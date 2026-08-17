"""Block-5B: one allocation authority, carried in exact Decimal, end to end.

Package 5A made the canonical ``RiskEngine`` reachable from the real runtime.
It left three defects behind, all reproduced before this package was written:

A.  A real ``MarketLoop`` BUY reached ``risk_check`` with ``amount == 0``,
    because nothing between ``DecisionAdapter`` and ``risk_check`` sized the
    decision. Every genuine runtime BUY died as ``INVALID_FINANCIAL_INPUT``.

B.  Risk approved a partial SELL of X and paper execution closed the whole
    holding: ``_execute_paper_sell`` read the position's full base quantity
    and ignored the approved reduction entirely.

C.  The risk-approved allocation was not what execution committed.
    ``allocate_capital`` preferred a ``CapitalManager`` position size over the
    approved amount, and ``_capital_risk_check`` let a ``CapitalManager`` veto
    a canonical ``RISK_APPROVED`` decision outright.

The frozen 5B rules these tests hold are:

1.  The risk-approved quote allocation is the *only* amount execution may
    commit, and it is carried as an exact ``Decimal`` from approval to
    settlement. ``ExecutionRequest.amount`` is a lossy mirror with no
    authority: corrupting it cannot change what executes.

2.  Nothing in this manager sizes a request. Defect A is fixed by refusing an
    unsized BUY as ``UNSIZED_REQUEST_REJECTED``, not by inheriting the policy
    ceiling as a size. The ceiling bounds an intent; it never manufactures one.

3.  ``execution_price * filled_base_quantity == filled_quote_notional``
    exactly, for prices that do not divide the allocation - which is nearly
    all real prices. Fills are sized in whole base quanta and their notional
    derived from the quantity, never the other way round.

4.  A full exit leaves the durable book with no position and no dust, so the
    symbol can be re-entered immediately.

Risk *policy* is not touched by 5B. The CRITICAL, max-positions,
duplicate-position and confidence verdicts asserted here are the same
verdicts 5A already proved reachable; they are re-asserted because the
allocation contract must not have weakened any of them.

Every fixture writes into pytest's tmp_path. Nothing here may touch the
operator's real runtime state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D
from typing import Any

import pytest

from core.application import (
    CAPITAL_RESERVATION_STATE_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    PAPER_TRADE_BOOK_FILE,
    RISK_ACCOUNTING_STATE_FILE,
    AtlasApplication,
)
from core.capital_reservation import JsonReservationStore
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.execution_portfolio_foundation import FinancialStateStore
from core.market_loop import MarketLoop
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState

POLICY_VERSION = "phase3-risk-v1"

# AtlasApplication derives RiskPolicy from CapitalManager.total_capital.
TOTAL_CAPITAL = D("10000")

# The policy ceiling for a MEDIUM-bucket BUY:
#   min(max_position_pct 0.40, bucket max_allocation_pct 0.25, ...) * capital
# It bounds a requested allocation. It is never a size.
MEDIUM_BUCKET_CEILING = TOTAL_CAPITAL * D("0.25")

# Prices chosen so that allocation / price does not terminate. These are the
# prices the old notional-first arithmetic could not represent exactly.
AWKWARD_PRICE = D("1.29")
BTC_LIKE_PRICE = D("43219.87654321")

QUANTUM = ExecutionManager.BASE_QUANTITY_QUANTUM


# --------------------------------------------------------------------------
# durable state seeding
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
    """Durable book holds 10 BTCUSDT at a mark of 10 -> 100 quote exposure.

    The compatibility paper book is opened to match, so an exit is judged by
    the durable authority rather than refused by a paper book that never saw
    the entry.
    """
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
    """Drive one admitted request all the way into the durable book.

    Admission, paper fill, durable finalization and capital resolution, in the
    order the runtime performs them. Every number these tests assert on comes
    out of this path rather than out of the test.
    """
    manager = app.execution
    admission = manager.risk_check(request)
    assert admission["approved"] is True, admission

    result = manager.paper_execute(request)
    assert result["success"] is True, result

    manager._finalize_durable_financial_state(request=request, result=result)
    manager._commit_capital_reservation(request.request_id)
    return result


def drive(app: AtlasApplication, decision: dict[str, Any]) -> dict[str, Any]:
    """Drive one decision through the real ``ExecutionManager.execute()``.

    ``settle()`` above composes the stages by hand, which is what makes the
    per-stage invariants readable. It cannot prove anything about the
    orchestration itself: the idempotency claim, the transaction-journal
    prepare barrier, the side-effect boundary, and the failure classification
    that turns a post-boundary failure into a halted runtime all live in
    ``execute()`` and are simply absent from the hand-rolled path.

    Anything asserted about *where* a refusal happens has to come through
    here, because "refused cleanly" and "refused after the paper book was
    mutated" are indistinguishable from ``paper_execute`` alone.
    """
    return app.execution.execute(decision)


def buy_decision(**overrides: Any) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT", "action": "BUY", "price": 10, "amount": 100,
        "confidence": 90.0, "risk": "MEDIUM", "request_id": "b1", **overrides,
    }


def sell_decision(**overrides: Any) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT", "action": "SELL", "price": 10, "amount": 40,
        "confidence": 90.0, "risk": "MEDIUM", "request_id": "s1", **overrides,
    }


def assert_no_execution_residue(app: AtlasApplication) -> None:
    """A refusal must leave the runtime exactly as it found it."""
    manager = app.execution
    assert manager.execution_halted is False
    assert manager.recovery_required is False
    assert manager.halt_reason is None
    assert manager._risk_admissions == {}
    assert manager._execution_side_effect_ids == set()
    assert manager.reservation_ledger._items == {}
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert app.paper_trader.positions == {}
    assert app.portfolio_foundation.snapshot()["positions"] == {}
    assert app.portfolio_foundation.snapshot()["cash"] == TOTAL_CAPITAL


def assert_exact_fill(result: dict[str, Any], *, approved: D) -> tuple[D, D]:
    """The BUY identity and bound, asserted together on real fill evidence."""
    price = D(str(result["filled_price"]))
    base = D(result["filled_base_quantity"])
    quote = D(result["filled_quote_notional"])
    fee = D(result["fee_amount"])

    # The identity, under the same arithmetic the evidence validator uses.
    assert price * base == quote

    # Never more than risk approved, fee included, and never zero.
    assert D("0") < quote
    assert quote + fee <= approved

    # The remainder is bounded by one quantum of notional: it is what the
    # base quantum could not buy, not slippage and not an unexplained gap.
    assert approved - quote - fee < price * QUANTUM
    return base, quote


# ==========================================================================
# 1 — allocation authority: this manager resolves intent, it never sizes
# ==========================================================================


def test_explicit_caller_amount_is_carried_exactly(flat_app):
    request = buy(amount=250)

    assert flat_app.execution.risk_check(request)["approved"] is True
    assert request.approved_quote_allocation == D("250")
    assert D(flat_app.execution.last_risk_decision["approved_allocation"]) == D("250")


def test_unsized_buy_is_rejected_rather_than_sized(flat_app):
    """Frozen 5B rule: new risk with no stated size does not execute.

    The policy ceiling is a bound. Inheriting it would make every unsized
    decision the largest trade policy allows, which is a sizing policy nobody
    authorized. This must be its own reason code - not malformed input, and
    certainly not a fill.
    """
    request = buy()

    result = flat_app.execution.risk_check(request)

    assert result["approved"] is False
    assert result["reason"] == "UNSIZED_REQUEST_REJECTED"
    assert request.approved_quote_allocation is None
    assert flat_app.execution.reservation_ledger.get("b1") is None
    assert flat_app.execution._risk_admissions == {}
    assert flat_app.execution.execution_halted is False


def test_unsized_buy_never_reaches_the_risk_engine(flat_app):
    """Nothing is evaluated, so nothing can be approved by accident."""
    calls: list[Any] = []
    evaluate = flat_app.execution.risk_engine.evaluate
    flat_app.execution.risk_engine.evaluate = (
        lambda request, state: calls.append(request) or evaluate(request, state)
    )

    assert flat_app.execution.risk_check(buy())["reason"] == "UNSIZED_REQUEST_REJECTED"
    assert calls == []


def test_unsized_buy_rejection_is_distinct_from_capital_exhaustion(tmp_path):
    """Two different failures must not collapse into one reason code."""
    app = application(tmp_path, cash="0")
    app.execution.start()

    unsized = app.execution.risk_check(buy(request_id="unsized"))
    exhausted = app.execution.risk_check(buy(amount=500, request_id="exhausted"))

    assert unsized["reason"] == "UNSIZED_REQUEST_REJECTED"
    assert exhausted["reason"] == "INSUFFICIENT_DURABLE_CAPITAL"
    assert unsized["reason"] != exhausted["reason"]


def test_zero_cash_reports_capital_exhaustion_not_malformed_input(tmp_path):
    """A capital bound of zero is an exhausted book, not a broken request."""
    app = application(tmp_path, cash="0")
    app.execution.start()

    result = app.execution.risk_check(buy(amount=500))

    assert result["approved"] is False
    assert result["reason"] == "INSUFFICIENT_DURABLE_CAPITAL"
    assert result["details"]["available_quote_capital"] == "0"
    assert app.execution.reservation_ledger.get("b1") is None
    assert app.execution._risk_admissions == {}
    assert app.execution.execution_halted is False


def test_explicitly_sized_buy_over_the_ceiling_is_refused_by_the_engine(flat_app):
    """The ceiling bounds the request by refusing it, never by trimming it."""
    request = buy(amount=int(MEDIUM_BUCKET_CEILING) + 1)

    result = flat_app.execution.risk_check(request)

    assert result["approved"] is False
    assert result["reason"] == "REQUEST_EXCEEDS_RISK_LIMIT"
    assert request.approved_quote_allocation is None
    assert flat_app.execution.reservation_ledger.get("b1") is None


def test_no_sizing_surface_exists_on_the_manager():
    """Every path that could manufacture a size is gone, and stays gone."""
    for name in ("DEFAULT_ALLOCATION", "allocate_capital",
                 "_calculate_manager_position_size", "_available_capital",
                 "_capital_risk_check", "_propose_quote_allocation"):
        assert not hasattr(ExecutionManager, name), name


def test_risk_engine_exposes_no_public_sizing_query(flat_app):
    """5B introduced a policy-ceiling query for sizing; sizing is now refused."""
    assert not hasattr(flat_app.execution.risk_engine, "maximum_new_risk_allocation")


def test_unsized_sell_with_nothing_held_is_malformed_not_unsized(tmp_path):
    """Selling what is not held is not a reduction, and is not sized either."""
    app = application(tmp_path)
    app.execution.start()

    result = app.execution.risk_check(sell())

    assert result["approved"] is False
    assert result["reason"] == "INVALID_FINANCIAL_INPUT"


# ==========================================================================
# 2 — the canonical Decimal is the only allocation authority
# ==========================================================================


def test_approved_reserved_executed_and_durable_amounts_all_agree(flat_app):
    request = buy(amount=1000, price=float(AWKWARD_PRICE))

    result = settle(flat_app, request)

    approved = request.approved_quote_allocation
    base, quote = assert_exact_fill(result, approved=approved)
    position = position_of(flat_app)

    assert approved == D("1000")
    assert D(result["requested_quote_allocation"]) == approved
    assert D(position["base_quantity"]) == base
    assert D(position["cost_quote"]) == quote
    assert flat_app.portfolio_foundation.snapshot()["cash"] == TOTAL_CAPITAL - quote


def test_approved_allocation_is_decimal_and_never_a_float(flat_app):
    request = buy(amount=1000, price=float(AWKWARD_PRICE))

    flat_app.execution.risk_check(request)

    assert isinstance(request.approved_quote_allocation, D)
    assert not isinstance(request.approved_quote_allocation, float)


def test_lossy_amount_mirror_cannot_change_what_executes(tmp_path):
    """Requirement: truncating `amount` after approval must change nothing.

    `amount` is a float mirror kept for historical callers. It is not an
    admitted term and no authoritative consumer reads it, so mangling it can
    neither resize the fill nor invalidate the admission. Two identical
    runtimes are driven side by side; only one has its mirror corrupted.
    """
    reference_app, corrupted_app = application(tmp_path / "a"), application(tmp_path / "b")
    reference_app.execution.start()
    corrupted_app.execution.start()

    reference_result = settle(
        reference_app, buy(amount=1000, price=float(AWKWARD_PRICE))
    )

    corrupted = buy(amount=1000, price=float(AWKWARD_PRICE))
    assert corrupted_app.execution.risk_check(corrupted)["approved"] is True

    approved = corrupted.approved_quote_allocation
    corrupted.amount = 0.0
    corrupted.amount = 7.5

    result = corrupted_app.execution.paper_execute(corrupted)

    assert result["success"] is True
    assert corrupted.approved_quote_allocation == approved
    assert D(result["filled_quote_notional"]) == D(
        reference_result["filled_quote_notional"]
    )
    assert D(result["filled_base_quantity"]) == D(
        reference_result["filled_base_quantity"]
    )


def test_approved_allocation_survives_request_serialization(flat_app):
    """A round-tripped request carries the same approval, not a float of it."""
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    flat_app.execution.risk_check(request)
    request.approved_quote_allocation = D("999.9999999876")

    payload = request.to_dict()
    restored = ExecutionRequest.from_dict(payload)

    assert payload["approved_quote_allocation"] == "999.9999999876"
    assert restored.approved_quote_allocation == D("999.9999999876")
    assert flat_app.execution._risk_admission_key(restored) == (
        flat_app.execution._risk_admission_key(request)
    )


def test_a_float_approval_is_rejected_at_construction():
    """The field cannot be handed a value that already lost precision."""
    with pytest.raises(ValueError, match="must not be float"):
        ExecutionRequest("BTCUSDT", "BUY", 1.29, 1000,
                         approved_quote_allocation=1000.0)


def test_changing_the_approved_decimal_loses_the_admission(flat_app):
    """The admission token seals the Decimal, so tampering with it fails closed."""
    manager = flat_app.execution
    request = buy(amount=1000)
    manager.risk_check(request)

    request.approved_quote_allocation = request.approved_quote_allocation * 2
    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["reason"] == "CANONICAL_RISK_ADMISSION_MISSING"
    assert position_of(flat_app) is None


def test_a_refusal_never_leaves_a_stale_approval_behind(flat_app):
    """A request re-evaluated into a refusal must not keep its old approval."""
    manager = flat_app.execution
    request = buy(amount=1000)
    assert manager.risk_check(request)["approved"] is True
    assert request.approved_quote_allocation == D("1000")

    request.confidence = 10.0
    result = manager.risk_check(request)

    assert result["approved"] is False
    assert result["reason"] == "CONFIDENCE_BELOW_POLICY"
    assert request.approved_quote_allocation is None


def awkward_exposure_app(tmp_path) -> AtlasApplication:
    """A holding whose quote exposure needs more digits than a float carries.

    ``0.05784375 * 43219.87654321`` is 2499.9997337963034375 - twenty
    significant digits. A float mirror of it rounds *up*, which is what makes
    it the reproduction for F2 rather than a merely awkward number.
    """
    app = application(
        tmp_path, positions=[("BTCUSDT", "0.05784375", "43219.87654321")]
    )
    app.paper_trader.open_trade("BTCUSDT", float(BTC_LIKE_PRICE), 2500)
    app.execution.start()
    return app


AWKWARD_EXPOSURE = D("0.05784375") * BTC_LIKE_PRICE


def test_the_float_mirror_of_an_exact_exposure_really_does_round_up():
    """The premise of F2, stated so the regression tests cannot go vacuous."""
    assert AWKWARD_EXPOSURE == D("2499.9997337963034375")
    assert D(str(float(AWKWARD_EXPOSURE))) != AWKWARD_EXPOSURE
    assert D(str(float(AWKWARD_EXPOSURE))) > AWKWARD_EXPOSURE


def test_risk_check_is_idempotent_for_an_unsized_exit(tmp_path):
    """F2: re-evaluating the same request object must not change the verdict.

    Reproduced before this fix: ``risk_check`` wrote ``float(requested)`` back
    onto ``request.amount``, so a second evaluation of the same object read
    its own rounded mirror as an explicit allocation instead of re-resolving
    the durable exposure. The mirror rounded up, so the second call refused
    the exit as INVALID_RISK_REDUCTION - the position became un-exitable
    through that request, which is the trapped-exposure direction.
    """
    app = awkward_exposure_app(tmp_path)
    manager = app.execution
    request = sell(price=float(BTC_LIKE_PRICE))

    first = manager.risk_check(request)
    first_approved = request.approved_quote_allocation

    second = manager.risk_check(request)

    assert first == second == {"approved": True, "reason": "RISK_APPROVED"}
    assert first_approved == AWKWARD_EXPOSURE
    assert request.approved_quote_allocation == AWKWARD_EXPOSURE


def test_risk_check_never_synthesizes_the_amount_mirror(tmp_path):
    """The mirror is caller input, and stays caller input.

    A resolved SELL exposure must never be written back onto it: that is what
    turns a compatibility field into an authority on the next evaluation.
    """
    app = awkward_exposure_app(tmp_path)
    unsized = sell(price=float(BTC_LIKE_PRICE))

    app.execution.risk_check(unsized)

    assert unsized.amount == 0
    assert unsized.approved_quote_allocation == AWKWARD_EXPOSURE


def test_an_explicit_amount_is_left_byte_for_byte_alone(flat_app):
    """Idempotency must not be bought by rewriting a caller's own number."""
    request = buy(amount=1000)

    flat_app.execution.risk_check(request)
    flat_app.execution.risk_check(request)

    assert request.amount == 1000
    assert request.approved_quote_allocation == D("1000")


