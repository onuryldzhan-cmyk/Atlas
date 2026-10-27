"""Block-5C: a single, pure, upstream BUY sizing authority.

Package 5B made ``ExecutionManager`` size nothing: an unsized BUY refuses as
``UNSIZED_REQUEST_REJECTED`` rather than inheriting a policy ceiling. 5B left
the runtime with no way to size a BUY at all, so every genuine loop BUY still
died unsized.

5C adds exactly one upstream proposer, ``PositionSizingService``, and wires it
into a dedicated exact pre-admission transport,
``ExecutionRequest.proposed_quote_allocation`` (Block 5C B1 remediation): a
``Decimal | None`` field that carries the sizing proposal to
``_requested_quote_allocation`` losslessly, never through the lossy
``amount: float`` compatibility mirror. The authority chain this package
proves, end to end, is:

    PositionSizingService  -> PROPOSES  (core/position_sizing.py)
    RiskEngine               -> APPROVES / REJECTS  (core/risk_engine.py)
    risk_check                 -> ADMITS / RESERVES  (core/execution_manager.py)
    Execution                   -> EXECUTES

The sizing formula is exactly:

    capacity  = derive_buy_capacity_limits(policy, bucket_policy,
                    symbol_exposure=symbol_exposure, committed_quote=committed_quote)
    candidate = durable_free_quote_capital * bucket_policy.max_allocation_pct
    proposed  = min(
        candidate,
        capacity.max_position,               # total_capital * max_position_pct
        capacity.bucket_allocation,           # total_capital * bucket_policy.max_allocation_pct
        capacity.per_symbol,                  # total_capital * per_symbol_pct - symbol_exposure
        capacity.concentration,               # total_capital * concentration_pct - symbol_exposure
        capacity.bucket_exposure_ceiling,     # total_capital * bucket_policy.exposure_ceiling_pct - symbol_exposure
        capacity.portfolio_exposure,          # total_capital * portfolio_exposure_pct - committed_quote
        capacity.allocatable_capital,         # policy.allocatable_capital - committed_quote
        durable_free_quote_capital,
    )

where ``durable_free_quote_capital = durable cash - active reservations``,
computed the same way ``ExecutionManager._durable_free_quote_capital``
already computes it, and ``derive_buy_capacity_limits`` (core/risk_engine.py)
is the single shared derivation ``RiskEngine.evaluate`` itself now also calls
for its own BUY admission limits (Block 5C M1/M2 remediation) - so a proposal
this service considers fine can never exceed a limit RiskEngine will actually
enforce, and a policy or exposure change can never let the two authorities'
ceilings drift apart. RiskEngine remains the sole approve/reject authority:
a sizing proposal that would violate a limit outside this shared capacity set
(confidence, drawdown, daily loss, position count, duplicate position) is
still rejected by RiskEngine, never silently trimmed.

Every fixture writes into pytest's tmp_path. Nothing here may touch the
operator's real runtime state.
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import UTC, datetime
from decimal import Decimal as D
from typing import Any

import pytest

from tests._market_clock import pin_clock_to_feed

import core.position_sizing as position_sizing_module
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
from core.position_sizing import (
    PositionSizingService,
    SizingInputs,
    SizingProposal,
    SizingStatus,
)
from core.risk_engine import (
    BucketPolicy, RiskBucket, RiskDecisionStatus, RiskEngine, RiskPolicy, RiskRequest, RiskState,
    PositionExposure, derive_buy_capacity_limits,
)
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState
from tools.build_architecture_inventory import load_architecture_map

POLICY_VERSION = "phase3-risk-v1"

# AtlasApplication derives RiskPolicy from CapitalManager.total_capital.
TOTAL_CAPITAL = D("10000")

# The default MEDIUM-bucket allocation percentage, matching Block-5B's own
# MEDIUM_BUCKET_CEILING constant.
MEDIUM_BUCKET_PCT = D("0.25")
MEDIUM_PROPOSAL_ON_A_FLAT_BOOK = TOTAL_CAPITAL * MEDIUM_BUCKET_PCT


# ==========================================================================
# durable state seeding (mirrors tests/test_block5b_single_sizing_authority.py)
# ==========================================================================


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
               peak="10000", equity="10000", leverage=1):
    state_dir.mkdir(parents=True, exist_ok=True)

    JsonReservationStore(state_dir / CAPITAL_RESERVATION_STATE_FILE).initialize_empty()

    JsonRiskStateStore(state_dir / RISK_ACCOUNTING_STATE_FILE).save(
        RestoredRiskState(
            datetime.now(UTC).date(), D(pnl), D(peak), D(equity), POLICY_VERSION
        )
    )

    store = FinancialStateStore(state_dir / EXECUTION_FINANCIAL_STATE_FILE)
    store.initialize(D(cash), leverage=leverage)   # Task 025: leverage 2 seeds the forex margin book

    if positions:
        payload = store.load()
        for symbol, base, price in positions:
            payload["positions"][symbol] = held_position(symbol, base, price)
            if leverage > 1:
                held = payload["positions"][symbol]
                held["margin"] = format(D(held["cost_quote"]) / leverage, "f")
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
    app = application(tmp_path, positions=[("BTCUSDT", "10", "10")])
    app.paper_trader.open_trade("BTCUSDT", 10, 100)
    app.execution.start()
    return app


def position_of(app: AtlasApplication, symbol="BTCUSDT"):
    return app.portfolio_foundation.snapshot()["positions"].get(symbol)


def buy_decision(**overrides: Any) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT", "action": "BUY", "price": 10, "amount": 0,
        "confidence": 90.0, "risk": "MEDIUM", "request_id": "b1", **overrides,
    }


def sell_decision(**overrides: Any) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT", "action": "SELL", "price": 10, "amount": 0,
        "confidence": 90.0, "risk": "MEDIUM", "request_id": "s1", **overrides,
    }


def sizing_inputs(**overrides: Any) -> SizingInputs:
    base: dict[str, Any] = dict(
        request_id="r1", symbol="BTCUSDT", risk_bucket="MEDIUM",
        durable_free_quote_capital=D("10000"), symbol_exposure=D("0"),
        committed_quote=D("0"),
    )
    base.update(overrides)
    return SizingInputs(**base)


def flat_state(policy: RiskPolicy) -> RiskState:
    """A durable-book-agrees-with-itself RiskState for direct RiskEngine calls."""
    return RiskState(
        positions=(), committed_quote=D("0"), realized_daily_pnl=D("0"),
        peak_equity=D("10000"), current_equity=D("10000"), state_ready=True,
        accounting_day_utc=datetime.now(UTC).date().isoformat(),
        policy_version=policy.version,
    )


# ==========================================================================
# 1 — PositionSizingService: pure contract
# ==========================================================================


def test_same_inputs_produce_the_same_proposal():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))
    inputs = sizing_inputs()

    first = service.propose(inputs)
    second = service.propose(inputs)

    assert first.status is second.status is SizingStatus.PROPOSED
    assert first.proposed_quote_allocation == second.proposed_quote_allocation


def test_same_inputs_produce_the_same_inputs_digest():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))
    inputs = sizing_inputs()

    first = service.propose(inputs)
    second = service.propose(inputs)

    assert first.provenance["inputs_digest"] == second.provenance["inputs_digest"]
    assert len(first.provenance["inputs_digest"]) == 64  # sha256 hex


def test_a_different_capital_basis_changes_the_digest():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))

    a = service.propose(sizing_inputs(durable_free_quote_capital=D("10000")))
    b = service.propose(sizing_inputs(durable_free_quote_capital=D("9999")))

    assert a.provenance["inputs_digest"] != b.provenance["inputs_digest"]


def test_authoritative_values_are_decimal_throughout():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))
    proposal = service.propose(sizing_inputs())

    assert isinstance(proposal.proposed_quote_allocation, D)
    assert not isinstance(proposal.proposed_quote_allocation, float)
    for key in ("durable_free_quote_capital", "basis_pct", "proposed_quote_allocation",
                "remaining_symbol_capacity", "remaining_position_capacity",
                "remaining_concentration_capacity", "remaining_portfolio_capacity"):
        assert isinstance(proposal.provenance[key], str)
        D(proposal.provenance[key])  # round-trips as an exact decimal string


@pytest.mark.parametrize("field", ["durable_free_quote_capital", "symbol_exposure", "committed_quote"])
def test_float_financial_input_is_rejected_at_construction(field):
    kwargs = {field: 1234.5}
    with pytest.raises(ValueError):
        sizing_inputs(**kwargs)


def test_bool_financial_input_is_rejected_at_construction():
    with pytest.raises(ValueError):
        sizing_inputs(durable_free_quote_capital=True)


def test_the_service_uses_the_actual_authorized_bucket_percentage():
    policy = RiskPolicy(total_capital=TOTAL_CAPITAL)
    service = PositionSizingService(policy)

    for bucket, expected_pct in (
        (RiskBucket.LOW, D("0.40")), (RiskBucket.MEDIUM, D("0.25")), (RiskBucket.HIGH, D("0.10")),
    ):
        proposal = service.propose(sizing_inputs(risk_bucket=bucket.value))
        assert proposal.provenance["basis_pct"] == format(expected_pct, "f")
        assert proposal.proposed_quote_allocation == TOTAL_CAPITAL * expected_pct


def test_an_unusual_policy_percentage_is_honoured_exactly():
    """Proves the basis is read from policy, not from a hidden constant ladder."""
    custom = RiskPolicy(
        total_capital=TOTAL_CAPITAL,
        buckets={
            RiskBucket.LOW: BucketPolicy(D("0.37"), D("0.60"), D("0.60")),
            RiskBucket.MEDIUM: BucketPolicy(D("0.13"), D("0.70"), D("0.40")),
            RiskBucket.HIGH: BucketPolicy(D("0.02"), D("0.80"), D("0.20")),
        },
    )
    service = PositionSizingService(custom)

    proposal = service.propose(sizing_inputs(risk_bucket="LOW"))

    assert proposal.proposed_quote_allocation == TOTAL_CAPITAL * D("0.37")


def test_no_legacy_sizing_ladder_or_score_multiplier_or_invented_default_exists():
    source = inspect.getsource(position_sizing_module)
    for forbidden in ("total_score", "* 15", "0.01", "CapitalManager"):
        assert forbidden not in source, forbidden


def test_confidence_is_not_a_sizing_input():
    """AI confidence must never be a direct allocation multiplier (Owner Decision 1)."""
    field_names = {f.name for f in dataclasses.fields(SizingInputs)}
    assert "confidence" not in field_names


def test_static_capital_manager_default_is_not_the_sizing_basis():
    """Durable free capital drives the proposal even while policy.total_capital is fixed."""
    policy = RiskPolicy(total_capital=D("10000"))
    service = PositionSizingService(policy)

    generous = service.propose(sizing_inputs(durable_free_quote_capital=D("10000")))
    depleted = service.propose(sizing_inputs(durable_free_quote_capital=D("1")))

    assert generous.proposed_quote_allocation == D("2500.00")
    # 0.25 * 1 = 0.25, still bound downward by the same durable figure.
    assert depleted.proposed_quote_allocation == D("0.25")
    assert generous.proposed_quote_allocation != depleted.proposed_quote_allocation


def test_zero_durable_free_capital_is_refused():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))

    proposal = service.propose(sizing_inputs(durable_free_quote_capital=D("0")))

    assert proposal.status is SizingStatus.REFUSED
    assert proposal.proposed_quote_allocation == D("0")


def test_zero_remaining_symbol_capacity_is_refused():
    policy = RiskPolicy(total_capital=TOTAL_CAPITAL, per_symbol_pct=D("0.10"))
    service = PositionSizingService(policy)

    # Symbol already carries exactly the per-symbol ceiling in durable exposure.
    proposal = service.propose(sizing_inputs(symbol_exposure=TOTAL_CAPITAL * D("0.10")))

    assert proposal.status is SizingStatus.REFUSED
    assert proposal.reason_code == "NON_POSITIVE_PROPOSAL"


def test_proposal_never_exceeds_durable_free_capital():
    policy = RiskPolicy(total_capital=D("1000000"))  # policy ceilings far above free capital
    service = PositionSizingService(policy)

    proposal = service.propose(sizing_inputs(durable_free_quote_capital=D("5")))

    assert proposal.status is SizingStatus.PROPOSED
    assert proposal.proposed_quote_allocation <= D("5")


def test_critical_risk_is_refused_without_proposing_a_size():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))

    proposal = service.propose(sizing_inputs(risk_bucket="CRITICAL"))

    assert proposal.status is SizingStatus.REFUSED
    assert proposal.reason_code == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert proposal.proposed_quote_allocation == D("0")


def test_unsupported_risk_is_refused_without_proposing_a_size():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))

    proposal = service.propose(sizing_inputs(risk_bucket="EXTREME"))

    assert proposal.status is SizingStatus.REFUSED
    assert proposal.reason_code == "UNSUPPORTED_RISK_LEVEL"
    assert proposal.provenance["risk_bucket"] == "UNKNOWN"


def test_service_and_proposal_never_expose_an_approval_surface():
    """Structural: nothing here can write approved_quote_allocation."""
    for name in ("approve", "approved_quote_allocation", "reserve", "execute"):
        assert not hasattr(PositionSizingService, name)
        assert not hasattr(SizingProposal, name)


def test_service_holds_no_io_or_reservation_or_execution_capability():
    source = inspect.getsource(position_sizing_module)
    for forbidden in ("open(", "requests.", "socket", "reservation_ledger", "portfolio_foundation"):
        assert forbidden not in source, forbidden


def test_another_requests_active_reservation_reduces_this_requests_free_capital(flat_app):
    """Owner Decision 2: durable_free_quote_capital = durable cash - active reservations.

    Isolates the mechanism directly: with nothing reserved, a second symbol's
    request sees the full durable cash; once the first symbol's BUY holds an
    active reservation, the second symbol's freshly computed capital basis is
    reduced by exactly that amount.
    """
    manager = flat_app.execution

    before = manager.portfolio_foundation.snapshot()["cash"] - manager.reservation_ledger.active_reserved_capital()
    assert before == TOTAL_CAPITAL

    manager.reservation_ledger.reserve("first-req", "first-req", D("3000"))

    decision = {"symbol": "ETHUSDT", "action": "BUY", "price": 10, "confidence": 90.0,
                "risk": "MEDIUM", "metadata": {}}
    flat_app.market_loop._apply_position_sizing("BUY", decision, "second-req")

    sizing = decision["metadata"]["sizing"]
    assert D(sizing["durable_free_quote_capital"]) == TOTAL_CAPITAL - D("3000")
    assert decision["proposed_quote_allocation"] == (TOTAL_CAPITAL - D("3000")) * MEDIUM_BUCKET_PCT
    assert "amount" not in decision


# ==========================================================================
# 2 — capacity bounding, downward only
# ==========================================================================


def test_per_symbol_capacity_binds_when_tighter_than_the_bucket_percentage():
    policy = RiskPolicy(total_capital=TOTAL_CAPITAL, per_symbol_pct=D("0.05"))
    service = PositionSizingService(policy)

    proposal = service.propose(sizing_inputs())

    assert proposal.proposed_quote_allocation == TOTAL_CAPITAL * D("0.05")
    assert proposal.proposed_quote_allocation < MEDIUM_PROPOSAL_ON_A_FLAT_BOOK


def test_concentration_capacity_binds_when_tighter():
    policy = RiskPolicy(total_capital=TOTAL_CAPITAL, concentration_pct=D("0.03"))
    service = PositionSizingService(policy)

    proposal = service.propose(sizing_inputs())

    assert proposal.proposed_quote_allocation == TOTAL_CAPITAL * D("0.03")


def test_portfolio_exposure_capacity_binds_when_tighter():
    policy = RiskPolicy(total_capital=TOTAL_CAPITAL, portfolio_exposure_pct=D("0.30"))
    service = PositionSizingService(policy)

    # committed_quote already close to the portfolio ceiling.
    proposal = service.propose(sizing_inputs(committed_quote=D("2950")))

    assert proposal.proposed_quote_allocation == TOTAL_CAPITAL * D("0.30") - D("2950")


def test_position_capacity_ceiling_is_respected():
    policy = RiskPolicy(total_capital=TOTAL_CAPITAL, max_position_pct=D("0.02"))
    service = PositionSizingService(policy)

    proposal = service.propose(sizing_inputs())

    assert proposal.proposed_quote_allocation == TOTAL_CAPITAL * D("0.02")


@pytest.mark.parametrize("tightened_field,value", [
    ("per_symbol_pct", D("0.01")),
    ("concentration_pct", D("0.01")),
    ("portfolio_exposure_pct", D("0.01")),
    ("max_position_pct", D("0.01")),
])
def test_every_capacity_only_ever_bounds_downward(tightened_field, value):
    baseline = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))
    tightened = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL, **{tightened_field: value}))

    baseline_proposal = baseline.propose(sizing_inputs())
    tightened_proposal = tightened.propose(sizing_inputs())

    assert tightened_proposal.proposed_quote_allocation <= baseline_proposal.proposed_quote_allocation


def test_proposal_is_never_raised_to_satisfy_a_minimum():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))

    tiny = service.propose(sizing_inputs(durable_free_quote_capital=D("0.00000001")))

    assert tiny.status is SizingStatus.PROPOSED
    assert tiny.proposed_quote_allocation == D("0.0000000025")
    assert tiny.proposed_quote_allocation < D("1")


# ==========================================================================
# 3 — authority boundaries preserved (Block 5B untouched)
# ==========================================================================


def test_no_sizing_surface_reappears_on_the_manager():
    for name in ("DEFAULT_ALLOCATION", "allocate_capital", "_calculate_manager_position_size",
                 "_available_capital", "_capital_risk_check", "_propose_quote_allocation",
                 "size_position", "propose_allocation"):
        assert not hasattr(ExecutionManager, name), name


def test_risk_engine_still_exposes_no_public_sizing_query(flat_app):
    assert not hasattr(flat_app.execution.risk_engine, "maximum_new_risk_allocation")
    for name in ("propose", "size", "sizing_service", "position_sizing_service"):
        assert not hasattr(flat_app.execution.risk_engine, name)


def test_decision_adapter_carries_no_sizing_logic(flat_app):
    for name in ("propose", "size_position", "position_sizing_service", "amount"):
        assert not hasattr(flat_app.market_loop.decision_adapter, name)


def test_unsized_buy_with_no_sizer_configured_is_still_rejected(flat_app):
    """Preserves Package 5B exactly when sizing is not wired at all."""
    flat_app.market_loop.position_sizing_service = None

    result = flat_app.execution.execute(buy_decision(amount=0))

    assert result["success"] is False
    assert result["reason"] == "UNSIZED_REQUEST_REJECTED"
    assert flat_app.execution.reservation_ledger.active_reserved_capital() == D("0")


def test_a_bare_market_loop_without_a_sizer_defaults_to_none():
    """The constructor default preserves 5B behaviour when nobody wires a sizer."""
    loop = MarketLoop(brain=None, market_feed=None, execution=None)
    assert loop.position_sizing_service is None


def test_sell_action_never_enters_the_sizing_service(flat_app):
    decision = sell_decision(amount=0)

    result = flat_app.market_loop._apply_position_sizing("SELL", decision, "s1")

    assert result is None
    assert decision.get("amount") == 0
    assert "sizing" not in decision.get("metadata", {})


def test_hold_and_other_non_buy_actions_never_enter_the_sizing_service(flat_app):
    decision = {"symbol": "BTCUSDT"}
    for action in ("HOLD", "WAIT", "SELL", "UNKNOWN"):
        assert flat_app.market_loop._apply_position_sizing(action, decision, "x1") is None
    assert "amount" not in decision
    assert "proposed_quote_allocation" not in decision


def test_unsized_sell_full_exit_still_uses_exact_durable_exposure_with_sizer_wired(holding_app):
    """5B rule: an unsized SELL against a held position exits at the durable quantity."""
    result = holding_app.execution.execute(sell_decision(amount=0))

    assert result["status"] == "PAPER_EXECUTED"
    assert D(result["filled_base_quantity"]) == D("10")
    assert position_of(holding_app) is None


def test_reduce_only_semantics_are_unchanged_with_sizer_wired(holding_app):
    request = ExecutionRequest("BTCUSDT", "SELL", 10, 4, confidence=90, risk="MEDIUM",
                               request_id="partial", reduce_only=False)

    admission = holding_app.execution.risk_check(request)

    assert admission["approved"] is True
    assert request.reduce_only is True  # derived from held-position state, not caller intent
    assert request.approved_quote_allocation == D("4")


# ==========================================================================
# 4 — replay / request-identity safety
# ==========================================================================


def test_matching_replay_reuses_the_identical_proposal(flat_app):
    decision_a = buy_decision(amount=0, metadata={})
    decision_b = buy_decision(amount=0, metadata={})

    refusal_a = flat_app.market_loop._apply_position_sizing("BUY", decision_a, "same-id")
    refusal_b = flat_app.market_loop._apply_position_sizing("BUY", decision_b, "same-id")

    assert refusal_a is None and refusal_b is None
    assert decision_a["proposed_quote_allocation"] == decision_b["proposed_quote_allocation"]
    assert isinstance(decision_a["proposed_quote_allocation"], D)
    assert (decision_a["metadata"]["sizing"]["inputs_digest"]
            == decision_b["metadata"]["sizing"]["inputs_digest"])


def test_replayed_request_with_an_existing_reservation_reuses_it_without_conflict(flat_app):
    manager = flat_app.execution
    manager.reservation_ledger.reserve("same-id", "same-id", MEDIUM_PROPOSAL_ON_A_FLAT_BOOK)

    decision = buy_decision(amount=0, metadata={})
    refusal = flat_app.market_loop._apply_position_sizing("BUY", decision, "same-id")

    assert refusal is None
    assert decision["proposed_quote_allocation"] == MEDIUM_PROPOSAL_ON_A_FLAT_BOOK
    assert "amount" not in decision or decision["amount"] == 0


def test_replay_with_conflicting_sizing_inputs_fails_closed_before_reservation(flat_app):
    manager = flat_app.execution
    request_id = "same-id"

    # A first admission already reserved 2500 for this exact request identity.
    manager.reservation_ledger.reserve(request_id, request_id, D("2500"))
    # Unrelated capital gets encumbered in between, so a fresh proposal for the
    # same request identity now prices differently.
    manager.reservation_ledger.reserve("other", "other", D("4000"))

    decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    refusal = flat_app.market_loop._apply_position_sizing("BUY", decision, request_id)

    assert refusal is not None
    assert refusal["reason"] == "SIZING_REPLAY_CONFLICT"
    assert refusal["success"] is False


def test_replay_conflict_never_mutates_the_existing_reservation(flat_app):
    manager = flat_app.execution
    request_id = "same-id"
    manager.reservation_ledger.reserve(request_id, request_id, D("2500"))
    manager.reservation_ledger.reserve("other", "other", D("4000"))

    decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    flat_app.market_loop._apply_position_sizing("BUY", decision, request_id)

    reservation = manager.reservation_ledger.get(request_id)
    assert reservation.amount == D("2500")
    assert reservation.status.value == "RESERVED"
    assert reservation.version == 1
    assert "amount" not in decision or decision["amount"] == 0
    assert "proposed_quote_allocation" not in decision


def test_replay_conflict_never_writes_a_proposed_allocation_onto_the_decision(flat_app):
    manager = flat_app.execution
    request_id = "same-id"
    manager.reservation_ledger.reserve(request_id, request_id, D("2500"))
    manager.reservation_ledger.reserve("other", "other", D("4000"))

    decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    flat_app.market_loop._apply_position_sizing("BUY", decision, request_id)

    assert decision["amount"] == 0
    assert "proposed_quote_allocation" not in decision


def test_replay_conflict_does_not_halt_the_runtime(flat_app):
    manager = flat_app.execution
    request_id = "same-id"
    manager.reservation_ledger.reserve(request_id, request_id, D("2500"))
    manager.reservation_ledger.reserve("other", "other", D("4000"))

    decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    flat_app.market_loop._apply_position_sizing("BUY", decision, request_id)

    assert manager.execution_halted is False
    assert manager.recovery_required is False
    assert manager._risk_admissions == {}


def test_replay_conflict_through_full_route_execution_is_refused_cleanly(flat_app):
    """The same conflict, driven through the real route_execution seam."""
    manager = flat_app.execution
    request_id = "BTCUSDT|open:conflict|BUY"
    manager.reservation_ledger.reserve(request_id, request_id, D("2500"))
    manager.reservation_ledger.reserve("other", "other", D("4000"))

    decision = {
        "symbol": "BTCUSDT", "action": "BUY", "price": 10, "confidence": 90.0,
        "risk": "MEDIUM", "metadata": {"candle_identity": "open:conflict"},
    }

    result = flat_app.market_loop.route_execution(decision=decision, market_state={})

    assert result["status"] == "REJECTED"
    assert result["reason"] == "SIZING_REPLAY_CONFLICT"
    assert manager.execution_halted is False
    assert manager.recovery_required is False
    assert request_id not in flat_app.market_loop.pending_execution_fingerprints


def test_reservation_ledger_collision_protection_is_unchanged(flat_app):
    """5C never weakens CapitalReservationLedger's own guard."""
    ledger = flat_app.execution.reservation_ledger
    ledger.reserve("x", "x", D("100"))

    with pytest.raises(ValueError):
        ledger.reserve("x", "x", D("200"))

    with pytest.raises(ValueError):
        ledger.reserve("x", "different-request", D("100"))


