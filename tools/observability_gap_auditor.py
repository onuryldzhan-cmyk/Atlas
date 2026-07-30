from __future__ import annotations
import ast, csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports" / "phase5_observability_gap"

EXCLUDED = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "reports", "_quarantine", "archive_unused_2026-07-22",
}
PREFIXES = ("archive", "backup", "phase1", "phase2", "phase3", "phase4", "phase5")
RUNTIME_PATHS = ("atlas_os/", "atlas_runtime/", "core/", "runtime/")
CLASS_HINTS = (
    "service", "manager", "kernel", "runtime", "registry",
    "scheduler", "controller", "engine", "monitor", "bus",
    "application", "orchestrator",
)
SKIP_SUFFIXES = (
    "error", "exception", "state", "status", "snapshot", "report",
    "result", "record", "identity", "statistics", "configuration",
    "declaration", "observation", "transition", "policy", "type",
    "step", "plan", "event", "metric",
)
LIFECYCLE = {
    "start", "stop", "initialize", "shutdown", "restart",
    "_on_start", "_on_stop", "run", "recover",
    "health", "health_check", "snapshot",
}


def norm(path: Path) -> str:
    return str(path).replace("\\", "/")


def excluded(path: Path) -> bool:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True

    for part in rel.parts:
        low = part.lower()
        if low in EXCLUDED or any(low.startswith(p) for p in PREFIXES):
            return True

    low = norm(rel).lower()
    return (
        low.startswith("tools/")
        or low.startswith("test_")
        or "/test_" in low
        or "/tests/" in f"/{low}/"
    )


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def has_logging(source: str) -> bool:
    low = source.lower()
    return any(x in low for x in (
        "logger.", "logging.", "getlogger(", "structlog"
    ))


def is_dataclass(node: ast.ClassDef) -> bool:
    for d in node.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        if dotted(target).lower().endswith("dataclass"):
            return True
    return False


def is_abstract(node: ast.ClassDef, bases: list[str]) -> bool:
    if any("abc" in b.lower() for b in bases):
        return True
    return any(
        isinstance(n, ast.Name) and n.id == "abstractmethod"
        for n in ast.walk(node)
    )


def priority(name: str, lifecycle: list[str], public_count: int) -> str:
    low = name.lower()
    if lifecycle and any(x in low for x in (
        "kernel", "runtime", "service", "manager", "scheduler", "controller"
    )):
        return "HIGH"
    if lifecycle or public_count >= 3:
        return "MEDIUM"
    return "LOW"


def scan():
    findings = []

    for path in ROOT.rglob("*.py"):
        if excluded(path):
            continue

        rel = norm(path.relative_to(ROOT))

        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError):
            continue

        if has_logging(source):
            continue

        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue

            bases = [dotted(b) for b in node.bases if dotted(b)]
            low_name = node.name.lower()

            if is_dataclass(node) or is_abstract(node, bases):
                continue
            if any(low_name.endswith(x) for x in SKIP_SUFFIXES):
                continue
            if any(b.lower().endswith(("error", "exception", "enum", "strenum")) for b in bases):
                continue

            methods = [
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            lifecycle = sorted(m for m in methods if m.lower() in LIFECYCLE)
            public = sorted(m for m in methods if not m.startswith("_"))

            if not rel.lower().startswith(RUNTIME_PATHS):
                continue
            if not lifecycle and not any(h in low_name for h in CLASS_HINTS):
                continue

            findings.append({
                "priority": priority(node.name, lifecycle, len(public)),
                "file": rel,
                "class": node.name,
                "line": node.lineno,
                "bases": bases,
                "lifecycle_methods": lifecycle,
                "public_methods": public,
                "recommended_logger": f'logging.getLogger("AtlasAI.{node.name}")',
            })

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(findings, key=lambda x: (order[x["priority"]], x["file"], x["line"]))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    findings = scan()

    summary = {
        "actionable_gaps": len(findings),
        "high": sum(x["priority"] == "HIGH" for x in findings),
        "medium": sum(x["priority"] == "MEDIUM" for x in findings),
        "low": sum(x["priority"] == "LOW" for x in findings),
        "gaps": findings,
    }

    (OUT / "observability_gap_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (OUT / "observability_gaps.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "priority", "file", "class", "line", "bases",
            "lifecycle_methods", "public_methods", "recommended_logger",
        ])
        for x in findings:
            w.writerow([
                x["priority"], x["file"], x["class"], x["line"],
                " | ".join(x["bases"]),
                " | ".join(x["lifecycle_methods"]),
                " | ".join(x["public_methods"]),
                x["recommended_logger"],
            ])

    lines = [
        "=" * 72,
        "ATLAS PHASE 5B - ACTIONABLE OBSERVABILITY GAPS",
        "=" * 72,
        f"Actionable gaps : {summary['actionable_gaps']}",
        f"HIGH            : {summary['high']}",
        f"MEDIUM          : {summary['medium']}",
        f"LOW             : {summary['low']}",
        "",
    ]

    if findings:
        lines.append("Top actionable classes:")
        for x in findings[:20]:
            lines.append(f"[{x['priority']}] {x['file']}:{x['line']} -> {x['class']}")
        if len(findings) > 20:
            lines.append(f"... and {len(findings) - 20} additional classes in JSON/CSV.")
    else:
        lines.append("No actionable runtime logging gap was detected.")

    lines += [
        "",
        f"Reports : {OUT}",
        "",
        "PHASE 5B COMPLETED - READ-ONLY AUDIT",
    ]

    text = "\n".join(lines)
    (OUT / "observability_gaps_concise.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
