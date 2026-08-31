# Atlas Block 5 / Package 5G Freeze Evidence

## Status

Package 5G closure candidate: PASS
BLOCKING: 0
HIGH: 0
MEDIUM NEW: 0

## Package

Block 5 / Package 5G — Closed Position Lifetime Identity
(`core/execution_manager.py`, `core/execution_portfolio_foundation.py`).

## Objective

5F's own evidence recorded, as an explicitly out-of-scope finding (F3), that
`ExecutionPortfolioFoundation._close` keys `closed_positions` by
`position_id` alone, and that `ExecutionManager` minted only a bare
`"long:" + symbol` constant — identical for every re-entry of the same
symbol. 5G closes F3: a durable per-lifetime archive requires a
lifetime-scoped identity, not a symbol-scoped one.

## Root Cause

`ExecutionManager._execute_paper_buy` minted a flat-book BUY's position
identity as `"long:" + request.symbol` — a constant depending only on the
symbol, reused verbatim by every future flat-book re-entry of that symbol.
`ExecutionPortfolioFoundation._close`'s full-exit branch then wrote
`state["closed_positions"][result.position_id] = closed` unconditionally.
Because every lifetime of a given symbol shared the identical identity, the
Nth full close's write silently replaced the (N-1)th's dict entry at that
key — losing its `gross_pnl`, `entry_fees`, `exit_price`, `opened_at`, and
`closed_at` with no error, no exception, and no recovery flag. Live position
state, book-level cash/fees/realized_gross_pnl, and idempotency were all
unaffected — only the per-lifetime historical archive was destroyed.

### Real reproduction (pre-fix, isolated `tempfile` state directory)

Four BUY → full-SELL cycles at distinct prices, driven through the real
`AtlasApplication` → `ExecutionManager.execute()` PAPER pipeline:

```
cycle 0: entry=10 exit=12 -> gross_pnl=20.0
cycle 1: entry=20 exit=15 -> gross_pnl=-25.0
cycle 2: entry=5  exit=9  -> gross_pnl=80.0
cycle 3: entry=40 exit=41 -> gross_pnl=2.50

closed_positions records surviving: 1
closed_positions keys: ['long:BTCUSDT']
```

4 completed lifetimes → 1 surviving record; restart reloaded cleanly
(`ready=True`) with the same single record — the loss was permanent and
silent. `realized_gross_pnl` (book-level accumulator, `77.50` = sum of all
four) was exact throughout; only the archive was wrong.

## Design Evolution During Construction (recorded accurately, not smoothed over)

This package's identity contract went through two designs before freeze.
Both are recorded here because the second was discovered *during* this
package's own construction, by its own test suite, before anything was
committed — the process that is supposed to catch exactly this kind of
conflict worked as intended.

**Design 1 (raw embed).** `long:<symbol>:<opening_request_id>` — the
opening `request_id` embedded directly. This closed the overwrite defect
(5G-1/5G-2) but required the identity charset to be *widened* one character
beyond `data_layer.models`' canonical `_ID` pattern, to admit `"|"`:
`core/market_loop.py` mints every real, automated BUY's `request_id` as the
deterministic fingerprint `f"{symbol}|{candle_identity}|{action}"`, which
contains `"|"` and has no pre-existing charset constraint anywhere in the
repository (`ExecutionManager` only requires `request_id` non-blank). Under
the *unwidened* charset, every real MarketLoop-driven BUY would have failed
closed — a regression caught immediately by four tests in sibling suites on
the first full regression run
(`test_block5a_risk_state_plumbing.py::test_market_loop_buy_executes_once_the_decision_is_sized`,
`test_block5c_upstream_sizing_authority.py::test_real_market_loop_buy_is_sized_and_settles_end_to_end`,
`::test_real_market_loop_writes_only_the_configured_state_root`,
`::test_completed_replay_after_restart_uses_durable_cache_not_sizing`).
Widening the local charset by exactly the one character in conflict fixed
the regression, but left the minted identity relational-incompatible with
`data_layer.models`' own *unwidened* contract for any `request_id`
containing `"|"` — i.e., for essentially every real, live BUY. That was
recorded as 5G-3 CLOSED-with-a-caveat, not a full close.

**Design 2 (SHA-256 digest, final).** `long:<symbol>:
<sha256(opening_request_id).hexdigest()>` — the opening `request_id` is
hashed, never embedded raw. A SHA-256 hex digest is always exactly 64
lowercase hex characters (`[0-9a-f]`), a strict subset of
`data_layer.models`' own charset, regardless of what `request_id` contains
or how long it is. This removes the coupling between `request_id`'s shape
and the identity's validity entirely: no widening is needed, no
special-casing per caller convention is needed, and the identity is
*always* relational-clean — closing 5G-3 unconditionally rather than only
for `request_id` shapes that happened to already conform.

