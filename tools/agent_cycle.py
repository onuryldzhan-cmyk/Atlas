"""Agent cycle: run every rule-based Atlas agent in turn and record what each one did.

  python -m tools.agent_cycle                 # one cycle: every agent now
  python -m tools.agent_cycle --every 5       # scheduler: every 5 minutes run the agents that are due
                                              # (each agent has its own clock, see SCHEDULE; Ctrl+C stops it)

Normally tools.start_atlas runs the scheduler for you, beside Atlas, as its own lower-priority process.
Only one runner can run at a time (an OS lock): while it runs, both commands above refuse to start a
second one, because two runners would race on record ids.

Runs next to Atlas on the owner machine and never touches the runtime, the
execution path or money. Each agent reads real evidence and writes only
through the governed logs (memory records, tasks, proposals):

  quant_research        performance report over the closed-position archive -> memory (only when new trades closed)
  strategy_lab          evidence-backed proposals from what the trades taught -> proposals (owner decides)
  market_regime         regime of each universe coin (trend / sideways / high-vol / panic) -> memory (observation only)
  knowledge_manager     lesson lifecycle (candidate / provisional / contested) -> memory, only when a status changes
  red_team              counter-view on each open strategy proposal: is the evidence enough? -> memory
  executive_assistant   self-review of code, tests, security and agents -> tasks
  data_quality          health check of the durable book, venue rules, logs
  security              Security Guardian scan of the running code
  explainable_ai        every closed trade -> memory with why it won/lost; an AI review with realistic suggestions
  deployment_manager    change notes: what changed / was fixed (git, read-only) and how Atlas looks since
  ai_model_research     apprentice: learns the AI advisors' answers to take their work over one day (owner decides)

One agent failing never stops the others; the failure is recorded. A cycle
is one OPERATIONS memory record, which the Agents page shows. Under the
scheduler (owner 2026-10-03) an agent runs only when its turn has come and
its inputs changed, and a tick is recorded when something changed or failed
(at least hourly, so the dashboard sees the agents alive).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from tools import atlas_org_cli as cli

Step = tuple[str, str, Callable[[], dict[str, Any]]]


def _archive_path() -> Path:
    from core.application import EXECUTION_CLOSED_POSITIONS_FILE, resolve_state_directory

    return resolve_state_directory() / EXECUTION_CLOSED_POSITIONS_FILE


def _approvals() -> dict:
    from core.application import EXECUTION_AUDIT_EVENT_FILE, resolve_state_directory
    from tools.paper_position_report import approvals_by_symbol

    return approvals_by_symbol(resolve_state_directory() / EXECUTION_AUDIT_EVENT_FILE)


def _last_report_total(records_dir: Path) -> dict[str, Any] | None:
    """The "total" block of the latest readable performance report (None when there is none)."""
    from atlas_org import memory_records

    records = memory_records.replay(cli.read_log(records_dir / cli.MEMORY_LOG)) if (records_dir / cli.MEMORY_LOG).exists() else {}
    totals = []
    for r in sorted(records.values(), key=lambda x: x["seq"]):
        if r["author"] != "quant_research" or r["type"] != "EXPERIMENTS":
            continue
        try:
            total = json.loads(r["body"]).get("total", {})
        except (ValueError, AttributeError):  # an older truncated body is skipped, never fatal
            continue
        if isinstance(total, dict):
            totals.append(total)
    return totals[-1] if totals else None


def _last_recorded_trades(records_dir: Path) -> int | None:
    return (_last_report_total(records_dir) or {}).get("trades")


def _since_last(previous: dict[str, Any] | None, total: dict[str, Any]) -> dict[str, Any] | None:
    """Owner 2026-10-03, build on the previous report: what the new trades changed, not the same totals again."""
    if not previous:
        return None
    from decimal import InvalidOperation

    try:
        net_change = str(Decimal(str(total.get("est_net_pnl"))) - Decimal(str(previous.get("est_net_pnl"))))
    except (InvalidOperation, ValueError, TypeError):
        net_change = None
    return {"new_trades": int(total.get("trades") or 0) - int(previous.get("trades") or 0), "net_change": net_change,
            "verdict_before": previous.get("verdict"), "verdict_now": total.get("verdict"),
            "win_rate_before": previous.get("win_rate_after_fees"), "win_rate_now": total.get("win_rate_after_fees")}


def quant_research(records_dir: Path) -> dict[str, Any]:
    from tools.exp001_report import load_closed
    from tools.performance_report import analyse
    from tools.reality_check import run as reality

    closed = load_closed(_archive_path())
    report = analyse(closed)
    n = report["total"].get("trades", 0)
    previous = _last_report_total(records_dir)
    if previous is not None and n == previous.get("trades"):
        return {"verdict": "OK", "summary": f"{n} işlem; yeni kapanan işlem yok, rapor tekrar yazılmadı"}
    real = reality(closed, _approvals())
    since = _since_last(previous, report["total"])
    body = {"total": report["total"], "since_last_report": since, "lessons": report["lessons"],
            "trader_book": report.get("trader_book"), "reality": real}
    existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
    change = f" (+{since['new_trades']} yeni işlem, net değişim {since['net_change']})" if since else ""
    cli.add_memory_record(records_dir, {
        "record_id": f"PR-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
        "title": f"Performans ve gerçeklik raporu: {n} işlem{change}", "body": json.dumps(body, ensure_ascii=False, default=str),
        "author": "quant_research", "source": "tools/agent_cycle.py (performance_report + reality_check)"})
    costs = real["costs"]
    edge = "" if not costs.get("trades") else ("; kenar maliyeti karşılıyor" if costs["edge_covers_costs"] else "; KENAR MALİYETİ KARŞILAMIYOR")
    return {"verdict": "OK", "summary": f"{n} işlem analiz edildi, hafızaya yazıldı; {report['lessons'][0]}{edge}"}


# ---------------------------------------------------------------- AI-001 agents (Claude API)
# Owner choice 2026-10-02. They only ADVISE: a brief or a review is a memory record, never a
# decision. Without a key on the owner's machine they abstain and say so - they never pretend.

_CEO_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["priorities", "followups", "cited_records"],
               "properties": {"priorities": {"type": "array", "items": {"type": "string"}},
                              "followups": {"type": "array", "items": {"type": "string"}},
                              "cited_records": {"type": "array", "items": {"type": "string"}}}}
_COUNCIL_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdict", "reasons"],
                   "properties": {"verdict": {"type": "string", "enum": ["SUPPORT", "OPPOSE", "UNSURE"]},
                                  "reasons": {"type": "array", "items": {"type": "string"}}}}
_AI_SYSTEM = ("You advise Atlas, a PAPER-only crypto research system. You have no authority: you cannot trade, "
              "deploy, approve or change any threshold. Use only the records given; cite their ids. If the "
              "evidence is insufficient, say so. Never invent numbers.")


def _ai_ledger():
    from tools.ai_gateway import USAGE_FILE, UsageLedger

    return UsageLedger(_research_dir() / USAGE_FILE)


def _recent_records(records_dir: Path, n: int = 25) -> list[dict[str, Any]]:
    log = records_dir / cli.MEMORY_LOG
    if not log.exists():
        return []
    from atlas_org import memory_records

    recs = sorted(memory_records.replay(cli.read_log(log)).values(), key=lambda r: r.get("created_at") or "")
    return recs[-n:]


CEO_IGNORED_AUTHORS = frozenset({"ceo_ai", "executive_assistant", "overview_snapshot"})
# 2026-10-03: one record per trade (TP) and the apprentice's scorecards (AP) are not CEO evidence; the trade
# review (TR) that summarises the TPs and the change notes (DM) are.
CEO_IGNORED_PREFIXES = ("TP-", "AP-")
CEO_MIN_GAP_H = 2.5  # spaces the CEO's 5-hour call share instead of spending it in the first cycles
CEO_MIN_EVIDENCE = 3  # fewer evidence records than this: no call (2026-10-02, a 1-record brief invented 5 priorities)
# Owner 2026-10-03: longer questions are fine when they make the answer useful. The CEO reads each record's
# body (capped), not only its title, so it can weigh the evidence instead of listing headlines.
CEO_BODY_CHARS = 700
# Owner 2026-10-03: build on what was done before instead of asking the same things again. The CEO sees its
# previous brief, the records that are NEW since it are marked, and each new priority must go a step further.
CEO_TASK = ("Task - build on your previous brief, never repeat it:\n"
            "1) followups: for each earlier priority, one line in Turkish saying whether the NEW records resolved it, "
            "changed it or left it open, and the next, sharper step if it is still open.\n"
            "2) priorities: at most 5 NEW priorities for the owner, most important first, in Turkish, drawn from the "
            "NEW records. Each must be one concrete decision or check the owner can act on now, say why it matters, "
            "and go a step further than before (a sharper check, a test that would settle it, or the next "
            "decision) - never an earlier priority again unchanged.\n"
            "Do not restate facts the records already state plainly (for example how many agents, records or coins "
            "there are), do not ask questions and skip routine operations. Cite every record you rely on in "
            "cited_records. If nothing new needs the owner, return empty priorities (followups may still say what "
            "changed); if there is nothing at all, return all three lists empty.")


def _brief_items(record: dict[str, Any] | None, key: str = "priorities") -> list[str]:
    try:
        return [str(p) for p in json.loads((record or {}).get("body") or "{}").get(key, [])][:5]
    except (ValueError, AttributeError):
        return []


def ceo_brief(records_dir: Path, ask=None, *, min_gap_h: float = CEO_MIN_GAP_H,
              now: datetime | None = None) -> dict[str, Any]:
    """CEO AI (org unit): up to 5 priorities for the owner, each grounded in cited memory records.

    Asks only when the last brief is at least min_gap_h old AND newer evidence exists since it
    (owner 2026-10-02: use the quota where it adds value, not on repeats).
    """
    from tools import ai_gateway as ai

    # Owner review 2026-10-02: CEO-0074 spent its call on its own previous brief and on routine
    # cycle/self-review/overview records. The CEO now reads evidence only, and only evidence
    # counts as "new" for the spacing gate below.
    recent = [r for r in _recent_records(records_dir, 200) if r.get("author") not in CEO_IGNORED_AUTHORS
              and not str(r.get("id", "")).startswith(CEO_IGNORED_PREFIXES)][-25:]
    if len(recent) < CEO_MIN_EVIDENCE:
        return {"verdict": "OK", "summary": f"{len(recent)} kanıt kaydı (en az {CEO_MIN_EVIDENCE} gerekir); özet çıkarılmadı"}
    mine = [r for r in _recent_records(records_dir, 500) if r.get("author") == "ceo_ai"]
    last_ceo = max((str(r.get("created_at") or "") for r in mine), default="")
    if last_ceo:
        try:
            last_at = datetime.strptime(last_ceo, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            # unreadable timestamp: fail closed, do not spend quota
            return {"verdict": "OK", "summary": "son CEO özetinin zamanı okunamadı; çağrı yapılmadı"}
        age_h = ((now or datetime.now(timezone.utc)) - last_at).total_seconds() / 3600
        if age_h < min_gap_h:
            # audit M1: come back once the gap has passed - the scheduler alone would wait for an unrelated input
            return {"verdict": "OK", "summary": f"son özet {age_h:.1f} saat önce; {min_gap_h} saat beklenir", "pending": True}
        if not any(str(r.get("created_at") or "") > last_ceo and r.get("author") != "ceo_ai" for r in recent):
            return {"verdict": "OK", "summary": "son özetten beri yeni kayıt yok; çağrı yapılmadı"}
    ids = {str(r.get("id")) for r in recent}
    previous = mine[-1] if mine else None
    # audit M6: a follow-ups-only brief must not cut the chain - the open priorities come from the latest brief
    # that had any, the follow-ups from the previous one, and both ids may be cited.
    with_items = next((r for r in reversed(mine) if _brief_items(r)), None)
    lines = []
    if previous and _brief_items(previous, "followups"):
        lines += [f"Your previous brief {previous.get('id')} ({previous.get('created_at')}) followed up:"]
        lines += [f"- {f}" for f in _brief_items(previous, "followups")]
    if with_items:
        lines += [f"Open priorities from your brief {with_items.get('id')} ({with_items.get('created_at')}):"]
        lines += [f"- {p}" for p in _brief_items(with_items)]
    head = "\n".join(lines) if lines else "This is your first brief: there is no earlier one to build on."
    shown = {str(r.get("id")) for r in (previous, with_items) if r}
    prompt = head + "\n\nAtlas evidence records, oldest first (id | NEW = after your previous brief | time | author | type | " \
        "title, then the body):\n\n" + "\n".join(
        f"[{r.get('id')}]{' NEW' if last_ceo and str(r.get('created_at') or '') > last_ceo else ''} {r.get('created_at')} | "
        f"{r.get('author')} | {r.get('type')} | {str(r.get('title') or '')[:200]}\n"
        f"  {' '.join(str(r.get('body') or '').split())[:CEO_BODY_CHARS]}" for r in recent) + "\n\n" + CEO_TASK
    res = (ask or ai.ask)(_AI_SYSTEM, prompt, _CEO_SCHEMA, ledger=_ai_ledger(), agent="ceo_ai")
    if res.status != "OK":
        return {"verdict": "OK", "summary": f"AI-001 çekimser: {res.reason}", "pending": True}
    data = res.data or {}
    priorities = [str(p)[:500] for p in data.get("priorities", []) if str(p).strip()][:5]
    followups = [str(f)[:400] for f in data.get("followups", []) if str(f).strip()][:5]
    if not priorities and not followups:  # a valid answer: nothing new for the owner, so nothing is recorded
        return {"verdict": "OK", "summary": "CEO: sahibin dikkatini gerektiren yeni bir konu yok; kayıt yazılmadı"}
    cited = [c for c in data.get("cited_records", []) if isinstance(c, str)]
    if not any(c in ids for c in cited) or any(c not in ids | shown for c in cited):
        return {"verdict": "OK", "summary": "AI-001 cevabı reddedildi: var olmayan ya da hiç kanıt kaydı gösterilmedi (kanıt doğrulaması)"}
    existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)}
    cli.add_memory_record(records_dir, {
        "record_id": f"CEO-{len(existing) + 1:04d}", "type": "OPERATIONS", "authority": "TEMPORARY",
        "title": f"CEO özeti: {len(priorities)} yeni öncelik, {len(followups)} takip (öneri, karar değil)",
        "body": json.dumps({"priorities": priorities, "followups": followups, "cited_records": cited,
                            "builds_on": previous.get("id") if previous else None, "model": res.model,
                            "cost_usd": str(res.cost_usd)}, ensure_ascii=False),
        "author": "ceo_ai", "source": "tools/agent_cycle.py (ceo_brief, tools/ai_gateway.py)"})
    return {"verdict": "OK", "summary": f"{len(priorities)} öncelik, {len(followups)} takip yazıldı ({res.model}, {res.cost_usd:.4f} $)"}


COUNCIL_MAX_PER_RUN = 3  # owner 2026-10-03: review what is waiting (as needed), not one proposal per cycle
COUNCIL_CONTEXT_CHARS = 1500


def _owner_track_record(state: dict[str, Any], recs: list[dict[str, Any]]) -> str:
    """Earlier proposals the owner decided, next to the council's own verdict on each (owner 2026-10-03:
    build on earlier work - the council learns the owner's bar and where it was wrong, it never decides)."""
    said: dict[str, Any] = {}
    for r in recs:
        if r.get("author") == "model_council" and r.get("related_proposal"):
            try:
                said[str(r["related_proposal"])] = json.loads(r.get("body") or "{}").get("outcome")
            except (ValueError, AttributeError):
                continue
    rows, agree, judged = [], 0, 0
    for pid, prop in sorted(state.items()):
        decision = getattr(prop, "owner_decision", None) or {}
        if not decision.get("decision"):
            continue
        verdict = said.get(pid)
        if verdict in ("SUPPORT", "OPPOSE") and decision["decision"] in ("APPROVED", "REJECTED"):
            judged += 1
            agree += (verdict == "SUPPORT") == (decision["decision"] == "APPROVED")
        note = str(decision.get("note") or "")[:200]
        title = str((getattr(prop, "fields", None) or {}).get("title"))[:120]
        rows.append(f"{pid} '{title}': owner {decision['decision']}{' - ' + note if note else ''}; "
                    f"council said {verdict or 'nothing'}")
    if not rows:
        return ""
    return (f"Owner decisions on earlier proposals (your verdict matched {agree} of {judged} clear calls; where it "
            "missed, weigh what the owner weighed):\n" + "\n".join(rows[-10:]))


