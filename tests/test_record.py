# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the stereo MixMonitor action builder (no wazo_calld needed)."""

from wazo_calld_optimogo import record


MONITOR = '/var/lib/wazo/sounds/tenants/t-uuid/monitor/rec-uuid.wav'
RX = f'{record.FEED_TMP_DIR}/rec-uuid.rx.wav'
TX = f'{record.FEED_TMP_DIR}/rec-uuid.tx.wav'


def test_feed_paths_are_outside_the_monitor_dir():
    rx, tx = record.feed_paths(MONITOR)
    assert (rx, tx) == (RX, TX)
    # The recordings (monitor) directory must never hold the feeds.
    assert '/monitor/' not in rx and '/monitor/' not in tx


def test_feed_paths_key_on_basename_uuid():
    rx, tx = record.feed_paths('/any/dir/abc123.wav')
    assert rx == f'{record.FEED_TMP_DIR}/abc123.rx.wav'
    assert tx == f'{record.FEED_TMP_DIR}/abc123.tx.wav'


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


def test_build_app_args_is_file_options_command():
    args = record.build_app_args(MONITOR)
    # agid uses the application form: File,options,command
    assert args == (
        f'{MONITOR},r({RX})t({TX}),'
        f'{record.PYTHON_BIN} -m {record.MERGE_MODULE} {MONITOR} {RX} {TX}'
    )
    # the app-arg feeds and the AMI-action feeds must be identical
    dest = record.build_destination('chan', MONITOR)
    assert dest['options'] in args and dest['Command'] in args


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
