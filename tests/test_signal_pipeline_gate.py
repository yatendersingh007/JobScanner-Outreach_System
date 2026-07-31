"""gate_group()'s two Workflow-D-local overrides of an otherwise-QUALIFIED
gate verdict: the geo TLD backstop (run 27) and the acquired-by-parent park
(run-29 funnel audit).

The geo backstop wires lib_snapshot.config.NORTH_AMERICA -- defined there,
never referenced anywhere else in the codebase before this -- into a check on
the gate's own resolved domain (research["domain"]/["own_domain"]).

Neither of these is a cross-check against the POSTING's own employer domain.
That one is still not buildable: a three-way investigation (scanner
connectors, the gating pipeline, and the wd_postings/wd_firms schema) found
no independently-derived employer domain anywhere in Workflow D's own code --
see BUILD_LOG.md's run-27 follow-up entry, including the correction of this
file's own prior (wrong) claim that Workflow D "already knows the posting's
employer domain from the scanner." What the run-29 audit DID find is a
second domain that has always been available and was never compared: the
POC's own email domain. That check lives in signal_drafting.py and is tested
in test_signal_drafting.py, because it happens at drafting time, after
Apollo, not at gate time.

What IS tested here: foreign_domain_park_reason() and
acquired_by_parent_park_reason() in isolation (pure classification logic),
and gate_group()'s wiring of both -- each only overrides an otherwise-
QUALIFIED verdict, a disqualified or already-parked verdict is left alone,
each uses a distinct park_source so it stays distinguishable from the gate's
own park reasons, and the two never stack into a doubly-overwritten reason.

No live Postgres, no network: wd_dbc and lib_referral.icp_gate.
research_and_gate are monkeypatched directly.
"""
from __future__ import annotations

import pytest

from lib_referral import icp_gate
from src import signal_pipeline as sp


# ---------------------------------------------------------------------------
# foreign_domain_park_reason: pure TLD classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("domain", [
    "alphax.ae",
    "example.co.uk",
    "firm.in",
    "firm.sg",
    "firm.hk",
    "firm.cn",
    "firm.de",
    "firm.au",
])
def test_foreign_domain_park_reason_flags_known_non_north_american_tlds(domain):
    assert sp.foreign_domain_park_reason({"domain": domain}) is not None


@pytest.mark.parametrize("domain", [
    "kingbird.com",
    "firm.us",
    "firm.ca",
    "firm.mx",
    "alphax-capital.com",   # the actual run-27 AlphaX case: a .com, not a foreign TLD
])
def test_foreign_domain_park_reason_does_not_flag_north_american_or_generic_domains(domain):
    assert sp.foreign_domain_park_reason({"domain": domain}) is None


@pytest.mark.parametrize("domain", [
    "startup.io", "brand.ai", "short.co", "personal.me", "channel.tv", "bit.ly",
])
def test_foreign_domain_park_reason_never_flags_vanity_gtlds(domain):
    """.io/.ai/.co/.me/.tv/.ly are technically ccTLDs but are overwhelmingly
    used as vanity/brand suffixes by North American firms -- flagging them
    would misfire on legitimate US/Canadian companies."""
    assert sp.foreign_domain_park_reason({"domain": domain}) is None


def test_foreign_domain_park_reason_falls_back_to_own_domain():
    assert sp.foreign_domain_park_reason({"own_domain": "firm.ae"}) is not None


def test_foreign_domain_park_reason_prefers_domain_over_own_domain():
    assert sp.foreign_domain_park_reason({"domain": "firm.com", "own_domain": "firm.ae"}) is None


@pytest.mark.parametrize("research", [{}, {"domain": ""}, {"domain": None}, None])
def test_foreign_domain_park_reason_handles_missing_domain(research):
    assert sp.foreign_domain_park_reason(research) is None


def test_foreign_domain_park_reason_names_the_country_and_tld():
    reason = sp.foreign_domain_park_reason({"domain": "alphax.ae"})
    assert "alphax.ae" in reason
    assert "United Arab Emirates" in reason
    assert ".ae" in reason


