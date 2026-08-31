"""Block 4 / Package 1: DataProvenance value object.

Covers PROV-1 (canonical provenance has source + schema version), PROV-2
(derived provenance references upstream identity without copying mutable
raw data), DATA-3 (malformed cannot silently become valid data), the M3
record-level vs dataset-level hash naming split, the M4 token normalization
policy, and provenance immutability.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from data_layer.contracts import IntegrityViolation
from data_layer.market_data_models import (
    DataProvenance,
    DataTimestamp,
    TimeSemantic,
    compute_content_digest,
)

INGESTED = DataTimestamp(value=datetime(2026, 8, 14, 12, 0, tzinfo=UTC), semantic=TimeSemantic.INGESTION_TIME)
RECORD_CONTENT_HASH = compute_content_digest({"symbol": "BTCUSDT", "close": "61234.5"})


def provenance(**overrides) -> DataProvenance:
    values = dict(
        source="BINANCE", venue="SPOT", schema_version="1.0",
        ingested_at=INGESTED, record_content_hash=RECORD_CONTENT_HASH,
    )
    values.update(overrides)
    return DataProvenance(**values)


def test_requires_source_and_schema_version():
    with pytest.raises(IntegrityViolation):
        provenance(source="")
    with pytest.raises(IntegrityViolation):
        provenance(schema_version="")


def test_source_and_venue_are_case_folded_but_schema_version_is_not():
    # M4 normalization policy, pinned at the record level so provenance and
    # dataset identity cannot drift apart: source/venue case-fold, opaque
    # version strings keep their case.
    record = provenance(source="BiNaNcE", venue="  Spot ", schema_version="V1.0-Beta")
    assert record.source == "binance"
    assert record.venue == "spot"
    assert record.schema_version == "V1.0-Beta"


def test_ingested_at_must_be_a_data_timestamp():
    with pytest.raises(IntegrityViolation):
        provenance(ingested_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC))


def test_ingested_at_must_use_ingestion_time_semantics():
    wrong_semantic = DataTimestamp(value=datetime(2026, 8, 14, 12, 0, tzinfo=UTC), semantic=TimeSemantic.EVENT_TIME)
    with pytest.raises(IntegrityViolation):
        provenance(ingested_at=wrong_semantic)


def test_record_content_hash_must_be_sha256_hex():
    with pytest.raises(IntegrityViolation):
        provenance(record_content_hash="not-a-hash")
    with pytest.raises(IntegrityViolation):
        provenance(record_content_hash="deadbeef")  # too short


def test_malformed_record_content_hash_is_rejected_not_silently_coerced():
    # A malformed hash must raise, never be zero-padded/truncated into a
    # falsely "valid" 64-char digest.
    with pytest.raises(IntegrityViolation):
        provenance(record_content_hash="0" * 63 + "zz")
    with pytest.raises(IntegrityViolation):
        provenance(record_content_hash=RECORD_CONTENT_HASH + "0")  # too long


def test_record_content_hash_canonicalizes_to_lowercase():
    # Permanent pin of the canonical stored form: an upper-case but
    # otherwise valid digest is accepted and folded to lowercase, so the
    # same digest written either way keys and compares identically.
    # Dropping the .lower() in sha256_hex must fail here.
    record = provenance(record_content_hash=RECORD_CONTENT_HASH.upper())
    assert record.record_content_hash == RECORD_CONTENT_HASH
    assert record.record_content_hash == record.record_content_hash.lower()
    assert provenance().record_content_hash == record.record_content_hash


def test_surrounding_whitespace_in_a_digest_is_stripped_not_rejected():
    assert provenance(record_content_hash=f"  {RECORD_CONTENT_HASH}  ").record_content_hash == RECORD_CONTENT_HASH


def test_record_content_hash_is_record_level_and_names_itself_so():
    # M3: the record-level digest is deliberately not named `content_hash`;
    # that name belongs to the dataset-level digest on DatasetManifest, and
    # the two are different granularities that must never be conflated.
    field_names = {field.name for field in dataclasses.fields(DataProvenance)}
    assert "record_content_hash" in field_names
    assert "content_hash" not in field_names


def test_upstream_identity_digest_is_a_reference_not_a_copy():
    upstream_digest = compute_content_digest({"logical": "identity", "of": "another-dataset"})
    record = provenance(upstream_identity_digest=upstream_digest)
    assert record.upstream_identity_digest == upstream_digest
    assert isinstance(record.upstream_identity_digest, str)


def test_upstream_identity_digest_defaults_to_none():
    assert provenance().upstream_identity_digest is None


def test_upstream_identity_digest_must_also_be_sha256_hex():
    with pytest.raises(IntegrityViolation):
        provenance(upstream_identity_digest="not-a-digest")


def test_provenance_is_immutable():
    record = provenance()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.source = "OTHER"


def test_provenance_excludes_decision_and_execution_fields():
    record = provenance()
    forbidden = {"confidence", "risk", "strategy", "execution_authority", "credentials", "secret"}
    assert forbidden.isdisjoint(dataclasses.asdict(record).keys())
