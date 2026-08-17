"""Block-5A: the canonical RiskEngine is reachable from the real runtime.

Before this package the caller was the position authority. ``risk_check``
required a ``RiskState`` to arrive through ``market_state``, but the only
runtime caller - ``MarketLoop.route_execution`` - passes
``WorldAnalysisEngine.build_market_state()`` output, which is market data.
Every genuine runtime request therefore died at
``RISK_STATE_RESTORATION_FAILED`` before RiskEngine policy was consulted at
all, and a legitimate exit was refused as ``NON_RISK_REDUCING_SELL`` unless
the caller happened to set ``reduce_only`` itself.

Block-5A assembles the RiskState inside ExecutionManager from the financial
state Atlas already owns, and derives reduce-only intent from the held
position rather than from a caller flag. RiskEngine policy is unchanged: these
tests assert that its existing verdicts now actually arrive.

Financial state is deliberately not routed through MarketLoop or
WorldAnalysisEngine; the market path still carries market data only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from core.execution_models import ExecutionRequest, ExecutionResult
from core.execution_portfolio_foundation import FinancialStateStore
from core.market_loop import MarketLoop
from core.risk_engine import PositionExposure, RiskState
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState

POLICY_VERSION = "phase3-risk-v1"

# AtlasApplication derives its policy from CapitalAllocator.total_capital.
TOTAL_CAPITAL = D("10000")

# RiskPolicy.buckets[HIGH].max_allocation_pct is 0.10 of total capital.
HIGH_BUCKET_MAX = TOTAL_CAPITAL * D("0.10")


# --------------------------------------------------------------------------
# durable state seeding
#
# Every fixture writes into pytest's tmp_path. Nothing here may touch the
# operator's real runtime state.
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


def seed_state(
    state_dir,
    *,
    cash="10000",
    positions=(),
    pnl="0",
    peak="10000",
    equity="10000",
):
    """Seed the three durable authorities Block-5A derives RiskState from."""
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


def application(tmp_path, **seeding) -> AtlasApplication:
    state_dir = tmp_path / "state"
    seed_state(state_dir, **seeding)
    return AtlasApplication(state_directory=state_dir)


@pytest.fixture
def flat_app(tmp_path) -> AtlasApplication:
    """A ready runtime holding no positions."""
    return application(tmp_path)


@pytest.fixture
def holding_app(tmp_path) -> AtlasApplication:
    """A ready runtime whose durable book holds 10 BTCUSDT marked at 10."""
    return application(tmp_path, positions=[("BTCUSDT", "10", "10")])


# --------------------------------------------------------------------------
# request helpers
# --------------------------------------------------------------------------


def buy(*, symbol="BTCUSDT", amount=HIGH_BUCKET_MAX, risk="HIGH", confidence=90,
        request_id="b1") -> ExecutionRequest:
    return ExecutionRequest(
        symbol, "BUY", 10, str(amount), confidence=confidence, risk=risk,
        request_id=request_id,
    )


def sell(*, symbol="BTCUSDT", amount="100", risk="HIGH", confidence=90,
         request_id="s1", reduce_only=False) -> ExecutionRequest:
    return ExecutionRequest(
        symbol, "SELL", 10, str(amount), confidence=confidence, risk=risk,
        request_id=request_id, reduce_only=reduce_only,
    )


# --------------------------------------------------------------------------
# A — a genuine runtime BUY reaches RiskEngine
# --------------------------------------------------------------------------


def test_runtime_buy_reaches_risk_engine_without_caller_state(flat_app):
    """The runtime shape: a market-data mapping, no RiskState anywhere."""
    market_state = {"symbol": "BTCUSDT", "price": 10.0, "trend": "UP"}

    result = flat_app.execution.risk_check(buy(), market_state)

    assert result["approved"] is True
    assert result["reason"] == "RISK_APPROVED"
    assert flat_app.execution.last_risk_decision["reason_code"] == "RISK_APPROVED"
    assert flat_app.execution.last_risk_decision["policy_version"] == POLICY_VERSION


def test_runtime_buy_needs_no_market_state_at_all(flat_app):
    result = flat_app.execution.risk_check(buy())

    assert result["approved"] is True
    assert result["reason"] == "RISK_APPROVED"


def test_derived_state_reflects_the_durable_book(holding_app):
    state = holding_app.execution._derive_risk_state()

    assert state.state_ready is True
    assert state.policy_version == POLICY_VERSION
    assert [position.symbol for position in state.positions] == ["BTCUSDT"]
    assert state.positions[0].base_quantity == D("10")
    assert state.positions[0].execution_price == D("10")
    assert state.committed_quote == D("100")


def test_unreadable_durable_book_fails_closed_and_is_never_replaced(tmp_path):
    """A configured but corrupt book must not fall back to caller positions."""
    state_dir = tmp_path / "state"
    seed_state(state_dir)
    (state_dir / EXECUTION_FINANCIAL_STATE_FILE).write_text("{ not json", encoding="utf-8")
    app = AtlasApplication(state_directory=state_dir)

    assert app.portfolio_foundation.ready is False

    caller_state = RiskState(
        (), D("0"), D("0"), D("10000"), D("10000"), True,
        datetime.now(UTC).date().isoformat(), POLICY_VERSION,
    )
    result = app.execution.risk_check(buy(), caller_state)

    assert result["approved"] is False
    assert result["reason"] == "RISK_STATE_RESTORATION_FAILED"
    assert result["status"] == "BLOCK_RECOVERY_REQUIRED"
    assert app.execution.reservation_ledger.get("b1") is None
    assert app.execution._risk_admissions == {}


# --------------------------------------------------------------------------
# B — CRITICAL new risk still fails closed
# --------------------------------------------------------------------------


def test_critical_buy_still_fails_closed(flat_app):
    result = flat_app.execution.risk_check(buy(risk="CRITICAL"))

    assert result["approved"] is False
    assert result["reason"] == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert result["details"]["approved_allocation"] == "0"
    assert flat_app.execution.reservation_ledger.get("b1") is None
    assert flat_app.execution._risk_admissions == {}


# --------------------------------------------------------------------------
# C — max-position enforcement is now reachable
# --------------------------------------------------------------------------


def test_max_positions_is_reachable_through_derived_state(tmp_path):
    """Five held positions is RiskPolicy.max_positions; the sixth is refused.

    This verdict was unreachable from the runtime before Block-5A, because no
    caller ever supplied the position count RiskEngine counts.
    """
    app = application(
        tmp_path,
        positions=[(f"SYM{index}USDT", "1", "10") for index in range(5)],
    )

    assert len(app.execution._derive_risk_state().positions) == 5

    result = app.execution.risk_check(buy(symbol="BTCUSDT", amount="100"))

    assert result["approved"] is False
    assert result["reason"] == "MAX_POSITIONS_REACHED"
    assert app.execution.reservation_ledger.get("b1") is None
    assert app.execution._risk_admissions == {}


# --------------------------------------------------------------------------
# D — averaging up stays forbidden
# --------------------------------------------------------------------------


def test_buy_against_an_open_position_is_a_duplicate(holding_app):
    result = holding_app.execution.risk_check(buy(amount="100"))

    assert result["approved"] is False
    assert result["reason"] == "DUPLICATE_OPEN_POSITION"
    assert holding_app.execution.reservation_ledger.get("b1") is None
    assert holding_app.execution._risk_admissions == {}


def test_buy_cannot_waive_its_reservation_with_a_reduce_only_flag(flat_app):
    """A BUY can never reduce exposure, so the flag is always derived False."""
    request = buy(amount="100")
    request.reduce_only = True

    result = flat_app.execution.risk_check(request)

    assert result["approved"] is True
    assert request.reduce_only is False

    reservation = flat_app.execution.reservation_ledger.get("b1")
    assert reservation is not None
    assert reservation.amount == D("100")


# --------------------------------------------------------------------------
# E — a held position derives reduce-only
# --------------------------------------------------------------------------


def test_sell_with_a_held_position_derives_reduce_only(holding_app):
    request = sell(amount="100")
    assert request.reduce_only is False

    result = holding_app.execution.risk_check(request)

    assert result["approved"] is True
    assert request.reduce_only is True
    assert holding_app.execution.last_risk_decision["reason_code"] == (
        "RISK_REDUCTION_APPROVED"
    )
    # A reduction consumes no new capital.
    assert holding_app.execution.reservation_ledger.get("s1") is None
    assert "s1" in holding_app.execution._risk_admissions


def test_partial_reduction_is_admitted_as_risk_reducing(holding_app):
    """Admission only. Partial-close execution fidelity belongs to 5B."""
    request = sell(amount="40")

    result = holding_app.execution.risk_check(request)

    assert result["approved"] is True
    assert request.reduce_only is True
    assert holding_app.execution.last_risk_decision["reason_code"] == (
        "RISK_REDUCTION_APPROVED"
    )


# --------------------------------------------------------------------------
# F — no held position is not a reduction
# --------------------------------------------------------------------------


def test_sell_without_a_held_position_is_not_reduce_only(flat_app):
    request = sell(amount="100")

    result = flat_app.execution.risk_check(request)

    assert result["approved"] is False
    assert result["reason"] == "NON_RISK_REDUCING_SELL"
    assert request.reduce_only is False
    assert flat_app.execution._risk_admissions == {}


def test_a_caller_flag_cannot_manufacture_a_reduction(flat_app):
    """The derived result, not the caller flag, is authoritative."""
    request = sell(amount="100", reduce_only=True)

    result = flat_app.execution.risk_check(request)

    assert result["approved"] is False
    assert result["reason"] == "NON_RISK_REDUCING_SELL"
    assert request.reduce_only is False


def test_a_reduction_of_a_different_symbol_is_not_a_reduction(holding_app):
    request = sell(symbol="ETHUSDT", amount="100", reduce_only=True)

    result = holding_app.execution.risk_check(request)

    assert result["approved"] is False
    assert result["reason"] == "NON_RISK_REDUCING_SELL"
    assert request.reduce_only is False


# --------------------------------------------------------------------------
# G — an over-sized reduction fails closed
# --------------------------------------------------------------------------


def test_sell_larger_than_the_held_exposure_fails_closed(holding_app):
    """Derived as a reduction attempt, then refused on its size by policy.

    It is deliberately not silently downsized and not re-read as new risk.
    """
    request = sell(amount="1000")

    result = holding_app.execution.risk_check(request)

    assert result["approved"] is False
    assert result["reason"] == "INVALID_RISK_REDUCTION"
    assert request.reduce_only is True
    assert holding_app.execution.reservation_ledger.get("s1") is None
    assert holding_app.execution._risk_admissions == {}


# --------------------------------------------------------------------------
# H — degraded conditions still permit only valid reductions
# --------------------------------------------------------------------------


def test_drawdown_halt_blocks_new_risk_but_not_a_valid_exit(tmp_path):
    app = application(
        tmp_path,
        positions=[("BTCUSDT", "10", "10")],
        peak="10000",
        equity="8000",
    )

    blocked = app.execution.risk_check(buy(symbol="ETHUSDT", amount="100"))
    assert blocked["approved"] is False
    assert blocked["reason"] == "DRAWDOWN_HALT_NEW_RISK"

    exit_request = sell(amount="100")
    allowed = app.execution.risk_check(exit_request)

    assert allowed["approved"] is True
    assert exit_request.reduce_only is True
    assert app.execution.last_risk_decision["reason_code"] == "RISK_REDUCTION_APPROVED"


def test_daily_loss_limit_blocks_new_risk_but_not_a_valid_exit(tmp_path):
    app = application(
        tmp_path,
        positions=[("BTCUSDT", "10", "10")],
        pnl="-600",
    )

    blocked = app.execution.risk_check(buy(symbol="ETHUSDT", amount="100"))
    assert blocked["approved"] is False
    assert blocked["reason"] == "DAILY_LOSS_LIMIT_BREACHED"

    exit_request = sell(amount="100")
    allowed = app.execution.risk_check(exit_request)

    assert allowed["approved"] is True
    assert exit_request.reduce_only is True


def test_critical_risk_still_permits_a_valid_exit(holding_app):
    exit_request = sell(amount="100", risk="CRITICAL")

    result = holding_app.execution.risk_check(exit_request)

    assert result["approved"] is True
    assert exit_request.reduce_only is True
    assert holding_app.execution.last_risk_decision["reason_code"] == (
        "RISK_REDUCTION_APPROVED"
    )


def test_degraded_conditions_do_not_permit_an_oversized_exit(tmp_path):
    """Degradation relaxes nothing: the reduction must still be genuine."""
    app = application(
        tmp_path,
        positions=[("BTCUSDT", "10", "10")],
        peak="10000",
        equity="8000",
    )

    result = app.execution.risk_check(sell(amount="1000"))

    assert result["approved"] is False
    assert result["reason"] == "INVALID_RISK_REDUCTION"


# --------------------------------------------------------------------------
# I — unsupported risk stays unsupported
# --------------------------------------------------------------------------


@pytest.mark.parametrize("risk", ["EXTREME", "VERY_HIGH", "SEVERE"])
def test_unsupported_risk_is_never_resolved_to_medium(flat_app, risk):
    result = flat_app.execution.risk_check(buy(risk=risk, amount="100"))

    assert result["approved"] is False
    assert result["reason"] == "UNSUPPORTED_RISK_LEVEL"
    assert result["details"]["approved_allocation"] == "0"
    assert flat_app.execution._risk_admissions == {}


def test_unsupported_risk_still_permits_a_valid_exit(holding_app):
    exit_request = sell(amount="100", risk="EXTREME")

    result = holding_app.execution.risk_check(exit_request)

    assert result["approved"] is True
    assert exit_request.reduce_only is True


# --------------------------------------------------------------------------
# the durable POSITION_NOT_FOUND defence survives below admission
# --------------------------------------------------------------------------


def test_durable_sell_defence_still_refuses_an_absent_position(flat_app):
    """Admission can no longer deliver a phantom position, but the durable
    layer keeps its own check rather than trusting the caller above it.

    This calls ``_execute_paper_sell`` directly, below where ``execute()``
    computes ``commit_outcome`` from the side-effect marker, so the durable
    NOT_COMMITTED contract is pinned here at its source: the request must
    never be recorded as having crossed the side-effect boundary.
    """
    request = sell(amount="100")
    result = ExecutionResult(success=True, status="PAPER_EXECUTED")
    result.filled_price = 10

    flat_app.execution._execute_paper_sell(
        request=request,
        result=result,
    )

    assert result.success is False
    assert result.error_code == "POSITION_NOT_FOUND"
    assert request.request_id not in flat_app.execution._execution_side_effect_ids


# --------------------------------------------------------------------------
# J — the real, execution-enabled MarketLoop path
# --------------------------------------------------------------------------


def build_closed_candles(count: int = 200) -> list[list[Any]]:
    """Historical 1m rows, long closed by any realistic processing cutoff."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[list[Any]] = []

    for index in range(count):
        open_time = start + timedelta(minutes=index)
        open_ms = int(open_time.timestamp() * 1000)
        base = 60_000.0 + (index * 4.0)
        volume = 10.0 + (index * 0.05)

        rows.append([
            open_ms,
            f"{base:.2f}",
            f"{base + 35.0:.2f}",
            f"{base - 25.0:.2f}",
            f"{base + 12.0:.2f}",
            f"{volume:.5f}",
            open_ms + 59_999,
            "0.0",
            0,
            f"{volume * 0.4:.5f}",
            f"{(base + 12.0) * volume * 0.4:.8f}",
            "0",
        ])

    return rows


