"""run_scan(): the one code path. Both the CLI (src/cli.py) and, later, the
Telegram bot (src/bot.py, prompt 2) call this — one code path, two front doors.

No systemd timer runs this (HARD RULE 2, Prompt 1: manual trigger only, no
scheduler, ever). Every run starts from a human command.

`scan` DRAFTS by default now (a deliberate change from the earlier
scan-then-pursue design): one command runs scan -> gate -> draft, with no
separate pursue step and no confirm prompt. `dry` is the opt-out that stops
after gating, for looking at a day's output without spending Apollo credits.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Optional

from . import signal_pipeline, wd_config as config
from . import wd_telegram as tg

log = logging.getLogger("workflow-d.run_scan")


def summarize(r, dry_hint: str = "--dry") -> str:
    """`dry_hint` is the exact flag text to show the operator for whichever
    front door is calling: "--dry" for the CLI, "/scan dry" for the bot.
    Never embed one syntax in a message the other front door might send."""
    lines = [f"Workflow D run {r.run_id}: {r.mode}"]
    if r.recency_days_used > 1:
        lines.append(
            f"Window: last {r.recency_days_used} days (catch-up). Postings "
            f"older than {r.recency_days_used} days that a prior run already "
            "recorded are not recoverable by widening further."
        )
    lines += [
        "",
        f"Postings kept: {r.postings_kept}",
        f"Companies: {r.groups}",
        f"Reused known verdicts: {len(r.skipped_known)}",
        "",
        f"QUALIFIED {len(r.qualified)}",
    ]
    for f in r.qualified:
        lines.append(f"  {f['firm_name']}, {f['posting_count']} open "
                     f"({f.get('aum_tag') or 'no AUM tag'}, {f.get('verdict_source')})")
    lines.append(f"PARKED {len(r.parked)}")
    for f in r.parked:
        lines.append(f"  {f['firm_name']}, {f.get('park_reason') or f.get('icp_reason')} "
                     f"[{f.get('park_source')}]  /qualify or /disqualify")
    lines.append(f"DISQUALIFIED {len(r.disqualified)}")
    for f in r.disqualified:
        lines.append(f"  {f['firm_name']}, {f.get('icp_reason')}")

    if r.deferred:
        lines += ["", f"OVER CAP {len(r.deferred)} not gated today "
                      f"(cap {config.GATE_CAP_PER_RUN}), queued for /resume:"]
        lines += [f"  {g.firm_name}" for g in r.deferred[:15]]
    if r.skipped_staffing:
        lines += ["", f"Staffing firms dropped: {len(r.skipped_staffing)} "
                      f"({', '.join(r.skipped_staffing[:5])})"]
    if r.skipped_uncategorized:
        lines.append(f"Uncategorized postings dropped: {r.skipped_uncategorized}")
    if r.connector_health:
        lines += ["", "CONNECTOR HEALTH: zero results from "
                      + ", ".join(r.connector_health)
                      + ". Check the target page markup."]
    lines += [
        "",
        f"Spend: {r.tavily_searches} Tavily searches, {r.llm_tokens} LLM tokens, "
        f"${r.research_cost_usd:.2f} research",
        f"CSV: {r.csv_path}",
    ]

    if r.dry:
        lines += ["", f"Dry run. Stopped after gating. Re-run without {dry_hint} to draft."]
    elif r.qualified:
        lines += ["", "Drafting is not built yet (prompts 3-4). Stopped after gating. "
                      f"Use {dry_hint} to suppress this note."]
    return "\n".join(lines)


def run_scan(mode: str, days: Optional[int] = None, dry: bool = False,
             gate_cap: Optional[int] = None, progress=tg.progress):
    """Scan, gate, and (once prompts 3-4 land) draft. Returns the RunResult.

    Never drafts today: signal_drafting.py does not exist yet. Gating always
    completes and persists regardless of `dry` — dry only controls whether a
    caller WOULD go on to draft, which right now is moot either way. The
    distinction is kept in the signature and in `summarize()`'s messaging so
    the two states ("you asked to stop" vs "drafting isn't built") never read
    as the same thing.
    """
    return signal_pipeline.run(mode=mode, progress=progress, gate_cap=gate_cap,
                                recency_days=days, dry=dry)


def run_single_firm(mode: str, firm_name: str, dry: bool = False,
                     progress=tg.progress):
    """`/scan "Firm"` / `--firm "Firm"`: gate exactly one named firm, skipping
    the scanner entirely. Reuses signal_pipeline.gate_group() and its dbc
    helpers unchanged -- this is new orchestration on top of them, not a
    change to signal_pipeline.py's own grouping/cache/gate logic (DO NOT
    CHANGE signal_pipeline.py, prompt 2's scope)."""
    dbc = signal_pipeline.dbc
    run_row = dbc.create_wd_run(mode, recency_days_used=1)
    result = signal_pipeline.RunResult(run_id=run_row["id"], mode=mode,
                                       recency_days_used=1, dry=dry, groups=1)
    group = signal_pipeline.FirmGroup(firm_name=firm_name, firm_key=dbc.firm_key(firm_name))
    progress(f"Gating {firm_name} (single-firm override, scanner skipped)...")
    firm = signal_pipeline.gate_group(result.run_id, group, progress)
    result.tavily_searches += firm.pop("_search_calls", 0) or 0
    result.llm_tokens += firm.pop("_tokens_used", 0) or 0
    result.research_cost_usd += float(firm.pop("_research_cost_usd", 0) or 0)
    {"qualified": result.qualified,
     "disqualified": result.disqualified,
     "parked": result.parked}.get(firm["icp_status"], result.parked).append(firm)
    dbc.update_wd_run(
        result.run_id,
        status="done",
        finished_at=signal_pipeline._now(),
        companies_grouped=1,
        companies_gated=len(result.qualified) + len(result.disqualified) + len(result.parked),
        tavily_searches=result.tavily_searches,
        llm_tokens=result.llm_tokens,
        research_cost_usd=result.research_cost_usd,
    )
    return result


