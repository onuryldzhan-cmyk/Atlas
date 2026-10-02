"""AI-001 gateway: the ONLY place Atlas's agents talk to a language model (owner choice 2026-10-02: Claude API).

Contract: config/model_registry.json and ADR-0011.
* Outside the trading runtime: imported only by tools/agent_cycle.py. The runtime closure
  stays AI-free (tests/architecture/test_runtime_has_no_ai_provider_dependency.py).
* The key comes ONLY from the owner's environment (ANTHROPIC_API_KEY or an `ant auth login`
  profile). It is never read from a file in the repository, never logged, never stored.
* Every prompt passes the SensitiveDataGuard first.
* Output is constrained by a JSON schema (output_config.format) and validated again here.
* timeout / malformed / refusal / unavailable / over budget -> ABSTAIN, never a default action.
* A spend cap per rolling 5-hour window (ATLAS_AI_WINDOW_BUDGET_USD, default 1.00); all agents together
  max 60 %, split by task size (AGENT_WEIGHTS).
* A model's answer is advice: no output here can trade, deploy, approve or change a threshold.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

DEFAULT_MODEL = "claude-opus-5-5"
COUNCIL_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
# USD per 1M tokens (input, output), Anthropic first-party rates, cached 2026-09-25.
PRICES = {"claude-opus-5-5": (Decimal("4"), Decimal("20")), "claude-sonnet-5-5": (Decimal("2"), Decimal("10"))}
DEFAULT_DAILY_BUDGET_USD = Decimal("1.00")
# Owner rule 2026-10-02: all AI agents together may use at most 60 % of the daily budget, and
# that share is split between the agents by task size (weight = expected model calls per run).
TOTAL_SHARE = Decimal("0.60")
AGENT_WEIGHTS = {"ceo_ai": 1, "model_council": 2}
TIMEOUT_S = 120.0
MAX_TOKENS = 16000
USAGE_FILE = "ai_usage.json"


@dataclass
class AIResult:
    status: str                      # OK | ABSTAIN
    data: dict[str, Any] | None = None
    reason: str = ""
    model: str = ""
    cost_usd: Decimal = Decimal("0")
    extra: dict[str, Any] = field(default_factory=dict)


def key_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.environ.get("ANTHROPIC_PROFILE"))


def daily_budget() -> Decimal:
    """Budget per rolling 5-hour window (ATLAS_AI_WINDOW_BUDGET_USD; the older ..._DAILY_... name is still read)."""
    raw = os.environ.get("ATLAS_AI_WINDOW_BUDGET_USD") or os.environ.get("ATLAS_AI_DAILY_BUDGET_USD") or str(DEFAULT_DAILY_BUDGET_USD)
    try:
        value = Decimal(raw)
    except ArithmeticError:
        return Decimal("0")  # an unreadable budget means no spend, never unlimited
    return value if value.is_finite() and value >= 0 else Decimal("0")


WINDOW_HOURS = 5  # owner rule 2026-10-02: quotas apply to a rolling 5-hour window, not a day or a week


class UsageLedger:
    """Spend entries [(epoch_s, agent, usd)] summed over the last WINDOW_HOURS (rolling).

    Unreadable ledger -> treated as quota exhausted (fail closed). Entries older than a day are pruned.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _load(self) -> list | None:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if isinstance(data, dict):  # pre-5h ledger format: start fresh rather than misread it
            return []
        return data if isinstance(data, list) else None

    def spent(self, now_s: float, agent: str | None = None) -> Decimal | None:
        data = self._load()
        if data is None:
            return None
        total = Decimal("0")
        try:
            for ts, who, usd in data:
                if now_s - float(ts) < WINDOW_HOURS * 3600 and (agent is None or who == agent):
                    total += Decimal(str(usd))
        except (TypeError, ValueError, ArithmeticError):
            return None
        return total

    def add(self, now_s: float, cost: Decimal, agent: str | None = None) -> None:
        data = [e for e in (self._load() or []) if now_s - float(e[0]) < 86400]
        data.append([now_s, agent, str(cost)])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.path)


