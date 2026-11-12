# Paper fee model plan (draft, 2026-09-28)

Owner decision: "Add an estimated fee to the report, then plan the model." The report part is done (commit bd7a31f). This document is the plan only. Implementation starts once the owner approves it.

## FACT (inspected)

- The owner's `tools.exp001_report` shows `all fees 0.00` after 5 closed paper trades. Paper results are therefore fee-free and overstate profit. The estimate at 0.1% per side is about 8 USDT against 17.54 gross.
- The accounting path already handles fees end to end:
  - `ExecutionManager` takes a component-reported `fee_amount` and `fee_currency` (`core/execution_manager.py` around 5870–5910);
  - `FeeNormalizer` accepts only a fee in the venue's quote asset;
  - the allocation is reduced by the fee;
  - `ExecutionPortfolioFoundation` debits `notional + fee` and books `fees` and `entry_fees`.
- The paper fill in the runtime never reports a fee, so the fee is always 0.
- The code notes that no fee-rate policy exists.
- `core/paper_execution_engine.py` has `fee_rate=0.001`, but it is **not** in the runtime closure. It is not the runtime path.

## Smallest correct change

1. Add one named constant, `PAPER_FEE_RATE_PER_SIDE = 0.001` (Binance spot base taker rate). It is pinned in code and in the registry, with no config or environment variable. The actual Binance rate for the owner's account tier is **UNKNOWN**; 0.001 is the public base rate.
2. The paper fill reports `fee_amount = rate × fill notional` in the quote asset (USDT), with `fee_currency = USDT`, on both BUY and SELL.
3. Nothing else changes. The existing chain (normalizer, allocation, settlement, `fees`/`entry_fees`) does the rest.

## Tests

- **BUY:** cash is debited by notional + fee, `entry_fees` = rate × notional, and the fee is carried within the approved allocation (the allocation is never exceeded).
- **SELL:** cash is credited by proceeds − fee; account `fees` grows by both sides.
- **Round trip:** net P&L = gross − both fees; the report's actual fee matches its estimate.
- **Idempotent replay** never charges twice.
- **Fee-shrunk minimums:** a fill whose fee pushes it below `min_notional` is refused, not settled.
- **Restart:** the fee appears in the replayed state.
- **CRITICAL gate:** full suite, independent audit, and a successor registry record.

## Effect on EXP-001

Trades before the change stay fee-free. Trades after it pay the fee. The report's estimated-fee line keeps both periods comparable, because the verdict is always taken on the net after estimated fees.

## Owner decisions needed

- **D1.** Approve the change (CRITICAL: settlement accounting).
- **D2.** Rate: 0.001 per side (public base rate; recommended until the account tier is known), or another figure.
