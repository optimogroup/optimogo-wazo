import pytest
from wazo_auth_optimogo.config import load_config

_OK = {
    'optimogo_base_url': 'https://og.example.com',
    'tenant_schema': 'acme',
    'wazo_tenant_uuid': 't-uuid',
    'auth_bridge_key': 'secret',
}


def test_defaults_and_url():
    cfg = load_config(dict(_OK))
    assert cfg['introspect_base_url'] == 'https://og.example.com/api/wazo/auth/acme'
    assert cfg['verify_certificate'] is True
    assert cfg['connect_timeout'] == 2 and cfg['read_timeout'] == 4


@pytest.mark.parametrize('missing', list(_OK))
def test_missing_required_raises(missing):
    bad = {k: v for k, v in _OK.items() if k != missing}
    with pytest.raises(ValueError):
        load_config(bad)


def test_non_https_rejected():
    with pytest.raises(ValueError):
        load_config({**_OK, 'optimogo_base_url': 'http://og.example.com'})


def test_explicit_overrides_applied():
    cfg = load_config({
        **_OK,
        'verify_certificate': False,
        'connect_timeout': 5,
        'read_timeout': 10,
    })
    assert cfg['verify_certificate'] is False
    assert cfg['connect_timeout'] == 5
    assert cfg['read_timeout'] == 10


def test_trailing_slash_stripped_from_base_url():
    cfg = load_config({**_OK, 'optimogo_base_url': 'https://og.example.com/'})
    assert cfg['introspect_base_url'] == 'https://og.example.com/api/wazo/auth/acme'


def test_all_required_fields_propagated():
    cfg = load_config(dict(_OK))
    assert cfg['tenant_schema'] == 'acme'
    assert cfg['wazo_tenant_uuid'] == 't-uuid'
    assert cfg['auth_bridge_key'] == 'secret'


def test_extra_keys_ignored():
    """Extra keys like enabled/priority (from idp_plugins config) must not raise."""
    cfg = load_config({**_OK, 'enabled': True, 'priority': 0, 'unknown_key': 'whatever'})
    assert cfg['introspect_base_url'] == 'https://og.example.com/api/wazo/auth/acme'
    assert 'enabled' not in cfg
    assert 'priority' not in cfg
    assert 'unknown_key' not in cfg
