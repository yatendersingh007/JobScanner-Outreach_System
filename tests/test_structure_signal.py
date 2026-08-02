"""Structure-signal park and AUM provenance tagging (run-36).

The ICP moved from industry label to structure signal: passing the vendored
gate's firm-type test is no longer enough. A firm additionally has to show that
it manages capital or property for someone else, because that is what creates
the back-office load X Analyst staffs. A pure production homebuilder books
revenue from selling houses: no fund to account for, no LP to report to, no
third-party portfolio to close.

THE FIGURE IS NOT THE SIGNAL, ITS LABEL IS. Three live blobs, all with a
disclosed_figure, only two describing capital or property held for others:

    Neal      "$905 million"          label "company revenue in fiscal year 2023"
    AlphaX    "$522M"                 label "Asset Under Management"
    Wasatch   "over 3,000,000 sq ft"  label "of commercial property under management"

Every firm_oneliner and disclosed_label quoted below is copied from a real
wd_firms row. Validated against all 48 distinct firms on file: of the four
currently qualified, exactly one (Neal) parks under the new rule.
"""
from __future__ import annotations

import pytest

from lib_referral import icp_gate
from src import signal_pipeline as sp


# --- live blobs ------------------------------------------------------------
CHOICE_NY = {"firm_oneliner": "Residential-focused property management and services in NYC metro",
             "aum_tag": "AUM_UNVERIFIED"}
NEAL = {"firm_oneliner": "Homebuilder, single-family and townhome development in Southwest Florida",
        "disclosed_figure": "$905 million",
        "disclosed_label": "company revenue in fiscal year 2023",
        "proxy_basis": "firm website / industry source reporting fiscal year revenue as proxy",
        "recent_event": "Article noting annual revenue ~$1B (Business Observer, Apr 2024)",
        "aum_tag": "AUM_ESTIMATED", "proxy_type": "non_floor"}
ALPHAX = {"firm_oneliner": "Builder-developer and vertically integrated real estate investment "
                          "and asset manager",
          "disclosed_label": "Asset Under Management", "disclosed_figure": "$522M",
          "aum_tag": "AUM_ESTIMATED", "proxy_type": "non_floor"}
WASATCH_CM = {"firm_oneliner": "Commercial property owner/operator and manager (retail and commercial)",
              "disclosed_label": "of commercial property under management",
              "proxy_basis": "units/sq-ft tertiary proxy",
              "aum_tag": "AUM_ESTIMATED", "proxy_type": "units"}
BROKERAGE = {"firm_oneliner": "Commercial real estate brokerage and transaction advisory, "
                             "tenant and landlord representation",
             "aum_tag": "AUM_UNVERIFIED"}
HOMEBUILDER_WITH_FUND = {
    "firm_oneliner": "Homebuilder and land developer operating a build-to-rent platform",
    "capital_stack": "land fund with institutional LPs",
    "aum_tag": "AUM_UNVERIFIED"}


# ---------------------------------------------------------------------------
# The four named cases
# ---------------------------------------------------------------------------
def test_third_party_property_manager_passes():
    """Choice NY class. Managing other owners' buildings IS the structure."""
    assert "managed_portfolio" in sp.structure_signals(CHOICE_NY)
    assert sp.no_structure_signal_park_reason(CHOICE_NY) is None


def test_pure_production_homebuilder_parks():
    """Neal class. It has a $905M figure, but the figure is REVENUE."""
    assert sp.structure_signals(NEAL) == []
    reason = sp.no_structure_signal_park_reason(NEAL)
    assert reason is not None
    assert "no structure signal" in reason
    assert "Homebuilder" in reason          # quotes the self-description as evidence


def test_a_revenue_figure_is_not_a_value_figure():
    """Stated on its own because it is the whole Neal case: presence of a
    disclosed_figure must not count, only what the label says it measures."""
    assert NEAL["disclosed_figure"]
    assert "value_figure" not in sp.structure_signals(NEAL)


