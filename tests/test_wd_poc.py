"""src/wd_poc.py (NOT vendored, closes the Apollo POC-search gap).

Three things under adversarial test here:
1. Search order: q_organization_domains_list first when a domain exists
   (a live comparison found 78 people via domain vs 12 via name for the
   same firm, with the CFO hit only in the domain-scoped result),
   q_organization_name as the fallback.
2. _firm_matches's containment rule (not strict equality -- see the
   module docstring for why containment alone isn't enough and the extra
   tokens must be checked against _TOLERABLE_EXTRAS, not lib_referral's
   full SUFFIX_TOKENS): "Choice New York Companies" must match "Choice NY
   Property Management LLC" (an abbreviation plus a merely-less-detailed
   name, both live-observed -- Apollo returned this pair 41 times for one
   real firm); "Shinda Management Corp." must match "Shinda Management
   Corporation" (pure legal-suffix variation); "Wasatch Bridge Capital
   Group" must NOT match "Wasatch Group" (a real distinguishing token,
   "Bridge", differs); "Kairos Real Estate Partners" must NOT match
   "Kairos Investment Management" (FIX 28's own collision shape -- two
   different, non-empty business-descriptor sets, not one side simply
   omitting detail); "Acme Capital Partners" must NOT match "Beta Real
   Estate Holdings" (completely unrelated).
3. TIERS recognizes senior finance titles at firms with no CFO (SVP/VP of
   Accounting, Portfolio/Corporate Controller, Assistant Controller, ...),
   correctly seniority-ordered -- including the one real collision this
   surfaced: plain substring matching would have ranked "Assistant
   Controller" as equal seniority to "Controller" (the substring
   "controller" is IN "assistant controller"), so a naive scan could pick
   whichever one Apollo happened to list first when both exist at the same
   firm.
4. The executive tier (Principal, Founder, President, CEO, COO, Partner,
   ...) added 2026-08-02: outranks the SVP/VP-of-Finance/Accounting tier,
   which outranks Controller, which outranks Assistant Controller -- and
   five substring collisions this surfaced (three named live, two found by
   this file's own exhaustive pairwise check): "partner" must not catch
   "Partnership Accountant" or "Finance Business Partner"; "president"
   must not catch "Vice President of Finance" or "Senior Vice President of
   Accounting"; "principal" must not catch "Principal Accountant";
   "managing director" must not catch "Managing Director of
   Accounting"/"...of Finance" (these correctly fall through to their own,
   already-existing lower tiers instead of vanishing).
5. find_senior_poc walks every ranked candidate (not just the top one),
   calling people/match until one comes back verified, capped at
   MAX_MATCH_ATTEMPTS -- an unverified top candidate no longer kills the
   whole search when a verified one exists further down the ranking.

No network: _search and the final requests.post (people/match) are
monkeypatched directly. lib_referral/ and lib_snapshot/ are read, never
edited.
"""
from __future__ import annotations

import pytest

from src import wd_poc


@pytest.fixture(autouse=True)
def _fake_key(monkeypatch):
    monkeypatch.setattr(wd_poc, "_key", lambda: "fake-apollo-key")


def _person(name, title, org_name, person_id=None):
    return {"id": person_id or name, "title": title,
           "organization": {"name": org_name}}


class _FakeMatchResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _mock_match(monkeypatch, name, email, status="verified"):
    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == wd_poc.MATCH_URL
        return _FakeMatchResponse(200, {"person": {"name": name, "email": email,
                                                    "email_status": status}})
    monkeypatch.setattr(wd_poc.requests, "post", fake_post)


def _mock_match_by_id(monkeypatch, responses: dict):
    """Like _mock_match, but keyed by candidate id -- needed to test
    find_senior_poc's multi-candidate walk, where different candidates
    must get different match outcomes. responses maps id -> either an int
    (HTTP status code, for a failed call) or a (name, email, status)
    3-tuple (for a 200 response). Records every id posted, in call order,
    on the returned fake's .calls, so a test can assert exactly how many
    attempts were made and in what order."""
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        assert url == wd_poc.MATCH_URL
        pid = json["id"]
        calls.append(pid)
        resp = responses[pid]
        if isinstance(resp, int):
            return _FakeMatchResponse(resp, {})
        name, email, status = resp
        return _FakeMatchResponse(200, {"person": {"name": name, "email": email,
                                                    "email_status": status}})

    fake_post.calls = calls
    monkeypatch.setattr(wd_poc.requests, "post", fake_post)
    return fake_post


