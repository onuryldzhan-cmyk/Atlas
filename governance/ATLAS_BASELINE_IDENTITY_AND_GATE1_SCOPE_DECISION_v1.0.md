# Atlas Baseline Identity Resolution And Gate 1 Scope Decision

Document ID: ATLAS-BASELINE-IDENTITY-001
Version: 1.0
Status: OWNER_DECISION_RECEIVED_IMPLEMENTED_BY_REGISTRY_V4_32
Authority Class: REPOSITORY_STATE_RECONCILIATION
Program: PROJECT_ATLAS_AI
Created: 2026-09-01

Pattern authority: `governance/ATLAS_CURRENT_STATE_ALIGNMENT_v1.0.md`
(ATLAS-STATE-ALIGNMENT-001), whose truth model and authority boundaries this
record follows and does not modify.

Immediate predecessor, left unmodified:
`governance/ATLAS_REM001_SPECIFICATION_ARTIFACT_INTEGRITY_v1.0.md`
(ATLAS-SPEC-INTEGRITY-001, GOV-DRIFT-005), commit `6059c8f`. That record's
section 5 left two findings explicitly open with owner decisions pending. This
record carries the owner decisions that answer both of them.

Sibling records, all left unmodified:
`governance/ATLAS_EXECUTION_STREAM_SCOPE_RECONCILIATION_v1.0.md`
(ATLAS-SCOPE-RECONCILIATION-001, GOV-DRIFT-002) and
`governance/ATLAS_RESEARCH_STREAM_RECONCILIATION_v1.0.md`
(ATLAS-SCOPE-RECONCILIATION-002, GOV-DRIFT-004).

---

## 1. Purpose

`ATLAS-SPEC-INTEGRITY-001` section 5 recorded two findings as
`OPEN_OWNER_DECISION_PENDING` and resolved neither:

1. **ARCH-P0-001 — baseline identity conflict.** Gate 1 computes a matrix *of*
   a baseline, and which baseline was authoritative was recorded as
   **UNKNOWN**.
2. **Gate 1 authorization state is self-contradicting.** Gate 1 was recorded as
   open and named as the next work candidate while every execution path for it
   was unauthorized.

Registries v4.30 and v4.31 both carried those two findings forward unchanged
and explicitly declined to resolve either. This record carries the owner
decisions that resolve the first and materially change the second, and defines
the exact boundary of that change.

This record creates **no new finding**. It resolves one existing finding and
narrows one existing contradiction. Per the
`each_drift_instance_requires_its_own_finding_id` invariant, no new
`GOV-DRIFT-*` identifier is minted, because no new drift instance is being
reported: ARCH-P0-001 and GATE-1-AUTHORIZATION-CONTRADICTION are the
identifiers already in use for both matters, and both are addressed under
those existing identifiers.

---

## 2. Repository Truth Verified For This Decision

Measured 2026-09-01 against `research/edge-validation` at
`5f02980ed4ded02d285ebfdff92c6dc40c175751`, tree
`b1e79ad5c655f0927c5711455b7d970a06f822b3`. Git is authoritative; nothing below
is inferred.

| measurement | value | method |
| --- | ---: | --- |
| Git-tracked `.py` files at HEAD | 861 | `git -c core.quotepath=false ls-files -z -- '*.py'` |
| Git-tracked `.py` files outside `tests/` | 735 | same, minus the `tests/` prefix |
| modules in the static runtime closure | 105 | `packaging/atlas_runtime_closure.json`, machine-checked by `tools/build_architecture_inventory.py check` |
| Git-tracked `.py` files at registry v4.30's commit `85bf8d7` | 860 | `git -c core.quotepath=false ls-tree -r --name-only -z 85bf8d7` |
| `.py` files added between `85bf8d7` and HEAD | 1 | `git diff --name-status --diff-filter=A 85bf8d7 HEAD -- '*.py'` |

**The 860 → 861 delta is fully attributed.** Exactly one `.py` file was added:
`tests/architecture/test_import_graph_reproduces_closure.py`, at commit
`6ec2f5b`, the Gate 1 deliverable 3 regression test recorded by registry v4.31.
The non-test count is unchanged at 735 because that file is under `tests/`.
`ATLAS-SPEC-INTEGRITY-001` section 5.1 and registries v4.30 and v4.31 record
860; that figure was correct when written and is preserved as written. It is
superseded by 861 here, with the single-commit cause named, rather than
silently restated.

