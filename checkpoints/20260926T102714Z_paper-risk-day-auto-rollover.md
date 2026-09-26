# ATLAS CHECKPOINT — Automatic PAPER risk-accounting day rollover

## Objective
Close the permanent-block defect: `RiskEngine.evaluate` (core/risk_engine.py:440-441) rejects every request whose durable `accounting_day_utc` is not today's UTC date, and `JsonRiskStateStore.rollover()` had no production caller. After the first UTC midnight, every execution was refused with RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED. The authorizing prompt reports 7/7 rejected in a real run on 2026-09-26. That run was not re-observed in this session.

The owner decided that the rollover is automatic in PAPER mode, gated, and that LIVE stays purely fail-closed.

## Completed
- Implementation commit `a97bfe1` on `research/edge-validation`.
- Registry v4.81 (`governance/current/ATLAS_MILESTONE_REGISTRY_v4.81.json`) adds one successor record, `paper_risk_accounting_day_auto_rollover_result`.
- CRITICAL final gate steps, all done: IMPLEMENT, TEST, SELF-REVIEW, REGRESSION, INDEPENDENT AUDIT, FIX, RE-TEST.

## Files changed
- `core/execution_manager.py`:
  - `_orphan_reservation_ids()`: F-2 detection extracted verbatim. `None` means the question can't be answered.
  - `_release_orphan_reservations`: now uses the extracted helper, with unchanged behaviour.
  - `_risk_day_rollover_refusal()`: the gate.
  - `_auto_rollover_risk_accounting_day()`: the rollover itself.
  - A hook at the top of `risk_check`.
  - `_record_audit_failure`: the `request` annotation is now Optional.
- `tests/test_risk_accounting_day_auto_rollover.py` (new, 32 tests).
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.81.json` (new).

## Architecture decisions
- **Hook-in point:** only `ExecutionManager.risk_check`, immediately before `_derive_risk_state`.
  - This is the single place a RiskState is derived for evaluation.
  - It covers both a restart on a later day and an uninterrupted run through midnight.
  - A startup-only hook would miss the uninterrupted-run case.
  - A MarketLoop hook would route financial-state mutation through the market path, which project doctrine forbids.
- **Mode:** `if self.mode != self.MODE_PAPER: return` runs before any load, gate or write. LIVE has no automatic path.
- **Gate:** every condition must hold.
  - The journal is loaded and has nothing unresolved.
  - F-2 orphan detection can answer and returns an empty list.
  - The foundation is ready.
  - Audit is enabled.
  - Equity is finite and positive.
  - The journal lock is available.
  - Open positions never block.
  - A refusal leaves the stored day untouched and logs a WARNING with the reason, and RiskEngine then rejects as before.
- **Atomicity:** the gate, the equity read, the PREPARED audit event and the atomic save all run under ExecutionManager._lock plus ExecutionTransactionJournal._lock, so no `prepare()` can land in between.
- **Audit:** PREPARED is written ahead and is mandatory; COMMITTED follows with `causation_id` pointing to PREPARED. If COMMITTED fails, the audit runtime goes to AUDIT_DEGRADED and the rollover stays durable.
- **Equity source:** `ExecutionPortfolioFoundation.snapshot()["equity"]`.

## Tests
- 32 new tests.
- Full suite on the final code: **4520 passed / 1 failed**, in 135.96s.
  - The one failure is the accepted Group B2 `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports` (the same atlas_finance edges seen since v4.29).
  - The baseline was 4488 / 1, so 4488 + 32 = 4520.
- The tests catch the bug:
  - With the hook disabled, 10 of the first 21 new tests fail.
  - With the journal lock removed, the prepare-atomicity test fails.

## Independent audit
- No BLOCKING or HIGH findings.
- MEDIUM-1 (prepare-atomicity untested): fixed.
- MEDIUM-2 (untested fail-closed branches): fixed.
- LOW-1 (COMMITTED failure did not degrade audit): fixed.
- LOW-4 (fallback when the journal lock is missing): fixed; the rollover now refuses.
- LOW-2 (repeated PREPARED events on a persistent save failure): accepted and documented.
- LOW-3 (the gate doesn't consult halt flags): deferred for an owner decision. `execute()` already blocks on these flags before `risk_check`.

## Current state
- The fix is committed.
- LIVE is still DENIED. Authority is unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- Live-instance verification: NOT_PERFORMED.

## Known issues / risks
- **Pre-existing, out of scope:**
  - No production code accumulates `realized_daily_pnl` or refreshes `current_equity` in the risk store, apart from bootstrap and this rollover.
  - So the daily-loss limit is effectively inert, and `current_equity` refreshes only at rollover.
  - After a drawdown, the first rollover can correctly trigger DRAWDOWN_HALT_NEW_RISK.
  - This should become a future package.
- Operator-facing: the real `memory_data` risk state is currently stale. The first PAPER request after restart will attempt the rollover, and it will refuse if the journal or reservations are dirty.
- While the state is dirty, every request logs a REFUSED WARNING. That is noisy, but correct.

## Remaining work
- The owner starts a real PAPER run to verify live. Expected evidence:
  - One `RISK_ACCOUNTING_DAY_ROLLOVER_PREPARED`/`COMMITTED` pair in the audit log.
  - A WARNING rollover log line.
  - Execution requests no longer rejected with RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED.
- Deferred: LOW-3 (owner decision), and the daily PnL / equity refresh package.

## Next exact action
The owner restarts Atlas in PAPER mode against the real state directory. Then check:
- The logs for "Automatic PAPER risk-accounting day rollover" (success) or "REFUSED reason=..." (dirty state that needs reconciliation).
- The audit log for the event pair.
