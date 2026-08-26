# Atlas Block 6 / Package 6A Freeze Evidence — Venue Rule Freshness

## Status

Package 6A closure candidate: PASS.
BLOCKING: 0 remaining (0 introduced)
HIGH: 0 remaining (0 introduced)
MEDIUM NEW: 0 remaining (0 introduced)

Parent HEAD: `2e3d7d8` ("feat: close block 5 execution hardening").

Nothing was pushed. PAPER remains the default and LIVE authority remains
denied; this package neither enables nor prepares live capital.

## The Limitation This Closes

Block 5D made the checked-in `config/instrument_rules.json` the sole,
process-immutable venue precision authority (owner decisions 1 and 9) and
recorded limitation **M2** against it:

> `retrieved_at` is validated as present and non-empty, but nothing bounds how
> old a checked-in rule may be before it is treated as stale.

`docs/evidence/block5_final_closure.md` carried M2 forward as
operational-readiness gate **V2** ("static venue-rule staleness"), classified
SAFE for the current bounded PAPER runtime and REQUIRED before scaled live
capital, with the required work stated as "an operator refresh cadence and
staleness detection … so a venue rule change is detected rather than
discovered by a rejected order".

Before this package the runtime could not answer "how old are the rules I am
trading on?" at all: `retrieved_at` was a non-empty string, nothing parsed it,
and no surface reported it.

## Provenance Schema — Unchanged By Design

**No field was added to `InstrumentRules`, and `config/instrument_rules.json`
was not modified.** The 5D per-rule schema already carries complete
provenance, and 6A derives freshness from it:

| field | role in 6A |
| --- | --- |
| `venue` | freshness is venue-scoped; a ruleset spanning two venues has no single answer and is refused |
| `source` | reported as the origin of the values (public endpoint identity, no payload, no secret) |
| `source_version` | reported alongside the source for operator correlation |
| `retrieved_at` | **the** freshness input: parsed, required timezone-aware, bounded against the clock |

This was a deliberate constraint rather than a convenience. `InstrumentRules`
seals every field it carries into `digest`, and that digest is Block 5D's rule
identity: it is written into the admission key (`_admission_key`) and into
execution evidence. Widening the rule schema would have changed every digest
and silently invalidated prior risk admissions. `tests/test_block6a_venue_rule_freshness.py::test_rule_identity_and_quantization_are_unchanged_by_6a`
pins a fixed rule's digest so any future widening fails there instead.

One piece of *set-level* metadata was added:
`InstrumentRuleset.schema_version` (defaulting to the loader's accepted
`INSTRUMENT_RULES_SCHEMA_VERSION = "1.0"`). The loader previously validated
the config's `schema_version` and then discarded it; the runtime now reports
which rule schema it is trading on. It is set-level precisely because it must
not reach the per-rule digest.

The checked-in rules remain byte-reproducible: no migration, no rewrite, no
new required config field.

## Freshness States

`core/venue_rule_freshness.py` defines four states and never a fifth
"probably fine":

| state | meaning |
| --- | --- |
| `FRESH` | every rule's `retrieved_at` parsed, and the oldest is within the configured maximum age |
| `STALE` | parsed, but the oldest exceeds the maximum age |
| `UNKNOWN` | there is no ruleset to evaluate (load failed, or an empty set) |
| `INVALID` | a `retrieved_at` is unparseable, is timezone-naive, is dated beyond the allowed future skew, or the ruleset spans multiple venues |

Two deliberate rules inside the evaluation:

- **The oldest rule in the set decides the age.** A partial operator refresh
  is not averaged away — the set is only as fresh as the rule left furthest
  behind.
- **A naive timestamp is `INVALID`, not assumed UTC.** Guessing the offset of
  a provenance stamp is exactly the silent assumption this gate exists to
  remove.

## Threshold Policy

The repository states no refresh cadence anywhere, so no numeric threshold is
derivable from repo facts. The threshold is therefore **configuration with a
documented default**, not a constant:

- `DEFAULT_MAXIMUM_RULE_AGE_SECONDS = 2_592_000` (30 days) — the monthly
  operator re-pull of `exchangeInfo` into `config/instrument_rules.json`. It
  is the cadence an operator can actually meet by hand, which matters because
  6A deliberately ships no automated refresh (below). It should be tightened
  the day a validated refresh adapter makes a shorter cadence achievable.
