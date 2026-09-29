# Staged entries + capital sleeves in the runtime: plan (owner approved the direction 2026-09-29)

**Classification:** CRITICAL (execution, risk, financial state). Approved **scope and order only**. Each step below goes through the full gate before it runs:
1. tests, including failure cases;
2. regression;
3. an independent audit;
4. the owner's signature on that step;
5. PAPER-only observation for ≥30 trades.

**Evidence:** `proposals/2026-09-29_evidence_after_first_owner_runs.md`.
- On 20 coins, staged + sleeves cut the maximum drawdown 3–7× in every window.
- It is a risk frame, not a profit engine. The net result was still negative (−101 $ against −177 $ for the reference).

**Parameters:** as approved for the replay in registry v5.32 (`governance/ATLAS_STAGED_ENTRY_EXIT_PROPOSAL_v1.0.md`, `tools/backtest_replay.py`):
- tranches 40 / 30 / 30 %, at least 15 min apart, added only at or above the average entry;
- take-profit 1 at +1.5 % (sell ⅓), take-profit 2 at +3 % (sell ½ of the rest);
- trailing stop 1.5 % after take-profit 2;
- hard stop −3 %, confirmed by 2 closed candles;
- sleeves: LOW 50 % / MEDIUM 35 % / HIGH 15 % of capital across all coins.

## Steps: smallest first, each separately reversible

| Step | Change | Why this order | Touches |
|---|---|---|---|
| S1 | **Capital sleeves.** A BUY is refused with `SLEEVE_FULL` when its risk bucket's open cost plus the new order would exceed the bucket's share of equity. | Pure risk reduction: it can only refuse more, never allow more. It is the smallest change, and it also addresses the `max_positions` pressure without raising exposure. | `core/risk_engine.py` (one more rejection reason); state is read from the existing portfolio foundation. |
| S2 | **First tranche only (40 %).** The first BUY on a coin takes 40 % of today's target size. | Also risk-reducing: smaller positions. No new order types. | Sizing in the execution request path. |
| S3 | **Protective exit monitor.** Hard stop (confirmed), then take-profit 1 / 2 and trailing, emitted as SELL requests that go through the same Decision → Risk → Capital → Execution chain. | Needs partial sells: reduce-only intent already exists (`Reduce-only intent re-derived …` in the owner's logs). Partial-quantity support must be verified first (UNKNOWN). | Exit monitor in the market loop; reduce-only quantity. |
| S4 | **Add-on tranches (30 / 30).** | The largest change: `DUPLICATE_OPEN_POSITION` has to allow an explicit, governed add-on. Last, and only if S1–S3 hold up in PAPER. | Idempotency identity, position aggregation, recovery (K0–K6 crash-recovery tests must cover add-ons). |

## Invariants every step must keep

- AI decisions never bypass Risk / Capital / Execution Manager. The exit monitor only creates requests.
- Idempotency, crash recovery (K0–K6) and durable financial state are unchanged in meaning. Migration-safety checklist for any state shape change: idempotency, resume, retry, ordering, duplicates, partial state, rollback.
- `live_authority=DENIED`; PAPER only.

## Next exact action

S1 is implemented in a separate change with tests:
- bucket at its limit;
- bucket empty;
- unknown bucket → refuse;
- state unreadable → refuse;
- SELL never blocked;
- sleeve math with fees.

Then an independent audit, then the owner signs S1.