## Final Identity Contract

**Format:** `long:<symbol>:<sha256(opening_request_id).hexdigest()>`, minted
by `mint_long_position_id(symbol, request_id)`
(`core/execution_portfolio_foundation.py`) at the single site that used to
mint `"long:" + symbol` (`ExecutionManager._execute_paper_buy`).

**Determinism:** pure function of `(symbol, request_id)` — no `uuid`, no
clock, no random component; `hashlib.sha256` is a pure, deterministic
function of its input bytes. The same opening request always re-derives the
same identity: given the same `request_id` — already durably recorded in
the transaction journal and the idempotency store — anyone can recompute
the identical digest and thus the identical `position_id`, satisfying
`data_layer.projection_replay`'s requirement that a projected identity be
reproducible from confirmed evidence alone. `request_id` is already the
value `ExecutionPortfolioFoundation.apply_confirmed` enforces as a globally
unique idempotency key (`IDEMPOTENCY_IDENTITY_CONFLICT`), so the composite
introduces no new uniqueness invariant — only a naming convention layered
over an existing one.

**Charset:** `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$` — `data_layer.models`'
generic `_ID` pattern, byte-for-byte, unwidened. No longer needs widening:
the digest portion is always valid under it by construction.

**Length:** fixed at `len("long:") + len(symbol) + len(":") + 64` for any
`request_id` whatsoever — `77` characters for a 7-character symbol like
`BTCUSDT`, comfortably inside the 128-character bound regardless of
`request_id`'s own length (proven with a 100,000-character `request_id`).

**No raw-`request_id` dependency:** `request_id`'s own charset and length
carry no constraint relevant to this mint site any more — its only
pre-existing validation (non-blank, `ExecutionManager`) is unchanged and
untouched. `mint_long_position_id` owns solely the safe, deterministic
*projection* of `request_id` into a durable identity — never a truncation
or sanitization of the raw value into that identity; hashing is neither.

**Lifecycle semantics (unchanged from pre-5G, now on the new identity):**
- *Add-to-position*: a BUY against an existing live position reuses
  `existing["position_id"]` verbatim and never mints — untouched code path,
  proven still correct (`ExecutionPortfolioFoundation._open`'s
  `DUPLICATE_OPEN_POSITION` guard already required this).
- *SELL*: reads `position["position_id"]` off the live durable position and
  never constructs one — untouched code path
  (`ExecutionManager._execute_paper_sell`).
- *Partial reduction*: writes no `closed_positions` entry; the live
  position keeps its identity.
- *Full close*: archives exactly once, under the live position's identity.
- *One live LONG per symbol*: unchanged — `state["positions"]` remains
  keyed by symbol, untouched by this package.

