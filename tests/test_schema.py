import pytest
from marshmallow import ValidationError
from wazo_dird_optimogo.schema import load_config


def test_minimal_config_gets_defaults(valid_config):
    cfg = load_config(valid_config)
    assert cfg['name'] == 'optimogo'
    assert cfg['connect_timeout'] == 0.4
    assert cfg['read_timeout'] == 0.8
    assert cfg['cache_ttl'] == 60
    assert cfg['negative_cache_ttl'] == 30
    assert cfg['cache_max_entries'] == 5000
    assert cfg['breaker_failure_threshold'] == 5
    assert cfg['breaker_cooldown'] == 30.0
    assert cfg['ambiguous_prefix'] == 'Maybe: '
    assert cfg['search_min_term_length'] == 3
    assert cfg['search_max_term_length'] == 64
    assert cfg['search_limit'] == 25
    assert cfg['verify_certificate'] is True
    assert cfg['unique_column'] == 'id'
    assert cfg['first_matched_columns'] == ['number']
    assert cfg['searched_columns'] == ['name', 'number']


def test_missing_required_fields_raise():
    with pytest.raises(ValidationError):
        load_config({'name': 'optimogo'})  # no lookup_url / api_key


def test_bad_timeout_rejected(valid_config):
    bad = dict(valid_config, connect_timeout=0)
    with pytest.raises(ValidationError):
        load_config(bad)


def test_overrides_applied(valid_config):
    cfg = load_config(dict(valid_config, cache_ttl=120, ambiguous_prefix='? '))
    assert cfg['cache_ttl'] == 120
    assert cfg['ambiguous_prefix'] == '? '
