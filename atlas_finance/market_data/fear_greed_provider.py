"""
============================================================
ATLAS FEAR & GREED PROVIDER v1.0.0
============================================================

Project Atlas AI

Public, read-only provider for the alternative.me Crypto Fear & Greed
Index, the sentiment input authorized by registry v4.66
(GRANT-SENTIMENT-P3-IMPLEMENTATION).

Responsibilities
----------------
- Fetch the latest daily index value (standard library only, no API key)
- Validate the response strictly before a value is ever reported
- Cache the value so the network is contacted at most once per refresh
  interval, never once per market cycle
- Refuse a value older than its own daily update cycle (stale)
- Classify a validated value into the FEAR / GREED / NEUTRAL band

Fail-closed contract
--------------------
``get_reading()`` never raises and never invents a number. A network error,
timeout, non-200 status, oversized body, malformed JSON, missing field,
out-of-range value, future timestamp, provider-reported error, stale value
or any unexpected exception yields ``available=False`` with ``value=None``
and a reason code. A failed refresh never falls back to an older value.

Freshness
---------
Measured live on 2026-09-23: each value's ``timestamp`` is 00:00 UTC of the
day it describes, and ``time_until_update`` counts down to the next 00:00
UTC, i.e. a daily cadence. The public page states no precise publication
deadline, so a conservative 26h ceiling (the 24h cycle plus 2h grace for a
late publication) is applied to the value's own timestamp, not to the time
Atlas fetched it.

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
- Sends one unauthenticated HTTPS GET to a fixed public endpoint
- Cannot place orders, access capital, or modify positions

Data attribution: alternative.me Crypto Fear & Greed Index
(https://alternative.me/crypto/fear-and-greed-index/).

============================================================
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final


logger = logging.getLogger(
    "AtlasAI.FearGreedProvider"
)


FEAR_GREED_ENDPOINT: Final[str] = (
    "https://api.alternative.me/fng/?limit=1&format=json"
)

# Band thresholds (registry v4.64 cited scale, confirmed by the owner in
# registry v4.66). A value strictly below FEAR_THRESHOLD is fear; a value at
# or above GREED_THRESHOLD is greed; everything between gives no signal.
FEAR_THRESHOLD: Final[int] = 25
GREED_THRESHOLD: Final[int] = 75

BAND_FEAR: Final[str] = "FEAR"
BAND_GREED: Final[str] = "GREED"
BAND_NEUTRAL: Final[str] = "NEUTRAL"

DEFAULT_REFRESH_INTERVAL: Final[timedelta] = timedelta(hours=1)
DEFAULT_RETRY_INTERVAL: Final[timedelta] = timedelta(minutes=5)
DEFAULT_MAX_AGE: Final[timedelta] = timedelta(hours=26)
DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0

# A timestamp this far ahead of the local clock is tolerated as clock skew;
# anything further is rejected rather than trusted.
MAX_FUTURE_SKEW: Final[timedelta] = timedelta(minutes=5)

# The real response is ~250 bytes. Anything near this cap is not the
# documented response and is refused before parsing.
MAX_RESPONSE_BYTES: Final[int] = 64 * 1024

_UNSIGNED_INTEGER = re.compile(r"[0-9]{1,12}")


# Reason codes. Every unavailable reading carries exactly one.
REASON_OK: Final[str] = "OK"
REASON_NETWORK_ERROR: Final[str] = "NETWORK_ERROR"
REASON_TIMEOUT: Final[str] = "TIMEOUT"
REASON_HTTP_ERROR: Final[str] = "HTTP_ERROR"
REASON_RESPONSE_TOO_LARGE: Final[str] = "RESPONSE_TOO_LARGE"
REASON_MALFORMED_RESPONSE: Final[str] = "MALFORMED_RESPONSE"
REASON_MISSING_FIELD: Final[str] = "MISSING_FIELD"
REASON_VALUE_OUT_OF_RANGE: Final[str] = "VALUE_OUT_OF_RANGE"
REASON_FUTURE_TIMESTAMP: Final[str] = "FUTURE_TIMESTAMP"
REASON_PROVIDER_REPORTED_ERROR: Final[str] = "PROVIDER_REPORTED_ERROR"
REASON_STALE: Final[str] = "STALE"
REASON_UNEXPECTED_ERROR: Final[str] = "UNEXPECTED_ERROR"


Transport = Callable[[str, float], bytes]


class FearGreedResponseError(ValueError):
    """A fetched response failed validation. ``reason`` is a reason code."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


