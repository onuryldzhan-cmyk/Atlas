# ATLAS CHECKPOINT — Dashboard on AdminLTE 4 widgets + vendored Chart.js

## Objective
Rebuild the operator dashboard's presentation on AdminLTE 4's real component system and add small self-hosted charts. Rendering and layout only: no data, API contract, execution, risk, capital or decision logic changes.

Classification: CRITICAL, on the security trigger. The work vendors third-party executable JavaScript onto the operator surface, which is a supply-chain change. The owner explicitly requested and authorized it in the task prompt.

## Completed
All work is uncommitted on `research/edge-validation`. HEAD is `b20e302`; a concurrent session committed registry v4.85 during this work.

### Vendored scripts
- **AdminLTE 4.9.1 JS** (`adminlte.min.js`). Taken from the same npm tarball as the CSS; its sha512 matched the registry integrity.
- **Chart.js 4.5.1** (`chart.umd.min.js`). This is the npm dist-tag `latest`.
  - Licence: MIT.
  - Matches GitHub release v4.5.1 (published 2025-10-13); the GitHub repo licence is MIT.
  - npm publisher: `chartjs-ci`. The tarball sha512 matched the registry.
  - It bundles `@kurkle/color` v0.3.2 (MIT; its tarball sha512 was also verified). That licence is carried alongside as `KURKLE_COLOR_LICENSE.md`.
- Every vendored file is byte-identical to its tarball entry. Hashes are recorded in `static/vendor/VENDORED_ASSETS.json`.

### Security scan of both scripts
- No network or telemetry APIs: no fetch, XHR, WebSocket, sendBeacon, EventSource, importScripts, Worker, dynamic import, `.src=`, script-element creation, window.open, `location.`, `navigator.` or `document.cookie`.
- No eval and no `new Function`. The three `Function(` hits are the method name `_tickFormatFunction(`.
- The only URLs are in banner and licence comments.
- AdminLTE's localStorage use is limited to sidebar state (this page has no sidebar) and ColorMode.
  - The page sets `data-lte-color-mode="off"` on `<html>`, which disables ColorMode. Dark mode stays pinned, and no theme is read or written.

### Serving
- `web_app.VENDORED_ASSETS` gained two fixed entries, served as `text/javascript`.
- Same loopback-guarded `/assets/{name}` route, still no CDN.

### Template redesign (`templates/dashboard.html`)
- **One status palette:** `--atlas-ok/error/warn/neutral` CSS tokens plus the matching `STATUS_TONE` JS map, used by every panel.
- **KPI row:** AdminLTE small-boxes coloured by status.
  - Price: success when available, warning when not.
  - System state: success, danger (HALT/ERROR/FAIL) or warning.
  - Registry: success when resolved, warning when not.
  - Venue rules: FRESH success, STALE warning, anything else danger.
- **Per-symbol decisions:** CardWidget cards with coloured headers (BUY success, SELL danger, HOLD secondary) and a working collapse.
  - Collapse state is preserved across the 5-second grid rebuild.
  - A confidence progress bar (0–100 scale, verified in `MarketLoop._normalize_confidence`) shows the published value unchanged.
  - Agent votes are shown as badges; excluded agents get an outline "EXCLUDED" badge.
- **Risk-regime gauge:** a CSS gauge placing the volatility value against the p20/p80 band.
  - The marker colour follows the regime the provider reported (HIGH warn, NEUTRAL ok, LOW neutral); it is not recomputed.
- **Known limitations:** now a dedicated card, one callout per limitation, with a severity icon and a readable status label.
  - All three known OPEN_* statuses render as warn.
  - An unrecognised status renders as error (fail-conservative).
- **Telemetry:**
  - Chart.js bar charts: candle age, and cycle duration with two series (all log / latest run).
  - The exact percentile table stays beside the charts.
  - A missing value is a gap in the chart, never a zero.
- **Price sparkline:**
  - Plots only the server-rendered prices (the `data-price` attribute, present only when the provider returned one), collected across page loads in this tab's sessionStorage.
  - With fewer than 2 observations it draws nothing and says "geçmiş yok (tek gözlem)".
- **Trade log:** kept in terminal style.
  - One div per line (capped at 200), coloured action words, muted timestamps.
- **Health panel:** status badges; halted and recovery_required use error, the other flags use warn.
- If Chart.js fails to load, the numbers still render and a note explains the missing charts.