# ---------------------------------------------------------------------------
# gate_group(): wiring -- only overrides an otherwise-QUALIFIED verdict
# ---------------------------------------------------------------------------
def _fake_dbc(monkeypatch):
    state = {}
    updates = []

    def fake_create_wd_firm(run_id, firm_name, **fields):
        state.update({"id": 1, "run_id": run_id, "firm_name": firm_name, **fields})
        return dict(state)

    def fake_insert_postings(run_id, firm_id, rows):
        return len(rows)

    def fake_update_wd_firm(firm_id, **fields):
        updates.append(fields)
        state.update(fields)

    def fake_get_wd_firm(firm_id):
        return dict(state)

    monkeypatch.setattr(sp.dbc, "create_wd_firm", fake_create_wd_firm)
    monkeypatch.setattr(sp.dbc, "insert_postings", fake_insert_postings)
    monkeypatch.setattr(sp.dbc, "update_wd_firm", fake_update_wd_firm)
    monkeypatch.setattr(sp.dbc, "get_wd_firm", fake_get_wd_firm)
    return updates


def _group(name="AlphaX"):
    return sp.FirmGroup(firm_name=name, firm_key=name.lower(), postings=[])


def test_gate_group_parks_a_qualified_verdict_with_a_foreign_domain(monkeypatch):
    updates = _fake_dbc(monkeypatch)
    monkeypatch.setattr(
        icp_gate, "research_and_gate",
        lambda firm_name, progress: icp_gate.GateResult(
            icp_result="qualified", icp_reason="AUM ~$500M, US-based, qualifies",
            research={"domain": "alphax.ae"},
        ),
    )
    progressed = []

    row = sp.gate_group(run_id=1, group=_group(), progress=progressed.append)

    assert row["icp_status"] == "parked"
    assert row["park_source"] == "geo_tld_check"
    assert "United Arab Emirates" in row["park_reason"]
    assert "United Arab Emirates" in row["icp_reason"]
    assert any("United Arab Emirates" in msg and "qualifying" in msg for msg in progressed)
    # research and every other gate field still persisted, unmodified
    assert updates[-1]["research"] == {"domain": "alphax.ae"}


def test_gate_group_leaves_a_qualified_verdict_alone_when_domain_is_north_american(monkeypatch):
    _fake_dbc(monkeypatch)
    monkeypatch.setattr(
        icp_gate, "research_and_gate",
        lambda firm_name, progress: icp_gate.GateResult(
            icp_result="qualified", icp_reason="AUM ~$500M, US-based, qualifies",
            research={"domain": "kingbird.com"},
        ),
    )

    row = sp.gate_group(run_id=1, group=_group(), progress=lambda m: None)

    assert row["icp_status"] == "qualified"
    assert row["park_source"] is None


def test_gate_group_does_not_override_an_already_disqualified_verdict(monkeypatch):
    """The check only guards against a WOULD-BE-QUALIFIED firm slipping
    through on a foreign domain -- a firm the gate already disqualified for
    its own reasons needs no second opinion."""
    _fake_dbc(monkeypatch)
    monkeypatch.setattr(
        icp_gate, "research_and_gate",
        lambda firm_name, progress: icp_gate.GateResult(
            icp_result="disqualified", icp_reason="AUM ~$50M, below $200M floor, disqualified",
            research={"domain": "firm.ae"},
        ),
    )

    row = sp.gate_group(run_id=1, group=_group(), progress=lambda m: None)

    assert row["icp_status"] == "disqualified"
    assert row["park_source"] is None


def test_gate_group_does_not_override_an_already_parked_verdict(monkeypatch):
    _fake_dbc(monkeypatch)
    monkeypatch.setattr(
        icp_gate, "research_and_gate",
        lambda firm_name, progress: icp_gate.GateResult(
            icp_result="parked", icp_reason="AUM not found, no dollar proxies in sources, parked",
            park_reason="aum_unverified", park_source="research",
            research={"domain": "firm.ae"},
        ),
    )

    row = sp.gate_group(run_id=1, group=_group(), progress=lambda m: None)

    assert row["icp_status"] == "parked"
    assert row["park_source"] == "research"   # the gate's own reason, not overwritten
    assert row["park_reason"] == "aum_unverified"


