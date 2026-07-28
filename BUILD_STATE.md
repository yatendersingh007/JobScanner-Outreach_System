# Workflow D — build state

Built against WORKFLOW_D_BRIEF.md. Steps 0, 1, 2 and 6 of section 10 are done.
Steps 3, 4, 5 and 7 are seamed, not stubbed with fake behaviour: every call
site names the real function and the real signature it needs.

## Done and verified

| File | What it is |
|---|---|
| `migrations/010_wd_tables.sql` | `wd_runs`, `wd_firms`, `wd_postings`, `wd_drafts`, `wd_queue`. Additive, idempotent, `CREATE TABLE IF NOT EXISTS` only. Applies through `lib_snapshot.db.migrate()`. |
| `src/wd_dbc.py` | Postgres helpers in dbc.py's exact style. Includes `verdict_cache_lookup`, which reads `wd_firms` AND `wc_firms`. |
| `src/signal_pipeline.py` | scan → category filter → staffing drop → group by company → verdict cache → capped gate → persisted verdict. Stops before any paid drafting step. |
| `src/wd_config.py` | Budget guards on by default. `TEST_MODE` defaults true. `AUTO_DRAFT_ON_SCHEDULE` defaults false. |
| `src/wd_telegram.py` | Outbound notifications, message-edit live progress, rate limited. |
| `src/daily_run.py` | The 09:00 entrypoint. Scans, gates, posts the summary, stops. |
| `templates/signal_email.md` | New template. No referral language anywhere. **Needs Harp's approval before any live draft.** |
| `deploy/` | systemd oneshot + timer with `Timezone=America/New_York` and `Persistent=true`, plus an installer that verifies with `systemctl show` rather than trusting `systemctl edit`. |
| `tests/test_scanner_core.py` | 75 tests, all green. Title gate keep/drop against the live `config.yaml` regex list, exclusion precedence, malformed-regex tolerance, region detection, dedup semantics, `firm_key`, grouping. |

Run: `pytest tests/` locally. Never on the VM (HARD RULE 5).

## Three real defects the build surfaced

1. **The staffing blocklist does not filter anything today.** BRIEF 4.2 says
   "staffing blocklist already drops recruiters." It does not. In the scanner
   the list lives under `poc_enrichment` in `config.yaml` and is read only by
   `poc_enricher` to skip a TinyFish lookup. `scanner/pipeline.py` never
   consults it. A Robert Half posting for "Fund Accountant" passes the title
   gate, the geo gate and the classifier, and would arrive as a prospect and
   consume a slot out of the daily gate cap. `signal_pipeline.staffing_blocklist`
   applies it as a hard drop before the gate.

2. **`dedup_key` is namespaced per source, so one posting can survive dedup
   three times.** `models.py` returns `f"{self.source}:{...}"`. The same real
   LinkedIn posting reached by JSearch, by the TinyFish LinkedIn guest search,
   and by SelectLeaders is three rows. Harmless for grouping, not harmless for
   the email: `posting_count` and the posting titles go into Block 1 and into
   the grounding corpus, so "you have 3 finance roles open" when it is one role
   seen three times is a false claim in a cold email. `FirmGroup.distinct_titles`
   dedups on the normalized title. Test: `test_posting_count_dedups_the_same_role_from_two_sources`.

3. **`firm_key` collided two different firms, caught by its own test.** The
   first version stripped "group", "management", "partners" and "holdings" as
   suffixes, which collapsed Standish Management and Standish Group to
   `standish`. That is FIX 28's failure mode with a cache in front of it: a
   wrong verdict reused silently. Now only true legal forms are stripped
   (`llc`, `inc`, `lp`, `ltd`...). Paying to gate a near-duplicate name twice
   is cheap. A wrong verdict is not.

## Seams, with the exact signatures they need

Nothing below is faked. Each is a named import that will resolve once the
vendored file lands, and each signature was read off the donor file, not guessed.