### Latent defect found and fixed (bundled: tightly related, cheap)
- `core.autocrlf=true` with no `.gitattributes` meant every fresh checkout rewrote the vendored files as CRLF.
- Evidence:
  - At HEAD, in a clean worktree, `test_vendored_files_match_recorded_provenance` FAILED. The CSS hash was `30fa29f7…` instead of the recorded `0934e1e6…`.
  - `git cat-file --filters` on the same blob produced `30fa29f7…` without the attribute and the recorded hash with it.
- Fix: a new `.gitattributes` containing `static/vendor/** -text`. It is scoped to vendored files only.

## Files changed
- Modified:
  - `templates/dashboard.html`
  - `web_app.py` (allowlist entries and one comment only)
  - `static/vendor/VENDORED_ASSETS.json`
  - `tests/test_dashboard_adminlte_and_integrity_panels.py`
- New:
  - `.gitattributes`
  - `static/vendor/adminlte-4.9.1/adminlte.min.js`
  - `static/vendor/chartjs-4.5.1/{chart.umd.min.js, LICENSE.md, KURKLE_COLOR_LICENSE.md}`
  - this checkpoint

## Architecture decisions
1. The stylesheet-only invariant from `20260926T105401Z` ("no third-party JavaScript") is superseded by the owner's explicit request.
   - The successor test pins that the page loads exactly the two allowlisted, hash-recorded vendored scripts.
2. The risk gauge is CSS, not Chart.js. It re-renders every 5 seconds inside `innerHTML`, so there are no chart instances to leak or destroy.
3. Price history uses per-tab sessionStorage of real observations. No endpoint provides price history, and `/api/analysis` runs the brain, so it must not be polled.

## Tests
- **Baseline at HEAD `b20e302`** (clean worktree; relevant suite of 9 files):
  - Result: 203 passed / 1 failed / 1 skipped.
  - The failure is the CRLF defect above; the skip is the worktree-only artifact skip.
- **After the changes** (main tree, same 9 files): 218 passed.
- **Test-file changes:**
  - `test_dashboard_loads_no_third_party_javascript` was replaced by `test_dashboard_loads_only_the_vendored_allowlisted_javascript`, per decision 1.
  - The provenance file count changed from 3 to 7.
  - Added:
    - a ColorMode-off pin;
    - a no-network / no-eval scan of both scripts (×2);
    - a `.gitattributes` test;
    - byte-exact serving of both scripts (×2);
    - four more 404 allowlist names;
    - two more non-loopback routes;
    - a sparkline data-source test (`data-price` present only when a price exists).
- **Full suite** (main tree, final code): **4750 passed / 1 failed** in 162.10s.
  - The failure is the accepted Group B2 `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`.
  - Reconciliation: the HEAD test-results artifact shows 4737 passed / 1 failed; 4737 + 13 new = 4750.
- **Visual check** (fake runtime, scratch temp stores, port 8765 on loopback, real read-only report artifacts):
  - Checked at 1440px and at 375px. No page-level horizontal overflow; the percentile table scrolls inside `.table-responsive`.
  - No JS errors. The two console 503s are expected: the fake runtime has no trade archive.
  - Collapse state survived the rebuild.
  - All three charts instantiated; telemetry used the real artifact (3755 MEASURED records).

## Current state
- Implementation is complete and uncommitted.
- Authority is unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- Live verification against a real running Atlas instance: NOT_PERFORMED. Only the owner may start one.

## Known issues / risks
- **INDEPENDENT AUDIT step of the CRITICAL gate: NOT PERFORMED.** No separate reviewer agent was run, because none was requested. Self-review and the diff review were done.
- The sparkline only grows on page reloads, so it is sparse by nature. A real price series would need a backend price-history endpoint (see deferred item a).
- Stale `.git/worktrees/wt_baseline` metadata could not be deleted (permission denied, like earlier worktrees). It is harmless.

## Remaining work
- Owner review, then commit with explicit paths:
  - `.gitattributes`
  - `templates/dashboard.html`
  - `web_app.py`
  - `static/vendor/`
  - `tests/test_dashboard_adminlte_and_integrity_panels.py`
  - this checkpoint
- Governance: authorization in the registry is UNKNOWN. A successor record after v4.85 is needed.
- Deferred improvements:
  - (a) A read-only price-history endpoint to feed the sparkline (backend; out of scope here).
  - (b) Vendor the `.map` files to silence devtools-only 404s.

## Next exact action
The owner reviews the diff and the live dashboard, decides whether an independent audit is required before commit, and then commits with the path list above.
