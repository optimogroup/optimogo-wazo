# wazo-dird OptimoGo Lookup Plugin — Design Spec

- **Date:** 2026-06-16
- **Status:** Approved (design); pending implementation plan
- **Author:** Jayden Smith (with Claude Code)
- **Repo:** `wazo-optimogo`
- **Revisions:** v2 — revised after a Codex (gpt-5.5) adversarial design review: batch reverse contract, canonical row identity, bounded (not "absolute") fail-open + latency budget, outermost SPI safety-catch, POST-JSON to keep PII out of logs, circuit breaker, cache/HTTP thread-safety, overlapping-key rotation, generalized status handling, input normalization, `"Maybe: {name}"` ambiguous handset label, live-PBX upgrade/uninstall safety, Wazo-version pinning.
- **Scope:** A custom wazo-dird source backend (`optimogo`) that resolves caller IDs and directory searches against a tenant's OptimoGo instance over a JSON HTTP API, plus the precise contract for the OptimoGo-side endpoint it calls.

---

## 1. Overview & goals

Each OptimoGo tenant runs **their own** Wazo PBX (Debian host install; `wazo-dird` is a systemd service in the system Python env). This plugin makes that tenant's OptimoGo customer data resolvable inside Wazo's directory service so that:

1. **Reverse lookup (caller ID):** on an inbound call, the customer name appears on the physical handset/softphone **before it rings**. In Wazo, caller ID for phones is resolved synchronously in the Asterisk dialplan by the `callerid_forphones` AGI, which queries `wazo-dird`'s reverse service. To put an OptimoGo name on the device, OptimoGo data must be a **dird source** bound to the reverse profile; this plugin is that source. (The rejected alternatives for the same goal are phonebook sync — see §2 — and direct dialplan customization.)
2. **Forward search:** an agent typing a name or number in their softphone/Wazo directory sees matching OptimoGo customers (source bound to a lookup profile).

Resolution is **live** against OptimoGo over HTTP — there is no synced copy of the data on the PBX.

The exact dird SPI, profile/display behavior, and `callerid_forphones` query path are **version-sensitive**; they are stated here as the known shape and must be pinned to the tenant's deployed Wazo release before implementation (§10).

### Non-goals (this spec)
- Implementing the OptimoGo-side endpoint (specified in §4; built later in `optimogo-site`).
- The in-app screen pop, call recording, transcription, and AI summary pipelines — separate phases of the telephony integration, unaffected by this plugin (see §2).
- Click-to-dial / outbound origination, favorites/personal contacts in this source.

---

## 2. Relationship to the approved telephony design

This plugin is a **revision** to `optimogo-site/docs/superpowers/specs/2026-06-06-wazo-telephony-integration-design.md`, which put the customer name on the handset via **phonebook sync** (syncing OptimoGo customers into a Wazo phonebook through a local→Wazo `wazo_contact_id` mapping table, with a bulk-CSV backfill, on-change push, and a daily diff reconcile).

**This plugin replaces phonebook sync with live lookup.** Consequently:

- **Phase 3 of that design is removed**, along with `WazoPhonebookEntry`, the `wazo_contact_id` mapping, the CSV backfill, the on-change push, and the daily reconcile. There is no synced phonebook to drift or reconcile.
- **Phases 1, 2, 4, 5 are unaffected.** Screen pop, recording ingestion, transcription, and summaries derive caller identity from **webhook events plus the internal `match_customer_by_phone()` service** — independent of this plugin and of how the *handset* name is resolved.
- The OptimoGo reverse-lookup endpoint this plugin calls **reuses the same `match_customer_by_phone()`** logic, so handset caller ID and in-app identification agree.

Because the screen pop matches independently (webhook path), the ambiguity metadata in this plugin's reverse response (§4.2) is **diagnostic/observability only for the handset path** — it is not what drives in-app disambiguation. The in-app pop still shows the full candidate list, via its own matching.

