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

The boundary is ``_finalize_durable_financial_state``, which applies the
confirmed execution to ExecutionPortfolioFoundation. Before it, nothing
external can have happened and capital is released. After it, this manager
cannot prove the outcome either way, so capital is marked INDETERMINATE and
the runtime halts for operator recovery rather than being released as if
nothing happened.

It was previously PaperTrader.open_trade()/close_trade(). PaperTrader is now
a passive mirror projected from the durable authority after the commit, so it
mutates nothing the pipeline depends on and can no longer classify anything;
the only configuration where it is not the authority that mutates first is
the foundation-less one, where PositionController still carries the marker.
Test names in the T1 family retain their historical "paper_side_effect"
wording for continuity.

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
    """Raise once the side-effect boundary has been crossed.

    The boundary is no longer PaperTrader. PaperTrader is a passive mirror
    projected from the durable authority *after* the commit, so the only
    mutation an execution can be interrupted on the far side of is
    ``_finalize_durable_financial_state`` itself. The marker is set
    immediately before it, and this injection fails the durable snapshot
    read taken inside it, which reproduces a post-boundary interruption.

    Block-5A also reads that snapshot to derive the canonical RiskState,
    which happens during ``risk_check`` and therefore before the boundary.
    Scoping the injection to reads taken once the marker is set keeps this
    reproducing the post-side-effect interruption instead of degenerating
    into an admission refusal.
    """
    durable_snapshot = app.execution.portfolio_foundation.snapshot

    def failing_snapshot(*args, **kwargs):
        if app.execution._execution_side_effect_ids:
            raise RuntimeError("durable snapshot read failed")
        return durable_snapshot(*args, **kwargs)

    app.execution.portfolio_foundation.snapshot = failing_snapshot


def break_before_side_effect(app: AtlasApplication) -> None:
    """Raise before PaperTrader is reached.

    Reading the admitted quote allocation is the first step of
    ``_execute_paper_buy`` and runs before any component mutation, so this
    reproduces an interruption on the near side of the boundary.
    """

    def failing_allocation(request):
        raise RuntimeError("allocation engine failed")

    app.execution._admitted_quote_allocation = failing_allocation


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
    # The boundary moved to durable finalization, so an interruption on its
    # far side is now owned by that stage's own reason token. The safety
    # outcome - halted, recovery required, capital INDETERMINATE - is
    # unchanged; only which stage reports the halt is.
    assert running_app.execution.halt_reason == "DURABLE_FINANCIAL_FINALIZATION_FAILED"


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
    # The interruption is now caught by durable finalization's own handler
    # rather than the outer pipeline handler, so the stage that owns the
    # failure names it. The uncertainty contract above is unchanged.
    assert result["error_code"] == "DURABLE_FINANCIAL_FINALIZATION_FAILED"


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

    A request with no canonical approval is rejected as
    CANONICAL_ALLOCATION_MISSING at the top of ``_execute_paper_buy``, before
    ``_paper_open_trade`` runs.
    """
    app.execution._admitted_quote_allocation = lambda request: None


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
    assert result["error_code"] == "CANONICAL_ALLOCATION_MISSING"
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
# H-3 — PaperTrader can never affect an execution
# --------------------------------------------------------------------------
#
# PaperTrader used to be called *before* durable finalization, and its answer
# was treated as authoritative:
#
#   open_trade  -> {"status": "FAILED", "reason": "Position exists"}
#   close_trade -> {"status": "FAILED", "reason": "No position"}
#
# Both refusals are returned without the book being written at all, yet they
# landed past the side-effect marker, so a legitimate add-to-position BUY (or
# a SELL of a position the book had lost) became PAPER_TRADE_REJECTED, marked
# capital INDETERMINATE and halted the whole runtime for operator recovery -
# for a side effect that provably never happened.
#
# PaperTrader is now a passive mirror: it is projected from
# ExecutionPortfolioFoundation *after* the commit and is never consulted
# before one. These tests pin the inverted invariant - a refusing, stale, or
# outright broken paper book cannot change a trade's outcome in any way.


def refuse_paper_open(app: AtlasApplication) -> None:
    """A paper book that refuses every open, as a stale book would."""
    def refusing_open(symbol, price, amount=100):
        return {"status": "FAILED", "reason": "Position exists"}

    app.paper_trader.open_trade = refusing_open


def refuse_paper_close(app: AtlasApplication) -> None:
    def refusing_close(symbol):
        return {"status": "FAILED", "reason": "No position"}

    app.paper_trader.close_trade = refusing_close


def break_paper_mirror(app: AtlasApplication) -> None:
    """Make the passive mirror's own persistence fail."""
    def failing_save():
        raise OSError("paper book write failed")

    app.paper_trader.save = failing_save