def _council_context(records_dir: Path, pid: str, state: dict[str, Any] | None = None) -> str:
    """The evidence a reviewer needs next to the proposal: its red-team review, the latest measurements
    and how the owner decided earlier proposals."""
    recs = _recent_records(records_dir, 500)
    groups = (("Red-team review of this proposal", [r for r in recs if r.get("author") == "red_team"
                                                    and r.get("related_proposal") == pid]),
              ("Latest performance and reality report", [r for r in recs if r.get("author") == "quant_research"]),
              ("Latest model validation (confidence vs results)", [r for r in recs if r.get("author") == "model_validation"]))
    parts = [f"{label} [{group[-1].get('id')}]: {group[-1].get('title')}\n"
             f"{' '.join(str(group[-1].get('body') or '').split())[:COUNCIL_CONTEXT_CHARS]}"
             for label, group in groups if group]
    track = _owner_track_record(state or {}, recs)
    if track:
        parts.append(track)
    return "\n\n".join(parts) or "No related evidence record yet."


def model_council(records_dir: Path, ask=None) -> dict[str, Any]:
    """Multi-Model Council (org unit): two models review each open proposal independently.

    Disagreement is recorded as DISAGREEMENT, never forced into consensus (model_registry.json).
    Each proposal is reviewed once; up to COUNCIL_MAX_PER_RUN per run, and "pending" tells the
    scheduler to come back when some are left or the model abstained.
    """
    from tools import ai_gateway as ai

    from atlas_org import proposals as P

    plog = records_dir / cli.PROPOSALS_LOG
    state = P.replay(cli.read_log(plog)) if plog.exists() else {}
    open_ids = [pid for pid, prop in state.items() if prop.status not in P.TERMINAL and prop.status != P.S.APPLIED]
    reviewed = {str(r.get("related_proposal")) for r in _recent_records(records_dir, 500) if r.get("author") == "model_council"}
    todo = [pid for pid in sorted(open_ids) if pid not in reviewed]
    if not todo:
        return {"verdict": "OK", "summary": "incelenecek yeni öneri yok"}
    notes, pending = [], len(todo) > COUNCIL_MAX_PER_RUN
    for pid in todo[:COUNCIL_MAX_PER_RUN]:
        fields = state[pid].fields or {}
        prompt = (f"Proposal {pid}: {fields.get('title')}\nRisk: {fields.get('risk_level') or fields.get('risk')}\n"
                  f"Body: {json.dumps(fields, ensure_ascii=False, default=str)[:6000]}\n\n"
                  f"Related evidence:\n{_council_context(records_dir, pid, state)}\n\n"
                  "Should the owner approve it? Answer SUPPORT, OPPOSE or UNSURE. Give short reasons in Turkish that "
                  "point to the evidence above (sample size, costs, what could make the claim wrong); do not repeat "
                  "the proposal text.")
        votes: dict[str, dict[str, Any]] = {}
        abstained = None
        for perspective in ai.COUNCIL_PERSPECTIVES:
            system = f"{_AI_SYSTEM} Review independently as a {perspective}."
            res = (ask or ai.ask)(system, prompt, _COUNCIL_SCHEMA, ledger=_ai_ledger(), agent="model_council")
            if res.status != "OK":
                abstained = res.reason
                break  # audit H1: the next perspective would hit the same wall; no call is spent on it
            data = res.data or {}
            votes[perspective] = {"verdict": data.get("verdict"), "reasons": [str(x)[:300] for x in data.get("reasons", [])][:5]}
        if abstained is not None:
            # audit M5: a council verdict needs every perspective - one answer is not a consensus. Come back later;
            # an answer already given is served again from the gateway's cache, not paid twice.
            notes.append(f"AI-001 çekimser ({pid}): {abstained}")
            pending = True
            break
        verdicts = {v["verdict"] for v in votes.values()}
        outcome = verdicts.pop() if len(verdicts) == 1 else "DISAGREEMENT"
        existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)}
        cli.add_memory_record(records_dir, {
            "record_id": f"MC-{len(existing) + 1:04d}", "type": "OPERATIONS", "authority": "TEMPORARY",
            "title": f"Model konseyi {pid}: {outcome} (tavsiye, onay değil)",
            "body": json.dumps({"votes": votes, "outcome": outcome, "model": ai.DEFAULT_MODEL,
                                "note": "one model, two independent perspectives - not two models"}, ensure_ascii=False),
            "author": "model_council", "related_proposal": pid,
            "source": "tools/agent_cycle.py (model_council, tools/ai_gateway.py)"})
        notes.append(f"{pid}: {outcome}")
    if len(todo) > COUNCIL_MAX_PER_RUN and not notes[-1].startswith("AI-001"):
        notes.append(f"{len(todo) - COUNCIL_MAX_PER_RUN} öneri sonraki çalışmaya kaldı")
    return {"verdict": "OK", "summary": "; ".join(notes), "pending": pending}


