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

    snap = R.snapshot(symbols or R.load_symbols(), fetch_closes or R.binance_closes)
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
        if not pid.startswith("SA-") or prop.status in P.TERMINAL or prop.status == P.S.APPLIED or pid in done:
            continue
        claims = prop.fields.get("claims") or []
        text = " ".join(str(c.get("evidence", "")) + " " + str(c.get("counter_evidence", "")) for c in claims)
        thin = "INCONCLUSIVE" in text or "below the" in text or "Only " in text
        verdict = "KANIT YETERSİZ" if thin else "KANIT KABUL EDİLEBİLİR"
        body = {"proposal": pid, "verdict": verdict, "min_sample": MIN_SAMPLE,
                "challenge": ("Örnek küçük: önce geçmiş veriyle (replay) test edilmeden çalışma zamanına alınmamalı. "
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


AGENTS: tuple[tuple[str, str, Callable[[Path], dict[str, Any]]], ...] = (
    ("quant_research", "Performans analizi", quant_research),
    ("strategy_lab", "Strateji önerileri", strategy_lab),
    ("market_regime", "Piyasa rejimi", market_regime),
    ("knowledge_manager", "Ders defteri", knowledge_manager),
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
