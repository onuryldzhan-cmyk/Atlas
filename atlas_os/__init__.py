"""
============================================================
ATLAS OPERATING SYSTEM — PUBLIC API
============================================================

Canonical public exports for Project Atlas AI infrastructure.

The production lifecycle path is:

    AtlasRuntime -> AtlasOSKernel -> AtlasService implementations

The experimental ``atlas_os.core`` prototype is intentionally not
re-exported here. It remains isolated until its useful parts are reviewed
and merged into the canonical AtlasOS implementation.
============================================================
"""

from atlas_os.contracts import (
    AtlasService,
    HealthReport,
    HealthStatus,
    ServiceIdentity,
    ServiceSnapshot,
    ServiceState,
)
from atlas_os.kernel import (
    AtlasOSKernel,
    KernelHealthReport,
    KernelIdentity,
    KernelLifecycleError,
    KernelSnapshot,
    KernelState,
)
from atlas_os.services import (
    BaseAtlasService,
    CircularDependencyError,
    DependencyDeclaration,
    DependencyManagerError,
    DependencyServiceManager,
    DuplicateServiceError,
    InvalidDependencyError,
    MissingDependencyError,
    OrchestrationAction,
    OrchestrationPlan,
    OrchestrationResult,
    OrchestrationStep,
    RegistryHealthReport,
    RegistrySnapshot,
    ServiceBlockedError,
    ServiceLifecycleError,
    ServiceNotFoundError,
    ServiceOperationResult,
    ServiceRegistry,
    ServiceRegistryError,
    ServiceRemovalError,
)
from atlas_os.configuration import (
    ConfigurationService,
)
from atlas_os.secrets import (
    SecretsManager,
)
from atlas_os.integration import (
    ConfigurationSecretsBridge,
    SecretBindingMode,
)
from atlas_os.events import (
    AtlasEvent,
    EventBusNotRunningError,
    EventBusService,
    EventSeverity,
    SubscriptionNotFoundError,
)
from atlas_os.observability import (
    HealthMonitorService,
    HealthTransitionType,
    InvalidMetricNameError,
    MetricsService,
    MetricTypeConflictError,
)
from atlas_os.audit import (
    AuditLogService,
    AuditQuery,
)
from atlas_os.scheduling import (
    DuplicateTaskError,
    InvalidTaskConfigurationError,
    RetryPolicy,
    ScheduledTaskState,
    SchedulerService,
    TaskExecutionStatus,
    TaskNotFoundError,
    TaskScheduleType,
)
from atlas_os.integrations import (
    AtlasSystemEventType,
    EventAwareAtlasOSKernel,
    EventAwareHealthMonitorService,
)

__version__ = "1.0.0"

__all__ = [
    "AtlasEvent",
    "AtlasOSKernel",
    "AtlasService",
    "AtlasSystemEventType",
    "AuditLogService",
    "AuditQuery",
    "BaseAtlasService",
    "CircularDependencyError",
    "ConfigurationSecretsBridge",
    "ConfigurationService",
    "DependencyDeclaration",
    "DependencyManagerError",
    "DependencyServiceManager",
    "DuplicateServiceError",
    "DuplicateTaskError",
    "EventAwareAtlasOSKernel",
    "EventAwareHealthMonitorService",
    "EventBusNotRunningError",
    "EventBusService",
    "EventSeverity",
    "HealthMonitorService",
    "HealthReport",
    "HealthStatus",
    "HealthTransitionType",
    "InvalidDependencyError",
    "InvalidMetricNameError",
    "InvalidTaskConfigurationError",
    "KernelHealthReport",
    "KernelIdentity",
    "KernelLifecycleError",
    "KernelSnapshot",
    "KernelState",
    "MetricTypeConflictError",
    "MetricsService",
    "MissingDependencyError",
    "OrchestrationAction",
    "OrchestrationPlan",
    "OrchestrationResult",
    "OrchestrationStep",
    "RegistryHealthReport",
    "RegistrySnapshot",
    "RetryPolicy",
    "ScheduledTaskState",
    "SchedulerService",
    "SecretBindingMode",
    "SecretsManager",
    "ServiceBlockedError",
    "ServiceIdentity",
    "ServiceLifecycleError",
    "ServiceNotFoundError",
    "ServiceOperationResult",
    "ServiceRegistry",
    "ServiceRegistryError",
    "ServiceRemovalError",
    "ServiceSnapshot",
    "ServiceState",
    "SubscriptionNotFoundError",
    "TaskExecutionStatus",
    "TaskNotFoundError",
    "TaskScheduleType",
]
