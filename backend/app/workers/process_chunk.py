import uuid
from datetime import UTC, datetime

from arq.worker import Retry
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.asr_client import AsrKind
from app.core.logging import get_logger
from app.core.retry import RetryAction, decide
from app.models import (
    TERMINAL_CHUNK_STATUSES,
    Chunk,
    ChunkStatus,
    Job,
    JobStatus,
)
from app.workers.queueing import enqueue_stitch

log = get_logger(__name__)

_TERMINAL_CHUNK_VALUES = [s.value for s in TERMINAL_CHUNK_STATUSES]


def _now() -> datetime:
    return datetime.now(UTC)


async def finish_chunk(
    sessionmaker: async_sessionmaker,
    pool,
    chunk_id: uuid.UUID,
    terminal_status: ChunkStatus,
    *,
    transcript: str | None = None,
    error: str | None = None,
) -> None:
    """Move a chunk to a terminal state and decrement the job's
    pending_chunks — in ONE transaction (the core correctness pattern).

    The guarded UPDATE makes the terminal transition exactly-once: on a
    redelivered task no row transitions, so no decrement happens. The job
    row-lock serializes decrements, so exactly one caller observes 0 and
    enqueues the stitch (after commit; reconciler query C covers a crash
    in the commit->enqueue gap)."""
    async with sessionmaker() as session:
        transitioned = (
            await session.execute(
                update(Chunk)
                .where(Chunk.id == chunk_id, Chunk.status.notin_(_TERMINAL_CHUNK_VALUES))
                .values(
                    status=terminal_status.value,
                    transcript_text=transcript,
                    last_error=error,
                    updated_at=_now(),
                )
                .returning(Chunk.job_id)
            )
        ).first()
        if transitioned is None:
            await session.rollback()
            return
        job_id = transitioned[0]
        remaining = (
            await session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(pending_chunks=Job.pending_chunks - 1)
                .returning(Job.pending_chunks)
            )
        ).scalar_one()
        await session.commit()

    log.info(
        "chunk finished chunk_id=%s status=%s remaining=%d",
        chunk_id, terminal_status.value, remaining,
    )
    if remaining == 0:
        await enqueue_stitch(pool, job_id)


async def _revert_to_pending(
    sessionmaker: async_sessionmaker, chunk_id: uuid.UUID, *, error: str, consume_attempt: bool
) -> None:
    async with sessionmaker() as session:
        values = {"status": ChunkStatus.PENDING.value, "last_error": error, "updated_at": _now()}
        if consume_attempt:
            values["attempts"] = Chunk.attempts + 1
        await session.execute(
            update(Chunk)
            .where(Chunk.id == chunk_id, Chunk.status == ChunkStatus.PROCESSING.value)
            .values(**values)
        )
        await session.commit()


async def process_chunk(ctx: dict, chunk_id_str: str) -> None:
    """One ASR attempt for one chunk. At-least-once delivery is made safe by
    the idempotency gate and guarded transitions; retries are arq Retry
    re-deliveries with defer (attempt counts live in Postgres, not arq).

    Never holds a DB transaction or a queue slot across the ASR call; the
    semaphore permit is released on every exit path."""
    sessionmaker = ctx["sessionmaker"]
    settings = ctx["settings"]
    rng = ctx["rng"]
    chunk_id = uuid.UUID(chunk_id_str)

    # Idempotency gate: makes redelivery (arq at-least-once, reconciler) safe.
    async with sessionmaker() as session:
        row = (
            await session.execute(
                select(Chunk.status, Chunk.attempts, Chunk.audio_path, Chunk.job_id).where(
                    Chunk.id == chunk_id
                )
            )
        ).first()
    if row is None:
        log.error("chunk not found chunk_id=%s", chunk_id)
        return
    status, attempts, audio_path, job_id = row
    if status in _TERMINAL_CHUNK_VALUES:
        log.info("chunk already terminal, skipping chunk_id=%s", chunk_id)
        return

    if not ctx["breaker"].allow():
        log.warning("breaker open, deferring chunk_id=%s", chunk_id)
        raise Retry(defer=settings.breaker_open_defer_seconds)

    lease = await ctx["semaphore"].acquire()
    if lease is None:
        # At the global budget: come back shortly rather than hold a slot.
        raise Retry(defer=rng.uniform(0.5, 2.0))

    try:
        # Guarded claim: only a PENDING chunk may start PROCESSING.
        async with sessionmaker() as session:
            claimed = (
                await session.execute(
                    update(Chunk)
                    .where(Chunk.id == chunk_id, Chunk.status == ChunkStatus.PENDING.value)
                    .values(status=ChunkStatus.PROCESSING.value, updated_at=_now())
                    .returning(Chunk.id)
                )
            ).first()
            if claimed is not None:
                await session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == JobStatus.PENDING.value)
                    .values(status=JobStatus.PROCESSING.value)
                )
            await session.commit()
        if claimed is None:
            return  # concurrent duplicate holds it; let that delivery finish

        result = await ctx["asr"].get_transcript(audio_path)
    finally:
        await ctx["semaphore"].release(lease)

    if result.kind == AsrKind.TRANSIENT:
        ctx["breaker"].record_failure()
        attempts += 1  # this failed attempt, persisted below
    else:
        # 404 included: the vendor answered; the breaker tracks vendor
        # health, not per-path permanent failures.
        ctx["breaker"].record_success()

    decision = decide(
        result.kind,
        attempts,
        max_attempts=settings.retry_max_attempts,
        base=settings.retry_base_delay,
        cap=settings.retry_max_delay,
        rng=rng,
    )

    match decision.action:
        case RetryAction.COMPLETE:
            await finish_chunk(
                sessionmaker, ctx["arq_pool"], chunk_id, ChunkStatus.COMPLETED,
                transcript=result.transcript,
            )
        case RetryAction.FAIL:
            await finish_chunk(
                sessionmaker, ctx["arq_pool"], chunk_id, ChunkStatus.FAILED,
                error=result.detail,
            )
            log.warning("chunk failed permanently chunk_id=%s attempts=%d", chunk_id, attempts)
        case RetryAction.RETRY:
            await _revert_to_pending(
                sessionmaker, chunk_id, error=result.detail, consume_attempt=True
            )
            log.info(
                "chunk transient failure chunk_id=%s attempts=%d retry_in=%.2fs",
                chunk_id, attempts, decision.delay,
            )
            raise Retry(defer=decision.delay)
        case RetryAction.BREAKER_TRIP:
            # Our global limiter's invariant is violated — this must never
            # happen. Trip hard, long defer, and do NOT consume an attempt.
            ctx["breaker"].trip()
            log.error(
                "ASR returned 429: limiter invariant violated chunk_id=%s", chunk_id
            )
            await _revert_to_pending(
                sessionmaker, chunk_id, error=result.detail, consume_attempt=False
            )
            raise Retry(defer=settings.breaker_cooldown_seconds)