# ==========================================================================
# 5 — real MarketLoop, end to end
# ==========================================================================


def build_closed_candles(count: int = 200, *, epoch: int = 0) -> list[list[Any]]:
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
    def __init__(self, action: str, risk: str = "MEDIUM") -> None:
        self.action = action
        self.risk = risk

    def analyze_and_decide(self, symbol, market_data):
        return {
            "symbol": symbol, "action": self.action, "confidence": 90.0, "risk": self.risk,
            "strategy": "BLOCK5C_UPSTREAM_SIZING_AUTHORITY", "reason": "Sizing authority contract.",
        }


def execution_enabled_loop(app: AtlasApplication, action: str, *, risk: str = "MEDIUM",
                           epoch: int = 0) -> MarketLoop:
    loop = app.market_loop
    loop.brain = DecidingBrain(action, risk=risk)
    loop.market_feed = OfflineMarketFeed(epoch)
    loop.symbols = ["BTCUSDT"]
    assert loop.execution is app.execution
    pin_clock_to_feed(loop)
    return loop


def test_real_market_loop_buy_is_sized_and_settles_end_to_end(flat_app):
    """MarketLoop -> sizing -> ExecutionManager -> risk_check -> reservation ->
    paper execution -> settlement, driven through the real runtime path."""
    manager = flat_app.execution

    result = execution_enabled_loop(flat_app, "BUY").process_symbol("BTCUSDT")

    assert result["status"] == "PAPER_EXECUTED"
    sizing = result["metadata"]["sizing"]
    assert sizing["authority"] == "PositionSizingService"
    assert D(sizing["proposed_quote_allocation"]) == MEDIUM_PROPOSAL_ON_A_FLAT_BOOK

    approved = D(result["data"]["approved_quote_allocation"])
    assert approved == MEDIUM_PROPOSAL_ON_A_FLAT_BOOK
    assert approved > D("0")

    notional = D(result["filled_quote_notional"])
    fee = D(result["fee_amount"])
    assert notional + fee <= approved

    position = position_of(flat_app)
    assert D(position["base_quantity"]) == D(result["filled_base_quantity"])

    snapshot = flat_app.portfolio_foundation.snapshot()
    assert snapshot["cash"] == TOTAL_CAPITAL - notional - fee
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert manager.reservation_ledger.get(result["request_id"]).status.value == "COMMITTED"
    assert manager.execution_halted is False


