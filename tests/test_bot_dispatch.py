"""Prompt 2 VERIFY: src/bot.py's command surface.

Test _dispatch (and the one level above it, _process_updates, for the
authorization boundary specifically) directly. Never run_bot()'s loop, no
live token, no network, no real Postgres -- run_scan/run_single_firm/
run_resume and every wd_dbc call bot.py makes are monkeypatched.

Two things this file deliberately does NOT test as PROMPTS.md originally
worded them, and why:

- "/scan with no args drafts" -- superseded by explicit instruction: this
  build has no signal_drafting.py yet (prompts 3-4), so /scan must instead
  fail LOUDLY ("drafting is not built yet ... use /scan dry"), never
  silently behave like --dry. Tested as such below.
- "DRAFT_CAP_PER_RUN=2 against 5 qualified firms drafts exactly 2 and parks
  3" -- there is no real drafting to exercise yet. Tested instead as the
  draft-INTENT message's arithmetic (2 would be drafted, 3 over cap), which
  is the actual, honest behavior this build produces per prompt 2 step 2a.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import bot
from src.signal_pipeline import RunResult


class _SyncThread:
    """threading.Thread stand-in: runs target() synchronously in .start(),
    so /scan and /resume's background-thread dispatch is deterministic."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon

    def start(self):
        self.target(*self.args, **self.kwargs)


@pytest.fixture(autouse=True)
def wire(monkeypatch):
    monkeypatch.setattr(bot.threading, "Thread", _SyncThread)
    sent, progressed, finished = [], [], []
    monkeypatch.setattr(bot.tg, "send", lambda text, chat_id=None: sent.append(text))
    monkeypatch.setattr(bot.tg, "progress", lambda msg: progressed.append(msg))
    monkeypatch.setattr(bot.tg, "finish", lambda reason: finished.append(reason))
    monkeypatch.setattr(bot.tg, "reset_live", lambda: None)
    if bot._busy.locked():
        bot._busy.release()
    yield SimpleNamespace(sent=sent, progressed=progressed, finished=finished)
    if bot._busy.locked():
        bot._busy.release()


def _qualified_firm(name="Acme Capital", i=1):
    return {"id": i, "firm_name": name, "posting_count": 2, "aum_tag": "AUM_CONFIRMED",
           "verdict_source": "gated", "icp_status": "qualified"}


# ---------------------------------------------------------------------------
# Command routing: every command reaches the right handler, with a fake
# sender (chat_id is irrelevant -- Workflow D is single-operator).
# ---------------------------------------------------------------------------
def test_scan_routes_to_handle_scan(monkeypatch, wire):
    called = []
    monkeypatch.setattr(bot, "_handle_scan", lambda arg: called.append(("scan", arg)))
    bot._dispatch('/scan "Acme"')
    assert called == [("scan", '"Acme"')]


def test_cancel_routes_to_handle_cancel(monkeypatch, wire):
    called = []
    monkeypatch.setattr(bot, "_handle_cancel", lambda: called.append("cancel"))
    bot._dispatch("/cancel")
    assert called == ["cancel"]


def test_resume_routes_to_handle_resume(monkeypatch, wire):
    called = []
    monkeypatch.setattr(bot, "_handle_resume", lambda: called.append("resume"))
    bot._dispatch("/resume")
    assert called == ["resume"]


def test_status_routes_to_handle_status(monkeypatch, wire):
    called = []
    monkeypatch.setattr(bot, "_handle_status", lambda: called.append("status"))
    bot._dispatch("/status")
    assert called == ["status"]


def test_qualify_routes_to_handle_qualify(monkeypatch, wire):
    called = []
    monkeypatch.setattr(bot, "_handle_qualify", lambda arg: called.append(("qualify", arg)))
    bot._dispatch('/qualify "Acme" 800M')
    assert called == [("qualify", '"Acme" 800M')]


def test_disqualify_routes_to_handle_disqualify(monkeypatch, wire):
    called = []
    monkeypatch.setattr(bot, "_handle_disqualify", lambda arg: called.append(("disqualify", arg)))
    bot._dispatch('/disqualify "Acme"')
    assert called == [("disqualify", '"Acme"')]


