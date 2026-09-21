# ARCH-EDGE-001 — Ancestor-package forbidden edges surfaced by the AUDIT-016 A-1 detector fix

| Field | Value |
| --- | --- |
| Finding ID | ARCH-EDGE-001 |
| Title | Seventeen forbidden layer edges exist only through ancestor package `__init__.py` execution |
| Finding type | `ARCHITECTURE_BOUNDARY_EDGE_INVENTORY` |
| Operating mode | AUDIT MODE |
| Status | `OPEN_INVENTORY_RECORDED_NO_EDGE_DISPOSED` |
| Authorized by | `governance/current/ATLAS_MILESTONE_REGISTRY_v4.38.json`, GRANT-FINDINGS-17-EDGES |
| Derived at commit | `d85ec6a5ccff50ac033ea4a8ca3c33b57546321c` (branch `research/edge-validation`) |
| Recorded on | 2026-09-21 |
| Production effect | NONE |
| Live effect | NONE |

## Why this record exists

Registry v4.37 permitted the AUDIT-016 A-1 implementer to run the corrected
detector and describe the edges it surfaced, but explicitly withheld authority to
dispose of any of them. That description was produced in-session and never
written to a durable artifact, so the derivation existed only in a prior
session's transcript. A transcript is not repository evidence. This record makes
the edge set citable without deciding any of it.

Every edge below was **re-derived by running the live detector against the real
architecture map at the commit named above**, not transcribed from the prior
session. The prior session is cited as the origin of the finding, not as the
source of these figures.

## Origin: what the A-1 fix changed

`tools/build_architecture_inventory.find_forbidden_edges` previously resolved
only direct import edges. Importing `pkg.sub` executes `pkg/__init__.py` first,
so the ancestor package is a real runtime dependency even though it never
appears as a dotted name of its own. `compute_runtime_closure` and
`compute_import_graph` already followed those edges; `find_forbidden_edges` did
not. Commit `1ac3a64` hit this in production shape, and the A-1 remediation
(commit `d85ec6a`) widened the resolver. The 17 edges below are what that
widening surfaced. They are newly *visible*, not newly *introduced*.

## Method

```
find_forbidden_edges(
    Path("."),
    list(module_layers),
    module_layers,
    forbidden_edges,
    permitted_exceptions,
)
```

against `packaging/atlas_architecture_map.json` (schema 1.0, authority
`ATLAS_BLOCK2_ARCHITECTURE_BOUNDARY`, 18 forbidden-edge rules, 1 pre-existing
permitted exception). Result: **17 violations**, partitioned below.

Runtime coupling was measured separately and empirically, by importing each
entry module in a fresh interpreter and diffing `sys.modules` against its
baseline. Claims of "zero coupling" below rest on that measurement, not on
reading the source.

## Current gate status: RED

The architecture gate `tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`
**is currently failing at commit `d85ec6a`** on these exact 17 edges. Verified by
running it: `1 failed, 23 passed` across `tests/architecture/`.

This is a pre-existing failure and not a regression introduced by recording this
finding. No production file, no test, and no entry in
`packaging/atlas_architecture_map.json` was modified by the session that
authored this record.

The gate asserts on `compute_runtime_closure(REPOSITORY_ROOT, ENTRY_POINTS)`
rather than on the full `module_layers` table, so the two could in principle
disagree. They were checked separately and **both report the same 17 edges**, so
every edge inventoried here is reachable from a real entry point and is inside
what the gate actually enforces. None is a map-only artifact.

The practical consequence: the gate stays red until the owner disposes of these
edges. That is the correct behaviour — the A-1 remediation made the gate honest,
and it is now reporting real edges it had previously been blind to. It is not a
reason to weaken the gate, and this record weakens nothing.

---

## Group A — 10 edges into `core/__init__.py`

**Candidate classification: LOW.** Structurally present, zero runtime coupling.

| # | Source | Layers |
| --- | --- | --- |
| A1 | `core/audit_event_store.py` | L2 → L3 |
| A2 | `core/capital_reservation.py` | L1 → L3 |
| A3 | `core/execution_idempotency_store.py` | L2 → L3 |
| A4 | `core/execution_portfolio_foundation.py` | L1 → L3 |
| A5 | `core/execution_transaction_journal.py` | L2 → L3 |
| A6 | `core/fee_accounting.py` | L1 → L3 |
| A7 | `core/local_capability_adapter.py` | L2 → L3 |
| A8 | `core/model_provider_contracts.py` | L1 → L3 |
| A9 | `core/position_sizing.py` | L1 → L3 |
| A10 | `core/tool_gateway_contracts.py` | L1 → L3 |

