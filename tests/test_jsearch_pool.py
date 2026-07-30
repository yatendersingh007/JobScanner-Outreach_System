"""src/jsearch_pool.py: JSearch key-pool rotation, installed by monkeypatching
requests.get inside scanner.connectors.adapters.jsearch's own module
namespace only (never the shared requests module -- see the module
docstring for why that matters for scanner/connectors/tinyfish.py's own,
unrelated requests.get calls).

Hard constraint under test in its own right: scanner/, lib_referral/, and
lib_snapshot/ are vendored and must never be edited by anything in this
change -- the final test in this file asserts `git status --porcelain`
against those three paths is empty.

No real network: the real requests.get is monkeypatched with a canned
sequence of fake responses.
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

from lib_snapshot.researcher.search_client import _KeyPool
from scanner.connectors.adapters import jsearch as jsearch_module
from src import jsearch_pool


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _fake_get_sequence(statuses):
    """A fake requests.get(...) yielding responses with the given status
    codes in call order (the last status repeats if called more times than
    the list has entries). Records every call's url/params/headers."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        calls.append({"url": url, "params": params, "headers": dict(headers or {}),
                      "timeout": timeout})
        idx = len(calls) - 1
        status = statuses[idx] if idx < len(statuses) else statuses[-1]
        return _FakeResponse(status)

    fake_get.calls = calls
    return fake_get


@pytest.fixture(autouse=True)
def _isolate_pool_and_install_state(monkeypatch):
    """jsearch_pool._pool and _installed are module-level singletons, and
    install() mutates scanner.connectors.adapters.jsearch's own `requests`
    binding -- all real, deliberate global state (that's the whole
    mechanism), so every test gets a clean slate and the real jsearch
    module is restored afterward regardless of what a test did to it."""
    real_requests_ref = jsearch_module.requests
    monkeypatch.setattr(jsearch_pool, "_installed", False)
    yield
    jsearch_module.requests = real_requests_ref
    monkeypatch.setattr(jsearch_pool, "_installed", False)


def _set_pool(monkeypatch, keys):
    monkeypatch.setattr(jsearch_pool, "_pool", _KeyPool(keys))


# ---------------------------------------------------------------------------
# _load_keys: JSEARCH_API_KEYS with fallback to JSEARCH_API_KEY
# ---------------------------------------------------------------------------
def test_single_key_fallback_via_JSEARCH_API_KEY_only(monkeypatch):
    monkeypatch.delenv("JSEARCH_API_KEYS", raising=False)
    monkeypatch.setenv("JSEARCH_API_KEY", "solo-key")

    assert jsearch_pool._load_keys() == ["solo-key"]


def test_JSEARCH_API_KEYS_takes_priority_and_splits_on_comma(monkeypatch):
    monkeypatch.setenv("JSEARCH_API_KEYS", "key-a, key-b ,key-c")
    monkeypatch.setenv("JSEARCH_API_KEY", "should-be-ignored")

    assert jsearch_pool._load_keys() == ["key-a", "key-b", "key-c"]


def test_no_keys_configured_at_all_returns_empty_list(monkeypatch):
    monkeypatch.delenv("JSEARCH_API_KEYS", raising=False)
    monkeypatch.delenv("JSEARCH_API_KEY", raising=False)

    assert jsearch_pool._load_keys() == []


# ---------------------------------------------------------------------------
# _PooledRequests.get: rotation mechanics
# ---------------------------------------------------------------------------
def test_rotation_on_429_then_success_on_key_2(monkeypatch):
    _set_pool(monkeypatch, ["key-1", "key-2"])
    fake_get = _fake_get_sequence([429, 200])
    monkeypatch.setattr(jsearch_pool, "_real_requests",
                        types.SimpleNamespace(get=fake_get))

    pooled = jsearch_pool._PooledRequests()
    r = pooled.get("https://jsearch.p.rapidapi.com/search-v2",
                   params={"query": "fund accountant"}, headers={}, timeout=30)

    assert r.status_code == 200
    assert len(fake_get.calls) == 2
    assert fake_get.calls[0]["headers"]["X-RapidAPI-Key"] == "key-1"
    assert fake_get.calls[1]["headers"]["X-RapidAPI-Key"] == "key-2"


def test_all_keys_exhausted_returns_the_429(monkeypatch):
    _set_pool(monkeypatch, ["key-1", "key-2"])
    fake_get = _fake_get_sequence([429, 429])
    monkeypatch.setattr(jsearch_pool, "_real_requests",
                        types.SimpleNamespace(get=fake_get))

    pooled = jsearch_pool._PooledRequests()
    r = pooled.get("https://jsearch.p.rapidapi.com/search-v2",
                   params={"query": "fund accountant"}, headers={}, timeout=30)

    assert r.status_code == 429
    assert len(fake_get.calls) == 2  # one per key, never a third call
    assert fake_get.calls[0]["headers"]["X-RapidAPI-Key"] == "key-1"
    assert fake_get.calls[1]["headers"]["X-RapidAPI-Key"] == "key-2"


