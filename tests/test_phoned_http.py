# Copyright 2026 Optimo Group
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end tests for the XSI HTTP surface (routing + resources).

These drive a real Flask app through the plugin's own URL map, because the URL
map is where this integration has actually gone wrong before: a phone constructs
its own URLs from the paths we publish, and a rule that swallows another rule
fails as an empty screen on the handset with a perfectly healthy-looking server.

The Wazo services are faked at the client boundary (the same objects plugin.py
builds from wazo-confd/wazo-calld/wazo-call-logd), so the fakes return the shapes
those APIs really return — including a global voicemail whose folder ids are rows
rather than constants.
"""

import base64

import pytest
from flask import Flask
from flask_restful import Api

from wazo_phoned_optimogo import routes

SIP_USER = 'cuejqnsy'
SIP_PASSWORD = 'slevcxeb'
USER_UUID = 'aa3a2125-d8bf-4a3a-b039-de9cd95ce318'
TENANT_UUID = '02b639ea-a2d2-4314-ab30-cc7c1e490fbe'
USERID = 'wazo@pbx.local.optimo.group'

SHARED_VOICEMAIL_ID = 2
OTHER_TENANT_VOICEMAIL_ID = 99
NEW_MESSAGE_ID = '1784612544-00000007'
OLD_MESSAGE_ID = '1784366381-00000006'
RECORDING = b'RIFF$\x00\x00\x00WAVEfmt '

XSI = '/com.broadsoft.xsi-actions/v2.0/user/' + USERID
VOICEMAIL_URL = XSI + '/VoiceMessagingMessages'
LOWER_VOICEMAIL_URL = XSI + '/voicemessagingmessages'

FOLDER_INBOX_ID = 1
FOLDER_OLD_ID = 2


def _auth_header(sip_user=SIP_USER, password=SIP_PASSWORD):
    basic = base64.b64encode(f'{USERID}:{password}'.encode()).decode()
    sip = base64.b64encode(sip_user.encode()).decode()
    return {'Authorization': f'BroadWorksSIP basic="{basic}", sipUser="{sip}"'}


def _message(message_id, timestamp, name='Jayden Smith', number='0488168739'):
    return {
        'id': message_id,
        'duration': 3,
        'timestamp': timestamp,
        'caller_id_name': name,
        'caller_id_num': number,
        'transcription': None,
        'empty': False,
    }


class FakeConfd:
    """wazo-confd stand-in: endpoint/line lookup plus voicemail associations."""

    def __init__(self, global_voicemail_ids=(SHARED_VOICEMAIL_ID,), personal=None):
        self._global_ids = list(global_voicemail_ids)
        self._personal = personal
        self.endpoints_sip = self._Endpoints()
        self.lines = self._Lines()
        self.voicemails = self._Voicemails(self._global_ids)
        self.global_list_tenants = self.voicemails.tenants

    class _Endpoints:
        def list(self, name, recurse):
            if name != SIP_USER:
                return {'items': []}
            return {'items': [{'uuid': 'ep-uuid'}]}

        def get(self, uuid):
            return {
                'uuid': uuid,
                'name': SIP_USER,
                'tenant_uuid': TENANT_UUID,
                'auth_section_options': [
                    ['username', SIP_USER],
                    ['password', SIP_PASSWORD],
                ],
                'line': {'id': 1},
            }

    class _Lines:
        def get(self, line_id):
            return {'id': line_id, 'users': [{'uuid': USER_UUID}]}

    class _Voicemails:
        def __init__(self, ids):
            self._ids = ids
            self.tenants = []

        def list(self, accesstype, tenant_uuid):
            self.tenants.append((accesstype, tenant_uuid))
            return {'items': [{'id': vm_id} for vm_id in self._ids]}

    class _User:
        def __init__(self, personal):
            self._personal = personal

        def get_voicemail(self):
            return self._personal

    def users(self, uuid):
        return self._User(self._personal)


class FakeCalld:
    """wazo-calld stand-in tracking the mutations the XSI actions should cause."""

    def __init__(self, boxes=None):
        self.voicemails = self._Voicemails(boxes if boxes is not None else _boxes())

    class _Voicemails:
        def __init__(self, boxes):
            self._boxes = boxes
            self.moved = []
            self.deleted = []

        def get_voicemail(self, voicemail_id):
            return self._boxes[voicemail_id]

        def get_voicemail_recording(self, voicemail_id, message_id):
            return RECORDING

        def move_voicemail_message(self, voicemail_id, message_id, folder_id):
            self.moved.append((voicemail_id, message_id, folder_id))

        def delete_voicemail_message(self, voicemail_id, message_id):
            self.deleted.append((voicemail_id, message_id))


def _boxes(new=None, old=None):
    """One shared box holding a new and a read message, mirroring 1099."""
    new = [_message(NEW_MESSAGE_ID, 1784612544)] if new is None else new
    old = [_message(OLD_MESSAGE_ID, 1784366381)] if old is None else old
    return {
        SHARED_VOICEMAIL_ID: {
            'id': SHARED_VOICEMAIL_ID,
            'number': '1099',
            'folders': [
                {'id': FOLDER_INBOX_ID, 'name': 'inbox', 'type': 'new', 'messages': new},
                {'id': FOLDER_OLD_ID, 'name': 'old', 'type': 'old', 'messages': old},
            ],
        },
        OTHER_TENANT_VOICEMAIL_ID: {
            'id': OTHER_TENANT_VOICEMAIL_ID,
            'number': '2099',
            'folders': [
                {
                    'id': FOLDER_INBOX_ID,
                    'name': 'inbox',
                    'type': 'new',
                    'messages': [_message('1784000000-0000000f', 1784000000)],
                }
            ],
        },
    }


class FakeCallLogd:
    class _Cdr:
        def list_for_user(self, user_uuid, limit, recurse):
            return {'items': []}

    cdr = _Cdr()


@pytest.fixture
def services():
    return {'confd': FakeConfd(), 'calld': FakeCalld()}


def _client(services):
    """A test client wired to the plugin's real URL map over the given fakes."""
    app = Flask(__name__)
    api = Api(app)
    routes.register(
        api,
        call_log_kwargs={
            'confd_client': services['confd'],
            'call_logd_client': FakeCallLogd(),
        },
        voicemail_kwargs={
            'confd_client': services['confd'],
            'calld_client': services['calld'],
        },
    )
    return app.test_client()


