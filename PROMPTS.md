# Workflow D build prompts — Claude Code in VS Code

## How to run these sessions

**Do not hand Claude Code a meta-prompt that says "read PROMPTS.md and run all
of them in order."** Four concrete reasons, not stylistic ones:

1. Six of these eight prompts contain a `STOP` that waits on your judgment.
   Prompt 0 stops so you confirm the vendored file list. Prompt 1 stops so you
   check the recency arithmetic. Prompt 4 stops if `preflight_slots()` fails.
   A model told to run the whole file treats those stops as something to print
   and walk past, because continuing is what it was asked to do. The stops are
   the review gates, and they sit exactly where a wrong assumption gets
   expensive.
2. Context. Vendoring a whole donor closure, then drafting, then the deck, then
   the bot, then tests, will exhaust the window and start compacting. What gets
   dropped first is the early decisions, which is precisely what later steps
   depend on.
3. If prompt 2 goes subtly wrong, prompts 3 through 7 build on top of it and
   you find out at deploy. One prompt per session means one green suite per
   step and a real diff to read.
4. It contradicts the discipline the codebase already runs on: scope-locked,
   DO-NOT-CHANGE list, diagnose first, report count and delta. A meta-prompt is
   the opposite of scope-locked.

**Instead:** one prompt per session, `/clear` between them, and let the repo
carry the state. Have prompt 0 create `BUILD_LOG.md`, then append to it at the
end of every session:

```
## Prompt N - <name> - <date>
Built: <files>
Tests: <count> (delta +N)
Decisions made: <anything you chose that the prompt left open>
Deviations from the prompt, and why: <or "none">
Open for next session: <anything>
```

Open each new session with:

```
Read CLAUDE.md, BUILD_LOG.md, and DRIFT.md. Summarize in five lines where the
build stands. Then run prompt N from PROMPTS.md. Nothing else.
```

That gives continuity without asking one context window to hold eight steps.
The only pair worth merging is 5 and 6; everything else stays separate.

## Before prompt 0

```
workflow-d/
  CLAUDE.md              <- from this handoff, commit it first
  .env                   <- from .env.example, filled in
  scanner/               <- vendored Job Scanner
  lib_referral/          <- vendored referral-system (prompt 0 does this)
  src/                   <- signal_pipeline.py, wd_dbc.py, wd_config.py,
                            wd_telegram.py already exist
  migrations/010_wd_tables.sql
  templates/signal_email.md
  tests/test_scanner_core.py
```

Open the workspace with BOTH repos visible so Claude Code can read the donor:

```
code --add C:\path\to\workflow-d C:\path\to\referral-system C:\path\to\job-scanner
```

`CLAUDE.md` is read automatically every session. It carries the hard rules, so
the prompts below stay short. Commit it before prompt 0.

One standing instruction to paste at the top of any session where Claude Code
starts drifting: **"Re-read CLAUDE.md. Then tell me which rule my last request
conflicts with, if any, before you write code."**

---

## Prompt 0 — vendor the donor code

```
DIAGNOSE FIRST, PRINT ONLY, NO EDITS.

Read referral-system/ and job-scanner/ and print:
1. The full import graph for src/icp_gate.py, src/fact_check.py,
   src/email_drafter.py, src/deck_filler.py, src/apollo_enrich.py,
   src/gmail_client.py, src/preflight.py, src/personalization.py,
   src/testmode.py. Every internal module each one reaches, transitively,
   including lib_snapshot.
2. The same for job-scanner: scanner/pipeline.py's transitive imports.
3. The current git commit hash of each repo.
4. Any file in that closure that reads a config value workflow-d does not
   define in src/wd_config.py.

STOP after printing. I will confirm the file list before you copy anything.
```

Then, after you confirm:

