"""Block 2C Part A: explicit financial-state bootstrap/recovery contract.

Covers H1-H4 / P1-P3 from the Block 2C work order:
- normal startup with missing/corrupt state remains fail-closed (H1)
- explicit bootstrap initializes state safely (H2)
- bootstrap cannot silently overwrite existing valid state (H3)
- corrupt state is not silently replaced (H4)
"""

from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal as D

import pytest

import core.application as application_module
from core.capital_reservation import CapitalReservationLedger, JsonReservationStore
from core.execution_portfolio_foundation import ExecutionPortfolioFoundation, FinancialStateStore
from core.financial_state_bootstrap import (
    BootstrapOutcome,
    bootstrap_financial_state,
)
from core.risk_state_store import JsonRiskStateStore


# ---------------------------------------------------------------------------
# H1 / P1 - normal startup, missing/corrupt state fails closed (unchanged)
# ---------------------------------------------------------------------------


def test_risk_state_store_load_on_missing_file_raises():
    store = JsonRiskStateStore("does-not-exist/risk_accounting_state.json")
    with pytest.raises(OSError):
        store.load(expected_policy_version="v1", today_utc=date(2026, 1, 1))


def test_reservation_ledger_missing_file_is_not_ready(tmp_path):
    ledger = CapitalReservationLedger(
        JsonReservationStore(tmp_path / "capital_reservations.json"), D("1000"),
    )
    assert ledger.ready is False
    with pytest.raises(RuntimeError, match="recovery required"):
        ledger.available  # noqa: B018


def test_portfolio_foundation_missing_file_is_not_ready(tmp_path):
    foundation = ExecutionPortfolioFoundation(
        FinancialStateStore(tmp_path / "execution_financial_state.json"),
    )
    assert foundation.ready is False
    with pytest.raises(RuntimeError, match="FINANCIAL_STATE_RECOVERY_REQUIRED"):
        foundation.snapshot()


def test_application_does_not_invoke_bootstrap_on_startup():
    """P2: bootstrap is explicit-only, never wired into the composition root."""

    source = inspect.getsource(application_module)
    assert "financial_state_bootstrap" not in source
    assert "bootstrap_financial_state" not in source


# ---------------------------------------------------------------------------
# H2 / P2 - explicit bootstrap initializes state safely
# ---------------------------------------------------------------------------


def test_bootstrap_creates_all_three_stores_and_they_become_ready(tmp_path):
    result = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("10000"), policy_version="v1",
        today_utc=date(2026, 1, 1),
    )

    assert result.succeeded
    assert {r.outcome for r in result.results} == {BootstrapOutcome.CREATED}

    risk_store = JsonRiskStateStore(tmp_path / "risk_accounting_state.json")
    restored = risk_store.load(expected_policy_version="v1", today_utc=date(2026, 1, 1))
    assert restored.current_equity == D("10000")
    assert restored.peak_equity == D("10000")
    assert restored.realized_daily_pnl == D("0")

    ledger = CapitalReservationLedger(
        JsonReservationStore(tmp_path / "capital_reservations.json"), D("10000"),
    )
    assert ledger.ready is True
    assert ledger.available == D("10000")

    foundation = ExecutionPortfolioFoundation(
        FinancialStateStore(tmp_path / "execution_financial_state.json"),
    )
    assert foundation.ready is True
    assert foundation.snapshot()["cash"] == D("10000")


def test_bootstrap_rejects_non_positive_initial_capital(tmp_path):
    with pytest.raises(ValueError, match="initial_capital"):
        bootstrap_financial_state(
            state_directory=tmp_path, initial_capital=D("0"), policy_version="v1",
        )


def test_bootstrap_rejects_empty_policy_version(tmp_path):
    with pytest.raises(ValueError, match="policy_version"):
        bootstrap_financial_state(
            state_directory=tmp_path, initial_capital=D("100"), policy_version="",
        )


# ---------------------------------------------------------------------------
# H3 / P3 - bootstrap cannot silently overwrite existing valid state
# ---------------------------------------------------------------------------


def test_bootstrap_is_already_exists_on_second_call_and_does_not_touch_state(tmp_path):
    first = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("10000"), policy_version="v1",
        today_utc=date(2026, 1, 1),
    )
    assert first.succeeded

    financial_path = tmp_path / "execution_financial_state.json"
    before = financial_path.read_bytes()

    second = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("999999"), policy_version="v1",
        today_utc=date(2026, 1, 1),
    )

    assert {r.outcome for r in second.results} == {BootstrapOutcome.ALREADY_EXISTS}
    assert financial_path.read_bytes() == before

    foundation = ExecutionPortfolioFoundation(
        FinancialStateStore(financial_path),
    )
    assert foundation.snapshot()["cash"] == D("10000")


# ---------------------------------------------------------------------------
# H4 - corrupt state is not silently replaced
# ---------------------------------------------------------------------------


def test_bootstrap_does_not_replace_corrupt_existing_state(tmp_path):
    corrupt_path = tmp_path / "risk_accounting_state.json"
    corrupt_path.write_text("not valid json", encoding="utf-8")

    result = bootstrap_financial_state(
        state_directory=tmp_path, initial_capital=D("10000"), policy_version="v1",
        today_utc=date(2026, 1, 1),
    )

    risk_result = result.result_for("risk_accounting_state")
    assert risk_result.outcome is BootstrapOutcome.ALREADY_EXISTS
    assert corrupt_path.read_text(encoding="utf-8") == "not valid json"

    store = JsonRiskStateStore(corrupt_path)
    with pytest.raises(Exception):
        store.load(expected_policy_version="v1", today_utc=date(2026, 1, 1))
