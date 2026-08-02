"""Workflow D Postgres helpers.

Mirrors referral-system/src/dbc.py exactly in style and in what it refuses to
do: reuses lib_snapshot.db's schema-agnostic connection pool, never calls
init_db()/reset_db() (reset_db DROPs every table in the shared `outreach`
database), and applies schema only through lib_snapshot.db.migrate().

The one function here that reads across workflows is verdict_cache_lookup:
it checks wd_firms AND wc_firms, because a firm Workflow C already gated is a
firm Workflow D must not pay to gate again (BRIEF 4.4, the biggest cost lever).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from lib_snapshot import db as shared_db

log = logging.getLogger("workflow-d.wd_dbc")

conn = shared_db.conn
cursor = shared_db.cursor


def apply_migrations() -> None:
    shared_db.migrate()


def _jsonb(value: Any) -> Any:
    return shared_db._jsonb(value)


# ---------------------------------------------------------------------------
# Single-run lock. src/cli.py and src/bot.py are two front doors into the
# same Postgres and the same seen.db -- bot.py's _busy is an in-process
# threading.Lock, so it cannot see a concurrent CLI process, and both could
# gate (and spend Tavily/Apollo) at once. wd_runs.status is not proof of
# liveness either: a crashed process leaves a 'running' row behind forever.
# A session-scoped Postgres advisory lock covers both front doors with one
# mechanism, and dies with the connection -- hence with the process -- the
# instant it crashes, which a status column can never do.
# ---------------------------------------------------------------------------
class RunAlreadyInProgress(RuntimeError):
    """Another process (CLI or bot) already holds the run lock. Raised
    instead of a bare ValueError so each front door can word this for its
    own surface."""


_RUN_LOCK_KEY = 872346591  # arbitrary fixed bigint, unique to this one lock
_run_lock_conn = None  # the connection THIS process is holding the lock on, if any


def acquire_run_lock() -> bool:
    """Try to acquire workflow-d's single-run advisory lock. Returns True if
    acquired (or already held by this same process), False if another
    session holds it.

    Deliberately session-scoped (pg_try_advisory_lock), not transaction-
    scoped: it must stay held across every dbc call for the whole run, and
    it must release itself the moment the holding connection dies -- which
    is exactly what happens when the process that opened it dies, crash or
    not. That is the property a status column cannot offer.

    Holds ONE connection checked out directly from the pool via getconn()
    (not the usual conn()/cursor() context managers, which return the
    connection to the pool the instant their `with` block exits) for as
    long as the lock is held. This is required, not a style choice: a
    session advisory lock is tied to the physical backend session, and a
    pooled connection returned to the pool between calls can be handed to a
    completely different caller before the run is done -- the lock has to
    live on a connection this module keeps for itself until
    release_run_lock() runs.
    """
    global _run_lock_conn
    if _run_lock_conn is not None:
        return True  # this process already holds it
    pool = shared_db.get_pool()
    c = pool.getconn()
    try:
        with c.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (_RUN_LOCK_KEY,))
            acquired = cur.fetchone()["acquired"]
        c.commit()
    except Exception:
        pool.putconn(c)
        raise
    if not acquired:
        pool.putconn(c)
        return False
    _run_lock_conn = c
    return True


def release_run_lock() -> None:
    """Release the run lock this process holds, if any. Safe to call even
    when nothing was ever acquired."""
    global _run_lock_conn
    if _run_lock_conn is None:
        return
    c = _run_lock_conn
    _run_lock_conn = None
    pool = shared_db.get_pool()
    try:
        with c.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_RUN_LOCK_KEY,))
        c.commit()
    finally:
        pool.putconn(c)


# ---------------------------------------------------------------------------
# firm_key — the grouping and cache key
# ---------------------------------------------------------------------------
# ONLY true legal forms are stripped. Descriptive business words (group,
# holdings, partners, management, capital, advisors, properties) are NOT:
# they are the only thing distinguishing many real firms from each other.
# Found by test_firm_key_keeps_different_firms_apart — stripping "management"
# and "group" collapsed Standish Management and Standish Group to the same
# key, which is FIX 28's failure mode (a cached verdict reused on the wrong
# firm). Paying to gate the same firm twice is cheap. A wrong verdict is not.
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(llc|l\.l\.c|inc|incorporated|corp|corporation|co|company|"
    r"lp|l\.p|llp|l\.l\.p|ltd|limited|plc|pllc|pc|sa|nv|bv|gmbh|ag)\b",
    re.IGNORECASE,
)
_LEADING_THE_RE = re.compile(r"^the\s+", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^a-z0-9 ]+")
_WS_RE = re.compile(r"\s+")


def firm_key(name: str) -> str:
    """Normalized company identity for grouping and verdict caching.

    Deliberately conservative: lowercase, drop punctuation and true legal-form
    suffixes only, collapse whitespace. It does NOT fuzzy-match and it does NOT
    strip descriptive words like "Group", "Management", or "Partners".
    "Kairos Real Estate Partners" and "Kairos Investment Management" must stay
    two different keys — FIX 28's landmine (BRIEF 8) is exactly what happens
    when firm identity gets loose, and a cache hit on the wrong firm would
    reuse a wrong verdict silently, which is worse than paying to gate twice.
    """
    s = (name or "").strip().lower()
    s = _LEADING_THE_RE.sub("", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _LEGAL_SUFFIX_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s or (name or "").strip().lower()


# ---------------------------------------------------------------------------
# wd_runs
# ---------------------------------------------------------------------------
def create_wd_run(mode: str, recency_days_used: int = 1) -> dict:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO wd_runs (mode, recency_days_used) VALUES (%s, %s) RETURNING *",
                (mode, recency_days_used),
            )
            row = cur.fetchone()
        c.commit()
    return row


def update_wd_run(run_id: int, **fields) -> None:
    if not fields:
        return
    sets, vals = [], []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(_jsonb(v) if isinstance(v, (dict, list)) else v)
    vals.append(run_id)
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(f"UPDATE wd_runs SET {', '.join(sets)} WHERE id = %s", vals)
        c.commit()


def get_wd_run(run_id: int) -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM wd_runs WHERE id = %s", (run_id,))
        return cur.fetchone()


def latest_wd_run() -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM wd_runs ORDER BY id DESC LIMIT 1")
        return cur.fetchone()


def latest_resumable_run() -> Optional[dict]:
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM wd_runs WHERE status IN ('crashed','cancelled') "
            "ORDER BY id DESC LIMIT 1"
        )
        return cur.fetchone()


def latest_running_run() -> Optional[dict]:
    """The currently-active run, if any -- /cancel targets this. Only
    status='running' counts: a done/crashed/cancelled run is not active, and
    setting cancel_requested_at on one would report success while changing
    nothing (no per-firm loop is left to ever read the flag back)."""
    with cursor() as cur:
        cur.execute("SELECT * FROM wd_runs WHERE status = 'running' ORDER BY id DESC LIMIT 1")
        return cur.fetchone()


def reconcile_orphaned_runs() -> int:
    """Bot startup: workflow-d-bot.service has Restart=always, so if the
    process dies mid-run, systemd brings it back but the OLD run's wd_runs
    row is still sitting at status='running' with no process behind it
    forever -- latest_running_run() would find it and /cancel would flag a
    dead run and report success while changing nothing. Marks every such
    row 'crashed' with a note, and returns how many were reconciled so the
    caller can report it.

    Only touches wd_runs if it can acquire the run lock first: holding the
    lock IS the proof that no live run exists (a live run would already be
    holding it, whether it's a bot run or a concurrent CLI run this bot
    process has no other way to see). If the lock is already held, a run is
    genuinely live -- leave every row alone and say so, rather than
    reconciling out from under a process that is still working.
    """
    if not acquire_run_lock():
        log.warning(
            "reconcile_orphaned_runs: run lock is already held -- a run appears to "
            "be live, leaving wd_runs rows alone."
        )
        return 0
    try:
        with conn() as c:
            with c.cursor() as cur:
                cur.execute(
                    "UPDATE wd_runs SET status='crashed', finished_at=now(), "
                    "notes='Reconciled at bot startup: process died mid-run (previous status was running)' "
                    "WHERE status='running' RETURNING id"
                )
                rows = cur.fetchall()
            c.commit()
        return len(rows)
    finally:
        release_run_lock()


def request_run_cancellation(run_id: int) -> None:
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(
                "UPDATE wd_runs SET cancel_requested_at = now() "
                "WHERE id = %s AND cancel_requested_at IS NULL",
                (run_id,),
            )
        c.commit()


def cancel_requested(run_id: int) -> bool:
    with cursor() as cur:
        cur.execute("SELECT cancel_requested_at FROM wd_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    return bool(row and row["cancel_requested_at"])


# ---------------------------------------------------------------------------
# wd_firms
# ---------------------------------------------------------------------------
def create_wd_firm(run_id: int, firm_name: str, **fields) -> dict:
    cols = ["run_id", "firm_name", "firm_key"]
    vals: list[Any] = [run_id, firm_name, fields.pop("firm_key", firm_key(firm_name))]
    for k, v in fields.items():
        cols.append(k)
        vals.append(_jsonb(v) if isinstance(v, (dict, list)) else v)
    placeholders = ", ".join(["%s"] * len(cols))
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(
                f"INSERT INTO wd_firms ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *",
                vals,
            )
            row = cur.fetchone()
        c.commit()
    return row


def update_wd_firm(firm_id: int, **fields) -> None:
    if not fields:
        return
    sets, vals = [], []
    for k, v in fields.items():
        sets.append(f"{k} = %s")
        vals.append(_jsonb(v) if isinstance(v, (dict, list)) else v)
    vals.append(firm_id)
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(f"UPDATE wd_firms SET {', '.join(sets)} WHERE id = %s", vals)
        c.commit()


def get_wd_firm(firm_id: int) -> Optional[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM wd_firms WHERE id = %s", (firm_id,))
        return cur.fetchone()


def firms_for_run(run_id: int) -> list[dict]:
    with cursor() as cur:
        cur.execute("SELECT * FROM wd_firms WHERE run_id = %s ORDER BY id", (run_id,))
        return cur.fetchall()


def qualified_or_parked_firm_names() -> list[str]:
    """Every firm name ever QUALIFIED or PARKED, across all runs.

    The protected set for blocklist auto-adds (run-34): a name that fuzzy-
    matches one of these must never reach the blocklist, because a blocklist
    entry silently removes the firm from every future run and nothing
    re-tests it. Parked counts as protected -- a park is "we could not decide",
    not "no".
    """
    with cursor() as cur:
        cur.execute("SELECT DISTINCT firm_name FROM wd_firms "
                    "WHERE icp_status IN ('qualified', 'parked') AND firm_name IS NOT NULL")
        return [r["firm_name"] for r in cur.fetchall()]


def parked_firms(run_id: Optional[int] = None) -> list[dict]:
    with cursor() as cur:
        if run_id is not None:
            cur.execute(
                "SELECT * FROM wd_firms WHERE run_id=%s AND icp_status='parked' ORDER BY id",
                (run_id,),
            )
        else:
            cur.execute("SELECT * FROM wd_firms WHERE icp_status='parked' ORDER BY id")
        return cur.fetchall()


def parked_firm_by_name(firm_name: str) -> Optional[dict]:
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM wd_firms WHERE firm_key=%s AND icp_status='parked' "
            "ORDER BY id DESC LIMIT 1",
            (firm_key(firm_name),),
        )
        return cur.fetchone()


# ---------------------------------------------------------------------------
# Verdict cache (BRIEF 4.4) — the biggest cost lever in the funnel
# ---------------------------------------------------------------------------
def verdict_cache_lookup(name: str, window_days: int) -> Optional[dict]:
    """Return a still-fresh prior verdict for this firm, from D or C, else None.

    Two deliberate choices:

    1. `parked` verdicts are NOT cached. A park means the research was
       inconclusive, not that a decision was reached; re-running it on a later
       day is the whole point of the park and the /qualify rescue path. Only
       qualified and disqualified are terminal enough to reuse.
    2. Workflow C rows are matched on the same normalized firm_key computed
       here rather than on wc_firms.firm_name raw, so "Grubb Properties, LLC"
       in C matches "Grubb Properties" out of the scanner.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    key = firm_key(name)
    with cursor() as cur:
        cur.execute(
            "SELECT id, firm_name, icp_status, icp_reason, aum_tag, research, "
            "       COALESCE(gated_at, created_at) AS decided_at, 'cached_wd' AS src "
            "  FROM wd_firms "
            " WHERE firm_key = %s AND icp_status IN ('qualified','disqualified') "
            "   AND COALESCE(gated_at, created_at) >= %s "
            " ORDER BY id DESC LIMIT 1",
            (key, cutoff),
        )
        row = cur.fetchone()
        if row:
            return dict(row)
        # Workflow C's table has no firm_key column; normalize in SQL-free Python.
        cur.execute(
            "SELECT id, firm_name, icp_status, icp_reason, aum_tag, research_raw AS research, "
            "       created_at AS decided_at "
            "  FROM wc_firms "
            " WHERE icp_status IN ('qualified','disqualified') AND created_at >= %s "
            " ORDER BY id DESC",
            (cutoff,),
        )
        for candidate in cur.fetchall():
            if firm_key(candidate["firm_name"]) == key:
                out = dict(candidate)
                out["src"] = "cached_wc"
                return out
    return None


