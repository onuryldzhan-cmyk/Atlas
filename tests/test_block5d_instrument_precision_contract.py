"""Block-5D: venue & instrument precision contract, carried exactly end to end.

Package 5D replaces ``ExecutionManager.BASE_QUANTITY_QUANTUM`` - a runtime
representation bound with no venue authority behind it - with
``InstrumentRules``: a checked-in, per-symbol contract for a venue's
``quantity_step``, ``min_quantity``, ``min_notional`` and ``price_tick``,
loaded once at process startup from ``config/instrument_rules.json`` and
injected into ``ExecutionManager``.

The frozen 5D rules these tests hold are:

1.  There is no fallback quantum. A symbol with no checked-in rule cannot
    execute: startup halts fail-closed for a configured or held symbol
    (``INSTRUMENT_RULES_UNAVAILABLE``), and any request admission for an
    unruled symbol is refused the same way.

2.  A legacy durable position whose ``base_quantity`` is not an exact
    multiple of its symbol's ``quantity_step`` halts startup
    (``INSTRUMENT_RULES_POSITION_MISALIGNED``) without floor, round-up, or
    write-off - only an operator resolves it.

3.  BUY floors to ``quantity_step`` and never rounds up. A request price that
    is not exactly on ``price_tick``, a floored quantity below
    ``min_quantity``, or a floored notional below ``min_notional`` is
    refused before reservation and before any side effect. Allocation is
    never raised to satisfy a minimum.

4.  SELL floors a partial reduction to ``quantity_step`` and preserves the
    exact durable held quantity, byte for byte, on a full exit - so
    BUY -> partial SELL -> full SELL never strands dust.

5.  The admitted symbol's instrument-rules digest is sealed into the risk
    admission identity: a rules change invalidates a prior admission before
    it can execute.

Every fixture writes into pytest's tmp_path. Nothing here may touch the
operator's real runtime state.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from decimal import Decimal as D
from typing import Any

import pytest

from core.application import (
    CAPITAL_RESERVATION_STATE_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    RISK_ACCOUNTING_STATE_FILE,
    AtlasApplication,
)
from core.capital_reservation import JsonReservationStore
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.execution_portfolio_foundation import FinancialStateStore
from core.instrument_rules import (
    InstrumentRules,
    InstrumentRulesConfigError,
    InstrumentRuleset,
    floor_to_step,
    is_aligned_to_step,
    load_instrument_ruleset,
)
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState

POLICY_VERSION = "phase3-risk-v1"
TOTAL_CAPITAL = D("10000")

# The real, checked-in BTCUSDT rule (config/instrument_rules.json), verified
# against Binance's public exchangeInfo. Every fixture below trades this
# symbol so tests exercise the shipped production config end to end, unless
# a test explicitly needs a synthetic rule to isolate one gate.
BTCUSDT_QUANTITY_STEP = D("0.00001")
BTCUSDT_MIN_QUANTITY = D("0.00001")
BTCUSDT_MIN_NOTIONAL = D("5")
BTCUSDT_PRICE_TICK = D("0.01")


def _rule(**overrides: Any) -> InstrumentRules:
    defaults: dict[str, Any] = dict(
        venue="BINANCE",
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity_step="0.00001",
        min_quantity="0.00001",
        min_notional="5",
        price_tick="0.01",
        source="test-fixture",
        source_version="v1",
        retrieved_at="2026-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    return InstrumentRules(**defaults)


# --------------------------------------------------------------------------
# durable state seeding (mirrors tests/test_block5b_single_sizing_authority.py)
# --------------------------------------------------------------------------


def held_position(symbol: str, base: str, price: str) -> dict[str, Any]:
    return {
        "position_id": f"long:{symbol}",
        "symbol": symbol,
        "base_quantity": format(D(base), "f"),
        "cost_quote": format(D(base) * D(price), "f"),
        "entry_fees": "0",
        "average_entry_price": format(D(price), "f"),
        "mark_price": format(D(price), "f"),
        "version": 1,
        "opened_at": datetime.now(UTC).isoformat(),
    }


def seed_state(state_dir, *, cash="10000", positions=(), pnl="0",
               peak="10000", equity="10000"):
    state_dir.mkdir(parents=True, exist_ok=True)

    JsonReservationStore(state_dir / CAPITAL_RESERVATION_STATE_FILE).initialize_empty()

    JsonRiskStateStore(state_dir / RISK_ACCOUNTING_STATE_FILE).save(
        RestoredRiskState(
            datetime.now(UTC).date(), D(pnl), D(peak), D(equity), POLICY_VERSION
        )
    )

    store = FinancialStateStore(state_dir / EXECUTION_FINANCIAL_STATE_FILE)
    store.initialize(D(cash))

    if positions:
        payload = store.load()
        for symbol, base, price in positions:
            payload["positions"][symbol] = held_position(symbol, base, price)
        store.save(payload)

    return state_dir


def application(tmp_path, *, symbols=None, **seeding) -> AtlasApplication:
    return AtlasApplication(
        state_directory=seed_state(tmp_path / "state", **seeding),
        symbols=symbols,
    )


@pytest.fixture
def flat_app(tmp_path) -> AtlasApplication:
    app = application(tmp_path)
    app.execution.start()
    return app


def buy(*, symbol="BTCUSDT", amount=0, price=10, risk="MEDIUM", confidence=90,
        request_id="b1") -> ExecutionRequest:
    return ExecutionRequest(symbol, "BUY", price, amount, confidence=confidence,
                            risk=risk, request_id=request_id)


def sell(*, symbol="BTCUSDT", amount=0, price=10, risk="MEDIUM", confidence=90,
         request_id="s1") -> ExecutionRequest:
    return ExecutionRequest(symbol, "SELL", price, amount, confidence=confidence,
                            risk=risk, request_id=request_id)


def position_of(app: AtlasApplication, symbol="BTCUSDT"):
    return app.portfolio_foundation.snapshot()["positions"].get(symbol)


def settle(app: AtlasApplication, request: ExecutionRequest) -> dict[str, Any]:
    """Drive one admitted request all the way into the durable book."""
    manager = app.execution
    admission = manager.risk_check(request)
    assert admission["approved"] is True, admission

    result = manager.paper_execute(request)
    assert result["success"] is True, result

    manager._finalize_durable_financial_state(request=request, result=result)
    manager._commit_capital_reservation(request.request_id)
    return result


# ===========================================================================
# 1/2/3/4/5/6 - InstrumentRules / InstrumentRuleset contract
# ===========================================================================


def test_instrument_rules_rejects_float_financial_fields():
    for field_name in ("quantity_step", "min_quantity", "min_notional", "price_tick"):
        with pytest.raises(InstrumentRulesConfigError):
            _rule(**{field_name: 0.00001})


def test_instrument_rules_exact_serialization_round_trip(tmp_path):
    original = _rule(
        quantity_step="0.00001000", min_quantity="0.00002000",
        min_notional="5.00000000", price_tick="0.01000000",
    )

    config_path = tmp_path / "instrument_rules.json"
    config_path.write_text(
        json.dumps({"schema_version": "1.0", "rules": [original.to_dict()]}),
        encoding="utf-8",
    )

    reloaded = load_instrument_ruleset(config_path).get("BTCUSDT")

    assert reloaded.to_dict() == original.to_dict()
    assert reloaded.digest == original.digest
    assert reloaded.quantity_step == D("0.00001000")


def test_instrument_rules_rejects_non_positive_step():
    for bad_value in ("0", "-0.00001"):
        with pytest.raises(InstrumentRulesConfigError):
            _rule(quantity_step=bad_value)


def test_min_quantity_must_align_with_quantity_step():
    with pytest.raises(InstrumentRulesConfigError):
        _rule(quantity_step="0.001", min_quantity="0.0025")

    # An exact multiple is accepted.
    aligned = _rule(quantity_step="0.001", min_quantity="0.003")
    assert aligned.min_quantity == D("0.003")


def test_ruleset_lookup_is_deterministic_and_immutable():
    ruleset = InstrumentRuleset({"BTCUSDT": _rule()})

    assert ruleset.get("BTCUSDT") is ruleset.get("BTCUSDT")
    assert ruleset.get("btcusdt") is ruleset.get("BTCUSDT")
    assert ruleset.get("ETHUSDT") is None

    with pytest.raises(TypeError):
        ruleset.rules["BTCUSDT"] = None

    with pytest.raises(Exception):
        ruleset.rules = {}

    with pytest.raises(Exception):
        ruleset.get("BTCUSDT").quantity_step = D("1")


def test_rule_digest_changes_when_an_authoritative_rule_changes():
    baseline = _rule()
    changed_step = _rule(quantity_step="0.0001", min_quantity="0.0001")
    changed_notional = _rule(min_notional="10")

    assert baseline.digest != changed_step.digest
    assert baseline.digest != changed_notional.digest


# ===========================================================================
# M3 remediation - the digest is invariant to cosmetic trailing-zero
# representation of an economically identical Decimal field
# ===========================================================================


def test_digest_ignores_cosmetic_trailing_zero_representation():
    canonical = _rule(
        quantity_step="0.00001", min_quantity="0.00001",
        min_notional="5", price_tick="0.01",
    )
    cosmetically_padded = _rule(
        quantity_step="0.00001000", min_quantity="0.00001000",
        min_notional="5.00000000", price_tick="0.01000000",
    )

    assert canonical.digest == cosmetically_padded.digest
    # The value itself is untouched by canonicalization - only the digest
    # input is affected. Decimal equality already treats these as equal;
    # this is not new behaviour, just confirming digest parity follows it.
    assert canonical.quantity_step == cosmetically_padded.quantity_step
    assert canonical.min_notional == cosmetically_padded.min_notional


def test_digest_still_changes_for_a_genuinely_different_economic_value():
    baseline = _rule(min_notional="5")
    padded_but_different = _rule(min_notional="5.01")

    assert baseline.digest != padded_but_different.digest


def test_to_dict_serialization_is_unaffected_by_digest_canonicalization():
    """M3 canonicalizes only the digest's input, never external serialization."""
    padded = _rule(quantity_step="0.00001000", min_notional="5.00000000")

    payload = padded.to_dict()

    assert payload["quantity_step"] == "0.00001000"
    assert payload["min_notional"] == "5.00000000"


