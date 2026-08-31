# Atlas Block 5 / Package 5H Freeze Evidence

## Status

Package 5H closure candidate: PASS
BLOCKING: 0 remaining (0 introduced)
HIGH: 0 remaining (0 introduced)
MEDIUM NEW: 0

## Package

Block 5 / Package 5H — Capital Reservation Working Set & Immutable Archive
(`core/capital_reservation.py`, `core/financial_state_bootstrap.py`,
`core/application.py`, `tools/migrate_capital_reservations.py`).

## Objective

Block 5F (`docs/evidence/block5f_freeze_evidence.md`) corrected
`CapitalReservationLedger`'s live-encumbrance formula but explicitly
deferred its own finding **F4 — reservation-store growth**:
`CapitalReservationLedger` never removed a COMMITTED or RELEASED
reservation from `_items`, so `JsonReservationStore`'s persisted file grew
by one entry per reservation for the runtime's entire lifetime, with no
compaction or archival — an unbounded, full-file-rewrite-per-write store.

This package closes F4 for the working store, and closes a second,
previously unrecorded defect discovered while designing the fix:

**B5H-3 — naive terminal prune / replay re-arm (newly identified this
package, closed by construction).** The obvious fix for F4 — delete a
reservation from `_items` once it reaches COMMITTED/RELEASED — has a defect
of its own: `CapitalReservationLedger.reserve()`'s collision check only
ever consulted the live working set. Delete a terminal record outright and
its `reservation_id` becomes free again; a replayed or maliciously reused
id could then re-arm as a brand-new RESERVED reservation with **no
collision at all**, silently re-entering a transaction the system had
already durably settled. This was never shipped — it was identified during
this package's own design investigation, the same way 5F's F3/F4/F5 were
identified during 5F's investigation and recorded there for the first time.
It is closed by construction, not by a special-case check: terminal records
are never deleted, only moved to an immutable archive that `reserve()`'s
collision check and `get()`'s lookup both consult permanently (Section
"E — archive-aware collision", `test_e_*`).

## Final Architecture: v2 Working Set + Immutable Archive

**Working set** (`JsonReservationStore`, schema bumped
`atlas-capital-reservations-v1` → `atlas-capital-reservations-v2`): holds
only live/unresolved reservations — RESERVED and INDETERMINATE — once a
ledger with a configured archive has compacted. Same atomic
temp-file-write → flush → fsync → `os.replace` durability as before; no
change to that mechanism, only to which statuses accumulate in it over
time.

**Archive** (`ReservationArchiveStore`, new): an immutable, append-only
JSON-Lines file (`capital_reservations_archive.jsonl`), one canonical
`CapitalReservation.to_dict()` payload per line — `reservation_id`,
`request_id`, `amount` as an exact Decimal string, `status`, `version` —
for a COMMITTED or RELEASED reservation only. Every append is durable
(write → flush → `os.fsync`) before the call returns, mirroring
`AuditEventStore`'s existing append-only jsonl pattern
(`core/audit_event_store.py`) rather than inventing a new one. `append` is
the *only* write operation this store performs: no line is ever rewritten,
reordered, or deleted. No SQLite/PostgreSQL or other external dependency
was introduced.

There is no age retention, count retention, expiry horizon, or automatic
history deletion anywhere in this design. A terminal reservation is moved
from the working file to the archive; it is never deleted from Atlas
history, and it remains permanently addressable by `reservation_id` through
`CapitalReservationLedger.get()`.

Allowed archived statuses: **COMMITTED, RELEASED only.** RESERVED or
INDETERMINATE appearing in the archive is corruption and fails closed
(`ReservationArchiveStore.append()` refuses to write one at all;
`load_index()` refuses to load a line containing one, raising
`ReservationArchiveCorruptError` — `test_k2_archive_containing_live_status_fails_closed`).

## Archive Loading / Index and Ledger Read Semantics

At construction, `CapitalReservationLedger.__init__` loads the working set
exactly as before, then (if an `archive` was supplied) loads the archive
into an in-memory index via `ReservationArchiveStore.load_index()`:

