# Atlas Research Stream Reconciliation

Document ID: ATLAS-SCOPE-RECONCILIATION-002
Version: 1.0
Status: OWNER_DECISION_RECEIVED_IMPLEMENTED_BY_REGISTRY_V4_29
Authority Class: REPOSITORY_STATE_RECONCILIATION
Program: PROJECT_ATLAS_AI
Created: 2026-08-31

Pattern authority: `governance/ATLAS_CURRENT_STATE_ALIGNMENT_v1.0.md`
(ATLAS-STATE-ALIGNMENT-001), whose truth model and authority boundaries this
record follows and does not modify.

Sibling record: `governance/ATLAS_EXECUTION_STREAM_SCOPE_RECONCILIATION_v1.0.md`
(ATLAS-SCOPE-RECONCILIATION-001, GOV-DRIFT-002). That record is left
unmodified. This is a separate finding on a separate branch.

---

## 1. Purpose

This record reconciles two statements that were both true in this repository
before registry v4.29:

1. REM-001, as carried forward through
   `governance/current/ATLAS_MILESTONE_REGISTRY_v4.28.json`, records
   `feature_expansion_freeze: true` and `source_changes_authorized: false`
   repository-wide, with exceptions only for the two explicitly ratified
   bounded substreams BLOCK3-EXECUTION-SAFETY and
   BLOCK6C-VENUE-METADATA-ADAPTER.
2. The branch `research/edge-validation` carried 20 commits made after the
   merge base with that ratified stream, covered by **no** governance record,
   and was simultaneously running on a 2026-08-13 snapshot of the execution,
   risk and capital core — 40 ratified commits behind it.

It also records the reconciliation action itself: the merge of the ratified
stream into `research/edge-validation`, the two name collisions that merge
required resolving, and a pre-existing architecture-inventory defect that the
governance gap had concealed.

This document does not rewrite historical evidence and does not grant
authority.

---

## 2. Search Performed And Its Result

Scope of search: `governance/` (all files) on both branches, plus a per-commit
check of every commit in the divergence range.

| query | result |
| --- | --- |
| `governance/**` on `research/edge-validation` mentioning `edge-validation`, `edge_validation`, `research/` as a stream | none |
| `governance/**` mentioning `GOV-DRIFT-004` before this record | none |
| commits in `0942391..127a05d` touching `governance/` | **0 of 20** |
| `governance/` tree on `research/edge-validation` vs. merge base `0942391` | identical; the branch never wrote a governance record |
| ratified substreams listed in v4.28 | `BLOCK3-EXECUTION-SAFETY`, `BLOCK6C-VENUE-METADATA-ADAPTER` — neither covers this branch |

Result: **no governance record covered `research/edge-validation`.** None was
invented. This is the gap this document closes, as finding `GOV-DRIFT-004`.

---

## 3. Repository Truth (Git-authoritative)

Verified by direct command output on 2026-08-31. Every figure below was
re-derived from git in this session; no figure was carried over from a prior
session's notes or checkpoint.

### 3.1 Divergence structure

| item | value |
| --- | --- |
| merge base | `0942391dc2a2b7c4255751864831cd55bf526e9f` ("docs: record block2 freeze evidence", 2026-08-13) |
| `feat/block3-execution-safety` HEAD | `59225d1ad57258caa3a549a0a85a72c201e8c7ed` |
| `research/edge-validation` HEAD before this reconciliation | `127a05d2dc0e9a08f995e311339adfd58c61eae8` |
| commits on `feat/block3-execution-safety` since base | 40 |
| commits on `research/edge-validation` since base | 20 |
| files touched by the ratified side since base | 120 |
| files touched by the research side since base | 42 |
| files touched by **both** sides | 2 |

Command: `git rev-list --left-right --count feat/block3-execution-safety...research/edge-validation` → `40  20`.

### 3.2 Governance coverage of the incoming (ratified) side — verified, not assumed

The registries' own coverage claims were checked against git rather than
accepted at face value.

