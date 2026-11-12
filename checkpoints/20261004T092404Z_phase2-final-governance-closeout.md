# ATLAS CHECKPOINT — Phase-2 final governance closeout (2026-10-04)

Supersedes the EXP-002 "Known issues" of `20261004T000500Z_phase2-governance-closeout.md` (written before the grant existed).
That file is a historical record and is not edited.

**Objective:** close the EXP-002 governance items of the owner's 2026-10-03/04 decisions: explicit registry grant, manifest parameter pinning, runtime-vs-governance verification, boundary tests, final independent check, regression.

**Completed**
- Registry v5.85 (successor of sealed v5.84) holds `exp002_grant` (`GRANT-EXP002-PAPER-CONFIDENCE-EXPERIMENT`, GRANTED): EXP-002, MEDIUM only, floor 0.62, global floor 0.60, cap 30, 2026-10-02T00:00Z to 2026-10-16T00:00Z, HIGH-bucket sizing limits (10% / 20%), PAPER only, funding sentiment OFF, live/production effect NONE. Authorisation: the owner's in-session decision of 2026-10-03; references to the existing design proposal, independent audit and switch-on commit 637da41 only; nothing backdated or invented. Committed earlier as a07344f / a5bdbd6.
- Policy manifest v2 (v1 sealed, untouched) pins 31 switches including all 14 `exp002_*` parameters. Verification only: nothing is applied from it.
- Chain, recomputed independently on 2026-10-04: v5.85 supersedes v5.84; v5.85 pins v5.84 sha `62fe8415…381f` and manifest v2 bytes sha `df3516d3…c077` and its integrity digest; manifest v2 pins v5.84 and names v5.85 without a hash (no cycle); manifest v1 and v5.84 unchanged.
- Runtime check: an `AtlasApplication` built from the exact keyword arguments main.py passes verifies MATCH against the committed registry + manifest with every EXP-002 value as specified.

**Findings of this closeout and their fixes** (code: `core/policy_manifest.py`; no sealed governance file changed)
1. **Windows line endings (found by test, was a latent BLOCK_NEW_RISK):** the byte pins (v5.84 in the manifest, the manifest in v5.85) are sha256 of LF bytes. A CRLF checkout (git `core.autocrlf`, which this repository's `.gitattributes` already anticipates for vendored assets) made the whole chain fail with REGISTRY_MISMATCH. `file_sha256()` now reads CRLF as LF before hashing; any other byte change still changes the digest. Whether the owner's checkout actually has CRLF files is UNKNOWN; this makes the question irrelevant.
2. **Unsealed grant registry (was a YES to "can an EXP-002 parameter change silently"):** editing code + manifest + v5.85 together matched, because nothing pinned v5.85. Its digest is now pinned in code (`EXPECTED_GRANT_REGISTRY_SHA256`, same convention as `EXPECTED_REGISTRY_ID`); any edit is `GRANT_MISMATCH` = BLOCK_NEW_RISK until a governed change updates the pin. One existing test (`test_only_a_coordinated_governed_change_matches`) was changed to also move the code pin; it is stricter, not weaker, and says so.

**Tests added** (tests/test_phase2_g2_exp002_grant.py, only): real-application match against main.py's arguments; a mutation of floor, bucket, cap, start, expiry, sizing mode, HIGH-bucket limit, experiment id, enabled state, PAPER-only and funding sentiment in the real application each => POLICY_MISMATCH + `policy_manifest_block`; sealed-registry pin; CRLF neutrality and no content edit accepted. The new pin/CRLF tests fail on the previous verifier.

**Unchanged and re-verified:** reduce-only SELL executes under any manifest block and under DEGRADED audit; refused only for RECOVERY_REQUIRED, invalid size or unknown durable state. DEGRADED audit stays BLOCK_NEW_RISK in-process (`test_degraded_audit_stays_blocked_in_process_even_after_later_audit_writes_succeed`). PAPER only; LIVE disabled; ExitGuard OBSERVE with 0 rules; EXP-002 itself not enabled/disabled/altered.

**Tests (python3.13.12):** full suite 6725 passed, 0 failed, 12 skipped, 0 collection errors. Architecture 89 passed. Phase-2 files 336 passed. EXP-002 + G1 + G2 targeted: 92 passed.

**Known / UNKNOWN**
- Windows persistence behaviour (msvcrt lock, ftruncate rollback, os.replace): UNKNOWN, needs a run on the owner's machine.
- The manifest check runs at startup only (as designed): a change takes effect on restart and is verified then.
- RiskPolicy limits that bound every BUY but are not EXP-002's own parameters (sleeve shares, max positions, daily-loss and drawdown limits, per-symbol caps) are not pinned by manifest v2. Pinning them is a scope decision for the owner (manifest v3 + new grant), not done here.
- Current EXP-002 admission count: state on the owner's machine (log showed 10/30 on 2026-10-03).

**Next exact action:** none in Phase 2. Phase 3 has not been started.
