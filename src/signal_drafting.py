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
from typing import Callable, NamedTuple, Optional
from urllib.parse import urlsplit, urlunsplit

from lib_referral import apollo_enrich, config as gate_config, deck_filler, fact_check, gmail_client, testmode
from . import signal_pipeline
from . import wd_config as config
from . import wd_dbc as dbc
from . import wd_poc

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


def block_6(posting_url: str, deck_attached: bool) -> str:
    """The P.S. always carries the posting URL (the honest correction path).
    The "deck is attached" sentence is included ONLY when a deck genuinely
    is -- Prompt 4's scope, not yet wired. Every draft made before then
    would otherwise assert an attachment gmail_client.create_draft() was
    never given, a false factual claim in the one block this module treats
    as trustworthy by construction."""
    deck_line = "The deck is attached. " if deck_attached else ""
    return ("Harp\nFounder, X Analyst\n\n"
            f"P.S. {deck_line}The posting is here if I have the wrong one: {posting_url}")


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


def _canonical_posting_url(url: str) -> str:
    """Strips LinkedIn's guest-search tracking query params before a
    posting URL reaches a draft. Live evidence (run 27): Choice NY's draft
    P.S. carried "?position=19&pageNum=0&refId=...&trackingId=..." from
    TinyFish's LinkedIn guest search, while Neal Communities' (sourced via
    JSearch, no query string at all) was clean and still resolves -- the
    canonical LinkedIn job identity lives entirely in the
    /jobs/view/<slug>-<id> path.

    Scoped to linkedin.com specifically, NOT a blanket strip-everything-
    after-"?": wd_postings also carries ZipRecruiter URLs where "?jid=<id>"
    IS the job identifier (the path alone, e.g.
    /c/<Company>/Job/<Title>/-in-<City>,<ST>, does not uniquely resolve
    without it) -- confirmed against real rows before writing this, a
    blanket strip would have broken those links."""
    if not url:
        return url
    parts = urlsplit(url)
    host = parts.hostname or ""
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


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
_DECK_ATTACHED_CLAIM_RE = re.compile(r"the deck is attached", re.IGNORECASE)


def find_required_fact_violations(block1_text: str, block6_text: str, block3_text: str,
                                  posting_title: str, firm_short_name: str, posting_url: str,
                                  corpus_text: str, deck_attached: bool,
                                  firm_oneliner: str = "") -> list[str]:
    v = []
    if not posting_title or posting_title not in block1_text:
        v.append("missing_posting_title_in_block1")
    if not posting_title or posting_title not in corpus_text:
        v.append("posting_title_not_grounded")
    if not firm_short_name or firm_short_name not in block1_text:
        v.append("missing_firm_name_in_block1")
    if not posting_url or posting_url not in block6_text:
        v.append("missing_posting_url_in_block6")
    # Run 27 fix: same mechanism as posting_title_not_grounded above, applied
    # to the firm one-liner Block 2 draws on. Confirmed empty is fine (thin
    # research -- _fallback_blocks already lets Block 2 go blank rather than
    # ship filler); confirmed NON-empty must actually be traceable to the
    # research object the corpus was built from, not silently dropped
    # between research and corpus construction. Note the limit of what this
    # catches: it verifies research["firm_oneliner"] reached the corpus the
    # LLM/fallback draws from, not that the RESEARCH ITSELF is about the
    # right company -- a name-collision at the research stage (a different
    # real firm entirely) produces an oneliner that is genuinely, correctly
    # grounded in a research blob, just the wrong one. See BUILD_LOG.md.
    if firm_oneliner and firm_oneliner not in corpus_text:
        v.append("firm_oneliner_not_grounded")
    # The claim and the attachment cannot diverge: Block 6 says a deck is
    # attached exactly when one genuinely is, in either direction.
    if bool(_DECK_ATTACHED_CLAIM_RE.search(block6_text)) != bool(deck_attached):
        v.append("deck_attachment_claim_mismatch")
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
    # "we <verb> ... before/previously/earlier": widening the character gap
    # alone (a prior fix, done as a side edit and reverted here -- see
    # BUILD_LOG.md) is over-broad -- at 40 chars it also caught "we talked to
    # operators before joining X Analyst" and "we connected two ledger
    # systems before go-live," neither a claim about prior contact with THIS
    # firm. The real distinguishing signal a genuine forbidden claim has and
    # a false positive lacks: the recipient is referenced ("you"/"your")
    # somewhere in the same clause as the temporal word. Two independent
    # lookaheads (order-independent, both scoped to the same sentence via
    # [^.?!]) require BOTH "you"/"your" AND "before"/"previously"/"earlier"
    # to appear within the same clause as the verb -- neither alone is
    # sufficient, which is what a bare character-gap widening missed.
    "prior_contact_claim": re.compile(
        r"\bwe\s+(?:have\s+)?(?:spoke|spoken|talked|connected|been\s+in\s+touch)\b"
        r"(?=[^.?!]{0,45}\b(?:you|your)\b)(?=[^.?!]{0,45}\b(?:before|previously|earlier)\b)|"
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
                        block2_violations: list[str], block4_violations: list[str],
                        block2_hard: bool = False, block4_hard: bool = False) -> str:
    """block2_hard/block4_hard distinguish "not being retried because it's
    already clean" from "not being retried because it hard-failed and is
    going straight to fallback regardless of what this retry produces" --
    only the former is genuinely "already correct" context. A hard-failed
    block (e.g. a forbidden Manpreet mention) must never be echoed back into
    a live prompt labeled as correct: it isn't being asked for here, its
    final value is already decided (the fallback), and there is no reason
    for the model rewriting the OTHER block to see forbidden content framed
    as approved."""
    targets = [name for name, requested in (("Block 2", retry_block2), ("Block 4", retry_block4)) if requested]
    retry_target = " and ".join(targets)

    kept_lines = []
    if not retry_block2 and not block2_hard:
        kept_lines.append(f'Block 2 (already correct -- keep as context, do not rewrite it): "{block2}"')
    if not retry_block4 and not block4_hard:
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
                                       retry_block2, retry_block4, block2, block4, b2v, b4v,
                                       block2_hard=b2_hard, block4_hard=b4_hard)
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
                firm_short_name: str, research: dict, deck_attached: bool = False,
                progress: Progress = _noop) -> dict:
    """Entry point for one firm. Returns {subject, to, body,
    thin_personalization, word_count, block_2, block_4}.

    `deck_attached` must reflect whether the caller is ACTUALLY going to
    attach a deck to the Gmail draft this content ends up in -- Block 6's
    wording and this check both key off the same value the caller passes,
    so the claim and the attachment can never diverge."""
    b1 = block_1(poc_first_name, firm_short_name, posting_title, posting_count)
    b3 = _BLOCK_3
    b5 = _BLOCK_5
    b6 = block_6(posting_url, deck_attached)
    corpus_text = grounding_corpus(research, firm_name, posting_title, posting_url, titles, posting_count)
    firm_oneliner = str((research or {}).get("firm_oneliner") or "").strip()

    req_violations = find_required_fact_violations(
        b1, b6, b3, posting_title, firm_short_name, posting_url, corpus_text, deck_attached,
        firm_oneliner=firm_oneliner)
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
    poc_domain_mismatch: list = field(default_factory=list)
    cancelled: bool = False
    fallback_counts: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# POC email domain cross-check (run-27 funnel audit).
#
# Run 27 drafted to riqbal@alphax.ae for a firm the gate had resolved as
# alphax-capital.com -- a Silicon Valley builder-developer. "AlphaX" is a
# generic enough name that Apollo matched a different, UAE-based entity
# entirely, and nothing compared the two. The geo-TLD backstop in
# signal_pipeline.py cannot catch this: it checks the GATE's domain, which was
# a plain .com and passed. The mismatch only exists between the gate's domain
# and the CONTACT's, so that is where it has to be checked.
#
# Uses wd_poc._firm_matches rather than new comparison logic. That function
# already carries the FIX 28 protection (containment, not equality, with only
# _TOLERABLE_EXTRAS business-descriptor words allowed as extras) and the
# abbreviation expansion that makes "NY" and "New York" comparable -- and it
# is already the function trusted to decide whether an Apollo org name is the
# firm we researched. Comparing the two domains' core labels is the same
# question asked of a different string, so it gets the same answer function.
#
# The affiliate case is a WARNING, not a block: real firms genuinely operate
# on a sibling domain (a "<firm>-capital.com" for the investment arm, a
# regional "<firm>.ca"). If the two domains' core labels still read as the
# same firm, the draft proceeds with a logged warning.
#
# COUNTRY IS CHECKED BEFORE THE LABEL, and this is what makes the check catch
# the incident it was written for. Verified against the real run-27 draft
# rows: _firm_matches("alphax", "alphax capital") is TRUE, because "capital"
# is in _TOLERABLE_EXTRAS -- correct behavior for firm names, and it would
# have downgraded AlphaX to a mere warning and drafted to the UAE contact
# anyway. But alphax.ae carries a UAE ccTLD, and a contact in another country
# is not a sibling domain of a Silicon Valley firm; it is a different entity.
# So the POC domain runs through signal_pipeline's OWN ccTLD table first (the
# same table, imported, never a second copy to drift), and a non-North-
# American ccTLD blocks outright regardless of how well the labels match.
# ".ca" is North American and so does NOT block -- that is exactly the
# regional-domain case the warning path exists for.
# ---------------------------------------------------------------------------
_PUBLIC_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "live.com", "msn.com", "aol.com", "icloud.com", "me.com", "mac.com",
    "protonmail.com", "proton.me", "gmx.com", "zoho.com", "yandex.com",
})


def _email_domain(email: str) -> str:
    """The part after the last "@", or "" when there isn't one. A string with
    no "@" has no domain to compare -- treating the whole string as one (an
    earlier version did) turned a malformed address into a bogus mismatch."""
    text = (email or "").strip().lower()
    if "@" not in text:
        return ""
    _, _, domain = text.rpartition("@")
    return domain.strip().strip(".")


