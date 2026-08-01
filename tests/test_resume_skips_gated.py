"""/resume must not re-gate a firm this run already decided.

Live evidence, run 32: the run crashed mid-gate and the resume produced a
SECOND wd_firms row for every firm the first attempt had already gated --
colliers 87/122, abc imaging 88/123, executive alliance 89/124, eisneramper
90/125 -- at roughly 6 Tavily searches each.

Root cause, confirmed in the data rather than inferred: wd_queue is the
resume's only source of work, and signal_pipeline.run() calls dbc.enqueue()
once (line 627) and NEVER calls set_queue_status. So after a crash every
enqueued row is still 'pending', including the firms already gated, and
next_pending() handed them all back. run 32's queue held 12 rows, all
pending, for 4 already-gated firms plus 8 never-reached ones.

The verdict on the wd_firms row, not the queue's status, is the authority on
whether a firm still needs gating: a non-NULL icp_status means decided, NULL
means the process died mid-gate.

No live Postgres here (see tests/test_wd_dbc.py's docstring): every dbc call
run_resume makes is monkeypatched, and gate_group is replaced with a counter so
"did this cost a gate" is directly observable.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from src import run_scan, signal_pipeline
from src.run_scan import run_resume


def _noop(_: str) -> None:
    return None


class _FakeDb:
    """Just enough of wd_dbc for run_resume, with the state it mutates
    observable afterwards."""

    def __init__(self, firms, queue):
        self.firms = [dict(f) for f in firms]
        self.queue = [dict(q) for q in queue]
        self.run_updates = []
        self.released = 0
        self._next_id = max([f["id"] for f in self.firms], default=100) + 1

    # --- lock ---
    def acquire_run_lock(self):
        return True

    def release_run_lock(self):
        self.released += 1

    # --- run ---
    def latest_resumable_run(self):
        return {"id": 32, "recency_days_used": 1}

    def update_wd_run(self, run_id, **fields):
        self.run_updates.append(fields)

    def cancel_requested(self, run_id):
        return False

    # --- firms / queue ---
    def firms_for_run(self, run_id):
        return [dict(f) for f in self.firms]

    def next_pending(self, run_id, limit):
        return [dict(q) for q in self.queue if q["status"] == "pending"][:limit]

    def set_queue_status(self, queue_id, status, firm_id=None):
        for q in self.queue:
            if q["id"] == queue_id:
                q["status"] = status
                if firm_id is not None:
                    q["firm_id"] = firm_id

    # --- what gate_group would do ---
    def create_firm_row(self, firm_key, firm_name, status):
        row = {"id": self._next_id, "run_id": 32, "firm_key": firm_key,
               "firm_name": firm_name, "icp_status": status, "posting_count": 0}
        self._next_id += 1
        self.firms.append(row)
        return row

    def firm_by_id(self, fid):
        return next(f for f in self.firms if f["id"] == fid)

    def update_firm_row(self, fid, **fields):
        self.firm_by_id(fid).update(fields)

    def duplicate_key_pairs(self):
        seen, dupes = {}, []
        for f in self.firms:
            key = (f["run_id"], f["firm_key"])
            seen[key] = seen.get(key, 0) + 1
        return [k for k, n in seen.items() if n > 1]


def _wire(monkeypatch, firms, queue, verdict="disqualified"):
    """Returns (fake_db, gate_calls). gate_calls records one entry per firm
    actually gated, with the existing_firm it was handed."""
    db = _FakeDb(firms, queue)
    monkeypatch.setattr(signal_pipeline, "dbc", db)
    monkeypatch.setattr(signal_pipeline, "_now", lambda: "2026-08-15T00:00:00Z")
    monkeypatch.setattr(signal_pipeline, "_apply_draft_cap_fields", lambda result: None)
    monkeypatch.setattr(run_scan, "_run_drafting", lambda result, progress: None)
    monkeypatch.setattr(run_scan.config, "GATE_CAP_PER_RUN", 25)

    gate_calls = []

    def fake_gate_group(run_id, group, progress, existing_firm=None):
        gate_calls.append({"firm_key": group.firm_key, "existing_firm": existing_firm})
        if existing_firm is not None:
            # firms_for_run() hands back detached rows, as a real SELECT does,
            # so the write goes to the authoritative row by id -- what
            # update_wd_firm does inside the real gate_group.
            db.update_firm_row(existing_firm["id"], icp_status=verdict)
            return {**db.firm_by_id(existing_firm["id"]), "_search_calls": 6}
        row = db.create_firm_row(group.firm_key, group.firm_name, verdict)
        return {**row, "_search_calls": 6}

    monkeypatch.setattr(signal_pipeline, "gate_group", fake_gate_group)
    return db, gate_calls


def _firm(fid, key, status):
    return {"id": fid, "run_id": 32, "firm_key": key, "firm_name": key.title(),
            "icp_status": status, "posting_count": 1}


def _q(qid, key):
    return {"id": qid, "run_id": 32, "firm_key": key, "firm_name": key.title(),
            "status": "pending", "firm_id": None}


# ---------------------------------------------------------------------------
# The run-32 shape: 4 firms already gated, 1 of them NULL, 8 never reached.
# ---------------------------------------------------------------------------
_RUN32_FIRMS = [
    _firm(86, "jpmorgan chase", "disqualified"),     # verdict-cache hit, never enqueued
    _firm(87, "colliers", "disqualified"),
    _firm(88, "abc imaging", "disqualified"),
    _firm(89, "executive alliance", "disqualified"),
    _firm(90, "eisneramper", None),                  # in flight when the process died
]
_RUN32_QUEUE = [
    _q(53, "colliers"), _q(54, "abc imaging"), _q(55, "executive alliance"),
    _q(56, "eisneramper"), _q(57, "nichols contracting"), _q(58, "pridestaff"),
    _q(59, "corient"), _q(60, "blue origin"), _q(61, "aston carter"),
    _q(62, "profile products"), _q(63, "w3global"), _q(64, "cpa firm"),
]


def test_resume_gates_only_the_null_status_firms_and_the_never_reached_ones(monkeypatch):
    db, gate_calls = _wire(monkeypatch, _RUN32_FIRMS, _RUN32_QUEUE)

    run_resume(dry=True, progress=_noop)

    gated = [c["firm_key"] for c in gate_calls]
    # the three already-decided firms are NOT re-gated
    for decided in ("colliers", "abc imaging", "executive alliance"):
        assert decided not in gated
    # the NULL one is, plus the eight never reached
    assert "eisneramper" in gated
    assert len(gated) == 9


def test_resume_does_not_create_duplicate_run_id_firm_key_pairs(monkeypatch):
    db, _ = _wire(monkeypatch, _RUN32_FIRMS, _RUN32_QUEUE)

    run_resume(dry=True, progress=_noop)

    assert db.duplicate_key_pairs() == []


def test_resume_regates_the_null_firm_in_place_not_as_a_new_row(monkeypatch):
    """The NULL row owns the run's posting_count and the wd_postings rows point
    at its id, so a replacement row would orphan them. Live proof this matters:
    every row the run-32 resume created had posting_count=0 and zero linked
    postings."""
    db, gate_calls = _wire(monkeypatch, _RUN32_FIRMS, _RUN32_QUEUE)

    run_resume(dry=True, progress=_noop)

    eisner = next(c for c in gate_calls if c["firm_key"] == "eisneramper")
    assert eisner["existing_firm"] is not None
    assert eisner["existing_firm"]["id"] == 90

    rows = [f for f in db.firms if f["firm_key"] == "eisneramper"]
    assert len(rows) == 1
    assert rows[0]["id"] == 90                  # same row, updated
    assert rows[0]["icp_status"] == "disqualified"
    assert rows[0]["posting_count"] == 1        # its postings link survives


def test_resume_passes_no_existing_firm_for_a_never_reached_firm(monkeypatch):
    """A firm with no wd_firms row at all still takes the normal create path."""
    _db, gate_calls = _wire(monkeypatch, _RUN32_FIRMS, _RUN32_QUEUE)

    run_resume(dry=True, progress=_noop)

    fresh = next(c for c in gate_calls if c["firm_key"] == "nichols contracting")
    assert fresh["existing_firm"] is None


def test_a_fully_gated_run_resumes_to_zero_gate_calls(monkeypatch):
    """Every enqueued firm already has a verdict: the resume must spend
    nothing."""
    firms = [_firm(87, "colliers", "disqualified"),
             _firm(88, "abc imaging", "parked"),
             _firm(89, "executive alliance", "qualified")]
    queue = [_q(53, "colliers"), _q(54, "abc imaging"), _q(55, "executive alliance")]
    db, gate_calls = _wire(monkeypatch, firms, queue)

    result = run_resume(dry=True, progress=_noop)

    assert gate_calls == []
    assert result.tavily_searches == 0
    assert db.duplicate_key_pairs() == []


def test_resume_marks_the_skipped_queue_rows_done(monkeypatch):
    """Left 'pending', they would be handed back again on the next resume and
    the same waste would repeat."""
    db, _ = _wire(monkeypatch, _RUN32_FIRMS, _RUN32_QUEUE)

    run_resume(dry=True, progress=_noop)

    assert [q["status"] for q in db.queue] == ["done"] * len(db.queue)


def test_resume_reports_how_many_it_skipped(monkeypatch):
    _db, _ = _wire(monkeypatch, _RUN32_FIRMS, _RUN32_QUEUE)
    messages = []

    run_resume(dry=True, progress=messages.append)

    assert any("already have a verdict for this run, not re-gating" in m for m in messages)
    assert any("3 firm(s)" in m for m in messages)


def test_already_decided_firms_still_count_toward_the_summary(monkeypatch):
    """Skipping them must not lose them from the run's own totals."""
    _db, _ = _wire(monkeypatch, _RUN32_FIRMS, _RUN32_QUEUE)

    result = run_resume(dry=True, progress=_noop)

    keys = {f["firm_key"] for f in result.disqualified}
    assert {"jpmorgan chase", "colliers", "abc imaging", "executive alliance"} <= keys