| range | commits | instrument | verification |
| --- | --- | --- | --- |
| `3aca7cf..ddd6c45` | 58 | GOV-DRIFT-002, registry v4.27 (`46df920`) | `git rev-list --count` → 58, matches the registry's claim |
| `ddd6c45..3265b44` | 3 | GOV-DRIFT-003, registry v4.28 (`59225d1`) | `git rev-list --count` → 3; 1 source commit ratified, 2 governance instruments excluded |
| `59225d1` | 1 | the registry v4.28 commit itself | `git show --name-only` → touches only `governance/current/ATLAS_MILESTONE_REGISTRY_v4.28.json` |

`git merge-base --is-ancestor 3aca7cf 0942391` returns true: the merge base
lies **inside** the GOV-DRIFT-002 ratified range. Therefore all 40 incoming
commits since the merge base fall within a ratified range, and the incoming
side contributes **zero** uncovered source commits.

### 3.3 The uncovered range on the receiving side

All 20 commits in `0942391..127a05d`. Per-commit check: **0 of 20 touch
`governance/`**, so unlike the GOV-DRIFT-003 range there are no governance
instruments to exclude — every commit in the range is a source, tooling, or
documentation commit.

| class | commits | notes |
| --- | --- | --- |
| runtime source (in the runtime closure) | `5d033a7`, `1a49178`, `c86d5ad` | `web_app.py`, `observability/*`, `templates/dashboard.html`, `atlas_finance/market_data/binance_public_provider.py` |
| source, deliberately unwired (not in the runtime closure) | `a3317d7`, `c86d5ad` | the `research/` package and the market-data archive store; nothing reachable from `main.py` or `web_app.py` imports either |
| Claude Code tooling (`.claude/`) | `93c5083`, `99ba183`, `5569ccb`, `47b1166`, `ca12c58`, `e3708f2`, `1edb01c` | five skills and two subagents; no runtime effect |
| project documentation | `4d6f8b5`, `45496d8`, `128916b` | `CLAUDE.md` and the checkpoint skill/storage convention |
| checkpoint records | `bd10cd3`, `b954a05`, `6571965`, `d3dbeea`, `127a05d` | under `checkpoints/` |
| repository hygiene | `3d6cd04` | `.gitignore` for archive database sidecars |

Five research-side files are inside the runtime closure:
`atlas_finance/market_data/binance_public_provider.py`, `web_app.py`, and the
three `observability/` modules.

### 3.4 Verified test baseline before reconciliation

`python -m pytest tests/ -q` at `127a05d`, Python 3.14.6, ASCII `--basetemp`
override:

```
3 failed, 1398 passed in 29.63s
```

The three failures are recorded in §5. They are pre-existing on this branch
and were not introduced by the reconciliation.

---

## 4. Finding GOV-DRIFT-004

**Class:** GOVERNANCE_SCOPE_DRIFT. Same class as GOV-DRIFT-002 and
GOV-DRIFT-003, separate instance, separate branch, its own identifier.

**Severity:** P1.

**Statement.** Twenty source, tooling and documentation commits existed on
`research/edge-validation` with no governance record of any kind, while
REM-001's repository-wide `feature_expansion_freeze` and
`source_changes_authorized: false` remained in force and named only two
ratified substreams, neither of them this branch.

**Aggravating circumstance specific to this instance.** The branch was not
merely ungoverned; it was 40 ratified commits *behind* on the execution, risk
and capital core while adding research and observability work on top of the
stale snapshot. Blocks 3, 4, 5, 5a, 5b, 5c and 6c — including durable
execution storage, reservation capital reclamation, fee settlement, venue
precision and venue rule freshness — were absent from the branch on which new
work was being written.

---

## 5. Concealed Defect Surfaced By This Reconciliation

Recorded as a finding in its own right, not folded into GOV-DRIFT-004.

**ARCH-INVENTORY-001.** Commit `5d033a7` (2026-08-29) added the
`observability/` package and imported it from `web_app.py`, a declared runtime
entry point, without adding a `layer_rules` entry to
`packaging/atlas_architecture_map.json` or regenerating
`packaging/atlas_runtime_closure.json`. Three architecture-governance tests
failed continuously from that commit onward:

- `tests/architecture/test_layer_assignment_is_total.py`
- `tests/architecture/test_forbidden_layer_imports.py`
- `tests/architecture/test_runtime_closure_matches_inventory.py`

**Why it went unobserved.** Nothing on this branch was gated on a governance
record, an evidence document, or a green suite, because no governance record
covered the branch. This is a direct, demonstrated consequence of
GOV-DRIFT-004 rather than an unrelated coincidence.

**Remediation** — commit `41cab14`, `fix(architecture): register
observability/* as L5 in the architecture map`. `observability/*` is assigned
**L5 (PRESENTATION)** on the following evidence:

- its only consumer is `web_app.py`, itself L5, so the edge is L5 → L5, which
  is not a forbidden edge;
- `observability/panel_router.py` and `observability/panel_sources.py` import
  only stdlib and `fastapi`, reaching no domain, infrastructure, application
  or research module, so the assignment introduces no cross-layer edge at all;
- L2 is excluded on the layer's own definition — the package owns no store,
  journal, event bus or external service integration, and `panel_sources.py`
  reads already-produced artifacts off disk — and an L2 assignment would make
  the shipped `web_app.py` → `observability` import a hard forbidden L5 → L2
  edge.

The inventory artifacts were regenerated with the repository's own documented
generator, `python tools/build_architecture_inventory.py closure --write` and
`map --write`, not hand-edited. Runtime closure 102 → 105 modules; the three
added entries are exactly the `observability` modules; no existing module's
layer assignment changed. **No test was modified or weakened.**

No ADR was authored for this assignment. It registers an existing package
against existing layer definitions and creates no new architectural rule.
Whether the owner nevertheless wants an ADR is **UNKNOWN** and is not inferred
here.

---

## 6. The Reconciliation Action

### 6.1 Name collisions resolved before merging — commit `9d3b101`

Both branches independently claimed two identical names after the merge base:

| name | ratified side (`feat/block3-execution-safety`) | ungoverned side (`research/edge-validation`) |
| --- | --- | --- |
| `docs/adr/0005-*.md` | `0005-operator-bootstrap-runbook.md` (`22f8bba`, 2026-08-13) | `0005-historical-market-data-archive.md` (`c86d5ad`, 2026-08-29) |
| `data_layer/market_data_sqlite.py` | Package-1 dataset manifest/identity backend (`a7b95c8`, 2026-08-15) | OHLCV bar archive with per-batch provenance (`c86d5ad`, 2026-08-29) |

The two ADR files have different filenames, so git would have merged both in
silently and left two ADR-0005 documents in the repository. The two Python
modules share one path and were the **only** merge conflict
(`git merge-tree` → `CONFLICT (add/add)`); they are not variants of one
another but different modules that happen to share a filename and a class name
`MarketDataSQLiteStorage` with incompatible constructors (`database_path`
positional vs. keyword-only `state_directory`).

**Resolution rule applied:** in each collision the earlier claim, which is also
the governance-ratified one, keeps the name; the later, ungoverned claim
yields. No ratified file was touched.

- `docs/adr/0005-historical-market-data-archive.md` → `docs/adr/0006-…`
- `data_layer/market_data_sqlite.py` → `data_layer/market_data_archive_sqlite.py`
- `tests/test_market_data_sqlite.py` → `tests/test_market_data_archive_sqlite.py`
- four import sites updated; renames performed with `git mv` and detected by
  git as renames (R098 / R080 / R099), preserving history

The ADR's status section records the renumbering and its reason; the archive
module's docstring records that a same-named, differently-contracted
`MarketDataSQLiteStorage` exists in `data_layer.market_data_sqlite`.

### 6.2 Merge — commit `86955ee`

`git merge --no-ff feat/block3-execution-safety`, parents `9d3b101` and
`59225d1`. Because the collisions were resolved beforehand, the merge carried
**no conflict resolution**; a `git merge-tree` dry run against the resolved
tree returned exit 0. Registries v4.19–v4.28 arrived unmodified.

