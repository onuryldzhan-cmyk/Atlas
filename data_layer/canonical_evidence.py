"""Fail-closed adapter from Atlas execution authorities to projection evidence.

The adapter is deliberately read-only.  It performs no exchange operation and
copies only the fields required by the relational projection contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from .contracts import IntegrityViolation
from .projection_replay import ConfirmedExecutionEvidence

_CONFIRMED_STATUSES = frozenset({"PAPER_EXECUTED", "EXECUTED", "COMPLETED", "SUCCESS", "FILLED", "CLOSED"})
_FIELDS = ("request_id", "order_id", "execution_id", "position_id", "symbol", "action", "filled_base_quantity", "filled_quote_notional", "filled_price", "fee_amount", "timestamp")


def _required_text(value: Any, name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise IntegrityViolation(f"canonical evidence missing {name}")
    return text


def _decimal(value: Any, name: str, *, allow_zero: bool = False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise IntegrityViolation(f"canonical evidence has invalid {name}") from exc
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        raise IntegrityViolation(f"canonical evidence has invalid {name}")
    return number


def _same(left: Mapping[str, Any], right: Mapping[str, Any], field: str) -> Any:
    left_value, right_value = left.get(field), right.get(field)
    if left_value is None or right_value is None:
        raise IntegrityViolation(f"canonical evidence missing {field}")
    if str(left_value).strip() != str(right_value).strip():
        raise IntegrityViolation(f"canonical authorities disagree on {field}")
    return left_value


class CanonicalExecutionEvidenceAdapter:
    """Adapt matching COMMITTED journal/idempotency records without I/O."""

    def __init__(self, transaction_journal: Any, idempotency_store: Any) -> None:
        self._journal = transaction_journal
        self._idempotency = idempotency_store

    def __call__(self) -> Iterable[ConfirmedExecutionEvidence]:
        entries = getattr(self._journal, "entries", None)
        completed = getattr(self._idempotency, "completed_requests", None)
        if not isinstance(entries, Mapping) or not isinstance(completed, Mapping):
            raise IntegrityViolation("canonical authority state is unavailable")
        evidence: list[ConfirmedExecutionEvidence] = []
        for request_id in sorted(entries):
            journal_entry = entries[request_id]
            if not isinstance(journal_entry, Mapping):
                raise IntegrityViolation("canonical journal entry is corrupt")
            state = str(journal_entry.get("state", "")).upper()
            if state in {"PREPARED", "COMMIT_STATUS_UNKNOWN"}:
                raise IntegrityViolation("indeterminate execution cannot be replayed")
            if state != "COMMITTED":
                continue
            journal_result = journal_entry.get("result")
            idempotent_result = completed.get(request_id)
            if not isinstance(journal_result, Mapping) or not isinstance(idempotent_result, Mapping):
                raise IntegrityViolation("committed execution lacks both canonical results")
            for result in (journal_result, idempotent_result):
                if result.get("success") is not True:
                    raise IntegrityViolation("committed execution is not explicitly successful")
                if str(result.get("status", "")).upper() not in _CONFIRMED_STATUSES:
                    raise IntegrityViolation("committed execution status is not confirmed")
                if str(result.get("commit_outcome", "")).upper() != "COMMITTED":
                    raise IntegrityViolation("execution outcome is indeterminate")
            if _required_text(request_id, "request_id") != _required_text(_same(journal_result, idempotent_result, "request_id"), "request_id"):
                raise IntegrityViolation("canonical request identity conflicts with authority key")
            values = {field: _same(journal_result, idempotent_result, field) for field in _FIELDS[1:]}
            side = _required_text(values["action"], "action").upper()
            if side != "BUY":
                raise IntegrityViolation("only evidenced LONG opening executions are replayable")
            evidence.append(ConfirmedExecutionEvidence(
                request_id=str(request_id), order_id=_required_text(values["order_id"], "order_id"),
                execution_id=_required_text(values["execution_id"], "execution_id"),
                symbol=_required_text(values["symbol"], "symbol"), side=side,
                base_quantity=_decimal(values["filled_base_quantity"], "filled_base_quantity"),
                filled_quote_notional=_decimal(values["filled_quote_notional"], "filled_quote_notional"),
                price=_decimal(values["filled_price"], "filled_price"),
                fee=_decimal(values["fee_amount"], "fee_amount", allow_zero=True),
                executed_at=_required_text(values["timestamp"], "timestamp"),
                position_id=_required_text(values["position_id"], "position_id"),
                metadata={"provenance": ["ExecutionTransactionJournal", "ExecutionIdempotencyStore", "ExecutionResult"], "authority_request_id": str(request_id)},
            ))
        return tuple(evidence)
