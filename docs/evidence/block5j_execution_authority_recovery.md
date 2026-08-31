# Atlas Block 5 / Package 5J Freeze Evidence

## Status

Package 5J closure candidate: PASS.
BLOCKING: 0 remaining (0 introduced)
HIGH: 0 remaining (0 introduced)
MEDIUM NEW: 0 remaining (0 introduced)

Parent HEAD: `a0b3494` ("feat: externalize durable financial state history").

Nothing was pushed.

## Package

Close the two execution-authority recovery findings carried from Package
5H-0:

- **B5H-0-9** — `ExecutionManager.reset()` reset the idempotency state but
  not the transaction journal, which can manufacture `SOURCE_DISAGREEMENT`.
- **B5H-0-12** — there is no safe operator reconciliation path for an
  already-divergent journal/idempotency authority pair.

## Authority Model (reused, not redefined)

Established by Packages 5H-0 and 5I. This package changes none of it.

| authority | file | owns |
| --- | --- | --- |
| transaction journal | `execution_transaction_journal.json` | permanent commit outcome — COMMITTED means the financial side effect happened |
| idempotency store | `execution_idempotency.json` | permanent terminal result / replay answer for a `request_id` |
| applied-execution archive | `execution_applied_executions.jsonl` + `applied_checkpoint` | permanent proof that an `execution_id` / `idempotency_key` was durably applied to the book |

`idempotency_key` **is** the `request_id`
(`core/execution_manager.py:3249`, `:3348`), which is what makes the applied
archive an independent witness keyed by the same identity the other two
authorities use.

## Exact Reset Defect (B5H-0-9)

Pre-5J `ExecutionManager.reset()` (parent `a0b3494`,
`core/execution_manager.py:6124`) executed, under the manager lock:

```
history / rejections / errors      .clear()      # in-memory diagnostics
pending_request_ids                .clear()      # in-memory claim set
completed_request_results          .clear()      # in-memory replay map
_execution_side_effect_ids         .clear()      # in-memory
idempotency_store.reset(delete_file=False)       # DURABLE ERASE + rewrite
stats = _new_stats()
```

The transaction journal was never touched. Two independent consequences:

1. **Manufactured `SOURCE_DISAGREEMENT`.** Every COMMITTED journal entry
   survived while its idempotency counterpart was erased and the emptied
   file rewritten. `FinancialRuntimeSafetyService._authorities_agree`
   (`data_layer/runtime_safety.py:84`) fails exactly on "COMMITTED journal
   entry whose `request_id` is not in `completed_requests`", so
   `assess_recovery` returns `RECONCILIATION_REQUIRED` / `SOURCE_DISAGREEMENT`
   and the next start halts a runtime whose book was healthy a moment
   earlier.
2. **Second execution of an already-executed request.**
   `_claim_request` (`core/execution_manager.py:5765`) answers a duplicate
   from the in-memory `completed_request_results` map alone — it never
   consults the store. Clearing that map, even with the durable file intact,
   is by itself enough to let a replayed `request_id` execute again in the
   current process.

**Reachability.** The production commit sequence is applied-archive →
idempotency record (`_complete_request`, `core/execution_manager.py:1615`) →
`transaction_journal.mark_committed` (`:1684`). Because the journal is
written *last*, no crash can produce "journal COMMITTED with idempotency
missing". `reset()` was the only in-process way to reach that state; the
only other routes are external file loss or tampering. Verified by targeted
search: `ExecutionManager.reset()` had **no caller anywhere in the
repository** — not production, not tests, not tools.

## Final Reset Contract

Option B of the four considered (refuse when durable execution history
exists), combined with removing the durable-erase capability outright. A
reset transaction protocol (option C) was deliberately not built: with no
production caller, making the unsafe behaviour impossible is smaller and
strictly safer than making it atomic.

`ExecutionManager.reset()` now:

- **writes no state file at all.** The `idempotency_store.reset()` call is
  gone from the runtime path entirely — it is not reachable even in the
  clean case where it would be harmless.
- **refuses** with `ExecutionResetRefusedError` (new, module-level in
  `core/execution_manager.py`) carrying one fixed token:

  | token | condition |
  | --- | --- |
  | `EXECUTION_HISTORY_INDETERMINATE` | either authority failed to load, or either exposes a non-`dict` record map. A store that did not load reports zero records, which is indistinguishable from "no history" and is exactly when erasing the other half is most damaging. |
  | `EXECUTION_REQUESTS_IN_FLIGHT` | `pending_request_ids` or `_execution_side_effect_ids` is non-empty |
  | `EXECUTION_HISTORY_PRESENT` | the idempotency store, the journal, or the in-memory replay map holds anything |

