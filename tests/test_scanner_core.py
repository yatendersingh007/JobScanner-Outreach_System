"""Job Scanner core + Workflow D grouping.

BRIEF step 10.1: the scanner had zero tests, and the rule inherited from the
38-fix history is that the first change to an untested codebase is a test for
the thing being touched. Workflow D depends on the title gate, the geo gate,
and dedup semantics being right, so those come first.

Every title case below is a real title shape seen on the boards the scanner
reads. The regex list under test is the live one in scanner/config.yaml, loaded
from disk, so a future edit to that file that breaks a case fails here.

Run locally only. No pytest on the VM, ever (HARD RULE 5).
"""
from __future__ import annotations

from datetime import date

import pytest
import yaml

from scanner.pipeline import _compile_excludes, _compile_patterns, _title_matches
from scanner import config as scanner_config
from src import wd_dbc, signal_pipeline
from src.signal_pipeline import FirmGroup, group_by_company


@pytest.fixture(scope="module")
def cfg():
    return scanner_config.load("scanner/config.yaml")


@pytest.fixture(scope="module")
def gates(cfg):
    return _compile_patterns(cfg), _compile_excludes(cfg)


def _keep(title, cfg, gates):
    patterns, excludes = gates
    return _title_matches(title, cfg.titles, patterns, excludes)


# ---------------------------------------------------------------------------
# Title gate — keep
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("title", [
    "Property Accountant",
    "Senior Property Accountant",
    "Property Management Accountant",
    "Real Estate Accountant",
    "Fund Accountant",
    "Senior Fund Accountant",
    "Fund Controller",
    "Controller",
    "Assistant Controller",
    "Accounting Manager",
    "Staff Accountant",
    "Corporate Accountant",
    "Family Office Accountant",
    "Lease Administrator",
    "Lease Analyst",
    # "CAM Analyst" was here until run 39. The market does not use that title
    # (890+ CAM-reconciliation postings ship as Property Accountant, Senior
    # Accountant, Real Estate Controller), so the pattern and its TinyFish
    # target were dropped. "CAM Accountant" below is the title that is real.
    "CAM Accountant",
    "Joint Venture Accountant",
    "Construction Accountant",
    "Development Accountant",
    "Acquisitions Analyst",
    "Investment Associate",
    "Asset Management Analyst",
    "Capital Markets Analyst",
    "Commercial Real Estate Underwriter",
    "Investor Relations Associate",
    "Fund Operations Analyst",
    "Fund Administrator",
    "Treasury Analyst",
    "Financial Reporting Manager",
    "Valuations Analyst",
    "Accounts Payable Specialist",
    "Accounts Receivable Specialist",
    "Billing Coordinator",
])
def test_title_kept(title, cfg, gates):
    assert _keep(title, cfg, gates), f"{title!r} should be kept"


# ---------------------------------------------------------------------------
# Title gate — drop. Exclusions win over any include match.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("title", [
    "Accounting Intern",
    "Property Accountant Intern",
    "Fund Accounting Internship",
    "Air Traffic Controller",
    "Insurance Underwriter",
    "Underwriter, Commercial Insurance",
    "Life Insurance Underwriting Analyst",
    "P&C Underwriter",
    "Auto Underwriter",
])
def test_title_dropped(title, cfg, gates):
    assert not _keep(title, cfg, gates), f"{title!r} should be dropped"


@pytest.mark.parametrize("title", [
    "Software Engineer",
    "Registered Nurse",
    "Marketing Manager",
    "Warehouse Associate",
])
def test_unrelated_titles_dropped(title, cfg, gates):
    assert not _keep(title, cfg, gates)


def test_exclusion_beats_a_matching_include(cfg, gates):
    """"Property Accountant Intern" matches an include AND an exclude.

    scanner/pipeline.py:_title_matches checks excludes first and returns
    False immediately. This asserts that ordering, which is the only thing
    keeping intern postings out of a cold email to a CFO.
    """
    patterns, excludes = gates
    assert any(p.search("Property Accountant Intern") for p in patterns)
    assert not _title_matches("Property Accountant Intern", cfg.titles, patterns, excludes)


def test_bad_regex_is_skipped_not_fatal(cfg):
    """A malformed pattern in config.yaml must warn and skip, never crash.

    The scanner is edited by hand by a non-author. A typo'd bracket taking
    down the 9 AM run is not acceptable.
    """
    from scanner.pipeline import _compile
    out = _compile([r"property\s+accountant", r"[unclosed"], "title_pattern")
    assert len(out) == 1


# ---------------------------------------------------------------------------
# Geo gate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("location,expected", [
    ("New York, NY", "US"),
    ("Dallas, TX, United States", "US"),
    ("Toronto, ON, Canada", "Canada"),
    ("Vancouver, British Columbia", "Canada"),
    ("London, United Kingdom", "UK"),
    ("Bengaluru, India", "India"),
])
def test_region_detection(location, expected):
    from scanner import filters
    assert filters.region_of(location) == expected


