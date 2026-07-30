"""
============================================================
ATLAS MARKET DATA CONTRACT INSPECTOR v1.0
============================================================

Purpose
-------
Discover existing market-data classes before AtlasOS service
integration.

Searches
--------
- Market feed classes
- Candle processors
- Exchange clients
- Market-data providers
- Price providers
- Ticker providers
- Data caches

Safety
------
- Does not start Atlas
- Does not connect to an exchange
- Does not execute trades
- Imports modules defensively
- Reports import failures without stopping discovery

============================================================
"""

from __future__ import annotations

import importlib
import inspect
import sys

from pathlib import Path
from types import ModuleType
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent


IGNORED_DIRECTORIES = {
    "__pycache__",
    ".git",
    ".idea",
    ".pytest_cache",
    ".venv",
    "venv",
    "env",
    "archive",
    "archives",
    "runtime_data",
}


IGNORED_PREFIXES = (
    "archive_unused_",
)


TARGET_TERMS = (
    "market",
    "feed",
    "candle",
    "exchange",
    "binance",
    "ticker",
    "price",
    "quote",
    "provider",
    "data_cache",
)


CLASS_TERMS = (
    "market",
    "feed",
    "candle",
    "exchange",
    "binance",
    "ticker",
    "price",
    "quote",
    "provider",
    "cache",
)


def separator(
    title: str | None = None,
) -> None:
    print()
    print("=" * 88)

    if title:
        print(title)

    print("=" * 88)


def is_ignored(
    path: Path,
) -> bool:
    for part in path.parts:
        if part in IGNORED_DIRECTORIES:
            return True

        if any(
            part.startswith(prefix)
            for prefix in IGNORED_PREFIXES
        ):
            return True

    return False


def path_to_module(
    file_path: Path,
) -> str | None:
    try:
        relative = file_path.relative_to(
            PROJECT_ROOT
        )
    except ValueError:
        return None

    if relative.name == "__init__.py":
        parts = relative.parent.parts
    else:
        parts = (
            *relative.parent.parts,
            relative.stem,
        )

    if not parts:
        return None

    if any(
        not part.isidentifier()
        for part in parts
    ):
        return None

    return ".".join(
        parts
    )


def candidate_files() -> list[Path]:
    candidates: list[Path] = []

    for file_path in PROJECT_ROOT.rglob(
        "*.py"
    ):
        if is_ignored(
            file_path
        ):
            continue

        relative_text = str(
            file_path.relative_to(
                PROJECT_ROOT
            )
        ).lower()

        if any(
            term in relative_text
            for term in TARGET_TERMS
        ):
            candidates.append(
                file_path
            )

    return sorted(
        candidates
    )


def import_module_safely(
    module_name: str,
) -> tuple[
    ModuleType | None,
    str | None,
]:
    try:
        module = importlib.import_module(
            module_name
        )

        return module, None

    except BaseException as error:
        return (
            None,
            (
                f"{type(error).__name__}: "
                f"{error}"
            ),
        )


def is_target_class(
    class_name: str,
) -> bool:
    normalized = class_name.lower()

    return any(
        term in normalized
        for term in CLASS_TERMS
    )


def printable_signature(
    value: Any,
) -> str:
    try:
        return str(
            inspect.signature(
                value
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        return "<signature unavailable>"


def print_class_report(
    module_name: str,
    class_object: type[Any],
) -> None:
    separator(
        f"{module_name}.{class_object.__name__}"
    )

    print(
        "MODULE:",
        module_name,
    )

    print(
        "CLASS:",
        class_object.__qualname__,
    )

    print(
        "CONSTRUCTOR:",
        printable_signature(
            class_object
        ),
    )

    print()
    print("BASE CLASSES")

    for base_class in inspect.getmro(
        class_object
    ):
        print(
            "-",
            (
                f"{base_class.__module__}."
                f"{base_class.__qualname__}"
            ),
        )

    print()
    print("METHODS")

    method_count = 0

    for method_name, method in inspect.getmembers(
        class_object,
        predicate=inspect.isfunction,
    ):
        if method_name.startswith(
            "__"
        ):
            continue

        method_count += 1

        print(
            "-",
            method_name,
            printable_signature(
                method
            ),
        )

    if method_count == 0:
        print(
            "- <none>"
        )

    print()
    print("PROPERTIES")

    property_count = 0

    for attribute_name, attribute in vars(
        class_object
    ).items():
        if isinstance(
            attribute,
            property,
        ):
            property_count += 1

            print(
                "-",
                attribute_name,
            )

    if property_count == 0:
        print(
            "- <none>"
        )

    print()
    print("CLASS CONSTANTS")

    constant_count = 0

    for attribute_name, attribute in vars(
        class_object
    ).items():
        if (
            attribute_name.isupper()
            and not callable(
                attribute
            )
        ):
            constant_count += 1

            print(
                "-",
                attribute_name,
                "=",
                repr(
                    attribute
                ),
            )

    if constant_count == 0:
        print(
            "- <none>"
        )


def main() -> int:
    if str(
        PROJECT_ROOT
    ) not in sys.path:
        sys.path.insert(
            0,
            str(
                PROJECT_ROOT
            ),
        )

    separator(
        "ATLAS MARKET DATA CONTRACT INSPECTION"
    )

    files = candidate_files()

    print(
        "PROJECT ROOT:",
        PROJECT_ROOT,
    )

    print(
        "CANDIDATE FILES:",
        len(
            files
        ),
    )

    imported_modules = 0
    failed_modules = 0
    discovered_classes = 0
    discovered_objects: set[
        tuple[str, str]
    ] = set()

    for file_path in files:
        relative_path = file_path.relative_to(
            PROJECT_ROOT
        )

        module_name = path_to_module(
            file_path
        )

        if not module_name:
            print(
                "[SKIPPED]",
                relative_path,
                "| invalid module path",
            )
            continue

        module, error = import_module_safely(
            module_name
        )

        if module is None:
            failed_modules += 1

            print(
                "[IMPORT FAILED]",
                module_name,
                "|",
                error,
            )

            continue

        imported_modules += 1

        classes = []

        for class_name, class_object in inspect.getmembers(
            module,
            predicate=inspect.isclass,
        ):
            if (
                class_object.__module__
                != module.__name__
            ):
                continue

            if not is_target_class(
                class_name
            ):
                continue

            object_key = (
                class_object.__module__,
                class_object.__qualname__,
            )

            if object_key in discovered_objects:
                continue

            discovered_objects.add(
                object_key
            )

            classes.append(
                class_object
            )

        for class_object in classes:
            discovered_classes += 1

            print_class_report(
                module_name,
                class_object,
            )

    separator(
        "DISCOVERY SUMMARY"
    )

    print(
        "CANDIDATE FILES:",
        len(
            files
        ),
    )

    print(
        "IMPORTED MODULES:",
        imported_modules,
    )

    print(
        "FAILED MODULES:",
        failed_modules,
    )

    print(
        "DISCOVERED CLASSES:",
        discovered_classes,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )