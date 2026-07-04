import asyncio
import time

import fakeredis.aioredis
import pytest

from app.core.semaphore import HWM_KEY, LEASES_KEY, AsrSemaphore


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


async def test_acquire_and_release(redis):
    sem = AsrSemaphore(redis, capacity=5, ttl_seconds=30)
    lease = await sem.acquire()
    assert lease is not None
    assert await sem.held() == 1
    await sem.release(lease)
    assert await sem.held() == 0


async def test_capacity_enforced(redis):
    sem = AsrSemaphore(redis, capacity=3, ttl_seconds=30)
    leases = [await sem.acquire() for _ in range(3)]
    assert all(leases)
    assert await sem.acquire() is None
    await sem.release(leases[0])
    assert await sem.acquire() is not None


async def test_expired_leases_are_reclaimed(redis):
    sem = AsrSemaphore(redis, capacity=1, ttl_seconds=30)
    # Simulate a crashed worker: lease whose expiry is already in the past.
    await redis.zadd(LEASES_KEY, {"dead-worker-lease": time.time() - 1})
    assert await sem.acquire() is not None
    assert await sem.held() == 1  # dead lease purged, new one present


async def test_release_of_expired_lease_is_safe(redis):
    sem = AsrSemaphore(redis, capacity=1, ttl_seconds=30)
    await sem.release("never-existed")  # logs a warning, no error
    assert await sem.held() == 0


async def test_high_water_mark_is_monotonic(redis):
    sem = AsrSemaphore(redis, capacity=10, ttl_seconds=30)
    leases = [await sem.acquire() for _ in range(7)]
    for lease in leases:
        await sem.release(lease)
    await sem.acquire()
    assert await sem.high_water_mark() == 7


async def test_cap_holds_under_contention(redis):
    sem = AsrSemaphore(redis, capacity=10, ttl_seconds=30)
    results = await asyncio.gather(*[sem.acquire() for _ in range(100)])
    granted = [r for r in results if r is not None]
    assert len(granted) == 10
    assert await sem.held() == 10
    assert int(await redis.get(HWM_KEY)) == 10
