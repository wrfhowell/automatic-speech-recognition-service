import random

import pytest

from app.core.asr_client import AsrKind
from app.core.retry import RetryAction, backoff_delay, decide

POLICY = {"max_attempts": 4, "base": 0.5, "cap": 8.0}


def test_ok_completes():
    assert decide(AsrKind.OK, 0, **POLICY).action == RetryAction.COMPLETE


def test_404_fails_immediately_without_retry():
    assert decide(AsrKind.NOT_FOUND, 1, **POLICY).action == RetryAction.FAIL


def test_429_trips_breaker():
    assert decide(AsrKind.RATE_LIMITED, 1, **POLICY).action == RetryAction.BREAKER_TRIP


def test_transient_retries_until_attempts_exhausted():
    rng = random.Random(13)
    for failed in (1, 2, 3):
        decision = decide(AsrKind.TRANSIENT, failed, **POLICY, rng=rng)
        assert decision.action == RetryAction.RETRY
    assert decide(AsrKind.TRANSIENT, 4, **POLICY).action == RetryAction.FAIL


@pytest.mark.parametrize(
    ("failed_attempts", "upper"),
    [(1, 0.5), (2, 1.0), (3, 2.0), (4, 4.0), (5, 8.0), (6, 8.0), (10, 8.0)],
)
def test_backoff_full_jitter_bounds(failed_attempts, upper):
    rng = random.Random(13)
    for _ in range(200):
        d = backoff_delay(failed_attempts, base=0.5, cap=8.0, rng=rng)
        assert 0 <= d <= upper


def test_first_retry_is_fast():
    # The <20 s budget requires the first retry to land within base delay.
    rng = random.Random(13)
    assert all(
        backoff_delay(1, base=0.5, cap=8.0, rng=rng) <= 0.5 for _ in range(1000)
    )
