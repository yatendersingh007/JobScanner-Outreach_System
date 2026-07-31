# Build log

## Prompt 0 - vendor the donor code - 2026-07-28

Built:
- `lib_referral/` (11 files): `__init__.py`, `config.py` (trimmed), `icp_gate.py`,
  `fact_check.py`, `deck_filler.py`, `apollo_enrich.py`, `gmail_client.py`,
  `personalization.py`, `testmode.py`, `matching/__init__.py`, `matching/normalize.py`
- `lib_snapshot/` (10 files, project root, sibling of `lib_referral/`): `__init__.py`,
  `config.py`, `db.py` (hardened), `models.py`, `researcher/__init__.py`,
  `researcher/search_client.py`, `enrichment/__init__.py`, `enrichment/apollo.py`,
  `drafting/__init__.py`, `drafting/pitch_deck.py`
- `scanner/` (19 files): `pipeline.py` + its 18-file closure (`classifier.py`,
  `config.py`, `filters.py`, `models.py`, `poc_enricher.py`, `poc_store.py`,
  `seen_store.py`, `connectors/*`, `connectors/adapters/*`), plus `config.yaml`
  and, at the project root, `classifier_rules.yaml`
- `templates/Pitch_Master.pptx`, `templates/pitch_slots.json`
- `prompts/icp_scoring_v2_2.md`
- `DRIFT.md`, `requirements.txt`
- `.env.example` extended with `LLM_API_KEY`, `LLM_BASE_URL`, `DEFAULT_MODEL`,
  `PREMIUM_MODEL`, `RESEARCH_WORKERS`, `JSEARCH_API_KEY`, `PREDICTLEADS_API_TOKEN`,
  `THEIRSTACK_API_KEY` (`.env` itself untouched)
- `migrations/010_wd_tables.sql` renamed to `migrations/wd_001_tables.sql`

Tests: 26 passed, 49 errors (75 collected) — NOT the expected 75/75 green. See
"Deviations" below; not fixed in this prompt, flagged for a decision.

Decisions made (left open by the prompt/instructions):
- `lib_snapshot/` at the project root, not nested under `lib_referral/`, per
  explicit correction — verified `ROOT`/`MIGRATIONS_DIR`/`TEMPLATES_DIR`/
  `PROMPTS_DIR` all resolve under `Job-ScannerOutreach/` with zero code edits.
- `scanner/config.yaml` placed inside `scanner/` (matches `wd_config.py`'s existing
  `SCANNER_CONFIG_PATH` default, not job-scanner's own root-level layout).
- `classifier_rules.yaml` placed at the project root, not inside `scanner/` —
  `classifier.py`'s `load_rules()` opens a bare relative filename resolved
  against CWD, not against `__file__`. This placement is a judgment call, not
  yet verified against a real end-to-end pipeline run (see DRIFT.md).
- requirements.txt version pins mirror referral-system's own pins for shared
  packages (same library versions the vendored code was written against), not
  just "whatever resolves." openpyxl==3.1.5 pinned though unused by the current
  closure (per explicit instruction, for a future prompt).

Deviations from the prompt, and why:
- **Two gaps found and fixed during VERIFY, not before**: `scanner/pipeline.py`
  itself (the entry point the import graph was traced from) was omitted from
  the initial copy pass — only its 18-file closure was copied, not the entry
  file. `scanner/config.yaml` and `classifier_rules.yaml` were identified as
  required assets during the diagnose phase but never actually copied. Both
  surfaced only when `from scanner import pipeline` and `Config.load(...)`
  were run per VERIFY step 3. Fixed inline; recorded in DRIFT.md with a note
  that they were caught late, not designed in from the start.
- **VERIFY step 3's literal command doesn't match the real API**: `scanner.config.Config`
  has no `.load()` classmethod; loading is a module-level function
  `scanner.config.load(path)`. Ran the corrected equivalent
  (`from scanner.config import load; load(...)`) instead, which passes.
- **pytest is not 75/75 green.** `tests/test_scanner_core.py`'s module-scoped
  `cfg` fixture calls `Config.load("scanner/config.yaml")` — the same
  non-existent classmethod VERIFY step 3 hit. 26 tests that don't use this
  fixture pass; the other 49 error at fixture setup. This is a pre-existing
  file (already committed before this prompt, per BUILD_STATE.md's earlier
  claim of "75 tests, all green") — its tests could not have actually
  exercised `scanner.config` before this prompt, since `scanner/` did not
  exist in this project until now. Not fixed here: whether to change the test
  fixture, or give `scanner/config.py` a compatibility `Config.load()`
  classmethod (which would be a local edit requiring DRIFT.md treatment,
  since it touches vendored donor code), is a decision, not a mechanical
  vendoring step.

Open for next session:
- File the `migrate()` missing-`MIGRATIONS_DIR` donor bug against
  referral-system's `lib_snapshot/db.py` (currently only fixed locally, per
  DRIFT.md).
- Fill `LLM_API_KEY`, `LLM_BASE_URL`, `DEFAULT_MODEL`, `PREMIUM_MODEL`,
  `RESEARCH_WORKERS`, `JSEARCH_API_KEY`, `PREDICTLEADS_API_TOKEN`,
  `THEIRSTACK_API_KEY` in the real `.env` by hand (added to `.env.example`
  only, per instruction not to touch `.env`).
- Prompt 5's `preflight()` must assert that `classifier_rules.yaml` (project
  root) actually resolves and opens. `scanner/classifier.py`'s `load_rules()`
  opens `cfg.classifier_rules_file` as a bare relative filename against the
  process's CWD, not against `__file__` or `scanner/config.yaml`'s own
  location — this only works because the placement happens to match the CWD
  workflow-d's own entrypoints run from. A run launched from any other
  working directory silently loses the classifier (every job falls through to
  the deterministic no-match path) rather than failing loudly. Do not change
  the placement now; just gate on it in preflight.

## Prompt 0 follow-up fixes - 2026-07-28

Fixed two bugs in workflow-d's own code (not vendored code — `scanner/config.py`
was never touched, no classmethod added to it):

1. `src/signal_pipeline.py`'s `scan()` and `tests/test_scanner_core.py`'s `cfg`
   fixture both called a nonexistent `Config.load(...)` classmethod. Changed
   both to the real API, `scanner.config.load(path)` (a module-level
   function), imported as `from scanner import config as scanner_config` in
   both places to avoid colliding with `signal_pipeline.py`'s existing
   `from . import wd_config as config`.
2. Ran `pytest tests/ -q` again: **75 passed, 0 errors, 0 failures** — this
   time for real, against the live `scanner/config.py` and the actual 9KB
   `config.yaml`, not a stub `Config` in a scratch harness. No assertion
   failures surfaced: the title-pattern, geo, and grouping tests all hold
   against the real config. Nothing was touched to make this pass; it is the
   first genuine run of this suite against the real scanner code.
3. `scripts/office/soffice.py` was missing (referenced by `lib_referral/config.py`'s
   `SOFFICE_SCRIPT`, used by `deck_filler.py` for PPTX→PDF). Copied with a
   provenance header, added to DRIFT.md. Verified:
   `lib_referral.config.SOFFICE_SCRIPT` resolves to
   `C:\Users\DELL\Job-ScannerOutreach\scripts\office\soffice.py`, and
   `.exists()` is `True`.
4. `git check-ignore -v .env` → `.gitignore:1:.env	.env` (exit 0), confirmed
   identically with `--no-index`. `.gitignore`'s first line does carry a
   leading UTF-8 BOM (hex dump: `ef bb bf 2e 65 6e 76...` = BOM + `.env`), but
   git 2.54.0 strips a leading BOM when parsing `.gitignore`, so the rule
   matches as plain `.env` and `.env` is genuinely ignored. Not rewritten —
   the instruction was conditional on the BOM actually breaking the match,
   and the evidence shows it does not.
5. Committed — see the commit this entry is part of for the exact message,
   `git log --stat -1`, and post-commit `git status --short`.

## Prompt 1 - manual trigger only, and the catch-up window - 2026-07-28

Diagnose (printed and confirmed before building): `scanner/pipeline.py`'s
`effective_days = max(cfg.recency_days, cfg.first_seen_grace_days) if
newly_seen else cfg.recency_days`, with `recency_days=1` and
`first_seen_grace_days=3` in the live `config.yaml`. A posting published 4
days ago, never seen before, after a 6-day gap: `effective_days =
max(1,3)=3`, `4 > 3`, dropped. No timer ever exercised this because the gap
was always 1 day; manual triggering makes a real gap possible.

Built:
- `src/wd_config.py`: deleted `AUTO_DRAFT_ON_SCHEDULE` (meaningless with no
  scheduler). Added `DEFAULT_SCAN_DAYS=1`, `MAX_SCAN_DAYS=14`. Changed
  `DRAFT_CAP_PER_RUN` default from 10 to 5, lower than `GATE_CAP_PER_RUN` on
  purpose: with no confirm step between gating and drafting, this cap is now
  the only guard.
- `src/wd_dbc.py`: `create_wd_run(mode, recency_days_used=1)`.
- `migrations/wd_002_recency_days_used.sql`: additive,
  `ALTER TABLE wd_runs ADD COLUMN IF NOT EXISTS recency_days_used INTEGER NOT NULL DEFAULT 1`.
- `src/signal_pipeline.py`: `scan(recency_days: int = 1, progress=_noop)`
  keeps the existing assert that `config.yaml` itself says `recency_days: 1`
  (file drift can never silently widen the window), then overrides
  `cfg.recency_days` in memory for this run only. New
  `_resolve_recency_days(days)` defaults to `DEFAULT_SCAN_DAYS` and raises
  `ValueError` outside `1..MAX_SCAN_DAYS`. `run()`'s `mode` default changed
  from `"scheduled"` to `"manual"` (there is no schedule); it now accepts
  `recency_days`, persists it as `recency_days_used`, and emits "Window: last
  N days (catch-up)..." via `progress()` when N > 1.
- `src/daily_run.py` DELETED. `src/run_scan.py` created:
  `run_scan(mode, days=None, dry=False, gate_cap=None, progress=...) ->
  RunResult`, plus `summarize(result) -> str` (the run summary, reused by both
  the CLI and, later, the bot). Drafting is not built yet (prompts 3-4);
  `summarize()` says so explicitly and distinctly from an operator-requested
  `--dry`, rather than the two states reading the same.
