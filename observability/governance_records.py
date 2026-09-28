"""Read-only readers for the proposal and Atlas Memory logs.

They read ``governance/records/*.jsonl`` (written only by
``tools/atlas_org_cli.py``) and replay them through the pure ``atlas_org``
contracts, so every read re-verifies the hash chain and the governance
rules. A missing log is an empty, available state; a corrupted log is
reported unavailable with the reason - never partially shown.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atlas_org import memory_records, permissions, proposals

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RECORDS_RELPATH = "governance/records"
MAX_LOG_BYTES = 16 * 1024 * 1024


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.stat().st_size > MAX_LOG_BYTES:
        raise proposals.ProposalLogError(f"{path.name} exceeds {MAX_LOG_BYTES} bytes")
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise proposals.ProposalLogError(f"{path.name}: last record is truncated")
    try:
        return [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise proposals.ProposalLogError(f"{path.name}: unreadable ({type(exc).__name__})")


def read_proposals(repository_root: Path | None = None) -> dict[str, Any]:
    root = REPOSITORY_ROOT if repository_root is None else Path(repository_root)
    try:
        state = proposals.replay(_load(root / RECORDS_RELPATH / "proposals.jsonl"))
    except proposals.ProposalLogError as exc:
        return {"available": False, "reason": str(exc)}
    items = [p.to_public_dict() for p in state.values()]
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "available": True,
        "counts": counts,
        "awaiting_owner": [i["id"] for i in items if i["status"] == "READY_FOR_OWNER"],
        "proposals": sorted(items, key=lambda i: i["history"][-1]["seq"], reverse=True),
    }


def read_memory(repository_root: Path | None = None) -> dict[str, Any]:
    root = REPOSITORY_ROOT if repository_root is None else Path(repository_root)
    try:
        records = memory_records.replay(_load(root / RECORDS_RELPATH / "memory.jsonl"))
    except proposals.ProposalLogError as exc:
        return {"available": False, "reason": str(exc)}
    return {"available": True, "types": [t.value for t in memory_records.RecordType],
            "records": memory_records.public_view(records)}


def read_permissions() -> dict[str, Any]:
    return {
        "available": True,
        "never_granted_to_ai": sorted(c.value for c in permissions.NEVER_GRANTED_TO_AI),
        "units": permissions.permissions_public(),
    }
