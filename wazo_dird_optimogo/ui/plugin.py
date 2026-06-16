import logging

from wtforms.fields import FormField

from wazo_ui.helpers.plugin import create_blueprint
from wazo_ui.plugins.dird_source.form import DirdSourceForm

from .form import OptimoGoForm

logger = logging.getLogger(__name__)

# A route-less blueprint exists only so this package's templates/ folder joins
# Flask's Jinja search path. The stock dird_source view renders
# 'dird_source/form/form_optimogo.html', which resolves to the file we ship under
# templates/dird_source/form/ — no patching of wazo-ui's installed files.
optimogo_source = create_blueprint('optimogo_source', __name__)


class Plugin:
    def load(self, dependencies):
        core = dependencies['flask']

        # Add the optimogo config sub-form to the stock DirdSourceForm. wtforms
        # FormMeta.__setattr__ clears the cached _unbound_fields when an unbound
        # field is assigned, so the field is bound on the next instantiation —
        # additively (the stock *_config fields are untouched).
        DirdSourceForm.optimogo_config = FormField(OptimoGoForm)

        core.register_blueprint(optimogo_source)
        logger.debug('optimogo_source wazo-ui plugin loaded')
