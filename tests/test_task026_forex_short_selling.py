"""Task 026 (registry v5.109, policy manifest v5): forex short selling on the 1:2 margin book.

Owner 2026-10-26 'Short eklensin'; 2026-10-27 'Kaldıraç ve short onaylı'. Orders keep the venue side (BUY/SELL) and
gain a position side (LONG/SHORT) derived from the durable book: in FOREX a SELL of a pair not held opens a short,
a BUY of a held short covers it. A short passes every new-risk gate a long does; covering it is a reduction. CRYPTO
never shorts, and every LONG payload stays byte-identical."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

import core.application as application_module
from atlas_finance.forex import FOREX_SHORTS_ENABLED
from atlas_finance.market_data.mt5_provider import Mt5MarketDataProvider
from core import policy_manifest as pm
from core.application import AtlasApplication
from core.decision_intelligence import Action, Evidence, FusionPolicy, SignalFusion
from core.execution_models import ExecutionRequest, ExecutionResult, opens_risk, reduces_risk
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
    complete_interrupted_transition,
    mint_position_id,
    position_unrealized,
)
from core.exit_guard import (
    ENFORCE,
    EXIT_NOT_TRIGGERED,
    EXIT_TRIGGERED,
    RULE_MAX_LOSS_PCT,
    RULE_STOP_OUT,
    RULE_WEEKEND_CLOSE,
    SAFETY_EXIT,
    ExitGuard,
    ExitRule,
    Mark,
)
from core.market_loop import MarketLoop
from core.risk_engine import PositionExposure, RiskEngine, RiskPolicy, RiskRequest, RiskState
from core.valuation_snapshot import build_valuation_snapshot
from tests.intelligence.test_task009_regime_tracking import T0, Brain, Execution, Feed
from tests.test_block5c_upstream_sizing_authority import seed_state
from tests.test_task018_forex_foundation import NOW, FakeMt5
from tools.refresh_mt5_instrument_rules import refresh_mt5_instrument_rules

ROOT = Path(__file__).resolve().parents[1]
V5 = "governance/policy/ATLAS_POLICY_MANIFEST_v5.json"
SID = mint_position_id("EURUSD", "short-1", "SHORT")


# ---------------------------------------------------------------- the position side


@pytest.mark.parametrize("action, side, opens, reduces", [
    ("BUY", "LONG", True, False), ("SELL", "LONG", False, True),
    ("SELL", "SHORT", True, False), ("BUY", "SHORT", False, True),
])
def test_each_action_and_side_either_opens_or_reduces(action, side, opens, reduces):
    assert opens_risk(action, side) is opens and reduces_risk(action, side) is reduces


def test_long_is_never_serialized_so_every_existing_payload_is_unchanged():
    request = ExecutionRequest("BTCUSDT", "BUY", 10, 20, request_id="r")
    assert "position_side" not in request.to_dict() and request.position_side == "LONG"
    short = ExecutionRequest("EURUSD", "SELL", 1.08, 0, request_id="s", position_side="short")
    assert short.to_dict()["position_side"] == "SHORT"
    assert ExecutionRequest.from_dict(short.to_dict()).position_side == "SHORT"
    result = ExecutionResult(success=True, status="PAPER_EXECUTED", action="BUY")
    assert "position_side" not in result.to_dict()
    with pytest.raises(ValueError):
        ExecutionRequest("EURUSD", "SELL", 1.08, 0, position_side="FLAT")


def test_a_short_has_its_own_lifetime_identity():
    assert SID.startswith("short:EURUSD:") and mint_position_id("EURUSD", "short-1") .startswith("long:")
    with pytest.raises(ValueError):
        mint_position_id("EURUSD", "x", "FLAT")


# ---------------------------------------------------------------- the margin book


def book(tmp_path, *, cash="10000", leverage=2, name="fx"):
    store = FinancialStateStore(tmp_path / f"{name}.json")
    store.initialize(D(cash), leverage=leverage)
    return ExecutionPortfolioFoundation(
        store, applied_archive=AppliedExecutionArchiveStore(tmp_path / f"{name}-applied.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / f"{name}-closed.jsonl"), leverage=leverage), store


def reopen(tmp_path, store, name="fx"):
    return ExecutionPortfolioFoundation(
        store, applied_archive=AppliedExecutionArchiveStore(tmp_path / f"{name}-applied.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / f"{name}-closed.jsonl"), leverage=None)


def fill(action, base, price, execution_id, *, side="SHORT", fee="0", position_id=SID):
    return ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id=execution_id, position_id=position_id,
        symbol="EURUSD", action=action, filled_price=price, filled_base_quantity=D(str(base)),
        filled_quote_notional=D(str(price)) * D(str(base)), fee_amount=D(str(fee)), fee_currency="USD",
        idempotency_key=execution_id, provenance_ref="test", position_side=side)


def apply(foundation, result, version=None):
    return foundation.apply_confirmed(result, risk_authorized=True, reservation_confirmed=True,
                                      expected_position_version=version)


def test_a_short_opens_with_a_sell_and_reserves_margin_like_a_long(tmp_path):
    foundation, _ = book(tmp_path)
    snap = apply(foundation, fill("SELL", 2000, D("1.08"), "e1", fee="2"))
    position = snap["positions"]["EURUSD"]
    assert position["side"] == "SHORT" and D(position["margin"]) == D("1080") and position["base_quantity"] == "2000"
    assert snap["cash"] == D("10000") - D("1080") - 2 and snap["equity"] == D("9998")
    assert snap["gross_exposure"] == D("2160.00")                                  # the absolute notional


@pytest.mark.parametrize("mark, unrealized", [("1.03", "100"), ("1.13", "-100"), ("1.08", "0")])
def test_a_short_gains_as_the_price_falls(tmp_path, mark, unrealized):
    foundation, _ = book(tmp_path)
    apply(foundation, fill("SELL", 2000, D("1.08"), "e1"))
    foundation.mark("EURUSD", D(mark))
    snap = foundation.snapshot()
    assert snap["unrealized_pnl"] == D(unrealized) and snap["equity"] == D("10000") + D(unrealized)
    assert snap["spendable_cash"] == snap["cash"] + min(D(unrealized), D("0"))     # a paper gain never funds risk
    assert position_unrealized(snap["positions"]["EURUSD"]) == D(unrealized)


@pytest.mark.parametrize("cover, gross", [("1.05", "60"), ("1.11", "-60")])
def test_a_cover_realizes_entry_minus_exit(tmp_path, cover, gross):
    foundation, _ = book(tmp_path)
    apply(foundation, fill("SELL", 2000, D("1.08"), "e1"))
    snap = apply(foundation, fill("BUY", 2000, D(cover), "e2", fee="1"), version=1)
    assert snap["positions"] == {} and snap["realized_gross_pnl"] == D(gross)
    assert snap["cash"] == D("10000") + D(gross) - 1
    closed = foundation._closed_by_position_id[SID]
    assert closed["side"] == "SHORT" and D(closed["gross_pnl"]) == D(gross)


def test_a_partial_cover_releases_margin_and_cost_pro_rata(tmp_path):
    foundation, _ = book(tmp_path)
    apply(foundation, fill("SELL", 3000, D("1.1"), "e1"))                          # margin 1650
    snap = apply(foundation, fill("BUY", 1000, D("1.0"), "e2"), version=1)         # gross +100
    position = snap["positions"]["EURUSD"]
    assert position["side"] == "SHORT" and position["base_quantity"] == "2000"
    assert D(position["margin"]) == D("1650") - D("1650") * 1000 / 3000
    assert snap["realized_gross_pnl"] == D("100.0")


@pytest.mark.parametrize("second", [
    fill("BUY", 1000, D("1.0"), "e2", side="LONG"),                     # a long add on a short
    fill("SELL", 1000, D("1.0"), "e2", side="LONG"),                    # a long reduction of a short
])
def test_sides_never_mix(tmp_path, second):
    foundation, store = book(tmp_path)
    apply(foundation, fill("SELL", 1000, D("1.1"), "e1"))
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="POSITION_SIDE_CONFLICT"):
        apply(foundation, second, version=1)
    assert store.path.read_bytes() == before and foundation.ready


def test_a_cash_book_refuses_a_short_and_writes_nothing(tmp_path):
    foundation, store = book(tmp_path, leverage=1)
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="SHORT_NOT_PERMITTED_IN_CASH_BOOK"):
        apply(foundation, fill("SELL", 1000, D("1.0"), "e1"))
    assert store.path.read_bytes() == before and foundation.ready


@pytest.mark.parametrize("edit", [
    lambda p: p["positions"]["EURUSD"].update(side="LONG"),
    lambda p: p["positions"]["EURUSD"].update(side="short"),
    lambda p: p["positions"]["EURUSD"].update(side=None),
])
def test_a_corrupt_side_is_never_ready(tmp_path, edit):
    foundation, store = book(tmp_path)
    apply(foundation, fill("SELL", 1000, D("1.0"), "e1"))
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    edit(payload)
    store.save(payload)
    assert not reopen(tmp_path, store).ready


def test_an_interrupted_cover_is_completed_with_the_short_arithmetic(tmp_path):
    foundation, store = book(tmp_path)
    apply(foundation, fill("SELL", 1000, D("1.2"), "e1"))
    cover = fill("BUY", 1000, D("1.0"), "e2")

    def crash():
        raise RuntimeError("killed")

    with pytest.raises(RuntimeError):
        foundation.apply_confirmed(cover, risk_authorized=True, reservation_confirmed=True,
                                   expected_position_version=1, before_final_persist=crash)
    snap = complete_interrupted_transition(
        store, applied_archive=AppliedExecutionArchiveStore(tmp_path / "fx-applied.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / "fx-closed.jsonl"), evidence=cover)
    assert snap["cash"] == D("10200") and snap["positions"] == {} and reopen(tmp_path, store).ready


# ---------------------------------------------------------------- RiskEngine


def state(*positions, equity="10000"):
    return RiskState(positions=positions, committed_quote=sum((p.quote_exposure for p in positions), D("0")),
                     current_equity=D(equity), peak_equity=D(equity), state_ready=True,
                     accounting_day_utc=datetime.now(UTC).date().isoformat(), policy_version="phase3-risk-v1")


def ask(action, side, *, allocation="1000", reduce_only=False, confidence="0.9"):
    return RiskRequest(symbol="EURUSD", action=action, confidence=D(confidence),
                       requested_quote_allocation=D(allocation), execution_price=D("1.0"), risk_bucket="HIGH",
                       reduce_only=reduce_only, position_side=side)


SHORT_HELD = PositionExposure("EURUSD", D("1000"), D("1.0"), D("1000"), side="SHORT")
LONG_HELD = PositionExposure("EURUSD", D("1000"), D("1.0"), D("1000"))
ON = RiskPolicy(total_capital=D("10000"), leverage=2, shorts_enabled=True)


def test_shorts_are_refused_unless_the_policy_allows_them():
    off = RiskEngine(RiskPolicy(total_capital=D("10000"), leverage=2)).evaluate(ask("SELL", "SHORT"), state())
    assert off.reason_code == "SHORT_NOT_PERMITTED" and not off.approved
    on = RiskEngine(ON).evaluate(ask("SELL", "SHORT"), state())
    assert on.approved and on.approved_allocation == D("1000")
    with pytest.raises(ValueError, match="margin book"):
        RiskPolicy(total_capital=D("10000"), shorts_enabled=True)


def test_a_short_passes_the_same_new_risk_gates_as_a_long():
    engine = RiskEngine(ON)
    for side, action in (("SHORT", "SELL"), ("LONG", "BUY")):
        low = engine.evaluate(ask(action, side, confidence="0.1"), state())
        assert not low.approved and low.reason_code == engine.evaluate(ask("BUY", "LONG", confidence="0.1"),
                                                                       state()).reason_code
    assert engine.evaluate(ask("SELL", "SHORT"), state(LONG_HELD)).reason_code == "DUPLICATE_OPEN_POSITION"
    assert engine.evaluate(ask("BUY", "LONG"), state(SHORT_HELD)).reason_code == "DUPLICATE_OPEN_POSITION"


def test_a_cover_is_a_reduction_judged_against_the_short_only():
    engine = RiskEngine(ON)
    cover = engine.evaluate(ask("BUY", "SHORT", reduce_only=True, confidence="0"), state(SHORT_HELD))
    assert cover.approved and cover.reason_code == "RISK_REDUCTION_APPROVED"
    too_big = engine.evaluate(ask("BUY", "SHORT", allocation="1001", reduce_only=True), state(SHORT_HELD))
    assert too_big.reason_code == "INVALID_RISK_REDUCTION"
    wrong_side = engine.evaluate(ask("BUY", "SHORT", reduce_only=True), state(LONG_HELD))
    assert wrong_side.reason_code == "INVALID_RISK_REDUCTION"
    unheld = engine.evaluate(ask("BUY", "SHORT"), state())
    assert unheld.reason_code == "NON_RISK_REDUCING_COVER"
    assert engine.evaluate(ask("SELL", "LONG", reduce_only=True), state(LONG_HELD)).approved   # longs unchanged


# ---------------------------------------------------------------- NB-4 / NB-5 for a bearish decision


def evidence(source, action, *, symbol="EURUSD"):
    return Evidence(f"{source}-1", source, "1", symbol, action, D("1"), NOW - timedelta(seconds=1))


def test_missing_agents_never_raise_a_sell_s_confidence_nb4_nb5():
    fusion = SignalFusion(FusionPolicy(weights={"a": D("1"), "b": D("1"), "c": D("1")}))
    full = fusion.fuse("EURUSD", [evidence(s, Action.SELL) for s in "abc"], now=NOW)
    one_missing = fusion.fuse("EURUSD", [evidence(s, Action.SELL) for s in "ab"], now=NOW)
    only_one = fusion.fuse("EURUSD", [evidence("a", Action.SELL)], now=NOW)
    assert full.action == Action.SELL and full.confidence == D("1")
    assert full.confidence > one_missing.confidence > only_one.confidence           # expected roster denominator
    mixed = fusion.fuse("EURUSD", [evidence("a", Action.SELL), evidence("b", Action.BUY),
                                   evidence("c", Action.SELL)], now=NOW)
    assert mixed.confidence < full.confidence and mixed.disagreement > 0


# ---------------------------------------------------------------- end to end through ExecutionManager


@pytest.fixture
def forex_app(tmp_path, monkeypatch):
    rules = tmp_path / "instrument_rules_mt5.json"
    refresh_mt5_instrument_rules(destination=rules, now=datetime.now(UTC),
                                 provider=Mt5MarketDataProvider(mt5_module=FakeMt5(), clock=lambda: NOW))
    monkeypatch.setattr(application_module, "FOREX_INSTRUMENT_RULES_PATH", rules)
    app = AtlasApplication(state_directory=seed_state(tmp_path / "forex" / "state", leverage=2), market="FOREX")
    app.execution.start()
    yield app
    app.stop()


def decision(action, request_id, *, price=1.08, confidence=80, proposed=None):
    out = {"symbol": "EURUSD", "action": action, "price": price, "amount": 0, "confidence": confidence,
           "risk": "HIGH", "request_id": request_id, "strategy": "T"}
    if proposed is not None:
        out["proposed_quote_allocation"] = proposed
    return out


def test_a_sell_opens_a_short_and_a_buy_covers_it_end_to_end(forex_app):
    manager, book_ = forex_app.execution, forex_app.portfolio_foundation
    opened = manager.execute(decision("SELL", "s-1", proposed="2000"))
    assert opened["status"] == "PAPER_EXECUTED", opened
    position = book_.snapshot()["positions"]["EURUSD"]
    assert position["side"] == "SHORT" and position["position_id"].startswith("short:EURUSD:")
    assert D(position["margin"]) == D(position["cost_quote"]) / 2
    covered = manager.execute(decision("BUY", "c-1", price=1.07, confidence=0))     # a cover needs no confidence
    assert covered["status"] == "PAPER_EXECUTED", covered
    snap = book_.snapshot()
    assert snap["positions"] == {} and snap["realized_gross_pnl"] > 0


def test_a_low_confidence_short_is_refused_before_risk(forex_app):
    refused = forex_app.execution.execute(decision("SELL", "s-low", confidence=10, proposed="2000"))
    assert refused["status"] == "REJECTED" and refused["reason"] == "LOW_CONFIDENCE"
    assert forex_app.portfolio_foundation.snapshot()["positions"] == {}


def test_an_unsized_short_is_refused(forex_app):
    refused = forex_app.execution.execute(decision("SELL", "s-unsized"))
    assert refused["reason"] == "UNSIZED_REQUEST_REJECTED"


def test_a_caller_cannot_choose_the_side(forex_app):
    manager = forex_app.execution
    assert manager.execute(decision("SELL", "s-1", proposed="2000"))["status"] == "PAPER_EXECUTED"
    # a BUY that claims to open a long on a held short is still a cover of that short
    forged = {**decision("BUY", "c-forged", price=1.07, confidence=0), "position_side": "LONG"}
    assert manager.execute(forged)["status"] == "PAPER_EXECUTED"
    assert forex_app.portfolio_foundation.snapshot()["positions"] == {}


def test_crypto_never_shorts(tmp_path):
    app = AtlasApplication(state_directory=seed_state(tmp_path / "state"))
    try:
        app.execution.start()
        assert app.risk_policy.shorts_enabled is False and app.market_loop.shorts_enabled is False
        result = app.execution.execute({**decision("SELL", "s-c", proposed="100"), "symbol": "BTCUSDT",
                                        "price": 50000})
        assert result["status"] == "REJECTED" and app.portfolio_foundation.snapshot()["positions"] == {}
    finally:
        app.stop()


# ---------------------------------------------------------------- MarketLoop


def loop(*, shorts=True, held=None, flat=True, blocked=None):
    market_loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["EURUSD"])
    market_loop.shorts_enabled = shorts
    market_loop._held_side = lambda symbol: held
    market_loop._sell_symbol_known_flat = lambda symbol: flat
    market_loop.market_entry_blocked = blocked
    return market_loop


def gate(market_loop, action, *, fresh=True):
    cutoff = datetime.fromtimestamp(T0 / 1000, UTC)
    close = T0 - 1 if fresh else T0 - 3_600_000
    return market_loop._symbol_execution_gate("EURUSD", {"action": action, "symbol": "EURUSD", "metadata": {}},
                                              [{"open_time": close - 59_999, "close_time": close}], cutoff)


def test_a_sell_of_a_pair_not_held_is_routed_as_a_short_only_when_shorts_are_on():
    assert gate(loop(shorts=False), "SELL")["reason"] == "NO_POSITION_TO_SELL"     # crypto: HOLD, as before
    routed = gate(loop(), "SELL")
    assert not (isinstance(routed, dict) and routed.get("status") == "SKIPPED")


def test_every_new_risk_gate_applies_to_a_short():
    assert gate(loop(blocked=lambda now: True), "SELL")["reason"] == "PRE_CLOSE_NO_NEW_RISK"
    assert gate(loop(), "SELL", fresh=False)["reason"] == "STALE_MARKET_DATA"


def test_a_cover_is_never_held_back_by_a_new_risk_gate():
    held_short = loop(held="SHORT", flat=False, blocked=lambda now: True)
    for result in (gate(held_short, "BUY"), gate(held_short, "BUY", fresh=False)):
        assert not (isinstance(result, dict) and result.get("status") == "SKIPPED")


def test_the_regime_gate_never_opens_a_short():
    from core.market_cycle import RegimeGateConfig

    market_loop = loop()
    market_loop.regime_gate = RegimeGateConfig(enabled=True)
    assert gate(market_loop, "SELL")["reason"] == "REGIME_GATE_LONG_ONLY"


def test_shorts_are_sized_like_buys():
    market_loop = loop()
    assert market_loop._opens_new_risk("EURUSD", "SELL") and market_loop._opens_new_risk("EURUSD", "BUY")
    covering = loop(held="SHORT", flat=False)
    assert not covering._opens_new_risk("EURUSD", "BUY") and not covering._opens_new_risk("EURUSD", "SELL")
    assert not loop(shorts=False)._opens_new_risk("EURUSD", "SELL")


# ---------------------------------------------------------------- the exit guard


class Book:
    def __init__(self, positions, *, cash="1080", used="1080"):
        self.positions, self.cash, self.used = positions, D(cash), D(used)

    def snapshot(self):
        unrealized = sum((position_unrealized(p) for p in self.positions.values()), D("0"))
        return {"positions": self.positions, "cash": self.cash, "used_margin": self.used,
                "equity": self.cash + self.used + unrealized}


class Manager:
    def __init__(self):
        self.calls = []

    def execute(self, decision_, _):
        self.calls.append(decision_)
        return {"status": "COMPLETED"}


CLOCK = 1_800_000_000.0


def short_position(entry="1.08", mark="1.08", base=2000):
    return {"base_quantity": str(base), "average_entry_price": entry, "position_id": SID, "side": "SHORT",
            "opened_at": "2026-10-28T10:00:00+00:00", "mark_price": mark,
            "cost_quote": str(D(str(base)) * D(entry))}


def guard(rules, positions=None):
    manager = Manager()
    return ExitGuard(manager, Book(positions or {"EURUSD": short_position()}), rules=rules, mode=ENFORCE,
                     clock=lambda: CLOCK), manager


def marks(price):
    return {"EURUSD": Mark(D(price), CLOCK - 5)}


@pytest.mark.parametrize("price, triggered", [("1.60", False), ("1.62", True), ("0.50", False)])
def test_a_short_is_stopped_out_when_the_price_rises(price, triggered):
    # margin 1080, cash 1080: equity = 2160 - 2000 x (price - 1.08), level 1 at 1.62
    exit_guard, manager = guard((ExitRule("so", RULE_STOP_OUT, D("1"), priority=SAFETY_EXIT),))
    outcome = exit_guard.run_once(marks(price))[0]
    assert (outcome["state"] == EXIT_TRIGGERED) is triggered
    if triggered:
        cover = manager.calls[0]
        assert cover["action"] == "BUY" and cover["reduce_only"] is True and cover["exit_priority"] == SAFETY_EXIT


def test_max_loss_measures_a_short_s_loss_as_a_rising_price():
    exit_guard, manager = guard((ExitRule("ml", RULE_MAX_LOSS_PCT, D("0.05")),))
    assert exit_guard.run_once(marks("1.02"))[0]["state"] == EXIT_NOT_TRIGGERED      # a 5.6 % gain
    assert exit_guard.run_once(marks("1.14"))[0]["state"] == EXIT_TRIGGERED          # a 5.6 % loss
    assert manager.calls[0]["action"] == "BUY"


def test_the_weekend_close_covers_a_short():
    exit_guard, manager = guard((ExitRule("wk", RULE_WEEKEND_CLOSE, None, minutes=30,
                                          in_window=lambda now, minutes: True),))
    assert exit_guard.run_once(marks("1.08"))[0]["state"] == EXIT_TRIGGERED
    assert manager.calls[0]["action"] == "BUY" and manager.calls[0]["reduce_only"] is True


def test_a_short_and_a_long_are_stopped_out_largest_loss_first():
    long_position = {**short_position(), "position_id": "long:GBPUSD:x", "side": "LONG", "base_quantity": "1000",
                     "average_entry_price": "1.30", "mark_price": "1.30", "cost_quote": "1300"}
    long_position.pop("side")
    exit_guard, manager = guard((ExitRule("so", RULE_STOP_OUT, D("1"), priority=SAFETY_EXIT),),
                                {"EURUSD": short_position(), "GBPUSD": long_position})
    exit_guard.portfolio_foundation.used = D("1730")
    exit_guard.portfolio_foundation.cash = D("0")
    exit_guard.run_once({"EURUSD": Mark(D("1.20"), CLOCK - 5), "GBPUSD": Mark(D("1.10"), CLOCK - 5)})
    assert [(c["symbol"], c["action"]) for c in manager.calls] == [("EURUSD", "BUY"), ("GBPUSD", "SELL")]


# ---------------------------------------------------------------- valuation


def test_the_valuation_counts_a_short_s_loss():
    snap = build_valuation_snapshot(book_positions={"EURUSD": short_position()}, marks={"EURUSD": "1.18"},
                                    ledger_equity=D("10000"), peak_equity=D("10000"), realized_daily=D("0"),
                                    close_fee_rate=0, as_of="2026-10-28T10:00:00+00:00")
    assert snap.marked_equity == D("9800")                                           # 2000 x (1.08 - 1.18)


# ---------------------------------------------------------------- manifest v5


@pytest.mark.parametrize("market", ["CRYPTO", "FOREX"])
def test_the_application_built_as_main_py_matches_v5(tmp_path, monkeypatch, market):
    import main
    from tests.test_phase2_g2_exp002_grant import production_kwargs

    leverage = 2 if market == "FOREX" else 1
    kwargs = production_kwargs(tmp_path, monkeypatch)
    app = AtlasApplication(**{**kwargs, "state_directory": seed_state(tmp_path / "state", leverage=leverage),
                              "market": market})
    try:
        check = main.apply_policy_manifest(app)
        assert check.status == pm.MATCH, check.to_dict()
        assert check.owner_approval == f"{pm.OWNER_RATIFIED}:{pm.V5_RATIFICATION_REGISTRY_ID}"
        runtime = pm.runtime_policy(app)
        assert runtime["shorts_enabled"] is (market == "FOREX")
        bad = pm.verify({**runtime, "shorts_enabled": market != "FOREX"})
        assert bad.status == pm.POLICY_MISMATCH and [m[0] for m in bad.mismatches] == ["shorts_enabled"]
        app.market_loop.shorts_enabled = market != "FOREX"                           # loop and policy disagree
        assert pm.runtime_policy(app)["shorts_enabled"] == pm.UNREADABLE
    finally:
        app.stop()


def test_v5_is_active_and_its_chain_is_sealed():
    assert pm.MANIFEST_PATH == ROOT / V5 and pm.EXPECTED_MANIFEST_VERSION == 5 and FOREX_SHORTS_ENABLED is True
    manifest = json.loads((ROOT / V5).read_text(encoding="utf-8"))
    policy = manifest["policy"]
    assert set(policy) == set(pm.CRITICAL_SWITCHES_V5) == set(pm.CRITICAL_SWITCHES_V4) | {"shorts_enabled"}
    assert policy["shorts_enabled"] == {"by_market": {"CRYPTO": False, "FOREX": True}}
    assert policy["execution_mode"] == "PAPER" and policy["live_execution_enabled"] is False
    v4 = json.loads(pm.MANIFEST_V4_PATH.read_text(encoding="utf-8"))["policy"]
    assert {k: x for k, x in policy.items() if k != "shorts_enabled"} == v4
    record = json.loads((ROOT / pm.V5_RATIFICATION_REGISTRY_PATH).read_text(encoding="utf-8"))
    ratification = record[pm.V5_RATIFICATION_RECORD_KEY]
    assert ratification["status"] == "RATIFIED" and ratification["live_effect"] == "NONE"
    assert ratification["manifest_pin"] == {"manifest_file_sha256": pm.file_sha256((ROOT / V5).read_bytes()),
                                            "manifest_version": 5}
    assert pm.file_sha256((ROOT / pm.V5_RATIFICATION_REGISTRY_PATH).read_bytes()) == pm.V5_RATIFICATION_REGISTRY_SHA256
    assert record["grant_task_026_forex_short_selling"]["grants_trading_authority"] is False


def test_finalizing_a_short_needs_its_reservation_and_stays_within_the_approval(forex_app):
    manager = forex_app.execution
    request = ExecutionRequest("EURUSD", "SELL", 1.08, 0, confidence=80, risk="HIGH", request_id="s-fin",
                               position_side="SHORT", approved_quote_allocation=D("1080"))
    manager._risk_admissions[request.request_id] = manager._risk_admission_key(request)
    evidence = {"success": True, "status": "PAPER_EXECUTED", "execution_id": "x-fin", "symbol": "EURUSD",
                "action": "SELL", "position_side": "SHORT", "position_id": mint_position_id("EURUSD", "s-fin", "SHORT"),
                "filled_price": 1.08, "filled_base_quantity": "1000", "filled_quote_notional": "1080",
                "fee_amount": "0", "timestamp": datetime.now(UTC).isoformat()}
    with pytest.raises(PermissionError, match="CAPITAL_RESERVATION_NOT_CONFIRMED"):
        manager._finalize_durable_financial_state(request=request, result=dict(evidence))
    manager.reservation_ledger.reserve(request.request_id, request.request_id, D("1000"))
    manager._risk_admissions[request.request_id] = manager._risk_admission_key(request)
    request.approved_quote_allocation = D("1000")
    manager._risk_admissions[request.request_id] = manager._risk_admission_key(request)
    with pytest.raises(PermissionError, match="SETTLEMENT_EXCEEDS_APPROVED_ALLOCATION"):
        manager._finalize_durable_financial_state(request=request, result=dict(evidence))
    assert forex_app.portfolio_foundation.snapshot()["positions"] == {}


def test_risk_check_rederives_a_forged_side_from_the_book(forex_app):
    manager = forex_app.execution
    assert manager.execute(decision("SELL", "s-1", proposed="2000"))["status"] == "PAPER_EXECUTED"
    forged = ExecutionRequest("EURUSD", "BUY", 1.07, 0, confidence=0, risk="HIGH", request_id="c-direct",
                              position_side="LONG")
    verdict = manager.risk_check(forged)
    assert forged.position_side == "SHORT" and forged.reduce_only is True
    assert verdict["approved"] is True, verdict


# ---------------------------------------------------------------- recovery (review F1)


class SimulatedCrash(BaseException):
    """A process kill at a commit boundary: no ``except Exception`` sees it."""


def crash_on(monkeypatch, target, name, *, after=False):
    original = getattr(target, name)

    def crashing(*args, **kwargs):
        if after:
            original(*args, **kwargs)
        raise SimulatedCrash(name)

    monkeypatch.setattr(target, name, crashing)


@pytest.fixture
def forex_state(tmp_path, monkeypatch):
    monkeypatch.delenv("ATLAS_LOG_DIRECTORY", raising=False)
    rules = tmp_path / "instrument_rules_mt5.json"
    refresh_mt5_instrument_rules(destination=rules, now=datetime.now(UTC),
                                 provider=Mt5MarketDataProvider(mt5_module=FakeMt5(), clock=lambda: NOW))
    monkeypatch.setattr(application_module, "FOREX_INSTRUMENT_RULES_PATH", rules)
    return seed_state(tmp_path / "forex" / "state", leverage=2)


def forex_app_at(state_dir):
    app = AtlasApplication(state_directory=state_dir, evidence_directory=state_dir.parent / "evidence",
                           market="FOREX")
    app.execution.start()
    return app


def recover(state_dir):
    from tools.reconcile_execution_authorities import reconcile

    return reconcile(state_dir, apply=True, execution_mode="PAPER")


def test_an_interrupted_short_open_is_recovered_from_its_applied_evidence(forex_state, monkeypatch):
    from core.capital_reservation import ReservationStatus
    from tools.reconcile_execution_authorities import ReconciliationOutcome, RecoveryClass

    app = forex_app_at(forex_state)
    with monkeypatch.context() as patch, pytest.raises(SimulatedCrash):
        crash_on(patch, app.execution.reservation_ledger, "commit")            # applied; reservation not settled
        app.execution.execute(decision("SELL", "s-1", proposed="2000"))
    position = app.portfolio_foundation.snapshot()["positions"]["EURUSD"]
    assert position["side"] == "SHORT"
    outcome = recover(forex_state)
    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.recovery_class == RecoveryClass.COMMIT_APPLIED_EVIDENCE.value
    assert outcome.risk_accounting == "NOT_APPLICABLE"
    restarted = forex_app_at(forex_state)
    try:
        assert restarted.execution.execution_halted is False, restarted.execution.halt_reason
        assert restarted.execution.recovery_required is False
        assert restarted.reservation_ledger.get("s-1").status is ReservationStatus.COMMITTED
        assert restarted.portfolio_foundation.snapshot()["positions"]["EURUSD"] == position
    finally:
        restarted.stop()


def test_an_interrupted_cover_has_its_realized_result_booked(forex_state, monkeypatch):
    from tools.reconcile_execution_authorities import ReconciliationOutcome

    app = forex_app_at(forex_state)
    assert app.execution.execute(decision("SELL", "s-1", proposed="2000"))["status"] == "PAPER_EXECUTED"
    with monkeypatch.context() as patch, pytest.raises(SimulatedCrash):
        crash_on(patch, app.execution, "_mirror_paper_book")                   # applied and booked; not mirrored
        app.execution.execute(decision("BUY", "c-1", price=1.07, confidence=0))
    assert app.portfolio_foundation.snapshot()["positions"] == {}
    outcome = recover(forex_state)
    assert outcome.outcome is ReconciliationOutcome.RECOVERED, outcome
    assert outcome.risk_accounting in ("ALREADY_RECORDED", "RECORD")           # never NOT_APPLICABLE for a cover
    restarted = forex_app_at(forex_state)
    try:
        assert restarted.execution.execution_halted is False
    finally:
        restarted.stop()


def test_a_direct_risk_check_cannot_slip_a_short_past_the_manifest_block(forex_app):
    # review F2: the side is derived from the book before the new-risk gates, whoever built the request
    manager = forex_app.execution
    manager.policy_manifest_block = "POLICY_MANIFEST_POLICY_MISMATCH"
    forged = ExecutionRequest("EURUSD", "SELL", 1.08, 0, confidence=80, risk="HIGH", request_id="s-forged",
                              position_side="LONG", proposed_quote_allocation=D("2000"))
    verdict = manager.risk_check(forged)
    assert verdict["approved"] is False and verdict["reason"] == "POLICY_MANIFEST_POLICY_MISMATCH"
    assert forged.position_side == "SHORT" and "s-forged" not in manager._risk_admissions
