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

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from lib_referral import config as gate_config
from . import blocklist, wd_config as config, wd_dbc as dbc, wd_telegram as tg
from .run_scan import run_resume, run_scan, run_single_firm, summarize

log = logging.getLogger("workflow-d.bot")
# Fast in-process guard only: stops this ONE bot process from spawning a
# second background thread on top of its own already-running one (e.g. a
# double /scan before the first has finished). It cannot see src/cli.py, a
# separate process. The REAL cross-front-door guard is wd_dbc's Postgres
# advisory lock (acquire_run_lock/release_run_lock), taken inside
# run_scan()/run_single_firm()/run_resume() themselves -- _busy is a cheap
# early exit, not the safety property.
_busy = threading.Lock()
_POLL_ERROR_BACKOFF_SEC = 5

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
def _mark_interrupted() -> None:
    """Same gap as src/cli.py's own _mark_interrupted (see its docstring):
    signal_pipeline.run()'s inner crash handler only catches Exception, so a
    BaseException (KeyboardInterrupt/SystemExit) reaching this far leaves
    wd_runs stuck at status='running' even though the lock itself already
    released via that call's own finally. A real Ctrl+C lands on run_bot()'s
    main polling thread, not this background thread -- this mainly guards
    a SystemExit or a future direct call reaching _run_scan_job/_resume_job
    outside a thread. release_run_lock() is safe to call again regardless."""
    run = dbc.latest_running_run()
    if run:
        dbc.update_wd_run(run["id"], status="crashed",
                          finished_at=datetime.now(timezone.utc), notes="interrupted")
    dbc.release_run_lock()


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
        except dbc.RunAlreadyInProgress as e:
            # Not a crash: the Postgres advisory lock is held by another
            # process (the CLI, or another bot instance) -- _busy only ever
            # sees this same process, so this is the real cross-front-door
            # guard actually firing.
            tg.send(str(e))
            return
        except ValueError as e:
            tg.send(f"Could not start: {e}")
            return
        except Exception as e:  # noqa: BLE001
            tg.finish("crashed")
            tg.send(f"Workflow D run CRASHED: {type(e).__name__}: {e}")
            return
        except BaseException as e:
            _mark_interrupted()
            tg.finish("crashed")
            tg.send(f"Workflow D run interrupted: {type(e).__name__}. "
                    "Run marked crashed, lock released.")
            raise

        # Prompt 2 step 2a's spend/draft intent message and prompt 3's actual
        # drafting both happen INSIDE run_scan()/run_single_firm() now (Prompt
        # 3: run_scan._run_drafting), right after gating and before drafting
        # starts -- not here. bot.py only formats the final result.
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
        except dbc.RunAlreadyInProgress as e:
            tg.send(str(e))
            return
        except Exception as e:  # noqa: BLE001
            tg.finish("crashed")
            tg.send(f"Resume failed: {type(e).__name__}: {e}")
            return
        except BaseException as e:
            _mark_interrupted()
            tg.finish("crashed")
            tg.send(f"Resume interrupted: {type(e).__name__}. Run marked crashed, lock released.")
            raise
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
    # Input validation against the gate's own thresholds, not a gate verdict:
    # an operator override still has to fall inside the same $200M-$2B band
    # icp_gate.py itself enforces. Do not move this on principle.
    in_band = gate_config.AUM_MIN_USD <= aum <= gate_config.AUM_MAX_USD
    if not in_band:
        tg.send(
            f'{human_usd(aum)} is outside the ${gate_config.AUM_MIN_USD / 1e6:.0f}M-'
            f'${gate_config.AUM_MAX_USD / 1e9:.1f}B band. Still DISQUALIFIED. Nothing changed.'
        )
        return
    # The AUM figure must reach research in the same shape icp_gate.py itself
    # produces (aum_display/aum_value_usd/disclosed_figure/disclosed_label),
    # not just as free text in icp_reason -- deck_filler.build_fill_data()
    # reads disclosed_figure/disclosed_label to fill the deck's AUM stat
    # tile, and reads them from research, never from icp_reason. Reuses the
    # ALREADY-PARSED `aum` float from above, not a re-parse of icp_reason's
    # text. Preserves every other research field the original park already
    # gathered (domain, sources, geography, founded_year, ...) -- only the
    # AUM-related keys change, including the JSON's own nested "aum_tag"
    # (a real, live inconsistency confirmed on Neal Communities' actual row:
    # the wd_firms.aum_tag COLUMN said AUM_CONFIRMED while research["aum_tag"]
    # was still the original AUM_UNVERIFIED, never brought into agreement).
    disclosed_figure = human_usd(aum)
    disclosed_label = "assets under management"
    research = dict(row.get("research") or {})
    research.update({
        "aum_tag": "AUM_CONFIRMED",
        "aum_value_usd": aum,
        "disclosed_figure": disclosed_figure,
        "disclosed_label": disclosed_label,
        "aum_display": f"{disclosed_figure} ({disclosed_label})",
    })
    dbc.update_wd_firm(
        row["id"], icp_status="qualified",
        icp_reason=f"QUALIFIED (operator-verified AUM {human_usd(aum)})",
        aum_tag="AUM_CONFIRMED", park_reason=None, park_source=None,
        research=research,
    )
    tg.send(
        f'Qualified "{row["firm_name"]}" at {human_usd(aum)}. '
        "Nothing else happens automatically -- /resume drafts it on the next run."
    )


