# CLAUDE.md — workflow-d

Read this before touching anything. These rules come from 38 numbered fixes in
the sibling referral-system project. They are not preferences.

## What this project is

Workflow D turns a job posting into a reviewed Gmail draft.

manual `/scan` from Telegram -> Job Scanner (North America, last 24h, target
titles) -> classifier keeps Real Estate / Family Office -> group by company ->
verdict-cache check -> binary ICP gate on new companies only -> Apollo senior
finance POC -> personalized cold email + customized pitch deck PDF -> Gmail
DRAFT in Harpreet's account -> Telegram notifies at every stage.

A job posting is a buying signal. A CRE firm or family office hiring a fund
accountant, property accountant or controller has that capacity gap today, and
X Analyst sells the alternative to that hire: embedded senior offshore finance
professionals, $145K-$180K US fully loaded versus $55K-$75K.

## Hard rules

1. **NEVER send email.** `drafts().create()` only. No code path anywhere calls
   `.send()`. Harpreet reviews and sends by hand. Grep-verify this claim
   before asserting it.
2. **No automatic firing.** There is no systemd timer and there will not be
   one. Runs start from a Telegram command, always. Holidays are a human
   choice. Do not add a scheduler, a cron entry, or an APScheduler job.
3. **Cross-workflow dedup is ADVISORY, never blocking** (FIX 38). Check
   `contacted_pocs` across Workflows A, C and D before drafting. On a hit,
   draft anyway and flag loudly: "previously drafted via Workflow C on
   <date>, check sent mail before sending." Within a single run, a repeat
   person still BLOCKS. Two different guarantees, not one.
4. **Fact grounding on every LLM-drafted claim** via `fact_check.py`. A
   dropped or retried block is logged with stage and reason, never silently.
   Per-run aggregate counts go in the Telegram summary.
5. **Guards fail toward honesty.** An honest blank or a logged park beats a
   fabricated or mismatched sentence. Never pad. Never patch a flagged
   sentence in place: a hand-edited sentence reads as mutilated. Replace the
   whole block with its fallback.
6. **No pytest on the VM, ever.** Patchright stays off the VM. Tests run on
   the local machine only. VM verification is realmode smoke scripts and
   TEST_MODE.
7. **Secrets never in git.** `.env`, `token.json`, `credentials.json`,
   `seen.db`, `poc_cache.db`, scanned lead data, `connections.csv`.
8. **Diagnose before fixing.** Every fix starts print-only and STOPS if
   evidence contradicts the premise. Never assert a bug is confirmed before
   reproducing it in the environment that failed. Never compare artifacts
   from different runs without checking timestamps.
9. **Adversarial review passes are READ-ONLY.** No edits while a test run is
   in flight. Keep the full suite green. Report count and delta every time.
10. **Budget guards on by default.** `GATE_CAP_PER_RUN`,
    `MAX_LLM_TOKENS_PER_FIRM`, `TINYFISH_STEP_CAP_PER_RUN`, Tavily pool
    rotation, JSearch quota awareness. Every run reports what it spent.

## Style for all human-facing output

Emails, deck text, Telegram messages, docs, commit messages.

- No em dashes. Harp flags them as an AI tell. Use commas, periods, or rewrite.
- No hedging. No "it's worth noting", no "I hope this finds you well".
- Direct sentences. Vary length.
- Banned words in generated email or deck content: leverage, optimize,
  streamline, synergy, unlock, empower, crucial, pivotal, vital, robust,
  comprehensive, holistic, innovative, cutting-edge, enhance, foster,
  cultivate, showcase, underscore, delve, navigate, spearhead, bolster,
  garner, resonate, seamless, transformative, groundbreaking, bespoke,
  tailored, scalable.
- Banned phrases: "I noticed", "I came across", "I was impressed", "exciting
  opportunity", "I wanted to reach out", "at the intersection of", "when it
  comes to", "in today's market", "not just X, it's Y".

## Vendored code

`lib_referral/` is vendored from referral-system. Every file carries a
provenance header: source path, source commit hash, date copied. `DRIFT.md`
lists them all.

**Never edit a vendored file to fix a bug without also filing the fix against
the donor repo.** referral-system's own `lib_snapshot/` already drifted from
outreach-system and reconciling it is still open. Do not create a third
unsynced fork casually.

