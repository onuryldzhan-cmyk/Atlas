"""
============================================================
ATLAS PHASE 6A6.2 — APPLICATION LIFECYCLE INTEGRATION TEST
============================================================

Validates AtlasApplication lifecycle without constructing production
dependencies or opening network connections.

Coverage
--------
- Dependency-safe startup order
- Reverse shutdown order
- running / started_services state
- Startup failure recording
- runtime.fail transition
- Partial-start rollback

Safety
------
- Offline
- AtlasApplication.__init__ is bypassed
- No Binance connection
- No trading execution
- No production source modification
============================================================
"""

from __future__ import annotations

import unittest
from typing import Any

from core.application import AtlasApplication


class CallRecorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def add(self, name: str) -> None:
        self.calls.append(name)


class FakeRuntime:
    def __init__(self, recorder: CallRecorder) -> None:
        self.recorder = recorder
        self.failed_message: str | None = None

    def boot(self) -> None:
        self.recorder.add("runtime.boot")

    def initialize(self) -> None:
        self.recorder.add("runtime.initialize")

    def connect(self) -> None:
        self.recorder.add("runtime.connect")

    def ready(self) -> None:
        self.recorder.add("runtime.ready")

    def start(self) -> None:
        self.recorder.add("runtime.start")

    def stop(self) -> None:
        self.recorder.add("runtime.stop")

    def shutdown(self) -> None:
        self.recorder.add("runtime.shutdown")

    def fail(self, message: str) -> None:
        self.failed_message = message
        self.recorder.add("runtime.fail")


class FakeService:
    def __init__(
        self,
        name: str,
        recorder: CallRecorder,
        *,
        fail_on_start: bool = False,
        fail_on_stop: bool = False,
    ) -> None:
        self.name = name
        self.recorder = recorder
        self.fail_on_start = fail_on_start
        self.fail_on_stop = fail_on_stop

    def start(self) -> None:
        self.recorder.add(f"{self.name}.start")
        if self.fail_on_start:
            raise RuntimeError(f"{self.name} startup failure")

    def stop(self) -> None:
        self.recorder.add(f"{self.name}.stop")
        if self.fail_on_stop:
            raise RuntimeError(f"{self.name} shutdown failure")


class FakeLifecycle:
    def __init__(self, recorder: CallRecorder) -> None:
        self.recorder = recorder

    def stop_all(self) -> None:
        self.recorder.add("lifecycle.stop_all")


def build_application(
    *,
    failing_service: str | None = None,
) -> tuple[AtlasApplication, CallRecorder]:
    recorder = CallRecorder()

    app = AtlasApplication.__new__(AtlasApplication)

    app.running = False
    app.initialized = True
    app.started_at = None
    app.stopped_at = None
    app.errors = []
    app.started_services = []

    app.runtime = FakeRuntime(recorder)
    app.lifecycle = FakeLifecycle(recorder)

    app.execution = FakeService(
        "execution",
        recorder,
        fail_on_start=failing_service == "execution",
    )
    app.market_feed = FakeService(
        "market_feed",
        recorder,
        fail_on_start=failing_service == "market_feed",
    )
    app.brain = FakeService(
        "brain",
        recorder,
        fail_on_start=failing_service == "brain",
    )
    app.market_loop = FakeService(
        "market_loop",
        recorder,
        fail_on_start=failing_service == "market_loop",
    )
    app.controller = FakeService(
        "controller",
        recorder,
        fail_on_start=failing_service == "controller",
    )
    app.scheduler = FakeService("scheduler", recorder)

    return app, recorder


class AtlasApplicationLifecycleTests(unittest.TestCase):

    def test_startup_order_matches_runtime_contract(self) -> None:
        app, recorder = build_application()

        result = app.start()

        self.assertTrue(result)
        self.assertTrue(app.running)
        self.assertEqual(
            app.started_services,
            [
                "execution",
                "market_feed",
                "brain",
                "market_loop",
                "controller",
            ],
        )
        self.assertEqual(
            recorder.calls,
            [
                "runtime.boot",
                "runtime.initialize",
                "execution.start",
                "runtime.connect",
                "market_feed.start",
                "brain.start",
                "runtime.ready",
                "market_loop.start",
                "controller.start",
                "runtime.start",
            ],
        )

    def test_shutdown_order_is_reverse_dependency_safe(self) -> None:
        app, recorder = build_application()
        self.assertTrue(app.start())

        recorder.calls.clear()
        result = app.stop()

        self.assertTrue(result)
        self.assertFalse(app.running)
        self.assertEqual(app.started_services, [])
        self.assertEqual(
            recorder.calls,
            [
                "runtime.stop",
                "controller.stop",
                "market_loop.stop",
                "execution.stop",
                "market_feed.stop",
                "scheduler.stop",
                "lifecycle.stop_all",
                "runtime.shutdown",
            ],
        )

    def test_duplicate_start_is_idempotent(self) -> None:
        app, recorder = build_application()

        self.assertTrue(app.start())
        first_calls = list(recorder.calls)

        self.assertTrue(app.start())
        self.assertEqual(recorder.calls, first_calls)

    def test_market_feed_failure_triggers_runtime_fail_and_rollback(self) -> None:
        app, recorder = build_application(
            failing_service="market_feed",
        )

        result = app.start()

        self.assertFalse(result)
        self.assertFalse(app.running)
        self.assertEqual(app.started_services, [])
        self.assertEqual(len(app.errors), 1)
        self.assertEqual(app.errors[0]["phase"], "startup")
        self.assertEqual(app.errors[0]["type"], "RuntimeError")
        self.assertIn(
            "market_feed startup failure",
            app.errors[0]["error"],
        )
        self.assertEqual(
            app.runtime.failed_message,
            "market_feed startup failure",
        )

        self.assertEqual(
            recorder.calls,
            [
                "runtime.boot",
                "runtime.initialize",
                "execution.start",
                "runtime.connect",
                "market_feed.start",
                "runtime.fail",
                "runtime.stop",
                "controller.stop",
                "market_loop.stop",
                "execution.stop",
                "market_feed.stop",
                "scheduler.stop",
                "lifecycle.stop_all",
                "runtime.shutdown",
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
