# Independent Audit — F-3 / F-4 / M-1 and related changes (2026-09-30)

Mode: AUDIT. Branch: claude/exp001-on-owner-lineage (HEAD e8c7a3e). Auditor did not write the code. No source file modified.

## Tests run (exact)
- `pytest tests/test_order_lifecycle.py tests/test_f4_slippage_end_to_end.py tests/test_f3_mark_to_market_wiring.py tests/test_phase2_persistence_semantics.py tests/test_f3_unrealized_daily_loss.py tests/test_brain_mem_001.py tests/test_f4_paper_slippage.py` -> 44 passed.
- `pytest -k candle tests` -> 181 passed, 5966 deselected.
- Adversarial probes: `/tmp/claude-0/-home-user-Atlas/ed488b89-88cf-5587-bd7c-1e74806fd963/scratchpad/probe.py`, `/tmp/claude-0/-home-user-Atlas/ed488b89-88cf-5587-bd7c-1e74806fd963/scratchpad/probe2.py` (scratchpad, not committed).
- Full suite NOT run (UNKNOWN beyond the above).

## Verdicts
| Item | Verdict |
|---|---|
| 1. M-1 memory evidence / cache / caution | APPROVE_WITH_FIXES (A-1, A-4, A-5) |
| 2. F-3 unrealized P&L in daily loss | APPROVE_FOR_SWITCH_ON (A-7 informational) |
| 3. F-4 paper slippage | APPROVE_WITH_FIXES (A-3) — default 0 is safe; fix before bps>0 via untrusted config |
| 4. candle_processor NaN/inf guard | APPROVE_FOR_SWITCH_ON |
| 5. order_lifecycle (not wired) | APPROVE_WITH_FIXES before wiring (A-2, A-6) |
| 6. telemetry decision | APPROVE_WITH_FIXES (A-4b) |

No BLOCKING or HIGH findings.

## Findings
| ID | Sev | Location | Summary |
|---|---|---|---|
| A-1 | MEDIUM | ai/core/intelligence/trade_evidence.py:26-65 | An "Infinity" (or huge) gross_pnl record is accepted as valid and lifts the LOSING_EFFECT caution |
| A-2 | LOW | core/order_lifecycle.py:58-63 | Late-fill branch trusts `reason.startswith("fill ")`; a direct `transition("FILLED","fill x")` on a CANCELLED order writes a false history entry and bypasses the FILLED-needs-full-quantity check (status stays correct) |
| A-3 | LOW | core/execution_manager.py:2949-2961 | Slippage fails open: SELL with bps>=10000 (raw<=0) silently returns the UNSLIPPED price; NaN bps raises decimal.InvalidOperation inside paper execution |
| A-4 | LOW | core/market_loop.py:2309-2311, 2962-2975 | NaN/inf float confidence passes `isinstance(conf,(int,float))`; `json.dumps(allow_nan=False)` raises; the single try wraps the per-symbol loop so that cycle's remaining symbols' telemetry is silently dropped (debug log only) |
| A-5 | LOW | core/brain.py:344-347 | Cache key (mtime_ns, size) serves stale content when a same-size rewrite keeps mtime (coarse-timestamp FS, or utime restore); cached dicts are shared with callers (mutation would poison cache) |
| A-6 | INFORMATIONAL | core/order_lifecycle.py:24-33 | Late-fill-after-terminal only modelled for CANCELLED, not EXPIRED (same venue race) |
| A-7 | INFORMATIONAL | core/market_loop.py:2325 | Freshness measured from candle open_time; with 1m candles (market_loop.py:1090) and 300s max age this is fine, but a longer interval would make every mark stale (fail-closed: all BUYs rejected UNREALIZED_PNL_UNKNOWN). Not zero-filled — correct direction |

