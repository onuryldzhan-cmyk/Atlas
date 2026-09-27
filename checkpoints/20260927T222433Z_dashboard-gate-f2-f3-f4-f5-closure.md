# ATLAS CHECKPOINT — Dashboard execution-gates F2/F3/F4/F5 closure

## Objective
Owner brief (2026-09-28 local, branch `research/edge-validation`): close the
four findings registry v4.97's
`dashboard_execution_gates_independent_audit_and_checkpoint_rename` record
deferred from the `696824e`/`6ac94f8` independent audit — F2 (LOW, the
"execute edilmez" badge under-reports), F3 (LOW, no executable JS test for
the gate logic), F4 (INFORMATIONAL, `runtime.risk_policy` vs
`runtime.risk_engine.policy` identity assumption undocumented), F5
(INFORMATIONAL, 30s staleness window undocumented). No execution/risk/capital
logic changes authorized; stay clear of any parallel SUPERVISOR-1-style work
on `web_app.py`/`panel_sources.py`.

Classification: ROUTINE/STANDARD per `atlas-task-classification-rubric` —
LOW/INFO display-and-test findings confined to `templates/dashboard.html`
and one comment in `web_app.py`, following the existing visual/test pattern,
no new architectural decision. The CRITICAL final gate from v4.96/v4.97 is
not re-invoked by this package.

## Completed
- F2 fixed: `assessRiskGate` in `templates/dashboard.html` now blocks
  (badge + `gate-fail`) a SELL below the execution gate, and a BUY below the
  execution gate even when the risk-bucket policy is unreadable — not only a
  BUY whose readable risk-bucket gate fails. HOLD/WAIT/etc. are excluded
  because `NON_EXECUTION_ACTIONS` never reaches ExecutionManager's
  `minimum_confidence` check (`core/execution_manager.py:189-195`, checked
  before the gate at line 2736).
- F3 fixed: new `tests/test_dashboard_gate_js_execution.py` extracts the
  gate helpers from the template and executes them in a real `node`
  subprocess (skips if `node` is absent), asserting on `assessRiskGate`'s
  actual return value rather than on source text.
- F4 documented: one-line comment in `web_app.py::_risk_policy_gates` at the
  `runtime.risk_policy` read, naming the identity assumption with
  `core/application.py:768-778` as the current evidence.
- F5 documented: one-line comment in
  `templates/dashboard.html::renderLatestRiskDecision` naming the 30s
  slow-panel refresh cadence and the fail-to-"unavailable" behavior.
- Additive governance record: `governance/current/ATLAS_MILESTONE_REGISTRY_v4.98.json`.
- This checkpoint.

## Files changed
(from `git status`/`git diff` at checkpoint time, restricted to this
package's own commits — see "Known issues" for concurrent unrelated changes
present in the working tree from another session)
- `templates/dashboard.html`: `assessRiskGate` extended with `execGateFails`
  (F2, +~27/-10 net over the original function) and a comment at
  `renderLatestRiskDecision` (F5, +5 lines). Commit `462fbf3`.
- `tests/test_dashboard_gate_js_execution.py` (new, 215 lines, 12 tests).
  Commit `98f563c`.
