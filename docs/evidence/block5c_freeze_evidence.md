# Atlas Block 5 / Package 5C Freeze Evidence

## Status

Package 5C closure candidate: PASS
BLOCKING: 0
HIGH: 0
MEDIUM: 0

User approval required before staging/commit. As of this writing, only two
of the files in Package 5C's intended file list are staged (see Source
Revision). Nothing in Package 5C — including this document — has been
committed.

## Package

Block 5 / Package 5C — Upstream Sizing Authority.

## Objective

Package 5B (already committed, `923a9a2`) established a single canonical
`Decimal` admission/settlement authority but deliberately sized nothing: an
unsized BUY refused as `UNSIZED_REQUEST_REJECTED`, and 5B's own evidence
recorded this as an open limitation — "No real MarketLoop BUY can execute
until a sizing authority is added upstream; that is out of scope for 5B."
Package 5C closes that gap. It adds exactly one upstream proposer,
`PositionSizingService` (`core/position_sizing.py`), wires it into
`AtlasApplication` and `MarketLoop`, and establishes: a durable-free-capital
sizing basis; an exact pre-admission `Decimal` transport for the proposal
that never crosses the lossy `amount: float` compatibility mirror; a single
shared BUY capacity-limit derivation consumed by both `PositionSizingService`
and `RiskEngine`, so the two authorities' ceilings can never drift apart;
replay/idempotency safety, including safe behavior for a request identity
that already completed across a process restart; and an explicit L1
architecture-layer assignment for the new module. `RiskEngine` remains the
sole approve/reject authority throughout; its numeric semantics are
unchanged.

## Source Revision

Branch: `feat/block3-execution-safety`

Parent HEAD (Package 5B, already committed):
`923a9a2abfc9b9b3abb47edce359931bfbb978e6` —
`feat: close block 5b financial precision and sizing authority`

Package 5C commit: **not yet made.** As with Package 5B's own evidence
document, this document is prepared *before* Package 5C is committed, at
explicit instruction. It records the working-tree and index state at
evidence-capture time, not a tagged or already-committed revision.

Worktree at evidence-capture time: **not clean.** The Package 5C production,
packaging, and test files listed below are modified or newly added in the
working tree.

**Staged** (`git diff --cached --stat`, explicitly authorized this session so
that `git ls-files`-based architecture tooling can see both new Package 5C
files):

```
core/position_sizing.py                         |  234 ++++
tests/test_block5c_upstream_sizing_authority.py | 1374 +++++++++++++++++++++++
2 files changed, 1608 insertions(+)
```

**Unstaged** (`git diff --stat`, remaining intended Package 5C files, not yet
staged — staging them is the explicitly deferred next step, not part of this
document):

```
core/application.py                           |  10 ++
core/execution_manager.py                     |  28 +++-
core/execution_models.py                      |  48 +++++++
core/market_loop.py                           | 200 ++++++++++++++++++++++++++
core/risk_engine.py                           |  71 +++++++--
packaging/atlas_architecture_map.json         |   6 +
packaging/atlas_runtime_closure.json          |   1 +
tests/test_block5a_risk_state_plumbing.py     |   8 ++
tests/test_block5b_single_sizing_authority.py |  17 ++-
9 files changed, 369 insertions(+), 20 deletions(-)
```

## Frozen Decisions

- `PositionSizingService` is the single upstream BUY sizing authority. It is
  pure and deterministic — no I/O, no reservation, no execution, no
  portfolio mutation — and it proposes only; it never approves, reserves, or
  executes.
- `RiskEngine` remains the sole approve/reject authority. Its numeric
  semantics are unchanged by this package.
- `risk_check` remains the sole admission/reservation authority; only it may
  write `approved_quote_allocation`.
- **Durable-free-capital sizing basis:** `durable_free_quote_capital =
  ExecutionPortfolioFoundation.snapshot()["cash"] -
  CapitalReservationLedger.active_reserved_capital(exclude=request_id)` — the
  same formula `ExecutionManager._durable_free_quote_capital` already used
  for its own admission-time check, not a separate or static figure.
