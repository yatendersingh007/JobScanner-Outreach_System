-- Workflow D (signal-driven outreach) schema.
-- Additive and idempotent, per referral-system's migrations/ pattern.
-- Shares the `outreach` database with Workflows A and C so contacted_pocs
-- stays cross-workflow visible (BRIEF 3.4, HARD RULE 2).

CREATE TABLE IF NOT EXISTS wd_runs (
    id                   SERIAL PRIMARY KEY,
    mode                 TEXT NOT NULL,              -- scheduled | manual | pursue | single | resume
    started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at          TIMESTAMPTZ,
    status               TEXT NOT NULL DEFAULT 'running',  -- running|done|cancelled|crashed
    cancel_requested_at  TIMESTAMPTZ,
    postings_raw         INTEGER DEFAULT 0,
    postings_kept        INTEGER DEFAULT 0,
    companies_grouped    INTEGER DEFAULT 0,
    companies_gated      INTEGER DEFAULT 0,
    csv_path             TEXT,
    -- spend telemetry, reported in every Telegram summary (HARD RULE 10)
    jsearch_calls        INTEGER DEFAULT 0,
    tinyfish_steps       INTEGER DEFAULT 0,
    tavily_searches      INTEGER DEFAULT 0,
    llm_tokens           INTEGER DEFAULT 0,
    research_cost_usd    NUMERIC(10,4) DEFAULT 0,
    notes                TEXT
);

CREATE TABLE IF NOT EXISTS wd_firms (
    id                SERIAL PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES wd_runs(id),
    firm_name         TEXT NOT NULL,
    firm_key          TEXT NOT NULL,          -- normalized name, the grouping/cache key
    category          TEXT,                   -- Real Estate | Family Office
    subcategory       TEXT,
    posting_count     INTEGER DEFAULT 0,      -- distinct (title) count, an email hook
    icp_status        TEXT,                   -- qualified|disqualified|parked|skipped_known
    icp_reason        TEXT,
    aum_tag           TEXT,                   -- AUM_CONFIRMED|AUM_ESTIMATED|AUM_UNVERIFIED
    park_reason       TEXT,
    park_source       TEXT,                   -- research|infrastructure|match
    confidence        NUMERIC(4,3),
    source_count      INTEGER,
    research          JSONB,                  -- GateResult.research verbatim
    verdict_source    TEXT,                   -- gated | cached_wd | cached_wc
    verdict_cached_from INTEGER,              -- source row id when reused
    gated_at          TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS wd_firms_key_idx    ON wd_firms (firm_key);
CREATE INDEX IF NOT EXISTS wd_firms_status_idx ON wd_firms (icp_status);
CREATE INDEX IF NOT EXISTS wd_firms_run_idx    ON wd_firms (run_id);

CREATE TABLE IF NOT EXISTS wd_postings (
    id                 SERIAL PRIMARY KEY,
    run_id             INTEGER NOT NULL REFERENCES wd_runs(id),
    firm_id            INTEGER REFERENCES wd_firms(id),
    company            TEXT NOT NULL,
    title              TEXT NOT NULL,
    url                TEXT,
    source             TEXT,
    dedup_key          TEXT,
    category           TEXT,
    subcategory        TEXT,
    region             TEXT,
    location           TEXT,
    posted_date        DATE,
    first_seen         DATE,
    days_since_posted  INTEGER,
    match_reason       TEXT,
    poc_name_hint      TEXT,                  -- scanner TinyFish poc_enricher, hint only
    poc_designation_hint TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS wd_postings_firm_idx ON wd_postings (firm_id);
CREATE INDEX IF NOT EXISTS wd_postings_run_idx  ON wd_postings (run_id);

CREATE TABLE IF NOT EXISTS wd_drafts (
    id                SERIAL PRIMARY KEY,
    firm_id           INTEGER NOT NULL REFERENCES wd_firms(id),
    poc_name          TEXT,
    poc_email         TEXT,
    poc_title         TEXT,
    poc_linkedin_url  TEXT,
    poc_source        TEXT,                   -- apollo | scanner_hint | manual
    subject           TEXT,
    body              TEXT,
    word_count        INTEGER,
    thin_personalization BOOLEAN DEFAULT false,
    gmail_draft_id    TEXT,
    deck_pdf_path     TEXT,
    deck_attached     BOOLEAN DEFAULT false,
    -- HARD RULE 2: advisory, never blocking (FIX 38 lineage)
    collision_note    TEXT,
    prior_contact_workflow TEXT,
    prior_contact_at  TIMESTAMPTZ,
    fallback_stage    TEXT,                   -- which block fell back, and why
    fallback_reason   TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS wd_drafts_firm_idx ON wd_drafts (firm_id);

-- Queue, so /scan pursue and resume behave like Workflow C's batch drain.
CREATE TABLE IF NOT EXISTS wd_queue (
    id          SERIAL PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES wd_runs(id),
    firm_key    TEXT NOT NULL,
    firm_name   TEXT NOT NULL,
    firm_id     INTEGER REFERENCES wd_firms(id),
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending|done|skipped|paused|failed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS wd_queue_run_status_idx ON wd_queue (run_id, status);
