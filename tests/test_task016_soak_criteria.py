"""Task 016 (registry v5.100): the soak report's benchmark, robustness checks and drawdown stop, delta tests only.

The benchmark prices come from a real market archive built with Atlas's own MarketDataSQLiteStorage, the trades from
Atlas's own ClosedPositionArchiveStore, and the basket from the repository's configured trade universe.
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from core.application import DEFAULT_INSTRUMENT_RULES_PATH
from core.execution_portfolio_foundation import ClosedPositionArchiveStore
from data_layer.market_data_archive_sqlite import ArchivedBar, FetchBatch, MarketDataSQLiteStorage
from tools import soak_report as report
from tools.bootstrap_financial_state import canonical_policy

HOUR_MS = 3_600_000
DAY0 = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
START = DAY0.isoformat()
UNIVERSE = report.basket_symbols(DEFAULT_INSTRUMENT_RULES_PATH)


def ms(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


def iso(moment: datetime) -> str:
    return moment.isoformat()


def record(n, gross="10", cost="1000", fees="1", opened=None, closed=None, symbol="BTCUSDT"):
    opened = opened or DAY0 + timedelta(hours=1)
    closed = closed or DAY0 + timedelta(hours=5)
    return {"position_id": f"LONG:{symbol}:r{n}", "symbol": symbol, "base_quantity": "0", "cost_quote": cost,
            "entry_fees": fees, "average_entry_price": "100", "mark_price": "101", "version": 2,
            "opened_at": iso(opened), "status": "CLOSED", "exit_price": "101", "gross_pnl": gross,
            "closed_at": iso(closed)}


def write_state(root, records, realized=None):
    root.mkdir(parents=True, exist_ok=True)
    store = ClosedPositionArchiveStore(root / "execution_closed_positions.jsonl")
    for sequence, item in enumerate(records):
        store.append(sequence, item)
    if realized is None:
        realized = format(sum((Decimal(r["gross_pnl"]) for r in records), Decimal("0")), "f")
    (root / "execution_financial_state.json").write_text(json.dumps({
        "cash": "10000", "reserved_capital": "0", "realized_gross_pnl": realized, "fees": "0", "positions": {}}),
        encoding="utf-8")
    return root


def write_market_archive(database, symbols, hours, price_of, start=DAY0 - timedelta(hours=2)):
    """1h bars for each symbol; price_of(symbol, hour_index) is the open, the next hour's open is the close."""
    store = MarketDataSQLiteStorage(database)
    store.open()
    try:
        for symbol in symbols:
            bars = []
            for hour in range(hours):
                open_ms = ms(start) + hour * HOUR_MS
                bars.append(ArchivedBar(
                    symbol=symbol, timeframe="1h", open_time_ms=open_ms, close_time_ms=open_ms + HOUR_MS - 1,
                    open=price_of(symbol, hour), high=price_of(symbol, hour + 1) + 1, low=1.0,
                    close=price_of(symbol, hour + 1), volume=1.0))
            store.store_batch(FetchBatch(
                source="test", endpoint="/api/v3/klines", provider_version="1", symbol=symbol, timeframe="1h",
                fetched_at=datetime(2026, 10, 17, tzinfo=UTC), bars=tuple(bars),
                requested_start_ms=bars[0].open_time_ms, requested_end_ms=bars[-1].open_time_ms))
    finally:
        store.close()
    return Path(database)


def growth(rate):
    return lambda symbol, hour: 100.0 * (1 + rate) ** hour


def run(monkeypatch, capsys, root, database, *args):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(root))
    code = report.main(["--start", START, "--market-archive", str(database), *args])
    return code, capsys.readouterr().out


def hundred_trades(gross="10"):
    """100 trades closing over 25 UTC days, four a day, each held four hours on the hour."""
    rows = []
    for i in range(100):
        opened = DAY0 + timedelta(days=i // 4, hours=1 + 5 * (i % 4))
        rows.append(record(i, gross=gross, opened=opened, closed=opened + timedelta(hours=4)))
    return rows


# --- pinned numbers ---------------------------------------------------------------------------------------------

def test_the_task_016_numbers_and_sources_are_pinned():
    assert report.TOP_REMOVED == 3
    assert report.DRAWDOWN_STOP_PCT == Decimal("10")
    assert report.BENCHMARK_TIMEFRAME == "1h" and report.BENCHMARK_BTC == "BTCUSDT"
    assert report.DEFAULT_START_CAPITAL == canonical_policy().total_capital
    from tools.fetch_historical_market_data import DATABASE_FILENAME
    assert report.MARKET_ARCHIVE_FILENAME == DATABASE_FILENAME


# --- day-block bootstrap ----------------------------------------------------------------------------------------

def test_day_block_lower_bound_resamples_whole_utc_closing_days():
    # eight closing days with different trade counts and sums, so every draw and every divisor matters
    counts = [1, 2, 3, 1, 2, 4, 1, 2]
    values = [Decimal(v) for v in ("5", "7", "-3", "-1", "2", "4", "-6", "8", "1", "-2", "9", "3", "-4", "6", "-5", "2",
                                   "7", "-1", "4", "-3", "2")]
    rows, nets, blocks, at = [], [], [], 0
    for day, count in enumerate(counts):
        chunk = values[at:at + count]
        at += count
        blocks.append((float(sum(chunk)), count))
        for k, value in enumerate(chunk):
            rows.append(record(day * 10 + k, closed=DAY0 + timedelta(days=day, hours=5 + k)))
            nets.append(value)
    for resamples in (7, 50, 400):
        rng = random.Random(report.SEED)
        means = []
        for _ in range(resamples):
            picks = [blocks[int(rng.random() * len(blocks))] for _ in range(len(blocks))]
            means.append(sum(p[0] for p in picks) / sum(p[1] for p in picks))
        assert report.day_block_lower_bound(rows, nets, resamples=resamples) == sorted(means)[math.ceil(0.05 * resamples) - 1]
    assert report.day_block_lower_bound([], []) is None


def test_the_day_is_the_utc_closing_day_whatever_the_offset_of_the_timestamp():
    late_utc = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)
    same_instant_plus3 = late_utc.astimezone(timezone_plus3())
    a = [record(1, closed=late_utc), record(2, closed=late_utc + timedelta(hours=1))]      # two different UTC days
    b = [record(1, closed=same_instant_plus3), record(2, closed=(late_utc + timedelta(hours=1)).astimezone(timezone_plus3()))]
    nets = [Decimal("3"), Decimal("-1")]
    assert report.day_block_lower_bound(a, nets, resamples=50) == report.day_block_lower_bound(b, nets, resamples=50)
    one_day = [record(1, closed=late_utc), record(2, closed=late_utc + timedelta(minutes=10))]
    assert report.day_block_lower_bound(one_day, nets, resamples=50) == pytest.approx(1.0)  # one block: its own mean


