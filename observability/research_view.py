"""Read-only list of Atlas research documents (docs/research/*.md) for /research.

Only each file's name, first heading and size are read; bodies are not
served. Research is evidence and proposals, never policy (ADR-0013).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_RELPATH = "docs/research"
MAX_HEAD_BYTES = 4096


def read_research(repository_root: Path | None = None) -> dict[str, Any]:
    root = REPOSITORY_ROOT if repository_root is None else Path(repository_root)
    folder = root / RESEARCH_RELPATH
    if not folder.is_dir():
        return {"available": False, "reason": f"{RESEARCH_RELPATH} missing"}
    docs = []
    for path in sorted(folder.glob("*.md"), reverse=True):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                head = handle.read(MAX_HEAD_BYTES)
        except OSError:
            continue
        title = next((line.lstrip("# ").strip() for line in head.splitlines() if line.startswith("# ")), path.stem)
        docs.append({"file": f"{RESEARCH_RELPATH}/{path.name}", "title": title, "bytes": path.stat().st_size})
    return {"available": True, "documents": docs}
