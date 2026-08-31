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
- Classify open and closed candles against ONE explicit cutoff
- Validate OHLCV integrity
- Verify the ordering assumption without repairing it
- Collapse identical duplicate candles
- Fail closed on conflicting candles that share one identity
- Provide latest price and candle helpers

Temporal authority
------------------

The processor owns no clock. Closure is decided by
``atlas_finance.market_data.temporal.is_closed_at`` against the
explicit ``processing_cutoff`` supplied by MarketLoop, which reads the
processing clock once per cycle. There is no cutoff fallback: an
absent cutoff is a programming error, not an invitation to call now().

Ordering authority
------------------

MarketFeedService remains the canonical ordering authority. This
processor detects a violated ordering assumption and fails closed. It
never silently sorts input into a new authoritative sequence.

Ordering is judged on primary temporal order alone: the open time. Two
rows that share an open time share one exchange candle identity, so
they are a duplicate or a conflict question, never an ordering
question.

Binance Kline Layout
--------------------

Index 0  : Open time
Index 1  : Open
Index 2  : High
Index 3  : Low
Index 4  : Close
Index 5  : Volume
Index 6  : Close time
Index 7  : Quote asset volume
Index 8  : Number of trades
Index 9  : Taker buy base volume
Index 10 : Taker buy quote volume
Index 11 : Ignore

Indices 0 to 10 are market evidence and all participate in conflict
detection. Index 11 is the Binance filler field and carries no
established market meaning, so it is excluded.

