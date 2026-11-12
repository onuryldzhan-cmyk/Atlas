"""Atlas exchange contract."""

import hashlib
import re
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any


# Task 008 (registry v5.92): the venue's client order id format. Binance documents
# ``newClientOrderId`` as ``^[\.A-Z\:/a-z0-9_-]{1,36}$`` (a unique id among open
# orders); re-verify against the venue's current docs before live enablement.
CLIENT_ORDER_ID_PATTERN = re.compile(r"^[.A-Z:/a-z0-9_-]{1,36}$")
CLIENT_ORDER_ID_PREFIX = "atl-"


def derive_client_order_id(
    *,
    strategy_id: str,
    symbol: str,
    side: str,
    order_type: str,
    quantity: Decimal | str,
    price: Decimal | str | None,
    timestamp_ms: int,
    window_ms: int = 60_000,
) -> str:
    """Deterministic client order id for ONE order intent (Task 008, owner decision 2026-10-10).

    SHA-256 over (strategy_id, symbol, side, order_type, quantity and price as exact
    precision strings, timestamp window bucket), shortened to the venue's 36-character
    limit: ``atl-`` + 128 bits of hex. Derive it ONCE when the intent is created and
    store it with the intent; every retry and reconciliation reuses the stored id. It is
    never recomputed: a recomputation after the time bucket rolls over would yield a new
    id and could submit the same order twice.
    """
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
        raise ValueError("timestamp_ms must be a non-negative integer")
    if isinstance(window_ms, bool) or not isinstance(window_ms, int) or window_ms <= 0:
        raise ValueError("window_ms must be a positive integer")
    fields = []
    for name, value in (("strategy_id", strategy_id), ("symbol", symbol), ("side", side),
                        ("order_type", order_type)):
        text = str(value).strip().upper() if name != "strategy_id" else str(value).strip()
        if not text or "|" in text:
            raise ValueError(f"{name} is required and must not contain '|'")
        fields.append(text)
    for name, value in (("quantity", quantity), ("price", price)):
        if value is None and name == "price":
            fields.append("MARKET")
            continue
        if isinstance(value, (bool, float)):
            raise ValueError(f"{name} must be a Decimal or a precision string, never a float")
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError(f"{name} must be finite and positive")
        fields.append(str(value).strip())
    fields.append(str(timestamp_ms // window_ms))
    digest = hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()
    return CLIENT_ORDER_ID_PREFIX + digest[:32]


# Task 008: the venue error taxonomy a live adapter must raise, so ExchangeManager can
# classify outcomes. Any OTHER exception from an adapter keeps its existing meaning: a
# definite local failure before anything reached the venue.
class VenueError(Exception):
    """A response or failure from the venue itself."""

    def __init__(self, message: str = "", *, http_status: int | None = None,
                 venue_code: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.venue_code = venue_code


class VenueRateLimitedError(VenueError):
    """HTTP 429 / 418: the venue refused to process the request. Safe to retry with the
    SAME client order id after a backoff."""


class VenueOutcomeUnknownError(VenueError, ConnectionError):
    """HTTP 5xx or a dropped connection after dispatch. Binance documents a 5xx as
    "execution status UNKNOWN, could have been a success": the order must be reconciled
    by client order id, never blindly resubmitted."""


class VenueRejectedError(VenueError):
    """A terminal rejection (HTTP 400 bad precision/symbol, 401/403 auth or signature,
    venue code -2010 insufficient balance, ...): never retried."""


# Binance codes whose execution status is documented as UNKNOWN (-1006 UNEXPECTED_RESP,
# -1007 TIMEOUT), whatever HTTP status carries them (review 10 M-3).
UNKNOWN_OUTCOME_VENUE_CODES = frozenset({-1006, -1007})


def classify_venue_failure(http_status: int | None, venue_code: int | None = None,
                           message: str | None = None) -> type[VenueError]:
    """Map a venue HTTP status, venue error code and message onto the taxonomy above.

    Anything not positively known to be terminal or rate-limited is UNKNOWN, so an
    unrecognised failure is reconciled rather than treated as safe to resend. "Duplicate
    order sent" (-2010) means the venue already holds an order with this client order id:
    its outcome is unknown, never a terminal rejection.
    """
    if http_status in (418, 429):
        return VenueRateLimitedError
    if venue_code in UNKNOWN_OUTCOME_VENUE_CODES:
        return VenueOutcomeUnknownError
    if message is not None and "duplicate order" in str(message).lower():
        return VenueOutcomeUnknownError
    if http_status == 408:  # request timeout: the venue may or may not have processed it
        return VenueOutcomeUnknownError
    if http_status is not None and 400 <= http_status < 500:
        return VenueRejectedError
    if venue_code == -2010:
        return VenueRejectedError
    return VenueOutcomeUnknownError


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
