"""Task 030 (registry v5.113): tools/forex_replay.py, the research-only forex replay and strategy comparison.

Owner 2026-11-12 'Forex verisiyle test (Önerilen)'. The replay must apply the forex rules the runtime has (real
spread, session, margin book at 1:2, shorts) and must never present its output as evidence."""

from __future__ import annotations

import lzma
import struct
from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from core.decision import Decision, DecisionAction, RiskLevel
from tools import forex_replay as fx

WEDNESDAY = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
FRIDAY = datetime(2026, 10, 30, 16, 0, tzinfo=UTC)        # the week closes at 21:00 UTC (17:00 New York, EDT)
SPREAD = 0.0001


def rows(count, start=WEDNESDAY, price=lambda i: 1.10, spread=SPREAD, skip=()):
    out, start_ms = [], int(start.timestamp() * 1000)
    for i in range(count):
        if i in skip:
            continue
        bid, ask = f"{price(i):.5f}", f"{price(i) + spread:.5f}"
        ms = start_ms + i * 60_000
        out.append([ms, bid, bid, bid, bid, 1.0, ms + 59_999, ask, ask, ask, ask])
    return out


def script(*actions, confidence=80):
    """A brain that answers the scripted actions in order, one per decision, then HOLD. ``"BUY:MEDIUM"`` names the
    risk level (HIGH when omitted). With two pairs the decisions alternate: EURUSD, GBPUSD, EURUSD, ..."""

    class Brain:
        def __init__(self):
            self.queue = list(actions)

        def analyze_and_decide(self, symbol, market_data):
            action, _, level = (self.queue.pop(0) if self.queue else "HOLD").partition(":")
            return Decision(action=DecisionAction[action], symbol=symbol, confidence=confidence, reasoning="scripted",
                            risk_level=RiskLevel[level or "HIGH"])

    return Brain


def run(data, *actions, **kw):
    confidence = kw.pop("confidence", 80)
    return fx.replay({"EURUSD": data}, step=15, brain_factory=script(*actions, confidence=confidence), **kw)


# ---------------------------------------------------------------- history


def bi5(records):
    return lzma.compress(b"".join(struct.pack(">5If", *r) for r in records))


def test_a_day_file_decodes_to_candles_in_open_high_low_close_order():
    blob = bi5([(0, 110000, 110020, 109990, 110030, 12.5), (60, 110020, 110010, 110000, 110025, 3.0)])
    first, second = fx.decode_bi5(blob, date(2026, 10, 28))
    start = int(datetime(2026, 10, 28, tzinfo=UTC).timestamp() * 1000)
    assert first == (start, "1.10000", "1.10030", "1.09990", "1.10020", 12.5)      # file order is open, close, low, high
    assert second[0] == start + 60_000
    assert fx.decode_bi5(b"", date(2026, 10, 28)) == []                            # a day with no data


@pytest.mark.parametrize("records", [
    [(0, 110000, 110020, 110010, 110030, 1.0)],       # the low is above the open
    [(0, 110000, 110020, 109990, 110010, 1.0)],       # the high is below the close
    [(0, 0, 110020, 0, 110030, 1.0)],                 # a zero price
])
def test_a_corrupt_candle_is_refused_never_replayed(records):
    with pytest.raises(ValueError, match="not a valid candle"):
        fx.decode_bi5(bi5(records), date(2026, 10, 28))


def test_a_truncated_file_is_refused():
    with pytest.raises(ValueError, match="whole number of records"):
        fx.decode_bi5(lzma.compress(b"\x00" * 30), date(2026, 10, 28))


def test_the_month_in_the_address_is_zero_based():
    assert fx.day_url("EURUSD", date(2026, 10, 28), "BID").endswith("/EURUSD/2026/09/28/BID_candles_min_1.bi5")