```
SCOPE: create lib_referral/ and complete scanner/ in workflow-d. Copy only the
files from the list I confirmed.

DO NOT CHANGE: anything under src/ that already exists. Do not modify a single
line of any file you copy, except to prepend the provenance header.

BUILD:
1. Copy each file into lib_referral/ (referral-system origin) or scanner/
   (job-scanner origin), preserving relative structure.
2. Prepend to every copied file:
   # VENDORED - DO NOT EDIT IN PLACE
   # source: <repo>/<path>
   # commit: <hash>
   # copied: <date>
   # Fixing a bug here requires the same fix filed against the donor repo.
3. Write DRIFT.md: a table of every vendored file, its source repo, path,
   commit, copy date, and a "local edits" column that says "none" for all of
   them right now.
4. Fix imports so lib_referral and scanner import cleanly from workflow-d's
   root. Prefer adjusting workflow-d's own sys.path / package layout over
   rewriting vendored import lines. If a vendored line must change, record it
   in DRIFT.md's local-edits column and say so in your report.
5. requirements.txt from the union of what the vendored closure needs. Pin
   openpyxl==3.1.5 and rapidfuzz==3.10.1 as referral-system does.

VERIFY:
- python -c "import lib_referral.icp_gate, lib_referral.fact_check,
  lib_referral.deck_filler, lib_referral.email_drafter" succeeds.
- python -c "from scanner import pipeline; from scanner.config import Config"
  succeeds.
- pytest tests/ -q still passes 75/75.
- grep -rn "\.send()" lib_referral/ scanner/ src/ returns nothing that is an
  email send. Print what it does return.

REPORT: files vendored, any import line you had to change and why, test count
and delta.
```

---

## Prompt 1 — manual trigger only, and the catch-up window

This is the architecture change. No timer, ever.

```
DIAGNOSE FIRST, PRINT ONLY.

1. Print scanner/pipeline.py lines that compute effective_days and the
   recency filter, plus first_seen_grace_days from scanner/config.yaml.
2. Answer this concretely with the code in front of you: if the last run was
   6 days ago, a posting published 4 days ago and never seen before - does it
   survive the recency filter? Show the arithmetic.

STOP. I want your answer before you build.
```

Expected answer: it does not. `effective_days = max(recency_days=1,
first_seen_grace_days=3) = 3`, so anything older than 3 days is dropped on
first sight. With a timer that never mattered because the gap was always one
day. With manual triggering, a holiday break silently drops postings. That is
what the next step fixes.

```
SCOPE: manual trigger with an explicit catch-up window. Delete the scheduler.

DO NOT CHANGE: scanner/ (vendored). signal_pipeline.py's grouping, cache and
gate logic. wd_dbc.py.

BUILD:
1. DELETE deploy/workflow-d.service and deploy/workflow-d.timer. There is no
   scheduled run. Create deploy/workflow-d-bot.service instead: long-running
   long-poll bot, Type=simple, User=outreach, Restart=always, RestartSec=10,
   ExecStart=/opt/workflow-d/.venv/bin/python -u -m src.bot. Update
   deploy/install.sh: install the bot unit, no timer, keep the tee-not-
   systemctl-edit pattern and the systemctl show verification.
2. src/daily_run.py becomes src/run_scan.py. Same body, but it is a function
   called by a command, not a systemd entrypoint. Signature:
   run_scan(mode: str, days: int = 1, dry: bool = False,
            gate_cap: int | None = None, progress=...) -> RunResult
3. signal_pipeline.scan() takes recency_days: int = 1. Keep the existing
   assert that config.yaml itself says 1, so file drift can never silently
   widen the window, but let the caller override it in memory for this run
   only. Validate 1 <= days <= 14 and raise ValueError outside that.
   Record the value used in wd_runs (new column recency_days_used, additive
   migration 011) and print it in the Telegram summary every run:
   "Window: last N days (catch-up)" when N > 1.
4. src/cli.py with argparse: `python -m src.cli scan [--days N] [--dry]
   [--cap N] [--firm "Name"]`. This is the local/VS Code entrypoint and the
   thing the Telegram command calls. One code path, two front doors.

   IMPORTANT, this is a change from the earlier design: `scan` runs the FULL
   pipeline by default, through to Gmail drafts. There is no separate pursue
   step and no confirm prompt. Harpreet issues one command and the rest is
   automatic. `--dry` is the opt-out that stops after gating, for when you want
   to look at a day's output without spending Apollo credits.

   So: pursue is the default, dry is the flag. Make sure the parser reflects
   that and not the reverse.
5. wd_config: delete AUTO_DRAFT_ON_SCHEDULE, it is meaningless now. Add
   DEFAULT_SCAN_DAYS=1 and MAX_SCAN_DAYS=14. Set DRAFT_CAP_PER_RUN=5, lower
   than the gate cap on purpose: with no human confirm between gating and
   drafting, the cap IS the guard. Exceeding it parks the remainder in the
   queue for /resume and says so in Telegram. It never silently truncates and
   it never drafts past the ceiling.

VERIFY:
- New tests in tests/test_recency_window.py: days=1 is the default; days=0 and
  days=15 raise; a 4-day-old never-before-seen posting is dropped at days=1 and
  kept at days=7; the value is persisted to wd_runs and appears in the summary
  string. Use a fake connector, no network.
- grep -rn "OnCalendar\|systemd.timer\|APScheduler\|schedule\|cron" src/ deploy/
  returns nothing.
- pytest tests/ -q green, report count and delta.

REPORT: the arithmetic from the diagnose step, what you deleted, the new
command surface.
```

