# wazo-ui OptimoGo Source Form — Design Spec

- **Date:** 2026-06-16
- **Status:** Approved (design); building
- **Author:** Jayden Smith (with Claude Code)
- **Repo:** `wazo-optimogo`
- **Scope:** Make the `optimogo` dird source fully configurable from the wazo-ui
  "Add Directory Source" web form, by shipping a wazo-ui plugin bundled into the
  existing `wazo-dird-optimogo` package.

---

## 1. Problem

The dird backend (`optimogo`) is installed and enabled, so it now appears in the
wazo-ui "Add Directory Source" menu (`GET /0.1/backends`). But clicking it errors:
wazo-ui's `dird_source` plugin renders a **per-backend form** (`form_<backend>.html`)
and binds a per-backend `<backend>_config` field on the hardcoded `DirdSourceForm`.
There is no `form_optimogo.html` and no `optimogo_config` field, so `new/optimogo`
raises `TemplateNotFound`.

Submission/CRUD already works generically: for backends not in wazo-ui's hardcoded
`endpoints` map, `DirdSourceService` calls the generic dird API
(`backends.create_source(backend, config)` / `get_source` / `edit_source` /
`delete_source`). **Only the form (field + template) is missing.**

## 2. Approach (verified feasible on wazo-ui 26.05)

A new wazo-ui plugin (`optimogo_source`), bundled in the same package, that at load:

1. **Injects the config field** onto the stock form:
   `DirdSourceForm.optimogo_config = FormField(OptimoGoForm)`. Verified: wtforms
   3.0's `FormMeta.__setattr__` clears `_unbound_fields` when an unbound field is
   assigned, so the field is picked up on next instantiation — additively (stock
   `*_config` fields remain; `to_dict()` includes `optimogo_config`).
2. **Provides the template** `dird_source/form/form_optimogo.html` via its own
   blueprint's `templates/` folder. Flask's dispatching Jinja loader searches every
   blueprint's template folder, so the stock view's
   `render_template('dird_source/form/form_optimogo.html')` resolves to ours — no
   patching of wazo-ui files.

No changes to wazo-dird or the dird backend. No changes to wazo-ui's installed files.

## 3. Components (new, under `wazo_dird_optimogo/ui/`)

- **`form.py`** — `OptimoGoForm(BaseForm)` (`from wazo_ui.helpers.form import BaseForm`):
  - **Main:** `lookup_url` (StringField, required), `api_key` (StringField, required).
  - **Advanced (all optional; blank → backend default):** `connect_timeout`,
    `read_timeout`, `cache_ttl`, `negative_cache_ttl`, `cache_max_entries`,
    `breaker_failure_threshold`, `breaker_cooldown`, `ambiguous_prefix`,
    `search_min_term_length`, `search_max_term_length`, `search_limit`,
    `verify_certificate` (BooleanField).
  - Blank optional fields are dropped (so the dird source schema's defaults apply).
- **`plugin.py`** — `class Plugin: def load(self, dependencies):` injects the field
  onto `DirdSourceForm` and registers a (route-less) blueprint via
  `create_blueprint('optimogo_source', __name__)` + `core.register_blueprint(...)`.
- **`templates/dird_source/form/form_optimogo.html`** — mirrors `form_csv_ws.html`:
  `{% extends "layout.html" %}`, `{% set backend = 'optimogo' %}`, add/edit URL
  wiring, a **main tab** (lookup_url, api_key) and an **Advanced tab**, rendering
  `form.optimogo_config.<field>`.

## 4. Packaging & enablement

- **`setup.py`** — add a second entry point and ship templates as package data:
  `wazo_ui.plugins = optimogo_source = wazo_dird_optimogo.ui.plugin:Plugin`;
  `include_package_data=True` + `package_data` for `ui/templates/**`.
- **`etc/wazo-ui/conf.d/50-wazo-dird-optimogo.yml`** — `enabled_plugins:
  {optimogo_source: true}` (flat dict; xivo ChainMap deep-merges, keeping stock
  plugins). wazo-ui loads only enabled plugins.
- **`wazo/rules`** — `install` also installs the wazo-ui conf.d and restarts
  `wazo-ui`; `uninstall`/`postrm` remove it and restart `wazo-ui`. (The single
  package serves both wazo-dird and wazo-ui — they share the system Python.)

## 5. Testing

- **Container:** extend `Dockerfile.dev` to also `apt-get install wazo-ui`
  (postinst failure tolerated like wazo-dird). New `needs_ui` marker.
  - `form.py`: fields present, required validation, `to_dict()` drops blank
    optionals, keeps lookup_url/api_key.
  - `plugin.py`: `Plugin.load(fake_deps)` injects `optimogo_config` into
    `DirdSourceForm` (additive — stock fields intact) and registers the blueprint.
  - Template: Jinja syntax compiles.
- **PBX (real wazo-ui):** install via `wazo/rules install`; assert `wazo-ui` active
  (no crash), the `optimogo_source` plugin loads, and `DirdSourceForm` carries
  `optimogo_config` in the running interpreter.
- **Manual:** user clicks "Add → OptimoGo" in the browser and confirms the form
  renders + a source can be created (the only step needing an authenticated session).

## 6. Out of scope
- Editing the dird-returned column mappings from the UI (server returns fixed
  columns; the form configures operational params only).
- Any change to the OptimoGo endpoint or the dird backend.
