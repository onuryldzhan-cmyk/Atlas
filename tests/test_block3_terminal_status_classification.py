"""Block-3 HIGH-1: terminal execution status classification.

The final independent Block-3 audit reproduced a durable-state defect at the
post-adapter terminal boundary of ``ExecutionManager.execute()``. That branch
classified an outcome with a *failure* allow-list::

    if status in self.FAILURE_STATUSES:      # {"FAILED", "ERROR"}

Every other terminal status therefore fell through into the durable-commit
path. The statuses that actually reach that point are ``PAPER_EXECUTED`` and
``FAILED`` from ``paper_execute``, ``REJECTED`` from the canonical-admission
guard in both routers, and ``LIVE_DISABLED`` / ``LIVE_NOT_IMPLEMENTED`` from
``live_execute``. So a correctly *denied* LIVE request - one that provably
performed no side effect whatsoever - was finalized as a confirmed execution:
``_finalize_durable_financial_state`` raised on the empty evidence, capital
was marked INDETERMINATE, the journal entry was left unresolved, the runtime
halted, and the audit record asserted that an execution "was confirmed" which
had never occurred. One such request permanently blocked the next run with
RECOVERY_REQUIRED until an operator reconciled by hand.

The replacement contract is a SUCCESS allow-list: only a status this manager
recognises as a completed execution continues to durable finalization, and
everything else - including any status added in future, and the ``UNKNOWN``
default of ``ExecutionResult.status`` - resolves through the unsuccessful
path and fails closed.

What these tests deliberately do not change: the side-effect marker, not the
status, still decides deterministic rollback versus genuine uncertainty. The
post-side-effect cases below exist to prove that distinction survived, so a
failure on the far side of ``PaperTrader`` stays INDETERMINATE rather than
being "cleaned up" into a false rollback.

No risk bucket, allocation percentage, confidence threshold, exposure
ceiling, sizing formula, or LIVE enablement is exercised or changed here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.application import AtlasApplication
from core.capital_reservation import ReservationStatus
from core.execution_models import ExecutionRequest
from core.execution_transaction_journal import CommitOutcome
from core.risk_engine import PositionExposure, RiskState

from tests.test_block2_risk_service_composition_wiring import (
    POLICY_VERSION,
    high_bucket_allocation,
    seed_valid_state,
)


D = Decimal


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _app(tmp_path, *, execution_mode: str = "PAPER") -> AtlasApplication:
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = AtlasApplication(state_directory=state_dir, execution_mode=execution_mode)
    app.execution.start()
    assert app.execution.execution_halted is False
    assert app.execution.recovery_required is False
    return app


@pytest.fixture
def paper_app(tmp_path) -> AtlasApplication:
    return _app(tmp_path)


@pytest.fixture
def live_app(tmp_path) -> AtlasApplication:
    """A LIVE-mode runtime. LIVE stays denied: nothing here enables it."""
    app = _app(tmp_path, execution_mode="LIVE")
    assert app.execution.mode == "LIVE"
    assert app.execution.live_execution_enabled is False
    return app


def risk_state_with(*positions) -> RiskState:
    return RiskState(
        tuple(positions),
        sum((item.quote_exposure for item in positions), D("0")),
        D("0"), D("10000"), D("10000"), True,
        datetime.now(UTC).date().isoformat(), POLICY_VERSION,
    )


def risk_state() -> RiskState:
    return risk_state_with()


def buy_decision(app: AtlasApplication, *, request_id: str = "r1") -> dict:
    return ExecutionRequest(
        "BTCUSDT", "BUY", 10, str(high_bucket_allocation(app)),
        confidence=90, risk="HIGH", request_id=request_id,
    ).to_dict()


def execute(app: AtlasApplication, *, request_id: str = "r1") -> dict:
    return app.execution.execute(buy_decision(app, request_id=request_id), risk_state())


def journal_state(app: AtlasApplication, request_id: str) -> str | None:
    entry = app.execution.transaction_journal.entries.get(request_id)
    return None if entry is None else entry.get("state")


def reservation_status(app: AtlasApplication, request_id: str) -> str | None:
    reservation = app.execution.reservation_ledger.get(request_id)
    return None if reservation is None else reservation.status.value


def force_terminal_status(app: AtlasApplication, payload: dict) -> None:
    """Replace the paper router so an arbitrary terminal status reaches the
    classifier, without faking any execution internals below it."""
    app.execution.paper_execute = lambda request: dict(payload)


def assert_no_durable_consequence(
    app: AtlasApplication, result: dict, request_id: str = "r1",
) -> None:
    """The no-side-effect contract, asserted as one unit.

    Deliberately says nothing about the result's own ``success`` flag: that
    flag is echoed from whatever the router reported, and the property under
    test is what Atlas *durably did*, not how the component labelled itself.
    """
    assert result["commit_outcome"] == CommitOutcome.NOT_COMMITTED.value
    assert result.get("recovery_required") is not True
    # capital released, not stranded
    assert reservation_status(app, request_id) == ReservationStatus.RELEASED.value
    # journal resolved, not left unresolved
    assert journal_state(app, request_id) == CommitOutcome.NOT_COMMITTED.value
    assert app.execution.transaction_journal.has_unresolved() is False
    # runtime still usable
    assert app.execution.execution_halted is False
    assert app.execution.recovery_required is False
    # no durable financial consequence
    assert app.execution.portfolio_foundation.snapshot()["positions"] == {}


# --------------------------------------------------------------------------
# 1-2. LIVE routing: denied cleanly, with no durable consequence
# --------------------------------------------------------------------------


def test_live_disabled_is_a_clean_denial_with_no_durable_consequence(live_app):
    """1 + 11 + 12: LIVE_DISABLED must not finalize as a confirmed execution."""
    result = execute(live_app)

    assert result["status"] != CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert result["success"] is False
    assert_no_durable_consequence(live_app, result)


def test_live_enabled_without_adapter_is_also_a_clean_denial(live_app):
    """2: LIVE_NOT_IMPLEMENTED is a denial too - no adapter ran, so nothing
    happened. Enabling the flag must not make the *absence* of an adapter
    look like a durable execution."""
    live_app.execution.live_execution_enabled = True

    result = execute(live_app)

    assert result["error_code"] == "LIVE_ADAPTER_NOT_IMPLEMENTED"
    assert result["success"] is False
    assert_no_durable_consequence(live_app, result)


# --------------------------------------------------------------------------
# 3-6. every other non-success terminal status
# --------------------------------------------------------------------------


def test_rejected_status_resolves_as_not_committed(paper_app):
    """3: REJECTED reaches the classifier from the canonical-admission guard
    inside both routers."""
    force_terminal_status(paper_app, {
        "success": False, "status": "REJECTED", "reason": "CANONICAL_RISK_ADMISSION_MISSING",
    })

    assert_no_durable_consequence(paper_app, execute(paper_app))


@pytest.mark.parametrize("status", ["FAILED", "ERROR"])
def test_declared_failure_statuses_keep_their_existing_resolution(paper_app, status):
    """4 + 5: the two statuses the old allow-list already handled must behave
    exactly as before. This is the no-regression half of the change."""
    force_terminal_status(paper_app, {"success": False, "status": status})

    assert_no_durable_consequence(paper_app, execute(paper_app))


@pytest.mark.parametrize(
    "status", ["UNKNOWN", "PARTIALLY_FILLED", "SETTLING", "", "paper_executed_typo"],
)
def test_unknown_terminal_status_fails_closed(paper_app, status):
    """6: an unrecognised status must be treated as not-committed rather than
    silently durable. This is the property the failure allow-list could not
    express: it admitted every unknown status into the commit path."""
    force_terminal_status(paper_app, {"success": True, "status": status})

    assert_no_durable_consequence(paper_app, execute(paper_app))


def test_success_status_vocabulary_is_the_classifier_authority(paper_app):
    """The allow-list is exactly SUCCESS_STATUSES - not a subset of it, and
    not a hand-maintained second copy."""
    manager = paper_app.execution

    assert "PAPER_EXECUTED" in manager.SUCCESS_STATUSES
    assert manager.FAILURE_STATUSES.isdisjoint(manager.SUCCESS_STATUSES)
    for denial_status in ("REJECTED", "LIVE_DISABLED", "LIVE_NOT_IMPLEMENTED", "UNKNOWN"):
        assert denial_status not in manager.SUCCESS_STATUSES


# --------------------------------------------------------------------------
# 7-8. genuine successes still commit
# --------------------------------------------------------------------------


def test_paper_success_still_commits_durably(paper_app):
    """7: the ordinary PAPER path is untouched."""
    result = execute(paper_app)

    assert result["status"] == "PAPER_EXECUTED"
    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value
    assert reservation_status(paper_app, "r1") == ReservationStatus.COMMITTED.value
    assert journal_state(paper_app, "r1") == CommitOutcome.COMMITTED.value
    assert "BTCUSDT" in paper_app.execution.portfolio_foundation.snapshot()["positions"]


def test_successful_reduce_only_close_still_commits(paper_app):
    """8: the reduce-only exit path must remain executable end to end.

    Principle 9 - a valid reduce-only exit must stay possible - is the one
    invariant a stricter terminal classifier could plausibly have broken, so
    it is asserted against a real close rather than a simulated status.
    """
    opened = execute(paper_app, request_id="open-1")
    assert opened["commit_outcome"] == CommitOutcome.COMMITTED.value

    position = paper_app.execution.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]
    base = D(position["base_quantity"])
    notional = base * D("10")

    close = ExecutionRequest(
        "BTCUSDT", "SELL", 10, str(notional),
        confidence=90, risk="HIGH", request_id="close-1", reduce_only=True,
    ).to_dict()

    # The authoritative exposure state is the caller's to supply; the
    # reduce-only check in RiskEngine reads it, not the portfolio snapshot.
    exposure = PositionExposure("BTCUSDT", base, D("10"), notional)
    result = paper_app.execution.execute(close, risk_state_with(exposure))

    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value
    assert paper_app.execution.portfolio_foundation.snapshot()["positions"] == {}


# --------------------------------------------------------------------------
# 9-10. post-side-effect uncertainty is NOT converted into rollback
# --------------------------------------------------------------------------


def test_explicit_failure_after_side_effect_stays_indeterminate(paper_app):
    """9: a FAILED result reported *after* PaperTrader persisted its book is
    still genuinely uncertain. The success allow-list must not turn recorded
    uncertainty into a deterministic rollback."""
    paper_app.execution._mark_execution_side_effect("r1")
    force_terminal_status(paper_app, {"success": False, "status": "FAILED"})

    result = execute(paper_app)

    assert result["commit_outcome"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert result["recovery_required"] is True
    assert reservation_status(paper_app, "r1") == ReservationStatus.INDETERMINATE.value
    assert journal_state(paper_app, "r1") == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert paper_app.execution.execution_halted is True


def test_denial_status_after_side_effect_also_stays_indeterminate(paper_app):
    """10: the same holds for a *denial-shaped* status. Uncertainty is decided
    by the recorded boundary, never by how the outcome was labelled - which is
    exactly why this change is safe to make at the status layer."""
    paper_app.execution._mark_execution_side_effect("r1")
    force_terminal_status(paper_app, {"success": False, "status": "REJECTED"})

    result = execute(paper_app)

    assert result["commit_outcome"] == CommitOutcome.COMMIT_STATUS_UNKNOWN.value
    assert reservation_status(paper_app, "r1") == ReservationStatus.INDETERMINATE.value
    assert paper_app.execution.execution_halted is True


# --------------------------------------------------------------------------
# 13-14. restart and retry semantics stay truthful
# --------------------------------------------------------------------------


def test_restart_after_live_denial_does_not_require_recovery(tmp_path, live_app):
    """13: the defect's real cost was that one denied LIVE request bricked the
    *next* run. A fresh runtime over the same durable state must start clean."""
    execute(live_app)

    restarted = AtlasApplication(
        state_directory=live_app.state_directory, execution_mode="PAPER",
    )
    restarted.execution.start()

    assert restarted.execution.transaction_journal.has_unresolved() is False
    assert restarted.execution.execution_halted is False
    assert restarted.execution.recovery_required is False
    assert reservation_status(restarted, "r1") == ReservationStatus.RELEASED.value


def test_live_denial_leaves_the_request_retryable(live_app):
    """14: a denial with no side effect released its claim, so the same
    request id is not mistaken for an in-flight duplicate."""
    first = execute(live_app)
    second = execute(live_app)

    assert first["status"] == second["status"]
    assert second["status"] != "SKIPPED"
    assert second.get("reason") != "DUPLICATE_REQUEST_PENDING"
    assert live_app.execution.execution_halted is False


def test_paper_execution_still_succeeds_after_a_live_denial(tmp_path):
    """The end-to-end statement of the fix: a LIVE denial must not poison the
    durable state that a subsequent PAPER runtime depends on."""
    live = _app(tmp_path, execution_mode="LIVE")
    execute(live, request_id="denied-1")

    paper = AtlasApplication(state_directory=live.state_directory)
    paper.execution.start()

    result = execute(paper, request_id="paper-1")

    assert result["commit_outcome"] == CommitOutcome.COMMITTED.value
    assert "BTCUSDT" in paper.execution.portfolio_foundation.snapshot()["positions"]
