"""Block 6A - venue instrument-rule freshness and staleness safety.

Package 5D shipped `config/instrument_rules.json` as the sole venue precision
authority and recorded limitation M2 against it: `retrieved_at` was validated
as present, but nothing bounded how old a checked-in rule could be. The Block
5 closure record carried that forward as operational-readiness gate V2. These
tests hold the contract that closes it.

What is *not* tested here: quantization arithmetic, tick/step admission, and
rule-digest identity are Block 5D contracts covered by
`tests/test_block5d_instrument_precision_contract.py`. This file touches them
only to pin that 6A left them unchanged - a freshness gate that perturbed the
rule digest would silently invalidate every prior risk admission.

Every freshness answer below comes from an injected clock. Not one assertion
depends on the wall clock, on how old the checked-in config happens to be on
the day the suite runs, or on the order the tests execute in.
"""

from __future__ import annotations

import socket
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from core.application import DEFAULT_INSTRUMENT_RULES_PATH, AtlasApplication
from core.instrument_rules import (
    INSTRUMENT_RULES_SCHEMA_VERSION,
    InstrumentRules,
    InstrumentRulesConfigError,
    InstrumentRuleset,
    floor_to_step,
    is_aligned_to_step,
    load_instrument_ruleset,
)
from core import venue_rule_freshness as freshness_module
from core.venue_rule_freshness import (
    DEFAULT_MAXIMUM_RULE_AGE_SECONDS,
    REASON_INVALID,
    REASON_STALE,
    REASON_UNKNOWN,
    VenueRuleFreshnessPolicy,
    VenueRuleFreshnessPolicyError,
    VenueRuleFreshnessService,
    VenueRuleFreshnessStatus,
)

from tests.test_block5d_instrument_precision_contract import buy, seed_state


STATUS = VenueRuleFreshnessStatus

# The provenance instant every synthetic ruleset below is stamped with, and
# the threshold every age is measured against. Both are fixtures, not repo
# facts: the point is that the *policy* decides, not the calendar.
OBSERVED_AT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
THRESHOLD_SECONDS = 7 * 24 * 60 * 60


