import pytest

pytest.importorskip('wazo_dird')           # only runs where wazo_dird is installed

from wazo_dird_optimogo.plugin import OptimoGoSourcePlugin


class _FakeEngine:
    def __init__(self):
        self.reverse_result = None
        self.search_result = []
        self.match_all_result = {}
    def reverse(self, number):
        return self.reverse_result
    def search(self, term):
        return self.search_result
    def match_all(self, numbers):
        return self.match_all_result
    def close(self):
        pass


def _loaded_plugin(engine):
    p = OptimoGoSourcePlugin()
    p.load({'config': {
        'name': 'optimogo',
        'lookup_url': 'https://opt.example.com/api/wazo/dird/acme',
        'api_key': 'secret-key',
    }})
    p._engine = engine        # swap in a fake after load wires the real one
    return p


@pytest.mark.needs_dird
def test_first_match_wraps_result_dict():
    eng = _FakeEngine()
    eng.reverse_result = {'id': 'customer:1:number:+61', 'name': 'Acme', 'number': '+61',
                          'customer_id': 1, 'contact_name': None, 'display_name': 'Acme'}
    p = _loaded_plugin(eng)
    result = p.first_match('+61')
    assert result is not None
    assert result.fields['display_name'] == 'Acme'


@pytest.mark.needs_dird
def test_first_match_none_returns_none():
    p = _loaded_plugin(_FakeEngine())     # reverse_result defaults to None
    assert p.first_match('+61') is None


@pytest.mark.needs_dird
def test_list_returns_empty():
    p = _loaded_plugin(_FakeEngine())
    assert p.list(['x'], None) == []


@pytest.mark.needs_dird
def test_safety_catch_swallows_unexpected_errors():
    class Boom(_FakeEngine):
        def reverse(self, number):
            raise RuntimeError('unexpected')
    p = _loaded_plugin(Boom())
    assert p.first_match('+61') is None    # must NOT propagate into the dialplan


@pytest.mark.needs_dird
def test_search_wraps_rows():
    eng = _FakeEngine()
    eng.search_result = [{'id': 'customer:1:number:+61', 'name': 'Acme', 'number': '+61',
                          'customer_id': 1, 'contact_name': None, 'display_name': 'Acme'}]
    p = _loaded_plugin(eng)
    rows = p.search('acme')
    assert len(rows) == 1
    assert rows[0].fields['name'] == 'Acme'
