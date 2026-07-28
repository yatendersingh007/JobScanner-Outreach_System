"""Phase 5a for Workflow D: turns a qualified firm plus its posting(s) into a
Gmail draft, against templates/signal_email.md (CLAUDE.md HARD RULE 4/5).

Reuses referral-system/src/email_drafter.py's generate -> validate -> retry
-> fallback ARCHITECTURE (that file is deliberately NOT vendored -- see
DRIFT.md -- because its FIXED_SUBJECT and fixed blocks assert an
introduction from Manpreet Singh that does not exist for a scanned lead).
This module's content is original: its own forbidden-claim set, its own
required-fact set, and its own Block 4 argument check, because this
template has no referral to fabricate and a different offering to state.

DO NOT CHANGE: lib_referral/fact_check.py, templates/signal_email.md's text.
"""
from __future__ import annotations

import json as _json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from lib_referral import apollo_enrich, config as gate_config, fact_check, gmail_client, testmode
from . import wd_config as config
from . import wd_dbc as dbc

log = logging.getLogger("workflow-d.signal_drafting")

Progress = Callable[[str], None]


def _noop(_: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Fixed blocks (BUILD item 1): Block 1 and Block 6 are assembled in PYTHON,
# never LLM-written -- the posting title, the firm name, and the posting URL
# are the facts that must never be wrong, and the only way to guarantee that
# is to never let a model retype them. Block 3 and Block 5 are also fixed
# (never LLM-written) and are hardcoded here too, character-for-character
# from templates/signal_email.md's own BLOCK 1/3/5/6 email-content lines --
# NOT parsed from the template file the way referral's simpler fixed blocks
# are. Decision (recorded in BUILD_LOG.md): this template's BLOCK 1 and
# BLOCK 3 sections each carry trailing developer-facing prose in the same
# section ("This block is assembled in Python...", "This is the deck's own
# pre-approved language...") that a generic header-to-header parser would
# have to know to strip; a wrong strip silently ships commentary as email
# text. Hardcoding fails more visibly: a stale literal is wrong on read, not
# wrong at runtime. A template edit to these blocks' wording requires
# updating these literals to match.
# ---------------------------------------------------------------------------
_BLOCK_3 = (
    "A US fully loaded hire for that seat runs $145K to $180K. We place a "
    "dedicated senior operator on your team for $55K to $75K, exclusively "
    "yours, embedded in your systems and your close calendar, live in 10 days."
)
_BLOCK_5 = (
    "Can we do a call next week? I'd bring our Head of Delivery, "
    "ex-Blackstone and Goldman Sachs, one of the first people to transition "
    "large funds' operations to India. Thirty minutes with him is useful "
    "even if we never work together."
)
_FALLBACK_BLOCK_4 = (
    "The search takes three months and the close does not pause while you "
    "run it. Most firms bridge it by paying a provider whose partners never "
    "open their ledger, or by pushing it onto a controller who is already at "
    "capacity. Both cost more than the seat."
)

# BUILD item 6 / FIX 29 landmine: without the offering stated explicitly and
# exhaustively in the generation prompt, the model invents PropTech.
OFFERING = (
    "property-level books and month-end close, bank reconciliations, AP/AR "
    "and tenant billing, CAM reconciliations and true-ups, budget vs actual "
    "variance reporting, lender and covenant packages, owner distributions "
    "and monthly owner reports, across Yardi, RealPage, and Entrata"
)


def _subject(posting_title: str, posting_count: int) -> str:
    if posting_count > 1:
        return f"Your {posting_count} open finance roles"
    return f"Your {posting_title} opening"


def block_1(poc_first_name: str, firm_short: str, posting_title: str, posting_count: int) -> str:
    greeting = f"Hi {poc_first_name or 'there'},"
    if posting_count > 1:
        signal = (f"You have {posting_count} finance roles open at {firm_short} "
                  f"right now, including {posting_title}. I run X Analyst. We "
                  "are the alternative to that hire.")
    else:
        signal = (f"You have a {posting_title} open at {firm_short}. I run X "
                  "Analyst. We are the alternative to that hire.")
    return f"{greeting}\n\n{signal}"


def block_6(posting_url: str) -> str:
    return ("Harp\nFounder, X Analyst\n\n"
            f"P.S. The deck is attached. The posting is here if I have the wrong one: {posting_url}")


_LEGAL_SUFFIX_DISPLAY_RE = re.compile(
    r",?\s+(LLC|L\.L\.C\.?|Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Company|"
    r"LP|L\.P\.?|LLP|L\.L\.P\.?|Ltd\.?|Limited|PLC|PLLC|PC)\.?\s*$",
    re.IGNORECASE,
)


def firm_short(firm_name: str) -> str:
    """Display-cased common name, legal suffix stripped. Mechanical, not
    LLM-derived (the template's own note describes it as "LLM-derived" --
    Workflow D has no separate personalization-research phase to derive it
    from, a scope decision recorded in BUILD_LOG.md). Strips a single
    trailing legal form only; anything else about the name is left alone."""
    stripped = _LEGAL_SUFFIX_DISPLAY_RE.sub("", firm_name or "").strip()
    return stripped or (firm_name or "").strip()


_WS_RE = re.compile(r"\s+")


def _norm_title(title: str) -> str:
    return _WS_RE.sub(" ", (title or "").strip().lower())


def distinct_titles(postings: list[dict]) -> list[str]:
    """Dedup on normalized title, not on posting rows -- the scanner's
    dedup_key is namespaced per source, so one real posting found by two
    connectors survives as two rows. See CLAUDE.md's dedup_key landmine."""
    seen, out = set(), []
    for p in postings:
        raw = p.get("title") or ""
        t = _norm_title(raw)
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(raw.strip())
    return out


# ---------------------------------------------------------------------------
# Grounding corpus (BUILD item 2): the gate's research dict PLUS the posting
# facts -- exact title, firm name, posting URL, distinct posting count.
# fact_check.grounding_corpus is reused unchanged (vendored, generic).
# ---------------------------------------------------------------------------
def grounding_corpus(research: dict, firm_name: str, posting_title: str, posting_url: str,
                     titles: list[str], posting_count: int) -> str:
    posting_facts = {
        "firm_name": firm_name,
        "posting_title": posting_title,
        "posting_titles": titles,
        "posting_url": posting_url,
        "posting_count": posting_count,
    }
    return fact_check.grounding_corpus(research or {}, posting_facts)


# ---------------------------------------------------------------------------
# Required-fact checks (BUILD item 3): drafting fails without these. Block 1
# and Block 6 are Python-assembled so these can only fail if a caller passes
# a posting_title/firm_short/posting_url that has drifted from the actual
# posting record -- e.g. a reworded title -- which is exactly the defect
# this check exists to catch mechanically rather than trust by construction.
# ---------------------------------------------------------------------------
def find_required_fact_violations(block1_text: str, block6_text: str, block3_text: str,
                                  posting_title: str, firm_short_name: str, posting_url: str,
                                  corpus_text: str) -> list[str]:
    v = []
    if not posting_title or posting_title not in block1_text:
        v.append("missing_posting_title_in_block1")
    if not posting_title or posting_title not in corpus_text:
        v.append("posting_title_not_grounded")
    if not firm_short_name or firm_short_name not in block1_text:
        v.append("missing_firm_name_in_block1")
    if not posting_url or posting_url not in block6_text:
        v.append("missing_posting_url_in_block6")
    if block3_text != _BLOCK_3:
        v.append("block3_modified")
    elif "$145K to $180K" not in block3_text or "$55K to $75K" not in block3_text:
        v.append("missing_dollar_ranges_in_block3")
    return v


# ---------------------------------------------------------------------------
# Style violations. Banned phrase/word lists copied verbatim from
# referral-system/src/email_drafter.py's _BANNED_PHRASES/_BANNED_WORDS, per
# templates/signal_email.md rule 4: "Same banned phrase and banned word
# lists" as referral_email.md. Duplicated rather than imported because
# email_drafter.py is deliberately not vendored (see module docstring).
# ---------------------------------------------------------------------------
_BANNED_PHRASES = [
    "i noticed", "i came across", "i was impressed", "it's clear that",
    "exciting opportunity", "unique opportunity", "great opportunity",
    "i wanted to reach out", "i'd love to connect", "at the intersection of",
    "when it comes to", "in today's market",
]
_BANNED_WORDS = [
    "leverage", "optimize", "streamline", "synergy", "unlock", "empower",
    "crucial", "pivotal", "vital", "landscape", "robust", "comprehensive",
    "holistic", "innovative", "cutting-edge", "enhance", "foster", "cultivate",
    "showcase", "underscore", "highlight", "delve", "navigate", "spearhead",
    "bolster", "garner", "resonate", "seamless", "transformative",
    "groundbreaking", "strategic", "scalable", "tailored", "bespoke", "key",
]
_WORD_RE = {w: re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in _BANNED_WORDS}

# New for Workflow D: CLAUDE.md bans "not just X, it's Y" outright, and no
# substring check can express a pattern with two free variables. Matches
# "not/isn't/is not" + "just/merely/only", then requires the contrastive
# "it's/it is/but" to land before the sentence ends -- a "not just X" that
# never completes the cliche (sentence just ends) does not fire.
_NOT_JUST_X_ITS_Y_RE = re.compile(
    r"\b(?:not|isn'?t|is\s+not)\s+(?:just|merely|only)\b[^.?!]{0,60}?\b(?:it'?s|it\s+is|but)\b",
    re.IGNORECASE,
)


def find_style_violations(text: str) -> list[str]:
    v = []
    if "—" in text or "--" in text:
        v.append("em_dash")
    if ";" in text:
        v.append("semicolon")
    if "“" in text or "”" in text or "‘" in text or "’" in text:
        v.append("curly_quotes")
    if "?" in text:
        v.append("question_mark")
    if _NOT_JUST_X_ITS_Y_RE.search(text):
        v.append("not_just_x_its_y")
    low = text.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in low:
            v.append(f"banned_phrase:{phrase}")
    for word, rx in _WORD_RE.items():
        if rx.search(text):
            v.append(f"banned_word:{word}")
    return v


# ---------------------------------------------------------------------------
# Forbidden claims (BUILD item 4). Any hit is a HARD FAILURE, never a retry,
# never a patched sentence -- a cold email claiming a referral or a prior
# contact is the exact integrity failure this template exists to prevent,
# so the check is mechanical, not a prompt instruction. Built adversarially
# against the test matrix in tests/test_signal_drafting.py.
#
# "introduction": the one pattern that needs a negative lookahead. Bare
# "introduc*" would also fire on "introduction to our model" (a legitimate
# sales-pitch usage the template's own near-miss list requires NOT to fire).
# The lookahead excludes only "introduction to our/my <company-facing
# noun>", the narrow shape of that legitimate usage -- everything else
# ("an introduction", "introduced by", "introduction to you", "introduction
# to the team") still fires. Deliberately asymmetric: a false positive here
# costs one unnecessary fallback (HARD RULE 5 territory); a false negative
# ships a fabricated referral claim.
# ---------------------------------------------------------------------------
_FORBIDDEN_CLAIM_PATTERNS: dict[str, re.Pattern] = {
    "manpreet_mention": re.compile(r"\bmanpreet\w*\b", re.IGNORECASE),
    "m_singh_obfuscation": re.compile(r"\bm\.?\s*singh\b", re.IGNORECASE),
    "singh_capital": re.compile(r"\bsingh\s+capital\b", re.IGNORECASE),
    "referral_word": re.compile(r"\breferrals?\b|\breferred\b|\breferring\b", re.IGNORECASE),
    "mutual_connection": re.compile(r"\bmutual\s+connections?\b", re.IGNORECASE),
    "connected_origin_claim": re.compile(
        r"\b(?:we|you\s+and\s+i)\s+were\s+connected\b|\bconnected\s+(?:through|via|by)\b",
        re.IGNORECASE,
    ),
    "network_origin_claim": re.compile(
        r"\b(?:came\s+up|showed\s+up|surfaced)\s+in\s+(?:our|my|your)\s+network\b|"
        r"\bsomeone\s+in\s+(?:our|my|your)\s+network\b",
        re.IGNORECASE,
    ),
    "colleague_attribution": re.compile(
        r"\b(?:a\s+)?colleague\s+(?:recommended|suggested|mentioned|referred)\b", re.IGNORECASE,
    ),
    "prior_contact_claim": re.compile(
        r"\bwe\s+(?:have\s+)?(?:spoke|spoken|talked|connected|been\s+in\s+touch)\b[^.?!]{0,40}\b"
        r"(?:before|previously|earlier)\b|"
        r"\bas\s+we\s+discussed\b|\bfollowing\s+up\s+on\s+(?:our|my)\s+(?:call|conversation|chat)\b",
        re.IGNORECASE,
    ),
    "introduction_claim": re.compile(
        r"\bintroduc\w*\b(?!\s+to\s+(?:our|my)\s+(?:model|service|approach|offering|process|"
        r"program|platform|way|solution))",
        re.IGNORECASE,
    ),
}


def find_forbidden_claims(text: str) -> list[str]:
    return [name for name, rx in _FORBIDDEN_CLAIM_PATTERNS.items() if rx.search(text)]


# ---------------------------------------------------------------------------
# Grounding (reused, unchanged logic from fact_check.py) -- PROMPTS.md's own
# item 4 lists "any figure about the firm not in the corpus, including a
# computed saving" under FORBIDDEN CLAIMS, not under the retry-eligible
# checks referral treats it as. Decision: an ungrounded numeric claim is
# HARD here, same tier as forbidden_claims, not a soft/retryable violation --
# a fabricated number is as much an integrity failure as a fabricated
# referral for a cold email whose entire premise is "we know your business".
# ---------------------------------------------------------------------------
def find_grounding_violations(text: str, corpus_text: str) -> list[str]:
    return [f"ungrounded_claim:{c}" for c in sorted(fact_check.unverifiable_claims(text, corpus_text))]


def find_redundant_claims(block2: str, block4: str) -> list[str]:
    shared = fact_check.extract_numeric_claims(block2) & fact_check.extract_numeric_claims(block4)
    return [f"redundant_claim:{c}" for c in sorted(shared)]


# FIX 10 lineage, adapted (decision recorded in BUILD_LOG.md as mine, not a
# template rule): only require a figure when research actually discloses
# one. An AUM_ESTIMATED firm with a units proxy has no dollar figure and the
# template explicitly says invent none, so demanding one would force exactly
# the fabrication this check exists to prevent. Uses disclosed_figure only,
# NOT aum_display -- icp_gate.py's own research dict comment marks
# aum_display "legacy/operator-view-only," superseded by disclosed_figure/
# disclosed_label; email_drafter.py's aum_display fallback predates that
# split and Workflow D has no reason to carry it forward.
def find_missing_required_facts(combined_text: str, research: dict) -> list[str]:
    research = research or {}
    required_source = str(research.get("disclosed_figure") or "").strip()
    if not required_source:
        return []
    required = fact_check.extract_numeric_claims(required_source)
    if not required:
        return []
    present = fact_check.extract_numeric_claims(combined_text)
    missing = required - present
    return [f"missing_required_aum:{c}" for c in sorted(missing)]


# Reused unchanged from email_drafter.py's find_missing_temporal_framing --
# generic (aum_tag/proxy_type/proxy_basis/founded_year are icp_gate.py
# fields, not Workflow-C-specific content).
def find_missing_temporal_framing(combined_text: str, research: dict) -> list[str]:
    research = research or {}
    aum_tag = str(research.get("aum_tag") or "").upper()
    proxy_type = str(research.get("proxy_type") or "").strip().lower()
    proxy_basis = str(research.get("proxy_basis") or "").lower()
    founded_year = str(research.get("founded_year") or "").strip()
    is_invested_capital_proxy = (
        "ESTIMATED" in aum_tag and proxy_type != "gav"
        and ("invested capital" in proxy_basis or "deployed" in proxy_basis)
    )
    if not (is_invested_capital_proxy and founded_year):
        return []
    if founded_year in combined_text:
        return []
    return [f"missing_temporal_framing:{founded_year}"]


# ---------------------------------------------------------------------------
# Block 4 argument (BUILD item 4 user addition): two elements of Workflow
# D's own, not referral's provider-cost/internal-burden pitch.
#
# (a) role_connection: block4 must reference a DISTINCTIVE word from the
#     ACTUAL posting title, not any role noun -- otherwise a CAM analyst
#     opening passes a paragraph written about a fund controller. Generic
#     seniority/corporate words are stripped before matching so "Senior Fund
#     Controller" and "Fund Controller" match the same way.
# (b) concrete_cost: names a concrete cost (whose night, what breaks, how
#     long the seat stays empty), not an abstract risk ("risks disrupting
#     reporting" fails review per the template's own bad example).
# ---------------------------------------------------------------------------
_GENERIC_ROLE_WORDS = {
    "senior", "junior", "staff", "lead", "principal", "associate", "assistant",
    "corporate", "regional", "the", "a", "an", "of", "and", "for", "i", "ii", "iii",
}


def _distinctive_title_words(posting_title: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]+", (posting_title or "").lower())
    return {w for w in words if w not in _GENERIC_ROLE_WORDS and len(w) > 2}


def find_missing_role_connection(block4: str, posting_title: str) -> list[str]:
    distinctive = _distinctive_title_words(posting_title)
    if not distinctive:
        return []
    low = block4.lower()
    if any(re.search(rf"\b{re.escape(w)}\w*", low) for w in distinctive):
        return []
    return ["missing_role_connection"]


_CONCRETE_COST_SIGNAL_RE = re.compile(
    r"\b(nights?|weekends?|stays?\s+empty|empty\s+seat|takes?\s+(?:three|two|\d+)\s+months?|"
    r"close\s+does\s+not\s+pause|misses?\s+(?:a|the)\s+close|backlog|delays?|delayed|"
    r"breaks?\s+first|costs?\s+(?:more|you)|every\s+close|month-end\s+crunch)\b",
    re.IGNORECASE,
)


def find_missing_concrete_cost(block4: str) -> list[str]:
    if _CONCRETE_COST_SIGNAL_RE.search(block4):
        return []
    return ["missing_concrete_cost"]


def find_missing_block4_argument(block4: str, posting_title: str) -> list[str]:
    return find_missing_role_connection(block4, posting_title) + find_missing_concrete_cost(block4)


# ---------------------------------------------------------------------------
# Fallback telemetry (BUILD item 5 / HARD RULE 4). The donor's own
# reset_fallback_counts() docstring admits nothing outside email_drafter.py
# ever calls it at a batch-run boundary; draft_for_run() below is that
# wiring, calling reset at the top of every run and reporting the aggregate
# via DraftBatchResult.fallback_counts, which run_scan.py folds into the
# Telegram summary.
# ---------------------------------------------------------------------------
_fallback_counts: dict[str, int] = {}


def reset_fallback_counts() -> None:
    _fallback_counts.clear()


def fallback_counts() -> dict[str, int]:
    return dict(_fallback_counts)


def _record_fallback(reasons: list[str]) -> None:
    for reason in reasons:
        _fallback_counts[reason] = _fallback_counts.get(reason, 0) + 1


def _fallback_blocks(research: dict) -> tuple[str, str]:
    """HARD RULE 5: an honest blank beats a fabricated sentence. Referral's
    own ultimate fallback line ("Your firm came up in Manpreet's network...")
    is forbidden content for this template -- reusing it would fabricate the
    exact claim this module's forbidden-claims check exists to block. If
    firm_oneliner is itself empty, Block 2 becomes "" and draft_email() omits
    it from the assembled body entirely rather than ship a generic filler
    sentence (the template's own self-check: "could you swap in any firm
    name and it still reads? If yes, Block 2 is filler")."""
    oneliner = str(research.get("firm_oneliner") or "").strip()
    return oneliner, _FALLBACK_BLOCK_4


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s]


