"""
P0 regression tests for Atlas sensitive-data output boundaries.

These tests intentionally describe the required secure behavior.
They must fail before the production remediation is applied.
"""

from __future__ import annotations

import json

from typing import Any

from ai.core.atlas_reasoning_engine import (
    ConfidenceLevel,
    Decision,
    DecisionType,
    ReasoningStep,
)
from atlas_os import (
    AuditLogService,
    EventBusService,
)
from core.audit_event import AuditEvent
from core.decision_adapter import DecisionAdapter
from core.execution_idempotency_store import (
    ExecutionIdempotencyStore,
)
from core.execution_manager import ExecutionManager
from core.market_loop import MarketLoop


SECRET_VALUE = (
    "atlas-p0-secret-"
    "74f9d33c9c9a4ab0"
)

EMAIL_VALUE = (
    "atlas.private.user"
    "@example.test"
)

IBAN_VALUE = (
    "TR330006100519786457841326"
)

PRIVATE_KEY_VALUE = (
    "-----BEGIN PRIVATE KEY-----"
    "ATLAS-P0-PRIVATE-MATERIAL"
    "-----END PRIVATE KEY-----"
)

SENSITIVE_VALUES = (
    SECRET_VALUE,
    EMAIL_VALUE,
    IBAN_VALUE,
    PRIVATE_KEY_VALUE,
)


class LeakyObject:
    def __init__(self) -> None:
        self.credential = SECRET_VALUE
        self.customer_email = EMAIL_VALUE

    def __repr__(self) -> str:
        return (
            "LeakyObject("
            f"token={SECRET_VALUE},"
            f"iban={IBAN_VALUE}"
            ")"
        )


class CurrentContractSpyBus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def publish(
        self,
        event_payload: Any,
    ) -> None:
        self.events.append(
            event_payload
        )


class LegacyContractSpyBus:
    def __init__(self) -> None:
        self.events: list[
            tuple[str, Any]
        ] = []

    def publish(
        self,
        event_name: str,
        payload: Any,
    ) -> None:
        self.events.append(
            (
                event_name,
                payload,
            )
        )


def _serialize(
    value: Any,
) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _assert_sensitive_values_absent(
    value: Any,
) -> str:
    serialized = _serialize(
        value
    )

    for sensitive_value in SENSITIVE_VALUES:
        assert sensitive_value not in serialized

    return serialized


def _sensitive_payload() -> dict[str, Any]:
    return {
        "public_value": "safe-public-value",
        "api_key": SECRET_VALUE,
        "owner_email": EMAIL_VALUE,
        "iban": IBAN_VALUE,
        "nested": {
            "authorization": (
                f"Bearer {SECRET_VALUE}"
            ),
            "private_key": (
                PRIVATE_KEY_VALUE
            ),
        },
        "evidence": [
            (
                "Market observation is valid."
            ),
            (
                "Contact analyst at "
                f"{EMAIL_VALUE}"
            ),
            (
                "credential="
                f"{SECRET_VALUE}"
            ),
        ],
    }


def test_decision_adapter_redacts_sensitive_metadata() -> None:
    result = DecisionAdapter.convert(
        {
            "action": "BUY",
            "symbol": "BTCUSDT",
            "confidence": 90.0,
            "price": 65000.0,
            "strategy": "P0_SECURITY_TEST",
            "risk_level": "LOW",
            "metadata": _sensitive_payload(),
        }
    )

    assert result is not None
    assert (
        result["metadata"]["public_value"]
        == "safe-public-value"
    )

    _assert_sensitive_values_absent(
        result
    )


