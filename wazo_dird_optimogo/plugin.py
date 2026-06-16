import logging

from wazo_dird import BaseSourcePlugin, make_result_class

from .engine import LookupEngine
from .http_client import OptimoGoClient
from .schema import load_config

logger = logging.getLogger(__name__)


class OptimoGoSourcePlugin(BaseSourcePlugin):
    """wazo-dird source backend resolving caller IDs/searches against OptimoGo.

    Each dird-facing method wraps an explicit outermost safety-catch: an
    unforeseen error (mapping, cache, result-class) must never propagate into
    the dialplan. Typed HTTP errors are already handled in the engine.
    """

    def load(self, args):
        cfg = load_config(args['config'])
        self.name = cfg['name']
        self.backend = args['config'].get('backend', 'optimogo')
        verify = cfg['verify_certificate']
        if verify is False:
            logger.warning('optimogo source %s has verify_certificate=False '
                           '(emergency diagnostics only)', self.name)
        if not str(cfg['lookup_url']).startswith('https://'):
            logger.warning('optimogo source %s lookup_url is not https', self.name)
        client = OptimoGoClient(
            base_url=cfg['lookup_url'], api_key=cfg['api_key'],
            connect_timeout=cfg['connect_timeout'], read_timeout=cfg['read_timeout'],
            verify=verify)
        self._engine = LookupEngine(client=client, config=cfg)
        self._result_class = make_result_class(
            self.backend, self.name, cfg['unique_column'], cfg['format_columns'])

    def first_match(self, exten, args=None):
        try:
            fields = self._engine.reverse(exten)
            return self._result_class(fields) if fields else None
        except Exception:
            logger.exception('optimogo first_match failed (returning None)')
            return None

    def match_all(self, extens, args=None):
        try:
            return {number: self._result_class(fields)
                    for number, fields in self._engine.match_all(extens).items()}
        except Exception:
            logger.exception('optimogo match_all failed (returning {})')
            return {}

    def search(self, term, args=None):
        try:
            return [self._result_class(fields) for fields in self._engine.search(term)]
        except Exception:
            logger.exception('optimogo search failed (returning [])')
            return []

    def list(self, uids, args=None):
        return []          # favorites unsupported by this source

    def unload(self):
        engine = getattr(self, '_engine', None)
        if engine:
            engine.close()