- **Exact `proposed_quote_allocation` Decimal transport (B1):**
  `ExecutionRequest.proposed_quote_allocation` is a new `Decimal | None`
  field carrying the exact pre-admission sizing proposal. It raises
  `ValueError` on a float input, exactly like `approved_quote_allocation`. It
  is not an approval; `approved_quote_allocation` remains the sole canonical
  admitted allocation, written only by `risk_check`. `_requested_quote_allocation`
  reads it first, ahead of the `amount` fallback, so an authoritative
  proposal never round-trips through the lossy `float` mirror on its way to
  `RiskEngine`.
- **Shared `derive_buy_capacity_limits` contract (M1/M2):**
  `core/risk_engine.py` now exposes `BuyCapacityLimits` and
  `derive_buy_capacity_limits(policy, bucket_policy, *, symbol_exposure,
  committed_quote)` as the single derivation of the seven canonical BUY
  capacity ceilings. `RiskEngine.evaluate` and `PositionSizingService.propose`
  both call the identical function object — not two independently
  maintained copies of the same formula — so a proposal
  `PositionSizingService` considers fine can never exceed a limit
  `RiskEngine` will actually enforce, and a policy or exposure change can
  never let the two authorities' ceilings drift apart.
- `core/position_sizing.py` is explicitly assigned layer **L1** in
  `packaging/atlas_architecture_map.json`.

## Sizing Formula

```
capacity  = derive_buy_capacity_limits(policy, bucket_policy,
                symbol_exposure=symbol_exposure, committed_quote=committed_quote)
candidate = durable_free_quote_capital * bucket_policy.max_allocation_pct
proposed  = min(candidate, *capacity.as_tuple(), durable_free_quote_capital)
```
computed under `ROUND_DOWN`. `confidence` is deliberately not a
`SizingInputs` field (Owner Decision 1: AI confidence is never a direct
allocation multiplier).

## Replay / Idempotency Guarantees

- Same request identity + unchanged durable inputs recomputes the identical
  proposal (same `inputs_digest`) and reuses the existing reservation without
  a second `reserve()` call and without conflict.
- Same request identity + changed durable inputs (e.g. unrelated capital
  newly encumbered) is refused as `SIZING_REPLAY_CONFLICT` before
  `risk_check` and before any reservation attempt, leaving the existing
  reservation's amount and version untouched and never halting the runtime.
- **Completed-replay restart fix (M-A):** a request identity that already
  holds a `COMMITTED` reservation because it already executed to completion
  is answered from `ExecutionManager`'s own durable completed-request cache
  (`completed_request_results`, rehydrated from the on-disk
  `ExecutionIdempotencyStore` file across a process restart) rather than
  being re-priced by `PositionSizingService`. Before this fix, post-trade
  cash/exposure differed from what earned the original approval, so the
  recomputed proposal legitimately differed from the `COMMITTED` reservation
  amount and was misreported as `SIZING_REPLAY_CONFLICT` instead of the
  duplicate it actually was. `MarketLoop._apply_position_sizing` now returns
  `None` — before any proposal is computed — whenever `request_id` is
  already present in `completed_request_results`, handing the request to
  `execute() -> _claim_request()`, which answers it from the durable cache
  with no sizing, no new reservation, no conflict, and no halt.
- `CapitalReservationLedger`'s own collision guard (a second `reserve()`
  call under the same reservation id with a different amount, or a
  different `request_id`, still raises `ValueError`) is unchanged.

## Risk / Admission Separation

- `PositionSizingService` and `SizingProposal` expose no approve / reserve /
  execute surface (structurally asserted in tests).
- `RiskEngine` exposes no sizing surface (no `propose` / `size` /
  `sizing_service` attribute).
- A proposal `PositionSizingService` considers fine can still be rejected by
  `RiskEngine` on grounds the sizer structurally has no input for
  (confidence, drawdown, daily loss, duplicate position, position count).
- `RiskEngine` never silently caps a request above a limit: a request one
  unit above a binding limit is still refused as `REQUEST_EXCEEDS_RISK_LIMIT`.
