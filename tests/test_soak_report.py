"""tools/soak_report.py: read-only paper soak expectancy (Task 015, registry v5.99), delta tests only.

Archives are written by Atlas's own writers: ClosedPositionArchiveStore.append everywhere, and the real
ExecutionPortfolioFoundation in the two cases that trade through it. So the report is tested on the line format Atlas
produces, not on hand-made lines. The financial-state file beside a store-written archive is hand-written; the
foundation cases book fees with a test helper at the paper rate, rounded up as the execution manager rounds them.
"""

from __future__ import annotations

import json
import math
import random
from decimal import ROUND_UP, Decimal

import pytest

from core.execution_manager import PAPER_FEE_QUANTUM, PAPER_FEE_RATE_PER_SIDE
from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)
from tools import soak_report as report

START = "2026-10-18T00:00:00+00:00"
ARCHIVE = "execution_closed_positions.jsonl"
STATE = "execution_financial_state.json"


def record(n=1, gross="10", cost="1000", fees="1", opened="2026-10-18T01:00:00+00:00",
           closed="2026-10-18T05:00:00+00:00", symbol="BTCUSDT"):
    return {"position_id": f"LONG:{symbol}:r{n}", "symbol": symbol, "base_quantity": "0", "cost_quote": cost,
            "entry_fees": fees, "average_entry_price": "100", "mark_price": "101", "version": 2,
            "opened_at": opened, "status": "CLOSED", "exit_price": "101", "gross_pnl": gross, "closed_at": closed}


def write_state(root, records, positions=None, realized=None):
    """An archive written by Atlas's own archive store, and a financial state beside it."""
    root.mkdir(parents=True, exist_ok=True)
    store = ClosedPositionArchiveStore(root / ARCHIVE)
    for sequence, item in enumerate(records):
        store.append(sequence, item)
    if realized is None:
        realized = format(sum((Decimal(r["gross_pnl"]) for r in records), Decimal("0")), "f")
    (root / STATE).write_text(json.dumps({
        "cash": "10000", "reserved_capital": "0", "realized_gross_pnl": realized, "fees": "0",
        "positions": positions or {}}), encoding="utf-8")
    return root


def paper_fee(notional):
    return (notional * PAPER_FEE_RATE_PER_SIDE).quantize(PAPER_FEE_QUANTUM, rounding=ROUND_UP)


def trade_through_the_foundation(root, trades, partial_first=False):
    """Open and close positions with the real ExecutionPortfolioFoundation, paper fees booked as Atlas books them."""
    root.mkdir(parents=True, exist_ok=True)
    store = FinancialStateStore(root / STATE)
    store.initialize(Decimal("10000"))
    foundation = ExecutionPortfolioFoundation(
        store, applied_archive=AppliedExecutionArchiveStore(root / "execution_applied_executions.jsonl"),
        closed_archive=ClosedPositionArchiveStore(root / ARCHIVE))
    count = 0

    def fill(action, position_id, symbol, price, base, timestamp):
        nonlocal count
        count += 1
        notional = Decimal(price) * Decimal(base)
        version = (foundation.snapshot()["positions"].get(symbol) or {}).get("version")
        result = ExecutionResult(
            success=True, status="PAPER_EXECUTED", execution_id=f"e{count}", position_id=position_id, symbol=symbol,
            action=action, filled_price=price, filled_base_quantity=Decimal(base), filled_quote_notional=notional,
            fee_amount=paper_fee(notional), fee_currency="USDT", idempotency_key=f"r{count}",
            provenance_ref=f"transaction-journal:r{count}", timestamp=timestamp)
        foundation.apply_confirmed(result, risk_authorized=True, reservation_confirmed=True,
                                   expected_position_version=version)

    for i, (symbol, buy, sell) in enumerate(trades):
        position_id = f"LONG:{symbol}:t{i}"
        fill("BUY", position_id, symbol, buy, "1.2345", f"2026-10-18T0{i}:00:00+00:00")
        if partial_first and i == 0:
            fill("SELL", position_id, symbol, "105", "0.5", f"2026-10-18T0{i}:30:00+00:00")
            fill("SELL", position_id, symbol, sell, "0.7345", f"2026-10-18T0{i}:40:00+00:00")
        else:
            fill("SELL", position_id, symbol, sell, "1.2345", f"2026-10-18T0{i}:40:00+00:00")
    return root