def _drop_trailing_sentences(text: str, words_to_cut: int) -> str:
    """Drop whole trailing sentences until under the cut target, or until
    only one remains. Never truncates mid-sentence."""
    sentences = _sentences(text)
    while len(sentences) > 1 and words_to_cut > 0:
        last_len = len(sentences[-1].split())
        sentences.pop()
        words_to_cut -= last_len
    return " ".join(sentences)


def _trim_to_budget(block2: str, block4: str, fixed_word_count: int,
                    block4_is_fixed: bool = False) -> tuple[str, str]:
    """Length guard at config.EMAIL_MAX_WORDS. Trim Block 4 first, then
    Block 2, whole sentences only. `block4_is_fixed` exempts the fixed
    fallback paragraph from trimming (Harp's own fixed text, not a free
    variable) -- Block 2 absorbs the whole cut instead, same as
    email_drafter.py's identical exemption."""
    def word_count(s: str) -> int:
        return len(s.split())

    if block4_is_fixed:
        total = fixed_word_count + word_count(block2) + word_count(block4)
        if total > config.EMAIL_MAX_WORDS:
            over = total - config.EMAIL_MAX_WORDS
            block2 = _drop_trailing_sentences(block2, over)
        return block2, block4

    total = fixed_word_count + word_count(block2) + word_count(block4)
    if total <= config.EMAIL_MAX_WORDS:
        return block2, block4

    over = total - config.EMAIL_MAX_WORDS
    new_block4 = _drop_trailing_sentences(block4, over)
    over -= word_count(block4) - word_count(new_block4)
    block4 = new_block4
    if over > 0:
        block2 = _drop_trailing_sentences(block2, over)
    return block2, block4


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
_GENERATE_PROMPT = """You are writing two short paragraphs (Block 2 and Block 4) of a cold email for X Analyst, from Harp, to a point of contact at {firm_name} about their open {posting_title} posting.

X Analyst sells embedded senior offshore finance professionals. The offering, and ONLY this offering: {offering}. Never call it software, a platform, or PropTech. Never invent a different offering.

BLOCK 2 (1-2 sentences, 15-30 words): firm-specific context proving we know their actual business. Draw only on the research object below. Every number copied verbatim, never re-derived, never rounded. If aum_tag is AUM_ESTIMATED with proxy_type "units", there is no dollar figure -- state the quantity itself, invent no dollar amount. If aum_tag is AUM_ESTIMATED with an invested-capital proxy, frame it with "since {founded_year}". No compliments, no "I noticed", no "I came across".

BLOCK 4 (2-3 sentences, 30-50 words): map the {posting_title} role to what our operators do (from the offering list above), then name a concrete cost of the alternative -- whose night it costs, what breaks first, how long the seat stays empty. Not an abstract risk. Do not repeat a number Block 2 already used.

FORBIDDEN, anywhere in either block: any mention of a referral, an introduction, a mutual connection, being connected to someone, or anyone named Manpreet or Singh Capital. Any claim of prior contact with this firm. Any invented figure not in the research object below.

No em dashes, no semicolons, straight quotes only. Never write "not just X, it's Y" or any variant of that construction.

Research object (every claim in Block 2 must trace to one of these facts):
{research_json}

Return a SINGLE JSON object, no prose, no markdown fence:
{{"block_2": "...", "block_4": "..."}}
"""