def test_help_and_start_send_help_text(wire):
    bot._dispatch("/help")
    bot._dispatch("/start")
    assert wire.sent == [bot._help_text(), bot._help_text()]


def test_unknown_command_sends_help(wire):
    bot._dispatch("/whatever")
    assert "Unknown command: whatever" in wire.sent[0]


def test_non_command_text_is_ignored(monkeypatch, wire):
    called = []
    monkeypatch.setattr(bot, "_handle_scan", lambda arg: called.append(arg))
    bot._dispatch("just chatting, no slash")
    assert called == []
    assert wire.sent == []


def test_scan_stop_is_an_alias_for_cancel(monkeypatch, wire):
    called = []
    monkeypatch.setattr(bot, "_handle_cancel", lambda: called.append("cancel"))
    bot._handle_scan("stop")
    assert called == ["cancel"]


# ---------------------------------------------------------------------------
# Authorization boundary: lives in _process_updates (called by run_bot's
# loop), NOT in _dispatch. An unauthorized sender must reach _dispatch_message
# not at all.
# ---------------------------------------------------------------------------
def test_process_updates_unauthorized_sender_reaches_nothing(monkeypatch, wire):
    dispatched = []
    monkeypatch.setattr(bot, "_dispatch_message", lambda msg: dispatched.append(msg))
    updates = [{"update_id": 1, "message": {"from": {"id": 999}, "text": "/status"}}]
    bot._process_updates(updates, allowed={"111"})
    assert dispatched == []


def test_process_updates_authorized_sender_dispatches(monkeypatch, wire):
    dispatched = []
    monkeypatch.setattr(bot, "_dispatch_message", lambda msg: dispatched.append(msg))
    updates = [{"update_id": 1, "message": {"from": {"id": 111}, "text": "/status"}}]
    next_offset = bot._process_updates(updates, allowed={"111"})
    assert len(dispatched) == 1
    assert next_offset == 2


def test_process_updates_advances_offset_even_for_unauthorized(monkeypatch, wire):
    monkeypatch.setattr(bot, "_dispatch_message", lambda msg: None)
    updates = [{"update_id": 5, "message": {"from": {"id": 999}, "text": "/status"}}]
    next_offset = bot._process_updates(updates, allowed={"111"})
    assert next_offset == 6  # an unauthorized update is still consumed, never replayed


# ---------------------------------------------------------------------------
# Parsing: quoted firm names with commas and apostrophes. See the module
# docstring in bot.py -- this is the corrected side, not the donor's.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ('"Smith, Jones & Co" 800M', ("Smith, Jones & Co", "800M")),
    ("\"O'Brien Capital\" 450M", ("O'Brien Capital", "450M")),
    ("Acme Capital Partners 300M", ("Acme Capital Partners", "300M")),
    ("  Acme Capital  ", ("Acme Capital", "")),
])
def test_parse_quoted_handles_commas_apostrophes_and_whitespace(text, expected):
    assert bot.parse_quoted(text) == expected


def test_scan_command_fragment_is_rejected_not_treated_as_firm(wire):
    bot._handle_scan('"dry"')
    assert len(wire.sent) == 1
    assert "leftover /scan option" in wire.sent[0]


def test_scan_command_fragment_never_calls_run_scan_or_run_single_firm(monkeypatch, wire):
    called = []
    monkeypatch.setattr(bot, "run_scan", lambda **kw: called.append(("scan", kw)))
    monkeypatch.setattr(bot, "run_single_firm", lambda **kw: called.append(("single", kw)))
    bot._handle_scan('"dry"')
    assert called == []


# ---------------------------------------------------------------------------
# /scan behavior: the two things explicitly checked this round.
# ---------------------------------------------------------------------------
def test_scan_dry_reports_dry_stop_and_skips_the_not_built_note(monkeypatch, wire):
    result = RunResult(run_id=1, mode="manual", recency_days_used=1, dry=True)
    result.qualified = [_qualified_firm()]
    monkeypatch.setattr(bot, "run_scan", lambda **kw: result)

    bot._handle_scan("dry")

    combined = "\n".join(wire.sent)
    assert "Dry run. Stopped after gating." in combined
    assert "would be drafted" not in combined  # 2a's intent message is dry-gated, never sent


