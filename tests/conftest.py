"""Repo-wide test fixtures.

Run 27 fix: tests/test_run_lock.py called run_single_firm()/run_resume()
without overriding their module-level default of progress=tg.progress -- a
REAL Telegram sender (src/wd_telegram.py). This environment's own .env
carries live TELEGRAM_BOT_TOKEN_D/TELEGRAM_CHAT_ID values (needed for real
runs), so every pytest run that reached one of those code paths posted an
actual message to the operator's bot. The individual call sites are now
fixed to pass an explicit no-op progress (see test_run_lock.py), but that
only covers the leaks found today -- this fixture is the general backstop
against any future one.

wd_telegram.send()/_send_and_get_id()/_edit() each wrap their requests.post
call in a bare `except Exception`, so a plain raise from a monkeypatched
requests.post would be silently swallowed and logged as a warning, not fail
the test. pytest.fail() raises pytest's own Failed, which subclasses
BaseException (not Exception) specifically so it survives a bare except --
that's what makes this an actual hard failure instead of a quiet no-op.

Scoped to wd_telegram's OWN `requests` name (mirroring src/jsearch_pool.py's
_PooledRequests technique), not the shared `requests` module -- so this
never affects any other module's own `import requests` (wd_poc.py,
apollo_enrich.py, etc. all monkeypatch their own `requests.post` directly in
their own tests, which still works normally: that monkeypatch.setattr call
runs inside the test body, after this autouse fixture has already run, so it
simply overrides this default for that one test).

Known gap: _edit() dispatches its requests.post call onto a background
daemon thread (src/wd_telegram.py's _dispatch_edit) to keep the pipeline's
own thread from blocking on a slow Telegram response. An exception raised
there does not propagate to the main test thread, so this guard's coverage
is the two SYNCHRONOUS entry points (send(), and progress()'s first call
via _send_and_get_id()) -- which is exactly the shape both known leaks took,
and the shape any realistic future one would too (a test would need to call
progress() more than once, past the live-message rate-limit window, to ever
reach _edit() at all).
"""
from __future__ import annotations

import pytest

from src import wd_telegram


class _BlockedRequests:
    def post(self, *args, **kwargs):
        pytest.fail(
            "A test attempted a real Telegram HTTP call via wd_telegram.requests.post "
            "-- pass an explicit no-op progress callback instead of relying on the "
            "tg.progress/tg.send default.",
            pytrace=False,
        )

    def __getattr__(self, name):
        import requests as _real_requests
        return getattr(_real_requests, name)


@pytest.fixture(autouse=True)
def _block_real_telegram_sends(monkeypatch):
    monkeypatch.setattr(wd_telegram, "requests", _BlockedRequests())