def test_history_joins_bid_and_ask_keeps_the_session_only_and_caches(tmp_path):
    calls = []
    saturday, wednesday = date(2026, 10, 24), date(2026, 10, 28)

    def opener(url):
        calls.append(url)
        ask = "ASK" in url
        up = 10 if ask else 0
        if "/24/" in url:                                         # Saturday: the market is closed
            return bi5([(0, 110000 + up, 110000 + up, 110000 + up, 110000 + up, 1.0)])
        records = [(0, 110000 + up, 110000 + up, 110000 + up, 110000 + up, 1.0),
                   (60, 110000 - (20 if ask else 0), 110000, 109000, 111000, 1.0)]   # minute 1: ask below bid
        if not ask:
            records.append((120, 110000, 110000, 110000, 110000, 1.0))               # minute 2: no ask candle
        return bi5(records)

    data = fx.history("EURUSD", saturday, saturday, tmp_path, opener) + fx.history("EURUSD", wednesday, wednesday,
                                                                                  tmp_path, opener)
    start = int(datetime(2026, 10, 28, tzinfo=UTC).timestamp() * 1000)
    assert data == [[start, "1.10000", "1.10000", "1.10000", "1.10000", 1.0, start + 59_999,
                     "1.10010", "1.10010", "1.10010", "1.10010"]]
    assert len(calls) == 4
    fx.history("EURUSD", wednesday, wednesday, tmp_path, opener)
    assert len(calls) == 4                                        # answered from the cache
    with pytest.raises(ValueError, match="not in the forex universe"):
        fx.history("USDJPY", wednesday, wednesday, tmp_path, opener)


# ---------------------------------------------------------------- fills, sides, the margin book


def test_a_long_buys_at_the_ask_and_sells_at_the_bid_so_a_flat_market_costs_the_spread():
    result = run(rows(400), "BUY", "SELL")
    [trade] = result.trades
    assert (trade.side, trade.entry_price, trade.exit_price) == ("LONG", D("1.10010"), D("1.10000"))
    assert trade.quantity == D("1818.18")                        # 10000 x leverage 2 x the HIGH bucket's 10 % / 1.10
    assert trade.net == -trade.quantity * D("0.0001") == -trade.spread_cost
    row = fx.window_row(result)
    assert row["before_costs"] == 0 and row["net_pnl"] == -row["spread_cost"] and row["commission"] == 0


def test_a_sell_of_a_pair_not_held_opens_a_short_and_a_buy_covers_it():
    falling = rows(400, price=lambda i: 1.10 - 0.00001 * i)
    [trade] = run(falling, "SELL", "BUY").trades
    assert trade.side == "SHORT" and trade.exit_reason == "BUY_SIGNAL"
    assert trade.entry_price > trade.exit_price and trade.net > 0             # sold at the bid, covered lower at the ask
    assert trade.net == trade.quantity * (trade.entry_price - trade.exit_price)
    rising = rows(400, price=lambda i: 1.10 + 0.00001 * i)
    assert run(rising, "SELL", "BUY").trades[0].net < 0                       # a short loses when the price rises


def test_without_shorts_a_sell_of_a_pair_not_held_does_nothing():
    result = run(rows(400), "SELL", "BUY", "SELL", shorts=False)
    assert [t.side for t in result.trades] == ["LONG"] and result.buy_signals == 1


def test_leverage_only_widens_the_notional_and_shorts_need_a_margin_book():
    geared = run(rows(400), "BUY", "SELL").trades[0]
    plain = run(rows(400), "BUY", "SELL", leverage=1, shorts=False).trades[0]
    assert geared.quantity == 2 * plain.quantity
    with pytest.raises(ValueError, match="margin book"):
        run(rows(400), "SELL", leverage=1, shorts=True)


def test_an_order_below_the_execution_gate_opens_nothing():
    result = run(rows(400), "BUY", confidence=55)
    assert result.trades == [] and result.buy_rejections == {"EXECUTION_GATE": 1}


