# ATLAS CHECKPOINT

## Objective

Owner brief 2026-09-25, Part H: complete the 5-agent roster by giving the
`macro` and `risk` (`market_risk`) agents real providers. Do this without
changing `AgentFusion.fuse()`, the confidence calculation, or the NB-4/NB-5
protections. If no free, keyless, unambiguous option exists, propose
instead of implementing.

**Status: PART H, AWAITING OWNER DECISION.** No code was changed.

## Template: how sentiment is wired (read in this session)

The chain runs from provider to fusion in four steps.

1. **Provider.** `atlas_finance/market_data/fear_greed_provider.py`
   (`FearGreedProvider`, `classify_fear_greed_band`) does the lazy fetch and
   caches the result. It fails closed. Its construction does no I/O.
2. **Composition root.** `core/application.py:76` imports the provider and
   injects it into MarketLoop as `sentiment_provider`.
3. **MarketLoop.**
   - Holds the provider from `core/market_loop.py:187-198`.
   - Builds `sentiment_input` in `_sentiment_input()` at
     `core/market_loop.py:1916-1970`.
   - Any provider exception becomes `_sentiment_unavailable(reason)`.
4. **WorldAnalysisEngine.** `analysis/world_analysis_engine.py` sets
   `evidence_status["sentiment"]` to AVAILABLE only when a directional band
   exists. Otherwise it stays `UNAVAILABLE_NO_PROVIDER`. It emits
   `sentiment_score` only when the status is AVAILABLE. `macro` and
   `market_risk` are hard-coded to `UNAVAILABLE_NO_PROVIDER` at lines
   106-119.

The fusion contract, which stays unchanged:

- `ai/core/intelligence/agent_fusion.py` maps these status keys:
  - `macro` → `macro`
  - `risk` → `market_risk`
- It reads `macro_score` and `risk_score` only when the matching status is
  AVAILABLE.
- `MIN_PARTICIPATING_AGENTS = 3`, and the WEIGHTS roster has 5 entries.
- A new provider therefore only has to:
  - emit an honest `evidence_status`, and
  - emit a score in the same `[0, 1]` directional convention the other
    agents use.

What a new agent would touch:

- `core/application.py`, `core/market_loop.py`, and
  `analysis/world_analysis_engine.py`. That makes this cross-module and
  CRITICAL-tier.
- By precedent, a governance authorization record. Sentiment needed registry
  v4.66.

## Why this was not implemented

Every candidate below needs at least one decision that is the owner's to
make:

- **The vote mapping.** Fusion treats each agent's score as directional,
  where a higher score means more bullish. A risk signal such as high
  realized volatility or extreme funding is not naturally directional. Three
  mappings are possible:
  - vote bearish;
  - withhold, meaning AVAILABLE only in extreme bands, as sentiment does;
  - act as a confidence dampener. This option is excluded, because it would
    change the fusion logic, which is out of scope.
- **Thresholds and bands.** These are the same kind of threshold decision the
  owner made for sentiment (v4.66) and for S-3/M-2 (v4.73).
- **Staleness.** Some macro data is monthly (CPI), so a policy for how old a
  reading may be before it counts as AVAILABLE is a design choice.

## Candidate sources

These are **UNVERIFIED in this session.** They come from general knowledge,
and no network call was made. Each must pass the external-dependency
checklist (Discover → License → Security → Quality → Compatibility → Test)
before adoption.

### Macro

| Candidate | Key? | Cadence | Tradeoffs |
|---|---|---|---|
| M1. FRED API (St. Louis Fed): e.g. `DTWEXBGS` broad dollar index, `DFF` fed funds, `T10Y2Y`, `CPIAUCSL` | Free, **API key required** | Daily; CPI monthly | Authoritative and stable. The key must be handled under the secrets rules. Series lag 1 day or more. |
| M2. US Treasury yield-curve daily CSV (home.treasury.gov) | Keyless | Daily | Official. Rates only, no USD index. Publishes after the US close. |
| M3. DefiLlama stablecoin total supply (a crypto-native liquidity proxy) | Keyless | Daily or better | Directly crypto-relevant. It is a proxy, not "macro" in the rates/DXY sense. It is a third-party aggregator. |
| (Rejected) Yahoo Finance `DX-Y.NYB` | Keyless | Intraday | Unofficial endpoint and ToS risk. Breaks without notice. |

### Risk (`market_risk`)

| Candidate | Key? | Cadence | Tradeoffs |
|---|---|---|---|
| R1. Realized volatility from the candles Atlas already fetches | **No new source** | Per candle | Zero new dependency or network call. The methodology (window, bands, vote mapping) must be decided. It is partly correlated with the technical agent. |
| R2. Binance USDⓈ-M public funding rate / open interest (`fapi` `premiumIndex`, `openInterest`) | Keyless | Funding 8h, OI near-real-time | Crowding and leverage signal. Futures data for spot trading. Same venue, so failures are correlated. |
| R3. Deribit DVOL (BTC/ETH implied-volatility index), public API | Keyless | Near-real-time | Forward-looking. Covers BTC and ETH only, not SOL/XRP/BNB. |
| (Rejected) Coinglass liquidations | **Paid key** | Real-time | Cost and key handling. Binance `forceOrder` WS is keyless but needs a streaming client, which Atlas does not have. |

## Recommendation

- **risk:** R1 first. It needs no new data source and no new dependency,
  only a methodology decision. R2 is the second signal once R1 is proven.
- **macro:** M2 or M3 if the owner wants keyless. M1 if the owner accepts a
  free API key, since it is the most complete source.
- Both new agents should be AVAILABLE only in the extreme bands, as
  sentiment is. Neutral readings then withhold, and NB-4 holds by
  construction.

## Owner decisions needed

1. The data source per agent.
2. The vote mapping for risk: bearish-in-extreme-band, or withhold-only.
3. Bands and thresholds, and the staleness limit per source.
4. For M1, whether an API key is acceptable, and where it lives
   (environment variable only).
5. The governance authorization record, following v4.66.

## Files changed

This checkpoint only.

## Tests

None. No code changed. When this is implemented, the tests must cover:
missing evidence, provider failure, neutral-band withholding, NB-4
(removing the agent never raises confidence), and NB-5 (the denominator
stays at the 5-agent roster).

## Risks

None introduced.

## Next exact action

The owner answers decisions 1-5. After that, the implementation follows the
sentiment template exactly.
