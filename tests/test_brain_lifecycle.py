from __future__ import annotations

from typing import Any

from core.application import AtlasApplication
from core.brain import AtlasBrain


class FakeIntelligence:
    def __init__(self) -> None:
        self.shutdown_called = False

    def analyze_and_decide(
        self,
        symbol: str,
        observation: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "action": "HOLD",
            "confidence": 0.0,
            "source": "fake_intelligence",
        }

    def shutdown(self) -> None:
        self.shutdown_called = True


def install_fake_intelligence(brain: AtlasBrain) -> FakeIntelligence:
    intelligence = FakeIntelligence()

    def fake_loader() -> bool:
        brain.intelligence = intelligence
        return True

    brain.load_intelligence = fake_loader  # type: ignore[method-assign]

    return intelligence


def test_constructor_is_offline_and_lazy() -> None:
    brain = AtlasBrain()

    assert brain.initialized is True
    assert brain.running is False
    assert brain.intelligence is None

    status = brain.status()

    assert status["running"] is False
    assert status["intelligence_loaded"] is False

    health = brain.health()

    assert health["healthy"] is False
    assert health["state"] == "OFFLINE"


def test_process_fails_closed_before_start() -> None:
    brain = AtlasBrain()

    result = brain.process(
        {
            "symbol": "BTCUSDT",
            "price": 65_000.0,
        }
    )

    assert result["status"] == "OFFLINE"
    assert result["reason"] == "BRAIN_NOT_RUNNING"
    assert result["decision"] is None
    assert brain.state.total_cycles == 0
    assert brain.state.total_rejections == 1


def test_start_and_stop_are_idempotent() -> None:
    brain = AtlasBrain()
    intelligence = install_fake_intelligence(brain)

    assert brain.start() is True
    assert brain.running is True
    assert brain.intelligence is intelligence

    first_started_at = brain.state.started_at

    assert brain.start() is True
    assert brain.running is True
    assert brain.state.started_at == first_started_at

    assert brain.stop() is True
    assert brain.running is False
    assert brain.state.stopped_at is not None

    first_stopped_at = brain.state.stopped_at

    assert brain.stop() is True
    assert brain.running is False
    assert brain.state.stopped_at == first_stopped_at


def test_running_brain_processes_observation() -> None:
    brain = AtlasBrain()
    install_fake_intelligence(brain)

    assert brain.start() is True

    result = brain.process(
        {
            "symbol": "BTCUSDT",
            "price": 65_000.0,
        }
    )

    assert result["status"] == "SUCCESS"
    assert result["symbol"] == "BTCUSDT"
    assert result["analysis"]["status"] == "SUCCESS"
    assert brain.state.total_cycles == 1
    assert brain.state.total_errors == 0


def test_shutdown_releases_intelligence() -> None:
    brain = AtlasBrain()
    intelligence = install_fake_intelligence(brain)

    assert brain.start() is True
    assert brain.shutdown() is True

    assert brain.running is False
    assert brain.intelligence is None
    assert intelligence.shutdown_called is True


def test_application_constructor_does_not_start_brain() -> None:
    app = AtlasApplication(
        execution_mode="PAPER",
        symbols=[
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
        ],
    )

    status = app.status()

    assert status["application"]["running"] is False
    assert status["application"]["execution_mode"] == "PAPER"

    assert status["brain"]["running"] is False
    assert status["brain"]["intelligence_loaded"] is False

    assert status["execution"]["live_execution_enabled"] is False
