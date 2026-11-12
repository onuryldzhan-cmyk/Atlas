# REM-001 D4 Drift Check — 2026-09-27

Additive comparison record. It checks every claim in REM-001 Gate 1 deliverable 4
(`packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md`, "D4") against the repository
as it stands today. It does not edit D4, does not regenerate it, and does not
replace it.

## Identity

| field | value |
| --- | --- |
| subject | `packaging/REM-001_RUNTIME_CONSTRUCTION_PATHS.md` |
| subject sha256 (checked before and after this record) | `099e806aa69ac07d27e2bb0f5fb4417002b229a60f2317999d5f7849e8710c46` (byte-unchanged) |
| subject lines | 400 |
| subject generated_from_commit | `db8bdf3f22e05a730ca6c3a8ec4eae51f8b66d4b` |
| compared against (HEAD) | `3159500ce6047ace81b067bd0ff0d0b4eaf50ed2`, branch `research/edge-validation`, only change in the working tree an untracked `.claude/agents/atlas-test-runner.md` (not in any runtime closure) |
| commits between db8bdf3 and HEAD | 140 (13 of them touch `main.py`, `web_app.py` or `core/application.py`) |
| governance record | registry v4.91, `rem001_d4_drift_check_result` |

## Effect and non-effect

- Read-only comparison. No application code, D4, D5, test or tool is changed.
- `REM-001` `gate_1_state` stays `OPEN_NOT_CERTIFIED`. This record is not
  certification or progress toward closing a gate, and it grants no authorization.
- `tools/build_rem001_gate1_maps.py` was **not** rebuilt, recovered or
  approximated as a replacement. See "Method" for the throwaway verification
  instrument used, and why its output is not a D4 successor.

## Method

D4 has two kinds of claim. The first is 277 construction-site rows (D4 lines
94–370). Each row asserts five coordinates: constructing module, class, defining
module, line and enclosing scope. The second is 35 header, scope, chain and gate
claims (D4 lines 3–66, 74–88 and 372–399).

**Instrument.** A throwaway AST verifier (scratch file, not committed, sha256
`8d2d0344236dbb1dda662d91c70c75acef92be910682328f22ebcc18b6316612`) implements
the analysis *exactly as D4 itself describes it* in its lines 29–42. It takes
every `ast.Call` over the closure modules whose callee name (`Name.id` or
`Attribute.attr`) matches a class defined in the closure. It skips a class's own
defining module, records a defining module defined more than once as `UNKNOWN`,
and uses the enclosing scope as the `::`-joined names of the enclosing class and
function definitions. Files are read as `utf-8-sig`, because `web_app.py`
carries a BOM.

**Calibration (why the instrument is trustworthy).** The verifier was first run
on the committed db8bdf3 tree (`git archive db8bdf3`) with the db8bdf3 closure
(`packaging/atlas_runtime_closure.json` at db8bdf3). It reproduced all **277/277**
D4 rows exactly on all five coordinates, with **0** extra rows. It also
reproduced every D4 scope figure: 105 modules, 368 distinct class names, 277
sites, 33 constructing modules, 117 classes constructed, 86 edges, 2 ambiguous
names (the same two) and 0 parse failures. Any difference it reports at HEAD is
therefore a change in the code, not a difference in method.

**Current closure.** `packaging/atlas_runtime_closure.json` at HEAD is
regression-enforced against the live inventory. In this session
`tests/architecture/test_runtime_closure_matches_inventory.py` and
`tests/architecture/test_composition_root_is_unique.py` gave **4 passed**
together, and the second file alone gave **2 passed**. The current closure is
therefore current evidence.

**Per-row matching.** Rows are grouped by (constructing module, class, defining
module, scope). A row whose HEAD line matches exactly is `STILL_ACCURATE`. The
remaining rows in a group are paired, in line order, with the remaining HEAD
sites of that same group and marked `DRIFTED` (line shift). A row with no HEAD
partner would be `DRIFTED` (removed), and none occurred. A row whose
constructing module has left the HEAD closure is `DRIFTED` (closure boundary).
Those rows were checked against the same file at HEAD with the db8bdf3 module
list.

**Why the instrument is not a D4 successor.** It is a comparison device. It
emits no D4-format artifact, carries no authorization, and was deliberately not
committed. Producing a current D4 is a separate, owner-authorized task (see
"Recommended next step").

## Summary

| claim set | claims | STILL_ACCURATE | DRIFTED | CANNOT_VERIFY |
| --- | --- | --- | --- | --- |
| construction-site rows (R1–R277) | 277 | 181 | 96 | 0 |
| header / scope / chain / gate claims (H1–H35) | 35 | 19 | 11 | 5 |
| **total** | **312** | **200** | **107** | **5** |

The 96 drifted rows fall into two kinds of drift:

- **72 line-number shifts.** The module, class, defining module and scope are
  unchanged, and only the line moved. By module: `core/application.py` 33,
  `core/execution_manager.py` 15, `ai/core/atlas_brain.py` 13,
  `core/market_loop.py` 5, `core/execution_transaction_journal.py` 4,
  `core/model_provider_contracts.py` 1, `main.py` 1.
- **24 closure-boundary exits.** The call is still present at the identical
  line, but the constructing module is no longer in the runtime closure:
  `data_layer/config.py` (6 rows) and `data_layer/sqlite.py` (18 rows). Commit
  `1ac3a64` made `data_layer/__init__.py` a PEP 562 lazy package
  (`data_layer/__init__.py:40`, `def __getattr__`). As a result, importing
  `data_layer.contracts` no longer eagerly loads `.config` and `.sqlite`, and the
  closure regenerated in `dad8a88` dropped them. The rows no longer describe
  *runtime* construction, which is D4's stated subject.

**No construction relationship recorded in D4 has disappeared.** Zero rows were
removed, re-scoped, or re-pointed to a different defining module.

## Most significant drift

1. **D4's enforcing regression test does not exist (H32).** D4 lines 392–393
   say its gates are "Enforced by `tests/architecture/test_rem001_construction_paths.py`".
   That file is absent at HEAD, and `git log --all -- tests/architecture/test_rem001_construction_paths.py`
   returns nothing, so it is in no commit on any ref. The generator is equally
   absent from every ref (`git log --all -- tools/build_rem001_gate1_maps.py`
   returns nothing). D4 has therefore never had the regression protection it
   claims, and nothing flagged the 107 drifts recorded here.
2. **Two new runtime entry points sit outside D4's scope (H14).** The closure's
   `entry_points` are now `main.py`, `web_app.py`, `atlas_service.py` and
   `atlas_supervisor.py`, where D4 lists only the first two. `atlas_service.py`
   arrived in commit `9fadd67` ("merge Core and Dashboard into one process") and
   `atlas_supervisor.py` in `2d7ab52` (SUPERVISOR-1). The construction chain now
   has an outer layer D4 does not show: `atlas_service.py:398`
   `return AtlasProcess(` constructs `main.py`'s `AtlasProcess`, which then
   constructs `AtlasApplication` at `main.py:406`.
3. **New composition-root wiring is not captured (omissions; see "Sites at HEAD not in D4").**
   `core/application.py::AtlasApplication::_build_services` now also constructs
   `EvidenceStore` (`:600`), `FearGreedProvider` (`:672`), `TreasuryYieldProvider`
   (`:680`) and `MarketRiskRegimeProvider` (`:681`). `core/execution_manager.py:3955`
   constructs `RestoredRiskState` in `_record_realized_risk_accounting`, and
   `ai/core/atlas_brain.py:1299` constructs `ClaimSource`. In all, 33 HEAD
   construction sites are absent from D4.
4. **Scope figures (H16–H22).** The figures now read 105→108 modules (+6: the 2
   entry points, `fear_greed_provider.py`, `treasury_yield_provider.py`,
   `core/market_risk_regime.py` and `data_layer/evidence_store.py`; −3:
   `data_layer/config.py`, `data_layer/semantic_contracts.py` and
   `data_layer/sqlite.py`), 368→384 class names, 277→286 sites, 117→121 classes
   constructed, 86→91 edges, and 2→3 ambiguous names (new: `_TransportError`).
5. **GOV-DRIFT-005 status (H6).** D4 says "OPEN". Registry v4.90
   `governance_findings.GOV-DRIFT-005.status` is
   `CONFIRMED_AND_RECORDED_BY_VERSIONED_SUCCESSOR_RECORD`.

## What still holds

The authoritative chain is intact. Each entry below is cited against HEAD:

- `AtlasApplication` is constructed only by `main.py:406` (`self.application = AtlasApplication(`).
- `AtlasRuntime` is constructed at `core/application.py:547`.
- `AtlasBrain` is constructed at `core/application.py:604`.
- `ExecutionManager` is constructed at `core/application.py:648`.
- `MarketLoop` is constructed at `core/application.py:683`.

The canonical composition-root invariant is also regression-green:
`test_composition_root_is_unique.py` gave **2 passed** this session.

## Overall verdict

**STALE, and needing a full regeneration, not a localized patch.** What is stale
is the exact coordinates and counts D4 carries, not the architecture it
describes.

