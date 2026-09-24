# ADR-0005: Operator Financial-State Bootstrap Entry Point and Runbook

## Status

Accepted. Block 3 / Package 2 (M-F). Builds on ADR-0003 (and its Block-3
amendment), which defines the bootstrap contract itself.

## Context

ADR-0003 established `bootstrap_financial_state()` as the only explicit path
that creates initial durable financial state, and its Block-3 amendment made
the result truthful about existing state (`CREATED` / `VALID_EXISTING` /
`INVALID_EXISTING` / `FAILED`).

What was still missing was a safe operator *workflow*. To bring up a fresh
PAPER environment an operator had to open a Python REPL, know the names of
three separate state files, know that the state directory is anchored to the
installation rather than the working directory, and supply a
`policy_version` string by hand. Nothing told them which version string the
runtime would actually accept — ADR-0003's own example and the Package-2C
test fixtures used `"v1"`, while `RiskPolicy.version` is `"phase3-risk-v1"`.
Bootstrapping with the documented value produced state that every order
would be rejected against.

There was also no machine-detectable failure signal: an automated
provisioning step had no exit code to branch on.

## Decision

`tools/bootstrap_financial_state.py` is the supported operator entry point.

```
python tools/bootstrap_financial_state.py --state-directory PATH [options]
```

| flag | meaning |
| --- | --- |
| `--state-directory PATH` | **Required.** No default; never resolved against the CWD. |
| `--total-capital DEC` | Override canonical total capital. Positive finite decimal. |
| `--policy-version STR` | Override canonical risk policy version. |
| `--today-utc YYYY-MM-DD` | Deterministic UTC accounting date (testing input). |
| `--json` | Structured output instead of the human table. |
| `--verify-only` | Validate only. Creates and modifies nothing. |

Exit codes:

| code | meaning |
| --- | --- |
| `0` | every store `CREATED` or `VALID_EXISTING` |
| `1` | CLI usage / argument error |
| `2` | at least one `INVALID_EXISTING` — operator action required, nothing was touched |
| `3` | at least one `FAILED` — bootstrap could not complete |

`argparse` exits `2` on usage errors by default, which would be
indistinguishable from `INVALID_EXISTING` — a provisioning script would read
a mistyped flag as corrupt financial state. The parser therefore overrides
`error()` to exit `1`. An explicitly blank `--policy-version` is likewise a
usage error rather than a silent fallback to the canonical version.

There is deliberately no `--force`, `--repair`, `--overwrite`, `--live`, no
execution-mode switch, and no migration flag. The tool never constructs
`AtlasApplication` or an execution manager, so it carries no LIVE authority
and cannot start trading.

**Canonical defaults are derived, never duplicated.** When
`--total-capital` / `--policy-version` are omitted, the CLI builds
`CapitalManager()` → `RiskPolicy(total_capital=…)` — exactly what the
composition root does — and reads `total_capital`, `allocatable_capital`,
and `version` off that policy. No financial literal (`10000`,
`phase3-risk-v1`, `0.8`) is copied into the CLI or into
`core/financial_state_bootstrap.py`; a test asserts their absence in both.
This is what makes B4 hold: bootstrap and runtime cannot silently disagree,
because by default they read the same source.

`core/financial_state_bootstrap.py` stays on plain parameters and does not
import `RiskPolicy` or `CapitalManager`, so no new core architecture edge is
introduced. Composition is the CLI's job.

**Output safety.** Only `store | path | outcome | reason_code` is printed
(or its JSON equivalent). State-file contents are never emitted, reason
codes are fixed tokens rather than raw exception text, and every free-text
field passes through `sanitize_sensitive_text` before output.

## Runbook

### 0. Which state directory to pass

Every command below takes `--state-directory` explicitly; the tools have no
default and never resolve the path against the CWD. Pass the directory the
*runtime* will actually open, which is not always the installation default:

- If `ATLAS_STATE_DIRECTORY` is set, it **takes precedence** over
  `core/application.py`'s `DEFAULT_STATE_DIRECTORY`, and the runtime opens
  the override. Pass that same path to these tools, or they will inspect and
  bootstrap a directory the runtime never reads.
- If it is unset, the runtime falls back to the installation default
  (`<repo>/memory_data`), and that is the path to pass.

