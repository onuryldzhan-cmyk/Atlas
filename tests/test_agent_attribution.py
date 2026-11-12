"""Agent attribution joins trades to the votes recorded just before opening; missing votes are unattributed."""

import json

from tools.agent_attribution import attribute, decisions_by_symbol


def tele(ts, votes, action="BUY", symbol="BTCUSDT"):
    return json.dumps({"timestamp": ts, "symbol": symbol, "decision": {"action": action, "votes": votes}})


def trade(opened, gross):
    return {"symbol": "BTCUSDT", "opened_at": opened, "cost_quote": "1000", "gross_pnl": gross}


def test_votes_are_attributed_and_split_supported_vs_opposed():
    lines = [tele("2026-09-30T10:00:00+00:00", {"technical": "BUY", "macro": "SELL"}),
             tele("2026-09-30T11:00:00+00:00", {"technical": "BUY", "macro": "BUY"})]
    out = attribute([trade("2026-09-30T10:00:30+00:00", "10"), trade("2026-09-30T11:00:20+00:00", "-10")],
                    decisions_by_symbol(lines))
    tech = out["agents"]["technical"]["supported"]
    assert tech["trades"] == 2 and tech["verdict"] == "INSUFFICIENT"
    assert out["agents"]["macro"]["opposed"]["trades"] == 1 and out["agents"]["macro"]["opposed"]["net_expectancy"] > 0


def test_trade_without_recorded_votes_is_unattributed():
    out = attribute([trade("2026-09-30T10:00:00+00:00", "5")], decisions_by_symbol(["not json", tele("2026-09-29T00:00:00+00:00", {"a": "BUY"})]))
    assert out["unattributed_trades"] == 1 and out["agents"] == {}
