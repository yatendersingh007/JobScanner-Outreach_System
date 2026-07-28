"""Telegram notification side for Workflow D.

NEW bot, not Workflow C's @Manpconnections_bot (BRIEF 6.4): that bot's
defaulted replies route to Harpreet and its command namespace is C's. Sharing
it would cross two workflows' notification streams in one thread.

This module is the OUTBOUND half only: send, split, live-edit progress. The
command surface (/scan, /scan pursue, /status d, /cancel) is build step 5 and
follows referral-system/src/telegram_bot.py's long-poll + allowlist pattern.

The allowlist check lives in the polling loop, not per command, exactly as it
does in Workflow C, so every future command inherits authorization for free.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from . import wd_config as config

log = logging.getLogger(__name__)

_TG_LIMIT = 3800
LIVE_STATUS_MIN_INTERVAL_SEC = 3

_last_live_edit = 0.0
_live_message_id: Optional[int] = None


def _api_base() -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN_D}"


def _split(text: str, limit: int = _TG_LIMIT) -> list[str]:
    """Split on line boundaries. A summary cut mid-line reads as truncated data."""
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur.rstrip("\n"))
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur.rstrip("\n"))
    return chunks


def send(text: str, chat_id: Optional[str] = None) -> None:
    """Fire and forget. A Telegram outage must never take down a run."""
    cid = chat_id or config.TELEGRAM_CHAT_ID
    if not config.TELEGRAM_BOT_TOKEN_D or not cid:
        log.info("TELEGRAM(no token/chat): %s", text)
        return
    for chunk in _split(text):
        try:
            requests.post(f"{_api_base()}/sendMessage", timeout=20,
                          json={"chat_id": cid, "text": chunk,
                                "disable_web_page_preview": True})
        except Exception as e:
            log.warning("Telegram send failed: %s", e)


def _send_and_get_id(text: str) -> Optional[int]:
    cid = config.TELEGRAM_CHAT_ID
    if not config.TELEGRAM_BOT_TOKEN_D or not cid:
        log.info("TELEGRAM(no token/chat): %s", text)
        return None
    try:
        r = requests.post(f"{_api_base()}/sendMessage", timeout=20,
                          json={"chat_id": cid, "text": text[:_TG_LIMIT],
                                "disable_web_page_preview": True})
        return r.json().get("result", {}).get("message_id")
    except Exception as e:
        log.warning("Telegram send failed: %s", e)
        return None


def _edit(message_id: int, text: str) -> bool:
    try:
        r = requests.post(f"{_api_base()}/editMessageText", timeout=20,
                          json={"chat_id": config.TELEGRAM_CHAT_ID,
                                "message_id": message_id,
                                "text": text[:_TG_LIMIT],
                                "disable_web_page_preview": True})
        return bool(r.json().get("ok"))
    except Exception as e:
        log.warning("Telegram edit failed: %s", e)
        return False


def progress(msg: str) -> None:
    """Live progress via message EDIT, rate limited.

    A 10-firm gate emits dozens of progress lines. Sending each one turns the
    thread into noise and hits Telegram's rate limit; editing one message keeps
    it readable. Everything still goes to stderr, so journalctl has the full
    sequence even though Telegram only ever shows the latest line.
    """
    global _last_live_edit, _live_message_id
    log.info("%s", msg)
    now = time.time()
    if _live_message_id is None:
        _live_message_id = _send_and_get_id(msg)
        _last_live_edit = now
        return
    if now - _last_live_edit < LIVE_STATUS_MIN_INTERVAL_SEC:
        return
    if _edit(_live_message_id, msg):
        _last_live_edit = now


def reset_live() -> None:
    """Start a fresh live message. Call at the top of each run."""
    global _live_message_id, _last_live_edit
    _live_message_id, _last_live_edit = None, 0.0
