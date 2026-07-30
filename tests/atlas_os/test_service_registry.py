"""
Tests for AtlasOS ServiceRegistry.
"""

from __future__ import annotations

import unittest

from atlas_os.contracts import (
    HealthStatus,
    ServiceIdentity,
    ServiceState,
)
from atlas_os.services import (
    BaseAtlasService,
    DuplicateServiceError,
    ServiceNotFoundError,
    ServiceRegistry,
    ServiceRemovalError,
)


class RegistryTestService(BaseAtlasService):
    """
    Controllable test service for registry tests.
    """

    lifecycle_events: list[str] = []

    def __init__(
        self,
        name: str,
        *,
        fail_start: bool = False,
        fail_stop: bool = False,
    ) -> None:

        super().__init__(
            ServiceIdentity(
                name=name,
                version="1.0.0",
                service_type="TEST",
                description="Registry test service.",
            )
        )

        self.fail_start = fail_start
        self.fail_stop = fail_stop

        self.start_count = 0
        self.stop_count = 0

    def _on_start(self) -> None:

        self.start_count += 1

        self.lifecycle_events.append(
            f"START:{self.identity.name}"
        )

        if self.fail_start:
            raise RuntimeError(
                f"{self.identity.name} startup failed."
            )

    def _on_stop(self) -> None:

        self.stop_count += 1

        self.lifecycle_events.append(
            f"STOP:{self.identity.name}"
        )

        if self.fail_stop:
            raise RuntimeError(
                f"{self.identity.name} shutdown failed."
            )

    def _health_details(self) -> dict[str, object]:

        return {
            "start_count": self.start_count,
            "stop_count": self.stop_count,
        }


