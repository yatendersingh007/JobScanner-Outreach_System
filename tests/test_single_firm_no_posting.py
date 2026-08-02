"""Single-firm mode: hidden from /help, and honest when it can't draft.

`/scan "Firm"` and `/scan "Firm" fresh` skip the scanner, so the firm has no
wd_postings row. The v2 email template is posting-anchored: its opening names
the role and its P.S. links the posting. The required-fact check refuses to
ship an email asserting both with nothing behind them, so the command can
gate, resolve a POC and build a deck, but can never produce a draft.

Two consequences, both tested here. The commands stay wired and stop being
advertised. And the drafting path reports the outcome in plain language
instead of raising a ValueError that bot.py renders as "Could not start: ..."
before returning -- which used to take the verdict, the POC and the spend
down with the email.

The required-fact check itself is NOT relaxed anywhere below. The no-posting
path returns before it, and the last group of tests pins that it still fires
with full force everywhere it used to.
"""
from __future__ import annotations

import pytest

from src import bot, run_scan, signal_drafting as sd
from src.signal_drafting import DraftBatchResult
from src.signal_pipeline import RunResult


# ---------------------------------------------------------------------------
# /help: both single-firm lines gone, the commands still routed.
# ---------------------------------------------------------------------------
def test_help_text_does_not_document_the_single_firm_commands():
    help_text = bot._help_text()
    assert '/scan "Firm"' not in help_text
    assert "fresh" not in help_text
    assert "single-firm" not in help_text.lower()


def test_help_text_still_documents_everything_else():
    """The two lines were removed by hand; nothing adjacent went with them."""
    help_text = bot._help_text()
    for cmd in ("/scan  ", "/scan dry", "/scan days N", "/status", "/qualify",
                "/disqualify", "/cancel", "/resume", "/block ", "/unblock ",
                "/blocklist", "/help"):
        assert cmd in help_text, f"{cmd} disappeared from /help"


def test_the_hidden_commands_are_undocumented_not_removed():
    """Hidden means absent from the help string and nowhere else. If this
    fails, someone read 'hidden' as 'delete it'."""
    plain = bot.parse_scan_args('"Kingbird Investment"')
    assert plain["firm"] == "Kingbird Investment" and plain["fresh"] is False
    assert bot.parse_scan_args('"Kingbird Investment" fresh')["fresh"] is True


