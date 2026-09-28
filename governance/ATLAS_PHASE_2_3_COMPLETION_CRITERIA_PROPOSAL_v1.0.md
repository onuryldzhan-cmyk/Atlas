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

**Today: MET for new risk; one open question.**
- Restart, idempotent replay and crash recovery have existing tests (the Block 5B/5C/5D and F1–F6 suites).
- Corrupting any durable store leaves Atlas running but refusing new risk. Two test files pin this:
  - `tests/test_corrupt_risk_state_fails_closed.py` (v5.11);
  - `tests/test_corrupt_execution_state_fails_closed.py`, which covers the idempotency log, the journal and the financial state (execution halts with `RECOVERY_REQUIRED`) and the reservation store (`CAPITAL_RESERVATION_STATE_NOT_READY`).
- **Open question (UNKNOWN):** can a *held* position still be exited while execution is halted by a corrupt store? A halt blocking exits is conservative, but it can also trap risk. Owner decision needed on the intended behaviour.

### 2. Reconnect
**Criterion.**
- Losing market data marks the runtime `market_data_stale` and blocks new risk.
- Recovering the data clears that flag without a restart.
- No decision is taken on stale candles.

**Today: UNKNOWN.** The flag is shown on the panel (`market_data_stale=false` in the owner's 2026-09-28 run). No reconnect test was inspected this session.

### 3. Status API
**Criterion.**
- Every panel figure comes from a read-only endpoint.
- No endpoint can change state.
- Every endpoint is loopback-only.
- An unreadable source is shown as *unavailable* and never invented.

**Today: PARTIAL.**
- Loopback guard: tested (`tests/test_loopback_host_header_guard.py`).
- Execution-gates endpoint: shows the enforced EXP-001 floor and fails as *unavailable* (`tests/test_dashboard_execution_gates.py`).
- **Missing:** an inventory proving *every* route is read-only.

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
**Criterion.**
- The web surface imports nothing that can mutate financial state.
- The runtime runs identically with the web surface disabled.
- A web failure cannot stop trading, and a trading halt cannot hide the panel.

**Today: UNKNOWN.** The composition hooks (`atlas_service.py`) and `test_merged_process_composition.py` cover start and stop ordering. The import-direction check was not run this session.

### 6. Recovery
**Criterion.** Every durable-state failure has one of two documented outcomes:
- a documented automatic recovery;
- a documented, owner-run, dry-run-first repair tool.

In addition, every repair keeps the original bytes.

**Today: PARTIAL.**
- The audit-chain fork has a diagnosis tool and a quarantine repair tool. Both are tested, and the repair was applied successfully on the owner machine (registry v5.06).
- **Missing:** a written runbook mapping each store's failure mode to its outcome. The v5.09 table is the starting point.

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
