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

import re
import zipfile

import lib_snapshot.models as models_mod
import pytest

from src import signal_drafting as sd


@pytest.fixture(autouse=True)
def _default_test_mode_true(monkeypatch):
    """This environment's .env can carry TEST_MODE=false for live Apollo
    probing (see src/wd_poc.py's docstring) -- without forcing it back to
    True here, every test in this file that doesn't explicitly want the
    real-LLM control flow would silently fall through to real, slow, costly
    API calls during pytest instead of the deterministic fixture-or-fallback
    branch these tests are written against. The handful of tests that DO
    want the real-mode control flow (e.g. _generate_blocks's hard-fail/retry
    tests) call monkeypatch.setattr(sd.config, "TEST_MODE", False) themselves
    afterward, which wins over this fixture."""
    monkeypatch.setattr(sd.config, "TEST_MODE", True)


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
    # prior_contact_claim boundary cases (the fix that replaced a bare
    # character-gap widening with a you/your-anchored check -- see
    # BUILD_LOG.md): genuine prior-contact claims with a longer clause
    # between the verb and the temporal word.
    "We spoke with your controller before, back in March.",
    "We talked with someone at your firm previously.",
    "We have been in touch with your office earlier this year.",
    "We connected with your CFO earlier this quarter.",
    "We spoke to you before, at the conference in Dallas last fall.",
]

