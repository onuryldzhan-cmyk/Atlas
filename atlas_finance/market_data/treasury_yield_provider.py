"""
============================================================
ATLAS TREASURY YIELD PROVIDER v1.0.0
============================================================

Project Atlas AI

Public, read-only provider for the US Treasury Daily Par Yield Curve, the
macro input authorized by registry v4.79
(GRANT-BACKLOG001-MACRO-RISK-IMPLEMENTATION). It mirrors
``fear_greed_provider.py`` (registry v4.66) deliberately: same cache, retry,
freshness and fail-closed shape.

Responsibilities
----------------
- Fetch the current calendar year's daily yield-curve CSV (standard library
  only, no API key) and, only when that year does not yet hold enough rows
  for the lookback (early January), the previous year's CSV from the same
  endpoint
- Validate every row strictly before any value is ever reported
- Cache the result so the network is contacted at most once per refresh
  interval, never once per market cycle
- Refuse a curve whose latest row is older than the stale ceiling
- Classify the 10-year yield's move over the lookback as RISING / FALLING /
  FLAT

Fail-closed contract
--------------------
``get_reading()`` never raises and never invents a number. A network error,
timeout, non-200 status, oversized body, malformed CSV, missing column, a
row with an unparseable date or yield, an out-of-order or duplicated date,
too few rows for the lookback, a future date, a stale curve or any
unexpected exception yields ``available=False`` with no values and a reason
code. A failed refresh never falls back to an older value.

Data shape (verified live 2026-09-25)
-------------------------------------
``text/csv``; header ``Date,"1 Mo",...,"2 Yr",...,"10 Yr",...``; one row per
US business day, newest first; dates ``MM/DD/YYYY``; yields in percent with
two decimals. Only the ``2 Yr`` and ``10 Yr`` columns are read. Because the
yields carry exactly two decimals they are parsed as ``Decimal`` and every
derived quantity is an exact whole number of basis points.

Freshness
---------
The curve is published once per US business day, after the close. A
weekend plus a holiday plus publication lag can leave the newest row
several calendar days old in normal operation (e.g. Wednesday's row is
still the newest on the following Tuesday morning UTC around
Thanksgiving), so the ceiling is 7 calendar days, measured on the row's own
date, not on when Atlas fetched it.

Architecture
------------
Layer L2 (``atlas_finance/*``). Consumed by ``core/market_loop.py`` (L3),
which passes plain values - never this object - to
``analysis/world_analysis_engine.py`` (L4). L4 must never import this module;
that would be the forbidden L4 -> L2 edge.

Security boundary
-----------------
This provider:

- Does not require an API key or read any secret
- Sends unauthenticated HTTPS GETs to one fixed public endpoint
- Cannot place orders, access capital, or modify positions

Data source: U.S. Department of the Treasury, Daily Treasury Par Yield Curve
Rates (https://home.treasury.gov/resource-center/data-chart-center/interest-rates).

============================================================
"""

from __future__ import annotations

import csv
import io
import logging
import re
import threading
import urllib.error
import urllib.request

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final


logger = logging.getLogger(
    "AtlasAI.TreasuryYieldProvider"
)


TREASURY_YIELD_ENDPOINT_TEMPLATE: Final[str] = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value={year}"
    "&page&_format=csv"
)

TEN_YEAR_COLUMN: Final[str] = "10 Yr"
TWO_YEAR_COLUMN: Final[str] = "2 Yr"
DATE_COLUMN: Final[str] = "Date"

# The 10-year move is measured over this many trading days (rows), i.e.
# roughly one calendar month.
LOOKBACK_TRADING_DAYS: Final[int] = 20

# Longest calendar span the 20-row lookback may cover before rows are
# considered missing (20 business days = 28 calendar days, plus room for
# up to several market holidays).
MAX_LOOKBACK_SPAN: Final[timedelta] = timedelta(days=35)

# Move classification (owner-approved, registry v4.79). A 10-year move of at
# least +25bp over the lookback is RISING; at most -25bp is FALLING;
# everything strictly between is FLAT.
MOVE_THRESHOLD_BP: Final[int] = 25