- **Identical duplicate archive lines** (the same reservation_id appended
  twice with the same payload — a retried compaction append after a crash)
  are idempotently deduplicated, not an error (`test_j`,
  `test_crash_c_*`).
- **Same reservation_id, differing payload, within the archive itself**
  raises `ReservationArchiveConflictError` (`test_k3`).
- **Malformed or torn lines** (bad JSON, wrong shape, a live status) raise
  `ReservationArchiveCorruptError` — never silently treated as an empty
  archive (`test_k1`, `test_k2`, `test_k4`).
- **The same reservation_id present in both the working set and the
  archive** is tolerated *only* when the two copies agree field-for-field
  (an interrupted compaction — the archive append durably succeeded but the
  working-set rewrite that would drop the record never completed). Any
  disagreement raises and the ledger comes up `ready is False`
  (`test_h`, `test_i`, `test_crash_b_d`).

Any of the above failing during construction leaves the ledger
`ready is False`, exactly like every other pre-5H load failure — no new
failure-handling shape was introduced, the archive load was folded into the
existing single `try/except Exception: self._ready = False` block.

**`CapitalReservationLedger.get(reservation_id)`** now checks the working
set first, then the archive index. A COMMITTED/RELEASED reservation
`compact()` has moved out of the working set is still returned exactly, so
historical reservations remain queryable forever (`test_a`, `test_b`,
`test_g`).

**`reserve()`** now checks the archive *before* the working-set collision
check: a `reservation_id` already present in the archive raises
unconditionally — unlike the pre-existing working-set collision check,
there is **no idempotent same-request/same-amount carve-out**, because an
archived id is permanently consumed history and can never be re-created as
RESERVED regardless of what is requested (`test_e`). This is the specific
mechanism that closes B5H-3.

**`commit()` and `release()`/`mark_indeterminate()` (via `_transition()`)**
were changed to look up the current record through the same archive-aware
path `get()` uses, instead of the working set alone. This was not in the
original task text — it was discovered during implementation: `get()`
becoming archive-aware meant `get(id) is not None` no longer implied "found
in the working set," but `core/execution_manager.py`'s
`_release_capital_reservation` / `_commit_capital_reservation` /
`_mark_capital_indeterminate` all guard with
`if self.reservation_ledger.get(request_id) is None: return True` before
calling `release()`/`commit()`/`mark_indeterminate()`. Left unfixed, a
replayed call against an already-archived id would have hit a spurious
`KeyError` instead of the pre-existing idempotent-same-status return —
and for `_release_capital_reservation` specifically, that exception path
**halts the runtime** (`execution_halted = True`,
`halt_reason = "CAPITAL_RESERVATION_RELEASE_FAILED"`). Because archived
records are always terminal (COMMITTED/RELEASED) and the transition-allow
list only ever permits transitions *from* RESERVED, an archive-sourced
lookup can only ever reach the existing idempotent-return or the existing
invalid-transition error inside `commit()`/`_transition()` — never the
working-set mutation path — so this fix adds no new mutation surface, only
closes the spurious-halt gap.

**`_live_encumbered` / `available` / `active_reserved_capital`** are
unchanged: still computed from the live working set (`self._items`) alone.
The archive never contributes to either figure (`test_a` through `test_d`,
`test_m`).

## Compaction

`CapitalReservationLedger.compact()` (new, explicit entry point — never
invoked automatically by `AtlasApplication`, `ExecutionManager`, or
`MarketLoop`):

1. Requires `ready is True` and a configured `archive`; otherwise raises
   `RuntimeError` and touches nothing.
2. Selects every working-set record whose status is COMMITTED or RELEASED.
3. For each one, in turn:
   a. If not already present identically in the archive index: append it
      (durable: write → flush → fsync) and record it in the in-memory
      archive index.
   b. If already present with a *different* payload: raise `RuntimeError`
      (defense in depth — `reserve()`'s archive-collision guard and
      `__init__`'s cross-store check should make this unreachable in
      practice).
   c. Remove it from the working set and atomically re-save the working
      file via the existing `_persist()` (same rollback-on-failure
      contract every other mutation already uses).

