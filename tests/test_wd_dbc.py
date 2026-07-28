"""wd_dbc.latest_running_run(): without a filter that actually excludes
done/crashed/cancelled rows, /cancel would find a FINISHED run, set
cancel_requested_at on it, report success to the operator, and change
nothing -- there is no per-firm loop left on a finished run to ever read the
flag back.

No live Postgres in this environment: `cursor()` is monkeypatched with an
in-memory fake that inspects the literal SQL string for the `status =
'running'` filter and applies it to an in-memory row list, then sorts by id
descending -- mirroring the real query's WHERE + ORDER BY id DESC LIMIT 1.
This is not a substitute for a real integration test against Postgres, but
it does catch the specific regression class this test exists for: a future
edit that loosens or drops the status filter.
"""
from __future__ import annotations

from contextlib import contextmanager

from src import wd_dbc


class _FakeWdRunsCursor:
    def __init__(self, rows):
        self._all_rows = rows
        self._result = None

    def execute(self, sql, params=None):
        if "status = 'running'" in sql:
            filtered = [r for r in self._all_rows if r["status"] == "running"]
        else:
            filtered = list(self._all_rows)
        filtered.sort(key=lambda r: r["id"], reverse=True)
        self._result = filtered[0] if filtered else None

    def fetchone(self):
        return self._result


@contextmanager
def _fake_cursor(rows):
    yield _FakeWdRunsCursor(rows)


def test_latest_running_run_ignores_done_crashed_cancelled(monkeypatch):
    rows = [
        {"id": 1, "status": "done"},
        {"id": 2, "status": "crashed"},
        {"id": 3, "status": "cancelled"},
        {"id": 4, "status": "running"},
    ]
    monkeypatch.setattr(wd_dbc, "cursor", lambda: _fake_cursor(rows))

    result = wd_dbc.latest_running_run()

    assert result == {"id": 4, "status": "running"}


def test_latest_running_run_returns_none_when_nothing_running(monkeypatch):
    rows = [{"id": 1, "status": "done"}, {"id": 2, "status": "cancelled"}, {"id": 3, "status": "crashed"}]
    monkeypatch.setattr(wd_dbc, "cursor", lambda: _fake_cursor(rows))

    assert wd_dbc.latest_running_run() is None


def test_latest_running_run_picks_the_most_recent_running_row(monkeypatch):
    rows = [
        {"id": 1, "status": "running"},
        {"id": 5, "status": "running"},
        {"id": 3, "status": "done"},
    ]
    monkeypatch.setattr(wd_dbc, "cursor", lambda: _fake_cursor(rows))

    result = wd_dbc.latest_running_run()

    assert result["id"] == 5
