# ATLAS CHECKPOINT — Authoritative test baseline reconciliation (registry v4.99)

## Objective
Replace the stale "2 known failures" test baseline with an evidenced account of every
current failure. Run the real full suite fresh on HEAD. Classify each failure as
expected, flaky, stale artifact, or genuine defect, and find when each deterministic
failure started. Record the result additively in governance. This package was
read-only: it fixed no genuine defect.

## Completed
- Ran the full suite on a clean detached worktree at `f8d5761`. The worktree was outside
  OneDrive and used an ASCII basetemp. None of the concurrent session's uncommitted
  changes were in it. Result: **3 failed, 5152 passed, 1 skipped (268.43s)**.
- Classified every failure and every previously reported failure (see Tests).
- Found the onset of the dashboard registry-version failure. It passes at `32e25c4` and
  fails at `c3ca0da` (v4.98). The root cause is that v4.98 wrote `schema_version` as the
  JSON number `4.98` instead of a string.
- Reproduced the capital-reservation `test_l` failure and found its cause:
  `PermissionError [WinError 5]` on `os.replace` when the basetemp is inside OneDrive.
  The failure is environmental.
- Added registry v4.99 (`af803c9`), which contains
  `test_baseline_reconciliation_2026_09_28`.
- Re-ran the full suite on `af803c9`: **2 failed, 5154 passed, 0 skipped (234.56s)**.

## Files changed
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.99.json` (new, commit `af803c9`).
- This checkpoint.
- No application code, tests, artifacts or historical registries were changed.
  `feat/block3-execution-safety` was not touched.

## Architecture decisions
- **Registry test fixed additively.** The registry-version failure is fixed by the
  successor record's string `schema_version`. v4.98 is not edited in place, per the
  additive-only governance rule, and v4.99 records its wrong type.
- **D5 not regenerated.** The trivial-regeneration allowance does not apply to D5.
  `92bc00a` recorded D5 regeneration as not yet authorized, and v4.97 keeps D5 as a
  historical artifact that is "NOT edited in place".

## Tests
Full-suite runs:
- `f8d5761`, clean worktree: 3 failed / 5152 passed / 1 skipped.
- `af803c9`, same worktree: 2 failed / 5154 passed / 0 skipped. Reconciliation:
  5152 + 1 (registry test now passes) + 1 (the observability-artifact skip now runs,
  because the first run produced the artifact) = 5154. The total of 5156 is unchanged.

Failure inventory:

| Test | Classification | Evidence |
|---|---|---|
| `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports` | EXPECTED / ACCEPTED | Only the two known `atlas_finance/market_data/contracts.py` edges. Accepted by GRANT-B2-PERMANENT-CLOSURE (v4.63) and the CI criterion (v4.90). |
| `tests/architecture/test_rem001_state_authority_map.py::test_committed_artifact_matches_current_source` | EXPECTED / ACCEPTED (stale artifact; regeneration withheld) | Failing since the test was committed in `92bc00a`. Drift is recorded in v4.92. |
| `tests/test_dashboard_adminlte_and_integrity_panels.py::test_system_integrity_registry_version_is_the_real_chain_head` | GENUINE DEFECT (LOW) in governance record v4.98; RESOLVED by v4.99 | Deterministic (3/3 isolated failures at `f8d5761`). Passes at `32e25c4`, fails at `c3ca0da`. `web_app.py:958-961` and `observability/panel_sources.py:496-501` return null for a non-string version. Display-only and fail-closed. |
| `tests/test_block5h_capital_reservation_archive.py::test_l_working_file_size_depends_on_live_records_not_lifetime_count` | ENVIRONMENTAL (OneDrive), not a code defect | Passes 5/5 on clean HEAD with a Temp basetemp and 5/5 in the real tree with a Temp basetemp. Fails 6/8 in the real tree with a basetemp inside the OneDrive repo, with `WinError 5` at `core/capital_reservation.py:114`. The ledger correctly fails closed. |
| `test_block3_execution_exception_atomicity::test_refused_paper_open_never_halts_the_runtime`, `test_block5i_durable_financial_state_sidecars::test_a_repeated_full_close_lifetimes_produce_n_immutable_closed_records`, `test_execution_audit_trail_completeness::test_c3_unverifiable_reservation_state_refusal_is_audited` | FLAKY / UNREPRODUCED | Each failed only once, in v4.98's dirty-tree full run. Here they passed in the clean full run and 10/10 in isolation (5 with a OneDrive basetemp, 5 with a Temp basetemp). |

Other tests:
- The dashboard and observability panel tests passed (95) with v4.99 as the chain head.
- No live verification was needed: nothing in the runtime changed.

## Current state
- **Authoritative baseline (cite this from now on):** registry v4.99
  `test_baseline_reconciliation_2026_09_28`. On a clean checkout with an ASCII basetemp
  outside OneDrive, 2 failures are expected: B2 and D5. The measured figure at `af803c9`
  is 2 failed / 5154 passed / 0 skipped. A fresh checkout that has no observability
  artifact yet shows 1 skip.
- Authority is unchanged: `production_authority=NONE`, `live_authority=DENIED`,
  `autonomous_deployment_authority=DENIED`.
- The concurrent session's uncommitted changes are untouched and were not measured.
  They cover `atlas_supervisor.py`, `core/application.py`, `main.py`, `web_app.py`,
  several tests, and untracked files.

## Known issues
- **CONFLICT-D5-DRIFT-TEST-VS-V4.97-HISTORICAL-ARTIFACT.** The D5 test is red by
  construction. `tools/ci_check_known_accepted_b2_failure.py` passes the build only when
  B2 is the sole failure, so the CI criterion has been red since `92bc00a`.
- v4.98 permanently keeps a numeric `schema_version`. This is harmless now that it is
  no longer the chain head.
- `git commit` still prints "failed to delete .git/worktrees/..." for 7 stale entries.
  This was pre-existing and not investigated.

## Risks
- If `memory_data/` stays inside OneDrive, the same `os.replace` refusal would halt a
  real runtime's reservation persistence. It fails closed, not silently. This is covered
  by the standing decision to move execution state out of OneDrive before any sustained
  paper run.
- Packages that keep using a repo-local basetemp inside OneDrive will keep seeing
  spurious failures.

## Remaining work
- Owner decision on the D5 conflict. Options:
  - authorize regenerating D5, as v4.93 did for D4;
  - retire or re-scope the drift test now that the Gate 1 certification path is closed;
  - extend the CI known-accepted criterion to include D5.
- Deferred improvement: add an authoring-time check that each registry's
  `schema_version` is a string.
- Deferred improvement: standardize every package's pytest basetemp on an ASCII path
  outside OneDrive.

## Next exact action
Owner chooses the D5 disposition. Until then, future packages cite
"baseline per registry v4.99: 2 expected failures (B2, D5)" and triage any other
failure as new. They should first re-run any `os.replace`-heavy failure with a basetemp
outside OneDrive.
