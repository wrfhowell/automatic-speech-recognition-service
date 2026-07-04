"""Pure retry policy (§5.2). No I/O — trivially unit-testable.

Backoff is full-jitter exponential: uniform(0, min(cap, base * 2^(n-1))).
Attempt 1 retries within <= base (0.5 s) because the < 20 s happy-path
budget needs a fast first retry; later attempts back off harder.
"""

import random
from dataclasses import dataclass
from enum import StrEnum

from app.core.asr_client import AsrKind


class RetryAction(StrEnum):
    COMPLETE = "COMPLETE"           # persist transcript, chunk COMPLETED
    FAIL = "FAIL"                   # chunk FAILED, job continues
    RETRY = "RETRY"                 # re-enqueue with delay, attempt consumed
    BREAKER_TRIP = "BREAKER_TRIP"   # 429: limiter invariant violated


@dataclass(frozen=True)
class RetryDecision:
    action: RetryAction
    delay: float = 0.0


def backoff_delay(
    failed_attempts: int,
    *,
    base: float,
    cap: float,
    rng: random.Random | None = None,
) -> float:
    """Delay before the next attempt, given `failed_attempts` >= 1 so far."""
    upper = min(cap, base * 2 ** (failed_attempts - 1))
    return (rng or random).uniform(0, upper)


def decide(
    kind: AsrKind,
    failed_attempts: int,
    *,
    max_attempts: int,
    base: float,
    cap: float,
    rng: random.Random | None = None,
) -> RetryDecision:
    """Map an ASR outcome to the next action. `failed_attempts` counts this
    attempt if it failed."""
    match kind:
        case AsrKind.OK:
            return RetryDecision(RetryAction.COMPLETE)
        case AsrKind.NOT_FOUND:
            return RetryDecision(RetryAction.FAIL)
        case AsrKind.RATE_LIMITED:
            return RetryDecision(RetryAction.BREAKER_TRIP)
        case AsrKind.TRANSIENT:
            if failed_attempts >= max_attempts:
                return RetryDecision(RetryAction.FAIL)
            return RetryDecision(
                RetryAction.RETRY,
                delay=backoff_delay(failed_attempts, base=base, cap=cap, rng=rng),
            )
    raise ValueError(f"unhandled ASR kind: {kind}")
