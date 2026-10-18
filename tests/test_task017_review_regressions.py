"""Task 017: regression tests for the independent review's findings F1-F10 (registry v5.101 task_017_reviews).

Each test reproduces the reviewer's failing input and pins the corrected behaviour.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.market_cycle import INTERVAL_MS

from tests._task017_support import AS_OF, CUTOFF, FakeAsk, inputs, klines
from tools.build_architecture_inventory import ENTRY_POINTS, REPOSITORY_ROOT, compute_runtime_closure
from tools.unified_analysis import __main__ as cli
from tools.unified_analysis.contracts import Classification
from tools.unified_analysis.decision import calibration_cap
from tools.unified_analysis.experience import ExperienceLedger, calibration, evaluate
from tools.unified_analysis.pipeline import run_analysis
from tools.unified_analysis.specialists import DEFAULT_SPECIALISTS

H = INTERVAL_MS["1h"]
DIRECTIONAL = (Classification.BULLISH_SETUP, Classification.BEARISH_SETUP)
BASES = [dict(drift=d) for d in (0.002, 0.001, 0.0005, 0.0, -0.0005, -0.002)] + [
    dict(drift=0.0005, band="CROWDED_LONG", fng=80, ten_year_bp=30),
    dict(drift=-0.0005, band="CROWDED_SHORT", fng=15, ten_year_bp=-30),
    dict(drift=0.002, band="CROWDED_LONG", fng=80, ten_year_bp=30),
]


def _run(base, **kw):
    base = dict(base)
    drift = base.pop("drift")
    return run_analysis(inputs(drift, **base), **kw)


# ---------------------------------------------------------------- F2 + the counter-evidence hole: NB-4


@pytest.mark.parametrize("base", BASES, ids=[str(b) for b in BASES])
def test_nb4_removing_any_subset_never_raises_reported_confidence_or_flips_direction(base):
    full = _run(base)
    names = [s.name for s in DEFAULT_SPECIALISTS]
    for k in range(1, len(names) + 1):
        for removed in itertools.combinations(names, k):
            kept = tuple(s for s in DEFAULT_SPECIALISTS if s.name not in removed)
            r = _run(base, specialists=kept)
            assert r.confidence <= full.confidence, (removed, r.classification, r.confidence, full.confidence)
            if r.classification in DIRECTIONAL:
                assert r.classification is full.classification, removed


def test_non_directional_results_report_no_confidence():
    for base in BASES:
        r = _run(base)
        if r.classification not in DIRECTIONAL:
            assert r.confidence == 0, (base, r.classification)


def test_two_sided_moderate_evidence_is_not_a_range_view():
    r = _run(dict(drift=0.0005, band="CROWDED_LONG", fng=80, ten_year_bp=30))
    assert r.classification is not Classification.NEUTRAL_RANGE or Decimal(r.confidence_basis["neutral_bound"]) >= Decimal("0.2")


# ---------------------------------------------------------------- F1: model narrative cannot move the result


def _multi_group_narrative():
    cites = ["liquidity:quote_volume_24", "derivatives:funding", "sentiment:fear_greed", "macro:ten_year"]
    return {"findings": [{"statement": "supports the trend", "kind": "INTERPRETATION", "stance": "BULLISH",
                          "strength": 1.0, "cites": [c], "claims": []} for c in cites]}


@pytest.mark.parametrize("drift", [0.0005, 0.001, 0.002])
def test_a_multi_group_narrative_changes_neither_class_nor_confidence(drift):
    det = run_analysis(inputs(drift))
    with_model = run_analysis(inputs(drift), ask=FakeAsk(narrative=_multi_group_narrative()), max_inference_calls=1)
    assert with_model.classification is det.classification
    assert with_model.confidence == det.confidence
    assert all(not f.startswith("narrative") for s in with_model.scenarios for f in (*s.supporting, *s.opposing))


@pytest.mark.parametrize("item", [
    {"statement": "target 250000 USD by Friday, insiders buying"},       # an unbacked number in free text
    {"kind": "PREDICTION"},                                              # a kind the schema does not allow
    {"cites": "technical:1h:trend"},                                     # a string, not a list
])
def test_unverifiable_narrative_items_are_dropped(item):
    base = {"statement": "trend intact", "kind": "INTERPRETATION", "stance": "BULLISH", "strength": 0.3,
            "cites": ["technical:1h:trend"], "claims": []}
    base.update(item)
    r = run_analysis(inputs(0.002), ask=FakeAsk(narrative={"findings": [base]}), max_inference_calls=1)
    nar = next(x for x in r.specialists if x.agent == "narrative")
    assert nar.findings == () and nar.status.value == "ABSTAIN"


def test_a_number_backed_by_a_claim_is_allowed():
    close = run_analysis(inputs(0.002)).reference_close
    item = {"statement": f"close {close:.2f} holds above support", "kind": "INTERPRETATION", "stance": "BULLISH",
            "strength": 0.3, "cites": ["technical:1h:trend"],
            "claims": [{"metric": "close", "timeframe": "1h", "value": round(close, 2)}]}
    r = run_analysis(inputs(0.002), ask=FakeAsk(narrative={"findings": [item]}), max_inference_calls=1)
    assert next(x for x in r.specialists if x.agent == "narrative").findings


def test_a_neutral_narrative_cannot_create_a_range_view():
    item = {"statement": "range-bound", "kind": "INTERPRETATION", "stance": "NEUTRAL", "strength": 0.3,
            "cites": ["technical:1h:trend"], "claims": []}
    for drift in (0.0005, 0.0):
        det = run_analysis(inputs(drift))
        r = run_analysis(inputs(drift), ask=FakeAsk(narrative={"findings": [item] * 4}), max_inference_calls=1)
        assert r.classification is det.classification


# ---------------------------------------------------------------- F3: decision time vs bar cutoff


def test_a_live_fetch_inside_the_hour_is_valid_and_settles_from_the_next_boundary():
    late = replace(inputs(0.002), fetched_at=AS_OF + timedelta(minutes=30))
    r = run_analysis(late)
    assert r.verification.passed, [c.check_id for c in r.verification.failures]
    assert r.classification is Classification.BULLISH_SETUP
    assert "derivatives" not in r.confidence_basis["missing_sources"]
    assert r.entry_from_ms == CUTOFF + H and r.as_of == AS_OF + timedelta(minutes=30)


def test_context_observed_after_the_decision_time_is_refused():
    base = inputs(0.002)
    late_fng = SimpleNamespace(**{**vars(base.fear_greed), "observed_at": AS_OF + timedelta(minutes=10)})
    r = run_analysis(replace(base, fear_greed=late_fng))
    assert "fear_greed:AFTER_CUTOFF" in r.metrics["data_problems"]
    assert next(x for x in r.specialists if x.agent == "sentiment").status.value == "ABSTAIN"


def test_a_fetch_more_than_an_hour_after_the_cutoff_is_untrusted():
    r = run_analysis(replace(inputs(0.002), fetched_at=AS_OF + timedelta(minutes=61)))
    assert r.classification is Classification.INSUFFICIENT_EVIDENCE
    assert "FETCH_LONG_AFTER_CUTOFF" in r.metrics["data_problems"]


def test_settlement_never_reads_the_decision_hour(tmp_path):
    ledger = ExperienceLedger(tmp_path / "e.jsonl")
    report = run_analysis(replace(inputs(0.002), fetched_at=AS_OF + timedelta(minutes=30)))
    pred = ledger.record_prediction(report)
    start = CUTOFF + H
    rows = [[start + i * H, 100.0, 101.0, 99.0, 100.5, 1.0, start + i * H + H - 1, 1.0] for i in range(24)]
    decision_hour = [[CUTOFF, 1.0, 999.0, 1.0, 999.0, 1.0, CUTOFF + H - 1, 1.0]]
    out = evaluate(pred, decision_hour + rows, now_ms=start + 24 * H)
    assert out["first_bar_open_ms"] == start and out["entry_open"] == 100.0
    assert out == evaluate(pred, rows, now_ms=start + 24 * H)


# ---------------------------------------------------------------- F4: calibration cap direction


def test_a_poor_record_lowers_the_cap_and_never_resets_it():
    none, _ = calibration_cap({})
    poor, _ = calibration_cap({"n": 30, "hits": 4, "measured": False})
    one_miss, _ = calibration_cap({"n": 1, "hits": 0, "measured": False})
    good_unmeasured, _ = calibration_cap({"n": 30, "hits": 29, "measured": False})
    assert none == Decimal("0.5") and poor < Decimal("0.25") and Decimal("0.4") < one_miss < none
    assert good_unmeasured == Decimal("0.5")                      # unmeasured never above the uncalibrated cap
    capped = run_analysis(inputs(0.002), calibration={"live:BULLISH_SETUP": {"n": 30, "hits": 4, "measured": False}})
    assert capped.confidence == Decimal("0.225")                  # (4 + 0.5 * 10) / (30 + 10)
    r = run_analysis(inputs(0.002), calibration={"live:BULLISH_SETUP": {"n": 30, "hits": 1, "measured": False}})
    assert r.classification is Classification.INSUFFICIENT_EVIDENCE   # cap 0.15 < threshold 0.20
    assert r.confidence_basis["candidate"] == "BULLISH_SETUP"     # still scored, so the record keeps growing


def test_capped_candidates_keep_accumulating_a_record():
    recs = []
    for i in range(3):
        recs.append({"record_type": "PREDICTION", "analysis_id": f"a{i}", "symbol": "X", "cutoff_ms": i * 48 * H,
                     "horizon_ms": 24 * H, "classification": "INSUFFICIENT_EVIDENCE", "candidate": "BULLISH_SETUP",
                     "report": {"confidence_basis": {"roster": "live"}}})
        recs.append({"record_type": "OUTCOME", "analysis_id": f"a{i}", "hit": True, "through_ms": (i * 48 + 24) * H})
    assert calibration(recs)["live:BULLISH_SETUP"]["n"] == 3


# ---------------------------------------------------------------- F5: no outcome from the future in calibration


def test_calibration_as_of_excludes_outcomes_closed_later():
    recs = []
    for i in range(40):
        recs.append({"record_type": "PREDICTION", "analysis_id": f"a{i}", "symbol": "X", "cutoff_ms": i * 24 * H,
                     "horizon_ms": 24 * H, "classification": "BULLISH_SETUP",
                     "report": {"confidence_basis": {"roster": "hist"}}})
        recs.append({"record_type": "OUTCOME", "analysis_id": f"a{i}", "hit": True, "through_ms": (i + 1) * 24 * H})
    assert calibration(recs, as_of_ms=10 * 24 * H)["hist:BULLISH_SETUP"]["n"] == 10
    assert calibration(recs, as_of_ms=0) == {}


# ---------------------------------------------------------------- F6: malformed model output never crashes


@pytest.mark.parametrize("narrative, prosecutor", [
    ({"findings": {"a": 1}}, {"charges": [], "unresolved_questions": []}),
    ({"findings": 5}, {"charges": {"x": 1}, "unresolved_questions": []}),
    ({"findings": []}, {"charges": [], "unresolved_questions": 7}),
    ({"findings": [{"statement": 1, "kind": "INTERPRETATION", "stance": "BULLISH", "strength": "x",
                    "cites": ["technical:1h:trend"], "claims": [{"metric": None}]}]},
     {"charges": [{"statement": "s", "cites": 3, "severity": "MAJOR"}], "unresolved_questions": []}),
])
def test_type_malformed_model_output_never_raises(narrative, prosecutor):
    r = run_analysis(inputs(0.002), ask=FakeAsk(narrative=narrative, prosecutor=prosecutor, juror={"vote": 1}),
                     max_inference_calls=5)
    assert r.classification is run_analysis(inputs(0.002)).classification


def test_an_ask_that_raises_is_an_abstain():
    def boom(system, prompt, schema):
        raise RuntimeError("socket")

    r = run_analysis(inputs(0.002), ask=boom, max_inference_calls=5)
    assert next(x for x in r.specialists if x.agent == "narrative").reason.startswith("MODEL_ASK_RAISED")
    assert r.review.court_status == "ABSTAINED"


# ---------------------------------------------------------------- F7 / F8: CLI


def test_cli_argument_errors_exit_2(tmp_path):
    for argv in (["analyze", "--symbol", "BTCUSDT", "--horizon", "0"],
                 ["analyze", "--symbol", "BTCUSDT", "--max-calls", "-1"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--state-dir", str(tmp_path), *argv])
        assert exc.value.code == 2
    assert cli.main(["--state-dir", str(tmp_path), "analyze", "--symbol", "BTCUSDT",
                     "--cutoff", "2026-01-01T00:00:00Z"]) == 2


def test_cli_conflict_saves_the_rerun_report_and_exits_4(tmp_path, monkeypatch, capsys):
    calls = iter([inputs(0.002), replace(inputs(0.002), funding={"available": True, "rate": "0.0004",
                                                                 "band": "CROWDED_LONG"})])
    monkeypatch.setattr(cli, "collect_binance", lambda symbol: next(calls))
    assert cli.main(["--state-dir", str(tmp_path), "analyze", "--symbol", "BTCUSDT"]) == 0
    assert cli.main(["--state-dir", str(tmp_path), "analyze", "--symbol", "BTCUSDT"]) == 4
    reports = sorted(p.name for p in (tmp_path / "reports").iterdir())
    assert len(reports) == 2 and any(".rerun-" in n for n in reports)
    assert "the first one stands" in capsys.readouterr().out


def test_cli_does_not_record_a_data_outage(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "collect_binance", lambda symbol: inputs(k={"1h": None, "4h": None, "1d": None}))
    assert cli.main(["--state-dir", str(tmp_path), "analyze", "--symbol", "BTCUSDT"]) == 0
    assert ExperienceLedger(tmp_path / "experience.jsonl").records() == []


def test_a_failing_append_is_a_ledger_error(tmp_path, monkeypatch):
    ledger = ExperienceLedger(tmp_path / "e.jsonl")

    def poisoned(payloads):
        raise OSError("disk")

    monkeypatch.setattr(ledger._log, "append", poisoned)
    from tools.unified_analysis.experience import ExperienceLedgerError

    with pytest.raises(ExperienceLedgerError):
        ledger.record_prediction(run_analysis(inputs(0.002)))


# ---------------------------------------------------------------- F9: the package stays outside the runtime


def test_unified_analysis_and_the_gateway_are_outside_the_runtime_closure():
    closure = compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)
    assert not any(str(m).startswith(("tools.unified_analysis", "tools/unified_analysis")) for m in closure)
    assert not any("ai_gateway" in str(m) for m in closure)


# ---------------------------------------------------------------- re-audit N1-N5


def _track(hits, n, measured, wilson=None):
    from tools.unified_analysis.experience import wilson_lower

    return {"n": n, "hits": hits, "measured": measured,
            "wilson_lower": wilson if wilson is not None else round(wilson_lower(hits, n), 4)}


def test_n1_one_more_hit_or_passing_walk_forward_never_lowers_the_cap():
    before, _ = calibration_cap(_track(17, 29, False))
    after, _ = calibration_cap(_track(18, 30, True))
    failed_wf, _ = calibration_cap(_track(18, 30, False))
    assert after >= before and after >= failed_wf
    for n in range(1, 60):
        for hits in range(n):
            lower, _ = calibration_cap(_track(hits, n, False))
            higher, _ = calibration_cap(_track(hits + 1, n, False))
            assert higher >= lower


def test_n2_the_default_roster_can_reach_a_range_view():
    r = run_analysis(inputs(0.0, k=klines(0.0, vol=0.003, wiggle=1.3)))
    assert r.classification is Classification.NEUTRAL_RANGE
    assert Decimal(r.confidence_basis["neutral_bound"]) >= Decimal("0.2") and r.confidence == 0
    names = [s.name for s in DEFAULT_SPECIALISTS]
    for k in range(1, len(names) + 1):            # NB-4 on the range path: removal never raises the bound
        for removed in itertools.combinations(names, k):
            kept = tuple(s for s in DEFAULT_SPECIALISTS if s.name not in removed)
            sub = run_analysis(inputs(0.0, k=klines(0.0, vol=0.003, wiggle=1.3)), specialists=kept)
            if "neutral_bound" in sub.confidence_basis:
                assert Decimal(sub.confidence_basis["neutral_bound"]) <= Decimal(r.confidence_basis["neutral_bound"])
            assert sub.classification not in DIRECTIONAL


def test_n3_risk_rejected_candidates_never_set_the_approved_cap():
    recs = []
    for i in range(40):
        recs.append({"record_type": "PREDICTION", "analysis_id": f"r{i}", "symbol": "X", "cutoff_ms": i * 48 * H,
                     "horizon_ms": 24 * H, "classification": "RISK_REJECTED", "candidate": "BULLISH_SETUP",
                     "risk_approved": False, "report": {"confidence_basis": {"roster": "live"}}})
        recs.append({"record_type": "OUTCOME", "analysis_id": f"r{i}", "hit": True, "through_ms": (i * 48 + 24) * H})
    cal = calibration(recs)
    assert "live:BULLISH_SETUP" not in cal and cal["live:BULLISH_SETUP:risk_rejected"]["n"] == 40


@pytest.mark.parametrize("statement", ["target 250000 m", "market cap to 150 M", "200 bars of accumulation to 90000 d",
                                       "rally to 70k next"])
def test_n4_unit_suffixed_numbers_are_still_numbers(statement):
    item = {"statement": statement, "kind": "INTERPRETATION", "stance": "BULLISH", "strength": 0.3,
            "cites": ["technical:1h:trend"], "claims": []}
    r = run_analysis(inputs(0.002), ask=FakeAsk(narrative={"findings": [item]}), max_inference_calls=1)
    assert next(x for x in r.specialists if x.agent == "narrative").findings == ()


def test_n4_indicator_periods_and_timeframes_are_not_free_numbers():
    item = {"statement": "RSI(14) and EMA20 on 1h and 4h agree", "kind": "INTERPRETATION", "stance": "BULLISH",
            "strength": 0.3, "cites": ["technical:1h:trend"], "claims": []}
    r = run_analysis(inputs(0.002), ask=FakeAsk(narrative={"findings": [item]}), max_inference_calls=1)
    assert next(x for x in r.specialists if x.agent == "narrative").findings


def test_n5_counter_evidence_inside_a_supporting_specialist_is_penalised_once():
    from tools.unified_analysis.contracts import Objection, ReviewResult, Severity, SpecialistReport, AgentStatus, Stance
    from tools.unified_analysis.decision import _penalised_majors

    reports = (SpecialistReport("technical", AgentStatus.OK, Stance.BULLISH, 0.6),
               SpecialistReport("derivatives", AgentStatus.OK, Stance.BEARISH, 0.3))
    obj = lambda target: Objection(f"o:{target}", "det", Severity.MAJOR, "COUNTER_EVIDENCE", "x", (target,))
    review = ReviewResult((obj("technical:4h:trend"), obj("technical:1d:trend"), obj("derivatives:funding")), (),
                          "NOT_RUN")
    # two internal technical counters -> one penalty; the derivatives counter is inside fusion -> none
    assert _penalised_majors(review, reports, Stance.BULLISH) == 1