- The *topology* D4 describes is sound. Every one of the 277 recorded
  relationships still exists, and the ADR-0001 chain and composition-root
  uniqueness hold.
- D4's value as evidence lies in its exact coordinates and counts, and those are
  broadly out of date. About one row in three carries a stale line number, and
  the stale rows span 7 modules, including every row in `core/application.py`.
  24 rows are no longer in the runtime closure, 33 current sites and two entry
  points are missing, 7 of its 10 scope figures are wrong, and the test it says
  enforces it has never existed.
- Patching D4 in place is prohibited, and hand-editing ~130 coordinates would
  produce an unreproducible artifact. D4 should therefore be treated from now on
  as a **historical snapshot of db8bdf3**. It is accurate for that commit, as the
  calibration above proves, and must not be cited as evidence of current runtime
  construction.

## Recommended next step (separate, owner-authorized task — not done here)

An owner decision is needed on whether to produce a successor D4 at a current
HEAD. If one is authorized, the generator must this time be committed together
with the regression test D4 promised
(`tests/architecture/test_rem001_construction_paths.py`, or a successor name),
so that any future drift fails loudly. The successor should record the
4-entry-point closure.

## Deferred observations (recorded, not acted on)

- `docs/adr/0001-canonical-composition-root.md:24` cites `main.py:345` for the
  `AtlasApplication` construction. At HEAD that construction is at `main.py:406`.
  This is the same kind of line drift, found in an ADR rather than in D4. It is
  out of scope here and is recorded for a future documentation pass.
- `packaging/REM-001_STATE_AUTHORITY_MAP.md` (D5) was generated from the same
  commit by the same absent tool, so it is likely subject to the same kind of
  drift. It was not checked here because D5 is out of scope.

## Header, scope, chain and gate claims (H1–H35)

| # | D4 line(s) | claim | classification | evidence |
| --- | --- | --- | --- | --- |
| H1 | 3 | D4 is "deliverable 4 of 9" of Gate 1 | CANNOT_VERIFY | REM-001's specification, which defines the deliverable set, is permanently lost (GOV-DRIFT-005). The registry still treats this file as D4 (v4.90 `d4_d5_dangling_stash_recovery_authorization.grant_d4_d5_recovery.target_files`), but the "of 9" count cannot be checked against its source. |
| H2 | 5–6 | Generated by `tools/build_rem001_gate1_maps.py construction`, command `python -m tools.build_rem001_gate1_maps construction --write` | CANNOT_VERIFY | The tool is absent from the working tree and from every git ref (`git log --all` over the path returns nothing), so the provenance cannot be checked directly and the command cannot be run. The *output* is independently reproduced (see Calibration). |
| H3 | 12 | authorization_id `REM-001-GATE1-MECHANICAL` | STILL_ACCURATE | `governance/ATLAS_BASELINE_IDENTITY_AND_GATE1_SCOPE_DECISION_v1.0.md:208` defines `REM-001-GATE1-MECHANICAL`. Registry v4.90 `grant_d4_d5_recovery` re-confirms the ID for this file. |
| H4 | 13 | granted_by_registry v4.32 | STILL_ACCURATE | `governance/current/ATLAS_MILESTONE_REGISTRY_v4.32.json` exists (tracked). |
| H5 | 14 | decision_record path | STILL_ACCURATE | `governance/ATLAS_BASELINE_IDENTITY_AND_GATE1_SCOPE_DECISION_v1.0.md` exists (tracked). |
| H6 | 15 | GOV-DRIFT-005 is "OPEN, not resolved by this artifact" | DRIFTED | Registry v4.90 `governance_findings.GOV-DRIFT-005.status` = `CONFIRMED_AND_RECORDED_BY_VERSIONED_SUCCESSOR_RECORD`. The "not resolved by this artifact" part still holds. |
| H7 | 16 | Not a certification; does not advance `gate_1_state`; no approval | STILL_ACCURATE | Registry v4.90 `REM-001 … gate_1_state` = `OPEN_NOT_CERTIFIED`. |
| H8 | 22 | generated_from_commit db8bdf3… | STILL_ACCURATE | The commit exists. The verifier reproduces all 277 rows from that commit's tree. |
| H9 | 23 | generated_from_tree 6e4b60a9… | STILL_ACCURATE | `git rev-parse db8bdf3^{tree}` = `6e4b60a9cd88d2d65d70717ef3509af092aa5e19`. |
| H10 | 24–25 | tracked working tree clean; no modified paths at generation | CANNOT_VERIFY | The working-tree state at generation time is unrecoverable. The exact reproduction from the committed tree is *consistent* with a clean tree but does not prove it. |
| H11 | 29–38 | Method: static AST call-site resolution by name over the closure | STILL_ACCURATE | An independent implementation of exactly this description reproduces 277/277 rows and every scope figure at db8bdf3. |
| H12 | 40–42 | Own defining module not counted, matching `test_composition_root_is_unique.py` | STILL_ACCURATE | `tests/architecture/test_composition_root_is_unique.py:53-56` skips the class's `defining_file`. |
| H13 | 46–51 | Supersedes `runtime_entrypoint_pattern_matches: 529`, and the old figure is preserved in the registry | STILL_ACCURATE | Registry v4.90 still carries `"runtime_entrypoint_pattern_matches": 529`. |
| H14 | 57 | entry_points = `main.py`, `web_app.py` | DRIFTED | The HEAD closure `entry_points` = `main.py`, `web_app.py`, `atlas_service.py`, `atlas_supervisor.py` (commits `9fadd67` and `2d7ab52`). |
| H15 | 58 | Canonical composition root = `core/application.py` (ADR-0001) | STILL_ACCURATE | `docs/adr/0001-canonical-composition-root.md:13`. `test_composition_root_is_unique.py`: 2 passed. |
| H16 | 59 | modules_in_runtime_closure 105 | DRIFTED | 108 at HEAD (+6 / −3, listed above). |
| H17 | 60 | classes_defined_in_closure 368 | DRIFTED | 384 distinct class names (387 definitions) at HEAD. At db8bdf3 the verifier gives 368 names and 370 definitions, so D4 counts distinct names. |
| H18 | 61 | construction_sites 277 | DRIFTED | 286 at HEAD. |
| H19 | 62 | modules_constructing 33 | STILL_ACCURATE | 33 at HEAD. The value is unchanged but the membership changed: `data_layer/config.py` and `data_layer/sqlite.py` left, and `atlas_service.py` and `data_layer/evidence_store.py` joined. |
| H20 | 63 | classes_constructed 117 | DRIFTED | 121 at HEAD. |
| H21 | 64 | construction_edges 86 | DRIFTED | 91 at HEAD. |
| H22 | 65 | ambiguous_class_names 2 | DRIFTED | 3 at HEAD. |
| H23 | 66 | parse_failures 0 | STILL_ACCURATE | 0 at HEAD (with BOM-tolerant decoding). |
| H24 | 74–76 | Ambiguous names are `AtlasBrain` and `Decision` | DRIFTED | Both are still ambiguous with the same two definitions each. They are joined by `_TransportError`, defined in both `atlas_finance/market_data/fear_greed_provider.py` and `atlas_finance/market_data/treasury_yield_provider.py`. |
| H25 | 79–81 | ADR-0001 chain `main.py` → `core/application.py` (`AtlasApplication`) → `core/runtime.py` (`AtlasRuntime`) | STILL_ACCURATE | ADR-0001:13 states the chain. `main.py:406` and `core/application.py:547` implement it. An outer `atlas_service.py` layer now exists (H14), and it constructs `AtlasProcess`, not a chain class. |
| H26 | 85 | `AtlasApplication` constructed by `main.py` | STILL_ACCURATE | `main.py:406`. No other HEAD closure module constructs it. |
| H27 | 86 | `AtlasBrain` constructed by `core/application.py` | STILL_ACCURATE | `core/application.py:604`. |
| H28 | 87 | `MarketLoop` constructed by `core/application.py` | STILL_ACCURATE | `core/application.py:683`. |
| H29 | 88 | `ExecutionManager` constructed by `core/application.py` | STILL_ACCURATE | `core/application.py:648`. |
| H30 | 374–388 | This artifact omits `source_scope`, `current_responsibility`, `intended_responsibility`, `domain`, `owner`, `lifecycle`, `criticality`, `state_ownership` | STILL_ACCURATE | By inspection, these names appear only in this exclusion list (D4 lines 379–386). No table in D4 carries any of them as a column or a value. |
| H31 | 374–377 | ARCH-001.2.1 reserves these fields for human architecture review | CANNOT_VERIFY | `ARCH-001.2.1_MODULE_INVENTORY_SCHEMA.json/.md` is not tracked (`git ls-files` finds no match). Its reservation is known only as quoted in `governance/ATLAS_BASELINE_IDENTITY_AND_GATE1_SCOPE_DECISION_v1.0.md:239-249`, which names five values. D4 omits a superset of them. |
| H32 | 392–393 | Gates enforced by `tests/architecture/test_rem001_construction_paths.py` | DRIFTED | The file is absent at HEAD and has never been committed on any ref (`git log --all` over the path is empty). |
| H33 | 397 | Gate 1 reference `test_composition_root_is_unique.py` | STILL_ACCURATE | The file exists and gave 2 passed this session. |
| H34 | 398 | Every constructing module lies inside `packaging/atlas_runtime_closure.json` | DRIFTED | The reference file exists, but 24 of D4's own rows (`data_layer/config.py`, `data_layer/sqlite.py`) now fall outside it. |
| H35 | 399 | Regeneration is byte-identical | CANNOT_VERIFY | The generator is absent. Even if it were present, a rerun at HEAD could not match D4 given H16–H22. |

