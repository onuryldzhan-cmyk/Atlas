# Proposal v1.0 — Completion criteria for PHASE_2_3_INVESTMENT_ENGINE_AND_RELIABILITY

| Field | Value |
| --- | --- |
| Status | PROPOSED — owner decision required. This document changes no registry value. |
| Date | 2026-09-28 (UTC) |
| Why | Registry v5.10 made `PHASE_2_3_INVESTMENT_ENGINE_AND_RELIABILITY` the active milestone with `completion_criteria: UNKNOWN`. It gates nine milestones and has no finish line. |
| Source of the item list | Owner vision §96, recorded in `governance/ATLAS_ROADMAP_PHASE_0_10_ENUMERATION_v1.0.md` §3: Financial State → Reconnect → Status API → Supervisor → Frontend separation → Recovery → Testing → Independent Review. |
| Authority effect | NONE. Completing Phase 2–3 grants nothing toward Shadow, live, or Phases 4–10. |

## Rules for every criterion

- **Evidence only.** A criterion is met only when a named artifact proves it: a test file, a registry record, a tool output pasted by the owner, or a CI run. A statement in prose is not enough (CLAUDE.md No Hallucination Policy).
- **Failure paths count.** A happy-path test alone never meets a criterion (CLAUDE.md rule 8).
- **Windows counts.** The owner runs Windows. A behaviour verified only on Linux is marked *Linux-only* until Windows CI or an owner run shows it.
- **No gate loosens.** Meeting a criterion never relaxes RiskEngine, capital or execution gates.

## Criteria and today's evidence

"Today" means branch `claude/exp001-on-owner-lineage` at `3e5c798`. MET means the evidence named is in the repository. PARTIAL and UNKNOWN say what is missing.

### 1. Financial State
**Criterion.** Durable financial state survives:
- restart;
- a crash between the fill and the commit;
- corruption of each of its stores.

In every case the runtime either resumes exactly or refuses new risk. It never silently continues.

**Today: MET.**
- Restart, idempotent replay and crash recovery have existing tests (the Block 5B/5C/5D and F1–F6 suites).
- Five stores were each damaged in four ways (garbled, truncated, empty, deleted), then a BUY was attempted on a symbol with no open position (`tests/test_corrupt_execution_state_fails_closed.py`, 20 cases). **All 20 refuse new risk.**
- The audit HIGH (an empty or deleted journal was accepted as fresh and trading continued) is **FIXED** in registry v5.13 under an owner grant ("mantıklı olan"). `FinancialRuntimeSafetyService._authorities_agree` now also checks the reverse direction: every COMMITTED idempotency result must keep its COMMITTED journal entry, otherwise `SOURCE_DISAGREEMENT` and execution halts. Rejected requests never reach the journal and are exempt. The evidence is `test_erasing_only_the_journal_manufactures_disagreement` and `test_rejected_requests_need_no_journal_entry`. Reverting the fix fails three tests.
- **Exits while halted: DECIDED** (owner, "gerçek trader ne yaparsa o"). Nothing trades while a corrupt store has halted execution, including exits. This is the current behaviour. The operator reconciles first.

### 2. Reconnect
**Criterion (as first drafted).**
- Losing market data marks the runtime `market_data_stale` and blocks new risk.
- Recovering the data clears that flag without a restart.
- No decision is taken on stale candles.

**CONFLICT with an existing design decision.**
- *Expected (this draft):* staleness blocks new risk.
- *Actual:* `core/market_loop.py` (`STALENESS_THRESHOLD_SECONDS`, and candle age per registry v4.71) states that staleness and candle age are **observability only and never gate trading or decisions**.
- *Evidence:*
  - `core/market_loop.py:155-166`;
  - `tests/test_application_health_market_signals.py::test_stale_market_data_does_not_flip_healthy`.