class ServiceRegistryTests(unittest.TestCase):

    def setUp(self) -> None:

        RegistryTestService.lifecycle_events.clear()

        self.registry = ServiceRegistry()

    def test_registry_starts_empty(self) -> None:

        self.assertEqual(
            len(self.registry),
            0,
        )

        self.assertEqual(
            self.registry.service_count,
            0,
        )

    def test_register_service(self) -> None:

        service = RegistryTestService(
            "MarketFeed"
        )

        self.registry.register(
            service
        )

        self.assertEqual(
            len(self.registry),
            1,
        )

        self.assertIn(
            "MarketFeed",
            self.registry,
        )

        self.assertIs(
            self.registry.require("MarketFeed"),
            service,
        )

    def test_lookup_is_case_insensitive(self) -> None:

        service = RegistryTestService(
            "RiskService"
        )

        self.registry.register(
            service
        )

        self.assertIs(
            self.registry.require("riskservice"),
            service,
        )

        self.assertIs(
            self.registry.require("RISKSERVICE"),
            service,
        )

    def test_duplicate_service_is_rejected(self) -> None:

        self.registry.register(
            RegistryTestService(
                "PortfolioService"
            )
        )

        with self.assertRaises(
            DuplicateServiceError
        ):
            self.registry.register(
                RegistryTestService(
                    "portfolioservice"
                )
            )

    def test_missing_service_returns_none(self) -> None:

        self.assertIsNone(
            self.registry.get(
                "MissingService"
            )
        )

    def test_require_missing_service_raises(self) -> None:

        with self.assertRaises(
            ServiceNotFoundError
        ):
            self.registry.require(
                "MissingService"
            )

    def test_unregister_stopped_service(self) -> None:

        service = RegistryTestService(
            "LearningService"
        )

        self.registry.register(
            service
        )

        removed = self.registry.unregister(
            "LearningService"
        )

        self.assertIs(
            removed,
            service,
        )

        self.assertEqual(
            len(self.registry),
            0,
        )

    def test_running_service_cannot_be_removed_unsafely(self) -> None:

        service = RegistryTestService(
            "ExecutionService"
        )

        self.registry.register(
            service
        )

        service.start()

        with self.assertRaises(
            ServiceRemovalError
        ):
            self.registry.unregister(
                "ExecutionService"
            )

    def test_running_service_can_be_stopped_and_removed(self) -> None:

        service = RegistryTestService(
            "ExecutionService"
        )

        self.registry.register(
            service
        )

        service.start()

        removed = self.registry.unregister(
            "ExecutionService",
            stop_if_running=True,
        )

        self.assertIs(
            removed,
            service,
        )

        self.assertEqual(
            service.state,
            ServiceState.STOPPED,
        )

    def test_start_single_service(self) -> None:

        service = RegistryTestService(
            "MarketFeed"
        )

        self.registry.register(
            service
        )

        result = self.registry.start(
            "MarketFeed"
        )

        self.assertTrue(
            result.success
        )

        self.assertEqual(
            result.operation,
            "START",
        )

        self.assertEqual(
            service.state,
            ServiceState.RUNNING,
        )

    def test_stop_single_service(self) -> None:

        service = RegistryTestService(
            "MarketFeed"
        )

        self.registry.register(
            service
        )

        self.registry.start(
            "MarketFeed"
        )

        result = self.registry.stop(
            "MarketFeed"
        )

        self.assertTrue(
            result.success
        )

        self.assertEqual(
            service.state,
            ServiceState.STOPPED,
        )

    def test_start_all_uses_registration_order(self) -> None:

        self.registry.register(
            RegistryTestService("A")
        )

        self.registry.register(
            RegistryTestService("B")
        )

        self.registry.register(
            RegistryTestService("C")
        )

        results = self.registry.start_all()

        self.assertEqual(
            len(results),
            3,
        )

        self.assertTrue(
            all(
                result.success
                for result in results
            )
        )

        self.assertEqual(
            RegistryTestService.lifecycle_events,
            [
                "START:A",
                "START:B",
                "START:C",
            ],
        )

    def test_stop_all_uses_reverse_registration_order(self) -> None:

        self.registry.register(
            RegistryTestService("A")
        )

        self.registry.register(
            RegistryTestService("B")
        )

        self.registry.register(
            RegistryTestService("C")
        )

        self.registry.start_all()

        RegistryTestService.lifecycle_events.clear()

        results = self.registry.stop_all()

        self.assertEqual(
            len(results),
            3,
        )

        self.assertEqual(
            RegistryTestService.lifecycle_events,
            [
                "STOP:C",
                "STOP:B",
                "STOP:A",
            ],
        )

    def test_start_failure_is_isolated(self) -> None:

        first = RegistryTestService(
            "First"
        )

        failing = RegistryTestService(
            "Failing",
            fail_start=True,
        )

        third = RegistryTestService(
            "Third"
        )

        self.registry.register(first)
        self.registry.register(failing)
        self.registry.register(third)

        results = self.registry.start_all()

        self.assertEqual(
            len(results),
            3,
        )

        self.assertTrue(
            results[0].success
        )

        self.assertFalse(
            results[1].success
        )

        self.assertTrue(
            results[2].success
        )

        self.assertEqual(
            failing.state,
            ServiceState.FAILED,
        )

        self.assertEqual(
            third.state,
            ServiceState.RUNNING,
        )

    def test_stop_on_failure_prevents_later_startup(self) -> None:

        first = RegistryTestService(
            "First"
        )

        failing = RegistryTestService(
            "Failing",
            fail_start=True,
        )

        third = RegistryTestService(
            "Third"
        )

        self.registry.register(first)
        self.registry.register(failing)
        self.registry.register(third)

        results = self.registry.start_all(
            stop_on_failure=True
        )

        self.assertEqual(
            len(results),
            2,
        )

        self.assertEqual(
            third.state,
            ServiceState.CREATED,
        )

    def test_rollback_stops_previously_started_services(self) -> None:

        first = RegistryTestService(
            "First"
        )

        failing = RegistryTestService(
            "Failing",
            fail_start=True,
        )

        self.registry.register(first)
        self.registry.register(failing)

        results = self.registry.start_all(
            stop_on_failure=True,
            rollback_started=True,
        )

        self.assertEqual(
            len(results),
            2,
        )

        self.assertEqual(
            first.state,
            ServiceState.STOPPED,
        )

    def test_health_reports_healthy_registry(self) -> None:

        self.registry.register(
            RegistryTestService(
                "MarketFeed"
            )
        )

        self.registry.register(
            RegistryTestService(
                "RiskService"
            )
        )

        self.registry.start_all()

        report = self.registry.health()

        self.assertEqual(
            report.status,
            HealthStatus.HEALTHY,
        )

        self.assertEqual(
            report.total_services,
            2,
        )

        self.assertEqual(
            report.healthy_services,
            2,
        )

        self.assertTrue(
            report.is_operational
        )

    def test_health_detects_degraded_service(self) -> None:

        service = RegistryTestService(
            "MarketFeed"
        )

        self.registry.register(
            service
        )

        service.start()

        service.mark_degraded(
            "Dependency latency."
        )

        report = self.registry.health()

        self.assertEqual(
            report.status,
            HealthStatus.DEGRADED,
        )

        self.assertEqual(
            report.degraded_services,
            1,
        )

    def test_health_detects_failed_service(self) -> None:

        service = RegistryTestService(
            "Failing",
            fail_start=True,
        )

        self.registry.register(
            service
        )

        self.registry.start_all()

        report = self.registry.health()

        self.assertEqual(
            report.status,
            HealthStatus.UNHEALTHY,
        )

        self.assertEqual(
            report.unhealthy_services,
            1,
        )

        self.assertFalse(
            report.is_operational
        )

    def test_snapshot_contains_registered_services(self) -> None:

        service = RegistryTestService(
            "PortfolioService"
        )

        self.registry.register(
            service
        )

        service.start()

        snapshot = self.registry.snapshot()

        self.assertEqual(
            snapshot.service_count,
            1,
        )

        self.assertIn(
            "PortfolioService",
            snapshot.services,
        )

        self.assertEqual(
            snapshot.registration_order,
            ("PortfolioService",),
        )


if __name__ == "__main__":
    unittest.main()