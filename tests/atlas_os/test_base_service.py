"""
Tests for AtlasOS BaseAtlasService.
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
    ServiceLifecycleError,
)


class DummyService(BaseAtlasService):
    """
    Test service with observable lifecycle hooks.
    """

    def __init__(
        self,
        fail_start: bool = False,
        fail_stop: bool = False,
    ) -> None:

        super().__init__(
            ServiceIdentity(
                name="DummyService",
                version="1.0.0",
                service_type="TEST",
                description="AtlasOS test service.",
            )
        )

        self.fail_start = fail_start
        self.fail_stop = fail_stop

        self.start_count = 0
        self.stop_count = 0

    def _on_start(self) -> None:

        self.start_count += 1

        if self.fail_start:
            raise RuntimeError(
                "Simulated startup failure."
            )

    def _on_stop(self) -> None:

        self.stop_count += 1

        if self.fail_stop:
            raise RuntimeError(
                "Simulated shutdown failure."
            )

    def _health_details(self) -> dict[str, object]:

        return {
            "start_count": self.start_count,
            "stop_count": self.stop_count,
        }

    def _snapshot_metadata(self) -> dict[str, object]:

        return {
            "test_service": True,
        }


class BaseAtlasServiceTests(unittest.TestCase):

    def test_initial_state_is_created(self) -> None:

        service = DummyService()

        self.assertEqual(
            service.state,
            ServiceState.CREATED,
        )

        self.assertFalse(
            service.is_running
        )

    def test_start_moves_service_to_running(self) -> None:

        service = DummyService()

        service.start()

        self.assertEqual(
            service.state,
            ServiceState.RUNNING,
        )

        self.assertTrue(
            service.is_running
        )

        self.assertEqual(
            service.start_count,
            1,
        )

        self.assertIsNotNone(
            service.started_at
        )

    def test_start_is_idempotent(self) -> None:

        service = DummyService()

        service.start()
        service.start()

        self.assertEqual(
            service.start_count,
            1,
        )

    def test_stop_moves_service_to_stopped(self) -> None:

        service = DummyService()

        service.start()
        service.stop()

        self.assertEqual(
            service.state,
            ServiceState.STOPPED,
        )

        self.assertEqual(
            service.stop_count,
            1,
        )

        self.assertIsNotNone(
            service.stopped_at
        )

    def test_stop_is_idempotent(self) -> None:

        service = DummyService()

        service.start()
        service.stop()
        service.stop()

        self.assertEqual(
            service.stop_count,
            1,
        )

    def test_start_failure_moves_service_to_failed(self) -> None:

        service = DummyService(
            fail_start=True
        )

        with self.assertRaises(RuntimeError):
            service.start()

        self.assertEqual(
            service.state,
            ServiceState.FAILED,
        )

        self.assertIn(
            "Simulated startup failure",
            service.last_error or "",
        )

    def test_stop_failure_moves_service_to_failed(self) -> None:

        service = DummyService(
            fail_stop=True
        )

        service.start()

        with self.assertRaises(RuntimeError):
            service.stop()

        self.assertEqual(
            service.state,
            ServiceState.FAILED,
        )

    def test_running_health_is_healthy(self) -> None:

        service = DummyService()

        service.start()

        report = service.health()

        self.assertEqual(
            report.status,
            HealthStatus.HEALTHY,
        )

        self.assertTrue(
            report.is_operational
        )

    def test_degraded_service_can_recover(self) -> None:

        service = DummyService()

        service.start()

        service.mark_degraded(
            "Simulated dependency latency."
        )

        self.assertEqual(
            service.state,
            ServiceState.DEGRADED,
        )

        self.assertEqual(
            service.health().status,
            HealthStatus.DEGRADED,
        )

        service.recover()

        self.assertEqual(
            service.state,
            ServiceState.RUNNING,
        )

        self.assertIsNone(
            service.last_error
        )

    def test_degrade_requires_running_state(self) -> None:

        service = DummyService()

        with self.assertRaises(
            ServiceLifecycleError
        ):
            service.mark_degraded(
                "Invalid transition."
            )

    def test_snapshot_contains_service_information(self) -> None:

        service = DummyService()

        service.start()

        snapshot = service.snapshot()

        self.assertEqual(
            snapshot.identity.name,
            "DummyService",
        )

        self.assertEqual(
            snapshot.state,
            ServiceState.RUNNING,
        )

        self.assertTrue(
            snapshot.metadata["test_service"]
        )


if __name__ == "__main__":
    unittest.main()