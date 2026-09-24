# ATLAS CHECKPOINT

## Objective

Owner brief (2026-09-24), AUDIT MODE: audit the execution/financial-state
pipeline for correctness under crash-recovery, duplicate-order,
partial-fill, and reconciliation scenarios. Findings only, no fixes. The
owner deferred this audit on 16 Eylül and has now prioritized it ahead of
the FRONTEND package. It also gives a READY / CONDITIONAL / BLOCKED verdict
on trusting an uninterrupted paper run (Gate 1) on top of this pipeline.

Classification: CRITICAL (execution, capital, and migration domains). Tier:
strongest model at maximum effort. No implementation was made, so the
IMPLEMENT→…→FINAL GATE sequence does not apply.

## Completed

- Code audit at HEAD `f5e7250` (branch `research/edge-validation`) of:
  - `core/execution_portfolio_foundation.py`
  - `core/capital_reservation.py`
  - `core/risk_state_store.py`
  - `core/execution_transaction_journal.py`
  - `core/durable_append_log.py`
  - the `ExecutionManager` order lifecycle, which covers `execute`,
    `risk_check` reservation, `_finalize_durable_financial_state`,
    `_mirror_paper_book`, the paper BUY/SELL paths, `_claim_request`,
    `_complete_request`, and `_release_request`
  - `core/paper_trader.py`
  - `tools/reconcile_execution_authorities.py`
  - the contracts of the migration and bootstrap tools
- Behavioral probes, run as disposable scripts and not committed. They ran
  the real `AtlasApplication` in PAPER mode. Each probe used an isolated
  scratch `state_directory` with all three `ATLAS_*_DIRECTORY` variables
  redirected and `ATLAS_LOG_DIRECTORY` unset. No real runtime state was
  touched. `git status` after the probes showed no changes to tracked
  files. The scripts and scratch state were deleted after use.
  - **Crash probes:** a child process ran one BUY and was killed with
    `os._exit(137)` at each commit boundary (K0–K6). A fresh process then
    constructed a runtime on the same state and inspected every authority.
    It also ran `reconcile()` in dry-run mode.
  - **Scenario probes:**
    - E1: transient prepare failure, then the same `request_id` retried.
    - E3: BUY, then a partial reduce-only SELL, then an add.
    - E4: a duplicate `request_id` in-process, across a restart, and at the
      foundation layer.
    - E7: a torn `paper_trades.json`.
    - E8: capacity after an orphan reservation.

### Crash-window matrix (verified by the probes)

| Kill point | Journal | Reservation | Foundation | Paper book | Idempotency | Restart | Reconcile tool |
|---|---|---|---|---|---|---|---|
| K0 after reserve, before `prepare` | none | RESERVED | untouched | empty | none | **starts healthy** | AGREE |
| K1 after `prepare` | PREPARED | RESERVED | untouched | empty | none | halt UNRESOLVED_JOURNAL | refuses JOURNAL_UNRESOLVED |
| K2 after applied-archive append, inside `apply_confirmed` | PREPARED | RESERVED | NOT READY: FINANCIAL_TRANSITION_RECOVERY_REQUIRED | empty | none | halt | refuses |
| K3 after `apply_confirmed`, before reservation commit | PREPARED | RESERVED (cash already debited) | BTC 100, cash 9000 | **empty (diverged)** | none | halt | refuses |
| K4 after reservation commit, before mirror | PREPARED | COMMITTED | BTC 100 | **empty (diverged)** | none | halt | refuses |
| K5 after mirror, before idempotency record | PREPARED | COMMITTED | BTC 100 | BTC 100 | none | halt | refuses |
| K6 after idempotency record, before journal COMMITTED | PREPARED | COMMITTED | BTC 100 | BTC 100 | r1 | halt | refuses |
| no kill (baseline) | COMMITTED | COMMITTED | BTC 100 | BTC 100 | r1 | healthy | AGREE |

The probes found no silent drop and no double-apply of authoritative state
in any window. Every window from K1 to K6 fails closed. No window has a
supported way back.

## Findings (by severity)

### F-1: HIGH. No supported recovery path for an execution interrupted between journal PREPARE and journal COMMITTED

- **Location:**
  - `tools/reconcile_execution_authorities.py:58-60, 314-316`, which refuses
    any unresolved entry.
  - `core/execution_portfolio_foundation.py:166-167`, the transition-marker
    halt.
  - `core/durable_append_log.py:131-134`, the torn-tail refusal. The same
    applies to the applied and closed sidecars' `load_index`.
  - `docs/adr/0005-operator-bootstrap-runbook.md:207`, which says to
    "establish what the interrupted transition did" but gives no procedure.
