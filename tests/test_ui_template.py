import os

import jinja2

# Plain Jinja syntax check for the form template. This needs neither wazo_ui nor
# the wazo-ui macros (parse() validates syntax, not name resolution), so it runs
# on any host and catches malformed-template regressions early.
_TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'wazo_dird_optimogo', 'ui', 'templates', 'dird_source', 'form', 'form_optimogo.html',
)


def test_form_template_is_valid_jinja():
    with open(_TEMPLATE) as f:
        source = f.read()
    jinja2.Environment().parse(source)  # raises TemplateSyntaxError on bad syntax


def test_form_template_targets_optimogo_backend():
    with open(_TEMPLATE) as f:
        source = f.read()
    assert "{% set backend = 'optimogo' %}" in source
    assert 'form.optimogo_config.lookup_url' in source
    assert 'form.optimogo_config.api_key' in source
