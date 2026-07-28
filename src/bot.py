"""Telegram bot: the only way a run starts, alongside src/cli.py -- both call
src.run_scan's run_scan()/run_single_firm()/run_resume(), the same functions,
never their own copy of the pipeline.

Follows referral-system/src/telegram_bot.py's structure (see BUILD_LOG.md's
Prompt 2 diagnose entry for the reuse/rewrite breakdown): the
AUTHORIZED_USER_IDS check happens IN THE POLLING LOOP, before _dispatch is
ever called, never inside a command handler, so every future command
inherits authorization for free and no command can forget it.

bot.py contains no business logic: it parses, authorizes, calls run_scan's
functions, and formats. A gate decision or a dedup rule belongs in the
pipeline, not here.
"""
from __future__ import annotations

import re
import threading
from typing import Optional

import requests

from lib_referral import config as gate_config
from . import wd_config as config, wd_dbc as dbc, wd_telegram as tg
from .run_scan import run_resume, run_scan, run_single_firm, summarize

_busy = threading.Lock()

# ---------------------------------------------------------------------------
# Parsing helpers. Independently reimplemented and empirically compared
# against referral-system/src/telegram_bot.py's _parse_quoted/_parse_aum --
# see BUILD_LOG.md's Prompt 2 build entry for the comparison table. One real
# divergence found and kept deliberately: this version closes a quote with
# the SAME quote character that opened it, so a firm name containing an
# apostrophe or a nested quote (e.g. "O'Brien Capital") parses correctly.
# The donor's version treats ANY quote character as a closer and would
# truncate that same name to "O".
# ---------------------------------------------------------------------------
_QUOTE_PAIRS = {'"': '"', "'": "'", "“": "”", "‘": "’"}

# Reserved /scan sub-words. A quoted "firm name" that is actually one of
# these is almost always a mis-typed option, not a real company -- refuse
# rather than silently research it or silently misparse the command.
_COMMAND_FRAGMENT_WORDS = {"dry", "stop", "days", "cancel", "confirm", "yes", "ok", "resume"}


def strip_quotes(s: str) -> str:
    s = (s or "").strip()
    while len(s) >= 2 and s[0] in _QUOTE_PAIRS and s[-1] == _QUOTE_PAIRS.get(s[0]):
        s = s[1:-1].strip()
    return s


def parse_quoted(arg: str) -> tuple[str, str]:
    """'"Firm" 800M' -> ('Firm', '800M'). Unquoted: only peel a trailing
    numeric-looking token; otherwise the whole string is the firm name.
    Closes on the SAME quote character that opened (see module docstring)."""
    s = (arg or "").strip()
    if not s:
        return "", ""
    opener = s[0]
    closer = _QUOTE_PAIRS.get(opener)
    if closer is not None:
        end = s.find(closer, 1)
        if end != -1:
            return s[1:end].strip(), s[end + 1:].strip()
        return s[1:].strip(), ""
    parts = s.rsplit(None, 1)
    if len(parts) == 2 and any(ch.isdigit() for ch in parts[1]):
        return parts[0].strip(), parts[1].strip()
    return s, ""


_AUM_RE = re.compile(r"([\d.,]+)\s*(billion|bn|b|million|mm|m)?", re.IGNORECASE)


def parse_aum(raw: str) -> Optional[float]:
    raw = (raw or "").strip().replace("$", "").replace(",", "")
    if not raw:
        return None
    m = _AUM_RE.match(raw)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    if unit in ("billion", "bn", "b"):
        return value * 1_000_000_000
    if unit in ("million", "mm", "m"):
        return value * 1_000_000
    return value


def human_usd(n: float) -> str:
    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.0f}M"
    return f"${n:,.0f}"


def _looks_like_command_fragment(name: str) -> bool:
    return (name or "").strip().lower() in _COMMAND_FRAGMENT_WORDS


# ---------------------------------------------------------------------------
# /scan argument parsing
# ---------------------------------------------------------------------------
def parse_scan_args(arg: str) -> dict:
    """Parses the text after '/scan'. Returns {"firm", "dry", "days", "stop"}.
    Raises ValueError (the caller sends the message) on anything unrecognized
    -- reject rather than guess at what an operator meant."""
    text = (arg or "").strip()
    if not text:
        return {"firm": None, "dry": False, "days": None, "stop": False}
    if text.lower() == "stop":
        return {"firm": None, "dry": False, "days": None, "stop": True}

    if text[0] in _QUOTE_PAIRS:
        firm, rest = parse_quoted(text)
        if _looks_like_command_fragment(firm):
            raise ValueError(
                f'"{firm}" looks like a leftover /scan option, not a firm name. '
                'Nothing started. Use /scan, /scan dry, /scan days N, or /scan "Firm Name".'
            )
        rest = rest.strip()
        dry = rest.lower() == "dry"
        if rest and not dry:
            raise ValueError(f'Unrecognized text after the firm name: "{rest}".')
        return {"firm": firm, "dry": dry, "days": None, "stop": False}

    words = text.split()
    dry = False
    days = None
    leftover = []
    i = 0
    while i < len(words):
        w = words[i].lower()
        if w == "dry":
            dry = True
            i += 1
        elif w == "days" and i + 1 < len(words) and words[i + 1].isdigit():
            days = int(words[i + 1])
            i += 2
        else:
            leftover.append(words[i])
            i += 1
    if leftover:
        candidate = " ".join(leftover)
        raise ValueError(
            f'Unrecognized /scan argument: "{candidate}". A firm name needs quotes: '
            f'/scan "{candidate}". Otherwise use /scan, /scan dry, or /scan days N.'
        )
    return {"firm": None, "dry": dry, "days": days, "stop": False}


# ---------------------------------------------------------------------------
# /scan and /resume: long-running, so each spawns a background thread and
# holds _busy for its duration. Every other command is fast enough to run
# synchronously inside _dispatch, exactly as referral-system does it.
# ---------------------------------------------------------------------------
def _run_scan_job(parsed: dict) -> None:
    try:
        tg.reset_live()
        firm = parsed.get("firm")
        dry = parsed.get("dry", False)
        try:
            if firm:
                tg.send(f'Single-firm run started: "{firm}" (scanner skipped).')
                result = run_single_firm(mode="manual", firm_name=firm, dry=dry,
                                         progress=tg.progress)
            else:
                tg.send("Workflow D run started.")
                result = run_scan(mode="manual", days=parsed.get("days"), dry=dry,
                                  progress=tg.progress)
        except ValueError as e:
            tg.send(f"Could not start: {e}")
            return
        except Exception as e:  # noqa: BLE001
            tg.finish("crashed")
            tg.send(f"Workflow D run CRASHED: {type(e).__name__}: {e}")
            return

        # Prompt 2 step 2a: post the draft/spend INTENT right after gating,
        # before any attempt to draft. Information, not a question -- there
        # is no confirm gate. /cancel is there if the number looks wrong;
        # DRAFT_CAP_PER_RUN stops it regardless.
        if not dry and result.qualified:
            n_q = len(result.qualified)
            n_draft = min(n_q, config.DRAFT_CAP_PER_RUN)
            n_over = max(0, n_q - config.DRAFT_CAP_PER_RUN)
            over_note = f", {n_over} over cap and parked for /resume" if n_over else ""
            tg.send(
                f"{n_q} qualified. {n_draft} would be drafted "
                f"(DRAFT_CAP_PER_RUN={config.DRAFT_CAP_PER_RUN}){over_note}. "
                "Drafting is not built yet (prompts 3-4), so this run stops after "
                "gating. /cancel would have stopped it here if this number looked wrong."
            )

        tg.finish("cancelled" if result.cancelled else "done")
        tg.send(summarize(result, dry_hint="/scan dry"))
    finally:
        _busy.release()


def _handle_scan(arg: str) -> None:
    try:
        parsed = parse_scan_args(arg)
    except ValueError as e:
        tg.send(str(e))
        return
    if parsed["stop"]:
        _handle_cancel()
        return
    if not _busy.acquire(blocking=False):
        tg.send("A run is already in progress. /cancel it first, or wait for it to finish.")
        return
    threading.Thread(target=_run_scan_job, args=(parsed,), daemon=True).start()


def _resume_job() -> None:
    try:
        tg.reset_live()
        tg.send("Resuming the latest crashed or cancelled run...")
        try:
            result = run_resume(progress=tg.progress)
        except Exception as e:  # noqa: BLE001
            tg.finish("crashed")
            tg.send(f"Resume failed: {type(e).__name__}: {e}")
            return
        if result is None:
            tg.send("Nothing to resume. No crashed or cancelled run on record.")
            return
        tg.finish("cancelled" if result.cancelled else "done")
        tg.send(summarize(result, dry_hint="/scan dry"))
    finally:
        _busy.release()


