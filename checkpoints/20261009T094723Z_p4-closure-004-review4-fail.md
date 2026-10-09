# ATLAS CHECKPOINT — P4-CLOSURE-004 remediation, independent review round 4: FAIL (2026-10-09)

**Status: INCOMPLETE — STOPPED for owner decision.** Phase 4 is **not** closed and P4-7 is **NOT MET**. Round-1..3 work is committed as UNVERIFIED WIP `8b847f4` on `claude/exp001-on-owner-lineage`. Round-4 work is in the working tree, uncommitted. This file grants no authority. Predecessor: `20261009T092311Z_p4-closure-004-remediation-review3-fail.md`.

**Objective:** close the round-3 findings under the owner's round-4 authorization (NEW-1, NEW-2a, NEW-2b closed by recording every run, NEW-3, NEW-4), then pass a fresh-context review.

## Round-4 changes (uncommitted)
- `tools/regime_bar_check.py`
  - NEW-1: a period's span is its earliest→latest candle over all of its symbols. Overlapping spans are refused.
  - NEW-2a: every registered member of the family must be supplied, whatever its specification.
- `tools/strategy_compare.py`
  - NEW-2b: `start_study_run` records the one study run per hypothesis in the registry's existing durable state chain (`advance` REGISTERED → CALIBRATED). It runs after the data checks and immediately before the replay. A second run is refused. `verify_registered_result` requires the result's `run_started_at` to be that recorded transition.
  - NEW-3: `result_digest` covers the study block.
  - Research imports stay lazy.
- `tools/agent_cycle.py`
  - NEW-4: an unreadable or malformed result file is recorded as EXPLORATORY and marked seen.
  - NEW-2b: before launch, the binding is pre-checked with `bind_study`. If the hypothesis is already consumed, unknown, has a different spec, or the binding is malformed, the daily run launches as EXPLORATORY.
- Tests:
  - `tests/test_regime_bar_check.py`: fixture records runs. New NEW-1/2a/2b/3 tests.
  - `tests/test_research_preregistration_enforcement.py`: the launch test now uses a real registration (documented). New NEW-2b/NEW-4 tests.

**Architecture decision (recorded):** CALIBRATED doubles as "study run consumed" for strategy_compare hypotheses. Reviewer 4 found that it does not weaken registry guarantees: `adjudicate_family` still needs a TEST evaluation, and TEST stays single-use. INFO: the meaning is documented in `strategy_compare.py`, not in `research/lifecycle.py`.

## Tests (Python 3.13, `-p no:cacheprovider`)
- Focused suites + `tests/architecture`: 3546 passed.
- **Full suite on the round-4 tree: 10165 passed, 0 failed, 12 skipped (Windows-only), exit 0.**
- Reviewer 4 targeted run: 3357 passed + REM-001 architecture 10 passed.

## Review round 4 verdict: FAIL — no BLOCKING/HIGH open
- REMEDIATED:
  - F-1, F-2, F-3, F-5, F-6
  - N-1, N-3
  - NF-1..NF-7 (NF-8 documented)
  - NEW-1, NEW-2a, NEW-3, NEW-4
- PARTIAL, residual documented: F-4, N-2.
- NOT VERIFIABLE: N-4.
- NEW-5 INFO (pre-existing generator bug, `tools/build_architecture_inventory.py:578-592`): not remediated.
- **NEW-2b: PARTIAL**, because of R4-1.

### Open findings
- **R4-1 MEDIUM**
  - **Attack:** run free EXPLORATORY looks over slices inside a wide sealed window. Then run each registered hypothesis once, through `--dataset`, on the best slice. That slice may even have candles deleted mid-series. The reviewer's probe got "BAR CLEARED".
  - **Gap:** neither the data's coverage of the sealed window nor its contiguity is checked.
  - **Not affected:** the daily agent, which downloads the latest 30 days.
  - **Candidate fix:**
    - For registered runs, require the data to cover the sealed span exactly (consistent with the sealed `days`) at a contiguous 1-minute interval.
    - Or refuse `--dataset` for registered runs unless its sha256 is sealed.
    - Or document it as a residual.
- **R4-2 LOW:** no canonical registry path. The same family can be registered in N registry files and only the best one shown. Fix: pin one canonical registry path, or document it with the cross-family residual.
- **INFO:**
  - A malformed `--dataset` row raises `ValueError` in `_check_rows`. This happens before the run is recorded, so it fails closed.
  - The NEW-3 docstring phrase "data range match it" overstates: only the bounds are checked.

## Remaining residuals needing owner decisions
- NEW-M3/U1: keyed signing.
- F-4: WebFetch exfiltration of repo text.
- Cross-family selection (and R4-2).

## v5.88 inputs (prepared, not a record; no signature invented)
Unchanged from the predecessor checkpoint. P4-7 is NOT MET.

## Next exact action (owner decides)
1. R4-1 path, one of:
   - (a) a round 5: sealed-span + contiguity checks for registered runs, and the R4-2 canonical registry or its documentation;
   - (b) accept and document R4-1/R4-2 as residuals;
   - (c) stop.
2. Whether to commit the round-4 tree as UNVERIFIED WIP (full suite green).
3. Only on an independent PASS: commit/push, then the v5.88 closure proposal. Phase 4 stays OPEN; tasks 005–015 stay BLOCKED.

## Owner decisions after this checkpoint (2026-10-09, in session)
- Round 5 authorized:
  - registered runs must cover the sealed span exactly (consistent with sealed `days`) at a contiguous 1-minute interval, with malformed rows refused;
  - pin one canonical registry path (R4-2);
  - fix the docstring overclaim.
  - Then a 5th fresh-context review.
- Commit the round-4 tree as UNVERIFIED WIP.
