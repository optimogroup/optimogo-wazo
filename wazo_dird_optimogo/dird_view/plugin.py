from wazo_dird.helpers import BaseBackendView

from . import http


class OptimoGoView(BaseBackendView):
    """Registers the optimogo source-CRUD HTTP routes on wazo-dird.

    BaseBackendView.load() adds:
      /backends/optimogo/sources            (list + create)
      /backends/optimogo/sources/<uuid>     (read + update + delete)
    Without this view plugin those routes 404, so no source can be created via
    the dird API or wazo-ui.
    """

    backend = 'optimogo'
    list_resource = http.OptimoGoList
    item_resource = http.OptimoGoItem
