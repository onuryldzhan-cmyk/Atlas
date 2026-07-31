"""
Atlas Binance Global Adapter v2.1.

The adapter remains paper-only for order submission. It nevertheless exposes
Binance's client-order-id query contract so a future authorized live adapter
can reconcile uncertain outcomes without resubmitting an order.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from binance.spot import Spot
from dotenv import load_dotenv

from exchange.base_exchange import BaseExchange


load_dotenv()
logger = logging.getLogger("AtlasAI.BinanceGlobal")


class BinanceGlobalExchange(BaseExchange):
    VERSION = "2.1"

    def __init__(self) -> None:
        self.connected = False
        self.client: Spot | None = None
        self.api_key = os.getenv("BINANCE_API_KEY", "")
        self.api_secret = os.getenv("BINANCE_API_SECRET", "")
        logger.info("Binance Global Adapter initialized")

    def connect(self) -> bool:
        try:
            if self.client is None:
                self.client = Spot(api_key=self.api_key, api_secret=self.api_secret)
            self.client.time()
            self.connected = True
            logger.info("Binance Global connected")
            return True
        except Exception:
            self.connected = False
            logger.exception("Binance connection failed")
            return False

    def disconnect(self) -> None:
        self.connected = False
        self.client = None
        logger.info("Binance disconnected")

    def _ensure_connection(self) -> None:
        if not self.connected or self.client is None:
            logger.warning("Binance reconnect required")
            self.connect()
        if self.client is None:
            raise ConnectionError("Binance client unavailable")

    def get_price(self, symbol: str) -> float:
        self._ensure_connection()
        assert self.client is not None
        ticker = self.client.ticker_price(symbol=symbol)
        return float(ticker["price"])

    def get_klines(self, symbol: str, interval: str = "1m", limit: int = 500) -> Any:
        self._ensure_connection()
        assert self.client is not None
        return self.client.klines(symbol=symbol, interval=interval, limit=limit)

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        *,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        logger.warning("Real order disabled - PAPER MODE")
        return {
            "status": "PAPER_ONLY",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "client_order_id": client_order_id,
        }

    def get_order_by_client_id(
        self,
        symbol: str,
        client_order_id: str,
    ) -> dict[str, Any]:
        self._ensure_connection()
        assert self.client is not None
        result = self.client.get_order(
            symbol=symbol,
            origClientOrderId=client_order_id,
        )
        if not isinstance(result, dict):
            raise TypeError("Binance order query returned a non-object response")
        return result
