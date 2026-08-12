"""
============================================================
ATLAS RUNTIME PACKAGE
============================================================

Production process lifecycle and AtlasOS assembly layer for
Project Atlas AI.
============================================================
"""

from __future__ import annotations

from atlas_runtime.bootstrap import (
    AtlasBootstrapConfigurationError,
    AtlasBootstrapError,
    AtlasInfrastructure,
    AtlasSecureCore,
    build_infrastructure,
    build_secure_core,
)

from atlas_runtime.runtime import (
    AtlasRuntime,
    AtlasRuntimeConfigurationError,
    AtlasRuntimeError,
    AtlasRuntimeShutdownError,
    AtlasRuntimeSnapshot,
    AtlasRuntimeStartupError,
    AtlasRuntimeState,
    AtlasRuntimeStateError,
    RuntimeServiceRegistration,
)


__title__ = "Atlas Runtime"

__package_name__ = "atlas_runtime"

__project__ = "Project Atlas AI"

__version__ = "2.0.0"

__author__ = "Project Atlas AI"

__description__ = (
    "Production process lifecycle and AtlasOS infrastructure "
    "assembly layer for Project Atlas AI."
)


__all__ = [
    "__title__",
    "__package_name__",
    "__project__",
    "__version__",
    "__author__",
    "__description__",
    "AtlasRuntime",
    "AtlasRuntimeState",
    "AtlasRuntimeSnapshot",
    "RuntimeServiceRegistration",
    "AtlasRuntimeError",
    "AtlasRuntimeStateError",
    "AtlasRuntimeConfigurationError",
    "AtlasRuntimeStartupError",
    "AtlasRuntimeShutdownError",
    "AtlasSecureCore",
    "AtlasInfrastructure",
    "AtlasBootstrapError",
    "AtlasBootstrapConfigurationError",
    "build_secure_core",
    "build_infrastructure",
]