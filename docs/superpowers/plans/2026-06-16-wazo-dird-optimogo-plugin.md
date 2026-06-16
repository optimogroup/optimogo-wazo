# wazo-dird OptimoGo Lookup Plugin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `wazo-dird-optimogo` Python package — a wazo-dird source backend (`optimogo`) that resolves caller IDs (reverse) and directory searches (forward) against a tenant's OptimoGo JSON HTTP endpoint — plus its wazo-plugind packaging.

**Architecture:** A thin SPI glue class (`plugin.py`) wraps a set of pure-Python modules — HTTP client, TTL cache, circuit breaker, input rules, JSON→column mapping, config schema — none of which import `wazo_dird`. This keeps ~90% of the code TDD-able on macOS with plain pytest; only `plugin.py` and the entry-point smoke test need a Debian container with a pinned `wazo-dird`. Every lookup is bounded fail-open: a tight timeout, a cache, and a breaker guarantee the dialplan is never blocked or broken.

**Tech Stack:** Python 3 (match the deployed dird's Python), `requests`, `marshmallow` (config validation), `pytest` + `responses` (HTTP stubbing), `wazo_dird` SPI (`BaseSourcePlugin`, `make_result_class`), wazo-plugind packaging (`wazo/plugin.yml`).

**Reference spec:** `docs/superpowers/specs/2026-06-16-wazo-dird-optimogo-lookup-design.md`

---

## File structure

```
wazo-optimogo/
  setup.py                          # package metadata + wazo_dird.backends entry point
  requirements-dev.txt              # pytest, responses, marshmallow, requests
  pytest.ini                        # pytest config + markers (needs_dird)
  Dockerfile.dev                    # pinned wazo-dird base for SPI/packaging tests
  wazo_dird_optimogo/
    __init__.py
    exceptions.py                   # typed errors
    schema.py                       # marshmallow source-config schema
    inputs.py                       # number skip-rules, term validation, cache-key normalization
    cache.py                        # TTLCache (lock-guarded, LRU, positive/negative TTL)
    breaker.py                      # CircuitBreaker
    http_client.py                  # OptimoGoClient (POST JSON, bearer, timeouts, size cap, typed errors)
    mapping.py                      # endpoint JSON -> dird field dicts (canonical id, Maybe-prefix, None-empties)
    plugin.py                       # OptimoGoSourcePlugin(BaseSourcePlugin) — SPI + safety-catch wiring
  tests/
    __init__.py
    conftest.py                     # shared fixtures (valid config dict, fake clock)
    test_schema.py
    test_inputs.py
    test_cache.py
    test_breaker.py
    test_http_client.py
    test_mapping.py
    test_plugin.py                  # @needs_dird (container)
    test_entry_point.py             # @needs_dird (container)
  wazo/
    plugin.yml                      # wazo-plugind manifest
    Makefile                        # build/install/uninstall rules
  docs/
    INSTALL.md                      # provisioning: create source, bind profiles, teardown order
```

**Module dependency direction:** `plugin.py` → (`schema`, `inputs`, `cache`, `breaker`, `http_client`, `mapping`, `exceptions`). The leaf modules import only stdlib + `requests`/`marshmallow`, never `wazo_dird`. Only `plugin.py` imports `wazo_dird`.

**Deliberate refinement over spec §4.4 (note for the implementer):** the circuit breaker is fed by **every error class except `OptimoGoAuthError`** — i.e. `OptimoGoTimeout`, `OptimoGoUnavailable` (5xx/429/conn/DNS/TLS), and `OptimoGoLookupError` (malformed/oversized/wrong-content-type/other-4xx). Auth failures (401/403) never trip the breaker (rotation in progress, not an outage) and instead log at ERROR for the OptimoGo-side alert. This matches the spec's intent (429/5xx/malformed feed the breaker; 401/403 don't) with one clean rule.

---

## Task 1: Project scaffolding

**Files:**
- Create: `setup.py`, `requirements-dev.txt`, `pytest.ini`, `wazo_dird_optimogo/__init__.py`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Create the package skeleton files**

`wazo_dird_optimogo/__init__.py`:
```python
__version__ = '1.0.0'
```

`tests/__init__.py`:
```python
```

`requirements-dev.txt`:
```text
requests>=2.25
marshmallow>=3.13,<4
pytest>=7
responses>=0.23
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
markers =
    needs_dird: test requires the wazo_dird package (run in Dockerfile.dev container)
addopts = -v
```

`setup.py`:
```python
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
```

`tests/conftest.py`:
```python
import pytest


class FakeClock:
    """Deterministic monotonic clock for cache/breaker tests."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def valid_config():
    """A minimal valid source-config dict as wazo-dird would pass it in args['config']."""
    return {
        'name': 'optimogo',
        'lookup_url': 'https://opt.example.com/api/wazo/dird/acme',
        'api_key': 'secret-key',
    }
```

- [ ] **Step 2: Create the dev virtualenv and install dev deps**

Run:
```bash
cd /Users/jayden/public_html/wazo-optimogo
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```
Expected: installs requests, marshmallow, pytest, responses with no errors.

- [ ] **Step 3: Verify pytest collects nothing yet (sanity)**

Run: `.venv/bin/pytest`
Expected: `no tests ran` (exit code 5) — confirms config is valid.

- [ ] **Step 4: Commit**

```bash
git add setup.py requirements-dev.txt pytest.ini wazo_dird_optimogo/__init__.py tests/__init__.py tests/conftest.py
git commit -m "chore: scaffold wazo-dird-optimogo package"
```

---

## Task 2: Pin the deployed wazo-dird version & write Dockerfile.dev

This is a verification task — it determines real environment values used by later container-run tasks. Do it before writing `plugin.py`.

**Files:**
- Create: `Dockerfile.dev`

- [ ] **Step 1: Determine the deployed wazo-dird version on the PBX**

Run (against the PBX host `pbx.local.optimo.group`, via SSH or `! ssh ...`):
```bash
dpkg-query -W -f='${Version}\n' wazo-dird
python3 -c "import wazo_dird, inspect, os; print(os.path.dirname(inspect.getfile(wazo_dird)))"
```
Record the exact `wazo-dird` version string (e.g. `24.16`) and the Debian release codename:
```bash
. /etc/os-release; echo "$VERSION_CODENAME"
cat /etc/apt/sources.list.d/*wazo* 2>/dev/null
```
Expected: a concrete version (call it `<WAZO_DIRD_VERSION>`), the Debian codename (e.g. `bookworm`), and the Wazo apt repo line.

- [ ] **Step 2: Confirm the real SPI on the PBX matches the plan's assumptions**

Run on the PBX:
```bash
python3 - <<'PY'
import inspect
from wazo_dird import BaseSourcePlugin, make_result_class
print("BaseSourcePlugin methods:")
for m in ('load', 'search', 'first_match', 'match_all', 'list', 'unload'):
    print(" ", m, inspect.signature(getattr(BaseSourcePlugin, m)))
print("class attrs:", BaseSourcePlugin.SEARCHED_COLUMNS, BaseSourcePlugin.FIRST_MATCHED_COLUMNS,
      BaseSourcePlugin.FORMAT_COLUMNS, BaseSourcePlugin.UNIQUE_COLUMN)
print("make_result_class:", inspect.signature(make_result_class))
PY
```
Expected: `load(self, args)`, `search(self, term, args=None)`, `first_match(self, exten, args=None)`, `match_all(self, extens, args=None)`, `list(self, uids, args)`, and `make_result_class(backend, name, unique_column, format_columns, ...)`. **If signatures differ, update Task 9/10 code to match before implementing.**

