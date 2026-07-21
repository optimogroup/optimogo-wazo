# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for XSI XML rendering (wazo_phoned_optimogo.xml).

We assert on the exact rendered bytes rather than parsing them: the output is
ours and deterministic, and the whole point is to pin the precise wire format a
Yealink phone accepts (bare lowercase root, field order, encoding). Asserting on
the literal string also means we never run an XML parser over anything.
"""

import pytest

from wazo_phoned_optimogo.call_logs import MISSED, PLACED, RECEIVED, CallLogEntry
from wazo_phoned_optimogo.voicemail import VoiceMessage
from wazo_phoned_optimogo import xml

USERID = 'wazo@pbx.local.optimo.group'


def _entry(log_id='1', number='0400111222', name='Robyn Campbell',
           time='2026-07-21T11:56:07.628+10:00', country_code=''):
    return CallLogEntry(
        log_id=log_id, number=number, name=name, time=time, country_code=country_code
    )


def test_render_list_uses_bare_lowercase_root_without_namespace():
    # The critical shape: a sub-endpoint returns <placed>, NOT <CallLogs>, and
    # the root carries no xmlns.
    raw = xml.render_list(PLACED, [_entry()]).decode('latin-1')
    assert '<placed>' in raw and '</placed>' in raw
    assert 'CallLogs' not in raw
    assert 'xmlns' not in raw


def test_render_list_declares_iso_8859_1():
    raw = xml.render_list(MISSED, [])
    assert raw.startswith(b'<?xml version="1.0" encoding="ISO-8859-1"?>')


def test_render_list_entry_field_order_matches_spec():
    raw = xml.render_list(RECEIVED, [_entry()]).decode('latin-1')
    assert (
        '<callLogsEntry>'
        '<countryCode></countryCode>'
        '<phoneNumber>0400111222</phoneNumber>'
        '<name>Robyn Campbell</name>'
        '<time>2026-07-21T11:56:07.628+10:00</time>'
        '<callLogId>1</callLogId>'
        '</callLogsEntry>'
    ) in raw


def test_render_list_empty_produces_empty_root():
    raw = xml.render_list(PLACED, []).decode('latin-1')
    assert raw.endswith('<placed></placed>')


def test_render_list_escapes_xml_special_characters():
    raw = xml.render_list(RECEIVED, [_entry(name='Tom & Jerry <LLC>')]).decode('latin-1')
    assert '<name>Tom &amp; Jerry &lt;LLC&gt;</name>' in raw


def test_render_list_latin1_encodes_accented_name():
    raw = xml.render_list(RECEIVED, [_entry(name='José')])
    assert raw.decode('latin-1').count('<name>José</name>') == 1
    assert isinstance(raw, bytes)


def test_render_list_rejects_unknown_list_name():
    with pytest.raises(ValueError):
        xml.render_list('sent', [])


def test_render_combined_wraps_all_three_lists_with_namespace_in_order():
    buckets = {PLACED: [_entry(log_id='p')], RECEIVED: [], MISSED: [_entry(log_id='m')]}
    raw = xml.render_combined(buckets).decode('latin-1')
    assert '<CallLogs xmlns="http://schema.broadsoft.com/xsi">' in raw
    # lists appear once each, in placed/received/missed order
    assert raw.index('<placed>') < raw.index('<received>') < raw.index('<missed>')


def test_render_combined_places_entries_in_correct_list():
    buckets = {PLACED: [_entry(log_id='p')], RECEIVED: [], MISSED: [_entry(log_id='m')]}
    raw = xml.render_combined(buckets).decode('latin-1')
    assert '<received></received>' in raw
    assert '<placed><callLogsEntry>' in raw
    assert '<callLogId>p</callLogId>' in raw
    assert '<callLogId>m</callLogId>' in raw


# --- voice messaging -------------------------------------------------------

def _message(key='2.1784612544-00000007', name='Jayden Smith',
             number='0488168739', duration_ms=3000, time_ms=1784612544000,
             read=False, urgent=False):
    return VoiceMessage(
        key=key,
        voicemail_id=2,
        message_id=key.partition('.')[2],
        caller_name=name,
        caller_number=number,
        duration_ms=duration_ms,
        time_ms=time_ms,
        read=read,
        urgent=urgent,
    )


def test_message_path_is_the_path_the_phone_fetches_back():
    # The phone appends this to the XSI base URL, so it must be a path (leading
    # slash, versioned, lowercase collection), not a bare id.
    assert xml.message_path(USERID, '2.abc') == (
        f'/v2.0/user/{USERID}/voicemessagingmessages/2.abc'
    )


def test_render_voice_messages_declares_utf8_and_the_xsi_namespace():
    raw = xml.render_voice_messages(USERID, [])
    assert raw.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert b'<VoiceMessagingMessages xmlns="http://schema.broadsoft.com/xsi">' in raw


def test_render_voice_messages_empty_still_carries_the_list_element():
    # An empty <messageInfoList> is what tells the phone "no messages"; omitting
    # the element makes it treat the document as malformed.
    raw = xml.render_voice_messages(USERID, []).decode('utf-8')
    assert '<messageInfoList></messageInfoList>' in raw


def test_render_voice_messages_field_order_matches_spec():
    raw = xml.render_voice_messages(USERID, [_message()]).decode('utf-8')
    assert (
        '<messageInfo>'
        '<duration>3000</duration>'
        '<callingPartyInfo>'
        '<name>Jayden Smith</name>'
        '<address>tel:0488168739</address>'
        '</callingPartyInfo>'
        '<time>1784612544000</time>'
        f'<messageId>/v2.0/user/{USERID}/voicemessagingmessages/2.1784612544-00000007'
        '</messageId>'
        '</messageInfo>'
    ) in raw


def test_read_and_urgent_markers_are_valueless_elements_between_party_and_time():
    raw = xml.render_voice_messages(
        USERID, [_message(read=True, urgent=True)]
    ).decode('utf-8')
    assert '</callingPartyInfo><read/><urgent/><time>' in raw


def test_unread_message_omits_the_read_marker_entirely():
    raw = xml.render_voice_messages(USERID, [_message(read=False)]).decode('utf-8')
    assert '<read/>' not in raw
    assert '</callingPartyInfo><time>' in raw


def test_missing_caller_name_leaves_an_empty_calling_party_child():
    raw = xml.render_voice_messages(USERID, [_message(name='')]).decode('utf-8')
    assert '<callingPartyInfo><address>tel:0488168739</address></callingPartyInfo>' in raw


def test_render_voice_messages_escapes_xml_special_characters():
    raw = xml.render_voice_messages(
        USERID, [_message(name='Tom & Jerry <LLC>')]
    ).decode('utf-8')
    assert '<name>Tom &amp; Jerry &lt;LLC&gt;</name>' in raw


def test_render_voice_message_wraps_info_and_base64_media():
    raw = xml.render_voice_message(USERID, _message(), b'RIFF....WAVE').decode('utf-8')
    assert '<VoiceMessage xmlns="http://schema.broadsoft.com/xsi">' in raw
    assert '<messageInfo>' in raw
    assert (
        '<messageMediaContent>'
        '<description></description>'
        '<mediaType>WAV</mediaType>'
        '<content>UklGRi4uLi5XQVZF</content>'
        '</messageMediaContent>'
    ) in raw


def test_render_voice_message_media_is_base64_of_the_exact_bytes():
    from base64 import b64decode
    import re

    media = bytes(range(256))
    raw = xml.render_voice_message(USERID, _message(), media).decode('utf-8')
    encoded = re.search(r'<content>(.*)</content>', raw).group(1)
    assert b64decode(encoded) == media