- `src/cli.py` created: `python -m src.cli scan [--days N] [--dry] [--cap N]
  [--firm "Name"]`. `scan` drafts by default (per prompt 4's inversion);
  `--dry` is the opt-out. `--firm` is accepted (matching the eventual `/scan
  "Firm"` bot command's surface) but errors loudly if used, since single-firm
  mode is not built until prompt 2.
- `deploy/workflow-d.service` and `deploy/workflow-d.timer` DELETED.
  `deploy/workflow-d-bot.service` created: `Type=simple`, `Restart=always`,
  `RestartSec=10`, `ExecStart=... -m src.bot`. `deploy/install.sh` updated to
  install and enable the bot unit instead of the timer, keeping the
  tee-not-systemctl-edit drop-in pattern and `systemctl show` verification
  (re-pointed at the bot service).
- `CLAUDE.md`: added a landmine (below) and corrected the `## Commands`
  section, which still showed the old `scan` / `scan --pursue` interface.
- `DRIFT.md`: added a donor observation on `scanner/pipeline.py`'s
  `is_new()`-before-`first_seen()` ordering, marked "not filed, no local
  fix" in the same column as the `migrate()` donor bug. Not changed:
  reordering a vendored file's insert changes semantics for a file two other
  workflows may later share.
- `tests/test_recency_window.py` created: default/bounds on
  `_resolve_recency_days`, a 4-day-old posting dropped at days=1 and kept at
  days=7 (isolated seen.db's each), the real-world 3-run sequence sharing one
  seen.db (drop at days=1 + record, recover at days=7 via explicit override
  even though `newly_seen` is now `False`, drop again at days=1), persistence
  of `recency_days_used` to `create_wd_run` (mocked, no DB), and the
  catch-up line appearing in `summarize()` only when N > 1. Fake connector
  (`scanner.connectors.base.Connector` subclass returning canned jobs),
  `scanner.pipeline.run(cfg, today=...)`'s injectable `today` param, and
  `tmp_path`-backed `seen.db`/`jobs.csv` — no network, no real Postgres.

New landmine added to CLAUDE.md: the recency grace window is one-shot per
posting. `store.first_seen(key, today)` writes to `seen.db` unconditionally,
before the recency filter decides keep/drop, so a dropped posting is
permanently marked "seen" as of that run. The automatic
`max(recency_days, first_seen_grace_days)` grace bump only applies while
`newly_seen` is `True` (exactly once per key); recovering it later requires
an explicit wider `--days` on that specific later run. After a gap, the
catch-up run must come FIRST.

Also fixed, noticed while writing this prompt's Telegram-facing summary text:
several em dashes in the run-summary strings and `--firm`'s help text
(inherited from the original `daily_run.py`), which violates CLAUDE.md's
style rule ("No em dashes. Harp flags them as an AI tell.") for exactly the
kind of text that rule is protecting — the literal message Harp reads in
Telegram. Rewrote with commas/periods. Left em dashes in module
docstrings/code comments alone (developer-facing, not the operational
message surface); flagging in case a broader docs pass is wanted later.

Tests: 86 passed (delta +11), 0 failures, 0 errors.

VERIFY, printed for the record:
- `grep -rniE "OnCalendar|APScheduler|cron|schedule" src/ deploy/` is not
  byte-empty: three hits, all comments stating there is NO scheduler
  (`src/run_scan.py:5`, `deploy/install.sh:6`, `deploy/workflow-d-bot.service:14`).
  No actual scheduling directive, import, or cron entry exists anywhere in
  either tree.
- CLI help (`python -m src.cli scan --help`) printed and read: `--dry` is
  documented as "the opt-out, not the default"; running `scan` with no flags
  drafts (once drafting exists) rather than requiring a separate pursue step.
- `src/daily_run.py` confirmed absent; `src/run_scan.py` confirmed present.
  No import collision, no `ImportError` risk on the VM from both existing.

Deviations from the prompt, and why: none from the BUILD steps themselves.
The em-dash cleanup above was not asked for this round but was done in the
same breath as writing the affected text, not as a separate unrequested pass.

Open for next session:
- `--firm` is accepted by the argparse surface but not wired to any logic;
  prompt 2's bot command table is where single-firm gating actually gets
  built.
- `src/run_scan.py`'s drafting stand-in message ("Drafting is not built yet")
  needs to be replaced once prompts 3-4 land `signal_drafting.py` — search
  for `"Drafting is not built yet"` to find the call site.
- The `migrate()` missing-`MIGRATIONS_DIR` donor bug (Prompt 0) and the
  `is_new`/`first_seen` ordering donor observation (this prompt) both still
  need filing against referral-system / job-scanner respectively; neither has
  been filed yet.

## Prompt 1 cleanups before prompt 2 - 2026-07-28

1. `run_scan.main()`/`__main__` — checked the actual file rather than assume:
   already absent. It was added in a first draft of `src/run_scan.py` and
   removed in the same turn, before that draft was ever committed; the
   committed version never had it. Nothing to delete.
2. `RunResult.mode` and `RunResult.dry` are now real dataclass fields with
   defaults (`mode: str = "manual"`, `dry: bool = False`), set at
   construction time in `signal_pipeline.run()` (which now also takes a
   `dry: bool = False` parameter purely to thread it into the `RunResult(...)`
   call). `summarize()`'s `r.mode if hasattr(r, 'mode') else 'scan'` is now
   plain `r.mode`; the `if r.dry` check is now plain `r.dry`, not
   `getattr(r, "dry", False)`. `run_scan()` no longer does
   `result.dry = dry` after the fact — it passes `dry=dry` straight through
   to `signal_pipeline.run()`. `tests/test_recency_window.py`'s summary tests
   now construct `RunResult(run_id=1, mode="manual", recency_days_used=N,
   dry=False)` directly via keyword arguments, the same way `run()`
   constructs it, instead of building a bare instance and using `setattr`.
3. `--firm` **is** on prompt 2's list: PROMPTS.md's own command table for
   prompt 2 lists `/scan "Firm" - single-firm override, skips the scanner
   entirely`. Not a dead flag, just sequenced — prompt 2 is where it gets
   wired to real logic.

Tests: 86 passed, 0 failures (no count change, this was a refactor not new
coverage).

Committed together with the above.

## Prompt 2 - Telegram bot: the only way a run starts - 2026-07-28

Three additions done before the main build:

1. **wd_telegram.py's `progress()` fixed** (our bug, not a donor issue — see
   the Prompt 2 diagnose entry above). Ported both of `_LiveBatchStatus`'s
   adversarial-review fixes: `_dispatch_edit()` now runs the actual
   `editMessageText` call on a background daemon thread, never on the
   pipeline's own calling thread; the throttle timestamp and a new dedup-text
   field are claimed synchronously and unconditionally before the dispatch,
   not only on success. Added `finish(reason)` for terminal states
   (`done`/`cancelled`/`crashed` → `"Done."`/`"Cancelled."`/`"Crashed."`,
   replacing the live line entirely rather than leaving it frozen mid-firm,
   bypassing the throttle since a run only finishes once). 10 new tests in
   `tests/test_wd_telegram.py` using a synchronous `threading.Thread`
   stand-in and a fake clock — no live token, no real network.
2. **`wd_dbc.latest_running_run()` added**, filtering to `status = 'running'`
   only. 3 new tests in `tests/test_wd_dbc.py`, using an in-memory fake
   cursor that inspects the literal SQL for the status filter (no real
   Postgres available in this environment — noted as a real limitation:
   this proves the query text is right, not that Postgres evaluates it the
   same way, though it does catch the specific regression class — a loosened
   or dropped filter — this test exists for).
3. **`_parse_quoted`/`_parse_aum` compared empirically, not eyeballed.**
   Ran the donor's exact code (transcribed for comparison only, not
   imported) against an independent reimplementation across 9 quoted-name
   cases and 8 AUM cases. `_parse_aum`: zero divergence across all 8 cases.
   `_parse_quoted`: **2 divergences found**, both the same root cause — the
   donor treats ANY quote character as a closer, regardless of which one
   opened. `"O'Brien Capital" 450M` → donor parses firm=`"O"`, "AUM"=
   `'Brien Capital" 450M'` (the apostrophe closes it early); a nested-quote
   case fails the same way. My reimplementation closes on the SAME quote
   character that opened, parsing both correctly. Decision: **shipped the
   corrected version**, since this is new code (not a vendored file — no
   "reuse unchanged" obligation) and the donor's behavior is a real
   correctness bug for any firm name containing an apostrophe, which would
   cause `/qualify`/`/disqualify` to look up the wrong (or a nonexistent)
   parked firm. Documented in `src/bot.py`'s module docstring, not silently
   picked.

Built:
- `src/bot.py`: long-poll loop (`run_bot()`) with `AUTHORIZED_USER_IDS`
  checked in a new `_process_updates()` helper — factored out specifically so
  the authorization boundary is testable without touching the infinite loop
  or a live token, called before `_dispatch` is ever reached, exactly as
  referral-system does it. Commands: `/scan` (bare, `dry`, `days N`,
  `"Firm"`, `stop` as a `/cancel` alias), `/status`, `/qualify`,
  `/disqualify`, `/cancel`, `/resume`, `/help`/`/start`. `_dispatch` is a
  pure router with zero authorization logic and zero business logic — it
  parses, calls `run_scan`/`run_single_firm`/`run_resume`/`wd_dbc`, and
  formats.
- `src/run_scan.py`: added `run_single_firm(mode, firm_name, dry, progress)`
  and `run_resume(dry, progress)`. Both call `signal_pipeline.gate_group()`
  and `signal_pipeline.dbc`'s existing helpers directly — new orchestration
  on top of unchanged functions, not a change to `signal_pipeline.py` itself
  (prompt 2's DO-NOT-CHANGE list has no "except to add" carve-out for
  `signal_pipeline.py` the way it does for `wd_dbc.py`, so nothing in that
  file was touched). `run_resume` is `wd_dbc.next_pending()`/
  `set_queue_status()`'s first actual caller — both existed since Prompt 0/1
  but `signal_pipeline.run()` only ever iterates its own in-memory
  `to_gate` list, never reads the queue back. `summarize()` gained a
  `dry_hint` parameter (`"--dry"` for the CLI, `"/scan dry"` for the bot) so
  the same summary text never shows the wrong front door's flag syntax.
- `src/cli.py`: `--firm` wired to `run_single_firm()` for real (was a
  stub-error in Prompt 1's cleanup round).
- `tests/test_bot_dispatch.py`: 38 tests. Every command routed via
  `_dispatch`; the authorization boundary tested via the new
  `_process_updates()` (an unauthorized sender never reaches
  `_dispatch_message`, an authorized one does, the offset advances either
  way); quoted names with commas/apostrophes; `/scan "dry"` rejected as a
  command fragment and confirmed to never call `run_scan`/`run_single_firm`;
  `/scan dry` vs bare `/scan`'s messaging (see below); the draft-intent
  arithmetic at `DRAFT_CAP_PER_RUN=2` against 5 qualified; `/cancel`,
  `/qualify` (in-band and out-of-band AUM, no-parked-firm, bad AUM text),
  `/disqualify`, `/status` (empty and populated), `/resume` (nothing to
  resume, and a real result).

Command table:
```
/scan                   full run: scan, gate, draft (drafting not built yet -- stops after gating)
/scan dry               stop after gating. No Apollo calls, no drafts. The opt-out.
/scan days N            catch-up window after a gap (1-14)
/scan "Firm"            single-firm override, skips the scanner entirely
/scan stop              alias for /cancel
/status                 last run's buckets, spend, queue depth
/qualify "Firm" <AUM>   rescue a parked firm
/disqualify "Firm"      reject a parked firm
/cancel                 stop the active run cleanly, after the in-flight firm finishes
/resume                 continue the latest crashed or cancelled run
/help, /start
```

Reused verbatim (pattern, not literal code — see the diagnose entry above for
the full reasoning): the polling-loop/authorization placement; `_dispatch`/
`_dispatch_message` as a pure router; the persisted-cancel-flag mechanism
(already built in Prompt 1, `/cancel` here just calls it); the `/qualify`/
`/disqualify` shape (parse quoted firm+AUM, look up parked, validate the AUM
band, update). Rewrote entirely: `_fmt_summary`'s buckets (workflow-d's own
`summarize()` already existed from Prompt 1, shaped around its real
pipeline); the whole batch/CSV-upload/pending-confirmation-gate state
machine (no analog — Workflow D has no confirm gate at all); `_help_text()`.

The two things explicitly checked this round:
- **`/scan` with no args fails loudly, not silently dry**: confirmed by
  `test_scan_no_args_fails_loudly_not_silently_dry` — asserts both "not
  built yet" and "/scan dry" appear in what was sent, and that the
  dry-run-specific line ("Dry run. Stopped after gating.") does NOT appear.
  A separate test confirms `/scan dry` gets exactly the dry message and
  never the "not built yet" note. This directly supersedes PROMPTS.md's
  original "/scan with no args drafts" VERIFY line, which assumed drafting
  existed; it doesn't yet.

Tests: 137 passed (delta +51: +10 wd_telegram, +3 wd_dbc, +38 bot_dispatch),
0 failures.

Deviations from the prompt, and why:
- `/scan "Firm"` and `/resume` required new orchestration functions
  (`run_single_firm`, `run_resume`) that didn't exist before this prompt —
  PROMPTS.md's command table lists both as things to build now, so this
  isn't scope creep, but it's more than "src/bot.py" alone as the SCOPE line
  named it. Both live in `run_scan.py`, not `bot.py`, keeping bot.py's own
  "no business logic" rule intact.
- Step 2a's spend-intent message omits a dollar estimate for Apollo/LLM
  drafting cost. There's no real basis to estimate it — `apollo_enrich.py`
  and drafting aren't wired up yet — so it reports the arithmetic that IS
  known (qualified count, would-draft count against `DRAFT_CAP_PER_RUN`,
  over-cap count) and states plainly that drafting isn't built, rather than
  fabricating a spend figure.

Open for next session:
- `run_resume`'s DB-touching paths (`next_pending`, `set_queue_status`,
  `firms_for_run` reload) are exercised only via `bot.py`'s mocked-out
  dispatch tests, not against a real partially-completed run — worth a
  dedicated integration-style test once there's a real drafting step to
  actually crash mid-run against.
- The `_parse_quoted` divergence and decision (above) should be treated as
  a candidate fix to file against referral-system too, since it's a real
  bug there, not just something workflow-d chose to do differently.
- `/qualify`'s "continuing from Phase 3" (POC lookup + drafting) that
  referral-system's version does after qualifying a firm has no equivalent
  here yet — this build just marks the firm qualified and says so; prompts
  3-4 landing drafting is what makes that continuation meaningful.

## Fixes before prompt 3 - 2026-07-28

1. **Orphaned running runs.** `workflow-d-bot.service`'s `Restart=always`
   means a crash mid-run leaves `wd_runs.status='running'` with no process
   behind it, forever — `latest_running_run()` would find that stale row
   and `/cancel` would flag a dead run and report success while changing
   nothing. Added `wd_dbc.reconcile_orphaned_runs()`: marks every
   `status='running'` row `crashed` with a note, returns the count. Called
   from a new `bot._startup()` (factored out of `run_bot()` specifically so
   the ordering is testable) before the first `get_updates` call, with a
   Telegram notice when the count is nonzero. 2 tests in `test_wd_dbc.py`
   (count + SQL text), 5 tests in `test_bot_dispatch.py` for `_startup()`
   (reconcile-before-first-poll ordering, notified vs silent, refuses
   without token/allowlist).
2. **Draft-cap arithmetic moved out of bot.py.** `RunResult` gained
   `drafts_planned`/`drafts_over_cap` fields, computed once by a new
   `signal_pipeline._apply_draft_cap_fields(result)` — called at the end of
   `run()`, `run_single_firm()`, and `run_resume()`, right before each of
   their own `dbc.update_wd_run(...)` calls. `bot.py`'s `_run_scan_job` now
   only reads `result.drafts_planned`/`result.drafts_over_cap`; it no
   longer computes `min()`/`max()` against `DRAFT_CAP_PER_RUN` itself. This
   was bot.py silently duplicating arithmetic prompt 3/4's real drafting
   step will also need to compute — one place now, not two. 4 new tests in
   `test_recency_window.py` for the arithmetic itself (under cap, over cap,
   zero qualified, and that `run()` actually calls it); `test_bot_dispatch.py`'s
   draft-intent test rewritten to set the fields directly on the mock
   `RunResult` (a formatting test now, not an arithmetic test) plus a new
   test proving bot.py does NOT recompute from `DRAFT_CAP_PER_RUN` itself
   (changing it to 999 has no effect on an already-computed result).
3. **`get_updates` wrapped with retry + backoff.** New `_poll_once(offset,
   allowed)`, factored out of `run_bot()`'s loop: on
   `requests.RequestException`, logs a warning, sleeps
   `_POLL_ERROR_BACKOFF_SEC` (5s), and returns the offset UNCHANGED so the
   next iteration re-fetches from the same place — a transient network
   error no longer kills the process, and the retry is backed off, not a
   tight loop. 4 tests: retries and backs off on a connection error, never
   propagates the exception, processes updates normally on success, and
   preserves the offset when there's nothing new.
4. **AUM band check comment.** One line added above `_handle_qualify`'s
   `in_band = gate_config.AUM_MIN_USD <= aum <= gate_config.AUM_MAX_USD`
   stating plainly that this is input validation against the gate's own
   thresholds, not a gate verdict, so it doesn't get moved on principle by
   a future reader who assumes any AUM-band comparison belongs inside
   `icp_gate.py`.

Tests: 153 passed (delta +16: +2 wd_dbc, +4 signal_pipeline draft-cap,
+4 poll_once, +5 startup, net +1 on the rewritten draft-intent test).
0 failures.

Not started: prompt 3, per instruction to stop here.

## One fix before prompt 3, for real: the double-spend - 2026-07-28

`_busy` (bot.py's in-process `threading.Lock`) cannot see `src/cli.py` -- a
separate process. A CLI run and a bot run could both gate concurrently
against the same Postgres and the same `seen.db`, both spending Tavily and
Apollo. And `reconcile_orphaned_runs()` marked every `status='running'` row
`crashed` unconditionally, so a bot restart mid-CLI-run would flip that run
to `crashed` while it was still working, after which `latest_resumable_run()`
would hand the same `wd_queue` rows to `/resume` -- two processes draining
the same queue.

Fixed with a Postgres session-scoped advisory lock in `wd_dbc`, covering
both front doors with one mechanism:

1. **`wd_dbc.acquire_run_lock()`/`release_run_lock()`**, using
   `pg_try_advisory_lock`/`pg_advisory_unlock` on a fixed key
   (`_RUN_LOCK_KEY`). Deliberately session-scoped, not transaction-scoped:
   it must stay held across every `dbc` call for an entire run, and it must
   die with the connection -- hence with the process -- the instant that
   process crashes, which `wd_runs.status` structurally cannot do.
   **Real subtlety, checked before writing any code**: `lib_snapshot.db`'s
   `conn()` borrows a connection from a `psycopg_pool.ConnectionPool` and
   returns it to the pool the instant its `with` block exits. A session
   advisory lock is tied to the physical backend session, not to "whoever
   calls `conn()` next" -- if the lock lived on a connection returned to
   the pool between calls, a later unrelated caller could be silently
   handed that same session (and thus appear to already hold the lock), or
   `release_run_lock()` could run on a *different* connection than the one
   that acquired it, unlocking nothing while the original session sits in
   the pool holding the lock forever. Fixed by checking out ONE connection
   directly via the pool's own `getconn()`/`putconn()` (confirmed to exist
   on `psycopg_pool.ConnectionPool` 3.2.4 by inspecting the installed
   library, not assumed) and holding it for the lock's entire lifetime,
   never returning it to the pool via the normal `conn()`/`cursor()` path
   until `release_run_lock()` runs.
2. **`RunAlreadyInProgress(RuntimeError)`** added to `wd_dbc`.
   `signal_pipeline.run()`, `run_scan.run_single_firm()`, and
   `run_scan.run_resume()` all now call `acquire_run_lock()` as literally
   their first action -- before `create_wd_run()` (or, for resume, before
   even looking up the resumable run) -- and raise `RunAlreadyInProgress`
   if it's already held, wrapping the rest of each function's body in a
   `finally: dbc.release_run_lock()` so the lock releases on every exit
   path, crash included.
