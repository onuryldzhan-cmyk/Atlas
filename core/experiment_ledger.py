"""Durable, monotonic admission counter for paper confidence experiments.

Registry v5.17. EXP-001's sample cap used to be restored only by counting
RISK_APPROVED audit events, so anything that removed audit lines (a
rotation, a truncation, a quarantine) could lower the count and silently
re-open admissions. This ledger is a second, independent record: the count
is written *before* an admission is granted, never decreases, and at
startup the larger of the two sources wins.

File: ``<state_root>/experiment_admissions.json`` =
``{"<experiment_id>": {"admissions": <int>, "updated_at": "<iso>"}}``,
replaced atomically (write temp + fsync + os.replace).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

EXPERIMENT_LEDGER_FILE = "experiment_admissions.json"


class ExperimentLedgerError(RuntimeError):
    """The ledger exists but cannot be trusted; the experiment must not run."""


class ExperimentAdmissionLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ExperimentLedgerError(f"experiment ledger unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise ExperimentLedgerError("experiment ledger is not an object")
        return data

    def count(self, experiment_id: str) -> int:
        """Recorded admissions for ``experiment_id`` (0 when absent)."""

        entry = self._read().get(experiment_id)
        if entry is None:
            return 0
        admissions = entry.get("admissions") if isinstance(entry, dict) else None
        if not isinstance(admissions, int) or isinstance(admissions, bool) or admissions < 0:
            raise ExperimentLedgerError(f"experiment ledger entry for {experiment_id} is malformed")
        return admissions

    def record(self, experiment_id: str, admissions: int) -> None:
        """Durably record ``admissions``; never lowers a recorded count."""

        with self._lock:
            data = self._read()
            current = self.count(experiment_id) if experiment_id in data else 0
            data[experiment_id] = {
                "admissions": max(current, int(admissions)),
                "updated_at": datetime.now(UTC).isoformat(),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".json.tmp")
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            # Make the rename itself durable, or a power loss could bring
            # back the previous (lower) count. POSIX only: Windows cannot
            # open a directory for fsync.
            if os.name == "posix":
                directory = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
