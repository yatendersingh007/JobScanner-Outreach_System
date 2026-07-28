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
from typing import Optional

from . import signal_pipeline, wd_config as config
from . import wd_telegram as tg

log = logging.getLogger("workflow-d.run_scan")


def summarize(r) -> str:
    lines = [f"Workflow D run {r.run_id}: {r.mode if hasattr(r, 'mode') else 'scan'}"]
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

    if getattr(r, "dry", False):
        lines += ["", "Dry run. Stopped after gating. Re-run without --dry to draft."]
    elif r.qualified:
        lines += ["", "Drafting is not built yet (prompts 3-4). Stopped after gating. "
                      "Use --dry to suppress this note."]
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
    result = signal_pipeline.run(mode=mode, progress=progress, gate_cap=gate_cap,
                                  recency_days=days)
    result.dry = dry
    return result
