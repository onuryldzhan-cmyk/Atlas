"""F-4: PAPER slippage (default 0 = historical fill); when on, always adverse and tick-rounded adversely."""

from decimal import Decimal as D
from types import SimpleNamespace

from core.execution_manager import ExecutionManager


def _em(bps, tick="0.01"):
    em = ExecutionManager.__new__(ExecutionManager)
    em.paper_slippage_bps = D(bps)
    em.instrument_rules = SimpleNamespace(get=lambda s: SimpleNamespace(price_tick=tick))
    return em


def req(action, price=100.0):
    return SimpleNamespace(action=action, price=price, symbol="BTCUSDT")


def test_default_is_the_historical_fill():
    assert _em("0")._paper_fill_price(req("BUY")) == 100.0
    em = ExecutionManager.__new__(ExecutionManager)
    em.instrument_rules = None
    assert em._paper_fill_price(req("SELL")) == 100.0  # class default 0


def test_slippage_is_adverse_for_both_sides():
    assert _em("5")._paper_fill_price(req("BUY")) == 100.05
    assert _em("5")._paper_fill_price(req("SELL")) == 99.95


def test_tick_rounding_is_adverse():
    assert _em("3", tick="0.1")._paper_fill_price(req("BUY")) == 100.1   # 100.03 -> up
    assert _em("3", tick="0.1")._paper_fill_price(req("SELL")) == 99.9   # 99.97 -> down
