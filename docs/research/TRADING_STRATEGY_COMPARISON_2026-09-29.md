# Research: Atlas's trading strategy versus established approaches (2026-09-29)

**Owner request:** "alım satım stratejilerini araştırıp atlasınki ile karşılaştırmanı istiyorum".

**Mode:** RESEARCH (CLAUDE.md), with FACT, INFERENCE and RECOMMENDATION kept apart.
- Nothing here changes the runtime.
- Every recommendation is tested in the replay first, then goes through an owner-approved proposal.
- Roadmap placement: Phase 4, research and strategy.

## 1. Atlas today (FACT, from the repository and registries)

| Aspect | Atlas |
|---|---|
| Data | Binance 1-minute candles, live and real. Macro data (US Treasury yields) and sentiment (Fear & Greed) are fetched daily and fail closed. |
| Signal | Five deterministic agents (technical, macro, sentiment, volatility-risk, momentum) are fused into BUY / SELL / HOLD with a confidence score. The confidence denominator is the expected roster size (NB-5). No LLM is involved (ADR-0011). |
| Entry gate | The confidence floor depends on the risk bucket: LOW 0.60, MEDIUM 0.70, HIGH 0.80. The execution gate is ≥ 60. EXP-001 lowers the floor to 0.60 for 50 paper admissions, sized as HIGH. |
| Sizing | Fixed fraction of capital per bucket: LOW 40 %, MEDIUM 25 %, HIGH 10 %. At most 5 positions, 80 % total exposure, and a daily loss limit. |
| Exit | **Only a SELL decision with confidence ≥ 60.** The runtime has no stop-loss, no take-profit and no trailing stop. The staged ladder and stop exist only in the backtest (v5.32). |
| Costs | Paper fee is 0.1 % per side. Fills happen at the last closed candle's close, with no slippage (v5.47 finding). |
| Evidence | The 7-day replay (v5.33) with EXP-001 had 50 trades, 12/50 wins after fees and net −129.74, with fees at 99.87. **Every exit was a SELL signal.** |

## 2. What the literature and practitioners report

