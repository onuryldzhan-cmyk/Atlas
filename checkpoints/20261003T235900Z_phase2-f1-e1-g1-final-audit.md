# ATLAS CHECKPOINT — Phase-2 F1/E1/G1 + final audit (2026-10-03)

**Objective:** finish Phase-2: F1 → E1 → G1 → final audit. No Phase 3 work.

**Completed**
- F1 (7c1910c, 01cfb9a): trades are attributed by exact ID. position_id = mint_long_position_id(symbol, opening request_id), and RISK_APPROVED.aggregate_id = request_id. Telemetry decisions now carry request_id. The close is found through RISK_ACCOUNTING_REALIZED_PNL_PREPARED.position_id. A missing link is UNATTRIBUTED. Timestamp matching survives only as an explicit, unambiguous LEGACY_TIMESTAMP fallback for records without a canonical id. Post-mortems record request_id, risk_approval_event_id and the attribution method.
- E1 (0ef808e): confidence is labelled as weighted agent consensus. Fusion output now also reports consensus, coverage, confidence_semantics, calibrated_p_win=None and calibration_ref=None. No threshold changed. Fact found: five barely-BUY agents produce 1.0, exactly like five strong ones.
- G1 (e3f8b12, then the fail-closed fix): core/policy_manifest.py compares 17 critical switches with governance/policy/ATLAS_POLICY_MANIFEST_v1.json. The manifest pins registry v5.83 (sha256) and proposal PHASE2-G1-POLICY-MANIFEST, and records owner_approval=UNKNOWN. main.py runs the check before start: any result other than MATCH gives BLOCK_NEW_RISK for BUYs, SELL reductions follow B1 unchanged, and safe_to_trade becomes False. If the check cannot be applied, Atlas does not start. A manifest can never enable LIVE.
- Maps regenerated: changes are line shifts plus the new L3 module.
- Independent review: 1 MEDIUM (a legacy decision_trace join could merge unidentified events), fixed and re-reviewed. 0 open findings at MEDIUM or above.

**Tests:** python3.13.12, full suite: 6671 passed / 0 failed / 12 skipped (Windows-only). Architecture: 89 passed.

**Known issues / risks:** Windows FlushFileBuffers, msvcrt locking and failed-write rollback are UNKNOWN (not tested on Windows). CapitalReservationLedger archive append is outside DurableAppendContract; no runtime path calls it (compact() has no caller) — INFO. Trades whose telemetry predates request_id stamping show the decision as UNATTRIBUTED (conservative). The manifest integrity digest only detects accidental edits; it does not prove who made a change. The REM-001 map generator drops the first character of some modified-path metadata (pre-existing, cosmetic).

**Owner decisions:**
1. Ratify the policy manifest (owner_approval is UNKNOWN).
2. EXP-002 has no registry record (it was switched on via a main.py comment).
3. The earlier DEGRADED-audit latch decision is still pending.

**Next exact action:** owner review of the Phase-2 result. Run a Windows validation on the owner's machine. Do not start Phase 3 until the owner says so.
