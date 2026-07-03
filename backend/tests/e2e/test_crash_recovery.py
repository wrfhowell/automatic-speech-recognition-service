"""The money shot, automated: kill -9 a worker mid-job, restart it, and the
job still completes. Permit TTLs reclaim the budget; arq redelivery plus
the reconciler recover the chunks; idempotent handlers make it safe."""

import asyncio
import time

from sqlalchemy import select

from app.models import Chunk, ChunkStatus, Job, JobStatus, TERMINAL_JOB_STATUSES
from app.workers.queueing import enqueue_chunk

TERMINAL = [s.value for s in TERMINAL_JOB_STATUSES]


async def _submit_job(e2e_db, arq_pool, paths: list[str]):
    async with e2e_db() as session:
        job = Job(user_id="e2e-crash", status=JobStatus.PENDING.value, pending_chunks=len(paths))
        session.add(job)
        await session.flush()
        chunk_ids = []
        for i, path in enumerate(paths):
            chunk = Chunk(
                job_id=job.id, ordinal=i, audio_path=path,
                status=ChunkStatus.PENDING.value,
            )
            session.add(chunk)
            await session.flush()
            chunk_ids.append(chunk.id)
        await session.commit()
        job_id = job.id
    for chunk_id in chunk_ids:
        await enqueue_chunk(arq_pool, chunk_id)
    return job_id


async def _job_status(e2e_db, job_id) -> str:
    async with e2e_db() as session:
        return (await session.scalars(select(Job.status).where(Job.id == job_id))).one()


async def _wait_for(predicate, timeout: float, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def test_kill_9_mid_job_then_restart_completes(e2e_db, arq_pool, spawn_worker):
    worker = spawn_worker()
    job_id = await _submit_job(
        e2e_db, arq_pool,
        ["audio-file-1.wav", "audio-file-2.wav", "audio-file-3.wav", "audio-file-4.wav"],
    )

    async def any_processing() -> bool:
        async with e2e_db() as session:
            statuses = (
                await session.scalars(select(Chunk.status).where(Chunk.job_id == job_id))
            ).all()
        return ChunkStatus.PROCESSING.value in statuses

    assert await _wait_for(any_processing, timeout=20), "chunks never started processing"

    worker.kill()  # SIGKILL: no cleanup, permits orphaned, tasks in flight
    worker.wait()
    await asyncio.sleep(2)
    assert await _job_status(e2e_db, job_id) not in TERMINAL, "job finished implausibly fast"

    spawn_worker()  # restart

    async def job_terminal() -> bool:
        return await _job_status(e2e_db, job_id) in TERMINAL

    assert await _wait_for(job_terminal, timeout=120), "job did not recover after restart"
    assert await _job_status(e2e_db, job_id) == JobStatus.COMPLETED.value

    async with e2e_db() as session:
        job = (await session.scalars(select(Job).where(Job.id == job_id))).one()
        assert job.transcript_text is not None
        assert "[chunk" not in job.transcript_text  # no chunk was lost
