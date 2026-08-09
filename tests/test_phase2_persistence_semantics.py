from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

from data_layer.contracts import IntegrityViolation
from data_layer.legacy_migration import dry_run_legacy_records
from data_layer.semantic_contracts import (
    OrderState, PositionPersistenceDTO, RecoveryAction,
    startup_recovery_action, validate_order_transition,
)


def test_order_lifecycle_allowed_invalid_terminal_and_duplicate() -> None:
    assert validate_order_transition(OrderState.NEW, OrderState.ACCEPTED)
    assert validate_order_transition(OrderState.ACCEPTED, OrderState.PARTIALLY_FILLED)
    assert validate_order_transition(OrderState.PARTIALLY_FILLED, OrderState.FILLED)
    assert validate_order_transition(OrderState.ACCEPTED, OrderState.ACCEPTED) is False
    with pytest.raises(ValueError):
        validate_order_transition(OrderState.FILLED, OrderState.CANCELLED)
    with pytest.raises(ValueError):
        validate_order_transition(OrderState.NEW, OrderState.FILLED)


def test_position_units_precision_and_long_only_contract() -> None:
    dto = PositionPersistenceDTO("p-1", "btcusdt", Decimal("0.123456789123456789"),
        Decimal("12.345678912345678900"), Decimal("100"), Decimal("0"), "OPEN",
        "2026-08-09T00:00:00Z")
    assert dto.base_quantity == Decimal("0.123456789123456789")
    assert dto.quote_exposure == Decimal("12.345678912345678900")
    with pytest.raises((ValueError, IntegrityViolation)):
        PositionPersistenceDTO("p-2", "BTCUSDT", Decimal("-1"), Decimal("1"), Decimal("1"), Decimal("0"), "OPEN", "2026-08-09T00:00:00Z")
    with pytest.raises(ValueError):
        PositionPersistenceDTO("p-3", "BTCUSDT", Decimal("1"), Decimal("100"), Decimal("100"), Decimal("0"), "OPEN", "2026-08-09T00:00:00Z", "SHORT")


def test_closed_and_partial_close_projection_semantics() -> None:
    partial = PositionPersistenceDTO("p-1", "BTCUSDT", Decimal("0.4"), Decimal("40"), Decimal("100"), Decimal("2.5"), "OPEN", "2026-08-09T00:00:00Z")
    assert partial.status == "OPEN"
    closed = PositionPersistenceDTO("p-1", "BTCUSDT", Decimal("0"), Decimal("0"), Decimal("100"), Decimal("5"), "CLOSED", "2026-08-09T00:00:01Z")
    assert closed.base_quantity == 0


@pytest.mark.parametrize("kwargs,expected", [
    ({"journal_valid": True, "unresolved_journal": True, "idempotency_valid": True, "relational_valid": True, "sources_agree": True}, RecoveryAction.RECONCILE),
    ({"journal_valid": True, "unresolved_journal": False, "idempotency_valid": True, "relational_valid": False, "sources_agree": True}, RecoveryAction.FAIL_CLOSED),
    ({"journal_valid": True, "unresolved_journal": False, "idempotency_valid": True, "relational_valid": True, "sources_agree": False}, RecoveryAction.RECONCILE),
])
def test_recovery_never_blindly_retries_or_falls_back_empty(kwargs, expected) -> None:
    assert startup_recovery_action(**kwargs) is expected


def test_domain_migration_is_deterministic_read_only_and_validates(tmp_path) -> None:
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps({"orders": [
        {"id": "o-2", "symbol": "ethusdt", "quantity": "2.50", "price": "10", "created_at": "2026-08-09T00:00:00Z"},
        {"id": "o-1", "symbol": "btcusdt", "quantity": "bad", "created_at": "bad"},
        {"id": "o-2", "symbol": "ethusdt", "quantity": "2", "created_at": "2026-08-09T00:00:00Z"},
    ]}, sort_keys=True), encoding="utf-8")
    before = source.read_bytes()
    first = dry_run_legacy_records(source, "orders")
    second = dry_run_legacy_records(source, "orders")
    assert first == second
    assert first["migration_state"] == "MIGRATION_BLOCKED"
    assert first["accepted"][0]["id"] == "o-2"
    assert len(first["rejected"]) == 2
    assert source.read_bytes() == before
    assert first["source_sha256"] == hashlib.sha256(before).hexdigest().upper()
    assert first["database_writes"] == 0


def test_ambiguous_legacy_schema_is_machine_blocked(tmp_path) -> None:
    source = tmp_path / "legacy.json"
    source.write_text('{"history": []}', encoding="utf-8")
    assert dry_run_legacy_records(source, "positions")["blocked_reason"] == "DOMAIN_SCHEMA_AMBIGUOUS"
