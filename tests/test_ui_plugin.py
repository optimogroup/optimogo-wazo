import pytest

pytest.importorskip('wazo_ui')

import flask  # noqa: E402

from wazo_dird_optimogo.ui.plugin import Plugin  # noqa: E402
from wazo_ui.plugins.dird_source.form import DirdSourceForm  # noqa: E402
from wazo_ui.plugins.identity.form import IdentityForm  # noqa: E402


@pytest.mark.needs_ui
def test_load_injects_config_field_and_registers_blueprint():
    app = flask.Flask(__name__)
    app.config['WTF_CSRF_ENABLED'] = False
    app.secret_key = 'test'

    Plugin().load({'flask': app})

    # The blueprint is registered (so its templates/ folder joins the loader).
    assert 'optimogo_source' in app.blueprints

    # The config sub-form is bound onto DirdSourceForm, additively: a fresh
    # instance carries optimogo_config AND the stock backend configs.
    with app.test_request_context():
        form = DirdSourceForm(meta={'csrf': False})
        assert 'optimogo_config' in form._fields
        assert 'csv_ws_config' in form._fields  # stock field untouched
        # the injected sub-form carries our config fields
        assert 'lookup_url' in form.optimogo_config.form._fields
        assert 'api_key' in form.optimogo_config.form._fields


@pytest.mark.needs_ui
def test_load_is_idempotent():
    app = flask.Flask(__name__)
    # Loading twice (e.g. across worker reloads) must not raise.
    Plugin().load({'flask': app})
    app2 = flask.Flask(__name__)
    Plugin().load({'flask': app2})
    assert hasattr(DirdSourceForm, 'optimogo_config')


@pytest.mark.needs_ui
def test_load_adds_optimogo_authentication_method():
    app = flask.Flask(__name__)
    app.config['WTF_CSRF_ENABLED'] = False
    app.secret_key = 'test'

    Plugin().load({'flask': app})

    choices = IdentityForm.authentication_method.kwargs['choices']
    values = [value for value, _label in choices]
    # added, exactly once, with the expected label
    assert ('optimogo', 'OptimoGo') in choices
    assert values.count('optimogo') == 1
    # stock choices preserved (additive, not replaced)
    for stock in ('default', 'native', 'saml', 'ldap'):
        assert stock in values


@pytest.mark.needs_ui
def test_load_optimogo_authentication_method_is_idempotent():
    # Loading twice (e.g. across worker reloads) must not duplicate the choice.
    Plugin().load({'flask': flask.Flask(__name__)})
    Plugin().load({'flask': flask.Flask(__name__)})

    values = [value for value, _label in IdentityForm.authentication_method.kwargs['choices']]
    assert values.count('optimogo') == 1
