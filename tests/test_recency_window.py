"""Prompt 1: manual trigger + explicit catch-up window.

Diagnose finding this locks in: a posting's dedup key is written to seen.db
the moment scanner/pipeline.py first evaluates it (SeenStore.first_seen()),
before the recency filter decides to keep or drop it. So the automatic
grace-window bump (max(recency_days, first_seen_grace_days)) only ever
applies on first sighting -- recovering a dropped posting on a later run
needs an EXPLICIT wider --days override, it never happens on its own. See
CLAUDE.md's "recency grace window is one-shot per posting" landmine and
DRIFT.md's donor observation on scanner/pipeline.py.

No network: the scanner connectors are replaced with a fake one that returns
canned postings, and seen.db/jobs.csv live under pytest's tmp_path.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from scanner import pipeline as scanner_pipeline
from scanner.config import Config
from scanner.connectors.base import Connector
from scanner.models import NormalizedJob

from src import signal_pipeline, wd_config as config
from src.run_scan import summarize
from src.signal_pipeline import RunResult, _resolve_recency_days

TODAY = date(2026, 1, 20)
POSTED = TODAY - timedelta(days=4)  # a 4-day-old posting, matching the diagnose scenario


class _FakeConnector(Connector):
    name = "fake"

    def __init__(self, jobs):
        self._jobs = jobs

    def fetch(self):
        return list(self._jobs)


def _job() -> NormalizedJob:
    """A fresh instance each call -- scanner/pipeline.run() mutates fields
    (first_seen, region, days_since_posted) in place, so reusing one instance
    across simulated runs would leak state between them."""
    return NormalizedJob(
        company="Acme Capital Partners",
        title="Fund Accountant",
        url="https://example.com/jobs/1",
        source="fake",
        posted_date=POSTED,
        job_id="job-1",
    )


def _make_cfg(tmp_path, recency_days: int) -> Config:
    return Config(
        recency_days=recency_days,
        target_country="US",
        titles=[],
        ats_enabled=False,
        ats_companies=[],
        aggregator_enabled=False,
        aggregator_provider="jsearch",
        tinyfish_enabled=False,
        tinyfish_targets=[],
        csv_path=str(tmp_path / "jobs.csv"),
        seen_db=str(tmp_path / "seen.db"),
        require_title_match=False,  # title filtering is covered in test_scanner_core.py
        us_empty_location_passes=True,
        regions=["US"],
        first_seen_grace_days=3,
        classifier_enabled=False,
        poc_enrichment_enabled=False,
    )


# ---------------------------------------------------------------------------
# _resolve_recency_days: default and bounds
# ---------------------------------------------------------------------------
def test_days_defaults_to_one():
    assert config.DEFAULT_SCAN_DAYS == 1
    assert _resolve_recency_days(None) == 1


def test_days_zero_raises():
    with pytest.raises(ValueError):
        _resolve_recency_days(0)


def test_days_over_max_raises():
    with pytest.raises(ValueError):
        _resolve_recency_days(config.MAX_SCAN_DAYS + 1)


def test_days_at_max_boundary_is_accepted():
    assert _resolve_recency_days(config.MAX_SCAN_DAYS) == config.MAX_SCAN_DAYS


# ---------------------------------------------------------------------------
# A 4-day-old never-before-seen posting: dropped at days=1, kept at days=7
# (PROMPTS.md's original VERIFY spec) -- two independent seen.db's, so both
# sides genuinely exercise the newly_seen=True grace-window branch.
# ---------------------------------------------------------------------------
def test_four_day_old_posting_dropped_at_days_1(monkeypatch, tmp_path):
    cfg = _make_cfg(tmp_path, recency_days=1)
    monkeypatch.setattr(scanner_pipeline, "build_connectors",
                         lambda cfg: [_FakeConnector([_job()])])
    kept = scanner_pipeline.run(cfg, today=TODAY)
    assert kept == []


def test_four_day_old_posting_kept_at_days_7(monkeypatch, tmp_path):
    cfg = _make_cfg(tmp_path, recency_days=7)
    monkeypatch.setattr(scanner_pipeline, "build_connectors",
                         lambda cfg: [_FakeConnector([_job()])])
    kept = scanner_pipeline.run(cfg, today=TODAY)
    assert len(kept) == 1
    assert kept[0].dedup_key() == "fake:job-1"


# ---------------------------------------------------------------------------
# The real-world sequence: one seen.db shared across three simulated runs.
# ---------------------------------------------------------------------------
def test_recency_window_real_world_sequence(monkeypatch, tmp_path):
    cfg = _make_cfg(tmp_path, recency_days=1)
    monkeypatch.setattr(scanner_pipeline, "build_connectors",
                         lambda cfg: [_FakeConnector([_job()])])

    # Run 1: days=1 (no catch-up), first sighting of a 4-day-old posting.
    # newly_seen=True -> effective_days = max(1, 3) = 3; 4 > 3 -> dropped.
    # SeenStore.first_seen() still runs and records the key regardless.
    cfg.recency_days = 1
    kept1 = scanner_pipeline.run(cfg, today=TODAY)
    assert kept1 == []

    # Run 2: days=7, explicit catch-up, same posting. newly_seen is now False
    # (recorded by run 1), so effective_days takes the plain cfg.recency_days
    # branch directly -- the override reaches it even though there is no more
    # automatic grace bump. 4 <= 7 -> recovered.
    cfg.recency_days = 7
    kept2 = scanner_pipeline.run(cfg, today=TODAY)
    assert len(kept2) == 1
    assert kept2[0].dedup_key() == "fake:job-1"

    # Run 3: back to days=1. Still not newly_seen, so still no automatic
    # grace bump -- effective_days=1, 4 > 1 -> dropped again. The one-shot
    # grace window was spent entirely on run 1.
    cfg.recency_days = 1
    kept3 = scanner_pipeline.run(cfg, today=TODAY)
    assert kept3 == []


# ---------------------------------------------------------------------------
# signal_pipeline.run() persists the resolved value to wd_runs
# ---------------------------------------------------------------------------
def test_run_persists_recency_days_used(monkeypatch):
    captured = {}

    def fake_create_wd_run(mode, recency_days_used=1):
        captured["mode"] = mode
        captured["recency_days_used"] = recency_days_used
        return {"id": 1}

    def fake_scan(recency_days, progress):
        captured["scan_recency_days"] = recency_days
        return [], SimpleNamespace(poc_blocklist=[]), "jobs.csv"

    monkeypatch.setattr(signal_pipeline.dbc, "create_wd_run", fake_create_wd_run)
    monkeypatch.setattr(signal_pipeline.dbc, "update_wd_run", lambda *a, **k: None)
    monkeypatch.setattr(signal_pipeline, "scan", fake_scan)

    result = signal_pipeline.run(mode="manual", recency_days=7)

    assert captured["recency_days_used"] == 7
    assert captured["scan_recency_days"] == 7
    assert result.recency_days_used == 7


def test_run_default_recency_days_used_is_one(monkeypatch):
    captured = {}

    def fake_create_wd_run(mode, recency_days_used=1):
        captured["recency_days_used"] = recency_days_used
        return {"id": 1}

    monkeypatch.setattr(signal_pipeline.dbc, "create_wd_run", fake_create_wd_run)
    monkeypatch.setattr(signal_pipeline.dbc, "update_wd_run", lambda *a, **k: None)
    monkeypatch.setattr(
        signal_pipeline, "scan",
        lambda recency_days, progress: ([], SimpleNamespace(poc_blocklist=[]), "jobs.csv"),
    )

    result = signal_pipeline.run(mode="manual")

    assert captured["recency_days_used"] == 1
    assert result.recency_days_used == 1


# ---------------------------------------------------------------------------
# The catch-up window appears in the run summary when N > 1, not when N == 1.
# Constructed the same way signal_pipeline.run() constructs it -- keyword
# arguments to RunResult(), not attributes set after the fact -- since mode
# and dry are real dataclass fields now.
# ---------------------------------------------------------------------------
def test_summary_includes_catchup_line_when_over_one_day():
    result = RunResult(run_id=1, mode="manual", recency_days_used=7, dry=False)
    text = summarize(result)
    assert "Window: last 7 days (catch-up)" in text
    assert "not recoverable by widening further" in text


def test_summary_omits_catchup_line_at_default_one_day():
    result = RunResult(run_id=1, mode="manual", recency_days_used=1, dry=False)
    text = summarize(result)
    assert "catch-up" not in text
