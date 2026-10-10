# ATLAS CHECKPOINT — Task 007: Risk Intelligence & Position Limit Rules

## Objective
Implement Task 007 under GRANT-TASK-007-RISK-INTELLIGENCE-POSITION-LIMITS (registry v5.91). The work extends
the existing independent risk authority (core/risk_engine.RiskEngine) with opt-in portfolio guards, a 1x
leverage cap and a downsize-only sizing ceiling, while keeping every existing behaviour byte-identical.

## Completed
- **CONFLICTs C-1 to C-5 reported to the owner and decided in session on 2026-10-10:**
  - v5.91 did not exist.
  - Task 006 was still ACTIVE.
  - There was no Task 007 grant.
  - The constitution / Madde citations are UNKNOWN.
  - RiskEngine already is the "Risk Brain".
- **Owner decisions:**
  - draft v5.91 (close Task 006, confirm F3, grant Task 007);
  - extend RiskEngine;
  - downsize-only sizing;
  - hard 1x leverage cap.
- **Registry v5.91** (committed on its own): Task 006 CLOSED and F3 confirmed; Task 007 defined (roadmap
  Phase 2) and granted, with the conflicts recorded in the Expected/Actual/Evidence/Impact/Decision format.
- **core/risk_engine.py:**
  - new `RiskPolicy` fields, all OFF by default: `correlation_ceiling`, `cluster_exposure_pct` +
    `symbol_clusters`, `quote_exposure_pct` + `quote_currencies`, `max_market_data_age_seconds`,
    `kelly_fraction`, `volatility_target`, `drawdown_sizing`;
  - `RiskRequest.leverage`: any leverage other than 1x is vetoed, always on;
  - optional request inputs: `market_data_age_seconds`, `return_correlations`, `sizing_signal`;
  - `SizingSignal`, `SizingCeiling`, `sizing_ceiling` (fractional Kelly f* = p/L − (1−p)/W, volatility target,
    drawdown taper; downsize only), `quote_currency`, `drawdown_fraction`, `FrozenMapping`;
  - `RiskDecision.detail`: present in `to_dict` only when a Task 007 guard sets it; excluded from repr and
    hash; picklable.
- **core/position_sizing.py:** the proposal shrinks to the shared ceiling. Sizing refusals are reported with
  the guard's reason.
- **tests/core/test_task007_risk_intelligence.py:** 69 tests. They cover:
  - vetoes overriding confidence 1.0;
  - fail-closed handling of unready state, corrupt prices, and missing or malformed inputs;
  - exits never blocked;
  - correlation, cluster and quote-currency budgets;
  - EV, volatility and drawdown sizing, and monotonicity;
  - sizer/engine agreement;
  - drawdown and daily-loss halts;
  - immutability, pickling, overflow;
  - a golden digest pinned to the pre-Task 007 code.
- **packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md:** regenerated with the repo's tool (line shifts and two
  new classes).

## Architecture decisions
- One approval authority (RiskEngine). The sizer shrinks to the ceiling; the engine only vetoes and never
  downsizes, because ExecutionManager asserts approved == requested.
- With every guard OFF nothing changes. `RiskPolicy.version` stays phase3-risk-v1, so persisted risk state
  keeps matching. Runtime switch-on is a separate owner decision. It needs threshold values, the policy
  manifest, and the inputs wired in execution_manager/market_loop; the drawdown must come from
  `drawdown_fraction`.
- NB-4: a position whose cluster or quote currency is unknown counts against every group. Missing evidence
  refuses.

## Tests
- Full suite (final tree): 10422 passed, 12 skipped, 0 failed.
- Differential against the HEAD code: identical over 69,210 decisions/proposals for each of the default
  policy, sleeves on, and unrealized-loss on. Reviewers ran wider differentials: 995,328 records (review 7)
  and 2,700,192 records (review 8), also identical.
- Every review fix was mutation-checked by reverting it: the duplicate-correlation-key check, the taper
  fix, and the detail-key guard (caught by the golden test).

## Reviews (fresh context, independent)
- Review 7: PASS, 0 BLOCKING/0 HIGH. 2 MEDIUM (duplicate correlation keys; C-4 missing and the CONFLICT
  format), 5 LOW, 2 INFO. All fixed.
- Review 8: PASS. 1 MEDIUM: the MappingProxyType detail made decisions unpicklable. Fixed with
  FrozenMapping, plus 3 LOW.
- Review 9: PASS, 0 BLOCKING/0 HIGH/0 MEDIUM. 2 LOW (FrozenMapping slot rewrite; sizer/engine drawdown
  precision), fixed afterwards and re-tested; 5 INFO.

## Current state
Task 007 implemented and verified. Milestone ACTIVE; closure is the owner's decision. The guards are dormant
in the paper runtime until the owner switches them on.

## Known issues
- **Deferred (pre-existing, not changed):** `tools/build_architecture_inventory.py` strips the whole
  `git status --porcelain` output, so the regenerated artifact lists 'ore/position_sizing.py'.
- **Deferred (pre-existing):** the clock-resolution flake in
  `tests/test_apprentice.py::test_ceo_evidence_selection_is_learned_from_what_the_ceo_cited`.
- **Informational:**
  - `dataclasses.asdict(RiskDecision)` includes a FrozenMapping `detail` (no consumer; use `to_dict`).
  - The sizer does not pre-shrink for the correlation, cluster or quote guards; the engine vetoes, failing
    closed.
  - A guard switched on is invisible to the policy version and manifest until the manifest is extended at
    switch-on.

## Risks
None to the current runtime, which is unchanged. At switch-on, an unwired guard refuses every BUY (fail
closed).

## Remaining work
Owner: close Task 007 or not. Separately, a governed switch-on (thresholds, manifest, wiring) under a new
grant.

## Next exact action
Report to the owner: changes, test metrics, review verdicts, deferred items, and the switch-on
prerequisites.
