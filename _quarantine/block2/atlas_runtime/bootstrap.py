"""
============================================================
ATLAS RUNTIME INFRASTRUCTURE BOOTSTRAP v2.0.0
============================================================

Project
-------
Project Atlas AI

Package
-------
atlas_runtime

Purpose
-------
Build the production AtlasOS infrastructure graph used by
Atlas Runtime.

Infrastructure
--------------
- ConfigurationService
- SecretsManager
- ConfigurationSecretsBridge
- ConfigurationSecretsService
- EventBusService
- MetricsService
- AuditLogService
- SchedulerService
- HealthMonitorService

Responsibilities
----------------
- Construct AtlasOS infrastructure services
- Preserve dependency injection
- Validate injected component consistency
- Register services with Atlas Runtime
- Declare explicit lifecycle dependencies
- Ensure HealthMonitor starts last
- Ensure shutdown occurs in reverse dependency order
- Prevent plaintext secret exposure
- Provide immutable infrastructure containers

Startup order
-------------
1. ConfigurationService
2. SecretsManager
3. ConfigurationSecretsService
4. EventBusService
5. MetricsService
6. AuditLogService
7. SchedulerService
8. HealthMonitorService

Shutdown order
--------------
1. HealthMonitorService
2. SchedulerService
3. AuditLogService
4. MetricsService
5. EventBusService
6. ConfigurationSecretsService
7. SecretsManager
8. ConfigurationService

============================================================
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Mapping

from atlas_os import (
    AuditLogService,
    ConfigurationSecretsBridge,
    ConfigurationService,
    EventBusService,
    HealthMonitorService,
    MetricsService,
    SchedulerService,
    SecretsManager,
)

from atlas_os.integration.configuration_secrets_service import (
    ConfigurationSecretsService,
)

from atlas_runtime.runtime import (
    AtlasRuntime,
)


logger = logging.getLogger(
    "AtlasRuntime.Bootstrap"
)


# =========================================================
# EXCEPTIONS
# =========================================================


class AtlasBootstrapError(
    RuntimeError
):
    """
    Base exception for Atlas Runtime bootstrap failures.
    """


class AtlasBootstrapConfigurationError(
    AtlasBootstrapError
):
    """
    Raised when bootstrap component configuration is invalid.
    """


# =========================================================
# DATA MODELS
# =========================================================


@dataclass(
    frozen=True,
    slots=True,
)
class AtlasSecureCore:
    """
    Atlas secure-core component container.
    """

    runtime: AtlasRuntime

    configuration_service: ConfigurationService

    secrets_manager: SecretsManager

    configuration_secrets_bridge: (
        ConfigurationSecretsBridge
    )

    configuration_secrets_service: (
        ConfigurationSecretsService
    )

    plaintext_values_exposed: bool = False


@dataclass(
    frozen=True,
    slots=True,
)
class AtlasInfrastructure:
    """
    Complete AtlasOS infrastructure container.

    This object contains service references only. It never stores
    plaintext secret values.
    """

    runtime: AtlasRuntime

    configuration_service: ConfigurationService

    secrets_manager: SecretsManager

    configuration_secrets_bridge: (
        ConfigurationSecretsBridge
    )

    configuration_secrets_service: (
        ConfigurationSecretsService
    )

    event_bus: EventBusService

    metrics_service: MetricsService

    audit_service: AuditLogService

    scheduler_service: SchedulerService

    health_monitor_service: (
        HealthMonitorService
    )

    plaintext_values_exposed: bool = False

    @property
    def secure_core(
        self,
    ) -> AtlasSecureCore:
        """
        Return the secure-core view of this infrastructure.
        """

        return AtlasSecureCore(
            runtime=self.runtime,
            configuration_service=(
                self.configuration_service
            ),
            secrets_manager=(
                self.secrets_manager
            ),
            configuration_secrets_bridge=(
                self.configuration_secrets_bridge
            ),
            configuration_secrets_service=(
                self.configuration_secrets_service
            ),
            plaintext_values_exposed=False,
        )


# =========================================================
# HELPERS
# =========================================================


def _service_name(
    service: Any,
) -> str:
    """
    Resolve the canonical AtlasOS service name.
    """

    identity = getattr(
        service,
        "identity",
        None,
    )

    if identity is None:
        raise AtlasBootstrapConfigurationError(
            "AtlasOS service has no identity."
        )

    for attribute_name in (
        "name",
        "service_name",
    ):
        value = getattr(
            identity,
            attribute_name,
            None,
        )

        if value is None:
            continue

        normalized = str(
            value
        ).strip()

        if normalized:
            return normalized

    raise AtlasBootstrapConfigurationError(
        "AtlasOS service identity has no usable name."
    )


def _validate_runtime(
    runtime: AtlasRuntime,
) -> AtlasRuntime:
    """
    Validate an injected Runtime.
    """

    if not isinstance(
        runtime,
        AtlasRuntime,
    ):
        raise TypeError(
            "runtime must be an AtlasRuntime instance."
        )

    if runtime.service_count != 0:
        raise AtlasBootstrapConfigurationError(
            "Bootstrap requires an empty AtlasRuntime. "
            "Register custom application services after "
            "building the infrastructure."
        )

    return runtime


def _assert_instance(
    value: Any,
    expected_type: type[Any],
    parameter_name: str,
) -> None:
    """
    Validate an injected component type.
    """

    if not isinstance(
        value,
        expected_type,
    ):
        raise TypeError(
            f"{parameter_name} must be an instance of "
            f"{expected_type.__name__}."
        )


# =========================================================
# SECURE CORE BUILDER
# =========================================================


def build_secure_core(
    *,
    runtime: AtlasRuntime | None = None,
    runtime_metadata: Mapping[
        str,
        Any,
    ] | None = None,
    configuration_service: (
        ConfigurationService | None
    ) = None,
    secrets_manager: SecretsManager | None = None,
    configuration_secrets_bridge: (
        ConfigurationSecretsBridge | None
    ) = None,
    configuration_secrets_service: (
        ConfigurationSecretsService | None
    ) = None,
    configuration_options: Mapping[
        str,
        Any,
    ] | None = None,
    secrets_options: Mapping[
        str,
        Any,
    ] | None = None,
    bridge_options: Mapping[
        str,
        Any,
    ] | None = None,
    service_options: Mapping[
        str,
        Any,
    ] | None = None,
    install_signal_handlers: bool = True,
) -> AtlasSecureCore:
    """
    Build and register only the Atlas secure core.

    This compatibility builder is retained for focused security
    tests. Production startup should use build_infrastructure().
    """

    resolved_runtime = (
        runtime
        if runtime is not None
        else AtlasRuntime(
            metadata=runtime_metadata,
            install_signal_handlers=(
                install_signal_handlers
            ),
        )
    )

    _validate_runtime(
        resolved_runtime
    )

    resolved_configuration = (
        configuration_service
        if configuration_service is not None
        else ConfigurationService(
            **dict(
                configuration_options or {}
            )
        )
    )

    resolved_secrets = (
        secrets_manager
        if secrets_manager is not None
        else SecretsManager(
            **dict(
                secrets_options or {}
            )
        )
    )

    _assert_instance(
        resolved_configuration,
        ConfigurationService,
        "configuration_service",
    )

    _assert_instance(
        resolved_secrets,
        SecretsManager,
        "secrets_manager",
    )

    resolved_bridge = (
        configuration_secrets_bridge
        if configuration_secrets_bridge
        is not None
        else ConfigurationSecretsBridge(
            resolved_configuration,
            resolved_secrets,
            **dict(
                bridge_options or {}
            ),
        )
    )

    _assert_instance(
        resolved_bridge,
        ConfigurationSecretsBridge,
        "configuration_secrets_bridge",
    )

    if (
        resolved_bridge.configuration_service
        is not resolved_configuration
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsBridge uses a different "
            "ConfigurationService instance."
        )

    if (
        resolved_bridge.secrets_manager
        is not resolved_secrets
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsBridge uses a different "
            "SecretsManager instance."
        )

    resolved_configuration_secrets_service = (
        configuration_secrets_service
        if configuration_secrets_service
        is not None
        else ConfigurationSecretsService(
            resolved_configuration,
            resolved_secrets,
            bridge=resolved_bridge,
            **dict(
                service_options or {}
            ),
        )
    )

    _assert_instance(
        resolved_configuration_secrets_service,
        ConfigurationSecretsService,
        "configuration_secrets_service",
    )

    if (
        resolved_configuration_secrets_service
        .configuration_service
        is not resolved_configuration
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsService uses a different "
            "ConfigurationService instance."
        )

    if (
        resolved_configuration_secrets_service
        .secrets_manager
        is not resolved_secrets
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsService uses a different "
            "SecretsManager instance."
        )

    if (
        resolved_configuration_secrets_service.bridge
        is not resolved_bridge
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsService uses a different "
            "ConfigurationSecretsBridge instance."
        )

    configuration_name = _service_name(
        resolved_configuration
    )

    secrets_name = _service_name(
        resolved_secrets
    )

    resolved_runtime.register_service(
        resolved_configuration,
        dependencies=(),
        critical=True,
    )

    resolved_runtime.register_service(
        resolved_secrets,
        dependencies=(),
        critical=True,
    )

    resolved_runtime.register_service(
        resolved_configuration_secrets_service,
        dependencies=(
            configuration_name,
            secrets_name,
        ),
        critical=True,
    )

    logger.info(
        "Atlas secure core registered successfully."
    )

    return AtlasSecureCore(
        runtime=resolved_runtime,
        configuration_service=(
            resolved_configuration
        ),
        secrets_manager=resolved_secrets,
        configuration_secrets_bridge=(
            resolved_bridge
        ),
        configuration_secrets_service=(
            resolved_configuration_secrets_service
        ),
        plaintext_values_exposed=False,
    )


# =========================================================
# FULL INFRASTRUCTURE BUILDER
# =========================================================


def build_infrastructure(
    *,
    runtime: AtlasRuntime | None = None,
    runtime_metadata: Mapping[
        str,
        Any,
    ] | None = None,
    configuration_service: (
        ConfigurationService | None
    ) = None,
    secrets_manager: SecretsManager | None = None,
    configuration_secrets_bridge: (
        ConfigurationSecretsBridge | None
    ) = None,
    configuration_secrets_service: (
        ConfigurationSecretsService | None
    ) = None,
    event_bus: EventBusService | None = None,
    metrics_service: MetricsService | None = None,
    audit_service: AuditLogService | None = None,
    scheduler_service: SchedulerService | None = None,
    health_monitor_service: (
        HealthMonitorService | None
    ) = None,
    configuration_options: Mapping[
        str,
        Any,
    ] | None = None,
    secrets_options: Mapping[
        str,
        Any,
    ] | None = None,
    bridge_options: Mapping[
        str,
        Any,
    ] | None = None,
    configuration_secrets_options: Mapping[
        str,
        Any,
    ] | None = None,
    event_bus_options: Mapping[
        str,
        Any,
    ] | None = None,
    metrics_options: Mapping[
        str,
        Any,
    ] | None = None,
    audit_options: Mapping[
        str,
        Any,
    ] | None = None,
    scheduler_options: Mapping[
        str,
        Any,
    ] | None = None,
    health_monitor_options: Mapping[
        str,
        Any,
    ] | None = None,
    install_signal_handlers: bool = True,
) -> AtlasInfrastructure:
    """
    Build the complete AtlasOS production infrastructure.

    No services are started by this function. After registering
    secret bindings, call:

        infrastructure.runtime.validate()
        infrastructure.runtime.start()
    """

    resolved_runtime = (
        runtime
        if runtime is not None
        else AtlasRuntime(
            metadata=runtime_metadata,
            install_signal_handlers=(
                install_signal_handlers
            ),
        )
    )

    _validate_runtime(
        resolved_runtime
    )

    # -----------------------------------------------------
    # SECURE CORE
    # -----------------------------------------------------

    resolved_configuration = (
        configuration_service
        if configuration_service is not None
        else ConfigurationService(
            **dict(
                configuration_options or {}
            )
        )
    )

    resolved_secrets = (
        secrets_manager
        if secrets_manager is not None
        else SecretsManager(
            **dict(
                secrets_options or {}
            )
        )
    )

    _assert_instance(
        resolved_configuration,
        ConfigurationService,
        "configuration_service",
    )

    _assert_instance(
        resolved_secrets,
        SecretsManager,
        "secrets_manager",
    )

    resolved_bridge = (
        configuration_secrets_bridge
        if configuration_secrets_bridge
        is not None
        else ConfigurationSecretsBridge(
            resolved_configuration,
            resolved_secrets,
            **dict(
                bridge_options or {}
            ),
        )
    )

    _assert_instance(
        resolved_bridge,
        ConfigurationSecretsBridge,
        "configuration_secrets_bridge",
    )

    if (
        resolved_bridge.configuration_service
        is not resolved_configuration
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsBridge uses a different "
            "ConfigurationService instance."
        )

    if (
        resolved_bridge.secrets_manager
        is not resolved_secrets
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsBridge uses a different "
            "SecretsManager instance."
        )

    resolved_configuration_secrets_service = (
        configuration_secrets_service
        if configuration_secrets_service
        is not None
        else ConfigurationSecretsService(
            resolved_configuration,
            resolved_secrets,
            bridge=resolved_bridge,
            **dict(
                configuration_secrets_options
                or {}
            ),
        )
    )

    _assert_instance(
        resolved_configuration_secrets_service,
        ConfigurationSecretsService,
        "configuration_secrets_service",
    )

    if (
        resolved_configuration_secrets_service
        .configuration_service
        is not resolved_configuration
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsService uses a different "
            "ConfigurationService instance."
        )

    if (
        resolved_configuration_secrets_service
        .secrets_manager
        is not resolved_secrets
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsService uses a different "
            "SecretsManager instance."
        )

    if (
        resolved_configuration_secrets_service.bridge
        is not resolved_bridge
    ):
        raise AtlasBootstrapConfigurationError(
            "ConfigurationSecretsService uses a different "
            "ConfigurationSecretsBridge instance."
        )

    # -----------------------------------------------------
    # EVENT BUS
    # -----------------------------------------------------

    resolved_event_bus = (
        event_bus
        if event_bus is not None
        else EventBusService(
            **dict(
                event_bus_options or {}
            )
        )
    )

    _assert_instance(
        resolved_event_bus,
        EventBusService,
        "event_bus",
    )

    # -----------------------------------------------------
    # METRICS
    # -----------------------------------------------------

    metrics_kwargs = dict(
        metrics_options or {}
    )

    metrics_kwargs.setdefault(
        "event_bus",
        resolved_event_bus,
    )

    metrics_kwargs.setdefault(
        "collect_event_metrics",
        True,
    )

    resolved_metrics = (
        metrics_service
        if metrics_service is not None
        else MetricsService(
            **metrics_kwargs
        )
    )

    _assert_instance(
        resolved_metrics,
        MetricsService,
        "metrics_service",
    )

    # -----------------------------------------------------
    # AUDIT
    # -----------------------------------------------------

    audit_kwargs = dict(
        audit_options or {}
    )

    audit_kwargs.setdefault(
        "audit_file",
        Path(
            "runtime_data/audit/"
            "atlas_os_audit.jsonl"
        ),
    )

    audit_kwargs.setdefault(
        "load_existing_records",
        True,
    )

    resolved_audit = (
        audit_service
        if audit_service is not None
        else AuditLogService(
            resolved_event_bus,
            **audit_kwargs,
        )
    )

    _assert_instance(
        resolved_audit,
        AuditLogService,
        "audit_service",
    )

    if (
        resolved_audit.event_bus
        is not resolved_event_bus
    ):
        raise AtlasBootstrapConfigurationError(
            "AuditLogService uses a different "
            "EventBusService instance."
        )

    # -----------------------------------------------------
    # SCHEDULER
    # -----------------------------------------------------

    scheduler_kwargs = dict(
        scheduler_options or {}
    )

    scheduler_kwargs.setdefault(
        "event_bus",
        resolved_event_bus,
    )

    scheduler_kwargs.setdefault(
        "publish_events",
        True,
    )

    resolved_scheduler = (
        scheduler_service
        if scheduler_service is not None
        else SchedulerService(
            **scheduler_kwargs
        )
    )

    _assert_instance(
        resolved_scheduler,
        SchedulerService,
        "scheduler_service",
    )

    # -----------------------------------------------------
    # HEALTH MONITOR
    # -----------------------------------------------------

    resolved_health_monitor = (
        health_monitor_service
        if health_monitor_service is not None
        else HealthMonitorService(
            resolved_runtime.kernel,
            **dict(
                health_monitor_options or {}
            ),
        )
    )

    _assert_instance(
        resolved_health_monitor,
        HealthMonitorService,
        "health_monitor_service",
    )

    if (
        resolved_health_monitor.kernel
        is not resolved_runtime.kernel
    ):
        raise AtlasBootstrapConfigurationError(
            "HealthMonitorService uses a different "
            "AtlasOSKernel instance."
        )

    # -----------------------------------------------------
    # SERVICE NAMES
    # -----------------------------------------------------

    configuration_name = _service_name(
        resolved_configuration
    )

    secrets_name = _service_name(
        resolved_secrets
    )

    configuration_secrets_name = (
        _service_name(
            resolved_configuration_secrets_service
        )
    )

    event_bus_name = _service_name(
        resolved_event_bus
    )

    metrics_name = _service_name(
        resolved_metrics
    )

    audit_name = _service_name(
        resolved_audit
    )

    scheduler_name = _service_name(
        resolved_scheduler
    )

    # -----------------------------------------------------
    # REGISTRATION
    # -----------------------------------------------------

    resolved_runtime.register_service(
        resolved_configuration,
        dependencies=(),
        critical=True,
    )

    resolved_runtime.register_service(
        resolved_secrets,
        dependencies=(),
        critical=True,
    )

    resolved_runtime.register_service(
        resolved_configuration_secrets_service,
        dependencies=(
            configuration_name,
            secrets_name,
        ),
        critical=True,
    )

    resolved_runtime.register_service(
        resolved_event_bus,
        dependencies=(),
        critical=True,
    )

    resolved_runtime.register_service(
        resolved_metrics,
        dependencies=(
            event_bus_name,
        ),
        critical=True,
    )

    resolved_runtime.register_service(
        resolved_audit,
        dependencies=(
            event_bus_name,
        ),
        critical=True,
    )

    resolved_runtime.register_service(
        resolved_scheduler,
        dependencies=(
            event_bus_name,
        ),
        critical=True,
    )

    resolved_runtime.register_service(
        resolved_health_monitor,
        dependencies=(
            configuration_secrets_name,
            event_bus_name,
            metrics_name,
            audit_name,
            scheduler_name,
        ),
        critical=True,
    )

    logger.info(
        "Atlas infrastructure registered successfully. "
        "Service count: %s.",
        resolved_runtime.service_count,
    )

    return AtlasInfrastructure(
        runtime=resolved_runtime,
        configuration_service=(
            resolved_configuration
        ),
        secrets_manager=resolved_secrets,
        configuration_secrets_bridge=(
            resolved_bridge
        ),
        configuration_secrets_service=(
            resolved_configuration_secrets_service
        ),
        event_bus=resolved_event_bus,
        metrics_service=resolved_metrics,
        audit_service=resolved_audit,
        scheduler_service=resolved_scheduler,
        health_monitor_service=(
            resolved_health_monitor
        ),
        plaintext_values_exposed=False,
    )


__all__ = [
    "AtlasSecureCore",
    "AtlasInfrastructure",
    "AtlasBootstrapError",
    "AtlasBootstrapConfigurationError",
    "build_secure_core",
    "build_infrastructure",
]