# Shadow stage: design, not implemented (2026-10-01)

**Status:** DESIGN ONLY. CRITICAL (it touches the execution boundary). Coding needs owner approval and then an independent audit. Live authority stays DENIED throughout: Shadow never sends an order.

## Where it sits
- Ladder (CLAUDE.md, 2026-09-21): Paper → **Shadow** → Small Live → Controlled Autonomous → Advanced Autonomous.
- `config/environments.json` already declares SHADOW: `real_money: false`, `market_data: live`, `state_directory: separate`, `may_submit_orders: false`, entry `NOT IMPLEMENTED`.

## What Shadow adds over today's PAPER (the honest difference)
Today's PAPER already uses live market data, but it **fills at the candle price**, with modelled fees and 5 bp modelled slippage. That flatters results. Shadow answers a different question: *had this been a real order on the real venue, what would have happened?*

| | PAPER (now) | SHADOW (proposed) |
|---|---|---|
| Decision chain | Decision → Risk → Capital → Execution | identical, unchanged |
| Order | virtual, candle price | the **exact venue order** that would be sent (symbol rules, step and tick size, min notional, order type), built and validated, then **not submitted** |
| Fill estimate | candle close ± modelled slippage | **real order-book price at decision time** (public read-only depth endpoint); a size larger than the top levels is reported as partial or unknown |
| Latency | ignored | decision → would-be-submit time measured |
| Measured result | P/L under a model | *shadow vs. paper gap*: how much PAPER over- or under-states the result |
| State | normal state directory | **separate** state directory (environments.json); it never touches the PAPER book |

## Safety design
1. **No order path.** The Shadow executor has no submit method at all; tests assert that no private or signed endpoint is ever called. No API key is read in Shadow.
2. **Separate state.** A separate state directory and its own instance lock. Shadow can never write the PAPER or the future live book.
3. **Read-only market data.** Only public endpoints, registered in the data source registry (an unregistered host fails a test).
4. **Fail closed.** If the order book is missing, stale or malformed, the shadow fill is UNKNOWN and is never estimated.
5. **Default OFF**, behind a flag. Entry only via a `main.py` literal, like the other switches.

## Exit criteria to Small Live (fixed in advance, so they cannot be moved after seeing the data)
- At least **4 weeks** of Shadow alongside PAPER.
- At least **50** shadow round trips.
- Median shadow-vs-paper gap is measured and stated; the strategy's net expectancy is still **positive after the shadow fill model**.
- **Zero** order-lifecycle violations and **zero** shadow attempts to reach a private endpoint.
- Then: an independent audit, then the owner decides on Small Live. Small Live has its own capital cap and kill switch and is a separate decision.

## Build steps (each step is tested and needs owner approval)
1. A read-only order-book source (public depth endpoint), registered, with tests for stale and malformed data.
2. `ShadowExecutor`: builds and validates the venue order and records the would-be fill. No submit capability.
3. A shadow vs. paper report on `/postmortem` (read-only).
4. Independent audit.

## Decision required
The owner approves step 1 (read-only order-book source), or defers Shadow until PAPER has run for a week with the new switches.
