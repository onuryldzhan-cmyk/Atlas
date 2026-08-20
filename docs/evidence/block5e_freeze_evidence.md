# Atlas Block 5 / Package 5E Freeze Evidence

## Status

Package 5E closure candidate: PASS
BLOCKING: 0
HIGH: 0
MEDIUM NEW: 0

User approval required before staging/commit. As of this writing, only
`core/fee_accounting.py` and `tests/test_block5e_fee_settlement_accounting.py`
are staged (from an earlier, already-superseded staging action), and neither
has been committed. No file in Package 5E's intended file list — including
this document — has been committed.

## Package

Block 5 / Package 5E — Fee-Currency Classification and Fee-Inclusive
Settlement (`core/fee_accounting.py`, `core/execution_manager.py`,
`core/execution_portfolio_foundation.py`, `core/capital_reservation.py`,
`core/execution_models.py`).

## Objective

Package 5B settled a component-reported fee correctly in quote currency but
left three defects on record (5B freeze evidence, F4/F7/F8) plus an implicit
gap: nothing wired to Package 5B ever charged a fee, so no fee-currency
classification existed at all. Package 5E closes all three defects and adds
that classification:

- **F4.** A fee reported without a declared currency failed inside durable
  finalization, after the paper side-effect boundary, rather than before it.
- **F7.** A COMMITTED reservation kept the full reserved amount even though
  settlement spent `notional + fee`, permanently over-encumbering the
  deterministic sub-quantum remainder a BUY never spent.
- **F8.** `entry_fees` were carried whole through a partial SELL instead of
  being released pro rata with the cost basis they sit alongside.
- **F9 (fee-currency classification, new in 5E).** `core.fee_accounting.FeeNormalizer`
  classifies a reported fee against the instrument's own declared assets
  (Block 5D). Only the venue's quote asset is settleable exactly today; a
  base-asset fee, a third-asset fee (e.g. BNB), and an undeclared nonzero fee
  are all refused before durable settlement — never assumed to be quote
  currency and never converted, because there is no FX or fee-rate policy
  anywhere in this repository.

A final targeted review of the first implementation pass raised three
MEDIUM findings, closed by this remediation (Review History, below):

1. Malformed `fee_amount` ingress (negative, non-finite, or unparseable)
   was silently discarded and fell back to the legacy `fee`/`commission`
   mirror instead of failing closed.
2. The Decimal-context pin covering the settlement slice's arithmetic
   (F5, in the sense used throughout this package — see "F5 Scope" below)
   was scoped too narrowly: only the partial-close pro-rata division and
   its complements were pinned, not the BUY debit/fee accumulation, the
   SELL gross P&L/cash/fee accumulation, either leg's average-entry-price
   division, or the two `notional + fee` settlement sums in
   `ExecutionManager`.
3. The test guarding F8's pro-ration invariant derived its own expected
   value from the code's own output (`released = original - remaining`,
   then asserted `released + remaining == original`), which holds for any
   value of `remaining` and could never fail — including under the original
   F8 defect.

## Source Revision

Branch: `feat/block3-execution-safety`

Parent HEAD: `bd950fdca16c999034ff984b7f8e437755f6c1d9` —
`feat: add venue instrument precision contract`

Package 5E commit: **not yet made.** As with Packages 5B/5C/5D's own
evidence documents, this document is prepared *before* Package 5E is
committed. It records the working-tree and index state at evidence-capture
time, not a tagged or already-committed revision.

Worktree at evidence-capture time: **not clean, and not staged** beyond the
pre-existing partial staging of `core/fee_accounting.py` and
`tests/test_block5e_fee_settlement_accounting.py` (both `A`/`AM` in `git
status`, from an earlier, already-superseded staging action that predates
this remediation). Full diff against parent HEAD, staged and unstaged
combined:

```
core/capital_reservation.py                        |  49 +-
core/execution_manager.py                          | 256 ++++++-
core/execution_models.py                           |   4 +
core/execution_portfolio_foundation.py             | 121 +++-
core/fee_accounting.py                             | 107 +++
packaging/atlas_architecture_map.json              |   6 +
packaging/atlas_runtime_closure.json               |   1 +
tests/test_block5b_single_sizing_authority.py      |  21 +-
tests/test_block5e_fee_settlement_accounting.py    | 753 +++++++++++++++++++++
tests/test_phase4_execution_position_portfolio_foundation.py | 19 +-
10 files changed, 1272 insertions(+), 65 deletions(-)
```