The same relationship holds between `ATLAS_MARKET_ARCHIVE_DIRECTORY` and
`DEFAULT_MARKET_ARCHIVE_DIRECTORY` for the historical market-data archive,
and between `ATLAS_EVIDENCE_DIRECTORY` and `DEFAULT_EVIDENCE_DIRECTORY` for
the research Evidence Store (ADR-0008). **None** of the three variables is
created by the runtime: an override that is present but does not point at an
existing absolute directory is a startup failure, never a silent fallback
(see ADR-0007).

There are therefore three operator-relocatable roots:

| Variable | Default | Operator target | Holds |
| --- | --- | --- | --- |
| `ATLAS_STATE_DIRECTORY` | `<repo>/memory_data` | `C:\AtlasState\memory_data` | Execution/financial state |
| `ATLAS_MARKET_ARCHIVE_DIRECTORY` | `<repo>/data/market_archive` | `C:\AtlasState\market_archive` | Historical market data |
| `ATLAS_EVIDENCE_DIRECTORY` | `<repo>/evidence_store` | `C:\AtlasState\evidence_store` | Research claims (ADR-0008) |

On this deployment as of 2026-09-18 the first two overrides are set and the
live durable root is `C:\AtlasState\memory_data` (archive:
`C:\AtlasState\market_archive`), which is why the examples below name them.
Confirm the values in force before running anything:

```
echo %ATLAS_STATE_DIRECTORY%
echo %ATLAS_MARKET_ARCHIVE_DIRECTORY%
echo %ATLAS_EVIDENCE_DIRECTORY%
```

**`ATLAS_EVIDENCE_DIRECTORY` is not yet set on this deployment, and
`C:\AtlasState\evidence_store` does not yet exist.** No directory is ever
created automatically — not the override and not the installation default —
so until one is provisioned, Atlas starts normally, logs that the evidence
store could not be opened, and records no research evidence. That is
fail-open by design, not a fault. To enable it, create the directory first
and set the variable second — the order matters, because a variable pointing
at a directory that does not exist is refused at startup:

```
mkdir C:\AtlasState\evidence_store
setx ATLAS_EVIDENCE_DIRECTORY C:\AtlasState\evidence_store
```

`setx` is per-user and persists across restarts; the supervisor hands its
child a full copy of `os.environ`, so it survives every supervised restart.
Open a fresh terminal and echo the value back before restarting Atlas — the
shell that ran `setx` does not see it. The change takes effect on Atlas's
next ordinary restart; no migration or data move is involved, because this
is a new subsystem rather than a relocation. The Evidence Store is also the
one durable store Atlas will start *without*: if it cannot be opened,
startup logs the failure and continues, and the failure stays visible in
`EvidenceStore.health()`.

### 1. Fresh PAPER environment

```
python tools/bootstrap_financial_state.py --state-directory C:\AtlasState\memory_data
```

Expect exit `0` and three `CREATED` rows. Atlas can now start. This is
PAPER-only; nothing in this workflow grants live-trading authority.

### 2. Existing valid environment / restart / recovery

```
python tools/bootstrap_financial_state.py --state-directory C:\AtlasState\memory_data --verify-only
```

Expect exit `0` and three `VALID_EXISTING` rows. `--verify-only` is the
correct pre-flight check before restarting Atlas: it creates nothing,
modifies nothing, and validates each store through the same loader the
runtime uses. Re-running without `--verify-only` against a healthy directory
is also safe — it reports `VALID_EXISTING` and leaves every file untouched.

A store that is absent under `--verify-only` is reported
`INVALID_EXISTING` / `STATE_ABSENT` (exit `2`) rather than being created;
use the plain run when you intend to create.

### 3. Corrupt state

Exit `2` with `INVALID_EXISTING` and a reason code identifying the store:
`RISK_STATE_UNREADABLE`, `RISK_STATE_SCHEMA_INVALID`,
`RESERVATION_STATE_UNREADABLE`, `RESERVATION_SCHEMA_INVALID`,
`RESERVATION_DUPLICATE_ID`, `FINANCIAL_STATE_RECOVERY_REQUIRED`,
`FINANCIAL_TRANSITION_RECOVERY_REQUIRED`, `FINANCIAL_STATE_INVALID`,
`FINANCIAL_MIGRATION_REQUIRED`.

