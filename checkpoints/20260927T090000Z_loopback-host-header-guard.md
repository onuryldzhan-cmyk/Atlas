# ATLAS CHECKPOINT — Loopback Host-header guard (v4.86 A1) and v4.85 record correction

## Objective
- (A) Close v4.86 audit finding A1 (MEDIUM, pre-existing): the loopback guard checked only the peer IP, leaving the operator surface open to DNS rebinding.
- (B) Restore v4.84's record of the recovery-booking work (committed `5088708`) that v4.85 regressed, additively in v4.87.

## Completed
- `observability/panel_router.is_loopback_request` now requires, after the unchanged loopback-peer check, exactly one Host header naming `127.0.0.1`, `localhost` or `[::1]` (case-insensitive, optional decimal port 1..65535).
  - Missing, repeated or malformed Host fails closed with the existing 403 body.
  - Any valid port is accepted: the hostname defeats rebinding, and port-forwards change the port.
  - TestClient's in-process pair (peer `testclient` + exact `Host: testserver`) stays accepted; it is unreachable from a socket.
- The predicate is the single guard for all 13 guarded GET routes (`/`, `/dashboard`, 7 `/api/*`, `/assets/{name}`, 3 `/api/observability/*`), so `web_app.py` needed no change. A completeness test pins that list against the app's real routes.
- Independent audit (separate agent) run, INFO-5 fixed, full suite run once on final code.
- Registry v4.87 written: the recovery-booking record restored to equal v4.84's, plus `v4_85_recovery_booking_record_correction` and `loopback_host_header_guard_result`.

## Files changed
- Commit `76ed33d`: `observability/panel_router.py`, `tests/test_loopback_host_header_guard.py` (new).
- Registry commit: `governance/current/ATLAS_MILESTONE_REGISTRY_v4.87.json`, this checkpoint.
- v4.84, v4.85 and v4.86 are unchanged.

## Architecture decisions
- Harden the single shared predicate, not the call sites or a middleware, to keep one guard for the whole surface.
- Missing Host means refusal (fail closed).
- Part B was delivered as one governance file, per the owner prompt, instead of the two-commit record-then-registry pattern.

## Tests
- New file: 212 passed.
- Full suite (`pytest tests`, ASCII `--basetemp`, code `76ed33d`): **4962 passed / 1 failed / 0 skipped** in 166.86s. That is 4750 + 212. The failure is the accepted B2 `test_forbidden_layer_imports` (atlas_finance `market_data/contracts.py` edges only).
- After v4.87 was written: `tests/test_observability_panel.py` 29 passed (the governance chain head resolves).

## Independent audit
- 0 BLOCKING / 0 HIGH / 0 MEDIUM / 0 LOW.
- Discrimination: 86 of the new tests fail against the old peer-only guard.
- Live socket probe: rebinding Host 403, `testserver` over the socket 403, HTTP/1.0 without Host 403, duplicate Host 400 (h11), loopback Host served.
- INFO-1: `/docs`, `/openapi.json` and `/redoc` are unguarded (schema only). Pre-existing.
- INFO-2: `POST /login` is unguarded and only redirects. Pre-existing.
- INFO-3: a page on another loopback origin passes the Host check. The same-origin policy blocks it from reading responses. Closing it needs an Origin/Sec-Fetch-Site check or authentication.
- INFO-4: the servers bind IPv4 only, so `http://[::1]:8000` is refused at connect time. Pre-existing.
- INFO-5: two real-socket tests were missing. Fixed in `76ed33d`.

## Current state
- Committed on `research/edge-validation`.
- Authority unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- Live verification against an owner-started instance: NOT_PERFORMED.

## Known issues / risks
- v4.86 A2 (LOW, CSP) and A3–A7 (INFO) are still open for owner decision.
- INFO-1 and INFO-3 are deferred.
- The root cause of the v4.85 regression is UNKNOWN.

## Remaining work
- Owner decides on A2, INFO-1 and INFO-3.
- Owner live check: open http://127.0.0.1:8000/dashboard on a running instance.

## Next exact action
Owner starts Atlas and confirms the dashboard loads at http://127.0.0.1:8000. Then the owner decides whether to schedule A2 (CSP) together with INFO-1 (doc routes) as one security-headers package.