# ---------------------------------------------------------------------------
# _firm_matches: adversarial fuzzy-match matrix
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("candidate,target", [
    ("Shinda Management Corp.", "Shinda Management Corporation"),
    ("Shinda Management Corporation", "Shinda Management Corp."),
    ("Shinda Management", "Shinda Management Corp."),  # bare name, no suffix at all
    ("SHINDA MANAGEMENT CORP", "shinda management corporation"),  # case-insensitive
    # Live-observed: 41 Apollo domain hits for this exact pair, all rejected
    # by the old set-equality check ({choice,ny} != {choice,new,york}).
    ("Choice New York Companies", "Choice NY Property Management LLC"),
    ("Choice NY Property Management LLC", "Choice New York Companies"),
    ("Choice NY Companies", "Choice New York Property Management LLC"),
])
def test_firm_matches_legal_suffix_variants(candidate, target):
    assert wd_poc._firm_matches(candidate, target) is True


@pytest.mark.parametrize("candidate,target", [
    ("Wasatch Group", "Wasatch Bridge Capital Group"),
    ("Wasatch Bridge Capital Group", "Wasatch Group"),
    ("Meridian Realty Partners", "Meridian Bridge Capital"),  # {"meridian"} vs {"meridian","bridge"}
    # FIX 28's own collision shape: two DIFFERENT, non-empty
    # business-descriptor sets, not one side simply omitting detail.
    ("Kairos Real Estate Partners", "Kairos Investment Management"),
    ("Kairos Investment Management", "Kairos Real Estate Partners"),
])
def test_firm_matches_rejects_distinguishing_token_mismatch(candidate, target):
    assert wd_poc._firm_matches(candidate, target) is False


def test_firm_matches_wasatch_case_exactly_as_specified():
    """The exact adversarial pair given: must NOT match, in either direction."""
    assert wd_poc._firm_matches("Wasatch Group", "Wasatch Bridge Capital Group") is False
    assert wd_poc._firm_matches("Wasatch Bridge Capital Group", "Wasatch Group") is False


def test_firm_matches_shinda_case_exactly_as_specified():
    """The exact adversarial pair given: must match."""
    assert wd_poc._firm_matches("Shinda Management Corp.", "Shinda Management Corporation") is True


def test_firm_matches_choice_case_exactly_as_specified():
    """The exact live-observed pair: must match. "NY" is an abbreviation of
    "New York", not a distinguishing token."""
    assert wd_poc._firm_matches("Choice New York Companies",
                                "Choice NY Property Management LLC") is True


def test_firm_matches_kairos_case_exactly_as_specified():
    """The exact adversarial pair given: must NOT match."""
    assert wd_poc._firm_matches("Kairos Real Estate Partners",
                                "Kairos Investment Management") is False


def test_firm_matches_acme_beta_case_exactly_as_specified():
    """The exact adversarial pair given: must NOT match."""
    assert wd_poc._firm_matches("Acme Capital Partners", "Beta Real Estate Holdings") is False


def test_firm_matches_empty_or_none_never_matches():
    assert wd_poc._firm_matches("", "Shinda Management Corp.") is False
    assert wd_poc._firm_matches("Shinda Management Corp.", "") is False
    assert wd_poc._firm_matches(None, "Shinda Management Corp.") is False
    assert wd_poc._firm_matches("Shinda Management Corp.", None) is False


def test_firm_matches_completely_unrelated_names():
    assert wd_poc._firm_matches("Acme Capital Partners", "Beta Real Estate Holdings") is False


@pytest.mark.parametrize("abbrev,spelled_out", [
    ("Choice NJ Holdings", "Choice New Jersey Holdings"),
    ("Choice CA Holdings", "Choice California Holdings"),
    ("Choice LA Holdings", "Choice Los Angeles Holdings"),
    ("Choice SF Holdings", "Choice San Francisco Holdings"),
    ("Acme Intl Partners", "Acme International Partners"),
    ("Acme Mgmt", "Acme Management"),
    ("Acme Assoc", "Acme Associates"),
    ("Acme Ptnrs", "Acme Partners"),
])
def test_firm_matches_other_required_abbreviations(abbrev, spelled_out):
    assert wd_poc._firm_matches(abbrev, spelled_out) is True


