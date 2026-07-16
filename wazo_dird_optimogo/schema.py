from marshmallow import Schema, fields, validate, EXCLUDE

# Column defaults shared with the HTTP view schema (dird_view/schemas.py) so a
# minimal source (name + lookup_url + api_key) is complete on both paths.
DEFAULT_FIRST_MATCHED_COLUMNS = ['number']
DEFAULT_SEARCHED_COLUMNS = ['name', 'number']
# wazo-dird derives the reverse (caller-ID) display and the forward name from the
# source's `reverse` / `name` format columns. Without a `reverse` column the
# caller-ID lookup resolves the match but returns an empty display (no name on the
# phone). `{display_name}` carries the ambiguous "Maybe: " prefix from mapping.py.
DEFAULT_FORMAT_COLUMNS = {'name': '{display_name}', 'reverse': '{display_name}'}


class _ConfigSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    name = fields.String(required=True, validate=validate.Length(min=1))
    lookup_url = fields.Url(required=True)
    api_key = fields.String(required=True, validate=validate.Length(min=1))
    connect_timeout = fields.Float(load_default=0.4, validate=validate.Range(min=0.05))
    read_timeout = fields.Float(load_default=0.8, validate=validate.Range(min=0.05))
    cache_ttl = fields.Integer(load_default=60, validate=validate.Range(min=0))
    negative_cache_ttl = fields.Integer(load_default=30, validate=validate.Range(min=0))
    cache_max_entries = fields.Integer(load_default=5000, validate=validate.Range(min=1))
    breaker_failure_threshold = fields.Integer(load_default=5, validate=validate.Range(min=1))
    breaker_cooldown = fields.Float(load_default=30.0, validate=validate.Range(min=1))
    ambiguous_prefix = fields.String(load_default='Maybe: ')
    search_min_term_length = fields.Integer(load_default=3, validate=validate.Range(min=1))
    search_max_term_length = fields.Integer(load_default=64, validate=validate.Range(min=1))
    search_limit = fields.Integer(load_default=25, validate=validate.Range(min=1, max=200))
    verify_certificate = fields.Raw(load_default=True)
    first_matched_columns = fields.List(
        fields.String(), load_default=lambda: list(DEFAULT_FIRST_MATCHED_COLUMNS)
    )
    searched_columns = fields.List(
        fields.String(), load_default=lambda: list(DEFAULT_SEARCHED_COLUMNS)
    )
    format_columns = fields.Dict(load_default=lambda: dict(DEFAULT_FORMAT_COLUMNS))
    unique_column = fields.String(load_default='id')


_SCHEMA = _ConfigSchema()


def load_config(raw):
    """Validate a source-config dict, returning a dict with defaults applied.

    Raises marshmallow.ValidationError on bad input.
    """
    return _SCHEMA.load(raw)