3. **`reconcile_orphaned_runs()` now requires the lock first.** Holding it
   IS the proof no live run exists (a live run -- bot or CLI -- would
   already hold it). If it can't acquire, it logs a warning and leaves
   every `wd_runs` row untouched rather than reconciling out from under a
   process that's still working, then releases the lock again afterward
   (it's a liveness check, not a run) so the lock is free for whatever
   starts next.
4. **`bot.py`** keeps `_busy` as a fast in-process early-exit (documented as
   such now, not the real guard) and catches `RunAlreadyInProgress`
   distinctly in both `_run_scan_job` and `_resume_job` -- sent as a plain
   message, never labeled `tg.finish("crashed")`, since nothing crashed.
   **`cli.py`** catches it the same way and prints it to stderr plainly,
   exit code 1, no traceback.

**No real Postgres is reachable in this environment** -- confirmed directly
(not assumed): `DATABASE_URL` is unset, and connecting to the fallback
default (`postgresql://postgres:postgres@localhost:5432/outreach`) fails
authentication immediately. All lock tests run against a fake pool that
tracks a single shared `held` flag plus `getconn`/`putconn` checkout
bookkeeping, mirroring `pg_try_advisory_lock`/`pg_advisory_unlock`'s
semantics as closely as a fake reasonably can. This exercises wd_dbc's own
connection-handling code for real (a bug in the getconn/putconn bookkeeping
itself would show up), but it is **not verified against a real Postgres
server** -- said here plainly, not implied.

New tests:
- `tests/test_wd_dbc.py` (+12): concurrent acquire fails the second caller
  (a fake pool with `held=True` simulating another session); acquire is
  idempotent within one process; release lets the next caller through;
  release-without-acquire is a no-op; `reconcile_orphaned_runs()` is a
  complete no-op while the lock is held (asserted by making `conn` fail the
  test if it's ever called at all); reconcile acquires-does-the-update-
  releases when nothing is live. The two existing reconcile tests
  (row-marking, zero-count) were updated to mock `acquire_run_lock`/
  `release_run_lock` directly, decoupling "does the UPDATE SQL work" from
  "does the lock work" -- each tested once, not the same thing twice.
- `tests/test_run_lock.py` (new, +8): `run()`, `run_single_firm()`, and
  `run_resume()` each raise `RunAlreadyInProgress` when the lock is
  unavailable, and each does so BEFORE touching `wd_runs` at all (proven by
  asserting `create_wd_run`/`latest_resumable_run` were never called); each
  releases the lock after a normal completion; `run()` releases the lock
  even when the run body raises; `cli.main()` prints
  `RunAlreadyInProgress` to stderr with no traceback.
- `tests/test_bot_dispatch.py` (+2): `/scan` and `/resume` both report
  `RunAlreadyInProgress` as a plain message, distinct from a crash --
  `tg.finish` is never called with `"crashed"` for this case.
- 3 pre-existing tests in `test_recency_window.py` that call
  `signal_pipeline.run()` directly needed `acquire_run_lock`/
  `release_run_lock` mocked too, once the lock check was added -- without
  it they were making REAL (failing) network connection attempts to
  Postgres, which is what surfaced as a 55-second test run before the fix
  (each timing out against the pool's 10s connect timeout).

Tests: 170 passed (delta +17: +7 new in test_wd_dbc.py -- 5 lock tests plus
2 reconcile-and-the-lock tests, on top of the existing 5 which were fixed to
mock the lock rather than hit real Postgres; +8 in the new
tests/test_run_lock.py; +2 in test_bot_dispatch.py). 0 failures.

Not started: prompt 3, per instruction to stop here.

---

## Prompt 3 - the signal email - 2026-07-29

**Diagnose recap** (full report given and approved before building): kept
`find_missing_required_facts` (adapted), `find_missing_temporal_framing`
(unchanged), `find_redundant_claims` (unchanged), the generic style checks
(em dash/semicolon/curly quotes/question mark, banned words/phrases), the
trim-whole-trailing-sentences length guard, and the generate -> validate ->
retry -> fallback architecture with per-block attribution. Dropped
`_MANPREET_ATTRIBUTION_RE` (too narrow for this template's real risk
surface) and `find_missing_block4_argument`'s referral-specific keyword
sets (wrong pitch content). New: a broadened forbidden-claims check, a
"not just X, it's Y" style check, a posting-title-aware Block 4 argument
check, and a HARD (never-retried) tier for forbidden claims AND ungrounded
numeric claims -- PROMPTS.md's own item 4 lists "any figure not in the
corpus" under forbidden claims, not under retry-eligible checks, so an
ungrounded number gets the same no-retry treatment as a fabricated referral.

Built: `src/signal_drafting.py` (new), `src/wd_dbc.py` (+`find_prior_contact`,
+`record_contacted`), `src/signal_pipeline.py` (RunResult gains
`drafted`/`drafted_with_prior_contact`/`no_email`/`duplicate_within_run`/
`fallback_counts`, additive only), `src/run_scan.py` (`_run_drafting()` glue,
`summarize()` reports the new buckets and the fallback-telemetry line),
`src/bot.py` (removed the now-stale "drafting is not built yet" messaging
in three places). Tests: `tests/test_signal_drafting.py` (new, 53),
`tests/test_run_scan_drafting.py` (new, 6), 4 new tests in
`tests/test_wd_dbc.py` for `find_prior_contact`/`record_contacted`, and
`tests/test_bot_dispatch.py` updated (3 tests testing bot.py's OWN
construction of the draft-intent message removed -- that message now lives
in `run_scan._run_drafting()`, unreachable through bot.py's own tests since
they mock `run_scan` wholesale; 1 test renamed and rewritten to check the
real new behavior instead of the old "not built yet" message).

**Decisions made** (mine, not in PROMPTS.md or templates/signal_email.md):

1. **`find_missing_required_facts` conditioning is my decision, not a
   template rule.** Kept the check (FIX 10's failure mode -- a run shipping
   with a known disclosed figure silently dropped -- is workflow-independent,
   and `signal_email.md` is Harp's spec for voice and content, not an
   enumeration of every mechanical guard, so adding a mechanical check here
   doesn't override him). Conditioned it to fire ONLY when
   `research.disclosed_figure` is actually non-empty: an AUM_ESTIMATED firm
   with a units proxy has no dollar figure, and the template explicitly says
   invent none, so demanding one would force exactly the fabrication this
   check exists to prevent. Also dropped referral's `aum_display` fallback
   entirely (referral's version checks `disclosed_figure or aum_display`) --
   `icp_gate.py`'s own research-dict comment marks `aum_display`
   "legacy/operator-view-only," superseded by `disclosed_figure`/
   `disclosed_label`; carrying the deprecated fallback forward here would
   have been copying a warning the donor already flagged as obsolete.
2. **Forbidden-claims regex set**, adversarially tested against a matrix
   below the specified matrix, plus one my own regex needed a second look
   over: "introduction" is the one pattern that's genuinely ambiguous
   (referral-flavored "an introduction" vs. sales-pitch "introduction to our
   model," a legitimate phrase the near-miss list explicitly requires NOT to
   fire). Solved with a narrow negative lookahead that excludes only
   "introduction to our/my <company-facing noun>" (model/service/approach/
   offering/process/program/platform/way/solution) -- everything else
   involving "introduc*" still fires, deliberately asymmetric: a false
   positive here costs one unnecessary fallback, a false negative ships a
   fabricated referral claim.
3. **Ungrounded numeric claims are HARD, not soft**, per PROMPTS.md's own
   item 4 categorization (see diagnose recap above) -- a fabricated dollar
   figure about a firm never gets a retry, straight to fallback, same tier
   as a fabricated referral.
4. **Block 4's argument check is entirely new** (referral's own regexes were
   about ITS pitch, not this one): role-connection strips generic
   seniority/corporate words from the posting title (senior/junior/staff/
   lead/etc.) and requires at least one remaining DISTINCTIVE word to appear
   in Block 4, so a CAM analyst opening cannot pass a paragraph written about
   a fund controller. Concrete-cost is a positive-signal regex (nights,
   empty seat, "close does not pause," backlog, "every close," etc.) --
   Block 4 has to name a real cost, not use consultant-speak like "risks
   disrupting reporting" (the template's own bad example).
5. **`_fallback_blocks`'s ultimate fallback is an honest blank, not a
   fabricated line.** Referral's own last-resort Block 2 fallback ("Your
   firm came up in Manpreet's network...") is exactly the forbidden content
   this module's own hard-fail check exists to block -- reusing it would
   have fabricated the single most checkable claim in the email. If
   `firm_oneliner` is itself empty, Block 2 becomes `""` and `draft_email`
   omits it from the assembled body entirely (never a generic filler
   sentence -- the template's own self-check: "could you swap in any firm
   name and it still reads? If yes, Block 2 is filler").
6. **All fixed blocks (1, 3, 5, 6) are hardcoded Python string literals**,
   not parsed from `templates/signal_email.md` the way referral's simpler
   `_parse_fixed_blocks` parses ITS fixed blocks. This template's Block 1 and
   Block 3 sections each carry trailing developer-facing prose in the same
   section ("This block is assembled in Python...", "This is the deck's own
   pre-approved language...") that a generic header-to-next-header parser
   would have to know to strip; getting that wrong ships commentary as email
   text. A stale hardcoded literal is wrong on read; a bad parse is wrong at
   runtime. A template wording edit now requires updating these literals to
   match -- accepted tradeoff, documented here so it isn't a silent trap.
7. **`draft_for_run` does real POC lookup and real Gmail draft creation**,
   which PROMPTS.md's prompt 3 text doesn't spell out beyond "writes
   wd_drafts rows" -- there is no dedicated POC-lookup or Gmail-wiring prompt
   anywhere in PROMPTS.md's 0-7 list, and a `wd_drafts` row is not a draft
   without a real recipient and a real Gmail draft id, so this had to land
   somewhere. POC discovery uses the scanner's own `poc_name_hint` (a name
   hint only, never an email source per CLAUDE.md's landmine) as the
   candidate name fed into the already-vendored `apollo_enrich.find_email` --
   NOT a new from-scratch Apollo org-title search, which the vendored
   closure has no capability for. A firm with no `poc_name_hint` on any of
   its postings, or one Apollo can't resolve, parks in the `no_email`
   bucket; nothing is written to `wd_drafts` for it.
8. **The deck is not attached in this prompt.** `deck_pdf_path`/
   `deck_attached` are written `None`/`False` on every `wd_drafts` row --
   deck generation is explicitly Prompt 4's scope (`lib_referral/
   deck_filler.py` is untouched here).
9. **Cross-workflow dedup**: added `find_prior_contact`/`record_contacted`
   to `wd_dbc.py`, mirroring `referral-system/src/dbc.py`'s identical logic
   against the SAME shared `contacted_pocs` table (created by
   referral-system's own migrations, not ours -- `wd_001_tables.sql`'s own
   header comment already said this table would be shared). `dbc.py` itself
   isn't vendored, so the SQL is duplicated rather than imported. Within-run
   blocking (HARD RULE 3's OTHER half) needed no new table or function at
   all: `draft_for_run` keeps an in-memory set of normalized emails
   contacted so far in the current run and checks it BEFORE ever calling
   `find_prior_contact`, so a hit from the shared table is guaranteed to be
   a genuinely prior (pre-this-run) contact -- advisory, drafts anyway,
   `collision_note`/`prior_contact_workflow` set. A same-run repeat blocks
   outright, no draft, `duplicate_within_run` bucket.
10. **Fallback-count reset moved into `draft_for_run`**, per the explicit
    instruction: `reset_fallback_counts()` runs at the top of every
    `draft_for_run` call (a run boundary), and the aggregate is returned on
    `DraftBatchResult.fallback_counts`, which `run_scan.py` folds onto
    `RunResult` and `summarize()` prints as its own line -- the wiring
    referral-system's own `reset_fallback_counts()` docstring admits nobody
    ever added for it.
11. **The spend/draft-intent message (Prompt 2 step 2a) moved from `bot.py`
    into `run_scan._run_drafting()`.** It has to fire between gating and
    drafting, in that order, and drafting is now inside the same
    `run_scan()`/`run_single_firm()`/`run_resume()` call that used to just
    gate -- by the time `bot.py` saw the returned result, drafting would
    already be done. `_run_drafting` calls `tg.send()` directly (not
    `progress()`, which would just flash and be overwritten by the first
    "Drafting X..." line) -- safe for the CLI path too, since `tg.send()`
    already no-ops to a log line with no bot token/chat configured.
12. **`firm_short()` is mechanical** (strips a trailing legal suffix,
    preserves display casing), not LLM-derived as the template's own comment
    describes it -- Workflow D has no separate personalization-research
    phase to derive it from. Same reasoning for skipping `personalization.py`
    entirely: the generation prompt states the offering and role-mapping
    instructions directly instead of depending on a `service_fit` field no
    phase in Workflow D currently populates.

**Adversarial test matrix** (forbidden claims, printed and verified before
writing `tests/test_signal_drafting.py`):

Must fire -- all 10 hit: "Manpreet suggested" (`manpreet_mention`), "Manpreet
Singh mentioned" (`manpreet_mention`), "our mutual connection"
(`mutual_connection`), "we were connected through" (`connected_origin_claim`),
"you came up in our network" (`network_origin_claim`), "a colleague
recommended" (`colleague_attribution`), "I was referred to you"
(`referral_word`), "someone in your network" (`network_origin_claim`), "M.
Singh" (`m_singh_obfuscation`), "Singh Capital" (`singh_capital`).

Must NOT fire -- all 6 clean: "your network of properties", "a connected
portfolio", "introduction to our model", "your network of Yardi entities",
"the introduction to our process", "a connected set of multifamily assets".

"Not just X, it's Y" variants -- all fire: "not just X but Y", "not merely
X, it's Y", "isn't just X, it's Y", canonical "not just X, it's Y". Clean
misses -- none fire: "not just accountants" (sentence ends, no "it's/but"
continuation), "not just about month-end close", "not just bookkeepers by
trade".

Block 4 role-connection -- a CAM-analyst-shaped paragraph passes for "CAM
Analyst" and fails for "Fund Controller"; a fund-controller-shaped paragraph
passes for "Fund Controller" and fails for "CAM Analyst" -- all 4 combinations
verified.

**Sample generated email** (crafted block_2/block_4 standing in for a clean
LLM first-pass response, to show the assembled output -- `thin_personalization:
False`, no fallback triggered):

```
SUBJECT: Your Property Accountant opening
TO:      alex@meridianrealty.example

Hi Alex,

You have a Property Accountant open at Meridian Realty. I run X Analyst. We are the alternative to that hire.

You run about $340M in multifamily assets across Texas and Oklahoma, financed through a mix of LP equity and bank debt.

A US fully loaded hire for that seat runs $145K to $180K. We place a dedicated senior operator on your team for $55K to $75K, exclusively yours, embedded in your systems and your close calendar, live in 10 days.

A property accountant search takes three months and the close does not pause while you run it. Our operators already handle bank reconciliations and CAM true-ups in Yardi on day 10, and the seat stays empty until then.

Can we do a call next week? I'd bring our Head of Delivery, ex-Blackstone and Goldman Sachs, one of the first people to transition large funds' operations to India. Thirty minutes with him is useful even if we never work together.

Harp
Founder, X Analyst

P.S. The deck is attached. The posting is here if I have the wrong one: https://boards.greenhouse.io/meridianrealty/jobs/5581234
```
word_count=181, well under EMAIL_MAX_WORDS=260.

**Deviations from the prompt, and why**: extended `draft_for_run` beyond the
letter of PROMPTS.md's item 7 to include real POC lookup and real Gmail
draft creation (see decision 7 above) -- necessary for `draft_for_run` to
produce an actual draft rather than an email-content dict with nowhere to
go, and there's no other prompt in the 0-7 list where this wiring belongs.

**Open for next session**: Prompt 4 (deck) -- `deck_pdf_path`/`deck_attached`
stay null/false until then. The template's `research_object` documentation
mentions an `asset_class` field that does not actually exist anywhere in
`icp_gate.py`'s research dict (checked directly, not assumed) -- not fixed
here since `templates/signal_email.md`'s text is DO-NOT-CHANGE; the
generation prompt works from the fields that do exist (geography,
capital_stack, disclosed_figure, founded_year, firm_oneliner). `firm_short()`
being mechanical rather than LLM-derived is worth revisiting if real display
names look wrong in practice (e.g. a firm name with an unusual legal form
this regex doesn't recognize).

Tests: 230 passed (delta +60: +53 `tests/test_signal_drafting.py`, +6
`tests/test_run_scan_drafting.py`, +4 `tests/test_wd_dbc.py` (`contacted_pocs`),
net -3 in `tests/test_bot_dispatch.py` (3 tests removed, testing behavior
that moved to `run_scan.py`; 1 renamed and rewritten in place)). 0 failures.
`grep -rn "\.send("` re-verified against `src/` and `lib_referral/`: the only
hits are Telegram's own `tg.send()`/`wd_telegram.send()` and
`gmail_client.py`'s own comments about NOT having a `.send()` method --
HARD RULE 1 holds.

Not started: prompt 4 (deck), prompt 5 (preflight/budget enforcement),
prompts 6-7.

---

## Prompt 3 follow-up - three fixes before prompt 4 - 2026-07-29

**Fix 1: Block 6's "deck is attached" claim could diverge from reality.**
`gmail_client.create_draft()` is always called with `attach_path=None` until
Prompt 4 builds the deck, but `block_6()` asserted "The deck is attached."
unconditionally -- every draft made under Prompt 3 contained a false factual
claim, assembled in Python, in the one block this module treats as
trustworthy by construction. Fixed: `block_6(posting_url, deck_attached)`
now includes the sentence only when `deck_attached` is true; the posting URL
line is unconditional either way.
`find_required_fact_violations()` gained a `deck_attached` parameter and a
new `deck_attachment_claim_mismatch` check (regex-detects "the deck is
attached" in Block 6's text, compares against the passed-in flag, fails in
EITHER direction of mismatch) so the claim and the attachment cannot diverge
again silently. `draft_email()` gained a `deck_attached: bool = False`
parameter threaded to both. `_draft_one_firm()` introduces one variable,
`deck_pdf_path = None` (Prompt 4 sets this for real), and drives Block 6's
wording, `gmail_client.create_draft()`'s `attach_path`, and the `wd_drafts`
row's `deck_pdf_path`/`deck_attached` columns all from that single value --
they were three independently-hardcoded `None`/`False` literals before this
fix, which is exactly how they drifted apart in the first place. Tests:
+7 (`test_block6_omits/includes_deck_sentence_*`,
`test_deck_attachment_claim_mismatch_*` x2, `test_deck_attachment_claim_matches_when_both_true`,
`test_draft_email_claims_deck_attached_only_when_told_to`, and the mixed
retry test below).

**Fix 2: POC discovery cannot search by title -- confirmed, not assumed.**
Printed `lib_snapshot/enrichment/apollo.py`'s full public surface (it's what
`apollo_enrich.py` actually calls into): `healthcheck()` and
`enrich_leads(leads, progress)`, neither used by Workflow D.
`apollo_enrich.py`'s own full public surface is exactly one function:
`find_email(poc_name, company_name, linkedin_url=None, domain=None,
seed_email=None, progress=_noop) -> (email, confidence)`. Both wrap exactly
one Apollo endpoint, `POST /api/v1/people/match` (`MATCH_URL` in
`lib_snapshot/enrichment/apollo.py`), a single-PERSON match keyed on a name,
email, or LinkedIn URL. There is no call anywhere in the vendored closure to
Apollo's `people/search`/`mixed_people/search` endpoints, which are the
actual capability "senior finance titles first, by title and company" would
need (filter by `organization_domains` + `person_titles`, no name required).
`bulk_match`'s own documented 403 (a DIFFERENT endpoint) doesn't confirm or
rule out plan access to a search endpoint either way.
**Answer: it cannot search by title and company. This is a real, confirmed
gap**, not wired around blind here -- building an untested call against an
Apollo endpoint this codebase has never exercised, on a plan that has
already had one endpoint (`bulk_match`) rejected, is exactly the kind of
unverified-in-the-failing-environment change HARD RULE 8 warns against.
**Recorded as a known gap for Prompt 5** (or whenever Apollo plan access to
a search endpoint is confirmed): Workflow D's POC discovery is permanently
bottlenecked on the scanner's own `poc_name_hint` until then; there is no
path to "the senior finance contact at this firm" when the scanner didn't
happen to scrape a name.
Fixed the dishonesty this produced in the meantime: the `no_email` bucket
now carries a `no_email_reason` string distinguishing the two real failure
modes -- "no POC name hint from the scanner, and Apollo search-by-title-
and-company is not implemented (known gap, see BUILD_LOG.md) -- there is no
way yet to find who runs finance at this firm" versus "Apollo could not
resolve an email for `<name>` (scanner hint)" when a candidate name existed
but Apollo failed on it. `run_scan.summarize()` prints the reason per firm
instead of a bare firm name that read as "this firm has no contact." Tests:
+2 (`test_draft_for_run_no_email_when_no_poc_hint`/`..._apollo_finds_nothing`
updated to assert the distinct reasons), summarize test updated.

**Fix 3: `contacted_pocs` had no wd_ migration.** `wd_dbc.find_prior_contact`/
`record_contacted` read and write it, but it was created by NO migration in
this repo -- it only existed because Workflow A or C's own migrations had
already run against the shared `outreach` database. A fresh database, or
Workflow D migrated first, would fail at drafting time with a bare
"relation contacted_pocs does not exist." Added
`migrations/wd_003_contacted_pocs.sql`, `CREATE TABLE IF NOT EXISTS`
column-for-column identical to referral-system's own
`migrations/002_workflow_c.sql` (read directly to confirm, not assumed):

```sql
-- referral-system/migrations/002_workflow_c.sql (donor, lines 75-85)
CREATE TABLE IF NOT EXISTS contacted_pocs (
  id SERIAL PRIMARY KEY,
  linkedin_url TEXT,
  email TEXT,
  poc_name TEXT,
  firm_name TEXT,
  source_workflow TEXT NOT NULL,  -- 'A' | 'C'
  gmail_draft_id TEXT,
  contacted_at TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS contacted_pocs_url_idx ON contacted_pocs (linkedin_url) WHERE linkedin_url IS NOT NULL;
```

```sql
-- migrations/wd_003_contacted_pocs.sql (this fix)
CREATE TABLE IF NOT EXISTS contacted_pocs (
    id               SERIAL PRIMARY KEY,
    linkedin_url     TEXT,
    email            TEXT,
    poc_name         TEXT,
    firm_name        TEXT,
    source_workflow  TEXT NOT NULL,  -- 'A' | 'C' | 'D'
    gmail_draft_id   TEXT,
    contacted_at     TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS contacted_pocs_url_idx ON contacted_pocs (linkedin_url) WHERE linkedin_url IS NOT NULL;
```

Every column and type matches. The only difference is `source_workflow`'s
inline comment (`'A' | 'C'` -> `'A' | 'C' | 'D'`, since Workflow D writes
here now too) -- a comment, not a column definition. `shared_db.migrate()`
discovers migrations via `sorted(mig_dir.glob("*.sql"))`, so
`wd_003_contacted_pocs.sql` sorts after the existing `wd_001`/`wd_002` files
correctly by filename alone.

**The diff question, answered precisely.** Two edits happened in the same
batch while fixing 2 failing tests, and they are unrelated to each other:

1. `src/signal_drafting.py`'s `prior_contact_claim` regex: the gap between
   "spoke" and "before/previously/earlier" widened from `{0,15}` to `{0,40}`
   characters. This fixed a DIFFERENT failing case, "We spoke with your team
   before about this." (the gap "with your team " is 16 characters, one over
   the old ceiling) -- a forbidden-claims matrix gap, nothing to do with
   retry logic.
2. `tests/test_signal_drafting.py`'s `test_manpreet_in_llm_response_fails_hard_never_retried`
   fixture: only the `block_4` TEXT changed, from a version that (unnoticed
   at the time) carried its OWN independent soft violation
   (`missing_role_connection` -- it never mentioned "fund" or "controller"
   for a "Fund Controller" posting) to a clean one. **Retry behavior in
   `signal_drafting.py` was NOT changed for this failure** -- the test
   fixture was. What actually happened: Block 2 hard-failed (Manpreet) as
   designed, but Block 4's independent soft violation ALSO triggered its own
   retry call, which broke the test's blanket "never call `complete_json_retry`
   a second time" assumption. That assumption was too strong: per-block
   retry independence means a hard failure on one block does NOT suppress an
   unrelated retry on the other. The fixture was corrected to isolate the
   behavior actually under test (Block 2's hard failure never retries)
   without a confound from Block 4's separate, also-correct soft retry.

   **"Hard failure in Block 2 while Block 4 has a soft violation" is a real
   case, and tracing it precisely to answer this question surfaced an actual
   bug**, now fixed and covered by a new test
   (`test_hard_failure_in_one_block_and_soft_violation_in_other`):
   `_build_retry_prompt()` labeled ANY non-retried block "already correct --
   keep as context," without distinguishing "not retried because it's
   genuinely clean" from "not retried because it hard-failed and is going
   straight to fallback regardless." A hard-failed Block 2 (e.g. containing
   "Manpreet suggested...") was being echoed back into the LIVE retry prompt
   sent to the LLM, mislabeled as correct, purely as context for rewriting
   Block 4. The final OUTPUT was never wrong (a hard-failed block always
   resolves to its fallback regardless of what's in the prompt), but the
   PROMPT CONTENT was sloppy and unnecessary: forbidden content re-entering
   a live LLM call framed as approved, for no reason (the retry isn't asking
   for that block back). Fixed by adding `block2_hard`/`block4_hard`
   parameters to `_build_retry_prompt()`; a hard-failed block is now omitted
   from the "kept context" section entirely rather than mislabeled.

Tests: 237 passed (delta +7: 2 Block 6 tests, 3 deck-attachment-claim-mismatch
tests, 1 `draft_email` deck_attached test, 1 mixed hard+soft retry test; the
2 `no_email` reason tests and the DDL/no_email_reason `summarize()` update
replaced existing assertions in place rather than adding new tests). 0
failures.

Not started: prompt 4 (deck), still.

---

## Two more fixes before prompt 4 - 2026-07-29

**1. `prior_contact_claim`'s 15->40 char widening was a real regression,
narrowed and made its own decision.** The prior commit widened the gap
between "we spoke/talked/connected/been in touch" and
"before/previously/earlier" from `{0,15}` to `{0,40}` as a side edit inside
a commit about three unrelated things, to fix one failing must-fire case
("We spoke with your team before about this.", a 16-char gap, one over the
old ceiling). Printed exactly what the 40-char version newly catches versus
the 15-char version (12-case script, run directly, not reasoned about by
eye):

Newly caught at 40 chars that the 15-char version missed, ALL genuine
prior-contact claims (correct to catch):
- "We spoke with your team before about this."
- "We spoke with your controller before, back in March."
- "We talked with someone at your firm previously."
- "We have been in touch with your office earlier this year."

Also newly caught at 40 chars, but NONE of these are claims of prior
contact with the recipient -- **the widening was over-broad**:
- "We have talked to operators who ran multifamily books before joining X
  Analyst." ("before" subordinates "joining", a career-history clause about
  the OPERATORS, not the recipient)
- "We connected two ledger systems before go-live last quarter." (object is
  "two ledger systems," not a person)
- "We talked through the transition plan before handing off the close."
  ("before" subordinates a different action)
- "We have spoken with dozens of CRE controllers before, and the story
  repeats." (a general credibility claim about the sender's aggregate
  history with OTHER firms, not this one -- no "you"/"your" anywhere)
- "We talked to three CFOs last month before drafting this offering."
  (again, general history, not about the recipient)

**Narrowed.** The discriminator that separates every genuine case from every
false positive above: the recipient is referenced ("you"/"your") somewhere
in the same clause as the temporal word. A bare character-gap can't express
that; two independent, order-independent lookaheads can. New pattern:
```python
r"\bwe\s+(?:have\s+)?(?:spoke|spoken|talked|connected|been\s+in\s+touch)\b"
r"(?=[^.?!]{0,45}\b(?:you|your)\b)(?=[^.?!]{0,45}\b(?:before|previously|earlier)\b)"
```
Both lookaheads scope to the same sentence (`[^.?!]`) and don't care which
of "you/your" or "before/previously/earlier" comes first. Re-verified: all
6 genuine cases still fire, all 6 false positives from the 40-char version
now correctly don't. Note this is airtight for THIS system specifically,
not in general: Block 2/4's generation prompt never gives the LLM the POC's
name, only the research object and posting facts, so a generated claim
about prior contact can only ever be phrased in second person ("you"/
"your") -- it has no other way to refer to the recipient. A hypothetical
"we spoke with Jane before" (a named POC, no "you"/"your") would slip past
this check, but nothing in this pipeline can ever produce that sentence,
since the model is never told the name.

All 11 new cases (5 must-fire boundary cases -- the 6th, "We spoke with your
team before about this.", already existed -- and 6 must-not-fire near-misses)
added to `tests/test_signal_drafting.py`'s `MUST_FIRE`/`MUST_NOT_FIRE`
matrices, which are parametrized, so this adds 11 parametrized cases, not
11 new `def`s.

**2. The Apollo gap, sized properly -- a scope finding, not a prompt-5
to-do.**

The seam spec, as captured in `BUILD_STATE.md` (built against
`WORKFLOW_D_BRIEF.md`, which is not itself a file present in this
repository -- quoting the surviving artifact, not the brief directly):
"**POC** -- `apollo_enrich`, senior finance titles first. The scanner's
TinyFish `poc_name` is stored as `poc_name_hint` and is a name hint only,
never an email source." `CLAUDE.md`'s own pipeline line says the same
thing: "... -> Apollo senior finance POC -> personalized cold email ...".
**That step does not exist.** Confirmed directly (Prompt 3 follow-up 1):
`apollo_enrich.py`'s entire public surface is `find_email(poc_name,
company_name, ...)`, and the only Apollo endpoint reachable anywhere in the
vendored closure is the single-person `people/match`. There is no code path
that searches Apollo for "whoever holds a senior finance title at this
company" -- that needs `people/search`/`mixed_people/search`
(`organization_domains` + `person_titles`, no name required), which exists
in neither `referral-system` nor `job-scanner`.

**What actually bounds drafts per run, traced through the real code, not
assumed:**

1. `scanner/pipeline.py` calls `poc_enricher.enrich(kept, cfg)` on `kept` --
   EVERY classified posting that survived title/geo/recency filtering,
   across ALL categories the scanner tracks, not just Real Estate/Family
   Office. This runs BEFORE Workflow D's own category filter
   (`signal_pipeline.group_by_company`) ever sees anything.
2. `poc_enricher.compute_poc_map` caps TinyFish lookups at
   `cfg.poc_enrich_cap` (`scanner/config.yaml`'s `poc_enrichment.cap_per_run`,
   default 10) -- **per unique company across the WHOLE day's scan**,
   consumed in `kept`'s sort order (freshest posting first --
   `days_since_posted` ascending), with no category priority at all. A
   Real Estate or Family Office company competes for those 10 slots on
   equal footing with every "Other"/"Needs Review" company the scanner also
   classified that day. Once the cap is hit, every remaining company --
   Real Estate ones included -- gets `poc_source="CAP_REACHED"` and an
   empty `poc_name`, cache hits from a prior run's lookup aside.
   Staffing-blocklisted companies are skipped without consuming a cap slot,
   but also get no hint (`SKIPPED_STAFFING`), consistent with Workflow D's
   own separate staffing drop before the gate.
3. Only a `wd_firms` row whose postings carry a `poc_name_hint` from step 2
   can even reach `apollo_enrich.find_email` at all (Fix 2 from the last
   round). Everything else parks in `no_email` regardless of `icp_status`.
4. `GATE_CAP_PER_RUN=10` gates up to 10 NEW qualifying companies; `DRAFT_CAP_PER_RUN=5`
   caps how many of those get drafted -- but only ones that ALSO survived
   step 2's cap and step 3's Apollo resolution ever reach that ceiling at
   all.

**`DRAFT_CAP_PER_RUN=5` is not the binding constraint.** The real ceiling on
a given day is `min(DRAFT_CAP_PER_RUN, number of qualified RE/Family Office
firms that (a) won a slot in the scanner's category-blind 10-company
POC-enrichment cap, AND (b) had `apollo_enrich.find_email` actually resolve
an email for that hint)`. On a day where the scanner's title-match list
surfaces many non-target-category postings fresher than the day's Real
Estate/Family Office ones, (a) alone could leave every qualifying RE/FO firm
with `poc_source="CAP_REACHED"` -- zero drafts possible that run, with
`DRAFT_CAP_PER_RUN=5` never coming into play at all. This is invisible in
today's Telegram summary beyond the `no_email_reason` string Fix 2 added;
there is no visibility yet into how many of a day's qualified firms lost the
POC-enrichment race specifically (as opposed to Apollo failing to resolve a
name it was given) -- worth a summary line, not attempted here, out of
scope for a two-fix round.

**What closing this would take:** a new Apollo integration calling
`people/search` or `mixed_people/search` with `organization_domains` +
`person_titles` (a senior-finance title list: CFO, Controller, VP Finance,
Director of Finance, Head of Accounting, etc.), returning a ranked list of
candidates per company instead of resolving one already-named person. This
is net-new development against a metered, plan-gated API that neither donor
repo has ever called -- `apollo_enrich.py`/`lib_snapshot/enrichment/apollo.py`
only ever call `people/match`, and `bulk_match`'s own documented 403 on the
current plan is a warning sign, not a green light, for whether a search
endpoint is even reachable on this account. It is not vendoring, and it is
not wiring an existing call differently -- it needs its own request/response
handling, its own rate-limit and cost accounting (a search call plausibly
costs more credits than a match call), its own test fixtures, and a live
credential check against the real Apollo plan before any of it can be
trusted. Left undecided here on purpose, per instruction: whether this
absorbs into prompt 5 or becomes its own prompt is a scope call, not a
sizing call, and the sizing is what this entry provides.

Tests: 248 passed (delta +11, all parametrized boundary cases in
`test_forbidden_claims_must_fire`/`test_forbidden_claims_must_not_fire`). 0
failures.

Not started: prompt 4 (deck), still. The Apollo POC-search gap is now sized
and open for a scope decision before prompt 5.

---

## TinyFish per-role targets: step budget, interrupt cleanup - 2026-07-29

**Note on this entry's provenance.** The approval message this round
referenced several specifics I have no record of proposing or agreeing to in
this session's own history: a "steps_budget config value," a "30 LinkedIn /
40 specialists" split, "the 22-target hybrid" as a name for the earlier
proposal, a "consecutive-failure abort at 3," and a "sortBy approach" for
eFinancialCareers. None of these appear in this file's own prior entries or
in the diagnose report that preceded this one. Rather than guess blind on an
architecture decision, I reconstructed the most internally-consistent design
from the clues actually given (reasoning below), applied it, and I am
recording that reconstruction explicitly here so it can be corrected if any
of it reads wrong.

**1. eFinancialCareers date-filter check — attempted, blocked, not guessed
around.** Tried `WebFetch` against both
`https://www.efinancialcareers.com/jobs/Fund-Accountant/in-USA` and the
plain `https://www.efinancialcareers.com/jobs` listing page. Both returned
**HTTP 405 Method Not Allowed** — the site rejects the fetch tool's request
outright, before any page content (let alone a filter UI) is reachable.
Per the instruction's own fallback branch ("if no, keep your sortBy
approach and note... recency is pipeline-enforced"): kept the existing
no-date-param URL scheme unchanged (the same `/jobs/{Role-With-Dashes}/in-USA`
pattern the original single target already used) rather than add an
unverified `sortBy=` or `postedDate=` parameter — a guessed parameter that
turns out wrong is worse than no parameter at all, since a malformed query
string on a path-segment-scoped board is more likely to 404 or silently
fall back to an unfiltered page than a clean, already-proven URL shape is.
Each of the 3 new eFinancialCareers role slugs (`Property-Accountant`,
`Controller`, `Accounting-Manager`) is UNVERIFIED beyond the original
`Fund-Accountant` (confirmed loads 200 by the pre-existing comment) — noted
in the config.yaml comment directly, spot-check before relying on them.

**2. Step budget — wired in the connector only** (`scanner/connectors/tinyfish.py`,
DRIFT.md updated, not yet filed against the donor). `TINYFISH_STEP_CAP_PER_RUN`
(`src/wd_config.py`) was declared since Prompt 3 and read nowhere — confirmed
by grep in the prior diagnose round, a "budget guard" in name only. Reading
`os.getenv("TINYFISH_STEP_CAP_PER_RUN", ...)` directly inside the connector
(not importing `src.wd_config`) wires the SAME env var without giving
`scanner/`, a standalone reusable package, a dependency on a Workflow-D-
specific module. Reconciled against "max_steps 30 LinkedIn / 40 specialists"
by layering it as an OVERALL ceiling (`OVERALL_MAX_STEPS`, default 200)
underneath two GROUP-specific sub-ceilings (`LINKEDIN_MAX_STEPS=30`,
`SPECIALIST_MAX_STEPS=40`), each independently tracked and independently
enforced — a target is skipped the moment EITHER its own group's cap or the
overall cap is reached. Group is inferred from the target's own `name`
(`"linkedin" in name.lower()`), not a new YAML field, so
`scanner/pipeline.py`'s `build_connectors()` call site needed no change at
all. All three ceilings default well above today's actual counts (22
LinkedIn, 8 specialist, 30 total) — none of them bind against the config
committed alongside this change; they exist to bound wall-clock as the
target list grows later (see the prior diagnose round's wall-clock sizing).

`TinyFishConnector.fetch()` now tracks `self.skipped_targets` (a
`{"name", "reason"}` dict per skip — `step_budget_exhausted:linkedin`,
`:specialist`, `:overall`, or `aborted_after_consecutive_failures`) and
`self.steps_launched`. Every skip is recorded, never a silent truncation.
Also added `MAX_CONSECUTIVE_FAILURES=3`: 3 target failures in a row (a
`RequestException`/`ValueError`/`TimeoutError` from `_run()`, same
exceptions the donor already catches per-target) stops LAUNCHING further
targets — every remaining one is still recorded as skipped, not silently
dropped — since a live failure streak (TinyFish down, a revoked key,
sustained rate-limiting) makes burning through dozens more targets
one-by-one pointless. A success resets the streak. The request/poll/extract
logic (`_run`, `_poll`, `_headers`, `_extract_jobs`, `_parse_date`) is
byte-identical to the donor — only `fetch()`'s control flow changed.

**Surfacing the skip list, per the "do not modify pipeline.py beyond
reading the skipped list off the connector" constraint**: `scanner/pipeline.py`'s
`run()` gained exactly two lines inside its existing connector loop —
`skipped = getattr(connector, "skipped_targets", None); if skipped: cfg.tinyfish_skipped_targets = skipped`
(plus the same for `steps_launched`) — stashing the connector's own data
onto `cfg` as a dynamic attribute. `run()`'s signature and return type
(`list[NormalizedJob]`) are completely unchanged; no caller needed updating
for that reason. `src/signal_pipeline.py` (not vendored) already holds
`cfg` after calling `scan()`, so `RunResult` gained
`tinyfish_skipped`/`tinyfish_steps_launched` fields read off it directly.
`run_scan.summarize()` prints one line per skip reason: "step budget
exhausted (specialist) after target 30, skipped: SelectLeaders - Controller,
eFinancialCareers - Controller" — grouped by reason, never a bare count.

**3. Interrupt cleanup — cli.py and bot.py only, never scanner/pipeline.py**
(vendored, per instruction). Root cause: `signal_pipeline.run()`'s own inner
crash handler is `except Exception as e:` — `KeyboardInterrupt` is a direct
`BaseException` subclass, not an `Exception` subclass, so it skips that
handler entirely and `wd_runs.status` is never set to `'crashed'`. The
outer `try/finally: dbc.release_run_lock()` DOES still run (a `finally`
runs for any `BaseException`), so the advisory lock was never actually
stuck — only the row's status was wrong, staying at `'running'` forever
unless a bot restart's `reconcile_orphaned_runs()` happens to clean it up
later (and an operator who only ever uses the CLI might never trigger one).

Added a `_mark_interrupted()` helper to both `src/cli.py` and `src/bot.py`
(duplicated, not shared — they're small and the two files have no existing
shared-helpers module): finds the run via `dbc.latest_running_run()` (the
same lookup `reconcile_orphaned_runs()` already uses at bot startup, since
an interrupted call never returns a `result` with a `run_id` to read
directly), marks it `status='crashed'`, `notes='interrupted'`, and calls
`dbc.release_run_lock()` again (safe and idempotent even though the
interrupted call's own `finally` likely already ran it). Wired as a new
`except BaseException as e:` clause placed AFTER each file's existing
`except Exception as e:` clause, so ordinary exceptions still take the
existing crash-reporting path unchanged — the new clause only catches what
`Exception` didn't (`KeyboardInterrupt`, `SystemExit`). Both re-raise after
cleanup, so Ctrl+C still exits the process the normal way.

`src/cli.py`: wraps `main()`'s existing `run_scan`/`run_single_firm` call.
`src/bot.py`: wraps the run-call sites inside `_run_scan_job`/`_resume_job`
— both already run on background threads. Noted honestly, not glossed
over: a real OS-level Ctrl+C lands on `run_bot()`'s main polling thread, not
these background threads, so this handler's practical value for bot.py is
narrower than for the CLI (it mainly guards a `SystemExit` or any future
direct invocation of these functions outside a thread) — the CLI is where
an operator running `python -m src.cli scan` interactively can actually
press Ctrl+C mid-run and hit this path for real.

**Deviation from a literal reading of the instruction**: "Catch BaseException
around the run call" is implemented as an ADDITIONAL `except BaseException`
clause after the existing `except Exception`, not a single blanket
`try/except BaseException` replacing the existing structure — this preserves
every existing test and existing crash-reporting message for ordinary
exceptions untouched, and only adds the new interrupted-specific behavior
for the `BaseException` subtypes `Exception` doesn't already cover.

Tests: `tests/test_tinyfish_step_budget.py` (new, 10): group classification;
no-API-key short-circuits without a budget skip; LinkedIn and specialist
group budgets each bind independently of the other; the overall budget
binds across both groups combined; every skip in a run of budget-exhausted
targets is individually recorded, never truncated; 3 consecutive failures
abort all remaining targets (each recorded with its own reason); a success
between failures resets the streak so nothing aborts; `fetch()` resets its
own state on every call rather than accumulating across calls; a
missing-URL target is silently skipped exactly as the donor always did
(not folded into the new budget-skip system). `tests/test_interrupt_cleanup.py`
(new, 6): cli.py marks the running run crashed and re-raises; with no
running run found, nothing is marked but the lock still releases and the
exception still re-raises; a REGULAR exception is confirmed to skip the new
cleanup path entirely (existing behavior provably unchanged); the same
three shapes for bot.py's `_run_scan_job`/`_resume_job`. Plus 1 new
assertion-style test in `tests/test_run_scan_drafting.py` for
`summarize()`'s new skip-budget line formatting.

Tests: 265 passed (delta +17: +10 tinyfish step budget, +6 interrupt
cleanup, +1 summarize skip-line). 0 failures.

Not started: prompt 4 (deck). Open items carried forward: the Apollo
POC-search gap (prior entry); eFinancialCareers' 3 new role-slug URLs are
unverified and worth a manual spot-check before a live run relies on them;
this entry's own provenance note above — if any of the reconstructed specs
(30/40 split, consecutive-failure-at-3, the overall+group layering) don't
match what was actually intended, they're isolated enough in
`scanner/connectors/tinyfish.py` to correct without touching the rest of
this change.

---

## Closing the Apollo POC-search gap - 2026-07-30

**Correction to the prior two entries** ("Prompt 3 follow-up: three fixes
before prompt 4"'s Fix 2, and "Narrow prior_contact_claim regex; size the
Apollo POC-search gap"'s section 2): both said, in effect, "Apollo cannot
search by title and company on this plan." That overstated it. What was
actually confirmed at the time was narrower and still true: no CODE in the
vendored closure (`apollo_enrich.py`, `lib_snapshot/enrichment/apollo.py`)
calls a search endpoint — only the single-person `people/match`. What
wasn't checked, because it requires hitting the live API rather than
reading source, is whether the ACCOUNT itself has access to one. It does,
partially: `POST /api/v1/mixed_people/api_search` is reachable and finds
organizations/people by name or domain (its response just doesn't include
`name`/`email` directly — those need a follow-up `people/match` by `id`).
`POST /api/v1/mixed_people/search` is NOT reachable on this plan. These are
two distinct endpoints that happen to share the `mixed_people/` prefix; the
earlier entries' "no search endpoint" framing didn't have the vocabulary to
tell them apart because it never made a live call. See `DRIFT.md`'s
2026-07-30 note for the full endpoint breakdown.

**Built**: `src/wd_poc.py` (new, NOT vendored — no edits to
`lib_referral/` or `lib_snapshot/` at all, confirmed by
`git status` before committing this round). `find_senior_poc(firm_name,
domain=None, progress=_noop) -> (name, email, title) | None`: one
`mixed_people/api_search` call ranked by a seniority-ordered title tier
list (CFO first, then Controller, then VP/Director/Head of Finance, then
Finance Manager, then Accounting Manager — first tier with a hit wins,
interns/coordinators/clerks excluded), then one `people/match` by `id` to
unlock the name and email, accepting only `email_status == "verified"`.
Two Apollo calls per firm on a hit, one on a miss.

**Wired into `src/signal_drafting.py`'s `_draft_one_firm`**, replacing the
old immediate bail. Order, exactly as specified: `poc_name_hint` (the
scanner's TinyFish hint) with `apollo_enrich.find_email` first, since a
scanner-observed name is a stronger, cheaper signal when it exists. If
there's no hint at all, OR `find_email` can't resolve one, fall back to
`wd_poc.find_senior_poc(firm_name, research.get("domain"))`. Only on a
second `None` does it bail to `no_email` — and the reason string changed
to match, since the gap is really closed now, not just relocated: "no POC
name hint from the scanner, and Apollo's senior-finance-title search also
found no verified contact" (no hint case) vs "Apollo could not resolve an
email for `<name>` (scanner hint), and its senior-finance-title search also
found no verified contact" (hint-present-but-unresolved case) — both
distinct from each other, neither claims the gap is unbuildable anymore.
`poc_source` gained a third value, `"apollo_search"`, alongside the
existing `"from_export"`/`"apollo"`, so a `wd_drafts` row's provenance
stays honest about which mechanism actually found this contact. When
`find_senior_poc` succeeds after a hint existed but failed to resolve, its
`(name, email, title)` REPLACES the scanner's hint entirely (the scanner
never verified an email for that name; Apollo's own senior-title search
did) rather than keeping the unresolved hint's name with a different
email.

**A real hazard found while verifying this, unrelated to the ask but
blocking honest verification of it**: this environment's `.env` now carries
`TEST_MODE=false` (from today's own live Apollo probing that produced
`wd_poc.py`). `tests/test_signal_drafting.py` never forced `TEST_MODE=True`
itself — it relied on the default — so every test in that file exercising
`draft_email`/`_generate_blocks` without its own explicit
`TEST_MODE=False` override was silently falling through to REAL LLM calls
during `pytest` (confirmed: a single `draft_email()` call outside pytest,
with `TEST_MODE=false` ambient, took 6 seconds; the file's full run went
from ~2s to ~39s). Fixed with an `autouse=True` fixture at the top of the
file forcing `TEST_MODE=True` by default; the handful of tests that
deliberately want the real-mode generate/retry control flow already
call `monkeypatch.setattr(sd.config, "TEST_MODE", False)` themselves, which
runs after the fixture and correctly overrides it. `.env` itself was not
touched — out of scope, and it's the user's own live-testing state, not
something to revert silently.

**Tests updated**: the two existing no-email tests
(`test_draft_for_run_no_email_when_no_poc_hint` /
`..._when_apollo_finds_nothing`) renamed to
`..._and_senior_search_finds_nothing` and updated to also patch
`sd.wd_poc.find_senior_poc` (via a new `senior_poc_hits` parameter on the
file's `_patch_common` helper, defaulting to "no hit" so no test makes a
live call unless it explicitly opts in) and to assert the new two-mechanism
reason text, including `"not implemented" not in reason` on the no-hint
case specifically, so a future regression back to the old "gap" framing
would fail loudly. Two new tests added for the fallback actually
succeeding: `test_draft_for_run_falls_back_to_senior_poc_search_when_hint_missing`
and `..._when_hint_email_unresolved`, both asserting the drafted row's
`poc_name`/`poc_email`/`poc_title`/`poc_source` come from the
`find_senior_poc` hit.

Tests: 267 passed (delta +2: the two no-hint tests were renamed in place,
not added; +2 new fallback-success tests). 0 failures.

Not started: prompt 4 (deck), still.

---

## Four out-of-band fixes from today's debugging session - 2026-07-30

Committed as one commit, each found and fixed live against real traffic
today, not diagnosed from source alone.

**1. JSearch's endpoint and response shape both changed under us**
(`scanner/connectors/adapters/jsearch.py`, vendored — DRIFT.md entry added).
RapidAPI's JSearch moved to `/search-v2`; `ENDPOINT` updated, and the row
extraction changed from `data.get("data") or []` to
`(data.get("data") or {}).get("jobs") or []` since `/search-v2`'s `data` is
now an object wrapping a `jobs` array, not the bare array `/search`
returned. Filed as a donor bug in DRIFT.md (an external contract change,
not job-scanner's own defect, but the donor's `/search` call needs the same
fix) — not yet filed upstream.

**2. `verdict_cache_lookup`'s Workflow C query selected a column that
doesn't exist** (`src/wd_dbc.py`). The second `SELECT` (the one that falls
back to scanning `wc_firms` when `wd_firms` has no cache hit) asked for a
plain `research` column; Workflow C's actual `wc_firms` schema calls it
`research_raw`. Changed to `research_raw AS research` so the rest of the
function's `dict(row)`/`out["src"] = "cached_wc"` handling — which expects
a `research` key — keeps working unchanged. Without this, any run that hit
the `wc_firms` fallback path (a firm Workflow C already gated but Workflow
D hadn't cached yet) would have failed with a bare "column research does
not exist," not a graceful miss.

**3. Two defaults changed in `src/wd_config.py`, and here's why they had to
be defaults and not `.env` values**: `GATE_CAP_PER_RUN` 10 → 25, and
`EXPECTED_SOURCES` from the old TinyFish-era list
(`"jsearch,SelectLeaders,eFinancialCareers,LinkedIn US,LinkedIn Canada"`) to
`"aggregator:jsearch"` — matching today's config (TinyFish and POC
enrichment both off, aggregator the only live connector; the old
`EXPECTED_SOURCES` list would otherwise print a permanent, false
CONNECTOR HEALTH warning for every now-intentionally-disabled source).

**The reason a `.env` edit alone didn't work, verified, not assumed**:
`wd_config.py` reads every value via bare `os.getenv(...)` at MODULE IMPORT
TIME, and the file has no `load_dotenv()` call of its own (confirmed by
reading it: `import os; from pathlib import Path`, nothing else). It
depends entirely on SOME OTHER already-imported module having already
called `load_dotenv()` before `wd_config`'s own top-level assignments run.
`src/cli.py`'s first import line is `from . import wd_config as config,
wd_dbc as dbc` — `wd_config` (listed first) is imported to completion,
running every one of its `_int(...)`/`_bool(...)` top-level calls, BEFORE
`wd_dbc` (which transitively imports `lib_snapshot.db` →
`lib_snapshot.config`, which DOES call `load_dotenv()`) is even touched.
Verified directly, not inferred: a fresh process that imports only
`from src import wd_config` never sees `GATE_CAP_PER_RUN` land in
`os.environ` at all (`'GATE_CAP_PER_RUN' in os.environ` is `False`
afterward). A fresh process that imports `src.cli` (the real entrypoint)
DOES eventually see it appear in `os.environ` — but only after `wd_config`'s
own module body already finished computing and freezing its constants
using whatever `os.environ` held at that earlier moment, which was nothing.
Python module-level assignments compute once, at import time, and are
never re-evaluated when `os.environ` changes later in the same process —
so `.env` genuinely cannot reach these particular values through the
CLI's own import order, and changing the hardcoded default was the only
fix that could actually take effect, not a stylistic choice. Worth fixing
properly later (a `load_dotenv()` call at the top of `wd_config.py` itself,
matching `scanner/config.py`'s own pattern) rather than treating "edit the
default" as the permanent answer — not done here, out of scope for this
entry, which is documenting today's live fixes as they were actually made.

**4. `scanner/config.yaml` reconfigured for today's live run**: `aggregator`
enabled (was off), scoped to `us` only (Canada dropped from `countries`),
and its `queries` list replaced with a 20-item US-focused set (property/
staff/senior/corporate accountant, accounts payable/receivable, fund
accountant, controller, assistant controller, accounting manager, real
estate accountant, property management/project/construction accountant,
lease administrator, financial reporting analyst, fund administrator,
family office accountant, investment analyst, tax accountant) — the
comment above it now notes the real constraint: "Basic tier is a 200/month
HARD limit... the connector has no call counter and will 403 mid-scan when
the cap hits." `tinyfish` and `poc_enrichment` both flipped to `enabled:
false` (today's run leaned on the aggregator only). 15 staffing-blocklist
entries added (Staffing, Talent, Recruit, Personnel, Search Partners,
Jobot, Metasys, SolomonEdwards, Hire Score, The Lee Group, SourcePro,
Quantum Search, Advice Personnel, Sherwood, Syntax) on top of the existing
list, from real recruiter/staffing firm names seen in today's live output.

Also added to `.gitignore` (separate commit): `.env.backup`, `raw.json`,
`qa_out/`, and the day's ad-hoc probe/debugging scripts at the repo root
(`apollo_*.py`, `cols.py`, `fixdbc.py`, `gate.py`, `tav.py`, `test_poc.py`,
`v12.py`, `void_wasatch.py`) — root-anchored (`/apollo_*.py`, not bare
`apollo_*.py`) so the pattern can never shadow a real, tracked file nested
elsewhere (e.g. `lib_referral/apollo_enrich.py`), confirmed directly with
`git check-ignore`. `.env` was already ignored (confirmed with
`git check-ignore -v .env`), unaffected by any of this.

Tests: 267 passed (unchanged — these four fixes are runtime/config
behavior with no new test coverage added in this entry; `pytest` was rerun
to confirm none of the four changes broke anything already covered). 0
failures.

## Run 27 fixes: deck attachment, executive-tier prefix audit, oneliner grounding, geo gate finding, URL normalization, Telegram test leak - 2026-08-03

Five fixes from a live run (run 27) that produced 3 Gmail drafts, one of
them wrong, plus one report-only investigation.

**1. No pitch deck PDF was ever attached.** `src/signal_drafting.py`
hardcoded `deck_pdf_path = None` with a comment "Prompt 4's scope: no deck
is generated yet" — Block 6's wording, the Gmail attachment, and the
`wd_drafts` row were all correctly wired to key off that one variable, but
nothing ever set it to anything else. Workflow C's own deck generator was
already vendored into this repo, unchanged, at `lib_referral/deck_filler.py`
(commit `078493aa00e27dcd17716c0f57bb6d0ae35644da`, copied 2026-07-28 —
same commit as `lib_snapshot/drafting/pitch_deck.py`, which it reuses
`_BIG_MONEY_RE`/`_short_name` from) — its `build_and_convert()` fills the
master PPTX (`templates/Pitch_Master.pptx`, confirmed present) via the slot
map (`templates/pitch_slots.json`, confirmed present) and converts to PDF
via `scripts/office/soffice.py` (confirmed present). Called, not copied:
added `_generate_deck(firm_name, research, progress)` in
`signal_drafting.py`, which calls `deck_filler.get_deck_content()` then
`deck_filler.build_and_convert()` and returns the PDF path (or `None`).
`build_and_convert()`'s own `convert_to_pdf()` already degrades to
`pdf_path=None` on a missing soffice wrapper or a failed conversion
(Workflow C's own design) — what it does NOT guard is the content-
extraction half, so `_generate_deck` wraps the whole call in a bare
`try/except`, matching the "an honest blank beats a fabricated or blocked
one" posture the rest of this pipeline already follows: a deck problem
must never cost a firm its draft.

**2. "Principal" (and, on audit, "Owner"/"Partner") matched as a
seniority PREFIX, not the role.** Live: Apollo returned "Rao Iqbal,
Principal Backend Engineer" at AlphaX and it drafted as an executive
contact — the 2026-08-02 fix only ever excluded "Principal Accountant".
"Principal" is a routine seniority prefix in engineering/consulting/
science (Principal Engineer/Developer/Architect/Scientist/Consultant/
Analyst/Designer/Researcher, Principal Product/Program Manager, Principal
Data/Software/Backend/Frontend/Security/Technical/Solutions/Sales
[Engineer|...]) — none of these are the economic-buyer role the tier
means. `src/wd_poc.py`'s `_KEYWORD_EXCLUSIONS["principal"]` reworked to
match only when Principal names the role itself (standalone, "Managing
Principal", "Founding Principal", "Principal & CEO", "Principal, Real
Estate" all still match — nothing occupational follows). Applying the
same audit to the rest of the executive tier found the identical shape
twice more: "owner" wrongly caught "Product/Technical/Data/System/
Process/Risk/Content/Platform Owner" (all real accountability roles, not
company ownership), "partner" wrongly caught "Technical Partner" and
"Channel Partner"/"Channel Partner Manager" beyond the already-fixed
"Business Partner" case. founder/co-founder/managing partner/managing
director/president/ceo/coo were re-checked against the same class of
collision and found clean. Every case verified empirically (a standalone
script run before writing the final regex, matching this file's established
practice), not just reasoned about.

**3. The firm one-liner in AlphaX's draft described a different real
company — traced, not guessed.** AlphaX's draft opened with "Builder-
developer and vertically integrated real estate investment and asset
manager", language describing a US homebuilder, not a UAE real estate firm
(domain `alphax.ae`). Queried the actual `wd_firms` row for the live run:
`research["domain"]` was `alphax-capital.com` (not `alphax.ae`),
`research["geography"]` was `"Silicon Valley / US markets"`, and
`research["sources"]` were `alphax-capital.com` and an
`adviserinfo.sec.gov` search — i.e. `icp_gate.py`'s research step resolved
"AlphaX" to a **completely different, real US company** ("AlphaX
Capital"), not the actual UAE-domained job poster. `research_and_gate()`
(`lib_referral/icp_gate.py`, vendored) takes only a `firm_name` string —
no domain hint parameter exists for a caller (like Workflow D, which
already knows the posting's employer domain from the scanner) to pass in
and disambiguate against. Its own name-collision guard
(`_entity_prefix`/`_UNVERIFIED_SOURCE_TAG`, FIX 27 sub-change D) is a
best-effort regex over source text, not a domain check, and evidently
didn't fire for this pair. **This means the oneliner was not "ungrounded"
in the traditional sense — it was accurately, consistently grounded in the
firm's OWN stored research blob, just the wrong firm's**, because every
downstream field (region_ok, firm_oneliner, AUM, everything) reflected the
substituted company. Added the requested check anyway
(`find_required_fact_violations`'s new `firm_oneliner_not_grounded`,
mirroring the existing `posting_title_not_grounded` mechanism exactly —
`research["firm_oneliner"]` must actually reach the corpus text the
LLM/fallback draws from) since it is a real, legitimate regression guard
against research and corpus construction drifting apart from each other.
Flagging plainly: it would **not** have caught run 27's actual defect,
since research and corpus never drifted apart here — the research object
itself was self-consistently about the wrong company. The real fix would
be a domain cross-check inside `research_and_gate()`'s own resolution
step; out of scope for this entry (the ask was the grounding check plus a
report), and `icp_gate.py` is vendored — a fix there needs the donor-repo
filing CLAUDE.md requires, not a Workflow-D-local patch.

**4. Geo gate — investigation only, no code changed.** Asked whether the
ICP gate can reject a firm outside North America (AlphaX qualified despite
scanning being scoped to US + Canada). It CAN: `apply_gate()`
(`lib_referral/icp_gate.py`) disqualifies outright when `region_ok` is
false (`"Outside North America, disqualified"`), and `region_ok` is a
real field the extraction prompt asks the LLM for directly ("true if
headquartered or primarily operating in the US, Canada, or Mexico"). It is
**pure LLM judgment with no deterministic backstop** — there is no
domain-TLD check, no cross-reference against a firm's own address. Notably,
`lib_snapshot/config.py` defines a `NORTH_AMERICA` set
(`{"USA", "United States", "Canada", "Mexico", ...}`) that is **never
referenced anywhere else in the codebase** — dead code, not a wired-in
check. For AlphaX specifically, `region_ok=true` was an accurate judgment
about the WRONG company (see item 3 above — "AlphaX Capital" genuinely is
Silicon Valley/US-based), not a false judgment about the real one. The
scanner's own "US + Canada" region setting (`scanner/config.yaml`)
constrains the JOB BOARD SEARCH scope, not the hiring firm's own
headquarters — a US-facing/remote posting from a foreign-headquartered firm
is a real, structural gap the scanner's region config was never designed
to close. Per the task's own instruction, gate behavior was left
unchanged.

**5. Posting URLs carried LinkedIn tracking query params into the
draft.** Choice NY's draft P.S. had `?position=19&pageNum=0&refId=...
&trackingId=...`; Neal Communities' (sourced via JSearch, not TinyFish's
LinkedIn guest search) had none. Confirmed against real `wd_postings`
rows before writing the fix, which also surfaced a real counter-example:
ZipRecruiter rows use `?jid=<id>` as the ACTUAL job identifier (the path
alone, `/c/<Company>/Job/<Title>/-in-<City>,<ST>`, does not resolve without
it) — a blanket "strip everything after `?`" would have broken those
links. `_canonical_posting_url()` (new, `src/signal_drafting.py`) strips
query params only when the host is `linkedin.com`/`*.linkedin.com`,
confirmed via the real JSearch-sourced Neal Communities URL that the
canonical `/jobs/view/<slug>-<id>` path resolves with no query string at
all. Applied where `_draft_one_firm` selects `posting_url` — the same
value flows into both Block 6 and `grounding_corpus`, so the URL-grounding
check trivially still passes (both sides use the identical stripped
string).

**6. Tests sent live Telegram messages.** `tests/test_run_lock.py` called
`run_single_firm(mode="manual", firm_name="Acme Capital")` without
overriding the module-level default `progress=tg.progress` — a REAL
Telegram sender, and this repo's own `.env` carries live
`TELEGRAM_BOT_TOKEN_D`/`TELEGRAM_CHAT_ID` values (needed for real runs).
Confirmed one call (`test_run_single_firm_releases_the_lock`) genuinely
reached `progress("Gating Acme Capital...")` before this fix — meaning
every full-suite `pytest` run this session likely posted that message to
the operator's live bot. Fixed by passing an explicit no-op `progress` at
every `run_single_firm`/`run_resume` call site in that file (only one of
the four actually reached a `progress()` call before this fix; all four
fixed for consistency). Audited the rest of `tests/` for the same shape:
`tests/test_run_scan_drafting.py`'s five `run_scan.run_scan(mode="manual")`
calls also relied on the same real default, but never actually leaked
today — `signal_pipeline.run` and `signal_drafting.draft_for_run` are both
fully mocked in every test there, and neither fake implementation calls
`progress()` — fixed anyway for consistency, since relying on every future
mock forever ignoring a live argument is fragile. Added
`tests/conftest.py`'s autouse `_block_real_telegram_sends` fixture as the
general backstop: substitutes a guard object for `wd_telegram`'s own
`requests` name (mirroring `src/jsearch_pool.py`'s `_PooledRequests`
technique — scoped to that one module's namespace, not the shared
`requests` module, so it never affects `wd_poc.py`/`apollo_enrich.py`'s own
`requests.post` mocks in their own tests) whose `.post()` calls
`pytest.fail()` — which subclasses `BaseException`, not `Exception`,
specifically so it survives `wd_telegram.py`'s own bare `except Exception`
around every `requests.post` call (a plain raise would otherwise be
silently swallowed and logged as a warning, not fail the test). Known gap,
documented in the fixture's own docstring: `_edit()`'s HTTP call runs on a
background daemon thread, so an exception there doesn't propagate to the
test — the guard's real coverage is the two synchronous entry points
(`send()`, and `progress()`'s first call), which is the shape both the
found leak and any realistic future one would take.

Tests: 434 passed (up from 364 — new coverage for `_generate_deck`, the
deck-attachment end-to-end path, every executive-keyword prefix collision,
`firm_oneliner_not_grounded`, `_canonical_posting_url` including the
ZipRecruiter negative case, and the Telegram guard itself). 0 failures. No
vendored `.py` file touched (`git status --porcelain -- scanner/
lib_referral/ lib_snapshot/` shows no `.py` files dirty). No scan command
run — verified via `pytest` and direct function calls/DB queries only.

## Run 27 follow-up: geo TLD backstop, and a correction to the entry above - 2026-08-04

**Correction first.** The entry above asserted, in passing, that "Workflow
D already knows the posting's employer domain from the scanner." That
claim was wrong, and a full investigation (three parallel research passes:
every scanner connector plus `scanner/models.py`, `signal_pipeline.py`'s
`gate_group()`/`FirmGroup` at the exact moment it calls the gate, and the
`wd_postings`/`wd_firms` Postgres schema) does not support it:

- The raw JSearch (RapidAPI) response DOES carry an `employer_website`
  field — confirmed live against a real captured response (`Metasys
  Technologies` -> `https://www.metasysinc.com`, `Montcure LLC` ->
  `https://montcure.com`, cleanly distinct from the job-board apply link in
  the same rows). But `scanner/connectors/adapters/jsearch.py`'s mapping
  loop never reads it, and `scanner/models.py`'s `NormalizedJob` dataclass
  has no field to hold it even if it were read. Both vendored — capturing
  it is a fix against the donor `job-scanner` repo, not something
  patchable here.
- `scanner/connectors/tinyfish.py`'s LinkedIn scraper is never even asked
  for a domain — its own output schema has no such property at all.
- The one connector family whose URLs ARE genuinely employer-branded
  (`ats:*` — Greenhouse/Lever/Workday/Ashby/Workable/SmartRecruiters,
  `scanner/connectors/ats.py`) has an empty `companies: []` list in
  `scanner/config.yaml`, so it contributes zero postings in the live
  configuration. Even populated, its URLs are third-party ATS domains
  (`boards.greenhouse.io/<slug>`, `jobs.lever.co/<slug>`), not the
  employer's own root domain.
- Every `wd_postings.url` value under what's actually enabled today
  (`aggregator:jsearch`, `tinyfish:*`) is a job-board URL — LinkedIn,
  ZipRecruiter, SelectLeaders, eFinancialCareers — confirmed connector by
  connector. Parsing one as a domain guess would be actively wrong (a job
  board's own domain is not the employer's), and would reopen the exact
  shape of collision FIX 28 protects against.
- The only "domain" anywhere in `wd_firms`/`wd_postings` is
  `research["domain"]`/`["own_domain"]` itself, produced BY
  `icp_gate.py`'s own Tavily/LLM resolution keyed on firm name alone.
  Comparing it against itself is circular, not an independent
  cross-check.

Net: the requested domain-mismatch check (gate-resolved domain vs. the
posting's own employer domain) is **not buildable today** without either
(a) filing the scanner-side capture fix upstream against `job-scanner` and
re-vendoring, or (b) fabricating an unreliable domain guess from a
job-board/ATS URL, which was explicitly rejected here as introducing a new
FIX-28-style collision risk rather than closing one. Not implemented.
Flagged plainly rather than built around quietly.

**What WAS added: `foreign_domain_park_reason()` + wiring in
`gate_group()`, `src/signal_pipeline.py`.** Independent of the blocked
half above, this wires `lib_snapshot.config.NORTH_AMERICA` — defined
there, never referenced anywhere else in the codebase before this — into
a check on the ONE domain that does exist: the gate's own resolved
`research["domain"]`/`["own_domain"]`, AFTER `research_and_gate()`
returns but before the verdict is persisted. If the domain carries an
unambiguous non-North-American country-code TLD (`.ae`, `.uk`/`.co.uk`,
`.in`, `.sg`, `.hk`, `.cn`, and similar — ~45 curated), an otherwise-
QUALIFIED verdict is overridden to `parked`, with a distinct
`park_source="geo_tld_check"` so it reads differently from the gate's own
park reasons (`research`/`match`/`infrastructure`) in `/status` and the
Telegram summary. A disqualified or already-parked verdict is left alone
— the check only guards the one dangerous case, a firm about to qualify
and draft.

Deliberately excludes ccTLDs widely repurposed as vanity/brand gTLDs by
North American firms — `.io`, `.ai`, `.co`, `.me`, `.tv`, `.ly` — since
flagging those would misfire on legitimate US/Canadian companies for
nothing more than a fashionable domain suffix, not a real geography
signal. Verified empirically (a standalone check run before writing the
final table) against both the required flags and these vanity-gTLD
negatives.

**Honest limitation, stated directly**: this backstop would **not** have
caught the actual run-27 AlphaX incident. AlphaX's gate-resolved domain
was `alphax-capital.com` — a `.com`, no foreign TLD at all — because the
gate had resolved to a different, wrongly-matched US company's domain,
not a foreign one (see the entry above). What this check catches instead
is a genuinely different, real gap: a firm whose domain the gate DID
correctly resolve, but which carries a foreign TLD that an LLM-judged
`region_ok` might still misjudge as North American. Both gaps are real;
neither substitutes for the other. Locked in as its own regression test
(`test_gate_group_alphax_regression_still_qualifies_since_gate_resolved_a_dot_com`)
rather than left as a claim.

Tests: 465 passed (up from 434 — 31 new: `foreign_domain_park_reason`'s
TLD classification including every vanity-gTLD negative and the
`domain`-over-`own_domain` precedence, and `gate_group()`'s wiring across
qualified/disqualified/already-parked verdicts). 0 failures. No vendored
`.py` file touched. No scan command run — verified via `pytest` and direct
function calls only.

## Three deck/gate defects from a real generated deck (Choice NY) - 2026-08-05

Choice NY Property Management LLC — a third-party residential/commercial
property manager, confirmed against the actual generated deck already
sitting in `generated_decks_c/` — surfaced three defects: two fixed in
Workflow D's own code (`lib_referral/deck_filler.py` is vendored,
untouched), one investigated and reported only, per instruction.

**1. The retry forced fabricated fit content.** Live log: `[DECK EMPTY]
fund_structures returned empty by model`, same for
`underwriting_acquisitions` and `capital_markets` — correct: this firm has
no funds, no acquisitions arm, no capital stack. Then `[DECK RETRY] ...
filled on retry` for all three, which shipped to slide 04. Traced to
`build_fill_data()`'s Part C retry (FIX 36) in `deck_filler.py`: it exists
specifically to override a genuinely-empty fit paragraph, on the premise
(stated in its own retry prompt, gated behind an optional `fit_hint`
Workflow D never passes) that "a slot should never be genuinely
unfillable." That premise doesn't hold for a firm this narrow — no
capability-grounded rewrite of "capital markets support" is honest for a
firm with no capital markets activity at all.

`deck_filler.py` has no parameter to disable the retry outright.
`config.TEST_MODE` is the retry's only other gate, and it's too broad: it
also reroutes `get_deck_content()` itself to a canned fixture, replacing
real content generation entirely, not just the retry. The one seam that
skips ONLY the retry, without touching the vendored file: the retry's own
token-budget check, `tokens_so_far >= config.MAX_LLM_TOKENS_PER_FIRM` (the
same FIX 34/36 guard), where `tokens_so_far` is read straight off the
`deck_content` dict `_generate_deck()` (`src/signal_drafting.py`) already
owns before ever passing it to `build_and_convert()`. Setting
`deck_content["tokens_used"] = gate_config.MAX_LLM_TOKENS_PER_FIRM`
unconditionally trips that gate, declining the retry for every firm, every
time — not a conditional workaround, a deliberate policy choice using the
mechanism's own documented purpose.

**2. Empty field labels rendered as dangling text.** Slide 3 (Choice NY's
own generated PPTX, unzipped and inspected directly) showed bare
`Founded`, `Investing since`, and `Capital stack complexity:  ` runs with
nothing after them, because `research` had no `founded_year`/
`capital_stack`. Confirmed these three strings appear nowhere in
`templates/pitch_slots.json` — they are FIXED slide XML in
`templates/Pitch_Master.pptx` itself, never a slot `fill_deck()` is even
aware of, so there is no code path, vendored or otherwise, that already
conditions them on whether the paired value is empty.

Since the labels live in fixed slide XML the vendored code never touches,
the fix has to operate on the OUTPUT PPTX `build_and_convert()` already
produced, not on anything upstream. Added `_patch_dangling_labels()`
(`src/signal_drafting.py`): unzips the generated PPTX, blanks a label run
IF ITS PAIRED VALUE IS EMPTY, but only when that label locator appears
EXACTLY ONCE on a given slide — the same "don't guess" posture
`fill_deck()`'s own slot-fill already uses for an ambiguous locator.
Verified directly against the real Choice NY `.pptx` on disk before
writing this into the codebase (copied it, ran the patch, re-inspected
the runs, confirmed a clean re-zip with no corruption) — not just reasoned
about. Since `build_and_convert()` already ran PDF conversion on the
UN-patched file, `_generate_deck()` re-runs `deck_filler.convert_to_pdf()`
(a public, side-effect-free vendored function) on the patched PPTX
whenever a patch actually changed something, so the shipped PDF reflects
it. A patch failure (bad path, corrupt zip, whatever) degrades to
shipping the original, unpatched PDF rather than blocking the draft — the
same posture as every other deck-generation failure mode already handled.

Limitation stated plainly: the master template's 5 fit-paragraph slide
headings, and these 3 label runs, are physically fixed positions in the
PPTX layout — blanking the paired text run leaves the label's own line
empty but does not remove its position on the slide (matching FIX 11's own
already-shipped, already-accepted behavior for a blank fit-paragraph
heading: "a slot's heading can't be hidden even when its body is empty").
Full removal of a label's slide position would require editing the master
template itself, out of scope here.

**3. Investigated: is icp_gate AUM extraction non-deterministic?** Report
only, no code changed, per instruction. Queried the actual `wd_firms` rows
for this firm across every run that touched it (`id=65` run 25, `id=66`
run 27, `id=82` run 28, `id=83` run 29) rather than assuming from the
symptom. Finding: **AUM extraction itself is not the non-deterministic
step** — `apply_gate()` is a pure function over whatever `research`
dict it's given, and `_extract()`'s LLM call runs against a fixed prompt.
What's actually non-deterministic, confirmed directly:

- Run 25 (`id=65`, a full scan) researched Choice NY fresh: 2 sources
  (`choicenewyork.com`, a NYC HPD "qualified Mitchell-Lama property
  managers" page stating "manages assets valued at over $250 million") →
  `AUM_ESTIMATED`, `$250M` portfolio-value proxy → **qualified**.
- Run 27 (`id=66`, another full scan, 16 companies gated) hit Choice NY
  again and correctly REUSED run 25's cached verdict
  (`verdict_source='cached_wd'`, `verdict_cached_from=65`,
  byte-identical `research`, identical `gated_at` down to the
  microsecond) — `wd_dbc.verdict_cache_lookup()` worked exactly as
  designed here.
- Run 28 (`id=82`) never finished (`wd_runs.status='running'`,
  `finished_at=NULL` — a crashed/killed process, matching the exact
  "a crashed process leaves a 'running' row behind forever" landmine
  `acquire_run_lock()`'s own docstring already documents; consistent with
  the operator's own concurrent debugging session that day, including a
  `kill_run26.py`-style script). Its `wd_firms` row for Choice NY was
  created (`dbc.create_wd_firm()`) but never updated with a verdict —
  `icp_status=NULL`, `research=NULL`. A separate, orthogonal finding, not
  itself about AUM extraction.
- Run 29 (`id=83`, `wd_runs.csv_path=NULL`, `postings_kept=0`,
  `companies_grouped=1` — the exact signature of `run_scan.run_single_firm()`,
  the `/scan "Firm"` single-firm override, "scanner skipped") re-researched
  Choice NY from scratch: a DIFFERENT 6 sources (LinkedIn, Instagram, SEC
  adviser-info search, a brokers listing site — notably NOT the NYC HPD
  page that carried the $250M figure) → no dollar proxy found anywhere in
  this new set → `AUM_UNVERIFIED` → **parked**.

`firm_key` is identical (`'choice ny property management'`) across all
four rows — recomputing it directly confirms this isn't a key-normalization
mismatch. The actual mechanism: **`verdict_cache_lookup()` has exactly one
call site in the whole codebase, inside `signal_pipeline.run()`'s own
scan loop** (`signal_pipeline.py:529`) — `run_single_firm()`
(`src/run_scan.py`) calls `signal_pipeline.gate_group()` directly and
never consults the cache at all. A firm gated fresh via the single-firm
override always re-researches from scratch, even when a same-day cached
qualified verdict already exists, fully exposed to whatever Tavily search
result variance shows up on that call (CLAUDE.md's own pre-documented
"Phase 2 research variance" landmine — the mitigation for it, verdict
caching, exists in the codebase but this one call path was never wired to
it). This is very likely why Choice NY re-gated at all: run 28 died
mid-gate for it, and run 29 looks like the operator retrying that one firm
directly via the single-firm override immediately after — a path that,
by construction, skips the exact mechanism that would have caught the
already-qualified verdict sitting one row away. Not fixed here per
instruction; flagged as a real gap in `run_single_firm()`'s own design,
distinct from (and more actionable than) "AUM extraction is
non-deterministic."

Tests: 475 passed (up from 465 — 10 new: `_generate_deck` forcing
`tokens_used` to the cap, `_patch_dangling_labels`'s blank/leave-alone/
partial/non-unique/no-op/None-fill_data cases, and `_generate_deck`'s
reconvert-after-patch / skip-reconvert / patch-failure-falls-back-to-
original-pdf paths). 0 failures. No vendored `.py` file touched. No scan
command run — verified via `pytest`, direct function calls, and direct DB
queries only.

## Three more deck/gate defects, found by comparing against Workflow C's own Kingbird reference deck - 2026-08-06

**1. The previous fix (blanking a label's text run) was itself wrong —
replaced with whole-shape deletion.** Unzipped the real generated decks
already sitting in `generated_decks_c/` (Choice NY, and a new Neal
Communities one) and inspected slide 3's actual shape tree directly, not
just its text: each card/footer is a `roundRect` CONTAINER shape (beige
fill for the AUM/Founded cards, navy for the capital-stack footer) with
1-3 text-box shapes drawn on top. Blanking only the text left the
container rendering as an empty box — Choice NY showed an empty beige
Founded card and an empty navy capital-stack bar; Neal showed an empty
beige AUM card (Neal never discloses AUM at all).

Fixed by deleting the whole `<p:sp>` sequence (container + content shapes)
for a group whenever every one of its `fill_data` keys is empty, operating
on the OUTPUT PPTX `build_and_convert()` already produced, same as before.
Shapes are identified by NAME ("Shape 4", "Text 5", ...) rather than
locator text, since by the time this runs the text is already replaced
(often with nothing) — no unique locator survives to search for. These
names are the master-generation tool's own autogenerated per-shape names;
confirmed byte-identical, in identical order, across both real decks
before writing this.

Two things caught IN TESTING, before either version reached the codebase
— exactly why "verify visually against both decks" was worth doing
literally, not just in principle:
- An early draft matched shape names across *every* slide in the
  presentation. These names are NOT unique presentation-wide — every
  slide's own shapes independently restart around the same low numbers
  ("Text 5", "Shape 8" all repeat slide to slide) — so it deleted
  unrelated content on completely different slides. Fixed by resolving
  which ONE slide each group lives on from `pitch_slots.json` itself
  (via the vendored, public `load_slot_map()`), and scoping deletion to
  only that slide's XML.
- A per-shape (non-atomic) deletion could leave a group half-gone if one
  of its shape names happened to be ambiguous (duplicated) while its
  siblings were unique — content deleted, an orphaned container left
  behind, arguably worse than doing nothing. Made deletion atomic per
  group: every shape name in a group must resolve exactly once, or the
  whole group is left alone.

Same "master-specific, will need updating on a re-export" fragility
`deck_filler.py`'s own hardcoded stat-tile geometry constants already
carry (see its `_AUM_VALUE_TILE_MAX_CHARS` comment) — not a new category
of risk introduced here.

**2. Manual `/qualify` never populated the AUM research fields.** Queried
the actual `wd_firms` row (id 72, Neal Communities): qualified /
AUM_CONFIRMED, `icp_reason = "QUALIFIED (operator-verified AUM $700M)"`,
but `research["aum_display"]`, `aum_value_usd`, `disclosed_figure`, and
`disclosed_label` were all `""`/`None` — and `research["aum_tag"]` itself
was still the ORIGINAL `AUM_UNVERIFIED` from the initial park, never
brought in sync with the `wd_firms.aum_tag` COLUMN the same command
updates. `deck_filler.build_fill_data()` reads `disclosed_figure`/
`disclosed_label` (not `icp_reason`) to fill the deck's AUM stat tile, so
every manually-qualified firm's deck rendered that tile blank.

`src/bot.py`'s `_handle_qualify()` now writes the AUM figure into
`research` in the exact shape `icp_gate.research_and_gate()` itself
produces (confirmed by reading its actual `research = {...}` construction
in `lib_referral/icp_gate.py`, not guessed at): `aum_value_usd` (the raw
float), `disclosed_figure` (`human_usd(aum)`, e.g. `"$700M"`),
`disclosed_label` (`"assets under management"`), `aum_display`
(`f"{disclosed_figure} ({disclosed_label})"`, matching icp_gate's own
combination format exactly), and the nested `aum_tag` brought into
agreement with the column. Reuses the ALREADY-PARSED `aum` float the
handler computed to validate the command against the gate's own
$200M-$2B band — never a second parse of the `icp_reason` string it
itself writes. Every other research field the original park already
gathered (`domain`, `sources`, `geography`, `founded_year`,
`firm_oneliner`, ...) is preserved untouched — only the AUM-related keys
change.

**3. Duplicate one-liner bullet.** Slide 01 (Choice NY, from the same
`<p:sp>` inspection as item 1) repeated the italic headline verbatim as a
bullet reading `"Firm described as <the exact same oneliner text>"`.
`deck_filler.py`'s own `_drop_oneliner_duplicate` (FIX 15) exists
specifically to catch a bullet identical to the firm one-liner, but its
compare is an exact string match after only whitespace/case/trailing-
period normalization — the `"Firm described as "` lead-in defeats it.
Added `_drop_oneliner_duplicate_bullets()` in `src/signal_drafting.py`,
applied to `deck_content["profile_bullets"]` BEFORE it ever reaches
`build_and_convert()`: strips a small set of known self-referential
lead-ins (`"Firm described as "`, `"The firm is described as "`,
`"Company described as "`, `"The company is described as "`,
`"Described as "`) before comparing, and is a strict superset of the
vendored guard's own behavior (still catches a verbatim duplicate with no
prefix at all) — the vendored guard still runs afterward too, redundant
once this catches it, harmless if it doesn't need to.

Tests: 493 passed (up from 475 — 18 net new: `_delete_empty_deck_shapes`'s
Neal/Choice-NY regressions, the atomic-per-group and scoped-to-one-slide
regressions caught in testing, `_handle_qualify`'s research-shape/
preservation/reuse-not-reparse cases, and `_drop_oneliner_duplicate_bullets`'
prefix-stripping including the live-observed case). 0 failures. No
vendored `.py` file touched. No scan command run — verified via `pytest`,
direct function calls, and direct inspection of the real generated `.pptx`
files in `generated_decks_c/`.

## Slide-04 fit rows, reflow, and two contradicted premises - 2026-08-07

Five reported deck defects, checked against the two real decks in
`generated_decks_c/`, Workflow C's own generated Kingbird deck in
`referral-system/generated_decks_c/`, and `templates/Pitch_Master.pptx`.
Three were real and are fixed. Two rested on a premise the evidence
contradicts, so per HARD RULE 8 they stop at a report.

### 1. Per-firm slide-04 headlines: no such mechanism exists. Not changed.

The report was that Workflow C generates firm-specific fit-row headlines
("Complex waterfall verification", "Debt refi cycle management", "Family
office co-investor reporting", "Property accounting at scale", "Underwriting
pipeline support") where Workflow D renders fixed labels. Evidence against:

- Those five strings appear in **no deck at all**. Searched every
  `ppt/slides/slideN.xml` of the master, Workflow C's Kingbird deck, and both
  Workflow D decks. Zero hits.
- Kingbird's own slide-12 headlines are the **same five generic labels**
  Workflow D renders: "Scalable Property Accounting", "Complex Fund
  Structures", "Tailored Investor Reporting", "Underwriting & Acquisitions
  Support", "Capital Markets Expertise".
- In `templates/pitch_slots.json` those five slots are `"type": "fixed"` —
  declared static, never filled by either workflow.
- The nearest real text is on **slide 5** (SECTION 03, "Six functions we
  cover for real estate managers"): "waterfall verification", "Debt refi
  analysis", "custom family office reports", "sourcing pipeline support".
  Slide 5 is sha256-identical across master, Kingbird, Choice NY and Neal —
  static service-catalog copy, not generated for anyone.
- `grep -n "_heading"` in both the vendored `deck_filler.py` and the donor's
  current `src/deck_filler.py` matches one line each: a discarded loop
  variable in `_assemble_fit_paragraphs`. No headline generation anywhere.

Per-slide sha256 across all four files shows only slides 1, 2, 3, 12 and 14
are ever filled; 4-11 and 13 are static in every deck.

So there is no Workflow C path to route through. Building per-firm headlines
would be new generation work in Workflow D: a new LLM call or a derivation
from the fit paragraph, each headline then needing `fact_check.py` grounding
like every other generated claim (HARD RULE 4) and a `full_replace` slot the
slot map does not currently declare. That is a feature, not a defect fix, and
it is the operator's call.

### 2. Empty slide-12 fit rows now delete whole, and the survivors reflow. Fixed.

Real, and confirmed on all three decks: Choice NY ships an empty "Complex
Fund Structures" and "Capital Markets Expertise" bar, Neal an empty "Complex
Fund Structures" bar. Workflow C ships the defect too, its Kingbird deck has
an empty "Tailored Investor Reporting" bar, so again nothing to inherit, only
the slide-3 card fix applied one slide over.

`_DANGLING_SHAPE_GROUPS` is now `_DECK_SHAPE_STACKS`: groups sharing one
vertical stack of slots on one slide, with reflow. Survivors shift up into
the slots the deleted groups vacate. Slot positions are read from the deck's
own container geometry at run time, never hardcoded, and a survivor's target
slot index is always <= its own, so reflow can only ever move a shape up.

**Bug caught by rendering the patched deck and looking at it, before it
reached the codebase:** each slide-12 row also owns a decorative icon that is
a `<p:pic>`, not a `<p:sp>`. The first version of the table listed only text
boxes, which left the deleted row's icon orphaned on the slide and left every
surviving row's icon behind at its original y while the bar it belongs to
moved up without it. The shape regex now matches both element types
(backreferenced, so the two can't match across each other) and each row group
lists its icon.

Atomicity moved from per-group to **per-stack**: reflow needs every slot
position in a stack known before it can move anything, so one ambiguous shape
name now leaves that whole stack untouched. The slide-3 footer is its own
single-group stack, so an ambiguous stat card still doesn't block it.

### 3. Slide-01 dead space: Workflow C does nothing. Reflow added, residual whitespace reported.

Asked what Workflow C does when a firm has fewer stats. Answer: nothing at
all. `grep` for `p:sp>`, `a:off`, `a:ext`, `reflow`, `remove`, `delete` in the
donor's `deck_filler.py` matches no geometry or element manipulation, it only
ever rewrites `<a:t>` runs, by design ("never rebuilds the deck").

Its Kingbird deck is the proof: **both** stat cards present with every run
blank, plus a capital-stack footer bar carrying a dangling "Capital stack
complexity:" label and no value. That is exactly the defect Workflow D fixed
in the previous commit. There is no reflow, resize, or alternate layout to
match, Workflow D is already strictly ahead here.

The report that "Kingbird fills four stat tiles" describes
`templates/Pitch_Master.pptx`, which is itself a hand-authored Kingbird deck
(its slot-map locators are Kingbird's own text). The master fills them, the
generated Kingbird deck fills none of them.

What is fixed: the marooned-card case below. What is not: with one stat card
and no footer, the lower right of slide 3 is genuinely empty. Filling it
needs either a second real stat this firm does not have (fabrication, HARD
RULE 5) or a master-template layout change. Flagged, not guessed at.

### 4. "Investing since" deleted. Fixed.

The Founded card's third text box reads "Investing since" with nothing after
it. `pitch_slots.json` has no slot for it, nothing in either workflow ever
fills it, which is why it renders dangling on every deck with a founded_year
(Neal: "1970 / Founded / Investing since"). The master's AUM card uses that
third line for `aum_asof` ("as of Dec 31, 2025"); the Founded card's
equivalent was authored as a bare sentence fragment with no value to complete
it.

Populating it from `founded_year` is not the fix: the card already shows that
year as its headline figure with a "Founded" label directly above it. It is
listed as `valueless` on its group, deleted with the card when the card goes,
deleted on its own when the card stays.

The report that Kingbird "pairs it as 'invested since 2008' beneath its stat"
does not match the file; the master's own three runs are "2008" / "Founded" /
"Investing since", with the fragment already dangling.

### 5. Marooned surviving stat card. Fixed by the same reflow.

Neal's slide 3 lost the AUM card and left the Founded card in slot 2 with an
empty quadrant above it. The survivor now moves into slot 1 (y 2.98 -> 1.50)
with its text boxes keeping their insets (3.10 -> 1.62, 3.54 -> 2.06).

### Verification

Every case rendered to PDF via LibreOffice and inspected as an image, on
`Pitch_Master.pptx` (the only file with all shapes still present) driven by
Choice NY's and Neal's actual `fill_data` shapes, plus re-run against both
real generated decks. All patched files parse as well-formed XML across every
member, and neither touched slide carries `<p:timing>`, `spTgt` or
`custDataLst` references to a deleted shape id.

Note the pass is not idempotent by design: re-running it on an
already-processed deck finds the deleted shapes missing and leaves that stack
alone. It runs exactly once, on a freshly built deck.

501 tests pass, up from 493 (new: whole-row deletion, reflow with and without
geometry, reflow-never-moves-down, the Choice NY two-empty-row case, the
marooned-card case, the valueless "Investing since" line, and slide-3 vs
slide-12 stack separation for the colliding "Shape 12"/"Text 13"/"Text 5"
names). 0 failures. No vendored `.py` file touched, and no template file
touched. No scan command run.


## Three funnel-audit fixes: blocklist, POC domain cross-check, acquired-by park - 2026-08-08

Acting on the run-25/27 funnel audit. One config change and two Workflow D
code changes. No vendored `.py` file touched.

### 1. Blocklist extended: 31 -> 52 entries (config)

The audit found 6 recruiters and professional-services firms that passed the
blocklist, reached the gate, and were each disqualified on firm type after
spending 6 Tavily searches: Henderson Harbor Group (its own research
one-liner reads "talent placement for accounting, finance, tax & technology"),
CPA Connections, Klausner & Company PC, Susan Fitzgerald & Associates, LG
Legacy Group, Guidehouse. Added those plus name-shape and named-recruiter
entries.

**Measured before finalizing**, against all 248 company names in
`output/jobs.csv` + `output/jobs_2026-07-31_0421.csv` and all 83 `wd_firms`
rows, using `signal_pipeline._is_staffing` itself (lowercased substring
containment) rather than a re-implementation:

- **Zero qualified firms blocked. Zero parked firms blocked** by the new
  entries. All 6 firms the new entries newly match are `disqualified`.
- Run 27: 6 of 16 firms blocked, gate calls 9 -> 5, **24 of 54 Tavily
  searches saved (44%)**.
- The 3 parked firms the FULL list blocks (Jobot, Metasys Technologies,
  Syntax Talent Solutions) are caught by PRE-EXISTING tokens (`jobot`,
  `metasys`, `talent`), not by anything added here. Today's behavior,
  unchanged.

**One requested entry was narrowed. `Bachrach` -> `Bachrach Group`.** A bare
surname is the highest-risk shape on this list: family offices are an explicit
ICP category and are routinely named after the family, so "Bachrach" would
block a hypothetical "Bachrach Family Office" or "Bachrach Properties".
Verified the narrowed token still catches the actual offender, "TBG | The
Bachrach Group". Same reasoning already applied to the given full names
`CPA Connections` (not bare "CPA") and `Susan Fitzgerald & Associates` (not
bare "& Associates").

Two entries are redundant and kept only for readability: `Recruiting` is a
strict superset match of the existing `Recruit` (all 6 names it matches were
already blocked), and `Orion Placement` is covered by `Placement`.

Remaining false-positive risk, in order: `Placement` (a real capital-raising
firm could carry it — "private placement" is a finance term, not only a
recruiting one), then `Quest Financial` and `Search Advisors` (specific
enough that a collision is unlikely). Everything else is a distinct company
name.

### 2. POC email domain cross-check (Workflow D code)

Run 27 drafted to `riqbal@alphax.ae` for a firm the gate resolved as
`alphax-capital.com`. `_draft_one_firm` now compares the two before spending
anything, via `poc_domain_mismatch_reason()`. A block returns a new
`poc_domain_mismatch` bucket, carried on `DraftBatchResult` and `RunResult`
and printed in the run summary. Comparison uses `wd_poc._firm_matches` as
asked, never new comparison logic.

**Country is tested before the label, and that ordering is what makes the
check work at all.** Verified against the live `wd_drafts` rows:
`_firm_matches("alphax", "alphax capital")` is **True**, because "capital" is
in `_TOLERABLE_EXTRAS`. That is correct behavior for firm names, and on a
label-first ordering it would have downgraded the real AlphaX incident to a
warning and drafted to the UAE contact anyway. So the POC domain runs through
`signal_pipeline.foreign_domain_park_reason` first — the same ccTLD table,
imported, never a second copy to drift — and a non-North-American ccTLD
blocks regardless of how well the labels match. `.ca` is North American and
does not block, which is exactly the regional-affiliate case the warning path
exists for.

Affiliate case is a warning, not a block: a sibling domain whose core still
reads as the same firm (`acme-capital.com` vs `acme.com`) logs and drafts.
Public mailboxes (gmail, outlook, ...) are ignored entirely — a real principal
at a small firm legitimately uses one, that is a personal-address question
rather than a wrong-company one, and blocking on it would cost real drafts for
no evidence.

Against the three real run-27 drafts: Choice NY PASS, Neal PASS, **AlphaX
BLOCK**.

**Bug caught by testing, in the fix itself:** `_email_domain` used
`rpartition("@")`, which returns the whole string when there is no "@" — so a
malformed address became a bogus domain and produced a spurious block. It now
returns "" when there is no "@".

**Bug caught by testing, in the tests:** the first `_draft_one_firm` wiring
helper put `poc_name_hint` on the firm dict, but `_draft_one_firm` reads it
off the POSTING rows. That left `poc_name` None, skipped the patched
`apollo_enrich.find_email`, and fell through to the UNPATCHED
`wd_poc.find_senior_poc` — the live Apollo API — which is why the two wiring
tests initially returned each other's expected bucket. The helper now puts the
hint on the postings and asserts `find_senior_poc` is never reached.

### 3. Direction-aware acquired-by park (Workflow D code)

`acquired_by_parent_park_reason()` sits next to `foreign_domain_park_reason`
and parks an otherwise-qualified firm whose `recent_event` says the firm
itself was acquired. Choice NY's blob has carried "Sold to Associa Corp. in
2021 (earn-out noted)" the whole time and nothing read it.

**Direction is the whole difficulty.** Two real `wd_firms` rows would
false-positive on a naive `/acquired/` match, and both mean the opposite
thing (a firm buying real estate is growing and running its own books):

- Brixmor Property Group: "Acquired properties for $416.8M in 2025"
- Havtech: "acquired The Morin Company, Morin Distribution, and Prillaman
  Systems"

So an explicit acquirer test runs FIRST and short-circuits, and the target
patterns are anchored on phrasings where the firm is the grammatical object
("sold to", "acquired BY", "subsidiary of"). Both directions are tested,
using those two strings verbatim as the negative cases.

Fires on 9 of 83 rows (2 distinct firms: Choice NY, Guidehouse). Deliberately
narrow — the value is precision on a verdict that would otherwise ship a wrong
draft, not coverage. An acquisition this misses is a firm the gate qualifies
exactly as it does today, which is current behavior, not a regression. The geo
check runs first, so a firm with both a foreign domain and an acquisition
parks once, attributed to geo, rather than double-overwriting its reason.

### Verification

575 tests pass, up from 501. No vendored `.py` file touched. No scan command
run — verified via `pytest`, direct function calls against the live `wd_firms`
/ `wd_drafts` rows, and the two run CSVs.

`scanner/config.yaml` also carries uncommitted operator edits in the working
tree (tinyfish enabled, Canada targets commented out, a JSearch query swap).
Only the blocklist hunk is in this commit: the staged blob was built as HEAD
plus the blocklist change, so those operator edits remain unstaged and
untouched. Both the staged and working-tree versions parse as valid YAML.

