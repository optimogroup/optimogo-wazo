# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Map Wazo voicemail boxes and messages onto the XSI VoiceMessagingMessages model.

A Yealink phone provisioned with ``bw.voice_mail.visual.enable = 1`` stops dialling
the voicemail IVR and instead drives a real message list: it fetches
``/VoiceMessagingMessages``, downloads a chosen message's audio inline (base64
inside the XML), and can mark messages read/unread or delete them.

Two Wazo details shape this mapping:

  * **"read" is a folder, not a flag.** A new message lands in the voicemail's
    ``new`` folder (or ``urgent``) and moves to ``old`` once it has been listened
    to, so XSI's ``<read/>`` marker is folder membership and MarkAsRead /
    MarkAsUnread are folder moves. Folder ids are read from the voicemail's own
    definition rather than hardcoded — they are per-voicemail rows in Wazo, not
    global constants.
  * **A message id is only unique within its box.** The phone hands our
    ``<messageId>`` straight back to us in a URL, so the id we publish has to
    carry the voicemail it belongs to as well.

Which boxes a user sees mirrors wazo-calld's own ``voicemail_type='all'`` rule
(``VoicemailsService._get_voicemails_configs``): the user's personal box, if any,
plus every box in their tenant marked ``accesstype=global``. At Optimo nobody has
a personal box and the shared reception box (1099) is global, so a desk phone
shows exactly the queue's messages — the same list the OptimoGo webapp shows.
"""

from __future__ import annotations

from typing import NamedTuple

from .exceptions import MessageKeyError, VoicemailFolderError

FOLDER_NEW = 'new'
FOLDER_OLD = 'old'
FOLDER_URGENT = 'urgent'
# Wazo folder types that mean "the user has not listened to this yet". A message
# left as urgent is unread *and* urgent; XSI carries those as separate markers.
UNREAD_FOLDER_TYPES = (FOLDER_NEW, FOLDER_URGENT)

# XSI message ids must survive a round trip through a URL path segment: the phone
# reads the <messageId> we publish and GETs/PUTs/DELETEs it back verbatim. Wazo
# message ids are "<unix-time>-<8 hex digits>" and never contain a '.', so '.'
# safely joins the voicemail id to the message id.
_KEY_SEPARATOR = '.'

_MILLIS_PER_SECOND = 1000


class VoiceMessage(NamedTuple):
    """One voicemail message in phone-facing form (an XSI ``messageInfo``)."""

    key: str
    voicemail_id: int
    message_id: str
    caller_name: str
    caller_number: str
    duration_ms: int
    time_ms: int
    read: bool
    urgent: bool


def build_key(voicemail_id: int, message_id: str) -> str:
    """Join a voicemail id and message id into the id we publish to the phone."""
    return f'{voicemail_id}{_KEY_SEPARATOR}{message_id}'


def parse_key(key: str) -> tuple[int, str]:
    """Split a published message id back into (voicemail_id, message_id).

    Raises MessageKeyError for anything we did not produce — the phone should
    only ever echo our own ids back, so a malformed key means a stale or forged
    request and must not be turned into a lookup against an arbitrary box.
    """
    voicemail_part, separator, message_id = key.partition(_KEY_SEPARATOR)
    if not separator or not message_id:
        raise MessageKeyError(f'malformed message id {key!r}')
    try:
        voicemail_id = int(voicemail_part)
    except ValueError as exc:
        raise MessageKeyError(f'message id {key!r} has no voicemail id') from exc
    return voicemail_id, message_id


def folder_id(voicemail: dict, folder_type: str) -> int:
    """Return the id of the folder of ``folder_type`` in a calld voicemail detail.

    Raises VoicemailFolderError when the box has no such folder: without it we
    cannot express "read"/"unread" for that box, and silently doing nothing would
    leave the phone showing a state the server never applied.
    """
    for folder in voicemail.get('folders') or []:
        if folder.get('type') == folder_type:
            return folder['id']
    raise VoicemailFolderError(
        f'voicemail {voicemail.get("id")} has no {folder_type!r} folder'
    )


def messages_from_voicemail(voicemail: dict) -> list[VoiceMessage]:
    """Flatten one calld voicemail detail into VoiceMessages across its folders."""
    voicemail_id = voicemail['id']
    messages = []
    for folder in voicemail.get('folders') or []:
        folder_type = folder.get('type')
        for message in folder.get('messages') or []:
            messages.append(
                _to_message(message, voicemail_id, folder_type)
            )
    return messages


def _to_message(message: dict, voicemail_id: int, folder_type: str) -> VoiceMessage:
    message_id = message['id']
    return VoiceMessage(
        key=build_key(voicemail_id, message_id),
        voicemail_id=voicemail_id,
        message_id=message_id,
        caller_name=message.get('caller_id_name') or '',
        caller_number=message.get('caller_id_num') or '',
        # calld reports whole seconds; XSI durations and times are milliseconds.
        duration_ms=(message.get('duration') or 0) * _MILLIS_PER_SECOND,
        time_ms=(message.get('timestamp') or 0) * _MILLIS_PER_SECOND,
        read=folder_type not in UNREAD_FOLDER_TYPES,
        urgent=folder_type == FOLDER_URGENT,
    )


def sort_newest_first(messages: list[VoiceMessage]) -> list[VoiceMessage]:
    """Order messages the way the phone lists them: most recent first.

    Messages arrive grouped by folder (all new, then all old); the phone renders
    the list in the order it is given, so they have to be merged by time or a
    week-old read message would sit above this morning's new one.
    """
    return sorted(messages, key=lambda message: message.time_ms, reverse=True)
