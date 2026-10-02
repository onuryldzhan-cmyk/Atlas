"""Agent cycle: run every rule-based Atlas agent in turn and record what each one did.

  python -m tools.agent_cycle                 # one cycle
  python -m tools.agent_cycle --every 60      # repeat every 60 minutes (Ctrl+C stops it; Atlas is unaffected)

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

One agent failing never stops the others; the failure is recorded. The
whole cycle is one OPERATIONS memory record, which the Agents page shows.
"""

from __future__ import annotations

import argparse
import json
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


def _last_recorded_trades(records_dir: Path) -> int | None:
    from atlas_org import memory_records

    records = memory_records.replay(cli.read_log(records_dir / cli.MEMORY_LOG)) if (records_dir / cli.MEMORY_LOG).exists() else {}
    counts = []
    for r in sorted(records.values(), key=lambda x: x["seq"]):
        if r["author"] != "quant_research" or r["type"] != "EXPERIMENTS":
            continue
        try:
            counts.append(json.loads(r["body"]).get("total", {}).get("trades"))
        except (ValueError, AttributeError):  # an older truncated body is skipped, never fatal
            continue
    return counts[-1] if counts else None


def quant_research(records_dir: Path) -> dict[str, Any]:
    from tools.exp001_report import load_closed
    from tools.performance_report import analyse
    from tools.reality_check import run as reality

    closed = load_closed(_archive_path())
    report = analyse(closed)
    n = report["total"].get("trades", 0)
    if n == _last_recorded_trades(records_dir):
        return {"verdict": "OK", "summary": f"{n} işlem; yeni kapanan işlem yok, rapor tekrar yazılmadı"}
    real = reality(closed, _approvals())
    body = {"total": report["total"], "lessons": report["lessons"], "trader_book": report.get("trader_book"),
            "reality": real}
    existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
    cli.add_memory_record(records_dir, {
        "record_id": f"PR-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
        "title": f"Performans ve gerçeklik raporu: {n} işlem", "body": json.dumps(body, ensure_ascii=False, default=str),
        "author": "quant_research", "source": "tools/agent_cycle.py (performance_report + reality_check)"})
    costs = real["costs"]
    edge = "" if not costs.get("trades") else ("; kenar maliyeti karşılıyor" if costs["edge_covers_costs"] else "; KENAR MALİYETİ KARŞILAMIYOR")
    return {"verdict": "OK", "summary": f"{n} işlem analiz edildi, hafızaya yazıldı; {report['lessons'][0]}{edge}"}


# ---------------------------------------------------------------- AI-001 agents (Claude API)
# Owner choice 2026-10-02. They only ADVISE: a brief or a review is a memory record, never a
# decision. Without a key on the owner's machine they abstain and say so - they never pretend.

_CEO_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["priorities", "cited_records"],
               "properties": {"priorities": {"type": "array", "items": {"type": "string"}},
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
CEO_MIN_GAP_H = 2.5  # spaces the CEO's 5-hour call share instead of spending it in the first cycles
CEO_MIN_EVIDENCE = 3  # fewer evidence records than this: no call (2026-10-02, a 1-record brief invented 5 priorities)


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
    recent = [r for r in _recent_records(records_dir, 200) if r.get("author") not in CEO_IGNORED_AUTHORS][-25:]
    if len(recent) < CEO_MIN_EVIDENCE:
        return {"verdict": "OK", "summary": f"{len(recent)} kanıt kaydı (en az {CEO_MIN_EVIDENCE} gerekir); özet çıkarılmadı"}
    last_ceo = max((str(r.get("created_at") or "") for r in _recent_records(records_dir, 500)
                    if r.get("author") == "ceo_ai"), default="")
    if last_ceo:
        try:
            last_at = datetime.strptime(last_ceo, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            # unreadable timestamp: fail closed, do not spend quota
            return {"verdict": "OK", "summary": "son CEO özetinin zamanı okunamadı; çağrı yapılmadı"}
        age_h = ((now or datetime.now(timezone.utc)) - last_at).total_seconds() / 3600
        if age_h < min_gap_h:
            return {"verdict": "OK", "summary": f"son özet {age_h:.1f} saat önce; {min_gap_h} saat beklenir"}
        if not any(str(r.get("created_at") or "") > last_ceo and r.get("author") != "ceo_ai" for r in recent):
            return {"verdict": "OK", "summary": "son özetten beri yeni kayıt yok; çağrı yapılmadı"}
    ids = {str(r.get("id")) for r in recent}
    prompt = "Recent Atlas records (id | author | title):\n" + "\n".join(
        f"{r.get('id')} | {r.get('author')} | {str(r.get('title') or '')[:160]}" for r in recent) + (
        "\n\nGive at most 5 priorities for the owner today, most important first, in Turkish. "
        "Cite the record ids each priority rests on in cited_records.")
    res = (ask or ai.ask)(_AI_SYSTEM, prompt, _CEO_SCHEMA, ledger=_ai_ledger(), agent="ceo_ai")
    if res.status != "OK":
        return {"verdict": "OK", "summary": f"AI-001 çekimser: {res.reason}"}
    cited = [c for c in res.data.get("cited_records", []) if isinstance(c, str)]
    if not cited or any(c not in ids for c in cited):
        return {"verdict": "OK", "summary": "AI-001 cevabı reddedildi: var olmayan ya da hiç kayıt gösterilmedi (kanıt doğrulaması)"}
    priorities = [str(p)[:300] for p in res.data.get("priorities", [])][:5]
    existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)}
    cli.add_memory_record(records_dir, {
        "record_id": f"CEO-{len(existing) + 1:04d}", "type": "OPERATIONS", "authority": "TEMPORARY",
        "title": f"CEO özeti: {len(priorities)} öncelik (öneri, karar değil)",
        "body": json.dumps({"priorities": priorities, "cited_records": cited, "model": res.model,
                            "cost_usd": str(res.cost_usd)}, ensure_ascii=False),
        "author": "ceo_ai", "source": "tools/agent_cycle.py (ceo_brief, tools/ai_gateway.py)"})
    return {"verdict": "OK", "summary": f"{len(priorities)} öncelik yazıldı ({res.model}, {res.cost_usd:.4f} $)"}


