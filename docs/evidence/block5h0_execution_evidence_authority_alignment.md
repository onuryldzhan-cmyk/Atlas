# Atlas Block 5 / Package 5H-0 Freeze Evidence

## Status

Package 5H-0 closure candidate: PASS
BLOCKING: 0 remaining (2 closed this package)
HIGH: 0 remaining (4 closed this package)
MEDIUM NEW: 0

## Package

Block 5 / Package 5H-0 — Execution Evidence Authority Alignment
(`core/execution_idempotency_store.py`, `core/execution_transaction_journal.py`).

## Objective

Prior packages established that a COMMITTED request in
`ExecutionTransactionJournal` and its counterpart in
`ExecutionIdempotencyStore` must independently agree, and that
`FinancialRuntimeSafetyService._authorities_agree` fails the runtime closed
(`SOURCE_DISAGREEMENT`) the moment they don't. What was never proven is that
the idempotency store could actually *keep* agreeing once real trading
volume accumulated: its production default, `DEFAULT_MAX_RECORDS = 5_000`,
silently pruned the oldest completed request once a 5,001st one arrived —
while the journal, already unbounded, kept every entry forever. This
package removes that bound from production, and separately hardens
`ExecutionTransactionJournal.prepare()` against a related but distinct
hazard the same investigation surfaced: nothing stopped `prepare()` from
silently overwriting an already-COMMITTED entry back to `PREPARED`.

## Original Blocker and Reproduction

**The 5,000-request blocker (B5H-0-1, BLOCKING).** `ExecutionIdempotencyStore`
retained only the newest `max_records` (default 5,000) completed requests,
evicting the oldest by insertion order the moment a new one arrived past
that bound. A COMMITTED request older than the newest 5,000 would still be
present, COMMITTED, in the transaction journal (unbounded), but silently
absent from the idempotency store — and `_authorities_agree()` treats a
COMMITTED journal entry with no idempotency counterpart as a genuine
disagreement, exactly as it must (that check itself is correct and is not
weakened by this package; see B5H-0-3 below).

**Proof that the 5,001st request caused prune and SOURCE_DISAGREEMENT**
(`test_a_old_bound_crossing_then_production_unbounded`,
`tests/test_block5h0_execution_evidence_authority_alignment.py`): 5,001
requests recorded into an `ExecutionIdempotencyStore` explicitly constructed
with the historical `max_records=5_000` leaves exactly 5,000 present,
`stats["records_pruned"] == 1`, and the very first (oldest) request_id
evicted. Pairing that store with a journal that recorded all 5,001 as
COMMITTED and asking `FinancialRuntimeSafetyService.assess()`: `ready is
False`, `decision.reason == "SOURCE_DISAGREEMENT"`. This is a real, provoked
instance of the defect, not an assertion about the constant's value.

**Why `max_records` was not a legitimate expiry contract.** Nothing in the
system ever declares a COMMITTED execution request "expired." A COMMITTED
journal entry is retained forever by design (it is the durable record that
money moved); the idempotency store existed specifically to let
`ExecutionManager` recognize a replay of that same request_id after a
restart and return the original result instead of re-executing it. A
time-blind, count-based LRU eviction over that store had no relationship to
any real lifecycle event — it fired purely as a function of how much
*unrelated* traffic (including traffic with no financial consequence at
all; see B5H-0-6) happened to arrive afterward, silently converting a
100%-correct, agreeing system into a fail-closed one with no operator
action, no audit trail explaining why, and no relationship to the age or
outcome of the affected request. It was accidental capacity management that
had leaked into a correctness contract.

## Final Retention Contract

**Production (default):** `ExecutionIdempotencyStore.DEFAULT_MAX_RECORDS` is
now `None`. `ExecutionIdempotencyStore()` constructed with no `max_records`
argument is unbounded: `self.max_records is None`, `_prune_locked()` returns
immediately, `records_pruned` stays `0` forever, and every COMMITTED
request_id remains replayable indefinitely, matching the owner's ruling that
historical COMMITTED request_ids remain replayable indefinitely and that
production retention is unbounded.

