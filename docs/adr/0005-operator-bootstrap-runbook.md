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

### 1. Fresh PAPER environment

```
python tools/bootstrap_financial_state.py --state-directory ./memory_data
```

Expect exit `0` and three `CREATED` rows. Atlas can now start. This is
PAPER-only; nothing in this workflow grants live-trading authority.

### 2. Existing valid environment / restart / recovery

```
python tools/bootstrap_financial_state.py --state-directory ./memory_data --verify-only
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
`FINANCIAL_TRANSITION_RECOVERY_REQUIRED`, `FINANCIAL_STATE_INVALID`.

The tool does not repair, overwrite, or delete anything — the file is left
byte-for-byte as found. Resolution is a deliberate operator decision:
inspect the named file, restore it from your own backup, or move it aside
and re-run to create fresh state for that store. Moving a financial-state
file aside discards the accounting history it represents; treat that as a
decision with financial consequences, not a cleanup step.

`FINANCIAL_TRANSITION_RECOVERY_REQUIRED` specifically means a write was
interrupted mid-transition. Do not create fresh state over it without first
establishing what the interrupted transition did.

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

## Consequences

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
