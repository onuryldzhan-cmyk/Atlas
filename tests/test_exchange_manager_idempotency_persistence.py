from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from exchange.execution_exposure_guard import (
    ExecutionExposureGuard,
)
from exchange.execution_risk_guard import ExecutionRiskGuard
from exchange.execution_safety_gate import ExecutionSafetyGate
from exchange.exchange_manager import ExchangeManager



def _healthy_exposure_guard() -> ExecutionExposureGuard:
    guard = ExecutionExposureGuard(
        portfolio_equity=10_000.0,
        max_order_notional=2_000.0,
        max_symbol_exposure=3_000.0,
        max_total_exposure=7_000.0,
        max_open_positions=5,
        minimum_cash_reserve=2_000.0,
    )

    result = guard.update_portfolio(
        cash=10_000.0,
        total_exposure=0.0,
        symbol_exposures={},
        open_positions=0,
    )

    if result.get("accepted") is not True:
        raise RuntimeError(
            "Healthy exposure fixture was rejected"
        )

    return guard


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

        exposure_guard=_healthy_exposure_guard(),)


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

        order_notional=500.0,
        opens_new_position=False,)

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

        order_notional=500.0,
        opens_new_position=False,)

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

        order_notional=500.0,
        opens_new_position=False,)

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

        order_notional=500.0,
        opens_new_position=False,)

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

        exposure_guard=_healthy_exposure_guard(),)

    result = manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="retry-after-error-001",

        order_notional=500.0,
        opens_new_position=False,)

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

        order_notional=500.0,
        opens_new_position=False,)

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

        order_notional=500.0,
        opens_new_position=False,)

    status = manager.status()

    assert status["idempotency"]["persistent"] is True
    assert status["idempotency"]["store_available"] is True
    assert "secret-request-key" not in str(status)
    assert "entries" not in status["idempotency"]

def test_persisted_key_rejects_different_order_notional_after_restart(
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
        idempotency_key="restart-notional-conflict-001",
        order_notional=500.0,
        opens_new_position=False,
    )

    assert first_result["status"] == "FILLED"
    assert len(first_exchange.orders) == 1

    second_exchange = SpyExchange()
    second_manager = _build_manager(
        exchange=second_exchange,
        store_path=store_path,
    )

    second_result = second_manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="restart-notional-conflict-001",
        order_notional=750.0,
        opens_new_position=False,
    )

    assert second_result["status"] == "REJECTED"
    assert second_result["reason"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert second_exchange.orders == []


def test_persisted_key_rejects_different_position_opening_intent_after_restart(
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
        idempotency_key="restart-position-conflict-001",
        order_notional=500.0,
        opens_new_position=False,
    )

    assert first_result["status"] == "FILLED"
    assert len(first_exchange.orders) == 1

    second_exchange = SpyExchange()
    second_manager = _build_manager(
        exchange=second_exchange,
        store_path=store_path,
    )

    second_result = second_manager.place_order(
        "BTCUSDT",
        "BUY",
        0.01,
        idempotency_key="restart-position-conflict-001",
        order_notional=500.0,
        opens_new_position=True,
    )

    assert second_result["status"] == "REJECTED"
    assert second_result["reason"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert second_exchange.orders == []

def test_legacy_three_field_fingerprint_store_fails_closed(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "legacy-idempotency.json"

    store_path.write_text(
        (
            '{"version":"1.0","entries":{'
            '"legacy-key-001":{'
            '"fingerprint":["BTCUSDT","BUY",0.01],'
            '"response":{'
            '"status":"FILLED",'
            '"order_id":"legacy-order"'
            '},'
            '"expires_at":4102444800.0'
            '}'
            '}}'
        ),
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
        idempotency_key="legacy-key-001",
        order_notional=500.0,
        opens_new_position=False,
    )

    status = manager.status()

    assert result["status"] == "REJECTED"
    assert result["reason"] == "IDEMPOTENCY_STORE_UNAVAILABLE"
    assert exchange.orders == []
    assert status["idempotency"]["store_available"] is False
