# Atlas: audit-mode status report for MEGA TASKS 1–3 and the follow-up specifications (2026-09-30)

## Nature of this report

- **Who wrote it.** The implementing session wrote it in AUDIT MODE. It is not a third-party audit. The independent audit CLAUDE.md requires for CRITICAL work is still **UNKNOWN / pending**.
- **What it covers.** The owner sent about 20 specifications in one sitting:
  - MEGA 1–3;
  - Portfolio / Market / Execution;
  - Data Engineering;
  - Reliability;
  - Independent Final Audit;
  - Model Orchestration;
  - Simulation / Digital Twin;
  - Advanced Risk;
  - Strategy Factory;
  - Knowledge Graph;
  - Multi-venue;
  - News / NLP;
  - Treasury;
  - Disaster Recovery;
  - Deployment;
  - Compute / Cost;
  - Advanced 3D HQ;
  - Full Digital Trial;
  - the GitHub reference list.
- **What it is based on.** Only the repository, the runtime closure (`packaging/atlas_runtime_closure.json`) and the test suite.
- **Levels used.** CODE EXISTS ≠ TEST EXISTS ≠ INTEGRATION EXISTS ≠ RUNTIME EXISTS ≠ PRODUCTION READY. A file or class existing is not counted as implementation.
- **Git state.** Per the owner's instruction, the changes made in this session are **not committed and not staged**.

## 1. What this session changed (uncommitted)

| File | Change | Level reached |
|---|---|---|
| `tests/architecture/test_single_execution_authority.py` (new) | The legacy direct-execution modules (`core/execution_bridge.py`, `intelligence/trading/paper_bridge.py`, `portfolio/portfolio_manager.py`) must never enter the runtime closure. Only `core/execution_manager.py` may call PaperTrader mutators. | TEST + RUNTIME closure check |
| `observability/learning_view.py` | Adds, all derived from the closed-position archive:<br>• a TradeOutcome **fingerprint** (sha256 of the archive row; an edited outcome changes it);<br>• **post-trade analysis** (holding time, gross return, fee impact, "fees turned a win into a loss", hindsight worth-taking), with its unmeasured items listed explicitly;<br>• **book metrics**: expectancy, win rate, average win and loss, profit factor, per-trade Sharpe and Sortino, max drawdown, recovery factor, losing streak, INSUFFICIENT below 10 trades;<br>• the lesson lifecycle renamed to the spec's vocabulary (PROPOSED / VALIDATING / CONFIRMED (owner-signed) / CONTESTED / EXPIRED). | RUNTIME (read-only `/api/learning`), tested |
| `templates/governance.html` | Turkish labels for the new lifecycle. | UI |
| `tests/test_learning_view.py`, `tests/test_agent_cycle.py` | New tests; the lifecycle names were updated to the new vocabulary. Two expectations of mine were wrong and corrected with the reason written in the test: the streak is 3 because fees turn +1.5 into a loss, and the test position ids collided. | TEST |

**Test result after the changes:** `6061 passed, 2 failed, 12 skipped`. The two failures are the long-standing accepted ones:
- B2 `test_forbidden_layer_imports`
- D5 `test_rem001_state_authority_map`

## 2. Capability classification

### Architecture and authority

| Capability | Status | Evidence |
|---|---|---|
| Single composition root | IMPLEMENTED | `tests/architecture/test_composition_root_is_unique.py` passes |
| Single execution authority | IMPLEMENTED (runtime) | New test above. `ExecutionBridge` still exists as dead code outside the closure, so it is guarded, not deleted. |
| Single risk authority | IMPLEMENTED | `core/risk_engine.py`; `test_composition_root_wires_canonical_risk_services.py` |
| Intelligence cannot import execution | IMPLEMENTED | `test_intelligence_cannot_import_execution.py` |
| Live execution denied by default | IMPLEMENTED | `test_live_execution_is_denied_by_default.py`; `live_authority=DENIED` |
| Web / UI cannot mutate | IMPLEMENTED | `test_web_layer_is_read_only.py`; loopback-only guard tests |
| Distinct HOLD / ABSTAIN / REJECT / SYSTEM_FAILURE semantics end to end | PARTIALLY_IMPLEMENTED | SELL-without-position becomes HOLD and gate rejections carry reasons, but no single enum spanning the whole path was verified in this session |
| Full decision provenance (decision_id → evidence → votes → memory → risk → execution) | PARTIALLY_IMPLEMENTED | Audit events plus `metadata.memory_adjustment` plus `/decisions`. Evidence IDs and memory references are not linked per decision. |

