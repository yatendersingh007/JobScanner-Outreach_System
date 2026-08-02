"""Run-39 audit: JSearch scope, the tax pattern, the dead CAM Analyst target,
and the CAM description flag.

The config assertions read scanner/config.yaml itself and compile its patterns
the way scanner/pipeline.py does (re.IGNORECASE, exclusions win). That is the
point: these are claims about the shipped config, not about a fixture. If
someone edits the YAML, these fail.
"""
from __future__ import annotations

import io
import re

import pytest
import yaml

from src import run_scan, signal_pipeline as sp
from src.signal_pipeline import FirmGroup, RunResult

CONFIG_PATH = "scanner/config.yaml"


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(io.open(CONFIG_PATH, encoding="utf-8"))


@pytest.fixture(scope="module")
def patterns(cfg):
    return [re.compile(p, re.IGNORECASE) for p in cfg["title_patterns"]]


@pytest.fixture(scope="module")
def excludes(cfg):
    return [re.compile(p, re.IGNORECASE) for p in cfg["title_exclude_patterns"]]


def _kept(title, patterns, excludes):
    """scanner/pipeline.py's rule: exclusions win, then any pattern matches."""
    if any(e.search(title) for e in excludes):
        return False
    return any(p.search(title) for p in patterns)


# ---------------------------------------------------------------------------
# 1. JSearch scope: US only, 28 queries, every query backed by a pattern.
# ---------------------------------------------------------------------------
def test_canada_is_gone_from_the_aggregator(cfg):
    assert cfg["connectors"]["aggregator"]["countries"] == ["us"]


def test_the_query_list_is_twenty_eight_and_has_no_duplicates(cfg):
    queries = cfg["connectors"]["aggregator"]["queries"]
    assert len(queries) == 28
    assert len(set(queries)) == 28, "a duplicate query spends quota twice"


@pytest.mark.parametrize("query", [
    "real estate controller", "fund controller", "portfolio accountant",
    "lease analyst", "acquisitions analyst", "asset management analyst",
    "investor reporting analyst", "property bookkeeper",
])
def test_each_added_query_is_present(cfg, query):
    assert query in cfg["connectors"]["aggregator"]["queries"]


# The two queries whose own phrase no pattern matches, both deliberate and
# both pre-dating or caused by this change. Listed by name so a THIRD one
# cannot appear silently: the parity test below excludes exactly these.
_PARITY_EXCEPTIONS = {
    # 'accounts receivable' as a bare title is not in scope; the pattern wants
    # a role noun after it ("Accounts Receivable Specialist"). Pre-existing.
    "accounts receivable",
    # 'tax accountant' stopped matching its own phrase when the tax pattern
    # was tightened below, which is the entire point of that change: a tax
    # title now needs an asset class. The query still earns its slot through
    # titles like "Tax Accountant - Real Estate".
    "tax accountant",
}


def test_every_query_has_a_matching_title_pattern(cfg, patterns):
    gaps = [q for q in cfg["connectors"]["aggregator"]["queries"]
            if not any(p.search(q) for p in patterns)]
    assert set(gaps) == _PARITY_EXCEPTIONS, (
        "a query with no title_pattern spends JSearch quota on postings the "
        f"title filter then drops. Unexpected gaps: {set(gaps) - _PARITY_EXCEPTIONS}")


@pytest.mark.parametrize("title", [
    "Accounts Receivable Specialist",
    "Tax Accountant - Real Estate",
])
def test_the_parity_exceptions_still_admit_real_titles(title, patterns, excludes):
    """Exempting them from parity is only defensible if they still return
    something the filter keeps."""
    assert _kept(title, patterns, excludes)


@pytest.mark.parametrize("title", [
    "Real Estate Controller", "Fund Controller", "Portfolio Accountant",
    "Lease Analyst", "Acquisitions Analyst", "Asset Management Analyst",
    "Investor Reporting Analyst", "Property Bookkeeper", "Bookkeeper",
    "Senior Bookkeeper", "Full Charge Bookkeeper",
])
def test_the_new_queries_titles_survive_the_filter(title, patterns, excludes):
    assert _kept(title, patterns, excludes)


def test_bookkeeper_did_not_break_the_intern_exclusion(patterns, excludes):
    """Exclusions still win over the newly added patterns."""
    assert not _kept("Bookkeeping Intern", patterns, excludes)


# ---------------------------------------------------------------------------
# 2. The tax pattern needs an asset class. Titles verbatim from run 39.
# ---------------------------------------------------------------------------
def test_the_legitimate_run39_tax_title_still_passes(patterns, excludes):
    assert _kept("Tax Manager - Construction & Real Estate", patterns, excludes)


@pytest.mark.parametrize("title", [
    "Tax Accountant - In-Store (QUEENS)",
    "CPA / Tax Accountant (US Individual Tax 1040)",
])
def test_the_run39_tax_false_positives_are_dropped(title, patterns, excludes):
    assert not _kept(title, patterns, excludes)


