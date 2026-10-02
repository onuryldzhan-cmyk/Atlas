"""Performance report (registry v5.47): lessons only with evidence, never from small samples."""

from __future__ import annotations

from tools import performance_report as pr


def _trade(symbol, gross, minutes, hour=10, cost="100"):
    return {"symbol": symbol, "gross_pnl": str(gross), "cost_quote": cost, "entry_fees": "0.1",
            "opened_at": f"2026-09-20T{hour:02d}:00:00+00:00",
            "closed_at": f"2026-09-20T{hour + minutes // 60:02d}:{minutes % 60:02d}:00+00:00"}


def test_small_samples_never_produce_a_lesson():
    report = pr.analyse([_trade("BTCUSDT", -1, 5) for _ in range(5)])
    assert all("INCONCLUSIVE" in s["verdict"] for t in report["by"].values() for s in t.values())
    assert not any("WEAK" in lesson for lesson in report["lessons"])


def test_consistent_losers_are_flagged_weak_and_winners_strong():
    losers = [_trade("DOGEUSDT", -0.5, 5) for _ in range(20)]
    winners = [_trade("BTCUSDT", 3, 120) for _ in range(20)]
    report = pr.analyse(losers + winners)
    assert report["by"]["coin"]["DOGEUSDT"]["verdict"] == "WEAK"
    assert report["by"]["coin"]["BTCUSDT"]["verdict"] == "STRONG"
    assert report["by"]["holding_time"]["<15 dk"]["verdict"] == "WEAK"
    assert any("DOGEUSDT" in lesson for lesson in report["lessons"])


def test_fee_share_lesson_when_fees_dominate():
    report = pr.analyse([_trade("ETHUSDT", 0.05, 3) for _ in range(12)])
    assert any("ücretler" in lesson for lesson in report["lessons"])


def test_reads_a_real_archive(tmp_path):
    import json

    path = tmp_path / "closed.jsonl"
    path.write_text("".join(json.dumps({"sequence": i, **_trade("BTCUSDT", 1, 30)}) + "\n" for i in range(3)))
    assert pr.main(["--archive", str(path), "--json"]) == 0


def test_lucky_groups_lose_their_verdict_under_the_false_discovery_filter():
    """2026-10-02: 24 coins of coin-flip trades: per-group 95 % intervals call a few WEAK/STRONG by luck."""
    import random

    rng = random.Random(5)
    trades = [_trade(f"C{c:02d}USDT", rng.choice([2, -2]), 30) for c in range(24) for _ in range(24)]
    filter_ = pr._false_discovery_filter
    try:
        pr._false_discovery_filter = lambda tables: None
        unfiltered = [s["verdict"] for s in pr.analyse(trades)["by"]["coin"].values()]
    finally:
        pr._false_discovery_filter = filter_
    assert sum(v in ("WEAK", "STRONG") for v in unfiltered) >= 1  # luck alone produced a "lesson" (C06, C07)
    report = pr.analyse(trades)
    verdicts = [s["verdict"] for s in report["by"]["coin"].values()]
    assert not any(v in ("WEAK", "STRONG") for v in verdicts), verdicts
    assert all("q_fdr" in s for s in report["by"]["coin"].values())


def test_strong_signal_keeps_its_verdict_and_reports_q():
    losers = [_trade("DOGEUSDT", -0.5, 5) for _ in range(20)]
    report = pr.analyse(losers + [_trade("BTCUSDT", 3, 120) for _ in range(20)])
    assert report["by"]["coin"]["DOGEUSDT"]["verdict"] == "WEAK" and report["by"]["coin"]["DOGEUSDT"]["q_fdr"] < 0.001
