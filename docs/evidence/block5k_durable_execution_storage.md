# Atlas Block 5 / Package 5K Freeze Evidence

## Status

Package 5K closure candidate: PASS.
BLOCKING: 0 remaining (0 introduced)
HIGH: 0 remaining (0 introduced)
MEDIUM NEW: 0 remaining (0 introduced)

Parent HEAD: `2b79c71` ("feat: harden execution authority recovery").

Nothing was pushed.

## Package

Remove the remaining execution-storage write amplification without weakening
replay, durability, crash recovery, or authority semantics.

- **B5H-0-7** — `ExecutionIdempotencyStore.save()` rewrote its entire durable
  state as history grew.
- **transaction journal write growth** — every lifecycle transition rewrote
  the whole journal file.
- **B5J-1** — `tools/migrate_execution_financial_state.py` embedded truncated
  raw exception text in an operator-visible reason code, deviating from
  ADR-0005's fixed-token rule.

## Exact Pre-5K Write Amplification

Measured from the parent commit's own source, not inferred.

| authority | durable write | in-memory cost per write |
| --- | --- | --- |
| `ExecutionIdempotencyStore.save()` | `json.dump` of the **whole** `completed_requests` map (`indent=2`, `sort_keys=True`) to a temp file, fsync, `os.replace` | `record()` additionally deep-copied the entire registry for rollback before writing a byte |
| `ExecutionTransactionJournal.save()` | `json.dump` of the **whole** `entries` map, fsync, `os.replace` | `prepare()`, `_mark_terminal()`, and `mark_unknown()` each deep-copied every entry for rollback |

So completing request *N* serialized *N* records and copied *N* records, and
each of a request's journal transitions did the same. Both authorities are
permanent and unpruned by design (Blocks 5H-0 and 5J), so *N* only grows.

## Chosen Durable Format

Both authorities are now versioned append-only JSON-Lines logs written
through one shared physical primitive, `core/durable_append_log.py`.

```
{"log":"execution_idempotency","version":2}
{"request_id":"...","result":{...},"sequence":0}
{"request_id":"...","result":{...},"sequence":1}
```

```
{"log":"execution_transaction_journal","version":2}
{"entry":{...},"request_id":"...","sequence":0,"state":"PREPARED"}
{"entry":{...},"request_id":"...","sequence":1,"state":"COMMITTED"}
```

The primitive owns line framing, the versioned header, the reserved
`sequence` field, durable append (write → flush → fsync), atomic rewrite
(temp file → fsync → `os.replace`), and fail-closed reading. It mirrors the
existing Atlas JSON-Lines convention established by
`AppliedExecutionArchiveStore` / `ClosedPositionArchiveStore` (Block 5I) and
`ReservationArchiveStore` (Block 5H), including their tolerance of a
byte-identical repeat of the immediately preceding record as a defence
against a storage layer duplicating a line during a torn write.

**Answer to the shared-primitive question (5K §1 G):** the two stores'
*physical* durability requirements are identical and are shared; their
*logical* models differ — one holds at most one terminal record per
`request_id`, the other an ordered lifecycle event stream — and those stay
in their own modules. No database, queue, or new dependency was introduced.

### Storage inspection answers

| question | answer |
| --- | --- |
| A. idempotency durable storage | was one JSON object rewritten on every terminal write; now append-only |
| B. journal durable storage | was full-file rewrite per transition; now append-only events |
| C. hot path | `ExecutionManager._complete_request` → `record(save=True)`; `transaction_journal.prepare` / `mark_committed` / `mark_not_committed` / `mark_unknown` |
| D. data classes | terminal results and COMMITTED outcomes are immutable correctness authority; PREPARED / COMMIT_STATUS_UNKNOWN are live lifecycle state; stats and timestamps are operational metadata |
| E. readers of the whole map | `ExecutionManager.__init__`, `CanonicalExecutionEvidenceAdapter`, `FinancialRuntimeSafetyService._authorities_agree`, `tools/reconcile_execution_authorities.py` — all keep the same fully-hydrated in-memory `entries` / `completed_requests` dicts, rebuilt by replay at startup |
| F. crash guarantees | each append is flushed and fsynced before the call reports success; each rewrite is atomic |

