"""D6 / S4: M-1 interlock.

Proves Package 2A has NOT activated RiskEngine, CapitalReservationLedger,
RiskStateStore, or ExecutionPortfolioFoundation inside the live composition
root. This is temporary by design: canonical risk services remain
deliberately unwired until M-1 is fixed. Package 2B will replace/invert
this test only AFTER M-1 has been remediated.

The proof is a black-box construction of the real, unmodified
AtlasApplication composition root (no mocking of core/application.py or
core/execution_manager.py) followed by attribute inspection of the live
ExecutionManager instance it produces.
"""

from __future__ import annotations

from core.application import AtlasApplication


def test_composition_root_does_not_wire_risk_services() -> None:
    app = AtlasApplication()

    assert app.execution.risk_engine is None, (
        "Package 2A must not wire RiskEngine into the live composition root; "
        "M-1 remains dormant by design until Package 2B remediation"
    )
    assert app.execution.reservation_ledger is None, (
        "Package 2A must not wire CapitalReservationLedger into the live "
        "composition root; M-1 remains dormant by design until Package 2B remediation"
    )
    assert app.execution.risk_state_store is None, (
        "Package 2A must not wire RiskStateStore into the live composition "
        "root; M-1 remains dormant by design until Package 2B remediation"
    )
    assert app.execution.portfolio_foundation is None, (
        "Package 2A must not wire ExecutionPortfolioFoundation into the live "
        "composition root; M-1 remains dormant by design until Package 2B remediation"
    )
