import random

from arq.connections import RedisSettings

from app.config import get_settings
from app.core.asr_client import AsrClient
from app.core.breaker import CircuitBreaker
from app.core.db import create_engine, create_sessionmaker
from app.core.logging import configure_logging, get_logger
from app.core.semaphore import AsrSemaphore
from app.workers.process_chunk import process_chunk
from app.workers.stitch_job import stitch_job

log = get_logger(__name__)


async def startup(ctx: dict) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings)
    ctx["engine"] = engine
    ctx["sessionmaker"] = create_sessionmaker(engine)
    ctx["settings"] = settings
    ctx["rng"] = random.Random()
    # arq provides ctx["redis"] (ArqRedis extends Redis): one connection pool
    # for the queue, the semaphore, and enqueues.
    ctx["arq_pool"] = ctx["redis"]
    ctx["semaphore"] = AsrSemaphore(
        ctx["redis"],
        capacity=settings.asr_max_concurrency,
        ttl_seconds=settings.asr_lease_ttl_seconds,
    )
    ctx["asr"] = AsrClient(settings.asr_base_url, settings.asr_timeout_seconds)
    ctx["breaker"] = CircuitBreaker(
        window_seconds=settings.breaker_window_seconds,
        min_requests=settings.breaker_min_requests,
        failure_rate_threshold=settings.breaker_failure_rate_threshold,
        cooldown_seconds=settings.breaker_cooldown_seconds,
    )
    log.info("worker started asr_max_concurrency=%d", settings.asr_max_concurrency)


async def shutdown(ctx: dict) -> None:
    await ctx["asr"].aclose()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [process_chunk, stitch_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # Retries are governed by attempts in Postgres (retry_max_attempts) and
    # deferred re-deliveries also consume arq tries, so keep this effectively
    # unbounded. keep_result=0: finished job ids leave no residue, so
    # reconciler re-enqueues of chunk:{id}/stitch:{id} are never blocked.
    max_tries = 1000
    keep_result = 0
    job_timeout = 60
    # Comfortably holds the whole vendor budget in one process (I/O-bound).
    max_jobs = 200
