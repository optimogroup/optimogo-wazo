# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for CDR -> XSI entry classification and mapping (call_logs.py)."""

from wazo_phoned_optimogo import call_logs
from wazo_phoned_optimogo.call_logs import MISSED, PLACED, RECEIVED

USER = 'aa3a2125-d8bf-4a3a-b039-de9cd95ce318'
OTHER = '11111111-1111-1111-1111-111111111111'


def _cdr(**overrides):
    base = {
        'id': 1,
        'start': '2026-07-21T11:56:07.628181+10:00',
        'answered': True,
        'source_user_uuid': None,
        'destination_user_uuid': None,
        'requested_user_uuid': None,
        'source_extension': '0438572104',
        'source_name': 'Robyn Campbell',
        'source_internal_name': '',
        'destination_extension': '1000',
        'destination_name': 'Jayden Smith',
        'requested_extension': '61363911836',
        'requested_name': 'Jayden Smith',
    }
    base.update(overrides)
    return base


# --- classify -------------------------------------------------------------

def test_classify_placed_when_user_is_source():
    cdr = _cdr(source_user_uuid=USER, answered=False)
    assert call_logs.classify(cdr, USER) == PLACED


def test_classify_received_when_user_is_answered_destination():
    cdr = _cdr(destination_user_uuid=USER, answered=True)
    assert call_logs.classify(cdr, USER) == RECEIVED


def test_classify_missed_when_user_is_unanswered_destination():
    cdr = _cdr(destination_user_uuid=USER, answered=False)
    assert call_logs.classify(cdr, USER) == MISSED


def test_classify_received_via_requested_user_uuid():
    # Inbound calls carry the callee on requested_user_uuid in some flows.
    cdr = _cdr(destination_user_uuid=None, requested_user_uuid=USER, answered=True)
    assert call_logs.classify(cdr, USER) == RECEIVED


def test_classify_source_wins_over_destination_for_call_to_self():
    cdr = _cdr(source_user_uuid=USER, destination_user_uuid=USER)
    assert call_logs.classify(cdr, USER) == PLACED


def test_classify_drops_cdr_not_involving_user():
    cdr = _cdr(source_user_uuid=OTHER, destination_user_uuid=OTHER)
    assert call_logs.classify(cdr, USER) is None


# --- other party / to_entry ----------------------------------------------

def test_placed_entry_shows_destination_party():
    cdr = _cdr(source_user_uuid=USER, destination_extension='1002',
               destination_name='Matt Coote')
    entry = call_logs.to_entry(cdr, PLACED)
    assert entry.number == '1002'
    assert entry.name == 'Matt Coote'


def test_placed_entry_falls_back_to_requested_when_no_destination():
    cdr = _cdr(source_user_uuid=USER, destination_extension=None,
               destination_name=None, requested_extension='000',
               requested_name='Emergency')
    entry = call_logs.to_entry(cdr, PLACED)
    assert entry.number == '000'
    assert entry.name == 'Emergency'


def test_received_entry_shows_source_party():
    cdr = _cdr(destination_user_uuid=USER)
    entry = call_logs.to_entry(cdr, RECEIVED)
    assert entry.number == '0438572104'
    assert entry.name == 'Robyn Campbell'


def test_entry_name_falls_back_to_source_internal_name():
    cdr = _cdr(destination_user_uuid=USER, source_name='', source_internal_name='Pat')
    entry = call_logs.to_entry(cdr, MISSED)
    assert entry.name == 'Pat'


def test_entry_log_id_is_cdr_id_as_string():
    entry = call_logs.to_entry(_cdr(id=191, source_user_uuid=USER), PLACED)
    assert entry.log_id == '191'


def test_entry_country_code_is_blank():
    entry = call_logs.to_entry(_cdr(source_user_uuid=USER), PLACED)
    assert entry.country_code == ''


# --- time formatting ------------------------------------------------------

def test_time_truncated_to_milliseconds_with_colon_offset():
    entry = call_logs.to_entry(
        _cdr(source_user_uuid=USER, start='2026-07-21T11:56:07.628181+10:00'), PLACED
    )
    assert entry.time == '2026-07-21T11:56:07.628+10:00'


def test_time_missing_yields_empty_string():
    entry = call_logs.to_entry(_cdr(source_user_uuid=USER, start=None), PLACED)
    assert entry.time == ''


def test_time_unparseable_yields_empty_string_not_error():
    entry = call_logs.to_entry(_cdr(source_user_uuid=USER, start='not-a-time'), PLACED)
    assert entry.time == ''


# --- split ----------------------------------------------------------------

def test_split_buckets_by_kind_and_preserves_order():
    cdrs = [
        _cdr(id=1, source_user_uuid=USER),                      # placed
        _cdr(id=2, destination_user_uuid=USER, answered=True),  # received
        _cdr(id=3, destination_user_uuid=USER, answered=False),  # missed
        _cdr(id=4, source_user_uuid=USER),                      # placed
        _cdr(id=5, source_user_uuid=OTHER, destination_user_uuid=OTHER),  # dropped
    ]
    buckets = call_logs.split_call_logs(cdrs, USER)
    assert [e.log_id for e in buckets[PLACED]] == ['1', '4']
    assert [e.log_id for e in buckets[RECEIVED]] == ['2']
    assert [e.log_id for e in buckets[MISSED]] == ['3']


def test_split_returns_all_three_lists_even_when_empty():
    buckets = call_logs.split_call_logs([], USER)
    assert set(buckets) == {PLACED, RECEIVED, MISSED}
    assert all(v == [] for v in buckets.values())
