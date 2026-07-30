"""
AtlasOS Health Monitor manual integration test.
"""

from __future__ import annotations

import json
import time

from atlas_os import (
    AtlasOSKernel,
    BaseAtlasService,
    HealthMonitorService,
    ServiceIdentity,
)


class DemoMarketService(BaseAtlasService):

    def __init__(self) -> None:

        super().__init__(
            ServiceIdentity(
                name="MarketFeedService",
                version="1.0.0",
                service_type="MARKET_DATA",
                description="Demo market feed service.",
            )
        )

    def _on_start(self) -> None:

        print(
            "[START] MarketFeedService"
        )

    def _on_stop(self) -> None:

        print(
            "[STOP] MarketFeedService"
        )


def print_observation(
    title: str,
    monitor: HealthMonitorService,
) -> None:

    observation = monitor.poll_once()

    print("\n" + title)
    print("-" * 60)

    print(
        json.dumps(
            {
                "sequence": observation.sequence,
                "kernel_state": (
                    observation.kernel_state.value
                ),
                "health": (
                    observation.kernel_status.value
                ),
                "service_health": (
                    observation.service_status.value
                ),
                "healthy_services": (
                    observation.healthy_services
                ),
                "degraded_services": (
                    observation.degraded_services
                ),
                "unhealthy_services": (
                    observation.unhealthy_services
                ),
                "operational": (
                    observation.operational
                ),
            },
            indent=4,
        )
    )


def main() -> None:

    print("=" * 60)
    print("ATLAS OS HEALTH MONITOR v1.0 TEST")
    print("=" * 60)

    kernel = AtlasOSKernel()

    market_service = DemoMarketService()

    kernel.register_service(
        market_service
    )

    kernel.start()

    monitor = HealthMonitorService(
        kernel,
        interval_seconds=0.5,
        history_limit=100,
    )

    monitor.start()

    print_observation(
        "1. NORMAL SYSTEM",
        monitor,
    )

    market_service.mark_degraded(
        "Simulated exchange latency."
    )

    print_observation(
        "2. DEGRADED SYSTEM",
        monitor,
    )

    market_service.recover()

    print_observation(
        "3. RECOVERED SYSTEM",
        monitor,
    )

    time.sleep(0.6)

    snapshot = (
        monitor.monitor_snapshot()
    )

    print("\nMONITOR SNAPSHOT")
    print("-" * 60)

    print(
        json.dumps(
            {
                "running": snapshot.running,
                "thread_alive": (
                    snapshot.thread_alive
                ),
                "observation_count": (
                    snapshot.observation_count
                ),
                "transition_count": (
                    snapshot.transition_count
                ),
                "last_health": (
                    snapshot
                    .last_observation
                    .kernel_status
                    .value
                    if snapshot.last_observation
                    else None
                ),
                "last_transition": (
                    snapshot
                    .last_transition
                    .transition_type
                    .value
                    if snapshot.last_transition
                    else None
                ),
            },
            indent=4,
        )
    )

    monitor.stop()
    kernel.stop()


if __name__ == "__main__":
    main()