Cross-checkpoint validation against the two Block 5I sidecars
(`execution_applied_executions.jsonl` / `execution_closed_positions.jsonl`)
can additionally report `FINANCIAL_APPLIED_AUTHORITY_DIVERGENT`,
`FINANCIAL_APPLIED_AUTHORITY_MISSING`, `FINANCIAL_APPLIED_AUTHORITY_CORRUPT`,
`FINANCIAL_APPLIED_AUTHORITY_CONFLICT`, `FINANCIAL_CLOSED_AUTHORITY_DIVERGENT`,
`FINANCIAL_CLOSED_AUTHORITY_MISSING`, `FINANCIAL_CLOSED_AUTHORITY_CORRUPT`,
`FINANCIAL_CLOSED_AUTHORITY_CONFLICT`, or `FINANCIAL_CLOSED_POSITION_LIVE_CONFLICT`
— always one of these fixed tokens, never the underlying exception's raw
text. `ExecutionPortfolioFoundation`'s own internal diagnostic for a corrupt
or conflicting sidecar embeds the specific execution_id/idempotency_key/
position_id/archive line number involved, which is useful for an operator
reading logs directly but must never appear in this tool's output;
`core/financial_state_bootstrap.py`'s `_classify_financial_foundation_reason`
maps every such internal diagnostic to one of the tokens above before it
ever becomes a `reason_code`.

The tool does not repair, overwrite, or delete anything — the file is left
byte-for-byte as found. Resolution is a deliberate operator decision:
inspect the named file, restore it from your own backup, or move it aside
and re-run to create fresh state for that store. Moving a financial-state
file aside discards the accounting history it represents; treat that as a
decision with financial consequences, not a cleanup step.

`FINANCIAL_TRANSITION_RECOVERY_REQUIRED` specifically means a write was
interrupted mid-transition. Do not create fresh state over it without first
establishing what the interrupted transition did. In a PAPER runtime,
section 7 below is the supported procedure for establishing it.

`FINANCIAL_MIGRATION_REQUIRED` (Block 5I) means `execution_financial_state.json`
is still on the legacy schema_version 1, which held `closed_positions` and
`applied_executions` inline instead of in the current schema_version 2
layout's two immutable sidecars. This tool never migrates it — moving state
aside here would discard that accounting history exactly as any other
manual move would. Run the dedicated, explicit migration tool instead:

```
python tools/migrate_execution_financial_state.py --state-directory C:\AtlasState\memory_data
```

It rewrites `execution_financial_state.json` in place as schema_version 2
and populates `execution_applied_executions.jsonl` /
`execution_closed_positions.jsonl` from the v1 file's contents exactly, then
`--verify-only` against this bootstrap tool reports `VALID_EXISTING`. See
that tool's own module docstring for its idempotency/resumability and
refusal contract — it is a separate, standalone operator workflow, not a
flag on this one.

### 4. Policy mismatch

Exit `2` with `INVALID_EXISTING` / `POLICY_VERSION_MISMATCH` on
`risk_accounting_state` means the durable state was written under a
different risk policy version than the one the runtime will enforce. Left
unresolved, every order is rejected at
`execution_manager` with `RISK_STATE_RESTORATION_FAILED`.

Decide which side is authoritative. If the runtime policy is correct, the
existing risk state belongs to a superseded policy and must be retired
deliberately. Do not "fix" this by passing `--policy-version` to match the
old file — that only re-labels the mismatch and leaves the runtime rejecting
orders.

`INVALID_EXISTING` / `CAPITAL_MISMATCH` on `capital_reservations` means
reservations already on disk exceed the allocatable capital implied by
current policy (`total_capital` minus the cash reserve). Either capital was
lowered below outstanding commitments, or the reservation ledger holds
encumbrances that should have been released.

### 5. Legacy `paper_trades.json`

**There is no automatic migration, and there will not be one here.** The
bootstrap tool never reads, moves, deletes, imports, or migrates the legacy
root-level `paper_trades.json`; a test asserts the tool does not reference
it at all and that an adjacent `paper_trades.json` is byte-identical after a
run.

