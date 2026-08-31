# Atlas Block 6 / Package 6B Freeze Evidence — Venue Upper Bounds

## Status

Package 6B closure candidate: PASS.
BLOCKING: 0 remaining (0 introduced)
HIGH: 0 remaining (0 introduced)
MEDIUM NEW: 0 remaining (0 introduced)

Parent HEAD: `93821c7` ("feat: add venue rule freshness safety").

Nothing was pushed. PAPER remains the default and LIVE authority remains
denied; this package neither enables nor prepares live capital.

## The Limitation This Closes

Block 5D modelled the venue's lower bounds only and recorded limitation
**M4**: `LOT_SIZE.maxQty`, `NOTIONAL.maxNotional` and `MARKET_LOT_SIZE` were
not modelled at all. `docs/evidence/block5_final_closure.md` carried M4
forward as readiness gate **V1**, SAFE for bounded PAPER (no order can reach a
venue) and REQUIRED before scaled live capital, with the required work stated
as: model the maxima and "enforce them in the same fail-closed admission gate
that already enforces the lower bounds … *before* any live execution adapter
is wired, not after".

That is what this package does. It supersedes the V1 row of the Block 5
closure record; the historical record itself is left as written.

## Enforcement Points — Exact

Four, and no new layer: the two that already enforce the venue's lower bounds,
plus the two live-authority gates 6A established.

| # | site | what it enforces | when |
| --- | --- | --- | --- |
| 1 | `ExecutionManager.risk_check`, new-risk BUY block | the derived admission fill against every **modelled** bound | every mode, before any capital is reserved and before the admission is recorded |
| 2 | `ExecutionManager._resolve_reduction_quantity`, full exit and partial reduction | the holding, or the submitted reduction, against every modelled bound | every mode, before the paper side-effect boundary |
| 3 | `ExecutionManager._instrument_rules_startup_check` | **completeness**: every configured or held symbol must model all three bounds | startup, under live authority only |
| 4 | `ExecutionManager.live_execute`, ahead of the adapter step | **completeness** for the dispatched symbol | every live dispatch by a runtime that started live-authorized |

Sites 1 and 2 share one derivation — `InstrumentRules.upper_bound_violation`
— exactly as they already share `_resolve_base_fill` for what a fill is, so
the BUY and SELL gates cannot drift on what "too large" means.

Sites 3 and 4 are the fail-closed halves. Site 4 exists because site 3 covers
only the configured and held symbol universe: a request for any other symbol
reaches dispatch unchecked, and dispatch is the last point before an adapter
seam. Site 4 runs *after* the 6A freshness check, so with rules both stale and
unbounded the operator sees one deterministic reason.

An order above a maximum is **refused whole**. It is never capped to the
maximum, resized, or split into several orders — the mirror of the existing
rule that an order below a minimum is never raised to it. A refusal at site 1
leaves no reservation and no admission behind.

## Authority And Source Of Each Bound

| bound | venue filter | field | modelled |
| --- | --- | --- | --- |
| maximum quantity | `LOT_SIZE.maxQty` | `InstrumentRules.max_quantity` | yes, optional |
| maximum notional | `NOTIONAL.maxNotional` | `InstrumentRules.max_notional` | yes, optional |
| maximum market quantity | `MARKET_LOT_SIZE.maxQty` | `InstrumentRules.market_max_quantity` | yes, optional |
| `MARKET_LOT_SIZE.minQty` / `.stepSize` | — | — | **no** (below) |

`MARKET_LOT_SIZE` binds market orders only — that is what makes it distinct
from `LOT_SIZE` — so `market_max_quantity` is applied only when
`ExecutionRequest.order_type` is `MARKET`, the vocabulary the request contract
already normalizes to. A limit order at the same size clears it and is still
held to `LOT_SIZE.maxQty`.

The authority for the values themselves is unchanged from Block 5D: the
checked-in `config/instrument_rules.json`, whose entries must trace to a
verified venue source through the `source` / `source_version` / `retrieved_at`
provenance 6A now bounds the age of.

## Why The Bounds Are Optional, And Why The Config Is Unchanged

