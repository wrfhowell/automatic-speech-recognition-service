import pytest
from arq.worker import Retry

from app.core.asr_client import AsrKind, AsrResult
from app.core.breaker import BreakerState
from app.core.semaphore import AsrSemaphore
from app.models import Chunk, Job
from app.workers.process_chunk import process_chunk

from .conftest import FakeAsr, seed_job_with_chunks

OK = AsrResult(AsrKind.OK, transcript="fine")
TRANSIENT = AsrResult(AsrKind.TRANSIENT, detail="http 500")
NOT_FOUND = AsrResult(AsrKind.NOT_FOUND, detail="http 404")
RATE_LIMITED = AsrResult(AsrKind.RATE_LIMITED, detail="http 429")


async def _get_chunk(app, chunk_id) -> Chunk:
    async with app.state.sessionmaker() as session:
        return await session.get(Chunk, chunk_id)


async def test_transient_failure_reverts_to_pending_and_retries(app, worker_ctx):
    _, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [TRANSIENT]})

    with pytest.raises(Retry) as exc:
        await process_chunk(worker_ctx, str(chunk_ids[0]))
    assert exc.value.defer_score is not None  # deferred re-delivery

    chunk = await _get_chunk(app, chunk_ids[0])
    assert chunk.status == "PENDING"
    assert chunk.attempts == 1
    assert chunk.last_error == "http 500"
    assert await worker_ctx["semaphore"].held() == 0


async def test_transient_then_success_completes(app, worker_ctx):
    job_id, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [TRANSIENT, OK]})

    with pytest.raises(Retry):
        await process_chunk(worker_ctx, str(chunk_ids[0]))
    await process_chunk(worker_ctx, str(chunk_ids[0]))  # the deferred redelivery

    chunk = await _get_chunk(app, chunk_ids[0])
    assert chunk.status == "COMPLETED"
    assert chunk.attempts == 1
    assert chunk.transcript_text == "fine"


async def test_404_fails_immediately_no_retry(app, worker_ctx):
    job_id, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [NOT_FOUND]})

    await process_chunk(worker_ctx, str(chunk_ids[0]))  # no Retry raised

    chunk = await _get_chunk(app, chunk_ids[0])
    assert chunk.status == "FAILED"
    assert chunk.attempts == 0
    assert worker_ctx["asr"].calls == ["audio-file-1.wav"]
    assert await worker_ctx["semaphore"].held() == 0
    async with app.state.sessionmaker() as session:
        assert (await session.get(Job, job_id)).pending_chunks == 0
    assert len(worker_ctx["arq_pool"].enqueued("stitch_job")) == 1


async def test_attempt_exhaustion_fails_chunk_with_attempts_persisted(app, worker_ctx):
    _, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [TRANSIENT] * 4})

    for _ in range(3):
        with pytest.raises(Retry):
            await process_chunk(worker_ctx, str(chunk_ids[0]))
    await process_chunk(worker_ctx, str(chunk_ids[0]))  # 4th attempt exhausts

    chunk = await _get_chunk(app, chunk_ids[0])
    assert chunk.status == "FAILED"
    assert chunk.attempts == 4
    assert await worker_ctx["semaphore"].held() == 0


async def test_429_trips_breaker_without_consuming_attempt(app, worker_ctx):
    _, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [RATE_LIMITED]})

    with pytest.raises(Retry):
        await process_chunk(worker_ctx, str(chunk_ids[0]))

    assert worker_ctx["breaker"].state == BreakerState.OPEN
    chunk = await _get_chunk(app, chunk_ids[0])
    assert chunk.status == "PENDING"
    assert chunk.attempts == 0  # invariant violation is not the chunk's fault
    assert await worker_ctx["semaphore"].held() == 0


async def test_breaker_open_defers_before_taking_a_permit(app, worker_ctx):
    _, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [OK]})
    worker_ctx["breaker"].trip()

    with pytest.raises(Retry):
        await process_chunk(worker_ctx, str(chunk_ids[0]))

    assert worker_ctx["asr"].calls == []
    assert await worker_ctx["semaphore"].high_water_mark() == 0  # never acquired
    assert (await _get_chunk(app, chunk_ids[0])).status == "PENDING"


async def test_no_permit_defers_with_short_jitter(app, worker_ctx):
    import fakeredis.aioredis

    _, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [OK]})
    redis = fakeredis.aioredis.FakeRedis()
    worker_ctx["semaphore"] = AsrSemaphore(redis, capacity=0, ttl_seconds=30)

    with pytest.raises(Retry) as exc:
        await process_chunk(worker_ctx, str(chunk_ids[0]))

    assert worker_ctx["asr"].calls == []
    assert (await _get_chunk(app, chunk_ids[0])).status == "PENDING"
    assert exc.value.defer_score is not None
    await redis.aclose()
