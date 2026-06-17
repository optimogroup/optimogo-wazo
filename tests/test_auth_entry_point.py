from importlib.metadata import entry_points


def test_optimogo_idp_entry_point_registered():
    eps = {ep.name: ep.value for ep in entry_points(group='wazo_auth.idp')}
    assert eps.get('optimogo') == 'wazo_auth_optimogo.idp:OptimoGoIDP'
