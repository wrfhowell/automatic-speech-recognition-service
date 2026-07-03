import base64
import binascii
import json
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.schemas import ChunkInfo, SearchResponse, TranscriptResult
from app.core.logging import get_logger
from app.models import AuditAction, AuditLog, Chunk, Job, JobStatus

log = get_logger(__name__)

router = APIRouter(prefix="/transcript")


def encode_cursor(created_at: datetime, job_id: uuid.UUID) -> str:
    payload = json.dumps({"t": created_at.isoformat(), "id": str(job_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(payload["t"]), uuid.UUID(payload["id"])
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid cursor")


def _build_result(job: Job, chunks: list[Chunk], transcript_text: str | None) -> TranscriptResult:
    return TranscriptResult(
        job_id=job.id,
        user_id=job.user_id,
        transcript_text=transcript_text,
        chunk_statuses={c.audio_path: c.status for c in chunks},
        chunks=[
            ChunkInfo(
                ordinal=c.ordinal, audio_path=c.audio_path, status=c.status, attempts=c.attempts
            )
            for c in chunks
        ],
        job_status=job.status,
        completed_time=job.completed_time,
    )


# Registered before /{job_id} so "search" is never captured as a job id.
@router.get("/search", response_model=SearchResponse)
async def search_transcripts(
    session: Annotated[AsyncSession, Depends(get_session)],
    job_status: Annotated[str | None, Query(alias="jobStatus")] = None,
    user_id: Annotated[str | None, Query(alias="userId")] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResponse:
    if job_status is not None and job_status not in JobStatus.__members__:
        raise HTTPException(status_code=400, detail="invalid jobStatus")

    stmt = select(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)
    if job_status is not None:
        stmt = stmt.where(Job.status == job_status)
    if user_id is not None:
        stmt = stmt.where(Job.user_id == user_id)
    if cursor is not None:
        after_t, after_id = decode_cursor(cursor)
        stmt = stmt.where(tuple_(Job.created_at, Job.id) < (after_t, after_id))

    jobs = list((await session.scalars(stmt)).all())
    has_more = len(jobs) > limit
    jobs = jobs[:limit]

    chunks_by_job: dict[uuid.UUID, list[Chunk]] = defaultdict(list)
    if jobs:
        chunk_rows = await session.scalars(
            select(Chunk)
            .where(Chunk.job_id.in_([j.id for j in jobs]))
            .order_by(Chunk.job_id, Chunk.ordinal)
        )
        for c in chunk_rows:
            chunks_by_job[c.job_id].append(c)

    return SearchResponse(
        results=[_build_result(j, chunks_by_job[j.id], j.transcript_deid) for j in jobs],
        next_cursor=encode_cursor(jobs[-1].created_at, jobs[-1].id) if has_more else None,
    )


@router.get("/{job_id}", response_model=TranscriptResult)
async def get_transcript(
    job_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    view: str | None = None,
) -> TranscriptResult:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")

    chunks = list(
        (
            await session.scalars(
                select(Chunk).where(Chunk.job_id == job_id).order_by(Chunk.ordinal)
            )
        ).all()
    )

    if view == "raw":
        # Elevated-access path (§8.4): every raw read leaves an audit row.
        session.add(AuditLog(job_id=job_id, action=AuditAction.RAW_READ.value))
        await session.commit()
        log.info("raw transcript read job_id=%s", job_id)
        return _build_result(job, chunks, job.transcript_text)

    return _build_result(job, chunks, job.transcript_deid)
