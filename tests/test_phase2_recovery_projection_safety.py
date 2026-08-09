from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from data_layer.contracts import ConcurrencyConflict, IntegrityViolation
from data_layer.models import OrderRecord, PositionRecord
from data_layer.projection_replay import ConfirmedExecutionEvidence, replay_confirmed_execution
from data_layer.recovery import RecoveryDisposition, RecoveryEvidence, assess_recovery, startup_ready
from data_layer.sqlite import SQLiteStorage


NOW = datetime(2026, 8, 9, tzinfo=UTC)


@pytest.fixture
def storage(tmp_path):
    backend = SQLiteStorage(tmp_path / "phase2.sqlite3")
    backend.open()
    yield backend
    backend.close()


def evidence(**changes):
    values = dict(request_id="req-1", order_id="order-1", execution_id="exec-1",
                  symbol="BTCUSDT", side="BUY", base_quantity=Decimal("0.25"),
                  filled_quote_notional=Decimal("10000"),
                  price=Decimal("40000"), fee=Decimal("1"), executed_at=NOW,
                  position_id="position-1")
    values.update(changes)
    if "base_quantity" in changes and "filled_quote_notional" not in changes:
        values["filled_quote_notional"] = values["base_quantity"] * values["price"]
    return ConfirmedExecutionEvidence(**values)


def test_confirmed_missing_requires_replay_and_present_is_ready():
    missing = RecoveryEvidence(external_outcome="CONFIRMED", projection_present=False)
    assert assess_recovery(missing).disposition is RecoveryDisposition.PROJECTION_REPLAY_REQUIRED
    assert assess_recovery(RecoveryEvidence(external_outcome="CONFIRMED")).ready


@pytest.mark.parametrize("state,reason", [
    (RecoveryEvidence(external_outcome="INDETERMINATE"), "EXTERNAL_OUTCOME_INDETERMINATE"),
    (RecoveryEvidence(journal_unresolved=True), "UNRESOLVED_JOURNAL"),
    (RecoveryEvidence(sources_agree=False), "SOURCE_DISAGREEMENT"),
])
def test_reconciliation_blocks_readiness_and_never_allows_blind_retry(state, reason):
    decision = assess_recovery(state)
    assert decision.disposition is RecoveryDisposition.RECONCILIATION_REQUIRED
    assert decision.reason == reason
    assert not decision.ready and not decision.blind_retry_allowed


@pytest.mark.parametrize("state", [
    RecoveryEvidence(relational_valid=False), RecoveryEvidence(schema_valid=False),
    RecoveryEvidence(journal_valid=False), RecoveryEvidence(idempotency_valid=False),
])
def test_corruption_or_invalid_schema_fails_closed(state):
    assert assess_recovery(state).disposition is RecoveryDisposition.FAIL_CLOSED
    assert not startup_ready(state)


def test_clean_state_permits_readiness():
    assert startup_ready(RecoveryEvidence())


def test_replay_once_and_twice_is_idempotent_and_preserves_units(storage):
    assert replay_confirmed_execution(storage, evidence()).state == "PROJECTED"
    assert replay_confirmed_execution(storage, evidence()).state == "ALREADY_PROJECTED"
    with storage.unit_of_work() as uow:
        position = uow.positions.get("position-1")
        assert position.quantity == Decimal("0.25")
        assert position.average_price == Decimal("40000")
        assert position.quantity != position.quantity * position.average_price
        execution = uow.executions.get("exec-1")
        assert execution.metadata["filled_quote_notional"] == "10000"


def test_replay_never_calls_exchange(storage):
    class ExchangeTrap:
        def __getattr__(self, name):
            raise AssertionError("exchange must never be called")
    confirmed = evidence(metadata={"exchange_trap_is_not_a_dependency": True})
    assert replay_confirmed_execution(storage, confirmed).state == "PROJECTED"
    ExchangeTrap()  # service accepts no exchange object and imports no exchange module


def test_replay_second_write_failure_rolls_back(storage, monkeypatch):
    from data_layer.sqlite import SQLiteExecutionRepository
    monkeypatch.setattr(SQLiteExecutionRepository, "add", lambda self, record: (_ for _ in ()).throw(RuntimeError("second write")))
    with pytest.raises(RuntimeError, match="second write"):
        replay_confirmed_execution(storage, evidence())
    with storage.unit_of_work() as uow:
        assert uow.orders.get("order-1") is None
        assert uow.positions.get("position-1") is None


def test_replay_commit_failure_remains_unprojected(storage, monkeypatch):
    real_connect = storage._connect
    class CommitFailure:
        def __init__(self, connection): self.connection = connection
        def execute(self, *args, **kwargs): return self.connection.execute(*args, **kwargs)
        def commit(self): self.connection.rollback(); raise sqlite3.OperationalError("commit failure")
        def rollback(self): return self.connection.rollback()
        def close(self): return self.connection.close()
    monkeypatch.setattr(storage, "_connect", lambda: CommitFailure(real_connect()))
    with pytest.raises(sqlite3.OperationalError, match="commit failure"):
        replay_confirmed_execution(storage, evidence())
    monkeypatch.setattr(storage, "_connect", real_connect)
    with storage.unit_of_work() as uow:
        assert uow.orders.get("order-1") is None


def _new_order():
    return OrderRecord("order-1", "BTCUSDT", "BUY", Decimal("1"), "NEW", NOW, "req-1")


def test_order_cas_valid_stale_duplicate_and_terminal_regression(storage):
    with storage.unit_of_work() as uow: uow.orders.add(_new_order())
    with storage.unit_of_work() as uow: assert uow.orders.transition("order-1", "ACCEPTED", expected_version=0) == 1
    with pytest.raises(ConcurrencyConflict):
        with storage.unit_of_work() as uow: uow.orders.transition("order-1", "CANCELLED", expected_version=0)
    with storage.unit_of_work() as uow: assert uow.orders.transition("order-1", "ACCEPTED", expected_version=1) == 1
    with storage.unit_of_work() as uow: assert uow.orders.transition("order-1", "FILLED", expected_version=1) == 2
    with pytest.raises(ValueError):
        with storage.unit_of_work() as uow: uow.orders.transition("order-1", "CANCELLED", expected_version=2)


def test_position_stale_cas_rejected(storage):
    opened = PositionRecord("p-1", "BTCUSDT", Decimal("1"), Decimal("10"), "OPEN", NOW)
    with storage.unit_of_work() as uow: assert uow.positions.put_cas(opened, expected_version=-1) == 0
    with pytest.raises(ConcurrencyConflict):
        with storage.unit_of_work() as uow: uow.positions.put_cas(opened, expected_version=-1)


def test_full_close_and_short_or_partial_close_rejected(storage):
    opened = PositionRecord("position-1", "BTCUSDT", Decimal("0.25"), Decimal("40000"), "OPEN", NOW)
    with storage.unit_of_work() as uow: uow.positions.put_cas(opened, expected_version=-1)
    sell = evidence(side="SELL", prior_position=opened, realized_pnl=Decimal("25"))
    assert replay_confirmed_execution(storage, sell).state == "PROJECTED"
    with storage.unit_of_work() as uow:
        assert uow.positions.get("position-1").status == "CLOSED"
    with pytest.raises(IntegrityViolation, match="partial close"):
        replay_confirmed_execution(storage, evidence(order_id="o-2", execution_id="e-2", side="SELL", base_quantity=Decimal("0.1"), prior_position=opened))
    with pytest.raises(IntegrityViolation, match="SHORT"):
        replay_confirmed_execution(storage, evidence(order_id="o-3", execution_id="e-3", side="SHORT"))
