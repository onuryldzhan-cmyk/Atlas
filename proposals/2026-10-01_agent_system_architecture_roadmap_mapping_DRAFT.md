# DRAFT — Atlas Agent System architecture: placement into the 0–10 roadmap

Status: **DRAFT — owner decision required.** This file changes nothing. It does not
edit `governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md`. If approved, the
placement is recorded as a new versioned successor record (v1.1), per CLAUDE.md
Governance. No new phase is created. Every item is placed in an existing phase.

Source: owner message of 2026-10-01 (agent types, start-up protocol, decision chain,
Evolution loop, the 18 external references).

## 1. Facts this rests on (verified in the repository this session)

- The roadmap has 11 fixed phases. The current focus is **Phases 2–3 (Investment Engine +
  Reliability)**. Ordering rule (§94/§96): the full agent organization and self-evolution
  are end goals, and they are not built before Phases 2–3 are sound.
- `feature_expansion_status = PAUSED_PENDING_REM_GATE_1` (the roadmap record, §4).
- Authority: production NONE, live DENIED, autonomous deployment DENIED.
- Existing pieces: `atlas_org/{manager,tasks,proposals,permissions,memory_records,security_review,strategy_registry}.py`,
  `tools/agent_cycle.py` (market_regime, strategy_lab, knowledge_manager, red_team, self-review),
  the hash-chained records under `governance/records/`, and the deterministic risk → capital → execution chain.

## 2. The owner's design largely matches the existing doctrine

These are already rules in CLAUDE.md or the roadmap, so they need no new decision:
- AI proposes and deterministic code enforces. An LLM never sends orders.
  This is the Decision → Risk → Capital → Execution Manager → Exchange flow.
- The Code Agent never deploys alone. Changes go through review, security, audit and the owner (ADR-0011, Phase 9).
- Learning, self-modification and live capital are three separate authorities.
- NO ACTION / WAIT / BLOCKED count as real decisions. Consensus is not evidence (NB-4/NB-5).

## 3. Placement (What → Where → Decision)

ACCEPT means it is placed in that phase and done in phase order. DEFER means it is placed, but it waits for a gate.

| Item from the owner design | Phase | Decision | Note |
|---|---|---|---|
| **Agent State Registry (single source of truth; READY/RUNNING/WAITING/BLOCKED/DEGRADED/FAILED/DISABLED/REVIEW_REQUIRED)** | 3 (status API, self-monitoring) | **ACCEPT — first** | This is an operational-truth bug: the UI shows "no agent running", "6/20" and "running" at the same time. CORRECTNESS priority. |
| Agent / service / worker / governance / human distinction in the registry | 3 + 6 | ACCEPT | It explains "36 units / 20 agents". |
| Data Quality hardening (freshness, gaps, outliers, cross-source); DEGRADED blocks **new entries** deterministically | 2 | ACCEPT | A deterministic gate, not an LLM. |
| Deterministic critical-failure rules (Risk down / data stale → NEW ORDERS BLOCKED) | 2 + 3 | ACCEPT | It must be code-enforced. |
| Incident Manager (detect → classify → isolate → recover → verify) | 3 (§38) | ACCEPT | Already in the phase scope. |
| Boot protocol (system → security → data → agent health → regime → snapshot → monitoring) | 3 (supervisor §28) | ACCEPT | It is deterministic orchestration. |
| Event types (MARKET_UPDATE, REGIME_CHANGE, DATA_DEGRADED, ORDER_FILLED…) and event-driven wake-up | 1 (event bus §57) | ACCEPT | It reuses the existing event bus. No new framework. |
| Portfolio Manager (exposure, concentration, allocation) | 2 (§23–26) | ACCEPT | S1 sleeves and the limits card are the start. Correlation needs a data source first (Atlas has none yet). |
| Risk Manager umbrella (PASS / REDUCE / BLOCK) over the existing risk engine | 2 | ACCEPT | The deterministic engine stays the authority. |
| Execution Manager vs Execution Engine split (Hummingbot Controller/Executor) | 2 | ACCEPT (study) | Compare with the current ExecutionManager before changing anything. |
| Position Manager (thesis validity, exits) | 2 | DEFER | It waits on the regime-filter and sleeves results. |
| Performance Analyst + Post-Mortem (incl. "did the change really improve Atlas?" before/after) | 4 + 9 | ACCEPT | It grows out of `performance_report`. Dashboard v2 already plans a Trade post-mortem view. |
| Experiment Manager (hypothesis, control, costs, OOS, stop rules) | 4 (§36) | ACCEPT | The first subject is SA-FEE-DRAG.1. |
| Strategy Board, Strategy Comparison → candidates | 4 | DEFER | It waits on strategy_compare evidence (SC-* records). |
| Memory validation (Observed → Repeated → Validated → Trusted) | 7 | ACCEPT | knowledge_manager already refuses to promote to VALIDATED alone. |
| Evidence independence / source overlap (5 votes ≠ 5 evidences) | 2 (decision intelligence) | ACCEPT | NB-4/NB-5 tests are required. |
| Signal strength vs decision confidence split | 2 + 8 | ACCEPT | Dashboard v1 already shows a band, not a raw %. |
| Atlas Manager three-way split (Investment / Operations / Evolution) | 6 | DEFER | Only after Phases 2–3 are sound (ordering rule). |
| Assistant Manager (retry, handoff, normalization) | 6 | DEFER | Same reason. |
| Task state machine + worker claim/lock/heartbeat ("çalıştırıcı bekliyor") | 6 | DEFER | Same reason. It also needs AI-001 (an LLM executor). |
| Standard machine-readable agent result object; immutable Decision Object | 1 (canonical contracts) | ACCEPT | It is a contract only. Decision Trace (Dashboard v2) reads it. |
| Agent permissions per unit | 5 (§46) | Exists | `atlas_org/permissions.py`. Extend it, don't rebuild it. |
| Security Guardian vs Security Auditor | 5 | DEFER | The Guardian exists. The Auditor is a role on the existing review step. |
| Independent Auditor (process compliance, ≠ Red Team) | 6 | DEFER | |
| Chief Architect between proposal and Code Agent | 6 | DEFER | |
| Context isolation, model routing, cost telemetry | 6 (§50–52) | DEFER | |
| Evolution Manager / Evolution loop (self-review → improvement pipeline) | 9 | DEFER | It builds on `executive_assistant` self-review and T-00xx tasks. It is not a new system. |
| Technology / open-source scout | 4 (§10) | DEFER | It must go through Discover → License → Security → Quality → Compatibility. |
| Sentiment expansion (news, social, funding, OI) | 2 | DEFER | No source exists. It is not shown in the UI until one does. |
| Attention Center, Why-not, Decision Trace | 8 | ACCEPT | v1 is done (Attention, Why/Why-not). Decision Trace is v2. |
| Adopting LangGraph / TradingAgents / LEAN / Qlib / CCXT etc. as dependencies | — | **REJECT for now (study only)** | Rule: no new dependencies, and Framework ≠ Atlas. Each repo becomes a RESEARCH MODE report (REUSE / ADAPT / REJECT per the 12 headings). Nothing is installed. |