MOVE_RISING: Final[str] = "RISING"
MOVE_FALLING: Final[str] = "FALLING"
MOVE_FLAT: Final[str] = "FLAT"

DEFAULT_REFRESH_INTERVAL: Final[timedelta] = timedelta(hours=6)
DEFAULT_RETRY_INTERVAL: Final[timedelta] = timedelta(minutes=15)
DEFAULT_MAX_AGE: Final[timedelta] = timedelta(days=7)
DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0

# A full calendar year is ~250 rows of ~85 bytes (~21 KiB). Anything near
# this cap is not the documented response and is refused before parsing.
MAX_RESPONSE_BYTES: Final[int] = 256 * 1024
MAX_ROWS: Final[int] = 400

# Plausibility bounds for a US Treasury par yield, in percent. Negative
# yields are admitted down to a small floor; nothing outside is trusted.
MIN_YIELD_PERCENT: Final[Decimal] = Decimal("-5")
MAX_YIELD_PERCENT: Final[Decimal] = Decimal("25")

_DATE_PATTERN = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
_YIELD_PATTERN = re.compile(r"-?[0-9]{1,2}(\.[0-9]{1,2})?")


# Reason codes. Every unavailable reading carries exactly one.
REASON_OK: Final[str] = "OK"
REASON_NETWORK_ERROR: Final[str] = "NETWORK_ERROR"
REASON_TIMEOUT: Final[str] = "TIMEOUT"
REASON_HTTP_ERROR: Final[str] = "HTTP_ERROR"
REASON_RESPONSE_TOO_LARGE: Final[str] = "RESPONSE_TOO_LARGE"
REASON_MALFORMED_RESPONSE: Final[str] = "MALFORMED_RESPONSE"
REASON_MISSING_FIELD: Final[str] = "MISSING_FIELD"
REASON_VALUE_OUT_OF_RANGE: Final[str] = "VALUE_OUT_OF_RANGE"
REASON_INSUFFICIENT_HISTORY: Final[str] = "INSUFFICIENT_HISTORY"
REASON_LOOKBACK_SPAN_EXCEEDED: Final[str] = "LOOKBACK_SPAN_EXCEEDED"
REASON_FUTURE_TIMESTAMP: Final[str] = "FUTURE_TIMESTAMP"
REASON_STALE: Final[str] = "STALE"
REASON_UNEXPECTED_ERROR: Final[str] = "UNEXPECTED_ERROR"


Transport = Callable[[str, float], bytes]


