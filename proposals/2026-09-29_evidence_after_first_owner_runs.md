# Evidence after the first owner runs, and the two decisions it points to (2026-09-29)

**Status:** recommendation to the owner. Nothing has changed in the runtime. Both decisions are the owner's.

## What the owner's machine measured (facts)

**`tools.reality_check`: 15 closed PAPER trades.**
- All 15 were opened at confidence 60–70. That is the band admitted only by EXP-001's lowered floor; the policy floor is 70.
- Win rate after fees: 33 %. Net expectancy: −7.42 $ per trade. The gross result is already negative (−5.85 $ per trade) before costs of 1.56 $.
- Monte Carlo over the next 50 trades, resampling these trades: loss probability 100 %; median maximum drawdown −369 $ at +0 bp, −451 $ at +20 bp worse execution.

**`tools.strategy_compare`, 20 coins, 30 days, 3 windows (net $ / max drawdown $):**

| Variant | Window 1 | Window 2 | Window 3 | Sum |
|---|---|---|---|---|
| Realistic reference (today's rules) | +11 / 244 | −384 / 384 | +195 / 142 | **−177** |
| Staged entries + sleeves | +22 / 32 | −114 / 134 | −9 / 59 | **−101** |
| Sell confirmation 2 | −37 / 206 | −355 / 482 | +417 / 137 | +25 |
| 1 h EMA20 trend filter | −117 / 234 | −287 / 287 | +96 / 130 | −307 |
| ATR stop 2x | −247 / 349 | −211 / 218 | +198 / 98 | −259 |
| Minimum hold 60 min | −63 / 297 | −371 / 415 | +189 / 136 | −246 |

On 5 coins over 21 days every variant lost in every window; staged + sleeves lost about a third as much.

## Reading (INFERENCE, stated with its limits)

1. **The signal itself has no edge yet.** Gross P/L is negative before fees. Results depend on the regime: window 2 lost for every variant. No variant is robustly profitable, so no "better strategy" can be claimed.
2. **Staged entries + sleeves is the one robust risk improvement.** Its maximum drawdown is 3–7× smaller in every window on 20 coins and in every window on 5 coins. It is not a profit engine: it gives up the good window 3 (−9 vs +195).
3. **"Sell confirmation 2" has the only positive sum**, but it swings from −355 to +417 with the deepest drawdown (482). That is not evidence; it would be chasing noise.
4. **EXP-001 (confidence floor 60 instead of 70) produced every live PAPER trade, and they lost.** Fifteen trades is below the experiment's own 30-trade verdict bar, so this is a strong signal, not a verdict.

## Decision 1: stop EXP-001 early (owner; risk-reducing, reversible)

- **Why:** every admitted trade came from the lowered floor. They lost with 33 % wins, and the gross result is negative, so the problem is not only fees. Returning to the 70 floor means fewer, higher-bar trades while the strategy work continues.
- **Evidence first:** `python -m tools.exp001_report`. It gives the experiment's formal view.
- **Counter-evidence:** 15 < 30 trades, and one regime only. Stopping early loses the chance to reach the planned sample.
- **How:** the owner's decision. The experiment config is `ATLAS_PAPER_CONFIDENCE_EXPERIMENT` at start-up; the exact switch is to be confirmed on the owner machine before use (UNKNOWN until verified).

## Decision 2: staged entries + sleeves as the risk frame (CRITICAL, needs the full gate)

- **Why:** the only change that cut drawdown in every window on both universes.
- **What it is not:** a profit fix. The signal work (regime engine v2, cost/expectancy gate; see `docs/research/STRATEGY_FRAMEWORK_AND_EXTERNAL_TRADERS_2026-09-29.md`) stays the priority.
- **Gate:**
  1. owner approval of the scope;
  2. implementation behind the existing risk chain;
  3. tests including failure cases;
  4. independent audit;
  5. PAPER-only observation for ≥30 trades.

## Not recommended now

- Raising `max_positions`: more exposure to a signal with no edge.
- The minimum-hold rule: worse than the reference on 20 coins.
- Any live step.