### 6.3 Verified test baseline after reconciliation

`python -m pytest tests/ -q` at the reconciled tree, Python 3.14.6, ASCII
`--basetemp` override:

```
2641 passed in 72.46s
```

Delta attribution:

| quantity | value | basis |
| --- | --- | --- |
| ratified-side baseline | 2443 | registry v4.28 `validation_evidence`, measured at `3265b44` |
| `3265b44` → `59225d1` test change | 0 | `git show --name-only 59225d1` touches only the v4.28 registry file |
| research-side test files added | 198 | `pytest --collect-only -q` across the eight research-added test modules |
| expected total | 2443 + 198 = **2641** | |
| measured total | **2641** | |
| unexplained delta | **0** | |

The three architecture failures of §5 pass in the reconciled tree.

---

## 7. Owner Decision

Unlike ATLAS-SCOPE-RECONCILIATION-001, this record does not present options
for later selection. The owner issued an explicit governance instruction in
session on 2026-08-31 directing that the ratified stream be reconciled into
`research/edge-validation` and that the branch's own uncovered commits be
closed "as one coherent governance action", with the successor record
following the v4.27/v4.28 pattern.

**Decision evidence state:** `OWNER_EXPLICITLY_ASSERTED_IN_GOVERNANCE_INSTRUCTION`
— the same evidence class recorded for GOV-DRIFT-002 in v4.27 and GOV-DRIFT-003
in v4.28.

**Implemented by:** `governance/current/ATLAS_MILESTONE_REGISTRY_v4.29.json`.

The instruction explicitly placed the two previously recorded conflicts C1 (no
document enumerates the Phase 0–10 roadmap) and C2 (active milestone
`FIN-004.1a-C1` has no status object) **out of scope**. They remain open and
are not addressed, resolved, or closed by this record.

---

## 8. Authority Boundary

This document records repository reality, a governance gap, and the action
taken to close it. It does not grant:

- production deployment authority;
- LIVE trading authority;
- retroactive authorization for any commit outside the range registry v4.29
  names;
- permission to continue the stream beyond the ratified range;
- a new roadmap phase;
- relief from REM-001 Gate 1;
- permission to modify historical governance evidence.

Unchanged and explicitly reaffirmed:

```
production_authority      = NONE
live_trading_authority    = DENIED
autonomous_deployment     = DENIED
real_money_trading        = DENIED
feature_expansion_freeze  = true (REM-001)
source_changes_authorized = false (REM-001, outside ratified substreams)
```

LIVE authority must be granted explicitly by a future owner decision. No
absence of denial in this or any document may be interpreted as granting it.

Whether the validation environment used for the 2641-test baseline satisfies
the ENV-ISOLATION-001 canonical isolated-virtual-environment requirement was
not established. It is recorded as **UNKNOWN**, not inferred, exactly as
registry v4.28 recorded the same question for its own baseline.

---

## 9. Historical Preservation

Untouched and unmodified by this record and by registry v4.29:

- `governance/history/ATLAS_MILESTONE_REGISTRY_v4.18.json`
- `governance/current/ATLAS_MILESTONE_REGISTRY_v4.19.json` … `v4.28.json`
- `governance/ATLAS_CURRENT_STATE_ALIGNMENT_v1.0.md`
- `governance/ATLAS_EXECUTION_STREAM_SCOPE_RECONCILIATION_v1.0.md`
- `governance/findings/*`

No registry field was edited in place. Reconciliation is additive only, by a
new versioned successor record, per
`historical_governance_records_remain_immutable` and
`historical_v4_18_immutable`.

---

## 10. Recovery

The pre-reconciliation state of `research/edge-validation` is preserved at
`127a05d` by two refs created before any change was made:

- branch `backup/pre-block3-merge-research-edge-validation`
- annotated tag `pre-block3-merge/research-edge-validation`

Neither ref is required by the reconciliation; both exist so the action is
reversible without relying on the reflog.