class _SyncThread:
    """threading.Thread stand-in, as in test_bot_dispatch.py: runs target()
    inside .start() so the dispatch is deterministic."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


def test_the_hidden_commands_still_reach_run_single_firm(monkeypatch):
    """End to end through the router, not just the parser."""
    calls = []
    monkeypatch.setattr(bot.threading, "Thread", _SyncThread)
    monkeypatch.setattr(bot, "run_single_firm",
                        lambda **kw: calls.append(kw) or RunResult(run_id=1))
    monkeypatch.setattr(bot, "summarize", lambda r, dry_hint="": "")
    monkeypatch.setattr(bot.tg, "send", lambda text, chat_id=None: None)
    monkeypatch.setattr(bot.tg, "progress", lambda msg: None)
    monkeypatch.setattr(bot.tg, "finish", lambda reason: None)
    monkeypatch.setattr(bot.tg, "reset_live", lambda: None)
    if bot._busy.locked():
        bot._busy.release()

    bot._dispatch('/scan "Kingbird Investment" fresh')

    assert len(calls) == 1
    assert calls[0]["firm_name"] == "Kingbird Investment"
    assert calls[0]["fresh"] is True


# ---------------------------------------------------------------------------
# The drafting path.
#
# _wire() mirrors test_signal_drafting.py's _wire_poc: the POC name hint lives
# on the POSTING rows, so an empty postings list also means no hint, and the
# fallback wd_poc.find_senior_poc is what resolves the contact. Both are
# patched -- reaching the real one would hit live Apollo.
# ---------------------------------------------------------------------------
def _wire(monkeypatch, postings, deck_path="/out/deck.pdf", patch_draft_email=True):
    draft_calls, deck_calls = [], []
    monkeypatch.setattr(sd.dbc, "postings_for_firm", lambda firm_id: postings)
    monkeypatch.setattr(sd.apollo_enrich, "find_email", lambda **kw: (None, None))
    monkeypatch.setattr(sd.wd_poc, "find_senior_poc",
                        lambda *a, **kw: ("Dana Reyes", "dana@kingbird.com", "CFO"))
    monkeypatch.setattr(sd.dbc, "find_prior_contact", lambda **kw: None)
    monkeypatch.setattr(sd.dbc, "create_wd_draft", lambda firm_id, **f: {"id": 9, **f})
    monkeypatch.setattr(sd.dbc, "record_contacted", lambda **kw: None)
    monkeypatch.setattr(sd.gmail_client, "create_draft",
                        lambda to, subject, body, attach_path=None, progress=None:
                        {"draft_id": "DRAFT-1", "attached": bool(attach_path)})

    def fake_deck(*a, **kw):
        deck_calls.append(a)
        return deck_path

    def fake_draft_email(**kw):
        draft_calls.append(kw)
        return {"subject": "s", "body": "b", "word_count": 1,
                "thin_personalization": False, "fallback_stage": None,
                "fallback_reason": None}

    monkeypatch.setattr(sd, "_generate_deck", fake_deck)
    if patch_draft_email:
        monkeypatch.setattr(sd, "draft_email", fake_draft_email)
    firm = {"id": 1, "firm_name": "Kingbird Investment", "icp_status": "qualified",
            "research": {"own_domain": "kingbird.com"}}
    return firm, deck_calls, draft_calls


_BATCH_POSTING = [{"title": "Fund Controller", "url": "https://x.example/1",
                   "poc_name_hint": None, "poc_designation_hint": None,
                   "description": "Own the close."}]


def test_no_posting_returns_its_own_bucket(monkeypatch):
    firm, _deck, draft_calls = _wire(monkeypatch, [])
    progressed = []

    bucket, row = sd._draft_one_firm(firm, set(), progressed.append)

    assert bucket == "no_posting"
    # Not smuggled into an existing failure bucket: the POC WAS found and the
    # deck WAS built, so no_email and poc_domain_mismatch would both lie.
    assert bucket not in ("no_email", "poc_domain_mismatch", "duplicate_within_run")
    assert draft_calls == [], "draft_email must not be reached without a posting"


def test_no_posting_emits_the_plain_language_message(monkeypatch):
    firm, _deck, _draft = _wire(monkeypatch, [])
    progressed = []

    _bucket, row = sd._draft_one_firm(firm, set(), progressed.append)

    reason = row["no_posting_reason"]
    assert reason == (
        "Qualified, POC resolved, deck generated. No email drafted because "
        "single-firm mode has no job posting to anchor the v2 template. "
        "The draft fires automatically when a posting for this firm appears in a scan.")
    assert any(reason in msg for msg in progressed), "the operator must see it live too"


def test_the_message_replaces_the_raw_fact_check_text(monkeypatch):
    """The whole point: no violation identifiers reach the operator."""
    firm, _deck, _draft = _wire(monkeypatch, [])

    _bucket, row = sd._draft_one_firm(firm, set(), lambda _m: None)

    for leak in ("required-fact", "missing_role_title_in_opening",
                 "posting_title_not_grounded", "missing_posting_url_in_signoff",
                 "ValueError", "_"):
        assert leak not in row["no_posting_reason"]


def test_the_message_carries_no_em_dash(monkeypatch):
    """CLAUDE.md's style rule covers Telegram messages. The copy as dictated
    had an em dash between "deck generated" and "no email drafted"; it is a
    sentence break here."""
    firm, _deck, _draft = _wire(monkeypatch, [])

    _bucket, row = sd._draft_one_firm(firm, set(), lambda _m: None)

    assert "—" not in row["no_posting_reason"]
    assert "deck generated. No email drafted" in row["no_posting_reason"]


def test_the_message_does_not_claim_a_deck_that_failed(monkeypatch):
    """HARD RULE 5. The copy asserts three things happened; if the third
    didn't, the message says so rather than shipping a comfortable lie."""
    firm, _deck, _draft = _wire(monkeypatch, [], deck_path=None)

    _bucket, row = sd._draft_one_firm(firm, set(), lambda _m: None)

    assert "deck generation failed" in row["no_posting_reason"]
    assert "deck generated" not in row["no_posting_reason"]