OVERCONFIDENCE_GAP = -0.10  # win rate this far below the stated confidence, in a MEASURED band


def model_validation(records_dir: Path) -> dict[str, Any]:
    """Model Validation Department (org unit, owner 2026-10-02): does Atlas's confidence match reality?

    Rule-based: per confidence band, win rate after fees vs mean stated confidence and the
    Brier score (tools/reality_check.calibration; ideas from proper-scoring practice). A band
    with enough trades (MEASURED) whose win rate is >10 points below its confidence is flagged
    OVERCONFIDENT. Evidence only - it never changes a confidence or a threshold (NB-4); one
    MV record per change of findings.
    """
    from tools.exp001_report import load_closed
    from tools.reality_check import calibration

    rows = calibration(load_closed(_archive_path()), _approvals())
    measured = [r for r in rows if r.get("verdict") == "MEASURED"]
    flagged = [r["band"] for r in measured if (r.get("calibration_gap") or 0) <= OVERCONFIDENCE_GAP]
    # 2026-10-02: a flag is CONFIRMED when even the top of the 95 % Wilson interval of the win rate is
    # below the stated confidence; otherwise it stays flagged but only SUSPECTED (small sample).
    confirmed = [r["band"] for r in measured if r["band"] in flagged and r.get("win_rate_95ci")
                 and r["win_rate_95ci"][1] < r["mean_confidence"]]
    findings = {"bands": [{k: r.get(k) for k in ("band", "trades", "mean_confidence", "win_rate_after_fees",
                                                 "win_rate_95ci", "brier", "calibration_gap", "verdict")} for r in rows],
                "overconfident_bands": flagged, "overconfidence_confirmed": confirmed}
    log = records_dir / cli.MEMORY_LOG
    previous = None
    if log.exists():
        from atlas_org import memory_records
        mine = [r for r in memory_records.replay(cli.read_log(log)).values() if r.get("author") == "model_validation"]
        if mine:
            previous = json.loads(sorted(mine, key=lambda r: r.get("created_at") or "")[-1].get("body") or "{}")
    if previous == findings:
        return {"verdict": "OK", "summary": "kalibrasyon değişmedi; yeni kayıt yok"}
    existing = {r["record_id"] for r in cli.read_log(log)} if log.exists() else set()
    title = (f"Model doğrulama: AŞIRI GÜVEN {', '.join(flagged)} bandında "
             f"({'kesin: ' + ', '.join(confirmed) if confirmed else 'şüpheli; örnek henüz kesin değil'})" if flagged
             else f"Model doğrulama: {len(measured)} bant ölçüldü, aşırı güven yok" if measured
             else "Model doğrulama: ölçecek kadar işlem yok (bant başına en az 10)")
    cli.add_memory_record(records_dir, {
        "record_id": f"MV-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
        "title": title, "body": json.dumps(findings, ensure_ascii=False, default=str),
        "author": "model_validation", "source": "tools/agent_cycle.py (model_validation, tools/reality_check.calibration)"})
    return {"verdict": "OK", "summary": title}


def strategy_lab(records_dir: Path) -> dict[str, Any]:
    from tools.exp001_report import load_closed
    from tools.performance_report import analyse
    from tools.strategy_agent import file_proposals

    out = file_proposals(analyse(load_closed(_archive_path())), records_dir, apply=True)
    filed = ", ".join(f["id"] for f in out["filed"]) or "yok"
    return {"verdict": "OK", "summary": f"yeni öneri: {filed}; açık olduğu için tekrar edilmeyen: {len(out['skipped_open'])}"}


def market_regime(records_dir: Path, symbols=None, fetch_closes=None) -> dict[str, Any]:
    """Observation only: how many coins are trending right now. Nothing reads this at decision time."""
    from tools import regime_engine as R

    symbols = symbols or R.load_symbols()
    fetch = fetch_closes or R.binance_closes
    # 2026-10-02: 20 sequential downloads took 329 s once (> AGENT_BUDGET_S). Download in parallel;
    # a failed download is stored as the exception and snapshot() still records that coin UNKNOWN.
    from concurrent.futures import ThreadPoolExecutor

    def _get(sym):
        try:
            return sym, fetch(sym)
        except Exception as exc:  # noqa: BLE001 - re-raised per symbol inside snapshot()
            return sym, exc
    with ThreadPoolExecutor(max_workers=5) as pool:
        got = dict(pool.map(_get, symbols))

    def _prefetched(sym):
        value = got[sym]
        if isinstance(value, Exception):
            raise value
        return value
    snap = R.snapshot(symbols, _prefetched)
    counts: dict[str, int] = {}
    for r in snap.values():
        counts[r["regime"]] = counts.get(r["regime"], 0) + 1
    if counts.get("UNKNOWN") == len(snap):
        return {"verdict": "WARN", "summary": f"{len(snap)} coin için veri alınamadı; rejim bilinmiyor"}
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
    trend = counts.get("TREND_UP", 0)
    coins = {k: {"regime": v["regime"]} for k, v in snap.items()}
    log = records_dir / cli.MEMORY_LOG
    if log.exists():
        # Owner 2026-10-03 (no busywork): an unchanged map is not recorded again. Before, every cycle wrote
        # an MR record, which also counted as "new evidence" for the CEO and filled its context.
        from atlas_org import memory_records

        mine = [r for r in memory_records.replay(cli.read_log(log)).values() if r.get("author") == "market_regime"]
        if mine:
            try:
                last = json.loads(max(mine, key=lambda r: r["seq"])["body"]).get("coins")
            except (ValueError, KeyError, AttributeError):
                last = None  # an unreadable last record never suppresses a new one
            if last == coins:
                return {"verdict": "OK", "summary": f"{summary}; rejim değişmedi, yeni kayıt yok"}
    existing = {r["record_id"] for r in cli.read_log(log)} if log.exists() else set()
    cli.add_memory_record(records_dir, {
        "record_id": f"MR-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
        "title": f"Piyasa rejimi: {summary}",
        "body": json.dumps({"counts": counts, "coins": coins}, ensure_ascii=False),
        "author": "market_regime", "source": "tools/agent_cycle.py (regime_engine)"})
    return {"verdict": "OK", "summary": f"{summary}; yükselen trendde {trend}/{len(snap)} coin"}


