# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Flask-RESTful resources serving the XSI endpoints a Yealink phone drives.

Two families live here:

  * ``…/directories/CallLogs`` — the "Network CallLog" screen, backed by
    wazo-call-logd.
  * ``…/VoiceMessagingMessages`` — the visual-voicemail screen, backed by
    wazo-calld's voicemail API.

Both ignore the ``<userid>`` in the URL: identity is taken from the authenticated
SIP credential (see auth.py), never from a caller-supplied path segment. The
userid is only echoed back inside the message ids we publish, because the phone
builds its follow-up URLs from them.

Auth failures return 401 with a ``WWW-Authenticate`` challenge (not 403/500) so
the phone treats it as a credential prompt and shows an empty list rather than a
hard error.
"""

from __future__ import annotations

import logging

import requests
from flask import Response, request
from flask_restful import Resource

from . import auth, call_logs, queues, voicemail, xml
from .exceptions import MessageKeyError, VoicemailFolderError, XsiError

logger = logging.getLogger(__name__)

_CONTENT_TYPE = 'text/xml; charset=ISO-8859-1'
_VOICE_CONTENT_TYPE = 'text/xml; charset=UTF-8'
_CHALLENGE = {'WWW-Authenticate': 'BroadWorksSIP'}
# Phones display a bounded recent history; cap the CDR fetch so a heavy user's
# full history never turns into a huge XML document.
_CDR_LIMIT = 50

_STATUS_NO_CONTENT = 204
_STATUS_NOT_FOUND = 404
_STATUS_UNAUTHORIZED = 401
_STATUS_SERVICE_UNAVAILABLE = 503

_ACCESSTYPE_GLOBAL = 'global'


class _BaseXsiResource(Resource):
    """Shared identity and response plumbing for every XSI resource."""

    def __init__(self, confd_client):
        self.confd_client = confd_client

    def _resolve_user(self) -> auth.ResolvedUser:
        credential = auth.parse_broadworks_sip(request.headers.get('Authorization'))
        return auth.resolve_user(self.confd_client, credential)

    @staticmethod
    def _xml_response(body: bytes, content_type: str = _CONTENT_TYPE) -> Response:
        return Response(body, status=200, content_type=content_type)

    @staticmethod
    def _challenge() -> Response:
        return Response(status=_STATUS_UNAUTHORIZED, headers=_CHALLENGE)


class _BaseCallLogsResource(_BaseXsiResource):
    def __init__(self, confd_client, call_logd_client):
        super().__init__(confd_client)
        self.call_logd_client = call_logd_client

    def _fetch_feed(self, user_uuid: str) -> list[dict]:
        # recurse=True is required, not optional: phoned's service token lives in
        # the master tenant while users and their CDRs live in a sub-tenant, so a
        # non-recursive query returns an empty list for every real user.
        result = self.call_logd_client.cdr.list_for_user(
            user_uuid, limit=_CDR_LIMIT, recurse=True
        )
        return result.get('items') or []

    def _load_buckets(self, user_uuid: str) -> dict:
        """Build the three call-log lists for a user.

        Placed and Received are always personal — the user's own CDR feed. Missed
        is personal too *unless* the user is a queue member, in which case it
        becomes the shared reception list: an inbound call nobody on the queue
        answered shows on every member's phone, because call-logd tags each such
        CDR to only one member and would otherwise hide it from the rest.
        """
        own_feed = self._fetch_feed(user_uuid)
        buckets = call_logs.split_call_logs(own_feed, user_uuid)

        comembers = self._reception_comembers(user_uuid)
        if comembers:
            feeds = [own_feed]
            feeds += [
                self._fetch_feed(uuid) for uuid in sorted(comembers) if uuid != user_uuid
            ]
            buckets[call_logs.MISSED] = call_logs.shared_missed_entries(
                feeds, limit=_CDR_LIMIT
            )
        return buckets

    def _reception_comembers(self, user_uuid: str) -> set:
        """Queue co-members of the user, or an empty set to keep the personal list.

        A missing ``confd.queues.read`` grant surfaces as an HTTP error from confd
        rather than a crash: we log the remediation once and fall back to the
        personal Missed list, so the feature degrades to its previous behaviour
        instead of failing the whole call-log screen.
        """
        try:
            return queues.comember_uuids(self.confd_client, user_uuid)
        except requests.RequestException as exc:
            logger.warning(
                'queue lookup failed for %s (%s); serving the personal Missed '
                'list. Grant wazo-phoned confd.queues.read to enable the shared '
                'reception Missed list.',
                user_uuid,
                exc,
            )
            return set()


class CallLogsResource(_BaseCallLogsResource):
    """The combined ``/CallLogs`` endpoint (returns <CallLogs> with all lists)."""

    def get(self, userid):
        try:
            user = self._resolve_user()
        except XsiError as exc:
            logger.info('XSI auth rejected for %s: %s', userid, exc)
            return self._challenge()
        buckets = self._load_buckets(user.uuid)
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
            return Response(status=_STATUS_NOT_FOUND)
        try:
            user = self._resolve_user()
        except XsiError as exc:
            logger.info('XSI auth rejected for %s/%s: %s', userid, list_type, exc)
            return self._challenge()
        buckets = self._load_buckets(user.uuid)
        return self._xml_response(xml.render_list(list_name, buckets[list_name]))


class _BaseVoiceMessagingResource(_BaseXsiResource):
    """Shared voicemail lookups for the VoiceMessagingMessages endpoints."""

    def __init__(self, confd_client, calld_client):
        super().__init__(confd_client)
        self.calld_client = calld_client

    def _voicemail_ids(self, user: auth.ResolvedUser) -> list[int]:
        """Return the ids of every voicemail box this user may read.

        Mirrors wazo-calld's own rule for a user's messages: their personal box,
        if they have one, plus every box in their tenant marked global. The
        tenant scope is not optional — without it a recursive query would offer
        one tenant's shared mailbox to another tenant's phones.
        """
        ids = []
        personal = self.confd_client.users(user.uuid).get_voicemail()
        if personal:
            ids.append(personal['id'])
        shared = self.confd_client.voicemails.list(
            accesstype=_ACCESSTYPE_GLOBAL, tenant_uuid=user.tenant_uuid
        )
        ids.extend(
            box['id'] for box in shared.get('items') or [] if box['id'] not in ids
        )
        return ids

    def _load_messages(self, user: auth.ResolvedUser) -> list[voicemail.VoiceMessage]:
        messages: list[voicemail.VoiceMessage] = []
        for voicemail_id in self._voicemail_ids(user):
            detail = self.calld_client.voicemails.get_voicemail(voicemail_id)
            messages.extend(voicemail.messages_from_voicemail(detail))
        return voicemail.sort_newest_first(messages)

    def _find_message(
        self, user: auth.ResolvedUser, message_key: str
    ) -> tuple[dict, voicemail.VoiceMessage]:
        """Return (voicemail detail, message) for the message ``message_key`` names.

        The key carries a voicemail id the phone could tamper with, so the box it
        names is checked against the boxes this user may read before anything is
        fetched, moved or deleted. The box detail is returned alongside the
        message because a follow-up move needs its folder ids and would otherwise
        refetch it.
        """
        voicemail_id, message_id = voicemail.parse_key(message_key)
        if voicemail_id not in self._voicemail_ids(user):
            raise MessageKeyError(
                f'voicemail {voicemail_id} is not readable by user {user.uuid}'
            )
        detail = self.calld_client.voicemails.get_voicemail(voicemail_id)
        for message in voicemail.messages_from_voicemail(detail):
            if message.message_id == message_id:
                return detail, message
        raise MessageKeyError(f'no message {message_id} in voicemail {voicemail_id}')

    def _move_to_folder(
        self, detail: dict, message: voicemail.VoiceMessage, folder_type: str
    ) -> None:
        self.calld_client.voicemails.move_voicemail_message(
            message.voicemail_id,
            message.message_id,
            voicemail.folder_id(detail, folder_type),
        )

    def _mark_all(
        self, user: auth.ResolvedUser, folder_type: str, mark_read: bool
    ) -> None:
        """Move every message not already in the wanted state, box by box.

        Iterating per box rather than over a merged list keeps it to one fetch
        per voicemail, and a message already read (or already unread) is skipped
        so the operation does not rewrite folders needlessly.
        """
        for voicemail_id in self._voicemail_ids(user):
            detail = self.calld_client.voicemails.get_voicemail(voicemail_id)
            for message in voicemail.messages_from_voicemail(detail):
                if message.read is not mark_read:
                    self._move_to_folder(detail, message, folder_type)


class VoiceMessagesResource(_BaseVoiceMessagingResource):
    """``/VoiceMessagingMessages`` — the message list the phone renders."""

    def get(self, userid):
        try:
            user = self._resolve_user()
        except XsiError as exc:
            logger.info('XSI voicemail auth rejected for %s: %s', userid, exc)
            return self._challenge()
        messages = self._load_messages(user)
        return self._xml_response(
            xml.render_voice_messages(userid, messages), _VOICE_CONTENT_TYPE
        )


# The read/unread actions XSI defines, keyed by the lowercased action name so a
# difference in capitalisation between the specification's prose and what a phone
# actually sends cannot break them.
_MARK_ALL_ACTIONS = {
    'markallasread': (voicemail.FOLDER_OLD, True),
    'markallasunread': (voicemail.FOLDER_NEW, False),
}
_MARK_ACTIONS = {
    'markasread': voicemail.FOLDER_OLD,
    'markasunread': voicemail.FOLDER_NEW,
}


class VoiceMessageResource(_BaseVoiceMessagingResource):
    """``/VoiceMessagingMessages/<segment>`` — one message, or a mark-all action.

    XSI overloads this position in its URL space: ``GET``/``DELETE`` address a
    single message by the id we published, while ``PUT`` addresses the
    MarkAllAsRead / MarkAllAsUnread actions. Nothing in the path distinguishes
    them — only the method does — so both live in one resource rather than two
    routes that would collide on the same rule.
    """

    def get(self, userid, segment):
        try:
            user = self._resolve_user()
        except XsiError as exc:
            logger.info('XSI voicemail auth rejected for %s: %s', userid, exc)
            return self._challenge()
        try:
            _, message = self._find_message(user, segment)
        except MessageKeyError as exc:
            logger.info('XSI voicemail message not available: %s', exc)
            return Response(status=_STATUS_NOT_FOUND)
        media = self.calld_client.voicemails.get_voicemail_recording(
            message.voicemail_id, message.message_id
        )
        return self._xml_response(
            xml.render_voice_message(userid, message, media), _VOICE_CONTENT_TYPE
        )

    def delete(self, userid, segment):
        try:
            user = self._resolve_user()
        except XsiError as exc:
            logger.info('XSI voicemail auth rejected for %s: %s', userid, exc)
            return self._challenge()
        try:
            _, message = self._find_message(user, segment)
        except MessageKeyError as exc:
            logger.info('XSI voicemail message not available: %s', exc)
            return Response(status=_STATUS_NOT_FOUND)
        self.calld_client.voicemails.delete_voicemail_message(
            message.voicemail_id, message.message_id
        )
        return Response(status=_STATUS_NO_CONTENT)

    def put(self, userid, segment):
        """MarkAllAsRead / MarkAllAsUnread.

        Marking every message read means moving each unread one into its box's
        ``old`` folder (and the reverse for unread), so a message already in the
        wanted state is skipped rather than moved onto itself.
        """
        target = _MARK_ALL_ACTIONS.get(segment.lower())
        if target is None:
            return Response(status=_STATUS_NOT_FOUND)
        folder_type, mark_read = target
        try:
            user = self._resolve_user()
        except XsiError as exc:
            logger.info(
                'XSI voicemail auth rejected for %s/%s: %s', userid, segment, exc
            )
            return self._challenge()
        try:
            self._mark_all(user, folder_type, mark_read)
        except VoicemailFolderError as exc:
            logger.error('cannot %s for %s: %s', segment, userid, exc)
            return Response(status=_STATUS_SERVICE_UNAVAILABLE)
        return Response(status=_STATUS_NO_CONTENT)


class VoiceMessageMarkResource(_BaseVoiceMessagingResource):
    """``/VoiceMessagingMessages/<key>/MarkAsRead|MarkAsUnread``."""

    def put(self, userid, message_key, action):
        folder_type = _MARK_ACTIONS.get(action.lower())
        if folder_type is None:
            return Response(status=_STATUS_NOT_FOUND)
        try:
            user = self._resolve_user()
        except XsiError as exc:
            logger.info('XSI voicemail auth rejected for %s: %s', userid, exc)
            return self._challenge()
        try:
            detail, message = self._find_message(user, message_key)
        except MessageKeyError as exc:
            logger.info('XSI voicemail message not available: %s', exc)
            return Response(status=_STATUS_NOT_FOUND)
        try:
            self._move_to_folder(detail, message, folder_type)
        except VoicemailFolderError as exc:
            logger.error('cannot %s %s: %s', action, message_key, exc)
            return Response(status=_STATUS_SERVICE_UNAVAILABLE)
        return Response(status=_STATUS_NO_CONTENT)
