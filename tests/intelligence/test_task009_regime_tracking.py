"""Task 009: market regime identification and cycle tracking (registry v5.93 grant).

The classifier is shared with replay and research (core.market_cycle; tools.regime_engine
re-exports it). These tests pin: no lookahead (bar t+1 never changes the regime at t),
asymmetric hysteresis (risk-off immediate, risk-on confirmed), the multi-timeframe anchor,
the immutable permissibility matrix, fail-closed UNKNOWN on sparse/gapped/stale/non-finite
data, and the MarketLoop gate (OFF by default; when on it only skips or shrinks BUYs).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

import tools.regime_engine as research_regime
from core import market_cycle as mc
from core.market_loop import MarketLoop

H = mc.INTERVAL_MS["1h"]
T0 = 1_700_000_000_000 // H * H


def rows(closes, *, interval="1h", start=T0):
    step = mc.INTERVAL_MS[interval]
    return [[start + i * step, str(c), str(c), str(c), str(c), "1", start + (i + 1) * step - 1, "0", 1, "0", "0", "0"]
            for i, c in enumerate(closes)]


def cutoff_after(n, *, interval="1h", start=T0):
    """The cutoff just after bar n-1 closed (bar n is still forming)."""
    return start + n * mc.INTERVAL_MS[interval]


def up(n=120, p=100.0):
    """A steady linear advance: efficiency ratio 1, falling return volatility -> TREND_UP."""
    return [p + i for i in range(n)]


def down(n=120, p=100.0, g=0.999):
    return [p * g ** i for i in range(n)]


def sideways(n=120, p=100.0):
    return [p * (1.01 if i % 2 else 1.0) for i in range(n)]


# -- the shared classifier -----------------------------------------------------------------------


def test_replay_and_runtime_share_one_classifier():
    assert research_regime.classify is mc.classify and research_regime.WINDOW == mc.WINDOW
    assert mc.classify(up())["regime"] == "TREND_UP" and mc.classify(sideways())["regime"] == "SIDEWAYS"
    assert mc.classify(down())["regime"] == "TREND_DOWN"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "100", None, True])
def test_non_finite_or_non_numeric_inputs_are_unknown_never_a_regime(bad):
    """Vector C: before Task 009 a NaN close silently classified as TRANSITION."""
    closes = up()
    closes[-3] = bad
    assert mc.classify(closes)["regime"] == "UNKNOWN"


def test_a_non_finite_indicator_is_unknown(monkeypatch):
    """Defensive guard: any non-finite indicator makes the bar UNKNOWN, never a regime."""
    monkeypatch.setattr(mc, "efficiency_ratio", lambda closes, window=mc.WINDOW: float("nan"))
    assert mc.classify(up()) == {"regime": "UNKNOWN", "reason": "non-finite indicator"}


# -- 3.1 lookahead -----------------------------------------------------------------------------------


def test_future_bars_never_change_the_regime_at_t():
    """Lookahead audit: a synthetic future shock after the cutoff leaves the regime at t untouched."""
    calm = up(200)
    cutoff = cutoff_after(150)
    base = mc.classify_closed(rows(calm[:150]), interval="1h", cutoff_ms=cutoff)
    shocked = calm[:150] + [calm[149] * 0.5] + [calm[149] * 0.4] * 49  # crash at t+1 and after
    with_future = mc.classify_closed(rows(shocked), interval="1h", cutoff_ms=cutoff)
    assert base == with_future and base["regime"] == "TREND_UP" and base["bars"] == 150


def test_walk_forward_regime_equals_the_regime_on_truncated_history():
    series = up(80) + [p * 0.97 ** i for i, p in enumerate([up(80)[-1]] * 60)] + sideways(80, 50.0)
    full = rows(series)
    for t in range(60, len(series), 7):
        assert mc.classify_closed(full, interval="1h", cutoff_ms=cutoff_after(t)) == \
            mc.classify_closed(rows(series[:t]), interval="1h", cutoff_ms=cutoff_after(t)), t


def test_the_forming_bar_is_dropped_and_the_causal_assertion_holds():
    forming_cutoff = cutoff_after(150) - 1  # bar 149 closes at exactly this millisecond -> not yet closed
    result = mc.classify_closed(rows(up(150)), interval="1h", cutoff_ms=forming_cutoff)
    assert result["bars"] == 149
    with pytest.raises(mc.CausalityError):
        mc.assert_causal([mc.Bar(T0, T0 + H - 1, 1.0)], T0 + H - 1)


def test_the_tracker_never_lets_a_future_bar_in():
    tracker = mc.MarketCycleTracker(lambda s, i, n: rows(up(400), interval=i, start=T0),
                                    mc.RegimeGateConfig(anchors=("4h",)))
    snap = tracker.observe("BTCUSDT", cutoff_after(150))
    assert snap["raw"]["1h"] == "TREND_UP"


# -- 3.2 hysteresis ----------------------------------------------------------------------------------


def test_boundary_flicker_never_toggles_the_state():
    tracker = mc.RegimeTracker(mc.HysteresisPolicy(confirm_bars=2, min_dwell_bars=3))
    for i in range(5):
        tracker.update("TREND_UP", T0 + i * H)
    assert tracker.state == "TREND_UP"
    for i in range(5, 105):  # flickering TREND_UP / TRANSITION every bar
        tracker.update("TRANSITION" if i % 2 else "TREND_UP", T0 + i * H)
    assert tracker.state == "TREND_UP" and tracker.transitions == 1  # only UNKNOWN -> TREND_UP at the start


def test_a_confirmed_change_needs_confirmation_and_dwell():
    tracker = mc.RegimeTracker(mc.HysteresisPolicy(confirm_bars=2, min_dwell_bars=3))
    states = [tracker.update(r, T0 + i * H) for i, r in enumerate(["TREND_UP"] * 4 + ["SIDEWAYS"] * 3)]
    # leaving UNKNOWN needs 2 agreeing bars and 3 bars of dwell; so does the later change
    assert states == ["UNKNOWN", "UNKNOWN", "TREND_UP", "TREND_UP", "TREND_UP", "SIDEWAYS", "SIDEWAYS"]


def test_risk_off_is_never_delayed_and_bars_are_idempotent():
    tracker = mc.RegimeTracker()
    for i in range(10):
        tracker.update("TREND_UP", T0 + i * H)
    assert tracker.update("PANIC", T0 + 10 * H) == "PANIC"  # immediate
    assert tracker.update("TREND_UP", T0 + 10 * H) == "PANIC"  # the same bar again: ignored
    assert tracker.update("TREND_UP", T0 + 5 * H) == "PANIC"  # an older bar: ignored
    assert tracker.update("TREND_UP", None) == "UNKNOWN"  # no usable bar: fail closed at once


@pytest.mark.parametrize("dwell", [2, 3, 5])
def test_transitions_are_bounded_by_the_dwell_time(dwell):
    """Vector B: even adversarial alternation between two permissive regimes cannot flap fast."""
    tracker = mc.RegimeTracker(mc.HysteresisPolicy(confirm_bars=2, min_dwell_bars=dwell))
    pattern = ["TREND_UP", "TREND_UP", "SIDEWAYS", "SIDEWAYS"]
    for i in range(400):
        tracker.update(pattern[i % 4], T0 + i * H)
    assert tracker.transitions <= 400 // dwell + 1


def test_policy_and_config_validation():
    with pytest.raises(ValueError):
        mc.HysteresisPolicy(confirm_bars=0)
    for bad in (dict(archetype="SCALPING"), dict(anchors=("1h",)), dict(tactical="4h", anchors=("1h",)),
                dict(tactical="5m"), dict(enabled="yes")):
        with pytest.raises(ValueError):
            mc.RegimeGateConfig(**bad)


# -- multi-timeframe anchor -------------------------------------------------------------------------


@pytest.mark.parametrize("tactical, anchors, expected", [
    ("TREND_UP", {"4h": "PANIC", "1d": "TREND_UP"}, "PANIC"),
    ("TREND_UP", {"4h": "TREND_UP", "1d": "HIGH_VOL"}, "HIGH_VOL"),
    ("SIDEWAYS", {"4h": "UNKNOWN", "1d": "TREND_UP"}, "UNKNOWN"),
    ("TREND_UP", {"4h": "TREND_UP", "1d": "TREND_DOWN"}, "TRANSITION"),
    ("SIDEWAYS", {"4h": "TREND_DOWN", "1d": "SIDEWAYS"}, "SIDEWAYS"),
    ("TREND_UP", {"4h": "TREND_UP", "1d": "TREND_UP"}, "TREND_UP"),
])
def test_higher_timeframes_bound_the_tactical_regime(tactical, anchors, expected):
    assert mc.anchored_regime(tactical, anchors)[0] == expected


# -- 3.3 permissibility ------------------------------------------------------------------------------


def test_the_permissibility_matrix_is_immutable():
    with pytest.raises(TypeError):
        mc.PERMISSIBILITY["TREND_FOLLOWING"] = {}
    with pytest.raises(TypeError):
        mc.PERMISSIBILITY["MEAN_REVERSION"]["TREND_UP"] = Decimal("1")


@pytest.mark.parametrize("archetype, regime, allowed, scale", [
    ("MEAN_REVERSION", "SIDEWAYS", True, "1"), ("MEAN_REVERSION", "TRANSITION", True, "0.5"),
    ("MEAN_REVERSION", "TREND_UP", False, "0"), ("MEAN_REVERSION", "TREND_DOWN", False, "0"),
    ("BREAKOUT", "TREND_UP", True, "1"), ("BREAKOUT", "HIGH_VOL", True, "0.5"), ("BREAKOUT", "SIDEWAYS", False, "0"),
    ("MOMENTUM", "TRANSITION", True, "0.5"), ("TREND_FOLLOWING", "SIDEWAYS", False, "0"),
    ("TREND_FOLLOWING", "TREND_UP", True, "1"), ("TREND_FOLLOWING", "PANIC", False, "0"),
    ("BREAKOUT", "UNKNOWN", False, "0"), ("SCALPING", "TREND_UP", False, "0"),
])
def test_archetype_permissions(archetype, regime, allowed, scale):
    verdict = mc.permission(archetype, regime)
    assert (verdict.allowed, verdict.scale) == (allowed, Decimal(scale))
    assert Decimal("0") <= verdict.scale <= Decimal("1")


# -- 3.4 sparse / gapped / stale data -------------------------------------------------------------------


@pytest.mark.parametrize("mutate, reason", [
    (lambda r: r[:30], None),                                        # too short: classify says why
    (lambda r: r[:60] + r[61:], "GAP"),
    (lambda r: r[:60] + [r[59]] + r[60:], "UNORDERED_OR_DUPLICATE"),
    (lambda r: r[:-1] + [[*r[-1][:4], "nan", *r[-1][5:]]], "NON_FINITE_CLOSE"),
    (lambda r: [[*x[:4], "0", *x[5:]] if i == 70 else x for i, x in enumerate(r)], "NON_FINITE_CLOSE"),
    (lambda r: r[:-10], "STALE"),
    (lambda r: [], "NO_CLOSED_BARS"),
    (lambda r: r[:5] + [["x"]] + r[5:], "MALFORMED_ROW"),
])
def test_unusable_data_degrades_to_unknown(mutate, reason):
    result = mc.classify_closed(mutate(rows(up(120))), interval="1h", cutoff_ms=cutoff_after(120))
    assert result["regime"] == "UNKNOWN"
    if reason is not None:
        assert result["reason"] == reason


def test_the_tracker_fails_closed_and_refetches_at_most_once_per_bar():
    calls: list[tuple[str, str]] = []

    def fetch(symbol, interval, limit):
        calls.append((symbol, interval))
        if interval == "1d":
            raise OSError("provider has no daily bars")
        step = mc.INTERVAL_MS[interval]
        start = (T0 + 100 * H) // step * step - 300 * step  # 300 closed bars ending at the cutoff
        return rows(up(300), interval=interval, start=start)

    tracker = mc.MarketCycleTracker(fetch)
    cutoff = T0 + 100 * H
    first = tracker.observe("ethusdt", cutoff)
    assert first["regime"] == "UNKNOWN" and first["anchor_reason"] == "ANCHOR_1d_UNKNOWN"
    assert first["reasons"]["1d"] == "OSError" and first["states"]["1h"] == first["states"]["4h"] == "TREND_UP"
    tracker.observe("ETHUSDT", cutoff + 1000)  # same bars: no new fetch except the failed retry window
    assert calls.count(("ETHUSDT", "1h")) == 1 and calls.count(("ETHUSDT", "1d")) == 1


def test_the_observer_never_raises():
    tracker = mc.MarketCycleTracker(lambda s, i, n: 1 / 0)
    assert tracker.observe("BTCUSDT", T0)["regime"] == "UNKNOWN"


# -- MarketLoop integration ---------------------------------------------------------------------------


class Brain:
    def analyze_and_decide(self, symbol, market_data):
        return {"symbol": symbol, "action": "BUY", "confidence": 95.0, "risk_level": "LOW"}


class Feed:
    def __init__(self):
        self.intervals: list[str] = []

    def candles(self, symbol, interval="1m", limit=500):
        self.intervals.append(interval)
        return []


class Execution:
    def __init__(self):
        self.calls = 0

    def execute(self, *a, **kw):
        self.calls += 1
        return {"status": "EXECUTED"}


def loop_with(snapshot_regime: str | None, **kw) -> MarketLoop:
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["BTCUSDT"],
                      regime_feed=Feed(), **kw)
    if loop.market_cycle is not None and snapshot_regime is not None:
        loop.market_cycle._snapshots["BTCUSDT"] = {"regime": snapshot_regime}
    loop._sell_symbol_known_flat = lambda symbol: False
    return loop


def gate(loop: MarketLoop, action: str) -> Any:
    cutoff = datetime.fromtimestamp(T0 / 1000, UTC)
    candle = {"open_time": T0 - 60_000, "close_time": T0 - 1}
    return loop._symbol_execution_gate("BTCUSDT", {"action": action, "symbol": "BTCUSDT", "metadata": {}},
                                       [candle], cutoff)


def test_everything_is_off_by_default():
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["BTCUSDT"])
    assert loop.market_cycle is None and loop.regime_gate.enabled is False
    assert "market_regime" not in loop.status()
    assert gate(loop_with(None), "BUY") is not None and not isinstance(gate(loop_with(None), "BUY"), dict)


def test_a_trend_signal_in_a_range_is_vetoed_before_the_risk_layer():
    loop = loop_with("SIDEWAYS", regime_gate=mc.RegimeGateConfig(enabled=True))
    vetoed = gate(loop, "BUY")
    assert vetoed["status"] == "SKIPPED" and vetoed["reason"] == "REGIME_NOT_PERMITTED"
    assert vetoed["market_regime"] == "SIDEWAYS" and loop.metrics["buy_regime_vetoed"] == 1
    assert loop.execution.calls == 0


def test_unknown_regime_blocks_new_entries_but_never_exits():
    loop = loop_with("UNKNOWN", regime_gate=mc.RegimeGateConfig(enabled=True))
    assert gate(loop, "BUY")["reason"] == "REGIME_UNKNOWN"
    assert not isinstance(gate(loop, "SELL"), dict)  # SELL continues to execution untouched
    never_observed = loop_with(None, regime_gate=mc.RegimeGateConfig(enabled=True))
    assert gate(never_observed, "BUY")["reason"] == "REGIME_UNKNOWN"


def test_a_permitted_regime_passes_and_records_its_scale():
    loop = loop_with("TRANSITION", regime_gate=mc.RegimeGateConfig(enabled=True, archetype="MEAN_REVERSION"))
    decision = {"action": "BUY", "symbol": "BTCUSDT", "metadata": {}}
    cutoff = datetime.fromtimestamp(T0 / 1000, UTC)
    result = loop._symbol_execution_gate("BTCUSDT", decision, [{"open_time": T0 - 60_000, "close_time": T0 - 1}],
                                         cutoff)
    assert not isinstance(result, dict) and decision["metadata"]["regime_scale"] == "0.5"


def test_observation_alone_never_changes_a_decision():
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["BTCUSDT"],
                      regime_observation=True, regime_feed=Feed())
    assert loop.market_cycle is not None and loop.regime_gate.enabled is False
    decision = {"action": "BUY", "symbol": "BTCUSDT", "metadata": {}}
    loop._observe_regime("BTCUSDT", decision, datetime.fromtimestamp(T0 / 1000, UTC))
    assert decision == {"action": "BUY", "symbol": "BTCUSDT", "metadata": {}}
    assert "regime_observations" not in loop.metrics
    assert loop.status()["market_regime"]["symbols"]["BTCUSDT"]["regime"] == "UNKNOWN"
    assert set(loop.regime_feed.intervals) == {"1h", "4h", "1d"} and loop.market_feed.intervals == []


@pytest.mark.parametrize("gate_on, skipped, expected", [
    (False, False, ["gate", "route", "observe"]),
    (False, True, ["gate", "observe"]),
    (True, False, ["observe", "gate", "route"]),
])
def test_observation_alone_runs_after_routing(gate_on, skipped, expected):
    """Review 16 L1: observe-only fetches never sit between the BUY freshness check and execution."""
    from core.market_loop import _CONTINUE

    order: list[str] = []
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["BTCUSDT"],
                      regime_observation=True, regime_gate=mc.RegimeGateConfig(enabled=gate_on), regime_feed=Feed())
    decision = {"action": "BUY", "symbol": "BTCUSDT", "metadata": {}}
    loop._symbol_closed_candles = lambda symbol, cutoff: ([{}], _CONTINUE)
    loop._symbol_new_candle_identity = lambda symbol, candles: ("id", _CONTINUE)
    loop._symbol_decide = lambda symbol, candles: (decision, {}, _CONTINUE)
    loop._agent_evidence_snapshot = lambda market_data: {}
    loop.world.build_market_state = lambda market_data: {}
    loop._observe_regime = lambda *a: order.append("observe")
    loop._symbol_execution_gate = lambda *a: (order.append("gate"), {"status": "SKIPPED"} if skipped
                                              else _CONTINUE)[1]
    loop.route_execution = lambda **kw: (order.append("route"), {"status": "EXECUTED"})[1]
    loop.process_symbol("BTCUSDT", processing_cutoff=datetime.fromtimestamp(T0 / 1000, UTC))
    assert order == expected


def test_a_marginal_regime_halves_the_proposed_size():
    from core.position_sizing import PositionSizingService
    from core.risk_engine import RiskPolicy

    class Foundation:
        ready = True

        def snapshot(self):
            return {"positions": {}, "cash": Decimal("10000"), "spendable_cash": Decimal("10000"),   # Task 025
                    "gross_exposure": Decimal("0")}

    class Ledger:
        ready = True

        def active_reserved_capital(self, exclude=None):
            return Decimal("0")

        def get(self, request_id):
            return None

    class Manager:
        completed_request_results: dict = {}
        portfolio_foundation = Foundation()
        reservation_ledger = Ledger()

    def proposed(scale: str | None, enabled: bool) -> Decimal:
        loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Manager(), symbols=["BTCUSDT"],
                          position_sizing_service=PositionSizingService(RiskPolicy(total_capital=Decimal("10000"))),
                          regime_gate=mc.RegimeGateConfig(enabled=enabled), regime_feed=Feed())
        decision = {"action": "BUY", "symbol": "BTCUSDT", "risk": "LOW", "confidence": 95.0,
                    "metadata": {} if scale is None else {"regime_scale": scale}}
        assert loop._apply_position_sizing("BUY", decision, "req-1") is None
        return decision["proposed_quote_allocation"]

    full = proposed(None, False)
    assert proposed("0.5", True) == full * Decimal("0.5") and proposed("1", True) == full
    assert full > 0


def test_regime_gate_arguments_are_validated():
    with pytest.raises(ValueError):
        MarketLoop(brain=Brain(), market_feed=Feed(), regime_gate={"enabled": True})
    with pytest.raises(ValueError):
        MarketLoop(brain=Brain(), market_feed=Feed(), regime_observation="yes")
    shared = Feed()
    for kw in ({"regime_observation": True}, {"regime_gate": mc.RegimeGateConfig(enabled=True)}):
        with pytest.raises(ValueError, match="own regime_feed"):  # review 17 F1: never the 1m feed
            MarketLoop(brain=Brain(), market_feed=shared, **kw)
        with pytest.raises(ValueError, match="own regime_feed"):
            MarketLoop(brain=Brain(), market_feed=shared, regime_feed=shared, **kw)



def test_a_restart_is_warm_started_causally_from_closed_bars():
    """Without a warm start the gate would hold UNKNOWN for days (1D dwell) after every restart;
    the warm start replays only bars that closed before the cutoff."""
    def fetch(symbol, interval, limit):
        step = mc.INTERVAL_MS[interval]
        start = (T0 + 100 * H) // step * step - 300 * step
        return rows(up(300), interval=interval, start=start)

    snap = mc.MarketCycleTracker(fetch).observe("BTCUSDT", T0 + 100 * H)
    assert snap["regime"] == "TREND_UP" and snap["states"] == {"1h": "TREND_UP", "4h": "TREND_UP", "1d": "TREND_UP"}

    def shocked(symbol, interval, limit):  # identical history plus bars that have not closed yet
        good = fetch(symbol, interval, limit)
        step = mc.INTERVAL_MS[interval]
        return good + rows([1.0] * 5, interval=interval, start=good[-1][0] + step)

    assert mc.MarketCycleTracker(shocked).observe("BTCUSDT", T0 + 100 * H) == snap


# -- review 15 regressions ---------------------------------------------------------------------------


def _hourly(n_closed, closes=None, *, cutoff):
    """Rows whose last n_closed bars closed exactly before ``cutoff``, plus the forming bar."""
    step = H
    start = cutoff // step * step - n_closed * step
    values = closes if closes is not None else up(n_closed + 1)
    return rows(values[: n_closed + 1], interval="1h", start=start)


def test_a_transient_fetch_failure_does_not_reset_the_smoothed_regime():
    """F2: one provider blip shows UNKNOWN while it lasts, then the regime is back at once."""
    state = {"fail": False}

    def fetch(symbol, interval, limit):
        if state["fail"]:
            raise OSError("blip")
        cutoff = fetch.cutoff
        step = mc.INTERVAL_MS[interval]
        start = cutoff // step * step - 300 * step
        return rows(up(301), interval=interval, start=start)

    tracker = mc.MarketCycleTracker(fetch)
    fetch.cutoff = T0 + 100 * H
    assert tracker.observe("BTCUSDT", fetch.cutoff)["regime"] == "TREND_UP"
    state["fail"], fetch.cutoff = True, fetch.cutoff + H  # the next 1h bar is due and the fetch fails
    assert tracker.observe("BTCUSDT", fetch.cutoff)["regime"] == "UNKNOWN"
    state["fail"], fetch.cutoff = False, fetch.cutoff + mc.FETCH_RETRY_MS
    assert tracker.observe("BTCUSDT", fetch.cutoff)["regime"] == "TREND_UP"  # no multi-day dwell


def test_a_failed_first_fetch_still_warm_starts_on_the_first_good_one():
    calls = {"n": 0}

    def fetch(symbol, interval, limit):
        calls["n"] += 1
        if calls["n"] <= 3:
            raise OSError("cold start blip")
        step = mc.INTERVAL_MS[interval]
        start = (T0 + 100 * H + mc.FETCH_RETRY_MS) // step * step - 300 * step
        return rows(up(301), interval=interval, start=start)

    tracker = mc.MarketCycleTracker(fetch)
    assert tracker.observe("BTCUSDT", T0 + 100 * H)["regime"] == "UNKNOWN"
    assert tracker.observe("BTCUSDT", T0 + 100 * H + mc.FETCH_RETRY_MS)["regime"] == "TREND_UP"


def test_the_draft_evidence_configuration_equals_raw_classify_of_clock_aligned_closed_bars():
    """F3: DRAFT_EVIDENCE_GATE equals raw classify of the last 720 clock-aligned closed 1H bars, bar by bar."""
    import random

    rng = random.Random(4)
    p, closes = 100.0, []
    for i in range(1400):
        drift = 0.003 if (i // 150) % 3 == 0 else (-0.002 if (i // 150) % 3 == 1 else 0.0)
        p *= math.exp(drift + rng.gauss(0, 0.006))
        closes.append(p)
    series = rows(closes, interval="1h", start=T0)
    tracker = mc.MarketCycleTracker(lambda s, i, n: series, mc.DRAFT_EVIDENCE_GATE)
    for t in range(760, 1400):  # review 17 F6: every bar, not a sample
        cutoff = T0 + t * H
        expected = mc.classify(closes[max(0, t - 720):t])["regime"]
        got = tracker.observe("BTCUSDT", cutoff)["regime"]
        assert got == expected, (t, got, expected)


def _minute_rows(hours, seed=7):
    import random

    rng = random.Random(seed)
    p, out = 100.0, []
    for i in range(hours * 60):
        p *= math.exp(0.00004 + rng.gauss(0, 0.0012))
        out.append([T0 + i * 60_000, str(p), str(p), str(p), str(p), "1", T0 + (i + 1) * 60_000 - 1])
    return out


def test_the_replay_rule_matches_the_runtime_rule_only_at_clock_aligned_decision_minutes():
    """Review 16 M1: the evidence bar's replay bars are rolling 60-minute chunks ending at the decision minute.

    At a clock-aligned decision minute they are exactly the runtime's closed 1H klines; off the hour
    (strategy_compare decides every 15 minutes from minute 200) the replay's last bar carries the
    decision minute's price, which no closed kline does. The known difference is pinned here so the
    two rules are never again recorded as equivalent.
    """
    from tools.backtest_replay import _hourly_bars

    minutes = _minute_rows(600)
    hourly = [[T0 + h * H, *minutes[h * 60 + 59][1:6], T0 + (h + 1) * H - 1] for h in range(600)]
    tracker = mc.MarketCycleTracker(lambda s, i, n: hourly, mc.DRAFT_EVIDENCE_GATE)
    for hour in (560, 599):
        end = hour * 60
        replay = [float(b[2]) for b in _hourly_bars(minutes, end)]
        runtime = [float(r[4]) for r in hourly[:hour]]
        assert replay == runtime
        assert tracker.observe("BTCUSDT", T0 + end * 60_000)["regime"] == mc.classify(replay)["regime"]
    end = 580 * 60 + 20  # 20 minutes past the hour, as strategy_compare's decisions are
    replay = [float(b[2]) for b in _hourly_bars(minutes, end)]
    runtime = [float(r[4]) for r in hourly[:580]]
    assert replay[-1] == float(minutes[end - 1][4])
    assert replay != runtime[-len(replay):]


def test_the_windowed_replay_classifies_a_shorter_history_than_the_runtime():
    """Review 17 F3: strategy_compare replays each window on its own (7-day windows by default).

    Even at a clock-aligned minute the replay then classifies at most the window's hours (UNKNOWN for
    its first ~51), while the runtime classifies the last 720 closed bars. Equivalence needs both
    clock alignment and equal history.
    """
    from tools.backtest_replay import _hourly_bars

    minutes = _minute_rows(600)
    window_start = 560 * 60 - 7 * 24 * 60  # a 7-day window ending at hour 560
    early = 40 * 60  # 40 hours into the window, on the clock hour
    window = minutes[window_start:window_start + early]
    replay = [float(b[2]) for b in _hourly_bars(window, len(window))]
    runtime = [float(r[4]) for r in minutes[59:window_start + early:60]]
    assert len(replay) == 40 and len(runtime) > 400
    assert replay == runtime[-40:]
    assert mc.classify(replay)["regime"] == "UNKNOWN" != mc.classify(runtime[-720:])["regime"]


def test_an_overtaken_observation_keeps_the_later_state():
    """Review 16 L2: a slower, older observation never overwrites a later one's snapshot."""
    import threading

    series = rows(up(400), interval="1h", start=T0)
    entered, release = threading.Event(), threading.Event()

    def fetch(symbol, interval, limit):
        if threading.current_thread() is not threading.main_thread():
            entered.set()
            release.wait(5)
        return series

    tracker = mc.MarketCycleTracker(fetch, mc.RegimeGateConfig(anchors=()))
    slow: dict[str, Any] = {}
    worker = threading.Thread(target=lambda: slow.update(tracker.observe("BTCUSDT", T0 + 300 * H)))
    worker.start()
    assert entered.wait(5)
    fast = tracker.observe("BTCUSDT", T0 + 301 * H)
    release.set()
    worker.join(5)
    assert fast["observed_at_ms"] == T0 + 301 * H and fast["regime"] == "TREND_UP"
    assert slow["observed_at_ms"] == T0 + 301 * H
    assert tracker.snapshot("BTCUSDT")["observed_at_ms"] == T0 + 301 * H


