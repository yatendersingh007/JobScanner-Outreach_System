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