def _domain_core(domain: str) -> str:
    """The registrable label of a domain, as a firm-name-shaped string.

    "www.alphax-capital.com" -> "alphax capital"; "ir.sonicautomotive.com" ->
    "sonicautomotive". Hyphens and dots become spaces so _firm_matches sees
    tokens rather than one fused label. The TLD and any leading host labels
    are dropped -- a firm on mail.example.com and one on example.com are the
    same firm, and the geo-TLD check already owns the country question."""
    domain = (domain or "").strip().lower().strip(".")
    if not domain:
        return ""
    parts = [p for p in domain.split(".") if p]
    if len(parts) >= 2:
        # Drop the TLD, plus a second-level public suffix ("co.uk", "com.au").
        if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) <= 3:
            parts = parts[:-2]
        else:
            parts = parts[:-1]
    label = parts[-1] if parts else ""
    return label.replace("-", " ").replace("_", " ").strip()


def poc_domain_mismatch_reason(email: str, research: dict, firm_name: str = "") -> Optional[tuple[str, str]]:
    """(severity, message) where severity is "block" or "warn", or None when
    the POC's email domain raises no question at all.

    None when there is nothing to compare against -- no gate domain, or a
    public mailbox (a real principal at a small firm legitimately uses Gmail;
    that is a personal-address question, not a wrong-company one, and blocking
    on it would cost real drafts for no evidence)."""
    gate_domain = str((research or {}).get("own_domain")
                     or (research or {}).get("domain") or "").strip().lower()
    poc_domain = _email_domain(email)
    if not gate_domain or not poc_domain:
        return None
    if poc_domain in _PUBLIC_EMAIL_DOMAINS:
        return None
    if poc_domain == gate_domain.strip().strip("."):
        return None

    foreign = signal_pipeline.foreign_domain_park_reason({"domain": poc_domain})
    if foreign:
        return ("block",
                f"POC email domain {poc_domain} is in a different country from the "
                f"gate's resolved domain {gate_domain} for {firm_name or 'this firm'} "
                f"({foreign}). Not an affiliate domain; not drafted.")

    gate_core, poc_core = _domain_core(gate_domain), _domain_core(poc_domain)
    if not gate_core or not poc_core:
        return None
    if gate_core == poc_core:
        return None
    if wd_poc._firm_matches(poc_core, gate_core):
        return ("warn",
                f"POC email domain {poc_domain} differs from the gate's resolved "
                f"domain {gate_domain}, but both read as the same firm. Possible "
                f"affiliate or regional domain; drafted anyway.")
    return ("block",
            f"POC email domain {poc_domain} does not match the gate's resolved "
            f"domain {gate_domain} for {firm_name or 'this firm'}. The contact and "
            f"the researched firm may be two different companies; not drafted.")


