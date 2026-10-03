"""Phase-2 F1: deterministic trade evidence.

A position's id is minted from its opening request_id, so the entry approval,
the decision, the execution events, the close and the post-mortem are joined by
identity. Timestamp matching survives only as an explicit LEGACY fallback for
records without that chain, and only when unambiguous; anything else is
UNATTRIBUTED. Two trades close in time are never attributed to each other.
"""

from __future__ import annotations

import json

from core.execution_portfolio_foundation import mint_long_position_id
from tests.test_block5c_upstream_sizing_authority import application, execution_enabled_loop
from tools import agent_attribution as aa
from tools import decision_trace as dt
from tools import exp001_report as report
from tools import paper_position_report as ppr
from tools import trade_postmortem as tp

T0 = "2026-10-01T10:00:00.000+00:00"
T0_PLUS = "2026-10-01T10:00:00.050+00:00"


def rid(candle, symbol="BTCUSDT"):
    return f"{symbol}|{candle}|BUY"


def pid(candle, symbol="BTCUSDT"):
    return mint_long_position_id(symbol, rid(candle, symbol))


def approval(candle, ts, *, experiment=None, confidence=60.0, symbol="BTCUSDT"):
    return {"timestamp": ts, "experiment_id": experiment, "confidence": confidence, "risk": "MEDIUM",
            "request_id": rid(candle, symbol), "risk_approval_event_id": f"evt-{candle}"}


def closed(candle, opened, gross="1", symbol="BTCUSDT", position_id=None):
    return {"position_id": position_id if position_id is not None else pid(candle, symbol), "symbol": symbol,
            "cost_quote": "1000", "gross_pnl": gross, "entry_fees": "0", "opened_at": opened,
            "closed_at": "2026-10-01T11:00:00+00:00"}


# --- entry approval -------------------------------------------------------------------------------


def test_exact_id_wins_over_a_closer_approval_of_another_trade():
    """Critical criterion: the other trade's approval is nearer in time, the exact one still wins."""
    approvals = [approval("c2", T0, experiment="EXP-001", confidence=61.0),   # 0 ms from the open
                 approval("c1", "2026-10-01T09:58:00+00:00", confidence=80.0)]  # 2 min away, but it is ours
    chosen = ppr.entry_approval(approvals, T0, pid("c1"))
    assert chosen["request_id"] == rid("c1") and chosen["confidence"] == 80.0
    assert chosen["attribution"] == ppr.EXACT and chosen["risk_approval_event_id"] == "evt-c1"


def test_two_trades_in_the_same_window_each_get_their_own_approval():
    approvals = [approval("c1", T0, experiment="EXP-001"), approval("c2", T0_PLUS)]
    a1 = ppr.entry_approval(approvals, T0_PLUS, pid("c1"))
    a2 = ppr.entry_approval(approvals, T0, pid("c2"))
    assert (a1["request_id"], a1["experiment_id"]) == (rid("c1"), "EXP-001")
    assert (a2["request_id"], a2["experiment_id"]) == (rid("c2"), None)


def test_missing_link_is_unattributed_even_with_an_approval_at_the_same_instant():
    assert ppr.entry_approval([approval("c2", T0)], T0, pid("c1")) is None


def test_conflicting_duplicate_approvals_of_one_request_are_unattributed():
    a, b = approval("c1", T0, confidence=60.0), approval("c1", T0_PLUS, confidence=90.0)
    assert ppr.entry_approval([a, b], T0, pid("c1")) is None
    assert ppr.entry_approval([a, dict(a)], T0, pid("c1"))["attribution"] == ppr.EXACT


def test_legacy_record_uses_the_explicit_fallback_only_when_unambiguous():
    legacy = "long:BTCUSDT:BTCUSDT|c1|BUY"  # pre-hash identity: no canonical chain
    assert not ppr.is_canonical_position_id(legacy)
    one = ppr.entry_approval([approval("c1", T0_PLUS)], T0, legacy)
    assert one["attribution"] == ppr.LEGACY_TIMESTAMP
    assert ppr.entry_approval([approval("c1", T0_PLUS), approval("c2", T0)], T0, legacy) is None   # two: ambiguous
    assert ppr.entry_approval([approval("c1", "2026-10-01T10:05:00+00:00")], T0, legacy) is None   # outside window
    assert ppr.entry_approval([approval("c1", T0)], None, None) is None                           # no time at all
    assert ppr.entry_approval([approval("c1", T0)], "garbage", None) is None