def test_gate_group_alphax_regression_is_not_caught_by_the_geo_tld_backstop(monkeypatch):
    """The exact run-27 AlphaX case: the gate resolved to alphax-capital.com
    (a wrongly-matched different company, but a .com, no foreign TLD) --
    this backstop, by design, does not catch it. What DOES catch it is the
    POC email domain cross-check in signal_drafting.py (the contact was at
    alphax.ae) -- see test_signal_drafting.py. Documented here, not silently
    assumed fixed."""
    _fake_dbc(monkeypatch)
    monkeypatch.setattr(
        icp_gate, "research_and_gate",
        lambda firm_name, progress: icp_gate.GateResult(
            icp_result="qualified", icp_reason="AUM ~$522M, US-based, qualifies",
            research={"domain": "alphax-capital.com", "geography": "Silicon Valley / US markets"},
        ),
    )

    row = sp.gate_group(run_id=1, group=_group(), progress=lambda m: None)

    assert row["icp_status"] == "qualified"


# ---------------------------------------------------------------------------
# acquired_by_parent_park_reason: direction is the whole difficulty
#
# Run-27 funnel audit: Choice NY gated QUALIFIED while the gate's own
# research blob read "Sold to Associa Corp. in 2021 (earn-out noted)".
# Associa is the largest community-management operator in North America and
# has its own back office. Nothing read that field.
#
# The two acquirer strings below are REAL rows out of wd_firms, not invented
# counterexamples: a naive /acquired/ match parks both, and both mean the
# opposite thing (a firm buying real estate is growing and running its own
# books).
# ---------------------------------------------------------------------------
_ACQUIRED_TARGET_EVENTS = [
    "Sold to Associa Corp. in 2021 (earn-out noted)",          # live, wd_firms id 65/66
    "sold to Associa Corp. in 2021 (earn-out mentioned)",      # live, wd_firms id 83 (lowercase)
    "Acquired by Bain Capital for $5.3B (Dec 14, 2023)",       # live, Guidehouse
    "Bought by a larger operator in 2019",
    "Purchased by Greystar in March 2024",
    "Taken private by a PE sponsor last year",
    "Merged into its parent company in 2022",
    "Merged to form a combined platform (2023)",
    "Now a wholly-owned subsidiary of Associa",
    "A subsidiary of Brookfield Asset Management",
]

_ACQUIRER_EVENTS = [
    # Both live rows in wd_firms. Neither firm was acquired.
    "Acquired properties for $416.8M in 2025 (12 months ended Dec 31, 2025)",   # Brixmor, id 73
    "acquired The Morin Company, Morin Distribution, and Prillaman Systems",    # Havtech, id 17
    "Acquired a 12-property portfolio in Texas",
    "Completed the acquisition of a regional manager",
    "Announced the acquisition of two shopping centers",
    "Acquiring its third industrial park this year",
]


@pytest.mark.parametrize("event", _ACQUIRED_TARGET_EVENTS)
def test_acquired_by_parent_fires_when_the_firm_itself_was_acquired(event):
    reason = sp.acquired_by_parent_park_reason({"recent_event": event})
    assert reason is not None
    assert event in reason          # the event is quoted verbatim, never paraphrased


@pytest.mark.parametrize("event", _ACQUIRER_EVENTS)
def test_acquired_by_parent_never_fires_when_the_firm_is_the_acquirer(event):
    """The Brixmor/Havtech regression. A firm doing the acquiring is the
    OPPOSITE signal and must not be parked."""
    assert sp.acquired_by_parent_park_reason({"recent_event": event}) is None


@pytest.mark.parametrize("research", [
    {}, None, {"recent_event": ""}, {"recent_event": "   "},
    {"recent_event": None}, {"recent_event": "None"},
])
def test_acquired_by_parent_handles_a_missing_recent_event(research):
    assert sp.acquired_by_parent_park_reason(research) is None


