# Core improvements from high-star repos (RESEARCH MODE, 2026-10-02)

Status: PROPOSAL ONLY. Nothing implemented. No external code copied, run or installed. External content treated as untrusted data.
Scope: core (risk, order lifecycle, sizing, backtest/replay, calibration, fusion, data quality, recovery). Dashboard/HQ items from proposals/20261001T120000Z_* and 20261001T130000Z_* are not repeated.

## 1. Sources and licences (FACT unless marked)
| Project | Licence (fetched LICENSE file 2026-10-02) | Source used | Implication |
|---|---|---|---|
| nautechsystems/nautilus_trader | LGPL-3.0 | raw LICENSE; docs page fetch for risk/execution FAILED (UNKNOWN - requires verification) | ideas only |
| freqtrade/freqtrade | GPL-3.0 | docs/includes/protections.md, docs/lookahead-analysis.md, docs/recursive-analysis.md | ideas only, no code |
| hummingbot/hummingbot | Apache-2.0 | LICENSE | ideas; code reuse would still need full adoption review |
| kernc/backtesting.py | AGPL-3.0 | LICENSE.md | ideas only |
| polakowo/vectorbt | Apache-2.0 + Commons Clause | LICENSE.md | ideas only (Commons Clause) |
| microsoft/qlib | MIT | LICENSE | ideas |
| jesse-ai/jesse | MIT | LICENSE | ideas |
| Purged k-fold / embargo / triple barrier / meta-labeling / deflated Sharpe | Textbook: M. Lopez de Prado, *Advances in Financial Machine Learning* (Wiley 2018) ch. 3, 7, 14; Bailey & Lopez de Prado (2014) "The Deflated Sharpe Ratio". mlfinlab is under a proprietary/commercial licence (INFERENCE from memory, UNKNOWN - requires verification) - not used. | method only |

FACT (freqtrade protections.md): StoplossGuard (stop after N stoplosses in lookback window), MaxDrawdown (lock trading when drawdown over closed trades in lookback exceeds limit), LowProfitPairs (lock a pair whose profit over lookback is below threshold), CooldownPeriod (lock a pair for stop_duration after exit).
FACT (freqtrade lookahead-analysis.md): validates strategies by chaining backtests and comparing signals computed on full vs truncated data. recursive-analysis.md: indicators with recursive formulas differ depending on warm-up length available live vs in backtest.
INFERENCE (memory, not re-fetched): NautilusTrader RiskEngine has a TradingState ACTIVE/REDUCING/HALTED, order submit-rate throttling and max-notional-per-order checks; its execution engine reconciles cached orders/positions against venue reports at startup. Marked UNKNOWN - requires verification before citing as fact.

## 2. Atlas as inspected (FACT)
- core/risk_engine.py:236-264 RiskPolicy: exposure/position/confidence floors, daily loss (amount/pct), F-3 unrealized flag, sleeves, drawdown warning/restrict/halt. evaluate() 635-773: state readiness, policy version, accounting day, reduce-only path, CRITICAL/unsupported refusals, confidence floor, daily loss, drawdown, duplicate position, max positions, capacity. No time-windowed loss-streak or per-symbol cooldown/lock; no order-rate limit.
- core/order_lifecycle.py:24-37 canonical state machine (Nautilus-style DENIED rule, late fill after cancel, idempotent fill ids); observe_outcome() 94 is observe-only and maps only PAPER_EXECUTED and REJECTED.
- core/position_sizing.py:129-210 sizing = durable_free_cash x bucket max_allocation_pct, min'ed by RiskEngine capacity; no volatility or stop-distance term.
- tools/backtest_replay.py:16 default fills at decision candle close, no slippage; :215 optional slippage_bps / next_open_fill (registry v5.47).
- tools/strategy_compare.py:65-79 split() contiguous windows, embargo drops the first `embargo` candles of windows i>0 (one-sided, no purge of trades whose holding period spans a boundary).
- tools/reality_check.py:35 BANDS, 39-61 calibration per band: win rate, expectancy, Wilson CI; no Brier score / reliability gap; 82 Monte Carlo drawdown; 115 VaR/ES.
- ai/core/intelligence/agent_fusion.py:552-705 weighted vote with configured WEIGHTS, missing_weight and MIN_WEIGHT_COVERAGE (NB-5 guard). Weights static.
- observability/learning_view.py:139-165 metrics: expectancy, win rate, sharpe_per_trade.
- tools/state_backup.py: sha256 manifest backup/verify/restore, refuses when Atlas running.

## 3. Gap comparisons and proposals

