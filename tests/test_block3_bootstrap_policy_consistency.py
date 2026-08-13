"""Block 3 / Package 2, M-D: bootstrap inputs must be traceable to, and
validated against, the same policy the runtime will actually use.

These tests exercise bootstrap_financial_state() with capital/policy values
derived exactly the way the operator CLI (tools/bootstrap_financial_state.py)
and the AtlasApplication composition root derive them -- from
CapitalManager.total_capital -> RiskPolicy(total_capital) -- rather than
hard-coded literals, so a change to those defaults cannot silently drift the
tests away from the canonical path. No risk/capital policy number is
introduced here; the values below are pinned only as a regression net
against accidental change elsewhere.
"""

from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal as D

import pytest

import core.financial_state_bootstrap as bootstrap_module
from core.capital_reservation import (
    CapitalReservation,
    CapitalReservationLedger,
    JsonReservationStore,
    ReservationStatus,
)
from core.execution_portfolio_foundation import ExecutionPortfolioFoundation, FinancialStateStore
from core.financial_state_bootstrap import BootstrapOutcome, bootstrap_financial_state
from core.risk_engine import RiskPolicy
from core.risk_state_store import JsonRiskStateStore
from portfolio.capital_manager import CapitalManager

TODAY = date(2026, 1, 1)


def _canonical_policy() -> RiskPolicy:
    capital = CapitalManager()
    return RiskPolicy(total_capital=D(str(capital.total_capital)))


# ---------------------------------------------------------------------------
# Regression net: no policy number changes in this package
# ---------------------------------------------------------------------------


def test_canonical_policy_numbers_are_unchanged():
    policy = _canonical_policy()
    assert policy.cash_reserve_pct == D("0.20")
    assert policy.max_position_pct == D("0.40")
    assert policy.portfolio_exposure_pct == D("0.80")
    assert policy.global_minimum_confidence == D("0.60")
    assert policy.drawdown_warning_pct == D("0.05")
    assert policy.drawdown_restrict_pct == D("0.10")
    assert policy.drawdown_halt_pct == D("0.15")
    assert policy.max_daily_loss_pct == D("0.05")
    assert policy.version == "phase3-risk-v1"


# ---------------------------------------------------------------------------
# canonical CLI/default policy -> runtime-compatible state
# ---------------------------------------------------------------------------


def test_bootstrap_with_canonical_defaults_produces_runtime_compatible_state(tmp_path):
    policy = _canonical_policy()

    result = bootstrap_financial_state(
        state_directory=tmp_path,
        initial_capital=policy.total_capital,
        allocatable_capital=policy.allocatable_capital,
        policy_version=policy.version,
        today_utc=TODAY,
    )
    assert result.succeeded
    assert {r.outcome for r in result.results} == {BootstrapOutcome.CREATED}

    # The exact canonical loaders execution_manager.py / AtlasApplication use.
    restored = JsonRiskStateStore(tmp_path / "risk_accounting_state.json").load(
        expected_policy_version=policy.version, today_utc=TODAY,
    )
    assert restored.policy_version == policy.version

    ledger = CapitalReservationLedger(
        JsonReservationStore(tmp_path / "capital_reservations.json"),
        policy.allocatable_capital,
    )
    assert ledger.ready is True
    assert ledger.available == policy.allocatable_capital

    foundation = ExecutionPortfolioFoundation(
        FinancialStateStore(tmp_path / "execution_financial_state.json"),
    )
    assert foundation.ready is True


def test_bootstrap_with_stale_v1_literal_is_incompatible_with_canonical_policy(tmp_path):
    # Earlier Package-2C fixtures/ADR text used "v1", which the real
    # RiskPolicy.version ("phase3-risk-v1") does not match. Bootstrapping
    # with "v1" must not be silently treated as runtime-compatible.
    policy = _canonical_policy()

    bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("10000"),
        allocatable_capital=D("8000"), policy_version="v1", today_utc=TODAY,
    )

    with pytest.raises(ValueError, match="policy version mismatch"):
        JsonRiskStateStore(tmp_path / "risk_accounting_state.json").load(
            expected_policy_version=policy.version, today_utc=TODAY,
        )


# ---------------------------------------------------------------------------
# policy version mismatch -> INVALID_EXISTING / POLICY_VERSION_MISMATCH
# ---------------------------------------------------------------------------


def test_rebootstrap_with_different_policy_version_does_not_silently_succeed(tmp_path):
    policy = _canonical_policy()
    first = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=policy.total_capital,
        allocatable_capital=policy.allocatable_capital, policy_version=policy.version,
        today_utc=TODAY,
    )
    assert first.succeeded

    second = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=policy.total_capital,
        allocatable_capital=policy.allocatable_capital,
        policy_version="a-future-policy-revision", today_utc=TODAY,
    )
    assert second.succeeded is False
    risk_result = second.result_for("risk_accounting_state")
    assert risk_result.outcome is BootstrapOutcome.INVALID_EXISTING
    assert risk_result.reason_code == "POLICY_VERSION_MISMATCH"


# ---------------------------------------------------------------------------
# capital incompatibility -> INVALID_EXISTING / CAPITAL_MISMATCH
# ---------------------------------------------------------------------------


def test_rebootstrap_with_smaller_allocatable_capital_over_encumbered_state_fails(tmp_path):
    policy = _canonical_policy()
    first = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=policy.total_capital,
        allocatable_capital=policy.allocatable_capital, policy_version=policy.version,
        today_utc=TODAY,
    )
    assert first.succeeded

    # Reservations an operator made under the original (larger) allocatable
    # capital.
    reservation_path = tmp_path / "capital_reservations.json"
    JsonReservationStore(reservation_path).save((
        CapitalReservation(
            reservation_id="r1", request_id="req-1",
            amount=policy.allocatable_capital - D("1"), status=ReservationStatus.RESERVED,
        ),
    ))
    before = reservation_path.read_bytes()

    # Operator re-runs bootstrap with a smaller allocatable capital (e.g.
    # total_capital was lowered). The existing encumbrance no longer fits
    # and must not be silently reported as ready.
    smaller_allocatable = policy.allocatable_capital / 2
    result = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=policy.total_capital,
        allocatable_capital=smaller_allocatable, policy_version=policy.version,
        today_utc=TODAY,
    )

    assert result.succeeded is False
    reservation_result = result.result_for("capital_reservations")
    assert reservation_result.outcome is BootstrapOutcome.INVALID_EXISTING
    assert reservation_result.reason_code == "CAPITAL_MISMATCH"
    assert reservation_path.read_bytes() == before


# ---------------------------------------------------------------------------
# no duplicated policy constants in the bootstrap core
# ---------------------------------------------------------------------------


def test_bootstrap_core_does_not_hard_code_policy_constants():
    source = inspect.getsource(bootstrap_module)
    assert "phase3-risk-v1" not in source
    assert "0.20" not in source
    assert "0.80" not in source