**Method note, recorded because it changed a number.** Counting tracked `.py`
files with `git ls-tree -r --name-only` under default settings yields 834, not
861. The difference is not a discrepancy in the repository: it is Git's
`core.quotepath` behaviour, which wraps paths containing non-ASCII bytes in
quotes, so 27 such paths do not match a `\.py$` anchor. Every count in this
record disables `quotepath`, which is also what
`tools/build_architecture_inventory.py` does. The 861 figure agrees with the
node count independently recorded in `packaging/REM-001_IMPORT_GRAPH.json`.

---

## 3. Decision 1 — ARCH-P0-001 Is Resolved

**Status: RESOLVED_BY_OWNER_DECISION.** ARCH-P0-001 moves from
`OPEN_OWNER_DECISION_PENDING` to `RESOLVED`.

### 3.1 The decision

The canonical Atlas baseline, going forward, is **the current Git HEAD of
branch `research/edge-validation` in this repository**, and thereafter whatever
that branch's HEAD becomes as work proceeds. At the moment of this decision
that is commit `5f02980ed4ded02d285ebfdff92c6dc40c175751`, tree
`b1e79ad5c655f0927c5711455b7d970a06f822b3`, 861 tracked `.py` files.

The baseline is defined as **a Git commit in this repository**, not as a
filesystem path and not as a file count. That is the substance of the decision,
not a formality: the previous baseline was defined by an absolute path on one
machine, and that is precisely how it became unresolvable.

### 3.2 What is superseded

`ARCH-001.2.2_OWNER_CANONICAL_BASELINE_DECISION.md`
(`ARCH-001.2.2-OWNER-BASELINE`, `APPROVED WITH SCOPE CONTROLS`) approved:

```
C:\Users\HUAWEİ\OneDrive\Masaüstü\Project_Atlas_AI
```

and its recorded 691-file Python baseline, under baseline identity
`APPROVED_CANONICAL_REPOSITORY_ROOT`.

Verified 2026-09-01: **that path does not exist on disk.** The decision record
itself does still exist, untracked, at
`SOURCE_REPOSITORY/GOVERNANCE_AND_ARCHITECTURE/ARCH-001.2.2_OWNER_CANONICAL_BASELINE_DECISION.md`
within the delivery package, with a second copy under
`architecture_evidence/ARCH-001/source_scope/`.

That approval is **superseded**, effective at this record.

### 3.3 "Superseded" means superseded, not recovered and not deleted

Recorded explicitly, because the distinction is the whole point of the
decision:

- The old canonical root is **not recovered.** No attempt is made or authorized
  to locate, reconstruct, re-extract, or re-derive the 691-file tree. It is not
  a pending task; it is closed.
- The old approval is **not deleted from history.** The
  `ARCH-001.2.2-OWNER-BASELINE` record stands exactly as written, and remains
  the true account of what was approved on the date it was approved. Registries
  v4.19 through v4.31 continue to carry `python_files: 691`,
  `baseline_identity: APPROVED_CANONICAL_REPOSITORY_ROOT`, and the
  `candidate_scope_counts` census under `architecture_execution_program`. None
  of that is edited. It is historical fact and stays historical fact.
- What changes is only which baseline is **authoritative going forward.** The
  691-file baseline is no longer the reference against which current work is
  measured. The current Git HEAD is.

This follows the same additive discipline as every prior reconciliation in this
repository: drift is reconciled by adding a successor record, never by editing
a predecessor.

### 3.4 Figures that are now superseded, and what they are superseded by

| superseded figure | recorded in | superseded by | status of the old figure |
| --- | --- | --- | --- |
| canonical root `…\Project_Atlas_AI` | `ARCH-001.2.2-OWNER-BASELINE`; registry `architecture_execution_program.phase_2_2` | branch `research/edge-validation`, HEAD `5f02980` | preserved as written; path confirmed absent |
| `python_files: 691` | registry `architecture_execution_program.phase_2_2` | 861 tracked `.py` at HEAD | preserved as written |
| `candidate_scope_counts` (ARCHIVE 276, UNKNOWN 230, TEST 73, BACKUP 38, REPORT_COPY 34, TOOL 26, QUARANTINE 14) | same block | **nothing yet** — see 3.5 | preserved as written |
| `runtime_entrypoint_pattern_matches: 529` | same block | `REM-001_RUNTIME_CONSTRUCTION_PATHS.md`, once produced | preserved as written |
| `860` tracked `.py` | ATLAS-SPEC-INTEGRITY-001 §5.1; registries v4.30, v4.31 | 861, delta attributed in §2 | preserved as written |