**No value was invented.** No verified `maxQty`, `maxNotional` or
`MARKET_LOT_SIZE.maxQty` for the five shipped symbols was available to this
package — obtaining one requires the venue metadata seam that does not exist
(6A: the only Binance client serves prices and candles, not `exchangeInfo`).
Fabricating a plausible maximum would be worse than modelling none: it would
read as verified for the rest of the system's life.

So the three fields are **optional in the schema and absent from the shipped
config**, and absence means exactly "this bound is not modelled":

- a bounded PAPER runtime is unaffected by it — the existing, recorded reason
  V1 was SAFE for bounded execution is that nothing leaves the paper book;
- a live-authorized runtime **fails closed on it** — it will not come online,
  and will not dispatch, until an operator publishes verified bounds.

Completeness is all three or nothing: a rule that bounds quantity but not
notional still admits an order the venue would refuse.

## LIVE vs PAPER Semantics

| | PAPER / bounded | LIVE-authorized (`mode == LIVE and live_execution_enabled`) |
| --- | --- | --- |
| bound present, order within it | admitted | admitted |
| bound present, order above it | **refused** (sites 1/2) | **refused** (sites 1/2) |
| bound absent | not enforced — behaviour identical to the parent commit | **fails closed**: startup halts, dispatch refuses |

The PAPER policy is unchanged and now explicit rather than implied: an
unmodelled maximum is not turned into a live-style rejection there. It is
pinned by `test_bounded_paper_runtime_without_modelled_maxima_is_unchanged`
(the shipped config still starts, admits and settles) and
`test_bounded_paper_runtime_is_not_held_to_the_live_bar`.

## Stable Refusal Codes

All are module constants in `core.instrument_rules`, carrying only which bound
was exceeded and by what — no account, key, or venue payload.

| code | raised at |
| --- | --- |
| `QUANTITY_ABOVE_VENUE_MAXIMUM` | BUY admission, partial SELL reduction |
| `QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM` | as above, market orders only |
| `NOTIONAL_ABOVE_VENUE_MAXIMUM` | BUY admission, partial SELL reduction |
| `FULL_EXIT_ABOVE_VENUE_MAXIMUM` | full exit — operationally distinct (the holding itself is unsellable in one order, for operator reconciliation), and names the bound it broke in `error_details.exceeded_bound` |
| `VENUE_UPPER_BOUNDS_UNAVAILABLE` | live startup halt reason, and live dispatch status/`error_code` |

`VENUE_UPPER_BOUNDS_UNAVAILABLE` is not in `SUCCESS_STATUSES`, so the Block 3
terminal classifier resolves a blocked dispatch as not-committed with no
durable consequence.

Boundary rule, stated once: comparisons are strict (`>`). An order exactly
*at* a venue maximum is admissible, because the venue accepts it.

## Schema And Migration Impact

- `config/instrument_rules.json` — **unchanged**. No migration is required by
  this package, and none is possible without verified values.
- `InstrumentRules` gains three optional `Decimal | None` fields. Validation
  is as strict as for the required fields when a value is present (exact,
  non-float, finite, positive) and additionally refuses a **contradictory**
  config at load: a maximum below the matching minimum admits nothing at all,
  so it fails when it is loaded rather than silently rejecting every request
  at runtime. Upper bounds are deliberately not required to be step-aligned —
  a venue may publish one that is not a whole multiple of its step, and the
  comparison stays exact either way.
- **Digest / rule identity.** A present bound is sealed into `digest`; an
  absent one is omitted from the canonical payload entirely. So a rule that
  models no upper bound hashes to exactly the digest it had before 6B —
  every existing admission key, evidence record and replay identity is
  untouched — while adding a bound to a symbol changes that symbol's identity,
  which is correct: its admission window changed, and a prior admission taken
  under a different maximum must be invalidated. The unbounded-rule digest is
  pinned in the 6A suite and was not touched by this package.
- `to_dict()` omits an unmodelled bound rather than writing null, so the
  on-disk shape of the shipped config is unchanged and a round-trip
  reproduces the same digest.
- The loader now **refuses an unrecognised field** in a `rules[]` entry. This
  is the hazard optional fields create: a misspelled `max_quanttiy` would
  otherwise read as "this venue has no maximum" and silently reopen the gate.

