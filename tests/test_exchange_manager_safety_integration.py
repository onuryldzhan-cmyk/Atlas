from __future__ import annotations

from typing import Any

import pytest

from exchange.execution_safety_gate import (
    ExecutionSafetyGate,
)
from exchange.exchange_manager import ExchangeManager


class SpyExchange:
    def __init__(self) -> None:
        self.orders: list[dict[str, Any]] = []

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        order = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
        }

        self.orders.append(order)

        return {
            "status": "FILLED",
            "order": order,
        }


def _build_manager(
    *,
    gate: ExecutionSafetyGate,
) -> tuple[ExchangeManager, SpyExchange]:
    exchange = SpyExchange()

    manager = ExchangeManager(
        exchange_name="test",
        exchange=exchange,
        safety_gate=gate,
    )

    return manager, exchange


def test_paper_mode_never_calls_live_exchange() -> None:
    manager, exchange = _build_manager(
        gate=ExecutionSafetyGate(
            mode="PAPER",
            live_enabled=False,
        )
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
    )

    assert result == {
        "status": "REJECTED",
        "allowed": False,
        "reason": "EXECUTION_MODE_NOT_LIVE",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 0.01,
    }

    assert exchange.orders == []


def test_live_without_explicit_enable_never_calls_exchange() -> None:
    manager, exchange = _build_manager(
        gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=False,
        )
    )

    result = manager.place_order(
        "ETHUSDT",
        "SELL",
        0.25,
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "LIVE_NOT_EXPLICITLY_ENABLED"
    assert exchange.orders == []


def test_kill_switch_never_calls_exchange() -> None:
    manager, exchange = _build_manager(
        gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
            kill_switch=True,
        )
    )

    result = manager.place_order(
        "SOLUSDT",
        "BUY",
        1.0,
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "KILL_SWITCH_ACTIVE"
    assert exchange.orders == []


def test_missing_required_credentials_never_calls_exchange(
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

    manager, exchange = _build_manager(
        gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
            require_credentials=True,
        )
    )

    result = manager.place_order(
        "BNBUSDT",
        "BUY",
        0.5,
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "LIVE_CREDENTIALS_MISSING"
    assert exchange.orders == []


def test_authorized_live_order_calls_exchange_exactly_once() -> None:
    manager, exchange = _build_manager(
        gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
        )
    )

    result = manager.place_order(
        "XRPUSDT",
        "BUY",
        25.0,
    )

    assert result == {
        "status": "FILLED",
        "order": {
            "symbol": "XRPUSDT",
            "side": "BUY",
            "quantity": 25.0,
        },
    }

    assert exchange.orders == [
        {
            "symbol": "XRPUSDT",
            "side": "BUY",
            "quantity": 25.0,
        }
    ]


def test_manager_defaults_to_fail_closed_environment_gate(
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

    exchange = SpyExchange()

    manager = ExchangeManager(
        exchange_name="test",
        exchange=exchange,
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "EXECUTION_MODE_NOT_LIVE"
    assert exchange.orders == []
