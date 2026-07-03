"""Postgres-is-truth reconciler (arq cron). Recovery mechanism of record
for kill -9, Redis loss, and enqueue-after-commit gaps.

  A. stale PENDING  — enqueue was lost (or its arq job evaporated):
     touch updated_at + re-enqueue.
  B. stale PROCESSING — worker died mid-call. CHUNK_STUCK_SECONDS (120 s)
     exceeds lease TTL + max ASR call, so this never races a live call:
     reset to PENDING + re-enqueue.
  C. non-terminal job with pending_chunks=0 — crash in the
     commit->enqueue-stitch gap (or a failed stitch): enqueue stitch.

All re-enqueues dedupe against in-flight arq jobs via deterministic job
ids; FOR UPDATE SKIP LOCKED keeps concurrent reconcilers from fighting.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.logging import get_logger
from app.models import TERMINAL_JOB_STATUSES, Chunk, ChunkStatus, Job
from app.workers.queueing import enqueue_chunk, enqueue_stitch

log = get_logger(__name__)

_TERMINAL_JOB_VALUES = [s.value for s in TERMINAL_JOB_STATUSES]


async def reconcile(ctx: dict) -> None:
    sessionmaker = ctx["sessionmaker"]
    pool = ctx["arq_pool"]
    settings = ctx["settings"]
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=settings.chunk_stuck_seconds)

    # A + B: both end as freshly-touched PENDING + re-enqueue.
    async with sessionmaker() as session:
        stale = (
            await session.execute(
                select(Chunk.id, Chunk.status)
                .where(
                    Chunk.status.in_(
                        [ChunkStatus.PENDING.value, ChunkStatus.PROCESSING.value]
                    ),
                    Chunk.updated_at < cutoff,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
        if stale:
            await session.execute(
                update(Chunk)
                .where(Chunk.id.in_([cid for cid, _ in stale]))
                .values(status=ChunkStatus.PENDING.value, updated_at=now)
            )
        await session.commit()

    for chunk_id, status in stale:
        log.warning("reconciler: recovering stale chunk chunk_id=%s was=%s", chunk_id, status)
        await enqueue_chunk(pool, chunk_id)

    # C: all chunks done but no stitch landed.
    async with sessionmaker() as session:
        unstitched = (
            await session.scalars(
                select(Job.id)
                .where(Job.status.notin_(_TERMINAL_JOB_VALUES), Job.pending_chunks == 0)
                .with_for_update(skip_locked=True)
            )
        ).all()
        await session.commit()

    for job_id in unstitched:
        log.warning("reconciler: enqueueing missed stitch job_id=%s", job_id)
        await enqueue_stitch(pool, job_id)
