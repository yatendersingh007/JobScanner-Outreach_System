-- wd_dbc.find_prior_contact()/record_contacted() (HARD RULE 3, cross-workflow
-- dedup) read and write contacted_pocs, but until now no wd_ migration
-- created it -- the table only existed because Workflow A or C's own
-- migrations (referral-system's migrations/002_workflow_c.sql) had already
-- run against the shared `outreach` database. A fresh database, or one
-- where Workflow D is migrated before A or C ever is, would fail at
-- drafting time with a bare "relation contacted_pocs does not exist".
--
-- CREATE TABLE IF NOT EXISTS makes this additive and idempotent against a
-- database where A/C's migration already created the table, same as every
-- other wd_ migration -- it does not re-create or alter anything that
-- exists.
--
-- Column-for-column identical to referral-system's own
-- migrations/002_workflow_c.sql (confirmed by reading it directly, printed
-- alongside this file in the same turn that added it). The only difference
-- is source_workflow's inline comment, updated from 'A' | 'C' to
-- 'A' | 'C' | 'D' since Workflow D writes here now too -- a comment, not a
-- column definition, so the schemas remain identical.
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
