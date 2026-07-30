from __future__ import annotations

import ast
import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "reports" / "phase5_runtime_architecture"

EXCLUDED_EXACT = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
    "reports", "_quarantine", "archive_unused_2026-07-22",
}
EXCLUDED_PREFIXES = (
    "archive", "backup", "phase1_backup", "phase2_backup",
    "phase3", "phase4", "phase5", "_archive", "_backup",
)

RUNTIME_HINTS = (
    "runtime", "kernel", "service", "registry", "lifecycle",
    "health", "metric", "scheduler", "event", "shutdown",
    "recovery", "application",
)

LIFECYCLE = {"start", "stop", "restart", "initialize", "shutdown", "close", "_on_start", "_on_stop", "run"}
HEALTH = {"health", "health_check", "get_health", "status", "get_status", "diagnostics", "snapshot", "is_healthy"}
METRICS = {"metrics", "get_metrics", "record_metric", "increment", "observe", "snapshot_metrics"}
RECOVERY = {"recover", "retry", "restart", "reset", "restore", "rollback", "reconnect"}
SHUTDOWN = {"stop", "shutdown", "close", "dispose", "terminate", "_on_stop"}


@dataclass
class ClassRecord:
    file: str
    name: str
    bases: list[str]
    line: int
    methods: list[str]
    lifecycle_methods: list[str]
    health_methods: list[str]
    metric_methods: list[str]
    recovery_methods: list[str]
    shutdown_methods: list[str]
    dependencies: list[str]
    logging: bool
    threading: bool
    async_support: bool
    event_bus_reference: bool


def normalize(path: Path) -> str:
    return str(path).replace("\\", "/")