- No-sizer BUY remains fail-closed exactly as Package 5B specified:
  `UNSIZED_REQUEST_REJECTED`, refused before the engine and before any
  reservation.
- SELL / reduce-only requests never enter `PositionSizingService`; Package
  5B's exact durable-exposure exit semantics are unmodified and unreached by
  this package's code.

## Architecture

- `core/position_sizing.py` is explicitly assigned `L1` in
  `packaging/atlas_architecture_map.json`'s `layer_rules`, listed ahead of
  the generic `core/* -> L3` fallback (first-match-wins).
- Its only non-stdlib import is `core.risk_engine` (L1). `L1 -> L2` and
  `L1 -> L3` are both standing `forbidden_edges` with no
  `permitted_exceptions` entry covering this module, so a future L2/L3
  import added to it would be rejected by
  `tests/architecture/test_forbidden_layer_imports.py`.
- `packaging/atlas_runtime_closure.json` lists `core/position_sizing.py`
  among the modules reachable from the declared entry points, conditional on
  the file being tracked by git (see Review History, B-A).

## Review History

### Independent review of the original Package 5C implementation

Raised against an earlier, pre-remediation state of this package (not
independently re-derived in this session; verified as closed below against
the code as it stands now).

**B1.** An exact `Decimal` sizing proposal could cross
`ExecutionRequest.amount`, a `float`-backed compatibility field, corrupting
a decimal tail. **Remediated:** the dedicated `proposed_quote_allocation`
field (Frozen Decisions, above) carries the proposal exactly; `amount` is
never written by sizing.
**Closed. Evidence:** `test_decimal_tail_proposal_is_computed_exactly`,
`test_execution_request_rejects_a_float_proposed_quote_allocation`,
`test_execution_request_proposed_quote_allocation_round_trips_exactly`,
`test_decimal_tail_proposal_reaches_risk_check_and_reservation_exactly` —
a decimal-tail durable cash figure (`7500.000000004106`) is proven to
produce an exact proposal (`1875.00000000102650`), provably distinct from
the corrupted value a `Decimal -> float -> Decimal` round trip would have
produced (`1875.0000000010266`), and that exact value survives proposal ->
`ExecutionRequest` -> `risk_check` approval -> reservation unchanged.

**H1.** The `inputs_digest` did not seal every effective input capable of
changing the proposal, so a policy or exposure change could go undetected as
an unchanged replay. **Remediated:** the digest now seals `durable_free_quote_capital`,
both exposure figures, `basis_pct`, and all seven resolved capacity terms —
exactly the terms `propose()` mins over.
**Closed. Evidence:** `test_digest_changes_when_any_effective_capacity_input_changes`
(8 parametrized cases: `total_capital`, `max_position_pct`, `per_symbol_pct`,
`concentration_pct`, `portfolio_exposure_pct`, `cash_reserve_pct`,
bucket `max_allocation_pct`, bucket `exposure_ceiling_pct`) and
`test_digest_is_stable_for_the_same_effective_sizing_inputs`.

**M1.** Durable cash above the nominal `RiskPolicy.total_capital` could let
the sizer's own candidate formula (`durable_free_quote_capital * basis_pct`)
propose more than the canonical, `total_capital`-relative limit `RiskEngine`
itself enforces — a proposal the runtime could never admit.
**Remediated:** by the M2 shared-derivation fix (below); the sizer's own
`min(...)` now includes the same `total_capital`-relative ceilings
`RiskEngine` applies.
**Closed. Evidence:** `test_cash_greater_than_nominal_total_capital_does_not_over_propose`
— cash `12000` against nominal `total_capital` `10000` under the default
MEDIUM policy proposes `2500` (the bucket-allocation ceiling), not `3000`
(the unbounded candidate), and `RiskEngine` approves that proposal
unchanged.

