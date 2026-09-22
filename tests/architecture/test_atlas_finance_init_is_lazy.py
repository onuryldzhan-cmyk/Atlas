"""Runtime guard: the ``atlas_finance`` package markers must not load the heavy chain.

Registry v4.45 (GRANT-B2-PHASE-1-LAZY-ONLY) authorizes converting
``atlas_finance/__init__.py`` and ``atlas_finance/market_data/__init__.py`` to
PEP 562 lazy re-exports, mirroring ``data_layer/__init__.py``. This file is the
compensating guard for that change, written to the same standard as
``tests/architecture/test_data_layer_init_is_lazy.py``.

What was wrong
--------------
Both markers were eager. ``atlas_finance/__init__.py`` performed an
unconditional ``from atlas_finance.market_data import (...)`` of thirty names,
and ``atlas_finance/market_data/__init__.py`` eagerly imported
``binance_public_provider`` and ``market_feed_service``. Because Python executes
every ancestor package ``__init__`` on the way into a submodule, importing the
pure L1 contract module ``atlas_finance/market_data/contracts.py`` loaded a live
``requests`` HTTP client, ``BinancePublicDataProvider`` and ``MarketFeedService``
as a side effect. Measured at commit 1e737a8: **313 modules**. That is
ARCH-EDGE-001's Group B2, classified MEDIUM there precisely because - unlike
Groups A, B1 and C - no inertness argument was available and the coupling was
real, present and measured.

Why a runtime guard rather than a static one
--------------------------------------------
The same asymmetry that made ``data_layer``'s guard necessary applies here. The
static detector in ``tools.build_architecture_inventory`` resolves imports by
walking ``ast.Import`` and ``ast.ImportFrom`` nodes. Lazy re-exports go through
``importlib.import_module`` on *string* module names, which is neither node
type, so the detector is structurally blind to a regression that reached the
provider through an importlib string at import time. Only a runtime measurement
catches that shape, so every assertion below is taken from a **clean subprocess
interpreter**, diffing ``sys.modules`` against that subprocess's own baseline,
so modules already imported by the pytest process cannot mask the result.

What this guard deliberately does NOT assert
--------------------------------------------
It does not assert that the architecture gate is green, because it is not and is
not supposed to be. ``find_forbidden_edges`` flags the ancestor-package
*execution* edge, which exists no matter what these files contain. Making them
lazy removes the runtime coupling; it does not remove the edge the static
detector measures. Clearing the gate would require the L2 -> L1 reclassification
of phase (ii), which registry v4.45 explicitly does not authorize.

``test_group_b2_violation_count_is_unchanged`` therefore pins the *expected red*
result: exactly the two Group B2 edges, no more and no fewer. A future change
that silently altered that count - in either direction - fails here rather than
passing unnoticed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tools.build_architecture_inventory import (
    REPOSITORY_ROOT,
    find_forbidden_edges,
    load_architecture_map,
)

# The modules whose eager loading was the actual harm. ``requests`` is the live
# HTTP client; the other two are the provider and feed service that pull it in.
HEAVY_CHAIN = frozenset(
    {
        "requests",
        "atlas_finance.market_data.binance_public_provider",
        "atlas_finance.market_data.market_feed_service",
    }
)

# The two Group B2 edges, as the gate measures them. Pinned as a prediction.
EXPECTED_GROUP_B2_EDGES = (
    "atlas_finance/market_data/contracts.py -> atlas_finance/__init__.py",
    "atlas_finance/market_data/contracts.py -> atlas_finance/market_data/__init__.py",
)

# ``__all__`` for both packages, pinned at their pre-change values. The grant
# requires the public surface to be unchanged; this is what enforces it.
EXPECTED_ATLAS_FINANCE_ALL = (
    "BinancePublicDataProvider", "InvalidCandleError", "InvalidCandleLimitError",
    "InvalidPriceError", "InvalidSymbolError", "InvalidTimeframeError",
    "MarketCandle", "MarketDataConfigurationError", "MarketDataConnectionError",
    "MarketDataError", "MarketDataProviderError", "MarketDataProviderProtocol",
    "MarketDataProviderUnavailableError", "MarketDataRateLimitError",
    "MarketDataRequestError", "MarketDataRequestStatistics",
    "MarketDataResponseError", "MarketDataServiceError",
    "MarketDataServiceNotRunningError", "MarketDataServiceShutdownError",
    "MarketDataServiceStartupError", "MarketDataTimeoutError",
    "MarketDataValidationError", "MarketFeedEventType", "MarketFeedService",
    "MarketFeedSnapshot", "MarketFeedStatistics", "MarketPrice", "__author__",
    "__description__", "__package_name__", "__project__", "__title__",
    "__version__", "candles_as_dicts", "immutable_mapping", "utc_now",
)

EXPECTED_MARKET_DATA_ALL = tuple(
    name
    for name in EXPECTED_ATLAS_FINANCE_ALL
    if name not in {"__author__", "__description__"}
)

_PROBE = textwrap.dedent(
    """
    import importlib
    import json
    import sys

    sys.path.insert(0, sys.argv[1])
    baseline = set(sys.modules)
    importlib.import_module(sys.argv[2])
    print(json.dumps(sorted(set(sys.modules) - baseline)))
    """
)


def _modules_loaded_by_importing(sys_path_entry: Path, dotted: str) -> set[str]:
    """Return the module names importing ``dotted`` adds, in a fresh interpreter."""

    completed = subprocess.run(
        [sys.executable, "-c", _PROBE, str(sys_path_entry), dotted],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, (
        f"probe interpreter failed importing {dotted!r}\n"
        f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
    )
    return set(json.loads(completed.stdout))


# ---------------------------------------------------------------------------
# The guard's own premise
# ---------------------------------------------------------------------------


def test_the_heavy_chain_is_real_and_reachable() -> None:
    """A guard against loading modules that do not exist passes for free.

    Prove the chain this file forbids is genuinely there: the provider module
    exists on disk and does import ``requests`` at module scope, so the
    measurements below are forbidding something real.
    """

    provider = REPOSITORY_ROOT / "atlas_finance/market_data/binance_public_provider.py"
    feed = REPOSITORY_ROOT / "atlas_finance/market_data/market_feed_service.py"

    assert provider.is_file(), "the provider module this guard is about does not exist"
    assert feed.is_file(), "the feed service module this guard is about does not exist"

    source = provider.read_text(encoding="utf-8")
    assert "import requests" in source, (
        "binance_public_provider no longer imports requests at module scope; the "
        "premise of this guard - that eager re-export dragged in a live HTTP "
        "client - has changed and the guard needs re-deriving"
    )

    # And it really does load when asked for directly, so 'absent' below means
    # 'not pulled in as a side effect', not 'unloadable in this environment'.
    loaded = _modules_loaded_by_importing(
        REPOSITORY_ROOT, "atlas_finance.market_data.binance_public_provider"
    )
    assert "requests" in loaded, (
        "importing the provider directly did not load requests, so the absence "
        "assertions below would pass vacuously"
    )


# ---------------------------------------------------------------------------
# The real invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dotted",
    [
        "atlas_finance",
        "atlas_finance.market_data",
        "atlas_finance.market_data.contracts",
    ],
)
def test_importing_does_not_load_the_heavy_chain(dotted: str) -> None:
    """Neither package marker may drag the provider chain in as a side effect.

    ``atlas_finance.market_data.contracts`` is the case ARCH-EDGE-001 Group B2
    is actually about: a pure L1 contract module whose import executes both
    ancestor ``__init__`` files on the way in.
    """

    loaded = _modules_loaded_by_importing(REPOSITORY_ROOT, dotted)
    leaked = loaded & HEAVY_CHAIN

    assert leaked == set(), (
        f"importing {dotted} eagerly loaded {sorted(leaked)}. This is the "
        "ARCH-EDGE-001 Group B2 coupling: a pure L1 contract import pulling in a "
        "live HTTP client and the market-feed service. Registry v4.45 "
        "GRANT-B2-PHASE-1-LAZY-ONLY removed it by making both package markers "
        "PEP 562 lazy; that property has regressed."
    )


def test_contracts_import_is_small() -> None:
    """The coupling is gone in magnitude, not just in the three named modules.

    ARCH-EDGE-001 measured 313 modules for this import at commit 1e737a8. The
    bound below is deliberately loose - it is a regression tripwire, not a
    performance budget - but anything near the old figure means the chain is
    back through some route the named-module check did not anticipate.
    """

    loaded = _modules_loaded_by_importing(
        REPOSITORY_ROOT, "atlas_finance.market_data.contracts"
    )

    assert len(loaded) < 150, (
        f"importing atlas_finance.market_data.contracts loaded {len(loaded)} "
        "modules. ARCH-EDGE-001 measured 313 before the lazy conversion and the "
        "post-conversion measurement was well under 100, so a figure this large "
        "means heavy transitive imports have returned."
    )


def test_lazy_attribute_access_still_resolves() -> None:
    """Laziness must defer the import, not break it.

    Without this, every assertion above could be satisfied by package markers
    that had stopped re-exporting anything at all - passing the layering check
    by removing the feature rather than by keeping it lazy. This mirrors the
    non-vacuity guard in test_data_layer_init_is_lazy.py.
    """

    probe = textwrap.dedent(
        """
        import json, sys
        sys.path.insert(0, sys.argv[1])
        import atlas_finance

        before = "atlas_finance.market_data.market_feed_service" in sys.modules
        service = atlas_finance.MarketFeedService
        after = "atlas_finance.market_data.market_feed_service" in sys.modules

        import atlas_finance.market_data as md
        import atlas_finance.market_data.models as models

        print(json.dumps({
            "loaded_before_access": before,
            "loaded_after_access": after,
            "resolved": service is not None,
            "identity_parent_vs_subpackage":
                atlas_finance.MarketCandle is md.MarketCandle,
            "identity_parent_vs_leaf":
                atlas_finance.MarketCandle is models.MarketCandle,
            "submodule_attribute_preserved": md.models is models,
        }))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(REPOSITORY_ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert result["loaded_before_access"] is False, "the feed service loaded eagerly"
    assert result["loaded_after_access"] is True, (
        "attribute access did not import the feed service, so the lazy table is "
        "resolving to something other than the real module"
    )
    assert result["resolved"] is True, "lazy re-export resolved to nothing"
    assert result["identity_parent_vs_subpackage"] is True, (
        "atlas_finance.MarketCandle is not the same object as "
        "atlas_finance.market_data.MarketCandle; the re-export changed identity"
    )
    assert result["identity_parent_vs_leaf"] is True, (
        "the re-exported name is not the object defined in models.py"
    )
    assert result["submodule_attribute_preserved"] is True, (
        "atlas_finance.market_data.models stopped working as an attribute; the "
        "eager imports used to bind submodules onto the package object and that "
        "behaviour must be preserved"
    )


@pytest.mark.parametrize(
    ("dotted", "expected"),
    [
        ("atlas_finance", EXPECTED_ATLAS_FINANCE_ALL),
        ("atlas_finance.market_data", EXPECTED_MARKET_DATA_ALL),
    ],
)
def test_public_surface_is_unchanged(dotted: str, expected: tuple[str, ...]) -> None:
    """``__all__`` is pinned at its pre-change value, and every name resolves.

    GRANT-B2-PHASE-1-LAZY-ONLY forbids any change to either package's public
    names. Asserting the list alone would not be enough: a name can be listed
    and still fail to resolve through ``__getattr__``, so both are checked.
    """

    probe = textwrap.dedent(
        """
        import importlib, json, sys
        sys.path.insert(0, sys.argv[1])
        package = importlib.import_module(sys.argv[2])
        print(json.dumps({
            "all": list(package.__all__),
            "unresolved": [n for n in package.__all__ if not hasattr(package, n)],
        }))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(REPOSITORY_ROOT), dotted],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)

    assert tuple(result["all"]) == expected, (
        f"{dotted}.__all__ changed. Added: "
        f"{sorted(set(result['all']) - set(expected))}; removed: "
        f"{sorted(set(expected) - set(result['all']))}"
    )
    assert result["unresolved"] == [], (
        f"{dotted} lists {result['unresolved']} in __all__ but they do not "
        "resolve, so the lazy table and the public surface have drifted apart"
    )


# ---------------------------------------------------------------------------
# The expected-red prediction, pinned
# ---------------------------------------------------------------------------


def test_group_b2_violation_count_is_unchanged() -> None:
    """The lazy conversion must leave the static gate's verdict exactly as it was.

    This is the assertion that keeps the record honest in both directions.

    It must not DECREASE: a drop would mean something cleared the edges without
    the authorized reclassification - most likely a weakened rule or a new
    permitted exception, both of which registry v4.45 forbids outright, and
    either of which would be a worse outcome than the red gate.

    It must not INCREASE: a rise would mean the lazy conversion introduced new
    forbidden coupling of its own.

    The predicted, accepted answer is: exactly these two Group B2 edges.
    """

    architecture_map = load_architecture_map()
    module_layers = architecture_map["module_layers"]

    violations = find_forbidden_edges(
        REPOSITORY_ROOT,
        list(module_layers),
        module_layers,
        architecture_map["forbidden_edges"],
        architecture_map.get("permitted_exceptions", []),
    )

    edges = sorted(violation.split(" (")[0] for violation in violations)

    assert edges == sorted(EXPECTED_GROUP_B2_EDGES), (
        "the forbidden-edge set changed. Expected exactly the two ARCH-EDGE-001 "
        f"Group B2 edges and found {edges}. A DECREASE means the gate was "
        "cleared without the L2->L1 reclassification that registry v4.45 "
        "explicitly withholds; an INCREASE means new coupling was introduced."
    )


# ---------------------------------------------------------------------------
# Discrimination proof
#
# A passing test is not evidence until it has been shown to fail against the
# behaviour it forbids. These build the regressed shapes as synthetic packages
# in tmp_path and run the *same* measurement against them. The real
# atlas_finance package markers are never modified to manufacture a failure:
# they are the evidence this guard rests on.
# ---------------------------------------------------------------------------

_FIXTURE_PROVIDER = "VALUE = 'heavy provider loaded'\n"

_FIXTURE_EAGER_INIT = "from __PKG__.provider import VALUE as Provider\n"

_FIXTURE_IMPORTLIB_STRING_INIT = textwrap.dedent(
    """
    import importlib

    # The detector-blind regression: a string module name resolved at import
    # time. No ast.Import or ast.ImportFrom node exists for this, so the static
    # forbidden-edge detector cannot see it. Only a runtime measurement can.
    Provider = getattr(importlib.import_module("__PKG__.provider"), "VALUE")
    """
)

_FIXTURE_LAZY_INIT = textwrap.dedent(
    """
    import importlib
    from typing import Any

    _LAZY = {"Provider": ("__PKG__.provider", "VALUE")}

    def __getattr__(name: str) -> Any:
        target = _LAZY.get(name)
        if target is None:
            raise AttributeError(name)
        module_name, attribute_name = target
        return getattr(importlib.import_module(module_name), attribute_name)
    """
)


def _build_fixture_package(tmp_path: Path, name: str, init_source: str) -> None:
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text(
        init_source.replace("__PKG__", name), encoding="utf-8"
    )
    (package / "provider.py").write_text(_FIXTURE_PROVIDER, encoding="utf-8")
    (package / "contracts.py").write_text("CONTRACT = object()\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("label", "init_source"),
    [
        ("eager_from_import", _FIXTURE_EAGER_INIT),
        ("dynamic_importlib_string", _FIXTURE_IMPORTLIB_STRING_INIT),
    ],
)
def test_check_fails_against_a_regressed_init(
    tmp_path: Path, label: str, init_source: str
) -> None:
    """The measurement must actually catch both regression shapes.

    ``dynamic_importlib_string`` is the case that motivates using a runtime
    measurement at all: it is invisible to the static detector, so if this
    measurement did not catch it, nothing in the repository would.
    """

    package_name = f"af_fixture_{label}"
    _build_fixture_package(tmp_path, package_name, init_source)

    loaded = _modules_loaded_by_importing(tmp_path, f"{package_name}.contracts")

    assert f"{package_name}.provider" in loaded, (
        f"the {label} regression was NOT detected: importing "
        f"{package_name}.contracts did not report {package_name}.provider as "
        "loaded, so this guard would not catch the equivalent regression in the "
        "real atlas_finance package markers"
    )


def test_check_passes_against_a_faithful_lazy_replica(tmp_path: Path) -> None:
    """The control: the same measurement must clear a correctly lazy package.

    Without this, a measurement that reported everything as a violation would
    pass both discrimination cases above while being useless.
    """

    package_name = "af_fixture_lazy_control"
    _build_fixture_package(tmp_path, package_name, _FIXTURE_LAZY_INIT)

    loaded = _modules_loaded_by_importing(tmp_path, f"{package_name}.contracts")

    assert f"{package_name}.provider" not in loaded, (
        "the measurement reported a violation against a correctly lazy package, "
        "so it does not discriminate - it just always fails"
    )
