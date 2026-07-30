"""
Tests for AtlasOS service contracts.
"""

from __future__ import annotations

import unittest

from atlas_os.contracts import (
    HealthReport,
    HealthStatus,
    ServiceIdentity,
    ServiceState,
)


class ServiceIdentityTests(unittest.TestCase):

    def test_valid_identity(self) -> None:
        identity = ServiceIdentity(
            name="MarketFeed",
            version="1.0.0",
            service_type="MARKET_DATA",
            description="Atlas market data service.",
        )

        self.assertEqual(
            identity.name,
            "MarketFeed",
        )

        self.assertEqual(
            identity.version,
            "1.0.0",
        )

    def test_empty_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ServiceIdentity(
                name="",
                version="1.0.0",
                service_type="MARKET_DATA",
            )

    def test_empty_version_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ServiceIdentity(
                name="MarketFeed",
                version="",
                service_type="MARKET_DATA",
            )

    def test_empty_service_type_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ServiceIdentity(
                name="MarketFeed",
                version="1.0.0",
                service_type="",
            )


class HealthReportTests(unittest.TestCase):

    def test_healthy_service_is_operational(self) -> None:
        report = HealthReport(
            service_name="MarketFeed",
            status=HealthStatus.HEALTHY,
            state=ServiceState.RUNNING,
        )

        self.assertTrue(
            report.is_operational
        )

    def test_degraded_service_is_operational(self) -> None:
        report = HealthReport(
            service_name="MarketFeed",
            status=HealthStatus.DEGRADED,
            state=ServiceState.DEGRADED,
        )

        self.assertTrue(
            report.is_operational
        )

    def test_unhealthy_service_is_not_operational(self) -> None:
        report = HealthReport(
            service_name="MarketFeed",
            status=HealthStatus.UNHEALTHY,
            state=ServiceState.FAILED,
        )

        self.assertFalse(
            report.is_operational
        )


if __name__ == "__main__":
    unittest.main()