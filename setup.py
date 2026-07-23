from setuptools import setup, find_packages

setup(
    name='wazo-dird-optimogo',
    version='1.3.0',
    description='wazo-dird source backend that resolves caller IDs against OptimoGo',
    author='Optimo Group',
    packages=find_packages(exclude=['tests', 'tests.*']),
    install_requires=['requests>=2.25', 'marshmallow>=3.13,<4'],
    include_package_data=True,
    package_data={
        'wazo_dird_optimogo.ui': ['templates/dird_source/form/*.html'],
    },
    entry_points={
        # wazo-calld plugin: swap ami.record_start for a dual-channel (stereo)
        # recorder. See wazo_calld_optimogo/plugin.py.
        'wazo_calld.plugins': [
            'optimogo_stereo_record = wazo_calld_optimogo.plugin:Plugin',
        ],
        # wazo-dird source backend: the lookup logic (server side).
        'wazo_dird.backends': [
            'optimogo = wazo_dird_optimogo.plugin:OptimoGoSourcePlugin',
        ],
        # wazo-dird view: the /backends/optimogo/sources CRUD HTTP routes.
        'wazo_dird.views': [
            'optimogo_backend = wazo_dird_optimogo.dird_view.plugin:OptimoGoView',
        ],
        # wazo-ui admin form for configuring an optimogo source (web UI side).
        'wazo_ui.plugins': [
            'optimogo_source = wazo_dird_optimogo.ui.plugin:Plugin',
        ],
        # wazo-auth IDP plugin: per-user SSO via OptimoGo introspection.
        'wazo_auth.idp': [
            'optimogo = wazo_auth_optimogo.idp:OptimoGoIDP',
        ],
        # wazo-phoned plugin: serve Wazo call history to Yealink phones' Network
        # CallLog over BroadWorks XSI (see wazo_phoned_optimogo/plugin.py).
        'wazo_phoned.plugins': [
            'optimogo_xsi_calllog = wazo_phoned_optimogo.plugin:Plugin',
        ],
    },
)
