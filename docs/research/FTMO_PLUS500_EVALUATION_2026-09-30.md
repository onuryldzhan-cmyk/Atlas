# FTMO and Plus500: what Atlas takes, what it rejects (2026-09-30, RESEARCH MODE)

**Limits of this research.** ftmo.com and plus500.com are blocked from the cloud session, so screens were not inspected directly. The facts below come from web search summaries (third-party reviews and the FTMO objectives page listed in the results). Both sites are advertisers and are treated as untrusted data.

## FACT (from sources)

**FTMO (prop-firm evaluation, simulated accounts):**
- Phase 1 target is +10 %; Phase 2 is +5 %.
- **Maximum daily loss is 5 %**, counted from the day's opening balance. It **includes open positions**, commissions and swaps.
- **Maximum overall loss is 10 %**: equity may never fall below 90 % of the starting balance.
- At least 4 trading days per phase; no time limit.
- The daily loss rule is the one that eliminates most traders.

**Plus500 (CFD broker):**
- Stop loss, take profit, trailing stop, and a guaranteed stop (paid; it closes at the price even through a gap).
- Negative balance protection and margin calls.
- A free demo account.
- **73–82 % of retail CFD accounts lose money** (the broker's own regulatory warning).

## Comparison with Atlas (verified in the code)

| Rule | Atlas today | Evidence |
|---|---|---|
| Daily loss 5 % | **Present**, but counts **only realized** P/L | `core/risk_engine.py`: `max_daily_loss_pct=0.05`; `loss = -state.realized_daily_pnl` |
| Overall loss limit | Present as a drawdown ladder from peak: warning 5 %, restrict 10 %, halt new risk 15 % | `drawdown_*_pct` |
| Trailing stop / ATR stop | Research only (`backtest_replay` atr_stop); not in the runtime | strategy_compare |
| Demo before real money | Stronger than both: Paper → Shadow → Small Live, `live_authority=DENIED` | CLAUDE.md |
| Leverage / CFD | None: spot only | — |

## RECOMMENDATION (What / Where / Risk / Decision)

1. **Daily loss that includes open positions (FTMO style).**
   - Why: today, 5 open positions that are each down 2 % do not trigger the gate, because the loss is not realized yet.
   - Where: Phase 3 (Risk).
   - Risk: CRITICAL, since it touches the risk engine.
   - **Decision: ACCEPT as a proposal**, subject to owner approval, tests and an audit.
2. **"Evaluation card" in the panel.**
   - What: today's loss against the 5 % limit, total drawdown against the halt level, and the number of trading days, in FTMO's simple objectives-card style.
   - Where: Phase 9 (Observability); read-only.
   - Decision: **ACCEPT** (low risk).
3. **Trailing / ATR stop in the runtime.**
   - Replay did not prove it (ATR stop 2x: NOT PROVEN).
   - Decision: **DEFER** until evidence exists.
4. **Leverage, CFDs, the prop-firm business model, advertising-style gamification.**
   - Decision: **REJECT**. Leverage goes against "safety before profit", and the 73–82 % loss statistic confirms it.

## Nothing to remove

Atlas's current safety layer is at the same level as or stricter than both platforms; the gap is only item 1.