def run_resume(dry: bool = False, progress=tg.progress):
    """`/resume`: continue the latest crashed or cancelled run from its
    wd_queue, without re-drafting (re-gating) anything already decided.
    Reuses signal_pipeline.gate_group() plus wd_dbc's next_pending()/
    set_queue_status() -- written in Prompt 0/1 but never read back until
    now, since signal_pipeline.run() itself only ever iterates its own
    in-memory `to_gate` list, not the queue. Returns None if there is
    nothing resumable.
    """
    dbc = signal_pipeline.dbc
    run = dbc.latest_resumable_run()
    if run is None:
        return None
    run_id = run["id"]
    dbc.update_wd_run(run_id, status="running", cancel_requested_at=None)
    result = signal_pipeline.RunResult(
        run_id=run_id, mode="resume",
        recency_days_used=run.get("recency_days_used") or 1, dry=dry,
    )
    # Firms this run already decided before it crashed/was cancelled count
    # toward the summary; none of them are re-gated or re-drafted.
    for firm in dbc.firms_for_run(run_id):
        bucket = {"qualified": result.qualified, "disqualified": result.disqualified,
                  "parked": result.parked}.get(firm.get("icp_status"))
        if bucket is not None:
            bucket.append(firm)
    result.groups = len(result.qualified) + len(result.disqualified) + len(result.parked)

    cap = config.GATE_CAP_PER_RUN
    # A generous limit, not an unbounded query -- effectively "all pending
    # rows for this run," which then gets split at `cap` below so the cap
    # guard still applies to a resumed run exactly as it does to a fresh one.
    all_pending = dbc.next_pending(run_id, limit=cap + 10_000)
    to_process, still_pending = all_pending[:cap], all_pending[cap:]

    for i, q in enumerate(to_process):
        if dbc.cancel_requested(run_id):
            result.cancelled = True
            still_pending = to_process[i:] + still_pending
            break
        progress(f"Resuming: gating {q['firm_name']} ({i + 1}/{len(to_process)})...")
        group = signal_pipeline.FirmGroup(firm_name=q["firm_name"], firm_key=q["firm_key"])
        firm = signal_pipeline.gate_group(run_id, group, progress)
        dbc.set_queue_status(q["id"], "done", firm_id=firm["id"])
        result.groups += 1
        result.tavily_searches += firm.pop("_search_calls", 0) or 0
        result.llm_tokens += firm.pop("_tokens_used", 0) or 0
        result.research_cost_usd += float(firm.pop("_research_cost_usd", 0) or 0)
        {"qualified": result.qualified, "disqualified": result.disqualified,
         "parked": result.parked}.get(firm["icp_status"], result.parked).append(firm)

    result.deferred = [SimpleNamespace(firm_name=q["firm_name"]) for q in still_pending]
    dbc.update_wd_run(
        run_id,
        status="cancelled" if result.cancelled else "done",
        finished_at=signal_pipeline._now(),
        companies_gated=len(result.qualified) + len(result.disqualified) + len(result.parked),
        tavily_searches=result.tavily_searches,
        llm_tokens=result.llm_tokens,
        research_cost_usd=result.research_cost_usd,
    )
    return result
