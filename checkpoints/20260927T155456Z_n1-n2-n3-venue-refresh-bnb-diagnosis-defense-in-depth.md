# ATLAS CHECKPOINT — N1 venue-rules refresh attempt, N2 BNBUSDT diagnosis, N3 defense-in-depth (CSP/docs-guard/Origin check)

## Objective
Three independently-scoped parts from the owner's brief:
- **N1**: run `tools/refresh_venue_instrument_rules.py`, review the diff, commit `config/instrument_rules.json` if it looks sane.
- **N2**: read-only diagnosis of why a BNBUSDT decision cycle (26 Sep, confidence 60.43, above the 60.00 execution threshold) produced no execution attempt while the Performance panel showed 0 total trades.
- **N3**: defense-in-depth on the operator web surface — CSP/security headers on every response, extend the loopback+Host guard to `/docs`, `/openapi.json`, `/redoc` and `/login`, and add Origin-header validation on the one non-GET route.

Classification note: the owner's brief called all three "non-critical." Per the standing Atlas task-classification rubric, N1 (writes the file `ExecutionManager` is the sole reader of for order validation) and N3 (security posture of the operator surface) both fall in domains that make CRITICAL a floor regardless of diff size; the CRITICAL final gate (implement/test/self-review/regression) was applied to N3. N2 is read-only diagnosis with no implementation, so no gate applies; it was held to evidence-only rigor instead.

## Completed
- **N1**: Tool run against the live Binance API. It failed every time with HTTP 400 (`{"code":-1100,"msg":"Illegal characters found in parameter 'symbols'"...}`) before producing any diff. Root-caused (see below) and reported; nothing committed, per the objective's own "if anything looks off, stop and report" instruction — fixing the tool was out of N1's stated scope (run + review + commit, not modify).
- **N2**: Root cause identified with full evidence chain from the real (non-repository) audit log at `C:\AtlasState\memory_data\audit\atlas_audit_events.jsonl` plus the `RiskEngine.evaluate` and `ExecutionManager` source. See below.
- **N3**: Implemented, tested (unit + full suite), no regressions beyond the pre-existing accepted baseline failure.

