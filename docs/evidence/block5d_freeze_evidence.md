# Atlas Block 5 / Package 5D Freeze Evidence

## Status

Package 5D closure candidate: PASS
BLOCKING: 0
HIGH: 0
MEDIUM NEW: 0

User approval required before staging/commit. As of this writing, **none**
of the files in Package 5D's intended file list are staged. Nothing in
Package 5D — including this document — has been committed.

## Package

Block 5 / Package 5D — Venue Instrument Precision Contract
(`core/instrument_rules.py`, `config/instrument_rules.json`,
`core/execution_manager.py`, `core/application.py`).

## Objective

Package 5D establishes the sole venue instrument-precision authority for the
runtime: `InstrumentRules` / `InstrumentRuleset`, loaded once at startup from
the checked-in static `config/instrument_rules.json` and injected into
`ExecutionManager`, which consumes rules but never constructs, mutates, or
invents an entry. It replaces the prior `ExecutionManager.BASE_QUANTITY_QUANTUM`
representation bound (a runtime constant with no venue authority behind it)
with per-symbol `quantity_step` / `min_quantity` / `min_notional` /
`price_tick` fields, and adds a `price_tick` admission gate that refuses a
misaligned request price rather than rounding it.

An independent review of the original package raised three findings — H1
(SELL had no venue-minimum enforcement), M1 (a fee-adjusted BUY fill was not
rechecked against the venue minimums after the fee became known), and M3 (the
rule digest was sensitive to cosmetic trailing-zero representation) — plus
two accepted, explicitly out-of-scope limitations, M2 (no rule-staleness
bound) and M4 (no upper venue bound). This document freezes the
post-remediation state: H1, M1, and M3 closed; M2 and M4 recorded as
accepted, unresolved limitations, not claimed fixed; M5 (this evidence
recording those decisions accurately) closed by the existence and content of
`docs/evidence/block5d_owner_decisions.md` and this document.

## Source Revision

Branch: `feat/block3-execution-safety`

Parent HEAD:
`6ce5153f895ee4ba7e0c082a8705896a3b7e6f73` —
`feat: add upstream position sizing authority`

Package 5D commit: **not yet made.** As with Package 5B's and 5C's own
evidence documents, this document is prepared *before* Package 5D is
committed. It records the working-tree and index state at evidence-capture
time, not a tagged or already-committed revision.

Worktree at evidence-capture time: **not clean, and not staged.** `git diff
--stat HEAD` for the tracked-modified files, plus two new untracked files
(`core/instrument_rules.py`, `tests/test_block5d_instrument_precision_contract.py`,
both shown as `AM` — added-then-modified in the index from an earlier,
already-superseded staging action — and one new untracked file,
`config/instrument_rules.json`, shown as `A`):

```
config/instrument_rules.json                            |  70 ++
core/application.py                                      |  65 ++
core/execution_manager.py                                | 535 ++++++++++---
core/instrument_rules.py                                  | 317 ++++++++
packaging/atlas_architecture_map.json                     |   6 +
packaging/atlas_runtime_closure.json                      |   1 +
packaging/atlas_runtime_distribution_manifest.json         |   1 -
tests/test_block2_m1_reservation_admission_atomicity.py    |  14 +
tests/test_block5b_single_sizing_authority.py              | 143 ++--
tests/test_block5d_instrument_precision_contract.py        | 869 +++++++++++++++++++++
tests/test_durable_transaction_state.py                    |  13 +
tests/test_financial_quantity_identity_contract.py         |  23 +-
tests/test_nbf3_critical_risk_non_executable.py            |  13 +
tests/test_nbf4_unsupported_risk_fail_closed.py            |  13 +
tests/test_nbf6_adapter_enum_authenticity.py                |  13 +
tests/test_phase3_risk_capital_foundation.py                |  13 +
tests/test_phase4_execution_manager_runtime_cutover.py      |   3 +
17 files changed, 1976 insertions(+), 136 deletions(-)
```

Two more files exist only as untracked, evidence-only documents and carry no
production diff: `docs/evidence/block5d_owner_decisions.md` and this
document, `docs/evidence/block5d_freeze_evidence.md`.

