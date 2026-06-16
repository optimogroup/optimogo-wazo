import json
import pytest
import responses
from wazo_dird_optimogo.http_client import OptimoGoClient
from wazo_dird_optimogo.exceptions import (
    OptimoGoAuthError, OptimoGoUnavailable, OptimoGoLookupError,
)

BASE = 'https://opt.example.com/api/wazo/dird/acme'


def make_client():
    return OptimoGoClient(base_url=BASE, api_key='secret-key',
                          connect_timeout=0.4, read_timeout=0.8, verify=True)


@responses.activate
def test_post_returns_parsed_json_and_sends_bearer():
    responses.add(responses.POST, f'{BASE}/reverse',
                  json={'match': None}, status=200,
                  content_type='application/json')
    body = make_client().post('/reverse', {'number': '+61399999999'})
    assert body == {'match': None}
    sent = responses.calls[0].request
    assert sent.headers['Authorization'] == 'Bearer secret-key'
    assert json.loads(sent.body) == {'number': '+61399999999'}


@responses.activate
@pytest.mark.parametrize('status', [401, 403])
def test_auth_errors(status):
    responses.add(responses.POST, f'{BASE}/reverse', status=status,
                  json={}, content_type='application/json')
    with pytest.raises(OptimoGoAuthError):
        make_client().post('/reverse', {'number': '1'})


@responses.activate
@pytest.mark.parametrize('status', [429, 500, 503])
def test_unavailable_errors(status):
    responses.add(responses.POST, f'{BASE}/reverse', status=status,
                  json={}, content_type='application/json')
    with pytest.raises(OptimoGoUnavailable):
        make_client().post('/reverse', {'number': '1'})


@responses.activate
@pytest.mark.parametrize('status', [400, 408, 409, 422])
def test_other_4xx_is_lookup_error(status):
    responses.add(responses.POST, f'{BASE}/reverse', status=status,
                  json={}, content_type='application/json')
    with pytest.raises(OptimoGoLookupError):
        make_client().post('/reverse', {'number': '1'})


@responses.activate
def test_wrong_content_type_is_lookup_error():
    responses.add(responses.POST, f'{BASE}/reverse', body='hello',
                  status=200, content_type='text/plain')
    with pytest.raises(OptimoGoLookupError):
        make_client().post('/reverse', {'number': '1'})


@responses.activate
def test_malformed_json_is_lookup_error():
    responses.add(responses.POST, f'{BASE}/reverse', body='{not json',
                  status=200, content_type='application/json')
    with pytest.raises(OptimoGoLookupError):
        make_client().post('/reverse', {'number': '1'})
