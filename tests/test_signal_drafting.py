"""Prompt 3: src/signal_drafting.py.

Adversarial by design (per the build instructions): the forbidden-claims
regex set is tested against a must-fire matrix (Manpreet in every form,
Singh Capital, referral/introduction/connection language) AND a must-NOT-
fire near-miss matrix (legitimate phrases that share a word with a forbidden
pattern but not its meaning) -- a check that only proves the must-fire half
is exactly the kind of check that ships silently too broad.

No live Postgres, no network, no live LLM: dbc/apollo_enrich/gmail_client
are monkeypatched on signal_drafting's own module object; the LLM path is
exercised either via config.TEST_MODE's existing fixture-or-fallback branch
(deterministic, no mock needed) or with lib_snapshot.models.complete_json_retry
mocked directly when a test needs to force config.TEST_MODE=False to reach
the real generate/retry/fallback control flow.
"""
from __future__ import annotations

import lib_snapshot.models as models_mod
import pytest

from src import signal_drafting as sd


# ---------------------------------------------------------------------------
# Forbidden claims: must-fire matrix
# ---------------------------------------------------------------------------
MUST_FIRE = [
    "Manpreet suggested I reach out to you.",
    "Manpreet Singh mentioned your recent expansion.",
    "You came up through our mutual connection.",
    "We were connected through a mutual friend last year.",
    "You came up in our network last week.",
    "A colleague recommended I reach out.",
    "I was referred to you by a friend.",
    "Someone in your network mentioned you were hiring.",
    "M. Singh suggested I write to you.",
    "This comes through Singh Capital's network.",
    "As we discussed on our call last week.",
    "We spoke with your team before about this.",
]

# Near-misses: share a word with a forbidden pattern, but not its meaning.
MUST_NOT_FIRE = [
    "You run a wide network of properties across three states.",
    "It gives you a connected portfolio across every close.",
    "This is an introduction to our model, not a pitch for software.",
    "Our operators plug into your network of Yardi entities directly.",
    "The introduction to our process takes about ten days.",
    "Their portfolio spans a connected set of multifamily assets.",
]


@pytest.mark.parametrize("text", MUST_FIRE)
def test_forbidden_claims_must_fire(text):
    assert sd.find_forbidden_claims(text), f"expected a hit on: {text!r}"


@pytest.mark.parametrize("text", MUST_NOT_FIRE)
def test_forbidden_claims_must_not_fire(text):
    assert not sd.find_forbidden_claims(text), f"unexpected hit on: {text!r}"


# ---------------------------------------------------------------------------
# "not just X, it's Y" -- the real variants, not just the canonical phrasing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "This is not just a hire, it's a capacity decision.",
    "It's not just about cost but about who actually knows your ledgers.",
    "This is not merely a staffing gap, it's a reporting risk.",
    "This isn't just a vacancy, it's a close that slips every month.",
])
def test_not_just_x_its_y_must_fire(text):
    assert sd._NOT_JUST_X_ITS_Y_RE.search(text), f"expected a hit on: {text!r}"


@pytest.mark.parametrize("text", [
    "We are not just accountants.",
    "This role is not just about month-end close.",
    "Property accountants are not just bookkeepers by trade.",
])
def test_not_just_x_its_y_must_not_fire(text):
    assert not sd._NOT_JUST_X_ITS_Y_RE.search(text), f"unexpected hit on: {text!r}"


def test_not_just_x_its_y_is_a_style_violation():
    assert "not_just_x_its_y" in sd.find_style_violations(
        "This is not just a hire, it's a capacity decision.")


# ---------------------------------------------------------------------------
# Block 4 argument: role connection must track the ACTUAL posting title
# ---------------------------------------------------------------------------
_CAM_PARAGRAPH = ("A CAM analyst search takes three months and the close does not "
                  "pause while you run it. Our operators already run CAM true-ups "
                  "and lender packages in Yardi on day 10, and they stay yours.")
