# Atlas Block 5 / Package 5F Freeze Evidence

## Status

Package 5F closure candidate: PASS
BLOCKING: 0
HIGH: 0
MEDIUM NEW: 0

User approval required before staging/commit. As of this writing, nothing in
Package 5F's file list — including this document — is staged or committed.

## Package

Block 5 / Package 5F — Reservation Capital Reclamation
(`core/capital_reservation.py`).

## Objective

Package 5E left one BLOCKING item on record: a COMMITTED reservation
permanently encumbered `CapitalReservationLedger.available`, because the
capital it settled was never given back. 5E's own remediation (F7) narrowed
*how much* stayed encumbered — committing at `notional + fee` instead of the
full reservation — but explicitly did not address the encumbrance itself
continuing forever.

5F closes that item by correcting the ledger's definition of live
encumbrance, per the owner's ruling: **COMMITTED is durable historical
evidence, not live encumbrance.** No reservation/position linkage and no
`COMMITTED -> RELEASED` transition were added to reach this — the fix is
entirely a corrected formula.

## Root Cause

`CapitalReservationLedger` computed two supposedly-equivalent measures of
"capital currently spoken for" from two independently maintained formulas:

- `_encumbered` (private, backing both `available` and the `__init__`
  over-allocation guard) summed **RESERVED + COMMITTED + INDETERMINATE**.
- `active_reserved_capital` (the formula `ExecutionManager` actually reads
  for every admission decision) summed **RESERVED + INDETERMINATE** only.

`active_reserved_capital` was already correct — `ExecutionManager` never
called `.available` directly (confirmed: `core/execution_manager.py` has no
call site for it), so no admission decision was ever affected by this
defect. But `CapitalReservationLedger.available` itself — and every direct
caller of it, including several existing tests — silently double-counted a
COMMITTED reservation's settled amount: once for real, as a debit against
`cash` in `ExecutionPortfolioFoundation` at the moment of settlement, and a
second time, forever, as encumbrance in this ledger. Nothing ever reversed
the second count: not a later SELL (no reservation/position linkage exists
to reverse it through), not a restart (the encumbrance is recomputed from
persisted status on every load, and COMMITTED is permanent), nothing.

## Old vs New Live-Encumbrance Semantics

| | Old (pre-5F) | New (5F) |
|---|---|---|
| `_encumbered` statuses | RESERVED, COMMITTED, INDETERMINATE | *(removed — replaced by `_live_encumbered`)* |
| `_live_encumbered` statuses | *(did not exist)* | RESERVED, INDETERMINATE |
| `available` | `total_allocatable - _encumbered(items)` | `total_allocatable - _live_encumbered(items)` |
| `active_reserved_capital` | its own inline RESERVED+INDETERMINATE sum | `_live_encumbered(items, exclude=...)` — same helper as `available` |
| `available == total_allocatable - active_reserved_capital()` | **false** whenever any COMMITTED reservation existed | **true**, always (single shared formula) |

COMMITTED and RELEASED reservations are unaffected in every other respect:
they remain persisted, queryable via `get()`, exact at their settled/reserved
amount, and idempotent. `ReservationStatus` gained no new member; the
`_transition` allowed-pairs set (RESERVED->RELEASED, RESERVED->INDETERMINATE)
is unchanged, so COMMITTED still never transitions to RELEASED and
INDETERMINATE still never transitions anywhere. No code anywhere links a
reservation to a position; a partial or full SELL touches only
`ExecutionPortfolioFoundation` and never reads or writes the reservation
ledger.

## F1 / F2

**F1 (BLOCKING, CLOSED).** The structural defect above:
`CapitalReservationLedger` counted COMMITTED as live encumbrance.
Fixed by `_live_encumbered` (`core/capital_reservation.py`), the single
formula `available` and `active_reserved_capital` both now compute from.

