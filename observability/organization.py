"""Atlas organization registry: every corporate unit and agent, with its real status.

Source of the roster: the owner's vision documents - docs/vision/01_nihai_vizyon.txt
(section 3 hierarchy, section 7 departments), 02_ust_duzey_yetenekler.txt
(27 Multi-Model Council, 28 Red Team) and 04_kurumsal_kritik_gereksinimler.md
(3 Model Validation Department). Registry v5.25 (owner: "Kurumsal yapı
agentlerin hepsini istiyorum ... Web sitesinde de görünsünler").

Honesty rule (CLAUDE.md No Hallucination Policy): a unit is ACTIVE only when
running runtime code backs it, and ``implemented_by`` names those files (a
test checks they exist). PARTIAL means a real part exists (often the
development process, not the runtime). PLANNED names the roadmap phase.
Nothing here grants authority: capability is never authority, and every
AI unit is ``can_execute=False`` - only the deterministic risk/capital/
execution chain may admit or place a (paper) trade, and live stays DENIED.

Pure data (observability/*, L5 read-only panel source): stdlib only, no I/O,
no imports from the runtime - the web layer may import it (it may not import core).
"""

from __future__ import annotations

from dataclasses import dataclass

ACTIVE = "ACTIVE"
PARTIAL = "PARTIAL"
PLANNED = "PLANNED"
STATUSES = (ACTIVE, PARTIAL, PLANNED)

TIERS = (
    "OWNER",
    "CEO_AI",
    "DIRECTOR_AI",
    "EXECUTIVE_ASSISTANT",
    "DEPARTMENT",
    "WORKER_AGENT",
    "SPECIALIZED_UNIT",
    "MICRO_AGENT",
)


@dataclass(frozen=True)
class OrgUnit:
    unit_id: str
    name: str
    tier: str
    status: str
    phase: int | None
    mission: str
    can: tuple[str, ...]
    cannot: tuple[str, ...]
    implemented_by: tuple[str, ...] = ()
    can_execute: bool = False

    def to_public_dict(self) -> dict:
        return {
            "id": self.unit_id,
            "name": self.name,
            "tier": self.tier,
            "status": self.status,
            "phase": self.phase,
            "mission": self.mission,
            "can": list(self.can),
            "cannot": list(self.cannot),
            "implemented_by": list(self.implemented_by),
            "can_execute": self.can_execute,
        }


_NO_TRADE = "place or approve trades"
_NO_LIVE = "touch live capital (live DENIED)"
_NO_SELF = "change its own permissions or the roadmap"