# ---------------------------------------------------------------------------
# Deck generation (run 27 fix): Workflow C's own generator, vendored unchanged
# at lib_referral/deck_filler.py -- called, never copied. Same master PPTX
# (templates/Pitch_Master.pptx), same slot map, same fixed slide copy;
# firm-specific fields differ (that's the point of the fill). build_and_convert()
# runs the LLM content extraction, the XML slot-fill, and the PDF conversion in
# one call; convert_to_pdf() inside it already degrades to pdf_path=None on a
# missing soffice wrapper or a conversion failure (Workflow C's own design).
# What it does NOT already guard is the CONTENT half -- a real LLM hiccup or a
# DeckFillError (a preflight slot mismatch, a stat-tile overflow) raises. A
# deck problem must never cost a firm its draft, so that half is guarded here,
# in Workflow D's own code, the same "an honest blank beats a fabricated or
# blocked one" posture CLAUDE.md states for everything else in this pipeline.
#
# Two more fixes below, both live evidence from a real Choice NY Property
# Management LLC deck (a third-party property manager -- no funds, no
# acquisitions arm, no capital stack, no disclosed founding year):
#
# 1. build_fill_data()'s Part C retry (FIX 36) rewrote fund_structures,
# underwriting_acquisitions, and capital_markets from genuinely, correctly
# empty ([DECK EMPTY]) into invented fit claims ([DECK RETRY] ... filled on
# retry) that shipped to slide 04. The model was right the first time --
# this firm has no fit there at all -- and the retry exists specifically to
# override an honest blank, which is backwards for a firm this narrow.
# deck_filler.py has no parameter to disable the retry, and config.TEST_MODE
# (the retry's only other gate) is too broad: it also reroutes
# get_deck_content() itself to a canned fixture, replacing real content
# generation entirely, not just the retry. The one seam that skips ONLY the
# retry is build_fill_data()'s own token-budget check (tokens_so_far >=
# MAX_LLM_TOKENS_PER_FIRM, FIX 34/36's own guard) -- deck_content is a plain
# dict this function already owns before build_and_convert() ever sees it,
# so forcing tokens_used to the cap here declines the retry unconditionally,
# without editing the vendored file.
#
# 2. Slide 3 of the master template has three card/footer groups -- the AUM
# stat tile, the Founded stat tile, and the capital-stack footer bar -- each
# a roundRect container shape plus 1-3 text-box shapes on top of it. None of
# the container shapes are slots in pitch_slots.json at all (they carry no
# text, so fill_deck() never touches them), and blanking just the label text
# runs (the first version of this fix) left the container rendering as an
# empty beige card or navy bar -- confirmed visually against real generated
# decks: Choice NY's empty Founded card and navy capital-stack bar (founded_
# year/capital_stack both ""), Neal Communities' empty AUM card (aum_value/
# aum_label/aum_asof all "" -- Neal never discloses AUM). The fix has to
# delete the whole shape sequence, not blank text inside it, and it has to
# operate on the OUTPUT PPTX deck_filler already produced, the same as the
# fix above.
#
# Shapes are identified by NAME ("Shape 4", "Text 5", ...) rather than by
# their locator TEXT, because by the time this runs the text has already
# been replaced (often with nothing) -- there is no longer a unique locator
# to search for. These names are the master-generation tool's own
# autogenerated per-shape names; confirmed identical, in the identical
# order, across two independently generated decks (Choice NY, Neal
# Communities) before writing this. They are NOT unique across the whole
# presentation (every slide's own shapes restart around the same low
# numbers), so which slide to touch is resolved from pitch_slots.json
# itself (via the vendored, public load_slot_map()) rather than assumed --
# an earlier draft of this fix, caught in testing before it ever reached
# the codebase, deleted "Text 9"/"Text 13" etc. on unrelated slides across
# the whole deck for exactly this reason. Master-specific, same class of
# fragility deck_filler.py's own geometry constants already accept (see
# its _AUM_VALUE_TILE_MAX_CHARS comment) -- a future master re-export that
# renumbers these shapes needs this table updated to match.
# Run 29 follow-up, same mechanism extended in three ways, all from real
# generated decks plus Workflow C's own Kingbird deck read as the reference:
#
# a. Slide 12 (SECTION 04, "Where this fits <firm> specifically") has the
# same construction as slide 3's cards -- five stacked roundRect row bars,
# each with a static heading text box and a fit_paragraph_N body text box on
# top. With the Part C retry now declined (above), a genuinely-empty section
# leaves the bar rendering with its heading and no body: Choice NY ships an
# empty "Complex Fund Structures" and "Capital Markets Expertise" bar, Neal
# an empty "Complex Fund Structures" bar. Workflow C ships this defect too --
# its Kingbird deck has an empty "Tailored Investor Reporting" bar -- so
# there is no upstream behavior to inherit here, only the same fix applied
# one slide over.
#
# b. Reflow. Deleting a group used to leave its vertical slot vacant: Neal's
# slide 3 lost the AUM card and left the Founded card marooned in slot 2 with
# an empty quadrant above it. Survivors now shift up into the slots the
# deleted groups vacated, so a stack always fills from the top with no gap.
# Slot positions are read from the deck's OWN container geometry at run time
# rather than hardcoded, and a survivor only ever moves up (its target slot
# index is always <= its own), so this can never push a shape off-slide.
#
# c. Slide 3's Founded card carries a third text box reading "Investing
# since" that pitch_slots.json has no slot for at all -- nothing fills it,
# in either workflow, ever. The master's AUM card uses that third line for
# aum_asof ("as of Dec 31, 2025"); the Founded card's equivalent line was
# authored as a bare sentence fragment with no value to complete it, so it
# renders dangling on every deck that has a founded_year (Neal: "1970 /
# Founded / Investing since"). Populating it from founded_year is not the
# fix -- the card already shows that year as its headline figure and its
# "Founded" label right above. It is listed as `valueless` below: deleted
# with its card when the card goes, and deleted on its own when the card
# stays.
#
# Slides are still resolved from pitch_slots.json (never hardcoded), stacks
# are still atomic, and the shape-name table is still master-specific in
# exactly the way documented above.
# ---------------------------------------------------------------------------
class _DeckShapeGroup(NamedTuple):
    """One card / footer / row: a container shape plus the text boxes drawn
    on top of it. `keys` are the fill_data keys whose values that group
    displays -- ALL of them empty means the group has nothing to show and is
    deleted whole. `valueless` names shapes inside the group that no slot
    ever fills (see (c) above); they go whether the group survives or not."""
    container: str
    content: tuple[str, ...]
    keys: tuple[str, ...]
    valueless: tuple[str, ...] = ()


class _DeckShapeStack(NamedTuple):
    """Groups sharing one vertical stack of slots on one slide. `anchor_key`
    is any fill_data key on that slide -- pitch_slots.json resolves it to the
    slide number. `reflow` is False for a lone full-width group that has no
    other slot to move into."""
    anchor_key: str
    reflow: bool
    groups: tuple[_DeckShapeGroup, ...]


