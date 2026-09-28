# RELSUP remediation proposal: supervisor hang detection (G-S1) and alerting (G-S3) — v1.0, PROPOSED

- **Status:** PROPOSED. No code was written.
- **Why implementation waits:** it is new source work in `atlas_supervisor.py`, a runtime entry point, under the feature freeze (`PAUSED_PENDING_REM_GATE_1`). It needs an owner decision, and G-S3 also needs owner-held credentials.
- **Source:** `governance/findings/RELSUP-001_RECONNECT_AND_SUPERVISOR_STATUS.md` (MEDIUM findings G-S1 and G-S3).
- **Where:** Phase 3 (RELIABILITY), under REL-001 / OBS-001.
- **Date:** 2026-09-28.

## G-S1 — Detect a hung Atlas

**Existing surface (FACT).**
- `atlas_service.py` serves `web_app` on `127.0.0.1:8000`.
- `GET /api/health` is loopback-only. It returns 200 when `health.healthy is True`, otherwise 503 (`web_app.py:968-994`).

### Option A — health polling (recommended first step)

The supervisor polls `http://127.0.0.1:8000/api/health` with the standard library (`urllib.request`):
- It imports nothing from Atlas, so its isolation is preserved.
- The Host header is the loopback host, which satisfies the Host-header guard.

**Classification:**

| Observation | Meaning | Action |
|---|---|---|
| 200 | alive and healthy | none |
| 503 | alive but unhealthy: possibly a deliberate fail-closed state (`execution_halted`, `recovery_required`) | **No restart.** Log and alert only. Restarting a fail-closed runtime would churn and hide the cause. |
| No response for K consecutive polls, after a startup grace period | hung | Graceful stop (the existing single CTRL_BREAK and 45 s flush window), then escalate, then restart under the existing `RestartPolicy`, counted as an abnormal exit |

**Proposed constants** (owner may tune): poll every 20 s, startup grace 120 s, K = 3, request timeout 5 s.

**Limit.** A hang in the core loop while the web thread still answers is not detected, because `/api/health` would keep answering. Option B closes that.

**Tests.** Unit tests with a fake HTTP server:
- no restart on 503;
- restart on K timeouts;
- the grace period is honoured;
- a stop request during polling is honoured.

Windows signal paths need a Windows run, as the existing supervisor tests already do.

### Option B — core-loop heartbeat (later)

- The core loop writes a monotonic heartbeat (timestamp and cycle sequence) to a small file under the durable state root each cycle.
- The supervisor treats a heartbeat older than N cycles as hung.
- This touches the core, so it needs its own review of the file-write failure mode. A failed heartbeat write must never affect trading.

## G-S3 — Alert channel

**Events:**
- `RESTARTED` (with attempt number);
- `GAVE_UP` (policy exhausted);
- `HUNG_DETECTED`;
- `UNHEALTHY_503_PERSISTENT`;
- `RECOVERED` (a healthy run after restarts).

**Channel options:**
- Telegram bot (phone push; matches vision §75), or
- email over SMTP.

Either one needs owner-held credentials, read through the existing secret-management path, never from code or config files (CLAUDE.md security rules).

**Safety rules for any channel:**
- Delivery is best-effort and asynchronous. A failed or slow alert never delays or blocks a stop or restart.
- Alerts are rate-limited, with duplicates suppressed per event type.
- Content is limited to event type, time, attempt count and exit code. It never includes financial data, positions, secrets or free-form exception text.
- The outbound host is fixed (`api.telegram.org` or the configured SMTP host) and logged.

**Needed from the owner:**
- the channel choice;
- a bot token and chat ID (or SMTP credentials) stored as secrets;
- confirmation that the supervisor process may make that one outbound connection.

## Decision requested

1. Authorize Option A of G-S1 as a bounded source change to `atlas_supervisor.py` and its tests, or defer it.
2. Choose the G-S3 channel and provide credentials, or defer it.
