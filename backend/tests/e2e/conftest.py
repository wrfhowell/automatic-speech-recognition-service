"""E2E tests run against the live compose stack (postgres :5433,
redis :6379, mock-asr :3000) and real worker subprocesses. They are
skipped automatically when the stack isn't up: `make up` first."""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from app.config import Settings
from app.core.db import create_engine, create_sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2]

DATABASE_URL = os.environ.get(
    "E2E_DATABASE_URL", "postgresql+asyncpg://asr:asr@localhost:5433/asr"
)
REDIS_URL = os.environ.get("E2E_REDIS_URL", "redis://localhost:6379/0")
ASR_BASE_URL = os.environ.get("E2E_ASR_BASE_URL", "http://localhost:3000")

# Tuned for fast recovery in tests; correctness is identical at any values.
WORKER_ENV = {
    "DATABASE_URL": DATABASE_URL,
    "REDIS_URL": REDIS_URL,
    "ASR_BASE_URL": ASR_BASE_URL,
    "CHUNK_STUCK_SECONDS": "15",
    "RECONCILER_INTERVAL_SECONDS": "5",
}


def _reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    if _reachable("localhost", 5433) and _reachable("localhost", 6379) and _reachable(
        "localhost", 3000
    ):
        return
    skip = pytest.mark.skip(reason="compose stack not running (make up)")
    for item in items:
        if str(item.fspath).startswith(str(BACKEND_ROOT / "tests" / "e2e")):
            item.add_marker(skip)


@pytest.fixture
def spawn_worker():
    """Start a real arq worker subprocess; returns the spawn function.
    All spawned workers are killed at teardown."""
    procs: list[subprocess.Popen] = []

    def _spawn() -> subprocess.Popen:
        proc = subprocess.Popen(
            [str(Path(sys.executable).parent / "arq"), "app.workers.main.WorkerSettings"],
            cwd=BACKEND_ROOT,
            env={**os.environ, **WORKER_ENV},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        procs.append(proc)
        return proc

    yield _spawn
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


@pytest_asyncio.fixture
async def e2e_db():
    settings = Settings(database_url=DATABASE_URL, redis_url=REDIS_URL)
    engine = create_engine(settings)
    yield create_sessionmaker(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def arq_pool():
    from arq import create_pool
    from arq.connections import RedisSettings

    pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    yield pool
    await pool.aclose()
