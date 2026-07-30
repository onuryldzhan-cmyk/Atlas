"""
============================================================
ATLAS OPERATING SYSTEM
============================================================

Core platform for Project Atlas AI.

AtlasOS manages service lifecycle, configuration, events,
dependencies, scheduling, observability, permissions and plugins.

============================================================
"""

from atlas_os.core import (
    AtlasKernel,
    AtlasService,
    HealthReport,
    HealthState,
    KernelSnapshot,
    KernelState,
    ServiceMetadata,
    ServiceRegistry,
    ServiceSnapshot,
    ServiceState,
)

__version__ = "1.0.0"

__all__ = [
    "AtlasKernel",
    "AtlasService",
    "HealthReport",
    "HealthState",
    "KernelSnapshot",
    "KernelState",
    "ServiceMetadata",
    "ServiceRegistry",
    "ServiceSnapshot",
    "ServiceState",
]