def test_reasoning_evidence_and_risk_assessment_are_redacted() -> None:
    decision = Decision(
        decision_type=DecisionType.BUY,
        symbol="BTCUSDT",
        confidence=90.0,
        reasoning_steps=[
            ReasoningStep(
                step_id=1,
                description=(
                    "P0 security reasoning step"
                ),
                evidence=[
                    (
                        "Authorization: Bearer "
                        f"{SECRET_VALUE}"
                    ),
                    (
                        "Analyst email: "
                        f"{EMAIL_VALUE}"
                    ),
                    (
                        "Settlement IBAN: "
                        f"{IBAN_VALUE}"
                    ),
                    PRIVATE_KEY_VALUE,
                ],
                confidence=(
                    ConfidenceLevel.HIGH
                ),
            )
        ],
        risk_assessment={
            "risk_level": "LOW",
            "customer_email": EMAIL_VALUE,
            "bank_account": IBAN_VALUE,
            "token": SECRET_VALUE,
        },
    )

    result = decision.to_dict()

    assert result["symbol"] == "BTCUSDT"

    _assert_sensitive_values_absent(
        result
    )


def test_core_audit_event_redacts_nested_payload_metadata_and_objects() -> None:
    event = AuditEvent.create(
        event_type="P0_SECURITY_EVENT",
        source="SecurityTest",
        aggregate_type="security",
        aggregate_id="p0-001",
        payload={
            **_sensitive_payload(),
            "custom_object": LeakyObject(),
        },
        metadata={
            "account_number": IBAN_VALUE,
            "contact": EMAIL_VALUE,
            "password": SECRET_VALUE,
        },
    )

    result = event.to_dict()

    assert (
        result["payload"]["public_value"]
        == "safe-public-value"
    )

    _assert_sensitive_values_absent(
        result
    )


def test_event_bus_and_audit_log_never_retain_or_persist_sensitive_values(
    tmp_path,
) -> None:
    audit_file = (
        tmp_path
        / "atlas_sensitive_audit.jsonl"
    )

    event_bus = EventBusService(
        history_limit=10
    )

    audit = AuditLogService(
        event_bus,
        audit_file=audit_file,
        history_limit=10,
        rotation_size_bytes=1_000_000,
    )

    event_bus.start()
    audit.start()

    try:
        event_bus.publish_event(
            event_type="P0_SECURITY_EVENT",
            source="SecurityTest",
            payload=_sensitive_payload(),
        )

        history = event_bus.event_history()

        assert len(history) == 1
        assert (
            history[0]
            .payload["public_value"]
            == "safe-public-value"
        )

        _assert_sensitive_values_absent(
            dict(
                history[0].payload
            )
        )

        persisted_text = audit_file.read_text(
            encoding="utf-8"
        )

        for sensitive_value in SENSITIVE_VALUES:
            assert (
                sensitive_value
                not in persisted_text
            )

        assert (
            "safe-public-value"
            in persisted_text
        )

    finally:
        if audit.is_running:
            audit.stop()

        if event_bus.is_running:
            event_bus.stop()


def test_execution_manager_current_publish_contract_is_sanitized() -> None:
    event_bus = CurrentContractSpyBus()

    manager = ExecutionManager.__new__(
        ExecutionManager
    )

    manager.event_bus = event_bus

    published = manager.publish(
        "P0_SECURITY_EVENT",
        _sensitive_payload(),
    )

    assert published is True
    assert len(event_bus.events) == 1

    _assert_sensitive_values_absent(
        event_bus.events[0]
    )


def test_execution_manager_legacy_publish_contract_is_sanitized() -> None:
    event_bus = LegacyContractSpyBus()

    manager = ExecutionManager.__new__(
        ExecutionManager
    )

    manager.event_bus = event_bus

    published = manager.publish(
        "P0_SECURITY_EVENT",
        _sensitive_payload(),
    )

    assert published is True
    assert len(event_bus.events) == 1

    event_name, payload = (
        event_bus.events[0]
    )

    assert (
        event_name
        == "P0_SECURITY_EVENT"
    )

    _assert_sensitive_values_absent(
        payload
    )


