# wazo-ui OptimoGo Auth-Method Dropdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `optimogo` to the wazo-ui user Authentication Method dropdown so saving an SSO user in wazo-ui keeps `authentication_method='optimogo'` instead of reverting it to `default`.

**Architecture:** One additive, idempotent monkeypatch in the plugin's existing `wazo_ui.plugins` entry-point `load()` — append `('optimogo', 'OptimoGo')` to `wazo_ui.plugins.identity.form.IdentityForm`'s hardcoded `authentication_method` choices, in place. No template override, no new files.

**Tech Stack:** Python, Flask, WTForms, wazo-ui plugin (stevedore entry point), pytest.

**Spec:** `docs/superpowers/specs/2026-06-18-wazo-ui-optimogo-auth-method-design.md`.

**Working directory for all commands/paths:** the repo root `wazo-optimogo/`.

## Global Constraints

- Additive + idempotent monkeypatch only; never replace wazo-ui's stock choice list. No template override, no new entry point/files.
- The choice value is exactly `'optimogo'` (must equal the IDP's `authentication_method`); the label is `'OptimoGo'` (display-only, plain string, not localised).
- Follow the existing `wazo_dird_optimogo/ui/plugin.py` monkeypatch-on-`load()` pattern and the `@pytest.mark.needs_ui` test convention in `tests/test_ui_plugin.py`.
- `tests/test_ui_plugin.py` begins with `pytest.importorskip('wazo_ui')`, so the whole module is **skipped wherever `wazo_ui` is not installed** (e.g. local dev). The new tests therefore only execute where `wazo_ui` is present (the PBX / a wazo-ui env). Local verification = the suite still collects and the module skips cleanly; real execution + acceptance happen on the box (see Deployment).

---

### Task 1: Add `optimogo` to the wazo-ui auth-method dropdown

**Files:**
- Modify: `wazo_dird_optimogo/ui/plugin.py`
- Test: `tests/test_ui_plugin.py` (extend)

**Interfaces:**
- Consumes: `wazo_ui.plugins.identity.form.IdentityForm` (its `authentication_method` is an unbound `SelectField` whose `kwargs['choices']` is a list of `(value, label)` tuples — stock `[('default',…),('native',…),('saml',…),('ldap',…)]`).
- Produces: after `Plugin().load(...)`, that choices list also contains `('optimogo', 'OptimoGo')` exactly once.

**Context:** The existing file already monkeypatches a wazo-ui form on `load()` (`DirdSourceForm.optimogo_config = FormField(OptimoGoForm)`) and imports wazo-ui form classes at module level. Add an analogous, additive patch for the identity form. The choices list lives on the *unbound* field and is read at bind time, so mutating it in place affects every later `IdentityForm` instantiation; an idempotency guard keeps a second `load()` (worker reload / test double-load) a no-op.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui_plugin.py` — first add this import alongside the existing `from wazo_ui.plugins.dird_source.form import DirdSourceForm  # noqa: E402` line (both are under the module's `pytest.importorskip('wazo_ui')`, so they only import where wazo-ui exists):

```python
from wazo_ui.plugins.identity.form import IdentityForm  # noqa: E402
```

Then append these two tests:

```python
@pytest.mark.needs_ui
def test_load_adds_optimogo_authentication_method():
    app = flask.Flask(__name__)
    app.config['WTF_CSRF_ENABLED'] = False
    app.secret_key = 'test'

    Plugin().load({'flask': app})

    choices = IdentityForm.authentication_method.kwargs['choices']
    values = [value for value, _label in choices]
    # added, exactly once, with the expected label
    assert ('optimogo', 'OptimoGo') in choices
    assert values.count('optimogo') == 1
    # stock choices preserved (additive, not replaced)
    for stock in ('default', 'native', 'saml', 'ldap'):
        assert stock in values


@pytest.mark.needs_ui
def test_load_optimogo_authentication_method_is_idempotent():
    # Loading twice (e.g. across worker reloads) must not duplicate the choice.
    Plugin().load({'flask': flask.Flask(__name__)})
    Plugin().load({'flask': flask.Flask(__name__)})

    values = [value for value, _label in IdentityForm.authentication_method.kwargs['choices']]
    assert values.count('optimogo') == 1
```

- [ ] **Step 2: Run the test file to verify state**

Run: `python3 -m pytest tests/test_ui_plugin.py -v`
Expected (local, no `wazo_ui` installed): the module is **skipped** at collection (`pytest.importorskip('wazo_ui')`) — i.e. the new tests are reported skipped, not failed, and there is **no import/collection error**. (If `wazo_ui` *is* installed in your env, the two new tests FAIL because the plugin doesn't add the choice yet.) Either outcome confirms the test is wired correctly before implementing.

- [ ] **Step 3: Implement the additive patch**

Edit `wazo_dird_optimogo/ui/plugin.py`. Add the `IdentityForm` import next to the existing wazo-ui form import, a module-level constant, and a helper; call the helper from `load()`. The full file after editing:

```python
import logging

from wtforms.fields import FormField

from wazo_ui.helpers.plugin import create_blueprint
from wazo_ui.plugins.dird_source.form import DirdSourceForm
from wazo_ui.plugins.identity.form import IdentityForm

from .form import OptimoGoForm

logger = logging.getLogger(__name__)

# (value, label) for the user Authentication Method dropdown. The value MUST
# equal the optimogo wazo_auth IDP's `authentication_method` — the auth-method
# gate compares the strings exactly. The label is display-only.
_OPTIMOGO_AUTH_METHOD = ('optimogo', 'OptimoGo')

# A route-less blueprint exists only so this package's templates/ folder joins
# Flask's Jinja search path. The stock dird_source view renders
# 'dird_source/form/form_optimogo.html', which resolves to the file we ship under
# templates/dird_source/form/ — no patching of wazo-ui's installed files.
optimogo_source = create_blueprint('optimogo_source', __name__)


def _add_optimogo_auth_method():
    """Add 'optimogo' to wazo-ui's user Authentication Method dropdown,
    additively and idempotently.

    IdentityForm.authentication_method is an unbound SelectField; its
    kwargs['choices'] list is read each time the form binds, so appending to it
    in place surfaces the new option on every future IdentityForm instantiation
    without touching wazo-ui's installed files. The guard keeps a second load()
    (gunicorn worker reload, test double-load) a no-op and leaves the stock
    choices intact.
    """
    choices = IdentityForm.authentication_method.kwargs['choices']
    if not any(value == _OPTIMOGO_AUTH_METHOD[0] for value, _label in choices):
        choices.append(_OPTIMOGO_AUTH_METHOD)


class Plugin:
    def load(self, dependencies):
        core = dependencies['flask']

        # Add the optimogo config sub-form to the stock DirdSourceForm. wtforms
        # FormMeta.__setattr__ clears the cached _unbound_fields when an unbound
        # field is assigned, so the field is bound on the next instantiation —
        # additively (the stock *_config fields are untouched).
        DirdSourceForm.optimogo_config = FormField(OptimoGoForm)

        # Add 'optimogo' to the user Authentication Method dropdown so saving an
        # SSO user in wazo-ui preserves authentication_method='optimogo'.
        _add_optimogo_auth_method()

        core.register_blueprint(optimogo_source)
        logger.debug('optimogo_source wazo-ui plugin loaded')
```

- [ ] **Step 4: Run the test file to verify it passes where wazo-ui is available**

Run (local): `python3 -m pytest tests/test_ui_plugin.py -v`
Expected (local, no `wazo_ui`): still SKIPPED cleanly, no errors.

Run the full suite to confirm no regression: `python3 -m pytest -q`
Expected: all currently-passing tests still pass; the `needs_ui` tests are skipped locally. (Actual GREEN for the two new tests is demonstrated on the box in Step 6.)

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/ui/plugin.py tests/test_ui_plugin.py
git commit -m "feat(ui): add optimogo to wazo-ui user Authentication Method dropdown"
```

- [ ] **Step 6: Execute the needs_ui tests where wazo-ui is installed (acceptance)**

The `needs_ui` tests only run where `wazo_ui` is importable. Run them in a wazo-ui environment (e.g. the test PBX with the repo checked out / copied, or a venv with `wazo-ui` installed):

Run: `python3 -m pytest tests/test_ui_plugin.py -m needs_ui -v`
Expected: `test_load_adds_optimogo_authentication_method` and `test_load_optimogo_authentication_method_is_idempotent` PASS, along with the pre-existing `needs_ui` tests.

If a wazo-ui env is not readily available for pytest, the equivalent acceptance is the live check in Deployment below (the dropdown renders `OptimoGo` and saving a user keeps the method).

---

## Deployment & live acceptance (test PBX — non-production)

The patch applies when wazo-ui loads its plugins at startup, so the box needs the updated package + a restart:

- [ ] Update the installed plugin source on the PBX and reinstall it, matching the existing install path:
  `pip3 install --break-system-packages --no-deps --upgrade <src>` (the staged source under `/usr/src/wazo-dird-optimogo`, refreshed from this repo).
- [ ] `systemctl restart wazo-ui`.
- [ ] In wazo-ui, edit a user → the **Authentication Method** dropdown now lists **OptimoGo**. Select it (or, for jayden/pat, confirm their current `optimogo` shows as selected) and **Save**.
- [ ] Confirm the method persists (no revert to `default`): `SELECT username, authentication_method FROM auth_user WHERE username IN ('jayden@optimo.group','pat@optimo.group');` → `optimogo`.

## Out of scope (YAGNI)

- The tenant `default_authentication_method` dropdown — only the per-user field.
- Any wazo-auth/server change (the user-update API already accepts `optimogo`).
- Localising the `OptimoGo` label.