_CONTROLLER_PARAGRAPH = ("A fund controller search takes three months and the close "
                         "does not pause while you run it. Our operators already run "
                         "waterfall allocations and investor reporting on day 10.")


def test_block4_argument_passes_when_role_matches():
    assert sd.find_missing_block4_argument(_CAM_PARAGRAPH, "CAM Analyst") == []


def test_block4_argument_fails_when_role_does_not_match():
    """The exact failure mode named in the build instructions: a CAM analyst
    paragraph must not pass review for a Fund Controller posting."""
    v = sd.find_missing_block4_argument(_CAM_PARAGRAPH, "Fund Controller")
    assert "missing_role_connection" in v


def test_block4_argument_fails_without_concrete_cost():
    v = sd.find_missing_block4_argument(
        "We offer embedded fund controllers who handle waterfall allocations.",
        "Fund Controller",
    )
    assert "missing_concrete_cost" in v


def test_block4_argument_abstract_risk_fails():
    """The template's own bad example: consultant-speak, no concrete cost."""
    v = sd.find_missing_concrete_cost(
        "We offer comprehensive solutions that can help streamline your "
        "accounting operations and unlock efficiency across your portfolio."
    )
    assert v == ["missing_concrete_cost"]


# ---------------------------------------------------------------------------
# Block 6: the deck-attached claim must never diverge from the attachment
# ---------------------------------------------------------------------------
def test_block6_omits_deck_sentence_when_not_attached():
    text = sd.block_6("https://boards.example/jobs/123", deck_attached=False)
    assert "deck is attached" not in text.lower()
    assert "https://boards.example/jobs/123" in text  # the URL line is unconditional


def test_block6_includes_deck_sentence_when_attached():
    text = sd.block_6("https://boards.example/jobs/123", deck_attached=True)
    assert "The deck is attached." in text
    assert "https://boards.example/jobs/123" in text


# ---------------------------------------------------------------------------
# Required facts
# ---------------------------------------------------------------------------
def test_required_facts_pass_when_assembled_correctly():
    b1 = sd.block_1("Jane", "Acme Capital", "Fund Controller", 1)
    b6 = sd.block_6("https://boards.example/jobs/123", deck_attached=False)
    corpus = sd.grounding_corpus({}, "Acme Capital", "Fund Controller",
                                 "https://boards.example/jobs/123", ["Fund Controller"], 1)
    v = sd.find_required_fact_violations(
        b1, b6, sd._BLOCK_3, "Fund Controller", "Acme Capital",
        "https://boards.example/jobs/123", corpus, deck_attached=False)
    assert v == []


def test_reworded_posting_title_fails_required_fact_check():
    """The posting_title used to assemble Block 1 must match the ground-truth
    corpus verbatim. A caller that reworded the title before calling block_1
    (e.g. paraphrased or re-cased it) is caught here, not shipped silently."""
    b1 = sd.block_1("Jane", "Acme Capital", "Senior Fund Controller", 1)
    b6 = sd.block_6("https://boards.example/jobs/123", deck_attached=False)
    # The corpus reflects the ACTUAL posting title, which differs from what
    # was used to build block_1 above -- simulating a reworded title.
    corpus = sd.grounding_corpus({}, "Acme Capital", "Fund Controller",
                                 "https://boards.example/jobs/123", ["Fund Controller"], 1)
    v = sd.find_required_fact_violations(
        b1, b6, sd._BLOCK_3, "Senior Fund Controller", "Acme Capital",
        "https://boards.example/jobs/123", corpus, deck_attached=False)
    assert "posting_title_not_grounded" in v


def test_missing_firm_name_in_block1_fails():
    b1 = sd.block_1("Jane", "Acme Capital", "Fund Controller", 1)
    v = sd.find_required_fact_violations(
        b1, "P.S. https://x.example", sd._BLOCK_3, "Fund Controller", "A Totally Different Firm",
        "https://x.example", "corpus text", deck_attached=False)
    assert "missing_firm_name_in_block1" in v