**F2 (HIGH, CLOSED as a consequence of F1 — no separate change).** The
operational symptom F1 produced: `available` decayed monotonically with
completed turnover regardless of real durable cash, and given enough
completed trades would refuse a `reserve()` call for a brand-new,
fully-collateralized BUY even though every prior position had already fully
exited. Closed automatically by F1's single formula correction — proven by
`test_repeated_buy_full_sell_cycles_do_not_decay_available_capital`, which
runs 12 clean BUY -> full-SELL cycles at 1000/100/96 (one cycle past the
point the old formula would have refused the 11th reservation outright) and
shows `available` never leaves 1000.

## Concrete Numbers (`test_partial_and_full_sell_leave_committed_reservation_untouched_across_restarts`)

Ledger `total_allocatable = 1000`, foundation `cash = 1000`, both isolated to
`tmp_path`.

| Stage | Reservation | `ledger.available` | `active_reserved_capital()` | Durable cash |
|---|---|---|---|---|
| Reserve (approved 100) | RESERVED 100 | 900 (mid-flight, not asserted as a checkpoint) | 100 | 1000 |
| BUY settles (notional 95 + fee 1) | **COMMITTED 96** | **1000** | 0 | 904 |
| Partial SELL (5 of 10 @ 12, fee 0.5) | COMMITTED 96 (untouched) | **1000** | 0 | 963.5 |
| Full SELL (remaining 5 @ 11, fee 0.4) | COMMITTED 96 (untouched) | **1000** | 0 | 1018.1 |

Every one of the four rows above was re-verified against a freshly
reloaded `CapitalReservationLedger`/`ExecutionPortfolioFoundation` pair
(restart/replay) at three checkpoints — after the BUY, after the partial
SELL, and after the full SELL — and matched exactly. Final durable cash
(1018.1) equals `1000 + realized_gross_pnl(20) - fees(1.9)` exactly,
independent of the reservation ledger, which the SELL side of this scenario
never touches again after the BUY committed.

## Proof Summary

| Letter | Claim | Test(s) |
|---|---|---|
| A | BUY settlement reclaims capital at settled amount, direct and full-pipeline | `test_buy_settlement_reclaims_reservation_capital_at_settled_amount`, `test_real_execute_buy_reclaims_reservation_capital_through_full_pipeline` |
| B/C/D | Partial/full SELL never mutate COMMITTED history; restart survives BUY, partial SELL, full SELL | `test_partial_and_full_sell_leave_committed_reservation_untouched_across_restarts` |
| E | Repeated turnover: `available` never decays; every valid BUY continues to admit | `test_repeated_buy_full_sell_cycles_do_not_decay_available_capital` |
| F | INDETERMINATE still encumbers, still recovery-blocking, still cannot reach RELEASED, real runtime still halts | `test_indeterminate_reservation_still_encumbers_and_cannot_release_or_commit`, `test_indeterminate_from_a_real_interrupted_execution_halts_and_still_encumbers` |
| G | `total_allocatable` still prevents concurrent double-spend | `test_concurrent_reservations_still_prevent_double_spend` |
| H | `available == total_allocatable - active_reserved_capital()` across RESERVED+COMMITTED+RELEASED+INDETERMINATE simultaneously | `test_available_equals_allocatable_minus_active_across_every_status` |
| I | N COMMITTED records remain queryable and exact after restart | `test_reservation_history_survives_n_round_trips_and_restart` |

All nine tests live in `tests/test_block5f_reservation_capital_reclamation.py`
and construct real `CapitalReservationLedger`/`JsonReservationStore`/
`ExecutionPortfolioFoundation`/`FinancialStateStore` instances (two tests
also drive the real `AtlasApplication`/`ExecutionManager.execute()`
pipeline), never mocks of the classes under test, all rooted at pytest's
`tmp_path`.

## Source Revision

Branch: `feat/block3-execution-safety`

Parent HEAD: `fc69e97b7af8877a1ad098360b277f05d85ddfd6` —
`feat: close fee settlement accounting contract`

## Frozen Decisions (owner rulings, applied verbatim)

- COMMITTED is durable historical evidence, not live encumbrance.
- Live encumbrance = RESERVED + INDETERMINATE only.
- No new reservation states — `ReservationStatus` is unchanged.
- No COMMITTED -> RELEASED transition — `_transition`'s allowed-pairs set is
  unchanged.
