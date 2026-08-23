from decimal import Decimal
from pathlib import Path

import pytest

from core.capital_reservation import ReservationStatus
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)


class Reservation:
    status = ReservationStatus.RESERVED


class Reservations:
    def get(self, request_id):
        return Reservation()

    def active_reserved_capital(self, *, exclude=None):
        return Decimal("0")


def manager_with(book):
    manager = ExecutionManager.__new__(ExecutionManager)
    manager.portfolio_foundation = book
    manager.reservation_ledger = Reservations()
    manager._risk_admissions = {}
    # Block 5D: _risk_admission_key() (used by _has_risk_admission(), which
    # _finalize_durable_financial_state() calls) now reads this too.
    manager.instrument_rules = None
    return manager


def request():
    # An admitted request carries the engine's approval as an exact Decimal;
    # finalization reconciles the settled notional + fee against it.
    return ExecutionRequest(
        "BTCUSDT", "BUY", 10, 20, confidence=90, request_id="request-1",
        approved_quote_allocation=Decimal("20"),
    )


def confirmed_result():
    return {
        "success": True,
        "status": "PAPER_EXECUTED",
        "execution_id": "execution-1",
        "position_id": "long:BTCUSDT",
        "symbol": "BTCUSDT",
        "action": "BUY",
        "filled_price": 10,
        "filled_base_quantity": "2",
        "filled_quote_notional": "20",
        "fee_amount": "0",
        "timestamp": "2026-08-10T00:00:00+00:00",
    }


def durable_book(tmp_path):
    store = FinancialStateStore(tmp_path / "financial.json")
    store.initialize(Decimal("100"))
    return ExecutionPortfolioFoundation(
        store,
        applied_archive=AppliedExecutionArchiveStore(tmp_path / "financial-applied.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / "financial-closed.jsonl"),
    )


def test_runtime_finalization_updates_durable_position_and_portfolio(tmp_path):
    book = durable_book(tmp_path)
    manager = manager_with(book)
    item = request()
    manager._risk_admissions[item.request_id] = manager._risk_admission_key(item)

    result = confirmed_result()
    snapshot = manager._finalize_durable_financial_state(request=item, result=result)

    assert snapshot["cash"] == Decimal("80")
    assert snapshot["positions"]["BTCUSDT"]["base_quantity"] == "2"
    assert result["provenance_ref"] == "transaction-journal:request-1"


def test_runtime_duplicate_finalization_has_no_double_accounting(tmp_path):
    book = durable_book(tmp_path)
    manager = manager_with(book)
    item = request()
    manager._risk_admissions[item.request_id] = manager._risk_admission_key(item)
    first = manager._finalize_durable_financial_state(
        request=item, result=confirmed_result()
    )
    second = manager._finalize_durable_financial_state(
        request=item, result=confirmed_result()
    )

    assert first["cash"] == second["cash"] == Decimal("80")
    assert second["replayed"] is True


def test_runtime_finalization_cannot_bypass_risk_admission(tmp_path):
    manager = manager_with(durable_book(tmp_path))
    with pytest.raises(PermissionError, match="CANONICAL_RISK_ADMISSION_MISSING"):
        manager._finalize_durable_financial_state(
            request=request(), result=confirmed_result()
        )


def test_runtime_finalization_failure_propagates_and_cannot_be_success(tmp_path):
    class FailingFoundation:
        ready = True

        def set_reserved_capital(self, value):
            pass

        def snapshot(self):
            return {"positions": {}}

        def apply_confirmed(self, *args, **kwargs):
            raise RuntimeError("portfolio persist failed")

    manager = manager_with(FailingFoundation())
    item = request()
    manager._risk_admissions[item.request_id] = manager._risk_admission_key(item)
    with pytest.raises(RuntimeError, match="portfolio persist failed"):
        manager._finalize_durable_financial_state(
            request=item, result=confirmed_result()
        )


def test_corrupt_durable_state_blocks_runtime_readiness(tmp_path):
    path = tmp_path / "financial.json"
    path.write_text("not-json", encoding="utf-8")
    manager = manager_with(ExecutionPortfolioFoundation(
        FinancialStateStore(path),
        applied_archive=AppliedExecutionArchiveStore(tmp_path / "financial-applied.jsonl"),
        closed_archive=ClosedPositionArchiveStore(tmp_path / "financial-closed.jsonl"),
    ))
    ready, reason = manager._durable_financial_ready()
    assert not ready
    assert reason


def test_execution_manager_has_no_sqlite_backend_dependency():
    source = Path(ExecutionManager.__module__.replace(".", "/") + ".py").read_text(
        encoding="utf-8"
    )
    assert "sqlite" not in source.lower()
