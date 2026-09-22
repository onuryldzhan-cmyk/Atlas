# ARCH-EDGE-001 — Ancestor-package forbidden edges surfaced by the AUDIT-016 A-1 detector fix

| Field | Value |
| --- | --- |
| Finding ID | ARCH-EDGE-001 |
| Title | Seventeen forbidden layer edges exist only through ancestor package `__init__.py` execution |
| Finding type | `ARCHITECTURE_BOUNDARY_EDGE_INVENTORY` |
| Operating mode | AUDIT MODE |
| Status | `PARTIALLY_RESOLVED_15_OF_17_VIA_RECLASSIFICATION_GROUP_B2_STILL_OPEN` |
| Status (as recorded 2026-09-21, pre-implementation) | `OPEN_INVENTORY_RECORDED_NO_EDGE_DISPOSED` |
| Resolving commit | `f2c25e2ca8df92a9a199e4691f5f14fa49c9e193` (branch `research/edge-validation`) |
| Resolving authority | `governance/current/ATLAS_MILESTONE_REGISTRY_v4.39.json`, GRANT-ANCESTOR-INIT-RECLASSIFICATION |
| Authorized by | `governance/current/ATLAS_MILESTONE_REGISTRY_v4.38.json`, GRANT-FINDINGS-17-EDGES |
| Derived at commit | `d85ec6a5ccff50ac033ea4a8ca3c33b57546321c` (branch `research/edge-validation`) |
| Recorded on | 2026-09-21 |
| Production effect | NONE |
| Live effect | NONE |

## Group B2 phase (i) resolution update — 2026-09-22, commit `370567f`

**This section is additive.** Everything below it, including the
supersession annotation, the resolution update of 2026-09-21, and the
original record beneath that, is preserved unchanged. Nothing has been
deleted or rewritten.

**Authority.** `governance/current/ATLAS_MILESTONE_REGISTRY_v4.46.json`,
`GRANT-ARCH-EDGE-001-UPDATE`, successor to `GRANT-B2-PHASE-1-LAZY-ONLY`
(registry v4.45), whose predicted outcome this section confirms occurred
exactly as predicted.

**STATUS: Group B2 phase (i) RESOLVED at `370567f`. Phase (ii) remains
OPEN, UNAUTHORIZED.**

### What changed

`atlas_finance/__init__.py` and `atlas_finance/market_data/__init__.py` were
converted to PEP 562 module-level `__getattr__`/`__dir__` lazy attribute
access, mirroring the same pattern that resolved Group B1's
`data_layer/__init__.py` (§ B1 above). `__all__` is unchanged in both files;
every previously eager-exported name still resolves, now on first attribute
access rather than at package-import time.

**Evidence — re-measured, fresh interpreter.** `import
atlas_finance.market_data.contracts` now loads **49 modules**, down from the
**313** this record measured before `370567f` (§ B2 above). `requests`,
`atlas_finance.market_data.binance_public_provider`, and
`atlas_finance.market_data.market_feed_service` no longer load at
ancestor-import time.

**Regression guard added.**
`tests/architecture/test_atlas_finance_init_is_lazy.py` (8 test functions),
mirroring `tests/architecture/test_data_layer_init_is_lazy.py`'s existing
non-vacuity pattern for Group B1.

### What did NOT change — the edges and the gate are still open, by design

`tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`
is still **RED**, on exactly the same 2 Group B2 edges (B2.1, B2.2 above).
This is the accepted, predicted outcome of `GRANT-B2-PHASE-1-LAZY-ONLY`, not
a regression and not an incomplete fix: `find_forbidden_edges` is a static
AST-based detector that flags ancestor-package execution — importing
`atlas_finance.market_data.contracts` still causes Python to execute both
ancestor `__init__.py` files, and that remains true regardless of what those
files' bodies now contain. Lazy imports remove the *runtime coupling* the
edges made possible; they do not remove the *static ancestor-execution
relationship* the detector measures.

