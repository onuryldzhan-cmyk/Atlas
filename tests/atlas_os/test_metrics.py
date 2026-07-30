"""
Tests for AtlasOS MetricsService.
"""

from __future__ import annotations

import time
import unittest

from atlas_os import (
    EventBusService,
    EventSeverity,
    HealthStatus,
    InvalidMetricNameError,
    MetricsService,
    MetricTypeConflictError,
)


class MetricsServiceTests(unittest.TestCase):

    def setUp(self) -> None:

        self.metrics = MetricsService(
            histogram_history_limit=5
        )

        self.metrics.start()

    def tearDown(self) -> None:

        if self.metrics.is_running:
            self.metrics.stop()

    def test_initial_service_gauge_exists(self) -> None:

        value = self.metrics.gauge_value(
            "atlas.metrics.service.running"
        )

        self.assertEqual(
            value,
            1.0,
        )

    def test_counter_increment(self) -> None:

        value = self.metrics.increment(
            "atlas.orders.total"
        )

        self.assertEqual(
            value,
            1.0,
        )

        value = self.metrics.increment(
            "atlas.orders.total",
            4,
        )

        self.assertEqual(
            value,
            5.0,
        )

    def test_counter_cannot_decrease(self) -> None:

        with self.assertRaises(ValueError):

            self.metrics.increment(
                "atlas.orders.total",
                -1,
            )

    def test_counter_labels_create_distinct_series(
        self,
    ) -> None:

        self.metrics.increment(
            "atlas.orders.total",
            labels={
                "side": "BUY",
            },
        )

        self.metrics.increment(
            "atlas.orders.total",
            labels={
                "side": "SELL",
            },
        )

        self.assertEqual(
            self.metrics.counter_value(
                "atlas.orders.total",
                labels={
                    "side": "BUY",
                },
            ),
            1.0,
        )

        self.assertEqual(
            self.metrics.counter_value(
                "atlas.orders.total",
                labels={
                    "side": "SELL",
                },
            ),
            1.0,
        )

    def test_label_order_is_deterministic(
        self,
    ) -> None:

        self.metrics.increment(
            "atlas.test.total",
            labels={
                "symbol": "BTCUSDT",
                "side": "BUY",
            },
        )

        value = self.metrics.counter_value(
            "atlas.test.total",
            labels={
                "side": "BUY",
                "symbol": "BTCUSDT",
            },
        )

        self.assertEqual(
            value,
            1.0,
        )

    def test_gauge_can_be_set(self) -> None:

        value = self.metrics.set_gauge(
            "atlas.positions.open",
            3,
        )

        self.assertEqual(
            value,
            3.0,
        )

    def test_gauge_can_be_adjusted(self) -> None:

        self.metrics.set_gauge(
            "atlas.balance",
            1000,
        )

        value = self.metrics.adjust_gauge(
            "atlas.balance",
            -250,
        )

        self.assertEqual(
            value,
            750.0,
        )

    def test_histogram_observation(self) -> None:

        self.metrics.observe(
            "atlas.execution.latency_seconds",
            0.10,
        )

        histogram = self.metrics.observe(
            "atlas.execution.latency_seconds",
            0.30,
        )

        self.assertEqual(
            histogram.count,
            2,
        )

        self.assertAlmostEqual(
            histogram.total,
            0.40,
        )

        self.assertAlmostEqual(
            histogram.average,
            0.20,
        )

        self.assertEqual(
            histogram.minimum,
            0.10,
        )

        self.assertEqual(
            histogram.maximum,
            0.30,
        )

    def test_histogram_history_is_bounded(
        self,
    ) -> None:

        for value in range(10):

            self.metrics.observe(
                "atlas.test.histogram",
                value,
            )

        histogram = self.metrics.histogram(
            "atlas.test.histogram"
        )

        self.assertEqual(
            histogram.count,
            10,
        )

        self.assertEqual(
            len(histogram.observations),
            5,
        )

        self.assertEqual(
            histogram.observations[-1],
            9.0,
        )

    def test_timer_records_duration(self) -> None:

        with self.metrics.timer(
            "atlas.operation.duration_seconds"
        ) as timer:

            time.sleep(
                0.001
            )

        self.assertIsNotNone(
            timer.elapsed_seconds
        )

        histogram = self.metrics.histogram(
            "atlas.operation.duration_seconds",
            labels={
                "outcome": "success",
            },
        )

        self.assertIsNotNone(
            histogram
        )

        self.assertEqual(
            histogram.count,
            1,
        )

        self.assertGreater(
            histogram.latest,
            0,
        )

    def test_timer_records_error_outcome(self) -> None:

        with self.assertRaises(RuntimeError):

            with self.metrics.timer(
                "atlas.failure.duration_seconds"
            ):

                raise RuntimeError(
                    "Simulated operation failure."
                )

        histogram = self.metrics.histogram(
            "atlas.failure.duration_seconds",
            labels={
                "outcome": "error",
            },
        )

        self.assertIsNotNone(
            histogram
        )

        self.assertEqual(
            histogram.count,
            1,
        )

    def test_metric_type_conflict_is_rejected(
        self,
    ) -> None:

        self.metrics.increment(
            "atlas.conflict.metric"
        )

        with self.assertRaises(
            MetricTypeConflictError
        ):

            self.metrics.set_gauge(
                "atlas.conflict.metric",
                1,
            )

    def test_invalid_metric_name_is_rejected(
        self,
    ) -> None:

        with self.assertRaises(
            InvalidMetricNameError
        ):

            self.metrics.increment(
                "invalid metric name"
            )

    def test_non_finite_value_is_rejected(
        self,
    ) -> None:

        with self.assertRaises(ValueError):

            self.metrics.observe(
                "atlas.invalid.value",
                float("inf"),
            )

    def test_metric_can_be_removed(self) -> None:

        self.metrics.increment(
            "atlas.removable.total"
        )

        removed = self.metrics.remove_metric(
            "atlas.removable.total"
        )

        self.assertTrue(
            removed
        )

        self.assertIsNone(
            self.metrics.counter_value(
                "atlas.removable.total"
            )
        )

    def test_snapshot_contains_metrics(self) -> None:

        self.metrics.increment(
            "atlas.orders.total"
        )

        self.metrics.set_gauge(
            "atlas.positions.open",
            2,
        )

        self.metrics.observe(
            "atlas.latency",
            0.2,
        )

        snapshot = (
            self.metrics.metrics_snapshot()
        )

        self.assertTrue(
            snapshot.running
        )

        self.assertGreaterEqual(
            len(snapshot.counters),
            1,
        )

        self.assertGreaterEqual(
            len(snapshot.gauges),
            2,
        )

        self.assertEqual(
            len(snapshot.histograms),
            1,
        )

    def test_statistics_are_recorded(self) -> None:

        self.metrics.increment(
            "atlas.orders.total"
        )

        self.metrics.set_gauge(
            "atlas.positions.open",
            2,
        )

        self.metrics.observe(
            "atlas.latency",
            0.2,
        )

        statistics = (
            self.metrics.statistics()
        )

        self.assertGreaterEqual(
            statistics.total_updates,
            4,
        )

        self.assertEqual(
            statistics.counter_updates,
            1,
        )

        self.assertGreaterEqual(
            statistics.gauge_updates,
            2,
        )

        self.assertEqual(
            statistics.histogram_updates,
            1,
        )

    def test_health_contains_metrics_statistics(
        self,
    ) -> None:

        self.metrics.increment(
            "atlas.orders.total"
        )

        report = self.metrics.health()

        self.assertEqual(
            report.status,
            HealthStatus.HEALTHY,
        )

        self.assertGreaterEqual(
            report.details[
                "total_metric_series"
            ],
            2,
        )

    def test_clear_metrics(self) -> None:

        self.metrics.increment(
            "atlas.orders.total"
        )

        self.metrics.observe(
            "atlas.latency",
            0.1,
        )

        self.metrics.clear_metrics()

        self.assertEqual(
            self.metrics.metric_series_count,
            0,
        )


