"""JSearch (RapidAPI) key-pool rotation for the scanner's aggregator
connector. NOT vendored -- scanner/connectors/adapters/jsearch.py must stay
byte-identical to the donor; this module reaches in from the OUTSIDE and
monkeypatches only what that module's own namespace exposes. `git status
--porcelain -- scanner/ lib_referral/ lib_snapshot/` must stay empty.

Mirrors lib_snapshot/researcher/search_client.py's _KeyPool
(current/advance/position/size/reset) by importing it directly, not
reimplementing it -- that module's own docstring already frames _KeyPool as
generic ("no Tavily-specific code") and built for another provider to
adopt. Same for _query_hash's hashed-query logging convention.

Mechanism: install() replaces the NAME `requests` inside
scanner.connectors.adapters.jsearch's own module dict with a proxy object
whose .get() rotates keys on HTTP 429 and forwards every other attribute
unchanged to the real requests module. Deliberately narrower than
monkeypatching the shared `requests` module's own .get attribute:
scanner/connectors/tinyfish.py ALSO calls requests.get, for its own,
unrelated polling loop, and a global patch would silently route its calls
through JSearch's key-rotation and header-rewriting too.
"""
from __future__ import annotations

import os
import sys

import requests as _real_requests

from lib_snapshot.researcher.search_client import _KeyPool, _query_hash

HEADER = "X-RapidAPI-Key"


def _load_keys() -> list[str]:
    raw = os.getenv("JSEARCH_API_KEYS", "").strip()
    if raw:
        return [k.strip() for k in raw.split(",") if k.strip()]
    single = os.getenv("JSEARCH_API_KEY", "").strip()
    return [single] if single else []


_pool = _KeyPool(_load_keys())


def reload_keys() -> None:
    """Mirrors search_client.reload_keys(): re-read .env-sourced keys into
    a fresh pool, starting back at key 1."""
    _pool.reset(_load_keys())


def pool_size() -> int:
    return _pool.size()


def _log(msg: str) -> None:
    print(f"[jsearch-pool] {msg}", file=sys.stderr, flush=True)


class _PooledRequests:
    """Stands in for the `requests` module inside jsearch.py's own
    namespace only. Every attribute other than get() forwards unchanged to
    the real requests module, so installing this can never affect any
    other module's own `import requests`."""

    def __getattr__(self, name):
        return getattr(_real_requests, name)

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        if not _pool.current():
            # No JSearch key configured at all -- behave exactly like the
            # real requests.get. The adapter itself already self-skips
            # without a key before ever reaching here; this is a
            # defensive fallback, not the expected path.
            return _real_requests.get(url, params=params, headers=headers,
                                      timeout=timeout, **kwargs)

        headers = dict(headers or {})
        qhash = _query_hash((params or {}).get("query", url))
        while True:
            idx, total = _pool.position()
            headers[HEADER] = _pool.current()
            r = _real_requests.get(url, params=params, headers=headers,
                                   timeout=timeout, **kwargs)
            _log(f"key {idx}/{total} query={qhash} status={r.status_code}")
            if r.status_code != 429:
                return r
            # This key is exhausted for the run: advance() moves past it
            # permanently (until reload_keys()), mirroring _post's own
            # "never revisit an exhausted key" behavior in search_client.py.
            if not _pool.advance():
                return r  # every key exhausted -- return the 429 as-is
            # loop retries the SAME request with the new current key


_installed = False


def install() -> None:
    """Monkeypatches requests.get inside
    scanner.connectors.adapters.jsearch's own module namespace. Idempotent
    -- a second call is a no-op, so callers never need to track whether
    they already installed it."""
    global _installed
    if _installed:
        return
    from scanner.connectors.adapters import jsearch as _jsearch_module
    _jsearch_module.requests = _PooledRequests()
    _installed = True