The gate (`lib_referral/icp_gate.py`) is vendored unchanged. Its own-domain
resolution parks on ambiguous identity signals (FIX 28: the gate once
attributed Kairos Investment Management's $2.4B to Kairos Real Estate
Partners). Do not weaken it.

## Known landmines

- **The LLM invents the service offering** if the prompt does not state what
  X Analyst sells (FIX 29: it pitched PropTech). Every drafting prompt states
  the offering explicitly, from a fixed list.
- **gpt-5-mini reasoning-budget exhaustion** returns sparse-but-valid JSON
  that no retry catches (FIX 15). Use `reasoning_effort="minimal"` on
  extraction calls. Log `finish_reason` and `reasoning_tokens`.
- **`ensure_ascii=True` in `json.dumps` corrupts grounding** (FIX 37C: an en
  dash escaped to `\u2013` and its hex digits fused with adjacent numbers into
  phantom tokens). The vendored `fact_check.py` has `ensure_ascii=False`. Keep it.
- **Greenhouse has no reliable posted date.** First-seen anchoring handles it.
  Do not "fix" recency by trusting `updated_at`.
- **Phase 2 research variance.** The same firm can gate differently across
  runs (American Real Estate Partners: $63M then $309M on consecutive days).
  Verdict caching is the mitigation. Gate once, reuse. Near-boundary firms
  ($200M and $2B) are the risk zone.
- **`dedup_key` is namespaced per source.** `scanner/models.py` returns
  `f"{source}:{...}"`, so one real posting found by JSearch and by the
  TinyFish LinkedIn guest search survives dedup twice. `posting_count` must
  dedup on normalized title, because that number goes into the email.
- **The scanner's staffing blocklist filters nothing.** It lives under
  `poc_enrichment` in `config.yaml` and only `poc_enricher` reads it.
  Workflow D applies it as a hard drop before the gate.
- **`firm_key` must not strip descriptive words.** Stripping "group" and
  "management" collapsed Standish Management and Standish Group to one key.
  Only true legal forms strip (llc, inc, lp, ltd). A wrong cached verdict is
  worse than gating a near-duplicate name twice.
- **LinkedIn boundary.** TinyFish targets are GUEST-search public URLs only,
  never authenticated LinkedIn. Patchright (account-level automation) stays
  off the VM. Do not conflate the two.
- **The recency grace window is one-shot per posting.** `scanner/pipeline.py`
  checks `store.is_new(key)` and then unconditionally calls
  `store.first_seen(key, today)` — which writes the key into `seen.db` right
  then, before the recency filter decides to keep or drop the posting. So a
  posting dropped on its first sighting is still permanently marked "seen" as
  of that run's date. The automatic grace bump (`max(recency_days,
  first_seen_grace_days)`) only ever applies while `newly_seen` is `True`,
  which is exactly once per key. Recovering a dropped posting on a later run
  requires the operator to explicitly pass a wider `--days` for that specific
  run; it never happens automatically again. **After a gap, the catch-up run
  must come FIRST** — a normal `--days 1` run after a holiday, done before the
  intentional catch-up run, permanently burns the one-shot grace window on
  every posting it sees.
- **`systemctl edit` can silently discard drop-ins.** Write `override.conf`
  via `tee`, verify with `systemctl show`.

## Environment

- Local: Windows, VS Code, Python venv. Tests run here.
- VM: Azure Ubuntu 24 at 172.174.154.60, user `azureuser`, service user
  `outreach`. Already runs `outreach-bot` (A) and `referral-bot` (C) as
  systemd units, shared Postgres db `outreach`, LibreOffice for PPTX->PDF,
  five-key Tavily pool.
- Deploy: local zip -> scp -> unzip -> rsync (no `--delete`, it preserves
  `.env`/`token.json`/`.venv`) -> `grep -c` marker check -> restart.
  robocopy/zip exclude list: `.venv`, `node_modules`, `__pycache__`, `.git`,
  `qa_out`, `output/`.

## Commands

```bash
pytest tests/ -q                       # local only, never on the VM
python -c "from src import wd_dbc; wd_dbc.apply_migrations()"   # idempotent
python -m src.cli scan                 # full pipeline: scan, gate, draft (default)
python -m src.cli scan --dry           # stop after gating, no Apollo/Gmail spend
python -m src.cli scan --days N        # catch-up window after a gap (default 1, max 14)
python -m src.bot                      # long-poll Telegram bot (prompt 2)
```
