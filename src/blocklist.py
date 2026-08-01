"""Blocklist maintenance for Workflow D: two tiers, one file editor.

WHY THIS EXISTS. The run-27 funnel audit found that 69% of gate spend went to
firms disqualified as "Not an accepted firm type" -- recruiters, CPA practices
and consultancies that a name check rejects for free. The blocklist is the
free check, and it was being maintained by hand from audit findings.

TWO TIERS, and the split is deliberate.

  AUTO   A firm whose OWN research one-liner says it is a staffing, recruiting,
         talent-placement or executive-search firm. That is not a judgement
         call about fit; it is the firm describing itself as an intermediary,
         and an intermediary is never someone X Analyst can place embedded
         staff with. Appended without confirmation.

  NOTIFY Everything else that reads structurally non-ICP: accounting, advisory
         and consultancy self-descriptions. These are genuinely ambiguous -- a
         real estate family office can describe itself as an advisory, and
         "Accounting and tax advisory for businesses and real estate clients"
         (LG Legacy Group, live) is one keyword away from a firm we would want.
         Suggested only, with /block to accept.

NEVER, in either tier: a firm disqualified on AUM grounds. An AUM misread is
recoverable (the verdict cache expires, /qualify overrides it); a blocklist
entry silently removes the firm from every future run, and nothing re-tests it.
Enforced twice, once by requiring the firm-type reason and once by rejecting
any AUM-shaped reason outright.

THE EVIDENCE IS ALWAYS THE FIRM'S OWN ONE-LINER, never a posting description.
icp_gate's firm_oneliner describes the firm; a job description describes
whoever the job is for, which for a recruiter is its CLIENT. Reading a posting
would auto-block a real estate operator whose posting happened to say "agency
experience preferred". This module never looks at posting text.

Auto-apply writes to a git-tracked file (scanner/config.yaml) and appends an
audit line to BUILD_LOG.md, so every addition is visible in `git status`,
greppable in the log, and reversible with /unblock.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

import yaml

from . import wd_poc

# ---------------------------------------------------------------------------
# Tier signals. Matched against the firm's own self-description only.
#
# STAFFING is the auto tier: an intermediary that sells people. ADVISORY is the
# notify tier: a professional-services firm that sells hours. The two lists are
# disjoint on purpose -- "talent" belongs to staffing, "advisory" does not, and
# a firm matching both is treated as staffing (checked first).
# ---------------------------------------------------------------------------
_STAFFING_RE = re.compile(
    r"\b("
    r"staffing|staff\s+augmentation"
    r"|recruit(?:ing|ment|er|ers)?"
    r"|talent\s+(?:placement|acquisition|solutions|partners?)"
    r"|talent\s+and\s+\w+"
    r"|placement\s+(?:firm|agency|services)|placements?\s+for"
    r"|executive\s+search|search\s+firm|retained\s+search"
    r"|headhunt(?:er|ing)?"
    r"|employment\s+agency|temp\s+agency|contract\s+staffing"
    r"|job\s+board"
    r")\b",
    re.IGNORECASE,
)

# "talent placement for accounting, finance, tax & technology" (Henderson
# Harbor Group, live) is the shape this has to catch, so a bare "talent" next
# to a placement word counts even without one of the compound forms above.
_STAFFING_LOOSE_RE = re.compile(
    r"\btalent\b[^.]{0,40}\b(?:placement|placing|placed|hiring|staffing|search)\b"
    r"|\b(?:placement|placing)\b[^.]{0,40}\btalent\b",
    re.IGNORECASE,
)

_ADVISORY_RE = re.compile(
    r"\b("
    r"cpa|certified\s+public\s+account\w*|public\s+accounting"
    r"|accounting\s+(?:firm|practice|services)|bookkeeping|outsourced\s+accounting"
    r"|audit\s+firm|tax\s+(?:practice|advisory|services)"
    r"|advisory|advisors?"
    r"|consult(?:ing|ancy|ants?)"
    r"|professional\s+services|managed\s+services"
    r"|law\s+firm|legal\s+services"
    r")\b",
    re.IGNORECASE,
)

# The firm-type verdict this whole feature keys off. icp_gate writes it
# verbatim; matched case-insensitively on a substring so a later reword of the
# tail does not silently switch the feature off.
_FIRM_TYPE_REASON_RE = re.compile(r"not an accepted firm type", re.IGNORECASE)

# Any reason that turns on a money figure. Belt and braces alongside the
# firm-type requirement: if icp_gate ever emits a reason carrying both, the AUM
# half wins and the firm is left alone.
_AUM_REASON_RE = re.compile(
    r"\b(?:aum|assets\s+under\s+management|below|above|outside)\b"
    r"|\$\s?[\d.,]+\s*(?:[bmk]\b|billion|million)"
    r"|\bband\b|\baum_unverified\b|\baum_estimated\b",
    re.IGNORECASE,
)

# Business-suffix words that do not make a name distinctive on their own.
_SUFFIX_WORDS = frozenset({
    "group", "capital", "partners", "partner", "holdings", "holding",
    "associates", "advisors", "management", "ventures", "enterprises",
})
# Tokens the normalizer keeps that carry no identity.
_EMPTY_TOKENS = frozenset({"and", "of", "the", "for"})

MIN_SINGLE_TOKEN_LEN = 8


class Candidate(NamedTuple):
    firm_id: Optional[int]
    firm_name: str
    tier: str          # "auto" | "notify"
    evidence: str      # the self-description that classified it


def self_description(research: dict) -> str:
    """The firm's own description. firm_oneliner first, then a description
    field if the gate ever supplies one. Never posting text."""
    research = research or {}
    for key in ("firm_oneliner", "description", "firm_description"):
        value = str(research.get(key) or "").strip()
        if value and value.lower() != "none":
            return value
    return ""


def is_firm_type_disqualification(firm: dict) -> bool:
    """True only for a firm-type disqualification with no AUM reasoning in it."""
    if (firm or {}).get("icp_status") != "disqualified":
        return False
    reason = str((firm or {}).get("icp_reason") or "")
    if not _FIRM_TYPE_REASON_RE.search(reason):
        return False
    return not _AUM_REASON_RE.search(reason)


def tier_for_description(description: str) -> Optional[str]:
    """"auto" for a staffing self-description, "notify" for an advisory one,
    None for anything else. Staffing is checked first so a firm calling itself
    a "recruiting and advisory practice" auto-blocks."""
    text = description or ""
    if not text.strip():
        return None
    if _STAFFING_RE.search(text) or _STAFFING_LOOSE_RE.search(text):
        return "auto"
    if _ADVISORY_RE.search(text):
        return "notify"
    return None


# What lifts safety check 3, and it is DELIBERATELY NARROWER than the tier
# regexes above. A first version reused those, which made the exemption the
# same condition as candidacy and left check 3 unable to ever fire -- dead
# code that read like a safeguard. The distinction that matters: naming the
# firm's own TYPE ("a recruiting firm", "public accounting firm") versus
# naming an activity it happens to perform ("bookkeeping support for
# portfolio companies"), which is exactly what a family office's in-house
# finance team does.
_FIRM_TYPE_NOUN_RE = re.compile(
    r"\b(firm|agency|practice|consultancy|solutions|partners|company|business)\b",
    re.IGNORECASE,
)
_INTERMEDIARY_WORD_RE = re.compile(
    r"\b(staffing|recruit\w*|talent|placement|search|headhunt\w*"
    r"|cpa|accounting|audit|advisory|advisors?|consult\w+|legal|law)\b",
    re.IGNORECASE,
)
# Phrases that are a firm-type declaration on their own, no second noun needed.
_STANDALONE_SELF_DESC_RE = re.compile(
    r"\b(executive\s+search|search\s+firm|staffing\s+firm|staffing\s+agency"
    r"|recruit(?:ing|ment)\s+(?:firm|agency|practice)"
    r"|employment\s+agency|temp\s+agency|headhunt(?:er|ing)"
    r"|public\s+accounting|certified\s+public\s+account\w*|cpa\s+firm"
    r"|accounting\s+firm|audit\s+firm|law\s+firm"
    r"|management\s+consulting|consulting\s+firm|consultancy"
    r"|advisory\s+(?:firm|practice|services))\b",
    re.IGNORECASE,
)


def has_explicit_self_description(description: str) -> bool:
    """Whether the description names the firm's own business TYPE outright.

    True for "a recruiting firm" and "public accounting firm". False for
    "bookkeeping support for portfolio companies", which describes work, not an
    identity, and is what an in-house family office team does."""
    text = description or ""
    if not text.strip():
        return False
    if _STANDALONE_SELF_DESC_RE.search(text):
        return True
    return bool(_INTERMEDIARY_WORD_RE.search(text) and _FIRM_TYPE_NOUN_RE.search(text))


# ---------------------------------------------------------------------------
# The four mandatory safety checks. Every one must pass, in either tier.
# ---------------------------------------------------------------------------
def _content_tokens(name: str) -> set:
    return {t for t in wd_poc._meaningful_tokens(name) if t not in _EMPTY_TOKENS}


def fuzzy_matches_protected(name: str, protected_names) -> Optional[str]:
    """The protected name this candidate collides with, or None.

    Protected = every firm ever QUALIFIED or PARKED in wd_firms. Uses
    wd_poc._firm_matches, the same containment-with-tolerable-extras compare
    already trusted to decide whether an Apollo org is the firm we researched,
    so "Kairos Real Estate Partners" and "Kairos Investment Management" stay
    distinct (FIX 28) while "Choice NY" and "Choice New York Companies" match.
    """
    for protected in (protected_names or []):
        if not protected:
            continue
        if wd_poc._firm_matches(name, protected) or wd_poc._firm_matches(protected, name):
            return protected
    return None


def name_is_distinctive(name: str) -> bool:
    """At least two content tokens, or one token of MIN_SINGLE_TOKEN_LEN+.

    A one-token generic name is what makes a blocklist dangerous: the entry is
    matched as a substring against every future company name, so a bare
    "Metro" would silently drop "Metro Real Estate Partners" forever."""
    tokens = _content_tokens(name)
    if len(tokens) >= 2:
        return True
    return bool(tokens) and max(len(t) for t in tokens) >= MIN_SINGLE_TOKEN_LEN


def is_surname_suffix_pattern(name: str) -> bool:
    """"Raptor Group", "Whitman Capital", "Delaney Partners" -- exactly two
    tokens where the second is a business suffix. That is the standard shape of
    a family office named after its family, an explicit ICP category, so it is
    refused unless the firm says outright what it is."""
    tokens = [t for t in wd_poc.tokenize(name) if t not in _EMPTY_TOKENS]
    if len(tokens) != 2:
        return False
    return tokens[1] in _SUFFIX_WORDS and tokens[0] not in _SUFFIX_WORDS


def covered_by_blocklist(name: str, blocklist) -> Optional[str]:
    """The existing entry that already covers this name, or None. Substring in
    both directions, matching how signal_pipeline._is_staffing applies the
    list."""
    low = (name or "").strip().lower()
    if not low:
        return None
    for entry in (blocklist or []):
        e = str(entry or "").strip().lower()
        if not e:
            continue
        if e in low or low in e:
            return str(entry)
    return None


def safety_failures(name: str, description: str, protected_names, blocklist) -> list:
    """Every mandatory check that rejects this candidate. Empty means safe."""
    failures = []
    hit = fuzzy_matches_protected(name, protected_names)
    if hit:
        failures.append(f"fuzzy_matches_protected_firm:{hit}")
    if not name_is_distinctive(name):
        failures.append("name_not_distinctive")
    if is_surname_suffix_pattern(name) and not has_explicit_self_description(description):
        failures.append("surname_suffix_pattern_without_explicit_self_description")
    covered = covered_by_blocklist(name, blocklist)
    if covered:
        failures.append(f"already_covered_by:{covered}")
    return failures


def classify_firms(firms, protected_names, blocklist) -> tuple:
    """(auto, notify, rejected) for one run's firms.

    `rejected` carries (name, tier, failures) so a candidate dropped by a
    safety check is reportable rather than invisible."""
    auto, notify, rejected = [], [], []
    seen: set = set()
    for firm in (firms or []):
        if not is_firm_type_disqualification(firm):
            continue
        name = str(firm.get("firm_name") or "").strip()
        if not name or name.lower() in seen:
            continue
        description = self_description(firm.get("research"))
        tier = tier_for_description(description)
        if tier is None:
            continue
        seen.add(name.lower())
        failures = safety_failures(name, description, protected_names, blocklist)
        if failures:
            rejected.append((name, tier, failures))
            continue
        candidate = Candidate(firm.get("id"), name, tier, description)
        (auto if tier == "auto" else notify).append(candidate)
    return auto, notify, rejected


# ---------------------------------------------------------------------------
# The config.yaml editor.
#
# LINE-BASED, never a string replace on the document. The blocklist entries are
# short company names and several are substrings of unrelated YAML elsewhere in
# the file ("Talent" appears in TinyFish target names, "Search" in queries), so
# a replace could edit the wrong line. Every write is validated by re-parsing
# the result and confirming the entry list changed the way it was meant to;
# anything else restores the original bytes.
# ---------------------------------------------------------------------------
_BLOCKLIST_KEY_RE = re.compile(r"^(\s*)blocklist:\s*$")
_SAFE_BARE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .&/'()+_-]*$")


class BlocklistFileError(RuntimeError):
    pass


def _yaml_scalar(name: str) -> str:
    """`name` as a YAML scalar: bare when unambiguous, double-quoted when not.
    A name with a colon, a leading dash or a trailing space changes the
    document's meaning if written bare."""
    if _SAFE_BARE_RE.match(name) and name == name.strip():
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _find_span(lines: list) -> tuple:
    """(entry_indent, first_entry_idx, last_entry_idx) for the blocklist block.

    Walks forward from the `blocklist:` key and stops at the first non-blank,
    non-comment line indented no deeper than the key -- i.e. the next mapping
    key -- so an entry is never inserted into whatever section follows."""
    key_idx = next((i for i, ln in enumerate(lines) if _BLOCKLIST_KEY_RE.match(ln)), None)
    if key_idx is None:
        raise BlocklistFileError("no `blocklist:` key found in the scanner config")
    key_indent = len(_BLOCKLIST_KEY_RE.match(lines[key_idx]).group(1))
    first_entry = last_entry = None
    entry_indent = None
    for i in range(key_idx + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("#"):
            continue
        if indent <= key_indent:
            break
        if stripped.startswith("- "):
            if first_entry is None:
                first_entry, entry_indent = i, indent
            last_entry = i
    if last_entry is None:
        raise BlocklistFileError("the blocklist has no entries to anchor an insertion to")
    return entry_indent, first_entry, last_entry


def read_entries(path) -> list:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return list((raw.get("poc_enrichment") or {}).get("blocklist") or [])


def _write_and_validate(path, lines: list, original: str, expect) -> list:
    """Write `lines`, re-parse, and hand back the resulting entry list. Any
    parse failure or unexpected entry list restores `original` and raises."""
    text = "".join(lines)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    try:
        entries = read_entries(path)
    except Exception as e:  # noqa: BLE001 - a corrupt write must never survive
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(original)
        raise BlocklistFileError(f"write left the config unparseable, reverted ({e})") from e
    problem = expect(entries)
    if problem:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(original)
        raise BlocklistFileError(f"write did not take effect as intended, reverted ({problem})")
    return entries


def add_entry(path, name: str, comment: str = "") -> list:
    """Append `name` to the blocklist. Returns the new entry list.

    Refuses a name already covered rather than writing a duplicate, and
    reverts the file if the write does not parse or does not land."""
    name = (name or "").strip()
    if not name:
        raise BlocklistFileError("no name given")
    existing = read_entries(path)
    covered = covered_by_blocklist(name, existing)
    if covered:
        raise BlocklistFileError(f'"{name}" is already covered by the entry "{covered}"')

    with open(path, encoding="utf-8", newline="") as fh:
        original = fh.read()
    lines = original.splitlines(keepends=True)
    entry_indent, _first, last_entry = _find_span(lines)

    if not lines[last_entry].endswith("\n"):
        lines[last_entry] = lines[last_entry] + "\n"
    suffix = f"    # {comment}" if comment else ""
    lines.insert(last_entry + 1, f"{' ' * entry_indent}- {_yaml_scalar(name)}{suffix}\n")

    def expect(entries):
        if name not in entries:
            return f"{name!r} not present after the write"
        if len(entries) != len(existing) + 1:
            return f"entry count went {len(existing)} -> {len(entries)}, expected +1"
        return None

    return _write_and_validate(path, lines, original, expect)


def remove_entry(path, name: str) -> list:
    """Remove the blocklist entry equal to `name`, case-insensitively. Returns
    the new entry list. Reverts on a write that does not parse."""
    name = (name or "").strip()
    if not name:
        raise BlocklistFileError("no name given")
    existing = read_entries(path)
    match = next((e for e in existing if str(e).strip().lower() == name.lower()), None)
    if match is None:
        raise BlocklistFileError(f'"{name}" is not a blocklist entry')

    with open(path, encoding="utf-8", newline="") as fh:
        original = fh.read()
    lines = original.splitlines(keepends=True)
    entry_indent, first_entry, last_entry = _find_span(lines)

    target = None
    for i in range(first_entry, last_entry + 1):
        stripped = lines[i].strip()
        if not stripped.startswith("- "):
            continue
        value = stripped[2:].split("#")[0].strip().strip('"').strip("'")
        if value.lower() == name.lower():
            target = i
            break
    if target is None:
        raise BlocklistFileError(f'could not locate the line for "{name}"')
    if last_entry == first_entry:
        raise BlocklistFileError("refusing to remove the only blocklist entry")
    del lines[target]

    def expect(entries):
        if any(str(e).strip().lower() == name.lower() for e in entries):
            return f"{name!r} still present after the write"
        if len(entries) != len(existing) - 1:
            return f"entry count went {len(existing)} -> {len(entries)}, expected -1"
        return None

    return _write_and_validate(path, lines, original, expect)


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
AUDIT_MARKER = "AUTO-BLOCK"


def audit_line(run_id, candidate: Candidate) -> str:
    evidence = " ".join((candidate.evidence or "").split())
    return (f"- {AUDIT_MARKER} run {run_id}: {candidate.firm_name}. "
            f'Self-description: "{evidence}"\n')


def append_audit(build_log_path, run_id, candidates) -> int:
    """One line per auto-add, so a wrong add is greppable and reversible.
    Never raises into the run: an audit-log failure must not lose the run."""
    lines = [audit_line(run_id, c) for c in (candidates or [])]
    if not lines:
        return 0
    try:
        with open(build_log_path, "a", encoding="utf-8") as fh:
            fh.write("\n" + "".join(lines))
    except OSError:
        return 0
    return len(lines)