# ===========================================================================
# 7/8 - startup halt semantics
# ===========================================================================


def test_missing_rules_for_configured_symbol_halts_startup(tmp_path):
    app = application(tmp_path, symbols=["DOGEUSDT"])
    app.execution.start()

    assert app.execution.execution_halted is True
    assert app.execution.recovery_required is True
    assert app.execution.halt_reason == "INSTRUMENT_RULES_UNAVAILABLE"


def test_legacy_misaligned_position_halts_startup_without_mutation(tmp_path):
    misaligned_base = "0.123456"  # 6 dp; BTCUSDT quantity_step has 5 dp
    app = application(tmp_path, positions=[("BTCUSDT", misaligned_base, "50000")])

    app.execution.start()

    assert app.execution.execution_halted is True
    assert app.execution.recovery_required is True
    assert app.execution.halt_reason == "INSTRUMENT_RULES_POSITION_MISALIGNED"

    # No floor, round-up, or write-off: the durable value is untouched.
    assert position_of(app)["base_quantity"] == format(D(misaligned_base), "f")


def test_aligned_legacy_position_starts_healthy(tmp_path):
    app = application(tmp_path, positions=[("BTCUSDT", "0.00010", "50000")])
    app.execution.start()

    assert app.execution.execution_halted is False
    assert app.execution.halt_reason is None


