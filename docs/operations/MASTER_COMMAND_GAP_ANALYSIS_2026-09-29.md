# Master Build Command and Vision — gap analysis against the repository (2026-09-29)

**Scope:** the owner's "ATLAS — MASTER BUILD & COMPLETION COMMAND" (§0–61) and the "Tam vizyon" text (§1–97), both received 2026-09-28/29, checked against branch `claude/exp001-on-owner-lineage` at registry v5.58.

**Rule:** the repository and the tests are the source of truth. "Evidence" is a pointer, **not** a completion claim. Nothing is closed without the full gate: tests, independent audit and the owner's decision.

**Phase numbering (CONFLICT, recorded in v5.34):** the command numbers its areas differently from the canonical roadmap (for example, the command's "Phase 6 = Monitoring"). The canonical record `governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md` governs. The vision's §95 list matches the canonical record exactly.

**Legend:**
- **EVIDENCE**: implemented and tested.
- **PARTIAL**: part exists, or it works only on the owner's machine.
- **OWNER**: blocked on the owner's decision or data.
- **NOT STARTED**
- **DEFERRED**: by rule 1/10 or an ADR.

## Organization, governance, memory (command §5–16, vision §3–15)

| Item | Status | Evidence / gap |
|---|---|---|
| Owner is the final authority; agents propose | EVIDENCE | v5.34, v5.39: HMAC-signed owner decisions; APPLIED only after a verified approval |
| Atlas Manager, Assistant Manager | EVIDENCE (deterministic) | v5.35: `atlas_org/manager.py` and `tasks.py`. They are policy code, not an LLM (research lesson: an LLM never routes authority). |
| Worker agents doing the work | PARTIAL / OWNER | Steps are carried out today by development sessions and the owner through the CLI. LLM workers are Phase 6 AI-001, and PART_1 of the spec is missing (Q6). |
| Capability permission model | EVIDENCE | v5.34 `permissions.py`. `financial_execute` and `deploy` can never be granted to an AI unit. |
| Authority levels 0–7 (vision §3) | PARTIAL | Expressed through capabilities and risk levels, not as a numbered level field. |
| Proposal lifecycle and UI | EVIDENCE | v5.34, v5.43. Recommendation, review, owner decision and applied are shown as visibly distinct stages. |
| Code review independence | EVIDENCE | A reviewer can never be the author; the rule is re-checked on replay. |
| Security Guardian | EVIDENCE | v5.36, v5.39, v5.55. AST-based; bound to the evidence; scans the running code. |
| Atlas Memory with provenance | EVIDENCE | v5.34, v5.43. Immutable, versioned; only the owner writes AUTHORITATIVE records. |
| Obsidian vault as the human-readable memory (vision §15) | PARTIAL | The vault exists outside the repository (agent `atlas-obsidian-writer`). Memory records are not yet exported to it: DEFERRED to Phase 7. |
| Knowledge graph (vision §53) | NOT STARTED | Phase 7. Records already link task, proposal and decision. |
| Agent-to-agent message format (vision §47) | PARTIAL | The task log carries: from (actor), task_id, event, payload and time. There is no confidence field. |
| Model router / cost management (vision §50–52) | DEFERRED | Phase 6, after AI-001. No LLM runs in the runtime (ADR-0011). |

## Engineering and self-improvement (command §13, §34–35; vision §66–73)

| Item | Status | Evidence / gap |
|---|---|---|
| Controlled code-change lifecycle | EVIDENCE | Task, research, code, tests, code review, security review, proposal, owner approval (Workflow B test). |
| Self-improvement that only observes and proposes | EVIDENCE | v5.42 self-review; v5.50 agent scorecards. |
| Research output with license/maintenance/security | EVIDENCE | A RESEARCH memory record requires the evaluation fields. |
| Controlled application / deploy | OWNER | Autonomous deployment is DENIED. APPLIED is a recorded state; the deploy itself stays manual. |
| GitHub issue → PR flow (vision §72) | PARTIAL | Work happens on branches with commits; no PR automation. |

## Investment engine (command §17–23; vision §16–27, §62–65)

| Item | Status | Evidence / gap |
|---|---|---|
| Market data, validation, staleness | EVIDENCE (pre-existing) | Block 4 contracts; per-coin staleness in `/api/status`. |
| Risk engine (position, exposure, daily loss, drawdown, buckets) | EVIDENCE (pre-existing) | `core/risk_engine.py`. Limits unchanged in this program. |
| Durable financial state, sequence, identity, recovery | EVIDENCE (pre-existing) | Blocks 5–5L, F-1..F-6. v5.45 health check reads it from a copy. |
| Paper execution, same interfaces as live | EVIDENCE (pre-existing) | Live is DENIED by default (`test_live_execution_is_denied_by_default`). |
| Realistic paper fills (slippage, latency) | OWNER | v5.47 finding; the replay measures it. The runtime change is CRITICAL. |
| No runtime stop-loss / take-profit | OWNER | v5.32 staged design and v5.53 ATR stop exist in the replay only. The runtime waits for evidence from `tools/strategy_compare`. |
| Strategy isolation, versions, backtest → paper → live | PARTIAL | The replay reproduces the real chain. There are no per-strategy version folders: one fused strategy today. |
| Exchange reconciliation (vision §62) | PARTIAL | Internal reconciliation of the execution authorities exists (`tools/reconcile_execution_authorities.py`). Reconciliation against a live venue needs live access (DENIED). |
| Emergency stop (vision §63) | EVIDENCE (pre-existing) | Emergency mode in the runtime status. |
| 20-coin universe from real data | OWNER | v5.51 selection tool. It runs on the owner's machine because Binance is blocked here. |

## Reliability and status API (command §24–27, §39–43; vision §28–30, §37–39, §57–61, §85)

| Item | Status | Evidence / gap |
|---|---|---|
| Health, **readiness, liveness** | EVIDENCE | `/api/health`; **v5.58 `/api/readiness` and `/api/liveness`** (unknown is never ready). |
| Status API that is read-only and cannot restart the backend | EVIDENCE | `tests/architecture/test_web_layer_is_read_only.py`; every route is loopback-only. |
| Supervisor with bounded restarts | EVIDENCE (pre-existing) | `atlas_supervisor.py` and `tests/test_process_supervisor.py`. Five restarts, then it gives up. |
| Reconnect and resync | EVIDENCE (pre-existing) | `tests/test_market_feed_restart_lifecycle.py`. |
| Structured logs with correlation IDs | PARTIAL | Audit trail and telemetry JSONL exist. The task/proposal/decision chain is linked by ids. There is no single correlation id across all logs. |
| Incident management reports (vision §38) | NOT STARTED | Phase 3. The Incident Response unit is ACTIVE only as runtime halts. |
| Chaos / failure injection in a sandbox (vision §61) | PARTIAL | Crash-recovery tests F1–F6. No chaos harness. |
| Performance measurement | PARTIAL | PERF-001 baseline for 5 coins. The 20-coin figure is an estimate (v5.46) that must be measured on the owner's machine. |

## HQ, dashboard, chat (command §28–33, §40, §46–47; vision §31–33, §74–82)

| Item | Status | Evidence / gap |
|---|---|---|
| Sections: Command Center, Agents, Memory, Research, Security, Trading, Analytics, Proposals, Experiments, System, Roadmap | EVIDENCE | `/home`, `/hq`, `/agents`, `/governance`, `/research`, `/security`, `/trading`, `/system`, `/roadmap`. "Development" lives in the tasks/proposals tabs. |
| Real data only; unknown shown as unknown | EVIDENCE | Every page states its source; tests check that pages only read. |
| 3D HQ separated from logic; works with 3D off | EVIDENCE | v5.38: a dependency-free Canvas renderer. Vendoring three.js is DEFERRED (the download was denied). |
| Atlas Chat | EVIDENCE (deterministic) | v5.37, v5.48. It answers from the live portfolio, coins, proposals and health, and cannot act. An LLM chat would be Phase 6. |
| Phone management and alerts (vision §74–75) | DEFERRED by ADR-0012 | The owner decided on a pull surface with no push notifications. The command's §46 agrees. |

## Controlled live (command §45; vision §64–65)

| Item | Status |
|---|---|
| Paper → Shadow → Small Live → … | LOCKED. `live_authority=DENIED`. Shadow is a required gate (CLAUDE.md, 2026-09-21). |

## What remains, in the owner's own order (vision §96: "Investment Engine + Reliability")

1. **Owner data runs** (OWNER_TERMINAL_TASKS §6a, §10–12): the 20-coin universe, the data health check, the performance report, the strategy comparison.
2. **From that evidence, CRITICAL proposals:** realistic paper fills; the winning exit rule. Each needs tests, an independent audit and the owner's signature.
3. **Reliability:** incident reports; one correlation id across logs; a chaos harness in a sandbox.
4. **Owner decisions still open:**
   - Q2 EXP-001 (by 2026-10-12);
   - Q6 AI-001 scope (LLM workers, model router);
   - Ed25519 / `cryptography` for web-side signature verification;
   - `max_positions` with 20 coins.