## N1 — root cause (reported, not fixed)
`tools/refresh_venue_instrument_rules.py:121` calls `json.dumps(wanted)` with Python's default separators, which insert a space after each comma: `["BTCUSDT", "ETHUSDT", ...]`. Binance's `exchangeInfo` endpoint's `symbols` query parameter is validated against a strict regex that rejects any whitespace, so every call returns HTTP 400 (`code -1100`). Verified directly against the live API: the identical request with `json.dumps(wanted, separators=(",", ":"))` (no whitespace) returns HTTP 200 with the expected payload. This means the tool has never successfully run since it was committed (25 Sep) — the "917+ hours STALE" state was never actually closeable by this tool as written.
- **Deferred improvement** (not implemented, per N1's scope): change line 121 to `json.dumps(wanted, separators=(",", ":"))`, then re-run and review the diff before committing `config/instrument_rules.json`.
- `config/instrument_rules.json` is unchanged; still 5 symbols dated `2026-08-19T17:47:48Z`.

## N2 — root cause (evidence-backed)
The specific decision cycle: `BNBUSDT|open:1790464260000|BUY`, confidence 60.43, risk bucket `HIGH`, timestamp `2026-09-26T23:12:03Z`.
- `EXECUTION_REQUEST_VALIDATED` (event `3d379865-...`): `approved: true`, `confidence: 60.43`, `minimum_confidence: 60.0` — this is `ExecutionManager`'s own flat gate, and 60.43 clears it.
- `RISK_REJECTED` (event `f654a1c7-...`): `reason_code: CONFIDENCE_BELOW_POLICY`, `status: REJECT`.
- Mechanism (`core/execution_manager.py:3177`): when building the `RiskRequest` for `RiskEngine.evaluate`, confidence is converted from the 0–100 scale back to 0–1: `confidence=Decimal(str(request.confidence)) / Decimal("100")` → `0.6043`.
- `core/risk_engine.py:494-496`: `bucket_policy = self.policy.buckets[RiskBucket(risk_level)]`; `if confidence < max(self.policy.global_minimum_confidence, bucket_policy.minimum_confidence): reject("CONFIDENCE_BELOW_POLICY")`. The default `HIGH` bucket policy (`core/risk_engine.py:149`) has `minimum_confidence = Decimal("0.80")` — i.e., HIGH-risk trades require 80% confidence, not the 60% `ExecutionManager` checks first. `0.6043 < 0.80` → rejected.
- Conclusion: **the flat 60.00 threshold shown in the Performance panel / execution log is not the effective threshold for HIGH-risk trades.** `RiskEngine`'s per-bucket policy imposes a materially stricter 80% floor for `HIGH`, applied *after* the 60% gate is already passed and logged as `approved: true`. This is why a decision that "crossed the confidence threshold" produced zero trades: it crossed the execution-level threshold but not the risk-level one, and the two are silently different numbers on different scales.
- Supporting context (not this cycle's cause, but present in the same log): three earlier BNBUSDT SELL attempts that day (09:51–09:54, confidence 71–88, also `risk: HIGH`) were rejected earlier for an unrelated reason, `RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED` / `BLOCK_RECOVERY_REQUIRED` — a day-reconciliation gate, not the confidence-policy gate. By 23:11–23:13 that gate was no longer firing; `CONFIDENCE_BELOW_POLICY` is what blocked the 60.43 and a following 63.58 attempt specifically.
- No fix implemented (out of scope per the brief). No confidence-calculation logic touched.

## N3 — files changed
- `observability/panel_router.py`: added `_in_process_test_request`, `_origin_header_name`, `is_same_origin_request` (Origin-header equivalent of the existing Host check, reusing `LOOPBACK_HOST_HEADER_NAMES` and the same in-process TestClient carve-out).
- `web_app.py`:
  - Added `SECURITY_HEADERS` (CSP, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`) applied via an `@application.middleware("http")` hook to every response the app returns (covers the mounted observability router too, since middleware wraps the whole ASGI app).
  - `FastAPI(...)` now passes `docs_url=None, redoc_url=None, openapi_url=None`, and `create_app` defines its own `/openapi.json`, `/docs`, `/redoc` routes that call `is_loopback_request` first — same guard, same 403 payload, as every other route. No `/docs/oauth2-redirect` route exists any more (verified: it was only auto-created alongside the default docs routes).
  - `/login` (`POST`) now calls `is_loopback_request` and `is_same_origin_request` before redirecting; previously unguarded entirely.
- `tests/test_loopback_host_header_guard.py`: `WEB_APP_GUARDED_ROUTES` now includes `/docs`, `/redoc`, `/openapi.json`; `FRAMEWORK_ROUTES` is now empty (was `{"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}`, previously carved out as a documented deferred finding — that finding is now closed).
- `tests/test_security_headers_and_origin_guard.py` (new): headers present on served and refused responses, CSP directive assertions, docs-route guard (refuse/serve/real-schema-content/no-oauth2-redirect-route), and Origin-check unit tests (loopback accepted, foreign/malformed/missing/repeated refused, in-process TestClient carve-out, and end-to-end `/login` guard behavior).

## Architecture decisions
- CSP keeps `script-src 'self' 'unsafe-inline'` and `style-src 'self' 'unsafe-inline'` rather than a strict nonce-based policy: `templates/dashboard.html` has inline `<script>` blocks and inline `style="..."` attributes with no nonce plumbing today, and a strict policy would silently break the dashboard's JS (a GET-response content regression this package's OUT OF SCOPE forbids). Everything else in the policy (`default-src 'self'`, `object-src 'none'`, `frame-ancestors 'none'`, `form-action 'self'`, `base-uri 'self'`, `connect-src 'self'`) is as strict as the current self-hosted `/assets` design allows. Tightening script/style to nonce-based is a **deferred improvement**, not implemented here (would require template changes, out of N3's scope).
- Origin check fails closed on a missing header, matching the existing Host-header posture (`_host_header_name` already refuses a missing Host). A same-origin browser POST always sends Origin per the Fetch spec, so absence means either a non-browser client or something worth refusing anyway.
- Docs guard reuses `is_loopback_request` exactly (no second implementation), per the brief's explicit instruction.
- Verified before implementing that `/login` is the only non-GET route in the whole app (`grep` for `@application.post|put|delete|patch` found exactly one match) — no other non-GET route needed the Origin check.

## Tests
- Baseline (pre-existing, accepted): `test_forbidden_layer_imports` (`atlas_finance` domain/contracts edges) — unrelated to this package, tracked separately.
- New file `tests/test_security_headers_and_origin_guard.py`: 35 tests, all passing — headers, CSP content, docs-route guard/content, Origin-check unit tests, and `/login` end-to-end guard tests (rebinding host, mismatched origin, missing origin, matching host+origin succeeds).
- `tests/test_loopback_host_header_guard.py` (updated route lists): 236 passed.
- Targeted regression (`test_web_app_contract.py`, `test_web_app_runtime_response_safety.py`, `test_web_app_signals_and_trades.py`, `test_observability_panel.py`, `test_block2c_observability_contract.py`, `test_observability_artifact_freshness.py`, `test_loopback_host_header_guard.py`, `test_security_headers_and_origin_guard.py`): **370 passed**.
- **Full suite, final code: 5101 passed / 1 failed in 302.49s.** The failure is the pre-existing accepted `test_forbidden_layer_imports` (`atlas_finance` edges) — same class of failure recorded in the most recent prior checkpoint's baseline, not introduced by this package.
- No independent (second-agent) audit was run for N3 in this session; only self-review + regression + full suite. Given CLAUDE.md's CRITICAL gate calls for independent audit before a milestone closes, this is flagged as **remaining work**, not skipped silently.

## Current state
- Working tree (uncommitted at end of session): `observability/panel_router.py`, `web_app.py`, `tests/test_loopback_host_header_guard.py` modified; `tests/test_security_headers_and_origin_guard.py` new; this checkpoint new.
- `config/instrument_rules.json` unchanged (N1 produced no diff to review/commit).
- Authority unchanged: `production_authority=NONE`, `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.
- Live verification of N3 (a real browser or real HTTP client hitting a running `web_app`): NOT_PERFORMED — only `TestClient`/unit-level verification in this session.
- Untracked, unrelated to this session and left untouched: `.claude/agents/atlas-dashboard-scout.md`, `.claude/agents/atlas-test-runner.md`, `.claude/hooks/atlas_proposal_write_guard.py`, `proposals/`, `governance/current/ATLAS_MILESTONE_REGISTRY_v4.93.json`.

## Known issues / risks
- CSP's `'unsafe-inline'` for script/style means the CSP does not stop a reflected/stored XSS from executing inline script — it only stops loading a *different-origin* script/style/frame/object. This is a real, acknowledged limitation, not an oversight; closing it requires a nonce-based template rework (deferred).
- N1's tool bug means venue rules remain STALE (unchanged since 2026-08-19) until someone fixes the `json.dumps` separator and re-runs it — this is now a known, diagnosed blocker rather than an unexplained one.
- No independent audit of the N3 diff has been performed yet (see Tests section).

## Remaining work
- N1: apply the one-line `separators=(",", ":")` fix to `tools/refresh_venue_instrument_rules.py`, re-run, review the diff, commit `config/instrument_rules.json` if sane. Explicitly not done here (out of N1's scope as written).
- N2: no remaining action requested (diagnosis only); the two-threshold (execution 60% flat vs. risk-engine per-bucket, HIGH=80%) design is presumably intentional but was never reconciled anywhere visible to the operator (the Performance panel shows only the 60.00 number) — worth an owner decision on whether the panel should surface the effective (bucket-specific) threshold instead. Not implemented; flagged as a deferred improvement, not a bug fix, since it was explicitly out of scope.
- N3: independent audit of the diff before this milestone is considered closed; commit the changes; live verification against a running `web_app` instance (owner-run, per standing process rule) if desired before relying on this in an actual exposed session.

## Next exact action
Commit `observability/panel_router.py`, `web_app.py`, `tests/test_loopback_host_header_guard.py`, `tests/test_security_headers_and_origin_guard.py`, and this checkpoint on `research/edge-validation`.