## 4. Step-by-step order (what we will actually do)

Each step is one package: INSPECT → PLAN → IMPLEMENT → TEST → REVIEW → checkpoint. Owner approval is needed where it says so.

**Stage A — Phases 2–3, the current focus**
1. **Agent State Registry**: one read-only state source. Agents page, HQ and Overview all read it. It fixes the contradictory "running" displays.
2. **Data Quality gate**: deterministic. DEGRADED/stale data → no new entries. Tests cover stale, gaps, outlier and cross-source cases.
3. **Critical-failure rules**: risk engine unavailable → NEW ORDERS BLOCKED. Existing positions follow predefined rules only. *(CRITICAL tier, independent audit.)*
4. **Boot protocol in the supervisor**: ordered health checks before the market loop trades.
5. **Incident records**: detect/classify/recover written to INCIDENTS memory. The Attention Center already reads them.
6. **Owner switches still pending**: F-3/F-4 on, S1 `risk_bucket` persistence (migration checklist). *(Owner approval.)*

**Stage B — finishing Phase 2 decision quality**
7. Canonical Agent Result and Decision Object contracts (Phase 1 contract work).
8. Evidence independence in aggregation plus the signal strength / decision confidence split. NB-4/NB-5 tests.
9. Portfolio Manager v1 (exposure / concentration → PASS / REDUCE / BLOCK as a deterministic check) and the Risk Manager umbrella.
10. Dashboard v2: Decision Trace + Trade post-mortem view.

**Stage C — Phase 4 research**
11. Experiment Manager v1, run first on SA-FEE-DRAG.1.
12. Performance Analyst with a before/after "did it improve?" measure.
13. External architecture study: the 10 repos as RESEARCH MODE reports (no install, no code copy).

**Stage D — Phases 6/7/9, only after Stage A–B gates close**
14. Task state machine + worker claim/lock/heartbeat. Needs AI-001.
15. Atlas Manager split, Assistant Manager, Chief Architect, Independent Auditor.
16. Memory validation ladder.
17. Evolution loop on top of self-review. Every change still goes through Proposal → Review → Security → Audit → Owner.

**Never in this plan:** an LLM placing orders, an agent raising its own permissions, live trading,
or new phases.

## 5. Decision required from the owner

1. Approve this placement → it is recorded as successor roadmap record v1.1 (the original stays as is).
2. Confirm that Stage A step 1 (Agent State Registry) is the next package.
