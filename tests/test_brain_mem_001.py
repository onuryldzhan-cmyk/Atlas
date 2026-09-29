"""BRAIN-MEM-001: Atlas learns caution (never confidence) from its own closed trades, after fees."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai.core.atlas_brain import AtlasBrain as IntelligenceBrain
from ai.core.intelligence.memory_adapter import MemoryAdapter
from ai.core.intelligence.trade_evidence import LOSING_EFFECT, MIN_TRADES, symbol_evidence
from core.brain import AtlasBrain
from core.decision import DecisionAction


def trade(symbol="BTCUSDT", gross="1", cost="1000"):
    return {"symbol": symbol, "cost_quote": cost, "gross_pnl": gross}


def test_no_trades_and_too_few_trades_have_no_effect():
    assert symbol_evidence([], "BTCUSDT")["effect"] == 0.0
    losing = [trade(gross="-5")] * (MIN_TRADES - 1)
    assert symbol_evidence(losing, "BTCUSDT")["effect"] == 0.0


def test_proven_losing_book_gives_caution():
    out = symbol_evidence([trade(gross="-5")] * MIN_TRADES, "BTCUSDT")
    assert out["effect"] == LOSING_EFFECT and out["net_expectancy"] < 0 and out["longest_losing_streak"] == MIN_TRADES


def test_gross_winners_that_fees_turn_into_losers_count_as_losing():
    # +1 gross on 1000 notional pays ~2 in fees: 100 % gross win rate, losing book
    out = symbol_evidence([trade(gross="1")] * MIN_TRADES, "BTCUSDT")
    assert out["win_rate_after_fees"] == 0.0 and out["effect"] == LOSING_EFFECT


def test_winning_book_never_raises_confidence():
    out = symbol_evidence([trade(gross="50")] * (MIN_TRADES * 3), "BTCUSDT")
    assert out["net_expectancy"] > 0 and out["effect"] == 0.0


def test_other_coins_do_not_leak_into_a_coin():
    records = [trade("ETHUSDT", gross="-50")] * (MIN_TRADES * 2) + [trade("BTCUSDT", gross="-50")] * 2
    assert symbol_evidence(records, "BTCUSDT")["effect"] == 0.0


def test_malformed_record_is_no_signal():
    out = symbol_evidence([trade()] * MIN_TRADES + [{"symbol": "BTCUSDT", "gross_pnl": "x"}], "BTCUSDT")
    assert out["available"] is False and out["effect"] == 0.0


def test_adapter_unreadable_archive_is_no_signal_and_legacy_path_kept():
    def boom():
        raise OSError("locked")

    out = MemoryAdapter(None, closed_trades_reader=boom).analyze("BTCUSDT")
    assert out["available"] is False and out["effect"] == 0.0
    assert MemoryAdapter(None).analyze()["effect"] == 0  # no reader: historical behaviour


@pytest.mark.parametrize("action,effect,expected", [
    (DecisionAction.BUY, LOSING_EFFECT, 58.6),
    (DecisionAction.SELL, LOSING_EFFECT, 63.6),   # reducing exposure is never blocked
    (DecisionAction.BUY, 0.0, 63.6),
    (DecisionAction.BUY, 0.3, 63.6),              # a positive effect is ignored (NB-4)
    (DecisionAction.BUY, -0.9, 58.6),             # capped at 5 points
])
def test_brain_caution_only_lowers_buy_confidence(action, effect, expected):
    decision = SimpleNamespace(action=action, confidence=63.6)
    IntelligenceBrain._memory_buy_caution(decision, {"effect": effect, "trades": 12})
    assert decision.confidence == pytest.approx(expected)
    assert decision.confidence <= 63.6


def test_core_reader_missing_file_is_empty_and_bad_line_raises(tmp_path):
    path = tmp_path / "closed.jsonl"
    brain = AtlasBrain(closed_positions_path=path)
    assert brain._read_closed_positions() == []
    path.write_text(json.dumps(trade()) + "\n{broken\n", encoding="utf-8")
    with pytest.raises(ValueError):
        brain._read_closed_positions()
    assert "closed_trades_reader" in brain._intelligence_config()
    assert AtlasBrain()._intelligence_config() is None  # bare brain unchanged


def test_end_to_end_losing_archive_lowers_buy_through_the_adapter(tmp_path):
    path = tmp_path / "closed.jsonl"
    path.write_text("".join(json.dumps(trade(gross="-5")) + "\n" for _ in range(MIN_TRADES)), encoding="utf-8")
    brain = AtlasBrain(closed_positions_path=path)
    memory = MemoryAdapter(None, closed_trades_reader=brain._read_closed_positions)
    decision = SimpleNamespace(action=DecisionAction.BUY, confidence=63.6)
    adj = IntelligenceBrain._memory_buy_caution(decision, memory.analyze("BTCUSDT"))
    assert adj["reason"] == "LOSING_BOOK_AFTER_FEES" and decision.confidence == pytest.approx(58.6)
    other = SimpleNamespace(action=DecisionAction.BUY, confidence=63.6)
    assert IntelligenceBrain._memory_buy_caution(other, memory.analyze("ETHUSDT")) is None