def test_commission_and_a_wider_spread_are_charged_on_both_sides():
    base = fx.window_row(run(rows(400), "BUY", "SELL"))
    paid = fx.window_row(run(rows(400), "BUY", "SELL", commission_rate="0.001"))
    wide = fx.window_row(run(rows(400), "BUY", "SELL", spread_mult=3))
    assert paid["commission"] > D("3.9") and paid["net_pnl"] == base["net_pnl"] - paid["commission"]
    assert paid["before_costs"] == 0
    assert abs(wide["spread_cost"] - 3 * base["spread_cost"]) < D("0.01") and wide["before_costs"] == 0
    with pytest.raises(ValueError, match="negative"):
        run(rows(400), commission_rate="-0.001")


def test_nothing_fills_across_a_gap_in_the_minutes():
    # decisions fall on rows 200, 215, ...; the minute after the first decision is missing, so there is no next open
    gap = rows(400, skip={200})
    result = run(gap, "BUY")
    assert result.trades == [] and result.open_trades == [] and result.decisions > 0


def test_a_position_still_open_at_the_end_is_marked_never_hidden():
    falling = rows(400, price=lambda i: 1.10 - 0.00001 * i)
    result = run(falling, "BUY")
    assert result.trades == [] and len(result.open_trades) == 1
    [marked] = result.marked_open
    assert marked.exit_reason == "MARK_TO_MARKET" and marked.net < 0
    assert fx.window_row(result)["net_pnl"] == marked.net


def test_the_book_balances_margin_is_returned_and_cash_equals_capital_plus_the_net():
    falling = rows(400, price=lambda i: 1.10 - 0.00001 * i)
    result = run(falling, "SELL", "BUY", "BUY", "SELL", commission_rate="0.0001", slippage_bps=1)
    assert len(result.trades) == 2 and result.open_trades == []
    net = sum((t.net for t in result.trades), D("0"))
    assert result.cash == result.equity == D("10000") + net
    held = run(falling, "BUY")                                   # still open: its margin and fee are out of the cash
    [position] = held.open_trades
    assert held.cash == D("10000") - position.cost / 2 and held.equity == D("10000")


def pair(count, eur, gbp, start=WEDNESDAY):
    return {"EURUSD": rows(count, start, eur), "GBPUSD": rows(count, start, gbp)}


def test_an_open_loss_counts_against_the_daily_loss_limit_as_in_the_runtime():
    # audit T030-F1: EURUSD is shorted (1818.18 at 1.10) and then trades at 1.50: an open loss of about 727, above
    # the 5 % daily-loss limit (500). The runtime refuses new risk then; so does the replay.
    losing = pair(400, lambda i: 1.10 if i < 205 else 1.50, lambda i: 1.30)
    refused = fx.replay(losing, step=15, brain_factory=script("SELL", "HOLD", "HOLD", "BUY:MEDIUM"))
    assert [t.symbol for t in refused.open_trades] == ["EURUSD"] and len(refused.buy_rejections) == 1
    assert "LOSS" in next(iter(refused.buy_rejections))
    small = pair(400, lambda i: 1.10 if i < 205 else 1.12, lambda i: 1.30)          # an open loss of about 36
    allowed = fx.replay(small, step=15, brain_factory=script("SELL", "HOLD", "HOLD", "BUY:MEDIUM"))
    assert sorted(t.symbol for t in allowed.open_trades) == ["EURUSD", "GBPUSD"] and allowed.buy_rejections == {}


def test_the_capital_sleeves_are_on_as_in_the_runtime():
    result = fx.replay(pair(400, lambda i: 1.10, lambda i: 1.30), step=15, brain_factory=script("BUY", "BUY"))
    assert [t.symbol for t in result.open_trades] == ["EURUSD"] and result.buy_rejections == {"SLEEVE_FULL": 1}


