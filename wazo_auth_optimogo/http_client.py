import requests

from .exceptions import (
    IntrospectAuthError, IntrospectTimeout, IntrospectUnavailable, IntrospectError,
)

_MAX_BODY_BYTES = 1 << 16  # 64 KiB — introspect responses are tiny
_PATH = '/introspect'


class OptimoGoIntrospectClient:
    """POSTs {token} to OptimoGo's per-tenant introspect URL with bearer auth and
    a hard connect/read timeout. The base_url already includes the schema prefix
    (e.g. /api/wazo/auth/<schema>). Raises typed IntrospectError subclasses only.

    One pooled Session is created once and shared across threads; it is never
    mutated per-call, so concurrent use is safe.
    """

    def __init__(self, base_url, api_key, connect_timeout, read_timeout,
                 verify, session=None):
        self._base = base_url.rstrip('/')
        self._timeout = (connect_timeout, read_timeout)
        self._verify = verify
        self._session = session or requests.Session()
        self._session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

    def introspect(self, token: str) -> dict:
        """POST {token} to the introspect endpoint and return the parsed response dict.

        Returns a dict that always contains the 'active' key.
        Raises:
            IntrospectAuthError: 401 or 403 response (bad/rotated API key).
            IntrospectTimeout: connect or read timeout.
            IntrospectUnavailable: 5xx, 429, or transport-level failure.
            IntrospectError: unexpected status, wrong content-type, malformed body.
        """
        url = f'{self._base}{_PATH}'
        try:
            resp = self._session.post(
                url, json={'token': token}, timeout=self._timeout,
                verify=self._verify, allow_redirects=False,
            )
        except requests.exceptions.Timeout as e:
            raise IntrospectTimeout(str(e)) from e
        except requests.exceptions.RequestException as e:
            raise IntrospectUnavailable(str(e)) from e

        return self._parse(resp)

    def _parse(self, resp) -> dict:
        try:
            status = resp.status_code
            if status in (401, 403):
                raise IntrospectAuthError(f'auth failed: HTTP {status}')
            if status == 429 or 500 <= status < 600:
                raise IntrospectUnavailable(f'unavailable: HTTP {status}')
            if status != 200:
                raise IntrospectError(f'unexpected status: HTTP {status}')
            ctype = resp.headers.get('Content-Type', '')
            if 'application/json' not in ctype:
                raise IntrospectError(f'unexpected content-type: {ctype!r}')
            data = resp.json()
        finally:
            getattr(resp, 'close', lambda: None)()

        if not isinstance(data, dict) or 'active' not in data:
            raise IntrospectError('malformed introspection response: missing "active" key')
        return data

    def close(self):
        self._session.close()
