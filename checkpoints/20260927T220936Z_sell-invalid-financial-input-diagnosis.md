# ATLAS CHECKPOINT — SELL `INVALID_FINANCIAL_INPUT` diagnosis (read-only)

## Objective
Owner brief (2026-09-28 local, branch `research/edge-validation`). The live dashboard showed `RiskEngine` rejecting SELLs with `INVALID_FINANCIAL_INPUT`: BTC/ETH/SOL/XRP SELL @ 85.4 around 2026-09-27T22:04Z, and BNBUSDT SELL @ 68.5 at 00:16:02Z. The performance panel shows 0 trades. The brief asked to:
- find where the code is raised,
- trace the real inputs from `C:\AtlasState\memory_data`,
- test the "SELL with no position" hypothesis,
- decide whether this is a bug or correct behavior,
- establish how often it has happened.

This was diagnosis only. No fix was made.

Classification: STANDARD investigation, read-only. It touches the risk/execution domain, but it changes no code and no state. Any follow-up fix is CRITICAL (see below).

## Completed — root cause (FACT, each with evidence)
1. **Raise site.** `core/risk_engine.py:449`: `decimal_value(request.requested_quote_allocation, ..., allow_zero=False)` raises `ValueError` for a zero allocation (`core/risk_engine.py:125-127`). That is caught at `:466`, and `INVALID_FINANCIAL_INPUT` is returned at `:467`. The same `try` block also catches a bad confidence, price, risk bucket or base_quantity. The replay in item 5 shows that allocation is the only field that fails here.
2. **Why the allocation is zero.**
   - Runtime SELLs are never sized. `MarketLoop` sizing returns early for anything that is not a BUY (`core/market_loop.py:1696`), so the request arrives with `amount=0.0` and `proposed_quote_allocation=None`.
   - `_derive_reduce_only` gives `False` when the symbol is not held (`core/execution_manager.py:2939-2947`).
   - `_requested_quote_allocation` therefore reaches its last branch and returns `Decimal("0")` (`core/execution_manager.py:3059-3062`).
   - The docstring there says this outright: an unsized, non-reducing SELL "resolves to zero, which RiskEngine refuses as INVALID_FINANCIAL_INPUT … selling a symbol that is not held is malformed" (`:3032-3035`).
   - A test pins this behavior: `tests/test_block5b_single_sizing_authority.py:372-380` `test_unsized_sell_with_nothing_held_is_malformed_not_unsized`.
3. **The real records.** `C:\AtlasState\memory_data\execution_idempotency.jsonl` (read-only) holds 22 records with this code, seq 27-36 and 61-75, excluding 63/68/73.
   - Every one is `action=SELL`, `amount=0.0`, `details.gross_exposure="0"`, `approved_allocation="0"`, `status=REJECT`.
   - Prices are positive and finite, for example BTC 84441.09 and XRP 1.5128.
   - Confidence values are 68.5 and 85.4. The risk bucket is `HIGH` at 00:15-00:16Z and `MEDIUM` at 22:04-22:06Z.
   - `audit/atlas_audit_events.jsonl` has the matching 22 `RISK_REJECTED` events.
4. **The "no position" hypothesis is CONFIRMED.**
   - `execution_financial_state.json` shows `positions={}` and `cash="10000.0"`. Its last write was 2026-09-15T20:25:33Z, which is before every observed instance.
   - `execution_transaction_journal.jsonl` was last written 2026-09-15T16:27:04Z, so no fill has been journaled since.
   - The newest `EXECUTION_COMPLETED` in the audit log is from 2026-08-13 (`r1`). No completion exists on 2026-09-26/27.
   - The book was therefore flat at every rejected timestamp. That agrees with `gross_exposure="0"` in each rejection.
5. **Disk-free replay.** This ran in the session scratchpad and used no `AtlasApplication` and no state directory. It called the real `ExecutionManager._derive_reduce_only`, `_requested_quote_allocation` and `RiskEngine.evaluate` with the recorded inputs.
   - Flat book, BTC/XRP @ 85.4 MEDIUM and BNB @ 68.5 HIGH: `(reduce_only=False, requested=0) → INVALID_FINANCIAL_INPUT`. This reproduces the audit record exactly.
   - Same BTC SELL, but with a held BTC position: `RISK_REDUCTION_APPROVED`. A real exit is not blocked.
   - Same flat BTC SELL with `amount=100`: `NON_RISK_REDUCING_SELL`. Confidence, price and bucket all pass validation, so allocation is the only failing field.
6. **The BNBUSDT timing discrepancy is explained.** At 22:04-22:06Z BNBUSDT was a BUY @ 56.38, refused `LOW_CONFIDENCE`. That refusal is an `EXECUTION_REQUEST_REJECTED` event, not a `RISK_*` event. So the dashboard's latest-risk-outcome line still showed BNB's most recent `RISK_REJECTED`, which is the 00:16:02Z SELL. This matches F5 in `20260927T220211Z_dashboard-execution-gates-critical-gate-closure.md`.

