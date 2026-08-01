"""Role-family table for Workflow D's signal email.

Every value here is DETERMINISTIC. Nothing in this module is LLM-generated,
and nothing in it may be: the pain line, the cadence noun and the stack list
go into a cold email as statements of fact about what the seat does, and six
rounds of guarding model prose on the deck taught this project that an
open-class generation failure cannot be closed with a blocklist (BUILD_LOG,
run-30). A posting title maps to exactly one family by table lookup, and the
family supplies fixed strings.

`controller` is the declared default for any title the table does not match,
so an unmatched posting still produces a grammatical, honest email rather
than a blank slot.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional


class RoleFamily(NamedTuple):
    key: str
    pain: str            # "{role_pain} while you run it."
    cadence: str         # "embedded in your systems and your {role_cadence}."
    stack: tuple         # base list for {role_mapped_stack}
    responsibilities: tuple  # canonical Block 2 material when a posting has no description
    titles: tuple        # matching keywords, checked as substrings of the lowercased title


# Ordered most-specific-first: matching is substring-based, so a title
# containing several keywords resolves by this order, not by dict order.
# "assistant controller" and "controller" both land on `controller` anyway,
# but "senior property accountant" must reach property_accounting before any
# broader accountant keyword sees it.
_FAMILIES: tuple = (
    RoleFamily(
        key="property_accounting",
        pain="The close does not pause",
        cadence="close calendar",
        stack=("property-level books and month-end close",
               "CAM reconciliations and true-ups",
               "budget versus actual variance reporting",
               "lender and owner reporting"),
        responsibilities=("property-level books and month-end close",
                          "bank reconciliations",
                          "CAM reconciliations and true-ups",
                          "owner and lender reporting packages"),
        titles=("property accountant", "real estate accountant", "senior accountant"),
    ),
    RoleFamily(
        key="fund_accounting",
        pain="The capital calls do not wait",
        cadence="reporting calendar",
        stack=("capital calls and distributions",
               "partner capital accounts",
               "waterfall allocations",
               "lender and owner reporting"),
        responsibilities=("capital call and distribution processing",
                          "partner capital account maintenance",
                          "waterfall allocations",
                          "quarterly LP reporting packages"),
        titles=("fund accountant", "fund administrator"),
    ),
    RoleFamily(
        key="treasury",
        pain="The cash does not stop moving",
        cadence="cash reporting calendar",
        stack=("daily cash positioning",
               "bank reconciliations",
               "debt service and covenant tracking",
               "lender and owner reporting"),
        responsibilities=("daily cash positioning",
                          "bank reconciliations",
                          "debt service scheduling",
                          "covenant and lender reporting"),
        titles=("treasury analyst", "treasury"),
    ),
    RoleFamily(
        key="ap_ar",
        pain="The invoices do not stop landing",
        cadence="payment calendar",
        stack=("AP and AR processing",
               "tenant billing",
               "vendor and invoice reconciliation",
               "lender and owner reporting"),
        responsibilities=("AP and AR processing",
                          "tenant billing and collections",
                          "vendor and invoice reconciliation",
                          "month-end accruals"),
        titles=("accounts payable", "accounts receivable", "staff accountant"),
    ),
    RoleFamily(
        key="lease_admin",
        pain="The abstracts do not read themselves",
        cadence="lease calendar",
        stack=("lease abstraction",
               "CAM reconciliations and true-ups",
               "recovery and escalation schedules",
               "lender and owner reporting"),
        responsibilities=("lease abstraction and data entry",
                          "CAM reconciliations and true-ups",
                          "recovery and escalation schedules",
                          "critical date tracking"),
        titles=("lease administrator", "lease analyst", "cam analyst",
                "lease administration"),
    ),
    RoleFamily(
        key="underwriting",
        pain="The deals do not wait",
        cadence="deal calendar",
        stack=("deal underwriting models",
               "market and comp analysis",
               "sensitivity runs",
               "investment committee packages"),
        responsibilities=("deal underwriting models",
                          "market and comparable analysis",
                          "sensitivity and scenario runs",
                          "investment committee memos"),
        titles=("acquisitions analyst", "acquisition analyst",
                "asset management analyst"),
    ),
    RoleFamily(
        key="controller",
        pain="The close does not pause",
        cadence="close calendar",
        stack=("month-end close",
               "bank reconciliations",
               "budget versus actual variance reporting",
               "lender and owner reporting"),
        responsibilities=("month-end and year-end close",
                          "bank reconciliations",
                          "budget versus actual variance reporting",
                          "lender and owner reporting packages"),
        titles=("assistant controller", "controller", "accounting manager",
                "financial reporting analyst"),
    ),
)

DEFAULT_FAMILY_KEY = "controller"
BY_KEY = {f.key: f for f in _FAMILIES}


def family_for_title(title: str) -> RoleFamily:
    """The role family a posting title belongs to. Unmatched titles fall to
    `controller`, the declared default -- never None, so the email always has
    a pain line and a cadence noun to put in its fixed sentences."""
    low = (title or "").strip().lower()
    for family in _FAMILIES:
        for keyword in family.titles:
            if keyword in low:
                return family
    return BY_KEY[DEFAULT_FAMILY_KEY]


# ---------------------------------------------------------------------------
# {systems_if_known}
#
# Only these eight, and only when the posting text actually names one. The
# systems clause asserts what the firm runs on; guessing it from the asset
# class would be exactly the kind of unfalsifiable claim the email is built to
# avoid. Longest names first so "Juniper Square" is not shadowed by a shorter
# token, and word-boundary matched so "MRI" does not fire inside a word.
# ---------------------------------------------------------------------------
KNOWN_SYSTEMS: tuple = ("Juniper Square", "RealPage", "AppFolio", "Entrata",
                        "Investran", "Backstop", "Yardi", "MRI")

_SYSTEM_RES = tuple(
    (name, re.compile(r"(?<![A-Za-z0-9])" + re.escape(name).replace(r"\ ", r"\s+")
                      + r"(?![A-Za-z0-9])", re.IGNORECASE))
    for name in KNOWN_SYSTEMS
)


def systems_in(posting_text: str) -> list:
    """The known systems named in the posting text, in KNOWN_SYSTEMS order.
    Empty when the posting has no text at all, which is every posting today
    (see signal_drafting's note on the un-persisted description)."""
    text = posting_text or ""
    if not text.strip():
        return []
    return [name for name, rx in _SYSTEM_RES if rx.search(text)]


def join_systems(systems: list) -> str:
    """"Yardi", "Yardi and MRI", "Yardi, MRI and RealPage"."""
    systems = [s for s in (systems or []) if s]
    if not systems:
        return ""
    if len(systems) == 1:
        return systems[0]
    return ", ".join(systems[:-1]) + " and " + systems[-1]


# ---------------------------------------------------------------------------
# {role_mapped_stack}
#
# The family's base list, plus any additional stack item the POSTING ITSELF
# names. An addition is only made when the posting text contains its trigger,
# so the sentence never claims a responsibility the posting did not mention.
# ---------------------------------------------------------------------------
_STACK_ADDITIONS: tuple = (
    (("cam ", "common area maintenance"), "CAM reconciliations and true-ups"),
    (("waterfall",), "waterfall allocations"),
    (("capital call",), "capital calls and distributions"),
    (("covenant",), "debt service and covenant tracking"),
    (("consolidat",), "multi-entity consolidations"),
    (("1031", "like-kind"), "1031 exchange tracking"),
    (("budget",), "budget versus actual variance reporting"),
    (("audit",), "audit preparation"),
    (("tenant billing", "rent roll"), "tenant billing"),
    (("draw request", "construction draw"), "construction draw packages"),
)


def mapped_stack(title: str, posting_text: str = "") -> str:
    """The comma-joined stack list for this seat: the family's base items plus
    posting-named additions, deduplicated, base order preserved."""
    family = family_for_title(title)
    items = list(family.stack)
    text = (posting_text or "").lower()
    if text.strip():
        for triggers, item in _STACK_ADDITIONS:
            if item in items:
                continue
            if any(t in text for t in triggers):
                items.append(item)
    return ", ".join(items)


def role_variables(title: str, posting_text: str = "") -> dict:
    """Every deterministic variable the email template needs for this seat."""
    family = family_for_title(title)
    systems = systems_in(posting_text)
    return {
        "family": family.key,
        "role_pain": family.pain,
        "role_cadence": family.cadence,
        "role_mapped_stack": mapped_stack(title, posting_text),
        "systems": systems,
        "systems_if_known": join_systems(systems),
        "responsibilities": list(family.responsibilities),
    }