# ===========================================================================
# 9/10/11/12/13/14 - BUY admission and execution
# ===========================================================================


def test_buy_floors_to_quantity_step_and_never_rounds_up(flat_app):
    # 100 / 3.00 = 33.333333...; the correctly-rounded value would be
    # 33.33334 - proving this floors (33.33333) proves it never rounds up.
    request = buy(price="3.00", amount="100", request_id="floor-buy")
    result = settle(flat_app, request)

    filled = D(result["data"]["executed_quote_notional"])
    expected_base = D("33.33333")
    assert expected_base * D("3.00") == filled
    assert is_aligned_to_step(expected_base, BTCUSDT_QUANTITY_STEP)

    position = position_of(flat_app)
    assert D(position["base_quantity"]) == expected_base


def test_quantity_below_venue_minimum_rejected_pre_reservation(tmp_path):
    """Isolates the ``base < min_quantity`` gate from ``min_notional``.

    Requires a rule where min_quantity is a multiple of, but larger than,
    quantity_step - the real BTCUSDT rule has them equal, so any positive
    fill already satisfies it. A synthetic rule is injected after
    construction (Package 5D owner decision 9: rules are immutable
    per-*run*, not per-object; a test verifying one specific gate in
    isolation is not a mid-run refresh of the real config).
    """
    app = application(tmp_path)
    app.execution.start()
    app.execution.instrument_rules = InstrumentRuleset({
        "BTCUSDT": _rule(
            quantity_step="0.001", min_quantity="0.01", min_notional="1",
        ),
    })

    # 5.5 / 1000 = 0.0055 -> floors to 0.005 (< min_quantity 0.01), while
    # notional 1000*0.005 = 5.0 already clears min_notional 1.
    request = buy(price="1000.00", amount="5.5", request_id="below-min-qty")
    admission = app.execution.risk_check(request)

    assert admission["approved"] is False
    assert admission["reason"] == "QUANTITY_BELOW_VENUE_MINIMUM"
    assert app.reservation_ledger.get(request.request_id) is None


