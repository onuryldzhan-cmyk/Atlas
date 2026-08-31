"""Local, inert implementations of the Package-3 capability seams.

Package 3 introduced the vocabulary (`ToolDescriptor`, `ToolInvocation`,
`ToolAdapter`, `CapabilityGateway`, `PolicyGate`) but deliberately shipped no
implementation of any of it, so the architecture it describes had never been
executed. This module is the smallest thing that executes it end to end:

- `UnconfiguredPolicyGate` - the concrete `PolicyGate` Atlas uses when no
  capability policy has been configured. It denies everything.
- `LocalCapabilityProbeAdapter` - one concrete `ToolAdapter` that computes a
  digest of its own invocation identity and returns it. It is a probe for the
  governed invocation path itself, not a capability that does anything useful
  to the outside world.

Together they demonstrate the intended shape - L1 contracts, L2
implementation, L3 composition - without granting Atlas a single new power.

What this module deliberately is not
------------------------------------
No network, no socket, no filesystem access, no subprocess, no credential, no
SDK, no MCP client, no scheduler, no background work, no cost. It produces no
`Evidence`, touches no fusion participant, and has no financial side effect.
Nothing here can open, increase, or reduce a position, and nothing here runs
unless something explicitly invokes it through `CapabilityGateway`.

Why the policy gate denies
--------------------------
`CapabilityGateway` cannot be constructed without a `PolicyGate`, so wiring a
gateway into the composition root forces a choice about what the default
authorization answer is. `UnconfiguredPolicyGate` makes that answer "no", and
makes it for a stated reason rather than by omission: Atlas has no capability
policy, no permission store, and no operator authorization model yet, so the
only honest decision available is denial. It is not a policy engine and holds
no rules to tune - it is the explicit absence of one. Introducing a gate that
can say yes is a separate, reviewable decision.

The practical consequence is that the composed gateway is provably incapable
of reaching any adapter: every invocation denies at the policy check, before
the adapter is touched.
"""

from __future__ import annotations

import hashlib
import time

from core.model_provider_contracts import (
    CapabilityClass,
    CostMetadata,
    InvocationOutcome,
)
from core.operational_contracts import OperationContext, PolicyDecision
from core.tool_gateway_contracts import (
    SideEffectClass,
    ToolDescriptor,
    ToolInvocation,
    ToolInvocationResult,
)


#: Reason code returned for every denial by `UnconfiguredPolicyGate`. Fixed
#: vocabulary, like the gateway's own reason codes: it must be greppable in an
#: audit trail and must never carry caller text.
NO_POLICY_CONFIGURED = "NO_CAPABILITY_POLICY_CONFIGURED"

#: Identity of the deny-everything policy, recorded on each decision so an
#: audit record shows *which* policy refused rather than only that one did.
UNCONFIGURED_POLICY_ID = "atlas.capability.unconfigured"


class UnconfiguredPolicyGate:
    """The `PolicyGate` Atlas uses when no capability policy exists.

    Denies every operation. It is deliberately stateless and takes no
    configuration: there is no constructor argument, allow-list, or override
    that could turn it into an approving gate by accident or by config.
    """

    def evaluate(self, context: OperationContext) -> PolicyDecision:
        if not isinstance(context, OperationContext):
            raise TypeError("context must be an OperationContext")
        return PolicyDecision(
            allowed=False,
            reason_code=NO_POLICY_CONFIGURED,
            policy_id=UNCONFIGURED_POLICY_ID,
            operation=context.operation,
            actor_id=context.actor_id,
        )


#: Outcome reason for a successful probe. Also a fixed token.
PROBE_OK = "LOCAL_PROBE_OK"

#: Returned when the adapter is handed an invocation addressed to some other
#: tool. The gateway already refuses that case before the adapter is reached;
#: this is the adapter refusing it again on its own account, so a caller that
#: bypasses the gateway still cannot make this adapter act on a descriptor it
#: does not own.
DESCRIPTOR_MISMATCH = "DESCRIPTOR_MISMATCH"

#: The single operation this tool understands.
PROBE_OPERATION = "capability_probe"


class LocalCapabilityProbeAdapter:
    """A pure, local tool that proves the governed invocation path works.

    Given an invocation, it returns a SHA-256 digest over that invocation's
    own identity (tool id, operation, invocation id). It reads nothing, writes
    nothing, and reaches nothing; the digest is a function of its arguments
    alone, so the same invocation identity always yields the same
    `output_digest`.

    Its value is diagnostic. An operator can establish that descriptors,
    policy evaluation, replay claiming, identity matching, and result
    validation all behave as specified, using a capability that cannot cause
    harm if any one of them is wrong.
    """

    TOOL_ID = "local_capability_probe"

    #: READ_ONLY and LOCAL are not conveniences here; they are the two
    #: declarations that let the gateway's default configuration reach this
    #: adapter at all. A tool declaring anything else is denied by
    #: DEFAULT_ALLOWED_SIDE_EFFECTS or by the paid-capability check, which is
    #: the behaviour this adapter is meant to stay inside rather than test
    #: the edges of.
    DESCRIPTOR = ToolDescriptor(
        tool_id=TOOL_ID,
        side_effect=SideEffectClass.READ_ONLY,
        capability_class=CapabilityClass.LOCAL,
        requires_network=False,
    )

    @property
    def descriptor(self) -> ToolDescriptor:
        return self.DESCRIPTOR

    @staticmethod
    def free_cost() -> CostMetadata:
        """The only cost this adapter can legitimately be invoked with.

        Exposed so callers do not hand-build a cost that disagrees with the
        descriptor; `CostMetadata` already rejects a LOCAL capability that
        declares any spend.
        """
        return CostMetadata(capability_class=CapabilityClass.LOCAL)

    def invoke(self, invocation: ToolInvocation) -> ToolInvocationResult:
        if not isinstance(invocation, ToolInvocation):
            raise TypeError("invocation must be a ToolInvocation")

        started = time.perf_counter()

        if invocation.descriptor != self.DESCRIPTOR:
            return ToolInvocationResult(
                invocation_id=invocation.invocation_id,
                tool_id=self.TOOL_ID,
                outcome=InvocationOutcome.INVALID_RESULT,
                reason_code=DESCRIPTOR_MISMATCH,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                cost=invocation.cost,
            )

        digest = hashlib.sha256(
            "\x1f".join(
                (
                    self.TOOL_ID,
                    invocation.operation,
                    invocation.invocation_id,
                )
            ).encode("utf-8")
        ).hexdigest()

        return ToolInvocationResult(
            invocation_id=invocation.invocation_id,
            tool_id=self.TOOL_ID,
            outcome=InvocationOutcome.OK,
            reason_code=PROBE_OK,
            # Measured rather than fixed: the digest is the deterministic
            # part, latency is observability. Nothing asserts on it.
            latency_ms=(time.perf_counter() - started) * 1000.0,
            cost=invocation.cost,
            # The digest field, not the descriptive one: this value is
            # meaningful only by being exactly itself, and `output_reference`
            # sanitizes what it accepts. There is no descriptive reference to
            # report - the probe produces no output to point at - so
            # `output_reference` stays None.
            output_digest=digest,
            metadata={
                "operation": invocation.operation,
                "digest_algorithm": "sha256",
            },
        )