def test_scan_no_args_fails_loudly_not_silently_dry(monkeypatch, wire):
    """The exact behavior checked this round: /scan with no args must say
    'drafting not built yet ... use /scan dry' out loud, never quietly
    behave like --dry."""
    result = RunResult(run_id=2, mode="manual", recency_days_used=1, dry=False)
    result.qualified = [_qualified_firm()]
    monkeypatch.setattr(bot, "run_scan", lambda **kw: result)

    bot._handle_scan("")

    combined = "\n".join(wire.sent)
    assert "not built yet" in combined
    assert "/scan dry" in combined
    assert "Dry run. Stopped after gating." not in combined


def test_scan_passes_dry_false_by_default(monkeypatch, wire):
    captured = {}

    def fake_run_scan(**kw):
        captured.update(kw)
        return RunResult(run_id=3, mode="manual", recency_days_used=1, dry=kw.get("dry", False))

    monkeypatch.setattr(bot, "run_scan", fake_run_scan)
    bot._handle_scan("")
    assert captured["dry"] is False


def test_scan_dry_flag_passes_dry_true(monkeypatch, wire):
    captured = {}

    def fake_run_scan(**kw):
        captured.update(kw)
        return RunResult(run_id=4, mode="manual", recency_days_used=1, dry=True)

    monkeypatch.setattr(bot, "run_scan", fake_run_scan)
    bot._handle_scan("dry")
    assert captured["dry"] is True


def test_scan_days_parses_and_passes_through(monkeypatch, wire):
    captured = {}

    def fake_run_scan(**kw):
        captured.update(kw)
        return RunResult(run_id=6, mode="manual", recency_days_used=7, dry=False)

    monkeypatch.setattr(bot, "run_scan", fake_run_scan)
    bot._handle_scan("days 7")
    assert captured["days"] == 7


def test_scan_firm_calls_run_single_firm_not_run_scan(monkeypatch, wire):
    scan_called = []
    single_called = []
    monkeypatch.setattr(bot, "run_scan", lambda **kw: scan_called.append(kw) or RunResult(run_id=1))
    monkeypatch.setattr(
        bot, "run_single_firm",
        lambda **kw: single_called.append(kw) or RunResult(run_id=2, mode=kw["mode"]),
    )

    bot._handle_scan("\"O'Brien Capital\"")

    assert scan_called == []
    assert len(single_called) == 1
    assert single_called[0]["firm_name"] == "O'Brien Capital"


# ---------------------------------------------------------------------------
# Draft-intent message (prompt 2 step 2a) -- the honest stand-in for "drafts
# exactly N and parks the rest" until signal_drafting.py exists.
#
# The arithmetic itself (drafts_planned/drafts_over_cap) is computed by
# signal_pipeline._apply_draft_cap_fields(), tested in test_recency_window.py
# -- bot.py only READS and formats those two fields now, per the fix that
# moved the computation out of bot.py (it was duplicating what the pipeline
# would also need to compute for real once drafting exists). So here we set
# them directly on the mock RunResult, the same way run_scan()/
# run_single_firm()/run_resume() already would have, and check only the
# formatting.
# ---------------------------------------------------------------------------
def test_draft_intent_message_formats_pipeline_computed_fields(monkeypatch, wire):
    result = RunResult(run_id=5, mode="manual", recency_days_used=1, dry=False)
    result.qualified = [_qualified_firm(f"Firm {i}", i) for i in range(5)]
    result.drafts_planned = 2
    result.drafts_over_cap = 3
    monkeypatch.setattr(bot, "run_scan", lambda **kw: result)

    bot._handle_scan("")

    combined = "\n".join(wire.sent)
    assert "5 qualified" in combined
    assert "2 would be drafted" in combined
    assert "3 over cap" in combined


