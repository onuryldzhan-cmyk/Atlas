"""
AtlasOS Core Package.
"""

from atlas_os.core.contracts import (
    AtlasService,
    HealthReport,
    HealthState,
    ServiceMetadata,
    ServiceSnapshot,
    ServiceState,
)
from atlas_os.core.kernel import (
    AtlasKernel,
    InvalidKernelStateError,
    KernelError,
    KernelSnapshot,
    KernelStartupError,
    KernelState,
)
from atlas_os.core.service_registry import (
    CircularDependencyError,
    DuplicateServiceError,
    MissingDependencyError,
    ServiceNotFoundError,
    ServiceRegistry,
    ServiceRegistryError,
)

__all__ = [
    "AtlasKernel",
    "AtlasService",
    "CircularDependencyError",
    "DuplicateServiceError",
    "HealthReport",
    "HealthState",
    "InvalidKernelStateError",
    "KernelError",
    "KernelSnapshot",
    "KernelStartupError",
    "KernelState",
    "MissingDependencyError",
    "ServiceMetadata",
    "ServiceNotFoundError",
    "ServiceRegistry",
    "ServiceRegistryError",
    "ServiceSnapshot",
    "ServiceState",
]