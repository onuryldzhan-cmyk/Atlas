# ATLAS CHECKPOINT — Task 014: Paper Environment Long-Term Verification

## Objective
Implement Task 014 under GRANT-TASK-014-PAPER-ENVIRONMENT-LONG-TERM-VERIFICATION (registry v5.98, Phase 2 INVESTMENT
ENGINE):
- evaluate EXP-002 against its v5.85 criteria;
- audit the paper-only locks;
- write the long-term paper soak plan.

PAPER only, live authority DENIED, no change to trading behaviour.

## Completed
- **Owner decisions** (2026-10-17):
  - Phase 2 INVESTMENT ENGINE;
  - evaluate EXP-002 and write a soak plan;
  - audit and test the existing locks, with no new lock mechanism;
  - final sign-off on the work and on v5.98.
- **Conflicts C-1..C-3** recorded in v5.98: no "Phase 4 real-time paper deployment" in the roadmap; real-time market data
  already integrated; EXP-002's evidence is not in the repository.
- **EXP-002 evaluation: UNKNOWN here.**
  - The evidence is on the owner's machine.
  - `python -m tools.exp001_report --experiment EXP-002` is the read-only report, and it applies the 30-trade minimum.
  - Since 2026-10-16T00:00Z the experiment admits nothing, and the manifest check stays MATCH.
  - The design record's "reference" is undefined; reading it as the policy-floor group is an inference for the owner to
    confirm.
- **Paper-lock audit.**
  - Five guards read and probed: main.py's fixed PAPER; `core/atlas_config.load_config`; `core/policy_manifest`;
    ExecutionManager's live authority; no live adapter.
  - One LOW gap, fixed: `AtlasApplication` stored the mode string as given while ExecutionManager normalised it.
  - It now strips and upper-cases the mode and refuses anything but PAPER or LIVE at construction.
  - `main.py` is unaffected.
- **Soak plan** (DRAFT; every number is the owner's to set before the run). It is in the verification document:
  - at least 21 days, target 100 closed trades, capped at 42 days;
  - net = gross P&L − recorded entry fee − estimated 0.1 % exit fee;
  - PASS only at 100 or more trades with E > 0 and a bootstrap lower bound > 0;
  - fill model LAST_PRICE;
  - fresh venue rules for the whole run;
  - supervised launch;
  - restart drills on days 3, 7, 10 and 14;
  - stop conditions.

## Files changed
- **Commit 1:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.98.json.
- **Commit 2:**
  - core/application.py
  - tests/test_task014_paper_locks.py (new, 9 cases)
  - docs/operations/TASK014_PAPER_VERIFICATION_2026-10-17.md (new)
  - packaging/REM-001_IMPORT_GRAPH.json
  - packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md
  - packaging/REM-001_STATE_AUTHORITY_MAP.md
  - this checkpoint
- **Unchanged:** every other runtime module, the policy manifest, and all experiment parameters.

## Architecture decisions
- **No new mode or lock mechanism.** The existing five guards stand; only the mode reporting was made consistent.
- **Normalisation is shared.** The application normalises the mode exactly as ExecutionManager does.
- **Soak numbers stay proposals.** Fixed in advance by the owner, never after seeing results.

## Tests
- **Full suite:** 10970 passed, 12 skipped, 0 failed, from the final run before commit on 2026-10-17. That is the 10961
  tests at Task 013's seal plus the 9 Task 014 cases.
- **After that run,** only the v5.98 record's sign-off fields changed. The registry-reading and architecture tests
  were re-run on it.
- **Mutation testing:** removing the refusal, removing the strip, allowing SHADOW, and removing the upper-case are all
  caught by the 9 tests.

## Reviews (fresh context, red team, threshold 0 BLOCKING / 0 HIGH / 0 MEDIUM)
- **Reviews 37 and 38: FAIL**, all findings in the soak plan or the record:
  - 37: the profit formula double-counted slippage and assumed stored exit fees; the fill model was unpinned; the venue
    rules go stale mid-run.
  - 38: the restart drills used an unsupervised launch.
- **Review 39: PASS (0/0/0; 4 LOW, 6 INFORMATIONAL).** Its LOW items were fixed in the document, a test comment and
  the record, after the review. Details are in v5.98 under task_014_reviews_v5_98.

## Current state
Task 014 is implemented, owner-signed and ACTIVE in v5.98. No soak run has started.

## Known issues / limitations (all recorded in v5.98 or the verification document)
- **EXP-002 result.** Unknown until the report is run on the owner's machine.
- **EXP-002 reference.** The comparison group is an inference awaiting the owner's confirmation, and it holds every
  attributed trade not tagged EXP-002, including EXP-001 trades.
- **No tool for E.** None computes E, E% or the seeded bootstrap. The owner approves a small read-only script, or an
  existing report's figures, before day 0.
- **Soak numbers.** Not yet set by the owner: duration, trade target, thresholds and any minimum-EV floor.
- **Trades per day.** Unknown.
- **Main switch.** `main.py` still has the EXP-002 switch on; turning it off changes the manifest comparison and is a
  separate governed decision.
- **Carried from v5.96/v5.97.** The apprentice-test flake, the map generator's first-character bug, and the
  incident_report severity question.

## Risks
None to trading. The only code change is a construction-time check that `main.py` never trips.

## Remaining work
- The owner closes Task 014.
- Task 015 initiates the paper soak: the day-0 plan and its pre-registration.

## Next exact action
Present the commit hashes and the Task 015 day-0 plan, with v5.99 drafted for sign-off. Start nothing before the owner
signs off.