# ---------------------------------------------------------------------------
# wd_postings
# ---------------------------------------------------------------------------
def insert_postings(run_id: int, firm_id: Optional[int], rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = ["run_id", "firm_id", "company", "title", "url", "source", "dedup_key",
            "category", "subcategory", "region", "location", "posted_date",
            "first_seen", "days_since_posted", "match_reason",
            "poc_name_hint", "poc_designation_hint", "description", "cam_flag"]
    placeholders = ", ".join(["%s"] * len(cols))
    values = [
        [run_id, firm_id] + [r.get(c) for c in cols[2:]]
        for r in rows
    ]
    with conn() as c:
        with c.cursor() as cur:
            cur.executemany(
                f"INSERT INTO wd_postings ({', '.join(cols)}) VALUES ({placeholders})",
                values,
            )
        c.commit()
    return len(values)


def postings_for_firm(firm_id: int) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM wd_postings WHERE firm_id = %s ORDER BY id", (firm_id,)
        )
        return cur.fetchall()


# ---------------------------------------------------------------------------
# wd_drafts
# ---------------------------------------------------------------------------
def create_wd_draft(firm_id: int, **fields) -> dict:
    cols = ["firm_id"]
    vals: list[Any] = [firm_id]
    for k, v in fields.items():
        cols.append(k)
        vals.append(_jsonb(v) if isinstance(v, (dict, list)) else v)
    placeholders = ", ".join(["%s"] * len(cols))
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(
                f"INSERT INTO wd_drafts ({', '.join(cols)}) VALUES ({placeholders}) RETURNING *",
                vals,
            )
            row = cur.fetchone()
        c.commit()
    return row


