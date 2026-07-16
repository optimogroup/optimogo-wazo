import pytest

pytest.importorskip('wazo_dird')

from marshmallow import ValidationError  # noqa: E402

from wazo_dird_optimogo.dird_view.plugin import OptimoGoView  # noqa: E402
from wazo_dird_optimogo.dird_view.schemas import source_schema  # noqa: E402


@pytest.mark.needs_dird
def test_view_targets_optimogo_backend():
    assert OptimoGoView.backend == 'optimogo'
    assert OptimoGoView.list_resource is not None
    assert OptimoGoView.item_resource is not None


@pytest.mark.needs_dird
def test_source_schema_requires_lookup_url_and_api_key():
    with pytest.raises(ValidationError):
        source_schema.load({'name': 'optimogo'})  # missing lookup_url + api_key


@pytest.mark.needs_dird
def test_source_schema_applies_backend_defaults():
    loaded = source_schema.load(
        {
            'name': 'optimogo',
            'lookup_url': 'https://opt.example.com/api/wazo/dird/acme',
            'api_key': 'secret',
        }
    )
    assert loaded['connect_timeout'] == 0.4
    assert loaded['read_timeout'] == 0.8
    assert loaded['cache_ttl'] == 60
    assert loaded['negative_cache_ttl'] == 30
    assert loaded['cache_max_entries'] == 5000
    assert loaded['breaker_failure_threshold'] == 5
    assert loaded['breaker_cooldown'] == 30.0
    assert loaded['ambiguous_prefix'] == 'Maybe: '
    assert loaded['search_min_term_length'] == 3
    assert loaded['search_max_term_length'] == 64
    assert loaded['search_limit'] == 25
    assert loaded['verify_certificate'] is True
    # The create path (this view schema) must also populate the column configs —
    # a minimal create previously stored these empty, so caller-ID showed no name.
    assert loaded['first_matched_columns'] == ['number']
    assert loaded['searched_columns'] == ['name', 'number']
    assert loaded['format_columns'] == {
        'name': '{display_name}',
        'reverse': '{display_name}',
    }