Any migration of legacy paper-trading history into the current durable
stores is a separate, explicit operator workflow that does not exist yet.
Until it does, treat the legacy file as read-only historical data.

### 6. `SOURCE_DISAGREEMENT` at startup (Block 5J)

Atlas halts with `SOURCE_DISAGREEMENT` when the execution transaction
journal holds a COMMITTED entry whose counterpart is missing from the
execution idempotency store. The journal owns the commit outcome; the
idempotency store owns the terminal result a replayed request must be
answered with. Starting with one half missing would let an already-executed
request execute a second time, so the runtime refuses.

```
python tools/reconcile_execution_authorities.py --state-directory C:\AtlasState\memory_data
```

The tool is verify-first: without `--apply` it reports and writes nothing.
`--dry-run` is an explicit spelling of that default and cannot be combined
with `--apply`. Exit codes follow the same contract as the tools above
(`0` agreed / dry run / repaired, `1` usage, `2` action required, `3` repair
attempted and failed with the idempotency file restored byte-for-byte).

Outcomes are `AUTHORITIES_AGREE`, `WOULD_RECONCILE`, `RECONCILED`,
`RECONCILIATION_REQUIRED`, `STATE_INVALID`, `FAILED`, with these fixed
reason codes:

| reason code | meaning |
| --- | --- |
| `AUTHORITIES_ALREADY_AGREE` | nothing to reconcile |
| `DRY_RUN` | a repair is provable; `--apply` would perform it |
| `RECONCILIATION_COMPLETE` | repaired and verified |
| `STATE_DIRECTORY_ABSENT` | no such state directory |
| `JOURNAL_UNREADABLE` / `IDEMPOTENCY_UNREADABLE` | that authority did not load |
| `APPLIED_AUTHORITY_CORRUPT` / `APPLIED_AUTHORITY_CONFLICT` | the immutable applied-execution archive is torn or self-contradictory |
| `JOURNAL_UNRESOLVED` | a PREPARED / COMMIT_STATUS_UNKNOWN entry exists — resolve it first |
| `JOURNAL_ENTRY_MALFORMED` | a journal entry's state or result is not a complete, self-consistent record |
| `AUTHORITY_RESULT_CONFLICT` | both authorities hold a record and they disagree |
| `JOURNAL_ENTRY_ABSENT` | a terminal result exists with no journal entry |
| `FINANCIAL_APPLICATION_UNPROVEN` | no applied-execution record (or no clean book) proves the execution was applied |
| `IDEMPOTENCY_WRITE_FAILED` | the repair could not be persisted |
| `POST_REPAIR_VERIFICATION_FAILED` / `POST_REPAIR_RUNTIME_NOT_READY` / `POST_REPAIR_EVIDENCE_INVALID` | the write landed but a post-write gate refused it; originals restored |

**The tool repairs exactly one class**: a journal entry that is COMMITTED
with a complete successful result, whose `request_id`/`execution_id` an
immutable applied-execution record proves was financially applied, in a book
that loads cleanly — and that has no idempotency record. The repair copies
the journal's own result into the idempotency store field for field. It is a
copy of an existing authority, never a derivation from partial evidence.

Everything else refuses, including the reverse direction: a journal entry is
never reconstructed from a terminal result, because commit-outcome and
lifecycle semantics are not recoverable from one. A book holding any other
disagreement class refuses wholesale, so nothing is written while an
unresolved question remains. The idempotency store is the only file this
tool can ever write; the journal, both sidecars, the financial-state file,
and the audit log are never modified.

> **Amended 2026-09-24 (execution reconciliation audit, finding F-1).** The
> sentence above remains true of the *repair* described in this section. The
> same tool gained a second, separately gated capability - PAPER-only recovery
> of an interrupted execution, section 7 - which does write the journal, the
> idempotency store, the reservation ledger, and (to clear or complete an
> interrupted transition) the financial-state file and its sidecars. It runs
> only when `--execution-mode PAPER` is given; without that flag the tool
> behaves exactly as this section describes. The audit log is still never
> written.

Output safety is the same as the tools above: fixed reason-code tokens,
outcomes, counts, and the sanitized state-directory path only. No
`request_id`, `execution_id`, `position_id`, `order_id`, state-file content,
or raw exception text is ever printed.

