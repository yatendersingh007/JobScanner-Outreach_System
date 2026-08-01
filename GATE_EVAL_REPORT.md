# ICP gate: adversarial evaluation report

Harness: `scripts/gate_eval.py`. Read-only and report-only. Nothing in
`lib_referral/icp_gate.py` was modified, no gate behaviour was changed, and no
row in `wd_firms` was written. **No fixes are proposed as changes here**, only
located.

- **Part 1 (offline, zero API cost): complete.** Results below.
- **Part 2 (adversarial live set): PROPOSED, NOT RUN.** Awaiting go-ahead on the
  firm list. See the cost note, the estimate is 186 searches, not 150.

---

## Method, and why the offline replay is trustworthy

`icp_gate.apply_gate()` is a pure function with no I/O, and
`research_and_gate()` calls it with `gate_value_usd=parsed["aum_value_usd"]`
while storing that same value as `research["aum_value_usd"]`. The stored blob
therefore carries apply_gate's own inputs verbatim for `aum_value_usd`,
`aum_tag`, `proxy_type` and `proxy_basis`. Replay feeds those back in and
compares the returned verdict to the stored `icp_status`.

Two inputs are **not** persisted and are handled explicitly rather than guessed:

| input | handling |
|---|---|
| `firm_type_ok`, `region_ok` | inferred from the stored `icp_reason`, whose two early-return strings are unique |
| `unit_count`, `sqft_count` | not stored at all. Rows with `proxy_type == "units"` are reported **UNREPLAYABLE**, not reconstructed |

`source_note` only reaches reason text, never the verdict, so replay compares
verdicts and not reason strings.

**Two measurement errors were found and corrected in the harness before these
numbers were trusted**, both of which would have inflated the failure count:

1. Rows a human corrected after the fact were first counted as gate
   divergences. `VOID:` appears nowhere in `icp_gate.py` and nowhere in
   `bot.py`, so those rows are direct manual DB edits, not gate output. They
   are now excluded from the agreement rate and reported separately.
2. The reason-versus-blob check flagged the band constants. A reason reading
   "exceeds $2B ceiling" cites policy, not a claim about the firm. `$200M` and
   `$2B` literals are now skipped, which removed 8 false findings.

---

## Part 1 results

### Verdict accuracy: the verdict logic is not the problem

| | rows |
|---|---|
| `wd_firms` rows with a research blob | 99 |
| replayable through `apply_gate` | 97 |
| operator-overridden (excluded from the rate) | 11 |
| **verdict matched** | **86** |
| **verdict diverged** | **0** |
| unreplayable (inputs not persisted) | 2 |
| **replay agreement** | **100.0%** |

Given identical inputs, `apply_gate` reproduces every stored verdict exactly.
The band logic, the proxy branching and the park/disqualify split are all
faithful and deterministic.

**This reframes the whole exercise: every instability found below originates in
RESEARCH, in which facts get extracted, not in the verdict function.** That
matters for fix locality, because research is the expensive, non-deterministic,
vendored half.

### Verdict instability across runs

| | count |
|---|---|
| distinct `firm_key`s with a research blob | 48 |
| gated more than once | 18 |
| with any disagreement (verdict, figure or tag) | 7 |
| **with a verdict disagreement** | **5** |
| figure/tag disagreement only | 2 |

Raw instability rate is 5/18 = **28% of repeat-gated firms**, but that number
is misleading and should not be quoted on its own. Four of the five are one
cohort shift, not run-to-run noise:

| run | firms gated | type-rejected | "AUM not found" parks |
|---|---|---|---|
| 10 | 10 | **0** | **9** |
| 13 | 11 | 7 | 0 |
| 15 | 12 | 10 | 0 |
| 16 | 9 | 7 | 0 |

Australia-Employment, Havtech, JPMorgan Chase and Wealthspire all parked in run
10 with `firm_type_ok` true and no AUM, then type-rejected from run 13 onward.
All on the same date. That is the firm-type rule tightening during development,
and every one of those four flips is toward the **correct** answer. Counting it
as gate flakiness would be wrong.

**The one clean same-generation instability is Choice NY**, the case you already
knew about:

```
id=65  run 25  qualified  $250,000,000  AUM_ESTIMATED   "$250 million"   gated
id=66  run 27  qualified  $250,000,000  AUM_ESTIMATED   "$250 million"   cached_wd
id=83  run 29  parked     None          AUM_UNVERIFIED  ""               gated
```

`firm_type_ok` was true in all three. Run 29 simply failed to find the figure
runs 25 and 27 found. Research variance, verdict logic blameless.

And one figure-drift case with no verdict change:

```
Neal Communities  run 23  value None      (gate parked; operator qualified at $700M)
                  run 27  $700,000,000    AUM_CONFIRMED
                  run 30  $905,000,000    AUM_ESTIMATED   <- gate's own figure
```

$700M operator-verified versus $905M gate-derived on the same firm is a 29%
spread. Both sit inside the band so the verdict held, but a firm near an edge
with that spread would flip.