- **Evidence:** In crash probes K1 to K6, every restart halts with
  `UNRESOLVED_JOURNAL`. K2 also leaves
  `FINANCIAL_TRANSITION_RECOVERY_REQUIRED`. `reconcile()` returns
  `RECONCILIATION_REQUIRED / JOURNAL_UNRESOLVED` in every case. The halt
  applies even when the durable evidence settles the outcome:
  - In K1, the foundation is untouched and has no applied record, so
    provably nothing happened.
  - In K3 to K6, the applied-execution archive holds `idempotency_key == r1`,
    so provably the execution was applied.
- **Impact:** A process kill during an execution window ends a Gate-1 run.
  The window is milliseconds long per trade, but it recurs on every trade.
  The only way out is to hand-edit append-only financial authority files:
  the journal, the sidecars, and the working state. That hand-editing is
  itself a data-integrity risk and has no verification gate.
- **Reasoning:** The fail-closed behavior is correct and must be kept. The
  gap is that recovery is undefined, even though the evidence needed to
  classify each window already exists durably.
- **Remediation (recommendation only):** Build a verify-first recovery path
  that classifies each unresolved entry from the applied archive, the
  reservation state, the idempotency record, and the foundation transition
  marker:
  - Provably not applied: resolve NOT_COMMITTED and release the reservation.
  - Provably applied: resolve COMMITTED and commit the reservation.
  - Anything else: refuse.

  This needs an **owner decision** on what a recovered journal resolution
  may contain. The existing tool's rule is never to fabricate result
  fields, and a PREPARED entry holds no result. It is a CRITICAL package.

### F-2: MEDIUM. A crash between reservation and journal prepare leaves a silent, permanent orphan RESERVED reservation

- **Location:** `core/execution_manager.py:3053` (reserve), with no journal
  entry until `:1336` (prepare). No startup cross-check exists between the
  ledger and the journal.
- **Evidence:**
  - K0: after a restart the runtime is **not halted**, while r1 stays
    RESERVED (1000).
  - E8: `active_reserved=1000`, and `durable_free=9000` against cash 10000.
  - The reconcile tool reports AGREE.
  - Nothing ever releases the reservation. The one exception: a restart
    within the same candle re-derives the same `request_id` and adopts it.
- **Impact:** Admissible capital shrinks silently by each orphaned amount,
  and nothing detects the ledger/journal inconsistency. The direction is
  conservative, so no over-allocation results.
- **Reasoning:** This is inconsistent durable state that is continued
  through silently rather than detected (CLAUDE.md Financial/migration
  safety).
- **Remediation:** At startup, detect any RESERVED reservation with no
  journal entry, or with only a NOT_COMMITTED entry. Report it, or halt on
  it. Offer an operator release path in the same recovery package as F-1.

### F-3: MEDIUM. Retrying a `request_id` after a pre-side-effect failure reuses a RELEASED reservation, turning a transient failure into a halt with a false COMMIT_STATUS_UNKNOWN

- **Location:**
  - `core/capital_reservation.py:342-345`: `reserve()` returns the
    existing record of *any* status when `request_id` and amount match.
  - `core/execution_manager.py:3402-3406`: the finalization refusal.
  - `core/execution_manager.py:1629`: the side-effect marker, set before
    these provably non-mutating checks.
- **Evidence (E1):**
  - Attempt 1 fails with `TRANSACTION_PREPARE_FAILED`. The reservation is
    RELEASED and the runtime keeps running.
  - Attempt 2 uses the same `request_id`. It gets `COMMIT_STATUS_UNKNOWN /
    DURABLE_FINANCIAL_FINALIZATION_FAILED`: the runtime halts, the journal
    shows COMMIT_STATUS_UNKNOWN, and the reservation is still RELEASED
    (RELEASED→INDETERMINATE is illegal).
  - The foundation is **unchanged** (cash 10000, no position).
- **Impact:**
  - Admission was granted with no live encumbrance: the reservation
    invariant is broken for the duration of attempt 2.
  - A transient I/O failure becomes a halt that falls under F-1's
    no-recovery gap.
  - The journal asserts an unknown outcome for an execution that provably
    did not happen.
