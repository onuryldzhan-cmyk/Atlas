# ATLAS CHECKPOINT — PAPER crash-recovery books realized P&L into risk accounting (v4.82 MEDIUM-1)

## Objective
Make `tools/reconcile_execution_authorities.py` book a recovered COMMITTED SELL's realized P&L and equity into `risk_accounting_state.json`. It must reuse the hook normal execution uses, `ExecutionManager._record_realized_risk_accounting` from commit `5b670bc`, and book PAPER only.

Classification: CRITICAL (touches risk accounting, execution recovery and migration-style state transitions). The full final gate applied.

## Completed
- IMPLEMENT, TEST, SELF-REVIEW, REGRESSION, INDEPENDENT AUDIT, FIX and RE-TEST are all done.
- Registry `governance/current/ATLAS_MILESTONE_REGISTRY_v4.84.json` is written as an additive successor to v4.83 (`58efbd0`). Only the 3 header lines changed, plus one appended member, `paper_recovery_risk_accounting_booking_result`.
- **Nothing is committed.** The working tree holds all changes on base `58efbd0`.

## Files changed
- `tools/reconcile_execution_authorities.py`
  - New: `RiskAccounting` enum and `ReconciliationResult.risk_accounting`.
  - New helpers: `_plan_risk_accounting`, `_require_redo_book`, `_redo_before` and `_book_risk_accounting`.
  - The risk store joins the rollback set.
  - `_verify_recovery` gains a SELL accounting check.
  - New refusal codes: `RISK_ACCOUNTING_EVIDENCE_UNAVAILABLE` and `RISK_ACCOUNTING_DAY_NOT_CURRENT`. New failure code: `RISK_ACCOUNTING_UPDATE_FAILED`.
  - The CLI attaches a NullHandler to the `AtlasAI` logger.
  - Docstrings are updated.
- `tests/test_recovery_risk_accounting_booking.py` is new, with 33 tests.
- `observability/panel_sources.py`: the limitation `RISK-ACCOUNTING-RECOVERY-REBOOK-GAP-001` gets new status and summary text only.
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.84.json` is new.
- Unchanged: `core/execution_manager.py`, `core/risk_state_store.py`, `core/risk_engine.py`, and the K1/abort and LIVE paths.

## Architecture decisions
- **CONFLICT with the task premise.**
  - The prompt assumed K3–K6 never book the P&L. In fact the hook runs inside `_finalize_durable_financial_state`, before K3–K6, so those windows are already booked.
  - Calling the hook there would double-book.
  - The implementation is therefore exactly-once. It compares the hook's own PREPARED write-ahead record with the stored state:
    - new_state stored → ALREADY_RECORDED;
    - previous_state stored → RECORD (redo; the hook must reproduce new_state);
    - no PREPARED → K2 books, and applied-evidence is refused.
- **K2 booking.** `before` is `_pre_transition_view(transition).snapshot()`. `after` is the snapshot that `complete_interrupted_transition` returns.
- **Order.** The book comes first, then accounting, reservation, idempotency, and the journal last. This is the runtime's order.
- **Audit log.** It is never rolled back. A stale PREPARED is harmless, because the restored store equals its previous_state.

## Tests
- New file: 33 passed.
- Targeted regressions, all passing: f1_f6, block5j, block5k, realized-pnl wiring, dashboard and observability panel.
- **Full suite on the final code: 4633 passed / 1 failed / 0 skipped in 318.62s.**
  - This matches the v4.83 baseline of 4600/1/0 plus 33.
  - The failure is the accepted B2 `test_forbidden_layer_imports`, with `atlas_finance` edges only.
- Mutation evidence:
  - no booking: 10 fail
  - ALREADY_RECORDED ignored (double booking): 4 fail
  - day check removed: 1 fail
  - rollback set: 1 fail
  - silent skip: 1 fail
  - NullHandler removed: 1 fail
- Threshold crossing via recovery is proven for both the K2 and redo paths.
  - DAILY_LOSS_LIMIT_BREACHED: the store shows 0 before recovery, and after recovery the restarted `risk_check` rejects.
  - DRAWDOWN_HALT_NEW_RISK: likewise proven.

## Independent audit
- BLOCKING and HIGH: none.
- **MEDIUM-A** was accepted fail-closed, pending owner review. If the tool itself is killed between completing a K2 SELL book and the hook's PREPARED, every rerun refuses `RISK_ACCOUNTING_EVIDENCE_UNAVAILABLE`. This is documented and tested.
- **LOW-B** (identifiers on stderr) is fixed.
- **LOW-C** (audit provenance, and COMMITTED left behind on rollback) is deferred.
- **LOW-D** (test gaps) is fixed, except the `position_closed` mismatch branch.

## Current state
- Uncommitted.
- Authority is unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- Live-instance verification: NOT_PERFORMED.

## Known issues / risks
- **EXEC-ID-REDACTION-001** is a new, pre-existing, out-of-scope finding; the proposed severity is HIGH.
  - `ExecutionTransactionJournal` and `ExecutionIdempotencyStore` sanitize results.
  - The redactor corrupts about 0.25% of uuid4 `execution_id`s, for example `...-4923-8615-...` → `[REDACTED]`. That is 49 of 20000 measured.
  - This caused every intermittent K-matrix failure seen this session. The evidence was captured with temporary instrumentation, since removed.
  - It needs its own CRITICAL package.
- The day-not-current refusal has no tool-side remedy, because the halted runtime never rolls the day. A crash recovered after UTC midnight needs operator reconciliation.
- COMMIT_STATUS_UNKNOWN left by a runtime hook failure is still outside the tool (unchanged).
- The `.git/worktrees/wt_head` admin folder could not be deleted (Permission denied, like 4 older ones). It is unregistered and harmless.

## Remaining work
- Owner:
  - approve and commit, as an implementation commit followed by a registry commit;
  - decide on MEDIUM-A and LOW-C;
  - schedule EXEC-ID-REDACTION-001.
- After committing, fill in the implementation commit hash before the registry is committed. The registry currently says UNKNOWN.

## Next exact action
- Stage and commit the implementation: `tools/reconcile_execution_authorities.py`, `tests/test_recovery_risk_accounting_booking.py`, `observability/panel_sources.py`.
- Update v4.84's `implementation_commit`.
- Commit the registry together with this checkpoint.
