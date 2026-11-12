# ATLAS CHECKPOINT — P4-CLOSURE-004 audit remediation: independent review PASS (2026-10-09)

**Status: REMEDIATION VERIFIED.** A fresh-context independent review (round 7) gave a PASS: no open BLOCKING or HIGH finding, and every MEDIUM remediated or documented as residual.

**Phase 4 is NOT closed.** Closing it is a separate owner decision, recorded in successor registry v5.88 (P4-8). This file grants no authority. Tasks 005–015 stay BLOCKED.

Predecessors:
- `20261009T151725Z_p4-closure-004-review6-fail.md` (and rounds 3–5 before it)
- `20261008T233643Z_phase4-closure-status.md`

## Objective
Remediate the independent P4-CLOSURE-003 audit (verdict FAIL; findings F-1..F-6) under the owner's P4-CLOSURE-004 authorization. Then pass a genuinely independent review, commit/push through the owner lineage, and prepare the v5.88 inputs without inventing signatures.

## Completed
Seven remediation rounds were run. Each was followed by a fresh-context independent reviewer (general-purpose subagent, read-only, given findings and requirements only). From round 4 on, every further round was explicitly authorized by the owner in the session.

| Review | Verdict | Findings that drove the next round |
|---|---|---|
| 1 | FAIL | N-1 HIGH, N-2, N-3, N-4 |
| 2 | FAIL | NF-1 HIGH, NF-2 HIGH, NF-3..NF-5 MEDIUM, NF-6/7 LOW, NF-8 INFO |
| 3 | FAIL | NEW-1 HIGH, NEW-2 MEDIUM, NEW-3/4 LOW |
| 4 | FAIL | R4-1 MEDIUM, R4-2 LOW |
| 5 | FAIL | R5-1 MEDIUM, R5-2/3/4 LOW |
| 6 | FAIL | R6-1 MEDIUM, R6-2/3 LOW |
| **7** | **PASS** | R7-1..R7-3 LOW, R7-4/5 INFO (open, below) |

## Final finding status (review 7)
- **F-1 HIGH — REMEDIATED.**
  - Change:
    - `SignalFusion` uses the expected roster as its denominator, and a missing source counts as fully against.
    - `atlas_brain` takes its roster from `AgentFusion.WEIGHTS`.
  - Evidence:
    - 20,000-policy removal probe: 0 NB-4/NB-5 violations.
    - Thresholds unchanged (0.20); confidence can only fall.
- **F-2 HIGH — REMEDIATED.** Strategy studies must be pre-registered in the canonical registry.
  - Registration and run:
    - A run binds to a sealed specification.
    - The window starts after the registry's own genesis time and lasts exactly the sealed days.
    - Data must be exactly that window: contiguous 1-minute candles, fully validated.
    - Each hypothesis gets one durably recorded run (REGISTERED→CALIBRATED).
  - Results:
    - Each result carries a digest over its numbers and study block.
    - Unregistered runs are quarantined as EXPLORATORY.
    - The daily agent and `regime_bar_check` re-verify every result.
    - The regime bar needs non-overlapping time spans and the complete family.
  - End to end: a legitimate registered daily study runs, verifies and is recorded.
- **F-3 MEDIUM — REMEDIATED:** the scout holds no Write.
  - Caveat: the agent-definition change takes effect in a new session. A live check in this session is NOT VERIFIED (definitions are cached per session).
- **F-4 MEDIUM — PARTIAL, documented residual:** a WebFetch to an attacker-chosen public host can still carry repository text.
- **F-5 MEDIUM — REMEDIATED:** surrogate and timezone-overflow inputs are refused with domain errors; the managers do not halt.
- **F-6 LOW — REMEDIATED.**
- **Earlier review findings:**
  - REMEDIATED: N-1, N-3, NF-1..NF-7, NEW-1..NEW-4, R4-1, R4-2, R5-1, R5-3, R6-1, R6-2, R6-3.
  - PARTIAL, documented: N-2.
  - Documented: NF-8.
  - NOT VERIFIABLE: N-4 (the reviewer did not have its content). It was deferred by the implementing session in round 1; its acceptance is the owner's call.
- **Documented residuals (owner decisions 2026-10-09):**
  - NEW-M3/U1: the registry and result files use unkeyed hashes, so anyone who can write the files can forge them. Keyed signing needs an owner decision.
  - Candle prices' authenticity is not verified.
  - R5-2: the specification binds variant names, not their arguments or the code version.
  - R5-4: hook gaps for glob patterns, IP shorthand and indented diff fences.
  - R5-5: "canonical" is per state root.
  - R5-6 / cross-family selection.
  - Historical SC records that still say BETTER.
- **NEW-5 INFO:** pre-existing REM-001 generator bug (`tools/build_architecture_inventory.py:578-592`), out of scope.

