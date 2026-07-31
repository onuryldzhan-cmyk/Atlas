"""
ATLAS PERSISTENT IDEMPOTENCY STORE v1.0

Restart-safe JSON persistence for terminal order outcomes.

Security properties
-------------------
- Atomic file replacement
- Corrupt or unreadable store fails closed
- Expired entries are discarded
- Adapter errors are never written by this component
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
    VERSION = "1.0"

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

        self._time_provider = (
            time_provider
            if time_provider is not None
            else time.time
        )

        self.available = True
        self.error_type: str | None = None

    def _now(
        self,
    ) -> float:
        value = float(
            self._time_provider()
        )

        if not math.isfinite(value):
            raise ValueError(
                "time provider returned a non-finite value"
            )

        return value

    def load(
        self,
    ) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            self.available = True
            self.error_type = None
            return {}

        try:
            raw = json.loads(
                self.path.read_text(
                    encoding="utf-8",
                )
            )

            if not isinstance(raw, dict):
                raise ValueError(
                    "store root must be an object"
                )

            entries = raw.get(
                "entries",
                {},
            )

            if not isinstance(entries, dict):
                raise ValueError(
                    "entries must be an object"
                )

            now = self._now()
            loaded: dict[str, dict[str, Any]] = {}

            for key, entry in entries.items():
                if not isinstance(key, str):
                    continue

                if not isinstance(entry, dict):
                    continue

                fingerprint = entry.get(
                    "fingerprint"
                )
                response = entry.get(
                    "response"
                )
                expires_at = entry.get(
                    "expires_at"
                )

                if (
                    not isinstance(fingerprint, list)
                    or len(fingerprint) != 3
                    or not isinstance(response, dict)
                ):
                    continue

                try:
                    normalized_expiry = float(
                        expires_at
                    )
                except (
                    TypeError,
                    ValueError,
                    OverflowError,
                ):
                    continue

                if (
                    not math.isfinite(normalized_expiry)
                    or normalized_expiry <= now
                ):
                    continue

                loaded[key] = {
                    "fingerprint": (
                        str(fingerprint[0]),
                        str(fingerprint[1]),
                        float(fingerprint[2]),
                    ),
                    "response": response,
                    "expires_at": normalized_expiry,
                }

            self.available = True
            self.error_type = None

            return loaded

        except Exception as exc:
            self.available = False
            self.error_type = type(exc).__name__

            return {}

    def save(
        self,
        entries: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        if not self.available:
            return False

        temporary_path = self.path.with_name(
            f"{self.path.name}.tmp"
        )

        try:
            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            payload_entries: dict[str, Any] = {}

            for key, entry in entries.items():
                fingerprint = entry.get(
                    "fingerprint"
                )
                response = entry.get(
                    "response"
                )
                expires_at = entry.get(
                    "expires_at"
                )

                if (
                    not isinstance(key, str)
                    or not isinstance(fingerprint, tuple)
                    or len(fingerprint) != 3
                    or not isinstance(response, dict)
                ):
                    continue

                payload_entries[key] = {
                    "fingerprint": list(
                        fingerprint
                    ),
                    "response": response,
                    "expires_at": float(
                        expires_at
                    ),
                }

            if len(payload_entries) > self.max_entries:
                payload_entries = dict(
                    list(payload_entries.items())[
                        -self.max_entries:
                    ]
                )

            payload = {
                "version": self.VERSION,
                "entries": payload_entries,
            }

            temporary_path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

            os.replace(
                temporary_path,
                self.path,
            )

            self.available = True
            self.error_type = None

            return True

        except Exception as exc:
            self.available = False
            self.error_type = type(exc).__name__

            try:
                temporary_path.unlink(
                    missing_ok=True
                )
            except OSError:
                pass

            return False

    def status(
        self,
    ) -> dict[str, Any]:
        return {
            "persistent": True,
            "store_available": self.available,
            "store_error_type": self.error_type,
        }
