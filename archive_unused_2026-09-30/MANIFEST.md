# Archived files (2026-09-30)

- **What:** 29 files moved here, not deleted.
- **Authority:** the owner ("arşivle", 2026-09-30).
- **Source:** the ARCHIVE decisions in `docs/operations/UNUSED_AND_EMPTY_INVENTORY_2026-09-29.md`.

A file was moved only when all of the following held:

- it is outside the runtime closure (`packaging/atlas_runtime_closure.json`);
- no live module, test or tool imports it;
- nothing outside the archives references it (or, for the JSON stores, only the earlier archive does).

## Moved

- **Old fusion / decision:**
  - `ai/core/atlas_multi_agent.py`
  - `ai/core/intelligence/fusion_engine.py`
  - `ai/core/intelligence/agent_analyzer.py`
  - `ai/core/intelligence/world_analyzer.py`
  - `ai/core/intelligence/risk_model.py`
  - `ai/core/decision/decision_builder.py`
- **Old chat and stub:**
  - `ai/chat_assistant.py`
  - `ai/cognition/state.py`
- **Old learning:**
  - `core/memory.py`
- **Old execution path.** These could bypass the risk gates if revived.
  - `core/execution_controller.py`
  - `core/execution_bridge.py` (direct `paper_trader.open_trade`)
  - `core/execution_event.py`
  - `core/order_validator.py`
- **Tooling / misplaced:**
  - `core/code_cleanup_analyzer.py`
  - `core/project_snapshot.py`
  - `core/test_snapshot.py`
  - `core/test_position_manager.py`
  - `core/module.py`
  - `core/module_classifier.py`
  - `core/module_manager.py`
- **Superseded feeds:**
  - `core/market_feed.py`
  - `data/market_provider.py`
- **Stale JSON stores:**
  - `database/*.json` (6 files)
  - `learning/model_memory.json`

## Kept in place (still imported somewhere, or part of a data-layer migration inventory; they need a separate change)

- `core/learning_engine.py`: `data_layer/runtime_integration_inventory.json`, DEFER_CONTROLLED_MIGRATION (rule 7)
- `database/execution_audit.json`, `database/execution_state.json`: listed in `data_layer/persistence_inventory.json`
- `core/trade_memory.py`
- `core/execution_router.py`
- `core/paper_execution_engine.py`
- `core/execution_state.py`
- `core/execution_contracts.py`
- `data/binance_provider.py`
- `data/candle_manager.py`
- `analytics/performance_tracker.py` (used by `dashboard/app.py`)
- `analysis/technical_analyzer.py`

## Restore

To restore a file:

```
git mv archive_unused_2026-09-30/<path> <path>
```