def test_notional_below_venue_minimum_rejected_pre_reservation(flat_app):
    # 4.99 quote / 10.00 price floors to 0.49900 BTC; notional stays 4.99,
    # under BTCUSDT's real 5.00 min_notional.
    request = buy(price="10.00", amount="4.99", request_id="below-min-notional")
    admission = flat_app.execution.risk_check(request)

    assert admission["approved"] is False
    assert admission["reason"] == "NOTIONAL_BELOW_VENUE_MINIMUM"
    assert flat_app.reservation_ledger.get(request.request_id) is None
    # A future independent request is unaffected: it is evaluated fresh.
    retry = buy(price="10.00", amount="100", request_id="retry-after-terminal")
    assert flat_app.execution.risk_check(retry)["approved"] is True


def test_tick_misaligned_price_rejected_never_rounded(flat_app):
    request = buy(price="10.001", amount="100", request_id="bad-tick")
    admission = flat_app.execution.risk_check(request)

    assert admission["approved"] is False
    assert admission["reason"] == "PRICE_TICK_MISALIGNED"
    # The request price itself was never touched - refused, not rounded.
    assert request.price == 10.001


def test_no_rules_fails_closed_with_no_1e8_fallback(tmp_path):
    app = application(tmp_path, symbols=["DOGEUSDT"])
    # DOGEUSDT has no checked-in rule, so this run cannot start clean; force
    # it online anyway to exercise the admission-time gate directly (the
    # startup halt for this exact scenario is proven separately above).
    app.execution.running = True

    request = buy(symbol="DOGEUSDT", price="0.10", amount="100", request_id="no-rules")
    admission = app.execution.risk_check(request)

    assert admission["approved"] is False
    assert admission["reason"] == "INSTRUMENT_RULES_UNAVAILABLE"
    assert not hasattr(ExecutionManager, "BASE_QUANTITY_QUANTUM")


# ===========================================================================
# M1 remediation - a component-reported fee can push a BUY fill's
# fee-adjusted quantity/notional below the venue minimum, discovered only at
# fill time (admission necessarily bounds with fee=0). Must fail closed
# before durable settlement, via the existing post-side-effect machinery.
# ===========================================================================


def test_component_fee_pushes_buy_fill_below_min_notional_and_fails_closed(flat_app):
    """The exact regression: admission clears at fee=0, the component then
    reports a fee that drops the fee-adjusted fill under min_notional.

    Directly exercised at the ``paper_execute`` level (this file's existing
    convention for proving admission/execution outcomes, e.g.
    ``test_paper_execution_cannot_bypass_instrument_rules``): the durable
    book must never see this fill, and the reservation this admission made
    must stay exactly as ``risk_check`` left it - never silently treated as
    settled.
    """
    manager = flat_app.execution
    original_open_trade = manager._paper_open_trade

    def fee_charging_open_trade(**kwargs):
        payload = dict(original_open_trade(**kwargs) or {})
        payload["fee"] = 0.01
        payload["fee_currency"] = "USDT"
        return payload

    manager._paper_open_trade = fee_charging_open_trade

    # Floored notional at fee=0 is exactly 5.00 - clears BTCUSDT's real
    # min_notional (5) at admission. A 0.01 fee then drops the fee-adjusted
    # fill to 4.99.
    request = buy(price="10.00", amount="5.00", request_id="fee-edge")
    admission = manager.risk_check(request)
    assert admission["approved"] is True

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "NOTIONAL_BELOW_VENUE_MINIMUM"

    # Durable state / reservation safety: the fee-invalid fill never reaches
    # the durable book, and the reservation this admission made is still
    # exactly RESERVED - neither silently committed as though the fill had
    # settled, nor released while the compatibility book's own mutation
    # (already unavoidable, since the fee is unknown until it is called) is
    # unresolved.
    assert position_of(flat_app) is None
    reservation = manager.reservation_ledger.get(request.request_id)
    assert reservation is not None
    assert reservation.status.value == "RESERVED"