- `DEFAULT_FUTURE_SKEW_SECONDS = 300` — tolerance for genuine clock skew
  between the machine that produced the config and the machine running it.
  Beyond it, a future-dated artifact is a provenance defect (`INVALID`), never
  a negative age.
- `VenueRuleFreshnessPolicy` is injectable at the composition root:
  `AtlasApplication(venue_rule_freshness_policy=...)`. A policy that cannot be
  enforced (non-int, zero, negative) fails at construction rather than being
  replaced by a default at decision time.

**The boundary is closed on the fresh side.** Age exactly equal to the maximum
is `FRESH`; one second beyond is `STALE`. Stated once, so the same input can
never straddle two answers.

**The clock is injected.** `VenueRuleFreshnessService(policy, clock)` takes its
time source as a constructor argument; the composition root owns the wall
clock (`core.venue_rule_freshness.utc_now`, the single named place it is
read), and tests own it identically. No ambient `datetime.now()` was added to
the financial core. A clock returning a naive datetime is refused.

The shipped config (`retrieved_at` `2026-08-19T17:47:48Z` on all five symbols,
`source_version` `1787161613022`) evaluates `FRESH` under the default policy
at the time of this record, and becomes `STALE` on 2026-09-18 unless an
operator re-pulls it. That transition is the intended signal, not a defect:
no test asserts against it, because every freshness assertion in the suite
uses an injected clock.

## PAPER / Bounded Behavior

A bounded runtime **continues** on `STALE` static rules, and does so loudly:

- `allow_stale_bounded_execution` defaults `True`. Rationale from current repo
  facts: a bounded run moves only the paper book, and `docs/evidence/block5_final_closure.md`
  already classifies V2 as SAFE for it because the checked-in config is the
  only source a PAPER book can act on.
- The state is reported on **both** operational surfaces
  (`ExecutionManager.health()` and `.status()`), and `start()` logs a WARNING
  naming the status, age, threshold and observed timestamp. Nothing is
  swallowed.
- Setting `allow_stale_bounded_execution=False` makes a bounded runtime halt
  on stale rules too. The switch is load-bearing, not decorative
  (`test_bounded_paper_runtime_halts_when_policy_withdraws_stale_tolerance`).
- The switch covers `STALE` **only**. `UNKNOWN` and `INVALID` fail closed in
  bounded mode as well: there is no path from "cannot tell" to unconstrained
  execution.

Quantization, tick/step admission, and every other Block 5D gate are
unchanged. A bounded run on stale rules executes against exactly the rules it
already had — it does not fall back to a permissive quantum, and a symbol with
no rule remains `INSTRUMENT_RULES_UNAVAILABLE`.

## LIVE / Scaled-Live Fail-Closed Behavior

`ExecutionManager.live_authorized` is the conjunction `mode == LIVE and
live_execution_enabled`. LIVE mode alone is not authority: with live execution
disabled, `live_execute` denies every request before any adapter step, so no
venue rule — fresh or stale — can be acted on.

Two enforcement points, both fail-closed, neither reachable by a bounded run:

1. **Startup.** `_instrument_rules_startup_check` now ends with the freshness
   gate. A live-authorized runtime whose rules are `STALE`, `UNKNOWN` or
   `INVALID` does not come online: `execution_halted`, `recovery_required`,
   and `halt_reason` ∈ {`VENUE_RULES_STALE`, `VENUE_RULES_FRESHNESS_UNKNOWN`,
   `VENUE_RULES_PROVENANCE_INVALID`}. This runs after the existing 5D checks,
   so a missing rule still halts as `INSTRUMENT_RULES_UNAVAILABLE` first.
2. **Dispatch.** Rules are immutable for the life of a process (5D decision 9)
   but their *age* is not. A runtime that came online holding live authority
   re-checks freshness on every `live_execute`, ahead of the adapter step, and
   refuses with status `VENUE_RULES_NOT_FRESH` carrying the gate reason as
   `error_code` and the full freshness report in `data`. `VENUE_RULES_NOT_FRESH`
   is not in `SUCCESS_STATUSES`, so the Block 3 terminal classifier resolves it
   as not-committed with no durable consequence.

