"""Block 5E: fee-currency classification and fee-inclusive settlement.

Package 5B settled a component-reported fee correctly in quote currency but
left three defects on record for a later package (5B freeze evidence,
F4/F7/F8):

F4. A fee reported without a declared currency failed inside durable
    finalization - after the paper side-effect boundary - rather than
    before it.
F7. A COMMITTED reservation kept the full reserved amount even though
    settlement spent notional + fee, permanently over-encumbering the
    deterministic sub-quantum remainder a BUY never spent.
F8. ``entry_fees`` were carried whole through a partial SELL instead of
    being released pro rata with the cost basis they sit alongside.

5E closes all three, and adds the fee-currency gate 5B never needed because
nothing wired to it ever charged a fee: ``core.fee_accounting.FeeNormalizer``
classifies a reported fee against the instrument's own declared assets
(Block 5D). Only the venue's quote asset is settleable exactly today; a
base-asset fee, a third-asset fee (e.g. BNB), and an undeclared nonzero fee
are all refused before durable settlement, never assumed to be quote
currency and never converted - there is no FX or fee-rate policy anywhere
in this repository.

Explicitly NOT covered here (owner-scoped out of 5E):
- The COMMITTED-reservation-never-unwinds defect: at 5E freeze, a committed
  reservation still permanently encumbered ``available`` even though the
  capital it spent was already accounted for through durable cash. That was
  a separate, BLOCKING follow-up - CLOSED by Block 5F, which redefined live
  encumbrance as RESERVED + INDETERMINATE only, so COMMITTED never
  encumbers ``available`` regardless of position lifecycle (see
  ``tests/test_block5f_reservation_capital_reclamation.py`` and
  ``docs/evidence/block5f_freeze_evidence.md``). COMMITTED still never
  transitions to RELEASED and is still never linked to a position - 5F
  reached the reclamation goal without adding either.
- Any fee rate, fee schedule, or FX conversion.
- Base-asset fee *settlement* (withholding from base quantity) - fails
  closed instead of being implemented.
- Per-position net P&L as an ``entry_fees`` consumer.

Every fixture writes into pytest's tmp_path. Nothing here may touch the
operator's real runtime state.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D
from decimal import ROUND_HALF_EVEN, getcontext, localcontext
from typing import Any

import pytest

from core.application import (
    CAPITAL_RESERVATION_STATE_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    RISK_ACCOUNTING_STATE_FILE,
    AtlasApplication,
)
from core.capital_reservation import CapitalReservationLedger, JsonReservationStore
from core.execution_models import ExecutionRequest, ExecutionResult
from core.execution_portfolio_foundation import (
    SETTLEMENT_CONTEXT_PRECISION,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)
from core.fee_accounting import FeeNormalizer, FeeRejected, FeeRejectionReason
from core.instrument_rules import InstrumentRules
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState

POLICY_VERSION = "phase3-risk-v1"
TOTAL_CAPITAL = D("10000")

# Prices chosen, exactly as in 5B, so allocation / price does not terminate:
# the fee-settlement remainder these tests assert on is real quantization,
# not a coincidence of round numbers.
AWKWARD_PRICE = D("1.29")

BTCUSDT_RULE = InstrumentRules(
    venue="BINANCE", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
    quantity_step="0.00001", min_quantity="0.00001", min_notional="5",
    price_tick="0.01", source="test-fixture", source_version="v1",
    retrieved_at="2026-01-01T00:00:00Z",
)


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


def application(tmp_path, **seeding) -> AtlasApplication:
    return AtlasApplication(state_directory=seed_state(tmp_path / "state", **seeding))


@pytest.fixture
def flat_app(tmp_path) -> AtlasApplication:
    app = application(tmp_path)
    app.execution.start()
    return app


@pytest.fixture
def holding_app(tmp_path) -> AtlasApplication:
    """Durable book holds 10 BTCUSDT at a mark of 10 -> 100 quote exposure."""
    app = application(tmp_path, positions=[("BTCUSDT", "10", "10")])
    app.paper_trader.open_trade("BTCUSDT", 10, 100)
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
# A - FeeNormalizer: pure classification (no ExecutionManager required)
# ===========================================================================


def test_quote_asset_fee_is_accepted_exactly():
    normalized = FeeNormalizer.normalize(
        fee_amount=D("2.5"), fee_currency="usdt", instrument=BTCUSDT_RULE,
    )
    assert normalized.quote_amount == D("2.5")
    assert normalized.currency == "USDT"


def test_zero_fee_needs_no_currency():
    normalized = FeeNormalizer.normalize(
        fee_amount=D("0"), fee_currency=None, instrument=BTCUSDT_RULE,
    )
    assert normalized.quote_amount == D("0")


def test_base_asset_fee_fails_closed():
    with pytest.raises(FeeRejected) as excinfo:
        FeeNormalizer.normalize(
            fee_amount=D("0.001"), fee_currency="BTC", instrument=BTCUSDT_RULE,
        )
    assert excinfo.value.reason is FeeRejectionReason.BASE_ASSET_FEE_UNSUPPORTED


def test_third_asset_fee_fails_closed():
    with pytest.raises(FeeRejected) as excinfo:
        FeeNormalizer.normalize(
            fee_amount=D("0.05"), fee_currency="BNB", instrument=BTCUSDT_RULE,
        )
    assert excinfo.value.reason is FeeRejectionReason.THIRD_ASSET_FEE_UNSUPPORTED


def test_undeclared_nonzero_fee_fails_closed():
    with pytest.raises(FeeRejected) as excinfo:
        FeeNormalizer.normalize(
            fee_amount=D("1"), fee_currency=None, instrument=BTCUSDT_RULE,
        )
    assert excinfo.value.reason is FeeRejectionReason.UNDECLARED_FEE_CURRENCY


# ===========================================================================
# B - fee classification wired into the real BUY/SELL execution paths
# ===========================================================================


def test_buy_with_quote_fee_settles_correctly(flat_app):
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee": 2.5, "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))

    result = settle(flat_app, request)

    assert result["success"] is True
    assert result["fee_currency"] == "USDT"
    fee = D(result["fee_amount"])
    notional = D(result["filled_quote_notional"])
    assert fee == D("2.5")

    snapshot = flat_app.portfolio_foundation.snapshot()
    assert snapshot["cash"] == TOTAL_CAPITAL - notional - fee
    assert snapshot["fees"] == fee


def test_buy_with_base_asset_fee_fails_closed_before_settlement(flat_app):
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee": 0.001, "fee_currency": "BTC",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "BASE_ASSET_FEE_UNSUPPORTED"
    assert position_of(flat_app) is None
    assert flat_app.portfolio_foundation.snapshot()["cash"] == TOTAL_CAPITAL


def test_buy_with_third_asset_fee_fails_closed_before_settlement(flat_app):
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee": 0.05, "fee_currency": "BNB",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "THIRD_ASSET_FEE_UNSUPPORTED"
    assert position_of(flat_app) is None
    assert flat_app.portfolio_foundation.snapshot()["cash"] == TOTAL_CAPITAL


def test_buy_with_undeclared_fee_currency_fails_closed_before_settlement(flat_app):
    """Closes F4: the rejection now happens in ``paper_execute`` itself,
    before ``_finalize_durable_financial_state`` is ever reached - not
    inside it, as it did prior to 5E."""
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {"success": True, "fee": 2.5}
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "UNDECLARED_FEE_CURRENCY"
    assert position_of(flat_app) is None
    assert flat_app.portfolio_foundation.snapshot()["cash"] == TOTAL_CAPITAL


def test_sell_full_exit_with_undeclared_fee_currency_fails_closed(holding_app):
    """The same gate applies on the SELL path's full-exit call to
    ``_paper_close_trade`` (the only SELL case that ever hydrates a fee -
    a partial reduction skips the compatibility paper book, F3)."""
    manager = holding_app.execution
    manager._paper_close_trade = lambda request: {
        "status": "CLOSED", "profit": 0.0, "fee": 1.0,
    }
    request = sell(amount=100)  # full exit of the 10 @ 10 exposure
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "UNDECLARED_FEE_CURRENCY"
    position = position_of(holding_app)
    assert position is not None
    assert D(position["base_quantity"]) == D("10")


def test_exact_string_fee_amount_ingress_stays_exact(flat_app):
    """A component reporting ``fee_amount`` as a decimal string is carried
    through verbatim, never rounded through the float ``fee`` mirror."""
    manager = flat_app.execution
    exact = "1.234567890123456789"
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee_amount": exact, "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))

    result = settle(flat_app, request)

    assert result["fee_amount"] == format(D(exact), "f")
    assert D(result["fee_amount"]) == D(exact)
    # The lossy path this would have taken before 5E: Decimal(str(float(x))).
    assert D(exact) != D(str(float(exact)))


# ===========================================================================
# B2 - malformed exact `fee_amount` ingress fails closed, never falls back
#      to the legacy `fee`/`commission` mirror (final-review MEDIUM #1)
# ===========================================================================


def test_invalid_exact_fee_with_valid_legacy_fee_rejects_without_fallback(flat_app):
    """A component that names an exact `fee_amount` and gets it wrong is
    refused - it must not be rescued by a well-formed legacy `fee` sitting
    alongside it. Before this fix, `_extract_exact_decimal` discarded the
    invalid `-5` as if `fee_amount` had never been offered, and hydration
    silently settled the legacy `2.5` instead."""
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee_amount": "-5", "fee": 2.5, "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "INVALID_FEE_AMOUNT"
    assert position_of(flat_app) is None
    assert flat_app.portfolio_foundation.snapshot()["cash"] == TOTAL_CAPITAL


def test_invalid_exact_fee_with_no_legacy_fee_rejects(flat_app):
    """Unparseable `fee_amount` - not just a well-formed-but-invalid one -
    is refused rather than treated as absent."""
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee_amount": "not-a-number", "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "INVALID_FEE_AMOUNT"
    assert position_of(flat_app) is None


def test_negative_exact_fee_amount_rejects(flat_app):
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee_amount": "-1", "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "INVALID_FEE_AMOUNT"
    assert position_of(flat_app) is None


@pytest.mark.parametrize("poison", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_exact_fee_amount_rejects(flat_app, poison):
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee_amount": poison, "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "INVALID_FEE_AMOUNT"
    assert position_of(flat_app) is None


def test_valid_exact_fee_amount_still_settles_exactly(flat_app):
    """Positive control alongside the malformed-input tests above: a
    well-formed `fee_amount` reaches durable settlement unaffected by the
    fail-closed path those tests exercise."""
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee_amount": "2.5", "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))

    result = settle(flat_app, request)

    assert result["success"] is True
    assert D(result["fee_amount"]) == D("2.5")
    assert flat_app.portfolio_foundation.snapshot()["fees"] == D("2.5")


def test_fee_amount_absent_falls_back_to_legacy_commission_key(flat_app):
    """The one case the legacy mirror is still consulted for: no
    `fee_amount` key at all. Uses the `commission` alias specifically -
    `test_buy_with_quote_fee_settles_correctly` already covers the `fee`
    alias - so this also pins the second legacy key `_extract_numeric_value`
    still falls back to."""
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "commission": 2.5, "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))

    result = settle(flat_app, request)

    assert result["success"] is True
    assert D(result["fee_amount"]) == D("2.5")


# ===========================================================================
# C - reservation settlement: F7
# ===========================================================================


def test_committed_reservation_settles_at_notional_plus_fee_not_full_approval(tmp_path):
    """The owner's worked example: approved 100, notional 95, fee 1 -> the
    COMMITTED reservation records 96, not 100, and the unused 4 is no
    longer part of the committed amount."""
    store = JsonReservationStore(tmp_path / "reservations.json")
    store.initialize_empty()
    ledger = CapitalReservationLedger(store, D("1000"))

    ledger.reserve("req-1", "req-1", D("100"))
    committed = ledger.commit("req-1", D("95") + D("1"))

    assert committed.amount == D("96")
    assert committed.status.value == "COMMITTED"
    # COMMITTED is durable history, not live encumbrance (Block 5F): the
    # settled 96 does not reduce available capital at all.
    assert ledger.available == D("1000")
    assert ledger.active_reserved_capital() == D("0")


def test_committed_settlement_amount_survives_a_restart_reload(tmp_path):
    store = JsonReservationStore(tmp_path / "reservations.json")
    store.initialize_empty()
    ledger = CapitalReservationLedger(store, D("1000"))
    ledger.reserve("req-1", "req-1", D("100"))
    ledger.commit("req-1", D("96"))

    reloaded = CapitalReservationLedger(store, D("1000"))

    assert reloaded.get("req-1").amount == D("96")
    assert reloaded.get("req-1").status.value == "COMMITTED"
    # Block 5F: COMMITTED never encumbers, restart or not.
    assert reloaded.available == D("1000")


def test_commit_replay_does_not_reprice_an_already_committed_reservation(tmp_path):
    store = JsonReservationStore(tmp_path / "reservations.json")
    store.initialize_empty()
    ledger = CapitalReservationLedger(store, D("1000"))
    ledger.reserve("req-1", "req-1", D("100"))
    ledger.commit("req-1", D("96"))

    replayed = ledger.commit("req-1", D("50"))

    assert replayed.amount == D("96")


def test_commit_settled_amount_cannot_exceed_the_reservation(tmp_path):
    store = JsonReservationStore(tmp_path / "reservations.json")
    store.initialize_empty()
    ledger = CapitalReservationLedger(store, D("1000"))
    ledger.reserve("req-1", "req-1", D("100"))

    with pytest.raises(ValueError, match="exceeds reserved amount"):
        ledger.commit("req-1", D("101"))


def test_real_buy_execution_commits_the_exact_settled_amount(flat_app):
    """End-to-end proof through ``ExecutionManager.execute()`` itself - not
    the hand-rolled ``settle()`` helper - that production code now commits
    notional + fee rather than the full reservation."""
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee": 2.5, "fee_currency": "USDT",
    }
    decision = {
        "symbol": "BTCUSDT", "action": "BUY", "price": float(AWKWARD_PRICE),
        "amount": 1000, "confidence": 90.0, "risk": "MEDIUM", "request_id": "b1",
    }

    result = manager.execute(decision)

    assert result["status"] == "PAPER_EXECUTED"
    assert result["commit_outcome"] == "COMMITTED"

    settled = D(result["filled_quote_notional"]) + D(result["fee_amount"])
    reservation = manager.reservation_ledger.get("b1")
    assert reservation.status.value == "COMMITTED"
    assert reservation.amount == settled
    # The quantum-flooring remainder at this awkward price is real: the
    # committed amount is strictly less than the full 1000 requested.
    assert reservation.amount < D("1000")


# ===========================================================================
# D - partial-SELL entry_fees pro-ration: F8, plus the F5 settlement slice
# ===========================================================================


def _foundation(tmp_path, name="fs") -> ExecutionPortfolioFoundation:
    store = FinancialStateStore(tmp_path / f"{name}.json")
    store.initialize(D("1000"))
    return ExecutionPortfolioFoundation(store)


def _fill(action, *, base, price, fee, fee_ccy, execution_id,
          position_id="long:BTCUSDT") -> ExecutionResult:
    return ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id=execution_id,
        position_id=position_id, symbol="BTCUSDT", action=action,
        filled_price=price, filled_base_quantity=D(str(base)),
        filled_quote_notional=D(str(price)) * D(str(base)),
        fee_amount=D(str(fee)), fee_currency=fee_ccy,
        idempotency_key=execution_id, provenance_ref="test",
    )


def test_partial_sell_prorates_entry_fees_with_cost_basis(tmp_path):
    foundation = _foundation(tmp_path)
    foundation.set_reserved_capital(D("0"))
    foundation.apply_confirmed(
        _fill("BUY", base="10", price=10, fee="1", fee_ccy="USDT", execution_id="e1"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    foundation.apply_confirmed(
        _fill("SELL", base="5", price=12, fee="0.6", fee_ccy="USDT", execution_id="e2"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )

    position = foundation.snapshot()["positions"]["BTCUSDT"]
    assert D(position["cost_quote"]) == D("50")
    assert D(position["entry_fees"]) == D("0.5")


def test_full_close_exhausts_the_remaining_entry_fee_basis(tmp_path):
    foundation = _foundation(tmp_path)
    foundation.set_reserved_capital(D("0"))
    foundation.apply_confirmed(
        _fill("BUY", base="10", price=10, fee="1", fee_ccy="USDT", execution_id="e1"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    foundation.apply_confirmed(
        _fill("SELL", base="5", price=12, fee="0.6", fee_ccy="USDT", execution_id="e2"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    foundation.apply_confirmed(
        _fill("SELL", base="5", price=13, fee="0.5", fee_ccy="USDT", execution_id="e3"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=2,
    )

    snapshot = foundation.snapshot()
    assert "BTCUSDT" not in snapshot["positions"]
    closed = foundation._state["closed_positions"]["long:BTCUSDT"]
    # The full 0.5 remaining entry-fee basis is exhausted into the closed
    # record; none is left dangling on an open position (there is none).
    assert D(closed["entry_fees"]) == D("0.5")


def test_partial_sell_entry_fee_release_matches_independently_computed_ratio(tmp_path):
    """Discriminating replacement for the prior release+remainder check.

    That check derived ``released = original - remaining`` and then
    asserted ``released + remaining == original`` - an identity that holds
    for *any* value of ``remaining``, including the original F8 defect
    (the whole fee carried through unreleased) or a wrong ratio. It could
    never fail.

    This version computes the expected released fee independently, from
    the known ``sold/held`` ratio applied to the known original fee - never
    read back from the position under test - under the identical explicit
    context (`SETTLEMENT_CONTEXT_PRECISION`/``ROUND_HALF_EVEN``) ``_close``
    pins its own pro-ration under, so a non-terminating ratio (2/7) cannot
    make this test's independently computed figure disagree with the
    foundation's own merely because the two round a repeating decimal at
    different ambient precisions. Carrying the whole fee, or applying any
    ratio other than 2/7, fails both assertions below.
    """
    foundation = _foundation(tmp_path)
    foundation.set_reserved_capital(D("0"))
    original_entry_fees = D("1")
    foundation.apply_confirmed(
        _fill("BUY", base="7", price=10, fee=str(original_entry_fees), fee_ccy="USDT", execution_id="e1"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    foundation.apply_confirmed(
        _fill("SELL", base="2", price=10, fee="0", fee_ccy="USDT", execution_id="e2"),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )

    position = foundation.snapshot()["positions"]["BTCUSDT"]
    remaining_entry_fees = D(position["entry_fees"])

    # Every figure compared here - including `released_entry_fees`, which
    # is only observable as this same complement - is computed inside the
    # identical pinned context `_close` uses internally, so this comparison
    # is not itself exposed to this test's own ambient precision (which
    # would otherwise round the non-terminating 2/7 differently than the
    # foundation's pinned 50-digit computation did, producing a false
    # mismatch unrelated to what this test is checking).
    with localcontext() as context:
        context.prec = SETTLEMENT_CONTEXT_PRECISION
        context.rounding = ROUND_HALF_EVEN
        expected_released = original_entry_fees * D("2") / D("7")
        expected_remaining = original_entry_fees - expected_released
        released_entry_fees = original_entry_fees - remaining_entry_fees

    assert released_entry_fees == expected_released
    assert remaining_entry_fees == expected_remaining


def test_ambient_decimal_precision_cannot_change_buy_or_sell_settlement(tmp_path):
    """F5's settlement slice, widened at final review (MEDIUM #2) beyond
    just the pro-rata division: the BUY debit/fee accumulation and
    average-entry-price division in ``_open``, and the SELL gross P&L/cash/
    fee accumulation in ``_close``, are now all pinned to the same explicit
    context, so a caller's ambient precision cannot perturb any of them -
    not only the pro-rata split this test covered before.

    Two BUYs (the second adding to the first's position, so ``_open``'s
    add-to-existing-position branch runs, not just its fresh-open one) and
    a partial SELL, all at prices/fees chosen so every sum this covers -
    debit, fee accumulation, and both legs' average-entry-price - needs
    more than the perturbed 5-digit precision to represent exactly; a
    9-of-7 held/sold ratio keeps the pro-rata split non-terminating too.
    Round inputs would pass this assertion whether or not ``_open``/
    ``_close`` actually pin anything, proving nothing.
    """

    def run(root, *, prec: int | None) -> dict[str, Any]:
        foundation = _foundation(root)
        foundation.set_reserved_capital(D("0"))
        original_prec = getcontext().prec
        try:
            if prec is not None:
                getcontext().prec = prec
            foundation.apply_confirmed(
                _fill("BUY", base="3", price="1.29", fee="0.333333", fee_ccy="USDT", execution_id="e1"),
                risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
            )
            foundation.apply_confirmed(
                _fill("BUY", base="4", price=10, fee="0.222222", fee_ccy="USDT", execution_id="e2"),
                risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
            )
            foundation.apply_confirmed(
                _fill("SELL", base="2", price=10, fee="0.3", fee_ccy="USDT", execution_id="e3"),
                risk_authorized=True, reservation_confirmed=True, expected_position_version=2,
            )
        finally:
            getcontext().prec = original_prec
        return foundation.snapshot()

    baseline = run(tmp_path / "baseline", prec=None)
    perturbed = run(tmp_path / "perturbed", prec=5)

    assert perturbed["cash"] == baseline["cash"]
    assert perturbed["fees"] == baseline["fees"]
    assert perturbed["realized_gross_pnl"] == baseline["realized_gross_pnl"]

    baseline_position = baseline["positions"]["BTCUSDT"]
    perturbed_position = perturbed["positions"]["BTCUSDT"]
    assert perturbed_position["entry_fees"] == baseline_position["entry_fees"]
    assert perturbed_position["cost_quote"] == baseline_position["cost_quote"]
    assert perturbed_position["average_entry_price"] == baseline_position["average_entry_price"]


def test_ambient_decimal_precision_cannot_change_the_reservation_commit_amount(tmp_path):
    """The commit-time ``notional + fee`` sum and the approval-check sum in
    ``ExecutionManager`` (final-review MEDIUM #2) are pinned identically to
    the rest of the settlement slice: the exact reservation amount a real
    ``execute()`` BUY commits does not depend on the caller thread's
    ambient Decimal precision, and a low ambient precision does not turn a
    valid settlement into a spurious ``CAPITAL_RESERVATION_COMMIT_FAILED``
    halt.

    ``_resolve_base_fill`` (Block 5D sizing) is mocked out to hand back a
    fixed, deliberately many-digit notional rather than deriving it from a
    live division: that division pins only ``rounding``, not ``prec``
    (out of scope for 5E - "do not broaden into sizing... arithmetic"), so
    driving it with a many-digit fee/notional here would perturb the
    *sized fill itself* under a low ambient precision and conflate a real
    but unrelated Block 5D characteristic with what this test is actually
    proving: that the settlement-sum addition sites this package pinned
    do not lose precision under a low ambient context.
    """

    def run(root, *, prec: int | None) -> D:
        app = application(root)
        app.execution.start()
        manager = app.execution
        # `notional` must equal `price * base` exactly - the invariant
        # `ExecutionResult.validate_financial_evidence` re-derives and
        # checks on every `apply_confirmed` call, including under whichever
        # ambient precision is active at the time (that re-derivation is
        # itself pre-existing Phase-4 code, not part of 5E's settlement
        # slice). `base` is kept to 5 significant digits - short enough
        # that `price * base` cannot round differently at `prec=5` than at
        # normal ambient - so this test perturbs only what it means to:
        # the many-digit *fee* added onto the notional at the two 5E sites.
        mocked_base = D("61.235")
        mocked_notional = D("10") * mocked_base
        manager._resolve_base_fill = lambda **kwargs: (mocked_base, mocked_notional)
        manager._paper_open_trade = lambda **kwargs: {
            "success": True,
            "fee_amount": "3.210987654321098765432109",
            "fee_currency": "USDT",
        }
        decision = {
            "symbol": "BTCUSDT", "action": "BUY", "price": 10.0,
            "amount": 1000, "confidence": 90.0, "risk": "MEDIUM", "request_id": "b1",
        }
        original_prec = getcontext().prec
        try:
            if prec is not None:
                getcontext().prec = prec
            result = manager.execute(decision)
        finally:
            getcontext().prec = original_prec
        assert result["commit_outcome"] == "COMMITTED", result
        return manager.reservation_ledger.get("b1").amount

    baseline_amount = run(tmp_path / "baseline", prec=None)
    perturbed_amount = run(tmp_path / "perturbed", prec=5)

    assert perturbed_amount == baseline_amount
