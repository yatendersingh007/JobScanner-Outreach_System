"""Role-family table: the deterministic half of the v2 signal email.

Every value this module returns lands in a cold email as a statement of fact
about the seat, so the mapping is pinned per title rather than spot-checked.
The two coverage tests read scanner/config.yaml itself, so adding an
aggregator query or a TinyFish target without deciding its family shows up
here instead of in a prospect's inbox.
"""
from __future__ import annotations

import pathlib
import re
import urllib.parse

import pytest
import yaml

from src import role_families as rf

_CONFIG = yaml.safe_load(
    pathlib.Path(__file__).resolve().parents[1].joinpath("scanner", "config.yaml")
    .read_text(encoding="utf-8"))


def _aggregator_queries():
    return list(_CONFIG["connectors"]["aggregator"]["queries"])


def _tinyfish_titles():
    """The role each TinyFish target searches for, taken from the target's own
    URL (LinkedIn ?keywords=, SelectLeaders ?keywords=). Commented-out targets
    are absent from the parsed YAML, so this tracks what actually runs."""
    titles = []
    for target in _CONFIG["connectors"]["tinyfish"]["targets"]:
        query = urllib.parse.urlparse(target["url"]).query
        params = urllib.parse.parse_qs(query)
        keywords = params.get("keywords")
        titles.append(keywords[0] if keywords else target["name"].split(" - ")[-1])
    return titles


# ---------------------------------------------------------------------------
# The spec's own table, verbatim. Anything not named here is the controller
# default by design.
# ---------------------------------------------------------------------------
_SPEC = {
    "property accountant": "property_accounting",
    "real estate accountant": "property_accounting",
    "senior accountant": "property_accounting",
    "fund accountant": "fund_accounting",
    "fund administrator": "fund_accounting",
    "controller": "controller",
    "assistant controller": "controller",
    "accounting manager": "controller",
    "financial reporting analyst": "controller",
    "treasury analyst": "treasury",
    "accounts payable": "ap_ar",
    "accounts receivable": "ap_ar",
    "staff accountant": "ap_ar",
    "lease administrator": "lease_admin",
    "lease analyst": "lease_admin",
    "cam analyst": "lease_admin",
    "acquisitions analyst": "underwriting",
    "asset management analyst": "underwriting",
}


@pytest.mark.parametrize("title,expected", sorted(_SPEC.items()))
def test_family_for_each_title_named_in_the_spec(title, expected):
    assert rf.family_for_title(title).key == expected


@pytest.mark.parametrize("title,expected", [
    ("Senior Property Accountant", "property_accounting"),
    ("SR Property Accountant", "property_accounting"),
    ("Junior Property Accountant", "property_accounting"),
    ("Assistant Controller", "controller"),
    ("Corporate Controller", "controller"),
    ("Senior Fund Accountant", "fund_accounting"),
    # role_families keeps its own "cam analyst" title, unaffected by run 39
    # dropping the scanner PATTERN: the two tables are independent, and a
    # title the scanner no longer surfaces still maps correctly if it ever
    # arrives from another source.
    ("CAM Analyst", "lease_admin"),
    ("Lease Administration Specialist", "lease_admin"),
    ("Treasury Analyst (Hybrid)", "treasury"),
    ("Accounts Payable Specialist", "ap_ar"),
])
def test_family_matching_is_substring_and_case_insensitive(title, expected):
    assert rf.family_for_title(title).key == expected


@pytest.mark.parametrize("title", [
    "Corporate Accountant", "Tax Accountant", "Family Office Accountant",
    "Project Accountant", "Construction Accountant", "Widget Inspector", "", None,
])
def test_unmatched_titles_fall_to_the_controller_default(title):
    """The spec names controller as the default. These land there rather than
    producing a blank pain line -- documented so the set is visible and can be
    extended deliberately."""
    assert rf.family_for_title(title).key == rf.DEFAULT_FAMILY_KEY


def test_every_aggregator_query_maps_to_a_family():
    """All 28 JSearch queries in scanner/config.yaml (8 added run 39)."""
    queries = _aggregator_queries()
    assert len(queries) == 28
    for query in queries:
        family = rf.family_for_title(query)
        assert family.key in rf.BY_KEY
        assert family.pain and family.cadence and family.stack


def test_every_tinyfish_target_title_maps_to_a_family():
    """Every enabled TinyFish target's search role."""
    titles = _tinyfish_titles()
    assert titles, "no TinyFish targets parsed from config.yaml"
    for title in titles:
        family = rf.family_for_title(title)
        assert family.key in rf.BY_KEY
        assert family.pain and family.cadence and family.stack


def test_aggregator_and_tinyfish_family_assignment_is_stable():
    """Pins the actual assignment for every configured source title, so a
    table edit that silently re-homes a role fails here."""
    got = {q: rf.family_for_title(q).key for q in _aggregator_queries()}
    assert got == {
        "property accountant": "property_accounting",
        "staff accountant": "ap_ar",
        "senior accountant": "property_accounting",
        "accounts payable": "ap_ar",
        "fund accountant": "fund_accounting",
        "controller": "controller",
        "assistant controller": "controller",
        "accounting manager": "controller",
        "real estate accountant": "property_accounting",
        "corporate accountant": "controller",
        "property management accountant": "controller",
        "project accountant": "controller",
        "construction accountant": "controller",
        "lease administrator": "lease_admin",
        "financial reporting analyst": "controller",
        "fund administrator": "fund_accounting",
        "accounts receivable": "ap_ar",
        "family office accountant": "controller",
        "treasury analyst": "treasury",
        "tax accountant": "controller",
        # Added run 39. Three of these reach a family by rule; the other five
        # land on the controller DEFAULT, in the same way "corporate
        # accountant" and "project accountant" above already do. Recorded
        # rather than fixed: re-homing "portfolio accountant" to fund
        # accounting or "property bookkeeper" to property accounting is a
        # role-table decision, not a scanner-scope one.
        "real estate controller": "controller",
        "fund controller": "controller",
        "portfolio accountant": "controller",          # default
        "lease analyst": "lease_admin",
        "acquisitions analyst": "underwriting",
        "asset management analyst": "underwriting",
        "investor reporting analyst": "controller",    # default
        "property bookkeeper": "controller",           # default
    }