All ten target `core/__init__.py`, classified L3.

**Evidence.** `core/__init__.py` is 6 lines: a module docstring and nothing else.
It contains no import statement of any kind. Measured: `import
core.decision_intelligence` loads exactly `core` and `core.decision_intelligence`
and no other first-party module; `import core.decision` behaves identically.

**Reasoning.** The edge is real as a graph fact — Python does execute
`core/__init__.py` — but it transfers no behavior, because there is no behavior
to transfer. No L1 or L2 module here acquires any application-layer capability
through this edge.

**Caveat that keeps this LOW rather than closed.** The inertness is a *current
contingent property of the file*, not a structural guarantee. A single eager
import added to `core/__init__.py` would silently convert all ten edges into real
L1→L3 and L2→L3 coupling, with no gate failing, because the gate would already
have been told these edges are acceptable. Nothing in the repository currently
enforces that `core/__init__.py` stays inert.

---

## Group B — 4 edges into `data_layer` / `atlas_finance` ancestor inits

The task framing under which this record was authorized treated Group B as
uniformly LOW, on the stated premise that `data_layer`'s `__init__` is lazy and
`atlas_finance`'s laziness was UNKNOWN and had to be verified rather than
assumed. **That verification was performed and returned the opposite of the
premise for `atlas_finance`.** Group B therefore splits into two subgroups with
materially different severities, and is *not* uniformly LOW.

### B1 — `data_layer` (2 edges). Candidate classification: LOW.

| # | Source | Target | Layers |
| --- | --- | --- | --- |
| B1.1 | `data_layer/canonical_evidence.py` | `data_layer/__init__.py` | L1 → L2 |
| B1.2 | `data_layer/models.py` | `data_layer/__init__.py` | L1 → L2 |

**Evidence — laziness CONFIRMED.** `data_layer/__init__.py` is 51 lines
implementing a PEP 562 module-level `__getattr__`. `StorageConfiguration`,
`load_storage_configuration`, `ExecutionRecord`, `OrderRecord`,
`PositionRecord` and `SQLiteStorage` resolve through `importlib.import_module`
on first attribute access. There is no eager import of `.config`, `.models` or
`.sqlite`. The file's own docstring states this was deliberate, precisely to stop
`from data_layer.<anything> import ...` from dragging in the L2 SQLite backend.

**Evidence — measured.** `import data_layer.contracts` in a fresh interpreter
loads exactly `data_layer` and `data_layer.contracts`. No `sqlite3`, no
`data_layer.sqlite`, no `data_layer.config`, no `data_layer.models`.

Same contingency caveat as Group A: laziness here *is* enforced by deliberate
design and documented intent, which is stronger than Group A's incidental
emptiness, but still not enforced by any test.

### B2 — `atlas_finance` (2 edges). Candidate classification: MEDIUM.

| # | Source | Target | Layers |
| --- | --- | --- | --- |
| B2.1 | `atlas_finance/market_data/contracts.py` | `atlas_finance/__init__.py` | L1 → L2 |
| B2.2 | `atlas_finance/market_data/contracts.py` | `atlas_finance/market_data/__init__.py` | L1 → L2 |

**Evidence — laziness DISCONFIRMED. Both ancestors are EAGER.**
`atlas_finance/__init__.py` (143 lines) performs an unconditional top-level
`from atlas_finance.market_data import (...)` of 30 names.
`atlas_finance/market_data/__init__.py` (129 lines) eagerly imports
`binance_public_provider`, `contracts`, `exceptions`, `market_feed_service` and
`models`. `binance_public_provider` imports the third-party `requests` HTTP
client at module scope.

**Evidence — measured.** `import atlas_finance.market_data.contracts` in a fresh
interpreter loads **313 modules**, including `requests`,
`atlas_finance.market_data.binance_public_provider` and
`atlas_finance.market_data.market_feed_service`.

**Why this is MEDIUM and not LOW.** This is exactly the harm the L1→L2 rule
exists to prevent, and it is actually occurring: importing a pure L1 contract
module loads a live HTTP client and a market-feed service. Unlike Groups A and
B1, the coupling here is real, present, and measured — there is no inertness
argument available. Classifying it LOW by association with the rest of Group B
would be downgrading a finding for convenience.