def test_partial_chain_malformed_ids_are_never_exact():
    for bad in ("long:BTCUSDT:abc", "", None, 7, "short:BTCUSDT:" + "a" * 64):
        assert not ppr.is_canonical_position_id(bad)
        assert ppr.opened_by(bad, rid("c1")) is False
    assert ppr.opened_by(pid("c1"), None) is False and ppr.opened_by(pid("c1"), "") is False
    assert ppr.opened_by(pid("c1"), rid("c1")) is True and ppr.opened_by(pid("c1"), rid("c2")) is False


# --- experiment reporting -------------------------------------------------------------------------


def test_experiment_grouping_uses_exact_ids_not_the_nearest_approval():
    approvals = {"BTCUSDT": [approval("c1", T0, experiment="EXP-001"), approval("c2", T0_PLUS)]}
    rows = [closed("c2", T0), closed("c1", T0_PLUS), closed("c3", T0)]  # c3: its approval is missing
    groups = report.group_closed(rows, approvals)
    assert [r["position_id"] for r in groups["EXP-001"]] == [pid("c1")]
    assert [r["position_id"] for r in groups["policy floor"]] == [pid("c2")]
    assert [r["position_id"] for r in groups["unattributed"]] == [pid("c3")]


# --- post-mortem ----------------------------------------------------------------------------------


