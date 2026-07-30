"""
AtlasOS Audit Log manual integration test.
"""

from __future__ import annotations

import json

from atlas_os import (
    AtlasEvent,
    AuditLogService,
    AuditQuery,
    BaseAtlasService,
    EventAwareAtlasOSKernel,
    EventAwareHealthMonitorService,
    EventBusService,
    ServiceIdentity,
)


class AuditDemoService(BaseAtlasService):

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
                    "AtlasOS Audit Log demo service."
                ),
            )
        )

    def _on_start(self) -> None:

        print(
            f"[START] {self.identity.name}"
        )

    def _on_stop(self) -> None:

        print(
            f"[STOP] {self.identity.name}"
        )


def main() -> None:

    print("=" * 60)
    print("ATLAS OS AUDIT LOG SERVICE v1.0")
    print("=" * 60)

    event_bus = EventBusService(
        history_limit=500
    )

    event_bus.start()

    audit = AuditLogService(
        event_bus,
        audit_file=(
            "runtime_data/audit/"
            "atlas_os_audit.jsonl"
        ),
        history_limit=500,
    )

    audit.start()

    kernel = EventAwareAtlasOSKernel(
        event_bus
    )

    market_service = AuditDemoService(
        "MarketFeedService"
    )

    risk_service = AuditDemoService(
        "RiskService"
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

    monitor.poll_once()

    print("\nDEGRADATION")
    print("-" * 60)

    market_service.mark_degraded(
        "Simulated exchange latency."
    )

    monitor.poll_once()

    print("\nRECOVERY")
    print("-" * 60)

    market_service.recover()

    monitor.poll_once()

    print("\nKERNEL STOP")
    print("-" * 60)

    kernel.stop()

    statistics = (
        audit.statistics()
    )

    warning_records = audit.query(
        AuditQuery(
            severities=(
                "WARNING",
            )
        )
    )

    kernel_records = audit.query(
        AuditQuery(
            event_types=(
                "KERNEL_STARTING",
                "KERNEL_STARTED",
                "KERNEL_STOPPING",
                "KERNEL_STOPPED",
            )
        )
    )

    print("\nAUDIT SNAPSHOT")
    print("-" * 60)

    print(
        json.dumps(
            {
                "audit_file": str(
                    audit.audit_file
                ),
                "records_received": (
                    statistics.records_received
                ),
                "records_persisted": (
                    statistics.records_persisted
                ),
                "persistence_failures": (
                    statistics.persistence_failures
                ),
                "history_size": (
                    statistics.current_history_size
                ),
                "file_size_bytes": (
                    statistics.current_file_size_bytes
                ),
                "warning_records": len(
                    warning_records
                ),
                "kernel_records": len(
                    kernel_records
                ),
            },
            indent=4,
        )
    )

    print("\nRECENT AUDIT RECORDS")
    print("-" * 60)

    for index, record in enumerate(
        audit.records(),
        start=1,
    ):

        print(
            f"{index:02d}. "
            f"{record.event_type:<28} | "
            f"{record.severity:<8} | "
            f"{record.source}"
        )

    audit.stop()
    event_bus.stop()


if __name__ == "__main__":
    main()