def test_out_of_scope_region_rejected(cfg):
    """config.yaml scope is North America. UK and India must not be in it."""
    assert set(cfg.regions) <= {"US", "Canada", "Mexico"}
    assert "UK" not in cfg.regions and "India" not in cfg.regions


# ---------------------------------------------------------------------------
# Dedup semantics
# ---------------------------------------------------------------------------
def _job(company="Acme Realty", title="Fund Accountant", url="https://x/1",
         source="jsearch", job_id="", category="Real Estate",
         subcategory="Staff Accountant", region="US", location="New York, NY"):
    from scanner.models import NormalizedJob
    j = NormalizedJob(company=company, title=title, url=url, source=source,
                      job_id=job_id, location=location)
    j.category, j.subcategory, j.region = category, subcategory, region
    j.first_seen = date(2026, 7, 28)
    j.days_since_posted = 0
    return j


def test_dedup_key_prefers_source_native_id():
    j = _job(job_id="abc123")
    assert j.dedup_key() == "jsearch:abc123"


def test_dedup_key_falls_back_to_content_hash():
    a, b = _job(), _job()
    assert a.dedup_key() == b.dedup_key()
    assert _job(title="Controller").dedup_key() != a.dedup_key()


def test_dedup_key_is_namespaced_per_source():
    """This is the documented gap Workflow D compensates for.

    The same real posting found by JSearch and by the TinyFish LinkedIn guest
    search produces two different keys, so it survives dedup twice. Asserting
    it here so the behaviour is known and deliberate, not discovered later in
    a shipped email claiming three openings that are one.
    """
    a = _job(source="jsearch")
    b = _job(source="LinkedIn US")
    assert a.dedup_key() != b.dedup_key()


# ---------------------------------------------------------------------------
# firm_key
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("a,b", [
    ("Grubb Properties", "Grubb Properties, LLC"),
    ("Magnolia Capital", "Magnolia Capital Inc."),
    ("29th Street Capital", "29th Street Capital LP"),
    ("The Carlyle Group", "Carlyle Group"),
    ("Standish Management LLC", "Standish Management"),
])
def test_firm_key_matches_same_firm(a, b):
    assert wd_dbc.firm_key(a) == wd_dbc.firm_key(b)


@pytest.mark.parametrize("a,b", [
    ("Kairos Real Estate Partners", "Kairos Investment Management"),
    ("Standish Management", "Standish Group"),
    ("Blue Rock Partners", "Blue Rock"),
    ("American Real Estate Partners", "American Realty Advisors"),
])
def test_firm_key_keeps_different_firms_apart(a, b):
    """FIX 28's landmine. A loose key would reuse the wrong cached verdict."""
    assert wd_dbc.firm_key(a) != wd_dbc.firm_key(b)


def test_firm_key_never_returns_empty_for_a_named_firm():
    assert wd_dbc.firm_key("Holdings LLC") != ""


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------
def test_group_collapses_a_firms_postings_into_one_prospect():
    jobs = [_job(title="Property Accountant"),
            _job(title="Fund Accountant"),
            _job(company="Acme Realty, LLC", title="Controller")]
    groups, staffing, uncat = group_by_company(jobs, [])
    assert len(groups) == 1
    assert groups[0].posting_count == 3
    assert not staffing and not uncat


def test_posting_count_dedups_the_same_role_from_two_sources():
    """One role seen on JSearch and LinkedIn is ONE opening, not two.

    posting_count goes into the email as a fact. Getting this wrong is a false
    claim in a cold email, which is the exact failure class fact_check exists
    to prevent.
    """
    jobs = [_job(title="Fund Accountant", source="jsearch"),
            _job(title="fund accountant", source="LinkedIn US"),
            _job(title="  Fund Accountant  ", source="SelectLeaders")]
    groups, _, _ = group_by_company(jobs, [])
    assert groups[0].posting_count == 1
    assert groups[0].distinct_titles == ["Fund Accountant"]


def test_staffing_firms_are_dropped_before_the_gate():
    jobs = [_job(company="Robert Half"),
            _job(company="Vaco by Highspring"),
            _job(company="Acme Realty")]
    blocklist = ["robert half", "vaco"]
    groups, staffing, _ = group_by_company(jobs, blocklist)
    assert [g.firm_name for g in groups] == ["Acme Realty"]
    assert len(staffing) == 2


def test_uncategorized_postings_are_dropped_not_gated():
    """The classifier never guesses. Neither does the gate budget."""
    jobs = [_job(category="Other"), _job(category="Needs Review"),
            _job(category="Family Office"), _job(category="Real Estate")]
    groups, _, uncat = group_by_company(jobs, [])
    assert uncat == 2
    assert len(groups) == 1  # same company, both target categories


def test_blank_company_is_dropped():
    groups, _, uncat = group_by_company([_job(company="   ")], [])
    assert groups == [] and uncat == 1


def test_group_category_prefers_a_target_category():
    g = FirmGroup(firm_name="Acme", firm_key="acme",
                  postings=[_job(category="Real Estate")])
    assert g.category == "Real Estate"


def test_target_categories_are_exactly_the_two_sellable_ones():
    assert signal_pipeline.TARGET_CATEGORIES == {"Real Estate", "Family Office"}