## Frozen Decisions

**InstrumentRules / static config authority (owner decisions 1, 2, 9).**
`config/instrument_rules.json` is the sole source of venue instrument
precision for a run. `AtlasApplication._build_instrument_rules` loads it once
at process startup via `load_instrument_ruleset` and injects the resulting
`InstrumentRuleset` into `ExecutionManager`; `ExecutionManager` consumes it
but never constructs, mutates, or invents an entry. There is no
`/exchangeInfo` fetch and no mid-run refresh — rules are immutable for the
lifetime of one process. The distribution manifest's
`block2_non_canonical_unreachable_source_paths` exclusion is narrowed to drop
its blanket `config/**` entry; `config/instrument_rules.json` is the only
file tracked under `config/` (`config/__pycache__/` is untracked and already
caught by the separate `caches_and_environments` exclusion), so the narrowing
selects exactly this one file into the runtime distribution closure, per
owner decision 9.

**BUY venue-precision semantics.** `risk_check` refuses a BUY at admission
when the approved allocation cannot fund one whole `quantity_step`, or when
the floored fill's quantity or notional falls below `min_quantity` /
`min_notional` — `QUANTITY_BELOW_VENUE_MINIMUM` / `NOTIONAL_BELOW_VENUE_MINIMUM`
— before any reservation. `_execute_paper_buy` re-derives the fill via the
same `_resolve_base_fill` used at admission (now parameterized by
`quantity_step` instead of the removed `BASE_QUANTITY_QUANTUM` constant), so
admission and execution can never disagree on how a fill is sized, and
independently re-asserts both minimums against the fee-adjusted fill (M1,
below).

**SELL venue-precision semantics (H1).** `_resolve_reduction_quantity`
enforces, before any side effect: a partial reduction's floored
`base_quantity` must itself clear `min_quantity`, and its notional at the
risk basis must clear `min_notional`; a partial reduction may never strand a
nonzero durable remainder below either minimum
(`REDUCTION_STRANDS_SUBMINIMUM_REMAINDER`) — the request is refused outright,
never silently upgraded to a full close and never rounded up to avoid the
remainder; a full exit still returns the exact durable `base_quantity` byte
for byte (Package 5B unchanged), but that exact quantity is not exempt from
venue minimums — `FULL_EXIT_BELOW_VENUE_MINIMUM` fails closed rather than
being floored, rounded, or written off. No SELL-side venue-minimum failure
reserves, settles, or mutates durable state: every check above runs before
`_mark_execution_side_effect`.

**Startup fail-closed rules (owner decisions 3, 5).**
`ExecutionManager._instrument_rules_startup_check` checks both the
composition root's configured trade-enabled symbols and every symbol the
durable book currently holds a position in. Either kind of symbol without a
rule halts `start()` fail-closed as `INSTRUMENT_RULES_UNAVAILABLE`. A held
position whose durable `base_quantity` is not an exact multiple of its
symbol's `quantity_step` halts as `INSTRUMENT_RULES_POSITION_MISALIGNED` —
never floored, rounded, or written off; only an operator resolves it.

**Replay / rule-digest behavior.** `InstrumentRules._compute_digest` seals
`venue`/`symbol`/`base_asset`/`quote_asset` plus the four authoritative
Decimal fields (each `Decimal.normalize()`-d before serialization — M3,
below) and `source`/`source_version`/`retrieved_at` into a canonical-JSON
sha256 digest. `_risk_admission_key` now includes the symbol's current
rule digest as a sealed admission term, so a rules change between admission
and execution invalidates the admission exactly as an altered approval would
— even though rules are immutable for the lifetime of one process (decision
2), the seal makes that invariant structurally enforced rather than merely
assumed. `RISK_APPROVED` and every fill's `result.data` record
`instrument_rules_digest` / `instrument_rules_source_version` (and, on fill,
`instrument_rules_source`) as evidence.

## Review History

### Independent review of the original Package 5D implementation

Raised against an earlier, pre-remediation state of this package (not
independently re-derived in this session; verified as closed below against
the code as it stands now).