def test_a_float_rounded_mirror_cannot_trap_an_exit(tmp_path):
    """The full consequence: a re-evaluated exit still closes the position."""
    app = awkward_exposure_app(tmp_path)
    manager = app.execution
    request = sell(price=float(BTC_LIKE_PRICE))

    manager.risk_check(request)
    assert manager.risk_check(request)["approved"] is True

    result = manager.paper_execute(request)
    manager._finalize_durable_financial_state(request=request, result=result)

    assert result["success"] is True
    assert result["data"]["partial_reduction"] is False
    assert D(result["filled_base_quantity"]) == D("0.05784375")
    assert position_of(app) is None


def test_repeated_risk_check_does_not_double_reserve(flat_app):
    """Idempotent admission must not encumber capital twice."""
    manager = flat_app.execution
    request = buy(amount=1000)

    manager.risk_check(request)
    manager.risk_check(request)

    assert manager.reservation_ledger.get("b1").amount == D("1000")
    assert manager.reservation_ledger.active_reserved_capital() == D("1000")


def test_capital_manager_cannot_resize_an_approved_buy(flat_app):
    class ResizingCapitalManager:
        def calculate_position_size(self, *args, **kwargs):
            return 750.0

        def allocate(self, *args, **kwargs):
            return {"success": True, "amount": 750.0}

        def get_available_capital(self):
            return 1.0

    manager = flat_app.execution
    manager.capital_manager = ResizingCapitalManager()
    request = buy(amount=1000)

    manager.risk_check(request)
    result = manager.paper_execute(request)

    assert request.approved_quote_allocation == D("1000")
    assert D(result["filled_quote_notional"]) == D("1000")