## Sites at HEAD not in D4 (33; omissions, not D4 claims)

| constructing module | class | defining module | HEAD line | enclosing scope |
| --- | --- | --- | --- | --- |
| `ai/core/atlas_brain.py` | `ClaimSource` | `data_layer/contracts.py` | 1299 | `AtlasBrain::_record_one_agent_claim` |
| `atlas_service.py` | `AtlasProcess` | `main.py` | 398 | `build_process` |
| `core/application.py` | `EvidenceStore` | `data_layer/evidence_store.py` | 600 | `AtlasApplication::_build_services` |
| `core/application.py` | `FearGreedProvider` | `atlas_finance/market_data/fear_greed_provider.py` | 672 | `AtlasApplication::_build_services` |
| `core/application.py` | `MarketRiskRegimeProvider` | `core/market_risk_regime.py` | 681 | `AtlasApplication::_build_services` |
| `core/application.py` | `TreasuryYieldProvider` | `atlas_finance/market_data/treasury_yield_provider.py` | 680 | `AtlasApplication::_build_services` |
| `core/execution_manager.py` | `RestoredRiskState` | `core/risk_state_store.py` | 3955 | `ExecutionManager::_record_realized_risk_accounting` |
| `data_layer/evidence_store.py` | `ClaimSource` | `data_layer/contracts.py` | 877 | `EvidenceStore::sources_for` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 722 | `EvidenceStore::link` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 769 | `EvidenceStore::link` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 575 | `EvidenceStore::record_claim` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 577 | `EvidenceStore::record_claim` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 581 | `EvidenceStore::record_claim` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 583 | `EvidenceStore::record_claim` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 602 | `EvidenceStore::record_claim` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 678 | `EvidenceStore::record_claim` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 817 | `EvidenceStore::set_status` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 307 | `_canonical_json` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 265 | `_confidence_text` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 267 | `_confidence_text` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 271 | `_confidence_text` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 273 | `_confidence_text` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 275 | `_confidence_text` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 324 | `_enum_value` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 316 | `_required_text` |
| `data_layer/evidence_store.py` | `IntegrityViolation` | `data_layer/contracts.py` | 287 | `_utc_text` |
| `data_layer/evidence_store.py` | `Migration` | `data_layer/migrations.py` | 229 | `<module>` |
| `data_layer/evidence_store.py` | `StorageError` | `data_layer/contracts.py` | 521 | `EvidenceStore::_connect` |
| `data_layer/evidence_store.py` | `StorageError` | `data_layer/contracts.py` | 778 | `EvidenceStore::link` |
| `data_layer/evidence_store.py` | `StorageError` | `data_layer/contracts.py` | 471 | `EvidenceStore::open` |
| `data_layer/evidence_store.py` | `StorageError` | `data_layer/contracts.py` | 500 | `EvidenceStore::open` |
| `data_layer/evidence_store.py` | `StorageError` | `data_layer/contracts.py` | 691 | `EvidenceStore::record_claim` |
| `data_layer/evidence_store.py` | `StorageError` | `data_layer/contracts.py` | 843 | `EvidenceStore::set_status` |

## Construction-site rows (R1–R277)

The "D4 line" column is the line of the row in D4, and "D4 line no." is the source line D4 cites. The "HEAD line" column is the matched line at `3159500`.

