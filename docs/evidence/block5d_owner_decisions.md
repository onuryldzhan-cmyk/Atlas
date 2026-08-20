# Atlas Block 5 / Package 5D Owner Decisions

## Status

This document records the owner decisions that scope Package 5D — venue
instrument precision and provenance — and the decisions made in the
subsequent H1/M1/M3 remediation that followed an independent review of the
original package. It is a decision record, not a freeze-evidence document:
it does not itself certify Package 5D closure.

## Package

Block 5 / Package 5D — Venue Instrument Precision Contract
(`core/instrument_rules.py`, `config/instrument_rules.json`,
`core/execution_manager.py`, `core/application.py`).

## Source Revision

Branch: `feat/block3-execution-safety`.

Parent HEAD at the time these decisions were recorded:
`6ce5153f895ee4ba7e0c082a8705896a3b7e6f73` —
`feat: add upstream position sizing authority`.

## Decisions

1. **Static config is the runtime authority.** The checked-in
   `config/instrument_rules.json` is the sole source of venue instrument
   precision for a run. `AtlasApplication._build_instrument_rules` loads it
   once at process startup and injects the resulting `InstrumentRuleset`
   into `ExecutionManager`; `ExecutionManager` consumes it but never
   constructs, mutates, or invents an entry.

2. **No live refresh.** There is no `/exchangeInfo` fetch and no mid-run
   refresh. Rules are immutable for the lifetime of one process. A rules
   change is simulated only in tests, to prove the digest seal described in
   decision 8 actually invalidates a prior admission if that invariant were
   ever violated.

3. **A missing rule for a configured/trade-enabled symbol halts startup.**
   `ExecutionManager._instrument_rules_startup_check` checks both the
   composition root's configured trade-enabled symbols and every symbol the
   durable book currently holds a position in. Either kind of symbol without
   a rule halts `start()` fail-closed with `INSTRUMENT_RULES_UNAVAILABLE`.

4. **A missing rule at admission fails closed.** Independently of the
   startup gate, `risk_check` refuses any request for a symbol with no
   checked-in rule as `INSTRUMENT_RULES_UNAVAILABLE`, before reservation and
   before any side effect.

5. **A legacy non-step-aligned durable position halts, never mutates.** A
   held position whose durable `base_quantity` is not an exact multiple of
   its symbol's `quantity_step` halts startup as
   `INSTRUMENT_RULES_POSITION_MISALIGNED`. It is never floored, rounded, or
   written off; only an operator resolves it.

6. **No 1e-8 executable fallback.** `ExecutionManager.BASE_QUANTITY_QUANTUM`
   (a runtime representation bound with no venue authority behind it) is
   removed entirely. Every quantity derivation — BUY sizing, the BUY
   fill-time backstop, and SELL reduction sizing — floors to the venue's own
   `quantity_step` via `floor_to_step`, and a symbol with no rule has no
   fallback quantum to fall back to.

7. **A notional-below-minimum refusal is terminal only for that request.**
   Refusing an admission or a reduction as below `min_notional` halts
   nothing else: a later independent request (a new `request_id`, e.g. the
   next market-loop tick with an updated price or allocation) is evaluated
   fresh against the same rule.

8. **Price-tick misalignment refuses, never rounds.** A request price that
   does not land exactly on the venue's `price_tick` is refused as
   `PRICE_TICK_MISALIGNED`. The observed/request price itself is never
   mutated, rounded, or snapped to the nearest valid tick anywhere in the
   admission or execution path.

9. **`config/instrument_rules.json` ships with the runtime.** The
   distribution manifest's `config/**` exclusion is narrowed so that this
   file — and no other file under `config/` — is selected into the runtime
   distribution closure alongside `core/instrument_rules.py`.

10. **SELL is subject to the same venue minimums as BUY** (this remediation,
    following the H1 finding that the original package enforced
    `min_quantity`/`min_notional` on BUY only). `_resolve_reduction_quantity`
    now enforces, before any side effect:
    - A **partial** reduction's floored `base_quantity` must itself clear
      `min_quantity`, and its notional at the same exposure basis
      (`base_quantity * mark_price`) must clear `min_notional` —
      `QUANTITY_BELOW_VENUE_MINIMUM` / `NOTIONAL_BELOW_VENUE_MINIMUM`, the
      same reason vocabulary the BUY path already uses.
    - A partial reduction may never strand a nonzero durable remainder that
      is itself below `min_quantity` or `min_notional` —
      `REDUCTION_STRANDS_SUBMINIMUM_REMAINDER`. The request is refused
      outright; it is never silently upgraded into a full close, and the
      reduction quantity is never rounded up to avoid the remainder.
    - A **full exit** still returns the exact durable `base_quantity` byte
      for byte (Package 5B), but that exact quantity is not exempt from
      venue minimums: if the durable holding itself — quantity or notional —
      is below what the venue would accept as a close order, the exit fails
      closed as `FULL_EXIT_BELOW_VENUE_MINIMUM` rather than being floored,
      rounded up, or written off. Resolving it is operator/dust
      reconciliation, out of Package 5D's scope.
    - The BUY fill-time backstop in `_execute_paper_buy` re-asserts
      `min_quantity`/`min_notional` against the fee-adjusted fill (the
      admission-time check necessarily used `fee = 0`, since the fee is not
      known until the executing component reports it): a component-reported
      fee that pushes the executable fill below either minimum now fails
      closed, via the existing post-side-effect failure machinery, before
      durable settlement — reusing the `QUANTITY_BELOW_VENUE_MINIMUM` /
      `NOTIONAL_BELOW_VENUE_MINIMUM` reason vocabulary.
    - No SELL-side or fee-adjusted-BUY venue-minimum failure reserves,
      settles, or mutates durable state: every SELL check above runs before
      `ExecutionManager._mark_execution_side_effect`, and a BUY fill-time
      failure is classified by the same side-effect boundary every other
      post-mutation failure already uses, so `_finalize_durable_financial_state`
      is never reached.

## Digest canonicalization (M3 remediation)

`InstrumentRules._compute_digest` normalizes each authoritative Decimal
field (`Decimal.normalize()`) before serializing it into the canonical JSON
payload that is hashed. Two rules that are economically identical but
differ only in the checked-in config's cosmetic trailing-zero
representation (`"5"` vs. `"5.00"`, `"0.00001"` vs. `"0.00001000"`) now
produce the same digest. The value each field carries everywhere else —
`to_dict()`, every execution-path computation, every serialized fill string
— is unchanged; only the digest's canonical representation is affected.

## Accepted Package 5D limitations

These are recorded as accepted, out-of-scope limitations for Package 5D —
not resolved by this remediation, and not to be represented as resolved in
any later evidence document.

**M2 — no rule-staleness bound.** `retrieved_at` is validated as present and
non-empty, but nothing bounds how old a checked-in rule may be before it is
treated as stale. Because decision 2 deliberately removes any live refresh,
a venue tightening a `stepSize`/`tickSize`/`minNotional` after
`retrieved_at` is not detected until an operator re-pulls `exchangeInfo` and
updates the checked-in config. Operator refresh cadence and staleness
detection are a later operational package, not Package 5D.

**M4 — no upper venue bound.** `LOT_SIZE.maxQty`, `NOTIONAL.maxNotional`,
and `MARKET_LOT_SIZE` are not modelled; `InstrumentRules` carries only the
four minimum/step fields. This is currently unreachable at the configured
capital envelope (`RiskPolicy.total_capital` is far below any of the five
checked-in symbols' `maxQty`/`maxNotional`), but it must be addressed before
a larger capital envelope or live execution makes an upper bound reachable.
