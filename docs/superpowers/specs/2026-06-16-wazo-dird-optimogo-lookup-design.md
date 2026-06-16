# wazo-dird OptimoGo Lookup Plugin — Design Spec

- **Date:** 2026-06-16
- **Status:** Approved (design); pending implementation plan
- **Author:** Jayden Smith (with Claude Code)
- **Repo:** `wazo-optimogo`
- **Scope:** A custom wazo-dird source backend (`optimogo`) that resolves caller IDs and directory searches against a tenant's OptimoGo instance over a JSON HTTP API, plus the precise contract for the OptimoGo-side endpoint it calls.

---

## 1. Overview & goals

Each OptimoGo tenant runs **their own** Wazo PBX (Debian host install; `wazo-dird` is a systemd service in the system Python env). This plugin makes that tenant's OptimoGo customer data resolvable inside Wazo's directory service so that:

1. **Reverse lookup (caller ID):** on an inbound call, the customer name appears on the physical handset/softphone **before it rings**. Caller ID is resolved synchronously in the Asterisk dialplan by the `callerid_forphones` AGI, which queries `wazo-dird`. The only way to put an OptimoGo name on the device is to make OptimoGo data a **dird source** resolved pre-ring — this plugin is that source.
2. **Forward search:** an agent typing a name or number in their softphone/Wazo directory sees matching OptimoGo customers (added to a lookup profile).

Resolution is **live** against OptimoGo over HTTP — there is no synced copy of the data on the PBX.

### Non-goals (this spec)
- Implementing the OptimoGo-side endpoint (specified in §4; built later in `optimogo-site`).
- The in-app screen pop, call recording, transcription, and AI summary pipelines — those are separate phases of the telephony integration and are unaffected by this plugin (see §2).
- Click-to-dial / outbound origination, favorites/personal contacts in this source.

---

## 2. Relationship to the approved telephony design

This plugin is a **revision** to `optimogo-site/docs/superpowers/specs/2026-06-06-wazo-telephony-integration-design.md`. That design put the customer name on the handset via **phonebook sync** (syncing OptimoGo customers into a Wazo phonebook through a local→Wazo `wazo_contact_id` mapping table, with a bulk-CSV backfill, on-change push, and a daily diff reconcile).

**This plugin replaces phonebook sync with live lookup.** Consequently:

- **Phase 3 of that design is removed**, along with `WazoPhonebookEntry`, the `wazo_contact_id` mapping, the CSV backfill, the on-change push, and the daily reconcile. There is no longer a synced phonebook to drift or reconcile.
- **Phases 1, 2, 4, 5 are unaffected.** Screen pop, recording ingestion, transcription, and summaries derive caller identity from webhook events plus the internal `match_customer_by_phone()` service — independent of how the *handset* name is resolved.
- The OptimoGo reverse-lookup endpoint this plugin calls **reuses the same `match_customer_by_phone()`** logic, so handset caller ID and in-app identification agree.

### Locked decisions
| Decision | Choice |
|---|---|
| Handset caller ID mechanism | **Live wazo-dird source plugin** (replaces phonebook sync) |
| Project scope (this repo) | **Plugin + written contract** for the OptimoGo endpoint (endpoint built separately in `optimogo-site`) |
| Wazo deployment target | **Debian host install**; packaged as a **wazo-plugind** plugin |
| Lookups provided | **Reverse + forward search** |
| Plugin → OptimoGo auth | **Per-tenant bearer API key** (separate from the webhook secret) |
| Resilience posture | **Fail-open + short TTL cache** (never delay/drop a call) |
| Ambiguous reverse match (handset) | **Show first/most-recent customer**, deterministic & configurable, while still reporting `match_state=ambiguous` + `candidate_count` |

---

## 3. Plugin architecture

Distribution: Python package **`wazo-dird-optimogo`**, module **`wazo_dird_optimogo`**, backend name **`optimogo`**, registered under the setuptools entry point group **`wazo_dird.backends`**.

