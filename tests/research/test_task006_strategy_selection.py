"""Task 006: multi-strategy comparison and selection (registry v5.89 grant, research only).

Unit tests pin the statistics (block-bootstrap p-value, effect size, confidence
interval, Sharpe/Sortino, drawdown), EV under real costs, the regime split and the
no-lookahead regime labels. Integration tests run the whole cycle on the canonical
registry: Task 005 registration -> one sealed run per hypothesis -> its single TEST
evaluation -> family adjudication (BH, sealed Bonferroni) -> the read-only shortlist
with its correlation guard, plus every refusal and failure path.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from research import hypothesis_generation as hg
from research import strategy_evaluation as se
from research.hypothesis_registry import HypothesisRegistry
from research.lifecycle import HypothesisState
from research.screening import ScreeningSpec
from tests.research.test_task005_hypothesis_pipeline import candles, history, HISTORY_START, NOW, NOW_MS
from tools import backtest_replay as bt
from tools import strategy_compare as sc
from tools import strategy_selection as ss

DAYS = 90  # strategy_evaluation.MIN_DAYS (owner decision 2026-10-09: the 90-day floor)
START = datetime(2100, 1, 1, tzinfo=timezone.utc)
START_MS = int(START.timestamp() * 1000)
DAY_NAMES = [(START + timedelta(days=i)).date().isoformat() for i in range(DAYS)]


@pytest.fixture(autouse=True)
def state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    (tmp_path / "research").mkdir()


def registry():
    return HypothesisRegistry(registry_path=sc.canonical_registry())


EV_ROW = {"trades": 3, "wins": 2, "win_sum": "30", "losses": 1, "loss_sum": "12", "fees": "3", "slippage": "1.5",
          "funding": "0", "funding_note": "spot replay: no funding"}


def rows(daily, windows=2, ev=EV_ROW):
    """Per-window strategy_compare rows carrying a daily net series."""
    out = []
    for w in range(windows):
        part = {d: str(v) for i, (d, v) in enumerate(zip(DAY_NAMES, daily)) if i * windows // DAYS == w and v != 0}
        out.append({"net_pnl": str(sum(Decimal(v) for v in part.values())), "max_drawdown": "1", "closed_trades": 3,
                    "daily_net": part, "ev": dict(ev)})
    return out


def synthetic(variant_daily, reference_daily, verdict="BETTER", days=DAYS, regimes=None, digest="d" * 64):
    variant = "gen:t:atr_stop=2"
    spec = {"variants": sorted([sc.REFERENCE, variant]), "reference": sc.REFERENCE, "variant_args": {}}
    return {"study": {"status": "REGISTERED", "hypothesis_id": "HYP-0001", "parameters": spec, "result_digest": digest},
            "dataset": {"symbols": {"BTCUSDT": {"first_open": START_MS, "last_open": START_MS + days * 86_400_000 - 60_000}}},
            "table": {variant: rows(variant_daily), sc.REFERENCE: rows(reference_daily)},
            "verdicts": {variant: verdict, sc.REFERENCE: "-"}, "regimes": regimes or {}}


RNG = np.random.default_rng(7)
NOISE = RNG.normal(0, 5, DAYS)


# -- statistics --------------------------------------------------------------------


def test_a_strong_edge_has_a_small_p_value_and_a_null_edge_does_not():
    ref = list(RNG.normal(0, 5, DAYS))
    strong = se.evaluate_result(synthetic([r + 8 + n for r, n in zip(ref, NOISE)], ref), samples=4000)
    null = se.evaluate_result(synthetic([r + n for r, n in zip(ref, NOISE)], ref), samples=4000)
    assert strong.p_value < 0.01 and strong.effect_size > 1 and strong.ci_low > 0
    assert null.p_value > 0.05 and null.ci_low < 0 < null.ci_high
    assert strong.ci_low <= strong.mean_difference <= strong.ci_high
    assert 0 < strong.p_value <= 1 and 0 < null.p_value <= 1  # never exactly 0


def _ar(n, phi, rng):
    e = rng.normal(size=n + 50)
    x = np.zeros(n + 50)
    for i in range(1, n + 50):
        x[i] = phi * x[i - 1] + e[i]
    return x[50:]


@pytest.mark.parametrize("phi, bound", [(0.0, 0.07), (0.3, 0.07), (0.5, 0.07), (0.7, 0.07)])
def test_the_p_value_is_calibrated_under_the_null_at_the_floor(phi, bound):
    """Review F-2: with no edge, p <= 0.05 must happen about 5% of the time at the floor, also with
    day-to-day dependence. 1500 simulations: Monte Carlo SE about 0.6 points."""
    rng = np.random.default_rng(13)
    hits = sum(se.studentized_block_bootstrap(_ar(se.MIN_DAYS, phi, rng), samples=999, seed=i)[0] <= 0.05
               for i in range(1500))
    assert hits / 1500 <= bound


def test_the_old_percentile_bootstrap_would_fail_that_calibration():
    """The method the review rejected, kept here to show the calibration test can tell them apart.
    At the 90-day floor it measures about 7.5% (phi 0.3), 10.3% (phi 0.5) and 15.6% (phi 0.7); phi 0.5
    is used so the gap to the 0.07 bound is clear."""
    rng = np.random.default_rng(13)
    hits = 0
    for i in range(1500):
        d = _ar(se.MIN_DAYS, 0.5, rng)
        idx = se._block_index(len(d), 3, 999, np.random.default_rng(i))
        null = (d - d.mean())[idx].mean(axis=1)
        hits += (1 + np.count_nonzero(null >= d.mean())) / 1000 <= 0.05
    assert hits / 1500 > 0.09


def test_resamples_without_spread_widen_the_interval_never_narrow_it():
    """Review 5 L-B: activity clustered in 10 days leaves many resamples without spread; they count against
    the p-value and leave the interval unbounded (recorded as null) instead of narrowing it."""
    d = np.zeros(se.MIN_DAYS)
    d[40:50] = np.random.default_rng(5).normal(3, 1, 10)
    p, low, high, _ = se.studentized_block_bootstrap(d, samples=999, seed=1)
    assert low == -np.inf and high == np.inf and 0 < p <= 1
    ev = se.evaluate_result(synthetic(list(d), [0.0] * DAYS), samples=999)
    assert ev.ci() == [None, None] and ev.payload()[se.PAYLOAD_KEY]["ci"] == [None, None]
    json.dumps(ev.payload(), allow_nan=False)  # strict JSON: nothing infinite is recorded
    assert se._lowest([1.0, None]) is None and se._lowest([1.0, -2.0]) == -2.0
    ranked = sorted([{"idea": "a", "conservative_ci_low": None}, {"idea": "b", "conservative_ci_low": -1.0},
                     {"idea": "c", "conservative_ci_low": 2.0}], key=se._rank_key)
    assert [e["idea"] for e in ranked] == ["c", "b", "a"]  # review 6 F2: an unbounded bound ranks last


def test_power_is_kept_for_a_real_edge():
    rng = np.random.default_rng(17)
    hits = sum(se.studentized_block_bootstrap(rng.normal(0.8, 1, se.MIN_DAYS), samples=999, seed=i)[0] <= 0.05
               for i in range(300))
    assert hits / 300 > 0.7


def test_the_evaluation_is_reproducible_from_the_result_digest():
    ref = list(RNG.normal(0, 5, DAYS))
    var = [r + 2 + n for r, n in zip(ref, NOISE)]
    a = se.evaluate_result(synthetic(var, ref), samples=2000)
    b = se.evaluate_result(synthetic(var, ref), samples=2000)
    c = se.evaluate_result(synthetic(var, ref, digest="e" * 64), samples=2000)
    assert (a.p_value, a.ci_low) == (b.p_value, b.ci_low) and a.stats["seed"] != c.stats["seed"]


def test_risk_statistics():
    var = [10, -5, 10, -5] * 5
    ev = se.evaluate_result(synthetic(var, [0] * DAYS), samples=500)
    assert ev.stats["max_drawdown"] == 5.0 and ev.stats["sharpe"] > 0 and ev.stats["sortino"] > ev.stats["sharpe"]
    assert ev.stats["reference_max_drawdown"] == 0.0 and len(ev.variant_daily) == DAYS


@pytest.mark.parametrize("mangle, error", [
    (lambda r: r.update(dataset={}), "dataset span"),
    (lambda r: r["table"][sc.REFERENCE][0].pop("daily_net"), "daily_net"),
    (lambda r: r["table"][sc.REFERENCE][0]["daily_net"].update({"2099-12-31": "5"}), "outside the sealed window"),
    (lambda r: r["table"][sc.REFERENCE][0]["daily_net"].update({DAY_NAMES[0]: "NaN"}), "not finite"),
    (lambda r: r["table"][sc.REFERENCE][0].pop("ev"), "EV"),
    (lambda r: r["table"][sc.REFERENCE][0]["ev"].update(wins=-1), "EV count"),
    (lambda r: r["study"].update(status="EXPLORATORY"), "registered generated study"),
    (lambda r: r["study"]["parameters"].pop("variant_args"), "registered generated study"),
    (lambda r: r["study"]["parameters"].update(variants=sorted([sc.REFERENCE, "a", "b"])), "exactly one variant"),
])
def test_malformed_or_non_generated_results_are_refused(mangle, error):
    result = synthetic(list(NOISE + 3), [0.0] * DAYS)
    mangle(result)
    with pytest.raises(se.EvaluationError, match=error):
        se.evaluate_result(result, samples=200)


def test_too_few_days_and_zero_variance_are_refused_not_scored():
    with pytest.raises(se.InsufficientSampleError):
        se.evaluate_result(synthetic([1.0] * 5, [0.0] * 5, days=5), samples=200)
    with pytest.raises(se.InsufficientSampleError, match="no spread"):
        se.evaluate_result(synthetic([3.0] * DAYS, [1.0] * DAYS), samples=200)
    with pytest.raises(se.InsufficientSampleError, match="differ"):  # a variant identical to the reference
        se.evaluate_result(synthetic(list(NOISE), list(NOISE)), samples=200)


# -- EV under real costs ---------------------------------------------------------------


def test_ev_decomposition_under_fees_and_slippage():
    ev = se.evaluate_result(synthetic(list(NOISE + 3), [0.0] * DAYS), samples=200).stats["ev"]["variant"]
    # 2 windows x (2 wins of 30, 1 loss of 12, fees 3, slippage 1.5): P(W)=2/3 E(W)=15 P(L)=1/3 E(L)=12 C=1.5
    assert Decimal(ev["p_win"]) == Decimal(2) / 3 and Decimal(ev["avg_win"]) == 15 and Decimal(ev["avg_loss"]) == 12
    assert Decimal(ev["cost_per_trade"]) == Decimal("1.5") and Decimal(ev["funding"]) == 0
    assert abs(Decimal(ev["ev_per_trade"]) - Decimal("4.5")) < Decimal("1e-20")
    assert ev["funding_note"] == "spot replay: no funding"


def test_ev_components_recover_slippage_exactly_from_replay_trades():
    s = Decimal("0.0005")  # 5 bps
    buy, sell = Decimal("100") * (1 + s), Decimal("110") * (1 - s)
    fee_in, fee_out = buy * Decimal("0.001"), sell * Decimal("0.001")
    win = bt.Trade("BTCUSDT", "t0", buy, Decimal("1"), buy, fee_in, "core", False, "2100-01-01T10:00:00+00:00",
                   sell, fee_out)
    small_loss = bt.Trade("BTCUSDT", "t1", buy, Decimal("1"), buy, fee_in, "core", False, "2100-01-02T10:00:00+00:00",
                          Decimal("100") * (1 - s), Decimal("100") * (1 - s) * Decimal("0.001"))
    result = bt.Result(trades=[win, small_loss])
    ev = sc.ev_components(result, 5)
    slip_win = Decimal("100") * s + Decimal("110") * s
    assert abs(Decimal(ev["slippage"]) - slip_win - Decimal("100") * s * 2) < Decimal("1e-20")  # 0.205 exactly
    assert (ev["wins"], ev["losses"]) == (1, 1)  # the round trip at an unchanged reference price is a loss before costs
    assert Decimal(ev["win_sum"]) == Decimal("10") and Decimal(ev["loss_sum"]) == 0
    daily = sc.daily_net(result)
    assert list(daily) == ["2100-01-01", "2100-01-02"] and Decimal(daily["2100-01-01"]) == win.net


def test_positions_open_at_the_window_end_are_marked_to_market():
    """Review 5 M-A: a position still held at the window end is valued at the last close less slippage
    and the exit fee, so a variant cannot hide a loser by holding it; the closed-trade report is unchanged."""
    class AlwaysBuy:
        def analyze_and_decide(self, symbol, market_data):
            return {"symbol": symbol, "action": "BUY", "confidence": 95.0, "risk_level": "LOW"}

    flat = [[r[0], "100", "100.1", "99.9", "100", *r[5:]] for r in candles(START_MS, 300)]
    result = bt.replay({"BTCUSDT": flat}, step=20, brain_factory=AlwaysBuy, slippage_bps=5)
    assert result.trades == [] and len(result.open_trades) == 1 and len(result.marked_open) == 1
    held, mark = result.open_trades[0], result.marked_open[0]
    gross = held.quantity * Decimal("100") * (1 - Decimal("0.0005"))
    expected = gross - gross * bt.PAPER_FEE_RATE_PER_SIDE - held.cost - held.entry_fee
    assert mark.exit_reason == "MARK_TO_MARKET" and abs(mark.net - expected) < Decimal("1e-20")
    assert mark.net < -10  # fees and slippage on about 4000: a real loss, not hidden
    assert mark.exit_time.startswith(DAY_NAMES[0]) and held.exit_price == 0  # open_trades itself is unchanged
    assert sc.daily_net(result) == {DAY_NAMES[0]: str(mark.net)}
    ev = sc.ev_components(result, 5)
    assert (ev["marked_open"], ev["trades"], ev["losses"]) == (1, 1, 1)
    summary = bt.summarize(result)
    assert (summary["closed_trades"], summary["open_at_end"], summary["net_pnl"]) == (0, 1, 0)  # BETTER basis kept


def _hold_or_sell(prices, sell_last, **kw):
    """Review 6 F1: the same replay, holding to the window end or selling at the last decision."""
    data = [[START_MS + i * 60_000, str(p), str(p), str(p), str(p), "10", START_MS + i * 60_000 + 59_999, "0", 3, "4",
             "400", "0"] for i, p in enumerate(prices)]
    calls = len(range(bt.WINDOW, len(prices), 20))

    class Brain:
        n = 0

        def analyze_and_decide(self, symbol, market_data):
            Brain.n += 1
            action = "SELL" if sell_last and Brain.n >= calls else "BUY"
            return {"symbol": symbol, "action": action, "confidence": 95.0, "risk_level": "LOW"}

    return bt.replay({"BTCUSDT": data}, step=20, brain_factory=Brain, **kw)


RISE = [Decimal(100)] * 260 + [Decimal(100) + Decimal(i) / 100 for i in range(1, 101)] + [Decimal(101)] * 80 \
    + [Decimal(102)] * 200


@pytest.mark.parametrize("kw", [dict(slippage_bps=5), dict(staged=True, slippage_bps=7),
                                dict(staged=True, slippage_bps=7, next_open_fill=True)])
def test_a_mark_equals_a_real_sell_at_the_window_end(kw):
    """Review 6 F1: with a flat tail the mark is exactly what selling would have booked, including tranche
    adds, partial take-profit sells, slippage and next-open fills."""
    held, sold = _hold_or_sell(RISE, False, **kw), _hold_or_sell(RISE, True, **kw)
    assert held.trades == [] and len(held.marked_open) == 1 and sold.trades and not sold.open_trades
    if kw.get("staged"):
        assert held.partial_sells > 0 and held.tranche_adds > 0  # the risky paths are really exercised
    mark, real = held.marked_open[0], sold.trades[-1]
    assert abs(mark.net - real.net) < Decimal("1e-20")
    ev_m, ev_s = sc.ev_components(held, kw["slippage_bps"]), sc.ev_components(sold, kw["slippage_bps"])
    assert all(abs(Decimal(ev_m[k]) - Decimal(ev_s[k])) < Decimal("1e-20") for k in ("win_sum", "loss_sum", "fees",
                                                                                      "slippage"))


def test_a_corrupt_last_close_falls_back_to_the_last_valid_one():
    held = _hold_or_sell([Decimal(100)] * 299 + [Decimal(0)], False, slippage_bps=5)
    clean = _hold_or_sell([Decimal(100)] * 300, False, slippage_bps=5)
    [mark], [ref] = held.marked_open, clean.marked_open
    assert mark.net == ref.net and mark.exit_time < ref.exit_time  # valued and dated at the last valid candle


# -- regimes --------------------------------------------------------------------------


def test_regime_split_and_stability():
    regimes = {d: ("TREND_UP" if i < 10 else "SIDEWAYS") for i, d in enumerate(DAY_NAMES)}
    var = [5 + n if i < 10 else -5 + n for i, n in enumerate(NOISE)]
    ev = se.evaluate_result(synthetic(var, [0.0] * DAYS, regimes=regimes), samples=200)
    assert ev.stats["regimes"]["TREND_UP"]["days"] == 10 and ev.stats["regimes"]["TREND_UP"]["mean_difference"] > 0
    assert ev.stats["regimes"]["SIDEWAYS"]["mean_difference"] < 0 and ev.stats["regime_stability"] == 0.5
    assert se.evaluate_result(synthetic(var, [0.0] * DAYS), samples=200).stats["regime_stability"] is None


def test_daily_regimes_use_only_the_past():
    data = {"BTCUSDT": candles(START_MS, 1440 * 6)}
    full = sc.daily_regimes(data)
    cut = sc.daily_regimes({"BTCUSDT": data["BTCUSDT"][:1440 * 4]})
    assert all(full[d] == cut[d] for d in cut)  # later candles never change an earlier day's label
    assert full[DAY_NAMES[0]] == "UNKNOWN" and set(full.values()) <= {"UNKNOWN", "TREND_UP", "TREND_DOWN", "SIDEWAYS",
                                                                        "HIGH_VOL", "PANIC", "TRANSITION"}


def test_a_day_label_never_sees_that_day_s_own_candles(monkeypatch):
    """Review 5 L-A: a crash at noon of day 4 may label day 5, never day 4 itself (same-day lookahead)."""
    import tools.regime_engine as re_

    monkeypatch.setattr(re_, "classify", lambda closes: {"regime": "PANIC" if closes and closes[-1] < 50 else "SIDEWAYS"})
    crash = START_MS + 4 * 86_400_000 + 12 * 3_600_000
    data = [[r[0], "100", "100", "100", "10" if r[0] >= crash else "100", *r[5:]] for r in candles(START_MS, 1440 * 6)]
    labels = sc.daily_regimes({"BTCUSDT": data})
    assert [labels[d] for d in DAY_NAMES[3:6]] == ["SIDEWAYS", "SIDEWAYS", "PANIC"]


def test_a_regime_tie_across_the_universe_is_transition(monkeypatch):
    import tools.regime_engine as re_

    monkeypatch.setattr(re_, "classify", lambda closes: {"regime": "TREND_UP" if closes and closes[0] > 150 else "SIDEWAYS"})
    up = candles(START_MS, 1440 * 4)
    down = [[r[0], "200", "201", "199", "200", *r[5:]] for r in up]
    labels = sc.daily_regimes({"AAAUSDT": up, "BBBUSDT": down})
    assert labels[DAY_NAMES[3]] == "TRANSITION"


# -- the whole cycle on the canonical registry --------------------------------------------


def template(**overrides):
    params = dict(name="sel", family_id="FAM-GEN-SEL", author="research", universe=("BTCUSDT",),
                  reference=sc.REFERENCE, reference_args=dict(sc.REALISTIC), base_args=dict(sc.REALISTIC),
                  grid={"atr_stop": ["1.5", 2, 3]}, periods=(START.isoformat(),),
                  economic_rationale="Volatility-scaled stops cut losses in chop.", days=DAYS, windows=2, embargo=0,
                  step=15, exp001=True)
    params.update(overrides)
    return hg.Template(**params)


def register(tmpl=None):
    return hg.run_pipeline(tmpl or template(), sc.canonical_registry(), historical=history(), now=NOW,
                           screening=ScreeningSpec(start_ms=HISTORY_START, end_ms=NOW_MS, cutoff_ms=NOW_MS,
                                                   minimum_trades=0),
                           quick_trades=lambda c, d: 1)


@pytest.fixture(scope="module")
def dataset_file(tmp_path_factory):
    data = {"BTCUSDT": candles(START_MS, 1440 * DAYS)}
    path = tmp_path_factory.mktemp("ds") / "ds.json"
    path.write_text(json.dumps({"manifest": sc.dataset_manifest(data), "data": data}), encoding="utf-8")
    return path


def sealed_run(tmp_path, monkeypatch, dataset_file, hid, variant_daily, verdict="BETTER", reference_daily=None):
    """One registered run of hid whose replay (stubbed) produced these daily nets."""
    reference_daily = [0.0] * DAYS if reference_daily is None else reference_daily

    def fake_compare(data, windows, step, exp001, variants, **kw):
        variant = next(n for n in variants if n != sc.REFERENCE)
        return {"table": {variant: rows(variant_daily, windows), sc.REFERENCE: rows(reference_daily, windows)},
                "verdicts": {variant: verdict, sc.REFERENCE: "-"}}

    monkeypatch.setattr(sc, "compare", fake_compare)
    out = tmp_path / f"{hid}.json"
    assert sc.main(["--dataset", str(dataset_file), "--symbols", "BTCUSDT", "--json", "--days", str(DAYS),
                    "--windows", "2", "--embargo", "0", "--step", "15", "--output", str(out),
                    "--registry", str(sc.canonical_registry()), "--hypothesis", hid]) == 0
    return out


def cli(*argv):
    return ss.main(list(argv))


def family_ids(family="FAM-GEN-SEL"):
    return [r.hypothesis_id for r in registry().family(family)]


def test_the_whole_cycle_adjudicates_a_family_and_clusters_correlated_winners(tmp_path, monkeypatch, dataset_file,
                                                                               capsys):
    register()
    a, b, c = family_ids()
    base = list(np.random.default_rng(3).normal(0, 4, DAYS))
    sealed_run(tmp_path, monkeypatch, dataset_file, a, [10 + x for x in base])
    sealed_run(tmp_path, monkeypatch, dataset_file, b, [9 + x * 1.1 for x in base])  # the same risk, slightly weaker
    sealed_run(tmp_path, monkeypatch, dataset_file, c, list(np.random.default_rng(4).normal(0, 4, DAYS)),
               verdict="NOT PROVEN")
    assert cli("status", "--family", "FAM-GEN-SEL") == 0 and '"ready": false' in capsys.readouterr().out
    for hid in (a, b, c):
        assert cli("evaluate", "--result", str(tmp_path / f"{hid}.json")) == 0
        assert registry().get(hid).state is HypothesisState.TESTED
    capsys.readouterr()
    assert cli("adjudicate", "--family", "FAM-GEN-SEL") == 0
    states = {h: registry().get(h).state for h in (a, b, c)}
    assert states == {a: HypothesisState.CANDIDATE, b: HypothesisState.CANDIDATE, c: HypothesisState.REJECTED}
    capsys.readouterr()
    out = tmp_path / "short.json"
    assert cli("shortlist", "--output", str(out)) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["capital_weights"] is None and report["evidence_eligible"] is False
    [top] = report["shortlist"]
    assert top["hypotheses"] == [a] and [m["idea"] for m in top["cluster"]] and top["cluster"][0]["correlation"] > 0.8
    assert all(k not in json.dumps(report) for k in ("weight\":", "allocation\":", "size\":"))


def _first_row(result):
    return result["table"][next(n for n in result["table"] if n != sc.REFERENCE)][0]


def test_evaluate_refuses_anything_but_a_verified_registered_run(tmp_path, monkeypatch, dataset_file):
    register()
    a = family_ids()[0]
    good = sealed_run(tmp_path, monkeypatch, dataset_file, a, list(NOISE + 5))
    raw = json.loads(good.read_text(encoding="utf-8"))
    for name, mutate in (
        ("exploratory", lambda r: r.update(study={"status": "EXPLORATORY", "evidence_eligible": False})),
        ("edited", lambda r: r["table"][next(n for n in r["table"] if n != sc.REFERENCE)][0].update(net_pnl="999")),
        ("refused", lambda r: r.update(study={"status": "REFUSED", "hypothesis_id": a, "evidence_eligible": False})),
        ("failed", lambda r: r.update(study={"status": "FAILED", "hypothesis_id": a, "evidence_eligible": False})),
        ("relabelled", lambda r: r["study"].update(hypothesis_id=family_ids()[1])),
        # review 5 L-C: every Task 006 input is covered by the result digest
        ("daily_net", lambda r: _first_row(r)["daily_net"].update({next(iter(_first_row(r)["daily_net"])): "999"})),
        ("reference_daily_net", lambda r: r["table"][sc.REFERENCE][0]["daily_net"].update({DAY_NAMES[0]: "-50"})),
        ("ev", lambda r: _first_row(r)["ev"].update(fees="0")),
        ("regime", lambda r: r["regimes"].update({DAY_NAMES[0]: "PANIC"})),
        ("no_regimes", lambda r: r.pop("regimes")),
    ):
        bad = json.loads(json.dumps(raw))
        mutate(bad)
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        assert cli("evaluate", "--result", str(path)) == 2, name
    assert registry().get(a).state is HypothesisState.CALIBRATED  # nothing recorded
    assert cli("evaluate", "--result", str(good)) == 0
    assert cli("evaluate", "--result", str(good)) == 2  # the single test segment is consumed once
    assert len(registry().get(a).evaluations) == 1


def test_a_short_window_is_scored_as_no_evidence_and_counted(tmp_path, monkeypatch, capsys):
    # Review F-3: before, the run was refused and left CALIBRATED forever (a stuck family); now it is
    # recorded once as NO EVIDENCE (p = 1): it stays one of the m tests and can never pass.
    register(template(days=5, family_id="FAM-GEN-SHORT", name="short", grid={"atr_stop": [2]}))
    hid = family_ids("FAM-GEN-SHORT")[0]
    data = {"BTCUSDT": candles(START_MS, 1440 * 5)}
    ds = tmp_path / "short.json"
    ds.write_text(json.dumps({"manifest": sc.dataset_manifest(data), "data": data}), encoding="utf-8")
    monkeypatch.setattr(sc, "compare", lambda data, windows, step, exp001, variants, **kw: {
        "table": {n: [{"net_pnl": "1", "max_drawdown": "0", "closed_trades": 1, "daily_net": {DAY_NAMES[0]: "1"},
                       "ev": dict(EV_ROW)}] * windows for n in variants}, "verdicts": {n: "-" for n in variants}})
    out = tmp_path / "r.json"
    assert sc.main(["--dataset", str(ds), "--symbols", "BTCUSDT", "--json", "--days", "5", "--windows", "2",
                    "--embargo", "0", "--step", "15", "--output", str(out), "--registry", str(sc.canonical_registry()),
                    "--hypothesis", hid]) == 0
    assert cli("evaluate", "--result", str(out)) == 0 and '"NO_EVIDENCE"' in capsys.readouterr().out
    record = registry().get(hid)
    assert record.state is HypothesisState.TESTED and record.test_evaluation.p_value == 1.0
    assert cli("adjudicate", "--family", "FAM-GEN-SHORT") == 0
    assert registry().get(hid).state is HypothesisState.REJECTED


def test_adjudication_waits_for_every_member_and_names_what_blocks_it(tmp_path, monkeypatch, dataset_file, capsys):
    register()
    a, b, c = family_ids()
    sealed_run(tmp_path, monkeypatch, dataset_file, a, list(NOISE + 8))
    sealed_run(tmp_path, monkeypatch, dataset_file, b, list(NOISE + 8))  # b's run "crashes": never evaluated
    assert cli("evaluate", "--result", str(tmp_path / f"{a}.json")) == 0
    capsys.readouterr()
    assert cli("adjudicate", "--family", "FAM-GEN-SEL") == 2
    blocking = json.loads(capsys.readouterr().out)["blocking"]
    assert blocking[c] == "not run yet" and "no TEST evaluation" in blocking[b]
    assert registry().get(a).state is HypothesisState.TESTED  # nothing adjudicated
    # the crashed run is recorded as a failed run and the unrun one is abandoned: both count as p = 1
    # tests (review N-1: once a sibling has run, leaving a member out would shrink m after the fact)
    assert cli("record-failed-run", "--hypothesis", b, "--reason", "process killed") == 0
    assert cli("abandon", "--hypothesis", c, "--reason", "no longer wanted") == 0
    capsys.readouterr()
    assert cli("adjudicate", "--family", "FAM-GEN-SEL") == 0
    assert json.loads(capsys.readouterr().out)["n_tests"] == 3  # the sealed family size
    assert registry().get(a).state is HypothesisState.CANDIDATE and registry().get(b).state is HypothesisState.REJECTED
    assert cli("adjudicate", "--family", "FAM-GEN-SEL") == 2  # adjudicated once


def test_an_incomplete_generated_family_is_not_adjudicated(monkeypatch, capsys):
    real = HypothesisRegistry.register
    calls = []

    def flaky(self, prereg):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(self, prereg)

    monkeypatch.setattr(HypothesisRegistry, "register", flaky)
    register()
    monkeypatch.setattr(HypothesisRegistry, "register", real)
    assert cli("adjudicate", "--family", "FAM-GEN-SEL") == 2
    assert "of its sealed 3 members" in json.loads(capsys.readouterr().out)["reason"]


def test_bonferroni_alpha_rejects_what_bh_alone_would_pass(tmp_path, monkeypatch, dataset_file):
    register(template(correction="BONFERRONI", grid={"atr_stop": [2]}, family_id="FAM-GEN-BONF", name="bonf"))
    [hid] = family_ids("FAM-GEN-BONF")
    assert registry().get(hid).preregistration.alpha == 0.05  # m = 1
    sealed_run(tmp_path, monkeypatch, dataset_file, hid, list(NOISE + 8))
    assert cli("evaluate", "--result", str(tmp_path / f"{hid}.json")) == 0
    assert cli("adjudicate", "--family", "FAM-GEN-BONF") == 0
    assert registry().get(hid).state is HypothesisState.CANDIDATE
    register(template(correction="BONFERRONI", family_id="FAM-GEN-BONF3", name="bonf3",
                      grid={"atr_stop": [4, 5, 6]}))
    assert {registry().get(h).preregistration.alpha for h in family_ids("FAM-GEN-BONF3")} == {0.05 / 3}


def test_a_failing_sealed_check_rejects_even_a_significant_result(tmp_path, monkeypatch, dataset_file):
    register(template(grid={"atr_stop": [2]}, family_id="FAM-GEN-CHECK", name="check"))
    [hid] = family_ids("FAM-GEN-CHECK")
    sealed_run(tmp_path, monkeypatch, dataset_file, hid, list(NOISE + 8), verdict="NOT PROVEN")
    assert cli("evaluate", "--result", str(tmp_path / f"{hid}.json")) == 0
    assert registry().get(hid).test_evaluation.p_value < 0.05
    assert cli("adjudicate", "--family", "FAM-GEN-CHECK") == 0
    assert registry().get(hid).state is HypothesisState.REJECTED  # OUT_OF_SAMPLE (the BETTER rule) failed


def test_a_held_lock_fails_evaluation_and_adjudication_without_writing(tmp_path, monkeypatch, dataset_file, capsys):
    from functools import partial
    from research import registry_lock as rl

    register(template(grid={"atr_stop": [2]}, family_id="FAM-GEN-LOCK", name="lock"))
    [hid] = family_ids("FAM-GEN-LOCK")
    sealed_run(tmp_path, monkeypatch, dataset_file, hid, list(NOISE + 8))
    monkeypatch.setattr(rl, "registry_write_lock", partial(rl.registry_write_lock, timeout_s=0.1))
    rl.lock_path(sc.canonical_registry()).write_text("another writer", encoding="utf-8")
    assert cli("evaluate", "--result", str(tmp_path / f"{hid}.json")) == 2
    assert cli("adjudicate", "--family", "FAM-GEN-LOCK") == 2
    assert "FAILED" in capsys.readouterr().err
    assert registry().get(hid).state is HypothesisState.CALIBRATED


def test_the_shortlist_reads_only_recorded_evaluations_and_lists_complete_ideas_only(tmp_path, monkeypatch,
                                                                                      dataset_file):
    register(template(grid={"atr_stop": [2]}, family_id="FAM-GEN-TWO", name="two",
                      periods=(START.isoformat(), (START + timedelta(days=DAYS + 1)).isoformat())))
    first, second = family_ids("FAM-GEN-TWO")
    sealed_run(tmp_path, monkeypatch, dataset_file, first, list(NOISE + 8))
    assert cli("evaluate", "--result", str(tmp_path / f"{first}.json")) == 0
    assert cli("abandon", "--hypothesis", second, "--reason", "never ran") == 0  # counted as p = 1 (review N-1)
    assert cli("adjudicate", "--family", "FAM-GEN-TWO") == 0
    assert registry().get(first).state is HypothesisState.CANDIDATE
    report = se.shortlist(registry())
    assert report["shortlist"] == []  # one period CANDIDATE, the other rejected: the idea is not listed
    with pytest.raises(se.EvaluationError):
        se.shortlist(registry(), max_correlation=0)


def test_too_little_overlap_is_not_called_uncorrelated():
    a = {d: float(i) for i, d in enumerate(DAY_NAMES[:5])}
    assert se._correlation(a, a) is None
    b = {d: float(i % 7) for i, d in enumerate(DAY_NAMES)}
    assert se._correlation(b, b) == pytest.approx(1.0)


# -- independent review of Task 006: F-1, F-3, F-4 ------------------------------------------


def test_f1_rejecting_siblings_after_their_runs_cannot_shrink_the_family(tmp_path, monkeypatch, dataset_file, capsys):
    register()
    a, b, c = family_ids()
    sealed_run(tmp_path, monkeypatch, dataset_file, a, list(NOISE + 3))
    sealed_run(tmp_path, monkeypatch, dataset_file, b, list(np.random.default_rng(8).normal(0, 4, DAYS)))
    sealed_run(tmp_path, monkeypatch, dataset_file, c, list(np.random.default_rng(9).normal(-2, 4, DAYS)))
    assert cli("evaluate", "--result", str(tmp_path / f"{a}.json")) == 0
    for hid in (b, c):  # their weak results are visible; rejecting them untested would lift a past BH
        registry().advance(hid, HypothesisState.REJECTED)
    capsys.readouterr()
    assert cli("adjudicate", "--family", "FAM-GEN-SEL") == 2
    blocking = json.loads(capsys.readouterr().out)["blocking"]
    assert set(blocking) == {b, c} and all("rejected AFTER its run" in v for v in blocking.values())
    assert registry().get(a).state is HypothesisState.TESTED  # never promoted


def test_f3_a_variant_identical_to_the_reference_is_no_evidence_and_still_counts(tmp_path, monkeypatch, dataset_file,
                                                                                  capsys):
    register(template(grid={"atr_stop": [2, 3]}, family_id="FAM-GEN-SAME", name="same"))
    a, b = family_ids("FAM-GEN-SAME")
    sealed_run(tmp_path, monkeypatch, dataset_file, a, list(NOISE + 8))
    sealed_run(tmp_path, monkeypatch, dataset_file, b, [0.0] * DAYS)  # trades exactly like the reference
    assert cli("evaluate", "--result", str(tmp_path / f"{a}.json")) == 0
    capsys.readouterr()
    assert cli("evaluate", "--result", str(tmp_path / f"{b}.json")) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "NO_EVIDENCE"
    capsys.readouterr()
    assert cli("adjudicate", "--family", "FAM-GEN-SAME") == 0
    assert json.loads(capsys.readouterr().out)["n_tests"] == 2
    assert registry().get(b).state is HypothesisState.REJECTED


def test_f3_record_failed_run_only_for_a_recorded_run_without_evaluation(tmp_path, monkeypatch, dataset_file):
    register()
    a, b, _ = family_ids()
    assert cli("record-failed-run", "--hypothesis", a, "--reason", "x") == 2  # never run: not a failed run
    sealed_run(tmp_path, monkeypatch, dataset_file, b, list(NOISE + 8))
    assert cli("record-failed-run", "--hypothesis", b, "--reason", "  ") == 2  # a reason is required
    assert cli("evaluate", "--result", str(tmp_path / f"{b}.json")) == 0
    assert cli("record-failed-run", "--hypothesis", b, "--reason", "x") == 2  # already evaluated
    assert registry().get(b).test_evaluation.p_value < 0.05


def test_f3_the_registration_entry_point_refuses_windows_below_the_floor(tmp_path):
    from tools import hypothesis_pipeline as hp

    path = tmp_path / "t.json"
    path.write_text(json.dumps(dict(name="short", family_id="FAM-GEN-CLI-SHORT", author="research",
                                    universe=["BTCUSDT"], base_args={}, grid={"atr_stop": ["2"]},
                                    periods=[START.isoformat()], economic_rationale="x", days=se.MIN_DAYS - 1,
                                    windows=3, embargo=0, step=15)), encoding="utf-8")
    assert hp.main(["--template", str(path), "--history-days", "1"], fetch=lambda s, t: [], now=NOW) == 2
    assert not sc.canonical_registry().exists()


def test_f4_an_unmeasurable_correlation_is_flagged_not_called_independent(tmp_path, monkeypatch, dataset_file):
    register(template(grid={"atr_stop": [2, 3]}, family_id="FAM-GEN-UNK", name="unk"))
    a, b = family_ids("FAM-GEN-UNK")
    sealed_run(tmp_path, monkeypatch, dataset_file, a, list(NOISE + 9))
    sealed_run(tmp_path, monkeypatch, dataset_file, b, list(NOISE * 0.5 + 8))
    for hid in (a, b):
        assert cli("evaluate", "--result", str(tmp_path / f"{hid}.json")) == 0
    assert cli("adjudicate", "--family", "FAM-GEN-UNK") == 0
    monkeypatch.setattr(se, "_correlation", lambda x, y: None)
    listed = se.shortlist(registry())["shortlist"]
    assert len(listed) == 2 and listed[1]["correlation_unknown_with"] == [listed[0]["idea"]]


# -- second independent review of Task 006: N-1, N-2 ------------------------------------------


def test_n1_abandoning_unrun_members_after_a_sibling_ran_cannot_shrink_the_family(tmp_path, monkeypatch,
                                                                                    dataset_file, capsys):
    register()
    a, b, c = family_ids()
    sealed_run(tmp_path, monkeypatch, dataset_file, a, list(NOISE + 3))
    assert cli("evaluate", "--result", str(tmp_path / f"{a}.json")) == 0
    for hid in (b, c):  # a's result is visible; dropping the unrun siblings would lift it past BH
        registry().advance(hid, HypothesisState.REJECTED)
    capsys.readouterr()
    assert cli("adjudicate", "--family", "FAM-GEN-SEL") == 2
    blocking = json.loads(capsys.readouterr().out)["blocking"]
    assert set(blocking) == {b, c} and all("a sibling's run was recorded" in v for v in blocking.values())
    assert registry().get(a).state is HypothesisState.TESTED


def test_n1_abandoning_before_any_run_of_the_family_is_free(tmp_path, monkeypatch, dataset_file, capsys):
    register()
    a, b, c = family_ids()
    registry().advance(c, HypothesisState.REJECTED)  # nothing of the family has been read yet
    for hid in (a, b):
        sealed_run(tmp_path, monkeypatch, dataset_file, hid, list(NOISE + 8))
        assert cli("evaluate", "--result", str(tmp_path / f"{hid}.json")) == 0
    capsys.readouterr()
    assert cli("adjudicate", "--family", "FAM-GEN-SEL") == 0
    assert json.loads(capsys.readouterr().out)["n_tests"] == 2


def test_n1_abandon_only_counts_a_member_that_never_ran(tmp_path, monkeypatch, dataset_file):
    register()
    a, b, _ = family_ids()
    sealed_run(tmp_path, monkeypatch, dataset_file, a, list(NOISE + 8))
    assert cli("abandon", "--hypothesis", a, "--reason", "x") == 2  # it ran: evaluate or record-failed-run
    assert cli("abandon", "--hypothesis", b, "--reason", " ") == 2  # a reason is required
    assert cli("abandon", "--hypothesis", b, "--reason", "dropped") == 0
    record = registry().get(b)
    assert record.state is HypothesisState.TESTED and record.test_evaluation.p_value == 1.0


def test_n2_too_few_active_days_is_no_evidence():
    d = np.zeros(se.MIN_DAYS)
    d[[3, 17]] = 1.0  # only two days differ, both in the variant's favour
    with pytest.raises(se.InsufficientSampleError, match="days where the variant and the reference differ"):
        se.studentized_block_bootstrap(d, samples=999, seed=1)


def test_n2_tied_degenerate_nulls_stay_calibrated():
    """Equal-size gains/losses on few active days: resamples without spread count against the hypothesis."""
    rng = np.random.default_rng(19)
    hits = 0
    for i in range(1000):
        d = np.zeros(se.MIN_DAYS)
        days = rng.choice(se.MIN_DAYS, size=se.MIN_ACTIVE_DAYS, replace=False)
        d[days] = rng.choice([-1.0, 1.0], size=se.MIN_ACTIVE_DAYS)
        try:
            hits += se.studentized_block_bootstrap(d, samples=999, seed=i)[0] <= 0.05
        except se.InsufficientSampleError:
            pass  # no spread at all: no evidence
    assert hits / 1000 <= 0.07


def test_h1_abandoning_after_the_earliest_window_began_is_blocked_even_before_any_run(monkeypatch, capsys):
    """Review H-1: once a sealed window has started its outcome can be replayed as EXPLORATORY, even
    before any registered run, so an untested rejection after that moment would shrink m after the fact."""
    register()
    a, b, c = family_ids()
    registry().advance(c, HypothesisState.REJECTED)  # recorded now (2026); the windows start in 2100
    assert "blocking" in se.adjudication_readiness(registry(), "FAM-GEN-SEL") and \
        c not in se.adjudication_readiness(registry(), "FAM-GEN-SEL")["blocking"]  # before the window: free
    monkeypatch.setattr(se, "_earliest_window", lambda members: datetime(2000, 1, 1, tzinfo=timezone.utc))
    blocking = se.adjudication_readiness(registry(), "FAM-GEN-SEL")["blocking"]
    assert "abandoned AFTER the family's earliest sealed window" in blocking[c]
