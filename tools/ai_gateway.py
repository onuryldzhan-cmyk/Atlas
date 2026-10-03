"""AI-001 gateway: the ONLY place Atlas's agents talk to a language model (owner choice 2026-10-02: Claude API).

Contract: config/model_registry.json and ADR-0011.
* Outside the trading runtime: imported only by tools/agent_cycle.py. The runtime closure
  stays AI-free (tests/architecture/test_runtime_has_no_ai_provider_dependency.py).
* The key comes ONLY from the owner's environment (ANTHROPIC_API_KEY or an `ant auth login`
  profile). It is never read from a file in the repository, never logged, never stored.
* Every prompt passes the SensitiveDataGuard first.
* Output is constrained by a JSON schema (output_config.format) and validated again here.
* timeout / malformed / refusal / unavailable / over budget -> ABSTAIN, never a default action.
* Owner rule 2026-10-03: the agents may use the whole rolling 5-hour window of the owner's plan, each as
  much as its work needs (the 2026-10-02 "60 %, split by task size" rule is superseded). Still bounded:
  only AI_AGENTS may call, the same question is never paid for twice in 24 h, a per-agent runaway
  ceiling stops a loop, and an owner-set ceiling (ATLAS_AI_WINDOW_CALLS / ATLAS_AI_WINDOW_BUDGET_USD)
  is honoured in full.
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

DEFAULT_MODEL = "claude-sonnet-5-5"  # owner choice 2026-10-02: agents run on Sonnet 5.5 at effort high
DEFAULT_EFFORT = "high"
# Council: one model, two independent reviewer perspectives (recorded as such - not two models).
COUNCIL_PERSPECTIVES = ("risk-focused reviewer", "evidence-focused reviewer")
# USD per 1M tokens (input, output), Anthropic first-party rates, cached 2026-09-25.
PRICES = {"claude-opus-5-5": (Decimal("4"), Decimal("20")), "claude-sonnet-5-5": (Decimal("2"), Decimal("10"))}
DEFAULT_DAILY_BUDGET_USD = Decimal("1.00")
# Owner choice 2026-10-02: run the agents through Claude Code on the owner's Pro subscription
# (`claude -p`), not a paid API key. ATLAS_AI_BACKEND=api switches back to the API path.
BACKEND = os.environ.get("ATLAS_AI_BACKEND", "claude_code")
# Pro usage is not visible to Atlas, so on the subscription the plan's own 5-hour limit is the budget:
# Claude Code refuses past it and the agents abstain. ATLAS_AI_WINDOW_CALLS, when the owner sets it, is
# an extra ceiling of calls per rolling 5 hours, used in full.
#
# Superseded record (kept, not erased): "Owner rule 2026-10-02: all AI agents together may use at most
# 60 % of the daily budget, and that share is split between the agents by task size (TOTAL_SHARE 0.60,
# AGENT_WEIGHTS ceo_ai 1 / model_council 2; default 10 calls -> ceo 2, council 4)."
# Owner rule 2026-10-03 (reason: tie the budget to the whole 5-hour window and let each agent use what its
# work needs): no share and no fixed split. What still bounds the spend, so a loop can never burn the window:
AI_AGENTS = frozenset({"ceo_ai", "model_council"})  # nobody else may call a model
# Per agent per rolling 5 hours: far above normal need (CEO <= 2 by its 2.5 h gap, council 2 calls per new
# proposal); reaching it means a loop, not work.
RUNAWAY_CALLS_PER_WINDOW = 12
DUPLICATE_WINDOW_H = 24  # the same agent never pays twice for the same question within this window
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
    """Spend entries [epoch_s, agent, usd(, question_hash)] summed over the last WINDOW_HOURS (rolling).

    Unreadable ledger -> treated as quota exhausted (fail closed). Entries older than a day are pruned.
    The question hash (2026-10-03) is optional, so older three-field entries stay valid.
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
            for entry in data:
                ts, who, usd = entry[0], entry[1], entry[2]
                if now_s - float(ts) < WINDOW_HOURS * 3600 and (agent is None or who == agent):
                    total += Decimal(str(usd))
        except (TypeError, ValueError, ArithmeticError, IndexError, KeyError):
            return None
        return total

    def calls(self, now_s: float, agent: str | None = None) -> int | None:
        data = self._load()
        if data is None:
            return None
        try:
            return sum(1 for entry in data
                       if now_s - float(entry[0]) < WINDOW_HOURS * 3600 and (agent is None or entry[1] == agent))
        except (TypeError, ValueError, IndexError, KeyError):
            return None

    def asked(self, now_s: float, agent: str | None, question: str) -> bool | None:
        """True when this agent already paid for this exact question within DUPLICATE_WINDOW_H; None: unreadable."""
        data = self._load()
        if data is None:
            return None
        try:
            return any(len(entry) > 3 and entry[3] == question and entry[1] == agent
                       and now_s - float(entry[0]) < DUPLICATE_WINDOW_H * 3600 for entry in data)
        except (TypeError, ValueError, IndexError, KeyError):
            return None

    def between(self, start_s: float, end_s: float) -> tuple[int, Decimal] | None:
        """Calls and USD recorded in [start_s, end_s] (one agent cycle); None when the ledger is unreadable."""
        data = self._load()
        if data is None:
            return None
        calls, total = 0, Decimal("0")
        try:
            for entry in data:
                if start_s <= float(entry[0]) <= end_s:
                    calls += 1
                    total += Decimal(str(entry[2]))
        except (TypeError, ValueError, ArithmeticError, IndexError, KeyError):
            return None
        return calls, total

    def add(self, now_s: float, cost: Decimal, agent: str | None = None, question: str | None = None) -> None:
        data = [e for e in (self._load() or []) if now_s - float(e[0]) < 86400]
        data.append([now_s, agent, str(cost)] + ([question] if question else []))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(self.path)


