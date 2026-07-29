"""KeyboardInterrupt cleanup in src/cli.py and src/bot.py (never in
scanner/pipeline.py -- vendored). signal_pipeline.run()'s own inner crash
handler only catches Exception, not BaseException, so a KeyboardInterrupt
propagates past it without ever marking wd_runs.status='crashed' -- its
`finally: dbc.release_run_lock()` still runs (finally runs for any
BaseException), so the lock is not actually stuck, but the row sits at
'running' forever unless a bot restart's reconcile_orphaned_runs() happens
to clean it up later. cli.py/bot.py's own BaseException handler closes that
gap directly: find the run via latest_running_run() (same lookup
reconcile_orphaned_runs() uses), mark it crashed with note "interrupted",
release the lock again (safe, idempotent), and re-raise.

No live Postgres, no network: dbc calls are monkeypatched.
"""
from __future__ import annotations

import pytest

from src import bot, cli


# ---------------------------------------------------------------------------
# src/cli.py
# ---------------------------------------------------------------------------
def test_cli_marks_the_running_run_crashed_on_keyboard_interrupt(monkeypatch):
    def _boom(**kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "run_scan", _boom)
    monkeypatch.setattr(cli.dbc, "latest_running_run", lambda: {"id": 42})
    marked = []
    monkeypatch.setattr(cli.dbc, "update_wd_run", lambda run_id, **kw: marked.append((run_id, kw)))
    released = []
    monkeypatch.setattr(cli.dbc, "release_run_lock", lambda: released.append(True))

    with pytest.raises(KeyboardInterrupt):
        cli.main(["scan"])

    assert len(marked) == 1
    run_id, kwargs = marked[0]
    assert run_id == 42
    assert kwargs["status"] == "crashed"
    assert kwargs["notes"] == "interrupted"
    assert "finished_at" in kwargs
    assert released == [True]


def test_cli_interrupt_with_no_running_run_still_releases_and_reraises(monkeypatch):
    """No run is currently 'running' (e.g. interrupted before create_wd_run
    even ran) -- nothing to mark, but the lock release and re-raise still
    happen, and update_wd_run is never called with nothing to update."""

    def _boom(**kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli, "run_scan", _boom)
    monkeypatch.setattr(cli.dbc, "latest_running_run", lambda: None)
    marked = []
    monkeypatch.setattr(cli.dbc, "update_wd_run", lambda run_id, **kw: marked.append((run_id, kw)))
    released = []
    monkeypatch.setattr(cli.dbc, "release_run_lock", lambda: released.append(True))

    with pytest.raises(KeyboardInterrupt):
        cli.main(["scan"])

    assert marked == []
    assert released == [True]


def test_cli_regular_exception_still_uses_the_existing_crash_path(monkeypatch):
    """A normal Exception must NOT go through the new BaseException branch --
    the existing "Workflow D run CRASHED" message and re-raise, unchanged."""

    def _boom(**kwargs):
        raise RuntimeError("normal crash")

    monkeypatch.setattr(cli, "run_scan", _boom)
    called = []
    monkeypatch.setattr(cli.dbc, "latest_running_run", lambda: called.append(1))
    monkeypatch.setattr(cli.dbc, "release_run_lock", lambda: called.append(2))

    with pytest.raises(RuntimeError):
        cli.main(["scan"])

    assert called == []  # the interrupt-only cleanup path never ran


# ---------------------------------------------------------------------------
# src/bot.py
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _wire_telegram(monkeypatch):
    monkeypatch.setattr(bot.tg, "send", lambda *a, **k: None)
    monkeypatch.setattr(bot.tg, "finish", lambda *a, **k: None)
    monkeypatch.setattr(bot.tg, "reset_live", lambda: None)
    if bot._busy.locked():
        bot._busy.release()
    yield
    if bot._busy.locked():
        bot._busy.release()


def test_run_scan_job_marks_crashed_on_keyboard_interrupt(monkeypatch):
    def _boom(**kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(bot, "run_scan", _boom)
    monkeypatch.setattr(bot.dbc, "latest_running_run", lambda: {"id": 7})
    marked = []
    monkeypatch.setattr(bot.dbc, "update_wd_run", lambda run_id, **kw: marked.append((run_id, kw)))
    released = []
    monkeypatch.setattr(bot.dbc, "release_run_lock", lambda: released.append(True))

    bot._busy.acquire()
    with pytest.raises(KeyboardInterrupt):
        bot._run_scan_job({"firm": None, "dry": False, "days": None})

    assert len(marked) == 1
    run_id, kwargs = marked[0]
    assert run_id == 7
    assert kwargs["status"] == "crashed"
    assert kwargs["notes"] == "interrupted"
    assert released == [True]
    assert not bot._busy.locked()  # _run_scan_job's own finally released it


def test_resume_job_marks_crashed_on_keyboard_interrupt(monkeypatch):
    def _boom(**kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(bot, "run_resume", _boom)
    monkeypatch.setattr(bot.dbc, "latest_running_run", lambda: {"id": 9})
    marked = []
    monkeypatch.setattr(bot.dbc, "update_wd_run", lambda run_id, **kw: marked.append((run_id, kw)))
    released = []
    monkeypatch.setattr(bot.dbc, "release_run_lock", lambda: released.append(True))

    bot._busy.acquire()
    with pytest.raises(KeyboardInterrupt):
        bot._resume_job()

    assert len(marked) == 1
    run_id, kwargs = marked[0]
    assert run_id == 9
    assert kwargs["status"] == "crashed"
    assert kwargs["notes"] == "interrupted"
    assert released == [True]
    assert not bot._busy.locked()


def test_run_scan_job_regular_exception_still_uses_existing_crash_path(monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("normal crash")

    monkeypatch.setattr(bot, "run_scan", _boom)
    called = []
    monkeypatch.setattr(bot.dbc, "latest_running_run", lambda: called.append(1))
    monkeypatch.setattr(bot.dbc, "release_run_lock", lambda: called.append(2))

    bot._busy.acquire()
    bot._run_scan_job({"firm": None, "dry": False, "days": None})  # returns, does not raise

    assert called == []  # the interrupt-only cleanup path never ran
    assert not bot._busy.locked()