- **Gate** — `lib_referral/icp_gate.py`, called as
  `research_and_gate(firm_name: str, progress) -> GateResult`, reading
  `.icp_result` in `{qualified, disqualified, parked}`, `.icp_reason`,
  `.aum_tag`, `.park_reason`, `.park_source`, `.confidence`, `.source_count`,
  `.search_calls`, `.tokens_used`, `.research_cost_usd`, `.research`. Both
  `InfrastructureError` and `BudgetExceeded` are caught and parked with
  `park_source="infrastructure"`, so a retry never reads as a research finding
  about the firm. Vendor unchanged; do not weaken the own-domain resolution.
- **Drafting (step 3)** — `signal_drafting.draft_for_run(run_id, progress)`.
  Reuse `email_drafter.py`'s architecture (generate → validate → retry once →
  per-block fallback → log stage and reason), not its content. Its
  `FIXED_SUBJECT`, `_MANPREET_ATTRIBUTION_RE` and block set are Workflow C's.
  Redefine the checks list against `signal_email.md` section 2 and 3:
  posting title present character-for-character, firm name present, posting URL
  present, both dollar ranges unmodified, zero referral language.
  `fact_check.py` is reused as-is, all three public functions.
- **Deck (step 4)** — `deck_filler.build_and_convert(firm_name, research,
  deck_content, progress, personalization) -> {"pptx_path", "pdf_path",
  "fill_data"}`. Pass the distinct posting titles into `get_deck_content` so
  "Where this fits" can name the hiring need. Needs `assets/Pitch_Master.pptx`
  and `pitch_slots.json`; re-run `scripts/locate_pptx_slots.py` if the master
  is ever re-exported, before restarting the service.
- **POC** — `apollo_enrich`, senior finance titles first. The scanner's
  TinyFish `poc_name` is stored as `poc_name_hint` and is a name hint only,
  never an email source.
- **Cross-workflow dedup** — `dbc.find_prior_contact(linkedin_url, email)`
  from Workflow C, unchanged. Advisory, never blocking (FIX 38). Write the
  result to `wd_drafts.collision_note` / `prior_contact_workflow` and give it
  its own summary bucket.
- **Gmail** — `gmail_client`, `drafts().create()` only. `wd_config.NEVER_SEND`
  exists so preflight can assert it and so the value is greppable.
- **Telegram commands (step 5)** — allowlist filtering in the polling loop, not
  per command, so every future command inherits authorization.

## What blocks the first live run

1. Harp approves `templates/signal_email.md` text. Same gate the referral
   template went through.
2. Vendor `lib_referral/` with provenance headers (source path, commit hash,
   date) and write `DRIFT.md`. The `lib_snapshot` fork already drifted from
   `outreach-system` and that reconciliation is still open. Do not create a
   third unsynced fork casually.
3. New Telegram bot token from BotFather, `AUTHORIZED_USER_IDS` with your ID
   first, `TELEGRAM_CHAT_ID`.
4. Steps 3, 4, 5 built and tested.
5. `TEST_MODE=false`, one manual `/scan pursue` on a real day's output, and
   read every draft in Gmail before enabling the timer.

## Two decisions still open from BRIEF section 11

- Second recipient (senior POC + hiring manager). Built single-recipient;
  `SECOND_RECIPIENT_ENABLED` is the extension point and is deliberately not
  implemented.
- `GATE_CAP_PER_RUN=10` and `REGATE_WINDOW_DAYS=90` are the brief's suggested
  starting values, not confirmed ones. The near-boundary variance in BRIEF 8
  (American Real Estate Partners gated at $63M and $309M on consecutive days)
  argues for a longer window, not a shorter one: re-gating a boundary firm is
  how you get two different answers for the same firm.

## One thing to decide before the timer goes on

`AUTO_DRAFT_ON_SCHEDULE` is false, so the 09:00 run scans and gates and then
stops for a human. That is the right default and it is worth keeping, because
the alternative is drafts appearing in Harp's Gmail from an unattended process
with no one having looked at the day's qualified list. Gating unattended costs
Tavily and LLM tokens. Drafting unattended costs Apollo credits and puts text
in front of Harp that nobody reviewed before it arrived.
