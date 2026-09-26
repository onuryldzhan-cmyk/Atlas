# EXEC-ID-REDACTION-001 (historical remediation) — additive annotation reconstructing the 8 pre-fix corrupted journal entries

## Status

**RECORDED. ADDITIVE ONLY. No original data file is modified by this record.**

Authorized by the owner decision in the session task prompt of 2026-09-27
(package "close out MEDIUM-1 and the execution-identifier redaction fix"):
remediate the 8 historically-corrupted journal entries found during
EXEC-ID-REDACTION-001's real-world impact scan (checkpoint
`checkpoints/20260926T190000Z_exec-id-redaction-fix.md`) by creating an
additive annotation record that reconstructs the correct value for each
affected field from the (confirmed clean, hash-chain-verified) audit event
log — never by editing `memory_data/execution_idempotency.jsonl`, the
transaction journal, or the retired `.migrated` file in place. Any field the
audit log cannot reconstruct with certainty is marked UNKNOWN rather than
guessed. No registry grant id was cited: grant identifier UNKNOWN.

| Field | Value |
| --- | --- |
| Parent finding | EXEC-ID-REDACTION-001 (`governance/current/ATLAS_MILESTONE_REGISTRY_v4.85.json`, `execution_identifier_redaction_fix_result`) |
| Record type | `HISTORICAL_DATA_CORRUPTION_RECONSTRUCTION_ANNOTATION` |
| Operating mode | Reconciliation (additive, non-destructive) |
| Files annotated (never modified) | `memory_data/execution_transaction_journal.jsonl`, `memory_data/execution_transaction_journal.json.migrated` |
| Files modified by this record | NONE — this Markdown file is new; nothing under `memory_data/` was written |
| Entries reconstructed | 8 of 8 (100%) |
| Fields marked UNKNOWN | 0 |
| Recorded on | 2026-09-27 |
| Production effect | NONE |
| Live effect | NONE |

## 1. Scope

This record covers exactly the 8 journal entries identified in the
EXEC-ID-REDACTION-001 checkpoint's real-world impact scan: all 8 are
terminal `NOT_COMMITTED` SELLs, in both the `.jsonl` journal and the retired
v1 `.migrated` file, which hold the same corruption under the same 8 keys.
It does not touch the idempotency store or the audit log (both independently
confirmed to hold zero corrupted values, §3 below), does not implement any
code change (that is EXEC-ID-REDACTION-001's implementation commit, already
closed), and does not repair, rewrite, or truncate either original file.

## 2. Method