**Explicit bounded test mode (retained, non-production):** passing an
explicit `max_records` (any integer) still enables the original
insertion-order LRU pruning exactly as before, including the same
normalization of invalid values (`max(1, int(max_records))` — `0` and
negative values both normalize to `1`, unchanged from the pre-existing
style). This mode exists solely so the historical defect has a permanent,
fast, literal regression witness (`test_a_old_bound_crossing_...`,
`test_i1_explicit_bounded_test_mode_still_prunes`,
`test_i2_explicit_invalid_bounds_normalize_like_before`) and is never
constructed anywhere in production wiring. There are exactly two production
`ExecutionIdempotencyStore` construction sites, and **both omit
`max_records`**, so both inherit the new unbounded default automatically
without any change to either file:

- `core/application.py` (composition root) —
  `ExecutionIdempotencyStore(self.state_directory / EXECUTION_IDEMPOTENCY_STATE_FILE)`
  passes the resolved state-directory path positionally and nothing else.
  This is the site the running Atlas application actually uses.
- `core/execution_manager.py` (injection fallback) —
  `ExecutionIdempotencyStore(file_path=idempotency_file)`, used only when no
  store is injected, passes the file path by keyword and nothing else.

No configuration key, environment variable, or constructor default anywhere
in the repository supplies a `max_records` value, so explicit bounded
retention cannot become production behaviour through current wiring.

**No schema migration.** `ExecutionIdempotencyStore.VERSION` stays `"1.0"`;
the persisted JSON shape (`version`, `updated_at`, `completed_requests`) is
byte-for-byte unchanged. A file written by the old bounded implementation
loads under the new code with no conversion step and no version bump
(`test_j_v1_persisted_format_loads_without_migration_and_stops_pruning`):
all pre-existing records survive the load, and every write that follows
(including ones that cross the old 5,000-record threshold) prunes nothing.

## Journal Terminal-Overwrite Blocker and Guard

**The reopen hazard (B5H-0-2, BLOCKING).** Independent of the retention bug
above, `ExecutionTransactionJournal.prepare()` had no guard at all: calling
it a second time for a request_id already recorded `COMMITTED`
unconditionally replaced that entry with a fresh `PREPARED` record,
discarding the stored terminal `result`. Combined with the retention defect,
this was a second, compounding failure mode: a COMMITTED request whose
idempotency counterpart had been pruned would not only cause
`SOURCE_DISAGREEMENT` at the next readiness check — if a caller ever
resubmitted that request_id in the window before that check ran, the
now-unprotected journal would silently erase the fact that the request had
already committed, reopening a closed financial transaction.

**The guard.** `ExecutionTransactionJournal.TERMINAL_STATES = {"COMMITTED"}`.
`prepare()` now checks the existing entry's `state` before doing anything
else; if it is `COMMITTED`, `prepare()` logs a warning and returns `False`
without touching `self.entries` or calling `save()` — the same fail-closed
return value `prepare()` already used for a persistence failure, so
`ExecutionManager`'s existing `if not prepared:` handling
(`TRANSACTION_PREPARE_FAILED` → capital released → `NOT_COMMITTED` result)
applies unchanged; no new journal lifecycle state or result convention was
introduced. Proven byte-for-byte: after `prepare()` → `mark_committed()`,
calling `prepare()` again returns `False`, and the stored entry — state,
`result`, every field — is dict-equal to what it was immediately after
`mark_committed()` (`test_h1_journal_refuses_to_reopen_committed_entry`).

