# ATLAS CHECKPOINT — Dashboard sectioned layout + risk-bucket confidence gates made visible

## Objective
Owner brief (display/layout only, no execution/risk/capital logic change):
- **Part 1**: reorganize the flat operator dashboard into clearly separated top-level sections, nesting secondary content inside its logical parent (known limitations inside System Integrity, collapsible; per-agent evidence inside each symbol card, collapsible).
- **Part 2**: make the risk-bucket / execution-threshold relationship visible on each symbol card, sourced from the real RiskEngine/ExecutionManager values, show when a decision was rejected with `CONFIDENCE_BELOW_POLICY`, and label the Risk agent's regime line so it can never be mistaken for the RiskEngine risk bucket. Follows up the N2 diagnosis in `20260927T155456Z_n1-n2-n3-...md` (HIGH bucket requires 80% vs the flat 60% execution gate).

Classification: the owner framed this as display-only. Per the standing rubric it was treated as **CRITICAL** anyway: it adds a new HTTP route to the operator surface (security posture) and publishes risk-policy values an operator will act on (a wrong number would mislead). Gate applied: implement → test → self-review → regression → full suite. No independent (second-agent) audit was run — see Remaining work.

## Completed
- New read-only, loopback-guarded route `GET /api/execution-gates` in `web_app.py`.
- Dashboard restructured into four collapsible top-level sections with nested sub-sections.
- Per-card risk-bucket gate block, confidence-bar threshold markers, "execute edilmez" header badge, latest audit-recorded risk outcome per symbol, gate legend.
- Risk agent row relabelled "Risk (volatilite)" and its line "volatilite rejimi: …" (was "rejim: …"); position unchanged.

