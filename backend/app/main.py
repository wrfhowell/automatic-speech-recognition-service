from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api import health, transcribe, transcript
from app.config import get_settings
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = Redis.from_url(settings.redis_url)
    yield
    await app.state.redis.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Transcription Service", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(transcribe.router)
    app.include_router(transcript.router)
    return app


app = create_app()