**M2.** The sizer's own capacity `min(...)` and `RiskEngine`'s admission
`min(...)` were two independently maintained copies of the same formula,
free to drift apart.
**Remediated:** both now call the single shared `derive_buy_capacity_limits`
function (Frozen Decisions, above); the formula, term order, and `min()`
semantics are byte-identical to the pre-remediation inline tuple in
`RiskEngine.evaluate` (verified by direct diff comparison this session).
**Closed. Evidence:** `test_sizer_and_engine_consume_the_identical_shared_limit_derivation`
(asserts `sizing_module.derive_buy_capacity_limits is
risk_engine_module.derive_buy_capacity_limits` — the same function object,
not two copies), `test_sizer_now_bounds_its_own_proposal_by_the_bucket_exposure_ceiling`,
`test_riskengine_evaluate_still_never_silently_caps_a_request_above_a_limit`.

**M3.** `core/position_sizing.py` had no explicit architecture-layer
assignment.
**Remediated:** explicit `L1` rule added ahead of the `core/*` fallback
(Architecture, above).
**Closed. Evidence:** `test_position_sizing_is_explicitly_assigned_l1_in_the_architecture_map`,
`test_forbidden_edges_would_reject_a_future_l2_or_l3_import_into_position_sizing`,
and `tests/architecture/` passing in full (Validation Evidence, below) —
conditional on the file being tracked (see B-A).

### This session's independent verification

Performed as a read-only review of the remediated B1/H1/M1/M2/M3 state,
against the actual working-tree code and by direct reproduction, not by
re-reading the original review's claims.

**B-A — BLOCKING (found and closed this session).** `core/position_sizing.py`
and `tests/test_block5c_upstream_sizing_authority.py` were untracked
(`git status` `??`). `compute_runtime_closure` builds its module index from
`git ls-files`, so an untracked module cannot enter the closure, making the
checked-in `packaging/atlas_runtime_closure.json` and
`packaging/atlas_architecture_map.json` entries for it read as stale:
`pytest tests/architecture -q` failed 2 of 15
(`test_runtime_closure_matches_inventory`, `test_layer_assignment_is_total`).
Verified by simulation (monkeypatched tracked-file lookup only, no repo
writes) that with the file tracked, both checks pass and no
`permitted_exceptions` entry shields it.
**Remediated:** `git add core/position_sizing.py
tests/test_block5c_upstream_sizing_authority.py`, explicitly authorized.
**Closed. Evidence:** `pytest tests/architecture -q` — 15 passed (Validation
Evidence, below).

**M-A — MEDIUM (found and closed this session).** Reachability: a completed
BUY's fingerprint was cached only in `MarketLoop`'s in-memory
`completed_execution_fingerprints`, which does not survive a process
restart, while `ExecutionManager.completed_request_results` — rehydrated
from the durable `ExecutionIdempotencyStore` file — does. After a restart,
a replay of a completed request's exact identity therefore reached
`PositionSizingService` before `ExecutionManager`'s own durable duplicate
check, and post-trade cash/exposure legitimately produced a different
proposal than the `COMMITTED` reservation, misreporting the duplicate as
`SIZING_REPLAY_CONFLICT`. Reproduced directly (isolated scratch state
directory) before the fix: run 1 a real BUY to `PAPER_EXECUTED` /
`COMMITTED`; a fresh `AtlasApplication` on the same state directory replaying
the identical request identity returned `('REJECTED', 'SIZING_REPLAY_CONFLICT')`
from `_apply_position_sizing`, while `execute()` alone answered correctly
from its own idempotency cache (`cache_hit: True`).
**Remediated:** `MarketLoop._apply_position_sizing` now returns `None`,
before any proposal is computed, whenever `request_id` is already present in
`ExecutionManager.completed_request_results` (Replay / Idempotency
Guarantees, above).
**Closed. Evidence:** `test_completed_replay_after_restart_uses_durable_cache_not_sizing`
in `tests/test_block5c_upstream_sizing_authority.py` — drives a real BUY to
completion, then constructs a **second, independent** `AtlasApplication` on
the identical scratch state directory (a genuine restart; the durable cache
is rehydrated from disk, not hand-seeded in memory) and replays the same
request identity through the real `MarketLoop.route_execution` path,
asserting cache-hit/duplicate semantics win, no `SIZING_REPLAY_CONFLICT`, no
sizing metadata written, and the existing reservation's amount/version/status
untouched.

### Final known findings

