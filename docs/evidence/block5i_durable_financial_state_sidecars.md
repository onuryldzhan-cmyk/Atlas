# Atlas Block 5 / Package 5I Freeze Evidence

## Status

Package 5I closure candidate: PASS, after remediation (see "Independent
Review Remediation" below).
BLOCKING: 0 remaining (0 introduced)
HIGH: 0 remaining **(1 introduced by this package, found by independent
review, remediated below - not a false "0 introduced")**
MEDIUM NEW: 0 remaining (3 introduced by this package, found by independent
review, remediated below)

## Independent Review Remediation

An independent review of the code this document originally described was
run against the final code before staging/commit, per this project's
convention. That review's initial verdict was **FAIL**: one HIGH and three
MEDIUM findings against code this package itself introduced, plus two
lower-severity (L) accuracy findings. All are closed as of this revision of
this document; the sections below and the rest of this document describe
the post-remediation state. Two additional lower-severity findings from
that same review (L-3, L-4) are explicitly **out of scope for this
remediation pass and are not claimed fixed** - they remain open.

**H-1 (HIGH, introduced by this package, now CLOSED).**
`tools/migrate_execution_financial_state.py`'s pre-existing-closed-sidecar
conflict check compared only
`ClosedPositionArchiveStore.load_index().by_position_id` - a view that, by
design, strips the archive's own `sequence` field - against the source's
expected records by `position_id` alone. A pre-existing archive record with
the *right* content at the *wrong* sequence therefore passed this check
silently. The subsequent append loop, which skips any `position_id` already
present in the pre-existing archive, would then append a *different* source
position at that same now-conflicting sequence - producing a corrupt,
non-monotonic archive - and, since nothing downstream re-validated what had
just been written, the tool proceeded to overwrite the v1 working file with
schema_version 2 and report `MIGRATED`, exit 0.

Fix, in two parts:

1. **Closed identity is now `(sequence, canonical payload)`, not payload
   alone.** `ClosedPositionIndex` gained a `sequence_by_position_id` field
   (populated by `ClosedPositionArchiveStore.load_index()` alongside the
   existing `by_position_id`), and a new `_closed_identity(sequence,
   record)` helper in the migration tool mirrors the pre-existing
   `_applied_identity(record)` helper the applied sidecar already used
   correctly. Because each sidecar's own `load_index()` already requires a
   gapless, zero-based sequence internally, requiring every pre-existing
   record to match this source's record *at that record's own sequence* is
   exactly equivalent to requiring the pre-existing archive be a valid
   prefix of this run's deterministic output - a non-prefix subset (the
   reviewer's exact example: source `[p1 seq0, p2 seq1, p3 seq2]`,
   pre-existing archive `[p2 seq0]`) now refuses
   (`CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE`) before anything is written. An
   exact prefix (e.g. `[p1 seq0, p2 seq1]`) still resumes and appends only
   the missing tail (`p3 seq2`). No existing archive line is ever
   renumbered or rewritten in either case.
