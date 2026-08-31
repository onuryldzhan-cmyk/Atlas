from decimal import Decimal

import pytest

from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest, ExecutionResult
from core.instrument_rules import InstrumentRules, InstrumentRuleset
from data_layer.contracts import IntegrityViolation
from data_layer.projection_replay import ConfirmedExecutionEvidence, replay_confirmed_execution

# A minimal, hermetic stand-in for the real checked-in BTCUSDT rule (Block
# 5D): every request in this file trades BTCUSDT at price 50000.
_BTCUSDT_RULES = InstrumentRuleset({
    "BTCUSDT": InstrumentRules(
        venue="BINANCE", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        quantity_step="0.00001", min_quantity="0.00001", min_notional="5",
        price_tick="0.01", source="test-fixture", source_version="v1",
        retrieved_at="2026-01-01T00:00:00Z",
    ),
})


def test_explicit_decimal_contract_preserves_quote_and_base_units():
    result = ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id="exec-1",
        order_id="order-1", position_id="position-1", symbol="BTCUSDT",
        action="BUY", filled_price=50000, filled_amount=1000,
        requested_quote_allocation=Decimal("1000"),
        filled_base_quantity=Decimal("1000") / Decimal("50000"),
        filled_quote_notional=Decimal("1000"), fee_amount=Decimal("0"),
    )
    payload = result.to_dict()
    assert payload["filled_base_quantity"] == "0.02"
    assert payload["filled_quote_notional"] == "1000"
    assert payload["filled_amount"] == 1000.0
    assert payload["execution_id"] == "exec-1"


def test_canonical_paper_flow_emits_stable_order_and_authoritative_position_identity(monkeypatch):
    manager = ExecutionManager(audit_enabled=False, instrument_rules=_BTCUSDT_RULES)
    # The committed quote allocation is the canonical approved Decimal on the
    # request. There is no separate allocation step left to stand in for, and
    # `amount` is only its lossy mirror.
    monkeypatch.setattr(manager, "_paper_open_trade", lambda **kwargs: {"success": True})
    monkeypatch.setattr(manager, "_position_open", lambda **kwargs: {"success": True, "position_id": "position-1"})
    monkeypatch.setattr(manager, "publish", lambda *args, **kwargs: None)
    request = ExecutionRequest("BTCUSDT", "BUY", 50000, 1000, request_id="req-stable",
                               approved_quote_allocation=Decimal("1000"))
    manager._risk_admissions[request.request_id] = manager._risk_admission_key(request)
    first = manager.paper_execute(request)
    second = manager.paper_execute(request)
    # Block 5D: flooring now derives from the venue quantity_step (via
    # floor_to_step) rather than always quantizing to a fixed 8dp quantum, so
    # the exact zero-padding of the serialized string is no longer a fixed
    # width - only the value is a stable contract.
    assert Decimal(first["filled_base_quantity"]) == Decimal("0.02")
    assert Decimal(first["filled_quote_notional"]) == Decimal("1000")
    assert first["filled_amount"] == 1000.0
    assert first["execution_id"]
    assert first["order_id"] == second["order_id"]
    assert first["order_id"].startswith("paper-order:")
    assert first["position_id"] == "position-1"


def test_paper_flow_preserves_authoritative_order_identity(monkeypatch):
    manager = ExecutionManager(audit_enabled=False, instrument_rules=_BTCUSDT_RULES)
    monkeypatch.setattr(manager, "_paper_open_trade", lambda **kwargs: {"success": True, "order_id": "engine-order-7"})
    monkeypatch.setattr(manager, "_position_open", lambda **kwargs: None)
    monkeypatch.setattr(manager, "publish", lambda *args, **kwargs: None)
    request = ExecutionRequest("BTCUSDT", "BUY", 50000, 1000, request_id="req-1",
                               approved_quote_allocation=Decimal("1000"))
    manager._risk_admissions[request.request_id] = manager._risk_admission_key(request)
    result = manager.paper_execute(request)
    assert result["order_id"] == "engine-order-7"


def test_paper_buy_without_a_canonical_approval_cannot_execute(monkeypatch):
    """An admission token is not an approval: the Decimal has to be there."""
    manager = ExecutionManager(audit_enabled=False)
    monkeypatch.setattr(manager, "_paper_open_trade", lambda **kwargs: {"success": True})
    monkeypatch.setattr(manager, "publish", lambda *args, **kwargs: None)
    request = ExecutionRequest("BTCUSDT", "BUY", 50000, 1000, request_id="req-unapproved")
    manager._risk_admissions[request.request_id] = manager._risk_admission_key(request)
    result = manager.paper_execute(request)
    assert result["success"] is False
    assert result["error_code"] == "CANONICAL_ALLOCATION_MISSING"


def test_completed_retry_preserves_all_canonical_identities():
    class Store:
        completed_requests = {}
        def record(self, key, value, save=True):
            self.completed_requests[key] = dict(value)
            return True
    manager = ExecutionManager(idempotency_store=Store(), audit_enabled=False)
    request = ExecutionRequest("BTCUSDT", "BUY", 50000, 1000, request_id="retry-1")
    assert manager._claim_request(request) is None
    original = {"success": True, "status": "FILLED", "execution_id": "exec-1", "order_id": "order-1", "position_id": "position-1"}
    assert manager._complete_request(request_id=request.request_id, result=original)
    retry = manager._claim_request(request)
    assert (retry["execution_id"], retry["order_id"], retry["position_id"]) == ("exec-1", "order-1", "position-1")


@pytest.mark.parametrize("price,quantity,notional", [
    (Decimal("0"), Decimal("0.02"), Decimal("1000")),
    (Decimal("50000"), Decimal("0"), Decimal("1000")),
    (Decimal("50000"), Decimal("-0.02"), Decimal("1000")),
    (Decimal("50000"), Decimal("0.02"), Decimal("999")),
])
def test_replay_fails_closed_for_invalid_or_inconsistent_units(storage, price, quantity, notional):
    with pytest.raises((IntegrityViolation, ValueError)):
        replay_confirmed_execution(storage, ConfirmedExecutionEvidence(
            request_id="req-1", order_id="order-1", execution_id="exec-1",
            symbol="BTCUSDT", side="BUY", base_quantity=quantity,
            filled_quote_notional=notional, price=price, fee=Decimal("0"),
            executed_at="2026-08-09T00:00:00+00:00", position_id="position-1",
        ))


@pytest.fixture
def storage(tmp_path):
    from data_layer.sqlite import SQLiteStorage
    backend = SQLiteStorage(tmp_path / "contract.sqlite3"); backend.open()
    yield backend
    backend.close()