- [ ] **Step 3: Write Dockerfile.dev pinned to that version**

`Dockerfile.dev` (fill `<DEBIAN_CODENAME>`, `<WAZO_APT_REPO_LINE>`, `<WAZO_DIRD_VERSION>` from Step 1):
```dockerfile
# Reproduces the PBX's wazo-dird environment for SPI + packaging tests.
FROM debian:<DEBIAN_CODENAME>

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates gnupg curl python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Wazo apt repo (from Step 1) + pinned wazo-dird so the SPI matches prod.
RUN echo "<WAZO_APT_REPO_LINE>" > /etc/apt/sources.list.d/wazo.list \
    && curl -fsSL https://mirror.wazo.community/wazo_current.key | gpg --dearmor -o /usr/share/keyrings/wazo.gpg \
    && apt-get update \
    && apt-get install -y --no-install-recommends wazo-dird=<WAZO_DIRD_VERSION>* \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY requirements-dev.txt .
RUN pip3 install --break-system-packages -r requirements-dev.txt
COPY . .
RUN pip3 install --break-system-packages -e .
CMD ["pytest", "-m", "needs_dird"]
```

- [ ] **Step 4: Build the image and confirm the SPI imports inside it**

Run:
```bash
docker build -f Dockerfile.dev -t wazo-dird-optimogo-dev .
docker run --rm wazo-dird-optimogo-dev python3 -c "from wazo_dird import BaseSourcePlugin, make_result_class; print('ok')"
```
Expected: `ok`. If `wazo-dird` cannot be apt-installed at that version, fall back to the published `wazoplatform/wazo-dird:<tag>` base image and re-run.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile.dev
git commit -m "build: add Dockerfile.dev pinned to deployed wazo-dird"
```

---

## Task 3: Typed exceptions

**Files:**
- Create: `wazo_dird_optimogo/exceptions.py`, `tests/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

`tests/test_exceptions.py`:
```python
from wazo_dird_optimogo.exceptions import (
    OptimoGoError, OptimoGoAuthError, OptimoGoTimeout,
    OptimoGoUnavailable, OptimoGoLookupError,
)


def test_all_errors_subclass_base():
    for cls in (OptimoGoAuthError, OptimoGoTimeout, OptimoGoUnavailable, OptimoGoLookupError):
        assert issubclass(cls, OptimoGoError)


def test_base_is_exception():
    assert issubclass(OptimoGoError, Exception)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_exceptions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wazo_dird_optimogo.exceptions'`.

- [ ] **Step 3: Implement**

`wazo_dird_optimogo/exceptions.py`:
```python
class OptimoGoError(Exception):
    """Base class for all OptimoGo plugin errors."""


class OptimoGoAuthError(OptimoGoError):
    """401/403 from OptimoGo: bad or rotated API key. Never trips the breaker."""


class OptimoGoTimeout(OptimoGoError):
    """Connect or read timeout talking to OptimoGo. Feeds the breaker."""


class OptimoGoUnavailable(OptimoGoError):
    """5xx, 429, or connection/DNS/TLS failure from OptimoGo. Feeds the breaker."""


class OptimoGoLookupError(OptimoGoError):
    """200 with malformed/oversized/wrong-type body, or other 4xx. Feeds the breaker."""
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_exceptions.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/exceptions.py tests/test_exceptions.py
git commit -m "feat: typed OptimoGo plugin exceptions"
```

---

## Task 4: Config schema

**Files:**
- Create: `wazo_dird_optimogo/schema.py`, `tests/test_schema.py`

- [ ] **Step 1: Write the failing test**

`tests/test_schema.py`:
```python
import pytest
from marshmallow import ValidationError
from wazo_dird_optimogo.schema import load_config


def test_minimal_config_gets_defaults(valid_config):
    cfg = load_config(valid_config)
    assert cfg['name'] == 'optimogo'
    assert cfg['connect_timeout'] == 0.4
    assert cfg['read_timeout'] == 0.8
    assert cfg['cache_ttl'] == 60
    assert cfg['negative_cache_ttl'] == 30
    assert cfg['cache_max_entries'] == 5000
    assert cfg['breaker_failure_threshold'] == 5
    assert cfg['breaker_cooldown'] == 30.0
    assert cfg['ambiguous_prefix'] == 'Maybe: '
    assert cfg['search_min_term_length'] == 3
    assert cfg['search_max_term_length'] == 64
    assert cfg['search_limit'] == 25
    assert cfg['verify_certificate'] is True
    assert cfg['unique_column'] == 'id'
    assert cfg['first_matched_columns'] == ['number']
    assert cfg['searched_columns'] == ['name', 'number']


def test_missing_required_fields_raise():
    with pytest.raises(ValidationError):
        load_config({'name': 'optimogo'})  # no lookup_url / api_key


def test_bad_timeout_rejected(valid_config):
    bad = dict(valid_config, connect_timeout=0)
    with pytest.raises(ValidationError):
        load_config(bad)


def test_overrides_applied(valid_config):
    cfg = load_config(dict(valid_config, cache_ttl=120, ambiguous_prefix='? '))
    assert cfg['cache_ttl'] == 120
    assert cfg['ambiguous_prefix'] == '? '
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wazo_dird_optimogo.schema'`.

- [ ] **Step 3: Implement**

`wazo_dird_optimogo/schema.py`:
```python
from marshmallow import Schema, fields, validate, EXCLUDE


class _ConfigSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    name = fields.String(required=True, validate=validate.Length(min=1))
    lookup_url = fields.Url(required=True)
    api_key = fields.String(required=True, validate=validate.Length(min=1))
    connect_timeout = fields.Float(load_default=0.4, validate=validate.Range(min=0.05))
    read_timeout = fields.Float(load_default=0.8, validate=validate.Range(min=0.05))
    cache_ttl = fields.Integer(load_default=60, validate=validate.Range(min=0))
    negative_cache_ttl = fields.Integer(load_default=30, validate=validate.Range(min=0))
    cache_max_entries = fields.Integer(load_default=5000, validate=validate.Range(min=1))
    breaker_failure_threshold = fields.Integer(load_default=5, validate=validate.Range(min=1))
    breaker_cooldown = fields.Float(load_default=30.0, validate=validate.Range(min=1))
    ambiguous_prefix = fields.String(load_default='Maybe: ')
    search_min_term_length = fields.Integer(load_default=3, validate=validate.Range(min=1))
    search_max_term_length = fields.Integer(load_default=64, validate=validate.Range(min=1))
    search_limit = fields.Integer(load_default=25, validate=validate.Range(min=1, max=200))
    verify_certificate = fields.Raw(load_default=True)
    first_matched_columns = fields.List(fields.String(), load_default=lambda: ['number'])
    searched_columns = fields.List(fields.String(), load_default=lambda: ['name', 'number'])
    format_columns = fields.Dict(load_default=dict)
    unique_column = fields.String(load_default='id')


_SCHEMA = _ConfigSchema()


def load_config(raw):
    """Validate a source-config dict, returning a dict with defaults applied.

    Raises marshmallow.ValidationError on bad input.
    """
    return _SCHEMA.load(raw)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_schema.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/schema.py tests/test_schema.py
git commit -m "feat: marshmallow source-config schema with defaults"
```

