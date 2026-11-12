# ATLAS Roadmap — Phase 0–10 Enumeration (v1.0)

> **Lineage note (2026-09-28):** first recorded on the non-canonical parallel branch `claude/vigilant-maxwell-5vwebp` as registry v4.90, a number that collides with the owner's own v4.90. The owner designated the local lineage canonical; this document is re-recorded there in `governance/current/ATLAS_MILESTONE_REGISTRY_v5.02.json` (`parallel_lineage_reconciliation`). References to v4.90 below mean the parallel-branch record.

- **Record type:** governance conflict resolution (C1) and evidence record (C2)
- **Date:** 2026-09-28 (UTC)
- **Registry:** `governance/current/ATLAS_MILESTONE_REGISTRY_v4.90.json`, block `roadmap_enumeration_and_ai_independence_adr_result`
- **Companion ADR:** `docs/adr/0011-ai-independent-deterministic-core.md`
- **Authorization:** owner decision in the Claude Code session of 2026-09-28. The owner selected option "B + ADR". The option was worded as: record the owner's 0–10 vision as the official roadmap, close the open C1/C2 conflicts, and add the AI architecture principles as an ADR in the same package. No registry grant identifier was cited, so the grant identifier is **UNKNOWN**.
- **Authority effect:** NONE.

---

## 1. Why this record exists

CLAUDE.md says Atlas has a *fixed 0–10 phase roadmap*. It also says new ideas are distributed into existing phases and never form a new one. No document in the repository enumerated those phases.

The registry has carried that gap as conflict **C1** since at least v4.29/v4.30 (`C1_NO_DOCUMENT_ENUMERATES_PHASE_0_10_ROADMAP`). It carried a sibling conflict **C2** alongside it (`C2_ACTIVE_MILESTONE_FIN_004_1A_C1_HAS_NO_STATUS_OBJECT`). Both were placed out of scope by the owner every time until now (`governance/ATLAS_RESEARCH_STREAM_RECONCILIATION_v1.0.md:285-288`).

Without an enumeration, CLAUDE.md's "Where (which existing phase)" field in the new-idea evaluation format could not be filled against anything written. The registry itself relies on that field (for example `where_field_constraint`: "must name an existing roadmap phase from the project's own fixed 0-10 phase roadmap").

This record closes **C1**. It records the evidence for **C2** and leaves C2 **open** for an owner decision (section 6).

## 2. Source of the enumeration

The only enumeration of eleven phases, 0 to 10, available anywhere is the owner's own. It is section 95 ("GERÇEK GELİŞTİRME SIRASI") of the owner's vision message in the 2026-09-28 session. The owner's words that accompany it:

> "Buradaki isimleri mevcut 0–10 ana roadmap'in mantığını koruyarak düşünmek önemli; yeni ana fazlar eklemek yerine yeni özellikleri mevcut fazların altına yerleştiriyoruz."

The owner then chose to have this list recorded as the roadmap. It is recorded verbatim below. Phase names are the owner's. The scope column summarizes the owner's own vision sections and adds nothing.

## 3. The roadmap (canonical from this record on)

| Phase | Name (owner, verbatim) | Scope, from the owner's vision sections |
|---|---|---|
| **0** | FOUNDATION | Repository and runtime baseline, configuration and secret management (§58–59), CI and test base (§60), versioning and rollback discipline (§40–41) |
| **1** | CORE | Single composition root, clean layering (§56), event bus (§57), canonical contracts, data layer separation (§54–55) |
| **2** | INVESTMENT ENGINE | Market data and data quality (§17, §19), strategy, backtest and paper (§20–22), risk engine, capital, position and execution managers (§23–26), durable financial state (§27), reconciliation (§62) |
| **3** | RELIABILITY | Reconnect and resync (§18), supervisor (§28), status API with read-only telemetry separated from actions (§29–30), self-monitoring (§37), incident management (§38), audit trail (§39), observability (§85), recovery, failure and chaos testing in sandbox only (§61) |
| **4** | RESEARCH | Research department (§11), strategic scout (§10), source and evidence system (§69), experiment manager (§36), knowledge manager (§12) |
| **5** | SECURITY/RISK | Security guardian (§9), agent permission system (§46), tool registry and sandbox (§88–89), license governance (§90), emergency stop (§63), live-mode guard (§65), compliance routing to humans (§84), data governance and privacy (§86–87) |
| **6** | ORGANIZATION | Atlas Manager, Assistant Manager, worker agents, chief architect, code reviewer (§4–8), authority levels 0–7 (§3), agent-to-agent protocol and observability (§47–48), cost management and model router (§50–52), proposal and approval systems (§34–35) |
| **7** | MEMORY | Atlas Memory and its layers (§13–14), Obsidian vault (§15), decision memory (§70), knowledge graph (§53) |
| **8** | ATLAS HQ | User dashboard and screens (§76–82), chat interface (§33), phone management and alerts (§74–75), 3D HQ (§31–32, §93) |
| **9** | EVOLUTION | Controlled self-improvement (§66), controlled self-healing (§67), roadmap engine (§71), the development pipeline (§72); the "Atlas Coder" pipeline governed by ADR-0011 |
| **10** | CONTROLLED LIVE | Paper to live transition (§64). It follows the ladder CLAUDE.md fixes: **Paper → Shadow → Small Live → Controlled Autonomous → Advanced Autonomous**. The owner's §64 list has no Shadow step; CLAUDE.md's 2026-09-21 correction governs and is not changed here. |