def test_draft_intent_message_does_not_compute_its_own_arithmetic(monkeypatch, wire):
    """bot.py must not recompute drafts_planned/drafts_over_cap itself --
    changing DRAFT_CAP_PER_RUN here must have NO effect on the message,
    since only the pipeline-set fields on the result are read."""
    monkeypatch.setattr(bot.config, "DRAFT_CAP_PER_RUN", 999)
    result = RunResult(run_id=5, mode="manual", recency_days_used=1, dry=False)
    result.qualified = [_qualified_firm(f"Firm {i}", i) for i in range(5)]
    result.drafts_planned = 2
    result.drafts_over_cap = 3
    monkeypatch.setattr(bot, "run_scan", lambda **kw: result)

    bot._handle_scan("")

    combined = "\n".join(wire.sent)
    assert "2 would be drafted" in combined
    assert "3 over cap" in combined


def test_draft_intent_message_omitted_when_qualified_is_zero(monkeypatch, wire):
    result = RunResult(run_id=8, mode="manual", recency_days_used=1, dry=False)
    monkeypatch.setattr(bot, "run_scan", lambda **kw: result)

    bot._handle_scan("")

    combined = "\n".join(wire.sent)
    assert "would be drafted" not in combined


# ---------------------------------------------------------------------------
# /cancel, /qualify, /disqualify, /status
# ---------------------------------------------------------------------------
def test_cancel_with_no_running_run(monkeypatch, wire):
    monkeypatch.setattr(bot.dbc, "latest_running_run", lambda: None)
    bot._handle_cancel()
    assert wire.sent == ["No run in progress to cancel."]


def test_cancel_requests_cancellation_on_the_running_run(monkeypatch, wire):
    monkeypatch.setattr(bot.dbc, "latest_running_run", lambda: {"id": 7})
    requested = []
    monkeypatch.setattr(bot.dbc, "request_run_cancellation", lambda run_id: requested.append(run_id))
    bot._handle_cancel()
    assert requested == [7]
    assert "run #7" in wire.sent[0]


def test_qualify_rejects_out_of_band_aum(monkeypatch, wire):
    monkeypatch.setattr(bot.dbc, "parked_firm_by_name", lambda name: {"id": 1, "firm_name": name})
    updated = []
    monkeypatch.setattr(bot.dbc, "update_wd_firm", lambda *a, **k: updated.append((a, k)))
    bot._handle_qualify('"Acme" 5B')  # over gate_config.AUM_MAX_USD (2B)
    assert updated == []
    assert "Still DISQUALIFIED" in wire.sent[0]


def test_qualify_updates_a_parked_firm_in_band(monkeypatch, wire):
    monkeypatch.setattr(bot.dbc, "parked_firm_by_name", lambda name: {"id": 9, "firm_name": name})
    updated = []
    monkeypatch.setattr(bot.dbc, "update_wd_firm", lambda firm_id, **k: updated.append((firm_id, k)))
    bot._handle_qualify('"Acme Capital" 800M')
    assert updated[0][0] == 9
    assert updated[0][1]["icp_status"] == "qualified"
    assert "Qualified" in wire.sent[0]


def test_qualify_no_parked_firm_found(monkeypatch, wire):
    monkeypatch.setattr(bot.dbc, "parked_firm_by_name", lambda name: None)
    bot._handle_qualify('"Nonexistent" 800M')
    assert "No PARKED firm" in wire.sent[0]


def test_qualify_bad_aum_text(monkeypatch, wire):
    monkeypatch.setattr(bot.dbc, "parked_firm_by_name", lambda name: {"id": 1, "firm_name": name})
    bot._handle_qualify('"Acme" not-a-number')
    assert "Could not read an AUM" in wire.sent[0]


def test_disqualify_updates_a_parked_firm(monkeypatch, wire):
    monkeypatch.setattr(bot.dbc, "parked_firm_by_name", lambda name: {"id": 3, "firm_name": name})
    updated = []
    monkeypatch.setattr(bot.dbc, "update_wd_firm", lambda firm_id, **k: updated.append((firm_id, k)))
    bot._handle_disqualify('"Acme"')
    assert updated[0][0] == 3
    assert updated[0][1]["icp_status"] == "disqualified"