---

## Task 5: Input rules (skip + normalization)

**Files:**
- Create: `wazo_dird_optimogo/inputs.py`, `tests/test_inputs.py`

- [ ] **Step 1: Write the failing test**

`tests/test_inputs.py`:
```python
import pytest
from wazo_dird_optimogo.inputs import (
    should_skip_number, normalize_number_key, validate_term, normalize_term_key,
)


@pytest.mark.parametrize('raw', [None, '', '  ', 'anonymous', 'Anonymous', 'unknown',
                                 'private', 'withheld', 'restricted', 'abc', '++'])
def test_skip_non_dialable(raw):
    assert should_skip_number(raw) is True


@pytest.mark.parametrize('raw', ['+61399999999', '0399999999', '  04 1234 5678 '])
def test_do_not_skip_dialable(raw):
    assert should_skip_number(raw) is False


def test_number_key_strips_punctuation_keeps_plus():
    assert normalize_number_key('+61 3 9999-9999') == '+61399999999'
    assert normalize_number_key('(03) 9999 9999') == '0399999999'


def test_validate_term_length_bounds():
    assert validate_term('ab', 3, 64) is None          # too short
    assert validate_term('x' * 65, 3, 64) is None       # too long
    assert validate_term('  ace  ', 3, 64) == 'ace'     # trimmed, ok
    assert validate_term(None, 3, 64) is None


def test_term_key_normalizes_whitespace_and_case():
    assert normalize_term_key('  Acme   Plumbing ') == 'acme plumbing'
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_inputs.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`wazo_dird_optimogo/inputs.py`:
```python
_ANON_TOKENS = frozenset({
    '', 'anonymous', 'unknown', 'unavailable', 'private',
    'withheld', 'restricted', 'asserted', 'anonymous@anonymous.invalid',
})


def should_skip_number(raw):
    """True when there is no point querying OptimoGo (empty/anonymous/non-dialable)."""
    if raw is None:
        return True
    s = raw.strip().lower()
    if s in _ANON_TOKENS:
        return True
    return not any(c.isdigit() for c in s)


def normalize_number_key(raw):
    """Light cache-key normalization: keep a leading '+', drop all non-digits.

    Authoritative E.164 normalization happens server-side; this only collapses
    formatting differences so '+61 3...' and '03...' that are equal as typed hit
    one cache entry.
    """
    s = raw.strip()
    plus = s.startswith('+')
    digits = ''.join(c for c in s if c.isdigit())
    return ('+' if plus else '') + digits


def validate_term(term, min_len, max_len):
    """Return the trimmed term if within [min_len, max_len], else None."""
    if term is None:
        return None
    s = term.strip()
    if len(s) < min_len or len(s) > max_len:
        return None
    return s


def normalize_term_key(term):
    """Cache-key normalization for search terms: lowercased, whitespace-collapsed."""
    return ' '.join(term.strip().lower().split())
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_inputs.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/inputs.py tests/test_inputs.py
git commit -m "feat: input skip-rules and cache-key normalization"
```

---

## Task 6: TTL cache

**Files:**
- Create: `wazo_dird_optimogo/cache.py`, `tests/test_cache.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cache.py`:
```python
from wazo_dird_optimogo.cache import TTLCache


def test_miss_then_hit(clock):
    c = TTLCache(max_entries=10, time_func=clock)
    assert c.get('k') == (False, None)
    c.set('k', {'name': 'Acme'}, ttl=60)
    assert c.get('k') == (True, {'name': 'Acme'})


def test_expiry(clock):
    c = TTLCache(max_entries=10, time_func=clock)
    c.set('k', 'v', ttl=60)
    clock.advance(59)
    assert c.get('k') == (True, 'v')
    clock.advance(2)              # now 61s elapsed
    assert c.get('k') == (False, None)


def test_negative_value_is_cacheable(clock):
    c = TTLCache(max_entries=10, time_func=clock)
    c.set('k', None, ttl=30)       # cached "no match"
    assert c.get('k') == (True, None)


def test_zero_ttl_does_not_store(clock):
    c = TTLCache(max_entries=10, time_func=clock)
    c.set('k', 'v', ttl=0)
    assert c.get('k') == (False, None)


def test_lru_eviction(clock):
    c = TTLCache(max_entries=2, time_func=clock)
    c.set('a', 1, ttl=60)
    c.set('b', 2, ttl=60)
    c.get('a')                     # 'a' now most-recently used
    c.set('c', 3, ttl=60)          # evicts least-recently used 'b'
    assert c.get('b') == (False, None)
    assert c.get('a') == (True, 1)
    assert c.get('c') == (True, 3)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_cache.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`wazo_dird_optimogo/cache.py`:
```python
import threading
import time as _time
from collections import OrderedDict

_MISS = object()


class TTLCache:
    """Thread-safe, bounded, lazily-expiring TTL cache.

    Values may be any object, including None (a cached negative result).
    get() returns (hit: bool, value). A single instance is shared across
    wazo-dird worker threads, so every access is lock-guarded.
    """

    def __init__(self, max_entries, time_func=_time.monotonic):
        self._max = max_entries
        self._time = time_func
        self._lock = threading.Lock()
        self._data = OrderedDict()  # key -> (expires_at, value)

    def get(self, key):
        now = self._time()
        with self._lock:
            entry = self._data.get(key, _MISS)
            if entry is _MISS:
                return (False, None)
            expires_at, value = entry
            if expires_at <= now:
                del self._data[key]
                return (False, None)
            self._data.move_to_end(key)
            return (True, value)

    def set(self, key, value, ttl):
        if ttl <= 0:
            return
        expires_at = self._time() + ttl
        with self._lock:
            self._data[key] = (expires_at, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_cache.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/cache.py tests/test_cache.py
git commit -m "feat: thread-safe bounded TTL cache"
```

---

## Task 7: Circuit breaker

**Files:**
- Create: `wazo_dird_optimogo/breaker.py`, `tests/test_breaker.py`

- [ ] **Step 1: Write the failing test**

`tests/test_breaker.py`:
```python
from wazo_dird_optimogo.breaker import CircuitBreaker


def test_closed_allows(clock):
    b = CircuitBreaker(failure_threshold=3, cooldown=30, time_func=clock)
    assert b.allow() is True


def test_opens_after_threshold(clock):
    b = CircuitBreaker(failure_threshold=3, cooldown=30, time_func=clock)
    for _ in range(3):
        b.record_failure()
    assert b.allow() is False        # open: blocks without an HTTP attempt


def test_probe_after_cooldown(clock):
    b = CircuitBreaker(failure_threshold=2, cooldown=30, time_func=clock)
    b.record_failure(); b.record_failure()
    assert b.allow() is False
    clock.advance(31)
    assert b.allow() is True          # one probe allowed
    assert b.allow() is False         # subsequent calls blocked until probe resolves


def test_success_closes(clock):
    b = CircuitBreaker(failure_threshold=2, cooldown=30, time_func=clock)
    b.record_failure(); b.record_failure()
    clock.advance(31)
    assert b.allow() is True
    b.record_success()
    assert b.allow() is True          # fully closed again
    assert b.allow() is True


def test_failed_probe_stays_open(clock):
    b = CircuitBreaker(failure_threshold=2, cooldown=30, time_func=clock)
    b.record_failure(); b.record_failure()
    clock.advance(31)
    assert b.allow() is True          # probe
    b.record_failure()                # probe failed
    assert b.allow() is False         # still open
    clock.advance(31)
    assert b.allow() is True          # next probe after another cooldown
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_breaker.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`wazo_dird_optimogo/breaker.py`:
```python
import threading
import time as _time


