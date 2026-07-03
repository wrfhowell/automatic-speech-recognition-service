from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.models import Chunk, Job, JobStatus
from app.workers.reconciler import reconcile

from .conftest import seed_job_with_chunks

STALE = datetime.now(UTC) - timedelta(seconds=600)


async def _age_chunks(app, chunk_ids, when=STALE):
    async with app.state.sessionmaker() as session:
        await session.execute(
            update(Chunk).where(Chunk.id.in_(chunk_ids)).values(updated_at=when)
        )
        await session.commit()


async def test_stale_pending_is_touched_and_reenqueued(app, worker_ctx):
    _, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PENDING"])
    await _age_chunks(app, chunk_ids)

    await reconcile(worker_ctx)

    enqueued = worker_ctx["arq_pool"].enqueued("process_chunk")
    assert [c[1] for c in enqueued] == [(str(chunk_ids[0]),)]
    async with app.state.sessionmaker() as session:
        chunk = await session.get(Chunk, chunk_ids[0])
        assert chunk.status == "PENDING"
        assert chunk.updated_at > STALE  # touched: won't re-trigger next cycle


async def test_stale_processing_is_reset_to_pending_and_reenqueued(app, worker_ctx):
    _, chunk_ids = await seed_job_with_chunks(app, chunk_statuses=["PROCESSING"])
    await _age_chunks(app, chunk_ids)

    await reconcile(worker_ctx)

    assert len(worker_ctx["arq_pool"].enqueued("process_chunk")) == 1
    async with app.state.sessionmaker() as session:
        assert (await session.get(Chunk, chunk_ids[0])).status == "PENDING"


async def test_fresh_and_terminal_chunks_are_left_alone(app, worker_ctx):
    _, fresh_ids = await seed_job_with_chunks(
        app, chunk_statuses=["PENDING", "PROCESSING"]
    )
    _, terminal_ids = await seed_job_with_chunks(
        app, chunk_statuses=["COMPLETED", "FAILED"]
    )
    await _age_chunks(app, terminal_ids)  # old but terminal

    await reconcile(worker_ctx)

    assert worker_ctx["arq_pool"].enqueued("process_chunk") == []
    async with app.state.sessionmaker() as session:
        assert (await session.get(Chunk, terminal_ids[0])).status == "COMPLETED"
        assert (await session.get(Chunk, terminal_ids[1])).status == "FAILED"


async def test_unstitched_job_gets_stitch_enqueued(app, worker_ctx):
    # Simulates a crash in the commit -> enqueue-stitch gap.
    job_id, _ = await seed_job_with_chunks(
        app, chunk_statuses=["COMPLETED", "COMPLETED"]
    )
    async with app.state.sessionmaker() as session:
        await session.execute(
            update(Job).where(Job.id == job_id).values(pending_chunks=0)
        )
        await session.commit()

    await reconcile(worker_ctx)

    stitches = worker_ctx["arq_pool"].enqueued("stitch_job")
    assert [s[1] for s in stitches] == [(str(job_id),)]


async def test_terminal_jobs_never_restitched(app, worker_ctx):
    job_id, _ = await seed_job_with_chunks(app, chunk_statuses=["COMPLETED"])
    async with app.state.sessionmaker() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(pending_chunks=0, status=JobStatus.COMPLETED.value)
        )
        await session.commit()

    await reconcile(worker_ctx)
    assert worker_ctx["arq_pool"].enqueued("stitch_job") == []
