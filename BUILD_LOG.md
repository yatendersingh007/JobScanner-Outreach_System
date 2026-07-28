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
