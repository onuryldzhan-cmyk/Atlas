"""
AtlasOS Event Bus manual integration test.
"""

from __future__ import annotations

import json

from atlas_os import (
    AtlasEvent,
    EventBusService,
    EventSeverity,
)


def main() -> None:

    print("=" * 60)
    print("ATLAS OS EVENT BUS v1.0 TEST")
    print("=" * 60)

    event_bus = EventBusService(
        history_limit=100
    )

    received_events: list[
        AtlasEvent
    ] = []

    audit_events: list[
        AtlasEvent
    ] = []

    def service_listener(
        event: AtlasEvent,
    ) -> None:

        received_events.append(
            event
        )

        print(
            f"[SERVICE LISTENER] "
            f"{event.event_type} | "
            f"{event.source}"
        )

    def audit_listener(
        event: AtlasEvent,
    ) -> None:

        audit_events.append(
            event
        )

        print(
            f"[AUDIT] "
            f"{event.severity.value} | "
            f"{event.event_type}"
        )

    event_bus.subscribe(
        "SERVICE_STARTED",
        service_listener,
        subscriber_name="ServiceListener",
    )

    event_bus.subscribe(
        "*",
        audit_listener,
        subscriber_name="AuditListener",
    )

    event_bus.start()

    print("\nPUBLISH EVENTS")
    print("-" * 60)

    start_result = (
        event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="AtlasOSKernel",
            payload={
                "service": "MarketFeedService",
                "version": "1.0.0",
            },
            severity=EventSeverity.INFO,
            correlation_id="startup-001",
        )
    )

    health_result = (
        event_bus.publish_event(
            event_type="HEALTH_DEGRADED",
            source="HealthMonitor",
            payload={
                "service": "MarketFeedService",
                "reason": "Exchange latency",
            },
            severity=EventSeverity.WARNING,
            correlation_id="health-001",
        )
    )

    snapshot = (
        event_bus.event_bus_snapshot()
    )

    print("\nEVENT BUS SNAPSHOT")
    print("-" * 60)

    print(
        json.dumps(
            {
                "running": snapshot.running,
                "subscription_count": (
                    snapshot.subscription_count
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
                "history_size": (
                    snapshot.history_size
                ),
                "service_start_deliveries": (
                    start_result.successful_deliveries
                ),
                "health_deliveries": (
                    health_result.successful_deliveries
                ),
                "service_listener_events": len(
                    received_events
                ),
                "audit_events": len(
                    audit_events
                ),
            },
            indent=4,
        )
    )

    print("\nEVENT HISTORY")
    print("-" * 60)

    for event in event_bus.event_history():

        print(
            f"{event.created_at.isoformat()} | "
            f"{event.severity.value} | "
            f"{event.event_type} | "
            f"{event.source}"
        )

    event_bus.stop()


if __name__ == "__main__":
    main()