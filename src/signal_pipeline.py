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
# Gate
# ---------------------------------------------------------------------------
def gate_group(run_id: int, group: FirmGroup, progress: Progress) -> dict:
    """Gate one firm and persist the verdict. Returns the wd_firms row.

    The gate is vendored unchanged from referral-system (icp_gate.py):
    research_and_gate(firm_name, progress) -> GateResult with icp_result in
    {qualified, disqualified, parked}. Its own-domain resolution and PARK-on-
    ambiguity behaviour is the FIX 28 protection and is not weakened here.
    """
    from lib_referral import icp_gate

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

    dbc.update_wd_firm(
        firm["id"],
        icp_status=res.icp_result,
        icp_reason=res.icp_reason,
        aum_tag=res.aum_tag,
        park_reason=res.park_reason,
        park_source=res.park_source,
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
