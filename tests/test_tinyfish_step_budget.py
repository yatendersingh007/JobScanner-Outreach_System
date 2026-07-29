"""LOCAL EDIT (2026-07-29) to scanner/connectors/tinyfish.py: per-group step
budgets (LinkedIn vs. specialist boards), an overall cap wiring the
previously-dead TINYFISH_STEP_CAP_PER_RUN, and a consecutive-failure abort.
Never a silent truncation -- every skip is recorded on
connector.skipped_targets with a reason.

No network: TinyFishConnector._run is monkeypatched directly, so fetch()'s
own request/poll/extract logic (byte-identical to the donor) is never
exercised here -- that's not what this file is testing.
"""
from __future__ import annotations

import requests

from scanner.connectors import tinyfish as tf


def _target(name, url="https://example.com/jobs"):
    return {"name": name, "url": url}


def _connector(targets, monkeypatch, run_fn=None, api_key="fake-key"):
    conn = tf.TinyFishConnector(api_key=api_key, targets=targets, titles=["fund accountant"])
    monkeypatch.setattr(conn, "_run", run_fn or (lambda url, goal: []))
    return conn


def setup_function(_):
    pass


def _patch_small_budgets(monkeypatch, linkedin=2, specialist=2, overall=200, consecutive=3):
    monkeypatch.setattr(tf, "LINKEDIN_MAX_STEPS", linkedin)
    monkeypatch.setattr(tf, "SPECIALIST_MAX_STEPS", specialist)
    monkeypatch.setattr(tf, "OVERALL_MAX_STEPS", overall)
    monkeypatch.setattr(tf, "MAX_CONSECUTIVE_FAILURES", consecutive)


def test_group_classification():
    assert tf.TinyFishConnector._group("LinkedIn US - Property Accountant") == "linkedin"
    assert tf.TinyFishConnector._group("LinkedIn Canada - Fund Accountant") == "linkedin"
    assert tf.TinyFishConnector._group("SelectLeaders - Fund Accountant") == "specialist"
    assert tf.TinyFishConnector._group("eFinancialCareers - Controller") == "specialist"


def test_no_api_key_skips_everything_without_recording_a_budget_skip(monkeypatch):
    _patch_small_budgets(monkeypatch)
    conn = tf.TinyFishConnector(api_key="", targets=[_target("LinkedIn US - A")], titles=[])
    jobs = conn.fetch()
    assert jobs == []
    assert conn.skipped_targets == []  # missing key is a different case, not a budget skip
    assert conn.steps_launched == 0


def test_linkedin_group_budget_binds_independently_of_specialist(monkeypatch):
    _patch_small_budgets(monkeypatch, linkedin=2, specialist=2)
    targets = [
        _target("LinkedIn US - Property Accountant"),
        _target("LinkedIn Canada - Property Accountant"),
        _target("LinkedIn US - Fund Accountant"),        # 3rd LinkedIn target, budget=2
        _target("SelectLeaders - Property Accountant"),   # specialist, budget still open
    ]
    conn = _connector(targets, monkeypatch)
    conn.fetch()

    assert conn.steps_launched == 3  # 2 LinkedIn + 1 specialist launched
    assert len(conn.skipped_targets) == 1
    assert conn.skipped_targets[0] == {
        "name": "LinkedIn US - Fund Accountant",
        "reason": "step_budget_exhausted:linkedin",
    }


def test_specialist_budget_binds_independently_of_linkedin(monkeypatch):
    _patch_small_budgets(monkeypatch, linkedin=2, specialist=2)
    targets = [
        _target("SelectLeaders - Property Accountant"),
        _target("eFinancialCareers - Property Accountant"),
        _target("SelectLeaders - Fund Accountant"),      # 3rd specialist, budget=2
        _target("LinkedIn US - Property Accountant"),     # linkedin, budget still open
    ]
    conn = _connector(targets, monkeypatch)
    conn.fetch()

    assert conn.steps_launched == 3
    assert len(conn.skipped_targets) == 1
    assert conn.skipped_targets[0]["reason"] == "step_budget_exhausted:specialist"
    assert conn.skipped_targets[0]["name"] == "SelectLeaders - Fund Accountant"


