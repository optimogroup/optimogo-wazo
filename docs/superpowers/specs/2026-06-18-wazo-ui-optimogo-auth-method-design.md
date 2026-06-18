# wazo-ui OptimoGo Authentication Method — Design

**Date:** 2026-06-18
**Status:** Approved (design); pending spec review → plan.

## Goal

Add `optimogo` as an option in the wazo-ui user **Authentication Method**
dropdown, so an admin can assign/keep `authentication_method='optimogo'` on a
user through the UI — instead of the current behaviour where saving the user
form silently reverts the method to `default` (because the dropdown has no
`optimogo` option, and the form posts whatever the dropdown holds).

## Background / root cause

The per-user SSO auth bridge requires each SSO user's wazo-auth
`authentication_method` to equal the optimogo IDP's method (`optimogo`); the
auth-method gate rejects the login otherwise (`Unauthorized authentication
method optimogo … should use native`). Setting it via DB/API works, but
**editing the user in wazo-ui rewrites the column** because wazo-ui's
`IdentityForm.authentication_method` SelectField has a hardcoded choice list
(`default/native/saml/ldap`) with no `optimogo`, so every save posts a value
from that limited list. Adding `optimogo` to the choices fixes both the save
(keeps `optimogo`) and the edit-form display (pre-selects the user's current
method).

## Load-bearing facts (verified on the test PBX, wazo-ui + wazo-auth installed)

- `wazo_ui/plugins/identity/form.py` → `class IdentityForm(BaseForm)` →
  `authentication_method = SelectField(l_('Authentication Method'),
  choices=[('default', …), ('native', …), ('saml', …), ('ldap', …)])`.
  The choices are hardcoded on the field.
- `wazo_ui/plugins/identity/templates/identity/edit.html` renders the field
  generically: `{{ render_field(form.authentication_method) }}`. A generic
  SelectField render iterates the field's choices ⇒ **adding a choice requires
  no template change.**
- This plugin already ships a `wazo_ui.plugins` entry point
  (`optimogo_source = wazo_dird_optimogo.ui.plugin:Plugin` in `setup.py`) whose
  `Plugin.load(dependencies)` already monkeypatches a wazo-ui form
  (`DirdSourceForm.optimogo_config = FormField(OptimoGoForm)`). Same hook,
  same lifecycle.
- Save path accepts `optimogo`: `wazo_auth/plugins/http/users/schemas.py` types
  `authentication_method = fields.String()` (no `OneOf`), and
  `wazo_auth/plugins/http/users/http.py` validates it on POST/PUT via
  `idp_service.is_valid_idp_type(authentication_method)`, which is True for any
  **registered** IDP. The optimogo IDP is registered (loaded by the wazo-auth
  controller), so `is_valid_idp_type('optimogo')` is True ⇒ the user-update API
  accepts `authentication_method='optimogo'`.

## Architecture

A single, additive monkeypatch in the existing wazo-ui plugin's `load()`. No new
files, no template override, no new entry point.

## Component

`wazo_dird_optimogo/ui/plugin.py` (modify):

- Add a module-level helper:
  ```python
  _OPTIMOGO_AUTH_METHOD = ('optimogo', 'OptimoGo')

  def _add_optimogo_auth_method():
      """Add 'optimogo' to wazo-ui's user Authentication Method dropdown,
      additively and idempotently. The field's choices list (on the unbound
      SelectField) is read at bind time, so mutating it in place affects every
      future IdentityForm instantiation."""
      from wazo_ui.plugins.identity.form import IdentityForm
      choices = IdentityForm.authentication_method.kwargs['choices']
      if not any(value == _OPTIMOGO_AUTH_METHOD[0] for value, _ in choices):
          choices.append(_OPTIMOGO_AUTH_METHOD)
  ```
- Call `_add_optimogo_auth_method()` from `Plugin.load()` (after the existing
  DirdSourceForm patch).

**Value vs. label:** value `'optimogo'` MUST equal the IDP's
`authentication_method` (the auth-method gate compares exact strings). Label
`'OptimoGo'` is display-only. The label is a plain string (not `l_()`); it is a
proper noun / brand, not translatable copy. (The existing plugin imports for
`l_` are not required.)

**Idempotency:** the guard (`any(value == 'optimogo' …)`) makes a second
`load()` — across gunicorn worker reloads or test double-load — a no-op, and
preserves wazo-ui's stock choices untouched.

**Cache note:** mutating the same `kwargs['choices']` list object that wtforms'
`_unbound_fields` cache already references means future binds see the new
choice without clearing the cache. If, on the box, the choice does not appear
(e.g. a wtforms version that snapshots choices differently), the fallback is to
reassign the field (`IdentityForm.authentication_method = SelectField(...,
choices=choices)`), which `FormMeta.__setattr__` uses to clear the cache — but
the in-place mutation is expected to suffice.

## Error handling

- Import of `wazo_ui.plugins.identity.form` happens inside `load()` (the plugin
  only runs inside wazo-ui, where the import resolves) — consistent with the
  existing `from wazo_ui.plugins.dird_source.form import DirdSourceForm`
  module-level import in this file.
- No new failure modes: the helper either appends once or no-ops.

## Testing

`tests/test_ui_plugin.py` (extend, `@pytest.mark.needs_ui` — runs where
`wazo_ui` is importable; skipped locally via `pytest.importorskip('wazo_ui')`):

- After `Plugin().load({'flask': app})`, `IdentityForm.authentication_method`'s
  choices contain `('optimogo', 'OptimoGo')` exactly once.
- The stock choices (`default`, `native`, `saml`, `ldap`) are still present
  (additive, not replaced).
- A second `Plugin().load(...)` (new Flask app) does not duplicate the
  `optimogo` choice (idempotent).

## Deployment

The patch applies when wazo-ui loads its plugins at startup. After updating the
installed package: reinstall the plugin (`pip3 install --break-system-packages
--no-deps --upgrade <src>`, matching the existing install path) and
`systemctl restart wazo-ui`.

## Out of scope (YAGNI)

- Changing the tenant `default_authentication_method` dropdown
  (`TenantForm.default_authentication_method`) — only the per-user field is in
  scope.
- Any server-side / wazo-auth change (the API already accepts `optimogo`).
- Localising the `OptimoGo` label.

## Global Constraints

- Additive + idempotent monkeypatch only; never replace wazo-ui's stock choice
  list. No template override, no new entry point/files.
- The choice value is exactly `'optimogo'` (matches the IDP's
  `authentication_method`); changing it would break the auth-method gate.
- Follow the existing `wazo_dird_optimogo/ui/plugin.py` monkeypatch-on-`load()`
  pattern and its `needs_ui` test convention.