**H1.** SELL was not subject to any venue `min_quantity` / `min_notional`
enforcement — only BUY was. A partial or full reduction could settle a
durable position at a size the venue itself would refuse, and a partial
reduction could strand a durable remainder too small to ever be sold.
**Remediated:** `_resolve_reduction_quantity` (Frozen Decisions, above).
**Closed. Evidence:** `test_sell_floors_to_quantity_step_and_never_rounds_up`,
`test_partial_sell_below_min_quantity_rejected_without_mutation`,
`test_partial_sell_below_min_notional_rejected_without_mutation`,
`test_partial_sell_cannot_strand_remainder_below_min_quantity`,
`test_partial_sell_cannot_strand_remainder_below_min_notional`,
`test_full_sell_below_venue_minimum_fails_closed_without_mutation`,
`test_valid_partial_sell_clearing_all_minimums_still_settles` — the
strand-remainder tests explicitly assert the durable position is left
untouched and `manager._execution_side_effect_ids == set()` (no side effect
was ever crossed), not merely that the request was refused.

**M1.** The admission-time BUY quantum check necessarily used `fee = 0` (the
fee is not known until the executing component reports it); a
component-reported fee could drop the fee-adjusted fill below `min_quantity`
/ `min_notional` after admission had already cleared it, with no recheck at
fill time.
**Remediated:** `_execute_paper_buy` re-asserts both minimums against the
actual fee-adjusted fill, using the same post-side-effect failure machinery
the pre-existing `ALLOCATION_BELOW_EXECUTABLE_QUANTUM` fill-time failure
already used — classified as `EXECUTION_INTERRUPTED_AFTER_SIDE_EFFECT`, the
reservation moved to `INDETERMINATE`, the durable book never seeing the
fill, never silently committed or released.
**Closed. Evidence:** `test_component_fee_pushes_buy_fill_below_min_notional_and_fails_closed`
(direct `paper_execute` level — asserts `position_of(flat_app) is None` and
the reservation stays exactly `RESERVED`, never silently treated as
settled) and `test_component_fee_below_min_notional_halts_through_full_orchestration`
(driven through the real `execute()` orchestration — asserts
`commit_outcome == "COMMIT_STATUS_UNKNOWN"`, `recovery_required is True`,
`halt_reason == "EXECUTION_INTERRUPTED_AFTER_SIDE_EFFECT"`, and the
reservation moved to `INDETERMINATE`).

**M3.** `InstrumentRules._compute_digest` serialized each Decimal field's
un-normalized `format(x, "f")` string, so two rules that are economically
identical but differ only in the checked-in config's cosmetic trailing-zero
representation (`"5"` vs. `"5.00"`, `"0.00001"` vs. `"0.00001000"`) produced
different digests — a purely cosmetic config edit could look like a rule
change to the replay seal.
**Remediated:** each field is `Decimal.normalize()`-d before it enters the
canonical digest payload; `to_dict()` and every execution-path computation
still use the field exactly as configured — only the digest's canonical
input is affected.
**Closed. Evidence:** `test_digest_ignores_cosmetic_trailing_zero_representation`
(`"0.00001"` == `"0.00001000"`, `"5"` == `"5.00000000"`, `"0.01"` ==
`"0.01000000"`, all producing identical digests), `test_digest_still_changes_for_a_genuinely_different_economic_value`
(`"5"` vs. `"5.01"` still differ), `test_rule_digest_changes_when_an_authoritative_rule_changes`,
and `test_to_dict_serialization_is_unaffected_by_digest_canonicalization`
(external evidence serialization is not silently falsified — `to_dict()`
still reports the exact configured string, e.g. `"0.00001000"`, unchanged).

### This session's independent verification (read-only, prior to this document)

Performed as a read-only review of the remediated H1/M1/M3 state against the
actual working-tree code, and of M5 against `docs/evidence/block5d_owner_decisions.md`,
independent of the original review's claims.

- Confirmed `_resolve_reduction_quantity` runs every venue-minimum check
  strictly before `_mark_execution_side_effect` (`_execute_paper_sell` calls
  it at the point durable state is still read-only), so a venue-invalid SELL
  of any kind cannot mutate durable state.
