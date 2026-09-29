"""Agent cycle: run every rule-based Atlas agent in turn and record what each one did.

  python -m tools.agent_cycle                 # one cycle
  python -m tools.agent_cycle --every 60      # repeat every 60 minutes (Ctrl+C stops it; Atlas is unaffected)

Runs next to Atlas on the owner machine and never touches the runtime, the
execution path or money. Each agent reads real evidence and writes only
through the governed logs (memory records, tasks, proposals):

  quant_research        performance report over the closed-position archive -> memory (only when new trades closed)
  strategy_lab          evidence-backed proposals from what the trades taught -> proposals (owner decides)
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


def _last_recorded_trades(records_dir: Path) -> int | None:
    from atlas_org import memory_records

    records = memory_records.replay(cli.read_log(records_dir / cli.MEMORY_LOG)) if (records_dir / cli.MEMORY_LOG).exists() else {}
    counts = [json.loads(r["body"]).get("total", {}).get("trades") for r in records.values()
              if r["author"] == "quant_research" and r["type"] == "EXPERIMENTS" and r["body"].startswith("{")]
    return counts[-1] if counts else None


def quant_research(records_dir: Path) -> dict[str, Any]:
    from tools.exp001_report import load_closed
    from tools.performance_report import analyse

    report = analyse(load_closed(_archive_path()))
    n = report["total"].get("trades", 0)
    if n == _last_recorded_trades(records_dir):
        return {"verdict": "OK", "summary": f"{n} işlem; yeni kapanan işlem yok, rapor tekrar yazılmadı"}
    existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)}
    cli.add_memory_record(records_dir, {
        "record_id": f"PR-{len(existing) + 1:04d}", "type": "EXPERIMENTS", "authority": "RESEARCH",
        "title": f"Performans raporu: {n} işlem", "body": json.dumps(report, ensure_ascii=False)[:20000],
        "author": "quant_research", "source": "tools/agent_cycle.py (performance_report)"})
    return {"verdict": "OK", "summary": f"{n} işlem analiz edildi ve hafızaya yazıldı; dersler: {report['lessons'][0]}"}


def strategy_lab(records_dir: Path) -> dict[str, Any]:
    from tools.exp001_report import load_closed
    from tools.performance_report import analyse
    from tools.strategy_agent import file_proposals

    out = file_proposals(analyse(load_closed(_archive_path())), records_dir, apply=True)
    filed = ", ".join(f["id"] for f in out["filed"]) or "yok"
    return {"verdict": "OK", "summary": f"yeni öneri: {filed}; açık olduğu için tekrar edilmeyen: {len(out['skipped_open'])}"}


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


AGENTS: tuple[tuple[str, str, Callable[[Path], dict[str, Any]]], ...] = (
    ("quant_research", "Performans analizi", quant_research),
    ("strategy_lab", "Strateji önerileri", strategy_lab),
    ("executive_assistant", "Öz-değerlendirme", executive_assistant),
    ("data_quality", "Veri sağlığı", data_quality),
    ("security", "Güvenlik taraması", security),
)


def run_cycle(records_dir: Path = cli.RECORDS_DIR, agents=AGENTS) -> dict[str, Any]:
    results = []
    for unit, name, fn in agents:
        started = time.monotonic()
        try:
            outcome = fn(records_dir)
        except Exception as exc:  # one agent failing never stops the others
            outcome = {"verdict": "FAIL", "summary": f"{type(exc).__name__}: {exc}"[:300]}
        results.append({"unit": unit, "name": name, **outcome, "seconds": round(time.monotonic() - started, 2)})
    existing = {r["record_id"] for r in cli.read_log(records_dir / cli.MEMORY_LOG)} if (records_dir / cli.MEMORY_LOG).exists() else set()
    rid = f"AC-{len(existing) + 1:04d}"
    ok = sum(1 for r in results if r["verdict"] == "OK")
    cli.add_memory_record(records_dir, {
        "record_id": rid, "type": "OPERATIONS", "authority": "TEMPORARY",
        "title": f"Ajan döngüsü: {ok}/{len(results)} ajan sorunsuz",
        "body": json.dumps({"agent_cycle": results}, ensure_ascii=False),
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
