# Atlas Block 6 / Package 6C Freeze Evidence — Venue Metadata Adapter

## Status

Package 6C closure candidate: PASS.
BLOCKING: 0 remaining (0 introduced)
HIGH: 0 remaining (0 introduced)
MEDIUM NEW: 0 remaining (0 introduced)

Parent HEAD: `46df920` ("docs: ratify block3 execution safety stream in registry
v4.27").

Governance state: this package is work inside the `BLOCK3-EXECUTION-SAFETY`
substream ratified by `governance/current/ATLAS_MILESTONE_REGISTRY_v4.27.json`
under finding `GOV-DRIFT-002`. Nothing was pushed. PAPER remains the default,
production authority remains NONE and LIVE authority remains DENIED; this
package neither enables nor prepares live execution.

## The Gap This Closes

Packages 6A and 6B each stopped at the same missing piece, for the same
recorded reason:

- **6A (V2, refresh):** the freshness contract was built, but no refresh
  mechanism, because "the only Binance client serves prices and candles, not
  `exchangeInfo`". 6A wrote the integration contract a future adapter must
  satisfy and deferred it.
- **6B (V1, values):** the venue maxima were modelled, sealed and enforced,
  but the shipped config carries none, because no verified value could be
  obtained without that same seam. No number was invented.

6C is that seam: an operator-invoked adapter that turns an `exchangeInfo`
snapshot into a validated, atomically published `InstrumentRuleset` carrying
the 6B maxima and full provenance. It implements every clause of the 6A
integration contract — fetch outside the financial core, transform to
canonical rules, validate the complete ruleset before publishing, write
atomically to a runtime destination, keep the previous known-good ruleset on
failure, re-evaluate freshness after publish.

## What It Does Not Close

Stated plainly, because the distinction is the whole honesty of the package:

- **V1's data gap remains open.** 6C provides the mechanism; it does not
  supply verified values. `config/instrument_rules.json` is unchanged and
  still models no maxima. Real values require an operator to run this tool
  against a real `exchangeInfo` snapshot.
- **Runtime consumption is not wired.** Nothing in `AtlasApplication` loads a
  published artifact. The published document is deliberately in the same
  schema the runtime's own loader accepts, so wiring it is a small, explicit
  future step — but it is not taken here, which is why PAPER behaviour is
  unchanged by construction (see below).
- **No authenticated transport exists.** See the transport decision below.

## Boundary — Structural, Not Just Documentary

The adapter lives at `tools/venue_metadata_adapter.py`, alongside the other
operator entry points (`tools/bootstrap_financial_state.py` and the migration
tools), and follows their idiom: never called by `AtlasApplication`, no
`--force`, no `--repair`, no mode switch, no LIVE authority.

The dependency direction is `tools -> core`, never the reverse, and this is
verified rather than asserted:

- `python tools/build_architecture_inventory.py check` — run with the new
  module **staged** (so the inventory tool, which reads tracked files, can see
  it) — reports `OK: runtime closure matches (102 modules)`. The module is not
  in the runtime closure; nothing reachable from `main.py` or `web_app.py` can
  import it. No inventory artifact needed regeneration.
- `test_the_adapter_is_outside_the_runtime_closure` pins both halves: absent
  from `packaging/atlas_runtime_closure.json`, and imported by no `core/*.py`.

This is the 6A finding enforced structurally: the component that decides
whether an order may execute cannot acquire venue metadata, by accident or
otherwise.

## Publication Contract

`publish_venue_rules` performs exactly four steps, in this order:

1. **transform and construct** every rule through `InstrumentRules`, so all of
   5D's exactness rules and 6B's contradiction rules apply at the boundary;
2. **serialize and write a temporary file** beside the destination, flushed
   and `fsync`ed;
3. **re-load that temporary file through the runtime's own
   `load_instrument_ruleset`** and re-check, on the bytes actually written:
   the symbol set is exactly what was requested, every rule still satisfies
   `has_complete_venue_bounds`, every rule's `digest` is unchanged by the
   round trip, and `VenueRuleFreshnessService` assesses the set `FRESH`;
4. **`os.replace`** onto the destination.

Step 3 is what makes this a reviewed boundary rather than a write. There is no
path by which an unvalidated document becomes the destination: the destination
is never opened for writing at all.

**Atomicity and the previous known-good ruleset.** Validation completes before
the replace, so any failure leaves the existing artifact byte-identical, and
the temporary file is removed on every failure path (`except BaseException:
unlink; raise`). `test_a_failed_publication_preserves_the_previous_ruleset_byte_for_byte`
publishes a good ruleset, then fails a second publication, and asserts the
bytes are identical, no `.tmp` survives, and the survivor still loads with
complete bounds.

## What Is Refused

Nothing incomplete, inexact or invented is ever published. Each of these
refuses by name, publishes nothing, and leaves no temporary file:

| condition | reason |
| --- | --- |
| a bound published as `0` (the venue's "unlimited") | this contract models a bound as a positive Decimal and has no explicitly-unbounded representation; refusing beats publishing a silently unmodelled maximum |
| `NOTIONAL` filter absent (older `MIN_NOTIONAL`-only payloads) | no `maxNotional` exists to model; completeness is all three bounds or nothing |
| symbol status not `TRADING` | a symbol the venue is not trading is not an executable instrument |
| a requested symbol missing from the snapshot | partial coverage is not published |
| a maximum below its own minimum | 6B's contradiction rule, reached through the adapter |
| a bound delivered as a JSON float | cannot carry a venue step exactly |
| snapshot `serverTime` older than the freshness policy | below |
| snapshot `serverTime` in the future beyond the skew allowance | provenance defect |
| malformed / unreadable snapshot file | refused at the transport |

### The staleness-laundering property

Worth recording because it is not obvious. Freshness is assessed from
`retrieved_at`, which records when the *operator observed* the payload. The
adapter sets that to now — so publishing a six-month-old `exchangeInfo` file
today would stamp it observed-now and assess `FRESH`, laundering stale venue
data through a current observation.

`publish_venue_rules` therefore bounds the age of the **snapshot itself**: the
venue's own `serverTime` is held to the same `VenueRuleFreshnessPolicy` the
runtime will judge the published rules by. Pinned by
`test_a_stale_snapshot_cannot_be_laundered_by_a_fresh_observation`.

## Provenance

The published document carries a top-level `provenance` block alongside the
`rules[]` array the runtime loader reads:

| field | meaning |
| --- | --- |
| `adapter_version` | `6C.1` |
| `venue`, `source` | venue identity and the endpoint identity the operator names |
| `source_version` | the payload's `serverTime`, in ms |
| `server_time` | that `serverTime` as ISO-8601 UTC |
| `retrieved_at` | when the operator observed the payload |
| `published_at` | when this artifact was written |
| `transport` | `OPERATOR_SUPPLIED_FILE` |
| `snapshot_origin` | the snapshot path |
| `payload_digest` | sha256 of the exact bytes parsed |
| `verification_status` | `OPERATOR_SUPPLIED_SNAPSHOT_UNVERIFIED_TRANSPORT` |
| `symbol_count`, `venue_upper_bounds_modelled` | coverage summary |

Per-rule provenance (`source` / `source_version` / `retrieved_at`) is carried
on each rule as 5D requires and is therefore *enforced* by the loader; the
block above is operator metadata the loader ignores.

**The two-timestamp convention is the repository's own, verified not assumed.**
The checked-in config's `source_version` `1787161613022` decodes to
`2026-08-19T17:46:53Z` while its `retrieved_at` is `2026-08-19T17:47:48Z` — 55
seconds later. So `source_version` dates the venue payload and `retrieved_at`
dates the observation. The adapter reproduces exactly that shape and refuses
an observation that predates its own payload.

**`verification_status` is deliberately not a claim.** The file transport is
unauthenticated, so the adapter records what it knows — an operator-supplied
snapshot with a byte digest — and never asserts the payload was verified
against the venue.

## Transport Decision — No Network Client (deliberate)

6C implements a transport-agnostic adapter with exactly one transport: an
operator-supplied file (`load_exchange_info_snapshot`). No HTTP client was
written. The reasons, recorded so the owner can direct otherwise:

1. An HTTP client could not be executed or verified in this environment, so
   every correctness claim about it would be UNVERIFIED — the one thing this
   repository's evidence discipline does not permit.
2. Placing a live venue call in the repository puts a network dependency one
   configuration flag away from the runtime, which is precisely the coupling
   6A refused.
3. The operator already has to obtain the payload deliberately; handing over a
   file keeps the acquisition step auditable and the adapter offline.

`ExchangeInfoSnapshot` is the seam an authenticated HTTP transport would slot
into without changing transform, validation, atomicity or provenance. That is
a separate, reviewable package. `test_the_adapter_opens_no_socket` pins the
current state by poisoning every socket constructor during a full publication.

## PAPER Behaviour — Unchanged By Construction

No production file was modified by this package. `core/`, `config/`,
`packaging/` and `main.py` are untouched; the commit adds two new files. A
PAPER runtime therefore behaves exactly as it did at `ddd6c45`: it loads the
same checked-in ruleset, which still models no maxima, and the 6B posture is
unchanged — unmodelled maxima are not enforced in bounded execution and fail
closed under live authority.

`test_publishing_never_writes_the_checked_in_config` asserts the checked-in
config is byte-identical after a publication and still reports
`has_complete_venue_bounds is False`.

## Changed Files

| file | change |
| --- | --- |
| `tools/venue_metadata_adapter.py` | new — transport, transform, validation, atomic publication, verification, operator CLI |
| `tests/test_block6c_venue_metadata_adapter.py` | new — 22 tests |
| `docs/evidence/block6c_venue_metadata_adapter.md` | this record |

No existing file was modified. `config/instrument_rules.json`, `core/**`,
`packaging/**` are unchanged.

## Tests

`tests/test_block6c_venue_metadata_adapter.py` — 22 tests.

| contract | test |
| --- | --- |
| publication is loadable and carries maxima + provenance | `test_publication_is_loadable_and_carries_maxima_and_provenance` |
| venue-derived values drive the 6B gate (both maxima) | `test_published_rules_are_enforceable_by_the_block_6b_gate` |
| two-timestamp convention; observation cannot predate payload | `test_provenance_keeps_the_checked_in_two_timestamp_convention` |
| no temporary file survives a success | `test_publication_leaves_no_temporary_file_behind` |
| failed publication preserves the previous ruleset byte-for-byte | `test_a_failed_publication_preserves_the_previous_ruleset_byte_for_byte` |
| a valid re-publication replaces and reports it | `test_a_second_valid_publication_replaces_and_reports_it` |
| `0` (unlimited) refused by name | `test_a_zero_maximum_means_unlimited_and_is_refused_by_name` |
| missing `maxNotional` refused | `test_a_venue_without_a_maximum_notional_is_refused` |
| non-`TRADING` symbol refused | `test_a_symbol_the_venue_is_not_trading_is_refused` |
| missing requested symbol refused | `test_a_requested_symbol_missing_from_the_snapshot_is_refused` |
| maximum below its own minimum refused | `test_a_maximum_below_its_own_minimum_is_refused_by_the_rule_contract` |
| float bound refused | `test_a_float_bound_is_refused_rather_than_rounded` |
| stale snapshot cannot be laundered by a fresh observation | `test_a_stale_snapshot_cannot_be_laundered_by_a_fresh_observation` |
| future-dated snapshot refused | `test_a_future_dated_snapshot_is_refused` |
| malformed / absent snapshot refused at the transport | `test_a_malformed_snapshot_file_is_refused_at_the_transport` |
| the checked-in config is never written | `test_publishing_never_writes_the_checked_in_config` |
| no socket is opened by a full publication | `test_the_adapter_opens_no_socket` |
| the adapter is outside the runtime closure | `test_the_adapter_is_outside_the_runtime_closure` |
| verify reports bounds, freshness and provenance | `test_verify_reports_bounds_freshness_and_provenance` |
| verify refuses an unloadable artifact | `test_verify_refuses_an_unloadable_artifact` |
| operator CLI publish → verify round trip | `test_the_operator_cli_publishes_then_verifies` |
| operator CLI refuses with a non-zero exit | `test_the_operator_cli_refuses_with_a_nonzero_exit` |

## Validation Executed

| run | scope | result |
| --- | --- | --- |
| focused | `tests/test_block6c_venue_metadata_adapter.py` | **22 passed** |
| inventory | `tools/build_architecture_inventory.py check` (module staged) | OK — closure matches (102 modules), every live module has a layer, no forbidden edges |
| direct regression | 6C + 6B + 6A + 5D + 5L + `tests/architecture` + block4 architecture (7 targets) | **154 passed** |

Run with `-p no:cacheprovider` and an ASCII `--basetemp`.

**Full-suite assessment: not warranted for this package.** The blast radius is
two new files; no file that existed at `ddd6c45` was modified, so the
production tree the last full run validated (`2421 passed` at `ddd6c45`) is
byte-identical. The only shared artifacts a new module could disturb are the
architecture inventories, and those were checked directly — with the module
staged, so the check saw it. A full run would add the 22 new tests to a
provably unchanged suite. It should be run before the next package that
touches `core/`, or on request.

## Readiness Gates After 6C

| gate | status |
| --- | --- |
| V1 venue upper bounds | enforcement CLOSED (6B); **values still open** — the mechanism to publish verified ones now exists, but no verified snapshot has been supplied |
| V2 static venue-rule staleness | detection and fail-closed enforcement CLOSED (6A); **refresh mechanism now CLOSED** (this package), less an authenticated transport |

Remaining, in order: supply a real `exchangeInfo` snapshot and publish it;
wire the runtime to load a published artifact explicitly; and, if the owner
wants unattended refresh, add an authenticated HTTP transport behind
`ExchangeInfoSnapshot` as its own reviewed package.
