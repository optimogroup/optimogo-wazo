from wazo_dird.auth import required_acl
from wazo_dird.helpers import SourceItem, SourceList

from .schemas import list_schema, source_list_schema, source_schema


class OptimoGoList(SourceList):
    list_schema = list_schema
    source_schema = source_schema
    source_list_schema = source_list_schema

    @required_acl('dird.backends.optimogo.sources.read')
    def get(self):
        return super().get()

    @required_acl('dird.backends.optimogo.sources.create')
    def post(self):
        return super().post()


class OptimoGoItem(SourceItem):
    source_schema = source_schema

    @required_acl('dird.backends.optimogo.sources.{source_uuid}.delete')
    def delete(self, source_uuid):
        return super().delete(source_uuid)

    @required_acl('dird.backends.optimogo.sources.{source_uuid}.read')
    def get(self, source_uuid):
        return super().get(source_uuid)

    @required_acl('dird.backends.optimogo.sources.{source_uuid}.update')
    def put(self, source_uuid):
        return super().put(source_uuid)
