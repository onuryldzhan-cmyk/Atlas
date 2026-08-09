"""Repository and transaction contracts for financially meaningful records."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .models import ExecutionRecord, OrderRecord, PositionRecord


class StorageError(RuntimeError):
    """Base storage failure; callers must not silently continue."""


class StorageConfigurationError(StorageError):
    """Storage selection is invalid or unavailable."""


class IntegrityViolation(StorageError):
    """Financial data violates a persistence invariant."""


class MigrationError(StorageError):
    """Schema migration validation or application failed."""


class TransactionStateError(StorageError):
    """Unit-of-work lifecycle was used incorrectly."""


class OrderRepository(Protocol):
    def add(self, record: OrderRecord) -> None: ...
    def get(self, order_id: str) -> OrderRecord | None: ...
    def exists(self, order_id: str) -> bool: ...


class ExecutionRepository(Protocol):
    def add(self, record: ExecutionRecord) -> None: ...
    def get(self, execution_id: str) -> ExecutionRecord | None: ...
    def list_for_order(self, order_id: str) -> list[ExecutionRecord]: ...


class PositionRepository(Protocol):
    def put(self, record: PositionRecord) -> None: ...
    def get(self, position_id: str) -> PositionRecord | None: ...
    def get_open_for_symbol(self, symbol: str) -> PositionRecord | None: ...


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
