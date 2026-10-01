# Independent Re-audit: S1 Capital Sleeves, Step 2 (fixes for the earlier audit)

Date: 2026-10-01. Mode: AUDIT. Auditor: independent subagent. The only repository file created or changed is this report. Nothing was committed.
Earlier report: `docs/audits/INDEPENDENT_AUDIT_S1_STEP2_2026-10-01.md`. Fix commit: `2a32633` ("S1 step 2: fix audit findings ...").

## Tests run
`/usr/bin/python3.13 -m pytest -q -p no:cacheprovider tests/test_position_risk_buckets.py tests/test_s1_capital_sleeves.py tests/test_backtest_replay.py` gave **38 passed** (33 before the fixes).

## Status of the earlier findings

| ID | Earlier severity | Status now |
|---|---|---|
| F-1 | HIGH | **FIXED** |
| F-2 | MEDIUM | **VERIFIED.** The claim holds. |
| F-3 | MEDIUM | **PARTLY FIXED.** It is now logged and fail-closed. The health flag and the truncation repair are still open (see R-2). |
| F-4 | LOW | **FIXED** in the design text |
| F-5 | LOW | **MOSTLY FIXED.** Two items are still open (see R-3). |
| F-6 | LOW | Deferred, and the deferral is recorded. Acceptable. |
| F-7 | INFO | Deferred, and recorded as UNKNOWN. Acceptable. |

### F-1: fixed
- **The change:** `core/risk_engine.py` `_sleeve_check` now counts a position when `pb == bucket or pb not in self.policy.sleeve_shares`. An UNKNOWN position, or one with an invalid bucket, therefore counts against every sleeve.
- **No double-counting:** within one sleeve, each position is counted at most once, because the two conditions cannot both be true for the same position. Across sleeves, an UNKNOWN exposure is charged to each sleeve. That is the intended fail-closed meaning: it can only reduce capacity.
- **Tests:**
  - `test_unknown_bucket_positions_count_against_every_sleeve` adds a MEDIUM refusal (140 + 220 > 350) that the old rule approved.
  - `test_losing_a_bucket_never_loosens_a_sleeve` is a direct NB-4 test: a MEDIUM refusal stays a refusal when the record becomes UNKNOWN.
- **The test change did not weaken anything:**
  - The replaced test kept both of its original assertions: HIGH is refused, and a small MEDIUM request is not `SLEEVE_FULL`. The second assertion is still true under the new rule, because 140 + 20 ≤ 350.
  - The replaced test also gained a stricter assertion.
  - The reason for the change is recorded in a comment, as the testing rules require.

### F-2: claim verified, with the reasoning traced through the code
- **Where the refusal happens:** in `core/risk_engine.py:718-719`, every BUY with an existing position on the same symbol is rejected with `DUPLICATE_OPEN_POSITION`. This check comes before any sleeve or capacity check.
- **The reduce_only path:**
  - `reducing` is true only for `reduce_only and action == "SELL"` (line 632).
  - A BUY with `reduce_only=True` therefore still reaches the duplicate check.
  - A non-reducing SELL is rejected with `NON_RISK_REDUCING_SELL`.
- **Other request sources:** the canonical engine is mandatory. `execution_manager.py:3239-3241` refuses with `CANONICAL_RISK_SERVICE_REQUIRED` when there is no risk engine. Positions come from the durable portfolio foundation, so the request source makes no difference.
- **Restart:** after a restart, positions are re-derived from the durable foundation, so the duplicate check still applies.
- **Foundation layer:** `execution_portfolio_foundation.py:694-695` independently rejects a different `position_id` on the same symbol.
- **What remains:** the add-to-same-id branch at `execution_manager.py:~4885` (`existing["position_id"] if existing ...`) and the same-id add path in the foundation are now unreachable through the risk gate. If they were ever reached (for example, pyramiding is enabled later), a different bucket would read UNKNOWN. After F-1, that is the strictest outcome. Acceptable.
- **Test:** `test_a_second_buy_on_an_open_position_is_refused_and_keeps_its_bucket` covers this end to end.
- **Not covered by a test:** a reduce_only BUY. It is verified by reading the code only. INFORMATIONAL.