ORGANIZATION: tuple[OrgUnit, ...] = (
    # ---------------------------------------------------------------- top
    OrgUnit("owner", "Owner (insan)", "OWNER", ACTIVE, None,
            "Final authority: approves grants, phases, risk changes and any live step.",
            ("approve or reject every critical change", "grant or revoke authority"),
            ("be bypassed by any agent",)),
    OrgUnit("ceo_ai", "CEO AI", "CEO_AI", PLANNED, 6,
            "Sets priorities across departments and reports to the owner.",
            ("propose priorities", "summarize department reports"),
            (_NO_TRADE, _NO_LIVE, _NO_SELF, "deploy code")),
    OrgUnit("director_ai", "Director AI", "DIRECTOR_AI", PLANNED, 6,
            "Coordinates departments; routing of authority stays deterministic policy, never an LLM choice.",
            ("coordinate tasks", "request reports"),
            (_NO_TRADE, _NO_LIVE, _NO_SELF, "delegate authority")),
    OrgUnit("executive_assistant", "Executive Assistant AI", "EXECUTIVE_ASSISTANT", PARTIAL, 6,
            "Prepares the owner's briefings and pending-decision queue (today: the owner terminal task list and decision log).",
            ("prepare briefings", "track owner tasks"),
            (_NO_TRADE, _NO_LIVE, _NO_SELF),
            ("docs/operations/OWNER_TERMINAL_TASKS.md", "docs/operations/AUTONOMOUS_DECISION_LOG.md")),
    OrgUnit("chief_architect", "Chief Architect AI", "DEPARTMENT", PARTIAL, 1,
            "Guards the layer model and forbidden dependencies (ARCH-001 baseline, test-enforced).",
            ("review architecture", "flag forbidden edges"),
            (_NO_TRADE, _NO_LIVE, "change layer rules without a registry record"),
            ("packaging/atlas_architecture_map.json", "tests/architecture/test_forbidden_layer_imports.py")),
    # ------------------------------------------------------- departments
    OrgUnit("quant_research", "Quant Research Department", "DEPARTMENT", PARTIAL, 4,
            "Measures market statistics that inform policy (e.g. the p30 volatility ceiling).",
            ("run read-only measurements", "write research reports"),
            (_NO_TRADE, _NO_LIVE, "change risk policy"),
            ("tools/measure_volatility_ceiling.py",)),
    OrgUnit("strategy_lab", "Strategy Laboratory", "DEPARTMENT", PLANNED, 4,
            "Designs and backtests strategies; walk-forward and out-of-sample evidence before promotion.",
            ("propose strategies", "backtest"),
            (_NO_TRADE, _NO_LIVE, "promote a strategy without evidence")),
    OrgUnit("macro_intelligence", "Macro Intelligence Center", "DEPARTMENT", ACTIVE, 2,
            "US 10Y yield trend and curve -> macro vote in the fusion; also caps the LOW risk bucket.",
            ("vote BUY/SELL/HOLD as evidence",),
            (_NO_TRADE, _NO_LIVE),
            ("analysis/world_analysis_engine.py",)),
    OrgUnit("risk_committee", "Risk Committee", "DEPARTMENT", ACTIVE, 3,
            "Deterministic sole admission authority: confidence floors, buckets, drawdown, daily loss, exposure; regime-derived bucket.",
            ("approve or reject a BUY within policy", "size limits per bucket"),
            (_NO_LIVE, "change its own policy", "be overridden by an AI decision"),
            ("core/risk_engine.py", "ai/core/intelligence/risk_engine.py"), can_execute=True),
    OrgUnit("capital_management", "Capital Management", "DEPARTMENT", ACTIVE, 3,
            "Reserves capital for admitted orders and proposes position size; never exceeds the approval.",
            ("reserve and release capital", "propose allocation"),
            (_NO_LIVE, "resize an approved order upward"),
            ("core/capital_reservation.py", "core/position_sizing.py"), can_execute=True),
    OrgUnit("performance_audit", "Performance Audit", "DEPARTMENT", ACTIVE, 3,
            "Reports closed trades, win rate with a 95% range, net after fees; never claims significance it lacks.",
            ("read the durable book", "report results"),
            (_NO_TRADE, _NO_LIVE, "edit financial records"),
            ("tools/exp001_report.py", "web_app.py")),
    OrgUnit("security", "Security Department", "DEPARTMENT", PARTIAL, 5,
            "Loopback-only panel, host/origin guards, CSP, sensitive-data redaction, no secrets in code.",
            ("block non-loopback access", "redact sensitive data"),
            (_NO_TRADE, _NO_LIVE),
            ("web_app.py", "atlas_security/sensitive_data_guard.py")),
    OrgUnit("compliance", "Compliance Department", "DEPARTMENT", PLANNED, 6,
            "Regulation readiness, tax records, data retention and privacy.",
            ("review for compliance",),
            (_NO_TRADE, _NO_LIVE)),
    OrgUnit("technology_research", "Technology Research Center", "DEPARTMENT", PLANNED, 4,
            "Evaluates new technology only for whether it speeds up or delays current roadmap work.",
            ("evaluate tools", "write proposals"),
            (_NO_TRADE, _NO_LIVE, "adopt a dependency without review")),
    OrgUnit("open_source_research", "Open Source Research Team", "DEPARTMENT", PARTIAL, 4,
            "Discover -> License -> Security -> Quality -> Compatibility -> Test -> Adopt/Adapt/Reject.",
            ("research repositories", "write proposals"),
            (_NO_TRADE, _NO_LIVE, "copy code without license review"),
            ("docs/research/AGENT_TEAM_ORG_AND_DASHBOARD_RESEARCH_2026-09-28.md",)),
    OrgUnit("ai_model_research", "AI Model Research Team", "DEPARTMENT", PLANNED, 6,
            "Model evaluation and calibration; the deterministic core stays AI-independent (ADR-0011).",
            ("evaluate models",),
            (_NO_TRADE, _NO_LIVE, "put an LLM on the execution path")),
    OrgUnit("code_review", "Code Review Team", "DEPARTMENT", PARTIAL, 9,
            "Independent audit of every critical change (today: independent audit agents in development).",
            ("review diffs", "report findings by severity"),
            (_NO_TRADE, _NO_LIVE, "deploy code", "approve its own changes")),
    OrgUnit("experiment_manager", "Experiment Manager", "DEPARTMENT", ACTIVE, 4,
            "Runs bounded PAPER experiments with a durable cap (EXP-001: floor 0.60, 50 admissions, HIGH-sized).",
            ("run a time- and count-bounded paper experiment",),
            (_NO_LIVE, "extend an experiment without the owner"),
            ("core/risk_engine.py", "core/experiment_ledger.py")),
    OrgUnit("knowledge_manager", "Knowledge Manager", "DEPARTMENT", PARTIAL, 7,
            "Keeps decisions and state recoverable: checkpoints, ADRs, registries (development process today).",
            ("record decisions", "write checkpoints"),
            (_NO_TRADE, _NO_LIVE, "edit historical registries")),
    OrgUnit("roadmap_planner", "Roadmap Planner", "DEPARTMENT", PARTIAL, 0,
            "Keeps the fixed Phase 0-10 order; new ideas go into existing phases.",
            ("place ideas into phases",),
            (_NO_TRADE, _NO_LIVE, "add a phase", _NO_SELF),
            ("governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md",)),
    OrgUnit("deployment_manager", "Deployment Manager", "DEPARTMENT", PLANNED, 9,
            "Release, canary and rollback (DEP-001); autonomous deployment is DENIED.",
            ("prepare releases",),
            (_NO_TRADE, _NO_LIVE, "deploy without owner approval")),
    OrgUnit("web_ux", "Web Design / UX Team", "DEPARTMENT", PARTIAL, 8,
            "The loopback operator panel today; the 3D Atlas HQ later.",
            ("display read-only data",),
            (_NO_TRADE, _NO_LIVE, "add a write path to the web layer"),
            ("templates/dashboard.html", "web_app.py")),
    OrgUnit("digital_twin", "Digital Twin Laboratory", "DEPARTMENT", PLANNED, 10,
            "Shadow copy of Atlas: live data, virtual orders, no capital - the required gate before small live.",
            ("simulate in parallel",),
            (_NO_TRADE, _NO_LIVE)),
    OrgUnit("incident_response", "Incident Response Team", "DEPARTMENT", ACTIVE, 3,
            "Supervisor restarts and halts, integrity exit codes, recovery runbook and reconciliation tool.",
            ("restart a hung process", "halt on corrupt state"),
            (_NO_TRADE, _NO_LIVE, "repair state without the owner"),
            ("atlas_supervisor.py", "docs/operations/RECOVERY_RUNBOOK.md", "tools/reconcile_execution_authorities.py")),
    OrgUnit("treasury", "Treasury Management", "DEPARTMENT", PLANNED, 10,
            "Live capital, custody and scaling - locked until Shadow and small-live gates pass.",
            ("plan capital allocation",),
            (_NO_TRADE, _NO_LIVE)),
    OrgUnit("explainable_ai", "Explainable AI Center", "DEPARTMENT", ACTIVE, 3,
            "Shows why each decision was made: every agent's vote and its evidence on the panel.",
            ("publish decision evidence",),
            (_NO_TRADE, _NO_LIVE),
            ("web_app.py", "templates/dashboard.html")),
    OrgUnit("model_validation", "Model Validation Department", "DEPARTMENT", PLANNED, 6,
            "Validates models and checks agents do not overstate their own success.",
            ("validate models",),
            (_NO_TRADE, _NO_LIVE)),
    OrgUnit("model_council", "Multi-Model Council", "SPECIALIZED_UNIT", PLANNED, 6,
            "Several models answer the same question; disagreement lowers confidence.",
            ("compare model answers",),
            (_NO_TRADE, _NO_LIVE)),
    OrgUnit("red_team", "Red Team / Karşı Görüş Ajanı", "SPECIALIZED_UNIT", PLANNED, 6,
            "Argues against every major decision before it is accepted.",
            ("challenge decisions",),
            (_NO_TRADE, _NO_LIVE)),
    # ----------------------------------------------------- worker agents
    OrgUnit("agent_technical", "Teknik Analiz Ajanı", "WORKER_AGENT", ACTIVE, 2,
            "RSI / EMA / ADX / trend from closed candles -> vote.",
            ("vote as evidence",), (_NO_TRADE, _NO_LIVE),
            ("core/technical_analyzer.py", "ai/core/intelligence/agent_fusion.py")),
    OrgUnit("agent_macro", "Makro Ajanı", "WORKER_AGENT", ACTIVE, 2,
            "10Y yield 20-day move and curve -> vote.",
            ("vote as evidence",), (_NO_TRADE, _NO_LIVE),
            ("analysis/world_analysis_engine.py", "ai/core/intelligence/agent_fusion.py")),
    OrgUnit("agent_sentiment", "Sentiment Ajanı", "WORKER_AGENT", PARTIAL, 4,
            "Excluded from the vote until a provider is configured (never a fabricated value).",
            ("vote as evidence when available",), (_NO_TRADE, _NO_LIVE),
            ("analysis/world_analysis_engine.py",)),
    OrgUnit("agent_risk", "Risk (Volatilite) Ajanı", "WORKER_AGENT", ACTIVE, 2,
            "Realized-volatility regime LOW/NEUTRAL/HIGH -> vote and bucket input.",
            ("vote as evidence",), (_NO_TRADE, _NO_LIVE),
            ("core/market_risk_regime.py",)),
    OrgUnit("agent_momentum", "Momentum Ajanı", "WORKER_AGENT", ACTIVE, 2,
            "RSI/trend momentum -> vote.",
            ("vote as evidence",), (_NO_TRADE, _NO_LIVE),
            ("ai/core/intelligence/agent_fusion.py",)),
    OrgUnit("micro_agents", "Micro Agents", "MICRO_AGENT", PLANNED, 6,
            "Narrow single-purpose helpers under a worker agent.",
            ("perform one narrow task",), (_NO_TRADE, _NO_LIVE)),
)


def organization_public() -> dict:
    """The roster for the read-only /api/organization endpoint."""

    counts = {status: sum(1 for unit in ORGANIZATION if unit.status == status) for status in STATUSES}
    return {
        "available": True,
        "source": "docs/vision (01 section 3 and 7, 02 items 27-28, 04 section 3)",
        "tiers": list(TIERS),
        "counts": counts,
        "units": [unit.to_public_dict() for unit in ORGANIZATION],
    }