- No reservation <-> position linkage — confirmed: nothing in
  `core/capital_reservation.py` references a position, and nothing in
  `core/execution_portfolio_foundation.py` references a reservation.
- Partial/full SELL do not mutate COMMITTED reservation history — proven by
  B/C/D above.
- `total_allocatable` remains the static `risk_policy.allocatable_capital` —
  unchanged; `CapitalReservationLedger.__init__` still takes it as a fixed
  constructor argument.
- INDETERMINATE remains fully encumbering and recovery-blocking — proven by
  F above.
- The two 5E `ledger.available` assertions that pinned the old defect were
  amended, not deleted or weakened elsewhere.

## 5B / 5C / 5D / 5E Authority Continuity

`git diff --stat -- core/` shows exactly one changed file:
`core/capital_reservation.py` (56 insertions, 23 deletions). Every other
core production file — `core/risk_engine.py` (5B), `core/position_sizing.py`
(5C), `core/instrument_rules.py` (5D), `core/fee_accounting.py`,
`core/execution_manager.py`, `core/execution_models.py`,
`core/execution_portfolio_foundation.py` (5E) — carries zero diff.

`core/execution_manager.py` was read, not edited: its only reservation-ledger
capacity read is `active_reserved_capital` (`_admitted_quote_allocation`,
`_finalize_durable_financial_state`), which already excluded COMMITTED
before this package and is behaviorally unchanged by it. No test revealed a
regression requiring an ExecutionManager change, so the scope guard against
touching it was honored with no exception needed.

## Known Non-Blocking Follow-ups / Limitations

**F3 — closed-position overwrite (accepted, open, deferred; CLOSED by
Block 5G).**
`ExecutionPortfolioFoundation._close`'s full-exit branch wrote
`state["closed_positions"][result.position_id] = closed`, keyed only by
`position_id`. A position id reused after a full close (the same symbol
traded again) silently overwrote the prior closed record; nothing
compacted or archived closed-position history.
`test_repeated_buy_full_sell_cycles_do_not_decay_available_capital`
triggered this overwrite on every one of its 12 cycles by construction and
deliberately asserted nothing about `closed_positions` for that reason. Out
of scope for 5F by explicit owner instruction.

Closed by Block 5G (`docs/evidence/block5g_freeze_evidence.md`):
`ExecutionManager` now mints a deterministic
`long:<symbol>:<sha256(request_id).hexdigest()>` identity once per lifetime
instead of reusing a bare `long:<symbol>` constant across every re-entry,
and `ExecutionPortfolioFoundation._close` fails closed with
`CLOSED_POSITION_IDENTITY_CONFLICT` rather than silently overwriting if a
collision is ever produced. Hashing the opening `request_id` rather than
embedding it raw also closes 5G-3, the dormant `data_layer` relational
projection layer's `PRIMARY KEY` incompatibility, unconditionally. The
turnover test above now
gives each simulated lifetime its own id for this reason, rather than
reproducing the old collision.

**F4 — reservation-store growth (accepted, open, deferred).**
`CapitalReservationLedger` never removes a COMMITTED or RELEASED reservation
from `_items`; `JsonReservationStore`'s persisted file grows by one entry
per reservation for the runtime's lifetime, with no compaction or archival.
Out of scope for 5F by explicit owner instruction.

**F5 — `applied_executions` growth (accepted, open, deferred).**
`ExecutionPortfolioFoundation`'s idempotency map grows by one entry per
fill forever, for the same reason: no pruning or archival exists. Out of
scope for 5F by explicit owner instruction.

None of F3/F4/F5 is fixed, worsened, or newly discovered by this package —
all three were identified during 5F's own investigation and are recorded
here for the first time as explicitly deferred, not carried forward from an
earlier package's evidence.

No BLOCKING, HIGH, or MEDIUM finding is newly introduced by this package.

## PAPER / LIVE