def rule(**overrides: Any) -> InstrumentRules:
    defaults: dict[str, Any] = dict(
        venue="BINANCE",
        symbol="BTCUSDT",
        base_asset="BTC",
        quote_asset="USDT",
        quantity_step="0.00001",
        min_quantity="0.00001",
        min_notional="5",
        price_tick="0.01",
        source="https://api.binance.com/api/v3/exchangeInfo",
        source_version="1787161613022",
        retrieved_at="2026-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    return InstrumentRules(**defaults)


def ruleset(*entries: InstrumentRules) -> InstrumentRuleset:
    entries = entries or (rule(),)
    return InstrumentRuleset({entry.symbol: entry for entry in entries})


def service(
    *,
    at: datetime | None = None,
    offset_seconds: int = 0,
    maximum_age_seconds: int = THRESHOLD_SECONDS,
    allow_stale_bounded_execution: bool = True,
) -> VenueRuleFreshnessService:
    """A service frozen at ``OBSERVED_AT + offset_seconds`` unless told otherwise."""
    moment = at if at is not None else OBSERVED_AT + timedelta(seconds=offset_seconds)
    return VenueRuleFreshnessService(
        policy=VenueRuleFreshnessPolicy(
            maximum_age_seconds=maximum_age_seconds,
            allow_stale_bounded_execution=allow_stale_bounded_execution,
        ),
        clock=lambda: moment,
    )


# ===========================================================================
# A/B/E/F - the four states, the boundary, and the injected clock
# ===========================================================================


def test_rules_inside_the_threshold_are_fresh() -> None:
    """A. Provenance younger than the configured maximum age is FRESH, and the
    report carries the evidence a monitor needs rather than a bare verdict."""
    report = service(offset_seconds=3600).assess(ruleset())

    assert report.status is STATUS.FRESH
    assert report.is_fresh is True
    assert report.reason is None
    assert report.age_seconds == 3600
    assert report.venue == "BINANCE"
    assert report.schema_version == INSTRUMENT_RULES_SCHEMA_VERSION
    assert report.symbol_count == 1
    assert report.source == "https://api.binance.com/api/v3/exchangeInfo"
    assert report.source_version == "1787161613022"
    assert report.observed_at == OBSERVED_AT.isoformat()
    assert report.maximum_age_seconds == THRESHOLD_SECONDS


def test_rules_past_the_threshold_are_stale() -> None:
    """B. One second of age beyond the policy is the whole difference between
    a runtime that may reach a venue and one that may not."""
    report = service(offset_seconds=THRESHOLD_SECONDS + 1).assess(ruleset())

    assert report.status is STATUS.STALE
    assert report.is_fresh is False
    assert report.reason == REASON_STALE
    assert report.age_seconds == THRESHOLD_SECONDS + 1


def test_threshold_boundary_is_closed_on_the_fresh_side() -> None:
    """E. Age exactly equal to the maximum has not *exceeded* the maximum. The
    boundary is stated once so the same input can never straddle two answers."""
    at_boundary = service(offset_seconds=THRESHOLD_SECONDS).assess(ruleset())
    past_boundary = service(offset_seconds=THRESHOLD_SECONDS + 1).assess(ruleset())

    assert at_boundary.age_seconds == THRESHOLD_SECONDS
    assert at_boundary.status is STATUS.FRESH
    assert past_boundary.status is STATUS.STALE


def test_the_oldest_rule_in_the_set_decides_the_age() -> None:
    """A partial operator refresh must not be averaged into freshness: the set
    a runtime trades on is only as fresh as the rule left furthest behind."""
    stale_entry = rule(symbol="ETHUSDT", base_asset="ETH", retrieved_at="2025-12-01T00:00:00Z")
    report = service(offset_seconds=3600).assess(ruleset(rule(), stale_entry))

    assert report.symbol_count == 2
    assert report.observed_at == datetime(2025, 12, 1, tzinfo=UTC).isoformat()
    assert report.status is STATUS.STALE


def test_freshness_is_a_pure_function_of_the_injected_clock() -> None:
    """F. Two evaluations with the same clock are byte-identical, and a clock
    that cannot be trusted to be unambiguous is refused rather than assumed."""
    frozen = service(offset_seconds=42)
    rules = ruleset()

    first = frozen.assess(rules)
    second = frozen.assess(rules)

    assert first == second
    assert first.to_dict() == second.to_dict()

    naive = VenueRuleFreshnessService(clock=lambda: datetime(2026, 1, 1, 0, 0, 0))

    with pytest.raises(VenueRuleFreshnessPolicyError):
        naive.assess(rules)


def test_policy_rejects_a_threshold_it_cannot_enforce() -> None:
    """A policy that is not usable fails at construction, at the composition
    root, rather than being silently replaced by a default at decision time."""
    for bad in (0, -1, "30", 30.0, True):
        with pytest.raises(VenueRuleFreshnessPolicyError):
            VenueRuleFreshnessPolicy(maximum_age_seconds=bad)

    with pytest.raises(VenueRuleFreshnessPolicyError):
        VenueRuleFreshnessPolicy(future_skew_seconds=-1)

    with pytest.raises(VenueRuleFreshnessPolicyError):
        VenueRuleFreshnessPolicy(allow_stale_bounded_execution="yes")


# ===========================================================================
# C/D - unknown and invalid provenance
# ===========================================================================


def test_absent_rules_are_unknown_not_assumed_fresh() -> None:
    """C. Freshness that cannot be determined is reported as exactly that."""
    for absent in (None, InstrumentRuleset({})):
        report = service().assess(absent)

        assert report.status is STATUS.UNKNOWN
        assert report.reason == REASON_UNKNOWN
        assert report.age_seconds is None
        assert report.observed_at is None
        assert report.symbol_count == 0


def test_a_rule_without_provenance_cannot_be_constructed_at_all() -> None:
    """C. The other half of the missing-provenance contract, which is why
    UNKNOWN can only mean "no ruleset" and never "a ruleset with no source":
    Block 5D already refuses to build a rule that cannot say where it came
    from, and 6A depends on that staying true."""
    for field_name in ("source", "source_version", "retrieved_at"):
        with pytest.raises(InstrumentRulesConfigError):
            rule(**{field_name: "  "})


@pytest.mark.parametrize(
    "bad_timestamp",
    [
        "not-a-timestamp",
        "2026-01-01",
        "2026-01-01T00:00:00",  # naive: the offset would have to be guessed
        "01/01/2026 00:00:00Z",
    ],
)
def test_malformed_provenance_is_invalid(bad_timestamp: str) -> None:
    """D. An unparseable or ambiguous timestamp is a provenance defect. It is
    never rounded to "probably recent" and never silently ignored."""
    report = service(offset_seconds=3600).assess(ruleset(rule(retrieved_at=bad_timestamp)))

    assert report.status is STATUS.INVALID
    assert report.reason == REASON_INVALID
    assert report.age_seconds is None


def test_provenance_dated_beyond_the_skew_allowance_is_invalid() -> None:
    """D. A checked-in artifact dated after the runtime's own clock is a
    defect, not a negative age. Inside the bounded skew allowance it is
    tolerated and reported as zero age; beyond it, it fails closed."""
    inside_skew = service(at=OBSERVED_AT - timedelta(seconds=60)).assess(ruleset())

    assert inside_skew.status is STATUS.FRESH
    assert inside_skew.age_seconds == 0

    beyond_skew = service(at=OBSERVED_AT - timedelta(days=1)).assess(ruleset())

    assert beyond_skew.status is STATUS.INVALID
    assert beyond_skew.reason == REASON_INVALID


def test_a_multi_venue_ruleset_has_no_single_freshness_answer() -> None:
    """This runtime trades one venue at a time. A ruleset spanning two of them
    is refused rather than resolved by picking one."""
    other_venue = rule(venue="KRAKEN", symbol="ETHUSDT", base_asset="ETH")
    report = service(offset_seconds=3600).assess(ruleset(rule(), other_venue))

    assert report.status is STATUS.INVALID


# ===========================================================================
# G/H/I - the gate
# ===========================================================================


def test_only_fresh_rules_pass_the_live_gate() -> None:
    """G + I. Live authority requires FRESH. STALE, UNKNOWN and INVALID all
    fail closed, each with the reason an operator needs to act on."""
    cases = [
        (service(offset_seconds=THRESHOLD_SECONDS + 1), ruleset(), REASON_STALE),
        (service(offset_seconds=3600), None, REASON_UNKNOWN),
        (
            service(offset_seconds=3600),
            ruleset(rule(retrieved_at="not-a-timestamp")),
            REASON_INVALID,
        ),
    ]

    for gate_service, rules, expected_reason in cases:
        decision = gate_service.evaluate_gate(rules, live_authorized=True)

        assert decision.allowed is False
        assert decision.reason == expected_reason
        assert decision.live_authorized is True
        assert decision.to_dict()["freshness"]["status"] == decision.report.status.value


def test_fresh_rules_pass_the_live_gate() -> None:
    """H. The gate is not a blanket refusal: validated, in-date rules pass,
    and pass carrying no reason."""
    decision = service(offset_seconds=3600).evaluate_gate(ruleset(), live_authorized=True)

    assert decision.allowed is True
    assert decision.reason is None
    assert decision.report.status is STATUS.FRESH


def test_bounded_execution_may_continue_on_stale_rules_only_by_policy() -> None:
    """The one deliberate PAPER/live asymmetry, in both directions. A bounded
    run continues on stale static rules because it cannot lose money - but the
    report still says STALE, and the policy can withdraw the permission."""
    stale = ruleset()

    permitted = service(
        offset_seconds=THRESHOLD_SECONDS + 1
    ).evaluate_gate(stale, live_authorized=False)

    assert permitted.allowed is True
    assert permitted.reason is None
    assert permitted.report.status is STATUS.STALE

    withheld = service(
        offset_seconds=THRESHOLD_SECONDS + 1,
        allow_stale_bounded_execution=False,
    ).evaluate_gate(stale, live_authorized=False)

    assert withheld.allowed is False
    assert withheld.reason == REASON_STALE


def test_bounded_execution_never_falls_back_from_unknown_or_invalid_rules() -> None:
    """I. The stale-tolerance switch is exactly that. Rules whose provenance
    cannot be evaluated at all are refused in bounded mode too: there is no
    path from "cannot tell" to unconstrained execution."""
    tolerant = service(offset_seconds=3600)

    unknown = tolerant.evaluate_gate(None, live_authorized=False)
    invalid = tolerant.evaluate_gate(
        ruleset(rule(retrieved_at="not-a-timestamp")), live_authorized=False
    )

    assert (unknown.allowed, unknown.reason) == (False, REASON_UNKNOWN)
    assert (invalid.allowed, invalid.reason) == (False, REASON_INVALID)


# ===========================================================================
# runtime wiring - startup, dispatch, observability
# ===========================================================================


def application(tmp_path, *, execution_mode: str = "PAPER", **policy: Any) -> AtlasApplication:
    return AtlasApplication(
        state_directory=seed_state(tmp_path / "state"),
        execution_mode=execution_mode,
        venue_rule_freshness_policy=(
            VenueRuleFreshnessPolicy(**policy) if policy else None
        ),
    )


def with_venue_bounds(rules: InstrumentRuleset) -> InstrumentRuleset:
    """The shipped rules, given venue upper bounds.

    Block 6B made complete upper bounds a second requirement of live
    authority. These tests are about rule *age*, so the bounds are supplied
    far above anything they trade and never bind: what stays isolated is the
    freshness gate.
    """
    return InstrumentRuleset(
        {
            symbol: replace(
                entry,
                max_quantity=D("1000000"),
                max_notional=D("1000000000"),
                market_max_quantity=D("1000000"),
            )
            for symbol, entry in rules.rules.items()
        },
        schema_version=rules.schema_version,
    )


def live_authorized_manager(tmp_path, *, offset_seconds: int):
    """A runtime holding live authority, with the shipped rules evaluated at a
    fixed distance from their own ``retrieved_at``."""
    app = application(tmp_path, execution_mode="LIVE")
    manager = app.execution
    manager.live_execution_enabled = True
    manager.instrument_rules = with_venue_bounds(app.instrument_ruleset)

    observed = datetime.fromisoformat(
        app.instrument_ruleset.get("BTCUSDT").retrieved_at.replace("Z", "+00:00")
    )
    manager.instrument_rule_freshness = service(
        at=observed + timedelta(seconds=offset_seconds)
    )

    return app, manager


def test_live_authorized_runtime_halts_on_stale_venue_rules(tmp_path) -> None:
    """G. The fail-closed enforcement point that matters: a runtime that can
    actually reach a venue does not come online at all on stale rules."""
    app, manager = live_authorized_manager(tmp_path, offset_seconds=THRESHOLD_SECONDS + 1)

    manager.start()

    assert manager.execution_halted is True
    assert manager.recovery_required is True
    assert manager.halt_reason == REASON_STALE
    assert manager.health()["venue_rules"]["status"] == STATUS.STALE.value


def test_live_authorized_runtime_starts_clean_on_fresh_venue_rules(tmp_path) -> None:
    """H. The same runtime, the same shipped config, in date: no halt. The gate
    discriminates on age, not on live authority alone."""
    app, manager = live_authorized_manager(tmp_path, offset_seconds=3600)

    manager.start()

    assert manager.execution_halted is False
    assert manager.recovery_required is False
    assert manager.halt_reason is None
    assert manager.health()["venue_rules"]["status"] == STATUS.FRESH.value


def test_live_dispatch_refuses_rules_that_went_stale_during_the_run(tmp_path) -> None:
    """G. Rules are immutable for the life of a process; their age is not. A
    long-running live-authorized runtime that crosses the threshold mid-run is
    refused at dispatch, not only at startup."""
    app, manager = live_authorized_manager(tmp_path, offset_seconds=3600)
    manager.start()
    assert manager.execution_halted is False

    request = buy(price="10.00", amount="100", request_id="live-stale-1")
    assert manager.risk_check(request)["approved"] is True

    manager.instrument_rule_freshness = service(
        at=datetime(2027, 1, 1, tzinfo=UTC)
    )

    outcome = manager.live_execute(request)

    assert outcome["success"] is False
    assert outcome["status"] == "VENUE_RULES_NOT_FRESH"
    assert outcome["error_code"] == REASON_STALE
    assert outcome["status"] not in manager.SUCCESS_STATUSES
    assert outcome["data"]["venue_rules"]["status"] == STATUS.STALE.value


def test_bounded_paper_runtime_reports_stale_rules_without_halting(tmp_path) -> None:
    """The paper/bounded contract, end to end through the composition root:
    execution continues, and the staleness is visible on both operational
    surfaces rather than being swallowed."""
    app = application(tmp_path)
    manager = app.execution
    manager.instrument_rule_freshness = service(at=datetime(2027, 1, 1, tzinfo=UTC))

    manager.start()

    assert manager.execution_halted is False
    assert manager.halt_reason is None

    for surface in (manager.health(), manager.status()):
        venue_rules = surface["venue_rules"]
        assert venue_rules["status"] == STATUS.STALE.value
        assert venue_rules["venue"] == "BINANCE"
        assert venue_rules["schema_version"] == INSTRUMENT_RULES_SCHEMA_VERSION
        assert venue_rules["source"] == "https://api.binance.com/api/v3/exchangeInfo"
        assert venue_rules["age_seconds"] > venue_rules["maximum_age_seconds"]
        assert venue_rules["observed_at"] is not None


def test_bounded_paper_runtime_halts_when_policy_withdraws_stale_tolerance(tmp_path) -> None:
    """The policy is load-bearing, not decorative: an operator who sets the
    bounded runtime to require fresh rules gets a runtime that halts."""
    app = application(tmp_path, maximum_age_seconds=60)
    manager = app.execution
    manager.instrument_rule_freshness = service(
        at=datetime(2027, 1, 1, tzinfo=UTC),
        allow_stale_bounded_execution=False,
    )

    manager.start()

    assert manager.execution_halted is True
    assert manager.halt_reason == REASON_STALE


def test_the_composition_root_wires_one_freshness_authority(tmp_path) -> None:
    """The startup gate and the health surface must not be able to disagree
    about how old the rules are, so they share one instance and one policy."""
    app = application(tmp_path, maximum_age_seconds=120)

    assert app.execution.instrument_rule_freshness is app.venue_rule_freshness
    assert app.venue_rule_freshness.policy.maximum_age_seconds == 120
    assert app.execution.health()["venue_rules"]["maximum_age_seconds"] == 120


def test_live_authority_is_the_conjunction_of_mode_and_enablement(tmp_path) -> None:
    """LIVE mode alone is not authority. With live execution disabled no venue
    rule can be acted on however stale it is, which is why the gate keys on
    both and a LIVE-mode paper-safe runtime is not held to the live bar."""
    app = application(tmp_path, execution_mode="LIVE")
    manager = app.execution
    manager.instrument_rule_freshness = service(at=datetime(2027, 1, 1, tzinfo=UTC))

    assert manager.mode == "LIVE"
    assert manager.live_execution_enabled is False
    assert manager.live_authorized is False

    manager.start()

    assert manager.execution_halted is False

    manager.live_execution_enabled = True
    assert manager.live_authorized is True


# ===========================================================================
# J/K/L - what 6A did not change, and did not build
# ===========================================================================


def test_rule_identity_and_quantization_are_unchanged_by_6a() -> None:
    """J. The rule digest seals Block 5D admission and replay identity. Adding
    set-level freshness metadata must not perturb it, so the digest of a fixed
    rule is pinned here: any future schema widening that touches rule identity
    fails this rather than silently invalidating prior admissions."""
    entry = rule(source="test-fixture", source_version="v1")

    assert entry.digest == (
        "dc76a935bf696deb9c0f07d7fdd4ce3bb983c464cea1ebfcf67c64fc85603e5e"
    )

    # Set-level metadata is set-level: it reaches the ruleset, never the rule.
    assert "schema_version" not in entry.to_dict()
    assert ruleset(entry).schema_version == INSTRUMENT_RULES_SCHEMA_VERSION
    assert ruleset(entry).get("BTCUSDT").digest == entry.digest

    # The venue-neutral arithmetic the admission gate runs on is untouched.
    assert floor_to_step(D("0.123456"), D("0.00001")) == D("0.12345")
    assert is_aligned_to_step(D("0.12345"), D("0.00001")) is True
    assert is_aligned_to_step(D("0.123456"), D("0.00001")) is False


def test_the_shipped_config_still_loads_and_now_reports_its_schema() -> None:
    """The checked-in rules stay reproducible: 6A reads provenance the 5D
    schema already carried and adds no required field to the config."""
    shipped = load_instrument_ruleset(DEFAULT_INSTRUMENT_RULES_PATH)

    assert shipped.schema_version == INSTRUMENT_RULES_SCHEMA_VERSION
    assert "BTCUSDT" in shipped.symbols

    # The documented default cadence, pinned: staleness is bounded out of the
    # box, and the bound is the monthly operator re-pull the evidence record
    # commits to rather than an unstated number.
    assert DEFAULT_MAXIMUM_RULE_AGE_SECONDS == 30 * 24 * 60 * 60
    assert (
        VenueRuleFreshnessPolicy().maximum_age_seconds
        == DEFAULT_MAXIMUM_RULE_AGE_SECONDS
    )

    report = service(at=datetime(2026, 8, 19, 18, 0, tzinfo=UTC)).assess(shipped)

    assert report.status is STATUS.FRESH
    assert report.venue == "BINANCE"
    assert report.symbol_count == len(shipped.symbols)


def test_ordinary_rule_validation_and_freshness_touch_no_network(monkeypatch) -> None:
    """K. The financial core must not acquire a live metadata dependency. With
    every socket constructor poisoned, loading, validating, assessing and
    gating the shipped rules all still complete."""

    def refuse(*args: Any, **kwargs: Any):
        raise AssertionError("venue rule validation must not open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    shipped = load_instrument_ruleset(DEFAULT_INSTRUMENT_RULES_PATH)
    frozen = service(at=datetime(2026, 8, 19, 18, 0, tzinfo=UTC))

    assert frozen.assess(shipped).status is STATUS.FRESH
    assert frozen.evaluate_gate(shipped, live_authorized=True).allowed is True


def test_no_refresh_adapter_exists_in_the_freshness_authority() -> None:
    """L. Package 6A deliberately builds no network refresh path: the
    repository has no venue *metadata* seam to build one behind (the Binance
    provider serves prices and candles, not exchangeInfo). This pins that
    decision, so the day a refresh adapter is introduced it must be wired
    through a reviewed boundary rather than appearing inside the freshness
    authority itself."""
    imported = set(vars(freshness_module))

    assert not imported & {"requests", "urllib", "http", "socket", "httpx", "aiohttp"}
    assert not [name for name in imported if "fetch" in name.lower()]
