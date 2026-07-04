import asyncio

from sqlalchemy import select

from app.core.asr_client import AsrKind, AsrResult
from app.models import Chunk, ChunkStatus, Job
from app.workers.process_chunk import finish_chunk, process_chunk
from app.workers.stitch_job import stitch_job

from .conftest import FakeAsr, seed_job_with_chunks

OK1 = AsrResult(AsrKind.OK, transcript="first part")
OK2 = AsrResult(AsrKind.OK, transcript="second part")


async def test_happy_path_two_chunks_to_completed_job(app, worker_ctx):
    job_id, chunk_ids = await seed_job_with_chunks(app)
    worker_ctx["asr"] = FakeAsr(
        {"audio-file-1.wav": [OK1], "audio-file-2.wav": [OK2]}
    )

    for chunk_id in chunk_ids:
        await process_chunk(worker_ctx, str(chunk_id))

    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.pending_chunks == 0
        chunks = [await session.get(Chunk, cid) for cid in chunk_ids]
        assert all(c.status == "COMPLETED" for c in chunks)
        assert chunks[0].transcript_text == "first part"

    stitches = worker_ctx["arq_pool"].enqueued("stitch_job")
    assert len(stitches) == 1
    assert stitches[0][1] == (str(job_id),)

    await stitch_job(worker_ctx, str(job_id))
    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.status == "COMPLETED"
        assert job.transcript_text == "first part\n\nsecond part"
        assert job.transcript_deid == "first part\n\nsecond part"  # identity-patched deid
        assert job.completed_time is not None


async def test_job_transitions_to_processing_on_first_claim(app, worker_ctx):
    job_id, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [OK1]})
    await process_chunk(worker_ctx, str(chunk_ids[0]))
    # job went PENDING -> PROCESSING during the claim, then stitch finishes it
    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.status == "PROCESSING"


async def test_redelivery_of_terminal_chunk_never_calls_asr(app, worker_ctx):
    job_id, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [OK1]})
    await process_chunk(worker_ctx, str(chunk_ids[0]))
    await process_chunk(worker_ctx, str(chunk_ids[0]))  # redelivery

    assert worker_ctx["asr"].calls == ["audio-file-1.wav"]
    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.pending_chunks == 0  # no double decrement


async def test_permit_released_after_success(app, worker_ctx):
    _, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    worker_ctx["asr"] = FakeAsr({"audio-file-1.wav": [OK1]})
    await process_chunk(worker_ctx, str(chunk_ids[0]))
    assert await worker_ctx["semaphore"].held() == 0


async def test_concurrent_finish_chunk_exactly_one_sees_zero(app, worker_ctx):
    n = 10
    job_id, chunk_ids = await seed_job_with_chunks(
        app, chunk_statuses=["PROCESSING"] * n
    )
    await asyncio.gather(
        *[
            finish_chunk(
                app.state.sessionmaker,
                worker_ctx["arq_pool"],
                cid,
                ChunkStatus.COMPLETED,
                transcript=f"part {i}",
            )
            for i, cid in enumerate(chunk_ids)
        ]
    )
    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.pending_chunks == 0
    assert len(worker_ctx["arq_pool"].enqueued("stitch_job")) == 1


async def test_finish_chunk_redelivery_does_not_double_decrement(app, worker_ctx):
    job_id, chunk_ids = await seed_job_with_chunks(
        app, chunk_statuses=["PROCESSING", "PROCESSING"]
    )
    for _ in range(3):  # redeliveries of the same terminal transition
        await finish_chunk(
            app.state.sessionmaker, worker_ctx["arq_pool"], chunk_ids[0],
            ChunkStatus.COMPLETED, transcript="x",
        )
    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.pending_chunks == 1
    assert len(worker_ctx["arq_pool"].enqueued("stitch_job")) == 0


async def test_stitch_is_idempotent(app, worker_ctx):
    job_id, _ = await seed_job_with_chunks(
        app, chunk_statuses=["COMPLETED", "FAILED"]
    )
    async with app.state.sessionmaker() as session:
        for chunk in (
            await session.scalars(select(Chunk).where(Chunk.job_id == job_id))
        ).all():
            chunk.transcript_text = "text" if chunk.status == "COMPLETED" else None
        await session.commit()

    await stitch_job(worker_ctx, str(job_id))
    async with app.state.sessionmaker() as session:
        first = (await session.get(Job, job_id)).completed_time
    await stitch_job(worker_ctx, str(job_id))
    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.completed_time == first
        assert job.status == "COMPLETED_WITH_ERRORS"
        assert job.transcript_text == "text\n\n[chunk 2 unavailable]"


async def test_stitch_bails_out_when_chunks_still_in_flight(app, worker_ctx):
    job_id, _ = await seed_job_with_chunks(
        app, chunk_statuses=["COMPLETED", "PROCESSING"]
    )
    await stitch_job(worker_ctx, str(job_id))
    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.status == "PENDING"
        assert job.transcript_text is None
