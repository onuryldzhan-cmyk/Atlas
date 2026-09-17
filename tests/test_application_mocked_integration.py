from __future__ import annotations

from pathlib import Path

from typing import Any

import pytest

from core.application import AtlasApplication


class FakeService:
    """
    Restartable lifecycle test double.
    """

    def __init__(
        self,
        name: str,
        events: list[str],
    ) -> None:
        self.name = name
        self.events = events
        self.running = False
        self.shutdown_completed = False

    def start(self) -> dict[str, Any]:
        self.events.append(
            f"start:{self.name}"
        )
        self.running = True
        self.shutdown_completed = False

        return {
            "success": True,
            "running": True,
            "service": self.name,
        }

    def stop(self) -> dict[str, Any]:
        self.events.append(
            f"stop:{self.name}"
        )
        self.running = False

        return {
            "success": True,
            "running": False,
            "service": self.name,
        }

    def shutdown(self) -> dict[str, Any]:
        self.events.append(
            f"shutdown:{self.name}"
        )
        self.running = False
        self.shutdown_completed = True

        return {
            "success": True,
            "running": False,
            "service": self.name,
        }

    def health(self) -> dict[str, Any]:
        return {
            "healthy": self.running,
            "state": (
                "HEALTHY"
                if self.running
                else "OFFLINE"
            ),
            "running": self.running,
            "service": self.name,
        }

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "service": self.name,
        }


class FakeRuntime(FakeService):
    """
    Atlas runtime state-transition test double.

    This object implements the runtime-specific protocol used by
    AtlasApplication without creating threads, network connections,
    exchange sessions, orders, or persistence.
    """

    def __init__(
        self,
        events: list[str],
    ) -> None:
        super().__init__(
            name="runtime",
            events=events,
        )

        self.state = "CREATED"
        self.connected = False
        self.last_failure: dict[str, Any] | None = None

    def boot(self) -> bool:
        self.events.append(
            "boot:runtime"
        )

        self.state = "BOOTING"
        self.running = False
        self.shutdown_completed = False

        return True

    def initialize(self) -> bool:
        self.events.append(
            "initialize:runtime"
        )

        self.state = "INITIALIZED"
        self.running = False

        return True

    def connect(self) -> bool:
        self.events.append(
            "connect:runtime"
        )

        self.state = "CONNECTED"
        self.connected = True
        self.running = False

        return True

    def ready(self) -> bool:
        self.events.append(
            "ready:runtime"
        )

        self.state = "READY"
        self.connected = True
        self.running = True

        return True

    def disconnect(self) -> bool:
        self.events.append(
            "disconnect:runtime"
        )

        self.connected = False

        if self.running:
            self.state = "STOPPING"
        else:
            self.state = "DISCONNECTED"

        return True

    def stop(self) -> dict[str, Any]:
        self.events.append(
            "stop:runtime"
        )

        self.state = "STOPPED"
        self.connected = False
        self.running = False

        return {
            "success": True,
            "status": "STOPPED",
            "running": False,
            "connected": False,
            "service": self.name,
        }

    def shutdown(self) -> dict[str, Any]:
        self.events.append(
            "shutdown:runtime"
        )

        self.state = "SHUTDOWN"
        self.connected = False
        self.running = False
        self.shutdown_completed = True

        return {
            "success": True,
            "status": "SHUTDOWN",
            "running": False,
            "connected": False,
            "service": self.name,
        }

    def fail(
        self,
        error: Any = None,
        **details: Any,
    ) -> bool:
        self.events.append(
            "fail:runtime"
        )

        self.state = "FAILED"
        self.connected = False
        self.running = False

        self.last_failure = {
            "error": error,
            **details,
        }

        return True

    def health(self) -> dict[str, Any]:
        return {
            "healthy": self.state == "READY",
            "state": self.state,
            "running": self.running,
            "connected": self.connected,
            "service": self.name,
        }

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "running": self.running,
            "connected": self.connected,
            "service": self.name,
            "last_failure": self.last_failure,
        }


