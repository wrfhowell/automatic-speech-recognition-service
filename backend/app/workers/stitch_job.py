import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.core.logging import get_logger
from app.deidentification import deidentify
from app.models import (
    TERMINAL_CHUNK_STATUSES,
    TERMINAL_JOB_STATUSES,
    Chunk,
    ChunkStatus,
    Job,
    JobStatus,
)

log = get_logger(__name__)

_TERMINAL_JOB_VALUES = [s.value for s in TERMINAL_JOB_STATUSES]
_TERMINAL_CHUNK_VALUES = [s.value for s in TERMINAL_CHUNK_STATUSES]


def stitch_transcript(chunks: list[tuple[int, str, str | None]]) -> str:
    """Concatenate (ordinal, status, text) in ordinal order. Failed chunks
    become inline `[chunk N unavailable]` markers, N 1-based."""
    parts = []
    for ordinal, status, text in sorted(chunks, key=lambda c: c[0]):
        if status == ChunkStatus.COMPLETED.value and text is not None:
            parts.append(text.strip())
        else:
            parts.append(f"[chunk {ordinal + 1} unavailable]")
    return "\n\n".join(parts)


def terminal_job_status(chunk_statuses: list[str]) -> JobStatus:
    if all(s == ChunkStatus.COMPLETED.value for s in chunk_statuses):
        return JobStatus.COMPLETED
    if all(s == ChunkStatus.FAILED.value for s in chunk_statuses):
        return JobStatus.FAILED
    return JobStatus.COMPLETED_WITH_ERRORS


async def stitch_job(ctx: dict, job_id_str: str) -> None:
    """Idempotent: re-running against a terminal job is a no-op, and the
    final write is guarded so only the first stitch persists."""
    sessionmaker = ctx["sessionmaker"]
    job_id = uuid.UUID(job_id_str)

    async with sessionmaker() as session:
        job_status = (
            await session.execute(select(Job.status).where(Job.id == job_id))
        ).scalar_one_or_none()
        if job_status is None:
            log.error("stitch: job not found job_id=%s", job_id)
            return
        if job_status in _TERMINAL_JOB_VALUES:
            return
        chunk_rows = (
            await session.execute(
                select(Chunk.ordinal, Chunk.status, Chunk.transcript_text)
                .where(Chunk.job_id == job_id)
                .order_by(Chunk.ordinal)
            )
        ).all()

    statuses = [status for _, status, _ in chunk_rows]
    if any(s not in _TERMINAL_CHUNK_VALUES for s in statuses):
        # Defensive: spurious enqueue while chunks are still in flight.
        log.warning("stitch: non-terminal chunks remain job_id=%s", job_id)
        return

    raw = stitch_transcript([(o, s, t) for o, s, t in chunk_rows])
    final_status = terminal_job_status(statuses)

    # Model inference is CPU-bound; keep the event loop responsive. If deid
    # raises, this task raises: the job stays non-terminal and arq/the
    # reconciler retries — we never silently serve raw PHI.
    deid_result = await asyncio.to_thread(deidentify, raw)

    async with sessionmaker() as session:
        await session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.notin_(_TERMINAL_JOB_VALUES))
            .values(
                status=final_status.value,
                transcript_text=raw,
                transcript_deid=deid_result.masked_text,
                completed_time=datetime.now(UTC),
            )
        )
        await session.commit()

    log.info("job stitched job_id=%s status=%s", job_id, final_status.value)