@pytest.fixture
def client(services):
    return _client(services)


def _key(voicemail_id=SHARED_VOICEMAIL_ID, message_id=NEW_MESSAGE_ID):
    return f'{voicemail_id}.{message_id}'


# --- routing ---------------------------------------------------------------

@pytest.mark.parametrize('url', [VOICEMAIL_URL, VOICEMAIL_URL + '/', LOWER_VOICEMAIL_URL])
def test_message_list_is_served_on_every_spelling_and_slash(client, url):
    response = client.get(url, headers=_auth_header())
    assert response.status_code == 200
    assert b'<VoiceMessagingMessages' in response.data


def test_get_on_the_single_segment_route_returns_a_message_not_a_405(client):
    # The regression this guards: MarkAll* and <messageId> occupy the same
    # position in the URL space, so a second Flask rule there would shadow this
    # one and a message download would come back 405/404.
    response = client.get(f'{VOICEMAIL_URL}/{_key()}', headers=_auth_header())
    assert response.status_code == 200
    assert b'<VoiceMessage ' in response.data


def test_put_on_the_same_route_is_treated_as_mark_all(client, services):
    response = client.put(f'{VOICEMAIL_URL}/MarkAllAsRead', headers=_auth_header())
    assert response.status_code == 204
    assert services['calld'].voicemails.moved == [
        (SHARED_VOICEMAIL_ID, NEW_MESSAGE_ID, FOLDER_OLD_ID)
    ]


def test_two_segment_route_reaches_the_per_message_mark(client, services):
    response = client.put(
        f'{VOICEMAIL_URL}/{_key()}/MarkAsRead', headers=_auth_header()
    )
    assert response.status_code == 204
    assert services['calld'].voicemails.moved == [
        (SHARED_VOICEMAIL_ID, NEW_MESSAGE_ID, FOLDER_OLD_ID)
    ]


def test_call_log_routes_still_resolve_alongside_the_voicemail_ones(client):
    assert client.get(XSI + '/directories/CallLogs/', headers=_auth_header()).status_code == 200
    assert client.get(XSI + '/directories/CallLogs/Missed', headers=_auth_header()).status_code == 200


# --- authentication --------------------------------------------------------

@pytest.mark.parametrize(
    'method,url',
    [
        ('get', VOICEMAIL_URL),
        ('get', VOICEMAIL_URL + '/' + _key()),
        ('delete', VOICEMAIL_URL + '/' + _key()),
        ('put', VOICEMAIL_URL + '/MarkAllAsRead'),
        ('put', VOICEMAIL_URL + '/' + _key() + '/MarkAsRead'),
    ],
)
def test_every_voicemail_endpoint_challenges_without_credentials(client, method, url):
    response = getattr(client, method)(url)
    assert response.status_code == 401
    assert response.headers['WWW-Authenticate'] == 'BroadWorksSIP'


def test_wrong_sip_password_does_not_expose_messages(client):
    response = client.get(VOICEMAIL_URL, headers=_auth_header(password='WRONG'))
    assert response.status_code == 401


def test_delete_is_refused_without_credentials(client, services):
    client.delete(f'{VOICEMAIL_URL}/{_key()}')
    assert services['calld'].voicemails.deleted == []


# --- which mailboxes a user sees -------------------------------------------

def test_global_voicemails_are_scoped_to_the_users_tenant(client, services):
    client.get(VOICEMAIL_URL, headers=_auth_header())
    assert services['confd'].global_list_tenants == [('global', TENANT_UUID)]


def test_personal_voicemail_is_listed_alongside_the_global_one(services):
    services['confd'] = FakeConfd(personal={'id': OTHER_TENANT_VOICEMAIL_ID})
    response = _client(services).get(VOICEMAIL_URL, headers=_auth_header())
    body = response.data.decode('utf-8')
    assert f'/{OTHER_TENANT_VOICEMAIL_ID}.1784000000-0000000f' in body
    assert f'/{SHARED_VOICEMAIL_ID}.{NEW_MESSAGE_ID}' in body


