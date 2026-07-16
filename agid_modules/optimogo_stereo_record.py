# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""wazo-agid shim: make the dialplan recording path record dual-channel (stereo).

wazo-agid has no entry-point plugin mechanism — it loads modules by importing every
``.py`` in ``wazo_agid/modules/`` (`from wazo_agid.modules import *` in
``wazo_agid/bin/agid.py``). This file is installed into that directory by the
plugin's ``wazo/rules`` so it is imported at agid startup.

At import it replaces ``wazo_agid.modules.call_recording._start_mix_monitor`` (the
OUTGOING-call / dialplan recording path) with a version that records each direction
to its own feed and merges them — the same helpers the wazo-calld path uses. This
also stops the corrupted recordings caused by the stock path applying the
``WAZO_MIXMONITOR_OPTIONS='D'`` (interleave) option to a ``.wav`` file, which writes
interleaved samples into a mono 8 kHz container (played back ~2x slow). The patched
version ignores that global entirely.

Everything is wrapped in a broad try/except: a failure here must NOT break
``from wazo_agid.modules import *`` (that would take down agid and all call routing).
On any error we log and leave the stock behaviour in place.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MARKER = '_optimogo_stereo'

try:
    import uuid

    from wazo_agid import dialplan_variables as dv
    from wazo_agid.modules import call_recording

    from wazo_calld_optimogo.record import build_app_args

    def _start_mix_monitor_stereo(agi):
        tenant_uuid = agi.get_variable(dv.TENANT_UUID)
        recording_uuid = str(uuid.uuid4())
        filename = call_recording.CALL_RECORDING_FILENAME_TEMPLATE.format(
            tenant_uuid=tenant_uuid,
            recording_uuid=recording_uuid,
        )
        agi.appexec('MixMonitor', build_app_args(filename))
        agi.set_variable(dv.RECORDING_UUID, recording_uuid)
        agi.set_variable('WAZO_CALL_RECORD_ACTIVE', '1')

    if not getattr(call_recording._start_mix_monitor, _MARKER, False):
        setattr(_start_mix_monitor_stereo, _MARKER, True)
        call_recording._start_mix_monitor = _start_mix_monitor_stereo
        logger.info(
            'optimogo: agid _start_mix_monitor patched for dual-channel recording'
        )
except Exception:  # noqa: BLE001 - never let a shim error break agid startup
    logger.exception(
        'optimogo: failed to enable dual-channel agid recording; leaving stock path'
    )
