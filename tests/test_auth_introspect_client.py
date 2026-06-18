import json
import pytest
import requests

from wazo_auth_optimogo.http_client import OptimoGoIntrospectClient
from wazo_auth_optimogo.exceptions import (
    IntrospectAuthError, IntrospectUnavailable, IntrospectTimeout, IntrospectError,
)


class _FakeResp:
    def __init__(self, status, body, ctype='application/json'):
        self.status_code = status
        self._body = body
        self.headers = {'Content-Type': ctype}

    def json(self):
        return json.loads(self._body)

    def close(self):
        pass


class _FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.headers = {}

    def post(self, *a, **k):
        return self._resp


class _TimeoutSession:
    def __init__(self):
        self.headers = {}

    def post(self, *a, **k):
        raise requests.exceptions.Timeout('timed out')


class _ConnectionErrorSession:
    def __init__(self):
        self.headers = {}

    def post(self, *a, **k):
        raise requests.exceptions.ConnectionError('connection refused')


def _client(resp):
    return OptimoGoIntrospectClient(
        base_url='https://og.example.com', api_key='k',
        connect_timeout=2, read_timeout=4, verify=True, session=_FakeSession(resp))


def test_active_true():
    c = _client(_FakeResp(200, '{"active": true, "email": "a@b.com", "wazo_tenant_uuid": "t"}'))
    assert c.introspect('tok') == {'active': True, 'email': 'a@b.com', 'wazo_tenant_uuid': 't'}


def test_active_false():
    c = _client(_FakeResp(200, '{"active": false}'))
    assert c.introspect('tok') == {'active': False}


def test_auth_error_401_raises():
    c = _client(_FakeResp(401, ''))
    with pytest.raises(IntrospectAuthError) as exc_info:
        c.introspect('tok')
    assert 'HTTP 401' in str(exc_info.value)


def test_auth_error_403_raises():
    c = _client(_FakeResp(403, ''))
    with pytest.raises(IntrospectAuthError) as exc_info:
        c.introspect('tok')
    assert 'HTTP 403' in str(exc_info.value)


def test_5xx_unavailable():
    c = _client(_FakeResp(500, ''))
    with pytest.raises(IntrospectUnavailable) as exc_info:
        c.introspect('tok')
    assert 'HTTP 500' in str(exc_info.value)


def test_503_unavailable():
    c = _client(_FakeResp(503, ''))
    with pytest.raises(IntrospectUnavailable) as exc_info:
        c.introspect('tok')
    assert 'HTTP 503' in str(exc_info.value)


def test_429_unavailable():
    c = _client(_FakeResp(429, ''))
    with pytest.raises(IntrospectUnavailable) as exc_info:
        c.introspect('tok')
    assert 'HTTP 429' in str(exc_info.value)


def test_timeout_raises_introspect_timeout():
    c = OptimoGoIntrospectClient(
        base_url='https://og.example.com', api_key='k',
        connect_timeout=2, read_timeout=4, verify=True, session=_TimeoutSession())
    with pytest.raises(IntrospectTimeout):
        c.introspect('tok')


def test_connection_error_raises_introspect_unavailable():
    c = OptimoGoIntrospectClient(
        base_url='https://og.example.com', api_key='k',
        connect_timeout=2, read_timeout=4, verify=True, session=_ConnectionErrorSession())
    with pytest.raises(IntrospectUnavailable):
        c.introspect('tok')


def test_wrong_content_type_raises_introspect_error():
    c = _client(_FakeResp(200, '<html/>', ctype='text/html'))
    with pytest.raises(IntrospectError):
        c.introspect('tok')


def test_missing_active_key_raises_introspect_error():
    c = _client(_FakeResp(200, '{"email": "a@b.com"}'))
    with pytest.raises(IntrospectError):
        c.introspect('tok')


def test_bearer_token_set_in_headers():
    """Authorization header is set to Bearer <api_key> on the session."""
    resp = _FakeResp(200, '{"active": true}')
    session = _FakeSession(resp)
    c = OptimoGoIntrospectClient(
        base_url='https://og.example.com', api_key='my-secret-key',
        connect_timeout=2, read_timeout=4, verify=True, session=session)
    c.introspect('tok')
    assert session.headers.get('Authorization') == 'Bearer my-secret-key'


def test_introspect_posts_to_correct_url():
    """introspect() POSTs to <base_url>/introspect/ — the trailing slash is required
    because OptimoGo's Django route is slash-terminated with APPEND_SLASH=True, which
    cannot redirect a POST to the slashed URL without dropping the body."""
    calls = []

    class _RecordingSession:
        def __init__(self):
            self.headers = {}

        def post(self, url, **k):
            calls.append(url)
            return _FakeResp(200, '{"active": true}')

    c = OptimoGoIntrospectClient(
        base_url='https://og.example.com/api/wazo/auth/acme', api_key='k',
        connect_timeout=2, read_timeout=4, verify=True, session=_RecordingSession())
    c.introspect('tok')
    assert calls == ['https://og.example.com/api/wazo/auth/acme/introspect/']


def test_introspect_sends_token_in_body():
    """introspect() sends {token: <value>} in JSON body."""
    payloads = []

    class _RecordingSession:
        def __init__(self):
            self.headers = {}

        def post(self, url, json=None, **k):
            payloads.append(json)
            return _FakeResp(200, '{"active": true}')

    c = OptimoGoIntrospectClient(
        base_url='https://og.example.com', api_key='k',
        connect_timeout=2, read_timeout=4, verify=True, session=_RecordingSession())
    c.introspect('my-token-value')
    assert payloads == [{'token': 'my-token-value'}]


def test_all_exception_types_inherit_introspect_error():
    """IntrospectAuthError, IntrospectTimeout, IntrospectUnavailable all subclass IntrospectError."""
    assert issubclass(IntrospectAuthError, IntrospectError)
    assert issubclass(IntrospectTimeout, IntrospectError)
    assert issubclass(IntrospectUnavailable, IntrospectError)
