# REM-001_CANONICAL_COMPONENT_MATRIX

REM-001 GATE_1 CANONICAL_COMPONENT_MAPPING — deliverable 2 of 9.

Mechanical markdown companion to Deliverable 1 (`REM-001_CANONICAL_COMPONENT_MATRIX.json`). This document presents the same canonical component matrix, the same field values, and the same classification dispositions, in markdown form. It transcribes; it does not reclassify, resolve any OWNER_DECISION_REQUIRED/UNKNOWN field, or add any judgment D1 does not already record. Where D1 and this document ever disagree, D1's JSON is authoritative.

Authorized by `governance/current/ATLAS_MILESTONE_REGISTRY_v4.56.json`, `GRANT-D2-D6-D7-D9-PRODUCTION` (grant (d): D2 only, gated on the specification-adequacy check recorded in that grant). Production of this artifact is not Owner acceptance of any mapping it documents, exactly as D1's own authorization states; its status is `produced, PENDING_OWNER_REVIEW`, not accepted, and it does not advance `gate_1_state` or certify Gate 1.

## Authorization

| field | value |
| --- | --- |
| authorization_id | ATLAS-REM001-GATE1-D1-AUTHORIZATION-001 |
| authorization_record | governance/ATLAS_REM001_GATE1_DELIVERABLE1_AUTHORIZATION_v1.0.md |
| predecessor_carve_out | governance/ATLAS_BASELINE_IDENTITY_AND_GATE1_SCOPE_DECISION_v1.0.md section 4.3 carve-out (i) |
| acceptance_status | NOT_ACCEPTED_EVIDENCE_FOR_REVIEW |
| gate_1_state | OPEN_NOT_CERTIFIED |
| gate_1_closure_authority | OWNER_ACCEPTANCE_REQUIRED |

## Source identity

| field | value |
| --- | --- |
| generated_from_commit | `bb5d1e49c1f0ae0b9b4ad954104458cf21f8ea6b` |
| generated_from_tree | `a37d665c690eb37b5bc37ec6a6e7887a40aa7a78` |
| branch | `research/edge-validation` |
| tracked_working_tree_clean | `False` |

Modified tracked paths at D1 generation time: core/application.py. core/application.py carries a pre-existing unstaged modification not produced by this task or its authorization chain. This artifact's evidence for core/application.py reflects the working-tree file content actually read at generation time (hashed in its evidence.source_sha256), which may diverge from the HEAD-committed blob; true reproducibility from commit HEAD alone is therefore not claimed for that one file until the pre-existing modification is committed or reverted.

## Scope

| field | value |
| --- | --- |
| population_source | packaging/atlas_runtime_closure.json |
| population_method | Static, deterministic, git-tracked runtime-reachability closure from entry points main.py and web_app.py, computed by tools/build_architecture_inventory.py check (per ATLAS-BASELINE-IDENTITY-001 section 2, '105' measured against this same repository). |
| population_count | 105 |
| canonical_module_set_status | NOT_YET_DETERMINED. This artifact does not resolve, narrow, or stand in for that determination (ATLAS-BASELINE-IDENTITY-001 section 3.5; ATLAS-REM001-GATE1-D1-AUTHORIZATION-001 section 6). Membership in this matrix is not a claim of canonicality. |

Entry points: main.py, web_app.py.

861 Git-tracked .py files exist at HEAD (ATLAS-BASELINE-IDENTITY-001 section 2); the 756 outside this 105-module closure (many under tests/, tools/, archive/backup/report-copy/quarantine-classified trees per the historical 691-file candidate_scope_counts census) are not evaluated by this artifact and their absence here is not a classification of them as inactive, deprecated, or out of scope for a future census.

## Methodology