class CircuitBreaker:
    """A minimal per-source circuit breaker.

    Closed: allow() is always True. After `failure_threshold` consecutive
    failures it opens for `cooldown` seconds, during which allow() returns
    False (fail-open immediately, no HTTP). After the cooldown a single probe
    is permitted; success closes the breaker, failure restarts the cooldown.
    Shared across worker threads -> lock-guarded.
    """

    def __init__(self, failure_threshold, cooldown, time_func=_time.monotonic):
        self._threshold = failure_threshold
        self._cooldown = cooldown
        self._time = time_func
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = None

    def allow(self):
        with self._lock:
            if self._opened_at is None:
                return True
            if self._time() - self._opened_at >= self._cooldown:
                self._opened_at = self._time()   # arm the next cooldown; lets exactly one probe through
                return True
            return False

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold and self._opened_at is None:
                self._opened_at = self._time()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_breaker.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/breaker.py tests/test_breaker.py
git commit -m "feat: per-source circuit breaker"
```

---

## Task 8: HTTP client

**Files:**
- Create: `wazo_dird_optimogo/http_client.py`, `tests/test_http_client.py`

- [ ] **Step 1: Write the failing test**

`tests/test_http_client.py`:
```python
import json
import pytest
import responses
from wazo_dird_optimogo.http_client import OptimoGoClient
from wazo_dird_optimogo.exceptions import (
    OptimoGoAuthError, OptimoGoUnavailable, OptimoGoLookupError,
)

BASE = 'https://opt.example.com/api/wazo/dird/acme'


def make_client():
    return OptimoGoClient(base_url=BASE, api_key='secret-key',
                          connect_timeout=0.4, read_timeout=0.8, verify=True)


@responses.activate
def test_post_returns_parsed_json_and_sends_bearer():
    responses.add(responses.POST, f'{BASE}/reverse',
                  json={'match': None}, status=200,
                  content_type='application/json')
    body = make_client().post('/reverse', {'number': '+61399999999'})
    assert body == {'match': None}
    sent = responses.calls[0].request
    assert sent.headers['Authorization'] == 'Bearer secret-key'
    assert json.loads(sent.body) == {'number': '+61399999999'}


@responses.activate
@pytest.mark.parametrize('status', [401, 403])
def test_auth_errors(status):
    responses.add(responses.POST, f'{BASE}/reverse', status=status,
                  json={}, content_type='application/json')
    with pytest.raises(OptimoGoAuthError):
        make_client().post('/reverse', {'number': '1'})


@responses.activate
@pytest.mark.parametrize('status', [429, 500, 503])
def test_unavailable_errors(status):
    responses.add(responses.POST, f'{BASE}/reverse', status=status,
                  json={}, content_type='application/json')
    with pytest.raises(OptimoGoUnavailable):
        make_client().post('/reverse', {'number': '1'})


@responses.activate
@pytest.mark.parametrize('status', [400, 408, 409, 422])
def test_other_4xx_is_lookup_error(status):
    responses.add(responses.POST, f'{BASE}/reverse', status=status,
                  json={}, content_type='application/json')
    with pytest.raises(OptimoGoLookupError):
        make_client().post('/reverse', {'number': '1'})


@responses.activate
def test_wrong_content_type_is_lookup_error():
    responses.add(responses.POST, f'{BASE}/reverse', body='hello',
                  status=200, content_type='text/plain')
    with pytest.raises(OptimoGoLookupError):
        make_client().post('/reverse', {'number': '1'})


@responses.activate
def test_malformed_json_is_lookup_error():
    responses.add(responses.POST, f'{BASE}/reverse', body='{not json',
                  status=200, content_type='application/json')
    with pytest.raises(OptimoGoLookupError):
        make_client().post('/reverse', {'number': '1'})
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_http_client.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`wazo_dird_optimogo/http_client.py`:
```python
import json

import requests

from .exceptions import (
    OptimoGoAuthError, OptimoGoTimeout, OptimoGoUnavailable, OptimoGoLookupError,
)

_MAX_BODY_BYTES = 1 << 20  # 1 MiB cap on response bodies


class OptimoGoClient:
    """POSTs JSON to OptimoGo with bearer auth and a hard connect/read timeout.

    One pooled Session is created once and shared across threads; it is never
    mutated per-call, so concurrent use is safe. Raises typed exceptions only.
    """

    def __init__(self, base_url, api_key, connect_timeout, read_timeout,
                 verify, session=None):
        self._base = base_url.rstrip('/')
        self._timeout = (connect_timeout, read_timeout)
        self._verify = verify
        self._session = session or requests.Session()
        self._session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

    def post(self, path, payload):
        url = f'{self._base}{path}'
        try:
            resp = self._session.post(
                url, json=payload, timeout=self._timeout, verify=self._verify,
                allow_redirects=False, stream=True,
            )
        except requests.exceptions.Timeout as e:
            raise OptimoGoTimeout(str(e)) from e
        except requests.exceptions.RequestException as e:
            raise OptimoGoUnavailable(str(e)) from e
        return self._parse(resp)

    def _parse(self, resp):
        try:
            status = resp.status_code
            if status in (401, 403):
                raise OptimoGoAuthError(f'auth failed: HTTP {status}')
            if status == 429 or 500 <= status < 600:
                raise OptimoGoUnavailable(f'unavailable: HTTP {status}')
            if status != 200:
                raise OptimoGoLookupError(f'unexpected status: HTTP {status}')
            ctype = resp.headers.get('Content-Type', '')
            if 'application/json' not in ctype:
                raise OptimoGoLookupError(f'unexpected content-type: {ctype!r}')
            raw = resp.raw.read(_MAX_BODY_BYTES + 1, decode_content=True)
            if len(raw) > _MAX_BODY_BYTES:
                raise OptimoGoLookupError('response body too large')
            try:
                return json.loads(raw)
            except ValueError as e:
                raise OptimoGoLookupError(f'invalid json: {e}') from e
        finally:
            resp.close()

    def close(self):
        self._session.close()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_http_client.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/http_client.py tests/test_http_client.py
git commit -m "feat: OptimoGo HTTP client with typed errors and body cap"
```

---

## Task 9: JSON → column mapping

**Files:**
- Create: `wazo_dird_optimogo/mapping.py`, `tests/test_mapping.py`

- [ ] **Step 1: Write the failing test**

