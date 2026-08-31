# Atlas Block 5 / Package 5B Freeze Evidence

## Status

Package 5B closure candidate: PASS
BLOCKING: 0
HIGH: 0
MEDIUM: 0

User approval required before staging/commit. As of this writing, nothing in
Package 5B — including this document — has been staged or committed.

## Package

Block 5 / Package 5B — Financial Precision / Single Sizing Authority.

## Objective

Package 5B establishes one canonical, exact-`Decimal` allocation authority
for execution, carried unchanged from `RiskEngine` approval through capital
reservation to durable settlement; makes the BUY quantity/notional identity
exact for real (non-terminating) prices; replaces deferred partial-SELL
rejection with an exact pro-rata reduction; and closes a re-evaluation defect
in the durable-capital admission check. Package 5A (already committed,
`5e84c02`) made the canonical `RiskEngine` reachable from the real runtime
and left three defects (A, B, C) and this package's own review findings
(F1, F2, M1) as the open work Package 5B closes.

## Source Revision

Branch: `feat/block3-execution-safety`

Parent HEAD (Package 5A, already committed):
`5e84c02d21083e981c8e870578d6241fea64cfce` —
`feat(5a): derive canonical RiskState and reduce-only intent from durable state`

Package 5B commit: **not yet made.** Unlike the Block-3 and Block-4
freeze-evidence documents, which were written after their code was already
committed and which anchor a specific already-frozen `Source HEAD`, this
document is deliberately being prepared *before* Package 5B is staged, at
explicit instruction. It records the working-tree state and the evidence
produced in this session, not a tagged or already-committed revision.

Worktree at evidence-capture time: **not clean.** The Package 5B production
and test files listed below are modified or untracked in the working tree.
Four pre-existing `reports/phase3_architecture_audit/*` files are also
modified but are unrelated generated-audit churn, out of scope for Package
5B, and excluded from its file list and from staging.

Staged: nothing. `git diff --cached --stat` is empty.

## Frozen Decisions

- `ExecutionRequest.approved_quote_allocation` is the canonical `Decimal`
  allocation authority.
- `ExecutionRequest.amount` is compatibility-only and is not authoritative.
- Execution/risk paths do not auto-size an unsized BUY request; an unsized
  new-risk BUY is refused as `UNSIZED_REQUEST_REJECTED` rather than sized to
  a policy ceiling.
- `risk_check` is the sole approval/admission authority for the canonical
  allocation. Nothing downstream — including `CapitalManager` — may resize or
  veto a canonical `RISK_APPROVED` decision.

## Precision Contract

- The `Decimal` allocation remains exact from admission through settlement;
  no leg of the path round-trips it through `float`.
- BUY sizing is quantity-first: the base quantity is derived from the
  approval and the notional is derived from that quantity, never the
  reverse.
- `execution_price * filled_base_quantity == filled_quote_notional` exactly,
  under the declared arithmetic contract, including for prices that do not
  divide the allocation evenly (e.g. `1.29`, `43219.87654321`).
- `filled_quote_notional + fee_amount <= approved_quote_allocation` always;
  settlement never exceeds what was approved.
- `BASE_QUANTITY_QUANTUM = Decimal("0.00000001")` (1e-8) is explicitly a
  representation-precision assumption for this runtime, **not** a venue or
  instrument lot size, step size, or minimum-quantity contract.
- A future per-instrument step-size/minimum-quantity contract must replace
  this constant at both of its call sites at the same time: the
  pre-reservation feasibility bound in `risk_check` and the fee-inclusive
  bound in `_resolve_base_fill`.

## Risk / Admission Guarantees

- A sub-quantum BUY (an approval too small to buy one whole base quantum) is
  rejected in `risk_check`, before any capital reservation or side effect —
  never discovered later inside `_resolve_base_fill`, past the side-effect
  boundary (F1).
- A repeated `risk_check` on the same BUY request excludes only that
  request's own existing reservation from its own durable-capital funding
  measurement. Every other request's reservation still encumbers capital in
  full; no request may hold two reservations (M1).
