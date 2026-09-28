# RELSUP-001 — Reconnect and Supervisor: repository status against the Phase 2–3 vision

- **Mode:** AUDIT (read-only investigation). No code was changed.
- **Date:** 2026-09-28 (UTC). HEAD at investigation: `bd2ee9f`.
- **Why:** the Phase 0–10 enumeration crosswalk (registry v4.90) recorded Reconnect and Supervisor status as UNKNOWN. The owner asked for it to be established (session of 2026-09-28, "Hepsini yap").
- **Measured against:** the owner's vision §18 (reconnect: detect → reconnect → resync → validate state → resume, and "which events did I miss?"), §19 (data quality) and §28 (supervisor: detect → classify → restart → verify → alert, and never restart blindly while financial state is unsafe).
- **Test environment:** Linux, Python 3.13.

## 1. Reconnect / market-data resilience

### FACT (verified in source)

**Transport.**
- The only live ingestion path is REST polling: `core/market_loop.py` → `exchange/market_feed.py` → `atlas_finance/market_data/market_feed_service.py` → `atlas_finance/market_data/binance_public_provider.py` (a `requests.Session`).
- There is no WebSocket in the live path: searching those four files for `websocket` / `wss://` / `stream` finds no transport code. "Reconnect" therefore means "the next poll succeeds", not re-establishing a socket.

**Retry.** `BinancePublicDataProvider`:
- timeout 5 s (`DEFAULT_TIMEOUT_SECONDS`);
- 3 attempts (`DEFAULT_RETRY_ATTEMPTS`);
- exponential backoff from 0.5 s;
- HTTP 429 is among `RETRYABLE_HTTP_STATUS_CODES`.

**Resync.** Every cycle refetches the latest closed candles. An outage shorter than the fetched window heals itself (`core/market_loop.py` `_check_backfill_gap` docstring).

**"Which events did I miss?"**
- An outage longer than the window is detected and reported: a `backfill_gap_exceeded` metric, a WARNING, and a `MARKET_DATA_BACKFILL_GAP_EXCEEDED` record.
- It is never backfilled. This is deliberate fail-closed behaviour: detect and report, don't silently repair.

**Validation.** `core/candle_processor.py` rejects:
- future candles;
- invalid time ranges;
- conflicting payloads for one candle identity;
- ordering violations;
- non-numeric fields.

`MarketLoop` also skips duplicate closed candles.

**No decision on stale data.** A cycle yields a decision only on a new, non-duplicate closed candle with at least 50 closed candles available:
- an empty fetch returns early;
- an unchanged last candle returns `DUPLICATE_CLOSED_CANDLE`;
- `NO_CLOSED_CANDLES` and `INSUFFICIENT_CLOSED_CANDLES` also skip.

A stalled feed therefore produces no new decision rather than a decision on old data.

**Health.** `MarketLoop.health()` derives `healthy` from recent, time-windowed errors, not from the lifetime counter. It also reports staleness per symbol.

**Tests.** `tests/test_market_loop_reconnect.py` has 9 tests, all passing.

### Gaps against the vision

| ID | Gap | Severity | Basis |
|---|---|---|---|
| G-R1 | Candles lost in an outage longer than the window are never recovered; only the loss is recorded. | LOW | FACT. Deliberate, and consistent with fail-closed. The first decision after the gap is computed on a freshly fetched window of the latest candles. **INFERENCE:** Binance returns that window contiguous, so indicators are not computed across the hole. Not verified against the exchange. |
| G-R2 | Staleness is observability only; it gates nothing. | INFORMATIONAL | FACT (test docstring GAP #2). The decision trigger above already prevents new decisions on stale data. |
| G-R3 | No streaming transport (order book, trades, WebSocket) as described in §17. | INFORMATIONAL | FACT. This is future Phase 2 scope, not a defect. |

## 2. Supervisor

### FACT (verified in source)

**Structure.** `atlas_supervisor.py` is a runtime-closure entry point. It is a parent process that:
- launches `atlas_service.py` as a child in a new process group;
- imports nothing from Atlas;
- passes `ATLAS_SUPERVISOR_EPOCH` and `ATLAS_SUPERVISOR_RESTART_COUNT` to the child, which surfaces them in `health()`.

**Classification.** Exit code 0 is a deliberate stop and is never restarted. Any other exit is a fault.

**Restart policy** (`RestartPolicy`):
- at most 5 attempts;
- backoff of 5 / 15 / 45 / 120 / 300 s;
- the counter resets after a healthy run of 600 s;
- once exhausted, a CRITICAL log "giving up. This needs an operator" and exit 1.

**Graceful stop.**
- Exactly one `CTRL_BREAK_EVENT`.
- A 45 s timeout, sized to cover the child's financial-state flush.
- Then `terminate()` and `kill()`. An operator's Ctrl+C is forwarded.

**Documented limits (owner decisions).**
- Console launch only.
- It watches the child's exit, not its health: a hung child is not detected.

**Tests.** `tests/test_process_supervisor.py` and `tests/test_supervisor_package_gate.py`: 20 passed, 10 skipped. The skipped tests are Windows-only (`CTRL_BREAK_EVENT`), so **Windows signal behaviour is not verified in this environment**.

### Gaps against the vision

| ID | Gap | Severity | Basis |
|---|---|---|---|
| G-S1 | No hang detection. A child that stops making progress without exiting is not restarted. | MEDIUM | FACT (documented, deliberate). Vision §28 "DETECT" covers only crashes today. Closing it needs a health-polling design, which is Phase 3 work under REL-001/OBS-001. |
| G-S2 | The supervisor itself does not check financial-state safety before a restart. | LOW | FACT. **INFERENCE:** safety rests on the child's own startup recovery gating (`execution_halted` / `recovery_required` in `core/execution_manager.py`; see checkpoint `20260924T203700Z_execution-authority-crash-recovery.md`). A restarted child therefore fails closed rather than trading. The startup path was not re-verified in this session. |
| G-S3 | No alert channel. Exhaustion and restarts are logged only; there is no Telegram, email or push notification (§28 "ALERT", §75). | MEDIUM | FACT: a search of `atlas_supervisor.py` for alert, notify, telegram or email finds nothing. |
| G-S4 | No "VERIFY" step after a restart beyond "it did not exit again within 600 s". | LOW | FACT (the policy's healthy-run rule). |

## 3. Summary

- **Reconnect:** implemented for the REST path the runtime actually uses (retry, resync, gap detection, validation, and no decisions on stale data). Nothing BLOCKING or HIGH.
- **Supervisor:** crash restart is implemented and bounded, and it respects the financial-state flush. The two MEDIUM gaps are hang detection (G-S1) and alerting (G-S3). Both are Phase 3 work.
- None of the gaps is fixed here. Fixing any of them is new source work: it falls under the feature freeze (`PAUSED_PENDING_REM_GATE_1`) and needs an owner decision.