def _handle_resume() -> None:
    if not _busy.acquire(blocking=False):
        tg.send("A run is already in progress.")
        return
    threading.Thread(target=_resume_job, daemon=True).start()


# ---------------------------------------------------------------------------
# Fast commands: run synchronously in _dispatch, no thread, no _busy.
# ---------------------------------------------------------------------------
def _handle_cancel() -> None:
    """Authorization: inherited for free -- every command reaches _dispatch
    only after run_bot()'s polling loop has already filtered senders against
    AUTHORIZED_USER_IDS, so no separate check is needed here (same as
    referral-system's _handle_cancel)."""
    run = dbc.latest_running_run()
    if not run:
        tg.send("No run in progress to cancel.")
        return
    dbc.request_run_cancellation(run["id"])
    tg.send(
        f"Cancellation requested for run #{run['id']}. Finishing the firm "
        "currently in progress, then stopping. /resume will continue from where it stops."
    )


def _handle_qualify(arg: str) -> None:
    firm, aum_raw = parse_quoted(arg)
    if not firm:
        tg.send('Usage: /qualify "<Firm>" <AUM>   e.g. /qualify "Aliya Capital Partners" 800M')
        return
    aum = parse_aum(aum_raw)
    if aum is None:
        tg.send(f'Could not read an AUM from "{aum_raw or "(nothing given)"}". Try 800M, 1.2B, or $500M.')
        return
    row = dbc.parked_firm_by_name(firm)
    if not row:
        tg.send(f'No PARKED firm named "{firm}" on record. /qualify only rescues parked firms.')
        return
    in_band = gate_config.AUM_MIN_USD <= aum <= gate_config.AUM_MAX_USD
    if not in_band:
        tg.send(
            f'{human_usd(aum)} is outside the ${gate_config.AUM_MIN_USD / 1e6:.0f}M-'
            f'${gate_config.AUM_MAX_USD / 1e9:.1f}B band. Still DISQUALIFIED. Nothing changed.'
        )
        return
    dbc.update_wd_firm(
        row["id"], icp_status="qualified",
        icp_reason=f"QUALIFIED (operator-verified AUM {human_usd(aum)})",
        aum_tag="AUM_CONFIRMED", park_reason=None, park_source=None,
    )
    tg.send(
        f'Qualified "{row["firm_name"]}" at {human_usd(aum)}. '
        "Drafting is not built yet (prompts 3-4); nothing else happens automatically."
    )


def _handle_disqualify(arg: str) -> None:
    firm, _rest = parse_quoted(arg)
    if not firm:
        tg.send('Usage: /disqualify "<Firm>"')
        return
    row = dbc.parked_firm_by_name(firm)
    if not row:
        tg.send(f'No PARKED firm named "{firm}" on record.')
        return
    dbc.update_wd_firm(row["id"], icp_status="disqualified",
                       icp_reason="Disqualified by operator override",
                       park_reason=None, park_source=None)
    tg.send(f'Disqualified "{row["firm_name"]}".')


def _handle_status() -> None:
    run = dbc.latest_wd_run()
    if not run:
        tg.send("No runs yet.")
        return
    firms = dbc.firms_for_run(run["id"])
    by_status: dict = {}
    for f in firms:
        by_status.setdefault(f.get("icp_status") or "unknown", []).append(f)
    queue = dbc.queue_counts(run["id"])
    lines = [
        f"Last run #{run['id']} ({run.get('mode', '?')}, {run.get('status', '?')})",
        f"Started: {run.get('started_at')}",
    ]
    if run.get("finished_at"):
        lines.append(f"Finished: {run['finished_at']}")
    lines += [
        "",
        f"Qualified: {len(by_status.get('qualified', []))}",
        f"Parked: {len(by_status.get('parked', []))}",
        f"Disqualified: {len(by_status.get('disqualified', []))}",
        "",
        f"Queue: {queue.get('pending', 0)} pending, {queue.get('done', 0)} done",
        "",
        f"Spend: {run.get('tavily_searches', 0)} Tavily searches, "
        f"{run.get('llm_tokens', 0)} LLM tokens, "
        f"${float(run.get('research_cost_usd') or 0):.2f} research",
    ]
    tg.send("\n".join(lines))


