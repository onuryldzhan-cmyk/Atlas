"""Trade post-mortems (owner 2026-10-03): every closed trade, win or loss, is written to memory once, with why and
what to watch next time; an AI review builds on its previous one and must cite real records. Evidence only."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from atlas_org import memory_records
from core.execution_portfolio_foundation import mint_long_position_id
from tools import ai_gateway as ai
from tools import atlas_org_cli as cli
from tools import trade_postmortem as tp


def _rid(hour, symbol="BTCUSDT"):
    return f"{symbol}|open:{hour}|BUY"


# Phase-2 F1: each trade's position_id is minted from its opening request_id, as
# ExecutionManager does, and joined to its own approval by that identity. (Before
# F1 one 09:00 approval was attributed to every trade by nearest time.)
def _rows(grosses, symbol="BTCUSDT", start=10):
    return [{"position_id": mint_long_position_id(symbol, _rid(start + i, symbol)), "symbol": symbol, "cost_quote": "1000", "gross_pnl": g,
             "opened_at": f"2026-10-01T{start + i:02d}:00:00+00:00", "closed_at": f"2026-10-01T{start + i:02d}:30:00+00:00"}
            for i, g in enumerate(grosses)]


APPROVALS = {"BTCUSDT": [{"timestamp": f"2026-10-01T{h:02d}:00:00.010+00:00", "confidence": 66.0, "risk": "MEDIUM",
                          "experiment_id": "EXP-002", "request_id": _rid(h)} for h in range(24)]}


def _mem(d):
    return sorted(memory_records.replay(cli.read_log(d / cli.MEMORY_LOG)).values(), key=lambda r: r["seq"])


def _never(*a, **k):
    raise AssertionError("the model must not be asked")


def test_every_trade_is_written_once_with_why_and_what_next(tmp_path):
    out = tp.run(tmp_path, _rows(["5", "1", "-3"]), APPROVALS, ask=_never)
    tps = [r for r in _mem(tmp_path) if r["id"].startswith("TP-")]
    assert len(tps) == 3 and "3 işlem hafızaya yazıldı (1 kazanç, 2 kayıp)" in out["summary"]
    kinds = [json.loads(r["body"])["kind"] for r in tps]
    assert kinds == ["WIN", "LOSS_FEES", "LOSS_PRICE"]          # +5 wins; +1 is eaten by ~0.2 % fees; -3 lost on price
    fee_loss = json.loads(tps[1]["body"])
    assert "ücret" in fee_loss["reason"] and "ücretin" in fee_loss["next_time"]
    assert fee_loss["band"] == "60-70" and fee_loss["confidence"] == 66.0 and fee_loss["experiment_id"] == "EXP-002"
    assert tps[0]["type"] == "TRADING" and tps[0]["authority"] == "RESEARCH" and tps[0]["author"] == "explainable_ai"
    again = tp.run(tmp_path, _rows(["5", "1", "-3"]), APPROVALS, ask=_never)
    assert "yeni kapanan işlem yok" in again["summary"] and len([r for r in _mem(tmp_path) if r["id"].startswith("TP-")]) == 3


def test_pattern_so_far_uses_only_earlier_trades(tmp_path):
    tp.run(tmp_path, _rows(["5", "-3", "4"]), APPROVALS, ask=_never)
    bodies = [json.loads(r["body"]) for r in _mem(tmp_path) if r["id"].startswith("TP-")]
    assert bodies[0]["earlier_same"]["trades"] == 0 and "ilk işlem" in bodies[0]["pattern_so_far"]
    assert bodies[2]["earlier_same"] == {"trades": 2, "wins": 1, "net_total": bodies[2]["earlier_same"]["net_total"]}
    # the third trade's own result is not part of its history (no look-ahead)
    assert bodies[1]["earlier_same"]["trades"] == 1


def test_regime_at_entry_never_uses_a_later_record(tmp_path):
    cli.add_memory_record(tmp_path, {"record_id": "MR-0001", "type": "EXPERIMENTS", "authority": "RESEARCH",
                                     "title": "Piyasa rejimi", "author": "market_regime", "source": "t",
                                     "body": json.dumps({"coins": {"BTCUSDT": {"regime": "TREND_UP"}}})})
    tp.run(tmp_path, _rows(["5"], start=10), APPROVALS, ask=_never)   # MR-0001 was written now, after 2026-10-01
    body = json.loads(next(r for r in _mem(tmp_path) if r["id"].startswith("TP-"))["body"])
    assert body["regime_at_entry"] == "UNKNOWN"


def test_a_long_history_is_back_filled_over_several_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "MAX_PER_RUN", 2)
    monkeypatch.setattr(tp, "REVIEW_EVERY", 100)                       # this test is about the back-fill only
    first = tp.run(tmp_path, _rows(["1", "2", "3", "4", "5"]), APPROVALS, ask=_never)
    assert first["pending"] is True and "3 işlem sonraki çalışmaya kaldı" in first["summary"]
    tp.run(tmp_path, _rows(["1", "2", "3", "4", "5"]), APPROVALS, ask=_never)
    last = tp.run(tmp_path, _rows(["1", "2", "3", "4", "5"]), APPROVALS, ask=_never)
    assert last["pending"] is False and len([r for r in _mem(tmp_path) if r["id"].startswith("TP-")]) == 5


def _answer(cited, suggestions=None):
    return lambda system, prompt, schema, **k: ai.AIResult("OK", model="m", data={
        "patterns": ["ücret kayıpları"], "followups": [], "cited_records": cited,
        "suggestions": suggestions if suggestions is not None else [
            {"change": "beklenen hareket < 2x ücret ise girme", "why": "TP-0002", "test": "replay 30 gün, net > 0", "risk": "az işlem"}]})


def test_ai_review_after_enough_new_trades_cites_real_records_and_builds_on_the_previous(tmp_path):
    prompts = []

    def ask(system, prompt, schema, **k):
        prompts.append(prompt)
        return _answer(["TP-0002"])(system, prompt, schema)

    out = tp.run(tmp_path, _rows(["5", "1", "-3", "4", "-1"]), APPROVALS, ask=ask)
    reviews = [r for r in _mem(tmp_path) if r["id"].startswith("TR-")]
    assert len(reviews) == 1 and "1 öneri" in out["summary"] and "first review" in prompts[0]
    body = json.loads(reviews[0]["body"])
    assert body["suggestions"][0]["test"] and body["reviewed"][0].startswith("TP-") and reviews[0]["authority"] == "TEMPORARY"
    # five more trades, three hours later: the next review sees what the previous one suggested
    later = datetime.now(timezone.utc) + timedelta(hours=4)
    tp.run(tmp_path, _rows(["5", "1", "-3", "4", "-1"], start=16), APPROVALS, ask=ask, now=later)
    assert len(prompts) == 2 and "Your previous review TR-" in prompts[1] and "beklenen hareket" in prompts[1]


def test_ai_review_waits_for_enough_trades_and_rejects_invented_citations(tmp_path):
    waiting = tp.run(tmp_path, _rows(["5", "1"]), APPROVALS, ask=_never)              # 2 trades: not worth a call
    assert "beklemede (2 yeni işlem)" in waiting["summary"]
    out = tp.run(tmp_path, _rows(["5", "1", "2", "3", "4"]), APPROVALS, ask=_answer(["TP-0001"]))
    assert "AI incelemesi TR-" in out["summary"]
    tp.run(tmp_path, _rows(["5", "1", "2", "3", "4", "6"]), APPROVALS, ask=_never)    # 1 new, 0 h after: waits
    bad = tp.run(tmp_path, _rows(["5", "1", "2", "3", "4", "6", "7", "8", "9", "10"]), APPROVALS,
                 ask=_answer(["TP-9999"]), now=datetime.now(timezone.utc) + timedelta(hours=4))
    assert "reddedildi" in bad["summary"] and len([r for r in _mem(tmp_path) if r["id"].startswith("TR-")]) == 1


def test_ai_review_abstain_comes_back_later(tmp_path):
    out = tp.run(tmp_path, _rows(["5", "1", "2", "3", "4"]), APPROVALS,
                 ask=lambda *a, **k: ai.AIResult("ABSTAIN", reason="NO_QUOTA"))
    assert out["pending"] is True and "çekimser" in out["summary"]


def test_ceo_reads_the_trade_review_not_every_single_trade(tmp_path, monkeypatch):
    from tools import agent_cycle as ac

    monkeypatch.setattr(ac, "_research_dir", lambda: tmp_path)
    tp.run(tmp_path, _rows(["5", "1", "-3", "4", "-1"]), APPROVALS, ask=_answer(["TP-0002"]))
    cli.add_memory_record(tmp_path, {"record_id": "AP-0099", "type": "AGENTS", "authority": "RESEARCH", "title": "Çırak",
                                     "body": "{}", "author": "ai_model_research", "source": "t"})
    for n in (1, 2):                                                           # the CEO needs 3 evidence records
        cli.add_memory_record(tmp_path, {"record_id": f"PR-01{n}", "type": "EXPERIMENTS", "authority": "RESEARCH",
                                         "title": f"Performans {n}", "body": "{}", "author": "quant_research", "source": "t"})
    prompts = []
    ac.ceo_brief(tmp_path, ask=lambda system, prompt, *a, **k: prompts.append(prompt) or ai.AIResult("ABSTAIN", reason="x"))
    assert prompts and "[TR-" in prompts[0]                                    # the review is evidence
    assert "[TP-" not in prompts[0] and "[AP-" not in prompts[0]               # single trades / scorecards are not
