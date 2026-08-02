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

from . import blocklist, signal_drafting, signal_pipeline, wd_config as config
from . import wd_telegram as tg

log = logging.getLogger("workflow-d.run_scan")


def _apply_blocklist_maintenance(result, progress) -> None:
    """Auto-block self-described staffing firms, and collect suggestions for the
    ambiguous rest. Runs after gating, on this run's own firms.

    Never raises into the run. A config-file or audit-log problem is worth
    reporting and worth leaving the blocklist unchanged over, but it is not
    worth losing a completed run's verdicts and drafts to -- so every failure
    degrades to a progress line and an untouched file.
    """
    dbc = signal_pipeline.dbc
    try:
        firms = dbc.firms_for_run(result.run_id)
        protected = dbc.qualified_or_parked_firm_names()
        entries = blocklist.read_entries(config.SCANNER_CONFIG_PATH)
        auto, notify, rejected = blocklist.classify_firms(firms, protected, entries)
    except Exception as e:  # noqa: BLE001 - suggestions are never worth a failed run
        progress(f"Blocklist maintenance skipped ({type(e).__name__}: {e}).")
        return

    for candidate in rejected:
        name, tier, failures = candidate
        log.info("blocklist candidate rejected: %s (%s) %s", name, tier, failures)

    applied = []
    for candidate in auto:
        comment = (f"auto-added run {result.run_id}: "
                   f"{' '.join((candidate.evidence or '').split())[:60]}")
        try:
            blocklist.add_entry(config.SCANNER_CONFIG_PATH, candidate.firm_name, comment)
        except blocklist.BlocklistFileError as e:
            progress(f"Could not auto-block {candidate.firm_name}: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            progress(f"Could not auto-block {candidate.firm_name} ({type(e).__name__}: {e}).")
            continue
        applied.append(candidate)

    if applied:
        blocklist.append_audit(config.BUILD_LOG_PATH, result.run_id, applied)
    result.auto_blocked = [c.firm_name for c in applied]
    result.blocklist_candidates = [c.firm_name for c in notify]


def _run_drafting(result, progress) -> None:
    """Prompt 3: drafting runs INLINE, right after gating, in the same call
    that gated -- not a second command (PROMPTS.md prompt 3 item 7). Posts
    the spend/draft intent as its own persistent Telegram message via
    tg.send() (Prompt 2 step 2a: "information, not a question"), distinct
    from progress()'s rate-limited live-edited status line -- a message
    sent via progress() would just flash and get overwritten by the first
    "Drafting X..." line. tg.send() no-ops to a log line when no bot
    token/chat is configured, so this is also safe to call from the CLI.
    """
    if not result.qualified:
        return
    over_note = (f", {result.drafts_over_cap} over cap and parked for /resume"
                if result.drafts_over_cap else "")
    tg.send(
        f"{len(result.qualified)} qualified. {result.drafts_planned} will be drafted "
        f"(DRAFT_CAP_PER_RUN={config.DRAFT_CAP_PER_RUN}){over_note}. "
        "/cancel now if this number looks wrong."
    )
    draft_result = signal_drafting.draft_for_run(result.run_id, progress)
    result.drafted = draft_result.drafted
    result.drafted_with_prior_contact = draft_result.drafted_with_prior_contact
    result.no_email = draft_result.no_email
    result.duplicate_within_run = draft_result.duplicate_within_run
    result.poc_domain_mismatch = draft_result.poc_domain_mismatch
    result.no_posting = draft_result.no_posting
    result.fallback_counts = draft_result.fallback_counts
    if draft_result.cancelled:
        result.cancelled = True


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
    if r.auto_blocked:
        lines += ["", f"Auto-blocked {len(r.auto_blocked)} staffing firms: "
                      f"{', '.join(r.auto_blocked)}"]
    if r.blocklist_candidates:
        lines += ["", "Blocklist candidates: " + ", ".join(r.blocklist_candidates)
                      + '  /block "Name" to add']
    if r.connector_health:
        lines += ["", "CONNECTOR HEALTH: zero results from "
                      + ", ".join(r.connector_health)
                      + ". Check the target page markup."]
    if r.tinyfish_skipped:
        by_reason: dict = {}
        for s in r.tinyfish_skipped:
            by_reason.setdefault(s["reason"], []).append(s["name"])
        lines += ["", "TINYFISH TARGETS SKIPPED (never truncated silently):"]
        for reason, names in by_reason.items():
            if reason.startswith("step_budget_exhausted"):
                group = reason.split(":", 1)[1] if ":" in reason else "overall"
                lines.append(
                    f"  step budget exhausted ({group}) after target "
                    f"{r.tinyfish_steps_launched}, skipped: {', '.join(names)}"
                )
            elif reason == "aborted_after_consecutive_failures":
                lines.append(f"  aborted after 3 consecutive failures, "
                            f"skipped: {', '.join(names)}")
            else:
                lines.append(f"  {reason}: {', '.join(names)}")
    if r.dry:
        lines += ["", f"Dry run. Stopped after gating. Re-run without {dry_hint} to draft."]
    elif r.qualified:
        lines += [
            "",
            f"DRAFTED {len(r.drafted)}",
        ]
        lines += [f"  {f['poc_name']} <{f['poc_email']}>, gmail draft {f.get('gmail_draft_id')}"
                  for f in r.drafted]
        if r.drafted_with_prior_contact:
            lines += [f"DRAFTED, PRIOR CONTACT (advisory, check before sending) "
                      f"{len(r.drafted_with_prior_contact)}"]
            lines += [f"  {f['poc_name']} <{f['poc_email']}>: {f.get('collision_note')}"
                      for f in r.drafted_with_prior_contact]
        if r.no_email:
            lines += [f"NO EMAIL FOUND {len(r.no_email)}"]
            lines += [f"  {f['firm_name']}: {f.get('no_email_reason', 'no email found')}"
                      for f in r.no_email]
        if r.duplicate_within_run:
            lines += [f"DUPLICATE WITHIN RUN, blocked {len(r.duplicate_within_run)}"]
            lines += [f"  {f['firm_name']}" for f in r.duplicate_within_run]
        if r.poc_domain_mismatch:
            lines += [f"POC DOMAIN MISMATCH, not drafted {len(r.poc_domain_mismatch)}"]
            lines += [f"  {f['firm_name']}: {f.get('poc_domain_mismatch_reason', 'domain mismatch')}"
                      for f in r.poc_domain_mismatch]
        # Not a failure heading. The gate ran, the POC resolved and the deck
        # exists; only the email is missing, and the reason says why.
        if r.no_posting:
            lines += [f"NO POSTING TO DRAFT AGAINST {len(r.no_posting)}"]
            lines += [f"  {f['firm_name']}: {f.get('no_posting_reason', 'no posting')}"
                      for f in r.no_posting]
        if r.fallback_counts:
            lines += ["", "Fallback telemetry (HARD RULE 4): " +
                      ", ".join(f"{reason}={count}" for reason, count in sorted(r.fallback_counts.items()))]

    lines += [
        "",
        f"Spend: {r.tavily_searches} Tavily searches, {r.llm_tokens} LLM tokens, "
        f"${r.research_cost_usd:.2f} research",
        f"CSV: {r.csv_path}",
    ]
    return "\n".join(lines)


def run_scan(mode: str, days: Optional[int] = None, dry: bool = False,
             gate_cap: Optional[int] = None, progress=tg.progress):
    """Scan, gate, and (unless `dry`) draft. Returns the RunResult.

    Gating always completes and persists regardless of `dry`. Drafting runs
    INLINE right after, in this same call, unless `dry` -- there is no
    separate pursue command (Prompt 1's design) and no confirm gate
    (Prompt 2 step 2a): the spend/draft intent is posted as information, not
    a question, and the run continues.
    """
    result = signal_pipeline.run(mode=mode, progress=progress, gate_cap=gate_cap,
                                 recency_days=days, dry=dry)
    _apply_blocklist_maintenance(result, progress)
    if not dry and not result.cancelled:
        _run_drafting(result, progress)
    return result


def run_single_firm(mode: str, firm_name: str, dry: bool = False,
                     fresh: bool = False, progress=tg.progress):
    """`/scan "Firm"` / `--firm "Firm"`: gate exactly one named firm, skipping
    the scanner entirely. Reuses signal_pipeline.gate_group() and its dbc
    helpers unchanged -- this is new orchestration on top of them, not a
    change to signal_pipeline.py's own grouping/cache/gate logic (DO NOT
    CHANGE signal_pipeline.py, prompt 2's scope).

    Takes the same Postgres advisory run lock signal_pipeline.run() does,
    before creating the wd_runs row -- this is a second front door into the
    same gate machinery and must be covered by the same single mechanism,
    not a second one.

    VERDICT CACHE (run-35 fix). This path used to go straight to gate_group(),
    so every `/scan "Firm"` re-researched from scratch: 6 Tavily searches and a
    fresh chance at a different answer. Live evidence, Choice NY:

        id 65  run 25  batch        gated      qualified  $250M
        id 66  run 27  batch        cached_wd  qualified  $250M   (from 65)
        id 83  run 29  SINGLE-FIRM  gated      parked     no figure

    Run 29 was a single-firm run on the same day as 25/27. The cache would have
    hit on 65 and returned qualified; instead it re-gated and parked, leaving
    two contradictory verdicts for one firm. Now it takes the same cache pass
    the batch path takes, before spending anything.

    `fresh=True` deliberately skips the cache, for when the operator WANTS a
    re-gate -- research improved, the firm changed, or the cached verdict is
    suspect. That is the only way to get a re-gate inside the window, so it has
    to exist: without it, wiring the cache in would make a bad cached verdict
    unfixable until it expired."""
    dbc = signal_pipeline.dbc
    if not dbc.acquire_run_lock():
        raise dbc.RunAlreadyInProgress(
            "Another Workflow D run is already in progress (CLI or bot). "
            "Wait for it to finish, or cancel it, before starting another."
        )
    try:
        run_row = dbc.create_wd_run(mode, recency_days_used=1)
        result = signal_pipeline.RunResult(run_id=run_row["id"], mode=mode,
                                           recency_days_used=1, dry=dry, groups=1)
        group = signal_pipeline.FirmGroup(firm_name=firm_name, firm_key=dbc.firm_key(firm_name))

        # The same cache pass the batch path runs (signal_pipeline.run: window =
        # config.REGATE_WINDOW_DAYS, then verdict_cache_lookup per group before
        # anything is spent), and the same _reuse_cached() writer, so a reused
        # verdict lands identically from either front door: verdict_source
        # 'cached_wd'/'cached_wc' and verdict_cached_from pointing at the row it
        # came from. Parks are never cached (verdict_cache_lookup's own rule), so
        # a parked firm always re-gates here whether or not `fresh` is set.
        cached = None
        if not fresh:
            cached = dbc.verdict_cache_lookup(firm_name, config.REGATE_WINDOW_DAYS)

        if cached:
            progress(f"{firm_name}: reusing the {cached['icp_status']} verdict decided "
                     f"{cached['decided_at']} (row {cached['id']}, {cached['src']}). "
                     f'No searches spent. /scan "{firm_name}" fresh to re-gate.')
            firm = signal_pipeline._reuse_cached(result.run_id, group, cached)
            result.skipped_known.append(firm)
            {"qualified": result.qualified,
             "disqualified": result.disqualified}.get(
                firm["icp_status"], result.parked).append(firm)
        else:
            note = " (fresh, cache skipped)" if fresh else ""
            progress(f"Gating {firm_name} (single-firm override, scanner skipped){note}...")
            firm = signal_pipeline.gate_group(result.run_id, group, progress)
            result.tavily_searches += firm.pop("_search_calls", 0) or 0
            result.llm_tokens += firm.pop("_tokens_used", 0) or 0
            result.research_cost_usd += float(firm.pop("_research_cost_usd", 0) or 0)
            {"qualified": result.qualified,
             "disqualified": result.disqualified,
             "parked": result.parked}.get(firm["icp_status"], result.parked).append(firm)
        signal_pipeline._apply_draft_cap_fields(result)
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
        if not dry:
            _run_drafting(result, progress)
        return result
    finally:
        dbc.release_run_lock()


def run_resume(dry: bool = False, progress=tg.progress):
    """`/resume`: continue the latest crashed or cancelled run from its
    wd_queue, without re-drafting (re-gating) anything already decided.
    Reuses signal_pipeline.gate_group() plus wd_dbc's next_pending()/
    set_queue_status() -- written in Prompt 0/1 but never read back until
    now, since signal_pipeline.run() itself only ever iterates its own
    in-memory `to_gate` list, not the queue. Returns None if there is
    nothing resumable.

    Takes the same Postgres advisory run lock signal_pipeline.run() does,
    before touching the resumable run at all -- a third front door into the
    same gate machinery, covered by the same single mechanism."""
    dbc = signal_pipeline.dbc
    if not dbc.acquire_run_lock():
        raise dbc.RunAlreadyInProgress(
            "Another Workflow D run is already in progress (CLI or bot). "
            "Wait for it to finish, or cancel it, before starting another."
        )
    try:
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
        #
        # THIS IS ALSO THE SKIP LIST, which it was not before (run-33 fix).
        # wd_queue is the resume's only source of work, and signal_pipeline.run()
        # enqueues once and never marks a row done -- so after a crash EVERY
        # enqueued row is still 'pending', including every firm the first
        # attempt already gated. next_pending() handed them all back and the
        # loop re-gated them. Live evidence, run 32: 12 queue rows all pending,
        # 4 firms already gated, and the resume produced a second wd_firms row
        # for each (colliers 87/122, abc imaging 88/123, executive alliance
        # 89/124, eisneramper 90/125) at 6 Tavily searches apiece.
        #
        # The verdict already on the row is the authority on whether a firm
        # needs gating, not the queue's status. A non-NULL icp_status means
        # decided; NULL means the process died mid-gate and it must be finished.
        decided_keys: set = set()
        needs_regate: dict = {}
        for firm in dbc.firms_for_run(run_id):
            status = firm.get("icp_status")
            bucket = {"qualified": result.qualified, "disqualified": result.disqualified,
                      "parked": result.parked}.get(status)
            if bucket is not None:
                bucket.append(firm)
            if status:
                decided_keys.add(firm.get("firm_key"))
            else:
                # In flight when the process died. Re-gated IN PLACE below:
                # this row owns the run's posting_count and the wd_postings
                # rows point at its id.
                needs_regate[firm.get("firm_key")] = firm
        result.groups = len(result.qualified) + len(result.disqualified) + len(result.parked)

        cap = config.GATE_CAP_PER_RUN
        # A generous limit, not an unbounded query -- effectively "all pending
        # rows for this run," which then gets split at `cap` below so the cap
        # guard still applies to a resumed run exactly as it does to a fresh one.
        all_pending = dbc.next_pending(run_id, limit=cap + 10_000)

        # Reconcile the queue against the verdicts before the cap is applied, so
        # a run whose first attempt already gated `cap` firms does not spend its
        # whole resumed budget re-deciding them.
        already_done = [q for q in all_pending if q["firm_key"] in decided_keys]
        for q in already_done:
            dbc.set_queue_status(q["id"], "done")
        if already_done:
            progress(f"Resuming: {len(already_done)} firm(s) already have a verdict for this "
                     f"run, not re-gating them.")
        all_pending = [q for q in all_pending if q["firm_key"] not in decided_keys]
        to_process, still_pending = all_pending[:cap], all_pending[cap:]

        for i, q in enumerate(to_process):
            if dbc.cancel_requested(run_id):
                result.cancelled = True
                still_pending = to_process[i:] + still_pending
                break
            progress(f"Resuming: gating {q['firm_name']} ({i + 1}/{len(to_process)})...")
            group = signal_pipeline.FirmGroup(firm_name=q["firm_name"], firm_key=q["firm_key"])
            firm = signal_pipeline.gate_group(
                run_id, group, progress, existing_firm=needs_regate.get(q["firm_key"]))
            dbc.set_queue_status(q["id"], "done", firm_id=firm["id"])
            result.groups += 1
            result.tavily_searches += firm.pop("_search_calls", 0) or 0
            result.llm_tokens += firm.pop("_tokens_used", 0) or 0
            result.research_cost_usd += float(firm.pop("_research_cost_usd", 0) or 0)
            {"qualified": result.qualified, "disqualified": result.disqualified,
             "parked": result.parked}.get(firm["icp_status"], result.parked).append(firm)

        result.deferred = [SimpleNamespace(firm_name=q["firm_name"]) for q in still_pending]
        signal_pipeline._apply_draft_cap_fields(result)
        dbc.update_wd_run(
            run_id,
            status="cancelled" if result.cancelled else "done",
            finished_at=signal_pipeline._now(),
            companies_gated=len(result.qualified) + len(result.disqualified) + len(result.parked),
            tavily_searches=result.tavily_searches,
            llm_tokens=result.llm_tokens,
            research_cost_usd=result.research_cost_usd,
        )
        _apply_blocklist_maintenance(result, progress)
        if not dry and not result.cancelled:
            _run_drafting(result, progress)
        return result
    finally:
        dbc.release_run_lock()