def test_homebuilder_with_a_land_fund_or_btr_arm_passes():
    """The fund scan runs over the same text before any parking decision, so a
    homebuilder with a fund arm never reaches the homebuilder outcome."""
    signals = sp.structure_signals(HOMEBUILDER_WITH_FUND)

    assert "fund_or_gp" in signals
    assert "limited_partners" in signals
    assert sp.no_structure_signal_park_reason(HOMEBUILDER_WITH_FUND) is None


@pytest.mark.parametrize("oneliner", [
    "Homebuilder operating a land fund alongside its production business",
    "Single-family homebuilder with a build-to-rent platform",
    "Production homebuilder and BTR fund sponsor",
    "Homebuilder co-investing through joint ventures with institutional partners",
])
def test_each_homebuilder_fund_variant_passes(oneliner):
    assert sp.structure_signals({"firm_oneliner": oneliner}) != []


def test_brokerage_without_a_management_arm_parks():
    assert sp.structure_signals(BROKERAGE) == []
    assert sp.no_structure_signal_park_reason(BROKERAGE) is not None


def test_brokerage_with_an_investment_management_arm_passes():
    """Colliers' real one-liner. The rule parks brokerages WITHOUT a management
    arm, so the arm has to be what decides it."""
    research = {"firm_oneliner": "Global commercial real estate services, investment "
                                "management and advisory"}
    assert "third_party_capital" in sp.structure_signals(research)


# ---------------------------------------------------------------------------
# Signal detection per field and per class
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field", list(sp._STRUCTURE_TEXT_FIELDS))
def test_every_scanned_field_can_carry_a_signal(field):
    assert sp.structure_signals({field: "manages a fund for institutional LPs"}) != []


def test_disclosed_figure_is_deliberately_not_scanned():
    """A bare number carries no meaning. Only its label does."""
    assert "disclosed_figure" not in sp._STRUCTURE_TEXT_FIELDS
    assert sp.structure_signals({"disclosed_figure": "$905 million"}) == []


@pytest.mark.parametrize("text,expected", [
    ("LP, GP, Co-GP, Preferred Equity", "limited_partners"),      # the master's own example
    ("closed-end fund vehicle", "fund_or_gp"),
    ("general partner on each deal", "fund_or_gp"),
    ("assets under management", "third_party_capital"),
    ("gross asset value of the portfolio", "value_figure"),
    ("of commercial property under management", "managed_portfolio"),
    ("third-party property manager for institutional owners", "managed_portfolio"),
])
def test_signal_classes(text, expected):
    assert expected in sp.structure_signals({"firm_oneliner": text})


@pytest.mark.parametrize("research", [{}, None, {"firm_oneliner": ""},
                                      {"firm_oneliner": None, "capital_stack": ""}])
def test_an_empty_blob_has_no_signals(research):
    assert sp.structure_signals(research) == []
    assert sp.no_structure_signal_park_reason(research) is not None


def test_a_negated_phrase_is_not_a_signal():
    """Aston Carter's live one-liner matched managed_portfolio on the very
    phrase negating it. Caught in validation against the real blobs."""
    research = {"firm_oneliner": "staffing and recruitment firm providing talent "
                                "solutions (not an owner/operator)"}
    assert sp.structure_signals(research) == []


def test_launch_vehicle_is_not_a_fund_vehicle():
    """Blue Origin's "aerospace launch vehicle manufacturer" matched fund_or_gp
    on a bare "vehicle" token. Also caught in validation."""
    research = {"firm_oneliner": "aerospace launch vehicle manufacturer (rocket company)"}
    assert sp.structure_signals(research) == []


