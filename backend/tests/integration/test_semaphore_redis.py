"""Hammer the semaphore against a real Redis: many concurrent workers
acquiring and releasing must never exceed capacity, and the recorded
high-water mark proves it after the fact."""

import asyncio
import random

import pytest
from redis.asyncio import Redis
from testcontainers.redis import RedisContainer

from app.core.semaphore import AsrSemaphore

CAPACITY = 90


@pytest.fixture(scope="module")
def redis_url():
    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


async def test_hammer_never_exceeds_capacity(redis_url):
    redis = Redis.from_url(redis_url)
    sem = AsrSemaphore(redis, capacity=CAPACITY, ttl_seconds=30)
    rng = random.Random(13)
    observed_max = 0

    async def worker() -> None:
        nonlocal observed_max
        for _ in range(5):
            lease = await sem.acquire()
            if lease is None:
                await asyncio.sleep(rng.uniform(0, 0.01))
                continue
            observed_max = max(observed_max, await sem.held())
            await asyncio.sleep(rng.uniform(0, 0.01))
            await sem.release(lease)

    await asyncio.gather(*[worker() for _ in range(300)])

    assert observed_max <= CAPACITY
    assert await sem.high_water_mark() <= CAPACITY
    assert await sem.high_water_mark() > 0
    assert await sem.held() == 0  # every exit path released
    await redis.aclose()