**Not escalated above MEDIUM** because `atlas_finance` is public market-data
infrastructure only. Both `__init__` docstrings assert an explicit security
boundary excluding order placement, balance access, portfolio mutation, capital
allocation, position modification and credential access. No execution or capital
authority is reachable through this edge. The cost is architectural integrity
and import weight, not a safety-invariant breach.

---

## Group C — 3 edges crossing L4 → L2/L3

**Candidate classification: HIGH.** Addressed separately under GRANT-GROUP-C-INVESTIGATION.

| # | Source | Target | Layers |
| --- | --- | --- | --- |
| C1 | `ai/core/atlas_brain.py` | `core/__init__.py` | L4 → L3 |
| C2 | `ai/core/atlas_brain.py` | `data_layer/__init__.py` | L4 → L2 |
| C3 | `ai/core/intelligence/decision_builder.py` | `core/__init__.py` | L4 → L3 |

Triggering imports, read directly from source:

- `ai/core/atlas_brain.py:83` — `from core.decision_intelligence import Action, CanonicalDecision, Evidence, FusionPolicy, SignalFusion`
- `ai/core/atlas_brain.py:96` — `from data_layer.contracts import ClaimSource`
- `ai/core/intelligence/decision_builder.py:24` — `from core.decision import Decision, DecisionAction`

In all three cases the *direct* target is correctly classified L1 and is a
legitimate L4→L1 dependency. The forbidden edge is to the target's **parent
package**, which Python executes first.

**Why HIGH despite identical measured inertness.** The runtime measurement for
Group C is the same as for Groups A and B1: zero first-party infrastructure is
loaded. The severity difference is not about current coupling, it is about which
invariant the edge sits on.

Groups A and B are intra-family layering edges. The rule they cross is a
structural-hygiene rule, and a future regression there produces a layering
defect. Group C crosses `L4 → L2` and `L4 → L3`, whose stated reason in the
architecture map is *"research/intelligence must not reach execution internals
(research cannot trade)."* That is the same invariant as CLAUDE.md's immutable
rules 4 and 5 and its three-authority-domains rule. A future regression there —
one eager import added to `core/__init__.py` — would hand L4 research code a live
path into L3 execution internals, silently, with the architecture gate reporting
green because the edge had been documented as acceptable.

The evidence of inertness is therefore *load-bearing on a safety invariant* for
Group C, where for Groups A and B it is load-bearing only on code quality. That
is why the same measurement supports a LOW reading for A/B1 and a HIGH reading
for C.

---

## Disposition

**None of the 17 edges is disposed of by this record.** No edge is suppressed,
whitelisted, resolved, or closed. No entry was added to `permitted_exceptions`.
No architecture-map rule, layer assignment, or forbidden-edge rule was changed.
The classifications above are documented readings, not dispositions.

- **Groups A and B (14 edges)** remain open owner decisions, in exactly the state
  registry v4.37 left them. Registry v4.38 explicitly lists their resolution as
  not authorized.
- **Group C (3 edges)** is under investigation per GRANT-GROUP-C-INVESTIGATION.
  That grant permits implementation *only* if a clean, bounded fix exists, and
  permits neither a `permitted_exception` nor a reclassification-with-evidence
  for Group C, because deciding that an edge across the research-cannot-trade
  boundary is safe is reserved to the owner.

### Reclassification-with-evidence is not a permitted exception

These are different instruments and this record does not conflate them. A
`permitted_exception` is an entry in the architecture map that makes the detector
stop reporting an edge; it changes the gate. A reclassification-with-evidence is
a documented finding that an edge, while still reported, carries no runtime
coupling; it changes the reading, not the gate. Everything in this record is the
second kind, and even that is offered as a *candidate* classification pending
owner decision.

## Deferred improvement (not implemented, not authorized)

The contingency caveat recurs in all three groups: inertness is currently
asserted by measurement at a point in time and enforced by nothing. A regression
test asserting that `core/__init__.py` and `data_layer/__init__.py` load no L2 or
L3 first-party module would convert a contingent property into an enforced
invariant, and is a prerequisite for any future decision to treat Group A, B1 or
C as safe on inertness grounds. Recorded here as a deferred improvement only; it
is outside every grant in registry v4.38.