@pytest.mark.parametrize("event", [
    "Opened new global HQ at 270 Park Avenue (Oct 21, 2025)",
    "launched $50M venture fund (2022)",
    "Article noting $1 billion annual revenue (Business Observer, Apr 2024)",
    "Project entered construction under SB 684 in Campbell",
    "achieved CMMI Institute Level 3 (public appraisal) - 2023",
    "Raptor Digital seeking $200M fund (reported 2024-2025 period)",
])
def test_acquired_by_parent_ignores_unrelated_events(event):
    """Every one of these is a real recent_event out of wd_firms."""
    assert sp.acquired_by_parent_park_reason({"recent_event": event}) is None


def test_gate_group_parks_a_qualified_firm_that_was_acquired(monkeypatch):
    """The Choice NY regression, end to end through the gate wiring."""
    updates = _fake_dbc(monkeypatch)
    research = {"domain": "choicenewyork.com",
                "recent_event": "Sold to Associa Corp. in 2021 (earn-out noted)"}
    monkeypatch.setattr(
        icp_gate, "research_and_gate",
        lambda firm_name, progress: icp_gate.GateResult(
            icp_result="qualified",
            icp_reason="QUALIFIED (est. $250M - portfolio value proxy)",
            research=research,
        ),
    )
    progressed = []

    row = sp.gate_group(run_id=1, group=_group("Choice NY Property Management LLC"),
                        progress=progressed.append)

    assert row["icp_status"] == "parked"
    assert row["park_source"] == "acquired_by_parent"
    assert "Associa" in row["park_reason"]
    assert "Associa" in row["icp_reason"]
    assert any("Associa" in msg and "qualifying" in msg for msg in progressed)
    assert updates[-1]["research"] == research     # research persisted unmodified


def test_gate_group_does_not_park_a_qualified_firm_that_did_the_acquiring(monkeypatch):
    """Brixmor's real research blob. It parked in run 27 for an unrelated
    reason (a $0M square-footage proxy); nothing about "Acquired properties"
    may park it here."""
    _fake_dbc(monkeypatch)
    monkeypatch.setattr(
        icp_gate, "research_and_gate",
        lambda firm_name, progress: icp_gate.GateResult(
            icp_result="qualified", icp_reason="QUALIFIED",
            research={"domain": "brixmor.com",
                     "recent_event": "Acquired properties for $416.8M in 2025"},
        ),
    )

    row = sp.gate_group(run_id=1, group=_group("Brixmor Property Group"), progress=lambda m: None)

    assert row["icp_status"] == "qualified"
    assert row["park_source"] is None


@pytest.mark.parametrize("verdict", ["disqualified", "parked"])
def test_gate_group_acquired_check_does_not_override_a_non_qualified_verdict(verdict, monkeypatch):
    _fake_dbc(monkeypatch)
    monkeypatch.setattr(
        icp_gate, "research_and_gate",
        lambda firm_name, progress: icp_gate.GateResult(
            icp_result=verdict, icp_reason="the gate's own reason",
            park_reason="the gate's own park reason" if verdict == "parked" else None,
            park_source="research" if verdict == "parked" else None,
            research={"recent_event": "Sold to Associa Corp. in 2021"},
        ),
    )

    row = sp.gate_group(run_id=1, group=_group(), progress=lambda m: None)

    assert row["icp_status"] == verdict
    assert row["icp_reason"] == "the gate's own reason"
    assert row["park_source"] != "acquired_by_parent"


def test_gate_group_geo_tld_check_wins_when_both_would_park(monkeypatch):
    """A firm with BOTH a foreign domain and an acquisition event parks once,
    attributed to the geo check, which runs first. The two must not stack
    into a doubly-overwritten reason."""
    _fake_dbc(monkeypatch)
    monkeypatch.setattr(
        icp_gate, "research_and_gate",
        lambda firm_name, progress: icp_gate.GateResult(
            icp_result="qualified", icp_reason="qualifies",
            research={"domain": "firm.ae",
                     "recent_event": "Acquired by a larger operator in 2021"},
        ),
    )

    row = sp.gate_group(run_id=1, group=_group(), progress=lambda m: None)

    assert row["icp_status"] == "parked"
    assert row["park_source"] == "geo_tld_check"
    assert "United Arab Emirates" in row["park_reason"]