def test_approved_quote_allocation_stays_none_until_risk_check_runs(flat_app):
    """Proves the ordering: sizing proposes; only risk_check may write approval."""
    manager = flat_app.execution
    decision = buy_decision(amount=0, metadata={})

    flat_app.market_loop._apply_position_sizing("BUY", decision, "b1")
    request = manager.build_request(decision)

    assert request.proposed_quote_allocation == MEDIUM_PROPOSAL_ON_A_FLAT_BOOK
    assert isinstance(request.proposed_quote_allocation, D)
    # `amount` is deliberately never written by sizing (Block 5C B1): it
    # stays the pre-5C compatibility mirror, untouched.
    assert request.amount == 0.0
    assert request.approved_quote_allocation is None

    admission = manager.risk_check(request)

    assert admission["approved"] is True
    assert request.approved_quote_allocation == MEDIUM_PROPOSAL_ON_A_FLAT_BOOK


def test_no_orphan_reservation_remains_after_successful_settlement(flat_app):
    execution_enabled_loop(flat_app, "BUY").process_symbol("BTCUSDT")

    manager = flat_app.execution
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert manager._risk_admissions == {}


def test_real_market_loop_sell_still_exits_a_held_position(holding_app):
    manager = holding_app.execution

    result = execution_enabled_loop(holding_app, "SELL").process_symbol("BTCUSDT")

    assert result["status"] == "PAPER_EXECUTED"
    assert manager.last_risk_decision["reason_code"] == "RISK_REDUCTION_APPROVED"
    assert D(result["filled_base_quantity"]) == D("10")
    assert position_of(holding_app) is None
    assert manager.reservation_ledger.active_reserved_capital() == D("0")


