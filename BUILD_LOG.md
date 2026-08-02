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


## Slide-01 bullet redundancy: headline substring and stat-tile restatement - 2026-08-09

The regenerated Neal Communities deck shipped five profile bullets of which
three restated something already on the same slide. Confirmed by reading
`ppt/slides/slide3.xml` out of both decks in `generated_decks_c/` (regenerated
15:59-16:00, after the previous commit's shape work landed):

| bullet | duplicates |
|---|---|
| `Founded in 1970` | the Founded stat card (`Text 9` = `1970`) |
| `Disclosed AUM: $700 million` | the AUM stat tile (`Text 5` = `$700 million`) |
| `Homebuilder/developer focusing on single-family and townhome communities` | the italic headline, minus its trailing ` in Southwest Florida` |

### Rule A: headline containment, either direction, above a length floor

`_is_oneliner_restatement`. The old guard compared exact strings after
lead-in stripping, so it caught "Firm described as X" but not a substring.
Now either string may contain the other, subject to a 30-character floor on
the SHORTER side. The floor is what keeps a legitimately short bullet from
being eaten by an incidental appearance in a long headline: "Multifamily" or
"Southwest Florida" inside this headline is not a restatement. The live case
clears the floor with 71 characters.

### Rule B: restatement of a POPULATED stat tile

`_is_stat_tile_restatement`. The value alone is not grounds to drop —
"Reported $1 billion annual revenue in Apr 2024 article" carries a figure and
is the slide's most interesting fact, and no tile shows it. The test is: the
bullet contains a tile's own value AND, once that value, the tile's label
words, and connective filler are removed, no substantive word remains.
"Founded in 1970 by Pat Neal in Sarasota" keeps pat/neal/sarasota and
survives.

Tile values come from `deck_filler.build_fill_data()`'s own output, not from a
re-derivation off `research`, so a change in how it picks a figure cannot
silently desync this check. That required calling `build_fill_data()` in
`_generate_deck` BEFORE `build_and_convert()` (which calls it internally, but
only after the bullets are already baked in). That call is free and
deterministic: with `tokens_used` forced to the cap, its one LLM path (the
Part C retry) is declined, leaving a pure function over research +
deck_content. None of the three tile fields depends on `profile_bullets`, so
the values compared against are identical to the ones the deck ends up with.
Cost is a duplicated `[DECK EMPTY]`/`[DECK RETRY]` diagnostic line per blank
fit key in the live log.

`$4.4 billion` and a tile reading `$4.4B` are one figure, so `_norm_money`
folds the magnitude word to its initial before comparing. Value matching is
word-boundary anchored, so a bare year cannot match inside `1970s` or `19700`.

**Finding worth recording: `fill_data` has no `disclosed_figure` key.**
`build_fill_data()` returns 21 keys and that is not one of them — the
disclosed figure reaches the tile as `aum_value`. The key is still read (it
costs nothing and starts working automatically if deck_filler ever adds it),
but today `founded_year` and `aum_value` are the two live comparands.

**Bug caught by the suite, in this change: `_WORD_RE` collision.** The new
token-splitting pattern was named `_WORD_RE`, which is already a module-level
constant at line 261 — the `{banned word: compiled regex}` dict that
`find_style_violations` iterates. Shadowing it silently disabled the entire
banned-word style check (HARD RULE style section); five pre-existing tests
failed with `'re.Pattern' object has no attribute 'items'`. Renamed to
`_TOKEN_RE`, and re-verified the guard flags `leverage`, `robust`,
`comprehensive` again.

### Verified visually

Both decks rebuilt from their real `wd_firms` research blobs and rendered to
PDF. Neal slide 01: two tiles filled, two distinct bullets, zero repetition,
no stray empty bullet glyphs, "Investing since" still gone. Choice NY: one
tile, three distinct bullets, zero repetition.

**Choice NY loses a fourth bullet, beyond the three Neal cases, and that is
deliberate.** `Manages assets valued at $250 million` restates a tile reading
`$250 million / Assets Valued`; every word in the residue is either the tile's
label or filler. It follows directly from Rule B as specified.

**Side effect worth flagging: dedup makes the empty lower slide worse.** Neal
goes from five bullets to two. The redundancy was padding the slide out. The
lower ~40% of slide 01 is now clearly empty, which is the subject of the
report below.

### Report, no change: could a third or fourth stat tile be populated?

**No, not in this master, and the data does not support it either.**

Geometry, measured from `templates/Pitch_Master.pptx`:

- Slide is 10.00 x 5.62 in. The stat column is `x=6.95, w=2.55`.
- Card 1 (`Shape 4`): `y=1.50, h=1.28`, bottom 2.78. Card 2 (`Shape 8`):
  `y=2.98, h=1.28`, bottom 4.26. Pitch 1.48 in.
- **There is no third or fourth card shape in the file.** The grid is a single
  column of exactly two.
- A third card at the existing pitch would sit at `y=4.46` and bottom at
  **5.74 in — 0.12 in below the slide's bottom edge**. It would also collide
  with the capital-stack footer (`y=4.95, h=0.50`, full width) whenever
  `capital_stack` is populated.
- A 2x2 grid would halve the column to ~1.2 in. `deck_filler`'s own
  `_AUM_VALUE_TILE_MAX_CHARS = 13` is calibrated to 2.19 in at 22 pt, so
  halving the width halves the budget to ~6 characters. `$700 million` is 12.
  Not viable without changing the master's geometry or font sizes.

What would populate one, and how often. Across all 83 `wd_firms` rows,
**26 (31%) have a `recent_event` currency figure distinct from the AUM
figure** — but only **3 of those 26 rows are qualified firms** (Shinda
`$175M`, Neal `$1 billion` twice), and qualified firms are the only ones that
get a deck. Worse, most of those figures are not the firm's own scale metric
and would be actively misleading on a stat tile:

- Guidehouse `$5.3B` — the price someone paid to acquire it
- Chipotle `$50M` — a venture fund it launched
- EliseAI `$250M` / `$2.2B` — a funding round and a valuation
- Brixmor `$416.8M` — property it bought, not property it owns
- Raptor Group `$200M` — a fund it is still trying to raise

Only Neal's `$1 billion annual revenue` and UVIMCO's `$15.5B Long Term Pool
AUM` read as genuine firm-scale metrics. `recent_event` is free prose with no
value/label/source structure, so populating a tile from it needs either a new
structured gate output field (a vendored `icp_gate.py` change plus a donor
filing) or prose parsing here — and that parsing would hit the same
direction problem the acquired-by park already has to solve.

The more honest read of the empty space: the two tiles that already exist are
usually unpopulated. `disclosed_figure` is set on 32/83 rows, `founded_year`
on 30/83, `aum_asof` on 16/83, `capital_stack` on 11/83. Slide 01 is sparse
because the research often has fewer than two disclosed facts, not because
the template is short of tile slots. Filling the space needs either better
research coverage or a template whose slide-01 layout does not assume four
populated regions.

For the record, the "Kingbird quality reference" of five distinct bullets and
four filled tiles describes `Pitch_Master.pptx` itself, which is a
hand-authored Kingbird deck. Workflow C's own GENERATED Kingbird deck has all
six bullet runs partly blank, both stat cards present with every value run
empty, a dangling "Capital stack complexity:" label, and a dangling
"Investing since" — the same defects fixed here across the last three
commits.

623 tests pass, up from 575. No vendored `.py` file touched. No scan command
run.


## Revert the stat-tile dedup rule, raise the headline floor, fix two content defects - 2026-08-10

### 1. Rule B (stat-tile restatement) removed

Removed entirely rather than flag-gated: a path that defaults off and is
contradicted by the quality reference is dead code that rots. Recoverable from
commit 8624538 if it is ever wanted. Removed with it:
`_is_stat_tile_restatement`, `_stat_tile_comparands`, `_norm_money`,
`_STAT_FILLER_WORDS`, `_TOKEN_RE`, and the `build_fill_data()` pre-call in
`_generate_deck` that existed only to feed it (which also removes the
duplicated `[DECK EMPTY]`/`[DECK RETRY]` log lines per firm).

A regression test now asserts `_is_stat_tile_restatement` and
`_stat_tile_comparands` do not exist and that "Founded in 1970" /
"Disclosed AUM: $700 million" survive, so the rule cannot come back by
accident.

Effect on the current builds: Choice NY goes back to all five bullets. The
bullet Rule B used to strip there ("Manages a portfolio valued at $250 million
(assets valued)") is retained.

**Correction on the cited evidence.** The three Kingbird bullets given as
justification — "Founded in 2008", "$4.4B (gross asset value) as of March 31,
2026", "Multifamily-focused real estate investment manager" — **appear in no
deck on this machine.** Searched all slide XML in 71 `.pptx` files across
`referral-system/` and this repo: zero hits for any of the three, and none for
"as of March 31, 2026". The generated Kingbird deck is unchanged since
2026-07-29 22:40 and its slide 3 holds four bullets, no founded-year bullet,
no GAV bullet, and every stat run blank:

```
Text 2  'Kingbird Investment Management is a test firm.'
Text 3  'Vertically integrated multifamily investment manager operating since 2008.'
        'Concentrated portfolio across Texas and the Southeast United States.'
        'Uses LP, GP, and co-GP structures alongside preferred equity on individual deals.'
        'Appointed a dedicated Director of Capital Markets in 2019.'
Text 5/6/7   ''  ''  ''      <- AUM tile, all blank
Text 9       ''              <- Founded tile value, blank
```

The revert stands on its own merits regardless: Rule B did strip three of five
bullets in the build measured last commit, and that outcome was flagged then.
The citation is recorded here only because it was the stated basis, and
because it could not be used to calibrate the new floor.

### 2. Rule A floor raised: containment plus a 0.70 ratio

Was "any containment over 30 characters", which is too eager. Now the shorter
side must also be at least 70% of the longer. Measured on real strings rather
than guessed:

| case | normalized | ratio | verdict |
|---|---|---|---|
| Neal bullet inside its own headline | 72 / 93 | **0.774** | drops |
| a clause-sharing bullet inside a longer headline | 50 / 110 | **0.455** | kept |

0.70 sits between them with margin either way. Exact duplicates and the
"Firm described as X" lead-in forms still drop unconditionally — those are not
judgement calls. The 30-character absolute floor stays.

### 3. Two content defects fixed

Both drop the bullet rather than rewrite it (HARD RULE 5: a hand-edited
sentence reads as mutilated), and every drop is now reported through
`progress()` with its reason (HARD RULE 4) instead of vanishing silently as
the old dedup did.

**`AUM displayed as $700 million`** — a statement about this slide's own stat
tile, not about the firm. `_describes_the_deck` matches display/meta language:
`displayed as/on/in`, `as displayed`, `shown as/on`, `this deck|slide|page`,
`the deck|slide`, `stat tile`, `tile above`. Deliberately excludes "listed as"
— "listed as one of the fastest-growing builders" is a real fact.

**`Reportedly targeting $1 billion annual revenue (Business Observer, Apr
2024)`** against `research["recent_event"]` = `Article noting $1 billion
annual revenue (Business Observer, Apr 2024)`. "Targeting" converts a reported
historical figure into a stated intention. `_misframes_a_research_figure`
drops a bullet carrying forward-looking wording when the research fields that
carry that figure state it as fact. Claim extraction is
`fact_check.extract_numeric_claims` (called, not reimplemented) so
"$1 billion" here and in `recent_event` normalize to the same `1B`.

Scoped deliberately: a figure research has never heard of is the vendored
ungrounded-claim guard's job, so "Targeting $5 billion in unrelated revenue"
is not this rule's business.

**Bug caught by a control case.** The first version checked research fields
one at a time and dropped on the first field carrying the figure without
forward wording. Raptor Group (wd_firms id 78) breaks that: its
`disclosed_figure` is a bare `$200 million` while its `aum_display` reads
`$200 million (fund target / fund size (Raptor Digital))` and its
`recent_event` says `seeking`. A supported bullet ("Seeking $200M for its
digital fund") was being dropped. Now EVERY field carrying the figure must
lack forward wording before the framing counts as unsupported.

### Why fact_check passed both, traced against Neal's real research

`_drop_ungrounded_claims` -> `fact_check.unverifiable_claims()` is a **number**
checker. It extracts numeric claims from the text and asks whether each
appears in the corpus. Run against Neal's actual blob:

```
'AUM displayed as $700 million'
    numeric claims extracted : ['700M']
    unverifiable_claims()    : (none -> GROUNDED, ships)

'Reportedly targeting $1 billion annual revenue (Business Observer, Apr 2024)'
    numeric claims extracted : ['1B']
    unverifiable_claims()    : (none -> GROUNDED, ships)
```

Both figures are in the research blob (`aum_display` `$700 million`,
`recent_event` `$1 billion`), so both bullets come back with zero
unverifiable claims. Nothing in the grounding path examines the words around
the number — not `displayed as`, not `targeting` versus `noting`. Both
defects keep the figure exactly right and change only the prose, which is
precisely that guard's blind spot. `unverifiable_claims`'s own docstring scopes
it to "numeric claims ... that do NOT appear anywhere in corpus_text"; it is
working as designed and was never a claim-framing check.

### Verified visually

Both decks rebuilt from their real research blobs and rendered. Choice NY:
five bullets, one tile, healthy slide. Neal: **one bullet.**

**Flagging that plainly.** Neal's current build generated three bullets, two of
which were factually defective, so the honest slide has one. The guards are
doing the right thing (an honest blank beats a false claim in a client-facing
document), but the deck is thin, and the fix is upstream: the content prompt is
producing deck-self-description and tense substitutions in the first place.
That is a `_CONTENT_PROMPT` change in vendored `deck_filler.py`, so it needs a
donor filing rather than a local edit, and it is not attempted here.

620 tests pass (was 623; the removed Rule B tests outnumber the added ones).
No vendored `.py` file touched. No scan command run.


## TinyFish descriptions: negative result, do not retry - 2026-07-31

Probed whether LinkedIn guest-search results pages carry job descriptions,
since the classifier matches employer-type signals against company name +
description only, and tinyfish.py never sets description (0-3% classification
rate vs JSearch's 33% on 112 postings/run).

GOAL_TEMPLATE and OUTPUT_SCHEMA were patched from outside the vendored module
(both are read at call time - lines 134 and 194 - so the jsearch_pool.py
technique applies). One live target: LinkedIn US - Property Accountant.

Result: 32 rows, 27 with a non-empty description. Every one is LinkedIn UI
chrome, not job text:
  'Be an early applicant.'
  'Medical insurance +4 benefits.'
  'Be an early applicant +4 benefits.'
Zero employer-type signal. Runtime 496s vs the ~300s a normal target takes -
65% slower for no gain, against a 900s MAX_WAIT ceiling.

Conclusion: the data is not on the page. Real descriptions would require
navigating into each of ~32 postings per target, which guarantees timeout.
The NormalizedJob interception plumbing was NOT built.

The probe did quantify the loss: America West Properties, RREAF Holdings,
Invest with Roots and Century Group all appeared and are all discarded for
lack of any signal. The false-discard rate is real. TinyFish cannot fix it.

Recommendation on record: shift budget from TinyFish LinkedIn targets to
JSearch queries. JSearch returns 2000-char descriptions, classifies at 33%,
and costs seconds instead of ~2 hours per run.

## ATS channel: ~0% coverage for this ICP - 2026-07-31

Probed 15 candidate RE firms (from the run-25/27 discard analysis plus known
large operators) against Greenhouse, Lever and Ashby public board APIs. All
free, no key. Slug variants tried per firm: concatenated, hyphenated, and
with the trailing legal/descriptor word dropped.

Result: 1 apparent hit of 15, and that hit is a bare generic slug
("ashby:stream", 3 roles) that is likely an unrelated company, not Stream
Realty Partners.

Firms with no public board on any of the three platforms: RREAF Holdings,
America West Properties, Invest with Roots, Osprey Management, Singh
Management, Signorelli Company, Baywater Properties, Aureate Group, Kidder
Mathews, Greystar, Empire State Realty Trust, Equity LifeStyle Properties,
Brixmor, Neal Communities.

Conclusion: mid-size RE operators in the $200M-$2B band do not use the modern
ATS platforms this connector supports. The ats: connector stays enabled with
an empty companies list; there is nothing to populate it with.

Third negative result in sequence, all measured:
  - classifier keyword tuning: recovers 11 of 229 discarded companies (4.8%)
  - TinyFish descriptions: LinkedIn UI chrome, zero employer signal
  - ATS coverage: ~0% for this ICP

Structural finding: firms in this band hire finance staff through recruiters,
which masks the employer in the posting, and do not expose first-party ATS
feeds. Job-posting scanning is a weak channel for this ICP regardless of
further engineering. Run 27 measured the ceiling: 227 postings -> 16 companies
gated -> 1 qualified firm surviving every check.

## Slide-01 bullets composed from research instead of generated - 2026-08-11

Six rounds of guarding the model's prose failed the same way each time: each
guard caught one tense variant and the next generation invented another
("targeting", then "eyeing"). The failure class is open, so a seventh verb
blocklist was never going to close it. Slide 01 no longer sources bullets from
the model.

### 1. Deterministic composition

`compose_profile_bullets(research, category, subcategory, icp_reason)` templates
the research blob's own fields. Every field value is inserted VERBATIM; the only
text this module authors is fixed scaffolding (`Founded in `, `Operates in `,
`Reported: `, `Focus: `, `AUM basis: `), each a constant in the file. Order is
founding, location, scale/figures, focus, domain.

| field | line |
|---|---|
| `founded_year` | `Founded in {founded_year}` |
| `geography` | `Operates in {geography}` |
| `recent_event` | verbatim, or `Reported: {recent_event}` if it is not a sentence |
| `subcategory` | `Focus: {subcategory}` |
| `own_domain` (else `domain`) | `{domain}` |

"Is a sentence" needs both ends: an initial capital AND terminal punctuation.
Neal's `Article noting $1 billion annual revenue (Business Observer, Apr 2024)`
has the capital but ends on a bracket, so it is a noun phrase and takes the
lead-in.

`get_deck_content()` is still called, because slide 12's fit paragraphs are
genuinely generative. Its `profile_bullets` are discarded unread. A test feeds
it `["Eyeing $5 billion in revenue by 2030", "Targeting nationwide expansion",
"AUM displayed as $700 million"]` and asserts not one word survives, while the
fit paragraphs pass through untouched.

The three LLM-output guards from previous commits still run on the composed
bullets as defense in depth. They are no-ops in practice and kept rather than
deleted so that re-enabling model-authored bullets cannot silently ship
unguarded prose.

**Verified on both live rows** by composing, building the real deck, and reading
back `ppt/slides/slide3.xml`: every bullet's payload, with its scaffold
stripped, is a verbatim substring of the field it came from. All five Neal
bullets and all four Choice bullets also survive the vendored guards
(`_drop_estimated_money_mentions`, `_drop_ungrounded_claims`,
`_drop_marketing_language`, `_cap_bullets`) unchanged.

One vendored interaction worth knowing: `_cap_bullets` truncates any bullet
over 18 words and appends a period. Both live firms' longest composed line is
11 words, and the templates are short by construction, but a very long
`recent_event` would be cut mid-phrase. Not worked around here.

### 2. Bullet-count floor

Below four bullets, grounded derivable lines are inserted in the scale/figures
band (not appended after the domain, so the declared order holds):

- **AUM basis.** Deviates from a literal `{aum_display} ({disclosed_label})`:
  icp_gate builds `aum_display` AS `f"{disclosed_figure} ({disclosed_label})"`,
  so that template double-prints the label — `$250 million (assets valued)
  (assets valued)` on the live Choice NY row. Uses `aum_display` verbatim, or
  `{disclosed_figure} ({disclosed_label})` when display is empty.
- **icp_reason**, only when client-safe.

Never generic filler: a firm with one usable field ships one bullet.

**The icp_reason line is rejected for both live firms, by design.** Gate verdict
strings are internal qualification bookkeeping — `QUALIFIED (est. $250M —
portfolio value proxy (manages assets valued at over $250 million))` — and the
gate writes them with the em dash CLAUDE.md bans as an AI tell. Neither belongs
in front of a prospect. `_ICP_REASON_UNSAFE_RE` rejects em/en dashes, the
verdict words, and `est.`/`proxy`/`unverified`/`tertiary`/`verify manually`. It
is a real path for cleaner future reasons; today it never fires, and the tests
say so explicitly.

Live floor behaviour: Neal 5 bullets (no top-up), Choice NY 4 (exactly at the
floor, no top-up), a geography+domain-only firm 4 (AUM basis added).

### 3. Navy footer fallback

With `capital_stack` empty, the bar now carries `Focus: {category} ·
{subcategory}` instead of being deleted; it is deleted only when all three are
empty. A populated `capital_stack` always wins — this is a fallback, not a
replacement.

The bar's own two runs are written separately: `Focus: ` into the bold-italic
label run and the value into the italic value run, preserving the label/value
styling the master intended rather than flattening both into one run. Values
are XML-escaped, and the write is skipped unless the shape resolves exactly
once with exactly its two expected runs.

This is what actually fills the dead lower third of slide 01 — 72 of 83
`wd_firms` rows have an empty `capital_stack`, so the bar was being deleted
almost always.

### 4. Bullet-box height: writable, but shrinking it is a no-op. Not implemented.

Reported before implementing, as asked.

**Writable: yes**, though not from deck_filler's fill layer — that layer only
rewrites `<a:t>` runs by design ("never rebuilds the deck"). It is writable
from Workflow D's own post-build XML pass, which already rewrites `<a:off>` for
stat-card and fit-row reflow; `<a:ext cy>` is the same operation on a sibling
attribute of the same element.

**But it would change nothing on screen.** The master's bullet box (slide3.xml,
`Text 3`) is:

```
<a:xfrm><a:off x="457200" y="2148840"/><a:ext cx="5760720" cy="2651760"/></a:xfrm>
<a:noFill/><a:ln></a:ln>
<a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t">
```

`anchor="t"` with `tIns="0"` and no autofit (`normAutofit` and `spAutoFit` both
absent) means the first line sits exactly on the box's top edge and every line
below it at a fixed offset from there. Reducing `cy` moves only the box's
BOTTOM edge, and the box has no fill and no outline, so its bounds are
invisible. Not one glyph moves.

The premise that "3-4 bullets float in a box sized for six" does not hold: the
bullets are pinned to the top already. The visible emptiness was the region
BELOW the text, which is now filled by the footer fallback (item 3) rather than
by resizing an invisible rectangle. Implementing the resize would add a
fragile geometry write with zero visual effect, so it is not implemented.

What WOULD change that region, if more is wanted later: moving the stat cards
and footer up toward the text, or widening the bullet column into the vacated
right column when no tile is populated. Both are real layout changes with real
overflow risk, and neither was asked for.

### Verified visually

Both decks regenerated from their real research blobs and rendered. Neal:
five bullets, both tiles, populated navy footer, no dead space. Choice NY: four
bullets, one tile, populated footer.

**One thing to decide.** Items 1 and 3 both surface the focus, so the slide now
shows `Focus: Fund Operations/Back Office` as a bullet AND `Focus: Real Estate ·
Fund Operations/Back Office` in the footer. Visible repetition, in both
renders. The footer is strictly more informative (it adds the category). Both
were specified separately so both are implemented as asked, but dropping the
bullet when the footer carries the same subcategory is a one-line change if
wanted — note it would push Choice NY to three bullets and trigger the AUM-basis
top-up.

661 tests pass. Three tests that asserted the old "filter the model's bullets"
behaviour were removed (that behaviour no longer exists); the guards themselves
are still unit-tested. No vendored `.py` file touched. No scan command run.


## Drop the duplicate focus bullet, and de-jargon the footer's subcategory - 2026-08-12

### 1. The `Focus: {subcategory}` bullet is gone

The navy footer already carries the focus and carries it better, since it adds
the category. `compose_profile_bullets` no longer emits the bullet;
`category`/`subcategory` are still accepted so its signature matches the
footer's and callers pass one set of arguments.

While removing it, the function was restructured from one list plus a computed
insert index into four explicit bands (founding, location, figures, domain).
Same declared order, but readable, and it fixes where a floor top-up lands: the
old index arithmetic put the AUM basis line AHEAD of the reported event, and
the event is the more interesting line. Top-ups now join the END of the figures
band.

Live effect, both rows regenerated and read back from `slide3.xml`:

- **Choice NY**: 3 lines without the focus bullet, so the floor pulls in the
  AUM basis. `Operates in New York metropolitan area` / `Reported: Sold to
  Associa Corp. in 2021 (earn-out noted)` / `AUM basis: $250 million (assets
  valued)` / `choicenewyork.com`. Exactly the behaviour predicted when this was
  flagged last commit.
- **Neal**: founding, location, event, domain -- exactly four, so neither
  top-up fires even though it has an AUM figure to offer. Went from five
  bullets to four.

### 2. Subcategory display labels

Subcategory values key the title-matching rule lists in
`classifier_rules.yaml`. They are routing labels for our own triage, and
`Fund Operations/Back Office` reads as our jargon on a deck the prospect
opens. `subcategory_display()` maps each to a phrase written for that reader,
and `footer_focus_text()` runs the subcategory through it.

All 8 names declared in the YAML are covered (Real Estate's seven plus Family
Office's three, overlapping on Investor Relations and Fund Operations/Back
Office):

| raw value | footer label |
|---|---|
| `Property Accounting` | Property accounting |
| `Fund Operations/Back Office` | Fund operations and back-office finance |
| `Investment Analyst/Underwriting` | Acquisitions and underwriting |
| `Fund Accountant` | Fund accounting |
| `Staff Accountant` | General accounting and controllership |
| `Asset Analyst` | Asset management |
| `Investor Relations` | Investor relations and reporting |
| `Accounts Payable` | Accounts payable |

Matching is case- and whitespace-insensitive on the raw value. Anything
unmapped falls back to the raw value verbatim, so a subcategory added to the
YAML later degrades to today's behaviour rather than vanishing from the bar.

**`Needs Review` maps to `""` on purpose.** The classifier assigns it when a
title matches none of its category's rules, so it means "not decided", not a
focus. Printing it would leak triage language; inventing a specific focus in
its place would be worse. The footer shows the category alone (`Real Estate`).
It is a live case, not hypothetical: it is the subcategory for every posting in
category `Other`, and a target-category firm whose title matched no rule
carries it too.

A test reads `classifier_rules.yaml` itself and asserts the declared set
equals the mapped set, so adding a subcategory there without a label fails the
suite instead of shipping internal taxonomy to a prospect. Another asserts no
mapped label contains a `/`, the tell that the raw taxonomy escaped.

Note the 8 `wd_firms` rows (3 of them qualified) with a blank
category/subcategory are unaffected: `footer_focus_text` returns `""` for them
and the bar is deleted, as before.

### Verified

Both decks regenerated and slide 01 read back from the XML: no `Focus:` bullet
in `Text 3`, no occurrence of `Fund Operations/Back Office` or `Needs Review`
anywhere in the slide, and the footer reading `Focus: ` + `Real Estate ·
Property accounting` / `Real Estate · Fund operations and back-office finance`
in the master's own label/value run styling. Rendered both to PDF and looked at
them: four bullets each, tiles populated, footer populated, no repetition.

680 tests pass, up from 661. Twelve existing expectations were updated for the
removed bullet, the new top-up ordering and the display labels. No vendored
`.py` file touched. No scan command run.


## Fix: a patched PPTX could ship an unpatched PDF - 2026-08-13

`_generate_deck` ended with `pdf_path = deck_filler.convert_to_pdf(pptx_path,
progress=progress) or pdf_path`. The vendored `convert_to_pdf` writes to
`pptx_path.parent / (pptx_path.stem + ".pdf")` -- the SAME path
`build_and_convert` already wrote -- so when reconversion failed, the `or`
handed back a file that was still the PRE-PATCH render. Live symptom: a Neal
deck whose PPTX carried the populated footer while its PDF at that same path
still showed a valueless "Capital stack complexity:", a dangling "Investing
since", and all five slide-04 rows undeleted.

### Report: why the second conversion fails

Reproduced against live soffice. The trigger is narrower than it looked, and
two of the three hypotheses are negative.

**Collision with the existing output file: NOT the cause.** Convert, patch the
pptx, convert again in the same directory: rc=0 both times, and the PDF is
rewritten (sha changes, 292,998 -> 283,919 bytes). soffice overwrites its own
output happily.

**A lingering soffice instance holding the profile lock: NOT the cause.**
Tested directly, with a background `soffice --headless --norestore --nologo
--nodefault` confirmed present in `tasklist` for the duration. The second
conversion still succeeded in 4.2s and rewrote the file. On this LibreOffice
build, single-instance delegation does not silently no-op.

**An open handle on the output PDF IS the cause.** With the target `.pdf` held
open (`msvcrt.locking` on the real file), the wrapper exits **rc=1**,
`convert_to_pdf` returns `None`, and the stale file stays on disk untouched.
That is the reproduction of the live failure.

And the trigger is completely mundane in practice: **POWERPNT.EXE was running
on this machine during the investigation** -- the operator reviewing the deck
that was just generated is enough to lock it. The same run also failed to write
the PPTX at all for the same reason (`[Errno 13] Permission denied` on
`generated_decks_c/XAnalyst_Neal_..._Pitch.pptx`), which `_generate_deck`'s
outer handler caught and reported correctly.

**On "no log line":** `convert_to_pdf` does emit one, but it reads *"PDF
conversion failed (rc=1); shipping the deck without a PDF conversion."* In this
call site that was actively false -- the `or` then shipped a stale PDF, so the
operator was told there was no PDF while a wrong one went out attached to the
draft. Worse than silence.

**A second, latent failure mode** the fix also had to be robust to:
`convert_to_pdf`'s success test is `rc != 0 or not pdf_path.exists()`. Because
the previous render already sits at exactly that path, `exists()` can never
detect a conversion that returned rc=0 without writing. Its truthy return is
not by itself evidence the file is fresh, so the new code does not trust it.

### The fix

`_reconvert_deck_pdf(pptx_path, pdf_path, firm_name, progress)`:

1. Creates a private staging directory **alongside the target**, not in
   `%TEMP%` -- `os.replace` cannot move across volumes on Windows and the decks
   directory may be on a different one.
2. Copies the patched PPTX in and converts THERE, where nothing is stale and
   `exists()` means what it says.
3. Requires the produced file to exist and be non-empty.
4. `os.replace`s it over the original only then.
5. On any failure: deletes the stale PDF and returns `None`.
6. Cleans up the staging directory in a `finally`, on both paths.

`_generate_deck` now computes `patched` first and reconverts only when the
PPTX was actually rewritten. A shape pass that RAISED leaves the PPTX
unpatched, so the original PDF is still honest and is kept -- that case is
distinct from a patch that succeeded and a reconversion that failed, and the
two are now separate branches rather than one `try` with an `or` at the end.

A side benefit of converting in a staging dir: the reconversion now SUCCEEDS
even when the target PDF is locked, because soffice writes to an unlocked path.
Only the final move fails in that case. So the locked-file trigger degrades
from "ships a stale deck" to "ships no deck", and often to "works".

If the stale PDF cannot be deleted (an open handle blocks `unlink` too), that
is reported explicitly -- "It is NOT attached to the draft, but it is still on
disk" -- and the path is still not returned. The guarantee is about what gets
attached, which is enforceable; deleting a file another process holds is not.

### Verified

End to end against real soffice, on Neal's live `wd_firms` row, with output
redirected to a scratch directory (the real one was locked by PowerPoint):

```
_generate_deck returned: .../XAnalyst_Neal_..._Pitch.pdf
   slide 01 composed 4 bullet(s) from research fields.
   deck PDF reconverted to match the patched PPTX.

PPTX slide3 : Shape 12 present=True   footer text present=True
PPTX slide3 : 'Investing since' removed=True
PDF page3 has the footer text          : True
PDF page3 has valueless 'Capital stack' : False
PDF page3 has dangling 'Investing since': False
>>> shipped PDF agrees with the patched PPTX: True
staging dirs left behind: []
```

Slide 12 was checked shape-by-shape against the PDF text as well: all five fit
rows had real paragraphs this run and all five are present in both. (An earlier
heading-count check reported "1 of 5" -- that was a bad check, because the PDF
wraps each heading across two lines. Not a defect.)

694 tests pass, up from 680. One pre-existing test was written to the old
contract -- its fake `convert_to_pdf` returned the string `"fresh.pdf"` without
creating a file, which the new existence check correctly rejects. Updated to
write a real file and to assert the returned path is the one the fresh file was
MOVED to, plus that the converter was handed a staged copy. No vendored `.py`
file touched. No scan command run.


## v2 signal email: deterministic template plus a role-family table - 2026-08-14

Replaces the v1 six-block template. Harp's copy is reproduced
character-for-character; every slot except Block 2 is filled from a
deterministic source. The deck path is untouched: the per-firm pitch deck PDF
is still the attachment, generated and attached exactly as before.

### Item 6 first: how each v1 required-fact check maps onto the v2 body

Every check survives. None was deleted.

| v1 check | v2 |
|---|---|
| `missing_posting_title_in_block1` | `missing_role_title_in_opening`. `{role_title}` IS the posting title verbatim, in the opening paragraph. |
| `posting_title_not_grounded` | unchanged. Still the corpus check. |
| `missing_firm_name_in_block1` | `missing_firm_name_in_opening`. `{company_name}` in the same sentence. |
| `missing_posting_url_in_block6` | `missing_posting_url_in_signoff`. The P.S. still carries `{job_posting_url}`. |
| `firm_oneliner_not_grounded` | unchanged. Block 2 still draws on research. |
| `deck_attachment_claim_mismatch` | kept, re-keyed. v1 matched "The deck is attached."; v2 matches "I've attached an overview". |
| `block3_modified` / `missing_dollar_ranges_in_block3` | split into `missing_dollar_ranges`, `math_sentence_modified`, `offer_sentence_modified`. v2 has no single money block: `$145K to $180K` is in the math paragraph and `$55K to $75K` in the offer paragraph, so there is nothing to compare against one constant. Both ranges and both fixed sentences are checked in the composed body instead. |

The attachment check matters more than it looks. The v2 copy states the
attachment unconditionally, but `_generate_deck` can legitimately return None
(no soffice, a generation failure, or the run-31 case where reconversion
cannot produce a PDF matching the patched PPTX). So the sentence is
conditional in code and the mismatch check is kept in both directions.

### Blocking finding: the posting description is never persisted

Item 3 asks Block 2 to carry two responsibility phrases traceable to the
posting description, and item 4 asks the systems clause to scan posting text.
`NormalizedJob` has a `description` and the JSearch adapter fills it
(`scanner/connectors/adapters/jsearch.py` sets it to the first 2000 chars of
`job_description`), but it is dropped before drafting:

- `signal_pipeline._posting_row()` does not copy it,
- `wd_dbc.insert_postings()` does not list it,
- `wd_postings` has no such column.

So EVERY posting arrives description-less, from every source, not only
TinyFish. Today that means `block2_generic` on every draft and the systems
clause always omitted.

Everything is written to work the moment a description exists:
`draft_email(..., posting_description="")` is threaded from `_draft_one_firm`
(reading a `description` key off the posting row, harmless while absent), the
traceability check is tested against real description text, and the systems
clause is tested both ways. Wiring it up is three changes plus a migration:
add `description` to `wd_postings`, to the `cols` list in `insert_postings`,
and to `_posting_row`. Not done here: it is a schema change to the shared
`outreach` database and was not in scope.

### 1. The template

Six paragraphs, all fixed except Block 2. Subject
`Your {role_title} hire for $55K, not $180K`.

**One feature is retired, deliberately.** v1 had a multi-posting variant
("Your {n} open finance roles" / "You have {n} finance roles open at ...
including ..."). The v2 copy has no such branch and the instruction was to
implement it exactly, so a firm hiring three seats now gets an email about
the first distinct title. `posting_count` is still computed and still reaches
`wd_drafts`; nothing reads it into the body.

### 2. src/role_families.py

Seven families, each supplying `pain`, `cadence`, a base `stack` and canonical
`responsibilities`. Nothing in the module is LLM-generated and nothing in it
may be. `controller` is the declared default.

Coverage is asserted against `scanner/config.yaml` itself, so adding a query
or a target without deciding its family fails the suite. All 20 aggregator
queries and every enabled TinyFish target map. **Six of the 20 aggregator
queries land on the `controller` default** because the spec's table does not
name them: `corporate accountant`, `property management accountant`, `project
accountant`, `construction accountant`, `family office accountant`, `tax
accountant`. That is the declared default behaving correctly, and the
assignment is pinned in a test so it is visible rather than incidental. Worth
a look: `property management accountant` and `project accountant` are
arguably property_accounting, and moving them is a one-line table edit.

### 3. Block 2

Generated only when a description exists AND the result opens with "You" AND
at least two responsibility phrases trace back to the description. Otherwise
the deterministic `generic_block2()` runs off the family's canonical
responsibilities and the draft is flagged `block2_generic` (surfaced on the
returned dict and as `thin_personalization`). With no description the LLM is
not called at all for Block 2, which a test asserts by making the call raise.

Traceability is substring or close-stem, needing at least two content-word
matches covering at least half the phrase. **Two calibration bugs found by
testing:** requiring EVERY content word rejected "You already run month-end
close" against a posting saying "own month-end close", because "already" is
not in the posting. And once relaxed, function words became evidence: "You
will close the submarine hatch" scored two matches against "will own
month-end close". A non-evidence word list fixes the second.

### 4. Stack and systems

`{role_mapped_stack}` is the family base plus additions the posting itself
names (CAM, waterfall, capital calls, covenants, consolidations, 1031,
budget, audit, tenant billing, construction draws), deduplicated, base order
preserved. `{systems_if_known}` scans for the eight named systems only,
word-boundary matched so "MRI" does not fire inside "MRIs", longest-first so
"Juniper Square" is not shadowed.

With no system found the credential sentence uses a SEPARATE template ending
at the stack list, so there is no dangling "across". Enforced three ways: a
unit test on the paragraph, an end-to-end test on the composed body, and a
`dangling_across` validator.

### 5. Hard-fail validators

`find_body_violations()` on the composed body: Block 2 opens with "You"; no em
or en dash anywhere; none of "my experience", "great fit", "my background",
"I am writing to"; subject exactly matches the template; no dangling "across".
A hit raises rather than shipping.

### Known consequence: the length guard now fires on nearly every draft

The fixed copy alone is **233 words**, and the generic Block 2 adds ~35, so a
typical body is **268** against `EMAIL_MAX_WORDS=260` -- over by 8. That is a
warning, not a failure (it always was), but it will now log on almost every
draft, which makes the signal useless. `EMAIL_MAX_WORDS` is left at its
current value because changing it was not in scope; raising it to ~300 would
restore the guard's meaning. Flagging rather than deciding.

Also note v2 has one generated block, not two, so the v1 trim mechanism
(`_trim_to_budget`, trim Block 4 then Block 2) no longer runs; Block 4 no
longer exists. `_trim_to_budget` and the v1 fixed blocks remain in the module
and are still used by the block-generation path's own tests.

### Verified

Composed real bodies for both live `wd_firms` rows and read them end to end.
Choice NY resolves to `property_accounting`, Neal's "Treasury & Financial
Analyst" to `treasury` with "The cash does not stop moving" and "cash
reporting calendar". Both omit the systems clause cleanly. A composition with
a Yardi-bearing description emits ", across Yardi." and, when the live LLM
returned an ungrounded figure, correctly fell back to the generic block, which
is the pre-existing grounding guard doing its job.

815 tests pass, up from 696 (73 new in `tests/test_role_families.py`, the rest
in `tests/test_signal_drafting.py`). Seventeen v1-template tests were remapped
to the v2 paragraphs rather than deleted. No vendored `.py` file touched. No
scan command run.


## Persist the posting description, activating the v2 template's two specific elements - 2026-08-15

`wd_postings` had no `description` column, so the v2 signal email's Block 2
traceability check and its `{systems_if_known}` clause could never fire:
`block2_generic` on every draft, from every source.

- `migrations/wd_004_postings_description.sql`:
  `ALTER TABLE wd_postings ADD COLUMN IF NOT EXISTS description TEXT`
- `wd_dbc.insert_postings()`: `description` appended to `cols`
- `signal_pipeline._posting_row()`: `"description": getattr(p, "description", "") or ""`

`getattr` with a default rather than `p.description`, so a NormalizedJob-shaped
test double that predates the field does not raise.

`postings_for_firm()` needed no change: it is `SELECT *`, so the column flows
through as soon as it exists. Confirmed against the live table, and pinned by a
test so a future edit to an explicit column list cannot silently drop it.
`_draft_one_firm` already read a `description` key off the row and threaded it
to `draft_email`, so nothing in the drafting layer changed.

### Report: how migrations/ is applied

**Manually. Nothing applies it automatically.** `wd_dbc.apply_migrations()` is
a one-line wrapper over `lib_snapshot.db.migrate()`, and a grep of `src/` finds
no call site anywhere: not `cli.py`, not `bot.py`, not `run_scan.py`. It runs
only when the operator invokes the command CLAUDE.md already documents:

```
python -c "from src import wd_dbc; wd_dbc.apply_migrations()"
```

`migrate()` globs `MIGRATIONS_DIR/*.sql` in sorted order, skips anything whose
filename is already in `schema_migrations`, executes each remaining file in its
own transaction, and records it. `MIGRATIONS_DIR` resolves to
`C:\Users\DELL\Job-ScannerOutreach\migrations` (`lib_snapshot/config.py`'s ROOT
is this repo, since lib_snapshot is vendored here), so it only ever sees
Workflow D's own files.

Applied it, then re-ran it: `applied migration
wd_004_postings_description.sql` / `applied 1 migration(s)`, then `no
un-applied migrations`. Idempotent, and `ADD COLUMN IF NOT EXISTS` makes the
SQL itself safe even if `schema_migrations` were ever cleared.

### Report: the shared database is unaffected beyond the new column

`schema_migrations` IS shared. It currently holds Workflow C's `001_...`
through `007_...` alongside Workflow D's `wd_001`..`wd_004`. That is exactly
why every Workflow D migration carries the `wd_` prefix: the table's primary
key is the bare filename, so a plain `004_...` here would collide with C's
`004_wc_firms_aum_tag.sql`.

Diffed the ENTIRE public schema before and after, all 19 tables, every column
with its type and nullability:

```
tables added/removed: set() set()
  wd_postings: added ['description:text:YES']  removed []
```

One column, on one table, nullable. Nothing else changed. `wd_postings` is
Workflow D's own table; Workflow A reads `leads`/`companies`/`connections` and
Workflow C reads `wc_*`, and neither touches it. All 99 pre-existing rows keep
NULL: the column is nullable with no default, so postings from sources that
genuinely have no description (the TinyFish LinkedIn guest search) stay NULL
rather than getting an empty string that would read as "we looked and it was
blank".

TEXT with no length cap: the JSearch adapter already truncates to 2000 chars,
and a DB-side limit would silently corrupt a longer description from a future
source instead of storing what it was handed.

### Verified end to end against the live database

Created a throwaway run and firm, inserted a JSearch-shaped posting carrying a
165-character description, read it back, and put it through `draft_email`:

```
_posting_row includes description: True | len 165
postings_for_firm rows: 1
  description present   : True
  round-tripped intact  : True
  systems clause in body: True     <- ", across Yardi." present
```

That is the first time the `{systems_if_known}` clause has ever populated.
Block 2 still reported `block2_generic` on that particular run, correctly: the
live LLM returned "manages 1,024 multifamily units", the pre-existing grounding
guard caught `ungrounded_claim:1024` and fell back. The description path is
working; that firm's generated text just failed grounding on its own merits.

Cleaned up afterwards and confirmed it: `wd_postings` back to 99 rows, zero
rows matching the test firm name. (`wd_firms` and `wd_drafts` are higher than
this BUILD_LOG's earlier funnel-audit baselines because of operator runs since,
not test residue.)

### Tests

824 pass, up from 815. Nine new in `tests/test_wd_dbc.py`, against fakes rather
than live Postgres, matching that file's existing approach and its stated
caveat: `description` is in the INSERT column list, its value is sent, the
column and value orders stay in step (both last), a posting without one sends
NULL, `postings_for_firm` returns it, `_posting_row` copies it and tolerates a
job object without the attribute, a JSearch posting reaches `draft_email` with
the description intact and produces ", across Yardi.", and a TinyFish posting
still yields no systems clause and no dangling "across".

One of these initially passed for the wrong reason: the placeholder-count
assertion compared `sql.count("%s")` against `sql.count(",") // 2 + 1`, an
identity that happens to hold at 18 columns. Replaced with a direct
count-the-columns assertion.

No vendored `.py` file touched. No scan command run.


## /resume no longer re-gates firms that already have a verdict - 2026-08-16

### Report 1: how the resume rebuilds its firm list, and what it read

**The firm list comes entirely from `wd_queue`, never from `wd_firms`.**
`run_resume` calls `dbc.next_pending(run_id, limit=cap + 10_000)`, which is
`SELECT * FROM wd_queue WHERE run_id=%s AND status='pending' ORDER BY id`. That
list, capped, is the gating loop.

**It did read `wd_firms`, but only for the summary.** `dbc.firms_for_run(run_id)`
at the top of the function pushed already-decided rows into
`result.qualified/disqualified/parked` and set `result.groups`. That data never
influenced which firms got gated. The docstring's claim that it resumes
"without re-drafting (re-gating) anything already decided" described the
summary, not the loop.

**Root cause, from the data rather than inferred.** `signal_pipeline.run()`
calls `dbc.enqueue()` exactly once (line 627) and **never** calls
`set_queue_status`. Nothing marks a queue row done during a normal run, so
after a crash every enqueued row is still `'pending'` -- including every firm
the first attempt already gated. `next_pending()` handed them all back.

Run 32, verified in Postgres:

```
wd_queue run 32: 12 rows, pending=0, done=12   (the resume marked them done)
wd_firms  run 32:
  id=86  jpmorgan chase       disqualified  cached_wd   <- verdict-cache hit, never enqueued
  id=87  colliers             disqualified  gated       <- attempt 1
  id=88  abc imaging          disqualified  gated
  id=89  executive alliance   disqualified  gated
  id=90  eisneramper          NULL          None        <- in flight when it died
  id=122 colliers             disqualified  gated       <- resume, duplicate
  id=123 abc imaging          disqualified  gated       <- duplicate
  id=124 executive alliance   disqualified  gated       <- duplicate
  id=125 eisneramper          disqualified  gated       <- duplicate of the NULL row
  id=126..133 (8 firms)       gated                     <- legitimately new
```

12 gated on resume: 3 pure waste, 1 that needed gating but should have updated
row 90 in place, 8 genuine. So the wasted spend is **18 searches, not 24** --
eisneramper's 6 were owed, what was wrong there was the duplicate row.

Replayed the pre-resume state through the new logic, read-only:

```
OLD: gated 12 -> 72 Tavily searches
NEW: skips 3, gates 9 -> 54 searches, saved 18
     in-place re-gate: eisneramper -> reuses row id 90
     new rows created: 8
     duplicate (run_id, firm_key) pairs created: 0
```

Checked whether other runs are exposed: seven finished runs still carry 100%
pending queue rows (10:21, 13:12, 15:4, 23:3, 24:2, 25:1, 27:9). None is
reachable, because `latest_resumable_run()` only selects `crashed`/`cancelled`
and every one of those currently has zero pending rows. Not a latent bomb, but
it is why the queue's status could not be trusted as the skip signal.

### Report 2: update the NULL row in place, do not replace it

**In place.** Two reasons, the second one measured:

1. The row already holds the run's own `posting_count`, `category` and
   `subcategory`.
2. The `wd_postings` rows are linked to it by `firm_id` --
   `insert_postings(run_id, firm["id"], ...)` runs inside `gate_group`. A
   replacement row does not inherit them.

The live data shows exactly what replacement costs. Every row the run-32
resume created has `posting_count=0` and **zero** linked postings:

```
id=90  eisneramper  NULL          posting_count=1  linked_postings=1
id=125 eisneramper  disqualified  posting_count=0  linked_postings=0
id=126..133                       posting_count=0  linked_postings=0
```

Because `run_resume` reconstructs `FirmGroup(firm_name=..., firm_key=...)` from
`wd_queue`, which stores only those two fields, so the group carries no
postings: `posting_count` computes to 0 and `insert_postings` inserts nothing.

**A separate, larger defect this exposes, reported not fixed.** A firm gated for
the FIRST time on a resume can never be drafted. `_draft_one_firm` reads
`dbc.postings_for_firm(firm_id)`, gets nothing, so `posting_title` and
`posting_url` are empty and `find_required_fact_violations` raises
`missing_role_title_in_opening`. Run 32 got away with it only because nothing
qualified (one park, eleven disqualified). Fixing it means either persisting
postings before the gate or carrying them in `wd_queue`, which is a bigger
change than this one and was not in scope.

### The fix

`run_resume` now builds two things from `firms_for_run(run_id)`, which it was
already calling:

- `decided_keys`: firm_keys with a non-NULL `icp_status`. Their queue rows are
  marked `done` and dropped from the pending list, with a progress line saying
  how many.
- `needs_regate`: firm_key to row, for NULL-status rows. Passed to `gate_group`
  as `existing_firm` so the verdict lands on the original row.

Reconciliation happens **before** the cap is applied, so a run whose first
attempt already gated `cap` firms does not spend its whole resumed budget
re-deciding them. Tested.

`gate_group` gained one optional parameter, `existing_firm=None`. When given, it
skips `create_wd_firm` and `insert_postings` and gates into that row. Default
`None` is byte-for-byte today's behaviour, and a test asserts the default still
creates a row and still calls `insert_postings`.

Skipped firms still count toward the run summary: they were already being
appended to the result buckets by the same loop that now classifies them.

### The historical duplicates are still in the database

Rows 122, 123, 124 and 125 remain. Left alone deliberately: deleting production
rows was not asked for. They are harmless to the fix (a future `/resume` of run
32 now sees both copies as decided and skips both) and harmless to the verdict
cache (identical verdicts). If you want them gone, 122-124 are pure duplicates
of 87-89, and 125 is the duplicate of 90 whose verdict would need copying back
onto 90 first.

836 tests pass, up from 824. Twelve new in `tests/test_resume_skips_gated.py`,
against a fake wd_dbc (no live Postgres, matching `tests/test_wd_dbc.py`'s
stated approach) with `gate_group` replaced by a counter so "did this cost a
gate" is directly observable. One of them initially failed on a harness
artifact rather than a real bug: the fake's `firms_for_run` returns detached
copies, as a real SELECT does, so the fake `gate_group` had to write back by id
the way `update_wd_firm` does. No vendored `.py` file touched. No scan command
run.


## Blocklist maintenance: auto-block staffing firms, suggest the rest - 2026-08-17

The run-27 funnel audit found 69% of gate spend going to firms disqualified as
"Not an accepted firm type". The blocklist is the free check that stops them,
and it was being maintained by hand from audit findings. This closes the loop.

### Two tiers

**AUTO, no confirmation.** The firm's own research one-liner says it is a
staffing, recruiting, talent-placement or executive-search firm. That is not a
judgement about fit; it is the firm describing itself as an intermediary, and an
intermediary is never someone X Analyst can place embedded staff with.

**NOTIFY, no action.** Accounting, advisory and consultancy self-descriptions.
Genuinely ambiguous: a real estate family office can describe itself as an
advisory, and LG Legacy Group's live one-liner ("Accounting and tax advisory for
businesses and real estate clients") is one keyword from a firm we would want.
Suggested with `/block "Name"` to accept.

**NEVER, either tier: an AUM-ground disqualification.** An AUM misread is
recoverable (the verdict cache expires, /qualify overrides); a blocklist entry
silently removes the firm from every future run and nothing re-tests it.
Enforced twice: the firm-type reason is required, AND any AUM-shaped reason is
rejected outright, so a reason carrying both leaves the firm alone.

**The evidence is always the firm's own one-liner, never posting text.**
icp_gate's `firm_oneliner` describes the firm; a job description describes
whoever the job is for, which for a recruiter is its CLIENT. Reading a posting
would auto-block a real estate operator whose posting said "agency experience
preferred". A test asserts posting text is ignored even when it is on the row.

### Live behaviour, run against all 90 firms in wd_firms

```
AUTO   Addison Group      "Staffing and professional talent solutions firm (recruiting, consulting)"
       Incendia Partners  "talent acquisition and recruiting firm (non-real-estate)"
NOTIFY CPA firm           "Accounting services firm, professional services"
REJECTED by a safety check: 12
```

Both auto-adds are correct and neither is in the blocklist today, so the next
run will add them. The twelve rejections are the checks earning their place:
ten `already_covered_by` (Guidehouse, Henderson Harbor Group, PrideStaff,
Executive Alliance, W3Global, Aston Carter, EisnerAmper and others), and
**Wealthspire blocked by check 1** because it is PARKED in wd_firms and its
one-liner is advisory-shaped. Without check 1 the loop would have suggested
blocking a firm still under consideration.

Firms correctly ignored despite being firm-type disqualifications, because
their one-liners describe an operator rather than an intermediary: Chipotle,
JPMorgan Chase, Sonic Automotive, Raptor Group, Blue Origin, Havtech, ABC
Imaging, Nichols Contracting, UVIMCO, EliseAI, ReminderMedia.

One conservative miss worth knowing: **Australia-Employment** is a job board and
blocking it would be right, but its `firm_oneliner` is empty, so no tier fires.
The rule is description-based by design; a name-based rule would have caught it
and would also have caught real firms. Failing toward "no action" is the correct
direction here.

### The four mandatory safety checks

1. **No fuzzy match against any firm ever qualified or parked.** Uses
   `wd_poc._firm_matches`, the same containment-with-tolerable-extras compare
   already trusted to decide whether an Apollo org is the firm we researched, so
   "Choice NY" and "Choice New York Companies" collide while "Kairos Real Estate
   Partners" and "Kairos Investment Management" stay distinct (FIX 28). Parked
   counts as protected: a park means "could not decide", not "no".
2. **At least two content tokens, or one of 8+ characters.** A blocklist entry
   is matched as a substring against every future company name, so a bare
   "Metro" would silently drop "Metro Real Estate Partners" forever. Tokens
   that carry no identity ("and", "of", "the") do not count toward the two, so
   "Klausner & Company PC" passes on `klausner` alone rather than on `and`.
3. **No bare surname + Group/Capital/Partners** unless the description names
   the firm's own type. That shape is how a family office named after its family
   reads, and family offices are an explicit ICP category.
4. **Nothing an existing entry already covers**, substring in both directions,
   matching how `signal_pipeline._is_staffing` applies the list.

**A dead-safeguard bug caught by its own test.** The first version of check 3's
exemption reused the tier regexes, which made the exemption the same condition
as candidacy: check 3 could never fire, and read like a safeguard while doing
nothing. The test for it failed, which is how it surfaced. The exemption is now
deliberately narrower: it requires the description to name the firm's own TYPE
("a recruiting firm", "public accounting firm") rather than an activity it
performs ("bookkeeping support for portfolio companies", which is exactly what
an in-house family office finance team does).

### The file editor

Line-based, never a string replace on the document. Several blocklist entries
are substrings of unrelated YAML elsewhere in the same file ("Talent" appears in
TinyFish target names, "Search" in aggregator queries), so a replace could edit
the wrong line. The insertion walk stops at the next mapping key, so an entry
never lands in the section that follows.

Every write is validated by re-parsing the result AND confirming the entry list
changed exactly as intended; anything else restores the original bytes. Names
that would change the document's meaning are quoted (`- "Zephyr: Advisors Co"`).
Verified against a copy of the real 62-entry document: add, remove, and
add-then-remove restoring the file byte for byte, plus a sabotaged write
reverting byte for byte and still parsing.

### Audit trail and recovery

Every auto-add appends one line to BUILD_LOG.md carrying the run id, the name
and the self-description evidence, marked `AUTO-BLOCK` so it is greppable. An
audit-log failure never raises into the run: a completed run's verdicts and
drafts are not worth losing to a log write.

`/block "Name"` and `/unblock "Name"` are the manual controls over the same
file, and `/blocklist` shows the last 10 entries. Auto-adds are undone with
`/unblock` exactly like manual ones.

Note this means a run mutates two git-tracked files. That is deliberate: an
auto-add shows up in `git status`, is greppable in BUILD_LOG.md, and is
reversible from Telegram, which is what makes an unconfirmed write acceptable.

The whole maintenance step is wrapped so it can never fail a run: a
config-file or database problem degrades to a progress line and an untouched
blocklist.

937 tests pass, up from 836. 90 in `tests/test_blocklist.py` (one rejection test
per safety check, tier classification against live one-liners, the editor
against a copy of the real config, audit trail) and 11 in
`tests/test_bot_dispatch.py` for the three commands. Every editor test points
`SCANNER_CONFIG_PATH` at a tmp_path copy, so the real config is never touched
and the tests still exercise its actual shape. No vendored `.py` file touched.
No scan command run.


## run_single_firm takes the verdict cache, plus a `fresh` escape hatch - 2026-08-18

### Report: how the batch path's cache call works

Four pieces, all in `signal_pipeline.run()` and `wd_dbc`:

1. **Window.** `window = config.REGATE_WINDOW_DAYS` (currently **90 days**),
   read once per run.
2. **The pass, before any spend.** For every group, in a loop that runs before
   `enqueue()` and before the gate cap is applied:
   `cached = dbc.verdict_cache_lookup(g.firm_name, window)`. A hit goes to
   `_reuse_cached()` and into `result.skipped_known` plus the qualified or
   disqualified bucket; a miss goes into `to_gate`. The cap is then applied to
   `to_gate` only, so reused verdicts never consume gate budget.
3. **`verdict_cache_lookup`.** Matches on `firm_key`, so "Grubb Properties,
   LLC" finds "Grubb Properties". Only `qualified` and `disqualified` are
   cacheable, deliberately: a park means the research was inconclusive, and
   re-running it later is the whole point of a park. Freshness is
   `COALESCE(gated_at, created_at) >= now() - window`. It checks `wd_firms`
   first (`src='cached_wd'`), newest id first, then falls back to Workflow C's
   `wc_firms` matched on the same normalized key (`src='cached_wc'`).
4. **`_reuse_cached`.** Writes a new `wd_firms` row for this run copying
   `icp_status`, `icp_reason`, `aum_tag` and `research` from the cached row, and
   records provenance: `verdict_source` = the cache's own `src`,
   `verdict_cached_from` = the source row id, `gated_at` = the original
   decision time. Then inserts the group's postings.

`run_single_firm` used none of it. It built a `FirmGroup` and called
`gate_group()` directly.

### The fix

`run_single_firm` now runs step 2 with the same window, the same
`verdict_cache_lookup`, and the same `_reuse_cached` writer, so a reused verdict
is byte-identical in provenance from either front door. On a miss it gates
exactly as before.

`fresh=True` skips the cache. This has to exist: with a 90-day window, wiring
the cache in without an escape hatch would make a bad cached verdict
unfixable for three months. Wired through both front doors:

- `/scan "Firm" fresh` (also `/scan "Firm" dry fresh`)
- `python -m src.cli scan --firm "X" --fresh`

`/scan fresh` without a firm is **rejected**, not silently ignored: a batch run
depends on the cache to be affordable, so there is nothing to skip. And `fresh`
joined `_COMMAND_FRAGMENT_WORDS`, so `/scan "fresh"` is caught as a leftover
option rather than gated as a firm named "fresh".

### Verified against the real history

```
REGATE_WINDOW_DAYS = 90
Choice NY Property Management LLC   HIT   row 66 qualified (cached_wd) decided 2026-07-31
Beyond International Group          miss  (parks are never cached)
Profile Products LLC                miss  (parks are never cached)
```

Choice NY's history and what changes:

```
id=65  run 25  qualified   gated       2026-07-31
id=66  run 27  qualified   cached_wd   2026-07-31   (from 65)
id=82  run 28  NULL        NULL                     (crashed mid-gate)
id=83  run 29  parked      gated       2026-07-31   <- single-firm, bypassed the cache
```

A live `verdict_cache_lookup` today returns row 66, qualified. Run 29 would now
reuse it at zero search cost instead of re-gating to a contradictory park.

### Correcting the conflict list

Two of the three conflicts cited do not exist as described, and it matters
because it changes what this fix is claimed to prevent:

- **Choice NY 65/66 vs 83: real, and exactly as described.** Run 29 was a
  single-firm run (`postings_kept=0`, no `csv_path`), it bypassed the cache, and
  it produced the contradictory park.
- **"Beyond International 76 vs 103": no.** Row 76 is Klausner, disqualified.
  There is no row 103. Beyond International Group has exactly **one** row (79,
  run 27, parked).
- **"Profile Products 118 vs 131": no.** There is no row 118. Profile Products
  has exactly **one** row (131, run 32, parked).

Both non-conflicts are parked, and a park can never be served from the cache or
conflict with it, because `verdict_cache_lookup` never caches parks. So this fix
prevents the Choice NY class of conflict and would not have touched the other
two. Worth being precise about: the eval report's own verdict-instability list
was australia-employment, choice-ny, havtech, jpmorgan-chase and wealthspire,
and of those only Choice NY is same-generation research variance.

Also worth noting for future spend accounting: single-firm runs are
identifiable by `postings_kept=0` with no `csv_path`, but that heuristic
mislabels a resumed run (run 32 has `postings_kept=0` and gated 16 firms).
`wd_runs.mode` is `'manual'` for every run including single-firm ones, so mode
does not distinguish them.

956 tests pass, up from 937. 19 new in `tests/test_single_firm_cache.py`: cached
firm returns the cached verdict at zero gate cost (gate never called, zero
searches, zero tokens, zero cost), the window matches the batch path's, the
reused row carries `cached_wd` and `verdict_cached_from`, `fresh` skips the
lookup entirely and re-gates, a reused and a re-gated row carry distinct
`verdict_source` values so a conflict stays diagnosable, parks always re-gate,
the lock is released on both paths, and the full `/scan` argument matrix. No
vendored `.py` file touched. No scan command run.


## ICP gate adversarial eval: closed - 2026-08-01

Part 1 (offline, zero cost): 3 verdict conflicts in 26 gated firms, all in the
safe direction (qualified->parked). Root causes: single-firm path bypassed the
verdict cache (fixed, commit 059d1c4) and engine drift between Jul 30 and 31.

Part 2 (live, ~24 Tavily searches): Profile Products gated 4x fresh -- verdict,
aum_tag, and park_reason byte-identical every time. The gate is deterministic.
Choice NY re-gated fresh: parked on aum_unverified again, and notably
aum_display/aum_estimated now come back EMPTY where the Jul 30 engine extracted
"$250 million (assets valued)". The proxy tightening is real current behavior,
and the extraction no longer surfaces the portfolio-value figure at all.

Dispositions:
- Verdict instability: EXPLAINED (cache bypass + engine drift), not gate
  non-determinism. Cache fix shipped; conflict warnings now in run summaries.
- Choice NY / Beyond International: possible false parks under current engine.
  Recoverable via /qualify if policy says proxies should count.
- Proxy-figure extraction regression: vendored icp_gate.py behavior -- donor
  filing if Harp wants portfolio-value proxies accepted.

Open policy question for Harp, not code: should an estimated/portfolio-value
AUM figure qualify a firm, or is parking for operator review the intended
behavior? Current engine parks. Jul 30 engine qualified.

## ICP scope change: structure signal required, plus AUM provenance tagging - 2026-08-02

Harpreet's change: the gate moves from industry label to structure signal. A
firm that passes the vendored gate additionally needs at least one sign that it
manages capital or property for someone else, because that is what creates the
back-office load X Analyst staffs. A pure production homebuilder books revenue
from selling houses: no fund to account for, no LP to report to, no third-party
portfolio to close.

Implemented as a Workflow-D post-gate check in `signal_pipeline.gate_group()`,
the same pattern as `foreign_domain_park_reason` and
`acquired_by_parent_park_reason`. `icp_gate.py` untouched.

### Report: where each signal is detectable in the blob

Read off the live rows, not assumed.

| field | what it carries | populated |
|---|---|---|
| `firm_oneliner` | the primary carrier for every signal class | 64/83 |
| `capital_stack` | the cleanest LP/GP carrier: the master's own example is "LP, GP, Co-GP, Preferred Equity" | 11/83 |
| `disclosed_label` | **what the figure measures**, the discriminating field | 32/83 |
| `proxy_basis` | how the figure was derived: "units/sq-ft tertiary proxy", "of commercial property under management" | 31/83 |
| `recent_event` | secondary: "seeking $200M fund" (Raptor Group) | 45/83 |

`disclosed_figure` is **deliberately not scanned**, and that is the whole Neal
case. Three live blobs, all carrying a figure, only two describing capital or
property held for others:

```
Neal      "$905 million"          label "company revenue in fiscal year 2023"
AlphaX    "$522M"                 label "Asset Under Management"
Wasatch   "over 3,000,000 sq ft"  label "of commercial property under management"
```

The figure alone is not a signal. Its label is. Revenue is a production metric,
so Neal parks despite having the largest disclosed number of the three.

Five signal classes, each a regex over the concatenated fields above:
`fund_or_gp`, `limited_partners`, `third_party_capital`, `value_figure` (an
allowlist of value-type labels: AUM, GAV, portfolio value, invested capital,
fund size, and explicitly NOT revenue), `managed_portfolio`. The fund scan runs
over the same text before any parking decision, so a homebuilder with a
BTR or land-fund arm passes on the fund signal and never reaches the
homebuilder outcome.

### Validated against every firm on file

Ran the detector over all 48 distinct firms. **Of the four currently qualified,
exactly one parks: Neal Communities.** That is the intended class and the whole
blast radius.

```
AlphaX                         third_party_capital, value_figure, managed_portfolio
Shinda Management Corporation  value_figure, managed_portfolio
Wasatch Commercial Management  managed_portfolio
Neal Communities               PARKS
```

Choice NY passes on `managed_portfolio` from "Residential-focused property
management and services in NYC metro", which is the third-party-PM case the
rule explicitly admits.

**Three regex bugs caught by validating against real data rather than fixtures:**

1. `vehicle` as a bare token matched Blue Origin's "aerospace launch **vehicle**
   manufacturer". Now requires investment/fund/capital as a qualifier.
2. `owner/operator` matched Aston Carter's "(**not** an owner/operator)" -- the
   phrase that was negating it. Added a negation guard that rejects a match
   preceded within 14 characters by "not a/an", "no" or "non-".
3. The alternation's trailing `\b` made every plural unmatchable: "joint
   venture" could not match "joint venture**s**", because `\b` fails between
   "venture" and "s". Caught by the homebuilder-with-a-fund-arm test. Plurals
   are now explicit on every alternative.

Chipotle still shows `fund_or_gp` from "launched $50M venture fund", which is
correct behaviour on that text. It never reaches the check: this is a POST-gate
check that only runs on a firm the vendored gate already qualified, and
Chipotle is type-rejected.

### AUM provenance tagging

`migrations/wd_005_firms_aum_source.sql` adds `wd_firms.aum_source TEXT`,
nullable, no backfill, so pre-existing rows read as "decided before this was
tracked" rather than asserting a provenance nobody recorded.

Precedence is **operator > disclosed > proxy**, and the order is load-bearing
on live data: the one operator-qualified row on file is ALSO `AUM_CONFIRMED`,
so a disclosed-first rule would mislabel it and hide the fact that a human put
the number there. `/qualify` sets `aum_source="operator"` explicitly rather
than relying on the reason string being parsed back out.

Only qualified rows are tagged. A parked or disqualified row has no figure
worth comparing conversion against, so it carries no provenance rather than a
misleading one. `_reuse_cached` carries the tag forward, so a cached row stays
comparable to the row it came from.

Checked the mapping is total against the 10 qualified rows on file:
AUM_ESTIMATED+non_floor (7) and +units (1) map to proxy, AUM_CONFIRMED with
operator-verified (1) maps to operator, AUM_UNVERIFIED with operator-verified
(1) maps to operator.

### Ordering

geo TLD, then acquired-by-parent, then structure. A firm failing more than one
parks once, attributed to the first, and a test pins that.

1006 tests pass, up from 956. 50 new in `tests/test_structure_signal.py`. Three
existing gate tests needed a structure signal added to their fixtures: they
build minimal blobs to test the geo and acquired-by checks, and without a
signal the new check parked them first. That is correct new behaviour and stale
fixtures, not a regression. No vendored `.py` file touched. No scan command run.
