# Independent Audit — Runtime changes live via main.py, 2026-10-01

Mode: AUDIT (CLAUDE.md). Auditor: independent sub-agent. No repository file changed except this report. Nothing committed.

Scope: commits since 2026-10-01 that reach the runtime via `main.py`:
`a3e9820` (F-3 / S1 / F-4 switch-on), `8662bf8` + `f83939b` (order lifecycle observe), `82254ff`/`2a32633`/`324c995` (risk-bucket sidecar),
`324c995`/`ffb5c54`/`a63eca4`/`f878ddd` (event contract, `/api/events`, HQ), `3ffb5b7`/`9028b27`/`cefaa5e` (tools/agent_cycle).
Prior reports `INDEPENDENT_AUDIT_S1_STEP2_2026-10-01.md` and `INDEPENDENT_REAUDIT_S1_STEP2_2026-10-01.md` not repeated.

## Verified facts
- Wiring: `main.py:523-528` passes `count_unrealized_in_daily_loss=True, sleeves_enabled=True, paper_slippage_bps="5", order_lifecycle_observe=True`.
  `core/application.py:919-927` puts F-3 and S1 into the single `RiskPolicy` instance (shared with `PositionSizingService`);
  `application.py:838-845` sets `execution.mark_price_provider`, `paper_slippage_bps`, `order_lifecycle_observe`, `position_risk_buckets`.
  No switch is silently dropped. `paper_slippage_bps` is range-checked [0,100] at construction and again (fail-closed) in `_paper_fill_price`.
- `EXECUTION_MODE = "PAPER"` (`main.py:60`). None of the changes adds an order path; the slippage applies only inside the PAPER branch. No change touches live authority. Live authority remains DENIED as far as these diffs are concerned.
- Exits: the reduce-only branch in `RiskEngine.evaluate` returns before the sleeve and daily-loss checks (`risk_engine.py:663-668`). `_mark_to_market` and `_recorded_risk_bucket` catch all exceptions and return `None`, so building the risk state cannot raise because of them. **None of the four switches can block an exit.**
- Slippage vs reservation: a BUY fill quantity is sized inside the approved ceiling *after* the slipped price is known (`_execute_paper_buy`, `execution_manager.py:4728-4740`). A slipped price cannot make notional exceed approval.
- No double count: the sleeve check uses cost-basis `quote_exposure` against `current_equity` from the realized-only risk state store. Unrealized P&L is used only in the daily-loss gate.
- `execute()` wrapper (`execution_manager.py:1300-1322`): it returns the `_execute_decision` result object unchanged. `observe_outcome` only reads it. Every exception is caught. There are no recursive `self.execute(` calls, so there is no double recording. `observe_outcome` maps only `PAPER_EXECUTED` and `REJECTED`. `reject()` dicts carry no `filled_price`/`commit_outcome`, so the REJECTED branch gives no false positive.
- Tests run: `pytest tests/test_order_lifecycle_observe.py tests/test_owner_switches_2026_10_01.py tests/test_position_risk_buckets.py tests/test_s1_capital_sleeves.py tests/test_event_contract.py tests/test_hq_page.py tests/test_loopback_host_header_guard.py tests/test_agent_cycle.py` → **548 passed** (42 warnings).

## Findings

### F-A — HIGH — F-3 lets unrealized *gains* un-breach a breached daily-loss limit (less conservative than OFF; NB-4 class)
- Location: `core/risk_engine.py:696-707`
  (`loss = max(-(state.realized_daily_pnl + state.unrealized_pnl), ZERO)`).
- Evidence: reproduction script (scratchpad `f3.py`): capital 10 000, realized_daily_pnl −600 (6 % > 5 % limit), one open position unrealized +200, LOW BUY at conf 0.9.
  Flag OFF → `REJECT DAILY_LOSS_LIMIT_BREACHED`. Flag ON (live main.py setting) → `APPROVE RISK_APPROVED`.
- Impact: F-3 was approved as a tightening ("also count unrealized loss"). As implemented, paper profits on open positions offset realized losses. A day that has already hit the realized loss limit can admit new risk again. Switching F-3 on therefore makes some states *less* conservative than before. This breaks "Safety before profit" and is the same pattern as NB-4: a change in the evidence loosens the limit. No existing test or prior audit covers a positive unrealized value (grep of docs/audits and tests).
- Remediation: only an unrealized *loss* should count, e.g. `loss = max(-state.realized_daily_pnl, -(state.realized_daily_pnl + min(state.unrealized_pnl, 0)), 0)`. That makes F-3 ON at least as strict as OFF. Add a regression test where realized is breached and unrealized is positive, and a monotonicity test (ON ≥ OFF strictness).

### F-B — MEDIUM — F-3 makes one unpriced held symbol block ALL new risk portfolio-wide, with no bound
- Location: `execution_manager.py:3010-3031` (any position with no fresh price → `None`); `market_loop.py:2315-2329` (price must be fresh within 300 s of candle open_time and come only from `recent_candles`, i.e. polled symbols); `risk_engine.py:700-701`.
- Evidence: `recent_candles` is filled only for symbols the market loop polls (`trade_universe()` from the instrument-rules file, `main.py:70-83`). Suppose a held position's symbol is removed from the rules file and the process restarts, or one symbol's feed stays stale. Every new BUY on every symbol is then refused with `UNREALIZED_PNL_UNKNOWN` until that position closes. If the symbol is no longer polled, the system cannot close it either. The block is then permanent and needs an operator to clear it.
- Impact: fail-closed and never harmful to capital, but it is a possible permanent stop of new risk with no dedicated readiness signal. The reason shows only in the rejections.
- Remediation: show "unrealized P&L unknown (symbols: …)" in status/readiness. Document an operator runbook. Optionally refuse to start when a held symbol is outside the polled universe. Do not zero-fill.