def test_no_sizer_runtime_remains_fail_closed_exactly_as_5b(flat_app):
    """The explicit opt-out: without a sizer, a real loop BUY still refuses unsized."""
    flat_app.market_loop.position_sizing_service = None
    manager = flat_app.execution

    result = execution_enabled_loop(flat_app, "BUY").process_symbol("BTCUSDT")

    assert result.get("status") != "PAPER_EXECUTED"
    assert result.get("reason") != "INVALID_FINANCIAL_INPUT"
    assert result.get("reason") == "UNSIZED_REQUEST_REJECTED"
    assert position_of(flat_app) is None
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert manager._risk_admissions == {}
    assert manager.execution_halted is False


def test_real_market_loop_writes_only_the_configured_state_root(tmp_path):
    app = application(tmp_path)
    app.execution.start()

    execution_enabled_loop(app, "BUY").process_symbol("BTCUSDT")

    state_dir = tmp_path / "state"
    assert (state_dir / EXECUTION_FINANCIAL_STATE_FILE).exists()
    assert (state_dir / PAPER_TRADE_BOOK_FILE).exists()
    assert (state_dir / CAPITAL_RESERVATION_STATE_FILE).exists()


# ==========================================================================
# 6 — risk-policy separation: a proposal is not an approval
# ==========================================================================


