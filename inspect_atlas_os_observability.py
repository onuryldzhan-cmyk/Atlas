"""
============================================================
ATLAS OS OBSERVABILITY CONTRACT INSPECTION
============================================================

Inspects the installed AtlasOS observability infrastructure.

Target components
-----------------
- Event Bus
- Metrics
- Audit
- Scheduler
- Health Monitor
============================================================
"""

from __future__ import annotations

import importlib
import inspect

from typing import Any


# =========================================================
# TARGET DEFINITIONS
# =========================================================


TARGET_CANDIDATES: dict[
    str,
    tuple[
        tuple[str, str],
        ...,
    ],
] = {
    "EVENT BUS": (
        (
            "atlas_os",
            "EventBusService",
        ),
        (
            "atlas_os.events",
            "EventBusService",
        ),
        (
            "atlas_os.event_bus",
            "EventBusService",
        ),
        (
            "atlas_os.events.event_bus",
            "EventBusService",
        ),
    ),
    "METRICS": (
        (
            "atlas_os",
            "MetricsService",
        ),
        (
            "atlas_os.metrics",
            "MetricsService",
        ),
        (
            "atlas_os.observability",
            "MetricsService",
        ),
        (
            "atlas_os.observability.metrics",
            "MetricsService",
        ),
    ),
    "AUDIT": (
        (
            "atlas_os",
            "AuditService",
        ),
        (
            "atlas_os",
            "AuditLogService",
        ),
        (
            "atlas_os.audit",
            "AuditService",
        ),
        (
            "atlas_os.audit",
            "AuditLogService",
        ),
        (
            "atlas_os.observability",
            "AuditService",
        ),
        (
            "atlas_os.observability.audit",
            "AuditService",
        ),
    ),
    "SCHEDULER": (
        (
            "atlas_os",
            "SchedulerService",
        ),
        (
            "atlas_os.scheduler",
            "SchedulerService",
        ),
        (
            "atlas_os.scheduling",
            "SchedulerService",
        ),
        (
            "atlas_os.scheduling.scheduler",
            "SchedulerService",
        ),
    ),
    "HEALTH MONITOR": (
        (
            "atlas_os",
            "HealthMonitorService",
        ),
        (
            "atlas_os",
            "HealthService",
        ),
        (
            "atlas_os.health",
            "HealthMonitorService",
        ),
        (
            "atlas_os.health",
            "HealthService",
        ),
        (
            "atlas_os.observability",
            "HealthMonitorService",
        ),
        (
            "atlas_os.observability.health",
            "HealthMonitorService",
        ),
    ),
}


# =========================================================
# DISCOVERY
# =========================================================


def discover_class(
    candidates: tuple[
        tuple[str, str],
        ...,
    ],
) -> tuple[
    type[Any] | None,
    str | None,
]:
    """
    Discover the first importable class.
    """

    attempted: list[str] = []

    for module_name, class_name in candidates:
        target_name = (
            f"{module_name}.{class_name}"
        )

        attempted.append(
            target_name
        )

        try:
            module = importlib.import_module(
                module_name
            )

        except Exception:
            continue

        candidate = getattr(
            module,
            class_name,
            None,
        )

        if inspect.isclass(
            candidate
        ):
            return (
                candidate,
                target_name,
            )

    return (
        None,
        ", ".join(
            attempted
        ),
    )


# =========================================================
# INSPECTION
# =========================================================


def inspect_class(
    title: str,
    target_class: type[Any],
    import_path: str,
) -> None:
    """
    Print class contract details.
    """

    print()
    print("=" * 90)
    print(title)
    print("=" * 90)

    print(
        "IMPORT PATH:",
        import_path,
    )

    print(
        "MODULE:",
        target_class.__module__,
    )

    print(
        "QUALNAME:",
        target_class.__qualname__,
    )

    try:
        print(
            "CLASS SIGNATURE:",
            inspect.signature(
                target_class
            ),
        )

    except (
        TypeError,
        ValueError,
    ) as error:
        print(
            "CLASS SIGNATURE: unavailable:",
            error,
        )

    print()
    print("BASE CLASSES")

    for base_class in target_class.__mro__:
        print(
            "-",
            (
                f"{base_class.__module__}."
                f"{base_class.__qualname__}"
            ),
        )

    print()
    print("METHODS")

    for name, member in inspect.getmembers(
        target_class
    ):
        if name.startswith(
            "__"
        ):
            continue

        if not (
            inspect.isfunction(
                member
            )
            or inspect.ismethod(
                member
            )
            or inspect.ismethoddescriptor(
                member
            )
        ):
            continue

        try:
            signature = inspect.signature(
                member
            )

        except (
            TypeError,
            ValueError,
        ):
            signature = (
                "<signature unavailable>"
            )

        print(
            f"- {name}{signature}"
        )

    print()
    print("PROPERTIES")

    property_found = False

    for name, member in inspect.getmembers(
        target_class
    ):
        if name.startswith(
            "__"
        ):
            continue

        if isinstance(
            member,
            property,
        ):
            property_found = True

            print(
                f"- {name}"
            )

    if not property_found:
        print(
            "- NONE"
        )

    print()
    print("CLASS CONSTANTS")

    constant_found = False

    for name, value in vars(
        target_class
    ).items():
        if name.startswith(
            "_"
        ):
            continue

        if (
            inspect.isfunction(
                value
            )
            or inspect.ismethod(
                value
            )
            or isinstance(
                value,
                property,
            )
        ):
            continue

        if isinstance(
            value,
            (
                str,
                int,
                float,
                bool,
                tuple,
                frozenset,
                type(None),
            ),
        ):
            constant_found = True

            print(
                f"- {name} = {value!r}"
            )

    if not constant_found:
        print(
            "- NONE"
        )


# =========================================================
# MAIN
# =========================================================


def main() -> None:
    """
    Discover and inspect AtlasOS observability classes.
    """

    print("=" * 90)
    print(
        "ATLAS OS OBSERVABILITY CONTRACT INSPECTION"
    )
    print("=" * 90)

    discovered_count = 0

    for title, candidates in (
        TARGET_CANDIDATES.items()
    ):
        (
            target_class,
            discovery_information,
        ) = discover_class(
            candidates
        )

        if target_class is None:
            print()
            print("=" * 90)
            print(title)
            print("=" * 90)
            print(
                "STATUS: NOT FOUND"
            )
            print(
                "ATTEMPTED:",
                discovery_information,
            )

            continue

        discovered_count += 1

        inspect_class(
            title,
            target_class,
            discovery_information or "",
        )

    print()
    print("=" * 90)
    print("DISCOVERY SUMMARY")
    print("=" * 90)
    print(
        "DISCOVERED:",
        discovered_count,
    )
    print(
        "EXPECTED:",
        len(
            TARGET_CANDIDATES
        ),
    )


if __name__ == "__main__":
    main()