# T1 — a refusing paper book no longer affects a BUY

def test_refused_paper_open_no_longer_affects_the_execution(running_app):
    refuse_paper_open(running_app)

    result = execute(running_app)

    assert result["success"] is True
    assert result["status"] == "PAPER_EXECUTED"
    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value
    assert "PAPER_TRADE_REJECTED" not in str(result.get("error_code"))


def test_refused_paper_open_never_halts_the_runtime(running_app):
    refuse_paper_open(running_app)

    execute(running_app)

    assert reservation_status(running_app, "r1") == ReservationStatus.COMMITTED.value
    assert journal_state(running_app, "r1") == CommitOutcome.COMMITTED.value
    assert running_app.execution.execution_halted is False
    assert running_app.execution.recovery_required is False


def test_stale_paper_book_position_does_not_block_a_buy(running_app):
    """The reachable form of the "Position exists" bug: a diverged book.

    A genuine add-to-position BUY is refused earlier and independently by
    RiskEngine (DUPLICATE_OPEN_POSITION, core/risk_engine.py), so it never
    reached PaperTrader. What did reach it was divergence: a paper book
    holding a symbol the authority is flat on - a book restored from an
    older file, or left stale by the by-design partial-exit skip. That used
    to answer "Position exists", which became PAPER_TRADE_REJECTED, marked
    capital INDETERMINATE and halted the runtime, for a refusal that wrote
    nothing. The stale entry must now simply be overwritten by the
    projection.
    """
    running_app.paper_trader.positions["BTCUSDT"] = {
        "symbol": "BTCUSDT",
        "stale_marker": True,
    }
    assert running_app.portfolio_foundation.snapshot()["positions"] == {}

    result = execute(running_app)

    assert result["success"] is True
    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value
    assert running_app.execution.execution_halted is False
    assert running_app.execution.recovery_required is False

    durable = running_app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]
    mirrored = running_app.paper_trader.positions["BTCUSDT"]

    # Projection, not accumulation: the mirror equals durable truth exactly
    # and the stale record is gone rather than merged with.
    assert "stale_marker" not in mirrored
    assert mirrored["base_quantity"] == str(durable["base_quantity"])
    assert mirrored["position_id"] == str(durable["position_id"])
    assert D(mirrored["base_quantity"]) > D("0")
    assert running_app.paper_trader.history[-1]["type"] == "OPEN"


# T2 — a SELL whose symbol the paper book never had

def test_sell_succeeds_when_the_paper_book_lacks_the_symbol(running_app):
    """A durable position the paper book does not know about.

    This is the state the runtime was left in whenever paper_trades.json was
    lost or archived while durable state survived. It used to halt the
    runtime; the mirror must simply catch up.
    """
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

    assert result["success"] is True
    assert journal_state(running_app, "s1") == CommitOutcome.COMMITTED.value
    assert running_app.execution.execution_halted is False
    # Projected from the authority: flat there means absent here.
    durable = running_app.portfolio_foundation.snapshot()["positions"]
    assert ("BTCUSDT" in running_app.paper_trader.positions) == ("BTCUSDT" in durable)


# T3 — a raising paper book cannot reach the execution at all

def test_raising_paper_book_cannot_affect_the_execution(running_app):
    def raising_open(symbol, price, amount=100):
        raise RuntimeError("paper book write failed")

    running_app.paper_trader.open_trade = raising_open

    result = execute(running_app)

    assert result["success"] is True
    assert result["status"] == "PAPER_EXECUTED"
    assert reservation_status(running_app, "r1") == ReservationStatus.COMMITTED.value
    assert journal_state(running_app, "r1") == CommitOutcome.COMMITTED.value
    assert running_app.execution.execution_halted is False


