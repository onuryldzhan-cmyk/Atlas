"""Read-only, deterministic domain-specific legacy migration dry runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .models import decimal_text, normalize_symbol, utc_text, validate_id


def dry_run_legacy_records(source: Path, domain: str) -> dict[str, Any]:
    raw = source.read_bytes()
    report: dict[str, Any] = {"mode": "DRY_RUN_ONLY", "domain": domain,
        "source_sha256": hashlib.sha256(raw).hexdigest().upper(), "source_size": len(raw),
        "accepted": [], "rejected": [], "database_writes": 0, "source_modified": False}
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        report["migration_state"] = "MIGRATION_BLOCKED"
        report["blocked_reason"] = f"INVALID_JSON:{type(exc).__name__}"
        return report
    records = payload.get(domain) if isinstance(payload, dict) else None
    if isinstance(records, dict):
        records = [dict(value, **({"symbol": key} if "symbol" not in value else {})) for key, value in sorted(records.items()) if isinstance(value, dict)]
    if not isinstance(records, list):
        report["migration_state"] = "MIGRATION_BLOCKED"
        report["blocked_reason"] = "DOMAIN_SCHEMA_AMBIGUOUS"
        return report
    seen: set[str] = set()
    for index, original in enumerate(records):
        try:
            if not isinstance(original, dict):
                raise ValueError("record must be object")
            item = dict(original)
            identity = validate_id(item.get("id") or item.get("order_id") or item.get("execution_id") or item.get("position_id"), "record_id")
            if identity in seen:
                raise ValueError("duplicate id")
            seen.add(identity)
            item["id"] = identity
            item["symbol"] = normalize_symbol(item["symbol"])
            for name in ("quantity", "price", "average_price", "base_quantity", "quote_exposure"):
                if name in item:
                    item[name] = decimal_text(item[name], name, nonnegative=True)
            timestamp = next((item[name] for name in ("created_at", "executed_at", "updated_at", "timestamp") if name in item), None)
            if timestamp is None:
                raise ValueError("timestamp missing")
            item["timestamp"] = utc_text(timestamp)
            report["accepted"].append(item)
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            report["rejected"].append({"index": index, "reason": str(exc)})
    report["accepted"].sort(key=lambda item: item["id"])
    report["migration_state"] = "DRY_RUN_VALIDATED" if not report["rejected"] else "MIGRATION_BLOCKED"
    return report

