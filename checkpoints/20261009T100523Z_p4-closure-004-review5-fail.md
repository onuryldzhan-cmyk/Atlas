# ATLAS CHECKPOINT — P4-CLOSURE-004 remediation, independent review round 5: FAIL (2026-10-09)

**Status: INCOMPLETE — STOPPED for owner decision.** Phase 4 is **not** closed and P4-7 is **NOT MET**. Rounds 1–4 are committed as UNVERIFIED WIP (`8b847f4`, `5a97dd3`) on `claude/exp001-on-owner-lineage`. Round 5 is in the working tree. This file grants no authority. Predecessor: `20261009T094723Z_p4-closure-004-review4-fail.md`.

**Objective:** close R4-1 and R4-2 under the owner's round-5 authorization, then pass a fresh-context review.

## Round-5 changes
- **`tools/strategy_compare.py`:**
  - R4-1:
    - `_window` requires a sealed window that lies wholly after the registration (the later of `preregistered_at` and the registry's genesis time), lasts exactly the sealed `days`, and starts on a whole minute.
    - `_check_rows` requires the data to be exactly that window, one candle per minute.
    - `_check_data` requires the manifest's first, last and row count to match.
    - A registered run downloads exactly its window.
  - R4-2: `canonical_registry()` = `<state root>/research/hypotheses.json`. Any other registry is refused. The docstring states what verification does and does not establish.
- **`tools/backtest_replay.py`:** `_history(..., window=None)`, backward compatible. It reads public history only; no order path.
- **`tools/agent_cycle.py`:**
  - Always re-verifies results against the canonical registry.
  - The binding names only `hypothesis_id`.
  - Launches as registered only once the sealed window has ended; otherwise exploratory.
- **`tools/regime_bar_check.py`:** docstring update.
- **`research/hypothesis_registry.py`, `research/lifecycle.py`:** doctrine notes only (the canonical registry is pinned in tools/; CALIBRATED = study run consumed).
- **Tests:**
  - `tests/test_regime_bar_check.py` rewritten: one exact window per hypothesis, canonical registry, R4-1/R4-2 tests.
  - `tests/test_research_preregistration_enforcement.py`: exact-window datasets, canonical state root, R4-1/R4-2 tests. The agent tests changed because recording no longer reads the binding; each change is documented in the test.

**Architecture decision (owner, 2026-10-09):** the canonical registry is pinned at tools level under the state root's `research/` folder. The registry module keeps no default.

## Tests
- Focused suites + `tests/architecture`: **3587 passed**.
- Full suite on the round-5 tree: **10182 passed, 0 failed, 12 skipped (Windows-only), exit 0**.
- Reviewer 5 targeted run: 3374 passed.

## Review round 5 verdict: FAIL — no BLOCKING/HIGH open; every original and earlier HIGH remediated
- **REMEDIATED:**
  - F-1, F-2, F-3, F-5, F-6
  - N-1, N-3
  - NF-1..NF-7 (NF-8 documented)
  - NEW-1, NEW-2(a), NEW-2(b), NEW-3, NEW-4
  - R4-1 (partial, see R5-3), R4-2
  - The round-4 INFO items
- **PARTIAL, residual documented:** F-4, N-2.
- **NOT VERIFIABLE:** N-4.
- **NEW-5 INFO:** pre-existing generator bug, not remediated.
- The reviewer's end-to-end probe confirmed that a legitimate daily registered study runs, verifies, clears with a complete family, and is refused on a re-run.

### Open findings
- **R5-1 MEDIUM (operational, safety intact):** a registered daily run that the tool refuses stalls the daily strategy research silently and indefinitely.
  - Causes: the universe drifted from `config/universe_selection.json`, or exchange data has a gap.
  - Each `RESEARCH_TIMEOUT_H` it relaunches, exits 2 and writes no result. stderr is discarded, and no exploratory fallback runs.
  - Fix:
    - Check the universe at launch, with an exploratory fallback.
    - Record a refusal the agent logs.
    - Document that a window with gaps can never be run.
- **R5-2 LOW:** the sealed specification binds variant names, not variant arguments or the code version. Fix: seal a digest of the variant arguments (and commit), or document it as a residual.
- **R5-3 LOW:** `_check_rows` validates only the open time. Short rows or NaN prices fail after the run is recorded, which consumes the hypothesis and blocks the family. Fix: validate row structure and numeric fields before `start_study_run`.
- **R5-4 LOW:** guard hook gaps (defense in depth only):
  - glob patterns `**/.e*`, `**/?env` and `**/.*` pass (names only);
  - `https://127.1/` passes the IP-literal check.
- **INFO:**
  - R5-5: "anywhere else is refused" holds per state root.
  - R5-6: exploratory runs can see the sealed window's data first (cross-family residual).
  - R5-7: owner approval is UNKNOWN for the binding file and the result `study` block as new on-disk formats.
  - Historical SC records written before this change still read BETTER (append-only log).
  - An indented ```` ```diff ```` fence passes the diff detection.

## Assessment for the owner
Five rounds have closed every HIGH. The later rounds' findings are progressively narrower: operational behaviour and LOW hardening of the new mechanisms, not evidence-promotion paths. R5-1 is the only finding above LOW.

## v5.88 inputs (prepared, not a record; no signature invented)
Unchanged from the predecessor checkpoints. P4-7 is NOT MET until a review PASSes.

## Next exact action (owner decides)
1. A round 6 for R5-1 (plus R5-3 and R5-2, and R5-4/INFO as documentation), or another path.
2. Whether to commit the round-5 tree as UNVERIFIED WIP (full suite green).
3. Only on an independent PASS: commit/push, then the v5.88 closure proposal. Phase 4 stays OPEN; tasks 005–015 stay BLOCKED.

## Owner decisions after this checkpoint (2026-10-09, in session)
- Round 6 authorized:
  - fix R5-1: launch-time universe check with an exploratory fallback, plus a logged refusal record; document that windows with gaps can never be run;
  - fix R5-3: validate full row structure and numerics before the run is recorded;
  - document R5-2, R5-4 and the INFO items as residuals.
  - Then a 6th fresh review.
- Commit the round-5 tree as UNVERIFIED WIP.
