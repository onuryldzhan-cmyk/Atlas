# ADR-0003: Financial State Bootstrap Contract

## Status

Accepted. Block 2 / Package 2C.

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
  the bootstrap result reports `ALREADY_EXISTS` rather than attempting any
  repair or overwrite.

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
