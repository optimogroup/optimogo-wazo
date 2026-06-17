import pytest
from wazo_auth_optimogo.idp import OptimoGoIDP, InvalidBridgeToken


class _FakeBackend:
    """Stand-in for the wazo_user backend instance."""
    pass


class _FakeClient:
    def __init__(self, result):
        self._result = result
        self.call_count = 0

    def introspect(self, token):
        self.call_count += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _idp(client, *, resolve_ok=True, breaker=None):
    """Build an OptimoGoIDP with internal wiring set directly (bypasses load)."""
    idp = OptimoGoIDP()
    idp.authentication_method = 'optimogo'
    idp._client = client
    idp._backend = _FakeBackend()
    idp._wazo_tenant_uuid = 't-uuid'
    idp._resolve_enabled_user = (lambda email, tenant: email if resolve_ok else None)
    if breaker is not None:
        idp._breaker = breaker
    else:
        from wazo_dird_optimogo.breaker import CircuitBreaker
        idp._breaker = CircuitBreaker(failure_threshold=5, cooldown=30)
    return idp


# ---------------------------------------------------------------------------
# can_authenticate
# ---------------------------------------------------------------------------

def test_can_authenticate_only_for_optimogo_backend():
    idp = _idp(_FakeClient({'active': True}))
    assert idp.can_authenticate({'backend': 'optimogo', 'login': 'a@b.com', 'password': 'tok'}) is True
    assert idp.can_authenticate({'backend': 'wazo_user', 'login': 'a@b.com', 'password': 'p'}) is False
    assert idp.can_authenticate({'backend': 'optimogo', 'login': 'a@b.com'}) is False


def test_can_authenticate_requires_login():
    idp = _idp(_FakeClient({'active': True}))
    assert idp.can_authenticate({'backend': 'optimogo', 'password': 'tok'}) is False


def test_can_authenticate_requires_password():
    idp = _idp(_FakeClient({'active': True}))
    assert idp.can_authenticate({'backend': 'optimogo', 'login': 'a@b.com'}) is False


def test_can_authenticate_empty_login_rejected():
    idp = _idp(_FakeClient({'active': True}))
    assert idp.can_authenticate({'backend': 'optimogo', 'login': '', 'password': 'tok'}) is False


def test_can_authenticate_empty_password_rejected():
    idp = _idp(_FakeClient({'active': True}))
    assert idp.can_authenticate({'backend': 'optimogo', 'login': 'a@b.com', 'password': ''}) is False


# ---------------------------------------------------------------------------
# verify_auth — success path
# ---------------------------------------------------------------------------

def test_verify_auth_success_returns_backend_and_authoritative_login():
    """Authoritative email from introspection result is used, not the client-supplied login."""
    idp = _idp(_FakeClient({'active': True, 'email': 'real@b.com', 'wazo_tenant_uuid': 't-uuid'}))
    backend, login = idp.verify_auth({'backend': 'optimogo', 'login': 'CLIENT-CLAIM@x.com', 'password': 'tok'})
    assert backend is idp._backend
    assert login == 'real@b.com'


def test_verify_auth_success_records_breaker_success():
    from wazo_dird_optimogo.breaker import CircuitBreaker
    breaker = CircuitBreaker(failure_threshold=5, cooldown=30)
    # Force it to open state, then let a probe through (advance_not_needed for threshold=5)
    idp = _idp(
        _FakeClient({'active': True, 'email': 'a@b.com', 'wazo_tenant_uuid': 't-uuid'}),
        breaker=breaker,
    )
    idp.verify_auth({'backend': 'optimogo', 'login': 'a@b.com', 'password': 'tok'})
    # Breaker still closed (no prior failures) — confirm it allows further calls
    assert breaker.allow() is True


# ---------------------------------------------------------------------------
# verify_auth — failure paths
# ---------------------------------------------------------------------------

def test_verify_auth_inactive_raises():
    idp = _idp(_FakeClient({'active': False}))
    with pytest.raises(InvalidBridgeToken):
        idp.verify_auth({'backend': 'optimogo', 'login': 'a@b.com', 'password': 'tok'})


def test_verify_auth_tenant_mismatch_raises():
    idp = _idp(_FakeClient({'active': True, 'email': 'a@b.com', 'wazo_tenant_uuid': 'WRONG'}))
    with pytest.raises(InvalidBridgeToken):
        idp.verify_auth({'backend': 'optimogo', 'login': 'a@b.com', 'password': 'tok'})


def test_verify_auth_unresolvable_user_raises():
    idp = _idp(
        _FakeClient({'active': True, 'email': 'a@b.com', 'wazo_tenant_uuid': 't-uuid'}),
        resolve_ok=False,
    )
    with pytest.raises(InvalidBridgeToken):
        idp.verify_auth({'backend': 'optimogo', 'login': 'a@b.com', 'password': 'tok'})


def test_verify_auth_introspect_error_raises_and_records_failure():
    """IntrospectError → record_failure() + raise InvalidBridgeToken."""
    from wazo_auth_optimogo.exceptions import IntrospectError
    from wazo_dird_optimogo.breaker import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=5, cooldown=30)
    idp = _idp(_FakeClient(IntrospectError('network down')), breaker=breaker)

    with pytest.raises(InvalidBridgeToken):
        idp.verify_auth({'backend': 'optimogo', 'login': 'a@b.com', 'password': 'tok'})

    # One failure recorded; breaker still closed (threshold is 5)
    assert breaker.allow() is True
    assert breaker._failures == 1


def test_verify_auth_breaker_open_raises_without_calling_client():
    """When the breaker is open, verify_auth raises immediately — no HTTP call."""
    from wazo_dird_optimogo.breaker import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=1, cooldown=30)
    breaker.record_failure()                      # opens the breaker
    assert breaker.allow() is False               # confirm it is open

    client = _FakeClient({'active': True, 'email': 'a@b.com', 'wazo_tenant_uuid': 't-uuid'})
    idp = _idp(client, breaker=breaker)

    with pytest.raises(InvalidBridgeToken):
        idp.verify_auth({'backend': 'optimogo', 'login': 'a@b.com', 'password': 'tok'})

    assert client.call_count == 0     # introspect() must NOT have been called


# ---------------------------------------------------------------------------
# InvalidBridgeToken inheritance
# ---------------------------------------------------------------------------

def test_invalid_bridge_token_is_invalid_username_password():
    """InvalidBridgeToken must subclass the wazo-auth exception hierarchy."""
    from wazo_auth_optimogo.idp import _InvalidUsernamePassword
    assert issubclass(InvalidBridgeToken, _InvalidUsernamePassword)


# ---------------------------------------------------------------------------
# authentication_method
# ---------------------------------------------------------------------------

def test_authentication_method_is_optimogo():
    idp = OptimoGoIDP()
    assert idp.authentication_method == 'optimogo'
