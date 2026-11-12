# File comparison 01: Atlas order lifecycle vs NautilusTrader (2026-09-30)

**Source.** The NautilusTrader source was cloned from GitHub (sparse checkout of `crates/model/src/orders/mod.rs`) because nautilustrader.io is blocked from the cloud.
- **Licence:** LGPL-3.0, verified in its LICENSE file.
- **Conclusion from the licence:** no code is copied. Only the *rules* are compared, and Atlas implements them in its own code.

## What Nautilus's transition table teaches

| Nautilus behaviour (mod.rs transition table) | Atlas before | Atlas now (`core/order_lifecycle.py`, not yet wired) |
|---|---|---|
| Denied → Submitted / Accepted / Filled does not exist | No order state machine; `status_implies_success` treats OPEN / PARTIALLY_FILLED as success | DENIED is terminal; fills are refused |
| **Canceled → Filled is a "real world possibility"** (cancel / fill race) | Not modelled (PAPER fills are instant) | Late fill after cancel is recorded with `LATE_FILL_AFTER_CANCEL`, never dropped |
| PendingCancel and PendingUpdate are in-flight states; Accepted can overtake a cancel rejection | — | PENDING_CANCEL with fills and ACKNOWLEDGED allowed |
| FillVoided (a venue busts a fill) | — | **Gap:** not modelled; needed before live |
| Submitted → Filled directly (fill-or-kill / immediate-or-cancel) | — | Allowed |
| External orders (Initialized → Accepted / Canceled) for reconciliation | Reconciliation tool exists (`tools/reconcile_execution_authorities.py`) | UNKNOWN → RECONCILING → venue-confirmed only |

## Atlas-specific rules kept

- An unknown outcome is never "failed": it goes UNKNOWN → RECONCILING. This matches Atlas's existing COMMIT_STATUS_UNKNOWN halt.
- Decimal quantities, positive and finite.
- No overfill.
- A fill id is counted once.

## Wiring step (CRITICAL; next)

ExecutionManager keeps its journal and idempotency authority. The state machine becomes the validator of every status it journals. It goes behind a flag, with the recovery tests re-run and then an independent audit.

## Still to compare

- LEAN: fill, slippage and fee models (for F-4).
- CCXT: order status mapping (for 6C).
- Riskfolio / PyPortfolioOpt: covariance (for F-2 and portfolio risk).
