"""Book extras (freqtrade-style report views, ideas only): honest with small samples, nothing inferred."""

from decimal import Decimal

from observability.learning_view import MIN_PROVISIONAL, build


def row(i, sym, gross, opened="2026-10-01T10:00:00+00:00", closed="2026-10-01T10:30:00+00:00"):
    return {"position_id": f"p{i}", "symbol": sym, "cost_quote": "1000", "gross_pnl": gross,
            "opened_at": opened, "closed_at": closed}


def test_small_book_has_tables_but_no_sqn():
    out = build([row(1, "BTCUSDT", "5"), row(2, "ETHUSDT", "-5", closed="2026-10-02T09:00:00+00:00")], [])["book_extras"]
    assert [c["symbol"] for c in out["per_coin"]] == ["BTCUSDT", "ETHUSDT"]
    assert [d["day_utc"] for d in out["daily_realised"]] == ["2026-10-01", "2026-10-02"]
    assert out["sqn"] is None and out["per_exit_reason"].startswith("N/A")
    assert out["avg_minutes_winners"] == 30.0


def test_sqn_appears_only_with_enough_trades():
    rows = [row(i, "BTCUSDT", "5" if i % 3 else "-3") for i in range(MIN_PROVISIONAL)]
    out = build(rows, [])["book_extras"]
    assert out["sqn"] is not None and out["longest_winning_streak"] >= 1


def test_empty_book():
    out = build([], [])["book_extras"]
    assert out["per_coin"] == [] and out["daily_realised"] == [] and out["sqn"] is None


def test_cooldown_evidence_counts_reentries_after_a_loss_on_the_same_coin():
    rows = [row(1, "BTCUSDT", "-5", "2026-10-01T10:00:00+00:00", "2026-10-01T10:30:00+00:00"),
            row(2, "BTCUSDT", "-2", "2026-10-01T10:45:00+00:00", "2026-10-01T11:00:00+00:00"),  # 15 min after a loss
            row(3, "ETHUSDT", "4", "2026-10-01T10:40:00+00:00", "2026-10-01T11:10:00+00:00"),   # other coin
            row(4, "BTCUSDT", "3", "2026-10-01T14:00:00+00:00", "2026-10-01T14:30:00+00:00")]   # long after
    ev = build(rows, [])["book_extras"]["cooldown_evidence"]
    assert ev["trades"] == 1 and Decimal(ev["net"]) < 0 and ev["verdict"] == "INSUFFICIENT"


def test_loss_streak_evidence_counts_trades_after_three_losses():
    grosses = ["-5", "-5", "-5", "3", "-2", "-2", "-2", "-2", "4"]
    rows = [row(i, "BTCUSDT", g, f"2026-10-01T{10 + i:02d}:00:00+00:00", f"2026-10-01T{10 + i:02d}:30:00+00:00")
            for i, g in enumerate(grosses)]
    ev = build(rows, [])["book_extras"]["loss_streak_evidence"]
    # after the 3rd loss: "3"; after -2,-2,-2: "-2" and "4" (streak still >= 3 before each)
    assert ev["trades"] == 3 and ev["verdict"] == "INSUFFICIENT"