def draft_exists_for_firm(firm_id: int) -> bool:
    with cursor() as cur:
        cur.execute("SELECT 1 FROM wd_drafts WHERE firm_id = %s LIMIT 1", (firm_id,))
        return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# contacted_pocs (cross-workflow dedup, HARD RULE 3). Shared infrastructure:
# the table itself is created by referral-system's migrations, not ours (see
# migrations/wd_001_tables.sql's own header comment) -- Workflow D reads and
# writes it directly here because referral-system's src/dbc.py, which
# already has this exact logic, is not vendored (only specific lib_referral
# files are; dbc.py isn't one of them). Same matching logic as referral's
# find_prior_contact/record_contacted: normalized LinkedIn URL first, email
# fallback, so a formatting difference (trailing slash, http vs https)
# doesn't let the same real person slip past as a "new" contact.
# ---------------------------------------------------------------------------
def find_prior_contact(linkedin_url: Optional[str], email: Optional[str]) -> Optional[dict]:
    """Cross-workflow, cross-run advisory check (HARD RULE 3): returns the
    MATCHING contacted_pocs row, or None. A hit is never blocking on its
    own -- the caller drafts anyway and attaches the row as a collision
    note. The within-run repeat block is a SEPARATE, simpler check done by
    the caller against its own in-memory set of emails contacted so far in
    THIS run, before this function is ever reached -- so a hit returned
    here is guaranteed to be a genuinely prior (pre-this-run) contact."""
    with cursor() as cur:
        if linkedin_url:
            cur.execute(
                "SELECT * FROM contacted_pocs WHERE linkedin_url IS NOT NULL AND "
                "lower(rtrim(regexp_replace(linkedin_url, '^https?://(www\\.)?', ''), '/')) = "
                "lower(rtrim(regexp_replace(%s, '^https?://(www\\.)?', ''), '/')) "
                "ORDER BY contacted_at LIMIT 1",
                (linkedin_url,),
            )
            row = cur.fetchone()
            if row:
                return row
        if email:
            cur.execute(
                "SELECT * FROM contacted_pocs WHERE lower(email) = lower(%s) "
                "ORDER BY contacted_at LIMIT 1",
                (email,),
            )
            row = cur.fetchone()
            if row:
                return row
    return None