def test_status_with_no_runs(monkeypatch, wire):
    monkeypatch.setattr(bot.dbc, "latest_wd_run", lambda: None)
    bot._handle_status()
    assert wire.sent == ["No runs yet."]


def test_status_reports_buckets_and_queue(monkeypatch, wire):
    monkeypatch.setattr(bot.dbc, "latest_wd_run", lambda: {
        "id": 10, "mode": "manual", "status": "done", "started_at": "t0",
        "finished_at": "t1", "tavily_searches": 4, "llm_tokens": 500, "research_cost_usd": 1.5,
    })
    monkeypatch.setattr(bot.dbc, "firms_for_run", lambda run_id: [
        {"icp_status": "qualified"}, {"icp_status": "qualified"}, {"icp_status": "parked"},
    ])
    monkeypatch.setattr(bot.dbc, "queue_counts", lambda run_id: {"pending": 2, "done": 3})

    bot._handle_status()

    combined = wire.sent[0]
    assert "Qualified: 2" in combined
    assert "Parked: 1" in combined
    assert "2 pending, 3 done" in combined


# ---------------------------------------------------------------------------
# /resume
# ---------------------------------------------------------------------------
def test_resume_with_nothing_resumable(monkeypatch, wire):
    monkeypatch.setattr(bot, "run_resume", lambda **kw: None)
    bot._handle_resume()
    assert any("Nothing to resume" in s for s in wire.sent)


def test_resume_sends_summary_when_something_resumed(monkeypatch, wire):
    result = RunResult(run_id=11, mode="resume", recency_days_used=1, dry=False)
    monkeypatch.setattr(bot, "run_resume", lambda **kw: result)
    bot._handle_resume()
    assert any("Workflow D run 11: resume" in s for s in wire.sent)


# ---------------------------------------------------------------------------
# _poll_once: a transient network error must back off and retry, never spin
# in a tight loop or kill the process. Tested directly, never run_bot()'s
# real infinite loop (which needs a live token).
# ---------------------------------------------------------------------------
def test_poll_once_retries_after_transient_network_error(monkeypatch, wire):
    def boom(offset, timeout=30):
        raise bot.requests.ConnectionError("boom")

    monkeypatch.setattr(bot, "get_updates", boom)
    slept = []
    monkeypatch.setattr(bot.time, "sleep", lambda s: slept.append(s))

    result_offset = bot._poll_once(42, {"111"})

    assert result_offset == 42  # unchanged -- re-fetch from the same place next time
    assert slept == [bot._POLL_ERROR_BACKOFF_SEC]


def test_poll_once_does_not_propagate_the_network_error(monkeypatch, wire):
    monkeypatch.setattr(bot, "get_updates", lambda offset, timeout=30: (_ for _ in ()).throw(
        bot.requests.Timeout("timed out")))
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)

    bot._poll_once(1, {"111"})  # must not raise


def test_poll_once_processes_updates_normally(monkeypatch, wire):
    monkeypatch.setattr(
        bot, "get_updates",
        lambda offset, timeout=30: [{"update_id": 9, "message": {"from": {"id": 111}, "text": "/status"}}],
    )
    dispatched = []
    monkeypatch.setattr(bot, "_dispatch_message", lambda msg: dispatched.append(msg))

    result_offset = bot._poll_once(5, {"111"})

    assert result_offset == 10
    assert len(dispatched) == 1


def test_poll_once_keeps_offset_when_no_updates(monkeypatch, wire):
    monkeypatch.setattr(bot, "get_updates", lambda offset, timeout=30: [])
    assert bot._poll_once(7, {"111"}) == 7