def test_no_posting_row_keeps_the_poc_and_the_deck(monkeypatch):
    """The run produced real artifacts. They must survive into the summary."""
    firm, _deck, _draft = _wire(monkeypatch, [])

    _bucket, row = sd._draft_one_firm(firm, set(), lambda _m: None)

    assert row["poc_name"] == "Dana Reyes"
    assert row["poc_email"] == "dana@kingbird.com"
    assert row["deck_pdf_path"] == "/out/deck.pdf"
    assert row["firm_name"] == "Kingbird Investment"


def test_no_posting_writes_nothing_to_gmail_or_wd_drafts(monkeypatch):
    firm, _deck, _draft = _wire(monkeypatch, [])
    monkeypatch.setattr(sd.gmail_client, "create_draft",
                        lambda **kw: pytest.fail("no Gmail draft without an email"))
    monkeypatch.setattr(sd.dbc, "create_wd_draft",
                        lambda *a, **kw: pytest.fail("no wd_drafts row without an email"))
    monkeypatch.setattr(sd.dbc, "record_contacted",
                        lambda **kw: pytest.fail("nobody was contacted"))

    bucket, _row = sd._draft_one_firm(firm, set(), lambda _m: None)

    assert bucket == "no_posting"


# ---------------------------------------------------------------------------
# The batch path is untouched.
# ---------------------------------------------------------------------------
def test_a_firm_with_a_posting_still_drafts(monkeypatch):
    firm, _deck, draft_calls = _wire(monkeypatch, _BATCH_POSTING)

    bucket, _row = sd._draft_one_firm(firm, set(), lambda _m: None)

    assert bucket == "drafted"
    assert len(draft_calls) == 1
    assert draft_calls[0]["posting_title"] == "Fund Controller"


def test_the_batch_path_never_takes_the_no_posting_branch(monkeypatch):
    """Keyed on "no postings at all", which only single-firm mode produces:
    a batch firm is grouped FROM its postings. A posting that is merely thin
    -- no description, no POC hint -- is still a posting."""
    thin = [{"title": "Controller", "url": "https://x.example/2",
             "poc_name_hint": None, "poc_designation_hint": None, "description": None}]
    firm, _deck, draft_calls = _wire(monkeypatch, thin)

    bucket, _row = sd._draft_one_firm(firm, set(), lambda _m: None)

    assert bucket == "drafted"
    assert draft_calls[0]["posting_description"] == ""


def test_a_batch_posting_missing_its_url_still_raises(monkeypatch):
    """Real drift between the posting record and the draft is a different
    problem from having no posting, and must stay loud. If this ever returns
    "no_posting" instead, the branch has been keyed on the wrong thing and a
    genuine defect is being reported as an expected outcome."""
    no_url = [{"title": "Controller", "url": "", "poc_name_hint": None,
               "poc_designation_hint": None, "description": None}]
    firm, _deck, _draft = _wire(monkeypatch, no_url, patch_draft_email=False)

    with pytest.raises(ValueError, match="missing_posting_url_in_signoff"):
        sd._draft_one_firm(firm, set(), lambda _m: None)