`tests/test_mapping.py`:
```python
from wazo_dird_optimogo.mapping import map_match, map_search_row, map_results

PREFIX = 'Maybe: '


def test_matched_maps_all_columns():
    match = {'name': 'Acme Plumbing', 'number': '+61399999999', 'customer_id': 123,
             'contact_name': 'John Smith', 'match_state': 'matched'}
    out = map_match(match, PREFIX)
    assert out == {
        'id': 'customer:123:number:+61399999999',
        'name': 'Acme Plumbing',
        'number': '+61399999999',
        'customer_id': 123,
        'contact_name': 'John Smith',
        'display_name': 'Acme Plumbing',
    }


def test_ambiguous_applies_prefix_once_from_raw_name():
    match = {'name': 'Acme Plumbing', 'display_name': 'Acme Plumbing',
             'number': '+61399999999', 'customer_id': 123,
             'match_state': 'ambiguous', 'candidate_count': 3}
    out = map_match(match, PREFIX)
    assert out['display_name'] == 'Maybe: Acme Plumbing'   # prefixed exactly once
    assert out['name'] == 'Acme Plumbing'


def test_none_match_returns_none():
    assert map_match(None, PREFIX) is None


def test_empty_strings_become_none():
    match = {'name': 'Acme', 'number': '+61', 'customer_id': 9,
             'contact_name': '  ', 'match_state': 'matched'}
    out = map_match(match, PREFIX)
    assert out['contact_name'] is None


def test_search_rows_mapped_with_per_number_id():
    rows = [
        {'name': 'Acme', 'number': '+61399999999', 'customer_id': 123, 'contact_name': None},
        {'name': 'John', 'number': '+61400000000', 'customer_id': 123,
         'contact_name': 'John', 'display_name': 'Acme — John'},
    ]
    out = map_results(rows)
    assert [r['id'] for r in out] == [
        'customer:123:number:+61399999999',
        'customer:123:number:+61400000000',
    ]
    assert out[1]['display_name'] == 'Acme — John'


def test_server_id_preserved_when_present():
    row = {'id': 'custom-id', 'name': 'Acme', 'number': '+61', 'customer_id': 1}
    assert map_search_row(row)['id'] == 'custom-id'
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_mapping.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`wazo_dird_optimogo/mapping.py`:
```python
def _none_if_empty(value):
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _canonical_id(customer_id, number):
    return f'customer:{customer_id}:number:{number}'


def _row_id(row, number):
    return _none_if_empty(row.get('id')) or _canonical_id(row.get('customer_id'), number)


def map_match(match, ambiguous_prefix):
    """Map a reverse 'match' object to a dird field dict, or None.

    The plugin owns the ambiguous prefix: when match_state == 'ambiguous' the
    display label is `ambiguous_prefix + name` (built from the raw name so the
    prefix is applied exactly once regardless of the server's display_name).
    """
    if not match:
        return None
    name = _none_if_empty(match.get('name'))
    number = _none_if_empty(match.get('number'))
    if match.get('match_state') == 'ambiguous' and name:
        display = f'{ambiguous_prefix}{name}'
    else:
        display = _none_if_empty(match.get('display_name')) or name
    return {
        'id': _row_id(match, number),
        'name': name,
        'number': number,
        'customer_id': match.get('customer_id'),
        'contact_name': _none_if_empty(match.get('contact_name')),
        'display_name': display,
    }


def map_search_row(row):
    name = _none_if_empty(row.get('name'))
    number = _none_if_empty(row.get('number'))
    return {
        'id': _row_id(row, number),
        'name': name,
        'number': number,
        'customer_id': row.get('customer_id'),
        'contact_name': _none_if_empty(row.get('contact_name')),
        'display_name': _none_if_empty(row.get('display_name')) or name,
    }


def map_results(rows):
    return [map_search_row(r) for r in rows]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_mapping.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/mapping.py tests/test_mapping.py
git commit -m "feat: map OptimoGo JSON to dird columns with ambiguous prefix"
```

---

## Task 10: Lookup engine (cache + breaker + client + mapping)

This is the core orchestration, with **no `wazo_dird` dependency** — fully testable on macOS. `plugin.py` (Task 11) is a thin SPI wrapper over it.

**Files:**
- Create: `wazo_dird_optimogo/engine.py`, `tests/test_engine.py`

- [ ] **Step 1: Write the failing test**

`tests/test_engine.py`:
```python
import pytest
from wazo_dird_optimogo.engine import LookupEngine
from wazo_dird_optimogo.exceptions import (
    OptimoGoAuthError, OptimoGoUnavailable, OptimoGoLookupError,
)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.responses = []          # list of (body | Exception)
    def post(self, path, payload):
        self.calls.append((path, payload))
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_engine(client, clock, **over):
    cfg = dict(cache_ttl=60, negative_cache_ttl=30, cache_max_entries=100,
               breaker_failure_threshold=2, breaker_cooldown=30,
               ambiguous_prefix='Maybe: ', search_min_term_length=3,
               search_max_term_length=64, search_limit=25)
    cfg.update(over)
    return LookupEngine(client=client, config=cfg, time_func=clock)


def test_reverse_match_then_cached(clock):
    client = FakeClient()
    # Two differently-formatted numbers normalize to DIFFERENT cache keys
    # ('+61399999999' keeps the '+', '0399999999' does not), so two HTTP calls
    # happen -> prime two responses. The third call (same formatting as the
    # first) is served from cache.
    match = {'match': {'name': 'Acme', 'number': '+61399999999',
                       'customer_id': 1, 'match_state': 'matched'}}
    client.responses = [match, match]
    eng = make_engine(client, clock)
    first = eng.reverse('+61 3 9999 9999')
    assert first['display_name'] == 'Acme'
    second = eng.reverse('0399999999')   # different formatting; separate key -> 2nd HTTP call
    client.responses = []                # no more responses available
    cached = eng.reverse('+61 3 9999 9999')
    assert cached == first
    assert len(client.calls) == 2        # first '+613...', then '0399...'; the 3rd was cached


def test_reverse_skips_anonymous_without_http(clock):
    client = FakeClient()
    eng = make_engine(client, clock)
    assert eng.reverse('anonymous') is None
    assert client.calls == []


def test_reverse_no_match_is_negative_cached(clock):
    client = FakeClient()
    client.responses = [{'match': None}]
    eng = make_engine(client, clock)
    assert eng.reverse('+61399999999') is None
    assert eng.reverse('+61399999999') is None   # served from negative cache
    assert len(client.calls) == 1


def test_reverse_ambiguous_prefixed(clock):
    client = FakeClient()
    client.responses = [{'match': {'name': 'Acme', 'number': '+61', 'customer_id': 1,
                                   'match_state': 'ambiguous', 'candidate_count': 3}}]
    eng = make_engine(client, clock)
    assert eng.reverse('+61')['display_name'] == 'Maybe: Acme'


def test_auth_error_fails_open_no_breaker(clock):
    client = FakeClient()
    client.responses = [OptimoGoAuthError('401'), OptimoGoAuthError('401'),
                        OptimoGoAuthError('401')]
    eng = make_engine(client, clock)
    for _ in range(3):
        assert eng.reverse('+61399999999') is None
    assert len(client.calls) == 3        # breaker never opened on auth errors


def test_unavailable_opens_breaker(clock):
    client = FakeClient()
    client.responses = [OptimoGoUnavailable('503'), OptimoGoUnavailable('503')]
    eng = make_engine(client, clock)
    assert eng.reverse('+61399999999') is None
    assert eng.reverse('+61399999990') is None   # 2nd failure -> opens breaker
    # 3rd call: breaker open -> no HTTP attempt
    assert eng.reverse('+61399999991') is None
    assert len(client.calls) == 2


