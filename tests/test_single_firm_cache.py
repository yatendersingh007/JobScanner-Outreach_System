"""run_single_firm() takes the verdict cache, and `fresh` deliberately skips it.

`/scan "Firm"` used to go straight to gate_group(), so every invocation
re-researched from scratch: 6 Tavily searches and a fresh chance at a different
answer. Live evidence, Choice NY, all on 2026-07-31:

    id 65  run 25  batch        gated      qualified  $250M
    id 66  run 27  batch        cached_wd  qualified  $250M   (cached from 65)
    id 83  run 29  SINGLE-FIRM  gated      parked     no figure

Run 29 was a single-firm run. The cache would have hit on 65 and returned
qualified; instead it re-gated and parked, leaving two contradictory verdicts.

No live Postgres here (see tests/test_wd_dbc.py's docstring): every dbc call is
monkeypatched, gate_group is replaced with a counter so "did this cost a gate"
is directly observable, and _reuse_cached is exercised for real against the fake
so the row it writes is inspectable.
"""
from __future__ import annotations

import pytest

from src import run_scan, signal_pipeline
from src.run_scan import run_single_firm


def _noop(_: str) -> None:
    return None


CACHED_ROW = {
    "id": 65,
    "firm_name": "Choice NY Property Management LLC",
    "icp_status": "qualified",
    "icp_reason": "QUALIFIED (est. $250M, portfolio value proxy)",
    "aum_tag": "AUM_ESTIMATED",
    "research": {"firm_oneliner": "Residential and mixed-use property management",
                 "aum_value_usd": 250000000, "disclosed_figure": "$250 million"},
    "decided_at": "2026-07-31T10:00:00Z",
    "src": "cached_wd",
}


class _FakeDb:
    RunAlreadyInProgress = RuntimeError

    def __init__(self, cached=None):
        self.cached = cached
        self.rows = []
        self.lookups = []
        self.released = 0
        self._next_id = 200

    # lock
    def acquire_run_lock(self):
        return True

    def release_run_lock(self):
        self.released += 1

    # run
    def create_wd_run(self, mode, recency_days_used=1):
        return {"id": 40, "mode": mode}

    def update_wd_run(self, run_id, **fields):
        return None

    # cache
    def verdict_cache_lookup(self, name, window_days):
        self.lookups.append((name, window_days))
        return dict(self.cached) if self.cached else None

    # firm rows: _reuse_cached and gate_group both land here
    def create_wd_firm(self, run_id, firm_name, **fields):
        row = {"id": self._next_id, "run_id": run_id, "firm_name": firm_name, **fields}
        self._next_id += 1
        self.rows.append(row)
        return dict(row)

    def insert_postings(self, run_id, firm_id, rows):
        return len(rows)

    def firm_key(self, name):
        return (name or "").strip().lower()


def _wire(monkeypatch, cached=None, gate_verdict="parked"):
    db = _FakeDb(cached)
    monkeypatch.setattr(signal_pipeline, "dbc", db)
    monkeypatch.setattr(signal_pipeline, "_now", lambda: "2026-08-02T00:00:00Z")
    monkeypatch.setattr(signal_pipeline, "_apply_draft_cap_fields", lambda r: None)
    monkeypatch.setattr(run_scan, "_run_drafting", lambda r, p: None)
    monkeypatch.setattr(run_scan, "_apply_blocklist_maintenance", lambda r, p: None)
    monkeypatch.setattr(run_scan.config, "REGATE_WINDOW_DAYS", 7)

    gate_calls = []

    def fake_gate_group(run_id, group, progress, existing_firm=None):
        gate_calls.append(group.firm_name)
        row = db.create_wd_firm(run_id, group.firm_name, firm_key=group.firm_key,
                                icp_status=gate_verdict, verdict_source="gated")
        return {**row, "_search_calls": 6, "_tokens_used": 1200,
                "_research_cost_usd": 0.02}

    monkeypatch.setattr(signal_pipeline, "gate_group", fake_gate_group)
    return db, gate_calls


# ---------------------------------------------------------------------------
# Cache hit: no gate, no searches
# ---------------------------------------------------------------------------
def test_a_cached_firm_returns_the_cached_verdict_at_zero_gate_cost(monkeypatch):
    db, gate_calls = _wire(monkeypatch, cached=CACHED_ROW)

    result = run_single_firm(mode="manual", firm_name="Choice NY Property Management LLC",
                            dry=True, progress=_noop)

    assert gate_calls == []                       # gate never called
    assert result.tavily_searches == 0
    assert result.llm_tokens == 0
    assert result.research_cost_usd == 0.0
    assert len(result.qualified) == 1
    assert result.qualified[0]["icp_status"] == "qualified"


