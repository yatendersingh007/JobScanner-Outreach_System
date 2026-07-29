# DRIFT.md — vendored code provenance

Every file below was copied byte-for-bit (`cp`, never retyped) from its donor
repo, then had a provenance header prepended and, where noted, a local edit
applied. **Never edit a vendored file to fix a bug without also filing the fix
against the donor repo** (CLAUDE.md). Donor commits at copy time:

- referral-system: `078493aa00e27dcd17716c0f57bb6d0ae35644da` (clean working tree)
- job-scanner: `8a5392cefbcbdf4f1dc8454ac464389d35ce230f` (clean working tree)

Copy date for every row below: 2026-07-28.

## lib_referral/ (from referral-system/src/)

| Target path | Source repo | Source path | Commit | Local edits | Filed against donor |
|---|---|---|---|---|---|
| lib_referral/__init__.py | referral-system | src/__init__.py | 078493a | none | n/a |
| lib_referral/config.py | referral-system | src/config.py | 078493a | Lines 41, 42, 51 deleted (`CONNECTIONS_CSV`, `REFERRAL_EMAIL_TEMPLATE`, `REFERRER_FIRMS`) — Manpreet/Singh Capital/referral-specific, unread once email_drafter.py and preflight.py are excluded from this vendor set (verified by grep, zero hits left in lib_referral/ except this file's own explanatory comment). The comment block originally contrasting `SENDER_FIRMS` against `REFERRER_FIRMS` ("above") was reworded so it no longer dangles on a deleted symbol. | n/a — workflow-d-specific trim, not a donor defect |
| lib_referral/icp_gate.py | referral-system | src/icp_gate.py | 078493a | none | n/a |
| lib_referral/fact_check.py | referral-system | src/fact_check.py | 078493a | none | n/a |
| lib_referral/deck_filler.py | referral-system | src/deck_filler.py | 078493a | none | n/a |
| lib_referral/apollo_enrich.py | referral-system | src/apollo_enrich.py | 078493a | none | n/a |
| lib_referral/gmail_client.py | referral-system | src/gmail_client.py | 078493a | none | n/a |
| lib_referral/personalization.py | referral-system | src/personalization.py | 078493a | none | n/a |
| lib_referral/testmode.py | referral-system | src/testmode.py | 078493a | none | n/a |
| lib_referral/matching/__init__.py | referral-system | src/matching/__init__.py | 078493a | none | n/a |
| lib_referral/matching/normalize.py | referral-system | src/matching/normalize.py | 078493a | none | n/a |
| scripts/office/soffice.py | referral-system | scripts/office/soffice.py | 078493a | none — thin LibreOffice-locator wrapper, referenced by `lib_referral/config.py`'s `SOFFICE_SCRIPT` (used by `deck_filler.py` for PPTX→PDF conversion). Missed in the original diagnose pass (scope was `src/` and `lib_snapshot/`, not the repo-root `scripts/` directory) and added on request. Verified: `lib_referral.config.SOFFICE_SCRIPT` resolves to `C:\Users\DELL\Job-ScannerOutreach\scripts\office\soffice.py` and `.exists()` is `True`. | n/a |

**Excluded from lib_referral/ (explicit decision, not an oversight):**
`src/email_drafter.py` and `src/preflight.py` are NOT vendored. Prompts 3 and 5
build workflow-d's own versions; the donor is read in-workspace when that work
starts. `src/email_drafter.py:28` is `FIXED_SUBJECT = "Intro via Manpreet Singh
(Singh Capital)"` — a reference-only copy inside the package is one import away
from live, so it stays out entirely. `src/matching/firm_matcher.py` and
`lib_snapshot/researcher/exa_client.py` are also excluded: unreachable from the
9 traced entry points.

## lib_snapshot/ (from referral-system/lib_snapshot/) — project root, sibling of lib_referral/

Placement: at `Job-ScannerOutreach/lib_snapshot/`, NOT nested under
`lib_referral/`. In referral-system, `lib_snapshot/` sits one level under the
repo root, so `lib_snapshot/config.py`'s `ROOT = Path(__file__).resolve().parents[1]`
resolves to the repo root. Root-level placement here reproduces that exact
relationship with zero code changes, and matches `src/wd_dbc.py`'s already-committed
`from lib_snapshot import db as shared_db` (an absolute import that requires
`lib_snapshot` to be a top-level package, not nested inside `lib_referral`).

| Target path | Source repo | Source path | Commit | Local edits | Filed against donor |
|---|---|---|---|---|---|
| lib_snapshot/__init__.py | referral-system | lib_snapshot/__init__.py | 078493a | none | n/a |
| lib_snapshot/config.py | referral-system | lib_snapshot/config.py | 078493a | none — root-level placement (above) keeps `ROOT`/`MIGRATIONS_DIR`/`TEMPLATES_DIR`/`PROMPTS_DIR`/`load_dotenv(ROOT/".env")` all correct unedited | n/a |
| lib_snapshot/db.py | referral-system | lib_snapshot/db.py | 078493a | `init_db()` and `reset_db()` bodies replaced with `raise RuntimeError(...)`; the `__main__` dispatch's `init`/`reset` branches removed (refuse + exit, never call into the functions); `migrate()`'s `files = sorted(mig_dir.glob("*.sql")) if mig_dir.exists() else []` changed to raise `FileNotFoundError` when `MIGRATIONS_DIR` is missing, instead of silently treating it as zero migrations | init_db/reset_db/`__main__` edits: n/a, workflow-d-specific safety (shared `outreach` DB). **migrate() missing-directory branch: YES — this is a donor bug** (see below), **still needs filing against referral-system**, not yet done. |
| lib_snapshot/models.py | referral-system | lib_snapshot/models.py | 078493a | none | n/a |
| lib_snapshot/researcher/__init__.py | referral-system | lib_snapshot/researcher/__init__.py | 078493a | none | n/a |
| lib_snapshot/researcher/search_client.py | referral-system | lib_snapshot/researcher/search_client.py | 078493a | none | n/a |
| lib_snapshot/enrichment/__init__.py | referral-system | lib_snapshot/enrichment/__init__.py | 078493a | none | n/a |
| lib_snapshot/enrichment/apollo.py | referral-system | lib_snapshot/enrichment/apollo.py | 078493a | none | n/a |
| lib_snapshot/drafting/__init__.py | referral-system | lib_snapshot/drafting/__init__.py | 078493a | none | n/a |
| lib_snapshot/drafting/pitch_deck.py | referral-system | lib_snapshot/drafting/pitch_deck.py | 078493a | none — `build_pitch_deck()` and the `deck_gen/build_deck.js` path it shells out to are dead code in this vendor set (`deck_gen/` is absent on disk in the donor too); only `_BIG_MONEY_RE`/`_short_name` are actually used, by lib_referral/deck_filler.py | n/a |

**Donor bug filed here, not yet filed upstream:** `migrate()`'s original
`if mig_dir.exists() else []` silently treats a missing/misconfigured
`MIGRATIONS_DIR` as "zero migrations to apply" — `apply_migrations()` then
logs "no un-applied migrations" and returns success while no table was ever
created, so the first real query fails on a missing table instead of the real
cause failing loudly at migration time. This reproduces in referral-system
itself, independent of relocation. **Action needed: file this against
referral-system's `lib_snapshot/db.py`.**

## scanner/ (from job-scanner/scanner/)

| Target path | Source repo | Source path | Commit | Local edits | Filed against donor |
|---|---|---|---|---|---|
| scanner/pipeline.py | job-scanner | scanner/pipeline.py | 8a5392c | this is the entry point the import graph was traced from; initially missed in the first copy pass (only its 18-file closure was copied) and added when `from scanner import pipeline` failed at VERIFY. **2026-07-29**: one line added to `run()`'s connector loop — `skipped = getattr(connector, "skipped_targets", None); if skipped: cfg.tinyfish_skipped_targets = skipped` (plus a companion line for `steps_launched`) — reads TinyFishConnector's new skip-tracking (see the tinyfish.py row below) and stashes it on `cfg` as a dynamic attribute so `src/signal_pipeline.py` (which already holds `cfg`) can surface it in the run summary. `run()`'s signature, return type, and every other line are unchanged. | **not filed** — see donor observation below (pre-existing) and the 2026-07-29 edit (workflow-d-specific surfacing, not a donor bug fix) |
| scanner/__init__.py | job-scanner | scanner/__init__.py | 8a5392c | none | n/a |
| scanner/classifier.py | job-scanner | scanner/classifier.py | 8a5392c | none | n/a |
| scanner/config.py | job-scanner | scanner/config.py | 8a5392c | none | n/a |
| scanner/filters.py | job-scanner | scanner/filters.py | 8a5392c | none | n/a |
| scanner/models.py | job-scanner | scanner/models.py | 8a5392c | none | n/a |
| scanner/poc_enricher.py | job-scanner | scanner/poc_enricher.py | 8a5392c | none | n/a |
| scanner/poc_store.py | job-scanner | scanner/poc_store.py | 8a5392c | none | n/a |
| scanner/seen_store.py | job-scanner | scanner/seen_store.py | 8a5392c | none | n/a |
| scanner/connectors/__init__.py | job-scanner | scanner/connectors/__init__.py | 8a5392c | none | n/a |
| scanner/connectors/base.py | job-scanner | scanner/connectors/base.py | 8a5392c | none | n/a |
| scanner/connectors/ats.py | job-scanner | scanner/connectors/ats.py | 8a5392c | none | n/a |
| scanner/connectors/tinyfish.py | job-scanner | scanner/connectors/tinyfish.py | 8a5392c | **2026-07-29**: `TinyFishConnector.fetch()` gained per-group cumulative step-budget tracking (`LINKEDIN_MAX_STEPS=30`, `SPECIALIST_MAX_STEPS=40`, read via `os.getenv` directly — see module comment for why not `src.wd_config`), an overall cap wiring the previously-dead `TINYFISH_STEP_CAP_PER_RUN` env var (`OVERALL_MAX_STEPS`, default 200), a consecutive-failure abort (`MAX_CONSECUTIVE_FAILURES=3`), and two new public attributes (`skipped_targets`, `steps_launched`) so a skip is always recorded, never a silent truncation. The request/poll/extract logic (`_run`, `_poll`, `_headers`, `_extract_jobs`, `_parse_date`) is byte-identical to the donor. | **not yet filed** — this is a genuine feature addition (an unenforced budget guard, now enforced), not a bug fix, but the same "file it against the donor" discipline applies since job-scanner's own users would want the same guard. Action needed. |
| scanner/connectors/aggregator.py | job-scanner | scanner/connectors/aggregator.py | 8a5392c | none | n/a |
| scanner/connectors/adapters/__init__.py | job-scanner | scanner/connectors/adapters/__init__.py | 8a5392c | none | n/a |
| scanner/connectors/adapters/base.py | job-scanner | scanner/connectors/adapters/base.py | 8a5392c | none | n/a |
| scanner/connectors/adapters/jsearch.py | job-scanner | scanner/connectors/adapters/jsearch.py | 8a5392c | none | n/a |
| scanner/connectors/adapters/predictleads.py | job-scanner | scanner/connectors/adapters/predictleads.py | 8a5392c | none | n/a |
| scanner/connectors/adapters/theirstack.py | job-scanner | scanner/connectors/adapters/theirstack.py | 8a5392c | none | n/a |
| scanner/config.yaml | job-scanner | config.yaml (repo root, not scanner/) | 8a5392c | Relocated from job-scanner's repo root into scanner/ — matches `wd_config.py`'s existing `SCANNER_CONFIG_PATH` default (`ROOT/scanner/config.yaml`), not job-scanner's own layout. Also initially missed in the first copy pass; added when caught in VERIFY. | n/a |
| classifier_rules.yaml (project root) | job-scanner | classifier_rules.yaml (repo root) | 8a5392c | Placed at the workflow-d project root, not inside scanner/. `scanner/classifier.py`'s `load_rules()` opens `cfg.classifier_rules_file` (default `"classifier_rules.yaml"`, a bare relative path resolved against the process's CWD, not against config.yaml's own location or `__file__`) — project-root placement matches the CWD `python -m src.cli scan`/the bot are expected to run from. **This placement is a judgment call, not verified end-to-end against an actual pipeline run yet** — flag for confirmation once `signal_pipeline.py`'s actual `classify()` call site is exercised. | n/a |

**Donor observation, not filed, no local fix (Prompt 1 diagnose):**
`scanner/pipeline.py:118-120` checks `newly_seen = store.is_new(key)` and then
unconditionally calls `job.first_seen = store.first_seen(key, today)` —
`SeenStore.first_seen()` inserts the key into `seen.db` right there, before
the recency filter (line 128) has decided whether to keep or drop the
posting. So a posting the recency filter drops is still permanently recorded
as "seen" as of that run's date. Net effect: the automatic grace-window bump
(`effective_days = max(cfg.recency_days, cfg.first_seen_grace_days)`) only
ever applies while `newly_seen` is `True` — exactly once per key, on first
sighting. Every later evaluation of the same key uses `cfg.recency_days`
directly, with no automatic grace, so recovering a dropped posting requires
the operator to explicitly pass a wider `recency_days` override on that later
run; it never happens on its own. This is a real, reproducible behavior
(confirmed by `tests/test_recency_window.py`'s three-run sequence: drop at
days=1, recover at days=7 via explicit override, drop again at days=1), not
a hypothetical. **Not changed here per explicit instruction**: reordering the
insert would change semantics for a vendored file two other workflows may
later share, and the fix (if any) belongs with the donor, not as a silent
local patch. Recorded as a landmine in CLAUDE.md ("the recency grace window
is one-shot per posting... after a gap, the catch-up run must come FIRST").

## Non-Python assets

| Target path | Source repo | Source path | Commit | Local edits | Filed against donor |
|---|---|---|---|---|---|
| templates/Pitch_Master.pptx | referral-system | templates/Pitch_Master.pptx | 078493a | none — binary asset, no header injected, provenance tracked here only | n/a |
| templates/pitch_slots.json | referral-system | templates/pitch_slots.json | 078493a | none — JSON asset, no header injected (would break parsing), provenance tracked here only | n/a |
| prompts/icp_scoring_v2_2.md | referral-system | prompts/icp_scoring_v2_2.md | 078493a | none — HTML-comment provenance header prepended (markdown-invisible), prompt text itself untouched | n/a |

## Not vendored (checked, deliberately excluded)

- `data/connections.csv`, `templates/referral_email.md`, `src/email_drafter.py`,
  `src/preflight.py`, `src/pipeline.py`, `src/telegram_bot.py`, `src/dbc.py`,
  `src/loader.py`, `src/batch_upload.py`, `src/status.py`,
  `src/matching/firm_matcher.py`, `lib_snapshot/researcher/exa_client.py`,
  `lib_snapshot/approval/` (telegram_queue.py, __init__.py),
  `lib_snapshot/drafting/gmail_drafter.py`, `deck_gen/` (absent on disk in the
  donor), `schema.sql` (absent on disk in the donor; `dbc.py` never calls it).
- referral-system's own `migrations/002_workflow_c.sql` through
  `007_wc_runs_cancel_flag.sql` — Workflow C's own tables, not needed here.

## Migration filename convention (not a vendored file, recorded here for one place to look)

`migrations/010_wd_tables.sql` renamed to `migrations/wd_001_tables.sql`.
`lib_snapshot/db.py`'s `migrate()` keys applied migrations on bare filename
(`schema_migrations.filename TEXT PRIMARY KEY`) in the shared `outreach`
Postgres database — referral-system, workflow-d, and Workflow A (if it shares
the same instance) all insert into the same table. A purely numeric prefix
risks a future collision; every workflow-d migration should use the
`wd_NNN_description.sql` convention going forward (referral-system's own
migrations already carry a `wc_`/`workflow_c` marker in the filename).