_RETRY_PROMPT = """You are rewriting {retry_target} of a cold email for X Analyst about {firm_name}'s open {posting_title} posting. A previous draft was rejected by an automated check. Rewrite ONLY {retry_target}, fixing the flagged problem(s) below, following every rule below.

X Analyst sells embedded senior offshore finance professionals. The offering, and ONLY this offering: {offering}. Never call it software, a platform, or PropTech.

FORBIDDEN, anywhere: any mention of a referral, an introduction, a mutual connection, being connected to someone, or anyone named Manpreet or Singh Capital. Any claim of prior contact. Any invented figure not in the research object below. No em dashes, no semicolons, straight quotes only, never "not just X, it's Y".

{kept_context}Flagged problem(s):
{violation_summary}

Research object (every claim must trace to one of these facts):
{research_json}

Return a SINGLE JSON object, no prose, no markdown fence, with ONLY:
{{{json_keys}}}
"""


def _capture(model_name: str, text: str, finish_reason: str, reasoning_tokens: int) -> None:
    """FIX 15 landmine: log finish_reason/reasoning_tokens so a reasoning-
    budget-exhaustion failure (empty response, finish_reason='length') is
    diagnosable rather than silently retried into an escalation."""
    if finish_reason == "length" or not text.strip():
        print(f"[SIGNAL DRAFT WARNING] {model_name} returned finish_reason={finish_reason!r} "
              f"reasoning_tokens={reasoning_tokens} response_chars={len(text)} -- possible "
              "reasoning-budget exhaustion.")


