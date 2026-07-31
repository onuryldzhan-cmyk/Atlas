from __future__ import annotations

import threading
import time

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


class BlockingExchange:
    def __init__(self) -> None:
        self.call_count = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        with self._lock:
            self.call_count += 1
            call_number = self.call_count

        self.entered.set()

        released = self.release.wait(
            timeout=5.0,
        )

        if not released:
            raise TimeoutError(
                "Test exchange release timeout"
            )

        return {
            "status": "FILLED",
            "order_id": f"order-{call_number}",
        }


class FailingBlockingExchange:
    def __init__(self) -> None:
        self.call_count = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        with self._lock:
            self.call_count += 1

        self.entered.set()

        released = self.release.wait(
            timeout=5.0,
        )

        if not released:
            raise TimeoutError(
                "Test exchange release timeout"
            )

        raise ConnectionError(
            "Simulated exchange outage"
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
    exchange: Any,
    *,
    in_flight_wait_timeout_seconds: float = 2.0,
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
        in_flight_wait_timeout_seconds=(
            in_flight_wait_timeout_seconds
        ),
    )


def _place_order(
    manager: ExchangeManager,
    *,
    symbol: str = "BTCUSDT",
    quantity: float = 0.01,
    key: str = "concurrent-request-001",
) -> dict[str, Any]:
    return manager.place_order(
        symbol,
        "BUY",
        quantity,
        idempotency_key=key,
        order_notional=500.0,
        opens_new_position=False,
    )