def test_a_closed_bar_is_stale_exactly_when_its_successor_should_have_closed():
    """Review 16 L2: the STALE boundary is one interval past the last close, not more."""
    series = rows(up(120))
    last_open = T0 + 119 * H
    assert mc.closed_bars(series, interval="1h", cutoff_ms=last_open + 2 * H - 1)[1] is None
    assert mc.closed_bars(series, interval="1h", cutoff_ms=last_open + 2 * H)[1] == "STALE"


def test_a_contradicted_state_decays_after_exactly_confirm_plus_dwell_bars():
    """Review 16 L2: the decay to TRANSITION happens at confirm + dwell disagreeing bars, not later."""
    tracker = mc.RegimeTracker()
    for i in range(6):
        tracker.update("TREND_UP", T0 + i * H)
    limit = tracker.policy.confirm_bars + tracker.policy.min_dwell_bars
    for k in range(limit - 1):
        assert tracker.update("TREND_DOWN" if k % 2 else "SIDEWAYS", T0 + (6 + k) * H) == "TREND_UP"
    assert tracker.update("TREND_DOWN" if (limit - 1) % 2 else "SIDEWAYS", T0 + (5 + limit) * H) == "TRANSITION"


def test_regime_fetch_failures_never_latch_the_1m_feed():
    """Review 17 F1: with the real MarketFeedService, failing regime fetches degrade only the regime feed."""
    from exchange.market_feed import MarketFeed
    from tests.phase6.test_market_feed_compatibility import FakeProvider

    class HigherTimeframesFail(FakeProvider):
        def get_candles(self, symbol, timeframe="5m", limit=100):
            if timeframe != "1m":
                raise ConnectionError(f"simulated {timeframe} failure")
            return super().get_candles(symbol, timeframe, limit)

    def feed():
        built = MarketFeed(provider=HigherTimeframesFail(), publish_events=False, collect_metrics=False)
        built.start()
        return built

    market_feed, regime_feed = feed(), feed()
    loop = MarketLoop(brain=Brain(), market_feed=market_feed, execution=None, symbols=["BTCUSDT"],
                      regime_observation=True, regime_feed=regime_feed)
    cutoff = datetime.now(UTC)
    for k in range(3):
        loop._observe_regime("BTCUSDT", {"action": "HOLD", "metadata": {}},
                             datetime.fromtimestamp(cutoff.timestamp() + k * mc.FETCH_RETRY_MS / 1000, UTC))
    assert regime_feed.service.consecutive_failures >= 3 and not regime_feed.service.is_running
    assert market_feed.service.consecutive_failures == 0 and market_feed.service.is_running
    assert len(market_feed.candles("BTCUSDT", "1m", 200)) == 200
    assert loop.market_cycle.snapshot("BTCUSDT")["regime"] == "UNKNOWN"