class TreasuryYieldResponseError(ValueError):
    """A fetched response failed validation. ``reason`` is a reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


class _TransportError(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class YieldCurveRow:
    """One validated CSV row: the 2-year and 10-year par yields, in percent."""

    observed_date: date
    two_year: Decimal
    ten_year: Decimal


@dataclass(frozen=True)
class TreasuryYieldReading:
    """One provider answer. Every value is None whenever ``available`` is False.

    ``ten_year_change_bp`` is the latest 10-year yield minus the 10-year
    yield ``LOOKBACK_TRADING_DAYS`` rows earlier; ``curve_spread_bp`` is the
    latest 10-year minus 2-year yield. Both are exact whole basis points.
    """

    available: bool
    observed_date: date | None
    lookback_date: date | None
    ten_year_yield: Decimal | None
    two_year_yield: Decimal | None
    ten_year_change_bp: int | None
    curve_spread_bp: int | None
    fetched_at: datetime | None
    reason: str

    @classmethod
    def unavailable(
        cls,
        reason: str,
        fetched_at: datetime | None = None,
    ) -> TreasuryYieldReading:
        return cls(
            available=False,
            observed_date=None,
            lookback_date=None,
            ten_year_yield=None,
            two_year_yield=None,
            ten_year_change_bp=None,
            curve_spread_bp=None,
            fetched_at=fetched_at,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def classify_ten_year_move(change_bp: Any) -> str:
    """Map a 10-year move in whole basis points to RISING, FALLING or FLAT.

    Raises ValueError for anything that is not exactly an ``int``.
    Subclasses (bool, IntEnum, ...) are rejected too, so only the plain
    number this module itself produces can be classified.
    """

    if type(change_bp) is not int:
        raise ValueError(
            f"ten-year change must be an int of basis points, got {change_bp!r}"
        )

    if change_bp >= MOVE_THRESHOLD_BP:
        return MOVE_RISING

    if change_bp <= -MOVE_THRESHOLD_BP:
        return MOVE_FALLING

    return MOVE_FLAT


def _basis_points(value: Decimal) -> int:
    scaled = value * 100
    integral = int(scaled)
    if Decimal(integral) != scaled:
        # Unreachable for two-decimal inputs; refuse rather than round.
        raise TreasuryYieldResponseError(
            REASON_MALFORMED_RESPONSE, "yield difference is not whole basis points"
        )
    return integral


def _strict_yield(raw: str, column: str) -> Decimal:
    if not isinstance(raw, str) or not _YIELD_PATTERN.fullmatch(raw):
        if raw == "":
            raise TreasuryYieldResponseError(REASON_MISSING_FIELD, column)
        raise TreasuryYieldResponseError(
            REASON_MALFORMED_RESPONSE, f"{column} is not a two-decimal yield"
        )

    value = Decimal(raw)
    if not MIN_YIELD_PERCENT <= value <= MAX_YIELD_PERCENT:
        raise TreasuryYieldResponseError(
            REASON_VALUE_OUT_OF_RANGE, f"{column} {raw} is implausible"
        )
    return value


def _strict_date(raw: str) -> date:
    match = _DATE_PATTERN.fullmatch(raw) if isinstance(raw, str) else None
    if match is None:
        raise TreasuryYieldResponseError(
            REASON_MALFORMED_RESPONSE, "date is not MM/DD/YYYY"
        )
    month, day, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        raise TreasuryYieldResponseError(
            REASON_MALFORMED_RESPONSE, "date is not a calendar date"
        ) from None


def parse_treasury_yield_csv(
    body: bytes,
    *,
    expected_year: int,
) -> list[YieldCurveRow]:
    """Validate one year's CSV body and return its rows, newest first.

    Raises TreasuryYieldResponseError on any deviation from the documented
    shape. It never substitutes a default for a missing or bad field. A
    header-only body (a year with no business days published yet) is valid
    and returns an empty list.
    """

    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise TreasuryYieldResponseError(
            REASON_MALFORMED_RESPONSE, "not UTF-8"
        ) from None

    try:
        records = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error:
        raise TreasuryYieldResponseError(
            REASON_MALFORMED_RESPONSE, "not valid CSV"
        ) from None

    records = [record for record in records if record]
    if not records:
        raise TreasuryYieldResponseError(REASON_MALFORMED_RESPONSE, "empty body")

    header = records[0]
    if not header or header[0] != DATE_COLUMN:
        raise TreasuryYieldResponseError(
            REASON_MALFORMED_RESPONSE, "first column is not Date"
        )

    for column in (TWO_YEAR_COLUMN, TEN_YEAR_COLUMN):
        if header.count(column) != 1:
            raise TreasuryYieldResponseError(REASON_MISSING_FIELD, column)

    two_index = header.index(TWO_YEAR_COLUMN)
    ten_index = header.index(TEN_YEAR_COLUMN)

    data = records[1:]
    if len(data) > MAX_ROWS:
        raise TreasuryYieldResponseError(
            REASON_MALFORMED_RESPONSE, f"more than {MAX_ROWS} rows"
        )

    rows: list[YieldCurveRow] = []
    for record in data:
        if len(record) != len(header):
            raise TreasuryYieldResponseError(
                REASON_MALFORMED_RESPONSE, "row width differs from header"
            )

        observed = _strict_date(record[0])
        if observed.year != expected_year:
            raise TreasuryYieldResponseError(
                REASON_MALFORMED_RESPONSE, "row is outside the requested year"
            )

        if rows and not observed < rows[-1].observed_date:
            raise TreasuryYieldResponseError(
                REASON_MALFORMED_RESPONSE, "dates are not strictly newest-first"
            )

        rows.append(
            YieldCurveRow(
                observed_date=observed,
                two_year=_strict_yield(record[two_index], TWO_YEAR_COLUMN),
                ten_year=_strict_yield(record[ten_index], TEN_YEAR_COLUMN),
            )
        )

    return rows


def _urllib_transport(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/csv",
            "User-Agent": "AtlasAI-TreasuryYieldProvider/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status != 200:
                raise _TransportError(REASON_HTTP_ERROR, f"HTTP status {status}")
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise _TransportError(
            REASON_HTTP_ERROR, f"HTTP status {error.code}"
        ) from None
    except TimeoutError:
        raise _TransportError(REASON_TIMEOUT, "request timed out") from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise _TransportError(REASON_TIMEOUT, "request timed out") from None
        raise _TransportError(
            REASON_NETWORK_ERROR, type(error.reason).__name__
        ) from None
    except OSError as error:
        raise _TransportError(
            REASON_NETWORK_ERROR, type(error).__name__
        ) from None

    if len(body) > MAX_RESPONSE_BYTES:
        raise _TransportError(
            REASON_RESPONSE_TOO_LARGE, f"body exceeds {MAX_RESPONSE_BYTES} bytes"
        )

    return body


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class TreasuryYieldProvider:
    """Cached, fail-closed access to the daily 2Y/10Y Treasury par yields.

    The network is contacted only when the last attempt is older than the
    refresh interval (after a success) or the retry interval (after a
    failure). In between, the cached outcome is returned: a cached value is
    re-checked for staleness on every call, and a cached failure stays a
    failure. Construction performs no I/O.
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        clock: Callable[[], datetime] | None = None,
        endpoint_template: str = TREASURY_YIELD_ENDPOINT_TEMPLATE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        refresh_interval: timedelta = DEFAULT_REFRESH_INTERVAL,
        retry_interval: timedelta = DEFAULT_RETRY_INTERVAL,
        max_age: timedelta = DEFAULT_MAX_AGE,
    ) -> None:
        # None means the real urllib transport, resolved at fetch time
        # rather than bound here, so the test suite's network guard
        # (repository-root conftest.py) covers every instance no matter
        # when it was constructed.
        self._transport = transport
        self._clock = clock if clock is not None else _utc_now
        self._endpoint_template = endpoint_template
        self._timeout_seconds = float(timeout_seconds)
        self._refresh_interval = refresh_interval
        self._retry_interval = retry_interval
        self._max_age = max_age

        self._lock = threading.Lock()
        self._last_attempt_at: datetime | None = None
        self._last_outcome: TreasuryYieldReading | None = None
        self.fetch_count = 0

    def get_reading(self) -> TreasuryYieldReading:
        """Return the current reading. Never raises."""

        try:
            with self._lock:
                now = self._clock()

                if self._fetch_due(now):
                    self._last_outcome = self._fetch(now)
                    self._last_attempt_at = now

                return self._checked(self._last_outcome, now)
        except Exception:
            logger.exception(
                "Treasury yield provider failed unexpectedly; reporting unavailable"
            )
            return TreasuryYieldReading.unavailable(REASON_UNEXPECTED_ERROR)

    # -----------------------------------------------------------------

    def _fetch_due(self, now: datetime) -> bool:
        if self._last_attempt_at is None or self._last_outcome is None:
            return True

        # A clock that moved backwards makes the elapsed time meaningless;
        # refetching is the only choice that cannot extend a cached value.
        if now < self._last_attempt_at:
            return True

        interval = (
            self._refresh_interval
            if self._last_outcome.available
            else self._retry_interval
        )
        return now - self._last_attempt_at >= interval

    def _fetch_year(self, year: int) -> list[YieldCurveRow]:
        self.fetch_count += 1

        transport = (
            self._transport
            if self._transport is not None
            else _urllib_transport
        )

        body = transport(
            self._endpoint_template.format(year=year),
            self._timeout_seconds,
        )
        if not isinstance(body, (bytes, bytearray)):
            raise TreasuryYieldResponseError(
                REASON_MALFORMED_RESPONSE, "transport returned non-bytes"
            )
        if len(body) > MAX_RESPONSE_BYTES:
            raise _TransportError(
                REASON_RESPONSE_TOO_LARGE,
                f"body exceeds {MAX_RESPONSE_BYTES} bytes",
            )
        return parse_treasury_yield_csv(bytes(body), expected_year=year)

    def _fetch(self, now: datetime) -> TreasuryYieldReading:
        needed = LOOKBACK_TRADING_DAYS + 1

        try:
            year = now.astimezone(UTC).year
            rows = self._fetch_year(year)

            # Early January: the current year cannot hold a full lookback
            # yet, so the previous year's file from the same endpoint
            # supplies the older rows. Only a genuinely young year
            # qualifies (no rows yet, or every row dated in January); a
            # short file later in the year is a truncated response, not a
            # year boundary, and must not be spliced onto last year.
            if len(rows) < needed and (
                not rows or rows[-1].observed_date.month == 1
            ):
                rows = rows + self._fetch_year(year - 1)

            if len(rows) < needed:
                raise TreasuryYieldResponseError(
                    REASON_INSUFFICIENT_HISTORY,
                    f"{len(rows)} rows, {needed} required",
                )

            latest = rows[0]
            lookback = rows[LOOKBACK_TRADING_DAYS]

            # 20 trading days span ~28 calendar days, a little more around
            # holidays. A longer span means rows are missing, so the move
            # would silently describe a different period: refused.
            span = latest.observed_date - lookback.observed_date
            if span > MAX_LOOKBACK_SPAN:
                raise TreasuryYieldResponseError(
                    REASON_LOOKBACK_SPAN_EXCEEDED,
                    f"lookback spans {span.days} calendar days",
                )
            change_bp = _basis_points(latest.ten_year - lookback.ten_year)
            spread_bp = _basis_points(latest.ten_year - latest.two_year)
        except (TreasuryYieldResponseError, _TransportError) as error:
            logger.warning(
                "Treasury yield fetch unavailable: %s", error
            )
            return TreasuryYieldReading.unavailable(error.reason, fetched_at=now)
        except Exception as error:
            logger.warning(
                "Treasury yield fetch failed unexpectedly: %s",
                type(error).__name__,
            )
            return TreasuryYieldReading.unavailable(
                REASON_UNEXPECTED_ERROR, fetched_at=now
            )

        return TreasuryYieldReading(
            available=True,
            observed_date=latest.observed_date,
            lookback_date=lookback.observed_date,
            ten_year_yield=latest.ten_year,
            two_year_yield=latest.two_year,
            ten_year_change_bp=change_bp,
            curve_spread_bp=spread_bp,
            fetched_at=now,
            reason=REASON_OK,
        )

    def _checked(
        self,
        reading: TreasuryYieldReading | None,
        now: datetime,
    ) -> TreasuryYieldReading:
        if reading is None:
            return TreasuryYieldReading.unavailable(REASON_UNEXPECTED_ERROR)

        if not reading.available:
            return reading

        observed = reading.observed_date
        if observed is None:
            return TreasuryYieldReading.unavailable(
                REASON_MISSING_FIELD, fetched_at=reading.fetched_at
            )

        # The Treasury dates rows in US Eastern time, which is never ahead
        # of UTC, so a row dated after today's UTC date is not genuine.
        today = now.astimezone(UTC).date()
        if observed > today:
            return TreasuryYieldReading.unavailable(
                REASON_FUTURE_TIMESTAMP, fetched_at=reading.fetched_at
            )

        observed_start = datetime(
            observed.year, observed.month, observed.day, tzinfo=UTC
        )
        if now - observed_start > self._max_age:
            return TreasuryYieldReading.unavailable(
                REASON_STALE, fetched_at=reading.fetched_at
            )

        return reading


def _utc_now() -> datetime:
    return datetime.now(UTC)