---

## Prompt 2 — Telegram bot: the only way a run starts

```
DIAGNOSE FIRST, PRINT ONLY.

Read referral-system/src/telegram_bot.py and print:
1. run_bot()'s polling loop, exactly where the AUTHORIZED_USER_IDS check
   happens relative to _dispatch.
2. The _LiveBatchStatus class: how it rate limits, what it does on the
   terminal states done/cancelled/crashed.
3. _fmt_summary's bucket structure.
4. How /cancel sets and reads the persisted cancel flag.

STOP. Then tell me what you will reuse verbatim versus rewrite, and why.
```

```
SCOPE: src/bot.py, Workflow D's command surface. New bot token, new allowlist.

DO NOT CHANGE: signal_pipeline.py. wd_dbc.py except to add functions you need.
lib_referral/. Do not touch referral-system at all.

BUILD src/bot.py following referral_system/src/telegram_bot.py's structure:

1. Long-poll loop. The AUTHORIZED_USER_IDS check happens IN THE LOOP, before
   _dispatch, exactly as Workflow C does it, so every command inherits
   authorization for free and no command can forget it.
2. Commands. `/scan` is the whole pipeline. One command from Harpreet, then
   scan, classify, group, cache-check, gate, POC lookup, email, deck, Gmail
   draft, all of it, with Telegram narrating. There is NO confirm gate and no
   separate pursue command.
   /scan                  - full run: scan -> gate -> draft -> Gmail drafts
   /scan days 7           - same, catch-up window after a break
   /scan dry              - stop after gating. Summary only, no Apollo, no
                            drafts. The opt-out, not the default.
   /scan "Firm"           - single-firm override, skips the scanner entirely
   /status                - last run dashboard: buckets, spend, queue depth
   /qualify "Firm" 450M   - rescue a parked firm, same pattern as Workflow C
   /disqualify "Firm"     - same
   /cancel  (alias /scan stop) - persisted DB flag, checked at the top of every
                            per-firm iteration, never mid-firm. The in-flight
                            firm finishes cleanly. This is the only interrupt,
                            so it has to work: test it against a run that is
                            mid-draft, not just mid-gate.
   /resume                - continue the latest crashed or cancelled run from
                            the queue, without re-drafting anything done
   /help

2a. Because there is no confirm gate, the run POSTS its spend intent instead of
   asking for it. Right after gating, before the first Apollo call, send one
   message: how many firms qualified, how many will be drafted, how many are
   parked over the draft cap, and the estimated Apollo and LLM spend. It is
   information, not a question. The run continues. /cancel is there if the
   number is wrong, and the ceilings stop it regardless.
3. Notification stream, mirroring Workflow C: run started, per-stage progress
   via message EDIT not new messages (rate limited, wd_telegram.progress
   already does this), then the final summary with buckets:
   drafted / drafted-with-prior-contact / parked / no-email / disqualified /
   skipped-known / over-cap, each naming firms and reasons.
4. Every summary carries a spend line: Tavily searches, LLM tokens, TinyFish
   steps, JSearch calls, research USD. And a connector-health line whenever a
   normally-productive source returned zero, naming the source.
5. src/bot.py must not contain business logic. It parses, authorizes, calls
   src/cli.py's functions, formats. If you find yourself writing a gate
   decision or a dedup rule in bot.py, it belongs in the pipeline.

VERIFY:
- tests/test_bot_dispatch.py: every command routes correctly with a fake
  sender; an unauthorized user id reaches nothing; /scan dry drafts zero firms
  and makes zero Apollo calls; /scan with no args drafts; quoted firm names
  with commas and apostrophes parse; a command fragment like /scan "dry" is
  rejected rather than treated as a firm name; DRAFT_CAP_PER_RUN=2 against 5
  qualified firms drafts exactly 2 and parks 3. Test _dispatch directly, never
  run_bot's loop, and use no live token.
- pytest tests/ -q green, report count and delta.

REPORT: command table, what you reused verbatim from Workflow C, what you
rewrote and why.
```