### F-C — LOW — Unrealized P&L excludes entry fees (slightly optimistic)
- Location: `execution_manager.py:3027` uses `quote_exposure = base * mark_price`. `mark_price` is the entry execution price and is never re-marked: no caller of `ExecutionPortfolioFoundation.mark()` was found in `core/`. The foundation's own unrealized figure uses `cost_quote` (`execution_portfolio_foundation.py:842`).
- Impact: unrealized loss is understated by the entry fee (about 0.1 % of notional per position). Small, but it errs in the permissive direction, the same direction as F-A.
- Remediation: subtract `cost_quote` (fees included) rather than `base*mark_price`, or document the choice.

### F-D — LOW — Order lifecycle violation list is mutated without the manager lock
- Location: `execution_manager.py:1316-1320` (`append` plus `del [:-100]` outside `self._lock`). `status()` reads it at `:7482-7485`.
- Impact: if `execute` runs on more than one thread, the observe-only counter or ring could be slightly wrong. It can never change a result, so the effect is observability only.
- Remediation: guard with `self._lock` or use `collections.deque(maxlen=100)`.

### F-E — LOW — Sleeve check is evaluated against the request bucket even for experiment admissions
- Location: `risk_engine.py:684-687` vs `:719-721` (the experiment sizes with `EXPERIMENT_SIZING_BUCKET`).
- Impact: none today, because `paper_confidence_experiment=False` in main.py (EXP-001 stopped). If the experiment were turned on again, the sleeve and the sizing bucket would disagree. Recorded so it is not lost.
- Remediation: when the experiment is re-enabled, decide which bucket the sleeve uses and add a test.

### F-F — LOW — Post-mortem CSV export is open to spreadsheet formula injection
- Location: `templates/postmortem.html` CSV `cell()`. Values starting with `=`, `+`, `-`, `@` are not neutralised.
- Impact: the data comes from local records, the export is loopback-only and starts on the client. Low risk.
- Remediation: prefix such cells with `'`.

### F-G — INFORMATIONAL — overview_snapshot record id
- `tools/agent_cycle.py` `overview_snapshot` mints `OV-{len(all memory record ids)+1}`, so the numbers are not sequential per OV type. It writes only to the governance memory log, never to trading state. The read-only claim for the web layer holds; the cycle tool itself writes.

### Checked, no finding
- `/api/events` (`web_app.py:2456-2471`): loopback guard first, read-only, capped at 200 events, no write path.
- HQ / postmortem / sidebar `innerHTML`: every dynamic value goes through `esc()`. Raw interpolations are static lookup tables (`STATE[...]`, `CAT[...]`) or `na()`/`local()`, which escape. No XSS found.
- `observability/event_contract.py`: imports only json/re/datetime/typing and a sanitizer, with no I/O.
- Switch combinations cannot produce NaN or negative values in decisions. `_mark_to_market` returns `None` for a non-finite total. Slippage is bounded, and a non-positive slipped price raises before any fill.

## Verdict
**KEEP ON AFTER FIXES:**
- **F-3 (`count_unrealized_in_daily_loss`)**: fix F-A (HIGH) before the next milestone close. Until it is fixed, F-3 ON can be *looser* than OFF on a day that is past the realized limit while open positions are in profit. Fixing F-A is the remedy. If it cannot be fixed promptly, turn F-3 OFF, since OFF is the stricter setting in exactly that case. F-B and F-C should follow.
- **S1 sleeves**: KEEP ON (F-E is latent only).
- **F-4 slippage 5 bp**: KEEP ON.
- **order_lifecycle_observe**: KEEP ON (F-D is cosmetic).

No path to a real order was found. Execution mode is PAPER and live authority is unchanged (DENIED).

## Remediation (2026-10-01, same session)
| Finding | Status | Change |
|---|---|---|
| **F-A (HIGH)** | Fixed | `core/risk_engine.py` counts only unrealized losses: `min(unrealized, 0)`. Tests: a gain never offsets a realized loss; with F-3 ON the check is never looser than with it OFF. |
| **F-B (MEDIUM)** | Fixed (visibility) | `ExecutionManager.unpriced_held_symbols` is shown in `status()`, and readiness reports `held_position_prices` as FAIL naming the coin. The refusal itself stays, because it fails closed. |
| **F-D (LOW)** | Fixed | Observer violations are now changed under the manager's lock. |
| **F-F (LOW)** | Fixed | The CSV export prefixes formula-like cells with `'`. |
| **F-C (LOW)** | Deferred | Entry fees are still missing from unrealized P&L. |
| **F-E (LOW)** | Deferred | The experiment is off, so this has no effect today. |
| **F-G (INFO)** | Deferred | Record numbering in `overview_snapshot`. |
