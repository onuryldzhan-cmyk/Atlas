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
    fwd = (lambda n, hits: {"n": n, "hits": hits, "forward_n": n, "forward_hits": hits, "measured": False})
    poor, _ = calibration_cap(fwd(30, 4))
    one_miss, _ = calibration_cap(fwd(1, 0))
    good_unmeasured, _ = calibration_cap(fwd(30, 29))
    assert none == Decimal("0.5") and poor < Decimal("0.25") and Decimal("0.4") < one_miss < none
    assert good_unmeasured == Decimal("0.5")                      # unmeasured never above the uncalibrated cap
    capped = run_analysis(inputs(0.002), calibration={"live:BULLISH_SETUP": fwd(30, 4)})
    assert capped.confidence == Decimal("0.225")                  # (4 + 0.5 * 10) / (30 + 10)
    r = run_analysis(inputs(0.002), calibration={"live:BULLISH_SETUP": fwd(30, 1)})
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

    # forward-recorded samples (review 52 F-52-2: without forward counts every sample would be hindsight)
    return {"n": n, "hits": hits, "forward_n": n, "forward_hits": hits, "measured": measured,
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


# ---------------------------------------------------------------- review 48 H1: the cap through calibration()


def _cal_records(entries_and_hits, horizon_h=24, roster="live"):
    from tools.unified_analysis.experience import calibration  # noqa: F401  (imported for the caller's clarity)
    recs = []
    for i, (entry_h, hit) in enumerate(entries_and_hits):
        c = entry_h * H
        recs.append({"record_type": "PREDICTION", "analysis_id": f"a{i:05d}", "symbol": "BTCUSDT", "cutoff_ms": c,
                     "entry_from_ms": c, "horizon_ms": horizon_h * H, "classification": "BULLISH_SETUP",
                     "candidate": "BULLISH_SETUP", "risk_approved": True,
                     "report": {"confidence_basis": {"roster": roster}}})
        if hit is not None:
            recs.append({"record_type": "OUTCOME", "analysis_id": f"a{i:05d}", "hit": hit,
                         "through_ms": c + horizon_h * H})
    return recs


def _cap(recs, roster="live"):
    from tools.unified_analysis.experience import calibration

    cap, _ = calibration_cap(calibration(recs).get(f"{roster}:BULLISH_SETUP") or {})
    return cap


def test_h1_a_late_outcome_never_moves_the_cap_the_wrong_way():
    # hourly 24 h predictions; the hour-0 outcome arrives last (review 48 case B)
    for late_hit in (True, False):
        rule = (lambda h: h % 24 == 1) if late_hit else (lambda h: h % 24 == 0)
        rest = [(h, rule(h)) for h in range(1, 20 * 24)]
        before = _cap(_cal_records([(0, None)] + rest))
        after = _cap(_cal_records([(0, late_hit)] + rest))
        assert (after >= before) if late_hit else (after <= before), (late_hit, before, after)


def test_h1_one_more_hit_never_lowers_and_one_more_miss_never_raises_the_cap():
    import random

    rng = random.Random(48)
    for _ in range(40):
        base = [(i * 24, rng.random() < rng.random()) for i in range(rng.randrange(0, 70))]
        before = _cap(_cal_records(base))
        assert _cap(_cal_records(base + [(len(base) * 24, True)])) >= before
        assert _cap(_cal_records(base + [(len(base) * 24, False)])) <= before
        # a late outcome for an earlier prediction, too
        shuffled = base + [(len(base) * 24 + 24, None)]
        assert _cap(_cal_records(shuffled[:-1] + [(len(base) * 24 + 24, True)])) >= _cap(_cal_records(shuffled))


def test_h1_a_measured_record_still_reports_no_confidence_above_the_uncalibrated_cap():
    # review 48 case A: 23/31 passing walk-forward, then one more hit
    seq = [True] * 8 + [False] * 8 + [True] * 15
    first = _cal_records([(i * 48, h) for i, h in enumerate(seq)], roster="hist")
    second = _cal_records([(i * 48, h) for i, h in enumerate(seq + [True])], roster="hist")
    a, b = _cap(first, "hist"), _cap(second, "hist")
    assert a <= Decimal("0.5") and b <= Decimal("0.5") and b >= a


def test_h1_only_grid_aligned_default_horizon_predictions_are_samples():
    from tools.unified_analysis.experience import CALIBRATION_HORIZON_MS, calibration
    from tools.unified_analysis.pipeline import DEFAULT_HORIZON_HOURS

    assert CALIBRATION_HORIZON_MS == DEFAULT_HORIZON_HOURS * H
    off_grid = _cal_records([(i * 24 + 8, True) for i in range(5)])
    other_horizon = _cal_records([(i * 48, True) for i in range(5)], horizon_h=48)
    on_grid = _cal_records([(i * 24, True) for i in range(5)])
    assert calibration(off_grid) == {} and calibration(other_horizon) == {}
    assert calibration(on_grid)["live:BULLISH_SETUP"]["n"] == 5


def _slot_pair(first_id, later_id, first_hit, later_hit, *, symbol="BTCUSDT", roster="live"):
    pred = _cal_records([(0, None)], roster=roster)[0]
    first = {**pred, "analysis_id": first_id, "symbol": symbol}
    later = {**pred, "analysis_id": later_id, "symbol": symbol}
    return first, later, ({"record_type": "OUTCOME", "analysis_id": first_id, "hit": first_hit, "through_ms": 24 * H},
                          {"record_type": "OUTCOME", "analysis_id": later_id, "hit": later_hit, "through_ms": 24 * H})


def test_review49_the_first_recorded_prediction_of_a_slot_is_its_sample_whatever_its_id():
    from tools.unified_analysis.experience import calibration

    # the first recorded has the larger id: it still wins, so ids cannot pick the sample (review 49 H-new-1)
    first, later, (o_first, o_later) = _slot_pair("b-first", "a-later", True, False)
    row = calibration([first, later, o_later, o_first])["live:BULLISH_SETUP"]
    assert (row["n"], row["hits"]) == (1, 1)
    first, later, (o_first, o_later) = _slot_pair("a-first", "b-later", False, True)
    row = calibration([first, later, o_first, o_later])["live:BULLISH_SETUP"]
    assert (row["n"], row["hits"]) == (1, 0)


def test_review49_a_later_prediction_in_a_settled_slot_never_changes_the_cap():
    from tools.unified_analysis.experience import calibration

    history = _cal_records([(i * 24, i % 3 != 0) for i in range(1, 40)])
    first, later, (o_first, o_later) = _slot_pair("x-first", "0-later", True, False)
    settled = history + [first, o_first]
    before = calibration(settled)
    for tail in ([later], [later, o_later]):          # unsettled, then settled with the opposite result
        assert calibration(settled + tail) == before
        assert _cap(settled + tail) == _cap(settled)


def test_review49_one_entry_counts_once_per_symbol_and_once_per_key():
    from tools.unified_analysis.experience import calibration

    btc, _, (o_btc, _) = _slot_pair("btc", "unused-1", True, True, symbol="BTCUSDT")
    eth, _, (o_eth, _) = _slot_pair("eth", "unused-2", False, False, symbol="ETHUSDT")
    row = calibration([btc, eth, o_btc, o_eth])["live:BULLISH_SETUP"]
    assert (row["n"], row["hits"]) == (2, 1)                      # two symbols on one entry: both are samples
    live, _, (o_live, _) = _slot_pair("live", "unused-3", True, True, roster="live")
    hist, _, (o_hist, _) = _slot_pair("hist", "unused-4", False, False, roster="hist")
    cal = calibration([live, hist, o_live, o_hist])
    assert (cal["live:BULLISH_SETUP"]["n"], cal["hist:BULLISH_SETUP"]["n"]) == (1, 1)   # two keys: one sample each


# ---------------------------------------------------------------- review 48 M2: behaviours the tests did not pin


def test_m2_the_neutral_bound_counts_a_missing_source_fully_against():
    # NB-5 on the range path: with only technical and regime present (2 of 6), the four missing sources count -1 each
    from tools.unified_analysis.contracts import AgentStatus, SpecialistReport, Stance
    from tools.unified_analysis.decision import neutral_bound
    from tools.unified_analysis.specialists import ROSTERS

    two = (SpecialistReport("technical", AgentStatus.OK, Stance.NEUTRAL, 0.5),
           SpecialistReport("regime", AgentStatus.OK, Stance.NEUTRAL, 0.5))
    weights = ROSTERS["live"]
    total = sum(weights.values(), Decimal("0"))
    expected = (Decimal("0.5") * weights["technical"] + Decimal("0.5") * weights["regime"]
                - sum(w for a, w in weights.items() if a not in ("technical", "regime"))) / total
    assert neutral_bound(two) == expected.quantize(Decimal("0.000001")) < 0
    failed = two + (SpecialistReport("liquidity", AgentStatus.FAILED),)
    assert neutral_bound(failed) == neutral_bound(two)               # a failed source counts like a missing one


def _court(charge_severity="MAJOR", narrative_marker=None, statement="the trend rests on a single stream"):
    prompts = []

    class Recording(FakeAsk):
        def __call__(self, system, prompt, schema):
            prompts.append((schema.get("properties", {}).keys(), prompt))
            return super().__call__(system, prompt, schema)

    narrative = None
    if narrative_marker:
        narrative = {"findings": [{"statement": narrative_marker, "kind": "INTERPRETATION", "stance": "BULLISH",
                                   "strength": 0.9, "cites": ["technical:1h:trend"], "claims": []}]}
    ask = Recording(narrative=narrative, prosecutor={"charges": [{"statement": statement,
                                                                   "cites": ["technical:1h:trend"],
                                                                   "severity": charge_severity}],
                                                     "unresolved_questions": []})
    return ask, prompts


def test_m2_a_model_charge_is_at_most_major_and_never_a_veto():
    ask, _ = _court("MAJOR")
    report = run_analysis(inputs(0.002), ask=ask, max_inference_calls=5)
    charges = [o for o in report.review.objections if o.category == "MODEL_CHARGE"]
    assert charges and all(o.severity.value == "MAJOR" for o in charges)
    assert not any(r.startswith("BLOCKING_OBJECTION") for r in report.risk.rejections)
    assert report.risk.approved == run_analysis(inputs(0.002)).risk.approved


def test_review49_a_charge_with_a_number_word_is_not_counted():
    # "one" is a number word; an unbacked number in a charge leaves it unresolved, never counted (review 49 LOW-1)
    ask, _ = _court("MAJOR", statement="the trend rests on one stream")
    report = run_analysis(inputs(0.002), ask=ask, max_inference_calls=5)
    assert not [o for o in report.review.objections if o.category == "MODEL_CHARGE"]
    assert any("unverified number" in q for q in report.review.unresolved_questions)


def test_review49_a_charge_number_must_come_from_the_findings_the_charge_cites():
    # 83.6 is the 1h RSI claim: counted when the charge cites the RSI finding, not when it cites only the trend
    # finding, even though the number is a real claim elsewhere in the case (review 48 L1, review 49 N17)
    statement = "the 1h RSI of 83.6 is overbought"

    def charges(cites):
        ask, _ = _court("MAJOR", statement=statement)
        ask.prosecutor["charges"][0]["cites"] = cites
        report = run_analysis(inputs(0.002), ask=ask, max_inference_calls=5)
        return [o for o in report.review.objections if o.category == "MODEL_CHARGE"], report.review.unresolved_questions

    counted, _ = charges(["technical:1h:rsi"])
    assert len(counted) == 1
    counted, questions = charges(["technical:1h:trend"])
    assert not counted and any("unverified number" in q for q in questions)


def test_m2_the_case_file_never_carries_the_model_narrative():
    marker = "MODEL-ONLY-NARRATIVE-MARKER"
    ask, prompts = _court(narrative_marker=marker)
    report = run_analysis(inputs(0.002), ask=ask, max_inference_calls=5)
    nar = next(r for r in report.specialists if r.agent == "narrative")
    assert nar.findings and nar.findings[0].statement == marker          # the narrative was accepted ...
    court_prompts = [p for keys, p in prompts if "findings" not in keys]
    assert court_prompts and all(marker not in p and nar.findings[0].finding_id not in p for p in court_prompts)


def _settle_rows(closes, start=0):
    out, price = [], closes[0]
    for i, close in enumerate(closes):
        o = start + i * H
        out.append([o, price, max(price, close), min(price, close), close, 1.0, o + H - 1, 1.0])
        price = close
    return out


def test_m2_a_direction_that_hit_its_invalidation_is_a_miss_even_if_price_came_back():
    pred = {"cutoff_ms": 0, "entry_from_ms": 0, "horizon_ms": 24 * H, "classification": "BULLISH_SETUP",
            "invalidation": [{"operator": "<", "threshold": 95.0}], "confidence": "0.3"}
    clean = _settle_rows([100.0] + [100.0 + i for i in range(1, 24)])
    dipped = _settle_rows([100.0, 94.0] + [100.0 + i for i in range(2, 24)])
    assert evaluate(pred, clean, now_ms=24 * H)["hit"] is True
    out = evaluate(pred, dipped, now_ms=24 * H)
    assert out["signed_return"] > 0.1 and out["invalidated_at_ms"] is not None and out["hit"] is False


def test_m2_the_decision_threshold_is_exactly_twenty_percent():
    fwd = (lambda n, hits: {"n": n, "hits": hits, "forward_n": n, "forward_hits": hits})
    at = run_analysis(inputs(0.002), calibration={"live:BULLISH_SETUP": fwd(20, 1)})       # cap 6/30
    below = run_analysis(inputs(0.002), calibration={"live:BULLISH_SETUP": fwd(18, 0)})    # cap 5/28
    assert at.classification is Classification.BULLISH_SETUP and at.confidence == Decimal("0.2")
    assert below.classification is Classification.INSUFFICIENT_EVIDENCE and below.confidence == 0
    assert Decimal(below.confidence_basis["candidate_confidence"]) == Decimal("0.178571")


def test_m2_the_archive_is_opened_through_an_immutable_read_only_uri(tmp_path, monkeypatch):
    import sqlite3

    from tools.unified_analysis import market_intelligence as mi

    database = tmp_path / "market_data.sqlite3"
    sqlite3.connect(database).close()
    seen = []

    def spy(target, *args, **kwargs):
        seen.append((target, kwargs.get("uri")))
        raise sqlite3.OperationalError("stop here")

    monkeypatch.setattr(mi.sqlite3, "connect", spy)
    with pytest.raises(mi.ArchiveUnavailable):
        mi.read_archive_rows(database, "BTCUSDT", "1h", 0, H)
    assert seen == [(f"{database.resolve().as_uri()}?mode=ro&immutable=1", True)]


def test_m2_unknown_liquidity_or_volatility_is_a_risk_rejection():
    from tools.unified_analysis.decision import assess_risk

    def snapshot(volume, atr):
        view = SimpleNamespace(metric=lambda name: {"quote_volume_24": volume, "atr_pct_14": atr}.get(name))
        return SimpleNamespace(view=lambda tf: view, funding=None)

    empty_review = SimpleNamespace(objections=())
    assert "LIQUIDITY_UNKNOWN" in assess_risk(snapshot(None, 0.01), (), empty_review).rejections
    assert "VOLATILITY_UNKNOWN" in assess_risk(snapshot(1e9, None), (), empty_review).rejections
    assert not any(r.startswith(("LIQUIDITY", "THIN", "VOLATILITY", "EXTREME"))
                   for r in assess_risk(snapshot(1e9, 0.01), (), empty_review).rejections)


# ---------------------------------------------------------------- review 48 L1-L3


@pytest.mark.parametrize("statement", ["to 1e5 soon", "ema 250000 is the target", "RSI 95 extreme",
                                       "seventy thousand dollars next", "price to 70k",
                                       # review 49 LOW-1: non-standard periods, number words, glued digits
                                       "RSI 20 now", "EMA 95 holds", "seventy grand", "up 5x", "a 9pct move",
                                       "half the range", "double top at the high", "one more leg", "2.5E3 next",
                                       # review 50 F-50-2: non-ASCII numerals, digits after a letter, spaced periods
                                       "target \u00bd of range", "price \u216b", "ATH at x7", "to_5", "Q3 lows",
                                       "x70000", "RSI 14 crossing", "EMA 200 sits at the close", "\u0663 legs"])
def test_l1_unbacked_numbers_in_model_text_are_never_kept(statement):
    from tools.unified_analysis.specialists import _numbers_backed

    assert _numbers_backed(statement, ()) is False
    narrative = {"findings": [{"statement": statement, "kind": "INTERPRETATION", "stance": "BULLISH", "strength": 0.9,
                               "cites": ["technical:1h:trend"], "claims": []}]}
    report = run_analysis(inputs(0.002), ask=FakeAsk(narrative=narrative), max_inference_calls=1)
    nar = next(r for r in report.specialists if r.agent == "narrative")
    assert not nar.findings


@pytest.mark.parametrize("statement", ["RSI(14) is high", "EMA20 above EMA50 on 4h", "RSI14 crossing", "SMA(200) support on 1d",
                                       "ATR(14) is wide on 24h", "price is above the trend"])
def test_l1_standard_indicator_periods_are_names_not_numbers(statement):
    from tools.unified_analysis.specialists import _numbers_backed

    assert _numbers_backed(statement, ()) is True


def test_l1_a_cited_charge_with_an_invented_number_is_not_counted():
    ask = FakeAsk(prosecutor={"charges": [{"statement": "insiders will dump 50000 BTC; price to 10",
                                           "cites": ["technical:1h:trend"], "severity": "MAJOR"}],
                              "unresolved_questions": []})
    report = run_analysis(inputs(0.002), ask=ask, max_inference_calls=5)
    assert not [o for o in report.review.objections if o.category == "MODEL_CHARGE"]
    assert any(q.startswith("charge with an unverified number (not counted)") for q in report.review.unresolved_questions)
    assert report.confidence == run_analysis(inputs(0.002)).confidence


def test_l2_an_unrecorded_run_never_overwrites_the_recorded_report(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "collect_binance", lambda symbol: inputs(0.002))
    assert cli.main(["--state-dir", str(tmp_path), "analyze", "--symbol", "BTCUSDT"]) == 0
    recorded = sorted((tmp_path / "reports").iterdir())
    assert len(recorded) == 1
    before = recorded[0].read_bytes()
    monkeypatch.setattr(cli, "collect_binance", lambda symbol: replace(inputs(0.002), funding={
        "available": True, "rate": "0.0004", "band": "CROWDED_LONG"}))
    assert cli.main(["--state-dir", str(tmp_path), "analyze", "--symbol", "BTCUSDT", "--no-record"]) == 0
    names = sorted(p.name for p in (tmp_path / "reports").iterdir())
    assert recorded[0].read_bytes() == before and len(names) == 2 and any(".unrecorded-" in n for n in names)


def test_l3_a_treasury_reading_with_a_non_date_day_is_malformed_not_a_crash():
    from tools.unified_analysis.market_intelligence import build_snapshot

    bad = inputs(0.002, )
    bad = replace(bad, treasury=SimpleNamespace(available=True, observed_date="2026-01-01", ten_year_change_bp=3,
                                                curve_spread_bp=40, reason="OK"))
    snap = build_snapshot(bad)
    assert "treasury:MALFORMED" in snap.problems
    report = run_analysis(bad)
    macro = next(r for r in report.specialists if r.agent == "macro")
    assert macro.status.value == "ABSTAIN"


# ---------------------------------------------------------------- review 49 LOW-5: out-of-roster specialists


@pytest.mark.parametrize("drift", [-0.004, -0.002, -0.0005, 0.0, 0.0005, 0.002, 0.004])
def test_review49_an_out_of_roster_specialist_never_moves_a_hist_result(drift):
    from tools.unified_analysis.specialists import ROSTERS

    # NB-4 on the hist roster: context the roster does not expect never reaches the scenarios, so adding or
    # removing it cannot change the result
    with_ctx = run_analysis(inputs(drift, source="market_archive"))
    without = run_analysis(inputs(drift, source="market_archive", with_context=False))
    assert {r.agent for r in with_ctx.specialists} <= set(ROSTERS["hist"])
    assert (with_ctx.classification, with_ctx.confidence, with_ctx.scenarios) == \
        (without.classification, without.confidence, without.scenarios)


# ---------------------------------------------------------------- review 50 F-50-1: hindsight predictions


def _stamped(entries_and_hits, forward):
    recs = _cal_records(entries_and_hits)
    for r in recs:
        if r["record_type"] == "PREDICTION":
            r["analysis_id"] = r["analysis_id"] + ("f" if forward else "h")
            r["recorded_at_ms"] = r["entry_from_ms"] - H if forward else r["entry_from_ms"] + 25 * H
        else:
            r["analysis_id"] = r["analysis_id"] + ("f" if forward else "h")
    return recs


def test_review50_hindsight_winners_never_raise_the_cap_and_hindsight_losers_lower_it():
    forward = _stamped([(i * 24, i % 4 == 0) for i in range(20)], forward=True)           # 5 of 20: a poor record
    winners = _stamped([(i * 24, True) for i in range(100, 160)], forward=False)          # chosen after the fact
    losers = _stamped([(i * 24, False) for i in range(100, 160)], forward=False)
    honest = _cap(forward)
    assert honest < Decimal("0.5")
    assert _cap(forward + winners) == honest                         # cherry-picked winners change nothing
    assert _cap(forward + losers) < honest                           # an honest bad replay still lowers the cap
    assert _cap(winners) == Decimal("0.5") and _cap(losers) < Decimal("0.5")
    # review 51 F-51-1: winners chosen after the fact cannot cancel honest hindsight misses either
    replay = _stamped([(i * 24, i % 4 == 0) for i in range(200, 220)], forward=False)       # 5 of 20 hindsight
    more_winners = _stamped([(i * 24, True) for i in range(300, 320)], forward=False)
    assert _cap(forward + replay + more_winners) == _cap(forward + replay) < honest
    assert _cap(replay + more_winners) == _cap(replay) < Decimal("0.5")
    # a track without forward counts is all hindsight: its hits count for nothing
    assert calibration_cap({"n": 30, "hits": 29})[0] == calibration_cap({"n": 1, "hits": 0})[0] < Decimal("0.5")
    assert calibration(forward + winners)["live:BULLISH_SETUP"]["forward_n"] == 20


def test_review50_the_cap_stays_monotone_with_mixed_forward_and_hindsight_samples():
    import random

    rng = random.Random(50)
    for _ in range(60):
        base, day = [], 0
        for _ in range(rng.randrange(0, 50)):
            day += 1
            base += _stamped([(day * 24, rng.random() < 0.5)], forward=rng.random() < 0.5)
        for forward in (True, False):
            hit = _stamped([((day + 1) * 24, True)], forward)
            miss = _stamped([((day + 1) * 24, False)], forward)
            assert _cap(base + hit) >= _cap(base) >= _cap(base + miss)


def test_review50_a_prediction_carries_its_wall_clock_record_time(tmp_path):
    from tools.unified_analysis.experience import forward_recorded

    report = run_analysis(inputs(0.002))
    entry = report.entry_from_ms
    early = ExperienceLedger(tmp_path / "a.jsonl").record_prediction(report, now_ms=entry - 1)
    late = ExperienceLedger(tmp_path / "b.jsonl").record_prediction(report, now_ms=entry + 1)
    wall = ExperienceLedger(tmp_path / "c.jsonl").record_prediction(report)
    at_start = ExperienceLedger(tmp_path / "d.jsonl").record_prediction(report, now_ms=entry)
    assert forward_recorded(early) and forward_recorded(at_start) and not forward_recorded(late)
    assert wall["recorded_at_ms"] > entry and not forward_recorded(wall)        # the fixture cutoff is in the past
    assert not forward_recorded({k: v for k, v in early.items() if k != "recorded_at_ms"})
    assert not forward_recorded({**early, "recorded_at_ms": True})


@pytest.mark.parametrize("extra", [{"record_type": "PREDICTION"}, {"analysis_id": "other"}, {"hash": "x"}, {"sequence": 9},
                                   {"prev_hash": "x"}, {"prediction_hash": "x"}, {"hit": "yes"}, {"hit": 1}])
def test_review50_an_outcome_cannot_overwrite_ledger_fields_or_carry_a_non_boolean_hit(tmp_path, extra):
    from tools.unified_analysis.experience import ExperienceLedgerError

    ledger = ExperienceLedger(tmp_path / "e.jsonl")
    report = run_analysis(inputs(0.002))
    pred = ledger.record_prediction(report)
    start = pred["entry_from_ms"]
    outcome = {"first_bar_open_ms": start, "through_ms": start + pred["horizon_ms"], "hit": True, **extra}
    with pytest.raises(ExperienceLedgerError):
        ledger.record_outcome(pred["analysis_id"], outcome)
    assert [r["record_type"] for r in ledger.records()] == ["PREDICTION"]
