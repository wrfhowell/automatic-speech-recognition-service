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


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
