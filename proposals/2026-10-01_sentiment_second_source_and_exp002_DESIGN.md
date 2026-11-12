# B + C: EXP-002 and a second sentiment source (owner choice "B ve C birlikte", 2026-10-01)

## Why
On 2026-10-01 Atlas opened no trades. Confidence was 56–64, against floors of MEDIUM ≥ 70 and HIGH ≥ 80. Two reasons:
- The macro agent votes SELL on every coin (US 10Y yield rising).
- The sentiment agent abstains, because Fear & Greed is in the neutral band.

NB-5 rightly divides by the expected 5 agents, so an abstention never counts as agreement.

## B: EXP-002 (IMPLEMENTED, OFF)
- `core/risk_engine.py` `EXP002_PAPER_CONFIDENCE_EXPERIMENT`:
  - MEDIUM bucket only; HIGH stays at 0.80.
  - Floor 0.62, above EXP-001's 0.60.
  - 30 admissions.
  - Window 2026-10-02 to 2026-10-16 UTC.
  - Positions are sized with HIGH-bucket limits (smaller).
  - PAPER only.
  - The cap is counted durably: the audit log and the ledger, taking the larger.
- `AtlasApplication(paper_confidence_experiment_id=...)` selects the experiment. An unknown id attaches nothing.
- **Still OFF.** `main.py` keeps `paper_confidence_experiment=False`.
- **Owner switch-on**, two literals in `main.py`:
  - `paper_confidence_experiment=True`
  - `paper_confidence_experiment_id="EXP-002"`
- The window is fixed in advance. If it is switched on after 2026-10-16, it admits nothing; a new window is a new governed decision.
- Tests: `tests/test_exp002_paper_confidence_experiment.py`.
- **Success measure, fixed in advance:** after 30 admissions or at the window end, net expectancy after fees is compared with the reference. Fewer than 30 closed trades is INSUFFICIENT, and the floor goes back.

## C: second sentiment source (DESIGN, needs the owner's source choice)
| Candidate | Cost / key | Licence | Note |
|---|---|---|---|
| **Binance USDⓈ-M funding rate** (`https://fapi.binance.com/fapi/v1/premiumIndex`, public) | free, no key | Binance API Terms (the provider Atlas already uses) | Derivatives crowd positioning: strongly positive = crowded long (contrarian caution), negative = crowded short |
| Binance long/short account ratio (`/futures/data/globalLongShortAccountRatio`, public) | free, no key | same | positioning per coin |
| CoinMarketCap Fear & Greed | API key | CMC terms | would need a secret on the owner's machine (environment variable only) |

**Recommendation:** Binance funding rate, per coin. It needs no key, and Binance is already the market-truth provider. Note that `fapi.binance.com` is a new host. It must be added to `config/data_sources.json` first, otherwise the registry test fails.

**Rules (decision intelligence, NB-4 / NB-5):**
- It is a **separate sixth evidence item inside the sentiment vote**, not a new agent, so the roster stays 5 (NB-5).
- The vote uses funding only when it is outside a neutral band fixed in advance: |funding| ≥ 0.03 % per 8 h. Inside the band, the agent abstains as today.
- Missing, stale or malformed data means abstain. It never votes, and confidence never rises because data is missing (NB-4).
- It can only change the *sentiment* vote. It never bypasses Risk, Capital or Execution.
- Tests are required for: missing, stale, malformed, extreme and neutral data; F&G and funding disagreeing; the NB-4 removal test; the NB-5 roster test.

## Order
1. The owner picks the source (recommended: funding rate).
2. Register the host, write the provider with tests, then wire it behind a flag that defaults OFF.
3. An independent audit (CRITICAL: decision intelligence).
4. The owner switches it on. Then, separately, the owner decides on EXP-002.

## Successor note after the audit (2026-10-01, audit F-4 / F-1)
**What the code does now:**
- Funding is **not** a sixth evidence item. It is consulted only when Fear & Greed is NEUTRAL.
- It may only produce an agreeing **BUY**: CROWDED_SHORT with a BULLISH trend.
- Every other reading abstains.

**Why the design changed:** the audit's F-1 showed that `AgentFusion.fuse()` turns a dissenting HOLD/SELL into *more* confidence for the winner than an abstention gives.

**Order of switch-on:**
1. EXP-002 alone, with funding OFF, is approved.
2. Funding, after the owner accepts F-2. A single funding BUY can lift a typical BUY past MEDIUM 0.70.