Vision sections not listed in the table are placed by the same rule when their work is proposed. They are cross-cutting or descriptive: §1–2, §42–45 and §49 (screens and performance, Phases 8 and 3), §68, §73, §83, §91–93, §97.

**Current focus, in the owner's words (§96):** "Investment Engine + Reliability". The order given is:

1. Financial State
2. Reconnect
3. Status API
4. Supervisor
5. Frontend separation
6. Recovery
7. Testing
8. Independent Review

This is Phases 2–3.

**Ordering rule, in the owner's words (§94, §96):** 3D HQ, the full agent organization, autonomous trading and self-evolution are end goals. They are not built before Phases 2–3 are sound.

## 4. What this record does not do

- It opens no phase and advances no milestone.
- It changes no `status`, `implementation_authorized` or `active_milestone` value. `active_milestone` stays `FIN-004.1a-C1` (see C2).
- It does not lift `feature_expansion_status = PAUSED_PENDING_REM_GATE_1`.
- It does not re-sequence `queued_foundation_sequence`.
- It grants no authority. `production_authority = NONE`, `live_authority = DENIED` and `autonomous_deployment_authority = DENIED` are unchanged.
- It supersedes no other framework (section 5). The phase axis is recorded; the other axes stay as they are.
- It does not edit CLAUDE.md. Adding a pointer from CLAUDE.md's "Roadmap discipline" to this record is a Deferred Improvement that needs its own owner decision.

## 5. Relationship to the other frameworks in the repository (advisory crosswalk)

Four structures coexist. They measure different things, and this record makes none of them obsolete:

| Axis | Structure | Where it lives |
|---|---|---|
| **Phase: what is being built** | Phase 0–10 (this record) | here |
| **Certification: what has been proven** | REM-001 gates 1–10 (canonical mapping → … → live trading authorization) | registry `milestones.REM-001.gates` |
| **Progression: how much real capital** | Paper → Shadow → Small Live → Controlled Autonomous → Advanced Autonomous | CLAUDE.md |
| **Delivery levels** | Master plan L0–L6 and Faz 1–4 | `docs/ATLAS_MASTER_PLAN.md` |
| **Program** | AMP-001 phases 0–8 | registry `master_program` |

**Unresolved, recorded rather than resolved:**
- AMP-001 counts phases 0–8.
- The master plan counts Faz 1–4 and L0–L6.
- Neither count matches 0–10.
- AMP-001's `program_governance_profile`, `AMP-001_PROGRAM_GOVERNANCE_PROFILE_v1.0.md`, is referenced but does not exist anywhere in the repository's history (checked with `git log --all` on the unshallowed clone). AMP-001's phase names are therefore **UNKNOWN**, and no phase-by-phase mapping to AMP-001 is asserted.

**Crosswalk.** This table is **INFERENCE**. It is advisory evidence of where delivered and queued work sits. It is not a status certification. "Evidence" means work that exists in the repository; it does not mean the phase is complete.

