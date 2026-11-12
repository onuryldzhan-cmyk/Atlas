"""Order state machine stage 1: observe only, default OFF, never changes a result."""

from __future__ import annotations

from core.order_lifecycle import observe_outcome
from tests.test_block5e_fee_settlement_accounting import application

BUY = {"symbol": "BTCUSDT", "action": "BUY", "price": 10.0, "amount": 1000, "confidence": 90.0, "risk": "MEDIUM"}


def test_clean_paper_fill_and_clean_rejection_have_no_violation():
    assert observe_outcome("a", {"status": "PAPER_EXECUTED", "success": True, "commit_outcome": "COMMITTED", "filled_price": 10.0}) == []
    assert observe_outcome("b", {"status": "REJECTED", "success": False, "reason": "LOW_CONFIDENCE"}) == []


def test_inconsistent_outcomes_are_flagged():
    assert "EXECUTED_WITHOUT_DURABLE_COMMIT" in observe_outcome("a", {"status": "PAPER_EXECUTED", "success": True, "filled_price": 10.0})
    assert "EXECUTED_WITHOUT_VALID_FILL_PRICE" in observe_outcome("a", {"status": "PAPER_EXECUTED", "success": True, "commit_outcome": "COMMITTED", "filled_price": None})
    assert "DENIED_ORDER_HAS_EXECUTION" in observe_outcome("b", {"status": "REJECTED", "success": True})


def test_unmapped_outcomes_are_not_guessed():
    assert observe_outcome("c", {"status": "SKIPPED"}) == []
    assert observe_outcome("d", {}) == []


def test_flag_off_by_default_and_results_identical(tmp_path):
    off, on = application(tmp_path / "off"), application(tmp_path / "on")
    assert off.execution.order_lifecycle_observe is False
    on.execution.order_lifecycle_observe = True
    off.execution.start(); on.execution.start()
    r_off = off.execution.execute(dict(BUY, request_id="b1"))
    r_on = on.execution.execute(dict(BUY, request_id="b1"))
    strip = lambda r: {k: v for k, v in r.items() if k not in ("latency_ms", "timestamp", "completed_at", "started_at", "duration_ms")}
    assert strip(r_off).keys() == strip(r_on).keys()
    assert r_on["status"] == r_off["status"] == "PAPER_EXECUTED"
    assert on.execution.order_lifecycle_violations == []
    low = on.execution.execute(dict(BUY, request_id="b2", confidence=5.0))
    assert low["status"] == "REJECTED" and on.execution.order_lifecycle_violations == []
