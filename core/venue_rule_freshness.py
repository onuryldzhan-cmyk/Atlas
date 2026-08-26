"""Block 6A — venue instrument-rule freshness and staleness safety.

Package 5D made the checked-in ``config/instrument_rules.json`` the sole,
process-immutable venue precision authority and recorded limitation M2:
``retrieved_at`` was validated as present and non-empty, but *nothing bounded
how old a checked-in rule could be*. A venue tightening a ``stepSize`` /
``tickSize`` / ``minNotional`` after that timestamp was undetectable until an
operator happened to re-pull ``exchangeInfo``. This module closes that gate.

Three properties are deliberate:

**The static rules stay the deterministic baseline.** Nothing here fetches,
mutates, or refreshes a rule. Freshness is derived from provenance the 5D
schema already carries (``venue`` / ``source`` / ``source_version`` /
``retrieved_at``), so the shipped config remains byte-reproducible and every
rule ``digest`` — the seal Block 5D admission and replay identity depend on —
is unchanged by this package.

**The clock is injected.** ``VenueRuleFreshnessService`` takes its time source
as a constructor argument. The financial core never reads an ambient
``datetime.now()`` to decide freshness: the composition root owns the clock,
and a test owns it exactly the same way.

**Evaluation fails closed.** A provenance timestamp that cannot be parsed, is
not timezone-aware, or claims a moment in the future beyond a bounded skew is
``INVALID`` — never silently treated as fresh. An absent ruleset is
``UNKNOWN``. Neither can pass the live-readiness gate, and neither is
downgraded into "probably fine".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Callable

from core.instrument_rules import InstrumentRuleset


# The operator refresh cadence for the checked-in static rules, in seconds.
#
# The repository has no automated refresh mechanism (Package 6A deliberately
# does not build one, see the evidence record), so this default is the
# cadence an operator can actually meet by hand: a monthly re-pull of
# ``exchangeInfo`` into ``config/instrument_rules.json``. It bounds staleness
# rather than leaving it unbounded, which is the whole of the 5D M2 gap. It
# is configuration, not a constant of nature: the composition root accepts a
# policy, and this threshold should be tightened the day a validated refresh
# adapter makes a shorter cadence achievable.
DEFAULT_MAXIMUM_RULE_AGE_SECONDS = 30 * 24 * 60 * 60

# A checked-in artifact should never be dated after the runtime's own clock.
# A small allowance absorbs genuine skew between the operator machine that
# produced the config and the machine running it; anything beyond it is a
# provenance defect, not skew.
DEFAULT_FUTURE_SKEW_SECONDS = 300


class VenueRuleFreshnessStatus(str, Enum):
    """The four states a runtime can be in with respect to venue rule age."""

    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


# Gate refusal reasons. Distinct per status: an operator resolving STALE
# re-pulls the config, while INVALID means the config they already have is
# malformed and re-pulling may not help.
REASON_STALE = "VENUE_RULES_STALE"
REASON_UNKNOWN = "VENUE_RULES_FRESHNESS_UNKNOWN"
REASON_INVALID = "VENUE_RULES_PROVENANCE_INVALID"

_STATUS_REASONS: dict[VenueRuleFreshnessStatus, str] = {
    VenueRuleFreshnessStatus.STALE: REASON_STALE,
    VenueRuleFreshnessStatus.UNKNOWN: REASON_UNKNOWN,
    VenueRuleFreshnessStatus.INVALID: REASON_INVALID,
}

_MIXED = "MIXED"


class VenueRuleFreshnessPolicyError(ValueError):
    """Raised when a freshness policy itself is not usable.

    A policy that cannot be trusted is not silently replaced by a default:
    constructing it fails, at the composition root, before any runtime
    decision is taken against it.
    """


def _positive_int(value: Any, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise VenueRuleFreshnessPolicyError(f"{name} must be an int")
    if value < minimum:
        raise VenueRuleFreshnessPolicyError(f"{name} must be >= {minimum}")
    return value


def utc_now() -> datetime:
    """The default runtime clock.

    Exists so the ambient wall clock is read in exactly one named place that
    a composition root or a test can substitute wholesale.
    """
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class VenueRuleFreshnessPolicy:
    """The explicit, injectable freshness policy for one runtime.

    ``allow_stale_bounded_execution`` is the one deliberate asymmetry between
    PAPER/bounded execution and live-authorized execution. A bounded run
    against stale static rules cannot lose money — the paper book is the only
    thing it moves — so it continues rather than halting, but it continues
    *loudly*: the status is reported as STALE on every health and status
    surface. Setting it ``False`` makes a bounded runtime halt on stale rules
    too. There is no equivalent switch for live authority: live requires
    FRESH, always.
    """

    maximum_age_seconds: int = DEFAULT_MAXIMUM_RULE_AGE_SECONDS
    future_skew_seconds: int = DEFAULT_FUTURE_SKEW_SECONDS
    allow_stale_bounded_execution: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "maximum_age_seconds",
            _positive_int(self.maximum_age_seconds, "maximum_age_seconds", minimum=1),
        )
        object.__setattr__(
            self,
            "future_skew_seconds",
            _positive_int(self.future_skew_seconds, "future_skew_seconds", minimum=0),
        )
        if not isinstance(self.allow_stale_bounded_execution, bool):
            raise VenueRuleFreshnessPolicyError(
                "allow_stale_bounded_execution must be a bool"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "maximum_age_seconds": self.maximum_age_seconds,
            "future_skew_seconds": self.future_skew_seconds,
            "allow_stale_bounded_execution": self.allow_stale_bounded_execution,
        }


@dataclass(frozen=True, slots=True)
class VenueRuleFreshnessReport:
    """One deterministic freshness evaluation of one ruleset.

    Every field here is operational observability — venue identity, schema
    version, the age actually measured, and the threshold it was measured
    against. No raw venue payload and no secret is carried: ``source`` is the
    public endpoint identity already checked into the config.
    """

    status: VenueRuleFreshnessStatus
    venue: str | None
    schema_version: str | None
    symbol_count: int
    source: str | None
    source_version: str | None
    observed_at: str | None
    age_seconds: int | None
    maximum_age_seconds: int
    evaluated_at: str
    reason: str | None

    @property
    def is_fresh(self) -> bool:
        return self.status is VenueRuleFreshnessStatus.FRESH

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "venue": self.venue,
            "schema_version": self.schema_version,
            "symbol_count": self.symbol_count,
            "source": self.source,
            "source_version": self.source_version,
            "observed_at": self.observed_at,
            "age_seconds": self.age_seconds,
            "maximum_age_seconds": self.maximum_age_seconds,
            "evaluated_at": self.evaluated_at,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class VenueRuleGateDecision:
    """The outcome of asking whether a runtime may execute on these rules."""

    allowed: bool
    reason: str | None
    live_authorized: bool
    report: VenueRuleFreshnessReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "live_authorized": self.live_authorized,
            "freshness": self.report.to_dict(),
        }


def _parse_provenance_timestamp(raw: str) -> datetime | None:
    """Parse one ``retrieved_at`` value, or ``None`` if it is not usable.

    Timezone-aware only. A naive timestamp is refused rather than assumed to
    be UTC: guessing the offset of a provenance stamp is exactly the kind of
    silent assumption this gate exists to remove.
    """
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith(("z", "Z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _common_value(values: list[str]) -> str | None:
    """The single shared value of a field across a ruleset, or ``MIXED``."""
    unique = set(values)
    if not unique:
        return None
    if len(unique) == 1:
        return unique.pop()
    return _MIXED


class VenueRuleFreshnessService:
    """The reusable venue-rule freshness authority.

    One instance is built by the composition root and shared by everything
    that needs to know how old the venue rules are: ``ExecutionManager``'s
    startup gate, its health/status surfaces, and any future runtime or
    control surface that has to decide whether venue rules are good enough to
    trade on. It holds no mutable state, so evaluating it twice with the same
    clock yields the same answer.
    """

    def __init__(
        self,
        policy: VenueRuleFreshnessPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._policy = policy if policy is not None else VenueRuleFreshnessPolicy()
        self._clock = clock if clock is not None else utc_now

    @property
    def policy(self) -> VenueRuleFreshnessPolicy:
        return self._policy

    def now(self) -> datetime:
        """The injected clock, validated to be timezone-aware."""
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise VenueRuleFreshnessPolicyError(
                "freshness clock must return a timezone-aware datetime"
            )
        return value.astimezone(UTC)

    def assess(self, ruleset: InstrumentRuleset | None) -> VenueRuleFreshnessReport:
        """Evaluate one ruleset's freshness against the injected clock.

        The *oldest* provenance timestamp in the ruleset decides the age:
        freshness is a property of the whole set a runtime trades on, so one
        rule left behind by a partial operator update makes the set stale
        rather than being averaged away.
        """
        now = self.now()
        evaluated_at = now.isoformat()
        threshold = self._policy.maximum_age_seconds

        if ruleset is None or not ruleset.rules:
            return VenueRuleFreshnessReport(
                status=VenueRuleFreshnessStatus.UNKNOWN,
                venue=None,
                schema_version=None if ruleset is None else ruleset.schema_version,
                symbol_count=0,
                source=None,
                source_version=None,
                observed_at=None,
                age_seconds=None,
                maximum_age_seconds=threshold,
                evaluated_at=evaluated_at,
                reason=REASON_UNKNOWN,
            )

        entries = [ruleset.rules[symbol] for symbol in ruleset.symbols]
        venue = _common_value([entry.venue for entry in entries])
        source = _common_value([entry.source for entry in entries])
        source_version = _common_value([entry.source_version for entry in entries])

        def invalid(reason_detail: str) -> VenueRuleFreshnessReport:
            return VenueRuleFreshnessReport(
                status=VenueRuleFreshnessStatus.INVALID,
                venue=venue,
                schema_version=ruleset.schema_version,
                symbol_count=len(entries),
                source=source,
                source_version=source_version,
                observed_at=None,
                age_seconds=None,
                maximum_age_seconds=threshold,
                evaluated_at=evaluated_at,
                reason=reason_detail,
            )

        # A ruleset spanning several venues has no single venue freshness to
        # report, and this runtime trades one venue at a time. Refuse rather
        # than pick one.
        if venue == _MIXED:
            return invalid(REASON_INVALID)

        oldest: datetime | None = None
        for entry in entries:
            parsed = _parse_provenance_timestamp(entry.retrieved_at)
            if parsed is None:
                return invalid(REASON_INVALID)
            if parsed > now + timedelta(seconds=self._policy.future_skew_seconds):
                return invalid(REASON_INVALID)
            if oldest is None or parsed < oldest:
                oldest = parsed

        assert oldest is not None  # entries is non-empty and all parsed

        # A timestamp inside the allowed future skew is treated as "now"
        # rather than a negative age, so the reported age is never absurd.
        age_seconds = max(0, int((now - oldest).total_seconds()))

        # Exactly at the threshold is still FRESH: the policy states the
        # maximum age a rule may have, and a rule of exactly that age has not
        # exceeded it. The boundary is closed on the fresh side so the same
        # input never straddles two answers.
        status = (
            VenueRuleFreshnessStatus.FRESH
            if age_seconds <= threshold
            else VenueRuleFreshnessStatus.STALE
        )

        return VenueRuleFreshnessReport(
            status=status,
            venue=venue,
            schema_version=ruleset.schema_version,
            symbol_count=len(entries),
            source=source,
            source_version=source_version,
            observed_at=oldest.isoformat(),
            age_seconds=age_seconds,
            maximum_age_seconds=threshold,
            evaluated_at=evaluated_at,
            reason=None if status is VenueRuleFreshnessStatus.FRESH else REASON_STALE,
        )

    def evaluate_gate(
        self,
        ruleset: InstrumentRuleset | None,
        *,
        live_authorized: bool,
    ) -> VenueRuleGateDecision:
        """Decide whether a runtime may execute against ``ruleset``.

        ``live_authorized`` is the caller's statement that this runtime can
        actually reach a venue with real capital. When it is true, only FRESH
        passes — STALE, UNKNOWN and INVALID all fail closed. When it is false
        (PAPER / bounded deterministic execution) STALE passes only if the
        policy explicitly allows it, and UNKNOWN / INVALID still fail closed:
        rules whose provenance cannot be evaluated at all are never a
        fallback to unconstrained execution.
        """
        report = self.assess(ruleset)
        status = report.status

        if status is VenueRuleFreshnessStatus.FRESH:
            return VenueRuleGateDecision(
                allowed=True,
                reason=None,
                live_authorized=bool(live_authorized),
                report=report,
            )

        allowed = (
            not live_authorized
            and status is VenueRuleFreshnessStatus.STALE
            and self._policy.allow_stale_bounded_execution
        )

        return VenueRuleGateDecision(
            allowed=allowed,
            reason=None if allowed else _STATUS_REASONS[status],
            live_authorized=bool(live_authorized),
            report=report,
        )
