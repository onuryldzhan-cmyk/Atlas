"""Backend-independent Atlas relational persistence foundation.

This package is not yet wired into canonical execution. Specialized exchange
journals, idempotency stores, recovery evidence, and audit stores retain their
existing authority.

Re-exports below are lazy (PEP 562): submodules such as ``data_layer.contracts``
are L1 domain contracts with no I/O, but ``.config``/``.models``/``.sqlite``
pull in the L2 SQLite backend (``sqlite3`` included). Eagerly importing them
here would make every ``from data_layer.<anything> import ...`` execute this
package's ``__init__.py`` first and, as a side effect, load L2 infrastructure
regardless of which submodule was actually requested -- including from L4
research/intelligence code that is only entitled to L1 contracts.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "ExecutionRecord",
    "OrderRecord",
    "PositionRecord",
    "SQLiteStorage",
    "StorageConfiguration",
    "load_storage_configuration",
]

_LAZY_ATTRIBUTES = {
    "StorageConfiguration": ("data_layer.config", "StorageConfiguration"),
    "load_storage_configuration": ("data_layer.config", "load_storage_configuration"),
    "ExecutionRecord": ("data_layer.models", "ExecutionRecord"),
    "OrderRecord": ("data_layer.models", "OrderRecord"),
    "PositionRecord": ("data_layer.models", "PositionRecord"),
    "SQLiteStorage": ("data_layer.sqlite", "SQLiteStorage"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRIBUTES.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(importlib.import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