At this point `/scan dry` works end to end and reports to Telegram. `/scan`
itself is not complete until prompts 3 and 4 land the drafting half, so until
then have it fail loudly with "drafting not built yet, use /scan dry" rather
than silently behaving like dry. A command that quietly does less than its name
says is how you ship a run that nobody notices did nothing.

---

## Prompt 3 — the signal email

The template text is in `templates/signal_email.md`. Harp approves it before
any live draft. This prompt builds the enforcement around it.

```
DIAGNOSE FIRST, PRINT ONLY.

Read lib_referral/email_drafter.py and lib_referral/fact_check.py and print:
1. Every check function in email_drafter and which of them is Workflow C
   specific (references Manpreet, the referral, or C's fixed blocks) versus
   generic.
2. The exact generate -> validate -> retry -> fallback control flow in
   _generate_blocks, including where fallback counts are recorded.
3. fact_check's three public functions with signatures, and what
   grounding_corpus expects as input.

STOP. Then list which checks Workflow D keeps, which it drops, and which are
new, before writing anything.
```

```
SCOPE: src/signal_drafting.py. Reuse email_drafter's ARCHITECTURE, not its
content.

DO NOT CHANGE: lib_referral/email_drafter.py, lib_referral/fact_check.py, or
templates/signal_email.md's text. If you believe the template text is wrong,
say so in your report and stop. Harp approves that text, not you and not me.

BUILD:
1. Block 1 and Block 6 are assembled in PYTHON, not generated. The posting
   title, the firm name and the posting URL are the facts that must never be
   wrong, and the way to guarantee that is to never let a model retype them.
   Only Block 2 and Block 4 are LLM-generated.
2. Grounding corpus for this template = the gate's research dict PLUS the
   posting facts: exact title, firm name, posting URL, distinct posting count.
   That is what makes the posting mechanically verifiable.
3. Required-fact checks, drafting FAILS without them:
   - posting title in Block 1, character for character
   - firm name in Block 1
   - posting URL in Block 6
   - both dollar ranges in Block 3 unmodified
4. Forbidden-claim checks, any hit is a HARD FAILURE not a retry:
   - Manpreet, Singh Capital, referral, introduction, mutual connection,
     "we were connected", "was suggested"
   - any claim we have spoken to this firm before
   - any figure about the firm not in the corpus, including a computed saving
   Write a regex set for this and test it adversarially. A cold email that
   claims a referral is the exact integrity failure this template exists to
   prevent, so the check is mechanical, not a prompt instruction.
5. Keep from Workflow C, adapted: banned words and phrases, number fidelity
   (a number not in the corpus fails the whole block, never a partial edit),
   Block 4 must not reuse Block 2's number, the trim-whole-trailing-sentences
   length guard at EMAIL_MAX_WORDS=260, fallback telemetry with stage and
   reason logged.
6. State the offering explicitly in the generation prompt from the fixed list
   in the template. FIX 29: without it the model invents PropTech.
7. draft_for_run(run_id, progress) -> writes wd_drafts rows. It is called
   INLINE by the same run that gated, not by a second command, so it must
   respect the persisted cancel flag between firms and stop at
   DRAFT_CAP_PER_RUN by parking the remainder. Before each
   draft, call the cross-workflow contacted_pocs check: advisory, never
   blocking, write collision_note and prior_contact_workflow, and give it its
   own summary bucket.

VERIFY:
- tests/test_signal_drafting.py, adversarial: an LLM response containing
  "Manpreet suggested" fails hard and is never patched; a reworded posting
  title fails the required-fact check; a fabricated dollar figure triggers the
  whole-block fallback; the 260-word guard drops whole sentences only, never
  mid-sentence; the corpus contains the posting URL. Fake the LLM client, no
  network.
- Print one full generated email to stdout for me to read.
- pytest tests/ -q green, report count and delta.

REPORT: the check table (kept / dropped / new), fallback telemetry counters,
and the sample email.
```

