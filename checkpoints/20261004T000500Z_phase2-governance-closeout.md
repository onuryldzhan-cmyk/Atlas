# ATLAS CHECKPOINT — Phase-2 governance closeout (2026-10-03)

**Objective:** record the owner's Phase-2 decisions and audit EXP-002 before closing the governance state.

**Completed:** registry v5.84 (successor of v5.83) records: Phase-2 COMPLETE; policy manifest v1 RATIFIED (manifest file sha256 and integrity digest pinned); DEGRADED audit -> BLOCK_NEW_RISK until restart, never auto-cleared; Windows UNKNOWN; the EXP-002 audit with its governance gap. A new test pins that a later DEGRADED-audit success does not clear the latch. A new test pins the manifest bytes to the ratification record.

**Files changed:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.84.json (new), tests/test_phase2_g1_policy_manifest.py, tests/test_phase2_a3_b1_audit_policy_and_reduce_only.py, this checkpoint. No runtime code changed.

**Tests:** python3.13 full suite 6673 passed / 0 failed / 12 skipped.

**Known issues:** EXP-002 has no registry grant (UNKNOWN). The manifest does not pin EXP-002's parameters (floor, bucket, window, cap). Windows persistence behavior UNKNOWN. The current EXP-002 admission count is UNKNOWN (state lives on the owner's machine).

**Next exact action:** owner decides the two EXP-002 items. Phase 3 has not started.