## Intentionally Not Implemented

- **No venue metadata fetch, and no refresh adapter.** Unchanged from 6A: no
  `exchangeInfo` seam exists, so none was invented. This package reads only
  the checked-in config.
- **No bound values for the shipped symbols**, for the same reason. The
  shipped config therefore models no maxima, which is asserted rather than
  assumed (`test_shipped_config_models_no_upper_bound_and_says_so`) because
  the live fail-closed gate depends on that premise.
- **`MARKET_LOT_SIZE.minQty` / `.stepSize` are not modelled.** Their values
  cannot be verified without the same missing seam, and the `LOT_SIZE`
  `min_quantity` / `quantity_step` Block 5D already enforces bound the same
  axis from below. The upper bound is the direction gate V1 named.
- **Reduce-only BUY** carries no admission-time fill derivation and is not
  covered, exactly as it is not covered by the existing venue *minimum* gate.
  The new coverage is the same shape as the coverage it extends: new-risk BUY
  admission and SELL reduction.
- **No live adapter seam.** `tests/test_block5l_block5_final_hardening.py`
  still fails the day one appears.

## Changed Files

| file | change |
| --- | --- |
| `core/instrument_rules.py` | three optional upper-bound fields + validation; conditional sealing and serialization; `upper_bound_violation`; `has_complete_venue_bounds`; refusal-code constants; `RULE_CONFIG_KEYS` unknown-field rejection; loader passthrough |
| `core/execution_manager.py` | upper-bound gate in BUY admission and in both SELL reduction paths; live completeness gate at startup and at dispatch; `_block_live_dispatch` extracted for the two pre-adapter refusals |
| `tests/test_block6b_venue_upper_bounds.py` | new — 24 test functions, 31 cases |
| `tests/test_block6a_venue_rule_freshness.py` | directly affected: the live-authorized fixture now installs non-binding upper bounds, so those tests keep isolating rule *age* rather than tripping the new completeness gate |
| `tests/test_block5l_block5_final_hardening.py` | gate 1 re-decided (below) |
| `packaging/atlas_runtime_closure.json` | regenerated: `core/venue_rule_freshness.py` added to the closure |
| `packaging/atlas_architecture_map.json` | regenerated: the same module assigned layer `L3` |
| `docs/evidence/block6b_venue_upper_bounds.md` | this record |

`config/instrument_rules.json` and `core/application.py` are unchanged.

### Architecture inventory — a 6A follow-on, closed here

The two `packaging/` artifacts are generated inventories, regenerated with the
repository's own tool (`tools/build_architecture_inventory.py closure --write`
and `map --write`), never hand-edited. Their diff is exactly one line each.

They are 6A's module, not 6B's, and the reason the drift appears only now is
worth recording: the inventory tool reads **tracked** files, so
`core/venue_rule_freshness.py` was invisible to it while it was still
untracked — including during 6A's own full-suite run, which was green. The
drift surfaced on the first full run after 6A was committed. Any future
package that adds a module to the runtime closure must regenerate these two
artifacts in the same commit.

### The Block 5L gate, re-decided

`test_instrument_rules_still_model_no_upper_venue_bound` was written to fail
the day an upper bound was added, forcing M4 to be re-decided rather than
silently inherited. It fired, as designed. It is replaced by
`test_instrument_rules_model_the_venue_upper_bounds`, which now fails the day
the bounds are removed or a fourth venue axis is modelled without this record
being revisited. The second 5L gate — no live adapter seam on
`ExecutionManager.__init__` — is unchanged and still enforced.

## Tests

`tests/test_block6b_venue_upper_bounds.py` — 24 test functions, 31 cases.