def test_market_loop_current_publish_contract_is_sanitized() -> None:
    event_bus = CurrentContractSpyBus()

    market_loop = MarketLoop.__new__(
        MarketLoop
    )

    market_loop.event_bus = event_bus

    published = market_loop.publish(
        "P0_SECURITY_EVENT",
        _sensitive_payload(),
    )

    assert published is True
    assert len(event_bus.events) == 1

    _assert_sensitive_values_absent(
        event_bus.events[0]
    )


def test_market_loop_legacy_publish_contract_is_sanitized() -> None:
    event_bus = LegacyContractSpyBus()

    market_loop = MarketLoop.__new__(
        MarketLoop
    )

    market_loop.event_bus = event_bus

    published = market_loop.publish(
        "P0_SECURITY_EVENT",
        _sensitive_payload(),
    )

    assert published is True
    assert len(event_bus.events) == 1

    event_name, payload = (
        event_bus.events[0]
    )

    assert (
        event_name
        == "P0_SECURITY_EVENT"
    )

    _assert_sensitive_values_absent(
        payload
    )


def test_execution_idempotency_serialization_is_fail_closed() -> None:
    result = (
        ExecutionIdempotencyStore
        ._safe_payload(
            {
                **_sensitive_payload(),
                "custom_object": LeakyObject(),
            }
        )
    )

    assert (
        result["public_value"]
        == "safe-public-value"
    )

    _assert_sensitive_values_absent(
        result
    )


def test_sensitive_guard_preserves_safe_trading_values() -> None:
    from atlas_security import sanitize_sensitive_mapping

    payload = {
        "symbol": "BTCUSDT",
        "price": 65000.0,
        "balance": 10000.0,
        "risk_level": "LOW",
        "note": "safe-public-value",
    }

    assert sanitize_sensitive_mapping(payload) == payload


def test_sensitive_guard_handles_cycles_fail_closed() -> None:
    from atlas_security import sanitize_sensitive_mapping

    payload = {
        "public_value": "safe-public-value",
    }
    payload["self"] = payload

    result = sanitize_sensitive_mapping(payload)

    assert result["public_value"] == "safe-public-value"
    assert result["self"] == "[REDACTED_CYCLE]"

    json.dumps(result)


def test_sensitive_guard_redacts_embedded_card_and_credentials() -> None:
    from atlas_security import sanitize_sensitive_text

    card_number = "4111111111111111"
    password_value = "Atlas-P0-Password-Value"

    value = (
        f"email={EMAIL_VALUE}; "
        f"card={card_number}; "
        f"password={password_value}; "
        f"iban={IBAN_VALUE}"
    )

    result = sanitize_sensitive_text(value)

    assert EMAIL_VALUE not in result
    assert card_number not in result
    assert password_value not in result
    assert IBAN_VALUE not in result


def test_legacy_core_event_serialization_is_sanitized() -> None:
    from core.events import (
        AtlasEvent as LegacyAtlasEvent,
        EventType,
    )

    event = LegacyAtlasEvent(
        event_type=EventType.DECISION_CREATED,
        source="SecurityTest",
        payload=_sensitive_payload(),
    )

    result = event.to_dict()

    assert result["payload"]["public_value"] == "safe-public-value"

    _assert_sensitive_values_absent(result)


def test_audit_record_from_dict_sanitizes_legacy_payload() -> None:
    from atlas_os.audit.audit_log import AuditRecord

    timestamp = "2026-07-31T11:00:00+00:00"

    record = AuditRecord.from_dict(
        {
            "schema_version": "1.0",
            "audit_id": "audit-1",
            "event_id": "event-1",
            "event_type": "P0_SECURITY_EVENT",
            "source": "SecurityTest",
            "severity": "INFO",
            "correlation_id": None,
            "payload": _sensitive_payload(),
            "event_created_at": timestamp,
            "recorded_at": timestamp,
        }
    )

    assert record.payload["public_value"] == "safe-public-value"

    _assert_sensitive_values_absent(record.to_dict())
