"""Task 027 (registry v5.110): the three LOW findings of the Task 026 review, fixed.

Owner 2026-11-02 'CLAUDE.md + LOW düzeltmeleri (Önerilen)'.
- T026-F3: the Brain's memory caution (up to 5 points less confidence on a losing book) also applies to a SELL that
  opens a forex short; a SELL that reduces exposure still never gets it.
- T026-F4: the passive PaperTrader mirror shows a short's side and its profit sign.
- T026-F5: a short's entry approval is attributed exactly, and its closed trade enters the lesson rows.
CRYPTO is unchanged throughout."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.core.atlas_brain import AtlasBrain as IntelligenceBrain
from ai.core.intelligence.trade_evidence import LOSING_EFFECT
from core.application import AtlasApplication
from core.decision import DecisionAction
from core.execution_portfolio_foundation import mint_position_id
from core.paper_trader import PaperTrader
from tests.test_block5c_upstream_sizing_authority import seed_state
from tools.lesson_book import live_rows
from tools.paper_position_report import entry_approval, is_canonical_position_id, opened_by

LOSING = {"effect": LOSING_EFFECT, "trades": 12}


# ---------------------------------------------------------------- F3: the Brain's memory caution


@pytest.mark.parametrize("action, opens, expected", [
    (DecisionAction.BUY, False, 58.6),
    (DecisionAction.SELL, True, 58.6),        # a SELL that opens a short is new risk
    (DecisionAction.SELL, False, 63.6),       # a SELL that reduces exposure is never blocked
])
def test_the_caution_applies_to_every_new_risk_order(action, opens, expected):
    decision = SimpleNamespace(action=action, confidence=63.6)
    IntelligenceBrain._memory_buy_caution(decision, LOSING, sell_opens_risk=opens)
    assert decision.confidence == pytest.approx(expected)


def test_a_positive_effect_never_raises_a_short_s_confidence_nb4():
    decision = SimpleNamespace(action=DecisionAction.SELL, confidence=63.6)
    assert IntelligenceBrain._memory_buy_caution(decision, {"effect": 0.3}, sell_opens_risk=True) is None
    assert decision.confidence == 63.6


@pytest.mark.parametrize("check, expected", [
    (None, False), (lambda symbol: True, True), (lambda symbol: False, False),
    (lambda symbol: None, True), (lambda symbol: 1 / 0, True),          # unsure counts as new risk
])
def test_the_short_entry_check_fails_closed(check, expected):
    brain = IntelligenceBrain.__new__(IntelligenceBrain)
    brain.short_entry_check = check
    assert brain._sell_opens_risk(SimpleNamespace(action=DecisionAction.SELL, symbol="EURUSD")) is expected
    assert brain._sell_opens_risk(SimpleNamespace(action=DecisionAction.BUY, symbol="EURUSD")) is False


@pytest.mark.parametrize("market, wired", [("FOREX", True), ("CRYPTO", False)])
def test_only_forex_hands_the_brain_a_short_entry_check(market, wired):
    state = Path(tempfile.mkdtemp()) / ("forex" if market == "FOREX" else "crypto")
    app = AtlasApplication(state_directory=seed_state(state, leverage=2 if wired else 1), market=market)
    try:
        assert app.brain.load_intelligence()
        check = app.brain.intelligence.short_entry_check
        assert (check is not None) is wired
        if wired:
            assert check("EURUSD") is True                                   # nothing held: a SELL opens a short
    finally:
        app.stop()


# ---------------------------------------------------------------- F4: the passive mirror


def _projected(position):
    return PaperTrader._projected_record(symbol="EURUSD", position=position)


POSITION = {"position_id": "p", "base_quantity": "1000", "average_entry_price": "1.10", "mark_price": "1.05",
            "cost_quote": "1100", "entry_fees": "0", "version": 1, "opened_at": "2026-10-28T10:00:00+00:00"}


def test_the_mirror_shows_a_short_and_its_profit_sign():
    short = _projected({**POSITION, "side": "SHORT"})
    long = _projected(POSITION)
    assert short["side"] == "SHORT" and "side" not in long
    trader = PaperTrader.__new__(PaperTrader)
    assert trader.calculate_profit(short) == pytest.approx(0.05)
    assert trader.calculate_profit(long) == pytest.approx(-0.05)


# ---------------------------------------------------------------- F5: attribution and lessons


SHORT_ID = mint_position_id("EURUSD", "EURUSD|1|SELL", "SHORT")


def approval(request_id, *, action, confidence=0.8, timestamp="2026-10-28T10:00:00+00:00"):
    return {"request_id": request_id, "action": action, "confidence": confidence, "risk": "HIGH",
            "experiment_id": None, "timestamp": timestamp}


def test_a_short_is_attributed_exactly_to_its_own_sell_approval():
    assert is_canonical_position_id(SHORT_ID) and opened_by(SHORT_ID, "EURUSD|1|SELL")
    assert not opened_by(SHORT_ID, "EURUSD|2|SELL")
    approvals = [approval("EURUSD|2|SELL", action="SELL"), approval("EURUSD|1|SELL", action="SELL")]
    assert entry_approval(approvals, None, SHORT_ID)["request_id"] == "EURUSD|1|SELL"


def test_a_sell_approval_never_takes_part_in_a_legacy_match():
    # a legacy (non-canonical) record is a crypto long; a nearby SELL (a reduction) must never claim it
    approvals = [approval("BTC|9|SELL", action="SELL")]
    assert entry_approval(approvals, "2026-10-28T10:00:00+00:00", None) is None
    approvals.append(approval("BTC|8|BUY", action="BUY"))
    assert entry_approval(approvals, "2026-10-28T10:00:00+00:00", None)["request_id"] == "BTC|8|BUY"


def test_a_closed_short_enters_the_lesson_rows_as_a_sell():
    closed = [{"symbol": "EURUSD", "position_id": SHORT_ID, "side": "SHORT", "cost_quote": "1100",
               "gross_pnl": "50", "opened_at": "2026-10-28T10:00:00+00:00"}]
    rows = live_rows(closed, {"EURUSD": [approval("EURUSD|1|SELL", action="SELL")]}, [])
    assert [row["action"] for row in rows] == ["SELL"] and float(rows[0]["net_live"]) > 0


def test_the_audit_loader_keeps_sell_approvals_and_labels_them(tmp_path):
    import json

    from tools.paper_position_report import approvals_by_symbol

    audit = tmp_path / "audit.jsonl"
    events = [
        {"event_type": "RISK_APPROVED", "aggregate_id": "EURUSD|1|SELL", "event_id": "e1",
         "timestamp": "2026-10-28T10:00:00+00:00", "payload": {"confidence": 0.8, "risk": "HIGH", "details": {}}},
        {"event_type": "RISK_APPROVED", "aggregate_id": "EURUSD|2|BUY", "event_id": "e2",
         "timestamp": "2026-10-28T11:00:00+00:00", "payload": {"confidence": 0.7, "risk": "HIGH", "details": {}}},
        {"event_type": "RISK_APPROVED", "aggregate_id": "EURUSD|3|HOLD", "event_id": "e3",
         "timestamp": "2026-10-28T12:00:00+00:00", "payload": {}},
    ]
    audit.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    found = approvals_by_symbol(audit)["EURUSD"]
    assert [(a["request_id"], a["action"]) for a in found] == [("EURUSD|1|SELL", "SELL"), ("EURUSD|2|BUY", "BUY")]
