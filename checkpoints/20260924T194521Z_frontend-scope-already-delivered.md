# ATLAS CHECKPOINT

## Objective

Owner brief (2026-09-24): implement the owner-approved FRONTEND dashboard
scope (all 5 symbols' decisions, per-agent breakdown including EXCLUDED
agents, execution/health panel with halted/recovery_required/supervisor
epoch/restart count, trade/performance history) and fix the "TEST SONUÇLARI"
panel, described as showing a stale hand-entered count, so it reads a real
generated artifact. The brief described the dashboard as still BTCUSDT-only
(the interim state left by `906074d`).

## Completed

Inspection only. No code, template, test or configuration file was changed.
The brief's premise conflicts with the repository:

**CONFLICT**

- **Expected (per brief):** dashboard BTCUSDT-only after `906074d`; per-agent,
  health and trade panels not yet built; test panel backed by a hand-entered
  figure; the 15–16 Eylül PLAN-mode output never captured.
- **Actual:** the full scope was planned, implemented, audited, live-verified
  and committed on 2026-09-17, after `906074d` (2026-09-15):
  - `6e87e81` feat(web): expand operator dashboard to 5 symbols, agents,
    health and trades. It adds `GET /api/signals` and `GET /api/trades`
    (both loopback-guarded and allowlisted) and rewrites
    `templates/dashboard.html`.
  - `da0e227` feat(observability): refresh test-results artifact from
    full-suite runs. This is the root `conftest.py` freshness hook.
  - The earlier planning output was captured. It is recorded in
    `checkpoints/20260917T103347Z_dashboard-multisymbol-expansion.md`, which
    cites the approved plan file
    `C:\Users\HUAWEİ\.claude\plans\replicated-marinating-crystal.md`, and in
    its successor
    `checkpoints/20260917T110452Z_observability-freshness-hook-and-dashboard-commit.md`.
- **Evidence (verified this session):**
  - `git log -- web_app.py templates/dashboard.html`: neither file has
    changed since `6e87e81`. Later commits touched only `conftest.py`, with
    additive session-isolation and telemetry hooks.
  - Template: `DEFAULT_SYMBOL_PLACEHOLDERS` holds all 5 symbols, plus any
    extra symbol the API returns. `renderAgentRow` renders a non-EVALUATED
    agent as "excluded" plus its reason string. It never shows a score for
    such an agent.
  - `web_app.py`: the agent builder maps each agent missing from
    `metadata["agents"]` to `{status: EXCLUDED, reason}`, where `reason` is
    the string from `metadata["unavailable_agents"]`. That string comes from
    `DecisionBuilder._safe_unavailable_agents`, which keeps string reasons
    only. A reason such as `UNAVAILABLE_NO_PROVIDER` is therefore shown
    verbatim.
  - The execution/health panel reads `execution_halted`,
    `execution_recovery_required`, `supervised`, `supervisor_epoch`,
    `supervisor_restart_count`, `market_data_stale` and
    `market_loop_thread_alive` from `/api/health`. An absent field is
    skipped, and a null value renders as `UNKNOWN` through `esc()`. Neither
    case crashes when the supervisor is not attached.
  - Test-results panel: `observability.panel_sources.read_test_results_panel()`
    reads `reports/observability/test_results.junit.xml` live and returns
    `3906 passed / 1 failed / 3907 total`. The artifact was stamped at
    `9e28d4d`, generated `2026-09-24T14:42:16Z`, with pytest exit code 1.
    `commit_alignment.state = STALE` because HEAD is `f5e7250`, two commits
    later. Between those commits only `tools/extract_candle_age_telemetry.py`,
    its test and docs/governance changed. A missing artifact renders as
    `unavailable: ARTIFACT_MISSING`, never as a number.
  - Parsing that junit shows all dashboard/observability suites green:
    `test_web_app_signals_and_trades` 16, `test_web_app_contract` 8,
    `test_web_app_runtime_response_safety` 10, `test_observability_panel` 29,
    `test_observability_artifact_freshness` 30. The single failure is
    `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`.
    Prior checkpoints (`20260924T123057Z`, `20260923T185339Z`) identify it as
    the pre-existing Group B2 failure.
- **Impact:** re-implementing would duplicate committed, audited code. The
  most likely source of the "stale" perception is the amber `commit: STALE`
  line. It means the artifact predates HEAD, not that the count is
  hand-entered. It self-corrects on the next full-suite run. The 17 Eylül
  checkpoint also records an earlier stale `1401` figure, which that work
  fixed.
- **Decision Required (owner):**
  1. Brief says trade history comes from "memory core trades/winrate". On
     17 Eylül the owner chose `ExecutionPortfolioFoundation.closed_archive`
     over `PaperTrader.history` and the dead `AtlasMemoryCore`. Keep that
     choice unless the owner explicitly reverses it.
  2. Is there any remaining dashboard gap the owner has actually observed on
     the running instance? If so, provide the specific symptom.

## Files changed

- Added: this checkpoint file only. It is not committed.

## Architecture decisions

None. The existing decisions recorded in the two 2026-09-17 checkpoints stand.

## Tests

- No tests were run. No production code changed, and the dashboard suites
  are green in the most recent full-suite artifact (3906 passed / 1 failed,
  the failure being the known Group B2 one). A re-run would reconfirm settled
  evidence (token-efficiency contract).

## Current state

Branch `research/edge-validation`, HEAD `f5e7250`. The working tree is clean
except for this checkpoint.

## Known issues

- Test panel shows `commit: STALE` until the next full-suite run on HEAD.
  This is expected behaviour of the provenance check, not a defect.
- Carried forward from 2026-09-17: the duplicated dead block in
  `tests/test_web_app_contract.py`; the CI workflow has not yet been exercised
  in GitHub Actions.

## Risks

None introduced. No code changed.

## Remaining work

Owner answers to the two decisions above.

## Next exact action

Await the owner's answer. If no specific gap is reported, this brief is
closed as already delivered by `6e87e81` and `da0e227`.
