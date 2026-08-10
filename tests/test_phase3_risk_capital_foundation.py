from decimal import Decimal
from datetime import UTC, date, datetime, timedelta
import threading

import pytest

from core.risk_engine import (
    BucketPolicy, DrawdownLevel, PositionExposure, RiskBucket,
    RiskDecisionStatus, RiskEngine, RiskPolicy, RiskRequest, RiskState,
)
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.capital_reservation import CapitalReservationLedger, JsonReservationStore, ReservationStatus
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState


D = Decimal


def policy(**changes):
    values = {"total_capital": D("1000")}
    values.update(changes)
    return RiskPolicy(**values)


def position(symbol="BTCUSDT", quote="100", price="10"):
    return PositionExposure(symbol, D(quote) / D(price), D(price), D(quote))


def state(*positions, pnl="0", peak="1000", equity="1000", ready=True):
    return RiskState(tuple(positions), sum((p.quote_exposure for p in positions), D("0")),
                     D(pnl), D(peak), D(equity), ready,
                     datetime.now(UTC).date().isoformat(), "phase3-risk-v1")


def request(symbol="ETHUSDT", amount="100", confidence="0.90", bucket="MEDIUM", **changes):
    values = dict(symbol=symbol, action="BUY", confidence=D(confidence),
                  requested_quote_allocation=D(amount), execution_price=D("10"),
                  risk_bucket=bucket, base_quantity=D(amount) / D("10"))
    values.update(changes)
    return RiskRequest(**values)


def test_safe_defaults_preserve_reserve_and_approve_decimal_allocation():
    engine = RiskEngine(policy())
    result = engine.evaluate(request(), state())
    assert result.status is RiskDecisionStatus.APPROVE
    assert result.approved_allocation == D("100")
    assert result.reserved_capital == D("200.00")
    assert result.available_capital == D("800.00")


@pytest.mark.parametrize("value", [D("NaN"), D("Infinity"), D("-1"), 1.5])
def test_invalid_financial_policy_values_rejected(value):
    with pytest.raises(ValueError):
        policy(total_capital=value)


def test_position_and_bucket_caps_reject_without_partial_silent_allocation():
    assert RiskEngine(policy()).evaluate(request(amount="401"), state()).reason_code == "REQUEST_EXCEEDS_RISK_LIMIT"
    assert RiskEngine(policy()).evaluate(request(amount="251", bucket="MEDIUM"), state()).reason_code == "REQUEST_EXCEEDS_RISK_LIMIT"


@pytest.mark.parametrize("bucket,confidence,approved", [
    (RiskBucket.LOW, "0.60", True), (RiskBucket.MEDIUM, "0.69", False),
    (RiskBucket.HIGH, "0.79", False), (RiskBucket.HIGH, "0.80", True),
])
def test_bucket_confidence_policy(bucket, confidence, approved):
    result = RiskEngine(policy()).evaluate(request(bucket=bucket, confidence=confidence), state())
    assert result.approved is approved


def test_invalid_bucket_fails_closed():
    result = RiskEngine(policy()).evaluate(request(bucket="UNKNOWN"), state())
    assert result.status is RiskDecisionStatus.REJECT
    assert result.reason_code == "INVALID_FINANCIAL_INPUT"


def test_exposure_reconciliation_prevents_stale_or_duplicate_accounting():
    p = position()
    with pytest.raises(ValueError, match="disagree"):
        RiskState((p,), D("0"), D("0"), D("1000"), D("1000"), True)
    result = RiskEngine(policy()).evaluate(request(symbol="BTCUSDT"), state(p))
    assert result.reason_code == "DUPLICATE_OPEN_POSITION"


def test_base_quantity_is_not_quote_notional():
    result = RiskEngine(policy()).evaluate(
        request(amount="100", base_quantity=D("100")), state())
    assert result.reason_code == "QUANTITY_NOTIONAL_MISMATCH"


def test_portfolio_cap_and_insufficient_available_capital():
    p1 = position("BTCUSDT", "400")
    p2 = position("SOLUSDT", "400")
    result = RiskEngine(policy()).evaluate(request(amount="1"), state(p1, p2))
    assert result.reason_code == "INSUFFICIENT_ALLOCATABLE_CAPITAL"


def test_daily_loss_breach_blocks_entry_but_not_valid_reduction():
    p = position()
    engine = RiskEngine(policy())
    assert engine.evaluate(request(), state(p, pnl="-50")).reason_code == "DAILY_LOSS_LIMIT_BREACHED"
    close = request(symbol="BTCUSDT", action="SELL", reduce_only=True,
                    requested_quote_allocation=D("50"), base_quantity=D("5"))
    assert engine.evaluate(close, state(p, pnl="-50")).reason_code == "RISK_REDUCTION_APPROVED"


@pytest.mark.parametrize("equity,level,reason", [
    ("949", DrawdownLevel.WARNING, "RISK_APPROVED"),
    ("900", DrawdownLevel.RESTRICT, "DRAWDOWN_RESTRICT_NEW_RISK"),
    ("850", DrawdownLevel.HALT_NEW_RISK, "DRAWDOWN_HALT_NEW_RISK"),
])
def test_drawdown_thresholds(equity, level, reason):
    result = RiskEngine(policy()).evaluate(request(), state(peak="1000", equity=equity))
    assert result.drawdown_level is level
    assert result.reason_code == reason


def test_max_positions_duplicate_and_concentration():
    positions = tuple(position(f"S{i}", "100") for i in range(5))
    assert RiskEngine(policy()).evaluate(request(), state(*positions)).reason_code == "MAX_POSITIONS_REACHED"
    assert RiskEngine(policy()).evaluate(request(symbol="S0"), state(*positions[:1])).reason_code == "DUPLICATE_OPEN_POSITION"
    tight = policy(concentration_pct=D("0.05"))
    assert RiskEngine(tight).evaluate(request(amount="51"), state()).reason_code == "REQUEST_EXCEEDS_RISK_LIMIT"


def test_missing_or_corrupt_restored_state_fails_recovery_closed():
    result = RiskEngine(policy()).evaluate(request(), state(ready=False))
    assert result.status is RiskDecisionStatus.BLOCK_RECOVERY_REQUIRED
    assert result.reason_code == "RISK_STATE_NOT_READY"


def test_policy_is_configuration_driven_and_requires_all_buckets():
    buckets = {
        RiskBucket.LOW: BucketPolicy(D(".2"), D(".5"), D(".3")),
        RiskBucket.MEDIUM: BucketPolicy(D(".1"), D(".6"), D(".2")),
    }
    with pytest.raises(ValueError, match="required"):
        policy(buckets=buckets)


def test_float_leakage_and_non_finite_request_fail_closed():
    engine = RiskEngine(policy())
    unsafe = RiskRequest("BTCUSDT", "BUY", 0.9, D("10"), D("1"), "LOW")
    assert engine.evaluate(unsafe, state()).reason_code == "INVALID_FINANCIAL_INPUT"
    assert engine.evaluate(request(confidence=D("NaN")), state()).reason_code == "INVALID_FINANCIAL_INPUT"


def test_compatibility_adapter_does_not_infer_missing_state():
    result = RiskEngine(policy()).validate({"symbol": "BTCUSDT", "action": "BUY",
                                            "confidence": "0.9", "amount": "10", "price": "1"})
    assert result["status"] == "BLOCK_RECOVERY_REQUIRED"


class MemoryStore:
    def __init__(self, initial=()): self.items = tuple(initial); self.fail = False
    def load(self): return self.items
    def save(self, items):
        if self.fail: raise OSError("save failed")
        self.items = tuple(items)


class MemoryRiskStateStore:
    def load(self, *, expected_policy_version, today_utc):
        return RestoredRiskState(today_utc, D("0"), D("1000"), D("1000"),
                                 expected_policy_version)


def ledger(total="800", store=None):
    return CapitalReservationLedger(store or MemoryStore(), D(total))


def execution_manager(engine, reservations=None):
    manager = ExecutionManager.__new__(ExecutionManager)
    manager.risk_engine = engine
    manager.reservation_ledger = reservations or ledger()
    manager.risk_state_store = MemoryRiskStateStore()
    manager.position_controller = None
    manager.capital_manager = None
    manager.last_risk_decision = None
    manager._risk_admissions = {}
    manager.mode = "PAPER"; manager.event_bus = None
    manager._lock = threading.RLock(); manager.errors = []
    return manager


def test_execution_seam_rejection_cannot_reach_legacy_capital_gate():
    manager = execution_manager(RiskEngine(policy()))
    req = ExecutionRequest("BTCUSDT", "BUY", 10, 100, confidence=90, risk="HIGH")
    result = manager.risk_check(req, state(ready=False))
    assert not result["approved"]
    assert result["status"] == "BLOCK_RECOVERY_REQUIRED"


def test_execution_seam_approved_amount_cannot_exceed_risk_decision():
    manager = execution_manager(RiskEngine(policy()))
    req = ExecutionRequest("BTCUSDT", "BUY", 10, 401, confidence=90, risk="LOW")
    result = manager.risk_check(req, state())
    assert not result["approved"]
    assert result["reason"] == "REQUEST_EXCEEDS_RISK_LIMIT"


def test_execution_seam_accepts_exact_canonical_allocation():
    manager = execution_manager(RiskEngine(policy()))
    req = ExecutionRequest("BTCUSDT", "BUY", 10, 100, confidence=90, risk="HIGH")
    assert manager.risk_check(req, state())["approved"]
    assert D(manager.last_risk_decision["approved_allocation"]) == D("100")


def test_missing_canonical_service_and_legacy_gate_cannot_substitute():
    manager = execution_manager(None)
    manager.capital_manager = type("Legacy", (), {"approve": lambda *args: {"approved": True}})()
    req = ExecutionRequest("BTCUSDT", "BUY", 10, 100, confidence=90)
    assert manager.risk_check(req, state())["reason"] == "CANONICAL_RISK_SERVICE_REQUIRED"


def test_alternate_paper_route_cannot_bypass_canonical_admission():
    manager = execution_manager(RiskEngine(policy()))
    manager._lock = threading.RLock(); manager.rejections = []; manager.history = []
    manager.stats = manager._new_stats()
    req = ExecutionRequest("BTCUSDT", "BUY", 10, 100, confidence=90)
    result = manager.paper_execute(req)
    assert not result["success"] and result["reason"] == "CANONICAL_RISK_ADMISSION_MISSING"


def test_approved_request_id_cannot_authorize_mutated_financial_request():
    manager = execution_manager(RiskEngine(policy()))
    original = ExecutionRequest("BTCUSDT", "BUY", 10, 100, confidence=90, request_id="same")
    assert manager.risk_check(original, state())["approved"]
    changed = ExecutionRequest("BTCUSDT", "BUY", 10, 200, confidence=90, request_id="same")
    manager.rejections = []; manager.history = []; manager.stats = manager._new_stats()
    assert manager.paper_execute(changed)["reason"] == "CANONICAL_RISK_ADMISSION_MISSING"


def test_concurrent_reservations_cannot_double_spend():
    reservations = ledger(total="100")
    barrier = threading.Barrier(2); outcomes = []
    def compete(name):
        barrier.wait()
        try: reservations.reserve(name, name, D("75")); outcomes.append("reserved")
        except ValueError: outcomes.append("blocked")
    threads = [threading.Thread(target=compete, args=(name,)) for name in ("a", "b")]
    [item.start() for item in threads]; [item.join() for item in threads]
    assert sorted(outcomes) == ["blocked", "reserved"]
    assert reservations.available == D("25")


def test_reservation_retry_commit_release_and_invalid_transitions():
    reservations = ledger(total="100")
    first = reservations.reserve("r1", "request-1", D("60"))
    assert reservations.reserve("r1", "request-1", D("60")) is first
    assert reservations.commit("r1").status is ReservationStatus.COMMITTED
    assert reservations.commit("r1").status is ReservationStatus.COMMITTED
    with pytest.raises(ValueError): reservations.release("r1")
    reservations.reserve("r2", "request-2", D("20"))
    assert reservations.release("r2").status is ReservationStatus.RELEASED
    assert reservations.release("r2").status is ReservationStatus.RELEASED


def test_restart_preserves_active_and_indeterminate_reservations(tmp_path):
    store = JsonReservationStore(tmp_path / "reservations.json"); store.initialize_empty()
    first = CapitalReservationLedger(store, D("100")); first.reserve("r1", "q1", D("40"))
    restarted = CapitalReservationLedger(store, D("100"))
    assert restarted.available == D("60")
    restarted.mark_indeterminate("r1")
    assert CapitalReservationLedger(store, D("100")).available == D("60")
    with pytest.raises(ValueError): restarted.release("r1")


def test_reservation_persistence_failures_make_ledger_not_ready():
    store = MemoryStore(); reservations = ledger(store=store); store.fail = True
    with pytest.raises(RuntimeError): reservations.reserve("r1", "q1", D("10"))
    assert not reservations.ready
    store2 = MemoryStore(); reservations2 = ledger(store=store2)
    reservations2.reserve("r1", "q1", D("10")); store2.fail = True
    with pytest.raises(RuntimeError): reservations2.commit("r1")
    assert not reservations2.ready


def test_missing_corrupt_and_policy_mismatched_loss_state_fail_closed(tmp_path):
    store = JsonRiskStateStore(tmp_path / "risk.json")
    with pytest.raises(FileNotFoundError): store.load(expected_policy_version="v1", today_utc=date.today())
    (tmp_path / "risk.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(Exception): store.load(expected_policy_version="v1", today_utc=date.today())
    store.save(RestoredRiskState(date.today(), D("-10"), D("100"), D("90"), "v2"))
    with pytest.raises(ValueError, match="version"): store.load(expected_policy_version="v1", today_utc=date.today())


def test_restored_loss_and_drawdown_continue_to_block_new_risk():
    engine = RiskEngine(policy())
    assert engine.evaluate(request(), state(pnl="-50")).reason_code == "DAILY_LOSS_LIMIT_BREACHED"
    assert engine.evaluate(request(), state(peak="1000", equity="850")).reason_code == "DRAWDOWN_HALT_NEW_RISK"


def test_utc_rollover_is_explicit_durable_and_preserves_peak(tmp_path):
    store = JsonRiskStateStore(tmp_path / "risk.json")
    yesterday = date.today() - timedelta(days=1)
    old = RestoredRiskState(yesterday, D("-50"), D("1200"), D("900"), "v1")
    store.save(old)
    loaded = store.load(expected_policy_version="v1", today_utc=date.today())
    assert loaded.realized_daily_pnl == D("-50")
    rolled = store.rollover(loaded, today_utc=date.today(), current_equity=D("950"))
    assert rolled.realized_daily_pnl == 0 and rolled.peak_equity == D("1200")
