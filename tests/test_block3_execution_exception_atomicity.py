"""Block-3 Package-1 M-A: post-reservation execution exception atomicity.

Block-2's final audit reproduced an execution pipeline exception raised after
canonical risk approval had already created a capital reservation and a risk
admission. The generic handler returned FAILED and let the runtime continue
while the reservation stayed RESERVED, the admission stayed recorded, and the
transaction journal stayed PREPARED. Nothing halted until the *next* request
tripped unresolved-journal detection, so one reservation survived each cycle.

These tests run the real AtlasApplication composition root in PAPER mode
against an isolated durable-state directory and prove the replacement
contract: an interrupted execution is classified by whether it crossed the
paper side-effect boundary, and neither classification can leave RESERVED
capital, a stale admission, and a running runtime behind together.

The boundary is PaperTrader.open_trade()/close_trade(), which persist their
own durable book (paper_trades.json). Before it, nothing external can have
happened and capital is released. After it, this manager cannot prove the
outcome either way, so capital is marked INDETERMINATE and the runtime halts
for operator recovery rather than being released as if nothing happened.

No risk bucket, allocation percentage, confidence threshold, exposure
ceiling, or sizing formula is exercised or changed here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.application import AtlasApplication
from core.capital_reservation import ReservationStatus
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.execution_transaction_journal import CommitOutcome
from core.risk_engine import PositionExposure, RiskState

from tests.test_block2_risk_service_composition_wiring import (
    POLICY_VERSION,
    DenyingPositionController,
    high_bucket_allocation,
    seed_valid_state,
)


D = Decimal


# --------------------------------------------------------------------------
# runtime helpers
# --------------------------------------------------------------------------


@pytest.fixture
def running_app(tmp_path) -> AtlasApplication:
    """A started PAPER runtime with valid durable state and no halt."""
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = AtlasApplication(state_directory=state_dir)
    app.execution.start()

    assert app.execution.execution_halted is False
    assert app.execution.recovery_required is False

    return app


def risk_state_with(*positions) -> RiskState:
    return RiskState(
        tuple(positions),
        sum((item.quote_exposure for item in positions), D("0")),
        D("0"),
        D("10000"),
        D("10000"),
        True,
        datetime.now(UTC).date().isoformat(),
        POLICY_VERSION,
    )


def risk_state() -> RiskState:
    return risk_state_with()


def buy_decision(app: AtlasApplication, *, request_id: str = "r1") -> dict:
    return ExecutionRequest(
        "BTCUSDT",
        "BUY",
        10,
        str(high_bucket_allocation(app)),
        confidence=90,
        risk="HIGH",
        request_id=request_id,
    ).to_dict()


def execute(app: AtlasApplication, *, request_id: str = "r1") -> dict:
    return app.execution.execute(buy_decision(app, request_id=request_id), risk_state())


def journal_state(app: AtlasApplication, request_id: str) -> str | None:
    entry = app.execution.transaction_journal.entries.get(request_id)
    return None if entry is None else entry.get("state")


def reservation_status(app: AtlasApplication, request_id: str) -> str | None:
    reservation = app.execution.reservation_ledger.get(request_id)
    return None if reservation is None else reservation.status.value


# --------------------------------------------------------------------------
# failure injection at known points of the real paper path
# --------------------------------------------------------------------------


def break_after_side_effect(app: AtlasApplication) -> None:
    """Raise after PaperTrader has already persisted the opened trade.

    ``_execute_paper_buy`` reads the durable portfolio snapshot to resolve the
    position identity only after ``_paper_open_trade`` has returned, so a
    failure there reproduces an interruption on the far side of the boundary.

    Block-5A also reads that snapshot to derive the canonical RiskState, which
    happens during ``risk_check`` and therefore *before* any component is
    touched. The injection is scoped to reads taken once the side-effect
    boundary has actually been crossed, so it keeps reproducing the post-side
    -effect interruption instead of degenerating into an admission refusal.
    """
    durable_snapshot = app.execution.portfolio_foundation.snapshot

    def failing_snapshot(*args, **kwargs):
        if app.execution._execution_side_effect_ids:
            raise RuntimeError("durable snapshot read failed")
        return durable_snapshot(*args, **kwargs)

    app.execution.portfolio_foundation.snapshot = failing_snapshot


def break_before_side_effect(app: AtlasApplication) -> None:
    """Raise before PaperTrader is reached.

    ``allocate_capital`` is the first step of ``_execute_paper_buy`` and runs
    before any component mutation, so this reproduces an interruption on the
    near side of the boundary.
    """

    def failing_allocation(request):
        raise RuntimeError("allocation engine failed")

    app.execution.allocate_capital = failing_allocation


# --------------------------------------------------------------------------
# T1 — paper execution exception after the side-effect boundary
# --------------------------------------------------------------------------


def test_exception_after_paper_side_effect_leaves_no_stale_admission(running_app):
    break_after_side_effect(running_app)

    execute(running_app)

    assert "r1" not in running_app.execution._risk_admissions
    assert running_app.execution._risk_admissions == {}


def test_exception_after_paper_side_effect_marks_capital_indeterminate(running_app):
    break_after_side_effect(running_app)

    execute(running_app)

    # The paper book was already mutated, so releasing the capital would
    # assert an outcome this runtime cannot prove.
    assert reservation_status(running_app, "r1") == ReservationStatus.INDETERMINATE.value


def test_exception_after_paper_side_effect_halts_the_runtime(running_app):
    break_after_side_effect(running_app)

    execute(running_app)

    assert running_app.execution.execution_halted is True
    assert running_app.execution.recovery_required is True
    assert running_app.execution.halt_reason == "EXECUTION_INTERRUPTED_AFTER_SIDE_EFFECT"


def test_exception_after_paper_side_effect_resolves_the_journal_as_unknown(running_app):
    break_after_side_effect(running_app)

    execute(running_app)

    assert journal_state(running_app, "r1") == (
        CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    )


def test_exception_after_paper_side_effect_returns_an_uncertain_result(running_app):
    break_after_side_effect(running_app)

    result = execute(running_app)

    assert result["success"] is False
    assert result["status"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert result["commit_outcome"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert result["recovery_required"] is True
    # The original failure reason is preserved rather than replaced.
    assert result["error_code"] == "EXECUTION_PIPELINE_EXCEPTION"
    assert result["error_details"]["error"] == "durable snapshot read failed"
    assert result["error_details"]["type"] == "RuntimeError"


def test_interrupted_execution_never_reports_failed_while_running(running_app):
    """The exact Block-2 M-A combination must be unreachable."""
    break_after_side_effect(running_app)

    result = execute(running_app)

    forbidden = (
        result["status"] in ExecutionManager.FAILURE_STATUSES
        and reservation_status(running_app, "r1") == ReservationStatus.RESERVED.value
        and "r1" in running_app.execution._risk_admissions
        and running_app.execution.execution_halted is False
    )
    assert forbidden is False

    # No terminal path may leave the journal unresolved-but-unnoticed.
    assert journal_state(running_app, "r1") != "PREPARED"


def test_interrupted_execution_does_not_retain_a_pending_claim(running_app):
    break_after_side_effect(running_app)

    execute(running_app)

    assert "r1" not in running_app.execution.pending_request_ids


# --------------------------------------------------------------------------
# T2 — repeated exceptions do not accumulate silent RESERVED capital
# --------------------------------------------------------------------------


def test_every_interrupted_cycle_ends_in_the_same_deterministic_state(tmp_path):
    """An interrupted execution is classified identically on every run."""
    for index in range(3):
        state_dir = tmp_path / f"cycle{index}"
        seed_valid_state(state_dir)
        app = AtlasApplication(state_directory=state_dir)
        app.execution.start()
        break_after_side_effect(app)

        execute(app, request_id=f"r{index}")

        # Never silently RESERVED, never a stale admission, never running on.
        assert reservation_status(app, f"r{index}") == (
            ReservationStatus.INDETERMINATE.value
        )
        assert journal_state(app, f"r{index}") == (
            CommitOutcome.COMMIT_STATUS_UNKNOWN.value
        )
        assert app.execution.execution_halted is True
        assert app.execution._risk_admissions == {}


def test_repeated_interrupted_executions_do_not_accumulate_reserved_capital(tmp_path):
    """Restarting onto unresolved state must not add a second reservation.

    Before this package one stale RESERVED reservation survived each halt
    cycle. Now the first interruption resolves into a single INDETERMINATE
    reservation and halts, and every restart against that unresolved durable
    state refuses new risk instead of reserving again.
    """
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)

    first = AtlasApplication(state_directory=state_dir)
    first.execution.start()
    break_after_side_effect(first)
    execute(first, request_id="r0")

    reserved_after_interruption = (
        first.execution.reservation_ledger.active_reserved_capital()
    )

    for index in range(1, 4):
        restarted = AtlasApplication(state_directory=state_dir)
        restarted.execution.start()
        break_after_side_effect(restarted)

        result = execute(restarted, request_id=f"r{index}")

        assert result["status"] == "RECOVERY_REQUIRED"
        assert reservation_status(restarted, f"r{index}") is None
        assert restarted.execution._risk_admissions == {}
        assert (
            restarted.execution.reservation_ledger.active_reserved_capital()
            == reserved_after_interruption
        )


def test_a_halted_runtime_admits_no_further_risk(running_app):
    break_after_side_effect(running_app)
    execute(running_app, request_id="r1")

    reserved_after_halt = running_app.execution.reservation_ledger.active_reserved_capital()

    second = execute(running_app, request_id="r2")

    assert second["status"] == "RECOVERY_REQUIRED"
    assert reservation_status(running_app, "r2") is None
    assert "r2" not in running_app.execution._risk_admissions
    assert (
        running_app.execution.reservation_ledger.active_reserved_capital()
        == reserved_after_halt
    )


# --------------------------------------------------------------------------
# T3 — successful paper execution is unchanged
# --------------------------------------------------------------------------


def test_successful_paper_execution_is_unchanged(running_app):
    result = execute(running_app)

    assert result["success"] is True
    assert result["status"] == "PAPER_EXECUTED"
    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value


def test_successful_paper_execution_commits_reservation_and_clears_admission(running_app):
    execute(running_app)

    assert reservation_status(running_app, "r1") == ReservationStatus.COMMITTED.value
    assert running_app.execution._risk_admissions == {}
    assert journal_state(running_app, "r1") == CommitOutcome.COMMITTED.value
    assert running_app.execution.execution_halted is False
    assert running_app.execution.recovery_required is False


def test_successful_paper_execution_leaves_no_side_effect_marker(running_app):
    execute(running_app)

    assert running_app.execution._execution_side_effect_ids == set()


# --------------------------------------------------------------------------
# T4 — M-1 stays closed: pre-execution rejection reserves nothing
# --------------------------------------------------------------------------


def test_position_limit_rejection_still_reserves_nothing(running_app):
    running_app.execution.position_controller = DenyingPositionController()
    before = running_app.execution.reservation_ledger.active_reserved_capital()

    result = execute(running_app)

    assert result["reason"] == "POSITION_LIMIT"
    assert reservation_status(running_app, "r1") is None
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.reservation_ledger.active_reserved_capital() == before
    assert running_app.execution.execution_halted is False


def test_canonical_risk_rejection_still_reserves_nothing(running_app):
    over_limit = high_bucket_allocation(running_app) * D("5")
    decision = ExecutionRequest(
        "BTCUSDT",
        "BUY",
        10,
        str(over_limit),
        confidence=90,
        risk="HIGH",
        request_id="r1",
    ).to_dict()

    result = running_app.execution.execute(decision, risk_state())

    assert result["success"] is False
    assert reservation_status(running_app, "r1") is None
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.execution_halted is False


def test_repeated_pre_execution_rejections_do_not_accumulate(running_app):
    running_app.execution.position_controller = DenyingPositionController()
    before = running_app.execution.reservation_ledger.active_reserved_capital()

    for index in range(5):
        execute(running_app, request_id=f"r{index}")

    assert running_app.execution.reservation_ledger.active_reserved_capital() == before
    assert running_app.execution._risk_admissions == {}


# --------------------------------------------------------------------------
# T5 — durable financial finalization failure keeps its own semantics
# --------------------------------------------------------------------------


def test_finalization_failure_stays_indeterminate_and_halts(running_app):
    def failing_apply(*args, **kwargs):
        raise RuntimeError("portfolio persist failed")

    running_app.execution.portfolio_foundation.apply_confirmed = failing_apply

    result = execute(running_app)

    assert result["status"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert result["error_code"] == "DURABLE_FINANCIAL_FINALIZATION_FAILED"
    assert result["recovery_required"] is True
    assert reservation_status(running_app, "r1") == ReservationStatus.INDETERMINATE.value
    assert journal_state(running_app, "r1") == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert running_app.execution.execution_halted is True
    assert running_app.execution.recovery_required is True


def test_finalization_failure_clears_the_admission(running_app):
    def failing_apply(*args, **kwargs):
        raise RuntimeError("portfolio persist failed")

    running_app.execution.portfolio_foundation.apply_confirmed = failing_apply

    execute(running_app)

    assert running_app.execution._risk_admissions == {}
    assert running_app.execution._execution_side_effect_ids == set()


def test_a_failing_ledger_write_still_ends_the_admission(running_app):
    """A request whose capital cannot be resolved keeps no authority token."""

    def failing_commit(request_id):
        raise RuntimeError("reservation ledger write failed")

    running_app.execution.reservation_ledger.commit = failing_commit

    result = execute(running_app)

    assert result["error_code"] == "CAPITAL_RESERVATION_COMMIT_FAILED"
    assert result["recovery_required"] is True
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.execution_halted is True
    assert running_app.execution.recovery_required is True


# --------------------------------------------------------------------------
# T6 — exception before the side-effect boundary releases safely
# --------------------------------------------------------------------------


def test_exception_before_paper_side_effect_releases_capital(running_app):
    break_before_side_effect(running_app)

    execute(running_app)

    assert reservation_status(running_app, "r1") == ReservationStatus.RELEASED.value
    assert running_app.execution.reservation_ledger.active_reserved_capital() == D("0")


def test_exception_before_paper_side_effect_stays_retryable(running_app):
    break_before_side_effect(running_app)

    result = execute(running_app)

    assert result["status"] == "FAILED"
    assert result["commit_outcome"] == CommitOutcome.NOT_COMMITTED.value
    assert result["error_code"] == "EXECUTION_PIPELINE_EXCEPTION"
    assert journal_state(running_app, "r1") == CommitOutcome.NOT_COMMITTED.value
    assert running_app.execution._risk_admissions == {}
    # Nothing external happened, so the runtime is not driven into recovery.
    assert running_app.execution.execution_halted is False
    assert running_app.execution.recovery_required is False


def test_prepare_failure_still_releases_capital_without_halting(running_app):
    """The pre-existing prepare barrier keeps its safe-release contract."""

    def failing_prepare(request_id, payload):
        return False

    running_app.execution.transaction_journal.prepare = failing_prepare

    result = running_app.execution.execute(buy_decision(running_app), risk_state())

    assert result["error_code"] == "TRANSACTION_PREPARE_FAILED"
    assert reservation_status(running_app, "r1") == ReservationStatus.RELEASED.value
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.execution_halted is False


def test_repeated_pre_side_effect_exceptions_do_not_accumulate(running_app):
    break_before_side_effect(running_app)
    before = running_app.execution.reservation_ledger.active_reserved_capital()

    for index in range(3):
        result = execute(running_app, request_id=f"r{index}")
        assert result["status"] == "FAILED"

    assert running_app.execution.reservation_ledger.active_reserved_capital() == before
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.execution_halted is False


# --------------------------------------------------------------------------
# H-1 — non-exception failures respect the same boundary
# --------------------------------------------------------------------------


class RejectingPositionController:
    """Admits the request, then refuses the position registration.

    This is the shape ExecutionManager's compatibility contract expects: a
    controller may approve opening and still return an unsuccessful
    registration, which ``_execute_paper_buy`` turns into
    POSITION_OPEN_REJECTED — after ``_paper_open_trade`` has already
    persisted the trade.
    """

    def can_open(self, symbol):
        return True

    def open_position(self, **kwargs):
        return {"success": False, "reason": "position register refused"}


def fail_after_side_effect(app: AtlasApplication) -> None:
    """Reach a real FAILED result raised after the paper book was mutated.

    ``_position_open`` runs only when no durable portfolio foundation is
    configured — the configuration ExecutionManager still supports for
    established transaction-journal users, where ``_durable_financial_ready``
    returns ready and the commit-outcome contract is unchanged. That branch
    is where a non-exception failure after the side-effect boundary is
    genuinely reachable, so it is where H-1 is proven.
    """
    app.execution.portfolio_foundation = None
    app.execution.position_controller = RejectingPositionController()


def fail_before_side_effect(app: AtlasApplication) -> None:
    """Return an explicit FAILED result before the paper book is touched.

    A zero allocation is rejected as ZERO_ALLOCATION at the top of
    ``_execute_paper_buy``, before ``_paper_open_trade`` runs.
    """
    app.execution.allocate_capital = lambda request: 0.0


def test_failed_result_after_side_effect_marks_capital_indeterminate(running_app):
    fail_after_side_effect(running_app)

    execute(running_app)

    assert reservation_status(running_app, "r1") == ReservationStatus.INDETERMINATE.value
    assert running_app.execution._risk_admissions == {}


def test_failed_result_after_side_effect_halts_the_runtime(running_app):
    fail_after_side_effect(running_app)

    execute(running_app)

    assert running_app.execution.execution_halted is True
    assert running_app.execution.recovery_required is True
    assert running_app.execution.halt_reason == "EXECUTION_INTERRUPTED_AFTER_SIDE_EFFECT"


def test_failed_result_after_side_effect_leaves_the_journal_unknown(running_app):
    fail_after_side_effect(running_app)

    execute(running_app)

    assert journal_state(running_app, "r1") == (
        CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    )


def test_failed_result_after_side_effect_preserves_the_business_reason(running_app):
    fail_after_side_effect(running_app)

    result = execute(running_app)

    # The failure is reclassified as uncertain, never relabelled successful,
    # and the original business reason survives.
    assert result["success"] is False
    assert result["status"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert result["commit_outcome"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert result["recovery_required"] is True
    assert result["original_status"] == "FAILED"
    assert result["error_code"] == "POSITION_OPEN_REJECTED"


def test_no_post_side_effect_failure_ends_released_and_running(running_app):
    """The H-1 forbidden combination must be unreachable."""
    fail_after_side_effect(running_app)

    result = execute(running_app)

    forbidden = (
        result["status"] in ExecutionManager.FAILURE_STATUSES
        and reservation_status(running_app, "r1") == ReservationStatus.RELEASED.value
        and running_app.execution.execution_halted is False
    )
    assert forbidden is False

    assert journal_state(running_app, "r1") != CommitOutcome.NOT_COMMITTED.value


def test_failed_result_before_side_effect_releases_capital(running_app):
    fail_before_side_effect(running_app)

    result = execute(running_app)

    assert result["status"] == "FAILED"
    assert result["error_code"] == "ZERO_ALLOCATION"
    assert result["commit_outcome"] == CommitOutcome.NOT_COMMITTED.value
    assert reservation_status(running_app, "r1") == ReservationStatus.RELEASED.value
    assert journal_state(running_app, "r1") == CommitOutcome.NOT_COMMITTED.value
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.execution_halted is False
    assert running_app.execution.recovery_required is False


def test_repeated_pre_side_effect_failures_do_not_accumulate(running_app):
    fail_before_side_effect(running_app)
    before = running_app.execution.reservation_ledger.active_reserved_capital()

    for index in range(3):
        assert execute(running_app, request_id=f"r{index}")["status"] == "FAILED"

    assert running_app.execution.reservation_ledger.active_reserved_capital() == before
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.execution_halted is False


def test_exception_and_failed_result_resolve_consistently(running_app, tmp_path):
    """The same boundary must produce the same financial classification."""
    fail_after_side_effect(running_app)
    by_result = execute(running_app)

    other_dir = tmp_path / "other"
    seed_valid_state(other_dir)
    other = AtlasApplication(state_directory=other_dir)
    other.execution.start()
    break_after_side_effect(other)
    by_exception = other.execution.execute(buy_decision(other), risk_state())

    assert by_result["status"] == by_exception["status"]
    assert by_result["commit_outcome"] == by_exception["commit_outcome"]
    assert by_result["recovery_required"] == by_exception["recovery_required"] is True
    assert (
        reservation_status(running_app, "r1")
        == reservation_status(other, "r1")
        == ReservationStatus.INDETERMINATE.value
    )
    assert journal_state(running_app, "r1") == journal_state(other, "r1")
    assert running_app.execution.execution_halted == other.execution.execution_halted


def test_sell_without_a_held_position_stays_before_the_boundary(running_app):
    """A SELL Atlas cannot back with a real position never reaches the book.

    Before Block-5A the caller supplied the exposure state, so a phantom
    position carried this request all the way to ``_execute_paper_sell`` and
    the reachable failure was POSITION_NOT_FOUND. Exposure is now derived from
    the durable book, so the same request is refused at admission instead: the
    boundary moved earlier, and the safety claims this test owns - the paper
    book is untouched, no admission survives, the runtime does not halt - are
    unchanged. The durable POSITION_NOT_FOUND defence still exists below this
    point and is covered directly in the Block-5A suite.
    """
    decision = ExecutionRequest(
        "BTCUSDT",
        "SELL",
        10,
        "100",
        confidence=90,
        risk="HIGH",
        request_id="s1",
        reduce_only=True,
    ).to_dict()

    # A caller-supplied exposure can no longer manufacture a reduction: the
    # durable book holds no position, so there is nothing to reduce.
    exposure = PositionExposure("BTCUSDT", D("10"), D("10"), D("100"))
    result = running_app.execution.execute(
        decision, risk_state_with(exposure)
    )

    assert result["success"] is False
    assert result["status"] == "REJECTED"
    assert result["reason"] == "NON_RISK_REDUCING_SELL"
    assert running_app.paper_trader.positions == {}
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.execution_halted is False


# --------------------------------------------------------------------------
# H-3 — a denied paper mutation can never become a successful execution
# --------------------------------------------------------------------------
#
# PaperTrader answers a refused mutation without raising:
#
#   open_trade  -> {"status": "FAILED", "reason": "Position exists"}
#   close_trade -> {"status": "FAILED", "reason": "No position"}
#
# and ExecutionManager's own wrapper adds {"success": False, ...} when the
# call raises. Hydration copies identifiers and numerics only — deliberately,
# because a successful open answers "OPENED", which is not one of this
# manager's success statuses — so the outcome has to be inspected separately.
# Before this fix it was not inspected at all, and a refused paper trade
# still finished as PAPER_EXECUTED with a fabricated durable position.
#
# The refusals above happen to be raised before PaperTrader mutates anything,
# but the exception wrapper case is not: save() truncates the book before
# writing, so a failure there can leave a partially written file. The manager
# cannot tell those cases apart from outside, so every component-reported
# failure past the side-effect marker is treated as uncertain.


def refuse_paper_open(app: AtlasApplication) -> None:
    def refusing_open(symbol, price, amount=100):
        return {"status": "FAILED", "reason": "Position exists"}

    app.paper_trader.open_trade = refusing_open


def refuse_paper_close(app: AtlasApplication) -> None:
    def refusing_close(symbol):
        return {"status": "FAILED", "reason": "No position"}

    app.paper_trader.close_trade = refusing_close


# T1 — BUY component failure

def test_refused_paper_open_is_not_a_successful_execution(running_app):
    refuse_paper_open(running_app)

    result = execute(running_app)

    assert result["success"] is False
    assert result["status"] != "PAPER_EXECUTED"
    assert result["status"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert result["original_status"] == "FAILED"
    assert result["error_code"] == "PAPER_TRADE_REJECTED"
    assert result["message"] == "Position exists"


def test_refused_paper_open_resolves_as_uncertain(running_app):
    refuse_paper_open(running_app)

    execute(running_app)

    assert reservation_status(running_app, "r1") == ReservationStatus.INDETERMINATE.value
    assert journal_state(running_app, "r1") == (
        CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    )
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.execution_halted is True
    assert running_app.execution.recovery_required is True


# T2 — SELL component failure

def test_refused_paper_close_is_not_a_successful_execution(running_app):
    """A durable position the paper book does not know about."""
    assert execute(running_app)["status"] == "PAPER_EXECUTED"
    running_app.paper_trader.positions.clear()
    refuse_paper_close(running_app)

    exposure = PositionExposure("BTCUSDT", D("100"), D("10"), D("1000"))
    decision = ExecutionRequest(
        "BTCUSDT",
        "SELL",
        10,
        "1000",
        confidence=90,
        risk="HIGH",
        request_id="s1",
        reduce_only=True,
    ).to_dict()

    result = running_app.execution.execute(decision, risk_state_with(exposure))

    assert result["success"] is False
    assert result["status"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert result["error_code"] == "PAPER_TRADE_REJECTED"
    assert result["message"] == "No position"
    assert journal_state(running_app, "s1") == (
        CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    )
    assert running_app.execution._risk_admissions == {}
    assert running_app.execution.execution_halted is True


# T3 — a raising component keeps the M-A contract

def test_raising_paper_component_is_still_uncertain(running_app):
    def raising_open(symbol, price, amount=100):
        raise RuntimeError("paper book write failed")

    running_app.paper_trader.open_trade = raising_open

    result = execute(running_app)

    # The wrapper converts the exception into {"success": False, ...}, which
    # the same authority check now rejects.
    assert result["success"] is False
    assert result["status"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert reservation_status(running_app, "r1") == ReservationStatus.INDETERMINATE.value
    assert journal_state(running_app, "r1") == (
        CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    )
    assert running_app.execution.execution_halted is True


# T4 — a succeeding component is unchanged

def test_successful_paper_component_is_unchanged(running_app):
    result = execute(running_app)

    assert result["success"] is True
    assert result["status"] == "PAPER_EXECUTED"
    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value
    assert reservation_status(running_app, "r1") == ReservationStatus.COMMITTED.value
    assert running_app.paper_trader.positions["BTCUSDT"]["amount"] > 0


def test_component_success_shapes_are_not_read_as_failure():
    """PaperTrader's own success vocabulary must not trip the check."""
    assert ExecutionManager._component_reported_failure(
        {"status": "OPENED", "position": {}}
    ) is False
    assert ExecutionManager._component_reported_failure(
        {"status": "CLOSED", "profit": 5}
    ) is False
    assert ExecutionManager._component_reported_failure({}) is False
    assert ExecutionManager._component_reported_failure(None) is False
    assert ExecutionManager._component_reported_failure(
        {"status": "FAILED", "reason": "Position exists"}
    ) is True
    assert ExecutionManager._component_reported_failure(
        {"success": False, "status": "FAILED"}
    ) is True


