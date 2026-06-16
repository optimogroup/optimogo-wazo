import pytest

pytest.importorskip('wazo_dird')


@pytest.mark.needs_dird
def test_entry_point_resolves_to_plugin_class():
    from importlib.metadata import entry_points
    eps = entry_points(group='wazo_dird.backends')
    optimogo = {ep.name: ep for ep in eps}.get('optimogo')
    assert optimogo is not None, 'optimogo backend entry point not registered'
    cls = optimogo.load()
    from wazo_dird_optimogo.plugin import OptimoGoSourcePlugin
    assert cls is OptimoGoSourcePlugin
