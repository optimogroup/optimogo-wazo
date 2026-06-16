# Installing the OptimoGo dird backend

Target verified on `pbx.local.optimo.group`: Debian 12 (bookworm),
**wazo-dird 26.05**, **wazo-plugind 26.04**, system Python 3.11.

## 1. Install the plugin (per PBX)

### Option A — via wazo-plugind (recommended, packaged)
The repo ships a `wazo/plugin.yml` (`namespace: optimo`, `name: wazo-dird-optimogo`,
`plugin_format_version: 2`) and an executable `wazo/rules`. wazo-plugind builds a
`.deb` (`wazo-plugind-wazo-dird-optimogo-optimo`) and runs `wazo/rules install`,
which `pip3 install`s the package into the system Python and restarts `wazo-dird`.

Install from a git URL via the plugind API (token from `wazo-auth`):

    curl -sk -X POST https://pbx.local.optimo.group/api/plugind/0.2/plugins \
      -H "X-Auth-Token: $TOKEN" -H 'Content-Type: application/json' \
      -d '{"method": "git", "options": {"url": "<repo-url>", "ref": "main"}}'

Poll progress on the returned `uuid` (`GET /api/plugind/0.2/plugins/<uuid>`), or
watch `journalctl -u wazo-plugind`.

`wazo/rules install` also drops `etc/wazo-dird/conf.d/50-wazo-dird-optimogo.yml`
into `/etc/wazo-dird/conf.d/`, which **enables** the backend
(`enabled_plugins.backends.optimogo: true`). This is required: wazo-dird's
`GET /0.1/backends` returns only `enabled ∩ installed` backends, so without the
drop-in the backend is installed but invisible to the API and the wazo-ui menu.
xivo's config ChainMap deep-merges the drop-in, so the stock backends stay enabled.

### Option B — manual install (testing, no plugind)
On the PBX, from a checkout of this repo:

    sudo pip3 install --break-system-packages --no-deps .
    sudo install -m 644 etc/wazo-dird/conf.d/50-wazo-dird-optimogo.yml /etc/wazo-dird/conf.d/
    sudo systemctl restart wazo-dird

### Post-install health check (and rollback)
    systemctl is-active wazo-dird           # must print 'active'
    python3 -c "from importlib.metadata import entry_points as e; \
      print('optimogo' in {x.name for x in e(group='wazo_dird.backends')})"   # must print True
Roll back on failure:
    # plugind:  curl -sk -X DELETE .../api/plugind/0.2/plugins/optimo/wazo-dird-optimogo -H "X-Auth-Token: $TOKEN"
    # manual:   sudo pip3 uninstall -y wazo-dird-optimogo && sudo systemctl restart wazo-dird

> Reminder: restarting `wazo-dird` briefly interrupts caller-ID lookups — install
> in a low-traffic window.

## 2. Create the source (per tenant)
POST to wazo-dird with the tenant's config and `Wazo-Tenant` header:

    POST /api/dird/0.1/backends/optimogo/sources
    Wazo-Tenant: <tenant-uuid>
    {
      "name": "optimogo",
      "lookup_url": "https://<optimogo-host>/api/wazo/dird/<tenant_schema>",
      "api_key": "<per-tenant-bearer-key>"
    }

Optional keys (defaults in spec §3.3): `connect_timeout` (0.4), `read_timeout`
(0.8), `cache_ttl` (60), `negative_cache_ttl` (30), `cache_max_entries` (5000),
`breaker_failure_threshold` (5), `breaker_cooldown` (30), `ambiguous_prefix`
("Maybe: "), `search_min_term_length` (3), `search_max_term_length` (64),
`search_limit` (25), `verify_certificate` (true).

## 3. Bind the source to profiles
- Add `optimogo` to the tenant's **reverse** profile (handset caller ID) and a
  **lookup** profile (directory search) via the dird profiles API
  (`/api/dird/0.1/profiles`).
- Confirm the reverse profile's **display** maps `display_name` to the handset
  name field. The handset caller-ID path is resolved pre-ring by the
  `callerid_forphones` AGI querying wazo-dird's reverse service.

## Web admin UI (wazo-ui): menu vs. form
Once the backend is enabled (above), `optimogo` **appears** in wazo-ui's
"Add Directory Source" menu, because that menu is `GET /0.1/backends`.

However, wazo-ui **cannot yet render a config form** for it: the per-backend forms
and templates (`form_<backend>.html`, the `<backend>_config` form field) are
hardcoded in wazo-ui for the 9 stock backends only — there is no `form_optimogo.html`.
Clicking "Add → OptimoGo" in the UI will therefore error (TemplateNotFound).

Two ways forward:
- **Provision via the dird REST API** (works today — §2), or
- **Add a wazo-ui plugin** that ships an `OptimoGoForm` + `form_optimogo.html`
  template so the source is fully manageable from the web UI (separate, optional
  deliverable).

## 4. Teardown order (uninstall / disconnect)
1. **Unbind** `optimogo` from all profiles (reverse + lookup) first.
2. **Delete** the source (`DELETE /api/dird/0.1/backends/optimogo/sources/<uuid>`) —
   removes the stored `api_key`.
3. **Uninstall** the plugin (plugind DELETE, or `pip3 uninstall`). `wazo/rules
   uninstall` removes the package and restarts dird.

## 5. Key rotation (no outage)
Rotate on OptimoGo first (the endpoint accepts current + previous key), then
update the source `api_key` via the sources API. The plugin logs repeated
401/403 at ERROR; the alert itself is raised OptimoGo-side.

## Notes for a staging validation pass
- Confirm `debian_depends: [wazo-dird]` survives into the generated package
  control (the metadata schema EXCLUDEs it from the validated dict; it is
  belt-and-suspenders since wazo-dird must already be present).
- Confirm `wazo/rules install` runs cleanly under the generated postinst on a
  staging PBX before using on production.
