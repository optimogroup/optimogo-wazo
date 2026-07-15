# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""wazo-calld plugin: enable dual-channel (stereo) call recordings.

Stock wazo-calld starts every recording with ``ami.record_start(..., options=None)``,
producing a mono mix of both parties. There is no config seam to change the options,
so this plugin replaces ``wazo_calld.plugin_helpers.ami.record_start`` at load time
with :func:`wazo_calld_optimogo.record.record_start`, which records each direction to
its own feed and merges them into a 2-channel file when the call ends.

This is a module-attribute swap, not a vendor-file edit: ``services.py`` calls
``ami.record_start(...)`` (looked up on the module at call time), so replacing the
attribute is picked up by all call paths, survives wazo-calld package upgrades, and
is undone by simply disabling this plugin.

Scope: pause/resume of a recording (``ami.record_resume``) is left stock — a
resumed recording degrades to mono. This deployment does not use manual
pause/resume, so that path is intentionally not patched.
"""

from __future__ import annotations

import logging

from wazo_calld.plugin_helpers import ami as ami_helpers

from .record import record_start as stereo_record_start

logger = logging.getLogger(__name__)

_PATCH_MARKER = '_optimogo_stereo_recording'


class Plugin:
    def load(self, dependencies: dict) -> None:
        if getattr(ami_helpers.record_start, _PATCH_MARKER, False):
            logger.info('optimogo stereo recording already active; nothing to do')
            return
        setattr(stereo_record_start, _PATCH_MARKER, True)
        ami_helpers.record_start = stereo_record_start
        logger.info(
            'optimogo stereo recording enabled: ami.record_start now records '
            'dual-channel (rx=left, tx=right)'
        )
