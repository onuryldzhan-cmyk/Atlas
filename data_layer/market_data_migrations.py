"""Forward-only schema migrations for the market-data bounded context.

This sequence is deliberately separate from data_layer.migrations.MIGRATIONS,
which owns the execution/financial schema. The two are different bounded
contexts and live in different database files, so the market-data sequence
also restarts at migration id 1 and keeps its own ledger rows.

The migration *engine* is reused unmodified: `Migration`, `validate_migrations`,
and `apply_migrations` all come from data_layer.migrations. Only the sequence
is new. Because the market-data database is a separate file, the engine's
`atlas_schema_migrations` ledger table lives in its own namespace and no
collision with the financial sequence is possible. Pointing this sequence at
the financial database by mistake fails closed on migration 1's
identity/checksum mismatch rather than corrupting either schema.

Appending a market-data migration to the financial MIGRATIONS tuple would
instead bump the financial schema version and make every existing financial
database report a migration mismatch for a non-financial reason; that is the
blast radius this separation exists to avoid.

Time columns
------------
Every `*_utc` column stores a Package-1 serialized UTC ISO-8601 instant. Those
strings are serialization only and are never a comparison authority: they are
variable width (fractional seconds are omitted when zero), so lexical ordering
does not match chronological ordering. No CHECK, index, or ORDER BY in this
schema compares or orders a timestamp column. Range and time correctness is
owned by the Package-1 constructors in data_layer.market_data_models.
"""

from __future__ import annotations

from .migrations import Migration

# A canonical stored digest is a 64-character lowercase hex SHA-256. Checking
# length plus lower-case idempotence is cheap and portable; data_layer
# .market_data_models.sha256_hex remains the authority on both write and read.
_DIGEST_SHAPE = "length({column}) = 64 AND {column} = lower({column})"


def _digest_check(column: str) -> str:
    return _DIGEST_SHAPE.format(column=column)


MARKET_DATA_MIGRATIONS = (
    Migration(
        1,
        "market_data_dataset_manifest_foundation",
        (
            f"""
            CREATE TABLE market_data_dataset_identities (
                identity_digest TEXT PRIMARY KEY CHECK ({_digest_check("identity_digest")}),
                source TEXT NOT NULL CHECK (trim(source) <> ''),
                venue TEXT NOT NULL CHECK (trim(venue) <> ''),
                instruments_json TEXT NOT NULL CHECK (json_valid(instruments_json)),
                range_start_utc TEXT NOT NULL CHECK (trim(range_start_utc) <> ''),
                range_end_utc TEXT NOT NULL CHECK (trim(range_end_utc) <> ''),
                timeframe TEXT NOT NULL CHECK (trim(timeframe) <> ''),
                schema_version TEXT NOT NULL CHECK (trim(schema_version) <> ''),
                transform_version TEXT NOT NULL CHECK (trim(transform_version) <> ''),
                UNIQUE (identity_digest, source, venue, schema_version)
            )
            """,
            # The composite UNIQUE above is the parent key of the manifest's
            # composite foreign key. It exists to make DatasetManifest's
            # identity/provenance agreement invariant a storage-level
            # guarantee rather than only a reconstruction-time check: a row
            # whose provenance names a different source/venue/schema_version
            # than its own identity is unrepresentable, not merely detected.
            f"""
            CREATE TABLE market_data_manifests (
                content_hash TEXT PRIMARY KEY CHECK ({_digest_check("content_hash")}),
                identity_digest TEXT NOT NULL CHECK ({_digest_check("identity_digest")}),
                record_count INTEGER NOT NULL CHECK (record_count >= 0),
                generated_at_utc TEXT NOT NULL CHECK (trim(generated_at_utc) <> ''),
                provenance_source TEXT NOT NULL CHECK (trim(provenance_source) <> ''),
                provenance_venue TEXT NOT NULL CHECK (trim(provenance_venue) <> ''),
                provenance_schema_version TEXT NOT NULL CHECK (trim(provenance_schema_version) <> ''),
                provenance_ingested_at_utc TEXT NOT NULL CHECK (trim(provenance_ingested_at_utc) <> ''),
                provenance_record_content_hash TEXT NOT NULL
                    CHECK ({_digest_check("provenance_record_content_hash")}),
                provenance_upstream_identity_digest TEXT
                    CHECK (
                        provenance_upstream_identity_digest IS NULL
                        OR ({_digest_check("provenance_upstream_identity_digest")})
                    ),
                FOREIGN KEY (
                    identity_digest, provenance_source, provenance_venue, provenance_schema_version
                ) REFERENCES market_data_dataset_identities (
                    identity_digest, source, venue, schema_version
                ) ON DELETE RESTRICT
            )
            """,
            # list_for_identity is the only 1:N read path. Ordering is by
            # content_hash, which the primary key already indexes, so no
            # timestamp-ordering index exists or should be added.
            "CREATE INDEX idx_market_data_manifests_identity"
            " ON market_data_manifests(identity_digest)",
        ),
    ),
)

MARKET_DATA_TABLES = (
    "market_data_dataset_identities",
    "market_data_manifests",
)

__all__ = ["MARKET_DATA_MIGRATIONS", "MARKET_DATA_TABLES"]