### Trading, execution, financial integrity

| Capability | Status | Evidence / gap |
|---|---|---|
| Idempotent execution, journal, COMMIT_STATUS_UNKNOWN halt | IMPLEMENTED | `execution_idempotency.jsonl` (2697 records on the owner's machine); the journal's `journal_unresolved` flag at startup; KNOWN_LIMITATIONS lists the residual gaps |
| Crash recovery / reconciliation | PARTIALLY_IMPLEMENTED | `tools/reconcile_execution_authorities.py` and recovery tests exist. Open: RISK-ACCOUNTING-RECOVERY-REBOOK-GAP-001 (manual reconciliation in some cases) and EXEC-MGR-COMMIT-UNKNOWN-GAP-001. |
| Order lifecycle states | PARTIALLY_IMPLEMENTED | `PARTIALLY_FILLED` appears in `core/execution_models.py`, but the PAPER engine fills whole orders; ACKNOWLEDGED / EXPIRED / RECONCILING are not exercised |
| Realistic paper fills (spread, slippage, latency, partial fills) | NOT_IMPLEMENTED in runtime | Slippage and next-open fills exist only in `tools/backtest_replay.py` (research) |
| Immutable TradeOutcome | PARTIALLY_IMPLEMENTED | Archive plus fingerprint (this session). No stored outcome record with decision / order / execution IDs; MAE / MFE and slippage are not captured. |
| Multi-currency ledger, FX, funding, NAV ledger | NOT_IMPLEMENTED | Single-quote (USDT) PAPER book |
| Multi-venue registry / adapters / routing | NOT_IMPLEMENTED | Single venue (binance_global), with instrument rules and freshness for that venue only |

### Risk and portfolio

| Capability | Status | Evidence / gap |
|---|---|---|
| Buckets, confidence floors, 5 % daily loss (realized), drawdown ladder 5 / 10 / 15 % | IMPLEMENTED | `core/risk_engine.py` |
| Daily loss including unrealized | NOT_IMPLEMENTED | RISK-EQUITY-UNREALIZED-DRAWDOWN-GAP-001; waiting on the owner ("günlük zarar onay") |
| Measured correlation / portfolio risk | NOT_IMPLEMENTED | **Finding F-2** below: the world-model correlations are hard-coded constants |
| Liquidity / order book / microstructure | NOT_IMPLEMENTED | No order-book or spread source in the runtime |
| VaR / ES / scenario engine | NOT_IMPLEMENTED in runtime | Monte Carlo on the closed-trade P/L exists offline (`tools/reality_check.py`) |
| Strategy capital sleeves (S1) | NOT_IMPLEMENTED | Designed; waiting on the owner ("S1 onay") |

### Intelligence, memory, learning

| Capability | Status | Evidence / gap |
|---|---|---|
| Memory affects future decisions | IMPLEMENTED (narrow) | BRAIN-MEM-001: a losing coin book lowers BUY confidence by at most 5 points. Open: finding M-1 (NB-4-shaped) in `docs/audits/BRAIN-MEM-001_SELF_AUDIT_2026-09-30.md`. |
| Trade → Outcome → Analysis → Lesson → Memory | PARTIALLY_IMPLEMENTED | Derived in `learning_view`; `knowledge_manager` records status changes. **Lessons do not feed decisions** (by design, evidence only). |
| Lesson validation | PARTIALLY_IMPLEMENTED | Sample-size lifecycle; CONFIRMED only with the owner's signature; contradictions kept. No out-of-sample validation of lessons. |
| Regime-aware experience | PARTIALLY_IMPLEMENTED | `market_regime` agent plus look-ahead-free tagging; regime is offline, not in the decision path |
| Confidence calibration | PARTIALLY_IMPLEMENTED | Offline bands in `tools/reality_check.py`. There is no runtime calibrated-confidence layer (it would be CRITICAL). |
| Agent performance attribution | NOT_IMPLEMENTED | Votes are logged per decision but not joined to outcomes |
| Counterfactual analysis | NOT_IMPLEMENTED | — |
| Strategy registry / lifecycle / certification | NOT_IMPLEMENTED as a registry | `strategy_compare` + `strategy_agent` + governance proposals give the research → proposal path only |
| Walk-forward / leakage-safe splits | PARTIALLY_IMPLEMENTED | Replay windows in `strategy_compare`; no train / validation / test splitter with leakage tests |
| Knowledge graph | NOT_IMPLEMENTED | — |
| News / NLP | NOT_IMPLEMENTED | Only Fear & Greed sentiment |
| Model registry / routing / LLM output validation | NOT_IMPLEMENTED | There is deliberately no AI provider in the runtime (`test_runtime_has_no_ai_provider_dependency.py`); AI-001 is deferred |

### Data, reliability, operations

| Capability | Status | Evidence / gap |
|---|---|---|
| Stale-data rejection, future-candle rejection | IMPLEMENTED | Market loop (`future_candles_rejected`), per-coin staleness |
| Data source registry / versioned datasets / feature pipeline | NOT_IMPLEMENTED | — |
| Supervisor, heartbeat, hung-child detection | IMPLEMENTED | `tools/start_atlas` supervisor (heartbeat file, stale_after=30 s) |
| Health / readiness | IMPLEMENTED | `/api/liveness`, `/api/readiness`, `core/health_monitor.py` |
| Incident records | PARTIALLY_IMPLEMENTED | INCIDENTS memory type with the lifecycle fields; no automatic detection → incident |
| Backup / restore / DR test | NOT_IMPLEMENTED | No backup / restore tool in `tools/` |
| Environments / release gate / artifact hashing | PARTIALLY_IMPLEMENTED | PAPER vs LIVE config, vendored asset hashes, registry-driven release; no DEV / TEST / PROD-CANDIDATE separation |
| Cost / resource tracking | NOT_IMPLEMENTED | No LLM cost to track today |

### Governance, security, UI

| Capability | Status | Evidence |
|---|---|---|
| Proposal lifecycle with owner-only approval | IMPLEMENTED | Hash-chained `proposals.jsonl`; owner key never read by the web |
| Agents cannot approve or deploy | IMPLEMENTED | `NEVER_GRANTED_TO_AI` permissions |
| Security Guardian (static scan of running code) | PARTIALLY_IMPLEMENTED | `atlas_org/security_review.py`, `/api/security`; no runtime file-integrity watch, process or network monitoring |
| External content as untrusted | IMPLEMENTED (process) | Research is never AUTHORITATIVE (memory schema check); the external-code gate is documented |
| HQ shows only real state | IMPLEMENTED | `/api/agent-states` derived from logs; empty → "AKTİVİTE YOK"; CONNECTION LOST banner |
| Decision inspector | PARTIALLY_IMPLEMENTED | `/decisions` (signals + gates); no per-decision replay |
| Timeline / trade replay / 3D engine (R3F) | NOT_IMPLEMENTED | Canvas HQ only; R3F deferred |
| Full digital trial | NOT_IMPLEMENTED | Replay exists for the decision loop only, without failure injection, the learning loop or partial fills |

## 3. Critical findings

### F-1 MEDIUM: memory caution disappears when the archive is unreadable (NB-4-shaped)

- **Evidence:** `ai/core/intelligence/memory_adapter.py _trade_book` returns effect 0 on `ARCHIVE_UNREADABLE`.
- **Impact:** A losing coin's BUY confidence rises by up to 5 points when evidence is removed.
- **Root cause:** Failure is mapped to "no effect" instead of "last known evidence".
- **Fix:** Keep the last good evidence per coin, and fail-closed caution when there is none (CRITICAL; owner approval "M-1 onay").
- **Verify:** A test with a losing book, then an unreadable archive: confidence must not rise.

### F-2 MEDIUM: world-model correlations are constants, not measurements

- **Evidence:** `ai/core/atlas_world_model.py:140-142` hard-codes BTC–ETH 0.85, ETH–SOL 0.75, SPX–BTC 0.6.
- **Impact:** Any consumer treats invented numbers as evidence. This breaks the "never invent data" rule.
- **Root cause:** Seed data from an early version.
- **Fix:** Label them as HYPOTHESIS with source "static seed", or compute rolling correlation from closed candles.
- **Verify:** A test that no correlation value without a measured source reaches decision metadata.

### F-3 MEDIUM: daily loss ignores open positions

- **Evidence:** `risk_engine.py:645` uses `-state.realized_daily_pnl`.
- **Impact:** Several open losing positions do not trip the 5 % gate.
- **Fix:** Owner decision ("günlük zarar onay"); CRITICAL.
- **Verify:** A test with 5 open positions each −2 %: the gate must trip.

### F-4 MEDIUM: paper fills are idealised

- **Evidence:** No slippage, spread or partial-fill model in the runtime PAPER path; replay with realistic fills turns the reference result from +126.80 to +73.61 in window 1 (owner run, registry v5.75).
- **Impact:** PAPER P/L is optimistic, so the evidence behind every strategy decision is biased upward.
- **Fix:** A fill model in the PAPER engine (CRITICAL; execution path).
- **Verify:** Replay and runtime parity test on the same candles.

### F-5 LOW: legacy direct-execution code is still in the repository

- **Evidence:** `core/execution_bridge.py` calls `paper_trader.open_trade`.
- **Impact:** None at runtime; it is now guarded by a test.
- **Fix:** Archive the file after the owner decides (part of the ~45-file archive decision).

### F-6 LOW: no backup / restore of the financial state

- **Impact:** A disk loss loses the PAPER book and the journal.
- **Fix:** A backup tool with an integrity hash plus a restore drill test.
- **Verify:** Restore into a temporary directory and reconcile.

## 4. Final gate answer

**What Atlas really does (verified in the code and the runtime closure):** Atlas is a **single-venue, spot, PAPER-only, fail-closed trading loop** with:
- one composition root;
- one risk authority and one execution authority;
- durable idempotent execution with journalled recovery;
- a governed, hash-chained proposal and memory system;
- rule-based agents that write evidence and never act;
- a narrow, caution-only memory effect on decisions;
- a read-only operator UI and HQ that shows only recorded state.

**What is missing:**
- portfolio-level risk (correlation, liquidity, VaR);
- realistic paper execution;
- a strategy registry and certification;
- agent attribution and a runtime confidence calibration;
- counterfactuals;
- a data registry and versioning;
- backup and DR;
- multi-venue and multi-currency;
- LLM orchestration;
- a knowledge graph and news;
- a full digital trial and a 3D engine.

Several specifications also ask for things CLAUDE.md forbids doing without the owner's signature: changes to execution, risk and financial state. They are listed as findings, not implemented.

**Not production ready:** live authority is DENIED, and it should stay that way until F-1, F-3 and F-4 are closed and independently audited.

## 5. GitHub reference list from the owner (not re-verified this session unless noted)

| Repo | Decision class | Why |
|---|---|---|
| NautilusTrader | Reference (architecture) | Event-driven, same code path for backtest and live, order-state lifecycle. Directly relevant to F-4 and order states. LGPL-3.0: no code copying. |
| QuantConnect LEAN | Reference | Brokerage / transaction / fill models for F-4. Apache-2.0. |
| vectorbt | Defer | Apache-2.0 **with Commons Clause**: licence review required before any use. |
| Freqtrade | Reference only | GPL-3.0 (verified earlier); no code. |
| Backtrader | Reference | GPL-3.0; comparison only. |
| PyPortfolioOpt | Candidate (Phase 3) | MIT. Covariance, HRP and allocation for sleeves / portfolio risk. Would be a new dependency: the gate is required. |
| CCXT | Candidate (6C venue adapter) | MIT. Transport adapter only, below ExecutionManager, never an authority. |
| yfinance | Research only | Never a production truth source. |
| pgvector, LangGraph, PydanticAI, MS Agent Framework (FIDES) | Defer to AI-001 | There is no LLM runtime today. The FIDES untrusted-content labelling idea matches Atlas's rule that external text is data. |
| OpenTelemetry | Defer | Structured audit plus telemetry JSONL already exist; revisit once there are multiple processes. |
| DuckDB, Great Expectations | Defer (data phase) | Useful for the research data layer and candle validation rules; new dependencies. |

The licences marked "verified earlier" were checked in this conversation. The others come from the owner's text and memory: **UNKNOWN until each repository's LICENSE file is read**.
