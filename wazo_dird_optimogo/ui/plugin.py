import logging

from wtforms.fields import FormField

from wazo_ui.helpers.plugin import create_blueprint
from wazo_ui.plugins.dird_source.form import DirdSourceForm
from wazo_ui.plugins.identity.form import IdentityForm

from .form import OptimoGoForm

logger = logging.getLogger(__name__)

# (value, label) for the user Authentication Method dropdown. The value MUST
# equal the optimogo wazo_auth IDP's `authentication_method` — the auth-method
# gate compares the strings exactly. The label is display-only.
_OPTIMOGO_AUTH_METHOD = ('optimogo', 'OptimoGo')

# A route-less blueprint exists only so this package's templates/ folder joins
# Flask's Jinja search path. The stock dird_source view renders
# 'dird_source/form/form_optimogo.html', which resolves to the file we ship under
# templates/dird_source/form/ — no patching of wazo-ui's installed files.
optimogo_source = create_blueprint('optimogo_source', __name__)


def _add_optimogo_auth_method():
    """Add 'optimogo' to wazo-ui's user Authentication Method dropdown,
    additively and idempotently.

    IdentityForm.authentication_method is an unbound SelectField; its
    kwargs['choices'] list is read each time the form binds, so appending to it
    in place surfaces the new option on every future IdentityForm instantiation
    without touching wazo-ui's installed files. The guard keeps a second load()
    (gunicorn worker reload, test double-load) a no-op and leaves the stock
    choices intact.
    """
    choices = IdentityForm.authentication_method.kwargs['choices']
    if not any(value == _OPTIMOGO_AUTH_METHOD[0] for value, _label in choices):
        choices.append(_OPTIMOGO_AUTH_METHOD)


class Plugin:
    def load(self, dependencies):
        core = dependencies['flask']

        # Add the optimogo config sub-form to the stock DirdSourceForm. wtforms
        # FormMeta.__setattr__ clears the cached _unbound_fields when an unbound
        # field is assigned, so the field is bound on the next instantiation —
        # additively (the stock *_config fields are untouched).
        DirdSourceForm.optimogo_config = FormField(OptimoGoForm)

        # Add 'optimogo' to the user Authentication Method dropdown so saving an
        # SSO user in wazo-ui preserves authentication_method='optimogo'.
        _add_optimogo_auth_method()

        core.register_blueprint(optimogo_source)
        logger.debug('optimogo_source wazo-ui plugin loaded')
