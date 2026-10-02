# ATLAS CHECKPOINT — experience panel, polling, lesson proposals (2026-10-02)

**Objective:** continue the owner's recommended order (options 1, 3, 6) and harden weak spots incl. the dashboard.

**Completed (branch claude/exp001-on-owner-lineage, all pushed):**
- 348d0e8 experience agent streams lesson aggregates (2.8M-row CSV never loaded); split at the time midpoint.
- e75fa61 + 60d6fde + cd7212a: /research "Deneyim" pane + loopback /api/experience. observability/experience_view.py reads only
  <runtime.state_directory>/research/experience/state.json (web layer imports no core; tools/ is outside the runtime distribution).
  e75fa61 alone broke 9 architecture tests; fixed in 60d6fde, inventories regenerated with tools/build_architecture_inventory.py.
- 945a0b4 scheduler: an exception between _begin_execution and _finish_execution now releases active_executions (test fails pre-fix).
- 42aff7a + 6aa54ae dashboard: window.atlasPoll in _atlas_theme.html (no polling in hidden tabs, no overlap, wait capped);
  verified in Chromium. Pattern from TanStack Query / SWR defaults.
- 6dcd976 option 3: a candidate lesson stable for STABLE_RUNS=14 consecutive replayed days is filed as an XL-* proposal CREATE
  (actor experiment_manager). Draft only, never applied; no duplicate while one is open.

**Tests:** full suite 6379 passed, 12 skipped (after 6dcd976).

**Known issues:** test_c2_failure_after_booking… flake not reproduced (8 isolated runs + 3 full runs green); left untouched (execution-critical, no evidence).
T-0013 _execute_decision refactor deferred by the owner.

**Owner standing preferences (persist):** answers in Turkish, one command per line; commit after each step;
use ideas ONLY from high-star GitHub repos (verify star count; unverified repos are not idea sources).
Prompt Master skill evaluated: decision B (only for first drafts of vague complex tasks; not for audits/execution/migration).

**Remaining work:** option 4 EXP-002 decision report after 2026-10-16; option 7 deferred.

**Next exact action:** owner pulls and restarts (window 1: git pull origin claude/exp001-on-owner-lineage; python -m tools.start_atlas),
then checks /research "Deneyim" and python -m tools.agent_report --n 1 after 20 minutes.
