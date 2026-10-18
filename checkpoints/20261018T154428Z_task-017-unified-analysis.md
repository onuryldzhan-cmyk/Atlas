# ATLAS CHECKPOINT — Task 017: Unified analysis (advisory)

## Objective
Complete Task 017 under GRANT-TASK-017-UNIFIED-ANALYSIS (registry v5.101; Phase 4 RESEARCH, with decision memory in
Phase 7 MEMORY). This follows the owner's "Task 017 Completion, Audit, and Final Verification Request" (2026-10-18):
- full suite on Python 3.13;
- an independent review reaching 0 BLOCKING / 0 HIGH / 0 MEDIUM;
- registry v5.101 and this checkpoint;
- packaging maps and the architecture boundary tests;
- two local commits, **not pushed**.

Constraints: advisory only, live DENIED, production NONE, no trading authority.

## Completed
- **`tools/unified_analysis/`.** An advisory pipeline for one coin at one cutoff:
  - a validated market snapshot (Binance spot, or the market archive read immutably);
  - deterministic specialists (technical, regime, liquidity, derivatives, sentiment, macro) and an optional model
    narrative;
  - verification by recomputation, and scenarios built from independence groups;
  - a deterministic prosecutor, plus an optional model court with Court Skill concepts;
  - SignalFusion over the expected roster (NB-4/NB-5);
  - review penalties, a calibration cap, and a risk gate with no override;
  - an append-only, hash-chained experience ledger.
  - The only change outside the package is one line in `tools/ai_gateway.py`, which adds `unified_analysis` to
    AI_AGENTS.
- **Review history:**
  - **F1–F10 and N1–N5** were fixed in the earlier local commits.
  - **Review 48:** H1, M1, M2 and L1–L4.
  - **Review 49:** H-new-1, M-new-1, LOW-1..5 and INFO.
  - **Review 50:** F-50-1 MEDIUM (hindsight records could build the track record), F-50-2 LOW and two INFO.
  - **Review 51:** 0/0/0; F-51-1 LOW and F-51-3/4 INFO were fixed, and F-51-2 was deferred.
  - **Review 52:** 0 BLOCKING / 0 HIGH / 0 MEDIUM / 0 LOW / 4 INFO. The doc and test INFO items were applied; F-52-3
    was deferred.
  - The details are in v5.101 `task_017_results_v5_101` and `task_017_reviews_v5_101`.
  - The reviewers were read-only sub-agents. They are not the owner and give no sign-off.
- **Key behaviour after the remediation:**
  - **Calibration samples:** only predictions with a 24 h horizon whose entry is on the 00:00 UTC grid, one per
    (key, symbol, entry), the first recorded in ledger order.
  - **Record time:** every PREDICTION carries a wall-clock `recorded_at_ms`. A prediction recorded after its window
    began is hindsight and counts only as a miss in the cap: `cap = min(0.50, (fwd_hits + 5) / (fwd_n +
    hindsight_misses + 10))`.
  - **MEASURED** counts forward samples only and is a diagnostic; it never lifts the cap.
  - **Model text:** numbers in model text and in counted charges must be backed by recomputed claims (charges: only
    the claims of the findings they cite). Spaced periods, number words (English), Unicode numerals and digits glued
    to letters are rejected.
  - **Hist roster:** out-of-roster specialists are dropped before scenarios are built.
  - **Outcomes:** an outcome cannot overwrite ledger fields, and `hit` must be a bool.

## Files changed
- **Commit 1:** `feat(task-017): update registry to v5.101`
  - governance/current/ATLAS_MILESTONE_REGISTRY_v5.101.json (a successor; v5.100 is untouched).
- **Commit 2:** `feat(task-017): add unified_analysis tools, robustness checks and tests`
  - tools/unified_analysis/ (12 modules)
  - tools/ai_gateway.py (one line)
  - tests/_task017_support.py, tests/test_task017_unified_analysis.py, tests/test_task017_experience.py and
    tests/test_task017_review_regressions.py
  - docs/architecture/UNIFIED_ANALYSIS.md
  - packaging/REM-001_IMPORT_GRAPH.json, REM-001_RUNTIME_CONSTRUCTION_PATHS.md and REM-001_STATE_AUTHORITY_MAP.md,
    regenerated with the files staged
  - this checkpoint.
