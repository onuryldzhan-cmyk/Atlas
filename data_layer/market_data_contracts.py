"""Protocol-only market-data repository seams.

Market-data persistence is a separate bounded context from
data_layer.contracts.UnitOfWork (orders/executions/positions). These
Protocols are additive and intentionally unwired: no backend implements
them yet, and they must never be merged into, inherited by, or registered
on the execution UnitOfWork. No execution-domain model is imported here.

Key semantics
-------------
A logical dataset identity may map to many concrete content revisions: the
same source/venue/instruments/range/timeframe/schema/transform inputs can be
rebuilt after an upstream correction and yield different content. The two
key spaces are therefore kept distinct and neither Protocol defines an
implicit "latest", "newest", "current", or "first" revision -- picking a
revision is the caller's decision, made from the full list.
"""

from __future__ import annotations

from typing import Protocol

from .market_data_models import DatasetIdentity, DatasetManifest


class DatasetRepository(Protocol):
    """Stores logical dataset identities, independent of their content.

    Keyed by DatasetIdentity.identity_digest().
    """

    def register(self, identity: DatasetIdentity) -> None: ...
    def get(self, identity_digest: str) -> DatasetIdentity | None: ...
    def exists(self, identity_digest: str) -> bool: ...


class MarketDataRepository(Protocol):
    """Stores dataset manifests across two distinct key spaces.

    get_manifest is addressed by DatasetManifest.content_hash and returns
    the one concrete content revision bearing that digest, or None.

    list_for_identity is addressed by DatasetIdentity.identity_digest() and
    returns every concrete manifest belonging to that logical identity --
    zero, one, or many. It never collapses that 1:N relation to a single
    implicitly-chosen revision.
    """

    def put_manifest(self, manifest: DatasetManifest) -> None: ...
    def get_manifest(self, content_hash: str) -> DatasetManifest | None: ...
    def list_for_identity(self, identity_digest: str) -> tuple[DatasetManifest, ...]: ...


__all__ = ["DatasetRepository", "MarketDataRepository"]
