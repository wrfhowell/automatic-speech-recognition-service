"""In-process circuit breaker around the ASR client.

Sliding-window failure rate over transient failures (a 404 is a healthy
vendor answering; callers record it as success). One breaker per worker
process — a coordinated distributed breaker is a production follow-up;
per-process is enough to stop burning permits on a down vendor.

trip() force-opens regardless of window state: a 429 means our global
limiter's invariant is violated and we must back off hard immediately.
"""

import time
from collections import deque
from collections.abc import Callable
from enum import StrEnum


class BreakerState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self,
        *,
        window_seconds: float,
        min_requests: int,
        failure_rate_threshold: float,
        cooldown_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window = window_seconds
        self._min_requests = min_requests
        self._threshold = failure_rate_threshold
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._events: deque[tuple[float, bool]] = deque()  # (timestamp, ok)
        self._state = BreakerState.CLOSED
        self._opened_at = 0.0

    @property
    def state(self) -> BreakerState:
        return self._state

    def allow(self) -> bool:
        """Whether a request may proceed. In HALF_OPEN, exactly one probe is
        let through per transition from OPEN."""
        if self._state == BreakerState.CLOSED:
            return True
        if self._state == BreakerState.OPEN:
            if self._clock() - self._opened_at >= self._cooldown:
                self._state = BreakerState.HALF_OPEN
                return True
            return False
        return False  # HALF_OPEN: probe already in flight

    def record_success(self) -> None:
        if self._state == BreakerState.HALF_OPEN:
            self._state = BreakerState.CLOSED
            self._events.clear()
            return
        self._events.append((self._clock(), True))
        self._prune()

    def record_failure(self) -> None:
        if self._state == BreakerState.HALF_OPEN:
            self._open()
            return
        self._events.append((self._clock(), False))
        self._prune()
        if self._state == BreakerState.CLOSED:
            n = len(self._events)
            failures = sum(1 for _, ok in self._events if not ok)
            if n >= self._min_requests and failures / n >= self._threshold:
                self._open()

    def trip(self) -> None:
        self._open()

    def _open(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = self._clock()
        self._events.clear()

    def _prune(self) -> None:
        horizon = self._clock() - self._window
        while self._events and self._events[0][0] < horizon:
            self._events.popleft()