class MetricsEventBusTests(unittest.TestCase):

    def setUp(self) -> None:

        self.event_bus = EventBusService(
            history_limit=100
        )

        self.event_bus.start()

        self.metrics = MetricsService(
            event_bus=self.event_bus,
            collect_event_metrics=True,
        )

        self.metrics.start()

    def tearDown(self) -> None:

        if self.metrics.is_running:
            self.metrics.stop()

        if self.event_bus.is_running:
            self.event_bus.stop()

    def test_event_subscription_is_active(
        self,
    ) -> None:

        self.assertTrue(
            self.metrics.event_subscription_active
        )

    def test_event_is_converted_to_metrics(
        self,
    ) -> None:

        self.event_bus.publish_event(
            event_type="KERNEL_STARTED",
            source="AtlasOS",
            severity=EventSeverity.INFO,
        )

        self.assertEqual(
            self.metrics.counter_value(
                "atlas.events.total"
            ),
            1.0,
        )

        self.assertEqual(
            self.metrics.counter_value(
                "atlas.events.by_type.total",
                labels={
                    "event_type": (
                        "KERNEL_STARTED"
                    ),
                },
            ),
            1.0,
        )

        self.assertEqual(
            self.metrics.counter_value(
                "atlas.events.by_severity.total",
                labels={
                    "severity": "INFO",
                },
            ),
            1.0,
        )

    def test_multiple_events_are_counted(
        self,
    ) -> None:

        self.event_bus.publish_event(
            event_type="KERNEL_STARTED",
            source="AtlasOS",
        )

        self.event_bus.publish_event(
            event_type="HEALTH_DEGRADED",
            source="HealthMonitor",
            severity=EventSeverity.WARNING,
        )

        self.assertEqual(
            self.metrics.counter_value(
                "atlas.events.total"
            ),
            2.0,
        )

        statistics = (
            self.metrics.statistics()
        )

        self.assertEqual(
            statistics.event_observations,
            2,
        )

    def test_stop_removes_event_subscription(
        self,
    ) -> None:

        self.metrics.stop()

        self.assertFalse(
            self.metrics.event_subscription_active
        )


if __name__ == "__main__":
    unittest.main()