def test_sizer_now_bounds_its_own_proposal_by_the_bucket_exposure_ceiling():
    """Block 5C M1/M2 regression: the sizer no longer omits a RiskEngine limit.

    Before remediation, ``bucket_policy.exposure_ceiling_pct`` was one of the
    RiskEngine BUY limits the sizer's own ``min(...)`` never included, so it
    could propose an amount RiskEngine would permanently refuse. Both
    authorities now derive their capacity ceilings from the same
    ``derive_buy_capacity_limits`` helper, so the sizer's own proposal is
    already bound by this ceiling and RiskEngine approves it unchanged.
    """
    policy = RiskPolicy(
        total_capital=TOTAL_CAPITAL,
        buckets={
            RiskBucket.LOW: BucketPolicy(D("0.40"), D("0.60"), D("0.60")),
            RiskBucket.MEDIUM: BucketPolicy(D("0.25"), D("0.70"), D("0.01")),
            RiskBucket.HIGH: BucketPolicy(D("0.10"), D("0.80"), D("0.20")),
        },
    )
    sizer = PositionSizingService(policy)
    engine = RiskEngine(policy)

    proposal = sizer.propose(sizing_inputs(durable_free_quote_capital=TOTAL_CAPITAL))
    assert proposal.status is SizingStatus.PROPOSED
    # Bound by the 0.01 exposure ceiling (100), not by the 0.25 bucket
    # allocation percentage (2500) the pre-remediation sizer used alone.
    assert proposal.proposed_quote_allocation == D("100")

    decision = engine.evaluate(
        RiskRequest(
            symbol="BTCUSDT", action="BUY", confidence=D("0.9"),
            requested_quote_allocation=proposal.proposed_quote_allocation,
            execution_price=D("10"), risk_bucket="MEDIUM",
        ),
        flat_state(policy),
    )

    assert decision.status is RiskDecisionStatus.APPROVE
    assert decision.approved_allocation == proposal.proposed_quote_allocation


def test_riskengine_still_rejects_a_sizing_proposal_on_grounds_the_sizer_cannot_see():
    """RiskEngine enforces limits the sizer structurally has no input for.

    ``confidence`` is deliberately not a ``SizingInputs`` field (Owner
    Decision 1; see ``test_confidence_is_not_a_sizing_input``), so a
    proposal PositionSizingService considers fine can still be refused by
    RiskEngine on a ground the sizer has no way to evaluate. This proves the
    two authorities are genuinely independent - a proposal is never an
    approval - without relying on a shared-capacity gap the M1/M2
    remediation has since closed.
    """
    policy = RiskPolicy(total_capital=TOTAL_CAPITAL)
    sizer = PositionSizingService(policy)
    engine = RiskEngine(policy)

    proposal = sizer.propose(sizing_inputs(durable_free_quote_capital=TOTAL_CAPITAL))
    assert proposal.status is SizingStatus.PROPOSED
    assert proposal.proposed_quote_allocation == D("2500.00")

    decision = engine.evaluate(
        RiskRequest(
            symbol="BTCUSDT", action="BUY",
            confidence=D("0.10"),  # below both global and bucket minimums
            requested_quote_allocation=proposal.proposed_quote_allocation,
            execution_price=D("10"), risk_bucket="MEDIUM",
        ),
        flat_state(policy),
    )

    assert decision.status is RiskDecisionStatus.REJECT
    assert decision.reason_code == "CONFIDENCE_BELOW_POLICY"


def test_sizer_output_alone_never_authorizes_execution():
    proposal = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL)).propose(
        sizing_inputs()
    )
    assert proposal.status is SizingStatus.PROPOSED
    # A SizingProposal is not, and cannot be mistaken for, a RiskDecision.
    assert not hasattr(proposal, "approved")
    assert not hasattr(proposal, "status_code")