Unchanged. PAPER remains the default and LIVE authority remains denied.
5F is a pure accounting-formula correction inside `CapitalReservationLedger`
and touches no execution-mode or venue-adapter path.

## Push Status

NOT PUSHED. NOT STAGED. NOT COMMITTED. `git status --short` at capture time:

```
 M core/capital_reservation.py
 M tests/test_block5e_fee_settlement_accounting.py
?? tests/test_block5f_reservation_capital_reclamation.py
```

## Validation Evidence

All commands ran against the working tree in this session with an isolated,
ASCII `--basetemp` outside the repository (this host's default tmp-path root
is broken for pytest under the `HUAWEİ` profile directory), per this
project's standing testing convention. Every fixture in
`tests/test_block5f_reservation_capital_reclamation.py` seeds into
`tmp_path`; no command wrote to the operator's real runtime state
(`memory_data/`, root-level `paper_trades.json`) or touched git beyond the
working tree.

**Package 5F focused suite:** 9 passed in 1.07s.
`python -m pytest tests/test_block5f_reservation_capital_reclamation.py -q --basetemp=<isolated>`

**Reservation/atomicity + bootstrap-validation regression:** 91 passed in 1.43s.
`python -m pytest tests/test_block2_m1_reservation_admission_atomicity.py tests/test_phase3_risk_capital_foundation.py tests/test_block3_bootstrap_state_validation.py tests/test_block3_bootstrap_policy_consistency.py tests/test_block2c_financial_state_bootstrap.py -q --basetemp=<isolated>`

**Amended Package 5E suite:** 29 passed in 1.32s.
`python -m pytest tests/test_block5e_fee_settlement_accounting.py -q --basetemp=<isolated>`

**INDETERMINATE exception/recovery regression (Block 3):** 43 passed in 3.31s.
`python -m pytest tests/test_block3_execution_exception_atomicity.py -q --basetemp=<isolated>`

**Package 5B + 5C reservation/capital-semantics regression:** 171 passed in 5.12s.
`python -m pytest tests/test_block5b_single_sizing_authority.py tests/test_block5c_upstream_sizing_authority.py -q --basetemp=<isolated>`

Architecture suite not re-run: no composition-root, import-layer, or wiring
file changed (`git diff --stat -- core/` touches only
`core/capital_reservation.py`, and its import set is unchanged), so no
architecture-relevant file was in scope for this package.

**Full `tests/` suite (once, after all remediation complete):** 2186 passed
in 75.99s.
`python -m pytest tests/ -q --basetemp=<isolated>`

2186 = 2177 (5E's full-suite count) + 9 (this package's new focused suite),
consistent with zero tests removed or newly failing elsewhere.

## Exact Intended Package 5F File List

Total: **5 files** — 1 core production, 1 test amended, 1 test new,
2 evidence (1 new, 1 amended).

Core production (1):
- `core/capital_reservation.py`

Tests (2):
- `tests/test_block5e_fee_settlement_accounting.py` (amended: two
  `ledger.available` assertions, one stale scope-note paragraph)
- `tests/test_block5f_reservation_capital_reclamation.py` (new)

Evidence (2):
- `docs/evidence/block5f_freeze_evidence.md` (new, this document)
- `docs/evidence/block5e_freeze_evidence.md` (amended: the carried-forward
  COMMITTED-reservation-lifecycle blocker note now points to this package
  as CLOSED)

No unrelated or generated file is in scope for this package. `git status
--short` at capture time contains no entry outside this list.

## Limits of This Evidence

This package corrects one ledger-internal formula and proves the corrected
contract through both direct construction and the full production pipeline.
It does not address, and makes no claim about, F3/F4/F5 above, any
Decimal/float finding unrelated to live-encumbrance semantics, or any
change to `ExecutionManager`, `RiskEngine`, `PositionSizingService`,
`MarketLoop`, `InstrumentRules`, or `FeeNormalizer` — none of which this
package touched. The reservation ledger and the portfolio foundation remain
two independent systems correlated only by the caller that happens to drive
both from the same settled amount at BUY time; this package neither adds
nor removes that independence.
