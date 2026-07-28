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

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from lib_snapshot import db as shared_db

conn = shared_db.conn
cursor = shared_db.cursor


def apply_migrations() -> None:
    shared_db.migrate()


def _jsonb(value: Any) -> Any:
    return shared_db._jsonb(value)


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
            "SELECT id, firm_name, icp_status, icp_reason, aum_tag, research, "
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
            "poc_name_hint", "poc_designation_hint"]
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
