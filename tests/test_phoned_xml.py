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
from wazo_phoned_optimogo import xml


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
