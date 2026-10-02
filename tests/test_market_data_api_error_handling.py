"""Finding S-4: the market-data API error boundary, exercised for real.

STAGE1-PAPER-001 Item 8 (exchange-API-error handling) records that the
market-data error taxonomy in
``atlas_finance/market_data/binance_public_provider.py`` is implemented
thoroughly - 418 and 429 raise ``MarketDataRateLimitError`` carrying
``Retry-After``, timeouts and connection failures raise their own types,
rate-limit errors deliberately bypass the retry loop - and that **none
of it is tested**. The provider's only test file covers time-window
parameter mapping, and its ``pytest.raises`` calls are argument
validation that happens before any HTTP call.

The finding also records the consumer-side half: no test reaches the
broad handler in ``core/market_loop.py`` from a raising provider.
``tests/test_market_loop_reconnect.py:132`` calls ``loop._record_error``
**directly**, which is the bypass the finding names. At Stage 1 this is
the boundary that is actually live: live order placement is DENIED, so
the real network surface of a paper run is the Binance public
market-data API.

This module closes both halves. Every provider test drives the real
``get_candles`` / ``get_price`` code path against a stubbed HTTP
session, and every loop test drives the real ``process_symbol`` path
with a feed that raises - no internal handler is called directly
anywhere in this file.

WHY THE CONSUMER CATCH IS NOT NARROWED
--------------------------------------
Registry v4.41 grant GRANT-S1-S4-TEST-COVERAGE permits narrowing the
broad ``except Exception`` at ``core/market_loop.py:829`` to name
``MarketData*Error`` types, but only *if* a raising provider cannot
otherwise reach that handler in a way a test can discriminate. It can:
``MarketLoop._record_error`` already stores ``type(error).__name__``
(``core/market_loop.py:1915``), so the tests below can assert the exact
exception class that arrived, proving the error's identity survives the
handler rather than merely that something was caught. The narrowing was
therefore not performed - it would have been a production change with no
testability gain, which the grant's own "no production behaviour change
beyond testability" bright line forbids.

That is a deliberate scope decision, not an omission. STAGE1-PAPER-001's
own remediation note already places the related idea - distinguishing
rate-limit from other errors in the *recorded error phase* for operator
diagnosability - outside this work as a behaviour change needing its own
authorization.

These tests are offline: the HTTP session is stubbed, the loop fixtures
are in-memory, and no state directory is constructed or written.
"""

from __future__ import annotations

import json

from typing import Any

import pytest

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException
from requests.exceptions import Timeout as RequestsTimeout

from atlas_finance.market_data.binance_public_provider import (
    BinancePublicDataProvider,
)
from atlas_finance.market_data.exceptions import (
    MarketDataConnectionError,
    MarketDataRateLimitError,
    MarketDataRequestError,
    MarketDataResponseError,
    MarketDataTimeoutError,
)
from core.market_loop import MarketLoop


# ---------------------------------------------------------------------------
# HTTP stubs
# ---------------------------------------------------------------------------


class StubResponse:
    """A ``requests.Response`` stand-in with a controllable status."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        headers: dict[str, str] | None = None,
        text: str | None = None,
        raise_on_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self._raise_on_json = raise_on_json
        self.text = (
            text
            if text is not None
            else json.dumps(payload if payload is not None else [])
        )

    def json(self) -> Any:
        if self._raise_on_json:
            raise ValueError("No JSON object could be decoded")

        return self._payload


class StubSession:
    """Records every request and replays a fixed response or exception."""

    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def get(
        self,
        url: str,
        params: Any = None,
        timeout: Any = None,
        headers: Any = None,
    ) -> StubResponse:
        self.calls.append({"url": url, "params": params})

        if isinstance(self._outcome, Exception):
            raise self._outcome

        return self._outcome

    def close(self) -> None:
        pass


def build_provider(
    outcome: Any,
    *,
    retry_attempts: int = 3,
    retry_backoff_seconds: float = 0.0,
) -> tuple[BinancePublicDataProvider, StubSession]:
    """Provider wired to a stub session.

    Backoff defaults to zero so the retry tests do not actually sleep;
    the one test that is *about* backoff sets it explicitly and
    intercepts ``time.sleep``.
    """

    session = StubSession(outcome)

    provider = BinancePublicDataProvider(
        session=session,
        retry_attempts=retry_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
    )

    return provider, session


# ---------------------------------------------------------------------------
# Rate limiting: 429 and 418
# ---------------------------------------------------------------------------


def test_http_429_raises_rate_limit_error_carrying_retry_after() -> None:
    """The Retry-After header must survive into the raised error."""

    provider, session = build_provider(
        StubResponse(
            status_code=429,
            headers={"Retry-After": "120"},
            text="",
        )
    )

    with pytest.raises(MarketDataRateLimitError) as raised:
        provider.get_candles("BTCUSDT", "1m", 100)

    message = str(raised.value)

    assert "status=429" in message
    assert "retry_after=120" in message
    assert session.calls, "the stub session must actually have been called"


def test_http_429_without_retry_after_still_raises_rate_limit_error() -> None:
    """A missing Retry-After must not downgrade the classification."""

    provider, _session = build_provider(
        StubResponse(status_code=429, text="")
    )

    with pytest.raises(MarketDataRateLimitError) as raised:
        provider.get_candles("BTCUSDT", "1m", 100)

    message = str(raised.value)

    assert "status=429" in message
    assert "retry_after" not in message


def test_http_418_raises_rate_limit_error() -> None:
    """418 is Binance's IP-ban signal and is classified as rate limiting."""

    provider, _session = build_provider(
        StubResponse(status_code=418, text="")
    )

    with pytest.raises(MarketDataRateLimitError) as raised:
        provider.get_candles("BTCUSDT", "1m", 100)

    assert "status=418" in str(raised.value)