def knowledge_manager(records_dir: Path) -> dict[str, Any]:
    """Records the lesson book when a lesson's status changes. Evidence only; it never promotes to VALIDATED."""
    from atlas_org import memory_records
    from observability.learning_view import build
    from tools.exp001_report import load_closed

    log = records_dir / cli.MEMORY_LOG
    mem = memory_records.public_view(memory_records.replay(cli.read_log(log))) if log.exists() else []
    out = build(load_closed(_archive_path()), mem)
    state = {x["id"]: x["status"] for x in out["lessons"]}
    last = None
    for r in sorted(mem, key=lambda r: r["seq"]):
        if r["author"] == "knowledge_manager":
            try:
                last = json.loads(r["body"]).get("statuses")
            except (ValueError, AttributeError):
                continue
    if state == last or not state:
        return {"verdict": "OK", "summary": f"{out['experience_count']} deneyim; ders durumu değişmedi"}
    changed = sorted(k for k in state if (last or {}).get(k) != state[k])
    existing = {r["record_id"] for r in cli.read_log(log)} if log.exists() else set()
    cli.add_memory_record(records_dir, {
        "record_id": f"LS-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
        "title": f"Ders defteri: {len(state)} ders, değişen {len(changed)}",
        "body": json.dumps({"statuses": state, "changed": changed, "counts": out["lesson_status_counts"],
                            "contradictions": [x["id"] for x in out["contradictions"]]}, ensure_ascii=False),
        "author": "knowledge_manager", "source": "tools/agent_cycle.py (observability/learning_view)"})
    return {"verdict": "OK", "summary": f"{len(changed)} dersin durumu değişti; çelişkili: {len(out['contradictions'])}"}


RESEARCH_EVERY_H = 24
RESEARCH_TIMEOUT_H = 6