### Locked decisions
| Decision | Choice |
|---|---|
| Handset caller ID mechanism | **Live wazo-dird source plugin** (replaces phonebook sync) |
| Project scope (this repo) | **Plugin + written contract** for the OptimoGo endpoint (endpoint built separately in `optimogo-site`) |
| Wazo deployment target | **Debian host install**; packaged as a **wazo-plugind** plugin |
| Lookups provided | **Reverse + forward search** |
| Plugin → OptimoGo auth | **Per-tenant bearer API key** (separate from the webhook secret), overlapping rotation |
| Transport | **HTTPS POST with JSON body** (keeps numbers/terms out of query strings & logs) |
| Resilience posture | **Bounded fail-open + short TTL cache + circuit breaker** (a lookup never drops a call; worst case adds ≤ timeout to ring setup) |
| Ambiguous reverse match (handset) | **`"Maybe: {name}"`** (configurable prefix) on the best candidate, still reporting `match_state=ambiguous` + `candidate_count` |

---

## 3. Plugin architecture

Distribution: Python package **`wazo-dird-optimogo`**, module **`wazo_dird_optimogo`**, backend name **`optimogo`**, registered under the setuptools entry point group **`wazo_dird.backends`** (exact base class and import path pinned to the deployed Wazo release — §10).

### 3.1 Package layout
```
wazo_dird_optimogo/
  __init__.py
  plugin.py          # OptimoGoSourcePlugin(BaseSourcePlugin) — SPI methods + outermost safety-catch
  http_client.py     # OptimoGoClient: POST JSON, bearer auth, connect/read timeouts, thread-safe pooled session, typed errors
  cache.py           # TTLCache: per-source, positive + negative TTLs, bounded LRU, lock-guarded
  breaker.py         # CircuitBreaker: opens after N consecutive failures, cooldown, sampled probes
  mapping.py         # endpoint JSON -> dird result dicts (canonical columns + stable row id)
  schema.py          # marshmallow source-config schema + validation
  exceptions.py      # OptimoGoLookupError, OptimoGoAuthError, OptimoGoTimeout, OptimoGoUnavailable
setup.py             # entry_points: wazo_dird.backends =
                     #   optimogo = wazo_dird_optimogo.plugin:OptimoGoSourcePlugin
```

### 3.2 Backend class — `OptimoGoSourcePlugin(BaseSourcePlugin)`
Implements the wazo-dird source SPI:

- **`load(dependencies)`** — `dependencies` provides `auth_client`, `config` (source-specific), `main_config`, `token_renewer`. Validate config (§3.3), build `OptimoGoClient`, `TTLCache`, `CircuitBreaker`; set the canonical column constants (§3.4). A `load` failure must raise clearly (so provisioning fails loudly) but must **not** be able to crash dird startup for *other* sources — confirm dird isolates a failing source (§10).
- **`first_match(exten, args=None) -> dict | None`** — cache + breaker-guarded single reverse lookup; one result dict or `None`.
- **`match_all(extens, args=None) -> dict[str, dict]`** — reverse-lookup **multiple numbers in one batch HTTP call** (§4.2 batch), mapping number → result dict (unmatched numbers omitted). This backs multi-number reverse paths (e.g. call-history enrichment), **not** a ring group of destinations. Whether `callerid_forphones` invokes `first_match` or `match_all` for handset caller ID is a §10 verification item; both are implemented and behave consistently.
- **`search(term, args=None) -> list[dict]`** — forward search; list of result dicts.
- **`list(uids, args) -> list[dict]`** — returns `[]` (favorites not supported by this source; documented, not silently empty).
- **`unload()`** — close the HTTP session / release the pool.

**Outermost safety-catch.** Each dird-facing method (`first_match`, `match_all`, `search`, `list`) wraps its body in a single deliberate boundary `try/except Exception` that logs redacted context and returns the fail-open value (`None` / `{}` / `[]`). This is **not** the lazy catch RULES.md forbids — typed exceptions are still handled specifically inside (§7); this is a documented last-resort net on a real-time path so that an unforeseen error (JSON decode, mapping bug, cache/breaker bug) can never propagate into the dialplan. Tested explicitly (§9).

**Thread-safety.** A single source instance is shared across dird's concurrent worker threads. The cache is lock-guarded; the breaker uses atomic/locked counters; the HTTP client uses a pooled session configured once at `load` and never mutated per-call (§6). Confirm dird's threading/instance-sharing model in §10.

Result dicts are keyed by the source's canonical columns (§3.4); empty fields are `None` per the SPI convention ("Empty values should be `None`, instead of empty string").

