# ATLAS CHECKPOINT — Dashboard execution-gates CRITICAL gate closure + checkpoint rename

## Objective
Owner brief (2026-09-28 local, branch `research/edge-validation`):
1. Run the independent AUDIT MODE review that the CRITICAL final gate requires over exactly the diff of `696824e` (new `GET /api/execution-gates` + sectioned dashboard with risk-bucket confidence gates). Focus on route exposure beyond the loopback+Host guard, and on whether the bar markers, bucket badge and "execute edilmez" badge are right for LOW/MEDIUM/HIGH and for HOLD, EXCLUDED-agent and no-audit-event cases, never showing a stale or fabricated number. Fix any BLOCKING/HIGH.
2. Rename the misnamed REM-001 D4 checkpoint to its real commit time (owner decision already made), after confirming its commit from git.

Classification: CRITICAL (the diff publishes risk-policy values and adds an operator-surface route). Full final gate applied.

## Completed
- Independent audit of `696824e`: 0 BLOCKING, 0 HIGH, 1 MEDIUM (fixed), 2 LOW (deferred), 2 INFORMATIONAL.
- F1 fix + discriminating regression test.
- Checkpoint rename, content byte-identical.
- Registry successor v4.96.

## Audit findings
- **F1 MEDIUM — FIXED (`6ac94f8`)**: `templates/dashboard.html` `assessRiskGate`. When `execution_minimum_confidence` was null (ExecutionManager value unreadable), a BUY at or above its bucket floor was shown `gate-pass` with "confidence eşikleri geçildi", even though only one of the two gates was known to be cleared. It now shows `gate-unknown`: "risk bucket eşiği geçildi, execution gate eşiği bilinmiyor". Reproduced on the `696824e` template with a node harness; the regression test fails there and passes after the fix.
- **F2 LOW — DEFERRED**: the badge under-reports. ExecutionManager's flat `minimum_confidence` (`LOW_CONFIDENCE`, `core/execution_manager.py:2736`) applies to every action, but "execute edilmez" appears only for BUY. A SELL below the execution gate, or a BUY below it while the risk policy is unreadable, gets no badge. Nothing false is shown, and the execution-gate marker is still drawn.
- **F3 LOW — DEFERRED**: there is no executable JS test for the gate logic, only template-text pins. Behaviour was verified ad hoc with node in the session scratchpad. A JS test runner would be new infrastructure.
- **F4 INFORMATIONAL**: thresholds are read from `runtime.risk_policy`, not `runtime.risk_engine.policy`. Today they are the same instance (`core/application.py:768-778`).
- **F5 INFORMATIONAL**: gates are re-read every 30 s. The latest-risk-decision line can lag by up to 30 s or name an earlier cycle, but it always carries its own action, confidence and time. A failed re-read replaces the cache with "unavailable", so stale values are never kept.
- Route exposure: **no finding**. It uses the same `is_loopback_request` (peer + Host) guard and response shape as its sibling routes and is in the every-GET-route guard test. It publishes only thresholds and per-symbol outcome/reason/action/confidence/time. Every reachable `RISK_REJECTED` reason is a fixed code (`risk_check`, `core/execution_manager.py:3068-3459`), so no free text can leak.
- Threshold correctness, verified from source:
  - The card's `risk_level` and `confidence` come from the same `last_signals[symbol]` dict that `route_execution` hands to `ExecutionManager.execute`. That dict has no `risk` key, so `request.risk` equals the card's `risk_level`.
  - The causation chain `RISK_*` → `EXECUTION_REQUEST_VALIDATED` holds, because `_write_audit_event` returns the event id.
  - `CONFIDENCE_BELOW_POLICY` is emitted only at `core/risk_engine.py:496`.
- Harness results:
  - LOW 60 passes, 59.99 is blocked. MEDIUM 70/69.99 and HIGH 80/79.99 behave the same way.
  - A BUY at CRITICAL or UNKNOWN is blocked.
  - HOLD and SELL are never blocked and never shown as passing.
  - With the execution minimum at 75 and a LOW floor, a BUY at 65 is blocked and the execution gate is named.
  - Not loaded, policy unavailable and route unavailable all show as unknown, and no marker is invented.
  - A symbol with no audit event shows "audit kaydında yok".
  - EXCLUDED agents only affect the agent rows. The gate reads nothing from them.

## Files changed
- `templates/dashboard.html`: one new `else if (execMin === null)` branch in `assessRiskGate` (+4 lines).
- `tests/test_dashboard_execution_gates.py`: +1 test `test_a_buy_is_never_shown_as_passing_while_the_execution_gate_is_unknown`.
- `checkpoints/20260927T200000Z_rem001-d4-generator-recovery-regeneration.md` → `checkpoints/20260927T154626Z_rem001-d4-generator-recovery-regeneration.md` (100% rename). The file was added in `11af030` at 2026-09-27T15:46:26Z (18:46:26+03:00), confirmed via `git log --diff-filter=A`. `20260927T182232Z_dashboard-sections-and-risk-bucket-gates.md` was not touched.
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.96.json` (new, additive). Only `schema_version`, `supersedes`, `registry_status` and the new key `dashboard_execution_gates_independent_audit_and_checkpoint_rename` differ from v4.95. v4.95 is byte-unchanged.
- This checkpoint.

## Commits
- `6ac94f8` fix(dashboard): never show a BUY as passing while the execution gate is unknown
- `f89a746` chore(checkpoints): rename REM-001 D4 checkpoint to its real commit time
- `1da13f4` docs(governance): registry v4.96
- this checkpoint's commit (not self-referenced)

## Architecture decisions
- F1 is fixed in the template only. No API change was needed, because the route already publishes `execution_minimum_confidence: null` honestly.
- F2 was not fixed inline. It is under-reporting (nothing false is displayed), and SELL gating semantics are a separate display decision.

## Tests
- Targeted: `tests/test_dashboard_execution_gates.py` gave **24 passed**. After the registry was added, `tests/test_observability_panel.py` gave **29 passed**.
- Full suite, run once on final code (tracked content = `f89a746`, apart from the out-of-scope local edit to `.claude/agents/atlas-obsidian-writer.md`): **5142 passed, 2 failed, 0 skipped** (312.89 s). 5142 = 5141 (for `696824e`) + 1 new test. The two failures are the known ones: `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports` and `tests/architecture/test_rem001_state_authority_map.py::test_committed_artifact_matches_current_source`.
- Discrimination: the new test **fails** on the `696824e` template and passes on `6ac94f8`.
- Live verification against a real running instance: **NOT_PERFORMED** (only the owner may start one).

## Current state
- The CRITICAL gate for `696824e` + `6ac94f8` is closed at the test-and-audit level. Live verification is still open.
- The "latest checkpoint" filename order now matches commit order: `154626Z` < `155456Z` < `180000Z` < `182232Z` < this file.
- Authority unchanged: `production_authority=NONE`, `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.

## Known issues / risks
- F2 and F3 (LOW) are deferred.
- The two known full-suite failures remain, as before.
- `git commit` prints "failed to delete .git/worktrees/<name>: Permission denied" for 7 stale worktree entries. The commits still succeed; the messages come from pre-existing locked worktree metadata (INFORMATIONAL, not investigated).

## Remaining work
- Owner: restart `web_app` against a real instance and verify the dashboard live.
- Optional future package: F2 (badge for any action below the execution gate) and F3 (executable JS tests for dashboard logic).

## Next exact action
Owner decides on live verification and whether F2/F3 get scheduled into an existing phase.
