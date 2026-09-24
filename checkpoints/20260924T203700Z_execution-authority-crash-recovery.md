# ATLAS CHECKPOINT

## Objective

Owner brief (2026-09-24), CRITICAL tier: implement and regression-test the
fixes for the reconciliation audit findings F-1 (HIGH), F-2 (MEDIUM), F-3
(MEDIUM), F-5 (LOW) and F-6 (LOW). The audit is
`checkpoints/20260924T195526Z_execution-financial-state-reconciliation-audit.md`.
The fixes must not weaken duplicate-order rejection or the
no-silent-double-apply guarantee. F-4 and F-7 are out of scope. F-7 is
confirmed intentional by the owner.

The owner fixed the F-1 contract before work started:

- In PAPER mode, the outcome may be derived from internal simulation state.
- Ground truth comes first: durable applied or closed evidence is used
  directly.
- Deterministic re-derivation is allowed only when that evidence is
  inconclusive.
- There is an explicit mode branch, and LIVE stays fail-closed exactly as
  before.

Classification: CRITICAL (execution, capital, recovery). The full final gate
was run: IMPLEMENT, TEST, SELF-REVIEW, REGRESSION, INDEPENDENT AUDIT, FIX,
RE-TEST.

## Completed

- **Step 0 (housekeeping):** commit `1d000b1` holds the three pre-existing
  checkpoints and is documentation only. `git status --short` was empty
  before and after.
- **F-6** (`core/execution_portfolio_foundation.py`, `apply_confirmed`):
  `_open`/`_close` validation now runs on the candidate *before* the
  transition marker is persisted. A pure refusal leaves the working file
  byte-identical and the foundation ready.
- **F-3** (`core/capital_reservation.py`, `reserve`):
  - A RESERVED reservation with the same request and amount is adopted, as
    before.
  - A RELEASED one is re-armed as a fresh RESERVED version. This is
    capacity-checked and allows the new amount.
  - COMMITTED and INDETERMINATE are refused (`reservation already <STATUS>`).
  - The archived-id refusal is unchanged.
  - `risk_check` now also asserts that the returned reservation is RESERVED.
- **F-5** (`core/execution_manager.py`, CAPITAL_RESERVATION_COMMIT_FAILED
  branch): this branch now calls `_release_request`, `_record_result` and
  `publish`, mirroring the dac9b72 finalization-failure branch.
- **F-2** (`ExecutionManager._release_orphan_reservations`, called from
  `start()` when financial and durable readiness hold): releases RESERVED
  reservations only when all of the following are true.
  - The id has zero journal activity.
  - It is a canonical id (reservation_id equals request_id, and it equals
    its stripped form).
  - It is not in flight (pending claim or risk admission).
  - The journal loaded.

  A failed release halts the runtime with `CAPITAL_RESERVATION_RELEASE_FAILED`.
  A new ledger accessor, `CapitalReservationLedger.reserved()`, supports it.
- **F-1** (`tools/reconcile_execution_authorities.py`, plus foundation
  helpers):
  - A new `execution_mode` parameter (`--execution-mode PAPER|LIVE`) gates
    recovery. Only PAPER reaches the planner. LIVE or no mode refuses with
    `JOURNAL_UNRESOLVED`, exactly as before.
  - Exactly one PREPARED entry is classified:
    - `ABORT_NOT_APPLIED`: no applied record and no terminal result. The book
      is clean, or it holds only this request's marker with no sidecar
      orphan. Resolution: clear the marker, release the reservation, set the
      entry to NOT_COMMITTED.
    - `COMMIT_APPLIED_EVIDENCE`: the applied record exists and the book is
      clean. Resolution: commit the reservation, record the idempotency
      result if it is missing, set the entry to COMMITTED. The result is the
      genuine idempotency record when present (K6). Otherwise it is an
      evidence-only result with a `recovery` block and no fill figures
      (K3–K5).
    - `COMMIT_PAPER_REDERIVATION`: the K2 inconclusive window, a marker plus
      a sidecar orphan. The fill is re-derived by a throwaway
      `ExecutionManager.paper_execute` against the pre-transition book. It
      runs only if the RISK_APPROVED audit event *of the prepared attempt*
      proves PAPER mode and the current instrument-rules digest. Every
      on-disk orphan must equal the re-derived settlement. The application
      is then completed via `complete_interrupted_transition`.
  - Mode proof requires all of:
    - the operator's statement;
    - the prepared request's `mode == PAPER`;
    - no non-PAPER result anywhere in the journal.
  - The existing idempotency repair also runs a projection-adapter check
    after it writes. That check now skips evidence-only recovered BUYs, the
    same way it already skips SELLs, because those BUYs carry no fill
    figures by design.
  - New foundation API, used only by the tool:
    - `FinancialStateStore.load(allow_transition=...)`
    - `inspect_interrupted_transition`
    - `abandon_interrupted_transition`
    - `complete_interrupted_transition(verify_only=...)`
    - `InterruptedTransition`
    - `InterruptedTransitionError`
  - Write order: book, then reservation, then idempotency, then journal last.
    Any failure restores every touched file byte-for-byte
    (`RECOVERY_WRITE_FAILED` or `POST_RECOVERY_*`).