def test_postmortem_records_its_exact_chain_and_unattributed_without_one(tmp_path):
    approvals = {"BTCUSDT": [approval("c1", T0, experiment="EXP-001", confidence=66.0), approval("c2", T0_PLUS)]}
    tp.run(tmp_path, [closed("c2", T0, "5"), closed("c1", T0_PLUS, "-3"), closed("c3", T0, "2")], approvals,
           ask=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model call")))
    bodies = {b["position_id"]: b for b in (json.loads(r["body"]) for r in tp._memory(tmp_path))}
    assert bodies[pid("c1")]["request_id"] == rid("c1") and bodies[pid("c1")]["experiment_id"] == "EXP-001"
    assert bodies[pid("c1")]["risk_approval_event_id"] == "evt-c1" and bodies[pid("c1")]["attribution"] == "EXACT"
    assert bodies[pid("c2")]["request_id"] == rid("c2") and bodies[pid("c2")]["experiment_id"] is None
    assert bodies[pid("c3")]["attribution"] == "UNATTRIBUTED" and bodies[pid("c3")]["confidence"] is None


# --- agent attribution / decision trace (telemetry) ----------------------------------------------


def tele(ts, request_id, votes, symbol="BTCUSDT"):
    return json.dumps({"timestamp": ts, "symbol": symbol,
                       "decision": {"action": "BUY", "votes": votes, "request_id": request_id}})


def test_agent_votes_join_by_request_id_not_by_time():
    lines = [tele(T0, rid("c2"), {"a": "SELL"}), tele("2026-10-01T09:58:00+00:00", rid("c1"), {"a": "BUY"})]
    out = aa.attribute([closed("c1", T0, "10")], aa.decisions_by_symbol(lines))
    assert out["agents"]["a"]["supported"]["trades"] == 1 and out["agents"]["a"]["opposed"]["trades"] == 0


def test_agent_votes_missing_link_is_unattributed():
    out = aa.attribute([closed("c1", T0)], aa.decisions_by_symbol([tele(T0, rid("c2"), {"a": "BUY"})]))
    assert out["unattributed_trades"] == 1 and out["agents"] == {}


def test_agent_votes_legacy_fallback_rejects_differing_decisions():
    legacy = closed("c1", T0, position_id="long:BTCUSDT:old")
    same = [tele(T0, None, {"a": "BUY"}), tele(T0_PLUS, None, {"a": "BUY"})]
    differ = [tele(T0, None, {"a": "BUY"}), tele(T0_PLUS, None, {"a": "SELL"})]
    assert aa.attribute([legacy], aa.decisions_by_symbol(same))["legacy_timestamp_attributed_trades"] == 1
    assert aa.attribute([legacy], aa.decisions_by_symbol(differ))["unattributed_trades"] == 1


def test_decision_trace_joins_approval_execution_and_close_exactly():
    events = [
        {"event_type": "RISK_APPROVED", "timestamp": T0, "aggregate_id": rid("c2"), "correlation_id": rid("c2"),
         "payload": {"reason": "theirs"}},
        {"event_type": "RISK_APPROVED", "timestamp": "2026-10-01T09:58:00+00:00", "aggregate_id": rid("c1"),
         "correlation_id": rid("c1"), "payload": {"reason": "ours"}},
        {"event_type": "RISK_ACCOUNTING_REALIZED_PNL_PREPARED", "timestamp": "2026-10-01T11:00:00+00:00",
         "aggregate_id": "2026-10-01", "correlation_id": None,
         "payload": {"position_id": pid("c1"), "position_closed": True, "request_id": "BTCUSDT|c9|SELL",
                     "execution_id": "exec-close-1"}},
    ]
    t = dt.trace(closed("c1", T0), [tele(T0, rid("c2"), {"a": "SELL"})], events)
    assert t["request_id"] == rid("c1")
    assert [r["reason"] for r in t["2_risk_and_execution"]] == ["ours"]
    assert t["2b_close"]["close_execution_id"] == "exec-close-1"
    assert t["attribution"] == {"decision": "UNATTRIBUTED", "risk_and_execution": "EXACT", "close": "EXACT"}
    assert str(t["1_decision"]).startswith("N/A (UNATTRIBUTED")


def test_decision_trace_legacy_refuses_two_overlapping_requests():
    events = [{"event_type": "RISK_APPROVED", "timestamp": T0, "correlation_id": rid("c1"), "payload": {"symbol": "BTCUSDT"}},
              {"event_type": "RISK_APPROVED", "timestamp": T0_PLUS, "correlation_id": rid("c2"), "payload": {"symbol": "BTCUSDT"}}]
    t = dt.trace(closed("c1", T0, position_id="long:BTCUSDT:old"), [], events)
    assert t["attribution"]["risk_and_execution"] == "UNATTRIBUTED"
    assert str(t["2_risk_and_execution"]).startswith("N/A (UNATTRIBUTED")


# --- one complete trade through the real runtime --------------------------------------------------


def test_one_complete_paper_trade_is_attributed_exactly_end_to_end(tmp_path):
    from core.application import EXECUTION_AUDIT_EVENT_FILE

    app = application(tmp_path)
    app.execution.start()
    loop = execution_enabled_loop(app, "BUY")
    result = loop.process_symbol("BTCUSDT")
    assert result["status"] == "PAPER_EXECUTED"
    position = app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]
    telemetry = loop._telemetry_decision("BTCUSDT")
    app.stop()

    assert telemetry["request_id"] == result["request_id"]                     # write side: decision -> request_id
    assert ppr.opened_by(position["position_id"], result["request_id"])        # request_id -> position_id
    approvals = ppr.approvals_by_symbol(tmp_path / "state" / EXECUTION_AUDIT_EVENT_FILE)
    chosen = ppr.entry_approval(approvals["BTCUSDT"], position["opened_at"], position["position_id"])
    assert chosen["attribution"] == ppr.EXACT and chosen["request_id"] == result["request_id"]
    assert chosen["risk_approval_event_id"]


def test_decision_trace_legacy_refuses_events_without_a_request_identity():
    """Independent review MEDIUM-1: events lacking correlation_id cannot be proven to be one request."""
    events = [{"event_type": "RISK_APPROVED", "timestamp": T0, "payload": {"symbol": "BTCUSDT"}},
              {"event_type": "RISK_REJECTED", "timestamp": T0_PLUS, "payload": {"symbol": "BTCUSDT"}}]
    t = dt.trace(closed("c1", T0, position_id="long:BTCUSDT:old"), [], events)
    assert t["attribution"]["risk_and_execution"] == "UNATTRIBUTED"