- **Reachability:** MarketLoop marks a candle processed before it executes
  (`core/market_loop.py:787-791`), so an in-process retry does not happen.
  `last_processed_candles` is held in memory only. A restart within the
  same candle after a transient pre-side-effect failure therefore
  re-derives the same `request_id`. On this OneDrive-hosted state root, a
  file lock is a realistic source of transient I/O failures.
- **Remediation:**
  - `reserve()` should return an existing record only when it is RESERVED.
  - A RELEASED record with the same ID should either be re-armed through
    an explicit, capacity-checked transition or refused before admission.
  - `risk_check` should assert that the returned reservation is RESERVED.
  - Separately, consider moving the side-effect marker after the
    non-mutating checks in `_finalize_durable_financial_state`.

### F-4: LOW. The PaperTrader mirror can silently diverge and lose history, and nothing detects the divergence

- **Location:**
  - `core/paper_trader.py:689-722`: `save()` opens the file with `"w"`, with
    no temp-file-and-replace and no fsync.
  - `core/paper_trader.py:637-685`: `load()` swallows every exception.
  - `core/execution_manager.py:3461-3524`: projection happens only after a
    commit. There is no startup projection.
- **Evidence:**
  - K3 and K4: the foundation holds BTC 100 while the paper book is empty
    after restart.
  - E7: after a torn file, the restart gives `paper_book={}` against
    foundation BTC 100, with no halt and no signal. After the next trade
    the history holds 1 entry, so the prior history is lost.
    `paper_mirror` still reports "OK", because it reflects only that one
    symbol's projection.
- **Impact:** The operator-visible `paper_trades.json` can disagree with the
  authority indefinitely for any symbol that does not trade again.
- **Reasoning for LOW:** Nothing in the active runtime consumes the mirror
  (verified by grep):
  - `apply_projection` is the only call into PaperTrader from active code.
  - `/api/trades` reads the closed-position archive.
  - `core/execution_bridge.py`, which still calls `open_trade`, is imported
    nowhere.
- **Positive:** The dac9b72 design holds. The mirror cannot veto, and E3
  showed that partial reductions project correctly.
- **Remediation:**
  - Run a full projection of every symbol once the foundation is ready at
    startup.
  - Write the file atomically.
  - Report a load failure as DEGRADED rather than as an empty book.

### F-5: LOW. The CAPITAL_RESERVATION_COMMIT_FAILED branch leaks the in-flight claim

- **Location:** `core/execution_manager.py:1704-1730`
- **Evidence (code reading):** The branch sets `request_claimed = False`
  without calling `_release_request()`. This is the same defect class that
  dac9b72 fixed for the finalization-failure branch at `:1654-1659`. The
  branch also skips `_record_result`, `publish`, and audit, unlike its
  sibling branches.
- **Impact:** The request ID stays in `pending_request_ids` until restart,
  so `reset()` refuses with `EXECUTION_REQUESTS_IN_FLIGHT`. The runtime is
  already halted, so there is no financial impact.
- **Remediation:** Mirror the finalization-failure branch.

### F-6: LOW. Validation refusals inside `apply_confirmed` happen after the transition marker is persisted

- **Location:** `core/execution_portfolio_foundation.py:602-615, 650-652`
- **Evidence (code reading):** The marker is saved first. The refusals then
  raise without mutating anything:
  - DUPLICATE_OPEN_POSITION
  - STALE_POSITION_MUTATION
  - INSUFFICIENT_CASH
  - NEGATIVE_AVAILABLE_CAPITAL
  - REDUCTION_EXCEEDS_POSITION
  - CLOSED_POSITION_IDENTITY_CONFLICT
  - LONG_ONLY_ACTION_REJECTED

  The marker stays on disk, so the foundation becomes
  `FINANCIAL_TRANSITION_RECOVERY_REQUIRED` both in-process and on restart.
- **Impact:** A pure refusal requires F-1's missing recovery.
  Reachability is low: the manager's preflight performs equivalent checks,
  and there is a single caller thread.
- **Remediation:** Compute and validate the candidate before persisting the
  marker.

### F-7: LOW. The reservation working set is never compacted at runtime

- **Location:** `CapitalReservationLedger.compact()` has no caller outside
  tests (verified by grep).
- **Evidence and impact:** COMMITTED reservations accumulate in
  `capital_reservations.json`. Every reserve or commit rewrites the whole
  file, which is O(n) per trade. Correctness is unaffected, because
  COMMITTED does not encumber capital.
- **Remediation:** This needs an owner decision on the compaction trigger.
  Whether the omission is intended is UNKNOWN.

### INFORMATIONAL

