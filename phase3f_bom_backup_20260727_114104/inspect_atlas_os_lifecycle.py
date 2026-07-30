from __future__ import annotations

import inspect

from atlas_os import (
    AtlasOSKernel,
    ConfigurationSecretsBridge,
    ConfigurationService,
    SecretsManager,
    ServiceRegistry,
)
from atlas_os.services import BaseAtlasService


TARGET_CLASSES = (
    BaseAtlasService,
    ConfigurationService,
    SecretsManager,
    ConfigurationSecretsBridge,
    ServiceRegistry,
    AtlasOSKernel,
)


def inspect_class(cls: type) -> None:
    print()
    print("=" * 90)
    print(f"{cls.__module__}.{cls.__qualname__}")
    print("=" * 90)

    try:
        print("CLASS SIGNATURE:", inspect.signature(cls))
    except (TypeError, ValueError) as error:
        print("CLASS SIGNATURE: unavailable:", error)

    print("\nMETHODS")

    for name, member in inspect.getmembers(cls):
        if name.startswith("__"):
            continue

        if not (
            inspect.isfunction(member)
            or inspect.ismethod(member)
            or inspect.ismethoddescriptor(member)
        ):
            continue

        try:
            signature = inspect.signature(member)
        except (TypeError, ValueError):
            signature = "<signature unavailable>"

        print(f"- {name}{signature}")

    print("\nPROPERTIES")

    for name, member in inspect.getmembers(cls):
        if name.startswith("__"):
            continue

        if isinstance(member, property):
            print(f"- {name}")


def main() -> None:
    print("=" * 90)
    print("ATLAS OS LIFECYCLE CONTRACT INSPECTION")
    print("=" * 90)

    for target_class in TARGET_CLASSES:
        inspect_class(target_class)


if __name__ == "__main__":
    main()