- Confirmed the partial-reduction bound (`base_quantity is None or
  base_quantity <= 0 or base_quantity >= held`) makes "partial is never
  auto-converted to full" a structural property, not a convention: a floored
  quantity that would reach or exceed the held quantity is refused as
  `REDUCTION_BELOW_EXECUTABLE_QUANTUM`, never silently promoted.
- Confirmed `core/risk_engine.py` and `core/position_sizing.py` carry zero
  diff against the parent HEAD (`git diff --stat HEAD -- core/risk_engine.py
  core/position_sizing.py` — no output).
- Confirmed `docs/evidence/block5d_owner_decisions.md` records decision 10
  (SELL venue minimums) and the digest canonicalization (M3) accurately
  against the code, and explicitly records M2 and M4 under "Accepted Package
  5D limitations" — not represented as resolved anywhere in that document.
- Ran the focused, touched-test-regression, architecture, and runtime
  distribution suites independently (Validation Evidence, below) rather than
  accepting reported pass counts.

### Final known findings

BLOCKING: 0
HIGH: 0
MEDIUM NEW: 0

M2 and M4 are **not** counted as new remediation failures: both are
pre-existing, explicitly accepted, out-of-scope limitations of Package 5D
(Known Non-Blocking Follow-ups / Limitations, below), recorded as such in
`docs/evidence/block5d_owner_decisions.md` before this remediation began.

## 5B / 5C Authority Continuity

**Package 5B — exact durable quantity authority: intact.** `core/risk_engine.py`
and the exact-`Decimal` settlement identity Package 5B established are
unmodified by Package 5D. `tests/test_block5b_single_sizing_authority.py`'s
diff updates fixture prices/allocations to clear the new 5D price-tick and
venue-minimum admission gates (e.g. `BTC_LIKE_PRICE` split into a
non-tick-valid mark-price constant and a new tick-valid
`BTC_LIKE_ADMITTED_PRICE` for request prices) but leaves every exact-identity
assertion in place (`base * basis == executed`, no rounding up, no
over-approval) — verified by direct diff read, not merely by the suite
passing.

**Package 5C — `PositionSizingService` authority: intact.** `core/position_sizing.py`
carries zero diff against the parent HEAD. `PositionSizingService` remains
venue-unaware by design; Package 5D's venue-precision gates apply strictly
after `RiskEngine.evaluate`'s admission, in `risk_check` and the
`_execute_paper_*` fill paths. Directly asserted by
`test_position_sizing_service_stays_venue_unaware` and
`test_risk_engine_stays_approve_reject_only` in
`tests/test_block5d_instrument_precision_contract.py`.

`RiskEngine` and `PositionSizingService` were not modified by this package.

## Known Non-Blocking Follow-ups / Limitations

**M2 — no rule-staleness bound (accepted, unresolved).** `retrieved_at` is
validated as present and non-empty, but nothing bounds how old a checked-in
rule may be before it is treated as stale. Because decision 2 deliberately
removes any live refresh, a venue tightening a `stepSize`/`tickSize`/
`minNotional` after `retrieved_at` is not detected until an operator
re-pulls `exchangeInfo` and updates the checked-in config. Operator refresh
cadence and staleness detection are a later operational package, not
Package 5D.

**M4 — no upper venue bound (accepted, unresolved).** `LOT_SIZE.maxQty`,
`NOTIONAL.maxNotional`, and `MARKET_LOT_SIZE` are not modelled;
`InstrumentRules` carries only the four minimum/step fields. This is
currently unreachable at the configured capital envelope
(`RiskPolicy.total_capital` is far below any of the five checked-in symbols'
`maxQty`/`maxNotional`), but it must be addressed before a larger capital
envelope or live execution makes an upper bound reachable.

Neither M2 nor M4 is claimed resolved by this document or by
`docs/evidence/block5d_owner_decisions.md`.

## PAPER / LIVE

Unchanged by this package. PAPER remains the default and LIVE authority
remains denied. Package 5D added venue instrument-precision admission and
fill-time gates; it did not modify the PAPER default, LIVE denial, or any
live-execution adapter path.

## Push Status

