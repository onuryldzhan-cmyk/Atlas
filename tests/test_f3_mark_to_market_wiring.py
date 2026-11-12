"""F-3 wiring: fresh closed-candle marks -> unrealized P&L in RiskState; stale or missing -> unknown."""

from decimal import Decimal as D
from types import SimpleNamespace

from core.execution_manager import ExecutionManager
from core.market_loop import MarketLoop
from core.risk_engine import PositionExposure, RiskPolicy


def test_mark_prices_only_fresh_closes():
    loop = MarketLoop.__new__(MarketLoop)
    loop.recent_candles = {"BTCUSDT": ((1_000_000, 1, 1, 1, 105.0),), "OLDUSDT": ((0, 1, 1, 1, 9.0),), "NONE": ()}
    assert loop.mark_prices(max_age_s=300, now_ms=1_000_000 + 60_000) == {"BTCUSDT": D("105.0")}


def _em(flag, prices):
    em = ExecutionManager.__new__(ExecutionManager)
    em.risk_engine = SimpleNamespace(policy=RiskPolicy(total_capital=D("1000"), count_unrealized_in_daily_loss=flag))
    em.mark_price_provider = (lambda: prices) if prices is not None else None
    return em


POS = [PositionExposure("BTCUSDT", D("1"), D("100"), D("100"))]


def test_unrealized_is_computed_only_with_flag_and_full_prices():
    assert _em(False, {"BTCUSDT": D("90")})._mark_to_market(POS) is None
    assert _em(True, {"BTCUSDT": D("90")})._mark_to_market(POS) == D("-10")
    assert _em(True, {})._mark_to_market(POS) is None          # missing mark -> unknown
    assert _em(True, None)._mark_to_market(POS) is None        # no provider -> unknown
    assert _em(True, {})._mark_to_market([]) == D("0")          # no positions -> zero is a fact


def test_provider_failure_is_unknown_not_zero():
    em = _em(True, None)
    em.mark_price_provider = lambda: (_ for _ in ()).throw(RuntimeError("feed down"))
    assert em._mark_to_market(POS) is None
