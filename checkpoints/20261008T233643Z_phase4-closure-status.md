# ATLAS CHECKPOINT — Phase 4 closure status (2026-10-08)

**Status: INCOMPLETE.** Phase 4 is **not** closed. This file records the gap analysis (ATLAS-P4-CLOSURE-001) and its remediation (ATLAS-P4-CLOSURE-002). It is not a closure record and grants no authority.

**Governance:** registry **v5.87** (`governance/current/ATLAS_MILESTONE_REGISTRY_v5.87.json`, SHA256 `1814d0f0…`), unchanged. Criteria P4-1..P4-8 are quoted from `milestones.PHASE_4_RESEARCH.completion_criteria_p4`. Branch `claude/exp001-on-owner-lineage`, base commit `e20f4d7` (Knowledge Manager v1).

**Objective:** close the remaining Phase 4 criteria with evidence, without reinterpreting them.

## Criterion matrix

| ID | Requirement (v5.87) | Evidence | Status |
|---|---|---|---|
| P4-1 | Studies pre-registered (sealed) in the hypothesis registry; `research/` passes `tests/test_research_isolation.py` and is outside the runtime closure; an unregistered experiment is rejected. | `tests/test_research_isolation.py` (12 passed, incl. `test_research_is_absent_from_the_runtime_closure`); `research/hypothesis_registry.py` seal tests; `test_a1_experiment_cannot_be_created_without_preregistration` (Experiment Manager). | **SATISFIED.** Note: no registry data file exists in the repository, so no study has been registered yet; the rule is enforced, not yet exercised on real studies. Runtime paper experiments EXP-001/EXP-002 are governed by their own grants (v5.85), not by the research registry. |
| P4-2 | External ideas only produce a proposal document; licence/security/compatibility recorded; no automatic code import; external text never executed. Evidence: document template + injection test. | Template: "Proposal format" in `.claude/agents/atlas-dashboard-scout.md` (Discover → License → Security → Quality → Compatibility → Test), `proposals/README.md`. Guard: `.claude/hooks/atlas_proposal_write_guard.py`. **New:** `tests/test_strategic_scout_boundary.py` (24 passed): template steps present, scout holds no Bash/Edit, 17 injected actions denied (Bash, foreign MCP tools, writes into `core/`, `.claude/`, traversal, relative path, subdirectory, README, NTFS stream, missing path, unified-diff and fenced-diff content), unparseable payload fails closed through the real entry point, a proper proposal write is not blocked. With the guard disabled the 17 injection cases fail (checked). | **SATISFIED.** Scope note: the only scout is the dashboard scout (`proposals/README.md`: other domains deferred). |
| P4-3 | Every claim carries CLAIM → SOURCE → EVIDENCE → TIMESTAMP → AGENT → CONFIDENCE → COUNTER-EVIDENCE; removing counter-evidence never raises confidence (NB-4); expected roster denominator (NB-5). Tests: missing evidence, missing agents, conflicting evidence, low confidence, unexpected roster, malformed input. | `data_layer/evidence_store.py` schema (claim text, required sources, payload, aware timestamps, agent, decimal confidence, CONTRADICTS relation). Tests: missing evidence `test_missing_ingestion_timestamp_records_nothing`, `test_removing_evidence_never_raises_the_recorded_confidence`; missing agents `test_fixed_missing_agents_keep_the_full_roster_denominator`, `test_missing_agents_below_the_floor_are_zero_consensus_with_known_coverage`; conflicting `test_directional_disagreement_creates_counter_evidence`, `test_weighted_votes_dissent_lowers_consensus`; low confidence `test_unanimous_weak_agents_are_full_consensus_not_a_certain_win`; unexpected roster `test_unconfigured_agent_names_still_cannot_satisfy_floor`; malformed `test_a_malformed_verdict_is_refused_rather_than_defaulted` and the evidence-store rejection tests; NB-4 `test_removing_an_agent_never_raises_consensus_nb4`, `test_fixed_agreement_never_lowers_and_removal_never_raises`. | **SATISFIED** by existing tests (no change). |
| P4-4 | Experiment Manager grant acceptance tests pass. | Closed earlier (checkpoint `20261004T120000Z_…`). | SATISFIED (earlier). |
| P4-5 | Knowledge Manager v1. | Closed and released in `e20f4d7` (checkpoint `20261008T231945Z_…`). | SATISFIED (earlier). |
| P4-6 | `research/` and new modules import no order path / RiskEngine / capital / ExecutionManager; architecture tests green (89 at 3d496b4); full suite zero regression (6725 passed / 12 skipped at 3d496b4). | Run on `e20f4d7` + `tests/test_strategic_scout_boundary.py`, Python 3.13.12: architecture **102 passed**; full suite **6911 passed, 0 failed, 12 skipped**. Isolation tests for Experiment Manager and Knowledge Manager included. | **SATISFIED.** |
| P4-7 | No BLOCKING/HIGH finding open. Evidence: audit report. | Experiment Manager: fresh independent review, no HIGH. Knowledge Manager: audit CONDITIONAL PASS, no P0/P1 — but performed by the implementing session, not independently. This P4 closure package has **not** been independently audited. | **NOT VERIFIED** — needs an independent (separate-session) review. |
| P4-8 | Owner decision + checkpoint; completing Phase 4 grants no Phase 5–10, Shadow or live authority. Evidence: successor registry. | No owner closure decision recorded; no successor registry. | **OPEN** — needs the independent audit, then an owner decision recorded in a successor registry (v5.88). |

## Changes in this step
- New: `tests/test_strategic_scout_boundary.py` (test-only; exercises the existing guard; no runtime, hook or agent change).
- New: this checkpoint.
No other file changed. No governance record written.

## Remaining limitations
- P4-1 rule not yet exercised on a real registered study.
- P4-2 covers the dashboard scout only.
- Knowledge Manager limitations KM-A2..KM-A8 (accepted / deferred, see its checkpoint).

## Next exact action
1. Independent Phase 4 closure audit (ATLAS-P4-CLOSURE-003) by a session or agent independent of the one that produced this package.
2. If it passes: owner decision closing Phase 4, recorded in successor registry v5.88 (P4-8). Tasks 005–014 stay blocked until then and until their own grants exist.
