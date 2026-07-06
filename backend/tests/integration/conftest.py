import os
import subprocess
import sys
from pathlib import Path

import fakeredis.aioredis
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from app.config import Settings
from app.core.db import create_engine, create_sessionmaker
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def identity_deid(request, monkeypatch):
    """Integration tests exercise stitch orchestration, not the model:
    patch deid to identity so they stay fast and text-independent. Opt out
    with @pytest.mark.real_deid to run the committed student for real."""
    if request.node.get_closest_marker("real_deid"):
        return
    from app.deidentification import DeidResult

    monkeypatch.setattr(
        "app.workers.stitch_job.deidentify", lambda text: DeidResult(masked_text=text)
    )


@pytest.fixture(scope="session")
def database_url():
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        env = dict(os.environ, DATABASE_URL=url)
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT,
            env=env,
            check=True,
        )
        yield url


@pytest_asyncio.fixture
async def app(database_url):
    settings = Settings(database_url=database_url, redis_url="redis://unused:6379/0")
    application = create_app()
    engine = create_engine(settings)
    application.state.settings = settings
    application.state.engine = engine
    application.state.sessionmaker = create_sessionmaker(engine)
    application.state.redis = fakeredis.aioredis.FakeRedis()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE audit_log, chunks, jobs"))
    yield application
    await application.state.redis.aclose()
    await engine.dispose()


class FakeArqPool:
    """Records enqueue_job calls; enough queue for unit-of-work tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, str | None, float | None]] = []

    async def enqueue_job(self, function, *args, _job_id=None, _defer_by=None):
        self.calls.append((function, args, _job_id, _defer_by))
        return object()

    def enqueued(self, function: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == function]


class FakeAsr:
    """Scripted per-path outcomes: pop from a list per audio_path."""

    def __init__(self, script: dict[str, list]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []

    async def get_transcript(self, audio_path: str):
        self.calls.append(audio_path)
        return self.script[audio_path].pop(0)


async def seed_job_with_chunks(app, *, user_id="u1", chunk_statuses=None, paths=None):
    """Insert a job and its chunks; returns (job_id, [chunk_ids])."""
    from app.models import Chunk, Job, JobStatus

    statuses = chunk_statuses or ["PENDING", "PENDING"]
    paths = paths or [f"audio-file-{i + 1}.wav" for i in range(len(statuses))]
    async with app.state.sessionmaker() as session:
        job = Job(
            user_id=user_id,
            status=JobStatus.PENDING.value,
            pending_chunks=len(statuses),
        )
        session.add(job)
        await session.flush()
        chunk_ids = []
        for i, (status, path) in enumerate(zip(statuses, paths)):
            chunk = Chunk(job_id=job.id, ordinal=i, audio_path=path, status=status)
            session.add(chunk)
            await session.flush()
            chunk_ids.append(chunk.id)
        await session.commit()
        return job.id, chunk_ids


@pytest_asyncio.fixture
async def worker_ctx(app):
    """arq-style ctx dict wired to the test DB, fakeredis semaphore, fake
    ASR (tests fill in ctx['asr']), and a recording arq pool."""
    import random

    from app.core.breaker import CircuitBreaker
    from app.core.semaphore import AsrSemaphore

    settings = app.state.settings.model_copy(
        update={"retry_base_delay": 0.01, "retry_max_delay": 0.05}
    )
    redis = fakeredis.aioredis.FakeRedis()
    ctx = {
        "sessionmaker": app.state.sessionmaker,
        "settings": settings,
        "rng": random.Random(13),
        "arq_pool": FakeArqPool(),
        "semaphore": AsrSemaphore(
            redis,
            capacity=settings.asr_max_concurrency,
            ttl_seconds=settings.asr_lease_ttl_seconds,
        ),
        "breaker": CircuitBreaker(
            window_seconds=settings.breaker_window_seconds,
            min_requests=settings.breaker_min_requests,
            failure_rate_threshold=settings.breaker_failure_rate_threshold,
            cooldown_seconds=settings.breaker_cooldown_seconds,
        ),
        "asr": None,
    }
    yield ctx
    await redis.aclose()


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
