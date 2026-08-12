"""Durable Phase-3 accounting state restoration boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RestoredRiskState:
    accounting_day_utc: date
    realized_daily_pnl: Decimal
    peak_equity: Decimal
    current_equity: Decimal
    policy_version: str

    def __post_init__(self) -> None:
        for name in ("realized_daily_pnl", "peak_equity", "current_equity"):
            value = getattr(self, name)
            if isinstance(value, float):
                raise ValueError(f"{name} must not be float")
            try:
                value = value if isinstance(value, Decimal) else Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError(f"invalid {name}") from exc
            if not value.is_finite():
                raise ValueError(f"{name} must be finite")
            if name != "realized_daily_pnl" and value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        if self.peak_equity < self.current_equity:
            raise ValueError("peak equity cannot be below current equity")
        if not self.policy_version:
            raise ValueError("policy_version is required")

    @property
    def drawdown_amount(self) -> Decimal:
        return self.peak_equity - self.current_equity

    @property
    def drawdown_pct(self) -> Decimal:
        return self.drawdown_amount / self.peak_equity

    def to_dict(self) -> dict[str, str]:
        return {"accounting_day_utc": self.accounting_day_utc.isoformat(),
                "realized_daily_pnl": str(self.realized_daily_pnl),
                "peak_equity": str(self.peak_equity), "current_equity": str(self.current_equity),
                "policy_version": self.policy_version}


class JsonRiskStateStore:
    SCHEMA = "atlas-risk-accounting-state-v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self, value: RestoredRiskState) -> None:
        """Create initial durable state. Never overwrites an existing file.

        This is the explicit-bootstrap counterpart to
        JsonReservationStore.initialize_empty() and
        FinancialStateStore.initialize(): callers that need a fresh
        accounting day 0 must construct RestoredRiskState themselves and
        pass it in, rather than this store fabricating one.
        """
        if self.path.exists():
            raise FileExistsError(self.path)
        self.save(value)

    def load(self, *, expected_policy_version: str, today_utc: date) -> RestoredRiskState:
        payload: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema") != self.SCHEMA:
            raise ValueError("unsupported risk-state schema")
        value = RestoredRiskState(
            date.fromisoformat(str(payload["accounting_day_utc"])),
            Decimal(str(payload["realized_daily_pnl"])), Decimal(str(payload["peak_equity"])),
            Decimal(str(payload["current_equity"])), str(payload["policy_version"]),
        )
        if value.policy_version != expected_policy_version:
            raise ValueError("risk policy version mismatch")
        if value.accounting_day_utc > today_utc:
            raise ValueError("risk state is from a future UTC day")
        # An older day is not silently reset by load.  The accounting owner must
        # explicitly invoke rollover and durably save the transition.
        return value

    def save(self, value: RestoredRiskState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {"schema": self.SCHEMA, **value.to_dict()}
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def rollover(self, value: RestoredRiskState, *, today_utc: date,
                 current_equity: Decimal) -> RestoredRiskState:
        if today_utc <= value.accounting_day_utc:
            if today_utc < value.accounting_day_utc:
                raise ValueError("UTC accounting day cannot move backwards")
            return value
        equity = current_equity if isinstance(current_equity, Decimal) else Decimal(str(current_equity))
        # Preserve the historical peak; only daily realized PnL rolls at a
        # deliberate UTC day transition.
        rolled = RestoredRiskState(today_utc, Decimal("0"), max(value.peak_equity, equity),
                                   equity, value.policy_version)
        self.save(rolled)
        return rolled
