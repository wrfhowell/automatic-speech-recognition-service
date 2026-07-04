"""NF2 as a test, not a claim: burst 40 jobs x 8 chunks (320 ASR calls,
naive parallelism would be 320 concurrent) through two worker processes
sharing the global budget. The semaphore's high-water mark must never
exceed ASR_MAX_CONCURRENCY=90 (the mock exposes no in-flight counter, so
the hwm key — maintained atomically inside the acquire Lua script — is
the metric of record)."""

import asyncio
import time

from redis.asyncio import Redis
from sqlalchemy import func, select

from app.core.semaphore import HWM_KEY, LEASES_KEY
from app.models import Chunk, ChunkStatus, Job, JobStatus, TERMINAL_JOB_STATUSES
from app.workers.queueing import enqueue_chunk

from .conftest import REDIS_URL

N_JOBS = 40
CHUNKS_PER_JOB = 8
# Every path except the poison chunk: transient 1/20 failures get retried,
# so all jobs must land COMPLETED.
PATHS = [f"audio-file-{n}.wav" for n in (1, 2, 3, 4, 5, 6, 7, 9)]
TERMINAL = [s.value for s in TERMINAL_JOB_STATUSES]


async def test_burst_never_exceeds_global_budget(e2e_db, arq_pool, spawn_worker):
    redis = Redis.from_url(REDIS_URL)
    await redis.delete(HWM_KEY, LEASES_KEY)  # measure this burst only

    spawn_worker()
    spawn_worker()  # two processes: the budget is shared, not per-worker

    job_ids = []
    chunk_ids = []
    async with e2e_db() as session:
        for _ in range(N_JOBS):
            job = Job(
                user_id="e2e-burst",
                status=JobStatus.PENDING.value,
                pending_chunks=CHUNKS_PER_JOB,
            )
            session.add(job)
            await session.flush()
            job_ids.append(job.id)
            for i in range(CHUNKS_PER_JOB):
                chunk = Chunk(
                    job_id=job.id, ordinal=i, audio_path=PATHS[i],
                    status=ChunkStatus.PENDING.value,
                )
                session.add(chunk)
                await session.flush()
                chunk_ids.append(chunk.id)
        await session.commit()

    await asyncio.gather(*[enqueue_chunk(arq_pool, cid) for cid in chunk_ids])

    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        async with e2e_db() as session:
            remaining = await session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.id.in_(job_ids), Job.status.notin_(TERMINAL))
            )
        if remaining == 0:
            break
        await asyncio.sleep(2)
    assert remaining == 0, f"{remaining} jobs still non-terminal after 300s"

    async with e2e_db() as session:
        by_status = dict(
            (
                await session.execute(
                    select(Job.status, func.count())
                    .where(Job.id.in_(job_ids))
                    .group_by(Job.status)
                )
            ).all()
        )
    assert by_status == {JobStatus.COMPLETED.value: N_JOBS}, by_status

    hwm = int(await redis.get(HWM_KEY) or 0)
    assert hwm <= 90, f"budget breached: high-water mark {hwm} > 90"
    assert hwm >= 45, f"suspiciously low concurrency ({hwm}); test not exercising the cap"
    assert await redis.zcard(LEASES_KEY) == 0  # every permit released
    await redis.aclose()