def _classify_violations(block2: str, block4: str, research: dict, firm_name: str,
                         posting_title: str, corpus_text: str,
                         stage: str) -> tuple[list[str], list[str], bool, bool]:
    """Returns (block2_violations, block4_violations, block2_hard, block4_hard).
    forbidden_claims and grounding are HARD (never retried); everything else
    is soft (one retry per block)."""
    combined_text = f"{block2} {block4}"
    checks = [
        ("forbidden_claim", find_forbidden_claims(block2), block2, "block2", True),
        ("forbidden_claim", find_forbidden_claims(block4), block4, "block4", True),
        ("grounding", find_grounding_violations(block2, corpus_text), block2, "block2", True),
        ("grounding", find_grounding_violations(block4, corpus_text), block4, "block4", True),
        ("style", find_style_violations(block2), block2, "block2", False),
        ("style", find_style_violations(block4), block4, "block4", False),
        ("redundancy", find_redundant_claims(block2, block4),
         f"block2={block2!r} block4={block4!r}", "block4", False),
        ("missing_required_fact", find_missing_required_facts(combined_text, research),
         combined_text, "block2", False),
        ("temporal_framing", find_missing_temporal_framing(combined_text, research),
         combined_text, "block2", False),
        ("block4_argument", find_missing_block4_argument(block4, posting_title), block4, "block4", False),
    ]
    block2_v, block4_v = [], []
    block2_hard = block4_hard = False
    for category, found, offending_text, owner, is_hard in checks:
        if not found:
            continue
        bucket = block2_v if owner == "block2" else block4_v
        bucket.extend(found)
        if is_hard:
            if owner == "block2":
                block2_hard = True
            else:
                block4_hard = True
        print(f"[SIGNAL FALLBACK] {firm_name}: {category} violation ({', '.join(found)}) "
              f"-- offending text: {offending_text!r} [{stage}]")
    return block2_v, block4_v, block2_hard, block4_hard


