"""S1 step 2: the risk bucket each open position was admitted under (owner approved option B, 2026-10-01).

An append-only sidecar keyed by position_id. The financial state file and its
schema are untouched (proposals/2026-10-01_s1_step2_risk_bucket_persistence_DESIGN.md).

Fail-closed reading: a position with no record, with records that disagree,
or any unreadable file reads as UNKNOWN (None). The risk engine counts
UNKNOWN against the smallest sleeve, so missing evidence can only refuse
more, never less (NB-4 principle). Nothing is ever guessed or backfilled.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

POSITION_RISK_BUCKETS_FILE = "position_risk_buckets.jsonl"
VALID_BUCKETS = frozenset({"LOW", "MEDIUM", "HIGH"})


class PositionRiskBucketStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.corrupt = False

    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)  # a truncated or garbled line raises: the caller fails closed
            if not isinstance(row, dict):
                raise ValueError("row is not an object")
            rows.append(row)
        return rows

    def buckets(self) -> dict[str, str | None]:
        """position_id -> bucket, or None when the records disagree. Unreadable file -> {} (all UNKNOWN)."""
        try:
            rows = self._read()
        except (OSError, ValueError):
            self.corrupt = True
            return {}
        self.corrupt = False
        out: dict[str, str | None] = {}
        for row in rows:
            pid, bucket = str(row.get("position_id") or ""), str(row.get("risk_bucket") or "").upper()
            if not pid:
                continue
            if bucket not in VALID_BUCKETS or (pid in out and out[pid] != bucket):
                out[pid] = None
            else:
                out.setdefault(pid, bucket)
        return out

    def record(self, position_id: str, risk_bucket: str) -> bool:
        """Append one record. An identical record already present is a no-op (idempotent)."""
        pid, bucket = str(position_id or "").strip(), str(risk_bucket or "").strip().upper()
        if not pid or bucket not in VALID_BUCKETS:
            return False
        current = self.buckets()
        if self.corrupt:
            return False  # never append to a file we cannot read
        if pid in current and current[pid] == bucket:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"position_id": pid, "risk_bucket": bucket,
                           "recorded_at": datetime.now(timezone.utc).isoformat()}, sort_keys=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return True

    def lookup(self, position_id: str | None) -> str | None:
        return self.buckets().get(str(position_id or "")) if position_id else None
