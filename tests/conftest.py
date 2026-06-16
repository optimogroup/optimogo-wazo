import pytest


class FakeClock:
    """Deterministic monotonic clock for cache/breaker tests."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def valid_config():
    """A minimal valid source-config dict as wazo-dird would pass it in args['config']."""
    return {
        'name': 'optimogo',
        'lookup_url': 'https://opt.example.com/api/wazo/dird/acme',
        'api_key': 'secret-key',
    }