class FakeBrain(FakeService):
    def __init__(
        self,
        events: list[str],
    ) -> None:
        super().__init__(
            name="brain",
            events=events,
        )
        self.observations: list[
            dict[str, Any]
        ] = []

    def process(
        self,
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        self.events.append(
            "process:brain"
        )

        if not self.running:
            return {
                "status": "OFFLINE",
                "reason": "BRAIN_NOT_RUNNING",
                "symbol": observation.get(
                    "symbol"
                ),
            }

        self.observations.append(
            observation
        )

        return {
            "status": "SUCCESS",
            "symbol": observation.get(
                "symbol"
            ),
            "decision": {
                "action": "HOLD",
                "source": "MOCKED_INTEGRATION",
            },
        }


def _assert_success(
    result: Any,
) -> None:
    """
    Accept the lifecycle result formats supported by AtlasApplication.
    """

    if result is None:
        return

    if isinstance(result, bool):
        assert result is True
        return

    assert isinstance(result, dict)

    assert result.get(
        "success",
        True,
    ) is not False

    assert result.get(
        "status",
        "SUCCESS",
    ) not in {
        "ERROR",
        "FAILED",
        "FAIL",
    }


def _replace_services(
    application: AtlasApplication,
    events: list[str],
) -> dict[str, FakeService]:
    """
    Replace application services without starting any real dependency.
    """

    replacements: dict[
        str,
        FakeService,
    ] = {}

    service_names = (
        "runtime",
        "market_feed",
        "execution",
        "execution_manager",
        "controller",
        "market_loop",
    )

    for name in service_names:
        if not hasattr(
            application,
            name,
        ):
            continue

        if name == "runtime":
            service = FakeRuntime(
                events=events,
            )
        else:
            service = FakeService(
                name=name,
                events=events,
            )

        setattr(
            application,
            name,
            service,
        )

        replacements[name] = service

    brain = FakeBrain(
        events=events,
    )

    application.brain = brain
    replacements["brain"] = brain

    application.started_services = []

    return replacements


@pytest.fixture
def deny_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Fail immediately if the integration test attempts external HTTP.
    """

    def blocked_request(
        *args: Any,
        **kwargs: Any,
    ) -> None:
        raise AssertionError(
            "External network access is forbidden "
            "in mocked integration tests."
        )

    monkeypatch.setattr(
        "requests.sessions.Session.request",
        blocked_request,
    )


def test_application_complete_mocked_lifecycle(
    deny_network: None,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    # Constructed against tmp_path, never the default root: a bare
    # AtlasApplication() binds to the real durable state directory and
    # would let a test read - or on any execution path write - the
    # operator's live financial state.
    application = AtlasApplication(state_directory=tmp_path)

    services = _replace_services(
        application,
        events,
    )

    # First start.
    first_start = application.start()
    _assert_success(first_start)

    assert application.started_services

    started_names = [
        name
        for name, service in services.items()
        if service.running
    ]

    assert "brain" in started_names

    # Process one harmless fake observation.
    result = application.brain.process(
        {
            "symbol": "BTCUSDT",
            "price": 65_000.0,
            "source": "MOCKED_TEST",
        }
    )

    assert result == {
        "status": "SUCCESS",
        "symbol": "BTCUSDT",
        "decision": {
            "action": "HOLD",
            "source": "MOCKED_INTEGRATION",
        },
    }

    assert application.brain.observations == [
        {
            "symbol": "BTCUSDT",
            "price": 65_000.0,
            "source": "MOCKED_TEST",
        }
    ]

    # Stop the full application.
    first_started_services = list(
        application.started_services
    )

    stop_result = application.stop()
    _assert_success(stop_result)

    assert all(
        service.running is False
        for service in services.values()
    )

    stop_events = [
        event
        for event in events
        if event.startswith("stop:")
    ]

    expected_stop_events = [
        "stop:runtime",
        *[
            f"stop:{name}"
            for name in reversed(
                first_started_services
            )
        ],
    ]

    assert stop_events == expected_stop_events

    # Restart the same application instance.
    restart_result = application.start()
    _assert_success(restart_result)

    assert all(
        service.running is True
        for service in services.values()
        if service.name in application.started_services
    )

    second_result = application.brain.process(
        {
            "symbol": "ETHUSDT",
            "price": 3_500.0,
            "source": "MOCKED_RESTART_TEST",
        }
    )

    assert second_result["status"] == "SUCCESS"
    assert second_result["symbol"] == "ETHUSDT"

    # Terminal shutdown.
    shutdown_result = application.shutdown()
    _assert_success(shutdown_result)

    assert all(
        service.running is False
        for service in services.values()
    )

    assert all(
        service.shutdown_completed
        for service in services.values()
        if (
            f"shutdown:{service.name}"
            in events
        )
    )


def test_application_brain_fails_closed_after_stop(
    deny_network: None,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    # Constructed against tmp_path, never the default root: a bare
    # AtlasApplication() binds to the real durable state directory and
    # would let a test read - or on any execution path write - the
    # operator's live financial state.
    application = AtlasApplication(state_directory=tmp_path)

    _replace_services(
        application,
        events,
    )

    _assert_success(
        application.start()
    )

    _assert_success(
        application.stop()
    )

    result = application.brain.process(
        {
            "symbol": "SOLUSDT",
            "price": 175.0,
        }
    )

    assert result == {
        "status": "OFFLINE",
        "reason": "BRAIN_NOT_RUNNING",
        "symbol": "SOLUSDT",
    }