## F5 Scope

"F5" is used two ways across this project's evidence trail, and this
document distinguishes them explicitly to avoid overstating what 5E closes:

- **F5 as originally recorded (5B freeze evidence):** "BUY `quote = price *
  base` depends on the ambient Decimal context outside the explicit
  `localcontext` used for division" — a property of `_resolve_base_fill`
  (Block 5D sizing), which pins only `rounding`, not `prec`, on its own
  division.
- **"F5's settlement slice"** — the phrase this package's code comments and
  its predecessor's docstrings use — refers to the same general concern
  (ambient-context-dependent Decimal arithmetic) as it separately manifests
  in `ExecutionPortfolioFoundation._open`/`_close` and in the two
  `notional + fee` settlement sums in `ExecutionManager`. This is what 5E
  actually pins, and what "F5 settlement slice: CLOSED" below refers to.

**`_resolve_base_fill`'s own ambient sensitivity (the original F5) is not
closed by this package and is explicitly out of scope** ("do not broaden
into sizing/market-price arithmetic outside 5E" — owner instruction for this
remediation). This session's ambient-precision test design work for
MEDIUM #2 empirically reconfirmed it is real, not merely theoretical: a
directly monkeypatched `_resolve_base_fill` was necessary in
`test_ambient_decimal_precision_cannot_change_the_reservation_commit_amount`
specifically because driving `_resolve_base_fill` itself with a many-digit
fee under `getcontext().prec = 5` measurably changed its sized fill (a
`612.35`-notional fill became a `615.56`-notional fill purely from lowering
ambient precision around the call, independent of anything this package
touched) — see Accepted Policy Limitations, below.

## Frozen Decisions

**Exact fee-currency classification (F9).** `core/fee_accounting.py`'s
`FeeNormalizer.normalize` is a stateless, pure classifier: given a reported
`fee_amount`/`fee_currency` and an instrument's `InstrumentRules` (Block
5D), it returns a `NormalizedFee` (always quote-denominated) or raises
`FeeRejected` with one of `UNDECLARED_FEE_CURRENCY`,
`BASE_ASSET_FEE_UNSUPPORTED`, `THIRD_ASSET_FEE_UNSUPPORTED`, or
`INVALID_FEE_AMOUNT`. It carries no fee-rate policy, no fee schedule, and no
FX conversion — none of those exist anywhere in this repository, and none
are invented here. It is called from `_execute_paper_buy` and
`_execute_paper_sell` (full-exit path only — a partial reduction skips the
compatibility paper book and never hydrates a fee, per F3) before either
reaches `_finalize_durable_financial_state`, so a fee this settlement path
cannot account for exactly never crosses the paper side-effect boundary's
durable consequence (F4).

**Exact `fee_amount` ingress, fail-closed on malformed input (F9 + final
review MEDIUM #1).** `ExecutionManager._extract_exact_decimal` reads a
component's `fee_amount` key directly as a `Decimal`/decimal string,
verbatim, never through the lossy `fee` float mirror. It returns `None`
*only* when the key itself is absent (or explicitly `None`) — the one case
`_hydrate_result_from_component` is allowed to fall back to the legacy
`fee`/`commission` keys for. A key that is *present* but cannot stand as an
authoritative fee — negative, non-finite, or not parseable as a `Decimal`
at all — now comes back as a `Decimal` regardless (poisoned as `NaN` when
unparseable), so it is carried through to `FeeNormalizer.normalize`, which
already refuses a negative or non-finite `fee_amount` via
`INVALID_FEE_AMOUNT`. It is never silently discarded into the `None`/
fallback path, and the legacy mirror is never consulted once `fee_amount`
was present, valid or not.

**Reservation settles at the exact spent amount, not the full reservation
(F7).** `CapitalReservationLedger.commit(reservation_id, settled_amount=None)`
records a COMMITTED reservation at `settled_amount` when supplied —
`filled_quote_notional + fee_amount`, computed by `ExecutionManager` right
before commit — never exceeding the original reserved amount
(`ValueError` if it would). `commit()` is now the sole door from RESERVED to
COMMITTED (`_transition`'s allowed-pairs set no longer includes it); an
already-COMMITTED reservation returns unchanged regardless of
`settled_amount`, so a replayed commit cannot re-price an already-settled
reservation. `active_reserved_capital`'s exclusion of COMMITTED means the
unspent sub-quantum remainder a BUY never spent stops being permanently
encumbered. This does not release the settled amount on a later position
exit — a COMMITTED reservation still never transitions to RELEASED — that
lifecycle/unwind remains the explicit BLOCKING follow-up recorded below,
unchanged by this package.

**`entry_fees` released pro rata with cost basis (F8).**
`ExecutionPortfolioFoundation._close` releases `entry_fees` at the identical
`sold/held` ratio as `cost_quote`. Both the cost-basis remainder and the
entry-fees remainder are the complement of their released figure (`cost -
released`, `entry_fees - released_entry_fees`), never independently
recomputed, so released + remaining equals the original exactly regardless
of the division's own rounding. A full close carries the exhausted
remaining `entry_fees` into the closed-position record rather than
discarding it.

**Explicit, pinned settlement Decimal context (F5's settlement slice, final
review MEDIUM #2).** `SETTLEMENT_CONTEXT_PRECISION = 50` /
`ROUND_HALF_EVEN`, defined once in `core/execution_portfolio_foundation.py`
and imported by `core/execution_manager.py` rather than duplicated, is now
pinned around every authoritative computation in this settlement slice, not
only the pro-rata division:

- `_open`: the BUY debit (`notional + fee`), the cash/fee accumulation, and
  the average-entry-price division (`cost / base`) — both the fresh-open
  and add-to-existing-position branches.
- `_close`: the cost-basis and entry-fee pro-rata divisions and their
  complements (unchanged from the first pass), plus gross P&L
  (`notional - released`), the cash and fee accumulation, and the
  remaining position's average-entry-price division — previously left
  outside the pinned block even though a subtraction rounds to its active
  context exactly as a division does.
- `ExecutionManager`: the commit-time `settled_amount = notional + fee`
  computed just before `_commit_capital_reservation`, and the
  approval-check `settled = notional + fee` computed inside
  `_finalize_durable_financial_state` just before the `settled > approved`
  comparison — the same economic sum, computed twice, now pinned
  identically in both places so the two can never round it differently
  under a caller's ambient precision.

Deliberately **not** widened into: `_resolve_base_fill` (Block 5D sizing;
see "F5 Scope" above), `mark()`, or `snapshot()`'s `unrealized_pnl`/
`gross_exposure` (display-derived from live `mark_price`, not settlement
evidence) — all out of scope for this package.

## Review History

### Final targeted review of the first Package 5E implementation

Performed against the first working-tree implementation of F4/F7/F8/F9,
read-only, before this remediation began. Raised three MEDIUM findings
(malformed `fee_amount` ingress falling back instead of failing closed; the
Decimal-context pin scoped to the pro-rata division only; the F8 pro-ration
test being tautological) and confirmed F4/F7/F8/F9 CLOSED, 5B/5C/5D
authorities INTACT, and `fee_accounting.py`'s L1 placement valid, subject to
those three MEDIUMs. Full verdict text preserved in this session's
transcript; not reproduced here beyond the findings this remediation
addresses.

### This remediation

**MEDIUM #1 (malformed exact fee ingress falls back instead of failing
closed).**
**Remediated:** `_extract_exact_decimal` (Frozen Decisions, above) —
`core/execution_manager.py`.
**Closed. Evidence:**
`test_invalid_exact_fee_with_valid_legacy_fee_rejects_without_fallback`,
`test_invalid_exact_fee_with_no_legacy_fee_rejects`,
`test_negative_exact_fee_amount_rejects`,
`test_non_finite_exact_fee_amount_rejects` (parametrized: `NaN`,
`Infinity`, `-Infinity`), `test_valid_exact_fee_amount_still_settles_exactly`
(positive control), `test_fee_amount_absent_falls_back_to_legacy_commission_key`
(the one case the legacy mirror is still consulted for — deliberately
exercises the `commission` alias specifically, since the `fee` alias was
already covered by an existing 5E test, so this adds rather than duplicates
coverage).

**MEDIUM #2 (Decimal-context pin scoped too narrowly).**
**Remediated:** widened `_open`/`_close`/the two `ExecutionManager` sums
(Frozen Decisions, above).
**Closed. Evidence:**
`test_ambient_decimal_precision_cannot_change_buy_or_sell_settlement`
(`ExecutionPortfolioFoundation` level — both BUY legs, both fresh-open and
add-to-position, plus a partial SELL, all at prices/fees chosen so debit,
fee accumulation, and both legs' average-entry-price division are
non-terminating; a 2-of-7 held/sold ratio keeps the pro-rata split
non-terminating too) and
`test_ambient_decimal_precision_cannot_change_the_reservation_commit_amount`
(`ExecutionManager.execute()` level, with `_resolve_base_fill` mocked to a
fixed, internally price-consistent, many-digit notional so this test
isolates the two settlement-sum sites this package pinned from Block 5D's
own separate, out-of-scope sizing-precision behavior — see "F5 Scope").
Both compare a full run at normal ambient precision against an identical
run under `getcontext().prec = 5`, asserting every settlement figure —
`cash`, `fees`, `realized_gross_pnl`, `entry_fees`, `cost_quote`,
`average_entry_price`, and the committed reservation amount — is bit-for-bit
identical, and that the perturbed run still reaches `COMMITTED` rather than
spuriously halting.

**Verification that these two tests actually discriminate, not merely
pass:** each pinned `with localcontext(): context.prec =
SETTLEMENT_CONTEXT_PRECISION` block this package added (`_open`, `_close`,
and both `ExecutionManager` sites) was independently, temporarily
neutralized in this session and the corresponding test rerun, confirmed to
fail against the neutralized code, then restored from an unmodified backup
and reconfirmed green. This was exploratory verification during
remediation, not part of the frozen state, and left no trace in the
working tree.

**MEDIUM #3 (tautological F8 pro-ration test).**
**Remediated:** replaced
`test_partial_sell_entry_fee_release_plus_remainder_equals_original` with
`test_partial_sell_entry_fee_release_matches_independently_computed_ratio`.
**Closed. Evidence:** the new test computes the expected released fee from
the known `sold/held` ratio (2/7) applied to the known original fee —
independently of `remaining_entry_fees` as observed from the position under
test — under the identical pinned context `_close` uses internally (so the
non-terminating ratio cannot make the test's own ambient precision disagree
with the foundation's), then asserts both `released_entry_fees ==
expected_released` and `remaining_entry_fees == expected_remaining`. Unlike
its predecessor, this fails if the whole fee is carried through unreleased
(the original F8 defect) or if any ratio other than 2/7 is applied —
confirmed by re-deriving the prior (tautological) form and observing it
could not fail for the same defect.

**A fourth, unplanned regression surfaced and fixed during this
remediation:** widening `_open`'s pinned context to include
`average_entry_price` (MEDIUM #2) changed that figure's stored precision
for any BUY whose `cost / base` does not terminate — from Python's ambient
28-digit default to this package's explicit 50-digit context — which is
more accurate, not less, but broke one pre-existing Phase-4 test
(`test_valid_increase_updates_weighted_position`,
`tests/test_phase4_execution_position_portfolio_foundation.py`) that
compared the stored value against `D("200") / D("15")` computed under its
own ambient precision. Fixed by computing that test's expected value under
the identical pinned context rather than loosening the comparison — the
semantic check (average entry price equals cost/base) is unchanged; only
the precision the comparison is performed at now matches what `_open`
actually — and correctly — computes. Confirmed no other test in the
repository asserts a non-terminating `average_entry_price` (or other
5E-pinned) division against a value computed outside that context (grep
across `tests/` for `average_entry_price` and bare `D(...)/D(...)`
comparisons; every other hit either compares against a value that
terminates exactly regardless of precision, e.g. whole numbers, or is one
of this package's own already-pinned assertions).

### Final known findings

BLOCKING: 0
HIGH: 0
MEDIUM NEW: 0

The COMMITTED-reservation-lifecycle/capital-reclamation defect and the
unsupported base-fee/pre-admission-fee policies are **not** counted as new
5E findings — both are pre-existing, already-recorded, explicitly
out-of-scope items (Known Non-Blocking Follow-ups, below), carried forward
from Package 5B and from this package's own stated scope, not introduced or
newly discovered by this remediation.

## 5B / 5C / 5D Authority Continuity

**Package 5B — exact durable quantity/allocation authority: intact.**
`core/risk_engine.py` and `core/position_sizing.py` carry zero diff against
parent HEAD (`git diff HEAD --stat -- core/risk_engine.py
core/position_sizing.py` — no output). The one 5B test edited by this
package (`test_a_fee_without_a_declared_currency_fails_closed`) tightens
*where* the undeclared-fee-currency rejection is caught (F4: now in
`paper_execute`, before `_finalize_durable_financial_state`, rather than
inside it) — the invariant itself (an undeclared nonzero fee never
settles) is unchanged, and every other 5B assertion in that file is
untouched.

**Package 5C — `PositionSizingService` authority: intact.**
`core/position_sizing.py` carries zero diff (see above); this package does
not touch sizing at all.

**Package 5D — venue instrument-precision authority: intact.**
`core/instrument_rules.py` carries zero diff. `FeeNormalizer.normalize`
consumes `InstrumentRules.base_asset`/`quote_asset` read-only and adds no
new instrument-rule authority; the venue-minimum/step/tick gates 5D
established are unmodified.

## Known Non-Blocking Follow-ups / Limitations

**COMMITTED reservation lifecycle / capital reclamation (CLOSED by Package
5F — open at this package's own freeze time).** At 5E's freeze, a COMMITTED
reservation still never transitioned to RELEASED, and F7's remediation in
this package (committing at the exact settled amount rather than the full
reservation) narrowed the amount permanently encumbered by a BUY's own
sub-quantum remainder without addressing the broader lifecycle: capital
committed to a position was not reclaimed when that position was later
reduced or closed. This was explicitly out of scope for Package 5E from the
outset (see the test module's own docstring) and was, at the time, the
single most consequential open item against this settlement authority.
Package 5F closed it — not by adding the RELEASED transition or a
reservation/position link this note anticipated, but by correcting
`CapitalReservationLedger`'s definition of live encumbrance to RESERVED +
INDETERMINATE only, so a COMMITTED reservation stops encumbering `available`
the instant it settles. See `docs/evidence/block5f_freeze_evidence.md`.

**Unsupported base-asset/third-asset fee settlement (accepted, open).**
`FeeNormalizer` fails closed on a base-asset or third-asset fee rather than
settling it (e.g. withholding from base quantity, or converting via an FX
rate) — there is no fee-rate policy, fee schedule, or FX conversion
authority anywhere in this repository, and none is invented here. A venue
that charges fees in BNB or in the base asset cannot be traded through this
settlement path until such a policy is designed and reviewed as its own
package.

**`_resolve_base_fill`'s own ambient-precision sensitivity (accepted, open
— the sizing side of F5, distinct from this package's settlement-slice
scope).** See "F5 Scope," above. `_resolve_base_fill` pins only `rounding`
on its sizing division, not `prec`; a many-digit fee or allocation can
change the *sized fill itself* under a caller's ambient precision.
Empirically reconfirmed during this remediation's test design, not merely
theoretical. Addressing it is Block 5D sizing work, not Package 5E
settlement work.

**No per-position net P&L consumer for `entry_fees` (accepted, open,
carried from F8's original scope note).** `entry_fees` is now released
pro rata (F8, closed), but nothing in this repository yet consumes it to
compute a fee-inclusive net P&L. It is correctly maintained bookkeeping
with no reader yet.

Neither the COMMITTED-lifecycle item, the unsupported-fee-currency policy
gap, `_resolve_base_fill`'s ambient sensitivity, nor the missing
net-P&L consumer is claimed resolved by this document.

## PAPER / LIVE

Unchanged by this package. PAPER remains the default and LIVE authority
remains denied. Package 5E added fee-currency classification and
fee-inclusive settlement arithmetic; it did not modify the PAPER default,
LIVE denial, or any live-execution adapter path.

## Push Status

NOT PUSHED. No push, no merge, and — as of this document — no commit exists
for Package 5E. Only `core/fee_accounting.py` and
`tests/test_block5e_fee_settlement_accounting.py` are staged (pre-dating
this remediation), and neither is committed. Nothing beyond the file list
below has been touched by this package's work.

## Validation Evidence

All commands were run against the working tree in this session with an
isolated, ASCII `--basetemp` outside the repository (this host's default
tmp-path root is broken for pytest), per this project's standing testing
convention. Every fixture in `tests/test_block5e_fee_settlement_accounting.py`
and `tests/test_phase4_execution_position_portfolio_foundation.py` seeds
into `tmp_path`; no command wrote to the operator's real runtime state. No
command modified, staged, or committed anything beyond what this document
itself describes.

**Package 5E focused suite:** 29 passed.
`python -m pytest tests/test_block5e_fee_settlement_accounting.py -q --basetemp=<isolated>`

**Combined 5A + 5B + 5C + 5D + 5E + architecture suite:** 281 passed.
`python -m pytest tests/test_block5e_fee_settlement_accounting.py tests/test_block5b_single_sizing_authority.py tests/test_block5c_upstream_sizing_authority.py tests/test_block5d_instrument_precision_contract.py tests/test_block5a_risk_state_plumbing.py tests/architecture -q --basetemp=<isolated>`

**Reservation / portfolio / financial-identity regression:** 82 passed.
`python -m pytest tests/test_phase3_risk_capital_foundation.py tests/test_phase4_execution_position_portfolio_foundation.py tests/test_block2_m1_reservation_admission_atomicity.py -q --basetemp=<isolated>`

**Full `tests/` suite (once, after all remediation complete):** 2177 passed
in 77.11s.
`python -m pytest tests/ -q --basetemp=<isolated>`

Architecture result (layer totality, forbidden imports, composition-root
uniqueness, runtime-closure/inventory match, LIVE-denied-by-default) is
unchanged by this package and already established by the combined suite
run above; `packaging/atlas_architecture_map.json` and
`packaging/atlas_runtime_closure.json` were updated only to register
`core/fee_accounting.py` as L1 (pre-dating this remediation, unmodified by
it) — both files carry zero further diff from this remediation's work.

## Exact Intended Package 5E File List

Total: **10 files** — 5 core production (1 new), 2 packaging/architecture,
3 tests (1 new).

Core production (5):
- `core/capital_reservation.py`
- `core/execution_manager.py`
- `core/execution_models.py`
- `core/execution_portfolio_foundation.py`
- `core/fee_accounting.py` (new)

Packaging / architecture metadata (2):
- `packaging/atlas_architecture_map.json`
- `packaging/atlas_runtime_closure.json`

Tests (3):
- `tests/test_block5b_single_sizing_authority.py`
- `tests/test_block5e_fee_settlement_accounting.py` (new)
- `tests/test_phase4_execution_position_portfolio_foundation.py`

Evidence (1, this document):
- `docs/evidence/block5e_freeze_evidence.md` (new)

No unrelated or generated files are in scope for this package. `git status
--short` at capture time contains no entries outside this list.

## Limits of This Evidence

Package 5E establishes fee-currency classification against Block 5D's
venue-precision authority, fee-inclusive reservation settlement, pro-rata
entry-fee release, and an explicit pinned Decimal context across that
settlement slice. It does not establish, and this document does not claim:
COMMITTED-reservation capital reclamation on position exit (accepted,
open — BLOCKING for a future package), base-asset/third-asset fee
settlement or any fee-rate/FX policy (accepted, open), ambient-precision
immunity for `_resolve_base_fill`'s own sizing division (accepted, open,
Block 5D scope), a net-P&L consumer for `entry_fees` (accepted, open), or
LIVE readiness. This document also does not claim a committed or tagged
revision: it is a closure candidate awaiting explicit user approval to
stage and commit.
