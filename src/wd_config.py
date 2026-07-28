"""Workflow D configuration. Values from .env, defaults here.

Budget guards are ON by default (HARD RULE 10). An unattended 9 AM run must
have a hard ceiling on every metered service it can reach.
"""
from __future__ import annotations

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


ROOT = Path(__file__).resolve().parent.parent

TEST_MODE = _bool("TEST_MODE", True)          # default-safe: real mode is opt-in

# ── Scanner ───────────────────────────────────────────────────────────────
SCANNER_CONFIG_PATH = os.getenv("SCANNER_CONFIG_PATH", str(ROOT / "scanner" / "config.yaml"))

# Sources that normally produce. Zero from one of these gets a connector-health
# line in the summary (BRIEF 4.1): a board changing its markup thins TinyFish
# results silently, TinyFish itself still answers.
EXPECTED_SOURCES = [
    s.strip() for s in os.getenv(
        "EXPECTED_SOURCES",
        "jsearch,SelectLeaders,eFinancialCareers,LinkedIn US,LinkedIn Canada",
    ).split(",") if s.strip()
]

# ── Cost controls (BRIEF 4, open decision 11.2) ───────────────────────────
GATE_CAP_PER_RUN = _int("GATE_CAP_PER_RUN", 10)     # NEW companies gated per run
REGATE_WINDOW_DAYS = _int("REGATE_WINDOW_DAYS", 90)  # reuse a verdict this fresh
# Lower than GATE_CAP_PER_RUN on purpose (Prompt 1): scan drafts by default now,
# with no human confirm between gating and drafting, so this cap IS the guard.
# Exceeding it parks the remainder in the queue for /resume; it never silently
# truncates and never drafts past the ceiling.
DRAFT_CAP_PER_RUN = _int("DRAFT_CAP_PER_RUN", 5)
TINYFISH_STEP_CAP_PER_RUN = _int("TINYFISH_STEP_CAP_PER_RUN", 200)
MAX_LLM_TOKENS_PER_FIRM = _int("MAX_LLM_TOKENS_PER_FIRM", 25000)

# ── Manual trigger + catch-up window (Prompt 1) ───────────────────────────
# No timer, ever (HARD RULE 2). Every run starts from a human command, so a
# gap between runs (a holiday, a skipped day) is real and must be an explicit,
# bounded choice, not silently absorbed or silently ignored.
DEFAULT_SCAN_DAYS = _int("DEFAULT_SCAN_DAYS", 1)
MAX_SCAN_DAYS = _int("MAX_SCAN_DAYS", 14)

# ── Drafting ──────────────────────────────────────────────────────────────
EMAIL_MAX_WORDS = _int("EMAIL_MAX_WORDS", 260)
SIGNAL_TEMPLATE_PATH = os.getenv(
    "SIGNAL_TEMPLATE_PATH", str(ROOT / "templates" / "signal_email.md")
)
# HARD RULE 1. There is no send path anywhere in this codebase. This flag
# exists so preflight can assert it and so the value is greppable, not so it
# can be flipped.
NEVER_SEND = True

# Section 11.1 is still open (senior POC only vs POC + hiring manager). Built
# single-recipient; this is the extension point, deliberately not implemented.
SECOND_RECIPIENT_ENABLED = _bool("SECOND_RECIPIENT_ENABLED", False)

# ── Telegram (new bot, NOT Workflow C's @Manpconnections_bot) ─────────────
TELEGRAM_BOT_TOKEN_D = os.getenv("TELEGRAM_BOT_TOKEN_D", "")
AUTHORIZED_USER_IDS = [
    u.strip() for u in os.getenv("AUTHORIZED_USER_IDS", "").split(",") if u.strip()
]
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

GENERATED_DECKS_DIR = Path(os.getenv("GENERATED_DECKS_DIR", str(ROOT / "output" / "decks")))
