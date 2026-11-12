# Forex leverage (margin) and short selling — DESIGN for owner approval

**Status:** DESIGN only. No code has been written. Both parts are CRITICAL: they change the risk, capital and
paper-book cores.

**Owner decisions (2026-10-26):** low leverage ("Düşük kaldıraç, örn. 1:2-1:5") and short selling
("Short eklensin").

**Authority is unchanged:** PAPER only, live DENIED. MetaTrader 5 is used with demo accounts only, and for market
data only.

## 1. What exists today (verified in the repository)
- **The book is cash-spot and LONG-only.** `core/execution_portfolio_foundation.py`:
  - a BUY debits the full notional from cash (`INSUFFICIENT_CASH` otherwise);
  - a SELL closes or reduces;
  - any other action raises `LONG_ONLY_ACTION_REJECTED`;
  - positions carry a positive `base_quantity`.
- **SHORT decisions turn into SELLs.** `core/decision_adapter.py` and `core/execution_manager.py` map
  SHORT/OPEN_SHORT to SELL. A SELL of a flat symbol is then treated as HOLD (MarketLoop, registry v5.04). So a SHORT
  decision today never opens anything.
- **Risk limits are measured against capital.** RiskEngine sizes by bucket as a percentage of capital, with
  exposure ceilings, quote exposure, the daily loss limit and drawdown.
- **Sizing is too small for one lot.** At 10,000 USD and 1:1, the HIGH bucket (~1,000 USD) is below 0.01 lot
  (1,000 units, ~1,080 USD for EURUSD). This is the reason for leverage (registry v5.103).
- **Forex has its own state directory.** Since Task 021, FOREX requires a state directory named `forex`, so
  forex starts from an empty book. This matters for migrations: the new book schema below can apply to forex
  state only, and the crypto state (schema 2) needs **no migration**.

## 2. Part A — Leverage as margin accounting

### Options
- **A1 (recommended): leverage scales the position size, and margin replaces the full cash debit.**
  - Bucket notional = bucket % × equity × L. Margin reserved = notional / L.
  - The total open notional is capped at L × equity × exposure ceiling.
  - This is the only option that solves the minimum-lot problem.
- **A2: margin only, with sizes unchanged.**
  - Cash is no longer fully debited, but the size stays at bucket % × equity.
  - It does not reach 0.01 lot for HIGH, so it does nothing useful. Recommended to reject.

### Rules (A1)
- **Leverage value:** L is a single owner-chosen integer from 2 to 5, pinned in the policy manifest. Recommended
  start: L = 2.
- **What the book tracks:** equity = cash + unrealized P&L, used margin, and free margin = equity − used margin. A
  new position needs free margin ≥ its margin. Otherwise it is refused (fail closed).
- **Where the limits are measured:**
  - The daily loss limit and the drawdown stages are measured on **equity**, with unrealized P&L counted
    (the F-3 switch is already on in main.py).
  - Exposure ceilings are measured on **notional**. Leverage therefore cannot hide exposure.
- **Stop-out:** if equity / used margin falls below the owner-chosen margin level (recommended 100 %), the exit
  guard submits SAFETY_EXIT full exits, largest loss first, through ExecutionManager. Every existing check applies.
  It never sells on a stale price.
- **Swap/rollover:** positions held overnight pay or earn a swap. This is UNKNOWN until it is read from MT5
  (`swap_long` and `swap_short` in `symbol_info`). It is charged daily against cash. Until then it is charged as the
  worse of the two sides (conservative).

## 3. Part B — Short selling

### Rules
- **Book (FOREX state only, new schema 3):**
  - each position has a side, LONG or SHORT;
  - P&L is (exit − entry) × quantity for LONG and (entry − exit) × quantity for SHORT;
  - a SHORT reserves margin exactly like a LONG under Part A.
  - **Part B therefore requires Part A**: a short has no meaning in the cash-spot model.
- **Decisions:**
  - in FOREX with shorts enabled, OPEN_SHORT and SHORT open a short, and CLOSE_SHORT closes it with a BUY;
  - a plain SELL still only reduces a LONG;
  - NB-4/NB-5 apply symmetrically: removing evidence must never raise a short's confidence either.
- **Fills:** a short opens at the bid and closes at the ask, with the spread paid both ways (the Task 021 model).
- **Risk:**
  - exposure is measured on absolute notional per currency (short EURUSD is long USD against EUR);
  - the exit guard rules mirror for shorts (a loss when price rises);
  - the weekend close and the pre-close entry block apply to shorts too.
- **Off by default:** shorts are off unless the manifest pins `forex_shorts_enabled = true`.

## 4. Order of work (each one a CRITICAL task)
1. **Manifest v3 activation:** the weekend close (already designed), after the owner ratifies v3.
2. **Part A, margin accounting:**
   - schema 3 for the forex book, plus a write/read tool, with **no migration of the crypto state**;
   - the RiskEngine and sizing changes;
   - the stop-out rule;
   - tests for boundary margin levels, stop-out on a gap, a stale price at stop-out, restart idempotency, and the
     crypto golden tests unchanged.
3. **Part B, short selling:** on top of Part A, with the same test discipline plus the symmetric NB-4/NB-5 cases.

Each task follows the same steps:
1. A registry grant.
2. The full suite.
3. An independent read-only review with 0 BLOCKING / 0 HIGH / 0 MEDIUM before commit.
4. A checkpoint.

The CLAUDE.md migration checklist applies to schema 3: idempotency, resume, retry, sequence, ordering, duplicates,
partial state, conflicts, and rollback/recovery.

## 5. What the owner decides
1. **Leverage value L:** 2, 3, 4 or 5. Recommended: 2.
2. **Stop-out margin level:** recommended 100 %.
3. **Pair scope:** all four USD-quoted pairs for shorts and leverage, or a subset.
4. **Order of work:** the recommended order is v3 activation, then Part A, then Part B. Moving to MT5 verification
   first, before any of these, is also possible.

## 6. Risks and UNKNOWNs
- **Losses scale with L.** With L = 2, a 1 % adverse move on a full HIGH-bucket position loses 2 % of that bucket's
  share.
- **Gap risk.** A Monday gap can jump past the stop-out level. The weekend close reduces this risk, but cannot
  remove it for a position opened after the close.
- **Swap rates** are UNKNOWN until read from MT5.
- **Regulation is UNKNOWN.** Retail leverage limits apply to the owner's real account (for example SPK in Turkey,
  commonly cited as 1:10). This design is PAPER only.
