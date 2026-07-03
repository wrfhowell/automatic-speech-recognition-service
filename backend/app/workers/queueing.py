"""Enqueue helpers. Deterministic arq job ids (chunk:{id}, stitch:{id}) +
keep_result=0 make duplicate enqueues from the API, retries, and the
reconciler dedupe naturally."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Chunk, ChunkStatus


def chunk_arq_id(chunk_id: uuid.UUID) -> str:
    return f"chunk:{chunk_id}"


def stitch_arq_id(job_id: uuid.UUID) -> str:
    return f"stitch:{job_id}"


async def enqueue_chunk(pool, chunk_id: uuid.UUID, defer_by: float | None = None) -> None:
    await pool.enqueue_job(
        "process_chunk", str(chunk_id), _job_id=chunk_arq_id(chunk_id), _defer_by=defer_by
    )


async def enqueue_stitch(pool, job_id: uuid.UUID) -> None:
    await pool.enqueue_job("stitch_job", str(job_id), _job_id=stitch_arq_id(job_id))


async def enqueue_pending_chunks(
    pool, sessionmaker: async_sessionmaker, job_id: uuid.UUID
) -> int:
    async with sessionmaker() as session:
        chunk_ids = (
            await session.scalars(
                select(Chunk.id).where(
                    Chunk.job_id == job_id, Chunk.status == ChunkStatus.PENDING.value
                )
            )
        ).all()
    for chunk_id in chunk_ids:
        await enqueue_chunk(pool, chunk_id)
    return len(chunk_ids)