def _build_retry_prompt(firm_name: str, posting_title: str, research_json: str,
                        retry_block2: bool, retry_block4: bool,
                        block2: str, block4: str,
                        block2_violations: list[str], block4_violations: list[str]) -> str:
    targets = [name for name, requested in (("Block 2", retry_block2), ("Block 4", retry_block4)) if requested]
    retry_target = " and ".join(targets)

    kept_lines = []
    if not retry_block2:
        kept_lines.append(f'Block 2 (already correct -- keep as context, do not rewrite it): "{block2}"')
    if not retry_block4:
        kept_lines.append(f'Block 4 (already correct -- keep as context, do not rewrite it): "{block4}"')
    kept_context = ("\n".join(kept_lines) + "\n\n") if kept_lines else ""

    violation_lines = []
    if retry_block2:
        violation_lines.append(f"Block 2 ({', '.join(block2_violations)}): {block2!r}")
    if retry_block4:
        violation_lines.append(f"Block 4 ({', '.join(block4_violations)}): {block4!r}")

    json_keys = ", ".join(
        f'"block_{n}": "..."' for n, requested in (("2", retry_block2), ("4", retry_block4)) if requested
    )
    return _RETRY_PROMPT.format(
        retry_target=retry_target, firm_name=firm_name, posting_title=posting_title,
        offering=OFFERING, kept_context=kept_context,
        violation_summary="\n".join(violation_lines), research_json=research_json,
        json_keys=json_keys,
    )


