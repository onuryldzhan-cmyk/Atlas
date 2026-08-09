# Phase 2 Data Layer and Data Correctness Foundation

## Boundary

Atlas domain callers target explicit order, execution, and position repository
contracts through a Unit of Work. The Unit of Work owns one backend transaction
and exposes all participating repositories, preventing partial multi-repository
commits. Core callers must not import `sqlite3` or a future PostgreSQL driver.

The controlled runtime caller review did not identify a cutover that can be
made without losing domain semantics or introducing a second persistence
authority. Runtime integration remains `PENDING_CONTROLLED_MIGRATION`; this is
a fail-closed deferral, not an implicit in-memory or SQLite fallback. The
machine-readable decision record is
`data_layer/runtime_integration_inventory.json`.

## Controlled runtime integration decision

No caller is classified `MIGRATE_NOW` in this batch. The canonical execution
manager has stable request and execution identities, but the repository
contract cannot update an order through its lifecycle. Its completion boundary
also spans external side effects, the durable transaction journal, and the
persistent idempotency store; committing a relational projection does not make
those authorities atomic.

The position controller remains the canonical in-memory lifecycle owner, but
its `amount` is quote exposure while relational `quantity` has no approved
base/quote definition. The relational position record also lacks the runtime
side. Mapping either value into metadata would weaken queryable integrity and
restart validation, so position cutover is deferred. Portfolio, capital, risk,
paper trading, trade memory, market data, learning/model state, and strategy
state remain deferred until their ownership and compatibility contracts are
explicit.

Before an order/execution/position cutover, Atlas must define order transitions,
base quantity versus quote exposure, position side, restart hydration and
reconciliation, and ordering/recovery across relational commit, idempotency,
journal persistence, and external side effects. Existing JSON/file data must be
handled only by an explicit validated dry-run migration path.

## Specialized persistence retained

The exchange transaction journal, execution idempotency store, recovery
evidence, and append-only audit/security evidence are distinct safety
mechanisms. A database transaction is not an exchange transaction. These stores
remain authoritative and unchanged until separate caller, failure, and recovery
contracts justify migration.

No dual write is enabled. Unmigrated callers remain operational and do not
receive a SQLite implementation. PostgreSQL selection remains fail closed as
`NOT_CONFIGURED`, with no SQLite fallback.

## Unit of Work

Each Unit of Work owns one connection and one transaction. Normal context exit
commits; exceptional exit rolls back and propagates the exception. A Unit of
Work instance cannot be nested or reused. Separate concurrent units are
independent and subject to backend locking/serialization.

## SQLite role

SQLite is for development, tests, and local validation. The backend enables
foreign keys, WAL, and a bounded busy timeout. Schema initialization is
idempotent. Financial writes use parameterized SQL. Monetary and quantity
values are validated finite `Decimal` values and stored as canonical decimal
text, never binary float. UTC timestamps are timezone-aware ISO-8601 values
normalized to `Z`.

The default database lives below `runtime_data`, which is excluded from the
canonical runtime source distribution. Operators may set an explicit path.

## PostgreSQL target

PostgreSQL is the intended production relational backend, but its adapter is
`NOT_CONFIGURED` and was not dynamically validated. Configuration accepts a
DSN only through `ATLAS_POSTGRESQL_DSN`; diagnostics redact credentials. An
explicit PostgreSQL selection fails closed and never falls back to SQLite.

Future adapter work must preserve repository/UoW behavior while addressing
placeholder syntax, partial indexes, JSON validation/type choice, isolation
level, serialization retry policy, UTC handling, decimal precision, and
transactional DDL.

## Schema and migrations

Migrations are ordered, contiguous, forward-only, and checksummed. The schema
table records migration ID, identity, checksum, and UTC application time.
Duplicate IDs, gaps, checksum changes, and future schema versions fail closed.
Each SQLite migration run is transaction-wrapped; destructive automatic
migrations are prohibited.

## Integrity and recovery

Stable IDs, idempotency keys, foreign keys, side/status sets, a single open
position per symbol, finite decimals, positive financial quantities/prices,
aware UTC timestamps, and valid JSON metadata are enforced by models and schema
constraints. Corrupt metadata and schema mismatches raise errors rather than
producing empty state. SQLite integrity is checked at open.

## Legacy migration policy

No runtime JSON, pickle, CSV, journal, or database artifact is automatically
migrated or deleted. The readiness scanner is deterministic and read-only:
it reports hashes, validity, duplicates, and record counts. Any future write
migration requires explicit operator action, source backup and checksum
verification, domain-specific mapping, idempotency, and independent validation.

## Authority

This foundation grants no deployment, Production, LIVE, autonomous deployment,
or real-money trading authority. F-006 hosted CI evidence remains open.
## Financial persistence semantic contract

### External side-effect ordering and recovery

