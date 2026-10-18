"""Task 017 (registry v5.101): unified analysis - market intelligence, specialists, verification, review, decision.

Every test is deterministic (synthetic bars, scripted model). The failure scenarios the task requires are here:
unavailable providers, malformed responses, stale data, contradictory findings, partial failures, a model stating
wrong numbers, missing agents (NB-5), evidence removal (NB-4), risk rejection against agreement, and the branch that
spends no model call on unusable data.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.market_cycle import INTERVAL_MS, ema as core_ema

from tests._task017_support import AS_OF, CUTOFF, FakeAsk, inputs, klines, rows
from tools.unified_analysis import indicators as ind
from tools.unified_analysis.contracts import (
    AgentStatus,
    Claim,
    Classification,
    Finding,
    FindingKind,
    Severity,
    SpecialistReport,
    Stance,
)
from tools.unified_analysis.market_intelligence import MarketInputs, build_snapshot, collect_binance
from tools.unified_analysis.pipeline import run_analysis
from tools.unified_analysis.scenarios import build_scenarios
from tools.unified_analysis.specialists import (
    DEFAULT_SPECIALISTS,
    ROSTER_WEIGHTS,
    TechnicalAnalyst,
)


# ---------------------------------------------------------------- helpers


class Scripted:
    """A specialist that returns a fixed report (or raises)."""

    def __init__(self, name, report=None, exc=None):
        self.name, self._report, self._exc = name, report, exc
        self.responsibility, self.inputs = "scripted", ()

    def analyze(self, snapshot):
        if self._exc:
            raise self._exc
        return self._report


def replace_specialist(name, new):
    return tuple(new if s.name == name else s for s in DEFAULT_SPECIALISTS)


def checks(report):
    return {c.check_id: c for c in report.verification.checks}


# ---------------------------------------------------------------- indicators


def test_rsi_reference_values():
    assert ind.rsi([100.0] * 30) == 50.0
    assert ind.rsi([float(i) for i in range(1, 31)]) == 100.0
    assert ind.rsi([float(i) for i in range(30, 0, -1)]) == 0.0
    assert ind.rsi([1.0] * 10) is None
    assert ind.rsi([1.0] * 20 + [math.nan]) is None


def test_atr_and_ema_use_trusted_shared_implementations():
    highs, lows, closes = [11.0] * 20, [9.0] * 20, [10.0] * 20
    assert ind.atr(highs, lows, closes) == pytest.approx(2.0)
    closes = [float(100 + i) for i in range(80)]
    assert ind.ema_last(closes, 20) == core_ema(closes, 20)[-1]
    assert ind.pct_change(closes, 20) == pytest.approx(closes[-1] / closes[-21] - 1)
    assert ind.atr(highs[:-1], lows, closes[:20]) is None


# ---------------------------------------------------------------- market intelligence


def test_snapshot_is_usable_with_provenance_and_digests():
    snap = build_snapshot(inputs())
    assert snap.usable and snap.problems == ()
    ids = {s.source_id for s in snap.sources}
    assert {"BTCUSDT:bars:1h", "BTCUSDT:bars:4h", "BTCUSDT:bars:1d", "BTCUSDT:funding",
            "market:fear_greed", "macro:treasury"} <= ids
    bar_ref = next(s for s in snap.sources if s.source_id == "BTCUSDT:bars:1h")
    assert "sha256:" in bar_ref.reference and bar_ref.observed_at < AS_OF


def test_forming_bar_at_the_cutoff_is_never_used():
    k = klines()
    forming = list(k["1h"][-1])
    forming[0] = CUTOFF
    forming[6] = CUTOFF + INTERVAL_MS["1h"] - 1
    forming[4] = forming[2] = 999.0
    k["1h"].append(forming)
    report = run_analysis(inputs(k=k))
    assert report.reference_close == k["1h"][-2][4]


@pytest.mark.parametrize("mutate, reason", [
    (lambda r: r.pop(250), "GAP"),
    (lambda r: r.__setitem__(-1, [r[-1][0], 1, 1, 1, "x", 1, r[-1][6]]), "MALFORMED_ROW"),
    (lambda r: r.__setitem__(-1, [*r[-1][:4], math.nan, *r[-1][5:]]), "NON_FINITE_CLOSE"),
    (lambda r: r.__setitem__(-1, [r[-1][0], 100.0, 90.0, 95.0, 120.0, 1.0, r[-1][6], 1.0]), "INCONSISTENT_OHLC"),
    (lambda r: r.append(list(r[-1])), "UNORDERED_OR_DUPLICATE"),
    (lambda r: [r.pop() for _ in range(5)], "STALE"),
    (lambda r: [r.pop(0) for _ in range(450)], "TOO_FEW_BARS"),
])
def test_defective_primary_bars_end_the_run_without_any_model_call(mutate, reason):
    k = klines()
    mutate(k["1h"])
    ask = FakeAsk(narrative={"findings": []})
    report = run_analysis(inputs(k=k), ask=ask)
    assert report.classification is Classification.INSUFFICIENT_EVIDENCE
    assert report.reason_codes[0] == "DATA_UNUSABLE"
    assert any(reason in p for p in report.metrics["data_problems"])
    assert ask.calls == [] and report.metrics["inference_calls"] == 0
    assert not report.verification.passed and report.specialists == ()


def test_unavailable_bar_provider_is_recorded_not_raised():
    def broken(path):
        raise TimeoutError("down")

    got = collect_binance("BTCUSDT", now=AS_OF, http_get=broken, context=False)
    report = run_analysis(got)
    assert report.classification is Classification.INSUFFICIENT_EVIDENCE
    assert "1h:FETCH_FAILED (TimeoutError)" in report.metrics["data_problems"]


def test_context_providers_failing_or_malformed_make_their_specialists_abstain():
    class Boom:
        def rate(self, symbol):
            raise ConnectionError

        def get_reading(self):
            raise ConnectionError

    got = collect_binance("BTCUSDT", now=AS_OF, http_get=lambda p: klines()[p.split("interval=")[1].split("&")[0]],
                          funding_provider=Boom(), fear_greed_provider=Boom(), treasury_provider=Boom())
    report = run_analysis(got)
    status = {r.agent: r.status for r in report.specialists}
    assert status["derivatives"] is status["sentiment"] is status["macro"] is AgentStatus.ABSTAIN
    assert status["technical"] is AgentStatus.OK
    assert set(report.confidence_basis["missing_sources"]) == {"derivatives", "sentiment", "macro"}


@pytest.mark.parametrize("field, value, problem", [
    ("fear_greed", SimpleNamespace(available=True, value=40, observed_at=AS_OF + timedelta(hours=1), reason="OK"),
     "fear_greed:AFTER_CUTOFF"),
    ("fear_greed", SimpleNamespace(available=True, value=40, observed_at=AS_OF - timedelta(days=3), reason="OK"),
     "fear_greed:STALE"),
    ("fear_greed", SimpleNamespace(available=True, value=140, observed_at=AS_OF, reason="OK"), "fear_greed:MALFORMED"),
    ("fear_greed", SimpleNamespace(available=False, value=None, observed_at=None, reason="HTTP_ERROR"),
     "fear_greed:HTTP_ERROR"),
    ("treasury", SimpleNamespace(available=True, observed_date=AS_OF.date(), ten_year_change_bp=1,
                                 curve_spread_bp=1, reason="OK"), "treasury:AFTER_CUTOFF"),
    ("funding", {"available": True, "rate": "0.5", "band": "CROWDED_LONG"}, "funding:IMPLAUSIBLE"),
    ("funding", {"available": True, "rate": None}, "funding:MALFORMED"),
])
def test_context_lookahead_stale_and_malformed_are_refused(field, value, problem):
    base = inputs()
    snap = build_snapshot(replace(base, **{field: value}))
    assert problem in snap.problems
    assert {"fear_greed": snap.fear_greed, "treasury": snap.treasury, "funding": snap.funding}[field] is None


def test_cutoff_after_fetch_time_is_untrusted():
    base = inputs()
    snap = build_snapshot(replace(base, fetched_at=AS_OF - timedelta(hours=2)))
    assert not snap.usable and "CUTOFF_AFTER_FETCH" in snap.problems


# ---------------------------------------------------------------- end-to-end classifications


def test_uptrend_reaches_review_verification_and_a_bullish_classification():
    report = run_analysis(inputs(0.002))
    assert report.classification is Classification.BULLISH_SETUP
    assert report.primary_scenario == "BULL"
    assert report.verification.passed and report.risk.approved
    assert Decimal("0") < report.confidence <= Decimal("0.5")          # uncalibrated cap
    assert report.confidence_basis["calibration"]["status"] == "UNCALIBRATED"
    assert report.confidence_basis["calibrated_probability"] is False
    assert any(o.category == "EVIDENCE_CONCENTRATION" for o in report.review.objections)
    bull = next(s for s in report.scenarios if s.name == "BULL")
    assert bull.invalidation and bull.invalidation[0].operator == "<"
    assert any(c.check_id.startswith("finding:technical") and c.status.value == "PASS"
               for c in report.verification.checks)
    assert report.note.startswith("Advisory")
    assert report.to_dict()["classification"] == "BULLISH_SETUP"


def test_downtrend_is_bearish_with_an_upper_invalidation():
    report = run_analysis(inputs(-0.002))
    assert report.classification is Classification.BEARISH_SETUP
    bear = next(s for s in report.scenarios if s.name == "BEAR")
    assert bear.invalidation[0].operator == ">"


def test_review_objections_change_the_final_confidence():
    report = run_analysis(inputs(0.002))
    raw = Decimal(report.confidence_basis["raw"])
    majors = report.confidence_basis["major_objections"]
    assert majors >= 1
    assert report.confidence == min(raw - Decimal("0.10") * majors, Decimal("0.50"))


def test_contradictory_evidence_is_insufficient_not_a_direction():
    strong = lambda agent, stance, group: SpecialistReport(agent, AgentStatus.OK, stance, 0.9, (Finding(
        f"{agent}:x", agent, FindingKind.OBSERVED_FACT, f"{agent} view", stance, 0.9, ("BTCUSDT:bars:1h",), (),
        group),))
    specs = (Scripted("technical", strong("technical", Stance.BULLISH, "g1")),
             Scripted("regime", strong("regime", Stance.BULLISH, "g2")),
             Scripted("liquidity", strong("liquidity", Stance.BEARISH, "g3")),
             Scripted("derivatives", strong("derivatives", Stance.BEARISH, "g4")))
    report = run_analysis(inputs(), specialists=specs)
    assert report.classification is Classification.INSUFFICIENT_EVIDENCE
    assert checks(report)["consistency:contradiction"].status.value == "FAIL"


def test_a_failing_specialist_is_a_missing_source_and_never_agreement():
    full = run_analysis(inputs(0.002))
    broken = run_analysis(inputs(0.002), specialists=replace_specialist("regime", Scripted("regime", exc=RuntimeError("x"))))
    regime = next(r for r in broken.specialists if r.agent == "regime")
    assert regime.status is AgentStatus.FAILED and "RuntimeError" in regime.reason
    assert "regime" in broken.confidence_basis["missing_sources"]
    assert Decimal(broken.confidence_basis.get("raw", "0")) < Decimal(full.confidence_basis["raw"])
    assert checks(broken)["agent:regime"].blocking is False


def test_a_malformed_specialist_report_is_failed():
    report = run_analysis(inputs(0.002), specialists=replace_specialist("macro", Scripted("macro", report={"x": 1})))
    assert next(r for r in report.specialists if r.agent == "macro").reason == "MALFORMED_REPORT"


def test_nb5_expected_roster_is_the_denominator():
    """With most of the roster missing, two agreeing agents cannot produce a confident consensus."""
    only_two = tuple(s for s in DEFAULT_SPECIALISTS if s.name in ("technical", "regime"))
    report = run_analysis(inputs(0.002), specialists=only_two)
    assert set(report.confidence_basis["expected_sources"]) == set(ROSTER_WEIGHTS)
    assert Decimal(report.confidence_basis["coverage"]) == Decimal("0.5")
    assert report.classification is not Classification.BULLISH_SETUP or report.confidence < Decimal("0.2")


def test_nb4_removing_any_specialists_never_raises_confidence():
    base = run_analysis(inputs(0.002))
    names = [s.name for s in DEFAULT_SPECIALISTS]
    for k in range(1, len(names)):
        for removed in itertools.combinations(names, k):
            kept = tuple(s for s in DEFAULT_SPECIALISTS if s.name not in removed)
            report = run_analysis(inputs(0.002), specialists=kept)
            assert report.confidence <= base.confidence, removed
            if report.classification in (Classification.BULLISH_SETUP, Classification.BEARISH_SETUP):
                assert report.classification is base.classification


def test_unexpected_roster_member_is_not_counted():
    extra = Scripted("hype_bot", SpecialistReport("hype_bot", AgentStatus.OK, Stance.BULLISH, 1.0, ()))
    base = run_analysis(inputs(0.002))
    report = run_analysis(inputs(0.002), specialists=DEFAULT_SPECIALISTS + (extra,))
    assert report.confidence == base.confidence
    assert "hype_bot" not in report.confidence_basis["expected_sources"]


# ---------------------------------------------------------------- verification of claims


def test_a_wrong_deterministic_number_fails_verification():
    class Lying(TechnicalAnalyst):
        def analyze(self, snapshot):
            good = super().analyze(snapshot)
            f = good.findings[0]
            bad = replace(f, claims=(Claim("ema_50", f.claims[2].timeframe, f.claims[2].value * 1.01),))
            return replace(good, findings=(bad,) + good.findings[1:])

    report = run_analysis(inputs(0.002), specialists=replace_specialist("technical", Lying()))
    assert report.classification is Classification.INSUFFICIENT_EVIDENCE
    assert report.reason_codes[0] == "VERIFICATION_FAILED"
    assert any(c.check_id.startswith("finding:technical") and c.blocking for c in report.verification.failures)


def test_a_finding_citing_an_unknown_source_fails():
    rep = SpecialistReport("technical", AgentStatus.OK, Stance.BULLISH, 0.8, (Finding(
        "technical:x", "technical", FindingKind.OBSERVED_FACT, "made up", Stance.BULLISH, 0.8, ("nowhere",)),))
    report = run_analysis(inputs(0.002), specialists=replace_specialist("technical", Scripted("technical", rep)))
    assert report.reason_codes[0] == "VERIFICATION_FAILED"


def _narrative(**over):
    item = {"statement": "trend is intact", "kind": "INTERPRETATION", "stance": "BULLISH", "strength": 0.9,
            "cites": ["technical:1h:trend"], "claims": []}
    item.update(over)
    return {"findings": [item]}


def test_model_narrative_with_a_correct_number_is_accepted_and_capped():
    close = run_analysis(inputs(0.002)).reference_close
    ask = FakeAsk(narrative=_narrative(claims=[{"metric": "close", "timeframe": "1h", "value": round(close, 2)}]))
    report = run_analysis(inputs(0.002), ask=ask, max_inference_calls=1)
    nar = next(r for r in report.specialists if r.agent == "narrative")
    assert nar.status is AgentStatus.OK and nar.findings[0].strength == 0.3 and nar.findings[0].model_generated
    assert report.verification.passed and report.metrics["inference_calls"] == 1


@pytest.mark.parametrize("over, expect_ok", [
    ({"claims": [{"metric": "rsi_14", "timeframe": "1h", "value": 12.0}]}, False),      # wrong number
    ({"claims": [{"metric": "moon_score", "timeframe": "1h", "value": 1.0}]}, False),   # unverifiable metric
    ({"kind": "OBSERVED_FACT"}, False),                                                # a model stating a fact
    ({"cites": ["invented:id"]}, False),                                               # no real citation
    ({"stance": "SIDEWAYS"}, False),                                                   # malformed enum
])
def test_model_findings_that_fail_verification_are_dropped_not_trusted(over, expect_ok):
    ask = FakeAsk(narrative=_narrative(**over))
    report = run_analysis(inputs(0.002), ask=ask, max_inference_calls=1)
    det = run_analysis(inputs(0.002))
    narrative_in = [f for s in report.scenarios for f in s.supporting if f.startswith("narrative")]
    assert narrative_in == []
    assert report.classification is det.classification       # the model cannot move the result by lying
    assert report.verification.passed                         # dropped model items do not fail the run


def test_model_unavailable_abstains_and_the_run_continues():
    report = run_analysis(inputs(0.002), ask=FakeAsk(), max_inference_calls=5)
    nar = next(r for r in report.specialists if r.agent == "narrative")
    assert nar.status is AgentStatus.ABSTAIN and nar.reason.startswith("MODEL_")
    assert report.review.court_status == "ABSTAINED"
    assert report.classification is run_analysis(inputs(0.002)).classification


# ---------------------------------------------------------------- scenarios


def test_findings_from_one_data_stream_count_once():
    snap = build_snapshot(inputs())
    many = tuple(Finding(f"t{i}", "technical", FindingKind.OBSERVED_FACT, "x", Stance.BULLISH, 0.5,
                         ("BTCUSDT:bars:1h",), (), "price:BTCUSDT") for i in range(5))
    one = (Finding("s", "sentiment", FindingKind.OBSERVED_FACT, "y", Stance.BEARISH, 0.5, (), (), "sentiment:market"),)
    scenarios, primary, _ = build_scenarios(snap, many + one)
    bull, bear = scenarios[0], scenarios[1]
    assert bull.support_score == bear.support_score == 0.5
    assert primary == "NEUTRAL"


# ---------------------------------------------------------------- adversarial review (court)


def _juror(vote):
    return {"vote": vote, "reason": "r", "deciding_finding": "technical:1h:trend", "would_flip_if": "a close below x"}


def test_court_charges_with_citations_lower_confidence_votes_do_not_decide():
    cited = {"charges": [{"statement": "RSI is stretched", "cites": ["technical:1h:rsi"], "severity": "MAJOR"},
                         {"statement": "volume is fading", "cites": ["nowhere"], "severity": "MAJOR"}],
             "unresolved_questions": ["is there an ETF flow?"]}
    upheld = run_analysis(inputs(0.002), ask=FakeAsk(prosecutor={"charges": [], "unresolved_questions": []},
                                                     juror=_juror("UPHOLD")), max_inference_calls=5)
    rejected = run_analysis(inputs(0.002), ask=FakeAsk(prosecutor={"charges": [], "unresolved_questions": []},
                                                       juror=_juror("REJECT")), max_inference_calls=5)
    charged = run_analysis(inputs(0.002), ask=FakeAsk(prosecutor=cited, juror=_juror("UPHOLD")), max_inference_calls=5)
    assert upheld.review.court_status == rejected.review.court_status == "COMPLETE"
    assert rejected.review.tally["REJECT"] == 3
    # a unanimous REJECT adds one MINOR objection only: the vote is recorded, never decisive
    assert rejected.classification is upheld.classification and rejected.confidence == upheld.confidence
    assert any(o.category == "JURY_MAJORITY_REJECTS" and o.severity is Severity.MINOR for o in rejected.review.objections)
    # a cited charge is a MAJOR objection and lowers confidence; the uncited one is only a question
    assert charged.confidence < upheld.confidence
    model_objs = [o for o in charged.review.objections if o.reviewer == "model_prosecutor"]
    assert len(model_objs) == 1 and model_objs[0].targets == ("technical:1h:rsi",)
    assert any("uncited charge" in q for q in charged.review.unresolved_questions)
    assert any("would flip if" in q for q in charged.review.unresolved_questions)
    assert "not statistically" in charged.review.independence_note


def test_court_jurors_are_called_separately_with_distinct_lenses_and_budget_is_respected():
    ask = FakeAsk(narrative=_narrative(), prosecutor={"charges": [], "unresolved_questions": []}, juror=_juror("UPHOLD"))
    report = run_analysis(inputs(0.002), ask=ask, max_inference_calls=3)
    kinds = [k for k, _ in ask.calls]
    assert kinds == ["narrative", "prosecutor", "juror"]
    assert report.metrics["inference_calls"] == 3 <= report.metrics["inference_budget"]
    ask2 = FakeAsk(narrative=_narrative(), prosecutor={"charges": [], "unresolved_questions": []}, juror=_juror("UPHOLD"))
    run_analysis(inputs(0.002), ask=ask2, max_inference_calls=5)
    lenses = [s for k, s in ask2.calls if k == "juror"]
    assert len(lenses) == 3 and len(set(lenses)) == 3


def test_a_failed_juror_is_no_vote_never_a_vote_written_for_it():
    answers = iter([_juror("UPHOLD"), None, _juror("UPHOLD")])
    ask = FakeAsk(prosecutor={"charges": [], "unresolved_questions": []}, juror=lambda s: next(answers))
    report = run_analysis(inputs(0.002), ask=ask, max_inference_calls=5)
    assert report.review.court_status == "PARTIAL"
    assert report.review.tally["NO VOTE"] == 1 and report.review.tally["UPHOLD"] == 2


def _neutral(agent, group):
    return Scripted(agent, SpecialistReport(agent, AgentStatus.OK, Stance.NEUTRAL, 0.6, (Finding(
        f"{agent}:range", agent, FindingKind.OBSERVED_FACT, f"{agent}: range", Stance.NEUTRAL, 0.6,
        ("BTCUSDT:bars:1h",), (), group),), reason="anchored=SIDEWAYS; restrictive=False"))


def test_court_does_not_sit_without_a_directional_thesis():
    specs = tuple(_neutral(n, f"g:{n}") if n in ("technical", "regime") else s for n, s in
                  ((s.name, s) for s in DEFAULT_SPECIALISTS))
    ask = FakeAsk(narrative={"findings": []}, prosecutor={"charges": [], "unresolved_questions": []},
                  juror=_juror("UPHOLD"))
    report = run_analysis(inputs(0.002), specialists=specs, ask=ask, max_inference_calls=5)
    assert report.primary_scenario == "NEUTRAL"
    assert report.classification is Classification.NEUTRAL_RANGE
    assert report.review.court_status == "NOT_RUN"
    assert [k for k, _ in ask.calls] == ["narrative"]          # no prosecutor, no juror: nothing to try
    assert report.confidence <= Decimal("0.5")


# ---------------------------------------------------------------- risk


def test_risk_rejects_a_unanimous_positive_view_on_thin_liquidity():
    report = run_analysis(inputs(0.002, k=klines(0.002, quote_scale=1.0)))
    assert report.classification is Classification.RISK_REJECTED
    assert any(r.startswith("THIN_LIQUIDITY") for r in report.risk.rejections)
    assert report.confidence == 0


def test_restrictive_regime_is_blocking_and_cannot_be_outvoted():
    class PanicRegime:
        name, responsibility, inputs = "regime", "scripted", ()

        def analyze(self, snapshot):
            return SpecialistReport("regime", AgentStatus.OK, Stance.BULLISH, 1.0, (Finding(
                "regime:anchored", "regime", FindingKind.INTERPRETATION, "PANIC", Stance.BULLISH, 1.0,
                ("BTCUSDT:bars:1h",), (), "regime:other"),), reason="anchored=PANIC; restrictive=True")

    ask = FakeAsk(prosecutor={"charges": [], "unresolved_questions": []}, juror=_juror("UPHOLD"))
    report = run_analysis(inputs(0.002), specialists=replace_specialist("regime", PanicRegime()), ask=ask,
                          max_inference_calls=5)
    assert report.classification is Classification.RISK_REJECTED
    assert "REGIME_PANIC" in report.risk.rejections
    assert any(o.severity is Severity.BLOCKING for o in report.review.objections)
    assert report.review.tally.get("UPHOLD") == 3       # the jury agreed; the risk rejection still stands


def test_extreme_volatility_is_recorded_as_a_risk_rejection_and_never_directional():
    report = run_analysis(inputs(0.002, k=klines(0.002, vol=0.06)))
    assert report.classification not in (Classification.BULLISH_SETUP, Classification.BEARISH_SETUP)
    assert any(r.startswith("EXTREME_VOLATILITY") for r in report.risk.rejections)


# ---------------------------------------------------------------- calibration cap


def test_measured_track_record_caps_and_never_raises_confidence():
    det = run_analysis(inputs(0.002))
    low = {"live:BULLISH_SETUP": {"measured": True, "wilson_lower": 0.21, "n": 40, "hit_rate": 0.6}}
    high = {"live:BULLISH_SETUP": {"measured": True, "wilson_lower": 0.99, "n": 400, "hit_rate": 0.99}}
    hist_only = {"hist:BULLISH_SETUP": {"measured": True, "wilson_lower": 0.99, "n": 400, "hit_rate": 0.99}}
    capped = run_analysis(inputs(0.002), calibration=low)
    lifted = run_analysis(inputs(0.002), calibration=high)
    other = run_analysis(inputs(0.002), calibration=hist_only)
    assert capped.confidence == Decimal("0.21")
    assert lifted.confidence == Decimal(lifted.confidence_basis["raw"]) - Decimal(lifted.confidence_basis["penalty"])
    assert lifted.confidence <= Decimal(det.confidence_basis["raw"])
    assert other.confidence == det.confidence           # a historical record never calibrates a live analysis


def test_historical_roster_is_declared_for_archive_replays():
    report = run_analysis(inputs(0.002, source="market_archive", with_context=False))
    assert report.confidence_basis["roster"] == "hist"
    assert set(report.confidence_basis["expected_sources"]) == {"technical", "regime", "liquidity"}
    assert report.analysis_id.endswith("-hist-det")
    live = run_analysis(inputs(0.002, with_context=False))
    assert live.analysis_id.endswith("-live-det")
    assert live.confidence < report.confidence or live.classification is Classification.INSUFFICIENT_EVIDENCE


def test_timings_and_costs_are_measured():
    ask = FakeAsk(narrative=_narrative(), prosecutor={"charges": [], "unresolved_questions": []}, juror=_juror("UPHOLD"))
    report = run_analysis(inputs(0.002), ask=ask)
    assert report.metrics["timings"]["total_ms"] >= 0
    assert Decimal(report.metrics["cost_usd"]) == Decimal("0.01") * report.metrics["inference_calls"]