def test_breaker_probe_recovers(clock):
    client = FakeClient()
    client.responses = [OptimoGoUnavailable('503'), OptimoGoUnavailable('503'),
                        {'match': {'name': 'Acme', 'number': '+61', 'customer_id': 1,
                                   'match_state': 'matched'}}]
    eng = make_engine(client, clock)
    eng.reverse('+61399999999'); eng.reverse('+61399999990')   # opens breaker
    clock.advance(31)
    assert eng.reverse('+61399999991')['name'] == 'Acme'        # probe succeeds
    assert eng.reverse('+61399999991')['name'] == 'Acme'        # now cached/closed


def test_lookup_error_feeds_breaker(clock):
    client = FakeClient()
    client.responses = [OptimoGoLookupError('bad'), OptimoGoLookupError('bad')]
    eng = make_engine(client, clock)
    eng.reverse('+61399999999'); eng.reverse('+61399999990')
    assert eng.reverse('+61399999991') is None
    assert len(client.calls) == 2        # breaker opened after 2 malformed responses


def test_search_term_too_short_skips_http(clock):
    client = FakeClient()
    eng = make_engine(client, clock)
    assert eng.search('ab') == []
    assert client.calls == []


def test_search_returns_rows_and_caches(clock):
    client = FakeClient()
    client.responses = [{'results': [
        {'name': 'Acme', 'number': '+61399999999', 'customer_id': 1, 'contact_name': None}]}]
    eng = make_engine(client, clock)
    rows = eng.search('acme')
    assert rows[0]['id'] == 'customer:1:number:+61399999999'
    eng.search('ACME')                   # normalized to same key -> cached
    assert len(client.calls) == 1


def test_match_all_one_batch_call(clock):
    client = FakeClient()
    client.responses = [{'matches': {
        '+61399999999': {'name': 'Acme', 'number': '+61399999999', 'customer_id': 1,
                         'match_state': 'matched'},
        '+61400000000': None}}]
    eng = make_engine(client, clock)
    out = eng.match_all(['+61399999999', '+61400000000', 'anonymous'])
    assert set(out.keys()) == {'+61399999999'}        # unmatched + skipped omitted
    assert out['+61399999999']['name'] == 'Acme'
    assert client.calls[0][0] == '/reverse/batch'
    assert len(client.calls) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/test_engine.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

`wazo_dird_optimogo/engine.py`:
```python
import logging

from .breaker import CircuitBreaker
from .cache import TTLCache
from .exceptions import OptimoGoAuthError, OptimoGoError
from .inputs import (
    normalize_number_key, normalize_term_key, should_skip_number, validate_term,
)
from .mapping import map_match, map_results

logger = logging.getLogger(__name__)


class LookupEngine:
    """Bounded fail-open lookups: cache -> breaker -> HTTP -> mapping.

    Returns plain field dicts (or None / []); the SPI layer wraps them into
    wazo-dird result objects. No wazo_dird import here.
    """

    def __init__(self, client, config, time_func=None):
        self._client = client
        self._cfg = config
        kw = {} if time_func is None else {'time_func': time_func}
        self._cache = TTLCache(max_entries=config['cache_max_entries'], **kw)
        self._breaker = CircuitBreaker(
            failure_threshold=config['breaker_failure_threshold'],
            cooldown=config['breaker_cooldown'], **kw)

    # ---- reverse (caller ID) -------------------------------------------------
    def reverse(self, number):
        if should_skip_number(number):
            return None
        key = ('reverse', normalize_number_key(number))
        hit, value = self._cache.get(key)
        if hit:
            return value
        body = self._request('/reverse', {'number': number})
        if body is _FAILED:
            return None
        match = body.get('match') if isinstance(body, dict) else None
        fields = map_match(match, self._cfg['ambiguous_prefix'])
        ttl = self._cfg['cache_ttl'] if fields else self._cfg['negative_cache_ttl']
        self._cache.set(key, fields, ttl)
        return fields

    # ---- forward search ------------------------------------------------------
    def search(self, term):
        clean = validate_term(term, self._cfg['search_min_term_length'],
                              self._cfg['search_max_term_length'])
        if clean is None:
            return []
        key = ('search', normalize_term_key(clean), self._cfg['search_limit'])
        hit, value = self._cache.get(key)
        if hit:
            return value
        body = self._request('/search', {'term': clean, 'limit': self._cfg['search_limit']})
        if body is _FAILED:
            return []
        rows = body.get('results') if isinstance(body, dict) else None
        results = map_results(rows or [])
        ttl = self._cfg['cache_ttl'] if results else self._cfg['negative_cache_ttl']
        self._cache.set(key, results, ttl)
        return results

    # ---- batch reverse -------------------------------------------------------
    def match_all(self, numbers):
        wanted = [n for n in numbers if not should_skip_number(n)]
        if not wanted:
            return {}
        body = self._request('/reverse/batch', {'numbers': wanted})
        if body is _FAILED:
            return {}
        matches = body.get('matches') if isinstance(body, dict) else None
        out = {}
        for number, match in (matches or {}).items():
            fields = map_match(match, self._cfg['ambiguous_prefix'])
            if fields:
                out[number] = fields
        return out

    # ---- shared request path -------------------------------------------------
    def _request(self, path, payload):
        if not self._breaker.allow():
            return _FAILED
        try:
            body = self._client.post(path, payload)
        except OptimoGoAuthError:
            logger.error('optimogo auth failed on %s (check the source api_key)', path)
            return _FAILED                       # no breaker, no cache
        except OptimoGoError as e:
            self._breaker.record_failure()
            logger.warning('optimogo lookup failed on %s: %s', path, type(e).__name__)
            return _FAILED                       # breaker fed, no cache
        self._breaker.record_success()
        return body

    def close(self):
        close = getattr(self._client, 'close', None)
        if close:
            close()


_FAILED = object()   # sentinel: request failed (distinct from a valid empty body)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/pytest tests/test_engine.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/engine.py tests/test_engine.py
git commit -m "feat: bounded fail-open lookup engine (cache+breaker+mapping)"
```

---

## Task 11: SPI plugin glue (`plugin.py`) — runs in the container

**Files:**
- Create: `wazo_dird_optimogo/plugin.py`, `tests/test_plugin.py`

- [ ] **Step 1: Write the failing test** (marked `needs_dird`)

