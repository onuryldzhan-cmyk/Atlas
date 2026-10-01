"""Fixes for the independent audit findings A-1..A-5 (docs/audits/INDEPENDENT_AUDIT_F3_F4_M1_2026-09-30.md)."""

from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from ai.core.intelligence.trade_evidence import LOSING_EFFECT, MIN_TRADES, symbol_evidence
from core.execution_manager import ExecutionManager
from core.order_lifecycle import Order, OrderLifecycleError


def row(g):
    return {"symbol": "BTCUSDT", "cost_quote": "1000", "gross_pnl": g}


def test_a1_infinity_record_cannot_remove_caution():
    losing = [row("-5")] * (MIN_TRADES + 2)
    assert symbol_evidence(losing, "BTCUSDT")["effect"] == LOSING_EFFECT
    out = symbol_evidence(losing + [row("Infinity")], "BTCUSDT")
    assert out["available"] is False  # malformed -> adapter keeps last good / fails closed


def test_a2_direct_transition_cannot_fake_a_late_fill():
    o = Order("o", D("10"))
    for st in ("VALIDATED", "SUBMITTED", "ACKNOWLEDGED", "CANCELLED"):
        o.transition(st, "x")
    with pytest.raises(OrderLifecycleError):
        o.transition("FILLED", "fill fake")
    assert not any("LATE_FILL" in h[1] for h in o.history)


@pytest.mark.parametrize("bps", ["NaN", "-1", "10000", "Infinity"])
def test_a3_invalid_slippage_fails_closed(bps):
    em = ExecutionManager.__new__(ExecutionManager)
    em.paper_slippage_bps = D(bps)
    em.instrument_rules = None
    with pytest.raises(ValueError):
        em._paper_fill_price(SimpleNamespace(action="SELL", price=10.0, symbol="X"))


def test_a4_nan_confidence_not_in_telemetry():
    from core.market_loop import MarketLoop

    loop = MarketLoop.__new__(MarketLoop)
    loop.last_signals = {"X": {"action": "BUY", "confidence": float("nan"), "metadata": {}}}
    assert loop._telemetry_decision("X")["confidence"] is None


def test_a5_cache_returns_copies(tmp_path):
    import json

    from core.brain import AtlasBrain

    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps({"position_id": "a", "symbol": "X"}) + "\n", encoding="utf-8")
    b = AtlasBrain.__new__(AtlasBrain)
    b.closed_positions_path = p
    b._read_closed_positions()[0]["symbol"] = "MUTATED"
    assert b._read_closed_positions()[0]["symbol"] == "X"
