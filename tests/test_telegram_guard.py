"""conftest.py's autouse _block_real_telegram_sends fixture: the general
backstop against any test leaking a real Telegram HTTP call (run 27 fix --
see conftest.py's own docstring for the full incident).

These tests deliberately configure a fake-but-truthy token/chat (the exact
condition under which src/wd_telegram.py's own functions would otherwise
attempt a real network call) and confirm the guard intercepts before that
call ever reaches the network, via pytest.fail() -- which subclasses
BaseException specifically so it survives wd_telegram.py's own bare
`except Exception` around every requests.post call.
"""
from __future__ import annotations

import pytest

from src import wd_telegram


@pytest.fixture(autouse=True)
def _configured_bot(monkeypatch):
    """Every send()/progress() path in wd_telegram.py short-circuits to a
    safe no-op when no token/chat is configured -- these tests exist to
    prove the OTHER case (a real token/chat present, matching this repo's
    own .env) is caught, so a token/chat must actually be set for them to
    mean anything."""
    monkeypatch.setattr(wd_telegram.config, "TELEGRAM_BOT_TOKEN_D", "fake-token-for-this-test")
    monkeypatch.setattr(wd_telegram.config, "TELEGRAM_CHAT_ID", "12345")


def test_send_is_blocked(monkeypatch):
    with pytest.raises(pytest.fail.Exception):
        wd_telegram.send("this must never actually reach api.telegram.org")


def test_progress_first_call_is_blocked(monkeypatch):
    monkeypatch.setattr(wd_telegram, "_live_message_id", None)
    with pytest.raises(pytest.fail.Exception):
        wd_telegram.progress("this must never actually reach api.telegram.org")


def test_guard_does_not_affect_other_modules_own_requests_binding():
    """Scoped to wd_telegram's own `requests` name only -- mirrors
    src/jsearch_pool.py's _PooledRequests technique specifically so a
    completely unrelated module's own `import requests` is untouched."""
    from src import wd_poc

    assert wd_poc.requests.post is not wd_telegram.requests.post