def test_capital_manager_cannot_veto_an_approved_canonical_decision(flat_app):
    class VetoingCapitalManager:
        def validate_execution(self, *args, **kwargs):
            return {"approved": False, "reason": "CAPITAL_MANAGER_SAYS_NO"}

        def risk_check(self, *args, **kwargs):
            return {"approved": False, "reason": "CAPITAL_MANAGER_SAYS_NO"}

        def approve(self, *args, **kwargs):
            return {"approved": False}

    manager = flat_app.execution
    manager.capital_manager = VetoingCapitalManager()

    result = manager.risk_check(buy(amount=1000))

    assert result["approved"] is True
    assert result["reason"] == "RISK_APPROVED"
    assert manager.reservation_ledger.get("b1") is not None


def test_component_reported_amount_cannot_overwrite_quote_capital(flat_app):
    """A base-unit value under an ambiguous key is not quote capital."""
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "filled_amount": 0.25, "allocation": 0.25,
    }
    request = buy(amount=1000)
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert D(result["filled_quote_notional"]) == D("1000")
    assert D(str(result["filled_amount"])) == D("1000")


def test_unreadable_durable_capital_state_fails_closed(flat_app):
    """The funding check cannot be skipped by a store that stops answering."""
    def unavailable(*args, **kwargs):
        raise RuntimeError("reservation state recovery required")

    flat_app.execution.reservation_ledger.active_reserved_capital = unavailable

    result = flat_app.execution.risk_check(buy(amount=100))

    assert result["approved"] is False
    assert result["reason"] == "DURABLE_CAPITAL_STATE_UNAVAILABLE"
    assert result["status"] == "BLOCK_RECOVERY_REQUIRED"
    assert flat_app.execution.reservation_ledger.get("b1") is None
    assert flat_app.execution._risk_admissions == {}


def test_insufficient_capital_is_an_admission_refusal_not_a_settlement_halt(tmp_path):
    """Policy permits the request; the durable book cannot fund it."""
    app = application(tmp_path, cash="50")
    app.execution.start()

    result = app.execution.risk_check(buy(amount=500))

    assert result["approved"] is False
    assert result["reason"] == "INSUFFICIENT_DURABLE_CAPITAL"
    assert app.execution.reservation_ledger.get("b1") is None
    assert app.execution._risk_admissions == {}
    assert app.execution.execution_halted is False


def test_reduction_is_not_subject_to_the_durable_capital_check(holding_app):
    """An exit consumes no capital, so free cash cannot block it."""
    payload = holding_app.portfolio_foundation.store.load()
    payload["cash"] = "0"
    holding_app.portfolio_foundation.store.save(payload)
    holding_app.portfolio_foundation._state = payload

    result = holding_app.execution.risk_check(sell())

    assert result["approved"] is True
    assert result["reason"] == "RISK_APPROVED"


# ==========================================================================
# 2b — M1: a request's own reservation must not defund its re-evaluation
# ==========================================================================
#
# The durable funding check reads free capital as `cash - active reservations`.
# A re-evaluated BUY already holds its own RESERVED entry from the first
# evaluation, so counting that entry charged the request for its own admission:
# near the durable bound the second verdict flipped to
# INSUFFICIENT_DURABLE_CAPITAL purely because the request had been approved
# once already, and the same well-formed request became un-admissible through
# its own object.
#
# The fix excludes exactly one reservation - the current request's own - and
# only from its own admission check. Every other reservation still encumbers
# capital, the reservation is neither released nor recreated to obtain the
# idempotency, and no request may hold two.

NEAR_BOUND_CASH = "1000"
NEAR_BOUND_ALLOCATION = D("600")


def near_bound_app(tmp_path) -> AtlasApplication:
    """A durable book of 1000 cash against an approved allocation of 600.

    Both numbers sit under the MEDIUM policy ceiling, so ``RiskEngine``
    approves on every evaluation and the durable funding check is the only
    gate under test. 600 of 1000 is what makes it near-bound: it is fundable
    once and not twice.
    """
    app = application(tmp_path, cash=NEAR_BOUND_CASH)
    app.execution.start()
    return app