### Open LOW/INFO follow-ups (do not block the PASS; candidates for a later scoped task)
- **R7-1 LOW:** a crash *after* the run is recorded writes a FAILED record that says "will be retried", although the hypothesis is spent. Fix: word the record "spent; register a new hypothesis" when the hypothesis is no longer REGISTERED.
- **R7-2 LOW:** the "no result within 6 h" record does not check that the run actually died. A slow live run gets a false FAILED record and a parallel relaunch; this pre-existing relaunch is a liveness issue only. Fix: put the PID in the marker.
- **R7-3 LOW:** a transient empty page or a registry I/O error becomes a permanent REFUSED until the marker is deleted. The REFUSED record does not mention that recovery. Fix: mention it, or treat I/O errors as FAILED.
- **R7-4 INFO:** stderr and tracebacks of background runs are discarded.
- **R6-4 INFO (rest):** WebFetch host names that resolve to loopback (`*.nip.io`) pass the hook; not stated in its docstring.
- **R7-5 / R5-7 INFO:** owner approval is UNKNOWN for the new on-disk formats:
  - `strategy_research_registration.json`
  - the result/memory `study` block
  - `strategy_compare.refused`
  - `strategy_compare.failed`
  - the REFUSED/FAILED statuses

## Files changed (`d2c9296` → this commit)
- **Runtime-adjacent:**
  - `core/decision_intelligence.py`
  - `ai/core/atlas_brain.py` (shadow-only decision intelligence; no order path)
- **Research:**
  - `research/knowledge_manager.py`, `research/experiment_manager.py`
  - `research/hypothesis_registry.py`, `research/lifecycle.py` (doctrine docstrings only)
- **Tools:**
  - `tools/strategy_compare.py`, `tools/agent_cycle.py`, `tools/regime_bar_check.py`
  - `tools/backtest_replay.py` (an optional `window` for the public-history download)
- **Scout boundary:**
  - `.claude/agents/atlas-dashboard-scout.md`, `.claude/hooks/atlas_proposal_write_guard.py`
  - `.claude/settings.json` (deny `~/.atlas/**`)
  - `proposals/README.md`
- **Generated:** `packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md`, regenerated with `tools.build_rem001_gate1_maps`.
- **Tests modified:**
  - `test_phase5_decision_intelligence_foundation.py`, `test_atlas_brain_phase5_shadow.py`, `test_agent_cycle.py`, `test_strategic_scout_boundary.py`, `test_regime_bar_check.py`.
  - Every changed expectation is commented. Reviewers judged that the old expectations encoded the defect or superseded behaviour; none was weakened.
- **Tests new:** `test_research_manager_input_availability.py`, `test_research_preregistration_enforcement.py`, `test_scout_guard_hardening.py`.
- **Checkpoints:** the review-3..6 FAIL checkpoints and this one.

## Architecture decisions (recorded)
1. **Expected-roster fusion (F-1):** missing sources stay in the denominator as worst case; the decision follows the conservative bound.
2. **One run per hypothesis (NEW-2b):** recorded through the registry's existing `advance` path, REGISTERED→CALIBRATED. No new storage schema. Documented in `research/lifecycle.py`.
3. **Canonical registry (R4-2, owner decision):** `<state root>/research/hypotheses.json`, pinned in `tools/strategy_compare.py`. The registry module keeps no default path.
4. **REFUSED / FAILED results (R5-1, R6-1):** non-evidence outcome files. The daily agent records them. REFUSED marks the hypothesis refused, with a documented manual recovery; FAILED marks nothing and is retried.

## Tests (Python 3.13, `-p no:cacheprovider`)
- **Full suite, round-7 tree: 10209 passed, 0 failed, 12 skipped** (Windows-only), exit 0.
- Focused suites + `tests/architecture`: 3626 passed.
- Reviewer 7 targeted run: 3401 passed. Probes: NB-4/NB-5 (20k policies), F-5 surrogates, round-7 end to end.

## Governance / authority
- No risk, confidence or approval threshold was relaxed.
- No trading authority or capital policy changed; no live/real-money path.
- No governance record was written.
- Authority remains `production_authority=NONE`, `live_authority=DENIED`.

## v5.88 inputs (PREPARED, NOT A RECORD; no owner signature invented)
- **Owner in-session decisions on 2026-10-09:**
  - authorization of P4-CLOSURE-004;
  - WIP commits `8b847f4`, `5a97dd3`, `75660d7`, `ba01352`;
  - rounds 4–7;
  - NEW-2b run recording;
  - the canonical registry location (CONFLICT resolved: tools-level pin);
  - R5-2, R5-4 and INFO documented as residuals.
- **Earlier owner acceptances:** KM-A2/KM-A3 (Knowledge Manager); P4-4.
- **P4-7 ("no BLOCKING/HIGH open; evidence: audit report"):** now supported by the round-7 independent PASS. The owner must decide whether a subagent review counts as the required independent audit. Separate-session audit status: UNKNOWN.
- **Owner decisions still needed:**
  - acceptance of the documented residuals and of the open R7-1..R7-3 LOWs;
  - N-4 disposition;
  - approval of the new on-disk formats (R5-7/R7-5);
  - keyed signing (NEW-M3).
- **P4-8:** the owner's closure decision, recorded in successor registry v5.88. Completing Phase 4 grants no Phase 5–10, Shadow or live authority.

## Next exact action
1. The owner reviews this package and decides whether Phase 4 is eligible to close (P4-7/P4-8). If yes, the owner records the decision in successor registry v5.88.
2. Optionally, a scoped follow-up for R7-1..R7-3 (LOW).
3. Tasks 005–015 stay BLOCKED until v5.88 and their own grants exist.
