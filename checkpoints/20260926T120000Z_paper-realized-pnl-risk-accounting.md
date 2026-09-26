# ATLAS CHECKPOINT — PAPER realized P&L into risk accounting + halted-rollover refusal (LOW-3)

## Objective
Close two follow-ups from the v4.81 independent audit:
- **LOW-3:** the automatic rollover gate must refuse while the runtime is halted.
- **Inert limits:** nothing in production updated `realized_daily_pnl` or refreshed `current_equity`/`peak_equity`, so RiskEngine's daily-loss limit and drawdown ladder never saw real data.

## Completed
- Implementation commit `5b670bc` on `research/edge-validation`.
- Registry v4.82 (`governance/current/ATLAS_MILESTONE_REGISTRY_v4.82.json`) adds one successor record, `paper_realized_pnl_risk_accounting_and_halted_rollover_refusal_result`.
- CRITICAL final gate steps, all done: IMPLEMENT, TEST, SELF-REVIEW, REGRESSION, INDEPENDENT AUDIT, FIX, RE-TEST.
- Scoped re-review of the HIGH-1 fix: CLOSED.

## Files changed
- `core/execution_manager.py`:
  - `_risk_day_rollover_refusal()` returns EXECUTION_HALTED or RECOVERY_REQUIRED first.
  - `_finalize_durable_financial_state`: the snapshot, `apply_confirmed` and the accounting hook now run under the manager lock plus the journal lock.
  - New `_record_realized_risk_accounting()` and three constants.
  - New imports: `nullcontext` and `RestoredRiskState`.
- `tests/test_risk_accounting_realized_pnl_wiring.py` (new, 29 tests).
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.82.json` (new).
- `core/risk_state_store.py` and `core/risk_engine.py` are **unchanged**.

## Architecture decisions
- **Trigger:** every non-replayed SELL apply, full exit or partial reduction.
- **Realized P&L** = Δ`realized_gross_pnl` − Δ`fees` − released `entry_fees`, all taken from foundation snapshots either side of the commit. Over a full round trip this equals Δ`realized_net_pnl`.
- **Equity:** `current_equity` is the post-commit snapshot equity. `peak_equity` = max(stored peak, that equity).
- **Day rule:** the stored day must be today. A midnight race counts as a recording failure.
- **Audit:** PREPARED (write-ahead) → atomic `save()` → COMMITTED. When `audit_enabled=False` the state is still written, without audit (audit LOW-2, accepted pending owner review).
- **Failure:** the hook raises `RISK_ACCOUNTING_UPDATE_FAILED` into execute()'s existing post-apply finalization-failure path:
  - the journal entry is left COMMIT_STATUS_UNKNOWN on disk;
  - the runtime halts with DURABLE_FINANCIAL_FINALIZATION_FAILED;
  - restart stays fail-closed.
- **Mode:** PAPER only.

## Configured thresholds (for owner visibility)
- `total_capital` is 10000, the CapitalManager default. `max_daily_loss_pct` is 0.05, so the daily ceiling is 500. `max_daily_loss_amount` is None. Drawdown bands: warning 5%, restrict 10%, halt 15%.
- Reason codes: the daily limit rejects as **DAILY_LOSS_LIMIT_BREACHED**. **DRAWDOWN_HALT_NEW_RISK** is the separate 15% drawdown check. The prompt conflated the two.
- Both reject new-risk BUYs only. Neither halts the runtime.

## Tests
- 29 new tests.
- Full suite on HEAD ee49011 plus this change, in a clean worktree: **4548 passed / 1 failed / 1 skipped** in 182.45s.
  - The failure is the accepted B2 `test_forbidden_layer_imports` (atlas_finance edges only).
  - The skip occurs only in the worktree.
  - Baseline: 4520 + 29 = 4549.
- Mutation evidence:
  - hook disabled: 18 fail
  - LOW-3 removed: 4 fail
  - locks removed: 1 fail
  - replay guard removed: 1 fail
  - in-memory-only halt: 5 fail

## Current state
- Committed.
- Authority is unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- Live-instance verification: NOT_PERFORMED.
- The operator state (read-only) has never applied a trade, so there is no backlog.

## Known issues / risks
- **MEDIUM-1 (deferred, owner decision):** operator journal recovery does not re-book the realized P&L into risk accounting. The operator must reconcile the risk store from the PREPARED audit record and foundation data. Possible follow-ups:
  - a runbook step;
  - a tool check that refuses recovery while a PREPARED record lacks its COMMITTED;
  - a recompute tool.
- **Equity refresh timing:** equity refreshes only on SELL commits and at rollover. An unrealized drawdown therefore does not trigger HALT_NEW_RISK.
- **Lock hold time:** the manager lock is now held across `apply_confirmed` fsyncs. This is latency only.
- **Concurrent session:** another session is doing uncommitted dashboard work in this tree (`web_app.py`, `observability/*`, `templates/*`, `static/`, `core/market_loop.py`). It is untouched here, and its `test_router_never_triggers_a_test_run` fails while uncommitted.
- **Stale worktree folder:** `.git/worktrees/cleanwt` is a leftover admin folder that cannot be deleted (permission denied, same as three older ones). It is unregistered and harmless.

## Remaining work
- The owner starts a PAPER run to verify live. Expected on the first SELL: a `RISK_ACCOUNTING_REALIZED_PNL_PREPARED`/`COMMITTED` pair and an INFO log line "Risk accounting realized P&L recorded".
- Owner decisions: MEDIUM-1 and LOW-2.

## Next exact action
The owner restarts Atlas in PAPER mode. After the first reduction, check `risk_accounting_state.json` `realized_daily_pnl` and `current_equity` against the `execution_financial_state.json` figures.