def test_missing_posting_url_in_block6_fails():
    b1 = sd.block_1("Jane", "Acme Capital", "Fund Controller", 1)
    v = sd.find_required_fact_violations(
        b1, "P.S. wrong url", sd._BLOCK_3, "Fund Controller", "Acme Capital",
        "https://boards.example/jobs/123", "corpus text with Fund Controller", deck_attached=False)
    assert "missing_posting_url_in_block6" in v


def test_block3_dollar_ranges_required():
    v = sd.find_required_fact_violations(
        "block1 text", "block6 text", "A modified Block 3 with no dollar ranges.",
        "Fund Controller", "Acme Capital", "https://x.example", "corpus", deck_attached=False)
    assert "block3_modified" in v


def test_deck_attachment_claim_mismatch_when_claimed_but_not_attached():
    b6 = sd.block_6("https://x.example", deck_attached=True)  # claims attached
    v = sd.find_required_fact_violations(
        "block1 text with Fund Controller and Acme Capital", b6, sd._BLOCK_3,
        "Fund Controller", "Acme Capital", "https://x.example",
        "corpus with Fund Controller", deck_attached=False)  # but it isn't
    assert "deck_attachment_claim_mismatch" in v


def test_deck_attachment_claim_mismatch_when_attached_but_not_claimed():
    b6 = sd.block_6("https://x.example", deck_attached=False)  # doesn't claim attached
    v = sd.find_required_fact_violations(
        "block1 text with Fund Controller and Acme Capital", b6, sd._BLOCK_3,
        "Fund Controller", "Acme Capital", "https://x.example",
        "corpus with Fund Controller", deck_attached=True)  # but it is
    assert "deck_attachment_claim_mismatch" in v


def test_deck_attachment_claim_matches_when_both_true():
    b6 = sd.block_6("https://x.example", deck_attached=True)
    v = sd.find_required_fact_violations(
        "block1 text with Fund Controller and Acme Capital", b6, sd._BLOCK_3,
        "Fund Controller", "Acme Capital", "https://x.example",
        "corpus with Fund Controller", deck_attached=True)
    assert "deck_attachment_claim_mismatch" not in v


def test_corpus_contains_posting_url():
    corpus = sd.grounding_corpus({"firm_oneliner": "x"}, "Acme Capital", "Fund Controller",
                                 "https://boards.example/jobs/123", ["Fund Controller"], 1)
    assert "https://boards.example/jobs/123" in corpus


# ---------------------------------------------------------------------------
# Grounding: a fabricated dollar figure is a HARD failure (no retry)
# ---------------------------------------------------------------------------
def test_fabricated_dollar_figure_is_a_hard_grounding_violation():
    corpus = sd.grounding_corpus({"disclosed_figure": "$300M"}, "Acme Capital",
                                 "Fund Controller", "https://x.example", ["Fund Controller"], 1)
    block2 = "Acme runs a $900M portfolio across the Southeast."
    v = sd.find_grounding_violations(block2, corpus)
    assert v  # $900M is not in the corpus -- ungrounded


def test_missing_required_aum_when_disclosed_figure_present():
    research = {"disclosed_figure": "$300M"}
    combined = "Acme is a real estate investment manager focused on multifamily."
    v = sd.find_missing_required_facts(combined, research)
    assert any("300" in x for x in v)


def test_missing_required_aum_not_forced_when_no_disclosed_figure():
    """The conditioning decision (recorded in BUILD_LOG.md): an AUM_ESTIMATED
    firm with a units proxy has no dollar figure at all, and the template
    says invent none -- this must not demand one."""
    research = {"disclosed_figure": "", "aum_tag": "AUM_ESTIMATED", "proxy_type": "units"}
    v = sd.find_missing_required_facts("Acme runs about 4,000 units.", research)
    assert v == []


