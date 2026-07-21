# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""wazo-phoned plugin: serve Wazo call history to Yealink phones over XSI.

A Yealink phone provisioned with ``bw.xsi.enable = 1`` fetches its "Network
CallLog" from the BroadWorks XSI path
``/com.broadsoft.xsi-actions/v2.0/user/<id>/directories/CallLogs``. Wazo is not a
BroadWorks server, so this plugin answers just that endpoint family, backed by
wazo-call-logd, turning the phone's otherwise local-only missed/placed/received
lists into the tenant's real per-user call history.

Mounting note: the phone hits a FIXED, unprefixed path. wazo-phoned's own routes
live under ``/0.1`` (via ``create_blueprint_api``), so we cannot use that helper —
we register our own Flask blueprint at the application root so the raw
``/com.broadsoft.xsi-actions/...`` URL resolves on phoned's phone-facing port
(9498), which the phones already reach for the remote phonebook.

Auth/data access: the plugin reuses phoned's service token (kept current via
``token_changed_subscribe``) for its confd and call-logd clients. That token's
policy must grant confd endpoint/line read and ``call-logd.users.*.cdr.read`` —
the plugin's install step adds those ACLs (see wazo/rules).
"""

from __future__ import annotations

import logging

from flask import Blueprint
from flask_restful import Api
from wazo_call_logd_client import Client as CallLogdClient
from wazo_confd_client import Client as ConfdClient

from .http import CallLogsListResource, CallLogsResource

logger = logging.getLogger(__name__)

_XSI_CALLLOGS = (
    '/com.broadsoft.xsi-actions/v2.0/user/<userid>/directories/CallLogs'
)
_DEFAULT_CALL_LOGD = {'host': 'localhost', 'port': 9298, 'prefix': None, 'https': False}


class Plugin:
    def load(self, dependencies: dict) -> None:
        app = dependencies['app']
        config = dependencies['config']

        confd_client = ConfdClient(**config['confd'])
        call_logd_client = CallLogdClient(**config.get('call_logd', _DEFAULT_CALL_LOGD))

        token_changed_subscribe = dependencies['token_changed_subscribe']
        token_changed_subscribe(confd_client.set_token)
        token_changed_subscribe(call_logd_client.set_token)

        blueprint = Blueprint('optimogo_xsi', __name__)
        api = Api(blueprint)
        class_kwargs = {
            'confd_client': confd_client,
            'call_logd_client': call_logd_client,
        }
        # The combined endpoint is registered with and without a trailing slash
        # because the phone requests "/CallLogs/" (trailing) for the combined
        # list but "/CallLogs/Placed" (no trailing) for a type.
        api.add_resource(
            CallLogsResource,
            _XSI_CALLLOGS,
            _XSI_CALLLOGS + '/',
            resource_class_kwargs=class_kwargs,
            endpoint='optimogo_xsi_calllogs',
        )
        api.add_resource(
            CallLogsListResource,
            _XSI_CALLLOGS + '/<list_type>',
            resource_class_kwargs=class_kwargs,
            endpoint='optimogo_xsi_calllogs_type',
        )
        app.register_blueprint(blueprint)
        logger.info('optimogo XSI call-log plugin loaded at %s', _XSI_CALLLOGS)