@pytest.mark.parametrize("key,pain,cadence", [
    ("property_accounting", "The close does not pause", "close calendar"),
    ("fund_accounting", "The capital calls do not wait", "reporting calendar"),
    ("controller", "The close does not pause", "close calendar"),
    ("treasury", "The cash does not stop moving", "cash reporting calendar"),
    ("ap_ar", "The invoices do not stop landing", "payment calendar"),
    ("lease_admin", "The abstracts do not read themselves", "lease calendar"),
    ("underwriting", "The deals do not wait", "deal calendar"),
])
def test_pain_and_cadence_match_the_spec_verbatim(key, pain, cadence):
    family = rf.BY_KEY[key]
    assert family.pain == pain
    assert family.cadence == cadence


def test_every_family_has_the_variables_the_template_needs():
    for key, family in rf.BY_KEY.items():
        assert family.pain and not family.pain.endswith("."), key
        assert family.cadence and not family.cadence.endswith("."), key
        assert len(family.stack) >= 3, key
        assert len(family.responsibilities) >= 3, key


def test_no_family_string_uses_a_banned_word_or_an_em_dash():
    """These strings go straight into a client-facing email, so they are held
    to CLAUDE.md's style rules like any other human-facing output."""
    from src import signal_drafting as sd

    for family in rf.BY_KEY.values():
        blob = " ".join((family.pain, family.cadence) + family.stack + family.responsibilities)
        assert "—" not in blob and "–" not in blob
        assert sd.find_style_violations(blob) == [], family.key


# ---------------------------------------------------------------------------
# {systems_if_known}
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("system", list(rf.KNOWN_SYSTEMS))
def test_each_known_system_is_detected(system):
    text = f"The role uses {system} daily for reporting."
    assert rf.systems_in(text) == [system]


def test_systems_are_returned_in_a_stable_order():
    text = "Experience with MRI, Yardi and RealPage required."
    assert rf.systems_in(text) == ["RealPage", "Yardi", "MRI"]


def test_multi_word_system_is_matched():
    assert rf.systems_in("Investor portal on Juniper Square.") == ["Juniper Square"]


@pytest.mark.parametrize("text", [
    "", None, "   ",
    "No accounting system is named anywhere in this posting.",
])
def test_no_systems_found_returns_empty(text):
    assert rf.systems_in(text) == []


def test_system_matching_respects_word_boundaries():
    """"MRI" must not fire inside an unrelated word."""
    assert rf.systems_in("Experience with MRIs in a medical imaging setting.") == []


@pytest.mark.parametrize("systems,expected", [
    ([], ""),
    (["Yardi"], "Yardi"),
    (["Yardi", "MRI"], "Yardi and MRI"),
    (["Yardi", "MRI", "RealPage"], "Yardi, MRI and RealPage"),
])
def test_join_systems(systems, expected):
    assert rf.join_systems(systems) == expected


# ---------------------------------------------------------------------------
# {role_mapped_stack}
# ---------------------------------------------------------------------------
def test_stack_is_the_family_base_when_there_is_no_posting_text():
    stack = rf.mapped_stack("Property Accountant", "")
    assert stack == ", ".join(rf.BY_KEY["property_accounting"].stack)


def test_stack_adds_a_posting_named_item():
    stack = rf.mapped_stack("Controller", "You will own multi-entity consolidations monthly.")
    assert "multi-entity consolidations" in stack
    assert stack.startswith("month-end close")     # base order preserved, addition appended


def test_stack_does_not_duplicate_an_item_already_in_the_base():
    stack = rf.mapped_stack("Property Accountant", "Heavy CAM reconciliation workload.")
    assert stack.count("CAM reconciliations and true-ups") == 1


def test_stack_adds_nothing_the_posting_did_not_name():
    stack = rf.mapped_stack("Controller", "A short posting with no system or task keywords.")
    assert stack == ", ".join(rf.BY_KEY["controller"].stack)


def test_property_family_stack_ends_at_lender_and_owner_reporting():
    """The spec's stated end-point for the no-systems sentence."""
    assert rf.BY_KEY["property_accounting"].stack[-1] == "lender and owner reporting"


def test_role_variables_bundles_everything_the_template_needs():
    v = rf.role_variables("Fund Accountant", "Waterfall allocations in Investran.")

    assert v["family"] == "fund_accounting"
    assert v["role_pain"] == "The capital calls do not wait"
    assert v["role_cadence"] == "reporting calendar"
    assert v["systems"] == ["Investran"]
    assert v["systems_if_known"] == "Investran"
    assert "waterfall allocations" in v["role_mapped_stack"]
    assert len(v["responsibilities"]) >= 3