def test_overall_budget_binds_across_both_groups(monkeypatch):
    _patch_small_budgets(monkeypatch, linkedin=10, specialist=10, overall=2)
    targets = [
        _target("LinkedIn US - Property Accountant"),
        _target("SelectLeaders - Property Accountant"),
        _target("LinkedIn Canada - Property Accountant"),  # 3rd overall, cap=2
    ]
    conn = _connector(targets, monkeypatch)
    conn.fetch()

    assert conn.steps_launched == 2
    assert len(conn.skipped_targets) == 1
    assert conn.skipped_targets[0]["reason"] == "step_budget_exhausted:overall"


def test_skipped_targets_all_recorded_never_silently_dropped(monkeypatch):
    _patch_small_budgets(monkeypatch, linkedin=2, specialist=2)
    targets = [_target(f"LinkedIn US - Role {i}") for i in range(5)]
    conn = _connector(targets, monkeypatch)
    conn.fetch()

    assert conn.steps_launched == 2
    assert len(conn.skipped_targets) == 3
    assert [s["name"] for s in conn.skipped_targets] == [
        "LinkedIn US - Role 2", "LinkedIn US - Role 3", "LinkedIn US - Role 4",
    ]
    assert all(s["reason"] == "step_budget_exhausted:linkedin" for s in conn.skipped_targets)


def test_consecutive_failures_abort_remaining_targets(monkeypatch):
    _patch_small_budgets(monkeypatch, linkedin=10, specialist=10, consecutive=3)
    call_count = {"n": 0}

    def failing_run(url, goal):
        call_count["n"] += 1
        raise requests.RequestException("boom")

    targets = [_target(f"SelectLeaders - Role {i}") for i in range(5)]
    conn = _connector(targets, monkeypatch, run_fn=failing_run)
    conn.fetch()

    assert call_count["n"] == 3  # MAX_CONSECUTIVE_FAILURES, then it stops trying
    assert conn.steps_launched == 3  # attempts count as launched even though they failed
    aborted = [s for s in conn.skipped_targets if s["reason"] == "aborted_after_consecutive_failures"]
    assert len(aborted) == 2  # targets 3 and 4 never attempted
    assert [s["name"] for s in aborted] == ["SelectLeaders - Role 3", "SelectLeaders - Role 4"]


def test_a_success_between_failures_resets_the_consecutive_counter(monkeypatch):
    _patch_small_budgets(monkeypatch, linkedin=10, specialist=10, consecutive=3)
    calls = []

    def flaky_run(url, goal):
        calls.append(url)
        if len(calls) in (1, 2, 4, 5):
            raise requests.RequestException("boom")
        return []  # 3rd call succeeds, resetting the streak

    targets = [_target(f"SelectLeaders - Role {i}") for i in range(5)]
    conn = _connector(targets, monkeypatch, run_fn=flaky_run)
    conn.fetch()

    # Failures 1,2 (streak=2), success 3 (resets), failures 4,5 (streak=2) --
    # never reaches 3 in a row, so nothing is ever aborted.
    assert conn.steps_launched == 5
    assert conn.skipped_targets == []


def test_fetch_resets_state_on_every_call_not_accumulated(monkeypatch):
    _patch_small_budgets(monkeypatch, linkedin=2, specialist=2)
    targets = [_target(f"LinkedIn US - Role {i}") for i in range(3)]
    conn = _connector(targets, monkeypatch)

    conn.fetch()
    assert len(conn.skipped_targets) == 1

    conn.fetch()
    assert len(conn.skipped_targets) == 1  # not 2 -- reset, not accumulated
    assert conn.steps_launched == 2


def test_missing_url_target_is_not_a_budget_skip(monkeypatch):
    """Preserves the donor's original behavior for a malformed config entry
    (no url) -- silently continue, not part of the new budget/skip system."""
    _patch_small_budgets(monkeypatch, linkedin=2, specialist=2)
    targets = [_target("LinkedIn US - Missing URL", url=None),
              _target("LinkedIn US - Real Target")]
    conn = _connector(targets, monkeypatch)
    conn.fetch()

    assert conn.steps_launched == 1
    assert conn.skipped_targets == []