# Near-misses: share a word with a forbidden pattern, but not its meaning.
MUST_NOT_FIRE = [
    "You run a wide network of properties across three states.",
    "It gives you a connected portfolio across every close.",
    "This is an introduction to our model, not a pitch for software.",
    "Our operators plug into your network of Yardi entities directly.",
    "The introduction to our process takes about ten days.",
    "Their portfolio spans a connected set of multifamily assets.",
    # prior_contact_claim boundary near-misses: "we <verb> ... before" with
    # no reference to the recipient at all -- these were false positives
    # under a plain 40-char gap widening, caught before it shipped.
    "We have talked to operators who ran multifamily books before joining X Analyst.",
    "We connected two ledger systems before go-live last quarter.",
    "We have worked with property managers before, across several states.",
    "We talked through the transition plan before handing off the close.",
    "We have spoken with dozens of CRE controllers before, and the story repeats.",
    "We talked to three CFOs last month before drafting this offering.",
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


# ---------------------------------------------------------------------------
# firm_oneliner_not_grounded (run 27 fix): same mechanism as
# posting_title_not_grounded, applied to the firm one-liner Block 2 draws
# on. Note what this catches and what it doesn't -- see BUILD_LOG.md: a
# name-collision at the RESEARCH stage (icp_gate.py resolving a firm's
# research to a different real company) produces a oneliner that is
# genuinely, correctly grounded in a research blob, just the wrong one.
# This check only catches the corpus/research object drifting apart from
# each other, not the research itself being about the wrong firm.
# ---------------------------------------------------------------------------
def test_required_facts_pass_when_oneliner_is_empty():
    """Thin research is an honest, allowed state -- _fallback_blocks already
    lets Block 2 go blank rather than ship filler; the required-fact check
    must not punish that."""
    b1 = sd.block_1("Jane", "Acme Capital", "Fund Controller", 1)
    b6 = sd.block_6("https://boards.example/jobs/123", deck_attached=False)
    corpus = sd.grounding_corpus({}, "Acme Capital", "Fund Controller",
                                 "https://boards.example/jobs/123", ["Fund Controller"], 1)
    v = sd.find_required_fact_violations(
        b1, b6, sd._BLOCK_3, "Fund Controller", "Acme Capital",
        "https://boards.example/jobs/123", corpus, deck_attached=False, firm_oneliner="")
    assert v == []


def test_required_facts_pass_when_oneliner_is_grounded_in_the_research_corpus():
    b1 = sd.block_1("Jane", "Acme Capital", "Fund Controller", 1)
    b6 = sd.block_6("https://boards.example/jobs/123", deck_attached=False)
    research = {"firm_oneliner": "A multifamily investment manager active in the Southeast."}
    corpus = sd.grounding_corpus(research, "Acme Capital", "Fund Controller",
                                 "https://boards.example/jobs/123", ["Fund Controller"], 1)
    v = sd.find_required_fact_violations(
        b1, b6, sd._BLOCK_3, "Fund Controller", "Acme Capital",
        "https://boards.example/jobs/123", corpus, deck_attached=False,
        firm_oneliner=research["firm_oneliner"])
    assert "firm_oneliner_not_grounded" not in v


def test_firm_oneliner_not_grounded_fails_when_missing_from_corpus():
    """A caller passing a firm_oneliner that never made it into the corpus
    the LLM/fallback actually drew from -- e.g. research and corpus_text
    built from two different objects that drifted apart."""
    b1 = sd.block_1("Jane", "Acme Capital", "Fund Controller", 1)
    b6 = sd.block_6("https://boards.example/jobs/123", deck_attached=False)
    corpus = sd.grounding_corpus({}, "Acme Capital", "Fund Controller",
                                 "https://boards.example/jobs/123", ["Fund Controller"], 1)
    v = sd.find_required_fact_violations(
        b1, b6, sd._BLOCK_3, "Fund Controller", "Acme Capital",
        "https://boards.example/jobs/123", corpus, deck_attached=False,
        firm_oneliner="A description that never reached the research object.")
    assert "firm_oneliner_not_grounded" in v


def test_draft_email_extracts_and_checks_firm_oneliner_from_research(monkeypatch):
    """draft_email() itself must pull firm_oneliner out of `research` and
    pass it through -- not just find_required_fact_violations in isolation."""
    monkeypatch.setattr(sd, "_generate_blocks",
                        lambda *a, **k: ("Block 2 text.", "Block 4 text.", False, False))
    content = sd.draft_email(
        firm_name="Acme Capital", poc_first_name="Jane", poc_email="jane@acme.example",
        posting_title="Fund Controller", posting_url="https://x.example/1",
        titles=["Fund Controller"], posting_count=1, firm_short_name="Acme Capital",
        research={"firm_oneliner": "A multifamily investment manager active in the Southeast."},
    )
    assert content["body"]  # drafted successfully, no required-fact ValueError raised


def test_corpus_contains_posting_url():
    corpus = sd.grounding_corpus({"firm_oneliner": "x"}, "Acme Capital", "Fund Controller",
                                 "https://boards.example/jobs/123", ["Fund Controller"], 1)
    assert "https://boards.example/jobs/123" in corpus


# ---------------------------------------------------------------------------
# _canonical_posting_url (run 27 fix): live evidence -- Choice NY's draft
# P.S. carried LinkedIn guest-search tracking params
# ("?position=19&pageNum=0&refId=...&trackingId=..."), Neal Communities'
# (sourced via JSearch) was clean. Scoped to linkedin.com only: real
# ZipRecruiter rows in wd_postings use "?jid=<id>" as the actual job
# identifier, not a tracking param -- a blanket strip would break those.
# ---------------------------------------------------------------------------
def test_canonical_posting_url_strips_linkedin_tracking_params():
    dirty = ("https://www.linkedin.com/jobs/view/sr-property-accountant-at-choice-ny-"
            "property-management-llc-4447076066?position=19&pageNum=0"
            "&refId=vkwlqF%2FRXr7iSKM43%2BJnYA%3D%3D&trackingId=vFfRqvzoaYTCR%2FlWdpRuig%3D%3D")
    clean = ("https://www.linkedin.com/jobs/view/sr-property-accountant-at-choice-ny-"
            "property-management-llc-4447076066")
    assert sd._canonical_posting_url(dirty) == clean


def test_canonical_posting_url_leaves_an_already_clean_linkedin_url_unchanged():
    clean = ("https://www.linkedin.com/jobs/view/treasury-financial-analyst-at-neal-"
            "communities-of-southwest-florida-inc-4445031275")
    assert sd._canonical_posting_url(clean) == clean


def test_canonical_posting_url_strips_bare_linkedin_com_host_too():
    dirty = "https://linkedin.com/jobs/view/some-job-123?position=1&pageNum=0"
    assert sd._canonical_posting_url(dirty) == "https://linkedin.com/jobs/view/some-job-123"


def test_canonical_posting_url_leaves_ziprecruiter_jid_param_alone():
    """ZipRecruiter's own "?jid=" IS the job identifier, not a tracking
    param -- the path alone does not resolve without it. A real row
    observed in wd_postings, confirmed before writing this fix."""
    url = "https://www.ziprecruiter.com/c/URS-CAPITAL-PARTNERS-I/Job/Controller/-in-Huntington,NY?jid=0f16c83e739780b9"
    assert sd._canonical_posting_url(url) == url


def test_canonical_posting_url_leaves_other_domains_alone():
    url = "https://boards.example/jobs/123?utm_source=newsletter"
    assert sd._canonical_posting_url(url) == url


def test_canonical_posting_url_handles_empty_string():
    assert sd._canonical_posting_url("") == ""


def test_draft_for_run_strips_linkedin_tracking_params_before_drafting(monkeypatch):
    """End-to-end: a dirty LinkedIn posting URL must reach neither Block 6
    nor the grounding corpus with its tracking params intact."""
    dirty = ("https://www.linkedin.com/jobs/view/sr-property-accountant-at-choice-ny-"
            "4447076066?position=19&pageNum=0&refId=abc%3D%3D&trackingId=def%3D%3D")
    clean = "https://www.linkedin.com/jobs/view/sr-property-accountant-at-choice-ny-4447076066"
    firms = [_firm(1, "Firm A")]
    postings = {1: [_posting(url=dirty, poc="Jane Doe")]}
    emails = {"Firm A": ("jane@x.example", "verified")}
    _patch_common(monkeypatch, firms, postings, emails)

    result = sd.draft_for_run(run_id=1)

    assert len(result.drafted) == 1
    body = result.drafted[0]["body"]
    assert clean in body
    assert "position=" not in body
    assert "trackingId" not in body


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


def _patch_common(monkeypatch, firms, postings_by_id, emails_by_name, senior_poc_hits=None):
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

    # wd_poc.find_senior_poc hits the live Apollo API with no fake -- a real
    # APOLLO_API_KEY is configured in this environment's .env, so an
    # unmocked call here is a genuine network request during pytest, not a
    # hypothetical. Defaults to "no hit" (None) unless a test explicitly
    # wants the fallback to succeed via senior_poc_hits={firm_name: (name,
    # email, title)}.
    def fake_find_senior_poc(firm_name, domain=None, progress=None):
        return (senior_poc_hits or {}).get(firm_name)

    monkeypatch.setattr(sd.wd_poc, "find_senior_poc", fake_find_senior_poc)

    # _generate_deck calls lib_referral.deck_filler, which in real mode makes
    # an LLM call and shells out to soffice for PDF conversion -- neither
    # belongs in this file's tests (see module docstring: no live LLM). Every
    # test here that doesn't specifically want deck-generation behavior gets
    # the pre-existing "no deck" outcome; test_generate_deck_* below and the
    # dedicated draft_for_run deck tests cover the real behavior.
    monkeypatch.setattr(sd, "_generate_deck", lambda firm_name, research, progress: None)

    monkeypatch.setattr(sd.gmail_client, "create_draft",
                        lambda to, subject, body, attach_path=None, progress=None:
                        {"draft_id": f"DRAFT-{to}", "attached": False})
    return created, recorded


# ---------------------------------------------------------------------------
# _generate_deck: calls lib_referral.deck_filler (vendored, called not
# copied), never blocks a draft when deck generation itself fails.
# ---------------------------------------------------------------------------
def test_generate_deck_returns_pdf_path_on_success(monkeypatch):
    monkeypatch.setattr(sd.deck_filler, "get_deck_content",
                        lambda firm_name, research, personalization:
                        {"profile_bullets": [], "fit_paragraphs": {}})
    monkeypatch.setattr(sd.deck_filler, "build_and_convert",
                        lambda firm_name, research, deck_content, progress=None, personalization=None:
                        {"pptx_path": "generated_decks_c/Acme_Pitch.pptx",
                         "pdf_path": "generated_decks_c/Acme_Pitch.pdf",
                         "fill_data": {}})

    result = sd._generate_deck("Acme Capital", {"firm_oneliner": "A manager."}, progress=lambda m: None)

    assert result == "generated_decks_c/Acme_Pitch.pdf"


def test_generate_deck_returns_none_when_no_pdf_produced(monkeypatch):
    """convert_to_pdf() inside build_and_convert() already degrades to
    pdf_path=None on a missing soffice wrapper or a failed conversion --
    _generate_deck must pass that through as None, not crash on it."""
    monkeypatch.setattr(sd.deck_filler, "get_deck_content",
                        lambda firm_name, research, personalization: {})
    monkeypatch.setattr(sd.deck_filler, "build_and_convert",
                        lambda firm_name, research, deck_content, progress=None, personalization=None:
                        {"pptx_path": "generated_decks_c/Acme_Pitch.pptx", "pdf_path": None, "fill_data": {}})

    result = sd._generate_deck("Acme Capital", {}, progress=lambda m: None)

    assert result is None


def test_generate_deck_returns_none_and_logs_on_exception(monkeypatch):
    """A deck problem (LLM hiccup, a DeckFillError from a preflight/overflow
    check) must never cost a firm its draft."""
    def _boom(firm_name, research, personalization):
        raise RuntimeError("LLM extraction failed")

    monkeypatch.setattr(sd.deck_filler, "get_deck_content", _boom)
    progressed = []

    result = sd._generate_deck("Acme Capital", {}, progress=progressed.append)

    assert result is None
    assert any("deck generation failed" in msg for msg in progressed)


def test_generate_deck_forces_tokens_used_to_the_cap_to_suppress_the_retry(monkeypatch):
    """Run 27 (Choice NY, a third-party property manager): build_fill_data()'s
    Part C retry rewrote genuinely-empty fund_structures/
    underwriting_acquisitions/capital_markets fit paragraphs into invented
    fit claims that shipped to slide 04. deck_filler.py has no parameter to
    disable the retry -- the only exposed seam is its own token-budget
    check (tokens_so_far >= MAX_LLM_TOKENS_PER_FIRM). Forcing tokens_used to
    the cap here declines the retry unconditionally, without editing the
    vendored file."""
    monkeypatch.setattr(sd.deck_filler, "get_deck_content",
                        lambda firm_name, research, personalization: {"profile_bullets": []})
    captured = {}

    def fake_build_and_convert(firm_name, research, deck_content, progress=None, personalization=None):
        captured["deck_content"] = dict(deck_content)
        return {"pptx_path": None, "pdf_path": "generated_decks_c/Acme_Pitch.pdf", "fill_data": {}}

    monkeypatch.setattr(sd.deck_filler, "build_and_convert", fake_build_and_convert)

    sd._generate_deck("Acme Capital", {}, progress=lambda m: None)

    assert captured["deck_content"]["tokens_used"] == sd.gate_config.MAX_LLM_TOKENS_PER_FIRM


# ---------------------------------------------------------------------------
# _drop_bad_profile_bullets, headline rule: run 27 follow-up, Choice NY live
# evidence -- slide 01 repeated the italic headline verbatim as the bullet
# "Firm described as <the exact same oneliner text>". deck_filler.py's own
# _drop_oneliner_duplicate (vendored) exists for exactly this shape of
# waste but only does an exact-string compare, which the "Firm described
# as " lead-in defeats. The containment extension and its ratio floor are
# tested further down, with the deck self-description and forward-looking
# rules that share the same entry point.
# ---------------------------------------------------------------------------
_ONELINER = "Residential & mixed-use property management, third-party operator"


def test_strip_oneliner_lead_in_removes_the_live_observed_prefix():
    assert sd._strip_oneliner_lead_in(f"Firm described as {_ONELINER}") == _ONELINER


@pytest.mark.parametrize("prefix", [
    "Firm described as ",
    "The firm is described as ",
    "Company described as ",
    "The company is described as ",
    "Described as ",
])
def test_strip_oneliner_lead_in_removes_known_prefixes_case_insensitively(prefix):
    assert sd._strip_oneliner_lead_in(f"{prefix.upper()}{_ONELINER}") == _ONELINER


def test_strip_oneliner_lead_in_leaves_unrelated_text_alone():
    text = "Sold to Associa Corp. in 2021 with an earn-out noted"
    assert sd._strip_oneliner_lead_in(text) == text


def test_drop_bad_profile_bullets_removes_the_live_observed_case():
    bullets = [
        "Operates in the New York metropolitan area",
        f"Firm described as {_ONELINER}",
        "Manages assets valued at over $250 million",
    ]

    kept, dropped = sd._drop_bad_profile_bullets(bullets, _ONELINER)

    assert kept == [
        "Operates in the New York metropolitan area",
        "Manages assets valued at over $250 million",
    ]
    assert [b for b, _ in dropped] == [f"Firm described as {_ONELINER}"]
    assert "restates the firm_oneliner" in dropped[0][1]


def test_drop_bad_profile_bullets_catches_a_verbatim_duplicate_too():
    """A bullet identical to the oneliner with no prefix at all must still
    be caught -- this is a strict superset of the vendored guard's own
    exact-match behavior, not a replacement that narrows it."""
    bullets = ["Operates in the New York metropolitan area", _ONELINER]

    kept, _ = sd._drop_bad_profile_bullets(bullets, _ONELINER)

    assert kept == ["Operates in the New York metropolitan area"]


def test_drop_bad_profile_bullets_keeps_genuinely_distinct_bullets():
    bullets = ["Operates in the New York metropolitan area", "Founded in 1970"]

    kept, dropped = sd._drop_bad_profile_bullets(bullets, _ONELINER)

    assert kept == bullets
    assert dropped == []


def test_drop_bad_profile_bullets_handles_empty_oneliner():
    bullets = ["Operates in the New York metropolitan area"]

    assert sd._drop_bad_profile_bullets(bullets, "") == (bullets, [])


def test_drop_bad_profile_bullets_handles_no_bullets_at_all():
    assert sd._drop_bad_profile_bullets(None, _ONELINER) == ([], [])
    assert sd._drop_bad_profile_bullets([], _ONELINER) == ([], [])


def test_generate_deck_strips_the_duplicate_oneliner_bullet_before_build(monkeypatch):
    monkeypatch.setattr(
        sd.deck_filler, "get_deck_content",
        lambda firm_name, research, personalization: {
            "profile_bullets": [
                "Operates in the New York metropolitan area",
                f"Firm described as {_ONELINER}",
            ],
        },
    )
    captured = {}

    def fake_build_and_convert(firm_name, research, deck_content, progress=None, personalization=None):
        captured["profile_bullets"] = list(deck_content.get("profile_bullets") or [])
        return {"pptx_path": None, "pdf_path": "x.pdf", "fill_data": {}}

    monkeypatch.setattr(sd.deck_filler, "build_and_convert", fake_build_and_convert)

    sd._generate_deck("Choice NY", {"firm_oneliner": _ONELINER}, progress=lambda m: None)

    assert captured["profile_bullets"] == ["Operates in the New York metropolitan area"]


def test_generate_deck_leaves_bullets_alone_when_research_has_no_oneliner(monkeypatch):
    bullets = ["Operates in the New York metropolitan area", "Firm described as something"]
    monkeypatch.setattr(sd.deck_filler, "get_deck_content",
                        lambda firm_name, research, personalization: {"profile_bullets": list(bullets)})
    captured = {}

    def fake_build_and_convert(firm_name, research, deck_content, progress=None, personalization=None):
        captured["profile_bullets"] = list(deck_content.get("profile_bullets") or [])
        return {"pptx_path": None, "pdf_path": "x.pdf", "fill_data": {}}

    monkeypatch.setattr(sd.deck_filler, "build_and_convert", fake_build_and_convert)

    sd._generate_deck("Acme", {}, progress=lambda m: None)

    assert captured["profile_bullets"] == bullets


# ---------------------------------------------------------------------------
# _delete_empty_deck_shapes: run 27 follow-up, Choice NY + Neal Communities
# live evidence -- blanking a label's text run (the first version of this
# fix) left the card/footer CONTAINER shape still rendering as an empty
# beige box or navy bar. The whole shape sequence must be deleted instead.
# Fixture mirrors the real master's slide 3 structure exactly (verified
# against both real generated decks in generated_decks_c/ before writing
# this): an AUM card (Shape 4 + Text 5/6/7), a Founded card (Shape 8 +
# Text 9/10/11), and a capital-stack footer (Shape 12 + Text 13).
# ---------------------------------------------------------------------------
EMU_PER_INCH = 914400


def _xfrm(y_inches):
    """The shape's own <a:xfrm>, or a bare <p:spPr/> when y_inches is None
    (a shape with no explicit geometry -- reflow must leave those alone)."""
    if y_inches is None:
        return "<p:spPr/>"
    y = int(round(y_inches * EMU_PER_INCH))
    return (f'<p:spPr><a:xfrm><a:off x="457200" y="{y}"/>'
            f'<a:ext cx="2331720" cy="567" /></a:xfrm></p:spPr>')


def _shape(shape_id, name, text=None, y=None):
    body = "" if text is None else f'<p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody>'
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
           f'{_xfrm(y)}{body}</p:sp>')


