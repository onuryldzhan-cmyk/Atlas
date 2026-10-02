"""T-0014 (owner 2026-10-03): golden characterization of ExecutionManager.risk_check.

Generated against the pre-refactor code (one 432-line body). For every scenario the
split must reproduce exactly: each returned verdict, the request fields risk_check
writes (approved_quote_allocation, reduce_only), the recorded admissions, capital
reservations, last_risk_decision, stats and error trail. Volatile values are
normalized by tests.test_execute_decision_golden.norm; nothing else is.

Regenerate ONLY for an intended, approved behaviour change:
    python -c "import json, tempfile, pathlib; from tests.test_risk_check_golden import collect, GOLDEN; \
GOLDEN.write_text(json.dumps(collect(pathlib.Path(tempfile.mkdtemp())), indent=1, sort_keys=True))"
"""
from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from core.execution_models import ExecutionRequest
from tests.test_block5e_fee_settlement_accounting import application
from tests.test_execute_decision_golden import _fail, norm

GOLDEN = Path(__file__).with_name("golden") / "risk_check_golden.json"


def _req(action="BUY", amount=1000.0, price=10.0, confidence=90.0, risk="MEDIUM", rid="r1", symbol="BTCUSDT", **kw):
    request = ExecutionRequest(symbol, action, price, amount, confidence=confidence, risk=risk, request_id=rid)
    for k, v in kw.items():
        setattr(request, k, v)
    return request


def _rules_stub(ex, **override):
    real = ex.instrument_rules.get("BTCUSDT")
    fields = {f: getattr(real, f) for f in ("price_tick", "quantity_step", "min_quantity", "min_notional",
                                             "digest", "source_version")}
    fields.update({k: v for k, v in override.items() if k != "upper"})
    upper = override.get("upper")
    stub = SimpleNamespace(**fields, upper_bound_violation=(lambda **kw: upper) if upper is not None
                           else real.upper_bound_violation)
    return SimpleNamespace(get=lambda symbol: stub if symbol == "BTCUSDT" else None)


def _hold(app, ex):
    """Buy once through the full pipeline so a SELL has a durable position."""
    assert ex.execute({"symbol": "BTCUSDT", "action": "BUY", "price": 10.0, "amount": 1000, "confidence": 90.0,
                       "risk": "MEDIUM", "request_id": "seed"})["status"] == "PAPER_EXECUTED"


# ----------------------------------------------------------------------------- scenarios
def s_no_risk_engine(app, ex):
    ex.risk_engine = None
    return [_req()]


def s_ledger_not_ready(app, ex):
    ex.reservation_ledger = SimpleNamespace(ready=False)
    return [_req()]


def s_no_risk_state_store(app, ex):
    ex.risk_state_store = None
    return [_req()]


def s_rollover_raises_but_continues(app, ex):
    ex._auto_rollover_risk_accounting_day = _fail("rollover boom")
    return [_req()]


def s_risk_state_raises(app, ex):
    ex._derive_risk_state = _fail("state boom")
    return [_req()]


def s_requested_raises(app, ex):
    ex._requested_quote_allocation = _fail("requested boom")
    return [_req()]


def s_unsized_buy(app, ex):
    return [_req(amount=0)]


def s_unsized_sell_unheld(app, ex):
    return [_req("SELL", amount=0, rid="s0")]


def s_engine_rejects_low_confidence(app, ex):
    return [_req(confidence=10.0)]


def s_engine_rejects_critical_risk(app, ex):
    return [_req(risk="CRITICAL")]


def s_engine_raises(app, ex):
    ex.risk_engine.evaluate = _fail("engine boom")
    return [_req()]


def s_allocation_mismatch(app, ex):
    real = ex.risk_engine.evaluate

    def evaluate(rr, state):
        d = real(rr, state)
        return dataclasses.replace(d, approved_allocation=d.approved_allocation + Decimal("1")) if d.approved else d
    ex.risk_engine.evaluate = evaluate
    return [_req()]


def s_no_instrument_rules(app, ex):
    ex.instrument_rules = SimpleNamespace(get=lambda symbol: None)
    return [_req()]


def s_instrument_rules_none(app, ex):
    ex.instrument_rules = None
    return [_req()]


def s_price_tick_misaligned(app, ex):
    ex.instrument_rules = _rules_stub(ex, price_tick=Decimal("0.5"))
    return [_req(price=10.25)]


def s_position_limit(app, ex):
    ex._can_open_position = lambda symbol: False
    return [_req()]


def s_below_quantity_step(app, ex):
    ex.instrument_rules = _rules_stub(ex, quantity_step=Decimal("1000"))
    return [_req()]


def s_below_min_quantity(app, ex):
    ex.instrument_rules = _rules_stub(ex, min_quantity=Decimal("1000"))
    return [_req()]


def s_below_min_notional(app, ex):
    ex.instrument_rules = _rules_stub(ex, min_notional=Decimal("100000"))
    return [_req()]


def s_above_upper_bound(app, ex):
    ex.instrument_rules = _rules_stub(ex, upper=("ABOVE_MAX_QUANTITY", {"max_quantity": "1"}))
    return [_req()]