- A repeated `risk_check` on the same SELL request remains idempotent: the
  resolved exposure is never written back onto `request.amount`, so a
  second evaluation re-resolves durable exposure rather than reading its own
  rounded mirror (F2).
- No double reservation: `CapitalReservationLedger.reserve` returns the
  identical existing entry for a repeated `(reservation_id, request_id,
  amount)` rather than creating a second one.
- No stale approval may authorize execution: `risk_check` clears
  `request.approved_quote_allocation` to `None` at the start of every
  evaluation, before any gate runs, so a refusal can never leave a prior
  approval readable as live authority.
- An unsized BUY remains fail-closed as `UNSIZED_REQUEST_REJECTED`, refused
  before the engine and before any reservation.

## SELL / Portfolio Behavior

- Partial reduction is supported: `ExecutionPortfolioFoundation._close` now
  records the base quantity actually sold and releases cost basis pro rata,
  instead of refusing every non-full reduction as `PARTIAL_CLOSE_DEFERRED`.
- A full close uses the exact durable base quantity held; selling more than
  is held is refused as `REDUCTION_EXCEEDS_POSITION`.
- A full close leaves no position dust under the tested contract: the
  remaining position is either closed outright (whole exit) or reduced to an
  exact remainder that itself closes with no residual base quantity on a
  subsequent full exit.

## Review History

### Initial independent review

**F1 — HIGH.** The sub-quantum BUY feasibility check ran only inside
`_resolve_base_fill`, past `_mark_execution_side_effect` and past
`_paper_open_trade` — after the side-effect boundary. A single well-formed
sub-quantum decision could therefore reserve capital, open a paper position
the durable book never received, fail, and be classified as a
post-side-effect interruption: INDETERMINATE capital, an unresolved journal
entry, and a halted runtime awaiting operator recovery.
**Remediated:** the same bound is now enforced in `risk_check`, before any
reservation or side effect, and refused as `ALLOCATION_BELOW_EXECUTABLE_QUANTUM`.

**F2 — MEDIUM.** `risk_check` wrote `float(requested)` back onto
`request.amount` for a resolved SELL exposure. A second evaluation of the
same request object then read its own rounded `float` mirror as an explicit
allocation instead of re-resolving durable exposure; because the mirror
could round *up*, the second call could refuse a legitimate full exit as
`INVALID_RISK_REDUCTION` — a position trapped by its own prior admission.
**Remediated:** the resolved exposure is never written back onto `amount`;
the canonical `Decimal` is published only on `approved_quote_allocation`,
and `amount` stays exactly the caller's own input.

Both are evidenced by their own named regression tests in
`tests/test_block5b_single_sizing_authority.py`, currently passing:
`test_sub_quantum_buy_is_refused_at_admission`,
`test_sub_quantum_buy_through_execute_refuses_without_halting`,
`test_sub_quantum_buy_leaves_no_journal_entry`,
`test_risk_check_is_idempotent_for_an_unsized_exit`,
`test_risk_check_never_synthesizes_the_amount_mirror`,
`test_a_float_rounded_mirror_cannot_trap_an_exit`, and (added this session)
`test_f1_sub_quantum_refusal_stays_pre_reservation_under_re_evaluation`,
`test_f2_repeated_sell_risk_check_remains_idempotent`.

### Follow-up finding

**M1 — MEDIUM.** The durable-capital admission check in `risk_check`
measured free capital as `cash - active_reserved_capital()`, which counts
*every* RESERVED/INDETERMINATE reservation — including the current
request's own, if it had already been approved once. Re-evaluating the same
BUY request near the durable bound therefore refused it as
`INSUFFICIENT_DURABLE_CAPITAL`, charging the request for capital it already
held. Reproduced: cash 1000, request 600 — first `risk_check` approved,
second `risk_check` on the same object refused, because free capital was
computed as `1000 - 600 = 400 < 600`.
**Remediated this session:** `_durable_free_quote_capital` now accepts an
`exclude` parameter, and `risk_check` calls it with `exclude=request.request_id`
for the BUY funding measurement. Only the request's own reservation is
excluded, and only from its own admission check. No parallel reservation
mechanism was introduced; no reservation is released and recreated to
manufacture idempotency; `CapitalReservationLedger.available` — which
excludes nothing — remains the bound on what may actually be reserved; and
no other request's reservation accounting is touched.