def record_contacted(linkedin_url: Optional[str], email: Optional[str], poc_name: str,
                     firm_name: str, gmail_draft_id: str, source_workflow: str = "D") -> None:
    """Mirrors referral-system's dbc.record_contacted exactly (same table,
    same ON CONFLICT target): a repeat linkedin_url updates the existing row
    to this latest contact event rather than silently no-opping, so the one
    row that can exist for a given LinkedIn URL never goes stale."""
    with conn() as c:
        with c.cursor() as cur:
            cur.execute(
                """INSERT INTO contacted_pocs
                   (linkedin_url, email, poc_name, firm_name, source_workflow, gmail_draft_id)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (linkedin_url) WHERE linkedin_url IS NOT NULL DO UPDATE SET
                     email = EXCLUDED.email,
                     poc_name = EXCLUDED.poc_name,
                     firm_name = EXCLUDED.firm_name,
                     contacted_at = now(),
                     gmail_draft_id = EXCLUDED.gmail_draft_id,
                     source_workflow = EXCLUDED.source_workflow""",
                (linkedin_url, email, poc_name, firm_name, source_workflow, gmail_draft_id),
            )
        c.commit()


# ---------------------------------------------------------------------------
# wd_queue
# ---------------------------------------------------------------------------
def enqueue(run_id: int, firms: list[tuple[str, str]]) -> int:
    """firms = [(firm_key, firm_name), ...]"""
    if not firms:
        return 0
    with conn() as c:
        with c.cursor() as cur:
            cur.executemany(
                "INSERT INTO wd_queue (run_id, firm_key, firm_name) VALUES (%s, %s, %s)",
                [(run_id, k, n) for k, n in firms],
            )
        c.commit()
    return len(firms)


def next_pending(run_id: int, limit: int) -> list[dict]:
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM wd_queue WHERE run_id=%s AND status='pending' "
            "ORDER BY id LIMIT %s",
            (run_id, limit),
        )
        return cur.fetchall()


def set_queue_status(queue_id: int, status: str, firm_id: Optional[int] = None) -> None:
    with conn() as c:
        with c.cursor() as cur:
            if firm_id is None:
                cur.execute("UPDATE wd_queue SET status=%s WHERE id=%s", (status, queue_id))
            else:
                cur.execute(
                    "UPDATE wd_queue SET status=%s, firm_id=%s WHERE id=%s",
                    (status, firm_id, queue_id),
                )
        c.commit()


def queue_counts(run_id: int) -> dict:
    with cursor() as cur:
        cur.execute(
            "SELECT status, count(*) AS n FROM wd_queue WHERE run_id=%s GROUP BY status",
            (run_id,),
        )
        return {r["status"]: r["n"] for r in cur.fetchall()}
