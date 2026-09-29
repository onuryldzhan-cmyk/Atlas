"""Strategy agent: evidence-backed proposals from Atlas's own trades, never an action."""

from __future__ import annotations

from atlas_org import proposals as P
from tools import atlas_org_cli as cli
from tools import strategy_agent as sa
from tools.performance_report import analyse


def closed(symbol, gross, cost="1000", minutes=30):
    return {"symbol": symbol, "cost_quote": cost, "gross_pnl": gross,
            "opened_at": "2026-09-29T10:00:00+00:00", "closed_at": f"2026-09-29T10:{minutes:02d}:00+00:00"}


def test_fee_drag_and_losing_coin_are_proposed_with_counter_evidence(tmp_path):
    report = analyse([closed("BTCUSDT", "0.5")] * 12)
    out = sa.file_proposals(report, tmp_path, apply=True)
    ids = {f["id"] for f in out["filed"]}
    assert ids == {"SA-FEE-DRAG.1", "SA-LOSING-BOOK-BTCUSDT.1"}
    state = P.replay(cli.read_log(tmp_path / cli.PROPOSALS_LOG))
    for p in state.values():
        assert p.author == "strategy_lab" and p.status not in (P.S.APPROVED, P.S.APPLIED)
        assert all(c["counter_evidence"] for c in p.fields["claims"])


def test_open_proposal_is_not_filed_twice_and_dry_run_writes_nothing(tmp_path):
    report = analyse([closed("BTCUSDT", "0.5")] * 12)
    assert sa.file_proposals(report, tmp_path, apply=False)["filed"]
    assert not (tmp_path / cli.PROPOSALS_LOG).exists()
    sa.file_proposals(report, tmp_path, apply=True)
    again = sa.file_proposals(report, tmp_path, apply=True)
    assert again["filed"] == [] and set(again["skipped_open"]) == {"FEE-DRAG", "LOSING-BOOK-BTCUSDT"}


def test_no_trades_or_healthy_book_proposes_nothing(tmp_path):
    assert sa.file_proposals(analyse([]), tmp_path)["filed"] == []
    assert sa.file_proposals(analyse([closed("BTCUSDT", "80", minutes=50)] * 12), tmp_path)["filed"] == []
