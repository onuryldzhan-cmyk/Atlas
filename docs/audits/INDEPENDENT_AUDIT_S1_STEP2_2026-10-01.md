# Independent Audit: S1 Capital Sleeves, Step 2 (Risk-Bucket Sidecar, Option B)

Date: 2026-10-01. Mode: AUDIT. Auditor: independent subagent. No repository file was modified except this report.

## Scope
- `core/position_risk_buckets.py`
- `core/execution_manager.py`: `position_risk_buckets`, `_recorded_risk_bucket`, `_derived_position_exposures`, and the record call in the paper-open path (around line 4860)
- `core/application.py`: wiring at lines 828-829
- `core/risk_engine.py`: `_sleeve_check`, `sleeves_enabled`, `PositionExposure.risk_bucket`
- `tests/test_position_risk_buckets.py`, `tests/test_s1_capital_sleeves.py`, `tests/test_backtest_replay.py`
- `proposals/2026-10-01_s1_step2_risk_bucket_persistence_DESIGN.md`
- `tools/state_backup.py`, to check whether backups include the sidecar

## Tests run
`/usr/bin/python3.13 -m pytest -q -p no:cacheprovider tests/test_position_risk_buckets.py tests/test_s1_capital_sleeves.py tests/test_backtest_replay.py` gave **33 passed**.
I also ran a throwaway probe script in the scratchpad. Its result is given under F-1.

## Findings

### F-1: HIGH. A lost or unclear bucket record loosens the limits for the larger sleeves (NB-4 violation)
- **Location:** `core/risk_engine.py:580-585` (`_sleeve_check`), together with every path in the sidecar that returns UNKNOWN.
- **Evidence:** an UNKNOWN position counts only against the smallest sleeve (`pb not in sleeve_shares and bucket == smallest`). It is removed from the sleeve it was actually admitted under. Probe with the default shares (LOW 0.50, MEDIUM 0.35, HIGH 0.15), equity 1000, sleeves ON:
  - MEDIUM position of 300 with a known bucket, new MEDIUM request of 100: `SLEEVE_FULL`
  - the same position with its bucket UNKNOWN, same request: `RISK_APPROVED`

  The existing test `tests/test_s1_capital_sleeves.py::test_unknown_bucket_positions_count_against_the_smallest_sleeve` asserts that a MEDIUM request is *not* `SLEEVE_FULL` when an UNKNOWN position exists. The test therefore locks the loosening in place.
- **Impact:** once sleeves are switched on, the following all move exposure out of the LOW and MEDIUM sleeves, so new LOW or MEDIUM admissions get through that would otherwise be refused:
  - a corrupt or truncated sidecar (every position becomes UNKNOWN)
  - a deleted sidecar (the design calls this a "safe" rollback)
  - a failed record write
  - conflicting records (F-2)

  Removing evidence makes the system less conservative. That is exactly the NB-4 regression, and it contradicts the design's own claim at line 21 ("missing evidence can never loosen a limit").
- **Reasoning:** "most conservative" was implemented as "charged to the strictest sleeve". The fail-closed meaning is "charged to every sleeve".
- **Remediation:** count every UNKNOWN exposure against every sleeve (or against the requested bucket and the smallest sleeve). Replace or extend the existing test so it asserts that UNKNOWN is never looser than any known bucket. Add an NB-4 test that removing a record never turns a refusal into an approval. Correct the design text.

### F-2: MEDIUM. Adding to an existing position under a different bucket creates a conflict, which then feeds F-1
- **Location:** `core/execution_manager.py` around lines 4851-4867. The id of the existing position is reused, and `record(position_id, request.risk)` is called on every add.
- **Evidence:** the store treats two different buckets for one `position_id` as a conflict and returns `None`. This is tested in `test_conflicting_records_read_as_unknown`. An add with a different risk level therefore turns the whole position UNKNOWN.
- **Impact:** with F-1 in place, a HIGH add on top of a LOW position frees the whole LOW exposure from the LOW sleeve. A position that is genuinely mixed has no representation at all. No test covers the execution path for this case.
- **Remediation:** after F-1 is fixed, this case is fail-closed, which is acceptable. Add an execution-level test for an add with the same bucket and one with a different bucket. Decide explicitly (and record the decision) whether a mixed position should be charged to the strictest bucket or to every bucket it was admitted under.

### F-3: MEDIUM. A truncated or corrupt sidecar degrades permanently and silently
- **Location:** `core/position_risk_buckets.py`, `buckets()` and `record()`.
- **Evidence:**
  - One partial last line, for example from a crash in the middle of an append, makes the whole file unreadable.
  - `record()` then refuses every further append.
  - `buckets()` sets `corrupt=True` but does not log anything, and nothing reads `corrupt` outside the class.
  - No repair or recovery path exists.
