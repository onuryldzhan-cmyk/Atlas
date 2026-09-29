# GitHub research registry (owner's "Atlas GitHub Arsenal", 2026-09-30)

**Status:** research inputs only. Nothing is a dependency.

**Gate for every entry:** License → Security → Dependencies → Maintenance → Architecture → Tests → Atlas compatibility → Evidence → Proposal → Owner approval → Adapt.

**Licences are UNKNOWN unless marked "verified"** (read from the repository page in this conversation). Stars and claims such as "production-grade" are not evidence of quality.

## First targets, tied to open audit findings (docs/audits/INDEPENDENT_STATUS_AUDIT_MEGA_TASKS_2026-09-30.md)

| Finding | Repos to study first | What to learn |
|---|---|---|
| F-4 idealised PAPER fills | NautilusTrader, LEAN, HftBacktest | Fill / slippage / latency / queue models; order-state lifecycle; backtest–live parity |
| F-2 invented correlations; portfolio risk | Riskfolio-Lib, PyPortfolioOpt, skfolio | Rolling covariance, shrinkage, HRP; risk-budget math (for S1 sleeves) |
| Strategy certification / walk-forward | Qlib, vectorbt (Commons Clause: licence review), Alphalens-reloaded, Alpha Engine | Experiment records, purged / embargoed splits, factor IC |
| Performance metrics cross-check | QuantStats | Independent check of `learning_view.metrics` (Sharpe, Sortino, drawdown) |
| Data quality | Pandera, Great Expectations, DuckDB | Candle schema rules; research store separate from operational state |
| Venue adapter (6C) | CCXT (MIT), Hummingbot | Transport only, below ExecutionManager |
| AI-001 (no LLM in the runtime today) | PydanticAI, LangGraph, MS Agent Framework (FIDES) | Typed outputs, untrusted-content labels, tool-authority limits |
| Memory retrieval (after AI-001) | pgvector vs Qdrant (choose one) | Only if structured retrieval proves insufficient |
| Observability (multi-process later) | OpenTelemetry, Prometheus | Trace IDs across market → decision → risk → execution |

## Everything else in the list

Reference only, when a concrete problem needs it:

- Barter
- Freqtrade (GPL-3.0, verified): no code
- Backtrader, Zipline-Reloaded, Backtesting.py, bt
- cvxportfolio, QuantLib
- OpenBB, yfinance (research only, never a production truth source), Polars
- Weaviate, Neo4j, AutoGen
- CrewAI
- TradingAgents (pattern already adapted as `red_team`), RD-Agent
- FinRL (rejected as a decision engine)
- edgartools
- statsmodels, SciPy, scikit-learn
- Grafana (rejected for now: external service)
- FastAPI and Pydantic: already in use

## Rule

No repository replaces ExecutionManager, RiskEngine, EvidenceStore, AtlasMemoryCore, AgentFusion, WorldModel or DecisionBuilder. Each one can only show which **gap** those components have. Every adoption is a separate, owner-approved proposal.

## Second list from the owner (2026-09-30): OMS, lineage, workflow, supply chain

| Area | Repos | Atlas gap it maps to | Class |
|---|---|---|---|
| OMS / order lifecycle | openexch/oms, riffarhan/ghfm-oms, tfrmma OMS+SOR, gregorian-09/orderflow | `core/execution_manager.py`: partial fills, cancel/replace, RECONCILING / UNKNOWN states, double-entry ledger (F-4, treasury) | Study first (code-level comparison) |
| FIX | QuickFIX/J, QuickFIX | Multi-broker transport (after 6C) | Reference, later |
| Feature / dataset / experiment lineage | Feast, DVC, MLflow | No feature versioning; replay results not tied to a dataset version | Study; adopt at most one, only when the research store exists |
| Workflow | Temporal, Dagster | Governance workflows already survive restarts through hash-chained logs | Defer: no proven need |
| Events | Kafka, Redpanda, Redis | Single-process EventBus is enough today | Reject for now (scale not proven); never a financial truth source |
| Data formats | Arrow, Parquet (with DuckDB / Polars) | Historical research store | Study with the data phase |
| Supply chain | OpenSSF Scorecard, Trivy, Sigstore / Cosign | External-code gate is manual today; no SBOM or artefact signing | **Scorecard + Trivy as scout tools: accept as the next security proposal** (they run outside the runtime) |
| Collector | OpenTelemetry Collector | — | Defer with OpenTelemetry |

**Agreed next step (same as the owner's conclusion):** stop adding repositories. Compare the core set against Atlas **file by file**. Start with `core/execution_manager.py` against the OMS group plus NautilusTrader (finding F-4), then `core/risk_engine.py` against Riskfolio / PyPortfolioOpt (finding F-2 / F-3).
