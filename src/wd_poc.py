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
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import requests

from lib_referral.matching import normalize as name_normalize

SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
MATCH_URL = "https://api.apollo.io/api/v1/people/match"
TIMEOUT = 60

# Ordered by seniority. First tier with a hit wins.
TIERS = [
    ("chief financial officer", "cfo"),
    ("controller",),
    ("svp of finance", "svp finance", "senior vice president of finance",
     "vp of finance", "vp finance", "vice president of finance",
     "vice president of corporate finance", "director of finance", "head of finance"),
    ("finance manager", "financial manager", "finance director"),
    ("accounting manager", "director of accounting"),
]
EXCLUDE = re.compile(r"\b(intern|internship|assistant to|coordinator|clerk)\b", re.I)


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


def _firm_matches(candidate_org_name: str, target_firm_name: str) -> bool:
    """True if candidate_org_name plausibly names the same firm as
    target_firm_name. Fuzzy via lib_referral's own normalizer
    (meaningful_tokens -- suffix/generic words stripped, e.g. Capital,
    Group, Management, Corp/Corporation), not a new one: set equality on
    each side's meaningful tokens.

    "Shinda Management Corp." and "Shinda Management Corporation" both
    reduce to {"shinda"} (management/corp/corporation are all suffix
    tokens) and match. "Wasatch Bridge Capital Group" reduces to
    {"wasatch", "bridge"} while "Wasatch Group" reduces to just {"wasatch"}
    -- not equal, correctly rejected, since "bridge" is a real
    distinguishing token neither side's suffix list strips. Set comparison
    rather than a joined-string comparison so token order doesn't matter
    (Apollo's org name and the scanner's company name are not guaranteed to
    order words the same way).

    Known tradeoff, not a new bug: lib_referral's SUFFIX_TOKENS strips
    "capital"/"group"/"management"/"real"/"estate" as generic words --
    broader than wd_dbc.firm_key's deliberately narrow legal-forms-only
    list (FIX 28's own protection against "Kairos Real Estate Partners"
    colliding with "Kairos Investment Management"). Reusing lib_referral's
    existing normalizer here, as instructed, inherits that broader
    collision risk in this new context -- a firm named e.g. "Kairos Real
    Estate" could still fuzzy-match an Apollo hit for "Kairos Management"
    under this check. Not solved here: the instruction is to reuse the
    existing normalizer, not write a new one.
    """
    if not candidate_org_name or not target_firm_name:
        return False
    a = set(name_normalize.meaningful_tokens(candidate_org_name))
    b = set(name_normalize.meaningful_tokens(target_firm_name))
    if not a or not b:
        return False
    return a == b


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
            if any(kw in t for kw in tier):
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