def test_non_429_passthrough_makes_exactly_one_call(monkeypatch):
    _set_pool(monkeypatch, ["key-1", "key-2", "key-3"])
    fake_get = _fake_get_sequence([200])
    monkeypatch.setattr(jsearch_pool, "_real_requests",
                        types.SimpleNamespace(get=fake_get))

    pooled = jsearch_pool._PooledRequests()
    r = pooled.get("https://jsearch.p.rapidapi.com/search-v2",
                   params={"query": "controller"}, headers={}, timeout=30)

    assert r.status_code == 200
    assert len(fake_get.calls) == 1
    assert fake_get.calls[0]["headers"]["X-RapidAPI-Key"] == "key-1"


def test_single_key_pool_returns_429_immediately_after_one_call(monkeypatch):
    """A one-key pool has nowhere to advance to -- advance() returns False
    on the first 429, so the 429 comes back after exactly one call."""
    _set_pool(monkeypatch, ["only-key"])
    fake_get = _fake_get_sequence([429])
    monkeypatch.setattr(jsearch_pool, "_real_requests",
                        types.SimpleNamespace(get=fake_get))

    pooled = jsearch_pool._PooledRequests()
    r = pooled.get("https://jsearch.p.rapidapi.com/search-v2",
                   params={"query": "controller"}, headers={}, timeout=30)

    assert r.status_code == 429
    assert len(fake_get.calls) == 1


def test_no_keys_at_all_passes_through_unmodified(monkeypatch):
    """Defensive fallback: an empty pool never rewrites headers or retries,
    it just calls straight through (the real adapter already self-skips
    before ever reaching here when it has no key)."""
    _set_pool(monkeypatch, [])
    fake_get = _fake_get_sequence([200])
    monkeypatch.setattr(jsearch_pool, "_real_requests",
                        types.SimpleNamespace(get=fake_get))

    pooled = jsearch_pool._PooledRequests()
    r = pooled.get("https://jsearch.p.rapidapi.com/search-v2",
                   params={"query": "controller"}, headers={"X-RapidAPI-Key": "untouched"},
                   timeout=30)

    assert r.status_code == 200
    assert len(fake_get.calls) == 1
    assert fake_get.calls[0]["headers"] == {"X-RapidAPI-Key": "untouched"}


def test_getattr_forwards_to_the_real_requests_module():
    pooled = jsearch_pool._PooledRequests()
    import requests
    assert pooled.exceptions is requests.exceptions


# ---------------------------------------------------------------------------
# install(): idempotent, scoped to jsearch's own module namespace
# ---------------------------------------------------------------------------
def test_install_wraps_jsearch_modules_requests_reference():
    original = jsearch_module.requests
    jsearch_pool.install()

    assert jsearch_module.requests is not original
    assert isinstance(jsearch_module.requests, jsearch_pool._PooledRequests)


def test_install_twice_does_not_double_wrap():
    jsearch_pool.install()
    first = jsearch_module.requests
    jsearch_pool.install()
    second = jsearch_module.requests

    assert first is second  # the same proxy instance, not re-wrapped


def test_install_does_not_touch_the_global_requests_module():
    """The mechanism is scoped to jsearch's own namespace -- the shared
    `requests` module other connectors (e.g. TinyFish) import must be
    completely unaffected."""
    import requests
    real_get = requests.get

    jsearch_pool.install()

    assert requests.get is real_get
    assert not isinstance(requests, jsearch_pool._PooledRequests)


# ---------------------------------------------------------------------------
# Hard constraint: this change must never touch vendored CODE.
# ---------------------------------------------------------------------------
def test_no_vendored_python_file_is_dirty():
    """Scoped to .py files specifically, not every path under these three
    roots: scanner/config.yaml is a tunable operational config (no
    "VENDORED - DO NOT EDIT IN PLACE" header, unlike every .py file under
    these roots) that gets edited directly and often as part of normal
    operation, independent of any code change -- asserting it must always
    be git-clean would make this test fail on unrelated, expected,
    intentional operator tuning rather than on the thing this constraint
    actually protects: nobody, including this change, editing the vendored
    source itself."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", "scanner/", "lib_referral/", "lib_snapshot/"],
        cwd=repo_root, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    dirty_python_files = [line for line in result.stdout.splitlines()
                          if line.strip().endswith(".py")]
    assert dirty_python_files == [], (
        "vendored Python file(s) dirty, must stay clean:\n" + "\n".join(dirty_python_files)
    )
