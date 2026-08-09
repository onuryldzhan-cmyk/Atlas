# Phase 2 Data Layer and Data Correctness Foundation

## Boundary

Atlas domain callers target explicit order, execution, and position repository
contracts through a Unit of Work. The Unit of Work owns one backend transaction
and exposes all participating repositories, preventing partial multi-repository
commits. Core callers must not import `sqlite3` or a future PostgreSQL driver.

This batch does not cut canonical execution over to the new repositories.
Runtime integration is `PENDING_CONTROLLED_MIGRATION`.

## Specialized persistence retained

The exchange transaction journal, execution idempotency store, recovery
evidence, and append-only audit/security evidence are distinct safety
mechanisms. A database transaction is not an exchange transaction. These stores
remain authoritative and unchanged until separate caller, failure, and recovery
contracts justify migration.

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
