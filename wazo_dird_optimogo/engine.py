import logging

from .breaker import CircuitBreaker
from .cache import TTLCache
from .exceptions import OptimoGoAuthError, OptimoGoError
from .inputs import (
    normalize_number_key, normalize_term_key, should_skip_number, validate_term,
)
from .mapping import map_match, map_results

logger = logging.getLogger(__name__)


class LookupEngine:
    """Bounded fail-open lookups: cache -> breaker -> HTTP -> mapping.

    Returns plain field dicts (or None / []); the SPI layer wraps them into
    wazo-dird result objects. No wazo_dird import here.
    """

    def __init__(self, client, config, time_func=None):
        self._client = client
        self._cfg = config
        kw = {} if time_func is None else {'time_func': time_func}
        self._cache = TTLCache(max_entries=config['cache_max_entries'], **kw)
        self._breaker = CircuitBreaker(
            failure_threshold=config['breaker_failure_threshold'],
            cooldown=config['breaker_cooldown'], **kw)

    # ---- reverse (caller ID) -------------------------------------------------
    def reverse(self, number):
        if should_skip_number(number):
            return None
        key = ('reverse', normalize_number_key(number))
        hit, value = self._cache.get(key)
        if hit:
            return value
        body = self._request('/reverse', {'number': number})
        if body is _FAILED:
            return None
        match = body.get('match') if isinstance(body, dict) else None
        fields = map_match(match, self._cfg['ambiguous_prefix'])
        ttl = self._cfg['cache_ttl'] if fields else self._cfg['negative_cache_ttl']
        self._cache.set(key, fields, ttl)
        return fields

    # ---- forward search ------------------------------------------------------
    def search(self, term):
        clean = validate_term(term, self._cfg['search_min_term_length'],
                              self._cfg['search_max_term_length'])
        if clean is None:
            return []
        key = ('search', normalize_term_key(clean), self._cfg['search_limit'])
        hit, value = self._cache.get(key)
        if hit:
            return value
        body = self._request('/search', {'term': clean, 'limit': self._cfg['search_limit']})
        if body is _FAILED:
            return []
        rows = body.get('results') if isinstance(body, dict) else None
        results = map_results(rows or [])
        ttl = self._cfg['cache_ttl'] if results else self._cfg['negative_cache_ttl']
        self._cache.set(key, results, ttl)
        return results

    # ---- batch reverse -------------------------------------------------------
    def match_all(self, numbers):
        wanted = [n for n in numbers if not should_skip_number(n)]
        if not wanted:
            return {}
        body = self._request('/reverse/batch', {'numbers': wanted})
        if body is _FAILED:
            return {}
        matches = body.get('matches') if isinstance(body, dict) else None
        out = {}
        for number, match in (matches or {}).items():
            fields = map_match(match, self._cfg['ambiguous_prefix'])
            if fields:
                out[number] = fields
        return out

    # ---- shared request path -------------------------------------------------
    def _request(self, path, payload):
        if not self._breaker.allow():
            return _FAILED
        try:
            body = self._client.post(path, payload)
        except OptimoGoAuthError:
            logger.error('optimogo auth failed on %s (check the source api_key)', path)
            return _FAILED                       # no breaker, no cache
        except OptimoGoError as e:
            self._breaker.record_failure()
            logger.warning('optimogo lookup failed on %s: %s', path, type(e).__name__)
            return _FAILED                       # breaker fed, no cache
        self._breaker.record_success()
        return body

    def close(self):
        close = getattr(self._client, 'close', None)
        if close:
            close()


_FAILED = object()   # sentinel: request failed (distinct from a valid empty body)