### 3.3 Source config schema (per tenant)
| key | purpose | default |
|---|---|---|
| `lookup_url` | tenant-scoped OptimoGo base URL (`…/api/wazo/dird/<tenant_schema>`) | required |
| `api_key` | per-tenant bearer key | required |
| `connect_timeout` | TCP/TLS connect budget (s) | `0.4` |
| `read_timeout` | response read budget (s) | `0.8` |
| `cache_ttl` | positive-result TTL (s) | `60` |
| `negative_cache_ttl` | not-found TTL (s) | `30` |
| `cache_max_entries` | LRU bound | `5000` |
| `breaker_failure_threshold` | consecutive failures before opening | `5` |
| `breaker_cooldown` | open-state duration before a probe (s) | `30` |
| `ambiguous_prefix` | handset label prefix on ambiguous match | `"Maybe: "` |
| `search_min_term_length` | below this, skip the HTTP call, return `[]` | `3` |
| `search_max_term_length` | above this, truncate/skip (return `[]`) | `64` |
| `search_limit` | max rows requested | `25` |
| `verify_certificate` | TLS verify (bool or CA-bundle path); **`false` is emergency-diagnostics only** — logs loudly and is forbidden by production provisioning | `true` |

No HTTP retries or redirect-following on the reverse (pre-ring) path; the effective wall-clock budget is `connect_timeout + read_timeout`. Config is validated by a marshmallow schema at `load`; required fields enforced, bad values rejected, `verify_certificate=false` warns.

### 3.4 Canonical columns & row identity
Endpoint rows map to a fixed column set so result formatting, dedup, and click-to-dial row identity are unambiguous:

| column | source | role |
|---|---|---|
| `id` | `"customer:<customer_id>:number:<E164>"` | **`unique_column`** — stable per-row id (a customer with N numbers yields N distinct rows) |
| `name` | customer (or contact) display name | searched + first-matched display |
| `number` | canonical E164 number | the dialable number; `first_matched_columns = ["number"]` |
| `customer_id` | OptimoGo customer pk | click-through / correlation (not unique per row) |
| `contact_name` | matched contact, nullable | |
| `display_name` | `"Maybe: " + name` when ambiguous, else `name` | handset/display label |

`searched_columns = ["name", "number"]`, `first_matched_columns = ["number"]`, `unique_column = "id"`. The reverse profile's display maps `display_name` to the handset name field (verify display mapping — §10).

---

## 4. OptimoGo endpoint contract (deliverable for `optimogo-site`)

Not built in this repo, but fully specified so the `optimogo-site` work is a known task. Mirrors the existing webhook design's tenant-scoping and secret-hardening. **All requests are HTTPS `POST` with a JSON body** — phone numbers and search terms must never appear in URLs/query strings (they would leak into access, proxy, and APM logs).

### 4.1 Tenant scoping & auth
- `lookup_url` base = `https://<optimogo-host>/api/wazo/dird/<tenant_schema>`; the plugin appends the mode path (`/reverse`, `/reverse/batch`, `/search`).
- Every request carries `Authorization: Bearer <api_key>` over HTTPS; `Content-Type: application/json`.
- The endpoint resolves `<tenant_schema>` (404 if unknown — tenant-schema names are treated as **non-secret**, so enumeration via 404-vs-403 is acceptable and intentional), switches into that schema, **constant-time compares** the key against a per-tenant **hashed, rotatable** dird key on `WazoConnection`, then reuses `match_customer_by_phone()`.
- **Rotation is overlapping:** OptimoGo accepts a current **and** previous key (`dird_key_hash` + `dird_key_hash_previous`, like the webhook dual-secret) so the key can be rotated on OptimoGo first and on the Wazo source config second without a window where every lookup silently fails. Repeated `401/403` raises an **auth-failure alert** to the tenant admin.
- The Wazo-side `api_key` lives in the dird source config (readable by Wazo admins/API/backups) — treat it as a tenant secret of equivalent sensitivity to the webhook secret; uninstall removes the source (and thus the key) — §8.2.

### 4.2 Reverse mode
Single — `POST {base}/reverse` body `{"number": "<raw_or_e164>"}`:
```json
// 200 matched
{ "match": { "id": "customer:123:number:+61399999999", "display_name": "Acme Plumbing",
             "name": "Acme Plumbing", "number": "+61399999999", "customer_id": 123,
             "contact_name": "John Smith", "match_state": "matched", "candidate_count": 1 } }

// 200 no match
{ "match": null }

// 200 ambiguous (number shared by >1 customer)
{ "match": { "id": "customer:123:number:+61399999999", "display_name": "Maybe: Acme Plumbing",
             "name": "Acme Plumbing", "number": "+61399999999", "customer_id": 123,
             "contact_name": null, "match_state": "ambiguous", "candidate_count": 3 } }
```
Batch — `POST {base}/reverse/batch` body `{"numbers": ["+61...", "+61..."]}` → `{"matches": {"<number>": <match-or-null>, ...}}`. Backs `match_all`.

