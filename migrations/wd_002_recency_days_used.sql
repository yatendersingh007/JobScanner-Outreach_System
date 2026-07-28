-- Workflow D — Prompt 1: manual trigger + explicit catch-up window.
-- Additive and idempotent, per referral-system's migrations/ pattern.
-- Records the actual recency_days override applied for each run, so a
-- catch-up run (--days N > 1) is visible after the fact, not just in the
-- Telegram summary at the time.

ALTER TABLE wd_runs ADD COLUMN IF NOT EXISTS recency_days_used INTEGER NOT NULL DEFAULT 1;
