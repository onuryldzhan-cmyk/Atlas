# Atlas Block 4 Freeze Evidence

## Status

CLOSED / FROZEN

## Objective

Data Layer & Data Correctness / Storage Foundation.

Block 4 establishes explicit market-data contracts, a reference storage
backend for those contracts, and a deterministic, fail-closed live
market-data processing path.

## Source Revision

Branch:
feat/block3-execution-safety

Source HEAD:
a1bd58de6de317385720bc752a363fb5cab970b0

Worktree at verification time: clean, nothing staged.

This document anchors the SOURCE HEAD above. The commit that introduces this
file is a separate evidence commit and is deliberately not recorded here; the
annotated `block4-frozen` tag anchors that commit instead.

## Scope

Block 4 spans the commits after the Block-3 freeze record (`f261a56`) through
the source HEAD. `f3a18a6` in that range is a Block-3 follow-up fix
(`ToolInvocationResult` machine `output_digest` split from the descriptive
`output_reference`) and is not attributed to a Block-4 package.

**Package 1 — market-data contract foundation.**
`431da9bf27dc334cd90f6f18be6238827578194b`

Definitions only; no runtime path was altered. Introduced explicit
`TimeSemantic` / `DataTimestamp` contracts so every market-data timestamp
declares whether it is event, ingestion, or snapshot time; pinned the
inclusive candle-close boundary so a bar's closing instant belongs to that
bar; added record-level provenance (source, venue, schema version, ingestion
time, record content digest); gave quality status a closed vocabulary rather
than free-form strings; added deterministic `DatasetIdentity` /
`DatasetManifest` in which the logical identity digest and the content hash
are distinct key spaces and one identity may own many content revisions; and
added structural, adapter-free repository Protocol seams kept out of the
execution UnitOfWork bounded context. L1 architecture rules were recorded in
the architecture map.

Deliberately excluded: no runtime wiring, no SQLite adapter, no PostgreSQL
adapter, no live market-data path modification.

**Package 2 — market-data SQLite reference backend.**
`a7b95c8a00e76b52bb065ab41d3f781c765e6595`

A reference dev/test backend implementing the Package-1 repository Protocols
over a separate SQLite database with its own forward-only migration sequence.
Manifest and identity metadata only; no OHLCV, tick, or order-book
persistence. One repository call is one `BEGIN IMMEDIATE` transaction, so
`put_manifest` cannot leave an identity-only residue. Duplicates are resolved
by comparing the complete reconstructed Package-1 object: equal is an
idempotent no-op, different is refused as `RecordConflict`, and nothing is
ever overwritten. Stored timestamps are serialization only — no CHECK, index,
or ORDER BY compares them, and `list_for_identity` orders by `content_hash`,
so no implicit latest revision is introduced. Driver failures are translated
at both the statement and row-retrieval boundary. `RecordConflict` was added
to the storage taxonomy and L2 layer rules recorded for both new modules. The
Package-1 contracts and the financial migration sequence are unchanged.

**Package 3 — deterministic, fail-closed live market-data path.**
`a1bd58de6de317385720bc752a363fb5cab970b0`

Established a single explicit processing-cutoff authority for live market
candles and removed hidden wall-clock closure decisions from the runtime
processing path. Naive timestamps, future-open candles, invalid temporal
ranges, out-of-order sequences, and same-identity conflicting payloads are
rejected deterministically. Exact duplicates remain idempotent; conflicts fail
closed independent of arrival order. Binance metadata semantics are aligned
end-to-end: quote volume, trade count, and taker-buy fields are required at
the Binance provider boundary, preserved without fabricating missing values,
and included in same-identity conflict detection without granting them new
analyzer or strategy authority. Added the pure L1 temporal helper
`atlas_finance/market_data/temporal.py`, which moved the runtime closure from
96 to 97 modules.

Packages 1, 2 and 3 are CLOSED.

**Package 4 — NOT REQUIRED.**
No Package 4 was opened for Block 4. The Block-4 objective is satisfied by
Packages 1 through 3; nothing was deferred into a fourth package.

## KEEP-UNWIRED Decision

The market-data SQLite reference backend (`data_layer/market_data_sqlite.py`
and `data_layer/market_data_migrations.py`) is intentionally UNWIRED and is
deliberately outside the runtime closure.