# ---------------------------------------------------------------------------
# gate_group wiring
# ---------------------------------------------------------------------------
def _fake_dbc(monkeypatch):
    state, updates = {}, []
    monkeypatch.setattr(sp.dbc, "create_wd_firm",
                        lambda run_id, firm_name, **f: state.update(
                            {"id": 1, "run_id": run_id, "firm_name": firm_name, **f}) or dict(state))
    monkeypatch.setattr(sp.dbc, "insert_postings", lambda run_id, firm_id, rows: len(rows))
    monkeypatch.setattr(sp.dbc, "update_wd_firm",
                        lambda fid, **f: (updates.append(f), state.update(f)) and None)
    monkeypatch.setattr(sp.dbc, "get_wd_firm", lambda fid: dict(state))
    return updates


def _gate(monkeypatch, research, verdict="qualified", reason="QUALIFIED (est. $500M)"):
    updates = _fake_dbc(monkeypatch)
    monkeypatch.setattr(icp_gate, "research_and_gate",
                        lambda firm_name, progress: icp_gate.GateResult(
                            icp_result=verdict, icp_reason=reason, research=research,
                            aum_tag=str(research.get("aum_tag") or "")))
    group = sp.FirmGroup(firm_name="Test Firm", firm_key="test firm", postings=[])
    row = sp.gate_group(1, group, lambda m: None)
    return row, updates


def test_gate_group_parks_a_qualified_firm_with_no_structure_signal(monkeypatch):
    row, _ = _gate(monkeypatch, dict(NEAL))

    assert row["icp_status"] == "parked"
    assert row["park_source"] == "no_structure_signal"
    assert "no structure signal" in row["park_reason"]
    assert "no structure signal" in row["icp_reason"]


def test_gate_group_leaves_a_qualified_firm_with_a_signal_alone(monkeypatch):
    row, _ = _gate(monkeypatch, dict(CHOICE_NY))

    assert row["icp_status"] == "qualified"
    assert row["park_source"] is None


@pytest.mark.parametrize("verdict", ["disqualified", "parked"])
def test_the_structure_check_never_overrides_a_non_qualified_verdict(verdict, monkeypatch):
    """It is a POST-gate check on an otherwise-qualified firm. A brokerage the
    gate already rejected on type is not re-decided here."""
    row, _ = _gate(monkeypatch, dict(NEAL), verdict=verdict, reason="the gate's own reason")

    assert row["icp_status"] == verdict
    assert row["park_source"] != "no_structure_signal"


def test_the_geo_check_still_wins_when_both_would_park(monkeypatch):
    """Ordering is geo, then acquired-by, then structure. A firm failing more
    than one parks once, attributed to the first."""
    research = {**NEAL, "domain": "firm.ae"}
    row, _ = _gate(monkeypatch, research)

    assert row["icp_status"] == "parked"
    assert row["park_source"] == "geo_tld_check"


def test_the_operator_is_told_why_it_parked(monkeypatch):
    updates = _fake_dbc(monkeypatch)
    monkeypatch.setattr(icp_gate, "research_and_gate",
                        lambda firm_name, progress: icp_gate.GateResult(
                            icp_result="qualified", icp_reason="q", research=dict(NEAL)))
    messages = []
    sp.gate_group(1, sp.FirmGroup(firm_name="Neal", firm_key="neal", postings=[]),
                  messages.append)

    assert any("no structure signal" in m and "qualifying" in m for m in messages)


# ---------------------------------------------------------------------------
# aum_source: operator > disclosed > proxy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("research,reason,expected", [
    ({"aum_tag": "AUM_CONFIRMED"}, "", "disclosed"),
    ({"aum_tag": "AUM_ESTIMATED", "proxy_type": "non_floor"}, "", "proxy"),
    ({"aum_tag": "AUM_ESTIMATED", "proxy_type": "units"}, "", "proxy"),
    ({"aum_tag": "AUM_UNVERIFIED"}, "", None),
    ({}, "", None),
    (None, "", None),
    ({"proxy_type": "gav"}, "", "proxy"),
])
def test_aum_source_mapping(research, reason, expected):
    assert sp.aum_source_for(research, reason) == expected


