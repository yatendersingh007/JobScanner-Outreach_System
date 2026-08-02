"""/parked: the worklist of firms waiting on a human decision.

A park is the one verdict that stalls until someone acts, and until now the
only way to see one was to still have the run summary in the chat. Nothing
here touches Postgres: dbc.parked_firms_recent is monkeypatched, and the
handler is called through the real router so the routing is covered too.
"""
from __future__ import annotations

import pytest

from src import bot


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(bot.tg, "send", lambda text, chat_id=None: out.append(text))
    return out


def _firm(i, reason="aum_unverified", name=None, run=39, **over):
    return {"id": i, "firm_name": name or f"Firm {i}", "run_id": run,
            "icp_status": "parked", "park_reason": reason,
            "icp_reason": "gate reason", **over}


def _wire(monkeypatch, rows, total=None):
    total = len(rows) if total is None else total
    monkeypatch.setattr(bot.dbc, "parked_firms_recent", lambda limit: (rows[:limit], total))


# ---------------------------------------------------------------------------
# Empty, one, more than the cap.
# ---------------------------------------------------------------------------
def test_empty_says_so_plainly(monkeypatch, sent):
    _wire(monkeypatch, [])

    bot._dispatch("/parked")

    assert sent == ["No parked firms."]


def test_one_parked_firm_lists_name_reason_and_run(monkeypatch, sent):
    _wire(monkeypatch, [_firm(143, name="The Greenbrier Hotel", run=39)])

    bot._dispatch("/parked")

    lines = sent[0].splitlines()
    assert lines[0] == "PARKED 1:"
    assert lines[1] == "  The Greenbrier Hotel, aum_unverified (run 39)"
    assert "...and" not in sent[0], "nothing is being withheld"


def test_more_than_the_cap_shows_fifteen_and_counts_the_rest(monkeypatch, sent):
    _wire(monkeypatch, [_firm(i) for i in range(40, 0, -1)])

    bot._dispatch("/parked")

    lines = sent[0].splitlines()
    assert lines[0] == "PARKED 40, showing the 15 most recent:"
    firm_lines = [ln for ln in lines if ln.startswith("  Firm ")]
    assert len(firm_lines) == 15
    assert "  ...and 25 more" in lines


def test_exactly_the_cap_has_no_tail(monkeypatch, sent):
    """The boundary: 15 is complete, 16 is not."""
    _wire(monkeypatch, [_firm(i) for i in range(15, 0, -1)])

    bot._dispatch("/parked")

    assert sent[0].splitlines()[0] == "PARKED 15:"
    assert "...and" not in sent[0]


def test_one_over_the_cap_has_a_tail_of_one(monkeypatch, sent):
    _wire(monkeypatch, [_firm(i) for i in range(16, 0, -1)])

    bot._dispatch("/parked")

    assert "  ...and 1 more" in sent[0].splitlines()


# ---------------------------------------------------------------------------
# Ordering and the cap reaching the query.
# ---------------------------------------------------------------------------
def test_the_cap_is_pushed_into_the_query_not_applied_after(monkeypatch, sent):
    """Slicing in Python would fetch every parked row to show 15 of them."""
    seen = {}

    def fake(limit):
        seen["limit"] = limit
        return [_firm(i) for i in range(3)], 3

    monkeypatch.setattr(bot.dbc, "parked_firms_recent", fake)
    bot._dispatch("/parked")

    assert seen["limit"] == bot._PARKED_LIST_CAP == 15


def test_rows_are_listed_in_the_order_the_query_returned_them(monkeypatch, sent):
    """Newest first is the query's ORDER BY id DESC. The handler must not
    re-sort and quietly undo it."""
    _wire(monkeypatch, [_firm(143, name="Newest"), _firm(79, name="Middle"),
                        _firm(12, name="Oldest")])

    bot._dispatch("/parked")

    names = [ln.split(",")[0].strip() for ln in sent[0].splitlines() if ln.startswith("  ")]
    assert names[:3] == ["Newest", "Middle", "Oldest"]


# ---------------------------------------------------------------------------
# One firm, one line.
# ---------------------------------------------------------------------------
LONG_REASON = (
    "no structure signal in the research: no fund or GP language, no LP reference, "
    "no third-party capital management, no AUM or portfolio-value figure, and no "
    'managed property portfolio. Self-description: "Homebuilder in southwest Florida".')


def test_a_prose_park_reason_is_truncated(monkeypatch, sent):
    """The post-gate parks write paragraphs. Fifteen of those is a wall."""
    _wire(monkeypatch, [_firm(1, reason=LONG_REASON, name="Neal Communities")])

    bot._dispatch("/parked")

    line = [ln for ln in sent[0].splitlines() if "Neal" in ln][0]
    assert line.endswith("(run 39)")
    assert "..." in line
    assert len(line) < 140, line
    assert line.startswith("  Neal Communities, no structure signal in the research")