def _generate_blocks(firm_name: str, research: dict, posting_title: str, posting_url: str,
                     titles: list[str], posting_count: int,
                     progress: Progress = _noop) -> tuple[str, str, bool, bool]:
    """Returns (block_2, block_4, block2_is_fallback, block4_is_fallback).

    forbidden_claim / grounding violations are HARD: that block goes
    straight to fallback on ANY pass, first or post-retry, never retried a
    second time. Everything else is soft: one retry per violating block,
    the already-clean block passed back as fixed context and never
    re-requested."""
    corpus_text = grounding_corpus(research, firm_name, posting_title, posting_url, titles, posting_count)

    if config.TEST_MODE:
        fixture = testmode.email_blocks_fixture(firm_name)
        if fixture:
            return fixture["block_2"], fixture["block_4"], False, False
        b2, b4 = _fallback_blocks(research)
        return b2, b4, not bool(b2), True

    from lib_snapshot import models

    research_json = _json.dumps(research or {}, default=str, ensure_ascii=False)
    prompt = _GENERATE_PROMPT.format(
        firm_name=firm_name, posting_title=posting_title, offering=OFFERING,
        founded_year=research.get("founded_year") or "", research_json=research_json,
    )
    parsed, usage = models.complete_json_retry(
        prompt, temperature=0.6, max_tokens=400, debug_capture=_capture, reasoning_effort="minimal",
    )
    block2 = (parsed.get("block_2") or "").strip()
    block4 = (parsed.get("block_4") or "").strip()

    b2v, b4v, b2_hard, b4_hard = _classify_violations(
        block2, block4, research, firm_name, posting_title, corpus_text, "first-pass")
    if not b2v and not b4v:
        return block2, block4, False, False

    retry_block2 = bool(b2v) and not b2_hard
    retry_block4 = bool(b4v) and not b4_hard

    if b2_hard:
        msg = f"{firm_name}: Block 2 hard failure ({', '.join(b2v)}) -- no retry, falling back. [first-pass]"
        print(f"[SIGNAL FALLBACK] {msg}")
        progress(msg)
    if b4_hard:
        msg = f"{firm_name}: Block 4 hard failure ({', '.join(b4v)}) -- no retry, falling back. [first-pass]"
        print(f"[SIGNAL FALLBACK] {msg}")
        progress(msg)

    tokens_so_far = getattr(usage, "total_tokens", 0) or 0
    skip_retry = tokens_so_far >= config.MAX_LLM_TOKENS_PER_FIRM
    if skip_retry and (retry_block2 or retry_block4):
        msg = (f"{firm_name}: skipping retry (token budget already at/over "
               f"{config.MAX_LLM_TOKENS_PER_FIRM}), falling back per-block.")
        print(f"[SIGNAL FALLBACK] {msg}")
        progress(msg)

    if not retry_block2 and not retry_block4 or skip_retry:
        _record_fallback(b2v)
        _record_fallback(b4v)
        fb2, fb4 = _fallback_blocks(research)
        final_block2 = block2 if not b2v else fb2
        final_block4 = block4 if not b4v else fb4
        return final_block2, final_block4, bool(b2v), bool(b4v)

    retry_prompt = _build_retry_prompt(firm_name, posting_title, research_json,
                                       retry_block2, retry_block4, block2, block4, b2v, b4v)
    retry_parsed, _retry_usage = models.complete_json_retry(
        retry_prompt, temperature=0.6, max_tokens=400, debug_capture=_capture, reasoning_effort="minimal",
    )
    new_block2 = (retry_parsed.get("block_2") or "").strip() if retry_block2 else block2
    new_block4 = (retry_parsed.get("block_4") or "").strip() if retry_block4 else block4

    nb2v, nb4v, _nb2_hard, _nb4_hard = _classify_violations(
        new_block2, new_block4, research, firm_name, posting_title, corpus_text, "post-retry")
    # Hard failures from the first pass that were never retried still count
    # as fallback outcomes for the block they hit.
    all_b2v = b2v if b2_hard else nb2v
    all_b4v = b4v if b4_hard else nb4v

    if all_b2v:
        msg = f"{firm_name}: Block 2 fell back ({', '.join(all_b2v)})."
        print(f"[SIGNAL FALLBACK] {msg}")
        progress(msg)
        _record_fallback(all_b2v)
    if all_b4v:
        msg = f"{firm_name}: Block 4 fell back ({', '.join(all_b4v)})."
        print(f"[SIGNAL FALLBACK] {msg}")
        progress(msg)
        _record_fallback(all_b4v)

    fb2, fb4 = _fallback_blocks(research)
    final_block2 = new_block2 if not all_b2v else fb2
    final_block4 = new_block4 if not all_b4v else fb4
    return final_block2, final_block4, bool(all_b2v), bool(all_b4v)