### A-1 (MEDIUM) — malformed evidence can remove caution (NB-4 spirit)
Evidence: `net_pnl` uses `Decimal(str(record["gross_pnl"]))`, which accepts "Infinity"; no finiteness check. Probe: 12 records gross_pnl=-5 -> effect -0.05; add one record gross_pnl="Infinity" -> effect 0.0.
Impact: a single corrupt archive line removes the losing-book caution and BUY confidence rises; the module docstring and _trade_book docstring promise malformed -> fail closed. ("NaN" is caught: its comparison raises outside the try and _trade_book fails closed.)
Remediation: in net_pnl reject non-finite entry/gross (raise ValueError), so symbol_evidence returns MALFORMED_ARCHIVE_RECORD -> last-good / fail-closed path. Add a test.
Repro: `/usr/bin/python3.13 /tmp/claude-0/-home-user-Atlas/ed488b89-88cf-5587-bd7c-1e74806fd963/scratchpad/probe.py` (lines "losing", "with Infinity").

### A-2 (LOW)
Evidence: probe.py: order acknowledged, fill 4/10, PENDING_CANCEL, CANCELLED, then `transition("FILLED","fill forged")` -> status CANCELLED, history last = ('CANCELLED','FILLED (LATE_FILL_AFTER_CANCEL)'), filled 4. Late fill via apply_fill (6) -> FILLED 10; overfill still rejected (checked before the branch). So apply_fill on CANCELLED cannot overfill, and partial-then-cancel status ends CANCELLED correctly.
Impact: audit history can claim a fill that never happened; not wired today.
Remediation: make the late-fill path private to apply_fill (e.g. internal flag) instead of a reason-string prefix; reject public transition out of CANCELLED.

### A-3 (LOW)
Evidence: probe2.py: paper_slippage_bps=10000, SELL 100.0 -> 100.0 (no slippage); bps=NaN -> InvalidOperation.
Impact: misconfiguration makes paper fills more optimistic than configured (fails open) or throws in the paper path. Default 0 unaffected; BUY sizing reads filled_price after hydration (execution_manager.py:4686) so quantity/fee flow from the slipped price; e2e test covers reservation within approval.
Remediation: validate bps finite and 0<=bps<10000 at configuration; if raw<=0 reject the fill rather than returning the unslipped price.

### A-4 (LOW)
Evidence: `json.dumps({"c": float("nan")}, allow_nan=False)` raises ValueError (probe.py); `_telemetry_decision` passes any float; record built inside the loop within one try (market_loop.py ~2896-2975).
Remediation: `conf if isinstance(conf,(int,float)) and math.isfinite(conf) else None`; optionally per-symbol try.

### A-5 (LOW)
Evidence: probe2.py writes {"gross_pnl":"-5"}, rewrites same length with "+5" and restores mtime via os.utime -> second read still returns "-5".
Remediation: add st_ino / st_ctime_ns to key (ctime cannot be set by utime), and return copies of records.
Also: _closed_cache and MemoryAdapter._last_good have no lock; _last_good grows by one entry per symbol (bounded by universe) — acceptable, not a finding.

## Checked, no defect found
- F-3 flag OFF: _mark_to_market returns None before calling the provider; risk_engine only reads unrealized_pnl under the flag -> prior behaviour preserved.
- F-3 reduce-only: `reducing` branch returns APPROVE (risk_engine.py:627-632) before the unrealized check (661) -> exits allowed when flag ON.
- F-3 missing/stale/non-positive price -> symbol omitted -> None -> UNREALIZED_PNL_UNKNOWN (never zero). Float rejected in RiskState; non-finite total -> None. mark_prices converts via Decimal(str(close)); NaN close fails `close > 0`.
- M-1 NB-4: unreadable archive with no history -> LOSING_EFFECT (fail closed); with history -> last good. _memory_buy_caution only lowers confidence; NaN effect leads to confidence 0 (conservative). NB-5 not applicable (no roster denominator in these changes).
- order_lifecycle: overfill impossible, replayed fill ids ignored, DENIED terminal.
- candle_processor: NaN/inf rejected (181 candle tests pass).
