"""
Tests for AtlasOS AuditLogService.
"""

from __future__ import annotations

import json
import tempfile
import unittest

from pathlib import Path

from atlas_os import (
    AuditLogService,
    AuditQuery,
    EventBusService,
    EventSeverity,
    HealthStatus,
)


class AuditLogServiceTests(unittest.TestCase):

    def setUp(self) -> None:

        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )

        self.audit_file = (
            Path(
                self.temp_directory.name
            )
            / "atlas_audit.jsonl"
        )

        self.event_bus = EventBusService(
            history_limit=100
        )

        self.event_bus.start()

        self.audit = AuditLogService(
            self.event_bus,
            audit_file=self.audit_file,
            history_limit=5,
            rotation_size_bytes=1_000_000,
        )

        self.audit.start()

    def tearDown(self) -> None:

        if self.audit.is_running:
            self.audit.stop()

        if self.event_bus.is_running:
            self.event_bus.stop()

        self.temp_directory.cleanup()

    def test_audit_starts_subscribed(self) -> None:

        self.assertTrue(
            self.audit.subscribed
        )

        self.assertTrue(
            self.audit.audit_file.exists()
        )

    def test_event_is_recorded(self) -> None:

        self.event_bus.publish_event(
            event_type="KERNEL_STARTED",
            source="AtlasOS",
            payload={
                "service_count": 3,
            },
        )

        self.assertEqual(
            self.audit.record_count,
            1,
        )

        record = self.audit.last_record

        self.assertIsNotNone(
            record
        )

        self.assertEqual(
            record.event_type,
            "KERNEL_STARTED",
        )

        self.assertEqual(
            record.payload["service_count"],
            3,
        )

    def test_event_is_persisted_as_jsonl(self) -> None:

        self.event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="AtlasOS",
            payload={
                "service_name": "MarketFeed",
            },
        )

        lines = (
            self.audit_file
            .read_text(
                encoding="utf-8"
            )
            .splitlines()
        )

        self.assertEqual(
            len(lines),
            1,
        )

        data = json.loads(
            lines[0]
        )

        self.assertEqual(
            data["event_type"],
            "SERVICE_STARTED",
        )

        self.assertEqual(
            data["payload"]["service_name"],
            "MarketFeed",
        )

    def test_multiple_events_create_multiple_lines(
        self,
    ) -> None:

        for event_type in (
            "KERNEL_STARTING",
            "KERNEL_STARTED",
            "HEALTH_DEGRADED",
        ):

            self.event_bus.publish_event(
                event_type=event_type,
                source="AtlasOS",
            )

        lines = (
            self.audit_file
            .read_text(
                encoding="utf-8"
            )
            .splitlines()
        )

        self.assertEqual(
            len(lines),
            3,
        )

    def test_correlation_id_is_preserved(
        self,
    ) -> None:

        self.event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="AtlasOS",
            correlation_id="startup-001",
        )

        self.assertEqual(
            self.audit.last_record.correlation_id,
            "startup-001",
        )

    def test_query_by_event_type(self) -> None:

        self.event_bus.publish_event(
            event_type="SERVICE_STARTED",
            source="AtlasOS",
        )

        self.event_bus.publish_event(
            event_type="SERVICE_STOPPED",
            source="AtlasOS",
        )

        records = self.audit.query(
            AuditQuery(
                event_types=(
                    "SERVICE_STARTED",
                )
            )
        )

        self.assertEqual(
            len(records),
            1,
        )

        self.assertEqual(
            records[0].event_type,
            "SERVICE_STARTED",
        )

    def test_query_by_severity(self) -> None:

        self.event_bus.publish_event(
            event_type="KERNEL_STARTED",
            source="AtlasOS",
            severity=EventSeverity.INFO,
        )

        self.event_bus.publish_event(
            event_type="HEALTH_DEGRADED",
            source="HealthMonitor",
            severity=EventSeverity.WARNING,
        )

        records = self.audit.query(
            AuditQuery(
                severities=(
                    "WARNING",
                )
            )
        )

        self.assertEqual(
            len(records),
            1,
        )

        self.assertEqual(
            records[0].event_type,
            "HEALTH_DEGRADED",
        )

    def test_query_by_correlation_id(self) -> None:

        self.event_bus.publish_event(
            event_type="KERNEL_STARTING",
            source="AtlasOS",
            correlation_id="operation-001",
        )

        self.event_bus.publish_event(
            event_type="KERNEL_STARTED",
            source="AtlasOS",
            correlation_id="operation-001",
        )

        self.event_bus.publish_event(
            event_type="HEALTH_DEGRADED",
            source="HealthMonitor",
            correlation_id="health-001",
        )

        records = (
            self.audit.find_by_correlation_id(
                "operation-001"
            )
        )

        self.assertEqual(
            len(records),
            2,
        )

    def test_query_limit(self) -> None:

        for index in range(4):

            self.event_bus.publish_event(
                event_type="TEST_EVENT",
                source="UnitTest",
                payload={
                    "index": index,
                },
            )

        records = self.audit.query(
            AuditQuery(
                limit=2
            )
        )

        self.assertEqual(
            len(records),
            2,
        )

    def test_history_is_bounded(self) -> None:

        for index in range(9):

            self.event_bus.publish_event(
                event_type="TEST_EVENT",
                source="UnitTest",
                payload={
                    "index": index,
                },
            )

        self.assertEqual(
            self.audit.record_count,
            5,
        )

        self.assertEqual(
            self.audit.last_record.payload["index"],
            8,
        )

    def test_memory_clear_preserves_file(self) -> None:

        self.event_bus.publish_event(
            event_type="TEST_EVENT",
            source="UnitTest",
        )

        self.audit.clear_memory_history()

        self.assertEqual(
            self.audit.record_count,
            0,
        )

        self.assertGreater(
            self.audit_file.stat().st_size,
            0,
        )

    def test_existing_records_can_be_loaded(
        self,
    ) -> None:

        self.event_bus.publish_event(
            event_type="KERNEL_STARTED",
            source="AtlasOS",
        )

        self.audit.stop()

        second_audit = AuditLogService(
            self.event_bus,
            audit_file=self.audit_file,
            history_limit=5,
            load_existing_records=True,
        )

        second_audit.start()

        try:

            self.assertEqual(
                second_audit.record_count,
                1,
            )

            self.assertEqual(
                second_audit.last_record.event_type,
                "KERNEL_STARTED",
            )

        finally:

            second_audit.stop()

    def test_manual_rotation(self) -> None:

        self.event_bus.publish_event(
            event_type="TEST_EVENT",
            source="UnitTest",
        )

        rotated_path = self.audit.rotate()

        self.assertIsNotNone(
            rotated_path
        )

        self.assertTrue(
            rotated_path.exists()
        )

        self.assertTrue(
            self.audit_file.exists()
        )

        self.assertEqual(
            self.audit_file.stat().st_size,
            0,
        )

    def test_statistics_are_recorded(self) -> None:

        self.event_bus.publish_event(
            event_type="KERNEL_STARTED",
            source="AtlasOS",
        )

        statistics = (
            self.audit.statistics()
        )

        self.assertEqual(
            statistics.records_received,
            1,
        )

        self.assertEqual(
            statistics.records_persisted,
            1,
        )

        self.assertEqual(
            statistics.persistence_failures,
            0,
        )

    def test_snapshot_contains_runtime_data(
        self,
    ) -> None:

        self.event_bus.publish_event(
            event_type="KERNEL_STARTED",
            source="AtlasOS",
        )

        snapshot = (
            self.audit.audit_snapshot()
        )

        self.assertTrue(
            snapshot.running
        )

        self.assertTrue(
            snapshot.subscribed
        )

        self.assertEqual(
            snapshot.history_size,
            1,
        )

        self.assertEqual(
            snapshot.last_record.event_type,
            "KERNEL_STARTED",
        )

    def test_health_contains_audit_statistics(
        self,
    ) -> None:

        self.event_bus.publish_event(
            event_type="KERNEL_STARTED",
            source="AtlasOS",
        )

        report = self.audit.health()

        self.assertEqual(
            report.status,
            HealthStatus.HEALTHY,
        )

        self.assertEqual(
            report.details[
                "records_persisted"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()