RESERVED and INDETERMINATE records are never selected in step 2, so no
compaction failure — partial or total — can ever free capital that is
still reserved or indeterminate (`test_m`). Compaction never mutates an
already-archived line and never deletes an archive line; the working-set
rewrite in step (c) is the only place any file is rewritten in place, and
it never touches the archive file.

**Idempotent and crash-safe by construction.** Because step (a) is skipped
when the archive already holds an identical copy, calling `compact()`
again after an interruption between (a) and (c) simply finishes the move —
it never re-appends a duplicate line and never loses the record
(`test_h`, `test_crash_b_d`).

## Crash Atomicity — Injection Points A–F

| Point | Scenario | Test | Result |
|---|---|---|---|
| A | Failure before any archive write | `test_crash_a_*` | `compact()` raises; working file and archive file both byte-unchanged; ledger stays `ready` |
| B | Crash between archive durability and working-set rewrite | `test_h_*`, `test_crash_b_d_*` | Restart tolerates the record present in both stores; a follow-up `compact()` finishes cleanly |
| C | Archive write/fsync failure | `test_crash_c_*` | `compact()` raises; working set untouched; a retry after the fault clears completes with exactly one archived copy (duplicate-line tolerance covers a partial pre-fsync write) |
| D | Working-file save failure after a successful archive append | `test_crash_b_d_*` | `compact()` raises `RuntimeError`, ledger becomes `ready is False` (same contract as every other `_persist`-backed mutation); archive already durably holds the record |
| E | Restart with the record present in both archive and working file | `test_h_*`, `test_crash_b_d_*` | Restart succeeds when the two copies agree field-for-field |
| F | Duplicate archive append retry | `test_j_*`, `test_crash_c_*` | `load_index()` deduplicates identical lines idempotently |

Required property proven throughout: no reservation history is ever lost.
When the working set and archive both contain the same terminal record,
restart succeeds (`test_h`, `test_crash_b_d`). When they conflict, restart
fails closed (`test_i`). A torn/malformed archive line is never silently
treated as an empty archive (`test_k1`, `test_k4`). No compaction failure —
at any injection point — frees RESERVED or INDETERMINATE capital
(`test_m`, and by construction: compaction never selects those statuses).

## Schema / Bootstrap Contract

Working schema is `atlas-capital-reservations-v2`. There is **no runtime
auto-migration**: `JsonReservationStore.load()` raises the new
`ReservationSchemaMigrationRequiredError` (a `ValueError` subclass) the
instant it sees the legacy `atlas-capital-reservations-v1` tag, before
parsing a single record (`test_n1`). Any other unrecognized schema string
still raises the pre-existing generic `ValueError("unsupported reservation
state schema")`, unchanged.

`core/financial_state_bootstrap.py`'s `_bootstrap_reservation_state` now
requires, for `VALID_EXISTING`, all three: the working file loads under
v2, the archive (if one exists on disk) loads with no internal corruption
or conflict, and no reservation_id present in both working set and archive
disagrees between them. New/precise reason codes, folded into the
existing single `"capital_reservations"` result (the 3-store result shape
`tools/bootstrap_financial_state.py` and its CLI tests depend on is
unchanged — no fourth row was added):

- `RESERVATION_MIGRATION_REQUIRED` — working file is still v1
- `RESERVATION_ARCHIVE_UNREADABLE` — archive present but an OS-level read
  failure
- `RESERVATION_ARCHIVE_CORRUPT` — archive present but internally malformed
- `RESERVATION_ARCHIVE_CONFLICT` — archive internally conflicting, or
  disagreeing with the working set for a shared id

(`test_n2`, `test_q`.) An absent archive is not an error — it is treated
as a valid, empty archive everywhere (ledger construction, bootstrap
validation, and the migration tool alike).