def timezone_plus3():
    from datetime import timezone
    return timezone(timedelta(hours=3))


def test_correlated_days_widen_the_interval_that_trades_alone_would_report():
    # ten days, ten trades each, every trade of a day identical: ten independent observations, not a hundred
    rows, nets = [], []
    for day in range(10):
        value = Decimal("6") if day % 2 == 0 else Decimal("-4")
        for k in range(10):
            rows.append(record(day * 10 + k, closed=DAY0 + timedelta(days=day, hours=5)))
            nets.append(value)
    assert report.lower_bound(nets) > report.day_block_lower_bound(rows, nets)


# --- E without the best trades ----------------------------------------------------------------------------------

def test_mean_without_the_best_trades():
    nets = [Decimal(v) for v in ("10", "9", "8", "1", "1", "-1")]
    assert report.mean_without_best(nets) == Decimal("1") / 3
    assert report.mean_without_best([Decimal(v) for v in ("9", "-1", "10", "8", "1", "1")]) == Decimal("1") / 3
    assert report.mean_without_best(nets[:3]) is None and report.mean_without_best([]) is None
    assert report.mean_without_best([Decimal("5")] * 4) == Decimal("5")


# --- drawdown ---------------------------------------------------------------------------------------------------

def test_drawdown_is_peak_to_trough_in_closing_order(monkeypatch):
    monkeypatch.setattr(report, "net_pnl", lambda r: Decimal(r["gross_pnl"]))
    rows = [record(1, gross="-50", closed=DAY0 + timedelta(hours=7)), record(2, gross="10", closed=DAY0 + timedelta(hours=5)),
            record(3, gross="-20", closed=DAY0 + timedelta(hours=9)), record(4, gross="5", closed=DAY0 + timedelta(hours=8))]
    # by closing time: +10 -> 1010 (peak), -50 -> 960, +5 -> 965, -20 -> 945: fall of 65 from 1010
    assert report.realized_drawdown_pct(rows, Decimal("1000")) == Decimal("65") / Decimal("1010") * 100
    assert report.realized_drawdown_pct([], Decimal("1000")) == 0
    assert report.realized_drawdown_pct([record(1, gross="40")], Decimal("1000")) == 0


def test_the_stop_is_at_or_above_ten_percent(monkeypatch):
    monkeypatch.setattr(report, "net_pnl", lambda r: Decimal(r["gross_pnl"]))
    assert report.realized_drawdown_pct([record(1, gross="-100")], Decimal("1000")) == Decimal("10")
    assert report.realized_drawdown_pct([record(1, gross="-99.99")], Decimal("1000")) < report.DRAWDOWN_STOP_PCT