NOT PUSHED. No push, no merge, and — as of this document — no commit exists
for Package 5D. No file has been staged. Nothing beyond the file list below
has been touched by this package's work.

## Validation Evidence

All commands were run against the working tree in this session with an
isolated, ASCII `--basetemp` outside the repository (this host's default
tmp-path root is broken for pytest), per this project's standing testing
convention. No command modified, staged, or committed anything.

**Package 5D focused suite:** 127 passed.
`python -m pytest tests/test_block5d_instrument_precision_contract.py tests/test_block5b_single_sizing_authority.py -q --basetemp=C:/temp/pytest5d`

**Touched-test regression (remaining 8 adjacent files modified by this
package):** 289 passed.
`python -m pytest tests/test_block2_m1_reservation_admission_atomicity.py tests/test_durable_transaction_state.py tests/test_financial_quantity_identity_contract.py tests/test_nbf3_critical_risk_non_executable.py tests/test_nbf4_unsupported_risk_fail_closed.py tests/test_nbf6_adapter_enum_authenticity.py tests/test_phase3_risk_capital_foundation.py tests/test_phase4_execution_manager_runtime_cutover.py -q --basetemp=C:/temp/pytest5d_2`

**Architecture suite:** 15 passed.
`python -m pytest tests/architecture -q --basetemp=C:/temp/pytest5d_arch`

**Runtime distribution boundary suite:** 13 passed.
`python -m pytest tests/test_runtime_distribution_boundary.py -q --basetemp=C:/temp/pytest5d_dist`

**Full `tests/` suite:** 2148 passed in 65.82s.
`python -m pytest tests/ -q --basetemp=C:/temp/pytest5d_full`

The eight files in the touched-test-regression run were modified only to
supply a hermetic `InstrumentRuleset` fixture (via a new `instrument_rules`
constructor argument or a direct `manager.instrument_rules` assignment) so
their existing, unrelated scenarios keep passing under the new fail-closed
instrument-rules dependency — not to change what any of them assert.

## Exact Intended Package 5D File List

Total: **19 files** — 1 config, 3 core production, 3 packaging/architecture,
10 tests, 2 evidence documents.

Config (1, new):
- `config/instrument_rules.json`

Core production (3):
- `core/application.py`
- `core/execution_manager.py`
- `core/instrument_rules.py` (new)

Packaging / architecture / distribution metadata (3):
- `packaging/atlas_architecture_map.json`
- `packaging/atlas_runtime_closure.json`
- `packaging/atlas_runtime_distribution_manifest.json`

Tests (10):
- `tests/test_block2_m1_reservation_admission_atomicity.py`
- `tests/test_block5b_single_sizing_authority.py`
- `tests/test_block5d_instrument_precision_contract.py` (new)
- `tests/test_durable_transaction_state.py`
- `tests/test_financial_quantity_identity_contract.py`
- `tests/test_nbf3_critical_risk_non_executable.py`
- `tests/test_nbf4_unsupported_risk_fail_closed.py`
- `tests/test_nbf6_adapter_enum_authenticity.py`
- `tests/test_phase3_risk_capital_foundation.py`
- `tests/test_phase4_execution_manager_runtime_cutover.py`

Evidence (2):
- `docs/evidence/block5d_owner_decisions.md` (new)
- `docs/evidence/block5d_freeze_evidence.md` (new, this document)

No unrelated or generated files are in scope for this package; `git status
--short` at capture time contains no entries outside this list.

## Limits of This Evidence

Package 5D establishes a checked-in, static, fail-closed venue
instrument-precision authority covering `quantity_step`, `min_quantity`,
`min_notional`, and `price_tick` for BUY and SELL, startup and admission
gating, and a replay-safe rule-identity seal. It does not establish, and
this document does not claim: rule-staleness detection or an operator
refresh workflow (M2, accepted open), an upper venue bound
(`maxQty`/`maxNotional`/`MARKET_LOT_SIZE`, M4, accepted open), a live
`/exchangeInfo` integration, LIVE readiness, or production exchange
execution. This document also does not claim a committed or tagged
revision: it is a closure candidate awaiting explicit user approval to
stage and commit.
