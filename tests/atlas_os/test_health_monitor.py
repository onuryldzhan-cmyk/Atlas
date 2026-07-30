"""
Tests for AtlasOS HealthMonitorService.
"""

from __future__ import annotations

import time
import unittest

from atlas_os import (
    AtlasOSKernel,
    BaseAtlasService,
    HealthMonitorService,
    HealthStatus,
    HealthTransitionType,
    KernelState,
    ServiceIdentity,
)


class MonitorTestService(BaseAtlasService):
    """
    Controllable service for monitor tests.
    """

    def __init__(
        self,
        name: str = "MarketFeed",
    ) -> None:

        super().__init__(
            ServiceIdentity(
                name=name,
                version="1.0.0",
                service_type="TEST",
                description="Health monitor test service.",
            )
        )

    def _on_start(self) -> None:
        pass

    def _on_stop(self) -> None:
        pass


class HealthMonitorServiceTests(unittest.TestCase):

    def setUp(self) -> None:

        self.kernel = AtlasOSKernel()

        self.service = MonitorTestService()

        self.kernel.register_service(
            self.service
        )

        self.kernel.start()

        self.monitor = HealthMonitorService(
            self.kernel,
            interval_seconds=0.01,
            history_limit=10,
        )

    def tearDown(self) -> None:

        if self.monitor.is_running:
            self.monitor.stop()

        if self.kernel.is_running:
            self.kernel.stop()

    def test_initial_configuration(self) -> None:

        self.assertEqual(
            self.monitor.interval_seconds,
            0.01,
        )

        self.assertEqual(
            self.monitor.history_limit,
            10,
        )

        self.assertEqual(
            self.monitor.observation_count,
            0,
        )

    def test_invalid_interval_is_rejected(self) -> None:

        with self.assertRaises(ValueError):

            HealthMonitorService(
                self.kernel,
                interval_seconds=0,
            )

    def test_invalid_history_limit_is_rejected(self) -> None:

        with self.assertRaises(ValueError):

            HealthMonitorService(
                self.kernel,
                history_limit=0,
            )

    def test_poll_once_records_observation(self) -> None:

        observation = self.monitor.poll_once()

        self.assertEqual(
            observation.sequence,
            1,
        )

        self.assertEqual(
            observation.kernel_state,
            KernelState.RUNNING,
        )

        self.assertEqual(
            observation.kernel_status,
            HealthStatus.HEALTHY,
        )

        self.assertTrue(
            observation.operational
        )

        self.assertEqual(
            self.monitor.observation_count,
            1,
        )

    def test_first_poll_creates_initial_transition(
        self,
    ) -> None:

        self.monitor.poll_once()

        transition = (
            self.monitor.last_transition
        )

        self.assertIsNotNone(
            transition
        )

        self.assertEqual(
            transition.transition_type,
            HealthTransitionType.INITIALIZED,
        )

    def test_repeated_same_health_creates_no_new_transition(
        self,
    ) -> None:

        self.monitor.poll_once()

        initial_count = (
            self.monitor.transition_count
        )

        self.monitor.poll_once()

        self.assertEqual(
            self.monitor.transition_count,
            initial_count,
        )

    def test_degradation_is_detected(self) -> None:

        self.monitor.poll_once()

        self.service.mark_degraded(
            "Simulated latency."
        )

        observation = self.monitor.poll_once()

        self.assertEqual(
            observation.kernel_state,
            KernelState.DEGRADED,
        )

        self.assertEqual(
            observation.kernel_status,
            HealthStatus.DEGRADED,
        )

        transition = (
            self.monitor.last_transition
        )

        self.assertIsNotNone(
            transition
        )

        self.assertEqual(
            transition.current_health_status,
            HealthStatus.DEGRADED,
        )

    def test_recovery_is_detected(self) -> None:

        self.monitor.poll_once()

        self.service.mark_degraded(
            "Temporary latency."
        )

        self.monitor.poll_once()

        self.service.recover()

        observation = self.monitor.poll_once()

        self.assertEqual(
            observation.kernel_state,
            KernelState.RUNNING,
        )

        self.assertEqual(
            observation.kernel_status,
            HealthStatus.HEALTHY,
        )

        transition = (
            self.monitor.last_transition
        )

        self.assertEqual(
            transition.current_health_status,
            HealthStatus.HEALTHY,
        )

    def test_background_monitor_runs(self) -> None:

        self.monitor.start()

        time.sleep(0.035)

        self.assertTrue(
            self.monitor.thread_alive
        )

        self.assertGreaterEqual(
            self.monitor.observation_count,
            2,
        )

    def test_background_monitor_stops(self) -> None:

        self.monitor.start()

        self.monitor.stop()

        self.assertFalse(
            self.monitor.thread_alive
        )

    def test_history_is_bounded(self) -> None:

        monitor = HealthMonitorService(
            self.kernel,
            interval_seconds=1.0,
            history_limit=3,
        )

        for _ in range(8):
            monitor.poll_once()

        self.assertEqual(
            monitor.observation_count,
            3,
        )

        observations = monitor.observations()

        self.assertEqual(
            len(observations),
            3,
        )

        self.assertEqual(
            observations[-1].sequence,
            8,
        )

    def test_clear_history_resets_monitor_data(
        self,
    ) -> None:

        self.monitor.poll_once()
        self.monitor.poll_once()

        self.monitor.clear_history()

        self.assertEqual(
            self.monitor.observation_count,
            0,
        )

        self.assertEqual(
            self.monitor.transition_count,
            0,
        )

        self.assertIsNone(
            self.monitor.last_observation
        )

        self.assertIsNone(
            self.monitor.last_transition
        )

    def test_monitor_snapshot_contains_data(
        self,
    ) -> None:

        self.monitor.poll_once()

        snapshot = (
            self.monitor.monitor_snapshot()
        )

        self.assertEqual(
            snapshot.monitor_name,
            "AtlasOSHealthMonitor",
        )

        self.assertEqual(
            snapshot.observation_count,
            1,
        )

        self.assertIsNotNone(
            snapshot.last_observation
        )

    def test_service_health_details_are_available(
        self,
    ) -> None:

        self.monitor.start()

        report = self.monitor.health()

        self.assertEqual(
            report.status,
            HealthStatus.HEALTHY,
        )

        self.assertTrue(
            report.details["thread_alive"]
        )

        self.assertGreaterEqual(
            report.details["observation_count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()