def test_concurrent_same_key_same_order_calls_adapter_once() -> None:
    exchange = BlockingExchange()
    manager = _build_manager(exchange)

    results: list[dict[str, Any]] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(
                _place_order(
                    manager,
                )
            )
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(
        target=worker,
        name="atlas-order-first",
    )

    second = threading.Thread(
        target=worker,
        name="atlas-order-second",
    )

    first.start()

    assert exchange.entered.wait(
        timeout=2.0,
    )

    second.start()

    time.sleep(0.10)

    assert exchange.call_count == 1

    exchange.release.set()

    first.join(timeout=3.0)
    second.join(timeout=3.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert exchange.call_count == 1
    assert len(results) == 2
    assert results[0] == results[1]
    assert results[0]["status"] == "FILLED"


def test_concurrent_same_key_different_order_rejects_conflict() -> None:
    exchange = BlockingExchange()
    manager = _build_manager(exchange)

    first_result: list[dict[str, Any]] = []

    def first_worker() -> None:
        first_result.append(
            _place_order(
                manager,
                symbol="BTCUSDT",
                quantity=0.01,
                key="concurrent-conflict-001",
            )
        )

    first = threading.Thread(
        target=first_worker,
        name="atlas-conflict-first",
    )

    first.start()

    assert exchange.entered.wait(
        timeout=2.0,
    )

    second_result = _place_order(
        manager,
        symbol="ETHUSDT",
        quantity=0.50,
        key="concurrent-conflict-001",
    )

    assert second_result["status"] == "REJECTED"
    assert (
        second_result["reason"]
        == "IDEMPOTENCY_KEY_CONFLICT"
    )
    assert exchange.call_count == 1

    exchange.release.set()
    first.join(timeout=3.0)

    assert not first.is_alive()
    assert first_result[0]["status"] == "FILLED"


def test_waiting_duplicate_receives_adapter_error_result() -> None:
    exchange = FailingBlockingExchange()
    manager = _build_manager(exchange)

    results: list[dict[str, Any]] = []

    def worker() -> None:
        results.append(
            _place_order(
                manager,
                key="concurrent-error-001",
            )
        )

    first = threading.Thread(
        target=worker,
    )

    second = threading.Thread(
        target=worker,
    )

    first.start()

    assert exchange.entered.wait(
        timeout=2.0,
    )

    second.start()

    time.sleep(0.10)

    assert exchange.call_count == 1

    exchange.release.set()

    first.join(timeout=3.0)
    second.join(timeout=3.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert exchange.call_count == 1
    assert len(results) == 2

    for result in results:
        assert result["status"] == "ERROR"
        assert (
            result["reason"]
            == "EXCHANGE_CONNECTION_ERROR"
        )


def test_in_flight_wait_timeout_fails_closed() -> None:
    exchange = BlockingExchange()

    manager = _build_manager(
        exchange,
        in_flight_wait_timeout_seconds=0.10,
    )

    first_result: list[dict[str, Any]] = []

    first = threading.Thread(
        target=lambda: first_result.append(
            _place_order(
                manager,
                key="concurrent-timeout-001",
            )
        )
    )

    first.start()

    assert exchange.entered.wait(
        timeout=2.0,
    )

    second_result = _place_order(
        manager,
        key="concurrent-timeout-001",
    )

    assert second_result["status"] == "REJECTED"
    assert (
        second_result["reason"]
        == "IDEMPOTENCY_REQUEST_IN_FLIGHT_TIMEOUT"
    )
    assert exchange.call_count == 1

    exchange.release.set()
    first.join(timeout=3.0)

    assert not first.is_alive()
    assert first_result[0]["status"] == "FILLED"


def test_in_flight_status_does_not_expose_keys() -> None:
    exchange = BlockingExchange()
    manager = _build_manager(exchange)

    thread = threading.Thread(
        target=lambda: _place_order(
            manager,
            key="secret-concurrent-key",
        )
    )

    thread.start()

    assert exchange.entered.wait(
        timeout=2.0,
    )

    status = manager.status()

    assert status["idempotency"]["in_flight_entries"] == 1
    assert "secret-concurrent-key" not in str(status)
    assert "in_flight_requests" not in status["idempotency"]

    exchange.release.set()
    thread.join(timeout=3.0)

    assert not thread.is_alive()


class AbortingExchange:
    def __init__(self) -> None:
        self.entered = threading.Event()

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict[str, Any]:
        self.entered.set()
        raise KeyboardInterrupt("Simulated leader process interrupt")


def test_leader_base_exception_releases_duplicate_and_cleans_in_flight() -> None:
    exchange = AbortingExchange()
    manager = _build_manager(
        exchange,
        in_flight_wait_timeout_seconds=5.0,
    )

    follower_result: list[dict[str, Any]] = []
    follower_errors: list[BaseException] = []

    def leader_worker() -> None:
        try:
            _place_order(
                manager,
                key="leader-abort-001",
            )
        except BaseException:
            pass

    def follower_worker() -> None:
        try:
            follower_result.append(
                _place_order(
                    manager,
                    key="leader-abort-001",
                )
            )
        except BaseException as exc:
            follower_errors.append(exc)

    leader = threading.Thread(
        target=leader_worker,
        name="atlas-leader-abort",
    )
    follower = threading.Thread(
        target=follower_worker,
        name="atlas-follower-wait",
    )

    leader.start()
    assert exchange.entered.wait(timeout=2.0)

    start_time = time.monotonic()
    follower.start()

    leader.join(timeout=3.0)
    follower.join(timeout=3.0)

    elapsed = time.monotonic() - start_time

    assert not leader.is_alive()
    assert not follower.is_alive()
    assert follower_errors == []

    assert elapsed < 2.0

    assert len(follower_result) == 1
    assert follower_result[0]["status"] == "ERROR"
    assert follower_result[0]["reason"] == "IDEMPOTENCY_LEADER_ABORTED"

    status = manager.status()
    assert status["idempotency"]["in_flight_entries"] == 0
    assert "leader-abort-001" not in str(status)


def test_finalization_failure_quarantines_key_and_prevents_duplicate_adapter_calls() -> None:
    class SuccessfulExchange:
        def __init__(self) -> None:
            self.call_count = 0
            self.entered = threading.Event()
            self.release = threading.Event()
            self._lock = threading.Lock()

        def place_order(
            self,
            symbol: str,
            side: str,
            quantity: float,
        ) -> dict[str, Any]:
            with self._lock:
                self.call_count += 1

            self.entered.set()
            assert self.release.wait(timeout=5.0)

            return {
                "status": "FILLED",
                "order_id": "committed-order-001",
            }

    exchange = SuccessfulExchange()
    manager = _build_manager(
        exchange,
        in_flight_wait_timeout_seconds=5.0,
    )

    original_cache_method = manager._cache_idempotency_result

    def failing_cache_result(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Disk write failed during result caching")

    manager._cache_idempotency_result = failing_cache_result

    leader_result: list[dict[str, Any]] = []
    follower_result: list[dict[str, Any]] = []

    def leader_worker() -> None:
        try:
            leader_result.append(
                _place_order(
                    manager,
                    key="finalization-failure-001",
                )
            )
        except RuntimeError:
            pass

    def follower_worker() -> None:
        follower_result.append(
            _place_order(
                manager,
                key="finalization-failure-001",
            )
        )

    leader = threading.Thread(
        target=leader_worker,
        name="atlas-leader-finalization",
    )
    follower = threading.Thread(
        target=follower_worker,
        name="atlas-follower-finalization",
    )

    try:
        leader.start()
        assert exchange.entered.wait(timeout=2.0)

        follower.start()
        time.sleep(0.10)

        assert exchange.call_count == 1

        exchange.release.set()

        leader.join(timeout=3.0)
        follower.join(timeout=3.0)

        assert not leader.is_alive()
        assert not follower.is_alive()

        assert exchange.call_count == 1

        assert len(follower_result) == 1
        assert follower_result[0]["status"] == "ERROR"
        assert follower_result[0]["reason"] == "IDEMPOTENCY_FINALIZATION_FAILED"

        status = manager.status()
        assert status["idempotency"]["in_flight_entries"] == 0

        subsequent_result = _place_order(
            manager,
            key="finalization-failure-001",
        )

        assert exchange.call_count == 1
        assert subsequent_result["status"] in ("REJECTED", "ERROR")
        assert subsequent_result["reason"] == "IDEMPOTENCY_OUTCOME_UNKNOWN"

    finally:
        manager._cache_idempotency_result = original_cache_method

