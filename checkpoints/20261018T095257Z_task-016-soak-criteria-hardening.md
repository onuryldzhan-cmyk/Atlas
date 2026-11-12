# ATLAS CHECKPOINT — Task 016: Soak criteria hardening

## Objective
Implement Task 016 under GRANT-TASK-016-SOAK-CRITERIA-HARDENING (registry v5.100, Phase 2 INVESTMENT ENGINE).
Before day 0 of the paper soak, and so before any result exists, complete the pre-registered criteria the owner chose:
- a benchmark as a PASS condition;
- two robustness checks;
- a drawdown stop.

PAPER only, live authority DENIED, no runtime change.

## Completed
- **Owner decisions** (2026-10-17, in session, after the question "how would an experienced trader do it"):
  - the benchmark and robustness checks are added before day 0;
  - the benchmark is a PASS condition;
  - the drawdown stop is at 10 %;
  - a new task, registry v5.100, full gate.
- **`tools/soak_report.py`**, still read-only, now also computes:
  - **Benchmark.** The equal-weight basket of the 20-coin trade universe, held over each trade's own window, from 1h
    archived bars read immutably. The excess is gross return minus basket return. PASS needs its mean, its
    trade-level lower bound and its day-block lower bound all above zero. BTC alone is shown, not graded.
  - **Robustness.** The day-block bootstrap lower bound of E, and E without the 3 best trades; both must be above
    zero.
  - **Drawdown.** Realized drawdown from the equity peak; 10 % or more prints STOP CONDITION and exits 3.
  - **Fail-closed rules.** A missing figure, a NaN or an unavailable benchmark never counts as met. `--capital` is
    limited to 1–10^12. A basket of fewer than 10 coins is refused.
- **Plan** `docs/operations/TASK015_SOAK_DAY0_PLAN_2026-10-17.md`:
  - sheet lines 5–6 extended and lines 16–19 added;
  - the precedence rule over Task 014 §3;
  - the day-0 pre-condition (owner confirms the agent's definitions) and the Task 016 code check;
  - exit codes;
  - the stop row;
  - the end-of-run fetch of benchmark bars (wait for the last hour to close).
- **Reviews:**
  - 44 FAIL (4 MEDIUM);
  - 45 FAIL (1 MEDIUM);
  - 46 FAIL (2 MEDIUM; the first attempt hit a rate limit and was resumed);
  - 47 PASS (0/0/0; 3 LOW, fixed after the review with tests only and record wording).
  - Details are in v5.100 `task_016_reviews_v5_100`.

## Files changed
- **Commit 1:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.100.json
- **Commit 2:**
  - tools/soak_report.py
  - tests/test_soak_report.py
  - tests/test_task016_soak_criteria.py (new)
  - docs/operations/TASK015_SOAK_DAY0_PLAN_2026-10-17.md
  - packaging maps, regenerated with the commit's files staged
  - this checkpoint
- **Unchanged:** every runtime module, the policy manifest and all parameters.

## Architecture decisions
- **The basket, not the same coin.** The same coin over the same window is circular: it measures only costs.
- **Day-block grading for E and the excess.** Same-day trades in correlated coins are not independent.
- **Immutable read of the market archive.** A read-only WAL connection created `-wal` and `-shm` side files. An
  unfinished write-ahead log makes the benchmark unavailable.
- **Criteria are constants; the three CLI options select inputs only.** Those inputs are printed for the evidence.

## Tests
- **Delta tests:** 103 (32 in test_soak_report.py, 71 in test_task016_soak_criteria.py), all passing on Python 3.13.
- **Mutation:** 98 mutants run on a scratch copy of the repository, never on the repository file: 98 of 98 killed
  in the final run.
- **Full suite (Python 3.13):** 11073 passed, 12 skipped, 0 failed in the final run (11002 at the Task 015 seal plus
  the 71 Task 016 cases). It ran after the last change to the tests and to the record (the
  review-47 entry).

## Current state
Task 016 is implemented and reviewed (review 47 PASS), and committed in two commits on
`claude/exp001-on-owner-lineage`. No soak run has started.

## Known issues / limitations (in v5.100)
- **Owner confirmation before day 0** (plan §2 step 1), UNKNOWN at commit. The owner must confirm the agent's
  definitions:
  - the basket and its slippage bias (about 0.1 pp per trade against the system);
  - day-block grading;
  - three best trades;
  - realized rather than account equity for the drawdown.
- **Benchmark strictness.** A single missing hourly bar makes the benchmark UNAVAILABLE. Whether the fetch tool
  completes on the owner's machine is UNKNOWN. Windows behaviour of the immutable read is UNKNOWN.
- **Expected outcome.** With seven conjunctive conditions, INCONCLUSIVE is the expected common outcome (review 45's
  toy simulation).
- **Not covered by the drawdown stop.** Unrealized drawdown. The 21-day minimum is not enforced by the script.
- **Carried from v5.99.** EXP-002 result UNKNOWN, completeness check gross-only, FinancialStateStore.load not used,
  Windows/Python 3.14 test failures on the owner's machine.

## Risks
None to trading. The changes are one read-only report, its tests and documents.

## Remaining work
- Owner: confirm the definitions (or ask for a basket slippage haircut), run the EXP-002 report, fill sheet lines 1,
  12 and 14, run plan §2.

## Next exact action
Report the commit hashes, the remote state and the owner items. Start nothing on the owner's machine.