- **clears only in-memory diagnostics** (`history`, `rejections`, `errors`,
  `stats`) when it proceeds — which, by the refusal preconditions, is only
  ever on a runtime with no execution history at all.

The single-authority primitives `ExecutionIdempotencyStore.reset()` and
`ExecutionTransactionJournal.reset()` are deliberately unchanged. Neither
store can see its counterpart, so the pairing invariant can only be enforced
where both are held. Both now have no caller in the repository.

## Authority Disagreement Matrix

| class | reachable in production? | classification | disposition |
| --- | --- | --- | --- |
| journal COMMITTED, idempotency missing | no (journal written last); reachable only via the pre-5J reset, file loss, or tampering | `FINANCIAL_APPLICATION_UNPROVEN` until proven, else repair candidate | **SAFE AUTOMATIC REPAIR** only with full three-authority proof (Case A); otherwise refuse |
| journal COMMITTED, idempotency payload mismatch | no | `AUTHORITY_RESULT_CONFLICT` | **OPERATOR RECONCILIATION ONLY** — refuse |
| idempotency terminal result exists, journal absent | no | `JOURNAL_ENTRY_ABSENT` | **UNRECOVERABLE WITHOUT EXTERNAL EVIDENCE** — refuse |
| journal NOT_COMMITTED, idempotency record claims `commit_outcome: COMMITTED` | no | `AUTHORITY_RESULT_CONFLICT` | **OPERATOR RECONCILIATION ONLY** — refuse |
| journal state/result malformed or incomplete | no | `JOURNAL_ENTRY_MALFORMED` | refuse |
| journal PREPARED / COMMIT_STATUS_UNKNOWN | **yes** — a crash mid-commit | `JOURNAL_UNRESOLVED` | refuse, and block all other reconciliation in the book |
| duplicate / conflicting applied identities | no | `APPLIED_AUTHORITY_CONFLICT` / `APPLIED_AUTHORITY_CORRUPT` (raised by the archive's own `load_index()`) | refuse |
| either authority file unreadable | on corruption | `JOURNAL_UNREADABLE` / `IDEMPOTENCY_UNREADABLE` | refuse |

## Reconciliation Tool (B5H-0-12)

`tools/reconcile_execution_authorities.py`. Verify-first, fail-closed,
dry-run by default (`--apply` opts in; `--dry-run` is an explicit spelling of
the default and is a usage error when combined with `--apply`). `--json`
mirrors the existing operator tools. Exit codes match ADR-0005's contract:
`0` agreed / dry run / repaired, `1` usage, `2` action required, `3` repair
attempted and failed.

### No-guessing principle

The tool never decides which authority is right. It repairs only by
**copying an existing authority's payload**, never by deriving one from
partial evidence, and only when three independent durable authorities agree
on one unique terminal truth. Where they do not, it refuses — it does not
pick a side, does not reconstruct money movement, and does not fall back to
the audit log (which is supporting evidence, never a correctness authority,
and is not read by this tool at all).

It also refuses **wholesale**: if any disagreement class is present anywhere
in the book, nothing is written, even for candidates that would otherwise be
provable. An operator resolves the open question first.

### Exact safe reconciliation case (Case A — the only one)

All four conditions, per candidate:

1. journal entry state is `COMMITTED` and its `result` is a complete
   self-consistent success — `success is True`, `status` in
   `ExecutionManager.SUCCESS_STATUSES` (imported, not restated, so the tool
   cannot drift from the runtime), `commit_outcome == "COMMITTED"`,
   `result["request_id"]` equal to the entry key, non-empty `execution_id`;
2. the idempotency store loaded cleanly and holds no record for that
   `request_id`;
3. `AppliedExecutionArchiveStore.load_index().by_idempotency_key[request_id]`
   exists and its `execution_id` equals the journal result's;
4. `ExecutionPortfolioFoundation(...).ready` is `True` — the runtime's own
   loader, which requires the working file to parse, no transition pending,
   and both checkpoints to agree field-for-field with their sidecars' durable
   tails. This is what proves every applied record up to the tail is
   confirmed-committed financial state, including non-tail records.

Repair: `ExecutionIdempotencyStore.record(request_id, journal_result)` — the
journal's own result, copied field for field.

**Field equivalence.** On the production path the journal stores
`sanitize_sensitive_data(result)` (`_mark_terminal`) and the idempotency
store stores the same sanitized payload plus its own
`idempotency_recorded_at` stamp (`record()`). The recreated record is
therefore byte/field-identical to what the original write produced, with
`idempotency_recorded_at` — repair provenance, no financial meaning — as the
only permitted difference. Proven directly by test E, which compares the
repaired record against both the journal result and the record the healthy
book originally held.

### Exact refused cases

`JOURNAL_UNRESOLVED`, `JOURNAL_ENTRY_MALFORMED`, `AUTHORITY_RESULT_CONFLICT`,
`JOURNAL_ENTRY_ABSENT`, `FINANCIAL_APPLICATION_UNPROVEN`,
`APPLIED_AUTHORITY_CORRUPT`, `APPLIED_AUTHORITY_CONFLICT`,
`JOURNAL_UNREADABLE`, `IDEMPOTENCY_UNREADABLE`, `STATE_DIRECTORY_ABSENT`.
Refusal order is fixed (`_REFUSAL_PRIORITY`) so a book holding several
classes always reports the same reason code.

Case B (idempotency result present, journal absent) is refused explicitly
and permanently: the journal carries commit-outcome and lifecycle state
(`prepared_at`, the prepared request payload) that a terminal result never
contained. Reconstructing it would fabricate evidence.

Case C (both present, differing) is refused as a conflict. Case D (no
applied-authority proof for a claimed successful financial execution) is
refused as `FINANCIAL_APPLICATION_UNPROVEN`.

### Write safety

- The idempotency store is the **only** file the tool can write. The
  journal, both sidecars, the financial-state file, and the audit log are
  never modified — proven byte-for-byte by test O.
- The pre-run idempotency file bytes are captured before any write. Every
  failure path after that restores them atomically (temp + `os.replace`), or
  removes the file if the run created it from nothing.
- Post-write, **all** authorities are reloaded from disk through their own
  public loaders — never the in-memory objects that produced the write — and
  the tool re-runs the runtime's own gate,
  `FinancialRuntimeSafetyService.assess()`. `RECONCILED` is reported only if
  every check passes; otherwise originals are restored and the exit code is
  non-zero.
- Post-write also verifies that the repair was purely **additive**: every
  pre-existing record is byte-equal to what it was, and none disappeared.

### Canonical evidence validation — scoped, not faked

`CanonicalExecutionEvidenceAdapter` is run as a post-write gate **only
within its own declared domain**: a book whose COMMITTED executions are all
BUYs. The adapter is the projection-replay contract for evidenced LONG
*opening* executions and raises `IntegrityViolation` on any COMMITTED SELL by
design (`data_layer/canonical_evidence.py:84`); the runtime only wires it
when a relational storage backend exists, which the default
`FinancialRuntimeSafetyService` construction does not. Running it over a book
holding a committed SELL would fail a perfectly healthy repair, so it is
applied where it is meaningful and skipped — not stubbed, not weakened —
where it is not.

## Restart / Replay Proof

- **Restart** (test F): after a repair, a fresh `ExecutionManager` built from
  freshly loaded stores starts with `running is True`,
  `execution_halted is False`, `recovery_required is False`.
- **Replay** (test G): after a repair, replaying the original `request_id`
  through a fully wired manager returns `duplicate_reason ==
  "DUPLICATE_REQUEST_COMPLETED"` with `idempotency.cache_hit is True` and the
  original `execution_id`, and the counting paper trader records
  `open_count == 0` — no second execution.

## Output-Safety Proof (ADR-0005)

All new operator reason codes are fixed tokens. No `request_id`,
`execution_id`, `position_id`, `order_id`, state-file content, or raw
exception text reaches stdout — only outcome, reason code, counts, and the
`sanitize_sensitive_text`-filtered state-directory path. Unlike
`tools/migrate_execution_financial_state.py`, this tool never embeds
exception text in a reason code.

Test N drives the CLI as a subprocess over a book whose every identifier is
a `SECRET-*` marker, in all four flag combinations plus the successful
repair path, and asserts none of `SECRET-REQUEST-ID`, `SECRET-EXEC-ID`,
`SECRET-POSITION-ID`, `SECRET-ORDER-ID`, nor any raw payload fragment
(`filled_quote_notional`, `commit_outcome`, `completed_requests`,
`PAPER_EXECUTED`, `order_id`) appears on stdout or stderr.
`ExecutionResetRefusedError`'s message is asserted to be the fixed token
alone. ADR-0005 gained a section 6 documenting the tool, its outcomes, and
every reason code.

## Exact Test Counts

New module `tests/test_block5j_execution_authority_recovery.py`: **30 tests,
30 passed**, covering A–O of the package's discriminating requirements —
reset asymmetry witness (A), production reset refusal in four forms plus
proof the store's reset is now unreachable (B), fail-closed genuine
disagreement (C), the safe repair (D), field equivalence (E), restart (F),
replay (G), conflict and orphan refusals (H), application-proof refusals in
two forms (I), five corruption/malformation refusals (J), dry-run byte
invariance plus the mutually-exclusive-flag usage error (K), restore-on-
failure (L), non-success reporting and unpersistable repair (M), output
safety in two forms (N), and mutation scoping plus healthy-book agreement
(O).

Discrimination: test A reproduces the defect mechanism directly at the store
level and asserts `SOURCE_DISAGREEMENT`; the test-B family asserts
`ExecutionResetRefusedError`, a symbol that does not exist at parent
`a0b3494`, so those tests cannot pass against the pre-fix code.

## Validation Executed

1. Focused: `tests/test_block5j_execution_authority_recovery.py` — **30
   passed**.
2. Direct regression, one grouped command — `test_block5h0_*`,
   `test_block5i_*`, `test_phase2_runtime_safety_integration`,
   `test_phase2_canonical_evidence_adapter`, `test_durable_transaction_state`,
   `test_deprecated_execution_state_recovery`, the three
   `test_exchange_manager_idempotency*` modules,
   `test_runtime_distribution_boundary`, `test_block3_operator_bootstrap_cli`,
   and `tests/architecture` — **184 passed**.
3. Full `tests/` — run exactly once, on the final code state: **2316
   passed, 0 failed** (`python -m pytest tests`, ASCII `--basetemp`). No
   overlapping intermediate group was run.

No architecture regeneration was required: `packaging/atlas_architecture_map.json`
does not enumerate `tools/`, and this package adds no import edge between
existing layers.

## Exact Production Files Changed

| file | change |
| --- | --- |
| `core/execution_manager.py` | new module-level `ExecutionResetRefusedError`; new `_reset_refusal_reason()`; `reset()` rewritten — durable erase removed, refuses on any durable/indeterminate/in-flight state, clears in-memory diagnostics only |
| `tools/reconcile_execution_authorities.py` | new operator tool (verify-first reconciliation) |
| `docs/adr/0005-operator-bootstrap-runbook.md` | new section 6: the tool, its outcomes, exit codes, reason codes, and the reset contract change |
| `tests/test_block5j_execution_authority_recovery.py` | new focused test module |
| `docs/evidence/block5j_execution_authority_recovery.md` | this document |

No existing test file was modified, weakened, or deleted.

## Findings Closed

- **B5H-0-9** — reset asymmetry: **CLOSED**. The durable erase is removed
  from the runtime path and the operation refuses whenever durable execution
  history exists, so it can no longer manufacture `SOURCE_DISAGREEMENT` or
  discard committed financial evidence.
- **B5H-0-12** — operator reconciliation path: **CLOSED**.
  `tools/reconcile_execution_authorities.py` provides a verify-first,
  fail-closed path with exactly one proven repair and an explicit refusal
  contract for every other class.

## Carried Forward (explicitly NOT fixed by this package)

Recorded accurately; none is required by 5J correctness.

- idempotency store full-file rewrite growth / write amplification
- transaction journal growth (full-file rewrite per state transition)
- audit growth
- startup O(history)
- no sidecar retention / pruning
- Package 5I LOW findings L-3 and L-4
- **B5J-1 (LOW, new, not fixed):**
  `tools/migrate_execution_financial_state.py` embeds truncated raw
  exception text in its `MIGRATION_WRITE_FAILED:` reason code, which is a
  deviation from ADR-0005's fixed-token rule. Noticed while mirroring that
  tool's structure; unrelated to 5J correctness and deliberately not changed
  inline.

### Growth analysis (section 9 — deliberate deferral)

This package did not naturally expose a safe append-only replacement for the
journal/idempotency full-file rewrites. The reconciliation tool performs at
most one `save()` per run (candidates are recorded with `save=False` and
persisted once), so it adds no new write amplification, and `reset()` now
performs zero writes where it previously rewrote the whole idempotency file.
Storage redesign remains deferred to a future package. Correctness first.

## PAPER / LIVE

PAPER-only throughout. The tool constructs no `AtlasApplication`, no
execution manager, and no exchange adapter; it carries no LIVE authority and
cannot start trading. Every test uses an isolated `tmp_path` state
directory.

## Push Status

Nothing pushed.

## Limits of This Evidence

- The post-write gates (`POST_REPAIR_*`) are defence in depth: the pre-write
  proof requirements are strict enough that no natural input is known to
  reach them, so tests L and M inject the failure to exercise the restore
  path rather than claiming a reachable production scenario.
- The tool's repair is proven correct for the class described. It makes no
  claim about books whose divergence arose from causes outside the three
  authorities it reads.
- "No caller anywhere" for `ExecutionManager.reset()` is a
  repository-wide search result at parent `a0b3494`, excluding
  `_quarantine/` and `archive_unused_*`; it does not constrain callers
  outside this repository.
