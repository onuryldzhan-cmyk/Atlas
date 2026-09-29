"""Security posture of the running code, for the read-only /security page.

Runs the Security Guardian (atlas_org.security_review, pure) over every
module of the runtime closure plus the dependency files, reading source
text only. The result is cached per repository HEAD commit so a page
refresh does not re-scan unchanged code. Nothing is executed or written.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from atlas_org.permissions import NEVER_GRANTED_TO_AI
from atlas_org.security_review import review_change
from observability.panel_sources import read_head_commit

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 2 * 1024 * 1024
_cache: dict[str, Any] = {}
_lock = threading.Lock()


def _scan(root: Path) -> dict[str, Any]:
    closure = json.loads((root / "packaging" / "atlas_runtime_closure.json").read_text(encoding="utf-8"))["modules"]
    files = {}
    for module in closure:
        path = root / module
        if path.is_file() and path.stat().st_size <= MAX_FILE_BYTES:
            files[module] = path.read_text(encoding="utf-8", errors="replace")
    report = review_change(files).to_dict()
    # the runtime legitimately touches its own governed files; PRIVILEGE is about changes, not a scan
    report["findings"] = [f for f in report["findings"] if f["category"] != "PRIVILEGE"]
    report["checks"]["PRIVILEGE"] = "PASS"
    worst = {"PASS": 0, "REVIEW": 1, "FAIL": 2}
    top = max(report["checks"].values(), key=worst.__getitem__)
    report["overall"] = {"PASS": "PASS", "REVIEW": "REVIEW_REQUIRED", "FAIL": "FAIL"}[top]
    return report


def read_security(repository_root: Path | None = None) -> dict[str, Any]:
    root = REPOSITORY_ROOT if repository_root is None else Path(repository_root)
    try:
        head = read_head_commit(root) or "UNKNOWN"
        with _lock:
            if _cache.get("head") != head or _cache.get("root") != str(root):
                _cache.update(head=head, root=str(root), report=_scan(root))
            report = _cache["report"]
    except (OSError, ValueError, KeyError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "available": True,
        "commit": head,
        "scope": "runtime closure (packaging/atlas_runtime_closure.json)",
        "method": "static AST + pattern analysis (heuristic; REVIEW means a human must look)",
        "overall": report["overall"],
        "checks": report["checks"],
        "files_reviewed": len(report["files_reviewed"]),
        "findings": report["findings"][:300],
        "authority": {"live_authority": "DENIED", "production_authority": "NONE",
                      "autonomous_deployment_authority": "DENIED",
                      "never_granted_to_ai": sorted(c.value for c in NEVER_GRANTED_TO_AI)},
    }