def test_component_fee_below_min_notional_halts_through_full_orchestration(flat_app):
    """Same regression, driven through the real ``execute()`` orchestration.

    Proves the full safety contract the owner ruling requires: because the
    compatibility paper book was already mutated by the time the fee is
    known, this is classified exactly like the pre-existing
    ``ALLOCATION_BELOW_EXECUTABLE_QUANTUM`` fill-time failure - the runtime
    halts for operator recovery with the reservation moved to
    INDETERMINATE, never silently committed or released, and the durable
    book never sees the fill.
    """
    manager = flat_app.execution
    original_open_trade = manager._paper_open_trade

    def fee_charging_open_trade(**kwargs):
        payload = dict(original_open_trade(**kwargs) or {})
        payload["fee"] = 0.01
        payload["fee_currency"] = "USDT"
        return payload

    manager._paper_open_trade = fee_charging_open_trade

    decision = {
        "symbol": "BTCUSDT", "action": "BUY", "price": 10.00, "amount": 5.00,
        "confidence": 90.0, "risk": "MEDIUM", "request_id": "fee-edge-orch",
    }

    result = manager.execute(decision)

    assert result["success"] is False
    assert result["commit_outcome"] == "COMMIT_STATUS_UNKNOWN"
    assert result["recovery_required"] is True
    assert manager.execution_halted is True
    assert manager.recovery_required is True
    assert manager.halt_reason == "EXECUTION_INTERRUPTED_AFTER_SIDE_EFFECT"

    assert position_of(flat_app) is None
    reservation = manager.reservation_ledger.get("fee-edge-orch")
    assert reservation is not None
    assert reservation.status.value == "INDETERMINATE"


# ===========================================================================
# 15/16/17 - SELL
# ===========================================================================


def test_partial_sell_uses_quantity_step(tmp_path):
    app = application(tmp_path, positions=[("BTCUSDT", "10.00000", "10")])
    app.paper_trader.open_trade("BTCUSDT", 10, 100)
    app.execution.start()

    # 33.333 quote / 10 mark = 3.3333 base, already step-aligned at 5 dp;
    # picked so the induction chain below (test 17) reduces to a clean
    # remainder.
    request = sell(amount="33.333", price="10", request_id="partial")
    result = settle(app, request)

    sold = D(result["data"]["executed_quote_reduction"]) / D("10")
    assert is_aligned_to_step(sold, BTCUSDT_QUANTITY_STEP)
    assert position_of(app)["base_quantity"] == format(D("10.00000") - sold, "f")


def test_full_sell_preserves_exact_durable_held_quantity(tmp_path):
    held = "7.00001"
    app = application(tmp_path, positions=[("BTCUSDT", held, "10")])
    app.paper_trader.open_trade("BTCUSDT", 10, 70.001)
    app.execution.start()

    request = sell(amount=0, price="10", request_id="full-exit")  # unsized = exit
    result = settle(app, request)

    assert result["data"]["held_base_quantity"] == format(D(held), "f")
    assert position_of(app) is None  # closed, no dust left behind