def summary_of(nets, **overrides):
    """A summary whose Task 016 PASS conditions all hold, unless overridden (a missing key counts as not met)."""
    nets = [Decimal(v) for v in nets]
    summary = {"trades": len(nets), "e": sum(nets) / len(nets), "lower_bound": report.lower_bound(nets),
               "day_lower_bound": 1.0, "top_removed_e": Decimal("1"), "excess_mean": 0.01, "excess_lower_bound": 0.005,
               "excess_day_lower_bound": 0.004}
    summary.update(overrides)
    return summary


TRADES = [("BTCUSDT", "100", "101.3"), ("ETHUSDT", "50", "48.77"), ("SOLUSDT", "20", "20.91")]


def run(monkeypatch, capsys, root, *args):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(root))
    code = report.main(["--start", START, *args])
    return code, capsys.readouterr().out


def test_net_is_gross_minus_recorded_entry_fee_minus_the_booked_exit_fee():
    # 10 - 1 - 0.001 * (1000 + 10)
    assert report.net_pnl(record()) == Decimal("7.99")
    # the recorded entry fee is used, not an estimate: 2 more recorded fee is exactly 2 less net
    assert report.net_pnl(record(fees="3")) == Decimal("5.99")
    # a loss: -50 - 1 - 0.001 * 950
    assert report.net_pnl(record(gross="-50")) == Decimal("-51.95")
    # the exit fee is rounded up to the paper fee quantum, as booked: 0.001 * 1000.000000001 -> 1.00000001
    assert report.exit_fee(record(gross="0.000000001")) == Decimal("1.00000001")
    # a gross loss beyond the cost cannot come from a real fill; the exit fee is then floored at zero, never negative
    assert report.net_pnl(record(gross="-1200")) == Decimal("-1201")


def test_on_an_archive_atlas_wrote_the_net_equals_the_accounts_own_realized_net(tmp_path):
    root = trade_through_the_foundation(tmp_path / "state", TRADES)
    archive = report.load_archive(root / ARCHIVE)
    assert [r["symbol"] for r in archive] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    state = json.loads((root / STATE).read_text(encoding="utf-8"))
    # full closes only: the archive's net is exactly the account's realized gross P&L minus all booked fees
    assert sum(report.net_pnl(r) for r in archive) == Decimal(state["realized_gross_pnl"]) - Decimal(state["fees"])
    assert report.archive_gross(archive) == Decimal(state["realized_gross_pnl"])


def test_a_tolerated_retry_line_is_read_as_atlas_reads_it(tmp_path):
    root = write_state(tmp_path / "state", [record(1), record(2)])
    ClosedPositionArchiveStore(root / ARCHIVE).append(1, record(2))      # identical retry of the last append
    assert [r["position_id"] for r in report.load_archive(root / ARCHIVE)] == ["LONG:BTCUSDT:r1", "LONG:BTCUSDT:r2"]


def test_window_counts_opened_at_or_after_start_and_closed_before_end():
    start, end = report.parse_utc(START), report.parse_utc("2026-10-20T00:00:00Z")
    rows = [record(1, opened="2026-10-17T23:59:59+00:00"),                                   # opened before start
            record(2, opened=START),                                                          # at start: counts
            record(3, closed="2026-10-19T23:59:59+00:00"),                                    # just before end
            record(4, closed="2026-10-20T00:00:00+00:00"),                                    # at end: excluded
            record(5, opened="2026-10-18T02:00:00+03:00")]                                    # 2026-10-17T23:00Z
    kept, before, after = report.in_window(rows, start, end)
    assert [r["position_id"] for r in kept] == ["LONG:BTCUSDT:r2", "LONG:BTCUSDT:r3"]
    assert (before, after) == (2, 1)
    kept, _, after = report.in_window(rows, start, None)
    assert len(kept) == 3 and after == 0