def test_a_drawdown_at_the_limit_stops_with_exit_3_and_below_it_does_not(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "no-archive.sqlite3"
    two_losses = [record(1, gross="-60", closed=DAY0 + timedelta(hours=5)),
                  record(2, gross="-60", closed=DAY0 + timedelta(hours=9))]
    root = write_state(tmp_path / "a", two_losses)
    code, out = run(monkeypatch, capsys, root, missing, "--capital", "1000")
    assert code == 3 and "STOP CONDITION: realized drawdown" in out
    root = write_state(tmp_path / "b", two_losses[:1])
    code, out = run(monkeypatch, capsys, root, missing, "--capital", "1000")
    assert code == 0 and "STOP CONDITION" not in out and "realized drawdown: 6." in out
    code, out = run(monkeypatch, capsys, root, missing, "--capital", "600")      # same loss on a smaller account
    assert code == 3


def test_exactly_ten_percent_stops_end_to_end_and_a_hair_less_does_not(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "no-archive.sqlite3"
    # net = gross - fees - 0.001 x (cost + gross): -99 - 0.099 - 0.901 = -100 exactly on 1000
    assert report.net_pnl(record(1, gross="-99", cost="1000", fees="0.099")) == Decimal("-100")
    root = write_state(tmp_path / "at", [record(1, gross="-99", cost="1000", fees="0.099")])
    code, out = run(monkeypatch, capsys, root, missing, "--capital", "1000")
    assert code == 3 and "realized drawdown: 10.00 %" in out and "STOP CONDITION" in out
    root = write_state(tmp_path / "under", [record(1, gross="-99", cost="1000", fees="0.098")])
    code, out = run(monkeypatch, capsys, root, missing, "--capital", "1000")
    assert code == 0 and "STOP CONDITION" not in out


@pytest.mark.parametrize("capital", ["0", "-5", "NaN", "inf", "abc", "", "1,5", "0.5", "1e999", "1e-999999", "1000000000001"])
def test_a_bad_capital_is_refused(tmp_path, monkeypatch, capital):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    with pytest.raises(SystemExit) as raised:
        report.main(["--start", START, "--capital", capital])
    assert raised.value.code == 2


# --- price lookup and window returns ---------------------------------------------------------------------------

def test_price_is_linear_inside_the_hour_and_a_missing_bar_is_never_guessed():
    bars = {0: (100.0, 110.0), HOUR_MS: (110.0, 130.0)}
    assert report.price_at(bars, 0, "X") == 100.0
    assert report.price_at(bars, HOUR_MS // 2, "X") == pytest.approx(105.0)
    assert report.price_at(bars, HOUR_MS + HOUR_MS // 4, "X") == pytest.approx(115.0)
    with pytest.raises(report.BenchmarkUnavailable, match="no archived 1h bar for X at 1970-01-01T02:00:00"):
        report.price_at(bars, 2 * HOUR_MS + 5, "X")


def test_each_trade_gets_the_basket_return_over_its_own_window(tmp_path):
    database = write_market_archive(tmp_path / "m.sqlite3", ["AAA", "BBB"], 48,
                                    lambda s, h: 100.0 * (1.01 if s == "AAA" else 1.03) ** h)
    short = record(1, opened=DAY0 + timedelta(hours=1), closed=DAY0 + timedelta(hours=3))
    long_ = record(2, opened=DAY0 + timedelta(hours=1), closed=DAY0 + timedelta(hours=11))
    returns = report.window_returns([short, long_], ["AAA", "BBB"], database)
    assert returns[0] == pytest.approx(((1.01 ** 2 - 1) + (1.03 ** 2 - 1)) / 2)
    assert returns[1] == pytest.approx(((1.01 ** 10 - 1) + (1.03 ** 10 - 1)) / 2)
    assert report.window_returns([], ["AAA"], database) == [] and report.window_returns([short], [], database) == []


def test_a_missing_symbol_or_hour_makes_the_benchmark_unavailable(tmp_path):
    database = write_market_archive(tmp_path / "m.sqlite3", ["AAA"], 8, growth(0.0))
    trade = record(1, opened=DAY0 + timedelta(hours=1), closed=DAY0 + timedelta(hours=3))
    with pytest.raises(report.BenchmarkUnavailable, match="BBB"):
        report.window_returns([trade], ["AAA", "BBB"], database)
    late = record(2, opened=DAY0 + timedelta(hours=1), closed=DAY0 + timedelta(hours=20))
    with pytest.raises(report.BenchmarkUnavailable, match="AAA"):
        report.window_returns([late], ["AAA"], database)


def test_the_excess_is_gross_return_minus_the_benchmark():
    rows = [record(1, gross="30", cost="1000", closed=DAY0 + timedelta(days=1, hours=5)),
            record(2, gross="-10", cost="500", closed=DAY0 + timedelta(days=2, hours=5))]
    summary = report.excess_summary(rows, [0.01, 0.02])
    assert summary["mean"] == pytest.approx(((0.03 - 0.01) + (-0.02 - 0.02)) / 2)
    excess = [0.03 - 0.01, -0.02 - 0.02]
    assert summary["day_lower_bound"] != pytest.approx(summary["mean"])         # two days: not the plain mean
    assert summary["lower_bound"] == report.lower_bound(excess)
    assert summary["day_lower_bound"] == report.day_block_lower_bound(rows, excess)
    assert report.excess_summary([], []) == {"mean": None, "lower_bound": None, "day_lower_bound": None}


# --- the market archive is read, never written -----------------------------------------------------------------

def test_the_market_archive_is_opened_read_only(tmp_path):
    database = write_market_archive(tmp_path / "m.sqlite3", ["AAA"], 8, growth(0.01))
    before = {p.name: p.read_bytes() for p in database.parent.iterdir()}
    bars = report.read_bars(database, "AAA", ms(DAY0 - timedelta(hours=2)), ms(DAY0 + timedelta(hours=3)))
    assert len(bars) == 6
    assert {p.name: p.read_bytes() for p in database.parent.iterdir()} == before
    assert sorted(p.name for p in database.parent.iterdir()) == ["m.sqlite3"]          # no -wal / -shm side files
    with pytest.raises(sqlite3.OperationalError):          # the connection the report uses cannot write
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            connection.execute("DELETE FROM market_data_bars")
        finally:
            connection.close()


def test_an_unfinished_write_ahead_log_makes_the_archive_unavailable(tmp_path):
    database = write_market_archive(tmp_path / "m.sqlite3", ["AAA"], 8, growth(0.01))
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode = WAL")
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("DELETE FROM market_data_bars WHERE symbol = 'AAA' AND open_time_ms > 0")
        writer.commit()
        assert database.with_name("m.sqlite3-wal").stat().st_size > 0
        with pytest.raises(report.BenchmarkUnavailable, match="unfinished write-ahead log"):
            report.read_bars(database, "AAA", 0, ms(DAY0 + timedelta(days=1)))
    finally:
        writer.close()


def test_a_missing_or_foreign_archive_is_unavailable_and_nothing_is_created(tmp_path):
    with pytest.raises(report.BenchmarkUnavailable, match="no market archive"):
        report.read_bars(tmp_path / "absent" / "m.sqlite3", "AAA", 0, HOUR_MS)
    assert not (tmp_path / "absent").exists()
    foreign = tmp_path / "foreign.sqlite3"
    sqlite3.connect(foreign).close()
    before = foreign.read_bytes()
    with pytest.raises(report.BenchmarkUnavailable):
        report.read_bars(foreign, "AAA", 0, HOUR_MS)
    assert foreign.read_bytes() == before


# --- the verdict ------------------------------------------------------------------------------------------------

def verdict_text(**overrides):
    summary = {"trades": 100, "e": Decimal("5"), "lower_bound": 1.0, "day_lower_bound": 1.0,
               "top_removed_e": Decimal("1"), "excess_mean": 0.01, "excess_lower_bound": 0.005,
               "excess_day_lower_bound": 0.004}
    summary.update(overrides)
    return report.verdict(summary)


def test_pass_needs_every_condition():
    assert verdict_text().startswith("PASS")
    for overrides, reason in [
        ({"day_lower_bound": 0.0}, "day-block lower bound"), ({"day_lower_bound": -1.0}, "day-block lower bound"),
        ({"day_lower_bound": None}, "day-block lower bound"), ({"top_removed_e": Decimal("0")}, "3 best trades"),
        ({"top_removed_e": Decimal("-1")}, "3 best trades"), ({"top_removed_e": None}, "3 best trades"),
        ({"excess_mean": None}, "benchmark is unavailable"), ({"excess_lower_bound": None}, "benchmark is unavailable"),
        ({"excess_day_lower_bound": None}, "benchmark is unavailable"),
        ({"excess_day_lower_bound": 0.0}, "do not beat the basket"), ({"excess_day_lower_bound": -0.01}, "do not beat the basket"),
        ({"excess_mean": 0.0}, "do not beat the basket"), ({"excess_mean": -0.01}, "do not beat the basket"),
        ({"excess_lower_bound": 0.0}, "do not beat the basket"), ({"excess_lower_bound": -0.01}, "do not beat the basket"),
    ]:
        text = verdict_text(**overrides)
        assert text.startswith("INCONCLUSIVE (PASS conditions on E hold, but ") and reason in text, (overrides, text)


def test_a_condition_that_was_not_computed_is_not_a_pass():
    summary = {"trades": 100, "e": Decimal("5"), "lower_bound": 1.0}
    text = report.verdict(summary)
    assert text.startswith("INCONCLUSIVE") and "day-block" in text and "3 best trades" in text and "benchmark" in text


def test_several_reasons_are_all_listed_and_the_earlier_rules_are_unchanged():
    text = verdict_text(day_lower_bound=0.0, excess_mean=-1.0)
    assert "the benchmark is unavailable" not in text
    assert "day-block" in text and "do not beat the basket" in text and "; " in text
    assert verdict_text(trades=29).startswith("INSUFFICIENT") and verdict_text(e=Decimal("0")).startswith("FAIL")
    assert verdict_text(lower_bound=0.0).startswith("INCONCLUSIVE (E > 0, lower bound <= 0)")
    assert verdict_text(trades=99).startswith("INCONCLUSIVE (E > 0, 99 < 100")


# --- end to end -------------------------------------------------------------------------------------------------

def test_a_system_that_beats_the_basket_passes_end_to_end(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", hundred_trades(gross="10"))                 # +1 % gross over 4 hours
    database = write_market_archive(tmp_path / "m.sqlite3", [*UNIVERSE, "BTCUSDT"], 24 * 27, growth(0.0))
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    code, out = run(monkeypatch, capsys, root, database, "--end", iso(DAY0 + timedelta(days=30)))
    assert code == 0, out
    assert f"equal-weight basket of {len(UNIVERSE)} universe coins" in out
    assert "mean excess return per trade: 1.0000 %" in out and "against BTCUSDT alone" in out
    assert "verdict: PASS (E > 0, lower bounds > 0, beats the basket)" in out
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before


def test_a_system_that_only_rides_a_rising_market_does_not_pass(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", hundred_trades(gross="10"))                 # +1 % gross over 4 hours
    others = [s for s in UNIVERSE if s != "BTCUSDT"]                      # BTC is itself one of the basket's coins
    write_market_archive(tmp_path / "m.sqlite3", others, 24 * 27, growth(0.005))        # about +2 % per window
    database = write_market_archive(tmp_path / "m.sqlite3", ["BTCUSDT"], 24 * 27, growth(0.0))
    code, out = run(monkeypatch, capsys, root, database, "--end", iso(DAY0 + timedelta(days=30)))
    assert code == 0
    assert "verdict: INCONCLUSIVE (PASS conditions on E hold, but the trades do not beat the basket" in out
    # BTC alone would have said "beats": it is shown, and it is not part of the verdict
    assert "against BTCUSDT alone: mean excess 1.0000 %" in out and "not part of the verdict" in out
    assert "mean excess return per trade: -0.9" in out                       # 1 % - (19 x 2.015 % + 0) / 20


def test_a_missing_btc_comparison_does_not_touch_the_verdict(tmp_path, monkeypatch, capsys):
    rules = json.loads(Path(DEFAULT_INSTRUMENT_RULES_PATH).read_text(encoding="utf-8"))
    rules["rules"] = [r for r in rules["rules"] if r["symbol"] != "BTCUSDT"]          # a universe without BTC
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    others = [s for s in UNIVERSE if s != "BTCUSDT"]
    root = write_state(tmp_path / "state", hundred_trades(gross="10"))
    database = write_market_archive(tmp_path / "m.sqlite3", others, 24 * 27, growth(0.0))
    code, out = run(monkeypatch, capsys, root, database, "--instrument-rules", str(rules_path),
                    "--end", iso(DAY0 + timedelta(days=30)))
    assert code == 0, out
    assert f"equal-weight basket of {len(others)} universe coins" in out
    assert "BTCUSDT comparison unavailable (no archived 1h bar for BTCUSDT" in out
    assert "verdict: PASS (E > 0, lower bounds > 0, beats the basket)" in out


def test_without_benchmark_data_the_report_says_what_to_fetch_and_cannot_pass(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", hundred_trades(gross="10"))
    absent = tmp_path / "nothing-here" / "market_data.sqlite3"
    code, out = run(monkeypatch, capsys, root, absent, "--end", iso(DAY0 + timedelta(days=30)))
    assert code == 0
    assert "benchmark: UNAVAILABLE (no market archive at" in out
    assert "python tools/fetch_historical_market_data.py --symbols " in out and "BTCUSDT" in out and UNIVERSE[0] in out
    assert "--start 2026-10-18T01:00:00+00:00" in out
    assert "the benchmark is unavailable" in out and "PASS (" not in out
    # the printed command is accepted by the fetch tool's own argument parser and names what the report needs
    import shlex
    from tools.fetch_historical_market_data import build_parser
    line = next(l for l in out.splitlines() if "tools/fetch_historical_market_data.py" in l)
    arguments = build_parser().parse_args(shlex.split(line.split("tools/fetch_historical_market_data.py", 1)[1]))
    assert sorted(arguments.symbols) == sorted(UNIVERSE) and arguments.timeframe == "1h"
    assert arguments.start == DAY0 + timedelta(hours=1) and arguments.end >= DAY0 + timedelta(days=24, hours=8)
    assert not absent.parent.exists()


def test_a_trade_universe_that_cannot_be_read_is_an_unavailable_benchmark_not_a_crash(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", hundred_trades(gross="10"))
    database = write_market_archive(tmp_path / "m.sqlite3", ["BTCUSDT"], 24 * 27, growth(0.0))
    bad = tmp_path / "rules.json"
    bad.write_text("{not json", encoding="utf-8")
    code, out = run(monkeypatch, capsys, root, database, "--instrument-rules", str(bad))
    assert code == 0 and "benchmark: UNAVAILABLE (trade universe from" in out and "PASS (" not in out


def test_the_default_market_archive_is_resolved_from_the_configured_directory(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", hundred_trades(gross="10"))
    archive_dir = tmp_path / "market"
    write_market_archive(archive_dir / report.MARKET_ARCHIVE_FILENAME, [*UNIVERSE, "BTCUSDT"], 24 * 27, growth(0.0))
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(root))
    monkeypatch.setenv("ATLAS_MARKET_ARCHIVE_DIRECTORY", str(archive_dir))
    assert report.main(["--start", START]) == 0
    assert "mean excess return per trade: 1.0000 %" in capsys.readouterr().out


# --- review 44: what a real run looks like (mid-hour timestamps, non-geometric prices) -------------------------------

def reference_bound(values, resamples=report.RESAMPLES):
    """The lower bound of a mean computed independently of the tool: a seeded bootstrap, 5 % quantile."""
    rng = random.Random(report.SEED)
    n = len(values)
    means = sorted(math.fsum(values[int(rng.random() * n)] for _ in range(n)) / n for _ in range(resamples))
    return means[math.ceil(0.05 * resamples) - 1]


def wobble(symbol, hour):
    """Open prices that are neither geometric nor shared by the coins, so a shift, a swap or a mix-up shows."""
    return 100.0 + 3.0 * math.sin(hour / 3.0) + (hour % 5) * 0.4 + len(symbol)


def test_mid_hour_trades_through_the_real_archive_match_an_independent_computation(tmp_path, monkeypatch, capsys):
    rows, expected_excess = [], []
    symbols = [*UNIVERSE]
    database = write_market_archive(tmp_path / "m.sqlite3", symbols, 24 * 6, wobble)
    for i in range(12):
        opened = DAY0 + timedelta(days=i // 3, hours=1 + 6 * (i % 3), minutes=7 + 5 * i, seconds=13)
        closed = opened + timedelta(hours=2, minutes=19 + i, seconds=41)
        rows.append(record(i, gross=str(4 + (i % 4)), opened=opened, closed=closed))

    def price(symbol, moment):
        origin = DAY0 - timedelta(hours=2)
        hours = (moment - origin).total_seconds() / 3600
        hour = math.floor(hours)
        return wobble(symbol, hour) + (wobble(symbol, hour + 1) - wobble(symbol, hour)) * (hours - hour)

    for r in rows:
        opened, closed = report.parse_utc(r["opened_at"]), report.parse_utc(r["closed_at"])
        basket = sum(price(s, closed) / price(s, opened) - 1 for s in symbols) / len(symbols)
        expected_excess.append(float(Decimal(r["gross_pnl"]) / Decimal(r["cost_quote"])) - basket)
    returns = report.window_returns(rows, symbols, database)
    assert [float(Decimal(r["gross_pnl"]) / Decimal(r["cost_quote"])) - b for r, b in zip(rows, returns)] == \
        pytest.approx(expected_excess, abs=1e-12)
    summary = report.excess_summary(rows, returns)
    assert summary["mean"] == pytest.approx(sum(expected_excess) / 12, abs=1e-12)
    assert summary["lower_bound"] == pytest.approx(reference_bound(expected_excess), abs=1e-12)
    # the same through main(): the printed lower bound is that independent figure
    root = write_state(tmp_path / "state", rows)
    code, out = run(monkeypatch, capsys, root, database)
    assert code == 0
    assert f"95 % lower bound: {reference_bound(expected_excess) * 100:.4f} %" in out


def test_the_bar_range_reaches_the_hour_that_contains_the_first_open(tmp_path):
    database = write_market_archive(tmp_path / "m.sqlite3", ["AAA"], 6, wobble)
    mid = record(1, opened=DAY0 + timedelta(minutes=20), closed=DAY0 + timedelta(hours=2, minutes=40))
    # the first bar needed starts at DAY0 and the archive begins two hours earlier; a range starting at the open
    # itself would miss the containing hour
    assert report.window_returns([mid], ["AAA"], database)
    short = tmp_path / "short.sqlite3"
    # an archive that starts exactly at the trade's hour has that bar, and one that starts an hour later does not
    write_market_archive(short, ["AAA"], 6, wobble, start=DAY0)
    assert report.window_returns([mid], ["AAA"], short)
    late = tmp_path / "late.sqlite3"
    write_market_archive(late, ["AAA"], 6, wobble, start=DAY0 + timedelta(hours=1))
    with pytest.raises(report.BenchmarkUnavailable):
        report.window_returns([mid], ["AAA"], late)


def test_the_fetch_hint_starts_at_the_hour_of_the_first_open_and_ends_after_the_last_close():
    rows = [record(1, opened=DAY0 + timedelta(hours=3, minutes=41, seconds=9), closed=DAY0 + timedelta(hours=7, minutes=5)),
            record(2, opened=DAY0 + timedelta(hours=9, minutes=2), closed=DAY0 + timedelta(hours=13, minutes=58, seconds=30))]
    hint = report.fetch_hint(["AAA", "BTCUSDT"], rows)
    assert "--symbols AAA BTCUSDT --timeframe 1h" in hint
    assert f"--start {iso(DAY0 + timedelta(hours=3))} " in hint
    assert hint.endswith(f"--end {iso(DAY0 + timedelta(hours=13, minutes=59, seconds=59))}")


def test_the_price_query_pairs_open_with_open_and_close_with_close(tmp_path):
    database = write_market_archive(tmp_path / "m.sqlite3", ["AAA"], 4, lambda s, h: [100.0, 140.0, 90.0, 120.0, 130.0][h])
    bars = report.read_bars(database, "AAA", ms(DAY0 - timedelta(hours=2)), ms(DAY0 + timedelta(hours=1)))
    assert bars == {ms(DAY0 - timedelta(hours=2)): (100.0, 140.0), ms(DAY0 - timedelta(hours=1)): (140.0, 90.0),
                    ms(DAY0): (90.0, 120.0), ms(DAY0 + timedelta(hours=1)): (120.0, 130.0)}


# --- review 44: guards, failures and the pinned defaults -------------------------------------------------------

def test_a_basket_of_a_few_coins_is_refused(tmp_path):
    rules = json.loads(Path(DEFAULT_INSTRUMENT_RULES_PATH).read_text(encoding="utf-8"))
    rules["rules"] = rules["rules"][: report.MIN_BASKET_COINS - 1]
    small = tmp_path / "small.json"
    small.write_text(json.dumps(rules), encoding="utf-8")
    with pytest.raises(report.BenchmarkUnavailable, match="fewer than the 10"):
        report.basket_symbols(small)
    rules["rules"] = json.loads(Path(DEFAULT_INSTRUMENT_RULES_PATH).read_text(encoding="utf-8"))["rules"][: report.MIN_BASKET_COINS]
    exact = tmp_path / "exact.json"
    exact.write_text(json.dumps(rules), encoding="utf-8")
    assert len(report.basket_symbols(exact)) == report.MIN_BASKET_COINS


def test_the_basket_is_the_whole_configured_universe():
    configured = json.loads(Path(DEFAULT_INSTRUMENT_RULES_PATH).read_text(encoding="utf-8"))["rules"]
    assert len(UNIVERSE) == len(configured) == len({r["symbol"] for r in configured})
    assert UNIVERSE == sorted(r["symbol"] for r in configured)


def test_the_inputs_in_effect_are_printed_so_the_evidence_shows_them(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", [record(1)])
    code, out = run(monkeypatch, capsys, root, tmp_path / "m.sqlite3", "--capital", "5000")
    assert f"inputs in effect: --capital 5000; --instrument-rules {DEFAULT_INSTRUMENT_RULES_PATH}; " \
           f"--market-archive {tmp_path / 'm.sqlite3'}" in out


def test_the_closing_days_are_printed(tmp_path, monkeypatch, capsys):
    rows = [record(i, closed=DAY0 + timedelta(days=i % 3, hours=5)) for i in range(7)]
    root = write_state(tmp_path / "state", rows)
    code, out = run(monkeypatch, capsys, root, tmp_path / "none.sqlite3")
    assert "3 distinct closing days" in out


def test_an_unexpected_error_in_the_benchmark_still_reports_the_stop_condition(tmp_path, monkeypatch, capsys):
    rows = [record(1, gross="-60", closed=DAY0 + timedelta(hours=5)), record(2, gross="-60", closed=DAY0 + timedelta(hours=9))]
    root = write_state(tmp_path / "state", rows)
    database = write_market_archive(tmp_path / "m.sqlite3", [*UNIVERSE, "BTCUSDT"], 48, growth(0.0))
    connection = sqlite3.connect(database)                        # a tampered bar: a zero open price
    connection.execute("UPDATE market_data_bars SET open = 0.0 WHERE symbol = 'AAVEUSDT'")
    connection.commit()
    connection.close()
    code, out = run(monkeypatch, capsys, root, database, "--capital", "1000")
    assert code == 3 and "STOP CONDITION" in out
    assert "benchmark: UNAVAILABLE (unexpected ZeroDivisionError" in out and "PASS (" not in out


def test_a_nan_is_never_above_zero_and_never_passes():
    nan = float("nan")
    assert report.above_zero(1e-12) and not report.above_zero(0.0) and not report.above_zero(-1.0)
    assert not report.above_zero(None) and not report.above_zero(nan) and not report.above_zero(Decimal("NaN"))
    for key in ("day_lower_bound", "top_removed_e", "excess_mean", "excess_lower_bound", "excess_day_lower_bound"):
        assert not verdict_text(**{key: nan}).startswith("PASS"), key
    assert verdict_text(e=nan).startswith("FAIL") and verdict_text(lower_bound=nan).startswith("INCONCLUSIVE")


def test_the_bootstrap_sizes_are_the_pinned_ones_everywhere():
    import inspect
    for function in (report.lower_bound, report.day_block_lower_bound):
        assert inspect.signature(function).parameters["resamples"].default == report.RESAMPLES == 10_000
        assert inspect.signature(function).parameters["seed"].default == report.SEED


def test_a_failure_after_the_basket_was_computed_does_not_leave_a_half_computed_benchmark(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", hundred_trades(gross="10"))
    database = write_market_archive(tmp_path / "m.sqlite3", [*UNIVERSE], 24 * 27, growth(0.0))
    real = report.window_returns

    def failing_for_btc(records, symbols, path):
        if symbols == [report.BENCHMARK_BTC]:
            raise RuntimeError("boom")
        return real(records, symbols, path)

    monkeypatch.setattr(report, "window_returns", failing_for_btc)
    code, out = run(monkeypatch, capsys, root, database, "--end", iso(DAY0 + timedelta(days=30)))
    assert code == 0 and "mean excess return per trade: 1.0000 %" in out        # the basket itself was computed
    assert "benchmark: UNAVAILABLE (unexpected RuntimeError: boom)" in out
    assert "PASS (" not in out and "the benchmark is unavailable" in out


def test_with_no_trades_there_is_no_benchmark_section(tmp_path, monkeypatch, capsys):
    root = tmp_path / "empty"
    root.mkdir()
    code, out = run(monkeypatch, capsys, root, tmp_path / "none.sqlite3")
    assert code == 0 and "benchmark" not in out and "INSUFFICIENT (0 < 30" in out


# --- review 45: the wiring from each computed figure to the verdict and to the evidence ----------------------------

def clustered_trades(per_day_gross, per_day=10, gross_of=None):
    rows = []
    for day, gross in enumerate(per_day_gross):
        for k in range(per_day):
            opened = DAY0 + timedelta(days=day, hours=1 + k % 5)
            rows.append(record(day * 100 + k, gross=str(gross), opened=opened, closed=opened + timedelta(hours=4)))
    return rows


def run_with_basket(tmp_path, monkeypatch, capsys, rows, basket_of, btc=0.0, *args):
    """main() with the basket's per-trade returns supplied directly (the archive read is exercised elsewhere)."""
    root = write_state(tmp_path / f"state{len(list(tmp_path.glob('state*')))}", rows)
    monkeypatch.setattr(report, "window_returns", lambda records, symbols, path: (
        [btc] * len(records) if symbols == [report.BENCHMARK_BTC] else list(basket_of(records))))
    database = tmp_path / "m.sqlite3"
    database.write_bytes(b"")                      # exists; never read because window_returns is replaced
    return run(monkeypatch, capsys, root, database, "--end", iso(DAY0 + timedelta(days=40)), *args)


def verdict_line(out):
    return next(line for line in out.splitlines() if line.startswith("verdict"))


def gross_return(r):
    return float(Decimal(r["gross_pnl"]) / Decimal(r["cost_quote"]))


def test_summarize_wires_the_day_block_bound_and_the_best_trades_check():
    rows = clustered_trades([3, 4, 2, 5, 1, 3, 4, 2, 5, 1])
    nets = [report.net_pnl(r) for r in rows]
    summary = report.summarize(rows)
    assert summary["day_lower_bound"] == report.day_block_lower_bound(rows, nets)
    assert summary["day_lower_bound"] != summary["lower_bound"]
    assert summary["lower_bound"] == report.lower_bound(nets)
    assert summary["top_removed_e"] == report.mean_without_best(nets)
    assert summary["top_removed_e"] != summary["e"]


def test_only_the_day_block_bound_of_e_failing_blocks_a_pass(tmp_path, monkeypatch, capsys):
    rows = clustered_trades([75, -40] * 5)                       # E and its trade-level bound above zero, by day not
    nets = [report.net_pnl(r) for r in rows]
    assert report.lower_bound(nets) > 0 and report.day_block_lower_bound(rows, nets) < 0
    code, out = run_with_basket(tmp_path, monkeypatch, capsys, rows, lambda recs: [gross_return(r) - 0.02 for r in recs])
    assert verdict_line(out) == ("verdict: INCONCLUSIVE (PASS conditions on E hold, but the day-block lower bound "
                                 "of E is not above zero)")


def test_only_the_best_trades_check_failing_blocks_a_pass(tmp_path, monkeypatch, capsys):
    # three huge winners, one on each of three of the four closing days, and small losers: E and both of its bounds
    # stay above zero, only E without the three best trades does not
    rows = [record(i, gross="900" if i in (0, 25, 50) else "-0.5", cost="1000", fees="0",
                   opened=DAY0 + timedelta(days=i // 25, hours=1), closed=DAY0 + timedelta(days=i // 25, hours=5))
            for i in range(100)]
    summary = report.summarize(rows)
    assert summary["lower_bound"] > 0 and summary["day_lower_bound"] > 0 and summary["top_removed_e"] < 0
    code, out = run_with_basket(tmp_path, monkeypatch, capsys, rows, lambda recs: [-0.5] * len(recs))
    assert verdict_line(out) == ("verdict: INCONCLUSIVE (PASS conditions on E hold, but E without the 3 best trades "
                                 "is not above zero)")


def test_only_the_day_block_bound_of_the_excess_failing_blocks_a_pass(tmp_path, monkeypatch, capsys):
    rows = clustered_trades([20] * 10)                           # E is steady; the excess alternates by day
    pattern = {day: (0.006 if day % 2 == 0 else -0.004) for day in range(10)}
    basket = lambda recs: [gross_return(r) - pattern[report.parse_utc(r["closed_at"]).day - DAY0.day] for r in recs]
    figures = report.excess_summary(rows, basket(rows))
    assert figures["mean"] > 0 and figures["lower_bound"] > 0 and figures["day_lower_bound"] < 0
    code, out = run_with_basket(tmp_path, monkeypatch, capsys, rows, basket)
    assert verdict_line(out) == ("verdict: INCONCLUSIVE (PASS conditions on E hold, but the trades do not beat the "
                                 "basket held over the same windows)")


def test_only_the_trade_level_bound_of_the_excess_failing_blocks_a_pass(tmp_path, monkeypatch, capsys):
    rows = [record(i, gross="20", opened=DAY0 + timedelta(days=i // 4, hours=1), closed=DAY0 + timedelta(days=i // 4, hours=5))
            for i in range(100)]
    pattern = [0.03 if i % 2 == 0 else -0.024 for i in range(100)]
    basket = lambda recs: [0.02 - pattern[i] for i in range(len(recs))]        # the excess is the pattern
    figures = report.excess_summary(rows, basket(rows))
    assert figures["mean"] > 0 and figures["lower_bound"] < 0 < figures["day_lower_bound"]
    code, out = run_with_basket(tmp_path, monkeypatch, capsys, rows, basket)
    assert verdict_line(out) == ("verdict: INCONCLUSIVE (PASS conditions on E hold, but the trades do not beat the "
                                 "basket held over the same windows)")


def test_the_excess_figures_failing_together_block_a_pass(tmp_path, monkeypatch, capsys):
    rows = clustered_trades([20] * 25, per_day=4)
    code, out = run_with_basket(tmp_path, monkeypatch, capsys, rows, lambda recs: [gross_return(r) + 0.01 for r in recs])
    assert verdict_line(out) == ("verdict: INCONCLUSIVE (PASS conditions on E hold, but the trades do not beat the "
                                 "basket held over the same windows)")
    code, out = run_with_basket(tmp_path, monkeypatch, capsys, rows, lambda recs: [gross_return(r) - 0.01 for r in recs])
    assert verdict_line(out) == "verdict: PASS (E > 0, lower bounds > 0, beats the basket)"      # the same trades


def test_the_drawdown_counts_only_the_window(tmp_path, monkeypatch, capsys):
    old = [record(900 + i, gross="-300", opened=DAY0 - timedelta(days=5, hours=-i), closed=DAY0 - timedelta(days=4, hours=-i))
           for i in range(2)]
    root = write_state(tmp_path / "state", old + [record(1, gross="5")])
    code, out = run(monkeypatch, capsys, root, tmp_path / "none.sqlite3", "--capital", "1000")
    assert code == 0 and "STOP CONDITION" not in out and "realized drawdown: 0.00 %" in out


def test_the_printed_figures_are_the_computed_ones(tmp_path, monkeypatch, capsys):
    rows = clustered_trades([20, 14, 26, 9, 31, 17, 22, 12, 28, 15])
    nets = [report.net_pnl(r) for r in rows]
    basket_returns = [0.004 * (i % 7) for i in range(len(rows))]
    excess = [gross_return(r) - b for r, b in zip(rows, basket_returns)]
    btc_excess = [gross_return(r) for r in rows]                                   # BTC held flat
    code, out = run_with_basket(tmp_path, monkeypatch, capsys, rows, lambda recs: basket_returns, 0.0, "--capital", "5000")
    days = len({report.parse_utc(r["closed_at"]).date() for r in rows})
    assert f"95 % lower bound of E (bootstrap, 10000 resamples, seed 20261017): {report.lower_bound(nets):.4f}" in out
    assert (f"day-block lower bound of E (whole UTC closing days resampled; {days} distinct closing days): "
            f"{report.day_block_lower_bound(rows, nets):.4f}") in out
    assert f"E without the 3 best trades: {report.mean_without_best(nets):.4f}" in out
    assert report.mean_without_best(nets) != sum(nets) / len(nets)
    assert (f"mean excess return per trade: {math.fsum(excess) / len(excess) * 100:.4f} %  95 % lower bound: "
            f"{report.lower_bound(excess) * 100:.4f} %  day-block lower bound: "
            f"{report.day_block_lower_bound(rows, excess) * 100:.4f} %") in out
    assert (f"against BTCUSDT alone: mean excess {math.fsum(btc_excess) / len(btc_excess) * 100:.4f} %, "
            f"lower bound {report.lower_bound(btc_excess) * 100:.4f} %") in out
    assert report.lower_bound(btc_excess) != math.fsum(btc_excess) / len(btc_excess)
    assert "starting capital 5000; stop at 10 %" in out


def test_an_idle_connection_to_the_archive_does_not_make_it_unavailable(tmp_path):
    database = write_market_archive(tmp_path / "m.sqlite3", ["AAA"], 8, growth(0.01))
    idle = sqlite3.connect(database)
    try:
        idle.execute("PRAGMA journal_mode = WAL")
        idle.execute("SELECT count(*) FROM market_data_bars").fetchone()
        log = database.with_name("m.sqlite3-wal")
        assert not log.exists() or log.stat().st_size == 0                         # nothing written, nothing to lose
        bars = report.read_bars(database, "AAA", ms(DAY0 - timedelta(hours=2)), ms(DAY0 + timedelta(hours=3)))
        assert len(bars) == 6
    finally:
        idle.close()


# --- review 46: the stop's own wiring, the read-only connection, the timeframe filter, the capital range ----------

def test_without_capital_the_bootstrap_default_is_used_and_a_ten_percent_realized_loss_stops(tmp_path, monkeypatch, capsys):
    # two trades of -500 gross on 1000: -500 - 1 - 0.5 each = -1003 on the default 10000, a 10.03 % fall
    losses = [record(1, gross="-500", closed=DAY0 + timedelta(hours=5)), record(2, gross="-500", closed=DAY0 + timedelta(hours=9))]
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(write_state(tmp_path / "a", losses)))
    code = report.main(["--start", START, "--market-archive", str(tmp_path / "none.sqlite3")])
    out = capsys.readouterr().out
    assert code == 3 and "realized drawdown: 10.03 % of peak (starting capital 10000;" in out and "STOP CONDITION" in out
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(write_state(tmp_path / "b", losses[:1])))
    code = report.main(["--start", START, "--market-archive", str(tmp_path / "none.sqlite3")])
    assert code == 0 and "realized drawdown: 5.02 % of peak (starting capital 10000;" in capsys.readouterr().out


def test_a_recovery_after_the_fall_does_not_cancel_the_stop(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(report, "net_pnl", lambda r: Decimal(r["gross_pnl"]))
    rows = [record(1, gross="-110", closed=DAY0 + timedelta(hours=5)), record(2, gross="60", closed=DAY0 + timedelta(hours=9))]
    assert report.realized_drawdown_pct(rows, Decimal("1000")) == Decimal("11")      # the maximum, not the 5 % now
    code, out = run(monkeypatch, capsys, write_state(tmp_path / "state", rows), tmp_path / "none.sqlite3", "--capital", "1000")
    assert code == 3 and "realized drawdown: 11.00 %" in out and "STOP CONDITION" in out


@pytest.mark.parametrize("capital", ["1", "1000000000000"])
def test_the_capital_range_ends_are_accepted(tmp_path, monkeypatch, capsys, capital):
    root = write_state(tmp_path / "state", [record(1)])
    code, out = run(monkeypatch, capsys, root, tmp_path / "none.sqlite3", "--capital", capital)
    assert code == 0 and f"starting capital {capital};" in out


def test_the_report_opens_the_archive_through_a_read_only_immutable_uri(tmp_path, monkeypatch):
    database = write_market_archive(tmp_path / "m.sqlite3", ["AAA"], 4, growth(0.01))
    seen = []
    real_connect = sqlite3.connect

    def spy(target, *args, **kwargs):
        seen.append((target, kwargs.get("uri")))
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr(report.sqlite3, "connect", spy)
    report.read_bars(database, "AAA", 0, ms(DAY0 + timedelta(hours=2)))
    assert seen == [(f"{database.resolve().as_uri()}?mode=ro&immutable=1", True)]


def test_bars_of_another_timeframe_at_the_same_open_time_are_ignored(tmp_path):
    database = write_market_archive(tmp_path / "m.sqlite3", ["AAA"], 4, lambda s, h: [100.0, 110.0, 120.0, 130.0, 140.0][h])
    connection = sqlite3.connect(database)
    batch = connection.execute("SELECT batch_id FROM market_data_bars LIMIT 1").fetchone()[0]
    connection.execute("INSERT INTO market_data_bars (symbol, timeframe, open_time_ms, close_time_ms, open, high, low, "
                       "close, volume, source, batch_id) VALUES ('AAA', '4h', ?, ?, 999.0, 999.0, 1.0, 555.0, 1.0, 'x', ?)",
                       (ms(DAY0), ms(DAY0) + 4 * HOUR_MS - 1, batch))
    connection.commit()
    connection.close()
    bars = report.read_bars(database, "AAA", ms(DAY0), ms(DAY0))
    assert bars == {ms(DAY0): (120.0, 130.0)}


# --- review 47: the Task 015 summary line, the --end wiring, the remaining refusal paths ---------------------------

def test_the_summary_line_shows_the_computed_figures(tmp_path, monkeypatch, capsys):
    rows = [record(1, gross="30", fees="2"), record(2, gross="-12", fees="1.5", closed=DAY0 + timedelta(hours=6)),
            record(3, gross="0.5", fees="0.2", closed=DAY0 + timedelta(hours=7)),
            record(4, gross="10", fees="8.99", closed=DAY0 + timedelta(hours=8))]      # net exactly 0: not a win
    nets = [report.net_pnl(r) for r in rows]
    assert nets[3] == 0
    code, out = run(monkeypatch, capsys, write_state(tmp_path / "state", rows), tmp_path / "none.sqlite3")
    wins = sum(1 for v in nets if v > 0)
    assert wins == 1                                       # 0.5 gross minus fees is a loss: not counted as a win
    assert f"trades: 4  wins after fees: {wins}" in out
    assert (f"gross P&L: {Decimal('28.5'):.2f}  recorded entry fees: {Decimal('12.69'):.2f}  exit fee rate: 0.001  "
            f"net P&L: {sum(nets):.2f}") in out


def test_a_trade_closed_at_or_after_end_is_left_out_end_to_end(tmp_path, monkeypatch, capsys):
    rows = [record(1, gross="10", closed=DAY0 + timedelta(hours=5)), record(2, gross="-40", closed=DAY0 + timedelta(hours=9))]
    root = write_state(tmp_path / "state", rows)
    code, out = run(monkeypatch, capsys, root, tmp_path / "none.sqlite3", "--end", iso(DAY0 + timedelta(hours=9)))
    assert "in window 1; opened before start 0; closed at or after end 1" in out
    assert "trades: 1  wins after fees: 1" in out


@pytest.mark.parametrize("state", ['{"positions": [], "realized_gross_pnl": "0"}',
                                   '{"positions": {}, "realized_gross_pnl": "abc"}',
                                   '{"positions": {}, "realized_gross_pnl": null}',
                                   '[1, 2]'])
def test_more_unreadable_financial_states_are_refused(tmp_path, monkeypatch, capsys, state):
    root = write_state(tmp_path / "state", [record(1)])
    (root / "execution_financial_state.json").write_text(state, encoding="utf-8")
    code, out = run(monkeypatch, capsys, root, tmp_path / "none.sqlite3")
    assert code == 2 and "REFUSED" in out and "verdict" not in out


def test_an_archive_path_that_is_a_directory_is_refused(tmp_path, monkeypatch, capsys):
    root = tmp_path / "state"
    (root / "execution_closed_positions.jsonl").mkdir(parents=True)
    code, out = run(monkeypatch, capsys, root, tmp_path / "none.sqlite3")
    assert code == 2 and "REFUSED" in out
