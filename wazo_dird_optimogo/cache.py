import threading
import time as _time
from collections import OrderedDict

_MISS = object()


class TTLCache:
    """Thread-safe, bounded, lazily-expiring TTL cache.

    Values may be any object, including None (a cached negative result).
    get() returns (hit: bool, value). A single instance is shared across
    wazo-dird worker threads, so every access is lock-guarded.
    """

    def __init__(self, max_entries, time_func=_time.monotonic):
        self._max = max_entries
        self._time = time_func
        self._lock = threading.Lock()
        self._data = OrderedDict()  # key -> (expires_at, value)

    def get(self, key):
        now = self._time()
        with self._lock:
            entry = self._data.get(key, _MISS)
            if entry is _MISS:
                return (False, None)
            expires_at, value = entry
            if expires_at <= now:
                del self._data[key]
                return (False, None)
            self._data.move_to_end(key)
            return (True, value)

    def set(self, key, value, ttl):
        if ttl <= 0:
            return
        expires_at = self._time() + ttl
        with self._lock:
            self._data[key] = (expires_at, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
