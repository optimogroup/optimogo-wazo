# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""The XSI URL map a Yealink phone drives.

Kept apart from plugin.py so the routing — which request lands on which resource,
the part that has actually bitten us — can be exercised without the wazo client
packages plugin.py imports to build its HTTP clients.

The paths are fixed by BroadWorks, not by us: the phone is told a host and port
and constructs everything else itself, so every string here has to match what the
firmware emits rather than what would read best.
"""

from __future__ import annotations

from flask_restful import Api

from .http import (
    CallLogsListResource,
    CallLogsResource,
    VoiceMessageMarkResource,
    VoiceMessageResource,
    VoiceMessagesResource,
)

XSI_USER = '/com.broadsoft.xsi-actions/v2.0/user/<userid>'
CALLLOGS = XSI_USER + '/directories/CallLogs'
# The specification capitalises the collection in the endpoint but spells it
# lowercase inside the <messageId> paths its own examples publish — and the phone
# builds its fetch/mark/delete URLs from those paths. Both spellings are served so
# the list and the actions it links to cannot disagree.
VOICEMAIL_PATHS = (
    XSI_USER + '/VoiceMessagingMessages',
    XSI_USER + '/voicemessagingmessages',
)


def register(api: Api, call_log_kwargs: dict, voicemail_kwargs: dict) -> None:
    """Attach every XSI resource to ``api`` with its phone-facing URLs."""
    # The combined call-log endpoint is registered with and without a trailing
    # slash because the phone requests "/CallLogs/" (trailing) for the combined
    # list but "/CallLogs/Placed" (no trailing) for a type.
    api.add_resource(
        CallLogsResource,
        CALLLOGS,
        CALLLOGS + '/',
        resource_class_kwargs=call_log_kwargs,
        endpoint='optimogo_xsi_calllogs',
    )
    api.add_resource(
        CallLogsListResource,
        CALLLOGS + '/<list_type>',
        resource_class_kwargs=call_log_kwargs,
        endpoint='optimogo_xsi_calllogs_type',
    )
    _add_voicemail(
        api,
        VoiceMessagesResource,
        '',
        voicemail_kwargs,
        'optimogo_xsi_voicemail_messages',
        trailing_slash=True,
    )
    # One rule for the single-segment position: it carries either a message id
    # (GET/DELETE) or a MarkAll* action (PUT), told apart by method inside the
    # resource — see VoiceMessageResource.
    _add_voicemail(
        api,
        VoiceMessageResource,
        '/<segment>',
        voicemail_kwargs,
        'optimogo_xsi_voicemail_message',
    )
    _add_voicemail(
        api,
        VoiceMessageMarkResource,
        '/<message_key>/<action>',
        voicemail_kwargs,
        'optimogo_xsi_voicemail_message_mark',
    )


def _add_voicemail(
    api: Api,
    resource,
    suffix: str,
    class_kwargs: dict,
    endpoint: str,
    trailing_slash: bool = False,
) -> None:
    """Register one voicemail resource under every spelling of the collection."""
    urls = [base + suffix for base in VOICEMAIL_PATHS]
    if trailing_slash:
        urls += [base + suffix + '/' for base in VOICEMAIL_PATHS]
    api.add_resource(
        resource, *urls, resource_class_kwargs=class_kwargs, endpoint=endpoint
    )