def _help_text() -> str:
    return (
        "Workflow D bot.\n\n"
        "/scan                  - full run: scan, gate, draft. Drafting is not "
        "built yet, so this stops after gating for now.\n"
        "/scan dry              - stop after gating. No Apollo calls, no drafts. "
        "The opt-out, not the default.\n"
        f"/scan days N           - catch-up window after a gap (1-{config.MAX_SCAN_DAYS}).\n"
        '/scan "Firm"           - single-firm override, skips the scanner entirely.\n'
        "/status                - last run's buckets, spend, queue depth.\n"
        '/qualify "Firm" <AUM>  - rescue a parked firm, e.g. /qualify "Acme" 800M\n'
        '/disqualify "Firm"     - reject a parked firm\n'
        "/cancel (or /scan stop) - stop the active run cleanly, after the "
        "in-flight firm finishes\n"
        "/resume                - continue the latest crashed or cancelled run\n"
        "/help\n"
    )


# ---------------------------------------------------------------------------
# Dispatch. Pure router: no authorization check here (see module docstring),
# no business logic (parses, authorizes-by-omission, calls, formats).
# ---------------------------------------------------------------------------
def _dispatch(text: str, chat_id: Optional[str] = None) -> None:
    """Testable without a live bot token. `chat_id` is accepted for
    structural parity with referral-system's router but unused: Workflow D
    is single-operator, and wd_telegram.send() already defaults to
    config.TELEGRAM_CHAT_ID."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return
    parts = text.split(maxsplit=1)
    cmd = parts[0].lstrip("/").split("@")[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "scan":
        _handle_scan(arg)
    elif cmd == "cancel":
        _handle_cancel()
    elif cmd == "resume":
        _handle_resume()
    elif cmd == "status":
        _handle_status()
    elif cmd == "qualify":
        _handle_qualify(arg)
    elif cmd == "disqualify":
        _handle_disqualify(arg)
    elif cmd in ("start", "help"):
        tg.send(_help_text())
    else:
        tg.send(f"Unknown command: {cmd}\n\n{_help_text()}")


def _dispatch_message(msg: dict) -> None:
    _dispatch(msg.get("text", ""))


# ---------------------------------------------------------------------------
# Real polling loop (not exercised by tests -- requires a live
# TELEGRAM_BOT_TOKEN_D). AUTHORIZED_USER_IDS is checked HERE, before
# _dispatch, never inside a handler.
# ---------------------------------------------------------------------------
def get_updates(offset: Optional[int], timeout: int = 30) -> list[dict]:
    r = requests.get(f"{tg._api_base()}/getUpdates", params={"offset": offset, "timeout": timeout},
                     timeout=timeout + 10)
    r.raise_for_status()
    return r.json().get("result", [])


def _process_updates(updates: list[dict], allowed: set[str]) -> Optional[int]:
    """The filter-then-dispatch step of the polling loop, factored out of
    run_bot() so it's testable without a live token or the infinite loop.
    AUTHORIZED_USER_IDS is checked HERE, before _dispatch is ever called --
    never inside a handler, so every command inherits authorization for
    free. Returns the next offset (or None if `updates` was empty)."""
    next_offset = None
    for upd in updates:
        next_offset = upd["update_id"] + 1
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue
        sender = str(msg.get("from", {}).get("id"))
        if sender not in allowed:
            continue
        if msg.get("text"):
            try:
                _dispatch_message(msg)
            except Exception as e:  # noqa: BLE001
                tg.send(f"Error handling command: {e}")
    return next_offset


def run_bot() -> None:
    if not config.TELEGRAM_BOT_TOKEN_D:
        raise SystemExit("Refusing to start: TELEGRAM_BOT_TOKEN_D is empty in .env")
    if not config.AUTHORIZED_USER_IDS:
        raise SystemExit("Refusing to start: AUTHORIZED_USER_IDS is empty in .env")

    allowed = set(config.AUTHORIZED_USER_IDS)
    offset: Optional[int] = None
    backlog = get_updates(None, timeout=0)
    if backlog:
        offset = backlog[-1]["update_id"] + 1
    tg.send("Workflow D bot online.\n\n" + _help_text())

    while True:
        next_offset = _process_updates(get_updates(offset), allowed)
        if next_offset is not None:
            offset = next_offset


if __name__ == "__main__":
    run_bot()