def model_council(records_dir: Path, ask=None) -> dict[str, Any]:
    """Multi-Model Council (org unit): two models review the newest open proposal independently.

    Disagreement is recorded as DISAGREEMENT, never forced into consensus (model_registry.json).
    Each proposal is reviewed once.
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
    pid = todo[0]
    fields = state[pid].fields or {}
    prompt = (f"Proposal {pid}: {fields.get('title')}\nRisk: {fields.get('risk_level') or fields.get('risk')}\n"
              f"Body: {json.dumps(fields, ensure_ascii=False, default=str)[:3000]}"
              "\n\nShould the owner approve it? Answer SUPPORT, OPPOSE or UNSURE with short reasons in Turkish.")
    votes = {}
    for perspective in ai.COUNCIL_PERSPECTIVES:
        system = f"{_AI_SYSTEM} Review independently as a {perspective}."
        res = (ask or ai.ask)(system, prompt, _COUNCIL_SCHEMA, ledger=_ai_ledger(), agent="model_council")
        votes[perspective] = {"verdict": res.data["verdict"], "reasons": [str(x)[:300] for x in res.data["reasons"]][:5]} \
            if res.status == "OK" else {"verdict": "ABSTAIN", "reason": res.reason}
    verdicts = {v["verdict"] for v in votes.values() if v["verdict"] != "ABSTAIN"}
    if not verdicts:
        return {"verdict": "OK", "summary": f"AI-001 çekimser: {next(iter(votes.values())).get('reason')}"}
    outcome = verdicts.pop() if len(verdicts) == 1 else "DISAGREEMENT"
    existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)}
    cli.add_memory_record(records_dir, {
        "record_id": f"MC-{len(existing) + 1:04d}", "type": "OPERATIONS", "authority": "TEMPORARY",
        "title": f"Model konseyi {pid}: {outcome} (tavsiye, onay değil)",
        "body": json.dumps({"votes": votes, "outcome": outcome, "model": ai.DEFAULT_MODEL,
                            "note": "one model, two independent perspectives - not two models"}, ensure_ascii=False),
        "author": "model_council", "related_proposal": pid,
        "source": "tools/agent_cycle.py (model_council, tools/ai_gateway.py)"})
    return {"verdict": "OK", "summary": f"{pid}: {outcome}"}


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
    existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
    summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
    cli.add_memory_record(records_dir, {
        "record_id": f"MR-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
        "title": f"Piyasa rejimi: {summary}",
        "body": json.dumps({"counts": counts, "coins": {k: {"regime": v["regime"]} for k, v in snap.items()}}, ensure_ascii=False),
        "author": "market_regime", "source": "tools/agent_cycle.py (regime_engine)"})
    trend = counts.get("TREND_UP", 0)
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
    """
    import subprocess

    d = research_dir or _research_dir()
    result, marker, seen = d / "strategy_compare_latest.json", d / "strategy_compare.running", d / "strategy_compare.recorded"
    now = now if now is not None else time.time()
    if result.exists() and (not seen.exists() or seen.read_text(encoding="utf-8") != str(result.stat().st_mtime_ns)):
        data = json.loads(result.read_text(encoding="utf-8"))
        nets = {name: [r.get("net_pnl") for r in rows] for name, rows in data.get("table", {}).items()}
        existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
        better = [k for k, v in data.get("verdicts", {}).items() if v == "BETTER"]
        cli.add_memory_record(records_dir, {
            "record_id": f"SC-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
            "title": f"Strateji karşılaştırması: BETTER = {', '.join(better) or 'yok'}",
            "body": json.dumps({"verdicts": data.get("verdicts"), "net_by_window": nets,
                                # full evidence for tools/regime_bar_check (drawdown and trade counts per window)
                                "drawdown_by_window": {name: [r.get("max_drawdown") for r in rows] for name, rows in data.get("table", {}).items()},
                                "closed_by_window": {name: [r.get("closed_trades") for r in rows] for name, rows in data.get("table", {}).items()},
                                "dataset": (data.get("dataset") or {}).get("dataset_sha256"), "finished_at": data.get("finished_at")},
                               ensure_ascii=False, default=str),
            "author": "strategy_lab", "source": "tools/agent_cycle.py (strategy_research, background tools.strategy_compare)"})
        seen.write_text(str(result.stat().st_mtime_ns), encoding="utf-8")
        marker.unlink(missing_ok=True)
        return {"verdict": "OK", "summary": f"karşılaştırma bitti ve hafızaya yazıldı; BETTER: {', '.join(better) or 'yok'}"}
    if marker.exists() and now - marker.stat().st_mtime < RESEARCH_TIMEOUT_H * 3600:
        return {"verdict": "OK", "summary": "karşılaştırma arka planda sürüyor"}
    if result.exists() and now - result.stat().st_mtime < RESEARCH_EVERY_H * 3600:
        return {"verdict": "OK", "summary": "son karşılaştırma 24 saatten yeni; yeniden başlatılmadı"}
    cmd = [sys.executable, "-m", "tools.strategy_compare", "--days", "30", "--windows", "3", "--embargo", "240",
           "--symbols-file", "config/universe_selection.json", "--json", "--output", str(result)]
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
    ("ceo_ai", "CEO özeti (AI-001)", ceo_brief),
    ("model_council", "Model konseyi (AI-001)", model_council),
    ("red_team", "Karşı görüş", red_team),
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


