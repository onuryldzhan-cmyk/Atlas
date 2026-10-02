"""T-0013 (owner 2026-10-02): golden characterization of ExecutionManager._execute_decision.

Written and generated against the pre-refactor code (one 1237-line body), so the
split into helpers must reproduce, for every scenario below, exactly the same:

  * returned result,
  * published events (name + payload, in order),
  * audit events (type, payload, and which earlier audit event each one is caused by),
  * stats counters, halt / recovery flags,
  * pending claims, side-effect markers, history / rejection / error trails,
  * capital reservations, transaction journal states and the durable portfolio.

Volatile values (timestamps, latencies, generated ids) are normalized; nothing else is.
Scenarios cover every return path of the function, most by fault injection.

Regenerate ONLY when a behaviour change is intended and approved:
    python -c "import json, tempfile, pathlib; from tests.test_execute_decision_golden import collect, GOLDEN; \
GOLDEN.write_text(json.dumps(collect(pathlib.Path(tempfile.mkdtemp())), indent=1, sort_keys=True))"
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from core.execution_models import ExecutionRequest
from tests.test_block5e_fee_settlement_accounting import application

GOLDEN = Path(__file__).with_name("golden") / "execute_decision_golden.json"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)?")
_VOLATILE = {"timestamp", "latency_ms", "execution_id", "created_at", "updated_at", "event_id",
             "recorded_at", "occurred_at", "last_updated", "started_at", "finished_at",
             "last_loaded_at", "last_saved_at", "duration_ms"}


def norm(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): ("<v>" if str(k) in _VOLATILE else norm(v))
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [norm(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(json.dumps(norm(v), sort_keys=True) for v in value)
    if isinstance(value, Enum):
        return norm(value.value)
    if isinstance(value, Decimal):
        return f"D:{value}"
    if isinstance(value, str):
        return _TS.sub("<ts>", _UUID.sub("<uuid>", value))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return norm(to_dict())
    return f"<{type(value).__name__}>"


class Recorder:
    """Wraps publish and _write_audit_event on the instance; the real ones still run."""

    def __init__(self, ex: Any) -> None:
        self.published: list[list[Any]] = []
        self.audits: list[dict[str, Any]] = []
        self._ids: dict[str, int] = {}
        orig_publish, orig_audit = ex.publish, ex._write_audit_event

        def publish(event_name: str, payload: Any) -> bool:
            self.published.append([event_name, norm(payload)])
            return orig_publish(event_name, payload)

        def write_audit_event(*, event_type: str, request: Any, payload: Any, causation_id: str | None = None):
            event_id = orig_audit(event_type=event_type, request=request, payload=payload, causation_id=causation_id)
            self.audits.append({
                "type": event_type,
                "request_id": norm(str(getattr(request, "request_id", None))),
                "payload": norm(dict(payload)),
                "caused_by": (None if causation_id is None else self._ids.get(causation_id, "<foreign>")),
                "written": event_id is not None,
            })
            if event_id is not None:
                self._ids[event_id] = len(self.audits) - 1
            return event_id

        ex.publish = publish
        ex._write_audit_event = write_audit_event


def _buy(request_id: str = "b1", amount: float = 1000, confidence: float = 90.0, **extra: Any) -> dict:
    return {"symbol": "BTCUSDT", "action": "BUY", "price": 10.0, "amount": amount,
            "confidence": confidence, "risk": "MEDIUM", "request_id": request_id, **extra}


def _sell(request_id: str = "s1", amount: float = 0) -> dict:
    return {"symbol": "BTCUSDT", "action": "SELL", "price": 10.0, "amount": amount,
            "confidence": 90.0, "risk": "MEDIUM", "request_id": request_id}


def _fail(message: str) -> Callable[..., Any]:
    def raiser(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(message)
    return raiser


# ----------------------------------------------------------------------------- scenarios
# Each takes (app, ex) and returns the list of results of its execute() calls.

def s_offline(app, ex):
    ex.stop() if getattr(ex, "running", False) else None
    return [ex.execute(_buy())]


def s_halted(app, ex):
    ex.execution_halted, ex.recovery_required, ex.halt_reason = True, False, "TEST_HALT"
    return [ex.execute(_buy())]


def s_durable_not_ready(app, ex):
    ex._durable_financial_ready = lambda: (False, "TEST_DURABLE_NOT_READY")
    return [ex.execute(_buy())]


def s_build_failure(app, ex):
    ex.build_request = _fail("build boom")
    return [ex.execute(_buy())]


def s_invalid_request_id(app, ex):
    request = ExecutionRequest("BTCUSDT", "BUY", 10.0, 1000, confidence=90.0, risk="MEDIUM", request_id="x1")
    request.request_id = "   "
    return [ex.execute(request)]


def s_buy_success(app, ex):
    return [ex.execute(_buy())]


def s_buy_then_full_sell(app, ex):
    return [ex.execute(_buy()), ex.execute(_sell())]


def s_buy_then_partial_sell(app, ex):
    return [ex.execute(_buy()), ex.execute(_sell(amount=300))]


def s_dict_with_metadata(app, ex):
    return [ex.execute(_buy(strategy="T13", source="golden", metadata={"note": "kept"}, order_type="market"))]


def s_duplicate_completed(app, ex):
    return [ex.execute(_buy()), ex.execute(_buy())]


def s_duplicate_pending(app, ex):
    request = ex.build_request(_buy("p1"))
    assert ex._claim_request(request) is None
    return [ex.execute(_buy("p1"))]


def s_validation_hold(app, ex):
    return [ex.execute({"symbol": "BTCUSDT", "action": "HOLD", "price": 10.0, "amount": 1000,
                        "confidence": 90.0, "request_id": "h1"})]


def s_validation_low_confidence(app, ex):
    return [ex.execute(_buy("c1", confidence=5.0))]  # 0..1 is read as a fraction, so 5.0 means 5 %


def s_duplicate_unknown_reason(app, ex):
    ex._claim_request = lambda request: {"success": False, "status": "SKIPPED", "reason": "SOMETHING_ELSE",
                                         "request_id": request.request_id}
    return [ex.execute(_buy())]


def s_validation_reject_persist_fails(app, ex):
    # A failed terminal persist leaves the claim exactly as the original body leaves it
    # (pins where request_claimed is cleared; _release_request is otherwise idempotent).
    ex._complete_request = lambda *, request_id, result: False
    return [ex.execute({"symbol": "BTCUSDT", "action": "HOLD", "price": 10.0, "amount": 1000,
                        "confidence": 90.0, "request_id": "h1"})]


def s_risk_reject_persist_fails(app, ex):
    ex._complete_request = lambda *, request_id, result: False
    return [ex.execute(_sell("s0"))]


def s_risk_reject_sell_without_position(app, ex):
    return [ex.execute(_sell("s0"))]


def s_admission_missing(app, ex):
    ex._has_risk_admission = lambda request: False
    return [ex.execute(_buy())]


def s_prepare_false(app, ex):
    ex.transaction_journal.prepare = lambda *a, **k: False
    return [ex.execute(_buy())]


def s_prepare_raises(app, ex):
    ex.transaction_journal.prepare = _fail("prepare boom")
    return [ex.execute(_buy())]


def s_paper_failed_no_side_effect(app, ex):
    ex.paper_execute = lambda request: {"success": False, "status": "FAILED", "message": "paper says no",
                                        "error_code": "TEST_PAPER_FAILED"}
    return [ex.execute(_buy()), ex.execute(_buy("b2"))]


def s_paper_failed_after_side_effect(app, ex):
    def paper(request):
        ex._mark_execution_side_effect(request.request_id)
        return {"success": False, "status": "FAILED", "message": "failed late", "error_code": "TEST_LATE"}
    ex.paper_execute = paper
    return [ex.execute(_buy()), ex.execute(_buy("b2"))]


def s_paper_unknown_status(app, ex):
    ex.paper_execute = lambda request: {"success": True, "status": "WEIRD_NEW_STATUS"}
    return [ex.execute(_buy())]


def s_paper_rejected_by_shadow_book(app, ex):
    ex.paper_fill_provider = lambda symbol, side, notional: None
    return [ex.execute(_buy())]


def s_live_mode_disabled(app, ex):
    ex.mode = ex.MODE_LIVE
    return [ex.execute(_buy())]


def s_finalize_raises(app, ex):
    ex._finalize_durable_financial_state = _fail("finalize boom")
    return [ex.execute(_buy()), ex.execute(_buy("b2"))]


def s_reservation_commit_false(app, ex):
    ex._commit_capital_reservation = lambda request_id, settled_amount=None: False
    return [ex.execute(_buy()), ex.execute(_buy("b2"))]


def s_complete_request_false(app, ex):
    ex._complete_request = lambda *, request_id, result: False
    return [ex.execute(_buy())]


def s_journal_commit_false(app, ex):
    ex.transaction_journal.mark_committed = lambda *a, **k: False
    return [ex.execute(_buy())]


def s_journal_commit_raises(app, ex):
    ex.transaction_journal.mark_committed = _fail("journal boom")
    return [ex.execute(_buy())]


def s_exception_in_validation(app, ex):
    ex.validate_request = _fail("validate boom")
    return [ex.execute(_buy()), ex.execute(_buy("b2"))]


def s_exception_in_risk_check(app, ex):
    ex.risk_check = _fail("risk boom")
    return [ex.execute(_buy())]


def s_exception_after_side_effect(app, ex):
    ex._mirror_paper_book = _fail("mirror boom")
    return [ex.execute(_buy()), ex.execute(_buy("b2"))]


def s_exception_in_paper_execute(app, ex):
    ex.paper_execute = _fail("paper boom")
    return [ex.execute(_buy())]


def s_audit_disabled(app, ex):
    ex.audit_enabled = False
    return [ex.execute(_buy()), ex.execute(_sell())]


def s_audit_store_failing(app, ex):
    ex.audit_store.append = _fail("audit store down")
    return [ex.execute(_buy())]


def s_execution_request_object(app, ex):
    request = ExecutionRequest("BTCUSDT", "BUY", 10.0, 1000, confidence=90.0, risk="MEDIUM", request_id="o1")
    return [ex.execute(request)]


SCENARIOS: dict[str, Callable[[Any, Any], list]] = {
    name.removeprefix("s_"): fn for name, fn in sorted(globals().items()) if name.startswith("s_") and callable(fn)
}


def _snapshot(app: Any, ex: Any, results: list, rec: Recorder) -> dict[str, Any]:
    ids = sorted({str(r.get("request_id")) for r in results if isinstance(r, dict) and r.get("request_id")}
                 | {"b1", "b2", "s1", "s0", "p1", "h1", "c1", "o1"})
    reservations = {}
    ledger = getattr(ex, "reservation_ledger", None)
    for rid in ids:
        res = ledger.get(rid) if ledger is not None else None
        if res is not None:
            reservations[rid] = {"status": res.status.value, "amount": str(res.amount)}
    entries = getattr(ex.transaction_journal, "entries", {}) or {}
    journal = {rid: str(entries[rid].get("state")) for rid in ids if rid in entries}
    snap = app.portfolio_foundation.snapshot() if app.portfolio_foundation is not None else {}
    return norm({
        "results": results,
        "published": rec.published,
        "audits": rec.audits,
        "stats": dict(ex.stats),
        "halted": [ex.execution_halted, ex.recovery_required, ex.halt_reason],
        "pending": sorted(ex.pending_request_ids),
        "side_effect_markers": sorted(ex._execution_side_effect_ids),
        "history": [[h.get("status"), h.get("error_code"), h.get("commit_outcome")] for h in ex.history],
        "rejections": [[r.get("reason"), r.get("request_id")] for r in ex.rejections],
        "errors": [[e.get("phase"), e.get("error")] for e in ex.errors],
        "reservations": reservations,
        "journal": journal,
        "portfolio": {"positions": snap.get("positions"), "cash": snap.get("cash"),
                      "realized_gross_pnl": snap.get("realized_gross_pnl")},
    })


def collect(root: Path) -> dict[str, Any]:
    out = {}
    for name, scenario in SCENARIOS.items():
        app = application(root / name)
        ex = app.execution
        if name != "offline":
            ex.start()
        rec = Recorder(ex)
        results = scenario(app, ex)
        out[name] = _snapshot(app, ex, results, rec)
    return out


def test_execute_decision_matches_golden(tmp_path):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = collect(tmp_path)
    assert sorted(actual) == sorted(expected), "scenario set changed"
    for name in sorted(expected):
        assert actual[name] == expected[name], f"scenario {name!r} diverged from the golden record"


def test_golden_covers_every_return_path():
    """Guard: the golden record must keep exercising each terminal status family."""
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    statuses = {r.get("status") for snap in expected.values() for r in snap["results"] if isinstance(r, dict)}
    errors = {r.get("error_code") for snap in expected.values() for r in snap["results"] if isinstance(r, dict)}
    assert {"PAPER_EXECUTED", "REJECTED", "RECOVERY_REQUIRED", "NOT_COMMITTED", "COMMIT_STATUS_UNKNOWN",
            "FAILED"} <= statuses, statuses
    assert {"EXECUTION_REQUEST_BUILD_FAILED", "TRANSACTION_PREPARE_FAILED", "DURABLE_FINANCIAL_FINALIZATION_FAILED",
            "CAPITAL_RESERVATION_COMMIT_FAILED", "DURABLE_COMMIT_FAILED", "TRANSACTION_JOURNAL_COMMIT_FAILED",
            "EXECUTION_PIPELINE_EXCEPTION"} <= errors, errors