@pytest.mark.parametrize("status_code", [429, 418])
def test_rate_limit_responses_are_never_retried(status_code: int) -> None:
    """The single most important behaviour in this boundary.

    A rate-limited endpoint must be left alone, not hammered. The
    provider is configured with three retry attempts; a rate-limit
    response must still produce exactly one HTTP call, because
    ``_request_json`` re-raises ``MarketDataRateLimitError`` ahead of
    the retry branch.

    Without that deliberate bypass this would be three calls - and 418
    means Binance has already started banning the IP, so retrying into
    it is the failure mode that matters during a long paper run.
    """

    provider, session = build_provider(
        StubResponse(status_code=status_code, text=""),
        retry_attempts=3,
    )

    with pytest.raises(MarketDataRateLimitError):
        provider.get_candles("BTCUSDT", "1m", 100)

    assert len(session.calls) == 1


# ---------------------------------------------------------------------------
# Retry and backoff
# ---------------------------------------------------------------------------


def test_retryable_server_error_is_retried_up_to_the_attempt_limit() -> None:
    """A 500 is retried, then surfaces as MarketDataRequestError."""

    provider, session = build_provider(
        StubResponse(status_code=500, text="upstream failure"),
        retry_attempts=3,
    )

    with pytest.raises(MarketDataRequestError) as raised:
        provider.get_candles("BTCUSDT", "1m", 100)

    assert "status=500" in str(raised.value)
    assert len(session.calls) == 3


def test_backoff_is_exponential_and_bounded_by_the_attempt_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delays double per attempt and stop after the last attempt.

    With ``retry_backoff_seconds`` of 0.25 and three attempts, the
    implementation sleeps ``0.25 * 2**(attempt-1)`` between attempts and
    not after the final one, so the recorded delays are exactly
    [0.25, 0.5] - two sleeps for three attempts.

    This is the regression the finding names: if rate-limit or retry
    handling ever collapsed into a tight loop, nothing in the suite
    would have caught it. ``time.sleep`` is intercepted rather than
    endured, so the test is fast and asserts the schedule directly.
    """

    delays: list[float] = []

    monkeypatch.setattr(
        "time.sleep",
        lambda seconds: delays.append(seconds),
    )

    provider, session = build_provider(
        StubResponse(status_code=503, text=""),
        retry_attempts=3,
        retry_backoff_seconds=0.25,
    )

    with pytest.raises(MarketDataRequestError):
        provider.get_candles("BTCUSDT", "1m", 100)

    assert delays == [0.25, 0.5]
    assert len(session.calls) == 3
    assert len(delays) == len(session.calls) - 1


def test_a_rate_limited_response_never_sleeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-retry bypass must also skip the backoff sleep entirely."""

    delays: list[float] = []

    monkeypatch.setattr(
        "time.sleep",
        lambda seconds: delays.append(seconds),
    )

    provider, _session = build_provider(
        StubResponse(status_code=429, text=""),
        retry_attempts=3,
        retry_backoff_seconds=0.25,
    )

    with pytest.raises(MarketDataRateLimitError):
        provider.get_candles("BTCUSDT", "1m", 100)

    assert delays == []