- **Time-series momentum (trend following) exists in crypto.** Cross-sectional momentum (ranking coins against each other) is weak. Under realistic assumptions, **transaction costs remove much of the profit**: many portfolios that look significant before costs earn insignificant profits after them.
  - Sources: [Han, Kang & Ryu (SSRN 4675565)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565), [AUT/ACFR version](https://acfr.aut.ac.nz/__data/assets/pdf_file/0009/918729/Time_Series_and_Cross_Sectional_Momentum_in_the_Cryptocurrency_Market_with_IA.pdf), [Dynamic TSMOM (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S1062940821000590), [Bitcoin intraday TSMOM](https://centaur.reading.ac.uk/100181/3/21Sep2021Bitcoin%20Intraday%20Time-Series%20Momentum.R2.pdf).
- **Holding period matters.** Momentum works over hours to weeks. At the minute scale, noise and fees dominate. (INFERENCE from the same sources: the studied horizons run from minutes to months, and costs bite hardest at short horizons.)
- **Stops.**
  - ATR-based stops (a multiple of the Average True Range) adapt to volatility.
  - ATR-based sizing shrinks positions when markets are wild.
  - Trailing stops can underperform fixed stops in jagged crypto markets because of whipsaw.
  - Sources: [Coinquant ATR](https://www.coinquant.ai/blog/how-to-use-atr-in-a-crypto-trading-strategy-with-backtest), [TrendRider stop comparison](https://trendrider.net/blog/stop-loss-strategies-crypto-trading-2026), [DEV: 4 stop methods](https://dev.to/trendrider/i-tested-4-stop-loss-methods-on-my-crypto-bot-heres-what-actually-works-47i0).
- **Validation.** A backtest is credible only with processing delay, conservative fills, strict out-of-sample windows and walk-forward testing of any tuned parameter.
  - Sources: [Freqtrade backtesting](https://www.freqtrade.io/en/stable/backtesting/), [Blockchain Council on overfitting](https://www.blockchain-council.org/cryptocurrency/backtesting-ai-crypto-trading-strategies-avoiding-overfitting-lookahead-bias-data-leakage/), [Coin Bureau 2026 guide](https://coinbureau.com/guides/how-to-backtest-your-crypto-trading-strategy).

## 3. Comparison

| Topic | Established practice | Atlas today | Gap (INFERENCE) |
|---|---|---|---|
| Signal horizon | Trend on hours to days | Decisions every cycle on 1-minute candles | Minute-scale flips create churn. The v5.33 losses match "profitable before costs, unprofitable after". |
| Exit rule | A protective stop plus a rule-based exit, with hysteresis | Only the opposite signal exits | No protection between signals; exits happen on the first opposite signal (every v5.33 exit). |
| Stop type | ATR-scaled | None in the runtime; fixed −3 % in the backtest only | Fixed percentages ignore each coin's volatility. This matters more with 20 coins, where the HIGH group is volatile. |
| Sizing | Volatility targeting (risk per trade) | Fixed fraction per bucket | The buckets are regime-based, which is partly volatility-aware, but no rule sets risk per trade. |
| Costs | Modelled: fees, spread, slippage, latency | Fee only, fill at the last close | Paper results are optimistic. The v5.47 replay flags now measure this. |
| Validation | Walk-forward, out-of-sample | One 7-day macro-neutral replay | One window is not evidence (v5.33 said so). |
| Governance | Usually none | Owner-gated, deterministic, audited | Atlas is **ahead** here: no strategy change reaches capital without evidence and approval. |

## 4. Recommendations (each one is tested first in `tools/backtest_replay.py`, then goes to an owner proposal)

1. **Reduce churn before anything else.** Test `--min-hold 60` and `--sell-confirm 2` (v5.47) with `--slippage-bps 5 --next-open-fill`.
   - Pass criterion: net P/L after fees and drawdown both better than the baseline over **at least 3 separate 7-day windows**.
2. **Make paper fills realistic in the runtime** (CRITICAL, needs owner approval): fill at the next observed price with a small adverse slippage. This removes optimism; it is the most conservative change on this list.
3. **A higher-timeframe trend filter for entries.** Allow a BUY only when the 1-hour trend agrees, for example the close above a 1-hour EMA.
   - This needs a new replay flag and an out-of-sample check.
   - It fits the evidence: time-series momentum works over hours, not minutes.
4. **An ATR-based protective stop** in place of the fixed −3 %.
   - Test 2×ATR and 3×ATR against the fixed stop.
   - Keep the confirmation candles (wick immunity, v5.32).
   - Treat trailing stops with caution, because whipsaw is well documented.
5. **Risk-per-trade sizing** inside the existing bucket caps: size = (equity × risk %) / stop distance, never above today's bucket maximum. This is risk-reducing only and never widens exposure.
6. **Walk-forward validation** as the rule for adopting any parameter: tune on one window, confirm on the next, and report both.

## 5. What we will not do

- **No strategy that raises confidence without evidence** (rule 3). Guarded by NB-4 and NB-5.
- **No bigger positions or more simultaneous positions** as a "strategy". Those are risk decisions for the owner.
- **No cross-sectional "rank the coins" rotation** for now: the evidence for it in crypto is weak.
- **No copying of GPL strategy code** (Freqtrade is GPL-3.0). Ideas only.

## 6. Next exact steps

1. The owner runs the four replay commands in OWNER_TERMINAL_TASKS §11 on real data.
2. If churn reduction helps across the windows, write a CRITICAL proposal for the runtime exit rule plus realistic paper fills: tests, independent audit, owner signature.
3. Add replay flags for the 1-hour trend filter and the ATR stop (research only), then repeat step 1.