def agent_cap(agent: str | None) -> Decimal:
    """USD an agent may spend in the window (API backend): the whole shared budget for a listed agent,
    0 for anyone else. There is no per-agent split any more (owner 2026-10-03)."""
    if agent is not None and agent not in AI_AGENTS:
        return Decimal("0")
    return daily_budget()


def window_calls() -> int | None:
    """The owner's optional ceiling of calls per rolling 5 hours (subscription backend).

    Unset -> None: no Atlas ceiling, the plan's own 5-hour limit is the budget. Unreadable or negative -> 0:
    no calls (fail closed, never unlimited by mistake)."""
    raw = os.environ.get("ATLAS_AI_WINDOW_CALLS")
    if raw is None or not raw.strip():
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def question_key(system: str, prompt: str, schema: dict[str, Any], model: str, effort: str) -> str:
    """Identity of a question, from exactly what is sent (after the SensitiveDataGuard)."""
    import hashlib

    blob = json.dumps([system, prompt, schema, model, effort], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _refusal(ledger: UsageLedger, now_s: float, agent: str | None, question: str, backend: str) -> AIResult | None:
    """Every reason not to ask, checked before anything is spent (fail closed). None: the call may go ahead."""
    if agent is not None and agent not in AI_AGENTS:
        return AIResult("ABSTAIN", reason=f"AGENT_NOT_ALLOWED ({agent} may not call a model)")
    used = ledger.calls(now_s)
    if used is None:
        return AIResult("ABSTAIN", reason="USAGE_LEDGER_UNREADABLE")
    asked = ledger.asked(now_s, agent, question)
    if asked is None:
        return AIResult("ABSTAIN", reason="USAGE_LEDGER_UNREADABLE")
    if asked:
        return AIResult("ABSTAIN", reason=f"DUPLICATE_QUESTION (asked within {DUPLICATE_WINDOW_H} h; "
                                          "only new evidence makes a new question)")
    if backend == "claude_code":
        ceiling = window_calls()
        if ceiling is not None and used >= ceiling:
            return AIResult("ABSTAIN", reason=f"WINDOW_CALLS_REACHED ({used}/{ceiling} calls in {WINDOW_HOURS} h, owner ceiling)")
    else:
        spent = ledger.spent(now_s)
        if spent is None:
            return AIResult("ABSTAIN", reason="USAGE_LEDGER_UNREADABLE")
        if spent >= daily_budget():
            return AIResult("ABSTAIN", reason=f"WINDOW_BUDGET_REACHED ({spent} USD in the last {WINDOW_HOURS} h)")
    if agent is not None:
        mine = ledger.calls(now_s, agent)
        if mine is None or mine >= RUNAWAY_CALLS_PER_WINDOW:
            return AIResult("ABSTAIN", reason=f"AGENT_RUNAWAY_LIMIT ({agent}: {mine} calls in {WINDOW_HOURS} h, "
                                              f"limit {RUNAWAY_CALLS_PER_WINDOW}; normal need is far below)")
    return None


def _claude_code_runner(prompt: str, system: str, schema: dict[str, Any], model: str, effort: str) -> dict[str, Any]:
    """`claude -p` on the owner's logged-in subscription: no tools, no project config, prompt via stdin."""
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("claude")
    if not exe:
        raise FileNotFoundError("claude CLI not found")
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    alias = "sonnet" if "sonnet" in model else model
    with tempfile.TemporaryDirectory() as empty:  # empty cwd: no CLAUDE.md, no repository access
        proc = subprocess.run(
            [exe, "-p", "--output-format", "json", "--json-schema", json.dumps(schema), "--model", alias,
             "--effort", effort, "--tools", "", "--max-turns", "3", "--setting-sources", "user",
             "--strict-mcp-config", "--append-system-prompt", system],
            input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_S * 3, cwd=empty, env=env)
    if proc.returncode != 0:
        from atlas_security import sanitize_sensitive_text
        detail = sanitize_sensitive_text((proc.stderr or proc.stdout or "").strip())[:300]
        raise RuntimeError(f"claude exit {proc.returncode}: {detail}")
    return json.loads(proc.stdout)


def _ask_claude_code(system, prompt, schema, model, effort, agent, ledger, now_s, runner) -> AIResult:
    question = question_key(system, prompt, schema, model, effort)
    refused = _refusal(ledger, now_s, agent, question, "claude_code")
    if refused is not None:
        return refused
    try:
        out = (runner or _claude_code_runner)(prompt, system, schema, model, effort)
    except Exception as exc:  # CLI missing, not logged in, usage limit hit, timeout: abstain
        return AIResult("ABSTAIN", reason=f"UNAVAILABLE ({type(exc).__name__}: {str(exc)[:300]})", model=model)
    cost = Decimal(str(out.get("total_cost_usd") or "0")) if isinstance(out, dict) else Decimal("0")
    ledger.add(now_s, cost, agent, question)  # one entry = one call, also when the answer is rejected below
    if not isinstance(out, dict) or out.get("is_error"):
        return AIResult("ABSTAIN", reason="CLAUDE_CODE_ERROR", model=model)
    data = out.get("structured_output")
    problem = _validate(data, schema)
    if problem:
        return AIResult("ABSTAIN", reason=f"MALFORMED ({problem})", model=model)
    return AIResult("OK", data=data, model=model, cost_usd=cost, extra={"backend": "claude_code"})


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
        effort: str = DEFAULT_EFFORT, agent: str | None = None, runner: Callable | None = None,
        backend: str | None = None) -> AIResult:
    """One structured question. Never raises; every failure is an ABSTAIN with a reason."""
    from atlas_security import sanitize_sensitive_data

    if (backend or BACKEND) == "claude_code" and client_factory is None:
        from atlas_security import sanitize_sensitive_data as _clean
        return _ask_claude_code(system, _clean(prompt), schema, model, effort, agent, ledger,
                                (now or datetime.now(timezone.utc)).timestamp(), runner)
    if not key_available() and client_factory is None:
        return AIResult("ABSTAIN", reason="NO_CREDENTIALS (AI-001: owner sets ANTHROPIC_API_KEY on his machine)")
    now_s = (now or datetime.now(timezone.utc)).timestamp()
    safe_prompt = sanitize_sensitive_data(prompt)
    question = question_key(system, safe_prompt, schema, model, effort)
    refused = _refusal(ledger, now_s, agent, question, "api")
    if refused is not None:
        return refused
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
    ledger.add(now_s, cost, agent, question)
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