def excluded(path: Path) -> bool:
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return True

    for part in rel.parts:
        lower = part.lower()
        if lower in EXCLUDED_EXACT:
            return True
        if any(lower.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            return True
    return False


def dotted_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def self_dependencies(class_node: ast.ClassDef) -> list[str]:
    dependencies = set()

    init_node = next(
        (
            node for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "__init__"
        ),
        None,
    )

    if init_node:
        for arg in list(init_node.args.args)[1:]:
            dependencies.add(arg.arg)
        for arg in init_node.args.kwonlyargs:
            dependencies.add(arg.arg)

    for node in ast.walk(class_node):
        if isinstance(node, ast.Assign):
            value = node.value
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            value = node.value
            targets = [node.target]
        else:
            continue

        if value is None:
            continue

        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                name = target.attr.lower()
                if any(hint in name for hint in (
                    "service", "manager", "registry", "event", "metric",
                    "health", "scheduler", "runtime", "kernel", "engine",
                    "client", "provider", "config",
                )):
                    dependencies.add(target.attr)

    return sorted(dependencies)


def analyze() -> tuple[list[dict], list[ClassRecord], list[dict]]:
    files = []
    classes = []
    parse_failures = []

    for path in PROJECT_ROOT.rglob("*.py"):
        if excluded(path):
            continue

        relative = normalize(path.relative_to(PROJECT_ROOT))

        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError) as exc:
            parse_failures.append({"file": relative, "error": str(exc)})
            continue

        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.extend(
                    f"{module}.{alias.name}" if module else alias.name
                    for alias in node.names
                )

        files.append({
            "file": relative,
            "imports": sorted(set(imports)),
        })

        for class_node in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
            methods = [
                n.name for n in class_node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            lower_source = source.lower()

            classes.append(ClassRecord(
                file=relative,
                name=class_node.name,
                bases=[dotted_name(base) for base in class_node.bases if dotted_name(base)],
                line=class_node.lineno,
                methods=sorted(methods),
                lifecycle_methods=sorted(m for m in methods if m.lower() in LIFECYCLE),
                health_methods=sorted(m for m in methods if m.lower() in HEALTH),
                metric_methods=sorted(m for m in methods if m.lower() in METRICS),
                recovery_methods=sorted(m for m in methods if m.lower() in RECOVERY),
                shutdown_methods=sorted(m for m in methods if m.lower() in SHUTDOWN),
                dependencies=self_dependencies(class_node),
                logging=("logger." in lower_source or "logging." in lower_source),
                threading=("threading" in lower_source or "thread(" in lower_source),
                async_support=any(isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(class_node)),
                event_bus_reference=("event_bus" in lower_source or "eventbus" in lower_source),
            ))

    return files, classes, parse_failures


def build_graph(files: list[dict]) -> dict[str, list[str]]:
    graph = defaultdict(set)

    local_roots = {
        path.stem for path in PROJECT_ROOT.glob("*.py")
    } | {
        path.name for path in PROJECT_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    }

    for item in files:
        source_root = item["file"].split("/")[0].replace(".py", "")
        for imported in item["imports"]:
            target = imported.split(".")[0]
            if target in local_roots and target != source_root:
                graph[source_root].add(target)

    return {key: sorted(value) for key, value in sorted(graph.items())}


def find_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    cycles = set()

    def visit(node: str, path: list[str], active: set[str]) -> None:
        if node in active:
            if node in path:
                index = path.index(node)
                cycles.add(tuple(path[index:] + [node]))
            return

        if len(path) > 20:
            return

        active.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            visit(neighbor, path, active)

        path.pop()
        active.remove(node)

    for node in graph:
        visit(node, [], set())

    return [list(item) for item in sorted(cycles)]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    files, classes, parse_failures = analyze()
    runtime_classes = [
        item for item in classes
        if any(
            hint in item.name.lower() or hint in item.file.lower()
            for hint in RUNTIME_HINTS
        )
    ]

    graph = build_graph(files)
    cycles = find_cycles(graph)

    gaps = []

    def add(area: str, severity: str, condition: bool, finding: str, recommendation: str) -> None:
        if condition:
            gaps.append({
                "area": area,
                "severity": severity,
                "finding": finding,
                "recommendation": recommendation,
            })

    add("LIFECYCLE", "HIGH", not any(x.lifecycle_methods for x in runtime_classes),
        "No runtime lifecycle methods detected.",
        "Define explicit initialize/start/stop contracts.")
    add("HEALTH", "HIGH", not any(x.health_methods for x in runtime_classes),
        "No runtime health contract detected.",
        "Provide structured health and readiness results.")
    add("METRICS", "MEDIUM", not any(x.metric_methods for x in runtime_classes),
        "No runtime metrics contract detected.",
        "Standardize counters, timings and snapshots.")
    add("SHUTDOWN", "HIGH", not any(x.shutdown_methods for x in runtime_classes),
        "No graceful shutdown contract detected.",
        "Stop services in reverse dependency order with timeouts.")
    add("RECOVERY", "MEDIUM", not any(x.recovery_methods for x in runtime_classes),
        "No recovery contract detected.",
        "Add bounded retries, backoff and escalation.")
    add("OBSERVABILITY", "MEDIUM", any(not x.logging for x in runtime_classes),
        "One or more runtime classes have no detectable logging.",
        "Use component loggers and lifecycle event logging.")
    add("SOURCE_INTEGRITY", "HIGH", bool(parse_failures),
        f"{len(parse_failures)} Python files could not be parsed.",
        "Repair or quarantine remaining parse failures.")

    roadmap = [
        {"order": 1, "phase": "5B", "title": "Runtime Contract Consolidation"},
        {"order": 2, "phase": "5C", "title": "Dependency Startup and Shutdown Plan"},
        {"order": 3, "phase": "5D", "title": "Health and Diagnostics Standard"},
        {"order": 4, "phase": "5E", "title": "Metrics and Observability"},
        {"order": 5, "phase": "5F", "title": "Graceful Shutdown"},
        {"order": 6, "phase": "5G", "title": "Recovery Policy"},
        {"order": 7, "phase": "5H", "title": "Runtime Integration Tests"},
    ]

    summary = {
        "project_root": str(PROJECT_ROOT),
        "files_scanned": len(files),
        "classes_scanned": len(classes),
        "runtime_relevant_classes": len(runtime_classes),
        "parse_failures": parse_failures,
        "runtime_classes": [asdict(item) for item in runtime_classes],
        "dependency_graph": graph,
        "dependency_cycles": cycles,
        "production_gaps": gaps,
        "recommended_roadmap": roadmap,
        "safety": {
            "source_files_modified": False,
            "atlas_modules_imported": False,
            "services_started": False,
            "exchange_connections_opened": False,
            "secret_values_read": False,
        },
    }

    (OUTPUT_DIR / "runtime_architecture_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (OUTPUT_DIR / "runtime_classes.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.writer(file)
        writer.writerow([
            "file", "class", "bases", "lifecycle", "health",
            "metrics", "shutdown", "recovery", "dependencies",
            "logging", "threading", "async", "event_bus",
        ])
        for item in runtime_classes:
            writer.writerow([
                item.file, item.name, " | ".join(item.bases),
                " | ".join(item.lifecycle_methods),
                " | ".join(item.health_methods),
                " | ".join(item.metric_methods),
                " | ".join(item.shutdown_methods),
                " | ".join(item.recovery_methods),
                " | ".join(item.dependencies),
                item.logging, item.threading, item.async_support,
                item.event_bus_reference,
            ])

    with (OUTPUT_DIR / "production_gaps.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.writer(file)
        writer.writerow(["area", "severity", "finding", "recommendation"])
        for gap in gaps:
            writer.writerow([
                gap["area"], gap["severity"],
                gap["finding"], gap["recommendation"],
            ])

    severity_counts = defaultdict(int)
    for gap in gaps:
        severity_counts[gap["severity"]] += 1

    print("=" * 72)
    print("ATLAS PHASE 5A - PRODUCTION RUNTIME ARCHITECTURE AUDIT")
    print("=" * 72)
    print(f"Project                  : {PROJECT_ROOT}")
    print(f"Python files scanned     : {len(files)}")
    print(f"Classes scanned          : {len(classes)}")
    print(f"Runtime classes detected : {len(runtime_classes)}")
    print(f"Dependency cycles        : {len(cycles)}")
    print(f"Production gaps          : {len(gaps)}")
    print()
    for severity in ("HIGH", "MEDIUM", "LOW"):
        print(f"{severity:<24}: {severity_counts.get(severity, 0)}")
    print()
    print(f"Reports                  : {OUTPUT_DIR}")
    print()
    print("PHASE 5A COMPLETED - READ-ONLY AUDIT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
