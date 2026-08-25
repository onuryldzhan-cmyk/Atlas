# Atlas Block 5 — Final Closure Record

## Status

**BLOCK 5 — CLOSED.**

BLOCKING open: 0
HIGH open: 0
MEDIUM correctness open: 0

Parent HEAD: `7f58271` ("feat: harden durable execution storage").

Nothing was pushed.

This document is the authoritative Block 5 closure record. It supersedes no
package evidence; each package's own freeze document remains the detailed
record of what it changed and why.

## Package Lineage

| package | final outcome |
| --- | --- |
| 5B | CLOSED — deterministic financial precision and a single sizing authority; `approved_quote_allocation` is the one canonical admitted allocation and `amount` became an explicitly non-authoritative float mirror |
| 5C | CLOSED — upstream position sizing authority; `proposed_quote_allocation` carries exact sizing intent to `risk_check` without crossing the float mirror |
| 5D | CLOSED — venue instrument precision is a fail-closed admission gate (unknown symbol, off-tick price, off-step quantity, sub-minimum notional all refused); M2 (static-rule staleness) and M4 (no upper venue bound) recorded as accepted, gated below |
| 5E | CLOSED — exact quote-fee and settlement accounting |
| 5F | CLOSED — durable capital reservation reclamation; capital is released on recorded fact, never on inference |
| 5G | CLOSED — deterministic position lifetime identity (`mint_long_position_id`) |
| 5H-0 | CLOSED — execution evidence authority alignment; idempotency retention made unbounded, `prepare()` cannot reopen a COMMITTED entry, runtime disagreement fails closed |
| 5H | CLOSED — reservation working set holds live states only; immutable reservation history lives in an append-only archive |
| 5I | CLOSED — financial state sidecars, crash-safe checkpoints, and migration safety (H-1 fixed: closed identity is `(sequence, payload)`, and the destination is verified before the v1 source is rewritten) |
| 5J | CLOSED — unsafe durable `ExecutionManager.reset()` closed, no reset can manufacture `SOURCE_DISAGREEMENT`, and one deliberately narrow operator reconciliation path exists |
| 5K | CLOSED — append-only execution idempotency and journal storage, versioned format with operator-only migration enforcement, B5J-1 output safety |
| 5L | CLOSED — remaining debt classified; three ambient-Decimal-context findings and one 5K architecture-governance defect fixed; live-readiness gates made explicit and enforced |

## Final Invariants

Each is held by current code, not by intent.

1. **Single sizing authority** — `approved_quote_allocation` is the sole
   admitted allocation; `RiskEngine` and `PositionSizingService` derive their
   ceilings from one shared `derive_buy_capacity_limits`, so the two
   authorities cannot drift apart. `CapitalManager` holds no admission
   authority.
2. **Deterministic financial precision** — every financial derivation runs
   inside an explicit `localcontext()`; no figure depends on the calling
   process's ambient `decimal` precision (completed in 5L, below).
3. **Venue quantity/notional safety under the current supported contract** —
   unknown symbol, off-tick price, off-step quantity, and sub-minimum
   notional are each refused before any reservation. Upper bounds are not
   modelled and are structurally unreachable (gate V1).
4. **Exact quote-fee settlement semantics** — fees settle in quote currency
   with exact `Decimal` arithmetic; `entry_fees` survives partial exits.
5. **Durable capital reservation lifecycle** — RESERVED before the
   side-effect boundary; RELEASED only when the boundary was provably not
   crossed; INDETERMINATE halts rather than freeing capital it cannot prove
   is free.
6. **Unique position lifetime identity** — a `position_id` archives exactly
   once; a repeat close raises `CLOSED_POSITION_IDENTITY_CONFLICT` against
   the immutable closed-position authority, and that check survives restart.
7. **Permanent execution replay authority** — the idempotency store retains
   every completed `request_id` indefinitely; a conflicting terminal result
   is refused at write and fails closed at read.
8. **Immutable financial history** — applied executions, closed positions,
   and reservation history are append-only with no retention or pruning.
9. **Crash-safe financial checkpoints** — the working state's
   `applied_checkpoint` / `closed_checkpoint` must agree with each sidecar's
   durable tail or the foundation refuses to become `ready`.