class OfflineMarketFeed:
    """Offline candle source. No Binance connection is ever opened."""

    def candles(self, symbol, interval="1m", limit=500):
        return build_closed_candles(limit)


class DecidingBrain:
    """Emits one fixed decision so the loop's own plumbing is what is tested."""

    def __init__(self, action: str, *, amount: float) -> None:
        self.action = action
        self.amount = amount
        self.calls: list[str] = []

    def analyze_and_decide(self, symbol, market_data):
        self.calls.append(symbol)
        return {
            "symbol": symbol,
            "action": self.action,
            "amount": self.amount,
            "confidence": 90.0,
            "risk": "HIGH",
            "strategy": "BLOCK5A_RISK_STATE_PLUMBING",
            "reason": "Offline runtime plumbing contract.",
        }


def execution_enabled_loop(app: AtlasApplication, brain: DecidingBrain) -> MarketLoop:
    """The composed MarketLoop, driven offline against the real ExecutionManager.

    The pre-5A MarketLoop tests all ran with ``execution=None``, which is why
    no test noticed that every real execution died at
    RISK_STATE_RESTORATION_FAILED.
    """
    loop = app.market_loop
    loop.brain = brain
    loop.market_feed = OfflineMarketFeed()
    loop.symbols = ["BTCUSDT"]
    assert loop.execution is app.execution
    return loop