**NOT_COMMITTED is deliberately excluded from the guard, and this was
discovered, not assumed.** The task framed the guard as covering "COMMITTED
or NOT_COMMITTED," directing that the actual scope be resolved against "the
repository's actual terminal-state contract." Implementing the broader
guard first and running the full suite (see Validation Evidence) surfaced a
real, pre-existing, intentional contract it would have broken:
`ExecutionManager._resolve_unsuccessful_execution`'s own docstring states
that when a request's side-effect boundary was never crossed, "the
reservation is RELEASED, the journal entry is resolved NOT_COMMITTED, and
the request stays retryable" — i.e., a fresh `prepare()` for that same
request_id must succeed again. `tests/test_block3_terminal_status_
classification.py::test_live_denial_leaves_the_request_retryable` already
depended on exactly this: two identical LIVE-disabled attempts with the same
request_id must produce the identical `LIVE_DISABLED` status both times,
which requires the second `prepare()` to succeed, not refuse. NOT_COMMITTED
carries no financial side effect by construction, so unlike COMMITTED there
is nothing there for a guard to protect, and guarding it anyway would have
silently converted an intentional, already-tested retry contract into a
spurious `TRANSACTION_PREPARE_FAILED`. `COMMIT_STATUS_UNKNOWN` was never in
scope either way — it is already in `UNRESOLVED_STATES`, not terminal, and
untouched by this package. This resolution — and the fact that it was
reached by discovery against the real regression suite rather than by
assumption — is recorded explicitly in
`test_h2_journal_still_allows_reprepare_of_not_committed_entry` and in the
`TERMINAL_STATES` comment in `core/execution_transaction_journal.py`.
`test_h3_journal_still_allows_reprepare_of_unresolved_states` separately
confirms `PREPARED` and `COMMIT_STATUS_UNKNOWN` retry semantics are
untouched.

## Restart / Replay Proof

**Restart (C).** 500 requests recorded COMMITTED into both a fresh
`ExecutionIdempotencyStore` and a fresh `ExecutionTransactionJournal`,
saved, then reloaded through brand-new instances pointed at the same files.
All 500 remain in both authorities, `records_pruned == 0` after reload, and
a real `ExecutionManager` constructed on the reloaded pair starts with
`running=True`, `execution_halted=False`, `recovery_required=False`
(`test_c_restart_reload_agrees_after_many_committed_requests`).

**Oldest-request replay across the old threshold (D).** One "oldest"
COMMITTED request plus 5,000 filler COMMITTED requests (the historical
bound, crossed by exactly one) are recorded into both authorities, saved,
and reloaded through fresh instances — simulating a process restart in
production-unbounded mode. A full `ExecutionManager` (real `RiskEngine`,
`CapitalReservationLedger`, `JsonRiskStateStore`, `InstrumentRuleset`, and a
call-counting paper trader) is then constructed on the restarted pair and
asked to execute the oldest request_id again:
`duplicate_reason == "DUPLICATE_REQUEST_COMPLETED"`,
`idempotency.cache_hit is True`, the original `execution_id` ("exec-oldest")
is returned unchanged, and the paper trader's `open_count` stays `0` — no
paper execution occurs a second time
(`test_d_oldest_request_still_replays_after_crossing_old_threshold_and_restart`).
Under the old bounded default this exact scenario is the one that would
have pruned the oldest request's idempotency record, made it look like a
brand-new request on replay, and (compounded by the journal hazard above)
risked a duplicate paper execution.

## Genuine Disagreement Still Fails Closed

Unbounded retention removes the *spurious* disagreement pruning used to
cause; it does not touch the disagreement check itself
(B5H-0-3, HIGH, CLOSED by not relaxing agreement). A COMMITTED journal entry
whose idempotency counterpart is independently removed — simulating
corruption or data loss unrelated to retention — still produces
`_authorities_agree() is False`, `FinancialRuntimeSafetyService.assess()`
returns `ready=False` with `decision.reason == "SOURCE_DISAGREEMENT"`, and a
real `ExecutionManager.start()` on that pair sets `execution_halted=True`,
`recovery_required=True`, `halt_reason == "SOURCE_DISAGREEMENT"`
(`test_f_genuine_disagreement_still_fails_closed`). `_authorities_agree`,
`FinancialRuntimeSafetyService`, and `data_layer/recovery.py` were not
modified by this package.

