# ATLAS CHECKPOINT — EXEC-ID-REDACTION-001: opaque execution identifiers preserved by field identity (v4.85)

## Objective
The redactor was corrupting opaque identifiers stored by the transaction journal, the idempotency store and audit events. This package:
- assesses the real-world impact read-only;
- fixes the corruption by field identity, not by tuning the detector;
- leaves free-text redaction unchanged.

Classification: CRITICAL (execution, audit and recovery durable state). The full final gate applied.

## Completed
- Real-state impact scan, read-only. Originals were sha256-verified unchanged afterwards.
- Every gate step is done: IMPLEMENT, TEST (fuzz), SELF-REVIEW (mutation), REGRESSION, INDEPENDENT AUDIT, FIX, and a full-suite RE-TEST.
- Registry `governance/current/ATLAS_MILESTONE_REGISTRY_v4.85.json` is additive to v4.84. It changes the 3 header fields and adds one member, `execution_identifier_redaction_fix_result`.
- **Nothing is committed.** The tree also still holds the uncommitted v4.84 package (see the prior checkpoint `20260926T160000Z_recovery-risk-accounting-booking.md`).

## Real-world impact (C:\AtlasState\memory_data)
- **Journal `.jsonl`: 8 of 22 entries are corrupted**, 72 field values in total. The affected fields are `request_id`, `idempotency_key`, `execution_fingerprint` and `candle_identity`, in both the request and the result. The 13-digit candle-open ms values `1786112160000` and `1786112400000` pass the Luhn check.
  - All 8 entries are terminal NOT_COMMITTED SELLs.
  - The envelope key is intact.
  - No `execution_id` is affected.
  - There is no capital, position or risk effect.
- `execution_transaction_journal.json.migrated` (retired v1) holds the same corruption.
- The idempotency log (12 records) and the audit log (130 events, chain valid) have 0 corrupted values.
- **Not repaired**, per the never-edit-history convention. Any remediation is an owner decision; a possible form is an additive annotation record.
- The task premise understated the rate. Candle request_ids are corrupted about **10%** of the time (9994/100000); uuid4 values about 0.23%.

## Files changed (this package)
- `atlas_security/sensitive_data_guard.py`:
  - `OPAQUE_IDENTIFIER_KEYS`, `DIGEST_KEYS`, a charset guard, `is_opaque_machine_identifier` and `_preserved_identifier`;
  - the `preserve_identifiers` kwarg, threaded through every recursion branch;
  - a disjointness RuntimeError;
  - the shared constants `MAX_IDENTIFIER_LENGTH` and `FORBIDDEN_IDENTIFIER_CHARACTERS`.
- `atlas_security/__init__.py` re-exports the two constants.
- `core/model_provider_contracts.py` imports those constants. Their values are unchanged.
- Opt-ins: `core/execution_transaction_journal.py` (4), `core/execution_idempotency_store.py` (1) and `core/audit_event.py` (1).
- `tests/test_execution_identifier_preservation.py` is new, with 104 tests.
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.85.json` is new.
- Unchanged:
  - the detectors;
  - `tools/migrate_execution_authority_logs.py`, which must mirror the v1 loader;
  - the event-bus publishers;
  - execution, risk and capital logic;
  - the v4.84 recovery mechanism.

## Architecture decisions
- Preservation works by exact key identity, and only for the execution authorities that opt in. A preserved value must be:
  - structurally valid: a string, not whitespace-padded, at most 200 characters, with no CR/LF/TAB/NUL;
  - inside `[A-Za-z0-9|:._-]`.
- Anything else falls back to the old redaction. Nothing is ever rejected or repaired.
- A digest is preserved only if it is exactly 64 lowercase hex characters.
- A sensitive key name still wins.

## Tests
- Fuzz with zero corruption:
  - 100k uuid4 and 100k candle ids across 8 keys (1.6M checks);
  - 50k digests.
  - The same corpus is corrupted without the switch, so the tests discriminate.
- Store round trips: 150 corrupting pairs each for the journal, idempotency store and audit store, reloaded from disk.
- Mutation testing: 9 of 10 mutants were killed. The survivor is equivalent, because the key sets are disjoint. Removing the charset guard makes 48 tests fail.
- **Full suite on the final code: 4737 passed / 1 failed / 0 skipped in 657.20s.** That is 4600 + 33 (v4.84) + 104. The failure is the accepted B2 `test_forbidden_layer_imports`, with `atlas_finance` edges only.
- The first full run gave 4736/2. `model_provider_contracts` was importing a submodule, which broke the Package-3 layer test. The code was fixed; the test was not touched.

## Independent audit
- BLOCKING and HIGH: none.
- F1 (MEDIUM): fixed. A free-text channel existed under identity key names; the charset guard closes it.
- F2 (MEDIUM): accepted and documented. The audit hash chain is **forward-only**. Events written after this fix that preserved a Luhn-positive id will not verify under pre-fix code, so a revert is hazardous once new events exist. This is pinned by a test.
- F3 (LOW): deferred. `provenance_ref` still embeds a redacted request_id. It has no byte-exact consumer, and it needs its own grammar before it can be preserved.
- F4 (LOW): ids that sit directly inside lists are not preserved. This is pinned by a test.
- F5: the migration tool is confirmed sound.
- F6: fixed; the check is now an explicit raise.
- F7: the gaps are fixed.

## Current state / risks
- Uncommitted.
- Authority: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- Live-instance verification: NOT_PERFORMED.
- Rollback hazard: see F2.

## Remaining work
Owner:
- Commit order: first v4.84 (implementation commit, then registry commit), then this package (implementation commit, then v4.85 commit).
- Fill in `implementation_commit` and `predecessor_registry_commit` in v4.85 before committing it.
- Decide on remediation for the 8 historical journal entries.
- Schedule F3.

## Next exact action
After v4.84 is committed, stage and commit:
- `atlas_security/__init__.py`
- `atlas_security/sensitive_data_guard.py`
- `core/audit_event.py`
- `core/execution_idempotency_store.py`
- `core/execution_transaction_journal.py`
- `core/model_provider_contracts.py`
- `tests/test_execution_identifier_preservation.py`

Then update the v4.85 hashes and commit the registry together with this checkpoint.