### F-3: partly fixed
- **What changed:** the store now logs `POSITION_RISK_BUCKETS_CORRUPT` once at ERROR level for each transition into the corrupt state. A test covers this.
- **Why it is now safe:** because F-1 is fixed, corruption only refuses capacity.
- **What is still open:** see R-2.

### F-4: fixed
The design text now says the record is written before the durable commit, and explains why that is harmless. That explanation matches the code comment and my own reading.

### F-5: mostly fixed
- **Fixed:**
  - The `hasattr` test was replaced.
  - A failing-sidecar test was added. It compares the result against a baseline with no sidecar and asserts `COMMITTED`.
  - An add-on test was added.
  - An NB-4 test was added.
  - A wiring test was added.
- **Still open:** see R-3.

## New or residual findings

### R-1: INFORMATIONAL. UNKNOWN against every sleeve: blocking behaviour and recovery
- **Evidence:** suppose the sidecar is corrupt. Every position reads UNKNOWN, and `record()` refuses to append, so new positions read UNKNOWN too.
- **Effect:** each sleeve's "used" amount then equals the total open exposure. With the default shares, new buying in a bucket is blocked once total open exposure plus the request exceeds that bucket's share. For example, HIGH is blocked above 15% of equity.
- **Not permanent:** the block lifts as positions are closed (SELLs are never blocked by a sleeve). It also lifts when the owner removes or repairs the file. After that, new positions record normally, and existing ones stay UNKNOWN, which is strictest.
- **Judgement:** this is acceptable fail-closed behaviour under rule 2 and NB-4. It is not a deadlock.
- **Owner recovery path:** it exists ("removing it is safe"), but only as a log message. It is not documented in a runbook.
- **Switch-on effect:** every position that was opened before the sidecar existed will be UNKNOWN on switch-on, so it will be charged to all sleeves. The owner should expect this.

### R-2: LOW. Corruption is still visible only through a log line, and one torn final line still loses every record
- **Location:** `core/position_risk_buckets.py` `_read` / `buckets`.
- **Evidence:**
  - The `corrupt` flag is still read by nothing outside the class. There is no health or status signal.
  - A partial last line, for example from a crash during an append, still makes every valid earlier record unreadable.
  - The only recovery is to delete the file. That throws away all good records, so every open position becomes UNKNOWN.
- **Impact:** fail-closed, so not a safety issue. It is an operational one: capacity can shrink after a single crash, and the cause shows only in the logs.
- **Remediation (can be deferred until before switch-on):**
  - Expose `corrupt` in the risk or health status.
  - Optionally provide an owner-run repair step that drops only an unterminated final line.

### R-3: LOW. Two F-5 items are still open, and the wiring test is weak
- **Restart / resume:** no test creates a new store, or restarts the application, on an existing file and checks that the bucket survives.
- **Flag-off test:** `test_flag_off_is_unchanged` still asserts only `!= "SLEEVE_FULL"`. It does not compare the whole decision against a sleeves-off baseline.
- **Wiring test:** `test_application_wires_the_sidecar_into_the_state_directory` checks that a string appears in the source code. It would not catch a wiring line that exists but is never executed.
- **Design text:** the design text says "F-5, fixed", which overstates the status.
- **Remediation:**
  - Add a restart test.
  - Compare whole decisions in the flag-off test.
  - Optionally replace the source-string check with a check on the constructed application.

## Verdict
**APPROVE switch-on.**
- The HIGH finding (F-1) is fixed, with NB-4 tests.
- The F-2 claim is verified in code, including the reduce_only, other-source and restart paths.
- Every remaining item is LOW or INFORMATIONAL and fail-closed.
- Before or shortly after switch-on, the owner should address R-2 (a visible corruption status) and R-3 (a restart test and a whole-decision flag-off test).
- Switch-on itself is an owner decision and is not authorized by this audit.