def test_exhausted_retries_mark_the_provider_disconnected() -> None:
    """Retry exhaustion flips connected state so health can observe it."""

    provider, _session = build_provider(
        StubResponse(status_code=502, text=""),
        retry_attempts=2,
    )

    with pytest.raises(MarketDataRequestError):
        provider.get_candles("BTCUSDT", "1m", 100)

    assert provider.connected is False


# ---------------------------------------------------------------------------
# Transport-level failures
# ---------------------------------------------------------------------------


def test_request_timeout_is_classified_as_market_data_timeout_error() -> None:
    provider, session = build_provider(
        RequestsTimeout("read timed out"),
        retry_attempts=3,
    )

    with pytest.raises(MarketDataTimeoutError) as raised:
        provider.get_candles("BTCUSDT", "1m", 100)

    assert "timed out" in str(raised.value).lower()
    # A timeout is retryable, unlike a rate limit.
    assert len(session.calls) == 3


def test_connection_failure_is_classified_as_connection_error() -> None:
    provider, _session = build_provider(
        RequestsConnectionError("name resolution failed"),
        retry_attempts=2,
    )

    with pytest.raises(MarketDataConnectionError):
        provider.get_candles("BTCUSDT", "1m", 100)


def test_other_request_failures_are_classified_as_request_error() -> None:
    provider, _session = build_provider(
        RequestException("protocol error"),
        retry_attempts=2,
    )

    with pytest.raises(MarketDataRequestError):
        provider.get_candles("BTCUSDT", "1m", 100)


def test_unparseable_body_is_classified_as_response_error() -> None:
    """A 200 carrying junk is a response error, not a silent empty result."""

    provider, _session = build_provider(
        StubResponse(status_code=200, raise_on_json=True, text="<html>"),
        retry_attempts=2,
    )

    with pytest.raises(MarketDataResponseError):
        provider.get_candles("BTCUSDT", "1m", 100)


def test_the_taxonomy_distinguishes_the_failure_modes() -> None:
    """Each transport failure maps to its own type, not a shared one.

    The point of the taxonomy is operator diagnosability: sustained rate
    limiting must be distinguishable from a DNS failure in the logs.
    Asserting the types pairwise proves the classification is real and
    not four aliases for one error.
    """

    outcomes: list[tuple[Any, type[Exception]]] = [
        (StubResponse(status_code=429, text=""), MarketDataRateLimitError),
        (RequestsTimeout("t"), MarketDataTimeoutError),
        (RequestsConnectionError("c"), MarketDataConnectionError),
        (
            StubResponse(status_code=200, raise_on_json=True, text="x"),
            MarketDataResponseError,
        ),
    ]

    observed: list[type[Exception]] = []

    for outcome, expected_type in outcomes:
        provider, _session = build_provider(outcome, retry_attempts=1)

        with pytest.raises(expected_type) as raised:
            provider.get_price("BTCUSDT")

        observed.append(type(raised.value))

    assert len(set(observed)) == len(outcomes)


# ---------------------------------------------------------------------------
# Consumer side: the real MarketLoop.process_symbol path
# ---------------------------------------------------------------------------


