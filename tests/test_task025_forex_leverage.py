"""Task 025 (registry v5.108, policy manifest v4): forex leverage 1:2 as margin accounting, with a 100 % stop-out.

Owner 2026-10-26 '1:2 (Önerilen)' and '%100 (Önerilen)'; 2026-10-27 'Kaldıraç ve short onaylı'. The FOREX book is
a schema 3 margin book (margin = notional / 2); every notional ceiling and the sizing proposal scale by 2, every loss
limit stays where it was; the exit guard closes everything, largest loss first, at a margin level of 100 % or below.
CRYPTO keeps leverage 1 and the schema 2 cash book, byte-identical."""

from __future__ import annotations

import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from atlas_finance.forex import FOREX_LEVERAGE, STOP_OUT_MARGIN_LEVEL
from core import policy_manifest as pm
from core.application import AtlasApplication
from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import (
    MARGIN_SCHEMA_VERSION,
    SCHEMA_VERSION,
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
    complete_interrupted_transition,
    mint_long_position_id,
)
from core.exit_guard import (
    ENFORCE,
    EXIT_NOT_TRIGGERED,
    EXIT_PENDING_PRICE,
    EXIT_TRIGGERED,
    PROTECTIVE_EXIT,
    RULE_STOP_OUT,
    RULE_WEEKEND_CLOSE,
    SAFETY_EXIT,
    ExitGuard,
    ExitRule,
    Mark,
)
from core.position_sizing import PositionSizingService, SizingInputs, SizingStatus
from core.risk_engine import RiskBucket, RiskPolicy, derive_buy_capacity_limits, sizing_ceiling, SizingSignal
from tests.test_block5c_upstream_sizing_authority import seed_state

ROOT = Path(__file__).resolve().parents[1]
V4 = "governance/policy/ATLAS_POLICY_MANIFEST_v4.json"
PID = mint_long_position_id("EURUSD", "req-1")


# ---------------------------------------------------------------- helpers


