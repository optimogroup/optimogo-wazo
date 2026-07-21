# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exceptions for the OptimoGo XSI call-log plugin.

The HTTP layer maps these to the responses a Yealink phone expects: a bad or
missing credential must produce ``401`` with a ``WWW-Authenticate`` challenge
(the phone resends its SIP credentials on the challenge), and an unresolvable
user is a ``401`` too — from the phone's side "these credentials don't grant a
call log" is indistinguishable from "wrong credentials", and returning 404/500
makes the phone show a hard error instead of an empty list.
"""

from __future__ import annotations


class XsiError(Exception):
    """Base class for all XSI plugin errors."""


class AuthHeaderError(XsiError):
    """The Authorization header is missing or not a shape we can parse.

    Raised before we even know which user is being claimed (malformed
    ``BroadWorksSIP`` header, missing parts, bad base64). Maps to 401 +
    challenge so the phone retries with credentials.
    """


class AuthenticationError(XsiError):
    """The presented SIP credentials did not match a known endpoint.

    The auth username was not found, or the password did not match the value
    wazo-confd stores for that endpoint. Maps to 401 (never 403) so the phone
    treats it as a credential prompt rather than a fatal error.
    """


class UserResolutionError(XsiError):
    """The endpoint is valid but is not associated with a user.

    e.g. a trunk endpoint, or a line with no user attached — there is no call
    log to return. Maps to 401 for the same phone-side reason as above.
    """


class MessageKeyError(XsiError):
    """A voicemail message id in the URL is not one we published.

    The phone echoes back the ``<messageId>`` we gave it, so a key we cannot
    parse is a stale or forged request rather than a credential problem. Maps to
    404 — unlike the auth errors above, re-authenticating would not help.
    """


class VoicemailFolderError(XsiError):
    """A voicemail is missing the folder a read/unread change needs.

    Wazo stores "read" as membership of the ``old`` folder, so a box without the
    target folder cannot express the change. Maps to 503: the request was valid,
    the server just cannot carry it out, and the phone should not conclude the
    message is gone.
    """