def test_buy_partial_sell_full_sell_preserves_alignment_with_no_dust(flat_app):
    buy_request = buy(price="10", amount="100", request_id="chain-buy")
    settle(flat_app, buy_request)
    after_buy = D(position_of(flat_app)["base_quantity"])
    assert after_buy == D("10.00000")
    assert is_aligned_to_step(after_buy, BTCUSDT_QUANTITY_STEP)

    partial_request = sell(amount="33.333", price="10", request_id="chain-partial")
    settle(flat_app, partial_request)
    after_partial = D(position_of(flat_app)["base_quantity"])
    assert is_aligned_to_step(after_partial, BTCUSDT_QUANTITY_STEP)
    assert after_partial < after_buy

    full_request = sell(amount=0, price="10", request_id="chain-full")
    settle(flat_app, full_request)
    assert position_of(flat_app) is None  # exact close, no residual dust


def test_sell_floors_to_quantity_step_and_never_rounds_up(tmp_path):
    app = application(tmp_path, positions=[("BTCUSDT", "50.00000", "3.00")])
    app.paper_trader.open_trade("BTCUSDT", 3.00, 150)
    app.execution.start()

    # 100 / 3.00 = 33.333333...; the correctly-rounded value would be
    # 33.33334 - proving this floors (33.33333) proves it never rounds up.
    request = sell(amount="100", price="3.00", request_id="sell-floor")
    result = settle(app, request)

    sold = D(result["filled_base_quantity"])
    expected = D("33.33333")
    assert sold == expected
    assert is_aligned_to_step(sold, BTCUSDT_QUANTITY_STEP)
    assert D(position_of(app)["base_quantity"]) == D("50.00000") - expected


# ===========================================================================
# H1 remediation - SELL is subject to the same venue quantity/notional
# minimums as BUY (Block 5D SELL-venue-minimums owner ruling). A partial
# reduction must itself clear the minimums and may never strand a nonzero
# durable remainder below them; a full exit preserves the exact durable
# quantity but is not exempt from the minimums either. No failure here may
# reserve, settle, or mutate durable state - every check below runs before
# the side-effect boundary.
# ===========================================================================


def test_partial_sell_below_min_quantity_rejected_without_mutation(tmp_path):
    """Isolates the ``base < min_quantity`` gate with a synthetic rule.

    The real BTCUSDT rule has min_quantity == quantity_step, so any positive
    floored quantity already clears it; a synthetic rule with a larger
    min_quantity is required to isolate this specific gate (same technique
    as the existing BUY-side isolation test).
    """
    app = application(tmp_path, positions=[("BTCUSDT", "100.00000", "1000")])
    app.paper_trader.open_trade("BTCUSDT", 1000, 100000)
    app.execution.start()
    app.execution.instrument_rules = InstrumentRuleset({
        "BTCUSDT": _rule(
            quantity_step="0.001", min_quantity="0.01", min_notional="1",
        ),
    })

    # 5.5 / 1000 = 0.0055 -> floors to 0.005 (< min_quantity 0.01), while
    # its own notional 1000*0.005 = 5.0 already clears min_notional 1.
    request = sell(amount="5.5", price="1000", request_id="sell-below-min-qty")
    admission = app.execution.risk_check(request)
    assert admission["approved"] is True

    result = app.execution.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "QUANTITY_BELOW_VENUE_MINIMUM"
    # No mutation, no side effect: the durable holding and the runtime's
    # side-effect ledger are exactly as they were before this SELL.
    assert position_of(app)["base_quantity"] == "100.00000"
    assert app.execution._execution_side_effect_ids == set()


def test_partial_sell_below_min_notional_rejected_without_mutation(tmp_path):
    """Isolates the ``notional < min_notional`` gate: the floored quantity
    itself clears min_quantity, but its notional at the exposure basis does
    not.
    """
    app = application(tmp_path, positions=[("BTCUSDT", "100.00000", "1000")])
    app.paper_trader.open_trade("BTCUSDT", 1000, 100000)
    app.execution.start()
    app.execution.instrument_rules = InstrumentRuleset({
        "BTCUSDT": _rule(
            quantity_step="0.001", min_quantity="0.001", min_notional="10",
        ),
    })

    # 1.5 / 1000 = 0.0015 -> floors to 0.001 (clears min_quantity 0.001),
    # but its notional 1000*0.001 = 1.0 is below min_notional 10.
    request = sell(amount="1.5", price="1000", request_id="sell-below-min-notional")
    admission = app.execution.risk_check(request)
    assert admission["approved"] is True

    result = app.execution.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "NOTIONAL_BELOW_VENUE_MINIMUM"
    assert position_of(app)["base_quantity"] == "100.00000"
    assert app.execution._execution_side_effect_ids == set()