### 3.5 What this decision does NOT resolve

Recorded so the resolution is not read wider than it is:

- It does **not** classify any file. The `candidate_scope_counts` census above
  described the 691-file tree, and no equivalent census of the 861-file tree
  exists. Producing one requires human classification judgment and is
  explicitly outside the authorization in section 4.
- It does **not** determine `canonical_module_set`, which remains
  `NOT_YET_DETERMINED`.
- It does **not** assert that every file at HEAD is active, correct, or
  canonical. The old decision was careful to say the same thing about its own
  691 files, and that caution carries over unchanged: approving a baseline
  approves *what is being measured*, not *the quality of what is measured*.
- It does **not** close Gate 1, resolve GOV-DRIFT-005, or restore any of the 41
  still-absent REM-001 specification artifacts.
- It does **not** grant production, LIVE, or deployment authority.

### 3.6 Why resolving it matters mechanically

Gate 1 computes a matrix of a baseline. With the baseline UNKNOWN, every Gate 1
deliverable had to be either blocked or, as with deliverable 3, deliberately
confined to something that is a pure function of the tree it stamps and
therefore independent of the answer. With the baseline settled as "this
repository's HEAD," the remaining mechanical deliverables have a well-defined
subject for the first time.

---

## 4. Decision 2 — Gate 1 Authorization Is Broadened

**Status of GATE-1-AUTHORIZATION-CONTRADICTION: NARROWED_BY_OWNER_DECISION,
NOT_FULLY_RESOLVED.** See 4.6.

### 4.1 The decision

Authorization for REM-001 Gate 1 work is broadened from the single-artifact
exception granted by registry v4.30 (`REM-001-GATE1-D3-EMISSION`, now spent) to
a standing authorization for a **class** of work:

> **MECHANICAL / GENERATED Gate 1 tooling work** — read-only analysis of the
> repository, artifact generation, and emission from existing or newly-written
> analysis tooling.

Under this authorization such work no longer requires a separate narrow
authorization request per deliverable, the way deliverable 3 did.

Authorization ID: **`REM-001-GATE1-MECHANICAL`**.

### 4.2 What "mechanical / generated" means, precisely

A deliverable is inside this authorization when **all** of the following hold:

1. Its content is computed from repository contents by a deterministic
   program — re-running the generator on the same tree reproduces it.
2. It is read-only with respect to everything it analyses.
3. It asserts only what the analysis observed, and records anything it did not
   establish as UNKNOWN rather than inferring it.
4. It carries a falsifiable regression check against an independently computed
   reference, so that a wrong artifact can fail rather than merely look
   plausible.

Newly-written analysis tooling is permitted, which is the substantive widening
over `REM-001-GATE1-D3-EMISSION` — that authorization permitted only "the
smallest additive code change required" to an existing generator. Tooling
written under this authorization is still subject to condition 4 above and to
the conditions in 4.4.

### 4.3 The carve-outs — three things this does NOT extend to

These are exclusions from the authorization, not cautions. Each is stated in
the form that decides cases.

**Carve-out (i) — human classification judgment is never authorized.**

Any deliverable, or any field within a deliverable, that requires human
classification judgment remains unauthorized and requires its own separate
owner decision. The governing gate is
`ARCH-001.2.1_MODULE_INVENTORY_SCHEMA.json`'s own, stated in its companion
`ARCH-001.2.1_MODULE_INVENTORY_SCHEMA.md`:

> Human architecture review must resolve source scope, responsibility, domain,
> owner and lifecycle for critical modules. Scanner evidence may propose but
> never approve these values.

The five reserved values are therefore **`source_scope`**,
**`current_responsibility` / `intended_responsibility`**, **`domain`**,
**`owner`**, and **`lifecycle`**. A generated artifact may present evidence
bearing on them; it may never assign them.

This carve-out **remains true regardless of this broadened authorization**. The
broadening is about *who must ask before running a scanner*; it changes nothing
about *what a scanner is allowed to conclude*. Registry v4.31 recorded
deliverable 3 as deliberately omitting those fields, and that same omission is
required of every artifact produced under `REM-001-GATE1-MECHANICAL`.