def _pic(shape_id, name, y=None):
    """A slide-12 row icon. <p:pic>, not <p:sp> -- deleting and reflowing
    these with their row is the whole point of the element-type handling."""
    return (f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="{name}"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
           f'<p:blipFill><a:blip r:embed="rId2"/></p:blipFill>{_xfrm(y)}</p:pic>')


def _slide3_xml(aum_value="", aum_label="", aum_asof="", founded_year="", capital_stack="",
                extra_shapes="", geometry=False):
    """Mirrors the real master's slide 3 shape sequence exactly. `geometry`
    adds the master's own y offsets (in inches, from templates/
    Pitch_Master.pptx) so reflow can be exercised; without it every shape
    carries a bare <p:spPr/> and reflow must be skipped."""
    def y(v):
        return v if geometry else None
    return (
        "<p:sld>"
        + _shape(2, "Text 0", "SECTION 01", y=y(0.32))
        + _shape(6, "Shape 4", y=y(1.50))                                   # AUM card container
        + _shape(7, "Text 5", aum_value, y=y(1.62))
        + _shape(8, "Text 6", aum_label, y=y(2.06))
        + _shape(9, "Text 7", aum_asof, y=y(2.48))
        + _shape(10, "Shape 8", y=y(2.98))                                  # Founded card container
        + _shape(11, "Text 9", founded_year, y=y(3.10))
        + _shape(12, "Text 10", "Founded" if founded_year else "", y=y(3.54))
        + _shape(13, "Text 11", "Investing since" if founded_year else "", y=y(3.96))
        + _shape(14, "Shape 12", y=y(4.95))                                 # capital-stack footer container
        + _shape(15, "Text 13", capital_stack, y=y(4.95))
        + extra_shapes
        + "</p:sld>"
    )


# The real master's slide 12: five stacked row bars at these y offsets, each
# a roundRect container, a <p:pic> icon 0.15in below the bar's top, a static
# heading text box and the fit_paragraph_N body text box.
_SLIDE12_ROW_YS = (1.80, 2.54, 3.29, 4.03, 4.78)
_SLIDE12_HEADINGS = ("Scalable Property Accounting", "Complex Fund Structures",
                     "Tailored Investor Reporting", "Underwriting &amp; Acquisitions Support",
                     "Capital Markets Expertise")


def _slide12_xml(*bodies, extra_shapes="", geometry=True):
    """`bodies` is the five fit_paragraph_N values in order."""
    assert len(bodies) == 5
    names = (("Shape 3", "Image 0", "Text 4", "Text 5"),
             ("Shape 6", "Image 1", "Text 7", "Text 8"),
             ("Shape 9", "Image 2", "Text 10", "Text 11"),
             ("Shape 12", "Image 3", "Text 13", "Text 14"),
             ("Shape 15", "Image 4", "Text 16", "Text 17"))
    out = ["<p:sld>", _shape(2, "Text 0", "SECTION 04", y=0.32 if geometry else None)]
    shape_id = 5
    for (container, icon, heading_box, body_box), row_y, heading, body in zip(
            names, _SLIDE12_ROW_YS, _SLIDE12_HEADINGS, bodies):
        y = row_y if geometry else None
        icon_y = (row_y + 0.15) if geometry else None
        out.append(_shape(shape_id, container, y=y))
        out.append(_pic(shape_id + 1, icon, y=icon_y))
        out.append(_shape(shape_id + 2, heading_box, heading, y=y))
        out.append(_shape(shape_id + 3, body_box, body, y=y))
        shape_id += 4
    out.append(extra_shapes)
    out.append("</p:sld>")
    return "".join(out)


def _make_test_pptx(tmp_path, member_xml, member="ppt/slides/slide3.xml", name="test.pptx",
                    extra_members=None):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(member, member_xml)
        for extra_member, extra_xml in (extra_members or {}).items():
            z.writestr(extra_member, extra_xml)
    return path


def _shape_names(pptx_path, member="ppt/slides/slide3.xml"):
    with zipfile.ZipFile(pptx_path) as z:
        xml = z.read(member).decode("utf-8")
    return re.findall(r'<p:cNvPr id="\d+" name="([^"]*)"', xml)


def _shape_ys(pptx_path, member="ppt/slides/slide3.xml"):
    """{shape name: y offset in inches} for every shape that has geometry."""
    with zipfile.ZipFile(pptx_path) as z:
        xml = z.read(member).decode("utf-8")
    out = {}
    for match in re.finditer(r"<p:(sp|pic)>.*?</p:\1>", xml, re.DOTALL):
        block = match.group(0)
        name = re.search(r'<p:cNvPr id="\d+" name="([^"]*)"', block)
        off = re.search(r'<a:off x="-?\d+" y="(-?\d+)"', block)
        if name and off:
            out[name.group(1)] = round(int(off.group(1)) / EMU_PER_INCH, 2)
    return out


def _slide12_fill(*bodies):
    return {f"fit_paragraph_{i}": body for i, body in enumerate(bodies, start=1)}


def test_delete_empty_deck_shapes_neal_regression_no_disclosed_aum(tmp_path):
    """Neal Communities live evidence: no disclosed AUM at all -- the whole
    AUM card (container + all 3 content shapes) is removed; the Founded
    card (real founded_year) stays."""
    xml = _slide3_xml(aum_value="", aum_label="", aum_asof="", founded_year="1970", capital_stack="")
    path = _make_test_pptx(tmp_path, xml)

    changed = sd._delete_empty_deck_shapes(path, {
        "aum_value": "", "aum_label": "", "aum_asof": "", "founded_year": "1970", "capital_stack": "",
    })

    assert changed is True
    names = _shape_names(path)
    assert "Shape 4" not in names and "Text 5" not in names and "Text 6" not in names and "Text 7" not in names
    assert "Shape 8" in names and "Text 9" in names


def test_delete_empty_deck_shapes_choice_ny_regression_no_founding_year_or_capital_stack(tmp_path):
    """Choice NY live evidence: AUM is disclosed (card stays), founded_year
    and capital_stack are both empty (their card and footer both go)."""
    xml = _slide3_xml(aum_value="$250 million", aum_label="Assets Valued", aum_asof="",
                      founded_year="", capital_stack="")
    path = _make_test_pptx(tmp_path, xml)

    changed = sd._delete_empty_deck_shapes(path, {
        "aum_value": "$250 million", "aum_label": "Assets Valued", "aum_asof": "",
        "founded_year": "", "capital_stack": "",
    })

    assert changed is True
    names = _shape_names(path)
    assert "Shape 4" in names and "Text 5" in names                # AUM card stays -- real content
    assert "Shape 8" not in names and "Text 9" not in names        # Founded card gone
    assert "Text 10" not in names and "Text 11" not in names
    assert "Shape 12" not in names and "Text 13" not in names      # capital-stack footer gone