# ---------------------------------------------------------------------------
# _rank: integrates _firm_matches with the seniority tiers
# ---------------------------------------------------------------------------
def test_rank_excludes_a_title_qualifying_candidate_from_the_wrong_org():
    people = [
        _person("Jane CFO", "Chief Financial Officer", "Wasatch Group"),
    ]
    # Target firm is "Wasatch Bridge Capital Group" -- Jane's org, "Wasatch
    # Group", does not fuzzy-match it (missing "Bridge"). Even though her
    # title is the most senior tier, she must be excluded.
    assert wd_poc._rank(people, "Wasatch Bridge Capital Group") is None


def test_rank_accepts_a_legal_suffix_variant_org_name():
    people = [
        _person("Jane CFO", "Chief Financial Officer", "Shinda Management Corp."),
    ]
    hit = wd_poc._rank(people, "Shinda Management Corporation")
    assert hit is not None
    assert hit["title"] == "Chief Financial Officer"


def test_rank_picks_the_most_senior_matching_candidate():
    people = [
        _person("Ann Manager", "Accounting Manager", "Shinda Management Corp."),
        _person("Ben CFO", "Chief Financial Officer", "Shinda Management Corp."),
        _person("Cara Controller", "Controller", "Shinda Management Corp."),
    ]
    hit = wd_poc._rank(people, "Shinda Management Corporation")
    assert hit["title"] == "Chief Financial Officer"


# ---------------------------------------------------------------------------
# TIERS extension: senior finance titles at firms with no CFO
# ---------------------------------------------------------------------------
FIRM = "Acme Capital Partners"


@pytest.mark.parametrize("title", [
    "SVP of Accounting",
    "Senior Vice President of Accounting",
    "Portfolio Controller",
    "VP Corporate Accounting",
    "VP of Accounting",
    "Corporate Controller",
    "Director of Accounting",
    "Assistant Controller",
])
def test_rank_recognizes_new_senior_titles_with_no_cfo_present(title):
    people = [_person("a", title, FIRM)]
    hit = wd_poc._rank(people, FIRM)
    assert hit is not None
    assert hit["title"] == title


def test_rank_ranks_controller_above_assistant_controller_regardless_of_list_order():
    """The real collision this surfaced: plain substring matching means
    "controller" in "assistant controller" is True, so a naive scan could
    rank an Assistant Controller as equal to a full Controller and pick
    whichever one Apollo happened to list first."""
    assistant_first = [_person("assistant", "Assistant Controller", FIRM),
                       _person("full", "Controller", FIRM)]
    controller_first = [_person("full", "Controller", FIRM),
                        _person("assistant", "Assistant Controller", FIRM)]
    assert wd_poc._rank(assistant_first, FIRM)["title"] == "Controller"
    assert wd_poc._rank(controller_first, FIRM)["title"] == "Controller"