| # | D4 line | constructing module | class | D4 line no. | enclosing scope | HEAD line | classification | drift detail |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | 94 | `ai/core/atlas_brain.py` | `Action` | 810 | `AtlasBrain::_build_phase5_agent_evidence` | 878 | DRIFTED | line 810 → 878; module, class, defining module and scope unchanged |
| R2 | 95 | `ai/core/atlas_brain.py` | `AdvisoryRiskScorer` | 210 | `AtlasBrain::initialize_modules` | 255 | DRIFTED | line 210 → 255; module, class, defining module and scope unchanged |
| R3 | 96 | `ai/core/atlas_brain.py` | `AgentFusion` | 198 | `AtlasBrain::initialize_modules` | 243 | DRIFTED | line 198 → 243; module, class, defining module and scope unchanged |
| R4 | 97 | `ai/core/atlas_brain.py` | `AtlasMemoryCore` | 186 | `AtlasBrain::initialize_modules` | 231 | DRIFTED | line 186 → 231; module, class, defining module and scope unchanged |
| R5 | 98 | `ai/core/atlas_brain.py` | `AtlasReasoningEngine` | 190 | `AtlasBrain::initialize_modules` | 235 | DRIFTED | line 190 → 235; module, class, defining module and scope unchanged |
| R6 | 99 | `ai/core/atlas_brain.py` | `AtlasWorldModel` | 194 | `AtlasBrain::initialize_modules` | 239 | DRIFTED | line 194 → 239; module, class, defining module and scope unchanged |
| R7 | 100 | `ai/core/atlas_brain.py` | `ConfidenceEngine` | 208 | `AtlasBrain::initialize_modules` | 253 | DRIFTED | line 208 → 253; module, class, defining module and scope unchanged |
| R8 | 101 | `ai/core/atlas_brain.py` | `DecisionBuilder` | 212 | `AtlasBrain::initialize_modules` | 257 | DRIFTED | line 212 → 257; module, class, defining module and scope unchanged |
| R9 | 102 | `ai/core/atlas_brain.py` | `Evidence` | 857 | `AtlasBrain::_build_phase5_agent_evidence` | 925 | DRIFTED | line 857 → 925; module, class, defining module and scope unchanged |
| R10 | 103 | `ai/core/atlas_brain.py` | `FusionPolicy` | 714 | `AtlasBrain::_build_phase5_shadow_proposal` | 782 | DRIFTED | line 714 → 782; module, class, defining module and scope unchanged |
| R11 | 104 | `ai/core/atlas_brain.py` | `MemoryAdapter` | 204 | `AtlasBrain::initialize_modules` | 249 | DRIFTED | line 204 → 249; module, class, defining module and scope unchanged |
| R12 | 105 | `ai/core/atlas_brain.py` | `ReasoningAdapter` | 200 | `AtlasBrain::initialize_modules` | 245 | DRIFTED | line 200 → 245; module, class, defining module and scope unchanged |
| R13 | 106 | `ai/core/atlas_brain.py` | `SignalFusion` | 721 | `AtlasBrain::_build_phase5_shadow_proposal` | 789 | DRIFTED | line 721 → 789; module, class, defining module and scope unchanged |
| R14 | 107 | `ai/core/intelligence/decision_builder.py` | `Decision` | 84 | `DecisionBuilder::create` | 84 | STILL_ACCURATE | — |
| R15 | 108 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleError` | 569 | `BinancePublicDataProvider::get_candles` | 569 | STILL_ACCURATE | — |
| R16 | 109 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleError` | 893 | `BinancePublicDataProvider::_parse_candle` | 893 | STILL_ACCURATE | — |
| R17 | 110 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleError` | 902 | `BinancePublicDataProvider::_parse_candle` | 902 | STILL_ACCURATE | — |
| R18 | 111 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleError` | 911 | `BinancePublicDataProvider::_parse_candle` | 911 | STILL_ACCURATE | — |
| R19 | 112 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleError` | 917 | `BinancePublicDataProvider::_parse_candle` | 917 | STILL_ACCURATE | — |
| R20 | 113 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleError` | 1361 | `BinancePublicDataProvider::_milliseconds_to_datetime` | 1361 | STILL_ACCURATE | — |
| R21 | 114 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleError` | 1367 | `BinancePublicDataProvider::_milliseconds_to_datetime` | 1367 | STILL_ACCURATE | — |
| R22 | 115 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleError` | 1382 | `BinancePublicDataProvider::_milliseconds_to_datetime` | 1382 | STILL_ACCURATE | — |
| R23 | 116 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleLimitError` | 1083 | `BinancePublicDataProvider::_validate_candle_limit` | 1083 | STILL_ACCURATE | — |
| R24 | 117 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidCandleLimitError` | 1093 | `BinancePublicDataProvider::_validate_candle_limit` | 1093 | STILL_ACCURATE | — |
| R25 | 118 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidSymbolError` | 1006 | `BinancePublicDataProvider::_normalize_symbol` | 1006 | STILL_ACCURATE | — |
| R26 | 119 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidSymbolError` | 1028 | `BinancePublicDataProvider::_normalize_symbol` | 1028 | STILL_ACCURATE | — |
| R27 | 120 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidSymbolError` | 1035 | `BinancePublicDataProvider::_normalize_symbol` | 1035 | STILL_ACCURATE | — |
| R28 | 121 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidTimeframeError` | 1051 | `BinancePublicDataProvider::_normalize_timeframe` | 1051 | STILL_ACCURATE | — |
| R29 | 122 | `atlas_finance/market_data/binance_public_provider.py` | `InvalidTimeframeError` | 1061 | `BinancePublicDataProvider::_normalize_timeframe` | 1061 | STILL_ACCURATE | — |
| R30 | 123 | `atlas_finance/market_data/binance_public_provider.py` | `MarketCandle` | 927 | `BinancePublicDataProvider::_parse_candle` | 927 | STILL_ACCURATE | — |
| R31 | 124 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1109 | `BinancePublicDataProvider::_validate_base_url` | 1109 | STILL_ACCURATE | — |
| R32 | 125 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1123 | `BinancePublicDataProvider::_validate_base_url` | 1123 | STILL_ACCURATE | — |
| R33 | 126 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1144 | `BinancePublicDataProvider::_validate_retry_attempts` | 1144 | STILL_ACCURATE | — |
| R34 | 127 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1149 | `BinancePublicDataProvider::_validate_retry_attempts` | 1149 | STILL_ACCURATE | — |
| R35 | 128 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1170 | `BinancePublicDataProvider::_validate_maximum_candle_limit` | 1170 | STILL_ACCURATE | — |
| R36 | 129 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1176 | `BinancePublicDataProvider::_validate_maximum_candle_limit` | 1176 | STILL_ACCURATE | — |
| R37 | 130 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1198 | `BinancePublicDataProvider::_validate_positive_float` | 1198 | STILL_ACCURATE | — |
| R38 | 131 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1208 | `BinancePublicDataProvider::_validate_positive_float` | 1208 | STILL_ACCURATE | — |
| R39 | 132 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1230 | `BinancePublicDataProvider::_validate_non_negative_float` | 1230 | STILL_ACCURATE | — |
| R40 | 133 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConfigurationError` | 1240 | `BinancePublicDataProvider::_validate_non_negative_float` | 1240 | STILL_ACCURATE | — |
| R41 | 134 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConnectionError` | 323 | `BinancePublicDataProvider::connect` | 323 | STILL_ACCURATE | — |
| R42 | 135 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConnectionError` | 345 | `BinancePublicDataProvider::connect` | 345 | STILL_ACCURATE | — |
| R43 | 136 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConnectionError` | 719 | `BinancePublicDataProvider::_perform_get` | 719 | STILL_ACCURATE | — |
| R44 | 137 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataConnectionError` | 992 | `BinancePublicDataProvider::_ensure_available` | 992 | STILL_ACCURATE | — |
| R45 | 138 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataRateLimitError` | 754 | `BinancePublicDataProvider::_validate_response` | 754 | STILL_ACCURATE | — |
| R46 | 139 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataRequestError` | 528 | `BinancePublicDataProvider::get_candles` | 528 | STILL_ACCURATE | — |
| R47 | 140 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataRequestError` | 677 | `BinancePublicDataProvider::_request_json` | 677 | STILL_ACCURATE | — |
| R48 | 141 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataRequestError` | 725 | `BinancePublicDataProvider::_perform_get` | 725 | STILL_ACCURATE | — |
| R49 | 142 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataRequestError` | 761 | `BinancePublicDataProvider::_validate_response` | 761 | STILL_ACCURATE | — |
| R50 | 143 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataRequestError` | 778 | `BinancePublicDataProvider::_validate_response` | 778 | STILL_ACCURATE | — |
| R51 | 144 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataRequestError` | 1323 | `BinancePublicDataProvider::_datetime_to_milliseconds` | 1323 | STILL_ACCURATE | — |
| R52 | 145 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataRequestError` | 1328 | `BinancePublicDataProvider::_datetime_to_milliseconds` | 1328 | STILL_ACCURATE | — |
| R53 | 146 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataRequestError` | 1339 | `BinancePublicDataProvider::_datetime_to_milliseconds` | 1339 | STILL_ACCURATE | — |
| R54 | 147 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataResponseError` | 410 | `BinancePublicDataProvider::get_price` | 410 | STILL_ACCURATE | — |
| R55 | 148 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataResponseError` | 430 | `BinancePublicDataProvider::get_price` | 430 | STILL_ACCURATE | — |
| R56 | 149 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataResponseError` | 541 | `BinancePublicDataProvider::get_candles` | 541 | STILL_ACCURATE | — |
| R57 | 150 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataResponseError` | 626 | `BinancePublicDataProvider::_request_json` | 626 | STILL_ACCURATE | — |
| R58 | 151 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataResponseError` | 813 | `BinancePublicDataProvider::_parse_candle` | 813 | STILL_ACCURATE | — |
| R59 | 152 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataResponseError` | 820 | `BinancePublicDataProvider::_parse_candle` | 820 | STILL_ACCURATE | — |
| R60 | 153 | `atlas_finance/market_data/binance_public_provider.py` | `MarketDataTimeoutError` | 712 | `BinancePublicDataProvider::_perform_get` | 712 | STILL_ACCURATE | — |
| R61 | 154 | `atlas_finance/market_data/binance_public_provider.py` | `MarketPrice` | 446 | `BinancePublicDataProvider::get_price` | 446 | STILL_ACCURATE | — |
| R62 | 155 | `atlas_finance/market_data/market_feed_service.py` | `InvalidCandleLimitError` | 1795 | `MarketFeedService::_validate_limit` | 1795 | STILL_ACCURATE | — |
| R63 | 156 | `atlas_finance/market_data/market_feed_service.py` | `InvalidCandleLimitError` | 1808 | `MarketFeedService::_validate_limit` | 1808 | STILL_ACCURATE | — |
| R64 | 157 | `atlas_finance/market_data/market_feed_service.py` | `InvalidSymbolError` | 1714 | `MarketFeedService::_normalize_symbol` | 1714 | STILL_ACCURATE | — |
| R65 | 158 | `atlas_finance/market_data/market_feed_service.py` | `InvalidSymbolError` | 1736 | `MarketFeedService::_normalize_symbol` | 1736 | STILL_ACCURATE | — |
| R66 | 159 | `atlas_finance/market_data/market_feed_service.py` | `InvalidTimeframeError` | 1750 | `MarketFeedService::_normalize_timeframe` | 1750 | STILL_ACCURATE | — |
| R67 | 160 | `atlas_finance/market_data/market_feed_service.py` | `InvalidTimeframeError` | 1757 | `MarketFeedService::_normalize_timeframe` | 1757 | STILL_ACCURATE | — |
| R68 | 161 | `atlas_finance/market_data/market_feed_service.py` | `InvalidTimeframeError` | 1773 | `MarketFeedService::_normalize_timeframe` | 1773 | STILL_ACCURATE | — |
| R69 | 162 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataConfigurationError` | 378 | `MarketFeedService::__init__` | 378 | STILL_ACCURATE | — |
| R70 | 163 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataConfigurationError` | 1693 | `MarketFeedService::_validate_failure_threshold` | 1693 | STILL_ACCURATE | — |
| R71 | 164 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataConfigurationError` | 1699 | `MarketFeedService::_validate_failure_threshold` | 1699 | STILL_ACCURATE | — |
| R72 | 165 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataError` | 1825 | `MarketFeedService::_validate_price_result` | 1825 | STILL_ACCURATE | — |
| R73 | 166 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataError` | 1831 | `MarketFeedService::_validate_price_result` | 1831 | STILL_ACCURATE | — |
| R74 | 167 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataError` | 1842 | `MarketFeedService::_validate_price_result` | 1842 | STILL_ACCURATE | — |
| R75 | 168 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataError` | 1857 | `MarketFeedService::_validate_candle_results` | 1857 | STILL_ACCURATE | — |
| R76 | 169 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataError` | 1873 | `MarketFeedService::_validate_candle_results` | 1873 | STILL_ACCURATE | — |
| R77 | 170 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataError` | 1882 | `MarketFeedService::_validate_candle_results` | 1882 | STILL_ACCURATE | — |
| R78 | 171 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataError` | 1891 | `MarketFeedService::_validate_candle_results` | 1891 | STILL_ACCURATE | — |
| R79 | 172 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataError` | 1901 | `MarketFeedService::_validate_candle_results` | 1901 | STILL_ACCURATE | — |
| R80 | 173 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataProviderUnavailableError` | 510 | `MarketFeedService::_on_start` | 510 | STILL_ACCURATE | — |
| R81 | 174 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataRequestStatistics` | 265 | `_MutableRequestStatistics::snapshot` | 265 | STILL_ACCURATE | — |
| R82 | 175 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataServiceNotRunningError` | 1674 | `MarketFeedService::_require_running` | 1674 | STILL_ACCURATE | — |
| R83 | 176 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataServiceShutdownError` | 625 | `MarketFeedService::_on_stop` | 625 | STILL_ACCURATE | — |
| R84 | 177 | `atlas_finance/market_data/market_feed_service.py` | `MarketDataServiceStartupError` | 572 | `MarketFeedService::_on_start` | 572 | STILL_ACCURATE | — |
| R85 | 178 | `atlas_finance/market_data/market_feed_service.py` | `MarketFeedSnapshot` | 919 | `MarketFeedService::market_feed_snapshot` | 919 | STILL_ACCURATE | — |
| R86 | 179 | `atlas_finance/market_data/market_feed_service.py` | `MarketFeedStatistics` | 842 | `MarketFeedService::statistics` | 842 | STILL_ACCURATE | — |
| R87 | 180 | `atlas_finance/market_data/market_feed_service.py` | `ServiceIdentity` | 366 | `MarketFeedService::__init__` | 366 | STILL_ACCURATE | — |
| R88 | 181 | `atlas_os/audit/audit_log.py` | `ServiceIdentity` | 310 | `AuditLogService::__init__` | 310 | STILL_ACCURATE | — |
| R89 | 182 | `atlas_os/configuration/configuration_service.py` | `ServiceIdentity` | 460 | `ConfigurationService::__init__` | 460 | STILL_ACCURATE | — |
| R90 | 183 | `atlas_os/events/event_bus.py` | `ServiceIdentity` | 310 | `EventBusService::__init__` | 310 | STILL_ACCURATE | — |
| R91 | 184 | `atlas_os/integration/configuration_secrets_bridge.py` | `DuplicateSecretError` | 535 | `ConfigurationSecretsBridge::register_binding` | 535 | STILL_ACCURATE | — |
| R92 | 185 | `atlas_os/integration/configuration_secrets_bridge.py` | `SecretValidationError` | 1001 | `ConfigurationSecretsBridge::validate` | 1001 | STILL_ACCURATE | — |
| R93 | 186 | `atlas_os/integration/configuration_secrets_bridge.py` | `SecretValidationError` | 1357 | `ConfigurationSecretsBridge::_validate_length` | 1357 | STILL_ACCURATE | — |
| R94 | 187 | `atlas_os/integration/configuration_secrets_bridge.py` | `SecretValidationError` | 1365 | `ConfigurationSecretsBridge::_validate_length` | 1365 | STILL_ACCURATE | — |
| R95 | 188 | `atlas_os/integration/configuration_secrets_bridge.py` | `SecretValidationError` | 1378 | `ConfigurationSecretsBridge::_validate_length` | 1378 | STILL_ACCURATE | — |
| R96 | 189 | `atlas_os/integration/configuration_secrets_bridge.py` | `SecretValueMissingError` | 783 | `ConfigurationSecretsBridge::_load_from_environment` | 783 | STILL_ACCURATE | — |
| R97 | 190 | `atlas_os/integration/configuration_secrets_bridge.py` | `SecretValueMissingError` | 833 | `ConfigurationSecretsBridge::_load_from_configuration_reference` | 833 | STILL_ACCURATE | — |
| R98 | 191 | `atlas_os/kernel/kernel.py` | `DependencyServiceManager` | 243 | `AtlasOSKernel::__init__` | 243 | STILL_ACCURATE | — |
| R99 | 192 | `atlas_os/kernel/kernel.py` | `OrchestrationResult` | 512 | `AtlasOSKernel::start` | 512 | STILL_ACCURATE | — |
| R100 | 193 | `atlas_os/kernel/kernel.py` | `OrchestrationResult` | 626 | `AtlasOSKernel::stop` | 626 | STILL_ACCURATE | — |
| R101 | 194 | `atlas_os/kernel/kernel.py` | `OrchestrationResult` | 641 | `AtlasOSKernel::stop` | 641 | STILL_ACCURATE | — |
| R102 | 195 | `atlas_os/observability/health_monitor.py` | `ServiceIdentity` | 198 | `HealthMonitorService::__init__` | 198 | STILL_ACCURATE | — |
| R103 | 196 | `atlas_os/observability/metrics.py` | `ServiceIdentity` | 394 | `MetricsService::__init__` | 394 | STILL_ACCURATE | — |
| R104 | 197 | `atlas_os/scheduling/scheduler.py` | `ServiceIdentity` | 517 | `SchedulerService::__init__` | 517 | STILL_ACCURATE | — |
| R105 | 198 | `atlas_os/secrets/secrets_manager.py` | `ServiceIdentity` | 438 | `SecretsManager::__init__` | 438 | STILL_ACCURATE | — |
| R106 | 199 | `atlas_os/services/base_service.py` | `HealthReport` | 339 | `BaseAtlasService::health` | 339 | STILL_ACCURATE | — |
| R107 | 200 | `atlas_os/services/base_service.py` | `ServiceSnapshot` | 358 | `BaseAtlasService::snapshot` | 358 | STILL_ACCURATE | — |
| R108 | 201 | `atlas_os/services/dependency_manager.py` | `DuplicateServiceError` | 300 | `DependencyServiceManager::register` | 300 | STILL_ACCURATE | — |
| R109 | 202 | `atlas_os/services/dependency_manager.py` | `ServiceNotFoundError` | 1225 | `DependencyServiceManager::_require_registered_key` | 1225 | STILL_ACCURATE | — |
| R110 | 203 | `atlas_os/services/dependency_manager.py` | `ServiceRegistry` | 217 | `DependencyServiceManager::__init__` | 217 | STILL_ACCURATE | — |
| R111 | 204 | `core/application.py` | `AppliedExecutionArchiveStore` | 465 | `AtlasApplication::_build_financial_services` | 806 | DRIFTED | line 465 → 806; module, class, defining module and scope unchanged |
| R112 | 205 | `core/application.py` | `AtlasBrain` | 281 | `AtlasApplication::_build_services` | 604 | DRIFTED | line 281 → 604; module, class, defining module and scope unchanged |
| R113 | 206 | `core/application.py` | `AtlasController` | 359 | `AtlasApplication::_build_services` | 700 | DRIFTED | line 359 → 700; module, class, defining module and scope unchanged |
| R114 | 207 | `core/application.py` | `AtlasLogger` | 240 | `AtlasApplication::_build_infrastructure` | 543 | DRIFTED | line 240 → 543; module, class, defining module and scope unchanged |
| R115 | 208 | `core/application.py` | `AtlasRuntime` | 241 | `AtlasApplication::_build_infrastructure` | 547 | DRIFTED | line 241 → 547; module, class, defining module and scope unchanged |
| R116 | 209 | `core/application.py` | `AuditEventStore` | 509 | `AtlasApplication::_build_execution_durability` | 850 | DRIFTED | line 509 → 850; module, class, defining module and scope unchanged |
| R117 | 210 | `core/application.py` | `CapabilityGateway` | 400 | `AtlasApplication::_build_capability_gateway` | 741 | DRIFTED | line 400 → 741; module, class, defining module and scope unchanged |
| R118 | 211 | `core/application.py` | `CapitalManager` | 260 | `AtlasApplication::_build_services` | 566 | DRIFTED | line 260 → 566; module, class, defining module and scope unchanged |
| R119 | 212 | `core/application.py` | `CapitalReservationLedger` | 451 | `AtlasApplication::_build_financial_services` | 792 | DRIFTED | line 451 → 792; module, class, defining module and scope unchanged |
| R120 | 213 | `core/application.py` | `ClosedPositionArchiveStore` | 468 | `AtlasApplication::_build_financial_services` | 809 | DRIFTED | line 468 → 809; module, class, defining module and scope unchanged |
| R121 | 214 | `core/application.py` | `EventBus` | 242 | `AtlasApplication::_build_infrastructure` | 548 | DRIFTED | line 242 → 548; module, class, defining module and scope unchanged |
| R122 | 215 | `core/application.py` | `ExecutionIdempotencyStore` | 501 | `AtlasApplication::_build_execution_durability` | 842 | DRIFTED | line 501 → 842; module, class, defining module and scope unchanged |
| R123 | 216 | `core/application.py` | `ExecutionManager` | 323 | `AtlasApplication::_build_services` | 648 | DRIFTED | line 323 → 648; module, class, defining module and scope unchanged |
| R124 | 217 | `core/application.py` | `ExecutionPortfolioFoundation` | 461 | `AtlasApplication::_build_financial_services` | 802 | DRIFTED | line 461 → 802; module, class, defining module and scope unchanged |
| R125 | 218 | `core/application.py` | `ExecutionTransactionJournal` | 505 | `AtlasApplication::_build_execution_durability` | 846 | DRIFTED | line 505 → 846; module, class, defining module and scope unchanged |
| R126 | 219 | `core/application.py` | `FinancialStateStore` | 462 | `AtlasApplication::_build_financial_services` | 803 | DRIFTED | line 462 → 803; module, class, defining module and scope unchanged |
| R127 | 220 | `core/application.py` | `JsonReservationStore` | 452 | `AtlasApplication::_build_financial_services` | 793 | DRIFTED | line 452 → 793; module, class, defining module and scope unchanged |
| R128 | 221 | `core/application.py` | `JsonRiskStateStore` | 447 | `AtlasApplication::_build_financial_services` | 788 | DRIFTED | line 447 → 788; module, class, defining module and scope unchanged |
| R129 | 222 | `core/application.py` | `LifecycleManager` | 244 | `AtlasApplication::_build_infrastructure` | 550 | DRIFTED | line 244 → 550; module, class, defining module and scope unchanged |
| R130 | 223 | `core/application.py` | `LocalCapabilityProbeAdapter` | 404 | `AtlasApplication::_build_capability_gateway` | 745 | DRIFTED | line 404 → 745; module, class, defining module and scope unchanged |
| R131 | 224 | `core/application.py` | `MarketFeed` | 289 | `AtlasApplication::_build_services` | 614 | DRIFTED | line 289 → 614; module, class, defining module and scope unchanged |
| R132 | 225 | `core/application.py` | `MarketLoop` | 345 | `AtlasApplication::_build_services` | 683 | DRIFTED | line 345 → 683; module, class, defining module and scope unchanged |
| R133 | 226 | `core/application.py` | `PaperTrader` | 267 | `AtlasApplication::_build_services` | 574 | DRIFTED | line 267 → 574; module, class, defining module and scope unchanged |
| R134 | 227 | `core/application.py` | `PositionController` | 273 | `AtlasApplication::_build_services` | 580 | DRIFTED | line 273 → 580; module, class, defining module and scope unchanged |
| R135 | 228 | `core/application.py` | `PositionSizingService` | 443 | `AtlasApplication::_build_financial_services` | 784 | DRIFTED | line 443 → 784; module, class, defining module and scope unchanged |
| R136 | 229 | `core/application.py` | `ReservationArchiveStore` | 456 | `AtlasApplication::_build_financial_services` | 797 | DRIFTED | line 456 → 797; module, class, defining module and scope unchanged |
| R137 | 230 | `core/application.py` | `RiskEngine` | 435 | `AtlasApplication::_build_financial_services` | 776 | DRIFTED | line 435 → 776; module, class, defining module and scope unchanged |
| R138 | 231 | `core/application.py` | `RiskPolicy` | 427 | `AtlasApplication::_build_financial_services` | 768 | DRIFTED | line 427 → 768; module, class, defining module and scope unchanged |
| R139 | 232 | `core/application.py` | `Scheduler` | 243 | `AtlasApplication::_build_infrastructure` | 549 | DRIFTED | line 243 → 549; module, class, defining module and scope unchanged |
| R140 | 233 | `core/application.py` | `ServiceContainer` | 245 | `AtlasApplication::_build_infrastructure` | 551 | DRIFTED | line 245 → 551; module, class, defining module and scope unchanged |
| R141 | 234 | `core/application.py` | `UnconfiguredPolicyGate` | 398 | `AtlasApplication::_build_capability_gateway` | 739 | DRIFTED | line 398 → 739; module, class, defining module and scope unchanged |
| R142 | 235 | `core/application.py` | `VenueRuleFreshnessPolicy` | 207 | `AtlasApplication::__init__` | 501 | DRIFTED | line 207 → 501; module, class, defining module and scope unchanged |
| R143 | 236 | `core/application.py` | `VenueRuleFreshnessService` | 547 | `AtlasApplication::_build_instrument_rules` | 909 | DRIFTED | line 547 → 909; module, class, defining module and scope unchanged |
| R144 | 237 | `core/execution_idempotency_store.py` | `DurableAppendLog` | 151 | `ExecutionIdempotencyStore::__init__` | 151 | STILL_ACCURATE | — |
| R145 | 238 | `core/execution_idempotency_store.py` | `DurableAppendLogCorruptError` | 291 | `ExecutionIdempotencyStore::load` | 291 | STILL_ACCURATE | — |
| R146 | 239 | `core/execution_idempotency_store.py` | `DurableAppendLogCorruptError` | 303 | `ExecutionIdempotencyStore::load` | 303 | STILL_ACCURATE | — |
| R147 | 240 | `core/execution_idempotency_store.py` | `DurableAppendLogCorruptError` | 315 | `ExecutionIdempotencyStore::load` | 315 | STILL_ACCURATE | — |
| R148 | 241 | `core/execution_idempotency_store.py` | `DurableAppendLogCorruptError` | 337 | `ExecutionIdempotencyStore::load` | 337 | STILL_ACCURATE | — |
| R149 | 242 | `core/execution_idempotency_store.py` | `DurableAppendLogCorruptError` | 350 | `ExecutionIdempotencyStore::load` | 350 | STILL_ACCURATE | — |
| R150 | 243 | `core/execution_manager.py` | `AuditEventStore` | 387 | `ExecutionManager::__init__` | 394 | DRIFTED | line 387 → 394; module, class, defining module and scope unchanged |
| R151 | 244 | `core/execution_manager.py` | `ExecutionIdempotencyStore` | 344 | `ExecutionManager::__init__` | 351 | DRIFTED | line 344 → 351; module, class, defining module and scope unchanged |
| R152 | 245 | `core/execution_manager.py` | `ExecutionRequest` | 2134 | `ExecutionManager::build_request` | 2536 | DRIFTED | line 2134 → 2536; module, class, defining module and scope unchanged |
| R153 | 246 | `core/execution_manager.py` | `ExecutionResult` | 3462 | `ExecutionManager::paper_execute` | 4285 | DRIFTED | line 3462 → 4285; module, class, defining module and scope unchanged |
| R154 | 247 | `core/execution_manager.py` | `ExecutionResult` | 4856 | `ExecutionManager::_block_live_dispatch` | 5526 | DRIFTED | line 4856 → 5526; module, class, defining module and scope unchanged |
| R155 | 248 | `core/execution_manager.py` | `ExecutionResult` | 4916 | `ExecutionManager::live_execute` | 5586 | DRIFTED | line 4916 → 5586; module, class, defining module and scope unchanged |
| R156 | 249 | `core/execution_manager.py` | `ExecutionResult` | 5007 | `ExecutionManager::live_execute` | 5677 | DRIFTED | line 5007 → 5677; module, class, defining module and scope unchanged |
| R157 | 250 | `core/execution_manager.py` | `ExecutionResult` | 5278 | `ExecutionManager::_failure_result` | 5905 | DRIFTED | line 5278 → 5905; module, class, defining module and scope unchanged |
| R158 | 251 | `core/execution_manager.py` | `ExecutionTransactionJournal` | 363 | `ExecutionManager::__init__` | 370 | DRIFTED | line 363 → 370; module, class, defining module and scope unchanged |
| R159 | 252 | `core/execution_manager.py` | `FinancialRuntimeSafetyService` | 374 | `ExecutionManager::__init__` | 381 | DRIFTED | line 374 → 381; module, class, defining module and scope unchanged |
| R160 | 253 | `core/execution_manager.py` | `FinancialRuntimeSafetyService` | 450 | `ExecutionManager::_assess_financial_readiness` | 457 | DRIFTED | line 450 → 457; module, class, defining module and scope unchanged |
| R161 | 254 | `core/execution_manager.py` | `PositionExposure` | 2424 | `ExecutionManager::_derived_position_exposures` | 2826 | DRIFTED | line 2424 → 2826; module, class, defining module and scope unchanged |
| R162 | 255 | `core/execution_manager.py` | `RiskRequest` | 2766 | `ExecutionManager::risk_check` | 3174 | DRIFTED | line 2766 → 3174; module, class, defining module and scope unchanged |
| R163 | 256 | `core/execution_manager.py` | `RiskState` | 2500 | `ExecutionManager::_derive_risk_state` | 2902 | DRIFTED | line 2500 → 2902; module, class, defining module and scope unchanged |
| R164 | 257 | `core/execution_manager.py` | `VenueRuleFreshnessService` | 278 | `ExecutionManager::__init__` | 280 | DRIFTED | line 278 → 280; module, class, defining module and scope unchanged |
| R165 | 258 | `core/execution_transaction_journal.py` | `DurableAppendLog` | 174 | `ExecutionTransactionJournal::__init__` | 174 | STILL_ACCURATE | — |
| R166 | 259 | `core/execution_transaction_journal.py` | `DurableAppendLogCorruptError` | 283 | `ExecutionTransactionJournal::load` | 283 | STILL_ACCURATE | — |
| R167 | 260 | `core/execution_transaction_journal.py` | `DurableAppendLogCorruptError` | 295 | `ExecutionTransactionJournal::load` | 295 | STILL_ACCURATE | — |
| R168 | 261 | `core/execution_transaction_journal.py` | `DurableAppendLogCorruptError` | 307 | `ExecutionTransactionJournal::load` | 308 | DRIFTED | line 307 → 308; module, class, defining module and scope unchanged |
| R169 | 262 | `core/execution_transaction_journal.py` | `DurableAppendLogCorruptError` | 328 | `ExecutionTransactionJournal::load` | 329 | DRIFTED | line 328 → 329; module, class, defining module and scope unchanged |
| R170 | 263 | `core/execution_transaction_journal.py` | `DurableAppendLogCorruptError` | 397 | `ExecutionTransactionJournal::_require_legal_transition` | 398 | DRIFTED | line 397 → 398; module, class, defining module and scope unchanged |
| R171 | 264 | `core/execution_transaction_journal.py` | `DurableAppendLogCorruptError` | 414 | `ExecutionTransactionJournal::_require_legal_transition` | 415 | DRIFTED | line 414 → 415; module, class, defining module and scope unchanged |
| R172 | 265 | `core/local_capability_adapter.py` | `CostMetadata` | 147 | `LocalCapabilityProbeAdapter::free_cost` | 147 | STILL_ACCURATE | — |
| R173 | 266 | `core/local_capability_adapter.py` | `PolicyDecision` | 82 | `UnconfiguredPolicyGate::evaluate` | 82 | STILL_ACCURATE | — |
| R174 | 267 | `core/local_capability_adapter.py` | `ToolDescriptor` | 128 | `LocalCapabilityProbeAdapter` | 128 | STILL_ACCURATE | — |
| R175 | 268 | `core/local_capability_adapter.py` | `ToolInvocationResult` | 156 | `LocalCapabilityProbeAdapter::invoke` | 156 | STILL_ACCURATE | — |
| R176 | 269 | `core/local_capability_adapter.py` | `ToolInvocationResult` | 175 | `LocalCapabilityProbeAdapter::invoke` | 175 | STILL_ACCURATE | — |
| R177 | 270 | `core/market_loop.py` | `CandleProcessor` | 137 | `MarketLoop::__init__` | 222 | DRIFTED | line 137 → 222; module, class, defining module and scope unchanged |
| R178 | 271 | `core/market_loop.py` | `DecisionAdapter` | 140 | `MarketLoop::__init__` | 225 | DRIFTED | line 140 → 225; module, class, defining module and scope unchanged |
| R179 | 272 | `core/market_loop.py` | `SizingInputs` | 1429 | `MarketLoop::_apply_position_sizing` | 1742 | DRIFTED | line 1429 → 1742; module, class, defining module and scope unchanged |
| R180 | 273 | `core/market_loop.py` | `TechnicalAnalyzer` | 138 | `MarketLoop::__init__` | 223 | DRIFTED | line 138 → 223; module, class, defining module and scope unchanged |
| R181 | 274 | `core/market_loop.py` | `WorldAnalysisEngine` | 139 | `MarketLoop::__init__` | 224 | DRIFTED | line 139 → 224; module, class, defining module and scope unchanged |
| R182 | 275 | `core/model_provider_contracts.py` | `OperationResult` | 479 | `ModelInvocationResult::to_operation_result` | 483 | DRIFTED | line 479 → 483; module, class, defining module and scope unchanged |
| R183 | 276 | `core/position_sizing.py` | `RiskBucket` | 162 | `PositionSizingService::propose` | 162 | STILL_ACCURATE | — |
| R184 | 277 | `core/tool_gateway_contracts.py` | `CapabilityClass` | 120 | `ToolDescriptor::__post_init__` | 120 | STILL_ACCURATE | — |
| R185 | 278 | `core/tool_gateway_contracts.py` | `InvocationOutcome` | 222 | `ToolInvocationResult::__post_init__` | 222 | STILL_ACCURATE | — |
| R186 | 279 | `core/tool_gateway_contracts.py` | `ModelInvocationResult` | 460 | `CapabilityGateway::invoke_model::denied` | 460 | STILL_ACCURATE | — |
| R187 | 280 | `core/tool_gateway_contracts.py` | `ModelInvocationResult` | 496 | `CapabilityGateway::invoke_model` | 496 | STILL_ACCURATE | — |
| R188 | 281 | `core/tool_gateway_contracts.py` | `ModelInvocationResult` | 511 | `CapabilityGateway::invoke_model` | 511 | STILL_ACCURATE | — |
| R189 | 282 | `data_layer/canonical_evidence.py` | `ConfirmedExecutionEvidence` | 85 | `CanonicalExecutionEvidenceAdapter::__call__` | 85 | STILL_ACCURATE | — |
| R190 | 283 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 23 | `_required_text` | 23 | STILL_ACCURATE | — |
| R191 | 284 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 31 | `_decimal` | 31 | STILL_ACCURATE | — |
| R192 | 285 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 33 | `_decimal` | 33 | STILL_ACCURATE | — |
| R193 | 286 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 40 | `_same` | 40 | STILL_ACCURATE | — |
| R194 | 287 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 42 | `_same` | 42 | STILL_ACCURATE | — |
| R195 | 288 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 57 | `CanonicalExecutionEvidenceAdapter::__call__` | 57 | STILL_ACCURATE | — |
| R196 | 289 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 62 | `CanonicalExecutionEvidenceAdapter::__call__` | 62 | STILL_ACCURATE | — |
| R197 | 290 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 65 | `CanonicalExecutionEvidenceAdapter::__call__` | 65 | STILL_ACCURATE | — |
| R198 | 291 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 71 | `CanonicalExecutionEvidenceAdapter::__call__` | 71 | STILL_ACCURATE | — |
| R199 | 292 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 74 | `CanonicalExecutionEvidenceAdapter::__call__` | 74 | STILL_ACCURATE | — |
| R200 | 293 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 76 | `CanonicalExecutionEvidenceAdapter::__call__` | 76 | STILL_ACCURATE | — |
| R201 | 294 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 78 | `CanonicalExecutionEvidenceAdapter::__call__` | 78 | STILL_ACCURATE | — |
| R202 | 295 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 80 | `CanonicalExecutionEvidenceAdapter::__call__` | 80 | STILL_ACCURATE | — |
| R203 | 296 | `data_layer/canonical_evidence.py` | `IntegrityViolation` | 84 | `CanonicalExecutionEvidenceAdapter::__call__` | 84 | STILL_ACCURATE | — |
| R204 | 297 | `data_layer/config.py` | `SQLiteStorage` | 74 | `create_storage` | 74 | DRIFTED | call unchanged at line 74, but `data_layer/config.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R205 | 298 | `data_layer/config.py` | `StorageConfigurationError` | 62 | `load_storage_configuration` | 62 | DRIFTED | call unchanged at line 62, but `data_layer/config.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R206 | 299 | `data_layer/config.py` | `StorageConfigurationError` | 66 | `load_storage_configuration` | 66 | DRIFTED | call unchanged at line 66, but `data_layer/config.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R207 | 300 | `data_layer/config.py` | `StorageConfigurationError` | 68 | `load_storage_configuration` | 68 | DRIFTED | call unchanged at line 68, but `data_layer/config.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R208 | 301 | `data_layer/config.py` | `StorageConfigurationError` | 76 | `create_storage` | 76 | DRIFTED | call unchanged at line 76, but `data_layer/config.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R209 | 302 | `data_layer/config.py` | `StorageConfigurationError` | 79 | `create_storage` | 79 | DRIFTED | call unchanged at line 79, but `data_layer/config.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R210 | 303 | `data_layer/migrations.py` | `MigrationError` | 90 | `validate_migrations` | 90 | STILL_ACCURATE | — |
| R211 | 304 | `data_layer/migrations.py` | `MigrationError` | 92 | `validate_migrations` | 92 | STILL_ACCURATE | — |
| R212 | 305 | `data_layer/migrations.py` | `MigrationError` | 94 | `validate_migrations` | 94 | STILL_ACCURATE | — |
| R213 | 306 | `data_layer/migrations.py` | `MigrationError` | 122 | `apply_migrations` | 122 | STILL_ACCURATE | — |
| R214 | 307 | `data_layer/migrations.py` | `MigrationError` | 128 | `apply_migrations` | 128 | STILL_ACCURATE | — |
| R215 | 308 | `data_layer/migrations.py` | `MigrationError` | 133 | `apply_migrations` | 133 | STILL_ACCURATE | — |
| R216 | 309 | `data_layer/models.py` | `IntegrityViolation` | 24 | `validate_id` | 24 | STILL_ACCURATE | — |
| R217 | 310 | `data_layer/models.py` | `IntegrityViolation` | 31 | `normalize_symbol` | 31 | STILL_ACCURATE | — |
| R218 | 311 | `data_layer/models.py` | `IntegrityViolation` | 39 | `decimal_text` | 39 | STILL_ACCURATE | — |
| R219 | 312 | `data_layer/models.py` | `IntegrityViolation` | 41 | `decimal_text` | 41 | STILL_ACCURATE | — |
| R220 | 313 | `data_layer/models.py` | `IntegrityViolation` | 43 | `decimal_text` | 43 | STILL_ACCURATE | — |
| R221 | 314 | `data_layer/models.py` | `IntegrityViolation` | 45 | `decimal_text` | 45 | STILL_ACCURATE | — |
| R222 | 315 | `data_layer/models.py` | `IntegrityViolation` | 48 | `decimal_text` | 48 | STILL_ACCURATE | — |
| R223 | 316 | `data_layer/models.py` | `IntegrityViolation` | 58 | `utc_text` | 58 | STILL_ACCURATE | — |
| R224 | 317 | `data_layer/models.py` | `IntegrityViolation` | 60 | `utc_text` | 60 | STILL_ACCURATE | — |
| R225 | 318 | `data_layer/models.py` | `IntegrityViolation` | 66 | `metadata_text` | 66 | STILL_ACCURATE | — |
| R226 | 319 | `data_layer/models.py` | `IntegrityViolation` | 71 | `metadata_text` | 71 | STILL_ACCURATE | — |
| R227 | 320 | `data_layer/models.py` | `IntegrityViolation` | 73 | `metadata_text` | 73 | STILL_ACCURATE | — |
| R228 | 321 | `data_layer/models.py` | `IntegrityViolation` | 81 | `parse_metadata` | 81 | STILL_ACCURATE | — |
| R229 | 322 | `data_layer/models.py` | `IntegrityViolation` | 83 | `parse_metadata` | 83 | STILL_ACCURATE | — |
| R230 | 323 | `data_layer/models.py` | `IntegrityViolation` | 109 | `OrderRecord::validated` | 109 | STILL_ACCURATE | — |
| R231 | 324 | `data_layer/models.py` | `IntegrityViolation` | 124 | `OrderRecord::validated` | 124 | STILL_ACCURATE | — |
| R232 | 325 | `data_layer/models.py` | `IntegrityViolation` | 128 | `OrderRecord::validated` | 128 | STILL_ACCURATE | — |
| R233 | 326 | `data_layer/models.py` | `IntegrityViolation` | 181 | `PositionRecord::validated` | 181 | STILL_ACCURATE | — |
| R234 | 327 | `data_layer/models.py` | `IntegrityViolation` | 183 | `PositionRecord::validated` | 183 | STILL_ACCURATE | — |
| R235 | 328 | `data_layer/models.py` | `IntegrityViolation` | 187 | `PositionRecord::validated` | 187 | STILL_ACCURATE | — |
| R236 | 329 | `data_layer/projection_replay.py` | `ExecutionRecord` | 79 | `replay_confirmed_execution` | 79 | STILL_ACCURATE | — |
| R237 | 330 | `data_layer/projection_replay.py` | `IntegrityViolation` | 47 | `_position_projection` | 47 | STILL_ACCURATE | — |
| R238 | 331 | `data_layer/projection_replay.py` | `IntegrityViolation` | 53 | `_position_projection` | 53 | STILL_ACCURATE | — |
| R239 | 332 | `data_layer/projection_replay.py` | `IntegrityViolation` | 56 | `_position_projection` | 56 | STILL_ACCURATE | — |
| R240 | 333 | `data_layer/projection_replay.py` | `IntegrityViolation` | 58 | `_position_projection` | 58 | STILL_ACCURATE | — |
| R241 | 334 | `data_layer/projection_replay.py` | `IntegrityViolation` | 68 | `replay_confirmed_execution` | 68 | STILL_ACCURATE | — |
| R242 | 335 | `data_layer/projection_replay.py` | `IntegrityViolation` | 70 | `replay_confirmed_execution` | 70 | STILL_ACCURATE | — |
| R243 | 336 | `data_layer/projection_replay.py` | `IntegrityViolation` | 72 | `replay_confirmed_execution` | 72 | STILL_ACCURATE | — |
| R244 | 337 | `data_layer/projection_replay.py` | `IntegrityViolation` | 89 | `replay_confirmed_execution` | 89 | STILL_ACCURATE | — |
| R245 | 338 | `data_layer/projection_replay.py` | `IntegrityViolation` | 91 | `replay_confirmed_execution` | 91 | STILL_ACCURATE | — |
| R246 | 339 | `data_layer/projection_replay.py` | `IntegrityViolation` | 94 | `replay_confirmed_execution` | 94 | STILL_ACCURATE | — |
| R247 | 340 | `data_layer/projection_replay.py` | `IntegrityViolation` | 98 | `replay_confirmed_execution` | 98 | STILL_ACCURATE | — |
| R248 | 341 | `data_layer/projection_replay.py` | `OrderRecord` | 74 | `replay_confirmed_execution` | 74 | STILL_ACCURATE | — |
| R249 | 342 | `data_layer/projection_replay.py` | `PositionRecord` | 48 | `_position_projection` | 48 | STILL_ACCURATE | — |
| R250 | 343 | `data_layer/projection_replay.py` | `PositionRecord` | 59 | `_position_projection` | 59 | STILL_ACCURATE | — |
| R251 | 344 | `data_layer/runtime_safety.py` | `CanonicalExecutionEvidenceAdapter` | 50 | `FinancialRuntimeSafetyService::__init__` | 50 | STILL_ACCURATE | — |
| R252 | 345 | `data_layer/runtime_safety.py` | `RecoveryDecision` | 58 | `FinancialRuntimeSafetyService::__init__` | 58 | STILL_ACCURATE | — |
| R253 | 346 | `data_layer/runtime_safety.py` | `RecoveryDecision` | 157 | `FinancialRuntimeSafetyService::assess` | 157 | STILL_ACCURATE | — |
| R254 | 347 | `data_layer/runtime_safety.py` | `RecoveryDecision` | 174 | `FinancialRuntimeSafetyService::assess` | 174 | STILL_ACCURATE | — |
| R255 | 348 | `data_layer/runtime_safety.py` | `RecoveryEvidence` | 130 | `FinancialRuntimeSafetyService::_base_evidence` | 130 | STILL_ACCURATE | — |
| R256 | 349 | `data_layer/sqlite.py` | `ConcurrencyConflict` | 114 | `SQLiteOrderRepository::transition` | 114 | DRIFTED | call unchanged at line 114, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R257 | 350 | `data_layer/sqlite.py` | `ConcurrencyConflict` | 121 | `SQLiteOrderRepository::transition` | 121 | DRIFTED | call unchanged at line 121, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R258 | 351 | `data_layer/sqlite.py` | `ConcurrencyConflict` | 244 | `SQLitePositionRepository::put_cas` | 244 | DRIFTED | call unchanged at line 244, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R259 | 352 | `data_layer/sqlite.py` | `ConcurrencyConflict` | 248 | `SQLitePositionRepository::put_cas` | 248 | DRIFTED | call unchanged at line 248, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R260 | 353 | `data_layer/sqlite.py` | `ConcurrencyConflict` | 261 | `SQLitePositionRepository::put_cas` | 261 | DRIFTED | call unchanged at line 261, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R261 | 354 | `data_layer/sqlite.py` | `ExecutionRecord` | 153 | `SQLiteExecutionRepository::_record` | 153 | DRIFTED | call unchanged at line 153, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R262 | 355 | `data_layer/sqlite.py` | `IntegrityViolation` | 29 | `_translate_integrity` | 29 | DRIFTED | call unchanged at line 29, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R263 | 356 | `data_layer/sqlite.py` | `IntegrityViolation` | 110 | `SQLiteOrderRepository::transition` | 110 | DRIFTED | call unchanged at line 110, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R264 | 357 | `data_layer/sqlite.py` | `IntegrityViolation` | 401 | `SQLiteStorage::_validate_financial_rows` | 401 | DRIFTED | call unchanged at line 401, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R265 | 358 | `data_layer/sqlite.py` | `IntegrityViolation` | 406 | `SQLiteStorage::_validate_financial_rows` | 406 | DRIFTED | call unchanged at line 406, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R266 | 359 | `data_layer/sqlite.py` | `IntegrityViolation` | 413 | `SQLiteStorage::_validate_financial_rows` | 413 | DRIFTED | call unchanged at line 413, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R267 | 360 | `data_layer/sqlite.py` | `OrderRecord` | 95 | `SQLiteOrderRepository::get` | 95 | DRIFTED | call unchanged at line 95, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R268 | 361 | `data_layer/sqlite.py` | `PositionRecord` | 211 | `SQLitePositionRepository::_record` | 211 | DRIFTED | call unchanged at line 211, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R269 | 362 | `data_layer/sqlite.py` | `StorageError` | 360 | `SQLiteStorage::_connect` | 360 | DRIFTED | call unchanged at line 360, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R270 | 363 | `data_layer/sqlite.py` | `StorageError` | 383 | `SQLiteStorage::open` | 383 | DRIFTED | call unchanged at line 383, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R271 | 364 | `data_layer/sqlite.py` | `StorageError` | 423 | `SQLiteStorage::unit_of_work` | 423 | DRIFTED | call unchanged at line 423, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R272 | 365 | `data_layer/sqlite.py` | `TransactionStateError` | 276 | `SQLiteUnitOfWork::_require_active` | 276 | DRIFTED | call unchanged at line 276, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R273 | 366 | `data_layer/sqlite.py` | `TransactionStateError` | 283 | `SQLiteUnitOfWork::__enter__` | 283 | DRIFTED | call unchanged at line 283, but `data_layer/sqlite.py` is no longer in the runtime closure (lazy `data_layer/__init__.py`, commit `1ac3a64`) |
| R274 | 367 | `exchange/market_feed.py` | `BinancePublicDataProvider` | 117 | `MarketFeed::__init__` | 117 | STILL_ACCURATE | — |
| R275 | 368 | `exchange/market_feed.py` | `InvalidCandleError` | 369 | `MarketFeed::_require_metadata` | 369 | STILL_ACCURATE | — |
| R276 | 369 | `exchange/market_feed.py` | `MarketFeedService` | 120 | `MarketFeed::__init__` | 120 | STILL_ACCURATE | — |
| R277 | 370 | `main.py` | `AtlasApplication` | 345 | `AtlasProcess::start` | 406 | DRIFTED | line 345 → 406; module, class, defining module and scope unchanged |