`tests/test_plugin.py`:
```python
import pytest

pytest.importorskip('wazo_dird')           # only runs where wazo_dird is installed

from wazo_dird_optimogo.plugin import OptimoGoSourcePlugin


class _FakeEngine:
    def __init__(self):
        self.reverse_result = None
        self.search_result = []
        self.match_all_result = {}
    def reverse(self, number):
        return self.reverse_result
    def search(self, term):
        return self.search_result
    def match_all(self, numbers):
        return self.match_all_result
    def close(self):
        pass


def _loaded_plugin(engine):
    p = OptimoGoSourcePlugin()
    p.load({'config': {
        'name': 'optimogo',
        'lookup_url': 'https://opt.example.com/api/wazo/dird/acme',
        'api_key': 'secret-key',
    }})
    p._engine = engine        # swap in a fake after load wires the real one
    return p


@pytest.mark.needs_dird
def test_first_match_wraps_result_dict():
    eng = _FakeEngine()
    eng.reverse_result = {'id': 'customer:1:number:+61', 'name': 'Acme', 'number': '+61',
                          'customer_id': 1, 'contact_name': None, 'display_name': 'Acme'}
    p = _loaded_plugin(eng)
    result = p.first_match('+61')
    assert result is not None
    assert result.fields['display_name'] == 'Acme'


@pytest.mark.needs_dird
def test_first_match_none_returns_none():
    p = _loaded_plugin(_FakeEngine())     # reverse_result defaults to None
    assert p.first_match('+61') is None


@pytest.mark.needs_dird
def test_list_returns_empty():
    p = _loaded_plugin(_FakeEngine())
    assert p.list(['x'], None) == []


@pytest.mark.needs_dird
def test_safety_catch_swallows_unexpected_errors():
    class Boom(_FakeEngine):
        def reverse(self, number):
            raise RuntimeError('unexpected')
    p = _loaded_plugin(Boom())
    assert p.first_match('+61') is None    # must NOT propagate into the dialplan


@pytest.mark.needs_dird
def test_search_wraps_rows():
    eng = _FakeEngine()
    eng.search_result = [{'id': 'customer:1:number:+61', 'name': 'Acme', 'number': '+61',
                          'customer_id': 1, 'contact_name': None, 'display_name': 'Acme'}]
    p = _loaded_plugin(eng)
    rows = p.search('acme')
    assert len(rows) == 1
    assert rows[0].fields['name'] == 'Acme'
```

> Note on `result.fields`: wazo-dird's result objects (from `make_result_class`) expose the source fields. Confirm the exact attribute name (`.fields`) against the pinned version in Task 2 Step 2; adjust these assertions if it differs.

- [ ] **Step 2: Run to verify it fails (in the container)**

Run:
```bash
docker build -f Dockerfile.dev -t wazo-dird-optimogo-dev .
docker run --rm wazo-dird-optimogo-dev pytest tests/test_plugin.py -v
```
Expected: FAIL — `cannot import name 'OptimoGoSourcePlugin'`.

- [ ] **Step 3: Implement**

`wazo_dird_optimogo/plugin.py`:
```python
import logging

from wazo_dird import BaseSourcePlugin, make_result_class

from .engine import LookupEngine
from .http_client import OptimoGoClient
from .schema import load_config

logger = logging.getLogger(__name__)


class OptimoGoSourcePlugin(BaseSourcePlugin):
    """wazo-dird source backend resolving caller IDs/searches against OptimoGo.

    Each dird-facing method wraps an explicit outermost safety-catch: an
    unforeseen error (mapping, cache, result-class) must never propagate into
    the dialplan. Typed HTTP errors are already handled in the engine.
    """

    def load(self, args):
        cfg = load_config(args['config'])
        self.name = cfg['name']
        self.backend = args['config'].get('backend', 'optimogo')
        verify = cfg['verify_certificate']
        if verify is False:
            logger.warning('optimogo source %s has verify_certificate=False '
                           '(emergency diagnostics only)', self.name)
        if not str(cfg['lookup_url']).startswith('https://'):
            logger.warning('optimogo source %s lookup_url is not https', self.name)
        client = OptimoGoClient(
            base_url=cfg['lookup_url'], api_key=cfg['api_key'],
            connect_timeout=cfg['connect_timeout'], read_timeout=cfg['read_timeout'],
            verify=verify)
        self._engine = LookupEngine(client=client, config=cfg)
        self._result_class = make_result_class(
            self.backend, self.name, cfg['unique_column'], cfg['format_columns'])

    def first_match(self, exten, args=None):
        try:
            fields = self._engine.reverse(exten)
            return self._result_class(fields) if fields else None
        except Exception:
            logger.exception('optimogo first_match failed (returning None)')
            return None

    def match_all(self, extens, args=None):
        try:
            return {number: self._result_class(fields)
                    for number, fields in self._engine.match_all(extens).items()}
        except Exception:
            logger.exception('optimogo match_all failed (returning {})')
            return {}

    def search(self, term, args=None):
        try:
            return [self._result_class(fields) for fields in self._engine.search(term)]
        except Exception:
            logger.exception('optimogo search failed (returning [])')
            return []

    def list(self, uids, args=None):
        return []          # favorites unsupported by this source

    def unload(self):
        engine = getattr(self, '_engine', None)
        if engine:
            engine.close()
```

> If Task 2 Step 2 showed `make_result_class` builds an instance differently (e.g. `make_result_class(...)(**fields)` vs `(fields)`), adjust the calls here and the `_FakeEngine`-based assertions accordingly.

- [ ] **Step 4: Run to verify it passes (in the container)**

Run: `docker run --rm wazo-dird-optimogo-dev pytest tests/test_plugin.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add wazo_dird_optimogo/plugin.py tests/test_plugin.py
git commit -m "feat: OptimoGoSourcePlugin SPI glue with outermost safety-catch"
```

---

## Task 12: Entry-point smoke test — runs in the container

**Files:**
- Create: `tests/test_entry_point.py`

- [ ] **Step 1: Write the failing test**

`tests/test_entry_point.py`:
```python
import pytest

pytest.importorskip('wazo_dird')


@pytest.mark.needs_dird
def test_entry_point_resolves_to_plugin_class():
    from importlib.metadata import entry_points
    eps = entry_points(group='wazo_dird.backends')
    optimogo = {ep.name: ep for ep in eps}.get('optimogo')
    assert optimogo is not None, 'optimogo backend entry point not registered'
    cls = optimogo.load()
    from wazo_dird_optimogo.plugin import OptimoGoSourcePlugin
    assert cls is OptimoGoSourcePlugin
```

- [ ] **Step 2: Run to verify it fails (before reinstall, if entry point absent)**

Run: `docker run --rm wazo-dird-optimogo-dev pytest tests/test_entry_point.py -v`
Expected: PASS if `pip install -e .` registered the entry point (Dockerfile.dev does). If it FAILS with "not registered", rebuild the image so `setup.py`'s entry point is picked up.

- [ ] **Step 3: No new implementation** — the entry point is defined in `setup.py` (Task 1). This task verifies it resolves under a real `wazo_dird` environment.

- [ ] **Step 4: Run the full container suite**

