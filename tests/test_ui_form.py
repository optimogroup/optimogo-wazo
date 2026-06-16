import pytest

pytest.importorskip('wazo_ui')

import flask  # noqa: E402

from wazo_dird_optimogo.ui.form import OptimoGoForm  # noqa: E402


@pytest.fixture
def app_ctx():
    app = flask.Flask(__name__)
    app.config['WTF_CSRF_ENABLED'] = False
    app.secret_key = 'test'
    with app.test_request_context():
        yield


@pytest.mark.needs_ui
def test_form_exposes_required_and_advanced_fields(app_ctx):
    form = OptimoGoForm(meta={'csrf': False})
    names = set(form._fields)
    assert {'lookup_url', 'api_key'} <= names
    assert {
        'connect_timeout', 'read_timeout', 'cache_ttl', 'negative_cache_ttl',
        'cache_max_entries', 'breaker_failure_threshold', 'breaker_cooldown',
        'ambiguous_prefix', 'search_min_term_length', 'search_max_term_length',
        'search_limit', 'verify_certificate',
    } <= names


@pytest.mark.needs_ui
def test_lookup_url_and_api_key_are_required(app_ctx):
    form = OptimoGoForm(meta={'csrf': False})  # no data submitted
    assert form.validate() is False
    assert 'lookup_url' in form.errors
    assert 'api_key' in form.errors


@pytest.mark.needs_ui
def test_advanced_defaults_match_backend_schema(app_ctx):
    form = OptimoGoForm(meta={'csrf': False})
    assert form.connect_timeout.default == 0.4
    assert form.read_timeout.default == 0.8
    assert form.cache_ttl.default == 60
    assert form.negative_cache_ttl.default == 30
    assert form.cache_max_entries.default == 5000
    assert form.breaker_failure_threshold.default == 5
    assert form.breaker_cooldown.default == 30.0
    assert form.ambiguous_prefix.default == 'Maybe: '
    assert form.search_min_term_length.default == 3
    assert form.search_max_term_length.default == 64
    assert form.search_limit.default == 25
    assert form.verify_certificate.default is True