## Canonical Evidence Adapter Still Requires Agreement

`CanonicalExecutionEvidenceAdapter` (`data_layer/canonical_evidence.py`) was
not modified. Against a set of 2,000 matching COMMITTED journal/idempotency
pairs it produces exactly 2,000 evidence records
(`test_g_canonical_evidence_adapter_large_committed_set`). Mutating one
idempotency counterpart's `execution_id` so it disagrees with its journal
record still raises `IntegrityViolation` on that field; removing the
counterpart entirely still raises `IntegrityViolation` for a missing
canonical result. Both failure modes are unchanged by this package — proven
against a set two orders of magnitude larger than any prior canonical
adapter test to confirm scale was never the reason the check worked before.

## Rejection Pressure Cannot Evict Committed Records

One COMMITTED request followed by 1,500 REJECTED terminal results (a
distinct request_id each — REJECTED is not in `FAILURE_STATUSES`, so each is
persisted) leaves the COMMITTED record untouched
(`store.completed_requests[committed_id]["execution_id"]` unchanged),
`records_pruned == 0`, and `FinancialRuntimeSafetyService.assess().ready is
True` (`test_e_rejection_pressure_cannot_evict_committed_record`).

Scope of this test, stated precisely: it validates retention behaviour under
rejection pressure **within the new unbounded contract** — that
financially-inconsequential traffic accumulates in the store without
displacing a COMMITTED record and without disturbing authority agreement.
It deliberately does **not** cross or reproduce the historical 5,000-record
threshold, and it is not offered as an independent witness of the historical
defect; `test_a_old_bound_crossing_then_production_unbounded` and
`test_d_oldest_request_still_replays_after_crossing_old_threshold_and_restart`
are the tests that provoke and witness that threshold directly. The design
observation that rejection traffic consumed the old retention budget
(REJECTED is not in `FAILURE_STATUSES`, so each such result was persisted and
counted toward the bound despite having no financial consequence) is recorded
here as rationale for removing the bound, not as something this test proves.

## Findings Closed

| ID | Severity | Status | Closure basis |
|---|---|---|---|
| B5H-0-1 | BLOCKING | CLOSED | Production `ExecutionIdempotencyStore` is unbounded by default; the 5,000-record eviction that caused `SOURCE_DISAGREEMENT` cannot occur in production wiring. |
| B5H-0-2 | BLOCKING | CLOSED | `ExecutionTransactionJournal.prepare()` refuses to reopen a COMMITTED entry; a pruned-then-resubmitted request_id can no longer reset a durable commit record back to PREPARED. |
| B5H-0-3 | HIGH | CLOSED by not relaxing agreement | `_authorities_agree()` / `SOURCE_DISAGREEMENT` is untouched; a genuine (non-retention) disagreement still fails closed (`test_f`). |
| B5H-0-4 | HIGH | CLOSED | Historical COMMITTED request_ids remain replayable indefinitely in production, per owner ruling; proven past the old bound and across a restart (`test_a` phase 2, `test_d`). |
| B5H-0-5 | HIGH | CLOSED for production because eviction no longer occurs | No insertion-order eviction of any kind happens when `max_records is None` (`test_a`, `test_b`, `test_c`). |
| B5H-0-6 | HIGH | CLOSED for production because rejection traffic cannot evict committed records | 1,500 REJECTED terminal results cannot displace one COMMITTED record (`test_e`). |
| B5H-0-7 | MEDIUM | OPEN (carried forward) | Unbounded idempotency store still rewrites and fsyncs the entire file on every `save()`; O(n) growth is accepted temporarily per owner ruling. Not addressed by this package; a compaction/segmented-write design is a separate future finding. |
| B5H-0-8 | MEDIUM | CLOSED in production / retained as test-mode note | In-memory/durable divergence caused by pruning cannot occur in production (pruning is disabled). Explicit bounded test mode may still diverge by design — it exists only to reproduce the historical defect and must never be used in production wiring. |
| B5H-0-9 | MEDIUM | OPEN (carried forward) | `ExecutionManager.reset()` resets `idempotency_store` but not `transaction_journal` — an existing asymmetry, out of scope for this package per owner ruling. |
| B5H-0-10 | MEDIUM | CLOSED in production because pruning is disabled | Any correctness gap that depended on the idempotency store silently forgetting a record cannot occur once pruning never runs. |
| B5H-0-11 | LOW | Irrelevant in production; retained as a test-mode note | `DEFAULT_MAX_RECORDS` no longer implies a real production bound; the name is retained for the explicit bounded test-mode constructor argument's default reference point only. |
| B5H-0-12 | LOW | OPEN (carried forward) | No operator reconciliation tool exists for an already-corrupt `SOURCE_DISAGREEMENT` environment (e.g., independent file corruption). The runtime still correctly fails closed and halts (`test_f`); it does not yet help an operator repair the underlying disagreement. |