Run: `docker run --rm wazo-dird-optimogo-dev pytest -v`
Expected: every test passes (macOS-core tests + `needs_dird` tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_entry_point.py
git commit -m "test: entry-point smoke test under real wazo_dird"
```

---

## Task 13: wazo-plugind packaging

**Files:**
- Create: `wazo/plugin.yml`, `wazo/Makefile`

- [ ] **Step 1: Confirm the wazo-plugind packaging format for the deployed version**

Run on the PBX (or read the docs for the pinned Wazo release):
```bash
wazo-plugind-cli --help 2>/dev/null || true
ls /var/lib/wazo-plugind/plugins/*/wazo/plugin.yml 2>/dev/null | head -1 | xargs cat 2>/dev/null
```
Confirm the `plugin.yml` schema (fields, `build`/`install` hook names) for an installed example plugin, since this format is version-sensitive.

- [ ] **Step 2: Write the plugind manifest**

`wazo/plugin.yml`:
```yaml
name: wazo-dird-optimogo
namespace: optimo
version: '1.0.0'
display_name: OptimoGo dird lookup
description: >
  wazo-dird source backend that resolves caller IDs (reverse) and directory
  searches (forward) against a tenant's OptimoGo JSON endpoint.
author: Optimo Group
license: proprietary
debian_depends:
  - wazo-dird
```

`wazo/Makefile`:
```makefile
build:
	true

package:
	mkdir -p ${DESTDIR}/opt/wazo-dird-optimogo
	cp -a wazo_dird_optimogo setup.py ${DESTDIR}/opt/wazo-dird-optimogo/

install:
	pip3 install --no-index --no-build-isolation /opt/wazo-dird-optimogo || \
	pip3 install /opt/wazo-dird-optimogo
	systemctl restart wazo-dird

uninstall:
	pip3 uninstall -y wazo-dird-optimogo || true
	systemctl restart wazo-dird
```

> The exact `plugin.yml` keys and `Makefile` target names must match the pinned wazo-plugind version (Step 1). Treat this as the best-effort template to reconcile against the live `wazo-plugind`.

- [ ] **Step 3: Validate the manifest parses**

Run:
```bash
.venv/bin/python -c "import yaml; print(yaml.safe_load(open('wazo/plugin.yml'))['name'])"
```
Expected: `wazo-dird-optimogo`. (Add `pyyaml` to `requirements-dev.txt` if not present.)

- [ ] **Step 4: Document the install validation (manual, on a staging PBX)**

Record in `docs/INSTALL.md` (created in Task 14) the manual install check: install the plugin via `wazo-plugind`, then run the §10/Task-2 SPI import check inside the running `wazo-dird` to confirm the backend loaded, with a **post-install health check** (`systemctl is-active wazo-dird` + the entry-point resolves) and **rollback** (uninstall) on failure.

- [ ] **Step 5: Commit**

```bash
git add wazo/plugin.yml wazo/Makefile
git commit -m "build: wazo-plugind packaging manifest and rules"
```

---

## Task 14: Provisioning & install docs

**Files:**
- Create: `docs/INSTALL.md`

- [ ] **Step 1: Write the install/provisioning doc**

`docs/INSTALL.md`:
```markdown
# Installing the OptimoGo dird backend

## 1. Install the plugin (per PBX)
Install via the Wazo plugin admin or:
    wazo-plugind-cli -c "install git <repo-url>"
This pip-installs `wazo-dird-optimogo` and restarts `wazo-dird`.

### Post-install health check (and rollback)
    systemctl is-active wazo-dird           # must be 'active'
    python3 -c "from importlib.metadata import entry_points as e; \
      print('optimogo' in {x.name for x in e(group='wazo_dird.backends')})"   # must be True
If either fails, uninstall to roll back:
    wazo-plugind-cli -c "uninstall optimo/wazo-dird-optimogo"

## 2. Create the source (per tenant)
POST to wazo-dird with the tenant's config and `Wazo-Tenant` header:
    POST /api/dird/0.1/backends/optimogo/sources
    {
      "name": "optimogo",
      "lookup_url": "https://<optimogo-host>/api/wazo/dird/<tenant_schema>",
      "api_key": "<per-tenant-bearer-key>"
    }
Optional keys (defaults in the spec §3.3): connect_timeout, read_timeout,
cache_ttl, negative_cache_ttl, breaker_failure_threshold, breaker_cooldown,
ambiguous_prefix, search_min_term_length, search_max_term_length, search_limit,
verify_certificate.

## 3. Bind the source to profiles
- Add `optimogo` to the tenant's **reverse** profile (handset caller ID) and a
  **lookup** profile (directory search) via the dird profiles API.
- Confirm the reverse profile's **display** maps `display_name` to the handset
  name field.

## 4. Teardown order (uninstall / disconnect)
1. Unbind `optimogo` from all profiles (reverse + lookup).
2. Delete the source (`DELETE /api/dird/0.1/backends/optimogo/sources/<uuid>`) —
   this removes the stored api_key.
3. Uninstall the plugin.

## Key rotation (no-outage)
Rotate on OptimoGo first (it accepts current + previous key), then update the
source `api_key` via the sources API. Repeated 401/403 is logged by the plugin
at ERROR and alerted OptimoGo-side.
```

- [ ] **Step 2: Commit**

```bash
git add docs/INSTALL.md
git commit -m "docs: plugin install, provisioning, rotation and teardown"
```

---

## Task 15: README & final full-suite run

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

`README.md`:
```markdown
# wazo-dird-optimogo

A wazo-dird source backend (`optimogo`) that resolves caller IDs (reverse) and
directory searches (forward) against a tenant's OptimoGo JSON HTTP endpoint.

- Design: `docs/superpowers/specs/2026-06-16-wazo-dird-optimogo-lookup-design.md`
- Install: `docs/INSTALL.md`

## Development
Pure-Python core (no wazo_dird) runs on any host:
    python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest -m "not needs_dird"

SPI + entry-point tests need a pinned wazo-dird (container):
    docker build -f Dockerfile.dev -t wazo-dird-optimogo-dev .
    docker run --rm wazo-dird-optimogo-dev pytest -v
```

- [ ] **Step 2: Run the macOS-core suite**

Run: `.venv/bin/pytest -m "not needs_dird" -v`
Expected: all core tests pass (exceptions, schema, inputs, cache, breaker, http_client, mapping, engine).

- [ ] **Step 3: Run the full container suite**

Run: `docker run --rm wazo-dird-optimogo-dev pytest -v`
Expected: all tests pass, including `needs_dird`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: project README and dev/test instructions"
```

---

## Self-review checklist (completed during planning)

**Spec coverage:**
- §3.1 package layout → Tasks 1, 3–11. §3.2 SPI methods + safety-catch → Task 11. §3.3 config schema → Task 4. §3.4 canonical columns/row id → Task 9 (`_canonical_id`), Task 11 (`unique_column`). §4.2/4.3 reverse/batch/search request shapes → Task 8 (client), Task 10 (engine). §4.4 status→fail-open → Task 8 (mapping to typed errors) + Task 10 (breaker/cache policy). §4.1 auth/bearer → Task 8; rotation/teardown → Task 14. §5 data flow → Task 10. §6 cache+breaker+thread-safety → Tasks 6, 7, 10. §7 error handling/redaction → Tasks 8, 10, 11 (no PII in logs). §8 packaging/provisioning/upgrade safety → Tasks 13, 14. §9 testing → every task's tests + Task 2 SPI confirm. §10 version pinning → Task 2. Input normalization → Task 5.
- **Not in this plan (by design):** the OptimoGo-side endpoint (separate `optimogo-site` work — spec §4 is the contract); live integration against the real endpoint (manual, post-install per Task 14).

**Placeholder scan:** the only environment-derived blanks (`<WAZO_DIRD_VERSION>`, `<DEBIAN_CODENAME>`, `<WAZO_APT_REPO_LINE>`) are produced by Task 2's explicit commands before any code depends on them — not lazy TODOs.

**Type consistency:** `LookupEngine.reverse/search/match_all` return field dicts / lists / `{number: dict}`; `plugin.py` wraps each via `self._result_class(...)`. `map_match` returns the 6-column dict consumed unchanged by both engine and the result class. `TTLCache.get` → `(bool, value)` used identically in engine. `CircuitBreaker.allow/record_success/record_failure` used consistently. The `_FAILED` sentinel distinguishes request failure from a valid empty body throughout the engine.
