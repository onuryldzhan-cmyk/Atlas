"""Repository and transaction contracts for financially meaningful records.

Also holds persistence value types that are shared across layers. A value
type defined beside a concrete store inherits that store's layer, which
would force any producer of the type to depend on infrastructure; defining
it here keeps the type importable without that dependency.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .models import ExecutionRecord, OrderRecord, PositionRecord


class StorageError(RuntimeError):
    """Base storage failure; callers must not silently continue."""


class StorageConfigurationError(StorageError):
    """Storage selection is invalid or unavailable."""


class IntegrityViolation(StorageError):
    """Financial data violates a persistence invariant."""


class ConcurrencyConflict(IntegrityViolation):
    """A stale optimistic writer attempted to mutate financial state."""


class RecordConflict(IntegrityViolation):
    """A record already exists under this exact key with a different payload.

    Distinct from ConcurrencyConflict, which reports a stale optimistic
    version of a record the writer intended to mutate. This instead reports
    an immutable, content-addressed record whose stored payload disagrees
    with the one being written: the write is refused rather than applied,
    because the two payloads cannot both be what that key identifies.

    Backend-neutral: it names a storage invariant, not a SQLite behavior, so
    a future PostgreSQL adapter raises the same class. No existing execution
    storage path raises it.
    """


class MigrationError(StorageError):
    """Schema migration validation or application failed."""


class TransactionStateError(StorageError):
    """Unit-of-work lifecycle was used incorrectly."""


class OrderRepository(Protocol):
    def add(self, record: OrderRecord) -> None: ...
    def get(self, order_id: str) -> OrderRecord | None: ...
    def exists(self, order_id: str) -> bool: ...
    def transition(self, order_id: str, target_status: str, *, expected_version: int) -> int: ...


class ExecutionRepository(Protocol):
    def add(self, record: ExecutionRecord) -> None: ...
    def get(self, execution_id: str) -> ExecutionRecord | None: ...
    def list_for_order(self, order_id: str) -> list[ExecutionRecord]: ...


class PositionRepository(Protocol):
    def put(self, record: PositionRecord) -> None: ...
    def get(self, position_id: str) -> PositionRecord | None: ...
    def get_open_for_symbol(self, symbol: str) -> PositionRecord | None: ...
    def put_cas(self, record: PositionRecord, *, expected_version: int) -> int: ...


class UnitOfWork(AbstractContextManager["UnitOfWork"], ABC):
    orders: OrderRepository
    executions: ExecutionRepository
    positions: PositionRepository

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...


class StorageBackend(Protocol):
    @property
    def backend_identity(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    def open(self) -> None: ...
    def close(self) -> None: ...
    def health(self) -> dict[str, Any]: ...
    def unit_of_work(self) -> UnitOfWork: ...


@dataclass(frozen=True)
class ClaimSource:
    """One examined source behind a claim.

    Written by the Evidence Store (ADR-0008) and constructed by the claim
    producers on the intelligence side, which must not import the store
    itself. Validation stays in the store: this carries values only.
    """

    source_kind: str
    source_uri: str
    source_version: str
    retrieved_at: datetime
    source_digest: str | None = None
