"""Task 012 (registry v5.96): the Brain -> MarketLoop decision contract, delta tests only.

Pinned here: the contract's field boundaries (and the JSON Schema document agreeing with them),
the staleness window, and MarketLoop's handling of a broken contract: dropped before any
execution gate, audited, never routed, retried on the next cycle, and a valid decision passed
on unchanged. Risk, regime, sizing and normalization behaviour are covered by their own suites
and are not re-tested here.
"""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

import pytest

from core.brain_decision_contract import (
    MAX_CLOCK_SKEW,
    MAX_DECISION_AGE,
    ACTIONS,
    REQUIRED_FIELDS,
    RISK_LEVELS,
    BrainDecisionPayload,
    ContractViolation,
)
from tests.test_block5c_upstream_sizing_authority import DecidingBrain, application, execution_enabled_loop

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "core" / "brain_decision_payload.schema.json"


def decision(**overrides: Any) -> dict[str, Any]:
    payload = {
        "action": "BUY", "symbol": "BTCUSDT", "confidence": 70.6, "strategy": "Atlas", "risk_level": "MEDIUM",
        "price": 65000.0, "created_at": NOW.isoformat(), "metadata": {},
    }
    payload.update(overrides)
    return payload


def check(payload: Any) -> BrainDecisionPayload:
    return BrainDecisionPayload.from_decision(payload, expected_symbol="BTCUSDT", now=NOW)


# -- the contract ------------------------------------------------------------------------------------


def test_a_valid_decision_becomes_an_immutable_payload_and_is_not_modified():
    source = decision(metadata={"note": "kept"})
    before = copy.deepcopy(source)
    payload = check(source)
    assert source == before
    assert (payload.action, payload.symbol, payload.confidence, payload.price) == ("BUY", "BTCUSDT", 70.6, 65000.0)
    assert payload.created_at == NOW
    with pytest.raises(AttributeError):
        payload.action = "SELL"  # type: ignore[misc]


FIELD_CASES = [
    ("action", "buy", "ACTION_INVALID"), ("action", "TELEPORT", "ACTION_INVALID"), ("action", None, "ACTION_INVALID"),
    ("symbol", "btcusdt", "SYMBOL_INVALID"), ("symbol", " BTCUSDT", "SYMBOL_INVALID"), ("symbol", "", "SYMBOL_INVALID"),
    ("symbol", 7, "SYMBOL_INVALID"),
    ("confidence", -0.01, "CONFIDENCE_INVALID"), ("confidence", 100.01, "CONFIDENCE_INVALID"),
    ("confidence", math.nan, "CONFIDENCE_INVALID"), ("confidence", math.inf, "CONFIDENCE_INVALID"),
    ("confidence", True, "CONFIDENCE_INVALID"), ("confidence", "70", "CONFIDENCE_INVALID"),
    ("strategy", "", "STRATEGY_INVALID"), ("strategy", "   ", "STRATEGY_INVALID"), ("strategy", None, "STRATEGY_INVALID"),
    ("risk_level", "medium", "RISK_LEVEL_INVALID"), ("risk_level", "EXTREME", "RISK_LEVEL_INVALID"),
    ("price", 0, "PRICE_INVALID"), ("price", -1.0, "PRICE_INVALID"), ("price", math.inf, "PRICE_INVALID"),
    ("price", False, "PRICE_INVALID"), ("price", "65000", "PRICE_INVALID"),
    ("metadata", [], "METADATA_INVALID"), ("metadata", None, "METADATA_INVALID"),
    ("created_at", "2026-10-16T12:00:00", "CREATED_AT_INVALID"), ("created_at", "yesterday", "CREATED_AT_INVALID"),
    ("created_at", 1760616000.0, "CREATED_AT_INVALID"), ("created_at", None, "CREATED_AT_INVALID"),
]
VALID_EDGES = [
    ("confidence", 0), ("confidence", 100.0), ("price", 1e-9), ("risk_level", "UNKNOWN"), ("action", "HOLD"),
    ("symbol", "1000PEPEUSDT"), ("strategy", " Atlas trend "), ("created_at", "2026-10-16T15:00:00+03:00"),
]


@pytest.mark.parametrize("field, value, code", FIELD_CASES)
def test_each_broken_field_is_refused_with_its_own_code(field, value, code):
    with pytest.raises(ContractViolation) as caught:
        check(decision(**{field: value}))
    assert caught.value.code == code


@pytest.mark.parametrize("field, value", VALID_EDGES)
def test_boundary_values_inside_the_contract_pass(field, value):
    payload = decision(**{field: value})
    BrainDecisionPayload.from_decision(payload, expected_symbol=payload["symbol"], now=NOW)


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_every_required_field_must_be_present(field):
    payload = decision()
    del payload[field]
    with pytest.raises(ContractViolation) as caught:
        check(payload)
    assert (caught.value.code, str(caught.value)) == ("MISSING_FIELD", f"MISSING_FIELD: {field}")


@pytest.mark.parametrize("field, code", [("confidence", "CONFIDENCE_INVALID"), ("price", "PRICE_INVALID")])
def test_a_number_too_large_for_a_float_is_refused_not_raised(field, code):
    # Outside the schema comparison: JSON Schema has no float range, so it would accept 10**400 as a price.
    with pytest.raises(ContractViolation) as caught:
        check(decision(**{field: 10 ** 400}))
    assert caught.value.code == code


def test_a_non_mapping_and_a_foreign_symbol_are_refused():
    for payload, code in ((None, "NOT_A_MAPPING"), ([("action", "BUY")], "NOT_A_MAPPING"),
                          (decision(symbol="ETHUSDT"), "SYMBOL_MISMATCH")):
        with pytest.raises(ContractViolation) as caught:
            check(payload)
        assert caught.value.code == code


@pytest.mark.parametrize("offset, code", [
    (-MAX_DECISION_AGE, None),
    (-MAX_DECISION_AGE - timedelta(microseconds=1), "DECISION_STALE"),
    (MAX_CLOCK_SKEW, None),
    (MAX_CLOCK_SKEW + timedelta(microseconds=1), "DECISION_FROM_FUTURE"),
])
@pytest.mark.parametrize("action", ["BUY", "SELL"])
def test_staleness_window_is_exact_for_buy_and_sell(offset, code, action):
    payload = decision(action=action, created_at=(NOW + offset).isoformat())
    if code is None:
        check(payload)
    else:
        with pytest.raises(ContractViolation) as caught:
            check(payload)
        assert caught.value.code == code


class _NoOffset(tzinfo):
    def utcoffset(self, dt):
        return None


def test_the_check_clock_must_be_timezone_aware():
    for now in (NOW.replace(tzinfo=None), NOW.replace(tzinfo=_NoOffset())):
        with pytest.raises(ValueError, match="timezone-aware"):
            BrainDecisionPayload.from_decision(decision(), expected_symbol="BTCUSDT", now=now)


def test_the_owner_decided_values_are_pinned():
    assert (MAX_DECISION_AGE, MAX_CLOCK_SKEW) == (timedelta(seconds=180), timedelta(seconds=5))
    assert ACTIONS == ("BUY", "SELL", "HOLD")
    assert RISK_LEVELS == ("LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN")


# -- the JSON Schema document agrees with the dataclass ---------------------------------------------


def _schema_accepts(schema: dict[str, Any], payload: dict[str, Any]) -> bool:
    """The draft 2020-12 keywords the document uses; test-only, not a runtime validator."""
    if any(name not in payload for name in schema["required"]):
        return False
    for name, rule in schema["properties"].items():
        value = payload[name]
        kind = rule["type"]
        if kind == "string" and not isinstance(value, str):
            return False
        if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))
                                 or not math.isfinite(value)):
            return False
        if kind == "object" and not isinstance(value, dict):
            return False
        if "enum" in rule and value not in rule["enum"]:
            return False
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            return False
        if "minimum" in rule and value < rule["minimum"]:
            return False
        if "maximum" in rule and value > rule["maximum"]:
            return False
        if "exclusiveMinimum" in rule and value <= rule["exclusiveMinimum"]:
            return False
        if rule.get("format") == "date-time":
            try:
                if datetime.fromisoformat(value).tzinfo is None:
                    return False
            except ValueError:
                return False
    return True


def test_the_schema_document_accepts_and_refuses_the_same_field_cases():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert tuple(schema["required"]) == REQUIRED_FIELDS and set(schema["properties"]) == set(REQUIRED_FIELDS)
    assert tuple(schema["properties"]["action"]["enum"]) == ACTIONS
    assert tuple(schema["properties"]["risk_level"]["enum"]) == RISK_LEVELS
    assert schema["additionalProperties"] is True  # later pipeline stages add fields; the contract allows them
    assert _schema_accepts(schema, decision())
    for field, value, _code in FIELD_CASES:
        assert not _schema_accepts(schema, decision(**{field: value})), (field, value)
    for field, value in VALID_EDGES:
        assert _schema_accepts(schema, decision(**{field: value})), (field, value)


# -- MarketLoop ----------------------------------------------------------------------------------------


class StampedBrain(DecidingBrain):
    def __init__(self, action: str, created_at: Any) -> None:
        super().__init__(action)
        self.created_at = created_at

    def analyze_and_decide(self, symbol, market_data):
        return {**super().analyze_and_decide(symbol, market_data), "created_at": self.created_at}


@pytest.fixture
def loop_and_app(tmp_path):
    app = application(tmp_path)
    app.execution.start()
    loop = execution_enabled_loop(app, "BUY")
    published: list[tuple[str, dict[str, Any]]] = []
    real_publish = loop.publish
    loop.publish = lambda event, payload: (published.append((event, payload)), real_publish(event, payload))[1]
    routed: list[dict[str, Any]] = []
    real_route = loop.route_execution
    loop.route_execution = lambda **kw: (routed.append(copy.deepcopy(kw["decision"])), real_route(**kw))[1]
    loop.published, loop.routed = published, routed
    yield loop, app
    app.stop()


def _stamp(loop, seconds_ago: float) -> str:
    return (loop._decision_contract_now() - timedelta(seconds=seconds_ago)).isoformat()


@pytest.mark.parametrize("created_at, reason", [
    (lambda loop: _stamp(loop, 181), "DECISION_STALE"),
    (lambda loop: "yesterday", "CREATED_AT_INVALID"),
    (lambda loop: _stamp(loop, -6), "DECISION_FROM_FUTURE"),
])
def test_a_broken_decision_is_dropped_audited_never_routed_and_the_candle_is_retried(loop_and_app, created_at,
                                                                                       reason):
    loop, app = loop_and_app
    loop.brain = StampedBrain("BUY", created_at(loop))
    assert loop.process_symbol("BTCUSDT") is None
    assert loop.routed == [] and app.portfolio_foundation.snapshot()["positions"].get("BTCUSDT") is None
    assert loop.metrics["decision_contract_rejected"] == 1 and loop.metrics["decisions_rejected"] == 1
    [(event, payload)] = [item for item in loop.published if item[0] == "DECISION_CONTRACT_REJECTED"]
    assert payload["symbol"] == "BTCUSDT" and payload["reason"] == reason
    assert payload["decision"]["action"] == "BUY"
    assert "BTCUSDT" not in loop.last_processed_candles and "BTCUSDT" not in loop.last_signals


def test_after_a_rejection_a_fresh_decision_on_the_same_candle_routes_exactly_once(loop_and_app):
    loop, _app = loop_and_app
    loop.brain = StampedBrain("BUY", _stamp(loop, 600))
    assert loop.process_symbol("BTCUSDT") is None
    loop.brain = StampedBrain("BUY", _stamp(loop, 1))
    assert loop.process_symbol("BTCUSDT")["status"] == "PAPER_EXECUTED"
    assert loop.process_symbol("BTCUSDT")["reason"] == "DUPLICATE_CLOSED_CANDLE"  # never decided twice
    assert len(loop.routed) == 1 and loop.metrics["decision_contract_rejected"] == 1


def test_a_valid_decision_reaches_the_gates_unchanged_and_in_order(loop_and_app, monkeypatch):
    loop, _app = loop_and_app
    order: list[str] = []
    seen: list[str] = []
    real_from_decision = BrainDecisionPayload.from_decision.__func__
    real_gate = loop._symbol_execution_gate

    def from_decision(cls, payload, **kw):
        order.append("contract")
        seen.append(json.dumps(payload, sort_keys=True, default=str))
        return real_from_decision(cls, payload, **kw)

    monkeypatch.setattr(BrainDecisionPayload, "from_decision", classmethod(from_decision))
    loop._symbol_execution_gate = lambda *a: (order.append("gate"), real_gate(*a))[1]
    returned: list[str] = []
    real_decide = loop._symbol_decide
    loop._symbol_decide = lambda *a: (lambda out: (returned.append(json.dumps(out[0], sort_keys=True, default=str)),
                                                   out)[1])(real_decide(*a))
    result = loop.process_symbol("BTCUSDT")
    assert result["status"] == "PAPER_EXECUTED"
    assert order == ["contract", "gate"] and len(loop.routed) == 1
    # The contract hands on exactly what it checked: no key added, removed or changed (review 31 L-A).
    assert returned == seen
    # Nothing the contract saw was altered by it: every field it read reaches the router as it was.
    checked = json.loads(seen[0])
    assert {name: loop.routed[0][name] for name in REQUIRED_FIELDS if name != "metadata"} == \
        {name: checked[name] for name in REQUIRED_FIELDS if name != "metadata"}
    # process_symbol only adds metadata keys after the contract; every key the contract saw is unchanged.
    routed_metadata = json.loads(json.dumps(loop.routed[0]["metadata"], sort_keys=True, default=str))
    assert {key: routed_metadata[key] for key in checked["metadata"]} == checked["metadata"]
    assert "decision_contract_rejected" not in loop.metrics


def test_a_rejected_decision_never_reaches_the_execution_gate(loop_and_app):
    loop, _app = loop_and_app
    loop.brain = StampedBrain("SELL", _stamp(loop, 181))
    loop._symbol_execution_gate = lambda *a: pytest.fail("the execution gate ran for a rejected decision")
    assert loop.process_symbol("BTCUSDT") is None


def test_the_contract_is_checked_against_the_cycle_symbol(loop_and_app):
    loop, _app = loop_and_app
    real = loop.normalize_decision

    def foreign(**kw):
        normalized = real(**kw)
        normalized["symbol"] = "ETHUSDT"
        return normalized

    loop.normalize_decision = foreign
    assert loop.process_symbol("BTCUSDT") is None and loop.routed == []
    [payload] = [p for event, p in loop.published if event == "DECISION_CONTRACT_REJECTED"]
    assert payload["reason"] == "SYMBOL_MISMATCH"


def test_an_unexpected_error_in_the_check_is_a_processing_failure_not_a_contract_rejection(loop_and_app,
                                                                                         monkeypatch):
    loop, _app = loop_and_app

    def broken(cls, payload, **kw):
        raise RuntimeError("contract boom")

    monkeypatch.setattr(BrainDecisionPayload, "from_decision", classmethod(broken))
    assert loop.process_symbol("BTCUSDT") is None and loop.routed == []
    assert "decision_contract_rejected" not in loop.metrics
    assert not [event for event, _p in loop.published if event == "DECISION_CONTRACT_REJECTED"]
    assert [e.get("error") for e in loop.errors][-1] == "contract boom"


def test_the_execution_gate_still_refuses_an_invalid_action_behind_the_contract(loop_and_app):
    """Defence in depth: the contract now stops an invalid action first, so this branch is only reachable
    by calling the gate directly; it must keep refusing (owner decision D-1, v5.96)."""
    loop, _app = loop_and_app
    candle = {"open_time": 0, "close_time": 59_999}
    result = loop._symbol_execution_gate("BTCUSDT", {"action": "TELEPORT", "symbol": "BTCUSDT", "metadata": {}},
                                         [candle], loop._processing_cutoff())
    assert result == {"status": "REJECTED", "reason": "INVALID_NORMALIZED_ACTION", "symbol": "BTCUSDT",
                      "action": "TELEPORT"}
    assert loop.metrics["decisions_rejected"] == 1 and loop.routed == []
