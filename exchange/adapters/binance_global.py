"""
============================================================
ATLAS BINANCE GLOBAL ADAPTER v3.0
============================================================

Official Binance Spot SDK Adapter

SDK
---
binance-sdk-spot 10.0.0

Responsibilities
----------------
- Connect to Binance Spot REST API
- Provide public market price data
- Provide candlestick / kline data
- Support client-order-id reconciliation queries
- Preserve Atlas exchange adapter contracts
- Normalize typed Binance SDK responses
- Keep real order submission disabled

Safety
------
Real order submission remains disabled.

This adapter must not submit a live Binance order until the
Atlas live-trading authorization path is explicitly enabled,
reviewed, tested, and approved.

============================================================
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Any

from binance_common.configuration import ConfigurationRestAPI
from binance_sdk_spot.rest_api.models.enums import KlinesIntervalEnum
from binance_sdk_spot.spot import Spot
from dotenv import load_dotenv

from exchange.base_exchange import CLIENT_ORDER_ID_PATTERN, BaseExchange


load_dotenv()

logger = logging.getLogger(
    "AtlasAI.BinanceGlobal"
)


class BinanceGlobalExchange(BaseExchange):

    VERSION = "3.0"

    NAME = "Binance Global"

    SDK = "binance-sdk-spot"

    SDK_VERSION = "10.0.0"

    # =====================================================
    # INIT
    # =====================================================

    def __init__(self) -> None:

        self.connected = False

        self.client: Spot | None = None

        # Task 010 (registry v5.94): credentials are read only when a signed client is created,
        # for an order query, which ExchangeManager makes only under live authorization. Public
        # market data (connect, get_price, get_klines) uses a client without credentials, so no
        # API key header is sent outside that path (review 20 F-2).
        self._keyless_client = False

        logger.info(
            "Binance Global Adapter initialized"
        )

    # =====================================================
    # CLIENT
    # =====================================================

    def _create_client(self, *, signed: bool = False) -> Spot:

        configuration = ConfigurationRestAPI(
            api_key=(os.getenv("BINANCE_API_KEY", "") or None) if signed else None,
            api_secret=(os.getenv("BINANCE_API_SECRET", "") or None) if signed else None,
        )

        return Spot(
            config_rest_api=configuration,
        )

    # =====================================================
    # CONNECTION
    # =====================================================

    def connect(self) -> bool:

        try:

            if self.client is None:
                self.client = self._create_client()
                self._keyless_client = True

            response = self.client.rest_api.time()

            response.data()

            self.connected = True

            logger.info(
                "Binance Global connected"
            )

            return True

        except Exception:

            self.connected = False

            logger.exception(
                "Binance connection failed"
            )

            return False

    def disconnect(self) -> None:

        self.connected = False

        self.client = None

        self._keyless_client = False

        logger.info(
            "Binance disconnected"
        )

    def _ensure_connection(self) -> None:

        if (
            not self.connected
            or self.client is None
        ):

            logger.warning(
                "Binance reconnect required"
            )

            connected = self.connect()

            if not connected:
                raise ConnectionError(
                    "Binance connection failed"
                )

        if self.client is None:
            raise ConnectionError(
                "Binance client unavailable"
            )

    # =====================================================
    # RESPONSE NORMALIZATION
    # =====================================================

    @staticmethod
    def _model_to_dict(
        value: Any,
    ) -> dict[str, Any]:

        if isinstance(value, dict):
            return dict(value)

        model_dump = getattr(
            value,
            "model_dump",
            None,
        )

        if callable(model_dump):

            result = model_dump(
                mode="json",
                exclude_none=True,
            )

            if isinstance(result, dict):

                result.pop(
                    "additional_properties",
                    None,
                )

                return result

        raise TypeError(
            "Binance SDK response could not be normalized to a dictionary"
        )

    @staticmethod
    def _enum_value(
        value: Any,
    ) -> Any:

        if isinstance(value, Enum):
            return value.value

        return value

    # =====================================================
    # MARKET DATA
    # =====================================================

    def get_price(
        self,
        symbol: str,
    ) -> float:

        self._ensure_connection()

        assert self.client is not None

        response = (
            self.client
            .rest_api
            .ticker_price(
                symbol=symbol,
            )
        )

        data = response.data()

        actual_instance = getattr(
            data,
            "actual_instance",
            None,
        )

        if actual_instance is None:
            raise TypeError(
                "Binance ticker response does not contain a single-symbol result"
            )

        price = getattr(
            actual_instance,
            "price",
            None,
        )

        if price is None:
            raise TypeError(
                "Binance ticker response does not contain price"
            )

        return float(price)

    def get_klines(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 500,
    ) -> Any:

        self._ensure_connection()

        assert self.client is not None

        try:

            interval_enum = (
                KlinesIntervalEnum(
                    interval
                )
            )

        except ValueError as exc:

            raise ValueError(
                f"Unsupported Binance kline interval: {interval}"
            ) from exc

        response = (
            self.client
            .rest_api
            .klines(
                symbol=symbol,
                interval=interval_enum,
                limit=limit,
            )
        )

        data = response.data()

        if not isinstance(
            data,
            list,
        ):
            raise TypeError(
                "Binance klines response returned a non-list result"
            )

        return data

    # =====================================================
    # EXECUTION
    # =====================================================

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        *,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:

        # Task 008 (registry v5.92): every order carries a venue-valid client order id
        # (exchange.base_exchange.CLIENT_ORDER_ID_PATTERN); without one an order can never
        # be reconciled, so it is refused before anything else.
        if not isinstance(client_order_id, str) or not CLIENT_ORDER_ID_PATTERN.fullmatch(client_order_id):
            return {
                "status": "REJECTED",
                "reason": "INVALID_CLIENT_ORDER_ID",
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
            }

        logger.warning(
            "Real order disabled - PAPER MODE"
        )

        return {
            "status": "PAPER_ONLY",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "client_order_id": client_order_id,
        }

    # =====================================================
    # ORDER RECONCILIATION
    # =====================================================

    def get_order_by_client_id(
        self,
        symbol: str,
        client_order_id: str,
    ) -> dict[str, Any]:

        self._ensure_connection()

        # Review 21 L-1: a signed client exists only for this query and is never kept, so later
        # public calls stay keyless (an injected client is used as given).
        client = (
            self._create_client(signed=True)
            if self._keyless_client
            else self.client
        )

        assert client is not None

        response = (
            client
            .rest_api
            .get_order(
                symbol=symbol,
                orig_client_order_id=client_order_id,
            )
        )

        data = response.data()

        result = self._model_to_dict(
            data
        )

        # Keep the Atlas-facing contract JSON-like and
        # independent from Binance SDK Enum implementations.
        return {
            key: self._enum_value(value)
            for key, value in result.items()
        }