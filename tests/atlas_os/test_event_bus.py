"""
Tests for AtlasOS EventBusService.
"""

from __future__ import annotations

import unittest

from atlas_os import (
    AtlasEvent,
    EventBusNotRunningError,
    EventBusService,
    EventSeverity,
    HealthStatus,
    SubscriptionNotFoundError,
)


class EventBusServiceTests(unittest.TestCase):

    def setUp(self) -> None:

        self.event_bus = EventBusService(
            history_limit=5,
            failure_history_limit=5,
        )

        self.received_events: list[
            AtlasEvent
        ] = []

    def _handler(
        self,
        event: AtlasEvent,
    ) -> None:

        self.received_events.append(
            event
        )

    def test_initial_state(self) -> None:

        self.assertEqual(
            self.event_bus.subscription_count,
            0,
        )

        self.assertEqual(
            self.event_bus.published_events,
            0,
        )

    def test_invalid_history_limit_is_rejected(
        self,
    ) -> None:

        with self.assertRaises(ValueError):

            EventBusService(
                history_limit=0
            )

    def test_publish_requires_running_bus(self) -> None:

        event = AtlasEvent(
            event_type="TEST_EVENT",
            source="UnitTest",
        )

        with self.assertRaises(
            EventBusNotRunningError
        ):
            self.event_bus.publish(
                event
            )

    def test_subscribe_and_publish(self) -> None:

        self.event_bus.subscribe(
            "SERVICE_STARTED",
            self._handler,
            subscriber_name="TestSubscriber",
        )

        self.event_bus.start()

        result = self.event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="Kernel",
            payload={
                "service": "MarketFeed",
            },
        )

        self.assertTrue(
            result.success
        )

        self.assertEqual(
            result.matched_subscribers,
            1,
        )

        self.assertEqual(
            len(self.received_events),
            1,
        )

        self.assertEqual(
            self.received_events[0]
            .payload["service"],
            "MarketFeed",
        )

    def test_event_type_is_case_insensitive(
        self,
    ) -> None:

        self.event_bus.subscribe(
            "service_started",
            self._handler,
        )

        self.event_bus.start()

        self.event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="Kernel",
        )

        self.assertEqual(
            len(self.received_events),
            1,
        )

    def test_unmatched_event_has_no_delivery(
        self,
    ) -> None:

        self.event_bus.subscribe(
            "SERVICE_STARTED",
            self._handler,
        )

        self.event_bus.start()

        result = self.event_bus.publish_event(
            event_type="SERVICE_STOPPED",
            source="Kernel",
        )

        self.assertTrue(
            result.success
        )

        self.assertEqual(
            result.matched_subscribers,
            0,
        )

        self.assertEqual(
            len(self.received_events),
            0,
        )

    def test_wildcard_subscription_receives_all_events(
        self,
    ) -> None:

        self.event_bus.subscribe(
            "*",
            self._handler,
            subscriber_name="AuditListener",
        )

        self.event_bus.start()

        self.event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="Kernel",
        )

        self.event_bus.publish_event(
            event_type="HEALTH_DEGRADED",
            source="HealthMonitor",
        )

        self.assertEqual(
            len(self.received_events),
            2,
        )

    def test_specific_and_wildcard_subscribers_receive_event(
        self,
    ) -> None:

        specific_events: list[
            AtlasEvent
        ] = []

        wildcard_events: list[
            AtlasEvent
        ] = []

        self.event_bus.subscribe(
            "SERVICE_STARTED",
            specific_events.append,
            subscriber_name="Specific",
        )

        self.event_bus.subscribe(
            "*",
            wildcard_events.append,
            subscriber_name="Wildcard",
        )

        self.event_bus.start()

        result = self.event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="Kernel",
        )

        self.assertEqual(
            result.matched_subscribers,
            2,
        )

        self.assertEqual(
            len(specific_events),
            1,
        )

        self.assertEqual(
            len(wildcard_events),
            1,
        )

    def test_unsubscribe_removes_handler(self) -> None:

        subscription = (
            self.event_bus.subscribe(
                "SERVICE_STARTED",
                self._handler,
            )
        )

        removed = self.event_bus.unsubscribe(
            subscription.subscription_id
        )

        self.assertEqual(
            removed.subscription_id,
            subscription.subscription_id,
        )

        self.event_bus.start()

        result = self.event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="Kernel",
        )

        self.assertEqual(
            result.matched_subscribers,
            0,
        )

    def test_unknown_subscription_is_rejected(
        self,
    ) -> None:

        with self.assertRaises(
            SubscriptionNotFoundError
        ):
            self.event_bus.unsubscribe(
                "missing-subscription"
            )

    def test_subscriber_failure_is_isolated(
        self,
    ) -> None:

        successful_events: list[
            AtlasEvent
        ] = []

        def failing_handler(
            event: AtlasEvent,
        ) -> None:

            raise RuntimeError(
                "Simulated subscriber failure."
            )

        self.event_bus.subscribe(
            "TEST_EVENT",
            failing_handler,
            subscriber_name="FailingSubscriber",
        )

        self.event_bus.subscribe(
            "TEST_EVENT",
            successful_events.append,
            subscriber_name="SuccessfulSubscriber",
        )

        self.event_bus.start()

        result = self.event_bus.publish_event(
            event_type="TEST_EVENT",
            source="UnitTest",
        )

        self.assertFalse(
            result.success
        )

        self.assertEqual(
            result.matched_subscribers,
            2,
        )

        self.assertEqual(
            result.successful_deliveries,
            1,
        )

        self.assertEqual(
            result.failed_deliveries,
            1,
        )

        self.assertEqual(
            len(successful_events),
            1,
        )

        self.assertEqual(
            len(
                self.event_bus.failure_history()
            ),
            1,
        )

    def test_event_history_is_bounded(self) -> None:

        self.event_bus.start()

        for index in range(8):

            self.event_bus.publish_event(
                event_type="TEST_EVENT",
                source="UnitTest",
                payload={
                    "index": index,
                },
            )

        history = (
            self.event_bus.event_history()
        )

        self.assertEqual(
            len(history),
            5,
        )

        self.assertEqual(
            history[-1].payload["index"],
            7,
        )

    def test_event_history_can_be_filtered(
        self,
    ) -> None:

        self.event_bus.start()

        self.event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="Kernel",
        )

        self.event_bus.publish_event(
            event_type="SERVICE_STOPPED",
            source="Kernel",
        )

        filtered = (
            self.event_bus.event_history(
                event_type="SERVICE_STARTED"
            )
        )

        self.assertEqual(
            len(filtered),
            1,
        )

        self.assertEqual(
            filtered[0].event_type,
            "SERVICE_STARTED",
        )

    def test_event_payload_is_immutable(self) -> None:

        event = AtlasEvent(
            event_type="TEST_EVENT",
            source="UnitTest",
            payload={
                "value": 1,
            },
        )

        with self.assertRaises(TypeError):

            event.payload["value"] = 2

    def test_event_metadata_is_normalized(
        self,
    ) -> None:

        event = AtlasEvent(
            event_type=" service_started ",
            source=" Kernel ",
            severity=EventSeverity.WARNING,
        )

        self.assertEqual(
            event.event_type,
            "SERVICE_STARTED",
        )

        self.assertEqual(
            event.source,
            "Kernel",
        )

        self.assertEqual(
            event.severity,
            EventSeverity.WARNING,
        )

    def test_snapshot_contains_statistics(
        self,
    ) -> None:

        self.event_bus.subscribe(
            "TEST_EVENT",
            self._handler,
        )

        self.event_bus.start()

        self.event_bus.publish_event(
            event_type="TEST_EVENT",
            source="UnitTest",
        )

        snapshot = (
            self.event_bus.event_bus_snapshot()
        )

        self.assertTrue(
            snapshot.running
        )

        self.assertEqual(
            snapshot.subscription_count,
            1,
        )

        self.assertEqual(
            snapshot.published_events,
            1,
        )

        self.assertEqual(
            snapshot.successful_deliveries,
            1,
        )

    def test_health_contains_event_statistics(
        self,
    ) -> None:

        self.event_bus.start()

        self.event_bus.publish_event(
            event_type="TEST_EVENT",
            source="UnitTest",
        )

        report = self.event_bus.health()

        self.assertEqual(
            report.status,
            HealthStatus.HEALTHY,
        )

        self.assertEqual(
            report.details[
                "published_events"
            ],
            1,
        )

    def test_clear_history_does_not_reset_statistics(
        self,
    ) -> None:

        self.event_bus.start()

        self.event_bus.publish_event(
            event_type="TEST_EVENT",
            source="UnitTest",
        )

        self.event_bus.clear_history()

        self.assertEqual(
            len(
                self.event_bus.event_history()
            ),
            0,
        )

        self.assertEqual(
            self.event_bus.published_events,
            1,
        )


if __name__ == "__main__":
    unittest.main()