## Files changed
- `web_app.py`: `import math`; constants `EXECUTION_REQUEST_AGGREGATE`, `EXECUTION_REQUEST_VALIDATED`, `RISK_STAGE_OUTCOMES` (literals, since web_app is L5 and may not import `core.execution_manager`); functions `_confidence_pct`, `_risk_policy_gates`, `_latest_risk_decisions`, `_execution_gates_payload`; route `/api/execution-gates` (same guard / threadpool / `PANEL_READ_FAILED` shape as `/api/risk-accounting`).
- `templates/dashboard.html`: layout + CSS (`.subpanel`, `details.atlas-sub`, `.gate-*`) + JS (`executionGates`, `bucketGate`, `renderGateLegend`, `renderLatestRiskDecision`, `assessRiskGate`, `updateExecutionGates`; `renderConfidence`/`renderSignalCard` extended; grid rebuild preserves each card's agent-breakdown open/closed state).
- `tests/test_dashboard_execution_gates.py` (new, 23 tests).
- `tests/test_loopback_host_header_guard.py`: `/api/execution-gates` added to `WEB_APP_GUARDED_ROUTES` (required by the existing every-GET-route coverage test; extends coverage, weakens nothing).

## New section structure
1. KPI strip (unchanged).
2. **Otonom Kararlar & Execution Eşikleri** — gate legend, symbol grid (each card: confidence bar with gate markers, risk-bucket gate block, nested collapsible "Ajan oyları & kanıt", open by default), nested collapsible "Karar günlüğü" (the former standalone trade log).
3. **Execution & Risk** — sub-panels Execution/Sağlık, Risk Accounting, Performans.
4. **System Integrity** — sub-panels Venue Kuralları & Registry, Governance (GOV-DRIFT), Test Sonuçları; nested collapsible **Bilinen Kısıtlar (N)**, closed by default.
5. **Telemetri (S-3 / M-2)**.
All element ids and every existing API call are preserved.

## Architecture decisions
- **New route rather than extending `/api/signals`**: `/api/signals`' exact response shape is pinned by existing tests (`test_signals_endpoint_shape_is_unchanged_by_the_evidence_store` and others); changing it would change an existing contract.
- **Source of the thresholds**: the live `risk_policy` attribute (the same `RiskPolicy` instance `AtlasApplication` passes to `RiskEngine` and `PositionSizingService`), read via the existing `_resolve_attr` pattern exactly like `_risk_accounting_payload`; ExecutionManager's `minimum_confidence` via `_resolve_attr(runtime, "execution")`. No threshold literal in web_app or the template. `panel_sources.py` was deliberately not used as the host: its module contract is "imports no Atlas runtime component, reads files only"; the runtime-backed readers live in web_app, and the new one follows the `{available, reason}` fail-closed convention both share.
- `required_confidence_pct` = `max(global_minimum_confidence, bucket.minimum_confidence)` × 100, mirroring `core/risk_engine.py:495`. This is the one piece of mirrored logic; it is pinned by a test that runs the real `RiskEngine.evaluate` at floor−0.01 (must be `CONFIDENCE_BELOW_POLICY`) and at floor (must not be), for default and a non-default policy. A mutation dropping the `max()` was confirmed to fail 2 tests.
- **Latest risk outcome** is attributed to a symbol only via `causation_id` → `EXECUTION_REQUEST_VALIDATED` (which carries symbol/action/confidence); orphans are skipped, never attributed by parsing the request id. Only outcome/reason/action/confidence/timestamp are published; allocation/equity details stay out (leak-marker test).
- The card's "execute edilmez" badge is shown only for a BUY whose current confidence is below max(execution gate, bucket floor), or whose level has no bucket (CRITICAL/UNKNOWN). Passing both floors is worded as "confidence eşikleri geçildi (diğer risk/capital kontrolleri ayrıca uygulanır)" — never as "will execute".

## Tests
- Baseline, dashboard/observability subset (9 files) before any change: **436 passed, 0 failed**.
- Baseline full suite at HEAD `5aff396` (clean detached worktree): **5109 passed, 2 failed, 1 skipped** — failures `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports` and `tests/architecture/test_rem001_state_authority_map.py::test_committed_artifact_matches_current_source`; the skip is `test_observability_artifact_freshness.py:398` (no artifact in a fresh worktree).
- After: same subset + new file: **467 passed** (= 436 + 23 new + 8 new loopback parametrizations).
- After: full suite on final code: **5141 passed, 2 failed, 0 skipped** — same two pre-existing failures; 5141 = 5109 + 1 (the skip passes in this checkout) + 31 new.
- Visual check: scratch uvicorn server (fake signals, real default `RiskPolicy`, a *copy* of the live audit log in the session scratchpad; no Atlas runtime constructed, no real state written) viewed in the browser pane at desktop and 375px widths — no horizontal overflow, no JS errors (only expected 503s from panels the fake runtime lacks), agent-breakdown collapse state survives the 5s rebuild, known limitations expand inside System Integrity.
- **Live verification against a real running Atlas instance: NOT_PERFORMED** (owner-only start; the running instance, if any, predates this route).

## Current state
- Real values in effect (verified from source): `core/application.py` builds `RiskPolicy(total_capital=...)` with defaults → LOW 60 / MEDIUM 70 / HIGH 80 (global 60, policy `phase3-risk-v1`); `ExecutionManager` is constructed without `minimum_confidence` → default 60.0.
- Real example from the live audit log (read-only): SOLUSDT BUY @ 63.58, `RISK_REJECTED` `CONFIDENCE_BELOW_POLICY` at 2026-09-27T16:22:01Z; BTCUSDT/ETHUSDT/XRPUSDT BUY @ 60.43 rejected the same way at 16:22:00–01Z; BNBUSDT latest is SELL @ 68.5 `INVALID_FINANCIAL_INPUT` at 00:16:02Z.
- Authority unchanged: `production_authority=NONE`, `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.

## Known issues / risks
- The latest-risk-outcome line belongs to the audit event it names (its own action/confidence/time), which can be an earlier cycle than the signal shown on the card; the UI shows those fields for exactly that reason.
- The audit scan is bounded to the last 4 MB (`AUDIT_SCAN_MAX_BYTES`), same as the risk-accounting panel; a symbol whose last risk decision is older than that shows "audit kaydında yok (taranan son bölümde)".
- **CONFLICT (checkpoint naming)** — Expected: checkpoint filename prefix is the real UTC time so the lexicographically last file is the most recent. Actual: `20260927T200000Z_rem001-...md` carries a 20:00Z prefix but was committed in `11af030` at 15:46Z; this checkpoint's real time is 18:22Z, so it sorts *before* that older file. Evidence: `git log --format=%cI -- checkpoints/`. Impact: "latest checkpoint" resolution would pick the rem001 file, not this one. Decision required: owner — rename the mislabeled historical file or accept; this checkpoint was not given a fabricated later timestamp.

## Remaining work
- Independent (second-agent) audit of this diff before the milestone is considered closed (CRITICAL gate).
- Owner-run live verification against a restarted `web_app` instance.
- Governance registry successor record, if the owner wants the new route recorded there (not done; registry edits were out of this brief's scope).

## Deferred improvements (not implemented)
- Surface the same effective-floor information in the Performance/trade panels if they ever display a threshold.
- Show the per-cycle risk bucket at decision time in the audit line (the `RISK_REJECTED` payload does not carry it today; would need an ExecutionManager audit-payload change — out of scope).

## Next exact action
Owner: review the dashboard at a restarted instance; decide the checkpoint-naming CONFLICT; request the independent audit.
