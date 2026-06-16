import pytest
from wazo_dird_optimogo.engine import LookupEngine
from wazo_dird_optimogo.exceptions import (
    OptimoGoAuthError, OptimoGoUnavailable, OptimoGoLookupError,
)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.responses = []          # list of (body | Exception)
    def post(self, path, payload):
        self.calls.append((path, payload))
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_engine(client, clock, **over):
    cfg = dict(cache_ttl=60, negative_cache_ttl=30, cache_max_entries=100,
               breaker_failure_threshold=2, breaker_cooldown=30,
               ambiguous_prefix='Maybe: ', search_min_term_length=3,
               search_max_term_length=64, search_limit=25)
    cfg.update(over)
    return LookupEngine(client=client, config=cfg, time_func=clock)


def test_reverse_match_then_cached(clock):
    client = FakeClient()
    client.responses = [{'match': {'name': 'Acme', 'number': '+61399999999',
                                   'customer_id': 1, 'match_state': 'matched'}},
                        {'match': {'name': 'Acme', 'number': '+61399999999',
                                   'customer_id': 1, 'match_state': 'matched'}}]
    eng = make_engine(client, clock)
    first = eng.reverse('+61 3 9999 9999')
    assert first['display_name'] == 'Acme'
    second = eng.reverse('0399999999')   # different formatting; NOTE separate key
    # second normalizes differently -> second HTTP call would be needed, so prime it
    # Re-querying the SAME formatting hits cache:
    client.responses = []                # no more responses available
    cached = eng.reverse('+61 3 9999 9999')
    assert cached == first
    assert len(client.calls) == 2        # first '+613...', then '0399...'; the 3rd was cached


def test_reverse_skips_anonymous_without_http(clock):
    client = FakeClient()
    eng = make_engine(client, clock)
    assert eng.reverse('anonymous') is None
    assert client.calls == []


def test_reverse_no_match_is_negative_cached(clock):
    client = FakeClient()
    client.responses = [{'match': None}]
    eng = make_engine(client, clock)
    assert eng.reverse('+61399999999') is None
    assert eng.reverse('+61399999999') is None   # served from negative cache
    assert len(client.calls) == 1


def test_reverse_ambiguous_prefixed(clock):
    client = FakeClient()
    client.responses = [{'match': {'name': 'Acme', 'number': '+61', 'customer_id': 1,
                                   'match_state': 'ambiguous', 'candidate_count': 3}}]
    eng = make_engine(client, clock)
    assert eng.reverse('+61')['display_name'] == 'Maybe: Acme'


def test_auth_error_fails_open_no_breaker(clock):
    client = FakeClient()
    client.responses = [OptimoGoAuthError('401'), OptimoGoAuthError('401'),
                        OptimoGoAuthError('401')]
    eng = make_engine(client, clock)
    for _ in range(3):
        assert eng.reverse('+61399999999') is None
    assert len(client.calls) == 3        # breaker never opened on auth errors


def test_unavailable_opens_breaker(clock):
    client = FakeClient()
    client.responses = [OptimoGoUnavailable('503'), OptimoGoUnavailable('503')]
    eng = make_engine(client, clock)
    assert eng.reverse('+61399999999') is None
    assert eng.reverse('+61399999990') is None   # 2nd failure -> opens breaker
    # 3rd call: breaker open -> no HTTP attempt
    assert eng.reverse('+61399999991') is None
    assert len(client.calls) == 2


def test_breaker_probe_recovers(clock):
    client = FakeClient()
    client.responses = [OptimoGoUnavailable('503'), OptimoGoUnavailable('503'),
                        {'match': {'name': 'Acme', 'number': '+61', 'customer_id': 1,
                                   'match_state': 'matched'}}]
    eng = make_engine(client, clock)
    eng.reverse('+61399999999'); eng.reverse('+61399999990')   # opens breaker
    clock.advance(31)
    assert eng.reverse('+61399999991')['name'] == 'Acme'        # probe succeeds
    assert eng.reverse('+61399999991')['name'] == 'Acme'        # now cached/closed


def test_lookup_error_feeds_breaker(clock):
    client = FakeClient()
    client.responses = [OptimoGoLookupError('bad'), OptimoGoLookupError('bad')]
    eng = make_engine(client, clock)
    eng.reverse('+61399999999'); eng.reverse('+61399999990')
    assert eng.reverse('+61399999991') is None
    assert len(client.calls) == 2        # breaker opened after 2 malformed responses


def test_search_term_too_short_skips_http(clock):
    client = FakeClient()
    eng = make_engine(client, clock)
    assert eng.search('ab') == []
    assert client.calls == []


def test_search_returns_rows_and_caches(clock):
    client = FakeClient()
    client.responses = [{'results': [
        {'name': 'Acme', 'number': '+61399999999', 'customer_id': 1, 'contact_name': None}]}]
    eng = make_engine(client, clock)
    rows = eng.search('acme')
    assert rows[0]['id'] == 'customer:1:number:+61399999999'
    eng.search('ACME')                   # normalized to same key -> cached
    assert len(client.calls) == 1


def test_match_all_one_batch_call(clock):
    client = FakeClient()
    client.responses = [{'matches': {
        '+61399999999': {'name': 'Acme', 'number': '+61399999999', 'customer_id': 1,
                         'match_state': 'matched'},
        '+61400000000': None}}]
    eng = make_engine(client, clock)
    out = eng.match_all(['+61399999999', '+61400000000', 'anonymous'])
    assert set(out.keys()) == {'+61399999999'}        # unmatched + skipped omitted
    assert out['+61399999999']['name'] == 'Acme'
    assert client.calls[0][0] == '/reverse/batch'
    assert len(client.calls) == 1