# ---------------------------------------------------------------------------
# Blocklist commands (run-34). The auto tier writes without asking; these are
# the operator's manual controls over the same file: accept a suggestion, undo
# anything (including an auto-add), and see what is in there.
# ---------------------------------------------------------------------------
def _handle_block(arg: str) -> None:
    firm, _rest = parse_quoted(arg)
    if not firm:
        tg.send('Usage: /block "<Firm>"')
        return
    run = dbc.latest_wd_run()
    run_id = run["id"] if run else "manual"
    try:
        entries = blocklist.add_entry(
            config.SCANNER_CONFIG_PATH, firm, f"added via /block, run {run_id}")
    except blocklist.BlocklistFileError as e:
        tg.send(f'Could not block "{firm}": {e}')
        return
    except Exception as e:  # noqa: BLE001
        tg.send(f'Could not block "{firm}" ({type(e).__name__}: {e}).')
        return
    tg.send(f'Blocked "{firm}". {len(entries)} entries now. It is dropped before '
            f'the gate from the next run on. /unblock "{firm}" to undo.')


def _handle_unblock(arg: str) -> None:
    firm, _rest = parse_quoted(arg)
    if not firm:
        tg.send('Usage: /unblock "<Firm>"')
        return
    try:
        entries = blocklist.remove_entry(config.SCANNER_CONFIG_PATH, firm)
    except blocklist.BlocklistFileError as e:
        tg.send(f'Could not unblock "{firm}": {e}')
        return
    except Exception as e:  # noqa: BLE001
        tg.send(f'Could not unblock "{firm}" ({type(e).__name__}: {e}).')
        return
    tg.send(f'Unblocked "{firm}". {len(entries)} entries now. It can be gated '
            "again from the next run on.")


def _handle_blocklist() -> None:
    try:
        entries = blocklist.read_entries(config.SCANNER_CONFIG_PATH)
    except Exception as e:  # noqa: BLE001
        tg.send(f"Could not read the blocklist ({type(e).__name__}: {e}).")
        return
    if not entries:
        tg.send("The blocklist is empty.")
        return
    tail = entries[-10:]
    lines = [f"Blocklist: {len(entries)} entries. Last {len(tail)}:"]
    lines += [f"  {e}" for e in tail]
    lines.append('/block "Name" to add, /unblock "Name" to remove.')
    tg.send(chr(10).join(lines))


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
        "/scan                  - full run: scan, gate, draft, Gmail drafts.\n"
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
        '/block "Firm"          - add Firm to the scanner blocklist\n'
        '/unblock "Firm"        - remove Firm from the blocklist\n'
        "/blocklist             - show the last 10 blocklist entries\n"
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
    elif cmd == "block":
        _handle_block(arg)
    elif cmd == "unblock":
        _handle_unblock(arg)
    elif cmd == "blocklist":
        _handle_blocklist()
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


def _poll_once(offset: Optional[int], allowed: set[str]) -> Optional[int]:
    """One iteration of the poll loop, factored out of run_bot() so the
    retry/backoff behavior is testable without a live token or the real
    infinite loop. On a transient network error, log it and back off briefly
    rather than retrying in a tight loop or letting the whole process die --
    returns the offset UNCHANGED so the next iteration re-fetches from where
    it left off."""
    try:
        updates = get_updates(offset)
    except requests.RequestException as e:
        log.warning("get_updates failed, retrying in %ss: %s", _POLL_ERROR_BACKOFF_SEC, e)
        time.sleep(_POLL_ERROR_BACKOFF_SEC)
        return offset
    next_offset = _process_updates(updates, allowed)
    return next_offset if next_offset is not None else offset


def _startup() -> tuple[Optional[int], set[str]]:
    """Everything run_bot() does before its first poll, factored out so the
    ordering is actually testable rather than just read off the source.
    workflow-d-bot.service has Restart=always: if the process died mid-run,
    the OLD run's wd_runs row is stuck at status='running' forever with no
    process behind it. Reconciling here, before anything else, means
    /cancel can never find and "successfully" cancel a dead run."""
    if not config.TELEGRAM_BOT_TOKEN_D:
        raise SystemExit("Refusing to start: TELEGRAM_BOT_TOKEN_D is empty in .env")
    if not config.AUTHORIZED_USER_IDS:
        raise SystemExit("Refusing to start: AUTHORIZED_USER_IDS is empty in .env")

    reconciled = dbc.reconcile_orphaned_runs()
    if reconciled:
        tg.send(f"Startup: reconciled {reconciled} orphaned run(s) stuck at "
                "'running' from a previous crash. Marked crashed.")

    allowed = set(config.AUTHORIZED_USER_IDS)
    offset: Optional[int] = None
    backlog = get_updates(None, timeout=0)
    if backlog:
        offset = backlog[-1]["update_id"] + 1
    tg.send("Workflow D bot online.\n\n" + _help_text())
    return offset, allowed


def run_bot() -> None:
    offset, allowed = _startup()
    while True:
        offset = _poll_once(offset, allowed)


if __name__ == "__main__":
    run_bot()