def test_a_stop_out_closes_the_largest_loss_first():
    # EURUSD short 2000 (margin 1000) and GBPUSD short 5000 (margin 2500); both prices double: the losses are about
    # 2000 and 5000, equity about 3000 against 3500 of margin
    data = pair(400, lambda i: 1.10 if i < 230 else 2.20, lambda i: 1.30 if i < 230 else 2.60)
    result = fx.replay(data, step=15, brain_factory=script("SELL", "SELL:MEDIUM"))
    assert result.stop_outs == 1
    assert [(t.symbol, t.exit_reason) for t in result.trades] == [("GBPUSD", "STOP_OUT"), ("EURUSD", "STOP_OUT")]
    assert result.trades[0].net < result.trades[1].net < 0


def test_protective_exits_are_checked_every_minute_whatever_the_step():
    # audit T030-F2: with a 60-minute step no decision falls inside the close-out window; the position still closes
    friday = rows(330, start=datetime(2026, 10, 30, 15, 30, tzinfo=UTC))      # decisions at 18:50, 19:50, 20:50
    result = fx.replay({"EURUSD": friday}, step=60, brain_factory=script("BUY"))
    [trade] = result.trades
    assert trade.exit_reason == "WEEKEND_CLOSE" and trade.exit_time.startswith("2026-10-30T20:30")
    assert result.weekend_closes == [trade.exit_time] and result.held_over_close == 0


def test_a_closure_with_no_priced_minute_in_the_window_is_counted_never_hidden():
    # the minutes 20:20-20:59 are missing and the data resumes on Sunday evening: the position is carried over
    friday = rows(260, start=FRIDAY)                                    # 16:00 - 20:19 UTC
    sunday = rows(120, start=datetime(2026, 11, 1, 22, 0, tzinfo=UTC))
    result = fx.replay({"EURUSD": friday + sunday}, step=15, brain_factory=script("BUY"))
    assert result.trades == [] and result.held_over_close == 1 and len(result.open_trades) == 1
    assert fx.window_row(result)["held_over_close"] == 1


def test_the_drawdown_is_of_the_marked_equity_not_only_of_closed_trades():
    # audit T030-F3: a long falls about 9 % and fully recovers before it is sold: the realized result is the spread,
    # the drawdown is the fall
    dip = rows(400, price=lambda i: 1.10 if i < 220 or i >= 300 else 1.00)
    result = run(dip, "BUY", "HOLD", "HOLD", "HOLD", "HOLD", "HOLD", "HOLD", "HOLD", "SELL")
    [trade] = result.trades
    assert abs(trade.net) < 1 and D("180") < result.max_drawdown < D("185")
    assert fx.window_row(result)["max_drawdown"] == result.max_drawdown


def test_slippage_has_its_own_column_and_the_cost_identity_holds():
    row = fx.window_row(run(rows(400), "BUY", "SELL", slippage_bps=5, commission_rate="0.0001"))
    base = fx.window_row(run(rows(400), "BUY", "SELL"))
    assert row["spread_cost"] == base["spread_cost"] and D("1.9") < row["slippage_cost"] < D("2.1")
    assert abs(row["before_costs"]) < D("0.000001")
    assert row["net_pnl"] == -(row["spread_cost"] + row["slippage_cost"] + row["commission"])


