"""wd_telegram.progress()/finish(): this was our own bug, not a donor issue
(confirmed against referral-system's _LiveBatchStatus, which already carries
the fix). Two adversarial-review-grade properties, ported here:

1. The actual editMessageText HTTP call runs on a background daemon thread,
   never on the caller's thread (the pipeline's per-firm loop calls
   progress() directly and synchronously).
2. The throttle timestamp and the dedup text are claimed BEFORE the dispatch,
   unconditionally -- not only on success -- so a failure/rate-limit streak
   cannot retry on every single call with no backoff.

Plus terminal-state handling (finish()): a stopped run's live message reads
Done./Cancelled./Crashed. instead of freezing on the last progress() line.

No live token, no network: _send_and_get_id/_edit are monkeypatched directly,
and threading.Thread is replaced with a stand-in that runs synchronously so
tests are deterministic while still proving a Thread object was used.
"""
from __future__ import annotations

import pytest

from src import wd_telegram


class _SyncThread:
    """Stand-in for threading.Thread: records construction, runs target()
    synchronously in .start() so assertions don't need to sleep/join."""
    instances: list["_SyncThread"] = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon
        _SyncThread.instances.append(self)

    def start(self):
        self.target(*self.args, **self.kwargs)


class _FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def time(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """wd_telegram's live-message state is module-level globals -- reset
    between tests, and always use the sync-thread stand-in and a fake clock
    so no test depends on real time passing or real threads landing."""
    wd_telegram.reset_live()
    _SyncThread.instances = []
    monkeypatch.setattr(wd_telegram.threading, "Thread", _SyncThread)
    clock = _FakeClock()
    monkeypatch.setattr(wd_telegram.time, "time", clock.time)
    yield clock
    wd_telegram.reset_live()


def test_first_progress_call_sends_not_edits(monkeypatch, _reset_module_state):
    sent = []
    monkeypatch.setattr(wd_telegram, "_send_and_get_id", lambda msg: (sent.append(msg), 42)[1])

    wd_telegram.progress("starting")

    assert sent == ["starting"]
    assert wd_telegram._live_message_id == 42
    assert _SyncThread.instances == []  # first call sends, never dispatches an edit


def test_progress_dispatches_edit_via_background_thread(monkeypatch, _reset_module_state):
    clock = _reset_module_state
    monkeypatch.setattr(wd_telegram, "_send_and_get_id", lambda msg: 42)
    edits = []
    monkeypatch.setattr(wd_telegram, "_edit", lambda mid, text: (edits.append((mid, text)), True)[1])

    wd_telegram.progress("firm 1 of 3")
    clock.advance(wd_telegram.LIVE_STATUS_MIN_INTERVAL_SEC + 1)
    wd_telegram.progress("firm 2 of 3")

    assert len(_SyncThread.instances) == 1
    assert _SyncThread.instances[0].daemon is True
    assert _SyncThread.instances[0].target is wd_telegram._edit
    assert edits == [(42, "firm 2 of 3")]


def test_progress_throttled_within_interval(monkeypatch, _reset_module_state):
    clock = _reset_module_state
    monkeypatch.setattr(wd_telegram, "_send_and_get_id", lambda msg: 42)
    edits = []
    monkeypatch.setattr(wd_telegram, "_edit", lambda mid, text: (edits.append(text), True)[1])

    wd_telegram.progress("start")
    clock.advance(1)  # under LIVE_STATUS_MIN_INTERVAL_SEC=3
    wd_telegram.progress("too soon")

    assert edits == []  # the second call never dispatched


def test_progress_dedup_skips_unchanged_text(monkeypatch, _reset_module_state):
    clock = _reset_module_state
    monkeypatch.setattr(wd_telegram, "_send_and_get_id", lambda msg: 42)
    edits = []
    monkeypatch.setattr(wd_telegram, "_edit", lambda mid, text: (edits.append(text), True)[1])

    wd_telegram.progress("same text")
    clock.advance(wd_telegram.LIVE_STATUS_MIN_INTERVAL_SEC + 1)
    wd_telegram.progress("same text")  # unchanged since the initial send

    assert edits == []


def test_throttle_and_dedup_claimed_before_dispatch_even_on_failure(monkeypatch, _reset_module_state):
    """The bug this fixes: claiming _last_live_edit/_last_sent_text only on
    a successful edit meant a failure streak retried every single call with
    no backoff. Simulate _edit always failing and confirm the throttle still
    holds for the next call within the window regardless."""
    clock = _reset_module_state
    monkeypatch.setattr(wd_telegram, "_send_and_get_id", lambda msg: 42)
    attempts = []

    def _always_fails(mid, text):
        attempts.append(text)
        return False

    monkeypatch.setattr(wd_telegram, "_edit", _always_fails)

    wd_telegram.progress("start")
    clock.advance(wd_telegram.LIVE_STATUS_MIN_INTERVAL_SEC + 1)
    wd_telegram.progress("update 1")  # dispatched, fails
    assert attempts == ["update 1"]

    clock.advance(1)  # still inside the window
    wd_telegram.progress("update 2")  # must NOT dispatch: window claimed regardless of failure
    assert attempts == ["update 1"]


def test_finish_labels_done_cancelled_crashed(monkeypatch, _reset_module_state):
    monkeypatch.setattr(wd_telegram, "_send_and_get_id", lambda msg: 42)
    edits = []
    monkeypatch.setattr(wd_telegram, "_edit", lambda mid, text: (edits.append(text), True)[1])

    for reason, label in [("done", "Done."), ("cancelled", "Cancelled."), ("crashed", "Crashed.")]:
        wd_telegram.reset_live()
        edits.clear()
        wd_telegram.progress("in progress")  # first call: just sends, sets _live_message_id
        wd_telegram.finish(reason)
        assert edits == [label]


def test_finish_unknown_reason_falls_back_to_stopped_label(monkeypatch, _reset_module_state):
    monkeypatch.setattr(wd_telegram, "_send_and_get_id", lambda msg: 42)
    edits = []
    monkeypatch.setattr(wd_telegram, "_edit", lambda mid, text: (edits.append(text), True)[1])

    wd_telegram.progress("in progress")
    wd_telegram.finish("infra_paused")

    assert edits == ["Stopped: infra_paused"]


def test_finish_is_noop_without_a_live_message(monkeypatch, _reset_module_state):
    monkeypatch.setattr(wd_telegram, "_edit", lambda mid, text: pytest.fail("must not dispatch"))

    wd_telegram.finish("done")  # no progress() call first -> _live_message_id is None

    assert _SyncThread.instances == []


def test_finish_bypasses_the_throttle_window(monkeypatch, _reset_module_state):
    """A run finishes exactly once; the terminal label must always land even
    if the last progress() edit just fired a moment ago."""
    clock = _reset_module_state
    monkeypatch.setattr(wd_telegram, "_send_and_get_id", lambda msg: 42)
    edits = []
    monkeypatch.setattr(wd_telegram, "_edit", lambda mid, text: (edits.append(text), True)[1])

    wd_telegram.progress("start")
    clock.advance(wd_telegram.LIVE_STATUS_MIN_INTERVAL_SEC + 1)
    wd_telegram.progress("mid-run")
    clock.advance(0.1)  # well inside the window
    wd_telegram.finish("done")

    assert edits[-1] == "Done."


def test_reset_live_clears_all_state(monkeypatch, _reset_module_state):
    monkeypatch.setattr(wd_telegram, "_send_and_get_id", lambda msg: 42)
    wd_telegram.progress("start")
    assert wd_telegram._live_message_id is not None

    wd_telegram.reset_live()

    assert wd_telegram._live_message_id is None
    assert wd_telegram._last_live_edit == 0.0
    assert wd_telegram._last_sent_text is None
