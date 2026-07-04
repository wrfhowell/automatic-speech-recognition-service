"""Global ASR concurrency budget: a Redis counting semaphore with TTL leases.

All atomicity lives in one Lua script executed on the Redis server:
  1. purge expired leases (score = expiry, compared to Redis server time —
     worker clocks are never trusted),
  2. reject if the zset is at capacity,
  3. otherwise add the lease with score now+TTL and maintain a high-water
     mark key (asr:sem:hwm) — the concurrency-proof metric for e2e tests.

Crashed workers' permits self-expire via the TTL; the next acquirer purges
them. No janitor process. The 90-of-100 capacity margin absorbs the window
where an expired-but-unreleased permit briefly double-counts.
"""

import uuid

from redis.asyncio import Redis

from app.core.logging import get_logger

log = get_logger(__name__)

LEASES_KEY = "asr:sem:leases"
HWM_KEY = "asr:sem:hwm"

_ACQUIRE_LUA = """
local time = redis.call('TIME')
local now = tonumber(time[1]) + tonumber(time[2]) / 1000000
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[1]) then
  return 0
end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[3])
local holding = count + 1
local hwm = tonumber(redis.call('GET', KEYS[2]) or '0')
if holding > hwm then
  redis.call('SET', KEYS[2], holding)
end
return 1
"""


class AsrSemaphore:
    def __init__(self, redis: Redis, *, capacity: int, ttl_seconds: float) -> None:
        self._redis = redis
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._acquire_script = redis.register_script(_ACQUIRE_LUA)

    async def acquire(self) -> str | None:
        """Non-blocking. Returns a lease id, or None when at capacity —
        callers re-enqueue with a short delay instead of holding a slot."""
        lease_id = uuid.uuid4().hex
        granted = await self._acquire_script(
            keys=[LEASES_KEY, HWM_KEY],
            args=[self._capacity, self._ttl, lease_id],
        )
        return lease_id if granted == 1 else None

    async def release(self, lease_id: str) -> None:
        removed = await self._redis.zrem(LEASES_KEY, lease_id)
        if not removed:
            # Lease outlived its TTL (slow call or worker pause) and was
            # purged by another acquirer. Budget already reclaimed.
            log.warning("semaphore lease already expired lease_id=%s", lease_id)

    async def held(self) -> int:
        return await self._redis.zcard(LEASES_KEY)

    async def high_water_mark(self) -> int:
        raw = await self._redis.get(HWM_KEY)
        return int(raw) if raw else 0
