"""
============================================================
ATLAS OS DEPENDENCY-AWARE SERVICE MANAGER v1.0
============================================================

Dependency-aware lifecycle orchestration for AtlasOS services.

Responsibilities
----------------
- Define service dependencies
- Validate dependency declarations
- Detect missing dependencies
- Detect circular dependencies
- Calculate deterministic startup order
- Start dependencies before dependants
- Stop dependants before dependencies
- Isolate service failures
- Skip blocked services safely
- Support transactional startup rollback
- Produce orchestration plans

Example
-------
MarketFeed
    |
    +--> Risk
    |
    +--> Portfolio
              |
              +--> Execution

Calculated startup order:

MarketFeed
Risk
Portfolio
Execution

Calculated shutdown order:

Execution
Portfolio
Risk
MarketFeed

Design principles
-----------------
- Thread safe
- Deterministic
- Explicit dependencies
- Cycle safe
- Failure isolated
- No trading-specific implementation
- Compatible with ServiceRegistry
- Safe for gradual legacy integration

============================================================
"""

from __future__ import annotations

import logging
import threading

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping

from atlas_os.contracts import (
    AtlasService,
    ServiceState,
)
from atlas_os.services.registry import (
    DuplicateServiceError,
    ServiceNotFoundError,
    ServiceOperationResult,
    ServiceRegistry,
)


logger = logging.getLogger(
    "AtlasAI.AtlasOS.DependencyServiceManager"
)


class DependencyManagerError(RuntimeError):
    """
    Base exception for dependency orchestration failures.
    """


class MissingDependencyError(DependencyManagerError):
    """
    Raised when a declared dependency is not registered.
    """


class CircularDependencyError(DependencyManagerError):
    """
    Raised when the dependency graph contains a cycle.
    """


class InvalidDependencyError(DependencyManagerError):
    """
    Raised when a dependency declaration is invalid.
    """


class ServiceBlockedError(DependencyManagerError):
    """
    Raised when a service cannot start because a dependency failed.
    """


class OrchestrationAction(StrEnum):
    """
    Supported orchestration actions.
    """

    START = "START"
    STOP = "STOP"
    SKIP = "SKIP"
    ROLLBACK = "ROLLBACK"


@dataclass(frozen=True, slots=True)
class DependencyDeclaration:
    """
    Immutable dependency declaration for one service.
    """

    service_name: str
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrchestrationStep:
    """
    One planned or completed orchestration step.
    """

    service_name: str
    action: OrchestrationAction
    success: bool
    state: ServiceState
    dependencies: tuple[str, ...] = ()
    message: str = ""
    error: str | None = None
    completed_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class OrchestrationPlan:
    """
    Immutable service orchestration plan.
    """

    target_services: tuple[str, ...]
    startup_order: tuple[str, ...]
    shutdown_order: tuple[str, ...]
    dependencies: Mapping[str, tuple[str, ...]]
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """
    Result of a dependency-aware lifecycle operation.
    """

    operation: str
    success: bool
    steps: tuple[OrchestrationStep, ...]
    started_services: tuple[str, ...] = ()
    stopped_services: tuple[str, ...] = ()
    skipped_services: tuple[str, ...] = ()
    rolled_back_services: tuple[str, ...] = ()
    completed_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