### Rows a human had to override

11 rows, and they concentrate almost entirely on one firm:

| firm | rows | human verdict | what the gate said |
|---|---|---|---|
| Wasatch Group | 9 | disqualified | `parked` ×2, `qualified` ×7 |
| Neal Communities | 2 | qualified | `parked`, `qualified` |

The Wasatch Group rows carry a hand-written reason: *"VOID: divisional AUM
figure, group is $4B+, above $2B ceiling."* The gate qualified a firm nine
separate times on a divisional figure, and a human corrected it nine separate
times. **This is the single strongest piece of evidence in Part 1**, and it is
exactly the divisional-AUM trap Part 2 is built to quantify.

Note the mechanism precisely: the gate extracted `$2,000,000,000` for Wasatch,
which is *exactly* the ceiling, and `apply_gate` treats the ceiling as
inclusive, so it qualified. The figure itself was the divisional one.

### Reason contradicts the blob's own facts

| class | rows | what it means |
|---|---|---|
| `reason_figure_not_in_blob` | 15 | a dollar figure in the reason is not traceable to the blob |
| `disqualified_inside_band` | 7 | verdict says disqualified while the blob's own value is in band |
| `zero_gate_value_from_a_real_disclosed_quantity` | 4 | a real disclosed quantity converted to `$0` |
| `qualified_with_no_aum_value` | 1 | qualified with `aum_value_usd` null |

Attribution matters here, so by cause rather than by class:

- **8 of the 15 untraceable figures, and all 7 `disqualified_inside_band`, are
  the Wasatch override artifact.** The human wrote a `$4B` reason and a
  disqualified verdict without updating the blob, which still says `$2B`. That
  is override hygiene, not a gate defect: there is no code path that writes
  back to research when a verdict is overridden.
- **4 rows genuinely derived `$0` from a real quantity**: CloudHQ, Brixmor
  Property Group, and Colliers twice. Brixmor's blob holds `64,000,000 sq ft`
  and its reason reads *"est. $0M from square footage tertiary proxy."* A real
  disclosed magnitude became zero.
- **1 row qualified with no persisted value**: Wasatch Commercial Management
  (id 46), reason cites `$240M`, blob has `aum_value_usd = None`. This is the
  units-proxy path: the derived gating figure is computed inside `apply_gate`
  and never persisted, so the row cannot justify its own verdict and cannot be
  replayed. Both unreplayable rows are this same path.
- 1 row is the historical `/qualify` bug already fixed (Neal id 55, `$700M` in
  the reason, nothing in research).

---

## Ranked failure modes from Part 1

Ranked by expected impact: wrong-verdict-on-a-real-prospect above cosmetic.

### 1. Divisional AUM is read as firm AUM

**Evidence.** Wasatch Group, 9 rows, gate said `qualified` 7 times and `parked`
twice, human overrode all 9. Extracted `$2,000,000,000` is the divisional
figure; the group is `$4B+`. Compounded by the ceiling being inclusive, so
exactly-$2B qualifies.

