# ATLAS CHECKPOINT — Task 013: Lean Reliability Readiness Signals

## Objective
Implement Task 013 under GRANT-TASK-013-RELIABILITY-READINESS-SIGNALS (registry v5.97, Phase 3 RELIABILITY): make the
Task 010 and Task 012 safety mechanisms visible to the operator, read-only.
- No write or action endpoint.
- No change to execution or risk rules.
- A fail-closed /api/status.
- Delta tests only.

## Completed
- **Feed transitions.** The market feed service counts its DEGRADED and recovered transitions and records when each
  last happened. The counters are written under the transition's own lock and appear in the health details.
- **`MarketFeed.status()`.** Reports the lifecycle state, consecutive failures, both counts and both times. It never
  includes the provider's error text.
- **Contract rejection record.** MarketLoop counts contract rejections per reason code and keeps the latest one (code
  and time). `status()` shows it as `decision_contract` only after the first rejection.
- **/api/status allowlist.** The new fields are published only as upper-case codes, numbers and timestamps.
- **Readiness.** `observability/readiness.py` gains two conditional checks:
  - `decision_contract`: FAIL while the latest rejection is at most `RECENT_CONTRACT_REJECTION_S` (300 s) old, and
    UNKNOWN when its time is unreadable.
  - `market_feed`: FAIL on any reported state other than RUNNING, and UNKNOWN when the state is unreadable.
  - A healthy status yields the same checks as before.
- **/system page.** Two new rows: "Veri sağlayıcı" (data provider) and "Karar sözleşmesi" (decision contract).
- **Fill-ledger / frozen-pair signal: not built.** The paper runtime does not construct ExchangeManager, and it is not
  in the runtime closure (FACT, recorded in v5.97).

## Files changed
- **Commit 1:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.97.json.
- **Commit 2:**
  - atlas_finance/market_data/market_feed_service.py
  - exchange/market_feed.py
  - core/market_loop.py
  - web_app.py
  - observability/readiness.py
  - templates/system.html
  - tests/test_task013_reliability_signals.py (new, 26 cases)
  - packaging/REM-001_IMPORT_GRAPH.json
  - packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md
  - packaging/REM-001_STATE_AUTHORITY_MAP.md
  - this checkpoint

## Architecture decisions
- **Observation only.** The new state is never read by a decision, risk, regime, sizing or contract path.
- **Same pattern as existing checks.** The readiness checks appear only when they fail or are UNKNOWN, like the
  existing conditional checks.
- **No new routes.** /api/status and /api/readiness are unchanged as routes; only the allowlist grew.

## Tests
- **Full suite:** 10961 passed, 12 skipped, 0 failed, from the final run before commit on 2026-10-17. That is the 10935
  tests at Task 012's seal plus 26 Task 013 cases. After that run only the v5.97 record changed (its sign-off fields),
  and the registry-reading and architecture tests were re-run on it: 243 passed.
- **Mutation testing:**
  - The 81 mutants from the agent's set and reviews 32–33: 77 killed and 4 skipped (written for pre-fix code).
  - Review 34's 16: all killed.
  - Review 35's 9: all killed.
  - Review 36's 4 lock-placement mutants survive, as recorded. The code is correct as written.

## Reviews (fresh context, red team, threshold 0 BLOCKING / 0 HIGH / 0 MEDIUM)
- **Reviews 32–35: FAIL, one MEDIUM each, all in the governance record.**
  - 32: a false statement about who reads readiness.
  - 33–35: overstated mutation and testability claims.
  - Each was fixed and corrected in place with a bracketed note.
- **Review 36: PASS (0/0/0; 1 LOW, 2 INFORMATIONAL).** The LOW was an overstated description of the lock test; the
  wording was narrowed. Details are in v5.97 under task_013_reviews_v5_97.

## Current state
Task 013 is implemented, owner-signed and ACTIVE in v5.97. There is no effect on decisions or orders.

## Known issues / limitations (all recorded in v5.97)
- **Readiness thresholds.** Whether the 300 s window and the treatment of a DEGRADED feed are the right thresholds is
  UNKNOWN until observed.
- **incident_report.**
  - `tools/incident_report.py detect`, run by hand, opens a MEDIUM incident while either new check fails.
  - Whether to give the new checks their own severity is deferred to the owner.
  - It deduplicates on check names, so one outage can open more than one incident.
- **Not persisted.** The counters and the record live in memory and reset when the process restarts.
- **Lag.** Either counter can lag the other by the rejections that land between two reads.
- **Carried from v5.96.** The apprentice-test flake and the map generator's first-character bug.

## Risks
None to trading. A not-ready readiness result changes no behaviour.

## Remaining work
- The owner closes Task 013.
- Task 014 brief: paper trading environment and long-term verification.

## Next exact action
Present the commit hashes, and the Task 014 brief with its roadmap-phase CONFLICT, for an owner decision before v5.98
is drafted.