# ---------------------------------------------------------------------------
# The required-fact check is unchanged.
# ---------------------------------------------------------------------------
def test_find_required_fact_violations_still_flags_a_missing_title_and_url():
    v = sd.find_required_fact_violations(
        opening_text="Hi Dana,", signoff_text="Harpreet", body_text="",
        posting_title="", firm_short_name="Kingbird", posting_url="",
        corpus_text="", deck_attached=False)
    assert "missing_role_title_in_opening" in v
    assert "posting_title_not_grounded" in v
    assert "missing_posting_url_in_signoff" in v


def test_draft_email_still_raises_when_a_caller_reaches_it_with_no_posting():
    """The guard is a caller-side early return, not a relaxation. Anything
    that reaches draft_email() without a posting still fails hard."""
    with pytest.raises(ValueError, match="required-fact check failed"):
        sd.draft_email(
            firm_name="Kingbird Investment", poc_first_name="Dana",
            poc_email="dana@kingbird.com", posting_title="", posting_url="",
            titles=[], posting_count=0, firm_short_name="Kingbird",
            research={"firm_oneliner": "Multifamily investment manager"},
            deck_attached=True)


# ---------------------------------------------------------------------------
# Plumbing: bucket -> DraftBatchResult -> RunResult -> summary.
# ---------------------------------------------------------------------------
def test_both_result_objects_carry_the_bucket():
    assert DraftBatchResult().no_posting == []
    assert RunResult(run_id=1).no_posting == []


def test_draft_for_run_routes_the_bucket(monkeypatch):
    firm = {"id": 1, "firm_name": "Kingbird Investment", "icp_status": "qualified"}
    monkeypatch.setattr(sd.dbc, "firms_for_run", lambda run_id: [firm])
    monkeypatch.setattr(sd.dbc, "cancel_requested", lambda run_id: False)
    monkeypatch.setattr(sd.dbc, "draft_exists_for_firm", lambda firm_id: False)
    monkeypatch.setattr(sd, "_draft_one_firm",
                        lambda f, c, p: ("no_posting", {**f, "no_posting_reason": "r"}))

    result = sd.draft_for_run(1, lambda _m: None)

    assert [f["firm_name"] for f in result.no_posting] == ["Kingbird Investment"]
    assert result.drafted == [] and result.no_email == []


def test_run_drafting_copies_the_bucket_onto_the_run_result(monkeypatch):
    batch = DraftBatchResult()
    batch.no_posting = [{"firm_name": "Kingbird Investment", "no_posting_reason": "r"}]
    monkeypatch.setattr(run_scan.signal_drafting, "draft_for_run",
                        lambda run_id, progress: batch)
    monkeypatch.setattr(run_scan.tg, "send", lambda text, chat_id=None: None)
    result = RunResult(run_id=1)
    result.qualified = [{"id": 1, "firm_name": "Kingbird Investment"}]

    run_scan._run_drafting(result, lambda _m: None)

    assert result.no_posting == batch.no_posting


def test_the_summary_reports_the_outcome_in_full(monkeypatch):
    reason = ("Qualified, POC resolved, deck generated. No email drafted because "
              "single-firm mode has no job posting to anchor the v2 template. "
              "The draft fires automatically when a posting for this firm appears "
              "in a scan.")
    result = RunResult(run_id=1)
    result.qualified = [{"id": 1, "firm_name": "Kingbird Investment", "posting_count": 0,
                         "aum_tag": "AUM_CONFIRMED", "verdict_source": "gated"}]
    result.no_posting = [{"firm_name": "Kingbird Investment", "no_posting_reason": reason}]

    text = run_scan.summarize(result)

    assert "NO POSTING TO DRAFT AGAINST 1" in text
    # The verdict still reaches the operator. Before this change the ValueError
    # returned out of bot.py before summarize() ran and none of it was reported.
    assert "QUALIFIED 1" in text
    assert reason in text


def test_the_summary_stays_silent_when_the_bucket_is_empty():
    result = RunResult(run_id=1)
    result.qualified = [{"id": 1, "firm_name": "Acme", "posting_count": 1,
                         "aum_tag": None, "verdict_source": "gated"}]

    assert "NO POSTING" not in run_scan.summarize(result)