**A pre-existing test's fixture, not its assertions, needed updating.**
`tests/test_block3_bootstrap_state_validation.py::test_reservation_state_duplicate_reservation_id_is_invalid_existing`
hand-wrote a payload tagged `"schema": "atlas-capital-reservations-v1"` —
current at the time it was written, before v1/v2 existed as a distinction.
Under the new contract every v1-tagged file fails closed with
`RESERVATION_MIGRATION_REQUIRED` before duplicate-id detection ever runs,
which would have silently changed this test's meaning from "duplicate id
detection" to "migration-required detection." This was discovered by
running the regression suite, not assumed: the fixture's schema tag was
corrected to `"atlas-capital-reservations-v2"` (a one-line change); its
assertions (`INVALID_EXISTING` / `RESERVATION_DUPLICATE_ID`) are
byte-identical to before, because the test's actual subject — duplicate-id
detection — is unaffected by the schema-version distinction. This was the
only *pre-existing* test in the repository referencing the v1 schema
string; the sole remaining reference is the new 5H suite's own
`_write_v1_file` helper, which writes a v1 file deliberately in order to
prove the migration-required path (`test_n1`, `test_n2`, `test_o`).

## Operator Migration Tool

`tools/migrate_capital_reservations.py` (new), mirroring
`tools/bootstrap_financial_state.py`'s CLI shape (`_UsageExitParser`,
`--json`, fixed exit-code tiers, `sanitize_sensitive_text` on all rendered
output) but as a self-contained tool: never invoked from
`AtlasApplication`, no automatic-invocation flag of any kind.

`python tools/migrate_capital_reservations.py --state-directory PATH [--dry-run] [--json]`

Migrates in place: `capital_reservations.json` is read as v1 and rewritten
as v2 (RESERVED/INDETERMINATE only); `capital_reservations_archive.jsonl`
receives every COMMITTED/RELEASED record. Every reservation is preserved
exactly — id, request_id, Decimal amount, status, version — via
`CapitalReservation.from_dict()`/`to_dict()`, never a hand-rolled parser
(`test_o`).

Exit codes: `0` MIGRATED / ALREADY_MIGRATED / (dry-run) WOULD_MIGRATE;
`1` CLI usage error; `2` refused — source absent/invalid, or an existing
archive that does not provably match this exact migration (nothing
touched); `3` FAILED — an unexpected write-phase error.

**Never silently overwrites.** If an archive already exists at the target
path, the tool recomputes the migration from the current source and
compares record-for-record; it proceeds only if every existing archived
record matches exactly what this source would produce, and refuses
(`REFUSED_ARCHIVE_CONFLICT`, exit 2, nothing written) otherwise
(`test_p1`). Refuses a corrupt or duplicate-id source outright
(`test_p3`). `--dry-run` reports counts and touches nothing (`test_p4`).

**Idempotent and resumable.** Re-running against an already-v2 source is a
no-op that still validates the archive if one is present
(`ALREADY_MIGRATED`, `test_p2`). Re-running after a prior run crashed
partway — some archive records durably appended, the working-file rewrite
never reached — resumes safely: only the missing archive records are
appended, then the working file is written (`test_p5`). A CLI-level
end-to-end check (`test_p6`, via `subprocess`) confirms the exit-code
contract for SOURCE_ABSENT → MIGRATED → ALREADY_MIGRATED across real
process invocations.

## Application Wiring

`core/application.py` gained `CAPITAL_RESERVATION_ARCHIVE_FILE =
"capital_reservations_archive.jsonl"` alongside the existing
`CAPITAL_RESERVATION_STATE_FILE` constant, and
`_build_financial_services` now constructs the reservation ledger with
both:

```python
self.reservation_ledger = CapitalReservationLedger(
    JsonReservationStore(self.state_directory / CAPITAL_RESERVATION_STATE_FILE),
    self.risk_policy.allocatable_capital,
    archive=ReservationArchiveStore(self.state_directory / CAPITAL_RESERVATION_ARCHIVE_FILE),
)
```

No other execution authority in `core/application.py` was touched. No
automatic compaction was wired anywhere — `compact()` and the migration
tool are both exclusively explicit, operator-invoked actions.

## MarketLoop Sizing-Replay-Conflict Result

Unaffected in production behaviour, and now proven for the archive-only
case specifically. `MarketLoop._apply_position_sizing` compares a fresh
sizing proposal against `reservation_ledger.get(request_id)`; since `get()`
reads through the archive, a request identity whose only surviving record
is a compacted, archive-only COMMITTED reservation still produces a clean
`SIZING_REPLAY_CONFLICT` refusal when re-priced differently — exercised
through the real `AtlasApplication` / `ExecutionManager` / `MarketLoop`
composition, not a mock (`test_f`).