BLOCKING: 0
HIGH: 0
MEDIUM: 0

## Validation Evidence

All commands were run against the working tree in this session with an
isolated, ASCII `--basetemp` outside the repository (this host's default
tmp-path root is broken for pytest), per this project's standing testing
convention.

**Package 5C focused suite (post-remediation, includes the M-A regression):**
81 passed.
`python -m pytest tests/test_block5c_upstream_sizing_authority.py -q --basetemp=C:/Users/HUAWE~1/AppData/Local/Temp/claude/atlas5c_ma -p no:cacheprovider`

**Package 5A + 5B regression:** 119 passed.
`python -m pytest tests/test_block5a_risk_state_plumbing.py tests/test_block5b_single_sizing_authority.py -q --basetemp=C:/Users/HUAWE~1/AppData/Local/Temp/claude/atlas5ab_ma -p no:cacheprovider`

**Architecture suite (post-staging of `core/position_sizing.py` and
`tests/test_block5c_upstream_sizing_authority.py`):** 15 passed.
`python -m pytest tests/architecture -q --basetemp=C:/Users/HUAWE~1/AppData/Local/Temp/claude/atlas5carch_final -p no:cacheprovider`

**Full `tests/` suite:** 2111 passed in 54.28s.
`python -m pytest tests/ -q --basetemp=C:/Users/HUAWE~1/AppData/Local/Temp/claude/atlas5c_full -p no:cacheprovider`

### Prior runs this session (superseded by the results above)

Recorded for audit continuity, not as current evidence.

- Before the M-A fix: `tests/test_block5c_upstream_sizing_authority.py` +
  `tests/test_block5b_single_sizing_authority.py` +
  `tests/test_block5a_risk_state_plumbing.py` together — 199 passed.
  Adjacent reservation/risk/execution suites
  (`test_block2_m1_reservation_admission_atomicity.py`,
  `test_block2_risk_service_composition_wiring.py`,
  `test_block3_durable_execution_path_ownership.py`,
  `test_block3_execution_exception_atomicity.py`,
  `test_block3_terminal_status_classification.py`) — 122 passed.
- Before staging: `tests/architecture -q` — 2 failed
  (`test_layer_assignment_is_total`, `test_runtime_closure_matches_inventory`),
  13 passed (B-A, above).

**`core/risk_engine.py`:** changed in this package (unlike Package 5B, which
left it untouched). `RiskEngine.evaluate`'s inline BUY capacity-limit tuple
was extracted into the new shared `derive_buy_capacity_limits(...)` function
(M2, above); the formula, term order, and `min()` semantics are unchanged,
verified by direct diff comparison. `RiskEngine`'s approve/reject role and
`PAPER`/`LIVE` behavior are otherwise untouched.

**Staging state at capture time:** exactly 2 of the 12 intended files staged
(`core/position_sizing.py`, `tests/test_block5c_upstream_sizing_authority.py`);
this document not yet staged (see Source Revision above).

## Known Non-Blocking Follow-ups / Limitations

**Superseded by Package 5C:** Package 5B's own recorded limitation — "No
upstream sizing authority yet... No real MarketLoop BUY can execute until a
sizing authority is added upstream" — is resolved by this package. A
real-loop BUY, sized by `PositionSizingService`, now settles end to end
(`test_real_market_loop_buy_is_sized_and_settles_end_to_end`).

**Still open, unrelated to Package 5C's scope, carried forward from
`docs/evidence/block5b_freeze_evidence.md` unchanged:**

- `BASE_QUANTITY_QUANTUM` is not venue precision — it is this runtime's own
  representation bound (1e-8), not a per-instrument exchange step size or
  minimum quantity.
- No pre-admission fee model — `ExecutionRequest` still carries no fee
  input; the fee-inclusive executable-quantum bound is still checked only at
  fill time, not at admission.