- **Docs:** ADR-0005 gained runbook section 7 (F-1/F-2). It also gained a
  dated amendment note to section 6, whose "idempotency store is the only
  file this tool can ever write" statement was retained, not erased.

## Files changed

- `core/execution_portfolio_foundation.py`
- `core/capital_reservation.py`
- `core/execution_manager.py`
- `tools/reconcile_execution_authorities.py`
- `docs/adr/0005-operator-bootstrap-runbook.md`
- `tests/test_execution_crash_recovery_f1_f6.py` (new, 39 tests)
- `tests/test_phase4_execution_position_portfolio_foundation.py` (2
  assertions changed, see Known issues)
- `tests/test_block5g_closed_position_lifetime_identity.py` (1 assertion
  block changed, see Known issues)

## Architecture decisions

- F-1 recovery is **operator-invoked** through the reconcile tool, never
  automatic at startup. "No journal-halt" means the entry is resolved, so the
  next start is healthy.
- The execution mode comes from an explicit operator statement,
  corroborated by durable evidence. `request.mode` alone is insufficient,
  because a decision can override it.
- COMMIT_STATUS_UNKNOWN entries stay out of the recovery. The owner's
  decision covered PREPARED only.
- The recovery runs alone. Pending idempotency-repair candidates are left for
  the next run.

## Tests

- New module: 39 passed.
- Discrimination: against the pre-fix `core/`+`tools/` (via an import shim),
  30 of the original 33 failed. The 3 that pass on both are intentional
  non-regression guards:
  - live-reservation adoption;
  - no re-reservation after success;
  - K0 same-candle retry.
- Blast radius (66 modules, 2203 tests): all passed after the Block 5G
  assertion update.
- Full suite, final code (`pytest tests`, ASCII basetemp), one run:
  **3945 passed, 1 failed**, 136.9s. The baseline was 3906 passed and 1
  failed. The +39 are exactly the new module.
- The single failure is
  `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`.
  It concerns `atlas_finance/*` import edges. This diff touches no
  `atlas_finance` file, and the failure is consistent with the known
  pre-existing Group B2 failure. That identity was not independently
  re-proven this session.

## Current state

- Branch `research/edge-validation`. Last commit `1d000b1`.
- The code changes are uncommitted, awaiting owner review.
- `memory_data/` and root `paper_trades.json` were verified untouched.

## Known issues / risks

- **Three existing test assertions were changed.** They pinned the exact
  behavior the owner ruled a defect under F-6: a pure refusal leaving the
  marker on disk and the book needing recovery. The changes are:
  - `test_increase_preserves_identity_and_rejects_stale_mutation`
  - `test_reduction_larger_than_the_holding_is_rejected`
  - `test_reused_closed_position_identity_fails_closed_without_overwriting`

  Every integrity assertion was kept. The replacement assertions are
  byte-level. **The owner should acknowledge these contract changes.**
- **Audit #1 (deferred, significant):** F-6 is fixed at the foundation, but
  `ExecutionManager` still sets the side-effect marker before `_finalize`. A
  pre-marker refusal therefore still produces COMMIT_STATUS_UNKNOWN,
  INDETERMINATE capital and a halt, which the reconcile tool refuses to
  resolve. Reachability is low, since the manager's preflight performs
  equivalent checks.
- **Audit #3 (deferred):** MarketLoop's SIZING_REPLAY_CONFLICT still compares
  against RELEASED reservations. A retry whose sizing moved is refused
  cleanly, which is conservative.
- **Audit #5:** an evidence-recovered K3 commits the reservation at the full
  approved amount. This is history only and does not encumber capital.
- Evidence-only recovered BUY results cannot be replayed into a relational
  projection. Storage is not wired today.
- Re-derivation residual: if the audit store lost *both* the
  REQUEST_RECEIVED and the RISK_APPROVED writes of the prepared attempt,
  binding falls back to the prior attempt's approval. This requires two
  consecutive best-effort audit write failures on the same attempt.
- Informational: `_open` does not check the closed archive for a reused
  position_id. A reused legacy id is caught only at reload
  (`FINANCIAL_CLOSED_POSITION_LIVE_CONFLICT`). This is pre-existing.

## Remaining work

- F-4 (deferred) and F-7 (intentional, no change).
- Audit #1: an ExecutionManager classification of pre-marker refusals, or
  COMMIT_STATUS_UNKNOWN recovery. Needs an owner decision.
- Audit #3: MarketLoop RELEASED handling.
- I-5: relocate `memory_data/` outside OneDrive before the Gate-1 run.
- I-4: a stale comment in `core/application.py`.
- A governance registry entry recording this package.
- Owner review, then commit.

## Next exact action

1. Owner reviews the diff and acknowledges the three changed test contracts.
2. Commit the package.
3. Decide audit #1 and I-5 before the Gate-1 run.