| Phase | Master plan | Registry items that sit here | Evidence in the repository (not a completion claim) |
|---|---|---|---|
| 0 | L0 (Mevcut/kısmi), Faz 1 | CFG-001, CODE-001, DEP-001; REM-001 gate 2 (reproducible build) | Pre-remediation baseline `fa25d15`; CI pipeline `c7c3a40`; dependency locking `08aadd1`; secret management `3047701` |
| 1 | L1 (Kısmi) | ARCH-001; REM-001 gates 1 and 5 (canonical mapping, core refactoring) | ADR-0001 composition root, ADR-0002, ADR-0003; REM-001 Gate 1 still open |
| 2 | L2 (Sonraki kapı) | FIN-004.1a-C1..C3 (undefined, see C2); DATA-001; REM-001 gate 6 (end-to-end paper) | PAPER execution, risk accounting and rollover, realized P&L booking, venue rules refresh, paper mirror integrity (checkpoints 2026-09-15 to 2026-09-27) |
| 3 | L2/L5 | REL-001, OBS-001, TEST-001, PERF-001; REM-001 gates 3–4, 7 | Crash recovery, sidecar fail-closed, execution audit-trail completeness, read-only loopback operator panel. **Reconnect and Supervisor: status not verified in this session (UNKNOWN).** |
| 4 | L3 (Planlı) | RESEARCH-EDGE-VALIDATION substream; INT-001 (paused) | Research packages A/B/C, ADR-0008 evidence store, ADR-0009/0010 hypothesis registry, sentiment and macro providers, compute engine P1/P2 (outside the runtime closure) |
| 5 | L4/L5 | SEC-001.1, SEC-002; BLOCK3-EXECUTION-SAFETY substream | Sensitive-data redactor, loopback Host-header guard |
| 6 | — | AI-001 (PROPOSED_NOT_SEQUENCED), GOV-001 (SPECIFICATION_COMPLETE), AEPO (SPECIFICATION_ONLY) | No implementation evidence found |
| 7 | — | — | Development-process memory only: checkpoints, registry, ADRs. No runtime institutional-memory implementation found. |
| 8 | — | OPS-001 | Loopback read-only operator panel. This is the CLAUDE.md "lightweight observability panel", not Atlas HQ. |
| 9 | — | — | None. Autonomous deployment authority is DENIED. |
| 10 | L6 (Kilitli), L4 (shadow) | REM-001 gates 8–10 | None. Live is DENIED and `live_status = BLOCKED`. |

**Where the two new ideas of 2026-09-28 go** (ADR-0011):
- AI provider layer and router, with local Ollama as the default: Phase 4 for the first research use, Phase 6 for the router and organization (through AI-001).
- Atlas Coder: Phase 9.
- The AI-independence of the deterministic core is a constraint on every phase, not a phase of its own.

## 6. C2 — `FIN-004.1a-C1` has no status object (evidence; decision required)

The following is verified on the unshallowed clone. It has 276 commits, from `fa25d15` (2026-07-30) to HEAD.

- `FIN-004.1a-C1`, `-C2` and `-C3` occur **only as bare identifiers**:
  - as `active_milestone`;
  - in `queued_foundation_sequence`;
  - as a prerequisite (`FIN-004.1a-C3`) of ARCH-001, CODE-001, OBS-001, TEST-001 and later milestones.
- No file at any revision defines their scope, status or acceptance criteria.
  - `git log -S "FIN-004"` first hits commit `71855a0` (2026-08-08, "docs: reconcile Atlas governance registry").
  - That commit imported registry v4.18 into `governance/history/`, and v4.18 already contains the identifiers undefined.
- Registries v4.0–v4.17 are not in the repository. Where the identifiers came from is **UNKNOWN**.

**CONFLICT**

| | |
|---|---|
| **Expected** | The active milestone has a status object that defines what it is and when it is done. |
| **Actual** | The active milestone and its two queued siblings are undefined identifiers. A chain of queued milestones depends on the undefined `-C3`. |
| **Evidence** | As listed above. |
| **Impact** | Nobody can tell what the "active" work is, or when the foundation queue can advance. Since the IDs were introduced, recent work has run in ratified substreams rather than under the active milestone. |
| **Decision required** | The owner chooses one of the options below. |

**Options:**
- **(a)** The owner supplies the definition of FIN-004.1a-C1/C2/C3 from outside the repository, for example from registries v4.0–v4.17 or an earlier session.
- **(b)** Retire the three identifiers as undefined and name a replacement `active_milestone`. The prerequisite references to `-C3` in the dependent milestones must be re-pointed in the same successor registry.
- **(c)** Leave C2 open.

Nothing is inferred or changed until the owner decides.