Evidenced by 9 new tests added this session in
`tests/test_block5b_single_sizing_authority.py` §2b ("M1: a request's own
reservation must not defund its re-evaluation"), including
`test_near_bound_buy_re_evaluation_keeps_its_approval`,
`test_re_evaluated_buy_reserves_its_allocation_exactly_once`,
`test_another_request_still_sees_the_first_reservation`, and
`test_a_request_beyond_remaining_durable_capital_is_still_refused`.

### Final known findings

BLOCKING: 0
HIGH: 0
MEDIUM: 0

## Validation Evidence

**Package 5B focused suite:** 90 passed.
`python -m pytest tests/test_block5b_single_sizing_authority.py --basetemp=C:/Users/HUAWE~1/AppData/Local/Temp/claude/atlas5b -q -p no:cacheprovider`

**Related reservation/risk/execution suites:** 318 passed.
`python -m pytest tests/test_block2_m1_reservation_admission_atomicity.py tests/test_block3_execution_exception_atomicity.py tests/test_block5a_risk_state_plumbing.py tests/test_financial_quantity_identity_contract.py tests/test_phase4_execution_manager_runtime_cutover.py tests/test_phase4_execution_position_portfolio_foundation.py tests/test_phase3_risk_capital_foundation.py tests/test_block2_risk_service_composition_wiring.py tests/test_durable_transaction_state.py tests/test_nbf4_unsupported_risk_fail_closed.py --basetemp=C:/Users/HUAWE~1/AppData/Local/Temp/claude/atlas5badj -q -p no:cacheprovider`

**Full `tests/` suite:** 2030 passed in 44.20s.
`python -m pytest tests/ --basetemp=C:/Users/HUAWE~1/AppData/Local/Temp/claude/atlasfull -q -p no:cacheprovider`

**`core/risk_engine.py`:** unchanged. `git diff --stat -- core/risk_engine.py`
produced no output in this session.

**Staging state at capture time:** nothing staged or committed
(`git diff --cached --stat` empty; see Source Revision above).

All commands were run against the working tree in this session with an
isolated, ASCII `--basetemp` outside the repository (this host's default
tmp-path root is broken for pytest).

## Known Non-Blocking Follow-ups / Limitations

- **No upstream sizing authority yet.** Nothing between `DecisionAdapter`
  and `risk_check` sizes a decision, so a genuine `MarketLoop` BUY still
  reaches `risk_check` unsized and is refused by design as
  `UNSIZED_REQUEST_REJECTED` — this is the documented refusal, not a defect.
  See `tests/test_block5a_risk_state_plumbing.py::test_market_loop_unsized_buy_fails_closed_under_5b`
  and `tests/test_block5b_single_sizing_authority.py::test_real_market_loop_buy_fails_closed_because_it_is_unsized`.
  No real MarketLoop BUY can execute until a sizing authority is added
  upstream; that is out of scope for 5B.
- **`BASE_QUANTITY_QUANTUM` is not venue precision.** It is this runtime's
  own representation bound (1e-8), not a per-instrument exchange step size
  or minimum quantity. See Precision Contract above.
- **No pre-admission fee model.** `ExecutionRequest` carries no fee input;
  the fee is known only when the executing component reports it at fill
  time. The fee-inclusive form of the executable-quantum bound
  (`approved - fee`) is therefore necessarily checked in
  `_resolve_base_fill`, not at admission.
- **Generated audit churn is unrelated.** The modified
  `reports/phase3_architecture_audit/*` files visible in `git status` were
  not produced by Package 5B's work, are out of its scope, and are excluded
  from its file list and from staging.

### Independent review — LOW / observation findings (F3–F9)

Carried forward from the same independent review that produced F1 and F2.
Recorded verbatim as supplied for this correction; not independently
re-derived or re-verified in this session. These are **known non-blocking
follow-ups** and are **not claimed resolved by Package 5B** — this
package's remediation scope was F1, F2, and M1 only (see Review History
above); the "Final known findings: BLOCKING 0 / HIGH 0 / MEDIUM 0" line
there is scoped to that remediation, not to this backlog.

