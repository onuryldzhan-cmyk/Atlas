# REM-001 D5 Drift Check — 2026-09-27

This is an additive comparison record. It checks every claim in REM-001 Gate 1
deliverable 5 (`packaging/REM-001_STATE_AUTHORITY_MAP.md`, "D5") against the
repository as it stands today. It does not edit, regenerate or replace D5. It
follows the convention of the D4 drift check
(`packaging/REM-001_D4_DRIFT_CHECK_2026-09-27.md`, registry v4.91) and reuses
that check's findings where the two artifacts share them. That check's findings
are not re-derived here.

## Identity

| field | value |
| --- | --- |
| subject | `packaging/REM-001_STATE_AUTHORITY_MAP.md` |
| subject sha256 (checked before and after this record) | `3a00d7679f1c91de527e7a0034f3258b10de3a20e12556a4b29dc8a8da089e47` (byte-unchanged; identical to the recovery hash recorded in commit `f5de0d6`) |
| subject lines | 209 |
| subject generated_from_commit / tree | `db8bdf3f22e05a730ca6c3a8ec4eae51f8b66d4b` / `6e4b60a9cd88d2d65d70717ef3509af092aa5e19` (tree re-derived by `git rev-parse db8bdf3^{tree}`) |
| compared against | code state of `3159500ce6047ace81b067bd0ff0d0b4eaf50ed2`. Branch HEAD is now `20917f3`, but the two intervening commits (`fa5b509`, `20917f3`) add only the D4 drift record and registry v4.91, and neither touches any module in scope. The working tree's only change is the untracked `.claude/agents/atlas-test-runner.md`. |
| commits between db8bdf3 and 3159500 | 140 |
| governance record | registry v4.92, `rem001_d5_drift_check_result` |

## Effect and non-effect

- This is a read-only comparison. No application code, D4, D5, test or tool is changed.
- REM-001's `gate_1_state` stays `OPEN_NOT_CERTIFIED`. This record grants no authorization.
- `tools/build_rem001_gate1_maps.py` was **not** rebuilt or recovered. Its
  historical copy in dangling stash object `59229fd` was **read** in two places:
  the `open()` rule (lines 309–312) and the module docstring. This was done only
  to calibrate what D5's own method counts. Nothing from that copy was run or
  written to the repository.
- REM-001's specification is not searched for or reconstructed (GOV-DRIFT-005).

## Brief-premise CONFLICT (reported, not resolved)

The task brief describes D5 in two ways that the repository does not support.

| | |
| --- | --- |
| **Expected** (brief) | D5 "covers 16 state-bearing modules" and carries "a flagged SQLite overlap between `data_layer/config.py` and `data_layer/sqlite.py`". |
| **Actual** | D5 contains neither claim. It reports **24** modules with persistence sites (D5 line 66) and 52 sites, and it contains no overlap flag. Its only SQLite mention is the literal `atlas-local.sqlite3` → `data_layer/config.py` (D5 line 101). `data_layer/sqlite.py` does not appear in D5 at all. |
| **Evidence** | The "16" figure and the overlap flag both come from **D1**, `REM-001_CANONICAL_COMPONENT_MATRIX.json`. D1 has exactly 16 modules with non-empty `mechanical_evidence.persistence_signal_hits`. Its `state_authority_overlap_flags` array has exactly one entry, `data_layer/config.py` + `data_layer/sqlite.py`, with `authority_established: UNKNOWN`. That entry's note says it is "flagged as data for future D5 review". **D6** (`REM-001_OVERLAP_REGISTER.json`, registry v4.60) formalizes the same entry. |
| **Impact** | None on D5's validity. The brief attributed D1/D6 content to D5. This record still answers both of the brief's questions: the D1 16-module set is cross-walked below, and the overlap flag's current status is checked below. |
| **Decision required** | None for this record. If the owner meant "check D1's 16 modules", the crosswalk section answers that. |

## Method

D5 makes 108 checkable claims: 23 header, scope and gate claims (H1–H23), 10
declared-constant rows (C1–C10), 23 literal rows (L1–L23) and 52
persistence-site rows (S1–S52).

**Instrument.** A throwaway AST verifier (a scratch file, not committed, sha256
`e82a3fd0ffe23cb60ea84690bd58269fd37941fa7b2d3d3f7d269c06940e9e3b`) implements
the allowlist D5 describes in its lines 44–56:

- `open()` in a write mode
- `write_text`, `write_bytes` and `writelines`
- `json.dump`
- `replace` and `rename`, resolved by attribute name alone
- `unlink` and `fsync`
- every string literal with a state-file suffix

It reads files as `utf-8-sig`.

**Calibration.** The verifier was run on the db8bdf3 tree (`git show db8bdf3:<path>`) with the db8bdf3 closure. It reproduced:

