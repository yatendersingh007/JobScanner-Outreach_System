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
import threading
import time
from typing import Optional

import requests

from . import wd_config as config

log = logging.getLogger(__name__)

_TG_LIMIT = 3800
LIVE_STATUS_MIN_INTERVAL_SEC = 3
_STOPPED_LABEL = {"done": "Done.", "cancelled": "Cancelled.", "crashed": "Crashed."}

_last_live_edit = 0.0
_live_message_id: Optional[int] = None
_last_sent_text: Optional[str] = None


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


def _dispatch_edit(message_id: int, text: str) -> None:
    """Runs _edit on a background daemon thread.

    FIX (this bug was ours, not a donor issue -- see referral-system's FIX 25
    adversarial review, ported here): progress() is called directly and
    synchronously from inside the pipeline's per-firm loop. Before this fix,
    _edit()'s HTTP call ran on that SAME thread, so a slow-but-eventually-200
    editMessageText response (not just an outright failure) blocked the
    actual pipeline run for however long that call took. Dispatching here
    keeps the HTTP work off that thread entirely."""
    threading.Thread(target=_edit, args=(message_id, text), daemon=True).start()


def progress(msg: str) -> None:
    """Live progress via message EDIT, rate limited.

    A 10-firm gate emits dozens of progress lines. Sending each one turns the
    thread into noise and hits Telegram's rate limit; editing one message keeps
    it readable. Everything still goes to stderr, so journalctl has the full
    sequence even though Telegram only ever shows the latest line.

    The throttle timestamp and the dedup text are claimed SYNCHRONOUSLY and
    UNCONDITIONALLY here, before the HTTP attempt even starts -- not inside a
    "did it succeed" branch (that was the bug: it only advanced on a
    successful edit, so a sustained failure/rate-limit streak retried on
    every single call with no backoff at all, competing for the same
    rate-limit budget as the failures themselves).
    """
    global _last_live_edit, _live_message_id, _last_sent_text
    log.info("%s", msg)
    if _live_message_id is None:
        _live_message_id = _send_and_get_id(msg)
        _last_live_edit = time.time()
        _last_sent_text = msg
        return
    now = time.time()
    if now - _last_live_edit < LIVE_STATUS_MIN_INTERVAL_SEC:
        return
    if msg == _last_sent_text:
        return
    _last_live_edit = now
    _last_sent_text = msg
    _dispatch_edit(_live_message_id, msg)


def finish(reason: str) -> None:
    """Terminal state: force the live message to read Done./Cancelled./Crashed.
    instead of staying frozen on whatever progress() line was last sent on
    every exit path (cancellation, crash, or plain successful completion).
    Bypasses the throttle window deliberately -- a run only finishes once --
    but still dispatches on a background thread, same as progress().
    No-op if no live message was ever started (e.g. no token/chat configured).
    """
    global _last_live_edit, _last_sent_text
    if _live_message_id is None:
        return
    label = _STOPPED_LABEL.get(reason, f"Stopped: {reason}")
    log.info("%s", label)
    _last_live_edit = time.time()
    _last_sent_text = label
    _dispatch_edit(_live_message_id, label)


def reset_live() -> None:
    """Start a fresh live message. Call at the top of each run."""
    global _live_message_id, _last_live_edit, _last_sent_text
    _live_message_id, _last_live_edit, _last_sent_text = None, 0.0, None