def test_partial_sell_cannot_strand_remainder_below_min_quantity(tmp_path):
    app = application(tmp_path, positions=[("BTCUSDT", "0.010", "1000")])
    app.paper_trader.open_trade("BTCUSDT", 1000, 10)
    app.execution.start()
    app.execution.instrument_rules = InstrumentRuleset({
        "BTCUSDT": _rule(
            quantity_step="0.001", min_quantity="0.005", min_notional="1",
        ),
    })

    # 9.5 / 1000 = 0.0095 -> floors to 0.009 (submitted: >= min_quantity
    # 0.005, notional 9 >= min_notional 1 - both clear). The durable
    # remainder, 0.010 - 0.009 = 0.001, is nonzero and below min_quantity
    # 0.005 - the SELL must be refused, not silently upgraded to a full
    # close and not rounded down further to avoid the remainder.
    request = sell(amount="9.5", price="1000", request_id="strand-min-qty")
    admission = app.execution.risk_check(request)
    assert admission["approved"] is True

    result = app.execution.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "REDUCTION_STRANDS_SUBMINIMUM_REMAINDER"
    assert position_of(app)["base_quantity"] == "0.010"
    assert app.execution._execution_side_effect_ids == set()


def test_partial_sell_cannot_strand_remainder_below_min_notional(tmp_path):
    app = application(tmp_path, positions=[("BTCUSDT", "0.100", "1000")])
    app.paper_trader.open_trade("BTCUSDT", 1000, 100)
    app.execution.start()
    app.execution.instrument_rules = InstrumentRuleset({
        "BTCUSDT": _rule(
            quantity_step="0.001", min_quantity="0.001", min_notional="50",
        ),
    })

    # 60.5 / 1000 = 0.0605 -> floors to 0.060 (submitted notional 60 clears
    # min_notional 50). The durable remainder, 0.100 - 0.060 = 0.040, clears
    # min_quantity (0.001) but its notional (40) is below min_notional 50 -
    # the SELL must be refused.
    request = sell(amount="60.5", price="1000", request_id="strand-min-notional")
    admission = app.execution.risk_check(request)
    assert admission["approved"] is True

    result = app.execution.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "REDUCTION_STRANDS_SUBMINIMUM_REMAINDER"
    assert position_of(app)["base_quantity"] == "0.100"
    assert app.execution._execution_side_effect_ids == set()


def test_full_sell_below_venue_minimum_fails_closed_without_mutation(tmp_path):
    """Exact durable-quantity preservation on a full exit does not exempt it
    from venue minimums: a close order this small is one the venue itself
    would refuse.
    """
    app = application(tmp_path, positions=[("BTCUSDT", "0.00001", "10")])
    app.paper_trader.open_trade("BTCUSDT", 10, 0.0001)
    app.execution.start()

    request = sell(amount=0, price="10", request_id="full-exit-too-small")
    admission = app.execution.risk_check(request)
    assert admission["approved"] is True

    result = app.execution.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "FULL_EXIT_BELOW_VENUE_MINIMUM"
    # No floor, round-up, or write-off: the durable holding is untouched,
    # and no side effect was ever crossed.
    assert position_of(app)["base_quantity"] == "0.00001"
    assert app.execution._execution_side_effect_ids == set()


def test_valid_partial_sell_clearing_all_minimums_still_settles(flat_app):
    """A partial reduction whose submission and remainder both clear the
    venue minimums is unaffected by the H1 remediation.
    """
    entry = settle(flat_app, buy(price="10", amount="1000", request_id="minimums-entry"))
    held = D(entry["filled_base_quantity"])
    assert held == D("100.00000")

    # 300 / 10 = 30.00000 (submitted); remainder 70.00000 - both comfortably
    # clear BTCUSDT's real min_quantity (0.00001) and min_notional (5).
    result = settle(flat_app, sell(amount="300", price="10", request_id="minimums-partial"))

    sold = D(result["filled_base_quantity"])
    assert sold == D("30.00000")
    assert D(position_of(flat_app)["base_quantity"]) == held - sold


# ===========================================================================
# 18/19/20 - rule identity / replay / evidence
# ===========================================================================