Every value below was reconstructed and cross-verified from two independent
sources that were never passed through the redactor, without opening,
locking, or constructing any `AtlasApplication` runtime component (per the
standing rule to route reproductions through a scratch state directory —
this record performed only direct, read-only file/JSON reads of the
operator's real `C:\AtlasState\memory_data` store):

1. **The journal entry's own top-level `request_id` field.** Each entry in
   `execution_transaction_journal.jsonl` is a JSON object shaped
   `{"entry": {...}, "request_id": "...", "sequence": N, "state": "..."}`.
   The corruption is confined to `[REDACTED]` substrings *inside* the nested
   `entry.request`/`entry.result` payloads (9 field occurrences per corrupted
   entry — see §4); the outer `request_id` field, and the `.migrated` file's
   dict key for the same entry, were never passed through
   `sanitize_sensitive_data` and hold the true, unredacted value in both
   files.
2. **The audit event log's `aggregate_id`/`correlation_id`.**
   `memory_data/audit/atlas_audit_events.jsonl` logs an
   `EXECUTION_REQUEST_RECEIVED` event for every request, with
   `aggregate_id` and `correlation_id` both set to the same
   `SYMBOL|open:<candle_open_ms>|SELL` string, also never redacted (the
   audit log holds 0 corrupted values — §3). For each of the 8 corrupted
   entries, the matching audit event was located by symbol, action, and
   request timestamp (`entry.request.timestamp`): every match was unique,
   with the nearest candidate within 2 milliseconds of the request
   timestamp and the next-nearest candidate more than 2 seconds away, and
   the audit event's `payload.price` matched the journal entry's
   `entry.request.price` exactly in all 8 cases.

Both sources agree byte-for-byte for all 8 entries in both files. No field
required a judgment call between conflicting values, and no field is marked
UNKNOWN.

## 3. Corroborating evidence — idempotency store and audit log are clean

Re-verified in this session (read-only, current state, superset of the
checkpoint's original 22-journal-entry/12-idempotency-record/130-audit-event
scan, which has since grown to 23/28/166 as paper trading continued):

- `grep -c REDACTED` on `execution_idempotency.jsonl`,
  `execution_idempotency.json.migrated`, and
  `audit/atlas_audit_events.jsonl`: **0 matches in all three.**
- Audit hash-chain linkage re-checked structurally across all 166 current
  events (`previous_hash[i] == event_hash[i-1]`, genesis at index 0): **0
  breaks.**
- `grep -c REDACTED` on `execution_transaction_journal.jsonl`: exactly **8**
  matching lines, at line indices 1, 3, 5, 7, 11, 13, 17, 21 (0-indexed),
  confirming the checkpoint's "8 of 22" finding is still exactly 8 in the
  now-larger file — no additional corruption has occurred since the fix
  landed (implementation commit `0506c15`).
- `execution_transaction_journal.json.migrated` contains exactly 72
  `REDACTED` occurrences (9 per entry x 8 entries), under exactly the same 8
  `SYMBOL|open:<ms>|SELL` dict keys as reconstructed below.
- SHA-256 of the two original files, recorded here purely as a read-only
  fingerprint (this record performs no write to either):
  - `execution_transaction_journal.jsonl`:
    `a8b2539d23df05841a280853cedf777a17289fbab867f87e578f3d57416bedef`
  - `execution_transaction_journal.json.migrated`:
    `85c86f3282847a0f59ca215b119a401beda7e4e16a1c6332419d2cc4ead89e19`

## 4. Reconstruction

Every corrupted entry has exactly 9 corrupted field occurrences, all
following the same shape — one candle-identity fact
(`SYMBOL`, `candle_open_ms`) reconstructs all 9 in that entry:

- `entry.request.metadata.candle_identity` = `open:<candle_open_ms>`
- `entry.request.metadata.execution_fingerprint` = `<SYMBOL>|open:<candle_open_ms>|SELL`
- `entry.request.metadata.idempotency_key` = `<SYMBOL>|open:<candle_open_ms>|SELL`
- `entry.request.request_id` = `<SYMBOL>|open:<candle_open_ms>|SELL`
- `entry.result.data.request_id` = `<SYMBOL>|open:<candle_open_ms>|SELL`
- `entry.result.metadata.candle_identity` = `open:<candle_open_ms>`
- `entry.result.metadata.execution_fingerprint` = `<SYMBOL>|open:<candle_open_ms>|SELL`
- `entry.result.metadata.idempotency_key` = `<SYMBOL>|open:<candle_open_ms>|SELL`
- `entry.result.request_id` = `<SYMBOL>|open:<candle_open_ms>|SELL`

The 8 entries, identified by their (never-corrupted) top-level/dict-key
`request_id`, `.jsonl` line index (0-indexed), and `sequence`:

| # | Reconstructed `request_id` (= key in `.migrated`) | `.jsonl` line | `sequence` | `entry.request.timestamp` | Matching audit event (`event_id`) | Audit-to-request delta |
| - | --- | --- | --- | --- | --- | --- |
| 1 | `BNBUSDT\|open:1786112160000\|SELL` | 1 | 0 | 2026-08-07T14:17:56.519814+00:00 | see §5 note | 1.477 ms |
| 2 | `BNBUSDT\|open:1786112400000\|SELL` | 3 | 2 | 2026-08-07T14:21:07.225724+00:00 | see §5 note | 1.496 ms |
| 3 | `BTCUSDT\|open:1786112160000\|SELL` | 5 | 4 | 2026-08-07T14:17:55.900869+00:00 | `0f5ecb9e-560a-4d24-9be9-c326507414c2` | 1.914 ms |
| 4 | `BTCUSDT\|open:1786112400000\|SELL` | 7 | 6 | 2026-08-07T14:21:06.194817+00:00 | see §5 note | 1.705 ms |
| 5 | `ETHUSDT\|open:1786112160000\|SELL` | 11 | 10 | 2026-08-07T14:17:56.211375+00:00 | see §5 note | 1.864 ms |
| 6 | `ETHUSDT\|open:1786112400000\|SELL` | 13 | 12 | 2026-08-07T14:21:06.862766+00:00 | see §5 note | 1.603 ms |
| 7 | `SOLUSDT\|open:1786112160000\|SELL` | 17 | 16 | 2026-08-07T14:17:56.835659+00:00 | see §5 note | 1.597 ms |
| 8 | `XRPUSDT\|open:1786112160000\|SELL` | 21 | 20 | 2026-08-07T14:17:57.141860+00:00 | see §5 note | 1.477 ms |

All 8 entries are `state: NOT_COMMITTED`, `reason: FAILED`,
`result.commit_outcome: NOT_COMMITTED`, `result.error_code:
POSITION_CLOSE_REJECTED` (`POSITION_NOT_FOUND`) — confirming the checkpoint's
finding that all 8 are terminal, non-committing SELLs with no capital,
position, or risk effect. Both `candle_open_ms` values present
(`1786112160000`, `1786112400000`) match the checkpoint's own note that these
two 13-digit values happen to pass the Luhn check, which is why the detector
flagged them.

## 5. Note on the audit-event cross-reference

Only entry #3's matching `event_id` is quoted directly above as a concrete
worked example; the same lookup (symbol + action=SELL + `payload.price`
match + timestamp within ~2 ms, next-nearest candidate >2 s away) was applied
identically and unambiguously to all 8 entries, and in every case the
audit event's `aggregate_id`/`correlation_id` reproduced exactly the same
`SYMBOL|open:<ms>|SELL` string already present in that entry's own
never-corrupted top-level `request_id` field (§2, source 1) and in the
`.migrated` file's dict key for the same entry — i.e. three independent,
mutually agreeing sources per entry, not one.

## 6. What this record does not do

- It does not modify `execution_transaction_journal.jsonl`,
  `execution_transaction_journal.json.migrated`,
  `execution_idempotency.jsonl`, `execution_idempotency.json.migrated`, or
  the audit log — every observation above was a read-only file/JSON read.
- It does not construct `AtlasApplication` or any durable store class; all
  reads were direct file I/O against the operator's real state, per the
  standing rule against runtime state isolation violations.
- It does not mark any field UNKNOWN, because all 72 corrupted field values
  across the 8 entries were reconstructible with certainty from mutually
  agreeing independent sources.
- It does not change EXEC-ID-REDACTION-001's status, severity, or
  disposition in `governance/current/ATLAS_MILESTONE_REGISTRY_v4.85.json`;
  that record already reflects the code fix as
  `IMPLEMENTED_CRITICAL_FINAL_GATE_CLOSED_IN_TESTS_COMMITTED` at
  implementation commit `0506c15`. This record only closes the historical
  remediation for the 8 pre-fix entries left corrupted in the durable store.
- It does not attempt any similar reconstruction for the idempotency store
  or audit log, because both were independently confirmed clean (§3) and
  need no annotation.
