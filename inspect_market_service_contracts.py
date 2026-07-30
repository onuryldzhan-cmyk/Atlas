"""
============================================================
ATLAS MARKET SERVICE CONTRACT INSPECTOR v1.0
============================================================

Purpose
-------
Inspect the exact AtlasOS contracts required by the upcoming
MarketFeedService implementation.

Inspected objects
-----------------
- ServiceIdentity
- BaseAtlasService
- EventBusService
- EventSeverity
- MetricsService

Safety
------
- Does not start AtlasOS
- Does not connect to Binance
- Does not publish events
- Does not execute trades

============================================================
"""

from __future__ import annotations

import inspect

from enum import Enum
from typing import Any

from atlas_os import (
    BaseAtlasService,
    EventBusService,
    EventSeverity,
    MetricsService,
    ServiceIdentity,
)


TARGET_CLASSES = (
    ServiceIdentity,
    BaseAtlasService,
    EventBusService,
    MetricsService,
)


def separator(
    title: str,
) -> None:
    print()
    print("=" * 90)
    print(title)
    print("=" * 90)


def safe_signature(
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


def inspect_class(
    class_object: type[Any],
) -> None:
    separator(
        (
            f"{class_object.__module__}."
            f"{class_object.__qualname__}"
        )
    )

    print(
        "CLASS SIGNATURE:",
        safe_signature(
            class_object
        ),
    )

    print()
    print("METHODS")

    method_count = 0

    for method_name, method in inspect.getmembers(
        class_object,
    ):
        if method_name.startswith(
            "__"
        ):
            continue

        if not (
            inspect.isfunction(
                method
            )
            or inspect.ismethod(
                method
            )
            or inspect.ismethoddescriptor(
                method
            )
        ):
            continue

        method_count += 1

        print(
            "-",
            method_name,
            safe_signature(
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

    for attribute_name, attribute in inspect.getmembers(
        class_object,
    ):
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
    print("DATACLASS FIELDS")

    dataclass_fields = getattr(
        class_object,
        "__dataclass_fields__",
        {},
    )

    if dataclass_fields:
        for field_name, field_definition in (
            dataclass_fields.items()
        ):
            print(
                "-",
                field_name,
                "| type:",
                field_definition.type,
                "| default:",
                repr(
                    field_definition.default
                ),
            )
    else:
        print(
            "- <none>"
        )


def inspect_enum(
    enum_class: type[Enum],
) -> None:
    separator(
        (
            f"{enum_class.__module__}."
            f"{enum_class.__qualname__}"
        )
    )

    for member in enum_class:
        print(
            "-",
            member.name,
            "=",
            repr(
                member.value
            ),
        )


def main() -> int:
    separator(
        "ATLAS MARKET SERVICE CONTRACT INSPECTION"
    )

    for class_object in TARGET_CLASSES:
        inspect_class(
            class_object
        )

    inspect_enum(
        EventSeverity
    )

    separator(
        "INSPECTION COMPLETED"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )