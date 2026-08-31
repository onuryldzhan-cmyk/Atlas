# Atlas Block 3 Freeze Evidence

## Status

CLOSED / FROZEN

## Source Revision

Branch:
feat/block3-execution-safety

Source HEAD:
bc96d447cd82a47233c4c348ca819cb6d41d4d41

Worktree at verification time: clean, nothing staged.

This document anchors the SOURCE HEAD above. The commit that introduces this
file is a separate evidence commit and is deliberately not recorded here; the
annotated `block3-frozen` tag anchors that commit instead.

## Scope

Block 3 spans the fifteen commits in `0942391..bc96d44`, that is everything
after the Block-2 freeze record (`0942391`) through the source HEAD. Package
attribution below groups those commits by the subject area each closed.

**Package 1 — execution safety and durable state ownership.**
Closed post-reservation execution failure leaks so that a failure after a
capital reservation can no longer strand that reservation (`a38854e`), and
centralized ownership of the durable execution and paper-trading state paths
in the composition root so that execution and persistence modules no longer
choose their own locations (`b34f0f4`).

**Package 2 — financial state bootstrap and operational metadata.**
Hardened operational metadata sanitization (`95f25c6`), added validation of
financial bootstrap state and policy consistency (`3f25337`), added the
explicit operator bootstrap workflow and its runbook ADR (`22f8bba`), and
exposed the shared sanitized metadata boundary (`08f09dd`).

**Package 3 — capability governance.**
Added the provider and tool capability governance contracts, including
`CapabilityGateway` (`842118c`), and preserved opaque machine identity
byte-exact through invocation results rather than routing it through the
sensitive-text redactor (`6bb857b`).

**Package 4 — confidence semantics and gateway wiring.**
Corrected evidence-removal monotonicity in agent fusion (`9b2ccb8`), made the
critical and unsupported risk penalties fail closed (`4d27184`), proved the
confidence authority boundaries structurally (`f3c5239`), and wired the local
capability adapter behind the gateway (`5d2f5f4`).

All four packages are CLOSED. A final independent audit was completed against
this branch; its findings are recorded below.

## Final Remediation

0fa4ffe9e1c036214876da4b80a0676718ff13dc
HIGH-1 terminal execution success allow-list

954fb834c2c4c326b822c49aa8b2edc8984346f9
M-2 winner selection off display rounding

bc96d447cd82a47233c4c348ca819cb6d41d4d41
comment-only M-2 freeze hygiene

## Verification

Full suite:
1605 passed

Command:
`python -m pytest tests/ -q --basetemp=<session scratch> -p no:cacheprovider`,
run against the committed source HEAD with an isolated basetemp outside the
repository. The worktree was still clean after the run.

Architecture:
96 modules
96/96 layered
0 forbidden edges

Command:
`python tools/build_architecture_inventory.py check` — runtime closure matches
(96 modules), the architecture map assigns every live module a layer (96
modules), no forbidden dependency edges.

Independent import/seam verification:
PASS

Specifically confirmed at this HEAD:

- No module under `ai/` imports `core.risk_engine`. The only textual matches
  are comments, so the canonical execution risk authority is unreachable from
  the intelligence layer.
- `core.financial_state_bootstrap` is not referenced from `core/application.py`
  or any other startup path.
- `CapabilityGateway(` is constructed in exactly one non-test location,
  `core/application.py`.
- No MCP runtime import exists under `core/` or `ai/`.

## M-2

Semantics:
CLOSED

Winner authority:
quantized_mass / MASS_PRECISION

`AgentFusion.fuse` selects the winning bucket with
`max(quantized_mass, key=quantized_mass.get)`, where `quantized_mass` rounds
each bucket's true mass at `MASS_PRECISION` (12). The confidence numerator
reads `quantized_mass[action]` — the identical value — so selection and
numerator cannot disagree by construction. The `scores` mapping keeps its
3-decimal rounding and is display-only; no decision path reads it.

Verification performed at freeze:

- Committed regression suites
  `tests/test_block3_terminal_status_classification.py` and
  `tests/test_block3_m2_winner_selection_authority.py`: 30 passed.
- The two recorded audit counterexamples were re-run independently. The
  display-tie case moves 0.5005 -> 0.5001 on removal (delta -0.0004) and the
  unchanged-denominator case holds at 0.5002 (delta +0.0000). Neither
  inverts.
- The recorded mis-selection is gone: on the display-tie case `scores["BUY"]`
  and `scores["SELL"]` are both 0.5, SELL genuinely holds more mass, and the
  selected action is SELL.
- A fresh property probe on seed 20260814, disjoint from the committed grid,
  covered 60,000 randomized states and 179,776 single-participant removals:
  0 removal violations, 0 winner-selection violations, 0 confidence values
  outside [0, 1]. 55,973 states fused; 4,027 correctly fell to the
  fail-closed INSUFFICIENT_EVIDENCE path.

Provider activation:
GATED

`MIN_PARTICIPATING_AGENTS` remains 3 and `MIN_WEIGHT_COVERAGE` remains 0.50.
The only participant combination reachable today (technical + momentum) still
fails closed with reason `INSUFFICIENT_EVIDENCE` and confidence 0.0. No third
evidence provider is activated by this block, and nothing in the M-2
remediation lifts that interlock.

## M-3

CLOSED

Risk penalty taxonomy in `ai/core/intelligence/confidence/confidence_engine.py`:

| Classification | Penalty |
| --- | --- |
| LOW | 0.05 |
| MEDIUM | 0.20 |
| HIGH | 0.40 |
| CRITICAL | 1.00 |
| UNKNOWN | 1.00 |
| present but unrecognized (`UNSUPPORTED_RISK_PENALTY`) | 1.00 |
| genuinely absent (`ABSENT_RISK_PENALTY`) | 0.20 |

LOW, MEDIUM and HIGH are unchanged. CRITICAL, UNKNOWN and any present but
unrecognized label fail closed at the maximum penalty rather than resolving to
the former MEDIUM default. These are pinned at the maximum because the
canonical execution authority `core.risk_engine` already refuses them outright:
`NON_EXECUTABLE_RISK_LEVELS` is `{"CRITICAL"}`, rejected as
`CRITICAL_RISK_NOT_EXECUTABLE`, and the `UNKNOWN` sentinel is rejected as
`UNSUPPORTED_RISK_LEVEL`, both with zero allocation.

The absent-risk default of 0.20 is the one legacy convention deliberately
retained; see MEDIUM-2 in the deferred backlog.

## M-4

CLOSED BY PROOF

Authoritative `Decision.confidence` source: `AgentFusion.fuse`, and only that.
`DecisionBuilder.create` accepts no confidence-shaped parameter, so no other
producer can set it.

`ConfidenceEngine`'s value is advisory. Its one financial channel is selecting
the analytical risk level, which selects an executable bucket — never the
confidence that bucket policy is compared against — and that channel is
bounded in the safe direction, since a lower advisory value can only produce
an equal or stricter bucket. `metadata.intermediate_confidence` has one
producer and zero consumers: it is absent from `DecisionAdapter.CONFIDENCE_KEYS`,
`metadata` is absent from `CONFIDENCE_CONTAINER_KEYS`, and the authoritative
names are searched ahead of the generic ones. The value compared at admission
is re-derived inside `core.risk_engine`, which the L4 forbidden edges make
structurally unreachable from intelligence.

This is proved structurally in `tests/test_block3_package4_confidence_semantics.py`
rather than by refactoring working code. That file plus the four capability
suites: 229 passed.

## Execution Safety

**Success allow-list.** Terminal classification at the post-adapter boundary in
`core/execution_manager.py` is `if status not in self.SUCCESS_STATUSES`, where
`SUCCESS_STATUSES` is
`{PAPER_EXECUTED, EXECUTED, COMPLETED, SUCCESS, FILLED, CLOSED}`. Only a status
this manager recognizes as a completed execution continues into durable
finalization. `LIVE_DISABLED`, `LIVE_NOT_IMPLEMENTED`, `REJECTED`, `FAILED`,
`ERROR` and the `UNKNOWN` default of `ExecutionResult.status` are all outside
that set and therefore resolve through the unsuccessful-execution path. Any
status added in future fails closed the same way until it is deliberately
declared a success. `PAPER_EXECUTED` still commits.

The previous `status in FAILURE_STATUSES` test admitted everything outside
`{FAILED, ERROR}` into the durable-commit branch, so a correctly denied LIVE
request — one that provably performed no side effect — was finalized as a
confirmed execution, halting the runtime with an unresolved journal entry,
INDETERMINATE capital, and an audit record asserting an execution that had
never occurred.

**Post-side-effect uncertainty.** How a side effect is judged is unchanged.
`_resolve_unsuccessful_execution` still decides deterministic rollback versus
genuine uncertainty from the recorded side-effect marker alone, never from the
status. When a side effect remains possible, the result is marked
`success=False`, `status` and `commit_outcome` become
`COMMIT_STATUS_UNKNOWN`, `recovery_required` is set, and the original business
failure is preserved in `original_status`. A failure on the far side of
PaperTrader therefore stays INDETERMINATE / recovery-required rather than
being reported as a clean rollback.

**Reservation and journal semantics.** Atomicity of risk admission and capital
reservation was established earlier, in Block 2B (`5c30bc3`), and is carried
forward unchanged. Block 3 closed the remaining post-reservation execution
failure leaks (`a38854e`) and moved ownership of the durable execution and
paper state paths into the composition root (`b34f0f4`).

**Restart and recovery truthfulness.** An unresolved transaction is not
silently discarded. While one is outstanding, `ExecutionManager` sets
`execution_halted` and `recovery_required` and refuses the request with
`status="RECOVERY_REQUIRED"`, `commit_outcome=COMMIT_STATUS_UNKNOWN`, and the
message that execution is blocked until unresolved transactions are reconciled.
It is never resolved into a false confirmed or false rolled-back outcome; an
operator must reconcile it.

## Financial State Bootstrap

`core/financial_state_bootstrap.py` is the only explicit, operator-invoked path
that creates initial durable financial state.

- **EXISTS != VALID.** A file merely existing on disk is not treated as usable.
  An existing store is reported `VALID_EXISTING` only if it loads and validates
  cleanly through its own canonical loader against the caller-supplied
  `policy_version` and `allocatable_capital`, and `INVALID_EXISTING` otherwise
  (corrupt, unreadable, schema-invalid, or policy/capital-incompatible).
- **Non-overwrite.** Each of the three underlying stores raises
  `FileExistsError` if the target path exists. This module does not weaken that:
  it never writes to, repairs, or deletes a store that already has a file on
  disk. Either outcome leaves the file untouched.
- **Verify-only.** With `verify_only=True` nothing is ever created; an absent
  store is reported, not fabricated.
- **Policy consistency.** Validation is performed against the supplied policy
  version and allocatable capital rather than a duplicate parser, so a store
  that is well-formed but incompatible with current policy is reported invalid.
- **No startup auto-bootstrap.** The module is never imported or called from
  `AtlasApplication.__init__` or any other startup path. Normal startup still
  treats missing or corrupt durable financial state as fail-closed, leaving the
  corresponding service not-ready or raising.

## Capability Gateway

- **Deny-by-default.** `CapabilityGateway` is deny-biased and checks everything
  cheap and provable before the adapter is consulted, so a denial guarantees no
  side effect occurred. The composed runtime binds
  `UnconfiguredPolicyGate`, which denies every operation, is stateless, and
  takes no constructor argument, allow-list, or override that could turn it
  into an approving gate.
- **READ_ONLY-only default.** `DEFAULT_ALLOWED_SIDE_EFFECTS` is
  `frozenset({SideEffectClass.READ_ONLY})`. Widening it requires an explicit
  argument at construction, which is a visible diff.
- **No MCP.** No MCP runtime, dependency, or framework is introduced, and no
  MCP import exists under `core/` or `ai/`. `ToolAdapter` is shaped so an MCP
  client could later be one adapter among others; none exists today.
- **No external provider.** The single registered adapter is
  `LocalCapabilityProbeAdapter`, declared `SideEffectClass.READ_ONLY`,
  `CapabilityClass.LOCAL`, `requires_network=False`.
- **No credential.** A READ_ONLY tool must not declare a `required_permission`;
  the descriptor rejects that at construction. No credential is held or
  required by the wired adapter.
- **No financial capability.** Paid capabilities are refused unless
  `permit_paid_capabilities` is set, which it is not; both capability class and
  cost amount are consulted, so a caller cannot escape the check by
  mislabelling cost. No adapter in the composed runtime performs financial
  writes.
- **No evidence-provider activation.** Nothing built by
  `_build_capability_gateway` runs. The gateway is not started, not scheduled,
  not subscribed to the event bus, and not referenced by the brain, the market
  loop, or the execution path. No caller invokes it today, and if one did, the
  policy gate would deny before any adapter was reached.

A tool that lies about its own declared side-effect class is a known limit of
this design: the gateway enforces the declaration, it cannot detect a false
one. The mitigations are the READ_ONLY-only default, explicit widening, and
descriptor/invocation identity matching before invocation.

## PAPER / LIVE

PAPER:
default

`ExecutionManager` defaults to `mode="PAPER"` with
`live_execution_enabled=False`.

LIVE:
denied

With LIVE execution disabled, a LIVE request returns
`status="LIVE_DISABLED"` / `error_code="LIVE_EXECUTION_DISABLED"` and publishes
`LIVE_EXECUTION_BLOCKED`. Even if the flag were enabled, there is no approved
live execution adapter and the request returns `LIVE_NOT_IMPLEMENTED`. Both
statuses are outside `SUCCESS_STATUSES`, so neither can enter durable-success
finalization. No LIVE authority is granted by this block.

## Deferred Backlog

Recorded, carried forward, and not modified at this freeze.

**MEDIUM-2 — out-of-contract outer risk shape may receive absence-default
semantics.** An outer risk shape that is out of contract can resolve to the
absent-risk default (`ABSENT_RISK_PENALTY = 0.20`) rather than the fail-closed
maximum. Currently unreachable from the composed runtime. Must be fixed before
the next relevant seam exposes that shape.

**MEDIUM-3 — advisory risk level is an authority edge into authoritative
risk-bucket policy.** The advisory risk level remains an explicit authority
edge into authoritative risk-bucket policy. Currently bounded. Must be
revisited before any provider-interlock lift or broader dynamic risk input.

**LOW-1 — `OperationContext` source-level `trace_id` / `operation_id`
validation.** Deferred.

**LOW-2 — `calculate_agent_agreement` missing action defaults to HOLD.**
Deferred.

**LOW-3 — replay id consumed before adapter invocation.** The id is consumed
before the adapter is invoked, so an adapter exception makes that same id
non-retryable. Deferred.

**LOW-4 — bounded replay history eviction.** `REPLAY_HISTORY_LIMIT` is 10,000;
an id older than that is forgotten and would be accepted again. Deferred.

Provider interlock remains gated and requires a separate owner decision.

## Environmental Notes

- Stale removed-worktree metadata exists at `.git/worktrees/Atlas_Clean_Verify`
  while `git worktree list` reports only the primary worktree. This may emit
  Windows permission warnings during Git maintenance. It does not affect
  tracked source, the verification above, or commit correctness.

## Push Status

NOT PUSHED

No push, no merge, no Block-4 branch, no provider-interlock lift, and no
production-code change was made by this freeze operation.

## Limits of This Evidence

Block 3 establishes execution safety, financial state bootstrap semantics,
capability governance, and confidence authority boundaries. It does not
establish, and this document does not claim, production-ready trading alpha, a
validated financial edge, LIVE readiness, provider activation, multi-provider
evidence, or production exchange integration.
