"""Canonical Phase-4 LONG-only execution/position/portfolio foundation.

External execution determination remains owned by the transaction journal and
reconciliation.  This module consumes confirmed evidence; it never retries an
exchange operation and never claims filesystem atomicity is exchange atomicity.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from typing import Any, Callable

from core.execution_models import ExecutionResult

D = Decimal
SCHEMA_VERSION = 1


def _decimal(value: Any, name: str, *, allow_zero: bool = True) -> Decimal:
    if isinstance(value, float):
        raise ValueError(f"{name} must not be float")
    try:
        result = D(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise ValueError(f"invalid {name}")
    return result


def _utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class LongPosition:
    position_id: str
    symbol: str
    base_quantity: Decimal
    cost_quote: Decimal
    entry_fees: Decimal
    average_entry_price: Decimal
    mark_price: Decimal
    version: int
    opened_at: str

    def to_dict(self) -> dict[str, Any]:
        return {name: (format(value, "f") if isinstance(value, D) else value)
                for name, value in asdict(self).items()}


class FinancialStateStore:
    """Atomic JSON state store; missing/corrupt state is never healthy-empty."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def initialize(self, initial_cash: Decimal) -> None:
        if self.path.exists():
            raise FileExistsError(self.path)
        self.save({
            "schema_version": SCHEMA_VERSION, "transition": None,
            "cash": format(initial_cash, "f"), "reserved_capital": "0",
            "realized_gross_pnl": "0", "fees": "0", "positions": {},
            "closed_positions": {}, "applied_executions": {},
        })

    def load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("FINANCIAL_STATE_RECOVERY_REQUIRED") from exc
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError("FINANCIAL_STATE_RECOVERY_REQUIRED")
        if payload.get("transition") is not None:
            raise RuntimeError("FINANCIAL_TRANSITION_RECOVERY_REQUIRED")
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, self.path)