_DECK_SHAPE_STACKS: tuple[_DeckShapeStack, ...] = (
    # Slide 3: the two stat cards in the right-hand column.
    _DeckShapeStack("aum_value", True, (
        _DeckShapeGroup("Shape 4", ("Text 5", "Text 6", "Text 7"),
                        ("aum_value", "aum_label", "aum_asof")),
        _DeckShapeGroup("Shape 8", ("Text 9", "Text 10", "Text 11"),
                        ("founded_year",), valueless=("Text 11",)),
    )),
    # Slide 3: the full-width capital-stack footer bar. Nothing to reflow into.
    _DeckShapeStack("capital_stack", False, (
        _DeckShapeGroup("Shape 12", ("Text 13",), ("capital_stack",)),
    )),
    # Slide 12: the five stacked fit rows. Each row also owns a decorative
    # icon, a <p:pic> rather than a <p:sp> -- caught by rendering the patched
    # deck to PDF and looking at it: the first version of this table listed
    # only the text boxes, which left the deleted row's icon orphaned on the
    # slide and left every surviving row's icon behind at its original y
    # while the bar it belongs to moved up without it.
    # NOTE the shape names collide with slide 3's ("Shape 12", "Text 13",
    # "Text 5") -- that collision is exactly why the slide is resolved per
    # stack instead of searched for.
    _DeckShapeStack("fit_paragraph_1", True, (
        _DeckShapeGroup("Shape 3", ("Image 0", "Text 4", "Text 5"), ("fit_paragraph_1",)),
        _DeckShapeGroup("Shape 6", ("Image 1", "Text 7", "Text 8"), ("fit_paragraph_2",)),
        _DeckShapeGroup("Shape 9", ("Image 2", "Text 10", "Text 11"), ("fit_paragraph_3",)),
        _DeckShapeGroup("Shape 12", ("Image 3", "Text 13", "Text 14"), ("fit_paragraph_4",)),
        _DeckShapeGroup("Shape 15", ("Image 4", "Text 16", "Text 17"), ("fit_paragraph_5",)),
    )),
)

# <p:sp> (text boxes, containers) and <p:pic> (the slide-12 row icons). The
# backreference keeps the two from being matched across each other; neither
# element type nests inside the other in any slide this touches.
_SHAPE_RE = re.compile(r"<p:(sp|pic)>.*?</p:\1>", re.DOTALL)
_SHAPE_NAME_RE = re.compile(r'<p:cNvPr id="\d+" name="([^"]*)"')
_SHAPE_OFF_RE = re.compile(r'<a:off x="(-?\d+)" y="(-?\d+)"\s*/>')


def _slide_no_for_key(slot_map: dict, key: str) -> Optional[str]:
    for slide_no, slots in (slot_map or {}).get("slides", {}).items():
        for slot in slots:
            if slot.get("key") == key:
                return slide_no
    return None


def _shape_y(shape_xml: str) -> Optional[int]:
    """The shape's own y offset in EMU, or None if it carries no explicit
    geometry (inherited from the layout -- not something to reflow blind)."""
    m = _SHAPE_OFF_RE.search(shape_xml)
    return int(m.group(2)) if m else None


def _shift_shape_y(shape_xml: str, delta: int) -> str:
    m = _SHAPE_OFF_RE.search(shape_xml)
    if not m or not delta:
        return shape_xml
    shifted = f'<a:off x="{m.group(1)}" y="{int(m.group(2)) + delta}"/>'
    return shape_xml[:m.start()] + shifted + shape_xml[m.end():]


def _apply_deck_shape_stack(xml: str, stack: _DeckShapeStack, fill_data: dict) -> str:
    """This stack's slide XML with every all-empty group deleted whole, every
    valueless shape deleted, and the surviving groups reflowed up into the
    vacated slots. Returns `xml` unchanged if there is nothing to do.

    The whole stack is atomic: every shape name it lists must be locatable
    EXACTLY ONCE on the slide or nothing in it is touched, the same "don't
    guess" posture fill_deck()'s own slot-fill takes on a locator that isn't
    unique. Deliberately not per-group: reflow needs every slot position in
    the stack to be known, and deleting only the unambiguous shapes would
    leave an orphaned container or text box behind, which reads worse on the
    slide than leaving the stack alone."""
    shapes: dict[str, list[str]] = {}
    for match in _SHAPE_RE.finditer(xml):
        shape_xml = match.group(0)
        m = _SHAPE_NAME_RE.search(shape_xml)
        if m:
            shapes.setdefault(m.group(1), []).append(shape_xml)

    needed = [n for g in stack.groups for n in (g.container, *g.content)]
    if len(set(needed)) != len(needed):
        return xml                                   # table bug: a name listed twice in one stack
    if any(len(shapes.get(n, [])) != 1 for n in needed):
        return xml
    one = {n: shapes[n][0] for n in needed}
    if any(xml.count(one[n]) != 1 for n in needed):  # identical shape XML twice over
        return xml

    empty = [all(not str((fill_data or {}).get(k) or "").strip() for k in g.keys)
             for g in stack.groups]

    to_delete: list[str] = []
    for group, is_empty in zip(stack.groups, empty):
        to_delete.extend([group.container, *group.content] if is_empty else group.valueless)

    shifts: list[tuple[str, int]] = []
    slot_ys = [_shape_y(one[g.container]) for g in stack.groups]
    if stack.reflow and all(y is not None for y in slot_ys):
        survivors = [g for g, is_empty in zip(stack.groups, empty) if not is_empty]
        for target_index, group in enumerate(survivors):
            delta = slot_ys[target_index] - slot_ys[stack.groups.index(group)]
            if delta:
                shifts.extend((n, delta) for n in (group.container, *group.content)
                              if n not in to_delete)

    if not to_delete and not shifts:
        return xml
    for name in to_delete:
        xml = xml.replace(one[name], "", 1)
    for name, delta in shifts:
        xml = xml.replace(one[name], _shift_shape_y(one[name], delta), 1)
    return xml