============================================================
"""

from __future__ import annotations

import logging

from datetime import UTC
from datetime import datetime
from typing import Any

from atlas_finance.market_data.temporal import (
    is_closed_at,
    is_future_open_at,
    require_aware_utc,
    to_milliseconds,
)


logger = logging.getLogger(
    "AtlasAI.CandleProcessor"
)


class CandleContractError(
    Exception
):
    """
    Base failure for market-data contract violations that must fail
    closed for the affected symbol and cycle.
    """

    reason = "MARKET_DATA_CONTRACT"


class CandleConflictError(
    CandleContractError
):
    """
    Raised when one candle identity carries conflicting payloads.

    There is no first-wins, last-wins, or input-order-dependent
    winner: the cycle fails closed for that symbol.
    """

    reason = "MARKET_DATA_CONFLICT"


class CandleOrderingError(
    CandleContractError
):
    """
    Raised when input candles violate the ordering assumption owned by
    MarketFeedService. The processor does not repair the sequence.
    """

    reason = "MARKET_DATA_ORDERING"


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
            "future_candles_rejected": 0,
            "invalid_time_range_rejected": 0,
            "ordering_violations": 0,
            "conflicts_detected": 0,
        }

    # =====================================================
    # NORMALIZATION
    # =====================================================

    def normalize(
        self,
        candles: Any,
        *,
        processing_cutoff: datetime | int,
    ) -> list[dict[str, Any]]:
        """
        Normalize an iterable of exchange candles.

        Args:
            candles:
                Exchange candle payloads in provider order.
            processing_cutoff:
                The explicit cycle cutoff owned by MarketLoop, as an
                aware UTC datetime or epoch milliseconds. It is
                mandatory: the processor never reads a clock.

        Returns:
            Candles in their original provider order, oldest to
            newest, with identical duplicates collapsed.

        Raises:
            CandleOrderingError:
                Input violates the MarketFeedService ordering
                assumption.
            CandleConflictError:
                One candle identity carries conflicting payloads.
        """

        cutoff_ms = self._require_cutoff_milliseconds(
            processing_cutoff
        )

        if not candles:
            return []

        result: list[dict[str, Any]] = []

        for candle in candles:
            self.metrics["candles_received"] += 1

            try:
                normalized = self._parse(
                    candle,
                    cutoff_ms,
                )

                if normalized is None:
                    self.metrics["candles_rejected"] += 1
                    continue

                temporal_rejection = (
                    self._temporal_rejection(
                        normalized,
                        cutoff_ms,
                    )
                )

                if temporal_rejection is not None:
                    self.metrics["candles_rejected"] += 1
                    self.metrics[
                        temporal_rejection
                    ] += 1

                    logger.warning(
                        "Candle rejected (%s): open_time=%s "
                        "close_time=%s cutoff=%s",
                        temporal_rejection,
                        normalized.get("open_time"),
                        normalized.get("close_time"),
                        cutoff_ms,
                    )

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

        self._require_provider_ordering(
            result
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
        cutoff_ms: int,
    ) -> dict[str, Any] | None:
        if isinstance(
            candle,
            (list, tuple),
        ):
            return self._parse_sequence(
                candle,
                cutoff_ms,
            )

        if isinstance(
            candle,
            dict,
        ):
            return self._parse_mapping(
                candle,
                cutoff_ms,
            )

        logger.warning(
            "Unsupported candle type: %s",
            type(candle).__name__,
        )

        return None

    def _parse_sequence(
        self,
        candle: list[Any] | tuple[Any, ...],
        cutoff_ms: int,
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
            quote_volume=self._position(
                candle,
                7,
            ),
            trades=self._position(
                candle,
                8,
            ),
            taker_buy_base_volume=self._position(
                candle,
                9,
            ),
            taker_buy_quote_volume=self._position(
                candle,
                10,
            ),
            source="sequence",
            cutoff_ms=cutoff_ms,
        )

    @staticmethod
    def _position(
        candle: list[Any] | tuple[Any, ...],
        index: int,
    ) -> Any:
        """
        Return one legacy row position, or None when the row is short.

        A row that stops before the position genuinely does not carry
        that evidence. The absence is preserved rather than replaced
        with a neutral number.
        """

        if index >= len(
            candle
        ):
            return None

        return candle[index]

    def _parse_mapping(
        self,
        candle: dict[str, Any],
        cutoff_ms: int,
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
            quote_volume=self._first_value(
                candle,
                (
                    "quote_volume",
                    "quoteVolume",
                ),
            ),
            trades=self._first_value(
                candle,
                (
                    "trades",
                    "numberOfTrades",
                ),
            ),
            taker_buy_base_volume=self._first_value(
                candle,
                (
                    "taker_buy_base_volume",
                    "takerBuyBaseVolume",
                ),
            ),
            taker_buy_quote_volume=self._first_value(
                candle,
                (
                    "taker_buy_quote_volume",
                    "takerBuyQuoteVolume",
                ),
            ),
            source="mapping",
            cutoff_ms=cutoff_ms,
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
        quote_volume: Any,
        trades: Any,
        taker_buy_base_volume: Any,
        taker_buy_quote_volume: Any,
        source: str,
        cutoff_ms: int,
    ) -> dict[str, Any]:
        """
        Build one canonical candle.

        The four ``provider_metadata`` values are real exchange
        evidence, so they are carried for conflict detection: two rows
        that share an identity but disagree on trade count or quote
        volume are not the same candle. They are deliberately kept out
        of the top level because they are not analyzer, strategy, or
        brain inputs, and this change grants them no such authority.
        """

        is_closed = (
            close_time_ms is not None
            and is_closed_at(
                close_time_ms,
                cutoff_ms,
            )
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
            "provider_metadata": {
                "quote_volume": self._optional_float(
                    quote_volume
                ),
                "trades": self._optional_count(
                    trades
                ),
                "taker_buy_base_volume": self._optional_float(
                    taker_buy_base_volume
                ),
                "taker_buy_quote_volume": self._optional_float(
                    taker_buy_quote_volume
                ),
            },
        }

    @staticmethod
    def _optional_float(
        value: Any,
    ) -> float | None:
        """
        Return ``value`` as a float while preserving a real absence.

        None means the source did not carry the field, and it is never
        replaced with zero: zero volume is a market statement, not a
        missing one. A present but non-numeric value raises, so the
        candle is rejected instead of being quietly downgraded to
        "absent".
        """

        if value is None:
            return None

        return float(
            value
        )

    @staticmethod
    def _optional_count(
        value: Any,
    ) -> int | None:
        """
        Return ``value`` as a trade count while preserving absence.
        """

        if value is None:
            return None

        return int(
            value
        )

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
    # TEMPORAL CONTRACT
    # =====================================================

    @staticmethod
    def _require_cutoff_milliseconds(
        processing_cutoff: datetime | int,
    ) -> int:
        """
        Return the explicit cycle cutoff in epoch milliseconds.

        A missing cutoff is a programming error. It must never be
        substituted with a wall-clock read inside the processor.
        """

        if processing_cutoff is None:
            raise ValueError(
                "processing_cutoff is required. CandleProcessor owns "
                "no clock: MarketLoop must supply the cycle cutoff."
            )

        return to_milliseconds(
            processing_cutoff,
            field_name="processing_cutoff",
        )

    @staticmethod
    def _temporal_rejection(
        candle: dict[str, Any],
        cutoff_ms: int,
    ) -> str | None:
        """
        Return the metric name for a temporal violation, or None.

        Policy against one explicit cutoff:

        - open_time  >  cutoff              -> invalid future candle
        - close_time <  open_time           -> invalid range
        - open_time <= cutoff <  close_time -> valid, currently open
        - close_time <= cutoff              -> closed

        A close time in the future is not by itself invalid: the
        currently-open exchange candle normally has one.
        """

        open_time_ms = candle.get(
            "open_time"
        )

        close_time_ms = candle.get(
            "close_time"
        )

        if (
            open_time_ms is not None
            and close_time_ms is not None
            and close_time_ms < open_time_ms
        ):
            return "invalid_time_range_rejected"

        if (
            open_time_ms is not None
            and is_future_open_at(
                open_time_ms,
                cutoff_ms,
            )
        ):
            return "future_candles_rejected"

        return None

    # =====================================================
    # ORDERING ASSUMPTION
    # =====================================================

    def _require_provider_ordering(
        self,
        candles: list[dict[str, Any]],
    ) -> None:
        """
        Verify the provider ordering assumption without repairing it.

        MarketFeedService is the canonical ordering authority. When its
        guarantee is violated the cycle fails closed instead of the
        processor silently sorting input into a new sequence.

        Only primary temporal order is judged here. An equal open time
        is not disorder: it is one exchange candle arriving twice, and
        whether that is a duplicate or a conflict belongs to
        deduplication authority.
        """

        previous_key: int | None = None

        for candle in candles:
            current_key = self._ordering_key(
                candle
            )

            if (
                previous_key is not None
                and current_key < previous_key
            ):
                self.metrics["ordering_violations"] += 1

                raise CandleOrderingError(
                    "Candles are not ordered by open time: "
                    f"{current_key} follows {previous_key}. "
                    "MarketFeedService owns candle ordering; "
                    "CandleProcessor does not repair it."
                )

            previous_key = current_key

    # =====================================================
    # DEDUPLICATION
    # =====================================================

    def _deduplicate(
        self,
        candles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Keep one candle for every exchange candle identity.

        Identical payloads collapse idempotently. Conflicting payloads
        that share one identity fail closed: there is no first-wins,
        last-wins, or input-order-dependent winner, so the outcome
        cannot depend on the order the conflict arrives in.
        """

        unique: dict[str, dict[str, Any]] = {}
        fingerprints: dict[str, tuple[Any, ...]] = {}

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

            fingerprint = self._payload_fingerprint(
                candle
            )

            if identity in unique:
                if fingerprints[identity] != fingerprint:
                    self.metrics["conflicts_detected"] += 1

                    raise CandleConflictError(
                        "Conflicting payloads share candle identity "
                        f"{identity}. Market data is ambiguous and "
                        "cannot be resolved by input order."
                    )

                self.metrics["duplicates_removed"] += 1

                continue

            unique[identity] = candle
            fingerprints[identity] = fingerprint

        return list(
            unique.values()
        )

    @staticmethod
    def _payload_fingerprint(
        candle: dict[str, Any],
    ) -> tuple[Any, ...]:
        """
        Return the comparable market payload of a normalized candle.

        Every legacy row position that carries market evidence takes
        part: the two timestamps, OHLCV, and the quote volume, trade
        count and taker-buy volumes. Disagreement on any of them means
        two different statements about one exchange candle, which is a
        conflict rather than a duplicate.

        Excluded are the Binance index 11 filler field, which has no
        established market meaning; parse provenance, so the same
        candle delivered as a sequence and as a mapping is a duplicate;
        and derived fields, which are pure functions of the values
        compared here and the cycle cutoff.
        """

        metadata = (
            candle.get(
                "provider_metadata"
            )
            or {}
        )

        return (
            candle.get("open_time"),
            candle.get("close_time"),
            candle.get("open"),
            candle.get("high"),
            candle.get("low"),
            candle.get("close"),
            candle.get("volume"),
            metadata.get("quote_volume"),
            metadata.get("trades"),
            metadata.get("taker_buy_base_volume"),
            metadata.get("taker_buy_quote_volume"),
        )

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
        """
        Convert a supported wire timestamp into epoch milliseconds.

        Datetimes are delegated to the temporal authority, so naive
        values are rejected rather than interpreted. Numeric seconds
        are still accepted because the legacy exchange row contract
        carries both second and millisecond epochs.
        """

        if value is None:
            return None

        if isinstance(
            value,
            datetime,
        ):
            return to_milliseconds(
                require_aware_utc(
                    value
                )
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

        return to_milliseconds(
            require_aware_utc(
                parsed
            )
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
    def _ordering_key(
        candle: dict[str, Any],
    ) -> int:
        """
        Return the primary temporal position of a candle.

        Open time alone decides order. Close time is deliberately not a
        tiebreaker: two rows sharing an open time share one exchange
        candle identity, so a close-time disagreement between them is
        ambiguous evidence about one candle, not a sequence defect. A
        close-time tiebreaker would report that same input as
        MARKET_DATA_ORDERING in one arrival order and
        MARKET_DATA_CONFLICT in the other.
        """

        open_time = candle.get(
            "open_time"
        )

        if open_time is not None:
            return int(
                open_time
            )

        return int(
            candle.get(
                "close_time"
            )
            or 0
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