**The B2 section's original blockquote above
("`STATUS: STILL OPEN. MEDIUM. UNCHANGED.`") is preserved exactly as
written and is still accurate for edge-disposal and gate-status purposes.**
What has changed is the *severity rationale* underneath that status, not the
status itself: the original MEDIUM classification rested on measured,
present runtime coupling ("importing a pure L1 contract module loads a live
HTTP client and a market-feed service" — § B2 above). That specific harm no
longer occurs after `370567f`. Whether that warrants a severity
reclassification is not decided by this record — reclassifying `atlas_finance`'s
two `__init__.py` files from L2 to L1 in `packaging/atlas_architecture_map.json`
is exactly **Group B2 phase (ii)**, and it remains **explicitly OPEN and
UNAUTHORIZED**. No grant through registry v4.46 authorizes it, per
`GRANT-B2-PHASE-1-LAZY-ONLY`'s own explicit exclusion
(`ANY_LAYER_RECLASSIFICATION_OF_ATLAS_FINANCE_INIT_PY_...`) and per this
record's own `## Reclassification-with-evidence is not a permitted
exception` section below, which this update does not alter.

### Evidence citations

- Commit `370567f3d46c446f31c021ebad4799dda105137a` (branch
  `research/edge-validation`), commit message: full regression suite
  "3224 passed, 1 failed in 151.68s", the 1 failure being this same
  unchanged architecture-gate failure on the same 2 edges above; nothing
  else newly failed.
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.45.json`,
  `grant_b_group_b2_phase_1_lazy_only`, whose
  `the_gate_remaining_red_is_the_expected_and_accepted_outcome` field
  predicted exactly this result in advance of implementation.

### What this update does not do

- It does **not** dispose of B2.1 or B2.2. Both remain open, undisposed
  edges.
- It does **not** change the gate. The architecture test remains red.
- It does **not** authorize, perform, or imply Group B2 phase (ii).
- It does **not** edit any historical registry or any text above this
  section.

---

## Supersession annotation — 2026-09-22, registry v4.45

**This section is additive.** Everything below it, including the resolution
update of 2026-09-21 and the original record beneath that, is preserved
unchanged. Nothing has been deleted or rewritten. This section records one
additional fact about what this record *is*, not a change to what it says.

**Authority.** `governance/current/ATLAS_MILESTONE_REGISTRY_v4.45.json`,
`GRANT-15-SUPERSEDED`. That grant is itself the successor to
`GRANT-15-CLASSIFICATIONS-SURVEY` (registry v4.43/v4.44), which authorized
locating the candidates and **required** that the numeric ambiguity be settled
with evidence rather than assumed in either direction.

### The backlog item this record supersedes

Commit `1ac3a64`'s own message deferred a follow-up package in these words:

> The broader ancestor-edge gap in find_forbidden_edges itself remains open
> elsewhere (18 violations found in an ad hoc simulation, 15 needing a real
> `__init__.py` classification decision) — deferred as its own scoped follow-up
> package, not started here.

That deferral is carried forward as the *"15 pending `__init__.py`
classifications"* item, quoted in the owner-exclusion lists of registries v4.42,
v4.43 and v4.44 and, in its original form, at two places in v4.37.

**It is now `SUPERSEDED-BY-ARCH-EDGE-001`.** This record is the authoritative
current enumeration of that item. The item is not separately open and needs no
separate survey.

### Why — settled by reproduction, not by assertion

The current post-AUDIT-016-A-1 detector
(`tools/build_architecture_inventory.find_forbidden_edges`) was run against two
historical trees extracted with `git archive` into a scratch directory, each
against its own contemporaneous `packaging/atlas_architecture_map.json`. No
historical commit was checked out over the working tree; no file in the
repository was modified by this derivation.

| Tree | Commit | Detector result |
| --- | --- | --- |
| `1ac3a64^` | `4af72ee17072df19c1903950e7655428706671b7` | **18** violations |
| `1ac3a64` | `1ac3a64d90a1695355eee75df478adfad9468887` | **17** violations |

- **FACT.** The 18 at `4af72ee` reproduces the *"18 violations found in an ad hoc
  simulation"* the commit message reports, and establishes that the simulation
  was run against the **pre-fix** tree.
- **FACT.** The 17 at `1ac3a64` is set-identical to the 17 edges this record
  enumerates.
- **FACT.** The set difference is exactly one edge:
  `data_layer/semantic_contracts.py -> data_layer/__init__.py`. It was eliminated
  by `1ac3a64`'s own `data_layer` laziness fix — which that commit's message
  independently records as dropping `semantic_contracts.py` out of the runtime
  closure (108 → 105 modules).

**Conclusion (FACT).** The backlog item's universe of 18 edges is a *strict
superset* of this record's 17, differing by one edge that `1ac3a64` itself
closed. Whatever 15-edge subset of the 18 the commit message meant, that subset
is wholly contained in this record's enumeration.

**Residue (FACT).** Of the 18, **sixteen are now closed** — one by `1ac3a64`
itself, fifteen by the reclassification at `f2c25e2`. The residual open set is
**exactly the two Group B2 `atlas_finance` edges, and nothing else.** This holds
regardless of which 15-subset the commit message meant, so the supersession does
not depend on resolving that question.

### Two numbers that are equal but are not the same set

This is flagged rather than relied on, because conflating them would misreport
the disposition.

- **INFERENCE, not FACT.** The most likely reading of *"15 needing a real
  `__init__.py` classification decision"* is the 18 minus the three edges
  targeting `data_layer/__init__.py`, which `1ac3a64` had just made lazy and
  therefore considered handled: Group A (10) + Group B2 (2) + Group C (3) = 15.
  This is arithmetic and context. The commit message does not say it.
- This record separately reports **"15 resolved"** at `f2c25e2`, being Group A
  (10) + Group B1 (2) + Group C (3).
- Under the inferred reading these two 15s are **numerically equal but not the
  same set**: the backlog's 15 would *contain* Group B2 and *exclude* Group B1;
  `f2c25e2`'s resolved 15 is the converse. The correct statement under that
  reading is that **13 of the backlog's 15 are resolved and 2 remain** — not
  that all 15 are resolved.

The task statement authorizing registry v4.45 described the backlog item as
*"15 already resolved at `f2c25e2`, 2 remain as Group B2"*, which conflates the
two. The supersession stands either way, because it rests on the superset fact
above and not on the coincidence.

### What this annotation does not do

- It **disposes of no edge.** Group B2's two edges remain **OPEN at MEDIUM**,
  exactly as the Group B2 section below states.
- It **changes no gate.** `tests/architecture/test_forbidden_layer_imports.py`
  remains red on those 2 edges.
- It **edits no historical registry.** Registries v4.19 onward are immutable once
  committed. The annotation is placed here and in the additive successor v4.45,
  never written back into v4.37, v4.42, v4.43 or v4.44.
- One inaccuracy in the authorizing task statement is recorded rather than
  silently accepted: it named *"v4.34/v4.37's `not_authorized` lists"* as the
  references, but v4.34 does not contain the phrase. The references verified at
  HEAD are v4.37 (original form, two places) and v4.42/v4.43/v4.44 (quoted
  owner-exclusion list).

---

## Resolution update — 2026-09-21, commit `f2c25e2`

**Everything below this section is the record as originally written and is
preserved unchanged.** It states the pre-implementation position, and its
measurements, reasoning and caveats remain the evidence the resolution rests on.
Nothing in it has been rewritten or deleted; CLAUDE.md's Governance section
requires that a changed decision record *why* it changed, which is impossible if
the superseded text is erased. Read the original sections as history and this
section as their current disposition.

### What changed

Registry v4.39 (`GRANT-ANCESTOR-INIT-RECLASSIFICATION`) authorized, and commit
`f2c25e2` implemented, a **reclassification** of two ancestor package markers in
`packaging/atlas_architecture_map.json`:

| File | Was | Now |
| --- | --- | --- |
| `core/__init__.py` | L3 (by the generic `core/*` default) | L1 (explicit rule) |
| `data_layer/__init__.py` | L2 (by the generic `data_layer/*` default) | L1 (explicit rule) |

No source file was modified. No `forbidden_edges` rule was changed. Nothing was
added to `permitted_exceptions`. `core/__init__.py` and `data_layer/__init__.py`
are byte-identical to their state at `d85ec6a`, when this record was authored.

### Disposition by group

| Group | Edges | Disposition |
| --- | --- | --- |
| A — `core/__init__.py` | 10 | **RESOLVED-VIA-RECLASSIFICATION** at `f2c25e2` |
| B1 — `data_layer/__init__.py` | 2 | **RESOLVED-VIA-RECLASSIFICATION** at `f2c25e2` |
| B2 — `atlas_finance` | 2 | **STILL OPEN. MEDIUM.** Not touched, not disposed of, no authority granted |
| C — L4 → L2/L3 | 3 | **RESOLVED-VIA-RECLASSIFICATION** at `f2c25e2` |

### Why these are genuinely resolved and not merely hidden

The distinction this record drew for itself under *"Reclassification-with-evidence
is not a permitted exception"* is the one that applies here, and it is worth
being precise about which of the three instruments was used:

- A **`permitted_exception`** would have named each importer/imported pair and
  told the detector to stop reporting it. The layer labels would have stayed put
  and the edges would have remained real cross-layer dependencies that the gate
  was instructed to tolerate. That was not done, and registry v4.39 explicitly
  forbids it.
- **Weakening a `forbidden_edges` rule** would have stopped the detector
  reporting an entire class of edge. `L4 → L2` and `L4 → L3` are untouched and
  still carry their original stated reason, *"research/intelligence must not
  reach execution internals (research cannot trade)."*
- **Reclassification** changed one input fact: which layer two files belong to.

The Group C edges are the clearest case. `ai/core/atlas_brain.py` imports
`core.decision_intelligence` and `data_layer.contracts`; `decision_builder.py`
imports `core.decision`. All three direct targets are L1, and L4 → L1 has always
been permitted. The violation was entirely against the **parent packages** Python
executes on the way in. Now that those parents carry accurate L1 labels, the
traversal is L4 → L1 at every step. These are not tolerated forbidden edges —
they are no longer forbidden edges at all.

The labels were the thing that was wrong. `core/__init__.py` inherited L3 from a
default whose recorded reason is *"application-layer orchestration, per the
composition-root diagram in `core/application.py`'s own docstring"* — true of
`application.py`, `market_loop.py` and `brain.py`, not of a six-line docstring.
`data_layer/__init__.py` inherited L2 from a default reasoning that it *"re-exports
both L1 (models) and L2 (config, sqlite) symbols so is classified at the
lower-common-denominator L2"* — correct for an eager `__init__`, and no longer
descriptive of a file whose re-exports are lazy by deliberate design.

### The contingency caveat is now closed, not carried forward

Every group above recorded the same caveat: inertness was *measured at a point in
time and enforced by nothing*. That caveat was the reason these were candidate
classifications rather than dispositions. It is now discharged, asymmetrically,
because the two files are asymmetric:

- **`core/__init__.py` is self-enforcing and needs no new test.** It is now
  classified L1. Adding an eager import of an L3 module to it — the exact change
  that would invalidate the reclassification — produces an `ast.Import` or
  `ast.ImportFrom` node that the existing detector sees, and it re-triggers
  immediately as a caught L1 → L3 violation. The reclassification made this file
  *more* sensitive to regression, not less.
- **`data_layer/__init__.py` is not self-enforcing, and this was the gap.** Its
  laziness runs through `importlib.import_module` on **string** module names.
  `tools/build_architecture_inventory._resolve_imports` walks `ast.Import` and
  `ast.ImportFrom` nodes only; an `importlib.import_module(str)` call is neither.
  The detector is structurally blind to it, so a future regression there would
  leave the gate green while an L1-labelled file loaded L2 infrastructure — and,
  through `ai/core/atlas_brain.py`, put research back on a live path to
  infrastructure with nothing reporting it.

The **Deferred improvement** recorded at the foot of this document is therefore
now implemented, as a binding condition of the grant rather than as an optional
follow-up: `tests/architecture/test_data_layer_init_is_lazy.py`.

It is a runtime check, not another static one. It measures `sys.modules` in a
**clean subprocess interpreter** against that subprocess's own baseline, so
modules already loaded by the pytest process cannot mask the result. It derives
the forbidden L2 set from `packaging/atlas_architecture_map.json` at test time —
not from a hardcoded list, and not from `module_layers`, which covers only the
runtime closure and would have missed `data_layer/config.py` and
`data_layer/sqlite.py`, the very modules the lazy table references. It honours
the map's pre-existing `permitted_exceptions` rather than re-litigating the
`canonical_evidence` → `projection_replay` edge. And it asserts that lazy access
still *resolves*, so the guard cannot be satisfied by an `__init__.py` that
passed the layering check by dropping the feature.

The check was **proven to discriminate**, not merely proven to pass:

| Subject | Guard result |
| --- | --- |
| Production `data_layer/__init__.py` (PEP 562 lazy) | passes |
| Synthetic package with an eager `from .sqlite import …` | **fails** |
| Synthetic package with an `importlib.import_module("…sqlite")` at import time | **fails** |
| Scratch copy of the **real** `data_layer`, `__init__.py` regressed to eager | **fails**, leaking `data_layer.sqlite` and `data_layer.migrations` |
| Scratch copy of the **real** `data_layer`, `__init__.py` regressed to importlib-string | **fails**, leaking `data_layer.sqlite` and `data_layer.migrations` |

The detector-blind importlib-string case is covered explicitly, because it is the
one no static check can see and therefore the only one that actually needed a
runtime guard. The regressions were constructed as fixtures and as scratch copies
under a temporary directory; the real `data_layer/__init__.py` was never edited
to manufacture a failure, since it is the evidence the reclassification rests on.

### Group B2 is not resolved by any of this

`atlas_finance/market_data/contracts.py`'s two edges into
`atlas_finance/__init__.py` and `atlas_finance/market_data/__init__.py` remain
**OPEN at MEDIUM**. No inertness argument is available for them and none is
offered: both ancestors are eager, and importing the L1 contracts module loads
313 modules including a live `requests` HTTP client. Registry v4.39 explicitly
excludes any change to them. The architecture gate is still red, and these two
edges are why.

---

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

## Gate status after `f2c25e2`: STILL RED, on 2 edges

`tests/architecture/test_forbidden_layer_imports.py::test_forbidden_layer_imports`
asserts `violations == []` and has no accepted-exception mechanism, so any
remaining edge fails it. Measured on the post-reclassification tree:

- **2 violations**, both Group B2 (`atlas_finance`).
- 15 resolved: Group A (10) + Group B1 (2) + Group C (3).
- **0 newly introduced**, measured as a set difference against the 17-edge
  baseline, not asserted.
- `tests/architecture/` reports `1 failed, 23 passed` before the new guard file;
  the single failure is this gate, now naming 2 edges instead of 17.

The gate was **not** made to pass. Turning it green would require disposing of
Group B2, which registry v4.39 explicitly does not authorize. Describing this
work as having cleaned the gate would be misreporting.

### Gate status as originally recorded (pre-implementation): RED on 17 edges


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

> **STATUS: RESOLVED-VIA-RECLASSIFICATION at `f2c25e2`.** `core/__init__.py` is
> classified L1. All ten edges are L1 → L1 or L2 → L1 and are no longer forbidden.
> The caveat below is discharged by self-enforcement, not by a new test: an eager
> L3 import added here would re-trigger as a caught L1 → L3 violation. Original
> pre-implementation text follows unchanged.

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

> **STATUS: RESOLVED-VIA-RECLASSIFICATION at `f2c25e2`.** `data_layer/__init__.py`
> is classified L1; both edges are L1 → L1 and no longer forbidden. The caveat
> below — laziness enforced by no test — is discharged by
> `tests/architecture/test_data_layer_init_is_lazy.py`, a binding condition of the
> authorizing grant. Original pre-implementation text follows unchanged.

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

> **STATUS: STILL OPEN. MEDIUM. UNCHANGED.** These two edges are not resolved,
> not suppressed, and not disposed of. Registry v4.39 explicitly excludes any
> change to `atlas_finance`. Both ancestors are eager and the coupling is real and
> measured — no inertness argument exists here. These are the 2 edges the
> architecture gate still fails on.

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

> **STATUS: RESOLVED-VIA-RECLASSIFICATION at `f2c25e2`.** These are no longer
> L4 → L3 / L4 → L2 edges at all. Every direct target was always L1 and always
> permitted; only the ancestor packages were mislabelled, and the traversal is now
> L4 → L1 at every step. The `L4 → L2` and `L4 → L3` rules are untouched and fully
> enforced — nothing was added to `permitted_exceptions`. The inertness evidence
> this group called *load-bearing on a safety invariant* is now enforced rather
> than merely measured, per the resolution section above. Original
> pre-implementation text follows unchanged.

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

> **SUPERSEDED at `f2c25e2` by registry v4.39,
> GRANT-ANCESTOR-INIT-RECLASSIFICATION.** The statement below was accurate for
> *this record*, which disposed of nothing. Fifteen of the seventeen edges have
> since been resolved by a separate, separately authorized reclassification — see
> the resolution section at the top. Group B2's two edges remain undisposed
> exactly as described below. The text is retained because the Governance section
> of CLAUDE.md requires a changed decision to record the reason it changed.

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

## Deferred improvement — IMPLEMENTED at `f2c25e2` (originally: not implemented, not authorized)

> **STATUS: CLOSED.** Registry v4.39 made this a *binding condition* of the
> reclassification grant rather than an optional follow-up, on the owner's
> explicit instruction that the asymmetry be closed with a real compensating test
> and not left as a known gap. Implemented as
> `tests/architecture/test_data_layer_init_is_lazy.py` and proven to discriminate
> against both an eager and a detector-blind importlib-string regression. The
> `core/__init__.py` half needs no test: it is self-enforcing once classified L1.
> See the resolution section at the top for the full discrimination evidence.
> Original text follows unchanged.


The contingency caveat recurs in all three groups: inertness is currently
asserted by measurement at a point in time and enforced by nothing. A regression
test asserting that `core/__init__.py` and `data_layer/__init__.py` load no L2 or
L3 first-party module would convert a contingent property into an enforced
invariant, and is a prerequisite for any future decision to treat Group A, B1 or
C as safe on inertness grounds. Recorded here as a deferred improvement only; it
is outside every grant in registry v4.38.