def test_the_near_bound_allocation_is_within_policy():
    """The premise of M1, stated so the regression tests cannot go vacuous."""
    assert NEAR_BOUND_ALLOCATION < MEDIUM_BUCKET_CEILING
    assert NEAR_BOUND_ALLOCATION <= D(NEAR_BOUND_CASH)
    assert NEAR_BOUND_ALLOCATION * 2 > D(NEAR_BOUND_CASH)


def test_near_bound_buy_re_evaluation_keeps_its_approval(tmp_path):
    """M1: the same request object must not be defunded by its own admission."""
    manager = near_bound_app(tmp_path).execution
    request = buy(amount=int(NEAR_BOUND_ALLOCATION))

    first = manager.risk_check(request)
    second = manager.risk_check(request)

    assert first == second == {"approved": True, "reason": "RISK_APPROVED"}


def test_re_evaluated_buy_reserves_its_allocation_exactly_once(tmp_path):
    """Idempotency must come from exclusion, not from a second reservation."""
    manager = near_bound_app(tmp_path).execution
    request = buy(amount=int(NEAR_BOUND_ALLOCATION))

    manager.risk_check(request)
    manager.risk_check(request)

    reservation = manager.reservation_ledger.get("b1")
    assert reservation.amount == NEAR_BOUND_ALLOCATION
    assert manager.reservation_ledger.active_reserved_capital() == NEAR_BOUND_ALLOCATION
    assert list(manager.reservation_ledger._items) == ["b1"]

    # Not released and recreated to make room: the original entry is still the
    # one standing, untouched, at its first version.
    assert reservation.status.value == "RESERVED"
    assert reservation.version == 1


def test_re_evaluation_leaves_the_canonical_allocation_unchanged(tmp_path):
    """The exclusion changes what is funded, never what was approved."""
    manager = near_bound_app(tmp_path).execution
    request = buy(amount=int(NEAR_BOUND_ALLOCATION))

    manager.risk_check(request)
    first_approved = request.approved_quote_allocation
    manager.risk_check(request)

    assert first_approved == NEAR_BOUND_ALLOCATION
    assert request.approved_quote_allocation == NEAR_BOUND_ALLOCATION
    assert isinstance(request.approved_quote_allocation, D)
    assert request.amount == int(NEAR_BOUND_ALLOCATION)
    assert manager._risk_admissions.get("b1") is not None


def test_another_request_still_sees_the_first_reservation(tmp_path):
    """Only the request's own reservation is excluded, and only for itself."""
    manager = near_bound_app(tmp_path).execution
    request = buy(amount=int(NEAR_BOUND_ALLOCATION))
    manager.risk_check(request)
    manager.risk_check(request)

    refused = manager.risk_check(
        buy(symbol="ETHUSDT", amount=int(NEAR_BOUND_ALLOCATION), request_id="b2")
    )

    assert refused["approved"] is False
    assert refused["reason"] == "INSUFFICIENT_DURABLE_CAPITAL"
    assert D(refused["details"]["available_quote_capital"]) == D("400")
    assert manager.reservation_ledger.get("b2") is None
    assert manager._risk_admissions.get("b2") is None

    fits = manager.risk_check(buy(symbol="ETHUSDT", amount=400, request_id="b3"))

    assert fits["approved"] is True
    assert manager.reservation_ledger.active_reserved_capital() == D("1000")


def test_a_request_beyond_remaining_durable_capital_is_still_refused(tmp_path):
    """Exclusion cannot manufacture capital the book does not hold."""
    manager = near_bound_app(tmp_path).execution
    oversized = buy(amount=1200)

    first = manager.risk_check(oversized)
    second = manager.risk_check(oversized)

    assert first == second
    assert first["approved"] is False
    assert first["reason"] == "INSUFFICIENT_DURABLE_CAPITAL"
    assert D(first["details"]["available_quote_capital"]) == D("1000")
    assert manager.reservation_ledger.get("b1") is None
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert oversized.approved_quote_allocation is None
    assert manager.execution_halted is False


def test_f1_sub_quantum_refusal_stays_pre_reservation_under_re_evaluation(tmp_path):
    """F1 is preserved: the quantum bound still refuses before any reservation."""
    app = near_bound_app(tmp_path)
    manager = app.execution
    request = buy(amount=0.0001, price=float(BTC_LIKE_PRICE))

    first = manager.risk_check(request)
    second = manager.risk_check(request)

    assert first["approved"] is second["approved"] is False
    assert first["reason"] == second["reason"] == "ALLOCATION_BELOW_EXECUTABLE_QUANTUM"
    assert manager.reservation_ledger.get("b1") is None
    assert manager.reservation_ledger._items == {}
    assert manager._risk_admissions == {}
    assert request.approved_quote_allocation is None


def test_f2_repeated_sell_risk_check_remains_idempotent(tmp_path):
    """F2 is preserved: a re-evaluated exit keeps its verdict and its amount."""
    manager = awkward_exposure_app(tmp_path).execution
    request = sell(price=float(BTC_LIKE_PRICE))

    verdicts = [manager.risk_check(request) for _ in range(3)]

    assert verdicts == [{"approved": True, "reason": "RISK_APPROVED"}] * 3
    assert request.approved_quote_allocation == AWKWARD_EXPOSURE
    assert request.amount == 0
    # A reduction consumes no capital, so no evaluation of it may reserve any.
    assert manager.reservation_ledger._items == {}


def test_no_execution_path_exceeds_the_approval_after_re_evaluation(tmp_path):
    """The re-evaluated request settles within its one approval, once."""
    app = near_bound_app(tmp_path)
    manager = app.execution
    request = buy(amount=int(NEAR_BOUND_ALLOCATION), price=float(AWKWARD_PRICE))

    manager.risk_check(request)
    result = settle(app, request)

    executed = D(result["filled_quote_notional"])
    assert_exact_fill(result, approved=NEAR_BOUND_ALLOCATION)

    snapshot = app.portfolio_foundation.snapshot()
    assert snapshot["cash"] == D(NEAR_BOUND_CASH) - executed - D(result["fee_amount"])
    assert snapshot["reserved_capital"] == D("0")
    assert manager.reservation_ledger.get("b1").status.value == "COMMITTED"
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert manager._risk_admissions == {}


# ==========================================================================
# 3 — BUY precision: the quantity/notional identity holds for real prices
# ==========================================================================


@pytest.mark.parametrize("price,allocation", [
    (AWKWARD_PRICE, D("1000")),      # the 1.29 reproduction
    (BTC_LIKE_PRICE, D("2500")),     # a non-round-trip venue price
    (D("1.00"), D("1.01")),          # the prior 1.01 / 1.00 reproduction
    (AWKWARD_PRICE, D("1.01")),      # the prior 1.01 / 1.29 reproduction
    (D("3"), D("1")),                # a recurring quote/price division
    (D("0.00031234"), D("17.77")),   # a sub-unit price
])
def test_buy_notional_is_exactly_price_times_quantity(tmp_path, price, allocation):
    """The exact-identity failure, fixed structurally rather than tolerated.

    ``filled_quote_notional`` is derived from the executed quantity, so the
    identity is a property of how the fill is built rather than an accident of
    the numbers. It is asserted here against six prices that the old
    notional-first arithmetic could not represent.
    """
    app = application(tmp_path)
    app.execution.start()
    request = buy(amount=float(allocation), price=float(price))

    result = settle(app, request)

    base, quote = assert_exact_fill(result, approved=allocation)
    assert base == base.quantize(QUANTUM)
    assert D(position_of(app)["cost_quote"]) == quote


