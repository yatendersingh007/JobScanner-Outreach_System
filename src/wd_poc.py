"""Workflow D senior-finance POC discovery via Apollo.

Closes the gap BUILD_LOG records as "Apollo search-by-title-and-company is
not implemented". NOT vendored -- this is Workflow D's own code.

Verified live 2026-07-30 against the real Apollo plan:
  POST /api/v1/mixed_people/api_search
    q_organization_name       (string)  -- works, finds divisional entities
    q_organization_domains_list (list)  -- works
    q_organization_domains    (string)  -- works; a LIST here returns 0 silently
    person_titles             (list)    -- too literal, returns 0, NOT used
  Response people[] carry title/organization/id but name=None, email=None.
  POST /api/v1/people/match  {"id": <id>}  -- unlocks name + verified email.
  people/show 404s on this plan. Do not use.

2026-07-31, also verified live: q_organization_domains_list finds far more
people than q_organization_name for the same firm (78 vs 12 in one direct
comparison), and the senior hit (a CFO) existed only in the domain-scoped
result -- domain search now tries first when a domain is known, name search
is the fallback. Apollo's org search also returns lookalike/divisional
entities (a firm's holding company, a similarly-named unrelated firm), so
every candidate's own organization.name is now fuzzy-matched against the
target firm_name before it's eligible for ranking -- reusing
lib_referral/matching/normalize.py's existing normalizer (NOT a new one,
and that file is vendored/untouched) rather than trusting Apollo's org
search to have already scoped correctly.

2026-08-01, live evidence the ORIGINAL fuzzy match (set equality on
lib_referral's own meaningful_tokens()) was too strict, blocking real
drafts: "Choice NY Property Management LLC" (domain choicenewyork.com) --
all 41 Apollo domain hits, including a Controller, carry organization.name
"Choice New York Companies". "NY" is an abbreviation of "New York", not a
distinguishing token, and set equality rejected every one of them
({choice, ny} != {choice, new, york}).

Replaced with a containment rule (see _firm_matches): one side's token set
must be a subset of the other's, and the larger side's extra tokens must
all be in _TOLERABLE_EXTRAS. Two things had to change together to make
this safe, not just "loosen equality to containment": (1) this file's own
abbreviation expansion (_ABBREVIATIONS) resolves state/city and
corporate-form abbreviations to real tokens before comparing, so "NY" and
"New York" are directly comparable; (2) _meaningful_tokens() DELIBERATELY
does NOT call lib_referral's own meaningful_tokens() / strip its full
SUFFIX_TOKENS list -- it only drops TRUE legal forms (_ALWAYS_STRIP,
mirroring wd_dbc.firm_key's own narrow philosophy). Descriptive
business-type words (capital, group, management, real, estate, partners,
investment, ...) are kept as real, comparable tokens; whether one of them
is missing on one side (tolerated, e.g. "Property Management" present on
one side and simply absent on the other) versus CONFLICTING on both sides
(rejected -- "Real Estate Partners" vs "Investment Management" are both
non-empty and share nothing) is exactly what separates a match from a
FIX-28-style collision. Naively containment-checking against
lib_referral's own fully-stripped meaningful_tokens() (i.e. keeping the
strip step but loosening equality to containment) would have reopened
that exact collision, since "Kairos Real Estate Partners" and "Kairos
Investment Management" both reduce to bare {"kairos"} once SUFFIX_TOKENS
is fully stripped -- trivially "equal", let alone a subset.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import requests

from lib_referral.config import SUFFIX_TOKENS
from lib_referral.matching.normalize import tokenize

SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
MATCH_URL = "https://api.apollo.io/api/v1/people/match"
TIMEOUT = 60

# Ordered by seniority. First tier with a hit wins. Extended 2026-08-01 for
# firms with no CFO: Portfolio/Corporate Controller join plain Controller
# (same seniority, a scope qualifier only); SVP/VP of Accounting join the
# existing VP-of-Finance-family tier (same level, Accounting instead of
# Finance); Assistant Controller gets its OWN tier below that one, since
# it's genuinely more junior than a full Controller -- placed above Finance
# Manager per instruction. Director of Accounting was already present.
TIERS = [
    ("chief financial officer", "cfo"),
    ("controller", "corporate controller", "portfolio controller"),
    ("svp of finance", "svp finance", "senior vice president of finance",
     "svp of accounting", "senior vice president of accounting",
     "vp of finance", "vp finance", "vice president of finance",
     "vice president of corporate finance", "vp corporate accounting",
     "vp of accounting", "director of finance", "head of finance"),
    ("assistant controller",),
    ("finance manager", "financial manager", "finance director"),
    ("accounting manager", "director of accounting"),
]
EXCLUDE = re.compile(r"\b(intern|internship|assistant to|coordinator|clerk)\b", re.I)

# A bare "controller" keyword match must NOT also catch "Assistant
# Controller" -- that's a real, more junior title with its own tier above
# (TIERS index 3). Confirmed by direct check before this fix: with plain
# substring matching, "controller" in "assistant controller" is True, so
# a naive keyword-list scan would rank an Assistant Controller as equal
# seniority to a full Controller, and -- worse -- could pick whichever one
# Apollo happened to list first when both exist at the same firm.
# "Corporate Controller"/"Portfolio Controller" are unaffected (no
# "assistant " prefix), so they still match this pattern too.
_CONTROLLER_RE = re.compile(r"(?<!assistant )\bcontroller\b")


def _title_matches_keyword(title: str, keyword: str) -> bool:
    if keyword == "controller":
        return bool(_CONTROLLER_RE.search(title))
    return keyword in title


def _noop(_: str) -> None:
    pass


def _key() -> Optional[str]:
    try:
        from lib_snapshot import config as snap
        k = getattr(snap, "APOLLO_API_KEY", None)
        if k:
            return k
    except Exception:
        pass
    import os
    return os.getenv("APOLLO_API_KEY")


def _headers(key: str) -> dict:
    return {"Content-Type": "application/json", "accept": "application/json",
            "x-api-key": key}


def _search(headers: dict, body: dict) -> list[dict]:
    r = requests.post(SEARCH_URL, headers=headers, json=body, timeout=TIMEOUT)
    if r.status_code != 200:
        return []
    return (r.json() or {}).get("people") or []


def _org_name(person: dict) -> str:
    org = person.get("organization") or {}
    return org.get("name") or ""


# Bidirectional abbreviation <-> expansion map. Applied to RAW tokens
# (lib_referral's own tokenize(), before _ALWAYS_STRIP/_TOLERABLE_EXTRAS
# classification below) so a corporate-form abbreviation (Mgmt, Corp, Co,
# Assoc, Ptnrs) expands into the exact spelled-out word that
# classification already knows how to handle, and a state/city
# abbreviation (NY, NJ, CA, LA, SF, DC, Intl) expands into the real,
# still-meaningful multi-word proper noun the spelled-out side already
# carries as separate tokens -- "ny" -> ("new", "york") makes "Choice
# NY..." directly comparable to "Choice New York...", which no amount of
# suffix-word filtering alone could do (that only drops generic words, it
# has no notion of one token standing in for several).
_ABBREVIATIONS: dict[str, tuple[str, ...]] = {
    "ny": ("new", "york"),
    "nj": ("new", "jersey"),
    "ca": ("california",),
    "la": ("los", "angeles"),
    "sf": ("san", "francisco"),
    "dc": ("washington", "dc"),
    "intl": ("international",),
    "mgmt": ("management",),
    "corp": ("corporation",),
    "co": ("company",),
    "assoc": ("associates",),
    "ptnrs": ("partners",),
}

# Two DIFFERENT categories, deliberately not the same thing:
#
# _ALWAYS_STRIP: TRUE legal forms plus two confirmed SUFFIX_TOKENS gaps
# ("companies" for "company", "corporations" for "corporation" -- both
# irregular plurals the vendored list only covers in singular). Dropped
# entirely from BOTH sides before comparison, mirroring wd_dbc.firm_key's
# own deliberately narrow "true legal forms only" philosophy (FIX 28's own
# reasoning), not lib_referral's broader SUFFIX_TOKENS.
#
# _TOLERABLE_EXTRAS: lib_referral's own SUFFIX_TOKENS, imported and reused
# AS-IS, but NOT pre-stripped -- these descriptive business-type words
# (capital, group, management, real, estate, partners, investment, ...)
# stay in each side's own token set. Whether one of these words shows up
# as an unmatched "extra" is exactly the signal that tells a genuine
# collision apart from a merely-less-detailed name (see _firm_matches).
_ALWAYS_STRIP = {
    "llc", "inc", "incorporated", "corp", "corporation", "co", "company",
    "companies", "corporations", "lp", "llp", "ltd", "limited", "plc",
    "pllc", "pc", "the",
}
_TOLERABLE_EXTRAS = SUFFIX_TOKENS


def _expand(token: str) -> tuple[str, ...]:
    return _ABBREVIATIONS.get(token, (token,))


def _meaningful_tokens(name: str) -> set[str]:
    """lib_referral's own tokenize() (vendored, unedited), plus this
    file's own abbreviation expansion, with only _ALWAYS_STRIP words
    dropped -- deliberately NOT lib_referral's own meaningful_tokens(),
    which strips the full SUFFIX_TOKENS list and would erase exactly the
    words _firm_matches needs to see to tell "Kairos Real Estate Partners"
    apart from "Kairos Investment Management"."""
    expanded: list[str] = []
    for t in tokenize(name):
        expanded.extend(_expand(t))
    return {t for t in expanded if t not in _ALWAYS_STRIP}


def _firm_matches(candidate_org_name: str, target_firm_name: str) -> bool:
    """True if candidate_org_name plausibly names the same firm as
    target_firm_name.

    Containment, not strict equality: one side's token set must be a
    SUBSET of the other's, and every extra token the larger side has must
    be in _TOLERABLE_EXTRAS (a business-descriptor word neither side is
    required to agree on) -- never a genuine distinguishing proper noun.

    "Choice New York Companies" -> {"choice","new","york"} ("companies" is
    in _ALWAYS_STRIP); "Choice NY Property Management LLC" -> NY expands
    to new+york, llc strips -> {"choice","new","york","property",
    "management"}. The smaller is a subset of the larger; the two extras,
    "property" and "management", are both in _TOLERABLE_EXTRAS -- match.

    "Shinda Management Corp." and "Shinda Management Corporation" both
    reduce to {"shinda","management"} (corp/corporation are _ALWAYS_STRIP,
    "management" is NOT stripped but appears on both sides) -- sets are
    equal, matches directly.

    "Wasatch Bridge Capital Group" -> {"wasatch","bridge","capital",
    "group"}; "Wasatch Group" -> {"wasatch","group"}. The smaller IS a
    subset of the larger, but one extra token, "bridge", is not in
    _TOLERABLE_EXTRAS -- a real distinguishing proper noun, not a business
    descriptor. Rejected, regardless of "capital" (which IS tolerable) --
    ANY intolerable extra rejects the whole match.

    "Kairos Real Estate Partners" -> {"kairos","real","estate","partners"};
    "Kairos Investment Management" -> {"kairos","investment","management"}.
    Neither is a subset of the other (each side has descriptor words the
    other lacks) -- containment fails outright, rejected before the
    tolerance check is even reached. This is exactly FIX 28's own
    collision (a wrong verdict/contact reused across two different real
    firms), now avoided here by keeping SUFFIX_TOKENS words IN the
    comparable set instead of stripping them -- the opposite of what
    lib_referral's own meaningful_tokens() does, which is why this
    function builds its token sets itself instead of calling that one.
    """
    if not candidate_org_name or not target_firm_name:
        return False
    a = _meaningful_tokens(candidate_org_name)
    b = _meaningful_tokens(target_firm_name)
    if not a or not b:
        return False
    if a == b:
        return True
    smaller, larger = (a, b) if len(a) < len(b) else (b, a)
    if not smaller.issubset(larger):
        return False
    extra = larger - smaller
    return extra.issubset(_TOLERABLE_EXTRAS)


def _rank(people: list[dict], firm_name: str) -> Optional[dict]:
    """Return the most senior finance person whose own organization name
    fuzzy-matches firm_name, or None. Filters to firm-matching candidates
    once, up front, rather than inside the per-tier loop below (which
    would otherwise re-check the same non-matching candidate once per
    tier)."""
    candidates = [p for p in people if _firm_matches(_org_name(p), firm_name)]
    for tier in TIERS:
        for p in candidates:
            t = (p.get("title") or "").lower()
            if not t or EXCLUDE.search(t):
                continue
            if any(_title_matches_keyword(t, kw) for kw in tier):
                return p
    return None


def find_senior_poc(firm_name: str, domain: Optional[str] = None,
                    progress: Callable[[str], None] = _noop):
    """(name, email, title) for the senior finance contact, or None.

    Search order: domain first when a domain is known, name as the
    fallback. A live comparison for the same firm returned 78 people via
    q_organization_domains_list against only 12 via q_organization_name,
    and the senior hit (a CFO) existed only in the domain-scoped result --
    domain search finds more and better candidates when it's available at
    all. Falls back to q_organization_name when there is no domain, or the
    domain search finds no senior-finance hit whose organization actually
    matches firm_name.

    Two Apollo calls on success: one search, one match. The match spends a
    credit. Only email_status == "verified" is accepted.
    """
    key = _key()
    if not key:
        progress("Apollo: no APOLLO_API_KEY set, POC search skipped.")
        return None
    headers = _headers(key)

    seen_count = 0
    hit = None

    if domain:
        domain_people = _search(headers, {"q_organization_domains_list": [domain],
                                          "per_page": 100})
        seen_count += len(domain_people)
        hit = _rank(domain_people, firm_name)

    if not hit:
        name_people = _search(headers, {"q_organization_name": firm_name, "per_page": 100})
        seen_count += len(name_people)
        hit = _rank(name_people, firm_name)

    if not hit:
        progress(f"{firm_name}: Apollo returned no senior finance title "
                 f"({seen_count} people seen).")
        return None

    r = requests.post(MATCH_URL, headers=headers, json={"id": hit["id"]},
                      timeout=TIMEOUT)
    if r.status_code != 200:
        progress(f"{firm_name}: Apollo match failed HTTP {r.status_code}.")
        return None

    person = (r.json() or {}).get("person") or {}
    email = (person.get("email") or "").strip()
    status = person.get("email_status")
    name = person.get("name")
    title = hit.get("title")

    if not email or status != "verified":
        progress(f"{firm_name}: {name or 'contact'} ({title}) has no verified "
                 f"email (status={status}).")
        return None

    progress(f"{firm_name}: {name}, {title}, {email} (verified).")
    return name, email, title
