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
"""
from __future__ import annotations

import re
from typing import Callable, Optional

import requests

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


def _rank(people: list[dict]) -> Optional[dict]:
    """Return the most senior finance person, or None."""
    for tier in TIERS:
        for p in people:
            t = (p.get("title") or "").lower()
            if not t or EXCLUDE.search(t):
                continue
            if any(kw in t for kw in tier):
                return p
    return None


def find_senior_poc(firm_name: str, domain: Optional[str] = None,
                    progress: Callable[[str], None] = _noop):
    """(name, email, title) for the senior finance contact, or None.

    Two Apollo calls on success: one search, one match. The match spends a
    credit. Only email_status == "verified" is accepted.
    """
    key = _key()
    if not key:
        progress("Apollo: no APOLLO_API_KEY set, POC search skipped.")
        return None
    headers = _headers(key)

    people = _search(headers, {"q_organization_name": firm_name, "per_page": 100})
    hit = _rank(people)

    if not hit and domain:
        people = _search(headers, {"q_organization_domains_list": [domain],
                                   "per_page": 100})
        hit = _rank(people)

    if not hit:
        progress(f"{firm_name}: Apollo returned no senior finance title "
                 f"({len(people)} people seen).")
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