class RaisingFeed:
    """MarketFeed stand-in that raises on the real ``candles()`` call."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    def candles(
        self,
        symbol: str,
        interval: str = "1m",
        limit: int = 200,
    ) -> list[Any]:
        self.calls += 1
        raise self._error


class CountingBrain:
    """Records whether the decision path was reached at all."""

    def __init__(self) -> None:
        self.calls = 0

    def analyze_and_decide(
        self,
        symbol: str,
        market_data: Any,
    ) -> dict[str, Any]:
        self.calls += 1

        return {
            "symbol": symbol,
            "action": "BUY",
            "confidence": 90.0,
            "risk": "LOW",
            "strategy": "SHOULD_NEVER_RUN",
            "reason": "This brain must not be reached on a feed error.",
        }


@pytest.mark.parametrize(
    "error",
    [
        MarketDataRateLimitError(
            "Binance public API rate limit reached. status=429 "
            "retry_after=120"
        ),
        MarketDataTimeoutError("Binance public request timed out."),
        MarketDataConnectionError("Could not connect to Binance."),
        MarketDataRequestError("Binance public HTTP request failed."),
        MarketDataResponseError("Binance returned invalid JSON."),
    ],
    ids=[
        "rate_limit",
        "timeout",
        "connection",
        "request",
        "response",
    ],
)
def test_market_data_errors_fail_closed_through_process_symbol(
    error: Exception,
) -> None:
    """Every taxonomy member must fail closed on the real loop path.

    This drives ``process_symbol`` itself, with a feed that raises from
    ``candles()`` - it does not call ``_record_error`` directly, which
    is the bypass finding S-4 identifies in the existing reconnect test.

    Failing closed means all four of: no decision returned, the brain
    never consulted, the error recorded with its own class name intact,
    and health flipped for the window.
    """

    feed = RaisingFeed(error)
    brain = CountingBrain()

    loop = MarketLoop(
        brain=brain,
        market_feed=feed,
        symbols=["BTCUSDT"],
    )

    result = loop.process_symbol("BTCUSDT")

    assert feed.calls == 1, "the raising feed must actually have been polled"
    assert result is None
    assert brain.calls == 0

    assert len(loop.errors) == 1
    recorded = loop.errors[-1]

    assert recorded["type"] == type(error).__name__
    assert recorded["phase"] == "symbol:BTCUSDT"
    assert str(error) in recorded["error"]

    assert loop.health()["healthy"] is False


def test_rate_limit_detail_survives_into_the_recorded_error() -> None:
    """The Retry-After detail must still be readable by an operator.

    The provider goes to the trouble of putting the retry window into
    the exception message; if the loop's handler discarded it, a
    rate-limited paper run would be indistinguishable in the error log
    from any other failure.
    """

    error = MarketDataRateLimitError(
        "Binance public API rate limit reached. status=429 retry_after=120"
    )

    feed = RaisingFeed(error)

    loop = MarketLoop(
        brain=CountingBrain(),
        market_feed=feed,
        symbols=["BTCUSDT"],
    )

    loop.process_symbol("BTCUSDT")

    recorded = loop.errors[-1]

    assert recorded["type"] == "MarketDataRateLimitError"
    assert "status=429" in recorded["error"]
    assert "retry_after=120" in recorded["error"]


def test_a_feed_error_does_not_leak_out_of_process_symbol() -> None:
    """The loop must absorb the error rather than propagate it.

    A raised exception escaping ``process_symbol`` would abort the whole
    cycle and every remaining symbol with it. Asserting no exception
    escapes is the other half of failing closed.
    """

    feed = RaisingFeed(MarketDataRateLimitError("status=418"))

    loop = MarketLoop(
        brain=CountingBrain(),
        market_feed=feed,
        symbols=["BTCUSDT", "ETHUSDT"],
    )

    for symbol in ("BTCUSDT", "ETHUSDT"):
        assert loop.process_symbol(symbol) is None

    assert feed.calls == 2
    assert len(loop.errors) == 2
    assert {record["phase"] for record in loop.errors} == {
        "symbol:BTCUSDT",
        "symbol:ETHUSDT",
    }


# ---------------------------------------------------------------------------
# Rate-limit back-off (2026-10-02; hummingbot AsyncThrottler idea)
# ---------------------------------------------------------------------------


def test_after_429_no_request_is_sent_until_retry_after_passes(monkeypatch) -> None:
    """Hitting the limit again during Retry-After escalates to a 418 IP ban; Atlas must not."""

    clock = {"now": 1000.0}
    monkeypatch.setattr(
        "atlas_finance.market_data.binance_public_provider.time.monotonic", lambda: clock["now"]
    )
    provider, session = build_provider(StubResponse(status_code=429, headers={"Retry-After": "30"}, text=""))

    with pytest.raises(MarketDataRateLimitError):
        provider.get_candles("BTCUSDT", "1m", 100)
    assert len(session.calls) == 1

    clock["now"] += 29
    with pytest.raises(MarketDataRateLimitError, match="no request sent"):
        provider.get_candles("ETHUSDT", "1m", 100)  # every symbol waits, not just the one that hit it
    assert len(session.calls) == 1

    clock["now"] += 2
    with pytest.raises(MarketDataRateLimitError, match="status=429"):
        provider.get_candles("BTCUSDT", "1m", 100)  # back-off over: the request goes out again
    assert len(session.calls) == 2


@pytest.mark.parametrize("header, expected", [(None, 60.0), ("garbage", 60.0), ("-5", 60.0), ("99999", 3600.0)])
def test_backoff_defaults_and_caps(monkeypatch, header, expected) -> None:
    monkeypatch.setattr("atlas_finance.market_data.binance_public_provider.time.monotonic", lambda: 0.0)
    headers = {} if header is None else {"Retry-After": header}
    provider, _ = build_provider(StubResponse(status_code=418, headers=headers, text=""))
    with pytest.raises(MarketDataRateLimitError):
        provider.get_candles("BTCUSDT", "1m", 100)
    assert provider._rate_limited_until == expected
