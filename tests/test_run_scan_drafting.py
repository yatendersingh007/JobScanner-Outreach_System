"""Prompt 3: run_scan.py's wiring between gating and drafting.

Drafting runs INLINE right after gating, in the same run_scan()/
run_single_firm()/run_resume() call -- not a second command. The
spend/draft-intent message (Prompt 2 step 2a) fires as its own persistent
tg.send() message BEFORE signal_drafting.draft_for_run() starts, distinct
from the rate-limited live-edited progress() line.

signal_pipeline.run() and signal_drafting.draft_for_run() are each mocked at
their own module boundary on run_scan's imported references -- this file
tests only the GLUE between them, not either module's own internals (those
live in test_recency_window.py and test_signal_drafting.py respectively).
"""
from __future__ import annotations

import pytest

from src import run_scan, wd_telegram as tg
from src.signal_drafting import DraftBatchResult
from src.signal_pipeline import RunResult


def _qualified_firm(name="Acme Capital", i=1):
    return {"id": i, "firm_name": name, "posting_count": 2, "aum_tag": "AUM_CONFIRMED",
           "verdict_source": "gated", "icp_status": "qualified"}


@pytest.fixture(autouse=True)
def wire(monkeypatch):
    sent = []
    monkeypatch.setattr(tg, "send", lambda text, chat_id=None: sent.append(text))
    return sent


def test_run_scan_sends_intent_message_before_drafting(monkeypatch, wire):
    gated = RunResult(run_id=1, mode="manual", recency_days_used=1, dry=False)
    gated.qualified = [_qualified_firm(f"Firm {i}", i) for i in range(5)]
    gated.drafts_planned = 2
    gated.drafts_over_cap = 3
    monkeypatch.setattr(run_scan.signal_pipeline, "run", lambda **kw: gated)

    order = []

    def fake_draft_for_run(run_id, progress):
        order.append("draft_for_run")
        return DraftBatchResult()

    monkeypatch.setattr(run_scan.signal_drafting, "draft_for_run", fake_draft_for_run)

    run_scan.run_scan(mode="manual")

    combined = "\n".join(wire)
    assert "5 qualified" in combined
    assert "2 will be drafted" in combined
    assert "3 over cap" in combined
    assert order == ["draft_for_run"]  # the intent message (asserted above) was sent first


def test_run_scan_intent_message_omitted_when_nothing_qualified(monkeypatch, wire):
    gated = RunResult(run_id=1, mode="manual", recency_days_used=1, dry=False)
    monkeypatch.setattr(run_scan.signal_pipeline, "run", lambda **kw: gated)
    called = []
    monkeypatch.setattr(run_scan.signal_drafting, "draft_for_run",
                        lambda run_id, progress: called.append(1) or DraftBatchResult())

    run_scan.run_scan(mode="manual")

    assert wire == []
    assert called == []


def test_run_scan_dry_never_drafts(monkeypatch, wire):
    gated = RunResult(run_id=1, mode="manual", recency_days_used=1, dry=True)
    gated.qualified = [_qualified_firm()]
    monkeypatch.setattr(run_scan.signal_pipeline, "run", lambda **kw: gated)
    called = []
    monkeypatch.setattr(run_scan.signal_drafting, "draft_for_run",
                        lambda run_id, progress: called.append(1))

    result = run_scan.run_scan(mode="manual", dry=True)

    assert called == []
    assert wire == []
    assert result.drafted == []


def test_run_scan_merges_draft_batch_result_onto_run_result(monkeypatch, wire):
    gated = RunResult(run_id=1, mode="manual", recency_days_used=1, dry=False)
    gated.qualified = [_qualified_firm()]
    monkeypatch.setattr(run_scan.signal_pipeline, "run", lambda **kw: gated)
    batch = DraftBatchResult(drafted=[{"poc_name": "Jane"}], fallback_counts={"style:x": 1})
    monkeypatch.setattr(run_scan.signal_drafting, "draft_for_run", lambda run_id, progress: batch)

    result = run_scan.run_scan(mode="manual")

    assert result.drafted == [{"poc_name": "Jane"}]
    assert result.fallback_counts == {"style:x": 1}


def test_run_scan_cancelled_during_gating_never_drafts(monkeypatch, wire):
    gated = RunResult(run_id=1, mode="manual", recency_days_used=1, dry=False)
    gated.qualified = [_qualified_firm()]
    gated.cancelled = True
    monkeypatch.setattr(run_scan.signal_pipeline, "run", lambda **kw: gated)
    called = []
    monkeypatch.setattr(run_scan.signal_drafting, "draft_for_run",
                        lambda run_id, progress: called.append(1))

    run_scan.run_scan(mode="manual")

    assert called == []


def test_summarize_reports_drafted_and_fallback_counts():
    result = RunResult(run_id=9, mode="manual", recency_days_used=1, dry=False)
    result.qualified = [_qualified_firm()]
    result.drafted = [{"poc_name": "Jane Doe", "poc_email": "jane@x.example", "gmail_draft_id": "D1"}]
    result.drafted_with_prior_contact = [
        {"poc_name": "Sam Lee", "poc_email": "sam@x.example",
         "collision_note": "previously drafted via Workflow C on 2026-01-01, check sent mail."},
    ]
    result.no_email = [{"firm_name": "No Email Co",
                       "no_email_reason": "no way yet to find who runs finance at this firm"}]
    result.duplicate_within_run = [{"firm_name": "Dup Co"}]
    result.fallback_counts = {"forbidden_claim:manpreet_mention": 1}

    text = run_scan.summarize(result)

    assert "DRAFTED 1" in text
    assert "Jane Doe <jane@x.example>" in text
    assert "DRAFTED, PRIOR CONTACT" in text
    assert "previously drafted via Workflow C" in text
    assert "NO EMAIL FOUND 1" in text
    assert "No Email Co: no way yet to find who runs finance at this firm" in text
    assert "DUPLICATE WITHIN RUN" in text
    assert "Dup Co" in text
    assert "forbidden_claim:manpreet_mention=1" in text