def book(tmp_path, *, cash="10000", leverage=2, expected=2, name="fx"):
    store = FinancialStateStore(tmp_path / f"{name}.json")
    store.initialize(D(cash), leverage=leverage)
    foundation = ExecutionPortfolioFoundation(
        store, applied_archive=AppliedExecutionArchiveStore(tmp_path / f"{name}-applied.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / f"{name}-closed.jsonl"), leverage=expected)
    return foundation, store


def reopen(tmp_path, store, *, expected=2, name="fx"):
    return ExecutionPortfolioFoundation(
        store, applied_archive=AppliedExecutionArchiveStore(tmp_path / f"{name}-applied.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / f"{name}-closed.jsonl"), leverage=expected)


def fill(action, base, price, execution_id, *, fee="0", position_id=PID, symbol="EURUSD"):
    return ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id=execution_id, position_id=position_id,
        symbol=symbol, action=action, filled_price=price, filled_base_quantity=D(str(base)),
        filled_quote_notional=D(str(price)) * D(str(base)), fee_amount=D(str(fee)), fee_currency="USD",
        idempotency_key=execution_id, provenance_ref="test")


def apply(foundation, result, version=None):
    return foundation.apply_confirmed(result, risk_authorized=True, reservation_confirmed=True,
                                      expected_position_version=version)


# ---------------------------------------------------------------- the margin book (schema 3)


def test_leverage_1_is_the_schema_2_cash_book_byte_for_byte(tmp_path):
    store = FinancialStateStore(tmp_path / "c.json")
    store.initialize(D("10000"))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION == 2 and "leverage" not in payload
    explicit = FinancialStateStore(tmp_path / "d.json")
    explicit.initialize(D("10000"), leverage=1)
    assert explicit.path.read_bytes() == store.path.read_bytes()


def test_leverage_2_creates_the_schema_3_margin_book(tmp_path):
    foundation, store = book(tmp_path)
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == MARGIN_SCHEMA_VERSION == 3 and payload["leverage"] == 2
    snap = foundation.snapshot()
    assert foundation.ready and snap["leverage"] == 2 and snap["used_margin"] == 0 and snap["margin_level"] is None
    assert snap["equity"] == snap["spendable_cash"] == snap["cash"] == D("10000")


@pytest.mark.parametrize("leverage", [0, 6, True, "2", 2.0])
def test_an_invalid_leverage_is_refused(tmp_path, leverage):
    with pytest.raises(ValueError):
        FinancialStateStore(tmp_path / "x.json").initialize(D("1"), leverage=leverage)
    assert not (tmp_path / "x.json").exists()


@pytest.mark.parametrize("created, expected, ready", [(1, 2, False), (2, 1, False), (2, 3, False), (1, 1, True),
                                                      (2, 2, True), (1, None, True), (2, None, True)])
def test_a_book_with_another_leverage_is_not_ready(tmp_path, created, expected, ready):
    foundation, _ = book(tmp_path, leverage=created, expected=expected)
    assert foundation.ready is ready
    if not ready:
        assert foundation.diagnostics()["reason"] == "FINANCIAL_LEVERAGE_CONFLICT"


def test_a_buy_debits_margin_and_fee_only(tmp_path):
    foundation, _ = book(tmp_path)
    snap = apply(foundation, fill("BUY", 2000, D("1.08"), "e1", fee="2.16"))          # notional 2160
    position = snap["positions"]["EURUSD"]
    assert D(position["margin"]) == D("1080") and position["cost_quote"] == "2160.00"
    assert snap["cash"] == D("10000") - D("1080") - D("2.16")
    assert snap["used_margin"] == D("1080") and snap["gross_exposure"] == D("2160.00")
    assert snap["equity"] == D("10000") - D("2.16")                                    # only the fee is spent
    assert abs(snap["margin_level"] - snap["equity"] / D("1080")) < D("1e-20")   # the book divides at 50 digits


def test_an_unrealized_loss_reduces_equity_and_spendable_cash_a_gain_never_funds_new_risk(tmp_path):
    foundation, _ = book(tmp_path)
    apply(foundation, fill("BUY", 2000, D("1.08"), "e1"))
    foundation.mark("EURUSD", D("1.03"))                                               # -100
    snap = foundation.snapshot()
    assert snap["unrealized_pnl"] == D("-100.00") and snap["equity"] == D("9900.00")
    assert snap["spendable_cash"] == snap["cash"] - D("100")
    foundation.mark("EURUSD", D("1.13"))                                               # +100
    snap = foundation.snapshot()
    assert snap["equity"] == D("10100.00") and snap["spendable_cash"] == snap["cash"]


def test_a_full_close_returns_margin_plus_gross_minus_fee(tmp_path):
    foundation, _ = book(tmp_path)
    apply(foundation, fill("BUY", 2000, D("1.08"), "e1", fee="2"))
    snap = apply(foundation, fill("SELL", 2000, D("1.10"), "e2", fee="2"), version=1)  # gross +40
    assert snap["positions"] == {} and snap["used_margin"] == 0
    assert snap["cash"] == D("10000") - 2 - 2 + D("40") and snap["equity"] == snap["cash"]
    assert snap["realized_gross_pnl"] == D("40.00")
    closed = foundation._closed_by_position_id[PID]
    assert D(closed["margin"]) == D("1080") and closed["gross_pnl"] == "40.00"


def test_a_partial_close_releases_margin_pro_rata_as_complements(tmp_path):
    foundation, _ = book(tmp_path)
    apply(foundation, fill("BUY", 3000, D("1.1"), "e1"))                               # margin 1650
    snap = apply(foundation, fill("SELL", 1000, D("1.1"), "e2"), version=1)
    position = snap["positions"]["EURUSD"]
    assert D(position["margin"]) == D("1650") - D("1650") * 1000 / 3000
    assert snap["cash"] == D("10000") - D("1650") + D("1650") * 1000 / 3000
    assert snap["equity"] == D("10000")


def test_adding_to_a_position_accumulates_margin(tmp_path):
    foundation, _ = book(tmp_path)
    apply(foundation, fill("BUY", 1000, D("1.08"), "e1"))
    snap = apply(foundation, fill("BUY", 1000, D("1.10"), "e2"), version=1)
    assert D(snap["positions"]["EURUSD"]["margin"]) == D("540") + D("550") == snap["used_margin"]


def test_margin_beyond_cash_is_refused_and_leaves_nothing(tmp_path):
    foundation, store = book(tmp_path, cash="1000")
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="INSUFFICIENT_CASH"):
        apply(foundation, fill("BUY", 2000, D("1.0"), "e1", fee="1"))                  # margin 1000 + fee 1
    assert store.path.read_bytes() == before and foundation.ready


def test_a_loss_larger_than_the_account_is_recorded_as_negative_cash(tmp_path):
    foundation, store = book(tmp_path, cash="1000")
    apply(foundation, fill("BUY", 2000, D("1.0"), "e1"))                               # margin 1000, cash 0
    snap = apply(foundation, fill("SELL", 2000, D("0.4"), "e2"), version=1)            # gross -1200
    assert snap["cash"] == D("-200") and snap["equity"] == D("-200") and snap["spendable_cash"] == D("-200")
    assert reopen(tmp_path, store).ready                                               # recorded, not corrupt


def test_a_cash_book_never_goes_negative_or_carries_margin(tmp_path):
    foundation, store = book(tmp_path, leverage=1, expected=1)
    apply(foundation, fill("BUY", 1000, D("1.0"), "e1"))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert "margin" not in payload["positions"]["EURUSD"]
    payload["positions"]["EURUSD"]["margin"] = "500"
    store.save(payload)
    assert reopen(tmp_path, store, expected=1).diagnostics()["reason"] == "CORRUPT_FINANCIAL_STATE"
    del payload["positions"]["EURUSD"]["margin"]
    payload["cash"] = "-1"
    store.save(payload)
    assert reopen(tmp_path, store, expected=1).diagnostics()["reason"] == "CORRUPT_FINANCIAL_STATE"


def test_the_cash_book_settlement_is_unchanged(tmp_path):
    foundation, _ = book(tmp_path, leverage=1, expected=1)
    snap = apply(foundation, fill("BUY", 1000, D("1.08"), "e1", fee="1"))
    assert snap["cash"] == D("10000") - D("1080") - 1 and snap["equity"] == snap["cash"] + D("1080")
    assert snap["used_margin"] == D("1080") and snap["spendable_cash"] == snap["cash"]
    assert snap["leverage"] == 1 and snap["margin_level"] is None
    snap = apply(foundation, fill("SELL", 1000, D("1.10"), "e2", fee="1"), version=1)
    assert snap["cash"] == D("10000") - 2 + D("20")


@pytest.mark.parametrize("edit", [
    lambda p: p["positions"]["EURUSD"].pop("margin"),
    lambda p: p["positions"]["EURUSD"].update(margin="0"),
    lambda p: p["positions"]["EURUSD"].update(margin="NaN"),
    lambda p: p.update(leverage=7),
    lambda p: p.update(leverage=1),
    lambda p: p.update(leverage="2"),
    lambda p: p.pop("leverage"),
    lambda p: p.update(extra=1),
])
def test_a_corrupt_margin_book_is_never_ready(tmp_path, edit):
    foundation, store = book(tmp_path)
    apply(foundation, fill("BUY", 1000, D("1.0"), "e1"))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    edit(payload)
    store.save(payload)
    assert not reopen(tmp_path, store, expected=None).ready


def test_restart_and_replay_are_idempotent(tmp_path):
    foundation, store = book(tmp_path)
    result = fill("BUY", 1000, D("1.0"), "e1", fee="1")
    first = apply(foundation, result)
    again = reopen(tmp_path, store)
    assert again.snapshot()["equity"] == first["equity"] and again.snapshot()["used_margin"] == D("500")
    replay = apply(again, result)
    assert replay["replayed"] is True and replay["cash"] == first["cash"]


def test_an_interrupted_margin_close_is_completed_with_the_margin_arithmetic(tmp_path):
    foundation, store = book(tmp_path)
    apply(foundation, fill("BUY", 1000, D("1.0"), "e1"))
    close = fill("SELL", 1000, D("1.2"), "e2", fee="1")

    def crash():
        raise RuntimeError("killed")

    with pytest.raises(RuntimeError):
        foundation.apply_confirmed(close, risk_authorized=True, reservation_confirmed=True,
                                   expected_position_version=1, before_final_persist=crash)
    snap = complete_interrupted_transition(
        store, applied_archive=AppliedExecutionArchiveStore(tmp_path / "fx-applied.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / "fx-closed.jsonl"), evidence=close)
    assert snap["cash"] == D("10000") + D("200") - 1 and snap["leverage"] == 2
    assert reopen(tmp_path, store).ready


# ---------------------------------------------------------------- RiskPolicy and sizing


@pytest.mark.parametrize("leverage", [0, 6, True, 2.0, "2"])
def test_policy_leverage_is_an_integer_from_1_to_5(leverage):
    with pytest.raises(ValueError):
        RiskPolicy(total_capital=D("10000"), leverage=leverage)


def test_leverage_1_keeps_every_ceiling_unchanged():
    policy, bucket = RiskPolicy(total_capital=D("10000")), None
    assert policy.leverage == 1 and policy.exposure_capital == D("10000")
    bucket = policy.buckets[RiskBucket.HIGH]
    limits = derive_buy_capacity_limits(policy, bucket, symbol_exposure=D("0"), committed_quote=D("0"))
    assert limits.max_position == D("10000") * policy.max_position_pct
    assert limits.allocatable_capital == policy.allocatable_capital


def test_notional_ceilings_scale_by_leverage_loss_limits_do_not():
    one, two = RiskPolicy(total_capital=D("10000")), RiskPolicy(total_capital=D("10000"), leverage=2)
    for bucket in RiskBucket:
        a = derive_buy_capacity_limits(one, one.buckets[bucket], symbol_exposure=D("0"), committed_quote=D("0"))
        b = derive_buy_capacity_limits(two, two.buckets[bucket], symbol_exposure=D("0"), committed_quote=D("0"))
        assert b.as_tuple() == tuple(2 * x for x in a.as_tuple())
    held = derive_buy_capacity_limits(two, two.buckets[RiskBucket.HIGH], symbol_exposure=D("500"),
                                      committed_quote=D("700"))
    assert held.per_symbol == D("20000") * two.per_symbol_pct - 500                   # exposure is never scaled
    assert held.portfolio_exposure == D("20000") * two.portfolio_exposure_pct - 700
    assert two.max_daily_loss_pct == one.max_daily_loss_pct and two.total_capital == one.total_capital
    assert two.reserved_capital == one.reserved_capital and two.allocatable_capital == one.allocatable_capital


def test_kelly_and_volatility_ceilings_are_not_scaled():
    signal = SizingSignal(win_probability=D("0.6"), win_return=D("0.1"), loss_return=D("0.1"),
                          realized_volatility=D("0.5"))
    # each guard set below the policy's own position cap (4000 at 1:1, 8000 at 1:2), so the guard decides
    for kind, expected in (({"kelly_fraction": D("0.1")}, D("2000")), ({"volatility_target": D("0.1")}, D("2000"))):
        one = sizing_ceiling(RiskPolicy(total_capital=D("10000"), **kind), signal, drawdown_pct=D("0"))
        two = sizing_ceiling(RiskPolicy(total_capital=D("10000"), leverage=2, **kind), signal, drawdown_pct=D("0"))
        assert one.amount == two.amount == expected
        assert D(one.detail["position_cap"]) * 2 == D(two.detail["position_cap"])


def test_the_sizing_proposal_scales_by_leverage_and_reaches_the_minimum_lot():
    def propose(leverage, free="10000"):
        service = PositionSizingService(RiskPolicy(total_capital=D("10000"), leverage=leverage))
        return service.propose(SizingInputs(request_id="r", symbol="EURUSD", risk_bucket="HIGH",
                                            durable_free_quote_capital=D(free), symbol_exposure=D("0"),
                                            committed_quote=D("0")))
    one, two = propose(1), propose(2)
    assert one.status is two.status is SizingStatus.PROPOSED
    assert two.proposed_quote_allocation == 2 * one.proposed_quote_allocation
    assert one.proposed_quote_allocation < D("1080") <= two.proposed_quote_allocation  # 0.01 lot EURUSD ~1080
    assert propose(2, free="500").proposed_quote_allocation <= D("500")                # cash still bounds it


# ---------------------------------------------------------------- the STOP_OUT rule


class Book:
    """equity = cash + used margin + unrealized P&L at the durable marks, as the margin book computes it."""

    def __init__(self, positions, *, cash, used, equity=None):
        self.positions, self.cash, self.used, self.equity = positions, cash, used, equity

    def snapshot(self):
        if self.equity is not None:
            equity = self.equity
        else:
            unrealized = sum((D(p["base_quantity"]) * D(p["mark_price"]) - D(p["cost_quote"])
                              for p in self.positions.values()), D("0"))
            equity = D(self.cash) + D(self.used) + unrealized
        return {"positions": self.positions, "cash": self.cash, "used_margin": self.used, "equity": equity}


class Manager:
    def __init__(self):
        self.calls = []

    def execute(self, decision, _):
        self.calls.append(decision)
        return {"status": "COMPLETED"}


NOW = 1_800_000_000.0


def position(symbol, base, entry, mark):
    return {"base_quantity": str(base), "average_entry_price": str(entry), "position_id": f"p-{symbol}",
            "opened_at": "2026-10-28T10:00:00+00:00", "mark_price": str(mark),
            "cost_quote": str(D(str(base)) * D(str(entry)))}


def stop_out_guard(positions, *, cash, used, equity=None, rules=None):
    manager = Manager()
    rules = rules if rules is not None else (ExitRule("so", RULE_STOP_OUT, D("1"), priority=SAFETY_EXIT),)
    guard = ExitGuard(manager, Book(positions, cash=cash, used=used, equity=equity), rules=rules, mode=ENFORCE,
                      clock=lambda: NOW)
    return guard, manager


def marks(**prices):
    return {symbol: Mark(D(str(price)), NOW - 5) for symbol, price in prices.items()}


@pytest.mark.parametrize("kwargs, message", [
    ({"threshold": None}, "threshold"), ({"threshold": D("0")}, "threshold"), ({"threshold": D("5.1")}, "threshold"),
    ({"threshold": D("1"), "priority": PROTECTIVE_EXIT}, "SAFETY_EXIT"),
    ({"threshold": D("1"), "minutes": 30}, "no minutes"),
])
def test_stop_out_rule_validation(kwargs, message):
    kwargs.setdefault("priority", SAFETY_EXIT)
    with pytest.raises(ValueError, match=message):
        ExitRule("so", RULE_STOP_OUT, **kwargs)


@pytest.mark.parametrize("price, triggered", [("1.08", False), ("0.6", False), ("0.5401", False), ("0.54", True),
                                             ("0.4", True)])
def test_stop_out_at_or_below_a_100_percent_margin_level(price, triggered):
    # account 2160, 2000 EURUSD at 1.08: margin 1080, cash 1080; equity = 2160 + 2000 x (price - 1.08), so the
    # level (equity / 1080) is 1 at price 0.54
    guard, manager = stop_out_guard({"EURUSD": position("EURUSD", 2000, "1.08", "1.08")}, cash="1080", used="1080")
    outcome = guard.run_once(marks(EURUSD=price))[0]
    assert (outcome["state"] == EXIT_TRIGGERED) is triggered
    assert (len(manager.calls) == 1) is triggered
    if triggered:
        sell = manager.calls[0]
        assert sell["action"] == "SELL" and sell["reduce_only"] is True and sell["exit_priority"] == SAFETY_EXIT
        assert outcome["detail"]["rule_kind"] == RULE_STOP_OUT


def test_the_level_uses_the_fresh_price_not_the_durable_mark():
    guard, _ = stop_out_guard({"EURUSD": position("EURUSD", 2000, "1.08", "1.08")}, cash="1080", used="1080")
    assert guard.run_once(marks(EURUSD="0.5"))[0]["state"] == EXIT_TRIGGERED          # durable mark says level 2
    guard, _ = stop_out_guard({"EURUSD": position("EURUSD", 2000, "1.08", "0.5")}, cash="1080", used="1080")
    assert guard.run_once(marks(EURUSD="1.08"))[0]["state"] == EXIT_NOT_TRIGGERED      # durable mark says 0.93


def test_largest_loss_first_and_every_position_closes():
    positions = {"AUDUSD": position("AUDUSD", 1000, "0.70", "0.70"), "EURUSD": position("EURUSD", 1000, "1.10", "1.10"),
                 "GBPUSD": position("GBPUSD", 1000, "1.30", "1.30")}
    guard, manager = stop_out_guard(positions, cash="0", used="1550")
    guard.run_once(marks(AUDUSD="0.69", EURUSD="0.80", GBPUSD="1.10"))                # losses 10, 300, 200
    assert [call["symbol"] for call in manager.calls] == ["EURUSD", "GBPUSD", "AUDUSD"]


def test_never_on_a_stale_price_even_in_a_stop_out():
    positions = {"EURUSD": position("EURUSD", 2000, "1.08", "0.4"), "GBPUSD": position("GBPUSD", 10, "1.3", "1.3")}
    guard, manager = stop_out_guard(positions, cash="0", used="1086.5")
    outcomes = {o["symbol"]: o for o in guard.run_once({"GBPUSD": Mark(D("1.3"), NOW - 5),
                                                         "EURUSD": Mark(D("0.4"), NOW - 600)})}
    assert outcomes["EURUSD"]["state"] == EXIT_PENDING_PRICE
    assert outcomes["GBPUSD"]["state"] == EXIT_TRIGGERED and [c["symbol"] for c in manager.calls] == ["GBPUSD"]


@pytest.mark.parametrize("used, equity", [("NaN", "5000"), ("-1", "5000"), ("1080", "garbage"), (None, "5000")])
def test_an_unreadable_margin_level_exits(used, equity):
    guard, manager = stop_out_guard({"EURUSD": position("EURUSD", 2000, "1.08", "1.08")}, cash="1080", used=used,
                                    equity=equity)
    assert guard.run_once(marks(EURUSD="1.08"))[0]["detail"]["margin_level"] == "UNREADABLE"
    assert len(manager.calls) == 1


def test_no_margin_used_means_no_stop_out():
    guard, manager = stop_out_guard({}, cash="10000", used="0")
    assert guard.run_once({}) == [] and manager.calls == []


def test_stop_out_comes_before_the_weekend_close():
    rules = (ExitRule("wk", RULE_WEEKEND_CLOSE, None, minutes=30, in_window=lambda now, minutes: True),
             ExitRule("so", RULE_STOP_OUT, D("1"), priority=SAFETY_EXIT))
    guard, manager = stop_out_guard({"EURUSD": position("EURUSD", 2000, "1.08", "1.08")}, cash="1080",
                                    used="1080", rules=rules)
    assert [rule.rule_id for rule in guard.rules] == ["so", "wk"]
    assert guard.run_once(marks(EURUSD="0.5"))[0]["rule_id"] == "so"
    assert manager.calls[0]["exit_rule_id"] == "so"


def test_the_real_margin_book_feeds_the_stop_out(tmp_path):
    foundation, _ = book(tmp_path, cash="2160")
    apply(foundation, fill("BUY", 2000, D("1.08"), "e1"))                              # margin 1080, cash 1080
    manager = Manager()
    guard = ExitGuard(manager, foundation, rules=(ExitRule("so", RULE_STOP_OUT, D("1"), priority=SAFETY_EXIT),),
                      mode=ENFORCE, clock=lambda: NOW)
    assert guard.run_once(marks(EURUSD="1.0"))[0]["state"] == EXIT_NOT_TRIGGERED      # level (2160-160)/1080
    assert guard.run_once(marks(EURUSD="0.54"))[0]["state"] == EXIT_TRIGGERED         # level exactly 1


# ---------------------------------------------------------------- the application and manifest v4


@pytest.mark.parametrize("market", ["CRYPTO", "FOREX"])
def test_the_application_wires_leverage_and_the_stop_out_by_market(tmp_path, market):
    leverage = FOREX_LEVERAGE if market == "FOREX" else 1
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state", leverage=leverage), market=market)
    try:
        assert app.risk_policy.leverage == leverage and app.portfolio_foundation.expected_leverage == leverage
        assert app.portfolio_foundation.ready and app.portfolio_foundation.snapshot()["leverage"] == leverage
        if market == "FOREX":
            assert FOREX_LEVERAGE == 2 and STOP_OUT_MARGIN_LEVEL == D("1")
            assert [(r.kind, r.threshold, r.priority) for r in app.exit_guard.rules][0] == \
                (RULE_STOP_OUT, D("1"), SAFETY_EXIT)
        else:
            assert app.exit_guard.rules == ()
    finally:
        app.stop()


def test_a_forex_application_on_a_cash_book_is_not_ready(tmp_path):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"), market="FOREX")
    try:
        assert app.portfolio_foundation.diagnostics()["reason"] == "FINANCIAL_LEVERAGE_CONFLICT"
    finally:
        app.stop()


def main_kwargs(tmp_path, monkeypatch) -> dict:
    from tests.test_phase2_g2_exp002_grant import production_kwargs

    return production_kwargs(tmp_path, monkeypatch)


@pytest.mark.parametrize("market", ["CRYPTO", "FOREX"])
def test_the_application_built_as_main_py_matches_v4(tmp_path, monkeypatch, market):
    import main

    leverage = 2 if market == "FOREX" else 1
    kwargs = main_kwargs(tmp_path, monkeypatch)
    app = AtlasApplication(**{**kwargs, "state_directory": seed_state(tmp_path / "state", leverage=leverage),
                              "market": market})
    try:
        check = main.apply_policy_manifest(app)
        assert check.status == pm.MATCH, check.to_dict()
        assert check.owner_approval == f"{pm.OWNER_RATIFIED}:{pm.V4_RATIFICATION_REGISTRY_ID}"
        runtime = pm.runtime_policy(app)
        assert (runtime["risk_leverage"], runtime["book_leverage"]) == (leverage, leverage)
        assert runtime["forex_stop_out_margin_level"] == "1"
        assert runtime["exit_guard_rules"] == (2 if market == "FOREX" else 0)
        for switch, value in (("risk_leverage", 3), ("book_leverage", 1 if market == "FOREX" else 2),
                              ("forex_stop_out_margin_level", "0.5"), ("exit_guard_rules", 1)):
            bad = pm.verify({**runtime, switch: value})
            assert bad.status == pm.POLICY_MISMATCH and [m[0] for m in bad.mismatches] == [switch]
    finally:
        app.stop()


def test_a_forex_stop_out_that_is_not_run_or_not_enforced_blocks_new_risk(tmp_path, monkeypatch):
    import main

    kwargs = main_kwargs(tmp_path, monkeypatch)
    app = AtlasApplication(**{**kwargs, "state_directory": seed_state(tmp_path / "state", leverage=2),
                              "market": "FOREX"})
    try:
        assert main.apply_policy_manifest(app).status == pm.MATCH
        app.exit_guard.mode = "OBSERVE"
        assert pm.runtime_policy(app)["forex_stop_out_margin_level"] == pm.UNREADABLE
        app.exit_guard.mode = ENFORCE
        app.market_loop.exit_guard_runner = lambda cutoff: None
        assert pm.runtime_policy(app)["forex_stop_out_margin_level"] == pm.UNREADABLE
        assert pm.verify(pm.runtime_policy(app)).status == pm.POLICY_MISMATCH
    finally:
        app.stop()


def test_v4_is_active_and_its_chain_is_sealed():
    assert pm.MANIFEST_PATH == ROOT / V4 and pm.EXPECTED_MANIFEST_VERSION == 4
    manifest = json.loads((ROOT / V4).read_text(encoding="utf-8"))
    policy = manifest["policy"]
    assert set(policy) == set(pm.CRITICAL_SWITCHES_V4) == set(pm.CRITICAL_SWITCHES_V3) | set(pm.LEVERAGE_SWITCHES)
    assert policy["execution_mode"] == "PAPER" and policy["live_execution_enabled"] is False
    assert policy["risk_leverage"] == policy["book_leverage"] == {"by_market": {"CRYPTO": 1, "FOREX": 2}}
    assert policy["exit_guard_rules"] == {"by_market": {"CRYPTO": 0, "FOREX": 2}}
    v3 = json.loads(pm.MANIFEST_V3_PATH.read_text(encoding="utf-8"))["policy"]
    assert {k: x for k, x in policy.items() if k not in pm.LEVERAGE_SWITCHES and k != "exit_guard_rules"} == \
        {k: x for k, x in v3.items() if k != "exit_guard_rules"}
    record = json.loads((ROOT / pm.V4_RATIFICATION_REGISTRY_PATH).read_text(encoding="utf-8"))
    ratification = record[pm.V4_RATIFICATION_RECORD_KEY]
    assert ratification["status"] == "RATIFIED" and ratification["live_effect"] == "NONE"
    assert ratification["manifest_pin"] == {"manifest_file_sha256": pm.file_sha256((ROOT / V4).read_bytes()),
                                            "manifest_version": 4}
    assert pm.file_sha256((ROOT / pm.V4_RATIFICATION_REGISTRY_PATH).read_bytes()) == pm.V4_RATIFICATION_REGISTRY_SHA256
    assert record["grant_task_025_forex_leverage_margin"]["grants_trading_authority"] is False


def test_an_edited_v4_or_its_ratification_blocks_new_risk(tmp_path, monkeypatch):
    import shutil

    for relative in (V4, pm.V4_RATIFICATION_REGISTRY_PATH, pm.V4_EXPECTED_REGISTRY_ID.join(
            ("governance/current/", ".json")), pm.EXPECTED_GRANT_REGISTRY_PATH):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / relative, tmp_path / relative)
    runtime = {**{n: s["by_market"]["FOREX"] if isinstance(s, dict) and "by_market" in s
                  else s["one_of"][0] if isinstance(s, dict) else s
                  for n, s in json.loads((ROOT / V4).read_text(encoding="utf-8"))["policy"].items()},
               "market": "FOREX"}
    assert pm.verify(runtime, tmp_path / V4, repository_root=tmp_path).status == pm.MATCH
    data = json.loads((tmp_path / V4).read_text(encoding="utf-8"))
    data["policy"]["risk_leverage"]["by_market"]["FOREX"] = 5
    data["integrity"]["digest"] = pm.integrity_digest(data)
    (tmp_path / V4).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert pm.verify({**runtime, "risk_leverage": 5}, tmp_path / V4, repository_root=tmp_path).status == \
        pm.GRANT_MISMATCH                                                              # resealed, not ratified


# ---------------------------------------------------------------- bootstrap


def test_the_bootstrap_tool_creates_and_verifies_the_margin_book(tmp_path, capsys):
    from tools.bootstrap_financial_state import main as bootstrap

    directory = tmp_path / "forex" / "shadow"
    assert bootstrap(["--state-directory", str(directory), "--leverage", "2"]) == 0
    payload = json.loads((directory / "execution_financial_state.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3 and payload["leverage"] == 2
    assert bootstrap(["--state-directory", str(directory), "--leverage", "2", "--verify-only"]) == 0
    capsys.readouterr()
    assert bootstrap(["--state-directory", str(directory), "--verify-only", "--json"]) != 0
    assert "FINANCIAL_LEVERAGE_CONFLICT" in capsys.readouterr().out


def test_the_manifest_reads_the_leverage_the_application_really_holds(tmp_path):
    import dataclasses

    app = AtlasApplication(state_directory=seed_state(tmp_path / "state", leverage=2), market="FOREX")
    try:
        app.risk_policy = dataclasses.replace(app.risk_policy, leverage=3)
        app.portfolio_foundation.expected_leverage = 4
        runtime = pm.runtime_policy(app)
        assert (runtime["risk_leverage"], runtime["book_leverage"]) == (3, 4)
        app.risk_policy = dataclasses.replace(app.risk_policy, leverage=1)
        app.portfolio_foundation.expected_leverage = True                               # not an integer
        runtime = pm.runtime_policy(app)
        assert (runtime["risk_leverage"], runtime["book_leverage"]) == (1, pm.UNREADABLE)
    finally:
        app.stop()


# ---------------------------------------------------------------- review findings (HIGH-1, MEDIUM-1/2, LOW-1/2)


def test_new_risk_is_funded_from_cash_less_the_unrealized_loss(tmp_path):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state", leverage=2,
                                                      positions=[("EURUSD", "2000", "1.08")]), market="FOREX")
    try:
        foundation = app.portfolio_foundation
        cash = foundation.snapshot()["cash"]
        foundation.mark("EURUSD", D("1.03"))                                           # -100 unrealized
        assert app.execution._durable_free_quote_capital() == cash - D("100")
        foundation.mark("EURUSD", D("1.13"))                                           # +100: never spendable
        assert app.execution._durable_free_quote_capital() == cash
    finally:
        app.stop()


def test_sleeve_and_quote_exposure_limits_scale_by_leverage_loss_limits_do_not():
    from core.risk_engine import RiskEngine, RiskState, PositionExposure

    for leverage, allowed in ((1, False), (2, True)):
        policy = RiskPolicy(total_capital=D("10000"), leverage=leverage, sleeves_enabled=True)
        engine = RiskEngine(policy)
        state = RiskState(positions=(), committed_quote=D("0"), current_equity=D("10000"),
                          peak_equity=D("10000"), state_ready=True, accounting_day_utc="2026-10-27",
                          policy_version=policy.version)
        # HIGH sleeve share 0.15 of equity x L: 1500 at 1:1, 3000 at 1:2
        assert (engine._sleeve_check("HIGH", D("2000"), state) is None) is allowed
        quoted = RiskPolicy(total_capital=D("10000"), leverage=leverage, quote_exposure_pct=D("0.1"),
                            quote_currencies=("USD",))
        held = RiskState(positions=(PositionExposure("GBPUSD", D("1000"), D("1.3"), D("1300")),),
                         committed_quote=D("1300"), current_equity=D("10000"), peak_equity=D("10000"),
                         state_ready=True, accounting_day_utc="2026-10-27", policy_version=quoted.version)
        from types import SimpleNamespace
        guard = RiskEngine(quoted)._portfolio_guards("EURUSD", D("500"), SimpleNamespace(correlations=None), held)
        assert (guard is None) is allowed                                             # 1300 + 500 vs 1000 / 2000


def test_the_operator_tools_open_a_book_at_its_own_leverage():
    import ast

    for tool in ("tools/reconcile_execution_authorities.py", "tools/data_health_check.py"):
        tree = ast.parse((ROOT / tool).read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and getattr(node.func, "id", None) == "ExecutionPortfolioFoundation"]
        assert calls, tool
        for call in calls:
            leverage = [k.value for k in call.keywords if k.arg == "leverage"]
            assert len(leverage) == 1 and isinstance(leverage[0], ast.Constant) and leverage[0].value is None, tool


def test_the_health_check_reads_a_margin_book(tmp_path):
    from tools.data_health_check import check_financial_state

    state = seed_state(tmp_path / "state", leverage=2, positions=[("EURUSD", "2000", "1.08")])
    result = check_financial_state(state)[0]
    assert result["status"] == "OK", result
    # the fixture adds the position without debiting it: cash 10000 + margin 1080 (a cash-book identity would
    # count the 2160 notional instead)
    assert "starting capital 11080.00" in result["detail"]


def test_a_closed_archive_from_the_other_book_kind_is_corrupt(tmp_path):
    for created, strip in ((2, True), (1, False)):
        name = f"k{created}"
        foundation, store = book(tmp_path, leverage=created, expected=created, name=name)
        apply(foundation, fill("BUY", 1000, D("1.0"), f"{name}-1"))
        apply(foundation, fill("SELL", 1000, D("1.0"), f"{name}-2"), version=1)
        archive = tmp_path / f"{name}-closed.jsonl"
        line = json.loads(archive.read_text(encoding="utf-8").splitlines()[0])
        record = line["record"] if "record" in line else line
        if strip:
            record.pop("margin")
        else:
            record["margin"] = "500"
        archive.write_text(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        refused = reopen(tmp_path, store, expected=created, name=name)
        assert not refused.ready and refused.diagnostics()["reason"] == "FINANCIAL_CLOSED_AUTHORITY_CORRUPT"
