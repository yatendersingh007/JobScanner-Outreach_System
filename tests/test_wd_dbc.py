"""wd_dbc.latest_running_run(): without a filter that actually excludes
done/crashed/cancelled rows, /cancel would find a FINISHED run, set
cancel_requested_at on it, report success to the operator, and change
nothing -- there is no per-firm loop left on a finished run to ever read the
flag back.

No live Postgres in this environment: `cursor()` is monkeypatched with an
in-memory fake that inspects the literal SQL string for the `status =
'running'` filter and applies it to an in-memory row list, then sorts by id
descending -- mirroring the real query's WHERE + ORDER BY id DESC LIMIT 1.
This is not a substitute for a real integration test against Postgres, but
it does catch the specific regression class this test exists for: a future
edit that loosens or drops the status filter.

The acquire_run_lock()/release_run_lock() tests further down are the same
kind of fake, for the same reason: DATABASE_URL is unset in this environment
and the fallback default connection times out (confirmed directly against
psycopg before writing these -- not assumed). NOT verified against a real
Postgres server. The fake tracks pg_try_advisory_lock/pg_advisory_unlock's
real semantics (one shared lock flag, held connections not returned to the
pool) as closely as a fake reasonably can, and it does exercise wd_dbc's own
getconn/putconn bookkeeping for real, but it cannot prove Postgres itself
behaves the way the fake assumes it does.
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from src import wd_dbc


class _FakeWdRunsCursor:
    def __init__(self, rows):
        self._all_rows = rows
        self._result = None

    def execute(self, sql, params=None):
        if "status = 'running'" in sql:
            filtered = [r for r in self._all_rows if r["status"] == "running"]
        else:
            filtered = list(self._all_rows)
        filtered.sort(key=lambda r: r["id"], reverse=True)
        self._result = filtered[0] if filtered else None

    def fetchone(self):
        return self._result


@contextmanager
def _fake_cursor(rows):
    yield _FakeWdRunsCursor(rows)


def test_latest_running_run_ignores_done_crashed_cancelled(monkeypatch):
    rows = [
        {"id": 1, "status": "done"},
        {"id": 2, "status": "crashed"},
        {"id": 3, "status": "cancelled"},
        {"id": 4, "status": "running"},
    ]
    monkeypatch.setattr(wd_dbc, "cursor", lambda: _fake_cursor(rows))

    result = wd_dbc.latest_running_run()

    assert result == {"id": 4, "status": "running"}


def test_latest_running_run_returns_none_when_nothing_running(monkeypatch):
    rows = [{"id": 1, "status": "done"}, {"id": 2, "status": "cancelled"}, {"id": 3, "status": "crashed"}]
    monkeypatch.setattr(wd_dbc, "cursor", lambda: _fake_cursor(rows))

    assert wd_dbc.latest_running_run() is None


def test_latest_running_run_picks_the_most_recent_running_row(monkeypatch):
    rows = [
        {"id": 1, "status": "running"},
        {"id": 5, "status": "running"},
        {"id": 3, "status": "done"},
    ]
    monkeypatch.setattr(wd_dbc, "cursor", lambda: _fake_cursor(rows))

    result = wd_dbc.latest_running_run()

    assert result["id"] == 5


# ---------------------------------------------------------------------------
# reconcile_orphaned_runs(): workflow-d-bot.service's Restart=always means a
# crash mid-run leaves wd_runs.status='running' with no process behind it,
# forever -- latest_running_run() would find that stale row and /cancel would
# flag a dead run and report success while changing nothing. This must mark
# every such row 'crashed' at bot startup, before the first poll.
# ---------------------------------------------------------------------------
class _FakeUpdateCursor:
    def __init__(self, matching_ids):
        self._matching_ids = matching_ids
        self.executed_sql = None
        self._result_rows = None

    def execute(self, sql, params=None):
        self.executed_sql = sql
        if "status='running'" in sql or "status = 'running'" in sql:
            self._result_rows = [{"id": i} for i in self._matching_ids]
        else:
            self._result_rows = []

    def fetchall(self):
        return self._result_rows


class _FakeUpdateConn:
    def __init__(self, cur):
        self._cur = cur
        self.committed = False

    @contextmanager
    def cursor(self):
        yield self._cur

    def commit(self):
        self.committed = True


def test_reconcile_orphaned_runs_marks_running_rows_crashed(monkeypatch):
    # These two tests are about the UPDATE SQL only, decoupled from lock
    # contention (covered separately below) -- this process's own lock
    # acquisition always succeeds here.
    monkeypatch.setattr(wd_dbc, "acquire_run_lock", lambda: True)
    monkeypatch.setattr(wd_dbc, "release_run_lock", lambda: None)
    cur = _FakeUpdateCursor(matching_ids=[3, 7])
    fake_conn = _FakeUpdateConn(cur)
    monkeypatch.setattr(wd_dbc, "conn", lambda: _wrap(fake_conn))

    count = wd_dbc.reconcile_orphaned_runs()

    assert count == 2
    assert "status='crashed'" in cur.executed_sql
    assert "status='running'" in cur.executed_sql
    assert fake_conn.committed is True


def test_reconcile_orphaned_runs_returns_zero_when_nothing_stuck(monkeypatch):
    monkeypatch.setattr(wd_dbc, "acquire_run_lock", lambda: True)
    monkeypatch.setattr(wd_dbc, "release_run_lock", lambda: None)
    cur = _FakeUpdateCursor(matching_ids=[])
    fake_conn = _FakeUpdateConn(cur)
    monkeypatch.setattr(wd_dbc, "conn", lambda: _wrap(fake_conn))

    assert wd_dbc.reconcile_orphaned_runs() == 0
    assert fake_conn.committed is True


@contextmanager
def _wrap(obj):
    yield obj


# ---------------------------------------------------------------------------
# acquire_run_lock() / release_run_lock(): the REAL cross-front-door guard.
# src/cli.py and src/bot.py are two separate processes; bot.py's _busy
# in-process Lock cannot see a concurrent CLI process, and wd_runs.status is
# not proof of liveness (a crashed process leaves 'running' behind forever).
# A session-scoped Postgres advisory lock covers both with one mechanism and
# releases itself the instant the holding connection -- hence the holding
# process -- dies.
# ---------------------------------------------------------------------------
class _FakeLockCursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __init__(self, pool):
        self._pool = pool
        self._result = None

    def execute(self, sql, params=None):
        if "pg_try_advisory_lock" in sql:
            if self._pool.held:
                self._result = {"acquired": False}
            else:
                self._pool.held = True
                self._result = {"acquired": True}
        elif "pg_advisory_unlock" in sql:
            self._pool.held = False
            self._result = {"pg_advisory_unlock": True}
        else:
            raise AssertionError(f"unexpected SQL in lock test: {sql!r}")

    def fetchone(self):
        return self._result


class _FakeLockConn:
    def __init__(self, pool):
        self._pool = pool
        self.committed = False

    def cursor(self):
        return _FakeLockCursor(self._pool)

    def commit(self):
        self.committed = True


class _FakeLockPool:
    """One instance = one simulated Postgres server's lock state. Two
    "processes" contending for the lock are just two independent getconn()
    call sequences against the SAME instance -- checked_out tracks whether
    wd_dbc's own getconn/putconn bookkeeping ever leaks a connection."""

    def __init__(self, held: bool = False):
        self.held = held
        self.checked_out: list = []

    def getconn(self, timeout=None):
        c = _FakeLockConn(self)
        self.checked_out.append(c)
        return c

    def putconn(self, c):
        self.checked_out.remove(c)


