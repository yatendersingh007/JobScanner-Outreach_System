"""The Postgres advisory run lock, as seen from signal_pipeline.run(),
run_scan.run_single_firm(), run_scan.run_resume(), and src/cli.py.

wd_dbc.acquire_run_lock()/release_run_lock() themselves (concurrent acquire,
release, reconcile-while-held) are tested directly in tests/test_wd_dbc.py.
This file tests that the THREE run-starting functions actually take the lock
before creating/touching a wd_runs row, actually release it in a finally
(even when the run body raises), and raise the distinct
wd_dbc.RunAlreadyInProgress -- not a bare ValueError -- when it's already
held, so each front door can word it for its own surface. bot.py's own
handling is tested in test_bot_dispatch.py, alongside its other dispatch
tests.

No live Postgres, no network: acquire_run_lock/release_run_lock are
monkeypatched directly here (their own correctness is test_wd_dbc.py's job).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src import cli, signal_pipeline, wd_dbc
from src.run_scan import run_resume, run_single_firm


def _noop_progress(_msg: str) -> None:
    pass


def _never_acquires(monkeypatch, target):
    monkeypatch.setattr(target.dbc, "acquire_run_lock", lambda: False)


def _always_acquires_and_tracks_release(monkeypatch, target):
    released = []
    monkeypatch.setattr(target.dbc, "acquire_run_lock", lambda: True)
    monkeypatch.setattr(target.dbc, "release_run_lock", lambda: released.append(True))
    return released


# ---------------------------------------------------------------------------
# signal_pipeline.run()
# ---------------------------------------------------------------------------
def test_run_raises_run_already_in_progress_when_lock_unavailable(monkeypatch):
    _never_acquires(monkeypatch, signal_pipeline)
    create_called = []
    monkeypatch.setattr(signal_pipeline.dbc, "create_wd_run", lambda *a, **k: create_called.append(1))

    with pytest.raises(wd_dbc.RunAlreadyInProgress):
        signal_pipeline.run(mode="manual")

    assert create_called == []  # never even created the row for a run that won't happen


def test_run_releases_the_lock_after_a_normal_completion(monkeypatch):
    released = _always_acquires_and_tracks_release(monkeypatch, signal_pipeline)
    monkeypatch.setattr(signal_pipeline.dbc, "create_wd_run",
                        lambda mode, recency_days_used=1: {"id": 1})
    monkeypatch.setattr(signal_pipeline.dbc, "update_wd_run", lambda *a, **k: None)
    monkeypatch.setattr(
        signal_pipeline, "scan",
        lambda recency_days, progress: ([], SimpleNamespace(poc_blocklist=[]), "jobs.csv"),
    )

    signal_pipeline.run(mode="manual")

    assert released == [True]


def test_run_releases_the_lock_even_when_the_run_crashes(monkeypatch):
    released = _always_acquires_and_tracks_release(monkeypatch, signal_pipeline)
    monkeypatch.setattr(signal_pipeline.dbc, "create_wd_run",
                        lambda mode, recency_days_used=1: {"id": 1})
    monkeypatch.setattr(signal_pipeline.dbc, "update_wd_run", lambda *a, **k: None)

    def _boom(recency_days, progress):
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr(signal_pipeline, "scan", _boom)

    with pytest.raises(RuntimeError):
        signal_pipeline.run(mode="manual")

    assert released == [True]  # the finally ran despite the crash


# ---------------------------------------------------------------------------
# run_scan.run_single_firm()
# ---------------------------------------------------------------------------
def test_run_single_firm_raises_when_lock_unavailable(monkeypatch):
    _never_acquires(monkeypatch, signal_pipeline)
    create_called = []
    monkeypatch.setattr(signal_pipeline.dbc, "create_wd_run", lambda *a, **k: create_called.append(1))

    with pytest.raises(wd_dbc.RunAlreadyInProgress):
        run_single_firm(mode="manual", firm_name="Acme Capital", progress=_noop_progress)

    assert create_called == []


def test_run_single_firm_releases_the_lock(monkeypatch):
    released = _always_acquires_and_tracks_release(monkeypatch, signal_pipeline)
    monkeypatch.setattr(signal_pipeline.dbc, "create_wd_run",
                        lambda mode, recency_days_used=1: {"id": 1})
    monkeypatch.setattr(signal_pipeline.dbc, "update_wd_run", lambda *a, **k: None)
    monkeypatch.setattr(
        signal_pipeline, "gate_group",
        lambda run_id, group, progress: {"icp_status": "parked", "id": 1},
    )

    # Every run_single_firm/run_resume call in this file passes an explicit
    # no-op progress -- the module-level default is progress=tg.progress,
    # a REAL Telegram sender. This one specifically used to leak: it's the
    # only call in this file whose code path actually reaches a progress()
    # call ("Gating Acme Capital...") before returning, so leaving the
    # real default here posted a live message to the operator's bot on
    # every pytest run. See conftest.py's autouse guard for the backstop.
    run_single_firm(mode="manual", firm_name="Acme Capital", progress=_noop_progress)

    assert released == [True]


# ---------------------------------------------------------------------------
# run_scan.run_resume()
# ---------------------------------------------------------------------------
def test_run_resume_raises_when_lock_unavailable(monkeypatch):
    _never_acquires(monkeypatch, signal_pipeline)
    checked = []
    monkeypatch.setattr(signal_pipeline.dbc, "latest_resumable_run",
                        lambda: checked.append(1))

    with pytest.raises(wd_dbc.RunAlreadyInProgress):
        run_resume(progress=_noop_progress)

    assert checked == []  # never even looked for a resumable run


def test_run_resume_releases_the_lock_when_nothing_is_resumable(monkeypatch):
    released = _always_acquires_and_tracks_release(monkeypatch, signal_pipeline)
    monkeypatch.setattr(signal_pipeline.dbc, "latest_resumable_run", lambda: None)

    result = run_resume(progress=_noop_progress)

    assert result is None
    assert released == [True]


# ---------------------------------------------------------------------------
# src/cli.py: catches RunAlreadyInProgress and prints it plainly, distinct
# from a generic crash (no traceback re-raised).
# ---------------------------------------------------------------------------
def test_cli_prints_run_already_in_progress_plainly(monkeypatch, capsys):
    def _boom(**kwargs):
        raise wd_dbc.RunAlreadyInProgress("Another Workflow D run is already in progress.")

    monkeypatch.setattr(cli, "run_scan", _boom)

    exit_code = cli.main(["scan"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Another Workflow D run is already in progress." in captured.err
    assert "Traceback" not in captured.err
