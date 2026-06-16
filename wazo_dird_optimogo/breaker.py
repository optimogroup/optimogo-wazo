import threading
import time as _time


class CircuitBreaker:
    """A minimal per-source circuit breaker.

    Closed: allow() is always True. After `failure_threshold` consecutive
    failures it opens for `cooldown` seconds, during which allow() returns
    False (fail-open immediately, no HTTP). After the cooldown a single probe
    is permitted; success closes the breaker, failure restarts the cooldown.
    Shared across worker threads -> lock-guarded.
    """

    def __init__(self, failure_threshold, cooldown, time_func=_time.monotonic):
        self._threshold = failure_threshold
        self._cooldown = cooldown
        self._time = time_func
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = None

    def allow(self):
        with self._lock:
            if self._opened_at is None:
                return True
            if self._time() - self._opened_at >= self._cooldown:
                self._opened_at = self._time()   # arm the next cooldown; lets exactly one probe through
                return True
            return False

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold and self._opened_at is None:
                self._opened_at = self._time()