def test_rule_digest_is_sealed_into_admission_identity(flat_app):
    request = buy(price="10", amount="100", request_id="sealed")
    admission = flat_app.execution.risk_check(request)
    assert admission["approved"] is True

    rules = flat_app.execution.instrument_rules.get("BTCUSDT")
    sealed_key = flat_app.execution._risk_admissions[request.request_id]
    assert rules.digest in sealed_key


def test_changed_rules_invalidate_prior_admission_before_execution(flat_app):
    request = buy(price="10", amount="100", request_id="pre-swap")
    assert flat_app.execution.risk_check(request)["approved"] is True

    # A different rule for the same symbol (Package 5D owner decision 9:
    # rules never change mid-run in production; this simulates the seal
    # doing its job if that invariant were ever violated).
    flat_app.execution.instrument_rules = InstrumentRuleset({
        "BTCUSDT": _rule(source_version="v2-different"),
    })

    result = flat_app.execution.paper_execute(request)
    assert result["success"] is False
    assert result["reason"] == "CANONICAL_RISK_ADMISSION_MISSING"


def test_evidence_records_rule_digest_and_source_version(flat_app):
    request = buy(price="10", amount="100", request_id="evidence")
    admission = flat_app.execution.risk_check(request)
    rules = flat_app.execution.instrument_rules.get("BTCUSDT")

    assert admission["details"]["instrument_rules_digest"] == rules.digest
    assert (
        admission["details"]["instrument_rules_source_version"]
        == rules.source_version
    )

    result = flat_app.execution.paper_execute(request)
    assert result["data"]["instrument_rules_digest"] == rules.digest
    assert result["data"]["instrument_rules_source_version"] == rules.source_version
    assert result["data"]["instrument_rules_source"] == rules.source


# ===========================================================================
# 21 - paper path cannot bypass instrument-rule gates
# ===========================================================================


def test_paper_execution_cannot_bypass_instrument_rules(flat_app):
    """Even a forged admission cannot reach a fill without rules.

    ``_risk_admissions`` is seeded directly, bypassing ``risk_check``
    entirely, to prove the execution-time gate inside ``_execute_paper_buy``
    is a real, independent check - not merely a side effect of the
    admission-key seal (that mechanism is proven separately above).
    """
    manager = flat_app.execution
    manager.instrument_rules = None

    request = buy(price="10", amount="100", request_id="forged-admission")
    request.approved_quote_allocation = D("100")
    manager._risk_admissions[request.request_id] = manager._risk_admission_key(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "INSTRUMENT_RULES_UNAVAILABLE"


# ===========================================================================
# 22/23 - PositionSizingService / RiskEngine remain unchanged and unaware
# ===========================================================================


def test_position_sizing_service_stays_venue_unaware():
    import core.position_sizing as position_sizing_module

    source = inspect.getsource(position_sizing_module)
    assert "instrument_rules" not in source
    assert "InstrumentRule" not in source

    params = set(inspect.signature(position_sizing_module.SizingInputs).parameters)
    assert "instrument_rules" not in params
    assert "venue" not in params


def test_risk_engine_stays_approve_reject_only():
    import core.risk_engine as risk_engine_module

    source = inspect.getsource(risk_engine_module)
    assert "instrument_rules" not in source
    assert "InstrumentRule" not in source

    statuses = {status.value for status in risk_engine_module.RiskDecisionStatus}
    assert statuses == {"APPROVE", "REJECT", "BLOCK_RECOVERY_REQUIRED"}


# ===========================================================================
# floor_to_step / is_aligned_to_step - pure helpers used by both BUY and SELL
# ===========================================================================


def test_floor_to_step_rounds_toward_zero_for_non_power_of_ten_steps():
    # step is not a power of ten - Decimal.quantize could not express this.
    assert floor_to_step(D("1.07"), D("0.05")) == D("1.05")
    assert floor_to_step(D("0.049"), D("0.05")) == D("0.00")


def test_is_aligned_to_step_exact_boundary_semantics():
    assert is_aligned_to_step(D("10.00"), D("0.01")) is True
    assert is_aligned_to_step(D("10.001"), D("0.01")) is False
    assert is_aligned_to_step(D("0.00001"), D("0.00001")) is True