def attach_allocation(loop: MarketLoop, amount: float) -> None:
    """Attach a quote allocation to the loop's normalized decision.

    ``DecisionAdapter.normalize()`` drops ``amount``, and ``build_request``
    then defaults it to ``0.0``. These 5A tests pin the *plumbing* - that the
    request reaches RiskEngine and is judged on its merits - so they state the
    allocation explicitly rather than depending on how it gets sized.

    Package 5B refuses an unsized new-risk request outright rather than
    sizing it, so an explicit amount here is what lets these plumbing tests
    reach RiskEngine at all - and it also proves 5B never overwrites caller
    intent. ``test_market_loop_unsized_buy_fails_closed_under_5b`` covers the
    unsized path, so this helper cannot hide it.
    """
    real_normalize = loop.normalize_decision

    def sized(**kwargs):
        decision = real_normalize(**kwargs)
        if isinstance(decision, dict):
            decision["amount"] = amount
        return decision

    loop.normalize_decision = sized


def test_market_loop_buy_reaches_risk_engine(flat_app):
    """5A's core claim: a genuine loop decision is judged by RiskEngine.

    Whatever verdict follows is policy. What must no longer happen is the
    request dying before RiskEngine is consulted at all.
    """
    flat_app.execution.start()
    brain = DecidingBrain("BUY", amount=float(HIGH_BUCKET_MAX))
    loop = execution_enabled_loop(flat_app, brain)
    attach_allocation(loop, float(HIGH_BUCKET_MAX))

    result = loop.process_symbol("BTCUSDT")

    assert brain.calls == ["BTCUSDT"]
    assert result is not None
    assert result.get("reason") != "RISK_STATE_RESTORATION_FAILED"
    assert flat_app.execution.last_risk_decision is not None
    assert flat_app.execution.last_risk_decision["policy_version"] == POLICY_VERSION


