"""
ATLAS PERSISTENT IDEMPOTENCY STORE v1.2

Restart-safe JSON persistence for terminal and indeterminate order outcomes.

Security properties
-------------------
- Atomic file replacement
- Corrupt or unreadable store fails closed
- Expired entries are discarded
- Legacy v1.1 terminal entries are migrated safely
- Pending reconciliation entries block duplicate submission across restarts
- Status output does not expose keys or order payloads
"""

from __future__ import annotations

import json
import math
import os
import time

from pathlib import Path
from typing import Any, Callable, Mapping


class PersistentIdempotencyStore:
    VERSION = "1.2"
    SUPPORTED_VERSIONS = frozenset({"1.1", "1.2"})
    TERMINAL_STATE = "TERMINAL"
    PENDING_STATE = "PENDING_RECONCILIATION"

    def __init__(
        self,
        *,
        path: str | Path,
        ttl_seconds: float,
        max_entries: int,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        self.path = Path(path)
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._time_provider = time_provider if time_provider is not None else time.time
        self.available = True
        self.error_type: str | None = None

    def _now(self) -> float:
        value = float(self._time_provider())
        if not math.isfinite(value):
            raise ValueError("time provider returned a non-finite value")
        return value

    @staticmethod
    def _normalize_fingerprint(value: Any) -> tuple[str, str, float, float, bool] | None:
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 5
            or not isinstance(value[4], bool)
        ):
            return None
        try:
            quantity = float(value[2])
            order_notional = float(value[3])
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(quantity) or not math.isfinite(order_notional):
            return None
        return (str(value[0]), str(value[1]), quantity, order_notional, value[4])

    def load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            self.available = True
            self.error_type = None
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("store root must be an object")
            version = raw.get("version")
            if version not in self.SUPPORTED_VERSIONS:
                raise ValueError("unsupported idempotency store version")
            entries = raw.get("entries", {})
            if not isinstance(entries, dict):
                raise ValueError("entries must be an object")
            now = self._now()
            loaded: dict[str, dict[str, Any]] = {}
            for key, entry in entries.items():
                if not isinstance(key, str) or not isinstance(entry, dict):
                    continue
                fingerprint = self._normalize_fingerprint(entry.get("fingerprint"))
                response = entry.get("response")
                if fingerprint is None or not isinstance(response, dict):
                    continue
                try:
                    expires_at = float(entry.get("expires_at"))
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(expires_at) or expires_at <= now:
                    continue
                state = str(entry.get("state", self.TERMINAL_STATE)).strip().upper()
                if state not in {self.TERMINAL_STATE, self.PENDING_STATE}:
                    continue
                normalized: dict[str, Any] = {
                    "state": state,
                    "fingerprint": fingerprint,
                    "response": response,
                    "expires_at": expires_at,
                }
                if state == self.PENDING_STATE:
                    symbol = entry.get("symbol")
                    client_order_id = entry.get("client_order_id", key)
                    if not isinstance(symbol, str) or not symbol.strip():
                        continue
                    if not isinstance(client_order_id, str) or not client_order_id.strip():
                        continue
                    normalized["symbol"] = symbol.strip().upper()
                    normalized["client_order_id"] = client_order_id.strip()
                loaded[key] = normalized
            self.available = True
            self.error_type = None
            return loaded
        except Exception as exc:
            self.available = False
            self.error_type = type(exc).__name__
            return {}

    def save(self, entries: Mapping[str, Mapping[str, Any]]) -> bool:
        if not self.available:
            return False
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload_entries: dict[str, Any] = {}
            for key, entry in entries.items():
                if not isinstance(key, str):
                    continue
                fingerprint = self._normalize_fingerprint(entry.get("fingerprint"))
                response = entry.get("response")
                if fingerprint is None or not isinstance(response, dict):
                    continue
                state = str(entry.get("state", self.TERMINAL_STATE)).strip().upper()
                if state not in {self.TERMINAL_STATE, self.PENDING_STATE}:
                    continue
                payload_entry: dict[str, Any] = {
                    "state": state,
                    "fingerprint": list(fingerprint),
                    "response": response,
                    "expires_at": float(entry.get("expires_at")),
                }
                if state == self.PENDING_STATE:
                    symbol = entry.get("symbol")
                    client_order_id = entry.get("client_order_id", key)
                    if not isinstance(symbol, str) or not symbol.strip():
                        continue
                    if not isinstance(client_order_id, str) or not client_order_id.strip():
                        continue
                    payload_entry["symbol"] = symbol.strip().upper()
                    payload_entry["client_order_id"] = client_order_id.strip()
                payload_entries[key] = payload_entry
            if len(payload_entries) > self.max_entries:
                payload_entries = dict(list(payload_entries.items())[-self.max_entries:])
            payload = {"version": self.VERSION, "entries": payload_entries}
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary_path, self.path)
            self.available = True
            self.error_type = None
            return True
        except Exception as exc:
            self.available = False
            self.error_type = type(exc).__name__
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def status(self) -> dict[str, Any]:
        return {
            "persistent": True,
            "store_available": self.available,
            "store_error_type": self.error_type,
            "schema_version": self.VERSION,
        }