class DependencyServiceManager:
    """
    Dependency-aware service orchestration manager.

    This manager owns a ServiceRegistry and adds an explicit directed
    dependency graph on top of it.

    A declaration such as:

        register(execution, dependencies=("Risk", "Portfolio"))

    means that Risk and Portfolio must be operational before
    Execution can start.
    """

    VERSION = "1.0.0"

    NAME = "AtlasOSDependencyServiceManager"

    def __init__(
        self,
        registry: ServiceRegistry | None = None,
    ) -> None:

        self._registry = (
            registry
            if registry is not None
            else ServiceRegistry()
        )

        self._dependencies: dict[
            str,
            tuple[str, ...],
        ] = {}

        self._display_names: dict[
            str,
            str,
        ] = {}

        self._lock = threading.RLock()

    # =====================================================
    # BASIC INFORMATION
    # =====================================================

    @property
    def registry(self) -> ServiceRegistry:
        """
        Return the underlying service registry.
        """

        return self._registry

    @property
    def service_count(self) -> int:
        """
        Return registered service count.
        """

        return self._registry.service_count

    def __len__(self) -> int:
        """
        Return registered service count.
        """

        return self.service_count

    def __contains__(
        self,
        service_name: object,
    ) -> bool:
        """
        Return True when the service is registered.
        """

        return service_name in self._registry

    # =====================================================
    # REGISTRATION
    # =====================================================

    def register(
        self,
        service: AtlasService,
        *,
        dependencies: Iterable[str] = (),
    ) -> None:
        """
        Register a service and its dependency declarations.

        Dependencies may be registered before or after this service.
        Full graph validation occurs before planning or startup.
        """

        service_name = service.identity.name.strip()

        service_key = self._normalize_name(
            service_name
        )

        dependency_names = self._normalize_dependencies(
            service_name=service_name,
            dependencies=dependencies,
        )

        with self._lock:

            if service_key in self._dependencies:
                raise DuplicateServiceError(
                    f"Service '{service_name}' is already "
                    "registered in the dependency manager."
                )

            self._registry.register(
                service
            )

            self._dependencies[
                service_key
            ] = dependency_names

            self._display_names[
                service_key
            ] = service_name

            logger.info(
                "AtlasOS dependency service registered: "
                "%s | dependencies=%s",
                service_name,
                dependency_names,
            )

    def unregister(
        self,
        service_name: str,
        *,
        stop_if_running: bool = False,
        allow_dependants: bool = False,
    ) -> AtlasService:
        """
        Remove a service from the manager.

        By default, a service cannot be removed while another
        registered service depends on it.
        """

        service_key = self._normalize_name(
            service_name
        )

        with self._lock:

            self._require_registered_key(
                service_key
            )

            dependant_names = self.dependants_of(
                service_name,
                recursive=False,
            )

            if dependant_names and not allow_dependants:
                raise InvalidDependencyError(
                    f"Service '{self._display_name(service_key)}' "
                    "cannot be removed because these services depend "
                    f"on it: {', '.join(dependant_names)}."
                )

            removed = self._registry.unregister(
                service_name,
                stop_if_running=stop_if_running,
            )

            del self._dependencies[
                service_key
            ]

            del self._display_names[
                service_key
            ]

            if allow_dependants:

                updated: dict[
                    str,
                    tuple[str, ...],
                ] = {}

                for key, dependencies in (
                    self._dependencies.items()
                ):

                    updated[key] = tuple(
                        dependency
                        for dependency in dependencies
                        if dependency != service_key
                    )

                self._dependencies.update(
                    updated
                )

            logger.info(
                "AtlasOS dependency service unregistered: %s",
                removed.identity.name,
            )

            return removed

    # =====================================================
    # DEPENDENCY DECLARATIONS
    # =====================================================

    def dependencies_of(
        self,
        service_name: str,
        *,
        recursive: bool = False,
    ) -> tuple[str, ...]:
        """
        Return direct or recursive dependencies of a service.
        """

        service_key = self._normalize_name(
            service_name
        )

        with self._lock:

            self._require_registered_key(
                service_key
            )

            if not recursive:

                return tuple(
                    self._display_name(key)
                    for key in self._dependencies[
                        service_key
                    ]
                )

            ordered_keys = self._collect_dependency_keys(
                service_key
            )

            return tuple(
                self._display_name(key)
                for key in ordered_keys
                if key != service_key
            )

    def dependants_of(
        self,
        service_name: str,
        *,
        recursive: bool = False,
    ) -> tuple[str, ...]:
        """
        Return services that depend on the requested service.
        """

        target_key = self._normalize_name(
            service_name
        )

        with self._lock:

            self._require_registered_key(
                target_key
            )

            direct_dependants = [
                service_key
                for service_key, dependencies
                in self._dependencies.items()
                if target_key in dependencies
            ]

            if not recursive:

                return tuple(
                    self._display_name(key)
                    for key in direct_dependants
                )

            visited: set[str] = set()
            ordered: list[str] = []

            def visit(
                current_key: str,
            ) -> None:

                for dependant_key in self._dependencies:

                    if current_key not in self._dependencies[
                        dependant_key
                    ]:
                        continue

                    if dependant_key in visited:
                        continue

                    visited.add(
                        dependant_key
                    )

                    ordered.append(
                        dependant_key
                    )

                    visit(
                        dependant_key
                    )

            visit(
                target_key
            )

            return tuple(
                self._display_name(key)
                for key in ordered
            )

    def declarations(
        self,
    ) -> tuple[DependencyDeclaration, ...]:
        """
        Return all dependency declarations.
        """

        with self._lock:

            declarations: list[
                DependencyDeclaration
            ] = []

            for service_key in (
                self._registry.registration_order
            ):

                normalized_key = self._normalize_name(
                    service_key
                )

                dependencies = self._dependencies.get(
                    normalized_key,
                    (),
                )

                declarations.append(
                    DependencyDeclaration(
                        service_name=self._display_name(
                            normalized_key
                        ),
                        dependencies=tuple(
                            self._display_name(key)
                            for key in dependencies
                        ),
                    )
                )

            return tuple(
                declarations
            )

    # =====================================================
    # VALIDATION
    # =====================================================

    def validate(self) -> None:
        """
        Validate the complete dependency graph.

        Raises
        ------
        MissingDependencyError
            A dependency is declared but not registered.

        CircularDependencyError
            The dependency graph contains a cycle.
        """

        with self._lock:

            self._validate_missing_dependencies()

            self._calculate_topological_keys(
                tuple(
                    self._dependencies.keys()
                )
            )

    # =====================================================
    # PLANNING
    # =====================================================

    def plan_all(self) -> OrchestrationPlan:
        """
        Build an orchestration plan for every registered service.
        """

        with self._lock:

            target_keys = tuple(
                self._dependencies.keys()
            )

            return self._build_plan_from_keys(
                target_keys
            )

    def plan_for(
        self,
        service_name: str,
    ) -> OrchestrationPlan:
        """
        Build an orchestration plan for one service and all of its
        recursive dependencies.
        """

        service_key = self._normalize_name(
            service_name
        )

        with self._lock:

            self._require_registered_key(
                service_key
            )

            target_keys = tuple(
                self._collect_dependency_keys(
                    service_key
                )
            )

            return self._build_plan_from_keys(
                target_keys
            )

    # =====================================================
    # START OPERATIONS
    # =====================================================

    def start(
        self,
        service_name: str,
        *,
        rollback_on_failure: bool = True,
    ) -> OrchestrationResult:
        """
        Start one target service and all required dependencies.
        """

        plan = self.plan_for(
            service_name
        )

        return self._execute_start_plan(
            plan,
            rollback_on_failure=rollback_on_failure,
        )

    def start_all(
        self,
        *,
        rollback_on_failure: bool = True,
    ) -> OrchestrationResult:
        """
        Start every registered service in dependency order.
        """

        plan = self.plan_all()

        return self._execute_start_plan(
            plan,
            rollback_on_failure=rollback_on_failure,
        )

    # =====================================================
    # STOP OPERATIONS
    # =====================================================

    def stop(
        self,
        service_name: str,
        *,
        include_dependants: bool = True,
    ) -> OrchestrationResult:
        """
        Stop one service.

        When include_dependants is True, all running dependant
        services are stopped before the requested service.
        """

        target_key = self._normalize_name(
            service_name
        )

        with self._lock:

            self._require_registered_key(
                target_key
            )

            keys: list[str] = [
                target_key
            ]

            if include_dependants:

                for dependant_name in self.dependants_of(
                    service_name,
                    recursive=True,
                ):

                    dependant_key = self._normalize_name(
                        dependant_name
                    )

                    if dependant_key not in keys:
                        keys.append(
                            dependant_key
                        )

            startup_keys = self._calculate_topological_keys(
                tuple(keys)
            )

            shutdown_keys = tuple(
                reversed(
                    startup_keys
                )
            )

            return self._execute_stop_keys(
                shutdown_keys
            )

    def stop_all(self) -> OrchestrationResult:
        """
        Stop every service in reverse dependency order.
        """

        plan = self.plan_all()

        shutdown_keys = tuple(
            self._normalize_name(name)
            for name in plan.shutdown_order
        )

        return self._execute_stop_keys(
            shutdown_keys
        )

    # =====================================================
    # START EXECUTION
    # =====================================================

    def _execute_start_plan(
        self,
        plan: OrchestrationPlan,
        *,
        rollback_on_failure: bool,
    ) -> OrchestrationResult:
        """
        Execute a startup plan.
        """

        steps: list[
            OrchestrationStep
        ] = []

        started_during_operation: list[
            str
        ] = []

        skipped_services: list[
            str
        ] = []

        failed_keys: set[
            str
        ] = set()

        for service_name in plan.startup_order:

            service_key = self._normalize_name(
                service_name
            )

            service = self._registry.require(
                service_name
            )

            dependency_keys = self._dependencies[
                service_key
            ]

            blocked_dependencies = [
                dependency_key
                for dependency_key in dependency_keys
                if (
                    dependency_key in failed_keys
                    or self._registry.require(
                        self._display_name(
                            dependency_key
                        )
                    ).state
                    not in {
                        ServiceState.RUNNING,
                        ServiceState.DEGRADED,
                    }
                )
            ]

            if blocked_dependencies:

                dependency_display_names = tuple(
                    self._display_name(key)
                    for key in blocked_dependencies
                )

                message = (
                    "Service startup skipped because required "
                    "dependencies are not operational: "
                    + ", ".join(
                        dependency_display_names
                    )
                )

                steps.append(
                    OrchestrationStep(
                        service_name=service.identity.name,
                        action=OrchestrationAction.SKIP,
                        success=False,
                        state=service.state,
                        dependencies=tuple(
                            self._display_name(key)
                            for key in dependency_keys
                        ),
                        message=message,
                        error=(
                            f"{ServiceBlockedError.__name__}: "
                            f"{message}"
                        ),
                    )
                )

                failed_keys.add(
                    service_key
                )

                skipped_services.append(
                    service.identity.name
                )

                continue

            was_operational = service.state in {
                ServiceState.RUNNING,
                ServiceState.DEGRADED,
            }

            operation_result = self._registry.start(
                service.identity.name
            )

            steps.append(
                self._operation_to_step(
                    operation_result,
                    dependencies=tuple(
                        self._display_name(key)
                        for key in dependency_keys
                    ),
                )
            )

            if operation_result.success:

                if (
                    not was_operational
                    and service.state
                    in {
                        ServiceState.RUNNING,
                        ServiceState.DEGRADED,
                    }
                ):
                    started_during_operation.append(
                        service.identity.name
                    )

                continue

            failed_keys.add(
                service_key
            )

        startup_success = (
            not failed_keys
            and not skipped_services
        )

        rolled_back_services: list[
            str
        ] = []

        if (
            not startup_success
            and rollback_on_failure
            and started_during_operation
        ):

            for started_name in reversed(
                started_during_operation
            ):

                rollback_result = self._registry.stop(
                    started_name
                )

                steps.append(
                    OrchestrationStep(
                        service_name=started_name,
                        action=OrchestrationAction.ROLLBACK,
                        success=rollback_result.success,
                        state=rollback_result.state,
                        message=(
                            "Service rolled back after startup "
                            "orchestration failure."
                        ),
                        error=rollback_result.error,
                    )
                )

                if rollback_result.success:
                    rolled_back_services.append(
                        started_name
                    )

        return OrchestrationResult(
            operation="START",
            success=startup_success,
            steps=tuple(steps),
            started_services=tuple(
                started_during_operation
            ),
            skipped_services=tuple(
                skipped_services
            ),
            rolled_back_services=tuple(
                rolled_back_services
            ),
        )

    # =====================================================
    # STOP EXECUTION
    # =====================================================

    def _execute_stop_keys(
        self,
        shutdown_keys: tuple[str, ...],
    ) -> OrchestrationResult:
        """
        Stop services using a precomputed dependency-safe order.
        """

        steps: list[
            OrchestrationStep
        ] = []

        stopped_services: list[
            str
        ] = []

        overall_success = True

        for service_key in shutdown_keys:

            service_name = self._display_name(
                service_key
            )

            operation_result = self._registry.stop(
                service_name
            )

            step = self._operation_to_step(
                operation_result,
                dependencies=tuple(
                    self._display_name(key)
                    for key in self._dependencies[
                        service_key
                    ]
                ),
            )

            steps.append(
                step
            )

            if operation_result.success:
                stopped_services.append(
                    service_name
                )
            else:
                overall_success = False

        return OrchestrationResult(
            operation="STOP",
            success=overall_success,
            steps=tuple(steps),
            stopped_services=tuple(
                stopped_services
            ),
        )

    # =====================================================
    # GRAPH OPERATIONS
    # =====================================================

    def _build_plan_from_keys(
        self,
        target_keys: tuple[str, ...],
    ) -> OrchestrationPlan:
        """
        Create an immutable orchestration plan.
        """

        self._validate_missing_dependencies()

        startup_keys = self._calculate_topological_keys(
            target_keys
        )

        shutdown_keys = tuple(
            reversed(
                startup_keys
            )
        )

        dependency_map: dict[
            str,
            tuple[str, ...],
        ] = {}

        for service_key in startup_keys:

            service_name = self._display_name(
                service_key
            )

            dependency_map[
                service_name
            ] = tuple(
                self._display_name(key)
                for key in self._dependencies[
                    service_key
                ]
            )

        return OrchestrationPlan(
            target_services=tuple(
                self._display_name(key)
                for key in target_keys
            ),
            startup_order=tuple(
                self._display_name(key)
                for key in startup_keys
            ),
            shutdown_order=tuple(
                self._display_name(key)
                for key in shutdown_keys
            ),
            dependencies=MappingProxyType(
                dependency_map.copy()
            ),
        )

    def _calculate_topological_keys(
        self,
        target_keys: tuple[str, ...],
    ) -> tuple[str, ...]:
        """
        Calculate deterministic topological startup order.

        Raises CircularDependencyError when a cycle is detected.
        """

        visited: set[str] = set()

        visiting: set[str] = set()

        ordered: list[str] = []

        path: list[str] = []

        def visit(
            service_key: str,
        ) -> None:

            if service_key in visited:
                return

            if service_key in visiting:

                cycle_start = path.index(
                    service_key
                )

                cycle_keys = (
                    path[cycle_start:]
                    + [service_key]
                )

                cycle_names = [
                    self._display_name(key)
                    for key in cycle_keys
                ]

                raise CircularDependencyError(
                    "Circular service dependency detected: "
                    + " -> ".join(
                        cycle_names
                    )
                )

            self._require_registered_key(
                service_key
            )

            visiting.add(
                service_key
            )

            path.append(
                service_key
            )

            for dependency_key in self._dependencies[
                service_key
            ]:

                self._require_registered_key(
                    dependency_key,
                    dependency_of=service_key,
                )

                visit(
                    dependency_key
                )

            path.pop()

            visiting.remove(
                service_key
            )

            visited.add(
                service_key
            )

            ordered.append(
                service_key
            )

        for target_key in target_keys:
            visit(
                target_key
            )

        return tuple(
            ordered
        )

    def _collect_dependency_keys(
        self,
        service_key: str,
    ) -> tuple[str, ...]:
        """
        Collect a service and all recursive dependencies in safe order.
        """

        return self._calculate_topological_keys(
            (service_key,)
        )

    def _validate_missing_dependencies(
        self,
    ) -> None:
        """
        Validate that every dependency is registered.
        """

        for service_key, dependencies in (
            self._dependencies.items()
        ):

            for dependency_key in dependencies:

                if dependency_key not in self._dependencies:
                    raise MissingDependencyError(
                        f"Service '{self._display_name(service_key)}' "
                        "depends on unregistered service "
                        f"'{dependency_key}'."
                    )

    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    def _require_registered_key(
        self,
        service_key: str,
        *,
        dependency_of: str | None = None,
    ) -> None:
        """
        Validate a normalized service key.
        """

        if service_key in self._dependencies:
            return

        if dependency_of is not None:
            raise MissingDependencyError(
                f"Service '{self._display_name(dependency_of)}' "
                "depends on unregistered service "
                f"'{service_key}'."
            )

        raise ServiceNotFoundError(
            f"Service '{service_key}' is not registered."
        )

    def _display_name(
        self,
        service_key: str,
    ) -> str:
        """
        Return the original display name for a normalized key.
        """

        return self._display_names.get(
            service_key,
            service_key,
        )

    @staticmethod
    def _operation_to_step(
        result: ServiceOperationResult,
        *,
        dependencies: tuple[str, ...],
    ) -> OrchestrationStep:
        """
        Convert a registry operation result into an orchestration step.
        """

        action = (
            OrchestrationAction.START
            if result.operation == "START"
            else OrchestrationAction.STOP
        )

        return OrchestrationStep(
            service_name=result.service_name,
            action=action,
            success=result.success,
            state=result.state,
            dependencies=dependencies,
            message=result.message,
            error=result.error,
            completed_at=result.completed_at,
        )

    def _normalize_dependencies(
        self,
        *,
        service_name: str,
        dependencies: Iterable[str],
    ) -> tuple[str, ...]:
        """
        Normalize and validate dependency declarations.
        """

        service_key = self._normalize_name(
            service_name
        )

        normalized: list[str] = []

        seen: set[str] = set()

        for dependency_name in dependencies:

            dependency_key = self._normalize_name(
                dependency_name
            )

            if dependency_key == service_key:
                raise InvalidDependencyError(
                    f"Service '{service_name}' cannot depend "
                    "on itself."
                )

            if dependency_key in seen:
                continue

            seen.add(
                dependency_key
            )

            normalized.append(
                dependency_key
            )

        return tuple(
            normalized
        )

    @staticmethod
    def _normalize_name(
        service_name: str,
    ) -> str:
        """
        Normalize a service identifier.
        """

        if not isinstance(service_name, str):
            raise TypeError(
                "Service name must be a string."
            )

        normalized = service_name.strip().casefold()

        if not normalized:
            raise ValueError(
                "Service name cannot be empty."
            )

        return normalized