- *Impact:* with the current design, a stale feed does not by itself block a BUY. What prevents decisions on a dead feed is the `DUPLICATE_CLOSED_CANDLE` skip: with no new closed candle, the loop processes nothing new (`core/market_loop.py:681-705`). A feed that returns old but not-yet-seen candles, such as after a backfill, is only *detected and logged* (`test_backfill_gap_exceeding_window_is_detected_and_logged`). It is not blocked.
- *Decision required from the owner:*
  - **(a)** keep observability-only and amend the criterion to "a dead feed produces no new decision (duplicate-candle guard), recovery is automatic, staleness is visible". This is **MET today**, per `tests/test_market_loop_reconnect.py`: its 9 recovery and staleness tests, plus `test_a_dead_feed_repeating_the_same_closed_candle_makes_no_new_decision`, which was added after audit HIGH-1 and proves no second analysis or order happens on a repeated candle.
  - **(b)** make staleness or candle age a gate on new risk. This is a behaviour change that needs its own grant, tests and audit.

**DECIDED: (b)** by the owner ("İkisini de değiştir"). Implemented in registry v5.14: a BUY needs a newest closed candle measured at 180s old or younger, while SELL is never gated. Evidence: `tests/test_buy_stale_data_gate.py` and the dead-feed test.

**Today: MET.**

### 3. Status API
**Criterion.**
- Every panel figure comes from a read-only endpoint.
- No endpoint can change state.
- Every endpoint is loopback-only.
- An unreadable source is shown as *unavailable* and never invented.

**Today: MET.**
- Loopback guard: `tests/test_loopback_host_header_guard.py`.
- Route inventory: `tests/test_status_api_read_only_inventory.py`.
  - All 19 routes, including the included observability router, are GET-only. The single exception is `POST /login`, which only redirects to `/dashboard` and is proven never to touch the runtime.
  - Adding any other state-changing route fails the test until it is reviewed and allow-listed.
- Unavailable sources report as unavailable: `tests/test_dashboard_execution_gates.py` and the observability endpoints return 503 with a reason when their artifact is missing.

### 4. Supervisor
**Criterion.**
- Abnormal exits restart within a bounded budget.
- A hang is detected and stopped.
- Unfixable exits are never restarted: 75 integrity, 76 already running.
- Shutdown is not killed mid-flush.
- Only one instance runs per state root.

**Today: MET, with one gap.**
- `tests/test_process_supervisor.py`, `tests/test_main_process_heartbeat.py` and `tests/test_single_instance_and_integrity_exit.py` cover these behaviours. They are recorded in registries v5.05 and v5.08.
- An owner run on Windows showed the heartbeat and a clean exit 0.
- Gap: the Windows lock behaviour is covered by mocks plus Windows CI only. No owner run has exercised exit 76 on a real second launch.

### 5. Frontend separation
**Criterion (as first drafted).**
- The web surface imports nothing that can mutate financial state.
- The runtime runs identically with the web surface disabled.
- A web failure cannot stop trading, and a trading halt cannot hide the panel.

**Today: MET for the first two points. CONFLICT on the third.**
- *Imports and calls:* `tests/architecture/test_web_layer_is_read_only.py` (AST-based) proves the following for `web_app.py` and `observability/*`:
  - no core, ai, risk, execution or storage module is imported;
  - no state-changing method is called directly;
  - there is no `setattr`/`delattr`, and no attribute store except on FastAPI app state;
  - every `getattr` or `_resolve_attr` lookup resolves to a known, non-mutating name.
  
  It was strengthened after audit MEDIUM-3. Four escape mutants (setattr, getattr-call on `process_symbol`, an attribute store on a runtime object, and a getattr with a non-literal name) all fail it.
- *Web disabled:* `python main.py` runs the full runtime with no web surface. Evidence: the owner's 2026-09-28 13:44 run, and `tests/test_merged_process_composition.py::test_process_without_hooks_is_unchanged`.
- **CONFLICT:**
  - *Expected:* a web failure cannot stop trading.
  - *Actual:* by design it does. A web surface that fails to start stops Atlas with exit 1 (`test_failing_start_hook_still_stops_the_application`). A web thread that dies at runtime stops Atlas too (`main.AtlasProcess._subordinate_alive`: "Subordinate component stopped unexpectedly").
  - *Impact:* a panel crash takes trading down, and the supervisor restarts it. That is conservative, because the operator is never left blind, but it couples availability to the panel.
  - *Decision required:*
    - **(a)** keep the coupling and amend the criterion;
    - **(b)** decouple, so that the runtime keeps running and the panel restarts on its own. That is a behaviour change needing a grant.
