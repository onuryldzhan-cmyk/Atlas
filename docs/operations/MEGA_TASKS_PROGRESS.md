# Owner's 20 mega tasks: step-by-step progress (2026-09-30)

**Rules for every step:**
- smallest correct change;
- tests;
- no fake data;
- commit after each step.

CRITICAL runtime changes ship **behind a switch that defaults OFF**, which keeps today's behaviour byte-identical. A switch is turned on only after an independent audit and the owner's decision.

**Status values:**

| Status | Meaning |
|---|---|
| DONE | The task's core is implemented and tested |
| PARTIAL | Implemented steps are listed; the gap is named |
| DEFERRED | Blocked on a named prerequisite |
| NEEDS-OWNER | Needs data or a switch-on from the owner machine |

| # | Task | Status | What exists now (all tested) | Remaining gap / blocker |
|---|---|---|---|---|
| 1 | Core completion | PARTIAL | Single execution authority (architecture test); TradeOutcome fingerprint; post-trade analysis; labelled counterfactuals; book metrics (expectancy, profit factor, Sharpe, Sortino, drawdown, recovery factor); lesson lifecycle PROPOSED → VALIDATING → CONFIRMED (owner) / CONTESTED / EXPIRED; M-1 last-good / fail-closed memory; calibration buckets 0–50 … 90–100 with Wilson intervals; strategy registry and lifecycle; agent votes in telemetry plus an attribution tool; order state machine; F-4 PAPER slippage model (default 0) | Order state machine not yet enforced inside ExecutionManager. F-4 end-to-end PAPER BUY→SELL with slippage > 0 is tested (`tests/test_f4_slippage_end_to_end.py`); switch-on still needs the independent audit. No runtime calibrated-confidence layer. Walk-forward uses replay windows; there is no purged or embargoed splitter. |
| 2 | Governance + agent ecosystem | DONE (rule-based) | 8 rule-based agents in the cycle; red_team; knowledge_manager; market_regime; agent-output schema validation plus SensitiveDataGuard; owner-only approval; hash-chained logs | LLM agents wait on AI-001 |
| 3 | Integration + certification + 3D | PARTIAL | Decision inspector shows votes, gates and **which memory evidence shaped the decision**; self-audit certification table | Per-decision replay; independent certification (task 7) |
| 4 | Portfolio / market / execution | PARTIAL | F-3 unrealized P/L in daily loss (engine and mark-to-market wiring, switch OFF); exposure by asset; largest concentration; long-only spot direction | Correlation (a measured source is needed); liquidity and order book: the runtime has no source for them |
| 5 | Data engineering | DONE (current scope) | Data source registry (a test fails on an unregistered host); **NaN / infinite OHLCV now rejected** (bug fixed); dataset manifest with sha256; save / replay | Feature store: no ML features exist yet |
| 6 | Reliability | DONE (current scope) | Supervisor, heartbeat, readiness; degradation matrix with code evidence; a failed agent opens one OPEN incident; runaway-agent flag | Chaos testing of the live process: owner machine |
| 7 | Independent final audit | NEEDS-OWNER | Self-audit exists (`docs/audits/`) | Needs a reviewer independent of this session |
| 8 | Model orchestration | DONE (contract) | `config/model_registry.json`: no active model; routing, abstain on failure, "model confidence ≠ Atlas confidence"; a test pins no trading authority | Implementation waits on AI-001 |
| 9 | Simulation / digital twin | DONE (research) | Replay drives the real chain; dataset hash; reproducible save / replay; a corrupted dataset is refused | — |
| 10 | Advanced risk | DONE (offline) | Historical VaR / ES with a method note and a tail warning; Monte Carlo with worse execution | Correlation-break scenarios need measured correlation (task 4) |
| 11 | Strategy factory | DONE (registry) | Strategy registry lifecycle: certification needs the owner plus an independent audit; book-level decay lesson; strategy_compare / strategy_agent | Automated hypothesis generation waits on AI-001 |
| 12 | Knowledge graph | PARTIAL | World-model edges labelled STATIC_SEED_HYPOTHESIS; temporal validity; lessons carry evidence and contradictions | No graph store; relationships are not measured |
| 13 | Multi-venue | DONE (contract, 1 venue) | `config/venues.json` bound to instrument rules by a test; no order submission | A second venue is an owner decision (6C) |
| 14 | News / NLP | DEFERRED | Contract: no active source; one event = one piece of evidence; news can never create an order | The owner must choose a licensed source |
| 15 | Treasury | PARTIAL | NAV and a single-denomination guard (mixed currencies never summed) | Deposits / withdrawals ledger; FX (no source) |
| 16 | Disaster recovery | NEEDS-OWNER | Backup / verify / restore with a restore-drill test; corrupted backups refused | The owner runs the first real backup |
| 17 | Deployment / environments | DONE (contract) | `config/environments.json` bound to `main.py`; only PRODUCTION has real money, and it is DENIED; Shadow comes before release | Artefact signing (Sigstore) is deferred |
| 18 | Compute / cost | DONE (current scope) | Agent-cycle resource record; runaway budget flag; tokens N/A (no LLM) | — |
| 19 | Advanced 3D HQ | PARTIAL | Real-state HQ; activity feed with RUNTIME / GOVERNANCE / SECURITY / **TRADE** timeline; inspector; ops table; CONNECTION LOST | R3F 3D engine deferred (new toolchain) |
| 20 | Full digital trial | DONE (research) | `tools/digital_trial.py`: determinism plus injected NaN / duplicates / outage / out-of-order. Measured: bad ordering or duplicates → the coin is skipped (fail closed); NaN rejected; an outage gives fewer trades | Multi-regime long-period run on the owner machine with a saved dataset |

## What the owner needs to do next (owner machine)

1. **First real backup**, with Atlas stopped:
   - `python -m tools.state_backup backup --out <folder>`
2. **A dataset for the trial and the comparison:**
   - `python -m tools.strategy_compare --days 30 --windows 3 --symbols-file config/universe_selection.json --only rejim,aşamalı --save-dataset ds.json`
   - then `python -m tools.digital_trial --dataset ds.json`
3. **Agent attribution** once a few trades have closed with votes recorded:
   - `python -m tools.agent_attribution`
4. **Decisions:**
   - S1;
   - switching on F-3 and F-4 after the independent audit.