The discovered canonical `ExecutionManager.execute` order is: running/recovery gate; request build; audit; atomic idempotency claim; validation; capital/risk/exposure checks; durable `ExecutionTransactionJournal.PREPARED`; PAPER or LIVE execution; terminal idempotency persistence; journal `COMMITTED`; audit/event/result. Paper execution mutates PaperTrader and PositionController inside the execution boundary. LIVE remains denied by default.

`PREPARED` is the authoritative pre-side-effect record. After an attempt, a confirmed result is persisted to the specialized idempotency store before the journal becomes `COMMITTED`. An exception or an unpersistable confirmed result becomes `COMMIT_STATUS_UNKNOWN`; execution admission halts and reconciliation is mandatory. An unknown exchange outcome is never blindly retried. A relational transaction cannot make an exchange call atomic: future order/execution rows are recoverable projections, not execution authority.

Crash rules are fail-closed: before durable prepare there is no permitted side effect; after prepare and before an observed result, reconcile; after confirmed execution but before durable idempotency/journal completion, reconcile using exchange evidence and the journal; after journal commit, rebuild relational projections idempotently. Request identity is immutable and the specialized idempotency key prevents duplicate admission. Disagreement is resolved from exchange reconciliation for external fact, with the journal as local recovery authority; neither a relational row nor empty memory overrides those records.

### Order lifecycle

The persistence lifecycle is limited to states already present in the Phase-2 model: `NEW`, `ACCEPTED`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, and `REJECTED`. Terminal states are FILLED, CANCELLED, and REJECTED. `data_layer.semantic_contracts.validate_order_transition` defines allowed transitions. An identical repeated state is an idempotent duplicate/no-op; all other invalid or terminal mutations fail. IDs, symbol, side, creation time, and idempotency key are immutable. State timestamps must be timezone-aware UTC and nondecreasing. Retry retains identity and may occur only after an evidenced not-submitted/not-committed outcome; indeterminate outcomes reconcile instead.

### Position units and semantics

PositionController is the current in-memory owner and enforces one open position per symbol. Canonical ExecutionManager behavior opens BUY as LONG and SELL fully closes it. Although the controller contains SHORT-compatible branches, no canonical runtime opening path evidences SHORT support, so relational cutover is long-only and SHORT is blocked. Existing `amount` is quote-currency exposure, never base quantity. Base quantity is `quote_exposure / average_entry_price`; prices are quote per base unit; realized and unrealized PnL are quote currency. `PositionPersistenceDTO` records both Decimal units explicitly. OPEN requires positive remaining base quantity/exposure; CLOSED requires both zero. Partial-close projection semantics are defined, but runtime partial close is not implemented and remains a cutover prerequisite.

### Restart, hydration, and authority

Startup must validate the journal (including load failures), validate and restore idempotency, validate relational records without an empty fallback, inspect unresolved journal entries, reconcile indeterminate external outcomes, reconstruct positions from confirmed executions, compare position/portfolio/capital invariants, and enter READY only when sources agree. Corruption fails closed. Unresolved entries or source disagreement enter reconciliation. The machine contract is `startup_recovery_action`.

### Persistence authority matrix

The machine-readable matrix in `data_layer/runtime_integration_inventory.json` covers orders, executions, positions, portfolio, capital, risk, journal, idempotency, audit, paper state, trade memory, strategy state, learning state, and market data. The journal, idempotency, and audit stores remain specialized authorities. Relational storage is a target projection only and does not silently become external execution authority.

### Controlled legacy migration prerequisites

`data_layer.legacy_migration.dry_run_legacy_records` is explicit, domain-selected, read-only, SHA-256 identified, deterministic, validates identifiers/Decimal/timestamps, detects duplicate IDs, reports rejection, writes no database, and is never invoked at startup. Ambiguous shapes return machine-readable `MIGRATION_BLOCKED`; no data is guessed, replaced, deleted, or migrated automatically. Domain mappings still require owner approval before write-mode adapters exist.

### Cutover status

No relational runtime caller is cut over. `CanonicalExecutionEvidenceAdapter` now
requires matching COMMITTED journal and persistent-idempotency results, explicit
success, deterministic request/order/execution/position identity, canonical
base quantity, price, fee, timestamp, symbol, and LONG action. It emits only a
whitelisted provenance record and has no exchange dependency. Runtime safety
uses this adapter automatically when relational storage is configured, replays
missing projections idempotently, verifies them with a second pass, and remains
not ready on incomplete, conflicting, indeterminate, corrupt, or unpersistable
state.

The order/execution/position caller cutover remains blocked: the current
canonical `ExecutionResult` does not guarantee `order_id`, `position_id`, or an
explicit `base_quantity` on every successful path, while `filled_amount` in the
paper path is quote-currency allocation and cannot safely be relabeled as base
quantity. Forcing projection would invent identity or units. Specialized
journal/idempotency authorities remain unchanged; SHORT, partial close,
PostgreSQL, and other domains remain deferred. The decision is
`PHASE2_CUTOVER_STILL_BLOCKED`.
