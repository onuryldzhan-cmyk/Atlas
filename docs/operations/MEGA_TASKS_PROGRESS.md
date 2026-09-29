# Owner's 20 mega tasks: step-by-step progress (started 2026-09-30)

**Rules for every step:**
- smallest correct change;
- tests;
- no fake data;
- CRITICAL changes (execution, risk, financial state) ship behind a flag that defaults OFF, until an independent audit and the owner's switch-on.

**Status values:** DONE / PARTIAL / NEXT / NEEDS-DATA (the owner's machine) / DEFERRED (with its reason).

**Audit baseline:** `docs/audits/INDEPENDENT_STATUS_AUDIT_MEGA_TASKS_2026-09-30.md`.

| # | Task | Steps done | Next step |
|---|---|---|---|
| 1 | Core completion (decision path, outcome, analysis, lesson, memory, calibration, strategy lifecycle, walk-forward, attribution, counterfactual, portfolio risk, data integrity, realistic paper, recovery) | single-execution-authority test; outcome fingerprint; post-trade analysis; book metrics; lesson lifecycle; **M-1 fix** (last-good evidence / fail closed); L-1 dedupe; L-2 cache; **strategy registry + lifecycle** (`atlas_org/strategy_registry.py`, `config/strategy_registry.json`); **order state machine** (`core/order_lifecycle.py`, informed by NautilusTrader source) | agent attribution from logged votes; calibration buckets 50–100 in `learning_view` |
| 2 | Governance + agent ecosystem | agent cycle (8 rule-based agents), red_team, knowledge_manager, owner-only approval | output-validation contract for agent records; agent experience scorecards |
| 3 | Final integration + certification + 3D | first certification table (self-audit) | per-decision inspector (decision → votes → gates) on `/decisions` |
| 4 | Portfolio / market / execution | **F-3 engine side + wiring**: `MarketLoop.mark_prices` (fresh closes only) → `ExecutionManager._mark_to_market` → `RiskState.unrealized_pnl` (flag OFF) | exposure report per asset / direction |
| 5 | Data engineering | **data source registry** (`config/data_sources.json`; a test fails if code uses an unregistered host) | show the registry on `/system`; candle quality rules |
| 6 | Reliability | supervisor, heartbeat, readiness (existing); **degradation matrix** `config/degradation_matrix.json` with a code-evidence test | incident auto-record from agent-cycle FAILs |
| 7 | Independent final audit | self-audit v1 | **real independent audit: needs a separate reviewer** |
| 8 | Model orchestration | — | DEFERRED (AI-001: no LLM in runtime); registry contract only |
| 9 | Simulation / digital twin | replay drives the real market loop | seeded, versioned dataset manifest for replay |
| 10 | Advanced risk | Monte Carlo on the P/L (offline) | VaR / ES (historical, method recorded) in `reality_check` |
| 11 | Strategy factory | strategy_compare + strategy_agent + **strategy registry** | strategy registry (shared with #1) |
| 12 | Knowledge graph | **F-2**: world-model edges labelled STATIC_SEED_HYPOTHESIS | temporal validity fields; contradiction link to lessons |
| 13 | Multi-venue | instrument rules for one venue | DEFERRED until a 2nd venue is decided (6C) |
| 14 | News / NLP | — | DEFERRED: needs a licensed source decided by the owner |
| 15 | Treasury | — | read-only NAV / cash / fees report from the book |
| 16 | Disaster recovery | **F-6**: `tools/state_backup.py` backup / verify / restore plus a real restore-drill test | owner runs the first real backup (NEEDS-DATA) |
| 17 | Deployment / environments | — | environment matrix (DEV / TEST / PAPER / PROD-CANDIDATE / PROD) as validated config |
| 18 | Compute / cost | — | task duration per agent cycle (tokens N/A) |
| 19 | Advanced 3D HQ | activity feed, ops table, inspector history | timeline view from the same activity feed |
| 20 | Full digital trial | — | after #9 (dataset manifest) and F-4 (fills) |

**Pending owner decisions / data:**
- `strategy_compare --only rejim,aşamalı` output;
- S1 sleeves;
- switching on F-3 after the wiring and the audit;
- whether to commit.
