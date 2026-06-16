from setuptools import setup, find_packages

setup(
    name='wazo-dird-optimogo',
    version='1.0.0',
    description='wazo-dird source backend that resolves caller IDs against OptimoGo',
    author='Optimo Group',
    packages=find_packages(exclude=['tests', 'tests.*']),
    install_requires=['requests>=2.25', 'marshmallow>=3.13,<4'],
    entry_points={
        'wazo_dird.backends': [
            'optimogo = wazo_dird_optimogo.plugin:OptimoGoSourcePlugin',
        ],
    },
)