Two adjacent enum fields, `criticality` and `state_ownership`, are not named in
the schema's own sentence above. They are nonetheless treated as reserved under
this record, for the reason the sentence gives rather than by its letter: both
are approval-shaped enumerations over the same modules, and asserting either
from scanner evidence would convert UNKNOWN into inferred truth. The adjacent
schema field `persistence` is an observation — an array of paths — and is
inside the authorization.

Deliverable 1, `REM-001_CANONICAL_COMPONENT_MATRIX.json` / `.md`, is the
deliverable this carve-out most directly governs: a component matrix is exactly
an assignment of scope, responsibility, domain, owner, and lifecycle. It is
**outside** this authorization and needs its own owner decision. Deliverables
2, 6, 7 and 9, which consume or validate that matrix, are outside it for the
same reason.

**Carve-out (ii) — no change to Atlas source, risk, execution, or capital
code.**

This authorization permits writing and running *analysis tooling*. It permits
no change whatsoever to Atlas application source, and specifically none to
risk, execution, or capital code. `source_changes_authorized` remains **false**
and is not set true, in any general sense, by this record.

Analysis tooling under `tools/` and its tests under `tests/` are the only code
this authorization permits to be added or modified, and only for the purpose of
producing or verifying a Gate 1 deliverable.

**Carve-out (iii) — the specification-missing question stays OPEN.**

GOV-DRIFT-005 is not resolved, narrowed, or closed by this record. The REM-001
specification and 41 of its 42 named artifacts remain absent. Producing a file
that carries a declared name does not restore the specification that would
define its content, and conformance of any artifact produced under this
authorization to that absent specification is **UNKNOWN and unknowable**.

Deliverable 8, `REM-001_SPECIFICATION_RECONCILIATION_MATRIX.md`, reconciles
intended responsibility against actual responsibility. Its intended-
responsibility source is among the absent artifacts, so it has no left-hand
side. **Deliverable 8 remains blocked by the absent specification, not by
authorization** — broadening authorization does not unblock it, and no
authorization can, until that question is answered.

### 4.4 Conditions carried forward

Every condition attached to `REM-001-GATE1-D3-EMISSION` by registry v4.30
carries forward and applies to each deliverable produced under
`REM-001-GATE1-MECHANICAL`:

1. `NO_CLASSIFICATION_JUDGMENT_ENCODED_IN_THE_ARTIFACT` — per carve-out (i).
2. `READ_ONLY_WITH_RESPECT_TO_ANALYZED_SOURCE` — per carve-out (ii).
3. `ARTIFACT_SELF_DESCRIBING_BY_GIT_COMMIT_AND_TREE` — every artifact stamps
   the commit and tree it was generated from, and whether the tracked working
   tree was clean at generation. This is what makes an artifact describe a
   baseline rather than assume one.
4. `REGRESSION_GATE_AGAINST_AN_INDEPENDENTLY_COMPUTED_REFERENCE` — per 4.2
   condition 4. A gate that restates the artifact's own computation does not
   satisfy this; the reference must be reachable by a different path.
5. `EXISTING_TESTS_REMAIN_GREEN_AND_UNMODIFIED` — no test is modified or
   weakened to accommodate a deliverable.
6. `PER_DELIVERABLE_EVIDENCE_RECORDED_IN_A_VERSIONED_SUCCESSOR_REGISTRY` — this
   authorization removes the need to *ask* before producing a mechanical
   deliverable. It does not remove the need to *record* what was produced.
   Each deliverable's artifact commit, generation commit, counts, regression
   result and validation evidence are recorded in a successor registry, exactly
   as registry v4.31 recorded deliverable 3. This mirrors the existing
   `ratified_substream_requires_per_package_evidence` invariant.

### 4.5 What is NOT granted

This record does not set, imply, or create a basis for setting any of the
following true, in any general sense or for any other purpose:

```
tooling_execution_authorized            (not set true in any general sense)
tooling_implementation_authorized       (not set true in any general sense)
tool_implementation_authorized          (not set true in any general sense)
canonical_mapping_execution_authorized  false
future_analysis_tooling_authorized      (not set true in any general sense)
implementation_authorized               false
source_changes_authorized               false
```

