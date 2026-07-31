"""Atlas exchange contract."""

from abc import ABC, abstractmethod
from typing import Any


class BaseExchange(ABC):
    @abstractmethod
    def connect(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def get_price(self, symbol: str) -> Any:
        raise NotImplementedError

    @abstractmethod
    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> Any:
        raise NotImplementedError

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        *,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def get_order_by_client_id(
        self,
        symbol: str,
        client_order_id: str,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "exchange adapter does not support client-order-id reconciliation"
        )
