from wazo_dird_optimogo.breaker import CircuitBreaker


def test_closed_allows(clock):
    b = CircuitBreaker(failure_threshold=3, cooldown=30, time_func=clock)
    assert b.allow() is True


def test_opens_after_threshold(clock):
    b = CircuitBreaker(failure_threshold=3, cooldown=30, time_func=clock)
    for _ in range(3):
        b.record_failure()
    assert b.allow() is False        # open: blocks without an HTTP attempt


def test_probe_after_cooldown(clock):
    b = CircuitBreaker(failure_threshold=2, cooldown=30, time_func=clock)
    b.record_failure(); b.record_failure()
    assert b.allow() is False
    clock.advance(31)
    assert b.allow() is True          # one probe allowed
    assert b.allow() is False         # subsequent calls blocked until probe resolves


def test_success_closes(clock):
    b = CircuitBreaker(failure_threshold=2, cooldown=30, time_func=clock)
    b.record_failure(); b.record_failure()
    clock.advance(31)
    assert b.allow() is True
    b.record_success()
    assert b.allow() is True          # fully closed again
    assert b.allow() is True


def test_failed_probe_stays_open(clock):
    b = CircuitBreaker(failure_threshold=2, cooldown=30, time_func=clock)
    b.record_failure(); b.record_failure()
    clock.advance(31)
    assert b.allow() is True          # probe
    b.record_failure()                # probe failed
    assert b.allow() is False         # still open
    clock.advance(31)
    assert b.allow() is True          # next probe after another cooldown