def test_a_message_key_naming_an_unreadable_box_is_refused(client, services):
    # The key is attacker-controllable: it comes back from the phone. Naming a
    # voicemail the user may not read must not fetch it.
    response = client.get(
        f'{VOICEMAIL_URL}/{_key(voicemail_id=OTHER_TENANT_VOICEMAIL_ID)}',
        headers=_auth_header(),
    )
    assert response.status_code == 404


def test_deleting_from_an_unreadable_box_is_refused(client, services):
    client.delete(
        f'{VOICEMAIL_URL}/{_key(voicemail_id=OTHER_TENANT_VOICEMAIL_ID)}',
        headers=_auth_header(),
    )
    assert services['calld'].voicemails.deleted == []


# --- message list content --------------------------------------------------

def test_list_publishes_message_ids_the_phone_can_fetch_back(client):
    body = client.get(VOICEMAIL_URL, headers=_auth_header()).data.decode('utf-8')
    published = f'/v2.0/user/{USERID}/voicemessagingmessages/{_key()}'
    assert f'<messageId>{published}</messageId>' in body
    # and that path, appended to the XSI root, is a route we serve
    assert client.get(
        '/com.broadsoft.xsi-actions' + published, headers=_auth_header()
    ).status_code == 200


def test_list_marks_the_old_folder_message_read_and_the_inbox_one_unread(client):
    body = client.get(VOICEMAIL_URL, headers=_auth_header()).data.decode('utf-8')
    new_entry, old_entry = body.split('<messageInfo>')[1:]
    assert '<read/>' not in new_entry
    assert '<read/>' in old_entry


def test_empty_mailbox_returns_an_empty_list_not_an_error(services):
    services['calld'] = FakeCalld(boxes=_boxes(new=[], old=[]))
    response = _client(services).get(VOICEMAIL_URL, headers=_auth_header())
    assert response.status_code == 200
    assert b'<messageInfoList></messageInfoList>' in response.data


# --- single message actions ------------------------------------------------

def test_message_download_carries_the_recording_base64_encoded(client):
    body = client.get(
        f'{VOICEMAIL_URL}/{_key()}', headers=_auth_header()
    ).data.decode('utf-8')
    expected = base64.b64encode(RECORDING).decode()
    assert f'<content>{expected}</content>' in body


def test_delete_removes_the_named_message(client, services):
    response = client.delete(f'{VOICEMAIL_URL}/{_key()}', headers=_auth_header())
    assert response.status_code == 204
    assert services['calld'].voicemails.deleted == [
        (SHARED_VOICEMAIL_ID, NEW_MESSAGE_ID)
    ]


def test_mark_as_unread_moves_a_read_message_back_to_the_inbox(client, services):
    response = client.put(
        f'{VOICEMAIL_URL}/{_key(message_id=OLD_MESSAGE_ID)}/MarkAsUnread',
        headers=_auth_header(),
    )
    assert response.status_code == 204
    assert services['calld'].voicemails.moved == [
        (SHARED_VOICEMAIL_ID, OLD_MESSAGE_ID, FOLDER_INBOX_ID)
    ]


def test_mark_all_as_read_skips_messages_already_read(client, services):
    client.put(f'{VOICEMAIL_URL}/MarkAllAsRead', headers=_auth_header())
    moved_ids = [message_id for _, message_id, _ in services['calld'].voicemails.moved]
    assert OLD_MESSAGE_ID not in moved_ids


def test_mark_all_as_unread_moves_only_the_read_one(client, services):
    client.put(f'{VOICEMAIL_URL}/MarkAllAsUnread', headers=_auth_header())
    assert services['calld'].voicemails.moved == [
        (SHARED_VOICEMAIL_ID, OLD_MESSAGE_ID, FOLDER_INBOX_ID)
    ]


@pytest.mark.parametrize('action', ['markallasread', 'MARKALLASREAD', 'markAllAsRead'])
def test_mark_all_action_names_are_case_insensitive(client, services, action):
    # The specification itself spells these inconsistently; the phone's actual
    # casing is not something we get to choose.
    response = client.put(f'{VOICEMAIL_URL}/{action}', headers=_auth_header())
    assert response.status_code == 204


def test_an_unknown_single_segment_put_is_not_mistaken_for_an_action(client, services):
    response = client.put(f'{VOICEMAIL_URL}/DoSomethingElse', headers=_auth_header())
    assert response.status_code == 404
    assert services['calld'].voicemails.moved == []


def test_a_malformed_message_key_is_a_404_not_a_500(client):
    response = client.get(f'{VOICEMAIL_URL}/not-a-key', headers=_auth_header())
    assert response.status_code == 404


def test_a_key_for_a_message_that_no_longer_exists_is_a_404(client):
    response = client.get(
        f'{VOICEMAIL_URL}/{_key(message_id="1700000000-00000001")}',
        headers=_auth_header(),
    )
    assert response.status_code == 404
