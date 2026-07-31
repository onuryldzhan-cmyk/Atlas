"""
RED tests for durable execution-outcome reconciliation.

An exchange timeout or connection loss can occur after an order has
already reached the exchange. Atlas must therefore preserve the
indeterminate outcome, block resubmission, and reconcile it through
the exchange's client-order-id query contract.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from exchange.execution_exposure_guard import (
    ExecutionExposureGuard,
)
from exchange.execution_risk_guard import (
    ExecutionRiskGuard,
)
from exchange.execution_safety_gate import (
    ExecutionSafetyGate,
)
from exchange.exchange_manager import ExchangeManager


class ReconcilableExchange:
    def __init__(
        self,
        *,
        submit_exception: Exception | None = None,
        query_result: dict[str, Any] | None = None,
        query_exception: Exception | None = None,
    ) -> None:
        self.submit_exception = submit_exception
        self.query_result = query_result
        self.query_exception = query_exception

        self.submit_count = 0
        self.query_count = 0
        self.client_order_ids: list[str | None] = []

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        *,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        self.submit_count += 1
        self.client_order_ids.append(
            client_order_id
        )

        if self.submit_exception is not None:
            raise self.submit_exception

        return {
            "status": "FILLED",
            "order_id": "direct-fill-001",
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
        }

    def get_order_by_client_id(
        self,
        symbol: str,
        client_order_id: str,
    ) -> dict[str, Any]:
        self.query_count += 1

        if self.query_exception is not None:
            raise self.query_exception

        if self.query_result is None:
            return {
                "status": "UNKNOWN",
                "client_order_id": client_order_id,
                "symbol": symbol,
            }

        return deepcopy(
            self.query_result
        )


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

    assert result["accepted"] is True

    return guard


def _build_manager(
    exchange: ReconcilableExchange,
    *,
    store_path: Path | None = None,
) -> ExchangeManager:
    return ExchangeManager(
        exchange_name="test",
        exchange=exchange,
        safety_gate=ExecutionSafetyGate(
            mode="LIVE",
            live_enabled=True,
        ),
        risk_guard=ExecutionRiskGuard(
            starting_equity=10_000.0,
            max_daily_loss_percent=5.0,
            max_drawdown_percent=10.0,
        ),
        exposure_guard=_healthy_exposure_guard(),
        idempotency_store_path=store_path,
    )


def _place(
    manager: ExchangeManager,
    *,
    key: str,
    symbol: str = "BTCUSDT",
    quantity: float = 0.01,
    order_notional: float = 500.0,
    opens_new_position: bool = False,
) -> dict[str, Any]:
    return manager.place_order(
        symbol,
        "BUY",
        quantity,
        idempotency_key=key,
        order_notional=order_notional,
        opens_new_position=opens_new_position,
    )


def _assert_pending(
    result: dict[str, Any],
) -> None:
    assert result["status"] == "PENDING_RECONCILIATION"
    assert result["allowed"] is False
    assert result["reason"] == "EXCHANGE_OUTCOME_UNKNOWN"


def test_timeout_becomes_indeterminate_instead_of_retryable_error() -> None:
    exchange = ReconcilableExchange(
        submit_exception=TimeoutError(
            "response lost after submission"
        )
    )

    manager = _build_manager(
        exchange
    )

    result = _place(
        manager,
        key="reconcile-timeout-001",
    )

    _assert_pending(
        result
    )

    assert exchange.submit_count == 1

    status = manager.status()

    assert (
        status["idempotency"]["indeterminate_entries"]
        == 1
    )

    assert "reconcile-timeout-001" not in str(
        status
    )


def test_connection_loss_becomes_indeterminate() -> None:
    exchange = ReconcilableExchange(
        submit_exception=ConnectionError(
            "connection lost after request write"
        )
    )

    manager = _build_manager(
        exchange
    )

    result = _place(
        manager,
        key="reconcile-connection-001",
    )

    _assert_pending(
        result
    )

    assert exchange.submit_count == 1


def test_duplicate_pending_order_does_not_resubmit() -> None:
    exchange = ReconcilableExchange(
        submit_exception=TimeoutError(
            "submission outcome unavailable"
        )
    )

    manager = _build_manager(
        exchange
    )

    first = _place(
        manager,
        key="reconcile-duplicate-001",
    )

    second = _place(
        manager,
        key="reconcile-duplicate-001",
    )

    _assert_pending(
        first
    )

    assert second == first
    assert exchange.submit_count == 1


def test_indeterminate_outcome_survives_restart(
    tmp_path: Path,
) -> None:
    store_path = (
        tmp_path
        / "reconciliation-store.json"
    )

    first_exchange = ReconcilableExchange(
        submit_exception=TimeoutError(
            "exchange accepted but response was lost"
        )
    )

    first_manager = _build_manager(
        first_exchange,
        store_path=store_path,
    )

    first_result = _place(
        first_manager,
        key="reconcile-restart-001",
    )

    _assert_pending(
        first_result
    )

    assert store_path.exists()
    assert first_exchange.submit_count == 1

    second_exchange = ReconcilableExchange()

    second_manager = _build_manager(
        second_exchange,
        store_path=store_path,
    )

    second_result = _place(
        second_manager,
        key="reconcile-restart-001",
    )

    _assert_pending(
        second_result
    )

    assert second_exchange.submit_count == 0


def test_reconcile_filled_outcome_becomes_terminal_cache() -> None:
    exchange = ReconcilableExchange(
        submit_exception=TimeoutError(
            "response lost"
        ),
        query_result={
            "status": "FILLED",
            "order_id": "exchange-order-001",
            "client_order_id": "reconcile-filled-001",
        },
    )

    manager = _build_manager(
        exchange
    )

    _place(
        manager,
        key="reconcile-filled-001",
    )

    assert hasattr(
        manager,
        "reconcile_order",
    )

    reconciled = manager.reconcile_order(
        "reconcile-filled-001"
    )

    assert reconciled["status"] == "FILLED"
    assert (
        reconciled["order_id"]
        == "exchange-order-001"
    )

    duplicate = _place(
        manager,
        key="reconcile-filled-001",
    )

    assert duplicate == reconciled
    assert exchange.submit_count == 1
    assert exchange.query_count == 1


def test_reconcile_rejected_outcome_becomes_terminal_cache() -> None:
    exchange = ReconcilableExchange(
        submit_exception=TimeoutError(
            "response lost"
        ),
        query_result={
            "status": "REJECTED",
            "reason": "INSUFFICIENT_BALANCE",
            "client_order_id": "reconcile-rejected-001",
        },
    )

    manager = _build_manager(
        exchange
    )

    _place(
        manager,
        key="reconcile-rejected-001",
    )

    assert hasattr(
        manager,
        "reconcile_order",
    )

    reconciled = manager.reconcile_order(
        "reconcile-rejected-001"
    )

    assert reconciled["status"] == "REJECTED"
    assert (
        reconciled["reason"]
        == "INSUFFICIENT_BALANCE"
    )

    duplicate = _place(
        manager,
        key="reconcile-rejected-001",
    )

    assert duplicate == reconciled
    assert exchange.submit_count == 1
    assert exchange.query_count == 1


def test_reconciliation_query_error_remains_quarantined() -> None:
    exchange = ReconcilableExchange(
        submit_exception=TimeoutError(
            "response lost"
        ),
        query_exception=ConnectionError(
            "query endpoint unavailable"
        ),
    )

    manager = _build_manager(
        exchange
    )

    initial = _place(
        manager,
        key="reconcile-query-error-001",
    )

    _assert_pending(
        initial
    )

    assert hasattr(
        manager,
        "reconcile_order",
    )

    reconciled = manager.reconcile_order(
        "reconcile-query-error-001"
    )

    _assert_pending(
        reconciled
    )

    duplicate = _place(
        manager,
        key="reconcile-query-error-001",
    )

    _assert_pending(
        duplicate
    )

    assert exchange.submit_count == 1
    assert exchange.query_count == 1


def test_client_order_id_is_propagated_to_exchange() -> None:
    exchange = ReconcilableExchange()

    manager = _build_manager(
        exchange
    )

    result = _place(
        manager,
        key="exchange-client-order-001",
    )

    assert result["status"] == "FILLED"

    assert exchange.client_order_ids == [
        "exchange-client-order-001"
    ]


def test_pending_key_rejects_different_order_intent() -> None:
    exchange = ReconcilableExchange(
        submit_exception=TimeoutError(
            "response lost"
        )
    )

    manager = _build_manager(
        exchange
    )

    first = _place(
        manager,
        key="reconcile-conflict-001",
        order_notional=500.0,
    )

    _assert_pending(
        first
    )

    conflict = _place(
        manager,
        key="reconcile-conflict-001",
        order_notional=750.0,
    )

    assert conflict["status"] == "REJECTED"
    assert (
        conflict["reason"]
        == "IDEMPOTENCY_KEY_CONFLICT"
    )

    assert exchange.submit_count == 1
