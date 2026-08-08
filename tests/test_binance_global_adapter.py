from __future__ import annotations

from enum import Enum
from types import SimpleNamespace
from typing import Any

import pytest

from exchange.adapters.binance_global import BinanceGlobalExchange


class FakeResponse:
    def __init__(self, data: Any) -> None:
        self._data = data

    def data(self) -> Any:
        return self._data


class FakeOrderStatus(Enum):
    FILLED = "FILLED"


def make_adapter(rest_api: Any) -> BinanceGlobalExchange:
    adapter = BinanceGlobalExchange()
    adapter.connected = True
    adapter.client = SimpleNamespace(rest_api=rest_api)
    return adapter


def test_place_order_remains_paper_only() -> None:
    adapter = BinanceGlobalExchange()

    result = adapter.place_order(
        "BTCUSDT",
        "BUY",
        0.001,
        client_order_id="atlas-test-order",
    )

    assert result == {
        "status": "PAPER_ONLY",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quantity": 0.001,
        "client_order_id": "atlas-test-order",
    }


def test_get_price_normalizes_single_symbol_ticker() -> None:
    class RestAPI:
        def ticker_price(self, *, symbol: str) -> FakeResponse:
            assert symbol == "BTCUSDT"

            ticker = SimpleNamespace(
                price="65000.25000000",
            )

            wrapper = SimpleNamespace(
                actual_instance=ticker,
            )

            return FakeResponse(wrapper)

    adapter = make_adapter(RestAPI())

    assert adapter.get_price("BTCUSDT") == 65000.25


def test_get_klines_maps_interval_to_sdk_enum() -> None:
    expected = [
        [
            1,
            "100.0",
            "101.0",
            "99.0",
            "100.5",
            "10.0",
        ]
    ]

    class RestAPI:
        def klines(
            self,
            *,
            symbol: str,
            interval: Any,
            limit: int,
        ) -> FakeResponse:
            assert symbol == "BTCUSDT"
            assert interval.value == "1m"
            assert limit == 2

            return FakeResponse(expected)

    adapter = make_adapter(RestAPI())

    result = adapter.get_klines(
        "BTCUSDT",
        "1m",
        2,
    )

    assert result == expected


def test_get_klines_rejects_unsupported_interval() -> None:
    adapter = make_adapter(
        SimpleNamespace()
    )

    with pytest.raises(
        ValueError,
        match="Unsupported Binance kline interval",
    ):
        adapter.get_klines(
            "BTCUSDT",
            "invalid",
            2,
        )


def test_get_order_by_client_id_uses_new_sdk_parameter() -> None:
    captured: dict[str, Any] = {}

    class OrderModel:
        def model_dump(
            self,
            *,
            mode: str,
            exclude_none: bool,
        ) -> dict[str, Any]:
            assert mode == "json"
            assert exclude_none is True

            return {
                "symbol": "BTCUSDT",
                "order_id": 12345,
                "client_order_id": "atlas-client-123",
                "status": FakeOrderStatus.FILLED,
                "additional_properties": {},
            }

    class RestAPI:
        def get_order(
            self,
            *,
            symbol: str,
            orig_client_order_id: str,
        ) -> FakeResponse:
            captured["symbol"] = symbol
            captured[
                "orig_client_order_id"
            ] = orig_client_order_id

            return FakeResponse(
                OrderModel()
            )

    adapter = make_adapter(RestAPI())

    result = adapter.get_order_by_client_id(
        "BTCUSDT",
        "atlas-client-123",
    )

    assert captured == {
        "symbol": "BTCUSDT",
        "orig_client_order_id": "atlas-client-123",
    }

    assert result["symbol"] == "BTCUSDT"
    assert result["order_id"] == 12345
    assert (
        result["client_order_id"]
        == "atlas-client-123"
    )
    assert result["status"] == "FILLED"

    assert (
        "additional_properties"
        not in result
    )


def test_connection_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = BinanceGlobalExchange()

    adapter.connected = False
    adapter.client = None

    monkeypatch.setattr(
        adapter,
        "connect",
        lambda: False,
    )

    with pytest.raises(
        ConnectionError,
        match="Binance connection failed",
    ):
        adapter._ensure_connection()