def test_a_multiline_reason_collapses_onto_one_line(monkeypatch, sent):
    _wire(monkeypatch, [_firm(1, reason="parked because\n  the gate\n  said so")])

    bot._dispatch("/parked")

    body = [ln for ln in sent[0].splitlines() if ln.startswith("  Firm 1")]
    assert len(body) == 1
    assert body[0] == "  Firm 1, parked because the gate said so (run 39)"


def test_a_short_reason_is_left_alone(monkeypatch, sent):
    _wire(monkeypatch, [_firm(1, reason="firm_identity_ambiguous")])

    bot._dispatch("/parked")

    assert "  Firm 1, firm_identity_ambiguous (run 39)" in sent[0].splitlines()


def test_every_line_stays_within_one_line(monkeypatch, sent):
    _wire(monkeypatch, [_firm(i, reason=LONG_REASON) for i in range(20, 0, -1)])

    bot._dispatch("/parked")

    lines = sent[0].splitlines()
    assert len(lines) == 1 + 15 + 1 + 1, "header, 15 firms, the tail, the hint"
    assert all(len(ln) < 140 for ln in lines)


# ---------------------------------------------------------------------------
# Falling back rather than showing a blank.
# ---------------------------------------------------------------------------
def test_it_falls_back_to_icp_reason(monkeypatch, sent):
    """summarize() falls back the same way. An infrastructure park sets
    park_reason, but a row that predates park_source has only icp_reason."""
    _wire(monkeypatch, [_firm(1, park_reason=None, icp_reason="aum_unverified")])

    bot._dispatch("/parked")

    assert "  Firm 1, aum_unverified (run 39)" in sent[0].splitlines()


def test_a_row_with_no_reason_at_all_says_so(monkeypatch, sent):
    _wire(monkeypatch, [_firm(1, park_reason=None, icp_reason=None)])

    bot._dispatch("/parked")

    assert "  Firm 1, no reason recorded (run 39)" in sent[0].splitlines()


def test_a_row_with_no_name_does_not_render_none(monkeypatch, sent):
    _wire(monkeypatch, [_firm(1, firm_name=None)])

    bot._dispatch("/parked")

    assert "None," not in sent[0]
    assert "  unnamed firm, aum_unverified (run 39)" in sent[0].splitlines()


# ---------------------------------------------------------------------------
# It is a worklist, so it says what to do next; and it never crashes the bot.
# ---------------------------------------------------------------------------
def test_the_list_points_at_the_two_actions(monkeypatch, sent):
    _wire(monkeypatch, [_firm(1)])

    bot._dispatch("/parked")

    assert sent[0].splitlines()[-1] == (
        '/qualify "Firm" <AUM> to rescue, /disqualify "Firm" to reject.')


def test_no_action_hint_when_there_is_nothing_to_act_on(monkeypatch, sent):
    _wire(monkeypatch, [])

    bot._dispatch("/parked")

    assert "/qualify" not in sent[0]


def test_a_database_failure_is_reported_not_raised(monkeypatch, sent):
    """Same shape as /blocklist: a handler must never take the poll loop down."""
    def boom(limit):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(bot.dbc, "parked_firms_recent", boom)

    bot._dispatch("/parked")

    assert sent == ["Could not read the parked firms (RuntimeError: connection refused)."]


# ---------------------------------------------------------------------------
# Routing and /help.
# ---------------------------------------------------------------------------
def test_the_command_is_in_the_help_text():
    assert "/parked " in bot._help_text()


def test_help_still_lists_every_other_command():
    help_text = bot._help_text()
    for cmd in ("/scan  ", "/scan dry", "/scan days N", "/status", "/parked",
                "/qualify", "/disqualify", "/cancel", "/resume", "/block ",
                "/unblock ", "/blocklist", "/help"):
        assert cmd in help_text, f"{cmd} disappeared from /help"


def test_parked_is_not_confused_with_another_command(monkeypatch, sent):
    """/parked takes no argument, so a stray one must not silently become a
    firm name or reroute the call."""
    _wire(monkeypatch, [_firm(1)])

    bot._dispatch("/parked all")

    assert sent[0].startswith("PARKED 1:")


def test_the_bot_suffix_form_routes(monkeypatch, sent):
    """_dispatch strips @botname; /parked has to inherit that like the rest."""
    _wire(monkeypatch, [_firm(1)])

    bot._dispatch("/parked@workflow_d_bot")

    assert sent[0].startswith("PARKED 1:")


def test_an_unknown_command_still_falls_through(monkeypatch, sent):
    bot._dispatch("/parkedd")

    assert sent[0].startswith("Unknown command: parkedd")