class _TransportError(RuntimeError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class FearGreedReading:
    """One provider answer. ``value`` is None whenever ``available`` is False."""

    available: bool
    value: int | None
    observed_at: datetime | None
    fetched_at: datetime | None
    reason: str

    @classmethod
    def unavailable(
        cls,
        reason: str,
        fetched_at: datetime | None = None,
    ) -> FearGreedReading:
        return cls(
            available=False,
            value=None,
            observed_at=None,
            fetched_at=fetched_at,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def classify_fear_greed_band(value: Any) -> str:
    """Map a validated 0-100 index value to FEAR, GREED or NEUTRAL.

    Raises ValueError for anything that is not exactly an ``int`` in
    [0, 100]. Subclasses (bool, IntEnum, ...) are rejected too, so only the
    plain number this module's parser itself produces can be classified and
    passed on as a plain value.
    """

    if type(value) is not int:
        raise ValueError(f"fear & greed value must be an int, got {value!r}")

    if not 0 <= value <= 100:
        raise ValueError(f"fear & greed value out of range: {value!r}")

    if value < FEAR_THRESHOLD:
        return BAND_FEAR

    if value >= GREED_THRESHOLD:
        return BAND_GREED

    return BAND_NEUTRAL


def _strict_unsigned_int(raw: Any, field: str) -> int:
    # The API sends numbers as decimal strings ("71"). A JSON integer is
    # accepted too; floats, bools, signs, whitespace and exponents are not.
    if isinstance(raw, bool):
        raise FearGreedResponseError(
            REASON_MALFORMED_RESPONSE, f"{field} is a bool"
        )

    if isinstance(raw, int):
        if raw < 0:
            raise FearGreedResponseError(
                REASON_MALFORMED_RESPONSE, f"{field} is negative"
            )
        return raw

    if isinstance(raw, str) and _UNSIGNED_INTEGER.fullmatch(raw):
        return int(raw)

    raise FearGreedResponseError(
        REASON_MALFORMED_RESPONSE, f"{field} is not an unsigned integer"
    )


def parse_fear_greed_response(body: bytes) -> tuple[int, datetime]:
    """Validate a raw response body and return ``(value, observed_at)``.

    Raises FearGreedResponseError on any deviation from the documented
    shape. It never substitutes a default for a missing or bad field.
    """

    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise FearGreedResponseError(
            REASON_MALFORMED_RESPONSE, f"not UTF-8 JSON ({type(error).__name__})"
        ) from None

    if not isinstance(document, dict):
        raise FearGreedResponseError(
            REASON_MALFORMED_RESPONSE, "top level is not an object"
        )

    metadata = document.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise FearGreedResponseError(
                REASON_MALFORMED_RESPONSE, "metadata is not an object"
            )
        if metadata.get("error") is not None:
            raise FearGreedResponseError(
                REASON_PROVIDER_REPORTED_ERROR, "metadata.error is set"
            )

    if "data" not in document:
        raise FearGreedResponseError(REASON_MISSING_FIELD, "data")

    data = document["data"]
    if not isinstance(data, list) or not data:
        raise FearGreedResponseError(
            REASON_MALFORMED_RESPONSE, "data is not a non-empty list"
        )

    latest = data[0]
    if not isinstance(latest, dict):
        raise FearGreedResponseError(
            REASON_MALFORMED_RESPONSE, "data[0] is not an object"
        )

    for field in ("value", "timestamp"):
        if field not in latest or latest[field] is None:
            raise FearGreedResponseError(REASON_MISSING_FIELD, f"data[0].{field}")

    value = _strict_unsigned_int(latest["value"], "value")
    if value > 100:
        raise FearGreedResponseError(
            REASON_VALUE_OUT_OF_RANGE, f"value {value} is above 100"
        )

    epoch_seconds = _strict_unsigned_int(latest["timestamp"], "timestamp")
    try:
        observed_at = datetime.fromtimestamp(epoch_seconds, UTC)
    except (OverflowError, OSError, ValueError):
        raise FearGreedResponseError(
            REASON_MALFORMED_RESPONSE, "timestamp is not a representable time"
        ) from None

    return value, observed_at


def _urllib_transport(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AtlasAI-FearGreedProvider/1.0",
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


class FearGreedProvider:
    """Cached, fail-closed access to the daily Fear & Greed value.

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
        endpoint: str = FEAR_GREED_ENDPOINT,
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
        self._endpoint = endpoint
        self._timeout_seconds = float(timeout_seconds)
        self._refresh_interval = refresh_interval
        self._retry_interval = retry_interval
        self._max_age = max_age

        self._lock = threading.Lock()
        self._last_attempt_at: datetime | None = None
        self._last_outcome: FearGreedReading | None = None
        self.fetch_count = 0

    def get_reading(self) -> FearGreedReading:
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
                "Fear & Greed provider failed unexpectedly; reporting unavailable"
            )
            return FearGreedReading.unavailable(REASON_UNEXPECTED_ERROR)

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

    def _fetch(self, now: datetime) -> FearGreedReading:
        self.fetch_count += 1

        transport = (
            self._transport
            if self._transport is not None
            else _urllib_transport
        )

        try:
            body = transport(self._endpoint, self._timeout_seconds)
            if not isinstance(body, (bytes, bytearray)):
                raise FearGreedResponseError(
                    REASON_MALFORMED_RESPONSE, "transport returned non-bytes"
                )
            if len(body) > MAX_RESPONSE_BYTES:
                raise _TransportError(
                    REASON_RESPONSE_TOO_LARGE,
                    f"body exceeds {MAX_RESPONSE_BYTES} bytes",
                )
            value, observed_at = parse_fear_greed_response(bytes(body))
        except (FearGreedResponseError, _TransportError) as error:
            logger.warning(
                "Fear & Greed fetch unavailable: %s", error
            )
            return FearGreedReading.unavailable(error.reason, fetched_at=now)
        except Exception as error:
            logger.warning(
                "Fear & Greed fetch failed unexpectedly: %s",
                type(error).__name__,
            )
            return FearGreedReading.unavailable(
                REASON_UNEXPECTED_ERROR, fetched_at=now
            )

        return FearGreedReading(
            available=True,
            value=value,
            observed_at=observed_at,
            fetched_at=now,
            reason=REASON_OK,
        )

    def _checked(
        self,
        reading: FearGreedReading | None,
        now: datetime,
    ) -> FearGreedReading:
        if reading is None:
            return FearGreedReading.unavailable(REASON_UNEXPECTED_ERROR)

        if not reading.available:
            return reading

        observed_at = reading.observed_at
        if observed_at is None:
            return FearGreedReading.unavailable(
                REASON_MISSING_FIELD, fetched_at=reading.fetched_at
            )

        if observed_at - now > MAX_FUTURE_SKEW:
            return FearGreedReading.unavailable(
                REASON_FUTURE_TIMESTAMP, fetched_at=reading.fetched_at
            )

        if now - observed_at > self._max_age:
            return FearGreedReading.unavailable(
                REASON_STALE, fetched_at=reading.fetched_at
            )

        return reading


def _utc_now() -> datetime:
    return datetime.now(UTC)
