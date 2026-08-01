"""Blocklist maintenance: the auto tier, the notify tier, and the file editor.

The auto tier writes to a git-tracked config file with no confirmation, so
every safety check has its own rejection test and the file editor has its own
revert test. Nothing here touches the real scanner/config.yaml: the editor
tests copy it to tmp_path first, which also means they exercise the real
document's shape (62 entries, comments interleaved) rather than a toy fixture.

Live strings throughout. The auto-tier evidence is Addison Group's and Incendia
Partners' actual research one-liners, the protected-collision case is
Wealthspire (parked in wd_firms and advisory-describing, which is exactly the
collision safety check 1 exists for), and the already-covered cases are entries
the blocklist really holds.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from src import blocklist as bl

REAL_CONFIG = Path(__file__).resolve().parents[1] / "scanner" / "config.yaml"


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("description", [
    "Staffing and professional talent solutions firm (recruiting, consulting)",   # live
    "talent acquisition and recruiting firm (non-real-estate)",                   # live
    "talent placement for accounting, finance, tax & technology",                 # live
    "Executive search firm for the built environment",
    "A retained search practice placing finance leaders",
    "Contract staffing and temp agency services",
    "national recruitment agency",
    "headhunting for private equity",
])
def test_staffing_self_descriptions_go_to_the_auto_tier(description):
    assert bl.tier_for_description(description) == "auto"


@pytest.mark.parametrize("description", [
    "CPA / advisory services for tax, bookkeeping, CFO advisory",                 # live
    "Public accounting firm providing tax, audit, and forensic accounting",       # live
    "Accounting and tax advisory for businesses and real estate clients",         # live
    "global consulting firm, advisory, technology, managed services",             # live
    "Management consulting for government and education",                        # live
    "Accounting services firm, professional services",                            # live
])
def test_advisory_self_descriptions_go_to_the_notify_tier(description):
    assert bl.tier_for_description(description) == "notify"


@pytest.mark.parametrize("description", [
    # Every one a live one-liner from a firm-type disqualification. None is an
    # intermediary, so none is a blocklist candidate at all.
    "Restaurant operator, fast-casual national chain",
    "global financial services firm with large-scale asset & wealth management",
    "Automotive retail operator (large dealer group, EchoPark used-car brand)",
    "Venture / growth investor across technology and digital assets",
    "aerospace launch vehicle manufacturer (rocket company)",
    "Commercial HVAC distribution, service, and building systems",
    "Printing and large-format signage provider",
    "Design-build commercial and institutional general contractor",
    "Endowment investment manager for University of Virginia",
    "", "   ", None,
])
def test_non_intermediary_descriptions_are_not_candidates(description):
    assert bl.tier_for_description(description) is None


def test_a_firm_calling_itself_both_recruiting_and_advisory_auto_blocks():
    """Staffing is checked first on purpose: an intermediary that also sells
    advice is still an intermediary."""
    assert bl.tier_for_description("recruiting and advisory practice") == "auto"


# ---------------------------------------------------------------------------
# Which firms are even eligible
# ---------------------------------------------------------------------------
def _firm(name, status="disqualified", reason="Not an accepted firm type "
          "(RE/family office/PE-RE/property management), disqualified",
          oneliner="", fid=1):
    return {"id": fid, "firm_name": name, "icp_status": status, "icp_reason": reason,
            "research": {"firm_oneliner": oneliner}}


def test_only_firm_type_disqualifications_are_eligible():
    assert bl.is_firm_type_disqualification(_firm("A")) is True
    assert bl.is_firm_type_disqualification(_firm("A", status="qualified")) is False
    assert bl.is_firm_type_disqualification(_firm("A", status="parked")) is False


@pytest.mark.parametrize("reason", [
    # Every one a live icp_reason from an AUM-ground disqualification.
    "AUM ~$230B, exceeds $2B ceiling, disqualified",
    "VOID: divisional AUM figure, group is $4B+, above $2B ceiling",
    "DISQUALIFIED (est. $0M - portfolio value proxy (company-reported))",
    "AUM ~$50M, below $200M floor, disqualified",
    "aum_unverified",
])
def test_aum_ground_disqualifications_are_never_eligible(reason):
    """An AUM misread is recoverable through the cache and /qualify. A
    blocklist entry is not: it removes the firm from every future run and
    nothing re-tests it."""
    assert bl.is_firm_type_disqualification(_firm("A", reason=reason)) is False


def test_a_reason_carrying_both_firm_type_and_aum_is_left_alone():
    """Belt and braces: if the gate ever emits both, the AUM half wins."""
    reason = "Not an accepted firm type, and AUM ~$5B above the $2B ceiling"
    assert bl.is_firm_type_disqualification(_firm("A", reason=reason)) is False


def test_aum_disqualifications_never_reach_either_tier():
    firms = [_firm("Prologis", reason="AUM ~$230B, exceeds $2B ceiling, disqualified",
                   oneliner="A staffing and recruiting firm")]      # tempting description
    auto, notify, rejected = bl.classify_firms(firms, [], [])
    assert (auto, notify, rejected) == ([], [], [])


def test_the_evidence_is_the_firms_own_one_liner_not_posting_text():
    """A posting description belongs to whoever the job is for, which for a
    recruiter is its client. classify_firms only ever reads research."""
    firm = _firm("Greystar", oneliner="")
    firm["research"]["description"] = ""
    firm["posting_description"] = "Agency and staffing recruiting experience preferred"
    auto, notify, _rejected = bl.classify_firms([firm], [], [])
    assert auto == [] and notify == []


@pytest.mark.parametrize("key", ["firm_oneliner", "description", "firm_description"])
def test_self_description_reads_the_research_fields_in_order(key):
    assert bl.self_description({key: "a staffing firm"}) == "a staffing firm"


def test_self_description_ignores_the_literal_none_string():
    assert bl.self_description({"firm_oneliner": "None"}) == ""


# ---------------------------------------------------------------------------
# The four mandatory safety checks, one rejection test each
# ---------------------------------------------------------------------------
def test_check1_rejects_a_near_name_of_a_qualified_or_parked_firm():
    """Wealthspire is PARKED in wd_firms and its one-liner is advisory-shaped,
    so without this check it would be suggested for the blocklist."""
    firms = [_firm("Wealthspire", oneliner="wealth advisory and financial planning")]
    auto, notify, rejected = bl.classify_firms(firms, ["Wealthspire"], [])

    assert (auto, notify) == ([], [])
    assert rejected[0][0] == "Wealthspire"
    assert any("fuzzy_matches_protected_firm" in f for f in rejected[0][2])


def test_check1_uses_the_firm_matches_normalizer_not_string_equality():
    """"Choice NY" and "Choice New York Companies" are the same firm to
    _firm_matches, so a protected long form protects the short one."""
    firms = [_firm("Choice NY", oneliner="a staffing agency")]
    auto, _notify, rejected = bl.classify_firms(
        firms, ["Choice New York Companies"], [])

    assert auto == []
    assert any("fuzzy_matches_protected_firm" in f for f in rejected[0][2])


def test_check1_still_distinguishes_a_fix28_style_collision():
    """The normalizer must not over-match: two genuinely different firms
    sharing a leading token stay distinct (FIX 28)."""
    firms = [_firm("Kairos Recruiting Partners", oneliner="an executive search firm")]
    auto, _notify, _rejected = bl.classify_firms(
        firms, ["Kairos Investment Management"], [])

    assert [c.firm_name for c in auto] == ["Kairos Recruiting Partners"]


@pytest.mark.parametrize("name", ["Metro", "Apex", "Summit", "Core", "Vista"])
def test_check2_rejects_a_bare_generic_single_token(name):
    """A blocklist entry is matched as a substring against every future company
    name, so a bare "Metro" would silently drop "Metro Real Estate Partners"
    forever."""
    firms = [_firm(name, oneliner="a staffing and recruiting firm")]
    auto, _notify, rejected = bl.classify_firms(firms, [], [])

    assert auto == []
    assert "name_not_distinctive" in rejected[0][2]


@pytest.mark.parametrize("name,ok", [
    ("Guidehouse", True),          # 10 chars, one token
    ("PrideStaff", True),          # 10 chars
    ("W3Global", True),            # 8 chars, at the floor
    ("Kforce", False),             # 6 chars, under it
    ("Aston Carter", True),        # two tokens
    ("CPA Connections", True),     # two tokens
])
def test_check2_single_token_floor_and_two_token_pass(name, ok):
    assert bl.name_is_distinctive(name) is ok


def test_check2_ignores_tokens_that_carry_no_identity():
    """"Klausner & Company PC" normalizes to {klausner, and}: one real token,
    long enough to stand alone. "and" must not be what makes it pass."""
    assert bl.name_is_distinctive("Klausner & Company PC") is True
    assert bl.name_is_distinctive("Ace & Co") is False


def test_check3_rejects_a_surname_plus_suffix_without_an_explicit_description():
    """The standard shape of a family office named after its family, which is
    an explicit ICP category."""
    firms = [_firm("Raptor Group", oneliner="bookkeeping support for portfolio companies")]
    auto, notify, rejected = bl.classify_firms(firms, [], [])

    assert (auto, notify) == ([], [])
    assert "surname_suffix_pattern_without_explicit_self_description" in rejected[0][2]


def test_check3_allows_a_surname_plus_suffix_when_the_firm_says_what_it_is():
    """Live: "Addison Group" and "Incendia Partners" are both surname+suffix,
    and both call themselves recruiters outright."""
    firms = [
        _firm("Addison Group", fid=1,
              oneliner="Staffing and professional talent solutions firm (recruiting)"),
        _firm("Incendia Partners", fid=2,
              oneliner="talent acquisition and recruiting firm (non-real-estate)"),
    ]
    auto, _notify, rejected = bl.classify_firms(firms, [], [])

    assert sorted(c.firm_name for c in auto) == ["Addison Group", "Incendia Partners"]
    assert rejected == []


@pytest.mark.parametrize("name,is_pattern", [
    ("Raptor Group", True),
    ("Whitman Capital", True),
    ("Delaney Partners", True),
    ("Henderson Harbor Group", False),      # three tokens
    ("Group Capital", False),               # both tokens are suffixes
    ("Aston Carter", False),                # no suffix word
    ("Guidehouse", False),                  # one token
])
def test_check3_pattern_detection(name, is_pattern):
    assert bl.is_surname_suffix_pattern(name) is is_pattern


@pytest.mark.parametrize("name,entry", [
    ("Henderson Harbor Group", "Henderson Harbor Group"),   # exact
    ("Robert Half International", "Robert Half"),           # entry inside name
    ("Talent", "Talent Edge Recruiting"),                   # name inside entry
    ("PRIDESTAFF", "PrideStaff"),                           # case
])
def test_check4_rejects_anything_an_existing_entry_already_covers(name, entry):
    firms = [_firm(name, oneliner="a staffing and recruiting firm")]
    auto, _notify, rejected = bl.classify_firms(firms, [], [entry])

    assert auto == []
    assert any("already_covered_by" in f for f in rejected[0][2])


def test_all_four_checks_pass_for_a_clean_staffing_firm():
    firms = [_firm("Incendia Partners",
                   oneliner="talent acquisition and recruiting firm (non-real-estate)")]
    auto, notify, rejected = bl.classify_firms(firms, ["Neal Communities"], ["Vaco", "Jobot"])

    assert [c.firm_name for c in auto] == ["Incendia Partners"]
    assert notify == [] and rejected == []
    assert auto[0].tier == "auto"
    assert "recruiting" in auto[0].evidence


def test_advisory_firms_go_to_notify_not_auto():
    firms = [_firm("Klausner Accounting Services",
                   oneliner="Public accounting firm providing tax and audit services")]
    auto, notify, _rejected = bl.classify_firms(firms, [], [])

    assert auto == []
    assert [c.firm_name for c in notify] == ["Klausner Accounting Services"]
    assert notify[0].tier == "notify"


def test_the_same_firm_twice_in_a_run_is_suggested_once():
    firms = [_firm("Addison Group", fid=1, oneliner="a staffing firm"),
             _firm("addison group", fid=2, oneliner="a staffing firm")]
    auto, _notify, _rejected = bl.classify_firms(firms, [], [])

    assert len(auto) == 1


# ---------------------------------------------------------------------------
# The config.yaml editor, against a copy of the real document
# ---------------------------------------------------------------------------
@pytest.fixture
def cfg(tmp_path):
    dest = tmp_path / "config.yaml"
    shutil.copy(REAL_CONFIG, dest)
    return dest


def test_add_entry_appends_and_round_trips(cfg):
    before = bl.read_entries(cfg)

    after = bl.add_entry(cfg, "Addison Group", "auto-added run 34: staffing firm")

    assert len(after) == len(before) + 1
    assert after[-1] == "Addison Group"
    assert bl.read_entries(cfg)[-1] == "Addison Group"


def test_add_entry_writes_the_comment(cfg):
    bl.add_entry(cfg, "Addison Group", "auto-added run 34: staffing firm")

    line = next(l for l in cfg.read_text(encoding="utf-8").splitlines()
                if "Addison Group" in l)
    assert line.strip().startswith("- Addison Group")
    assert "# auto-added run 34: staffing firm" in line


def test_add_entry_is_line_based_and_changes_nothing_else(cfg):
    """"Talent" and "Search" appear in TinyFish target names and aggregator
    queries elsewhere in this document, which is why a string replace could
    edit the wrong line."""
    original = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))

    bl.add_entry(cfg, "Addison Group", "c")

    patched = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    added = [e for e in patched["poc_enrichment"]["blocklist"]
             if e not in original["poc_enrichment"]["blocklist"]]
    assert added == ["Addison Group"]
    original["poc_enrichment"]["blocklist"] = None
    patched["poc_enrichment"]["blocklist"] = None
    assert patched == original


def test_add_entry_quotes_a_name_that_would_change_the_document(cfg):
    added = bl.add_entry(cfg, "Zephyr: Advisors Co", "c")

    assert "Zephyr: Advisors Co" in added
    line = next(l for l in cfg.read_text(encoding="utf-8").splitlines() if "Zephyr" in l)
    assert '- "Zephyr: Advisors Co"' in line


def test_add_entry_refuses_a_duplicate(cfg):
    with pytest.raises(bl.BlocklistFileError, match="already covered"):
        bl.add_entry(cfg, "Vaco", "c")


def test_add_entry_refuses_a_name_an_entry_already_covers(cfg):
    with pytest.raises(bl.BlocklistFileError, match="already covered"):
        bl.add_entry(cfg, "Robert Half International", "c")


def test_add_entry_reverts_when_the_write_would_not_parse(cfg, monkeypatch):
    original = cfg.read_text(encoding="utf-8")
    real = bl._write_and_validate

    def sabotage(path, lines, orig, expect):
        return real(path, list(lines) + ["  : not valid yaml : :\n"], orig, expect)

    monkeypatch.setattr(bl, "_write_and_validate", sabotage)

    with pytest.raises(bl.BlocklistFileError, match="reverted"):
        bl.add_entry(cfg, "Sabotage Co", "c")

    assert cfg.read_text(encoding="utf-8") == original
    assert bl.read_entries(cfg)                      # still parses


def test_remove_entry_removes_cleanly(cfg):
    before = bl.read_entries(cfg)
    bl.add_entry(cfg, "Addison Group", "c")

    after = bl.remove_entry(cfg, "Addison Group")

    assert after == before
    assert "Addison Group" not in cfg.read_text(encoding="utf-8")


def test_add_then_remove_restores_the_file_byte_for_byte(cfg):
    original = cfg.read_text(encoding="utf-8")

    bl.add_entry(cfg, "Addison Group", "auto-added run 34: staffing")
    bl.remove_entry(cfg, "Addison Group")

    assert cfg.read_text(encoding="utf-8") == original


def test_remove_entry_is_case_insensitive(cfg):
    bl.add_entry(cfg, "Addison Group", "c")

    bl.remove_entry(cfg, "addison GROUP")

    assert "Addison Group" not in bl.read_entries(cfg)


def test_remove_entry_refuses_a_name_that_is_not_an_entry(cfg):
    with pytest.raises(bl.BlocklistFileError, match="not a blocklist entry"):
        bl.remove_entry(cfg, "Never Existed Co")


def test_remove_entry_removes_only_the_named_line(cfg):
    before = bl.read_entries(cfg)

    bl.remove_entry(cfg, "Vaco")

    after = bl.read_entries(cfg)
    assert len(after) == len(before) - 1
    assert "Vaco" not in after
    assert set(before) - set(after) == {"Vaco"}


def test_editor_raises_when_there_is_no_blocklist_key(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("poc_enrichment:\n  enabled: false\n", encoding="utf-8")

    with pytest.raises(bl.BlocklistFileError, match="no `blocklist:` key"):
        bl.add_entry(path, "Addison Group", "c")


def test_editor_raises_when_the_blocklist_has_no_entries(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("poc_enrichment:\n  blocklist:\nweb_app:\n  enabled: false\n",
                    encoding="utf-8")

    with pytest.raises(bl.BlocklistFileError, match="no entries to anchor"):
        bl.add_entry(path, "Addison Group", "c")


def test_insertion_stays_inside_the_blocklist_block(tmp_path):
    """The walk stops at the next mapping key, so an entry never lands in the
    section that follows."""
    path = tmp_path / "c.yaml"
    path.write_text(
        "poc_enrichment:\n"
        "  blocklist:\n"
        "    - Vaco\n"
        "    - Jobot\n"
        "\n"
        "web_app:\n"
        "  enabled: false\n",
        encoding="utf-8")

    bl.add_entry(path, "Addison Group", "c")

    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert parsed["poc_enrichment"]["blocklist"] == ["Vaco", "Jobot", "Addison Group"]
    assert parsed["web_app"] == {"enabled": False}


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
def test_audit_line_carries_run_id_name_and_evidence():
    candidate = bl.Candidate(1, "Addison Group", "auto",
                             "Staffing and professional talent solutions firm")
    line = bl.audit_line(34, candidate)

    assert bl.AUDIT_MARKER in line
    assert "run 34" in line
    assert "Addison Group" in line
    assert "Staffing and professional talent solutions firm" in line
    assert "—" not in line          # no em dash, CLAUDE.md style rules


def test_append_audit_writes_one_line_per_add(tmp_path):
    log = tmp_path / "BUILD_LOG.md"
    log.write_text("# existing content\n", encoding="utf-8")
    candidates = [bl.Candidate(1, "Addison Group", "auto", "a staffing firm"),
                  bl.Candidate(2, "Incendia Partners", "auto", "a recruiting firm")]

    assert bl.append_audit(log, 34, candidates) == 2

    text = log.read_text(encoding="utf-8")
    assert text.startswith("# existing content")
    assert text.count(bl.AUDIT_MARKER) == 2
    assert "Addison Group" in text and "Incendia Partners" in text


def test_append_audit_does_nothing_for_no_candidates(tmp_path):
    log = tmp_path / "BUILD_LOG.md"
    log.write_text("x\n", encoding="utf-8")

    assert bl.append_audit(log, 34, []) == 0
    assert log.read_text(encoding="utf-8") == "x\n"


def test_append_audit_never_raises_on_an_unwritable_path(tmp_path):
    """An audit-log failure must not lose a completed run."""
    candidate = bl.Candidate(1, "Addison Group", "auto", "a staffing firm")

    assert bl.append_audit(tmp_path / "no" / "such" / "dir" / "log.md", 34, [candidate]) == 0
