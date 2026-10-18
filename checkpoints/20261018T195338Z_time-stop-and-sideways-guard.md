# ATLAS CHECKPOINT — SA-FEE-DRAG.1 time-stop replay, range-regime floor, process_symbol split

## Objective
Owner sprint spec on branch `feature/time-stop-and-backtest` (from `claude/exp001-on-owner-lineage` HEAD 6d6b846). Owner decisions taken in session: (1) replay first — time-stop/trailing stop in `tools/backtest_replay.py` only, no runtime exit rule; (2) Phase 4 regime floor in the risk layer; (3) split `process_symbol` only; (4) use the feature branch and push it.

## Completed
- **Replay (research only):** `time_trailing_exit()` plus `max_hold_min`, `trail_activation`, `trail_distance` in `replay()`. TIME_STOP closes a position held >= the cap whose net unrealized P&L (after exit fee and carried entry fees) is not positive. TRAIL_STOP arms at +activation and exits on a pullback from the peak close. Judged on the closed candle only (no lookahead; verified with `tools.lookahead_check`). A stopped-out symbol skips that step's decision. Defaults reproduce the baseline exactly.
- **Comparison matrix:** `compare_time_stop()`, `format_matrix()`, CLI `--compare-time-stop`, `--max-hold-hours`, `--trail-activation`, `--trail-distance`. Net P&L, win rate, max drawdown %, fees and fee-drag delta; open positions are marked to market in both columns. `tools/digital_trial.py` accepts the same flags.
- **Phase 4:** `RiskPolicy.range_regime_minimum_confidence` (default empty = OFF), `RiskRequest.market_regime`, `RANGE_REGIME_MEDIUM_FLOOR` (MEDIUM 0.70 -> 0.75). SIDEWAYS, TRANSITION, UNKNOWN or missing regime raises the floor (fail closed, NB-4); raise-only; also bounds the experiment floor; exits never see it. `ExecutionManager` forwards `metadata["market_regime"]` (set by MarketLoop's regime gate).
- **Phase 5:** `process_symbol` 190 -> 86 lines via `_symbol_commit_decision`, `_symbol_route`, `_symbol_contract_violation` (statements moved verbatim, same order, same try/except).
- Packaging maps regenerated (line numbers only).

## Files changed
core/risk_engine.py, core/execution_manager.py, core/market_loop.py, tools/backtest_replay.py, tools/digital_trial.py, tests/core/test_time_stop.py (new, 23), tests/core/test_risk_engine.py (new, 29), packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md, packaging/REM-001_STATE_AUTHORITY_MAP.md.

## Architecture decisions
- Regime source is `core/market_cycle.py` labels (the runtime classifier with SIDEWAYS and TRANSITION), not `intelligence/regime/market_regime_engine.py` (no TRANSITION, unused by core) and not `MarketRiskRegime` (volatility HIGH/LOW/NEUTRAL only). The owner's answer named market_regime_engine on the basis of an incorrect statement by the assistant that SIDEWAYS exists only there; the corrected choice needs owner confirmation.
- The Phase 4 floor ships OFF (Task 007 pattern); enabling it in the runtime is a separate owner decision. Because a missing regime fails closed, enabling it also requires regime observation (`regime_observation` or `regime_gate`) to be on, otherwise every MEDIUM BUY needs 0.75.
- No runtime time-stop/trailing exit was built (owner chose replay first).

## Tests
- `tests/core/test_time_stop.py` 23 passed; `tests/core/test_risk_engine.py` 29 passed.
- Golden/regression: test_process_symbol_golden, test_risk_check_golden, test_code001_quality_ratchet, test_backtest_replay, test_digital_trial, test_lookahead_check, block2/3/5a, phase3 risk, policy manifest, task007 all pass.
- Full suite on Python 3.13: 2 failed (the two REM-001 packaging maps, line numbers shifted), 11307 passed, 12 skipped (Windows-only). After regeneration `tests/architecture` 102 passed; a final full-suite re-run is recorded in the commit report.

## Current state
Committed on `feature/time-stop-and-backtest`. Not merged. production_authority=NONE, live_authority=DENIED unchanged.

## Known issues
- The matrix has NOT been run on real Binance data (no data and no network evidence in this session); on synthetic candles the real brain makes no trades. No performance claim is made. Stub-brain tests cover the logic only.
- Replay is 1-minute only: MarketLoop is hard-wired to 1m, so 5m candles are not supported (deferred).
- Governance registration (successor registry record for these changes) is UNKNOWN / not done; no grant exists in the repo for them.
- The proposal SA-FEE-DRAG.1 tests a MINIMUM hold; the spec's MAXIMUM hold is a different hypothesis and needs its own proposal record.
- Spec's `py -m pytest` and tests/core/test_execution_manager.py do not exist; python3.13 and the golden tests were used.

## Risks
Phase 4 edits risk_engine, execution_manager (CRITICAL files) but is inert while the policy field is empty (decisions byte-identical, asserted in tests). The process_symbol move is pinned by the 21-scenario golden test.

## Remaining work
Run `--compare-time-stop` on real walk-forward windows; owner decisions on regime source, enabling the floor, and a registry record; independent audit (CRITICAL gate) not yet performed.

## Next exact action
Owner reviews this branch; if the replay evidence wins on every window, open a separate CRITICAL proposal for any runtime exit rule.