# ---------------------------------------------------------------------------
# _generate_blocks: hard failure never retries; soft failure retries once
# ---------------------------------------------------------------------------
class _Usage:
    def __init__(self, total_tokens=200):
        self.total_tokens = total_tokens


def _no_retry_call(*a, **k):
    raise AssertionError("must not call complete_json_retry a second time after a hard failure")


def test_manpreet_in_llm_response_fails_hard_never_retried(monkeypatch):
    monkeypatch.setattr(sd.config, "TEST_MODE", False)
    calls = []

    def fake_complete(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) > 1:
            _no_retry_call()
        return ({"block_2": "Manpreet suggested I reach out about your Fund Controller role.",
                 "block_4": "Our operators already handle fund controller work like waterfall "
                            "allocations, and the search costs you every close while the seat "
                            "stays empty."},
                _Usage())

    monkeypatch.setattr(models_mod, "complete_json_retry", fake_complete)

    block2, block4, b2_fb, b4_fb = sd._generate_blocks(
        "Acme Capital", {"firm_oneliner": "A multifamily investment manager."},
        "Fund Controller", "https://x.example", ["Fund Controller"], 1)

    assert len(calls) == 1  # never retried
    assert b2_fb is True
    assert "manpreet" not in block2.lower()
    assert block2 == "A multifamily investment manager."  # fell back to the oneliner


