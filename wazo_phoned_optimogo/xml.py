# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render XSI XML exactly as a Yealink phone expects it.

Shapes verified against the Cisco BroadWorks XSI Interface Specification (R20 and
R23 are identical) *and* live on a T87W (185.87.0.34):

  * A per-type sub-endpoint (``/CallLogs/Placed`` etc.) returns a **bare,
    unnamespaced** lowercase root — ``<placed>…</placed>`` — NOT wrapped in
    ``<CallLogs>``. Returning the wrapper parses without error but renders an
    empty list (learned the hard way during discovery).
  * The combined ``/CallLogs`` endpoint returns ``<CallLogs xmlns="…/xsi">``
    containing all three lists.
  * The voice-messaging documents are namespaced and, unlike the call logs,
    declared UTF-8 by the specification — so the two families deliberately use
    different declarations and encodings here.

Each call-log row is ``<callLogsEntry>`` with children in this order:
countryCode, phoneNumber, name, time, callLogId. The document declares
ISO-8859-1, so we emit latin-1 bytes and XML-escape every value (names can
contain ``&``, ``<``).
"""

from __future__ import annotations

from base64 import b64encode
from xml.sax.saxutils import escape

from .call_logs import LISTS, CallLogEntry
from .voicemail import VoiceMessage

_NS = 'http://schema.broadsoft.com/xsi'
_DECL = '<?xml version="1.0" encoding="ISO-8859-1"?>'
_ENCODING = 'latin-1'

_VOICE_DECL = '<?xml version="1.0" encoding="UTF-8"?>'
_VOICE_ENCODING = 'utf-8'
# The <messageId> we publish is a path, not a bare id: the phone appends it to
# the XSI base URL to fetch, mark or delete the message. The specification's own
# examples spell the collection lowercase inside this path even though the
# endpoint that lists them is capitalised, so we match the examples and serve
# both spellings (see plugin.py).
_MESSAGE_PATH = '/v2.0/user/{userid}/voicemessagingmessages/{key}'
# Wazo stores voicemail recordings as, and wazo-calld serves them as, 8 kHz mono
# PCM WAV. There is no transcoding step here, so the advertised media type is a
# statement of fact about the bytes in <content>.
_MEDIA_TYPE = 'WAV'


def _entry_xml(entry: CallLogEntry) -> str:
    return (
        '<callLogsEntry>'
        f'<countryCode>{escape(entry.country_code)}</countryCode>'
        f'<phoneNumber>{escape(entry.number)}</phoneNumber>'
        f'<name>{escape(entry.name)}</name>'
        f'<time>{escape(entry.time)}</time>'
        f'<callLogId>{escape(entry.log_id)}</callLogId>'
        '</callLogsEntry>'
    )


def _entries_xml(entries: list[CallLogEntry]) -> str:
    return ''.join(_entry_xml(e) for e in entries)


def render_list(list_name: str, entries: list[CallLogEntry]) -> bytes:
    """Render one call-log list (``placed``/``received``/``missed``) for a sub-endpoint.

    The root element is the bare lowercase list name with no namespace, per the
    captured phone behaviour.
    """
    if list_name not in LISTS:
        raise ValueError(f'unknown call-log list {list_name!r}')
    body = f'{_DECL}<{list_name}>{_entries_xml(entries)}</{list_name}>'
    return body.encode(_ENCODING, 'xmlcharrefreplace')


def render_combined(buckets: dict[str, list[CallLogEntry]]) -> bytes:
    """Render the combined ``<CallLogs>`` document (the ``/CallLogs`` endpoint)."""
    inner = ''.join(
        f'<{name}>{_entries_xml(buckets.get(name, []))}</{name}>' for name in LISTS
    )
    body = f'{_DECL}<CallLogs xmlns="{_NS}">{inner}</CallLogs>'
    return body.encode(_ENCODING, 'xmlcharrefreplace')


def message_path(userid: str, key: str) -> str:
    """Return the ``<messageId>`` path the phone uses to address one message."""
    return _MESSAGE_PATH.format(userid=userid, key=key)


def _message_info_xml(userid: str, message: VoiceMessage) -> str:
    """Render one ``<messageInfo>``.

    Child order follows the specification's examples: duration, callingPartyInfo,
    then the state markers, then time and messageId. The markers are valueless
    elements that are simply absent when false.
    """
    calling_party = ''
    if message.caller_name:
        calling_party += f'<name>{escape(message.caller_name)}</name>'
    if message.caller_number:
        calling_party += f'<address>tel:{escape(message.caller_number)}</address>'

    markers = ''
    if message.read:
        markers += '<read/>'
    if message.urgent:
        markers += '<urgent/>'

    return (
        '<messageInfo>'
        f'<duration>{message.duration_ms}</duration>'
        f'<callingPartyInfo>{calling_party}</callingPartyInfo>'
        f'{markers}'
        f'<time>{message.time_ms}</time>'
        f'<messageId>{escape(message_path(userid, message.key))}</messageId>'
        '</messageInfo>'
    )


def render_voice_messages(userid: str, messages: list[VoiceMessage]) -> bytes:
    """Render the ``<VoiceMessagingMessages>`` list document (metadata only)."""
    inner = ''.join(_message_info_xml(userid, message) for message in messages)
    body = (
        f'{_VOICE_DECL}<VoiceMessagingMessages xmlns="{_NS}">'
        f'<messageInfoList>{inner}</messageInfoList>'
        '</VoiceMessagingMessages>'
    )
    return body.encode(_VOICE_ENCODING, 'xmlcharrefreplace')


def render_voice_message(userid: str, message: VoiceMessage, media: bytes) -> bytes:
    """Render a single ``<VoiceMessage>``, carrying the recording inline.

    XSI has no separate media URL: the audio travels base64-encoded inside the
    document, which is why this is the one response whose size tracks the length
    of the recording.
    """
    content = b64encode(media).decode('ascii')
    body = (
        f'{_VOICE_DECL}<VoiceMessage xmlns="{_NS}">'
        f'{_message_info_xml(userid, message)}'
        '<messageMediaContent>'
        '<description></description>'
        f'<mediaType>{_MEDIA_TYPE}</mediaType>'
        f'<content>{content}</content>'
        '</messageMediaContent>'
        '</VoiceMessage>'
    )
    return body.encode(_VOICE_ENCODING, 'xmlcharrefreplace')