2. **Mandatory post-append verification, as a hard gate before the v1 -> v2
   rewrite.** After every pending applied/closed record is appended and
   fsynced, `migrate()` now calls a new `_verify_post_append()` that
   reloads *both* sidecars from disk through their own public
   `load_index()` - never comparing only to the in-memory records that
   produced the appends - and requires each to exactly reproduce this run's
   complete expected identity set (`_applied_identity`/`_closed_identity`
   for every record, not just the newly-appended ones). Only if both
   verifications pass does the tool proceed to rewrite the working file;
   otherwise it returns `FAILED` with a fixed `POST_APPEND_VERIFICATION_FAILED:
   APPLIED_SIDECAR` / `:CLOSED_SIDECAR` token, a non-zero exit, and the v1
   working file untouched. This closes the gap the non-prefix scenario
   exploited (a corrupt archive being written and then trusted) and any
   other post-append damage (e.g. a torn write landing between the append
   and the tool's own read of it).

Five discriminating tests were added to
`tests/test_block5i_durable_financial_state_sidecars.py`:
`test_ad_closed_sidecar_non_prefix_subset_refuses_before_rewrite` (the
reviewer's exact example), `test_ae_closed_sidecar_exact_prefix_resumes_and_appends_remainder`,
`test_af_closed_sidecar_same_payload_wrong_sequence_refuses`,
`test_ag_post_append_corruption_blocks_rewrite_and_preserves_v1` (corruption
injected between a real append and verification, via a monkeypatched
`ClosedPositionArchiveStore.append`), and
`test_ah_post_append_verification_reloads_sidecars_from_disk` (a dropped
write that never reaches disk - proving verification reloads through the
public `load_index()` path rather than trusting that `append()` was called
the expected number of times). All five fail against the pre-remediation
implementation.

**M-1 (MEDIUM, introduced by this package, now CLOSED) - ADR-0005 output
safety.** `core/financial_state_bootstrap.py`'s `_bootstrap_financial_state`
placed `ExecutionPortfolioFoundation.diagnostics()["reason"]` directly into
the operator-visible `reason_code`. That internal diagnostic is deliberately
detailed for debugging (per `ExecutionPortfolioFoundation`'s own docstring)
- for `AppliedExecutionArchiveConflictError` / `ClosedPositionArchiveConflictError`
specifically, it embeds the raw `execution_id`, `idempotency_key`, or
`position_id` that triggered the conflict, and for the two
`*ArchiveCorruptError` types, a raw archive line number. That raw text
reached `reason_code` verbatim, violating ADR-0005's "reason codes are
fixed tokens rather than raw exception text" contract - and would not have
been fixed by truncation, since every one of those identifiers is well
under any reasonable length cap.

Fix: a new `_classify_financial_foundation_reason()` in
`core/financial_state_bootstrap.py` maps the foundation's raw internal
reason to one of a fixed, enumerable set of operator-safe tokens -
`FINANCIAL_APPLIED_AUTHORITY_{DIVERGENT,MISSING,CORRUPT,CONFLICT}`,
`FINANCIAL_CLOSED_AUTHORITY_{DIVERGENT,MISSING,CORRUPT,CONFLICT}`,
`FINANCIAL_CLOSED_POSITION_LIVE_CONFLICT`, `FINANCIAL_STATE_RECOVERY_REQUIRED`,
`FINANCIAL_TRANSITION_RECOVERY_REQUIRED` - before it ever becomes a
`reason_code`; anything not already one of these safe, data-free tokens
collapses to the generic `FINANCIAL_STATE_RECOVERY_REQUIRED` fallback
rather than being exposed. `docs/adr/0005-operator-bootstrap-runbook.md`'s
reason-code table gained these tokens. `tools/bootstrap_financial_state.py`'s
CLI needed no change - it only ever prints `reason_code` (already
`sanitize_sensitive_text`-wrapped as defense in depth), so fixing the
source eliminates the leak everywhere it could surface.
`test_ai_bootstrap_reason_code_never_leaks_raw_sensitive_identifiers`
constructs an applied-sidecar `IDEMPOTENCY_IDENTITY_CONFLICT` around the
deliberately sensitive identifier `SECRET-EXEC-ID-12345` and asserts it is
absent from `reason_code`, which instead reports the fixed
`FINANCIAL_APPLIED_AUTHORITY_CONFLICT` token.

**M-2 (MEDIUM, now CLOSED) - destructive migration refusal path coverage.**
Eight refusal reason codes previously had no direct test:
`CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE`, `APPLIED_SIDECAR_CORRUPT`,
`APPLIED_SIDECAR_CONFLICT`, `CLOSED_SIDECAR_CORRUPT`,
`CLOSED_SIDECAR_CONFLICT`, `SOURCE_UNREADABLE`, `SOURCE_UNRECOGNIZED_SCHEMA`,
`SOURCE_CORRUPT`. `CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE` is now covered
directly (and more thoroughly than a generic case would, since it proves
the prefix/resume rule specifically) by `test_ad`/`test_af` above; the
remaining seven are covered by one parametrized test,
`test_aj_destructive_migration_refusal_paths_touch_nothing`, over seven
`(setup, expected_outcome, expected_reason_code)` cases reusing the
existing `_write_v1_file`/`_closed_record` fixtures. Every case asserts the
v1 source and both sidecars (where present beforehand) are byte-identical
after refusal, that the outcome is never `MIGRATED`, and that the exit code
is `EXIT_REFUSED`.  `APPLIED_SIDECAR_DOES_NOT_MATCH_SOURCE` already had
direct coverage (`test_y`, pre-existing) and is intentionally not
duplicated in the parametrized set.

**M-3 (MEDIUM, now CLOSED) - unreachable retry-tolerance claim corrected.**
`AppliedExecutionArchiveStore.load_index()` tolerates a consecutive
byte-identical duplicate line, and its docstring described this as
"covering an interrupted-retry append landing twice" - phrasing that reads
as an operational guarantee this package relies on. Inspection of the one
live caller, `ExecutionPortfolioFoundation.apply_confirmed`, shows this
branch is not known to be reachable through it: `applied_at` is stamped
fresh with `datetime.now(UTC)` on every call, so two genuine retries of the
same logical execution never produce byte-identical archive lines, and a
same-process replay of an already-durable `execution_id` short-circuits at
`apply_confirmed`'s own `prior is not None` check *before* a second
`append()` is ever attempted - it never reaches the archive at all. Per the
task's instruction not to redesign the protocol merely to make the branch
reachable, and since removing defensive equality logic changes nothing
about valid crash/restart behavior either way, **no production behavior
was changed**: the tolerance branch is retained as defensive logic (it
still protects against representation-level duplication, e.g. a storage
layer duplicating a line), but the docstring in
`core/execution_portfolio_foundation.py` and this document's own
"Sequencing" section (below) now say so explicitly instead of implying it
is exercised by a live path. No new test was added for M-3, per the task's
own instruction to add one only if production behavior changed.

**L-1 (accuracy, now CORRECTED).**
`test_l_crash_during_final_working_state_save_leaves_prior_file_byte_exact`
claimed, in its own name, that the working file is left byte-exact after
this crash - but its own inline comment stated the opposite ("the file is
not byte-identical to `before_bytes`"), and no assertion in the test ever
compared the file's bytes to what they were before the call; the assertion
proving the point (`on_disk["transition"] is not None`) in fact proves the
file *changed*. The test's assertions were correct (the transition-marker
write genuinely lands before this crash point, per `apply_confirmed`'s own
ordering; only the previously-committed financial figures inside are
unperturbed) - only the name was wrong. Renamed, with no assertion changed,
to `test_l_crash_during_final_working_state_save_leaves_committed_data_unperturbed`.

**L-2 (accuracy, now CORRECTED).** This document's "Operator Migration
Tool" section previously described the migration protocol as
"(4) append/verify the applied sidecar; (5) append/verify the closed
sidecar" - but no per-sidecar verify step existed at that point in the
pre-remediation implementation; only H-1's fix above introduced a real
post-append verification step, and it verifies both sidecars together,
once, after all appends, not interleaved per-sidecar. The "Operator
Migration Tool" section below is corrected to describe the actual final
protocol.

## Package

Block 5 / Package 5I — Durable Financial State Sidecars
(`core/execution_portfolio_foundation.py`, `core/financial_state_bootstrap.py`,
`core/application.py`, `tools/migrate_execution_financial_state.py`).

## Objective

`ExecutionPortfolioFoundation`'s working file (`execution_financial_state.json`,
schema_version 1) held `closed_positions` and `applied_executions` inline.
Block 5H's own evidence (`docs/evidence/block5h_capital_reservation_archive.md`,
"Carried Forward") explicitly recorded this as out of scope for that
package: both collections grew by one entry for the runtime's entire
lifetime, with the *entire* working file — cash, positions, and both
historical collections — rewritten in full on every single confirmed
execution, regardless of which part actually changed.

This package closes that growth by moving both collections out of the
working file into two immutable, append-only JSON-Lines sidecars, following
the same pattern Block 5H established for capital reservations
(`ReservationArchiveStore`), extended with the checkpoint mechanism this
package's owner decisions require: the working file keeps two small
pointers — `applied_checkpoint` / `closed_checkpoint` — that must agree
exactly with each sidecar's durable tail at every load, so a durable
financial mutation can never exist without durable applied-execution proof,
and a durable applied-execution record can never be mistaken for a
committed mutation unless the working checkpoint confirms it.

## Final Architecture: v2 Working File + Two Immutable Sidecars

**Working file** (`FinancialStateStore`, schema bumped `1` → `2`, the module
constant `SCHEMA_VERSION`): holds only current operational state — `cash`,
`reserved_capital`, `realized_gross_pnl`, `fees`, `positions` — plus
`applied_checkpoint` and `closed_checkpoint`. `closed_positions` and
`applied_executions` no longer exist in this file at all. Same atomic
temp-file-write → flush → fsync → `os.replace` durability as before; no
change to that mechanism.

**Applied-execution authority** (`AppliedExecutionArchiveStore`, new,
`execution_applied_executions.jsonl`): one canonical record per line —
`sequence`, `execution_id`, `idempotency_key`, `applied_at` — append-only,
durable (write → flush → fsync) before the call returns, mirroring
`ReservationArchiveStore` / `AuditEventStore`'s existing jsonl pattern.
`load_index()` rebuilds two O(1) lookup maps — `by_execution_id`,
`by_idempotency_key` — in one O(history) pass at construction.

**Closed-position archive** (`ClosedPositionArchiveStore`, new,
`execution_closed_positions.jsonl`): one canonical closed-position record
per line, keyed by Block 5G's deterministic `position_id`, plus the same
`sequence` field. `append()` validates the full record shape strongly
(`validate_closed_position_record`) — every field `_close` actually
produces for a full exit (`position_id`, `symbol`, `base_quantity` pinned to
`"0"`, `cost_quote`, `entry_fees`, `average_entry_price`, `mark_price`,
`version`, `opened_at`, `status` pinned to `"CLOSED"`, `exit_price`,
`gross_pnl`, `closed_at`) — never a subset of the old working-map check
(`position_id` identity alone) and never a new economic field this module
does not already compute.

Neither sidecar has any retention, pruning, or compaction. `append` is the
only write operation either performs; no line is ever rewritten, reordered,
or deleted.

## Sequencing

Both sidecars share one contract: `load_index()` requires strictly
monotonic, gapless, zero-based `sequence` values, with exactly one
exception — a byte-identical repeat of the immediately preceding line
(sequence one behind the current tail, every other field equal) is
tolerated idempotently, as defensive equality logic against a torn write
duplicating a line at the storage layer. For the applied sidecar
specifically, this tolerance is not known to be reachable via any live
`apply_confirmed`-driven path — `applied_at` is stamped fresh on every
append, so two genuine retries never produce byte-identical records, and
same-process replay of an already-durable `execution_id` short-circuits in
`apply_confirmed` before a second append is ever attempted (M-3, see
"Independent Review Remediation" above; corrected in
`AppliedExecutionArchiveStore.load_index()`'s own docstring). Any other
repetition — a reused `sequence`, `execution_id`, `idempotency_key`,
or `position_id` at a genuinely new sequence — fails closed:

- **applied**: same `execution_id`, different `idempotency_key` →
  `APPLIED_EXECUTION_CONFLICT`; new `execution_id` reusing an existing
  `idempotency_key` → `IDEMPOTENCY_IDENTITY_CONFLICT` (the identical token
  `apply_confirmed` itself raises for the live-path case, Section
  "Replay / Idempotency" below — reused deliberately, not coincidentally,
  since both describe the same identity violation at two different times).
- **closed**: same `position_id` at a new sequence with disagreeing content
  → `CLOSED_POSITION_ARCHIVE_CONFLICT`.
- Malformed/torn JSON, wrong shape, or a shape-invalid closed record → each
  store's own `*ArchiveCorruptError`.

Per the task contract, migration sequence (`tools/migrate_execution_financial_state.py`)
is deterministic archive order only — v1's `closed_positions` /
`applied_executions` were unordered JSON maps, so the migration tool assigns
sequence by sorting each map's keys. It is not a reconstruction of
execution chronology, and no financial meaning is ever derived from a
sequence number anywhere in this package.

## Checkpoint Validation (`ExecutionPortfolioFoundation._hydrate_sidecars`)

Runs once at every construction, after the working file's own shape passes
`_validate_state`, before the foundation is usable:

| Condition | Result |
|---|---|
| `applied_checkpoint` is `None` and the applied archive is empty | valid fresh state |
| `applied_checkpoint` is `None` but the archive holds records | `FINANCIAL_APPLIED_AUTHORITY_DIVERGENT` |
| `applied_checkpoint` set but the archive is empty | `FINANCIAL_APPLIED_AUTHORITY_MISSING` |
| `applied_checkpoint` set but disagrees with the archive's actual tail (sequence/execution_id/idempotency_key) | `FINANCIAL_APPLIED_AUTHORITY_DIVERGENT` |
| the applied archive itself is malformed or internally conflicting | `FINANCIAL_APPLIED_AUTHORITY_CORRUPT*` |
| the same four conditions, for `closed_checkpoint` / the closed archive | `FINANCIAL_CLOSED_AUTHORITY_MISSING` / `_DIVERGENT` / `_CORRUPT*` |
| a `position_id` present in both live `positions` and the closed archive | `FINANCIAL_CLOSED_POSITION_LIVE_CONFLICT` |

This specifically protects against the scenario the task named explicitly:
a sidecar append durably lands, the process crashes before the working-state
commit that would advance the checkpoint, and an operator later clears the
stuck `transition` marker by hand without reconciling the checkpoint to
match — `test_m_orphan_applied_record_with_cleared_marker_fails_closed_divergent`
and `test_n_orphan_closed_record_with_cleared_marker_fails_closed_divergent`
construct exactly this and prove it fails closed rather than silently
adopting the orphan (or silently ignoring it).

An absent sidecar file is not distinguished from a present-but-empty one —
both produce `count == 0` — matching Block 5H's own "absent archive is a
valid, empty archive" convention.

## Crash-Safe `apply_confirmed` Ordering

1. Persist the working state with the transition marker set (unchanged
   pre-existing behavior — the prepare/intention barrier).
2. Compute the candidate financial mutation in memory (`_open`/`_close`;
   arithmetic itself is byte-for-byte unchanged from pre-5I — see "Financial
   Parity" below).
3. If `_close` produced a full-exit record: append it to the closed archive
   (durable: write → flush → fsync) and record `closed_checkpoint` on the
   in-memory candidate.
4. Append the applied-execution record to the applied archive (durable) and
   record `applied_checkpoint` on the candidate.
5. Atomically persist the candidate as the new working file: actual
   mutation, `transition = null`, both checkpoints pointing at the exact
   tail just durably written.

Two new test-only injection hooks (`before_closed_archive_append`,
`before_applied_archive_append`), alongside the pre-existing
`before_final_persist`, let tests crash at each of the three boundaries
without needing to fake I/O failures inside the store objects themselves:

| Point | Scenario | Test |
|---|---|---|
| Before any sidecar write | `test_i_*` | Marker persists; neither sidecar gains a record; restart reports `FINANCIAL_TRANSITION_RECOVERY_REQUIRED` |
| After closed append, before applied append | `test_j_*`, `test_n_*` | Closed archive durably orphaned; applied archive untouched |
| After applied append, before final commit | `test_k_*`, `test_m_*` | Both archives durably orphaned; working file's checkpoints still point at the pre-call tail |
| Failure *inside* the final `store.save` call itself (not a pre-call hook) | `test_l_*` | Same orphan-both outcome via a real `FinancialStateStore.save` failure, not the test hook — proves the fail-closed contract does not depend on the hook mechanism |

In every one of these, `ExecutionPortfolioFoundation._recovery_reason` is
set to `FINANCIAL_TRANSITION_RECOVERY_REQUIRED` and re-raises, exactly the
pre-existing (pre-5I) mid-transition contract
(`test_restart_mid_transition_blocks_ready`,
`tests/test_phase4_execution_position_portfolio_foundation.py`) — this
package adds no new in-process failure-handling shape, only two new
durable-append steps inside the same existing `try`/`except`.

## Migration-Required Signal

`FinancialStateStore.load()` distinguishes a legacy `schema_version: 1` file
from every other invalid case: it raises
`FinancialStateMigrationRequiredError` (a `ValueError` subclass, mirroring
Block 5H's `ReservationSchemaMigrationRequiredError`) *before* attempting to
interpret the payload under the v2 contract at all. Runtime never
auto-migrates. `core/financial_state_bootstrap.py`'s
`_bootstrap_financial_state` maps this to `INVALID_EXISTING` /
`FINANCIAL_MIGRATION_REQUIRED` — a distinct, fixed token, never the generic
`FINANCIAL_STATE_RECOVERY_REQUIRED` or `FINANCIAL_STATE_INVALID` an operator
could mistake for ordinary corruption (`test_u_*`). `docs/adr/0005-operator-bootstrap-runbook.md`
gained the token in its reason-code table and a short runbook paragraph
pointing at `tools/migrate_execution_financial_state.py` explicitly — the
one documentation change this package makes, per the task's own instruction
to update the runbook only for this.

Every other pre-existing `FinancialStateStore.load()` / bootstrap reason
code (`FINANCIAL_STATE_RECOVERY_REQUIRED`, `FINANCIAL_TRANSITION_RECOVERY_REQUIRED`,
`FINANCIAL_STATE_INVALID`) is unchanged in meaning and unchanged in the one
pre-existing test (`tests/test_block3_bootstrap_state_validation.py`) that
exercises them — that file needed **no edit at all**: its zero-byte,
wrong-schema, pending-transition, and negative-cash fixtures each fail on
a check `FinancialStateStore.load()`/`_validate_state` performs *before*
ever reaching the new checkpoint fields, so the stale `closed_positions: {}`
/ `applied_executions: {}` keys two of its hand-written v1-shaped fixtures
still carry are simply never inspected. Its one genuine `VALID_EXISTING`
check (`test_financial_state_valid_existing_is_reported_and_untouched`)
seeds state through the real `bootstrap_financial_state()` path rather than
a hand-rolled payload, so it already produces a correctly v2-shaped file
with `applied_checkpoint`/`closed_checkpoint` present.

`_bootstrap_financial_state` now also constructs a real
`ExecutionPortfolioFoundation` (wired to real `AppliedExecutionArchiveStore`
/ `ClosedPositionArchiveStore` instances) for cross-checkpoint validation,
reusing the foundation's own readiness computation and surfacing its exact
`diagnostics()["reason"]` token — the same reuse-the-canonical-service
pattern Block 5H used for `CapitalReservationLedger`. The pre-existing
`_validate_state`-only check (collapsed to the generic `FINANCIAL_STATE_INVALID`)
still runs first and is unchanged, so that one pre-existing reason code's
meaning did not shift.

## Operator Migration Tool

`tools/migrate_execution_financial_state.py` (new), mirroring
`tools/migrate_capital_reservations.py`'s CLI shape (`_UsageExitParser`,
`--json`, fixed exit-code tiers, `sanitize_sensitive_text` on all rendered
output) as a self-contained tool — never invoked from `AtlasApplication` or
`core/financial_state_bootstrap.py`, no automatic-invocation flag of any
kind.

```
python tools/migrate_execution_financial_state.py --state-directory PATH [--dry-run] [--json]
```

Ordering, as actually implemented (corrected here per L-2 - see
"Independent Review Remediation" above): (1) validate the v1 source fully —
financial fields, positions, every `closed_positions` record through the
same strong validator the runtime uses, every `applied_executions` entry's
shape; (2) refuse if `transition` is non-null (`SOURCE_TRANSITION_PENDING`)
— a pending transition means the last confirmed execution's durability is
itself unresolved, so migrating around it could misplace it; (3) construct
canonical `AppliedExecutionRecord`s (sequenced by sorted `execution_id`) and
compare every pre-existing sidecar record — both applied and closed — against
what this exact source would produce at that record's own sequence,
refusing (`REFUSED_SIDECAR_CONFLICT`) before writing anything if any
pre-existing record disagrees; (4) append the closed sidecar's missing
records (sequenced by sorted `position_id`); (5) append the applied
sidecar's missing records — both appends fsync per-line via the same
stores the runtime uses; (6) **hard gate:** reload both sidecars from disk
through their own public `load_index()` and require them to exactly
reproduce this run's complete deterministic output — never trusting the
in-memory records that produced the appends; (7) only if that gate passes,
rewrite the working file **last**, as v2, with both checkpoints pointing at
the exact tail just verified. The v1 working file is never touched until
step 7, so a crash — or a verification failure — at any point before it
leaves v1 completely intact, with both sidecars durably resumable
(`test_x_interrupted_migration_resumes_safely`) or, if verification itself
catches damage, with the tool reporting `FAILED` rather than `MIGRATED`
(`test_ag_*`, `test_ah_*`).

**Idempotent and resumable**, mirroring 5H exactly: re-running against an
already-v2 source is `ALREADY_MIGRATED`, still validating any present
sidecar rather than assuming it healthy. Re-running after a partial prior
run resumes safely — only sidecar records not already durably present are
appended. Applied-record identity for this comparison is `(sequence,
execution_id, idempotency_key)`, **deliberately excluding `applied_at`**:
v1 never recorded an original apply timestamp, so this tool stamps its own
migration-time value, and two independent migration attempts legitimately
disagree on that stamp for a record an earlier run already durably archived
— `_applied_identity()` and `test_x_*` make this exclusion explicit and
prove a pre-existing record's own timestamp is never overwritten by a
resumed run. Closed-record identity is `(sequence, canonical closed-position
payload)` — every field participates, since a closed-position record has no
migration-time-only field to exclude (`_closed_identity()`, `test_ae_*`).

**Never silently overwrites, and never accepts a non-prefix pre-existing
archive.** An existing sidecar record that does not provably match this
exact migration's record at that record's own sequence refuses with
`REFUSED_SIDECAR_CONFLICT`, exit 2, nothing written
(`test_y_conflicting_pre_existing_applied_sidecar_refuses` for the applied
sidecar; `test_ad_*`/`test_af_*` for the closed sidecar, including the
non-prefix-subset case). `--dry-run` reports counts and touches nothing
(`test_z_*`). Exit codes mirror 5H's tool exactly: `0` MIGRATED /
ALREADY_MIGRATED / (dry-run) WOULD_MIGRATE; `1` CLI usage error; `2` refused
(source absent/invalid, transition pending, or a sidecar conflict — nothing
touched); `3` FAILED (unexpected write-phase error, or the post-append
verification gate catching damage before any working-file rewrite). A
CLI-level end-to-end check (`test_z2_*`, `test_aa2_*`, via `subprocess`)
confirms the contract across real process invocations, including
SOURCE_ABSENT → MIGRATED → ALREADY_MIGRATED. Eight refusal paths that
previously had no direct test now do (M-2): `test_ad`/`test_af` for
`CLOSED_SIDECAR_DOES_NOT_MATCH_SOURCE`, and the parametrized
`test_aj_destructive_migration_refusal_paths_touch_nothing` for
`APPLIED_SIDECAR_CORRUPT`, `APPLIED_SIDECAR_CONFLICT`,
`CLOSED_SIDECAR_CORRUPT`, `CLOSED_SIDECAR_CONFLICT`, `SOURCE_UNREADABLE`,
`SOURCE_UNRECOGNIZED_SCHEMA`, `SOURCE_CORRUPT`.

## Replay / Idempotency

`apply_confirmed` replaces the v1 working-map lookups
(`applied_executions.get(execution_id)` / `identity in applied_executions.values()`)
with the immutable authority indexes (`_applied_by_execution_id`,
`_applied_by_idempotency_key`), loaded once at construction and updated
in-memory after every successful commit — never re-read from disk mid-session.
Caller-facing behavior is byte-for-byte unchanged from pre-5I:

- **A.** Same `execution_id` + same `idempotency_key` → `replayed=True`, no
  second mutation, no second archive append (`test_e_*`).
- **B.** Same `execution_id` + different `idempotency_key` →
  `EXECUTION_IDENTITY_CONFLICT` (`test_f_*`).
- **C.** New `execution_id` + already-applied `idempotency_key` →
  `IDEMPOTENCY_IDENTITY_CONFLICT` (`test_g_*`).

All three are rejected (or short-circuited) *before* the transition marker
is ever written, so none of them touches either sidecar.

## Restart / Bootstrap Result

`test_h_restart_rebuilds_both_indexes_and_preserves_replay_behavior`
proves a fresh `ExecutionPortfolioFoundation` construction against the same
files rebuilds both indexes from the sidecars alone and reproduces the
identical replay/conflict decisions a live, never-restarted instance would
have made. `test_v_*` proves the same for a freshly migrated v1→v2 book,
including a real `apply_confirmed` replay against a migrated identity.
`test_aa_*` proves `bootstrap_financial_state(..., verify_only=True)`
reports `VALID_EXISTING` for a freshly migrated directory, and that
re-running the migration tool against it is `ALREADY_MIGRATED`.

## Financial-Total Parity

No line inside `_open` or `_close` changed — same `SETTLEMENT_CONTEXT_PRECISION`-pinned
Decimal arithmetic, same pro-rata partial-close split, same average-entry-price
division. `_close`'s only structural change is that it now *returns* the
closed-position record (or `None` for a partial reduction) instead of
writing it into `state["closed_positions"]`; the caller (`apply_confirmed`)
owns archiving it. `test_d_financial_totals_match_pre_sidecar_arithmetic_exactly`
pins the exact cash/fees/realized_gross_pnl/committed_capital/equity figures
for an open → partial-close → full-close sequence to the same numbers
`tests/test_phase4_execution_position_portfolio_foundation.py`'s pre-5I
equivalents already established.

## Asymptotic Change

- **Working file**: O(current live state) — bounded by live position count
  plus two small checkpoint dicts, not by lifetime execution or closed-position
  count. Before this package it was O(lifetime executions + lifetime closes),
  rewritten in full on every single mutation.
- **Sidecar appends**: O(1) each — a single line write + fsync, never a
  full-file rewrite.
- **Startup index rebuild** (`load_index()` for each sidecar): O(history) —
  a full read of that sidecar's file, once, at construction. This package
  makes no claim of improving this; it is explicitly accepted per the task
  contract (owner decision 8) and carried forward unresolved, matching how
  Block 5H accepted the equivalent cost for its own archive and how the
  idempotency store's O(n) full-file rewrite is separately, still, carried
  forward below.

No performance timing claim is made beyond what this evidence's own test run
durations show; no benchmark beyond the existing suite's wall-clock numbers
was run.

## Exact Test Counts

**Pre-remediation baseline** (recorded by the original 5I evidence pass,
not re-run during remediation per this project's non-reproduction
convention): new focused suite 32 passed; directly affected regression (9
files) 157 passed; full architecture suite 15 passed; full `tests/` suite
2273 passed.

**Post-remediation** (this pass added 10 tests - see "Test Files Changed" -
and changed 3 production files; counts below are from the validation runs
in "Validation Evidence"):

- Targeted remediation group (5I focused suite - now 45 tests, 32 original
  + 13 new/parametrized - plus `test_block2c_financial_state_bootstrap.py`,
  `test_block3_bootstrap_policy_consistency.py`,
  `test_block3_bootstrap_state_validation.py`,
  `test_block3_operator_bootstrap_cli.py`, one command): **113 passed**
- Full `tests/` suite (once, final remediation code state, per this
  package's "run full tests/ exactly once because production code
  changed" instruction): **2286 passed**

2286 = 2273 (pre-remediation baseline) + 13 (this remediation's new tests:
5 H-1 + 1 M-1 + 7 M-2 parametrized cases). Exact match — confirms no test
was lost, silently skipped, or accidentally altered in count anywhere in
the repository by this remediation, including the L-1 rename (a rename
does not change the count).

Architecture suite was not re-run: no import/layer dependency changed in
remediation (only `core/execution_portfolio_foundation.py`,
`core/financial_state_bootstrap.py`, `tools/migrate_execution_financial_state.py`,
and their tests/docs were touched; no new module, no new cross-layer
import). The 15-passed architecture baseline above still applies.

## Exact Production Files Changed

- `core/execution_portfolio_foundation.py` — `SCHEMA_VERSION` 1→2;
  `FinancialStateStore` v2 shape + `FinancialStateMigrationRequiredError`;
  new `AppliedExecutionArchiveStore`/`AppliedExecutionRecord` and
  `ClosedPositionArchiveStore`/`validate_closed_position_record`;
  `ExecutionPortfolioFoundation.__init__` now requires `applied_archive`/
  `closed_archive`, adds `_hydrate_sidecars`; `apply_confirmed` rewritten
  around the immutable indexes and the new crash-ordered archive appends
  (plus two test-only injection hooks); `_close` now returns the closed
  record instead of mutating a working-state collection; `_validate_state`
  validates the two checkpoints' shape instead of `closed_positions`.
  **Remediation (H-1/M-3):** `ClosedPositionIndex` gained
  `sequence_by_position_id` (populated by `ClosedPositionArchiveStore.load_index()`)
  so a sequence-aware closed identity is derivable outside the store;
  `AppliedExecutionArchiveStore.load_index()`'s docstring corrected per M-3
  (no production behavior changed).
- `core/financial_state_bootstrap.py` — new `DEFAULT_APPLIED_EXECUTIONS_FILE`
  / `DEFAULT_CLOSED_POSITIONS_FILE` constants and parameters;
  `_bootstrap_financial_state` gains `FINANCIAL_MIGRATION_REQUIRED` handling
  and the cross-checkpoint construction described above. **Remediation
  (M-1):** new `_classify_financial_foundation_reason()` maps
  `foundation.diagnostics()["reason"]` to a fixed, enumerable, data-free
  token before it becomes `reason_code`; `_bootstrap_financial_state`'s
  `execution_financial_state` branch now calls it instead of using the raw
  diagnostic directly.
- `core/application.py` — new `EXECUTION_APPLIED_EXECUTIONS_FILE` /
  `EXECUTION_CLOSED_POSITIONS_FILE` constants; `_build_financial_services`
  wires both sidecar stores into `ExecutionPortfolioFoundation`. Not
  touched by remediation.
- `tools/migrate_execution_financial_state.py` (new) — operator migration
  tool described above. **Remediation (H-1):** new `_closed_identity()`
  helper; the pre-existing-closed-sidecar comparison now uses
  `(sequence, payload)` identity instead of payload alone; new
  `_verify_post_append()` hard-gates the v1→v2 rewrite on both sidecars
  reloading, from disk, to exactly the expected complete output; module
  docstring corrected to describe the actual (closed-then-applied append,
  then verify, then rewrite) protocol.
- `docs/adr/0005-operator-bootstrap-runbook.md` — reason-code table gained
  `FINANCIAL_MIGRATION_REQUIRED` (original package), plus the nine
  cross-checkpoint/sidecar-validation tokens `_classify_financial_foundation_reason()`
  can produce (remediation, M-1). No other documentation was touched by
  either pass.

No `core/execution_manager.py` change: confirmed by direct inspection that
it consumes `portfolio_foundation` exclusively through `.snapshot()` and
`.diagnostics()`, neither of which exposed or exposes `closed_positions`/
`applied_executions`, and reads only `snapshot()["positions"]` /
`snapshot()["cash"]` beyond that — both shapes are unchanged by this
package.

## Test Files Changed (fixture updates, assertions otherwise unchanged)

`ExecutionPortfolioFoundation`'s constructor now requires `applied_archive`/
`closed_archive`, an intentional, unconditional break per the owner's
ruling that both collections move out of the working snapshot — not an
optional/backward-compatible parameter the way Block 5H's reservation
`archive` was, because there is no legitimate "opt out of sidecar tracking"
case for a schema that no longer has anywhere else to put this data. Seven
pre-existing test files construct `ExecutionPortfolioFoundation` directly
and needed their construction call sites updated to pass real sidecar
stores; three of them (`test_block5e_fee_settlement_accounting.py`,
`test_block5g_closed_position_lifetime_identity.py`, and
`tests/test_phase4_execution_position_portfolio_foundation.py`) also read
`closed_positions` directly from the working state or its raw JSON and were
updated to read the closed-archive sidecar (via `_closed_by_position_id` or
a small local `sidecars()`/`_sidecars()` helper deriving each store's
sidecar paths from its own path) instead — the data moved, so the
assertion had to move with it. Every assertion's *expected value* is
unchanged; only where the value is read from changed.

- `tests/test_block2c_financial_state_bootstrap.py` — 3 call sites, mechanical.
- `tests/test_block3_bootstrap_policy_consistency.py` — 1 call site, mechanical.
- `tests/test_block5f_reservation_capital_reclamation.py` — `_foundation()`
  helper + 3 restart call sites now thread the same sidecar stores across
  simulated restarts (this file never read `closed_positions` directly).
- `tests/test_block5e_fee_settlement_accounting.py` — `_foundation()` helper
  + one `_state["closed_positions"]` read moved to `_closed_by_position_id`.
- `tests/test_phase4_execution_manager_runtime_cutover.py` — `durable_book()`
  helper + 1 call site, mechanical.
- `tests/test_block5g_closed_position_lifetime_identity.py` — `_foundation()`
  helper, `_closed_on_disk()` helper rewritten to read the closed archive
  instead of `store.load()["closed_positions"]`, and every
  `_state["closed_positions"]` / raw-JSON `closed_positions` read moved to
  the archive or `_closed_by_position_id` accordingly.
- `tests/test_phase4_execution_position_portfolio_foundation.py` — `foundation()`
  helper + 4 direct restart/corruption call sites, plus 2 `store.load()["closed_positions"]`
  reads moved to the closed archive via a new local `sidecars()` helper.
- `tests/test_block3_bootstrap_state_validation.py` — **unchanged**, verified
  by direct trace (see "Migration-Required Signal" above) and by the
  regression run.
- `tests/test_block5i_durable_financial_state_sidecars.py` (new) — this
  package's own discriminating suite. **Remediation:** `test_l_*` renamed
  (L-1, no assertion changed - see "Independent Review Remediation" above);
  `test_x_*`'s misleading crash-order comment corrected (same L-2 protocol-
  ordering correction, applied consistently); ten tests added -
  `test_ad_*` through `test_ah_*` (H-1), `test_ai_*` (M-1), and the
  seven-case parametrized `test_aj_*` (M-2).

## Findings Closed

| ID | Severity | Status | Closure basis |
|---|---|---|---|
| 5I BLOCKER | BLOCKING | CLOSED | externalized applied authority without a checkpoint would have let a durable sidecar append survive a crash with nothing tying it back to a confirmed financial mutation; `applied_checkpoint`/`closed_checkpoint` plus `_hydrate_sidecars`' cross-check close this (`test_m`, `test_n`, `test_ab`, `test_ac`) |
| HIGH | HIGH | CLOSED | applied_executions load validation gap — a torn/malformed/conflicting sidecar is never silently treated as empty or partially trusted; `load_index()` fails closed on any of these (`test_o`, `test_p`, `test_q`, `test_r`, `test_s`) |
| MEDIUM #1 | MEDIUM | CLOSED | O(lifetime) request-id scan — `identity in applied_executions.values()` (an O(n) scan of the entire history on every single apply) replaced by the O(1) `by_idempotency_key` index |
| MEDIUM #2 | MEDIUM | CLOSED | schema mismatch vs migration ambiguity — a v1 file previously surfaced the same generic `FINANCIAL_STATE_RECOVERY_REQUIRED` as any other corruption; `FINANCIAL_MIGRATION_REQUIRED` is now distinct and never generic "move aside/delete state" guidance |
| MEDIUM #3 | MEDIUM | CLOSED | historical collections causing working-snapshot growth — `closed_positions`/`applied_executions` no longer live in the working file at all; its size now tracks live state only |

## Carried Forward (explicitly NOT fixed by this package)

- Transaction journal (`ExecutionTransactionJournal`) growth — untouched,
  still a full-file rewrite per write.
- Audit log (`AuditEventStore`) growth/retention — untouched.
- `ExecutionIdempotencyStore.save()` full-file rewrite + fsync per write
  (B5H-0-7) — untouched.
- `ExecutionManager.reset()` idempotency/journal asymmetry (B5H-0-9) —
  untouched.
- No operator reconciliation tool for an already-corrupt `SOURCE_DISAGREEMENT`
  environment (B5H-0-12) — untouched.
- Startup O(history) index rebuild for either new sidecar — accepted per
  owner decision 8, not addressed.
- No retention/pruning of applied executions or closed positions — by
  owner decision 9, deliberate, not a gap.

None of the above is claimed fixed by this package.

No new BLOCKING finding was introduced. One HIGH (H-1) and three MEDIUM
(M-1, M-2, M-3) findings **were** introduced by this package's own code and
tests, caught by independent review, and are CLOSED by remediation — see
"Independent Review Remediation" above. This is not a "0 introduced"
package; it is a package whose introduced findings were found and closed
before commit.

## PAPER / LIVE

Unchanged. PAPER remains the default and LIVE authority remains denied.
This package touches financial-state persistence and one operator
migration tool only; no execution-mode or venue-adapter path is touched.

## Push Status

NOT PUSHED. Committed locally only on `feat/block3-execution-safety`, on
top of parent HEAD `f2901741600a872cc5a9451ab15e25548cc7342b`
(`feat: add durable reservation archive`).

No `git push` was run at any point in this package. Staging and the local
commit were performed only after this document had been independently
reviewed against the final code — the review that produced "Independent
Review Remediation" above is that review, and this document was updated to
match the remediated code before staging.

## Validation Evidence

All commands ran against the working tree in this session with an
isolated, ASCII `--basetemp` outside the repository (this host's default
tmp-path root is broken for pytest under the `HUAWEİ` profile directory),
per this project's standing testing convention. Every fixture in the new
and amended tests seeds into `tmp_path`; no command wrote to the operator's
real runtime state (`memory_data/`, root-level `paper_trades.json`) —
confirmed by `git status --short` showing only the intended source files
as changed.

Pre-remediation baseline (32 / 157 / 15 / 2273 passed) was established by
the original 5I evidence pass and is not reproduced here, per this
project's standing non-reproduction convention — remediation validation
below answers only what changed.

**Remediation targeted group** (Package 5I focused suite, including the 13
new remediation tests and the L-1 rename, plus financial-state bootstrap
reason-code/output-safety coverage): **113 passed in 23.92s.**
`python -m pytest tests/test_block5i_durable_financial_state_sidecars.py tests/test_block2c_financial_state_bootstrap.py tests/test_block3_bootstrap_policy_consistency.py tests/test_block3_bootstrap_state_validation.py tests/test_block3_operator_bootstrap_cli.py -q --basetemp=<isolated>`

**Full `tests/` suite** (run exactly once, on the final remediation code
state, because production code changed): **2286 passed in 226.64s.**
`python -m pytest tests/ -q --basetemp=<isolated>`

**Full architecture suite:** not re-run in this remediation pass — no
import/layer dependency changed (see "Exact Test Counts"); the
pre-remediation 15-passed baseline still applies unchanged.

## Exact Intended Package 5I File List

Total: **14 committed files** — 4 core production, 1 new operator tool, 1
doc, 7 tests amended, 1 test new, plus this evidence document.

Core production (3):
- `core/execution_portfolio_foundation.py`
- `core/financial_state_bootstrap.py`
- `core/application.py`

Operator tooling (1, new):
- `tools/migrate_execution_financial_state.py`

Documentation (1):
- `docs/adr/0005-operator-bootstrap-runbook.md`

Tests (8):
- `tests/test_block2c_financial_state_bootstrap.py` (amended)
- `tests/test_block3_bootstrap_policy_consistency.py` (amended)
- `tests/test_block5e_fee_settlement_accounting.py` (amended)
- `tests/test_block5f_reservation_capital_reclamation.py` (amended)
- `tests/test_block5g_closed_position_lifetime_identity.py` (amended)
- `tests/test_phase4_execution_manager_runtime_cutover.py` (amended)
- `tests/test_phase4_execution_position_portfolio_foundation.py` (amended)
- `tests/test_block5i_durable_financial_state_sidecars.py` (new)

Evidence (1):
- `docs/evidence/block5i_durable_financial_state_sidecars.md` (new, this
  document)

`tests/test_block3_bootstrap_state_validation.py` was inspected and run but
required no edit (see "Migration-Required Signal" above); it is not part of
the changed-file list. No unrelated or generated file is in scope for this
package.

## Limits of This Evidence

This package closes the 5I BLOCKER and the HIGH/MEDIUM findings listed
above for `closed_positions`/`applied_executions` externalization and their
checkpoint-backed crash safety. It does not address, and makes no claim
about: transaction-journal growth, audit-log growth/retention, the
idempotency store's full-file rewrite per save, `ExecutionManager.reset()`'s
idempotency/journal asymmetry, `SOURCE_DISAGREEMENT` reconciliation
tooling, or the O(history) cost of rebuilding either sidecar's index at
startup — none of these were touched, per owner decision 7/8. It does not
change BUY/SELL settlement arithmetic, the partial-close pro-rata split,
average-entry-price computation, risk/reservation admission, or any
capital-reservation semantics — all proven unchanged by the directly
affected regression run above, and specifically pinned exact by `test_d_*`
for the sequence it covers. Migration is exclusively an explicit,
operator-invoked action; nothing in this package causes it to run
automatically at any point in `AtlasApplication`'s lifecycle — a v1
directory stays fail-closed with `FINANCIAL_MIGRATION_REQUIRED` until an
operator deliberately runs the tool.
