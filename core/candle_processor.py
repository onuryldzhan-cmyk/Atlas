"""
============================================================
ATLAS CANDLE PROCESSOR v3.0
============================================================

Institutional Candle Normalization Layer

Responsibilities
----------------

- Normalize Binance list candles
- Normalize dictionary candles
- Preserve exchange candle timestamps
- Detect open and closed candles
- Validate OHLCV integrity
- Sort candles chronologically
- Remove duplicate candles
- Provide latest price and candle helpers

Binance Kline Layout
--------------------

Index 0  : Open time
Index 1  : Open
Index 2  : High
Index 3  : Low
Index 4  : Close
Index 5  : Volume
Index 6  : Close time

============================================================
"""

from __future__ import annotations

import logging
import time

from datetime import UTC
from datetime import datetime
from typing import Any


logger = logging.getLogger(
    "AtlasAI.CandleProcessor"
)


class CandleProcessor:
    """
    Convert exchange candle payloads into the canonical
    Atlas candle contract.
    """

    VERSION = "3.0"

    NAME = "CandleProcessor"

    REQUIRED_FIELDS = (
        "open",
        "high",
        "low",
        "close",
        "volume",
    )

    # =====================================================
    # INIT
    # =====================================================

    def __init__(self) -> None:
        self.version = self.VERSION

        self.metrics: dict[str, int] = {
            "candles_received": 0,
            "candles_normalized": 0,
            "candles_rejected": 0,
            "duplicates_removed": 0,
        }

    # =====================================================
    # NORMALIZATION
    # =====================================================

    def normalize(
        self,
        candles: Any,
    ) -> list[dict[str, Any]]:
        """
        Normalize an iterable of exchange candles.

        Returns candles ordered from oldest to newest.
        """

        if not candles:
            return []

        result: list[dict[str, Any]] = []

        for candle in candles:
            self.metrics["candles_received"] += 1

            try:
                normalized = self._parse(
                    candle
                )

                if normalized is None:
                    self.metrics["candles_rejected"] += 1
                    continue

                if not self._is_valid(
                    normalized
                ):
                    self.metrics["candles_rejected"] += 1
                    continue

                result.append(
                    normalized
                )

                self.metrics["candles_normalized"] += 1

            except (
                TypeError,
                ValueError,
                KeyError,
                IndexError,
            ) as exc:
                self.metrics["candles_rejected"] += 1

                logger.warning(
                    "Candle rejected: %s",
                    exc,
                )

            except Exception:
                self.metrics["candles_rejected"] += 1

                logger.exception(
                    "Unexpected candle normalization error"
                )

        result.sort(
            key=self._sort_key
        )

        return self._deduplicate(
            result
        )

    # =====================================================
    # PARSER
    # =====================================================

    def _parse(
        self,
        candle: Any,
    ) -> dict[str, Any] | None:
        if isinstance(
            candle,
            (list, tuple),
        ):
            return self._parse_sequence(
                candle
            )

        if isinstance(
            candle,
            dict,
        ):
            return self._parse_mapping(
                candle
            )

        logger.warning(
            "Unsupported candle type: %s",
            type(candle).__name__,
        )

        return None

    def _parse_sequence(
        self,
        candle: list[Any] | tuple[Any, ...],
    ) -> dict[str, Any]:
        """
        Parse Binance-compatible kline sequence.
        """

        if len(candle) < 6:
            raise ValueError(
                "Sequence candle requires at least 6 fields"
            )

        open_time_ms = self._to_milliseconds(
            candle[0]
        )

        close_time_ms: int | None = None

        if len(candle) > 6:
            close_time_ms = self._to_milliseconds(
                candle[6]
            )

        if close_time_ms is None and open_time_ms is not None:
            close_time_ms = open_time_ms

        return self._build_candle(
            open_time_ms=open_time_ms,
            close_time_ms=close_time_ms,
            open_price=candle[1],
            high_price=candle[2],
            low_price=candle[3],
            close_price=candle[4],
            volume=candle[5],
            source="sequence",
        )

    def _parse_mapping(
        self,
        candle: dict[str, Any],
    ) -> dict[str, Any]:
        open_time_value = self._first_value(
            candle,
            (
                "open_time",
                "openTime",
                "start_time",
                "startTime",
                "timestamp",
                "time",
            ),
        )

        close_time_value = self._first_value(
            candle,
            (
                "close_time",
                "closeTime",
                "end_time",
                "endTime",
            ),
        )

        open_time_ms = self._to_milliseconds(
            open_time_value
        )

        close_time_ms = self._to_milliseconds(
            close_time_value
        )

        if close_time_ms is None:
            close_time_ms = open_time_ms

        return self._build_candle(
            open_time_ms=open_time_ms,
            close_time_ms=close_time_ms,
            open_price=candle["open"],
            high_price=candle["high"],
            low_price=candle["low"],
            close_price=candle["close"],
            volume=candle.get(
                "volume",
                0,
            ),
            source="mapping",
        )

    # =====================================================
    # CANONICAL CANDLE
    # =====================================================

    def _build_candle(
        self,
        *,
        open_time_ms: int | None,
        close_time_ms: int | None,
        open_price: Any,
        high_price: Any,
        low_price: Any,
        close_price: Any,
        volume: Any,
        source: str,
    ) -> dict[str, Any]:
        now_ms = int(
            time.time() * 1000
        )

        is_closed = (
            close_time_ms is not None
            and close_time_ms <= now_ms
        )

        timestamp_ms = (
            open_time_ms
            if open_time_ms is not None
            else close_time_ms
        )

        return {
            "timestamp": self._milliseconds_to_iso(
                timestamp_ms
            ),
            "open_time": open_time_ms,
            "close_time": close_time_ms,
            "open_time_iso": self._milliseconds_to_iso(
                open_time_ms
            ),
            "close_time_iso": self._milliseconds_to_iso(
                close_time_ms
            ),
            "is_closed": is_closed,
            "open": float(
                open_price
            ),
            "high": float(
                high_price
            ),
            "low": float(
                low_price
            ),
            "close": float(
                close_price
            ),
            "volume": float(
                volume or 0
            ),
            "source": source,
        }

    # =====================================================
    # VALIDATION
    # =====================================================

    def _is_valid(
        self,
        candle: dict[str, Any],
    ) -> bool:
        for field_name in self.REQUIRED_FIELDS:
            if field_name not in candle:
                return False

        open_price = float(
            candle["open"]
        )
        high_price = float(
            candle["high"]
        )
        low_price = float(
            candle["low"]
        )
        close_price = float(
            candle["close"]
        )
        volume = float(
            candle["volume"]
        )

        if (
            open_price <= 0
            or high_price <= 0
            or low_price <= 0
            or close_price <= 0
        ):
            return False

        if high_price < low_price:
            return False

        if high_price < max(
            open_price,
            close_price,
        ):
            return False

        if low_price > min(
            open_price,
            close_price,
        ):
            return False

        if volume < 0:
            return False

        return True

    # =====================================================
    # DEDUPLICATION
    # =====================================================

    def _deduplicate(
        self,
        candles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Keep one candle for every exchange candle identity.

        The latest occurrence wins when duplicate data exists.
        """

        unique: dict[str, dict[str, Any]] = {}

        for index, candle in enumerate(
            candles
        ):
            identity = self.candle_identity(
                candle
            )

            if identity is None:
                identity = (
                    f"fallback:{index}:"
                    f"{candle.get('timestamp')}"
                )

            if identity in unique:
                self.metrics["duplicates_removed"] += 1

            unique[identity] = candle

        result = list(
            unique.values()
        )

        result.sort(
            key=self._sort_key
        )

        return result

    # =====================================================
    # CANDLE IDENTITY
    # =====================================================

    @staticmethod
    def candle_identity(
        candle: dict[str, Any] | None,
    ) -> str | None:
        """
        Return a stable exchange candle identity.
        """

        if not isinstance(
            candle,
            dict,
        ):
            return None

        open_time = candle.get(
            "open_time"
        )

        if open_time is not None:
            return f"open:{open_time}"

        close_time = candle.get(
            "close_time"
        )

        if close_time is not None:
            return f"close:{close_time}"

        timestamp = candle.get(
            "timestamp"
        )

        if timestamp:
            return f"timestamp:{timestamp}"

        return None

    # =====================================================
    # CLOSED-CANDLE HELPERS
    # =====================================================

    @staticmethod
    def closed_candles(
        candles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            candle
            for candle in candles
            if bool(
                candle.get(
                    "is_closed",
                    False,
                )
            )
        ]

    @classmethod
    def latest_closed_candle(
        cls,
        candles: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        closed = cls.closed_candles(
            candles
        )

        if not closed:
            return None

        return closed[-1]

    @classmethod
    def latest_closed_identity(
        cls,
        candles: list[dict[str, Any]],
    ) -> str | None:
        candle = cls.latest_closed_candle(
            candles
        )

        return cls.candle_identity(
            candle
        )

    # =====================================================
    # MARKET HELPERS
    # =====================================================

    @staticmethod
    def latest_price(
        candles: list[dict[str, Any]],
    ) -> float | None:
        if not candles:
            return None

        return float(
            candles[-1]["close"]
        )

    @staticmethod
    def latest_closed_price(
        candles: list[dict[str, Any]],
    ) -> float | None:
        candle = CandleProcessor.latest_closed_candle(
            candles
        )

        if candle is None:
            return None

        return float(
            candle["close"]
        )

    @staticmethod
    def candle_count(
        candles: list[dict[str, Any]],
    ) -> int:
        return len(
            candles
        )

    # =====================================================
    # TIME HELPERS
    # =====================================================

    @staticmethod
    def _to_milliseconds(
        value: Any,
    ) -> int | None:
        if value is None:
            return None

        if isinstance(
            value,
            datetime,
        ):
            if value.tzinfo is None:
                value = value.replace(
                    tzinfo=UTC
                )

            return int(
                value.timestamp() * 1000
            )

        if isinstance(
            value,
            (int, float),
        ):
            numeric = float(
                value
            )

            # Seconds are normally around 1.7 billion.
            # Milliseconds are normally around 1.7 trillion.
            if abs(
                numeric
            ) < 100_000_000_000:
                numeric *= 1000

            return int(
                numeric
            )

        text = str(
            value
        ).strip()

        if not text:
            return None

        try:
            numeric = float(
                text
            )

            if abs(
                numeric
            ) < 100_000_000_000:
                numeric *= 1000

            return int(
                numeric
            )

        except ValueError:
            pass

        normalized_text = text.replace(
            "Z",
            "+00:00",
        )

        parsed = datetime.fromisoformat(
            normalized_text
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=UTC
            )

        return int(
            parsed.timestamp() * 1000
        )

    @staticmethod
    def _milliseconds_to_iso(
        value: int | None,
    ) -> str | None:
        if value is None:
            return None

        return datetime.fromtimestamp(
            value / 1000,
            tz=UTC,
        ).isoformat()

    @staticmethod
    def _first_value(
        source: dict[str, Any],
        keys: tuple[str, ...],
    ) -> Any:
        for key in keys:
            if key in source:
                value = source.get(
                    key
                )

                if value is not None:
                    return value

        return None

    @staticmethod
    def _sort_key(
        candle: dict[str, Any],
    ) -> tuple[int, int]:
        open_time = candle.get(
            "open_time"
        )

        close_time = candle.get(
            "close_time"
        )

        primary = (
            int(open_time)
            if open_time is not None
            else int(close_time or 0)
        )

        secondary = int(
            close_time or 0
        )

        return (
            primary,
            secondary,
        )

    # =====================================================
    # DIAGNOSTICS
    # =====================================================

    def health(
        self,
    ) -> dict[str, Any]:
        return {
            "name": self.NAME,
            "version": self.VERSION,
            "status": "HEALTHY",
            "metrics": dict(
                self.metrics
            ),
        }