def test_buy_at_an_awkward_price_leaves_a_measured_sub_quantum_remainder(flat_app):
    """The remainder is stated in the result, not silently absorbed."""
    request = buy(amount=1000, price=float(AWKWARD_PRICE))

    result = settle(flat_app, request)

    assert D(result["filled_base_quantity"]) == D("775.19379844")
    assert D(result["filled_quote_notional"]) == D("999.9999999876")
    assert D(result["data"]["unallocated_quote_remainder"]) == D("0.0000000124")
    assert D(result["data"]["approved_quote_allocation"]) == D("1000")


def test_buy_at_a_btc_like_price_never_exceeds_the_approval(flat_app):
    request = buy(amount=2500, price=float(BTC_LIKE_PRICE))

    result = settle(flat_app, request)

    base, quote = assert_exact_fill(result, approved=D("2500"))
    assert quote < D("2500")
    assert base == D("0.05784375")


def test_buy_rounding_is_deterministic_across_identical_runtimes(tmp_path):
    first, second = application(tmp_path / "a"), application(tmp_path / "b")
    first.execution.start()
    second.execution.start()

    one = settle(first, buy(amount=1000, price=float(BTC_LIKE_PRICE)))
    two = settle(second, buy(amount=1000, price=float(BTC_LIKE_PRICE)))

    assert one["filled_base_quantity"] == two["filled_base_quantity"]
    assert one["filled_quote_notional"] == two["filled_quote_notional"]


def test_sub_quantum_buy_is_refused_at_admission(flat_app):
    """An approval too small to buy a single quantum is refused, never rounded up.

    The bound is a feasibility test on the amount the caller already asked for
    and the engine already approved. It sizes nothing: the request is refused
    rather than raised to the minimum executable notional.
    """
    manager = flat_app.execution
    minimum = D(str(BTC_LIKE_PRICE)) * QUANTUM
    request = buy(amount=0.0001, price=float(BTC_LIKE_PRICE))
    assert D(str(request.amount)) < minimum

    result = manager.risk_check(request)

    assert result["approved"] is False
    assert result["reason"] == "ALLOCATION_BELOW_EXECUTABLE_QUANTUM"
    assert D(result["details"]["minimum_executable_notional"]) == minimum
    assert D(result["details"]["approved_allocation"]) == D("0.0001")
    assert request.approved_quote_allocation is None
    assert manager.reservation_ledger.get("b1") is None
    assert manager._risk_admissions == {}


def test_sub_quantum_buy_through_execute_refuses_without_halting(flat_app):
    """F1: the refusal must land before anything is mutated.

    Reproduced before this fix: the affordability test lived only in
    ``_resolve_base_fill``, past ``_mark_execution_side_effect`` and past
    ``_paper_open_trade``. A single well-formed decision therefore reserved
    capital, opened a paper position the durable book never received, failed,
    and was classified as a post-side-effect interruption - INDETERMINATE
    capital, an unresolved journal entry and a halted runtime awaiting
    operator recovery.

    This is the assertion the old ``paper_execute``-only test could not make:
    the difference between the two outcomes is invisible unless the refusal is
    driven through the real orchestration.
    """
    result = drive(flat_app, buy_decision(
        amount=0.0001, price=float(BTC_LIKE_PRICE)
    ))

    assert result["success"] is False
    assert result["status"] == "REJECTED"
    assert result["reason"] == "ALLOCATION_BELOW_EXECUTABLE_QUANTUM"
    # Not a post-side-effect interruption: no unknown commit outcome at all.
    assert result.get("commit_outcome") is None
    assert result.get("original_status") is None
    assert_no_execution_residue(flat_app)


def test_sub_quantum_buy_leaves_no_journal_entry(flat_app):
    """The prepare barrier is never reached, so nothing needs resolving."""
    drive(flat_app, buy_decision(amount=0.0001, price=float(BTC_LIKE_PRICE)))

    assert flat_app.execution.transaction_journal.entries == {}


def test_a_sub_quantum_buy_does_not_block_a_later_valid_buy(flat_app):
    """A refusal that halted the runtime would make this impossible."""
    drive(flat_app, buy_decision(
        amount=0.0001, price=float(BTC_LIKE_PRICE), request_id="dust"
    ))

    result = drive(flat_app, buy_decision(
        amount=1000, price=float(AWKWARD_PRICE), request_id="real"
    ))

    assert result["status"] == "PAPER_EXECUTED"
    assert D(result["filled_quote_notional"]) == D("999.9999999876")


def test_buy_below_one_executable_quantum_fails_closed_at_the_backstop(flat_app):
    """``_resolve_base_fill`` stays as defence in depth behind the admission gate.

    Admission now refuses a sub-quantum approval outright, so reaching this
    check means the approval was altered after it was admitted. It must still
    refuse rather than round up - but note this is the *post*-side-effect path,
    which is exactly why the bound cannot live here alone.
    """
    manager = flat_app.execution
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    # An approval smaller than one quantum of base at this price.
    request.approved_quote_allocation = QUANTUM / D("1000")
    manager._risk_admissions[request.request_id] = manager._risk_admission_key(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "ALLOCATION_BELOW_EXECUTABLE_QUANTUM"
    assert position_of(flat_app) is None


def test_an_allocation_consumed_by_its_fee_still_fails_closed(flat_app):
    """The fee-inclusive half of the bound stays where the fee is first known.

    ``ExecutionRequest`` carries no pre-admission fee input, so admission can
    only bound the approval itself. A component whose reported fee consumes
    the whole allocation is therefore still caught by ``_resolve_base_fill``.
    """
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee": 1000.0, "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "ALLOCATION_BELOW_EXECUTABLE_QUANTUM"
    assert position_of(flat_app) is None


# ==========================================================================
# 4 — fee-inclusive settlement
# ==========================================================================


def test_a_reported_fee_is_paid_out_of_the_approval_not_on_top_of_it(flat_app):
    """Settlement debits notional + fee, so the approval must bound both.

    The repository models no pre-trade fee schedule and ``ExecutionRequest``
    exposes no pre-admission fee input, so the only fee that exists is the one
    the executing component reports at fill time. The BUY path therefore takes
    it out of the approved allocation, which is exactly the amount admission
    bounded and the reservation reserved.
    """
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": True, "fee": 2.5, "fee_currency": "USDT",
    }
    request = buy(amount=1000, price=float(AWKWARD_PRICE))

    result = settle(flat_app, request)

    approved = request.approved_quote_allocation
    base, quote = assert_exact_fill(result, approved=approved)
    fee = D(result["fee_amount"])
    snapshot = flat_app.portfolio_foundation.snapshot()

    assert fee == D("2.5")
    assert quote + fee <= approved
    assert snapshot["cash"] == TOTAL_CAPITAL - quote - fee
    assert snapshot["fees"] == fee
    # The reservation covered the whole economic requirement, fee included.
    assert manager.reservation_ledger.get("b1").amount >= quote + fee


def test_a_fee_without_a_declared_currency_fails_closed(flat_app):
    """The design gap, pinned rather than papered over.

    Nothing in this repository declares an instrument's quote asset, so a
    component that charges a fee without naming its currency leaves an
    unbooked denomination. That must stop at the evidence contract instead of
    being assumed to be quote currency.
    """
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {"success": True, "fee": 2.5}
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)

    result = manager.paper_execute(request)

    with pytest.raises(ValueError, match="fee_currency"):
        manager._finalize_durable_financial_state(request=request, result=result)

    assert position_of(flat_app) is None


def test_no_pre_admission_fee_input_exists_on_the_request():
    """Documented gap: admission cannot know a fee before execution.

    The approval is therefore treated as the fee-inclusive ceiling - the fee
    comes out of it at fill time - rather than a fee being predicted. If a
    pre-trade fee model is ever added, this assertion is the place that says
    the contract changed.
    """
    assert "fee" not in ExecutionRequest.__dataclass_fields__
    assert "expected_fee" not in ExecutionRequest.__dataclass_fields__