---

## Prompt 4 — deck with a posting-aware fit angle

```
DIAGNOSE FIRST, PRINT ONLY.

1. lib_referral/deck_filler.py: get_deck_content's prompt, build_fill_data's
   signature, and every slot key in pitch_slots.json.
2. Which slot is the "Where this fits <Firm>" surface, and how many fit
   paragraph keys exist.
3. The money-scrub logic and the disclosed-figure whitelist.
4. Whether assets/Pitch_Master.pptx and pitch_slots.json are present in
   workflow-d and whether preflight_slots() passes against them.

STOP if preflight_slots() fails. Print exactly which locator broke.
```

```
SCOPE: pass the posting into deck content generation.

DO NOT CHANGE: the money-scrub, the disclosed-figure whitelist, the slot
locators, or fill_deck. Do not re-export the PPTX.

BUILD:
1. get_deck_content gains the distinct posting titles and count. The "Where
   this fits" paragraph names the hiring need and maps that specific role to
   one of the six service functions. A CAM analyst opening and a fund
   controller opening are different paragraphs.
2. The posting titles join the deck's grounding corpus, so the fit paragraph
   naming the role is verifiable and a fit paragraph naming a role they are
   NOT hiring for gets dropped by the existing ungrounded-claim check.
3. The $145K-$180K and $55K-$75K ranges stay whitelisted disclosed figures.
   Never recalculated per firm, never turned into a percentage, never
   presented as this firm's actual saving. We do not know their salary band.
4. AUM_ESTIMATED firms still get a blank AUM stat card, not a substituted
   stat. That decision is settled.

VERIFY:
- tests/test_deck_fit_angle.py: the fit paragraph references the actual
  posting title; a paragraph naming an unrelated role is dropped by the
  grounding check; both dollar ranges survive the money-scrub; an
  AUM_ESTIMATED firm's AUM card is blank.
- Generate one real PDF locally and open it. Confirm no placeholder leaks,
  no text overflowing a stat tile.
- pytest tests/ -q green, report count and delta.

REPORT: the fit paragraph for two different posting titles at the same firm,
side by side.
```

---

## Prompt 5 — preflight and budget ceilings

```
SCOPE: src/preflight.py plus enforced ceilings. Nothing else.

BUILD:
1. preflight() runs at bot startup AND at the top of every run, and aborts the
   run naming exactly what is wrong:
   - .env present, every required key non-empty
   - Postgres reachable, all wd_ tables exist, migrations applied
   - Pitch_Master.pptx and pitch_slots.json present, preflight_slots() clean
   - templates/signal_email.md parses into the expected blocks
   - Gmail token loads and its scope is gmail.compose ONLY
   - assert wd_config.NEVER_SEND is True
   - LibreOffice on PATH (VM only)
   - scanner/config.yaml still says recency_days: 1 and
     require_title_match: true
2. Enforced ceilings, not just logged: GATE_CAP_PER_RUN, DRAFT_CAP_PER_RUN,
   TINYFISH_STEP_CAP_PER_RUN, MAX_LLM_TOKENS_PER_FIRM. Hitting a ceiling
   parks the remainder in the queue and says so in Telegram. It never
   silently truncates.
3. Tavily key-pool rotation carried over: rotate on 432/401/403, NOT on 429
   (that is ordinary rate limiting, already handled by same-key retry).
   Telegram notice on rotation. The circuit breaker trips only when the whole
   pool is dead. /resume re-reads .env from disk so a key added mid-pause is
   picked up without a bot restart.

VERIFY:
- tests/test_preflight.py: each failure mode aborts with its own message; a
  gmail token with send scope is REJECTED; ceilings park rather than truncate.
- pytest tests/ -q green, report count and delta.
```

