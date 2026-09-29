# Unused and empty parts of the repository, and what to use them for (2026-09-29)

**Method.** A module counts as "not running" if it is absent from the runtime import closure `packaging/atlas_runtime_closure.json` (127 modules, regenerated at v5.63 from the real entry points). Reference and test counts come from `grep`. Nothing was deleted or moved: deleting or archiving is the owner's decision.

**Decision format** (CLAUDE.md new-idea rule):
- **USE**: wire into an existing roadmap phase, through a proposal.
- **KEEP**: a future seam; leave as is.
- **ARCHIVE**: superseded; move to `archive_unused_*` with owner approval.
- **DEFER**: needs research first.

## Empty directories

`execution/`, `risk/`, `memory/`, `events/` are empty. `CLAUDE.md` lists them in its directory map, but the real code lives in `core/` (for example `core/execution_manager.py`, `core/risk_engine.py`, `core/event_bus.py`).

**Decision: KEEP**, but record the mismatch. The directory map is historical. Moving code there would be a large refactor that rule 1 forbids.

## Stale JSON stores in the repository

`database/*.json` (8 files, 140 B–1.2 KB each) and `learning/model_memory.json`. No runtime module reads them; the runtime state lives in `ATLAS_STATE_DIRECTORY` (`C:\AtlasState` on the owner machine).

**Decision: ARCHIVE** (owner). They can mislead a reader into thinking this is live state.

## AI layer (`ai/`, 14 files outside the runtime)

| File | What it is | Decision |
|---|---|---|
| `ai/lstm_predictor.py`, `ai/target_prediction_engine.py` | ML price-prediction prototypes, no references | **DEFER** to Phase 4. They must go through the hypothesis registry and leakage-safe splits (`docs/research/0001-hypothesis-registry-design.md`) before any use; unvalidated price prediction is the classic overfitting trap. |
| `ai/chat_assistant.py` | old chat | **ARCHIVE**: superseded by `observability/command_center.py` (`/api/chat`). |
| `ai/core/atlas_multi_agent.py`, `ai/core/intelligence/fusion_engine.py`, `agent_analyzer.py`, `world_analyzer.py`, `risk_model.py`, `ai/core/decision/decision_builder.py` | earlier fusion/decision versions | **ARCHIVE**. The live path is `agent_fusion.py` + `intelligence/decision_builder.py`. `fusion_engine.py` is where the memory effect used to live and never reached the decision (BRAIN-MEM-001 finding). |
| `ai/core/validation/decision_validator.py` | decision validator, not wired | **USE (Phase 3)**: candidate for a pre-execution sanity check, via a proposal. |
| `ai/cognition/state.py` | stub | **ARCHIVE**. |

## Core (`core/`, 62 files outside the runtime)

| Group | Files | Decision |
|---|---|---|
| Exit / trade planning | `trade_plan_engine.py` (476 lines, no tests), `position_reentry_engine.py`, `reentry_engine.py`, `profit_manager.py`, `position_lifecycle.py` | **USE (Phase 2), after evidence.** This is where stop-loss / take-profit / re-entry logic would live. The owner's strategy comparison (`tools/strategy_compare`) decides first which exit rule wins; then one CRITICAL proposal with tests and an audit. Do not wire untested code as is. |
| Capital / portfolio | `capital_allocator.py` (860 lines, no tests), `portfolio_manager.py` (1109) | **DEFER**. The runtime uses `ExecutionPortfolioFoundation` + `RiskEngine`. A second allocator would split financial truth (rule 7). Ideas (sleeves, sizing) go through the replay first (v5.32 sleeves). |
| Old learning | `learning_engine.py`, `trade_memory.py`, `memory.py` | **ARCHIVE**: superseded by BRAIN-MEM-001 (`ai/core/intelligence/trade_evidence.py` over the durable archive). |
| Old execution path | `execution_controller.py`, `execution_router.py`, `execution_bridge.py`, `paper_execution_engine.py`, `execution_state.py`, `execution_event.py`, `execution_contracts.py`, `order_validator.py` | **ARCHIVE** (owner). The live path is `core/execution_manager.py` with the durable stores. Keeping a second path invites a bypass of the risk gates. |
| Research pipeline | `research_evidence_bridge.py`, `research_market_data_bridge.py`, `research_timestamp_split_binding.py` | **USE (Phase 4)**: seams for the hypothesis registry; keep. |
| Scanning / intelligence | `market_scanner.py`, `opportunity_engine.py`, `market_intelligence.py`, `signal_pipeline.py`, `market_pipeline.py`, `pipeline.py`, `brain_analyzer.py`, `brain_compare.py` | **DEFER**. `market_scanner` / `opportunity_engine` overlap with `tools/select_universe.py`; revisit only if the 20-coin selection needs intraday rescans. |
| Secrets | `secret_provider.py` | **USE (Phase 0)**: the right place to read `ANTHROPIC_API_KEY` from the environment when the owner decides on AI-001; never a file in the repo. |
| Tooling / misplaced | `code_cleanup_analyzer.py`, `module*.py`, `project_snapshot.py`, `test_snapshot.py`, `test_position_manager.py` | **ARCHIVE**. The two `test_*.py` files are tests in the wrong folder, and pytest does not collect them from `core/`. |
| `core/market_feed.py` | superseded by `exchange/market_feed.py` | **ARCHIVE**. |

## Other layers

| Area | Files | Decision |
|---|---|---|
| Legacy data providers | `data/binance_provider.py`, `data/market_provider.py`, `data/candle_manager.py` | **ARCHIVE**: superseded by `atlas_finance/market_data/binance_public_provider.py`. |
| Performance tracking | `analytics/performance_tracker.py` | **ARCHIVE**: superseded by `tools/performance_report.py`. |
| Duplicate analyzer | `analysis/technical_analyzer.py` | **ARCHIVE**: the runtime uses `core/technical_analyzer.py`. |
| Data layer | 10 `data_layer/*` SQLite / market-archive / migration modules | **KEEP**: the data-layer migration track (Block 4 contracts, market archive). Tools and tests use them; the live loop does not yet. Wiring them in touches migration integrity (rule 7) and needs its own gate. |

## Organization units without a worker

Research, code, review and security agents have tasks (T-0001…T-0003) but no executor.

- Rule-based executors that exist today, run as owner commands: `performance_report`, `atlas_self_review`, `strategy_agent`, `security_guardian`, `chaos_drill`, `incident_report`.
- A language-model executor is AI-001. It waits on three owner decisions: an API key on the owner machine, a budget, and which roles start first.

## Summary

- ~90 files are not used by the running system.
- About 45 of them are superseded and can be archived with one owner-approved move.
- About 15 are future seams mapped to Phases 0, 2, 3 and 4.
- The rest wait on research.
- Nothing here blocks the current roadmap. The most valuable next use is `trade_plan_engine.py` for the exit rule, but only after the strategy comparison produces evidence.
