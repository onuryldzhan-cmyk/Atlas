"""Capability-oriented permission model for Atlas organization units.

Every unit gets an explicit, closed set of capabilities. Anything not granted
is denied. Two capabilities are never grantable to an AI unit, whatever a
grant table says:

* ``financial_execute``: only the deterministic Risk -> Capital -> Execution
  chain places (paper) orders, and live stays DENIED;
* ``deploy``: autonomous deployment authority is DENIED.

``modify_governance`` and ``modify_permissions`` are not capabilities at all:
no unit, the owner's tooling aside, may change governance or anyone's grants
(an agent may never change its own permissions - CLAUDE.md Security rules).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Capability(str, Enum):
    READ_CODE = "read_code"
    WRITE_CODE = "write_code"
    RUN_TESTS = "run_tests"
    WEB_RESEARCH = "web_research"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    EXECUTE_TOOLS = "execute_tools"
    FINANCIAL_READ = "financial_read"
    FINANCIAL_EXECUTE = "financial_execute"
    DEPLOY = "deploy"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


CAPABILITY_RISK: dict[Capability, RiskLevel] = {
    Capability.READ_CODE: RiskLevel.LOW,
    Capability.MEMORY_READ: RiskLevel.LOW,
    Capability.FINANCIAL_READ: RiskLevel.LOW,
    Capability.WEB_RESEARCH: RiskLevel.MEDIUM,
    Capability.RUN_TESTS: RiskLevel.MEDIUM,
    Capability.MEMORY_WRITE: RiskLevel.MEDIUM,
    Capability.WRITE_CODE: RiskLevel.HIGH,
    Capability.EXECUTE_TOOLS: RiskLevel.HIGH,
    Capability.FINANCIAL_EXECUTE: RiskLevel.CRITICAL,
    Capability.DEPLOY: RiskLevel.CRITICAL,
}

NEVER_GRANTED_TO_AI = frozenset({Capability.FINANCIAL_EXECUTE, Capability.DEPLOY})

_R = Capability
_READ = (_R.READ_CODE, _R.MEMORY_READ)

# Explicit grants, keyed by observability.organization unit ids. A unit that
# is missing here has no capability at all (deny by default).
GRANTS: dict[str, tuple[Capability, ...]] = {
    "ceo_ai": (*_READ, _R.FINANCIAL_READ),
    "director_ai": (*_READ, _R.FINANCIAL_READ),
    "executive_assistant": (*_READ, _R.MEMORY_WRITE),
    "chief_architect": (*_READ, _R.RUN_TESTS),
    "quant_research": (*_READ, _R.FINANCIAL_READ, _R.RUN_TESTS, _R.MEMORY_WRITE),
    "strategy_lab": (*_READ, _R.FINANCIAL_READ, _R.RUN_TESTS),
    "macro_intelligence": (_R.MEMORY_READ, _R.FINANCIAL_READ),
    "risk_committee": (_R.MEMORY_READ, _R.FINANCIAL_READ),
    "capital_management": (_R.MEMORY_READ, _R.FINANCIAL_READ),
    "performance_audit": (*_READ, _R.FINANCIAL_READ, _R.RUN_TESTS),
    "security": (*_READ, _R.RUN_TESTS, _R.EXECUTE_TOOLS, _R.MEMORY_WRITE),
    "compliance": _READ,
    "technology_research": (*_READ, _R.WEB_RESEARCH, _R.MEMORY_WRITE),
    "open_source_research": (*_READ, _R.WEB_RESEARCH, _R.MEMORY_WRITE),
    "ai_model_research": (*_READ, _R.WEB_RESEARCH),
    "code_review": (*_READ, _R.RUN_TESTS),
    "experiment_manager": (*_READ, _R.FINANCIAL_READ, _R.RUN_TESTS, _R.MEMORY_WRITE),
    "knowledge_manager": (*_READ, _R.MEMORY_WRITE),
    "roadmap_planner": _READ,
    "deployment_manager": (*_READ, _R.RUN_TESTS),
    "web_ux": (*_READ, _R.WRITE_CODE, _R.RUN_TESTS),
    "digital_twin": (*_READ, _R.FINANCIAL_READ),
    "incident_response": (*_READ, _R.FINANCIAL_READ),
    "treasury": (_R.MEMORY_READ, _R.FINANCIAL_READ),
    "explainable_ai": (_R.MEMORY_READ, _R.FINANCIAL_READ),
    "model_validation": (*_READ, _R.RUN_TESTS),
    "model_council": _READ,
    "red_team": _READ,
    "agent_technical": (_R.FINANCIAL_READ,),
    "agent_macro": (_R.FINANCIAL_READ,),
    "agent_sentiment": (_R.FINANCIAL_READ,),
    "agent_risk": (_R.FINANCIAL_READ,),
    "agent_momentum": (_R.FINANCIAL_READ,),
    "micro_agents": (_R.MEMORY_READ,),
}


@dataclass(frozen=True)
class AuthorizationResult:
    unit_id: str
    capability: Capability
    allowed: bool
    reason: str


def granted(unit_id: str) -> frozenset[Capability]:
    """The capabilities a unit holds; never includes a NEVER_GRANTED_TO_AI one."""

    return frozenset(GRANTS.get(unit_id, ())) - NEVER_GRANTED_TO_AI


def authorize(unit_id: str, capability: Capability | str) -> AuthorizationResult:
    try:
        cap = Capability(capability)
    except ValueError:
        return AuthorizationResult(unit_id, Capability.READ_CODE, False,
                                   f"unknown capability {capability!r}")
    if cap in NEVER_GRANTED_TO_AI:
        return AuthorizationResult(unit_id, cap, False,
                                   "never granted to an AI unit (live/deploy authority DENIED)")
    if unit_id not in GRANTS:
        return AuthorizationResult(unit_id, cap, False, "unknown unit: deny by default")
    if cap in granted(unit_id):
        return AuthorizationResult(unit_id, cap, True, "explicit grant")
    return AuthorizationResult(unit_id, cap, False, "not granted")


def unit_risk_level(unit_id: str) -> RiskLevel:
    order = list(RiskLevel)
    caps = granted(unit_id)
    if not caps:
        return RiskLevel.LOW
    return max((CAPABILITY_RISK[c] for c in caps), key=order.index)


def permissions_public() -> list[dict]:
    return [
        {
            "id": unit_id,
            "capabilities": sorted(c.value for c in granted(unit_id)),
            "risk_level": unit_risk_level(unit_id).value,
        }
        for unit_id in GRANTS
    ]
