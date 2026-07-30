"""
Tests for AtlasOS Kernel Event Integration.
"""

from __future__ import annotations

import unittest

from atlas_os import (
    AtlasEvent,
    AtlasSystemEventType,
    BaseAtlasService,
    EventAwareAtlasOSKernel,
    EventAwareHealthMonitorService,
    EventBusService,
    EventSeverity,
    KernelState,
    ServiceIdentity,
    ServiceState,
)


class IntegrationTestService(BaseAtlasService):
    """
    Controllable service for event integration tests.
    """

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
                description="Event integration test service.",
            )
        )

        self.fail_start = fail_start
        self.fail_stop = fail_stop

    def _on_start(self) -> None:

        if self.fail_start:
            raise RuntimeError(
                f"{self.identity.name} startup failed."
            )

    def _on_stop(self) -> None:

        if self.fail_stop:
            raise RuntimeError(
                f"{self.identity.name} shutdown failed."
            )


class EventIntegrationTests(unittest.TestCase):

    def setUp(self) -> None:

        self.event_bus = EventBusService(
            history_limit=100
        )

        self.received_events: list[
            AtlasEvent
        ] = []

        self.event_bus.subscribe(
            "*",
            self.received_events.append,
            subscriber_name="TestAuditListener",
        )

        self.event_bus.start()

        self.kernel = EventAwareAtlasOSKernel(
            self.event_bus
        )

    def tearDown(self) -> None:

        if self.kernel.is_running:
            self.kernel.stop()

        if self.event_bus.is_running:
            self.event_bus.stop()

    def event_types(self) -> list[str]:

        return [
            event.event_type
            for event in self.received_events
        ]

    def test_kernel_start_events_are_published(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        result = self.kernel.start()

        self.assertTrue(
            result.success
        )

        event_types = self.event_types()

        self.assertIn(
            AtlasSystemEventType
            .KERNEL_STARTING.value,
            event_types,
        )

        self.assertIn(
            AtlasSystemEventType
            .SERVICE_STARTED.value,
            event_types,
        )

        self.assertIn(
            AtlasSystemEventType
            .KERNEL_STARTED.value,
            event_types,
        )

    def test_kernel_start_event_order(self) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        self.kernel.start()

        event_types = self.event_types()

        self.assertEqual(
            event_types,
            [
                "KERNEL_STARTING",
                "SERVICE_STARTED",
                "KERNEL_STARTED",
            ],
        )

    def test_service_dependencies_generate_events_in_order(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        self.kernel.register_service(
            IntegrationTestService(
                "RiskService"
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        self.kernel.start()

        service_events = [
            event.payload["service_name"]
            for event in self.received_events
            if event.event_type
            == "SERVICE_STARTED"
        ]

        self.assertEqual(
            service_events,
            [
                "MarketFeed",
                "RiskService",
            ],
        )

    def test_start_failure_event_is_published(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "FailingService",
                fail_start=True,
            )
        )

        result = self.kernel.start()

        self.assertFalse(
            result.success
        )

        event_types = self.event_types()

        self.assertIn(
            "SERVICE_START_FAILED",
            event_types,
        )

        self.assertIn(
            "KERNEL_START_FAILED",
            event_types,
        )

        self.assertEqual(
            self.kernel.state,
            KernelState.FAILED,
        )

    def test_blocked_service_event_is_published(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed",
                fail_start=True,
            )
        )

        self.kernel.register_service(
            IntegrationTestService(
                "RiskService"
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        self.kernel.start(
            rollback_on_failure=False
        )

        event_types = self.event_types()

        self.assertIn(
            "SERVICE_START_SKIPPED",
            event_types,
        )

    def test_rollback_event_is_published(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        self.kernel.register_service(
            IntegrationTestService(
                "ExecutionService",
                fail_start=True,
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        self.kernel.start(
            rollback_on_failure=True
        )

        event_types = self.event_types()

        self.assertIn(
            "SERVICE_ROLLED_BACK",
            event_types,
        )

    def test_kernel_stop_events_are_published(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        self.kernel.start()

        self.received_events.clear()

        result = self.kernel.stop()

        self.assertTrue(
            result.success
        )

        self.assertEqual(
            self.event_types(),
            [
                "KERNEL_STOPPING",
                "SERVICE_STOPPED",
                "KERNEL_STOPPED",
            ],
        )

    def test_event_payload_contains_service_state(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        self.kernel.start()

        service_event = next(
            event
            for event in self.received_events
            if event.event_type
            == "SERVICE_STARTED"
        )

        self.assertEqual(
            service_event.payload[
                "service_name"
            ],
            "MarketFeed",
        )

        self.assertEqual(
            service_event.payload["state"],
            ServiceState.RUNNING.value,
        )

    def test_lifecycle_events_share_correlation_id(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        self.kernel.start()

        correlation_ids = {
            event.correlation_id
            for event in self.received_events
        }

        self.assertEqual(
            len(correlation_ids),
            1,
        )

        self.assertNotIn(
            None,
            correlation_ids,
        )

    def test_event_statistics_are_recorded(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        self.kernel.start()

        statistics = (
            self.kernel.event_statistics()
        )

        self.assertEqual(
            statistics.publication_attempts,
            3,
        )

        self.assertEqual(
            statistics.successful_publications,
            3,
        )

        self.assertEqual(
            statistics.failed_publications,
            0,
        )

    def test_stopped_event_bus_does_not_crash_kernel(
        self,
    ) -> None:

        self.event_bus.stop()

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        result = self.kernel.start()

        self.assertTrue(
            result.success
        )

        statistics = (
            self.kernel.event_statistics()
        )

        self.assertGreater(
            statistics.failed_publications,
            0,
        )

    def test_health_monitor_initial_event(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        self.kernel.start()

        self.received_events.clear()

        monitor = (
            EventAwareHealthMonitorService(
                self.kernel,
                self.event_bus,
                interval_seconds=1.0,
            )
        )

        monitor.poll_once()

        self.assertIn(
            "HEALTH_MONITOR_INITIALIZED",
            self.event_types(),
        )

    def test_health_degraded_event(
        self,
    ) -> None:

        service = IntegrationTestService(
            "MarketFeed"
        )

        self.kernel.register_service(
            service
        )

        self.kernel.start()

        monitor = (
            EventAwareHealthMonitorService(
                self.kernel,
                self.event_bus,
                interval_seconds=1.0,
            )
        )

        monitor.poll_once()

        self.received_events.clear()

        service.mark_degraded(
            "Simulated latency."
        )

        monitor.poll_once()

        self.assertIn(
            "HEALTH_DEGRADED",
            self.event_types(),
        )

        degraded_event = (
            self.received_events[-1]
        )

        self.assertEqual(
            degraded_event.severity,
            EventSeverity.WARNING,
        )

    def test_health_recovered_event(
        self,
    ) -> None:

        service = IntegrationTestService(
            "MarketFeed"
        )

        self.kernel.register_service(
            service
        )

        self.kernel.start()

        monitor = (
            EventAwareHealthMonitorService(
                self.kernel,
                self.event_bus,
                interval_seconds=1.0,
            )
        )

        monitor.poll_once()

        service.mark_degraded(
            "Temporary latency."
        )

        monitor.poll_once()

        self.received_events.clear()

        service.recover()

        monitor.poll_once()

        self.assertIn(
            "HEALTH_RECOVERED",
            self.event_types(),
        )

    def test_health_transition_is_not_duplicated(
        self,
    ) -> None:

        self.kernel.register_service(
            IntegrationTestService(
                "MarketFeed"
            )
        )

        self.kernel.start()

        self.received_events.clear()

        monitor = (
            EventAwareHealthMonitorService(
                self.kernel,
                self.event_bus,
                interval_seconds=1.0,
            )
        )

        monitor.poll_once()
        monitor.poll_once()
        monitor.poll_once()

        initialized_events = [
            event
            for event in self.received_events
            if event.event_type
            == "HEALTH_MONITOR_INITIALIZED"
        ]

        self.assertEqual(
            len(initialized_events),
            1,
        )


if __name__ == "__main__":
    unittest.main()