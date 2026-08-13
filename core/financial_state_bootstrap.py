"""Explicit operator bootstrap/recovery contract for durable financial state.

Normal application startup treats missing or corrupt durable financial
state as fail-closed: JsonRiskStateStore.load(), CapitalReservationLedger
(via JsonReservationStore.load()), and ExecutionPortfolioFoundation (via
FinancialStateStore.load()) all refuse to fabricate a healthy-empty state
and instead leave the corresponding service not-ready or raise. That is
correct and is unchanged by this module.

This module is the only explicit, operator-invoked path that creates
initial durable financial state. It is never imported or called from
AtlasApplication.__init__ or any other startup path; an operator (or an
operator-run script) must call bootstrap_financial_state() deliberately.

Each of the three underlying stores already refuses to overwrite an
existing file (JsonRiskStateStore.initialize(), JsonReservationStore
.initialize_empty(), FinancialStateStore.initialize() all raise
FileExistsError if the target path exists). This module does not weaken
that guarantee; it never writes to, repairs, or deletes a store that
already has a file on disk.

Existing state, when present, is loaded and validated through each
store's own canonical loader (JsonRiskStateStore.load(),
JsonReservationStore.load() + CapitalReservationLedger.ready,
FinancialStateStore.load() + ExecutionPortfolioFoundation._validate_state)
rather than through a duplicate parser. A file merely existing on disk is
not treated as equivalent to that file being usable: an existing store is
reported VALID_EXISTING only if it loads and validates cleanly against the
policy_version / allocatable_capital the caller supplies, and
INVALID_EXISTING otherwise (corrupt, unreadable, schema-invalid, or
policy/capital-incompatible). Either way the file itself is left
untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from core.capital_reservation import CapitalReservationLedger, JsonReservationStore
from core.execution_portfolio_foundation import (
    ExecutionPortfolioFoundation,
    FinancialStateStore,
)
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState

DEFAULT_RISK_STATE_FILE = "risk_accounting_state.json"
DEFAULT_RESERVATION_STATE_FILE = "capital_reservations.json"
DEFAULT_FINANCIAL_STATE_FILE = "execution_financial_state.json"

_STATE_VALID_EXISTING = "STATE_VALID_EXISTING"
_STATE_ABSENT = "STATE_ABSENT"


class BootstrapOutcome(str, Enum):
    CREATED = "CREATED"
    VALID_EXISTING = "VALID_EXISTING"
    INVALID_EXISTING = "INVALID_EXISTING"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class StoreBootstrapResult:
    store: str
    path: str
    outcome: BootstrapOutcome
    reason_code: str


@dataclass(frozen=True, slots=True)
class FinancialStateBootstrapResult:
    policy_version: str
    initiated_at: str
    results: tuple[StoreBootstrapResult, ...]

    @property
    def succeeded(self) -> bool:
        return all(
            result.outcome in (BootstrapOutcome.CREATED, BootstrapOutcome.VALID_EXISTING)
            for result in self.results
        )

    def result_for(self, store: str) -> StoreBootstrapResult:
        for result in self.results:
            if result.store == store:
                return result
        raise KeyError(store)


def bootstrap_financial_state(
    *,
    state_directory: str | Path,
    initial_capital: Decimal,
    allocatable_capital: Decimal,
    policy_version: str,
    today_utc: date | None = None,
    verify_only: bool = False,
    risk_state_file: str = DEFAULT_RISK_STATE_FILE,
    reservation_state_file: str = DEFAULT_RESERVATION_STATE_FILE,
    financial_state_file: str = DEFAULT_FINANCIAL_STATE_FILE,
) -> FinancialStateBootstrapResult:
    """Explicitly create or validate durable financial state.

    Must be invoked only by an explicit operator/bootstrap command, never
    from application startup. For each of the three canonical stores:

    - absent, successfully created -> CREATED
    - existing, loads and validates against policy_version /
      allocatable_capital -> VALID_EXISTING
    - existing, corrupt / unreadable / schema-invalid / incompatible with
      the supplied policy_version or allocatable_capital -> INVALID_EXISTING
    - bootstrap infrastructure failure while creating fresh state -> FAILED

    An existing file is never overwritten, repaired, or deleted by any of
    these outcomes, including INVALID_EXISTING. `allocatable_capital` is
    the caller's already-computed policy value (e.g. RiskPolicy's), not a
    constant duplicated here.

    With `verify_only=True` nothing is ever created: an absent store is
    reported INVALID_EXISTING/STATE_ABSENT and every present store is still
    validated normally.
    """
    initial_capital = Decimal(str(initial_capital))
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    allocatable_capital = Decimal(str(allocatable_capital))
    if allocatable_capital <= 0:
        raise ValueError("allocatable_capital must be positive")
    if not policy_version:
        raise ValueError("policy_version is required")

    directory = Path(state_directory)
    day = today_utc if today_utc is not None else datetime.now(UTC).date()

    results = [
        _bootstrap_risk_state(
            directory / risk_state_file, initial_capital, policy_version, day,
            verify_only,
        ),
        _bootstrap_reservation_state(
            directory / reservation_state_file, allocatable_capital, verify_only,
        ),
        _bootstrap_financial_state(
            directory / financial_state_file, initial_capital, verify_only,
        ),
    ]

    return FinancialStateBootstrapResult(
        policy_version=policy_version,
        initiated_at=datetime.now(UTC).isoformat(),
        results=tuple(results),
    )


# ---------------------------------------------------------------------------
# risk_accounting_state
# ---------------------------------------------------------------------------


def _classify_risk_state_failure(exc: Exception) -> str:
    if isinstance(exc, (OSError, json.JSONDecodeError)):
        return "RISK_STATE_UNREADABLE"
    message = str(exc)
    if message == "risk policy version mismatch":
        return "POLICY_VERSION_MISMATCH"
    if message == "risk state is from a future UTC day":
        return "RISK_STATE_FUTURE_DAY"
    if message == "unsupported risk-state schema":
        return "RISK_STATE_SCHEMA_INVALID"
    return "RISK_STATE_INVALID"


def _bootstrap_risk_state(
    path: Path, initial_capital: Decimal, policy_version: str, day: date,
    verify_only: bool = False,
) -> StoreBootstrapResult:
    store = JsonRiskStateStore(path)
    if verify_only:
        if not path.exists():
            return StoreBootstrapResult(
                "risk_accounting_state", str(path), BootstrapOutcome.INVALID_EXISTING,
                _STATE_ABSENT,
            )
    else:
        try:
            store.initialize(
                RestoredRiskState(
                    accounting_day_utc=day,
                    realized_daily_pnl=Decimal("0"),
                    peak_equity=initial_capital,
                    current_equity=initial_capital,
                    policy_version=policy_version,
                )
            )
            return StoreBootstrapResult(
                "risk_accounting_state", str(path), BootstrapOutcome.CREATED,
                "BOOTSTRAP_CREATED",
            )
        except FileExistsError:
            pass
        except Exception as exc:
            return StoreBootstrapResult(
                "risk_accounting_state", str(path), BootstrapOutcome.FAILED, str(exc)[:200],
            )

    try:
        store.load(expected_policy_version=policy_version, today_utc=day)
    except Exception as exc:
        return StoreBootstrapResult(
            "risk_accounting_state", str(path), BootstrapOutcome.INVALID_EXISTING,
            _classify_risk_state_failure(exc),
        )
    return StoreBootstrapResult(
        "risk_accounting_state", str(path), BootstrapOutcome.VALID_EXISTING,
        _STATE_VALID_EXISTING,
    )


# ---------------------------------------------------------------------------
# capital_reservations
# ---------------------------------------------------------------------------


def _bootstrap_reservation_state(
    path: Path, allocatable_capital: Decimal, verify_only: bool = False,
) -> StoreBootstrapResult:
    store = JsonReservationStore(path)
    if verify_only:
        if not path.exists():
            return StoreBootstrapResult(
                "capital_reservations", str(path), BootstrapOutcome.INVALID_EXISTING,
                _STATE_ABSENT,
            )
    else:
        try:
            store.initialize_empty()
            return StoreBootstrapResult(
                "capital_reservations", str(path), BootstrapOutcome.CREATED,
                "BOOTSTRAP_CREATED",
            )
        except FileExistsError:
            pass
        except Exception as exc:
            return StoreBootstrapResult(
                "capital_reservations", str(path), BootstrapOutcome.FAILED, str(exc)[:200],
            )

    try:
        reservations = store.load()
    except (OSError, json.JSONDecodeError):
        return StoreBootstrapResult(
            "capital_reservations", str(path), BootstrapOutcome.INVALID_EXISTING,
            "RESERVATION_STATE_UNREADABLE",
        )
    except Exception:
        return StoreBootstrapResult(
            "capital_reservations", str(path), BootstrapOutcome.INVALID_EXISTING,
            "RESERVATION_SCHEMA_INVALID",
        )

    ids = [item.reservation_id for item in reservations]
    if len(set(ids)) != len(ids):
        return StoreBootstrapResult(
            "capital_reservations", str(path), BootstrapOutcome.INVALID_EXISTING,
            "RESERVATION_DUPLICATE_ID",
        )

    # Reuses the canonical ledger's own readiness check rather than
    # re-deriving the encumbered-capital formula here.
    ledger = CapitalReservationLedger(JsonReservationStore(path), allocatable_capital)
    if not ledger.ready:
        return StoreBootstrapResult(
            "capital_reservations", str(path), BootstrapOutcome.INVALID_EXISTING,
            "CAPITAL_MISMATCH",
        )

    return StoreBootstrapResult(
        "capital_reservations", str(path), BootstrapOutcome.VALID_EXISTING,
        _STATE_VALID_EXISTING,
    )


# ---------------------------------------------------------------------------
# execution_financial_state
# ---------------------------------------------------------------------------


def _bootstrap_financial_state(
    path: Path, initial_capital: Decimal, verify_only: bool = False,
) -> StoreBootstrapResult:
    store = FinancialStateStore(path)
    if verify_only:
        if not path.exists():
            return StoreBootstrapResult(
                "execution_financial_state", str(path), BootstrapOutcome.INVALID_EXISTING,
                _STATE_ABSENT,
            )
    else:
        try:
            store.initialize(initial_capital)
            return StoreBootstrapResult(
                "execution_financial_state", str(path), BootstrapOutcome.CREATED,
                "BOOTSTRAP_CREATED",
            )
        except FileExistsError:
            pass
        except Exception as exc:
            return StoreBootstrapResult(
                "execution_financial_state", str(path), BootstrapOutcome.FAILED, str(exc)[:200],
            )

    try:
        payload = store.load()
    except RuntimeError as exc:
        return StoreBootstrapResult(
            "execution_financial_state", str(path), BootstrapOutcome.INVALID_EXISTING,
            str(exc) or "FINANCIAL_STATE_RECOVERY_REQUIRED",
        )

    try:
        # Reuses the canonical portfolio-foundation validator rather than
        # re-deriving positions/cash invariants here.
        ExecutionPortfolioFoundation._validate_state(payload)
    except Exception:
        return StoreBootstrapResult(
            "execution_financial_state", str(path), BootstrapOutcome.INVALID_EXISTING,
            "FINANCIAL_STATE_INVALID",
        )

    return StoreBootstrapResult(
        "execution_financial_state", str(path), BootstrapOutcome.VALID_EXISTING,
        _STATE_VALID_EXISTING,
    )
