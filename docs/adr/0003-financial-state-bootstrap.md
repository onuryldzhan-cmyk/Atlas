# ADR-0003: Financial State Bootstrap Contract

## Status

Accepted. Block 2 / Package 2C. Amended in Block 3 / Package 2 (M-C, M-D):
see "Amendment" below — `ALREADY_EXISTS` is replaced with truthful
existing-state semantics, and bootstrap now takes an explicit
`allocatable_capital` input for policy-compatibility validation.

## Context

Package 2B wired the canonical risk services (`JsonRiskStateStore`,
`CapitalReservationLedger` over `JsonReservationStore`,
`ExecutionPortfolioFoundation` over `FinancialStateStore`) into
`AtlasApplication`. All three correctly fail closed on missing or corrupt
durable state: `ExecutionPortfolioFoundation`/`CapitalReservationLedger`
report `ready == False` and `JsonRiskStateStore.load()` raises. That
behavior is intentional and is not changed by this package.

What was missing was any explicit, operator-invoked way to create that
state in the first place. `JsonReservationStore.initialize_empty()` and
`FinancialStateStore.initialize()` already existed and already guarded
against overwriting an existing file (`FileExistsError`), but
`JsonRiskStateStore` had no equivalent, and nothing tied the three stores
together into one bootstrap action.

## Decision

- `JsonRiskStateStore.initialize(value)` is added, mirroring the existing
  non-overwrite guard on the other two stores.
- `core/financial_state_bootstrap.py` adds
  `bootstrap_financial_state(state_directory, initial_capital,
  policy_version, ...)`, which calls all three stores' `initialize*()`
  methods and returns a `FinancialStateBootstrapResult` recording, per
  store, `CREATED`, `ALREADY_EXISTS`, or `FAILED` with a reason code.
- This function is not imported by `core/application.py` or any other
  startup path. It is only ever invoked explicitly, e.g. by an operator
  script.
- A store that already has a file - valid or corrupt - is left untouched;
  the bootstrap result reports what condition that existing file is
  actually in (see Amendment) rather than attempting any repair or
  overwrite.

## Consequences

- Normal application startup behavior is unchanged: missing/corrupt state
  still fails closed exactly as it did after Package 2B.
- Operators now have one explicit, testable entry point to create initial
  state for a fresh deployment, instead of needing to know the internal
  schema of three separate stores.
- Recovering genuinely corrupt state still requires deliberate operator
  action (e.g. removing or repairing the specific file) outside this
  module; this package does not add a repair/migration path, only
  creation of fresh state where none exists.

## Amendment (Block 3 / Package 2, M-C / M-D)

Package 2C's original decision treated any existing file as
`ALREADY_EXISTS`, without ever loading or validating it. That meant a
corrupt, unreadable, schema-invalid, or policy-incompatible file was
reported the same way as a genuinely healthy one — `EXISTS` was being
treated as equivalent to `VALID`. `FinancialStateBootstrapResult.succeeded`
could be `True` for a directory an operator could never actually trade
against.

`BootstrapOutcome` is replaced with truthful existing-state semantics:

- `CREATED` — the file did not exist; fresh state was written.
- `VALID_EXISTING` — the file existed, was loaded through that store's own
  canonical loader (`JsonRiskStateStore.load()`,
  `JsonReservationStore.load()` + `CapitalReservationLedger.ready`,
  `FinancialStateStore.load()` + `ExecutionPortfolioFoundation
  ._validate_state()`), and validated as usable against the supplied
  `policy_version` / `allocatable_capital`.
- `INVALID_EXISTING` — the file existed but is corrupt, unreadable,
  schema-invalid, or incompatible with the supplied `policy_version` /
  `allocatable_capital`. The file is left byte-for-byte untouched; no
  repair, overwrite, or delete is attempted.
- `FAILED` — bootstrap infrastructure itself could not complete while
  creating fresh state (e.g. an I/O error unrelated to an existing file).

`FinancialStateBootstrapResult.succeeded` is `True` only when every store
is `CREATED` or `VALID_EXISTING`; a single `INVALID_EXISTING` store makes
the whole result `False`.

Each store's existing-file validation reuses that store's own canonical
loader/validator — no duplicate parser is introduced. In particular,
`bootstrap_financial_state()` now takes an explicit `allocatable_capital`
parameter so the reservation store's existing encumbrance can be checked
against the same capital ceiling the runtime `RiskPolicy` would apply
(`CAPITAL_MISMATCH` when the existing reservations exceed it). This does
not duplicate any policy constant: `financial_state_bootstrap.py` stays on
plain parameters, and the operator CLI (ADR-0005) is responsible for
deriving `total_capital`, `allocatable_capital`, and `policy_version` from
the same `CapitalManager` / `RiskPolicy` construction the composition root
uses.

Risk-state `current_equity` / `peak_equity` and financial-state `cash` are
deliberately **not** compared against the caller's `initial_capital` for
already-existing state: those fields legitimately drift from their
bootstrap-time value as trading occurs, so an equality check against
`initial_capital` would misreport a healthy, actively-traded environment
as invalid. `policy_version` and reservation-encumbrance-vs-allocatable are
the two invariants that do not drift with trading and are the ones this
amendment validates.
