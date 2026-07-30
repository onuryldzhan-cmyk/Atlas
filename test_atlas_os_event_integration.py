"""
AtlasOS Kernel Event Integration manual test.
"""

from __future__ import annotations

import json

from atlas_os import (
    AtlasEvent,
    BaseAtlasService,
    EventAwareAtlasOSKernel,
    EventAwareHealthMonitorService,
    EventBusService,
    ServiceIdentity,
)


class DemoService(BaseAtlasService):

    def __init__(
        self,
        name: str,
    ) -> None:

        super().__init__(
            ServiceIdentity(
                name=name,
                version="1.0.0",
                service_type="DEMO",
                description=(
                    "AtlasOS event integration "
                    "demo service."
                ),
            )
        )

    def _on_start(self) -> None:

        print(
            f"[SERVICE START] "
            f"{self.identity.name}"
        )

    def _on_stop(self) -> None:

        print(
            f"[SERVICE STOP] "
            f"{self.identity.name}"
        )


def main() -> None:

    print("=" * 60)
    print("ATLAS OS KERNEL EVENT INTEGRATION v1.0")
    print("=" * 60)

    event_bus = EventBusService(
        history_limit=200
    )

    received_events: list[
        AtlasEvent
    ] = []

    def audit_listener(
        event: AtlasEvent,
    ) -> None:

        received_events.append(
            event
        )

        print(
            f"[EVENT] "
            f"{event.severity.value:<8} | "
            f"{event.event_type:<28} | "
            f"{event.source}"
        )

    event_bus.subscribe(
        "*",
        audit_listener,
        subscriber_name="AtlasAuditListener",
    )

    event_bus.start()

    kernel = EventAwareAtlasOSKernel(
        event_bus
    )

    market_service = DemoService(
        "MarketFeedService"
    )

    risk_service = DemoService(
        "RiskService"
    )

    execution_service = DemoService(
        "ExecutionService"
    )

    kernel.register_service(
        market_service
    )

    kernel.register_service(
        risk_service,
        dependencies=(
            "MarketFeedService",
        ),
    )

    kernel.register_service(
        execution_service,
        dependencies=(
            "RiskService",
        ),
    )

    print("\nKERNEL START")
    print("-" * 60)

    kernel.start()

    monitor = (
        EventAwareHealthMonitorService(
            kernel,
            event_bus,
            interval_seconds=1.0,
        )
    )

    print("\nINITIAL HEALTH")
    print("-" * 60)

    monitor.poll_once()

    print("\nSIMULATED DEGRADATION")
    print("-" * 60)

    market_service.mark_degraded(
        "Simulated exchange latency."
    )

    monitor.poll_once()

    print("\nSIMULATED RECOVERY")
    print("-" * 60)

    market_service.recover()

    monitor.poll_once()

    print("\nKERNEL STOP")
    print("-" * 60)

    kernel.stop()

    snapshot = (
        event_bus.event_bus_snapshot()
    )

    kernel_statistics = (
        kernel.event_statistics()
    )

    monitor_statistics = (
        monitor.event_statistics()
    )

    print("\nINTEGRATION SNAPSHOT")
    print("-" * 60)

    print(
        json.dumps(
            {
                "event_bus_running": (
                    snapshot.running
                ),
                "published_events": (
                    snapshot.published_events
                ),
                "successful_deliveries": (
                    snapshot.successful_deliveries
                ),
                "failed_deliveries": (
                    snapshot.failed_deliveries
                ),
                "event_history_size": (
                    snapshot.history_size
                ),
                "kernel_event_attempts": (
                    kernel_statistics
                    .publication_attempts
                ),
                "kernel_event_failures": (
                    kernel_statistics
                    .failed_publications
                ),
                "health_event_attempts": (
                    monitor_statistics
                    .publication_attempts
                ),
                "health_event_failures": (
                    monitor_statistics
                    .failed_publications
                ),
                "final_kernel_state": (
                    kernel.state.value
                ),
            },
            indent=4,
        )
    )

    print("\nEVENT HISTORY")
    print("-" * 60)

    for index, event in enumerate(
        event_bus.event_history(),
        start=1,
    ):

        print(
            f"{index:02d}. "
            f"{event.event_type:<28} | "
            f"{event.severity.value:<8} | "
            f"{event.correlation_id}"
        )

    event_bus.stop()


if __name__ == "__main__":
    main()