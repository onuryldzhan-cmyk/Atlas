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
that guarantee; it turns FileExistsError into a structured ALREADY_EXISTS
result instead of deleting or replacing whatever is already on disk,
whether that existing content is valid or corrupt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path

from core.capital_reservation import JsonReservationStore
from core.execution_portfolio_foundation import FinancialStateStore
from core.risk_state_store import JsonRiskStateStore, RestoredRiskState

DEFAULT_RISK_STATE_FILE = "risk_accounting_state.json"
DEFAULT_RESERVATION_STATE_FILE = "capital_reservations.json"
DEFAULT_FINANCIAL_STATE_FILE = "execution_financial_state.json"


class BootstrapOutcome(str, Enum):
    CREATED = "CREATED"
    ALREADY_EXISTS = "ALREADY_EXISTS"
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
            result.outcome is not BootstrapOutcome.FAILED
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
    policy_version: str,
    today_utc: date | None = None,
    risk_state_file: str = DEFAULT_RISK_STATE_FILE,
    reservation_state_file: str = DEFAULT_RESERVATION_STATE_FILE,
    financial_state_file: str = DEFAULT_FINANCIAL_STATE_FILE,
) -> FinancialStateBootstrapResult:
    """Explicitly create initial durable financial state.

    Must be invoked only by an explicit operator/bootstrap command, never
    from application startup. Idempotent in the sense that calling it
    again against a directory that already has state is safe: each store
    reports ALREADY_EXISTS rather than touching the existing file.
    """
    initial_capital = Decimal(str(initial_capital))
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    if not policy_version:
        raise ValueError("policy_version is required")

    directory = Path(state_directory)
    day = today_utc if today_utc is not None else datetime.now(UTC).date()

    results = [
        _bootstrap_risk_state(
            directory / risk_state_file, initial_capital, policy_version, day,
        ),
        _bootstrap_reservation_state(directory / reservation_state_file),
        _bootstrap_financial_state(directory / financial_state_file, initial_capital),
    ]

    return FinancialStateBootstrapResult(
        policy_version=policy_version,
        initiated_at=datetime.now(UTC).isoformat(),
        results=tuple(results),
    )


def _bootstrap_risk_state(
    path: Path, initial_capital: Decimal, policy_version: str, day: date,
) -> StoreBootstrapResult:
    store = JsonRiskStateStore(path)
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
            "risk_accounting_state", str(path), BootstrapOutcome.CREATED, "BOOTSTRAP_CREATED",
        )
    except FileExistsError:
        return StoreBootstrapResult(
            "risk_accounting_state", str(path), BootstrapOutcome.ALREADY_EXISTS,
            "STATE_FILE_ALREADY_EXISTS",
        )
    except Exception as exc:
        return StoreBootstrapResult(
            "risk_accounting_state", str(path), BootstrapOutcome.FAILED, str(exc)[:200],
        )


def _bootstrap_reservation_state(path: Path) -> StoreBootstrapResult:
    store = JsonReservationStore(path)
    try:
        store.initialize_empty()
        return StoreBootstrapResult(
            "capital_reservations", str(path), BootstrapOutcome.CREATED, "BOOTSTRAP_CREATED",
        )
    except FileExistsError:
        return StoreBootstrapResult(
            "capital_reservations", str(path), BootstrapOutcome.ALREADY_EXISTS,
            "STATE_FILE_ALREADY_EXISTS",
        )
    except Exception as exc:
        return StoreBootstrapResult(
            "capital_reservations", str(path), BootstrapOutcome.FAILED, str(exc)[:200],
        )


def _bootstrap_financial_state(path: Path, initial_capital: Decimal) -> StoreBootstrapResult:
    store = FinancialStateStore(path)
    try:
        store.initialize(initial_capital)
        return StoreBootstrapResult(
            "execution_financial_state", str(path), BootstrapOutcome.CREATED, "BOOTSTRAP_CREATED",
        )
    except FileExistsError:
        return StoreBootstrapResult(
            "execution_financial_state", str(path), BootstrapOutcome.ALREADY_EXISTS,
            "STATE_FILE_ALREADY_EXISTS",
        )
    except Exception as exc:
        return StoreBootstrapResult(
            "execution_financial_state", str(path), BootstrapOutcome.FAILED, str(exc)[:200],
        )
