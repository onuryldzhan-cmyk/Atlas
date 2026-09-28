# ATLAS REM-001 Gate 1 — Completion Plan (v1.0, PROPOSED)

- **Status:** PROPOSED. This is a plan, not an authorization.
  - `implementation_authorized`, `canonical_mapping_execution_authorized` and `source_changes_authorized` remain false for REM-001.
  - `gate_1_closure_authority` remains `OWNER_ACCEPTANCE_REQUIRED`.
- **Date:** 2026-09-28 (UTC). Registry at authoring: v4.91. Active milestone: `REM-001/GATE_1_CANONICAL_COMPONENT_MAPPING`.
- **Requested by:** the owner, session of 2026-09-28 ("Hepsini yap"). Option 1 was worded as: read Gate 1's scope and acceptance criteria, present a plan, and start work only on the owner's authorization.

## 1. Where Gate 1 stands (FACT, from registry v4.91)

The latest count is `d6_production_catchup_d7_closure_and_gate1_count_update.gate_1_deliverable_count_after_this_record`. Six of nine deliverables are produced; `gate_1_state = OPEN_NOT_CERTIFIED`.

| # | Deliverable | State | What blocks it |
|---|---|---|---|
| D1 | `REM-001_CANONICAL_COMPONENT_MATRIX.json` | PRODUCED_PENDING_OWNER_REVIEW | Owner review |
| D2 | `REM-001_CANONICAL_COMPONENT_MATRIX.md` | PRODUCED_PENDING_OWNER_REVIEW | Owner review |
| D3 | `packaging/REM-001_IMPORT_GRAPH.json` | produced | — |
| D4 | `packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md` | produced | — |
| D5 | `packaging/REM-001_STATE_AUTHORITY_MAP.md` | produced | — |
| D6 | `REM-001_OVERLAP_REGISTER.json` | PRODUCED_PENDING_OWNER_REVIEW | Owner review. OVL-001's `state_ownership_disposition` is `OWNER_DECISION_REQUIRED`. |
| D7 | `REM-001_LEGACY_RETIREMENT_REGISTER.json` | STOPPED_MISSING_SPECIFICATION | No valid definition of "legacy/retirement". The v4.59 candidate matched zero of D1's modules, and the owner treated that as a failed definition. |
| D8 | `REM-001_SPECIFICATION_RECONCILIATION_MATRIX.md` | Redefined (ATLAS-REM001-GATE1-D8-REDEFINITION-001) to reconcile against the ARCH-001.2.1 baseline | The ARCH-001.2.1 schema is **not tracked in Git**; its custody is `OWNER_DECISION_PENDING` (Decision 4). It cannot be produced from this repository. |
| D9 | `REM-001_GATE1_VALIDATOR.ps1` | STOPPED_MISSING_SPECIFICATION_AND_BLOCKED_ON_UNPRODUCED_DEPENDENCIES | Its checks are unspecified, and it depends on D7. PowerShell is not available in the Linux build container; CI runs on Windows. |

**Supporting fact.** None of these files is tracked in Git:
- the REM-001 part specifications and validators it cites (`REM-001_PART*`, `REM-001_FINAL_*`, `REM_GATE1_REAL_ARCHITECTURE_MAPPING_ENTRY_CONTRACT.md`, `REM_GATE1_OWNER_AUTHORIZATION_RECORD_TEMPLATE.md`);
- the ARCH-001.2.1 schema.

This was checked with `git ls-files`. The original REM-001 specification is recorded as permanently lost (D8 redefinition, Decision 1).

**Conclusion.** Every remaining step needs an owner decision or an owner-held artifact first. No remaining deliverable can be produced from the repository alone today.

## 2. Proposed sequence

Each step names who acts and what authorization it needs.

**S1 — Owner review of D1, D2 and D6** (owner only)
- The owner accepts them or returns changes.
- For OVL-001 (`data_layer/config.py` and the other sqlite-backed modules sharing a store), the owner records which module owns the store.
- Claude can prepare a one-page review summary per deliverable if asked. That is read-only and needs no grant.

**S2 — Custody of the ARCH-001.2.1 schema** (owner decision)
- **Option (a):** the owner commits `ARCH-001.2.1_MODULE_INVENTORY_SCHEMA.md/.json` from the workstation into Git. D8 can then be produced under the existing D8 acceptance contract.
- **Option (b):** the owner names another tracked baseline. This is a further redefinition of D8 and needs a successor record.
- After S2, producing D8 needs a D8 production grant.

**S3 — Definition for D7** (owner decision)

Candidate definitions, each grounded in something the repository already computes:
- **(a) Overlap-derived.** The non-owning side of each resolved D6 overlap entry is a retirement candidate. This depends on S1 resolving OVL-001.
- **(b) Unreachable-tracked.** Tracked `.py` modules outside the checked-in runtime closure (`packaging/atlas_runtime_closure.json`), excluding tests and tooling. This is reproducible from `tools/build_architecture_inventory.py`. It lies outside D1's 105-module population by construction, so the owner must accept that D7's population differs from D1's.
- **(c) Owner-supplied.** The owner lists the modules intended for retirement.

After S3, producing D7 needs a D7 production grant.

**S4 — Specification for D9** (owner decision, then grant)

Proposed checks:
1. Every deliverable file D1–D8 exists at its registered path.
2. Every JSON deliverable parses.
3. Every module in D1 appears in D3's graph.
4. Every D6 and D7 entry references a D1 `module_id`.
5. D2 renders the same module set as D1.

Language: the registry names `.ps1`. A Python validator run as a CI step would be testable in both environments, but changing the language changes the deliverable and needs an explicit owner decision.

**S5 — Gate 1 certification package** (after S1–S4)
- Claude assembles the evidence.
- An independent audit runs (CRITICAL final gate).
- The owner accepts or rejects.
- Only an owner acceptance closes Gate 1. Whether that also lifts `PAUSED_PENDING_REM_GATE_1` is a separate owner decision recorded in the same successor registry.

## 3. What this plan does not do

- It changes no deliverable, no gate state and no authorization.
- It lifts nothing: the feature freeze and the authority state are unchanged.
- It does not assume the lost specification's content. Every definition above is a candidate for the owner, not an inferred requirement.