def draft_email(firm_name: str, poc_first_name: str, poc_email: str, posting_title: str,
                posting_url: str, titles: list[str], posting_count: int,
                firm_short_name: str, research: dict, progress: Progress = _noop) -> dict:
    """Entry point for one firm. Returns {subject, to, body,
    thin_personalization, word_count, block_2, block_4}."""
    b1 = block_1(poc_first_name, firm_short_name, posting_title, posting_count)
    b3 = _BLOCK_3
    b5 = _BLOCK_5
    b6 = block_6(posting_url)
    corpus_text = grounding_corpus(research, firm_name, posting_title, posting_url, titles, posting_count)

    req_violations = find_required_fact_violations(
        b1, b6, b3, posting_title, firm_short_name, posting_url, corpus_text)
    if req_violations:
        # Should be unreachable given Python assembly above -- this is the
        # defensive backstop for a caller passing drifted facts, per FIX 10's
        # own philosophy: don't just trust construction, verify it happened.
        raise ValueError(f"{firm_name}: required-fact check failed: {', '.join(req_violations)}")

    block2, block4, b2_fallback, b4_fallback = _generate_blocks(
        firm_name, research, posting_title, posting_url, titles, posting_count, progress)

    fixed_word_count = sum(len(b.split()) for b in (b1, b3, b5, b6) if b)
    block2, block4 = _trim_to_budget(block2, block4, fixed_word_count, block4_is_fixed=b4_fallback)

    body = "\n\n".join(b for b in (b1, block2, b3, block4, b5, b6) if b.strip())
    word_count = len(body.split())
    if word_count > config.EMAIL_MAX_WORDS:
        progress(f"{firm_name}: email still over {config.EMAIL_MAX_WORDS} words "
                 f"({word_count}) after trim -- shipping anyway, flag for review.")

    return {
        "subject": _subject(posting_title, posting_count),
        "to": poc_email,
        "body": body,
        "thin_personalization": bool(b2_fallback or b4_fallback),
        "word_count": word_count,
        "block_2": block2,
        "block_4": block4,
    }


