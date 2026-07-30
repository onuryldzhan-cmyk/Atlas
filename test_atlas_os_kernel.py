"""
AtlasOS Kernel manual integration test.
"""

from __future__ import annotations

import json

from atlas_os import (
    AtlasOSKernel,
    BaseAtlasService,
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
                description="AtlasOS demonstration service.",
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
    print("ATLAS OS KERNEL v1.0 TEST")
    print("=" * 60)

    kernel = AtlasOSKernel()

    kernel.register_service(
        DemoService(
            "MarketFeedService"
        )
    )

    kernel.register_service(
        DemoService(
            "RiskService"
        ),
        dependencies=(
            "MarketFeedService",
        ),
    )

    kernel.register_service(
        DemoService(
            "PortfolioService"
        ),
        dependencies=(
            "MarketFeedService",
        ),
    )

    kernel.register_service(
        DemoService(
            "ExecutionService"
        ),
        dependencies=(
            "RiskService",
            "PortfolioService",
        ),
    )

    plan = kernel.plan()

    print("\nSTARTUP PLAN")
    print("-" * 60)

    for index, service_name in enumerate(
        plan.startup_order,
        start=1,
    ):
        print(
            f"{index}. {service_name}"
        )

    print("\nKERNEL START")
    print("-" * 60)

    start_result = kernel.start()

    print(
        json.dumps(
            {
                "success": start_result.success,
                "kernel_state": kernel.state.value,
                "service_count": kernel.service_count,
                "health": kernel.health().status.value,
                "uptime_seconds": (
                    kernel.uptime_seconds
                ),
            },
            indent=4,
        )
    )

    print("\nKERNEL STOP")
    print("-" * 60)

    stop_result = kernel.stop()

    print(
        json.dumps(
            {
                "success": stop_result.success,
                "kernel_state": kernel.state.value,
                "health": kernel.health().status.value,
                "uptime_seconds": (
                    kernel.uptime_seconds
                ),
            },
            indent=4,
        )
    )


if __name__ == "__main__":
    main()