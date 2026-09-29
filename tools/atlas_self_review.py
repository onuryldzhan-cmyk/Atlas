"""Atlas self-review: the organization inspects Atlas and files improvement tasks.

  python -m tools.atlas_self_review            # show what would be filed (dry run)
  python -m tools.atlas_self_review --apply    # file the tasks + one memory record

Owner request 2026-09-29: agents should work on improving Atlas and
themselves. CLAUDE.md rule 6 bounds it: self-improvement never becomes
uncontrolled self-modification. So this tool only OBSERVES and PROPOSES:

* every finding comes from real evidence already in the repository -
  the CODE-001 code-health measurement, the Security Guardian over the
  runtime closure, the saved telemetry summary, the saved test-results
  artifact, and the task log (blocked / failed agent work);
* each finding becomes a task through the Atlas Manager (``request_task``),
  so the same classification, owner-only refusals and permission-checked
  routing apply; nothing is edited, applied or approved here;
* an open task with the same request is never filed twice;
* one TEMPORARY memory record summarises the run (never authoritative).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from atlas_org import tasks as task_log
from atlas_org.security_review import review_change
from tools import atlas_org_cli as cli
from tools.code_health_report import measure

ROOT = Path(__file__).resolve().parents[1]
MAX_PER_SOURCE = 3
CYCLE_P95_LIMIT_S = 10.0


def _closure() -> list[str]:
    return json.loads((ROOT / "packaging" / "atlas_runtime_closure.json").read_text(encoding="utf-8"))["modules"]


def code_health_findings() -> list[dict[str, Any]]:
    health = measure(ROOT)
    out = []
    for item in sorted(health["long_functions"])[:MAX_PER_SOURCE]:
        out.append({"source": "code_health", "evidence": item,
                    "request": f"refactor {item} (over 300 lines) into smaller tested functions"})
    for item in health["bare_except"][:MAX_PER_SOURCE]:
        out.append({"source": "code_health", "evidence": item,
                    "request": f"fix bare except in {item}: catch specific errors"})
    return out


def security_findings() -> list[dict[str, Any]]:
    files = {}
    for module in _closure():
        path = ROOT / module
        if path.is_file():
            files[module] = path.read_text(encoding="utf-8", errors="replace")
    report = review_change(files)
    worst: dict[str, list[dict[str, Any]]] = {}
    for f in report.findings:
        if f.level == "FAIL" and f.category != "PRIVILEGE":
            worst.setdefault(f.path, []).append(f.to_dict())
    return [{"source": "security_guardian", "evidence": items[:5],
             "request": f"güvenlik incelemesi: {path} ({len(items)} FAIL bulgu)"}
            for path, items in sorted(worst.items())[:MAX_PER_SOURCE]]


def performance_findings() -> list[dict[str, Any]]:
    path = ROOT / "reports" / "observability" / "telemetry_summary.json"
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
        summary = json.loads(text)
    except (OSError, ValueError):
        return []
    p95 = (((summary.get("cycle_duration_seconds") or summary.get("cycle_duration") or {}) or {}).get("p95"))
    if isinstance(p95, (int, float)) and p95 > CYCLE_P95_LIMIT_S:
        return [{"source": "telemetry", "evidence": {"cycle_p95_s": p95, "limit_s": CYCLE_P95_LIMIT_S},
                 "request": f"performans: market loop döngüsü yavaş (p95 {p95:.1f} sn > {CYCLE_P95_LIMIT_S} sn), ölç ve darboğazı bul"}]
    return []


def test_findings() -> list[dict[str, Any]]:
    path = ROOT / "reports" / "observability" / "test_results.junit.xml"
    if not path.is_file():
        return []
    from observability.panel_sources import read_head_commit

    try:
        meta = json.loads((path.parent / "test_results.meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not meta.get("commit") or meta.get("commit") != read_head_commit(ROOT):
        return []  # stale evidence from another commit is not a finding
    import xml.etree.ElementTree as ElementTree

    try:
        tree = ElementTree.parse(path)
    except ElementTree.ParseError:
        return []
    from tools.ci_check_known_accepted_failures import B2_TEST_NAME, D5_TEST_CLASSNAME, D5_TEST_NAME

    def accepted(case) -> bool:  # B2 (v4.63) and D5 (v4.97) are permanently accepted, not work
        return case.get("name") == B2_TEST_NAME or (
            case.get("classname") == D5_TEST_CLASSNAME and case.get("name") == D5_TEST_NAME)

    failed = [f"{case.get('classname')}::{case.get('name')}" for case in tree.iter("testcase")
              if (case.find("failure") is not None or case.find("error") is not None) and not accepted(case)]
    return [{"source": "tests", "evidence": name, "request": f"hata düzelt: başarısız test {name}"}
            for name in failed[:MAX_PER_SOURCE]]


def agent_findings(records: Path) -> list[dict[str, Any]]:
    """The organization reviewing itself: work that got stuck or failed."""

    state = task_log.replay(cli.read_log(records / cli.TASKS_LOG))
    out = []
    for task in state.values():
        blocked = [s for s in task["steps"] if s["status"] == "BLOCKED"]
        failed = [s for s in task["steps"] if (s["result"] or {}).get("verdict") == "FAIL"]
        if task["status"] not in ("DONE", "CANCELLED") and (blocked or failed):
            out.append({"source": "agent_performance", "evidence": {"task": task["id"], "blocked": len(blocked),
                                                                     "failed": len(failed)},
                        "request": f"araştır: {task['id']} görevinde ajan işi takıldı ({len(blocked)} engelli, "
                                   f"{len(failed)} başarısız adım) - süreci iyileştir"})
    for unit, card in sorted(task_log.agent_scorecards(state).items()):
        if card["steps_done"] >= 4 and (card["fail_rate"] or 0) >= 0.5:
            out.append({"source": "agent_performance", "evidence": {"unit": unit, **card},
                        "request": f"araştır: {unit} ajanının başarısızlık oranı %{card['fail_rate'] * 100:.0f} "
                                   f"({card['steps_done']} adım) - çalışma yöntemini iyileştir"})
    return out[:MAX_PER_SOURCE]


def collect(records: Path) -> list[dict[str, Any]]:
    findings = []
    for source in (code_health_findings, security_findings, performance_findings, test_findings):
        findings.extend(source())
    findings.extend(agent_findings(records))
    return findings


def run(records: Path, apply: bool) -> dict[str, Any]:
    findings = collect(records)
    open_requests = {t["request"] for t in task_log.replay(cli.read_log(records / cli.TASKS_LOG)).values()
                     if t["status"] not in ("DONE", "CANCELLED")}
    filed, skipped, refused = [], [], []
    for finding in findings:
        if finding["request"] in open_requests:
            skipped.append(finding["request"])
            continue
        if not apply:
            filed.append({"request": finding["request"], "source": finding["source"]})
            continue
        result = cli.request_task(records, finding["request"])
        (filed if result["created"] else refused).append({**result, "request": finding["request"],
                                                          "source": finding["source"]})
        open_requests.add(finding["request"])
    summary = {"findings": len(findings), "filed": filed, "skipped_duplicates": skipped, "refused": refused,
               "applied": apply}
    if apply and findings:
        existing = {r["record_id"] for r in cli.read_log(records / cli.MEMORY_LOG)}
        rid = f"SR-{len(existing) + 1:04d}"
        cli.add_memory_record(records, {
            "record_id": rid, "type": "OPERATIONS", "authority": "TEMPORARY",
            "title": f"Atlas self-review: {len(filed)} tasks filed",
            "body": json.dumps({k: v for k, v in summary.items() if k != "applied"}, ensure_ascii=False)[:20000],
            "author": "executive_assistant", "source": "tools/atlas_self_review.py"})
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=str(cli.RECORDS_DIR))
    parser.add_argument("--apply", action="store_true", help="file the tasks (default: dry run)")
    args = parser.parse_args(argv)
    try:
        summary = run(Path(args.dir), args.apply)
    except task_log.TaskLogError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.apply:
        print("\nDry run: nothing was written. Add --apply to file these tasks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