### 3.1 Package layout
```
wazo_dird_optimogo/
  __init__.py
  plugin.py          # OptimoGoSourcePlugin(BaseSourcePlugin)
  http_client.py     # OptimoGoClient: bearer auth, timeout, JSON, typed errors
  cache.py           # TTLCache: per-source, positive + negative TTLs, bounded LRU
  schema.py          # marshmallow source-config schema + validation
  exceptions.py      # OptimoGoLookupError, OptimoGoAuthError, OptimoGoTimeout, OptimoGoUnavailable
setup.py             # entry_points: wazo_dird.backends =
                     #   optimogo = wazo_dird_optimogo.plugin:OptimoGoSourcePlugin
```

### 3.2 Backend class — `OptimoGoSourcePlugin(BaseSourcePlugin)`
Implements the wazo-dird source SPI (`BaseSourcePlugin`):

- **`load(dependencies)`** — `dependencies` provides `auth_client`, `config` (source-specific), `main_config`, `token_renewer`. Read the source `config`, build `OptimoGoClient` and `TTLCache`, and set the column constants (`SEARCHED_COLUMNS`, `FIRST_MATCHED_COLUMNS`, `UNIQUE_COLUMN`, `FORMAT_COLUMNS`).
- **`first_match(exten, args=None) -> dict | None`** — cache-checked reverse lookup; one result dict or `None`.
- **`match_all(extens, args=None) -> dict[str, dict]`** — **overrides** the default per-exten loop so a ring group of N numbers is one HTTP round-trip to the endpoint's reverse mode, not N. Returns a map of number → result dict (missing numbers omitted).
- **`search(term, args=None) -> list[dict]`** — forward search; list of result dicts.
- **`list(uids, args) -> list[dict]`** — returns `[]` (favorites not supported by this source; documented, not silently empty).
- **`unload()`** — close the HTTP session.

Result dicts are keyed by the source's columns; empty fields are `None` per the SPI ("Empty values should be `None`, instead of empty string").

### 3.3 Source config schema (per tenant)
| key | purpose | default |
|---|---|---|
| `lookup_url` | tenant-scoped OptimoGo base URL (`…/api/wazo/dird/<tenant_schema>`) | required |
| `api_key` | per-tenant bearer key | required |
| `timeout` | per-request seconds; fail-open on exceed | `1.0` |
| `cache_ttl` | positive-result TTL (s) | `60` |
| `negative_cache_ttl` | not-found TTL (s) | `30` |
| `verify_certificate` | TLS verify (bool or CA-bundle path) | `true` |
| `first_matched_columns` | columns matched on reverse | `["phone"]` |
| `searched_columns` | columns matched on forward search | `["name", "phone"]` |
| `format_columns` | display mapping, e.g. `{"display_name": "{name}"}` | sensible default |
| `unique_column` | stable id column | `"id"` |

Config is validated by a marshmallow schema at `load`; required fields enforced, bad values rejected.

---

## 4. OptimoGo endpoint contract (deliverable for `optimogo-site`)

The endpoint is **not** built in this repo, but is fully specified here so the `optimogo-site` work is a known task. It mirrors the existing webhook design's tenant-scoping and secret-hardening conventions.

### 4.1 Tenant scoping & auth
- `lookup_url` base = `https://<optimogo-host>/api/wazo/dird/<tenant_schema>`; the plugin appends the mode (`/reverse`, `/search`).
- Every request carries `Authorization: Bearer <api_key>` over HTTPS.
- The endpoint resolves `<tenant_schema>` (404 if unknown), switches into that schema, **constant-time compares** the key against a per-tenant **hashed, rotatable** dird key on `WazoConnection` (same hardening as the webhook secret), then reuses the existing `match_customer_by_phone()` service.

