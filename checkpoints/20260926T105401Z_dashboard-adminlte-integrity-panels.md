# ATLAS CHECKPOINT — Dashboard on AdminLTE 4 + integrity/telemetry panels (Parts L and M)

## Objective
- **Part L:** rebuild the loopback-only operator dashboard (`web_app.py` + `templates/dashboard.html`) on AdminLTE 4 with dark mode as the default. All assets are vendored locally, and nothing loads from a CDN.
- **Part M:** surface data the dashboard did not show:
  - the macro and risk evidence behind each vote;
  - risk-accounting day and rollover state;
  - system integrity (venue-rule freshness, registry version, known limitations);
  - the S-3/M-2 telemetry summary.
- Presentation only. Execution, risk, capital and decision logic are untouched.

Classification: COMPLEX. The work is cross-module (L5 web, `observability`, `core/market_loop.py`), adopts external code, and reads execution/risk state but never writes it.

## Completed
All work is uncommitted in the working tree on `research/edge-validation`.

### Adopted template
- AdminLTE **v4.9.1**, MIT licence.
- Provenance checks:
  - The npm tarball's sha512 matched the registry integrity value.
  - The publisher is `silkalns` (Colorlib), and the release matches GitHub tag v4.9.1 of ColorlibHQ/AdminLTE.
  - The GitHub repo licence is reported as MIT.
- Security scan:
  - No network or telemetry code.
  - The CSS has no `@import` and no external `url()`.
  - The only localStorage use in AdminLTE's JS is sidebar state.
- **Only `adminlte.min.css` is vendored; no JavaScript is.** It is byte-identical to upstream, with its licence and Bootstrap 5.3.8's MIT licence alongside.
- Provenance and hashes: `static/vendor/VENDORED_ASSETS.json`.
- The Tailwind CDN `<script>` was removed from `dashboard.html` and from the `/` landing page (`login.html`).

### New routes
Every new route is loopback-guarded with `is_loopback_request`.
- `GET /assets/{name}`
  - A fixed allowlist containing only `adminlte.min.css`. No request value is ever mapped onto the filesystem.
- `GET /api/agent-evidence`
  - Reads `MarketLoop.status()["last_agent_evidence"]`.
  - Allowlist projection that drops non-scalar values.
  - `market_risk` evidence is published under the agent name `risk`.
- `GET /api/risk-accounting`
  - `JsonRiskStateStore.load` (a pure read) gives the accounting day and its state: CURRENT / BEHIND_TODAY / RISK_STATE_MISSING / RISK_STATE_UNREADABLE / RISK_STATE_INVALID.
  - The latest rollover comes from a bounded scan of the audit JSONL tail (4 MiB), without the audit store's lock. PREPARED is paired with COMMITTED by `causation_id`.
  - Equity values are never published.
- `GET /api/system-integrity`
  - Venue freshness from `ExecutionManager.assess_venue_rule_freshness()` (a pure read), projected through an allowlist.
  - Registry head from `panel_sources.resolve_current_registry()`.
  - Static `KNOWN_LIMITATIONS`.
- `GET /api/observability/telemetry-summary`
  - Reads the operator-generated artifact `reports/observability/telemetry_summary.json`, now gitignored.

### MarketLoop change
- `core/market_loop.py` now keeps `last_agent_evidence[symbol]`: a shallow copy of `market_data["macro_evidence"/"market_risk_evidence"]`.
- It is set under the same lock as `last_signals` and published in `status()`.
- Nothing reads it except the web route.

## Files changed
- Modified:
  - `web_app.py`
  - `templates/dashboard.html` (rewritten)
  - `templates/login.html` (restyled; text unchanged)
  - `observability/panel_sources.py`
  - `observability/panel_router.py`
  - `core/market_loop.py`
  - `.gitignore`
- New:
  - `static/vendor/VENDORED_ASSETS.json`
  - `static/vendor/adminlte-4.9.1/{adminlte.min.css, LICENSE, BOOTSTRAP_LICENSE}`
  - `tests/test_dashboard_adminlte_and_integrity_panels.py` (51 tests)
- **Not this package:** `core/execution_manager.py` (modified) and `tests/test_risk_accounting_realized_pnl_wiring.py` (untracked). A concurrent session is actively editing both; it appears to be the daily-loss-limit package. Do not stage them with this package.

## Architecture decisions
1. **Telemetry panel reads an artifact; it does not run or import the tool.**
   - Importing the tool from L5 would pull in `core.application`, a forbidden L5→L3 edge.
   - The subprocess alternative broke the existing invariant `tests/test_observability_panel.py::test_router_never_triggers_a_test_run`, which says `panel_sources` must not import subprocess.
   - That test was not weakened, and moving the subprocess into `web_app.py` would only have dodged it.
   - The adopted pattern is identical to the test-results panel. The operator runs:
     `python tools/extract_candle_age_telemetry.py --json > reports/observability/telemetry_summary.json`
     The panel then shows the artifact's write time, so a stale summary is visible as stale.
   - Windows PowerShell 5.1's UTF-16 redirection output is accepted.
   - The tool itself is unchanged (registry v4.72 grant respected).
