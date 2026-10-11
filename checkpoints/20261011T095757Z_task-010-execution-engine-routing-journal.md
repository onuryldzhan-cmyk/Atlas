# ATLAS CHECKPOINT — Task 010: Execution Engine, Order Routing & Transaction Journal Integration

## Objective
Implement Task 010 under GRANT-TASK-010-EXECUTION-ENGINE-ROUTING-JOURNAL (registry v5.94), within the
owner's decision: paper + simulated venue only. The work covers:
- the environment firewall;
- the lifecycle journal with partial fills;
- reconciliation across disconnects and restarts;
- terminal rejection with local balance release;
- recovery of a stalled market-data feed.

Brief red-team vectors: A duplicate fills, B live key leakage, C state desynchronization.

## Completed
- **CONFLICTs C-1..C-9** reported to the owner, then decided in session on 2026-10-11:
  - v5.94 was absent and Task 009 was ACTIVE; "Phase 4 CLOSED" is UNKNOWN.
  - The brief's "governance ZERO" contradicted its own v5.94 deliverable.
  - The live grant asked for contradicts live DENIED: there is no live adapter and no signature mechanism.
  - The mode names differ from the existing gate.
  - There is no WebSocket client in the runtime.
  - Two journals exist, and neither modelled partial fills.
  - The feed latch lives outside the brief's scope list, and the runtime has no standing stop-loss.
  - The intelligence/regime premise does not hold.
  - "Madde" is UNKNOWN.
- **Owner decisions:**
  - Draft v5.94: close Task 009, grant Task 010.
  - Paper + simulated venue only.
  - Extend scope to fix the feed latch.
  - Audit first and adapt to the repository: keep PAPER/LIVE, use REST polling, Task 008's venue
    journal is the lifecycle journal.
- **Registry v5.94** (committed on its own): Task 009 CLOSED; Task 010 defined, granted and ACTIVE. It
  also records the conflicts, the audit findings, the unknowns and reviews 20–21.
- **exchange/exchange_manager.py:**
  - Reconcile firewall: no order-status query outside live authorization.
  - Fill ledger: FILL events carry the cumulative quantity. Progress is monotonic and checked for
    overfill, regression, quantity mismatch and malformed numbers; a failed check is journaled as
    UNRECONCILED and the pair freezes.
  - Events after TERMINAL are refused when journaling and ignored on replay.
  - `filled_positions()` and `order_state()` (core.order_lifecycle terms) are derived from the journal.
  - Exposure reservations: an open BUY is reserved atomically with its check. Any terminal outcome or
    proven non-dispatch releases it. It is restored after a restart.
  - `status()['order_fills']`.
- **exchange/execution_exposure_guard.py:**
  - New: `reserve` / `restore_reservation` / `release` / `reservations`, guarded by a lock.
  - Reservation-aware projections for symbol, total, cash floor and positions.
  - `authorize_order` and `update_portfolio` behave as before.
- **exchange/adapters/binance_global.py:** public calls use a keyless client. A signed client is created
  for each order query and never kept.
- **atlas_finance/market_data/market_feed_service.py (scope extension):**
  - A DEGRADED feed keeps serving and recovers on its next success.
  - Degrade and recover are each decided under the one service lock.

## Files changed
- **Task 010 commit:**
  - exchange/exchange_manager.py, exchange/execution_exposure_guard.py, exchange/adapters/binance_global.py
  - atlas_finance/market_data/market_feed_service.py
  - tests/core/test_task010_execution_engine.py (new, 48 tests)
  - packaging/REM-001_IMPORT_GRAPH.json, packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md,
    packaging/REM-001_STATE_AUTHORITY_MAP.md (regenerated)
  - this checkpoint
- **Separate commit:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.94.json.
- **Unchanged:** core/execution_manager.py, core/application.py, core/execution_transaction_journal.py.

## Architecture decisions
- Live stays DENIED. There is no venue path from ExecutionManager; the link to the core journal is the
  deterministic client order id.
- Task 008's venue order journal is the single lifecycle journal; FILL is a new event in it.
- Filled exposure still reaches the exposure guard only through update_portfolio, as before.
  Reservations cover open orders only.
- Partial fills are tracked as cumulative snapshots in a small ledger that uses core.order_lifecycle
  names and rules. It does not use the strict per-fill Order object.

## Tests
- Full suite: 10625 passed, 12 skipped, 0 failed. That is the 10,577 baseline plus the 48 Task 010
  tests. Verified by the final gate run before commit.
- Every fix was mutation-checked; the remaining survivors are masked by another layer of the same fix
  and are recorded in v5.94.

## Reviews (fresh context, red team, threshold 0 BLOCKING / 0 HIGH / 0 MEDIUM)
- **Review 20 — FAIL (1 MEDIUM).**
  - F-1: a reconcile racing another reconcile's TERMINAL left a finished order open after a restart.
  - F-2 to F-6 (LOW): key header on public calls, unsent-order ledger entries, test gaps, raw statuses,
    the feed race.
  - All fixed.
- **Review 21 — PASS (0/0/0).**
  - It ran a 40-seed stress harness: every order reached the venue exactly once, there was no deadlock,
    and replay was exact.
  - Its LOW findings were fixed before commit: a kept signed client, a never-dispatched reservation
    leak after restart, feed races, wording, and the mutation claim.

## Current state
Task 010 is implemented and verified, and its milestone is ACTIVE; closing it is the owner's decision.
The paper runtime's order path is unchanged. The market-data feed now recovers from DEGRADED instead of
halting until restart.

## Known issues / limitations (all recorded in v5.94)
- Every venue in the tests is simulated; live venue behaviour is UNKNOWN.
- Filled exposure reaches the guard only via update_portfolio, and nothing in the runtime calls it.
- The fill ledger is exact only with the order journal configured.
- SELLs reserve nothing.
- The kill switch also stops reconciliation queries.
- An open BUY freezes its pair, SELLs included, until terminal.
- load_dotenv() still places keys in the process environment.
- The REM-001 generator's path truncation is pre-existing.

## Risks
- None to the paper runtime's decisions or orders.
- The feed change makes market data resume after a stall instead of halting, which is intended.

## Remaining work
- The owner closes Task 010.
- A live adapter, an owner-signature design and live routing would need a separate grant.

## Next exact action
Report to the owner.
