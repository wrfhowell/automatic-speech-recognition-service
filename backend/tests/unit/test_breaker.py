from app.core.breaker import BreakerState, CircuitBreaker


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_breaker(clock, **overrides):
    kwargs = {
        "window_seconds": 30.0,
        "min_requests": 10,
        "failure_rate_threshold": 0.5,
        "cooldown_seconds": 15.0,
        "clock": clock,
    }
    kwargs.update(overrides)
    return CircuitBreaker(**kwargs)


def test_stays_closed_below_min_requests():
    clock = FakeClock()
    b = make_breaker(clock)
    for _ in range(9):
        b.record_failure()
    assert b.state == BreakerState.CLOSED
    assert b.allow()


def test_opens_at_failure_rate_threshold():
    clock = FakeClock()
    b = make_breaker(clock)
    for _ in range(5):
        b.record_success()
    for _ in range(5):
        b.record_failure()
    assert b.state == BreakerState.OPEN
    assert not b.allow()


def test_old_events_fall_out_of_window():
    clock = FakeClock()
    b = make_breaker(clock)
    for _ in range(9):
        b.record_failure()
    clock.advance(31.0)  # everything above expires
    b.record_failure()  # 1 failure in window, n=1 < min_requests
    assert b.state == BreakerState.CLOSED


def test_trip_opens_immediately():
    clock = FakeClock()
    b = make_breaker(clock)
    b.trip()
    assert b.state == BreakerState.OPEN
    assert not b.allow()


def test_half_open_allows_single_probe_then_closes_on_success():
    clock = FakeClock()
    b = make_breaker(clock)
    b.trip()
    clock.advance(15.0)
    assert b.allow()  # the probe
    assert b.state == BreakerState.HALF_OPEN
    assert not b.allow()  # only one probe
    b.record_success()
    assert b.state == BreakerState.CLOSED
    assert b.allow()


def test_half_open_reopens_on_probe_failure():
    clock = FakeClock()
    b = make_breaker(clock)
    b.trip()
    clock.advance(15.0)
    assert b.allow()
    b.record_failure()
    assert b.state == BreakerState.OPEN
    assert not b.allow()
    clock.advance(14.9)
    assert not b.allow()
    clock.advance(0.1)
    assert b.allow()  # next probe after full cooldown