No new BLOCKING, HIGH, or MEDIUM finding is introduced by this package.

## Proof Summary

| Item | Claim | Test(s) |
|---|---|---|
| A | Explicit `max_records=5_000` reproduces the historical defect at exactly 5,001 requests (1 pruned, `SOURCE_DISAGREEMENT`); production-unbounded mode at 5,500 requests prunes nothing and stays ready | `test_a_old_bound_crossing_then_production_unbounded` |
| B | `ExecutionIdempotencyStore.DEFAULT_MAX_RECORDS is None`; a store built with no `max_records` argument is unbounded and never prunes | `test_b_production_default_constructs_unbounded` |
| C | 500 COMMITTED pairs survive a save/reload restart intact; a real `ExecutionManager` starts un-halted on the reloaded pair | `test_c_restart_reload_agrees_after_many_committed_requests` |
| D | The oldest of 5,001 COMMITTED requests survives a restart and replays as `DUPLICATE_REQUEST_COMPLETED` with its original `execution_id`, with zero additional paper executions | `test_d_oldest_request_still_replays_after_crossing_old_threshold_and_restart` |
| E | Retention under rejection pressure in the new unbounded contract: 1,500 REJECTED terminal results accumulate without displacing one COMMITTED record and readiness stays true (does not cross the historical 5,000 threshold — see A and D for that) | `test_e_rejection_pressure_cannot_evict_committed_record` |
| F | An idempotency record independently removed from under a COMMITTED journal entry still produces `SOURCE_DISAGREEMENT` and a halted, recovery-required manager | `test_f_genuine_disagreement_still_fails_closed` |
| G | `CanonicalExecutionEvidenceAdapter` succeeds for 2,000 matching pairs; a mutated or missing idempotency counterpart still raises `IntegrityViolation` | `test_g_canonical_evidence_adapter_large_committed_set` |
| H1 | `prepare()` refuses to reopen a COMMITTED entry; the stored entry is byte/field-identical afterward | `test_h1_journal_refuses_to_reopen_committed_entry` |
| H2 | `prepare()` deliberately still allows reopening a NOT_COMMITTED entry, matching `ExecutionManager`'s existing retry contract | `test_h2_journal_still_allows_reprepare_of_not_committed_entry` |
| H3 | `prepare()` retry semantics for `PREPARED` and `COMMIT_STATUS_UNKNOWN` (both non-terminal) are unchanged | `test_h3_journal_still_allows_reprepare_of_unresolved_states` |
| I1 | Explicit `max_records=3` still prunes down to the 3 newest records | `test_i1_explicit_bounded_test_mode_still_prunes` |
| I2 | Explicit invalid bounds (`0`, `-5`) still normalize to `1`, matching pre-existing style | `test_i2_explicit_invalid_bounds_normalize_like_before` |
| J | A v1 idempotency JSON file written by the old implementation loads with no migration and all records intact; subsequent writes past the old 5,000 threshold prune nothing | `test_j_v1_persisted_format_loads_without_migration_and_stops_pruning` |

