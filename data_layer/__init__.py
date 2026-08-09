"""Backend-independent Atlas relational persistence foundation.

This package is not yet wired into canonical execution. Specialized exchange
journals, idempotency stores, recovery evidence, and audit stores retain their
existing authority.
"""

from .config import StorageConfiguration, load_storage_configuration
from .models import ExecutionRecord, OrderRecord, PositionRecord
from .sqlite import SQLiteStorage

__all__ = [
    "ExecutionRecord",
    "OrderRecord",
    "PositionRecord",
    "SQLiteStorage",
    "StorageConfiguration",
    "load_storage_configuration",
]