def test_operator_outranks_disclosed():
    """Load-bearing on live data: the one operator-qualified row on file is
    ALSO AUM_CONFIRMED, so a disclosed-first rule would hide the human."""
    research = {"aum_tag": "AUM_CONFIRMED", "disclosed_figure": "$700 million"}
    reason = "QUALIFIED (operator-verified AUM $700M)"

    assert sp.aum_source_for(research, reason) == "operator"
    assert sp.aum_source_for(research, "") == "disclosed"


def test_operator_outranks_proxy_and_an_unverified_tag():
    assert sp.aum_source_for({"aum_tag": "AUM_ESTIMATED", "proxy_type": "units"},
                             "QUALIFIED (operator-verified AUM $700M)") == "operator"
    assert sp.aum_source_for({"aum_tag": "AUM_UNVERIFIED"},
                             "QUALIFIED (operator-verified AUM $700M)") == "operator"


def test_gate_group_tags_a_qualified_row(monkeypatch):
    _row, updates = _gate(monkeypatch, dict(ALPHAX))

    assert updates[-1]["aum_source"] == "proxy"


def test_gate_group_tags_a_disclosed_figure(monkeypatch):
    research = {**CHOICE_NY, "aum_tag": "AUM_CONFIRMED"}
    _row, updates = _gate(monkeypatch, research)

    assert updates[-1]["aum_source"] == "disclosed"


def test_gate_group_leaves_a_parked_row_untagged(monkeypatch):
    """A parked or disqualified row has no figure worth comparing conversion
    against, so it carries no provenance rather than a misleading one."""
    _row, updates = _gate(monkeypatch, dict(NEAL))        # parks on no signal

    assert updates[-1]["aum_source"] is None


def test_qualify_tags_the_operator_source(monkeypatch):
    from src import bot

    updated = {}
    monkeypatch.setattr(bot.dbc, "parked_firm_by_name",
                        lambda name: {"id": 7, "firm_name": name, "research": {}})
    monkeypatch.setattr(bot.dbc, "update_wd_firm", lambda fid, **f: updated.update(f))
    monkeypatch.setattr(bot.tg, "send", lambda text, chat_id=None: None)

    bot._handle_qualify('"Acme Capital" 800M')

    assert updated["aum_source"] == "operator"
    assert updated["icp_status"] == "qualified"


def test_a_reused_cached_verdict_carries_its_provenance(monkeypatch):
    """Provenance travels with the verdict, so a cached row is comparable to
    the row it came from rather than silently untagged."""
    created = {}
    monkeypatch.setattr(sp.dbc, "create_wd_firm",
                        lambda run_id, firm_name, **f: created.update(f) or {"id": 2, **f})
    monkeypatch.setattr(sp.dbc, "insert_postings", lambda run_id, firm_id, rows: 0)
    group = sp.FirmGroup(firm_name="Acme", firm_key="acme", postings=[])

    sp._reuse_cached(1, group, {
        "id": 65, "icp_status": "qualified", "icp_reason": "QUALIFIED (est. $250M)",
        "aum_tag": "AUM_ESTIMATED", "research": {"aum_tag": "AUM_ESTIMATED",
                                                 "proxy_type": "non_floor"},
        "decided_at": "2026-07-31", "src": "cached_wd"})

    assert created["aum_source"] == "proxy"


def test_a_reused_disqualified_verdict_is_untagged(monkeypatch):
    created = {}
    monkeypatch.setattr(sp.dbc, "create_wd_firm",
                        lambda run_id, firm_name, **f: created.update(f) or {"id": 2, **f})
    monkeypatch.setattr(sp.dbc, "insert_postings", lambda run_id, firm_id, rows: 0)
    group = sp.FirmGroup(firm_name="Acme", firm_key="acme", postings=[])

    sp._reuse_cached(1, group, {
        "id": 70, "icp_status": "disqualified", "icp_reason": "Not an accepted firm type",
        "aum_tag": "AUM_CONFIRMED", "research": {"aum_tag": "AUM_CONFIRMED"},
        "decided_at": "2026-07-31", "src": "cached_wd"})

    assert created["aum_source"] is None