**Collision guard (unchanged from the first round):**
`ExecutionPortfolioFoundation._close` checks
`result.position_id in state["closed_positions"]` immediately before the
archive write and raises `CLOSED_POSITION_IDENTITY_CONFLICT` if it is
already present, instead of overwriting. The raise propagates through
`apply_confirmed`'s existing `except Exception: self._recovery_reason =
"FINANCIAL_TRANSITION_RECOVERY_REQUIRED"; raise` — the identical fail-closed
mechanism every other integrity violation in this module already uses.

**Durable-state validation (unchanged from the first round):**
`_validate_state` requires, for every `closed_positions` entry, that
`closed_record["position_id"] == dict_key` and that the key matches the
identity charset above — checked with a locally-defined pattern rather than
importing `data_layer.models` into this L1 module (an L1-to-L1 cross-domain
import; kept local and equivalent instead). `ExecutionManager` imports the
`mint_long_position_id` function from this same module rather than
duplicating the pattern, the same precedent `SETTLEMENT_CONTEXT_PRECISION`'s
existing reuse already set.

**Preflight check (unchanged in structure, updated in what it actually
guards):** before `ExecutionManager._execute_paper_buy` crosses the
paper-book side-effect boundary, a flat-book BUY's prospective identity is
validated; a mint failure is rejected with `INVALID_POSITION_IDENTITY` — a
normal `FAILED` result, capital cleanly released — before any side effect,
rather than after. Under the final (hashed) design this can no longer
actually fail due to `request_id`'s content or length — only a malformed
`symbol` reaching this point could trigger it, the same
always-should-be-unreachable defense-in-depth the instrument-rules check
three lines above it already applies to its own rule.

## Migration / Backward Compatibility

**No existing record is rewritten, ever.** A pre-5G live position carrying
`position_id = "long:<symbol>"` keeps that exact identity for the remainder
of its lifetime: `_open`'s `DUPLICATE_OPEN_POSITION` guard already compares
only against `current["position_id"]`, and `ExecutionManager` echoes it back
unchanged on every add-to-position BUY and every SELL. It closes exactly
once, into `closed_positions["long:<symbol>"]`, exactly as before. Only that
position's *next* lifetime (the next flat-book BUY on that symbol) mints the
new, hashed composite form. No migration step, no schema bump —
`SCHEMA_VERSION` stays `1`; no field was added to or removed from the
persisted shape. Proven directly by
`test_legacy_bare_symbol_position_id_closes_once_and_next_lifetime_mints_composite`:
a hand-seeded legacy position reloads, closes under its own id, and the
archive is untouched by the new lifetime that follows it.

**Operator environment fact:** `memory_data/execution_financial_state.json`
does not exist in this environment at the time of writing (only
`execution_transaction_journal.json`, `execution_idempotency.json`, and
`audit/` are present under `memory_data/`) — there are zero live positions
and zero closed-position records to migrate here today.

## Findings Closed

**5G-1 (HIGH, CLOSED).** `closed_positions` silent overwrite — the root
cause above. Closed by the deterministic composite identity plus the
fail-closed collision guard.

**5G-2 (HIGH, CLOSED).** No durable authority could attribute a confirmed
execution to a specific lifetime after a symbol was re-traded. Closed as a
direct consequence of 5G-1's fix: the idempotency record's `position_id` is
now lifetime-distinct.

**5G-3 (MEDIUM, fully CLOSED — not deferred, not partial).** The latent
`atlas_positions` `PRIMARY KEY` collision risk in the dormant relational
projection layer. Design 1 closed this only for `request_id` shapes that
happened to already be `data_layer`-clean (an unconditional collision
before 5G, a conditional gap after Design 1). Design 2 (SHA-256) closes it
unconditionally: every identity this package can ever mint — for any
`request_id` whatsoever, proven across `HOSTILE_REQUEST_IDS` (MarketLoop's
real pipe-delimited convention, spaces, slashes, non-ASCII, a
100,000-character string, the empty string) — satisfies
`data_layer.models`' canonical, unwidened `_ID` contract. Proven by
`test_minted_identity_always_satisfies_the_dormant_relational_projection_contract`.

**5G-4 (LOW, CLOSED).** `closed_positions` was previously unvalidated by
`_validate_state` and unread by `snapshot()`. The key/value identity
consistency and charset checks close the validation gap; `snapshot()`
remains deliberately unchanged (no production reader of `closed_positions`
exists).

**F4 (reservation-store growth) and F5 (`applied_executions` growth)
remain OPEN**, unchanged, exactly as recorded in 5F's evidence — neither is
touched, worsened, or newly discovered by this package.

No BLOCKING, HIGH, or MEDIUM finding is newly introduced by this package.
Design 1's charset conflict with MarketLoop's request_id convention was
caught by the existing regression suite during this package's own
construction, before being committed anywhere, and is fully superseded by
Design 2 — it is not carried forward as an open item in any form.

## Proof Summary

| Item | Claim | Test(s) |
|---|---|---|
| A | 4 real lifetimes -> 4 distinct closed records, correct per-lifetime entry/exit/pnl/fees, distinct timestamps, correct book-level totals, survives restart | `test_four_real_lifetimes_produce_four_distinct_closed_records_surviving_restart` |
| A2 | Real MarketLoop pipe-delimited request_id mints and closes successfully (regression guard) | `test_candle_identity_shaped_request_id_mints_and_closes_through_the_real_pipeline` |
| B | Deterministic, pure function of (symbol, request_id); no randomness; distinct request_ids/symbols produce distinct ids | `test_mint_is_deterministic_pure_function_of_symbol_and_request_id` |
| C | Add-to-position reuses the existing position_id; no new lifetime | `test_add_to_position_reuses_existing_position_id_and_mints_no_new_lifetime` |
| D | Partial SELL archives nothing; identity preserved | `test_partial_sell_creates_no_closed_record_and_preserves_position_id` |
| E | Full SELL archives exactly once; archive immutable against later unrelated lifetimes | `test_full_sell_archives_exactly_one_immutable_record` |
| F | A real duplicate closed-position identity fails closed; prior record byte-unchanged; recovery-required, matching existing integrity-violation semantics | `test_reused_closed_position_identity_fails_closed_without_overwriting` |
| G | Legacy bare `long:<symbol>` reloads, closes once under its own id, unrewritten; next lifetime mints the new hashed composite form | `test_legacy_bare_symbol_position_id_closes_once_and_next_lifetime_mints_composite` |
| H | Restart preserves every closed lifetime exactly | `test_restart_preserves_every_closed_lifetime_exactly` |
| I | Arbitrarily long request_id still produces a fixed, bounded (<128), valid identity; no raw request_id charset dependency remains across 8 hostile shapes (pipes, spaces, slashes, non-ASCII, 5000/100000-char strings, empty string), each minting distinctly and validly | `test_long_request_id_still_produces_a_bounded_valid_position_id`, `test_no_raw_request_id_charset_dependency_remains` |
| J | Minted identity always satisfies the dormant relational projection contract, unconditionally, across every hostile request_id shape | `test_minted_identity_always_satisfies_the_dormant_relational_projection_contract` |

All 12 tests live in
`tests/test_block5g_closed_position_lifetime_identity.py` and construct real
`ExecutionPortfolioFoundation`/`FinancialStateStore`/`AtlasApplication`
instances — no mocks of the classes under test — rooted at pytest's
`tmp_path`.

## Source Revision

Branch: `feat/block3-execution-safety`

Parent HEAD: `a2a9049d949bb6806a53d4fab10e08e8338fbaee` —
`feat: reclaim committed reservation capital`

## Frozen Decisions (owner rulings, applied verbatim)

- Final lifetime identity model: deterministic `long:<symbol>:
  <sha256(opening_request_id).hexdigest()>` — full digest, not truncated.
- Add-to-position reuses the existing live `position_id`; SELL reads the
  live durable `position_id` and never creates a new one — both unchanged
  code paths, not touched by this package.
- Closed-position collision fails closed
  (`CLOSED_POSITION_IDENTITY_CONFLICT`).
- Legacy `long:<symbol>` live/closed records are not rewritten.
- No `SCHEMA_VERSION` change.
- No reservation-store/`applied_executions` compaction work (F4/F5 stay
  open).
- No `data_layer` storage wiring.
- No audit-payload expansion — none was required to preserve an existing
  invariant.
- One live LONG per symbol remains unchanged — `state["positions"]` stays
  keyed by symbol.
- Output must satisfy the *existing, unwidened* `data_layer.models` `_ID`
  regex — achieved by hashing rather than by widening that regex.
- Raw `request_id` is never sanitized or truncated into the identity —
  hashing is a deterministic projection, not a sanitization.

## Authority Continuity

`git diff --stat -- core/` (against parent HEAD) shows exactly two changed
files: `core/execution_manager.py` and
`core/execution_portfolio_foundation.py`. No other production file —
`core/risk_engine.py` (5B), `core/position_sizing.py` (5C),
`core/instrument_rules.py` (5D), `core/fee_accounting.py`,
`core/capital_reservation.py` (5F), `core/execution_models.py`,
`core/market_loop.py` — carries any diff. `core/market_loop.py` in
particular was read, never edited: its `request_id` fingerprint convention
is exactly the thing this package's final design had to keep working
without touching.

`core/execution_portfolio_foundation.py`'s only new import is the stdlib
`hashlib` (plus the `re` already added in Design 1, still used for the
charset check). `core/execution_manager.py`'s only import change is one
added name (`mint_long_position_id`) in an already-existing import
statement from `core.execution_portfolio_foundation` — the same statement
that already imports `SETTLEMENT_CONTEXT_PRECISION`. Neither introduces a
new cross-layer edge, per the architecture-rerun scoping decision below.

## PAPER / LIVE

Unchanged. PAPER remains the default and LIVE authority remains denied. 5G
touches only PAPER-path position-identity minting and durable closed-record
archival; no execution-mode or venue-adapter path is touched.

## Push Status

NOT PUSHED. Committed locally only, on `feat/block3-execution-safety`, on
top of parent HEAD `a2a9049`. See the Final Commit section below for the
exact commit hash and committed file list.

## Validation Evidence

All commands ran against the working tree in this session with an isolated,
ASCII `--basetemp` outside the repository (this host's default tmp-path
root is broken for pytest under the `HUAWEİ` profile directory), per this
project's standing testing convention. Every fixture in
`tests/test_block5g_closed_position_lifetime_identity.py` seeds into
`tmp_path`; no command wrote to the operator's real runtime state
(`memory_data/`, root-level `paper_trades.json`) or touched git beyond the
working tree until the final commit described below.

**Package 5G focused suite (final, hashed design):** 12 passed in 1.33s.
`python -m pytest tests/test_block5g_closed_position_lifetime_identity.py -q --basetemp=<isolated>`

**Directly affected 5F turnover test (unchanged by the hashing change — it
constructs `position_id` as literal strings, not via `mint_long_position_id`,
so its 9/9 pass count carries over exactly):** 9 passed in 0.70s.
`python -m pytest tests/test_block5f_reservation_capital_reclamation.py -q --basetemp=<isolated>`

**MarketLoop/runtime-cutover identity tests + data_layer ID/projection
tests (without wiring storage):** 224 passed in 4.11s.
`python -m pytest tests/test_block5a_risk_state_plumbing.py tests/test_block5c_upstream_sizing_authority.py tests/test_phase4_execution_manager_runtime_cutover.py tests/test_phase4_execution_position_portfolio_foundation.py tests/test_phase2_canonical_evidence_adapter.py tests/test_phase2_data_layer.py tests/test_phase2_recovery_projection_safety.py tests/test_phase2_runtime_safety_integration.py -q --basetemp=<isolated>`

**Architecture suite: not re-run this round.** Only a stdlib `import
hashlib` was added in this round; no cross-module or cross-layer import
edge changed (the one production import-statement change, adding
`mint_long_position_id` to an already-existing `core.execution_manager` →
`core.execution_portfolio_foundation` import, was already covered by the
architecture suite's 15/15 pass in the prior round of this same package,
before any commit). Per explicit scoping for this round: stdlib `hashlib`
alone does not justify a rerun.

**Full `tests/` suite (once, after all remediation complete):** 2198
passed, 0 failed, in 94.23s.
`python -m pytest tests/ -q --basetemp=<isolated>`

2198 = 2200 (this package's prior-round full-suite count, itself 2186 5F
baseline + 14) − 2 (this round replaced 3 now-invalid tests, whose premise
was that `mint_long_position_id` rejects a `request_id` merely because its
characters are outside the identity charset, with 2 tests proving the
opposite under hashing, and replaced 2 conditional/negative
relational-compatibility tests with 1 unconditional one) = 12 (this
package's final focused-suite count) net of the prior round's 14.

## Exact Intended Package 5G File List

Total: **6 files** — 2 core production, 1 test amended, 1 test new, 2
evidence (1 new, 1 amended).

Core production (2):
- `core/execution_manager.py`
- `core/execution_portfolio_foundation.py`

Tests (2):
- `tests/test_block5f_reservation_capital_reclamation.py` (amended: the
  turnover test's simulated lifetimes now each carry a distinct
  deterministic `position_id` instead of reusing `long:BTCUSDT`; the
  module's scope-note docstring points the F3 deferral to this package as
  CLOSED. No capital-reclamation assertion was touched. Unaffected by this
  round's hashing change.)
- `tests/test_block5g_closed_position_lifetime_identity.py` (new; final
  version proves the hashed design)

Evidence (2):
- `docs/evidence/block5g_freeze_evidence.md` (new, this document — final
  version, superseding the intermediate raw-embed version drafted during
  this same package's construction and never committed)
- `docs/evidence/block5f_freeze_evidence.md` (amended: F3's status line and
  body point to this package as CLOSED, wording aligned to the final
  hashed identity format)

No unrelated or generated file is in scope for this package.

## Limits of This Evidence

This package corrects one identity-minting site and one archive-write site,
and proves the corrected contract through direct foundation construction
and the full production pipeline alike. It does not address, and makes no
claim about: F4 (reservation-store growth) or F5 (`applied_executions`
growth), both still open and untouched; wiring `data_layer` storage to the
live path (5G-3 proves the minted identity is *compatible* with that dormant
layer's contract, not that the layer is connected); or any change to
`RiskEngine`, `PositionSizingService`, `MarketLoop`, `InstrumentRules`,
`FeeNormalizer`, or `CapitalReservationLedger` — none of which this package
touched. The audit `EXECUTION_COMPLETED` payload still carries no
`position_id`; only the idempotency record does, which is sufficient to
close 5G-2 but is not itself expanded by this package. SHA-256 is one-way:
`position_id` cannot be reversed back into `request_id`, only re-derived
forward from it — which is the only direction `data_layer.projection_replay`
ever needs.