def test_critical_buy_stays_fail_closed_end_to_end_with_sizer_wired(flat_app):
    manager = flat_app.execution

    result = execution_enabled_loop(flat_app, "BUY", risk="CRITICAL").process_symbol("BTCUSDT")

    assert result.get("status") != "PAPER_EXECUTED"
    assert result.get("reason") == "UNSIZED_REQUEST_REJECTED"
    assert manager.reservation_ledger.active_reserved_capital() == D("0")
    assert manager.execution_halted is False


# ==========================================================================
# 7 — composition root wiring
# ==========================================================================


def test_application_constructs_exactly_one_sizing_service_sharing_the_risk_policy(flat_app):
    assert isinstance(flat_app.position_sizing_service, PositionSizingService)
    assert flat_app.position_sizing_service.policy is flat_app.risk_policy
    assert flat_app.execution.risk_engine.policy is flat_app.risk_policy


def test_market_loop_is_wired_to_the_application_sizing_service(flat_app):
    assert flat_app.market_loop.position_sizing_service is flat_app.position_sizing_service


# ==========================================================================
# 8 — Block 5C independent-review remediation (B1 / H1 / M1+M2 / M3)
# ==========================================================================
#
# The findings below were raised by an independent review of the original
# Block-5C implementation. Every test here pins the specific defect the
# review found, not just the surface-level fix.

DECIMAL_TAIL_CASH = D("7500.000000004106")
# 7500.000000004106 * 0.25, computed as an exact Decimal.
EXACT_DECIMAL_TAIL_PROPOSAL = D("1875.00000000102650")
# The corrupted value a Decimal -> float -> Decimal round trip through
# ExecutionRequest.amount would have produced instead (B1's defect).
CORRUPTED_FLOAT_ROUNDTRIP_PROPOSAL = D("1875.0000000010266")


# --- B1: exact Decimal proposal transport --------------------------------


def test_decimal_tail_proposal_is_computed_exactly():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))

    proposal = service.propose(sizing_inputs(durable_free_quote_capital=DECIMAL_TAIL_CASH))

    assert proposal.status is SizingStatus.PROPOSED
    assert proposal.proposed_quote_allocation == EXACT_DECIMAL_TAIL_PROPOSAL
    assert proposal.proposed_quote_allocation != CORRUPTED_FLOAT_ROUNDTRIP_PROPOSAL


def test_execution_request_rejects_a_float_proposed_quote_allocation():
    with pytest.raises(ValueError):
        ExecutionRequest("BTCUSDT", "BUY", 10, 0, proposed_quote_allocation=1875.5)


def test_execution_request_proposed_quote_allocation_round_trips_exactly():
    original = ExecutionRequest(
        "BTCUSDT", "BUY", 10, 0,
        proposed_quote_allocation=EXACT_DECIMAL_TAIL_PROPOSAL,
    )

    payload = original.to_dict()
    assert payload["proposed_quote_allocation"] == format(EXACT_DECIMAL_TAIL_PROPOSAL, "f")

    restored = ExecutionRequest.from_dict(payload)
    assert restored.proposed_quote_allocation == EXACT_DECIMAL_TAIL_PROPOSAL
    assert restored.proposed_quote_allocation != CORRUPTED_FLOAT_ROUNDTRIP_PROPOSAL


def test_legacy_unsized_request_with_no_exact_proposal_still_falls_back_to_5b_behavior(flat_app):
    """A request naming no exact proposal must behave exactly as Package 5B
    specified, even though a sizer is configured on the loop - this
    exercises risk_check's fallback directly, not the MarketLoop wiring."""
    manager = flat_app.execution
    request = ExecutionRequest("BTCUSDT", "BUY", 10, 0, confidence=90, risk="MEDIUM",
                               request_id="legacy-unsized")

    assert request.proposed_quote_allocation is None

    admission = manager.risk_check(request)

    assert admission["approved"] is False
    assert admission["reason"] == "UNSIZED_REQUEST_REJECTED"


def test_decimal_tail_proposal_reaches_risk_check_and_reservation_exactly(tmp_path):
    """Block 5C B1 mandatory regression.

    Drives the real MarketLoop -> ExecutionManager.build_request ->
    risk_check -> CapitalReservationLedger path with a realistic
    decimal-tail durable cash figure and proves the exact sizing Decimal
    survives every hop, never crossing the lossy ``ExecutionRequest.amount``
    float mirror.
    """
    app = application(tmp_path, cash=str(DECIMAL_TAIL_CASH))
    app.execution.start()
    manager = app.execution

    decision = buy_decision(amount=0, metadata={})
    app.market_loop._apply_position_sizing("BUY", decision, "decimal-tail-1")

    assert decision["proposed_quote_allocation"] == EXACT_DECIMAL_TAIL_PROPOSAL
    assert decision["amount"] == 0  # untouched: amount stays non-authoritative

    request = manager.build_request(decision)
    assert request.proposed_quote_allocation == EXACT_DECIMAL_TAIL_PROPOSAL
    assert request.proposed_quote_allocation != CORRUPTED_FLOAT_ROUNDTRIP_PROPOSAL

    admission = manager.risk_check(request)

    assert admission["approved"] is True
    assert request.approved_quote_allocation == EXACT_DECIMAL_TAIL_PROPOSAL

    reservation = manager.reservation_ledger.get(request.request_id)
    assert reservation.amount == EXACT_DECIMAL_TAIL_PROPOSAL
    assert reservation.amount != CORRUPTED_FLOAT_ROUNDTRIP_PROPOSAL


# --- REPLAY SAFETY: proved through the real path, not a hand-seeded amount


def test_decimal_tail_replay_with_unchanged_inputs_does_not_conflict(tmp_path):
    """Block 5C B1 + REPLAY SAFETY mandatory regression.

    The first reservation is created through the real sizing -> build_request
    -> risk_check path (not hand-seeded as a round number). A second sizing
    evaluation for the identical request identity, against the same durable
    state (nothing has settled yet, so cash has not moved), must recompute
    the identical exact proposal and must not be refused as
    SIZING_REPLAY_CONFLICT, and the existing reservation must be left as-is.
    """
    app = application(tmp_path, cash=str(DECIMAL_TAIL_CASH))
    app.execution.start()
    manager = app.execution
    request_id = "decimal-tail-replay"

    first_decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    app.market_loop._apply_position_sizing("BUY", first_decision, request_id)
    request = manager.build_request(first_decision)
    admission = manager.risk_check(request)
    assert admission["approved"] is True

    reservation_before = manager.reservation_ledger.get(request_id)
    assert reservation_before.amount == EXACT_DECIMAL_TAIL_PROPOSAL
    assert reservation_before.status.value == "RESERVED"

    replay_decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    refusal = app.market_loop._apply_position_sizing("BUY", replay_decision, request_id)

    assert refusal is None
    assert replay_decision["proposed_quote_allocation"] == EXACT_DECIMAL_TAIL_PROPOSAL
    assert (replay_decision["metadata"]["sizing"]["inputs_digest"]
            == first_decision["metadata"]["sizing"]["inputs_digest"])

    reservation_after = manager.reservation_ledger.get(request_id)
    assert reservation_after.amount == EXACT_DECIMAL_TAIL_PROPOSAL
    assert reservation_after.version == reservation_before.version  # untouched, not re-reserved
    assert manager.execution_halted is False
    assert manager.recovery_required is False


