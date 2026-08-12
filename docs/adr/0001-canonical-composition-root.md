# ADR-0001: Canonical Composition Root

## Status

Accepted. Frozen architecture decision for Block 2 / Package 2A.

## Decision

`core/application.py` (the `AtlasApplication` class) is the sole canonical
composition root for the Atlas runtime. The canonical construction chain is:

```
main.py -> core/application.py (AtlasApplication) -> core/runtime.py (AtlasRuntime)
```

`atlas_runtime/bootstrap.py` -> `atlas_runtime/runtime.py` is **not** adopted
as the runtime in Block 2, despite containing lifecycle/config/secrets
patterns that may be individually useful later. `atlas_runtime/*` is
classified `NON_CANONICAL / RETIRE_OR_QUARANTINE`.

## Evidence (static reachability, verified by AST import analysis)

- `main.py` imports exactly one first-party symbol: `core.application.AtlasApplication`,
  and constructs it once (`self.application = AtlasApplication(...)`, `main.py:345`).
  No other file constructs `AtlasApplication`.
- `web_app.py` has zero first-party imports at module scope; it constructs no
  application, brain, market loop, or execution manager of its own.
- `core/application.py` (`AtlasApplication._build_services`) is the only
  place in the entire repository that constructs `AtlasBrain`, `MarketLoop`,
  and `ExecutionManager` together as a wired system (`core/application.py:176`,
  `:204`, `:192`).
- `atlas_runtime/*` has **zero live importers**. A repository-wide AST/grep
  sweep found only three importers of `atlas_runtime`, all of them
  root-level `test_*.py` scripts (`test_atlas_infrastructure.py`,
  `test_atlas_secure_core.py`, `test_atlas_runtime_empty.py`) that are
  outside `tests/` and are already classified `LEGACY` /
  `"safe_for_pytest_collection": false` in `tests/legacy_test_inventory.json`.
  `pytest.ini` scopes `testpaths = tests`, so these scripts are not part of
  canonical test collection either. No dynamic import (`importlib.import_module`,
  `__import__`) of `atlas_runtime` exists anywhere in the repository.
- The generated runtime closure (`packaging/atlas_runtime_closure.json`),
  computed by static reachability from `main.py` and `web_app.py`, does not
  contain any `atlas_runtime/*` module. This is machine-checked by
  `tests/architecture/test_composition_root_is_unique.py` and
  `tools/build_architecture_inventory.py check`.

## Reasoning

**Minimal-change principle.** `core/application.py` is already the live,
tested, PAPER-mode-default composition root reachable from `main.py`. Adopting
`atlas_runtime/*` instead would require re-pointing the entry point, revalidating
the entire startup/shutdown lifecycle, capital/position/execution wiring, and
the Block-1 frozen risk/execution safety guarantees (commits `b627178`,
`9457791`, `472b213`) against an unexercised runtime. That is a large,
high-blast-radius change with no functional requirement driving it in this
package.

**Why the more sophisticated dead runtime is not adopted wholesale.**
`atlas_runtime/*` is architecturally more elaborate in places (bootstrap
staging, structured lifecycle states) but it has never been exercised as the
live entry point, has no current test coverage proving it preserves Block-1
safety behavior (PAPER-only default, execution admission, capital
reservation posture), and swapping it in would silently change execution
behavior — which Package 2A is explicitly required not to do (see
`test_composition_root_does_not_wire_risk_services` for the related M-1
interlock, and `test_live_execution_is_denied_by_default` for the LIVE-mode
posture, both of which pin the *current* `core/application.py` /
`core/execution_manager.py` behavior, not a hypothetical `atlas_runtime`
equivalent).

**Selective future reuse remains allowed.** This ADR quarantines
`atlas_runtime/*` as a module tree, not as an idea. Specific lifecycle,
configuration, or secrets-handling patterns inside it may be extracted and
reimplemented against `core/application.py` / `core/runtime.py` in a future
package, with their own review and test coverage, once M-1 remediation
(Package 2B) is underway. This ADR only forecloses *replacing* the runtime
wholesale in Block 2, not learning from it.

## Consequences

- `packaging/atlas_architecture_map.json` records `atlas_runtime` under
  `canonical_authorities.atlas_runtime.status = "NON_CANONICAL_QUARANTINED"`.
- `tests/architecture/test_composition_root_is_unique.py` machine-enforces
  that `AtlasBrain`, `MarketLoop`, and `ExecutionManager` are constructed
  together in exactly one place: `core/application.py`.
- Physical quarantine of the `atlas_runtime/` directory (moving it under
  `_quarantine/`) is executed as part of Package 2A section G, since the
  zero-live-importer and zero-canonical-test-importer conditions required
  before moving a file are both satisfied.
