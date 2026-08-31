"""Block 4 / Package 1: DatasetIdentity and DatasetManifest.

Covers DATA-5 (duplicate identity is deterministic), REPRO-1 (same
deterministic manifest inputs produce the same logical identity), the M1
dataset range time semantics, the M2 manifest/provenance consistency
invariant, the M3 dataset-level vs record-level hash split, the M4 token
normalization policy, and the counterfactual probes for schema-version
sensitivity, transform-version sensitivity, sorted/duplicate instrument
handling, manifest immutability, and wall-clock ingestion-time independence.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, datetime

import pytest

from data_layer.contracts import IntegrityViolation
from data_layer.market_data_models import (
    DataProvenance,
    DataTimestamp,
    DatasetIdentity,
    DatasetManifest,
    TimeSemantic,
    compute_content_digest,
)

RANGE_START = DataTimestamp(value=datetime(2026, 8, 1, tzinfo=UTC), semantic=TimeSemantic.EVENT_TIME)
RANGE_END = DataTimestamp(value=datetime(2026, 8, 14, tzinfo=UTC), semantic=TimeSemantic.EVENT_TIME)

# Deliberately different values: the manifest digest is dataset-level and the
# provenance digest is record-level. They are never asserted to be equal.
DATASET_CONTENT_HASH = compute_content_digest({"rows": 3})
RECORD_CONTENT_HASH = compute_content_digest({"row": 1, "close": "61234.5"})

INGESTED = DataTimestamp(value=datetime(2026, 8, 14, 1, 0, tzinfo=UTC), semantic=TimeSemantic.INGESTION_TIME)
GENERATED = DataTimestamp(value=datetime(2026, 8, 14, 2, 0, tzinfo=UTC), semantic=TimeSemantic.SNAPSHOT_TIME)

# Frozen golden vector for the canonical fixture below. It pins the whole
# digest recipe at once -- field set, canonical payload shape, key sorting,
# JSON separators, and every normalization rule -- so any silent change to
# how a dataset is identified breaks this test rather than re-identifying
# every already-stored dataset.
GOLDEN_IDENTITY_DIGEST = "1895e277a020ee8233328c1ef95bf3741d9f98f6752b3efc89522b5b307bd778"


def identity(**overrides) -> DatasetIdentity:
    values = dict(
        source="BINANCE", venue="SPOT", instruments=["BTCUSDT", "ETHUSDT"],
        range_start=RANGE_START, range_end=RANGE_END,
        timeframe="1h", schema_version="1.0", transform_version="1.0",
    )
    values.update(overrides)
    return DatasetIdentity(**values)


def provenance(**overrides) -> DataProvenance:
    values = dict(
        source="BINANCE", venue="SPOT", schema_version="1.0",
        ingested_at=INGESTED, record_content_hash=RECORD_CONTENT_HASH,
    )
    values.update(overrides)
    return DataProvenance(**values)


def manifest(dataset_identity: DatasetIdentity | None = None, **overrides) -> DatasetManifest:
    values = dict(
        identity=dataset_identity if dataset_identity is not None else identity(),
        content_hash=DATASET_CONTENT_HASH, record_count=3,
        provenance=provenance(), generated_at=GENERATED,
    )
    values.update(overrides)
    return DatasetManifest(**values)


# -- REPRO-1 / DATA-5: deterministic identity ---------------------------------

def test_same_logical_inputs_produce_the_same_identity_digest():
    assert identity().identity_digest() == identity().identity_digest()


def test_identity_digest_is_sha256_over_key_sorted_canonical_json():
    # Permanent pin of the canonicalization recipe. sort_keys=True is
    # load-bearing: canonical_payload() emits its keys in a domain-readable
    # order that is NOT sorted order, so dropping sort_keys would silently
    # re-identify every existing dataset. Both halves must hold.
    record = identity()
    payload = record.canonical_payload()
    key_sorted = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    dict_literal_order = hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    assert list(payload) != sorted(payload), "fixture assumption: payload order is not already sorted"
    assert key_sorted != dict_literal_order
    assert record.identity_digest() == key_sorted


def test_identity_digest_matches_the_frozen_golden_vector():
    assert identity().identity_digest() == GOLDEN_IDENTITY_DIGEST


def test_instrument_order_does_not_affect_identity_digest():
    forward = identity(instruments=["BTCUSDT", "ETHUSDT"])
    reversed_order = identity(instruments=["ETHUSDT", "BTCUSDT"])
    assert forward.identity_digest() == reversed_order.identity_digest()
    assert forward.instruments == ("BTCUSDT", "ETHUSDT")


def test_duplicate_instruments_in_universe_are_rejected():
    with pytest.raises(IntegrityViolation):
        identity(instruments=["BTCUSDT", "BTCUSDT", "ETHUSDT"])


def test_empty_instrument_universe_is_rejected():
    with pytest.raises(IntegrityViolation):
        identity(instruments=[])


# -- M4: token normalization policy --------------------------------------------

def test_instruments_are_upper_cased_and_case_variants_converge():
    # Permanent pin of normalize_instrument()'s .upper(): without it the
    # lower-case input fails the canonical instrument grammar outright, and
    # the two spellings would stop converging to one logical dataset.
    lower = identity(instruments=["btcusdt", "ethusdt"])
    assert lower.instruments == ("BTCUSDT", "ETHUSDT")
    assert lower.identity_digest() == identity().identity_digest()


def test_duplicate_instruments_are_detected_after_case_normalization():
    with pytest.raises(IntegrityViolation):
        identity(instruments=["BTCUSDT", "btcusdt"])


@pytest.mark.parametrize("source_spelling", ["BINANCE", "binance", "Binance", "  BiNaNcE  "])
def test_source_case_variants_converge_to_one_logical_identity(source_spelling):
    record = identity(source=source_spelling)
    assert record.source == "binance"
    assert record.identity_digest() == identity(source="binance").identity_digest()


@pytest.mark.parametrize("venue_spelling", ["SPOT", "spot", "Spot", "  SpOt  "])
def test_venue_case_variants_converge_to_one_logical_identity(venue_spelling):
    record = identity(venue=venue_spelling)
    assert record.venue == "spot"
    assert record.identity_digest() == identity(venue="spot").identity_digest()


def test_timeframe_case_does_not_silently_converge():
    # Timeframe grammar is domain-specific ("5m" minutes vs "5M" months), so
    # case is preserved and the two remain distinguishable datasets until a
    # domain-specific validator defines their equivalence.
    lower = identity(timeframe="5m")
    upper = identity(timeframe="5M")
    assert lower.timeframe == "5m"
    assert upper.timeframe == "5M"
    assert lower.identity_digest() != upper.identity_digest()


def test_timeframe_is_stripped_but_otherwise_untouched():
    assert identity(timeframe="  1h  ").identity_digest() == identity(timeframe="1h").identity_digest()


def test_schema_and_transform_version_case_is_preserved():
    lower = identity(schema_version="v1.0", transform_version="v1.0")
    upper = identity(schema_version="V1.0", transform_version="V1.0")
    assert lower.schema_version == "v1.0"
    assert upper.schema_version == "V1.0"
    assert lower.identity_digest() != upper.identity_digest()


# -- M1: dataset range time semantics ------------------------------------------

@pytest.mark.parametrize(
    "wrong_semantic",
    [
        TimeSemantic.SOURCE_TIME,
        TimeSemantic.INGESTION_TIME,
        TimeSemantic.PROCESSING_TIME,
        TimeSemantic.RECEIVED_TIME,
        TimeSemantic.SNAPSHOT_TIME,
    ],
)
def test_range_start_must_use_event_time_semantics(wrong_semantic):
    wrong = DataTimestamp(value=datetime(2026, 8, 1, tzinfo=UTC), semantic=wrong_semantic)
    with pytest.raises(IntegrityViolation):
        identity(range_start=wrong)


@pytest.mark.parametrize(
    "wrong_semantic",
    [
        TimeSemantic.SOURCE_TIME,
        TimeSemantic.INGESTION_TIME,
        TimeSemantic.PROCESSING_TIME,
        TimeSemantic.RECEIVED_TIME,
        TimeSemantic.SNAPSHOT_TIME,
    ],
)
def test_range_end_must_use_event_time_semantics(wrong_semantic):
    wrong = DataTimestamp(value=datetime(2026, 8, 14, tzinfo=UTC), semantic=wrong_semantic)
    with pytest.raises(IntegrityViolation):
        identity(range_end=wrong)


def test_range_bounds_must_be_data_timestamps_not_raw_datetimes():
    with pytest.raises(IntegrityViolation):
        identity(range_start=datetime(2026, 8, 1, tzinfo=UTC))
    with pytest.raises(IntegrityViolation):
        identity(range_end=datetime(2026, 8, 14, tzinfo=UTC))


def test_range_start_after_range_end_is_rejected():
    with pytest.raises(IntegrityViolation):
        identity(range_start=RANGE_END, range_end=RANGE_START)


def test_zero_width_range_is_allowed():
    # A point-in-time window is a legitimate request, not a malformed one.
    record = identity(range_start=RANGE_START, range_end=RANGE_START)
    assert record.range_start.value == record.range_end.value
    assert record.identity_digest() == identity(range_start=RANGE_START, range_end=RANGE_START).identity_digest()


def test_range_bounds_are_compared_as_instants_not_wall_clock_text():
    from datetime import timedelta, timezone

    same_instant_other_offset = DataTimestamp(
        value=datetime(2026, 8, 1, 3, 0, tzinfo=timezone(timedelta(hours=3))),
        semantic=TimeSemantic.EVENT_TIME,
    )
    assert identity(range_start=same_instant_other_offset).identity_digest() == identity().identity_digest()


# -- schema/transform version sensitivity -------------------------------------

def test_schema_version_change_changes_identity_digest():
    baseline = identity(schema_version="1.0")
    changed = identity(schema_version="2.0")
    assert baseline.identity_digest() != changed.identity_digest()


def test_transform_version_change_changes_identity_digest():
    baseline = identity(transform_version="1.0")
    changed = identity(transform_version="2.0")
    assert baseline.identity_digest() != changed.identity_digest()


def test_source_or_venue_change_changes_identity_digest():
    baseline = identity()
    assert baseline.identity_digest() != identity(source="COINBASE").identity_digest()
    assert baseline.identity_digest() != identity(venue="FUTURES").identity_digest()


def test_time_range_change_changes_identity_digest():
    baseline = identity()
    later_end = DataTimestamp(value=datetime(2026, 8, 20, tzinfo=UTC), semantic=TimeSemantic.EVENT_TIME)
    assert baseline.identity_digest() != identity(range_end=later_end).identity_digest()


# -- identity/manifest immutability -------------------------------------------

def test_dataset_identity_is_immutable():
    record = identity()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.schema_version = "9.9"


def test_dataset_manifest_is_immutable():
    record = manifest()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.record_count = 999


def test_manifest_generated_at_must_use_snapshot_time_semantics():
    wrong_semantic_generated = DataTimestamp(
        value=datetime(2026, 8, 14, 2, 0, tzinfo=UTC), semantic=TimeSemantic.EVENT_TIME
    )
    with pytest.raises(IntegrityViolation):
        manifest(generated_at=wrong_semantic_generated)


def test_manifest_content_hash_must_be_sha256_hex():
    with pytest.raises(IntegrityViolation):
        manifest(content_hash="not-a-hash")


def test_manifest_negative_record_count_is_rejected():
    with pytest.raises(IntegrityViolation):
        manifest(record_count=-1)


# -- M2: manifest/provenance describe the same dataset -------------------------

def test_manifest_rejects_provenance_source_mismatch():
    with pytest.raises(IntegrityViolation):
        manifest(provenance=provenance(source="COINBASE"))


def test_manifest_rejects_provenance_venue_mismatch():
    with pytest.raises(IntegrityViolation):
        manifest(provenance=provenance(venue="FUTURES"))


def test_manifest_rejects_provenance_schema_version_mismatch():
    with pytest.raises(IntegrityViolation):
        manifest(provenance=provenance(schema_version="2.0"))


def test_manifest_consistency_is_evaluated_after_case_normalization():
    # Equivalent case spellings are the same logical dataset, so they must
    # satisfy the invariant rather than trip it.
    record = manifest(identity(source="BINANCE", venue="SPOT"), provenance=provenance(source="binance", venue="spot"))
    assert record.provenance.source == record.identity.source
    assert record.provenance.venue == record.identity.venue


def test_manifest_schema_version_consistency_is_case_sensitive():
    # schema_version is opaque and case-preserving, so "1.0" and "1.0 " are
    # the same but "V1" and "v1" are not, and the mismatch must be rejected.
    with pytest.raises(IntegrityViolation):
        manifest(identity(schema_version="V1"), provenance=provenance(schema_version="v1"))


def test_derived_dataset_gets_its_own_identity_and_provenance_plus_upstream_reference():
    upstream = identity()
    derived_identity = identity(source="atlas-derived", venue="internal", transform_version="2.0")
    derived_provenance = provenance(
        source="atlas-derived", venue="internal",
        upstream_identity_digest=upstream.identity_digest(),
    )
    record = manifest(derived_identity, provenance=derived_provenance)

    assert record.identity.identity_digest() != upstream.identity_digest()
    assert record.provenance.upstream_identity_digest == upstream.identity_digest()
    assert record.provenance.source == record.identity.source
    assert record.provenance.venue == record.identity.venue


def test_derived_dataset_does_not_get_to_weaken_the_consistency_invariant():
    # Pointing at an upstream dataset is not a licence to disagree with your
    # own identity.
    upstream = identity()
    with pytest.raises(IntegrityViolation):
        manifest(
            identity(source="atlas-derived"),
            provenance=provenance(source="binance", upstream_identity_digest=upstream.identity_digest()),
        )


# -- M3: dataset-level vs record-level hashes ----------------------------------

def test_dataset_content_hash_and_record_content_hash_are_independent():
    # Different granularities: one digests a whole dataset build, the other
    # one record. They are never required to match, and the manifest must
    # accept a perfectly valid pair that differs.
    record = manifest()
    assert record.content_hash == DATASET_CONTENT_HASH
    assert record.provenance.record_content_hash == RECORD_CONTENT_HASH
    assert record.content_hash != record.provenance.record_content_hash


def test_manifest_content_hash_canonicalizes_to_lowercase():
    assert manifest(content_hash=DATASET_CONTENT_HASH.upper()).content_hash == DATASET_CONTENT_HASH


# -- wall-clock independence ---------------------------------------------------

def test_wall_clock_ingestion_time_does_not_affect_logical_dataset_identity():
    shared_identity = identity()
    early_ingest = DataTimestamp(value=datetime(2026, 8, 14, 0, 0, tzinfo=UTC), semantic=TimeSemantic.INGESTION_TIME)
    late_ingest = DataTimestamp(value=datetime(2026, 8, 14, 23, 59, tzinfo=UTC), semantic=TimeSemantic.INGESTION_TIME)
    early_generated = DataTimestamp(value=datetime(2026, 8, 14, 0, 5, tzinfo=UTC), semantic=TimeSemantic.SNAPSHOT_TIME)
    late_generated = DataTimestamp(value=datetime(2026, 12, 25, 23, 59, tzinfo=UTC), semantic=TimeSemantic.SNAPSHOT_TIME)

    manifest_a = manifest(
        shared_identity, generated_at=early_generated, provenance=provenance(ingested_at=early_ingest)
    )
    manifest_b = manifest(
        shared_identity, generated_at=late_generated, provenance=provenance(ingested_at=late_ingest)
    )

    assert manifest_a.logical_identity_digest == manifest_b.logical_identity_digest
    assert manifest_a.identity.canonical_payload() == manifest_b.identity.canonical_payload()


def test_dataset_identity_canonical_payload_never_includes_ingestion_fields():
    payload = identity().canonical_payload()
    for forbidden_key in ("ingested_at", "generated_at", "file_path", "cache_path", "uuid"):
        assert forbidden_key not in payload