class ExecutionPortfolioFoundation:
    """Idempotent durable LONG lifecycle and portfolio accounting."""
    def __init__(self, store: FinancialStateStore):
        self.store = store
        self._recovery_reason: str | None = None
        try:
            self._state = store.load()
            self._validate_state(self._state)
        except Exception as exc:
            self._state = {}
            self._recovery_reason = str(exc) or "FINANCIAL_STATE_RECOVERY_REQUIRED"

    @property
    def ready(self) -> bool:
        return self._recovery_reason is None

    def _require_ready(self) -> None:
        if not self.ready:
            raise RuntimeError(self._recovery_reason)

    @staticmethod
    def _validate_state(state: dict[str, Any]) -> None:
        for name in ("cash", "reserved_capital", "realized_gross_pnl", "fees"):
            value = D(str(state[name]))
            if not value.is_finite() or (name != "realized_gross_pnl" and value < 0):
                raise ValueError("CORRUPT_FINANCIAL_STATE")
        seen: set[str] = set()
        for symbol, item in state["positions"].items():
            if symbol in seen or item["symbol"] != symbol or item["position_id"] in seen:
                raise ValueError("DUPLICATE_POSITION_STATE")
            seen.update((symbol, item["position_id"]))
            for name in ("base_quantity", "cost_quote", "entry_fees", "average_entry_price", "mark_price"):
                _decimal(item[name], name, allow_zero=name == "entry_fees")

    def set_reserved_capital(self, value: Decimal) -> None:
        self._require_ready()
        candidate = dict(self._state)
        candidate["reserved_capital"] = format(_decimal(value, "reserved_capital"), "f")
        if self.available_capital(candidate) < 0:
            raise ValueError("NEGATIVE_AVAILABLE_CAPITAL")
        self.store.save(candidate); self._state = candidate

    def apply_confirmed(self, result: ExecutionResult, *, risk_authorized: bool,
                        reservation_confirmed: bool, expected_position_version: int | None = None,
                        before_final_persist: Callable[[], None] | None = None) -> dict[str, Any]:
        self._require_ready()
        if not risk_authorized or not reservation_confirmed:
            raise PermissionError("RISK_AND_RESERVATION_REQUIRED")
        result.validate_financial_evidence(position_mutation=True)
        assert result.execution_id and result.position_id and result.symbol and result.action
        prior = self._state["applied_executions"].get(result.execution_id)
        identity = result.idempotency_key
        if prior:
            if prior != identity:
                raise ValueError("EXECUTION_IDENTITY_CONFLICT")
            return self.snapshot(replayed=True)
        if identity in self._state["applied_executions"].values():
            raise ValueError("IDEMPOTENCY_IDENTITY_CONFLICT")

        transition = dict(self._state)
        transition["transition"] = {"execution_id": result.execution_id, "idempotency_key": identity,
                                    "stage": "CONFIRMED_EXECUTION"}
        self.store.save(transition)
        try:
            candidate = json.loads(json.dumps(self._state))
            if result.action == "BUY":
                self._open(candidate, result, expected_position_version)
            elif result.action == "SELL":
                self._close(candidate, result, expected_position_version)
            else:
                raise ValueError("LONG_ONLY_ACTION_REJECTED")
            candidate["applied_executions"][result.execution_id] = identity
            candidate["transition"] = None
            self._validate_state(candidate)
            if before_final_persist:
                before_final_persist()
            self.store.save(candidate)
        except Exception:
            self._recovery_reason = "FINANCIAL_TRANSITION_RECOVERY_REQUIRED"
            raise
        self._state = candidate
        return self.snapshot()

    def _open(self, state: dict[str, Any], result: ExecutionResult, expected: int | None) -> None:
        assert result.symbol and result.position_id and result.execution_price
        assert result.filled_base_quantity is not None and result.filled_quote_notional is not None
        current = state["positions"].get(result.symbol)
        if current is not None:
            if current["position_id"] != result.position_id:
                raise ValueError("DUPLICATE_OPEN_POSITION")
            if expected is None or expected != current["version"]:
                raise ValueError("STALE_POSITION_MUTATION")
            base = D(current["base_quantity"]) + result.filled_base_quantity
            cost = D(current["cost_quote"]) + result.filled_quote_notional
            version = current["version"] + 1
            opened_at = current["opened_at"]
            fees = D(current["entry_fees"]) + result.fee_amount
        else:
            if expected not in (None, 0): raise ValueError("STALE_POSITION_MUTATION")
            base, cost, version, opened_at, fees = (result.filled_base_quantity,
                result.filled_quote_notional, 1, _utc(str(result.timestamp)), result.fee_amount)
        debit = result.filled_quote_notional + result.fee_amount
        cash = D(state["cash"])
        if debit > cash: raise ValueError("INSUFFICIENT_CASH")
        if cash - debit < D(state["reserved_capital"]):
            raise ValueError("NEGATIVE_AVAILABLE_CAPITAL")
        state["cash"] = format(cash - debit, "f")
        state["fees"] = format(D(state["fees"]) + result.fee_amount, "f")
        state["positions"][result.symbol] = {
            "position_id": result.position_id, "symbol": result.symbol,
            "base_quantity": format(base, "f"), "cost_quote": format(cost, "f"),
            "entry_fees": format(fees, "f"), "average_entry_price": format(cost / base, "f"),
            "mark_price": format(result.execution_price, "f"), "version": version, "opened_at": opened_at,
        }

    def _close(self, state: dict[str, Any], result: ExecutionResult, expected: int | None) -> None:
        assert result.symbol and result.position_id
        assert result.filled_base_quantity is not None and result.filled_quote_notional is not None
        current = state["positions"].get(result.symbol)
        if current is None or current["position_id"] != result.position_id:
            raise ValueError("POSITION_NOT_FOUND")
        if expected is None or expected != current["version"]:
            raise ValueError("STALE_POSITION_MUTATION")
        held = D(current["base_quantity"])
        if result.filled_base_quantity != held:
            raise ValueError("PARTIAL_CLOSE_DEFERRED")
        gross = result.filled_quote_notional - D(current["cost_quote"])
        state["cash"] = format(D(state["cash"]) + result.filled_quote_notional - result.fee_amount, "f")
        state["fees"] = format(D(state["fees"]) + result.fee_amount, "f")
        state["realized_gross_pnl"] = format(D(state["realized_gross_pnl"]) + gross, "f")
        closed = dict(current); closed.update({"status": "CLOSED", "base_quantity": "0",
            "exit_price": format(result.execution_price, "f"), "gross_pnl": format(gross, "f"),
            "closed_at": _utc(str(result.timestamp)), "version": current["version"] + 1})
        state["closed_positions"][result.position_id] = closed
        del state["positions"][result.symbol]

    def mark(self, symbol: str, price: Decimal) -> None:
        self._require_ready(); value = _decimal(price, "mark_price", allow_zero=False)
        if symbol not in self._state["positions"]: raise KeyError(symbol)
        candidate = json.loads(json.dumps(self._state)); candidate["positions"][symbol]["mark_price"] = format(value, "f")
        self.store.save(candidate); self._state = candidate

    @staticmethod
    def available_capital(state: dict[str, Any]) -> Decimal:
        return D(state["cash"]) - D(state["reserved_capital"])

    def snapshot(self, *, replayed: bool = False) -> dict[str, Any]:
        self._require_ready()
        exposure = sum((D(p["base_quantity"]) * D(p["mark_price"]) for p in self._state["positions"].values()), D("0"))
        unrealized = sum((D(p["base_quantity"]) * D(p["mark_price"]) - D(p["cost_quote"]) for p in self._state["positions"].values()), D("0"))
        cash, fees = D(self._state["cash"]), D(self._state["fees"])
        return {"ready": True, "recovery_required": False, "cash": cash,
            "reserved_capital": D(self._state["reserved_capital"]),
            "committed_capital": sum((D(p["cost_quote"]) for p in self._state["positions"].values()), D("0")),
            "gross_exposure": exposure, "realized_gross_pnl": D(self._state["realized_gross_pnl"]),
            "fees": fees, "realized_net_pnl": D(self._state["realized_gross_pnl"]) - fees,
            "unrealized_pnl": unrealized, "equity": cash + exposure,
            "available_capital": self.available_capital(self._state),
            "positions": json.loads(json.dumps(self._state["positions"])), "replayed": replayed}

    def diagnostics(self) -> dict[str, Any]:
        if not self.ready: return {"ready": False, "recovery_required": True, "reason": self._recovery_reason}
        snap = self.snapshot()
        return {key: snap[key] for key in ("ready", "recovery_required", "cash", "reserved_capital",
            "gross_exposure", "realized_gross_pnl", "realized_net_pnl", "unrealized_pnl", "fees", "equity")}