def test_risk_per_trade_only_ever_reduces_the_size():
    def wave(i):
        return 1.10 + 0.0005 * ((i // 30) % 2)

    skip = ["HOLD"] * ((2400 - 200) // 15)
    full = fx.replay({"EURUSD": hours(42, wave)}, step=15, brain_factory=script(*skip, "BUY"), atr_stop=2)
    sized = fx.replay({"EURUSD": hours(42, wave)}, step=15, brain_factory=script(*skip, "BUY"), atr_stop=2,
                      risk_per_trade=0.00001)
    assert 0 < sized.open_trades[0].quantity < full.open_trades[0].quantity


def test_a_replay_result_always_says_it_is_not_evidence():
    result = run(rows(260))
    assert (result.status, result.evidence_eligible) == ("EXPLORATORY", False)
    row = fx.window_row(result)
    assert (row["status"], row["evidence_eligible"]) == ("EXPLORATORY", False)


def test_a_partial_day_is_never_cached_and_missing_weekdays_are_reported(tmp_path):
    today = datetime.now(UTC).date()
    with pytest.raises(ValueError, match="not a completed UTC day"):
        fx.fetch_day("EURUSD", today, "BID", tmp_path, lambda url: b"")
    assert list(tmp_path.rglob("*")) == []
    data = rows(10, start=datetime(2026, 10, 28, 10, 0, tzinfo=UTC))
    assert fx.missing_weekdays(data, date(2026, 10, 24), date(2026, 10, 29)) == ["2026-10-26", "2026-10-27",
                                                                                "2026-10-29"]


# ---------------------------------------------------------------- the session


def test_no_new_risk_in_the_last_hour_and_open_positions_close_30_minutes_before_the_close():
    friday = rows(300, start=FRIDAY)                # decisions at 19:20, 19:35, 19:50, 20:05, 20:20, 20:35, 20:50 UTC
    held = run(friday, "BUY")
    [trade] = held.trades
    assert trade.exit_reason == "WEEKEND_CLOSE" and trade.exit_time.startswith("2026-10-30T20:30")
    late = run(friday, "HOLD", "HOLD", "HOLD", "BUY", "SELL")           # the fourth decision is at 20:05
    assert late.trades == [] and late.open_trades == []
    assert late.buy_rejections == {"PRE_CLOSE": 2}                       # a short is new risk too
    assert run(friday, "HOLD", "HOLD", "BUY").open_trades == []          # 19:50: opened, then closed before the close


def test_a_cover_is_never_blocked_by_the_pre_close_gate():
    friday = rows(300, start=FRIDAY)
    [trade] = run(friday, "SELL", "HOLD", "HOLD", "BUY").trades          # the cover is decided at 20:05
    assert trade.side == "SHORT" and trade.exit_reason == "BUY_SIGNAL"


# ---------------------------------------------------------------- protective exits and research switches


def test_a_margin_level_at_or_below_100_percent_closes_the_book():
    # a 1818.18 short at 1.10: used margin 1000. At 6.10 the loss is about 9090, equity about 910: level below 1
    spike = rows(400, price=lambda i: 1.10 if i < 230 else 6.10)
    [trade] = run(spike, "SELL").trades
    assert trade.exit_reason == "STOP_OUT" and trade.net < -9000
    calm = rows(400, price=lambda i: 1.10 if i < 230 else 5.90)        # level about 1.27: no stop-out
    assert run(calm, "SELL").trades == []


def test_a_protective_exit_fills_at_the_next_minute_s_open_not_at_the_price_that_triggered_it():
    spike = rows(400, price=lambda i: 1.10 if i < 230 else 6.10 if i == 230 else 6.20)
    [trade] = run(spike, "SELL").trades
    assert trade.exit_reason == "STOP_OUT" and trade.exit_price == D("6.20010")    # a short covers at the ASK


def test_a_signal_exit_waits_for_the_minimum_hold_and_for_confirmation():
    held = run(rows(400), "BUY", "SELL", "SELL", "SELL", min_hold_min=40)
    assert held.exit_reasons == {"EXIT_DEFERRED": 2, "SELL_SIGNAL": 1}
    confirmed = run(rows(400), "BUY", "SELL", "HOLD", "SELL", "SELL", exit_confirm=2)
    assert confirmed.exit_reasons == {"EXIT_DEFERRED": 2, "SELL_SIGNAL": 1}


def hours(count, price):
    return rows(count * 60, start=datetime(2026, 10, 26, 0, 0, tzinfo=UTC), price=price)


def test_the_atr_stop_is_side_aware():
    # 40 quiet hours with a small wave (so ATR exists), then the price runs against the position
    def wave(i):
        return 1.10 + 0.0005 * ((i // 30) % 2)

    def against_short(i):
        return wave(i) if i < 2420 else 1.13

    def against_long(i):
        return wave(i) if i < 2420 else 1.07

    skip = ["HOLD"] * ((2400 - 200) // 15)                              # hold until minute 2400
    short = fx.replay({"EURUSD": hours(42, against_short)}, step=15, brain_factory=script(*skip, "SELL"), atr_stop=2)
    assert [(t.side, t.exit_reason) for t in short.trades] == [("SHORT", "ATR_STOP")]
    long = fx.replay({"EURUSD": hours(42, against_long)}, step=15, brain_factory=script(*skip, "BUY"), atr_stop=2)
    assert [(t.side, t.exit_reason) for t in long.trades] == [("LONG", "ATR_STOP")]
    favourable = fx.replay({"EURUSD": hours(42, against_long)}, step=15, brain_factory=script(*skip, "SELL"),
                           atr_stop=2)
    assert favourable.trades == []                                      # the price fell: a short is not stopped


def test_the_trend_filter_allows_a_long_only_above_and_a_short_only_below_the_average():
    rising = hours(42, lambda i: 1.10 + 0.000005 * i)
    skip = ["HOLD"] * ((2400 - 200) // 15)
    long = fx.replay({"EURUSD": rising}, step=15, brain_factory=script(*skip, "BUY"), trend_ema_hours=20)
    short = fx.replay({"EURUSD": rising}, step=15, brain_factory=script(*skip, "SELL"), trend_ema_hours=20)
    assert len(long.open_trades) == 1 and short.open_trades == []
    assert short.buy_rejections == {"TREND_FILTER": 1}


def test_the_cost_gate_refuses_an_entry_whose_expected_move_is_below_the_cost():
    flat = hours(42, lambda i: 1.10)                                    # ATR is zero: nothing clears any cost
    skip = ["HOLD"] * ((2400 - 200) // 15)
    result = fx.replay({"EURUSD": flat}, step=15, brain_factory=script(*skip, "BUY"), cost_gate=3)
    assert result.open_trades == [] and result.buy_rejections == {"EXPECTED_MOVE_BELOW_COST": 1}


# ---------------------------------------------------------------- the comparison is never evidence


def test_the_comparison_is_exploratory_and_gives_no_verdict():
    data = {"EURUSD": rows(1200)}
    variants = {fx.REFERENCE: {}, "sadece long (1:2)": {"shorts": False}}
    result = fx.compare(data, 2, 15, brain_factory=script("BUY", "SELL", "SELL", "BUY"), variants=variants)
    assert result["study"] == {"status": "EXPLORATORY", "evidence_eligible": False,
                               "reason": "NO_SEALED_PREREGISTRATION"}
    assert "verdicts" not in result and set(result["table"]) == set(variants)
    assert all(len(windows) == 2 for windows in result["table"].values())
    assert result["table"][fx.REFERENCE][0]["shorts"] == 1 and result["table"]["sadece long (1:2)"][0]["shorts"] == 0
    text = fx.render(result)
    assert "EXPLORATORY, NOT EVIDENCE" in text and "UNKNOWN" in text


def test_every_shipped_variant_is_a_valid_replay_call():
    assert fx.REFERENCE in fx.VARIANTS and fx.VARIANTS[fx.REFERENCE] == {}
    for name, kw in fx.VARIANTS.items():
        fx.replay({"EURUSD": rows(260)}, step=30, brain_factory=script("BUY"), **kw)


def test_the_history_and_the_output_must_stay_outside_the_repository(tmp_path, capsys):
    from pathlib import Path

    inside = Path(fx.__file__).resolve().parents[1] / "data" / "fxcache"
    for argv in (["--cache", str(inside)], ["--cache", str(tmp_path), "--output", str(inside / "r.json")]):
        with pytest.raises(SystemExit):
            fx.main([*argv, "--first", "2026-10-28", "--last", "2026-10-28"], opener=lambda url: b"")
    assert "outside the repository" in capsys.readouterr().err
    assert not inside.exists()
