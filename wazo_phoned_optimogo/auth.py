# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parse and validate the Yealink XSI ``BroadWorksSIP`` credential.

When a Yealink phone is provisioned with ``sip.authentication_for_xsi = 1`` it
authenticates XSI requests with its SIP register credentials, using a
BroadWorks-specific scheme (captured live from a T87W on 185.87.0.34):

    Authorization: BroadWorksSIP basic="<b64(xsiUser:sipPassword)>", sipUser="<b64(sipAuthName)>"

  * ``sipUser`` (base64) is the SIP authentication username — in Wazo this is
    the PJSIP endpoint name (e.g. ``cuejqnsy``).
  * ``basic`` (base64) is ``<xsiUser>:<sipPassword>``; only the password matters
    to us — the ``xsiUser`` half is the (cosmetic) ``account.X.xsi.user`` and is
    also echoed in the request URL, so we ignore it and trust ``sipUser``.

We authenticate by looking the endpoint up in wazo-confd by its auth username
and comparing the presented password to the one confd stores — the same
username/password pair Asterisk uses for SIP registration. A match proves the
request came from that phone; the endpoint's line then yields the user whose
call log to serve.

We deliberately validate the password (not just trust the username): the XSI
request is a plain HTTP call on the voice VLAN that never passes through
Asterisk's SIP auth, so without checking the password anyone on that VLAN could
read any user's call log by guessing endpoint names.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import NamedTuple

from .exceptions import AuthenticationError, AuthHeaderError, UserResolutionError

_SCHEME = 'BroadWorksSIP'
# key="value" pairs inside the header (basic="...", sipUser="...").
_PARAM_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


class SipCredential(NamedTuple):
    """A parsed XSI credential: the SIP auth username and its password."""

    sip_user: str
    password: str


def _b64decode(value: str, field: str) -> str:
    try:
        return base64.b64decode(value, validate=True).decode('utf-8')
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise AuthHeaderError(f'{field} is not valid base64') from exc


def parse_broadworks_sip(header: str | None) -> SipCredential:
    """Parse a ``BroadWorksSIP`` Authorization header into a SipCredential.

    Raises AuthHeaderError if the header is absent, uses a different scheme, or
    is missing/garbled parts — all of which the caller turns into a 401 so the
    phone (re)sends credentials.
    """
    if not header:
        raise AuthHeaderError('missing Authorization header')

    scheme, _, rest = header.partition(' ')
    if scheme != _SCHEME:
        raise AuthHeaderError(f'unsupported auth scheme {scheme!r}')

    params = dict(_PARAM_RE.findall(rest))
    basic = params.get('basic')
    sip_user_b64 = params.get('sipUser')
    if not basic or not sip_user_b64:
        raise AuthHeaderError('BroadWorksSIP header missing basic/sipUser')

    sip_user = _b64decode(sip_user_b64, 'sipUser')
    decoded_basic = _b64decode(basic, 'basic')
    # basic is "<xsiUser>:<sipPassword>"; the password may itself be empty but a
    # separator must be present, and we take everything after the LAST ':' so a
    # ':' inside the xsiUser (e.g. a sip: URI) does not corrupt the password.
    if ':' not in decoded_basic:
        raise AuthHeaderError('basic credential missing ":" separator')
    _, _, password = decoded_basic.rpartition(':')

    if not sip_user:
        raise AuthHeaderError('empty sipUser')
    return SipCredential(sip_user=sip_user, password=password)


def _auth_options(endpoint: dict) -> dict[str, str]:
    """Flatten confd's ``auth_section_options`` list-of-pairs into a dict."""
    return {key: value for key, value in endpoint.get('auth_section_options') or []}


def resolve_user_uuid(confd_client, credential: SipCredential) -> str:
    """Validate the SIP credential against confd and return the user UUID.

    Looks the endpoint up by its auth username, checks the password matches the
    stored one, then follows the endpoint's line to its user.

    Raises AuthenticationError if the endpoint/password is wrong, or
    UserResolutionError if the (valid) endpoint has no associated user.
    """
    result = confd_client.endpoints_sip.list(
        name=credential.sip_user, recurse=True
    )
    endpoint_ref = next(iter(result.get('items') or []), None)
    if endpoint_ref is None:
        raise AuthenticationError(f'no endpoint named {credential.sip_user!r}')

    # list() returns a summary; fetch the full endpoint for auth + line details.
    endpoint = confd_client.endpoints_sip.get(endpoint_ref['uuid'])
    options = _auth_options(endpoint)
    stored_username = options.get('username')
    stored_password = options.get('password')
    if stored_username != credential.sip_user or stored_password is None:
        raise AuthenticationError('endpoint has no matching SIP auth username')
    if not _passwords_equal(stored_password, credential.password):
        raise AuthenticationError('SIP password mismatch')

    line = endpoint.get('line')
    if not line:
        raise UserResolutionError('endpoint is not associated with a line')
    line_detail = confd_client.lines.get(line['id'])
    user = next(iter(line_detail.get('users') or []), None)
    if not user or not user.get('uuid'):
        raise UserResolutionError('line is not associated with a user')
    return user['uuid']


def _passwords_equal(stored: str, presented: str) -> bool:
    """Constant-time password comparison to avoid a timing side channel."""
    import hmac

    return hmac.compare_digest(stored, presented)
