"""D6 / S4: the composition root must wire the canonical risk services.

This replaces the temporary Package 2A interlock
(``test_composition_root_does_not_wire_risk_services``), which asserted the
deliberately incomplete state that held while M-1 was open. M-1 is closed,
so the contract is now inverted: the live composition root MUST provide
ExecutionManager with the canonical financial-risk service family, and it
must provide exactly one instance of each.

The proof is a black-box construction of the real, unmodified
AtlasApplication composition root (no mocking of core/application.py or
core/execution_manager.py) followed by attribute inspection of the live
ExecutionManager instance it produces.

This test fails if the wiring is removed, if a subclass or look-alike is
substituted for a canonical authority, or if a second reservation ledger
appears in the live runtime graph.
"""

from __future__ import annotations

from pathlib import Path

from core.application import AtlasApplication
from core.capital_reservation import CapitalReservationLedger
from core.execution_portfolio_foundation import ExecutionPortfolioFoundation
from core.risk_engine import RiskEngine
from core.risk_state_store import JsonRiskStateStore


def test_composition_root_wires_canonical_risk_services(
    tmp_path: Path,
) -> None:
    # Constructed against tmp_path, never the default root: a bare
    # AtlasApplication() binds to the real durable state directory and
    # would let a test read - or on any execution path write - the
    # operator's live financial state.
    app = AtlasApplication(state_directory=tmp_path)

    assert type(app.execution.risk_engine) is RiskEngine, (
        "the composition root must wire core.risk_engine.RiskEngine as the "
        "single executable risk admission authority"
    )
    assert type(app.execution.reservation_ledger) is CapitalReservationLedger, (
        "the composition root must wire the canonical CapitalReservationLedger"
    )
    assert type(app.execution.risk_state_store) is JsonRiskStateStore, (
        "the composition root must wire the canonical durable RiskStateStore"
    )
    assert type(app.execution.portfolio_foundation) is ExecutionPortfolioFoundation, (
        "the composition root must wire the canonical ExecutionPortfolioFoundation"
    )


def test_execution_manager_shares_the_composition_root_instances(
    tmp_path: Path,
) -> None:
    """No hidden second ledger, engine, store, or portfolio authority."""

    # Constructed against tmp_path, never the default root: a bare
    # AtlasApplication() binds to the real durable state directory and
    # would let a test read - or on any execution path write - the
    # operator's live financial state.
    app = AtlasApplication(state_directory=tmp_path)

    assert app.execution.risk_engine is app.risk_engine
    assert app.execution.reservation_ledger is app.reservation_ledger
    assert app.execution.risk_state_store is app.risk_state_store
    assert app.execution.portfolio_foundation is app.portfolio_foundation


def test_canonical_risk_services_are_registered_in_the_container(
    tmp_path: Path,
) -> None:
    # Constructed against tmp_path, never the default root: a bare
    # AtlasApplication() binds to the real durable state directory and
    # would let a test read - or on any execution path write - the
    # operator's live financial state.
    app = AtlasApplication(state_directory=tmp_path)

    registered = app.container.list_services()

    for service_type in (
        RiskEngine,
        CapitalReservationLedger,
        JsonRiskStateStore,
        ExecutionPortfolioFoundation,
    ):
        assert service_type.__name__ in registered, (
            f"{service_type.__name__} must be registered by the composition "
            "root so that no other module constructs its own instance"
        )
