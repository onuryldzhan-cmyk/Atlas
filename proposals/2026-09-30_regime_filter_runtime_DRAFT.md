# DRAFT: regime filter in the runtime (BUY only in TREND_UP)

**Status: DRAFT.** Waiting for evidence. Nothing is implemented. This is a CRITICAL change: it touches the decision → execution path.

## Evidence so far

The owner's 20-coin, 30-day, 3-window replay (registry v5.75):

| Variant | Net P/L per window | Max drawdown per window |
|---|---|---|
| Reference | +73.61 / −239.26 / +36.09 | 158 / 314 / 262 |
| Regime filter | −48.14 / +301.10 / +466.92 | 150 / 164 / 240 |

The verdict is **NOT PROVEN**:
- the filter loses window 1;
- trade counts were not printed.

## Bar to clear before this proposal is filed (decided in advance, so it cannot be moved after seeing the data)

1. `strategy_compare --only rejim,aşamalı` (prints n = closed/open) shows the regime filter beating the reference in **at least 2 of 3 windows**, with **drawdown no worse in any window**.
2. The filter has **at least 30 closed trades in total** across the windows. Fewer is an anecdote.
3. The same holds on a **second, non-overlapping period**, for example `--days 60` with the first 30 days excluded, or a later rerun. One period can be luck.

If any item fails, the draft stays a draft, and the lesson is recorded as NOT PROVEN.

## Runtime design (only if the bar is cleared)

- **Where:** a new gate in the market loop **before** the risk engine, that can only turn BUY into HOLD. It never creates a BUY, never touches SELL, and never changes confidence (NB-4). The flow stays Decision → Risk → Capital → Execution.
- **Input:** `tools/regime_engine.classify` over the closed 1-hour bars the market loop already holds.
  - The candle buffer (`RECENT_CANDLE_LIMIT=240`, 1-minute candles) is only 4 hours, which is not enough for EMA50 on 1-hour bars.
  - So step 1 is a 1-hour closed-bar buffer: at least 60 bars per coin, observation only.
- **Failure mode:** too few bars or bad data give regime UNKNOWN, and UNKNOWN blocks new BUYs. This is fail-closed, the conservative direction.
- **Audit:** the reject reason `REGIME_NOT_TREND_UP` is appended like other gate rejections; the decisions page shows it.
- **Switch:** a config flag, default OFF until the owner signs; kill-switch semantics are unchanged.

## Tests required

- A BUY in TREND_UP passes unchanged.
- A BUY in SIDEWAYS / HIGH_VOL / PANIC / TREND_DOWN / TRANSITION becomes HOLD with its reason recorded.
- UNKNOWN (short history, a zero price, NaN) blocks.
- SELL and position exits are never affected.
- Confidence is identical before and after the gate.
- With the flag OFF, behaviour is byte-identical to today.
- Replay and runtime use the same `classify` function.

## Gates

Owner signature → implementation → full test suite → independent audit → fix → re-test → paper observation for at least 2 weeks → review.