# T5 — hydration of identifiers and numerics is untouched

def test_successful_component_fields_still_hydrate(running_app):
    result = execute(running_app)

    assert result["order_id"]
    assert result["filled_price"] == 10
    assert result["filled_amount"] > 0
    assert result["data"]["paper_trade"]["status"] == "OPENED"


# T6 — the false-success invariant

def test_component_failure_can_never_end_successful(running_app):
    refuse_paper_open(running_app)

    result = execute(running_app)

    forbidden = (
        bool(result.get("success"))
        or result["status"] == "PAPER_EXECUTED"
        or reservation_status(running_app, "r1") == ReservationStatus.COMMITTED.value
        or journal_state(running_app, "r1") == CommitOutcome.COMMITTED.value
    )
    assert forbidden is False


def test_component_failure_confirms_no_durable_position(running_app):
    refuse_paper_open(running_app)

    execute(running_app)

    # The authoritative book must not gain a position the paper book refused.
    assert running_app.portfolio_foundation.snapshot()["positions"] == {}
    assert running_app.paper_trader.positions == {}


# T7 — restart after a component failure stays recovery-gated

def test_restart_after_component_failure_is_recovery_gated(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)

    first = AtlasApplication(state_directory=state_dir)
    first.execution.start()
    refuse_paper_open(first)
    execute(first)

    restarted = AtlasApplication(state_directory=state_dir)
    restarted.execution.start()

    assert restarted.transaction_journal.has_unresolved() is True

    result = execute(restarted, request_id="r2")

    assert result["status"] == "RECOVERY_REQUIRED"
    assert restarted.execution.reservation_ledger.get("r2") is None
    assert restarted.execution._risk_admissions == {}
    assert restarted.portfolio_foundation.snapshot()["positions"] == {}


# --------------------------------------------------------------------------
# PAPER / LIVE
# --------------------------------------------------------------------------


def test_runtime_stays_paper_only_through_every_failure_path(running_app):
    break_after_side_effect(running_app)
    execute(running_app)

    assert running_app.execution.mode == ExecutionManager.MODE_PAPER
    assert running_app.execution.live_execution_enabled is False
