"""The 09:00 America/New_York entrypoint. Invoked by workflow-d.service.

Scans, groups, gates the capped set of new companies, and reports to Telegram.
It does NOT draft unless AUTO_DRAFT_ON_SCHEDULE is true, which is false by
default: drafting spends Apollo credits and writes into Harp's Gmail, so the
unattended path stops at "here is today's qualified list, reply /scan pursue".

Exit codes: 0 clean, 1 crashed (systemd marks the unit failed and journalctl
carries the traceback; there is deliberately no automatic retry).
"""
from __future__ import annotations

import logging
import sys
import traceback

from . import signal_pipeline, wd_config as config, wd_dbc as dbc
from . import wd_telegram as tg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("workflow-d.daily")


def _summary(r) -> str:
    lines = [
        f"Workflow D run {r.run_id} — daily scan",
        "",
        f"Postings kept: {r.postings_kept}",
        f"Companies: {r.groups}",
        f"Reused known verdicts: {len(r.skipped_known)}",
        "",
        f"QUALIFIED {len(r.qualified)}",
    ]
    for f in r.qualified:
        lines.append(f"  {f['firm_name']} — {f['posting_count']} open "
                     f"({f.get('aum_tag') or 'no AUM tag'}, {f.get('verdict_source')})")
    lines.append(f"PARKED {len(r.parked)}")
    for f in r.parked:
        lines.append(f"  {f['firm_name']} — {f.get('park_reason') or f.get('icp_reason')} "
                     f"[{f.get('park_source')}]  /qualify or /disqualify")
    lines.append(f"DISQUALIFIED {len(r.disqualified)}")
    for f in r.disqualified:
        lines.append(f"  {f['firm_name']} — {f.get('icp_reason')}")

    if r.deferred:
        lines += ["", f"OVER CAP {len(r.deferred)} not gated today "
                      f"(cap {config.GATE_CAP_PER_RUN}), queued for /scan pursue:"]
        lines += [f"  {g.firm_name}" for g in r.deferred[:15]]
    if r.skipped_staffing:
        lines += ["", f"Staffing firms dropped: {len(r.skipped_staffing)} "
                      f"({', '.join(r.skipped_staffing[:5])})"]
    if r.skipped_uncategorized:
        lines.append(f"Uncategorized postings dropped: {r.skipped_uncategorized}")
    if r.connector_health:
        lines += ["", "CONNECTOR HEALTH: zero results from "
                      + ", ".join(r.connector_health)
                      + " — check the target page markup."]
    lines += [
        "",
        f"Spend: {r.tavily_searches} Tavily searches, {r.llm_tokens} LLM tokens, "
        f"${r.research_cost_usd:.2f} research",
        f"CSV: {r.csv_path}",
        "",
        "Reply /scan pursue to draft the qualified firms.",
    ]
    return "\n".join(lines)


def main() -> int:
    if config.TEST_MODE:
        tg.send("Workflow D daily run starting (TEST_MODE).")
    else:
        tg.send("Workflow D daily run starting.")
    try:
        result = signal_pipeline.run(mode="scheduled", progress=tg.progress)
    except Exception as e:
        tg.send(f"Workflow D daily run CRASHED: {type(e).__name__}: {e}\n"
                f"No retry will happen automatically. journalctl -u workflow-d "
                f"for the traceback.")
        traceback.print_exc()
        return 1

    tg.send(_summary(result))

    if config.AUTO_DRAFT_ON_SCHEDULE and result.qualified:
        tg.send("AUTO_DRAFT_ON_SCHEDULE is on, drafting now.")
        from . import signal_drafting  # not built yet, see BUILD_STATE.md
        signal_drafting.draft_for_run(result.run_id, progress=tg.progress)
    return 0


if __name__ == "__main__":
    sys.exit(main())
