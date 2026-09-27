# ATLAS CHECKPOINT — Execution audit-trail completeness (C1 provenance_ref, C2 recovery rollback markers, C3 rollover refusals)

## Objective
Close three deferred execution-audit-integrity findings as one CRITICAL package, without changing any gate, refusal or rollback logic:
- **C1** (v4.85 F3): preserve `provenance_ref`.
- **C2** (v4.84 LOW-C): make audit events from the recovery tool, and from a rolled-back booking, distinguishable.
- **C3**: record risk-day rollover refusals as audit events.

## Completed
- **C1** (`atlas_security/sensitive_data_guard.py`):
  - New `PROVENANCE_REF_KEYS = {"provenance_ref"}` with prefix `transaction-journal:`.
  - Preserved only when the value is that prefix followed by an id that passes `is_opaque_machine_identifier` and the F1 charset. The 200-character bound applies to the id.
  - Everything else is redacted as before.
- **C2** (`tools/reconcile_execution_authorities.py`):
  - `_ToolOriginAuditStore` stamps `metadata.origin = "tools.reconcile_execution_authorities"` on every event the reused hook writes.
  - After any rollback of an attempt that wrote events, one `RISK_ACCOUNTING_RECOVERY_BOOKING_ROLLED_BACK` event is written. It records the event ids and types left behind, the failure reason, and `risk_accounting_state_restored` (checked on disk).
  - The marker is best-effort.
- **C3** (`core/execution_manager.py`):
  - `_audit_risk_day_rollover_refusal` writes `RISK_ACCOUNTING_DAY_ROLLOVER_REFUSED` next to the unchanged WARNING, for every `_risk_day_rollover_refusal` reason.
  - The pre-write equity abort is also recorded, as `EQUITY_NOT_POSITIVE`, `EQUITY_NOT_FINITE` or `EQUITY_UNREADABLE`.
  - Each distinct (reason, stored_day, today) is written once per manager instance.
  - Nothing is written when audit is disabled.
  - A failed write degrades audit and is retried on the next request.
- An independent audit ran, and its two fixes are applied (see below).
- Full suite run once on the final code.
- Registry v4.88 written.

## Files changed
- Commit `3f253bf`:
  - `atlas_security/sensitive_data_guard.py`
  - `core/execution_manager.py`
  - `tools/reconcile_execution_authorities.py`
  - `tests/test_execution_audit_trail_completeness.py` (new)
- Registry commit:
  - `governance/current/ATLAS_MILESTONE_REGISTRY_v4.88.json`
  - this checkpoint
- Untouched: `web_app.py`, the templates, the migration tool, and `feat/block3-execution-safety`.
- The untracked `.claude/agents/atlas-test-runner.md` is not part of this package and was not staged.

## Architecture decisions
- C1 reuses the `preserve_identifiers` allowlist and gives this field its own grammar, rather than adding it to `OPAQUE_IDENTIFIER_KEYS`. The prefix would push long ids past the 200-character bound.
- C2 stays local to the tool (a subclass of the audit store). Runtime code and events are unchanged. Absence of `origin` means the event came from the runtime.
- C3 deduplicates refusals. Without it, a persisting refusal would append one event per `risk_check`, and the dashboard only scans the tail of the audit log.
- The C3 refusals that are not audited:
  - `AUDIT_DISABLED`: there is no trail to write to.
  - `JOURNAL_LOCK_UNAVAILABLE` and an unreadable stored state: neither proves a rollover is due.

## Tests
- Baseline at `9456caa`: 4962 passed / 1 failed.
  - This equals v4.87.
  - My edits started after collection, while that run was still going.
- New file: 62 tests.
  - C1: a 200k fuzz, the grammar/F1 negative matrix, legacy fixed points, legacy-hashed events verifying, and a round trip through the real stores.
  - C2: 8 tests.
  - C3: all refusal reasons and edge cases.
- Mutation: 10 of 10 mutants killed.
- Targeted regression: 382 passed / 1 failed (the B2 edge).
- **Full suite, final code: 5024 passed / 1 failed / 0 skipped in 481.95s** (4962 + 62).
  - The failure is the accepted B2 `test_forbidden_layer_imports` (the `atlas_finance` edges only).
- One run failed a single test, `test_c2_failed_booking_is_followed_by_a_rollback_marker`.
  - The traceback was not captured.
  - It did not reproduce in 22 later runs or in the full suite.
  - Root cause: **UNKNOWN**.

## Independent audit
- 0 BLOCKING, 0 HIGH, 0 MEDIUM.
- LOW F1 (deferred, CONFLICT recorded in v4.88): the dashboard still says refusals are not audited.
- LOW F2 (fixed): the legacy-hash test could not fail.
- INFO F5: NaN/Infinity relabelled `EQUITY_NOT_FINITE`, and the docstring now names the unaudited `store.load` path. Both fixed.
- INFO F3, F4 and F6: no action needed. The mixed-version trace found no new disagreement class.
- The fixes were verified by targeted runs, not by a second audit.

## Current state
- Committed on `research/edge-validation`.
- Authority unchanged: production=NONE, live=DENIED, autonomous_deployment=DENIED.
- Live verification: NOT_PERFORMED.

## Known issues / risks
- The dashboard's "reddetme sebebi" row is stale:
  - `web_app.py` still returns `NOT_AUDITED_WARNING_LOG_ONLY`.
  - `tests/test_dashboard_adminlte_and_integrity_panels.py:502-503` pins that value.
- The one-off test failure above is unexplained.
- Alternating refusal reasons re-append each time (accepted).
- Earlier open items (v4.86 A2, INFO-1, INFO-3, v4.84 MEDIUM-A) are unchanged.

## Remaining work
- Owner decision on the dashboard CONFLICT: either wire the panel to the latest REFUSED event and update the pinned test, or change only the wording.
- Owner live check on a running instance.

## Next exact action
Owner decides the dashboard refusal-label CONFLICT recorded in v4.88 `conflict_dashboard_refusal_label`.
