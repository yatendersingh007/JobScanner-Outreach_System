# JobScanner Outreach System (Workflow D)

Turns a live job posting into a reviewed Gmail draft.

A commercial real estate firm or family office that is hiring a fund
accountant, property accountant or controller has a finance capacity gap
today. This pipeline finds those postings and prepares outreach for a human
to review.

## Pipeline

1. `/scan` from Telegram starts a run. Nothing runs on a schedule.
2. Job Scanner pulls North American postings from the last 24 hours for
   target finance titles.
3. A classifier keeps Real Estate and Family Office employers. Staffing
   agencies are dropped.
4. Postings are grouped by company. Companies with a cached ICP verdict
   reuse it.
5. New companies go through a binary ICP gate (AUM and geography).
6. Apollo finds a senior finance contact at each qualified company.
7. A personalized cold email and a custom pitch deck PDF are drafted. Every
   LLM-written claim is checked against the research by `fact_check.py`.
8. The result lands as a Gmail **draft**. Telegram reports each stage and
   what the run spent.

## Safety rules

- The code never sends email. It only calls `drafts().create()`. A person
  reads and sends every draft.
- A contact already drafted by another workflow is flagged, not blocked.
- Budget caps are on by default for gate calls, LLM tokens and scraper steps.

## Commands

```bash
pytest tests/ -q                  # local machine only
python -m src.cli scan            # scan, gate and draft
python -m src.cli scan --dry      # stop after gating, no Apollo or Gmail spend
python -m src.cli scan --days N   # catch-up window after a gap (max 14)
python -m src.bot                 # Telegram bot
```

Copy `.env.example` to `.env` and fill in your own keys. Never commit `.env`,
`token.json` or `credentials.json`.

See `CLAUDE.md` for the full rules and `DRIFT.md` for code vendored from
referral-system.