def test_delete_empty_deck_shapes_keeps_a_card_with_only_one_empty_field(tmp_path):
    """aum_asof blank but aum_value/aum_label populated is NOT "every value
    empty" -- the card must stay, matching the pre-existing, already-
    accepted behavior of a single blank caption line inside an otherwise
    populated card. All three containers survive; the only thing that goes
    is the Founded card's valueless "Investing since" line."""
    xml = _slide3_xml(aum_value="$4.4B", aum_label="Gross Asset Value", aum_asof="",
                      founded_year="2008", capital_stack="LP, GP")
    path = _make_test_pptx(tmp_path, xml)

    changed = sd._delete_empty_deck_shapes(path, {
        "aum_value": "$4.4B", "aum_label": "Gross Asset Value", "aum_asof": "",
        "founded_year": "2008", "capital_stack": "LP, GP",
    })

    assert changed is True
    names = _shape_names(path)
    assert "Shape 4" in names and "Shape 8" in names and "Shape 12" in names
    assert "Text 5" in names and "Text 9" in names and "Text 10" in names and "Text 13" in names
    assert "Text 11" not in names


def test_delete_empty_deck_shapes_drops_the_valueless_investing_since_line(tmp_path):
    """Live evidence, both decks: the Founded card's third text box reads
    "Investing since" with no value after it, because pitch_slots.json has
    no slot for it and nothing in either workflow ever fills it. It goes
    even when the card it belongs to is fully populated and stays."""
    xml = _slide3_xml(aum_value="$4.4B", aum_label="Gross Asset Value", aum_asof="as of Dec 31, 2025",
                      founded_year="1970", capital_stack="LP, GP")
    path = _make_test_pptx(tmp_path, xml)

    changed = sd._delete_empty_deck_shapes(path, {
        "aum_value": "$4.4B", "aum_label": "Gross Asset Value", "aum_asof": "as of Dec 31, 2025",
        "founded_year": "1970", "capital_stack": "LP, GP",
    })

    assert changed is True
    names = _shape_names(path)
    assert "Text 11" not in names                       # "Investing since", nothing ever fills it
    assert "Shape 8" in names and "Text 9" in names     # the card and its year are real, they stay
    assert "Text 10" in names                           # so is its "Founded" label


def test_delete_empty_deck_shapes_returns_false_when_everything_is_populated(tmp_path):
    """Slide 12 with all five fit paragraphs filled: nothing to delete,
    nothing to reflow, file left untouched. (A slide-3 fixture can't show
    this any more -- its valueless "Investing since" line always goes.)"""
    xml = _slide12_xml("b1", "b2", "b3", "b4", "b5")
    path = _make_test_pptx(tmp_path, xml, member="ppt/slides/slide12.xml")

    changed = sd._delete_empty_deck_shapes(path, _slide12_fill("b1", "b2", "b3", "b4", "b5"))

    assert changed is False


def test_delete_empty_deck_shapes_treats_none_fill_data_as_all_empty(tmp_path):
    path = _make_test_pptx(tmp_path, _slide3_xml())

    changed = sd._delete_empty_deck_shapes(path, None)

    assert changed is True
    assert _shape_names(path) == ["Text 0"]   # both cards and the footer deleted


def test_delete_empty_deck_shapes_is_atomic_per_stack(tmp_path):
    """A stack whose shape names can't ALL be uniquely resolved is left
    entirely alone -- not partially deleted. Partial deletion (content gone,
    an ambiguous container orphaned behind) would read worse on the slide
    than leaving the stack untouched, and reflow needs every slot position
    in the stack to be known before it can move anything. Caught in testing
    before this reached the codebase: an earlier, per-shape (non-atomic)
    version would have deleted "Text 5/6/7" here even with "Shape 4"
    ambiguous."""
    xml = _slide3_xml(aum_value="", aum_label="", aum_asof="", founded_year="1970", capital_stack="",
                      extra_shapes=_shape(66, "Shape 4"))   # duplicate AUM container name
    path = _make_test_pptx(tmp_path, xml)

    changed = sd._delete_empty_deck_shapes(path, {
        "aum_value": "", "aum_label": "", "aum_asof": "", "founded_year": "1970", "capital_stack": "",
    })

    assert changed is True   # the capital-stack footer is its own stack, still resolves fine
    names = _shape_names(path)
    assert names.count("Shape 4") == 2   # ambiguous AUM group untouched, including its content
    assert "Text 5" in names and "Text 6" in names and "Text 7" in names
    # the Founded card shares the ambiguous stack, so even its valueless
    # "Investing since" line is left alone rather than half-treated
    assert "Shape 8" in names and "Text 11" in names
    assert "Shape 12" not in names       # capital_stack empty, separate stack -- still deleted


# ---------------------------------------------------------------------------
# Slide 12 (SECTION 04) fit rows, and reflow. Live evidence: with the Part C
# retry declined, a genuinely-empty fit section leaves its bar rendering with
# a heading and no body -- Choice NY ships two of them, Neal one, and
# Workflow C's own Kingbird deck ships one, so there is no upstream behavior
# to inherit. Survivors must also close the gap the deleted row leaves.
# ---------------------------------------------------------------------------
def test_delete_empty_deck_shapes_deletes_an_empty_fit_row_whole(tmp_path):
    """Neal live evidence: fit_paragraph_2 came back empty, so the whole
    "Complex Fund Structures" row goes -- bar, icon and both text boxes."""
    xml = _slide12_xml("b1", "", "b3", "b4", "b5")
    path = _make_test_pptx(tmp_path, xml, member="ppt/slides/slide12.xml")

    changed = sd._delete_empty_deck_shapes(path, _slide12_fill("b1", "", "b3", "b4", "b5"))

    assert changed is True
    names = _shape_names(path, member="ppt/slides/slide12.xml")
    for gone in ("Shape 6", "Image 1", "Text 7", "Text 8"):
        assert gone not in names
    for kept in ("Shape 3", "Image 0", "Text 4", "Text 5", "Shape 9", "Shape 12", "Shape 15"):
        assert kept in names


def test_delete_empty_deck_shapes_reflows_fit_rows_with_no_gap(tmp_path):
    """The rows below a deleted one move up into the vacated slots, so the
    stack always reads from the top with no hole in it. Slot positions are
    the deck's own; a survivor only ever moves up."""
    xml = _slide12_xml("b1", "", "b3", "b4", "b5")
    path = _make_test_pptx(tmp_path, xml, member="ppt/slides/slide12.xml")

    sd._delete_empty_deck_shapes(path, _slide12_fill("b1", "", "b3", "b4", "b5"))

    ys = _shape_ys(path, member="ppt/slides/slide12.xml")
    slot1, slot2, slot3, slot4 = _SLIDE12_ROW_YS[:4]
    assert ys["Shape 3"] == slot1                       # row 1 already at the top, unmoved
    assert ys["Shape 9"] == slot2                       # row 3 -> slot 2
    assert ys["Shape 12"] == slot3                      # row 4 -> slot 3
    assert ys["Shape 15"] == slot4                      # row 5 -> slot 4
    # each row's heading, body and icon travel with its bar, icon still
    # sitting 0.15in below the bar's top edge
    assert ys["Text 10"] == slot2 and ys["Text 11"] == slot2
    assert ys["Image 2"] == round(slot2 + 0.15, 2)
    assert ys["Image 3"] == round(slot3 + 0.15, 2)
    assert ys["Image 4"] == round(slot4 + 0.15, 2)


def test_delete_empty_deck_shapes_reflows_choice_ny_two_empty_rows(tmp_path):
    """Choice NY live evidence: fit_paragraph_2 AND fit_paragraph_5 empty.
    Three survivors, packed into the first three slots."""
    xml = _slide12_xml("b1", "", "b3", "b4", "")
    path = _make_test_pptx(tmp_path, xml, member="ppt/slides/slide12.xml")

    changed = sd._delete_empty_deck_shapes(path, _slide12_fill("b1", "", "b3", "b4", ""))

    assert changed is True
    names = _shape_names(path, member="ppt/slides/slide12.xml")
    assert "Shape 6" not in names and "Image 1" not in names    # row 2 gone
    assert "Shape 15" not in names and "Image 4" not in names   # row 5 gone
    ys = _shape_ys(path, member="ppt/slides/slide12.xml")
    assert [ys["Shape 3"], ys["Shape 9"], ys["Shape 12"]] == list(_SLIDE12_ROW_YS[:3])


def test_delete_empty_deck_shapes_reflow_never_moves_a_row_down(tmp_path):
    """Only the LAST row is empty, so every survivor is already in its own
    slot and nothing moves. A survivor's target slot index can never exceed
    its own, which is what keeps reflow from pushing a shape off-slide."""
    xml = _slide12_xml("b1", "b2", "b3", "b4", "")
    path = _make_test_pptx(tmp_path, xml, member="ppt/slides/slide12.xml")

    sd._delete_empty_deck_shapes(path, _slide12_fill("b1", "b2", "b3", "b4", ""))

    ys = _shape_ys(path, member="ppt/slides/slide12.xml")
    assert [ys["Shape 3"], ys["Shape 6"], ys["Shape 9"], ys["Shape 12"]] == list(_SLIDE12_ROW_YS[:4])


