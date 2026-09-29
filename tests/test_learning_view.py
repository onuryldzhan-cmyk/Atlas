"""Learning view: real experiences only, status by sample size, no look-ahead, contradictions kept."""

import json

from observability import learning_view as L


def trade(i, symbol="BTCUSDT", gross="5", opened="2026-09-29T10:00:00+00:00"):
    return {"position_id": f"p{i}", "symbol": symbol, "cost_quote": "1000", "gross_pnl": gross,
            "opened_at": opened, "closed_at": f"2026-09-29T{10 + i // 60:02d}:{i % 60:02d}:00+00:00"}


def regime_record(at, regime):
    return {"author": "market_regime", "created_at": at,
            "body": json.dumps({"coins": {"BTCUSDT": {"regime": regime}}})}


def test_no_trades_means_no_experience_and_no_lesson():
    out = L.build([], [])
    assert out["experience_count"] == 0 and out["lessons"] == []


def test_status_is_earned_by_sample_size_never_by_outcome():
    few = L.build([trade(i, gross="50") for i in range(3)], [])
    assert {x["status"] for x in few["lessons"]} == {"CANDIDATE"}
    many = L.build([trade(i, gross="50") for i in range(12)], [])
    assert {x["status"] for x in many["lessons"]} == {"PROVISIONAL"}


def test_regime_uses_only_records_written_before_the_trade_opened():
    mem = [regime_record("2026-09-29T09:00:00+00:00", "TREND_UP"), regime_record("2026-09-29T11:00:00+00:00", "PANIC")]
    exp = L.experiences([trade(1)], mem)[0]
    assert exp["regime"] == "TREND_UP" and exp["environment"] == "PAPER"
    assert L.experiences([trade(1, opened="2026-09-29T08:00:00+00:00")], mem)[0]["regime"] == "UNKNOWN"


def test_contradiction_is_kept_not_deleted_and_duplicates_count_once():
    rows = [trade(i, gross="20") for i in range(6)] + [trade(i, gross="-30") for i in range(6, 12)]
    out = L.build(rows + rows[:2], [])
    coin = next(x for x in out["lessons"] if x["id"] == "L-COIN-BTCUSDT")
    assert coin["status"] == "CONTESTED" and coin["sample_size"] == 12 and coin["halves"]
    assert out["contradictions"]


def test_validated_needs_an_owner_signed_record():
    rows = [trade(i, gross="-30") for i in range(12)]
    fake = {"authority": "AUTHORITATIVE", "owner_verified": False, "related_decision": "L-COIN-BTCUSDT"}
    assert next(x for x in L.build(rows, [fake])["lessons"] if x["id"] == "L-COIN-BTCUSDT")["status"] == "PROVISIONAL"
    real = {**fake, "owner_verified": True}
    assert next(x for x in L.build(rows, [real])["lessons"] if x["id"] == "L-COIN-BTCUSDT")["status"] == "VALIDATED"
