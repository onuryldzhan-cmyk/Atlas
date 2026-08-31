"""
============================================================
ATLAS MARKET DATA TEMPORAL AUTHORITY v1.0.0
============================================================

Project Atlas AI

Pure temporal semantics for the live/PAPER market-data path.

Responsibilities
----------------
- require_aware_utc : reject naive datetimes, normalize aware to UTC
- to_milliseconds   : exact epoch-millisecond conversion
- is_closed_at      : pure candle-closure decision
- is_future_open_at : pure future-data detection

Design rules
------------
- No wall-clock reads. Every decision needs an explicit cutoff.
- No local-time interpretation. Naive datetimes are rejected.
- No seconds/milliseconds guessing. Integers are epoch milliseconds.
- Deterministic: identical inputs always produce identical outputs.
- The exact cutoff is inclusive: close_time == cutoff is CLOSED.

This module is intentionally minimal. It is temporal vocabulary for
market data, not a general datetime framework.

============================================================
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime


MILLISECONDS_PER_SECOND = 1000

EPOCH = datetime(
    1970,
    1,
    1,
    tzinfo=UTC,
)


class TemporalContractError(
    ValueError
):
    """
    Raised when a temporal value violates the Atlas market-data
    temporal contract.
    """


def require_aware_utc(
    value: datetime,
    *,
    field_name: str = "timestamp",
) -> datetime:
    """
    Return ``value`` normalized to UTC.

    Naive datetimes are rejected instead of being interpreted, so the
    host timezone can never influence a normalized timestamp.
    """

    if not isinstance(
        value,
        datetime,
    ):
        raise TemporalContractError(
            f"{field_name} must be a datetime, "
            f"received {type(value).__name__}."
        )

    offset = (
        value.tzinfo.utcoffset(
            value
        )
        if value.tzinfo is not None
        else None
    )

    if offset is None:
        raise TemporalContractError(
            f"{field_name} must be timezone-aware. Naive datetimes "
            "are rejected because local-time interpretation is not "
            "an Atlas market-data contract."
        )

    return value.astimezone(
        UTC
    )


def to_milliseconds(
    value: datetime | int,
    *,
    field_name: str = "timestamp",
) -> int:
    """
    Return the epoch-millisecond representation of ``value``.

    Supported inputs
    ----------------
    - timezone-aware datetime (normalized to UTC)
    - int already expressed in epoch milliseconds

    No unit guessing is performed. Floats, strings, booleans and naive
    datetimes are rejected.
    """

    if isinstance(
        value,
        bool,
    ):
        raise TemporalContractError(
            f"{field_name} must not be a boolean."
        )

    if isinstance(
        value,
        datetime,
    ):
        aware = require_aware_utc(
            value,
            field_name=field_name,
        )

        elapsed = aware - EPOCH

        return (
            elapsed.days
            * 86_400
            * MILLISECONDS_PER_SECOND
            + elapsed.seconds
            * MILLISECONDS_PER_SECOND
            + elapsed.microseconds
            // 1000
        )

    if isinstance(
        value,
        int,
    ):
        return value

    raise TemporalContractError(
        f"{field_name} must be an aware datetime or epoch "
        f"milliseconds, received {type(value).__name__}."
    )


def is_closed_at(
    close_time: datetime | int,
    processing_cutoff: datetime | int,
) -> bool:
    """
    Return whether a candle is closed at the given processing cutoff.

    Closure is a pure function of the candle close time and one
    explicit cutoff. The exact cutoff is inclusive:
    ``close_time == processing_cutoff`` is CLOSED.
    """

    return to_milliseconds(
        close_time,
        field_name="close_time",
    ) <= to_milliseconds(
        processing_cutoff,
        field_name="processing_cutoff",
    )


def is_future_open_at(
    open_time: datetime | int,
    processing_cutoff: datetime | int,
) -> bool:
    """
    Return whether a candle opens after the given processing cutoff.

    A future close time is normal for the currently-open exchange
    candle. A future OPEN time is invalid market data.
    """

    return to_milliseconds(
        open_time,
        field_name="open_time",
    ) > to_milliseconds(
        processing_cutoff,
        field_name="processing_cutoff",
    )


__all__ = [
    "EPOCH",
    "MILLISECONDS_PER_SECOND",
    "TemporalContractError",
    "is_closed_at",
    "is_future_open_at",
    "require_aware_utc",
    "to_milliseconds",
]
