# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""wazo-phoned plugin: serve Wazo call history and voicemail to Yealink phones over XSI.

A Yealink phone provisioned with ``bw.xsi.enable = 1`` fetches its "Network
CallLog" from the BroadWorks XSI path
``/com.broadsoft.xsi-actions/v2.0/user/<id>/directories/CallLogs``, and with
``bw.voice_mail.visual.enable = 1`` it drives visual voicemail from
``…/VoiceMessagingMessages``. Wazo is not a BroadWorks server, so this plugin
answers just those two endpoint families — backed by wazo-call-logd and
wazo-calld — turning the phone's local-only lists and its dial-the-IVR voicemail
key into the tenant's real call history and message list.

Mounting note: the phone hits a FIXED, unprefixed path. wazo-phoned's own routes
live under ``/0.1`` (via ``create_blueprint_api``), so we cannot use that helper —
we register our own Flask blueprint at the application root so the raw
``/com.broadsoft.xsi-actions/...`` URL resolves on phoned's phone-facing port
(9498), which the phones already reach for the remote phonebook.

Auth/data access: the plugin reuses phoned's service token (kept current via
``token_changed_subscribe``) for its confd, call-logd and calld clients. That
token's policy must grant confd endpoint/line/voicemail read,
``call-logd.users.*.cdr.read`` and the calld voicemail ACLs (see wazo/rules).
"""

from __future__ import annotations

import logging

from flask import Blueprint
from flask_restful import Api
from wazo_call_logd_client import Client as CallLogdClient
from wazo_calld_client import Client as CalldClient
from wazo_confd_client import Client as ConfdClient

from . import routes

logger = logging.getLogger(__name__)

_DEFAULT_CALL_LOGD = {'host': 'localhost', 'port': 9298, 'prefix': None, 'https': False}
_DEFAULT_CALLD = {'host': 'localhost', 'port': 9500, 'prefix': None, 'https': False}


class Plugin:
    def load(self, dependencies: dict) -> None:
        app = dependencies['app']
        config = dependencies['config']

        confd_client = ConfdClient(**config['confd'])
        call_logd_client = CallLogdClient(**config.get('call_logd', _DEFAULT_CALL_LOGD))
        calld_client = CalldClient(**config.get('calld', _DEFAULT_CALLD))

        token_changed_subscribe = dependencies['token_changed_subscribe']
        token_changed_subscribe(confd_client.set_token)
        token_changed_subscribe(call_logd_client.set_token)
        token_changed_subscribe(calld_client.set_token)

        blueprint = Blueprint('optimogo_xsi', __name__)
        api = Api(blueprint)
        routes.register(
            api,
            call_log_kwargs={
                'confd_client': confd_client,
                'call_logd_client': call_logd_client,
            },
            voicemail_kwargs={
                'confd_client': confd_client,
                'calld_client': calld_client,
            },
        )
        app.register_blueprint(blueprint)
        logger.info(
            'optimogo XSI plugin loaded at %s and %s',
            routes.CALLLOGS,
            routes.VOICEMAIL_PATHS[0],
        )
