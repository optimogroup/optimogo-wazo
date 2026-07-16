from xivo.mallow import fields
from xivo.mallow.validate import Length, Range, validate_string_dict
from xivo.mallow_helpers import ListSchema as _ListSchema

from wazo_dird.schemas import BaseSourceSchema, VerifyCertificateField

from ..schema import (
    DEFAULT_FIRST_MATCHED_COLUMNS,
    DEFAULT_FORMAT_COLUMNS,
    DEFAULT_SEARCHED_COLUMNS,
)


class SourceSchema(BaseSourceSchema):
    """Validates an optimogo source config posted to the dird HTTP API.

    BaseSourceSchema supplies the standard fields (name, uuid, tenant_uuid,
    first_matched_columns, searched_columns, format_columns), but defaults those
    three column fields to EMPTY. We override them with the same defaults as the
    backend's own config schema so a minimal create (name + lookup_url + api_key)
    yields a complete source — in particular a `reverse` format column, without
    which caller-ID reverse lookups resolve the match but display no name.
    """

    lookup_url = fields.URL(required=True)
    api_key = fields.String(required=True, validate=Length(min=1))
    connect_timeout = fields.Float(validate=Range(min=0.05), load_default=0.4)
    read_timeout = fields.Float(validate=Range(min=0.05), load_default=0.8)
    cache_ttl = fields.Integer(validate=Range(min=0), load_default=60)
    negative_cache_ttl = fields.Integer(validate=Range(min=0), load_default=30)
    cache_max_entries = fields.Integer(validate=Range(min=1), load_default=5000)
    breaker_failure_threshold = fields.Integer(validate=Range(min=1), load_default=5)
    breaker_cooldown = fields.Float(validate=Range(min=1), load_default=30.0)
    ambiguous_prefix = fields.String(load_default='Maybe: ')
    search_min_term_length = fields.Integer(validate=Range(min=1), load_default=3)
    search_max_term_length = fields.Integer(validate=Range(min=1), load_default=64)
    search_limit = fields.Integer(validate=Range(min=1, max=200), load_default=25)
    verify_certificate = VerifyCertificateField(load_default=True)
    # Override BaseSourceSchema's empty defaults for these three (see docstring).
    first_matched_columns = fields.List(
        fields.String(validate=Length(min=1, max=128)),
        load_default=lambda: list(DEFAULT_FIRST_MATCHED_COLUMNS),
    )
    searched_columns = fields.List(
        fields.String(validate=Length(min=1, max=128)),
        load_default=lambda: list(DEFAULT_SEARCHED_COLUMNS),
    )
    format_columns = fields.Dict(
        validate=validate_string_dict,
        load_default=lambda: dict(DEFAULT_FORMAT_COLUMNS),
    )


class ListSchema(_ListSchema):
    searchable_columns = ['uuid', 'name', 'lookup_url']
    sort_columns = ['name', 'lookup_url']
    default_sort_column = 'name'

    recurse = fields.Boolean(load_default=False)


source_list_schema = SourceSchema(many=True)
source_schema = SourceSchema()
list_schema = ListSchema()