@pytest.mark.parametrize("title", [
    "Real Estate Tax Manager",              # context leads
    "Tax Analyst, Commercial Real Estate",  # context trails
    "Property Tax Analyst",
    "REIT Tax Manager",
    "Fund Tax Associate",
    "Partnership Tax Manager",
    "Tax Manager (Multifamily)",
])
def test_tax_titles_carrying_an_asset_class_pass_in_either_direction(
        title, patterns, excludes):
    assert _kept(title, patterns, excludes)


def test_a_seniority_word_between_tax_and_the_role_still_misses(patterns, excludes):
    """Recorded, not fixed. "Tax Senior Associate, Real Estate Partnerships"
    does not match, because the role words are adjacent to "tax" in the
    pattern. That was equally true of the bare pattern this replaced, so it is
    a pre-existing gap and not a cost of tightening. Widening the role list is
    a separate decision."""
    assert not _kept("Tax Senior Associate, Real Estate Partnerships", patterns, excludes)


@pytest.mark.parametrize("title", [
    "Tax Analyst",
    "Senior Tax Accountant",
    "Tax Manager - Individual Returns",
    "Tax Associate (Seasonal)",
])
def test_bare_tax_titles_no_longer_pass(title, patterns, excludes):
    """The old 'tax\\s+(analyst|associate|manager|accountant)' took all of
    these. Losing them is the intended cost of losing the retail tax preparers."""
    assert not _kept(title, patterns, excludes)


def test_the_bare_tax_pattern_is_gone(cfg):
    assert r"tax\s+(analyst|associate|manager|accountant)" not in cfg["title_patterns"]


# ---------------------------------------------------------------------------
# 3. CAM Analyst is dead as a title, alive as a word inside pattern 1.
# ---------------------------------------------------------------------------
def test_no_cam_analyst_title_pattern(cfg):
    assert r"cam\s+analyst" not in cfg["title_patterns"]


def test_no_cam_analyst_tinyfish_target_remains(cfg):
    names = [t["name"] for t in cfg["connectors"]["tinyfish"]["targets"]]
    assert not [n for n in names if "cam" in n.lower()], names


def test_cam_analyst_titles_are_no_longer_matched(patterns, excludes):
    assert not _kept("CAM Analyst", patterns, excludes)
    assert not _kept("Senior CAM Analyst", patterns, excludes)


def test_the_cam_accountant_alternative_survives(patterns, excludes):
    """Only the standalone 'cam analyst' pattern was dropped. The cam
    alternative inside the property/real-estate/lease accounting pattern
    matches titles the market actually uses."""
    assert _kept("CAM Accountant", patterns, excludes)
    assert _kept("CAM Accounting Manager", patterns, excludes)


@pytest.mark.parametrize("title", [
    "Property Accountant", "Senior Accountant", "Real Estate Controller",
])
def test_the_titles_cam_work_actually_ships_under_are_matched(
        title, patterns, excludes):
    """The audit's premise: 890+ CAM-reconciliation postings carry these
    titles. Dropping the CAM Analyst target only costs coverage if these
    don't match."""
    assert _kept(title, patterns, excludes)


# ---------------------------------------------------------------------------
# 4. The CAM description flag.
# ---------------------------------------------------------------------------
# Verbatim from wd_postings: Colliers' Senior Lease Administrator, the one
# description on file that carries the work. CAM sits in a list of recovery
# categories with "reconciliation" 53 characters later, which is why the
# detector needs proximity rather than adjacency.
COLLIERS_LIVE = ("In this role, you will\n\nAssist in the review of the tenant rent, "
                 "CAM, operating expense, tax, or insurance reimbursement reconciliation "
                 "as required.\nStrong attention to detail.")


@pytest.mark.parametrize("text,expected", [
    (COLLIERS_LIVE, "cam_reconciliation"),
    ("Prepare annual CAM reconciliations for a retail portfolio.", "cam_reconciliation"),
    ("Reconciliation of CAM charges and tenant billbacks.", "cam_reconciliation"),
    ("Responsible for common area maintenance billings.", "common_area_maintenance"),
    ("Owns NNN reconciliation and recovery billing.", "nnn_reconciliation"),
    ("Calculate operating expense recoveries and true-ups.", "opex_recoveries"),
    ("Handles operating expenses recovery for the portfolio.", "opex_recoveries"),
    ("* CAM\n* reconciliations of tenant charges", "cam_reconciliation"),
])
def test_cam_signals_fire_on_real_phrasings(text, expected):
    assert expected in sp.cam_signals(text)


@pytest.mark.parametrize("text", [
    "Operate the camera system; Cameron reconciles the schedule daily.",
    "Reconcile bank accounts and intercompany balances monthly.",
    "Prepare journal entries and account reconciliations for the fund.",
    "Manage the campus maintenance team.",
    "Month-end close, financial statements, and audit support.",
    "",
    "   ",
])
def test_cam_signals_stay_quiet_on_everything_else(text):
    assert sp.cam_signals(text) == []


def test_cam_signals_survives_none():
    assert sp.cam_signals(None) == []


def test_the_word_cam_alone_is_not_enough():
    """Proximity to reconciliation work, not a bare mention."""
    assert sp.cam_signals("Experience with CAM is a plus.") == []