### P1 Loss-streak / stoploss guard (refuse-only)
Atlas: evaluate() checks daily loss and drawdown only (risk_engine.py:713-737). freqtrade StoplossGuard stops entries after N losing stop exits within a lookback (protections.md).
What: optional policy `max_losing_exits_in_window` + `loss_window_minutes`; when count >= N, BUY rejected `LOSS_STREAK_GUARD`. Default OFF (byte-identical). Unknown count = reject (fail closed) when ON.
Why: daily-loss limit can be reached slowly by many small losses or reset at UTC midnight; streak guard catches regime breaks earlier. Where: core/risk_engine.py (RiskPolicy, RiskState field, evaluate), tests/. Dependencies: closed-trade feed to populate RiskState. Risk: low (refuse-only). Cost: S. Alternative: tools-only report. Decision: ACCEPT (owner approval required to switch ON). Tier: CRITICAL (risk path).

### P2 Per-symbol cooldown after exit (refuse-only)
Atlas: only DUPLICATE_OPEN_POSITION (risk_engine.py:742). freqtrade CooldownPeriod locks a pair after exit.
What: `symbol_cooldown_minutes` (default 0/OFF); BUY on a symbol whose last exit is younger => `SYMBOL_COOLDOWN`. Where: core/risk_engine.py. Risk: low. Cost: S. Alternative: strategy-level filter (not authoritative). Decision: ACCEPT. Tier: CRITICAL.

### P3 Purged + embargoed split in strategy_compare (research)
Atlas: strategy_compare.py:79 embargo only at the start of later windows; trades opened in window i may resolve using candles of window i+1 (no purge). Lopez de Prado ch.7: purge training samples whose label horizon overlaps the test set, plus embargo after the test set.
What: add `purge` = max holding horizon candles removed at the END of each window too; report it in result["parameters"]. Default 0 keeps output identical. Where: tools/strategy_compare.py, tests/test_strategy_compare*. Risk: none to runtime. Cost: S. Decision: ACCEPT. Tier: ROUTINE.

### P4 Brier score + reliability gap in reality_check (research)
Atlas: reality_check.py:39-61 reports win-rate per band but no proper scoring rule. Standard: Brier score; expected calibration error = weighted |mean confidence - win rate| per band.
What: add `brier` and `reliability_gap` per band and overall, with INSUFFICIENT when n < MIN_SAMPLE. Never feeds back into confidence (NB-4: evidence of miscalibration may only lower, never raise). Where: tools/reality_check.py. Cost: S. Risk: none. Decision: ACCEPT. Tier: ROUTINE.

### P5 Lookahead / recursive-warm-up check for replay (research)
Atlas: backtest_replay.py computes signals over loaded series; no automated check that a decision at t is unchanged when data after t is removed. freqtrade lookahead-analysis + recursive-analysis.
What: tool that re-runs the brain on truncated prefixes at K sampled timestamps and on varied warm-up lengths, flags any differing decision. Where: new function in tools/backtest_replay.py (or tests/test_replay_no_lookahead.py). Cost: M. Risk: none. Decision: ACCEPT. Tier: STANDARD.

### P6 Make realistic fills the default for comparisons
Atlas: backtest_replay.py:16 default close-fill, 0 slippage; realism is opt-in (:215). Backtesting.py/Nautilus fill on next bar/order book (INFERENCE, general knowledge).
What: strategy_compare REALISTIC profile already exists (line 42 area); require any "promote" verdict to use next_open_fill=True and slippage_bps>0; report optimistic results labelled OPTIMISTIC. Where: tools/strategy_compare.py. Cost: S. Risk: none (stricter). Decision: ACCEPT. Tier: ROUTINE.

### P7 Deflated Sharpe / multiple-testing note on variant comparisons
Atlas: strategy_compare compares several VARIANTS and picks; learning_view.py:165 sharpe_per_trade with no trial-count adjustment. Bailey & Lopez de Prado (2014) deflated Sharpe.
What: report number of variants tried and a DSR/probabilistic Sharpe; a variant "wins" only if DSR exceeds threshold. Where: tools/strategy_compare.py, observability/learning_view.py (read-only metric). Cost: M. Risk: none. Decision: ACCEPT. Tier: STANDARD.

### P8 Startup reconciliation check (observe-only first)
Atlas: order_lifecycle.py has RECONCILING state but observe_outcome() maps only two outcomes; no startup diff of journal vs portfolio vs (paper) venue. Nautilus reconciles at startup (INFERENCE, UNKNOWN - requires verification).
What: pure function `reconcile(journal_orders, positions, venue_report) -> list[mismatch]`; at startup any mismatch sets state_ready=False (already causes RISK_STATE_NOT_READY / BLOCK_RECOVERY_REQUIRED). Stage 1 report-only. Where: core/order_lifecycle.py + tests. Cost: M. Risk: medium (startup path) - stage 1 observe-only. Decision: ACCEPT (stage 1), DEFER wiring. Tier: CRITICAL.

