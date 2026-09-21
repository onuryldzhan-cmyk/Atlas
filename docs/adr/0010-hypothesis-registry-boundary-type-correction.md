# ADR-0010: Correction to ADR-0009's Integration Diagram Return Types

## Status

Accepted 2026-09-21 (UTC).

**Amends ADR-0009 (`docs/adr/0009-hypothesis-registry-boundary.md`) in exactly
one respect: the return-type names in its integration diagram.** Every other
decision in ADR-0009 stands unchanged and is restated below as still current.

ADR-0009 is **not edited**. This project reconciles a governance record's drift
by adding a new versioned successor and never by rewriting the historical
record; an ADR is held to the same convention. Registry v4.35 states the
prohibition directly, listing `ANY_EDIT_TO_ADR_0009_OR_ANY_OTHER_ADR` among its
`not_authorized` items. Registry v4.36
(`research_design_doc_and_adr_correction_authorization`, `authorized_action_2`)
authorizes this record as a new additive ADR and restates that in-place editing
of ADR-0009 remains prohibited.

Supersedes nothing. Amends nothing in ADR-0006 or ADR-0008.

## Context

ADR-0009 settled the `research/` boundary and described the sanctioned future
integration shape as an L3 bridge. Its diagram names the value objects that
`research/hypothesis_registry.py` hands to that bridge:

```
research/hypothesis_registry.py   (L4, pure, stdlib-only)
      └─ returns FamilyVerdict / HypothesisVerdict value objects
```

— `docs/adr/0009-hypothesis-registry-boundary.md:122`.

**Neither name exists.** Verified against the repository on 2026-09-21 at HEAD
`e2b2c93`:

- A content search for `FamilyVerdict` and `HypothesisVerdict` across `*.py`,
  `*.md` and `*.json` returns exactly two files: ADR-0009 itself, and
  `checkpoints/20260920T165052Z_research-evidence-bridge-package-c.md`, the
  Package C checkpoint that first recorded the discrepancy. No source file
  defines, imports, exports or references either name.
- The types the module actually produces are `CheckAdjudication`
  (`research/hypothesis_registry.py:920`) and `FDRDecision`
  (`research/multiple_testing.py:51`).

This is a **documentation-only discrepancy with no functional defect.** The
bridge ADR-0009 described was built in Package C (commit `e2b2c93`,
`core/research_evidence_bridge.py`), and it reaches the adjudication
structurally rather than by name: `_adjudicate()` calls
`record.adjudicate_checks()` through `getattr` and reads the returned object's
fields, with the record itself typed `Any`
(`core/research_evidence_bridge.py:301-318`). Nothing in the repository ever
imported a type called `FamilyVerdict` or `HypothesisVerdict`, so nothing
depended on the diagram's names and nothing broke. Only the diagram was wrong.
Correcting it matters because ADR-0009 is the record a future author reads
before touching this boundary, and a diagram naming two types that cannot be
found is a record that trains its reader to distrust it.

The correction is not a simple rename. The two real types live in **two
different modules**: the adjudication in `research/hypothesis_registry.py`, the
family-level FDR outcome in `research/multiple_testing.py`. A faithful diagram
has to name both, and the original's single-source shape could not.

## Decision

**ADR-0009's integration diagram is superseded by the following. Read this
diagram wherever ADR-0009's appears.** Like the original, it describes the
sanctioned *shape* of the boundary — which L4 modules produce a verdict, and
which edges an L3 bridge may take to read one — not the import list of any one
bridge.

```
research/hypothesis_registry.py   (L4, pure, stdlib-only)
      └─ returns CheckAdjudication            (per-hypothesis check scoring)
research/multiple_testing.py      (L4, pure, stdlib-only)
      └─ returns FDRDecision                  (family-level BH outcome)
                          │
                          ▼  read by
core/research_evidence_bridge.py  (L3 — classify_module confirms L3)
      ├─ may import research.hypothesis_registry    (L3 → L4, allowed)
      ├─ may import research.multiple_testing       (L3 → L4, allowed)
      ├─ imports data_layer.contracts.ClaimSource   (L3 → L1, allowed)
      └─ calls record_claim() on an injected store  (L3 → L2, allowed)
```

**As built, for the avoidance of doubt.** The delivered bridge takes fewer of
those edges than it is permitted to. Its only first-party imports are
`data_layer.contracts.ClaimSource` (L3 → L1) and
`research.hypothesis_registry.REGISTRY_FORMAT_VERSION` (L3 → L4); it does not
import `research.multiple_testing`, and it does not import either value type,
reaching the adjudication through `getattr` instead
(`core/research_evidence_bridge.py:60-73, 301-318`). The store is injected, not
imported, exactly as ADR-0008 and ADR-0009 require. Taking fewer allowed edges
than permitted is not a deviation from this diagram; the diagram bounds what is
allowed, and a narrower bridge is a stricter one.

The two value objects, as they exist in source:

- **`CheckAdjudication`** — `research/hypothesis_registry.py:920`, a frozen
  slotted dataclass carrying `required_check_count`, `passed_check_count`,
  `recorded_check_count`, `missing_checks`, `failed_checks` and `status`, with
  an `all_required_checks_passed` property. Its docstring states that
  `required_check_count` "comes from the plan and is the only denominator any
  caller should use" — the NB-5 discipline, expressed in the type itself.
- **`FDRDecision`** — `research/multiple_testing.py:51`, a frozen slotted
  dataclass carrying `labels`, `p_values`, `adjusted_p_values`, `rejected`,
  `q`, `n_tests`, `n_rejected` and `critical_p_value`, with `rejected_labels`
  and `is_rejected(label)` accessors.

Both remain pure, stdlib-only L4 value objects. The correction changes what the
diagram calls them; it changes nothing about what they are, where they live, or
who may read them.

## What this record does not change

Every other decision in ADR-0009 is **restated as still current**. None is
reopened, re-argued or revised here:

- **`research/**` is L4 (RESEARCH_INTELLIGENCE).** Unchanged. Confirmed against
  `packaging/atlas_architecture_map.json`, `layer_rules` entry
  `research/*` → L4.
- **`research/` imports nothing first-party outside `research/`** — not even
  `data_layer/contracts.py`. Unchanged. The package's own invariant remains
  stronger than the layer rule that covers it, for the three reasons ADR-0009
  gives.
- **L4 → L2 and L4 → L3 remain hard forbidden edges,** unweakened. Confirmed
  present in `forbidden_edges` with their original reasons ("research cannot
  trade").
- **A `permitted_exceptions` entry for `research/` → `data_layer/**` remains
  rejected outright.** Unchanged, and unchanged in principle: weakening a hard
  forbidden edge to accommodate code is the anti-pattern ADR-0009 refused.
- **Reusing `HypothesisRegistry.registry_path` as an Evidence Store path
  remains rejected.** Unchanged.
- **The one-way L3 bridge remains the only sanctioned integration route.**
  Unchanged, and now built: `core/research_evidence_bridge.py` (commit
  `e2b2c93`). The bridge is one-way by construction — `research/` never learns
  the store exists.
- **W1 over W2: `research/` stays out of the runtime closure.** Unchanged, and
  W2 remains unauthorized. One note for whoever reopens it, recorded here
  because it would otherwise be lost: ADR-0009 supports the W2 deferral partly
  by citing "Step 2 data acquisition, which
  `docs/research/0001-hypothesis-registry-design.md` names as a prerequisite".
  That premise is now stale — the archive exists, and the correction is
  recorded in that document's "Correction 2026-09-21" section under registry
  v4.36. **The W2 decision itself is not revisited by this record and is out of
  its scope.** A stale supporting premise is not by itself a reason to reverse
  a decision; it is a reason to re-derive the decision deliberately, in a
  package authorized to do so.
- **Compensating controls C1 and C2 remain in force.** C1, the
  `{"pattern": "research/*", "layer": "L4"}` rule, and C2,
  `tests/test_research_isolation.py`. Unchanged and untouched by this record.
- **The open ancestor-edge gap in `find_forbidden_edges`** is neither fixed nor
  worsened here, exactly as in ADR-0009.
- **The seal-compatibility question** ADR-0009 left open stays open.

## Consequences

- No code changes. No test changes. No architecture-map changes. This record is
  documentation only, and the architecture gate's output is unaffected.
- ADR-0009 remains the authority on the `research/` boundary. A reader must now
  read ADR-0009 together with this record; that cost is accepted as the price
  of the never-edit-history convention, which is the same trade the governance
  registries already make.
- A future author reading either record finds type names that resolve to real
  source, and finds them in both modules that produce them.

## Evidence

All re-verified in this session at HEAD `e2b2c93`, from source rather than from
any prior report:

- `docs/adr/0009-hypothesis-registry-boundary.md:122` —
  `└─ returns FamilyVerdict / HypothesisVerdict value objects`.
- `grep -rn "FamilyVerdict\|HypothesisVerdict"` over `*.py`, `*.md`, `*.json` —
  matches only ADR-0009 and
  `checkpoints/20260920T165052Z_research-evidence-bridge-package-c.md`. No
  source match.
- `grep -n "class CheckAdjudication\|class FDRDecision" research/*.py` —
  `research/hypothesis_registry.py:920`, `research/multiple_testing.py:51`.
- `packaging/atlas_architecture_map.json` — `layer_rules`: `research/*` → L4,
  `core/*` → L3, `data_layer/*` → L2. `forbidden_edges`: L4 → L2 and L4 → L3
  both present, with ADR-0009's stated reasons intact.
- Governance basis: `governance/current/ATLAS_MILESTONE_REGISTRY_v4.36.json`,
  `research_design_doc_and_adr_correction_authorization.scope.authorized_action_2`,
  which names this file, sets `edits_adr_0009_in_place: false`, and enumerates
  the ADR-0009 decisions this record must restate as still current.
