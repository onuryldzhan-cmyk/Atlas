# ADR-0011: AI-Independent Deterministic Core, Provider-Neutral AI Layer, and Governed Self-Modification

> **Lineage note (2026-09-28):** first recorded on the non-canonical parallel branch `claude/vigilant-maxwell-5vwebp` as registry v4.90, a number that collides with the owner's own v4.90. The owner designated the local lineage canonical; this document is re-recorded there in `governance/current/ATLAS_MILESTONE_REGISTRY_v5.02.json` (`parallel_lineage_reconciliation`). References to v4.90 below mean the parallel-branch record.

## Status

Accepted 2026-09-28 (UTC), **as principle only**.

- No part of this ADR authorizes implementation.
- Every implementation it anticipates stays behind the feature-expansion freeze (`PAUSED_PENDING_REM_GATE_1`), the milestone sequence, and a separate owner decision.
- The authority state is unchanged: `production_authority=NONE`, `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.

Authorized by the owner's selection of "B + ADR" in the Claude Code session of 2026-09-28. The grant identifier is UNKNOWN. It is recorded in registry v4.90 (`roadmap_enumeration_and_ai_independence_adr_result`), together with `governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md`.

Supersedes nothing. Amends no earlier ADR.

## Context

On 2026-09-28 the owner set out how Atlas relates to AI models and to Claude Code. In summary, in the owner's own framing:

1. **"Atlas'ın kalbi AI değil."** Market data, reconnect, P&L, positions, capital, risk limits, stop rules, orders, paper trading, financial state, database, event bus, supervisor, health, monitoring, alerts, audit, reconciliation, emergency stop, backtest, indicators, pre-programmed strategies and the panels are ordinary deterministic software. Atlas must run with every AI service off ("AI SERVICES: OFF … Atlas çalışmaya devam eder").
2. **AI is an upper layer, called when needed.** It handles research, natural language, complex analysis, strategy research, coding, review and reports. Anything computable locally costs zero tokens and is done locally.
3. **No single-provider lock-in.** There is an AI provider abstraction and an AI router. Local Ollama is the default. Claude or other models are used when needed. If Claude is unavailable, Atlas does not stop.
4. **Claude Code is the tool used to build Atlas.** It is not part of Atlas and not a runtime dependency.
5. **Atlas may eventually change its own code ("Atlas Coder").** It may do so only through this pipeline: proposal → risk/impact analysis → user approval → sandbox branch → implementation → tests → independent review → security review → user approval → apply. The AI must never be able to say "I judged it fit and changed the code."
6. **AI output is a proposal.** For example, "increase the BTC position by 50%" still has to pass the risk engine, the capital engine, the policy check and approval. A refusal by the risk engine is final whatever the AI says.

### Repository reality (verified 2026-09-28 at HEAD `ee50b63`)

- **No runtime module imports an AI provider SDK.** A search for `import`/`from` of `anthropic`, `openai`, `ollama` or `langchain` over `*.py` finds none outside `_quarantine`, `archive_unused_*` and backups.
- **No module calls an LLM HTTP endpoint.** No `*.py` file contains `api.anthropic.com`, `api.openai.com`, `localhost:11434`, `/api/generate`, `/api/chat`, `/v1/messages` or `/v1/chat/completions`.
- **Existing tests already forbid provider SDKs in the capability modules:**
  - `tests/test_block3_capability_architecture.py:148-153` (`test_no_provider_sdk_dependency_is_introduced`);
  - `tests/test_block3_package4_capability_gateway.py:173-179`.
  - Both name `ollama` explicitly.
- **`ai/chat_assistant.py` is inert.** It imports only `json`, `os`, `re` and `datetime`, and no module imports it.
- **AI-001 (Enterprise AI Architecture) exists only as a proposal.** It is `PROPOSED_NOT_SEQUENCED`, `implementation_authorized: false`, with prerequisites ARCH-001, GOV-001, DATA-001, SEC-001.1, SEC-002, OBS-001, TEST-001, DEP-001 and OPS-001.

Principles 1 and 6 therefore already hold in the code today. This ADR makes them binding, so later work cannot erode them.

## Decision

### D1 — The deterministic core never depends on AI

- The core runs, with unchanged safety behaviour, when every AI service is absent, slow or wrong. The core is market data, financial state, risk, capital, position, execution, persistence, audit, supervisor and the read-only status surfaces.
- No core module imports an AI provider SDK or calls an AI endpoint.
- AI unavailability may disable AI-dependent features only. It never blocks, alters or bypasses a core safety path.
- AI availability is reported as a status (for example `AI: OFFLINE / IDLE / ACTIVE`). It is not a precondition for starting the core.

### D2 — AI is reached only through a provider-neutral layer

- When the AI layer is implemented, AI is reached only through a provider abstraction and a router. No feature calls a provider directly.
- The intended default provider is local (Ollama). Cloud providers, Claude among them, are optional and replaceable.
- Model choice per task follows the owner's routing idea: deterministic code first, then local models for simple tasks, then stronger models, then independent multi-model review for critical tasks.
- Concrete models are **not** decided here (see "Not decided").

### D3 — Claude Code is a development tool, not a component

Atlas has no runtime dependency on Claude Code. Claude Code, like any other assistant, is used to build Atlas and is governed by CLAUDE.md. It is not an Atlas agent and holds no Atlas authority.

### D4 — AI output is always a proposal

The runtime order in CLAUDE.md is unchanged by any AI capability: Decision → Risk → Capital → Execution Manager → Exchange. An AI suggestion enters that chain as a proposal and has no path around any gate.

### D5 — Self-modification only through the governed pipeline (Atlas Coder)

If and when Atlas gains the ability to change its own code (Phase 9, EVOLUTION):

1. **No write before approval.** A code agent's first output is a proposal. It includes reason, files, risk, impact, tests, security notes and a rollback plan. Nothing is written before the first human approval.
2. **Isolation.** Implementation runs in a sandbox: a separate process and working copy with no access to secrets, exchange credentials, live or durable financial state, or the running core. Tool access is restricted to an explicit allowlist, and every tool call is audited.
3. **Gates are not the author.**
   - Tests, lint and security scans are deterministic tools.
   - Review is performed by a different model or by a human, never by the model that wrote the change.
   - A failed gate stops the pipeline; it does not ask the author for a verdict.
4. **Apply is human-gated.**
   - Applying a change requires a second, explicit human approval of the reviewed diff.
   - The code agent never applies, merges or deploys.
   - Every change carries its rollback.
5. **Authority separation holds.** CLAUDE.md's three authority domains (learning, self-modifying code, managing live capital) never grant each other permission. Capability is never authority.

## Consequences

- Any future change that adds an AI SDK import or an AI endpoint call to a core module violates this ADR, even if its tests pass.
- AI-001, when it is sequenced, must realize D1–D2. Its "Where" is Phase 4 for first research use and Phase 6 for the router and organization.
- Atlas Coder is Phase 9 work. It cannot start before the proposal and approval system (Phase 6), sandboxing and security gating (Phase 5), and a green CI gate exist.
- Cost behaviour follows directly: running panels, trading, risk and monitoring consume zero AI tokens by construction.

## Not decided (explicitly deferred)

- **Which models to use.** The owner's message names Qwen3:4B as installed locally, and `qwen3-coder`, `glm-4.7-flash` and `gpt-oss:20b` as candidate coding models. Their capabilities, licences, hardware needs and the cited Ollama and Anthropic documentation claims were **not verified**. Choosing any of them is a RESEARCH MODE task, and must go through CLAUDE.md's Discover → License → Security → Quality → Compatibility → Test → Adopt/Adapt/Reject flow for external components.
- **The shape of the provider interface, the router's classification rules, and the sandbox technology.**
- **Whether a static architecture test should enforce D1 across all core modules**, beyond today's capability-module tests. This is recorded as a Deferred Improvement.

## Alternatives considered

- **Claude Code or a single cloud model as Atlas's runtime brain.** Rejected by the owner: it creates provider lock-in and a runtime dependency on an external service, and it costs tokens for work deterministic code can do.
- **Letting a code agent write and apply directly after tests pass.** Rejected. It violates CLAUDE.md rule 6 ("never let self-improvement become uncontrolled self-modification"), and passing tests alone are not evidence of correctness or safety.
- **Keep status quo without an ADR.** Rejected: the principle already holds in code but is written nowhere, so nothing would stop a future change from eroding it.
