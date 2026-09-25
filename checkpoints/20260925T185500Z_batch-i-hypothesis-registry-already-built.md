# ATLAS CHECKPOINT

## Objective

Owner brief 2026-09-25, Part I: build the Edge-Validation Hypothesis
Registry infrastructure if it does not already exist. The brief expected it
not to exist ("Long-decided principle, never built"). The brief also asked
for a broad check for prior scaffolding before building anything.

**Status: ALREADY BUILT. Not rebuilt. The remaining gaps are proposed below
for owner decision.** No code was changed.

## Completed: scaffolding found (CONFLICT with the brief's premise)

- **Expected:** "never built".
- **Actual:** the registry, the split mechanism, the pre-registration
  workflow, Benjamini-Hochberg, and the CANDIDATE lifecycle all exist,
  are tested, and have been merged on this branch since 2026-09-19.
- **Evidence:**
  - Code in `research/` (L4, zero external imports, per `b9c96eb`):
    - `research/hypothesis_registry.py` (1493 lines):
      - `PreRegistration` with `seal_hash`
      - `HypothesisRegistry.register`, `advance`, `record_evaluation`,
        `adjudicate_family(q=...)`
      - `CheckPlan` sealing five closed checks: BACKTEST, WALK_FORWARD,
        OUT_OF_SAMPLE, COST_ADJUSTED, MONTE_CARLO
      - Threshold binding
      - `CheckVerdict` is PASS/FAIL only. There is deliberately no
        INCONCLUSIVE, and an absent required check counts as FAIL (the
        NB-4 analogue).
    - `research/splitting.py`: train/calibration/test splits with purge
      (`label_horizon_bars`) and `embargo_pct`, sealed into the
      pre-registration so the split cannot be tuned after the fact.
    - `research/multiple_testing.py`: `benjamini_hochberg` and
      `FDRDecision` (adjusted p-values, rejected labels).
    - `research/lifecycle.py`: DRAFT → REGISTERED → CALIBRATED → TESTED →
      **CANDIDATE** → PAPER_VALIDATING → VALIDATED, plus REJECTED, RETIRED
      and WITHDRAWN. TESTED→CANDIDATE is reachable only by family
      adjudication.
  - Bridges in `core/` (sanctioned L3):
    - `core/research_evidence_bridge.py` (`e2b2c93`)
    - `core/research_market_data_bridge.py` (compute engine P1, `e3f0c8e`)
    - `core/research_timestamp_split_binding.py` (P2, timestamp-bound purged
      splits, `dfcf21e`)
  - Nine test files:
    - `test_research_hypothesis_registry.py`
    - `test_research_hypothesis_checks.py`
    - `test_research_splitting.py`
    - `test_research_multiple_testing.py`
    - `test_research_lifecycle.py`
    - `test_research_isolation.py`
    - `test_research_evidence_bridge.py`
    - `test_research_market_data_bridge.py`
    - `test_research_timestamp_split_binding.py`
  - Design records:
    - `docs/research/0001-hypothesis-registry-design.md`, corrected
      2026-09-21 under v4.36
    - `docs/adr/0009-hypothesis-registry-boundary.md`
    - `docs/adr/0010-hypothesis-registry-boundary-type-correction.md`
  - Governance: registries v4.29 onward.
- **Impact:** building the registry again would have duplicated audited
  code.
- **Decision required:** none about the brief itself. The gaps below need
  decisions.

## Gaps against the brief's list (these are the real remaining work)

Each gap is either named as an open item in the design record or absent by
grep in this session.

1. **Power analysis: absent.** No `power` or `minimum detectable effect`
   code exists anywhere in `research/`. Design choices are needed:
   - Which test statistic: a Sharpe t-stat, or a mean-return t-test on
     non-overlapping labels.
   - Which target effect and alpha/beta.
   - Whether an underpowered pre-registration is refused at `register()`,
     or only flagged.
2. **No p-value procedure** (design-record open item 5). BH consumes
   p-values that nothing yet produces. This is tied to the compute engine
   (item 9, now partly addressed by P1/P2).
3. **Statistical-edge vs economic-edge gate: partial.** COST_ADJUSTED is
   the economic check, and BH/FDR is the statistical gate. There is no
   explicit two-gate record (for example `statistical_edge: PASS/FAIL` and
   `economic_edge: PASS/FAIL` required separately for CANDIDATE). It may be
   judged already covered by requiring both FDR rejection and COST_ADJUSTED
   PASS. That is an owner judgment.
4. **Family membership not sealed** (open item 6). Deleting a losing
   hypothesis from the file shrinks `m` and loosens BH. The proposed fix is
   a family-level manifest (count plus an ordered digest of ids) in the
   stored payload. This is a stored-format change, so it needs the migration
   checklist.
5. **A missing `records` key loads as an empty registry** (open item 7). A
   truncated file is indistinguishable from an empty one. This is small and
   well specified: refuse on load. Recommended as the first package.
6. **Record `state` not sealed** (open item 8). A hand-edited `CANDIDATE`
   loads as promoted. The proposed fix is a chained hash over the
   append-only evaluation log.
7. **Leakage controls beyond purge and embargo.** Purge and embargo exist.
   Feature-timestamp leakage checks (a feature computed from bars after the
   decision time) are UNKNOWN. Nothing named for them was found, and
   `core/research_timestamp_split_binding.py` may cover part of this.
   Verifying that would need a dedicated read.

## Recommendation

One bounded package, in this order:

1. Item 5, the load refusal. It is cheap and unambiguous.
2. Item 4, the family manifest. It needs a stored-format migration plan.
3. Item 6, the state chain.

Power analysis (item 1) and the explicit edge gate (item 3) need owner
methodology decisions first. Item 2 belongs to the compute-engine track.

## Files changed

This checkpoint only.

## Tests

None run for Part I. No code changed.

## Risks

None introduced.

## Next exact action

The owner decides:

- whether to authorize the items 5→4→6 hardening package;
- the power-analysis methodology;
- whether an explicit statistical-vs-economic gate record is wanted.
