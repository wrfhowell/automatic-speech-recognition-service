from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All runtime knobs. Every value is overridable via environment variable
    of the same (upper-cased) name; see .env.example for the full surface."""

    # Host port 5433 (compose maps 5433->5432 to dodge local postgres installs)
    database_url: str = "postgresql+asyncpg://asr:asr@localhost:5433/asr"
    redis_url: str = "redis://localhost:6379/0"

    # ASR vendor
    asr_base_url: str = "http://localhost:3000"
    asr_timeout_seconds: float = 15.0

    # Global concurrency budget (vendor cap is 100; 10 held back for deploy
    # overlap, clock skew, and crash-orphaned permits). THE scaling knob (§7).
    asr_max_concurrency: int = 90
    asr_lease_ttl_seconds: int = 30

    # Retry policy (§5.2)
    retry_max_attempts: int = 4
    retry_base_delay: float = 0.5
    retry_max_delay: float = 8.0

    # Reconciler
    chunk_stuck_seconds: int = 120
    reconciler_interval_seconds: int = 60

    # Circuit breaker around the ASR client
    breaker_window_seconds: float = 30.0
    breaker_min_requests: int = 10
    breaker_failure_rate_threshold: float = 0.5
    breaker_cooldown_seconds: float = 15.0
    breaker_open_defer_seconds: float = 5.0

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
