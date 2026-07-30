"""
Tests for AtlasOS DependencyServiceManager.
"""

from __future__ import annotations

import unittest

from atlas_os.contracts import (
    ServiceIdentity,
    ServiceState,
)
from atlas_os.services import (
    BaseAtlasService,
    CircularDependencyError,
    DependencyServiceManager,
    InvalidDependencyError,
    MissingDependencyError,
    OrchestrationAction,
)


class DependencyTestService(BaseAtlasService):
    """
    Controllable service used for dependency tests.
    """

    events: list[str] = []

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
                description="Dependency manager test service.",
            )
        )

        self.fail_start = fail_start
        self.fail_stop = fail_stop

        self.start_count = 0
        self.stop_count = 0

    def _on_start(self) -> None:

        self.start_count += 1

        self.events.append(
            f"START:{self.identity.name}"
        )

        if self.fail_start:
            raise RuntimeError(
                f"{self.identity.name} startup failed."
            )

    def _on_stop(self) -> None:

        self.stop_count += 1

        self.events.append(
            f"STOP:{self.identity.name}"
        )

        if self.fail_stop:
            raise RuntimeError(
                f"{self.identity.name} shutdown failed."
            )


class DependencyServiceManagerTests(unittest.TestCase):

    def setUp(self) -> None:

        DependencyTestService.events.clear()

        self.manager = DependencyServiceManager()

    def test_register_service_without_dependencies(self) -> None:

        service = DependencyTestService(
            "MarketFeed"
        )

        self.manager.register(
            service
        )

        self.assertEqual(
            len(self.manager),
            1,
        )

        self.assertIn(
            "MarketFeed",
            self.manager,
        )

    def test_direct_dependencies_are_returned(self) -> None:

        self.manager.register(
            DependencyTestService(
                "MarketFeed"
            )
        )

        self.manager.register(
            DependencyTestService(
                "RiskService"
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        self.assertEqual(
            self.manager.dependencies_of(
                "RiskService"
            ),
            ("MarketFeed",),
        )

    def test_recursive_dependencies_are_returned(self) -> None:

        self.manager.register(
            DependencyTestService(
                "MarketFeed"
            )
        )

        self.manager.register(
            DependencyTestService(
                "RiskService"
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        self.manager.register(
            DependencyTestService(
                "ExecutionService"
            ),
            dependencies=(
                "RiskService",
            ),
        )

        self.assertEqual(
            self.manager.dependencies_of(
                "ExecutionService",
                recursive=True,
            ),
            (
                "MarketFeed",
                "RiskService",
            ),
        )

    def test_self_dependency_is_rejected(self) -> None:

        with self.assertRaises(
            InvalidDependencyError
        ):
            self.manager.register(
                DependencyTestService(
                    "MarketFeed"
                ),
                dependencies=(
                    "MarketFeed",
                ),
            )

    def test_duplicate_dependencies_are_removed(self) -> None:

        self.manager.register(
            DependencyTestService(
                "MarketFeed"
            )
        )

        self.manager.register(
            DependencyTestService(
                "RiskService"
            ),
            dependencies=(
                "MarketFeed",
                "marketfeed",
                "MARKETFEED",
            ),
        )

        self.assertEqual(
            self.manager.dependencies_of(
                "RiskService"
            ),
            ("MarketFeed",),
        )

    def test_missing_dependency_is_detected(self) -> None:

        self.manager.register(
            DependencyTestService(
                "ExecutionService"
            ),
            dependencies=(
                "RiskService",
            ),
        )

        with self.assertRaises(
            MissingDependencyError
        ):
            self.manager.validate()

    def test_cycle_is_detected(self) -> None:

        self.manager.register(
            DependencyTestService("A"),
            dependencies=("B",),
        )

        self.manager.register(
            DependencyTestService("B"),
            dependencies=("C",),
        )

        self.manager.register(
            DependencyTestService("C"),
            dependencies=("A",),
        )

        with self.assertRaises(
            CircularDependencyError
        ):
            self.manager.validate()

    def test_plan_calculates_dependency_order(self) -> None:

        self.manager.register(
            DependencyTestService(
                "MarketFeed"
            )
        )

        self.manager.register(
            DependencyTestService(
                "RiskService"
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        self.manager.register(
            DependencyTestService(
                "PortfolioService"
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        self.manager.register(
            DependencyTestService(
                "ExecutionService"
            ),
            dependencies=(
                "RiskService",
                "PortfolioService",
            ),
        )

        plan = self.manager.plan_for(
            "ExecutionService"
        )

        self.assertEqual(
            plan.startup_order,
            (
                "MarketFeed",
                "RiskService",
                "PortfolioService",
                "ExecutionService",
            ),
        )

        self.assertEqual(
            plan.shutdown_order,
            (
                "ExecutionService",
                "PortfolioService",
                "RiskService",
                "MarketFeed",
            ),
        )

    def test_start_starts_dependencies_first(self) -> None:

        market = DependencyTestService(
            "MarketFeed"
        )

        risk = DependencyTestService(
            "RiskService"
        )

        execution = DependencyTestService(
            "ExecutionService"
        )

        self.manager.register(
            market
        )

        self.manager.register(
            risk,
            dependencies=(
                "MarketFeed",
            ),
        )

        self.manager.register(
            execution,
            dependencies=(
                "RiskService",
            ),
        )

        result = self.manager.start(
            "ExecutionService"
        )

        self.assertTrue(
            result.success
        )

        self.assertEqual(
            DependencyTestService.events,
            [
                "START:MarketFeed",
                "START:RiskService",
                "START:ExecutionService",
            ],
        )

        self.assertEqual(
            execution.state,
            ServiceState.RUNNING,
        )

    def test_dependency_failure_blocks_dependant(self) -> None:

        market = DependencyTestService(
            "MarketFeed",
            fail_start=True,
        )

        risk = DependencyTestService(
            "RiskService"
        )

        self.manager.register(
            market
        )

        self.manager.register(
            risk,
            dependencies=(
                "MarketFeed",
            ),
        )

        result = self.manager.start(
            "RiskService",
            rollback_on_failure=False,
        )

        self.assertFalse(
            result.success
        )

        self.assertEqual(
            market.state,
            ServiceState.FAILED,
        )

        self.assertEqual(
            risk.state,
            ServiceState.CREATED,
        )

        self.assertEqual(
            result.skipped_services,
            ("RiskService",),
        )

        self.assertEqual(
            result.steps[-1].action,
            OrchestrationAction.SKIP,
        )

    def test_rollback_stops_started_dependencies(self) -> None:

        market = DependencyTestService(
            "MarketFeed"
        )

        risk = DependencyTestService(
            "RiskService"
        )

        execution = DependencyTestService(
            "ExecutionService",
            fail_start=True,
        )

        self.manager.register(
            market
        )

        self.manager.register(
            risk,
            dependencies=(
                "MarketFeed",
            ),
        )

        self.manager.register(
            execution,
            dependencies=(
                "RiskService",
            ),
        )

        result = self.manager.start(
            "ExecutionService",
            rollback_on_failure=True,
        )

        self.assertFalse(
            result.success
        )

        self.assertEqual(
            market.state,
            ServiceState.STOPPED,
        )

        self.assertEqual(
            risk.state,
            ServiceState.STOPPED,
        )

        self.assertEqual(
            execution.state,
            ServiceState.FAILED,
        )

        self.assertEqual(
            result.rolled_back_services,
            (
                "RiskService",
                "MarketFeed",
            ),
        )

    def test_existing_running_dependency_is_not_rolled_back(self) -> None:

        market = DependencyTestService(
            "MarketFeed"
        )

        execution = DependencyTestService(
            "ExecutionService",
            fail_start=True,
        )

        self.manager.register(
            market
        )

        self.manager.register(
            execution,
            dependencies=(
                "MarketFeed",
            ),
        )

        market.start()

        result = self.manager.start(
            "ExecutionService",
            rollback_on_failure=True,
        )

        self.assertFalse(
            result.success
        )

        self.assertEqual(
            market.state,
            ServiceState.RUNNING,
        )

        self.assertNotIn(
            "MarketFeed",
            result.rolled_back_services,
        )

    def test_stop_all_stops_dependants_first(self) -> None:

        self.manager.register(
            DependencyTestService(
                "MarketFeed"
            )
        )

        self.manager.register(
            DependencyTestService(
                "RiskService"
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        self.manager.register(
            DependencyTestService(
                "ExecutionService"
            ),
            dependencies=(
                "RiskService",
            ),
        )

        self.manager.start_all()

        DependencyTestService.events.clear()

        result = self.manager.stop_all()

        self.assertTrue(
            result.success
        )

        self.assertEqual(
            DependencyTestService.events,
            [
                "STOP:ExecutionService",
                "STOP:RiskService",
                "STOP:MarketFeed",
            ],
        )

    def test_stop_dependency_stops_dependants_first(self) -> None:

        market = DependencyTestService(
            "MarketFeed"
        )

        risk = DependencyTestService(
            "RiskService"
        )

        execution = DependencyTestService(
            "ExecutionService"
        )

        self.manager.register(
            market
        )

        self.manager.register(
            risk,
            dependencies=(
                "MarketFeed",
            ),
        )

        self.manager.register(
            execution,
            dependencies=(
                "RiskService",
            ),
        )

        self.manager.start_all()

        DependencyTestService.events.clear()

        result = self.manager.stop(
            "MarketFeed",
            include_dependants=True,
        )

        self.assertTrue(
            result.success
        )

        self.assertEqual(
            DependencyTestService.events,
            [
                "STOP:ExecutionService",
                "STOP:RiskService",
                "STOP:MarketFeed",
            ],
        )

    def test_dependants_are_reported(self) -> None:

        self.manager.register(
            DependencyTestService(
                "MarketFeed"
            )
        )

        self.manager.register(
            DependencyTestService(
                "RiskService"
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        self.manager.register(
            DependencyTestService(
                "ExecutionService"
            ),
            dependencies=(
                "RiskService",
            ),
        )

        self.assertEqual(
            self.manager.dependants_of(
                "MarketFeed",
                recursive=True,
            ),
            (
                "RiskService",
                "ExecutionService",
            ),
        )

    def test_declarations_are_available(self) -> None:

        self.manager.register(
            DependencyTestService(
                "MarketFeed"
            )
        )

        self.manager.register(
            DependencyTestService(
                "RiskService"
            ),
            dependencies=(
                "MarketFeed",
            ),
        )

        declarations = (
            self.manager.declarations()
        )

        self.assertEqual(
            len(declarations),
            2,
        )

        self.assertEqual(
            declarations[1].service_name,
            "RiskService",
        )

        self.assertEqual(
            declarations[1].dependencies,
            ("MarketFeed",),
        )


if __name__ == "__main__":
    unittest.main()