def run_cycle(records_dir: Path = cli.RECORDS_DIR, agents=AGENTS) -> dict[str, Any]:
    results = []
    for unit, name, fn in agents:
        started = time.monotonic()
        try:
            outcome = validate_outcome(fn(records_dir))
        except Exception as exc:  # one agent failing never stops the others
            outcome = {"verdict": "FAIL", "summary": f"{type(exc).__name__}: {exc}"[:300]}
        seconds = round(time.monotonic() - started, 2)
        if seconds > AGENT_BUDGET_S and outcome.get("verdict") == "OK":
            outcome = {**outcome, "verdict": "WARN", "summary": f"süre bütçesi aşıldı ({seconds}s > {AGENT_BUDGET_S:g}s); " + str(outcome.get("summary", ""))}
        results.append({"unit": unit, "name": name, **outcome, "seconds": seconds})
    _open_incidents(records_dir, results)
    existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
    rid = f"AC-{len(existing) + 1:04d}"
    ok = sum(1 for r in results if r["verdict"] == "OK")
    cli.add_memory_record(records_dir, {
        "record_id": rid, "type": "OPERATIONS", "authority": "TEMPORARY",
        "title": f"Ajan döngüsü: {ok}/{len(results)} ajan sorunsuz",
        "body": json.dumps({"agent_cycle": results,
                            "resources": {"total_seconds": round(sum(r["seconds"] for r in results), 2),
                                          "llm_tokens": "N/A (rule-based agents, no model calls)",
                                          "cost": "N/A", "budget_per_agent_s": AGENT_BUDGET_S}}, ensure_ascii=False),
        "author": "executive_assistant", "source": "tools/agent_cycle.py"})
    return {"record_id": rid, "results": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--every", type=float, default=None, help="repeat every N minutes")
    args = parser.parse_args(argv)
    while True:
        out = run_cycle()
        print(f"\n{out['record_id']}  {time.strftime('%Y-%m-%d %H:%M')}")
        for r in out["results"]:
            print(f"  {r['verdict']:<4} {r['name']:<20} {r['summary']}")
        if not args.every:
            return 0 if all(r["verdict"] != "FAIL" for r in out["results"]) else 1
        print(f"sonraki döngü {args.every:g} dakika sonra (durdurmak için Ctrl+C; Atlas etkilenmez)")
        try:
            time.sleep(args.every * 60)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