**Ambiguous handling:** the best candidate is chosen deterministically (default: most-recent activity `updated_at` desc, tie-broken by `customer_id`); `name` is the real customer name and **`display_name` is prefixed with `ambiguous_prefix` (`"Maybe: "`)** so the handset itself signals uncertainty (the device cannot see `match_state`). `match_state`/`candidate_count` remain for logging/observability.

**Input normalization (server + plugin):** an empty/missing number, `anonymous`/withheld/private caller, or non-dialable token → the plugin **skips the HTTP call** and returns `None` (no point querying). The server normalizes national vs E.164 (reusing `core/utils/phone.py`) and treats unparseable input as no-match. Matching is via the Django ORM (parameterized — no injection surface).

### 4.3 Search mode — `POST {base}/search` body `{"term": "<text>", "limit": 25}`
```json
// 200
{ "results": [
  { "id": "customer:123:number:+61399999999", "display_name": "Acme Plumbing", "name": "Acme Plumbing",
    "number": "+61399999999", "customer_id": 123, "contact_name": null },
  { "id": "customer:123:number:+61400000000", "display_name": "Acme Plumbing — John Smith",
    "name": "John Smith", "number": "+61400000000", "customer_id": 123, "contact_name": "John Smith" }
] }
```
The plugin enforces `search_min_term_length`/`search_max_term_length` before calling (short/over-long/blank term → `[]`, no HTTP). **`limit` caps the number of customers matched server-side; each is then expanded to one row per dialable number, with an overall hard row cap** (e.g. `limit * max_numbers_per_customer`, bounded) so a customer with many numbers can't blow up the response.

### 4.4 Response handling (drives fail-open precisely)
**Success is narrow:** HTTP `200` **with** a well-formed JSON body matching the expected schema and `Content-Type: application/json`. Everything else is fail-open.

| Condition | Plugin behavior |
|---|---|
| `200` + valid schema, `match`/`results` present (incl. `match: null` / empty `results`) | use it; positive → positive cache, `null`/empty → negative cache |
| `200` + malformed/oversized body, wrong `Content-Type`, unexpected shape | log (redacted) + fail-open; **no cache**; counts toward breaker |
| `401` / `403` | log + fail-open; **no cache**; auth-failure alert; **does not** trip the breaker (rotating, not down) |
| `429` | fail-open; **no cache**; **feeds the breaker** (back off) |
| `408` / `409` / `422` / other `4xx` | log + fail-open; no cache |
| `5xx` / timeout / connection / DNS / TLS error | fail-open; no cache; **feeds the breaker** |

"Fail-open" always means return `None`/`{}`/`[]` so the call proceeds with the raw number. The plugin **never raises into the dialplan** (§3.2 safety-catch). Response bodies are size-capped before parsing.

### 4.5 Field → dird columns
Endpoint fields map to the canonical columns of §3.4. The reverse profile's display uses `display_name` for the handset name; `format_columns` may compose an alternate `display_name` per tenant.

---

## 5. Data flow

### 5.1 Reverse lookup (pre-ring, blocks the call — must be fast)
1. Inbound call → Asterisk dialplan → `callerid_forphones` AGI → `wazo-dird` reverse service on the tenant's reverse profile.
2. dird calls the source's `first_match(number)` (or `match_all(numbers)` for multi-number paths).
3. Plugin: if the number is empty/anonymous/withheld → return `None` (no HTTP). Else normalize → cache key. **Hit** → return cached. **Breaker open** → return `None` immediately (no HTTP) unless it's a sampled probe. **Miss + breaker closed** → `POST /reverse` with bearer, `connect_timeout`+`read_timeout`.
4. `200` + valid match → map to dict, positive-cache, return. `200` + `null` → negative-cache, return `None`. Any failure (§4.4) → log redacted, update breaker, return `None`, **do not cache**.
5. dird aggregates across sources; `None` here → handset shows the raw number (fail-open). Match → phone rings with the OptimoGo name. **Worst-case added latency for this source ≈ `connect_timeout + read_timeout`**; dird's total reverse latency also depends on its other sources and whether it queries them in parallel (verify — §10).

