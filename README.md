# wazo-dird-optimogo

A [wazo-dird](https://wazo-platform.org) source backend (`optimogo`) that resolves
caller IDs (reverse) and directory searches (forward) against a tenant's OptimoGo
JSON HTTP endpoint, with bounded fail-open behavior (tight timeout + TTL cache +
circuit breaker) so it never blocks or breaks the pre-ring dialplan.

- **Design spec:** `docs/superpowers/specs/2026-06-16-wazo-dird-optimogo-lookup-design.md`
- **Implementation plan:** `docs/superpowers/plans/2026-06-16-wazo-dird-optimogo-plugin.md`
- **Install & provisioning:** `docs/INSTALL.md`

## Architecture

A thin SPI glue class (`plugin.py`, the only module importing `wazo_dird`) wraps
pure-Python modules:

| Module | Responsibility |
|---|---|
| `http_client.py` | POST-JSON to OptimoGo: bearer auth, connect/read timeouts, 1 MiB body cap, typed errors |
| `cache.py` | thread-safe bounded TTL+LRU cache (negative results cacheable) |
| `breaker.py` | per-source circuit breaker (fail-open immediately during an outage) |
| `engine.py` | orchestration: skip → cache → breaker → HTTP → map; never raises |
| `mapping.py` | OptimoGo JSON → dird columns; applies the configurable `"Maybe: "` ambiguous prefix |
| `inputs.py` | skip-rules (anonymous/withheld/non-dialable) + cache-key normalization |
| `schema.py` | marshmallow source-config validation |
| `exceptions.py` | typed errors that drive the fail-open + breaker policy |
| `plugin.py` | `OptimoGoSourcePlugin(BaseSourcePlugin)`: `first_match`/`match_all`/`search`/`list` + outermost safety-catch |

## Development & tests

The pure-Python core (no `wazo_dird`) runs on any host:

    python3 -m venv .venv
    .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest -m "not needs_dird"

The SPI glue + entry-point tests need a real `wazo_dird`, provided by a container
pinned to the deployed version (Debian bookworm + wazo-dird 26.05, `linux/amd64`):

    docker build --platform linux/amd64 -f Dockerfile.dev -t wazo-dird-optimogo-dev .
    docker run --rm --platform linux/amd64 wazo-dird-optimogo-dev pytest -v

The full suite (core + `needs_dird`) passes in the container.

## Packaging

`wazo/plugin.yml` + `wazo/rules` package this as a wazo-plugind plugin
(`optimo/wazo-dird-optimogo`, `plugin_format_version: 2`). See `docs/INSTALL.md`.
