from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from exchange.execution_risk_guard import ExecutionRiskGuard
from exchange.execution_safety_gate import ExecutionSafetyGate
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
        self.orders.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
            }
        )

        return {
            "status": "FILLED",
            "order_id": f"order-{len(self.orders)}",
        }


def _healthy_guard() -> ExecutionRiskGuard:
    return ExecutionRiskGuard(
        starting_equity=10_000.0,
        max_daily_loss_percent=5.0,
        max_drawdown_percent=10.0,
    )


def _build_manager(
    *,
    exchange: SpyExchange,
    store_path: Path,
) -> ExchangeManager:
    return ExchangeManager(
        exchange_name="test",
        exchange=exchange,
        safety_gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
        ),
        risk_guard=_healthy_guard(),
        idempotency_store_path=store_path,
    )


def test_terminal_result_survives_manager_restart(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "idempotency.json"

    first_exchange = SpyExchange()

    first_manager = _build_manager(
        exchange=first_exchange,
        store_path=store_path,
    )

    first_result = first_manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="restart-safe-001",
    )

    assert first_result["status"] == "FILLED"
    assert len(first_exchange.orders) == 1
    assert store_path.exists()

    second_exchange = SpyExchange()

    second_manager = _build_manager(
        exchange=second_exchange,
        store_path=store_path,
    )

    second_result = second_manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="restart-safe-001",
    )

    assert second_result == first_result
    assert second_exchange.orders == []


def test_persisted_key_conflict_is_rejected_after_restart(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "idempotency.json"

    first_manager = _build_manager(
        exchange=SpyExchange(),
        store_path=store_path,
    )

    first_manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="restart-conflict-001",
    )

    second_exchange = SpyExchange()

    second_manager = _build_manager(
        exchange=second_exchange,
        store_path=store_path,
    )

    result = second_manager.place_order(
        "ETHUSDT",
        "BUY",
        1.0,
        idempotency_key="restart-conflict-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert second_exchange.orders == []


def test_store_does_not_persist_adapter_error(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "idempotency.json"

    class FailingExchange:
        def place_order(
            self,
            symbol: str,
            side: str,
            quantity: float,
        ) -> dict[str, Any]:
            raise ConnectionError(
                "temporary outage"
            )

    manager = ExchangeManager(
        exchange_name="test",
        exchange=FailingExchange(),
        safety_gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
        ),
        risk_guard=_healthy_guard(),
        idempotency_store_path=store_path,
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="retry-after-error-001",
    )

    assert result["status"] == "ERROR"

    if store_path.exists():
        data = json.loads(
            store_path.read_text(
                encoding="utf-8",
            )
        )

        assert data.get(
            "entries",
            {},
        ) == {}


def test_corrupt_store_fails_closed(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "idempotency.json"

    store_path.write_text(
        "{not-valid-json",
        encoding="utf-8",
    )

    exchange = SpyExchange()

    manager = _build_manager(
        exchange=exchange,
        store_path=store_path,
    )

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="corrupt-store-001",
    )

    assert result["status"] == "REJECTED"
    assert result["reason"] == "IDEMPOTENCY_STORE_UNAVAILABLE"
    assert exchange.orders == []


def test_store_status_exposes_no_keys_or_payloads(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "idempotency.json"

    manager = _build_manager(
        exchange=SpyExchange(),
        store_path=store_path,
    )

    manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="secret-request-key",
    )

    status = manager.status()

    assert status["idempotency"]["persistent"] is True
    assert status["idempotency"]["store_available"] is True
    assert "secret-request-key" not in str(status)
    assert "entries" not in status["idempotency"]