def test_settlement_above_the_approval_is_refused_at_finalization(flat_app):
    """Defence in depth: evidence that overspends never reaches the ledger."""
    manager = flat_app.execution
    request = buy(amount=1000, price=float(AWKWARD_PRICE))
    manager.risk_check(request)
    result = manager.paper_execute(request)

    result["filled_base_quantity"] = format(
        D(result["filled_base_quantity"]) * 2, "f"
    )
    result["filled_quote_notional"] = format(
        D(result["filled_quote_notional"]) * 2, "f"
    )

    with pytest.raises(PermissionError, match="SETTLEMENT_EXCEEDS_APPROVED_ALLOCATION"):
        manager._finalize_durable_financial_state(request=request, result=result)

    assert position_of(flat_app) is None


# ==========================================================================
# 5 — reduction precision, full close, and re-entry
# ==========================================================================


def test_partial_sell_executes_exactly_the_approved_reduction(holding_app):
    """Approved 40 of a 100 exposure -> 4 of 10 base sold, 6 left held."""
    manager = holding_app.execution
    request = sell(amount=40)

    result = settle(holding_app, request)

    assert request.approved_quote_allocation == D("40")
    assert D(result["filled_base_quantity"]) == D("4")
    assert D(result["filled_quote_notional"]) == D("40")
    assert result["data"]["partial_reduction"] is True

    position = position_of(holding_app)
    assert D(position["base_quantity"]) == D("6")
    assert D(position["cost_quote"]) == D("60")
    assert D(position["average_entry_price"]) == D("10")


def test_partial_sell_does_not_overwrite_the_request_with_the_holding(holding_app):
    """The 5A-era defect: the full base quantity replacing the approval."""
    manager = holding_app.execution
    request = sell(amount=40)
    manager.risk_check(request)

    result = manager.paper_execute(request)

    assert D(result["filled_base_quantity"]) != D("10")
    assert D(result["filled_quote_notional"]) != D("100")


def test_partial_reduction_at_an_awkward_basis_never_exceeds_the_approval(tmp_path):
    """A reduction the basis does not divide is floored, never rounded up."""
    app = application(tmp_path, positions=[("BTCUSDT", "1", "3")])
    app.execution.start()
    request = sell(amount=1, price=3)

    result = settle(app, request)

    basis = D(result["data"]["risk_basis_price"])
    base = D(result["filled_base_quantity"])
    executed = D(result["data"]["executed_quote_reduction"])

    assert base == D("0.33333333")
    assert base * basis == executed
    assert executed <= request.approved_quote_allocation
    assert request.approved_quote_allocation - executed < basis * QUANTUM
    assert D(position_of(app)["base_quantity"]) == D("0.66666667")


def test_unsized_sell_resolves_to_the_whole_durable_exposure(holding_app):
    request = sell()

    assert holding_app.execution.risk_check(request)["approved"] is True
    assert request.approved_quote_allocation == D("100")
    assert holding_app.execution.last_risk_decision["reason_code"] == (
        "RISK_REDUCTION_APPROVED"
    )


def test_full_sell_closes_the_position_with_no_decimal_dust(holding_app):
    request = sell(amount=100)

    result = settle(holding_app, request)

    assert D(result["filled_base_quantity"]) == D("10")
    assert result["data"]["partial_reduction"] is False
    assert result["data"]["unreduced_quote_remainder"] == "0"
    assert position_of(holding_app) is None
    assert holding_app.portfolio_foundation.snapshot()["gross_exposure"] == D("0")


def test_buy_then_partial_sell_then_full_remainder_exit_leaves_no_dust(flat_app):
    """The whole lifecycle at a price nothing divides evenly.

    An awkward entry price makes every downstream quantity awkward too: the
    entry quantity, the remaining exposure after a partial exit, and the final
    exit size. The position must still close to exactly nothing.
    """
    entry = settle(flat_app, buy(amount=1000, price=float(AWKWARD_PRICE),
                                 request_id="entry"))
    entry_base = D(entry["filled_base_quantity"])

    partial = settle(flat_app, sell(amount=400, price=float(AWKWARD_PRICE),
                                    request_id="partial"))
    partial_base = D(partial["filled_base_quantity"])

    remaining = position_of(flat_app)
    assert D(remaining["base_quantity"]) == entry_base - partial_base

    exit_request = sell(price=float(AWKWARD_PRICE), request_id="exit")
    final = settle(flat_app, exit_request)

    assert D(final["filled_base_quantity"]) == entry_base - partial_base
    assert position_of(flat_app) is None
    assert flat_app.portfolio_foundation.snapshot()["gross_exposure"] == D("0")
    assert flat_app.portfolio_foundation.snapshot()["positions"] == {}


def test_repeated_partial_reductions_still_close_exactly(flat_app):
    """Four partial exits and a final one, with no residue at the end."""
    entry = settle(flat_app, buy(amount=2000, price=float(BTC_LIKE_PRICE),
                                 request_id="entry"))
    sold = D("0")

    for index in range(4):
        result = settle(flat_app, sell(amount=300, price=float(BTC_LIKE_PRICE),
                                       request_id=f"cut{index}"))
        sold += D(result["filled_base_quantity"])
        assert position_of(flat_app) is not None

    held = D(position_of(flat_app)["base_quantity"])
    assert held == D(entry["filled_base_quantity"]) - sold

    final = settle(flat_app, sell(price=float(BTC_LIKE_PRICE), request_id="exit"))

    assert D(final["filled_base_quantity"]) == held
    assert position_of(flat_app) is None
    assert flat_app.portfolio_foundation.snapshot()["gross_exposure"] == D("0")


def test_re_entry_succeeds_immediately_after_a_full_close(flat_app):
    """A close that left dust would be refused here as a duplicate position."""
    settle(flat_app, buy(amount=1000, price=float(AWKWARD_PRICE), request_id="entry"))
    settle(flat_app, sell(price=float(AWKWARD_PRICE), request_id="exit"))

    assert position_of(flat_app) is None

    re_entry = buy(amount=500, price=float(BTC_LIKE_PRICE), request_id="reentry")
    result = settle(flat_app, re_entry)

    assert result["success"] is True
    assert flat_app.execution.last_risk_decision["reason_code"] == "RISK_APPROVED"
    assert D(position_of(flat_app)["cost_quote"]) == D(result["filled_quote_notional"])


def test_full_close_releases_the_max_position_slot(tmp_path):
    """The slot a closed position held must be genuinely free again."""
    app = application(
        tmp_path, positions=[(f"SYM{index}USDT", "1", "10") for index in range(5)]
    )
    app.execution.start()

    assert app.execution.risk_check(
        buy(symbol="OTHERUSDT", amount=100, request_id="blocked")
    )["reason"] == "MAX_POSITIONS_REACHED"

    app.paper_trader.open_trade("SYM0USDT", 10, 10)
    settle(app, sell(symbol="SYM0USDT", request_id="exit"))
    assert position_of(app, "SYM0USDT") is None

    result = app.execution.risk_check(
        buy(symbol="OTHERUSDT", amount=100, request_id="admitted")
    )

    assert result["approved"] is True
    assert result["reason"] == "RISK_APPROVED"


def test_oversized_sell_fails_closed_at_risk_admission(holding_app):
    manager = holding_app.execution

    result = manager.risk_check(sell(amount=140))

    assert result["approved"] is False
    assert result["reason"] == "INVALID_RISK_REDUCTION"
    assert manager._risk_admissions == {}
    assert D(position_of(holding_app)["base_quantity"]) == D("10")


