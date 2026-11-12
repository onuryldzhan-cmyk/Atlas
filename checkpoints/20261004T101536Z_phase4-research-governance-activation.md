# ATLAS CHECKPOINT — Phase 4 RESEARCH governance activation (2026-10-04)

**Objective:** make the owner's 2026-10-04 decisions durable in a successor registry: Phase 2–3 completed, Phase 4 RESEARCH opened, Experiment Manager v1 granted research-only. Governance record only; no code.

**Completed**
- `governance/current/ATLAS_MILESTONE_REGISTRY_v5.86.json` (successor of v5.85, review approved by the owner 2026-10-04).
  - SHA256 `085639f3cc1aec60a669260f88e4953dabde2ee14cbecf69b61561795118ba4d`. It records the SHA256 of v5.85 (`77f0c23ae150215dad6ef017eca8ca57b81d6c44e36c767a16278fc9efa2d0b8`) as `supersedes_sha256`.
- **Phase 2–3: COMPLETED.** The stale ACTIVE status of `PHASE_2_3_INVESTMENT_ENGINE_AND_RELIABILITY` is corrected in v5.86 only, with a before/after record. **C2 is resolved** by the owner: the canonical roadmap (`governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md`) and the v5.85 `phase_2_3_closure` record are the basis. The sentence "Phase 3 has not been started" in `checkpoints/20261004T092404Z_phase2-final-governance-closeout.md` is kept as a historical contradictory record; that file is unchanged.
- **Phase 4 — RESEARCH: ACTIVE** (`active_milestone = PHASE_4_RESEARCH`). Roadmap Phase 4, not a new phase.
- **Completion criteria P4-1 to P4-8 (accepted):**
  - P4-1 Research Department: studies pre-registered and sealed; `research/` passes the L4 isolation test and stays out of the runtime closure; unregistered experiments are rejected.
  - P4-2 Strategic Scout: external ideas produce only proposal documents; licence/security/compatibility recorded; no automatic code import; external text is never executed as instruction.
  - P4-3 Source & Evidence: CLAIM→SOURCE→EVIDENCE→TIMESTAMP→AGENT→CONFIDENCE→COUNTER-EVIDENCE; removing counter-evidence never raises confidence (NB-4); expected roster denominator (NB-5).
  - P4-4 Experiment Manager v1: all acceptance tests of its grant pass.
  - P4-5 Knowledge Manager: records linked to source and claim; nothing VALIDATED without an owner signature; unknown shown as UNKNOWN.
  - P4-6 Boundary: new modules import no runtime order path, RiskEngine, capital or ExecutionManager; architecture tests green (89); full suite no regression (6725 passed / 12 skipped).
  - P4-7 Independent review: no BLOCKING/HIGH open.
  - P4-8 Completion: owner decision + checkpoint; grants no authority for Phases 5–10, Shadow or live.
- **`GRANT-EXPMGR-V1-RESEARCH-ONLY`: GRANTED.** Research-only: no access to runtime trading decisions, RiskEngine, ExecutionManager, capital or order authority; no new storage schema or migration without separate owner approval.
- **Verdict rules (owner clarification at the v5.86 review):**
  - SUPPORTED needs a registered p-value procedure, power analysis, all required checks, BH-FDR and valid registered evidence; without them the maximum is INSUFFICIENT_EVIDENCE. Those procedures are not part of this build, so SUPPORTED cannot be issued now.
  - REJECTED is permitted only when negative-evidence criteria were defined at pre-registration, are measurable, and are sufficiently met. Missing, corrupt or insufficient data, a missing check or too small a sample is never a reason for REJECTED (it gives INSUFFICIENT_EVIDENCE). No criterion may be added in hindsight. Verdict changes are append-only successor records. No verdict, REJECTED included, creates trading authority.
- **W2 not applied.** The Experiment Manager is not connected to the runtime evidence bridge (`core/research_evidence_bridge.py` → `core/application.py`, ADR-0009).
- **PostgreSQL/pgvector and Phase 7 memory architecture are outside Phase 4.** The old JSON memory files are not used.
- **EXP-002** remains the existing grant in v5.85 (expires 2026-10-16T00:00Z); it is not copied to, amended or extended by v5.86 (v5.86 holds only a reference with v5.85's SHA256).
- **Authority unchanged:** production NONE, live DENIED, autonomous deployment DENIED; live_status BLOCKED. Production, live and paper effect of this record: NONE.

**Files changed:** `governance/current/ATLAS_MILESTONE_REGISTRY_v5.86.json` (new), this checkpoint (new). No code, test, manifest or earlier registry changed.

**Pre-commit verification (python3.13.12):** v5.85 byte-identical to its committed copy; the `core/policy_manifest.py` pin matches v5.85; manifests v1/v2 and `core/policy_manifest.py` unchanged; architecture 89 passed; `test_phase2_g1_*` and `test_phase2_g2_*` passed unchanged; full suite 6725 passed / 0 failed / 12 skipped (baseline).

**Architecture decisions:** the head of the `governance/current` supersedes chain is now v5.86; the EXP-002 grant stays in v5.85 and is verified there by `core/policy_manifest.py`.

**Known issues / remaining UNKNOWN**
- Windows persistence behaviour (file lock, rollback, atomic replace) is unverified on the owner's machine.
- `specification_development_focus` still reads `REM-001` (inherited from v5.85, not changed).
- When the p-value and power-analysis procedures will be written: no grant, not scheduled.
- Current EXP-002 admission count: state on the owner's machine.

**Risks:** none added; the record has no runtime effect.

**Remaining work:** Experiment Manager v1 (research-only), then P4-1, P4-2, P4-3, P4-5, P4-6 to P4-8.

**Next exact action:** BUILD Experiment Manager v1 — research-only, in a separate step: write the architecture test that pins its isolation from RiskEngine, ExecutionManager and capital (P4-6), then its acceptance tests, then the code, using the existing `PreRegistration` / `CheckPlan`. No W2, no PostgreSQL/pgvector, no old JSON memory files.