- **Impact:** every position, including future ones, reads UNKNOWN forever, and no operator signal is raised. Today that only changes risk outcomes through F-1. After F-1 is fixed it will refuse capacity indefinitely without anyone noticing. CLAUDE.md requires that corrupted state be "detected and halted, never silently continued through".
- **Remediation:** log or alert at error level when the file is corrupt, and expose a health or status flag. Optionally allow an operator-run repair step that drops only an unterminated final line. Add a test for crash recovery.

### F-4: LOW. CONFLICT between the design and the code on when the record is written
- **Expected (design lines 18 and 25):** the record is written "after a confirmed open" / "only after the open has been committed".
- **Actual:** the record is written *before* the durable commit (code comment at `execution_manager.py` around line 4862).
- **Evidence:** the code and design lines cited above.
- **Impact:** low. `mint_long_position_id` is deterministic from `request_id`, so a record left behind by an open that never committed is never looked up, unless the same `request_id` is retried with a different risk, which produces a conflict and therefore UNKNOWN (F-1 again).
- **Decision required:** update the design to match the code, or move the write to after the commit.

### F-5: LOW. Weak and missing tests
- `tests/test_position_risk_buckets.py::test_unknown_bucket_counts_against_the_strictest_sleeve` asserts only `risk_bucket is None` by default and `hasattr(RiskEngine, "_sleeve_check")`. It tests no behaviour.
- `tests/test_s1_capital_sleeves.py::test_flag_off_is_unchanged` asserts only `!= "SLEEVE_FULL"`. It does not compare the full decision with a baseline where sleeves are off. The gate itself is a single `if self.policy.sleeves_enabled` (risk_engine.py:682), so the risk is low, but the test would not catch other drift.
- Missing tests:
  - restart / resume (a new store on an existing file)
  - an exception from `record()` or `lookup()` not affecting the trade (the code wraps both in `except Exception`, which I verified by reading only)
  - add-to-position (F-2)
  - application wiring (`application.py:829`)
  - NB-4 evidence removal (F-1)
- **Remediation:** replace the hasattr test with a behavioural one, compare whole decisions in the flag-off test, and add the missing cases.

### F-6: LOW. Unbounded growth and a full-file read on every evaluation
- **Location:** `lookup()` → `buckets()` → `_read()`, called once per open position on every risk derivation, plus once per `record()`.
- **Impact:** the work is O(positions × file lines) per decision, and the file is never pruned for closed positions. This is a performance issue only, not a correctness one.
- **Remediation:** read the file once per derivation, or cache it keyed on mtime and size. A compaction policy can be deferred.

### F-7: INFORMATIONAL. Concurrency and Windows
- No lock is held between reading and appending. Two concurrent writers could both append the same identical record (harmless, because it reads back the same) or conflicting records (reads UNKNOWN). Execution is effectively serialized today, so this is UNKNOWN if a multi-process deployment ever happens.
- On Windows, append mode with `newline="\n"`, `fsync` and UTF-8 is portable. Antivirus or indexer locks would raise `OSError`, which is caught. Not verified on Windows: UNKNOWN.

### F-8: INFORMATIONAL. Verified as correct
- **Sleeves off:** decisions are unchanged. `_sleeve_check` is reached only under `sleeves_enabled` (risk_engine.py:682). The only other change is the new defaulted field `PositionExposure.risk_bucket`, and I found no use of `asdict` on it.
- **Trades are never blocked or altered by the sidecar:**
  - `record()` and `lookup()` are wrapped in `except Exception` with a warning.
  - The store returns False rather than raising for invalid input.
  - Non-UTF-8 bytes raise `UnicodeDecodeError`, a `ValueError`, which is handled.
- **Idempotency:** an identical record is a no-op, which is tested.
- **Position ids:** they are deterministic per `request_id`, so a new open never collides with a closed position unless `request_id` is reused.
- **Backups:** `tools/state_backup.py:71` copies every non-secret file under the state root, so the `.jsonl` sidecar is included. Restore validation only parses the first line of a `.jsonl` file (lines 59-63), so a truncated tail is not detected at restore time. This feeds F-3.

## Verdict
**APPROVE AFTER FIXES. Do not switch sleeves on until these are done:**
1. F-1: UNKNOWN must never be looser than any known bucket. Fix `_sleeve_check`, replace the test that asserts the loosening, and add an NB-4 evidence-removal test.
2. F-3: surface sidecar corruption (log, alert or health flag), and add a crash-truncation test.
3. F-5: replace the hasattr test with a behavioural test, and add the restart, exception-path and wiring tests.
4. F-2: add an execution test for adding to a position with the same bucket and with a different bucket, and record the decision on mixed positions.
5. F-4: reconcile the design text (write timing, and the claim that rollback is "safe").

F-6 and F-7 can be deferred. Leaving step 2 merged with `sleeves_enabled=False` is acceptable: decisions are unchanged and trades cannot be blocked by the sidecar.