## Restart / Bootstrap Result

A ledger constructed fresh after `compact()` (`test_g`), after an
interrupted compaction (`test_h`), and after a full v1→v2+archive
migration (`test_q`) comes up `ready is True` with every historical record
exact. `bootstrap_financial_state(..., verify_only=True)` against a
freshly migrated directory reports `VALID_EXISTING` for
`capital_reservations` (`test_q`).

## Before / After Growth Result

**Before (5F, F4 open):** the working-set file's record count, and
therefore its size, grew by exactly one entry per reservation for the
runtime's entire lifetime — every terminal reservation stayed in the same
file forever, rewritten in full on every unrelated mutation.

**After (this package):** `test_l_working_file_size_depends_on_live_records_not_lifetime_count`
runs 40 reserve→commit→compact cycles. After every single cycle's
`compact()`, the working file holds zero live records and — proven
directly on file size, not inferred — is the *same number of bytes*
regardless of whether it is the 1st or the 40th cycle
(`len(set(sizes_after_compact)) == 1`). All 40 terminal records remain
exactly queryable via `ledger.get()`, sourced from the archive. Leaving one
reservation RESERVED (not compacted) afterward grows the working file
again, isolating that its size tracks live record count, not lifetime
terminal count.

## Exact Test Counts

- New focused suite: **29 passed**
  (`tests/test_block5h_capital_reservation_archive.py`)
- Directly affected regression (11 files, one command): **276 passed**
- Full architecture suite: **15 passed** (run once; `core/application.py`
  changed, and a new `tools/` file was added)
- Full `tests/` suite (once, final code state): **2241 passed**