- F3–F9 (LOW / observation, from the independent review that also produced
  5B's F1/F2): partial-SELL side-effect-boundary marking when no external
  side effect occurred; a component-reported fee without a declared
  currency; BUY quote depending on ambient `Decimal` context outside the
  explicit `localcontext`; unsized-request rejection potentially masking a
  risk verdict in the audit trail; a deterministic sub-quantum remainder
  left encumbered after settlement; `entry_fees` not released pro rata on
  partial reduction; and price/fee/the caller-supplied `amount` mirror
  potentially still originating from `float`. None of these are touched,
  narrowed, or widened by Package 5C. Full text: `docs/evidence/block5b_freeze_evidence.md`,
  "Known Non-Blocking Follow-ups / Limitations" and "Independent review —
  LOW / observation findings (F3–F9)".

**D1 / D2 / D3 — LOW, non-blocking (supplied by the independent review).**
Recorded as supplied; not independently re-derived or re-verified in this
session. These are known non-blocking follow-ups and are **not claimed
resolved by Package 5C** — this package's remediation scope was B1, H1, M1,
M2, M3, B-A, and M-A only (see Review History above). They do not change the
"Final known findings" recorded there or this document's Status:

    BLOCKING: 0
    HIGH: 0
    MEDIUM: 0
    Package 5C closure candidate: PASS

**D1 — LOW.** The `SIZING_REPLAY_CONFLICT` early-return path
(`MarketLoop._apply_position_sizing`) discards the pending fingerprint but
does not add it to `completed_execution_fingerprints`. The same decision may
therefore be re-sized and re-rejected on subsequent cycles instead of
short-circuiting as an already-completed rejection. This is not unsafe, but
it can create repeated rejection/audit noise.

**D2 — LOW.** The sizing exception path can return `None` without writing
sizing-failure metadata. The BUY remains fail-closed as
`UNSIZED_REQUEST_REJECTED`, but the audit trail cannot distinguish "no sizer
configured" from "sizer attempted and failed" except through the loop's
in-memory error buffer.

**D3 — LOW.** A genuine `SIZING_REPLAY_CONFLICT` can leave an existing
durable reservation in `RESERVED` state. There is no startup reconciliation
for orphan reservations, so operator recovery/runbook handling remains a
known operational follow-up.

## PAPER / LIVE

Unchanged by this package. PAPER remains the default and LIVE authority
remains denied. Package 5C added an upstream sizing proposer and a shared
BUY capacity-limit derivation; it did not modify the PAPER default, LIVE
denial, or any live-execution adapter path.

## Push Status

NOT PUSHED. No push, no merge, and — as of this document — no commit exists
for Package 5C. Nothing beyond the file list below has been touched by this
package's work.

## Exact Intended Package 5C File List

Total: **12 files** — 6 core production, 2 packaging/architecture, 3 tests,
1 evidence document.

Core production (6):
- `core/application.py`
- `core/execution_manager.py`
- `core/execution_models.py`
- `core/market_loop.py`
- `core/position_sizing.py` (new)
- `core/risk_engine.py`

Packaging / architecture metadata (2):
- `packaging/atlas_architecture_map.json`
- `packaging/atlas_runtime_closure.json`

Tests (3):
- `tests/test_block5a_risk_state_plumbing.py`
- `tests/test_block5b_single_sizing_authority.py`
- `tests/test_block5c_upstream_sizing_authority.py` (new)

Evidence (1, this document):
- `docs/evidence/block5c_freeze_evidence.md` (new)

No unrelated or generated files are in scope for this package; `git status
--short` at capture time contains no entries outside this list.

## Limits of This Evidence

Package 5C establishes a single upstream BUY sizing authority with an exact
`Decimal` proposal transport, a durable-free-capital sizing basis, a shared
BUY capacity-limit derivation with `RiskEngine`, and replay/idempotency
safety including cross-restart completed-replay handling. It does not
establish, and this document does not claim: venue-accurate
lot-size/step-size/minimum-quantity enforcement, a fee model available at
admission, any change to SELL/reduce-only sizing or settlement semantics
(untouched, Package 5B's authority), LIVE readiness, or production exchange
integration, or resolution of the D1–D3 LOW follow-ups recorded above
(known non-blocking; not claimed resolved by this package). This document
also does not claim a committed or tagged revision: it is a closure
candidate awaiting explicit user approval to stage and commit.