### 4.2 Reverse mode — `GET {base}/reverse?number=<raw_or_e164>`
```json
// 200 matched
{ "match": { "display_name": "Acme Plumbing", "name": "Acme Plumbing",
             "number": "+61399999999", "customer_id": 123,
             "contact_name": "John Smith", "match_state": "matched" } }

// 200 no match
{ "match": null }

// 200 ambiguous (number shared by >1 customer)
{ "match": { "display_name": "Acme Plumbing", "name": "Acme Plumbing",
             "number": "+61399999999", "customer_id": 123,
             "contact_name": null, "match_state": "ambiguous",
             "candidate_count": 3 } }
```
Ambiguous selection is **deterministic and configurable**: default = most-recent activity (`updated_at` desc), tie-broken by `customer_id`. `display_name` carries the single chosen customer so the handset shows a real name, while `match_state` + `candidate_count` preserve the ambiguity for the in-app screen pop (which shows the full candidate list and lets the agent correct it).

### 4.3 Search mode — `GET {base}/search?term=<text>&limit=25`
```json
// 200
{ "results": [
  { "display_name": "Acme Plumbing", "name": "Acme Plumbing", "number": "+61399999999",
    "customer_id": 123, "contact_name": null },
  { "display_name": "Acme Plumbing — John Smith", "name": "John Smith", "number": "+61400000000",
    "customer_id": 123, "contact_name": "John Smith" }
] }
```
A customer with several numbers yields one row per dialable number (dird results are number-centric for click-to-dial). The server caps `limit`.

