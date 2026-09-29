"""FTMO-style limits card: shows, never decides; missing input is never guessed."""

from observability.portfolio_view import limits_card

POLICY = {"total_capital": "10000", "max_daily_loss_pct": "0.05", "drawdown_warning_pct": "0.05",
          "drawdown_restrict_pct": "0.10", "drawdown_halt_pct": "0.15"}
STATE = {"accounting_day_utc": "2026-09-30", "realized_daily_pnl": "-100", "peak_equity": "10000", "current_equity": "9800"}


def test_card_counts_realized_and_open_separately():
    c = limits_card(STATE, POLICY, "-150")
    assert c["daily_limit"] == "500.00" and c["realized_loss_today"] == "100.00" and c["realized_used_pct"] == "20.00"
    assert c["loss_with_open_positions"] == "250.00" and c["with_open_used_pct"] == "50.00"
    assert c["drawdown_pct"] == "2.00" and c["drawdown_levels_pct"]["halt"] == "15.00"


def test_profit_is_zero_loss_and_missing_inputs_are_not_guessed():
    c = limits_card({**STATE, "realized_daily_pnl": "40"}, POLICY, None)
    assert c["realized_loss_today"] == "0.00" and c["loss_with_open_positions"] is None
    assert limits_card(None, POLICY, "0")["available"] is False
    assert limits_card({**STATE, "peak_equity": "bad"}, POLICY, "0")["reason"] == "RISK_STATE_INCOMPLETE"


def test_web_helper_reads_durable_risk_file(tmp_path):
    import json
    from types import SimpleNamespace

    import web_app

    f = tmp_path / "risk.json"
    f.write_text(json.dumps({"schema": "atlas-risk-accounting-state-v1", **STATE, "policy_version": "x"}), encoding="utf-8")
    policy = SimpleNamespace(**{k: v for k, v in POLICY.items()})
    runtime = SimpleNamespace(risk_state_store=SimpleNamespace(path=f), risk_policy=policy)
    assert web_app._limits_payload(runtime, "0")["realized_loss_today"] == "100.00"
    runtime.risk_state_store.path = tmp_path / "missing.json"
    assert web_app._limits_payload(runtime, "0")["reason"] == "RISK_STATE_UNREADABLE"


def test_treasury_nav_single_denomination_and_mixed_currency_not_summed():
    from observability import portfolio_view as pv

    snap = {"cash": "900", "fees": "1", "committed_capital": "100", "realized_gross_pnl": "0", "realized_net_pnl": "0",
            "positions": {"BTCUSDT": {"base_quantity": "1", "cost_quote": "100", "average_entry_price": "100"}}}
    out = pv.build(snap, {"BTCUSDT": "110"}, None, quote_assets={"BTCUSDT": "USDT"})
    assert out["nav"] == out["equity"] == "1010.00" and out["denomination"] == "USDT"
    mixed = pv.build(snap, {"BTCUSDT": "110"}, None, quote_assets={"BTCUSDT": "TRY"})
    assert mixed["nav"] is None and mixed["denomination"] is None and "mixed quote currencies" in mixed["incomplete_reason"]