def test_the_cache_is_consulted_with_the_same_window_the_batch_path_uses(monkeypatch):
    db, _gate = _wire(monkeypatch, cached=CACHED_ROW)

    run_single_firm(mode="manual", firm_name="Acme Capital", dry=True, progress=_noop)

    assert db.lookups == [("Acme Capital", 7)]    # config.REGATE_WINDOW_DAYS


def test_a_reused_verdict_is_written_the_same_way_the_batch_path_writes_it(monkeypatch):
    """Same _reuse_cached() writer, so provenance is identical from either front
    door: verdict_source from the cache row and verdict_cached_from pointing at
    the row it came from."""
    db, _gate = _wire(monkeypatch, cached=CACHED_ROW)

    run_single_firm(mode="manual", firm_name="Choice NY Property Management LLC",
                    dry=True, progress=_noop)

    row = db.rows[0]
    assert row["verdict_source"] == "cached_wd"
    assert row["verdict_cached_from"] == 65
    assert row["icp_status"] == "qualified"
    assert row["icp_reason"] == CACHED_ROW["icp_reason"]
    assert row["aum_tag"] == "AUM_ESTIMATED"
    assert row["research"] == CACHED_ROW["research"]
    assert row["gated_at"] == CACHED_ROW["decided_at"]


def test_a_reused_verdict_counts_as_a_known_firm_not_a_new_gate(monkeypatch):
    db, _gate = _wire(monkeypatch, cached=CACHED_ROW)

    result = run_single_firm(mode="manual", firm_name="Acme Capital", dry=True,
                            progress=_noop)

    assert len(result.skipped_known) == 1
    assert result.skipped_known[0]["verdict_source"] == "cached_wd"


def test_a_cached_disqualified_verdict_lands_in_the_disqualified_bucket(monkeypatch):
    cached = {**CACHED_ROW, "icp_status": "disqualified",
              "icp_reason": "Not an accepted firm type", "src": "cached_wc"}
    _db, gate_calls = _wire(monkeypatch, cached=cached)

    result = run_single_firm(mode="manual", firm_name="Colliers", dry=True, progress=_noop)

    assert gate_calls == []
    assert len(result.disqualified) == 1
    assert result.qualified == []


def test_the_operator_is_told_the_verdict_was_reused_and_how_to_re_gate(monkeypatch):
    _db, _gate = _wire(monkeypatch, cached=CACHED_ROW)
    messages = []

    run_single_firm(mode="manual", firm_name="Choice NY", dry=True,
                    progress=messages.append)

    joined = " | ".join(messages)
    assert "reusing the qualified verdict" in joined
    assert "No searches spent" in joined
    assert "fresh" in joined                      # names the escape hatch


# ---------------------------------------------------------------------------
# Cache miss and fresh: gate runs
# ---------------------------------------------------------------------------
def test_a_cache_miss_gates_as_before(monkeypatch):
    _db, gate_calls = _wire(monkeypatch, cached=None, gate_verdict="qualified")

    result = run_single_firm(mode="manual", firm_name="Acme Capital", dry=True,
                            progress=_noop)

    assert gate_calls == ["Acme Capital"]
    assert result.tavily_searches == 6
    assert len(result.qualified) == 1


def test_fresh_skips_the_cache_and_re_gates(monkeypatch):
    """The escape hatch: without it, wiring the cache in would make a bad
    cached verdict unfixable until it expired."""
    db, gate_calls = _wire(monkeypatch, cached=CACHED_ROW, gate_verdict="parked")

    result = run_single_firm(mode="manual", firm_name="Choice NY Property Management LLC",
                            dry=True, fresh=True, progress=_noop)

    assert db.lookups == []                       # never even asked the cache
    assert gate_calls == ["Choice NY Property Management LLC"]
    assert result.tavily_searches == 6
    assert len(result.parked) == 1


def test_fresh_says_so_in_the_progress_line(monkeypatch):
    _db, _gate = _wire(monkeypatch, cached=CACHED_ROW)
    messages = []

    run_single_firm(mode="manual", firm_name="Acme Capital", dry=True, fresh=True,
                    progress=messages.append)

    assert any("cache skipped" in m for m in messages)