10. **Safe operator migration** — both migration tools reload the
    destination through the runtime's own loader and require an exact match
    before the legacy source is rewritten or retired; the source is never
    deleted.
11. **Safe authority reconciliation** — exactly one repair class, only when
    three independent durable authorities prove one unique terminal truth;
    every other disagreement refuses wholesale.
12. **Reset cannot erase half an authority pair** — `ExecutionManager.reset()`
    refuses whenever execution history is present or indeterminate.
13. **Append-only hot-path execution authority storage** — recording a
    terminal result or a journal transition appends one line; no prior
    durable byte is rewritten.
14. **A completed request cannot execute twice** — a replayed `request_id` is
    answered from the durable terminal record; a COMMITTED journal entry with
    no counterpart halts as `SOURCE_DISAGREEMENT`; legacy state halts as
    `SCHEMA_OR_MIGRATION_INVALID` rather than reading as empty history.

## Package 5L — Debt Classification

Every remaining recorded Block 5 item, classified before any change was made.

| item | classification | rationale |
| --- | --- | --- |
| A. startup O(history) | ACCEPTED OPERATIONAL LIMITATION | replay rebuilds the index every reader already needs; no current operational requirement is violated, and a cache would add a second thing that can disagree with the authority |
| B. audit growth / retention | LATER-PHASE OBSERVABILITY | `AuditEventStore` is already append-only JSON-Lines with fsync; only unbounded growth remains, which is a retention policy, not a correctness defect |
| C. no sidecar retention / pruning | ACCEPTED BY DESIGN | these are permanent correctness authorities; pruning one would be the defect, not the fix |
| D. 5I L-3 — tests assert private archive indexes | TEST-QUALITY DEBT ONLY → **fixed** | a public equivalent existed and is strictly more direct; see below |
| E. 5I L-4 — exact field-set equality blocks legacy records with extra fields | ACCEPTED OPERATIONAL LIMITATION | the field set is exactly what `_close` produces; no legacy record carrying extra fields exists in this repository, so an ignorable-metadata allowlist would be invented rather than derived. Kept fail-closed; the operator inspects and corrects the record |
| F. Decimal-context / float-origin | **PARTLY UNRESOLVED — fixed in 5L** | the float-origin half was already closed (authoritative fields are exact `Decimal`; float fields are documented non-authoritative mirrors; the one ingress uses `Decimal(str(...))`), but three ambient-context derivations were still open — see below |
| G. venue upper bounds + static-rule staleness | FUTURE LIVE-SCALE GATE | unreachable: `live_execute` refuses for want of an approved adapter even with `live_execution_enabled=True`, so no order reaches a venue at all |

## 5L Fixes

Four findings: three ambient-Decimal-context defects in authoritative
financial derivations, and one architecture-governance defect introduced by
Package 5K.

None of the three Decimal findings was reachable under the supported
contract — Atlas never mutates the global `decimal` context, and every
realistic magnitude fits the interpreter default of 28 significant digits —
but each made a financial result depend on the calling process's precision.
Each is now computed in an explicit local context, matching the discipline
`_open`/`_close` and `PositionSizingService` already used.

- **5L-1 (LOW, fixed) — `core/execution_models.py`.**
  `validate_financial_evidence` compared `execution_price × filled_base_quantity`
  against `filled_quote_notional` under the ambient context. A product needing
  more digits than that context carried was rounded, and the fill was refused
  as a mismatch although the equality held. Fail-closed in direction, but it
  refused money that had already moved. The product is now computed at a
  precision derived from the operands' own digit counts, so the gate is
  exactly the exact-equality check it claims to be; every genuine mismatch is
  still rejected.
- **5L-2 (LOW, fixed) — `core/execution_portfolio_foundation.py`.**
  `snapshot()` and `available_capital()` derived exposure, unrealized PnL,
  realized net PnL, equity, and free capital under the ambient context.
  `available_capital` is read by sizing, so a narrow context could silently
  understate or overstate it rather than fail closed.