@pytest.fixture(autouse=True)
def _reset_run_lock_state():
    """wd_dbc._run_lock_conn is a real module-level global (this process's
    own record of whether IT holds the lock) -- reset around every test in
    this file so state never leaks between tests."""
    wd_dbc._run_lock_conn = None
    yield
    wd_dbc._run_lock_conn = None


def test_acquire_succeeds_when_nothing_holds_the_lock(monkeypatch):
    pool = _FakeLockPool()
    monkeypatch.setattr(wd_dbc.shared_db, "get_pool", lambda: pool)

    acquired = wd_dbc.acquire_run_lock()

    assert acquired is True
    assert pool.held is True
    assert wd_dbc._run_lock_conn is not None
    assert len(pool.checked_out) == 1  # the connection stays checked out for the run's duration


def test_concurrent_acquire_fails_the_second_caller(monkeypatch):
    """Simulates a DIFFERENT process/session already holding the lock on the
    real server (pool.held=True) while THIS process has not acquired it
    (_run_lock_conn is None) -- exactly the scenario a second front door
    (the CLI while the bot is running, or vice versa) hits."""
    pool = _FakeLockPool(held=True)
    monkeypatch.setattr(wd_dbc.shared_db, "get_pool", lambda: pool)

    acquired = wd_dbc.acquire_run_lock()

    assert acquired is False
    assert wd_dbc._run_lock_conn is None
    assert pool.checked_out == []  # the probing connection was returned, not leaked