## Verdict
**Correct, fail-closed behavior. It is not a data or formatting bug.** No legitimate SELL is being rejected. Atlas is LONG-only, and nothing is held. With a position held, the same inputs are approved (item 5).

There is one real but minor defect: the reason code is misleading.
- The operator cannot tell "nothing to sell" apart from truly malformed financial input, such as a NaN price or confidence above 1. Both share `INVALID_FINANCIAL_INPUT`.
- On the runtime path, `NON_RISK_REDUCING_SELL` cannot be reached, because runtime SELLs are always unsized. Yet the `_derive_reduce_only` docstring (`core/execution_manager.py:2927-2929`) says a SELL of an unheld symbol "stays NON_RISK_REDUCING_SELL". That statement is true only for sized SELLs, and it conflicts with `:3032-3035`.
- Severity: **LOW**. It has no safety impact and fails closed. The cost is diagnostic quality only; it produced this investigation.

The 0-trades result has a different cause. SELLs cannot trade on a flat book. BUYs are stopped by `CONFIDENCE_BELOW_POLICY` (28 records) and `LOW_CONFIDENCE` (14 records), which is the N2 finding.

## Frequency / history
- The idempotency log (2026-08-07 → 2026-09-27T22:06Z, 76 results) has 22 occurrences, **all on 2026-09-27**, in two bursts:
  - 00:15:38-00:16:03Z: 10 records, 5 symbols × 2 candles, @ 68.5 HIGH.
  - 22:04:11-22:06:10Z: 12 records, 4 symbols × 3 candles, @ 85.4 MEDIUM.
- The earlier canonical-engine SELLs on 2026-09-26 (seq 3-11, 9 records) were stopped first by `RISK_ACCOUNTING_DAY_RECONCILIATION_REQUIRED`. That day check (`core/risk_engine.py:440`) runs before the allocation check. So the same condition was present but masked.
- The 2026-08-07 SELLs were `RISK_APPROVED` with `details=None`. They came from the pre-Phase-3 risk path and are not comparable.
- There are 0 hits in `logs/market_loop_telemetry.jsonl` (it does not record reasons) and 0 in `memory_data_backup_20260915/`.
- Conclusion: every canonical-engine runtime SELL on a flat book is refused this way, whenever the day gate lets it through.

## Files changed
- This checkpoint only. No code, test, state or governance file was touched. The operator state under `C:\AtlasState` was only read.

## Architecture decisions
- None. The existing 5B design decision ("unsized SELL of an unheld symbol is malformed") was confirmed as the implemented behavior. It was not changed.

## Tests
- None run, because there was no code change. The disk-free replay in item 5 is diagnostic evidence, not a test. The script is in the session scratchpad and was not committed.

## Current state
- Branch `research/edge-validation`, HEAD `8856881`. The pre-existing untracked and modified files are untouched.
- Authority unchanged: `production_authority=NONE`, `live_authority=DENIED`, `autonomous_deployment_authority=DENIED`.

## Known issues
- **LOW** misleading reason code, described under Verdict.
- **INFORMATIONAL**: `MarketLoop` sends bearish "SELL" decisions on flat symbols into `execute()`, which produces a stream of audit rejections (22 on 2026-09-27). This is a signal-routing question: should a SELL on a flat book be treated as HOLD? It is not an execution defect.
- **INFORMATIONAL**: the operator audit log contains `r1`/`r2` events dated 2026-08-13 (`EXECUTION_COMPLETED r1`). Their request ids look test-shaped, which suggests an old test or reproduction once wrote into the real state. This predates the state-isolation rule. It was not investigated further (out of scope).

## Risks
- If the reason code is left as is, a genuine malformed-input incident on the SELL path would be hidden among routine "nothing to sell" rejections.

## Remaining work / recommended follow-up (owner decision; not implemented)
- **REM (CRITICAL by rubric floor, small diff; recommended DEFER, not a blocker):** give "unsized SELL, nothing held" its own reason code. The candidates are the existing `NON_RISK_REDUCING_SELL`, or a new `NO_POSITION_TO_SELL` emitted in `risk_check` before the engine runs and before any reservation. Also reconcile the two conflicting docstrings.
  - This reverses a pinned 5B test and a recorded design decision, so it needs owner approval first.
  - It must keep: fail-closed behavior, no reservation, and malformed allocations (NaN or negative) still reported as `INVALID_FINANCIAL_INPUT`.
- **Deferred Improvement (What/Why/Where):** suppress or relabel SELL signals on flat symbols in `MarketLoop` routing. This belongs to the Decision→Execution routing phase. It is a behavior change, so it is DEFER pending an owner decision.

## Next exact action
Owner decides: (a) accept as correct and close, (b) open the CRITICAL reason-code REM, or (c) open the routing Deferred Improvement. Until then, no code changes.