def _research_dir() -> Path:
    from core.application import resolve_state_directory

    d = resolve_state_directory() / "research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def strategy_research(records_dir: Path, research_dir: Path | None = None, launch=None, now: float | None = None) -> dict[str, Any]:
    """Owner 2026-10-01: nobody waits for strategy comparisons.

    Once a day this agent starts tools.strategy_compare in a separate
    background process (all cores but one) and returns immediately. When the
    result file appears, the next cycle records it in memory (one SC-NNNN
    record per finished run). Research only; it never changes the runtime.

    Pre-registration (audit P4-CLOSURE-003 F-2): the run is bound to a sealed
    hypothesis only when ``strategy_research_registration.json`` in the
    research directory names a ``hypothesis_id`` in the canonical registry
    (``strategy_compare.canonical_registry()``, review R4-2) and that
    hypothesis's sealed window has ended; the run then replays exactly that
    window, and the tool refuses any run that does not match the sealed
    specification, window or universe. Until the window ends the daily run is
    exploratory. A result counts as REGISTERED only if it re-verifies against
    the canonical registry (``strategy_compare.verify_registered_result``); anything
    else, including result files written before this rule, is recorded as
    EXPLORATORY: no BETTER claim, ``evidence_eligible`` false. Nothing is
    registered after the fact. A hypothesis hosts one run (review NEW-2): once
    its run is recorded, or when the binding does not bind (malformed, unknown,
    a different sealed specification), the daily run launches as EXPLORATORY;
    the next registered study needs a new hypothesis from the owner. An
    unreadable or malformed result file is recorded as EXPLORATORY too
    (NEW-4), so it never stops the daily research.
    """
    import subprocess

    d = research_dir or _research_dir()
    result, marker, seen = d / "strategy_compare_latest.json", d / "strategy_compare.running", d / "strategy_compare.recorded"
    now = now if now is not None else time.time()
    if result.exists() and (not seen.exists() or seen.read_text(encoding="utf-8") != str(result.stat().st_mtime_ns)):
        try:  # NEW-4: an unreadable or malformed result is recorded as exploratory, never raised
            data = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            data = {"unreadable": f"{type(exc).__name__}: {exc}"}
        data = data if isinstance(data, dict) else {"unreadable": "the result is not a JSON object"}
        table = {str(name): [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
                 for name, rows in (data.get("table") if isinstance(data.get("table"), dict) else {}).items()}
        raw_verdicts = data.get("verdicts") if isinstance(data.get("verdicts"), dict) else {}
        nets = {name: [r.get("net_pnl") for r in rows] for name, rows in table.items()}
        existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
        from tools import strategy_compare as sc

        try:  # never trust the result file's own claim: re-verify against the canonical registry (R4-2)
            study, registered = sc.verify_registered_result(data, sc.canonical_registry()), True
        except (sc.StudyRegistrationError, OSError, ValueError, KeyError, TypeError) as exc:  # NF-7: never wedge the agent
            study, registered, refusal = {}, False, f"{type(exc).__name__}: {exc}"
        if registered:
            verdicts = raw_verdicts
            better = [k for k, v in verdicts.items() if v == "BETTER"]
            title = f"Strateji karşılaştırması ({study['hypothesis_id']}): BETTER = {', '.join(better) or 'yok'}"
        else:  # quarantine: never promote an unregistered study's verdicts
            verdicts = {str(k): (v if v == "-" else "EXPLORATORY") for k, v in raw_verdicts.items()}
            study = {"status": "EXPLORATORY", "evidence_eligible": False, "reason": "NO_SEALED_PREREGISTRATION",
                     "detail": refusal}
            better = []
            title = "Keşif karşılaştırması (ön kayıtsız; kanıt değildir)"
        cli.add_memory_record(records_dir, {
            "record_id": f"SC-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
            "title": title,
            "body": json.dumps({"study": study, "verdicts": verdicts, "net_by_window": nets,
                                # full evidence for tools/regime_bar_check (drawdown and trade counts per window)
                                "drawdown_by_window": {name: [r.get("max_drawdown") for r in rows] for name, rows in table.items()},
                                "closed_by_window": {name: [r.get("closed_trades") for r in rows] for name, rows in table.items()},
                                "dataset": (data.get("dataset") if isinstance(data.get("dataset"), dict) else {}).get("dataset_sha256"),
                                "finished_at": data.get("finished_at")},
                               ensure_ascii=False, default=str),
            "author": "strategy_lab", "source": "tools/agent_cycle.py (strategy_research, background tools.strategy_compare)"})
        seen.write_text(str(result.stat().st_mtime_ns), encoding="utf-8")
        marker.unlink(missing_ok=True)
        if not registered:
            return {"verdict": "OK", "summary": "karşılaştırma bitti ve hafızaya yazıldı; ön kayıt yok: keşif (kanıt değil)"}
        return {"verdict": "OK", "summary": f"karşılaştırma bitti ve hafızaya yazıldı; BETTER: {', '.join(better) or 'yok'}"}
    if marker.exists() and now - marker.stat().st_mtime < RESEARCH_TIMEOUT_H * 3600:
        return {"verdict": "OK", "summary": "karşılaştırma arka planda sürüyor"}
    if result.exists() and now - result.stat().st_mtime < RESEARCH_EVERY_H * 3600:
        return {"verdict": "OK", "summary": "son karşılaştırma 24 saatten yeni; yeniden başlatılmadı"}
    cmd = [sys.executable, "-m", "tools.strategy_compare", "--days", "30", "--windows", "3", "--embargo", "240",
           "--symbols-file", "config/universe_selection.json", "--json", "--output", str(result)]
    binding = d / "strategy_research_registration.json"
    if binding.exists():  # a sealed hypothesis the owner registered for this daily study
        from tools import strategy_compare as sc

        try:  # a consumed hypothesis (its one run recorded, NEW-2) or a malformed binding runs as exploratory
            hypothesis = str(json.loads(binding.read_text(encoding="utf-8"))["hypothesis_id"])
            registry = sc.canonical_registry()
            study = sc.bind_study(registry, hypothesis, sc.study_parameters(
                sc.VARIANTS, days=30, windows=3, embargo=240, step=15, exp001=True))
            if study["window_ms"][1] <= now * 1000:  # the sealed window has ended: its data exists (R4-1)
                cmd += ["--registry", str(registry), "--hypothesis", hypothesis]
        except (sc.StudyRegistrationError, OSError, ValueError, KeyError, TypeError):
            pass  # NF-7: never wedge the daily agent; the owner registers a new hypothesis for the next study
    (launch or (lambda c: subprocess.Popen(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           cwd=str(Path(__file__).resolve().parents[1]))))(cmd)
    marker.write_text(str(now), encoding="utf-8")
    return {"verdict": "OK", "summary": "karşılaştırma arka planda başlatıldı (paralel); sonuç bir sonraki döngülerde hafızaya yazılacak"}


def _snapshot(records_dir: Path, mem: list[dict[str, Any]]) -> dict[str, Any]:
    """The few facts the Overview's "What changed" compares (all from recorded sources)."""
    from atlas_org import proposals as P, tasks as T
    from ai.core.intelligence.trade_evidence import net_pnl
    from tools.exp001_report import load_closed

    regimes: dict[str, int] = {}
    mr = [r for r in mem if r.get("author") == "market_regime"]
    if mr:
        try:
            regimes = json.loads(max(mr, key=lambda r: r["seq"])["body"]).get("counts", {})
        except (ValueError, KeyError):
            regimes = {}
    try:
        closed = load_closed(_archive_path())
        trades, net = len(closed), round(float(sum((net_pnl(r) for r in closed), Decimal("0"))), 2)
    except Exception:
        trades, net = None, None
    plog, tlog = records_dir / cli.PROPOSALS_LOG, records_dir / cli.TASKS_LOG
    ready = sum(1 for p in P.replay(cli.read_log(plog)).values() if p.status.value == "READY_FOR_OWNER") if plog.exists() else 0
    blocked = sum(1 for t in T.replay(cli.read_log(tlog)).values() if t["status"] == "BLOCKED") if tlog.exists() else 0
    incidents = sum(1 for r in mem if r.get("type") == "INCIDENTS" and not r.get("superseded_by")
                    and (r.get("incident") or {}).get("status") != "RESOLVED")
    return {"regimes": regimes, "closed_trades": trades, "realized_net": net, "awaiting_owner": ready,
            "blocked_tasks": blocked, "open_incidents": incidents}


def overview_snapshot(records_dir: Path) -> dict[str, Any]:
    """Owner Dashboard v1 "What changed": compares the current facts with the last OV record.

    Writes one OV-NNNN record only when something changed, with the list of
    changes; the web layer just displays the latest one (it stays read-only).
    """
    from atlas_org import memory_records

    log = records_dir / cli.MEMORY_LOG
    mem = memory_records.public_view(memory_records.replay(cli.read_log(log))) if log.exists() else []
    now = _snapshot(records_dir, mem)
    prev_recs = [r for r in mem if r.get("author") == "overview_snapshot"]
    prev = {}
    if prev_recs:
        try:
            prev = json.loads(max(prev_recs, key=lambda r: r["seq"])["body"]).get("snapshot", {})
        except (ValueError, KeyError):
            prev = {}
    if now == prev:
        return {"verdict": "OK", "summary": "değişiklik yok"}
    labels = {"closed_trades": "Kapanan işlem", "realized_net": "Gerçekleşen net P/L ($)", "awaiting_owner": "Onayınızı bekleyen öneri",
              "blocked_tasks": "Engelli görev", "open_incidents": "Açık olay"}
    changes = [f"{labels[k]}: {prev.get(k, '—')} → {now[k]}" for k in labels if prev and prev.get(k) != now[k]]
    for reg in sorted(set(now["regimes"]) | set(prev.get("regimes", {}))):
        a, b = prev.get("regimes", {}).get(reg, 0), now["regimes"].get(reg, 0)
        if prev and a != b:
            changes.append(f"Rejim {reg}: {a} → {b} coin")
    existing = {r["record_id"] for r in cli.read_log(log)} if log.exists() else set()
    cli.add_memory_record(records_dir, {
        "record_id": f"OV-{len(existing) + 1:04d}", "type": "OPERATIONS", "authority": "TEMPORARY",
        "title": f"Durum özeti: {len(changes)} değişiklik" if prev else "Durum özeti: ilk kayıt",
        "body": json.dumps({"snapshot": now, "changes": changes}, ensure_ascii=False),
        "author": "overview_snapshot", "source": "tools/agent_cycle.py (overview_snapshot)"})
    return {"verdict": "OK", "summary": f"{len(changes)} değişiklik kaydedildi" if prev else "ilk durum özeti kaydedildi"}


def _security_step(records_dir: Path) -> tuple[str, str]:
    out = security(records_dir)
    return ({"OK": "PASS", "WARN": "REVIEW_REQUIRED"}.get(out["verdict"], "FAIL"), out["summary"])


def _data_step(records_dir: Path) -> tuple[str, str]:
    out = data_quality(records_dir)
    return ({"OK": "PASS", "WARN": "REVIEW_REQUIRED"}.get(out["verdict"], "FAIL"), out["summary"])


# Units that can execute an assigned task step on their own today (rule-based).
STEP_EXECUTORS = {"security": _security_step, "data_quality": _data_step}


def task_runner(records_dir: Path) -> dict[str, Any]:
    """Owner 2026-10-01: agents must not sit waiting for tasks.

    Every ASSIGNED step whose unit has a rule-based executor is started and
    finished now with a real result. A step whose unit needs a language model
    (research, code, review) is BLOCKED once: AI-001 agents are advisory only
    (no tools), so such a step is done in a development session with the
    owner's approval. The reason keeps the "AI-001" marker that
    atlas_self_review uses to skip it. Nothing here can approve,
    deploy or touch money.
    """
    from atlas_org import tasks as T

    log = records_dir / cli.TASKS_LOG
    if not log.exists():
        return {"verdict": "OK", "summary": "görev yok"}
    done, blocked = [], []
    for tid, task in sorted(T.replay(cli.read_log(log)).items()):
        if task["status"] in ("DONE", "CANCELLED"):
            continue
        for step in task["steps"]:
            if step["status"] != "ASSIGNED":
                continue
            unit, idx = step["unit"], step["index"]
            runner = STEP_EXECUTORS.get(unit)
            if runner is None:
                cli.add_task_event(records_dir, task_id=tid, event="BLOCK", actor=T.ASSISTANT,
                                   payload={"step": idx, "reason": f"{unit}: yapay zekâ ajanları yalnız danışman (AI-001); bu adım sahibin onayıyla geliştirme oturumunda yapılır"})
                blocked.append(f"{tid}#{idx}")
                break  # a BLOCK changes the task status; re-read on the next cycle
            cli.add_task_event(records_dir, task_id=tid, event="START", actor=unit, payload={"step": idx})
            verdict, summary = runner(records_dir)
            cli.add_task_event(records_dir, task_id=tid, event="RESULT", actor=unit,
                               payload={"step": idx, "verdict": verdict, "summary": summary[:500]})
            done.append(f"{tid}#{idx}")
    return {"verdict": "OK", "summary": f"yürütülen adım: {', '.join(done) or 'yok'}; AI-001 bekleyen: {', '.join(blocked) or 'yok'}"}


def executive_assistant(records_dir: Path) -> dict[str, Any]:
    from tools.atlas_self_review import run

    out = run(records_dir, apply=True)
    created = [f["task_id"] for f in out.get("filed", []) if f.get("created")]
    return {"verdict": "OK", "summary": f"{out.get('findings', 0)} bulgu; yeni görev: {', '.join(created) or 'yok'}"}


def data_quality(records_dir: Path) -> dict[str, Any]:
    from tools.data_health_check import run

    rows = run()
    bad = [r for r in rows if r.get("status") in ("FAIL", "WARN")]
    verdict = "FAIL" if any(r.get("status") == "FAIL" for r in rows) else "WARN" if bad else "OK"
    return {"verdict": verdict, "summary": f"{len(rows)} kontrol; sorunlu: " + (", ".join(r["check"] for r in bad) or "yok")}


def security(records_dir: Path) -> dict[str, Any]:
    from observability.security_view import read_security

    out = read_security()
    if not out.get("available"):
        return {"verdict": "WARN", "summary": f"tarama yapılamadı: {out.get('reason')}"}
    checks = out.get("checks") or {}
    review = [k for k, v in checks.items() if v != "PASS"]
    verdict = "FAIL" if out.get("overall") == "FAIL" else "OK"
    return {"verdict": verdict, "summary": f"genel {out.get('overall')}; {out.get('files_reviewed')} dosya; "
                                           f"incelenecek: {', '.join(review) or 'yok'}"}


def red_team(records_dir: Path) -> dict[str, Any]:
    """Counter-view on every open strategy proposal (TradingAgents' bull/bear debate, rule-based).

    Challenges the evidence, never the owner: it writes one REVIEWS memory
    record per proposal revision saying whether the sample clears the
    evidence bar and what could make the claim wrong.
    """

    from atlas_org import memory_records, proposals as P
    from tools.performance_report import MIN_SAMPLE

    plog = records_dir / cli.PROPOSALS_LOG
    if not plog.exists():
        return {"verdict": "OK", "summary": "incelenecek öneri yok"}
    state = P.replay(cli.read_log(plog))
    mem = memory_records.replay(cli.read_log(records_dir / cli.MEMORY_LOG)) if (records_dir / cli.MEMORY_LOG).exists() else {}
    done = {r["related_proposal"] for r in mem.values() if r["author"] == "red_team"}
    reviewed = []
    for pid, prop in sorted(state.items()):
        if not pid.startswith(("SA-", "XL-")) or prop.status in P.TERMINAL or prop.status == P.S.APPLIED or pid in done:
            continue
        claims = prop.fields.get("claims") or []
        text = " ".join(str(c.get("evidence", "")) + " " + str(c.get("counter_evidence", "")) for c in claims)
        thin = "INCONCLUSIVE" in text or "below the" in text or "Only " in text
        verdict = "KANIT YETERSİZ" if thin else "KANIT KABUL EDİLEBİLİR"
        body = {"proposal": pid, "verdict": verdict, "min_sample": MIN_SAMPLE,
                "challenge": ("Geçmiş tekrar oynatması: makro/duygu verisi yok, 15 dakikalık kararlar örtüşür (gerçek örnek "
                              "sayısı görünenden az). Çalışma zamanına alınmadan önce paper ve shadow aşamasında "
                              "doğrulanmalı." if pid.startswith("XL-") else
                              "Örnek küçük: önce geçmiş veriyle (replay) test edilmeden çalışma zamanına alınmamalı. "
                              "Kayma ve piyasa rejimi değişimi sonucu tersine çevirebilir." if thin else
                              "Örnek eşiği aşıyor; yine de ücret tahmini (%0,1/taraf) ve PAPER dolumları gerçeği iyimser gösterebilir.")}
        existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
        cli.add_memory_record(records_dir, {
            "record_id": f"RT-{len(existing) + 1:04d}", "type": "REVIEWS", "authority": "TEMPORARY",
            "title": f"Karşı görüş: {pid} — {verdict}", "body": json.dumps(body, ensure_ascii=False),
            "author": "red_team", "source": "tools/agent_cycle.py (red_team)", "related_proposal": pid,
            "claims": [{"claim": prop.fields.get("title", pid), "evidence": text[:500] or "yok",
                        "counter_evidence": body["challenge"]}]})
        reviewed.append(f"{pid}: {verdict}")
    return {"verdict": "OK", "summary": "; ".join(reviewed) or "yeni öneri yok (hepsi zaten incelendi)"}


def experience(records_dir: Path) -> dict[str, Any]:
    """Experience agent (owner 2026-10-02): one more replayed day per cycle; research evidence only."""
    from tools import experience_agent

    return experience_agent.run(records_dir, _research_dir())


def protections_watch(records_dir: Path) -> dict[str, Any]:
    """Would freqtrade-style protections have helped? Observe-only (2026-10-02, tools/protections_report.py).

    Replays the closed PAPER trades through CooldownPeriod / StoplossGuard / LowProfitPairs and records
    one memory record when the finding changes. It never locks a coin or changes a gate: turning a
    protection on is a risk-gate change that needs an owner-approved proposal.
    """
    from tools.exp001_report import load_closed
    from tools.protections_report import replay

    out = replay(load_closed(_archive_path()))
    finding = {"trades": out["trades"],
               "rules": {name: {"blocked": s["blocked"], "blocked_winners": s["blocked_wins"],
                                "net_avoided_usdt": str(round(s["avoided_net"], 2))}
                         for name, s in out["rules"].items()},
               "any_rule": {"blocked": out["combined"]["blocked"],
                            "net_avoided_usdt": str(round(out["combined"]["avoided_net"], 2))}}
    log = records_dir / cli.MEMORY_LOG
    if log.exists():
        from atlas_org import memory_records

        mine = [r for r in memory_records.replay(cli.read_log(log)).values() if r.get("author") == "performance_audit"]
        if mine and json.loads(sorted(mine, key=lambda r: r.get("created_at") or "")[-1].get("body") or "{}") == finding:
            return {"verdict": "OK", "summary": "koruma gözlemi değişmedi; yeni kayıt yok"}
    blocked, avoided = finding["any_rule"]["blocked"], finding["any_rule"]["net_avoided_usdt"]
    title = (f"Koruma gözlemi: {out['trades']} işlem; kurallar {blocked} girişi engellerdi, net {avoided} USDT "
             f"{'kaçınılırdı' if Decimal(avoided) > 0 else 'kaybedilirdi' if Decimal(avoided) < 0 else 'fark'} (kural değil)")
    existing = {r["record_id"] for r in cli.read_log(log)} if log.exists() else set()
    cli.add_memory_record(records_dir, {
        "record_id": f"PA-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
        "title": title, "body": json.dumps(finding, ensure_ascii=False),
        "author": "performance_audit", "source": "tools/agent_cycle.py (protections_watch, tools/protections_report.py)"})
    return {"verdict": "OK", "summary": title}


def shadow_costs(records_dir: Path) -> dict[str, Any]:
    """Shadow stage S1 (owner 2026-10-02): live order-book cost per coin for the typical Paper size; evidence only."""
    from tools import shadow_costs as sc
    from tools.experience_agent import symbols
    from tools.exp001_report import load_closed

    notional, measured = sc.typical_notional(load_closed(_archive_path()))
    out = sc.run(_research_dir(), list(symbols()), notional)
    if not measured:
        out["summary"] += f" (işlem büyüklüğü varsayılan {notional} USDT: henüz kapanan işlem yok)"
    return out


def trade_postmortem(records_dir: Path) -> dict[str, Any]:
    """Explainable AI Center (owner 2026-10-03): every closed trade into memory, then an AI review (tools/trade_postmortem.py)."""
    from tools import trade_postmortem as tp
    from tools.exp001_report import load_closed

    return tp.run(records_dir, load_closed(_archive_path()), _approvals(), ledger=_ai_ledger())


def change_notes(records_dir: Path) -> dict[str, Any]:
    """Deployment Manager, observation only (owner 2026-10-03): what changed and how Atlas looks since (tools/change_log.py)."""
    from tools import change_log

    return change_log.run(records_dir)


def apprentice(records_dir: Path) -> dict[str, Any]:
    """AI Model Research (owner 2026-10-03): learns the AI advisors' answers; never calls a model (tools/apprentice.py)."""
    from tools import apprentice as ap

    return ap.run(records_dir, _research_dir())


AGENTS: tuple[tuple[str, str, Callable[[Path], dict[str, Any]]], ...] = (
    ("quant_research", "Performans analizi", quant_research),
    ("strategy_lab", "Strateji önerileri", strategy_lab),
    ("strategy_research", "Strateji karşılaştırma (arka plan)", strategy_research),
    ("market_regime", "Piyasa rejimi", market_regime),
    ("knowledge_manager", "Ders defteri", knowledge_manager),
    ("task_runner", "Görev yürütücü", task_runner),
    ("overview_snapshot", "Durum özeti", overview_snapshot),
    ("model_validation", "Model doğrulama", model_validation),
    ("experiment_manager", "Deneyim ajanı", experience),
    ("digital_twin", "Shadow maliyet ölçümü", shadow_costs),
    ("performance_audit", "Koruma gözlemi", protections_watch),
    ("explainable_ai", "İşlem sonrası analiz", trade_postmortem),
    ("deployment_manager", "Değişiklik notları", change_notes),
    ("ceo_ai", "CEO özeti (AI-001)", ceo_brief),
    ("model_council", "Model konseyi (AI-001)", model_council),
    ("red_team", "Karşı görüş", red_team),
    ("ai_model_research", "Çırak (Sonnet'ten öğrenir)", apprentice),
    ("executive_assistant", "Öz-değerlendirme", executive_assistant),
    ("data_quality", "Veri sağlığı", data_quality),
    ("security", "Güvenlik taraması", security),
)


VERDICTS = ("OK", "WARN", "FAIL")


def validate_outcome(outcome: Any) -> dict[str, Any]:
    """Task 2 / MEGA 2 §12: an agent's output is data, validated before it is recorded.

    Schema: {"verdict": OK|WARN|FAIL, "summary": str}. Anything else becomes
    FAIL / INVALID_AGENT_OUTPUT. The summary is passed through the
    SensitiveDataGuard and capped, so a secret or an injected instruction is
    stored as inert, redacted text - it never gains authority.
    """
    from atlas_security import sanitize_sensitive_data

    if not isinstance(outcome, dict) or outcome.get("verdict") not in VERDICTS or not isinstance(outcome.get("summary"), str):
        return {"verdict": "FAIL", "summary": "INVALID_AGENT_OUTPUT"}
    return {"verdict": outcome["verdict"], "summary": str(sanitize_sensitive_data(outcome["summary"]))[:500]}


AGENT_BUDGET_S = 300.0  # task 18: one agent taking longer is flagged as a runaway (WARN), never silent


def _open_incidents(records_dir: Path, results: list[dict[str, Any]]) -> None:
    """Task 6 / reliability §12: a FAILed agent opens one OPEN incident (DETECTED); never a duplicate.

    Classification, containment and resolution (root cause, actions,
    prevention) are the owner's, recorded later as a superseding record.
    """
    from atlas_org import memory_records

    log = records_dir / cli.MEMORY_LOG
    mem = memory_records.replay(cli.read_log(log)) if log.exists() else {}
    open_units = {svc for r in mem.values() if r["type"] == "INCIDENTS" and r["superseded_by"] is None
                  and (r.get("incident") or {}).get("status") != "RESOLVED" for svc in (r.get("incident") or {}).get("services", [])}
    for r in results:
        if r["verdict"] != "FAIL" or r["unit"] in open_units:
            continue
        existing = {x["record_id"] for x in cli.read_log(log)} if log.exists() else set()
        cli.add_memory_record(records_dir, {
            "record_id": f"IN-{len(existing) + 1:04d}", "type": "INCIDENTS", "authority": "TEMPORARY",
            "title": f"Olay: {r['name']} ajanı başarısız", "body": r["summary"],
            "author": "executive_assistant", "source": "tools/agent_cycle.py (automatic detection)",
            "incident": {"what": r["summary"][:300], "detected_at": cli.now(), "severity": "MEDIUM",
                         "services": [r["unit"]], "status": "OPEN"}})
        open_units.add(r["unit"])


def _cycle_ai_usage(start_s: float, end_s: float) -> tuple[int, Any] | None:
    """(calls, USD) the usage ledger recorded during one cycle; None when it cannot be read. Creates nothing."""
    try:
        from core.application import resolve_state_directory
        from tools.ai_gateway import USAGE_FILE, UsageLedger

        return UsageLedger(resolve_state_directory() / "research" / USAGE_FILE).between(start_s, end_s)
    except Exception:  # noqa: BLE001 - an unreadable ledger is reported as unknown, never as zero
        return None


def _run_agents(records_dir: Path, agents) -> list[dict[str, Any]]:
    """Run the given agents in order; one failing never stops the others."""
    results = []
    for unit, name, fn in agents:
        started = time.monotonic()
        pending = False
        try:
            raw = fn(records_dir)
            outcome = validate_outcome(raw)
            # "pending": work is left over (or the model abstained), so the scheduler comes back for it.
            pending = isinstance(raw, dict) and raw.get("pending") is True and outcome["verdict"] != "FAIL"
        except (Exception, cli.RecordLockBusy) as exc:  # one agent failing never stops the others
            # RecordLockBusy is a SystemExit for the CLI; here a busy log fails this agent only.
            outcome = {"verdict": "FAIL", "summary": f"{type(exc).__name__}: {exc}"[:300]}
        seconds = round(time.monotonic() - started, 2)
        if seconds > AGENT_BUDGET_S and outcome.get("verdict") == "OK":
            outcome = {**outcome, "verdict": "WARN", "summary": f"süre bütçesi aşıldı ({seconds}s > {AGENT_BUDGET_S:g}s); " + str(outcome.get("summary", ""))}
        results.append({"unit": unit, "name": name, **outcome, "seconds": seconds, **({"pending": True} if pending else {})})
    return results


def _record_cycle(records_dir: Path, results: list[dict[str, Any]], started_s: float,
                  skipped: list[dict[str, Any]] | None = None, *, incidents: bool = True,
                  notes: dict[str, Any] | None = None) -> dict[str, Any]:
    """One AC record for the agents that ran (and, from the scheduler, the ones whose turn it was not)."""
    skipped = skipped or []
    # 2026-10-02: the AI-001 advisors (CEO, council) make paid model calls, so the cycle reports what
    # the usage ledger recorded during it instead of the old "no model calls" text.
    usage = _cycle_ai_usage(started_s, time.time())
    resources = {"total_seconds": round(sum(r["seconds"] for r in results), 2),
                 "ai_calls": usage[0] if usage else "UNKNOWN (usage ledger unreadable)",
                 "ai_cost_usd": str(usage[1]) if usage else "UNKNOWN (usage ledger unreadable)",
                 "llm_tokens": "N/A (the usage ledger records calls and cost, not tokens)",
                 "budget_per_agent_s": AGENT_BUDGET_S, **(notes or {})}
    try:
        if incidents:
            _open_incidents(records_dir, results)
        existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
        rid = f"AC-{len(existing) + 1:04d}"
        ok = sum(1 for r in results if r["verdict"] == "OK")
        title = (f"Ajan döngüsü: {ok}/{len(results)} ajan sorunsuz" if not skipped else
                 f"Ajan döngüsü: {len(results)} ajan çalıştı ({ok} sorunsuz), {len(skipped)} ajanın sırası değildi")
        if (notes or {}).get("schedule_save_failed"):
            title += " - UYARI: zamanlama kaydedilemedi, ajanlar her turda yeniden çalışabilir"
        cli.add_memory_record(records_dir, {
            "record_id": rid, "type": "OPERATIONS", "authority": "TEMPORARY", "title": title,
            "body": json.dumps({"agent_cycle": results + skipped, "resources": resources}, ensure_ascii=False),
            "author": "executive_assistant", "source": "tools/agent_cycle.py"})
    except cli.RecordLockBusy as exc:  # the next cycle records again; the loop must not die on a busy log
        return {"record_id": None, "results": results, "resources": resources, "warning": str(exc)}
    return {"record_id": rid, "results": results, "resources": resources}


def run_cycle(records_dir: Path = cli.RECORDS_DIR, agents=AGENTS) -> dict[str, Any]:
    """Every agent now, ignoring the schedule (the one-shot command), recorded as one AC record."""
    started = time.time()
    return _record_cycle(records_dir, _run_agents(records_dir, agents), started)


# ---------------------------------------------------------------- per-agent schedule (owner 2026-10-03)
# "Each agent on its own clock, as much as its work needs, no busywork." minutes = earliest re-run;
# inputs = files that must have changed since the agent's last clean run (None: the clock alone, for
# agents that sample the outside world). Inputs are compared by size + modification time (a stat call).
SCHEDULE: dict[str, tuple[float, tuple[str, ...] | None]] = {
    "quant_research": (15, ("archive", "audit")),            # a new closed trade or approval
    "strategy_lab": (15, ("archive", "proposals")),
    "strategy_research": (60, None),                         # starts / collects the daily background comparison
    "market_regime": (60, None),                             # 1-hour candles: a regime moves with an hourly close
    "knowledge_manager": (30, ("archive", "memory")),
    "task_runner": (10, ("tasks",)),
    "overview_snapshot": (30, ("archive", "memory", "proposals", "tasks")),
    "model_validation": (30, ("archive", "audit")),
    "experiment_manager": (10, None),                        # one replayed day per run until the history is done
    "digital_twin": (30, None),                              # order-book cost samples across the day
    "performance_audit": (30, ("archive",)),
    "explainable_ai": (15, ("archive", "audit")),            # a new closed trade; its AI review waits for 5 of them
    "deployment_manager": (60, None),                        # new commits since the last note (git, read-only)
    "ai_model_research": (30, ("memory",)),                  # learns from new CEO / council answers
    "ceo_ai": (150, ("memory",)),                            # model call: new evidence, at least 2.5 h apart
    "model_council": (15, ("proposals",)),                   # model calls: proposals not reviewed yet
    "red_team": (15, ("proposals",)),
    "executive_assistant": (360, None),                      # code / test / security self-review
    "data_quality": (60, None),
    "security": (360, None),
}
SCHEDULE_FILE = "agent_schedule.json"
# An idle runner still records one cycle an hour, so the dashboard (agent_states.RECENT_CYCLE_S = 2 h) never
# shows working agents as OFFLINE; a tick in which something changed or failed is recorded at once.
HEARTBEAT_RECORD_S = 3600.0
LOG_FILES = (cli.MEMORY_LOG, cli.PROPOSALS_LOG, cli.TASKS_LOG)


def _input_paths(records_dir: Path) -> dict[str, Path]:
    from core.application import EXECUTION_AUDIT_EVENT_FILE, resolve_state_directory

    return {"archive": _archive_path(), "audit": resolve_state_directory() / EXECUTION_AUDIT_EVENT_FILE,
            "memory": records_dir / cli.MEMORY_LOG, "proposals": records_dir / cli.PROPOSALS_LOG,
            "tasks": records_dir / cli.TASKS_LOG}


def _stamp(path: Path) -> list[int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


def _fingerprint(unit: str, paths: dict[str, Path] | None) -> dict[str, Any] | None:
    names = SCHEDULE.get(unit, (0, None))[1]
    if not names or paths is None:
        return None  # the clock alone decides
    return {n: _stamp(paths[n]) for n in names}


def _due(unit: str, entry: Any, fingerprint: dict[str, Any] | None, now: float) -> tuple[bool, str]:
    """(due, why not). Unknown agents, first runs, unreadable entries and a clock that went back: due."""
    if unit not in SCHEDULE or not isinstance(entry, dict):
        return True, ""
    try:
        last = float(entry["last_run"])
    except (KeyError, TypeError, ValueError):
        return True, ""
    if now < last:  # the clock went back: run instead of stalling until it catches up
        return True, ""
    wait = last + SCHEDULE[unit][0] * 60 - now
    if wait > 0:
        return False, f"sırası değil, {max(1, round(wait / 60))} dk sonra"
    if entry.get("verdict") != "OK" or entry.get("pending"):
        return True, ""  # a failed, warned or unfinished run is retried even without new input
    if fingerprint is not None and entry.get("fingerprint") == fingerprint:
        return False, "yeni girdi yok"
    return True, ""


def _load_schedule(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None  # missing or unreadable: every agent is due once (the old every-cycle behaviour)
    if not isinstance(data, dict) or not isinstance(data.get("units"), dict):
        data = {"units": {}}
    return data


def _save_schedule(path: Path, state: dict[str, Any]) -> bool:
    """False when the schedule could not be written. Never fatal, but reported (audit L6): without it every tick
    would quietly run every agent again."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return False
    return True


def run_scheduled(records_dir: Path = cli.RECORDS_DIR, agents=AGENTS, *, state_path: Path | None = None,
                  clock: Callable[[], float] = time.time, should_stop: Callable[[], bool] = lambda: False,
                  beat: Callable[[], None] = lambda: None) -> dict[str, Any]:
    """One scheduler tick: only the agents that are due run (owner 2026-10-03).

    should_stop is checked before each agent (a stop request never cuts an agent in half); beat is
    called before each agent, so a supervisor can tell a long tick from a hung one."""
    path = state_path or (_research_dir() / SCHEDULE_FILE)
    state = _load_schedule(path)
    units = state["units"]
    names = {unit: name for unit, name, _ in agents}
    try:
        paths: dict[str, Path] | None = _input_paths(records_dir)
    except Exception:  # noqa: BLE001 - unknown input paths: the clock decides, an agent is never silenced
        paths = None
    started = clock()
    logs_before = [_stamp(records_dir / name) for name in LOG_FILES]
    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    saved = True
    # Audit M3: an agent that was running when the previous runner hung or was killed is recorded as a failure and
    # waits for its own interval, so it cannot block the agents after it on every restart.
    for unit, entry in list(units.items()):
        if isinstance(entry, dict) and "running_since" in entry:
            summary = "önceki çalışması yarıda kaldı (çalıştırıcı asılı kaldı ya da durduruldu); sırası gelince yeniden denenecek"
            units[unit] = {"last_run": entry["running_since"], "verdict": "FAIL", "pending": False,
                           "fingerprint": entry.get("fingerprint"), "summary": summary}
            results.append({"unit": unit, "name": names.get(unit, unit), "verdict": "FAIL", "summary": summary, "seconds": 0.0})
    if results:
        saved = _save_schedule(path, state) and saved
    for unit, name, fn in agents:
        if should_stop():
            break
        entry = units.get(unit)
        fingerprint = _fingerprint(unit, paths)
        due, why = _due(unit, entry, fingerprint, clock())
        if not due:
            last = entry if isinstance(entry, dict) else {}
            # audit M2: a skipped agent keeps its last verdict, so a failure stays visible until a run clears it
            verdict = last.get("verdict") if last.get("verdict") in VERDICTS else "OK"
            skipped.append({"unit": unit, "name": name, "verdict": verdict, "ran": False, "seconds": 0.0,
                            "summary": f"atlandı ({why}); son çalışma: {str(last.get('summary') or 'henüz yok')[:300]}"})
            continue
        beat()
        ran_at = clock()
        units[unit] = {**(entry if isinstance(entry, dict) else {}), "running_since": ran_at, "fingerprint": fingerprint}
        saved = _save_schedule(path, state) and saved
        result = _run_agents(records_dir, ((unit, name, fn),))[0]
        results.append(result)
        units[unit] = {"last_run": ran_at, "verdict": result["verdict"], "pending": bool(result.get("pending")),
                       "fingerprint": fingerprint, "summary": result["summary"]}
        saved = _save_schedule(path, state) and saved  # after every agent: a crash mid-tick never repeats finished work
    notes = {} if saved else {"schedule_save_failed": True}
    if not results:
        return {"record_id": None, "results": results, "skipped": skipped, "recorded": False, **notes}
    changed = [_stamp(records_dir / name) for name in LOG_FILES] != logs_before
    failed = any(r["verdict"] != "OK" for r in results)
    last_record = state.get("last_record_at")
    heartbeat = not isinstance(last_record, (int, float)) or not 0 <= clock() - last_record < HEARTBEAT_RECORD_S
    if not (changed or failed or heartbeat or notes):
        return {"record_id": None, "results": results, "skipped": skipped, "recorded": False}
    try:
        _open_incidents(records_dir, results)  # audit L1: incidents are new input for the agents that read them
    except cli.RecordLockBusy:
        pass  # the next failing tick opens it; the cycle record below still says what failed
    log = records_dir / cli.MEMORY_LOG
    memory_before = _stamp(log)
    count_before = len(cli.read_log(log)) if log.exists() else 0
    out = _record_cycle(records_dir, results, started, skipped, incidents=False, notes=notes)
    if out["record_id"]:
        state["last_record_at"] = clock()
        # The cycle record is the runner's own bookkeeping, not new input: an agent whose memory input was current
        # before it stays current after it - but only when that record is the one and only line added (audit L1).
        if len(cli.read_log(log)) == count_before + 1:
            memory_after = _stamp(log)
            for entry in units.values():
                fp = entry.get("fingerprint") if isinstance(entry, dict) else None
                if isinstance(fp, dict) and "memory" in fp and fp["memory"] == memory_before:
                    fp["memory"] = memory_after
        saved = _save_schedule(path, state) and saved
    return {**out, "skipped": skipped, "recorded": bool(out["record_id"]), **({} if saved else {"schedule_save_failed": True})}


def _print_cycle(out: dict[str, Any]) -> None:
    print(f"\n{out['record_id'] or 'kayıt yazılmadı'}  {time.strftime('%Y-%m-%d %H:%M')}")
    for r in out["results"]:
        print(f"  {r['verdict']:<4} {r['name']:<20} {r['summary']}")
    if out.get("skipped"):
        print(f"  ({len(out['skipped'])} ajanın sırası değildi ya da yeni girdisi yoktu)")


# ---------------------------------------------------------------- the runner process (owner 2026-10-03)
# One runner at a time: two would race on record ids. The lock is the same exclusive OS lock Atlas uses for its
# state root (core.instance_lock), on its own directory; the OS drops it when the process dies, so a crash never
# leaves a stale lock. The heartbeat file lets tools.start_atlas tell a long tick from a hung runner.
RUNNER_DIR = "agent_runner"
HEARTBEAT_FILE = "heartbeat"
ALREADY_RUNNING_EXIT = 3
LOCK_UNAVAILABLE_EXIT = 2


def runner_dir(create: bool = True) -> Path:
    if create:
        return _research_dir() / RUNNER_DIR
    from core.application import resolve_state_directory

    return resolve_state_directory() / "research" / RUNNER_DIR  # the same place, without creating anything


def _beat(directory: Path) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / HEARTBEAT_FILE).write_text(str(time.time()), encoding="utf-8")
    except OSError:  # a missed beat only makes the supervisor's hang check stricter, never a crash here
        pass


def _install_stop_signals(stop) -> dict[Any, Any]:
    """Ctrl+Break (Windows) / SIGTERM (elsewhere): finish the current agent, then stop. Returns the old handlers."""
    import signal

    previous = {}
    for name in ("SIGBREAK", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                previous[sig] = signal.signal(sig, lambda *_: stop.set())
            except (ValueError, OSError):  # not the main thread / not supported here
                pass
    return previous


def _restore_signals(previous: dict[Any, Any]) -> None:
    import signal

    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError, TypeError):
            pass


class _RawStdin:
    """os.read on the descriptor. A daemon thread blocked in the buffered sys.stdin reader holds its lock, and
    CPython aborts at shutdown when it finds that lock taken (seen 2026-10-03 as exit -6 after a clean stop)."""

    def __init__(self, fd: int) -> None:
        self.fd = fd

    def read(self, n: int) -> bytes:
        return os.read(self.fd, n)


def _watch_parent(stop, stream) -> None:
    """The launcher holds our stdin open; it reads EOF only when the launcher is gone. Then we stop too."""
    try:
        while stream.read(1):
            pass
    except (OSError, ValueError):
        pass
    stop.set()


def _sleep(stop, seconds: float, beat: Callable[[], None] | None = None) -> bool:
    """Wait in one-second slices so a stop signal is seen promptly on every platform; beat at least every minute
    (audit M3: a long --every must not look like a hang). True: stop."""
    deadline = time.monotonic() + seconds
    next_beat = time.monotonic() + 60
    while time.monotonic() < deadline:
        if stop.wait(min(1.0, max(0.0, deadline - time.monotonic()))):
            return True
        if beat is not None and time.monotonic() >= next_beat:
            beat()
            next_beat = time.monotonic() + 60
    return stop.is_set()


def minutes(value: str) -> float:
    """--every: a finite number of minutes in (0, 1440] (audit L3: 0, negative or NaN would spin or never stop)."""
    try:
        n = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number of minutes")
    if not (0 < n <= 1440):  # also false for NaN
        raise argparse.ArgumentTypeError(f"--every must be more than 0 and at most 1440 minutes, not {value}")
    return n


def main(argv: list[str] | None = None) -> int:
    import threading

    from core import instance_lock

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--every", type=minutes, default=None,
                        help="scheduler: every N minutes run the agents that are due (each agent has its own clock)")
    parser.add_argument("--parent-watch", action="store_true", help=argparse.SUPPRESS)  # set by tools.start_atlas
    args = parser.parse_args(argv)
    directory = runner_dir()
    try:
        instance_lock.acquire(directory)
    except instance_lock.InstanceLockHeldError:
        print("Ajanlar zaten çalışıyor (başka bir ajan çalıştırıcısı açık; örneğin tools.start_atlas). "
              "İkincisi başlatılmadı: aynı anda iki çalıştırıcı kayıt numaralarında çakışırdı.")
        return ALREADY_RUNNING_EXIT
    except instance_lock.InstanceLockUnavailableError as exc:
        print(f"Ajan kilidi açılamadı ({exc}); kilitsiz çalışılmaz.")
        return LOCK_UNAVAILABLE_EXIT
    try:
        if not args.every:
            out = run_cycle(cli.RECORDS_DIR, agents=AGENTS)
            _print_cycle(out)
            return 0 if all(r["verdict"] != "FAIL" for r in out["results"]) else 1
        stop = threading.Event()
        previous = _install_stop_signals(stop)
        if args.parent_watch:
            threading.Thread(target=_watch_parent, args=(stop, _RawStdin(sys.stdin.fileno())), daemon=True,
                             name="atlas-agents-parent-watch").start()
        print(f"Ajanlar kendi saatleriyle çalışıyor: her {args.every:g} dakikada sırası gelenler "
              "(durdurmak için Ctrl+C; Atlas etkilenmez)", flush=True)
        try:
            while not stop.is_set():
                _beat(directory)
                out = run_scheduled(cli.RECORDS_DIR, agents=AGENTS, should_stop=stop.is_set,
                                    beat=lambda: _beat(directory))
                if out["results"]:
                    _print_cycle(out)
                if out.get("schedule_save_failed"):
                    print("UYARI: ajan zamanlaması kaydedilemedi (disk / izin?); ajanlar her turda yeniden çalışabilir")
                sys.stdout.flush()
                if _sleep(stop, args.every * 60, beat=lambda: _beat(directory)):
                    break
        finally:
            _restore_signals(previous)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        instance_lock.release(directory)


if __name__ == "__main__":
    raise SystemExit(main())
