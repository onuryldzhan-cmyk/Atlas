from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class FakeOrder:
    symbol: str = "BTCUSDT"
    side: str = "BUY"
    amount: float = 100.0


class SpyExchange:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def place_order(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "args": args,
                "kwargs": kwargs,
            }
        )

        return {
            "status": "FILLED",
        }


def test_execution_mode_defaults_to_paper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "ATLAS_EXECUTION_MODE",
        raising=False,
    )
    monkeypatch.delenv(
        "ATLAS_LIVE_ENABLED",
        raising=False,
    )

    from exchange.execution_safety_gate import (
        ExecutionSafetyGate,
    )

    gate = ExecutionSafetyGate.from_environment()

    assert gate.mode == "PAPER"
    assert gate.live_enabled is False
    assert gate.live_allowed is False


@pytest.mark.parametrize(
    ("mode", "live_enabled"),
    [
        ("PAPER", False),
        ("PAPER", True),
        ("LIVE", False),
    ],
)
def test_live_requires_double_authorization(
    mode: str,
    live_enabled: bool,
) -> None:
    from exchange.execution_safety_gate import (
        ExecutionSafetyGate,
    )

    gate = ExecutionSafetyGate(
        mode=mode,
        live_enabled=live_enabled,
    )

    decision = gate.authorize_live_order()

    assert decision["allowed"] is False
    assert decision["status"] == "REJECTED"


def test_live_allowed_only_when_both_gates_are_enabled() -> None:
    from exchange.execution_safety_gate import (
        ExecutionSafetyGate,
    )

    gate = ExecutionSafetyGate(
        mode="LIVE",
        live_enabled=True,
    )

    decision = gate.authorize_live_order()

    assert decision == {
        "allowed": True,
        "status": "AUTHORIZED",
        "reason": "LIVE_DOUBLE_GATE_PASSED",
    }


def test_kill_switch_blocks_live_order() -> None:
    from exchange.execution_safety_gate import (
        ExecutionSafetyGate,
    )

    gate = ExecutionSafetyGate(
        mode="LIVE",
        live_enabled=True,
        kill_switch=True,
    )

    decision = gate.authorize_live_order()

    assert decision["allowed"] is False
    assert decision["status"] == "REJECTED"
    assert decision["reason"] == "KILL_SWITCH_ACTIVE"


def test_invalid_mode_fails_closed() -> None:
    from exchange.execution_safety_gate import (
        ExecutionSafetyGate,
    )

    gate = ExecutionSafetyGate(
        mode="UNKNOWN",
        live_enabled=True,
    )

    assert gate.mode == "PAPER"
    assert gate.live_allowed is False


def test_missing_live_credentials_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "BINANCE_API_KEY",
        raising=False,
    )
    monkeypatch.delenv(
        "BINANCE_API_SECRET",
        raising=False,
    )

    from exchange.execution_safety_gate import (
        ExecutionSafetyGate,
    )

    gate = ExecutionSafetyGate(
        mode="LIVE",
        live_enabled=True,
        require_credentials=True,
    )

    decision = gate.authorize_live_order()

    assert decision["allowed"] is False
    assert decision["reason"] == "LIVE_CREDENTIALS_MISSING"