All 14 tests (`test_i2` parametrized ×2) live in
`tests/test_block5h0_execution_evidence_authority_alignment.py` and
construct real `ExecutionIdempotencyStore` / `ExecutionTransactionJournal` /
`FinancialRuntimeSafetyService` / `CanonicalExecutionEvidenceAdapter` /
`ExecutionManager` instances — no mocks of the classes under test — rooted
at pytest's `tmp_path`.

## Source Revision

Branch: `feat/block3-execution-safety`

Parent HEAD: `803a12da249ab0625b0688e7caa9e9f33175128e` —
`feat: add deterministic position lifetime identity`

## Frozen Decisions (owner rulings, applied verbatim)

- Historical COMMITTED request_ids remain replayable indefinitely.
- Production `ExecutionIdempotencyStore` is unbounded.
- `DEFAULT_MAX_RECORDS` becomes `None`.
- Explicit `max_records` remains supported for tests only.
- Runtime safety authority agreement (`_authorities_agree`) is not
  weakened.
- `CanonicalExecutionEvidenceAdapter`'s agreement requirement is not
  weakened.
- `applied_executions` remains untouched (not referenced by, or reachable
  from, either changed file).
- `ExecutionTransactionJournal` must refuse to overwrite terminal (COMMITTED)
  entries.
- No schema migration.
- O(n) rewrite/fsync growth on every idempotency-store `save()` is accepted
  temporarily and carried forward as B5H-0-7, a separate compaction
  finding.
- `ExecutionManager.reset()`'s idempotency/journal divergence (B5H-0-9) is
  out of scope for this package.

## Authority Continuity