@pytest.mark.parametrize("nets, verdict", [
    (["5"] * 29, "INSUFFICIENT"),
    (["-1"] * 30, "FAIL"),
    (["0"] * 120, "FAIL"),                                                  # E == 0 is not an edge
    (["5"] * 99, "INCONCLUSIVE (E > 0, 99 < 100"),                          # positive, tight, below target
    (["5"] * 100, "PASS"),
    (["100", "-99"] * 60, "INCONCLUSIVE (E > 0, lower bound <= 0)"),        # E = 0.5, but noise covers zero
    (["5"] + ["0"] * 99, "INCONCLUSIVE (E > 0, lower bound <= 0)"),         # E = 0.05, lower bound exactly 0
])
def test_verdict_follows_the_pre_registered_sheet(nets, verdict):
    assert report.verdict(summary_of(nets)).startswith(verdict)


@pytest.mark.parametrize("nets, verdict", [
    (["5"] * 100, "INCONCLUSIVE (PASS conditions on E hold, but the archive"),   # only a PASS is lowered
    (["-1"] * 100, "FAIL"),
    (["5"] * 99, "INCONCLUSIVE (E > 0, 99 < 100"),
    (["5"] * 10, "INSUFFICIENT"),
])
def test_an_incomplete_archive_can_only_lower_a_pass(nets, verdict):
    assert report.verdict(summary_of(nets), archive_complete=False).startswith(verdict)


def test_the_pre_registered_numbers_are_fixed():
    assert (report.TARGET_TRADES, report.MIN_TRADES_FOR_A_VERDICT) == (100, 30)
    assert (report.RESAMPLES, report.LOWER_QUANTILE, report.SEED) == (10_000, 0.05, 20261017)
    assert report.PAPER_FEE_RATE_PER_SIDE == Decimal("0.001")


def test_lower_bound_is_seeded_reproducible_and_below_the_mean():
    nets = [Decimal(v) for v in ("12", "-7", "3", "25", "-15", "4", "-2", "9", "1", "-6")]
    first = report.lower_bound(nets)
    assert first == report.lower_bound(nets)
    assert first < float(sum(nets) / len(nets))
    assert report.lower_bound([Decimal("2.5")] * 40) == 2.5
    assert report.lower_bound([]) is None


def test_lower_bound_takes_the_lower_five_percent_quantile_of_the_resampled_means():
    # 1 resample in 20 is the 5 % quantile: index ceil(0.05 * 20) - 1 = 0, the smallest of the seeded means
    nets = [Decimal(v) for v in ("1", "2", "3", "4", "5", "6", "7", "8")]
    rng = random.Random(report.SEED)
    means = sorted(math.fsum(float(nets[int(rng.random() * 8)]) for _ in range(8)) / 8 for _ in range(20))
    assert report.lower_bound(nets, resamples=20) == means[0]


