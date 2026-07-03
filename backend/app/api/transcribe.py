import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.schemas import TranscribeRequest, TranscribeResponse
from app.core.logging import get_logger
from app.models import Chunk, ChunkStatus, Job, JobStatus

log = get_logger(__name__)

router = APIRouter()


@router.post("/transcribe", status_code=202, response_model=TranscribeResponse)
async def submit_transcription(
    body: TranscribeRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> TranscribeResponse:
    paths = body.audio_chunk_paths

    values: dict = {
        "user_id": body.user_id,
        "status": JobStatus.PENDING.value,
        "pending_chunks": len(paths),
        "idempotency_key": idempotency_key,
    }
    stmt = pg_insert(Job).values(**values).returning(Job.id)
    if idempotency_key is not None:
        # Race-safe idempotency: a concurrent duplicate blocks on the unique
        # index until the winner commits, then takes the DO NOTHING branch.
        stmt = stmt.on_conflict_do_nothing(index_elements=["idempotency_key"])

    job_id: uuid.UUID | None = (await session.execute(stmt)).scalar_one_or_none()
    if job_id is None:
        job_id = (
            await session.execute(
                select(Job.id).where(Job.idempotency_key == idempotency_key)
            )
        ).scalar_one()
        log.info("idempotent replay job_id=%s", job_id)
        return TranscribeResponse(job_id=job_id)

    await session.execute(
        insert(Chunk),
        [
            {
                "job_id": job_id,
                "ordinal": i,
                "audio_path": path,
                "status": ChunkStatus.PENDING.value,
            }
            for i, path in enumerate(paths)
        ],
    )
    await session.commit()

    # Strict commit -> enqueue ordering (reconciler query A covers a crash in
    # this gap). The queue is attached to app.state once workers exist.
    enqueue = getattr(request.app.state, "enqueue_job_chunks", None)
    if enqueue is not None:
        await enqueue(job_id)

    log.info("job accepted job_id=%s n_chunks=%d", job_id, len(paths))
    return TranscribeResponse(job_id=job_id)
