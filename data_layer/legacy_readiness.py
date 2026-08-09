"""Deterministic, read-only legacy JSON migration readiness scanner."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class LegacyReadinessReport:
    scanned_files: int
    valid_json_files: int
    invalid_json_files: int
    duplicate_content_files: int
    records_observed: int
    files: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": "DRY_RUN_ONLY",
            "source_files_deleted": 0,
            "scanned_files": self.scanned_files,
            "valid_json_files": self.valid_json_files,
            "invalid_json_files": self.invalid_json_files,
            "duplicate_content_files": self.duplicate_content_files,
            "records_observed": self.records_observed,
            "files": list(self.files),
        }


def inspect_legacy_json(paths: list[Path]) -> LegacyReadinessReport:
    results: list[dict[str, Any]] = []
    hashes: set[str] = set()
    valid = invalid = duplicates = records = 0
    for source in sorted((Path(item) for item in paths), key=lambda p: p.as_posix()):
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest().upper()
        duplicate = digest in hashes
        hashes.add(digest)
        if duplicate:
            duplicates += 1
        item: dict[str, Any] = {
            "path": source.as_posix(),
            "sha256": digest,
            "size_bytes": len(raw),
            "duplicate_content": duplicate,
            "valid": False,
            "record_count": 0,
        }
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
            count = len(payload) if isinstance(payload, (list, dict)) else 1
            item.update({"valid": True, "record_count": count})
            valid += 1
            records += count
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            item["error"] = type(exc).__name__
            invalid += 1
        results.append(item)
    return LegacyReadinessReport(
        scanned_files=len(results),
        valid_json_files=valid,
        invalid_json_files=invalid,
        duplicate_content_files=duplicates,
        records_observed=records,
        files=tuple(results),
    )
