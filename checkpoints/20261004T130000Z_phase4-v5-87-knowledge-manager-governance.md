# ATLAS CHECKPOINT — v5.87 Knowledge Manager governance step (P4-5)

**Objective:** Record owner decisions D1–D5, C-1, C-2 for P4-5 in successor registry v5.87. Governance only — no code.

**Completed:**
- Created `governance/current/ATLAS_MILESTONE_REGISTRY_v5.87.json` (supersedes v5.86, `supersedes_sha256` = `085639f3cc1aec60a669260f88e4953dabde2ee14cbecf69b61561795118ba4d`). v5.86 left byte-identical.
- Added: `grant_knowledge_manager_v1_research_only` (GRANT-KNOWLEDGE-MANAGER-V1-RESEARCH-ONLY, GRANTED, research/in-memory only), `p4_5_criterion_redefinition_v5_87` (C-1, C-2; v5.86 wording quoted verbatim), `knowledge_manager_terminology_disambiguation_v5_87`, `p4_5_invariants_added_v5_87`, `preserved_state_v5_87`, `unknowns_recorded_v5_87`. P4-5 entry in `milestones.PHASE_4_RESEARCH.completion_criteria_p4` replaced; grant appended to that milestone's `grants`.

**Owner decisions (2026-10-04):**
- D1: Option A — self-contained HMAC-SHA256 in `research/knowledge_manager.py`, byte-compatible with existing owner signing-body semantics where applicable, no `atlas_org` import, caller key pinned by fingerprint, no AUTHORITATIVE without a valid owner key, no real keys in tests/repo.
- D2: CONTESTED is a distinct status; contradictions block VALIDATED/AUTHORITATIVE; withdrawing counter-evidence requires a new validation.
- D3: validator ≠ author; owner is never validator; validation and signature are separate lanes.
- D4: only submitter or owner may withdraw, non-empty reason; withdrawal changes evidence-set hash and invalidates validation/signature basis.
- D5: ≥1 verifiable supporting evidence for VALIDATED; multiple sources not required — explicit v1 boundary, not UNKNOWN.
- C-1: lineage SOURCE → CLAIM → EVIDENCE → VALIDATION → VALIDATED → OWNER SIGNATURE → AUTHORITATIVE; signature only after VALIDATED, never creates/promotes it.
- C-2: UI/endpoint verification deferred; P4-5 not wired into web_app, observability, tools, runtime, or W2.

**Architecture decisions:** Knowledge Manager v1 is separate from `knowledge_manager_agent` (lesson workflow, unchanged).

**Tests:** None run (out of scope). Structural validation only: JSON parses; v5.86 SHA256 unchanged; supersedes/sha linkage correct; unrelated top-level records equal to v5.86.

**Current state:** production NONE, live DENIED, autonomous deployment DENIED, live_status BLOCKED, no Phase 5–10 authority, no W2, no persistent memory, no PostgreSQL/pgvector, no legacy-memory migration/reuse. `core/policy_manifest.py` untouched. Uncommitted.

**Known issues / UNKNOWNs:** Windows persistence behaviour; specification_development_focus REM-001 (inherited); p-value/power-analysis timing; exact existing owner signing-body byte layout (verify at implementation); timing of deferred UI/endpoint verification.

**Risks:** D1 byte-compatibility must be verified against the existing signer without importing it.

**Remaining work:** Implement `research/knowledge_manager.py` + tests under the grant (separate step); P4-1..P4-4, P4-6..P4-8.

**Next exact action:** Owner reviews v5.87 and this checkpoint, then authorizes commit, then a separate implementation step for Knowledge Manager v1.
