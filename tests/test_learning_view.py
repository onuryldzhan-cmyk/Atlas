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
    assert {x["status"] for x in few["lessons"]} == {"PROPOSED"}
    many = L.build([trade(i, gross="50") for i in range(12)], [])
    assert {x["status"] for x in many["lessons"]} == {"VALIDATING"}


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
    assert next(x for x in L.build(rows, [fake])["lessons"] if x["id"] == "L-COIN-BTCUSDT")["status"] == "VALIDATING"
    real = {**fake, "owner_verified": True}
    assert next(x for x in L.build(rows, [real])["lessons"] if x["id"] == "L-COIN-BTCUSDT")["status"] == "CONFIRMED"


def test_metrics_and_post_trade_are_measured_not_invented():
    rows = [trade(i, gross=g) for i, g in enumerate(["20", "-10", "1.5", "-30", "40"])]
    out = L.build(rows, [])
    m = out["book_metrics"]
    assert m["trades"] == 5 and m["verdict"] == "INSUFFICIENT" and m["longest_losing_streak"] == 3  # -10, then 1.5 gross is a loss after fees, then -30
    third = out["experiences"][2]["analysis"]
    assert third["direction_right"] is True and third["fees_turned_win_into_loss"] is True
    assert "slippage (PAPER fill model)" in third["not_measured"]


def test_fingerprint_changes_when_an_outcome_is_edited():
    row = trade(1)
    assert L.fingerprint(row) == L.fingerprint(dict(row))
    assert L.fingerprint(row) != L.fingerprint({**row, "gross_pnl": "6"})


def test_stale_lesson_expires_but_is_kept():
    old = [trade(i, symbol="OLDUSDT", gross="5") for i in range(3)]
    for r in old:
        r["closed_at"] = "2026-07-01T10:00:00+00:00"
    out = L.build(old + [trade(99)], [])
    assert next(x for x in out["lessons"] if x["id"] == "L-COIN-OLDUSDT")["status"] == "EXPIRED"


def test_counterfactual_is_labelled_and_book_decay_detected():
    rows = [trade(i, gross="20") for i in range(6)] + [trade(i, gross="-30") for i in range(6, 12)]
    out = L.build(rows, [])
    cf = out["experiences"][0]["analysis"]["counterfactual"]
    assert cf["label"].startswith("COUNTERFACTUAL") and cf["no_trade_net"] == "0"
    book = next(x for x in out["lessons"] if x["id"] == "L-BOOK-ALL")
    assert book["status"] == "CONTESTED"  # the strategy got worse: decay is visible, nothing is deleted
