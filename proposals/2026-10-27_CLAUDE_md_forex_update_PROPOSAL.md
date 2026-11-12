# CLAUDE.md update for the forex pivot — PROPOSAL for the owner

**Status:** PROPOSAL only. CLAUDE.md is the owner's project doctrine. The agent has not edited it: an agent may never
change its own rules or roadmap. The owner applies the text below or rejects it.

**Why:** On 2026-10-25 the owner decided "Atlası değiştiriyoruz cripto değil forex yapacağız" and "Kriptoyu kaldır".
Since then, Tasks 018–026 have made FOREX (MetaTrader 5 demo, PAPER only) a full market in the code.
CLAUDE.md still describes Atlas as a crypto platform, which is a CONFLICT:

| Item | Content |
|---|---|
| Expected | CLAUDE.md describes the market Atlas is being built for. |
| Actual | Line 4 says "AI-native crypto investment/research/execution platform". |
| Evidence | Registry v5.102–v5.109; `ATLAS_MARKET` = CRYPTO \| FOREX in `core/atlas_config.py`; policy manifest v5. |
| Impact | A new session reads crypto as the product. The forex rules (sessions, margin, shorts) are not in the doctrine. |
| Decision required | The owner accepts, edits or rejects the replacements below. |

Nothing below changes any authority. `production_authority=NONE`, `live_authority=DENIED` and the ladder (Paper → Shadow
→ Small Live → …) stay exactly as they are.

## Proposed replacements

### 1. "What Atlas is" (line 4)
Replace:
> Atlas is an AI-native crypto investment/research/execution platform.

with:
> Atlas is an AI-native forex investment/research/execution platform (owner decision 2026-10-25: crypto → forex;
> registry v5.102). The market is MetaTrader 5, with demo accounts and market data only. CRYPTO remains in the code
> as the default `ATLAS_MARKET` until Task 020 removes it, after the owner's MT5 verification.

### 2. Decision flow (line 24)
Replace "… → Execution Manager → Exchange" with "… → Execution Manager → Venue (MT5 demo, market data only;
PAPER fills)".

### 3. New subsection under "Financial / migration safety"

> **Forex invariants (Tasks 018–026; registry v5.102–v5.109; policy manifest v5).** Never weaken any of these without
> a new ratified manifest:
> - FOREX uses its own state directory, named `forex` (and `shadow` for the BOOK fill), and never shares the crypto
>   state.
> - The FOREX book is the schema 3 margin book at leverage 2, created with
>   `tools/bootstrap_financial_state --leverage 2`. It is never migrated from a crypto book.
> - Margin = notional / 2. New risk spends only cash less any unrealized loss.
> - Loss limits (daily loss, drawdown, Kelly/volatility) are never scaled by leverage. Only notional exposure ceilings
>   are.
> - Stop-out at a margin level of 100 % or below: everything is closed, largest loss first, never on a stale price.
> - The session is open Sunday 17:00 to Friday 17:00 New York time. Christmas and New Year are closed.
> - No new risk in the last 60 minutes before a close. Open positions are closed 30 minutes before a close.
> - Shorts exist only on the margin book. A SELL of a pair not held opens a short, and a BUY covers it.
> - A short passes every new-risk gate a long does. A cover is never blocked by a new-risk gate.
> - CRYPTO never shorts.

### 4. Directory map
Add `atlas_finance` (`forex/`: instruments and sessions; `market_data/mt5_provider.py`) and `governance` to the
list.

## Not proposed (left to the owner)
- Whether to keep the "crypto" wording until Task 020 removes the crypto code.
- Whether the Phase 0–10 roadmap text needs any forex-specific note. The agent does not edit the roadmap.
