"""Run 27 follow-up: gate_group()'s geo TLD backstop.

Wires lib_snapshot.config.NORTH_AMERICA -- defined there, never referenced
anywhere else in the codebase before this -- into a Workflow-D-local check
on the gate's own resolved domain (research["domain"]/["own_domain"]).

This is NOT the domain-mismatch cross-check that was asked for alongside
it (comparing the gate's resolved domain against the posting's own
employer domain). That check is not buildable today: a three-way
investigation (scanner connectors, the gating pipeline, and the
wd_postings/wd_firms schema) found no independently-derived employer
domain anywhere in Workflow D's own code -- see BUILD_LOG.md's run-27
follow-up entry for the full finding, including the correction of this
file's own prior (wrong) claim that Workflow D "already knows the
posting's employer domain from the scanner."

What IS tested here: foreign_domain_park_reason() in isolation (the pure
TLD-classification logic), and gate_group()'s wiring of it (only overrides
an otherwise-QUALIFIED verdict; a disqualified or already-parked verdict
is left alone; the override uses a distinct park_source so it's
distinguishable from the gate's own park reasons).

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


def test_gate_group_alphax_regression_still_qualifies_since_gate_resolved_a_dot_com(monkeypatch):
    """The exact run-27 AlphaX case: the gate resolved to alphax-capital.com
    (a wrongly-matched different company, but a .com, no foreign TLD) --
    this backstop, by design, does not catch it. Documented, not silently
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
