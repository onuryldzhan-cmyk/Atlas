"""
============================================================
ATLAS ENVIRONMENT CHECK v2.0
============================================================

Validates
---------
- Python runtime
- Operating system
- Core dependencies
- Optional dependency groups
- Atlas package imports
- Main application import

This diagnostic tool does not start Atlas or connect to exchanges.
============================================================
"""

from __future__ import annotations

import importlib
import platform
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# ============================================================
# PROJECT ROOT
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# MODELS
# ============================================================

@dataclass(frozen=True)
class Dependency:
    package: str
    import_name: str
    required: bool = False


# ============================================================
# DEPENDENCY GROUPS
# ============================================================

CORE_DEPENDENCIES = (
    Dependency(
        package="requests",
        import_name="requests",
        required=True,
    ),
    Dependency(
        package="python-dotenv",
        import_name="dotenv",
        required=True,
    ),
    Dependency(
        package="binance-connector",
        import_name="binance.spot",
        required=True,
    ),
)

ANALYTICS_DEPENDENCIES = (
    Dependency(
        package="numpy",
        import_name="numpy",
    ),
    Dependency(
        package="pandas",
        import_name="pandas",
    ),
)

WEB_DEPENDENCIES = (
    Dependency(
        package="fastapi",
        import_name="fastapi",
    ),
    Dependency(
        package="uvicorn",
        import_name="uvicorn",
    ),
    Dependency(
        package="jinja2",
        import_name="jinja2",
    ),
    Dependency(
        package="flask",
        import_name="flask",
    ),
)

DEVELOPMENT_DEPENDENCIES = (
    Dependency(
        package="pytest",
        import_name="pytest",
    ),
)


# ============================================================
# HELPERS
# ============================================================

def print_header(title: str) -> None:
    print()
    print(title)


def check_dependency(
    dependency: Dependency,
) -> bool:
    try:
        importlib.import_module(
            dependency.import_name
        )

        print(
            f"[OK]      "
            f"{dependency.package:<20} "
            f"import={dependency.import_name}"
        )

        return True

    except Exception as exc:
        level = (
            "REQUIRED"
            if dependency.required
            else "OPTIONAL"
        )

        print(
            f"[MISSING] "
            f"{dependency.package:<20} "
            f"import={dependency.import_name} "
            f"type={level} "
            f"error={type(exc).__name__}: {exc}"
        )

        return False


def check_group(
    title: str,
    dependencies: Iterable[Dependency],
) -> bool:
    print_header(title)

    group_ready = True

    for dependency in dependencies:
        result = check_dependency(
            dependency
        )

        if dependency.required and not result:
            group_ready = False

    return group_ready


def check_atlas_imports() -> bool:
    print_header(
        "ATLAS IMPORT CHECK"
    )

    checks = (
        (
            "atlas_os",
            "atlas_os",
        ),
        (
            "atlas_runtime",
            "atlas_runtime",
        ),
        (
            "AtlasApplication",
            "core.application",
        ),
    )

    ready = True

    for label, import_name in checks:
        try:
            module = importlib.import_module(
                import_name
            )

            if label == "AtlasApplication":
                getattr(
                    module,
                    "AtlasApplication",
                )

            print(
                f"[OK]      {label}"
            )

        except Exception as exc:
            ready = False

            print(
                f"[FAIL]    "
                f"{label}: "
                f"{type(exc).__name__}: {exc}"
            )

    return ready


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    print(
        "=" * 72
    )
    print(
        "ATLAS ENVIRONMENT CHECK v2.0"
    )
    print(
        "=" * 72
    )

    print(
        f"Project    : {PROJECT_ROOT}"
    )
    print(
        f"Python     : {platform.python_version()}"
    )
    print(
        f"Executable : {sys.executable}"
    )
    print(
        f"Platform   : {platform.platform()}"
    )

    core_ready = check_group(
        "CORE / CURRENT MAIN.PY",
        CORE_DEPENDENCIES,
    )

    check_group(
        "OPTIONAL GROUP: ANALYTICS",
        ANALYTICS_DEPENDENCIES,
    )

    check_group(
        "OPTIONAL GROUP: WEB",
        WEB_DEPENDENCIES,
    )

    check_group(
        "OPTIONAL GROUP: DEVELOPMENT",
        DEVELOPMENT_DEPENDENCIES,
    )

    atlas_ready = check_atlas_imports()

    print()
    print(
        "=" * 72
    )

    if core_ready and atlas_ready:
        print(
            "RESULT: ENVIRONMENT READY"
        )
        print(
            "=" * 72
        )

        return 0

    print(
        "RESULT: ENVIRONMENT NOT READY"
    )
    print(
        "=" * 72
    )

    if not core_ready:
        print()
        print(
            "Install the current runtime dependencies:"
        )
        print(
            "python -m pip install -r requirements.txt"
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )