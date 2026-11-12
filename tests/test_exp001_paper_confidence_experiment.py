"""EXP-001 (registry v5.01): PAPER-only, time-boxed, sample-capped lowering
of the BUY confidence floor to 0.60 for the MEDIUM and HIGH buckets.

The experiment must only ever widen admission inside its window, for its
buckets, down to its floor, and only while attached; every other RiskEngine
behaviour must stay exactly as it is without it.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace

import pytest

from core.application import AtlasApplication, count_experiment_admissions
from core.experiment_ledger import (
    EXPERIMENT_LEDGER_FILE,
    ExperimentAdmissionLedger,
    ExperimentLedgerError,
)
from core.capital_reservation import CapitalReservationLedger
from core.execution_manager import ExecutionManager
from core.execution_models import ExecutionRequest
from core.instrument_rules import InstrumentRules, InstrumentRuleset
from core.risk_engine import (
    EXP001_PAPER_CONFIDENCE_EXPERIMENT, ConfidenceFloorExperiment, PositionExposure,
    RiskBucket, RiskDecisionStatus, RiskEngine, RiskPolicy, RiskRequest, RiskState,
)
from core.risk_state_store import RestoredRiskState


EXP = EXP001_PAPER_CONFIDENCE_EXPERIMENT
INSIDE = EXP.starts_at + timedelta(days=1)
BEFORE = EXP.starts_at - timedelta(seconds=1)
AT_END = EXP.ends_at


def policy():
    return RiskPolicy(total_capital=D("1000"))


def state(*positions, pnl="0", peak="1000", equity="1000"):
    return RiskState(tuple(positions), sum((p.quote_exposure for p in positions), D("0")),
                     D(pnl), D(peak), D(equity), True,
                     datetime.now(UTC).date().isoformat(), "phase3-risk-v1")


def buy(bucket="HIGH", confidence="0.63", amount="50", symbol="ETHUSDT"):
    return RiskRequest(symbol=symbol, action="BUY", confidence=D(confidence),
                       requested_quote_allocation=D(amount), execution_price=D("10"),
                       risk_bucket=bucket, base_quantity=D(amount) / D("10"))


def engine(now=INSIDE, prior=0, experiment=EXP, attach=True):
    risk = RiskEngine(policy())
    if attach:
        risk.attach_experiment(experiment, prior_admissions=prior, clock=lambda: now)
    return risk


# =====================================================================
# Pinned constants: the grant's values, not configurable
# =====================================================================

def test_exp001_constants_match_the_grant():
    assert EXP.experiment_id == "EXP-001"
    assert EXP.minimum_confidence == D("0.60")
    assert EXP.buckets == frozenset({RiskBucket.MEDIUM, RiskBucket.HIGH})
    assert EXP.starts_at == datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
    assert EXP.ends_at == datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
    assert EXP.max_admissions == 50


# =====================================================================
# Admission inside the window
# =====================================================================

@pytest.mark.parametrize("bucket", ["MEDIUM", "HIGH"])
@pytest.mark.parametrize("confidence", ["0.60", "0.63", "0.6999"])
def test_lowered_floor_admits_and_tags(bucket, confidence):
    risk = engine()
    decision = risk.evaluate(buy(bucket=bucket, confidence=confidence), state())
    assert decision.status is RiskDecisionStatus.APPROVE
    assert decision.reason_code == "RISK_APPROVED"
    assert decision.experiment_id == "EXP-001"
    assert decision.to_dict()["experiment_id"] == "EXP-001"
    assert risk.experiment_admissions == 1


@pytest.mark.parametrize("bucket", ["MEDIUM", "HIGH"])
def test_below_experiment_floor_still_rejected(bucket):
    risk = engine()
    decision = risk.evaluate(buy(bucket=bucket, confidence="0.5999"), state())
    assert decision.reason_code == "CONFIDENCE_BELOW_POLICY"
    assert risk.experiment_admissions == 0


@pytest.mark.parametrize("bucket,confidence", [("MEDIUM", "0.70"), ("HIGH", "0.80"), ("HIGH", "0.95")])
def test_admission_that_meets_default_floor_is_not_tagged(bucket, confidence):
    risk = engine()
    decision = risk.evaluate(buy(bucket=bucket, confidence=confidence), state())
    assert decision.approved
    assert decision.experiment_id == ""
    assert risk.experiment_admissions == 0


def test_low_bucket_is_not_in_the_experiment():
    risk = engine()
    assert risk.evaluate(buy(bucket="LOW", confidence="0.5999"), state()).reason_code == (
        "CONFIDENCE_BELOW_POLICY")
    approved = risk.evaluate(buy(bucket="LOW", confidence="0.60"), state())
    assert approved.approved and approved.experiment_id == ""


def test_bucket_outside_experiment_keeps_its_default_floor():
    high_only = ConfidenceFloorExperiment("EXP-H", D("0.60"), frozenset({RiskBucket.HIGH}),
                                          EXP.starts_at, EXP.ends_at, 5)
    risk = engine(experiment=high_only)
    assert risk.evaluate(buy(bucket="MEDIUM", confidence="0.65"), state()).reason_code == (
        "CONFIDENCE_BELOW_POLICY")
    assert risk.evaluate(buy(bucket="HIGH", confidence="0.65"), state()).experiment_id == "EXP-H"


def test_high_bucket_sizing_unchanged_under_experiment():
    risk = engine()
    over = risk.evaluate(buy(bucket="HIGH", confidence="0.63", amount="110"), state())
    assert over.reason_code == "REQUEST_EXCEEDS_RISK_LIMIT"
    at_limit = risk.evaluate(buy(bucket="HIGH", confidence="0.63", amount="100"), state())
    assert at_limit.approved and at_limit.approved_allocation == D("100")


# =====================================================================
# Window, cap and attachment: every closed state reverts to defaults
# =====================================================================

@pytest.mark.parametrize("now", [BEFORE, AT_END, AT_END + timedelta(days=30)])
def test_outside_window_default_floor_applies(now):
    risk = engine(now=now)
    assert risk.evaluate(buy(confidence="0.63"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"


def test_cap_reached_from_prior_admissions_reverts_to_default():
    risk = engine(prior=50)
    assert risk.evaluate(buy(confidence="0.63"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"


def test_cap_counts_its_own_admissions():
    small = ConfidenceFloorExperiment("EXP-T", D("0.60"), frozenset({RiskBucket.HIGH}),
                                      EXP.starts_at, EXP.ends_at, 2)
    risk = engine(experiment=small)
    results = [risk.evaluate(buy(confidence="0.63", symbol=s), state()) for s in ("A", "B", "C")]
    assert [r.approved for r in results] == [True, True, False]
    assert results[2].reason_code == "CONFIDENCE_BELOW_POLICY"
    assert risk.experiment_admissions == 2


def test_unattached_engine_keeps_default_floors():
    risk = engine(attach=False)
    assert risk.evaluate(buy(confidence="0.63"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"
    assert risk.status()["experiment"] is None


def test_policy_version_unchanged_so_restored_state_still_matches():
    risk = engine()
    assert risk.policy.version == "phase3-risk-v1"
    assert risk.evaluate(buy(confidence="0.63"), state()).policy_version == "phase3-risk-v1"


# =====================================================================
# Other limits are not bypassed by the lowered floor
# =====================================================================

def test_daily_loss_and_drawdown_still_reject():
    assert engine().evaluate(buy(), state(pnl="-50")).reason_code == "DAILY_LOSS_LIMIT_BREACHED"
    assert engine().evaluate(buy(), state(peak="1000", equity="890")).reason_code == (
        "DRAWDOWN_RESTRICT_NEW_RISK")


def test_duplicate_position_still_rejects():
    held = PositionExposure("ETHUSDT", D("10"), D("10"), D("100"))
    assert engine().evaluate(buy(), state(held)).reason_code == "DUPLICATE_OPEN_POSITION"


@pytest.mark.parametrize("bucket,reason", [("CRITICAL", "CRITICAL_RISK_NOT_EXECUTABLE"),
                                           ("EXTREME", "UNSUPPORTED_RISK_LEVEL")])
def test_non_executable_risk_still_rejects(bucket, reason):
    assert engine().evaluate(buy(bucket=bucket), state()).reason_code == reason


def test_rejections_do_not_consume_the_cap():
    risk = engine()
    risk.evaluate(buy(), state(pnl="-50"))
    risk.evaluate(buy(confidence="0.50"), state())
    assert risk.experiment_admissions == 0


# =====================================================================
# Validation of the experiment object and attachment
# =====================================================================

@pytest.mark.parametrize("changes", [
    {"experiment_id": ""},
    {"minimum_confidence": D("1.5")},
    {"minimum_confidence": 0.6},
    {"buckets": frozenset()},
    {"buckets": frozenset({"HIGH"})},
    {"starts_at": datetime(2026, 9, 28)},
    {"ends_at": EXP.starts_at},
    {"max_admissions": 0},
    {"max_admissions": True},
])
def test_invalid_experiment_is_refused(changes):
    values = dict(experiment_id="X", minimum_confidence=D("0.6"), buckets=frozenset({RiskBucket.HIGH}),
                  starts_at=EXP.starts_at, ends_at=EXP.ends_at, max_admissions=5)
    values.update(changes)
    with pytest.raises(ValueError):
        ConfidenceFloorExperiment(**values)


@pytest.mark.parametrize("prior", [-1, True, 1.0, None])
def test_invalid_prior_admissions_refused(prior):
    with pytest.raises(ValueError):
        RiskEngine(policy()).attach_experiment(EXP, prior_admissions=prior)


def test_experiment_floor_never_below_global_minimum():
    low = ConfidenceFloorExperiment("EXP-L", D("0.40"), frozenset({RiskBucket.HIGH}),
                                    EXP.starts_at, EXP.ends_at, 5)
    risk = engine(experiment=low)
    assert risk.evaluate(buy(confidence="0.50"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"


# =====================================================================
# Composition root: opt-in, PAPER only, fail-closed on unreadable audit
# =====================================================================

class FakeAudit:
    def __init__(self, events=(), fail=False):
        self.events, self.fail = list(events), fail

    def query(self, *, event_type=None, **_):
        if self.fail:
            raise ValueError("Malformed audit record at line 3")
        return [e for e in self.events if event_type is None or e.event_type == event_type]


def event(event_type, details):
    return SimpleNamespace(event_type=event_type, payload={"details": details})


def app(mode="PAPER", opted_in=True, audit=None, state_directory=None):
    application = AtlasApplication.__new__(AtlasApplication)
    # AtlasApplication.__init__ always sets this; the durable admission
    # ledger (registry v5.17) lives under it.
    application.state_directory = (
        Path(tempfile.mkdtemp()) if state_directory is None else Path(state_directory)
    )
    application.execution_mode = mode
    application.paper_confidence_experiment = opted_in
    application.audit_store = audit if audit is not None else FakeAudit()
    application.risk_engine = RiskEngine(policy())
    return application


def test_attached_when_opted_in_and_paper():
    application = app()
    application._attach_paper_confidence_experiment()
    assert application.risk_engine.experiment is EXP


@pytest.mark.parametrize("mode,opted_in", [("LIVE", True), ("SHADOW", True), ("PAPER", False)])
def test_not_attached_unless_opted_in_and_paper(mode, opted_in):
    application = app(mode=mode, opted_in=opted_in)
    application._attach_paper_confidence_experiment()
    assert application.risk_engine.experiment is None


def test_unreadable_audit_log_leaves_experiment_unattached():
    application = app(audit=FakeAudit(fail=True))
    application._attach_paper_confidence_experiment()
    assert application.risk_engine.experiment is None


def test_prior_admissions_counted_from_audit_log():
    events = [
        event("RISK_APPROVED", {"experiment_id": "EXP-001"}),
        event("RISK_APPROVED", {"experiment_id": "EXP-001"}),
        event("RISK_APPROVED", {"instrument_rules_digest": "x"}),
        event("RISK_APPROVED", {"experiment_id": "EXP-999"}),
        event("RISK_APPROVED", None),
        event("RISK_REJECTED", {"experiment_id": "EXP-001"}),
    ]
    assert count_experiment_admissions(FakeAudit(events), "EXP-001") == 2
    application = app(audit=FakeAudit(events))
    application._attach_paper_confidence_experiment()
    assert application.risk_engine.experiment_admissions == 2


def test_default_constructor_argument_is_off():
    import inspect
    signature = inspect.signature(AtlasApplication.__init__)
    assert signature.parameters["paper_confidence_experiment"].default is False


def test_only_main_entry_point_opts_in():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    hits = [p.relative_to(root).as_posix() for p in root.rglob("*.py")
            if "tests" not in p.parts and not any(part.startswith(("archive", "phase")) for part in p.parts)
            and "paper_confidence_experiment=True" in p.read_text(encoding="utf-8", errors="ignore")]
    # EXP-001 was stopped by the owner on 2026-09-29 (registry v5.71).
    # Test policy change 2026-10-01: the owner switched on EXP-002 - still only
    # main.py may opt in, and only for EXP-002 (EXP-001 stays stopped).
    assert hits == ["main.py"]
    text = (root / "main.py").read_text(encoding="utf-8")
    assert 'paper_confidence_experiment_id="EXP-002"' in text and '"EXP-001"' not in text


# =====================================================================
# ExecutionManager: tag reaches the RISK_APPROVED details, nothing else changes
# =====================================================================

ETHUSDT_RULES = InstrumentRuleset({
    "ETHUSDT": InstrumentRules(
        venue="BINANCE", symbol="ETHUSDT", base_asset="ETH", quote_asset="USDT",
        quantity_step="0.0001", min_quantity="0.0001", min_notional="5",
        price_tick="0.01", source="test-fixture", source_version="v1",
        retrieved_at="2026-01-01T00:00:00Z",
    ),
})


class MemoryStore:
    def __init__(self): self.items = ()
    def load(self): return self.items
    def save(self, items): self.items = tuple(items)


class MemoryRiskStateStore:
    def load(self, *, expected_policy_version, today_utc):
        return RestoredRiskState(today_utc, D("0"), D("1000"), D("1000"), expected_policy_version)


def manager(risk):
    m = ExecutionManager.__new__(ExecutionManager)
    m.risk_engine = risk
    m.reservation_ledger = CapitalReservationLedger(MemoryStore(), D("800"))
    m.risk_state_store = MemoryRiskStateStore()
    m.portfolio_foundation = None
    m.position_controller = None
    m.capital_manager = None
    m.last_risk_decision = None
    m._risk_admissions = {}
    m.instrument_rules = ETHUSDT_RULES
    m.mode = "PAPER"
    m.event_bus = None
    m._lock = threading.RLock()
    m.errors = []
    return m


def request(confidence, risk="HIGH"):
    return ExecutionRequest("ETHUSDT", "BUY", 10, 50, confidence=confidence, risk=risk)


def test_manager_tags_experiment_admission_in_details():
    result = manager(engine()).risk_check(request(63), state())
    assert result["approved"] is True
    assert result["reason"] == "RISK_APPROVED"
    assert result["details"]["experiment_id"] == "EXP-001"


def test_manager_normal_admission_has_no_experiment_key():
    result = manager(engine()).risk_check(request(95), state())
    assert result["approved"] is True
    assert "experiment_id" not in result["details"]


def test_unrecorded_experiment_admission_closes_experiment():
    risk = engine()
    m = manager(risk)
    m._close_experiment_if_unrecorded(None, {"experiment_id": "EXP-001"})
    assert risk.experiment_closed_reason == "AUDIT_WRITE_FAILED"
    assert risk.evaluate(buy(confidence="0.63"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"
    assert risk.status()["experiment"]["active"] is False


@pytest.mark.parametrize("event_id,details", [
    ("evt-1", {"experiment_id": "EXP-001"}),
    (None, {"instrument_rules_digest": "x"}),
    (None, None),
])
def test_recorded_or_untagged_admission_keeps_experiment_open(event_id, details):
    risk = engine()
    manager(risk)._close_experiment_if_unrecorded(event_id, details)
    assert risk.experiment_closed_reason is None
    assert risk.evaluate(buy(confidence="0.63"), state()).approved


def test_close_experiment_is_noop_without_experiment():
    risk = engine(attach=False)
    risk.close_experiment("AUDIT_WRITE_FAILED")
    assert risk.experiment_closed_reason is None


def test_concurrent_evaluations_never_exceed_the_cap():
    cap = ConfidenceFloorExperiment("EXP-C", D("0.60"), frozenset({RiskBucket.HIGH}),
                                    EXP.starts_at, EXP.ends_at, 5)
    risk = engine(experiment=cap)
    # Each thread's first floor check (the early one in evaluate) returns its
    # verdict and then waits until all 40 have passed it, so no admission has
    # been counted yet: the race the atomic re-check at approval must close.
    original_floor = risk._experiment_floor
    gate, calls, calls_lock = threading.Barrier(40), [0], threading.Lock()

    def racing_floor(bucket):
        verdict = original_floor(bucket)
        with calls_lock:
            calls[0] += 1
            first_pass = calls[0] <= 40
        if first_pass:
            gate.wait()
        return verdict

    risk._experiment_floor = racing_floor
    results = []

    def worker(i):
        results.append(risk.evaluate(buy(confidence="0.63", symbol=f"S{i}"), state()))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r.approved for r in results) == 5
    assert risk.experiment_admissions == 5


def test_manager_without_experiment_rejects_as_before():
    result = manager(engine(attach=False)).risk_check(request(63), state())
    assert result["approved"] is False
    assert result["reason"] == "CONFIDENCE_BELOW_POLICY"


# =====================================================================
# Durable admission ledger (registry v5.17)
# =====================================================================

def _admit_events(n):
    return [event("RISK_APPROVED", {"experiment_id": "EXP-001"}) for _ in range(n)]


def test_ledger_absent_counts_zero_and_record_is_monotonic(tmp_path):
    ledger = ExperimentAdmissionLedger(tmp_path / EXPERIMENT_LEDGER_FILE)
    assert ledger.count("EXP-001") == 0
    ledger.record("EXP-001", 3)
    ledger.record("EXP-001", 1)
    assert ledger.count("EXP-001") == 3
    assert not (tmp_path / (EXPERIMENT_LEDGER_FILE + ".tmp")).exists()


@pytest.mark.parametrize("content", ["{not json", "[]", '{"EXP-001": {"admissions": -1}}',
                                     '{"EXP-001": {"admissions": true}}', '{"EXP-001": 5}'])
def test_malformed_ledger_raises(tmp_path, content):
    path = tmp_path / EXPERIMENT_LEDGER_FILE
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ExperimentLedgerError):
        ExperimentAdmissionLedger(path).count("EXP-001")


def test_restart_takes_larger_of_audit_and_ledger(tmp_path):
    ExperimentAdmissionLedger(tmp_path / EXPERIMENT_LEDGER_FILE).record("EXP-001", 7)
    application = app(audit=FakeAudit(_admit_events(2)), state_directory=tmp_path)
    application._attach_paper_confidence_experiment()
    assert application.risk_engine.experiment_admissions == 7

    application = app(audit=FakeAudit(_admit_events(9)), state_directory=tmp_path)
    application._attach_paper_confidence_experiment()
    assert application.risk_engine.experiment_admissions == 9


def test_lost_audit_lines_cannot_reopen_a_full_experiment(tmp_path):
    ExperimentAdmissionLedger(tmp_path / EXPERIMENT_LEDGER_FILE).record("EXP-001", 50)
    application = app(audit=FakeAudit([]), state_directory=tmp_path)
    application._attach_paper_confidence_experiment()
    decision = application.risk_engine.evaluate(buy(confidence="0.63"), state())
    assert decision.reason_code == "CONFIDENCE_BELOW_POLICY"
    assert decision.experiment_id == ""


def test_unreadable_ledger_leaves_experiment_unattached(tmp_path):
    (tmp_path / EXPERIMENT_LEDGER_FILE).write_text("{garbage", encoding="utf-8")
    application = app(state_directory=tmp_path)
    application._attach_paper_confidence_experiment()
    assert application.risk_engine.experiment is None


def test_admission_is_recorded_before_it_is_granted(tmp_path):
    application = app(state_directory=tmp_path)
    application._attach_paper_confidence_experiment()
    risk = application.risk_engine
    risk._experiment_clock = lambda: INSIDE
    decision = risk.evaluate(buy(confidence="0.63"), state())
    assert decision.experiment_id == "EXP-001"
    stored = json.loads((tmp_path / EXPERIMENT_LEDGER_FILE).read_text(encoding="utf-8"))
    assert stored["EXP-001"]["admissions"] == risk.experiment_admissions == 1


def test_recorder_failure_refuses_admission_and_closes_experiment():
    calls = []

    def failing(experiment_id, admissions):
        calls.append((experiment_id, admissions))
        raise OSError("disk full")

    risk = RiskEngine(policy())
    risk.attach_experiment(EXP, prior_admissions=0, clock=lambda: INSIDE, admission_recorder=failing)
    decision = risk.evaluate(buy(confidence="0.63"), state())
    assert calls == [("EXP-001", 1)]
    assert decision.reason_code == "CONFIDENCE_BELOW_POLICY"
    assert risk.experiment_admissions == 0
    assert risk.experiment_closed_reason == "ADMISSION_LEDGER_WRITE_FAILED"
    # still closed afterwards; default-floor admissions are unaffected
    assert risk.evaluate(buy(confidence="0.63"), state()).reason_code == "CONFIDENCE_BELOW_POLICY"
    assert risk.evaluate(buy(confidence="0.85"), state()).approved
    assert len(calls) == 1


def test_real_ledger_corrupted_while_running_closes_experiment(tmp_path):
    path = tmp_path / EXPERIMENT_LEDGER_FILE
    ledger = ExperimentAdmissionLedger(path)
    risk = RiskEngine(policy())
    risk.attach_experiment(EXP, prior_admissions=0, clock=lambda: INSIDE, admission_recorder=ledger.record)
    assert risk.evaluate(buy(confidence="0.63"), state()).experiment_id == "EXP-001"
    path.write_text("{corrupt", encoding="utf-8")
    decision = risk.evaluate(buy(confidence="0.63"), state())
    assert decision.reason_code == "CONFIDENCE_BELOW_POLICY"
    assert risk.experiment_admissions == 1
    assert risk.experiment_closed_reason == "ADMISSION_LEDGER_WRITE_FAILED"


def test_concurrent_admissions_never_overshoot_cap_or_ledger(tmp_path):
    ledger = ExperimentAdmissionLedger(tmp_path / EXPERIMENT_LEDGER_FILE)
    ledger.record("EXP-001", 45)
    risk = RiskEngine(policy())
    risk.attach_experiment(EXP, prior_admissions=45, clock=lambda: INSIDE, admission_recorder=ledger.record)
    results, start = [], threading.Barrier(20)

    def worker():
        start.wait()
        results.append(risk.evaluate(buy(confidence="0.63", amount="1"), state()))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sum(1 for d in results if d.experiment_id == "EXP-001") == 5
    assert risk.experiment_admissions == 50
    assert ledger.count("EXP-001") == 50
