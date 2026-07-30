"""
============================================================
ATLAS OS KERNEL TEST v1.0
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


class TestService(AtlasService):
    """
    Controlled test implementation of an AtlasOS service.
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


def run_kernel_test() -> None:
    print("=" * 60)
    print("ATLAS OS KERNEL TEST v1.0")
    print("=" * 60)

    kernel = AtlasKernel()

    configuration = TestService(
        "ConfigurationService",
    )

    event_bus = TestService(
        "EventBusService",
        dependencies=("ConfigurationService",),
    )

    health_monitor = TestService(
        "HealthMonitorService",
        dependencies=(
            "ConfigurationService",
            "EventBusService",
        ),
    )

    kernel.register_service(health_monitor)
    kernel.register_service(event_bus)
    kernel.register_service(configuration)

    print("\n[1] REGISTERED SERVICES")

    for name in kernel.registry.names():
        print(f" - {name}")

    startup_order = kernel.registry.resolve_startup_order()

    print("\n[2] RESOLVED STARTUP ORDER")

    for index, service in enumerate(startup_order, start=1):
        print(f" {index}. {service.metadata.name}")

    kernel.start()

    assert kernel.state == KernelState.RUNNING
    assert configuration.state == ServiceState.RUNNING
    assert event_bus.state == ServiceState.RUNNING
    assert health_monitor.state == ServiceState.RUNNING

    print("\n[3] KERNEL STARTED")
    print(f" Kernel state: {kernel.state.value}")

    print("\n[4] SERVICE HEALTH")

    health = kernel.health()

    for service in health["services"]:
        print(
            f" {service['name']}: "
            f"{service['state']} — {service['message']}"
        )

    snapshot = kernel.snapshot()

    print("\n[5] KERNEL SNAPSHOT")
    print(f" Version             : {snapshot.version}")
    print(f" State               : {snapshot.state.value}")
    print(
        f" Registered services : "
        f"{snapshot.registered_services}"
    )
    print(
        f" Running services    : "
        f"{snapshot.running_services}"
    )
    print(
        f" Healthy services    : "
        f"{snapshot.healthy_services}"
    )
    print(
        f" Uptime seconds      : "
        f"{snapshot.uptime_seconds:.6f}"
    )

    kernel.stop()

    assert kernel.state == KernelState.STOPPED
    assert configuration.state == ServiceState.STOPPED
    assert event_bus.state == ServiceState.STOPPED
    assert health_monitor.state == ServiceState.STOPPED

    print("\n[6] KERNEL STOPPED")
    print(f" Kernel state: {kernel.state.value}")

    print("\n" + "=" * 60)
    print("ATLAS OS KERNEL TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_kernel_test()