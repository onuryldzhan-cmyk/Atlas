"""Atlas Manager: turns a natural-language request into a governed task plan.

This is deterministic policy, not an AI: classification is rule-based
keyword matching (Turkish and English), and routing of work to units is a
fixed table checked against ``atlas_org.permissions``. That is deliberate:
authority routing must never be an LLM choice (research doc 2026-09-28,
CrewAI lesson). An LLM may later suggest a classification, but the plan and
the routing stay here.

Requests that would need authority no agent has - live trading, deployment,
changing risk limits or governance, bypassing approval - are not turned into
tasks at all: they are returned as REQUIRES_OWNER with the reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from atlas_org import permissions

C = permissions.Capability


@dataclass(frozen=True)
class Step:
    role: str
    capability: str
    goal: str


@dataclass(frozen=True)
class Plan:
    category: str
    classification: str
    steps: tuple[Step, ...] = ()
    matched: tuple[str, ...] = ()
    refusal: str | None = None

    def to_payload(self, request: str) -> dict:
        return {"request": request, "category": self.category,
                "classification": {"method": "deterministic keyword rules", "matched": list(self.matched),
                                   "result": self.classification},
                "steps": [{"role": s.role, "capability": s.capability, "goal": s.goal} for s in self.steps]}


# Checked first: anything here needs the owner, never a task.
FORBIDDEN = (
    (r"\b(canl[ıi]|live)\b.*\b(i[sş]lem|trade|trading|emir|order)|ger[cç]ek para|real money|"
     r"go(ing)? live|canl[ıi]ya (ge[cç]|al)|live'?a ge[cç]|mainnet|real account|ger[cç]ek hesap|"
     r"real (funds?|capital)|ger[cç]ek (fon|bakiye|sermaye)",
     "live trading: live_authority is DENIED"),
    (r"\b(deploy|production|prod[uü]ksiyon|yay[ıi]na al)", "deployment: autonomous deployment is DENIED"),
    (r"risk (limit|s[ıi]n[ıi]r)|max(imum)? (pozisyon|position|drawdown)|kald[ıi]ra[cç]|leverage|"
     r"stop.?loss|zarar durdur|kill.?switch|circuit.?breaker|devre kesici|acil durdur|emergency.?stop|"
     r"sermaye(yi)? (pay|da[gğ][ıi]l|art|azalt|de[gğ]i[sş]tir)|capital (sleeve|allocation|increase)|exposure",
     "risk and capital controls change only by an owner decision"),
    (r"onay(ı|i)? (kald[ıi]r|atla|gerekmesin)|bypass|skip (approval|review|tests?)|without (approval|review)|"
     r"auto.?approve|otomatik onay|testleri? (atla|kapat|devre d[ıi][sş][ıi])|disable (tests?|audit|logging)",
     "approval, review, tests and audit cannot be bypassed"),
    (r"governance|y[oö]neti[sş]im|claude\.md|agents\.md|atlas_org|\.claude|architecture_map|permission|"
     r"yetki|izin(ler)?i? (de[gğ]i[sş]tir|ver|art)|kural(lar[ıi])? (de[gğ]i[sş]tir|kald[ıi]r)|"
     r"(write|deploy|admin|root) access|access to|eri[sş]im (ver|a[cç])",
     "governance and permissions change only by an owner decision"),
)

RULES = (
    ("SECURITY_REVIEW", r"g[uü]venlik|security|zafiyet|vulnerab|secret|s[ıi]z[ıi]nt[ıi]|injection"),
    ("PERFORMANCE", r"performans|performance|latency|gecikme|yava[sş]|slow|bottleneck|darbo[gğ]az"),
    ("CODE_CHANGE", r"d[uü]zelt|fix|iyile[sş]tir|improve|refactor|implement|geli[sş]tir|ekle|add|bug|hata"),
    ("RESEARCH", r"ara[sş]t[ıi]r|research|investigate|incele|github|k[uü]t[uü]phane|library|teknoloji|technology"),
    ("TRADING_ANALYSIS", r"strateji|strategy|backtest|piyasa|market|portf[oö]y|portfolio|pnl|k[aâ]r|zarar"),
    ("KNOWLEDGE", r"hat[ıi]rla|remember|kaydet|record|belgele|document|karar(ı|i)? yaz"),
)

PLANS: dict[str, tuple[Step, ...]] = {
    "RESEARCH": (
        Step("research", C.WEB_RESEARCH.value, "collect evidence: purpose, license, maintenance, dependencies"),
        Step("security", C.READ_CODE.value, "security and license evaluation of the findings"),
        Step("knowledge", C.MEMORY_WRITE.value, "record the result as a RESEARCH memory record"),
    ),
    "CODE_CHANGE": (
        Step("research", C.WEB_RESEARCH.value, "inspect existing code and prior art"),
        Step("engineering", C.WRITE_CODE.value, "implement the smallest correct change"),
        Step("engineering", C.RUN_TESTS.value, "run the relevant tests and record exact results"),
        Step("code_review", C.READ_CODE.value, "independent code review"),
        Step("security", C.READ_CODE.value, "independent security review"),
    ),
    "SECURITY_REVIEW": (
        Step("security", C.READ_CODE.value, "security review: dependencies, secrets, filesystem, network"),
        Step("code_review", C.READ_CODE.value, "second, independent review of the findings"),
    ),
    "PERFORMANCE": (
        Step("performance", C.RUN_TESTS.value, "measure before optimizing"),
        Step("code_review", C.READ_CODE.value, "review the measurement and any proposed change"),
    ),
    "TRADING_ANALYSIS": (
        Step("quant", C.FINANCIAL_READ.value, "analysis only - read paper results and market statistics"),
        Step("risk", C.FINANCIAL_READ.value, "risk view of the analysis (no limit changes)"),
    ),
    "KNOWLEDGE": (
        Step("knowledge", C.MEMORY_WRITE.value, "record with provenance; non-authoritative unless the owner decides"),
    ),
}

# Deterministic routing: role -> candidate units, first authorized one wins.
ROUTING: dict[str, tuple[str, ...]] = {
    "research": ("open_source_research", "technology_research"),
    "engineering": ("code_engineering",),
    "code_review": ("code_review",),
    "security": ("security",),
    "performance": ("performance_audit",),
    "quant": ("quant_research",),
    "risk": ("risk_committee",),
    "knowledge": ("knowledge_manager",),
}


def normalise_text(text: str | None) -> str:
    """Case-fold for Turkish and English alike: "İ"/"I" must not break matching (audit v5.39 F6)."""

    return (text or "").replace("İ", "i").replace("I", "i").strip().lower().replace("ı", "i")


def classify(request: str) -> Plan:
    text = normalise_text(request)
    if not text:
        return Plan("NONE", "EMPTY", refusal="empty request")
    for pattern, reason in FORBIDDEN:
        if re.search(pattern, text):
            return Plan("REQUIRES_OWNER", "REQUIRES_OWNER", matched=(pattern,), refusal=reason)
    for category, pattern in RULES:
        hits = tuple(m.group(0) for m in re.finditer(pattern, text))
        if hits:
            return Plan(category, category, PLANS[category], hits)
    return Plan("UNCLEAR", "UNCLEAR", refusal="no rule matched: the owner should restate the request")


def route(role: str, capability: str) -> str | None:
    for unit in ROUTING.get(role, ()):
        if permissions.authorize(unit, capability).allowed:
            return unit
    return None
