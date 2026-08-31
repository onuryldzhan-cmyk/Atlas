"""Block 3 / Package 2, M-C: EXISTS is not VALID.

`bootstrap_financial_state` must load and validate an existing store through
that store's own canonical loader rather than reporting success merely
because a path exists. Covers the 3-store matrix from the Package-2 Phase-1
investigation: risk_accounting_state, capital_reservations,
execution_financial_state, each across {absent, valid, corrupt, zero-byte,
wrong-schema, semantically-invalid / policy-incompatible}.

Every INVALID_EXISTING case additionally proves the file was left
byte-for-byte untouched (no repair, no overwrite, no delete).
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal as D

import pytest

from core.financial_state_bootstrap import (
    BootstrapOutcome,
    bootstrap_financial_state,
)

TODAY = date(2026, 1, 1)


def _bootstrap(tmp_path, **overrides):
    kwargs = dict(
        state_directory=tmp_path, initial_capital=D("10000"),
        allocatable_capital=D("8000"), policy_version="v1", today_utc=TODAY,
    )
    kwargs.update(overrides)
    return bootstrap_financial_state(**kwargs)


def _seed_valid(tmp_path):
    result = _bootstrap(tmp_path)
    assert result.succeeded
    return result


# ---------------------------------------------------------------------------
# risk_accounting_state
# ---------------------------------------------------------------------------


def test_risk_state_absent_is_created(tmp_path):
    result = _bootstrap(tmp_path)
    risk = result.result_for("risk_accounting_state")
    assert risk.outcome is BootstrapOutcome.CREATED
    assert risk.reason_code == "BOOTSTRAP_CREATED"


def test_risk_state_valid_existing_is_reported_and_untouched(tmp_path):
    _seed_valid(tmp_path)
    path = tmp_path / "risk_accounting_state.json"
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    risk = result.result_for("risk_accounting_state")
    assert risk.outcome is BootstrapOutcome.VALID_EXISTING
    assert risk.reason_code == "STATE_VALID_EXISTING"
    assert path.read_bytes() == before


def test_risk_state_corrupt_json_is_invalid_existing_and_untouched(tmp_path):
    path = tmp_path / "risk_accounting_state.json"
    path.write_text("not valid json", encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    risk = result.result_for("risk_accounting_state")
    assert risk.outcome is BootstrapOutcome.INVALID_EXISTING
    assert risk.reason_code == "RISK_STATE_UNREADABLE"
    assert path.read_bytes() == before
    assert result.succeeded is False


def test_risk_state_zero_byte_is_invalid_existing_and_untouched(tmp_path):
    path = tmp_path / "risk_accounting_state.json"
    path.write_text("", encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    risk = result.result_for("risk_accounting_state")
    assert risk.outcome is BootstrapOutcome.INVALID_EXISTING
    assert risk.reason_code == "RISK_STATE_UNREADABLE"
    assert path.read_bytes() == before


def test_risk_state_wrong_schema_is_invalid_existing_and_untouched(tmp_path):
    path = tmp_path / "risk_accounting_state.json"
    path.write_text(json.dumps({"schema": "not-the-real-schema"}), encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    risk = result.result_for("risk_accounting_state")
    assert risk.outcome is BootstrapOutcome.INVALID_EXISTING
    assert risk.reason_code == "RISK_STATE_SCHEMA_INVALID"
    assert path.read_bytes() == before


def test_risk_state_policy_version_mismatch_is_invalid_existing_and_untouched(tmp_path):
    _seed_valid(tmp_path)
    path = tmp_path / "risk_accounting_state.json"
    before = path.read_bytes()

    result = _bootstrap(tmp_path, policy_version="a-different-policy-version")
    risk = result.result_for("risk_accounting_state")
    assert risk.outcome is BootstrapOutcome.INVALID_EXISTING
    assert risk.reason_code == "POLICY_VERSION_MISMATCH"
    assert path.read_bytes() == before
    assert result.succeeded is False


def test_risk_state_future_accounting_day_is_invalid_existing_and_untouched(tmp_path):
    from core.risk_state_store import JsonRiskStateStore, RestoredRiskState

    path = tmp_path / "risk_accounting_state.json"
    JsonRiskStateStore(path).initialize(
        RestoredRiskState(
            accounting_day_utc=date(2026, 6, 1), realized_daily_pnl=D("0"),
            peak_equity=D("10000"), current_equity=D("10000"), policy_version="v1",
        )
    )
    before = path.read_bytes()

    result = _bootstrap(tmp_path, today_utc=date(2026, 1, 1))
    risk = result.result_for("risk_accounting_state")
    assert risk.outcome is BootstrapOutcome.INVALID_EXISTING
    assert risk.reason_code == "RISK_STATE_FUTURE_DAY"
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# capital_reservations
# ---------------------------------------------------------------------------


def test_reservation_state_absent_is_created(tmp_path):
    result = _bootstrap(tmp_path)
    reservation = result.result_for("capital_reservations")
    assert reservation.outcome is BootstrapOutcome.CREATED


def test_reservation_state_valid_existing_is_reported_and_untouched(tmp_path):
    _seed_valid(tmp_path)
    path = tmp_path / "capital_reservations.json"
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    reservation = result.result_for("capital_reservations")
    assert reservation.outcome is BootstrapOutcome.VALID_EXISTING
    assert path.read_bytes() == before


def test_reservation_state_corrupt_json_is_invalid_existing_and_untouched(tmp_path):
    path = tmp_path / "capital_reservations.json"
    path.write_text("not valid json", encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    reservation = result.result_for("capital_reservations")
    assert reservation.outcome is BootstrapOutcome.INVALID_EXISTING
    assert reservation.reason_code == "RESERVATION_STATE_UNREADABLE"
    assert path.read_bytes() == before


def test_reservation_state_zero_byte_is_invalid_existing_and_untouched(tmp_path):
    path = tmp_path / "capital_reservations.json"
    path.write_text("", encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    reservation = result.result_for("capital_reservations")
    assert reservation.outcome is BootstrapOutcome.INVALID_EXISTING
    assert reservation.reason_code == "RESERVATION_STATE_UNREADABLE"
    assert path.read_bytes() == before


def test_reservation_state_wrong_schema_is_invalid_existing_and_untouched(tmp_path):
    path = tmp_path / "capital_reservations.json"
    path.write_text(json.dumps({"schema": "wrong", "reservations": []}), encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    reservation = result.result_for("capital_reservations")
    assert reservation.outcome is BootstrapOutcome.INVALID_EXISTING
    assert reservation.reason_code == "RESERVATION_SCHEMA_INVALID"
    assert path.read_bytes() == before


def test_reservation_state_encumbered_exceeding_allocatable_is_invalid_existing(tmp_path):
    from core.capital_reservation import CapitalReservation, JsonReservationStore, ReservationStatus

    path = tmp_path / "capital_reservations.json"
    JsonReservationStore(path).save((
        CapitalReservation(
            reservation_id="r1", request_id="req-1", amount=D("9000"),
            status=ReservationStatus.RESERVED,
        ),
    ))
    before = path.read_bytes()

    # allocatable_capital of 8000 cannot cover a 9000 encumbrance already on disk.
    result = _bootstrap(tmp_path, allocatable_capital=D("8000"))
    reservation = result.result_for("capital_reservations")
    assert reservation.outcome is BootstrapOutcome.INVALID_EXISTING
    assert reservation.reason_code == "CAPITAL_MISMATCH"
    assert path.read_bytes() == before
    assert result.succeeded is False


def test_reservation_state_duplicate_reservation_id_is_invalid_existing(tmp_path):
    path = tmp_path / "capital_reservations.json"
    payload = {
        "schema": "atlas-capital-reservations-v2",
        "reservations": [
            {"reservation_id": "dup", "request_id": "req-1", "amount": "100",
             "status": "RESERVED"},
            {"reservation_id": "dup", "request_id": "req-2", "amount": "100",
             "status": "RESERVED"},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    reservation = result.result_for("capital_reservations")
    assert reservation.outcome is BootstrapOutcome.INVALID_EXISTING
    assert reservation.reason_code == "RESERVATION_DUPLICATE_ID"
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# execution_financial_state
# ---------------------------------------------------------------------------


def test_financial_state_absent_is_created(tmp_path):
    result = _bootstrap(tmp_path)
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.CREATED


def test_financial_state_valid_existing_is_reported_and_untouched(tmp_path):
    _seed_valid(tmp_path)
    path = tmp_path / "execution_financial_state.json"
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.VALID_EXISTING
    assert path.read_bytes() == before


def test_financial_state_corrupt_json_is_invalid_existing_and_untouched(tmp_path):
    path = tmp_path / "execution_financial_state.json"
    path.write_text("not valid json", encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.INVALID_EXISTING
    assert financial.reason_code == "FINANCIAL_STATE_RECOVERY_REQUIRED"
    assert path.read_bytes() == before


def test_financial_state_zero_byte_is_invalid_existing_and_untouched(tmp_path):
    path = tmp_path / "execution_financial_state.json"
    path.write_text("", encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.INVALID_EXISTING
    assert financial.reason_code == "FINANCIAL_STATE_RECOVERY_REQUIRED"
    assert path.read_bytes() == before


def test_financial_state_wrong_schema_version_is_invalid_existing(tmp_path):
    path = tmp_path / "execution_financial_state.json"
    path.write_text(json.dumps({
        "schema_version": "not-the-real-version", "transition": None, "cash": "10000",
        "reserved_capital": "0", "realized_gross_pnl": "0", "fees": "0",
        "positions": {}, "closed_positions": {}, "applied_executions": {},
    }), encoding="utf-8")
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.INVALID_EXISTING
    assert financial.reason_code == "FINANCIAL_STATE_RECOVERY_REQUIRED"
    assert path.read_bytes() == before


def test_financial_state_pending_transition_is_invalid_existing(tmp_path):
    from core.execution_portfolio_foundation import FinancialStateStore, SCHEMA_VERSION

    path = tmp_path / "execution_financial_state.json"
    FinancialStateStore(path).save({
        "schema_version": SCHEMA_VERSION, "transition": {"stage": "interrupted"},
        "cash": "10000", "reserved_capital": "0", "realized_gross_pnl": "0", "fees": "0",
        "positions": {}, "closed_positions": {}, "applied_executions": {},
    })
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.INVALID_EXISTING
    assert financial.reason_code == "FINANCIAL_TRANSITION_RECOVERY_REQUIRED"
    assert path.read_bytes() == before


def test_financial_state_negative_cash_is_invalid_existing(tmp_path):
    from core.execution_portfolio_foundation import FinancialStateStore, SCHEMA_VERSION

    path = tmp_path / "execution_financial_state.json"
    FinancialStateStore(path).save({
        "schema_version": SCHEMA_VERSION, "transition": None,
        "cash": "-500", "reserved_capital": "0", "realized_gross_pnl": "0", "fees": "0",
        "positions": {}, "closed_positions": {}, "applied_executions": {},
    })
    before = path.read_bytes()

    result = _bootstrap(tmp_path)
    financial = result.result_for("execution_financial_state")
    assert financial.outcome is BootstrapOutcome.INVALID_EXISTING
    assert financial.reason_code == "FINANCIAL_STATE_INVALID"
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# whole-result semantics
# ---------------------------------------------------------------------------


def test_succeeded_is_true_only_when_every_store_is_created_or_valid_existing(tmp_path):
    result = _bootstrap(tmp_path)
    assert result.succeeded is True
    assert {r.outcome for r in result.results} == {BootstrapOutcome.CREATED}


def test_succeeded_is_false_if_any_single_store_is_invalid_existing(tmp_path):
    _seed_valid(tmp_path)
    (tmp_path / "capital_reservations.json").write_text("corrupt", encoding="utf-8")

    result = _bootstrap(tmp_path)
    assert result.succeeded is False
    assert result.result_for("risk_accounting_state").outcome is BootstrapOutcome.VALID_EXISTING
    assert result.result_for("execution_financial_state").outcome is BootstrapOutcome.VALID_EXISTING
    assert result.result_for("capital_reservations").outcome is BootstrapOutcome.INVALID_EXISTING


def test_all_three_corrupt_at_once_reports_invalid_existing_for_each_and_untouched(tmp_path):
    paths = {
        name: tmp_path / name
        for name in (
            "risk_accounting_state.json",
            "capital_reservations.json",
            "execution_financial_state.json",
        )
    }
    for path in paths.values():
        path.write_text("}{ not json", encoding="utf-8")
    before = {name: path.read_bytes() for name, path in paths.items()}

    result = _bootstrap(tmp_path)

    assert result.succeeded is False
    assert {r.outcome for r in result.results} == {BootstrapOutcome.INVALID_EXISTING}
    for name, path in paths.items():
        assert path.read_bytes() == before[name]