class _Posting:
    def __init__(self, title="Property Accountant", description="", company="Acme"):
        self.title, self.description, self.company = title, description, company
        self.url = self.source = self.category = self.subcategory = ""
        self.region = self.location = self.match_reason = ""
        self.posted_date = self.first_seen = None
        self.days_since_posted = 0
        self.poc_name = self.poc_designation = None

    def dedup_key(self):
        return f"x:{self.title}"


def test_posting_row_carries_the_flag():
    flagged = sp._posting_row(_Posting(description=COLLIERS_LIVE))
    plain = sp._posting_row(_Posting(description="Month-end close and audit support."))
    assert flagged["cam_flag"] is True
    assert plain["cam_flag"] is False, "explicitly False, never None, on a row we evaluated"


def test_a_posting_with_no_description_is_false_not_none():
    """TinyFish guest-search rows have no description. False here means
    'read it, no CAM language', which is the honest reading of an empty body."""
    assert sp._posting_row(_Posting(description=""))["cam_flag"] is False


def test_insert_postings_writes_the_column():
    from src import wd_dbc
    import inspect
    src = inspect.getsource(wd_dbc.insert_postings)
    assert '"cam_flag"' in src, "the row dict carries cam_flag but the INSERT drops it"


def test_firm_group_flags_when_any_posting_does():
    group = FirmGroup(firm_name="Acme", firm_key="acme", postings=[
        _Posting(title="Staff Accountant", description="Month-end close."),
        _Posting(title="Property Accountant", description=COLLIERS_LIVE),
    ])
    assert group.cam_flag is True


def test_firm_group_stays_false_when_none_do():
    group = FirmGroup(firm_name="Acme", firm_key="acme", postings=[
        _Posting(description="Month-end close."),
        _Posting(description="Audit support."),
    ])
    assert group.cam_flag is False


def test_the_resume_path_reads_the_flag_back_from_the_db(monkeypatch):
    """The resume path re-gates in place from a FirmGroup rebuilt out of
    wd_queue, which carries no postings. The rows are already in wd_postings,
    so a silent False there would drop the marker on every resumed firm."""
    monkeypatch.setattr(sp.dbc, "postings_for_firm",
                        lambda firm_id: [{"cam_flag": False}, {"cam_flag": True}])
    assert sp._cam_flag_from_db(1) is True

    monkeypatch.setattr(sp.dbc, "postings_for_firm", lambda firm_id: [{"cam_flag": None}])
    assert sp._cam_flag_from_db(1) is False


def test_every_other_path_reads_the_group_and_never_queries(monkeypatch):
    """gate_group and _reuse_cached just inserted the rows from the group they
    are holding, so the group is authoritative and a query would be waste."""
    monkeypatch.setattr(sp.dbc, "postings_for_firm",
                        lambda firm_id: pytest.fail("no query needed, the group has them"))
    assert FirmGroup("Acme", "acme", [_Posting(description=COLLIERS_LIVE)]).cam_flag is True


# ---------------------------------------------------------------------------
# The [CAM] marker in the summary.
# ---------------------------------------------------------------------------
def _result_with(bucket, **firm):
    r = RunResult(run_id=1)
    getattr(r, bucket).append({"firm_name": "Colliers", "posting_count": 2,
                               "aum_tag": "AUM_CONFIRMED", "verdict_source": "gated",
                               "icp_reason": "reason", "park_reason": "reason",
                               "park_source": "src", **firm})
    return r


@pytest.mark.parametrize("bucket", ["qualified", "parked", "disqualified"])
def test_the_marker_appears_on_every_verdict_line(bucket):
    text = run_scan.summarize(_result_with(bucket, cam_flag=True))
    assert "[CAM] Colliers" in text, (
        "a PARKED firm with CAM work is exactly the one worth a second look "
        "before /disqualify")


@pytest.mark.parametrize("bucket", ["qualified", "parked", "disqualified"])
def test_no_marker_without_the_flag(bucket):
    assert "[CAM]" not in run_scan.summarize(_result_with(bucket, cam_flag=False))


def test_a_firm_row_predating_the_column_gets_no_marker():
    """cam_flag NULL means never evaluated. It must not render as a marker."""
    assert "[CAM]" not in run_scan.summarize(_result_with("qualified", cam_flag=None))
    r = RunResult(run_id=1)
    r.qualified.append({"firm_name": "Old Firm", "posting_count": 1,
                        "aum_tag": None, "verdict_source": "gated"})
    assert "[CAM]" not in run_scan.summarize(r)


def test_the_marker_does_not_disturb_the_rest_of_the_line():
    text = run_scan.summarize(_result_with("qualified", cam_flag=True))
    assert "[CAM] Colliers, 2 open (AUM_CONFIRMED, gated)" in text


# ---------------------------------------------------------------------------
# The flag records and surfaces. It must not touch composition.
# ---------------------------------------------------------------------------
def test_the_flag_is_not_read_by_the_drafting_layer():
    """This task records and surfaces only. If drafting starts reading
    cam_flag, that is a deliberate change and this test should be updated
    with it, not deleted quietly."""
    import inspect
    from src import signal_drafting
    assert "cam_flag" not in inspect.getsource(signal_drafting)