def test_acquire_is_idempotent_within_the_same_process(monkeypatch):
    pool = _FakeLockPool()
    monkeypatch.setattr(wd_dbc.shared_db, "get_pool", lambda: pool)

    first = wd_dbc.acquire_run_lock()
    second = wd_dbc.acquire_run_lock()  # same process asking again

    assert (first, second) == (True, True)
    assert len(pool.checked_out) == 1  # did not check out a second connection


def test_release_lets_the_next_caller_through(monkeypatch):
    pool = _FakeLockPool()
    monkeypatch.setattr(wd_dbc.shared_db, "get_pool", lambda: pool)

    wd_dbc.acquire_run_lock()
    wd_dbc.release_run_lock()

    assert pool.held is False
    assert wd_dbc._run_lock_conn is None
    assert pool.checked_out == []

    # A fresh acquire -- simulating either the next run in this process, or
    # a genuinely different process now that the server-side lock is free --
    # succeeds.
    assert wd_dbc.acquire_run_lock() is True


def test_release_without_acquire_is_a_noop(monkeypatch):
    pool = _FakeLockPool()
    monkeypatch.setattr(wd_dbc.shared_db, "get_pool", lambda: pool)

    wd_dbc.release_run_lock()  # never acquired -- must not raise or touch the pool

    assert pool.checked_out == []


def test_reconcile_is_a_noop_while_the_lock_is_held(monkeypatch):
    """A live run holds the lock elsewhere -- reconcile must leave every
    wd_runs row alone, and must NOT touch the DB at all (proven by making
    `conn` fail the test if it's ever called), and must NOT release the
    live run's lock out from under it."""
    pool = _FakeLockPool(held=True)
    monkeypatch.setattr(wd_dbc.shared_db, "get_pool", lambda: pool)
    monkeypatch.setattr(wd_dbc, "conn",
                        lambda: pytest.fail("must not touch wd_runs while the lock is held"))

    count = wd_dbc.reconcile_orphaned_runs()

    assert count == 0
    assert pool.held is True  # unchanged: reconcile never held, so never released, this lock
    assert wd_dbc._run_lock_conn is None  # reconcile itself never acquired it


def test_reconcile_acquires_and_releases_around_a_real_update(monkeypatch):
    """When nothing is live, reconcile briefly holds the lock (proving no
    run is live), does its UPDATE, and releases -- leaving the lock free for
    whatever starts next (the bot's own first /scan, for instance)."""
    pool = _FakeLockPool()
    monkeypatch.setattr(wd_dbc.shared_db, "get_pool", lambda: pool)
    cur = _FakeUpdateCursor(matching_ids=[9])
    fake_conn = _FakeUpdateConn(cur)
    monkeypatch.setattr(wd_dbc, "conn", lambda: _wrap(fake_conn))

    count = wd_dbc.reconcile_orphaned_runs()

    assert count == 1
    assert pool.held is False  # released again afterward
    assert wd_dbc._run_lock_conn is None
    assert pool.checked_out == []


