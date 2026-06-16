from wazo_dird_optimogo.cache import TTLCache


def test_miss_then_hit(clock):
    c = TTLCache(max_entries=10, time_func=clock)
    assert c.get('k') == (False, None)
    c.set('k', {'name': 'Acme'}, ttl=60)
    assert c.get('k') == (True, {'name': 'Acme'})


def test_expiry(clock):
    c = TTLCache(max_entries=10, time_func=clock)
    c.set('k', 'v', ttl=60)
    clock.advance(59)
    assert c.get('k') == (True, 'v')
    clock.advance(2)              # now 61s elapsed
    assert c.get('k') == (False, None)


def test_negative_value_is_cacheable(clock):
    c = TTLCache(max_entries=10, time_func=clock)
    c.set('k', None, ttl=30)       # cached "no match"
    assert c.get('k') == (True, None)


def test_zero_ttl_does_not_store(clock):
    c = TTLCache(max_entries=10, time_func=clock)
    c.set('k', 'v', ttl=0)
    assert c.get('k') == (False, None)


def test_lru_eviction(clock):
    c = TTLCache(max_entries=2, time_func=clock)
    c.set('a', 1, ttl=60)
    c.set('b', 2, ttl=60)
    c.get('a')                     # 'a' now most-recently used
    c.set('c', 3, ttl=60)          # evicts least-recently used 'b'
    assert c.get('b') == (False, None)
    assert c.get('a') == (True, 1)
    assert c.get('c') == (True, 3)
