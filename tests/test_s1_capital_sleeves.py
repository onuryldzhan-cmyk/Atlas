"""S1 capital sleeves: only refuses more; exits never blocked; unknown fails closed; flag OFF unchanged."""

from dataclasses import replace

from core.risk_engine import PositionExposure, RiskEngine
from tests.test_phase3_risk_capital_foundation import D, policy, position, request, state


def pos(symbol, quote, bucket):
    return replace(position(symbol=symbol, quote=quote), risk_bucket=bucket)


def test_flag_off_is_unchanged():
    engine = RiskEngine(policy())
    big = state(pos("BTCUSDT", "300", "MEDIUM"))
    assert engine.evaluate(request(bucket="MEDIUM", amount="100"), big).reason_code != "SLEEVE_FULL"


def test_bucket_at_limit_refuses_and_empty_bucket_allows():
    engine = RiskEngine(policy(sleeves_enabled=True))
    full = state(pos("BTCUSDT", "300", "MEDIUM"))       # MEDIUM sleeve = 35% of 1000 = 350
    assert engine.evaluate(request(bucket="MEDIUM", amount="100"), full).reason_code == "SLEEVE_FULL"
    assert engine.evaluate(request(bucket="MEDIUM", amount="40"), full).reason_code != "SLEEVE_FULL"
    assert engine.evaluate(request(bucket="LOW", amount="100"), full).reason_code != "SLEEVE_FULL"


def test_unknown_bucket_positions_count_against_the_smallest_sleeve():
    engine = RiskEngine(policy(sleeves_enabled=True))
    legacy = state(pos("BTCUSDT", "140", None))           # HIGH sleeve = 150
    assert engine.evaluate(request(bucket="HIGH", amount="20"), legacy).reason_code == "SLEEVE_FULL"
    assert engine.evaluate(request(bucket="MEDIUM", amount="20"), legacy).reason_code != "SLEEVE_FULL"


def test_sell_is_never_blocked_by_a_sleeve():
    engine = RiskEngine(policy(sleeves_enabled=True))
    full = state(pos("BTCUSDT", "100", "HIGH"))
    close = request(symbol="BTCUSDT", action="SELL", reduce_only=True, bucket="HIGH",
                    requested_quote_allocation=D("50"), base_quantity=D("5"))
    assert engine.evaluate(close, full).reason_code == "RISK_REDUCTION_APPROVED"


def test_unknown_share_for_bucket_fails_closed():
    engine = RiskEngine(policy(sleeves_enabled=True, sleeve_shares={"LOW": D("0.5")}))
    assert engine.evaluate(request(bucket="MEDIUM", amount="10"), state()).reason_code == "SLEEVE_UNKNOWN_BUCKET"
