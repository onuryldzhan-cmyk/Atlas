# ADR-0012: Operator-Pull Review Surface, No Push Notifications

## Status

**Accepted** 2026-09-28 (UTC) by the owner ("a ve c başla" in the Claude Code session, answering option A "ADR-0012'yi kabul et"). Recorded in registry v5.07. Proposed earlier the same day in commit 5c955f3.

- Principle only. It authorizes no implementation.
- Amends ADR-0011's governed self-modification pipeline in one respect: how the owner is reached. Every other part of ADR-0011 stands unchanged.
- Authority state unchanged: `production_authority=NONE`, `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.

## Context

ADR-0011 already records the owner's position that:
- the deterministic core runs without AI;
- AI output is always a proposal;
- local Ollama is the default provider;
- Claude Code builds Atlas but is not part of it;
- "Atlas Coder" changes code only through proposal → approval → sandbox → tests → review → security → approval → apply.

What ADR-0011 does not settle is how a pending proposal reaches the owner. On 2026-09-28 the owner decided (verbatim):

> "Atlas tasarımında telefon bildirimi / push notification kısmını kaldırıyoruz. … Atlas seni bildirimle çağırmayacak. Sen istediğin zaman Atlas'a girip … panelden göreceksin."

Repository reality, checked 2026-09-28:
- No push, SMS, e-mail or mobile notification channel exists in the runtime.
- The operator surface is the loopback-only web panel (`web_app.py`, `templates/dashboard.html`).

## Decision

1. **No outbound notification channel.** Atlas does not push proposals, alerts or results to a phone, e-mail, chat or any other external service. This keeps the runtime free of third-party messaging dependencies and credentials, and adds no outbound data path.
2. **The panel is the single review surface, and the owner pulls from it.** Whenever the owner chooses to open Atlas, the panel shows:
   - pending proposals (the ONAYLA / REDDET decision point);
   - agent activity;
   - diffs of proposed and applied code changes;
   - test results, review results and security results;
   - errors and system status;
   - the history of past decisions and applications.
3. **Silence is not consent.** A proposal nobody has reviewed stays pending. There is no timeout-to-approve and no default-approve. Leaving Atlas unattended never advances a proposal. This follows directly from ADR-0011's two explicit approval gates.
4. **Safety does not wait for the operator.** Deterministic protective actions stay local and immediate: risk rejection, exposure blocks, emergency stop, integrity halt (exit 75), single-instance refusal (exit 76). They are recorded for the panel. They never depend on reaching the owner.

## Consequences

- Nothing Atlas proposes can take effect while the owner is away; progress on proposals depends on the owner visiting the panel.
- The panel must make pending items conspicuous when the owner does visit (for example a count on the landing view). That is a Phase 8 (Atlas HQ) design item and is not specified here.
- Loopback-only access stays the security boundary. Remote viewing would be a separate decision with its own security review.

## Not decided here (DEFERRED)

- The proposal store, its schema, and the panel views. These are Phase 8 and Phase 9 work, behind the feature-expansion freeze (`PAUSED_PENDING_REM_GATE_1`).
- Everything ADR-0011 already defers: model choice, AI router, the Atlas Coder implementation.