def test_decimal_tail_perturbed_input_is_detected_as_replay_conflict(tmp_path):
    """Block 5C REPLAY SAFETY mandatory regression: after the same real first
    admission as above, changing one sizing-effective input under the same
    request identity must be caught before risk_check / reservation, must
    leave the existing reservation untouched, and must not halt the runtime.
    """
    app = application(tmp_path, cash=str(DECIMAL_TAIL_CASH))
    app.execution.start()
    manager = app.execution
    request_id = "decimal-tail-conflict"

    first_decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    app.market_loop._apply_position_sizing("BUY", first_decision, request_id)
    request = manager.build_request(first_decision)
    admission = manager.risk_check(request)
    assert admission["approved"] is True

    reservation_before = manager.reservation_ledger.get(request_id)

    # Encumber unrelated capital, so a fresh proposal for the same identity
    # now prices differently against the same durable cash.
    manager.reservation_ledger.reserve("unrelated", "unrelated", D("1000"))

    replay_decision = buy_decision(amount=0, metadata={}, request_id=request_id)
    refusal = app.market_loop._apply_position_sizing("BUY", replay_decision, request_id)

    assert refusal is not None
    assert refusal["reason"] == "SIZING_REPLAY_CONFLICT"
    assert refusal["success"] is False

    reservation_after = manager.reservation_ledger.get(request_id)
    assert reservation_after.amount == reservation_before.amount
    assert reservation_after.version == reservation_before.version
    assert manager.execution_halted is False
    assert manager.recovery_required is False


# --- H1: complete inputs_digest -------------------------------------------


@pytest.mark.parametrize("mutate", [
    lambda p: RiskPolicy(total_capital=p.total_capital + D("1")),
    lambda p: RiskPolicy(total_capital=p.total_capital, max_position_pct=D("0.39")),
    lambda p: RiskPolicy(total_capital=p.total_capital, per_symbol_pct=D("0.39")),
    lambda p: RiskPolicy(total_capital=p.total_capital, concentration_pct=D("0.39")),
    lambda p: RiskPolicy(total_capital=p.total_capital, portfolio_exposure_pct=D("0.79")),
    lambda p: RiskPolicy(total_capital=p.total_capital, cash_reserve_pct=D("0.21")),
    lambda p: RiskPolicy(total_capital=p.total_capital, buckets={
        RiskBucket.LOW: p.buckets[RiskBucket.LOW],
        RiskBucket.MEDIUM: BucketPolicy(D("0.24"), D("0.70"), D("0.40")),
        RiskBucket.HIGH: p.buckets[RiskBucket.HIGH],
    }),
    lambda p: RiskPolicy(total_capital=p.total_capital, buckets={
        RiskBucket.LOW: p.buckets[RiskBucket.LOW],
        RiskBucket.MEDIUM: BucketPolicy(D("0.25"), D("0.70"), D("0.39")),
        RiskBucket.HIGH: p.buckets[RiskBucket.HIGH],
    }),
], ids=[
    "total_capital", "max_position_pct", "per_symbol_pct", "concentration_pct",
    "portfolio_exposure_pct", "cash_reserve_pct", "bucket_max_allocation_pct",
    "bucket_exposure_ceiling_pct",
])
def test_digest_changes_when_any_effective_capacity_input_changes(mutate):
    """Block 5C H1 mandatory regression: every resolved capacity term feeding
    ``min(...)`` is sealed into the digest, so a policy input that moves any
    one of them - even one that does not happen to win the min this time -
    is still detectable as a changed effective input."""
    base_policy = RiskPolicy(total_capital=TOTAL_CAPITAL)
    mutated_policy = mutate(base_policy)

    base = PositionSizingService(base_policy).propose(sizing_inputs())
    mutated = PositionSizingService(mutated_policy).propose(sizing_inputs())

    assert base.provenance["inputs_digest"] != mutated.provenance["inputs_digest"]


def test_digest_is_stable_for_the_same_effective_sizing_inputs():
    service = PositionSizingService(RiskPolicy(total_capital=TOTAL_CAPITAL))

    first = service.propose(sizing_inputs(durable_free_quote_capital=DECIMAL_TAIL_CASH))
    second = service.propose(sizing_inputs(durable_free_quote_capital=DECIMAL_TAIL_CASH))

    assert first.provenance["inputs_digest"] == second.provenance["inputs_digest"]
    assert first.proposed_quote_allocation == second.proposed_quote_allocation == EXACT_DECIMAL_TAIL_PROPOSAL


# --- M1 + M2: one shared risk-limit derivation -----------------------------


def test_cash_greater_than_nominal_total_capital_does_not_over_propose():
    """Block 5C M1/M2 mandatory regression.

    Durable free capital (12000) exceeding the nominal policy total_capital
    (10000) must not let the sizer propose more than the canonical bucket
    allocation limit RiskEngine itself enforces (2500 = 10000 * 0.25).
    Before the shared-derivation fix, the sizer's own candidate formula
    (durable_free_quote_capital * basis_pct = 3000) was never bounded by
    that canonical, total_capital-relative limit, so RiskEngine would refuse
    the proposal every time - a request the runtime could never admit.
    """
    policy = RiskPolicy(total_capital=TOTAL_CAPITAL)  # 10000
    sizer = PositionSizingService(policy)
    engine = RiskEngine(policy)

    proposal = sizer.propose(sizing_inputs(durable_free_quote_capital=D("12000")))

    assert proposal.status is SizingStatus.PROPOSED
    assert proposal.proposed_quote_allocation == D("2500")
    assert proposal.proposed_quote_allocation != D("3000")

    decision = engine.evaluate(
        RiskRequest(
            symbol="BTCUSDT", action="BUY", confidence=D("0.9"),
            requested_quote_allocation=proposal.proposed_quote_allocation,
            execution_price=D("10"), risk_bucket="MEDIUM",
        ),
        flat_state(policy),
    )

    assert decision.status is RiskDecisionStatus.APPROVE
    assert decision.approved_allocation == D("2500")