**Fix locality.** Split. Detecting "this figure belongs to a division" is a
research/extraction concern and therefore **vendored** (donor filing against
`icp_gate.py`'s extraction prompt). But a **Workflow-D-local** post-gate check
is available and cheap, in the same shape as the existing
`foreign_domain_park_reason` and `acquired_by_parent_park_reason`: park an
otherwise-qualified firm whose research names a parent or group entity, or
whose figure lands within a small epsilon of either band edge. That converts a
wrong qualify into a park, which costs a manual look instead of a wrong draft.

**Expected impact.** Highest of any finding. It is the only failure mode with
repeated, documented human correction, and it produces false QUALIFIES, which
are the expensive direction: they reach Apollo, a deck and a draft.

### 2. Research variance silently flips verdicts between runs

**Evidence.** Choice NY qualified at `$250M` in runs 25 and 27, parked with no
figure at all in run 29, same code generation, same firm type. Neal Communities
`$700M` versus `$905M` on the same firm.

**Fix locality.** The variance itself is **vendored** (Tavily result ordering
plus extraction). Workflow-D-local mitigation already exists and is working:
the verdict cache reuses a decided verdict rather than re-researching. The gap
is that `run_single_firm` never consults it (recorded in an earlier BUILD_LOG
entry), so `/scan "Firm"` re-researches from scratch every time and is the most
likely place to observe a flip.

**Expected impact.** High. A flip on a near-boundary firm is a lost prospect
(qualified once, parked next time) with no signal that anything changed.

### 3. A real disclosed quantity can derive to $0

**Evidence.** 4 rows. Brixmor: blob holds `64,000,000 sq ft`, reason reads
`est. $0M from square footage tertiary proxy`. Also CloudHQ and Colliers twice.

**Fix locality.** **Vendored.** The conversion lives in
`_tertiary_proxy_conversion`. A Workflow-D-local guard could refuse to trust a
`$0` gating value when `aum_display` is non-empty and park instead, but the
arithmetic itself is the donor's.

**Expected impact.** Medium. It currently produces parks (the safe direction),
so the cost is a manual look plus an unusable `$0M` string in the park reason.
It would become severe if a `$0` ever routed to disqualified.

### 4. The units/sqft path cannot justify or reproduce its own verdict

**Evidence.** Both unreplayable rows (Wasatch Commercial Management, Brixmor)
are this path. Id 46 qualified citing `$240M` while `aum_value_usd` is null,
because the derived figure is computed inside `apply_gate` and discarded.

**Fix locality.** **Vendored** to fix properly (persist the derived value and
the inputs). Workflow-D-local partial: store `unit_count`/`sqft_count` on the
`wd_firms` row when present so the verdict is at least auditable afterwards.

**Expected impact.** Medium for auditability, low for correctness. It is why
2 of 99 rows cannot be regression-tested at all, and that blind spot grows with
every units-proxied firm.

### 5. Overriding a verdict leaves the research blob contradicting it

**Evidence.** 8 untraceable figures and all 7 `disqualified_inside_band` rows
trace to the Wasatch override. `/disqualify` and the manual `VOID:` edits write
`icp_status` and `icp_reason` and never touch `research`.

**Fix locality.** **Workflow-D-local**, entirely. `/qualify` was already fixed
this way (it now writes the parsed figure into the blob); `/disqualify` and
manual edits were not.

**Expected impact.** Low on outcomes, high on diagnosis. It is what made the
first pass of this very report mis-attribute 15 findings to the gate.

---

## What Part 1 cannot answer

Stated plainly, because these are exactly what Part 2 buys:

- **Same-code determinism.** History cannot hold the code constant. The run
  10 → 13 cohort shift proves the code moved underneath the data, so no
  historical comparison measures nondeterminism. Gating one firm three times in
  one session is the only way.
- **Accuracy against a known-correct answer.** Every Part 1 finding is internal
  consistency: replay agreement, cross-run stability, reason-versus-blob. None
  of it says whether a verdict is *right*. Only a constructed set with known
  answers does.
- **Boundary behaviour.** One data point exists ($2B exactly, qualified) and it
  came from an overridden row. Which side the gate lands on, and how
  consistently, is unmeasured.
- **Category consistency.** Homebuilders were accepted (Neal) and brokerages
  rejected (Colliers), but with n=1 each that is anecdote, not a rule.

---

## Part 2: proposed adversarial set, awaiting go-ahead

**Not run. No searches spent.** `python scripts/gate_eval.py part2-plan` prints
this list; `part2` refuses to execute without both `--live` and
`--i-approve-the-spend`.

25 firms, one trap per row, each with the ICP-correct verdict and why it is
knowable from public information. 3 firms are gated 3 times for determinism.

| trap | firms | expected |
|---|---|---|
| divisional_aum | Wasatch Commercial Management, Greystar Development, Related Affordable, Lincoln Property Company Southeast | parked / disqualified |
| direction_acquirer | Sila Realty Trust, Roberts Resorts | disqualified / qualified |
| direction_acquired | Monogram Residential, Pure Multi-Family REIT | parked |
| name_collision | Sentinel Real Estate, Summit Real Estate Group, Pacific Oak Capital Markets, Ares Management Real Estate | qualified / parked / disqualified |
| boundary_high | Fairfield Residential, Dalfen Industrial, Hamilton Zanze | disqualified / parked |
| boundary_low | Griffin Partners, Bridge33 Capital, Stoltz Real Estate Partners | qualified |
| category_homebuilder | Dream Finders Homes | qualified |
| category_brokerage | Kidder Mathews | disqualified |
| category_mortgage_reit | Arbor Realty Trust, Blackstone Mortgage Trust | disqualified |
| category_proptech | Entrata, VTS | disqualified |
| category_operator_control | Cortland | disqualified |

Determinism rows, gated 3× each: **Hamilton Zanze** (sits on the ceiling),
**Sentinel Real Estate** (name collision), **Stoltz Real Estate Partners**
(sits on the floor). Chosen from three different trap classes so variance can
be attributed.

### Cost: the estimate is 186 searches, not 150

25 firms + 6 repeat gates = **31 gate calls × 6 searches = 186**. Your budget
said ≈150. Three ways to land closer, none applied without a decision:

| option | calls | searches |
|---|---|---|
| as proposed | 31 | 186 |
| drop 3 firms (one each from boundary_high, mortgage_reit, proptech) | 28 | 168 |
| 19 firms + 3 determinism rows at 3× | 25 | 150 exactly |

My recommendation is **as proposed at 186**. The three over-represented
categories are where n=2 is already the minimum for a consistency claim, and
trimming to 150 costs two whole trap categories.

The harness writes nothing to `wd_firms`: it calls `research_and_gate()`
directly and persists results to `qa_out/gate_eval_part2.json`.