---

## Prompt 6 — TEST_MODE end to end

```
SCOPE: src/testmode.py plus scripts/run_e2e_test.py, following
referral-system's testmode.py pattern.

BUILD a five-outcome scenario with fixtures, zero network:
1. A firm that qualifies and drafts, with a filled PDF deck attached
2. A firm that disqualifies on AUM above $2B
3. A firm that parks on aum_unverified
4. A firm with no findable POC email
5. A firm already contacted via Workflow C: drafts anyway, flagged advisory

Plus: a staffing firm dropped before the gate, a company whose verdict comes
from cache instead of a gate call, and one posting appearing from two sources
that must count as one opening.

Assert on the Telegram summary text itself, not just the DB rows. The summary
is what a human acts on, so it is the thing that must be right.

VERIFY: scripts/run_e2e_test.py exits 0 and prints all outcomes. pytest green.
REPORT: the full summary text the run produced.
```

---

## Prompt 7 — deploy

```
DIAGNOSE FIRST, PRINT ONLY. Do not touch the VM yet.

Print the deploy plan: exact zip exclude list, scp destination, rsync flags,
the grep -c marker commands that prove arrival, and the restart sequence.
Confirm rsync has no --delete and explain what that preserves.

STOP for my approval.
```

Then, by hand, in this order:

1. `git init`, commit, push to a private repo. Verify `.env`, `token.json`,
   `credentials.json`, `*.db` are all ignored: `git ls-files | grep -iE
   "env|token|credential|\.db"` must return nothing.
2. Zip excluding `.venv node_modules __pycache__ .git qa_out output`. scp,
   unzip, rsync into `/opt/workflow-d`.
3. `grep -c` a marker string in two or three files on the VM to prove arrival
   before restarting anything.
4. `.env` on the VM is source of truth. Fill it there by hand. Keys do not
   sync. Transfer `credentials.json` and `token.json` separately, never zipped.
5. `python -c "from src import wd_dbc; wd_dbc.apply_migrations()"`. Idempotent.
6. `install.sh` for the bot unit. `systemctl status workflow-d-bot`, then
   `systemctl show workflow-d-bot -p Restart -p RestartSec` to confirm the
   drop-in took.
7. `TEST_MODE=true`, send `/scan` from Telegram, read the summary.
8. `TEST_MODE=false`, `/scan dry` first. Read the qualified list. Sanity check
   three firms by hand against their websites. Do this before you ever let the
   full command run against live data.
9. `/scan` for real, with `DRAFT_CAP_PER_RUN=2` for the first run only. Then
   read **both** drafts in Gmail end to end before Harp sends either, and
   before you raise the cap.

---

## What to check on the first real run, in order

1. Is the posting title in the email character-for-character what the board
   says? Open the URL.
2. Does the posting URL in the P.S. resolve to that posting?
3. Does `posting_count` match the number of genuinely distinct openings?
4. Is the AUM figure the firm's own disclosed number, not the internal
   haircut?
5. Zero referral language anywhere.
6. Does the deck's fit paragraph name the role they are actually hiring for?
7. Does the Telegram spend line match what the provider dashboards say?
8. Did the run stop at DRAFT_CAP_PER_RUN, and did the parked remainder show up
   in the summary rather than vanishing? With no confirm gate this ceiling is
   the only thing between a bad classifier day and a Gmail drafts folder full
   of mail to the wrong firms.

If any of 1 through 5 is wrong, stop and fix before the next run. Those are the
claims that cost credibility, and a cold email that gets a fact wrong about the
recipient's own job posting is worse than no email.
