# ATLAS CHECKPOINT — Independent audit of the dashboard vendored-JavaScript package

## Objective
Close the CRITICAL gate on the dashboard package described in `20260927T024500Z_dashboard-adminlte-widgets-chartjs.md`: run the independent AUDIT MODE pass (never run before), fix any BLOCKING/HIGH, run the full regression, commit, and record registry v4.86.

Audit focus: injection into the DOM via AdminLTE/Chart.js, exfiltration by the vendored scripts under any code path, and whether the loopback-only guarantee still holds. License and provenance were out of scope (already passed).

## Completed
- **Independent audit: 0 BLOCKING, 0 HIGH.** No fixes were required.
- Package committed as `9f92be0` with the exact paths from the implementation checkpoint.
- Registry v4.86 written, carrying v4.85 forward unchanged plus one new record.

### Audit method
1. **Template sinks (static).**
   - Every server-derived value reaching `innerHTML` passes `esc()`.
   - Every attribute interpolation is double-quoted.
   - Class tones come only from the constant `STATUS_TONE` map.
   - Style widths come from `toFixed()`, applied only to values that passed `isNumber`.
   - Jinja autoescape verified `True` for `dashboard.html` (starlette 1.5.0).
2. **Chart.js.**
   - Receives numbers or null plus constant labels only.
   - Draws text to canvas, never into the DOM.
   - JSON cannot carry the function-valued "scriptable" options.
3. **Vendored scripts, beyond the existing substring scan.**
   - No computed global access (`globalThis[`, `window[`, `self[`).
   - No string decoding (`atob`, `fromCharCode`, `unescape`).
   - No `location`, `navigator`, `.src`, `iframe` or `Image` network vectors.
   - Each of the following was inspected in context: `localStorage`, `createElement`, `setAttribute`, `href`, `dispatchEvent`.
   - **AdminLTE ColorMode:** `init`, the click handler and the `matchMedia` listener are all gated on `data-lte-color-mode="off"`.
   - **PushMenu:** returns before any `localStorage` access when there is no `.app-sidebar`.
   - **AccessibilityManager:** only adds skip links, a live region and captions, all via `textContent`.
4. **Runtime probe.**
   - Setup: scratch script, `create_app(runtime=None)` with a fake price provider, bound to 127.0.0.1:8766. No Atlas runtime was constructed and no state was written.
   - Actions: three page loads plus collapse clicks.
   - Result:
     - Every resource request went to 127.0.0.1:8766.
     - `localStorage` was empty and there were no cookies or iframes.
     - `sessionStorage` held only `atlas.dashboard.priceObservations.BTCUSDT`.
   - The server was stopped afterwards.
5. **Hostile-payload probe.**
   - Every polled API was stubbed with quote/tag breakouts, `<img onerror>`, `<script>` and `<svg onload>`.
   - All panels and all three charts rendered.
   - Zero injected elements or `on*` attributes; the canary never fired.
   - The payload text displayed verbatim as text.

## Findings (owner decision for all; none block)
- **A1 MEDIUM — pre-existing, not introduced by this package: no Host-header validation.**
  - `is_loopback_request` checks only the peer IP.
  - Evidence: `Host: attacker.example` sent to 127.0.0.1 returns 200 for `/dashboard`.
  - Risk: DNS rebinding could read the read-only panel APIs.
  - The vendored scripts neither widen nor create this exposure.
  - Recommendation: a separate package adding Host allowlisting.
- **A2 LOW — no CSP, `X-Content-Type-Options` or `frame-ancestors` headers.**
  - A CSP (`connect-src 'self'`, `script-src 'self'` plus the inline script's hash) would enforce no-exfiltration at runtime.
- **A3 INFO — the substring no-network scan only gates upgrades.**
  - The sha256 pin already fails on any byte change.
- **A4 INFO — `{{ symbol }}` in two JS string literals is HTML-escaped, not `|tojson`.**
  - Safe while it remains the constant `DEFAULT_SYMBOL`.
- **A5 INFO — `esc()` does not escape `'`.**
  - Safe because every attribute is double-quoted; this is a constraint on future template edits.
- **A6 INFO — sparkline sessionStorage is per-tab, per-origin and cleared on tab close.**
  - It holds only public prices. Accepted.
- **A7 INFO — no SRI `integrity` attribute on the script tags.**
  - The scripts are same-origin and hash-pinned by tests. This can be folded into A2.
- **Governance CONFLICT observed (recorded, not reconciled).**
  - **Expected:** v4.85 carries the v4.84 record `paper_recovery_risk_accounting_booking_result` unchanged.
  - **Actual:** v4.85 shows it as uncommitted, with `implementation_commit` UNKNOWN. v4.84 correctly shows COMMITTED `5088708`.
  - **Evidence:** `git diff --no-index` of v4.84 against v4.85.
  - **Impact:** documentation only.
  - **Decision required:** whether a successor record should restore the v4.84 values.

## Files changed
- Commit `9f92be0`:
  - `.gitattributes`
  - `templates/dashboard.html`
  - `web_app.py`
  - `static/vendor/VENDORED_ASSETS.json`
  - `static/vendor/adminlte-4.9.1/adminlte.min.js`
  - `static/vendor/chartjs-4.5.1/{chart.umd.min.js, LICENSE.md, KURKLE_COLOR_LICENSE.md}`
  - `tests/test_dashboard_adminlte_and_integrity_panels.py`
  - `checkpoints/20260927T024500Z_dashboard-adminlte-widgets-chartjs.md`
- Registry commit:
  - `governance/current/ATLAS_MILESTONE_REGISTRY_v4.86.json`
  - this checkpoint

## Architecture decisions
- None new. The audit accepted the package as implemented.

## Tests
- **Full suite** (`pytest tests`, ASCII `--basetemp`, final code state identical to `9f92be0`): **4750 passed / 1 failed / 0 skipped** in 162.98s.
  - The failure is the accepted B2 `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports` (atlas_finance `market_data/contracts.py` edges only).
- **Committed blob check:** the committed vendored blobs hash to the pinned sha256 values (`922181e2…`, `48444a82…`, CSS `0934e1e6…`), and `text` is unset for `static/vendor/**`.

## Current state
- Package and registry are committed on `research/edge-validation`.
- Authority is unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- Live verification against a real Atlas instance: NOT_PERFORMED (only the owner may start one).
- The stale `.git/worktrees/*` metadata still cannot be pruned (permission denied). It is harmless.

## Known issues / risks
- The MEDIUM and LOW findings above are open for owner decision.

## Remaining work
- Owner decides on A1 (Host allowlisting), A2 (CSP / security headers) and the v4.85 governance CONFLICT.
- Deferred: a price-history endpoint, and vendoring the `.map` files.

## Next exact action
Owner reviews findings A1 and A2 and, if accepted, schedules A1 as its own CRITICAL security package touching `observability/panel_router.py` and `web_app.py` middleware.