def _delete_empty_deck_shapes(pptx_path, fill_data: dict) -> bool:
    """Applies every _DECK_SHAPE_STACKS entry to the deck in place. Returns
    True if the file was rewritten (the caller must re-run PDF conversion in
    that case)."""
    import zipfile as _zipfile

    slot_map = deck_filler.load_slot_map()
    plan: list[tuple[str, _DeckShapeStack]] = []
    for stack in _DECK_SHAPE_STACKS:
        slide_no = _slide_no_for_key(slot_map, stack.anchor_key)
        if slide_no:
            plan.append((f"ppt/slides/slide{slide_no}.xml", stack))
    if not plan:
        return False

    with _zipfile.ZipFile(pptx_path, "r") as zin:
        names = zin.namelist()
        contents = {n: zin.read(n) for n in names}

    changed = False
    for member, stack in plan:
        if member not in contents:
            continue
        xml = contents[member].decode("utf-8")
        patched = _apply_deck_shape_stack(xml, stack, fill_data)
        if patched != xml:
            contents[member] = patched.encode("utf-8")
            changed = True

    if not changed:
        return False

    with _zipfile.ZipFile(pptx_path, "w", _zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, contents[name])
    return True


# Run 27 follow-up, Choice NY live evidence: slide 01 repeated the italic
# headline verbatim as a bullet reading "Firm described as <the exact same
# oneliner text>". deck_filler.py's own _drop_oneliner_duplicate exists
# specifically to catch a bullet identical to the firm one-liner (FIX 15),
# but its compare is an exact string match after only whitespace/case/
# trailing-period normalization -- the "Firm described as " lead-in defeats
# it. Applied here, to deck_content, BEFORE it ever reaches
# build_and_convert() -- the vendored guard's own unmodified compare still
# runs afterward too, redundant once this catches it, harmless if it
# doesn't need to.
_ONELINER_LEAD_INS: tuple[str, ...] = (
    "firm described as ",
    "the firm is described as ",
    "company described as ",
    "the company is described as ",
    "described as ",
)


def _strip_oneliner_lead_in(text: str) -> str:
    stripped = (text or "").strip()
    low = stripped.lower()
    for prefix in _ONELINER_LEAD_INS:
        if low.startswith(prefix):
            return stripped[len(prefix):]
    return stripped


def _norm_for_oneliner_compare(text: str) -> str:
    return _WS_RE.sub(" ", _strip_oneliner_lead_in(text).strip().rstrip(".")).lower()


# Run-29 follow-up, regenerated Neal Communities deck: three of five slide-01
# bullets restated something else already on the same slide.
#
#   "Founded in 1970"                        <- the Founded stat card ("1970")
#   "Disclosed AUM: $700 million"            <- the AUM stat tile ("$700 million")
#   "Homebuilder/developer focusing on
#    single-family and townhome communities"  <- the italic firm_oneliner headline,
#                                                minus its trailing " in Southwest Florida"
#
# The exact-match guard above misses the third because it is a SUBSTRING of the
# headline, not a prefix variant of it. Hence two additions:
#
# (a) substring containment in EITHER direction, above a length floor. A
# 30-character floor on the SHORTER side is what keeps a legitimately short
# bullet from being eaten by an incidental appearance in a long headline
# ("Multifamily" inside "...multifamily housing..." is not a restatement); the
# live case clears it with 71 characters.
#
# (b) a bullet that restates a POPULATED stat tile. The value alone is not
# enough to drop on -- "Reported $1 billion annual revenue in Apr 2024
# article" mentions a figure but is the slide's most interesting fact and no
# tile shows it. The test is: the bullet contains the tile's own value AND,
# once that value, the tile's label words, and connective filler are removed,
# no substantive word is left. "Founded in 1970 by Pat Neal in Sarasota" keeps
# pat/neal/sarasota and survives.
_MIN_ONELINER_OVERLAP_CHARS = 30

# "$4.4 billion" and a tile reading "$4.4B" are the same figure. Normalizing
# the magnitude word to its initial is what lets containment see that; without
# it the master's own "Manages $4.4 billion in gross asset value" bullet reads
# as a different fact from its "$4.4B" tile.
_MONEY_MAGNITUDE_RE = re.compile(r"(\d)\s*(?:billion|bn|b)\b", re.IGNORECASE)
_MONEY_MILLION_RE = re.compile(r"(\d)\s*(?:million|mm|m)\b", re.IGNORECASE)
_MONEY_TRILLION_RE = re.compile(r"(\d)\s*(?:trillion|tn|t)\b", re.IGNORECASE)
_NUM_COMMA_RE = re.compile(r"(?<=\d),(?=\d{3})")

# Connective/qualifier words that carry no fact of their own. A residue made
# only of these (plus the tile's own label words) means the bullet said
# nothing the tile did not already say.
_STAT_FILLER_WORDS = frozenset({
    "a", "an", "the", "of", "in", "at", "on", "to", "as", "is", "was", "are",
    "were", "and", "or", "with", "its", "their", "has", "have", "had", "been",
    "about", "approximately", "around", "roughly", "over", "under", "than",
    "more", "less", "least", "nearly", "some", "total", "totaling", "totalling",
    "currently", "now", "today", "reported", "reportedly", "reports",
    "disclosed", "discloses", "stated", "states", "manages", "managing",
    "management", "manager", "holds", "holding", "oversees", "operating",
    "operates", "firm", "company", "since", "founded", "established", "est",
    "year", "years", "circa", "per", "approx", "aum", "usd",
})
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'&/-]*")