def test_failing_authority_read_inside_the_mirror_cannot_affect_the_trade(running_app):
    """The mirror's own durable read is inside its containment, too.

    ``_mirror_paper_book`` reads the authority's snapshot to project from.
    That read is the one call in it that touches durable machinery, so it
    must not be able to escape and be reclassified as an interrupted
    execution - the commit has already landed by then.
    """
    foundation = running_app.execution.portfolio_foundation
    durable_snapshot = foundation.snapshot
    committed = {"done": False}
    apply_confirmed = foundation.apply_confirmed

    def marking_apply(*args, **kwargs):
        outcome = apply_confirmed(*args, **kwargs)
        committed["done"] = True
        return outcome

    def failing_snapshot(*args, **kwargs):
        if committed["done"]:
            raise RuntimeError("authority read failed inside the mirror")
        return durable_snapshot(*args, **kwargs)

    foundation.apply_confirmed = marking_apply
    foundation.snapshot = failing_snapshot

    result = execute(running_app)

    assert result["success"] is True
    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value
    assert result["data"]["paper_mirror"] == "DEGRADED"
    assert running_app.execution.execution_halted is False
    assert running_app.execution.recovery_required is False
    assert journal_state(running_app, "r1") == CommitOutcome.COMMITTED.value
    assert reservation_status(running_app, "r1") == ReservationStatus.COMMITTED.value


def test_failing_mirror_persistence_leaves_the_trade_successful(running_app):
    """A mirror that cannot write is reported, never escalated."""
    break_paper_mirror(running_app)

    result = execute(running_app)

    assert result["success"] is True
    assert result["status"] == "PAPER_EXECUTED"
    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value
    assert result["data"]["paper_mirror"] == "DEGRADED"
    assert running_app.execution.execution_halted is False
    assert running_app.execution.recovery_required is False
    # The authority is untouched by the mirror's failure.
    assert "BTCUSDT" in running_app.portfolio_foundation.snapshot()["positions"]


# T4 — a succeeding execution projects the book

def test_successful_paper_component_is_unchanged(running_app):
    result = execute(running_app)

    assert result["success"] is True
    assert result["status"] == "PAPER_EXECUTED"
    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value
    assert reservation_status(running_app, "r1") == ReservationStatus.COMMITTED.value
    assert result["data"]["paper_mirror"] == "OK"

    # The mirrored schema carries the authority's base quantity, never the
    # legacy quote-denominated `amount` the old book wrote.
    mirrored = running_app.paper_trader.positions["BTCUSDT"]
    assert D(mirrored["base_quantity"]) > D("0")
    assert "amount" not in mirrored
    assert mirrored["mirrored_from"] == "execution_financial_state"


# T5 — the fill is derived from the request, not from the paper book

def test_fill_fields_do_not_come_from_the_paper_book(running_app):
    result = execute(running_app)

    assert result["order_id"]
    assert result["filled_price"] == 10
    assert result["filled_amount"] > 0
    # No paper execution adapter reports a fill, so nothing is hydrated.
    assert "paper_trade" not in result["data"]


# T6 — the inverted false-failure invariant

def test_paper_book_failure_can_never_end_unsuccessful(running_app):
    refuse_paper_open(running_app)

    result = execute(running_app)

    forbidden = (
        not bool(result.get("success"))
        or result["status"] != "PAPER_EXECUTED"
        or reservation_status(running_app, "r1") != ReservationStatus.COMMITTED.value
        or journal_state(running_app, "r1") != CommitOutcome.COMMITTED.value
    )
    assert forbidden is False


def test_paper_book_refusal_does_not_block_the_durable_position(running_app):
    refuse_paper_open(running_app)

    execute(running_app)

    # The authority owns the position; the paper book cannot veto it, and is
    # projected from it afterwards.
    assert "BTCUSDT" in running_app.portfolio_foundation.snapshot()["positions"]
    assert "BTCUSDT" in running_app.paper_trader.positions


# T7 — restart after a refusing paper book is not recovery-gated

def test_restart_after_a_refusing_paper_book_is_not_recovery_gated(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)

    first = AtlasApplication(state_directory=state_dir)
    first.execution.start()
    refuse_paper_open(first)
    execute(first)

    restarted = AtlasApplication(state_directory=state_dir)
    restarted.execution.start()

    # Nothing was left unresolved, because nothing failed.
    assert restarted.transaction_journal.has_unresolved() is False
    assert restarted.execution.execution_halted is False
    assert "BTCUSDT" in restarted.portfolio_foundation.snapshot()["positions"]


# --------------------------------------------------------------------------
# PAPER / LIVE
# --------------------------------------------------------------------------


def test_runtime_stays_paper_only_through_every_failure_path(running_app):
    break_after_side_effect(running_app)
    execute(running_app)

    assert running_app.execution.mode == ExecutionManager.MODE_PAPER
    assert running_app.execution.live_execution_enabled is False
