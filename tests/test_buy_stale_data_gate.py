"""New risk needs fresh market data (registry v5.14).

MarketLoop routes a BUY only when the newest closed candle's measured age
is within BUY_MAX_CANDLE_AGE_SECONDS; an unmeasurable age refuses too.
SELL is never gated by freshness: reducing risk must not wait for a feed.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from core.market_loop import MarketLoop
from tests.test_block5c_upstream_sizing_authority import (
    application,
    execution_enabled_loop,
)


@pytest.fixture
def flat_app(tmp_path):
    app = application(tmp_path)
    app.execution.start()
    yield app
    app.stop()


@pytest.fixture
def holding_app(tmp_path):
    app = application(tmp_path, positions=[("BTCUSDT", "10", "10")])
    app.paper_trader.open_trade("BTCUSDT", 10, 100)
    app.execution.start()
    yield app
    app.stop()


def _age_clock(loop, seconds_after_close: float):
    """Pin 'now' to the newest candle's close plus ``seconds_after_close``."""

    fresh = loop._processing_cutoff()  # pinned to close + 1s by the helper
    loop._processing_cutoff = lambda: fresh + timedelta(seconds=seconds_after_close - 1)


def _spy_execute(app, monkeypatch):
    calls = []
    original = app.execution.execute

    def spy(decision, *args, **kwargs):
        calls.append(decision)
        return original(decision, *args, **kwargs)

    monkeypatch.setattr(app.execution, "execute", spy)
    return calls


def test_the_bound_matches_the_fetch_staleness_threshold():
    assert MarketLoop.BUY_MAX_CANDLE_AGE_SECONDS == MarketLoop.STALENESS_THRESHOLD_SECONDS


def test_fresh_buy_is_routed(flat_app, monkeypatch):
    calls = _spy_execute(flat_app, monkeypatch)
    loop = execution_enabled_loop(flat_app, "BUY")

    assert loop.process_symbol("BTCUSDT")["status"] == "PAPER_EXECUTED"
    assert len(calls) == 1


def test_stale_buy_is_not_routed(flat_app, monkeypatch):
    calls = _spy_execute(flat_app, monkeypatch)
    loop = execution_enabled_loop(flat_app, "BUY")
    _age_clock(loop, 600)

    result = loop.process_symbol("BTCUSDT")

    assert result["status"] == "SKIPPED"
    assert result["reason"] == "STALE_MARKET_DATA"
    assert calls == []
    assert loop.metrics["buy_stale_data_skipped"] == 1
    assert flat_app.portfolio_foundation.snapshot()["positions"] == {}


@pytest.mark.parametrize("age, routed", [(180.0, True), (180.5, False)])
def test_the_boundary_is_inclusive(flat_app, monkeypatch, age, routed):
    calls = _spy_execute(flat_app, monkeypatch)
    loop = execution_enabled_loop(flat_app, "BUY")
    _age_clock(loop, age)

    loop.process_symbol("BTCUSDT")

    assert (len(calls) == 1) is routed


def test_unmeasurable_candle_age_refuses_new_risk(flat_app, monkeypatch):
    calls = _spy_execute(flat_app, monkeypatch)
    loop = execution_enabled_loop(flat_app, "BUY")
    monkeypatch.setattr(
        MarketLoop, "_candle_age",
        classmethod(lambda cls, candle, cutoff: (None, cls.CANDLE_AGE_CLOSE_TIME_MISSING)),
    )

    result = loop.process_symbol("BTCUSDT")

    assert result["reason"] == "STALE_MARKET_DATA"
    assert calls == []


def test_stale_data_never_blocks_an_exit(holding_app, monkeypatch):
    calls = _spy_execute(holding_app, monkeypatch)
    loop = execution_enabled_loop(holding_app, "SELL")
    _age_clock(loop, 3600)

    result = loop.process_symbol("BTCUSDT")

    assert len(calls) == 1
    assert result["status"] == "PAPER_EXECUTED"
