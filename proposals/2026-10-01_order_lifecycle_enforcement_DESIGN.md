# Enforce the order state machine inside ExecutionManager. Design, not implemented (2026-10-01)

**Status:** DESIGN ONLY. Classified CRITICAL because it touches the execution path. Coding starts only after the owner approves it and an independent audit (rules 4, 5, 8).

## Facts (verified 2026-10-01)
- `core/order_lifecycle.py` already holds the canonical rules:
  - terminal states never change;
  - DENIED can never be submitted;
  - UNKNOWN can only move to RECONCILING;
  - filled quantity is monotonic;
  - a repeated fill id is ignored.
- It is tested (`tests/test_order_lifecycle.py`, `tests/test_independent_audit_fixes.py`) but **not wired**. A grep shows no runtime import.
- ExecutionManager's current authorities stay: the journal, idempotency, and the financial state.

## Plan (step by step, each behind a flag that defaults OFF)
1. **Shadow-validate (observe only).** ExecutionManager mirrors each request into an `Order` (CREATED → VALIDATED/DENIED → SUBMITTED → FILLED/REJECTED). An illegal transition is logged as an INCIDENT. Behaviour does not change.
2. **Run on PAPER for at least 1 week.** Expected result: zero illegal-transition incidents. If any occur, they are investigated before step 3.
3. **Enforce.** An illegal transition blocks that order (fail-closed, `BLOCK_RECOVERY_REQUIRED`). It never silently continues.
4. **Persist.** Order states go into the journal record that already exists, as an extra field. This goes through the migration checklist (idempotency, resume, duplicates, partial state) and needs its own audit.

## Tests required
- Each step on its own.
- Flag OFF means byte-identical behaviour.
- Restart in the middle of an order.
- A duplicate fill.
- A DENIED order is never submitted.
- UNKNOWN leads to reconciling, never to failed.

## Decision required
The owner approves step 1 (observe only, the lowest risk).