# ---------------------------------------------------------------------------
# find_prior_contact() / record_contacted() (Prompt 3, HARD RULE 3): the
# shared contacted_pocs table itself is created by referral-system's own
# migrations (see migrations/wd_001_tables.sql's header comment), not ours --
# these two functions just read/write it directly, mirroring
# referral-system/src/dbc.py's identical logic exactly (that file isn't
# vendored, so the SQL is duplicated, not imported).
# ---------------------------------------------------------------------------
class _FakeContactedPocsCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed: list[tuple] = []
        self._result = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "linkedin_url IS NOT NULL" in sql:
            self._result = next((r for r in self._rows if r.get("linkedin_url")), None)
        elif "lower(email)" in sql:
            target = (params[0] or "").lower()
            self._result = next((r for r in self._rows if (r.get("email") or "").lower() == target), None)
        else:
            self._result = None

    def fetchone(self):
        return self._result


def test_find_prior_contact_tries_linkedin_url_before_email(monkeypatch):
    rows = [{"linkedin_url": "https://linkedin.com/in/jane", "email": "jane@x.example",
            "source_workflow": "C"}]
    cur = _FakeContactedPocsCursor(rows)
    monkeypatch.setattr(wd_dbc, "cursor", lambda: _fake_cursor_wrap(cur))

    result = wd_dbc.find_prior_contact("https://linkedin.com/in/jane", "jane@x.example")

    assert result["source_workflow"] == "C"
    assert "linkedin_url IS NOT NULL" in cur.executed[0][0]


def test_find_prior_contact_falls_back_to_email_when_no_linkedin_url(monkeypatch):
    rows = [{"linkedin_url": None, "email": "jane@x.example", "source_workflow": "A"}]
    cur = _FakeContactedPocsCursor(rows)
    monkeypatch.setattr(wd_dbc, "cursor", lambda: _fake_cursor_wrap(cur))

    result = wd_dbc.find_prior_contact(None, "jane@x.example")

    assert result["source_workflow"] == "A"


def test_find_prior_contact_returns_none_when_nothing_matches(monkeypatch):
    cur = _FakeContactedPocsCursor([])
    monkeypatch.setattr(wd_dbc, "cursor", lambda: _fake_cursor_wrap(cur))

    assert wd_dbc.find_prior_contact(None, "nobody@x.example") is None


def test_record_contacted_inserts_with_on_conflict_upsert(monkeypatch):
    cur = _FakeUpdateCursor(matching_ids=[])
    fake_conn = _FakeUpdateConn(cur)
    monkeypatch.setattr(wd_dbc, "conn", lambda: _wrap(fake_conn))

    wd_dbc.record_contacted(linkedin_url=None, email="jane@x.example", poc_name="Jane Doe",
                            firm_name="Acme Capital", gmail_draft_id="D1", source_workflow="D")

    assert "INSERT INTO contacted_pocs" in cur.executed_sql
    assert "ON CONFLICT (linkedin_url)" in cur.executed_sql
    assert fake_conn.committed is True


@contextmanager
def _fake_cursor_wrap(cur):
    yield cur


# ---------------------------------------------------------------------------
# wd_postings.description (migration wd_004).
#
# The column existed nowhere before this: NormalizedJob carried a description
# and the JSearch adapter filled it, but _posting_row() never copied it and
# insert_postings() never listed it, so the v2 signal email's Block 2
# traceability check and its {systems_if_known} clause could never activate --
# block2_generic fired on every draft, for every source.
#
# No live Postgres in this environment (see the module docstring above), so
# insert is exercised against a fake connection that captures the SQL and the
# value rows, and the read path against a fake cursor. The real round trip was
# verified separately against the live database; these tests exist to catch a
# future edit that drops the column from either list again.
# ---------------------------------------------------------------------------
_JSEARCH_DESCRIPTION = (
    "The Property Accountant will own month-end close for a 40-property portfolio, "
    "prepare bank reconciliations in Yardi, and produce owner reporting packages "
    "each month."
)


class _FakeInsertCursor:
    def __init__(self, captured):
        self.captured = captured

    def executemany(self, sql, values):
        self.captured["sql"] = sql
        self.captured["values"] = values

    def execute(self, sql, params=None):
        self.captured.setdefault("execute", []).append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeInsertConn:
    def __init__(self, captured):
        self.captured = captured

    def cursor(self):
        return _FakeInsertCursor(self.captured)

    def commit(self):
        self.captured["committed"] = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def captured_insert(monkeypatch):
    captured = {}

    @contextmanager
    def fake_conn():
        yield _FakeInsertConn(captured)

    monkeypatch.setattr(wd_dbc, "conn", fake_conn)
    return captured