current_responsibility is populated wherever the repository directly evidences it (an exact-path entry in packaging/atlas_architecture_map.json#layer_rules, else an AST-extracted module docstring, else AST-extracted top-level public class/function names, else the nearest directory-default layer_rules reason), per this artifact's authorization to record current responsibility where directly evidenced. intended_responsibility, source_scope, domain, owner, state_ownership, criticality, and lifecycle are populated with the schema's own unresolved value (UNKNOWN, or UNASSIGNED for owner) unless an already-accepted ADR or the git-tracked architecture-boundary map itself states an explicit ratified designation for that exact file, in which case that designation is transcribed with evidence.confidence VALIDATED or HIGH and cited by section/path; this is recording an existing ratified record, not this artifact approving a new one. Every field left UNKNOWN additionally carries a classification_disposition entry stating whether the gap is OWNER_DECISION_REQUIRED (evidence or a heuristic proposal exists but only an Owner can approve it) or genuinely UNKNOWN (no evidence and no proposal), per ATLAS-REM001-GATE1-D1-AUTHORIZATION-001 section 4 and this task's instruction never to use UNKNOWN to hide a judgment requiring an Owner decision, and never to mark OWNER_DECISION_REQUIRED where the repository provides clear objective evidence. The criticality heuristic (module path under core/risk_engine*, core/capital_reservation*, core/execution_*, core/position_*, core/decision*, portfolio/capital_manager, data_layer/sqlite*, atlas_os/secrets*, atlas_security*, core/audit_event*, core/durable_append_log*, core/paper_trader*, core/venue_rule_freshness*, core/instrument_rules*, core/fee_accounting*, core/risk_state_store*) is used only to prioritize which OWNER_DECISION_REQUIRED gaps most need Owner attention first; it is not itself a criticality or risk-severity assignment.

## State-authority overlap flags carried from D1

- **sqlite-backed durable store (mechanical signal: sqlite3.connect / .sqlite3 reference)** — components: data_layer/config.py, data_layer/sqlite.py. authority_established: UNKNOWN. Multiple modules reference SQLite storage. This artifact does not determine whether they share a database, own disjoint tables, or overlap in authority; per this artifact's authorization section 7, the overlap is flagged as data for future D5 review, not resolved here.

## Module index (105 modules)

Full runtime-reachability closure population from `packaging/atlas_runtime_closure.json`. Sorted as D1 lists them (insertion order).

| # | module_id | file_path | current_responsibility |
| --- | --- | --- | --- |
| 1 | `MOD-AI.CORE.ATLAS_BRAIN` | `ai/core/atlas_brain.py` | ATLAS AI INTELLIGENCE BRAIN v10.2 |
| 2 | `MOD-AI.CORE.ATLAS_MEMORY_CORE` | `ai/core/atlas_memory_core.py` | ATLAS MEMORY CORE v2.0 - Geliştirilmiş Hafıza Sistemi |
| 3 | `MOD-AI.CORE.ATLAS_REASONING_ENGINE` | `ai/core/atlas_reasoning_engine.py` | ATLAS REASONING ENGINE v2.1 |
| 4 | `MOD-AI.CORE.ATLAS_WORLD_MODEL` | `ai/core/atlas_world_model.py` | ATLAS WORLD MODEL v2.0 - Piyasa Iliskileri Grafi |
| 5 | `MOD-AI.CORE.INTELLIGENCE.AGENT_FUSION` | `ai/core/intelligence/agent_fusion.py` | Atlas AI Agent Fusion Engine v10.0 |
| 6 | `MOD-AI.CORE.INTELLIGENCE.CONFIDENCE.CONFIDENCE_ENGINE` | `ai/core/intelligence/confidence/confidence_engine.py` | Atlas AI Confidence Engine v10.1 |
| 7 | `MOD-AI.CORE.INTELLIGENCE.DECISION_BUILDER` | `ai/core/intelligence/decision_builder.py` | Atlas AI Decision Builder v10.0 |
| 8 | `MOD-AI.CORE.INTELLIGENCE.MEMORY_ADAPTER` | `ai/core/intelligence/memory_adapter.py` | Atlas AI Memory Adapter v10.0 |
| 9 | `MOD-AI.CORE.INTELLIGENCE.REASONING_ADAPTER` | `ai/core/intelligence/reasoning_adapter.py` | Atlas AI Reasoning Adapter v10.0 |
| 10 | `MOD-AI.CORE.INTELLIGENCE.RISK_ENGINE` | `ai/core/intelligence/risk_engine.py` | Atlas AI Risk Engine v10.0 |
| 11 | `MOD-ANALYSIS._INIT_` | `analysis/__init__.py` | Atlas Analysis Layer |
| 12 | `MOD-ANALYSIS.EVIDENCE_STATUS` | `analysis/evidence_status.py` | explicit: shared L1 vocabulary exception within analysis/** |
| 13 | `MOD-ANALYSIS.WORLD_ANALYSIS_ENGINE` | `analysis/world_analysis_engine.py` | Atlas AI |
| 14 | `MOD-ATLAS_FINANCE._INIT_` | `atlas_finance/__init__.py` | ATLAS FINANCE v1.0.0 |
| 15 | `MOD-ATLAS_FINANCE.MARKET_DATA._INIT_` | `atlas_finance/market_data/__init__.py` | ATLAS FINANCE MARKET DATA PACKAGE v1.0.0 |
| 16 | `MOD-ATLAS_FINANCE.MARKET_DATA.BINANCE_PUBLIC_PROVIDER` | `atlas_finance/market_data/binance_public_provider.py` | ATLAS BINANCE PUBLIC DATA PROVIDER v1.0.0 |
| 17 | `MOD-ATLAS_FINANCE.MARKET_DATA.CONTRACTS` | `atlas_finance/market_data/contracts.py` | explicit: L1 domain contract example |
| 18 | `MOD-ATLAS_FINANCE.MARKET_DATA.EXCEPTIONS` | `atlas_finance/market_data/exceptions.py` | ATLAS MARKET DATA EXCEPTIONS v1.0.0 |
| 19 | `MOD-ATLAS_FINANCE.MARKET_DATA.MARKET_FEED_SERVICE` | `atlas_finance/market_data/market_feed_service.py` | ATLAS MARKET FEED SERVICE v1.0.0 |
| 20 | `MOD-ATLAS_FINANCE.MARKET_DATA.MODELS` | `atlas_finance/market_data/models.py` | explicit: L1 domain contract example |
| 21 | `MOD-ATLAS_FINANCE.MARKET_DATA.TEMPORAL` | `atlas_finance/market_data/temporal.py` | pure market-data temporal vocabulary (aware-UTC normalization and c... |
| 22 | `MOD-ATLAS_OS._INIT_` | `atlas_os/__init__.py` | ATLAS OPERATING SYSTEM — PUBLIC API |
| 23 | `MOD-ATLAS_OS.AUDIT._INIT_` | `atlas_os/audit/__init__.py` | AtlasOS persistent audit infrastructure. |
| 24 | `MOD-ATLAS_OS.AUDIT.AUDIT_LOG` | `atlas_os/audit/audit_log.py` | ATLAS OS AUDIT LOG SERVICE v1.0 |
| 25 | `MOD-ATLAS_OS.CONFIGURATION._INIT_` | `atlas_os/configuration/__init__.py` | AtlasOS configuration infrastructure. |
| 26 | `MOD-ATLAS_OS.CONFIGURATION.CONFIGURATION_SERVICE` | `atlas_os/configuration/configuration_service.py` | ATLAS OS CONFIGURATION SERVICE v1.0 |
| 27 | `MOD-ATLAS_OS.CONTRACTS` | `atlas_os/contracts.py` | explicit: L1 domain contract example; canonical AtlasOS contract au... |
| 28 | `MOD-ATLAS_OS.EVENTS._INIT_` | `atlas_os/events/__init__.py` | AtlasOS enterprise event infrastructure. |
| 29 | `MOD-ATLAS_OS.EVENTS.EVENT_BUS` | `atlas_os/events/event_bus.py` | ATLAS OS EVENT BUS v1.0 |
| 30 | `MOD-ATLAS_OS.INTEGRATION._INIT_` | `atlas_os/integration/__init__.py` | AtlasOS integration package. |
| 31 | `MOD-ATLAS_OS.INTEGRATION.CONFIGURATION_SECRETS_BRIDGE` | `atlas_os/integration/configuration_secrets_bridge.py` | ATLAS OS CONFIGURATION-SECRETS BRIDGE v2.0 |
| 32 | `MOD-ATLAS_OS.INTEGRATIONS._INIT_` | `atlas_os/integrations/__init__.py` | AtlasOS system integration infrastructure. |
| 33 | `MOD-ATLAS_OS.INTEGRATIONS.EVENT_INTEGRATION` | `atlas_os/integrations/event_integration.py` | ATLAS OS KERNEL EVENT INTEGRATION v1.0 |
| 34 | `MOD-ATLAS_OS.KERNEL._INIT_` | `atlas_os/kernel/__init__.py` | AtlasOS kernel infrastructure. |
| 35 | `MOD-ATLAS_OS.KERNEL.KERNEL` | `atlas_os/kernel/kernel.py` | ATLAS OS KERNEL v1.0 |
| 36 | `MOD-ATLAS_OS.OBSERVABILITY._INIT_` | `atlas_os/observability/__init__.py` | AtlasOS enterprise observability infrastructure. |
| 37 | `MOD-ATLAS_OS.OBSERVABILITY.HEALTH_MONITOR` | `atlas_os/observability/health_monitor.py` | ATLAS OS HEALTH MONITOR v1.0 |
| 38 | `MOD-ATLAS_OS.OBSERVABILITY.METRICS` | `atlas_os/observability/metrics.py` | ATLAS OS METRICS SERVICE v1.0 |
| 39 | `MOD-ATLAS_OS.SCHEDULING._INIT_` | `atlas_os/scheduling/__init__.py` | ATLAS OS SCHEDULING PACKAGE |
| 40 | `MOD-ATLAS_OS.SCHEDULING.SCHEDULER` | `atlas_os/scheduling/scheduler.py` | ATLAS OS SCHEDULER SERVICE v1.0 |
| 41 | `MOD-ATLAS_OS.SECRETS._INIT_` | `atlas_os/secrets/__init__.py` | AtlasOS Secrets Manager package. |
| 42 | `MOD-ATLAS_OS.SECRETS.SECRETS_MANAGER` | `atlas_os/secrets/secrets_manager.py` | ATLAS OS SECRETS MANAGER v1.0 |
| 43 | `MOD-ATLAS_OS.SERVICES._INIT_` | `atlas_os/services/__init__.py` | AtlasOS enterprise service management infrastructure. |
| 44 | `MOD-ATLAS_OS.SERVICES.BASE_SERVICE` | `atlas_os/services/base_service.py` | ATLAS OS BASE SERVICE v1.0 |
| 45 | `MOD-ATLAS_OS.SERVICES.DEPENDENCY_MANAGER` | `atlas_os/services/dependency_manager.py` | ATLAS OS DEPENDENCY-AWARE SERVICE MANAGER v1.0 |
| 46 | `MOD-ATLAS_OS.SERVICES.REGISTRY` | `atlas_os/services/registry.py` | ATLAS OS SERVICE REGISTRY v1.0 |
| 47 | `MOD-ATLAS_SECURITY._INIT_` | `atlas_security/__init__.py` | Atlas application-wide security boundaries. |
| 48 | `MOD-ATLAS_SECURITY.SENSITIVE_DATA_GUARD` | `atlas_security/sensitive_data_guard.py` | Fail-closed sanitization for Atlas output boundaries. |
| 49 | `MOD-CORE._INIT_` | `core/__init__.py` | Project Atlas AI legacy application core. |
| 50 | `MOD-CORE.APPLICATION` | `core/application.py` | explicit: L3 application example; canonical composition root |
| 51 | `MOD-CORE.AUDIT_EVENT` | `core/audit_event.py` | explicit: L1 domain contract example |
| 52 | `MOD-CORE.AUDIT_EVENT_STORE` | `core/audit_event_store.py` | persistent store, matches L2 example bucket |
| 53 | `MOD-CORE.BRAIN` | `core/brain.py` | explicit: L3 application example |
| 54 | `MOD-CORE.CANDLE_PROCESSOR` | `core/candle_processor.py` | market-data processing orchestration consumed by market_loop, not a... |
| 55 | `MOD-CORE.CAPITAL_RESERVATION` | `core/capital_reservation.py` | explicit: L1 domain contract example |
| 56 | `MOD-CORE.CONTROLLER._INIT_` | `core/controller/__init__.py` | AtlasController orchestration (application.py Control bucket) |
| 57 | `MOD-CORE.CONTROLLER.ATLAS_CONTROLLER` | `core/controller/atlas_controller.py` | ATLAS CONTROLLER v2.0 |
| 58 | `MOD-CORE.DECISION` | `core/decision.py` | explicit: L1 domain contract example |
| 59 | `MOD-CORE.DECISION_ADAPTER` | `core/decision_adapter.py` | explicit: L3 application example |
| 60 | `MOD-CORE.DECISION_INTELLIGENCE` | `core/decision_intelligence.py` | explicit: L1 domain contract example |
| 61 | `MOD-CORE.DURABLE_APPEND_LOG` | `core/durable_append_log.py` | durable append-only storage primitive, matches L2 example bucket |
| 62 | `MOD-CORE.EVENT_BUS` | `core/event_bus.py` | event bus implementation, matches L2 example bucket |
| 63 | `MOD-CORE.EXECUTION_IDEMPOTENCY_STORE` | `core/execution_idempotency_store.py` | persistent store, matches L2 example bucket |
| 64 | `MOD-CORE.EXECUTION_MANAGER` | `core/execution_manager.py` | explicit: L3 application example |
| 65 | `MOD-CORE.EXECUTION_MODELS` | `core/execution_models.py` | explicit: L1 domain contract example |
| 66 | `MOD-CORE.EXECUTION_PORTFOLIO_FOUNDATION` | `core/execution_portfolio_foundation.py` | canonical financial-state/portfolio-foundation domain authority, gr... |
| 67 | `MOD-CORE.EXECUTION_TRANSACTION_JOURNAL` | `core/execution_transaction_journal.py` | journal, matches L2 example bucket |
| 68 | `MOD-CORE.FEE_ACCOUNTING` | `core/fee_accounting.py` | pure fee-currency classification: FeeNormalizer is a stateless stat... |
| 69 | `MOD-CORE.INSTRUMENT_RULES` | `core/instrument_rules.py` | pure venue instrument-precision domain contract: immutable Instrume... |
| 70 | `MOD-CORE.LIFECYCLE` | `core/lifecycle.py` | infrastructure lifecycle manager (application.py Infrastructure buc... |
| 71 | `MOD-CORE.LOCAL_CAPABILITY_ADAPTER` | `core/local_capability_adapter.py` | concrete implementations of the L1 capability contracts (deny-by-de... |
| 72 | `MOD-CORE.LOGGER` | `core/logger.py` | infrastructure logging adapter |
| 73 | `MOD-CORE.MARKET_LOOP` | `core/market_loop.py` | explicit: L3 application example |
| 74 | `MOD-CORE.MODEL_PROVIDER_CONTRACTS` | `core/model_provider_contracts.py` | provider-neutral model invocation vocabulary; no SDK, client, or cr... |
| 75 | `MOD-CORE.OPERATIONAL_CONTRACTS` | `core/operational_contracts.py` | operation/policy vocabulary; data contracts only, no I/O (Block 3 c... |
| 76 | `MOD-CORE.PAPER_TRADER` | `core/paper_trader.py` | execution-orchestration collaborator alongside PositionController/C... |
| 77 | `MOD-CORE.POSITION_CONTROLLER` | `core/position_controller.py` | explicit: L3 application example |
| 78 | `MOD-CORE.POSITION_SIZING` | `core/position_sizing.py` | pure deterministic BUY sizing policy calculator: no I/O, no orchest... |
| 79 | `MOD-CORE.RISK_ENGINE` | `core/risk_engine.py` | explicit: L1 domain contract example; canonical execution/admission... |
| 80 | `MOD-CORE.RISK_STATE_STORE` | `core/risk_state_store.py` | Durable Phase-3 accounting state restoration boundary. |
| 81 | `MOD-CORE.RUNTIME` | `core/runtime.py` | explicit: L3 application example (composition root chain, main.py -... |
| 82 | `MOD-CORE.SCHEDULER` | `core/scheduler.py` | infrastructure scheduler (application.py Infrastructure bucket) |
| 83 | `MOD-CORE.SERVICE_CONTAINER` | `core/service_container.py` | infrastructure dependency container (application.py Infrastructure ... |
| 84 | `MOD-CORE.TECHNICAL_ANALYZER` | `core/technical_analyzer.py` | market analysis orchestration consumed by brain/market_loop, not a ... |
| 85 | `MOD-CORE.TOOL_GATEWAY_CONTRACTS` | `core/tool_gateway_contracts.py` | tool invocation vocabulary and the CapabilityGateway policy chokepo... |
| 86 | `MOD-CORE.VENUE_RULE_FRESHNESS` | `core/venue_rule_freshness.py` | Block 6A — venue instrument-rule freshness and staleness safety. |
| 87 | `MOD-DATA_LAYER._INIT_` | `data_layer/__init__.py` | Backend-independent Atlas relational persistence foundation. |
| 88 | `MOD-DATA_LAYER.CANONICAL_EVIDENCE` | `data_layer/canonical_evidence.py` | domain evidence contract, sibling of data_layer/contracts.py and da... |
| 89 | `MOD-DATA_LAYER.CONFIG` | `data_layer/config.py` | explicit: data-layer configuration is L2 infrastructure |
| 90 | `MOD-DATA_LAYER.CONTRACTS` | `data_layer/contracts.py` | explicit: L1 domain contract example |
| 91 | `MOD-DATA_LAYER.MIGRATIONS` | `data_layer/migrations.py` | explicit: data-layer migrations are L2 infrastructure |
| 92 | `MOD-DATA_LAYER.MODELS` | `data_layer/models.py` | explicit: L1 domain contract example |
| 93 | `MOD-DATA_LAYER.PROJECTION_REPLAY` | `data_layer/projection_replay.py` | Idempotent relational projection from confirmed authoritative evide... |
| 94 | `MOD-DATA_LAYER.RECOVERY` | `data_layer/recovery.py` | Fail-closed Phase-2 recovery assessment and startup admission gate. |
| 95 | `MOD-DATA_LAYER.RUNTIME_SAFETY` | `data_layer/runtime_safety.py` | Canonical financial-runtime recovery orchestration. |
| 96 | `MOD-DATA_LAYER.SEMANTIC_CONTRACTS` | `data_layer/semantic_contracts.py` | domain contract vocabulary, sibling of data_layer/contracts.py |
| 97 | `MOD-DATA_LAYER.SQLITE` | `data_layer/sqlite.py` | explicit: L2 infrastructure example |
| 98 | `MOD-EXCHANGE._INIT_` | `exchange/__init__.py` | explicit: exchange/** is L2 infrastructure |
| 99 | `MOD-EXCHANGE.MARKET_FEED` | `exchange/market_feed.py` | ATLAS MARKET FEED COMPATIBILITY ADAPTER v2.0.0 |
| 100 | `MOD-MAIN` | `main.py` | process entry point that constructs and starts the L3 composition r... |
| 101 | `MOD-OBSERVABILITY._INIT_` | `observability/__init__.py` | Read-only observability sources for the lightweight Atlas panel. |
| 102 | `MOD-OBSERVABILITY.PANEL_ROUTER` | `observability/panel_router.py` | Thin read-only FastAPI router for the lightweight observability panel. |
| 103 | `MOD-OBSERVABILITY.PANEL_SOURCES` | `observability/panel_sources.py` | Pure readers behind the lightweight observability panel. |
| 104 | `MOD-PORTFOLIO.CAPITAL_MANAGER` | `portfolio/capital_manager.py` | explicit: L3 application example (lifecycle/scheduler/controller or... |
| 105 | `MOD-WEB_APP` | `web_app.py` | explicit: L5 presentation example |

## Per-module detail

Every field below is transcribed verbatim from D1's JSON record for that module. `UNKNOWN` and `UNASSIGNED` are D1's own schema-native unresolved values (`ARCH-001.2.1_MODULE_INVENTORY_SCHEMA`), not this document's absence of effort.

### 1. `MOD-AI.CORE.ATLAS_BRAIN`

| field | value |
| --- | --- |
| file_path | ai/core/atlas_brain.py |
| package | ai.core |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS AI INTELLIGENCE BRAIN v10.2 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `ai/core/atlas_memory_core.py`, `ai/core/atlas_reasoning_engine.py`, `ai/core/atlas_world_model.py`, `ai/core/intelligence/agent_fusion.py`, `ai/core/intelligence/confidence/confidence_engine.py`, `ai/core/intelligence/decision_builder.py`, `ai/core/intelligence/memory_adapter.py`, `ai/core/intelligence/reasoning_adapter.py`, `ai/core/intelligence/risk_engine.py`, `core/decision_intelligence.py`

**Public interfaces:** `AtlasBrain`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `7B20934A63EF3298D8B08D13F27A18D2B145D6EC1C6D92C84BEBEEBCC3EC83C7`; references = `ai/core/atlas_brain.py`, `ai/core/atlas_brain.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 2. `MOD-AI.CORE.ATLAS_MEMORY_CORE`

| field | value |
| --- | --- |
| file_path | ai/core/atlas_memory_core.py |
| package | ai.core |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS MEMORY CORE v2.0 - Geliştirilmiş Hafıza Sistemi |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `AtlasMemoryCore`, `MarketEpisode`, `TradeOutcome`, `TradeRecord`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `C591A0D92A4279A4DE5BB8D895FB6CE982250FE592248256C0714140323A95D1`; references = `ai/core/atlas_memory_core.py`, `ai/core/atlas_memory_core.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 189', 'json.dump @ line 190', 'open() @ line 198', 'json.load @ line 199'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 189', 'json.dump @ line 190', 'open() @ line 198', 'json.load @ line 199']; ast_parse_error = None

### 3. `MOD-AI.CORE.ATLAS_REASONING_ENGINE`

| field | value |
| --- | --- |
| file_path | ai/core/atlas_reasoning_engine.py |
| package | ai.core |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS REASONING ENGINE v2.1 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_security/__init__.py`

**Public interfaces:** `AtlasReasoningEngine`, `ConfidenceLevel`, `Decision`, `DecisionType`, `ReasoningStep`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `81E180993FF77E2BCC46408A35279A7387F5B3F1ED3C939D7295EDF789033452`; references = `ai/core/atlas_reasoning_engine.py`, `ai/core/atlas_reasoning_engine.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 771', 'json.dump @ line 782', 'open() @ line 831', 'json.load @ line 842'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 771', 'json.dump @ line 782', 'open() @ line 831', 'json.load @ line 842']; ast_parse_error = None

### 4. `MOD-AI.CORE.ATLAS_WORLD_MODEL`

| field | value |
| --- | --- |
| file_path | ai/core/atlas_world_model.py |
| package | ai.core |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS WORLD MODEL v2.0 - Piyasa Iliskileri Grafi |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `AtlasWorldModel`, `MarketEdge`, `MarketNode`, `RelationshipType`, `SimpleGraph`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `2E22CC7F6829D73AB285D449B5B14DE17A21D10EE8DE0FDD878132DD86F5A95F`; references = `ai/core/atlas_world_model.py`, `ai/core/atlas_world_model.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 209', 'json.dump @ line 210', 'open() @ line 218', 'json.load @ line 219'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 209', 'json.dump @ line 210', 'open() @ line 218', 'json.load @ line 219']; ast_parse_error = None

### 5. `MOD-AI.CORE.INTELLIGENCE.AGENT_FUSION`

| field | value |
| --- | --- |
| file_path | ai/core/intelligence/agent_fusion.py |
| package | ai.core.intelligence |
| source_scope | UNKNOWN |
| current_responsibility | Atlas AI Agent Fusion Engine v10.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `analysis/evidence_status.py`

**Public interfaces:** `AgentFusion`, `AgentFusionResult`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `8EFEED1F39263E61792A565FFAFEDA4F636E80C32458AEF29A51C3C4755634FA`; references = `ai/core/intelligence/agent_fusion.py`, `ai/core/intelligence/agent_fusion.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 6. `MOD-AI.CORE.INTELLIGENCE.CONFIDENCE.CONFIDENCE_ENGINE`

| field | value |
| --- | --- |
| file_path | ai/core/intelligence/confidence/confidence_engine.py |
| package | ai.core.intelligence.confidence |
| source_scope | UNKNOWN |
| current_responsibility | Atlas AI Confidence Engine v10.1 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `ConfidenceEngine`, `ConfidenceResult`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `DD9C976D4654275C93158F6F321950C729DCF0886F682ABA60405D90EA232A60`; references = `ai/core/intelligence/confidence/confidence_engine.py`, `ai/core/intelligence/confidence/confidence_engine.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 7. `MOD-AI.CORE.INTELLIGENCE.DECISION_BUILDER`

| field | value |
| --- | --- |
| file_path | ai/core/intelligence/decision_builder.py |
| package | ai.core.intelligence |
| source_scope | UNKNOWN |
| current_responsibility | Atlas AI Decision Builder v10.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `core/decision.py`

**Public interfaces:** `DecisionBuilder`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `C1C712DAA943C56B2364D15668E31F974A357D38C3B20624923968352BF5C59A`; references = `ai/core/intelligence/decision_builder.py`, `ai/core/intelligence/decision_builder.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 8. `MOD-AI.CORE.INTELLIGENCE.MEMORY_ADAPTER`

| field | value |
| --- | --- |
| file_path | ai/core/intelligence/memory_adapter.py |
| package | ai.core.intelligence |
| source_scope | UNKNOWN |
| current_responsibility | Atlas AI Memory Adapter v10.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `MemoryAdapter`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `D07080F223BCA9EDBFED2D72768657C422F95CDC6BF9B518B86B8024F53720A1`; references = `ai/core/intelligence/memory_adapter.py`, `ai/core/intelligence/memory_adapter.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 9. `MOD-AI.CORE.INTELLIGENCE.REASONING_ADAPTER`

| field | value |
| --- | --- |
| file_path | ai/core/intelligence/reasoning_adapter.py |
| package | ai.core.intelligence |
| source_scope | UNKNOWN |
| current_responsibility | Atlas AI Reasoning Adapter v10.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `ReasoningAdapter`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `4244E51A485730AD53AD00C9E11B4AA30641E1BE3F2EEA7F658B4343D329BDD4`; references = `ai/core/intelligence/reasoning_adapter.py`, `ai/core/intelligence/reasoning_adapter.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 10. `MOD-AI.CORE.INTELLIGENCE.RISK_ENGINE`

| field | value |
| --- | --- |
| file_path | ai/core/intelligence/risk_engine.py |
| package | ai.core.intelligence |
| source_scope | UNKNOWN |
| current_responsibility | Atlas AI Risk Engine v10.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `AdvisoryRiskScorer`, `RiskCategory`, `RiskResult`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `6691737878B29F95F62B4794E03101C1DA5BC1B301CCC8D575CDA0F057B31F5C`; references = `ai/core/intelligence/risk_engine.py`, `ai/core/intelligence/risk_engine.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 11. `MOD-ANALYSIS._INIT_`

| field | value |
| --- | --- |
| file_path | analysis/__init__.py |
| package | analysis |
| source_scope | UNKNOWN |
| current_responsibility | Atlas Analysis Layer |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `4D80CDF7EFBBFF723404594D4829655461CA766B66F3E818ED90914192036C72`; references = `analysis/__init__.py`, `analysis/__init__.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 12. `MOD-ANALYSIS.EVIDENCE_STATUS`

| field | value |
| --- | --- |
| file_path | analysis/evidence_status.py |
| package | analysis |
| source_scope | UNKNOWN |
| current_responsibility | explicit: shared L1 vocabulary exception within analysis/** |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `MarketDataEvidenceStatus`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `18B85F3CC8C0A3C98E04486E45BEA963E8E22FD22841480215D9A00BEDB19E08`; references = `analysis/evidence_status.py`, `packaging/atlas_architecture_map.json#layer_rules[analysis/evidence_status.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 13. `MOD-ANALYSIS.WORLD_ANALYSIS_ENGINE`

| field | value |
| --- | --- |
| file_path | analysis/world_analysis_engine.py |
| package | analysis |
| source_scope | UNKNOWN |
| current_responsibility | Atlas AI |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `analysis/evidence_status.py`

**Public interfaces:** `WorldAnalysisEngine`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `75492B498A05EF793C42EF8B07A38A546EF1B6EAB995FAF50D41DF8DF3922C25`; references = `analysis/world_analysis_engine.py`, `analysis/world_analysis_engine.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | WORLD_ANALYSIS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 14. `MOD-ATLAS_FINANCE._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_finance/__init__.py |
| package | atlas_finance |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS FINANCE v1.0.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_finance/market_data/__init__.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `348F525C07EAC044A8178540618339E03DF608FDBB614746E5ED860CA5D09355`; references = `atlas_finance/__init__.py`, `atlas_finance/__init__.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** event_signal_hits=['EventBus symbol @ line 20']; ast_parse_error = None

### 15. `MOD-ATLAS_FINANCE.MARKET_DATA._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_finance/market_data/__init__.py |
| package | atlas_finance.market_data |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS FINANCE MARKET DATA PACKAGE v1.0.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_finance/market_data/binance_public_provider.py`, `atlas_finance/market_data/contracts.py`, `atlas_finance/market_data/exceptions.py`, `atlas_finance/market_data/market_feed_service.py`, `atlas_finance/market_data/models.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `DAA09EDFBC79DC41E1A746B639260E58D30DA4F16B3A0A7FF710BEC8DDCFCF74`; references = `atlas_finance/market_data/__init__.py`, `atlas_finance/market_data/__init__.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | MARKET_DATA | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 16. `MOD-ATLAS_FINANCE.MARKET_DATA.BINANCE_PUBLIC_PROVIDER`

| field | value |
| --- | --- |
| file_path | atlas_finance/market_data/binance_public_provider.py |
| package | atlas_finance.market_data |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS BINANCE PUBLIC DATA PROVIDER v1.0.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_finance/market_data/contracts.py`, `atlas_finance/market_data/exceptions.py`, `atlas_finance/market_data/models.py`

**Public interfaces:** `BinancePublicDataProvider`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `70DD660A24C6E4C930710575B960EF90AB499EA02401BB451A075D52F9317186`; references = `atlas_finance/market_data/binance_public_provider.py`, `atlas_finance/market_data/binance_public_provider.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | MARKET_DATA | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | EXTERNAL | Mechanical regex evidence of persistence/external-I/O call sites: ['requests. @ line 54', 'requests. @ line 57', 'requests. @ line 60', 'requests. @ line 232', 'requests. @ line 328'] |

**Mechanical evidence:** external_interface_signal_hits=['requests. @ line 54', 'requests. @ line 57', 'requests. @ line 60', 'requests. @ line 232', 'requests. @ line 328']; ast_parse_error = None

### 17. `MOD-ATLAS_FINANCE.MARKET_DATA.CONTRACTS`

| field | value |
| --- | --- |
| file_path | atlas_finance/market_data/contracts.py |
| package | atlas_finance.market_data |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_finance/market_data/models.py`

**Public interfaces:** `MarketDataProviderProtocol`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `FCB4D7EB4E94FEEF4894F2F99F854E051B7BBC29C44D8CC848790837E42B6A8B`; references = `atlas_finance/market_data/contracts.py`, `packaging/atlas_architecture_map.json#layer_rules[atlas_finance/market_data/contracts.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | MARKET_DATA | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 18. `MOD-ATLAS_FINANCE.MARKET_DATA.EXCEPTIONS`

| field | value |
| --- | --- |
| file_path | atlas_finance/market_data/exceptions.py |
| package | atlas_finance.market_data |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS MARKET DATA EXCEPTIONS v1.0.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `InvalidCandleError`, `InvalidCandleLimitError`, `InvalidPriceError`, `InvalidSymbolError`, `InvalidTimeframeError`, `MarketDataConfigurationError`, `MarketDataConnectionError`, `MarketDataError`, `MarketDataProviderError`, `MarketDataProviderUnavailableError`, `MarketDataRateLimitError`, `MarketDataRequestError`, `MarketDataResponseError`, `MarketDataServiceError`, `MarketDataServiceNotRunningError`, `MarketDataServiceShutdownError`, `MarketDataServiceStartupError`, `MarketDataTimeoutError`, `MarketDataValidationError`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `17FB8C4A632732DB559F6B7C095008648762EBCE3B1C638C8A0FE0E0F74EADBE`; references = `atlas_finance/market_data/exceptions.py`, `atlas_finance/market_data/exceptions.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | MARKET_DATA | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 19. `MOD-ATLAS_FINANCE.MARKET_DATA.MARKET_FEED_SERVICE`

| field | value |
| --- | --- |
| file_path | atlas_finance/market_data/market_feed_service.py |
| package | atlas_finance.market_data |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS MARKET FEED SERVICE v1.0.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_finance/market_data/contracts.py`, `atlas_finance/market_data/exceptions.py`, `atlas_finance/market_data/models.py`, `atlas_os/__init__.py`

**Public interfaces:** `MarketFeedEventType`, `MarketFeedService`, `_MutableRequestStatistics`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `48A3EC530CE9547A5F2FB3B96F6EDA6F8B9D83A62C1C59A3AE4A3A5B5E01871C`; references = `atlas_finance/market_data/market_feed_service.py`, `atlas_finance/market_data/market_feed_service.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | MARKET_DATA | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 20. `MOD-ATLAS_FINANCE.MARKET_DATA.MODELS`

| field | value |
| --- | --- |
| file_path | atlas_finance/market_data/models.py |
| package | atlas_finance.market_data |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `MarketCandle`, `MarketDataRequestStatistics`, `MarketFeedSnapshot`, `MarketFeedStatistics`, `MarketPrice`, `candles_as_dicts`, `immutable_mapping`, `utc_now`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `25891803A217E030A5DB035D12079F9D280B086BFA215150F5858AE40D6E7CBE`; references = `atlas_finance/market_data/models.py`, `packaging/atlas_architecture_map.json#layer_rules[atlas_finance/market_data/models.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | MARKET_DATA | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 21. `MOD-ATLAS_FINANCE.MARKET_DATA.TEMPORAL`

| field | value |
| --- | --- |
| file_path | atlas_finance/market_data/temporal.py |
| package | atlas_finance.market_data |
| source_scope | UNKNOWN |
| current_responsibility | pure market-data temporal vocabulary (aware-UTC normalization and cutoff-relative closure), stdlib-only with no I/O and no clock; sibling of atlas_finance/market_data/models.py and contracts.py, so it is exempt from the generic atlas_finance/* -> L2 default (Block 4 market-data correctness) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `TemporalContractError`, `is_closed_at`, `is_future_open_at`, `require_aware_utc`, `to_milliseconds`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `25424981252C6E5647FF76A0D838AF04C6A3D2D90E8DFBDE92167FF4E8082ACB`; references = `atlas_finance/market_data/temporal.py`, `packaging/atlas_architecture_map.json#layer_rules[atlas_finance/market_data/temporal.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | MARKET_DATA | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 22. `MOD-ATLAS_OS._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/__init__.py |
| package | atlas_os |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OPERATING SYSTEM — PUBLIC API |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/audit/__init__.py`, `atlas_os/configuration/__init__.py`, `atlas_os/contracts.py`, `atlas_os/events/__init__.py`, `atlas_os/integration/__init__.py`, `atlas_os/integrations/__init__.py`, `atlas_os/kernel/__init__.py`, `atlas_os/observability/__init__.py`, `atlas_os/scheduling/__init__.py`, `atlas_os/secrets/__init__.py`, `atlas_os/services/__init__.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `DC06C4F8FBD447BDE465BDFDF267D2C126434D1017162176189FE5954A19B57B`; references = `atlas_os/__init__.py`, `atlas_os/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 23. `MOD-ATLAS_OS.AUDIT._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/audit/__init__.py |
| package | atlas_os.audit |
| source_scope | UNKNOWN |
| current_responsibility | AtlasOS persistent audit infrastructure. |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/audit/audit_log.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `BD1AE40A3EF830050236D2943375E9A205D570ACEEC7C668FC9AE4AA284A1AA2`; references = `atlas_os/audit/__init__.py`, `atlas_os/audit/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | SECURITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 24. `MOD-ATLAS_OS.AUDIT.AUDIT_LOG`

| field | value |
| --- | --- |
| file_path | atlas_os/audit/audit_log.py |
| package | atlas_os.audit |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS AUDIT LOG SERVICE v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/events/__init__.py`, `atlas_os/services/__init__.py`, `atlas_security/__init__.py`

**Public interfaces:** `AuditLogError`, `AuditLogService`, `AuditLogSnapshot`, `AuditPersistenceError`, `AuditQuery`, `AuditRecord`, `AuditStatistics`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `29028D8E9A7312AFC9DC8D5698CEC9C3C1604C1D01DCFBDCE7BFDCA242EF9F6C`; references = `atlas_os/audit/audit_log.py`, `atlas_os/audit/audit_log.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | SECURITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 590', 'open() @ line 647'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 590', 'open() @ line 647']; event_signal_hits=['.subscribe( @ line 451']; ast_parse_error = None

### 25. `MOD-ATLAS_OS.CONFIGURATION._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/configuration/__init__.py |
| package | atlas_os.configuration |
| source_scope | UNKNOWN |
| current_responsibility | AtlasOS configuration infrastructure. |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/configuration/configuration_service.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `31D76C4A0C0E6AA71E5F9CCF79EA47C262BFE12A95AE06EA00BFDD2309EE36AA`; references = `atlas_os/configuration/__init__.py`, `atlas_os/configuration/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | CONFIGURATION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 26. `MOD-ATLAS_OS.CONFIGURATION.CONFIGURATION_SERVICE`

| field | value |
| --- | --- |
| file_path | atlas_os/configuration/configuration_service.py |
| package | atlas_os.configuration |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS CONFIGURATION SERVICE v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/events/__init__.py`, `atlas_os/services/__init__.py`

**Public interfaces:** `ConfigurationChange`, `ConfigurationConversionError`, `ConfigurationEntry`, `ConfigurationEnvironment`, `ConfigurationError`, `ConfigurationEventType`, `ConfigurationKeyNotFoundError`, `ConfigurationSchema`, `ConfigurationService`, `ConfigurationSnapshot`, `ConfigurationSource`, `ConfigurationSourceError`, `ConfigurationStatistics`, `ConfigurationValidationError`, `ConfigurationValueType`, `DuplicateConfigurationKeyError`, `ProductionSafetyError`, `_ConfigurationValue`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `5B4960A3BB92E8EE265948FA749E19A3164B1F84098B217EE4979678DD23EB6E`; references = `atlas_os/configuration/configuration_service.py`, `atlas_os/configuration/configuration_service.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | CONFIGURATION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 824', 'json.load @ line 829'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 824', 'json.load @ line 829']; ast_parse_error = None

### 27. `MOD-ATLAS_OS.CONTRACTS`

| field | value |
| --- | --- |
| file_path | atlas_os/contracts.py |
| package | atlas_os |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example; canonical AtlasOS contract authority (ADR-0002) |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** none recorded

**Public interfaces:** `AtlasService`, `HealthReport`, `HealthStatus`, `ServiceIdentity`, `ServiceSnapshot`, `ServiceState`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `4BFE221888DB0A661F6FA1B0E0772012678AAC2025D7560D17DE0154835EF739`; references = `atlas_os/contracts.py`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`, `packaging/atlas_architecture_map.json#layer_rules[atlas_os/contracts.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 28. `MOD-ATLAS_OS.EVENTS._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/events/__init__.py |
| package | atlas_os.events |
| source_scope | UNKNOWN |
| current_responsibility | AtlasOS enterprise event infrastructure. |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/events/event_bus.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `47DE24E972ADC5F1114E28DA9DF9100805144D47CF6194298DFEDD25A37C6474`; references = `atlas_os/events/__init__.py`, `atlas_os/events/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EVENTS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 29. `MOD-ATLAS_OS.EVENTS.EVENT_BUS`

| field | value |
| --- | --- |
| file_path | atlas_os/events/event_bus.py |
| package | atlas_os.events |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS EVENT BUS v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/services/__init__.py`, `atlas_security/__init__.py`

**Public interfaces:** `AtlasEvent`, `DeliveryFailure`, `EventBusError`, `EventBusNotRunningError`, `EventBusService`, `EventBusSnapshot`, `EventSeverity`, `PublishResult`, `Subscription`, `SubscriptionNotFoundError`, `_SubscriberRecord`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `52D2D8C20AFFE7C83CFCB2A07DF0980E756F89DF6AD6533654FEC406416A9B82`; references = `atlas_os/events/event_bus.py`, `atlas_os/events/event_bus.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EVENTS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** event_signal_hits=['EventBus symbol @ line 73', '.subscribe( @ line 272', '.publish( @ line 773']; ast_parse_error = None

### 30. `MOD-ATLAS_OS.INTEGRATION._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/integration/__init__.py |
| package | atlas_os.integration |
| source_scope | UNKNOWN |
| current_responsibility | AtlasOS integration package. |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/integration/configuration_secrets_bridge.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `C54E7D4875E989F505CB1B478D937FA982DD436011CA53ED5FA7AAC7FF5608A6`; references = `atlas_os/integration/__init__.py`, `atlas_os/integration/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 31. `MOD-ATLAS_OS.INTEGRATION.CONFIGURATION_SECRETS_BRIDGE`

| field | value |
| --- | --- |
| file_path | atlas_os/integration/configuration_secrets_bridge.py |
| package | atlas_os.integration |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS CONFIGURATION-SECRETS BRIDGE v2.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/secrets/__init__.py`

**Public interfaces:** `ConfigurationReaderProtocol`, `ConfigurationSecretsBridge`, `ConfigurationSecretsBridgeError`, `ConfigurationSecretsSnapshot`, `ConfigurationValueNotFoundError`, `SecretBinding`, `SecretBindingMode`, `SecretBindingNotFoundError`, `SecretBindingRegistrationError`, `SecretBindingResult`, `SecretBindingStatus`, `UnsafeSecretConfigurationError`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `08D287829FD394B4020C6C655C73BE657ABD2D080AA16F44B11254BDDD2A3D90`; references = `atlas_os/integration/configuration_secrets_bridge.py`, `atlas_os/integration/configuration_secrets_bridge.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 32. `MOD-ATLAS_OS.INTEGRATIONS._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/integrations/__init__.py |
| package | atlas_os.integrations |
| source_scope | UNKNOWN |
| current_responsibility | AtlasOS system integration infrastructure. |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/integrations/event_integration.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `4819335AEADB2F042CAF10514C24BEAE980C235F8720691577EA2A52904ECECD`; references = `atlas_os/integrations/__init__.py`, `atlas_os/integrations/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 33. `MOD-ATLAS_OS.INTEGRATIONS.EVENT_INTEGRATION`

| field | value |
| --- | --- |
| file_path | atlas_os/integrations/event_integration.py |
| package | atlas_os.integrations |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS KERNEL EVENT INTEGRATION v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/events/__init__.py`, `atlas_os/kernel/__init__.py`, `atlas_os/observability/__init__.py`, `atlas_os/services/__init__.py`

**Public interfaces:** `AtlasSystemEventType`, `EventAwareAtlasOSKernel`, `EventAwareHealthMonitorService`, `EventIntegrationStatistics`, `_SafeEventPublisher`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `29DAC5B21DC8BA2A104D68FEDAC0C8C2F2951A61B8070630394C1B1EA6BA6345`; references = `atlas_os/integrations/event_integration.py`, `atlas_os/integrations/event_integration.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EVENTS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 34. `MOD-ATLAS_OS.KERNEL._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/kernel/__init__.py |
| package | atlas_os.kernel |
| source_scope | UNKNOWN |
| current_responsibility | AtlasOS kernel infrastructure. |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/kernel/kernel.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `62DFA86F7F514C546B883B39DA77A3C2DF23D76EA6102C1F9479FA2575D89CED`; references = `atlas_os/kernel/__init__.py`, `atlas_os/kernel/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | RUNTIME | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 35. `MOD-ATLAS_OS.KERNEL.KERNEL`

| field | value |
| --- | --- |
| file_path | atlas_os/kernel/kernel.py |
| package | atlas_os.kernel |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS KERNEL v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/services/__init__.py`

**Public interfaces:** `AtlasOSKernel`, `KernelHealthReport`, `KernelIdentity`, `KernelLifecycleError`, `KernelSnapshot`, `KernelState`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `178A4ED34B5E170932F3877B5EE24CDBF27DC255E2E4C90B70DAF8CA580BD989`; references = `atlas_os/kernel/kernel.py`, `atlas_os/kernel/kernel.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | RUNTIME | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 36. `MOD-ATLAS_OS.OBSERVABILITY._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/observability/__init__.py |
| package | atlas_os.observability |
| source_scope | UNKNOWN |
| current_responsibility | AtlasOS enterprise observability infrastructure. |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/observability/health_monitor.py`, `atlas_os/observability/metrics.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `6571C2458CA08CDB53BE4479929F0DEAE511A54EA252D1104ACA93BC065CA02B`; references = `atlas_os/observability/__init__.py`, `atlas_os/observability/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OBSERVABILITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 37. `MOD-ATLAS_OS.OBSERVABILITY.HEALTH_MONITOR`

| field | value |
| --- | --- |
| file_path | atlas_os/observability/health_monitor.py |
| package | atlas_os.observability |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS HEALTH MONITOR v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/kernel/__init__.py`, `atlas_os/services/__init__.py`

**Public interfaces:** `HealthMonitorService`, `HealthMonitorSnapshot`, `HealthObservation`, `HealthTransition`, `HealthTransitionType`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `1BD87191CFDD308B6E85087C59C91E6BDE7DEF4EFAE7276C43368D05566E98E4`; references = `atlas_os/observability/health_monitor.py`, `atlas_os/observability/health_monitor.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OBSERVABILITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 38. `MOD-ATLAS_OS.OBSERVABILITY.METRICS`

| field | value |
| --- | --- |
| file_path | atlas_os/observability/metrics.py |
| package | atlas_os.observability |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS METRICS SERVICE v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/events/__init__.py`, `atlas_os/services/__init__.py`

**Public interfaces:** `CounterMetric`, `GaugeMetric`, `HistogramMetric`, `InvalidMetricNameError`, `MetricIdentity`, `MetricTimer`, `MetricType`, `MetricTypeConflictError`, `MetricsError`, `MetricsService`, `MetricsSnapshot`, `MetricsStatistics`, `_CounterState`, `_GaugeState`, `_HistogramState`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `73E3D4F44AD091B9A6127599CCDEDFAB9B5F346AEBE5A25CBA6C015B136150B4`; references = `atlas_os/observability/metrics.py`, `atlas_os/observability/metrics.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OBSERVABILITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** event_signal_hits=['.subscribe( @ line 467']; ast_parse_error = None

### 39. `MOD-ATLAS_OS.SCHEDULING._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/scheduling/__init__.py |
| package | atlas_os.scheduling |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS SCHEDULING PACKAGE |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/scheduling/scheduler.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `9BBFAECEA35AFFD8ADC19AA4AD1F5FD04AE8AF443F7AB65CC76E513689A94562`; references = `atlas_os/scheduling/__init__.py`, `atlas_os/scheduling/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OPERATIONS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 40. `MOD-ATLAS_OS.SCHEDULING.SCHEDULER`

| field | value |
| --- | --- |
| file_path | atlas_os/scheduling/scheduler.py |
| package | atlas_os.scheduling |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS SCHEDULER SERVICE v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/events/__init__.py`, `atlas_os/services/__init__.py`

**Public interfaces:** `DuplicateTaskError`, `InvalidTaskConfigurationError`, `RetryPolicy`, `ScheduledTaskSnapshot`, `ScheduledTaskState`, `SchedulerError`, `SchedulerEventType`, `SchedulerService`, `SchedulerSnapshot`, `SchedulerStatistics`, `TaskConfiguration`, `TaskExecutionError`, `TaskExecutionRecord`, `TaskExecutionStatus`, `TaskNotFoundError`, `TaskScheduleType`, `_ScheduledTask`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `EAC425CE4DD2F7DF99C43CDD78206C8B2EDC58641260A44D821CBEC2D50CE051`; references = `atlas_os/scheduling/scheduler.py`, `atlas_os/scheduling/scheduler.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OPERATIONS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 41. `MOD-ATLAS_OS.SECRETS._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/secrets/__init__.py |
| package | atlas_os.secrets |
| source_scope | UNKNOWN |
| current_responsibility | AtlasOS Secrets Manager package. |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/secrets/secrets_manager.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `7CE774FA82932D180C1AF31C40FA7B65998EDF5849EB0401BF9022C04996A552`; references = `atlas_os/secrets/__init__.py`, `atlas_os/secrets/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | SECRETS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 42. `MOD-ATLAS_OS.SECRETS.SECRETS_MANAGER`

| field | value |
| --- | --- |
| file_path | atlas_os/secrets/secrets_manager.py |
| package | atlas_os.secrets |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS SECRETS MANAGER v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/events/__init__.py`, `atlas_os/services/__init__.py`

**Public interfaces:** `DuplicateSecretError`, `SecretAccessDeniedError`, `SecretAccessRecord`, `SecretChangeRecord`, `SecretDefinition`, `SecretEventType`, `SecretExpiredError`, `SecretMetadata`, `SecretNotFoundError`, `SecretRevokedError`, `SecretSource`, `SecretStatus`, `SecretValidationError`, `SecretValueMissingError`, `SecretsManager`, `SecretsManagerError`, `SecretsManagerSnapshot`, `SecretsManagerStatistics`, `_StoredSecret`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `1126314BCFEB34490EAB76DDD802A2A4E5796EDBBFE6331FC774C379244B1D30`; references = `atlas_os/secrets/secrets_manager.py`, `atlas_os/secrets/secrets_manager.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | SECRETS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 43. `MOD-ATLAS_OS.SERVICES._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_os/services/__init__.py |
| package | atlas_os.services |
| source_scope | UNKNOWN |
| current_responsibility | AtlasOS enterprise service management infrastructure. |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/services/base_service.py`, `atlas_os/services/dependency_manager.py`, `atlas_os/services/registry.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `11F71D591CB48AFC847C2D4C40B8F975F4B83B568BEBB7975AC22E9E9D5DCC8D`; references = `atlas_os/services/__init__.py`, `atlas_os/services/__init__.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 44. `MOD-ATLAS_OS.SERVICES.BASE_SERVICE`

| field | value |
| --- | --- |
| file_path | atlas_os/services/base_service.py |
| package | atlas_os.services |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS BASE SERVICE v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`

**Public interfaces:** `BaseAtlasService`, `ServiceLifecycleError`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `0879CDE337933F8E7377484B65D6A5A6E360814F83FEAC8B4FE69FAB0C5BFE08`; references = `atlas_os/services/base_service.py`, `atlas_os/services/base_service.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 45. `MOD-ATLAS_OS.SERVICES.DEPENDENCY_MANAGER`

| field | value |
| --- | --- |
| file_path | atlas_os/services/dependency_manager.py |
| package | atlas_os.services |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS DEPENDENCY-AWARE SERVICE MANAGER v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`, `atlas_os/services/registry.py`

**Public interfaces:** `CircularDependencyError`, `DependencyDeclaration`, `DependencyManagerError`, `DependencyServiceManager`, `InvalidDependencyError`, `MissingDependencyError`, `OrchestrationAction`, `OrchestrationPlan`, `OrchestrationResult`, `OrchestrationStep`, `ServiceBlockedError`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `E071300E73F19F7EDA7E84391C4E453153AA04655AD4812C2B7DC558AF08C32D`; references = `atlas_os/services/dependency_manager.py`, `atlas_os/services/dependency_manager.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OPERATIONS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 46. `MOD-ATLAS_OS.SERVICES.REGISTRY`

| field | value |
| --- | --- |
| file_path | atlas_os/services/registry.py |
| package | atlas_os.services |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS OS SERVICE REGISTRY v1.0 |
| intended_responsibility | Canonical AtlasOS authority/infrastructure implementation re-exported from atlas_os/__init__.py, per ADR-0002 (docs/adr/0002-atlas-os-contract-authority.md). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `atlas_os/contracts.py`

**Public interfaces:** `DuplicateServiceError`, `RegistryHealthReport`, `RegistrySnapshot`, `ServiceNotFoundError`, `ServiceOperationResult`, `ServiceRegistry`, `ServiceRegistryError`, `ServiceRemovalError`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `FE6B488C4A578A00362CDD912703854907FED6064D190002D183269279FFA961`; references = `atlas_os/services/registry.py`, `atlas_os/services/registry.py (module docstring, first substantive line)`, `docs/adr/0002-atlas-os-contract-authority.md#Decision`, `packaging/atlas_architecture_map.json#canonical_authorities.atlas_os`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 47. `MOD-ATLAS_SECURITY._INIT_`

| field | value |
| --- | --- |
| file_path | atlas_security/__init__.py |
| package | atlas_security |
| source_scope | UNKNOWN |
| current_responsibility | Atlas application-wide security boundaries. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_security/sensitive_data_guard.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `76C9FEA5505033CB6AB50CFA72AC47C30A5662F3B86145CA09E82B2F14ECE597`; references = `atlas_security/__init__.py`, `atlas_security/__init__.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | SECURITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 48. `MOD-ATLAS_SECURITY.SENSITIVE_DATA_GUARD`

| field | value |
| --- | --- |
| file_path | atlas_security/sensitive_data_guard.py |
| package | atlas_security |
| source_scope | UNKNOWN |
| current_responsibility | Fail-closed sanitization for Atlas output boundaries. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `sanitize_sensitive_data`, `sanitize_sensitive_mapping`, `sanitize_sensitive_text`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `ED9FB2532E55454BB14BA35B5935ACB550A4100311005334AB5254C7B205B91B`; references = `atlas_security/sensitive_data_guard.py`, `atlas_security/sensitive_data_guard.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | SECURITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 49. `MOD-CORE._INIT_`

| field | value |
| --- | --- |
| file_path | core/__init__.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | Project Atlas AI legacy application core. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `DA133DB6235103E1661F461F10BE624C5C8EFCB21E99EEE6084424CBD35E314C`; references = `core/__init__.py`, `core/__init__.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 50. `MOD-CORE.APPLICATION`

| field | value |
| --- | --- |
| file_path | core/application.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L3 application example; canonical composition root |
| intended_responsibility | Sole canonical composition root for the Atlas runtime (AtlasApplication); the only place in the repository that constructs AtlasBrain, MarketLoop, and ExecutionManager together as a wired system (AtlasApplication._build_services). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `core/audit_event_store.py`, `core/brain.py`, `core/capital_reservation.py`, `core/controller/atlas_controller.py`, `core/event_bus.py`, `core/execution_idempotency_store.py`, `core/execution_manager.py`, `core/execution_portfolio_foundation.py`, `core/execution_transaction_journal.py`, `core/instrument_rules.py`, `core/lifecycle.py`, `core/local_capability_adapter.py`, `core/logger.py`, `core/market_loop.py`, `core/paper_trader.py`, `core/position_controller.py`, `core/position_sizing.py`, `core/risk_engine.py`, `core/risk_state_store.py`, `core/runtime.py`, `core/scheduler.py`, `core/service_container.py`, `core/tool_gateway_contracts.py`, `core/venue_rule_freshness.py`, `exchange/market_feed.py`, `portfolio/capital_manager.py`

**Public interfaces:** `AtlasApplication`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `4381C89AD187A16BE2D785EB9857963EB833F84F8C3BD5C5C9AE1AB8301CD52D`; references = `core/application.py`, `docs/adr/0001-canonical-composition-root.md#Decision`, `docs/adr/0001-canonical-composition-root.md#Evidence`, `packaging/atlas_architecture_map.json#composition_root`, `packaging/atlas_architecture_map.json#layer_rules[core/application.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | APP | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** event_signal_hits=['EventBus symbol @ line 26', 'EventBus symbol @ line 64', 'EventBus symbol @ line 242']; ast_parse_error = None

### 51. `MOD-CORE.AUDIT_EVENT`

| field | value |
| --- | --- |
| file_path | core/audit_event.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_security/__init__.py`

**Public interfaces:** `AuditEvent`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `571DB9BC1384E4CE9D7DE54677DBE71BB9584FF8939BB41E6DDF400F72C3636D`; references = `core/audit_event.py`, `packaging/atlas_architecture_map.json#layer_rules[core/audit_event.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EVENTS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 52. `MOD-CORE.AUDIT_EVENT_STORE`

| field | value |
| --- | --- |
| file_path | core/audit_event_store.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | persistent store, matches L2 example bucket |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `core/audit_event.py`

**Public interfaces:** `AuditEventStore`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `6534925D5F476D151BB18FC11093363794A6F6D5656C1D7F16BF685E204F2DCA`; references = `core/audit_event_store.py`, `packaging/atlas_architecture_map.json#layer_rules[core/audit_event_store.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EVENTS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 319', 'open() @ line 398', 'open() @ line 586'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 319', 'open() @ line 398', 'open() @ line 586']; ast_parse_error = None

### 53. `MOD-CORE.BRAIN`

| field | value |
| --- | --- |
| file_path | core/brain.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L3 application example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `ai/core/atlas_brain.py`, `core/decision_adapter.py`

**Public interfaces:** `AtlasBrain`, `BrainState`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `379A0DD2CFF14D1360C91123400FC145C80135742787EAC22A7513D7EE9EC125`; references = `core/brain.py`, `packaging/atlas_architecture_map.json#layer_rules[core/brain.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 54. `MOD-CORE.CANDLE_PROCESSOR`

| field | value |
| --- | --- |
| file_path | core/candle_processor.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | market-data processing orchestration consumed by market_loop, not a pure domain contract |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_finance/market_data/temporal.py`

**Public interfaces:** `CandleConflictError`, `CandleContractError`, `CandleOrderingError`, `CandleProcessor`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `CC832DC1A39C00DE8235ED9A8B65EA7731791B58649FF3BA3F3F8F6AD3D8AFC3`; references = `core/candle_processor.py`, `packaging/atlas_architecture_map.json#layer_rules[core/candle_processor.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | CANDLES | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 55. `MOD-CORE.CAPITAL_RESERVATION`

| field | value |
| --- | --- |
| file_path | core/capital_reservation.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example |
| intended_responsibility | M-1 canonical risk service, grouped with core/risk_engine.py and core/execution_portfolio_foundation.py. |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `core/risk_engine.py`

**Public interfaces:** `CapitalReservation`, `CapitalReservationLedger`, `JsonReservationStore`, `ReservationArchive`, `ReservationArchiveConflictError`, `ReservationArchiveCorruptError`, `ReservationArchiveError`, `ReservationArchiveStore`, `ReservationSchemaMigrationRequiredError`, `ReservationStatus`, `ReservationStore`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `047682D25DB290A4A2F0C641413A10AF92A62D020D699331E0281625863E9760`; references = `core/capital_reservation.py`, `packaging/atlas_architecture_map.json#layer_rules[core/capital_reservation.py]`, `packaging/atlas_architecture_map.json#layer_rules[core/execution_portfolio_foundation.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | CAPITAL | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 110', 'json.dump @ line 111', 'open() @ line 166', 'open() @ line 175'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 110', 'json.dump @ line 111', 'open() @ line 166', 'open() @ line 175']; ast_parse_error = None

### 56. `MOD-CORE.CONTROLLER._INIT_`

| field | value |
| --- | --- |
| file_path | core/controller/__init__.py |
| package | core.controller |
| source_scope | UNKNOWN |
| current_responsibility | AtlasController orchestration (application.py Control bucket) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `core/controller/atlas_controller.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map, directory-default layer_rules entry; confidence = MEDIUM; source_sha256 = `01039AC8201C7207F6319CFA718E7E025FC72F7119C48F7EF183361C538FDE73`; references = `core/controller/__init__.py`, `packaging/atlas_architecture_map.json#layer_rules[core/controller/*]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 57. `MOD-CORE.CONTROLLER.ATLAS_CONTROLLER`

| field | value |
| --- | --- |
| file_path | core/controller/atlas_controller.py |
| package | core.controller |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS CONTROLLER v2.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `AtlasController`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `0E5AC6269FE595F06F3A5412A0132FEFEE0EB126F7B169A08C7D62450EE1290B`; references = `core/controller/atlas_controller.py`, `core/controller/atlas_controller.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 58. `MOD-CORE.DECISION`

| field | value |
| --- | --- |
| file_path | core/decision.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `Decision`, `DecisionAction`, `RiskLevel`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `073671B892CFD9E1E1CD20F92688083D6BF9B9C053EF3E0B69C56143D44A9665`; references = `core/decision.py`, `packaging/atlas_architecture_map.json#layer_rules[core/decision.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | DECISION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 59. `MOD-CORE.DECISION_ADAPTER`

| field | value |
| --- | --- |
| file_path | core/decision_adapter.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L3 application example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_security/__init__.py`, `core/execution_models.py`

**Public interfaces:** `DecisionAdapter`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `BFFB408A2DD128DAFE9C780106B7D952FC11D9E6304E2BEC39EF2B4C0C6AA42A`; references = `core/decision_adapter.py`, `packaging/atlas_architecture_map.json#layer_rules[core/decision_adapter.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | DECISION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 60. `MOD-CORE.DECISION_INTELLIGENCE`

| field | value |
| --- | --- |
| file_path | core/decision_intelligence.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `Action`, `CanonicalDecision`, `Evidence`, `EvidenceStatus`, `FreshnessPolicy`, `FusionPolicy`, `FusionResult`, `ModelProvider`, `ModelRequest`, `ModelResponse`, `ModelStatus`, `OfflineLearningBoundary`, `SignalFusion`, `Strategy`, `StrategyDescriptor`, `StrategyRegistry`, `model_response_to_evidence`, `record_canonical_decision`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `2D3E13C395A1A4A3C1BD3AAF0B303E343C32AE5D15CB334C494C994A39938979`; references = `core/decision_intelligence.py`, `packaging/atlas_architecture_map.json#layer_rules[core/decision_intelligence.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | AI | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 61. `MOD-CORE.DURABLE_APPEND_LOG`

| field | value |
| --- | --- |
| file_path | core/durable_append_log.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | durable append-only storage primitive, matches L2 example bucket |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `DurableAppendLog`, `DurableAppendLogCorruptError`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `559BD547D4256A336ABC0877D0F2F1D450FB943039ED966BC37519C2C88AA708`; references = `core/durable_append_log.py`, `packaging/atlas_architecture_map.json#layer_rules[core/durable_append_log.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 272', 'open() @ line 332'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 272', 'open() @ line 332']; ast_parse_error = None

### 62. `MOD-CORE.EVENT_BUS`

| field | value |
| --- | --- |
| file_path | core/event_bus.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | event bus implementation, matches L2 example bucket |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `EventBus`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `158E742CAC3B7E24D50DDD7E96345FC744DAC64943FFFAB8D0CB049143EC4DAB`; references = `core/event_bus.py`, `packaging/atlas_architecture_map.json#layer_rules[core/event_bus.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EVENTS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** event_signal_hits=['EventBus symbol @ line 27', 'EventBus symbol @ line 57', 'EventBus symbol @ line 64']; ast_parse_error = None

### 63. `MOD-CORE.EXECUTION_IDEMPOTENCY_STORE`

| field | value |
| --- | --- |
| file_path | core/execution_idempotency_store.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | persistent store, matches L2 example bucket |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_security/__init__.py`, `core/durable_append_log.py`

**Public interfaces:** `ExecutionIdempotencyStore`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `17286C0810F07EE0342A29842EAE911FC2FC218AC15A244C042416775D4111D5`; references = `core/execution_idempotency_store.py`, `packaging/atlas_architecture_map.json#layer_rules[core/execution_idempotency_store.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EXECUTION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 64. `MOD-CORE.EXECUTION_MANAGER`

| field | value |
| --- | --- |
| file_path | core/execution_manager.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L3 application example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_security/__init__.py`, `core/audit_event_store.py`, `core/capital_reservation.py`, `core/execution_idempotency_store.py`, `core/execution_models.py`, `core/execution_portfolio_foundation.py`, `core/execution_transaction_journal.py`, `core/fee_accounting.py`, `core/instrument_rules.py`, `core/risk_engine.py`, `core/venue_rule_freshness.py`, `data_layer/runtime_safety.py`

**Public interfaces:** `ExecutionManager`, `ExecutionResetRefusedError`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `9D295F0A139EC5389708D80BA8CC5E11553CD5E6E5A16BC7E919CF611990907D`; references = `core/execution_manager.py`, `packaging/atlas_architecture_map.json#layer_rules[core/execution_manager.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EXECUTION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | EXTERNAL | Mechanical regex evidence of persistence/external-I/O call sites: ['requests. @ line 132', 'requests. @ line 644'] |

**Mechanical evidence:** event_signal_hits=['.publish( @ line 635', '.publish( @ line 660', '.publish( @ line 1051', '.publish( @ line 1387', '.publish( @ line 1562', '.publish( @ line 1658', '.publish( @ line 1785', '.publish( @ line 1861', '.publish( @ line 1929', '.publish( @ line 2078', '.publish( @ line 3956', '.publish( @ line 4657', '.publish( @ line 4875', '.publish( @ line 4941', '.publish( @ line 5031', '.publish( @ line 5407', 'EventBus symbol @ line 5471', 'EventBus symbol @ line 5481']; external_interface_signal_hits=['requests. @ line 132', 'requests. @ line 644']; ast_parse_error = None

### 65. `MOD-CORE.EXECUTION_MODELS`

| field | value |
| --- | --- |
| file_path | core/execution_models.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `ExecutionRequest`, `ExecutionResult`, `normalize_action`, `normalize_mode`, `normalize_risk`, `normalize_symbol`, `normalize_timestamp`, `status_implies_success`, `utc_now_iso`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `155C76FD24CB7C9981647C4F95EC0939BD9C60CC4CC89EADEB35816E73E44C18`; references = `core/execution_models.py`, `packaging/atlas_architecture_map.json#layer_rules[core/execution_models.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EXECUTION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 66. `MOD-CORE.EXECUTION_PORTFOLIO_FOUNDATION`

| field | value |
| --- | --- |
| file_path | core/execution_portfolio_foundation.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | canonical financial-state/portfolio-foundation domain authority, grouped with risk_engine.py and capital_reservation.py as the M-1 canonical risk services (deliberately unwired in Package 2A) |
| intended_responsibility | Canonical financial-state/portfolio-foundation domain authority; M-1 canonical risk service grouped with core/risk_engine.py and core/capital_reservation.py (deliberately unwired in Package 2A). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `core/execution_models.py`

**Public interfaces:** `AppliedExecutionArchiveConflictError`, `AppliedExecutionArchiveCorruptError`, `AppliedExecutionArchiveError`, `AppliedExecutionArchiveStore`, `AppliedExecutionIndex`, `AppliedExecutionRecord`, `ClosedPositionArchiveConflictError`, `ClosedPositionArchiveCorruptError`, `ClosedPositionArchiveError`, `ClosedPositionArchiveStore`, `ClosedPositionIndex`, `ExecutionPortfolioFoundation`, `FinancialStateMigrationRequiredError`, `FinancialStateStore`, `LongPosition`, `mint_long_position_id`, `validate_closed_position_record`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `43731E948E20DED9B7DFF765CA0808C58C46D68DDDF284BD2D7FD87E0E0DBBAD`; references = `core/execution_portfolio_foundation.py`, `packaging/atlas_architecture_map.json#layer_rules[core/execution_portfolio_foundation.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EXECUTION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 174', 'open() @ line 248', 'open() @ line 275', 'open() @ line 412', 'open() @ line 426'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 174', 'open() @ line 248', 'open() @ line 275', 'open() @ line 412', 'open() @ line 426']; ast_parse_error = None

### 67. `MOD-CORE.EXECUTION_TRANSACTION_JOURNAL`

| field | value |
| --- | --- |
| file_path | core/execution_transaction_journal.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | journal, matches L2 example bucket |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_security/__init__.py`, `core/durable_append_log.py`

**Public interfaces:** `CommitOutcome`, `ExecutionTransactionJournal`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `D02623EB04DB0172464B0BA72DD926232982957E27EF0601DEEDE926B71984AF`; references = `core/execution_transaction_journal.py`, `packaging/atlas_architecture_map.json#layer_rules[core/execution_transaction_journal.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | EXECUTION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 68. `MOD-CORE.FEE_ACCOUNTING`

| field | value |
| --- | --- |
| file_path | core/fee_accounting.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | pure fee-currency classification: FeeNormalizer is a stateless static-method classifier with no I/O, no orchestration, no stores, and no ledger ownership, depending only on stdlib and the L1 core/instrument_rules.py contract it classifies fees against; sibling of core/instrument_rules.py and core/position_sizing.py, not application orchestration, so it is exempt from the generic core/* -> L3 default (Block 5E) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `core/instrument_rules.py`

**Public interfaces:** `FeeNormalizer`, `FeeRejected`, `FeeRejectionReason`, `NormalizedFee`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `1D853CEAF3C2B12CE674A019D10742B02DA597CDCFA4942F7D08B1893A5DD777`; references = `core/fee_accounting.py`, `packaging/atlas_architecture_map.json#layer_rules[core/fee_accounting.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | SETTLEMENT | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 69. `MOD-CORE.INSTRUMENT_RULES`

| field | value |
| --- | --- |
| file_path | core/instrument_rules.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | pure venue instrument-precision domain contract: immutable InstrumentRules/InstrumentRuleset value objects plus stdlib-only floor_to_step/is_aligned_to_step helpers, no I/O beyond the checked-in-config loader function which the L3 composition root alone calls; sibling of core/risk_engine.py and core/position_sizing.py, not application orchestration, so it is exempt from the generic core/* -> L3 default (Block 5D) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `InstrumentRules`, `InstrumentRulesConfigError`, `InstrumentRuleset`, `floor_to_step`, `is_aligned_to_step`, `load_instrument_ruleset`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `16A5925D41717A67E37CEB27A135A5A40289C27FBFE53F206F265F54ED7907DA`; references = `core/instrument_rules.py`, `packaging/atlas_architecture_map.json#layer_rules[core/instrument_rules.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 70. `MOD-CORE.LIFECYCLE`

| field | value |
| --- | --- |
| file_path | core/lifecycle.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | infrastructure lifecycle manager (application.py Infrastructure bucket) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `LifecycleManager`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `6B946412656E98CF6A1EC29ED36A00E6BDDFB9554F26030429418595BC43DF3A`; references = `core/lifecycle.py`, `packaging/atlas_architecture_map.json#layer_rules[core/lifecycle.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OPERATIONS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 71. `MOD-CORE.LOCAL_CAPABILITY_ADAPTER`

| field | value |
| --- | --- |
| file_path | core/local_capability_adapter.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | concrete implementations of the L1 capability contracts (deny-by-default policy gate, local probe tool adapter); L2 keeps the L4->L2 forbidden edge as the structural guarantee that intelligence cannot import an adapter and bypass the gateway |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `core/model_provider_contracts.py`, `core/operational_contracts.py`, `core/tool_gateway_contracts.py`

**Public interfaces:** `LocalCapabilityProbeAdapter`, `UnconfiguredPolicyGate`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `DF59B246C18CA1FD03E53F73ADF0EA3CDC73439B573EC2C7406942C70A2EE1BF`; references = `core/local_capability_adapter.py`, `packaging/atlas_architecture_map.json#layer_rules[core/local_capability_adapter.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 72. `MOD-CORE.LOGGER`

| field | value |
| --- | --- |
| file_path | core/logger.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | infrastructure logging adapter |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `AtlasLogger`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `303FDC603A368D6044214D5E96A623C4DED80469BE19B3125868E32A7F7FA1CB`; references = `core/logger.py`, `packaging/atlas_architecture_map.json#layer_rules[core/logger.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 73. `MOD-CORE.MARKET_LOOP`

| field | value |
| --- | --- |
| file_path | core/market_loop.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L3 application example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `analysis/world_analysis_engine.py`, `atlas_security/__init__.py`, `core/candle_processor.py`, `core/decision_adapter.py`, `core/execution_models.py`, `core/position_sizing.py`, `core/technical_analyzer.py`

**Public interfaces:** `MarketLoop`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `BE8F842B185A432F32A3B7CE75421C2EA51E23CCC72C84D67333DE01E17818DB`; references = `core/market_loop.py`, `packaging/atlas_architecture_map.json#layer_rules[core/market_loop.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** event_signal_hits=['.publish( @ line 631', '.publish( @ line 678']; ast_parse_error = None

### 74. `MOD-CORE.MODEL_PROVIDER_CONTRACTS`

| field | value |
| --- | --- |
| file_path | core/model_provider_contracts.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | provider-neutral model invocation vocabulary; no SDK, client, or credential (Block 3 capability seam) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_security/__init__.py`, `core/operational_contracts.py`

**Public interfaces:** `CapabilityClass`, `CostMetadata`, `InvocationOutcome`, `ModelCapability`, `ModelInvocation`, `ModelInvocationResult`, `ModelProviderAdapter`, `ModelProviderDescriptor`, `machine_digest`, `machine_identifier`, `sanitized_identifier`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `0B61B52828BCB401F30E513D2DE59B05D1CA6F040AB0C8CD66F4BD863B03FE0C`; references = `core/model_provider_contracts.py`, `packaging/atlas_architecture_map.json#layer_rules[core/model_provider_contracts.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 75. `MOD-CORE.OPERATIONAL_CONTRACTS`

| field | value |
| --- | --- |
| file_path | core/operational_contracts.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | operation/policy vocabulary; data contracts only, no I/O (Block 3 capability seam) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_security/__init__.py`

**Public interfaces:** `OperationContext`, `OperationResult`, `PolicyDecision`, `PolicyGate`, `sanitized_metadata`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `E266DBEAD0FA34631394227F680DAC0E2CA4A784589289D0C5808F7605CCE15F`; references = `core/operational_contracts.py`, `packaging/atlas_architecture_map.json#layer_rules[core/operational_contracts.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 76. `MOD-CORE.PAPER_TRADER`

| field | value |
| --- | --- |
| file_path | core/paper_trader.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | execution-orchestration collaborator alongside PositionController/CapitalManager (application.py Portfolio bucket) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `PaperTrader`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `4425E539985C630269E98EC49E25EC87127A48CA08517D3F138794E4B78FB9EB`; references = `core/paper_trader.py`, `packaging/atlas_architecture_map.json#layer_rules[core/paper_trader.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 509', 'json.load @ line 518', 'open() @ line 565', 'json.dump @ line 574'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 509', 'json.load @ line 518', 'open() @ line 565', 'json.dump @ line 574']; ast_parse_error = None

### 77. `MOD-CORE.POSITION_CONTROLLER`

| field | value |
| --- | --- |
| file_path | core/position_controller.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L3 application example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `Position`, `PositionController`, `PositionSide`, `PositionStatus`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `75C7E3B812DD6DC0F3C1E010EE67BAC5AFE4FF126086D2198B8A1B9E233F926A`; references = `core/position_controller.py`, `packaging/atlas_architecture_map.json#layer_rules[core/position_controller.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | POSITION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 157', 'open() @ line 202', 'open() @ line 399'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 157', 'open() @ line 202', 'open() @ line 399']; event_signal_hits=['EventBus symbol @ line 36']; ast_parse_error = None

### 78. `MOD-CORE.POSITION_SIZING`

| field | value |
| --- | --- |
| file_path | core/position_sizing.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | pure deterministic BUY sizing policy calculator: no I/O, no orchestration, no stores, no ledger ownership, stdlib + L1 dependencies only (core.risk_engine); sibling of core/risk_engine.py, not application orchestration, so it is exempt from the generic core/* -> L3 default (Block 5C M3) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `core/risk_engine.py`

**Public interfaces:** `PositionSizingService`, `SizingInputs`, `SizingProposal`, `SizingStatus`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `3096EEFA2D80DD58841F6F8D39C0435AF00428D75E94F018E067F229C6EF525B`; references = `core/position_sizing.py`, `packaging/atlas_architecture_map.json#layer_rules[core/position_sizing.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | POSITION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 79. `MOD-CORE.RISK_ENGINE`

| field | value |
| --- | --- |
| file_path | core/risk_engine.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example; canonical execution/admission RiskEngine authority |
| intended_responsibility | Canonical execution/admission RiskEngine authority (M-1 canonical risk service). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** none recorded

**Public interfaces:** `BucketPolicy`, `BuyCapacityLimits`, `DrawdownLevel`, `PositionExposure`, `RiskBucket`, `RiskDecision`, `RiskDecisionStatus`, `RiskEngine`, `RiskPolicy`, `RiskRequest`, `RiskState`, `analytical_risk_level`, `decimal_value`, `derive_buy_capacity_limits`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `DF39F858226CE46F0DE2BCA627B2463232832635322946F95A33106936518D01`; references = `core/risk_engine.py`, `packaging/atlas_architecture_map.json#layer_rules[core/risk_engine.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | RISK | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 80. `MOD-CORE.RISK_STATE_STORE`

| field | value |
| --- | --- |
| file_path | core/risk_state_store.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | Durable Phase-3 accounting state restoration boundary. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `JsonRiskStateStore`, `RestoredRiskState`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `D6332C1CA5C383F31D7FBD6004124C32034AEEF0AC2D458AC8C8B0DDED09C5D8`; references = `core/risk_state_store.py`, `core/risk_state_store.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | RISK | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 97', 'json.dump @ line 98'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 97', 'json.dump @ line 98']; ast_parse_error = None

### 81. `MOD-CORE.RUNTIME`

| field | value |
| --- | --- |
| file_path | core/runtime.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L3 application example (composition root chain, main.py -> core/application.py -> core/runtime.py) |
| intended_responsibility | AtlasRuntime: third link of the canonical composition chain main.py -> core/application.py -> core/runtime.py. |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** none recorded

**Public interfaces:** `AtlasRuntime`, `RuntimeInfo`, `RuntimeState`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `1D43E8B874C242CAB1E231E20DCFD4FB9E2429109A9FC5D86F427ABFBBE2161D`; references = `core/runtime.py`, `docs/adr/0001-canonical-composition-root.md#Decision`, `packaging/atlas_architecture_map.json#layer_rules[core/runtime.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | RUNTIME | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 82. `MOD-CORE.SCHEDULER`

| field | value |
| --- | --- |
| file_path | core/scheduler.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | infrastructure scheduler (application.py Infrastructure bucket) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `ScheduledTask`, `Scheduler`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `214A52949C14DBC5267DD7E310A1BB4546E5A10763FB4CE7FD8530CB50D59BBE`; references = `core/scheduler.py`, `packaging/atlas_architecture_map.json#layer_rules[core/scheduler.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OPERATIONS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 83. `MOD-CORE.SERVICE_CONTAINER`

| field | value |
| --- | --- |
| file_path | core/service_container.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | infrastructure dependency container (application.py Infrastructure bucket) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `ServiceContainer`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `60FCA6044010B3635FAE0B8581F0638CB9369B7F140F1CD32B10FB4904685637`; references = `core/service_container.py`, `packaging/atlas_architecture_map.json#layer_rules[core/service_container.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OPERATIONS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 84. `MOD-CORE.TECHNICAL_ANALYZER`

| field | value |
| --- | --- |
| file_path | core/technical_analyzer.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | market analysis orchestration consumed by brain/market_loop, not a pure domain contract |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `TechnicalAnalyzer`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `D69DCED35ECE3F7954A918A99F230EB03B07EACE92B08D73B53A27603BE174EE`; references = `core/technical_analyzer.py`, `packaging/atlas_architecture_map.json#layer_rules[core/technical_analyzer.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | TECHNICAL_ANALYSIS | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 85. `MOD-CORE.TOOL_GATEWAY_CONTRACTS`

| field | value |
| --- | --- |
| file_path | core/tool_gateway_contracts.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | tool invocation vocabulary and the CapabilityGateway policy chokepoint; contracts only, concrete adapters live at L2 (Block 3 capability seam) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `core/model_provider_contracts.py`, `core/operational_contracts.py`

**Public interfaces:** `CapabilityGateway`, `GatewayReason`, `SideEffectClass`, `ToolAdapter`, `ToolDescriptor`, `ToolInvocation`, `ToolInvocationResult`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `7893C98B9B9D51B53CDA945CC97A9D854162E518D7CEAF0BD8DB7EB0C6AFE6E2`; references = `core/tool_gateway_contracts.py`, `packaging/atlas_architecture_map.json#layer_rules[core/tool_gateway_contracts.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 86. `MOD-CORE.VENUE_RULE_FRESHNESS`

| field | value |
| --- | --- |
| file_path | core/venue_rule_freshness.py |
| package | core |
| source_scope | UNKNOWN |
| current_responsibility | Block 6A — venue instrument-rule freshness and staleness safety. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `core/instrument_rules.py`

**Public interfaces:** `VenueRuleFreshnessPolicy`, `VenueRuleFreshnessPolicyError`, `VenueRuleFreshnessReport`, `VenueRuleFreshnessService`, `VenueRuleFreshnessStatus`, `VenueRuleGateDecision`, `utc_now`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `99B8B2CE7AD0213298672CB50B4686F9DBCE9D9DC47EB3406F729134380DF09F`; references = `core/venue_rule_freshness.py`, `core/venue_rule_freshness.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 87. `MOD-DATA_LAYER._INIT_`

| field | value |
| --- | --- |
| file_path | data_layer/__init__.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | Backend-independent Atlas relational persistence foundation. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `data_layer/config.py`, `data_layer/models.py`, `data_layer/sqlite.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `A72CC347D9CC5C36F775D79C3051A619E8D5ED4D8A928EDD1169A60A5A61DA63`; references = `data_layer/__init__.py`, `data_layer/__init__.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 88. `MOD-DATA_LAYER.CANONICAL_EVIDENCE`

| field | value |
| --- | --- |
| file_path | data_layer/canonical_evidence.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | domain evidence contract, sibling of data_layer/contracts.py and data_layer/models.py |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `data_layer/contracts.py`, `data_layer/projection_replay.py`

**Public interfaces:** `CanonicalExecutionEvidenceAdapter`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `0101F48D866F8A7BB74F331E07DDF796301C83BE09D817348E99C22FA29935F6`; references = `data_layer/canonical_evidence.py`, `packaging/atlas_architecture_map.json#layer_rules[data_layer/canonical_evidence.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 89. `MOD-DATA_LAYER.CONFIG`

| field | value |
| --- | --- |
| file_path | data_layer/config.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | explicit: data-layer configuration is L2 infrastructure |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `data_layer/contracts.py`, `data_layer/sqlite.py`

**Public interfaces:** `StorageConfiguration`, `create_storage`, `load_storage_configuration`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `69DF2971A29DFBE460A490486A3C7CD19E4CDE0D8243B6C5C74EC8B2176E3F60`; references = `data_layer/config.py`, `packaging/atlas_architecture_map.json#layer_rules[data_layer/config.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | CONFIGURATION | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['sqlite3 file reference @ line 55'] |

**Mechanical evidence:** persistence_signal_hits=['sqlite3 file reference @ line 55']; ast_parse_error = None

### 90. `MOD-DATA_LAYER.CONTRACTS`

| field | value |
| --- | --- |
| file_path | data_layer/contracts.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `ConcurrencyConflict`, `ExecutionRepository`, `IntegrityViolation`, `MigrationError`, `OrderRepository`, `PositionRepository`, `RecordConflict`, `StorageBackend`, `StorageConfigurationError`, `StorageError`, `TransactionStateError`, `UnitOfWork`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `9DC1A26DB0741EAA20F5D6C5D63014BE198F8A2A8349FF779DA572C30519B946`; references = `data_layer/contracts.py`, `packaging/atlas_architecture_map.json#layer_rules[data_layer/contracts.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 92'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 92']; ast_parse_error = None

### 91. `MOD-DATA_LAYER.MIGRATIONS`

| field | value |
| --- | --- |
| file_path | data_layer/migrations.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | explicit: data-layer migrations are L2 infrastructure |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `data_layer/contracts.py`

**Public interfaces:** `Migration`, `apply_migrations`, `validate_migrations`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `1E0A136B516870D17EC76364DE4EBDD7F7A2EF74770CAB6C8023EE3355B71AF9`; references = `data_layer/migrations.py`, `packaging/atlas_architecture_map.json#layer_rules[data_layer/migrations.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 92. `MOD-DATA_LAYER.MODELS`

| field | value |
| --- | --- |
| file_path | data_layer/models.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L1 domain contract example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `data_layer/contracts.py`

**Public interfaces:** `ExecutionRecord`, `OrderRecord`, `PositionRecord`, `decimal_text`, `metadata_text`, `normalize_symbol`, `parse_metadata`, `utc_text`, `validate_id`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `C55E97B25FE5C8DC740260EEBEA45B7CABDAF0EF7E1F5B965BA093E2DC498215`; references = `data_layer/models.py`, `packaging/atlas_architecture_map.json#layer_rules[data_layer/models.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 93. `MOD-DATA_LAYER.PROJECTION_REPLAY`

| field | value |
| --- | --- |
| file_path | data_layer/projection_replay.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | Idempotent relational projection from confirmed authoritative evidence. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `data_layer/contracts.py`, `data_layer/models.py`

**Public interfaces:** `ConfirmedExecutionEvidence`, `ReplayResult`, `replay_confirmed_execution`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `77E3B944E198375D9E546AB97A2E2459E9E514F73252D714E21E1AA6B4894B23`; references = `data_layer/projection_replay.py`, `data_layer/projection_replay.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 94. `MOD-DATA_LAYER.RECOVERY`

| field | value |
| --- | --- |
| file_path | data_layer/recovery.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | Fail-closed Phase-2 recovery assessment and startup admission gate. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `RecoveryDecision`, `RecoveryDisposition`, `RecoveryEvidence`, `assess_recovery`, `startup_ready`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `FCBDBF3FC279635F2693CE63E79B385A1B6AE2BD9D212D8AF694A570A5DBE7FD`; references = `data_layer/recovery.py`, `data_layer/recovery.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 95. `MOD-DATA_LAYER.RUNTIME_SAFETY`

| field | value |
| --- | --- |
| file_path | data_layer/runtime_safety.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | Canonical financial-runtime recovery orchestration. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `data_layer/canonical_evidence.py`, `data_layer/contracts.py`, `data_layer/projection_replay.py`, `data_layer/recovery.py`

**Public interfaces:** `FinancialReadiness`, `FinancialRuntimeSafetyService`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `5F087DF645A6F0DA9B4226F754A96C95F31FD2D6DEE24B7403B820F7ECCC178E`; references = `data_layer/runtime_safety.py`, `data_layer/runtime_safety.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 96. `MOD-DATA_LAYER.SEMANTIC_CONTRACTS`

| field | value |
| --- | --- |
| file_path | data_layer/semantic_contracts.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | domain contract vocabulary, sibling of data_layer/contracts.py |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `data_layer/models.py`

**Public interfaces:** `OrderState`, `PersistenceBoundary`, `PositionPersistenceDTO`, `RecoveryAction`, `startup_recovery_action`, `validate_order_transition`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `1FC03ED9B75548B98C8D457ED005A41639187D083C77F80127ED486A1BEBADAE`; references = `data_layer/semantic_contracts.py`, `packaging/atlas_architecture_map.json#layer_rules[data_layer/semantic_contracts.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | UNKNOWN | None | No directory/keyword signal matched a canonical_domain_ids heuristic; no proposal made. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 97. `MOD-DATA_LAYER.SQLITE`

| field | value |
| --- | --- |
| file_path | data_layer/sqlite.py |
| package | data_layer |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L2 infrastructure example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `data_layer/contracts.py`, `data_layer/migrations.py`, `data_layer/models.py`, `data_layer/semantic_contracts.py`

**Public interfaces:** `SQLiteExecutionRepository`, `SQLiteOrderRepository`, `SQLitePositionRepository`, `SQLiteStorage`, `SQLiteUnitOfWork`, `_GuardedConnection`, `_UnitOfWorkState`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `C8A15CFBB58C597EF4CDA388A855F6A84B25C90753D8D0DE6C01E5CA12E62BEB`; references = `data_layer/sqlite.py`, `packaging/atlas_architecture_map.json#layer_rules[data_layer/sqlite.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | LEDGER | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['sqlite3.connect @ line 361', 'open() @ line 370'] |

**Mechanical evidence:** persistence_signal_hits=['sqlite3.connect @ line 361', 'open() @ line 370']; ast_parse_error = None

### 98. `MOD-EXCHANGE._INIT_`

| field | value |
| --- | --- |
| file_path | exchange/__init__.py |
| package | exchange |
| source_scope | UNKNOWN |
| current_responsibility | explicit: exchange/** is L2 infrastructure |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map, directory-default layer_rules entry; confidence = MEDIUM; source_sha256 = `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`; references = `exchange/__init__.py`, `packaging/atlas_architecture_map.json#layer_rules[exchange/*]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | MARKET_DATA | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 99. `MOD-EXCHANGE.MARKET_FEED`

| field | value |
| --- | --- |
| file_path | exchange/market_feed.py |
| package | exchange |
| source_scope | UNKNOWN |
| current_responsibility | ATLAS MARKET FEED COMPATIBILITY ADAPTER v2.0.0 |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `atlas_finance/market_data/binance_public_provider.py`, `atlas_finance/market_data/contracts.py`, `atlas_finance/market_data/exceptions.py`, `atlas_finance/market_data/market_feed_service.py`, `atlas_finance/market_data/models.py`, `atlas_finance/market_data/temporal.py`

**Public interfaces:** `MarketFeed`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `BE79BB558F278DB3F9D463F70A5D25FA5B631DA6F9372EC27911B805FC200366`; references = `exchange/market_feed.py`, `exchange/market_feed.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | MARKET_DATA | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 100. `MOD-MAIN`

| field | value |
| --- | --- |
| file_path | main.py |
| package | UNKNOWN |
| source_scope | UNKNOWN |
| current_responsibility | process entry point that constructs and starts the L3 composition root; treated as part of the application layer |
| intended_responsibility | Process entry point that constructs AtlasApplication exactly once and starts the canonical composition root (main.py -> core/application.py -> core/runtime.py). |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | CANONICAL |

**Dependencies:** `core/application.py`

**Public interfaces:** `AtlasProcess`, `configure_logging`, `display_startup_status`, `main`, `safe_dict`, `safe_value`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `52476E0F787546060721A9C7BBDB90264D891BD7D5899CFEA3B78A19769D1482`; references = `docs/adr/0001-canonical-composition-root.md#Decision`, `docs/adr/0001-canonical-composition-root.md#Evidence`, `main.py`, `packaging/atlas_architecture_map.json#composition_root`, `packaging/atlas_architecture_map.json#layer_rules[main.py]`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | APP | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | RATIFIED_BY_EXISTING_RECORD | None | Ratified by an existing accepted ADR or the git-tracked architecture-boundary map; transcribed, not newly classified. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 101. `MOD-OBSERVABILITY._INIT_`

| field | value |
| --- | --- |
| file_path | observability/__init__.py |
| package | observability |
| source_scope | UNKNOWN |
| current_responsibility | Read-only observability sources for the lightweight Atlas panel. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `1A632B2E9BF05694EDF653A72CCFAF4EB0E716D8595972C1E6CCF9B68F265863`; references = `observability/__init__.py`, `observability/__init__.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OBSERVABILITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 102. `MOD-OBSERVABILITY.PANEL_ROUTER`

| field | value |
| --- | --- |
| file_path | observability/panel_router.py |
| package | observability |
| source_scope | UNKNOWN |
| current_responsibility | Thin read-only FastAPI router for the lightweight observability panel. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `observability/__init__.py`, `observability/panel_sources.py`

**Public interfaces:** `build_observability_router`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `66FF35118F1BAAF3015BC2085252A5A712963D017F5B6E8F0A30809E88E8CAF4`; references = `observability/panel_router.py`, `observability/panel_router.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OBSERVABILITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | EXTERNAL | Mechanical regex evidence of persistence/external-I/O call sites: ['APIRouter( @ line 89'] |

**Mechanical evidence:** external_interface_signal_hits=['APIRouter( @ line 89']; ast_parse_error = None

### 103. `MOD-OBSERVABILITY.PANEL_SOURCES`

| field | value |
| --- | --- |
| file_path | observability/panel_sources.py |
| package | observability |
| source_scope | UNKNOWN |
| current_responsibility | Pure readers behind the lightweight observability panel. |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `read_governance_panel`, `read_head_commit`, `read_observability_panels`, `read_test_results_panel`, `resolve_current_registry`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = AST-extracted module docstring (decorative banner/separator lines skipped); confidence = HIGH; source_sha256 = `0BDC0E74B2241EE4F07A6A937528015C7C13376B5E8CCAA7F0D1CE3CA2ADEE83`; references = `observability/panel_sources.py`, `observability/panel_sources.py (module docstring, first substantive line)`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | OBSERVABILITY | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | UNKNOWN | None | No persistence or external-interface call-site pattern matched. |

**Mechanical evidence:** no signal hits; ast_parse_error = None

### 104. `MOD-PORTFOLIO.CAPITAL_MANAGER`

| field | value |
| --- | --- |
| file_path | portfolio/capital_manager.py |
| package | portfolio |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L3 application example (lifecycle/scheduler/controller orchestration bucket) |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** none recorded

**Public interfaces:** `CapitalManager`

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `3B4B723B327B1FACF993396FBBD2E16E68D8406C1844CA3B7A3DDD88CED64CC6`; references = `packaging/atlas_architecture_map.json#layer_rules[portfolio/capital_manager.py]`, `portfolio/capital_manager.py`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | CAPITAL | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | OWNER_DECISION_REQUIRED | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. Flagged for priority Owner assignment because this module falls under the risk/execution/capital/security/persistence criticality heuristic. |
| lifecycle | OWNER_DECISION_REQUIRED | None | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | OWNER_DECISION_REQUIRED | P0_OR_P1_CANDIDATE | Path matches the risk/execution/capital/security/persistence criticality heuristic used only to prioritize Owner review; not a criticality assignment. |
| state_ownership | OWNER_DECISION_REQUIRED | DURABLE | Mechanical regex evidence of persistence/external-I/O call sites: ['open() @ line 797', 'json.dump @ line 808', 'open() @ line 846', 'json.load @ line 857'] |

**Mechanical evidence:** persistence_signal_hits=['open() @ line 797', 'json.dump @ line 808', 'open() @ line 846', 'json.load @ line 857']; ast_parse_error = None

### 105. `MOD-WEB_APP`

| field | value |
| --- | --- |
| file_path | web_app.py |
| package | UNKNOWN |
| source_scope | UNKNOWN |
| current_responsibility | explicit: L5 presentation example |
| intended_responsibility | UNKNOWN |
| domain | UNKNOWN |
| owner | UNASSIGNED |
| state_ownership | UNKNOWN |
| criticality | UNKNOWN |
| lifecycle | UNKNOWN |

**Dependencies:** `observability/panel_router.py`

**Public interfaces:** none recorded

**Events produced:** none recorded

**Events consumed:** none recorded

**Persistence:** none recorded

**Risk:** none recorded

**Evidence:** method = git-tracked architecture-boundary map (packaging/atlas_architecture_map.json), exact-path layer_rules entry; confidence = VALIDATED; source_sha256 = `105806FA49BCA588C19B02D545F442EAE228E6D93F069A4DDF4216BE90FD0414`; references = `packaging/atlas_architecture_map.json#layer_rules[web_app.py]`, `web_app.py`

**Classification disposition:**

| field | disposition | proposed_value | basis |
| --- | --- | --- | --- |
| source_scope | OWNER_DECISION_REQUIRED | ACTIVE_CANDIDATE | Member of packaging/atlas_runtime_closure.json (105-module static runtime closure, reachable from entry points main.py/web_app.py via AST import resolution, machine-checked by tools/build_architecture_inventory.py check). |
| domain | OWNER_DECISION_REQUIRED | WEB | Non-authoritative path/keyword heuristic against milestones.REM-001.canonical_domain_ids; no existing record maps this file to a canonical REM domain ID. |
| owner | UNKNOWN | None | No organizational owner/department is evidenced anywhere in the repository for any module; Atlas is a single-operator project with no department structure on record. |
| lifecycle | UNKNOWN | CANDIDATE | Member of the runtime closure with no ADR/registry lifecycle designation on record. |
| criticality | UNKNOWN | None | No signal proposing elevated criticality. |
| state_ownership | OWNER_DECISION_REQUIRED | EXTERNAL | Mechanical regex evidence of persistence/external-I/O call sites: ['FastAPI( @ line 150'] |

**Mechanical evidence:** external_interface_signal_hits=['FastAPI( @ line 150']; ast_parse_error = invalid non-printable character U+FEFF (<unknown>, line 1)

