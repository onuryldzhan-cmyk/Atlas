"""
============================================================
ATLAS BINANCE PUBLIC DATA PROVIDER v1.0.0
============================================================

Project Atlas AI

Production-oriented public Binance market-data provider.

Responsibilities
----------------
- Fetch public ticker prices
- Fetch public OHLCV candles
- Normalize Binance responses
- Validate symbols, timeframes and limits
- Apply timeout, retry and exponential backoff
- Maintain provider connection state
- Reuse HTTP connections safely
- Expose no order execution capability

Security boundary
-----------------
This provider:

- Does not require an API key
- Does not read trading secrets
- Cannot place orders
- Cannot access portfolio capital
- Cannot modify positions
- Cannot execute trades

============================================================
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time

from collections.abc import Mapping
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Final
from typing import Sequence

import requests

from requests import Response
from requests import Session
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
)
from requests.exceptions import (
    RequestException,
)
from requests.exceptions import (
    Timeout as RequestsTimeout,
)

from atlas_finance.market_data.contracts import (
    MarketDataProviderProtocol,
)

from atlas_finance.market_data.exceptions import (
    InvalidCandleError,
    InvalidCandleLimitError,
    InvalidPriceError,
    InvalidSymbolError,
    InvalidTimeframeError,
    MarketDataConfigurationError,
    MarketDataConnectionError,
    MarketDataRateLimitError,
    MarketDataRequestError,
    MarketDataResponseError,
    MarketDataTimeoutError,
)

from atlas_finance.market_data.models import (
    MarketCandle,
    MarketPrice,
    utc_now,
)


logger = logging.getLogger(
    "AtlasFinance.BinancePublicDataProvider"
)


class BinancePublicDataProvider(
    MarketDataProviderProtocol
):
    """
    Public Binance REST market-data provider.

    The provider intentionally implements no authenticated or
    execution-related endpoint.
    """

    VERSION: Final[str] = "1.0.0"

    PROVIDER_NAME: Final[str] = (
        "BinancePublicData"
    )

    DEFAULT_BASE_URL: Final[str] = (
        "https://api.binance.com"
    )

    DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0

    DEFAULT_RETRY_ATTEMPTS: Final[int] = 3

    DEFAULT_RETRY_BACKOFF_SECONDS: Final[float] = 0.5

    DEFAULT_MAXIMUM_CANDLE_LIMIT: Final[int] = 1000

    MINIMUM_CANDLE_LIMIT: Final[int] = 1

    SYMBOL_PATTERN: Final[
        re.Pattern[str]
    ] = re.compile(
        r"^[A-Z0-9]{4,30}$"
    )

    SUPPORTED_TIMEFRAMES: Final[
        tuple[str, ...]
    ] = (
        "1s",
        "1m",
        "3m",
        "5m",
        "15m",
        "30m",
        "1h",
        "2h",
        "4h",
        "6h",
        "8h",
        "12h",
        "1d",
        "3d",
        "1w",
        "1M",
    )

    RETRYABLE_HTTP_STATUS_CODES: Final[
        frozenset[int]
    ] = frozenset(
        {
            418,
            429,
            500,
            502,
            503,
            504,
        }
    )

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = (
            DEFAULT_TIMEOUT_SECONDS
        ),
        retry_attempts: int = (
            DEFAULT_RETRY_ATTEMPTS
        ),
        retry_backoff_seconds: float = (
            DEFAULT_RETRY_BACKOFF_SECONDS
        ),
        maximum_candle_limit: int = (
            DEFAULT_MAXIMUM_CANDLE_LIMIT
        ),
        session: Session | None = None,
        connection_test_symbol: str = "BTCUSDT",
    ) -> None:
        self._base_url = self._validate_base_url(
            base_url
        )

        self._timeout_seconds = (
            self._validate_positive_float(
                timeout_seconds,
                field_name="timeout_seconds",
            )
        )

        self._retry_attempts = (
            self._validate_retry_attempts(
                retry_attempts
            )
        )

        self._retry_backoff_seconds = (
            self._validate_non_negative_float(
                retry_backoff_seconds,
                field_name=(
                    "retry_backoff_seconds"
                ),
            )
        )

        self._maximum_candle_limit = (
            self._validate_maximum_candle_limit(
                maximum_candle_limit
            )
        )

        self._connection_test_symbol = (
            self._normalize_symbol(
                connection_test_symbol
            )
        )

        self._session = (
            session
            if session is not None
            else requests.Session()
        )

        self._owns_session = (
            session is None
        )

        self._connected = False

        self._closed = False

        self._lock = threading.RLock()

        logger.info(
            "%s v%s initialized.",
            self.PROVIDER_NAME,
            self.VERSION,
        )

    # =====================================================
    # PUBLIC PROPERTIES
    # =====================================================

    @property
    def provider_name(
        self,
    ) -> str:
        return self.PROVIDER_NAME

    @property
    def connected(
        self,
    ) -> bool:
        with self._lock:
            return self._connected

    @property
    def base_url(
        self,
    ) -> str:
        return self._base_url

    @property
    def timeout_seconds(
        self,
    ) -> float:
        return self._timeout_seconds

    @property
    def retry_attempts(
        self,
    ) -> int:
        return self._retry_attempts

    @property
    def retry_backoff_seconds(
        self,
    ) -> float:
        return self._retry_backoff_seconds

    @property
    def maximum_candle_limit(
        self,
    ) -> int:
        return self._maximum_candle_limit

    @property
    def supported_timeframes(
        self,
    ) -> tuple[str, ...]:
        return self.SUPPORTED_TIMEFRAMES

    # =====================================================
    # LIFECYCLE
    # =====================================================

    def connect(
        self,
    ) -> bool:
        """
        Validate public Binance connectivity.

        No authentication or private account request is made.
        """

        with self._lock:
            if self._connected:
                return True

            if self._closed:
                if not self._owns_session:
                    raise MarketDataConnectionError(
                        "Injected Binance public provider session "
                        "has already been closed."
                    )

                self._session = requests.Session()
                self._closed = False

                logger.info(
                    "%s HTTP session recreated for restart.",
                    self.PROVIDER_NAME,
                )

        try:
            self.get_price(
                self._connection_test_symbol
            )

        except Exception as error:
            with self._lock:
                self._connected = False

            raise MarketDataConnectionError(
                "Binance public connectivity test failed."
            ) from error

        with self._lock:
            self._connected = True

        logger.info(
            "%s connected successfully.",
            self.PROVIDER_NAME,
        )

        return True

    def disconnect(
        self,
    ) -> None:
        """
        Disconnect and release owned HTTP resources.
        """

        with self._lock:
            self._connected = False

            if (
                self._owns_session
                and not self._closed
            ):
                self._session.close()
                self._closed = True

        logger.info(
            "%s disconnected.",
            self.PROVIDER_NAME,
        )

    # =====================================================
    # PRICE
    # =====================================================

    def get_price(
        self,
        symbol: str,
    ) -> MarketPrice:
        """
        Fetch and normalize the latest symbol price.
        """

        normalized_symbol = (
            self._normalize_symbol(
                symbol
            )
        )

        payload = self._request_json(
            endpoint="/api/v3/ticker/price",
            params={
                "symbol": normalized_symbol,
            },
        )

        if not isinstance(
            payload,
            Mapping,
        ):
            raise MarketDataResponseError(
                "Binance ticker response must be "
                "a JSON object."
            )

        response_symbol = (
            self._normalize_symbol(
                str(
                    payload.get(
                        "symbol",
                        normalized_symbol,
                    )
                )
            )
        )

        if (
            response_symbol
            != normalized_symbol
        ):
            raise MarketDataResponseError(
                "Binance ticker response symbol does "
                "not match the requested symbol."
            )

        price = self._parse_positive_float(
            payload.get(
                "price"
            ),
            field_name="price",
            exception_type=InvalidPriceError,
        )

        with self._lock:
            self._connected = True

        return MarketPrice(
            symbol=normalized_symbol,
            price=price,
            provider=self.PROVIDER_NAME,
            received_at=utc_now(),
            source_timestamp=None,
            metadata={
                "endpoint": (
                    "/api/v3/ticker/price"
                ),
            },
        )

    # =====================================================
    # CANDLES
    # =====================================================

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 100,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Sequence[MarketCandle]:
        """
        Fetch and normalize Binance OHLCV candles.

        When ``start_time`` and/or ``end_time`` are supplied the
        request is bounded to that window. Binance still returns at
        most ``limit`` candles per call regardless of how wide the
        window is, so callers walking a long history must page by
        advancing ``start_time`` past the last returned open time.
        """

        normalized_symbol = (
            self._normalize_symbol(
                symbol
            )
        )

        normalized_timeframe = (
            self._normalize_timeframe(
                timeframe
            )
        )

        normalized_limit = (
            self._validate_candle_limit(
                limit
            )
        )

        request_params: dict[str, Any] = {
            "symbol": normalized_symbol,
            "interval": normalized_timeframe,
            "limit": normalized_limit,
        }

        if start_time is not None:
            request_params["startTime"] = (
                self._datetime_to_milliseconds(
                    start_time,
                    field_name="start_time",
                )
            )

        if end_time is not None:
            request_params["endTime"] = (
                self._datetime_to_milliseconds(
                    end_time,
                    field_name="end_time",
                )
            )

        if (
            start_time is not None
            and end_time is not None
            and request_params["endTime"]
            < request_params["startTime"]
        ):
            raise MarketDataRequestError(
                "end_time cannot precede start_time."
            )

        payload = self._request_json(
            endpoint="/api/v3/klines",
            params=request_params,
        )

        if not isinstance(
            payload,
            list,
        ):
            raise MarketDataResponseError(
                "Binance kline response must be "
                "a JSON array."
            )

        candles: list[
            MarketCandle
        ] = []

        for index, raw_candle in enumerate(
            payload
        ):
            try:
                candle = self._parse_candle(
                    raw_candle,
                    symbol=normalized_symbol,
                    timeframe=(
                        normalized_timeframe
                    ),
                )

            except (
                InvalidCandleError,
                MarketDataResponseError,
                TypeError,
                ValueError,
                IndexError,
            ) as error:
                raise InvalidCandleError(
                    "Invalid Binance candle at index "
                    f"{index}: {error}"
                ) from error

            candles.append(
                candle
            )

        candles.sort(
            key=lambda item: item.open_time
        )

        with self._lock:
            self._connected = True

        return tuple(
            candles
        )

    # =====================================================
    # HTTP REQUEST
    # =====================================================

    def _request_json(
        self,
        *,
        endpoint: str,
        params: Mapping[str, Any],
    ) -> Any:
        self._ensure_available()

        url = (
            f"{self._base_url}"
            f"{endpoint}"
        )

        last_error: Exception | None = None

        for attempt in range(
            1,
            self._retry_attempts + 1,
        ):
            try:
                response = self._perform_get(
                    url=url,
                    params=params,
                )

                self._validate_response(
                    response
                )

                try:
                    return response.json()

                except ValueError as error:
                    raise MarketDataResponseError(
                        "Binance returned invalid JSON."
                    ) from error

            except MarketDataRateLimitError:
                raise

            except (
                MarketDataTimeoutError,
                MarketDataConnectionError,
                MarketDataRequestError,
                MarketDataResponseError,
            ) as error:
                last_error = error

                if (
                    attempt
                    >= self._retry_attempts
                ):
                    break

                delay = (
                    self._retry_backoff_seconds
                    * (2 ** (attempt - 1))
                )

                logger.warning(
                    (
                        "Binance public request failed; "
                        "retrying. endpoint=%s "
                        "attempt=%s/%s delay=%.3f "
                        "error=%s"
                    ),
                    endpoint,
                    attempt,
                    self._retry_attempts,
                    delay,
                    error,
                )

                if delay > 0:
                    time.sleep(
                        delay
                    )

        with self._lock:
            self._connected = False

        if last_error is not None:
            raise last_error

        raise MarketDataRequestError(
            "Binance public request failed without "
            "a recorded error."
        )

    def _perform_get(
        self,
        *,
        url: str,
        params: Mapping[str, Any],
    ) -> Response:
        try:
            with self._lock:
                response = self._session.get(
                    url,
                    params=dict(
                        params
                    ),
                    timeout=(
                        self._timeout_seconds
                    ),
                    headers={
                        "Accept": (
                            "application/json"
                        ),
                        "User-Agent": (
                            "Project-Atlas-AI/"
                            f"{self.VERSION}"
                        ),
                    },
                )

            return response

        except RequestsTimeout as error:
            raise MarketDataTimeoutError(
                "Binance public request timed out "
                f"after {self._timeout_seconds} "
                "seconds."
            ) from error

        except RequestsConnectionError as error:
            raise MarketDataConnectionError(
                "Could not connect to Binance "
                "public API."
            ) from error

        except RequestException as error:
            raise MarketDataRequestError(
                "Binance public HTTP request failed."
            ) from error

    @classmethod
    def _validate_response(
        cls,
        response: Response,
    ) -> None:
        status_code = response.status_code

        if status_code in {
            418,
            429,
        }:
            retry_after = response.headers.get(
                "Retry-After"
            )

            message = (
                "Binance public API rate limit "
                f"reached. status={status_code}"
            )

            if retry_after:
                message += (
                    f" retry_after={retry_after}"
                )

            raise MarketDataRateLimitError(
                message
            )

        if status_code in (
            cls.RETRYABLE_HTTP_STATUS_CODES
        ):
            raise MarketDataRequestError(
                "Binance public API returned a "
                "retryable server error. "
                f"status={status_code}"
            )

        if not (
            200
            <= status_code
            < 300
        ):
            response_text = (
                response.text[:300]
                if response.text
                else ""
            )

            raise MarketDataRequestError(
                "Binance public API request failed. "
                f"status={status_code} "
                f"response={response_text!r}"
            )

    # =====================================================
    # CANDLE PARSING
    # =====================================================

    def _parse_candle(
        self,
        raw_candle: Any,
        *,
        symbol: str,
        timeframe: str,
    ) -> MarketCandle:
        if not isinstance(
            raw_candle,
            (
                list,
                tuple,
            ),
        ):
            raise MarketDataResponseError(
                "Binance candle must be an array."
            )

        if len(
            raw_candle
        ) < 7:
            raise MarketDataResponseError(
                "Binance candle array is incomplete."
            )

        open_time = (
            self._milliseconds_to_datetime(
                raw_candle[0],
                field_name="open_time",
            )
        )

        close_time = (
            self._milliseconds_to_datetime(
                raw_candle[6],
                field_name="close_time",
            )
        )

        open_price = (
            self._parse_positive_float(
                raw_candle[1],
                field_name="open",
                exception_type=(
                    InvalidCandleError
                ),
            )
        )

        high_price = (
            self._parse_positive_float(
                raw_candle[2],
                field_name="high",
                exception_type=(
                    InvalidCandleError
                ),
            )
        )

        low_price = (
            self._parse_positive_float(
                raw_candle[3],
                field_name="low",
                exception_type=(
                    InvalidCandleError
                ),
            )
        )

        close_price = (
            self._parse_positive_float(
                raw_candle[4],
                field_name="close",
                exception_type=(
                    InvalidCandleError
                ),
            )
        )

        volume = (
            self._parse_non_negative_float(
                raw_candle[5],
                field_name="volume",
                exception_type=(
                    InvalidCandleError
                ),
            )
        )

        if high_price < low_price:
            raise InvalidCandleError(
                "Candle high price cannot be lower "
                "than its low price."
            )

        if high_price < max(
            open_price,
            close_price,
        ):
            raise InvalidCandleError(
                "Candle high price cannot be lower "
                "than open or close."
            )

        if low_price > min(
            open_price,
            close_price,
        ):
            raise InvalidCandleError(
                "Candle low price cannot be higher "
                "than open or close."
            )

        if close_time < open_time:
            raise InvalidCandleError(
                "Candle close time cannot precede "
                "its open time."
            )

        closed = (
            close_time
            <= utc_now()
        )

        return MarketCandle(
            symbol=symbol,
            timeframe=timeframe,
            open_time=open_time,
            close_time=close_time,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            provider=self.PROVIDER_NAME,
            closed=closed,
            metadata={
                "trades": (
                    self._optional_integer(
                        raw_candle[8]
                    )
                    if len(raw_candle) > 8
                    else None
                ),
                "quote_volume": (
                    self._optional_float(
                        raw_candle[7]
                    )
                    if len(raw_candle) > 7
                    else None
                ),
                "taker_buy_base_volume": (
                    self._optional_float(
                        raw_candle[9]
                    )
                    if len(raw_candle) > 9
                    else None
                ),
                "taker_buy_quote_volume": (
                    self._optional_float(
                        raw_candle[10]
                    )
                    if len(raw_candle) > 10
                    else None
                ),
            },
        )

    # =====================================================
    # VALIDATION
    # =====================================================

    def _ensure_available(
        self,
    ) -> None:
        with self._lock:
            if self._closed:
                raise MarketDataConnectionError(
                    "Binance public provider session "
                    "is closed."
                )

    @classmethod
    def _normalize_symbol(
        cls,
        symbol: str,
    ) -> str:
        if not isinstance(
            symbol,
            str,
        ):
            raise InvalidSymbolError(
                "Market symbol must be a string."
            )

        normalized = (
            symbol.strip()
            .upper()
            .replace(
                "/",
                "",
            )
            .replace(
                "-",
                "",
            )
            .replace(
                "_",
                "",
            )
        )

        if not normalized:
            raise InvalidSymbolError(
                "Market symbol cannot be empty."
            )

        if not cls.SYMBOL_PATTERN.fullmatch(
            normalized
        ):
            raise InvalidSymbolError(
                "Market symbol contains unsupported "
                f"characters: {symbol!r}"
            )

        return normalized

    @classmethod
    def _normalize_timeframe(
        cls,
        timeframe: str,
    ) -> str:
        if not isinstance(
            timeframe,
            str,
        ):
            raise InvalidTimeframeError(
                "Timeframe must be a string."
            )

        normalized = timeframe.strip()

        if (
            normalized
            not in cls.SUPPORTED_TIMEFRAMES
        ):
            raise InvalidTimeframeError(
                "Unsupported Binance timeframe: "
                f"{timeframe!r}. Supported values: "
                f"{cls.SUPPORTED_TIMEFRAMES}"
            )

        return normalized

    def _validate_candle_limit(
        self,
        limit: int,
    ) -> int:
        if (
            isinstance(
                limit,
                bool,
            )
            or not isinstance(
                limit,
                int,
            )
        ):
            raise InvalidCandleLimitError(
                "Candle limit must be an integer."
            )

        if (
            limit
            < self.MINIMUM_CANDLE_LIMIT
            or limit
            > self._maximum_candle_limit
        ):
            raise InvalidCandleLimitError(
                "Candle limit must be between "
                f"{self.MINIMUM_CANDLE_LIMIT} and "
                f"{self._maximum_candle_limit}."
            )

        return limit

    @staticmethod
    def _validate_base_url(
        base_url: str,
    ) -> str:
        if not isinstance(
            base_url,
            str,
        ):
            raise MarketDataConfigurationError(
                "base_url must be a string."
            )

        normalized = base_url.strip().rstrip(
            "/"
        )

        if not normalized.startswith(
            (
                "https://",
                "http://",
            )
        ):
            raise MarketDataConfigurationError(
                "base_url must begin with HTTP or "
                "HTTPS."
            )

        return normalized

    @staticmethod
    def _validate_retry_attempts(
        value: int,
    ) -> int:
        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
        ):
            raise MarketDataConfigurationError(
                "retry_attempts must be an integer."
            )

        if value < 1 or value > 10:
            raise MarketDataConfigurationError(
                "retry_attempts must be between "
                "1 and 10."
            )

        return value

    @staticmethod
    def _validate_maximum_candle_limit(
        value: int,
    ) -> int:
        if (
            isinstance(
                value,
                bool,
            )
            or not isinstance(
                value,
                int,
            )
        ):
            raise MarketDataConfigurationError(
                "maximum_candle_limit must be an "
                "integer."
            )

        if value < 1 or value > 1000:
            raise MarketDataConfigurationError(
                "maximum_candle_limit must be "
                "between 1 and 1000."
            )

        return value

    @staticmethod
    def _validate_positive_float(
        value: float,
        *,
        field_name: str,
    ) -> float:
        try:
            normalized = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise MarketDataConfigurationError(
                f"{field_name} must be numeric."
            ) from error

        if (
            not math.isfinite(
                normalized
            )
            or normalized <= 0
        ):
            raise MarketDataConfigurationError(
                f"{field_name} must be finite and "
                "greater than zero."
            )

        return normalized

    @staticmethod
    def _validate_non_negative_float(
        value: float,
        *,
        field_name: str,
    ) -> float:
        try:
            normalized = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise MarketDataConfigurationError(
                f"{field_name} must be numeric."
            ) from error

        if (
            not math.isfinite(
                normalized
            )
            or normalized < 0
        ):
            raise MarketDataConfigurationError(
                f"{field_name} must be finite and "
                "non-negative."
            )

        return normalized

    @staticmethod
    def _parse_positive_float(
        value: Any,
        *,
        field_name: str,
        exception_type: type[Exception],
    ) -> float:
        try:
            normalized = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise exception_type(
                f"{field_name} must be numeric."
            ) from error

        if (
            not math.isfinite(
                normalized
            )
            or normalized <= 0
        ):
            raise exception_type(
                f"{field_name} must be finite and "
                "greater than zero."
            )

        return normalized

    @staticmethod
    def _parse_non_negative_float(
        value: Any,
        *,
        field_name: str,
        exception_type: type[Exception],
    ) -> float:
        try:
            normalized = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise exception_type(
                f"{field_name} must be numeric."
            ) from error

        if (
            not math.isfinite(
                normalized
            )
            or normalized < 0
        ):
            raise exception_type(
                f"{field_name} must be finite and "
                "non-negative."
            )

        return normalized

    @staticmethod
    def _datetime_to_milliseconds(
        value: datetime,
        *,
        field_name: str,
    ) -> int:
        if not isinstance(
            value,
            datetime,
        ):
            raise MarketDataRequestError(
                f"{field_name} must be a datetime."
            )

        if value.tzinfo is None:
            raise MarketDataRequestError(
                f"{field_name} must be timezone "
                "aware."
            )

        milliseconds = int(
            value.timestamp()
            * 1000
        )

        if milliseconds < 0:
            raise MarketDataRequestError(
                f"{field_name} cannot precede the "
                "Unix epoch."
            )

        return milliseconds

    @staticmethod
    def _milliseconds_to_datetime(
        value: Any,
        *,
        field_name: str,
    ) -> datetime:
        try:
            milliseconds = int(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            raise InvalidCandleError(
                f"{field_name} must be an integer "
                "timestamp."
            ) from error

        if milliseconds < 0:
            raise InvalidCandleError(
                f"{field_name} cannot be negative."
            )

        try:
            return datetime.fromtimestamp(
                milliseconds / 1000,
                tz=UTC,
            )

        except (
            OverflowError,
            OSError,
            ValueError,
        ) as error:
            raise InvalidCandleError(
                f"{field_name} is outside the "
                "supported datetime range."
            ) from error

    @staticmethod
    def _optional_float(
        value: Any,
    ) -> float | None:
        try:
            normalized = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        if not math.isfinite(
            normalized
        ):
            return None

        return normalized

    @staticmethod
    def _optional_integer(
        value: Any,
    ) -> int | None:
        try:
            return int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return None