def _posting_dict(**over):
    row = {
        "company": "Acme Capital", "title": "Property Accountant",
        "url": "https://x.example/1", "source": "aggregator:jsearch",
        "dedup_key": "aggregator:jsearch:abc", "category": "Real Estate",
        "subcategory": "Property Accounting", "region": "US", "location": "Austin, TX",
        "posted_date": None, "first_seen": None, "days_since_posted": 0,
        "match_reason": "test", "poc_name_hint": None, "poc_designation_hint": None,
        "description": _JSEARCH_DESCRIPTION,
    }
    row.update(over)
    return row


def test_insert_postings_lists_description_in_its_columns(captured_insert):
    wd_dbc.insert_postings(7, 3, [_posting_dict()])

    sql = captured_insert["sql"]
    assert "description" in sql
    # one placeholder per column, stated directly rather than inferred from a
    # comma count that happens to work out
    columns = sql[sql.index("(") + 1:sql.index(")")].split(", ")
    assert sql.count("%s") == len(columns)


def test_insert_postings_sends_the_description_value(captured_insert):
    wd_dbc.insert_postings(7, 3, [_posting_dict()])

    values = captured_insert["values"][0]
    assert _JSEARCH_DESCRIPTION in values


def test_insert_postings_column_order_matches_the_value_order(captured_insert):
    """A column list and a value list built separately can drift. This pins
    them together: description must be the LAST of both."""
    wd_dbc.insert_postings(7, 3, [_posting_dict()])

    sql = captured_insert["sql"]
    columns = sql[sql.index("(") + 1:sql.index(")")].split(", ")
    values = captured_insert["values"][0]

    assert len(columns) == len(values)
    assert columns[-1] == "description"
    assert values[-1] == _JSEARCH_DESCRIPTION
    assert columns[0] == "run_id" and values[0] == 7
    assert columns[1] == "firm_id" and values[1] == 3


def test_insert_postings_sends_none_when_a_posting_has_no_description(captured_insert):
    """TinyFish postings genuinely have none. They must arrive as NULL rather
    than an empty string that reads as "we looked and it was blank"."""
    row = _posting_dict()
    del row["description"]
    wd_dbc.insert_postings(7, 3, [row])

    assert captured_insert["values"][0][-1] is None


def test_postings_for_firm_returns_the_description(monkeypatch):
    """The read path is SELECT *, so the column flows through once it exists.
    Pinned so a future edit to an explicit column list cannot silently drop
    it."""
    stored = [{"id": 1, "firm_id": 3, "title": "Property Accountant",
              "source": "aggregator:jsearch", "description": _JSEARCH_DESCRIPTION}]

    class _Cur:
        def execute(self, sql, params=None):
            assert "SELECT *" in sql or "description" in sql
            self.rows = stored

        def fetchall(self):
            return self.rows

    @contextmanager
    def fake_cursor():
        yield _Cur()

    monkeypatch.setattr(wd_dbc, "cursor", fake_cursor)

    rows = wd_dbc.postings_for_firm(3)

    assert rows[0]["description"] == _JSEARCH_DESCRIPTION


def test_posting_row_copies_the_description_off_the_normalized_job():
    from src.signal_pipeline import _posting_row

    class Job:
        company = "Acme Capital"
        title = "Property Accountant"
        url = "https://x.example/1"
        source = "aggregator:jsearch"
        category = "Real Estate"
        subcategory = "Property Accounting"
        region = "US"
        location = "Austin, TX"
        posted_date = None
        first_seen = None
        days_since_posted = 0
        match_reason = "test"
        poc_name = None
        poc_designation = None
        description = _JSEARCH_DESCRIPTION

        def dedup_key(self):
            return "aggregator:jsearch:abc"

    row = _posting_row(Job())

    assert row["description"] == _JSEARCH_DESCRIPTION


