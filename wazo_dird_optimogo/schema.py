from marshmallow import Schema, fields, validate, EXCLUDE


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
    first_matched_columns = fields.List(fields.String(), load_default=lambda: ['number'])
    searched_columns = fields.List(fields.String(), load_default=lambda: ['name', 'number'])
    format_columns = fields.Dict(load_default=dict)
    unique_column = fields.String(load_default='id')


_SCHEMA = _ConfigSchema()


def load_config(raw):
    """Validate a source-config dict, returning a dict with defaults applied.

    Raises marshmallow.ValidationError on bad input.
    """
    return _SCHEMA.load(raw)