def _norm_money(text: str) -> str:
    text = _NUM_COMMA_RE.sub("", (text or "").lower())
    text = _MONEY_TRILLION_RE.sub(r"\1t", text)
    text = _MONEY_MAGNITUDE_RE.sub(r"\1b", text)
    text = _MONEY_MILLION_RE.sub(r"\1m", text)
    return _WS_RE.sub(" ", text).strip()


def _is_oneliner_restatement(bullet: str, oneliner: str) -> bool:
    """True if the bullet says what the italic headline already says: equal
    after lead-in stripping (the original guard), or one wholly contained in
    the other above the length floor."""
    b = _norm_for_oneliner_compare(bullet)
    o = _norm_for_oneliner_compare(oneliner)
    if not b or not o:
        return False
    if b == o:
        return True
    shorter, longer = (b, o) if len(b) <= len(o) else (o, b)
    if len(shorter) < _MIN_ONELINER_OVERLAP_CHARS:
        return False
    return shorter in longer


def _is_stat_tile_restatement(bullet: str, tile_values: list, label_words: frozenset) -> bool:
    """True if the bullet contains one of the populated tiles' values and adds
    no other fact of its own."""
    b = _norm_money(bullet)
    if not b:
        return False
    for value in tile_values:
        v = _norm_money(value)
        if not v:
            continue
        # Word-boundary match so a bare year ("1970") does not match inside
        # "1970s" or a longer number, and so "$700m" needs to stand alone.
        pattern = re.compile(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])")
        if not pattern.search(b):
            continue
        residue = pattern.sub(" ", b)
        leftover = {w for w in _TOKEN_RE.findall(residue)
                   if w not in _STAT_FILLER_WORDS and w not in label_words}
        if not leftover:
            return True
    return False


def _stat_tile_comparands(fill_data: dict) -> tuple[list, frozenset]:
    """(values shown on populated tiles, words those tiles' labels use).

    Exactly the three fill_data fields the tiles are filled from, read off
    deck_filler's own output rather than re-derived from research -- so a
    change in how it picks a figure can't silently desync this check. The
    labels feed the residue test: "AUM" in "Disclosed AUM: $700 million" is
    the tile's own caption, not a fact the bullet adds."""
    fill_data = fill_data or {}
    values = [str(fill_data.get(k) or "").strip()
              for k in ("founded_year", "aum_value", "disclosed_figure")]
    label_words = set()
    for key in ("aum_label", "disclosed_label", "aum_asof"):
        label_words.update(_TOKEN_RE.findall(_norm_money(str(fill_data.get(key) or ""))))
    return [v for v in values if v], frozenset(label_words)


def _drop_oneliner_duplicate_bullets(bullets: list, oneliner: str,
                                     fill_data: Optional[dict] = None) -> list:
    """Bullets with the slide-01 restatements removed: of the italic headline,
    and of any populated stat tile. `fill_data` omitted skips the tile rule
    (the headline rule alone is the pre-existing behavior)."""
    tile_values, label_words = _stat_tile_comparands(fill_data)
    has_oneliner = bool(_norm_for_oneliner_compare(oneliner))
    kept = []
    for bullet in (bullets or []):
        if has_oneliner and _is_oneliner_restatement(bullet, oneliner):
            continue
        if tile_values and _is_stat_tile_restatement(bullet, tile_values, label_words):
            continue
        kept.append(bullet)
    return kept