Nothing in the composed runtime constructs, registers, imports, or migrates
it. It exists as a reference implementation proving the Package-1 repository
Protocols are implementable and as a dev/test backend; it is not the production
storage decision. `packaging/atlas_runtime_closure.json` does not list either
module, so the architecture check would fail if a future change wired it in
without that decision being made explicitly and visibly.

This is a decision, not an oversight: wiring a storage backend into the
runtime is a separate, reviewable change with its own evidence.

## Verification

Focused Block-4 suites:
255 passed

Command:
`python -m pytest tests/test_block4_market_data_architecture.py
tests/test_block4_market_data_dataset_identity.py
tests/test_block4_market_data_live_correctness.py
tests/test_block4_market_data_provenance.py
tests/test_block4_market_data_quality_status.py
tests/test_block4_market_data_repository_protocols.py
tests/test_block4_market_data_sqlite_storage.py
tests/test_block4_market_data_time_semantics.py -q
--basetemp=<session scratch> -p no:cacheprovider`, run against the committed
source HEAD with an isolated basetemp outside the repository. The worktree was
still clean after the run.

Full suite baseline:
1907 passed

That baseline was established at closure of Package 3 against this same source
HEAD. It was not re-run at this freeze: production code and tests are unchanged
by this evidence commit, so the focused suites plus the architecture check are
the relevant validation.

Architecture:
97 modules
97/97 layered
0 forbidden edges

Command:
`python tools/build_architecture_inventory.py check` — runtime closure matches
(97 modules), the architecture map assigns every live module a layer (97
modules), no forbidden dependency edges.

## Deferred Backlog

Recorded, carried forward, and not modified at this freeze. Both are Package-2
LOW findings against the unwired SQLite reference backend.

**LOW-1 — journal-mode capability and readback truthfulness.**
`PRAGMA journal_mode = WAL` is issued as a persistent header setting and its
result is not read back, so the module does not verify that the requested
journal mode was actually adopted. This is performance-only today and no
correctness property in the module depends on it — unlike `PRAGMA
foreign_keys`, which is read back and enforced precisely because constraint
enforcement does depend on it. Must be revisited if any correctness property
is ever made to depend on the journal mode, or before the backend is wired.

**LOW-2 — foreign SQLite ownership marker and adoption.**
The backend carries no ownership marker identifying a database file as its
own, so an existing SQLite file at the configured path can be adopted and
migrated rather than refused as foreign. Bounded today because the backend is
unwired and used only by dev/test callers that supply their own path. Must be
fixed before the backend is wired to any operator-configured path.

Both are deferred deliberately. Neither is reachable from the composed
runtime while the KEEP-UNWIRED decision above holds.

## Future Ownership of Deferred Work

Work identified during Block 4 but out of its scope, with its intended owner:

| Deferred work | Future owner |
| --- | --- |
| Historical ingestion and backtest datasets | Later research / backtest work |
| Evidence and reproducibility persistence | Block 9 |
| Observability surfacing of data-layer state | Block 12 |
| PostgreSQL productionization | Later production storage work |

The Package-1 Protocol seams and the documented PostgreSQL portability seam in
the reference backend's SELECT-before-INSERT path exist so that this later work
does not require reopening the Block-4 contracts. No commitment is made here to
the schedule or design of any of it.

## PAPER / LIVE

Unchanged by this block.

PAPER remains the default and LIVE authority remains denied. Risk, execution,
portfolio, the provider interlock, the PAPER default, and LIVE denial were not
modified by any Block-4 package. Block 4 changed how market data is admitted
and timestamped, not what may be executed.

## Push Status

NOT PUSHED

No push, no merge, no Block-5 branch, no provider-interlock lift, and no
production-code or test change was made by this freeze operation. The only
file introduced by the freeze commit is this evidence record.

## Limits of This Evidence

Block 4 establishes market-data contracts, a reference storage backend, and a
deterministic, fail-closed live market-data path. It does not establish, and
this document does not claim, a production storage decision, a wired
persistence layer, historical dataset coverage, backtest validity, validated
financial edge, LIVE readiness, provider activation, or production exchange
integration.