`git diff --numstat -- core/` (against parent HEAD `803a12d`) shows exactly
two changed files: `core/execution_idempotency_store.py` (+27/-9) and
`core/execution_transaction_journal.py` (+45/-0). No other production file —
`core/execution_manager.py`, `core/execution_portfolio_foundation.py`,
`data_layer/runtime_safety.py`, `data_layer/canonical_evidence.py`,
`data_layer/recovery.py` — carries any diff. `core/execution_manager.py` was
read extensively (to establish `_claim_request`, `_complete_request`,
`_resolve_unsuccessful_execution`, and `prepare()`'s call site) but never
edited: its idempotency/journal construction call sites already pass no
`max_records`, so the new unbounded default applies with zero changes
there, and its `if not prepared:` handling of `prepare()`'s fail-closed
`False` already covers the new terminal-guard refusal without modification.
`applied_executions` (owned by `core/execution_portfolio_foundation.py`) is
not referenced by either changed file. Neither changed file gained or lost
an import; `execution_transaction_journal.py`'s only new symbol is the
class attribute `TERMINAL_STATES`, built from the already-imported
`CommitOutcome` enum.

## PAPER / LIVE

Unchanged. PAPER remains the default and LIVE authority remains denied.
This package touches only durable idempotency retention and journal
terminal-state protection; no execution-mode or venue-adapter path is
touched.

## Push Status

NOT PUSHED. Committed locally only on `feat/block3-execution-safety`,
on top of parent HEAD `803a12d`.

## Validation Evidence

All commands ran against the working tree in this session with an isolated,
ASCII `--basetemp` outside the repository (this host's default tmp-path
root is broken for pytest under the `HUAWEİ` profile directory), per this
project's standing testing convention. Every fixture in the new test file
seeds into `tmp_path`; no command wrote to the operator's real runtime state
(`memory_data/`, root-level `paper_trades.json`).

**Package 5H-0 focused suite:** 14 passed in 15.35s.
`python -m pytest tests/test_block5h0_execution_evidence_authority_alignment.py -q --basetemp=<isolated>`

**Directly affected regression groups** (durable execution path ownership,
runtime safety integration + its integration-boundary sibling, canonical
evidence adapter, durable transaction state, sensitive-data idempotency
serialization, restart/replay, plus every test file anywhere in `tests/`
that references `mark_not_committed`/`NOT_COMMITTED` — added after the
first full-suite run surfaced a real conflict there, see below): 196
passed in 21.38s.
`python -m pytest tests/test_block5h0_execution_evidence_authority_alignment.py tests/test_durable_transaction_state.py tests/test_block5a_risk_state_plumbing.py tests/test_block3_execution_exception_atomicity.py tests/test_block3_terminal_status_classification.py tests/test_block3_durable_execution_path_ownership.py tests/test_phase2_runtime_safety_integration.py tests/test_phase2_runtime_integration_boundary.py tests/test_phase2_canonical_evidence_adapter.py tests/test_sensitive_data_boundaries.py tests/test_phase2_recovery_projection_safety.py -q --basetemp=<isolated>`

**First full `tests/` run (initial `TERMINAL_STATES = {COMMITTED,
NOT_COMMITTED}` implementation): 1 failed, 2211 passed in 65.03s.** The
single failure,
`tests/test_block3_terminal_status_classification.py::test_live_denial_leaves_the_request_retryable`,
was a genuine regression: guarding NOT_COMMITTED broke
`ExecutionManager`'s existing, documented retry contract for a denial with
no side effect (see "Journal Terminal-Overwrite Blocker and Guard" above).
Per this project's standing rule against weakening or rewriting a test to
force a pass, the implementation was corrected instead —
`TERMINAL_STATES` narrowed to `{COMMITTED}` only — and the affected test
file (`test_h2`) rewritten to assert the actually-correct, actually-tested
contract.

**Second (final) full `tests/` run, after the correction: 2212 passed, 0
failed, in 61.31s.**
`python -m pytest tests/ -q --basetemp=<isolated>`

2212 = 2198 (5G's prior full-suite baseline) + 14 (this package's new
tests). No other test file's count changed: this package's production
changes are additive-only for every existing call site (unbounded default,
one new narrowly-scoped refusal path that nothing except the corrected
`test_h2` and the reverted `test_live_denial_leaves_the_request_retryable`
scenario ever reaches).

## Exact Intended Package 5H-0 File List

Total: **4 files** — 2 core production, 1 test new, 1 evidence new
(this document included in the count).

Core production (2):
- `core/execution_idempotency_store.py`
- `core/execution_transaction_journal.py`

Tests (1):
- `tests/test_block5h0_execution_evidence_authority_alignment.py` (new)

Evidence (1):
- `docs/evidence/block5h0_execution_evidence_authority_alignment.md` (new,
  this document)

No unrelated or generated file is in scope for this package.

## Limits of This Evidence

This package removes one accidental capacity bound from production and adds
one narrowly-scoped immutability guard; it does not address, and makes no
claim about: B5H-0-7 (unbounded idempotency store `save()` remains a full
file rewrite plus `fsync` on every call — O(n) per write, accepted
temporarily); B5H-0-9 (`ExecutionManager.reset()` still resets the
idempotency store without resetting the transaction journal); or B5H-0-12
(no operator tool exists to reconcile an already-corrupt
`SOURCE_DISAGREEMENT` environment caused by something other than this
package's own defect, e.g. independent file corruption — the runtime
correctly refuses to proceed, but recovering from that state today is a
manual, out-of-band operation). It does not change how `PREPARED` or
`COMMIT_STATUS_UNKNOWN` are handled, does not touch
`FinancialRuntimeSafetyService`, `data_layer/recovery.py`,
`CanonicalExecutionEvidenceAdapter`, or `applied_executions`, and does not
change `ExecutionManager` in any way — every production call site already
composed correctly with the new defaults and the new guard's existing
fail-closed return convention.
