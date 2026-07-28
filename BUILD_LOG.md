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
