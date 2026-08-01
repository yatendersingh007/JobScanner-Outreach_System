"""Adversarial evaluation harness for the ICP gate. READ-ONLY, REPORT-ONLY.

This harness never modifies lib_referral/icp_gate.py, never modifies gate
behaviour, and never writes to wd_firms. Part 1 costs nothing (it replays
stored research offline). Part 2 costs Tavily searches and REFUSES TO RUN
without an explicit --live flag plus a typed confirmation token, because 25
firms is roughly 150 searches.

    python scripts/gate_eval.py part1                 # offline, zero cost
    python scripts/gate_eval.py part2-plan            # print the firm list, no spend
    python scripts/gate_eval.py part2 --live --i-approve-the-spend

WHY OFFLINE REPLAY IS FAITHFUL. icp_gate.apply_gate() is a pure function with
no I/O, and research_and_gate() passes it `gate_value_usd=parsed["aum_value_usd"]`
while storing that same value as `research["aum_value_usd"]`. So the stored blob
carries apply_gate's own inputs verbatim for aum_value_usd, aum_tag, proxy_type
and proxy_basis. Two inputs are NOT stored and are handled explicitly:

  firm_type_ok / region_ok  inferred from the stored icp_reason, whose two
                            early-return strings are unique and unambiguous
  unit_count / sqft_count   not stored at all. Rows with proxy_type == "units"
                            are reported as UNREPLAYABLE rather than guessed at.

source_note only reaches reason text, never the verdict, so replay compares
verdicts and not reason strings.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib_referral import config as gate_config, icp_gate  # noqa: E402
from src import wd_dbc as dbc  # noqa: E402

BAND_LO = gate_config.AUM_MIN_USD
BAND_HI = gate_config.AUM_MAX_USD

_FIRM_TYPE_REASON = "not an accepted firm type"
_REGION_REASON = "outside north america"

# Verdicts Workflow D itself overrode AFTER the gate returned. These are not
# gate failures and must not be counted as replay divergences.
_WD_OVERRIDE_SOURCES = {"geo_tld_check", "acquired_by_parent", "infrastructure"}
# Rows a human corrected after the fact. Excluded from the replay-agreement
# rate (they are not gate output) and reported separately, because an override
# is the strongest evidence the gate got a class of firm wrong: someone had to
# fix it by hand.
#   "operator-verified"                 /qualify
#   "Disqualified by operator override" /disqualify
#   "VOID:"                             a direct manual DB edit. This string
#                                       appears nowhere in icp_gate.py and
#                                       nowhere in bot.py.
_OPERATOR_REASON_RE = re.compile(
    r"operator-verified|operator-rejected|by operator override|^\s*VOID\b",
    re.IGNORECASE)


# ---------------------------------------------------------------------------
# Part 1: offline replay + consistency audit
# ---------------------------------------------------------------------------
def load_rows() -> list:
    with dbc.cursor() as cur:
        cur.execute("""SELECT id, run_id, firm_name, firm_key, icp_status, icp_reason,
                              aum_tag, park_reason, park_source, verdict_source,
                              verdict_cached_from, research, gated_at
                       FROM wd_firms
                       WHERE research IS NOT NULL AND research::text <> '{}'
                       ORDER BY id""")
        return [dict(r) for r in cur.fetchall()]


def _reason(row) -> str:
    return str(row.get("icp_reason") or "").lower()


def is_wd_override(row) -> bool:
    if (row.get("park_source") or "") in _WD_OVERRIDE_SOURCES:
        return True
    return bool(_OPERATOR_REASON_RE.search(str(row.get("icp_reason") or "")))


def replay(row) -> tuple:
    """(replayed_verdict, replayable, note). Never calls out to anything."""
    research = row.get("research") or {}
    reason = _reason(row)
    proxy_type = (research.get("proxy_type") or "") or None

    if proxy_type == "units":
        return None, False, "unit/sqft proxy: unit_count and sqft_count are not persisted"

    firm_type_ok = _FIRM_TYPE_REASON not in reason
    region_ok = _REGION_REASON not in reason
    try:
        verdict, _reason_out = icp_gate.apply_gate(
            firm_type_ok=firm_type_ok,
            region_ok=region_ok,
            gate_value_usd=research.get("aum_value_usd"),
            aum_tag=str(research.get("aum_tag") or ""),
            proxy_type=proxy_type,
            proxy_basis=str(research.get("proxy_basis") or ""),
            source_note="",
        )
    except Exception as e:  # noqa: BLE001 - a harness must not die on one row
        return None, False, f"apply_gate raised: {type(e).__name__}: {e}"
    return verdict, True, ""


# --- contradiction checks: the stated reason versus the blob's own facts ----
def contradictions(row) -> list:
    research = row.get("research") or {}
    reason = str(row.get("icp_reason") or "")
    low = reason.lower()
    status = row.get("icp_status")
    value = research.get("aum_value_usd")
    tag = str(research.get("aum_tag") or "")
    proxy = str(research.get("proxy_type") or "")
    out = []

    if status == "qualified" and value is None and not _OPERATOR_REASON_RE.search(reason):
        out.append("qualified_with_no_aum_value")
    if status == "qualified" and isinstance(value, (int, float)) and value:
        if not (BAND_LO <= float(value) <= BAND_HI) and proxy not in ("gav", "units"):
            out.append(f"qualified_outside_band:{float(value):.0f}")
    if status == "disqualified" and _FIRM_TYPE_REASON not in low \
            and isinstance(value, (int, float)) and value:
        if BAND_LO <= float(value) <= BAND_HI and proxy not in ("gav", "units"):
            out.append(f"disqualified_inside_band:{float(value):.0f}")
    # A floor proxy states a LOWER bound, so below-floor must park, not disqualify.
    if status == "disqualified" and proxy == "floor" and isinstance(value, (int, float)) \
            and value and float(value) < BAND_LO:
        out.append("floor_proxy_below_band_disqualified_instead_of_parked")
    # A derived $0 from a real disclosed quantity (Brixmor: 64,000,000 sq ft).
    if isinstance(value, (int, float)) and float(value) == 0.0 and research.get("aum_display"):
        out.append("zero_gate_value_from_a_real_disclosed_quantity")
    # Every dollar figure the reason states should be traceable to the blob.
    # The band edges are POLICY constants, not claims about the firm, so a
    # reason reading "exceeds $2B ceiling" must not be counted as an
    # untraceable figure. Without this every ceiling mention reads as a finding.
    band_literals = {"$200m", "$200million", "$2b", "$2billion", "$2.0b"}
    blob = json.dumps(research, default=str).lower()
    for figure in re.findall(r"\$\s?[\d][\d,.]*\s*(?:billion|million|[bmk])\b", reason,
                            flags=re.IGNORECASE):
        norm = re.sub(r"[\s,]", "", figure).lower()
        if norm in band_literals:
            continue
        compact = norm.replace("million", "m").replace("billion", "b")
        if norm not in re.sub(r"[\s,]", "", blob).lower() \
                and compact not in re.sub(r"[\s,]", "", blob).lower():
            out.append(f"reason_figure_not_in_blob:{figure.strip()}")
    if tag == "AUM_CONFIRMED" and not research.get("disclosed_figure") \
            and not _OPERATOR_REASON_RE.search(reason):
        out.append("aum_confirmed_with_no_disclosed_figure")
    if status == "parked" and not (row.get("park_reason") or "").strip():
        out.append("parked_with_no_park_reason")
    return out


def instability(rows) -> dict:
    """firm_key -> the distinct verdicts, figures and tags it has ever had."""
    by_key = defaultdict(list)
    for row in rows:
        by_key[row.get("firm_key")].append(row)
    report = {}
    for key, group in by_key.items():
        if len(group) < 2:
            continue
        verdicts = {r["icp_status"] for r in group}
        figures = {str((r["research"] or {}).get("disclosed_figure") or "") for r in group}
        values = {(r["research"] or {}).get("aum_value_usd") for r in group}
        tags = {str((r["research"] or {}).get("aum_tag") or "") for r in group}
        blob_sizes = {len(json.dumps(r["research"] or {}, default=str)) for r in group}
        if len(verdicts) > 1 or len(values) > 1 or len(tags) > 1:
            report[key] = {
                "rows": [(r["id"], r["run_id"], r["icp_status"],
                          (r["research"] or {}).get("aum_value_usd"),
                          str((r["research"] or {}).get("aum_tag") or ""),
                          str((r["research"] or {}).get("disclosed_figure") or ""),
                          r["verdict_source"]) for r in group],
                "verdicts": sorted(v or "NULL" for v in verdicts),
                "figures": sorted(figures),
                "tags": sorted(tags),
                "blob_sizes": sorted(blob_sizes),
                "n": len(group),
            }
    return report


def part1() -> dict:
    rows = load_rows()
    replayed = matched = diverged = unreplayable = overridden = 0
    divergences, unreplayable_rows, contradiction_rows = [], [], []
    override_rows = []

    for row in rows:
        verdict, ok, note = replay(row)
        if not ok:
            unreplayable += 1
            unreplayable_rows.append((row["id"], row["firm_name"], note))
        else:
            replayed += 1
            if is_wd_override(row):
                overridden += 1
                override_rows.append((row["id"], row["firm_name"], row["icp_status"],
                                      verdict, row["icp_reason"]))
            elif verdict == row["icp_status"]:
                matched += 1
            else:
                diverged += 1
                divergences.append((row["id"], row["firm_name"], row["icp_status"],
                                    verdict, row["icp_reason"], row["verdict_source"]))
        found = contradictions(row)
        if found:
            contradiction_rows.append((row["id"], row["firm_name"], row["icp_status"], found))

    return {
        "total": len(rows), "replayed": replayed, "matched": matched,
        "diverged": diverged, "unreplayable": unreplayable, "overridden": overridden,
        "divergences": divergences, "unreplayable_rows": unreplayable_rows,
        "contradictions": contradiction_rows, "instability": instability(rows),
    }


# ---------------------------------------------------------------------------
# Part 2: the adversarial live set. PROPOSAL ONLY until approved.
#
# 25 firms, one trap per row, each with the verdict the gate SHOULD reach and
# why that is knowable from public information. "expected" is the ICP-correct
# answer, not a guess at what the gate will do -- the whole point is measuring
# the gap. Determinism rows are gated three times each, which is why the
# search estimate is 25 firms + 6 repeats = 31 gate calls.
# ---------------------------------------------------------------------------
PART2_FIRMS = [
    # -- Divisional-AUM traps: subsidiary in band, parent above ceiling ------
    ("Wasatch Commercial Management", "divisional_aum", "parked",
     "Divisional arm of Wasatch Group; group AUM $4B+ is above the $2B ceiling. "
     "Known live failure: gated on the divisional figure."),
    ("Greystar Development", "divisional_aum", "disqualified",
     "Development arm of Greystar, ~$76B AUM parent, far above ceiling."),
    ("Related Affordable", "divisional_aum", "disqualified",
     "Subsidiary of Related Companies, above ceiling at parent level."),
    ("Lincoln Property Company Southeast", "divisional_aum", "parked",
     "Regional division; parent Lincoln Property is above ceiling."),
    # -- Direction traps: acquirer should qualify, acquiree should park ------
    ("Sila Realty Trust", "direction_acquirer", "disqualified",
     "Active acquirer, but ~$2.2B portfolio puts it just above ceiling; "
     "tests ceiling AND direction together."),
    ("Roberts Resorts", "direction_acquirer", "qualified",
     "Recent acquirer of MH/RV communities, mid-market operator in band."),
    ("Monogram Residential", "direction_acquired", "parked",
     "Acquired by Greystar in 2017; a parent with its own back office."),
    ("Pure Multi-Family REIT", "direction_acquired", "parked",
     "Acquired by Cortland in 2019."),
    # -- Name-collision traps: shared stem, different company ---------------
    ("Sentinel Real Estate", "name_collision", "qualified",
     "Collides with Sentinel Capital Partners (PE, unrelated) and Sentinel One "
     "(software). AlphaX class."),
    ("Summit Real Estate Group", "name_collision", "qualified",
     "Many unrelated 'Summit' firms including Summit Partners (PE)."),
    ("Pacific Oak Capital Markets", "name_collision", "parked",
     "Collides with Pacific Oak Residential Trust and KBS legacy entities."),
    ("Ares Management Real Estate", "name_collision", "disqualified",
     "Parent Ares is ~$450B AUM; the RE arm has no separable public figure."),
    # -- Boundary AUM: just inside/outside each band edge -------------------
    ("Fairfield Residential", "boundary_high", "disqualified",
     "Publicly ~$8B, well above ceiling; the easy side of the high edge."),
    ("Dalfen Industrial", "boundary_high", "disqualified",
     "~$9B AUM, above ceiling."),
    ("Hamilton Zanze", "boundary_high", "parked",
     "Publicly cited around $2B, i.e. sitting ON the ceiling. Either side is "
     "defensible, so consistency across runs is what is measured."),
    ("Griffin Partners", "boundary_low", "qualified",
     "Publicly cited around $1.5B, inside the band near the top."),
    ("Bridge33 Capital", "boundary_low", "qualified",
     "Around $1.8B, just inside the ceiling."),
    ("Stoltz Real Estate Partners", "boundary_low", "qualified",
     "Around $200M-$250M, sitting ON the floor."),
    # -- Category edges: is 'accepted firm type' applied consistently? ------
    ("Dream Finders Homes", "category_homebuilder", "qualified",
     "Homebuilder. Neal Communities (also a homebuilder) was accepted, so the "
     "type rule should treat this the same way."),
    ("Kidder Mathews", "category_brokerage", "disqualified",
     "CRE brokerage/services, not an owner-operator. Colliers was blocked as "
     "brokerage; consistency check."),
    ("Arbor Realty Trust", "category_mortgage_reit", "disqualified",
     "Mortgage REIT, a lender rather than a property owner-operator."),
    ("Blackstone Mortgage Trust", "category_mortgage_reit", "disqualified",
     "Mortgage REIT and above ceiling."),
    ("Entrata", "category_proptech", "disqualified",
     "Property-management SOFTWARE. Chipotle-class type rejection; the gate "
     "must not read 'property management' in the description as the firm type."),
    ("VTS", "category_proptech", "disqualified",
     "CRE leasing software, not an operator."),
    ("Cortland", "category_operator_control", "disqualified",
     "Vertically integrated multifamily operator, ~$18B, above ceiling. The "
     "control row: a clean, unambiguous type with an unambiguous figure."),
]

# Gated three times each to measure verdict and figure variance on identical
# inputs. Deliberately chosen from three different trap classes.
PART2_DETERMINISM = ["Hamilton Zanze", "Sentinel Real Estate", "Stoltz Real Estate Partners"]

SEARCHES_PER_GATE = 6


def part2_plan() -> str:
    lines = ["ADVERSARIAL LIVE SET, PROPOSAL ONLY. Nothing is spent until approved.", ""]
    by_cat = defaultdict(list)
    for name, cat, expected, why in PART2_FIRMS:
        by_cat[cat].append((name, expected, why))
    for cat in sorted(by_cat):
        lines.append(f"{cat}  ({len(by_cat[cat])} firms)")
        for name, expected, why in by_cat[cat]:
            lines.append(f"    {name:<38} expect {expected:<13} {why}")
        lines.append("")
    repeats = len(PART2_DETERMINISM) * 2      # two EXTRA gates each
    total_gates = len(PART2_FIRMS) + repeats
    lines += [
        f"Firms: {len(PART2_FIRMS)}",
        f"Determinism repeats: {len(PART2_DETERMINISM)} firms x 2 extra gates = {repeats}",
        f"Total gate calls: {total_gates}",
        f"Estimated Tavily searches: {total_gates} x {SEARCHES_PER_GATE} = "
        f"{total_gates * SEARCHES_PER_GATE}",
        "",
        "Determinism rows: " + ", ".join(PART2_DETERMINISM),
        "",
        "This writes NOTHING to wd_firms. It calls icp_gate.research_and_gate()",
        "directly and keeps results in memory plus a JSON artifact.",
    ]
    return "\n".join(lines)


def part2_live(out_path: Path) -> dict:
    """Gate each firm once, plus two extra passes for the determinism rows.
    Calls research_and_gate() directly: no wd_runs row, no wd_firms write, no
    drafting, no deck. Results land in `out_path` as JSON."""
    results = []
    plan = [(n, c, e) for n, c, e, _w in PART2_FIRMS]
    for name, cat, expected in plan:
        passes = 3 if name in PART2_DETERMINISM else 1
        for attempt in range(1, passes + 1):
            try:
                res = icp_gate.research_and_gate(name, progress=lambda m: print(f"  {m}"))
                results.append({
                    "firm": name, "trap": cat, "expected": expected, "attempt": attempt,
                    "verdict": res.icp_result, "reason": res.icp_reason,
                    "aum_tag": res.aum_tag,
                    "aum_value_usd": (res.research or {}).get("aum_value_usd"),
                    "disclosed_figure": (res.research or {}).get("disclosed_figure"),
                    "own_domain": (res.research or {}).get("own_domain"),
                    "recent_event": (res.research or {}).get("recent_event"),
                    "search_calls": res.search_calls,
                })
            except Exception as e:  # noqa: BLE001
                results.append({"firm": name, "trap": cat, "expected": expected,
                                "attempt": attempt, "error": f"{type(e).__name__}: {e}"})
            out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
            print(f"[{len(results)}] {name} attempt {attempt}: "
                  f"{results[-1].get('verdict') or results[-1].get('error')}")
    return {"results": results}


# ---------------------------------------------------------------------------
def _print_part1(data) -> None:
    d = data
    print("=" * 78)
    print("PART 1  offline replay of stored research. Zero API cost.")
    print("=" * 78)
    print(f"  rows with a research blob      : {d['total']}")
    print(f"  replayable through apply_gate  : {d['replayed']}")
    print(f"    verdict matched              : {d['matched']}")
    print(f"    Workflow-D override (excluded): {d['overridden']}")
    print(f"    DIVERGED                     : {d['diverged']}")
    print(f"  unreplayable (inputs not kept) : {d['unreplayable']}")
    if d["replayed"] - d["overridden"]:
        rate = d["matched"] / (d["replayed"] - d["overridden"]) * 100
        print(f"  replay agreement               : {rate:.1f}%")

    print("\n-- divergences --")
    for row in d["divergences"]:
        print(f"  id={row[0]:<4} {row[1][:30]:<30} stored={row[2]:<13} replay={row[3]:<13} "
              f"src={row[5]}")
        print(f"        reason: {str(row[4])[:96]}")
    if not d["divergences"]:
        print("  none")

    print("\n-- unreplayable --")
    for row in d["unreplayable_rows"][:12]:
        print(f"  id={row[0]:<4} {row[1][:30]:<30} {row[2]}")

    print("\n-- verdict / figure instability across runs, same firm_key --")
    inst = d["instability"]
    print(f"  firm_keys gated more than once with ANY disagreement: {len(inst)}")
    for key, info in sorted(inst.items()):
        flag = "VERDICT" if len(info["verdicts"]) > 1 else "figure"
        print(f"  [{flag}] {key[:34]:<34} n={info['n']} verdicts={info['verdicts']} "
              f"tags={info['tags']}")
        for r in info["rows"]:
            print(f"        id={r[0]:<4} run={r[1]:<3} {str(r[2]):<13} value={r[3]} "
                  f"tag={r[4]:<15} figure={r[5]!r} src={r[6]}")

    print("\n-- reason contradicts the blob's own facts --")
    counts = defaultdict(int)
    for row in d["contradictions"]:
        for c in row[3]:
            counts[c.split(":")[0]] += 1
    for kind, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {kind}")
    print()
    for row in d["contradictions"][:24]:
        print(f"  id={row[0]:<4} {row[1][:30]:<30} {row[2]:<13} {row[3]}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["part1", "part2-plan", "part2"])
    parser.add_argument("--live", action="store_true",
                        help="required for part2; without it part2 refuses to spend")
    parser.add_argument("--i-approve-the-spend", dest="approved", action="store_true",
                        help="second, explicit confirmation for part2")
    parser.add_argument("--out", default="qa_out/gate_eval_part2.json")
    args = parser.parse_args(argv)

    if args.stage == "part1":
        _print_part1(part1())
        return 0
    if args.stage == "part2-plan":
        print(part2_plan())
        return 0

    if not (args.live and args.approved):
        print(part2_plan())
        print("\nREFUSING TO SPEND. part2 needs both --live and "
              "--i-approve-the-spend.")
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part2_live(out)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