### 4.4 Status-code contract (drives fail-open precisely)
| Status | Meaning | Plugin behavior |
|---|---|---|
| `200` | success, **including `match: null`** | use it; positive → positive cache, `null` → negative cache |
| `401` / `403` | bad/rotated key | log (redacted) + fail-open; **no cache** |
| `5xx` / timeout / conn error | OptimoGo down | fail-open; **no cache** |
| `400` | malformed request (shouldn't happen) | log + fail-open; no cache |

"Fail-open" always means return `None`/`[]` so the call proceeds with the raw number. The plugin **never raises into the dialplan**.

### 4.5 Field → dird columns
Endpoint fields map straight to source columns: `name`, `number`, `customer_id` (as `unique_column`), `contact_name`. The reverse profile's display uses `display_name`/`name` for the handset name. `format_columns` composes `display_name` if a tenant wants a custom format.

---

## 5. Data flow

### 5.1 Reverse lookup (pre-ring, blocks the call — must be fast)
1. Inbound call → Asterisk dialplan → `callerid_forphones` AGI → `wazo-dird` reverse lookup on the tenant's reverse profile.
2. dird calls the source's `first_match(number)` (or `match_all(numbers)` for ring groups).
3. Plugin: normalize → cache key. **Hit** → return cached. **Miss** → `GET /reverse?number=` with bearer, `timeout` (default 1s).
4. `200` + match → build dict, positive-cache (`cache_ttl`), return. `200` + `null` → negative-cache (`negative_cache_ttl`), return `None`. Non-200 / timeout / conn error → log (redacted), return `None`, **do not cache**.
5. dird aggregates across sources; `None` here → handset shows the raw number (fail-open). Match → phone rings with the OptimoGo name.

### 5.2 Forward search
1. Agent searches the directory in the softphone → `wazo-dird` lookup profile → source `search(term)`.
2. Plugin: cache key `(search, normalized_term)`. **Hit** → return cached. **Miss** → `GET /search?term=` with bearer, `timeout`.
3. `200` → positive-cache (`cache_ttl`) and return the list (an empty `results` list is cached under `negative_cache_ttl`). Any error → return `[]`, **do not cache** (other dird sources still contribute results).

---

## 6. Resilience & caching

- **`TTLCache`, per source.** Key `(mode, normalized_term)`. Positive results cached `cache_ttl` (60s); `match: null` cached `negative_cache_ttl` (30s); **errors/timeouts never cached** (a blip self-heals on the next call). Ambiguous results cached like positive ones.
- **Bounded** with LRU eviction (a busy line can't grow it unbounded). No background threads — purely lazy expiry on read.
- **Fail-open is absolute:** every error path returns `None`/`[]`; the call is never delayed or dropped by this plugin.

---

## 7. Error handling

Typed exceptions in `http_client.py` — `OptimoGoAuthError`, `OptimoGoTimeout`, `OptimoGoUnavailable`, `OptimoGoLookupError` — caught **explicitly** in the plugin (no blanket `except`, per RULES.md), each mapped to the §4.4 fail-open contract. The `api_key` is **never logged**; request logging redacts the `Authorization` header and records only mode + normalized term + status + latency.

---

## 8. Packaging, deployment & provisioning

### 8.1 wazo-plugind plugin
A git repo with `wazo/plugin.yml` (namespace/name **`optimo/wazo-dird-optimogo`**) whose Debian build rule pip-installs the wheel into the `wazo-dird` Python env, and whose install hook restarts `wazo-dird`. Installable via the Wazo plugin admin or `wazo-plugind-cli`, with clean upgrade/uninstall.

### 8.2 Per-tenant provisioning (documented + scriptable)
After install, for each tenant:
1. Create one `optimogo` **source** — `POST /api/dird/0.1/backends/optimogo/sources` with the §3.3 config and the `Wazo-Tenant` header.
2. Add that source to the tenant's **reverse** profile (caller ID) and a **lookup** profile (search), via the dird profiles API.
3. Confirm the reverse profile's **display** maps `display_name`/`name` to the handset name field.

This mirrors how the telephony design provisions dird/webhook resources on connect, and is a natural extension point for the telephony app's `connectWazo` later.

---

## 9. Testing strategy

Pytest, verbose and adversarial (per CLAUDE.md) — stubbed OptimoGo via `responses`/`respx`; tests reflect real usage and are designed to reveal flaws.

- **Reverse:** matched → dict; `match: null` → `None`; ambiguous → single chosen name + `match_state=ambiguous` + `candidate_count`; deterministic tie-break ordering.
- **`match_all`:** a ring group of N numbers → **one** HTTP call; correct per-number mapping; missing numbers omitted.
- **Search:** multiple results, per-number rows, `limit` honored, empty term.
- **Fail-open:** timeout, 5xx, 401/403, connection error → `None`/`[]`; call never blocked; errors not cached.
- **Cache:** positive hit within TTL (no 2nd HTTP call), expiry re-fetches, negative cache, error not cached, LRU eviction bound.
- **Auth/redaction:** bearer header sent; `api_key`/`Authorization` never appear in logs.
- **Config schema:** required fields, defaults, bad values rejected at `load`.
- **Field mapping:** JSON → columns; empty fields become `None` (SPI rule).
- **Packaging smoke test:** entry point resolves `optimogo` → the plugin class.

---

## 10. Open items to verify before/during planning

1. Exact dird **source-create + profile-bind** API shapes on the deployed Wazo version, and which profile `callerid_forphones` reads (typically `default`); confirm the reverse profile's **display** maps `display_name`/`name` to the handset name field.
2. Whether `wazo-dird` runs in the **system Python** vs a venv on this Debian build (affects the pip-install target in `plugin.yml`).
3. Form of the incoming `number` the dialplan passes to `first_match` (national vs E164) — confirm OptimoGo-side normalization covers both.
4. wazo-plugind `plugin.yml` build / Debian-rule specifics for installing a pip wheel + restarting `wazo-dird`.
5. The OptimoGo endpoint (separate `optimogo-site` work): add the tenant-scoped dird key (hashed, rotatable) to `WazoConnection`; add two read-only views reusing `match_customer_by_phone()` + a search query.

---

## 11. Out of scope / future

- Favorites/personal contacts from OptimoGo as a dird source.
- Click-to-dial / outbound origination.
- A shared multi-tenant lookup endpoint (each tenant has a dedicated Wazo + dedicated OptimoGo connection).
