"""Block-2B: canonical risk services wired into the composition root.

These tests build the real AtlasApplication composition root against an
isolated durable-state directory and prove the financial-safety contract of
the wiring itself:

- the canonical service family reaches ExecutionManager, once each;
- missing or corrupt durable state fails closed (no BUY authority, no
  capital reservation) instead of synthesizing a permissive ready state;
- valid restored state makes the canonical risk path reachable in PAPER;
- M-1 stays closed through the wired graph;
- CRITICAL and unsupported risk stay non-executable while risk-reducing
  exits stay available;
- LIVE is never activated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from core.application import (
    CAPITAL_RESERVATION_STATE_FILE,
    EXECUTION_FINANCIAL_STATE_FILE,
    RISK_ACCOUNTING_STATE_FILE,
    AtlasApplication,
)
from core.capital_reservation import CapitalReservationLedger, JsonReservationStore
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.execution_portfolio_foundation import (
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)
from core.risk_engine import RiskEngine, RiskState
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState


D = Decimal

POLICY_VERSION = "phase3-risk-v1"


# --------------------------------------------------------------------------
# durable state seeding
# --------------------------------------------------------------------------


def seed_reservation_state(state_dir):
    JsonReservationStore(state_dir / CAPITAL_RESERVATION_STATE_FILE).initialize_empty()


def seed_risk_state(state_dir, *, equity="10000", pnl="0"):
    JsonRiskStateStore(state_dir / RISK_ACCOUNTING_STATE_FILE).save(
        RestoredRiskState(
            datetime.now(UTC).date(),
            D(pnl),
            D(equity),
            D(equity),
            POLICY_VERSION,
        )
    )


def seed_financial_state(state_dir, *, cash="10000", held=None):
    """Seed the durable book, optionally with an already-open LONG position.

    ``held`` is ``(symbol, base_quantity, price)``. Block-5A derives both the
    canonical RiskState and reduce-only intent from this book, so a test that
    needs an exposure to reduce has to put it here rather than hand
    ExecutionManager a portfolio of its own.
    """
    store = FinancialStateStore(state_dir / EXECUTION_FINANCIAL_STATE_FILE)
    store.initialize(D(cash))

    if held is None:
        return

    symbol, base, price = held
    payload = store.load()
    payload["positions"][symbol] = {
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
    store.save(payload)


def seed_valid_state(state_dir, *, held=None):
    state_dir.mkdir(parents=True, exist_ok=True)
    seed_reservation_state(state_dir)
    seed_risk_state(state_dir)
    seed_financial_state(state_dir, held=held)


def application(state_dir) -> AtlasApplication:
    return AtlasApplication(state_directory=state_dir)


@pytest.fixture
def ready_app(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    return application(state_dir)


@pytest.fixture
def holding_app(tmp_path):
    """A runtime whose durable book already holds 10 BTCUSDT marked at 10."""
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir, held=("BTCUSDT", "10", "10"))
    return application(state_dir)


# --------------------------------------------------------------------------
# request helpers
# --------------------------------------------------------------------------


def high_bucket_allocation(app: AtlasApplication) -> Decimal:
    """Largest allocation the HIGH bucket policy admits, unchanged by wiring."""
    policy = app.risk_policy
    return policy.total_capital * policy.buckets[
        next(b for b in policy.buckets if b.value == "HIGH")
    ].max_allocation_pct


def buy_request(app, *, request_id="r1", risk="HIGH", amount=None, confidence=90):
    allocation = high_bucket_allocation(app) if amount is None else D(str(amount))
    return ExecutionRequest(
        "BTCUSDT",
        "BUY",
        10,
        str(allocation),
        confidence=confidence,
        risk=risk,
        request_id=request_id,
    )


def reduce_only_sell(*, request_id="r1", amount="100"):
    return ExecutionRequest(
        "BTCUSDT",
        "SELL",
        10,
        amount,
        confidence=90,
        risk="HIGH",
        request_id=request_id,
        reduce_only=True,
    )


def risk_state(*positions, pnl="0", equity="10000"):
    return RiskState(
        tuple(positions),
        sum((p.quote_exposure for p in positions), D("0")),
        D(pnl),
        D(equity),
        D(equity),
        True,
        datetime.now(UTC).date().isoformat(),
        POLICY_VERSION,
    )


class DenyingPositionController:
    """Compatibility gate that rejects after canonical risk approval."""

    def can_open(self, symbol):
        return False


# --------------------------------------------------------------------------
# T1 — canonical services wired
# --------------------------------------------------------------------------


def test_canonical_services_reach_execution_manager(ready_app):
    execution = ready_app.execution

    assert type(execution.risk_engine) is RiskEngine
    assert type(execution.reservation_ledger) is CapitalReservationLedger
    assert type(execution.risk_state_store) is JsonRiskStateStore
    assert type(execution.portfolio_foundation) is ExecutionPortfolioFoundation


def test_wired_state_is_ready_for_valid_durable_state(ready_app):
    assert ready_app.reservation_ledger.ready is True
    assert ready_app.portfolio_foundation.ready is True


def test_durable_state_paths_are_owned_by_the_composition_root(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = application(state_dir)

    assert app.risk_state_store.path == state_dir / RISK_ACCOUNTING_STATE_FILE
    assert app.reservation_ledger.store.path == state_dir / CAPITAL_RESERVATION_STATE_FILE
    assert app.portfolio_foundation.store.path == state_dir / EXECUTION_FINANCIAL_STATE_FILE


# --------------------------------------------------------------------------
# T2 — one authority
# --------------------------------------------------------------------------


def test_single_risk_and_reservation_authority(ready_app):
    assert ready_app.execution.risk_engine is ready_app.risk_engine
    assert ready_app.execution.reservation_ledger is ready_app.reservation_ledger
    assert ready_app.execution.risk_state_store is ready_app.risk_state_store
    assert ready_app.execution.portfolio_foundation is ready_app.portfolio_foundation


def test_container_resolves_the_same_authority_instances(ready_app):
    assert ready_app.container.get(RiskEngine) is ready_app.execution.risk_engine
    assert (
        ready_app.container.get(CapitalReservationLedger)
        is ready_app.execution.reservation_ledger
    )


def test_reservation_ledger_is_a_single_instance_for_the_lifecycle(ready_app):
    first = ready_app.execution.reservation_ledger

    ready_app.execution.risk_check(buy_request(ready_app), risk_state())

    assert ready_app.execution.reservation_ledger is first


# --------------------------------------------------------------------------
# T3 — missing durable state fails closed
# --------------------------------------------------------------------------


def test_missing_durable_state_denies_buy_and_reserves_nothing(tmp_path):
    app = application(tmp_path / "absent")

    assert app.reservation_ledger.ready is False
    assert app.portfolio_foundation.ready is False

    result = app.execution.risk_check(buy_request(app), risk_state())

    assert result["approved"] is False
    assert result["reason"] == "CAPITAL_RESERVATION_STATE_NOT_READY"
    assert result["status"] == "BLOCK_RECOVERY_REQUIRED"
    assert app.execution.reservation_ledger.get("r1") is None
    assert app.execution._risk_admissions == {}


def test_missing_risk_accounting_state_denies_buy(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    seed_reservation_state(state_dir)
    seed_financial_state(state_dir)
    app = application(state_dir)

    result = app.execution.risk_check(buy_request(app), risk_state())

    assert result["approved"] is False
    assert result["reason"] == "RISK_STATE_RESTORATION_FAILED"
    assert result["status"] == "BLOCK_RECOVERY_REQUIRED"
    assert app.execution.reservation_ledger.get("r1") is None
    assert app.execution._risk_admissions == {}


def test_missing_durable_state_halts_execution_startup(tmp_path):
    app = application(tmp_path / "absent")

    app.execution.start()

    assert app.execution.execution_halted is True
    assert app.execution.recovery_required is True


# --------------------------------------------------------------------------
# T4 — corrupt durable state fails closed
# --------------------------------------------------------------------------


def test_corrupt_reservation_state_denies_buy(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    (state_dir / CAPITAL_RESERVATION_STATE_FILE).write_text("{ not json", encoding="utf-8")
    seed_risk_state(state_dir)
    seed_financial_state(state_dir)
    app = application(state_dir)

    assert app.reservation_ledger.ready is False

    result = app.execution.risk_check(buy_request(app), risk_state())

    assert result["approved"] is False
    assert result["reason"] == "CAPITAL_RESERVATION_STATE_NOT_READY"
    assert app.execution._risk_admissions == {}


def test_corrupt_risk_accounting_state_denies_buy(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    seed_reservation_state(state_dir)
    seed_financial_state(state_dir)
    (state_dir / RISK_ACCOUNTING_STATE_FILE).write_text("{ not json", encoding="utf-8")
    app = application(state_dir)

    result = app.execution.risk_check(buy_request(app), risk_state())

    assert result["approved"] is False
    assert result["reason"] == "RISK_STATE_RESTORATION_FAILED"
    assert app.execution.reservation_ledger.get("r1") is None
    assert app.execution._risk_admissions == {}


def test_risk_policy_version_mismatch_denies_buy(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    seed_reservation_state(state_dir)
    seed_financial_state(state_dir)
    JsonRiskStateStore(state_dir / RISK_ACCOUNTING_STATE_FILE).save(
        RestoredRiskState(
            datetime.now(UTC).date(), D("0"), D("10000"), D("10000"), "some-other-policy"
        )
    )
    app = application(state_dir)

    result = app.execution.risk_check(buy_request(app), risk_state())

    assert result["approved"] is False
    assert result["reason"] == "RISK_STATE_RESTORATION_FAILED"
    assert app.execution.reservation_ledger.get("r1") is None


def test_corrupt_financial_state_denies_execution_startup(tmp_path):
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    seed_reservation_state(state_dir)
    seed_risk_state(state_dir)
    (state_dir / EXECUTION_FINANCIAL_STATE_FILE).write_text("{ not json", encoding="utf-8")
    app = application(state_dir)

    assert app.portfolio_foundation.ready is False

    app.execution.start()

    assert app.execution.execution_halted is True
    assert app.execution.recovery_required is True


# --------------------------------------------------------------------------
# T5 — valid restored state makes the canonical path reachable
# --------------------------------------------------------------------------


def test_valid_state_permits_canonical_risk_approval(ready_app):
    request = buy_request(ready_app)

    result = ready_app.execution.risk_check(request, risk_state())

    assert result["approved"] is True
    assert result["reason"] == "RISK_APPROVED"
    assert ready_app.execution.last_risk_decision["reason_code"] == "RISK_APPROVED"
    assert ready_app.execution.last_risk_decision["policy_version"] == POLICY_VERSION

    reservation = ready_app.execution.reservation_ledger.get(request.request_id)
    assert reservation is not None
    assert reservation.amount == D(str(request.amount))
    assert request.request_id in ready_app.execution._risk_admissions


def test_canonical_rejection_creates_no_reservation(ready_app):
    over_limit = high_bucket_allocation(ready_app) * D("5")

    result = ready_app.execution.risk_check(
        buy_request(ready_app, amount=over_limit), risk_state()
    )

    assert result["approved"] is False
    assert ready_app.execution.reservation_ledger.get("r1") is None
    assert ready_app.execution._risk_admissions == {}


# --------------------------------------------------------------------------
# T6 — M-1 regression through the wired graph
# --------------------------------------------------------------------------


def test_position_limit_rejection_leaves_no_reservation_or_admission(ready_app):
    ready_app.execution.position_controller = DenyingPositionController()
    before = ready_app.execution.reservation_ledger.active_reserved_capital()

    result = ready_app.execution.risk_check(buy_request(ready_app), risk_state())

    assert result["approved"] is False
    assert result["reason"] == "POSITION_LIMIT"
    assert ready_app.execution.reservation_ledger.active_reserved_capital() == before
    assert ready_app.execution.reservation_ledger.get("r1") is None
    assert ready_app.execution._risk_admissions == {}


def test_repeated_position_limit_rejections_do_not_accumulate(ready_app):
    ready_app.execution.position_controller = DenyingPositionController()
    before = ready_app.execution.reservation_ledger.active_reserved_capital()

    for index in range(5):
        result = ready_app.execution.risk_check(
            buy_request(ready_app, request_id=f"r{index}"), risk_state()
        )
        assert result["reason"] == "POSITION_LIMIT"

    assert ready_app.execution.reservation_ledger.active_reserved_capital() == before
    assert ready_app.execution._risk_admissions == {}


# --------------------------------------------------------------------------
# T7 — CRITICAL is not executable
# --------------------------------------------------------------------------


def test_critical_risk_is_not_executable(ready_app):
    result = ready_app.execution.risk_check(
        buy_request(ready_app, risk="CRITICAL"), risk_state()
    )

    assert result["approved"] is False
    assert result["reason"] == "CRITICAL_RISK_NOT_EXECUTABLE"
    assert result["details"]["approved_allocation"] == "0"
    assert ready_app.execution.reservation_ledger.get("r1") is None
    assert ready_app.execution._risk_admissions == {}


# --------------------------------------------------------------------------
# T8 — unsupported risk is not executable
# --------------------------------------------------------------------------


def test_unsupported_risk_level_is_not_executable(ready_app):
    result = ready_app.execution.risk_check(
        buy_request(ready_app, risk="EXTREME"), risk_state()
    )

    assert result["approved"] is False
    assert result["reason"] == "UNSUPPORTED_RISK_LEVEL"
    assert result["details"]["approved_allocation"] == "0"
    assert ready_app.execution.reservation_ledger.get("r1") is None
    assert ready_app.execution._risk_admissions == {}


# --------------------------------------------------------------------------
# T9 — risk-reducing exits stay available
# --------------------------------------------------------------------------


def test_reduce_only_exit_remains_available(holding_app):
    """The exit stays available, now proven against the durable book.

    Block-5A derives both the canonical RiskState and reduce-only intent from
    ExecutionPortfolioFoundation, so the exposure being reduced has to be a
    real held position rather than a portfolio the caller supplies. No
    ``market_state`` is passed at all, which is exactly the runtime shape.
    """
    holding_app.execution.position_controller = DenyingPositionController()

    result = holding_app.execution.risk_check(reduce_only_sell(amount="100"))

    assert result["approved"] is True
    assert holding_app.execution.last_risk_decision["reason_code"] == "RISK_REDUCTION_APPROVED"
    assert holding_app.execution.reservation_ledger.get("r1") is None
    assert "r1" in holding_app.execution._risk_admissions


# --------------------------------------------------------------------------
# T10 — PAPER / default deny
# --------------------------------------------------------------------------


def test_runtime_remains_paper_and_live_is_not_activated(ready_app):
    assert ready_app.execution_mode == ExecutionManager.MODE_PAPER
    assert ready_app.execution.mode == ExecutionManager.MODE_PAPER
    assert ready_app.execution.live_execution_enabled is False


# --------------------------------------------------------------------------
# T12 — restart determinism
# --------------------------------------------------------------------------


def test_restart_against_the_same_durable_state_is_deterministic(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)

    first = application(state_dir)
    second = application(state_dir)

    assert first.reservation_ledger.ready == second.reservation_ledger.ready is True
    assert first.portfolio_foundation.ready == second.portfolio_foundation.ready is True
    assert (
        first.portfolio_foundation.snapshot()["cash"]
        == second.portfolio_foundation.snapshot()["cash"]
    )
    assert first.risk_policy.version == second.risk_policy.version
    assert first.risk_policy.total_capital == second.risk_policy.total_capital
    assert first.reservation_ledger is not second.reservation_ledger


def test_reservation_survives_a_restart(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)

    first = application(state_dir)
    request = buy_request(first)
    assert first.execution.risk_check(request, risk_state())["approved"] is True

    restarted = application(state_dir)

    restored = restarted.reservation_ledger.get(request.request_id)
    assert restored is not None
    assert restored.amount == D(str(request.amount))
    # A restored reservation is durable state only; it grants no admission.
    assert restarted.execution._risk_admissions == {}
