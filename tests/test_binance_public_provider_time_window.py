"""Tests for the time-window parameters added to Binance kline requests.

No network access: the HTTP session is stubbed so only the request the
provider builds, and the way it normalizes the response, is under test.
"""

from __future__ import annotations

import json

from datetime import UTC, datetime

import pytest

from atlas_finance.market_data.binance_public_provider import (
    BinancePublicDataProvider,
)
from atlas_finance.market_data.exceptions import MarketDataRequestError

START = datetime(2017, 8, 17, 4, 0, tzinfo=UTC)
END = datetime(2017, 8, 18, 4, 0, tzinfo=UTC)
START_MS = 1_502_942_400_000
END_MS = 1_503_028_800_000


def kline(open_time_ms: int) -> list:
    return [
        open_time_ms,
        "4261.48000000",
        "4313.62000000",
        "4261.32000000",
        "4308.83000000",
        "47.18100900",
        open_time_ms + 3_599_999,
        "202366.13839304",
        171,
        "35.16050300",
        "150952.47794304",
        "0",
    ]


class StubResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class StubSession:
    def __init__(self, payload):
        self._payload = payload
        self.requests: list[dict] = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.requests.append({"url": url, "params": params})
        return StubResponse(self._payload)

    def close(self):
        pass


@pytest.fixture()
def session():
    return StubSession([kline(START_MS), kline(START_MS + 3_600_000)])


@pytest.fixture()
def provider(session):
    return BinancePublicDataProvider(session=session)


class TestTimeWindowParameters:
    def test_window_is_sent_as_millisecond_bounds(self, provider, session):
        provider.get_candles("BTCUSDT", "1h", 1000, start_time=START, end_time=END)

        params = session.requests[0]["params"]
        assert params["startTime"] == START_MS
        assert params["endTime"] == END_MS
        assert params["interval"] == "1h"
        assert params["limit"] == 1000

    def test_window_is_omitted_when_not_requested(self, provider, session):
        provider.get_candles("BTCUSDT", "1h", 500)

        params = session.requests[0]["params"]
        assert "startTime" not in params
        assert "endTime" not in params

    def test_only_start_time_may_be_supplied(self, provider, session):
        provider.get_candles("BTCUSDT", "1h", 500, start_time=START)

        params = session.requests[0]["params"]
        assert params["startTime"] == START_MS
        assert "endTime" not in params

    def test_endpoint_is_still_the_public_klines_route(self, provider, session):
        provider.get_candles("BTCUSDT", "1h", 10, start_time=START)

        assert session.requests[0]["url"].endswith("/api/v3/klines")


class TestTimeWindowValidation:
    def test_inverted_window_is_rejected(self, provider):
        with pytest.raises(MarketDataRequestError):
            provider.get_candles("BTCUSDT", "1h", 10, start_time=END, end_time=START)

    def test_naive_datetime_is_rejected(self, provider):
        with pytest.raises(MarketDataRequestError):
            provider.get_candles(
                "BTCUSDT", "1h", 10, start_time=datetime(2017, 8, 17, 4, 0)
            )

    def test_non_datetime_is_rejected(self, provider):
        with pytest.raises(MarketDataRequestError):
            provider.get_candles("BTCUSDT", "1h", 10, start_time=START_MS)


class TestResponseNormalization:
    def test_candles_are_returned_in_open_time_order(self, provider):
        candles = provider.get_candles("BTCUSDT", "1h", 10, start_time=START)

        assert [candle.open_time for candle in candles] == sorted(
            candle.open_time for candle in candles
        )
        assert candles[0].open_time == START
        assert candles[0].symbol == "BTCUSDT"
        assert candles[0].timeframe == "1h"