### 5.2 Forward search
1. Agent searches the directory → `wazo-dird` lookup profile → source `search(term)`.
2. Plugin: enforce term-length bounds (→ `[]` if out of range, no HTTP); cache key `(search, normalized_term, limit)`. **Hit** → return cached. **Breaker open** → `[]`. **Miss** → `POST /search` with bearer, timeouts.
3. `200` + valid → positive-cache and return (empty `results` → negative-cache). Any failure → return `[]`, no cache (other dird sources still contribute).

---

## 6. Resilience & caching

- **Bounded fail-open (not absolute).** A lookup never drops or indefinitely blocks a call, but a cache+breaker miss costs up to `connect_timeout + read_timeout` of ring-setup delay on this source. That bounded delay is the accepted cost of live lookup.
- **Circuit breaker** (`breaker.py`). After `breaker_failure_threshold` consecutive failures (5xx/timeout/conn/429/malformed — **not** 401/403), the breaker **opens** for `breaker_cooldown`: during open state, lookups fail-open **immediately without an HTTP attempt**, so an OptimoGo outage doesn't make every inbound call eat the full timeout. A single sampled probe per cooldown re-closes it on success. State is per-source, lock-guarded.
- **`TTLCache`** (`cache.py`), per source, **lock-guarded** (shared across worker threads). Key `(mode, normalized_term[, limit])`. Positive cached `cache_ttl` (60s); `null`/empty cached `negative_cache_ttl` (30s); **errors/timeouts never cached** (handled by the breaker instead). Ambiguous results cached like positive. Bounded by `cache_max_entries` with LRU eviction; lazy expiry on read, no background threads.
- **HTTP client** (`http_client.py`): one pooled `requests.Session` (or equivalent) created at `load`, configured immutably, used concurrently across threads; separate connect/read timeouts; no retries/redirects on the reverse path.
- **Stale-name window (accepted UX tradeoff, stated explicitly):** the 60s positive cache can briefly show a pre-edit name after a rename/merge/number reassignment; the 30s negative cache can briefly hide a just-created customer; an ambiguous selection can persist for the TTL. Acceptable for caller ID; tunable per source via the TTLs.

---

## 7. Error handling

Typed exceptions in `http_client.py` — `OptimoGoAuthError`, `OptimoGoTimeout`, `OptimoGoUnavailable`, `OptimoGoLookupError` — caught **explicitly** in the plugin (no lazy blanket catch), each mapped to the §4.4 behavior and the breaker. **Above** that, each SPI method has the single documented outermost safety-catch (§3.2) as a real-time-path last resort. The `api_key` and request bodies are **never logged**; the `Authorization` header is redacted; logs record only mode, a hashed/truncated term token (not the raw PII number), status, latency, and breaker state. Metrics (counters/histograms) are emitted for: lookups by mode, hit/miss, match/no-match/ambiguous, failures by class, breaker open/close, latency — for observability.

---

## 8. Packaging, deployment & provisioning

### 8.1 wazo-plugind plugin
A git repo with `wazo/plugin.yml` (namespace/name **`optimo/wazo-dird-optimogo`**) whose Debian build rule pip-installs the wheel into the `wazo-dird` Python env, and whose install hook restarts `wazo-dird`. Installable via the Wazo plugin admin or `wazo-plugind-cli`.

**Live-PBX safety:**
- Restarting `wazo-dird` momentarily interrupts caller-ID lookups — schedule installs/upgrades in a low-traffic window; document the brief blip.
- A broken plugin must not prevent `wazo-dird` from starting (other sources/services must survive). Confirm dird's per-source isolation (§10); the install hook **post-restart health-checks** dird (and the source loads) and **rolls back** the install on failure.
- The pinned Wazo release is recorded; the package declares the compatible dird version range and fails install on mismatch.

### 8.2 Per-tenant provisioning (documented + scriptable)
1. Create one `optimogo` **source** — `POST /api/dird/0.1/backends/optimogo/sources` with the §3.3 config and the `Wazo-Tenant` header.
2. Bind that source to the tenant's **reverse** profile (caller ID) and a **lookup** profile (search) via the dird profiles API; confirm the reverse profile's **display** maps `display_name` to the handset name field.
3. **Teardown order on uninstall/disable:** **unbind** the source from all profiles **first**, then delete the source, then remove the package — so no profile is left referencing a dead source. Removing the source removes the stored `api_key`.