2. **Evidence gets its own endpoint rather than widening `/api/signals`.**
   - Existing tests pin `/api/signals`' key set, and its contract is unchanged.
3. **Stylesheet only.** A single page with no sidebar needs no AdminLTE or Bootstrap JS, which removes third-party script from the operator surface entirely.
4. **Mirrored constants.** The rollover audit event-type strings are mirrored as literals in `web_app.py`, because L5 may not import `core.execution_manager`.

## CONFLICT
- **Expected:** the prompt says a refused rollover's exact reason is shown "sourced from the audit event log".
- **Actual:** `ExecutionManager._auto_rollover_risk_accounting_day` logs refusals only as a WARNING; it writes no audit event (`core/execution_manager.py` at HEAD, registry v4.81).
- **Evidence:** the refusal branch calls `logger.warning(...)` and then `return`, and never calls `audit_store.append`.
- **Impact:** the reason cannot be shown without fabricating it. The panel shows `refusal_reason: null` with `refusal_reason_source: NOT_AUDITED_WARNING_LOG_ONLY`, rendered as "audit log'a yazılmıyor — yalnızca WARNING log satırında". The day state BEHIND_TODAY still makes a blocked rollover visible.
- **Decision required (owner):** whether to audit rollover refusals. That would be a CRITICAL execution-path change, out of scope here.

## Tests
- New file: 51 passed.
- Directly affected regression (web_app contract, response safety, signals/trades, observability panel, block2c contract, artifact freshness, health signals, telemetry tool, candle-age telemetry, backlog001 macro/risk wiring, phase6 market-loop integration, architecture): all pass except the accepted Group B2 `test_forbidden_layer_imports`.
- **Full suite:** run once on the final code, in an isolated `git worktree` at HEAD `ee49011` plus only this package's files, so the concurrent session's uncommitted `execution_manager.py` work was excluded.
  - Result: **4570 passed / 1 failed / 1 skipped** in 191.88s.
  - Failed: the accepted B2 `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`.
  - Skipped: `tests/test_observability_artifact_freshness.py:398`, "no existing artifact to protect in this checkout". The fresh worktree has no test-results artifact; it is not skipped in the main checkout.
  - Reconciles with the v4.81 baseline of 4520 / 1: 4520 − 1 (worktree-only skip) + 51 = 4570.
- **Visual check:**
  - A fake-runtime preview (scratch script, scratch state) was rendered at 1400px and at phone width, with no horizontal overflow after a wrap fix.
  - The telemetry panel was checked end to end against the real log: 3755 MEASURED records, 3 runs.

## Current state
- Implementation is complete and uncommitted.
- Authority is unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- Live verification against a real running Atlas instance: NOT_PERFORMED. Only the owner may start one.

## Known issues / risks
- `/api/system-integrity` resolves the whole registry chain on each 30s poll, the same cost `/api/observability/governance` already pays. This doubles that read.
- The rollover scan covers only the last 4 MiB of the audit log. When the latest rollover is older than that window, the panel says so ("son 4 MB'ında yok") rather than "none".
- `KNOWN_LIMITATIONS` is static. The package that closes EXEC-MGR-COMMIT-UNKNOWN-GAP-001 or wires the daily-loss limit must update its entry in `observability/panel_sources.py`. The daily-loss package appears to be in progress concurrently.
- Stale git metadata `.git/worktrees/wt_dashboard` could not be deleted (permission denied, like the pre-existing `Atlas_Clean_Verify` and `atlas_baseline_worktree_parent` entries). It is harmless and not listed by `git worktree list`.

## Remaining work
- Owner review, then commit. Stage these paths explicitly:
  - `web_app.py`
  - `templates/dashboard.html`, `templates/login.html`
  - `observability/panel_sources.py`, `observability/panel_router.py`
  - `core/market_loop.py`
  - `.gitignore`
  - `static/`
  - `tests/test_dashboard_adminlte_and_integrity_panels.py`
  - this checkpoint
- Governance: authorization for this package is UNKNOWN in the registry, and no registry record was written. A successor record is needed. Coordinate the version number with the concurrent daily-loss-limit package, since both would otherwise claim v4.82.
- Deferred improvements:
  - (a) Audit rollover refusals (see CONFLICT; CRITICAL).
  - (b) `templates/register.html` still references the Tailwind CDN. It is served by no route, so it was left untouched.
  - (c) Optionally vendor `adminlte.min.css.map` to silence the devtools-only 404.

## Next exact action
The owner reviews the diff and decides:
1. Commit with the explicit path list above.
2. Which registry version records this package.
3. Whether rollover refusals should become audit events.