def test_delete_empty_deck_shapes_reflows_a_marooned_stat_card(tmp_path):
    """Neal live evidence: the AUM card was deleted and left the Founded
    card stranded in slot 2 with an empty quadrant above it. The survivor
    now moves up into slot 1, its own text boxes keeping their offsets
    inside the card."""
    xml = _slide3_xml(aum_value="", aum_label="", aum_asof="", founded_year="1970",
                      capital_stack="", geometry=True)
    path = _make_test_pptx(tmp_path, xml)

    sd._delete_empty_deck_shapes(path, {
        "aum_value": "", "aum_label": "", "aum_asof": "", "founded_year": "1970", "capital_stack": "",
    })

    ys = _shape_ys(path)
    assert ys["Shape 8"] == 1.50                      # was 2.98, the AUM card's own slot
    assert ys["Text 9"] == 1.62                       # was 3.10, same 0.12in inset as before
    assert ys["Text 10"] == 2.06                      # was 3.54
    assert ys["Text 0"] == 0.32                       # not in the stack, never moves


def test_delete_empty_deck_shapes_skips_reflow_without_geometry(tmp_path):
    """A shape with no explicit <a:xfrm> inherits its position from the
    layout. Deletion still happens; reflow is skipped rather than guessed
    at, because there is no slot position to read."""
    xml = _slide3_xml(aum_value="", aum_label="", aum_asof="", founded_year="1970",
                      capital_stack="", geometry=False)
    path = _make_test_pptx(tmp_path, xml)

    changed = sd._delete_empty_deck_shapes(path, {
        "aum_value": "", "aum_label": "", "aum_asof": "", "founded_year": "1970", "capital_stack": "",
    })

    assert changed is True
    names = _shape_names(path)
    assert "Shape 4" not in names and "Shape 8" in names
    assert _shape_ys(path) == {}                      # nothing gained geometry it didn't have


def test_delete_empty_deck_shapes_keeps_slide_3_and_slide_12_stacks_apart(tmp_path):
    """"Shape 12", "Text 13" and "Text 5" name DIFFERENT shapes on slide 3
    and slide 12 -- the capital-stack footer vs the fourth fit row, the AUM
    figure vs the first row's body. Each stack resolves its own slide from
    pitch_slots.json, so an empty capital_stack must not touch slide 12's
    row 4 and a filled row 4 must not save slide 3's footer."""
    fill = {"aum_value": "$250 million", "aum_label": "Assets Valued", "aum_asof": "",
            "founded_year": "", "capital_stack": "", **_slide12_fill("b1", "b2", "b3", "b4", "b5")}
    path = _make_test_pptx(
        tmp_path,
        _slide3_xml(aum_value="$250 million", aum_label="Assets Valued", geometry=True),
        extra_members={"ppt/slides/slide12.xml": _slide12_xml("b1", "b2", "b3", "b4", "b5")},
    )

    changed = sd._delete_empty_deck_shapes(path, fill)

    assert changed is True
    slide3 = _shape_names(path)
    assert "Shape 12" not in slide3 and "Text 13" not in slide3   # footer: capital_stack empty
    assert "Shape 4" in slide3 and "Text 5" in slide3             # AUM card: real figure
    slide12 = _shape_names(path, member="ppt/slides/slide12.xml")
    assert "Shape 12" in slide12 and "Text 13" in slide12         # row 4 filled, untouched
    assert "Text 5" in slide12                                    # row 1 body, untouched


def test_delete_empty_deck_shapes_scopes_deletion_to_the_correct_slide_only(tmp_path):
    """Regression: these autogenerated shape names ("Text 5", "Shape 8",
    ...) are NOT unique across the whole presentation -- every slide's own
    shapes restart around the same low numbers. An earlier draft of this
    fix, caught in testing before it ever reached the codebase, matched
    shape names across EVERY slide.xml in the deck and deleted unrelated
    content elsewhere."""
    xml = _slide3_xml(aum_value="", aum_label="", aum_asof="", founded_year="1970", capital_stack="")
    other_slide_xml = "<p:sld>" + _shape(99, "Text 5", "unrelated content on another slide") + "</p:sld>"
    path = _make_test_pptx(tmp_path, xml, extra_members={"ppt/slides/slide7.xml": other_slide_xml})

    sd._delete_empty_deck_shapes(path, {
        "aum_value": "", "aum_label": "", "aum_asof": "", "founded_year": "1970", "capital_stack": "",
    })

    with zipfile.ZipFile(path) as z:
        other_xml = z.read("ppt/slides/slide7.xml").decode("utf-8")
    assert "unrelated content on another slide" in other_xml
    assert "Text 5" in other_xml   # untouched, even though slide3's own "Text 5" was deleted


def test_generate_deck_reconverts_to_pdf_after_deleting_empty_shapes(tmp_path, monkeypatch):
    xml = _slide3_xml(aum_value="", aum_label="", aum_asof="", founded_year="1970", capital_stack="")
    pptx_path = _make_test_pptx(tmp_path, xml)
    monkeypatch.setattr(sd.deck_filler, "get_deck_content",
                        lambda firm_name, research, personalization: {"profile_bullets": []})
    monkeypatch.setattr(
        sd.deck_filler, "build_and_convert",
        lambda firm_name, research, deck_content, progress=None, personalization=None: {
            "pptx_path": pptx_path, "pdf_path": "stale.pdf",
            "fill_data": {"aum_value": "", "aum_label": "", "aum_asof": "",
                         "founded_year": "1970", "capital_stack": ""},
        },
    )
    convert_calls = []
    monkeypatch.setattr(sd.deck_filler, "convert_to_pdf",
                        lambda path, progress=None: convert_calls.append(path) or "fresh.pdf")

    result = sd._generate_deck("Acme Capital", {}, progress=lambda m: None)

    assert result == "fresh.pdf"
    assert convert_calls == [pptx_path]
    assert "Shape 4" not in _shape_names(pptx_path)


def test_generate_deck_skips_reconversion_when_nothing_needed_deleting(tmp_path, monkeypatch):
    xml = _slide12_xml("b1", "b2", "b3", "b4", "b5")
    pptx_path = _make_test_pptx(tmp_path, xml, member="ppt/slides/slide12.xml")
    fill_data = _slide12_fill("b1", "b2", "b3", "b4", "b5")
    monkeypatch.setattr(sd.deck_filler, "get_deck_content",
                        lambda firm_name, research, personalization: {"profile_bullets": []})
    monkeypatch.setattr(
        sd.deck_filler, "build_and_convert",
        lambda firm_name, research, deck_content, progress=None, personalization=None: {
            "pptx_path": pptx_path, "pdf_path": "original.pdf", "fill_data": fill_data,
        },
    )
    convert_calls = []
    monkeypatch.setattr(sd.deck_filler, "convert_to_pdf",
                        lambda path, progress=None: convert_calls.append(path) or "should-not-be-used.pdf")

    result = sd._generate_deck("Acme Capital", {}, progress=lambda m: None)

    assert result == "original.pdf"
    assert convert_calls == []


def test_generate_deck_falls_back_to_original_pdf_when_shape_cleanup_raises(monkeypatch):
    """A shape-cleanup failure (e.g. an inaccessible file) must ship the
    deck's original PDF, never crash the draft."""
    monkeypatch.setattr(sd.deck_filler, "get_deck_content",
                        lambda firm_name, research, personalization: {"profile_bullets": []})
    monkeypatch.setattr(
        sd.deck_filler, "build_and_convert",
        lambda firm_name, research, deck_content, progress=None, personalization=None: {
            "pptx_path": "does/not/exist.pptx", "pdf_path": "original.pdf",
            "fill_data": {"aum_value": "", "aum_label": "", "aum_asof": "",
                         "founded_year": "", "capital_stack": ""},
        },
    )
    progressed = []

    result = sd._generate_deck("Acme Capital", {}, progress=progressed.append)

    assert result == "original.pdf"
    assert any("empty-shape cleanup failed" in msg for msg in progressed)


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


def test_draft_for_run_no_email_when_no_poc_hint_and_senior_search_finds_nothing(monkeypatch):
    """No scanner hint at all now falls back to wd_poc.find_senior_poc
    (closes the gap the old reason described as unbuildable). When THAT
    also finds nothing, the reason must say both were tried, not read like
    the firm simply has no one to contact."""
    firms = [_firm(1, "Firm A")]
    postings = {1: [{"title": "Fund Controller", "url": "https://x.example", "poc_name_hint": None,
                     "poc_designation_hint": None}]}
    _patch_common(monkeypatch, firms, postings, {})  # senior_poc_hits defaults to no hit

    result = sd.draft_for_run(run_id=1)

    assert len(result.no_email) == 1
    assert result.drafted == []
    reason = result.no_email[0]["no_email_reason"]
    assert "no POC name hint from the scanner" in reason
    assert "senior-finance-title search also found no verified contact" in reason
    assert "not implemented" not in reason  # the gap is closed now