## Authority Semantics

Unchanged from Blocks 5H-0, 5H, 5I, and 5J, and re-asserted by the tests:

- the journal owns commit outcome; COMMITTED means the financial side effect
  actually happened;
- the idempotency store owns the terminal result a replayed `request_id` is
  answered with;
- a COMMITTED journal entry with no idempotency counterpart remains
  `SOURCE_DISAGREEMENT` and fails closed;
- neither authority prunes, truncates, or ages anything out.

### Idempotency replay model

Exactly one terminal record per `request_id` is the protocol.

- `record(save=True)` appends one line. It **refuses** to durably replace an
  existing terminal result with a different one and rolls the in-memory
  registry back, so a conflicting authority cannot be created through the
  store's API.
- On read, a repeated `request_id` with an identical payload is a harmless
  idempotent duplicate; a repeated `request_id` with a differing payload is a
  conflicting authority and fails the load closed. Neither side is chosen.
- A durable record carrying a FAILED / ERROR status is corruption — `record()`
  refuses to persist one — and fails closed rather than being filtered away.
- `remove()` and `reset()` compact the log by atomic rewrite. There is no
  tombstone record and no execution path reaches either.
- Bounded retention (`max_records`) remains the explicit test-only mode and
  keeps its whole-log rewrite; production leaves it unset and never prunes.

`execution_id` is **not** indexed globally by this store. The applied-execution
archive (Block 5I) already indexes `execution_id` and `idempotency_key`
independently, and Block 5J's reconciliation reads that archive for exactly
that proof, so a second index here would duplicate an existing authority
rather than add one.

### Journal transition model

The last event for a `request_id` is its current state. Legality is enforced
on both the write and the replay side, so a refused write never reaches the
log and a log holding an illegal transition fails closed instead of being
replayed into a state no writer could have produced.

| from | to |
| --- | --- |
| (no entry) | PREPARED, COMMITTED, NOT_COMMITTED, COMMIT_STATUS_UNKNOWN |
| PREPARED | PREPARED, COMMITTED, NOT_COMMITTED, COMMIT_STATUS_UNKNOWN |
| NOT_COMMITTED | PREPARED, COMMITTED, NOT_COMMITTED, COMMIT_STATUS_UNKNOWN |
| COMMIT_STATUS_UNKNOWN | PREPARED, COMMITTED, NOT_COMMITTED, COMMIT_STATUS_UNKNOWN |
| COMMITTED | COMMITTED only, and only carrying the identical committed fact |

Each event carries the complete resulting entry, so a restart reconstructs
byte-for-byte the entry map that was in memory when the last event was
written, and no merge semantics have to be invented.

**Hardening relative to the parent commit.** Before 5K only `prepare()`
guarded COMMITTED; `mark_not_committed()` and `mark_unknown()` could
downgrade a committed entry, and a second `mark_committed()` could overwrite
its result. All three are now refused. Neither downgrade is reachable from
`ExecutionManager` — `mark_unknown` is only called on a path where the commit
did not succeed, and `mark_not_committed` only where the side-effect boundary
was never crossed — and both call sites already tolerate a `False` return, so
this closes a latent hole without changing any reachable behaviour. A repeat
`mark_committed()` with the identical result is answered as the no-op success
it is and writes nothing.

## Crash Matrix

| crash point | durable state | restart behaviour |
| --- | --- | --- |
| before the idempotency append | no terminal record | journal COMMITTED without counterpart → `SOURCE_DISAGREEMENT`, halt (test H) |
| during the append / torn line | log does not end with a newline, or the final line is unparseable | load fails closed, `loaded=False` → `PERSISTED_STATE_CORRUPT`, halt (test D) |
| immediately after the append | complete terminal record | replayed request answered from it (test B) |
| before the journal transition append | previous journal state stands | PREPARED is unresolved → `UNRESOLVED_JOURNAL`, halt (test H) |
| between journal COMMITTED and the idempotency terminal record | COMMITTED entry, no terminal result | `SOURCE_DISAGREEMENT`, halt — never a silent clean start (test H) |
| during Block 5J reconciliation repair | the idempotency file is the only file written, restored byte-for-byte on any failed post-write check | unchanged from 5J |
| during operator migration | v2 log written and verified before the v1 file is renamed; the v1 file is never deleted or truncated | resumes or refuses; never leaves a half-authority (tests K, L, M) |

