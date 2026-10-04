# ATLAS CHECKPOINT — Phase 4: Experiment Manager v1 governance closure (2026-10-04)

**Objective:** record the owner's acceptance of Experiment Manager v1 (`GRANT-EXPMGR-V1-RESEARCH-ONLY`, registry v5.86) against P4-4 and P4-7, and the findings explicitly deferred. Governance record only; v5.86 is not edited (successor-record rule).

**Completed**
- **P4-4: ACCEPTED** by the owner. The implementation satisfies its current acceptance scope.
- **P4-7: SATISFIED.** Fresh independent review (Opus 5.5, read-only, 2026-10-04) result: **READY_FOR_GOVERNANCE_CLOSURE**. The independent reviewer found **no HIGH findings** (and no BLOCKING).
- H1 (read integrity), M1 (supersession) and M2 (evidence binding) are closed and **not reopened**. M2 is closed with the residual recorded as NEW-M1 below.

**Files changed (to be committed):**
- `research/experiment_manager.py` (new)
- `tests/test_research_experiment_manager.py` (new)
- `tests/architecture/test_experiment_manager_isolation.py` (new)
- this checkpoint (new)
No other file changed. `governance/current/ATLAS_MILESTONE_REGISTRY_v5.86.json` is unchanged (SHA256 `085639f3cc1aec60a669260f88e4953dabde2ee14cbecf69b61561795118ba4d`). No production/runtime file changed.

**Tests (Python 3.13.12)**
- Experiment Manager functional tests: **82 passed**
- Isolation tests (`tests/architecture/test_experiment_manager_isolation.py`): **6 passed**
- Architecture suite: **95 passed** (89 baseline + 6)
- Full suite: **6814 passed, 0 failed, 12 skipped**
- **71/72 discrepancy explanation:** 71 was the earlier Experiment Manager test delta; the full-suite increase included one automatically generated case from the existing research-isolation parametrized test. (Owner-supplied explanation; recorded as stated.) The test-file counts above are 82 + 6 = 88 for this module.
- Collecting the suite without the two new test files gave 6738 tests in the reviewer's environment, versus the 6725 + 12 baseline in v5.86: an environment-level difference not caused by this change. UNKNOWN beyond that; not further investigated.

**Architecture decisions:** Experiment Manager v1 is **research-only and in-memory**. It imports only stdlib and `research.hypothesis_registry` / `research.lifecycle` (ADR-0009); no runtime module imports it; SUPPORTED is unreachable (no registered p-value procedure or power analysis); REJECTED requires criteria sealed at pre-registration; a verdict carries no authority.

**Deferred findings (NOT fixed; none is to be marked fixed without a new, separately authorized change)**

MEDIUM
- **NEW-M1:** verdict read paths (`verdicts`, `latest_verdict`, also `runs`/`effective_runs`/`log`) can return a stale verdict after the underlying registry evidence changed; only `experiment()` and `evaluate()` and writes detect it.
- **NEW-M2:** REJECTED relies on a caller-claimed `sample_size` and format-checked (not existence-checked) `evidence_refs`.
- **NEW-M3:** the Hypothesis Registry seal is unkeyed and re-sealable, so hindsight rejection criteria can enter before Experiment Manager registration (also `preregistered_at` is caller-controlled). Treated as a registry/integrity architecture issue, not an Experiment Manager v1 patch.
- **NEW-M4:** four mutation-survivor gaps in the test suite (evidence pin at status changes; evidence pin in verdicts; `evaluate` idempotency ignoring `evidence_hash`; pre-registration hash pin).

LOW
- **R-1:** process-local, unkeyed hash chain; `log` returns the internal entry objects, so reflection-level mutation with a recomputed hash is undetected.
- **R-2:** `log` stays readable after a halt as untrusted forensic evidence.
- **L-3:** `Experiment.check_plan` is the registry's own mutable-parameters object; altering it breaks the seal and triggers the fail-safe halt.

INFORMATIONAL
- **I-1:** naming collision with the existing organizational `experiment_manager` role (`observability/organization.py`, `atlas_org/permissions.py`), which is unrelated to this module.
- **I-2:** halts and evidence pins are per process; a new manager instance starts un-halted (consequence of no persistence).

Previously listed L1–L5 / U1–U3: not enumerated in the repository; the reviewer covered those topics, but their one-to-one reclassification is UNKNOWN.

**Authority statement.** P4-4 / P4-7 closure grants **NO** Phase 5–10 authority, **NO** live trading authority, **NO** autonomous deployment authority, **NO** W2 (no connection to `core/research_evidence_bridge.py` / `core/application.py`) and **NO** persistence or storage migration. Authority unchanged: production NONE, live DENIED, autonomous deployment DENIED. Production, live and paper effect: NONE.

**Known issues / Risks:** the deferred findings above. None can create trading authority; the Experiment Manager is read by no order path.

**Remaining work:** P4-1, P4-2, P4-3, P4-5, P4-6 (full-suite/boundary evidence for the module is above), P4-8 (owner decision + successor registry). Each deferred finding needs its own authorized change.

**Next exact action:** owner issues the final commit/push command for the four files on the checked-out branch.
