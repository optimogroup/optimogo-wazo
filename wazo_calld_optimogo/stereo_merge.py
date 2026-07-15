# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Merge MixMonitor's per-direction feeds into one 2-channel recording.

Invoked by Asterisk when a MixMonitor recording stops (via the ``Command`` field
built in :mod:`wazo_calld_optimogo.record`)::

    python3 -m wazo_calld_optimogo.stereo_merge <out.wav> <rx.wav> <tx.wav>

``rx`` (received by the recorded channel) becomes the **left** channel and ``tx``
(transmitted to it) the **right**. The result atomically replaces ``out.wav``.

Safety contract: the caller has already written a mono mix to ``out.wav``. If
anything here fails (a feed missing/empty, ``sox`` error, unreadable file) we log
it and leave that mono file in place — a recording is never destroyed. The rx/tx
feeds are removed only after a successful merge (kept otherwise, for debugging).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger('wazo_calld_optimogo.stereo_merge')

SOX_BIN = '/usr/bin/sox'
SOX_TIMEOUT_SECONDS = 120
_LOG_PATH = '/var/log/asterisk/wazo-optimogo-stereo-merge.log'
_TMP_SUFFIX = '.stereo.tmp.wav'


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _feed_ready(path: str) -> bool:
    try:
        return os.path.getsize(path) > 0
    except OSError:
        return False


def merge(out_path: str, rx_path: str, tx_path: str) -> bool:
    """Merge rx (left) + tx (right) into a stereo file at ``out_path``.

    Returns True if ``out_path`` was replaced with the 2-channel file, False if the
    existing (mono) ``out_path`` was left untouched.
    """
    for feed in (rx_path, tx_path):
        if not _feed_ready(feed):
            logger.warning(
                'stereo merge skipped: feed missing or empty (%s); keeping mono %s',
                feed,
                out_path,
            )
            return False

    tmp_path = out_path + _TMP_SUFFIX
    # Force the classic WAVE_FORMAT_PCM header (`wavpcm`, 16-bit signed) rather than
    # sox's default WAVE_FORMAT_EXTENSIBLE for multichannel — the latter is valid
    # but trips stricter WAV parsers (incl. Python's `wave` and some browsers). This
    # matches the stock mono recording format so playback/download is unchanged.
    command = [
        SOX_BIN,
        '-M',
        rx_path,
        tx_path,
        '-t',
        'wavpcm',
        '-e',
        'signed-integer',
        '-b',
        '16',
        tmp_path,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=SOX_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        logger.error('stereo merge failed: sox not found at %s', SOX_BIN)
        _safe_remove(tmp_path)
        return False
    except subprocess.TimeoutExpired:
        logger.error('stereo merge failed: sox timed out for %s', out_path)
        _safe_remove(tmp_path)
        return False
    except subprocess.CalledProcessError as e:
        logger.error(
            'stereo merge failed: sox exited %s for %s: %s',
            e.returncode,
            out_path,
            (e.stderr or b'').decode('utf-8', 'replace').strip(),
        )
        _safe_remove(tmp_path)
        return False

    try:
        os.replace(tmp_path, out_path)  # atomic within the same filesystem
    except OSError as e:
        logger.error('stereo merge failed: could not replace %s: %s', out_path, e)
        _safe_remove(tmp_path)
        return False

    _safe_remove(rx_path)
    _safe_remove(tx_path)
    logger.info('stereo merge ok: %s', out_path)
    return True


def _setup_logging() -> None:
    handler: logging.Handler
    try:
        handler = logging.FileHandler(_LOG_PATH)
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        sys.stderr.write(
            'usage: python3 -m wazo_calld_optimogo.stereo_merge '
            '<out.wav> <rx.wav> <tx.wav>\n'
        )
        return 2
    _setup_logging()
    out_path, rx_path, tx_path = args
    return 0 if merge(out_path, rx_path, tx_path) else 1


if __name__ == '__main__':
    raise SystemExit(main())
