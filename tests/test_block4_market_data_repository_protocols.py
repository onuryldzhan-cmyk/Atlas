"""Block 4 / Package 1: market-data repository Protocol seams.

Confirms the Protocols are structural, adapter-free contracts kept
independent of the execution-domain UnitOfWork (data_layer.contracts), per
the Block-4 Package-1 bounded-context decision, and pins the M7 key
semantics: a manifest is addressed by its content hash, while a logical
identity may own many concrete manifests.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Protocol, get_type_hints, runtime_checkable

from data_layer import contracts as execution_contracts
from data_layer.market_data_contracts import DatasetRepository, MarketDataRepository
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
INGESTED = DataTimestamp(value=datetime(2026, 8, 14, 1, 0, tzinfo=UTC), semantic=TimeSemantic.INGESTION_TIME)
GENERATED = DataTimestamp(value=datetime(2026, 8, 14, 2, 0, tzinfo=UTC), semantic=TimeSemantic.SNAPSHOT_TIME)


def identity() -> DatasetIdentity:
    return DatasetIdentity(
        source="BINANCE", venue="SPOT", instruments=["BTCUSDT"],
        range_start=RANGE_START, range_end=RANGE_END,
        timeframe="1h", schema_version="1.0", transform_version="1.0",
    )


def manifest_with_content(payload: dict) -> DatasetManifest:
    return DatasetManifest(
        identity=identity(),
        content_hash=compute_content_digest(payload),
        record_count=1,
        provenance=DataProvenance(
            source="BINANCE", venue="SPOT", schema_version="1.0",
            ingested_at=INGESTED, record_content_hash=compute_content_digest({"record": payload}),
        ),
        generated_at=GENERATED,
    )


def test_dataset_repository_is_a_protocol_with_no_implementation():
    assert issubclass(DatasetRepository, Protocol)
    for name in ("register", "get", "exists"):
        method = getattr(DatasetRepository, name)
        assert inspect.getsource(method).strip().endswith("...")


def test_market_data_repository_is_a_protocol_with_no_implementation():
    assert issubclass(MarketDataRepository, Protocol)
    for name in ("put_manifest", "get_manifest", "list_for_identity"):
        method = getattr(MarketDataRepository, name)
        assert inspect.getsource(method).strip().endswith("...")


# -- M7: the two key spaces are distinct and named as such ---------------------

def test_manifest_lookup_is_keyed_by_content_hash_not_by_identity():
    # Parameter names are part of a Python call contract (callers may pass
    # them by keyword), so this pins the key space itself, not a comment:
    # reverting get_manifest to an identity key must fail here.
    parameters = list(inspect.signature(MarketDataRepository.get_manifest).parameters)
    assert parameters == ["self", "content_hash"]


def test_identity_lookup_is_keyed_by_identity_digest_and_returns_many():
    parameters = list(inspect.signature(MarketDataRepository.list_for_identity).parameters)
    assert parameters == ["self", "identity_digest"]

    annotation = inspect.signature(MarketDataRepository.list_for_identity).return_annotation
    assert "tuple[DatasetManifest, ...]" in str(annotation)


def test_dataset_repository_is_keyed_by_identity_digest():
    for name in ("get", "exists"):
        parameters = list(inspect.signature(getattr(DatasetRepository, name)).parameters)
        assert parameters == ["self", "identity_digest"]


def test_one_logical_identity_may_own_many_concrete_manifests():
    # Behavioural pin of the 1:N contract with an in-memory backend: the
    # same logical identity is rebuilt twice with different content, both
    # revisions remain individually addressable by content hash, and
    # list_for_identity returns both rather than an implicitly chosen one.
    class InMemoryMarketDataRepository:
        def __init__(self) -> None:
            self._by_content_hash: dict[str, DatasetManifest] = {}

        def put_manifest(self, manifest: DatasetManifest) -> None:
            self._by_content_hash[manifest.content_hash] = manifest

        def get_manifest(self, content_hash: str) -> DatasetManifest | None:
            return self._by_content_hash.get(content_hash)

        def list_for_identity(self, identity_digest: str) -> tuple[DatasetManifest, ...]:
            return tuple(
                manifest for manifest in self._by_content_hash.values()
                if manifest.logical_identity_digest == identity_digest
            )

    repository = InMemoryMarketDataRepository()
    first_revision = manifest_with_content({"rows": 3})
    corrected_revision = manifest_with_content({"rows": 4})
    repository.put_manifest(first_revision)
    repository.put_manifest(corrected_revision)

    shared_identity_digest = identity().identity_digest()
    assert first_revision.logical_identity_digest == shared_identity_digest
    assert corrected_revision.logical_identity_digest == shared_identity_digest
    assert first_revision.content_hash != corrected_revision.content_hash

    assert repository.get_manifest(first_revision.content_hash) is first_revision
    assert repository.get_manifest(corrected_revision.content_hash) is corrected_revision
    assert repository.get_manifest(shared_identity_digest) is None

    listed = repository.list_for_identity(shared_identity_digest)
    assert set(listed) == {first_revision, corrected_revision}
    assert repository.list_for_identity(compute_content_digest({"unknown": True})) == ()


def test_protocols_are_structurally_satisfiable_without_inheritance():
    @runtime_checkable
    class _CheckableDatasetRepository(DatasetRepository, Protocol):
        pass

    class InMemoryDatasetRepository:
        def __init__(self) -> None:
            self._store: dict[str, DatasetIdentity] = {}

        def register(self, identity: DatasetIdentity) -> None:
            self._store[identity.identity_digest()] = identity

        def get(self, identity_digest: str) -> DatasetIdentity | None:
            return self._store.get(identity_digest)

        def exists(self, identity_digest: str) -> bool:
            return identity_digest in self._store

    assert isinstance(InMemoryDatasetRepository(), _CheckableDatasetRepository)


def test_market_data_repositories_are_not_part_of_the_execution_unit_of_work():
    assert not hasattr(execution_contracts.UnitOfWork, "datasets")
    assert not hasattr(execution_contracts.UnitOfWork, "market_data")


def test_execution_unit_of_work_is_untouched_by_market_data_contracts():
    assert DatasetRepository is not execution_contracts.OrderRepository
    assert MarketDataRepository is not execution_contracts.OrderRepository
    # UnitOfWork is a real ABC (not a runtime_checkable Protocol); the
    # correct-direction check is that it never appears as a base of the new
    # market-data Protocols, i.e. neither was folded into the execution UoW.
    assert execution_contracts.UnitOfWork not in DatasetRepository.__mro__
    assert execution_contracts.UnitOfWork not in MarketDataRepository.__mro__


def test_manifest_type_used_by_protocol_is_the_companion_manifest_not_a_duplicate():
    # DatasetManifest must be the single canonical manifest type; the
    # Protocol must reference it rather than declaring a shadow copy.
    # The Protocol module uses postponed annotations, so the raw annotation
    # is only the string "DatasetManifest" -- accepting that string would
    # also accept a same-named duplicate declared in the Protocol module.
    # Resolve the hint through the defining module's own namespace instead
    # and pin the resolved class by identity with the companion model.
    hints = get_type_hints(MarketDataRepository.put_manifest)
    assert hints["manifest"] is DatasetManifest
