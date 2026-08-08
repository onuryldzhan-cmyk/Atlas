"""
============================================================
ATLAS OS KERNEL TESTS v2.0
============================================================

Pytest coverage for the Atlas OS kernel lifecycle.

Coverage
--------
- Service registration
- Dependency-aware startup ordering
- Kernel startup
- Service startup
- Kernel health reporting
- Kernel snapshot reporting
- Kernel shutdown
- Service shutdown

TEST-QUALITY-001
----------------
This module intentionally uses a helper service class whose name does
not begin with ``Test`` so that pytest does not mistake the helper for
a test class.

The previous implementation exposed a manual ``run_kernel_test()``
function. Pytest did not collect that function, which meant this module
contributed no executed tests to the canonical test suite.

============================================================
"""

from __future__ import annotations

from datetime import UTC, datetime

from atlas_os.core import (
    AtlasKernel,
    AtlasService,
    HealthReport,
    HealthState,
    KernelState,
    ServiceMetadata,
    ServiceSnapshot,
    ServiceState,
)


class FakeService(AtlasService):
    """
    Controlled AtlasService implementation used only by kernel tests.

    The class deliberately does not use pytest's ``Test*`` naming
    convention because it is a test helper rather than a test case.
    """

    def __init__(
        self,
        name: str,
        *,
        dependencies: tuple[str, ...] = (),
    ) -> None:
        self._metadata = ServiceMetadata(
            name=name,
            version="1.0",
            description=f"Test service: {name}",
            dependencies=dependencies,
        )

        self._state = ServiceState.CREATED
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._last_error: str | None = None

    @property
    def metadata(self) -> ServiceMetadata:
        return self._metadata

    @property
    def state(self) -> ServiceState:
        return self._state

    def initialize(self) -> None:
        self._state = ServiceState.INITIALIZING
        self._state = ServiceState.READY

    def start(self) -> None:
        if self._state not in {
            ServiceState.READY,
            ServiceState.STOPPED,
        }:
            raise RuntimeError(
                f"{self.metadata.name} cannot start from {self._state}."
            )

        self._state = ServiceState.STARTING
        self._started_at = datetime.now(UTC)
        self._stopped_at = None
        self._state = ServiceState.RUNNING

    def stop(self) -> None:
        self._state = ServiceState.STOPPING
        self._stopped_at = datetime.now(UTC)
        self._state = ServiceState.STOPPED

    def health_check(self) -> HealthReport:
        health_state = (
            HealthState.HEALTHY
            if self._state == ServiceState.RUNNING
            else HealthState.UNKNOWN
        )

        return HealthReport(
            service_name=self.metadata.name,
            state=health_state,
            message=f"Service state: {self._state.value}",
        )

    def snapshot(self) -> ServiceSnapshot:
        return ServiceSnapshot(
            name=self.metadata.name,
            version=self.metadata.version,
            state=self._state,
            critical=self.metadata.critical,
            dependencies=self.metadata.dependencies,
            started_at=self._started_at,
            stopped_at=self._stopped_at,
            last_error=self._last_error,
        )


def _build_kernel() -> tuple[
    AtlasKernel,
    FakeService,
    FakeService,
    FakeService,
]:
    """
    Build a kernel with a deterministic three-service dependency graph.

    Dependency graph
    ----------------
    ConfigurationService
        |
        v
    EventBusService
        |
        v
    HealthMonitorService

    Services are intentionally registered in reverse dependency order
    so that the kernel dependency resolver is exercised.
    """

    kernel = AtlasKernel()

    configuration = FakeService(
        "ConfigurationService",
    )

    event_bus = FakeService(
        "EventBusService",
        dependencies=("ConfigurationService",),
    )

    health_monitor = FakeService(
        "HealthMonitorService",
        dependencies=(
            "ConfigurationService",
            "EventBusService",
        ),
    )

    kernel.register_service(health_monitor)
    kernel.register_service(event_bus)
    kernel.register_service(configuration)

    return (
        kernel,
        configuration,
        event_bus,
        health_monitor,
    )


def test_kernel_resolves_dependency_aware_startup_order() -> None:
    """
    Kernel registry must resolve dependencies rather than blindly using
    reverse registration order.
    """

    (
        kernel,
        configuration,
        event_bus,
        health_monitor,
    ) = _build_kernel()

    assert set(kernel.registry.names()) == {
        "ConfigurationService",
        "EventBusService",
        "HealthMonitorService",
    }

    startup_order = kernel.registry.resolve_startup_order()

    startup_names = [
        service.metadata.name
        for service in startup_order
    ]

    assert startup_names == [
        configuration.metadata.name,
        event_bus.metadata.name,
        health_monitor.metadata.name,
    ]


def test_kernel_start_transitions_all_services_to_running() -> None:
    """
    Starting the kernel must initialize and start every registered
    service successfully.
    """

    (
        kernel,
        configuration,
        event_bus,
        health_monitor,
    ) = _build_kernel()

    kernel.start()

    try:
        assert kernel.state == KernelState.RUNNING

        assert configuration.state == ServiceState.RUNNING
        assert event_bus.state == ServiceState.RUNNING
        assert health_monitor.state == ServiceState.RUNNING

        assert configuration.snapshot().started_at is not None
        assert event_bus.snapshot().started_at is not None
        assert health_monitor.snapshot().started_at is not None

    finally:
        kernel.stop()


def test_kernel_health_and_snapshot_reflect_running_services() -> None:
    """
    Health and snapshot views must describe the active kernel and all
    running services consistently.
    """

    (
        kernel,
        configuration,
        event_bus,
        health_monitor,
    ) = _build_kernel()

    kernel.start()

    try:
        health = kernel.health()

        assert "services" in health
        assert len(health["services"]) == 3

        health_by_name = {
            service["name"]: service
            for service in health["services"]
        }

        expected_names = {
            configuration.metadata.name,
            event_bus.metadata.name,
            health_monitor.metadata.name,
        }

        assert set(health_by_name) == expected_names

        for service_name in expected_names:
            service_health = health_by_name[service_name]

            assert service_health["state"] == HealthState.HEALTHY.value
            assert service_health["message"]

        snapshot = kernel.snapshot()

        assert snapshot.state == KernelState.RUNNING
        assert snapshot.registered_services == 3
        assert snapshot.running_services == 3
        assert snapshot.healthy_services == 3
        assert snapshot.uptime_seconds >= 0.0

    finally:
        kernel.stop()


def test_kernel_stop_transitions_all_services_to_stopped() -> None:
    """
    Stopping the kernel must stop every service and leave the kernel in
    the STOPPED state.
    """

    (
        kernel,
        configuration,
        event_bus,
        health_monitor,
    ) = _build_kernel()

    kernel.start()

    assert kernel.state == KernelState.RUNNING

    kernel.stop()

    assert kernel.state == KernelState.STOPPED

    assert configuration.state == ServiceState.STOPPED
    assert event_bus.state == ServiceState.STOPPED
    assert health_monitor.state == ServiceState.STOPPED

    assert configuration.snapshot().stopped_at is not None
    assert event_bus.snapshot().stopped_at is not None
    assert health_monitor.snapshot().stopped_at is not None