def test_skipped_firms_do_not_consume_the_gate_cap(monkeypatch):
    """Reconciliation happens BEFORE the cap is applied. With a cap of 2 and
    three already-decided firms, the resume must still reach the undecided
    ones rather than spending its whole budget re-deciding."""
    db, gate_calls = _wire(monkeypatch, _RUN32_FIRMS, _RUN32_QUEUE)
    monkeypatch.setattr(run_scan.config, "GATE_CAP_PER_RUN", 2)

    result = run_resume(dry=True, progress=_noop)

    assert [c["firm_key"] for c in gate_calls] == ["eisneramper", "nichols contracting"]
    assert len(result.deferred) == 7      # the remaining never-reached firms
    assert db.duplicate_key_pairs() == []


def test_resume_with_an_empty_queue_gates_nothing(monkeypatch):
    db, gate_calls = _wire(monkeypatch, _RUN32_FIRMS, [])

    result = run_resume(dry=True, progress=_noop)

    assert gate_calls == []
    assert result.deferred == []


def test_gate_group_default_still_creates_a_row(monkeypatch):
    """existing_firm defaults to None, so signal_pipeline.run()'s own call site
    is unchanged."""
    created = {}
    monkeypatch.setattr(signal_pipeline.dbc, "create_wd_firm",
                        lambda run_id, firm_name, **f: created.setdefault(
                            "row", {"id": 1, "run_id": run_id, "firm_name": firm_name, **f}))
    monkeypatch.setattr(signal_pipeline.dbc, "insert_postings",
                        lambda run_id, firm_id, rows: created.setdefault("postings", len(rows)))
    monkeypatch.setattr(signal_pipeline.dbc, "update_wd_firm", lambda fid, **f: None)
    monkeypatch.setattr(signal_pipeline.dbc, "get_wd_firm",
                        lambda fid: {"id": fid, "icp_status": "parked"})
    monkeypatch.setattr(signal_pipeline, "_now", lambda: "t")

    from lib_referral import icp_gate
    monkeypatch.setattr(icp_gate, "research_and_gate",
                        lambda firm_name, progress: icp_gate.GateResult(
                            icp_result="disqualified", icp_reason="no"))

    group = signal_pipeline.FirmGroup(firm_name="Acme Capital", firm_key="acme capital")
    signal_pipeline.gate_group(1, group, _noop)

    assert created["row"]["firm_name"] == "Acme Capital"
    assert created["postings"] == 0


def test_gate_group_with_existing_firm_skips_create_and_postings(monkeypatch):
    calls = []
    monkeypatch.setattr(signal_pipeline.dbc, "create_wd_firm",
                        lambda *a, **k: calls.append("create"))
    monkeypatch.setattr(signal_pipeline.dbc, "insert_postings",
                        lambda *a, **k: calls.append("insert_postings"))
    monkeypatch.setattr(signal_pipeline.dbc, "update_wd_firm", lambda fid, **f: None)
    monkeypatch.setattr(signal_pipeline.dbc, "get_wd_firm",
                        lambda fid: {"id": fid, "icp_status": "disqualified"})
    monkeypatch.setattr(signal_pipeline, "_now", lambda: "t")

    from lib_referral import icp_gate
    monkeypatch.setattr(icp_gate, "research_and_gate",
                        lambda firm_name, progress: icp_gate.GateResult(
                            icp_result="disqualified", icp_reason="no"))

    group = signal_pipeline.FirmGroup(firm_name="EisnerAmper", firm_key="eisneramper")
    row = signal_pipeline.gate_group(1, group, _noop,
                                     existing_firm={"id": 90, "posting_count": 1})

    assert calls == []            # neither a new row nor a second posting insert
    assert row["id"] == 90
