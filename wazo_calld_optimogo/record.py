# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stereo (dual-channel) replacement for ``wazo_calld.plugin_helpers.ami.record_start``.

Stock Wazo records a call with a single ``MixMonitor(<uuid>.wav)`` action and no
options, so both parties are summed into one mono channel. This module builds the
same action but adds MixMonitor's per-direction feeds:

  * ``r(<uuid>.rx.wav)`` — audio *received* by the recorded channel
  * ``t(<uuid>.tx.wav)`` — audio *transmitted* to the recorded channel

plus a ``Command`` that runs when recording stops and merges the two feeds into a
2-channel file at the original ``<uuid>.wav`` path (see ``stereo_merge``). The stock
mono mix is still written to ``<uuid>.wav`` during the call, so if the merge fails
the recording degrades to mono rather than being lost.

The signature mirrors the vendor function exactly so it can be monkeypatched in
(see ``plugin.py``): ``wazo-call-logd`` indexes ``<uuid>.wav`` unchanged.
"""

from __future__ import annotations

import logging
import os

from requests import RequestException

logger = logging.getLogger(__name__)

# Merge is invoked as a module (`python3 -m wazo_calld_optimogo.stereo_merge`) so it
# resolves via the installed package regardless of console-script bin location.
PYTHON_BIN = '/usr/bin/python3'
MERGE_MODULE = 'wazo_calld_optimogo.stereo_merge'

# Per-direction feeds are written OUTSIDE the tenant monitor/ directory so that dir
# only ever contains the single registered <uuid>.wav — call-logd registers only the
# main file (via its MixMonitorStart CEL), but keeping the recordings dir clean of
# transient/failed feeds protects any disk-based consumer, backup, or retention scan.
# Must be writable by the asterisk process (MixMonitor writes the feeds); created by
# the plugin's install rules as asterisk:asterisk.
FEED_TMP_DIR = '/var/spool/asterisk/stereo-record-tmp'

_WAV_SUFFIX = '.wav'
_RX_SUFFIX = '.rx.wav'
_TX_SUFFIX = '.tx.wav'


def feed_paths(filename: str) -> tuple[str, str]:
    """Return (rx_path, tx_path) in the feed temp dir, keyed to the recording uuid."""
    stem = os.path.basename(filename)
    if stem.endswith(_WAV_SUFFIX):
        stem = stem[: -len(_WAV_SUFFIX)]
    return (
        os.path.join(FEED_TMP_DIR, stem + _RX_SUFFIX),
        os.path.join(FEED_TMP_DIR, stem + _TX_SUFFIX),
    )


def build_destination(channel: str, filename: str, options: str | None = None) -> dict:
    """Build the AMI ``MixMonitor`` action fields for a dual-channel recording.

    Pure (no I/O, no wazo_calld import) so it is unit-testable off-box.
    """
    rx_path, tx_path = feed_paths(filename)
    feed_options = f'r({rx_path})t({tx_path})'
    combined_options = f'{options}{feed_options}' if options else feed_options
    merge_command = f'{PYTHON_BIN} -m {MERGE_MODULE} {filename} {rx_path} {tx_path}'
    return {
        'Channel': channel,
        'File': filename,
        'options': combined_options,
        'Command': merge_command,
    }


def build_app_args(filename: str) -> str:
    """Build the ``MixMonitor`` *application* argument string (``file,options,command``).

    Used by the wazo-agid path, which starts recording via ``agi.appexec('MixMonitor',
    ...)`` rather than the AMI action. Same feeds + merge command as the calld path.
    """
    rx_path, tx_path = feed_paths(filename)
    options = f'r({rx_path})t({tx_path})'
    command = f'{PYTHON_BIN} -m {MERGE_MODULE} {filename} {rx_path} {tx_path}'
    return f'{filename},{options},{command}'


def record_start(amid, channel, filename, options=None):
    """Drop-in replacement for ``ami.record_start`` producing a stereo recording."""
    destination = build_destination(channel, filename, options)
    try:
        amid.action('MixMonitor', destination)
    except RequestException as e:
        # Imported lazily so this module stays importable without wazo_calld
        # (keeps the off-box unit tests dependency-free).
        from wazo_calld.plugin_helpers.ami import WazoAmidError

        raise WazoAmidError(amid, e)