def test_draft_for_run_no_email_when_hint_unresolved_and_senior_search_finds_nothing(monkeypatch):
    """A distinct reason from the no-hint case: there WAS a candidate name
    from the scanner, apollo_enrich couldn't resolve it, AND the
    senior-finance-title fallback also found nothing."""
    firms = [_firm(1, "Firm A")]
    postings = {1: [_posting(poc="Poc A")]}
    _patch_common(monkeypatch, firms, postings, {})  # no email in the fixture map, no senior hit

    result = sd.draft_for_run(run_id=1)

    assert len(result.no_email) == 1
    reason = result.no_email[0]["no_email_reason"]
    assert "Poc A" in reason
    assert "could not resolve an email" in reason
    assert "senior-finance-title search also found no verified contact" in reason


def test_draft_for_run_falls_back_to_senior_poc_search_when_hint_missing(monkeypatch):
    """The new fallback path succeeding: no scanner hint, but
    wd_poc.find_senior_poc finds a verified senior finance contact."""
    firms = [_firm(1, "Firm A")]
    postings = {1: [{"title": "Fund Controller", "url": "https://x.example", "poc_name_hint": None,
                     "poc_designation_hint": None}]}
    hits = {"Firm A": ("Alex Kim", "alex@firma.example", "Chief Financial Officer")}
    _patch_common(monkeypatch, firms, postings, {}, senior_poc_hits=hits)

    result = sd.draft_for_run(run_id=1)

    assert len(result.drafted) == 1
    assert result.no_email == []
    row = result.drafted[0]
    assert row["poc_name"] == "Alex Kim"
    assert row["poc_email"] == "alex@firma.example"
    assert row["poc_title"] == "Chief Financial Officer"
    assert row["poc_source"] == "apollo_search"


def test_draft_for_run_falls_back_to_senior_poc_search_when_hint_email_unresolved(monkeypatch):
    """The scanner hint exists but apollo_enrich can't resolve an email for
    it -- the senior-finance-title search still gets a chance."""
    firms = [_firm(1, "Firm A")]
    postings = {1: [_posting(poc="Poc A")]}  # hint present, no email in the fixture map
    hits = {"Firm A": ("Alex Kim", "alex@firma.example", "Controller")}
    _patch_common(monkeypatch, firms, postings, {}, senior_poc_hits=hits)

    result = sd.draft_for_run(run_id=1)

    assert len(result.drafted) == 1
    row = result.drafted[0]
    assert row["poc_name"] == "Alex Kim"  # replaced by the senior-search hit, not "Poc A"
    assert row["poc_source"] == "apollo_search"


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


def test_draft_for_run_attaches_the_deck_when_generation_succeeds(monkeypatch):
    """End-to-end: a successful _generate_deck() result must reach the Gmail
    attachment, the wd_drafts row, AND Block 6's wording -- the single
    deck_pdf_path variable that drives all three (see _draft_one_firm)."""
    firms = [_firm(1, "Firm A")]
    postings = {1: [_posting(poc="Jane Doe")]}
    emails = {"Firm A": ("jane@x.example", "verified")}
    created, recorded = _patch_common(monkeypatch, firms, postings, emails)
    monkeypatch.setattr(sd, "_generate_deck",
                        lambda firm_name, research, progress: "generated_decks_c/Firm_A_Pitch.pdf")
    gmail_calls = []
    monkeypatch.setattr(sd.gmail_client, "create_draft",
                        lambda to, subject, body, attach_path=None, progress=None:
                        gmail_calls.append(attach_path) or {"draft_id": f"DRAFT-{to}", "attached": True})

    result = sd.draft_for_run(run_id=1)

    assert len(result.drafted) == 1
    row = result.drafted[0]
    assert row["deck_pdf_path"] == "generated_decks_c/Firm_A_Pitch.pdf"
    assert row["deck_attached"] is True
    assert gmail_calls == ["generated_decks_c/Firm_A_Pitch.pdf"]
    assert "The deck is attached." in row["body"]


def test_draft_for_run_resets_and_reports_fallback_counts(monkeypatch):
    firms = [_firm(1, "Firm A")]
    postings = {1: [_posting(poc="Jane Doe")]}
    emails = {"Firm A": ("jane@x.example", "verified")}
    _patch_common(monkeypatch, firms, postings, emails)
    sd._fallback_counts["stale_from_a_previous_run"] = 99

    result = sd.draft_for_run(run_id=1)

    assert "stale_from_a_previous_run" not in result.fallback_counts


# ---------------------------------------------------------------------------
# POC email domain cross-check (run-29 funnel audit).
#
# Run 27 drafted to riqbal@alphax.ae for a firm the gate had resolved as
# alphax-capital.com. The geo TLD backstop in signal_pipeline.py cannot catch
# this -- it checks the GATE's domain, which was a plain .com and passed. The
# mismatch only exists between the gate's domain and the CONTACT's.
#
# The country test runs BEFORE the label test on purpose, and that ordering is
# what makes this catch AlphaX at all: _firm_matches("alphax", "alphax
# capital") is TRUE ("capital" is a _TOLERABLE_EXTRAS business descriptor),
# which is correct for firm names and would have downgraded the real incident
# to a warning. Verified against the live wd_drafts rows before the ordering
# was chosen.
# ---------------------------------------------------------------------------
def test_poc_domain_alphax_regression_blocks():
    """The exact run-27 rows: gate own_domain alphax-capital.com, Apollo
    contact riqbal@alphax.ae."""
    verdict = sd.poc_domain_mismatch_reason(
        "riqbal@alphax.ae", {"own_domain": "alphax-capital.com"}, "AlphaX")

    assert verdict is not None
    severity, message = verdict
    assert severity == "block"
    assert "alphax.ae" in message and "alphax-capital.com" in message
    assert "United Arab Emirates" in message


def test_poc_domain_alphax_would_have_only_warned_on_the_label_alone():
    """Documents WHY the country test runs first. The two labels genuinely
    read as the same firm through _firm_matches, so label-only ordering would
    have drafted to the UAE contact with a warning."""
    assert sd.wd_poc._firm_matches("alphax", "alphax capital") is True


@pytest.mark.parametrize("email,gate_domain", [
    ("drew.donovan@choicenewyork.com", "choicenewyork.com"),   # live run-27 draft
    ("pneal@nealcommunities.com", "nealcommunities.com"),      # live run-27 draft
])
def test_poc_domain_passes_the_two_run_27_drafts_that_were_correct(email, gate_domain):
    """Both correct run-27 drafts must stay clean -- this check may not cost
    a real draft."""
    assert sd.poc_domain_mismatch_reason(email, {"own_domain": gate_domain}, "Firm") is None


@pytest.mark.parametrize("email", [
    "a@acme.com",             # identical
    "a@mail.acme.com",        # subdomain, same registrable label
    "a@ACME.COM",             # case
    "a@acme.ca",              # Canadian regional domain: North American, allowed
    "a@acme.us",
])
def test_poc_domain_no_question_raised(email):
    assert sd.poc_domain_mismatch_reason(email, {"own_domain": "acme.com"}, "Acme") is None


@pytest.mark.parametrize("email", [
    "principal@gmail.com", "founder@outlook.com", "cfo@yahoo.com", "x@icloud.com",
    "y@protonmail.com",
])
def test_poc_domain_ignores_public_mailboxes(email):
    """A real principal at a small firm legitimately uses a personal mailbox.
    That is a personal-address question, not a wrong-company one, and
    blocking on it would cost real drafts for no evidence."""
    assert sd.poc_domain_mismatch_reason(email, {"own_domain": "acme.com"}, "Acme") is None


@pytest.mark.parametrize("research", [
    {}, None, {"own_domain": ""}, {"domain": None}, {"own_domain": None, "domain": ""},
])
def test_poc_domain_needs_a_gate_domain_to_compare_against(research):
    assert sd.poc_domain_mismatch_reason("a@anything.com", research, "Acme") is None


@pytest.mark.parametrize("email", ["", None, "not-an-email", "  "])
def test_poc_domain_handles_a_missing_or_malformed_email(email):
    assert sd.poc_domain_mismatch_reason(email, {"own_domain": "acme.com"}, "Acme") is None


def test_poc_domain_warns_on_a_plausible_affiliate_domain():
    """A sibling domain whose core still reads as the same firm is a warning,
    not a block -- real firms run a "<firm>-capital.com" for the investment
    arm."""
    verdict = sd.poc_domain_mismatch_reason(
        "a@acme-capital.com", {"own_domain": "acme.com"}, "Acme")

    assert verdict is not None
    severity, message = verdict
    assert severity == "warn"
    assert "drafted anyway" in message


def test_poc_domain_blocks_an_unrelated_domain():
    verdict = sd.poc_domain_mismatch_reason(
        "a@totallyunrelated.com", {"own_domain": "acme.com"}, "Acme")

    assert verdict is not None
    assert verdict[0] == "block"


@pytest.mark.parametrize("email", ["a@acme.co.uk", "a@acme.in", "a@acme.sg", "a@acme.de"])
def test_poc_domain_blocks_a_foreign_domain_even_when_the_label_matches(email):
    """The AlphaX lesson generalized: a label matching perfectly does not make
    a contact in another country an affiliate."""
    verdict = sd.poc_domain_mismatch_reason(email, {"own_domain": "acme.com"}, "Acme")

    assert verdict is not None
    assert verdict[0] == "block"


def test_poc_domain_falls_back_to_domain_when_own_domain_is_absent():
    assert sd.poc_domain_mismatch_reason(
        "a@acme.com", {"domain": "acme.com"}, "Acme") is None
    assert sd.poc_domain_mismatch_reason(
        "a@other.com", {"domain": "acme.com"}, "Acme")[0] == "block"


