# ATLAS CHECKPOINT — Task 025: Forex leverage 1:2 (margin book) and a 100 % stop-out

## Objective
Let a forex position reach the 0.01-lot minimum at the HIGH bucket (known issue from registry v5.103). This is
done with a governed 1:2 margin book and a stop-out at a 100 % margin level, PAPER only.

- **Grant:** GRANT-TASK-025-FOREX-LEVERAGE-MARGIN, registry v5.108, which also ratifies policy manifest v4.
- **Owner approval:** on 2026-10-27 the owner chose 'Kaldıraç ve short onaylı' (recorded verbatim in v5.108). The
  values themselves were chosen on 2026-10-26: '1:2 (Önerilen)' and '%100 (Önerilen)'.
- **Authority is unchanged:** live DENIED, production NONE.

## Completed
- **`core/execution_portfolio_foundation.py`: schema 3, the margin book, for forex state only.**
  - The working file holds `leverage` (2–5), and each position holds `margin`, which is notional / L.
  - A BUY debits margin + fee. A reduction credits the released margin + realized gross − fee. Margin is
    released pro rata, as a complement, like the cost basis.
  - Equity = cash + used margin + unrealized P&L. `spendable_cash` = cash + min(unrealized, 0), so a paper gain
    never funds new risk.
  - A margin book may record negative cash: a loss larger than the account is recorded, never hidden, and new
    risk is then refused.
  - Schema 2 (every crypto book) is byte-identical and never migrated. A book whose leverage differs from the one
    expected is not ready (`FINANCIAL_LEVERAGE_CONFLICT`). Operator recovery and the tools read the book at its
    own leverage (`leverage=None`).
  - Closed records carry `margin` exactly when the book is a margin book.
- **`core/risk_engine.py`: `RiskPolicy.leverage` (default 1).**
  - Every notional ceiling is measured against total_capital × L: the capacity limits, the position cap, the
    cluster and quote exposure caps, the sleeves and the reported available capital.
  - Daily loss, drawdown, the Kelly and volatility ceilings, the reserve, and a request's own leverage
    (`LEVERAGE_NOT_PERMITTED`) are unscaled.
- **`core/position_sizing.py`:** the proposal is × L, and free cash still bounds it.
- **`core/execution_manager.py` and `core/market_loop.py`:** new-risk funding reads `spendable_cash`, which
  equals `cash` in a cash book.
- **`core/exit_guard.py`: the `STOP_OUT` rule (a SAFETY_EXIT).**
  - The margin level is re-marked with fresh prices. At or below the threshold, every position is closed,
    largest loss first.
  - An unreadable level exits. A stale price never sells (EXIT_PENDING_PRICE).
- **`core/application.py`, FOREX:** RiskPolicy leverage 2, a book at leverage 2, and the guard in ENFORCE with
  the rules [STOP_OUT, WEEKEND_CLOSE]. CRYPTO is unchanged.
- **`core/policy_manifest.py`:** one successor-verification path for v3 and v4. The v4 chain is code → v5.108 →
  manifest v4 → v5.107. The new switches are `risk_leverage`, `book_leverage` and
  `forex_stop_out_margin_level`. v2 and v3 remain verifiable by their own rules.
- **Bootstrap and tools:**
  - `bootstrap_financial_state --leverage N`.
  - `tools/reconcile_execution_authorities.py` and `tools/data_health_check.py` read a schema 3 book.

## Files changed
- **Commit 1:** registry v5.108 + `governance/policy/ATLAS_POLICY_MANIFEST_v4.json`. They belong together because
  v5.108 pins the manifest's bytes.
- **Commit 2:**
  - the core modules above;
  - `atlas_finance/forex/{instruments,__init__}.py`;
  - `core/financial_state_bootstrap.py`;
  - `tools/bootstrap_financial_state.py`, `tools/reconcile_execution_authorities.py`, `tools/data_health_check.py`;
  - `tests/test_task025_forex_leverage.py` (new);
  - the packaging maps (regenerated);
  - this checkpoint.
- **Test changes, disclosed:**
  - `tests/test_block5c_upstream_sizing_authority.py`: `seed_state` gains `leverage=1`. The default is
    unchanged; 2 seeds a margin book.
  - `tests/test_task023_policy_manifest_v3.py`: the synthetic v3 chain tests name `MANIFEST_V3_PATH`
    explicitly, because v4 is now active. The FOREX application test now expects 2 rules and adds an assertion
    that the sealed v3 differs only on `exit_guard_rules`. The guard test expects [STOP_OUT, WEEKEND_CLOSE].
  - `tests/test_task024_forex_holidays.py`: the test picks the WEEKEND_CLOSE rule by kind instead of by index.
  - `tests/test_phase2_g1_policy_manifest.py`: the runtime keys are now `CRITICAL_SWITCHES_V4`.
  - `tests/intelligence/test_task009_regime_tracking.py`: two book fakes gain `spendable_cash` (= cash), so they
    match the snapshot contract. No assertion changed (review HIGH-1).

## Tests
- **Task 025:** 77 passed.
- **Mutation check:** 19 planted bugs on a scratch copy. The first pass caught 18. The survivor (a manifest
  reader returning a constant) was killed by an added test, so 19 of 19 are caught.
- **Independent read-only review:** 0 BLOCKING / 1 HIGH / 2 MEDIUM / 2 LOW / 3 INFO. All HIGH, MEDIUM and LOW
  findings are fixed: the test fakes, the recovery and health tools, the closed-archive kind check, and the added
  tests.
- **Re-review:** 0 BLOCKING / 0 HIGH / 0 MEDIUM / 1 LOW / 4 INFO; 442 + 406 targeted tests passed.
  - LOW-R1 is fixed: the cross-kind archive test now asserts the refusal reason. That edit strengthens one
    assertion; it was made after the full-suite run started, and the file was re-run alone: 77 passed.
  - INFO-R1, kept: the operator tools open either kind of book in any directory. The runtime still refuses a
    market/book mismatch.
- **Full suite (Python 3.13):** 11573 passed, 12 skipped, 0 failed (11496 before + 77 new).
- **`tests/architecture`:** 102 passed (after regenerating the maps).

## Known issues / Risks
- **Swap / rollover is not charged.** It is UNKNOWN until read from MT5 (`swap_long` / `swap_short`), so paper
  results are optimistic by the swap.
- **An existing FOREX schema 2 book is not ready.** It must be re-bootstrapped with `--leverage 2` (no
  migration, by the grant's design). Whether such a book exists on the owner's machine is UNKNOWN.
- **Gap risk.** A gap past the stop-out level can lose more than the margin. That shows up as negative cash.
- **Stop-out scope.** The stop-out closes every position, which is more conservative than MT5's close-one-at-a-time.
- **Carried over:** T023-F4/F5/F6 and the December early closes (Task 024).

## Remaining work
1. Task 026: short selling (approved; needs its own registry record).
2. CLAUDE.md update (owner document).
3. Owner: the MT5 test on Windows, with the new bootstrap command:
   `python -m tools.bootstrap_financial_state --state-directory C:\AtlasState\forex\shadow --leverage 2`.
4. The measured commission and swap (manifest change).
5. Task 020: crypto removal.

## Next exact action
Task 026: registry v5.109, then the short-selling design-to-code on the margin book.