def test_oversized_sell_fails_closed_at_execution_if_the_book_moved(holding_app):
    """Defence in depth: admission and the book disagreeing must not oversell."""
    manager = holding_app.execution
    request = sell(amount=100)
    manager.risk_check(request)

    # The durable book shrinks after admission.
    payload = holding_app.portfolio_foundation.store.load()
    payload["positions"]["BTCUSDT"] = held_position("BTCUSDT", "4", "10")
    holding_app.portfolio_foundation.store.save(payload)
    holding_app.portfolio_foundation._state = payload

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "REDUCTION_EXCEEDS_POSITION"
    assert D(position_of(holding_app)["base_quantity"]) == D("4")


def test_reduction_below_one_quantum_fails_closed(holding_app):
    """Too small to sell any positive quantity -> refuse, never round up."""
    manager = holding_app.execution
    request = sell(amount=40)
    manager.risk_check(request)

    request.approved_quote_allocation = QUANTUM / D("1000")
    manager._risk_admissions[request.request_id] = manager._risk_admission_key(request)

    result = manager.paper_execute(request)

    assert result["success"] is False
    assert result["error_code"] == "REDUCTION_BELOW_EXECUTABLE_QUANTUM"
    assert D(position_of(holding_app)["base_quantity"]) == D("10")


def test_partial_reduction_leaves_the_paper_book_untouched(holding_app):
    """PaperTrader can only express a whole exit, so it is not called."""
    manager = holding_app.execution
    calls: list[str] = []
    manager.paper_trader.close_trade = lambda symbol: calls.append(symbol)

    request = sell(amount=40)
    manager.risk_check(request)
    result = manager.paper_execute(request)

    assert calls == []
    assert result["data"]["paper_book_mutated"] is False


# ==========================================================================
# 6 — exposure basis
# ==========================================================================


def test_full_exit_is_admissible_when_the_execution_price_moved(holding_app):
    """The stale-mark defect: a legitimate exit refused for a basis mismatch.

    The book is marked at 10 (entry). The exit executes at 12. Admission and
    exit sizing both use the durable mark, so the exit is requested as the
    exposure it is compared against and is approved; the execution price
    prices the proceeds and nothing else.
    """
    request = sell(price=12)

    result = settle(holding_app, request)

    assert request.approved_quote_allocation == D("100")
    assert D(result["filled_base_quantity"]) == D("10")
    assert D(result["filled_quote_notional"]) == D("120")
    assert position_of(holding_app) is None


def test_exit_proceeds_differ_from_the_approved_reduction_only_by_price(holding_app):
    """The only permitted divergence, stated explicitly."""
    manager = holding_app.execution
    request = sell(price=12)
    manager.risk_check(request)

    result = manager.paper_execute(request)

    basis = D(result["data"]["risk_basis_price"])
    base = D(result["filled_base_quantity"])
    assert request.approved_quote_allocation == base * basis
    assert D(result["filled_quote_notional"]) == base * D(str(result["filled_price"]))


def test_exposure_basis_is_the_durable_mark_not_a_market_price(holding_app):
    state = holding_app.execution._derive_risk_state()

    assert state.positions[0].execution_price == D("10")
    assert state.committed_quote == D("100")


# ==========================================================================
# 7 — preserved risk policy
# ==========================================================================


@pytest.mark.parametrize("risk,reason", [
    ("CRITICAL", "CRITICAL_RISK_NOT_EXECUTABLE"),
    ("EXTREME", "UNSUPPORTED_RISK_LEVEL"),
])
def test_non_executable_risk_keeps_its_own_verdict(flat_app, risk, reason):
    """A sized request still gets the engine's verdict about its risk level.

    The allocation contract must not collapse a policy verdict into a generic
    refusal: CRITICAL and an unsupported classification stay distinguishable
    from each other and from malformed input.
    """
    request = buy(risk=risk, amount=500)

    result = flat_app.execution.risk_check(request)

    assert result["approved"] is False
    assert result["reason"] == reason
    assert request.approved_quote_allocation is None
    assert flat_app.execution.reservation_ledger.get("b1") is None
    assert flat_app.execution._risk_admissions == {}


def test_unsized_critical_buy_is_refused_for_being_unsized(flat_app):
    """Unsized is decided first, because there is nothing to evaluate yet.

    This is not a weakening: a CRITICAL BUY is refused either way, and the
    sized case above still proves the CRITICAL verdict itself is reachable.
    """
    result = flat_app.execution.risk_check(buy(risk="CRITICAL"))

    assert result["approved"] is False
    assert result["reason"] == "UNSIZED_REQUEST_REJECTED"
    assert flat_app.execution.reservation_ledger.get("b1") is None


def test_critical_reduction_remains_permitted(holding_app):
    """Exiting risk is always allowed, whatever the classification says."""
    request = sell(risk="CRITICAL")

    result = holding_app.execution.risk_check(request)

    assert result["approved"] is True
    assert holding_app.execution.last_risk_decision["reason_code"] == (
        "RISK_REDUCTION_APPROVED"
    )
    assert request.approved_quote_allocation == D("100")


def test_critical_reduction_executes_and_closes_the_position(holding_app):
    result = settle(holding_app, sell(risk="CRITICAL"))

    assert D(result["filled_base_quantity"]) == D("10")
    assert position_of(holding_app) is None


def test_duplicate_buy_remains_denied(holding_app):
    result = holding_app.execution.risk_check(buy(amount=100))

    assert result["approved"] is False
    assert result["reason"] == "DUPLICATE_OPEN_POSITION"


def test_max_positions_remains_enforced(tmp_path):
    app = application(
        tmp_path, positions=[(f"SYM{index}USDT", "1", "10") for index in range(5)]
    )
    app.execution.start()

    result = app.execution.risk_check(buy(symbol="OTHERUSDT", amount=100))

    assert result["approved"] is False
    assert result["reason"] == "MAX_POSITIONS_REACHED"


def test_confidence_policy_remains_enforced(flat_app):
    """65% clears the manager's own floor but not the MEDIUM bucket's 70%."""
    result = flat_app.execution.risk_check(buy(amount=100, confidence=65))

    assert result["approved"] is False
    assert result["reason"] == "CONFIDENCE_BELOW_POLICY"
    assert flat_app.execution.reservation_ledger.get("b1") is None


# ==========================================================================
# 8 — reconciliation after success and after failure
# ==========================================================================


def test_state_reservation_and_foundation_reconcile_after_success(flat_app):
    manager = flat_app.execution
    request = buy(amount=1000, price=float(AWKWARD_PRICE))

    result = settle(flat_app, request)

    snapshot = flat_app.portfolio_foundation.snapshot()
    executed = D(result["filled_quote_notional"])

    assert manager.reservation_ledger.get("b1").status.value == "COMMITTED"
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert snapshot["reserved_capital"] == D("0")
    assert snapshot["cash"] == TOTAL_CAPITAL - executed
    assert snapshot["committed_capital"] == executed
    assert snapshot["equity"] == TOTAL_CAPITAL - executed + snapshot["gross_exposure"]
    assert manager._risk_admissions == {}


def test_state_reservation_and_foundation_reconcile_after_failure(flat_app):
    manager = flat_app.execution
    manager._paper_open_trade = lambda **kwargs: {
        "success": False, "reason": "paper book refused"
    }
    request = buy(amount=1000)
    manager.risk_check(request)

    result = manager.paper_execute(request)
    manager._release_capital_reservation(request.request_id)

    snapshot = flat_app.portfolio_foundation.snapshot()

    assert result["success"] is False
    assert manager.reservation_ledger.get("b1").status.value == "RELEASED"
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert snapshot["cash"] == TOTAL_CAPITAL
    assert snapshot["positions"] == {}
    assert manager._risk_admissions == {}


# ==========================================================================
# 8b — the same invariants through the real execute() orchestration
# ==========================================================================
#
# Sections 2-5 compose the stages by hand through `settle()`, which is what
# makes the per-stage arithmetic readable. None of it exercises the idempotency
# claim, the journal prepare barrier, the side-effect boundary, or the failure
# classification - so the invariants that depend on *where* a step happens are
# re-proved here against the production entry point.