def _generate_deck(firm_name: str, research: dict, progress: Progress) -> Optional[str]:
    """Path to the generated deck PDF, or None if generation/conversion
    failed or produced no PDF. Workflow D has no personalization-hooks
    phase of its own (see firm_short's docstring) -- personalization is
    passed empty, matching deck_filler's own default for a caller with
    nothing to add there."""
    try:
        deck_content = deck_filler.get_deck_content(firm_name, research, personalization={})
        deck_content["tokens_used"] = gate_config.MAX_LLM_TOKENS_PER_FIRM
        oneliner = str((research or {}).get("firm_oneliner") or "").strip()
        if deck_content.get("profile_bullets"):
            # The stat-tile rule needs the tile values, which only
            # build_fill_data() produces -- and build_and_convert() calls it
            # internally, AFTER the bullets are already baked in. So it is
            # called here first, for its three tile fields only. That is free
            # and deterministic: with tokens_used forced to the cap above, its
            # one LLM path (the Part C retry) is declined, leaving a pure
            # function over research + deck_content. build_and_convert() then
            # recomputes the same values from the same research; none of the
            # three depends on profile_bullets, so the tiles it fills are
            # identical to the ones compared against here.
            fill_data = deck_filler.build_fill_data(firm_name, research, deck_content,
                                                    personalization={})
            deck_content["profile_bullets"] = _drop_oneliner_duplicate_bullets(
                deck_content["profile_bullets"], oneliner, fill_data)
        result = deck_filler.build_and_convert(firm_name, research, deck_content,
                                               progress=progress, personalization={})
    except Exception as e:  # noqa: BLE001 - a deck failure must never block a draft
        progress(f"{firm_name}: deck generation failed ({e}); drafting without a deck.")
        return None

    pdf_path = result.get("pdf_path")
    try:
        pptx_path = result.get("pptx_path")
        fill_data = result.get("fill_data") or {}
        if pptx_path and _delete_empty_deck_shapes(pptx_path, fill_data):
            pdf_path = deck_filler.convert_to_pdf(pptx_path, progress=progress) or pdf_path
    except Exception as e:  # noqa: BLE001 - a shape-cleanup failure ships the un-cleaned deck, not none
        progress(f"{firm_name}: empty-shape cleanup failed ({e}); shipping the deck as generated.")

    return str(pdf_path) if pdf_path else None


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
    posting_url = _canonical_posting_url(next((p["url"] for p in postings if p.get("url")), ""))
    short_name = firm_short(firm_name)

    # POC discovery, in order: the scanner's poc_name_hint (a name hint only,
    # never an email source) via apollo_enrich.find_email first. If there's
    # no hint at all, or find_email can't resolve one, fall back to
    # wd_poc.find_senior_poc's own Apollo mixed_people/api_search + match --
    # this closes the gap BUILD_LOG.md previously recorded as unbuildable
    # (see DRIFT.md/BUILD_LOG.md for the corrected endpoint finding).
    poc_name = next((p.get("poc_name_hint") for p in postings if p.get("poc_name_hint")), None)
    poc_title = next((p.get("poc_designation_hint") for p in postings if p.get("poc_designation_hint")), None)
    email = confidence = poc_source = None

    if poc_name:
        email, confidence = apollo_enrich.find_email(
            poc_name=poc_name, company_name=firm_name, domain=(research.get("domain") or None),
            progress=progress,
        )
        if email:
            poc_source = "from_export" if confidence == "from_export" else "apollo"

    if not email:
        hit = wd_poc.find_senior_poc(firm_name, research.get("domain") or None, progress=progress)
        if hit:
            poc_name, email, poc_title = hit
            poc_source = "apollo_search"

    if not email:
        if poc_name:
            reason = (f"Apollo could not resolve an email for {poc_name} (scanner hint), "
                      "and its senior-finance-title search also found no verified contact")
        else:
            reason = ("no POC name hint from the scanner, and Apollo's senior-finance-title "
                      "search also found no verified contact")
        progress(f"{firm_name}: {reason}.")
        return "no_email", {**firm, "no_email_reason": reason}

    norm_email = email.strip().lower()
    if norm_email in contacted_this_run:
        progress(f"{firm_name}: {poc_name} <{email}> already drafted earlier in this run. Blocked.")
        return "duplicate_within_run", firm

    # Before anything is spent on a deck or an LLM draft: is this contact even
    # at the firm the gate researched? (AlphaX, run 27 -- see the block above.)
    domain_check = poc_domain_mismatch_reason(email, research, firm_name)
    if domain_check:
        severity, message = domain_check
        progress(f"{firm_name}: {message}")
        if severity == "block":
            return "poc_domain_mismatch", {**firm, "poc_domain_mismatch_reason": message,
                                          "poc_name": poc_name, "poc_email": email}

    prior = dbc.find_prior_contact(linkedin_url=None, email=email)
    collision_note = prior_contact_workflow = prior_contact_at = None
    if prior:
        prior_contact_workflow = prior.get("source_workflow")
        prior_contact_at = prior.get("contacted_at")
        collision_note = (f"previously drafted via Workflow {prior_contact_workflow} on "
                          f"{prior_contact_at}, check sent mail before sending.")
        progress(f"{firm_name}: {poc_name} {collision_note}")

    # Single source of truth -- this one variable drives Block 6's wording,
    # the Gmail attachment, and the wd_drafts row, so they cannot drift
    # apart from each other. None (generation failed, or produced no PDF)
    # means exactly what it always meant: draft without a deck.
    deck_pdf_path = _generate_deck(firm_name, research, progress)
    poc_first_name = poc_name.split()[0] if poc_name else "there"
    email_content = draft_email(
        firm_name=firm_name, poc_first_name=poc_first_name, poc_email=email,
        posting_title=posting_title, posting_url=posting_url, titles=titles,
        posting_count=posting_count, firm_short_name=short_name, research=research,
        deck_attached=bool(deck_pdf_path), progress=progress,
    )

    gmail_result = gmail_client.create_draft(
        to=email, subject=email_content["subject"], body=email_content["body"],
        attach_path=deck_pdf_path, progress=progress,
    )

    draft_row = dbc.create_wd_draft(
        firm_id,
        poc_name=poc_name, poc_email=email, poc_title=poc_title,
        poc_linkedin_url=None,
        poc_source=poc_source,
        subject=email_content["subject"], body=email_content["body"],
        word_count=email_content["word_count"],
        thin_personalization=email_content["thin_personalization"],
        gmail_draft_id=gmail_result["draft_id"],
        deck_pdf_path=deck_pdf_path, deck_attached=bool(deck_pdf_path),
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