- *A trading halt never hides the panel:* health keeps reporting through a halt (`tests/test_application_health_market_signals.py::test_halted_execution_is_not_healthy`, which reports rather than hides).

### 6. Recovery
**Criterion.** Every durable-state failure has one of two documented outcomes:
- a documented automatic recovery;
- a documented, owner-run, dry-run-first repair tool.

In addition, every repair keeps the original bytes.

**Today: PARTIAL.**
- `docs/operations/RECOVERY_RUNBOOK.md` maps every verified failure (the audit fork, the lock, and the five durable stores) to its symptom, what Atlas does, the action to take, and the evidence.
- Only the audit fork has a repair tool.
- **Missing, owner decision:** repair procedures for the other five stores. Today they are "stop and report".

### 7. Testing
**Criterion.**
- The full suite is green on Windows CI, with only B2 and D5 failing as known-accepted (`tools/ci_check_known_accepted_failures.py`).
- Every Phase 2–3 criterion above cites at least one failure-path test.

**Today: PARTIAL.**
- Linux run: 5359 passed; only B2 and D5 fail.
- Windows CI was green on the heads it last reported. The current head is not yet reported.
- Failure-path coverage is partial wherever items 1, 2, 3 and 5 are.

### 8. Independent Review
**Criterion.**
- One whole-phase independent audit (AUDIT MODE, CLAUDE.md format) over items 1–7, as opposed to the per-change audits done so far.
- No BLOCKING or HIGH finding is open at close.

**Today: NOT STARTED.** Per-change audits exist for EXP-001, the SELL fix, the supervisor, the lock and the lock move. A phase-level audit has not been done.

## Proposed close condition

`PHASE_2_3_INVESTMENT_ENGINE_AND_RELIABILITY` completes only when all of the following hold:
- items 1–7 are MET, with the evidence named in a successor registry record;
- item 8 has run with no BLOCKING or HIGH finding open;
- the owner confirms the close.

Until then it keeps gating its nine dependants (ARCH-001, CODE-001, OBS-001, TEST-001, PERF-001, REL-001, SEC-001.1, DATA-001, SEC-002).

## Suggested order of the remaining work (for the owner to accept or change)

1. Pin the remaining corruption cases as tests (item 1). Small, test-only work.
2. Inspect and test reconnect and staleness (item 2).
3. Build a route inventory and a read-only proof for the status API (item 3).
4. Run the frontend import-direction check (item 5).
5. Write the recovery runbook (item 6).
6. Get Windows CI green on the final head (item 7).
7. Run the phase-level independent audit (item 8).

## Decision required

Accept these criteria as written, amend them, or reject them. Acceptance is recorded as a successor registry record that fills `completion_criteria` for the milestone.

## Phase-level independent audit (item 8), 2026-09-28

The audit found no BLOCKING issue. Findings and their disposition:
- **HIGH-1:** the reconnect evidence did not test the duplicate-candle guard. **Fixed:** a dead-feed test was added.
- **MEDIUM-1:** the runbook was wrong about deleted or empty financial state. **Fixed:** the row is corrected, and the cases are now tested.
- **MEDIUM-2:** corruption coverage was too narrow. **Fixed:** 5 stores × 4 modes are now tested. This surfaced the journal HIGH gap above.
- **MEDIUM-3:** the web read-only test was too narrow. **Fixed:** the test was strengthened and mutation-checked.
- **LOW-1:** the duplicate-candle memory is in-process only, so after a restart the last candle can be decided again. Execution idempotency is expected to make that replay harmless. That is UNKNOWN, still open.
- **LOW-2:** the Windows lock behaviour has not been proven by an owner run. Still open.
- **Not inspected:** EXP-001 cap durability and the paper/live boundary. These go into the next audit pass.

**Item 8 status: NOT MET while the journal HIGH is open** (the close condition requires no open HIGH).