def test_posting_row_tolerates_a_job_object_without_a_description():
    """getattr with a default, so a NormalizedJob-shaped test double that
    predates the field does not raise."""
    from src.signal_pipeline import _posting_row

    class Job:
        company = "Acme"
        title = "Controller"
        url = "u"
        source = "tinyfish:LinkedIn US - Controller"
        category = "Real Estate"
        subcategory = "Property Accounting"
        region = "US"
        location = ""
        posted_date = None
        first_seen = None
        days_since_posted = 0
        match_reason = ""
        poc_name = None
        poc_designation = None

        def dedup_key(self):
            return "k"

    assert _posting_row(Job())["description"] == ""


def test_a_jsearch_posting_reaches_draft_email_with_its_description_intact(monkeypatch):
    """End to end through the drafting entry point: a posting row carrying a
    JSearch description must reach draft_email, which means Block 2 is NOT
    generic and the systems clause names the system the posting mentioned."""
    from src import signal_drafting as sd

    seen = {}
    real_draft_email = sd.draft_email

    def spy_draft_email(**kwargs):
        seen["posting_description"] = kwargs.get("posting_description")
        return real_draft_email(**kwargs)

    monkeypatch.setattr(sd.dbc, "postings_for_firm", lambda fid: [{
        "title": "Property Accountant", "url": "https://x.example/1",
        "source": "aggregator:jsearch", "poc_name_hint": "Jane Doe",
        "poc_designation_hint": "Controller", "description": _JSEARCH_DESCRIPTION,
    }])
    monkeypatch.setattr(sd.apollo_enrich, "find_email",
                        lambda **kw: ("jane@acme.example", "verified"))
    monkeypatch.setattr(sd.wd_poc, "find_senior_poc",
                        lambda *a, **kw: pytest.fail("should not be reached"))
    monkeypatch.setattr(sd.dbc, "find_prior_contact", lambda **kw: None)
    monkeypatch.setattr(sd, "_generate_deck", lambda *a, **kw: None)
    monkeypatch.setattr(sd, "draft_email", spy_draft_email)
    monkeypatch.setattr(sd.dbc, "create_wd_draft", lambda fid, **f: {"id": 1, **f})
    monkeypatch.setattr(sd.dbc, "record_contacted", lambda **kw: None)
    monkeypatch.setattr(sd.gmail_client, "create_draft",
                        lambda to, subject, body, attach_path=None, progress=None:
                        {"draft_id": "D1", "attached": False})

    bucket, row = sd._draft_one_firm(
        {"id": 1, "firm_name": "Acme Capital", "research": {},
         "category": "Real Estate", "subcategory": "Property Accounting"},
        set(), lambda m: None)

    assert bucket == "drafted"
    assert seen["posting_description"] == _JSEARCH_DESCRIPTION
    # the two things the description unlocks
    assert ", across Yardi." in row["body"]
    assert "lender and owner reporting, across Yardi." in row["body"]


def test_a_tinyfish_posting_still_falls_back_to_the_generic_block(monkeypatch):
    """The other half of the same wiring: no description means no systems
    clause and no dangling "across"."""
    from src import signal_drafting as sd

    monkeypatch.setattr(sd.dbc, "postings_for_firm", lambda fid: [{
        "title": "Property Accountant", "url": "https://x.example/1",
        "source": "tinyfish:LinkedIn US - Property Accountant",
        "poc_name_hint": "Jane Doe", "poc_designation_hint": "Controller",
        "description": None,
    }])
    monkeypatch.setattr(sd.apollo_enrich, "find_email",
                        lambda **kw: ("jane@acme.example", "verified"))
    monkeypatch.setattr(sd.dbc, "find_prior_contact", lambda **kw: None)
    monkeypatch.setattr(sd, "_generate_deck", lambda *a, **kw: None)
    monkeypatch.setattr(sd.dbc, "create_wd_draft", lambda fid, **f: {"id": 1, **f})
    monkeypatch.setattr(sd.dbc, "record_contacted", lambda **kw: None)
    monkeypatch.setattr(sd.gmail_client, "create_draft",
                        lambda to, subject, body, attach_path=None, progress=None:
                        {"draft_id": "D1", "attached": False})

    _bucket, row = sd._draft_one_firm(
        {"id": 1, "firm_name": "Acme Capital", "research": {},
         "category": "Real Estate", "subcategory": "Property Accounting"},
        set(), lambda m: None)

    assert "across" not in row["body"]
    assert "lender and owner reporting." in row["body"]