# ---------------------------------------------------------------------------
# draft_for_run (BUILD item 7): called INLINE by the same run that gated.
# ---------------------------------------------------------------------------
@dataclass
class DraftBatchResult:
    drafted: list = field(default_factory=list)
    drafted_with_prior_contact: list = field(default_factory=list)
    no_email: list = field(default_factory=list)
    duplicate_within_run: list = field(default_factory=list)
    cancelled: bool = False
    fallback_counts: dict = field(default_factory=dict)


def _draft_one_firm(firm: dict, contacted_this_run: set[str], progress: Progress) -> tuple[str, dict]:
    """Returns (bucket_name, row). row is the wd_drafts row for a successful
    draft, or the wd_firms row itself for no_email/duplicate_within_run
    outcomes (nothing was written to wd_drafts for those)."""
    firm_id = firm["id"]
    firm_name = firm["firm_name"]
    research = firm.get("research") or {}
    postings = dbc.postings_for_firm(firm_id)
    titles = distinct_titles(postings)
    posting_count = len(titles)
    posting_title = titles[0] if titles else ""
    posting_url = next((p["url"] for p in postings if p.get("url")), "")
    short_name = firm_short(firm_name)

    poc_name = next((p.get("poc_name_hint") for p in postings if p.get("poc_name_hint")), None)
    if not poc_name:
        progress(f"{firm_name}: no POC name hint from the scanner. No email found.")
        return "no_email", firm

    email, confidence = apollo_enrich.find_email(
        poc_name=poc_name, company_name=firm_name, domain=(research.get("domain") or None),
        progress=progress,
    )
    if not email:
        progress(f"{firm_name}: Apollo could not find an email for {poc_name}.")
        return "no_email", firm

    norm_email = email.strip().lower()
    if norm_email in contacted_this_run:
        progress(f"{firm_name}: {poc_name} <{email}> already drafted earlier in this run. Blocked.")
        return "duplicate_within_run", firm

    prior = dbc.find_prior_contact(linkedin_url=None, email=email)
    collision_note = prior_contact_workflow = prior_contact_at = None
    if prior:
        prior_contact_workflow = prior.get("source_workflow")
        prior_contact_at = prior.get("contacted_at")
        collision_note = (f"previously drafted via Workflow {prior_contact_workflow} on "
                          f"{prior_contact_at}, check sent mail before sending.")
        progress(f"{firm_name}: {poc_name} {collision_note}")

    poc_first_name = poc_name.split()[0] if poc_name else "there"
    email_content = draft_email(
        firm_name=firm_name, poc_first_name=poc_first_name, poc_email=email,
        posting_title=posting_title, posting_url=posting_url, titles=titles,
        posting_count=posting_count, firm_short_name=short_name, research=research,
        progress=progress,
    )

    gmail_result = gmail_client.create_draft(
        to=email, subject=email_content["subject"], body=email_content["body"],
        attach_path=None, progress=progress,
    )

    poc_title = next((p.get("poc_designation_hint") for p in postings if p.get("poc_designation_hint")), None)
    draft_row = dbc.create_wd_draft(
        firm_id,
        poc_name=poc_name, poc_email=email, poc_title=poc_title,
        poc_linkedin_url=None,
        poc_source="from_export" if confidence == "from_export" else "apollo",
        subject=email_content["subject"], body=email_content["body"],
        word_count=email_content["word_count"],
        thin_personalization=email_content["thin_personalization"],
        gmail_draft_id=gmail_result["draft_id"],
        deck_pdf_path=None, deck_attached=False,
        collision_note=collision_note,
        prior_contact_workflow=prior_contact_workflow,
        prior_contact_at=prior_contact_at,
    )

    contacted_this_run.add(norm_email)
    dbc.record_contacted(linkedin_url=None, email=email, poc_name=poc_name,
                         firm_name=firm_name, gmail_draft_id=gmail_result["draft_id"],
                         source_workflow="D")

    progress(f"{firm_name}: drafted for {poc_name} <{email}>, Gmail draft {gmail_result['draft_id']}.")
    return ("drafted_with_prior_contact" if collision_note else "drafted"), draft_row


def draft_for_run(run_id: int, progress: Progress = _noop) -> DraftBatchResult:
    """Drafts every qualified firm in this run, up to DRAFT_CAP_PER_RUN.
    Respects the persisted cancel flag between firms (never mid-firm), never
    re-drafts a firm that already has a wd_drafts row (resume safety)."""
    reset_fallback_counts()
    result = DraftBatchResult()
    firms = [f for f in dbc.firms_for_run(run_id) if f.get("icp_status") == "qualified"]
    cap = config.DRAFT_CAP_PER_RUN
    contacted_this_run: set[str] = set()
    to_draft = firms[:cap]

    for i, firm in enumerate(to_draft):
        if dbc.cancel_requested(run_id):
            result.cancelled = True
            break
        if dbc.draft_exists_for_firm(firm["id"]):
            continue
        progress(f"Drafting {firm['firm_name']} ({i + 1}/{len(to_draft)})...")
        bucket, row = _draft_one_firm(firm, contacted_this_run, progress)
        getattr(result, bucket).append(row)

    result.fallback_counts = fallback_counts()
    return result
