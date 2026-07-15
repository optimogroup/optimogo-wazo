# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the rx/tx -> stereo merge step.

The safety contract is the important part: whenever the merge cannot produce a
valid 2-channel file it must leave the pre-written mono file untouched (a
recording is never destroyed).
"""

import shutil
import struct
import subprocess
import wave

import pytest

from wazo_calld_optimogo import stereo_merge


def _write_wav(path, samples, channels=1, rate=8000):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b''.join(struct.pack('<h', s) for s in samples))


def _channels(path):
    with wave.open(str(path), 'rb') as w:
        return w.getnchannels()


def test_merge_missing_feed_keeps_mono(tmp_path):
    out = tmp_path / 'rec.wav'
    _write_wav(out, [1, 2, 3])  # the mono mix already on disk
    rx = tmp_path / 'rec.rx.wav'  # never created
    tx = tmp_path / 'rec.tx.wav'

    assert stereo_merge.merge(str(out), str(rx), str(tx)) is False
    assert _channels(out) == 1  # untouched


def test_merge_empty_feed_keeps_mono(tmp_path):
    out = tmp_path / 'rec.wav'
    _write_wav(out, [1, 2, 3])
    rx = tmp_path / 'rec.rx.wav'
    tx = tmp_path / 'rec.tx.wav'
    _write_wav(rx, [4, 5, 6])
    tx.write_bytes(b'')  # zero-length transmit feed

    assert stereo_merge.merge(str(out), str(rx), str(tx)) is False
    assert _channels(out) == 1


def test_merge_sox_failure_keeps_mono_and_cleans_tmp(tmp_path, monkeypatch):
    out = tmp_path / 'rec.wav'
    _write_wav(out, [1, 2, 3])
    rx = tmp_path / 'rec.rx.wav'
    tx = tmp_path / 'rec.tx.wav'
    _write_wav(rx, [4, 5, 6])
    _write_wav(tx, [7, 8, 9])

    def _boom(*a, **k):
        raise subprocess.CalledProcessError(1, a[0], stderr=b'sox: boom')

    monkeypatch.setattr(stereo_merge.subprocess, 'run', _boom)

    assert stereo_merge.merge(str(out), str(rx), str(tx)) is False
    assert _channels(out) == 1  # mono preserved
    assert not (tmp_path / ('rec.wav' + stereo_merge._TMP_SUFFIX)).exists()
    assert rx.exists() and tx.exists()  # feeds kept for debugging on failure


def test_merge_sox_missing_binary_keeps_mono(tmp_path, monkeypatch):
    out = tmp_path / 'rec.wav'
    _write_wav(out, [1, 2, 3])
    rx = tmp_path / 'rec.rx.wav'
    tx = tmp_path / 'rec.tx.wav'
    _write_wav(rx, [4, 5, 6])
    _write_wav(tx, [7, 8, 9])
    monkeypatch.setattr(stereo_merge, 'SOX_BIN', '/nonexistent/sox')

    assert stereo_merge.merge(str(out), str(rx), str(tx)) is False
    assert _channels(out) == 1


@pytest.mark.needs_sox
def test_merge_success_produces_stereo(tmp_path, monkeypatch):
    sox = shutil.which('sox')
    if not sox:
        pytest.skip('sox binary not available')
    monkeypatch.setattr(stereo_merge, 'SOX_BIN', sox)

    out = tmp_path / 'rec.wav'
    rx = tmp_path / 'rec.rx.wav'
    tx = tmp_path / 'rec.tx.wav'
    _write_wav(out, [0] * 10)               # mono mix placeholder
    _write_wav(rx, [1000] * 10)             # "left" party
    _write_wav(tx, [-1000] * 10)            # "right" party

    assert stereo_merge.merge(str(out), str(rx), str(tx)) is True
    assert _channels(out) == 2               # now stereo
    assert not rx.exists() and not tx.exists()  # feeds cleaned up on success


def test_main_rejects_wrong_arg_count():
    assert stereo_merge.main(['only', 'two']) == 2


@pytest.mark.needs_sox
def test_main_returns_zero_on_success(tmp_path, monkeypatch):
    sox = shutil.which('sox')
    if not sox:
        pytest.skip('sox binary not available')
    monkeypatch.setattr(stereo_merge, 'SOX_BIN', sox)
    monkeypatch.setattr(stereo_merge, '_LOG_PATH', str(tmp_path / 'merge.log'))

    out = tmp_path / 'rec.wav'
    rx = tmp_path / 'rec.rx.wav'
    tx = tmp_path / 'rec.tx.wav'
    _write_wav(out, [0] * 10)
    _write_wav(rx, [1000] * 10)
    _write_wav(tx, [-1000] * 10)

    assert stereo_merge.main([str(out), str(rx), str(tx)]) == 0
    assert _channels(out) == 2
