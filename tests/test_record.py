# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the stereo MixMonitor action builder (no wazo_calld needed)."""

from wazo_calld_optimogo import record


MONITOR = '/var/lib/wazo/sounds/tenants/t-uuid/monitor/rec-uuid.wav'
RX = '/var/lib/wazo/sounds/tenants/t-uuid/monitor/rec-uuid.rx.wav'
TX = '/var/lib/wazo/sounds/tenants/t-uuid/monitor/rec-uuid.tx.wav'


def test_feed_paths_derives_rx_tx_from_wav():
    assert record.feed_paths(MONITOR) == (RX, TX)


def test_feed_paths_without_wav_suffix():
    assert record.feed_paths('/tmp/rec') == ('/tmp/rec.rx.wav', '/tmp/rec.tx.wav')


def test_build_destination_records_both_directions():
    dest = record.build_destination('PJSIP/abc-0001', MONITOR)
    assert dest['Channel'] == 'PJSIP/abc-0001'
    assert dest['File'] == MONITOR  # call-logd still indexes this path
    # rx is the receive feed, tx the transmit feed — both captured separately.
    assert dest['options'] == f'r({RX})t({TX})'


def test_build_destination_command_invokes_merge_with_three_paths():
    dest = record.build_destination('PJSIP/abc-0001', MONITOR)
    assert dest['Command'] == (
        f'{record.PYTHON_BIN} -m {record.MERGE_MODULE} {MONITOR} {RX} {TX}'
    )


def test_build_destination_preserves_existing_options():
    dest = record.build_destination('chan', MONITOR, options='b')
    assert dest['options'] == f'br({RX})t({TX})'


class _FakeAmid:
    def __init__(self):
        self.actions = []

    def action(self, name, destination):
        self.actions.append((name, destination))


def test_record_start_issues_mixmonitor_action():
    amid = _FakeAmid()
    record.record_start(amid, 'PJSIP/abc-0001', MONITOR, None)
    assert len(amid.actions) == 1
    name, dest = amid.actions[0]
    assert name == 'MixMonitor'
    assert dest['File'] == MONITOR
    assert dest['options'] == f'r({RX})t({TX})'
    assert dest['Command'].endswith(f'{MONITOR} {RX} {TX}')
