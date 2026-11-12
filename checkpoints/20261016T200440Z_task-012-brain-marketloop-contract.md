# ATLAS CHECKPOINT — Task 012: Brain → MarketLoop Typed Decision Contract

## Objective
Implement Task 012 under GRANT-TASK-012-BRAIN-MARKETLOOP-DECISION-CONTRACT (registry v5.96): a typed,
fail-closed contract between Brain output and MarketLoop's execution gates.
- **Contract standard:** frozen dataclass plus a JSON Schema document; no new runtime dependency.
- **Mode:** paper only.
- **Tests:** delta tests only.

## Completed
- **Owner decisions** (2026-10-16), from the brief, four answers and the final sign-off:
  - pipeline only; the earlier lean Task 012 items are deferred;
  - the dataclass validates and the JSON Schema documents;
  - the existing gates are kept (regime gate OFF per v5.93; a single RiskEngine inside ExecutionManager)
    and their order is proven by test;
  - staleness is 180 s and future skew 5 s, for BUY and SELL alike;
  - D-1 option (a) approved.
- **Conflicts C-1..C-5** recorded in v5.96: no JSON Schema in the repository and no jsonschema package;
  the regime gate's v5.93 conditions; RiskEngine already in ExecutionManager; no PAPER_SIMULATION mode;
  the scope change.
- **core/brain_decision_contract.py:**
  - `BrainDecisionPayload.from_decision` validates the 8 fields, the cycle symbol, timezone and
    staleness.
  - Each violation raises `ContractViolation` with a stable code.
- **core/brain_decision_payload.schema.json:** the same contract as a draft 2020-12 document. Its
  differences from the dataclass are documented in both files.
- **core/market_loop.py `_symbol_decide`:** the contract runs after normalization and before any
  execution gate.
  - A violation is not routed. It is counted (decisions_rejected, decision_contract_rejected), logged and
    published as DECISION_CONTRACT_REJECTED. The candle stays unprocessed and is retried next cycle.
  - A valid decision passes on exactly as checked.
- **D-1 (option a):**
  - The process_symbol golden record was regenerated; only the invalid_action scenario changed.
  - INVALID_NORMALIZED_ACTION was removed from the golden coverage set, which now also asserts that
    invalid_action is refused at the contract.
  - The gate's backstop branch keeps a direct test.

## Files changed
- **Commit 1:** governance/current/ATLAS_MILESTONE_REGISTRY_v5.96.json.
- **Commit 2:**
  - core/brain_decision_contract.py and core/brain_decision_payload.schema.json (new)
  - core/market_loop.py (one import, `_symbol_decide`, `_decision_contract_now`)
  - tests/core/test_task012_brain_decision_contract.py (new, 69 cases)
  - tests/test_process_symbol_golden.py and tests/golden/process_symbol_golden.json (D-1)
  - packaging/atlas_runtime_closure.json, packaging/atlas_architecture_map.json,
    packaging/REM-001_IMPORT_GRAPH.json, packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md,
    packaging/REM-001_STATE_AUTHORITY_MAP.md (regenerated)
  - this checkpoint
- **Unchanged:** RiskEngine, the regime gate, sizing, ExecutionManager, DecisionAdapter, the exchange
  layer and every execution-mode setting.

## Architecture decisions
- **The contract only reads and refuses.** It never creates, enlarges, mutates or routes a decision.
- **Rejection mirrors a failed normalization.** The candle is not marked, so the next cycle decides
  afresh.
- **What the staleness rule measures:** created_at, which the Brain stamps after its analysis. The rule
  refuses replayed or cached decisions and clock steps; it does not limit Brain latency or market-data
  age.

## Tests
- **Full suite:** 10935 passed, 12 skipped, 0 failed, from the final run before commit on 2026-10-16.
  That is the 10866 tests at Task 011's seal plus the 69 Task 012 cases.
- **Mutation testing:** all 38 contract, wiring and schema mutants are killed, including review 31's
  additive pass-through mutants.

## Reviews (fresh context, red team, threshold 0 BLOCKING / 0 HIGH / 0 MEDIUM)
- **Review 30 — FAIL (2 MEDIUM).** The D-1 disclosure was incomplete, and the staleness rule was
  misdescribed. Both were fixed, along with 3 LOW findings.
- **Review 31 — PASS (0/0/0; 2 LOW, 5 INFORMATIONAL).**
  - The LOW findings (additive pass-through mutants; D-1 omissions) were fixed after the review in one
    test and the record text. No runtime logic changed.
  - Details are in v5.96 under task_012_reviews_v5_96.

## Current state
Task 012 is implemented, owner-signed and ACTIVE in v5.96. The paper runtime now drops contract-breaking
decisions; valid decisions are unchanged.

## Known issues / limitations (all recorded in v5.96)
- How often the staleness rule fires in the paper runtime is UNKNOWN until measured; the
  decision_contract_rejected metric counts it.
- A rejected decision re-runs the Brain every worker cycle until a newer closed candle arrives.
- A stale SELL waits for a later valid decision.
- tools/backtest_replay.py bypasses the contract.
- **Pre-existing, outside Task 012:**
  - tests/test_apprentice.py::test_ceo_evidence_selection_is_learned_from_what_the_ceo_cited fails
    intermittently, about 1 run in 40–60, also on unmodified HEAD c5586bb;
  - the map generators drop the first character of the first path in modified_tracked_paths_at_generation.

## Risks
- A Brain or clock anomaly now stops decisions instead of routing them, which is fail-closed by design.
- No new path to an order.

## Remaining work
- The owner closes Task 012.
- Owner decisions are needed on the deferred items: the earlier lean Task 012 items, the apprentice
  flake, and the generator path bug.

## Next exact action
Present the commit hashes, and prepare the Task 013 (Atlas HQ Operations & System Health Monitoring)
brief for owner review. Implement nothing before the owner signs off.