| contract | test |
| --- | --- |
| optional bounds; absence means unmodelled; completeness is all three | `test_upper_bounds_are_optional_and_absence_means_unmodelled` |
| the shipped config models no maximum (premise of the live gate) | `test_shipped_config_models_no_upper_bound_and_says_so` |
| a bound is sealed into rule identity | `test_adding_an_upper_bound_changes_rule_identity` |
| contradictory / non-positive / float bounds refused at load | `test_contradictory_or_inexact_bounds_are_refused_at_load` (6 cases) |
| a misspelled bound is refused, not read as absent | `test_a_misspelled_bound_is_refused_rather_than_read_as_absent` |
| config round-trip preserves bounds and digest; absent bounds omitted | `test_config_round_trip_preserves_bounds_and_identity` |
| boundary equality admissible, one step past refused | `test_an_order_exactly_at_every_bound_is_admissible` |
| each bound has its own stable reason and evidence | `test_each_bound_reports_its_own_stable_reason_and_evidence` |
| MARKET_LOT_SIZE binds market orders only | `test_market_lot_size_binds_market_orders_only` |
| exact under a hostile Decimal context | `test_bound_comparison_is_exact_under_a_hostile_decimal_context` |
| valid quantity/notional still admitted | `test_buy_within_every_bound_is_admitted` |
| boundary equality through the real admission path | `test_buy_exactly_at_the_bounds_is_admitted` |
| maxQty / maxNotional / MARKET_LOT_SIZE violation refused pre-reservation | `test_buy_above_a_venue_maximum_is_refused_before_reservation` (3 cases) |
| an oversized order is never capped to the maximum | `test_an_oversized_buy_is_never_capped_to_the_maximum` |
| order type reaches the admission gate | `test_limit_order_clears_the_market_bound_at_the_same_size` |
| full exit above the maximum fails closed, no mutation | `test_full_exit_above_the_venue_maximum_fails_closed_without_mutation` |
| partial reduction above the maximum fails closed, no mutation | `test_partial_reduction_above_the_venue_maximum_fails_closed_without_mutation` |
| a within-bounds SELL still settles | `test_a_sell_within_the_bounds_still_settles` |
| PAPER unchanged where no bound is modelled | `test_bounded_paper_runtime_without_modelled_maxima_is_unchanged` |
| PAPER is not held to the live bar | `test_bounded_paper_runtime_is_not_held_to_the_live_bar` |
| live startup halts on unmodelled maxima | `test_live_authorized_runtime_halts_when_maxima_are_unmodelled` |
| the same runtime starts once bounds are modelled | `test_the_same_runtime_starts_once_the_maxima_are_modelled` |
| live dispatch refuses an unbounded symbol before the adapter step | `test_live_dispatch_refuses_an_unbounded_symbol_before_the_adapter_step` |
| freshness gate still precedes the bounds gate | `test_the_freshness_gate_still_precedes_the_upper_bound_gate` |

## Validation Executed

| run | scope | result |
| --- | --- | --- |
| focused | `tests/test_block6b_venue_upper_bounds.py` | 31 passed |
| direct regression | 6B + 6A, instrument-rule, execution precision/venue, execution-manager runtime, terminal-status and bootstrap suites (20 files) | 615 passed |
| full suite (first) | `pytest tests/ -q` | 2418 passed, **3 failed** — the architecture-inventory drift above, in `tests/architecture/` and `tests/test_block4_market_data_architecture.py` |
| inventory validation | `tools/build_architecture_inventory.py check` | OK: closure matches, every live module has a layer, no forbidden dependency edges |
| full suite (final state) | `pytest tests/ -q` | **2421 passed** |

The first full run is recorded rather than elided: it is what caught the
inventory drift, and the final run is on the corrected state.

Run with `-p no:cacheprovider` and an ASCII `--basetemp`; the repository path
contains non-ASCII characters that break pytest's default cache and tmp roots
on this host.

## Readiness Gates After 6B

| gate | status |
| --- | --- |
| V1 venue upper bounds | **CLOSED for enforcement.** The bounds are modelled, sealed, and enforced fail-closed at admission and at both live gates. What remains is *data*: verified values for the shipped symbols, which require the venue metadata seam. Until they are published, live authority fails closed — which is the correct state, not an open gate. |
| V2 static venue-rule staleness | CLOSED by Package 6A (detection, reporting, fail-closed live enforcement); refresh mechanism deferred with the same missing seam. |

Both remaining deferrals are the same single dependency: a bounded venue
metadata adapter behind a reviewed boundary. That is the next package, and it
is what would let an operator publish verified maxima and a refresh cadence at
once.