def test_hard_failure_in_one_block_and_soft_violation_in_other(monkeypatch):
    """The real mixed case: Block 2 hard-fails (forbidden claim) while Block 4
    independently has only a SOFT violation (missing role connection).
    Block 2 must never be retried, and -- the bug found while tracing this
    exact scenario -- must never be echoed into the retry prompt labeled
    "already correct" context, since it isn't correct, it's forbidden
    content already headed to fallback regardless of what the retry
    produces. Block 4 still gets its own independent retry, requested
    alone."""
    monkeypatch.setattr(sd.config, "TEST_MODE", False)
    calls = []

    def fake_complete(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return ({"block_2": "Manpreet suggested I reach out about your Fund Controller role.",
                     "block_4": "Our operators run CAM true-ups and it costs you every close."},
                    _Usage())
        # The forbidden-list boilerplate always mentions "Manpreet" (every
        # retry prompt warns against it); what must NOT appear is Block 2's
        # actual hard-failed SENTENCE echoed back labeled as correct context.
        assert "Manpreet suggested I reach out" not in prompt, \
            "hard-failed Block 2 must not be echoed as context"
        assert "Block 2 (already correct" not in prompt
        assert '"block_2"' not in prompt, "Block 2 must not be re-requested"
        return ({"block_4": "A fund controller search takes three months and the seat "
                            "stays empty while you run it."},
                _Usage())

    monkeypatch.setattr(models_mod, "complete_json_retry", fake_complete)

    block2, block4, b2_fb, b4_fb = sd._generate_blocks(
        "Acme Capital", {"firm_oneliner": "A multifamily investment manager."},
        "Fund Controller", "https://x.example", ["Fund Controller"], 1)

    assert len(calls) == 2  # Block 4's independent soft retry still runs
    assert b2_fb is True   # Block 2 fell back, hard failure, never retried
    assert b4_fb is False  # Block 4's retry produced a clean result
    assert block2 == "A multifamily investment manager."
    assert "fund controller" in block4.lower()


def test_soft_violation_gets_one_retry_then_ships_clean_result(monkeypatch):
    monkeypatch.setattr(sd.config, "TEST_MODE", False)
    calls = []

    def fake_complete(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            # First pass: Block 2 has a banned word (style violation, soft).
            return ({"block_2": "We offer a comprehensive fit for your firm.",
                     "block_4": "A CAM analyst search takes three months and the seat "
                                "stays empty while you run it."},
                    _Usage(total_tokens=100))
        return ({"block_2": "You run a multifamily portfolio across the Southeast."},
                _Usage(total_tokens=100))

    monkeypatch.setattr(models_mod, "complete_json_retry", fake_complete)

    block2, block4, b2_fb, b4_fb = sd._generate_blocks(
        "Acme Capital", {}, "CAM Analyst", "https://x.example", ["CAM Analyst"], 1)

    assert len(calls) == 2  # exactly one retry
    assert b2_fb is False
    assert block2 == "You run a multifamily portfolio across the Southeast."


def test_retry_skipped_when_token_budget_already_spent(monkeypatch):
    monkeypatch.setattr(sd.config, "TEST_MODE", False)
    monkeypatch.setattr(sd.config, "MAX_LLM_TOKENS_PER_FIRM", 50)
    calls = []

    def fake_complete(prompt, **kwargs):
        calls.append(prompt)
        return ({"block_2": "We offer a comprehensive fit for your firm.",
                 "block_4": "A CAM analyst search takes three months and the seat "
                            "stays empty while you run it."},
                _Usage(total_tokens=999))

    monkeypatch.setattr(models_mod, "complete_json_retry", fake_complete)

    block2, block4, b2_fb, b4_fb = sd._generate_blocks(
        "Acme Capital", {"firm_oneliner": "A CRE manager."}, "CAM Analyst",
        "https://x.example", ["CAM Analyst"], 1)

    assert len(calls) == 1  # budget guard skipped the retry
    assert b2_fb is True


# ---------------------------------------------------------------------------
# Length guard: whole trailing sentences only, never mid-sentence
# ---------------------------------------------------------------------------
def test_trim_drops_whole_sentences_never_mid_sentence():
    block4 = ("A property accountant search takes three months. The close does "
              "not pause while you run it. Our operators already run CAM "
              "true-ups on day 10. They stay yours the whole time.")
    block2 = "You run a large multifamily portfolio across the Southeast."
    trimmed2, trimmed4 = sd._trim_to_budget(block2, block4, fixed_word_count=200)
    for block in (trimmed2, trimmed4):
        assert block == "" or block[-1] in ".!?"


def test_trim_never_touches_fixed_fallback_block4():
    block4 = sd._FALLBACK_BLOCK_4
    block2 = "You run a large multifamily portfolio across the Southeast and Texas."
    trimmed2, trimmed4 = sd._trim_to_budget(block2, block4, fixed_word_count=250, block4_is_fixed=True)
    assert trimmed4 == block4  # untouched


# ---------------------------------------------------------------------------
# draft_email: full assembly, TEST_MODE fixture-or-fallback path (no mocks
# needed -- config.TEST_MODE defaults True and Acme Capital has no fixture).
# ---------------------------------------------------------------------------
def test_draft_email_full_assembly_prints_and_grounds_url():
    content = sd.draft_email(
        firm_name="Acme Capital Partners", poc_first_name="Jane", poc_email="jane@acme.example",
        posting_title="Fund Controller", posting_url="https://boards.example/jobs/456",
        titles=["Fund Controller"], posting_count=1, firm_short_name="Acme Capital",
        research={"firm_oneliner": "A multifamily investment manager active in the Southeast."},
    )
    assert "Fund Controller" in content["body"]
    assert "https://boards.example/jobs/456" in content["body"]
    assert content["word_count"] <= sd.config.EMAIL_MAX_WORDS
    assert content["subject"] == "Your Fund Controller opening"
    assert "deck is attached" not in content["body"].lower()  # deck_attached defaults False


def test_draft_email_claims_deck_attached_only_when_told_to():
    content = sd.draft_email(
        firm_name="Acme Capital Partners", poc_first_name="Jane", poc_email="jane@acme.example",
        posting_title="Fund Controller", posting_url="https://boards.example/jobs/456",
        titles=["Fund Controller"], posting_count=1, firm_short_name="Acme Capital",
        research={"firm_oneliner": "A multifamily investment manager active in the Southeast."},
        deck_attached=True,
    )
    assert "The deck is attached." in content["body"]


def test_draft_email_multi_posting_subject_and_block1():
    content = sd.draft_email(
        firm_name="Acme Capital Partners", poc_first_name="Jane", poc_email="jane@acme.example",
        posting_title="Fund Controller", posting_url="https://boards.example/jobs/456",
        titles=["Fund Controller", "Staff Accountant"], posting_count=2,
        firm_short_name="Acme Capital", research={},
    )
    assert content["subject"] == "Your 2 open finance roles"
    assert "2 finance roles open at Acme Capital" in content["body"]


# ---------------------------------------------------------------------------
# draft_for_run: cancel between firms, DRAFT_CAP_PER_RUN, within-run
# duplicate block, cross-workflow advisory (drafts anyway + collision_note).
# ---------------------------------------------------------------------------
def _firm(fid, name):
    return {"id": fid, "firm_name": name, "icp_status": "qualified", "research": {}}


def _posting(title="Fund Controller", url="https://x.example/1", poc="Jane Doe", desig="CFO"):
    return {"title": title, "url": url, "poc_name_hint": poc, "poc_designation_hint": desig}


def _patch_common(monkeypatch, firms, postings_by_id, emails_by_name):
    monkeypatch.setattr(sd.dbc, "firms_for_run", lambda run_id: firms)
    monkeypatch.setattr(sd.dbc, "postings_for_firm", lambda fid: postings_by_id.get(fid, []))
    monkeypatch.setattr(sd.dbc, "cancel_requested", lambda run_id: False)
    monkeypatch.setattr(sd.dbc, "draft_exists_for_firm", lambda fid: False)
    created = []
    monkeypatch.setattr(sd.dbc, "create_wd_draft", lambda fid, **fields: created.append(
        {**fields, "firm_id": fid}) or created[-1])
    monkeypatch.setattr(sd.dbc, "find_prior_contact", lambda linkedin_url, email: None)
    recorded = []
    monkeypatch.setattr(sd.dbc, "record_contacted", lambda **k: recorded.append(k))

    def fake_find_email(poc_name, company_name, linkedin_url=None, domain=None,
                        seed_email=None, progress=None):
        hit = emails_by_name.get(company_name)
        return hit if hit else (None, None)

    monkeypatch.setattr(sd.apollo_enrich, "find_email", fake_find_email)
    monkeypatch.setattr(sd.gmail_client, "create_draft",
                        lambda to, subject, body, attach_path=None, progress=None:
                        {"draft_id": f"DRAFT-{to}", "attached": False})
    return created, recorded


def test_draft_for_run_respects_draft_cap(monkeypatch):
    monkeypatch.setattr(sd.config, "DRAFT_CAP_PER_RUN", 2)
    firms = [_firm(1, "Firm A"), _firm(2, "Firm B"), _firm(3, "Firm C")]
    postings = {1: [_posting(poc="Poc A")], 2: [_posting(poc="Poc B")], 3: [_posting(poc="Poc C")]}
    emails = {"Firm A": ("a@x.example", "verified"), "Firm B": ("b@x.example", "verified"),
             "Firm C": ("c@x.example", "verified")}
    _patch_common(monkeypatch, firms, postings, emails)

    result = sd.draft_for_run(run_id=1)

    assert len(result.drafted) == 2  # capped, Firm C never even attempted


def test_draft_for_run_stops_at_cancel_between_firms(monkeypatch):
    monkeypatch.setattr(sd.config, "DRAFT_CAP_PER_RUN", 5)
    firms = [_firm(1, "Firm A"), _firm(2, "Firm B")]
    postings = {1: [_posting(poc="Poc A")], 2: [_posting(poc="Poc B")]}
    emails = {"Firm A": ("a@x.example", "verified"), "Firm B": ("b@x.example", "verified")}
    created, recorded = _patch_common(monkeypatch, firms, postings, emails)

    calls = {"n": 0}

    def cancel_after_first(run_id):
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(sd.dbc, "cancel_requested", cancel_after_first)

    result = sd.draft_for_run(run_id=1)

    assert result.cancelled is True
    assert len(result.drafted) == 1  # Firm A finished cleanly, Firm B never started


def test_draft_for_run_no_email_when_no_poc_hint(monkeypatch):
    """apollo_enrich cannot search by title and company (confirmed gap, see
    BUILD_LOG.md) -- with no scanner hint at all, the reason must say so
    plainly, not read like the firm simply has no one to contact."""
    firms = [_firm(1, "Firm A")]
    postings = {1: [{"title": "Fund Controller", "url": "https://x.example", "poc_name_hint": None,
                     "poc_designation_hint": None}]}
    _patch_common(monkeypatch, firms, postings, {})

    result = sd.draft_for_run(run_id=1)

    assert len(result.no_email) == 1
    assert result.drafted == []
    reason = result.no_email[0]["no_email_reason"]
    assert "no way yet to find who runs finance" in reason
    assert "search-by-title-and-company is not implemented" in reason


def test_draft_for_run_no_email_when_apollo_finds_nothing(monkeypatch):
    """A distinct reason from the no-hint case: there WAS a candidate name,
    Apollo just couldn't resolve an email for it."""
    firms = [_firm(1, "Firm A")]
    postings = {1: [_posting(poc="Poc A")]}
    _patch_common(monkeypatch, firms, postings, {})  # no email in the fixture map

    result = sd.draft_for_run(run_id=1)

    assert len(result.no_email) == 1
    reason = result.no_email[0]["no_email_reason"]
    assert "Poc A" in reason
    assert "could not resolve an email" in reason


def test_draft_for_run_within_run_duplicate_blocks(monkeypatch):
    """HARD RULE 3: within a single run, a repeat person BLOCKS -- unlike
    cross-run/cross-workflow contact, which is advisory only."""
    firms = [_firm(1, "Firm A"), _firm(2, "Firm B")]
    postings = {1: [_posting(poc="Jane Doe")], 2: [_posting(poc="Jane Doe")]}
    same_email = {"Firm A": ("jane@shared.example", "verified"),
                  "Firm B": ("jane@shared.example", "verified")}
    _patch_common(monkeypatch, firms, postings, same_email)

    result = sd.draft_for_run(run_id=1)

    assert len(result.drafted) == 1
    assert len(result.duplicate_within_run) == 1


def test_draft_for_run_cross_workflow_prior_contact_is_advisory_not_blocking(monkeypatch):
    """HARD RULE 3: a cross-workflow/cross-run hit drafts anyway, flagged
    loudly, never blocked."""
    firms = [_firm(1, "Firm A")]
    postings = {1: [_posting(poc="Jane Doe")]}
    emails = {"Firm A": ("jane@shared.example", "verified")}
    created, recorded = _patch_common(monkeypatch, firms, postings, emails)
    monkeypatch.setattr(sd.dbc, "find_prior_contact", lambda linkedin_url, email: {
        "source_workflow": "C", "contacted_at": "2026-01-01",
    })

    result = sd.draft_for_run(run_id=1)

    assert len(result.drafted) == 0
    assert len(result.drafted_with_prior_contact) == 1
    row = result.drafted_with_prior_contact[0]
    assert "Workflow C" in row["collision_note"]
    assert row["prior_contact_workflow"] == "C"


def test_draft_for_run_resets_and_reports_fallback_counts(monkeypatch):
    firms = [_firm(1, "Firm A")]
    postings = {1: [_posting(poc="Jane Doe")]}
    emails = {"Firm A": ("jane@x.example", "verified")}
    _patch_common(monkeypatch, firms, postings, emails)
    sd._fallback_counts["stale_from_a_previous_run"] = 99

    result = sd.draft_for_run(run_id=1)

    assert "stale_from_a_previous_run" not in result.fallback_counts