This mirrors how the telephony design provisions dird/webhook resources on connect, and is a natural extension point for the telephony app's `connectWazo` later.

---

## 9. Testing strategy

Pytest, verbose and adversarial (per CLAUDE.md) — stubbed OptimoGo via `responses`/`respx`; tests reflect real usage and are designed to reveal flaws.

- **Reverse:** matched → dict; `match: null` → `None`; ambiguous → `display_name` carries `"Maybe: "` prefix + `match_state=ambiguous` + `candidate_count`; deterministic tie-break ordering; canonical `id` shape.
- **`match_all` / batch:** N numbers → **one** `POST /reverse/batch`; correct per-number mapping; unmatched omitted.
- **Search:** multiple results, one row per number, `limit`/row-cap honored; term shorter than min, longer than max, blank → `[]` with **no HTTP call**.
- **Bounded fail-open:** timeout, 5xx, 401/403, 429, 408/409/422, malformed-JSON-on-200, wrong `Content-Type`, oversized body, DNS/TLS error → `None`/`{}`/`[]`; call never blocked; errors not cached; correct breaker feeding (401/403 does **not** trip; 429/5xx do).
- **Outermost safety-catch:** an injected unexpected exception (e.g. mapping bug, cache bug) in each SPI method is swallowed → fail-open value, logged redacted, **never propagates**.
- **Circuit breaker:** opens after threshold consecutive failures; open state returns fail-open with **no HTTP**; sampled probe re-closes on success; per-source isolation.
- **Cache + concurrency:** positive hit within TTL (no 2nd HTTP), expiry re-fetches, negative cache, LRU bound; **concurrent calls from multiple threads** don't corrupt the cache or duplicate-store (lock correctness); pooled session is safe under concurrency.
- **Auth/redaction:** bearer header sent; `api_key`/`Authorization`/raw number/term **never** appear in logs; overlapping-key rotation (old+new both accepted); auth-failure alert on repeated 401/403.
- **Config schema:** required fields, defaults, bad values rejected at `load`; `verify_certificate=false` warns.
- **Provisioning/packaging:** entry point resolves `optimogo` → the plugin class; source-create + profile-bind happy path; teardown unbinds before delete; install health-check + rollback on a deliberately broken build; source **reload** / config rotation without restart leaves a consistent client.

---

## 10. Open items to verify before/during planning

1. **Pin the Wazo release** and confirm against it: the dird source base class + import path + method signatures + `dependencies` keys; the dird **threading/instance-sharing** model (is one source instance shared across worker threads? — drives the cache/session locking); whether a failing source can block dird startup (per-source isolation).
2. Exact dird **source-create + profile-bind** API shapes, and which profile `callerid_forphones` reads (typically `default`); whether it calls `first_match` or `match_all`; confirm the reverse profile **display** maps `display_name` to the handset name field; whether dird queries sources in **parallel** (latency bound) or serially.
3. Whether `wazo-dird` runs in **system Python** vs a venv on this Debian build (pip-install target in `plugin.yml`).
4. Form of the incoming `number` the dialplan passes (national vs E.164; `anonymous`/withheld tokens) — confirm plugin skip-rules and OptimoGo normalization cover all.
5. wazo-plugind `plugin.yml` build / Debian-rule specifics for installing a pip wheel + restarting `wazo-dird`, plus the **post-install health-check + rollback** hook.
6. **csv_ws alternative (rationale, version-pinned):** the build-vs-configure decision rests on the stock `csv_ws` backend lacking custom/bearer headers and caching (verified against current upstream source). Re-confirm against the deployed dird release; it is unsuitable regardless because this design needs JSON, ambiguity metadata, bearer auth, a breaker, and custom caching.
7. The OptimoGo endpoint (separate `optimogo-site` work): add the tenant-scoped dird key (hashed, **dual current+previous**, rotatable) to `WazoConnection`; add the reverse / reverse-batch / search views reusing `match_customer_by_phone()` + a search query; auth-failure alerting.

---

## 11. Out of scope / future

- Favorites/personal contacts from OptimoGo as a dird source.
- Click-to-dial / outbound origination.
- A shared multi-tenant lookup endpoint (each tenant has a dedicated Wazo + dedicated OptimoGo connection).
