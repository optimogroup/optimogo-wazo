# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Flask-RESTful resources serving the XSI CallLogs endpoints to Yealink phones.

A Yealink phone fetches its "Network CallLog" from the fixed BroadWorks XSI path
``/com.broadsoft.xsi-actions/v2.0/user/<userid>/directories/CallLogs`` — either
the combined list or a per-type sub-resource (``/CallLogs/Placed`` etc.). We
ignore the ``<userid>`` in the URL: identity is taken from the authenticated SIP
credential (see auth.py), never from a caller-supplied path segment.

Auth failures return 401 with a ``WWW-Authenticate`` challenge (not 403/500) so
the phone treats it as a credential prompt and shows an empty log rather than a
hard error.
"""

from __future__ import annotations

import logging

from flask import Response, request
from flask_restful import Resource

from . import auth, call_logs, xml
from .exceptions import XsiError

logger = logging.getLogger(__name__)

_CONTENT_TYPE = 'text/xml; charset=ISO-8859-1'
_CHALLENGE = {'WWW-Authenticate': 'BroadWorksSIP'}
# Phones display a bounded recent history; cap the CDR fetch so a heavy user's
# full history never turns into a huge XML document.
_CDR_LIMIT = 50


class _BaseCallLogsResource(Resource):
    def __init__(self, confd_client, call_logd_client):
        self.confd_client = confd_client
        self.call_logd_client = call_logd_client

    def _resolve_user(self) -> str:
        credential = auth.parse_broadworks_sip(request.headers.get('Authorization'))
        return auth.resolve_user_uuid(self.confd_client, credential)

    def _load_buckets(self, user_uuid: str) -> dict:
        # recurse=True is required, not optional: phoned's service token lives in
        # the master tenant while users and their CDRs live in a sub-tenant, so a
        # non-recursive query returns an empty list for every real user.
        result = self.call_logd_client.cdr.list_for_user(
            user_uuid, limit=_CDR_LIMIT, recurse=True
        )
        return call_logs.split_call_logs(result.get('items') or [], user_uuid)

    @staticmethod
    def _xml_response(body: bytes) -> Response:
        return Response(body, status=200, content_type=_CONTENT_TYPE)

    @staticmethod
    def _challenge() -> Response:
        return Response(status=401, headers=_CHALLENGE)


class CallLogsResource(_BaseCallLogsResource):
    """The combined ``/CallLogs`` endpoint (returns <CallLogs> with all lists)."""

    def get(self, userid):
        try:
            user_uuid = self._resolve_user()
        except XsiError as exc:
            logger.info('XSI auth rejected for %s: %s', userid, exc)
            return self._challenge()
        buckets = self._load_buckets(user_uuid)
        return self._xml_response(xml.render_combined(buckets))


class CallLogsListResource(_BaseCallLogsResource):
    """A per-type sub-endpoint (``/CallLogs/Placed|Received|Missed``).

    Returns the bare lowercase root (<placed> etc.) the phone expects. An unknown
    type is treated as an empty list of that (lowercased) name would be invalid,
    so we 404 — the phone only ever requests the three real types.
    """

    def get(self, userid, list_type):
        list_name = list_type.lower()
        if list_name not in call_logs.LISTS:
            return Response(status=404)
        try:
            user_uuid = self._resolve_user()
        except XsiError as exc:
            logger.info('XSI auth rejected for %s/%s: %s', userid, list_type, exc)
            return self._challenge()
        buckets = self._load_buckets(user_uuid)
        return self._xml_response(xml.render_list(list_name, buckets[list_name]))
