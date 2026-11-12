# Proposal v1.0: staged entries and exits, protective stop, bucket allocation

| Field | Value |
|---|---|
| Status | **APPROVED by the owner 2026-09-28** (registry v5.32): recommended parameters. Part D replaced by the owner's capital sleeves: LOW 50% / MEDIUM 35% / HIGH 15% of capital across all symbols. Implemented in `tools/backtest_replay.py`; the runtime waits for the backtest results. |
| Tier | CRITICAL: it changes how positions are opened, grown and closed (execution + risk). |
| Why it is not auto-decided | The delegation covers recommended options, but trading-behaviour changes need owner approval (CLAUDE.md "ask when production behavior changes significantly"; decision-log mandate). |
| Authority | PAPER only. `live_authority=DENIED` unchanged. |

## Owner request (2026-09-28, verbatim)

> "alım yapınca aşamalı alım satım mesela yükseleceğini düşünüyorsa yavaş yavaş satsın tekte satmasın düşeceğini düşünüyorsa belli bir limitten sonra hepsini satsın beklemesin hemen de satmasın düştüğü gibi ayrıca tüm parayı aşamalı olarak alım yapsın mesela orta risk yüksek risk ve düşük risk sonra düşük risk ve orta riske daha çok pay ayırsın yüksek riske az pay"

## Today (FACT, from the code)

- **Entry:** one BUY per symbol, the full sized allocation at once. A second BUY on a held symbol is refused (`DUPLICATE_OPEN_POSITION`, `core/risk_engine.py`).
- **Exit:** only a SELL decision with confidence ≥ 60 (ExecutionManager gate), and it exits in full. There is **no stop-loss, no take-profit and no trailing stop** in the runtime path.
- **Allocation by bucket:** already LOW 40%, MEDIUM 25%, HIGH 10% of capital per position, and exposure ceilings 60 / 40 / 20% (`_default_buckets`). This already matches "more to LOW/MEDIUM, less to HIGH". While EXP-001 runs, experiment admissions are sized as HIGH (10%), by the owner's decision in v5.22.
- **Partial sells:** the accounting supports them (entry fees pro rata, tested in v5.23).

## Proposed design (recommended numbers)

### A. Staged entry (scale-in): "tüm parayı aşamalı olarak alım yapsın"

- The bucket's allocation is split into **3 tranches: 40% / 30% / 30%**.
- **Tranche 1** is placed at admission, exactly as today, through Risk → Capital → Execution.
- **Tranches 2 and 3** are placed only when all of these hold:
  1. a new BUY decision passes the same gates;
  2. the price is **not below** the average entry. This means adding on confirmation, never averaging down into a fall;
  3. at least **15 minutes** have passed since the previous tranche.
- The sum of the tranches can never exceed the bucket cap, and every tranche is a separate risk-checked, reserved and journaled request.

### B. Staged exit when a rise is expected: "yavaş yavaş satsın, tekte satmasın"

When the position is in profit:
- sell **1/3 at +1.5%**;
- sell **1/3 at +3%**;
- let **the rest run with a trailing stop 1.5% below the highest price since entry**, or close it on a SELL decision.

Take-profits are measured from the average entry, net of fees.

### C. Protective full exit when a fall is expected: "belli bir limitten sonra hepsini satsın, beklemesin, hemen de satmasın"

- **Hard stop at −3% from the average entry, confirmed by 2 consecutive closed 1-minute candles below it.** One wick does not trigger it ("hemen de satmasın"). Once confirmed, **everything is sold at once** ("beklemesin").
- A SELL decision with confidence ≥ 60 still exits in full, as today.

### D. Bucket allocation: "düşük ve orta riske daha çok, yüksek riske az"

- **No change recommended:** LOW 40% > MEDIUM 25% > HIGH 10% already implements it.
- Optional, if the owner wants a stronger tilt: LOW 40 / MEDIUM 30 / HIGH 5. That shifts risk and needs explicit approval.

## Where it goes (existing architecture, no new phase)

| Part | Component | Change |
|---|---|---|
| Tranche cap and add-ons | `core/risk_engine.py` | Allow an add-on BUY on a held symbol only as tranche 2/3, capped by the bucket's remaining allowance. The duplicate refusal stays for everything else. |
| Stop / take-profit / trailing monitor | `core/market_loop.py` | Each cycle, check held positions against closed candles. Emit **reduce-only** SELL requests through the normal Risk → Execution path. No AI involvement. |
| Partial sells | `core/execution_manager.py`, portfolio foundation | Already supported and tested; reused. |
| Position state (tranche count, peak price) | durable financial state | A new field. **Migration check needed:** idempotency, resume and replay (CLAUDE.md financial/migration checklist). |

## Validation plan (before any runtime change)

1. Implement the rules first in `tools/backtest_replay.py`, the research replay of the real chain. Compare against today's behaviour on the owner's data: net P&L after fees, max drawdown, number of trades.
2. Then the runtime change as a CRITICAL package: tests for every exit path (stop confirmation, wick immunity, ladder, trailing, SELL override), restart/replay idempotency, and fee accounting. After that, an independent audit and a full suite run.
3. PAPER only. It is observed live in paper before any further step.

## Parameters to approve

| Parameter | Recommended | Alternative |
|---|---|---|
| Entry tranches | 3 × (40/30/30), add only on confirmation, ≥ 15 min apart | 2 × (50/50) |
| Take-profit ladder | 1/3 at +1.5%, 1/3 at +3%, rest trailing 1.5% | 1/2 at +2%, rest trailing 2% |
| Hard stop | −3% from average entry, 2 closed candles to confirm, then sell everything | −2% (tighter) / −5% (looser) |
| Bucket allocation | unchanged (40/25/10) | 40/30/5 |
| Order of work | backtest first, then runtime | runtime directly (not recommended) |

## Risks

- A stop plus confirmation candles can still exit into a V-shaped rebound. That is accepted as the cost of capital protection.
- Scale-in on confirmation buys higher than the first tranche. That is the intent (trend confirmation), and it is capped by the bucket.
- More orders mean more fees: at 0.1% per side, each extra tranche and ladder step costs fees. The backtest measures whether it pays.