def test_rank_ranks_assistant_controller_above_finance_manager():
    people = [_person("fm", "Finance Manager", FIRM),
             _person("ac", "Assistant Controller", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "Assistant Controller"


def test_rank_ranks_assistant_controller_below_svp_of_accounting():
    people = [_person("svp", "SVP of Accounting", FIRM),
             _person("ac", "Assistant Controller", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "SVP of Accounting"


def test_rank_portfolio_and_corporate_controller_rank_with_plain_controller():
    """Same seniority tier as plain Controller -- a scope qualifier only,
    not a demotion."""
    people = [_person("pc", "Portfolio Controller", FIRM),
             _person("fm", "Finance Manager", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "Portfolio Controller"


def test_title_matches_keyword_controller_excludes_assistant():
    assert wd_poc._title_matches_keyword("assistant controller", "controller") is False
    assert wd_poc._title_matches_keyword("controller", "controller") is True
    assert wd_poc._title_matches_keyword("corporate controller", "controller") is True
    assert wd_poc._title_matches_keyword("portfolio controller", "controller") is True


# ---------------------------------------------------------------------------
# TIERS extension 2026-08-02: executive tier (no-CFO economic buyer) and
# the seniority chain it has to fit into: CFO > Executive > SVP/VP of
# Finance-and-Accounting > Controller.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("title", [
    "Principal",
    "Founder",
    "Co-Founder",
    "Owner",
    "Managing Partner",
    "Managing Director",
    "President",
    "Chief Executive Officer",
    "CEO",
    "Chief Operating Officer",
    "COO",
    "Partner",
])
def test_rank_recognizes_new_executive_titles_with_no_cfo_present(title):
    people = [_person("a", title, FIRM)]
    hit = wd_poc._rank(people, FIRM)
    assert hit is not None
    assert hit["title"] == title


def test_cfo_outranks_principal():
    people = [_person("p", "Principal", FIRM), _person("c", "Chief Financial Officer", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "Chief Financial Officer"


def test_principal_outranks_svp_of_accounting():
    people = [_person("s", "SVP of Accounting", FIRM), _person("p", "Principal", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "Principal"


def test_svp_of_accounting_outranks_controller():
    people = [_person("c", "Controller", FIRM), _person("s", "SVP of Accounting", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "SVP of Accounting"


# Live-named collisions: adding the executive tier's keywords must not
# reach into titles that belong to other, already-established tiers.
def test_title_matches_keyword_partner_excludes_partnership_accountant():
    assert wd_poc._title_matches_keyword("partnership accountant", "partner") is False
    assert wd_poc._title_matches_keyword("partner", "partner") is True
    assert wd_poc._title_matches_keyword("managing partner", "partner") is True


def test_title_matches_keyword_president_excludes_vice_president_titles():
    assert wd_poc._title_matches_keyword("vice president of finance", "president") is False
    assert wd_poc._title_matches_keyword("senior vice president of accounting", "president") is False
    assert wd_poc._title_matches_keyword("president", "president") is True


def test_title_matches_keyword_principal_excludes_principal_accountant():
    assert wd_poc._title_matches_keyword("principal accountant", "principal") is False
    assert wd_poc._title_matches_keyword("principal", "principal") is True


# Self-found during the exhaustive pairwise check, same shape of problem as
# the three named above, not explicitly called out but real collisions.
def test_title_matches_keyword_managing_director_excludes_function_scoped_roles():
    assert wd_poc._title_matches_keyword("managing director of accounting", "managing director") is False
    assert wd_poc._title_matches_keyword("managing director of finance", "managing director") is False
    assert wd_poc._title_matches_keyword("managing director", "managing director") is True


def test_title_matches_keyword_partner_excludes_finance_business_partner():
    assert wd_poc._title_matches_keyword("finance business partner", "partner") is False


@pytest.mark.parametrize("colliding_title", [
    "Partnership Accountant",
    "Principal Accountant",
    "Finance Business Partner",
])
def test_rank_collisions_never_land_in_the_executive_tier(colliding_title):
    """None of these are recognized senior-finance titles in any tier, so a
    solo candidate with one of these titles must not rank at all -- if any
    of them wrongly matched the executive tier, this candidate would come
    back as a hit instead of None."""
    people = [_person("a", colliding_title, FIRM)]
    assert wd_poc._rank(people, FIRM) is None


@pytest.mark.parametrize("colliding_title", [
    "Vice President of Finance",
    "Senior Vice President of Accounting",
])
def test_rank_vice_president_titles_land_in_svp_vp_tier_not_executive(colliding_title):
    """These DO belong to the existing SVP/VP-of-Finance tier -- confirm
    they still rank there (not swallowed by the executive tier's
    "president" keyword, and not dropped entirely) by checking a real
    executive still outranks them."""
    people = [_person("a", colliding_title, FIRM), _person("b", "Principal", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "Principal"
    solo = [_person("a", colliding_title, FIRM)]
    assert wd_poc._rank(solo, FIRM)["title"] == colliding_title


def test_rank_managing_director_of_accounting_falls_through_to_accounting_tier():
    people = [_person("a", "Managing Director of Accounting", FIRM),
             _person("b", "Chief Financial Officer", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "Chief Financial Officer"
    solo = [_person("a", "Managing Director of Accounting", FIRM)]
    assert wd_poc._rank(solo, FIRM)["title"] == "Managing Director of Accounting"


def test_rank_managing_director_of_finance_falls_through_to_svp_vp_tier():
    people = [_person("a", "Managing Director of Finance", FIRM),
             _person("b", "Principal", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "Principal"


# ---------------------------------------------------------------------------
# Run 27 fix: "principal" as a SENIORITY PREFIX (engineering/consulting/
# science), not the role itself, must never match the executive tier. Live
# evidence: Apollo returned "Rao Iqbal, Principal Backend Engineer" at
# AlphaX and it wrongly drafted as an executive contact. Same prefix-vs-role
# audit applied to every other executive keyword -- "owner" and "partner"
# both needed the identical fix.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("title", [
    "Principal", "Managing Principal", "Founding Principal",
    "Principal & CEO", "Principal, Real Estate",
])
def test_title_matches_keyword_principal_matches_when_principal_is_the_role(title):
    assert wd_poc._title_matches_keyword(title.lower(), "principal") is True


@pytest.mark.parametrize("colliding_title", [
    "Principal Backend Engineer",   # the exact run-27 live false positive
    "Principal Engineer",
    "Principal Developer",
    "Principal Architect",
    "Principal Scientist",
    "Principal Consultant",
    "Principal Analyst",
    "Principal Accountant",
    "Principal Designer",
    "Principal Researcher",
    "Principal Product Manager",
    "Principal Program Manager",
    "Principal Data Scientist",
    "Principal Data Engineer",
    "Principal Software Engineer",
    "Principal Frontend Engineer",
    "Principal Security Engineer",
    "Principal Technical Program Manager",
    "Principal Solutions Architect",
    "Principal Sales Engineer",
])
def test_title_matches_keyword_principal_excludes_occupational_prefixes(colliding_title):
    assert wd_poc._title_matches_keyword(colliding_title.lower(), "principal") is False


def test_rank_alphax_run27_false_positive_no_longer_ranks_as_executive():
    """The exact live case: a solo "Principal Backend Engineer" candidate
    must not rank at all (no tier recognizes an engineering title), and
    must not outrank a genuine executive."""
    solo = [_person("a", "Principal Backend Engineer", FIRM)]
    assert wd_poc._rank(solo, FIRM) is None
    people = [_person("a", "Principal Backend Engineer", FIRM),
             _person("b", "Chief Operating Officer", FIRM)]
    assert wd_poc._rank(people, FIRM)["title"] == "Chief Operating Officer"


@pytest.mark.parametrize("title", [
    "Owner", "Managing Owner", "Founder & Owner", "Owner-Operator", "Co-Owner",
])
def test_title_matches_keyword_owner_matches_when_owner_is_the_role(title):
    assert wd_poc._title_matches_keyword(title.lower(), "owner") is True


@pytest.mark.parametrize("colliding_title", [
    "Product Owner",   # named minimum for the "owner" audit
    "Technical Owner",
    "Data Owner",
    "System Owner",
    "Process Owner",
    "Risk Owner",
    "Content Owner",
    "Platform Owner",
])
def test_title_matches_keyword_owner_excludes_accountability_role_prefixes(colliding_title):
    assert wd_poc._title_matches_keyword(colliding_title.lower(), "owner") is False


def test_rank_product_owner_does_not_rank_as_executive():
    solo = [_person("a", "Product Owner", FIRM)]
    assert wd_poc._rank(solo, FIRM) is None


@pytest.mark.parametrize("title", [
    "Partner", "Managing Partner", "Partner & CEO", "Senior Partner",
    "General Partner", "Equity Partner", "Partner, Real Estate",
])
def test_title_matches_keyword_partner_matches_when_partner_is_the_role(title):
    assert wd_poc._title_matches_keyword(title.lower(), "partner") is True


@pytest.mark.parametrize("colliding_title", [
    "Technical Partner",   # named minimum for the "partner" audit
    "Channel Partner",
    "Channel Partner Manager",
    "HR Business Partner",
])
def test_title_matches_keyword_partner_excludes_non_equity_relationship_roles(colliding_title):
    assert wd_poc._title_matches_keyword(colliding_title.lower(), "partner") is False


def test_rank_technical_partner_does_not_rank_as_executive():
    solo = [_person("a", "Technical Partner", FIRM)]
    assert wd_poc._rank(solo, FIRM) is None


# ---------------------------------------------------------------------------
# _rank_all / _rank: _rank is a thin wrapper over _rank_all's first result
# ---------------------------------------------------------------------------
def test_rank_all_returns_every_matching_candidate_in_seniority_order():
    people = [
        _person("Ann Manager", "Accounting Manager", FIRM),
        _person("Ben CFO", "Chief Financial Officer", FIRM),
        _person("Cara Controller", "Controller", FIRM),
    ]
    ranked = wd_poc._rank_all(people, FIRM)
    assert [p["title"] for p in ranked] == [
        "Chief Financial Officer", "Controller", "Accounting Manager",
    ]


def test_rank_all_excludes_non_matching_org():
    people = [_person("Jane CFO", "Chief Financial Officer", "Wasatch Group")]
    assert wd_poc._rank_all(people, "Wasatch Bridge Capital Group") == []


def test_rank_all_deduplicates_by_id():
    people = [_person("Ben CFO", "Chief Financial Officer", FIRM, person_id="p1"),
             _person("Ben CFO", "Chief Financial Officer", FIRM, person_id="p1")]
    assert len(wd_poc._rank_all(people, FIRM)) == 1


def test_rank_is_a_thin_wrapper_over_rank_all_first_result():
    people = [
        _person("Ann Manager", "Accounting Manager", FIRM),
        _person("Ben CFO", "Chief Financial Officer", FIRM),
    ]
    assert wd_poc._rank(people, FIRM) == wd_poc._rank_all(people, FIRM)[0]


def test_rank_returns_none_when_rank_all_is_empty():
    assert wd_poc._rank([], FIRM) is None


# ---------------------------------------------------------------------------
# find_senior_poc: domain-first search order, name as fallback
# ---------------------------------------------------------------------------
def test_domain_search_tried_first_and_wins_when_it_finds_a_hit(monkeypatch):
    """Mirrors the live comparison: domain search returns many people
    including the CFO; name search (which must never even be called here)
    would have returned fewer, without a senior hit."""
    calls = []

    def fake_search(headers, body):
        calls.append(body)
        if "q_organization_domains_list" in body:
            return [_person(f"Person {i}", "Staff Accountant", "Acme Capital Partners")
                    for i in range(77)] + [_person("Dana CFO", "Chief Financial Officer",
                                                   "Acme Capital Partners")]
        raise AssertionError("q_organization_name search must not run when domain search hits")

    monkeypatch.setattr(wd_poc, "_search", fake_search)
    _mock_match(monkeypatch, "Dana CFO", "dana@acme.example")

    result = wd_poc.find_senior_poc("Acme Capital Partners", domain="acme.example")

    assert result == ("Dana CFO", "dana@acme.example", "Chief Financial Officer")
    assert len(calls) == 1
    assert calls[0] == {"q_organization_domains_list": ["acme.example"], "per_page": 100}


def test_falls_back_to_name_search_when_domain_search_finds_no_hit(monkeypatch):
    calls = []

    def fake_search(headers, body):
        calls.append(body)
        if "q_organization_domains_list" in body:
            return [_person("Someone", "Staff Accountant", "Acme Capital Partners")]  # no senior title
        if "q_organization_name" in body:
            return [_person("Dana CFO", "Chief Financial Officer", "Acme Capital Partners")]
        raise AssertionError(f"unexpected search body: {body}")

    monkeypatch.setattr(wd_poc, "_search", fake_search)
    _mock_match(monkeypatch, "Dana CFO", "dana@acme.example")

    result = wd_poc.find_senior_poc("Acme Capital Partners", domain="acme.example")

    assert result == ("Dana CFO", "dana@acme.example", "Chief Financial Officer")
    assert len(calls) == 2
    assert "q_organization_domains_list" in calls[0]
    assert "q_organization_name" in calls[1]


def test_falls_back_to_name_search_when_domain_search_hit_wrong_org(monkeypatch):
    """Domain search returns a senior title, but at a DIFFERENT organization
    (a domain can resolve to a divisional/lookalike entity) -- must still
    fall back to name search rather than accept the mismatch."""
    calls = []

    def fake_search(headers, body):
        calls.append(body)
        if "q_organization_domains_list" in body:
            return [_person("Wrong CFO", "Chief Financial Officer", "Some Other Firm")]
        return [_person("Dana CFO", "Chief Financial Officer", "Acme Capital Partners")]

    monkeypatch.setattr(wd_poc, "_search", fake_search)
    _mock_match(monkeypatch, "Dana CFO", "dana@acme.example")

    result = wd_poc.find_senior_poc("Acme Capital Partners", domain="acme.example")

    assert result == ("Dana CFO", "dana@acme.example", "Chief Financial Officer")
    assert len(calls) == 2


def test_no_domain_goes_straight_to_name_search(monkeypatch):
    calls = []

    def fake_search(headers, body):
        calls.append(body)
        assert "q_organization_domains_list" not in body
        return [_person("Dana CFO", "Chief Financial Officer", "Acme Capital Partners")]

    monkeypatch.setattr(wd_poc, "_search", fake_search)
    _mock_match(monkeypatch, "Dana CFO", "dana@acme.example")

    result = wd_poc.find_senior_poc("Acme Capital Partners", domain=None)

    assert result == ("Dana CFO", "dana@acme.example", "Chief Financial Officer")
    assert len(calls) == 1


def test_no_hit_anywhere_returns_none_and_reports_combined_count(monkeypatch):
    progressed = []

    def fake_search(headers, body):
        if "q_organization_domains_list" in body:
            return [_person(f"P{i}", "Staff Accountant", "Acme Capital Partners") for i in range(3)]
        return [_person(f"P{i}", "Staff Accountant", "Acme Capital Partners") for i in range(2)]

    monkeypatch.setattr(wd_poc, "_search", fake_search)

    result = wd_poc.find_senior_poc("Acme Capital Partners", domain="acme.example",
                                    progress=progressed.append)

    assert result is None
    assert any("5 people seen" in msg for msg in progressed)


# ---------------------------------------------------------------------------
# find_senior_poc: walks every ranked candidate, not just the top one
# ---------------------------------------------------------------------------
def test_find_senior_poc_falls_through_unverified_first_candidate_to_verified_second(monkeypatch):
    people = [
        _person("Dana CFO", "Chief Financial Officer", FIRM, person_id="p1"),
        _person("Alex Principal", "Principal", FIRM, person_id="p2"),
    ]
    monkeypatch.setattr(wd_poc, "_search", lambda headers, body: people)
    fake_post = _mock_match_by_id(monkeypatch, {
        "p1": ("Dana CFO", "dana@acme.example", "unverified"),
        "p2": ("Alex Principal", "alex@acme.example", "verified"),
    })

    result = wd_poc.find_senior_poc(FIRM, domain="acme.example")

    assert result == ("Alex Principal", "alex@acme.example", "Principal")
    assert fake_post.calls == ["p1", "p2"]


def test_find_senior_poc_logs_each_rejected_candidate(monkeypatch):
    people = [
        _person("Dana CFO", "Chief Financial Officer", FIRM, person_id="p1"),
        _person("Alex Principal", "Principal", FIRM, person_id="p2"),
    ]
    monkeypatch.setattr(wd_poc, "_search", lambda headers, body: people)
    _mock_match_by_id(monkeypatch, {
        "p1": ("Dana CFO", "dana@acme.example", "unverified"),
        "p2": ("Alex Principal", "alex@acme.example", "verified"),
    })
    progressed = []

    wd_poc.find_senior_poc(FIRM, domain="acme.example", progress=progressed.append)

    assert any("Dana CFO (Chief Financial Officer): email_status=unverified" in msg
              for msg in progressed)


def test_find_senior_poc_all_unverified_returns_none(monkeypatch):
    people = [
        _person("Dana CFO", "Chief Financial Officer", FIRM, person_id="p1"),
        _person("Alex Principal", "Principal", FIRM, person_id="p2"),
    ]
    monkeypatch.setattr(wd_poc, "_search", lambda headers, body: people)
    fake_post = _mock_match_by_id(monkeypatch, {
        "p1": ("Dana CFO", "dana@acme.example", "unverified"),
        "p2": ("Alex Principal", "alex@acme.example", "guessed"),
    })

    result = wd_poc.find_senior_poc(FIRM, domain="acme.example")

    assert result is None
    assert fake_post.calls == ["p1", "p2"]


def test_find_senior_poc_caps_match_attempts_at_five(monkeypatch):
    # All same-tier (executive) so seniority ties break on input order,
    # giving deterministic attempt order p0..p5.
    titles = ["Principal", "Founder", "Co-Founder", "Owner", "Managing Partner", "President"]
    people = [_person(f"Person {i}", title, FIRM, person_id=f"p{i}")
             for i, title in enumerate(titles)]
    monkeypatch.setattr(wd_poc, "_search", lambda headers, body: people)

    responses = {f"p{i}": (f"Person {i}", f"person{i}@acme.example", "unverified")
                for i in range(6)}
    responses["p5"] = ("Person 5", "person5@acme.example", "verified")  # 6th, never tried
    fake_post = _mock_match_by_id(monkeypatch, responses)

    result = wd_poc.find_senior_poc(FIRM, domain="acme.example")

    assert result is None
    assert fake_post.calls == ["p0", "p1", "p2", "p3", "p4"]
    assert len(fake_post.calls) == wd_poc.MAX_MATCH_ATTEMPTS