- **52/52** D5 site rows exactly, on module, operation, line and scope
- 105 closure modules, 24 modules with sites, and 23 distinct literals
- 0 parse failures

It also emitted 10 further rows that D5 lacks. All 10 are method-form
`Path.open("w"/"a")` calls, for example `core/risk_state_store.py:97`
`temporary.open("w", ...)`. The historical generator's `open()` rule
(`59229fd:tools/build_rem001_gate1_maps.py:309`) counts only
`call["form"] == "NAME"`, the bare built-in `open(...)`. D5 therefore
systematically omits method-form opens. This gap existed when D5 was generated,
so it is **not drift**. Those 10 rows are excluded when counting D5-equivalent
figures at HEAD, and are reported separately under Deferred observations.

**Current closure.** `packaging/atlas_runtime_closure.json` at HEAD lists 108
modules and four entry points. In this session
`tests/architecture/test_runtime_closure_matches_inventory.py` gave **2 passed**,
so the closure is current evidence. (The D4 check had already recorded this
test green in combination with another test; it was rerun here as the one
closure fact that D5's module-set figures depend on.)

## Summary

| claim group | claims | STILL_ACCURATE | DRIFTED | CANNOT_VERIFY |
| --- | --- | --- | --- | --- |
| Header, scope and gate (H1–H23) | 23 | 11 | 8 | 4 |
| Declared state-file constants (C1–C10) | 10 | 10 | 0 | 0 |
| Observed state-file literals (L1–L23) | 23 | 22 | 1 | 0 |
| Persistence-site rows (S1–S52) | 52 | 39 | 13 (all line-shift only) | 0 |
| **Total** | **108** | **82** | **22** | **4** |

No D5 row was removed or retargeted. Every operation D5 lists still exists in
the same module and the same enclosing scope. D5 does, however, omit **7** new
HEAD sites that its own generator rules would have captured (listed below).

## Financial-state stores (priority section)

### `core/risk_state_store.py`

**Rows S43–S46 are STILL_ACCURATE.** `git diff db8bdf3 3159500 -- core/risk_state_store.py` is empty, and no commit in the range touches the file. The four rows D5 records are unchanged, at the same lines, in `JsonRiskStateStore::save`:

- JSON_DUMP at line 98
- FSYNC at line 99
- ATOMIC_REPLACE at line 100 (a true `os.replace`)
- UNLINK at line 103

This session's risk-accounting work did not modify this module. That work is recorded in registry keys `paper_risk_accounting_day_auto_rollover_result`, `paper_realized_pnl_risk_accounting_and_halted_rollover_refusal_result` and `paper_recovery_risk_accounting_booking_result`. The durable write operations of the risk-accounting store are exactly the ones D5 recorded. Which callers now invoke `JsonRiskStateStore.save`, and when, is outside D5's site-based method and is not asserted here.

Which module *owns* risk-accounting state is an ownership question. D5 deliberately does not answer it (D5 lines 33–39), and it is not asserted here.

### `core/capital_reservation.py`

**Rows S19–S25: 5 STILL_ACCURATE, 2 DRIFTED (line shift only).** The file changed only in commit `176be4e`, "crash-recovery for F-1/F-2/F-3/F-5/F-6".

- The write path is unchanged at the same lines, in `JsonReservationStore::save`: JSON_DUMP at 111, FSYNC at 113, `os.replace` at 114 and UNLINK at 117. `ReservationArchiveStore::append` FSYNC is still at 169.
- S24 `CapitalReservationLedger::_transition` moved from line 376 to 401.
- S25 `CapitalReservationLedger::commit` moved from line 428 to 453.
- Both moved rows are `dataclasses.replace(...)`, not a filesystem replace (current `core/capital_reservation.py:401` reads `updated = replace(current, status=target, ...)`). They are false positives of the attribute-name rule and were already false positives at generation.

A behavioral change D5 cannot express: `CapitalReservationLedger::reserve` now re-arms a RELEASED reservation to RESERVED on a same-request retry. It checks capacity first (`core/capital_reservation.py:361-366`) and persists through the existing `self._persist(candidate)`. The change also adds a `reserved()` accessor. That re-arm step produces one new scanner hit at line 363, which is again a `dataclasses.replace` false positive. **The durable write surface of this store is unchanged.** Only the state-transition logic behind it changed. That logic is outside D5's observation-only scope.

### `core/execution_portfolio_foundation.py`

**Rows S35–S39: 1 STILL_ACCURATE, 4 DRIFTED (line shift of +6).** The file changed only in commit `176be4e`.

- S35 `_utc` at line 64 is STILL_ACCURATE. It is a `str.replace` false positive.
- `FinancialStateStore::save` FSYNC moved from 177 to 183, and its `os.replace` from 178 to 184.
- `AppliedExecutionArchiveStore::append` FSYNC moved from 251 to 257.
- `ClosedPositionArchiveStore::append` FSYNC moved from 415 to 421.

What D5 cannot show:

- `FinancialStateStore.load` gained `allow_transition`. A persisted non-null `transition` now raises `FINANCIAL_TRANSITION_RECOVERY_REQUIRED` unless the caller explicitly allows it (`core/execution_portfolio_foundation.py:170-173`).
- The commit added four module-level recovery functions: `inspect_interrupted_transition` (:940), `abandon_interrupted_transition` (:1037) and `complete_interrupted_transition` (:1061), plus the `_open_foundation` helper.
- The abandon and complete paths are **new callers** of the existing durable operations: `store.save(transition.pre_state)` at :1057, and `closed_archive.append`, `applied_archive.append` and `store.save(candidate)` at :1119–1138.

These add no new *operation site*, which is D5's unit of observation. They do add new *write paths* into financial state, and D5's method (sites attributed to the calling module, receivers not inferred) cannot represent that. This is the main reason D5 must not be read as a map of who writes financial state today.

### Adjacent financial-mirror store: `core/paper_trader.py` (not one of the three, but materially drifted)

- **Rows S41–S42 are DRIFTED (line shift):** OPEN_WRITE_MODE moved from 565 to 839, and JSON_DUMP from 574 to 852.
- **Omitted by D5 at HEAD:** 3 new sites that the D5 generator would capture.
  - `PaperTrader::save` now writes to `<file>.tmp` with `f.flush()` and `os.fsync` at :874, then `os.replace(temp, self.filename)` at :879.
  - At generation, `PaperTrader::save` had only a bare open and `json.dump` into the live file.
  - `PaperTrader::_load_failed` now quarantines an unreadable book with `os.replace` at :791.
- Source commits: `ccb2e37` (F-4, atomic save, loud load) and `e879517` (F-4, re-projection rewrites only on divergence). Earlier, `dac9b72` made PaperTrader a passive mirror.

D5's picture of the paper book is therefore a non-atomic writer. That picture is **stale**, and it understates the current durability guarantees.

### Other execution-state stores

- S40 `core/execution_transaction_journal.py` `ExecutionTransactionJournal::reset` UNLINK is DRIFTED (line 949 → 953).
- S32 `core/execution_idempotency_store.py` `ExecutionIdempotencyStore::reset` UNLINK is STILL_ACCURATE at 863.
- S17 `core/audit_event_store.py` FSYNC at 331 is STILL_ACCURATE.
- C1–C10: all ten composition-root state-file constants are unchanged in name and value, now at `core/application.py:350-369` (previously 144–163). Their "observed outside the composition root" column is unchanged: only `paper_trades.json` → `core/paper_trader.py`.

## SQLite overlap flag (D1/D6) — current status

**Short answer:** the flag is still valid **as recorded data**. The code pair is byte-unchanged and still describes one database resource that the two modules share. However, **neither module is in the runtime closure any more**, and none of this session's financial-state work touched either file. Nothing resolved the flag. It became runtime-unreachable through an unrelated architecture change.

Evidence:

- `git log db8bdf3..3159500 -- data_layer/config.py data_layer/sqlite.py` is empty, so both files are unchanged since D5's generation.
- Commit `1ac3a64` ("make data_layer/__init__.py lazy") converted the package init to PEP 562 lazy attributes. `packaging/atlas_runtime_closure.json` at HEAD no longer lists `data_layer/config.py`, `data_layer/sqlite.py` or `data_layer/semantic_contracts.py`, as the diff of that file from db8bdf3 shows. This matches the D4 check's finding of 24 D4 rows whose constructing module left the closure.
- The relationship itself is one configuration module naming a single path and constructing one backend, not two independent writers:
  - `data_layer/config.py:55` is the only place that names `atlas-local.sqlite3`.
  - `data_layer/config.py:71-74` (`create_storage`) passes that path into `data_layer/sqlite.py`'s `SQLiteStorage`, which opens it at `data_layer/sqlite.py:361`.
- A search of `core`, `ai`, `atlas_os`, `atlas_finance`, `observability`, `portfolio`, `main.py`, `web_app.py`, `atlas_service.py` and `atlas_supervisor.py` finds no call to `load_storage_configuration`, `create_storage` or `SQLiteStorage`.
- Whether the two modules "overlap in authority" remains `UNKNOWN`, as D1 and D6 state. That is an ownership judgment reserved for the owner, and it is not resolved here.
- **A different SQLite store has entered the runtime.** `core/application.py:600-602` constructs `EvidenceStore(self.evidence_directory / EVIDENCE_DATABASE_FILENAME)`, with `DATABASE_FILENAME = "evidence_store.sqlite3"` at `data_layer/evidence_store.py:68` (ADR-0008). It uses a distinct file name and a single owning module, so there is no name-level evidence of overlap with `atlas-local.sqlite3`. D5 cannot see it, however:
  - Its writes go through `sqlite3` connection methods, which are outside D5's allowlist.
  - Its path is not a module-level `*_FILE` constant of `core/application.py`, so it is absent from D5's "declared durable state surface" table.

## D1 16-module crosswalk (answers the brief's premise)

| D1 persistence-signal module | in D5 (site rows) | in HEAD closure | note |
| --- | --- | --- | --- |
| `ai/core/atlas_memory_core.py` | yes (S2–S3) | yes | rows exact |
| `ai/core/atlas_reasoning_engine.py` | yes (S4–S5) | yes | rows exact |
| `ai/core/atlas_world_model.py` | yes (S6–S7) | yes | rows exact |
| `atlas_os/audit/audit_log.py` | yes (S14–S15) | yes | rows exact; `Path.open` append omitted (method gap) |
| `atlas_os/configuration/configuration_service.py` | no | yes | D1 hit is a read, `resolved_path.open("r")` at :824; correctly absent |
| `core/audit_event_store.py` | yes (S17) | yes | row exact; `Path.open` append omitted (method gap) |
| `core/capital_reservation.py` | yes (S19–S25) | yes | see financial section |
| `core/durable_append_log.py` | yes (S28–S31) | yes | rows exact |
| `core/execution_portfolio_foundation.py` | yes (S35–S39) | yes | see financial section |
| `core/paper_trader.py` | yes (S41–S42) | yes | see financial section |
| `core/position_controller.py` | no | yes | D1 hits are `PositionController.open(...)`, a trading method (:157, :202, :399), not file I/O; correctly absent |
| `core/risk_state_store.py` | yes (S43–S46) | yes | unchanged file |
| `data_layer/config.py` | literal only (L3) | **no** | left closure at `1ac3a64` |
| `data_layer/contracts.py` | no | yes | D1 hit is a `Protocol` method `def open` (:92 at D1 generation); no I/O; correctly absent |
| `data_layer/sqlite.py` | no | **no** | `sqlite3.connect` is outside D5's allowlist; left closure at `1ac3a64` |
| `portfolio/capital_manager.py` | yes (S51–S52) | yes | rows exact |

Result: 11 of D1's 16 have site rows in D5, and a 12th (`data_layer/config.py`)
appears only as a literal. Of the other 4, three are false positives of D1's
signal and one is SQLite, which D5's method cannot see. Separately, D5 lists 13
site modules that D1 does not flag. Most of these are attribute-name `replace`
hits, such as `atlas_finance/...::_normalize_symbol`.

## Most significant drift

1. **Financial-state write paths grew in ways D5 cannot represent.** The interrupted-transition recovery tool (`176be4e`) adds new callers of `FinancialStateStore.save` and the archive appends. `CapitalReservationLedger.reserve` adds a RELEASED→RESERVED re-arm. D5 is site-based and receiver-blind, so neither change shows up as drift in its rows. Its rows look "accurate" while the write-path picture has changed.
2. **The paper book became atomic.** `PaperTrader::save` gained tmp + fsync + `os.replace`, and `_load_failed` gained quarantine `os.replace` (3 new sites omitted, `ccb2e37`).
3. **The declared durable state surface is incomplete at HEAD.**
   - `evidence_store.sqlite3` (`core/application.py:600`) and `market_loop_telemetry.jsonl` (`core/logger.py:39`, written by `_TelemetryFileWriter` at `core/logger.py:91`, commit `ba38ed4`) are durable runtime state.
   - Neither appears in D5, and neither is a `core/application.py` `*_FILE` constant.
   - Scope figures under D5's own rules: sites 52 → **59**; modules with sites 24 → **26** (adding `core/logger.py` and `data_layer/evidence_store.py`); literals 23 → **26**; closure modules 105 → **108**; entry points 2 → **4**.
4. **D5 was never regression-protected.** Its stated enforcing test, `tests/architecture/test_rem001_state_authority_map.py`, has no history on any ref (`git log --all` is empty). It exists only inside dangling stash object `59229fd`, beside the generator. This is the same situation the D4 check found for D4's test.
5. **The GOV-DRIFT-005 status is stale.** D5 records it as `OPEN`. Registry v4.91 records `CONFIRMED_AND_RECORDED_BY_VERSIONED_SUCCESSOR_RECORD`, the same drift as D4 H-claims.

## What still holds

- Every one of D5's 52 recorded operations still exists, in the same module and the same enclosing scope. 39 are at the identical line.
- All 10 composition-root state-file constants are unchanged in name and value.
- 22 of 23 literal rows are unchanged.
- `core/risk_state_store.py` is byte-unchanged.
- D5's non-claims still hold: it does not assign ownership, and it omits the classification fields.

## Overall verdict

**STALE_REGENERATION_REQUIRED — ROWS SOUND, SURFACE INCOMPLETE.** D5 is an accurate snapshot of db8bdf3's persistence *sites*. At HEAD it:

- understates the durable surface (two new durable stores, seven new sites)
- misses a method-form `Path.open` class of writes by design
- cannot represent the most important change in this area, which is new recovery write paths into financial state

D5 must be treated as a historical snapshot of db8bdf3. It must not be cited as current evidence of where financial state is written.

## Recommended next step (separate, owner-authorized task — not done here)

Take one owner decision covering both D4 and D5: whether to authorize successors generated at a current HEAD. If authorized:

- commit the generator together with the two regression tests D4 and D5 promised, so drift fails loudly
- widen the `open()` rule to method-form `Path.open`
- add SQLite connection writes to the allowlist
- filter `str.replace`, `datetime.replace` and `dataclasses.replace` false positives

The D1/D6 SQLite overlap flag should get its owner disposition in the same package. Its code pair is now runtime-unreachable.

## Deferred observations (recorded, not acted on)

- **Method gap at generation (not drift):** 10 method-form `Path.open` write
  sites are absent from D5, and all 10 still exist at HEAD:
  - `atlas_os/audit/audit_log.py:590`
  - `core/audit_event_store.py:319`
  - `core/capital_reservation.py:110`
  - `core/capital_reservation.py:166`
  - `core/durable_append_log.py:272`
  - `core/durable_append_log.py:332`
  - `core/execution_portfolio_foundation.py:180`
  - `core/execution_portfolio_foundation.py:254`
  - `core/execution_portfolio_foundation.py:418`
  - `core/risk_state_store.py:97`
- **False positives inside D5 (not drift):** of D5's 24 ATOMIC_REPLACE rows, only 5 are filesystem replaces: S15, S21, S30, S37 and S45. The other 19 are `str`, `datetime` or `dataclasses` `.replace`. D5's own lines 53–56 disclose attribute-name resolution, so this is a disclosed limitation, not an error.
- The literal `data_layer.sqlite` (`data_layer/__init__.py:36`) that appears at HEAD is a lazy-import module path, not a state file. It is a scanner false positive and is counted in the 26 only for method parity.
- `docs/evidence/block5j_execution_authority_recovery.md` names `execution_idempotency.json` and `execution_transaction_journal.json`, with a `.json` suffix. The current constants are `.jsonl`. This is likely historical naming. It is not investigated here.

## Header, scope and gate claims (H1–H23)

| # | D5 line(s) | claim | verdict | evidence |
| --- | --- | --- | --- | --- |
| H1 | 3 | Deliverable 5 of 9 | STILL_ACCURATE | registry v4.50 `grant_d4_d5_recovery.target_files`, v4.91 |
| H2 | 5–6 | Generated by / regenerable via `tools/build_rem001_gate1_maps.py state` | DRIFTED | tool absent from working tree and every branch; exists only in `59229fd` (excluded from v4.50 recovery) |
| H3 | 12–13 | authorization `REM-001-GATE1-MECHANICAL`, registry v4.32 | STILL_ACCURATE | `governance/current/ATLAS_MILESTONE_REGISTRY_v4.32.json` exists; re-verified by v4.50 |
| H4 | 14 | decision record path | STILL_ACCURATE | `governance/ATLAS_BASELINE_IDENTITY_AND_GATE1_SCOPE_DECISION_v1.0.md` exists |
| H5 | 15 | GOV-DRIFT-005 OPEN | DRIFTED | v4.91 status `CONFIRMED_AND_RECORDED_BY_VERSIONED_SUCCESSOR_RECORD` |
| H6 | 16 | not a certification; does not advance `gate_1_state` | STILL_ACCURATE | v4.91 `gate_1_state` = `OPEN_NOT_CERTIFIED` everywhere |
| H7 | 22 | generated_from_commit db8bdf3 | STILL_ACCURATE | object exists, ancestor of HEAD; calibration reproduces D5 |
| H8 | 23 | generated_from_tree 6e4b60a | STILL_ACCURATE | `git rev-parse db8bdf3^{tree}` |
| H9 | 24 | working tree clean at generation | CANNOT_VERIFY | generation-time state not recorded elsewhere |
| H10 | 25 | no modified tracked paths at generation | CANNOT_VERIFY | same |
| H11 | 62 | entry points `main.py`, `web_app.py` | DRIFTED | HEAD closure also lists `atlas_service.py`, `atlas_supervisor.py` (`9fadd67`, `2d7ab52`) |
| H12 | 63 | 105 closure modules | DRIFTED | 108 at HEAD (+6 −3 vs the db8bdf3 closure; closure test 2 passed) |
| H13 | 64 | 10 declared state-file constants | STILL_ACCURATE | `core/application.py:350-369`, same 10 |
| H14 | 65 | 52 persistence sites | DRIFTED | 59 under D5's own rules (69 incl. method-form gap) |
| H15 | 66 | 24 modules with sites | DRIFTED | 26 (+`core/logger.py`, +`data_layer/evidence_store.py`) |
| H16 | 67 | 23 distinct literals | DRIFTED | 26: −`atlas-local.sqlite3`; +`evidence_store.sqlite3`, `market_loop_telemetry.jsonl`, `reports/observability/telemetry_summary.json`, `data_layer.sqlite` (false positive) |
| H17 | 68 | 0 parse failures | STILL_ACCURATE | all 108 HEAD closure modules parsed |
| H18 | 180–196 | classification fields deliberately absent | STILL_ACCURATE | document property; D5 byte-unchanged |
| H19 | 200 | gates "enforced by" `tests/architecture/test_rem001_state_authority_map.py` | DRIFTED | never committed on any ref; only in `59229fd` |
| H20 | 205 | every declared constant accounted for | STILL_ACCURATE | C1–C10 unchanged at HEAD |
| H21 | 206 | every persistence-site module inside runtime closure | STILL_ACCURATE | all 24 D5 site modules in HEAD closure |
| H22 | 207 | ADR-0003 / block5j durable authorities present in declared surface | CANNOT_VERIFY | enforcing test absent; ADR-0003 names no state file by name; block5j uses `.json` names (see Deferred) |
| H23 | 208 | regeneration is byte-identical | CANNOT_VERIFY | generator absent; by H12–H16 a regeneration could not be byte-identical at HEAD |

## Declared state-file constants (C1–C10)

All STILL_ACCURATE. Name and value are unchanged, and so is the "observed
outside composition root" column. The declarations are now at
`core/application.py:350-369`.

| # | constant | file | HEAD line |
| --- | --- | --- | --- |
| C1 | `CAPITAL_RESERVATION_ARCHIVE_FILE` | `capital_reservations_archive.jsonl` | 356 |
| C2 | `CAPITAL_RESERVATION_STATE_FILE` | `capital_reservations.json` | 351 |
| C3 | `EXECUTION_APPLIED_EXECUTIONS_FILE` | `execution_applied_executions.jsonl` | 362 |
| C4 | `EXECUTION_AUDIT_EVENT_FILE` | `audit/atlas_audit_events.jsonl` | 367 |
| C5 | `EXECUTION_CLOSED_POSITIONS_FILE` | `execution_closed_positions.jsonl` | 363 |
| C6 | `EXECUTION_FINANCIAL_STATE_FILE` | `execution_financial_state.json` | 357 |
| C7 | `EXECUTION_IDEMPOTENCY_STATE_FILE` | `execution_idempotency.jsonl` | 365 |
| C8 | `EXECUTION_TRANSACTION_JOURNAL_FILE` | `execution_transaction_journal.jsonl` | 366 |
| C9 | `PAPER_TRADE_BOOK_FILE` | `paper_trades.json` | 369 |
| C10 | `RISK_ACCOUNTING_STATE_FILE` | `risk_accounting_state.json` | 350 |

## Observed state-file literals (L1–L23)

22 STILL_ACCURATE: every row except L3 has an identical module set at HEAD.
One row is DRIFTED:

| # | literal | D5 modules | HEAD | verdict |
| --- | --- | --- | --- | --- |
| L3 | `atlas-local.sqlite3` | `data_layer/config.py` | literal still at `data_layer/config.py:55`, but the module is no longer in the runtime closure (`1ac3a64`) | DRIFTED |

## Sites at HEAD not in D5 under D5's own generator rules (7; omissions, not D5 claims)

| module | operation | HEAD line | scope | nature |
| --- | --- | --- | --- | --- |
| `core/paper_trader.py` | FSYNC | 874 | `PaperTrader::save` | real — atomic save (`ccb2e37`) |
| `core/paper_trader.py` | ATOMIC_REPLACE | 879 | `PaperTrader::save` | real — `os.replace(temp, self.filename)` |
| `core/paper_trader.py` | ATOMIC_REPLACE | 791 | `PaperTrader::_load_failed` | real — quarantine `os.replace` |
| `core/logger.py` | OPEN_WRITE_MODE | 91 | `_TelemetryFileWriter::__init__` | real — `open(path, mode="a")`, `market_loop_telemetry.jsonl` (`ba38ed4`) |
| `core/capital_reservation.py` | ATOMIC_REPLACE | 363 | `CapitalReservationLedger::reserve` | false positive — `dataclasses.replace` |
| `data_layer/evidence_store.py` | ATOMIC_REPLACE | 288 | `_utc_text` | false positive — `str.replace` |
| `data_layer/evidence_store.py` | ATOMIC_REPLACE | 882 | `EvidenceStore::sources_for` | false positive — `str.replace` |

## Persistence-site rows (S1–S52)

| # | module | operation | D5 line | enclosing scope | HEAD line | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | `ai/core/atlas_brain.py` | ATOMIC_REPLACE | 528 | `AtlasBrain::world_analysis` | 596 | DRIFTED (line 528 -> 596) |
| S2 | `ai/core/atlas_memory_core.py` | OPEN_WRITE_MODE | 189 | `AtlasMemoryCore::save` | 189 | STILL_ACCURATE |
| S3 | `ai/core/atlas_memory_core.py` | JSON_DUMP | 190 | `AtlasMemoryCore::save` | 190 | STILL_ACCURATE |
| S4 | `ai/core/atlas_reasoning_engine.py` | OPEN_WRITE_MODE | 771 | `AtlasReasoningEngine::save` | 771 | STILL_ACCURATE |
| S5 | `ai/core/atlas_reasoning_engine.py` | JSON_DUMP | 782 | `AtlasReasoningEngine::save` | 782 | STILL_ACCURATE |
| S6 | `ai/core/atlas_world_model.py` | OPEN_WRITE_MODE | 209 | `AtlasWorldModel::save` | 209 | STILL_ACCURATE |
| S7 | `ai/core/atlas_world_model.py` | JSON_DUMP | 210 | `AtlasWorldModel::save` | 210 | STILL_ACCURATE |
| S8 | `atlas_finance/market_data/binance_public_provider.py` | ATOMIC_REPLACE | 1011 | `BinancePublicDataProvider::_normalize_symbol` | 1011 | STILL_ACCURATE |
| S9 | `atlas_finance/market_data/binance_public_provider.py` | ATOMIC_REPLACE | 1011 | `BinancePublicDataProvider::_normalize_symbol` | 1011 | STILL_ACCURATE |
| S10 | `atlas_finance/market_data/binance_public_provider.py` | ATOMIC_REPLACE | 1011 | `BinancePublicDataProvider::_normalize_symbol` | 1011 | STILL_ACCURATE |
| S11 | `atlas_finance/market_data/market_feed_service.py` | ATOMIC_REPLACE | 1719 | `MarketFeedService::_normalize_symbol` | 1719 | STILL_ACCURATE |
| S12 | `atlas_finance/market_data/market_feed_service.py` | ATOMIC_REPLACE | 1719 | `MarketFeedService::_normalize_symbol` | 1719 | STILL_ACCURATE |
| S13 | `atlas_finance/market_data/market_feed_service.py` | ATOMIC_REPLACE | 1719 | `MarketFeedService::_normalize_symbol` | 1719 | STILL_ACCURATE |
| S14 | `atlas_os/audit/audit_log.py` | FSYNC | 607 | `AuditLogService::_persist_record` | 607 | STILL_ACCURATE |
| S15 | `atlas_os/audit/audit_log.py` | ATOMIC_REPLACE | 741 | `AuditLogService::rotate` | 741 | STILL_ACCURATE |
| S16 | `core/audit_event.py` | ATOMIC_REPLACE | 565 | `AuditEvent::_normalize_timestamp` | 566 | DRIFTED (line 565 -> 566) |
| S17 | `core/audit_event_store.py` | FSYNC | 331 | `AuditEventStore::_append_event_locked` | 331 | STILL_ACCURATE |
| S18 | `core/candle_processor.py` | ATOMIC_REPLACE | 1061 | `CandleProcessor::_to_milliseconds` | 1061 | STILL_ACCURATE |
| S19 | `core/capital_reservation.py` | JSON_DUMP | 111 | `JsonReservationStore::save` | 111 | STILL_ACCURATE |
| S20 | `core/capital_reservation.py` | FSYNC | 113 | `JsonReservationStore::save` | 113 | STILL_ACCURATE |
| S21 | `core/capital_reservation.py` | ATOMIC_REPLACE | 114 | `JsonReservationStore::save` | 114 | STILL_ACCURATE |
| S22 | `core/capital_reservation.py` | UNLINK | 117 | `JsonReservationStore::save` | 117 | STILL_ACCURATE |
| S23 | `core/capital_reservation.py` | FSYNC | 169 | `ReservationArchiveStore::append` | 169 | STILL_ACCURATE |
| S24 | `core/capital_reservation.py` | ATOMIC_REPLACE | 376 | `CapitalReservationLedger::_transition` | 401 | DRIFTED (line 376 -> 401) |
| S25 | `core/capital_reservation.py` | ATOMIC_REPLACE | 428 | `CapitalReservationLedger::commit` | 453 | DRIFTED (line 428 -> 453) |
| S26 | `core/decision_adapter.py` | ATOMIC_REPLACE | 688 | `DecisionAdapter::_confidence_to_percent` | 688 | STILL_ACCURATE |
| S27 | `core/decision_adapter.py` | ATOMIC_REPLACE | 916 | `DecisionAdapter::get_created_at` | 916 | STILL_ACCURATE |
| S28 | `core/durable_append_log.py` | FSYNC | 285 | `DurableAppendLog::append` | 285 | STILL_ACCURATE |
| S29 | `core/durable_append_log.py` | FSYNC | 345 | `DurableAppendLog::rewrite` | 345 | STILL_ACCURATE |
| S30 | `core/durable_append_log.py` | ATOMIC_REPLACE | 349 | `DurableAppendLog::rewrite` | 349 | STILL_ACCURATE |
| S31 | `core/durable_append_log.py` | UNLINK | 356 | `DurableAppendLog::rewrite` | 356 | STILL_ACCURATE |
| S32 | `core/execution_idempotency_store.py` | UNLINK | 863 | `ExecutionIdempotencyStore::reset` | 863 | STILL_ACCURATE |
| S33 | `core/execution_manager.py` | ATOMIC_REPLACE | 5624 | `ExecutionManager::_normalize_confidence` | 6251 | DRIFTED (line 5624 -> 6251) |
| S34 | `core/execution_models.py` | ATOMIC_REPLACE | 96 | `normalize_timestamp` | 96 | STILL_ACCURATE |
| S35 | `core/execution_portfolio_foundation.py` | ATOMIC_REPLACE | 64 | `_utc` | 64 | STILL_ACCURATE |
| S36 | `core/execution_portfolio_foundation.py` | FSYNC | 177 | `FinancialStateStore::save` | 183 | DRIFTED (line 177 -> 183) |
| S37 | `core/execution_portfolio_foundation.py` | ATOMIC_REPLACE | 178 | `FinancialStateStore::save` | 184 | DRIFTED (line 178 -> 184) |
| S38 | `core/execution_portfolio_foundation.py` | FSYNC | 251 | `AppliedExecutionArchiveStore::append` | 257 | DRIFTED (line 251 -> 257) |
| S39 | `core/execution_portfolio_foundation.py` | FSYNC | 415 | `ClosedPositionArchiveStore::append` | 421 | DRIFTED (line 415 -> 421) |
| S40 | `core/execution_transaction_journal.py` | UNLINK | 949 | `ExecutionTransactionJournal::reset` | 953 | DRIFTED (line 949 -> 953) |
| S41 | `core/paper_trader.py` | OPEN_WRITE_MODE | 565 | `PaperTrader::save` | 839 | DRIFTED (line 565 -> 839) |
| S42 | `core/paper_trader.py` | JSON_DUMP | 574 | `PaperTrader::save` | 852 | DRIFTED (line 574 -> 852) |
| S43 | `core/risk_state_store.py` | JSON_DUMP | 98 | `JsonRiskStateStore::save` | 98 | STILL_ACCURATE |
| S44 | `core/risk_state_store.py` | FSYNC | 99 | `JsonRiskStateStore::save` | 99 | STILL_ACCURATE |
| S45 | `core/risk_state_store.py` | ATOMIC_REPLACE | 100 | `JsonRiskStateStore::save` | 100 | STILL_ACCURATE |
| S46 | `core/risk_state_store.py` | UNLINK | 103 | `JsonRiskStateStore::save` | 103 | STILL_ACCURATE |
| S47 | `data_layer/migrations.py` | ATOMIC_REPLACE | 146 | `apply_migrations` | 146 | STILL_ACCURATE |
| S48 | `data_layer/models.py` | ATOMIC_REPLACE | 54 | `utc_text` | 54 | STILL_ACCURATE |
| S49 | `data_layer/models.py` | ATOMIC_REPLACE | 61 | `utc_text` | 61 | STILL_ACCURATE |
| S50 | `observability/panel_sources.py` | ATOMIC_REPLACE | 370 | `_supersedes_name` | 377 | DRIFTED (line 370 -> 377) |
| S51 | `portfolio/capital_manager.py` | OPEN_WRITE_MODE | 797 | `CapitalManager::save_positions` | 797 | STILL_ACCURATE |
| S52 | `portfolio/capital_manager.py` | JSON_DUMP | 808 | `CapitalManager::save_positions` | 808 | STILL_ACCURATE |