# ---------------------------------------------------------------------------
# _startup(): reconcile_orphaned_runs() itself is covered at the wd_dbc level
# in tests/test_wd_dbc.py. Here we confirm the ORDERING run_bot() depends on
# -- reconciliation happens before anything Telegram-facing, including the
# very first get_updates call -- behaviorally, not by reading source text.
# run_bot() itself still isn't called (real infinite loop, needs a live
# token); _startup() is the part of it that actually can be.
# ---------------------------------------------------------------------------
def test_startup_reconciles_before_the_first_get_updates_call(monkeypatch, wire):
    monkeypatch.setattr(bot.config, "TELEGRAM_BOT_TOKEN_D", "fake-token")
    monkeypatch.setattr(bot.config, "AUTHORIZED_USER_IDS", ["111"])
    order = []
    monkeypatch.setattr(bot.dbc, "reconcile_orphaned_runs",
                        lambda: (order.append("reconcile"), 0)[1])
    monkeypatch.setattr(bot, "get_updates",
                        lambda offset, timeout=30: (order.append("get_updates"), [])[1])

    bot._startup()

    assert order == ["reconcile", "get_updates"]


def test_startup_notifies_when_runs_were_reconciled(monkeypatch, wire):
    monkeypatch.setattr(bot.config, "TELEGRAM_BOT_TOKEN_D", "fake-token")
    monkeypatch.setattr(bot.config, "AUTHORIZED_USER_IDS", ["111"])
    monkeypatch.setattr(bot.dbc, "reconcile_orphaned_runs", lambda: 2)
    monkeypatch.setattr(bot, "get_updates", lambda offset, timeout=30: [])

    bot._startup()

    assert any("reconciled 2 orphaned run" in s for s in wire.sent)


def test_startup_silent_when_nothing_was_orphaned(monkeypatch, wire):
    monkeypatch.setattr(bot.config, "TELEGRAM_BOT_TOKEN_D", "fake-token")
    monkeypatch.setattr(bot.config, "AUTHORIZED_USER_IDS", ["111"])
    monkeypatch.setattr(bot.dbc, "reconcile_orphaned_runs", lambda: 0)
    monkeypatch.setattr(bot, "get_updates", lambda offset, timeout=30: [])

    bot._startup()

    assert not any("reconciled" in s for s in wire.sent)


def test_startup_refuses_without_bot_token(monkeypatch, wire):
    monkeypatch.setattr(bot.config, "TELEGRAM_BOT_TOKEN_D", "")
    monkeypatch.setattr(bot.config, "AUTHORIZED_USER_IDS", ["111"])
    with pytest.raises(SystemExit):
        bot._startup()


def test_startup_refuses_without_authorized_users(monkeypatch, wire):
    monkeypatch.setattr(bot.config, "TELEGRAM_BOT_TOKEN_D", "fake-token")
    monkeypatch.setattr(bot.config, "AUTHORIZED_USER_IDS", [])
    with pytest.raises(SystemExit):
        bot._startup()


# ---------------------------------------------------------------------------
# RunAlreadyInProgress: the real cross-front-door guard (a Postgres advisory
# lock, not _busy) surfacing through the bot. _busy only ever sees this one
# process; this is what actually fires when the CLI (a separate process) or
# another bot instance is mid-run. Must read distinctly from a genuine crash
# -- no "Crashed." label, no CRASHED wording.
# ---------------------------------------------------------------------------
def test_scan_reports_run_already_in_progress_distinctly_from_a_crash(monkeypatch, wire):
    def _boom(**kw):
        raise bot.dbc.RunAlreadyInProgress("Another Workflow D run is already in progress.")

    monkeypatch.setattr(bot, "run_scan", _boom)

    bot._handle_scan("")

    assert wire.sent == ["Workflow D run started.",
                         "Another Workflow D run is already in progress."]
    assert wire.finished == []  # never called tg.finish("crashed") for this


def test_resume_reports_run_already_in_progress_distinctly_from_a_crash(monkeypatch, wire):
    def _boom(**kw):
        raise bot.dbc.RunAlreadyInProgress("Another Workflow D run is already in progress.")

    monkeypatch.setattr(bot, "run_resume", _boom)

    bot._handle_resume()

    assert "Another Workflow D run is already in progress." in wire.sent
    assert wire.finished == []