- **5L-3 (MEDIUM correctness, fixed) — `core/risk_engine.py`.**
  Every risk ceiling (`derive_buy_capacity_limits`), `reserved_capital`,
  `allocatable_capital`, the drawdown divisions, the daily-loss ceiling, the
  symbol-exposure sum, and the `quantity × price` admission gate were derived
  under the ambient context. This module holds no `localcontext` at all before
  5L. Graded MEDIUM rather than LOW because the direction is capital-permissive:
  a ceiling rounded *up* would admit an allocation above the true policy limit.
  Now derived at `RISK_CONTEXT_PRECISION` (50, matching
  `SETTLEMENT_CONTEXT_PRECISION`, restated locally so no module edge is added).

- **5L-4 (HIGH, introduced by 5K, fixed in 5L) — architecture governance.**
  Package 5K added `core/durable_append_log.py` without adding it to
  `packaging/atlas_architecture_map.json`. It fell through to the `core/`
  catch-all rule and was classified **L3** (application orchestration), which
  made both stores' imports of it forbidden `L2 -> L3` edges. Four tests
  (`tests/architecture/test_forbidden_layer_imports.py`,
  `test_layer_assignment_is_total.py`,
  `test_runtime_closure_matches_inventory.py`, and
  `tests/test_block4_market_data_architecture.py::test_declared_module_layers_still_cover_exactly_the_runtime_closure`)
  fail at commit `7f58271` with a clean tree — verified by stashing all 5L
  work and running them directly. The Package 5K evidence recorded a green
  full suite; that line was not a reliable green, and it has been corrected in
  place rather than left standing.

  Fixed by classifying the module **L2**, alongside `core/audit_event_store.py`
  and the two stores that import it — it is a pure durable-storage primitive
  with stdlib-only imports, so L2 is its correct layer. Both inventory
  artifacts were regenerated with `tools/build_architecture_inventory.py`. **No
  permitted exception was added**: the classification was wrong, not the rule,
  and adding an exception would have weakened the layer contract to fit a
  mistake.

Also in 5L:

- **5I L-3 closed.** `tests/test_block5i_durable_financial_state_sidecars.py`
  no longer reads `ExecutionPortfolioFoundation._closed_by_position_id` /
  `._applied_by_execution_id`. It asserts each archive's own public
  `load_index()` instead — the durable authority the private mirror was
  standing in for — while the foundation constructed on those archives is
  still required to report `ready`.

No production change was made for items A, B, C, E, or G: each is an accepted
limitation or an unreachable future requirement, and inventing a fix for one
would have added architecture without closing a defect.

## Live-Readiness Gates

Limitations that are safe now and **must** be resolved before the stated
expansion. None of this work is complete; none of it is claimed complete.

### CURRENT PAPER / BOUNDED EXECUTION — SAFE

| gate | status |
| --- | --- |
| V1 venue upper bounds (`LOT_SIZE.maxQty`, `NOTIONAL.maxNotional`, `MARKET_LOT_SIZE`) | SAFE — unmodelled, but no order can reach a venue: `live_execute` refuses for want of an approved adapter even when `live_execution_enabled=True` |
| V2 static venue-rule staleness | SAFE — the checked-in `config/instrument_rules.json` is the only source; a venue tightening a rule after `retrieved_at` cannot affect a PAPER book |
| S1 startup O(history) | SAFE — replay cost is bounded by the history a PAPER book accumulates |
| S2 authority log growth | SAFE — append-only, permanent by design |
| O1 audit log growth | SAFE — append-only with fsync; no retention policy exists |

### BEFORE SCALED LIVE CAPITAL — REQUIRED

- **V1.** Model `maxQty`, `maxNotional`, and `MARKET_LOT_SIZE` in
  `InstrumentRules` and enforce them in the same fail-closed admission gate
  that already enforces the lower bounds. This is required *before* any live
  execution adapter is wired, not after: the adapter is what makes an
  unmodelled maximum reachable.
- **V2.** An operator refresh cadence and staleness detection for
  `config/instrument_rules.json`, so a venue rule change is detected rather
  than discovered by a rejected order.

Two tests in `tests/test_block5l_block5_final_hardening.py` enforce this
gate rather than merely describing it: one fails the day an upper bound is
added to `InstrumentRules` (forcing the gate to be re-decided), and one fails
the day a live adapter seam appears on `ExecutionManager` (forcing V1 to be
closed first).

### BEFORE LONG-RUN OPERATIONAL SCALE — REQUIRED

- **S1.** A startup index or checkpoint cache for the execution authorities,
  only with a proof that the cache cannot disagree with the log it summarises.