- **I-1: No order-level partial-fill model exists.**
  - Paper fills are synchronous and all-or-nothing. No resting order and
    no remaining unfilled quantity exist anywhere.
  - `live_execute` has no fill model.
  - Partial *reduction* was verified consistent across all three views
    (E3). Foundation and mirror both went from 100/1000 v1 to 60/600 v2.
    SELL takes no reservation. The BUY reservation was COMMITTED at the
    settled amount.
  - A partial-fill design is required before Small Live. Live behavior is
    UNKNOWN.
- **I-2: Duplicate-order protection was verified (E4).**
  - In-process: `DUPLICATE_REQUEST_COMPLETED` with the same `execution_id`.
  - Across a restart: the idempotency store hydrates it.
  - At the foundation layer: a re-apply with a new `execution_id` is
    refused with `IDEMPOTENCY_IDENTITY_CONFLICT` before the marker is
    written, and the foundation stays ready.
  - The paper path has no retry-after-timeout. The same intent under a
    different `request_id` (the next candle) is a new order by design.
- **I-3: Serialization rests on a single caller.** `apply_confirmed` and the
  foundation hold no lock. Safety depends on `market_loop.py:1506` being the
  single `execute()` caller, on one thread. That holds today. It is not a
  defect.
- **I-4: Stale comment.** `core/application.py:559-563` still says the
  paper book "is a durable execution side effect … an interrupted
  execution is classified against it". That has been false since dac9b72.
- **I-5: Standing decision.** The standing owner decision requires moving
  `memory_data/` outside OneDrive before any sustained or unattended paper
  run. It is a Gate-1 precondition and bears directly on F-3's transient
  I/O trigger.
- **Migration and bootstrap tooling:**
  - The resume contract of `migrate_execution_financial_state.py` is sound
    at the contract level: prefix-validated resume, a post-append
    verification gate, and v1 left authoritative until the final rewrite.
    H-1 is settled and was not re-verified.
  - `bootstrap_financial_state` creates or validates each store
    independently, so it is resumable by construction.
  - `migrate_execution_authority_logs` writes atomically and then renames
    legacy files. It is settled by its production run.
  - A torn trailing line in any sidecar or log refuses closed and needs
    manual truncation, which falls under F-1.
  - No new findings.

## Overall verdict

**CONDITIONAL.** Every probed crash window fails closed. No authoritative
state is silently dropped, duplicated, or double-applied. Duplicate
submissions are rejected at three layers. Partial reductions reconcile
across the foundation, the ledger, and the mirror. State produced by an
**uninterrupted** paper run can therefore be trusted. The conditions:

1. **F-1 (HIGH):** Any interruption inside an execution window ends the
   run and has no supported recovery. Gate 1 must not be *closed* while
   F-1 is open.
2. **I-5:** Relocate execution state outside OneDrive before the run.
3. **F-2 and F-3:** Close them in the same package. They are the two
   remaining ways the durable authorities can disagree.

## Files changed

- `checkpoints/20260924T195526Z_execution-financial-state-reconciliation-audit.md`
  (this file, new, uncommitted). No code, test, or config file was changed.

## Architecture decisions

None made. Two decisions are required from the owner:

- F-1: what a recovered journal resolution may contain.
- F-7: whether runtime compaction is intended.

## Tests

No test suite was run, because no production code changed. The baseline
stays at 3906 passed and 1 failed (the known Group B2 failure, per the
brief). The probes' evidence is recorded above. The probes were disposable
and not committed.

## Current state

HEAD is `f5e7250`, and the working tree is unchanged apart from untracked
checkpoints. `checkpoints/20260924T195331Z_venue-freshness-and-agent-exclusion-investigation.md`
appeared during this session. This audit did not create it, and it was left
untouched.

## Known issues / risks

The findings above. UNKNOWN items:

- Live partial-fill behavior (I-1): no live fill model exists.
- Whether F-7 is deliberate.
- The migration tools' crash-resume behavior under a real kill: not
  re-exercised this session, relying on settled evidence.

## Remaining work

A CRITICAL implementation package for F-1 (with F-6 as its cheap
root-cause reducer), F-2, F-3, and F-5. F-4 and F-7 are recorded as
deferred LOW items.

## Next exact action

Owner decides the F-1 recovery-resolution contract. Then open the CRITICAL
package "execution-authority crash recovery" covering F-1, F-2, F-3, F-5,
and F-6, with kill-point regression tests K0–K6 and E1 as the discriminating
tests. Model tier: strongest, maximum effort. Start it from a fresh context
(`/clear`).
