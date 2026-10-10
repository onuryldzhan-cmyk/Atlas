# ATLAS CHECKPOINT — Task 006: Multi-Strategy Comparison & Selection Engine

## Objective
Implement Task 006 under GRANT-TASK-006-MULTI-STRATEGY-COMPARISON-SELECTION-RESEARCH-ONLY (registry v5.89):
evaluate each sealed, registered generated study once, adjudicate complete families with multiple-testing
control (BH + sealed Bonferroni), and rank the survivors into a research shortlist. Research only; no
trading, capital or allocation authority.

## Completed
- Registry v5.89 committed on its own (`fffdf95`): Task 005 closed; Task 006 redefined (replaces EXP-006,
  deferred, definition UNKNOWN) and granted; the owner's in-session decisions recorded (daily P/L +
  bootstrap, spot costs, ranked shortlist, 90-day evaluation floor, accepted residuals); UNKNOWNs recorded.
- Implementation (this commit):
  - `research/strategy_evaluation.py`: a studentized circular block bootstrap (batch-means SE, 4 batches,
    block n//4; resamples with no spread count against the hypothesis) giving the p-value and CI;
    effect size, Sharpe/Sortino, max drawdown, per-regime splits, EV decomposition. NO_EVIDENCE scoring
    (p = 1, counted in m) for a window under 90 days, under 10 active days, no spread, or no daily series.
    Adjudication readiness (generated families only; registered == sealed; rejection/abandon after a run,
    after the earliest sealed window start, or after the first recorded run blocks the family).
    Shortlist: CANDIDATEs only, from complete ideas, with a greedy correlation guard and a
    `correlation_unknown_with` flag.
  - `tools/strategy_selection.py`: the CLI (evaluate / adjudicate / status / record-failed-run / abandon /
    shortlist). Every write happens under the registry write lock, on a re-read, with the result re-verified.
  - `tools/strategy_compare.py`: daily net P/L series, EV components (fees, slippage recovered from fill
    prices, funding 0 for spot) and past-only daily regime labels, all covered by the result digest.
  - `tools/hypothesis_pipeline.py`: templates under the 90-day floor are refused.

## Files changed
research/strategy_evaluation.py (new), tools/strategy_selection.py (new),
tests/research/test_task006_strategy_selection.py (new), tools/strategy_compare.py,
tools/hypothesis_pipeline.py, tests/research/test_task005_hypothesis_pipeline.py (CLI template days 1 -> 90,
because of the new floor), governance/current/ATLAS_MILESTONE_REGISTRY_v5.89.json (separate commit),
this checkpoint.

## Architecture decisions
- research/ imports only the stdlib, numpy and research.* (ADR-0009); data access and the registry path stay
  in tools/.
- The adjudication gate is enforced in tools/strategy_selection. A direct `HypothesisRegistry.adjudicate_family`
  call bypasses it (a recorded residual, like the unkeyed registry).
- 90-day evaluation floor (owner decision 2026-10-09, review NEW-1).

## Tests
- tests/research/: 133 passed.
- Full suite (2026-10-10, JUnit): 10358 collected, 10346 passed, 12 skipped (Windows-only), 0 failed, 0 errors.
- `test_the_old_percentile_bootstrap_would_fail_that_calibration` (new in this task) uses phi 0.5 and
  asserts > 0.09. At 90 days the rejected method measures 7.5-8.0% at phi 0.3, too close to the bound.
  Review 5 judged this legitimate, not a weakening: the product's calibration tests are unchanged.

## Reviews
Five fresh-context independent reviews:
1. FAIL. F-1 and F-2 HIGH.
2. FAIL. N-1 HIGH.
3. FAIL. H-1 HIGH.
4. FAIL with 0 HIGH. NEW-1 MEDIUM, which led to the 90-day floor.
5. PASS: 0 BLOCKING, 0 HIGH, 1 MEDIUM, 3 LOW, 4 INFO.

## Current state
Task 006 is implemented and verified. The milestone stays ACTIVE (not closed) until M-A below is resolved.

## Known issues (review 5, open)
- **M-A MEDIUM**: positions still open at each window end (`result.open_trades`) are excluded from
  daily_net/EV/statistics. In a no-edge simulation with about 12-day holds, the false-positive rate was 7.5%;
  with intraday holds it was about 4.5%. Fix (mark to market at the window end) or owner-accepted residual:
  **owner decision required**.
- L-A LOW: the regime no-lookahead test cuts on a day boundary, so it cannot catch same-day lookahead.
- L-B LOW: CI quantiles leave out resamples with no spread. The p-value counts them conservatively; the CI
  does not.
- L-C LOW: no regression tests pin the digest coverage of daily_net/ev/regimes. The behaviour was verified
  by the reviewer.
- I-A: the unkeyed digest (pre-existing NEW-M3/U1) now feeds the p-value directly.
- I-C: `Template.days` defaults to 30, and a direct `run_pipeline` call bypasses the CLI floor. This is
  conservative: such families can only score NO_EVIDENCE.
- Pre-existing, unrelated: the flake `tests/test_apprentice.py::test_ceo_evidence_selection_is_learned_from_what_the_ceo_cited`
  (`atlas_org_cli.now()` has 1-second resolution). Proposed fix: freeze `now` in that test. Not changed.

## Risks
The peso-problem residual: about 3-14% false positives at 90 days for rare-loss P/L (owner-accepted). BH and
the sealed gates remain.

## Remaining work
Owner decision on M-A; then fix L-A/L-B/L-C (and M-A if chosen) in one follow-up, with an independent re-review.

## Next exact action
Ask the owner: M-A fix (mark open positions to market at the window end) or accept it as a recorded
residual in a v5.90 successor record.