def test_the_runtime_composition_root_keeps_regime_tracking_off(tmp_path):
    """Owner decision after review 18: observation is OFF in the runtime until it has its own worker."""
    from tests.test_block5c_upstream_sizing_authority import application

    app = application(tmp_path)
    assert app.market_loop.market_cycle is None and app.market_loop.regime_gate.enabled is False
    assert app.market_loop.regime_feed is None and not hasattr(app, "regime_feed")
    assert "market_regime" not in app.market_loop.status()


def test_observe_only_fetches_wait_until_every_symbol_of_the_cycle_is_routed():
    """Review 17 F2: no symbol's routing waits on another symbol's regime I/O."""
    from core.market_loop import _CONTINUE

    order: list[str] = []
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["BTCUSDT", "ETHUSDT"],
                      regime_observation=True, regime_feed=Feed())
    loop.running = True
    loop._symbol_closed_candles = lambda symbol, cutoff: ([{}], _CONTINUE)
    loop._symbol_new_candle_identity = lambda symbol, candles: ("id", _CONTINUE)
    loop._symbol_decide = lambda symbol, candles: ({"action": "BUY", "symbol": symbol, "metadata": {}}, {},
                                                   _CONTINUE)
    loop._agent_evidence_snapshot = lambda market_data: {}
    loop.world.build_market_state = lambda market_data: {}
    loop._observe_regime = lambda symbol, *a: order.append(f"observe:{symbol}")
    loop._symbol_execution_gate = lambda *a: _CONTINUE
    loop.route_execution = lambda **kw: (order.append(f"route:{kw['decision']['symbol']}"), {})[1]
    loop.run_cycle()
    assert order == ["route:BTCUSDT", "route:ETHUSDT", "observe:BTCUSDT", "observe:ETHUSDT"]
    assert loop._deferred_regime_observations is None