- **S2 / O1.** An archival policy for the append-only authorities and the
  audit log. Correctness authorities must stay permanent unless an archive
  proves equivalence; this is an archival design question, not a pruning one.

## Closure Review

One bounded review of current Block 5 financial and execution correctness, at
the boundaries that matter. Each answer is held by current code.

| can the current system... | answer | what holds it |
| --- | --- | --- |
| spend capital twice? | NO | durable reservation ledger; ceilings subtract `committed_quote`; INDETERMINATE halts instead of releasing |
| apply a fill twice? | NO | `apply_confirmed` short-circuits an already-durable `execution_id`; the applied archive refuses a duplicate `execution_id`/`idempotency_key` at load |
| replay a completed request as new? | NO | permanent idempotency authority; legacy state halts rather than reading as empty; reset refuses while history exists |
| silently lose committed financial history? | NO | append-only, no pruning; torn or conflicting logs fail closed; migration retains the source until the destination verifies |
| manufacture free capital? | NO | release is driven by the recorded side-effect boundary, never inferred |
| overwrite a closed lifetime? | NO | `CLOSED_POSITION_IDENTITY_CONFLICT` against the immutable closed archive |
| report ready with conflicting durable authorities? | NO | `SOURCE_DISAGREEMENT`; and `SCHEMA_OR_MIGRATION_INVALID` for legacy state |
| migrate successfully into an unloadable state? | NO | both tools reload the destination through the runtime's own loader before touching the source |
| silently accept unsupported venue precision/limits? | NO | precision is a fail-closed gate; upper limits are unreachable (gate V1) |

Closure review: **PASS**.

## Accepted Carry-Forward

Separated by kind. None of these is a correctness defect.

**Operational scalability**
- startup O(history) for both execution authorities (gate S1)
- append-only authority log growth (gate S2)

**Future live-scale venue requirements**
- venue upper bounds `maxQty` / `maxNotional` / `MARKET_LOT_SIZE` (gate V1)
- static venue-rule staleness and refresh cadence (gate V2, Block 5D M2)

**Test-quality LOW**
- none open. 5I L-3 was closed in 5L.

**Later-phase observability / retention**
- audit log growth and retention policy (gate O1)
- no retention or pruning for the correctness authorities — deliberate, and
  only revisitable via an archival design that proves equivalence

## Changed Files (5L)

| file | change |
| --- | --- |
| `core/execution_models.py` | 5L-1 — exact product computed in an explicit local context |
| `core/execution_portfolio_foundation.py` | 5L-2 — `snapshot()` / `available_capital()` derived in an explicit local context |
| `core/risk_engine.py` | 5L-3 — every capital derivation, ceiling, division, and the quantity/notional gate moved into an explicit local context |
| `tests/test_block5i_durable_financial_state_sidecars.py` | 5I L-3 — public archive indexes replace the private-mirror assertions |
| `tests/test_block5l_block5_final_hardening.py` | new — the five enforced closure gates |
| `packaging/atlas_architecture_map.json` | 5L-4 — `core/durable_append_log.py` classified L2; `module_layers` regenerated |
| `packaging/atlas_runtime_closure.json` | 5L-4 — regenerated |
| `docs/evidence/block5k_durable_execution_storage.md` | 5L-4 — the Package 5K full-suite claim corrected in place |
| `docs/evidence/block5_final_closure.md` | this document |

## Validation

| run | command | result |
| --- | --- | --- |
| focused | `pytest tests/test_block5l_block5_final_hardening.py -q` | 5 passed |
| direct regression | `pytest tests/ -q -k "block5 or block3 or risk or sizing or capital or execution or financial or phase4 or portfolio"` | 1430 passed |
| full suite | `pytest tests/ -q` | 2361 passed, 0 failed (includes all 30 architecture tests) |

The two hostile-context tests are the discriminating evidence for 5L-1/5L-2
and 5L-3: each drives a real open/close cycle, or a real risk admission, once
under the default context and once under `prec=6`, and requires the two to be
identical. Before the fixes, the first refused the fill outright and the
second produced different capital figures.

## PAPER / LIVE

PAPER remains the default and LIVE authority remains denied. Block 5 grants no
live-trading authority and 5L adds none — it makes the live-readiness
preconditions explicit and enforced instead.
