"""Roadmap C-4: a past trade is traced through recorded evidence only; gaps are N/A."""

import json

from tools.decision_trace import trace

TRADE = {"position_id": "long:BTCUSDT:abc", "symbol": "BTCUSDT", "cost_quote": "100", "gross_pnl": "2",
         "opened_at": "2026-10-01T10:00:00+00:00", "closed_at": "2026-10-01T11:00:00+00:00"}


def test_full_chain_is_joined():
    lines = [json.dumps({"symbol": "BTCUSDT", "timestamp": "2026-10-01T09:59:30+00:00",
                         "decision": {"action": "BUY", "confidence": 72.0, "votes": {"trend": "BUY", "risk": "HOLD"}}}),
             json.dumps({"symbol": "ETHUSDT", "timestamp": "2026-10-01T09:59:30+00:00", "decision": {"action": "BUY"}})]
    events = [{"event_type": "RISK_DECISION", "timestamp": "2026-10-01T10:00:01+00:00",
               "payload": {"symbol": "BTCUSDT", "status": "APPROVE", "reason_code": "RISK_APPROVED"}}]
    t = trace(TRADE, lines, events)
    assert t["1_decision"]["votes"] == {"trend": "BUY", "risk": "HOLD"}
    assert t["2_risk_and_execution"][0]["reason"] == "RISK_APPROVED"
    assert t["3_outcome"]["analysis"]["counterfactual"]["label"].startswith("COUNTERFACTUAL")


def test_missing_links_are_na_never_guessed():
    far = [json.dumps({"symbol": "BTCUSDT", "timestamp": "2026-10-01T08:00:00+00:00", "decision": {"action": "BUY"}})]
    t = trace(TRADE, far, [])
    assert str(t["1_decision"]).startswith("N/A") and str(t["2_risk_and_execution"]).startswith("N/A")


def test_malformed_telemetry_lines_are_skipped():
    t = trace(TRADE, ["not json", "{}"], [])
    assert str(t["1_decision"]).startswith("N/A")