**F3 — LOW.** Partial SELL can mark the side-effect boundary even when
`_paper_close_trade` is skipped and no external side effect occurred.

**F4 — LOW/MEDIUM, non-blocking.** A component-reported fee without a
declared currency fails during durable financial finalization, after the
side-effect boundary. It is not reachable today because `PaperTrader`
reports no fee, but must be revisited when a fee-charging component is
introduced.

**F5 — LOW.** BUY `quote = price * base` depends on the ambient `Decimal`
context outside the explicit `localcontext` used for division. Current
tested/runtime inputs do not make this a blocking defect, but arithmetic
context should eventually be made explicit.

**F6 — LOW.** Unsized-request rejection occurs before risk-engine
evaluation and therefore can mask `CRITICAL_RISK_NOT_EXECUTABLE` /
unsupported-risk verdicts in the audit trail for unsized requests. It
remains fail-closed.

**F7 — LOW.** Reservation accounting commits the approved allocation while
durable settlement spends notional + fee, leaving a deterministic
sub-quantum remainder encumbered. The broader committed-reservation
lifecycle/unwind issue is outside Package 5B.

**F8 — LOW.** `entry_fees` are not released pro rata during partial
position reduction. Currently cosmetic because `entry_fees` are not
consumed by net-P&L logic, but this must be resolved before such a
consumer is introduced.

**F9 — observation.** `approved_quote_allocation` is exact `Decimal`
end-to-end, but price, fee, and the caller-supplied compatibility `amount`
may still originate from `float` values via `Decimal(str(...))`. Do not
overstate the 5B exactness claim beyond the canonical allocation contract
itself.

## PAPER / LIVE

Unchanged by this package. PAPER remains the default and LIVE authority
remains denied. Package 5B changed how a request is sized, approved,
reserved, and reduced; it did not modify `core/risk_engine.py`, the PAPER
default, LIVE denial, or any live-execution adapter path.

## Push Status

NOT PUSHED. No push, no merge, and — as of this document — no commit exists
for Package 5B. Nothing beyond the file list below has been touched by this
package's work.

## Exact Intended Package 5B File List

Total: **11 files** — 3 production, 7 tests, 1 evidence document.

Production (3):
- `core/execution_manager.py`
- `core/execution_models.py`
- `core/execution_portfolio_foundation.py`

Tests (7):
- `tests/test_block5b_single_sizing_authority.py` (new)
- `tests/test_block2_m1_reservation_admission_atomicity.py`
- `tests/test_block3_execution_exception_atomicity.py`
- `tests/test_block5a_risk_state_plumbing.py`
- `tests/test_financial_quantity_identity_contract.py`
- `tests/test_phase4_execution_manager_runtime_cutover.py`
- `tests/test_phase4_execution_position_portfolio_foundation.py`

Evidence (1, this document):
- `docs/evidence/block5b_freeze_evidence.md` (new)

**Explicitly excluded** (pre-existing, generated, unrelated — left modified
in the working tree, not staged):
- `reports/phase3_architecture_audit/architecture_summary.json`
- `reports/phase3_architecture_audit/duplicate_class_names.csv`
- `reports/phase3_architecture_audit/exact_duplicate_files.csv`
- `reports/phase3_architecture_audit/file_inventory.csv`

## Limits of This Evidence

Package 5B establishes a single canonical `Decimal` sizing/admission
authority for BUY and SELL execution, an exact BUY quantity/notional
identity, pro-rata partial SELL reduction, and an idempotent durable-capital
admission check under request re-evaluation. It does not establish, and this
document does not claim: an upstream sizing authority for real `MarketLoop`
decisions, venue-accurate lot-size/step-size/minimum-quantity enforcement, a
fee model available at admission, any change to `core/risk_engine.py`'s own
semantics, LIVE readiness, or production exchange integration. This document
also does not claim a committed or tagged revision: it is a closure
candidate awaiting explicit user approval to stage and commit.
