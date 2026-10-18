"""Task 017 (registry v5.101): experience ledger, settlement, calibration and the CLI workflow.

Migration-safety items (CLAUDE.md): idempotency, duplicates, ordering/sequence, partial state (torn tail), conflicts,
tamper detection and halt, and no rewrite of a prediction by its outcome. Look-ahead: settlement ignores every bar
outside its own horizon.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from core.market_cycle import INTERVAL_MS

from tests._task017_support import CUTOFF, inputs, klines, rows
from tools import ai_gateway
from tools.unified_analysis import __main__ as cli
from tools.unified_analysis.contracts import Classification
from tools.unified_analysis.experience import (
    ROUND_TRIP_COST,
    ExperienceConflict,
    ExperienceLedger,
    ExperienceLedgerError,
    Pending,
    calibration,
    evaluate,
    wilson_lower,
)
from tools.unified_analysis.pipeline import run_analysis

H = INTERVAL_MS["1h"]


def future_rows(start_close: float, n: int, drift: float, start_ms: int = CUTOFF) -> list[list]:
    out, price = [], start_close
    for i in range(n):
        o = start_ms + i * H
        c = price * (1 + drift)
        out.append([o, price, max(price, c), min(price, c), c, 1.0, o + H - 1, 1.0])
        price = c
    return out


@pytest.fixture
def ledger(tmp_path):
    return ExperienceLedger(tmp_path / "experience.jsonl")


@pytest.fixture
def bull_report():
    report = run_analysis(inputs(0.002))
    assert report.classification is Classification.BULLISH_SETUP
    return report


# ---------------------------------------------------------------- ledger integrity


def test_prediction_is_recorded_before_any_outcome_and_idempotent(ledger, bull_report):
    first = ledger.record_prediction(bull_report)
    again = ledger.record_prediction(bull_report)
    assert first == again and len(ledger.records()) == 1
    assert first["report"]["classification"] == "BULLISH_SETUP" and first["prev_hash"] == "0" * 64
    assert ledger.outcomes() == {}


def test_a_different_report_for_the_same_id_is_refused(ledger, bull_report):
    ledger.record_prediction(bull_report)
    with pytest.raises(ExperienceConflict):
        ledger.record_prediction(replace(bull_report, confidence=Decimal("0.49")))
    assert len(ledger.records()) == 1


def test_pipeline_records_through_the_ledger(ledger):
    report = run_analysis(inputs(0.002), ledger=ledger)
    assert report.analysis_id in ledger.predictions()
    # review F7: a data outage is not an analysis and is not recorded, so a healthy re-run is not refused
    unusable = run_analysis(inputs(k={"1h": None, "4h": None, "1d": None}, symbol="ETHUSDT"), ledger=ledger)
    assert unusable.analysis_id not in ledger.predictions() and unusable.metrics["recorded"] is False


def test_tampered_ledger_halts(ledger, bull_report):
    ledger.record_prediction(bull_report)
    lines = ledger.path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["confidence"] = "0.99"
    ledger.path.write_text("\n".join([lines[0], json.dumps(rec)]) + "\n")
    with pytest.raises(ExperienceLedgerError, match="altered"):
        ledger.records()


def test_reordered_or_chain_broken_ledger_halts(ledger, bull_report):
    ledger.record_prediction(bull_report)
    other = run_analysis(inputs(-0.002, symbol="ETHUSDT"))
    ledger.record_prediction(other)
    lines = ledger.path.read_text().splitlines()
    second = json.loads(lines[2])
    second["prev_hash"] = "f" * 64
    ledger.path.write_text("\n".join([lines[0], lines[1], json.dumps(second)]) + "\n")
    with pytest.raises(ExperienceLedgerError):
        ledger.records()


def test_torn_tail_halts_and_nothing_is_appended(ledger, bull_report):
    ledger.record_prediction(bull_report)
    raw = ledger.path.read_bytes()
    ledger.path.write_bytes(raw[:-20])
    with pytest.raises(ExperienceLedgerError):
        ledger.records()
    with pytest.raises(ExperienceLedgerError):
        ledger.record_prediction(run_analysis(inputs(-0.002, symbol="ETHUSDT")))
    assert ledger.path.read_bytes() == raw[:-20]


def test_cli_exits_3_on_a_corrupt_ledger(tmp_path):
    (tmp_path / "experience.jsonl").write_text('{"log":"wrong","version":1}\n')
    assert cli.main(["--state-dir", str(tmp_path), "calibration"]) == 3


# ---------------------------------------------------------------- settlement


def _pred(ledger, report):
    return ledger.record_prediction(report)


def test_settlement_waits_for_the_whole_horizon(ledger, bull_report):
    pred = _pred(ledger, bull_report)
    bars = future_rows(bull_report.reference_close, 24, 0.001)
    assert isinstance(evaluate(pred, bars, now_ms=CUTOFF + 23 * H), Pending)
    assert isinstance(evaluate(pred, bars[:-1], now_ms=CUTOFF + 48 * H), Pending)   # a missing bar
    gapped = bars[:10] + bars[11:]
    assert isinstance(evaluate(pred, gapped, now_ms=CUTOFF + 48 * H), Pending)


def test_settlement_reads_only_bars_inside_its_own_horizon(ledger, bull_report):
    pred = _pred(ledger, bull_report)
    bars = future_rows(bull_report.reference_close, 24, 0.001)
    out = evaluate(pred, bars, now_ms=CUTOFF + 30 * H)
    before = rows("1h", 50, CUTOFF, drift=-0.05)                         # wild bars before the cutoff
    after = future_rows(1.0, 24, -0.5, start_ms=CUTOFF + 24 * H)         # and after the horizon
    assert evaluate(pred, before + bars + after, now_ms=CUTOFF + 30 * H) == out
    assert out["first_bar_open_ms"] == CUTOFF and out["bars"] == 24
    assert out["hit"] is True and out["return"] == pytest.approx(1.001 ** 24 - 1, rel=1e-6)


def test_a_direction_inside_costs_is_not_a_hit_and_invalidation_is_tracked(ledger, bull_report):
    pred = _pred(ledger, bull_report)
    tiny = evaluate(pred, future_rows(bull_report.reference_close, 24, 0.00005), now_ms=CUTOFF + 24 * H)
    assert 0 < tiny["signed_return"] < ROUND_TRIP_COST and tiny["hit"] is False
    threshold = pred["invalidation"][0]["threshold"]
    crash = future_rows(bull_report.reference_close, 24, -0.01)
    out = evaluate(pred, crash, now_ms=CUTOFF + 24 * H)
    assert out["hit"] is False and out["invalidated_at_ms"] is not None
    first_below = next(r for r in crash if r[4] < threshold)
    assert out["invalidated_at_ms"] == first_below[6]
    assert out["brier_on_bound"] == pytest.approx(float(pred["confidence"]) ** 2)


def test_benchmark_excess_return(ledger, bull_report):
    pred = _pred(ledger, bull_report)
    bars = future_rows(bull_report.reference_close, 24, 0.001)
    bench = future_rows(50.0, 25, 0.0005, start_ms=CUTOFF - H)
    out = evaluate(pred, bars, now_ms=CUTOFF + 24 * H, benchmark_rows=bench)
    assert out["excess_return"] == pytest.approx(out["return"] - out["benchmark_return"])


def test_outcome_rules_unknown_duplicate_early_and_short(ledger, bull_report):
    pred = _pred(ledger, bull_report)
    out = evaluate(pred, future_rows(bull_report.reference_close, 24, 0.001), now_ms=CUTOFF + 24 * H)
    with pytest.raises(ExperienceLedgerError):
        ledger.record_outcome("UA-NOPE", out)
    with pytest.raises(ExperienceLedgerError, match="before the cutoff"):
        ledger.record_outcome(pred["analysis_id"], {**out, "first_bar_open_ms": CUTOFF - H})
    with pytest.raises(ExperienceLedgerError, match="whole horizon"):
        ledger.record_outcome(pred["analysis_id"], {**out, "through_ms": CUTOFF + H})
    rec = ledger.record_outcome(pred["analysis_id"], out)
    assert rec["prediction_hash"] == pred["hash"]
    with pytest.raises(ExperienceConflict):
        ledger.record_outcome(pred["analysis_id"], out)
    assert ledger.predictions()[pred["analysis_id"]] == pred      # the prediction is untouched by its outcome


# ---------------------------------------------------------------- calibration


def _fake_records(n, hit_fn, horizon_h=24, every_h=24, cls="BULLISH_SETUP", roster="live"):
    recs = []
    for i in range(n):
        aid = f"UA-X-{i}"
        recs.append({"record_type": "PREDICTION", "analysis_id": aid, "symbol": "BTCUSDT",
                     "cutoff_ms": i * every_h * H, "horizon_ms": horizon_h * H, "classification": cls,
                     "report": {"confidence_basis": {"roster": roster}}})
        recs.append({"record_type": "OUTCOME", "analysis_id": aid, "hit": hit_fn(i), "brier_on_bound": 0.2,
                     "through_ms": (i * every_h + horizon_h) * H})
    return recs


def test_calibration_requires_samples_in_both_halves():
    good = calibration(_fake_records(40, lambda i: i % 3 != 0))
    assert good["live:BULLISH_SETUP"]["measured"] is True
    assert good["live:BULLISH_SETUP"]["wilson_lower"] == pytest.approx(wilson_lower(26, 40), abs=1e-4)
    few = calibration(_fake_records(20, lambda i: True))
    assert few["live:BULLISH_SETUP"]["measured"] is False
    decayed = calibration(_fake_records(40, lambda i: i < 20))           # skill only in the older half
    assert decayed["live:BULLISH_SETUP"]["measured"] is False


def test_overlapping_predictions_are_not_counted_twice():
    overlapping = calibration(_fake_records(40, lambda i: True, horizon_h=24, every_h=1))
    assert overlapping["live:BULLISH_SETUP"]["n"] == 2


def test_rosters_are_never_pooled():
    cal = calibration(_fake_records(40, lambda i: True, roster="hist"))
    assert set(cal) == {"hist:BULLISH_SETUP"}


def test_wilson_lower_bound():
    assert wilson_lower(0, 0) == 0.0
    assert 0 < wilson_lower(30, 40) < 0.75


# ---------------------------------------------------------------- CLI over a market archive


def _archive(path: Path, symbol_rows: dict[str, dict[str, list]]) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE market_data_bars (symbol TEXT, timeframe TEXT, open_time_ms INTEGER, open REAL, high REAL,"
                " low REAL, close REAL, volume REAL, close_time_ms INTEGER, quote_volume REAL)")
    for symbol, by_tf in symbol_rows.items():
        for tf, rs in by_tf.items():
            con.executemany("INSERT INTO market_data_bars VALUES (?,?,?,?,?,?,?,?,?,?)",
                            [(symbol, tf, r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in rs])
    con.commit()
    con.close()
    return path


def test_cli_replay_records_settles_and_calibrates_from_the_archive(tmp_path, capsys):
    end = CUTOFF + 40 * H                                              # ends inside the last horizon
    data = {"1h": rows("1h", 800, end, 0.001), "4h": rows("4h", 300, end, 0.002), "1d": rows("1d", 220, end, 0.004)}
    db = _archive(tmp_path / "market_data.sqlite3", {"BTCUSDT": data})
    state = tmp_path / "state"
    start = datetime.fromtimestamp((CUTOFF - 48 * H) / 1000, UTC).isoformat()
    stop = datetime.fromtimestamp((CUTOFF + 24 * H) / 1000, UTC).isoformat()
    assert cli.main(["--state-dir", str(state), "replay", "--symbol", "BTCUSDT", "--archive", str(db),
                     "--start", start, "--end", stop, "--every", "24"]) == 0
    led = ExperienceLedger(state / "experience.jsonl")
    preds, outs = led.predictions(), led.outcomes()
    assert len(preds) == 4 and len(outs) == 3                         # the newest horizon is beyond the archive
    for aid, out in outs.items():
        assert out["first_bar_open_ms"] == preds[aid]["cutoff_ms"]
        assert preds[aid]["report"]["confidence_basis"]["roster"] == "hist"
    # a second replay over the same window changes nothing (idempotent)
    before = led.path.read_bytes()
    assert cli.main(["--state-dir", str(state), "replay", "--symbol", "BTCUSDT", "--archive", str(db),
                     "--start", start, "--end", stop, "--every", "24"]) == 0
    assert led.path.read_bytes() == before
    assert cli.main(["--state-dir", str(state), "calibration"]) == 0
    assert "hist:" in capsys.readouterr().out
    assert not (db.parent / (db.name + "-wal")).exists() and not (db.parent / (db.name + "-shm")).exists()


def test_cli_replay_refuses_overlapping_windows(tmp_path):
    assert cli.main(["--state-dir", str(tmp_path), "replay", "--symbol", "BTCUSDT", "--archive", "x",
                     "--start", "2026-01-01T00:00:00Z", "--end", "2026-01-02T00:00:00Z", "--every", "1"]) == 2


def test_cli_archive_analyze_without_archive_is_insufficient(tmp_path, capsys):
    assert cli.main(["--state-dir", str(tmp_path), "analyze", "--symbol", "BTCUSDT", "--source", "archive",
                     "--archive", str(tmp_path / "missing.sqlite3"), "--cutoff", "2026-01-01T00:00:00Z"]) == 0
    assert "INSUFFICIENT_EVIDENCE" in capsys.readouterr().out


def test_gateway_lists_the_package_agent_and_refuses_others():
    assert cli.GATEWAY_AGENT in ai_gateway.AI_AGENTS
    refused = ai_gateway.ask("s", "p", {"type": "object"}, ledger=ai_gateway.UsageLedger(Path("/nonexistent/x.json")),
                             agent="narrative", backend="api", client_factory=lambda: None)
    assert refused.status == "ABSTAIN" and "AGENT_NOT_ALLOWED" in refused.reason


def test_rerunning_the_identical_analysis_is_a_no_op(ledger):
    run_analysis(inputs(0.002), ledger=ledger)
    before = ledger.path.read_bytes()
    run_analysis(inputs(0.002), ledger=ledger)        # different timings, same analysis
    assert ledger.path.read_bytes() == before
