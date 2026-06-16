import json

import requests

from .exceptions import (
    OptimoGoAuthError, OptimoGoTimeout, OptimoGoUnavailable, OptimoGoLookupError,
)

_MAX_BODY_BYTES = 1 << 20  # 1 MiB cap on response bodies


class OptimoGoClient:
    """POSTs JSON to OptimoGo with bearer auth and a hard connect/read timeout.

    One pooled Session is created once and shared across threads; it is never
    mutated per-call, so concurrent use is safe. Raises typed exceptions only.
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

    def post(self, path, payload):
        url = f'{self._base}{path}'
        try:
            resp = self._session.post(
                url, json=payload, timeout=self._timeout, verify=self._verify,
                allow_redirects=False, stream=True,
            )
        except requests.exceptions.Timeout as e:
            raise OptimoGoTimeout(str(e)) from e
        except requests.exceptions.RequestException as e:
            raise OptimoGoUnavailable(str(e)) from e
        return self._parse(resp)

    def _parse(self, resp):
        try:
            status = resp.status_code
            if status in (401, 403):
                raise OptimoGoAuthError(f'auth failed: HTTP {status}')
            if status == 429 or 500 <= status < 600:
                raise OptimoGoUnavailable(f'unavailable: HTTP {status}')
            if status != 200:
                raise OptimoGoLookupError(f'unexpected status: HTTP {status}')
            ctype = resp.headers.get('Content-Type', '')
            if 'application/json' not in ctype:
                raise OptimoGoLookupError(f'unexpected content-type: {ctype!r}')
            raw = resp.raw.read(_MAX_BODY_BYTES + 1, decode_content=True)
            if len(raw) > _MAX_BODY_BYTES:
                raise OptimoGoLookupError('response body too large')
            try:
                return json.loads(raw)
            except ValueError as e:
                raise OptimoGoLookupError(f'invalid json: {e}') from e
        finally:
            resp.close()

    def close(self):
        self._session.close()