def test_sizer_and_engine_consume_the_identical_shared_limit_derivation():
    """Block 5C M1/M2: both authorities call the same function object, not
    two copies of the same formula."""
    import core.position_sizing as sizing_module
    import core.risk_engine as risk_engine_module

    assert sizing_module.derive_buy_capacity_limits is risk_engine_module.derive_buy_capacity_limits

    policy = RiskPolicy(total_capital=TOTAL_CAPITAL, per_symbol_pct=D("0.05"))
    bucket_policy = policy.buckets[RiskBucket.MEDIUM]
    limits = derive_buy_capacity_limits(
        policy, bucket_policy, symbol_exposure=D("0"), committed_quote=D("0"),
    )

    sizer = PositionSizingService(policy)
    proposal = sizer.propose(sizing_inputs())
    # per_symbol_pct=0.05 (500) is the tightest limit here, binding both the
    # sizer's own proposal and, independently, RiskEngine's own approval.
    assert proposal.proposed_quote_allocation == limits.per_symbol == D("500")

    engine = RiskEngine(policy)
    decision = engine.evaluate(
        RiskRequest(
            symbol="BTCUSDT", action="BUY", confidence=D("0.9"),
            requested_quote_allocation=proposal.proposed_quote_allocation,
            execution_price=D("10"), risk_bucket="MEDIUM",
        ),
        flat_state(policy),
    )

    assert decision.status is RiskDecisionStatus.APPROVE
    assert decision.approved_allocation == limits.per_symbol


def test_riskengine_evaluate_still_never_silently_caps_a_request_above_a_limit():
    """M1/M2 must not weaken the existing 'never silently cap' guarantee."""
    policy = RiskPolicy(total_capital=TOTAL_CAPITAL, per_symbol_pct=D("0.05"))
    engine = RiskEngine(policy)

    decision = engine.evaluate(
        RiskRequest(
            symbol="BTCUSDT", action="BUY", confidence=D("0.9"),
            requested_quote_allocation=D("501"),  # 1 unit above the 500 per-symbol limit
            execution_price=D("10"), risk_bucket="MEDIUM",
        ),
        flat_state(policy),
    )

    assert decision.status is RiskDecisionStatus.REJECT
    assert decision.reason_code == "REQUEST_EXCEEDS_RISK_LIMIT"
    assert decision.approved_allocation == D("0")


# --- M3: explicit L1 architecture assignment -------------------------------


def test_position_sizing_is_explicitly_assigned_l1_in_the_architecture_map():
    architecture_map = load_architecture_map()

    assert architecture_map["module_layers"]["core/position_sizing.py"] == "L1"

    explicit_rules = [
        rule for rule in architecture_map["layer_rules"]
        if rule["pattern"] == "core/position_sizing.py"
    ]
    assert len(explicit_rules) == 1
    assert explicit_rules[0]["layer"] == "L1"

    # first-match-wins: the explicit rule must be listed ahead of the
    # generic core/* -> L3 fallback, or the fallback would still win.
    patterns = [rule["pattern"] for rule in architecture_map["layer_rules"]]
    assert patterns.index("core/position_sizing.py") < patterns.index("core/*")


def test_forbidden_edges_would_reject_a_future_l2_or_l3_import_into_position_sizing():
    architecture_map = load_architecture_map()
    forbidden_pairs = {(rule["from"], rule["to"]) for rule in architecture_map["forbidden_edges"]}

    # core/position_sizing.py is classified L1 (asserted above); combined
    # with these two standing forbidden edges, an L2 or L3 import added to
    # it in the future is guaranteed to fail tests/architecture/test_forbidden_layer_imports.py.
    assert ("L1", "L2") in forbidden_pairs
    assert ("L1", "L3") in forbidden_pairs


# ==========================================================================
# 9 — Block 5C independent-review remediation (M-A)
# ==========================================================================
#
# M-A: a completed BUY, replayed under its own exact request identity after
# a process restart, reached PositionSizingService before ExecutionManager's
# own durable idempotency cache could answer it. Post-trade cash and
# exposure differ from whatever earned the original approval, so the
# recomputed proposal legitimately differed from the COMMITTED reservation
# and was misreported as SIZING_REPLAY_CONFLICT instead of the duplicate it
# actually is. The fix returns from ``_apply_position_sizing`` before any
# proposal is computed whenever ``request_id`` is already present in
# ``ExecutionManager.completed_request_results``.


def test_completed_replay_after_restart_uses_durable_cache_not_sizing(tmp_path):
    """Block 5C M-A mandatory regression.

    Run 1 executes a real BUY to completion through the real MarketLoop ->
    ExecutionManager path. Run 2 constructs a brand new ``AtlasApplication``
    over the *same* scratch state directory - a process restart - and
    replays the identical request identity through ``route_execution``.
    Neither ``AtlasApplication`` shares any in-memory state with the other:
    the completed-request cache the fix relies on is rehydrated from the
    durable ``ExecutionIdempotencyStore`` file on disk, not hand-seeded.
    """
    request_id = "BTCUSDT|open:ma-restart|BUY"
    state_dir = seed_state(tmp_path / "state", cash="10000")

    def buy_with_candle() -> dict[str, Any]:
        return {
            "symbol": "BTCUSDT", "action": "BUY", "price": 10, "confidence": 90.0,
            "risk": "MEDIUM", "metadata": {"candle_identity": "open:ma-restart"},
        }

    # --- run 1: a real, complete BUY --------------------------------------
    app_run1 = AtlasApplication(state_directory=state_dir)
    app_run1.execution.start()

    first_result = app_run1.market_loop.route_execution(
        decision=buy_with_candle(), market_state={}
    )

    assert first_result["status"] == "PAPER_EXECUTED"
    assert first_result["request_id"] == request_id
    assert first_result.get("idempotency", {}).get("duplicate", False) is False

    reservation = app_run1.execution.reservation_ledger.get(request_id)
    assert reservation.status.value == "COMMITTED"
    assert reservation.amount == MEDIUM_PROPOSAL_ON_A_FLAT_BOOK
    committed_amount = reservation.amount
    committed_version = reservation.version

    # --- run 2: a brand new AtlasApplication over the identical scratch
    # state directory - simulating a process restart - replaying the exact
    # same request identity. -------------------------------------------
    app_run2 = AtlasApplication(state_directory=state_dir)
    app_run2.execution.start()

    replay_decision = buy_with_candle()
    replay_result = app_run2.market_loop.route_execution(
        decision=replay_decision, market_state={}
    )

    # Durable cache-hit/duplicate semantics win: the restarted runtime
    # answers from ExecutionManager's own idempotency cache...
    assert replay_result["status"] == "PAPER_EXECUTED"
    assert replay_result["request_id"] == request_id
    assert replay_result.get("idempotency", {}).get("duplicate") is True
    assert replay_result.get("idempotency", {}).get("cache_hit") is True

    # ...never as a sizing conflict...
    assert replay_result.get("status") != "REJECTED"
    assert replay_result.get("reason") != "SIZING_REPLAY_CONFLICT"

    # ...and no proposal was even computed for the completed replay.
    assert "sizing" not in replay_decision["metadata"]

    # No new reservation; the existing COMMITTED reservation is untouched.
    reservation_after = app_run2.execution.reservation_ledger.get(request_id)
    assert reservation_after.amount == committed_amount
    assert reservation_after.version == committed_version
    assert reservation_after.status.value == "COMMITTED"

    # No halt, no recovery.
    assert app_run2.execution.execution_halted is False
    assert app_run2.execution.recovery_required is False