def s_free_capital_raises(app, ex):
    ex._durable_free_quote_capital = _fail("capital boom")
    return [_req()]


def s_insufficient_capital(app, ex):
    ex._durable_free_quote_capital = lambda exclude=None: Decimal("5")
    return [_req()]


def s_free_capital_unknown(app, ex):
    ex._durable_free_quote_capital = lambda exclude=None: None
    return [_req()]


def s_reserve_raises(app, ex):
    ex.reservation_ledger.reserve = _fail("reserve boom")
    return [_req()]


def s_reserve_not_reserved(app, ex):
    real = ex.reservation_ledger.reserve

    def reserve(*args):
        r = real(*args)
        return SimpleNamespace(status="NOT_RESERVED", amount=r.amount)
    ex.reservation_ledger.reserve = reserve
    return [_req()]


def s_buy_approved(app, ex):
    return [_req()]


def s_buy_approved_twice_same_id(app, ex):
    return [_req(), _req()]


def s_buy_with_fee(app, ex):
    ex.paper_fee_rate = Decimal("0.001")
    return [_req()]


def s_buy_caller_reduce_only_rederived(app, ex):
    return [_req(reduce_only=True)]


def s_buy_stale_approval_cleared_on_reject(app, ex):
    return [_req(confidence=10.0, approved_quote_allocation=Decimal("999"))]


def s_sell_full_exit_held(app, ex):
    _hold(app, ex)
    return [_req("SELL", amount=0, rid="s1")]


def s_sell_partial_held(app, ex):
    _hold(app, ex)
    return [_req("SELL", amount=300, rid="s2")]


def s_sell_more_than_held(app, ex):
    _hold(app, ex)
    return [_req("SELL", amount=50000, rid="s3")]


def s_buy_more_when_held(app, ex):
    _hold(app, ex)
    return [_req(rid="b2")]


def s_reevaluate_near_capital_bound(app, ex):
    # A request re-evaluated near the durable bound must not be charged for its own reservation.
    return [_req(amount=2000.0), _req(amount=2000.0)]


s_reevaluate_near_capital_bound.seed = {"cash": "2500"}


def s_other_symbol(app, ex):
    return [_req(symbol="ETHUSDT", rid="e1")]


SCENARIOS: dict[str, Callable[[Any, Any], list]] = {
    name.removeprefix("s_"): fn for name, fn in sorted(globals().items()) if name.startswith("s_") and callable(fn)
}


def collect(root: Path) -> dict[str, Any]:
    out = {}
    for name, scenario in SCENARIOS.items():
        app = application(root / name, **getattr(scenario, "seed", {}))
        ex = app.execution
        ex.start()
        requests = scenario(app, ex)
        calls = []
        for request in requests:
            try:
                verdict = ex.risk_check(request=request, market_state=None)
            except Exception as exc:  # pinned too: an escaping exception is behaviour
                verdict = {"raised": type(exc).__name__, "message": str(exc)}
            calls.append({"verdict": verdict, "approved_quote_allocation": request.approved_quote_allocation,
                          "reduce_only": request.reduce_only, "amount": request.amount})
        ledger = ex.reservation_ledger
        reservations = {}
        if hasattr(ledger, "get"):
            for rid in ("r1", "s0", "s1", "s2", "s3", "b2", "e1", "seed"):
                r = ledger.get(rid)
                if r is not None:
                    reservations[rid] = [getattr(r.status, "value", r.status), str(r.amount)]
        out[name] = norm({
            "calls": calls,
            "admissions": sorted(ex._risk_admissions),
            "reservations": reservations,
            "last_risk_decision": ex.last_risk_decision,
            "stats": dict(ex.stats),
            "errors": [[e.get("phase"), e.get("error")] for e in ex.errors],
        })
    return out


def test_risk_check_matches_golden(tmp_path):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = collect(tmp_path)
    assert sorted(actual) == sorted(expected), "scenario set changed"
    for name in sorted(expected):
        assert actual[name] == expected[name], f"scenario {name!r} diverged from the golden record"


def test_golden_covers_every_risk_check_return():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    reasons = {c["verdict"].get("reason") for snap in expected.values() for c in snap["calls"]}
    assert {"CANONICAL_RISK_SERVICE_REQUIRED", "CAPITAL_RESERVATION_STATE_NOT_READY",
            "RISK_ACCOUNTING_STATE_STORE_REQUIRED", "RISK_STATE_RESTORATION_FAILED", "UNSIZED_REQUEST_REJECTED",
            "NO_POSITION_TO_SELL", "RISK_ALLOCATION_MISMATCH", "INSTRUMENT_RULES_UNAVAILABLE",
            "PRICE_TICK_MISALIGNED", "POSITION_LIMIT", "QUANTITY_BELOW_VENUE_MINIMUM",
            "NOTIONAL_BELOW_VENUE_MINIMUM", "ABOVE_MAX_QUANTITY", "DURABLE_CAPITAL_STATE_UNAVAILABLE",
            "INSUFFICIENT_DURABLE_CAPITAL", "CAPITAL_RESERVATION_FAILED", "RISK_APPROVED"} <= reasons, reasons