def test_a_parked_firm_always_re_gates_because_parks_are_never_cached(monkeypatch):
    """verdict_cache_lookup's own rule: only qualified/disqualified are cached,
    because a park means the research was inconclusive. So the park half of the
    Choice NY conflict could never have been served from the cache -- only
    prevented by the qualified row being reused instead."""
    _db, gate_calls = _wire(monkeypatch, cached=None, gate_verdict="parked")

    result = run_single_firm(mode="manual", firm_name="Beyond International Group",
                            dry=True, progress=_noop)

    assert gate_calls == ["Beyond International Group"]
    assert len(result.parked) == 1


# ---------------------------------------------------------------------------
# Provenance: a reused row and a re-gated row are distinguishable
# ---------------------------------------------------------------------------
def test_reused_and_regated_rows_carry_distinct_verdict_source_values(monkeypatch):
    """The Choice NY conflict is only diagnosable because 66 says cached_wd and
    83 says gated. Two runs over the same firm must stay tellable apart."""
    db, _gate = _wire(monkeypatch, cached=CACHED_ROW, gate_verdict="parked")

    run_single_firm(mode="manual", firm_name="Choice NY", dry=True, progress=_noop)
    run_single_firm(mode="manual", firm_name="Choice NY", dry=True, fresh=True,
                    progress=_noop)

    sources = [r["verdict_source"] for r in db.rows]
    assert sources == ["cached_wd", "gated"]
    assert len({s for s in sources}) == 2
    assert db.rows[0]["verdict_cached_from"] == 65
    assert db.rows[1].get("verdict_cached_from") is None


def test_the_lock_is_released_on_both_paths(monkeypatch):
    db, _gate = _wire(monkeypatch, cached=CACHED_ROW)
    run_single_firm(mode="manual", firm_name="Acme", dry=True, progress=_noop)
    run_single_firm(mode="manual", firm_name="Acme", dry=True, fresh=True, progress=_noop)

    assert db.released == 2


# ---------------------------------------------------------------------------
# /scan argument parsing
# ---------------------------------------------------------------------------
def test_parse_scan_args_accepts_fresh_after_a_quoted_firm():
    from src import bot

    assert bot.parse_scan_args('"Acme Capital" fresh') == {
        "firm": "Acme Capital", "dry": False, "days": None, "stop": False, "fresh": True}


def test_parse_scan_args_accepts_dry_and_fresh_together():
    from src import bot

    parsed = bot.parse_scan_args('"Acme Capital" dry fresh')
    assert parsed["dry"] is True and parsed["fresh"] is True


def test_parse_scan_args_defaults_fresh_to_false():
    from src import bot

    for text in ("", "dry", "days 3", '"Acme Capital"'):
        assert bot.parse_scan_args(text)["fresh"] is False


def test_parse_scan_args_rejects_fresh_on_a_batch_run():
    """A batch run relies on the cache to be affordable, so there is nothing to
    skip. Rejected loudly rather than silently ignored."""
    from src import bot

    with pytest.raises(ValueError, match="only applies to a single firm"):
        bot.parse_scan_args("fresh")


def test_parse_scan_args_still_rejects_unknown_text_after_a_firm():
    from src import bot

    with pytest.raises(ValueError, match="Unrecognized text after the firm name"):
        bot.parse_scan_args('"Acme Capital" bogus')


def test_scan_quoted_fresh_is_treated_as_a_command_fragment_not_a_firm():
    from src import bot

    with pytest.raises(ValueError, match="looks like a leftover /scan option"):
        bot.parse_scan_args('"fresh"')


def test_the_bot_threads_fresh_through_to_run_single_firm(monkeypatch):
    from src import bot

    captured = {}
    monkeypatch.setattr(bot, "run_single_firm",
                        lambda **kw: captured.update(kw) or _Result())
    monkeypatch.setattr(bot.tg, "send", lambda text, chat_id=None: None)
    monkeypatch.setattr(bot.tg, "reset_live", lambda: None)
    monkeypatch.setattr(bot.tg, "finish", lambda *a, **k: None)
    monkeypatch.setattr(bot, "summarize", lambda r, dry_hint="": "")

    # _run_scan_job releases _busy in its finally, exactly as _handle_scan
    # acquires it before spawning the thread.
    bot._busy.acquire(blocking=False)
    bot._run_scan_job({"firm": "Acme Capital", "dry": True, "days": None,
                      "stop": False, "fresh": True})

    assert captured["fresh"] is True
    assert captured["firm_name"] == "Acme Capital"


class _Result:
    run_id = 1
    cancelled = False
    qualified: list = []
    dry = True
