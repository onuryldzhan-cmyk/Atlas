"""Owner switch-on 2026-10-01: F-3, S1 sleeves and F-4 are ON in the real runtime (main.py) only."""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from tests.test_block5e_fee_settlement_accounting import seed_state
from core.application import AtlasApplication

ROOT = Path(__file__).resolve().parents[1]


def _main_call_kwargs() -> dict:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "AtlasApplication":
            return {k.arg: k.value for k in node.keywords}
    raise AssertionError("AtlasApplication call not found in main.py")


def test_main_turns_the_three_switches_on_as_literals():
    kw = _main_call_kwargs()
    assert ast.literal_eval(kw["count_unrealized_in_daily_loss"]) is True
    assert ast.literal_eval(kw["sleeves_enabled"]) is True
    assert ast.literal_eval(kw["paper_slippage_bps"]) == "5"


def test_switches_reach_the_engines(tmp_path):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), count_unrealized_in_daily_loss=True,
                           sleeves_enabled=True, paper_slippage_bps="5")
    assert app.risk_policy.count_unrealized_in_daily_loss is True
    assert app.risk_policy.sleeves_enabled is True
    assert app.risk_engine.policy.sleeves_enabled is True
    assert app.execution.paper_slippage_bps == Decimal("5")


def test_default_application_keeps_them_off(tmp_path):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"))
    assert app.risk_policy.count_unrealized_in_daily_loss is False and app.risk_policy.sleeves_enabled is False
    assert app.execution.paper_slippage_bps == Decimal("0")


@pytest.mark.parametrize("bad", ["-1", "101", "NaN"])
def test_absurd_slippage_is_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        AtlasApplication(state_directory=seed_state(tmp_path / "state"), paper_slippage_bps=bad)


def test_a_paper_round_trip_still_works_with_all_switches_on(tmp_path):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), count_unrealized_in_daily_loss=True,
                           sleeves_enabled=True, paper_slippage_bps="5")
    m = app.execution
    m.start()
    buy = m.execute({"symbol": "BTCUSDT", "action": "BUY", "price": 10.0, "amount": 100,
                     "confidence": 90.0, "risk": "MEDIUM", "request_id": "b1"})
    assert buy["status"] == "PAPER_EXECUTED" and buy["commit_outcome"] == "COMMITTED", buy
    assert Decimal(str(buy["filled_price"])) > Decimal("10")  # adverse slippage on the buy
    assert [e.risk_bucket for e in m._derived_position_exposures()] == ["MEDIUM"]
    sell = m.execute({"symbol": "BTCUSDT", "action": "SELL", "price": 10.0, "amount": 0,
                      "confidence": 90.0, "risk": "MEDIUM", "request_id": "s1"})
    assert sell["status"] == "PAPER_EXECUTED", sell
    assert "BTCUSDT" not in app.portfolio_foundation.snapshot()["positions"]


def test_main_turns_order_lifecycle_observe_on_and_it_reaches_execution(tmp_path):
    assert ast.literal_eval(_main_call_kwargs()["order_lifecycle_observe"]) is True
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), order_lifecycle_observe=True)
    assert app.execution.order_lifecycle_observe is True
    assert app.execution.status()["order_lifecycle"] == {"observe": True, "violations": 0, "latest": []}


def test_observed_violation_shows_in_readiness():
    from observability import readiness
    bad = readiness.evaluate({"runtime": {"healthy": True}, "execution": {
        "order_lifecycle": {"observe": True, "violations": 1, "latest": [{"violation": "EXECUTED_WITHOUT_DURABLE_COMMIT"}]}}})
    assert any(c["check"] == "order_lifecycle" and c["state"] == "FAIL" for c in bad["checks"])
    ok = readiness.evaluate({"runtime": {"healthy": True}, "execution": {"order_lifecycle": {"observe": True, "violations": 0}}})
    assert not any(c["check"] == "order_lifecycle" for c in ok["checks"])
