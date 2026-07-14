import uuid
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from redis.asyncio import Redis

from app.api import health, ops, transcribe, transcript
from app.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import configure_logging
from app.workers.queueing import enqueue_pending_chunks


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = Redis.from_url(settings.redis_url)
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))

    async def enqueue_job_chunks(job_id: uuid.UUID) -> None:
        await enqueue_pending_chunks(app.state.arq_pool, app.state.sessionmaker, job_id)

    app.state.enqueue_job_chunks = enqueue_job_chunks
    yield
    await app.state.arq_pool.aclose()
    await app.state.redis.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Transcription Service", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(ops.router)
    app.include_router(transcribe.router)
    app.include_router(transcript.router)
    return app


app = create_app()