2241 = 2212 (5H-0's prior full-suite baseline, `a814260`) + 29 (this
package's new focused suite). No other test file's count changed — this
package's production changes are additive-only for every existing call
site: all 25 pre-existing `CapitalReservationLedger(store, total)`
two-argument construction sites across `tests/` continue to work
unchanged, because `archive` is an optional keyword defaulting to `None`,
and a `None` archive behaves exactly as an always-empty one.

## Findings Closed

| ID | Severity | Status | Closure basis |
|---|---|---|---|
| F4 | MEDIUM | CLOSED for terminal-reservation accumulation in the working store | `ReservationArchiveStore` + `compact()`; working-file size now tracks live record count, not lifetime terminal count (`test_l`) |
| B5H-3 | — (identified and closed within this package) | CLOSED by immutable read-through archive | `reserve()`'s archive-aware collision check makes an archived id permanently unre-armable as RESERVED (`test_e`); `get()` reads through the archive so history is never lost by deletion |

## Carried Forward (explicitly NOT fixed by this package)

- **B5H-0-7** — `ExecutionIdempotencyStore.save()` remains a full-file
  rewrite + fsync on every write; O(n) growth accepted temporarily.
- **B5H-0-9** — `ExecutionManager.reset()` resets the idempotency store but
  not the transaction journal (asymmetry).
- **B5H-0-12** — no operator reconciliation tool exists for an already
  corrupt `SOURCE_DISAGREEMENT` environment.
- `applied_executions` growth (`ExecutionPortfolioFoundation`) — explicitly
  out of scope for this package per the task contract; not referenced by
  any file this package touched.
- `closed_positions` growth — untouched.
- Transaction journal (`ExecutionTransactionJournal`) growth — untouched,
  still a full-file rewrite per write.
- Audit log (`AuditEventStore`) growth — untouched (it was already
  append-only; this package's `ReservationArchiveStore` follows the same
  pattern for a different store, but no compaction/retention exists for
  the audit log itself).

None of the above is claimed fixed by this package.

No new BLOCKING, HIGH, or MEDIUM finding is introduced.

## PAPER / LIVE

Unchanged. PAPER remains the default and LIVE authority remains denied.
This package touches reservation persistence and one operator migration
tool only; no execution-mode or venue-adapter path is touched.

## Push Status

NOT PUSHED. Committed locally only on `feat/block3-execution-safety`, on
top of parent HEAD `a81426066b6ac110946fa01cf56b554201986435`
(`feat: align execution evidence authorities`).

No `git push` was run at any point in this package. Staging and the local
commit were performed only after this document had been independently
reviewed against the final code; the commit exists on the local branch
alone and no remote has received it.

## Validation Evidence

All commands ran against the working tree in this session with an
isolated, ASCII `--basetemp` outside the repository (this host's default
tmp-path root is broken for pytest under the `HUAWEİ` profile directory),
per this project's standing testing convention. Every fixture in the new
test file seeds into `tmp_path`; no command wrote to the operator's real
runtime state (`memory_data/`, root-level `paper_trades.json`).

**Package 5H focused suite:** 29 passed in 2.71s.
`python -m pytest tests/test_block5h_capital_reservation_archive.py -q --basetemp=<isolated>`

**Directly affected regression** (5F reservation capital reclamation, 5C
sizing/replay, Block 3 exception atomicity, financial-state
bootstrap/state-validation ×3, operator bootstrap CLI, application
composition wiring, reservation admission atomicity, Phase 3 risk/capital
foundation): 276 passed in 13.93s.
`python -m pytest tests/test_block5f_reservation_capital_reclamation.py tests/test_block5c_upstream_sizing_authority.py tests/test_block3_execution_exception_atomicity.py tests/test_block3_bootstrap_state_validation.py tests/test_block3_bootstrap_policy_consistency.py tests/test_block2c_financial_state_bootstrap.py tests/test_block3_operator_bootstrap_cli.py tests/test_block2_risk_service_composition_wiring.py tests/architecture/test_composition_root_wires_canonical_risk_services.py tests/test_block2_m1_reservation_admission_atomicity.py tests/test_phase3_risk_capital_foundation.py -q --basetemp=<isolated>`

**Full architecture suite** (run once — `core/application.py` changed and
a new `tools/` file was added): 15 passed in 53.93s.
`python -m pytest tests/architecture/ -q --basetemp=<isolated>`

**Full `tests/` suite (once, after all remediation complete):** 2241
passed in 75.09s.
`python -m pytest tests/ -q --basetemp=<isolated>`

## Exact Intended Package 5H File List

Total: **7 committed files** — 6 code-change files (3 core production,
1 new operator tool, 1 test amended, 1 test new) plus this evidence
document, which is committed alongside them but is not itself a code
change.

Core production (3):
- `core/capital_reservation.py`
- `core/financial_state_bootstrap.py`
- `core/application.py`

Operator tooling (1, new):
- `tools/migrate_capital_reservations.py`

Tests (2):
- `tests/test_block3_bootstrap_state_validation.py` (amended: one schema
  string literal, `v1` → `v2`, in a single fixture; assertions unchanged)
- `tests/test_block5h_capital_reservation_archive.py` (new)

Evidence (1):
- `docs/evidence/block5h_capital_reservation_archive.md` (new, this
  document)

`applied_executions` is out of scope and was not referenced by any changed
file. No unrelated or generated file is in scope for this package.

## Limits of This Evidence

This package closes F4 for the reservation working store's own growth and
closes B5H-3 by construction. It does not address, and makes no claim
about: B5H-0-7 (idempotency store O(n) rewrite per save), B5H-0-9
(`ExecutionManager.reset()` idempotency/journal asymmetry), B5H-0-12 (no
reconciliation tool for an independently corrupt disagreement),
`applied_executions` growth, `closed_positions` growth, transaction-journal
growth, or audit-log growth/retention — none of these files were touched.
It does not change 5F live-encumbrance semantics, COMMITTED historical
semantics, RESERVED admission, INDETERMINATE recovery blocking, the exact
settled-reservation-amount behaviour from 5E, `SIZING_REPLAY_CONFLICT`
detection logic, completed-request replay, the transaction journal,
execution idempotency, or risk/exposure arithmetic — all proven unchanged
by the directly-affected regression run above. `compact()` and the
migration tool are both exclusively explicit, operator-invoked actions;
nothing in this package causes compaction to happen automatically at any
point in `AtlasApplication`'s lifecycle, so a long-running production
process will still accumulate terminal records in the working file until
an operator runs `compact()` — this package provides the mechanism and
proves its safety, not a scheduler.
