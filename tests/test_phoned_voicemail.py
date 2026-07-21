# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Wazo voicemail -> XSI mapping (wazo_phoned_optimogo.voicemail).

The fixtures below are trimmed copies of real wazo-calld responses for the Optimo
reception box (voicemail 2 / extension 1099), so the shapes here are the shapes
the plugin actually receives — folder ids that are per-voicemail rows, second
precision timestamps, and caller_id fields that are null rather than absent.
"""

import pytest

from wazo_phoned_optimogo import voicemail
from wazo_phoned_optimogo.exceptions import MessageKeyError, VoicemailFolderError

VOICEMAIL_ID = 2
NEW_MESSAGE_ID = '1784612544-00000007'
OLD_MESSAGE_ID = '1784366381-00000006'


def _message(message_id, timestamp, duration=3, name='Jayden Smith', number='0488168739'):
    return {
        'id': message_id,
        'duration': duration,
        'timestamp': timestamp,
        'caller_id_name': name,
        'caller_id_num': number,
        'transcription': None,
        'empty': False,
    }


def _voicemail(new=(), old=(), urgent=()):
    """A calld voicemail detail. Folder ids differ from folder types on purpose."""
    return {
        'id': VOICEMAIL_ID,
        'name': 'Optimo Reception',
        'number': '1099',
        'accesstype': 'global',
        'folders': [
            {'id': 1, 'name': 'inbox', 'type': 'new', 'messages': list(new)},
            {'id': 2, 'name': 'old', 'type': 'old', 'messages': list(old)},
            {'id': 3, 'name': 'urgent', 'type': 'urgent', 'messages': list(urgent)},
            {'id': 4, 'name': 'work', 'type': 'other', 'messages': []},
        ],
    }


# --- message keys ----------------------------------------------------------

def test_build_key_joins_voicemail_and_message():
    assert voicemail.build_key(VOICEMAIL_ID, NEW_MESSAGE_ID) == f'2.{NEW_MESSAGE_ID}'


def test_parse_key_round_trips_build_key():
    key = voicemail.build_key(VOICEMAIL_ID, NEW_MESSAGE_ID)
    assert voicemail.parse_key(key) == (VOICEMAIL_ID, NEW_MESSAGE_ID)


def test_parse_key_keeps_hyphens_in_message_id():
    # Wazo ids are "<unix-time>-<hex>"; the hyphen must not be read as a separator.
    _, message_id = voicemail.parse_key(f'2.{NEW_MESSAGE_ID}')
    assert message_id == '1784612544-00000007'


@pytest.mark.parametrize(
    'key',
    [
        '',                       # empty
        '1784612544-00000007',    # no voicemail id at all
        '2.',                     # voicemail id but no message
        '.1784612544-00000007',   # message but no voicemail id
        'two.1784612544-0000007',  # non-numeric voicemail id
    ],
)
def test_parse_key_rejects_anything_we_did_not_publish(key):
    with pytest.raises(MessageKeyError):
        voicemail.parse_key(key)


# --- folders ---------------------------------------------------------------

def test_folder_id_reads_the_id_from_the_voicemail_not_a_constant():
    detail = _voicemail()
    assert voicemail.folder_id(detail, voicemail.FOLDER_OLD) == 2
    assert voicemail.folder_id(detail, voicemail.FOLDER_NEW) == 1


def test_folder_id_raises_when_the_folder_is_absent():
    detail = {'id': VOICEMAIL_ID, 'folders': [{'id': 1, 'type': 'new', 'messages': []}]}
    with pytest.raises(VoicemailFolderError):
        voicemail.folder_id(detail, voicemail.FOLDER_OLD)


# --- message mapping -------------------------------------------------------

def test_new_folder_message_is_unread_and_not_urgent():
    detail = _voicemail(new=[_message(NEW_MESSAGE_ID, 1784612544)])
    message, = voicemail.messages_from_voicemail(detail)
    assert message.read is False
    assert message.urgent is False


def test_old_folder_message_is_read():
    detail = _voicemail(old=[_message(OLD_MESSAGE_ID, 1784366381)])
    message, = voicemail.messages_from_voicemail(detail)
    assert message.read is True


def test_urgent_folder_message_is_unread_and_urgent():
    detail = _voicemail(urgent=[_message('1784700000-00000009', 1784700000)])
    message, = voicemail.messages_from_voicemail(detail)
    assert message.read is False
    assert message.urgent is True


def test_durations_and_times_are_converted_to_milliseconds():
    detail = _voicemail(new=[_message(NEW_MESSAGE_ID, 1784612544, duration=7)])
    message, = voicemail.messages_from_voicemail(detail)
    assert message.duration_ms == 7000
    assert message.time_ms == 1784612544000


def test_null_caller_id_name_becomes_empty_string_without_losing_the_number():
    # calld sends caller_id_name: null for an external caller with no CNAM; the
    # number must still reach the phone so the entry is callable back.
    detail = _voicemail(
        old=[_message(OLD_MESSAGE_ID, 1784366381, name=None, number='0429311399')]
    )
    message, = voicemail.messages_from_voicemail(detail)
    assert message.caller_name == ''
    assert message.caller_number == '0429311399'


def test_message_carries_its_voicemail_so_actions_can_address_it():
    detail = _voicemail(new=[_message(NEW_MESSAGE_ID, 1784612544)])
    message, = voicemail.messages_from_voicemail(detail)
    assert message.voicemail_id == VOICEMAIL_ID
    assert message.message_id == NEW_MESSAGE_ID
    assert message.key == f'2.{NEW_MESSAGE_ID}'


def test_empty_voicemail_yields_no_messages():
    assert voicemail.messages_from_voicemail(_voicemail()) == []


def test_messages_are_collected_from_every_folder():
    detail = _voicemail(
        new=[_message(NEW_MESSAGE_ID, 1784612544)],
        old=[_message(OLD_MESSAGE_ID, 1784366381)],
    )
    assert len(voicemail.messages_from_voicemail(detail)) == 2


# --- ordering --------------------------------------------------------------

def test_sort_newest_first_interleaves_read_and_unread():
    # The bug this guards: messages arrive grouped by folder, so without sorting
    # an old-but-recent message would render below a new-but-older one.
    detail = _voicemail(
        new=[_message('1784000000-00000001', 1784000000)],
        old=[_message('1784999999-00000002', 1784999999)],
    )
    ordered = voicemail.sort_newest_first(voicemail.messages_from_voicemail(detail))
    assert [m.time_ms for m in ordered] == [1784999999000, 1784000000000]
    assert ordered[0].read is True