An old completed request can never execute again on any of these paths: the
only ways its terminal record disappears are a corrupt log (halt) or an
explicit operator `remove` (Block 5J's own narrow tooling).

**Accepted consequence of append-only durability.** A crash part-way through
an append leaves a torn tail, which fails the next load closed; a crash
part-way through the v1 full-file rewrite left the previous file intact via
`os.replace`. The torn record is by definition the one whose write was never
confirmed, so this costs an operator halt rather than a wrong answer, and it
is the same trade the Block 5H/5I append-only archives already accepted. The
compaction paths (`reset`, `remove`, bounded test retention, migration) keep
the atomic temp-file-and-replace behaviour.

## Format Version and Migration

The persistent format changed, so it is versioned explicitly in the log
header (`version: 2`) and the runtime **never** reinterprets v1 state.

`execution_idempotency.json` / `execution_transaction_journal.json` present
while the `.jsonl` log is absent makes the store report
`migration_required`, refuse to load, and the runtime halt with
`SCHEMA_OR_MIGRATION_INVALID` (`data_layer/runtime_safety.py`). Reading a v1
file as an absent v2 authority would treat every completed request as never
executed, which is precisely the duplicate-execution failure this package
must not create. There is no automatic migration and no compatibility loader.

`tools/migrate_execution_authority_logs.py` is the operator path. Per
authority it:

1. reads the v1 file through exactly the v1 loader's normalization, so the
   migrated log holds precisely what the v1 runtime held in memory;
2. refuses an unreadable v1 file, and refuses a journal entry whose state is
   outside the lifecycle rather than normalizing it;
3. refuses a destination that is not this source's deterministic output
   (`DESTINATION_CONFLICT`), leaving the v1 file intact — an *equal*
   destination means an interrupted earlier run and is resumed;
4. writes the v2 log atomically;
5. reloads it through the runtime's own store and requires the reconstructed
   authority to equal the v1 authority exactly — the v1 file is still
   untouched and is still the rollback source;
6. only then retires the v1 file by **rename** to `<name>.migrated`.

Dry run is the default; `--apply` is required to write. This is the same
verify-first, source-retained shape as `tools/migrate_execution_financial_state.py`
after its Block 5I H-1 fix, and tests K/L/M assert each property directly.

`core/application.py`'s `EXECUTION_IDEMPOTENCY_STATE_FILE` and
`EXECUTION_TRANSACTION_JOURNAL_FILE` now name the `.jsonl` logs; every test
that asserts durable path ownership reads those constants rather than
literals, so path ownership is unchanged.

## Reconciliation Compatibility (Block 5J)

`tools/reconcile_execution_authorities.py` still works and its semantics are
unchanged. Its `record(..., save=False)` + one `save()` flow now appends only
the new records, so it adds no write amplification; its byte-for-byte restore
still holds the whole pre-run file. Two changes:

- its default filenames follow the authorities to `.jsonl`;
- it reports `JOURNAL_MIGRATION_REQUIRED` / `IDEMPOTENCY_MIGRATION_REQUIRED`
  (fixed tokens) so an operator with legacy state is sent to the migration
  tool rather than to a corruption investigation.

One existing 5J test moved refusal class: a journal state outside the
lifecycle is now refused by the authority itself at load
(`STATE_INVALID` / `JOURNAL_UNREADABLE`) instead of being classified by the
tool. The refusal got stricter and earlier, it did not disappear, and
`JOURNAL_ENTRY_MALFORMED` retains its own coverage against a COMMITTED entry
whose result is incomplete.

## B5J-1 Closure

`tools/migrate_execution_financial_state.py` no longer embeds
`str(exc)[:200]` in a reason code. The two write-failure paths now report the
fixed tokens `MIGRATION_WRITE_FAILED:SIDECAR_APPEND` and
`MIGRATION_WRITE_FAILED:WORKING_STATE_REWRITE`. The text was not truncated
further — it was removed. Adversarial tests raise an exception whose message
carries `SECRET-EXEC-ID`, `SECRET-REQUEST-ID`, `SECRET-POSITION-ID`, and
`SECRET-ORDER-ID` through both paths and assert none of them, and no
exception prose, reaches the reason code or either rendered output.

## Startup Complexity

Startup remains **O(history)**: both authorities replay their whole log to
rebuild the in-memory index every reader already depends on. No checkpoint or
index cache was built — the implementation did not need one, and adding one
would introduce a second thing that can disagree with the authority.

This is an accepted carry-forward, unchanged from the parent commit. The
package's target was write amplification on the execution hot path, which is
removed.

## Audit Log

Not touched. `AuditEventStore` was already append-only JSON-Lines; its growth
and retention question is unchanged and stays an explicit carry-forward. No
audit redesign was undertaken for convenience.

## Changed Files

| file | change |
| --- | --- |
| `core/durable_append_log.py` | new — shared append-only physical primitive |
| `core/execution_idempotency_store.py` | v2.0 — append-only terminal-record log, single-key rollback, conflict refusal, legacy detection |
| `core/execution_transaction_journal.py` | v2.0 — append-only event log, validated transitions, COMMITTED permanence, legacy detection |
| `core/application.py` | the two durable authority filenames |
| `data_layer/runtime_safety.py` | `migration_required` → `SCHEMA_OR_MIGRATION_INVALID`, and never "clean new store" |
| `tools/reconcile_execution_authorities.py` | `.jsonl` defaults, migration-required reason codes |
| `tools/migrate_execution_financial_state.py` | B5J-1 — fixed reason-code tokens |
| `tools/migrate_execution_authority_logs.py` | new — operator v1 → v2 migration |
| `tests/test_block5k_durable_execution_storage.py` | new — focused package tests |
| `tests/test_block5h0_execution_evidence_authority_alignment.py` | the v1-format test now asserts the fail-closed migration contract; unbounded retention still asserted |
| `tests/test_block5j_execution_authority_recovery.py` | three tests updated to the v2 storage contract |
| `docs/evidence/block5k_durable_execution_storage.md` | this document |

## Validation

| run | command | result |
| --- | --- | --- |
| focused | `pytest tests/test_block5k_durable_execution_storage.py -q` | 39 passed |
| direct regression | `pytest` over the 14 idempotency / journal / runtime-safety / canonical-evidence / replay / 5J / 5I / cutover / output-safety modules | 282 passed |
| full suite | `pytest tests/ -q` | 2356 passed, 0 failed |

**Correction (recorded during Package 5L).** That full-suite line was not a
reliable green and the reasoning below it was wrong. Run directly against
this commit with a clean tree,
`pytest tests/architecture/ tests/test_block4_market_data_architecture.py`
fails four tests: `core/durable_append_log.py` was never added to
`packaging/atlas_architecture_map.json`, so it fell through to the `core/`
catch-all rule and was classified L3 (application orchestration), which made
`core/execution_idempotency_store.py -> core/durable_append_log.py` and
`core/execution_transaction_journal.py -> core/durable_append_log.py`
forbidden `L2 -> L3` edges. The layer topology *did* change: a new module is
a new node. Why the full-suite invocation above reported zero failures is not
explained here, because it has not been established - only the direct,
reproducible result is asserted.

Closed in Package 5L by classifying the module L2 alongside
`core/audit_event_store.py` and the two stores that use it, and regenerating
both inventory artifacts. No permitted exception was added; the classification
was wrong, not the rule. See `docs/evidence/block5_final_closure.md`.

## Carried Forward (explicitly NOT fixed by this package)

Recorded accurately; none is required by 5K correctness.

- startup O(history) for both execution authorities
- audit growth / retention
- no sidecar retention / pruning (Blocks 5H, 5I — deliberate)
- Package 5I LOW findings L-3 and L-4

## PAPER / LIVE

PAPER-only throughout. No live-trading authority is granted, requested, or
implied. The new tool writes no financial state and contacts no venue. Every
test uses an isolated temporary state directory; none constructs a runtime
that could reach the repository's real state files.