def agent_cap(agent: str | None) -> Decimal:
    """This agent's daily USD cap: budget x 60 % x its weight share. Unknown agent -> 0 (no spend)."""
    usable = daily_budget() * TOTAL_SHARE
    if agent is None:
        return usable
    weight = AGENT_WEIGHTS.get(agent)
    if not weight:
        return Decimal("0")
    return usable * Decimal(weight) / Decimal(sum(AGENT_WEIGHTS.values()))


def _cost(model: str, usage: Any) -> Decimal:
    pin, pout = PRICES.get(model, PRICES[DEFAULT_MODEL])
    i = Decimal(int(getattr(usage, "input_tokens", 0) or 0))
    o = Decimal(int(getattr(usage, "output_tokens", 0) or 0))
    return (i * pin + o * pout) / Decimal(1_000_000)


def _default_client():
    import anthropic  # imported lazily: absent SDK -> ABSTAIN, and nothing in the runtime imports this module

    return anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=2)


def _validate(data: Any, schema: dict[str, Any]) -> str | None:
    if not isinstance(data, dict):
        return "not an object"
    for k in schema.get("required", []):
        if k not in data:
            return f"missing {k}"
    if schema.get("additionalProperties") is False:
        extra = set(data) - set(schema.get("properties", {}))
        if extra:
            return f"unexpected {sorted(extra)}"
    return None


def ask(system: str, prompt: str, schema: dict[str, Any], *, model: str = DEFAULT_MODEL, ledger: UsageLedger,
        client_factory: Callable[[], Any] | None = None, now: datetime | None = None,
        effort: str = "medium", agent: str | None = None) -> AIResult:
    """One structured question. Never raises; every failure is an ABSTAIN with a reason."""
    from atlas_security import sanitize_sensitive_data

    if not key_available() and client_factory is None:
        return AIResult("ABSTAIN", reason="NO_CREDENTIALS (AI-001: owner sets ANTHROPIC_API_KEY on his machine)")
    now_s = (now or datetime.now(timezone.utc)).timestamp()
    spent = ledger.spent(now_s)
    if spent is None:
        return AIResult("ABSTAIN", reason="USAGE_LEDGER_UNREADABLE")
    if spent >= daily_budget() * TOTAL_SHARE:
        return AIResult("ABSTAIN", reason=f"WINDOW_BUDGET_REACHED ({spent} USD in the last {WINDOW_HOURS} h, all agents max 60 %)")
    mine = ledger.spent(now_s, agent) if agent else spent
    if mine is None or mine >= agent_cap(agent):
        return AIResult("ABSTAIN", reason=f"AGENT_QUOTA_REACHED ({agent}: {mine} / {agent_cap(agent):.4f} USD)")
    safe_prompt = sanitize_sensitive_data(prompt)
    try:
        client = (client_factory or _default_client)()
        response = client.beta.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": safe_prompt}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
    except Exception as exc:  # SDK missing, network, rate limit, 4xx/5xx: abstain
        return AIResult("ABSTAIN", reason=f"UNAVAILABLE ({type(exc).__name__})", model=model)
    cost = _cost(getattr(response, "model", model) or model, getattr(response, "usage", None))
    ledger.add(now_s, cost, agent)
    if getattr(response, "stop_reason", None) == "refusal":
        return AIResult("ABSTAIN", reason="REFUSAL", model=model, cost_usd=cost)
    if getattr(response, "stop_reason", None) == "max_tokens":
        return AIResult("ABSTAIN", reason="TRUNCATED", model=model, cost_usd=cost)
    text = next((b.text for b in getattr(response, "content", []) or [] if getattr(b, "type", "") == "text"), None)
    try:
        data = json.loads(text) if text else None
    except ValueError:
        data = None
    problem = _validate(data, schema)
    if problem:
        return AIResult("ABSTAIN", reason=f"MALFORMED ({problem})", model=model, cost_usd=cost)
    return AIResult("OK", data=sanitize_sensitive_data(data), model=getattr(response, "model", model), cost_usd=cost)