Note that no *runtime* operation can produce this divergence any more.
`ExecutionManager.reset()` used to erase the idempotency authority while
leaving the journal intact; as of Block 5J it writes no state file at all and
refuses (`ExecutionResetRefusedError`, reason `EXECUTION_HISTORY_PRESENT` /
`EXECUTION_REQUESTS_IN_FLIGHT` / `EXECUTION_HISTORY_INDETERMINATE`) whenever
durable execution history exists.

### 7. `UNRESOLVED_JOURNAL` after an interrupted PAPER execution (F-1)

A process killed between the journal PREPARE and the journal COMMITTED event
leaves one PREPARED entry, and every restart halts with the unresolved
journal (and, if the kill landed inside the durable application itself,
`FINANCIAL_TRANSITION_RECOVERY_REQUIRED`). In a PAPER runtime the outcome is
decidable from durable evidence, so the reconcile tool can resolve it:

```
python tools/reconcile_execution_authorities.py --state-directory C:\AtlasState\memory_data --execution-mode PAPER
python tools/reconcile_execution_authorities.py --state-directory C:\AtlasState\memory_data --execution-mode PAPER --apply
```

Run the dry run first: `WOULD_RECOVER` names the class the `--apply` run will
perform. Classes, ground truth first:

| recovery class | evidence | resolution |
| --- | --- | --- |
| `ABORT_NOT_APPLIED` | no applied-execution record and no terminal result; the book is clean, or holds only this request's transition marker with nothing appended to either sidecar | marker cleared, RESERVED capital released, entry NOT_COMMITTED (the request stays retryable) |
| `COMMIT_APPLIED_EVIDENCE` | the applied-execution archive holds the request's record and the book loads cleanly | reservation committed, terminal result recorded if missing, entry COMMITTED. The result is the recorded idempotency result when one exists; otherwise it carries only proven identity fields and a `recovery` block, never recomputed fill figures |
| `COMMIT_PAPER_REDERIVATION` | the transition marker is still present but a sidecar record was already appended (append-only, so it cannot be undone) | the fill is re-derived with ExecutionManager's own paper-fill logic from the prepared request, against the pre-transition book, only if the durable `RISK_APPROVED` audit event proves PAPER admission under the current instrument-rules digest; every record already on disk must match, then the application is completed and the entry COMMITTED |

Additional reason codes: `WOULD_RECOVER` / `RECOVERED` outcomes with
`DRY_RUN` / `RECOVERY_COMPLETE`; refusals `RECOVERY_MODE_UNPROVEN` (the
prepared request or a committed result is not PAPER),
`RECOVERY_AUTHORITY_UNREADABLE`, `RECOVERY_EVIDENCE_AMBIGUOUS` (the evidence
fits none of the classes - including more than one unresolved entry),
`RECOVERY_DERIVATION_UNAVAILABLE` (re-derivation could not be proven);
failures `RECOVERY_WRITE_FAILED`, `POST_RECOVERY_VERIFICATION_FAILED`,
`POST_RECOVERY_RUNTIME_NOT_READY` (every touched file restored
byte-for-byte); `EXECUTION_MODE_INVALID` for an unknown mode.

What stays refused: without `--execution-mode`, or with `--execution-mode
LIVE`, every unresolved entry is `JOURNAL_UNRESOLVED` exactly as before - a
real venue's fill cannot be recomputed from local state. A
`COMMIT_STATUS_UNKNOWN` entry is also refused; it has no supported recovery
yet.

A RESERVED reservation whose request never reached the journal at all (a
kill between capital reservation and PREPARE) needs no operator action: the
runtime releases it at startup (F-2).


- Operators have one documented command with a machine-detectable exit code,
  instead of an undocumented REPL procedure with a misleading
  `policy_version` example.
- Startup remains fail-closed and never auto-bootstraps: the tool is not
  imported by `core/application.py`, and the existing source-grep guard in
  `tests/test_block2c_financial_state_bootstrap.py` continues to enforce
  that.
- Bringing up a fresh environment with default flags now produces state the
  canonical runtime policy accepts, because both derive from the same
  `CapitalManager` / `RiskPolicy` construction.
- Corrupt and policy-incompatible state are surfaced as explicit operator
  decisions rather than being silently repaired or silently reported ready.
