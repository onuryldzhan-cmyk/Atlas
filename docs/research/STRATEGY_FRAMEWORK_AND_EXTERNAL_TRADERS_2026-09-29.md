# Strategy framework, external trader intelligence and the reality layers: what Atlas has, what it adds, in what order (2026-09-29)

**Source.** The owner's framework (chat, 2026-09-29):
- a regime-aware multi-strategy ensemble;
- an External Trader Intelligence layer that is "not copy trading";
- 21 reality layers.

Each item is checked against the repository. Format: **What / Where (phase) / State in code / Decision**.

**Correction the owner made, recorded here.** Earlier win-rate figures (for example "trend following 65 %") were illustrative, not Atlas results. Atlas's target is not a win rate. It is out-of-sample expectancy after fees and slippage, risk-adjusted return, drawdown, stability and regime robustness. This matches rule 3, "never raise confidence without evidence".

## Already in the code (EVIDENCE)

| Layer | Where it is |
|---|---|
| Kill switch | `emergency_mode` / `execution_halted` in the runtime and execution manager; corrupt state halts. |
| Data quality guardian (partial) | Market-data staleness per coin; not-yet-closed candles rejected (`future_candles_rejected`); `tools/data_health_check.py`; agent cycle `data_quality`. **Missing:** cross-exchange price consistency (one venue today). |
| Volatility regime (partial) | `core/market_risk_regime.py`: LOW / NEUTRAL / HIGH realized volatility, used as a vote and as the risk bucket input. |
| "No trade" as a first-class decision | HOLD; two confidence gates; SELL without a position is treated as HOLD; the fusion needs ≥3 participating agents. |
| Walk-forward | `tools/strategy_compare.py` over replay windows. |
| Devil's advocate (proposals) | `red_team` agent (v5.67). |
| Learning from own trades | BRAIN-MEM-001 (v5.63): caution only, never confidence. |
| Paper → Shadow → Small live | CLAUDE.md ladder; `live_authority=DENIED`. |

## Added now (v5.69; offline only, no runtime change)

| Layer | What |
|---|---|
| Confidence calibration | `tools/reality_check.py`: each closed trade joined to the confidence it was approved with; win rate after fees and expectancy per confidence band (50–60, 60–70, 70–80, 80+). This answers "what is Atlas's 63 % worth?" with its own data. |
| Monte Carlo stress | Bootstrap of the net P/L sequence, fixed seed, with +0 / +10 / +20 bp worse execution: median, 95th and 99th percentile maximum drawdown over the next 50 trades, and the chance of a loss. |
| Cost engine (measurement) | Gross edge vs estimated round-trip cost per trade, and whether the edge covers costs. On the owner's book it does not: fees are 267 % of gross. |
| Automation | The agent cycle's `quant_research` writes all of this to memory after every new closed trade. |

## Next, in this order (each is a separate proposal; CRITICAL items need tests, an independent audit and the owner's signature)

| # | Layer | Phase | Why this order |
|---|---|---|---|
| 1 | Cost / expectancy gate in the runtime (no BUY unless the expected move clears the estimated cost by a margin) | 2 (CRITICAL) | The measured problem today is fee drag, not signal quality. `strategy_compare` (--min-hold, slippage) produces the evidence first. |
| 2 | Regime engine v2: trend / sideways / high-volatility / panic / transition from closed candles | 2 | The strategy router needs it. It extends the existing volatility regime rather than replacing it. |
| 3 | Strategy router + ensemble (trend, momentum, breakout, mean reversion per regime) | 2 → 4 | Each strategy goes through `RESEARCH-0001`: the hypothesis registry, leakage-safe splits and FDR control. `core/trade_plan_engine.py` is the seam for exits (inventory v5.64). |
| 4 | Strategy decay detector (recent vs historical expectancy per strategy and coin) | 4 | Rule-based agent in the cycle. Needs ≥30 trades per unit to say anything. |
| 5 | Correlation engine (coin and signal correlation, so that 5 agreeing coins are not counted as 5 independent bets) | 3 | Feeds exposure limits; related to the open `max_positions` decision. |
| 6 | Liquidity / spread / order-book check before an order | 2 | Needs order-book data (a new endpoint on the public Binance API). Slippage is modelled in replay today. |
| 7 | News / event risk (FOMC, CPI, exchange incidents) | 4 | Needs a vetted source (external-code rule: license, security, quality). Starts as a "no-trade window" calendar, not a model. |
| 8 | Reality Score per strategy (backtest → out-of-sample → walk-forward → paper → shadow → costs → regimes) | 4 | A status ladder shown in the panel, not a success score. |

## External Trader Intelligence

- **Decision: DEFER, Phase 4, research first.**
- **Accepted as design:**
  - traders are external signal sources, never employees and never copied;
  - Trader → normalization → fingerprint (style, regime, holding time, leverage, drawdown, correlation with Atlas) → regime check → Atlas agrees? → fusion → risk → **paper only** → validation;
  - trader decay and style-drift detection;
  - weights come from Atlas's own measured results on those signals, never from the trader's advertised ROI.
- **Blocking questions (UNKNOWN, need verification before any code):**
  1. Is there an official, terms-compliant data source? Binance copy-trading and eToro profile data may not have a public API for third-party use; scraping is out.
  2. What are the latency and the survivorship bias of "top trader" lists?
  3. How is manipulation handled (fake track records, the social-media impersonation the SEC warned about in 2026)?
- **Evidence the owner cited:** naive follow strategies do not beat costs; past performance does not predict future results. That supports paper-only validation with Atlas's own measurement.
- **What it would need:** a source decision by the owner, a research record with license and terms, then a PAPER-only shadow collector that records signals and their later outcomes. It would not feed the fusion until the outcomes clear the evidence bar.

## Non-negotiables kept

- A trader signal, a news flag or a model can only add caution or be one input to the fusion. Nothing bypasses Decision → Risk → Capital → Execution Manager.
- Confidence is not a probability of profit; calibration measures it.
- Nothing is promoted from backtest to runtime without walk-forward evidence, paper results, the owner's signature and an audit.