### P9 Order-rate / max-notional-per-order throttle (refuse-only)
Atlas: no per-minute submission cap in RiskEngine. Nautilus (INFERENCE) max_order_submit_rate, max_notional_per_order; hummingbot kill switch (Apache-2.0, concept).
What: `max_new_orders_per_minute` default OFF; exceeding => `ORDER_RATE_LIMIT`. Guards runaway loops. Where: core/risk_engine.py. Cost: S. Risk: low. Decision: DEFER until Small Live (paper loop has no venue rate risk; keep roadmap discipline). Tier: CRITICAL.

### P10 Volatility-aware down-sizing (shrink-only)
Atlas: position_sizing.py:181 candidate = cash x bucket pct, no volatility term. freqtrade/jesse examples size by stop distance / ATR (INFERENCE from docs memory).
What: optional multiplier min(1, target_vol / realized_vol), capped at 1 so it can ONLY shrink; unknown vol => no change? NO: unknown vol => REFUSED when enabled (fail closed). Where: core/position_sizing.py. Cost: M. Risk: medium (sizing). Decision: DEFER (needs replay evidence first via P5/P6). Tier: CRITICAL.

### Rejected
- Kelly / edge-based up-sizing (freqtrade Edge, removed upstream; Kelly increases size with estimated edge): REJECT - can raise exposure on noisy evidence (rule 3, rule 5).
- Learned/adaptive fusion weights from recent accuracy: REJECT for now - self-modifying decision weights without governance (rule 6); revisit only as a proposal-only report.
- Hyperopt-style parameter search on live configs: REJECT - overfitting, and P7 must exist first.
- Inventory skew (hummingbot market making): REJECT - not Atlas's strategy class; new feature.
- Triple barrier / meta-labeling: DEFER - useful labelling for research but new subsystem; revisit after Phase work completes.

## 4. Ranked top 10 (value / effort)
| # | Item | Tier | Decision |
|---|---|---|---|
| 1 | P4 Brier + reliability gap | ROUTINE | ACCEPT |
| 2 | P3 Purge at window ends | ROUTINE | ACCEPT |
| 3 | P6 Realistic fills required for verdicts | ROUTINE | ACCEPT |
| 4 | P1 Loss-streak guard (default OFF) | CRITICAL | ACCEPT |
| 5 | P2 Symbol cooldown (default OFF) | CRITICAL | ACCEPT |
| 6 | P5 Lookahead / warm-up check | STANDARD | ACCEPT |
| 7 | P7 Deflated Sharpe / trial count | STANDARD | ACCEPT |
| 8 | P8 Startup reconciliation, observe-only | CRITICAL | ACCEPT stage 1 |
| 9 | P10 Vol-aware shrink-only sizing | CRITICAL | DEFER |
| 10 | P9 Order-rate throttle | CRITICAL | DEFER |

All ACCEPTs remain subject to owner approval and registry entry; every risk-path item is refuse-only with default OFF and must test missing/unknown inputs failing closed.

## Status after review (2026-10-02, same session)
| Item | Status | Note |
|---|---|---|
| **#1 Brier score and calibration gap** | DONE | `tools/reality_check.py` adds `mean_confidence`, `brier` and `calibration_gap` per band. Research only. Tested. |
| **#2 Purge at window ends** | NOT NEEDED (claim checked) | `split()` returns disjoint slices `rows[i*size+embargo:(i+1)*size]`, and each replay sees only its own slice. A trade therefore cannot use the next window's candles, and positions still open at a window's end are counted as `open_at_end`. The proposal's premise is incorrect. |
| **#3 Realistic fills for any verdict** | DONE | A variant gets a verdict only with both `slippage_bps` and `next_open_fill`. Tested. |
| **#7 Multiple testing** | PARTLY DONE | `compare()` now reports `multiple_testing.variants_judged` with a caution note. A full deflated Sharpe is DEFERRED until per-window return series are long enough. |
| **#4 and #5 protections** | DEFERRED | Waiting for the cooldown evidence that `/postmortem` now measures. CRITICAL: refuse-only, default OFF, audit and owner required. |
| **#6 Look-ahead check** | DONE (research) | `tools/lookahead_check.py`: replays a truncated and a full dataset; trades closed before the cut must be identical. A test confirms a strategy that peeks at future data is caught. Warm-up-length sensitivity is still open. |
| **#8** | DEFERRED | CRITICAL; next. |
| **#9, #10** | DEFERRED | As in the proposal. |
