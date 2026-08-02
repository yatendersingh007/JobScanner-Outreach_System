"""Workflow D Phase 1-2: scan -> filter -> group -> verdict cache -> capped gate.

Order is the cost control (BRIEF 4). Every free operation happens before every
paid one, and the verdict cache sits in front of the gate because the gate is
the expensive step (~6 Tavily searches + up to MAX_LLM_TOKENS_PER_FIRM per firm).

This module stops at a persisted wd_firms verdict. Drafting (Phase 5a) and the
deck (Phase 5b) are the caller's job, so a `/scan` that only wants the summary
never touches Apollo, Gmail, or LibreOffice.

Entry point: run(mode, progress) -> RunResult
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from lib_snapshot.config import NORTH_AMERICA

from . import wd_config as config
from . import wd_dbc as dbc

log = logging.getLogger(__name__)

Progress = Callable[[str], None]


def _noop(_: str) -> None:
    return None


# Categories worth a prospect. The scanner's classifier writes "Other" and
# "Needs Review" for postings it could not attribute to an employer type, and
# it never guesses (classifier_rules.yaml header). Those are dropped here
# rather than gated: paying Tavily to research an unattributed employer is
# exactly the spend the classifier exists to avoid.
TARGET_CATEGORIES = {"Real Estate", "Family Office"}


@dataclass
class FirmGroup:
    """One company, all of its kept postings this run."""
    firm_name: str
    firm_key: str
    postings: list = field(default_factory=list)

    @property
    def distinct_titles(self) -> list[str]:
        """Deduped posting titles, in first-seen order.

        This is NOT len(self.postings). The scanner's dedup_key is namespaced
        by source (models.py: f"{self.source}:{...}"), so one real posting
        surfaced by both JSearch and the TinyFish LinkedIn guest search
        survives as two NormalizedJob rows. Harmless for grouping, but the
        posting count and titles go into the email and into the grounding
        corpus, where "hiring for 3 roles" when it is one role seen 3 times is
        a false factual claim in a cold email. Dedup on the title itself.
        """
        seen, out = set(), []
        for p in self.postings:
            t = _norm_title(p.title)
            if t in seen:
                continue
            seen.add(t)
            out.append(p.title.strip())
        return out

    @property
    def posting_count(self) -> int:
        return len(self.distinct_titles)

    @property
    def category(self) -> str:
        for p in self.postings:
            if p.category in TARGET_CATEGORIES:
                return p.category
        return ""

    @property
    def subcategory(self) -> str:
        return next((p.subcategory for p in self.postings if p.subcategory), "")


@dataclass
class RunResult:
    run_id: int
    mode: str = "manual"
    recency_days_used: int = 1
    dry: bool = False
    postings_raw: int = 0
    postings_kept: int = 0
    groups: int = 0
    qualified: list = field(default_factory=list)      # wd_firms rows
    disqualified: list = field(default_factory=list)
    parked: list = field(default_factory=list)
    skipped_known: list = field(default_factory=list)  # verdict-cache hits
    skipped_staffing: list = field(default_factory=list)
    skipped_uncategorized: int = 0
    deferred: list = field(default_factory=list)       # over the gate cap
    connector_health: list = field(default_factory=list)
    tavily_searches: int = 0
    llm_tokens: int = 0
    research_cost_usd: float = 0.0
    csv_path: str = ""
    cancelled: bool = False
    # Set by _apply_draft_cap_fields() once qualified/ is final, not by any
    # caller: how many of `qualified` fit under DRAFT_CAP_PER_RUN, and how
    # many don't. Computed once, here, so bot.py and the CLI only ever read
    # it rather than each recomputing their own copy of the same arithmetic.
    drafts_planned: int = 0
    drafts_over_cap: int = 0
    # Set by run_scan.py's drafting step (Prompt 3), never by run() itself --
    # this module stops at a persisted verdict (module docstring above).
    # wd_drafts rows / wd_firms rows, per HARD RULE 3's own bucket split.
    drafted: list = field(default_factory=list)
    drafted_with_prior_contact: list = field(default_factory=list)
    no_email: list = field(default_factory=list)
    duplicate_within_run: list = field(default_factory=list)
    # Contact resolved to a domain that is not the firm the gate researched.
    poc_domain_mismatch: list = field(default_factory=list)
    # Single-firm runs: gated and POC-resolved, but no posting exists to
    # anchor the v2 template, so no email. Not a failure bucket.
    no_posting: list = field(default_factory=list)
    # HARD RULE 4: per-run aggregate fact-grounding/fallback counts, reset at
    # the start of every draft_for_run() call and reported here.
    fallback_counts: dict = field(default_factory=dict)
    # TinyFish targets this run did NOT launch (step budget exhausted, or a
    # consecutive-failure abort), each a {"name", "reason"} dict. Never a
    # silent truncation -- see scanner/connectors/tinyfish.py's local edit.
    tinyfish_skipped: list = field(default_factory=list)
    tinyfish_steps_launched: int = 0
    # Blocklist maintenance (run-34). auto_blocked went into scanner/config.yaml
    # without confirmation; blocklist_candidates are suggestions only.
    auto_blocked: list = field(default_factory=list)
    blocklist_candidates: list = field(default_factory=list)


_WS_RE = re.compile(r"\s+")


def _norm_title(title: str) -> str:
    return _WS_RE.sub(" ", (title or "").strip().lower())


# ---------------------------------------------------------------------------
# Staffing firm exclusion
# ---------------------------------------------------------------------------
def staffing_blocklist(cfg) -> list[str]:
    """The blocklist out of the scanner's own config.yaml.

    NOTE, and this is a real correction to WORKFLOW_D_BRIEF.md section 4.2
    ("staffing blocklist already drops recruiters"): it does not. In the
    scanner the blocklist lives under poc_enrichment and is only consulted by
    poc_enricher to skip a TinyFish lookup. scanner/pipeline.py never filters
    on it, so a Robert Half posting for a "Fund Accountant" survives the title
    gate, the geo gate, and the classifier, and would arrive here as a
    prospect. Workflow D applies it as a hard drop before the gate, because a
    recruiter is not a firm we can sell embedded staff to and gating one burns
    a slot out of the daily cap.
    """
    raw = getattr(cfg, "poc_blocklist", None)
    if raw is None:
        raw = getattr(cfg, "blocklist", None)
    return [b.strip().lower() for b in (raw or []) if b and b.strip()]


def _is_staffing(company: str, blocklist: list[str]) -> Optional[str]:
    c = (company or "").lower()
    return next((b for b in blocklist if b and b in c), None)


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------
def group_by_company(jobs: list, blocklist: list[str]) -> tuple[list[FirmGroup], list[str], int]:
    """Group kept postings into one prospect per company.

    Returns (groups, staffing_dropped_names, uncategorized_dropped_count).
    Insertion order is preserved, and scanner/pipeline.run already sorted by
    days_since_posted, so the freshest signal leads and the gate cap spends on
    the newest postings first.
    """
    groups: dict[str, FirmGroup] = {}
    staffing: list[str] = []
    uncategorized = 0
    for job in jobs:
        company = (job.company or "").strip()
        if not company:
            uncategorized += 1
            continue
        hit = _is_staffing(company, blocklist)
        if hit:
            if company not in staffing:
                staffing.append(company)
            continue
        if job.category not in TARGET_CATEGORIES:
            uncategorized += 1
            continue
        key = dbc.firm_key(company)
        g = groups.get(key)
        if g is None:
            g = FirmGroup(firm_name=company, firm_key=key)
            groups[key] = g
        g.postings.append(job)
    return list(groups.values()), staffing, uncategorized


# ---------------------------------------------------------------------------
# Scanner invocation
# ---------------------------------------------------------------------------
def scan(recency_days: int = 1, progress: Progress = _noop):
    """Run the vendored Job Scanner and return (kept_jobs, cfg, csv_path).

    Workflow D uses the importable entry only. app.py and the Flask layer are
    not used (BRIEF 2). config.yaml already carries D's required settings:
    recency_days=1, regions [US, Canada], require_title_match=true, the full
    title_patterns list, classifier enabled.

    `recency_days` overrides cfg.recency_days IN MEMORY for this run only
    (Prompt 1's catch-up window, e.g. after a holiday gap). config.yaml on
    disk is never touched, so file drift can never silently widen the window
    for every future run — see the assert below.
    """
    from scanner import pipeline as scanner_pipeline
    from scanner import config as scanner_config
    from . import jsearch_pool

    jsearch_pool.install()
    cfg = scanner_config.load(config.SCANNER_CONFIG_PATH)

    # Assert rather than mutate on disk. If someone edits config.yaml to
    # recency_days=7 for a manual investigation and forgets to put it back,
    # a run must fail loudly instead of quietly emailing week-old signals as
    # "today". A one-off catch-up window is `--days N`, not a config.yaml edit.
    if cfg.recency_days != 1:
        raise ValueError(
            f"scanner recency_days is {cfg.recency_days}, Workflow D requires 1 "
            "in config.yaml. A stale posting invalidates the email's central "
            "claim. Use --days N for a one-off catch-up window instead."
        )
    if not cfg.require_title_match:
        raise ValueError("scanner require_title_match is false, Workflow D requires true.")

    if recency_days != cfg.recency_days:
        cfg.recency_days = recency_days

    progress("Scanning job boards...")
    kept = scanner_pipeline.run(cfg)
    progress(f"Scanner kept {len(kept)} postings.")
    return kept, cfg, cfg.csv_path


def connector_health(jobs: list, expected_sources: list[str]) -> list[str]:
    """Name any normally-productive source that returned nothing (BRIEF 4.1).

    A target site changing its markup thins TinyFish results silently: TinyFish
    still answers, it just finds less. Zero from a board that normally produces
    is the only signal available, so it goes in the summary every time.
    """
    seen = {j.source for j in jobs}
    return [s for s in expected_sources if s not in seen]


# ---------------------------------------------------------------------------
# Geo TLD backstop (run 27 follow-up). Wires lib_snapshot.config.NORTH_AMERICA
# -- defined there, never referenced anywhere until now -- into a Workflow-D-
# local check on the ONE domain that actually exists anywhere in this system:
# the gate's own post-research research["domain"]/["own_domain"].
#
# This is NOT the domain-mismatch cross-check that was asked for alongside
# it. That check needs a SECOND, independently-derived domain -- the actual
# posting's employer domain -- to compare the gate's resolved domain
# against. A full investigation (three parallel research passes over every
# scanner connector, the gating pipeline, and the wd_postings/wd_firms
# schema) found no such value anywhere in Workflow D's own code today:
# - JSearch's raw API response DOES carry an employer_website field
#   (confirmed live against a real captured response), but the vendored
#   adapter (scanner/connectors/adapters/jsearch.py) never reads it, and
#   the vendored NormalizedJob model (scanner/models.py) has no field to
#   hold it even if it did -- both vendored, so this is a donor-repo
#   (job-scanner) fix, not something patchable here.
# - TinyFish's LinkedIn scraper is never even asked for a domain -- its own
#   output schema has no such property.
# - The ats:* connector family (Greenhouse/Lever/Workday/...) WOULD produce
#   employer-adjacent URLs, but scanner/config.yaml's ats.companies list is
#   empty, so it contributes zero postings in the live configuration.
# - Every wd_postings.url value under what IS enabled today (jsearch,
#   tinyfish) is a job-board or ATS-vendor URL (linkedin.com,
#   ziprecruiter.com, boards.greenhouse.io/<slug>, ...), never the
#   employer's own root domain -- parsing one as a domain guess would be
#   actively wrong, and would reopen the exact class of collision FIX 28
#   protects against (a slug is not a verified identity).
# - The only "domain" anywhere in wd_firms/wd_postings is research["domain"]
#   itself, produced BY the gate's own Tavily/LLM resolution -- comparing
#   it against itself is circular, not a cross-check.
# BUILD_LOG.md's prior AlphaX post-mortem asserted Workflow D "already
# knows the posting's employer domain from the scanner" -- that assertion
# does not hold up; corrected here rather than left standing.
#
# What THIS check catches instead, independent of that gap: a firm whose
# domain the gate DID correctly resolve, but which carries an unambiguous
# non-North-American country-code TLD -- catching an LLM region_ok
# misjudgment even when the domain data itself was right there. It would
# NOT have caught the AlphaX incident specifically -- that run's
# gate-resolved domain was "alphax-capital.com" (a .com, no foreign TLD at
# all), because the gate had resolved to a different, wrongly-matched
# company's domain, not a foreign one. Deliberately excludes ccTLDs widely
# repurposed as vanity gTLDs by North American firms (.io, .ai, .co, .me,
# .tv, .ly) -- flagging those would misfire on legitimate US/Canadian
# firms for nothing more than a fashionable domain suffix.
# ---------------------------------------------------------------------------
_CCTLD_COUNTRY: dict[str, str] = {
    ".us": "United States", ".ca": "Canada", ".mx": "Mexico",
    ".ae": "United Arab Emirates", ".uk": "United Kingdom", ".in": "India",
    ".sg": "Singapore", ".hk": "Hong Kong", ".cn": "China", ".de": "Germany",
    ".fr": "France", ".es": "Spain", ".it": "Italy", ".nl": "Netherlands",
    ".ch": "Switzerland", ".au": "Australia", ".nz": "New Zealand",
    ".za": "South Africa", ".br": "Brazil", ".il": "Israel",
    ".sa": "Saudi Arabia", ".qa": "Qatar", ".kw": "Kuwait", ".eg": "Egypt",
    ".jp": "Japan", ".kr": "South Korea", ".ie": "Ireland", ".se": "Sweden",
    ".no": "Norway", ".dk": "Denmark", ".be": "Belgium", ".pt": "Portugal",
    ".at": "Austria", ".pl": "Poland", ".tr": "Turkey", ".th": "Thailand",
    ".my": "Malaysia", ".ph": "Philippines", ".id": "Indonesia",
    ".vn": "Vietnam", ".pk": "Pakistan", ".bd": "Bangladesh", ".ng": "Nigeria",
    ".ke": "Kenya", ".ar": "Argentina", ".cl": "Chile", ".pe": "Peru",
    ".ru": "Russia", ".ua": "Ukraine",
}


def foreign_domain_park_reason(research: dict) -> Optional[str]:
    """None if the gate's own resolved domain gives no reason to doubt
    region_ok, else a park reason naming the country/TLD. Matches on the
    LONGEST recognized suffix first ("co.uk" domains still end in ".uk" and
    match correctly via plain endswith; no compound-suffix table needed)."""
    domain = str((research or {}).get("domain")
                or (research or {}).get("own_domain") or "").strip().lower()
    if not domain:
        return None
    for suffix, country in _CCTLD_COUNTRY.items():
        if domain.endswith(suffix) and country not in NORTH_AMERICA:
            return f"domain {domain} carries a {country} ({suffix}) TLD, outside North America"
    return None


# ---------------------------------------------------------------------------
# Acquired-by-a-larger-operator park (run-27 funnel audit).
#
# Choice NY Property Management gated QUALIFIED while the gate's OWN research
# blob said recent_event = "Sold to Associa Corp. in 2021 (earn-out noted)".
# Associa is the largest community-management operator in North America and
# has its own back office, so the capacity gap the job posting signals is not
# Choice NY's to fill by hiring us. Nothing read that field. This reads it.
#
# DIRECTION IS THE WHOLE DIFFICULTY. Across all 83 wd_firms rows the audit
# found 45 with a non-empty recent_event, of which 11 mention an acquisition
# -- and 2 of those 11 describe the firm as the ACQUIRER, not the target:
#   Brixmor Property Group  "Acquired properties for $416.8M in 2025"
#   Havtech                 "acquired The Morin Company, Morin Distribution,
#                            and Prillaman Systems"
# A firm buying real estate is the opposite signal: it is growing and running
# its own books. A naive /acquired/ match parks both, so the patterns below
# are anchored on phrasings where the firm is the grammatical OBJECT of the
# acquisition ("sold to X", "acquired BY X", "subsidiary of X"), and an
# explicit acquirer test runs FIRST and wins outright.
#
# Deliberately narrow. It fires on 2 distinct firms out of 83 rows; the value
# is precision on a verdict that would otherwise ship a wrong draft, not
# coverage. An acquisition this misses is a firm the gate qualifies exactly as
# it does today, which is the current behavior, not a regression.
# ---------------------------------------------------------------------------
_ACQUIRED_TARGET_RE = re.compile(
    r"\b(?:"
    r"sold\s+(?:to|off\s+to)"
    r"|acquired\s+by"
    r"|bought\s+by"
    r"|purchased\s+by"
    r"|taken\s+private\s+by"
    r"|merged\s+(?:in)?to"
    r"|(?:a\s+|now\s+a\s+|wholly[\s-]owned\s+)?subsidiary\s+of"
    r")\b",
    re.IGNORECASE,
)

# Checked BEFORE _ACQUIRED_TARGET_RE and short-circuits it: the firm is doing
# the acquiring. "acquired properties", "acquired <a company name>",
# "completed the acquisition of", "acquired a portfolio".
_ACQUIRER_RE = re.compile(
    r"\b(?:"
    r"acquir(?:ed|es|ing)\s+(?:properties|property|a\s|an\s|its\s|the\s|\d|[A-Z])"
    r"|acquisition\s+of"
    r"|completed\s+the\s+acquisition"
    r")",
)


def acquired_by_parent_park_reason(research: dict) -> Optional[str]:
    """None if recent_event gives no reason to think the firm itself was
    acquired, else a park reason quoting the event verbatim.

    Returns None when the firm is the ACQUIRER -- that test runs first and
    wins, because "Acquired properties for $416.8M" also contains the word
    "acquired" and means the opposite thing."""
    event = str((research or {}).get("recent_event") or "").strip()
    if not event or event.lower() == "none":
        return None
    if _ACQUIRER_RE.search(event):
        return None
    if not _ACQUIRED_TARGET_RE.search(event):
        return None
    return (f"recent_event indicates the firm itself was acquired ({event}); "
            "a parent with its own back office may already cover this gap")


# ---------------------------------------------------------------------------
# Structure-signal park (run-36, ICP scope change from Harpreet).
#
# The gate moves from INDUSTRY LABEL to STRUCTURE SIGNAL. Passing the vendored
# gate's firm-type test is no longer sufficient: a firm additionally has to show
# at least one sign that it manages capital or property on someone else's
# behalf, because that is what creates the back-office load X Analyst staffs. A
# pure production homebuilder books revenue from selling houses; it has no fund
# to account for, no LP to report to and no third-party portfolio to close.
#
# WHERE EACH SIGNAL IS DETECTABLE, from reading the live blobs:
#
#   firm_oneliner    the primary carrier. "Residential-focused property
#                    management and services" (Choice NY), "Builder-developer
#                    and vertically integrated real estate investment and asset
#                    manager" (AlphaX), "Homebuilder, single-family and townhome
#                    development" (Neal).
#   capital_stack    the cleanest LP/GP carrier when populated: the master's own
#                    example is "LP, GP, Co-GP, Preferred Equity". Populated on
#                    11 of 83 rows, so it confirms but cannot be relied on.
#   disclosed_label  what the figure MEASURES, and the discriminating field.
#   proxy_basis      how the figure was derived, e.g. "units/sq-ft tertiary
#                    proxy", "of commercial property under management".
#   recent_event     secondary, e.g. "seeking $200M fund" (Raptor Group).
#
# THE FIGURE ALONE IS NOT A SIGNAL, ITS LABEL IS. This is the whole Neal case
# and the reason the check reads labels rather than checking for a number:
#
#   Neal      "$905 million"      label "company revenue in fiscal year 2023"
#   AlphaX    "$522M"             label "Asset Under Management"
#   Wasatch   "over 3,000,000 sq ft"  label "of commercial property under management"
#
# All three have a disclosed_figure. Only two of them describe capital or
# property held for others. Revenue is a production metric, so Neal parks.
#
# Homebuilders with a BTR or land-fund arm pass on the fund signal, which is
# why the fund scan runs over the same text before any parking decision rather
# than after a homebuilder classification.
# ---------------------------------------------------------------------------
_STRUCTURE_TEXT_FIELDS = ("firm_oneliner", "capital_stack", "disclosed_label",
                          "proxy_basis", "recent_event")

_STRUCTURE_SIGNALS: tuple = (
    # Plurals are explicit on every alternative. The group ends with \b, so a
    # bare "joint venture" cannot match "joint ventures" -- \b fails between
    # "venture" and "s". Caught by the homebuilder-with-a-fund-arm test.
    ("fund_or_gp", re.compile(
        r"\b(funds?|fund\s+i{1,3}\b|land\s+funds?|btr\s+funds?|build[\s-]to[\s-]rent"
        r"|general\s+partners?|co[\s-]?gp|\bgp\b|sponsors?|syndicat\w*"
        r"|joint\s+ventures?|\bjv\b|opportunity\s+zones?|closed[\s-]end|open[\s-]end"
        # "vehicle" must be qualified. A bare token matched Blue Origin's
        # "aerospace launch vehicle manufacturer", caught in validation.
        r"|(?:investment|fund|capital)\s+vehicles?|programmatic\s+equity)\b",
        re.IGNORECASE)),
    ("limited_partners", re.compile(
        r"\b(limited\s+partners?|\blps?\b|institutional\s+investors?|investor\s+capital"
        r"|preferred\s+equity|capital\s+partners?)\b", re.IGNORECASE)),
    ("third_party_capital", re.compile(
        r"\b(asset\s+manager|asset\s+management|investment\s+manager"
        r"|investment\s+management|manages?\s+capital|discretionary\s+capital"
        r"|on\s+behalf\s+of\s+(?:investors?|clients?|owners?)|fiduciary"
        r"|assets?\s+under\s+management|\baum\b)\b", re.IGNORECASE)),
    ("value_figure", re.compile(
        r"\b(assets?\s+under\s+management|\baum\b|gross\s+asset\s+value|\bgav\b"
        r"|portfolio\s+value|assets?\s+valued|invested\s+capital|deployed\s+capital"
        r"|fund\s+size|fund\s+target|capital\s+raised)\b", re.IGNORECASE)),
    ("managed_portfolio", re.compile(
        r"\b(property\s+manage\w*|under\s+management|managed\s+portfolio"
        r"|third[\s-]party\s+(?:manager|management|operator)"
        r"|owner[\s/-]operator|operates?\s+and\s+manages?|manages?\s+and\s+operates?"
        r"|manages?\s+over|servic\w+\s+for\s+owners)\b", re.IGNORECASE)),
)


def _structure_text(research: dict) -> str:
    return " || ".join(str((research or {}).get(f) or "") for f in _STRUCTURE_TEXT_FIELDS)


# A one-liner that DENIES the structure is not evidence of it. Live case caught
# in validation: Aston Carter's "staffing and recruitment firm providing talent
# solutions (not an owner/operator)" matched managed_portfolio on the very
# phrase that was negating it.
_NEGATION_RE = re.compile(r"(?:\bnot\s+(?:an?\s+)?|\bno\s+|\bnon[\s-]?)$", re.IGNORECASE)
_NEGATION_WINDOW = 14


def _is_negated(text: str, start: int) -> bool:
    return bool(_NEGATION_RE.search(text[max(0, start - _NEGATION_WINDOW):start]))


def structure_signals(research: dict) -> list:
    """Every structure signal present in the blob, by name. Empty means the
    firm shows no sign of managing capital or property for anyone else.

    A match immediately preceded by a negation does not count."""
    text = _structure_text(research)
    if not text.strip(" |"):
        return []
    found = []
    for name, rx in _STRUCTURE_SIGNALS:
        if any(not _is_negated(text, m.start()) for m in rx.finditer(text)):
            found.append(name)
    return found


def no_structure_signal_park_reason(research: dict) -> Optional[str]:
    """None if the firm shows at least one structure signal, else a park
    reason. Applied only to a firm the vendored gate already qualified."""
    if structure_signals(research):
        return None
    oneliner = str((research or {}).get("firm_oneliner") or "").strip()
    detail = f' Self-description: "{oneliner}".' if oneliner else ""
    return ("no structure signal in the research: no fund or GP language, no LP "
            "reference, no third-party capital management, no AUM or portfolio-value "
            f"figure, and no managed property portfolio.{detail}")


# ---------------------------------------------------------------------------
# AUM provenance tag (run-36). operator > disclosed > proxy, and that order is
# load-bearing: the one operator-qualified row on file is also AUM_CONFIRMED.
# ---------------------------------------------------------------------------
_OPERATOR_VERIFIED_RE = re.compile(r"operator-verified", re.IGNORECASE)


def aum_source_for(research: dict, icp_reason: str = "") -> Optional[str]:
    """"operator" | "disclosed" | "proxy" | None."""
    if _OPERATOR_VERIFIED_RE.search(icp_reason or ""):
        return "operator"
    research = research or {}
    tag = str(research.get("aum_tag") or "").upper()
    proxy = str(research.get("proxy_type") or "").strip()
    if tag == "AUM_CONFIRMED":
        return "disclosed"
    if tag == "AUM_ESTIMATED" or proxy:
        return "proxy"
    return None


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------
def gate_group(run_id: int, group: FirmGroup, progress: Progress,
               existing_firm: Optional[dict] = None) -> dict:
    """Gate one firm and persist the verdict. Returns the wd_firms row.

    The gate is vendored unchanged from referral-system (icp_gate.py):
    research_and_gate(firm_name, progress) -> GateResult with icp_result in
    {qualified, disqualified, parked}. Its own-domain resolution and PARK-on-
    ambiguity behaviour is the FIX 28 protection and is not weakened here.

    `existing_firm` re-gates IN PLACE into a wd_firms row that already exists,
    instead of inserting a second one. It exists for /resume finishing a firm
    that was in flight when the process died: that row already holds the run's
    own posting_count/category/subcategory AND the wd_postings rows are linked
    to it by firm_id, so replacing it would orphan them. Postings are not
    re-inserted in that path -- the row already has them, and the FirmGroup a
    resume reconstructs from wd_queue carries none (see run_scan.run_resume's
    note on that gap). Default None is byte-for-byte today's behaviour.
    """
    from lib_referral import icp_gate

    if existing_firm is not None:
        firm = existing_firm
    else:
        firm = dbc.create_wd_firm(
            run_id, group.firm_name,
            firm_key=group.firm_key,
            category=group.category,
            subcategory=group.subcategory,
            posting_count=group.posting_count,
        )
        dbc.insert_postings(run_id, firm["id"], [_posting_row(p) for p in group.postings])

    try:
        res = icp_gate.research_and_gate(group.firm_name, progress)
    except icp_gate.InfrastructureError as e:
        # Infrastructure failure is not a verdict. Park it with the source
        # recorded so /qualify can rescue it and the retry does not read as a
        # research finding about the firm.
        dbc.update_wd_firm(firm["id"], icp_status="parked",
                           park_reason=str(e), park_source="infrastructure",
                           icp_reason="infrastructure failure during research")
        return dbc.get_wd_firm(firm["id"])
    except icp_gate.BudgetExceeded as e:
        dbc.update_wd_firm(firm["id"], icp_status="parked",
                           park_reason=str(e), park_source="infrastructure",
                           icp_reason="per-firm token budget exceeded")
        return dbc.get_wd_firm(firm["id"])

    icp_status, icp_reason = res.icp_result, res.icp_reason
    park_reason, park_source = res.park_reason, res.park_source
    if icp_status == "qualified":
        geo_reason = foreign_domain_park_reason(res.research)
        if geo_reason:
            progress(f"{group.firm_name}: {geo_reason}. Parked despite the gate qualifying it.")
            icp_status, icp_reason = "parked", geo_reason
            park_reason, park_source = geo_reason, "geo_tld_check"
    if icp_status == "qualified":
        acquired_reason = acquired_by_parent_park_reason(res.research)
        if acquired_reason:
            progress(f"{group.firm_name}: {acquired_reason}. Parked despite the gate qualifying it.")
            icp_status, icp_reason = "parked", acquired_reason
            park_reason, park_source = acquired_reason, "acquired_by_parent"
    if icp_status == "qualified":
        structure_reason = no_structure_signal_park_reason(res.research)
        if structure_reason:
            progress(f"{group.firm_name}: {structure_reason} Parked despite the gate "
                     "qualifying it.")
            icp_status, icp_reason = "parked", structure_reason
            park_reason, park_source = structure_reason, "no_structure_signal"

    # Only a firm that survived every check gets a provenance tag; a parked or
    # disqualified row has no figure worth comparing conversion against.
    aum_source = aum_source_for(res.research, icp_reason) if icp_status == "qualified" else None

    dbc.update_wd_firm(
        firm["id"],
        icp_status=icp_status,
        icp_reason=icp_reason,
        aum_tag=res.aum_tag,
        aum_source=aum_source,
        park_reason=park_reason,
        park_source=park_source,
        confidence=res.confidence,
        source_count=res.source_count,
        research=res.research,
        verdict_source="gated",
        gated_at=_now(),
    )
    row = dbc.get_wd_firm(firm["id"])
    row["_search_calls"] = res.search_calls
    row["_tokens_used"] = res.tokens_used
    row["_research_cost_usd"] = res.research_cost_usd
    return row


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _posting_row(p) -> dict:
    return {
        "company": p.company,
        "title": p.title,
        "url": p.url,
        "source": p.source,
        "dedup_key": p.dedup_key(),
        "category": p.category,
        "subcategory": p.subcategory,
        "region": p.region,
        "location": p.location,
        "posted_date": p.posted_date,
        "first_seen": p.first_seen,
        "days_since_posted": p.days_since_posted,
        "match_reason": p.match_reason,
        "poc_name_hint": p.poc_name,
        "poc_designation_hint": p.poc_designation,
        # The v2 signal email's Block 2 traceability check and its
        # {systems_if_known} clause both read this. NormalizedJob has carried
        # it all along (JSearch fills it, the TinyFish guest search cannot);
        # it was simply never copied into the row, so every draft fell back to
        # block2_generic. getattr keeps a NormalizedJob-shaped test double
        # without the field working.
        "description": getattr(p, "description", "") or "",
    }


def _reuse_cached(run_id: int, group: FirmGroup, cached: dict) -> dict:
    firm = dbc.create_wd_firm(
        run_id, group.firm_name,
        firm_key=group.firm_key,
        category=group.category,
        subcategory=group.subcategory,
        posting_count=group.posting_count,
        icp_status=cached["icp_status"],
        icp_reason=cached["icp_reason"],
        aum_tag=cached.get("aum_tag"),
        research=cached.get("research"),
        verdict_source=cached["src"],
        verdict_cached_from=cached["id"],
        gated_at=cached["decided_at"],
        # run-36: provenance travels with the reused verdict, so a cached row
        # is comparable to the row it came from rather than silently untagged.
        aum_source=(aum_source_for(cached.get("research"), cached.get("icp_reason") or "")
                    if cached["icp_status"] == "qualified" else None),
    )
    dbc.insert_postings(run_id, firm["id"], [_posting_row(p) for p in group.postings])
    return firm


# ---------------------------------------------------------------------------
# Catch-up window (Prompt 1, manual trigger only, no timer)
# ---------------------------------------------------------------------------
def _resolve_recency_days(days: Optional[int]) -> int:
    """Default to config.DEFAULT_SCAN_DAYS (1); validate 1 <= days <= MAX_SCAN_DAYS.

    Outside that range raises rather than clamping, so a mistyped --days is a
    loud error, not a silently different window than the operator asked for.
    """
    resolved = config.DEFAULT_SCAN_DAYS if days is None else days
    if not (1 <= resolved <= config.MAX_SCAN_DAYS):
        raise ValueError(
            f"recency_days must be between 1 and {config.MAX_SCAN_DAYS}, got {resolved}"
        )
    return resolved


def _apply_draft_cap_fields(result: RunResult) -> None:
    """Sets drafts_planned/drafts_over_cap from the FINAL qualified list and
    the current DRAFT_CAP_PER_RUN. Computed once, here -- the one place that
    knows both numbers -- so callers (bot.py, the CLI) only ever read it
    rather than each recomputing the same min()/max() themselves."""
    n_qualified = len(result.qualified)
    result.drafts_planned = min(n_qualified, config.DRAFT_CAP_PER_RUN)
    result.drafts_over_cap = max(0, n_qualified - config.DRAFT_CAP_PER_RUN)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def run(mode: str = "manual", progress: Progress = _noop,
        gate_cap: Optional[int] = None, recency_days: Optional[int] = None,
        dry: bool = False) -> RunResult:
    cap = config.GATE_CAP_PER_RUN if gate_cap is None else gate_cap
    window = config.REGATE_WINDOW_DAYS
    days = _resolve_recency_days(recency_days)

    # The Postgres advisory lock, not _busy (bot.py's in-process guard), is
    # the real cross-front-door guard: src/cli.py and src/bot.py are two
    # separate processes that can both reach this function at once. Taken
    # before the wd_runs row even exists, so a losing caller never creates
    # a row for a run that will not happen.
    if not dbc.acquire_run_lock():
        raise dbc.RunAlreadyInProgress(
            "Another Workflow D run is already in progress (CLI or bot). "
            "Wait for it to finish, or cancel it, before starting another."
        )
    try:
        run_row = dbc.create_wd_run(mode, recency_days_used=days)
        result = RunResult(run_id=run_row["id"], mode=mode, recency_days_used=days, dry=dry)
        if days > 1:
            progress(
                f"Window: last {days} days (catch-up). Postings older than {days} "
                "days that a prior run already recorded are not recoverable by "
                "widening further."
            )
        try:
            jobs, cfg, csv_path = scan(recency_days=days, progress=progress)
            # scanner/pipeline.run returns only what survived its own filters, so
            # raw and kept are the same number here. Raw counts live in the
            # scanner's own log line.
            result.postings_raw = len(jobs)
            result.postings_kept = len(jobs)
            result.csv_path = csv_path
            result.connector_health = connector_health(jobs, config.EXPECTED_SOURCES)
            result.tinyfish_skipped = getattr(cfg, "tinyfish_skipped_targets", [])
            result.tinyfish_steps_launched = getattr(cfg, "tinyfish_steps_launched", 0)

            blocklist = staffing_blocklist(cfg)
            groups, staffing, uncategorized = group_by_company(jobs, blocklist)
            result.skipped_staffing = staffing
            result.skipped_uncategorized = uncategorized
            result.groups = len(groups)
            progress(f"{len(groups)} companies after grouping "
                     f"({len(staffing)} staffing, {uncategorized} uncategorized dropped).")

            # Cache pass first, on every group, before spending anything. Cheap,
            # and it decides how much of the cap is actually needed.
            to_gate: list[FirmGroup] = []
            for g in groups:
                cached = dbc.verdict_cache_lookup(g.firm_name, window)
                if cached:
                    firm = _reuse_cached(result.run_id, g, cached)
                    result.skipped_known.append(firm)
                    if cached["icp_status"] == "qualified":
                        result.qualified.append(firm)
                    else:
                        result.disqualified.append(firm)
                else:
                    to_gate.append(g)

            progress(f"{len(result.skipped_known)} known firms reused from cache, "
                     f"{len(to_gate)} new to gate (cap {cap}).")

            dbc.enqueue(result.run_id, [(g.firm_key, g.firm_name) for g in to_gate])

            for i, g in enumerate(to_gate):
                if dbc.cancel_requested(result.run_id):
                    result.cancelled = True
                    result.deferred.extend(to_gate[i:])
                    break
                if i >= cap:
                    result.deferred.append(g)
                    continue
                progress(f"Gating {g.firm_name} ({i + 1}/{min(cap, len(to_gate))})...")
                firm = gate_group(result.run_id, g, progress)
                result.tavily_searches += firm.pop("_search_calls", 0) or 0
                result.llm_tokens += firm.pop("_tokens_used", 0) or 0
                result.research_cost_usd += float(firm.pop("_research_cost_usd", 0) or 0)
                {"qualified": result.qualified,
                 "disqualified": result.disqualified,
                 "parked": result.parked}.get(firm["icp_status"], result.parked).append(firm)

            _apply_draft_cap_fields(result)
            dbc.update_wd_run(
                result.run_id,
                status="cancelled" if result.cancelled else "done",
                finished_at=_now(),
                postings_kept=result.postings_kept,
                companies_grouped=result.groups,
                companies_gated=len(result.qualified) + len(result.disqualified) + len(result.parked),
                csv_path=result.csv_path,
                tavily_searches=result.tavily_searches,
                llm_tokens=result.llm_tokens,
                research_cost_usd=result.research_cost_usd,
            )
        except Exception as e:
            log.exception("Workflow D run %s crashed", result.run_id)
            dbc.update_wd_run(result.run_id, status="crashed", finished_at=_now(),
                              notes=f"{type(e).__name__}: {e}")
            raise
        return result
    finally:
        dbc.release_run_lock()
