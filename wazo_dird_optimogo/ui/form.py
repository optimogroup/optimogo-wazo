from flask_babel import lazy_gettext as l_
from wtforms.fields import (
    BooleanField,
    FloatField,
    IntegerField,
    StringField,
)
from wtforms.validators import InputRequired
from wtforms.widgets import PasswordInput

from wazo_ui.helpers.form import BaseForm


class OptimoGoForm(BaseForm):
    """Config sub-form for an optimogo dird source.

    Injected onto wazo-ui's DirdSourceForm as `optimogo_config` so the source is
    configurable from the "Add Directory Source" web form. The advanced fields
    carry the same defaults as the backend's source-config schema, so they render
    pre-filled and always submit valid values (a blank optional would otherwise
    serialize to None and fail the backend schema).
    """

    lookup_url = StringField(l_('Lookup URL'), validators=[InputRequired()])
    api_key = StringField(
        l_('API key'),
        validators=[InputRequired()],
        widget=PasswordInput(hide_value=False),
    )

    connect_timeout = FloatField(l_('Connect timeout (s)'), default=0.4)
    read_timeout = FloatField(l_('Read timeout (s)'), default=0.8)
    cache_ttl = IntegerField(l_('Cache TTL (s)'), default=60)
    negative_cache_ttl = IntegerField(l_('Negative cache TTL (s)'), default=30)
    cache_max_entries = IntegerField(l_('Cache max entries'), default=5000)
    breaker_failure_threshold = IntegerField(
        l_('Breaker failure threshold'), default=5
    )
    breaker_cooldown = FloatField(l_('Breaker cooldown (s)'), default=30.0)
    ambiguous_prefix = StringField(l_('Ambiguous handset prefix'), default='Maybe: ')
    search_min_term_length = IntegerField(l_('Search min term length'), default=3)
    search_max_term_length = IntegerField(l_('Search max term length'), default=64)
    search_limit = IntegerField(l_('Search result limit'), default=25)
    verify_certificate = BooleanField(l_('Verify TLS certificate'), default=True)