`tooling_gate` remains `T1_NOT_STARTED` and `tooling_trust_level` remains
`L0_PROTOTYPE_NOT_IMPLEMENTED`. Producing deliverables mechanically does not
advance either: those flags describe a validated, trusted canonical-mapping
tool chain, which is not what this authorization creates.

Not authorized:

- deliverable 1 (`REM-001_CANONICAL_COMPONENT_MATRIX.json` / `.md`), or
  deliverables 2, 6, 7, 9 which depend on it — carve-out (i);
- any change to Atlas application, risk, execution, or capital source —
  carve-out (ii);
- deliverable 8 — blocked by carve-out (iii), independently of authorization;
- closing, certifying, or partially certifying Gate 1 —
  `gate_1_closure_authority` remains `OWNER_ACCEPTANCE_REQUIRED` and
  `gate_1_state` remains `OPEN_NOT_CERTIFIED`;
- reconstructing, substituting for, or standing in place of any of the 41
  absent artifacts;
- relief from the REM-001 `feature_expansion_freeze`, which remains in force
  repository-wide;
- retroactive authorization for any commit not named by a successor registry;
- any production, deployment, or LIVE authority.

### 4.6 Effect on GATE-1-AUTHORIZATION-CONTRADICTION

The contradiction recorded in `ATLAS-SPEC-INTEGRITY-001` §5.2 was that Gate 1
is open and named as the next work candidate while *every* execution path for
it is unauthorized. That is no longer true: the mechanical path is now
authorized as a class.

It is **narrowed, not resolved.** The residual contradiction is real and is
recorded rather than declared closed: Gate 1 cannot be *completed*
mechanically. Deliverable 1 is a human-classification deliverable, four more
deliverables depend on it, and deliverable 8 is blocked by an absent
specification. A gate whose remaining path requires decisions nobody has made
yet is still a gate that cannot be advanced to closure without further owner
decisions. The finding therefore stays open in narrowed form rather than being
marked resolved.

---

## 5. Authority Boundary

This document records two owner decisions. It does not grant:

- production deployment authority;
- LIVE trading authority;
- autonomous deployment authority;
- retroactive authorization for any commit not named by registry v4.32 or a
  successor;
- a new roadmap phase;
- closure of REM-001 Gate 1;
- permission to modify historical governance evidence.

Unchanged and explicitly reaffirmed:

```
production_authority      = NONE
live_trading_authority    = DENIED
autonomous_deployment     = DENIED
real_money_trading        = DENIED
feature_expansion_freeze  = true (REM-001)
source_changes_authorized = false (REM-001, outside ratified substreams; the
                            authorization in section 4 covers analysis tooling
                            under tools/ and tests/ only, and no Atlas
                            application source)
```

LIVE authority must be granted explicitly by a future owner decision. No
absence of denial in this or any document may be interpreted as granting it.

---

## 6. Historical Preservation

Additive only. This record modifies nothing.

- Registries v4.19 through v4.31 are unmodified. The v4.31 blocks
  `rem001_specification_artifact_integrity` and
  `rem001_gate1_deliverable_3_production` — including their
  `findings_explicitly_left_open` sections, which record both findings as open
  and pending — are preserved byte-identical in every historical registry that
  carries them. They were accurate when written; this record states the state
  as of v4.32.
- `governance/ATLAS_REM001_SPECIFICATION_ARTIFACT_INTEGRITY_v1.0.md`,
  `governance/ATLAS_RESEARCH_STREAM_RECONCILIATION_v1.0.md`,
  `governance/ATLAS_EXECUTION_STREAM_SCOPE_RECONCILIATION_v1.0.md` and
  `governance/ATLAS_CURRENT_STATE_ALIGNMENT_v1.0.md` are unmodified.
- `ARCH-001.2.2_OWNER_CANONICAL_BASELINE_DECISION.md` and
  `ARCH-001.1_CLOSE_DECISION.md` are unmodified and untracked, exactly as
  ATLAS-SPEC-INTEGRITY-001 recorded them. Their custody risk is unchanged by
  this record.
- No historical count, census, or figure is edited anywhere. Superseded figures
  are listed in §3.4 with what supersedes them.

Implemented by registry v4.32, committed next. Per the
`governance_record_commits_cannot_self_ratify` invariant, this record does not
ratify itself; the successor registry cites this record's commit.
