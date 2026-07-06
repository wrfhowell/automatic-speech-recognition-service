"""Operational counters for the demo console's System panel and the load
test: semaphore held/high-water-mark (the vendor-cap evidence of record),
arq queue depth, job/chunk status counts, and job latency percentiles.
Counts and numbers only — transcript text and audio paths never appear here.
"""

from arq.constants import default_queue_name
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.schemas import (
    ChunkStats,
    LatencyStats,
    LoadTestRequest,
    LoadTestResponse,
    OpsResponse,
    QueueStats,
    SemaphoreStats,
)
from app.core.semaphore import HWM_KEY, LEASES_KEY
from app.models import Chunk, ChunkStatus, Job, JobStatus

router = APIRouter()

# Every healthy mock path (audio-file-8.wav is the poison chunk): transient
# 1/20 failures get retried, so a burst must land all-COMPLETED.
HEALTHY_PATHS = [f"audio-file-{n}.wav" for n in (1, 2, 3, 4, 5, 6, 7, 9)]


@router.post("/ops/loadtest", status_code=202, response_model=LoadTestResponse)
async def loadtest(
    body: LoadTestRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoadTestResponse:
    """Burst-submit synthetic jobs so the System panel shows the semaphore
    working the vendor cap live. Same insert-then-enqueue path as /transcribe;
    the high-water mark is reset so the burst is measured from zero."""
    await request.app.state.redis.delete(HWM_KEY)

    paths = HEALTHY_PATHS[: body.chunks]
    job_ids = (
        (
            await session.execute(
                insert(Job).returning(Job.id),
                [
                    {
                        "user_id": "loadtest",
                        "status": JobStatus.PENDING.value,
                        "pending_chunks": len(paths),
                    }
                    for _ in range(body.jobs)
                ],
            )
        )
        .scalars()
        .all()
    )
    await session.execute(
        insert(Chunk),
        [
            {
                "job_id": job_id,
                "ordinal": i,
                "audio_path": path,
                "status": ChunkStatus.PENDING.value,
            }
            for job_id in job_ids
            for i, path in enumerate(paths)
        ],
    )
    await session.commit()

    enqueue = getattr(request.app.state, "enqueue_job_chunks", None)
    if enqueue is not None:
        for job_id in job_ids:
            await enqueue(job_id)

    return LoadTestResponse(
        jobs_submitted=len(job_ids), chunks_submitted=len(job_ids) * len(paths)
    )


@router.get("/ops", response_model=OpsResponse)
async def ops(
    request: Request, session: AsyncSession = Depends(get_session)
) -> OpsResponse:
    redis = request.app.state.redis
    held = await redis.zcard(LEASES_KEY)
    hwm = int(await redis.get(HWM_KEY) or 0)
    depth = await redis.llen(default_queue_name)

    jobs_by_status = dict(
        (await session.execute(select(Job.status, func.count()).group_by(Job.status)))
        .tuples()
        .all()
    )
    chunks_by_status = dict(
        (
            await session.execute(
                select(Chunk.status, func.count()).group_by(Chunk.status)
            )
        )
        .tuples()
        .all()
    )
    total_retries = await session.scalar(
        select(func.coalesce(func.sum(Chunk.attempts), 0))
    )

    duration = func.extract("epoch", Job.completed_time - Job.created_at)
    completed_jobs, p50, p95 = (
        await session.execute(
            select(
                func.count(),
                func.percentile_cont(0.5).within_group(duration),
                func.percentile_cont(0.95).within_group(duration),
            ).where(Job.completed_time.is_not(None))
        )
    ).one()

    return OpsResponse(
        semaphore=SemaphoreStats(
            held=held,
            high_water_mark=hwm,
            capacity=request.app.state.settings.asr_max_concurrency,
        ),
        queue=QueueStats(depth=depth),
        jobs=jobs_by_status,
        chunks=ChunkStats(by_status=chunks_by_status, total_retries=total_retries),
        latency=LatencyStats(
            completed_jobs=completed_jobs,
            p50_seconds=p50,
            p95_seconds=p95,
        ),
    )