- `web_app.py`: one 5-line comment in `_risk_policy_gates` (F4). Commit
  `32e25c4`. Isolated from a concurrent session's separate, larger,
  uncommitted `web_app.py` changes (new `/api/status` route) by writing an
  isolated copy on top of the pre-session `HEAD`, committing only that
  diff, then restoring the full working-tree file — verified afterward that
  `git diff --stat -- web_app.py` showed only the concurrent session's own
  `+86` lines, not this package's comment (already in `HEAD`).
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.98.json` (new, additive;
  verified programmatically that only `schema_version`, `supersedes`,
  `registry_status` and the new
  `dashboard_execution_gates_f2_f3_f4_f5_closure` key differ from v4.97,
  which is byte-unchanged).

## Architecture decisions
- F2's execution-gate check (`execGateFails`) was added as a value
  independent of the BUY-only risk-bucket gate (`gate.known`/`gate.bucket`),
  so it can fire in the `!gate.known` and `!gate.bucket` branches as well as
  the existing `!isBuy` branch inside the known-bucket branch — no change to
  the already-correct BUY-with-known-bucket path (`floor = max(required,
  execMin)`).
- F3's test extracts source text from the template rather than adding a
  build step or JS test runner as new infrastructure, matching the
  independent audit's own ad hoc approach (reused deliberately, per the
  owner's brief) and this repository's no-build-step template model. Jinja
  `{# #}`/`{{ }}` constructs inside the extracted slice are stripped/
  substituted before the slice is handed to `node`, since the file is Jinja
  source, not plain JS.
- F4/F5 were documentation-only, per the owner's brief — no behavior change.

## Tests
- Targeted: `tests/test_dashboard_gate_js_execution.py` — **12 passed**.
  `tests/test_dashboard_execution_gates.py` — **24 passed** (unchanged from
  v4.97's baseline). Combined run: **36 passed**.
- Discrimination confirmed: with `templates/dashboard.html` stashed back to
  its pre-`462fbf3` state, `test_a_sell_below_the_execution_gate_is_now_blocked`,
  `test_a_buy_below_the_execution_gate_is_blocked_even_when_risk_policy_is_unreadable`,
  and `test_a_sell_is_blocked_when_the_bucket_has_no_policy_entry_and_execution_gate_fails`
  fail (`assert False is True`); all pass with the fix in place.
- Full suite, run once on this package's final commit (`32e25c4`), on a
  working tree that also carried a concurrent session's uncommitted changes
  to `atlas_supervisor.py`, `core/application.py`, and `main.py`:
  **5150 passed, 6 failed, 0 skipped (321.17s)**.
  - 2 are the pre-existing known failures unchanged since v4.96/v4.97:
    `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`
    and
    `tests/architecture/test_rem001_state_authority_map.py::test_committed_artifact_matches_current_source`.
  - 3 (`test_block3_execution_exception_atomicity::test_refused_paper_open_never_halts_the_runtime`,
    `test_block5i_durable_financial_state_sidecars::test_a_repeated_full_close_lifetimes_produce_n_immutable_closed_records`,
    `test_execution_audit_trail_completeness::test_c3_unverifiable_reservation_state_refusal_is_audited`)
    passed when re-run in isolation immediately afterward — attributed to
    the concurrent session's in-flight file writes racing the full-suite
    run (Windows `PermissionError` on `os.replace` was observed in the
    full-run traceback for one of these), not to a code defect.
  - 1 (`test_block5h_capital_reservation_archive.py::test_l_working_file_size_depends_on_live_records_not_lifetime_count`)
    failed in isolation too (`RuntimeError: reservation persistence failed;
    recovery required`), and — verified by stashing this package's three
    commits (`462fbf3`, `98f563c`, `32e25c4`) out and re-running the same
    isolated test — fails identically without this package's changes.
    Confirmed pre-existing on top of `d70573d` plus the concurrent
    session's uncommitted working-tree state; not investigated further
    here (out of this package's F2/F3/F4/F5 scope, and touches
    `core/capital_reservation.py`/execution financial state, which this
    package was not authorized to touch).
- Live verification against a real running instance: **NOT_PERFORMED**
  (only the owner may start one).

## Current state
- F2 and F3 (LOW) from v4.97 are FIXED with discriminating tests. F4 and F5
  (INFORMATIONAL) are DOCUMENTED. Registry v4.98 records the closure.
- Repository authority unchanged: `production_authority=NONE`,
  `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.
- A concurrent session is mid-flight on this branch (uncommitted changes to
  `.claude/agents/atlas-obsidian-writer.md`, `atlas_supervisor.py`,
  `core/application.py`, `main.py`, `tests/test_application_health_market_signals.py`,
  `tests/test_process_supervisor.py`, `tests/test_web_app_runtime_response_safety.py`,
  `web_app.py`, plus an untracked
  `checkpoints/20260927T220936Z_sell-invalid-financial-input-diagnosis.md`).
  This package's commits do not touch or depend on any of those files'
  pending content beyond the one isolated `web_app.py` comment described
  above.

## Known issues
- The full-suite run's 4 non-baseline failures and their disposition are
  recorded above under Tests; the capital-reservation one in particular is
  a live, reproducible failure on this branch right now, outside this
  package's scope, and not yet triaged by anyone in this session.
- `git commit` prints "failed to delete .git/worktrees/<name>: Permission
  denied" for 7 stale worktree entries on every commit in this session,
  matching the same pre-existing, not-investigated condition noted in the
  prior checkpoint (`20260927T220211Z_dashboard-execution-gates-critical-gate-closure.md`).
  Commits still succeed.

## Risks
- None of this package's changes touch risk, execution, capital, security,
  migration, or governance logic — display and test code only, per the
  brief's OUT OF SCOPE instruction. The one live risk visible from this
  session is the pre-existing `test_block5h_capital_reservation_archive.py`
  failure noted above, which does touch capital-reservation persistence;
  it is flagged here for owner attention, not fixed.

## Remaining work
- Owner: decide whether to investigate the
  `test_l_working_file_size_depends_on_live_records_not_lifetime_count`
  failure now (it reproduces independent of any uncommitted change in this
  session) or route it to whichever session owns `core/capital_reservation.py`
  / `core/application.py` right now.
- Owner: as with v4.97's predecessor record, live verification of the
  dashboard against a real running instance remains open and owner-only.

## Next exact action
Owner decides whether to open a separate package for the
`test_block5h_capital_reservation_archive.py` failure, or to let the
concurrent session (evidently already touching `core/application.py` and
`atlas_supervisor.py`) absorb it.