def test_market_loop_unsized_buy_fails_closed_under_5b(flat_app):
    """The 5A blocker, now visible rather than fatal.

    ``DecisionAdapter.normalize()`` still drops ``amount``, so the loop still
    hands ``build_request`` a zero allocation - the plumbing gap 5A exposed is
    genuinely still open upstream.

    Package 5B does not close it by inventing a size. It refuses the request
    on its own reason code, so the gap is reported instead of being papered
    over with the largest allocation policy would permit. What must no longer
    happen is the old symptom: the request dying as malformed input.
    """
    flat_app.execution.start()
    loop = execution_enabled_loop(
        flat_app, DecidingBrain("BUY", amount=float(HIGH_BUCKET_MAX))
    )

    decision = loop.normalize_decision(
        raw_decision={"action": "BUY", "confidence": 90, "risk_level": "MEDIUM"},
        symbol="BTCUSDT", price=10.0, market_data={"symbol": "BTCUSDT", "price": 10.0},
    )
    assert "amount" not in decision
    assert flat_app.execution.build_request(decision).amount == 0.0

    result = loop.process_symbol("BTCUSDT")

    assert result.get("status") != "PAPER_EXECUTED"
    assert result.get("reason") == "UNSIZED_REQUEST_REJECTED"
    assert result.get("reason") != "INVALID_FINANCIAL_INPUT"
    assert flat_app.portfolio_foundation.snapshot()["positions"] == {}
    assert flat_app.execution.reservation_ledger.active_reserved_capital() == D("0")