- **History:** the earlier work-in-progress commits fc51117, 0040c4b and f287ed0 had been placed on
  `claude/vigilant-maxwell-5vwebp` and pushed there (origin at f287ed0). Their content was recommitted as these two
  commits and applied onto `claude/exp001-on-owner-lineage` by cherry-pick, on the owner's explicit instruction
  (Option 1, 2026-10-18); see registry conflict C-3.
  - Local `claude/vigilant-maxwell-5vwebp` was set back to its remote state (f287ed0); no force push was made.
  - Backups: a git bundle and a working-tree patch, both in the session scratchpad.
- **Unchanged:**
  - the runtime closure (142 modules), every runtime module, the policy manifest and all parameters;
  - `reports/branch_archive/vigilant-maxwell-pre-task017.bundle`, which belongs to another session. It is untracked
    and was neither committed nor deleted.

## Architecture decisions
- **Concepts, not code.** TradingAgents and Court Skill are not imported or vendored; their concepts are adapted on
  Atlas interfaces (C-1).
- **Credited upstream text.** Three pieces of court-skill text are adapted with MIT attribution, verified against
  upstream commit 2abd32d: the prosecutor sentence, COURT_RULES, and the Statistician lens's first sentence.
- **Model output only lowers.** Narrative findings are recorded but never scored. A model charge is at most MAJOR
  and only lowers confidence. Votes never count as verification.
- **The cap is monotone and never above 0.50.** Lifting it above 0.50 is an owner decision.
- **Hindsight evidence only lowers.** Archive replays therefore measure the record but can never support a claim.

## Tests
- **Task 017:** 184 passed (3 test files).
- **Architecture boundary** (`tests/architecture`; the requested `tests/test_architecture_boundary.py` does not
  exist, C-4): 102 passed on the staged tree.
- **Full suite (Python 3.13, `python3.13 -m pytest -q -p no:cacheprovider`):**
  - on the final code: 11257 passed, 12 skipped, 0 failed;
  - on the staged commit-2 tree, after the maps were regenerated: 11257 passed, 12 skipped, 0 failed.
- **Mutation testing** (on a scratch copy, never on the repo): 70 of 70 applicable mutants killed, 0 survived.
- **Test changes, disclosed** (none weakened; review 52 checked the cap-related ones):
  - Two calibration tests were rewritten for the review 48 design.
  - The court test's charge text was changed because "one" became a number word. A new test pins that behaviour.
  - Spaced periods moved from accepted to rejected.
  - Calibration fixtures now state forward counts explicitly.

## Current state
- **Branch:** `claude/exp001-on-owner-lineage`, origin at 8085352 (Task 016) before this work; the two Task 017
  commits sit on top of it, a plain fast-forward.
- **Push:** authorised by the owner's Option 1 instruction (2026-10-18). `owner_final_sign_off` in v5.101 was
  written as PENDING before that instruction and is left as the historical record; this checkpoint records the
  later instruction. No owner signature is created or implied.

## Known issues / Risks
- **Predictive skill is UNKNOWN.** Every threshold and weight is an uncalibrated default.
- **Hindsight classification depends on an honest host clock** (F-51-2, deferred).
- **The ledger has no external anchor** (review 48 M1, deferred). A clean truncation at a record boundary goes
  undetected.
- **Number words are detected in English only.** They can never raise a classification or confidence.
- **The hist roster stops claiming** after 16 settled misses per class (F-52-1, documented).

## Remaining work
- **Owner:** decide on the deferred items listed in v5.101 `deferred_improvements_v5_101`.

## Next exact action
Verify that the remote head of `claude/exp001-on-owner-lineage` matches the local head after the push; then decide
the deferred items.