def test_corrupt_conflicting_or_undecodable_archive_is_refused(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", [record(1), record(2)])
    ClosedPositionArchiveStore(root / ARCHIVE).append(2, record(1, gross="11"))    # same position, other figures
    code, out = run(monkeypatch, capsys, root)
    assert code == 2 and "REFUSED" in out and "verdict" not in out

    root = write_state(tmp_path / "state2", [record(1)])
    with (root / ARCHIVE).open("a", encoding="utf-8") as handle:
        handle.write('{"sequence": 1, "position_id": "LONG:BTCUSDT:r2"}\n')        # a field missing
    code, out = run(monkeypatch, capsys, root)
    assert code == 2 and "line 2" in out and "verdict" not in out

    root = write_state(tmp_path / "state3", [record(1)])
    with (root / ARCHIVE).open("ab") as handle:
        handle.write(b"\xff\xfe not utf-8\n")
    code, out = run(monkeypatch, capsys, root)
    assert code == 2 and "REFUSED" in out

    root = tmp_path / "state4"
    root.mkdir()
    (root / ARCHIVE).write_text(json.dumps(record(1)) + "\n", encoding="utf-8")   # no sequence: not Atlas's format
    assert run(monkeypatch, capsys, root)[0] == 2


@pytest.mark.parametrize("state", ["{}", "not json", '{"positions": {"BTCUSDT": "x"}, "realized_gross_pnl": "0"}',
                                   '{"positions": {}, "realized_gross_pnl": "NaN"}'])
def test_unreadable_financial_state_is_refused(tmp_path, monkeypatch, capsys, state):
    root = write_state(tmp_path / "state", [record(1)])
    (root / STATE).write_text(state, encoding="utf-8")
    code, out = run(monkeypatch, capsys, root)
    assert code == 2 and "REFUSED" in out and "verdict" not in out


def test_an_unusable_state_directory_is_refused(tmp_path, monkeypatch, capsys):
    code, out = run(monkeypatch, capsys, tmp_path / "missing")
    assert code == 2 and "REFUSED" in out


def test_report_end_to_end_lists_open_positions_and_never_writes(tmp_path, monkeypatch, capsys):
    rows = [record(i, gross="10") for i in range(30)] + [record(99, opened="2026-10-01T00:00:00+00:00")]
    open_position = {"ETHUSDT": {"position_id": "LONG:ETHUSDT:r7", "opened_at": "2026-10-19T00:00:00+00:00"}}
    root = write_state(tmp_path / "state", rows, positions=open_position)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()}
    code, out = run(monkeypatch, capsys, root)
    assert code == 0
    assert f"state root: {root.resolve()}" in out
    assert "in window 30; opened before start 1" in out
    assert "open positions (excluded): 1" in out and "LONG:ETHUSDT:r7" in out
    assert "E (net per trade): 7.9900  E%: 0.7990 %" in out
    assert "verdict (interim; final only at the end of run with --end): INCONCLUSIVE (E > 0, 30 < 100" in out
    assert "WARNING" not in out
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.iterdir()} == before


def test_a_partial_sale_written_by_atlas_is_flagged(tmp_path, monkeypatch, capsys):
    root = trade_through_the_foundation(tmp_path / "state", TRADES, partial_first=True)
    code, out = run(monkeypatch, capsys, root, "--end", "2026-11-08T00:00:00Z")
    assert code == 0 and "WARNING: archive gross P&L" in out and "partial sales" in out
    assert "verdict: INSUFFICIENT" in out


def test_an_archive_gross_above_the_accounts_is_flagged_too(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", [record(i) for i in range(100)], realized="999")
    code, out = run(monkeypatch, capsys, root)
    assert code == 0 and "WARNING: archive gross P&L 1000 differs" in out
    assert "INCONCLUSIVE (PASS conditions on E hold, but the archive does not account" in out


def test_without_a_financial_state_the_archive_is_unchecked_and_cannot_pass(tmp_path, monkeypatch, capsys):
    root = write_state(tmp_path / "state", [record(i) for i in range(100)])
    (root / STATE).unlink()
    code, out = run(monkeypatch, capsys, root)
    assert code == 0 and "open positions UNKNOWN" in out
    assert "INCONCLUSIVE (PASS conditions on E hold, but the archive does not account" in out


def test_empty_state_is_insufficient_not_an_error(tmp_path, monkeypatch, capsys):
    root = tmp_path / "empty"
    root.mkdir()
    code, out = run(monkeypatch, capsys, root)
    assert code == 0 and "INSUFFICIENT (0 < 30" in out


@pytest.mark.parametrize("args", [["--start", "2026-10-18T00:00:00"],                       # no timezone
                                  ["--start", START, "--end", START],                       # end not after start
                                  ["--start", "day zero"]])
def test_bad_window_arguments_are_refused(tmp_path, monkeypatch, args):
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    with pytest.raises(SystemExit) as raised:
        report.main(args)
    assert raised.value.code == 2
