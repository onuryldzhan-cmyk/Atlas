from __future__ import annotations

from typing import Any

from core.application import AtlasApplication


class FakeRuntime:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def boot(self) -> None:
        self.events.append("runtime.boot")

    def initialize(self) -> None:
        self.events.append("runtime.initialize")

    def connect(self) -> None:
        self.events.append("runtime.connect")

    def ready(self) -> None:
        self.events.append("runtime.ready")

    def start(self) -> None:
        self.events.append("runtime.start")

    def stop(self) -> None:
        self.events.append("runtime.stop")

    def shutdown(self) -> None:
        self.events.append("runtime.shutdown")

    def fail(self, reason: str) -> None:
        self.events.append("runtime.fail")


class FakeLifecycle:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def stop_all(self) -> None:
        self.events.append("lifecycle.stop_all")


class FakeService:
    def __init__(
        self,
        name: str,
        events: list[str],
        start_result: Any = True,
        *,
        raise_on_start: Exception | None = None,
    ) -> None:
        self.name = name
        self.events = events
        self.start_result = start_result
        self.raise_on_start = raise_on_start
        self.running = False

    def start(self) -> Any:
        self.events.append(f"{self.name}.start")

        if self.raise_on_start is not None:
            raise self.raise_on_start

        if self.start_result is not False:
            self.running = True

        return self.start_result

    def stop(self) -> None:
        self.events.append(f"{self.name}.stop")
        self.running = False


class FakeController(FakeService):
    pass


def build_application(
    *,
    brain_result: Any = True,
    market_feed_result: Any = None,
    market_loop_result: Any = True,
    controller_result: Any = {
        "status": "STARTED",
        "running": True,
    },
) -> tuple[AtlasApplication, list[str]]:
    events: list[str] = []

    app = AtlasApplication.__new__(
        AtlasApplication
    )

    app.NAME = "AtlasApplication"
    app.VERSION = "test"

    app.running = False
    app.initialized = True
    app.started_services = []
    app.errors = []

    app.started_at = None
    app.stopped_at = None

    app.runtime = FakeRuntime(events)
    app.lifecycle = FakeLifecycle(events)

    app.execution = FakeService(
        "execution",
        events,
        True,
    )

    app.market_feed = FakeService(
        "market_feed",
        events,
        market_feed_result,
    )

    app.brain = FakeService(
        "brain",
        events,
        brain_result,
    )

    app.market_loop = FakeService(
        "market_loop",
        events,
        market_loop_result,
    )

    app.controller = FakeController(
        "controller",
        events,
        controller_result,
    )

    app.scheduler = FakeService(
        "scheduler",
        events,
        True,
    )

    return app, events


def test_application_start_order_without_network_or_thread() -> None:
    app, events = build_application()

    result = app.start()

    assert result is True
    assert app.running is True

    assert app.started_services == [
        "execution",
        "market_feed",
        "brain",
        "market_loop",
        "controller",
    ]

    assert events == [
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
    ]


def test_false_start_result_causes_startup_failure() -> None:
    app, events = build_application(
        brain_result=False,
    )

    result = app.start()

    assert result is False
    assert app.running is False
    assert "brain" not in app.started_services

    assert "brain.start" in events
    assert "brain.stop" in events
    assert "market_feed.stop" in events
    assert "execution.stop" in events


def test_error_dict_causes_startup_failure() -> None:
    app, events = build_application(
        controller_result={
            "status": "ERROR",
            "running": False,
        },
    )

    result = app.start()

    assert result is False
    assert app.running is False

    assert "controller.start" in events
    assert "controller.stop" in events


def test_success_false_causes_startup_failure() -> None:
    app, _ = build_application(
        controller_result={
            "status": "STARTED",
            "success": False,
            "running": True,
        },
    )

    assert app.start() is False
    assert app.running is False


def test_running_false_causes_startup_failure() -> None:
    app, _ = build_application(
        controller_result={
            "status": "STARTED",
            "running": False,
        },
    )

    assert app.start() is False
    assert app.running is False


def test_stop_uses_reverse_started_service_order() -> None:
    app, events = build_application()

    assert app.start() is True

    events.clear()

    assert app.stop() is True

    assert events == [
        "runtime.stop",
        "controller.stop",
        "market_loop.stop",
        "brain.stop",
        "market_feed.stop",
        "execution.stop",
        "lifecycle.stop_all",
        "runtime.shutdown",
    ]

    assert app.running is False
    assert app.started_services == []


def test_missing_required_start_method_fails() -> None:
    app, _ = build_application()

    app.brain = object()

    assert app.start() is False
    assert app.running is False


def test_optional_missing_service_is_skipped() -> None:
    app, _ = build_application()

    result = app._start_service(
        name="optional_service",
        service=None,
        required=False,
    )

    assert result is False
    assert "optional_service" not in app.started_services