def test_a_stop_during_the_cycle_drops_the_deferred_observations():
    """Review 18 L4: stopping mid-cycle never starts the deferred regime I/O."""
    from core.market_loop import _CONTINUE

    order: list[str] = []
    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=Execution(), symbols=["BTCUSDT"],
                      regime_observation=True, regime_feed=Feed())
    loop.running = True
    loop._symbol_closed_candles = lambda symbol, cutoff: ([{}], _CONTINUE)
    loop._symbol_new_candle_identity = lambda symbol, candles: ("id", _CONTINUE)
    loop._symbol_decide = lambda symbol, candles: ({"action": "SELL", "symbol": symbol, "metadata": {}}, {},
                                                   _CONTINUE)
    loop._agent_evidence_snapshot = lambda market_data: {}
    loop.world.build_market_state = lambda market_data: {}
    loop._observe_regime = lambda symbol, *a: order.append(f"observe:{symbol}")
    loop._symbol_execution_gate = lambda *a: _CONTINUE

    def route(**kw):
        order.append("route")
        loop.running = False  # a stop arrives while the cycle is routing
        return {}

    loop.route_execution = route
    loop.run_cycle()
    assert order == ["route"] and loop._deferred_regime_observations is None


def test_missed_bars_are_replayed_causally_and_the_warm_start_depth_is_bounded(monkeypatch):
    """Review 18 L3/L4: every replayed update labels a bar with the closes up to and including that bar."""
    import random

    rng = random.Random(11)
    p, closes = 100.0, []
    for i in range(500):
        p *= math.exp((0.004 if (i // 40) % 2 else -0.003) + rng.gauss(0, 0.01))
        closes.append(p)
    series = rows(closes, interval="1h", start=T0)
    calls: list[tuple[str, int | None]] = []
    original = mc.RegimeTracker.update

    def spy(self, raw, bar_open_ms):
        calls.append((raw, bar_open_ms))
        return original(self, raw, bar_open_ms)

    monkeypatch.setattr(mc.RegimeTracker, "update", spy)
    config = mc.RegimeGateConfig(anchors=())
    tracker = mc.MarketCycleTracker(lambda s, i, n: series, config)
    tracker.observe("BTCUSDT", T0 + 300 * H)
    depth = config.policy.confirm_bars + config.policy.min_dwell_bars + 1
    assert len(calls) == depth + 1  # a new tracker warm-starts from the last few closed bars only
    tracker._next_due_ms[("BTCUSDT", "1h")] = 0
    tracker.observe("BTCUSDT", T0 + 340 * H)  # 40 closed bars were missed
    assert len(calls) == depth + 1 + 40
    for raw, bar_open_ms in calls:
        k = (bar_open_ms - T0) // H
        assert raw == mc.classify(closes[:k + 1])["regime"], k


def test_too_short_a_history_is_unknown():
    """Review 18 L4: the minimum history is pinned at the boundary."""
    assert mc.classify(up(mc.MINIMUM_CLOSES - 1))["regime"] == "UNKNOWN"
    assert mc.classify(up(mc.MINIMUM_CLOSES))["regime"] != "UNKNOWN"


def test_the_observer_s_trackers_enter_a_refused_regime_on_the_same_bar(monkeypatch):
    """Review 19 F2 (B6): the archetype's refusals reach the trackers the observer builds, not just its config."""
    monkeypatch.setattr(mc, "classify", lambda closes: {"regime": "TREND_UP" if len(closes) < 150 else "SIDEWAYS"})
    series = rows(up(300), interval="1h", start=T0)
    tracker = mc.MarketCycleTracker(lambda s, i, n: series, mc.RegimeGateConfig(anchors=()))
    assert tracker.observe("BTCUSDT", T0 + 149 * H)["regime"] == "TREND_UP"
    assert tracker.observe("BTCUSDT", T0 + 150 * H)["regime"] == "SIDEWAYS"


def test_observation_without_the_gate_never_vetoes_a_buy():
    """Review 19 F2 (L2): a refusing regime under observation alone leaves the BUY to the existing gates."""
    loop = loop_with("SIDEWAYS", regime_observation=True)
    assert loop.market_cycle is not None and loop.regime_gate.enabled is False
    assert not isinstance(gate(loop, "BUY"), dict)
    assert "buy_regime_vetoed" not in loop.metrics


def test_the_minimum_history_matches_the_previous_classifier_literally():
    """Review 19 F2 (C7): 52 closes, as tools.regime_engine required before Task 009."""
    assert mc.MINIMUM_CLOSES == 52
    assert mc.classify(up(51))["regime"] == "UNKNOWN" and mc.classify(up(52))["regime"] != "UNKNOWN"


def test_an_observer_defect_is_unknown_never_a_regime(monkeypatch):
    """Review 19 F2 (C11)."""
    def broken(*a, **kw):
        raise RuntimeError("anchor defect")

    monkeypatch.setattr(mc, "anchored_regime", broken)
    series = rows(up(400), interval="1h", start=T0)
    found = mc.MarketCycleTracker(lambda s, i, n: series, mc.RegimeGateConfig(anchors=())).observe(
        "BTCUSDT", T0 + 300 * H)
    assert found["regime"] == "UNKNOWN" and found["anchor_reason"] == "OBSERVER_ERROR:RuntimeError"


def test_a_repeated_bar_never_counts_as_a_second_confirmation():
    """Review 17 F4: hysteresis cannot be bypassed by delivering the same bar twice."""
    tracker = mc.RegimeTracker()
    for i in range(6):
        tracker.update("TREND_UP", T0 + i * H)
    for _ in range(tracker.policy.confirm_bars + 1):
        assert tracker.update("SIDEWAYS", T0 + 6 * H) == "TREND_UP"


def test_bars_closer_than_one_interval_are_a_gap():
    """Review 17 F5: overlapping or misaligned spacing is refused, not only missing bars."""
    series = rows(up(120))
    extra_open = series[-1][0] + H // 2
    series.append([extra_open, "220", "220", "220", "220", "1", extra_open + H - 1, "0", 1, "0", "0", "0"])
    assert mc.closed_bars(series, interval="1h", cutoff_ms=extra_open + H)[1] == "GAP"


def test_a_close_time_that_is_not_the_interval_end_is_refused():
    """F5: a provider falling back to open_time cannot smuggle in the forming bar."""
    bad = rows(up(120))
    bad[-1][6] = bad[-1][0]
    assert mc.classify_closed(bad, interval="1h", cutoff_ms=cutoff_after(120))["reason"] == "INCONSISTENT_CLOSE_TIME"


def test_a_backwards_cutoff_never_reuses_later_state():
    """F6."""
    series = rows(up(400), interval="1h", start=T0)
    tracker = mc.MarketCycleTracker(lambda s, i, n: series, mc.RegimeGateConfig(anchors=()))
    tracker.observe("BTCUSDT", T0 + 300 * H)
    assert tracker.observe("BTCUSDT", T0 + 240 * H) == {"regime": "UNKNOWN", "anchor_reason": "CUTOFF_REGRESSED",
                                                        "observed_at_ms": T0 + 240 * H}


def test_status_is_not_blocked_by_a_slow_fetch():
    """F7: network I/O runs outside the tracker lock."""
    import threading
    import time

    release = threading.Event()

    def slow(symbol, interval, limit):
        release.wait(5)
        return []

    tracker = mc.MarketCycleTracker(slow)
    worker = threading.Thread(target=lambda: tracker.observe("BTCUSDT", T0))
    worker.start()
    time.sleep(0.1)
    started = time.monotonic()
    tracker.status()
    assert time.monotonic() - started < 0.5
    release.set()
    worker.join(5)


def test_the_strategy_s_refusals_are_entered_at_once_and_stale_states_decay():
    """F8: for trend following, any non-TREND_UP label refuses immediately; a contradicted state decays."""
    tracker = mc.RegimeTracker(mc.HysteresisPolicy(), frozenset({"TREND_DOWN", "TRANSITION", "SIDEWAYS"}))
    for i in range(6):
        tracker.update("TREND_UP", T0 + i * H)
    assert tracker.update("TRANSITION", T0 + 6 * H) == "TRANSITION"
    plain = mc.RegimeTracker()
    for i in range(6):
        plain.update("TREND_UP", T0 + i * H)
    for i in range(6, 20):  # alternating labels that never confirm a successor
        plain.update("TREND_DOWN" if i % 2 else "SIDEWAYS", T0 + i * H)
    assert plain.state != "TREND_UP"


def test_the_observer_marks_an_unrefreshed_state_unknown():
    series = rows(up(400), interval="1h", start=T0)
    tracker = mc.MarketCycleTracker(lambda s, i, n: series, mc.RegimeGateConfig(anchors=()))
    assert tracker.observe("BTCUSDT", T0 + 300 * H)["regime"] == "TREND_UP"
    tracker._next_due_ms[("BTCUSDT", "1h")] = 10 ** 18  # no refresh happens
    assert tracker.observe("BTCUSDT", T0 + 303 * H)["regime"] == "UNKNOWN"


class _Manager:
    """Enough of ExecutionManager for _apply_position_sizing's refusal and conflict paths."""

    def __init__(self, reserved=None):
        class Foundation:
            ready = True

            def snapshot(self):
                return {"positions": {}, "cash": Decimal("10000"), "spendable_cash": Decimal("10000"),   # Task 025
                    "gross_exposure": Decimal("0")}

        class Ledger:
            ready = True

            def active_reserved_capital(self, exclude=None):
                return Decimal("0")

            def get(self, request_id):
                return reserved

        self.completed_request_results = {}
        self.portfolio_foundation = Foundation()
        self.reservation_ledger = Ledger()

    def build_request(self, decision):
        return dict(decision)

    def reject(self, code, request, details=None):
        return {"status": "REJECTED", "reason": code, "details": details}


def _sized(scale, *, reserved=None):
    from core.position_sizing import PositionSizingService
    from core.risk_engine import RiskPolicy

    loop = MarketLoop(brain=Brain(), market_feed=Feed(), execution=_Manager(reserved), symbols=["BTCUSDT"],
                      position_sizing_service=PositionSizingService(RiskPolicy(total_capital=Decimal("10000"))),
                      regime_gate=mc.RegimeGateConfig(enabled=True), regime_feed=Feed())
    decision = {"action": "BUY", "symbol": "BTCUSDT", "risk": "LOW", "confidence": 95.0,
                "metadata": {"regime_scale": scale}}
    return loop._apply_position_sizing("BUY", decision, "req-1"), decision


@pytest.mark.parametrize("scale", ["2", "1.0000001", "-1", "0", "NaN", "sNaN", "Infinity", "abc", None])
def test_an_invalid_regime_scale_is_refused_never_used(scale):
    """F4."""
    refused, decision = _sized(scale)
    assert refused["reason"] == "REGIME_SCALE_INVALID" and "proposed_quote_allocation" not in decision


def test_the_replay_conflict_check_compares_the_scaled_amount():
    """F4: a prior reservation for the scaled amount is the same request, for the unscaled one a conflict."""
    from types import SimpleNamespace

    _, full = _sized("1")
    whole = full["proposed_quote_allocation"]
    accepted, decision = _sized("0.5", reserved=SimpleNamespace(amount=whole * Decimal("0.5")))
    assert accepted is None and decision["proposed_quote_allocation"] == whole * Decimal("0.5")
    conflict, _ = _sized("0.5", reserved=SimpleNamespace(amount=whole))
    assert conflict["reason"] == "SIZING_REPLAY_CONFLICT"


def test_the_gate_end_to_end_through_the_real_runtime_path(tmp_path):
    """F4: a real AtlasApplication MarketLoop with the gate ON: SIDEWAYS skips the BUY before risk and
    capital; a marginal regime halves the size that risk_check approves; SELL is untouched."""
    from tests.test_block5c_upstream_sizing_authority import application, execution_enabled_loop

    def run(regime, archetype="TREND_FOLLOWING", path="a"):
        app = application(tmp_path / path)
        app.execution.start()
        loop = execution_enabled_loop(app, "BUY")
        loop.regime_gate = mc.RegimeGateConfig(enabled=True, archetype=archetype)
        loop.market_cycle = mc.MarketCycleTracker(lambda s, i, n: [], loop.regime_gate)
        loop.market_cycle.observe = lambda symbol, cutoff_ms: {"regime": regime}
        loop.market_cycle.snapshot = lambda symbol: {"regime": regime}
        return app, loop.process_symbol("BTCUSDT")

    app, skipped = run("SIDEWAYS", path="side")
    assert skipped["status"] == "SKIPPED" and skipped["reason"] == "REGIME_NOT_PERMITTED"
    assert app.portfolio_foundation.snapshot()["positions"].get("BTCUSDT") is None
    _, full = run("TREND_UP", path="up")
    _, half = run("TRANSITION", archetype="MOMENTUM", path="half")
    assert full["status"] == half["status"] == "PAPER_EXECUTED"
    assert Decimal(half["data"]["approved_quote_allocation"]) == \
        Decimal(full["data"]["approved_quote_allocation"]) * Decimal("0.5")


def test_the_tracker_enters_every_regime_its_archetype_refuses_at_once():
    """F8: the refusal set is derived from the permissibility matrix, so smoothing never delays a refusal."""
    trend = mc.MarketCycleTracker(lambda s, i, n: [], mc.RegimeGateConfig(archetype="TREND_FOLLOWING"))
    assert trend._immediate == frozenset({"PANIC", "HIGH_VOL", "TREND_DOWN", "SIDEWAYS", "TRANSITION", "UNKNOWN"})
    reverting = mc.MarketCycleTracker(lambda s, i, n: [], mc.RegimeGateConfig(archetype="MEAN_REVERSION"))
    assert "TREND_UP" in reverting._immediate and "SIDEWAYS" not in reverting._immediate