The dispatch re-check is scoped to `_live_authorized_at_start` deliberately. A
runtime that had its live flag flipped after startup never passed the live
startup gate at all and is already denied for want of an approved adapter, so
nothing reaches a venue either way; scoping it this way keeps the existing
Block 3 denial vocabulary (`LIVE_DISABLED`, `LIVE_ADAPTER_NOT_IMPLEMENTED`)
exactly as it was rather than making an unrelated test outcome depend on the
wall-clock age of the checked-in config.

**Nothing silently falls back.** Every non-`FRESH` outcome under live
authority is a refusal with a named reason.

## Refresh Adapter Decision — NOT IMPLEMENTED (deliberate)

Package 6A builds **no** network refresh path. The narrow inspection found no
venue *metadata* seam to build one behind: the only Binance client in the
repository (`atlas_finance/market_data/binance_public_provider.py`) serves
prices and candles (`/api/v3/ticker`, `/api/v3/klines`) and has no
`exchangeInfo` surface. Per the package contract, a network stack was not
invented for 6A.

`test_no_refresh_adapter_exists_in_the_freshness_authority` pins the decision:
the freshness authority imports no HTTP or socket machinery, so the day a
refresh adapter is introduced it must be wired through a reviewed boundary
rather than appearing inside the financial core.

Integration contract for the next runtime package, when a metadata seam
exists:

- fetch outside the financial core, behind an adapter/tool boundary;
- transform the venue response into canonical `InstrumentRules` and validate
  the **complete** ruleset before publishing;
- write atomically to a runtime cache destination, never mutating the
  checked-in config in place;
- keep the previous known-good ruleset until the replacement validates — no
  partial update;
- re-evaluate freshness through `VenueRuleFreshnessService` after publish, so
  the gate and the health surface see the new provenance.

## Observability

`ExecutionManager.health()["venue_rules"]` and
`.status()["venue_rules"]` (and therefore `AtlasApplication.status()`
["execution"]) carry the full report, re-evaluated per call so a long-running
process can be seen crossing the threshold:

| field | example |
| --- | --- |
| `status` | `FRESH` / `STALE` / `UNKNOWN` / `INVALID` |
| `venue` | `BINANCE` |
| `schema_version` | `1.0` |
| `symbol_count` | `5` |
| `source` | `https://api.binance.com/api/v3/exchangeInfo` |
| `source_version` | `1787161613022` |
| `observed_at` | oldest `retrieved_at` in the set, ISO-8601 UTC |
| `age_seconds` | measured age |
| `maximum_age_seconds` | threshold it was measured against |
| `evaluated_at` | the injected clock's reading |
| `reason` | the gate reason, or `null` when `FRESH` |

No raw exchange payload and no secret is exposed: `source` is the public
endpoint identity already checked into the config.

## Changed Files

| file | change |
| --- | --- |
| `core/venue_rule_freshness.py` | new — states, policy, report, gate decision, service |
| `core/instrument_rules.py` | `INSTRUMENT_RULES_SCHEMA_VERSION`; set-level `InstrumentRuleset.schema_version`; loader carries it through |
| `core/execution_manager.py` | freshness service injection; `live_authorized`; `assess_venue_rule_freshness()`; startup gate; live dispatch re-check; `venue_rules` on `health()`/`status()` |
| `core/application.py` | `venue_rule_freshness_policy` composition parameter; builds the single shared service; logs freshness at load; injects it into `ExecutionManager` |
| `tests/test_block6a_venue_rule_freshness.py` | new — 26 test functions, 29 cases |
| `docs/evidence/block6a_venue_rule_freshness.md` | this record |

## Tests

`tests/test_block6a_venue_rule_freshness.py` — 26 test functions (29 cases,
one is parametrized over four malformed timestamps), all clock-injected;
no assertion depends on the wall clock or on how old the checked-in config is
on the day the suite runs.

| contract | test |
| --- | --- |
| A. fresh rules → `FRESH` | `test_rules_inside_the_threshold_are_fresh` |
| B. age past threshold → `STALE` | `test_rules_past_the_threshold_are_stale` |
| C. missing ruleset → `UNKNOWN` | `test_absent_rules_are_unknown_not_assumed_fresh` |
| C. a rule without provenance cannot exist | `test_a_rule_without_provenance_cannot_be_constructed_at_all` |
| D. malformed / naive provenance → `INVALID` | `test_malformed_provenance_is_invalid` (4 cases) |
| D. future beyond skew → `INVALID`; inside skew → age 0 | `test_provenance_dated_beyond_the_skew_allowance_is_invalid` |
| D. multi-venue set → `INVALID` | `test_a_multi_venue_ruleset_has_no_single_freshness_answer` |
| E. boundary exactly at threshold | `test_threshold_boundary_is_closed_on_the_fresh_side` |
| oldest rule decides the age | `test_the_oldest_rule_in_the_set_decides_the_age` |
| F. injected clock determinism; naive clock refused | `test_freshness_is_a_pure_function_of_the_injected_clock` |
| unenforceable policy refused at construction | `test_policy_rejects_a_threshold_it_cannot_enforce` |
| G. stale/unknown/invalid cannot pass the live gate | `test_only_fresh_rules_pass_the_live_gate` |
| G. live-authorized startup halts on stale rules | `test_live_authorized_runtime_halts_on_stale_venue_rules` |
| G. live dispatch refuses rules that aged mid-run | `test_live_dispatch_refuses_rules_that_went_stale_during_the_run` |
| H. fresh rules pass the gate | `test_fresh_rules_pass_the_live_gate` |
| H. live-authorized startup is clean on fresh rules | `test_live_authorized_runtime_starts_clean_on_fresh_venue_rules` |
| I. bounded mode never falls back on `UNKNOWN`/`INVALID` | `test_bounded_execution_never_falls_back_from_unknown_or_invalid_rules` |
| paper/bounded: continues, reports `STALE` on both surfaces | `test_bounded_paper_runtime_reports_stale_rules_without_halting` |
| paper/bounded: policy can withdraw stale tolerance | `test_bounded_paper_runtime_halts_when_policy_withdraws_stale_tolerance` |
| stale tolerance applies to `STALE` only | `test_bounded_execution_may_continue_on_stale_rules_only_by_policy` |
| one shared freshness authority in the composition root | `test_the_composition_root_wires_one_freshness_authority` |
| live authority = mode ∧ enablement | `test_live_authority_is_the_conjunction_of_mode_and_enablement` |
| J. rule digest + quantization unchanged | `test_rule_identity_and_quantization_are_unchanged_by_6a` |
| J. shipped config still loads; default cadence pinned | `test_the_shipped_config_still_loads_and_now_reports_its_schema` |
| K. no socket is opened by validation, assessment or gating | `test_ordinary_rule_validation_and_freshness_touch_no_network` |
| L. no refresh adapter inside the freshness authority | `test_no_refresh_adapter_exists_in_the_freshness_authority` |

## Validation Executed

| run | scope | result |
| --- | --- | --- |
| focused | `tests/test_block6a_venue_rule_freshness.py` | 29 passed |
| direct regression | 6A + instrument-rule, execution precision/venue, execution-manager runtime, terminal-status, and bootstrap suites (19 files) | 584 passed |
| full suite | `pytest tests/ -q` | see below |

Commands were run with `-p no:cacheprovider` and an ASCII `--basetemp`; the
repository path contains non-ASCII characters that break pytest's default
cache and tmp roots on this host.

## Remaining Open — Gate V1 (unchanged by this package)

Venue **upper** bounds remain unmodelled: `LOT_SIZE.maxQty`,
`NOTIONAL.maxNotional`, and `MARKET_LOT_SIZE`. `InstrumentRules` still carries
only the four minimum/step fields (Block 5D M4). This stays SAFE for the same
reason the closure record gave — `live_execute` refuses for want of an
approved adapter even with `live_execution_enabled=True`, so no order reaches
a venue — and it stays REQUIRED before scaled live capital.
`tests/test_block5l_block5_final_hardening.py` continues to enforce the gate
in both directions (an upper-bound field appearing, or a live adapter seam
appearing, fails there), and 6A did not touch it.

Gate V2 (static venue-rule staleness) is **CLOSED** by this package for
detection, reporting, and fail-closed live enforcement. What V2's "operator
refresh cadence" still lacks is the *mechanism* to refresh — that is the
documented refresh-adapter integration above, deliberately deferred to the
runtime package that has a venue metadata seam to build it behind.