def test_buy_settles_through_execute_with_the_exact_identity(flat_app):
    result = drive(flat_app, buy_decision(amount=1000, price=float(AWKWARD_PRICE)))

    assert result["status"] == "PAPER_EXECUTED"
    assert result["commit_outcome"] == "COMMITTED"

    base, quote = assert_exact_fill(result, approved=D("1000"))
    snapshot = flat_app.portfolio_foundation.snapshot()

    assert D(position_of(flat_app)["base_quantity"]) == base
    assert D(position_of(flat_app)["cost_quote"]) == quote
    assert snapshot["cash"] == TOTAL_CAPITAL - quote
    assert flat_app.execution.reservation_ledger.get("b1").status.value == "COMMITTED"
    assert flat_app.execution.reservation_ledger.active_reserved_capital() == D("0")
    assert flat_app.execution._risk_admissions == {}
    assert flat_app.execution._execution_side_effect_ids == set()
    assert flat_app.execution.execution_halted is False


def test_partial_sell_settles_through_execute(holding_app):
    """The partial-reduction path had no execute()-level coverage at all."""
    result = drive(holding_app, sell_decision(amount=40))

    assert result["status"] == "PAPER_EXECUTED"
    assert result["commit_outcome"] == "COMMITTED"
    assert result["data"]["partial_reduction"] is True
    assert D(result["filled_base_quantity"]) == D("4")

    position = position_of(holding_app)

    assert D(position["base_quantity"]) == D("6")
    assert D(position["cost_quote"]) == D("60")
    assert D(position["average_entry_price"]) == D("10")
    assert holding_app.execution._execution_side_effect_ids == set()
    assert holding_app.execution.execution_halted is False


def test_full_sell_settles_through_execute(holding_app):
    result = drive(holding_app, sell_decision(amount=100))

    assert result["status"] == "PAPER_EXECUTED"
    assert D(result["filled_base_quantity"]) == D("10")
    assert result["data"]["partial_reduction"] is False
    assert position_of(holding_app) is None
    assert holding_app.execution.execution_halted is False


def test_full_lifecycle_through_execute_leaves_no_dust(flat_app):
    """Entry, partial exit and full remainder exit, all through execute()."""
    entry = drive(flat_app, buy_decision(
        amount=1000, price=float(AWKWARD_PRICE), request_id="entry"
    ))
    entry_base = D(entry["filled_base_quantity"])

    partial = drive(flat_app, sell_decision(
        amount=400, price=float(AWKWARD_PRICE), request_id="partial"
    ))
    partial_base = D(partial["filled_base_quantity"])

    assert partial["data"]["partial_reduction"] is True
    assert D(position_of(flat_app)["base_quantity"]) == entry_base - partial_base

    final = drive(flat_app, sell_decision(
        amount=0, price=float(AWKWARD_PRICE), request_id="exit"
    ))

    assert final["status"] == "PAPER_EXECUTED"
    assert D(final["filled_base_quantity"]) == entry_base - partial_base
    assert position_of(flat_app) is None
    assert flat_app.portfolio_foundation.snapshot()["gross_exposure"] == D("0")
    assert flat_app.execution.execution_halted is False


def test_unsized_buy_through_execute_leaves_no_residue(flat_app):
    """The 5B refusal, proved against the orchestration rather than risk_check."""
    result = drive(flat_app, buy_decision(amount=0))

    assert result["success"] is False
    assert result["reason"] == "UNSIZED_REQUEST_REJECTED"
    assert_no_execution_residue(flat_app)


# ==========================================================================
# 9 — real MarketLoop end to end
# ==========================================================================


def build_closed_candles(count: int = 200, *, epoch: int = 0) -> list[list[Any]]:
    """Deterministic closed candles. No exchange connection is opened.

    ``epoch`` advances the candle identity so a second ``process_symbol`` call
    is not skipped as DUPLICATE_CLOSED_CANDLE - the loop only acts once per
    closed candle, which is correct loop behaviour and not under test here.
    """
    rows: list[list[Any]] = []
    for index in range(count):
        open_ms = 1_700_000_000_000 + (epoch * count + index) * 60_000
        base = 100.0 + index * 0.75
        volume = 10.0 + index * 0.1
        rows.append([
            open_ms, f"{base:.2f}", f"{base + 35.0:.2f}", f"{base - 25.0:.2f}",
            f"{base + 12.0:.2f}", f"{volume:.5f}", open_ms + 59_999, "0.0", 0,
            f"{volume * 0.4:.5f}", f"{(base + 12.0) * volume * 0.4:.8f}", "0",
        ])
    return rows


class OfflineMarketFeed:
    def __init__(self, epoch: int = 0) -> None:
        self.epoch = epoch

    def candles(self, symbol, interval="1m", limit=500):
        return build_closed_candles(limit, epoch=self.epoch)


class DecidingBrain:
    """Emits an *unsized* decision, exactly as the real adapter produces."""

    def __init__(self, action: str) -> None:
        self.action = action
        self.calls: list[str] = []

    def analyze_and_decide(self, symbol, market_data):
        self.calls.append(symbol)
        return {
            "symbol": symbol,
            "action": self.action,
            "confidence": 90.0,
            "risk": "MEDIUM",
            "strategy": "BLOCK5B_SINGLE_SIZING_AUTHORITY",
            "reason": "Offline runtime sizing contract.",
        }


def execution_enabled_loop(app: AtlasApplication, action: str,
                           epoch: int = 0) -> MarketLoop:
    loop = app.market_loop
    loop.brain = DecidingBrain(action)
    loop.market_feed = OfflineMarketFeed(epoch)
    loop.symbols = ["BTCUSDT"]
    assert loop.execution is app.execution
    return loop


def test_real_market_loop_buy_fails_closed_because_it_is_unsized(flat_app):
    """The runtime's decision path still produces no allocation.

    Package 5B refuses to invent one. Until a deliberate sizing authority
    exists upstream, a genuine loop BUY must stop here - visibly, on its own
    reason code, with nothing reserved and nothing executed. It must not be
    reported as malformed input (defect A's symptom) and must not execute.
    """
    manager = flat_app.execution

    result = execution_enabled_loop(flat_app, "BUY").process_symbol("BTCUSDT")

    assert result.get("status") != "PAPER_EXECUTED"
    assert result.get("reason") != "INVALID_FINANCIAL_INPUT"
    assert result.get("reason") == "UNSIZED_REQUEST_REJECTED"
    assert position_of(flat_app) is None
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert manager._risk_admissions == {}
    assert manager.execution_halted is False


def test_real_market_loop_sell_still_exits_a_held_position(holding_app):
    """An exit is not a sizing decision, so the loop can still close risk.

    This is the safety-critical half of the loop path: a runtime that cannot
    open new risk must still be able to reduce the risk it already carries.
    """
    manager = holding_app.execution

    result = execution_enabled_loop(holding_app, "SELL").process_symbol("BTCUSDT")

    assert result["status"] == "PAPER_EXECUTED"
    assert manager.last_risk_decision["reason_code"] == "RISK_REDUCTION_APPROVED"
    assert D(result["filled_base_quantity"]) == D("10")
    assert position_of(holding_app) is None
    assert manager.reservation_ledger.active_reserved_capital() == D("0")


def test_real_market_loop_writes_only_the_configured_state_root(tmp_path):
    """The E2E path persists under the injected state directory and nowhere else."""
    app = application(tmp_path, positions=[("BTCUSDT", "10", "10")])
    app.paper_trader.open_trade("BTCUSDT", 10, 100)
    app.execution.start()

    execution_enabled_loop(app, "SELL").process_symbol("BTCUSDT")

    state_dir = tmp_path / "state"
    assert (state_dir / EXECUTION_FINANCIAL_STATE_FILE).exists()
    assert (state_dir / PAPER_TRADE_BOOK_FILE).exists()