def test_market_loop_buy_executes_once_the_decision_is_sized(flat_app):
    flat_app.execution.start()
    brain = DecidingBrain("BUY", amount=float(HIGH_BUCKET_MAX))
    loop = execution_enabled_loop(flat_app, brain)
    attach_allocation(loop, float(HIGH_BUCKET_MAX))

    result = loop.process_symbol("BTCUSDT")

    assert result["status"] == "PAPER_EXECUTED"
    assert flat_app.execution.last_risk_decision["reason_code"] == "RISK_APPROVED"
    assert "BTCUSDT" in flat_app.portfolio_foundation.snapshot()["positions"]


def test_market_loop_never_carries_financial_state(flat_app):
    """MarketLoop hands ExecutionManager market data, and nothing more.

    RiskState assembly stays inside ExecutionManager: the market path must not
    become a financial-state channel.
    """
    flat_app.execution.start()
    loop = execution_enabled_loop(
        flat_app, DecidingBrain("BUY", amount=float(HIGH_BUCKET_MAX))
    )

    seen: list[Any] = []
    real_risk_check = flat_app.execution.risk_check

    def recording_risk_check(request, market_state=None):
        seen.append(market_state)
        return real_risk_check(request, market_state)

    flat_app.execution.risk_check = recording_risk_check

    loop.process_symbol("BTCUSDT")

    assert len(seen) == 1
    market_state = seen[0]
    assert not isinstance(market_state, RiskState)
    if isinstance(market_state, dict):
        assert "risk_state" not in market_state
        assert not any(
            isinstance(value, (RiskState, PositionExposure))
            for value in market_state.values()
        )


def test_market_loop_exit_derives_reduce_only_from_the_durable_book(holding_app):
    """A runtime SELL of a held position is admitted as a reduction.

    The brain emits no ``reduce_only``; the held position is what makes this a
    reduction, which is exactly the pre-5A failure.
    """
    holding_app.execution.start()
    loop = execution_enabled_loop(holding_app, DecidingBrain("SELL", amount=100.0))
    attach_allocation(loop, 100.0)

    result = loop.process_symbol("BTCUSDT")

    assert result is not None
    assert result.get("reason") != "NON_RISK_REDUCING_SELL"
    assert holding_app.execution.last_risk_decision["reason_code"] == (
        "RISK_REDUCTION_APPROVED"
    )


def test_market_loop_stays_paper_and_live_is_not_activated(flat_app):
    flat_app.execution.start()
    loop = execution_enabled_loop(
        flat_app, DecidingBrain("BUY", amount=float(HIGH_BUCKET_MAX))
    )

    loop.process_symbol("BTCUSDT")

    assert flat_app.execution.mode == ExecutionManager.MODE_PAPER
    assert flat_app.execution.live_execution_enabled is False
