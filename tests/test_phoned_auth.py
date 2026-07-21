# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for XSI BroadWorksSIP auth parsing + confd validation (auth.py)."""

import base64

import pytest

from wazo_phoned_optimogo import auth
from wazo_phoned_optimogo.auth import SipCredential
from wazo_phoned_optimogo.exceptions import (
    AuthenticationError,
    AuthHeaderError,
    UserResolutionError,
)

USER = 'aa3a2125-d8bf-4a3a-b039-de9cd95ce318'


def _b64(text):
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


def _header(sip_user='cuejqnsy', xsi_user='1000@pbx.local.optimo.group',
            password='slevcxeb'):
    # The exact scheme a T87W sends with sip.authentication_for_xsi = 1.
    basic = _b64(f'{xsi_user}:{password}')
    return f'BroadWorksSIP basic="{basic}", sipUser="{_b64(sip_user)}"'


# --- parse_broadworks_sip -------------------------------------------------

def test_parse_extracts_sip_user_and_password():
    cred = auth.parse_broadworks_sip(_header())
    assert cred == SipCredential(sip_user='cuejqnsy', password='slevcxeb')


def test_parse_takes_password_after_last_colon_so_uri_user_is_safe():
    # xsiUser is a sip: URI containing ':'; the password is after the LAST colon.
    header = _header(xsi_user='sip:1000@host', password='pw')
    assert auth.parse_broadworks_sip(header).password == 'pw'


def test_parse_missing_header_raises():
    with pytest.raises(AuthHeaderError):
        auth.parse_broadworks_sip(None)


def test_parse_plain_basic_scheme_rejected():
    with pytest.raises(AuthHeaderError):
        auth.parse_broadworks_sip('Basic ' + _b64('u:p'))


def test_parse_missing_sip_user_param_raises():
    with pytest.raises(AuthHeaderError):
        auth.parse_broadworks_sip(f'BroadWorksSIP basic="{_b64("u:p")}"')


def test_parse_bad_base64_raises():
    with pytest.raises(AuthHeaderError):
        auth.parse_broadworks_sip('BroadWorksSIP basic="!!!", sipUser="!!!"')


def test_parse_basic_without_colon_raises():
    header = f'BroadWorksSIP basic="{_b64("nocolon")}", sipUser="{_b64("x")}"'
    with pytest.raises(AuthHeaderError):
        auth.parse_broadworks_sip(header)


# --- resolve_user ----------------------------------------------------

class FakeConfd:
    """Minimal confd stand-in exposing only what resolve_user touches."""

    def __init__(self, endpoint=None, line=None):
        self._endpoint = endpoint
        self._line = line
        self.endpoints_sip = self._Endpoints(endpoint)
        self.lines = self._Lines(line)

    class _Endpoints:
        def __init__(self, endpoint):
            self._endpoint = endpoint

        def list(self, name, recurse):
            self.list_name = name
            return {'items': [{'uuid': 'ep-uuid'}] if self._endpoint else []}

        def get(self, uuid):
            return self._endpoint

    class _Lines:
        def __init__(self, line):
            self._line = line

        def get(self, line_id):
            self.get_id = line_id
            return self._line


TENANT = '02b639ea-a2d2-4314-ab30-cc7c1e490fbe'


def _endpoint(username='cuejqnsy', password='slevcxeb', line_id=1):
    return {
        'uuid': 'ep-uuid',
        'name': username,
        'tenant_uuid': TENANT,
        'auth_section_options': [['username', username], ['password', password]],
        'line': {'id': line_id} if line_id else None,
    }


def _line(user_uuid=USER):
    return {'id': 1, 'users': [{'uuid': user_uuid}] if user_uuid else []}


def test_resolve_returns_user_and_tenant_on_valid_credential():
    confd = FakeConfd(endpoint=_endpoint(), line=_line())
    cred = SipCredential(sip_user='cuejqnsy', password='slevcxeb')
    resolved = auth.resolve_user(confd, cred)
    assert resolved.uuid == USER
    # The tenant comes off the endpoint, not the (tenant-less) user summary the
    # line returns — the voicemail lookup needs it to scope global mailboxes.
    assert resolved.tenant_uuid == TENANT


def test_resolve_unknown_endpoint_raises_authentication_error():
    confd = FakeConfd(endpoint=None)
    cred = SipCredential(sip_user='nobody', password='x')
    with pytest.raises(AuthenticationError):
        auth.resolve_user(confd, cred)


def test_resolve_wrong_password_raises_authentication_error():
    confd = FakeConfd(endpoint=_endpoint(password='correct'), line=_line())
    cred = SipCredential(sip_user='cuejqnsy', password='WRONG')
    with pytest.raises(AuthenticationError):
        auth.resolve_user(confd, cred)


def test_resolve_endpoint_without_line_raises_user_resolution_error():
    confd = FakeConfd(endpoint=_endpoint(line_id=None))
    cred = SipCredential(sip_user='cuejqnsy', password='slevcxeb')
    with pytest.raises(UserResolutionError):
        auth.resolve_user(confd, cred)


def test_resolve_line_without_user_raises_user_resolution_error():
    confd = FakeConfd(endpoint=_endpoint(), line=_line(user_uuid=None))
    cred = SipCredential(sip_user='cuejqnsy', password='slevcxeb')
    with pytest.raises(UserResolutionError):
        auth.resolve_user(confd, cred)