@pytest.mark.parametrize("domain,expected", [
    ("acme.com", "acme"),
    ("www.acme.com", "acme"),
    ("ir.sonicautomotive.com", "sonicautomotive"),
    ("alphax-capital.com", "alphax capital"),
    ("acme.co.uk", "acme"),
    ("acme.com.au", "acme"),
    ("acme", "acme"),
    ("", ""),
])
def test_domain_core_reduces_to_the_registrable_label(domain, expected):
    assert sd._domain_core(domain) == expected


# ---------------------------------------------------------------------------
# _draft_one_firm wiring: a block must stop the draft BEFORE any deck or LLM
# spend, and must surface as its own bucket.
# ---------------------------------------------------------------------------
def _wire_poc(monkeypatch, email, research, deck_calls, draft_calls):
    # poc_name comes off the POSTING rows, not the firm dict -- an earlier
    # version of this helper put the hint on the firm, which left poc_name
    # None and fell through to the UNPATCHED wd_poc.find_senior_poc, i.e. the
    # live Apollo API (see the warning on the older POC tests above).
    monkeypatch.setattr(sd.dbc, "postings_for_firm",
                        lambda firm_id: [{"title": "Controller", "url": "https://x.example/1",
                                         "poc_name_hint": "Rao Iqbal",
                                         "poc_designation_hint": "CFO"}])
    monkeypatch.setattr(sd.apollo_enrich, "find_email", lambda **kw: (email, "verified"))
    monkeypatch.setattr(sd.wd_poc, "find_senior_poc",
                        lambda *a, **kw: pytest.fail("find_senior_poc must not be reached"))
    monkeypatch.setattr(sd.dbc, "find_prior_contact", lambda **kw: None)

    def fake_generate_deck(*a, **kw):
        deck_calls.append(a)
        return None

    def fake_draft_email(**kw):
        draft_calls.append(kw)
        return {"subject": "s", "body": "b", "word_count": 1,
                "thin_personalization": False, "fallback_stage": None,
                "fallback_reason": None}

    monkeypatch.setattr(sd, "_generate_deck", fake_generate_deck)
    monkeypatch.setattr(sd, "draft_email", fake_draft_email)
    return {"id": 1, "firm_name": "AlphaX", "research": research}


def test_draft_one_firm_blocks_on_a_poc_domain_mismatch(monkeypatch):
    deck_calls, draft_calls = [], []
    firm = _wire_poc(monkeypatch, "riqbal@alphax.ae",
                     {"own_domain": "alphax-capital.com"}, deck_calls, draft_calls)
    progressed = []

    bucket, row = sd._draft_one_firm(firm, set(), progressed.append)

    assert bucket == "poc_domain_mismatch"
    assert "alphax.ae" in row["poc_domain_mismatch_reason"]
    assert row["poc_email"] == "riqbal@alphax.ae"
    assert any("alphax.ae" in msg for msg in progressed)
    # nothing was spent: no deck generated, no email drafted
    assert deck_calls == [] and draft_calls == []


def test_draft_one_firm_proceeds_through_an_affiliate_warning(monkeypatch):
    """A warning logs and drafts. It must NOT land in the mismatch bucket."""
    deck_calls, draft_calls = [], []
    firm = _wire_poc(monkeypatch, "a@acme-capital.com", {"own_domain": "acme.com"},
                     deck_calls, draft_calls)
    monkeypatch.setattr(sd.dbc, "create_wd_draft", lambda firm_id, **f: {"id": 9, **f})
    monkeypatch.setattr(sd.dbc, "record_contacted", lambda **kw: None)
    monkeypatch.setattr(sd.gmail_client, "create_draft",
                        lambda to, subject, body, attach_path=None, progress=None:
                        {"draft_id": f"DRAFT-{to}", "attached": False})
    progressed = []

    bucket, _ = sd._draft_one_firm(firm, set(), progressed.append)

    assert bucket == "drafted"
    assert any("drafted anyway" in msg for msg in progressed)
    assert draft_calls, "the email must still be drafted on a warning"


def test_draft_batch_result_has_a_poc_domain_mismatch_bucket():
    assert sd.DraftBatchResult().poc_domain_mismatch == []



# ---------------------------------------------------------------------------
# Slide-01 profile bullet guards. Every bullet string below is copied out of a
# real deck in generated_decks_c/ or referral-system/generated_decks_c/, and
# every research value out of the matching wd_firms row.
#
# The stat-tile rule that briefly lived here (commit 8624538) is GONE. It
# dropped "Founded in 1970" and "Disclosed AUM: $700 million" as restatements
# of their own tiles, which stripped Neal to three bullets and a visibly empty
# lower slide. Reverted on the operator's call; recoverable from that commit
# if it is ever wanted behind a flag.
# ---------------------------------------------------------------------------
_NEAL_ONELINER = ("Homebuilder/developer focusing on single-family and townhome "
                  "communities in Southwest Florida")
# Neal's research blob, wd_firms id 72, verbatim on the fields these rules read.
_NEAL_RESEARCH = {
    "firm_oneliner": _NEAL_ONELINER,
    "founded_year": "1970",
    "aum_display": "$700 million",
    "disclosed_figure": "$700 million",
    "disclosed_label": "AUM",
    "geography": "Southwest Florida (Sarasota/Lakewood Ranch), US",
    "recent_event": "Article noting $1 billion annual revenue (Business Observer, Apr 2024)",
    "aum_value_usd": 700000000,
}
# Raptor Group, wd_firms id 78: research that states its figure as an
# intention in its own right. A forward-looking bullet here is supported.
_RAPTOR_RESEARCH = {
    "recent_event": "Raptor Digital seeking $200M fund (reported 2024-2025 period)",
    "aum_display": "$200 million (fund target / fund size (Raptor Digital))",
    "disclosed_figure": "$200 million",
    "disclosed_label": "fund target / fund size (Raptor Digital)",
}


# --- Rule 1: headline restatement, with the raised floor -------------------
def test_oneliner_near_exact_restatement_still_drops():
    """The live Neal case: the headline minus its trailing " in Southwest
    Florida". 72 of 93 normalized characters, ratio 0.774."""
    bullet = "Homebuilder/developer focusing on single-family and townhome communities"

    assert sd._is_oneliner_restatement(bullet, _NEAL_ONELINER) is True


@pytest.mark.parametrize("bullet", [
    # Each shares a clause with the headline but is a narrower fact of its
    # own. The first floor (any containment over 30 chars) ate these; the
    # ratio floor keeps them.
    "Homebuilder/developer focusing on single-family",
    "single-family and townhome communities",
    "focusing on single-family and townhome",
])
def test_oneliner_clause_sharing_bullets_now_survive(bullet):
    assert sd._is_oneliner_restatement(bullet, _NEAL_ONELINER) is False


def test_oneliner_clause_sharing_ratio_is_measured_not_assumed():
    """The two live measurements the 0.70 floor sits between."""
    near = sd._norm_for_oneliner_compare(
        "Homebuilder/developer focusing on single-family and townhome communities")
    head = sd._norm_for_oneliner_compare(_NEAL_ONELINER)
    assert near in head
    assert (len(near) / len(head)) > sd._MIN_ONELINER_OVERLAP_RATIO

    clause_head = sd._norm_for_oneliner_compare(
        "Multifamily-focused real estate investment manager with $4.4B in gross "
        "asset value across US secondary markets")
    clause = sd._norm_for_oneliner_compare("Multifamily-focused real estate investment manager")
    assert clause in clause_head
    assert (len(clause) / len(clause_head)) < sd._MIN_ONELINER_OVERLAP_RATIO


def test_oneliner_exact_and_prefix_forms_drop_regardless_of_ratio():
    """Not judgement calls: an exact duplicate and a "Firm described as X"
    duplicate go whatever the ratio says."""
    assert sd._is_oneliner_restatement(_ONELINER, _ONELINER) is True
    assert sd._is_oneliner_restatement(f"Firm described as {_ONELINER}", _ONELINER) is True


@pytest.mark.parametrize("bullet", ["Multifamily", "Southwest Florida", "Homebuilder"])
def test_oneliner_short_bullets_survive_incidental_containment(bullet):
    assert sd._is_oneliner_restatement(bullet, _NEAL_ONELINER) is False


@pytest.mark.parametrize("oneliner", ["", None, "   "])
def test_oneliner_rule_needs_a_oneliner(oneliner):
    assert sd._is_oneliner_restatement("anything at all here", oneliner) is False


def test_stat_tile_rule_is_gone():
    """Regression guard on the revert itself: Workflow C's Kingbird deck keeps
    "Founded in 2008"-style bullets next to their own tiles, so this project
    must not reintroduce a rule that strips them."""
    assert not hasattr(sd, "_is_stat_tile_restatement")
    assert not hasattr(sd, "_stat_tile_comparands")

    kept, dropped = sd._drop_bad_profile_bullets(
        ["Founded in 1970", "Disclosed AUM: $700 million"], _NEAL_ONELINER, _NEAL_RESEARCH)

    assert kept == ["Founded in 1970", "Disclosed AUM: $700 million"]
    assert dropped == []


# --- Rule 2: the bullet describes the deck, not the firm -------------------
@pytest.mark.parametrize("bullet", [
    "AUM displayed as $700 million",           # live Neal bullet
    "Founded year displayed as 1970",
    "Revenue shown as $1 billion",
    "AUM as displayed is $700 million",
    "Figures on this slide are approximate",
    "See the deck for portfolio detail",
    "Value appears on this slide",
    "The stat tile shows $700 million",
])
def test_describes_the_deck_is_dropped(bullet):
    assert sd._describes_the_deck(bullet) is True


@pytest.mark.parametrize("bullet", [
    "Operates in Southwest Florida (Sarasota/Lakewood Ranch), US",
    "Listed as one of the fastest-growing builders in Florida",
    "Displays homes at three design centers",       # "displays" with no as/on/in
    "Was sold to Associa Corp. in 2021 with an earn-out noted",
    "Manages a portfolio valued at $250 million (assets valued)",
])
def test_real_facts_are_not_deck_self_description(bullet):
    assert sd._describes_the_deck(bullet) is False


# --- Rule 3: forward-looking substitution ---------------------------------
def test_forward_looking_substitution_is_dropped():
    """The live Neal bullet. research["recent_event"] says the $1 billion was
    NOTED as annual revenue; the bullet turns it into a target."""
    bullet = "Reportedly targeting $1 billion annual revenue (Business Observer, Apr 2024)"

    reason = sd._misframes_a_research_figure(bullet, _NEAL_RESEARCH)

    assert reason is not None
    assert "1B" in reason
    assert "Article noting" in reason


@pytest.mark.parametrize("bullet", [
    "Reported $1 billion annual revenue in Apr 2024 article",   # the honest phrasing
    "Operates in Southwest Florida (Sarasota/Lakewood Ranch), US",
    "Founded in 1970",
])
def test_no_forward_looking_marker_means_no_drop(bullet):
    assert sd._misframes_a_research_figure(bullet, _NEAL_RESEARCH) is None


@pytest.mark.parametrize("bullet", [
    "Seeking $200M for its digital fund",
    "Targeting a $200M fund",
])
def test_forward_looking_is_kept_when_research_frames_it_that_way(bullet):
    """The Raptor Group control. Its disclosed_figure is a bare "$200
    million" while its aum_display says "fund target" -- checking research
    fields one at a time and dropping on the first bare one flagged this
    wrongly, which is how the any/all bug was caught."""
    assert sd._misframes_a_research_figure(bullet, _RAPTOR_RESEARCH) is None


def test_forward_looking_with_a_figure_absent_from_research_is_left_to_grounding():
    """Scoped deliberately: this rule judges FRAMING of a figure the research
    carries. A figure research has never heard of is the vendored
    ungrounded-claim guard's job, not this one's."""
    assert sd._misframes_a_research_figure(
        "Targeting $5 billion in unrelated revenue", _NEAL_RESEARCH) is None


def test_forward_looking_with_no_figure_at_all_is_left_alone():
    assert sd._misframes_a_research_figure(
        "Targeting further expansion across the Southeast", _NEAL_RESEARCH) is None


@pytest.mark.parametrize("research", [{}, None])
def test_forward_looking_handles_empty_research(research):
    assert sd._misframes_a_research_figure("Targeting $1 billion revenue", research) is None


def test_research_text_values_flattens_strings_and_string_lists():
    values = sd._research_text_values({
        "a": "plain", "b": ["one", "two"], "c": 700000000, "d": "", "e": None,
        "f": {"nested": "ignored"},
    })

    assert sorted(values) == ["one", "plain", "two"]


# --- all three together, on the real builds -------------------------------
def test_drop_bad_bullets_current_neal_build():
    """The Neal deck as regenerated at 16:17: one good bullet, one deck
    self-description, one forward-looking substitution."""
    bullets = [
        "Operates in Southwest Florida (Sarasota/Lakewood Ranch), US",
        "Reportedly targeting $1 billion annual revenue (Business Observer, Apr 2024)",
        "AUM displayed as $700 million",
    ]

    kept, dropped = sd._drop_bad_profile_bullets(bullets, _NEAL_ONELINER, _NEAL_RESEARCH)

    assert kept == ["Operates in Southwest Florida (Sarasota/Lakewood Ranch), US"]
    assert [b for b, _ in dropped] == bullets[1:]
    assert "unsupported" in dropped[0][1]
    assert "describes the deck" in dropped[1][1]


def test_drop_bad_bullets_current_choice_build_keeps_all_five():
    """Choice NY's five bullets are all real facts about the firm. With the
    stat-tile rule reverted, none of them goes -- including the AUM bullet
    that rule used to strip."""
    bullets = [
        "Operates as a third-party residential & mixed-use property manager",
        "Manages a portfolio valued at $250 million (assets valued)",
        "Focuses on properties in the New York metropolitan area",
        "Website domain is choicenewyork.com",
        "Was sold to Associa Corp. in 2021 with an earn-out noted",
    ]
    research = {"firm_oneliner": "Residential & mixed-use property management, third-party operator",
               "aum_display": "$250 million", "disclosed_figure": "$250 million",
               "disclosed_label": "assets valued",
               "recent_event": "sold to Associa Corp. in 2021 (earn-out mentioned)"}

    kept, dropped = sd._drop_bad_profile_bullets(bullets, research["firm_oneliner"], research)

    assert kept == bullets
    assert dropped == []


def test_drop_bad_bullets_kingbird_reference_keeps_all_six():
    """The quality reference: six bullets including a founded-year restatement
    and a gross-asset-value restatement, all retained."""
    bullets = [
        "Vertically integrated real estate investment manager with over a century of family office heritage.",
        "Manages $4.4 billion in gross asset value as of December 31, 2025.",
        "Founded in 2008",
        "Specializes in multifamily workforce housing through ventures with local operating partners.",
        "Appointed Director of Capital Markets in 2019 to expand investment services.",
        "Acts as fiduciary for a family office and third-party investors.",
    ]
    research = {"firm_oneliner": "Kingbird Investment Management is a test firm.",
               "founded_year": "2008", "aum_display": "$4.4B",
               "disclosed_figure": "$4.4B", "disclosed_label": "Gross Asset Value"}

    kept, dropped = sd._drop_bad_profile_bullets(bullets, research["firm_oneliner"], research)

    assert kept == bullets
    assert dropped == []


@pytest.mark.parametrize("bullets", [[], None])
def test_drop_bad_bullets_handles_no_bullets(bullets):
    assert sd._drop_bad_profile_bullets(bullets, _NEAL_ONELINER, _NEAL_RESEARCH) == ([], [])


def test_drop_bad_bullets_without_research_applies_only_the_first_two_rules():
    bullets = ["Reportedly targeting $1 billion annual revenue", "AUM displayed as $700 million"]

    kept, dropped = sd._drop_bad_profile_bullets(bullets, _NEAL_ONELINER, None)

    assert kept == ["Reportedly targeting $1 billion annual revenue"]
    assert len(dropped) == 1


def test_generate_deck_logs_every_dropped_bullet_with_its_reason(monkeypatch):
    """HARD RULE 4: a dropped block is logged with stage and reason, never
    silently."""
    seen, progressed = {}, []
    monkeypatch.setattr(sd.deck_filler, "get_deck_content",
                        lambda firm_name, research, personalization: {
                            "profile_bullets": [
                                "Operates in Southwest Florida (Sarasota/Lakewood Ranch), US",
                                "Reportedly targeting $1 billion annual revenue (Business Observer, Apr 2024)",
                                "AUM displayed as $700 million"],
                            "fit_paragraphs": {}})

    def fake_build_and_convert(firm_name, research, deck_content, progress=None, personalization=None):
        seen["bullets"] = list(deck_content["profile_bullets"])
        return {"pptx_path": None, "pdf_path": "deck.pdf", "fill_data": {}}

    monkeypatch.setattr(sd.deck_filler, "build_and_convert", fake_build_and_convert)

    result = sd._generate_deck("Neal Communities of Southwest Florida, Inc.",
                               _NEAL_RESEARCH, progress=progressed.append)

    assert result == "deck.pdf"
    assert seen["bullets"] == ["Operates in Southwest Florida (Sarasota/Lakewood Ranch), US"]
    assert any("profile bullet dropped" in m and "describes the deck" in m for m in progressed)
    assert any("profile bullet dropped" in m and "unsupported" in m for m in progressed)


def test_generate_deck_no_longer_precomputes_fill_data(monkeypatch):
    """The stat-tile rule was the only reason to call build_fill_data() before
    build_and_convert(); with it gone, that duplicated call (and its doubled
    [DECK EMPTY]/[DECK RETRY] log lines) must be gone too."""
    calls = []
    monkeypatch.setattr(sd.deck_filler, "get_deck_content",
                        lambda firm_name, research, personalization: {
                            "profile_bullets": ["Operates in Southwest Florida"], "fit_paragraphs": {}})
    monkeypatch.setattr(sd.deck_filler, "build_fill_data",
                        lambda *a, **kw: calls.append(a) or {})
    monkeypatch.setattr(
        sd.deck_filler, "build_and_convert",
        lambda firm_name, research, deck_content, progress=None, personalization=None: {
            "pptx_path": None, "pdf_path": "deck.pdf", "fill_data": {}})

    sd._generate_deck("Neal", _NEAL_RESEARCH, progress=lambda m: None)

    assert calls == []
