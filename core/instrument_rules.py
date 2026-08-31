"""Block 5D — venue-neutral instrument precision and provenance contract.

``InstrumentRules`` is the sole authoritative source of venue execution
precision (quantity step, minimum quantity, minimum notional, price tick)
for one symbol. ``InstrumentRuleset`` is an immutable, venue-scoped
collection of them, loaded once at process startup from the checked-in
static ``config/instrument_rules.json`` (owner decision 1) and injected into
``ExecutionManager``, which consumes rules but never constructs, mutates, or
invents an entry.

There is no live ``/exchangeInfo`` fetch and no mid-run refresh: rules are
immutable for the lifetime of one process (owner decision 9). A symbol with
no checked-in rule is not defaulted to a permissive quantum - it is
unexecutable, and every caller in this module and in ``ExecutionManager``
fails closed rather than inventing a value.

How *old* those immutable rules are allowed to be is a separate contract,
held outside this module by ``core.venue_rule_freshness`` (Block 6A). It
reads the provenance defined here and adds no field to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


# The only config schema version this loader accepts. Carried onto the loaded
# ``InstrumentRuleset`` so a runtime can report which rule schema it is
# actually trading on (Block 6A observability) instead of the loader knowing
# it and then discarding it.
INSTRUMENT_RULES_SCHEMA_VERSION = "1.0"

# Every key a ``rules[]`` config entry may carry. ``digest`` is accepted and
# ignored so a ``to_dict()`` round-trip loads, and the three Block 6B upper
# bounds are optional; anything else is a config defect (see
# ``load_instrument_ruleset``).
# The order type ``MARKET_LOT_SIZE`` binds, matching the vocabulary
# ``ExecutionRequest.order_type`` normalizes to.
MARKET_ORDER_TYPE = "MARKET"

# Stable, non-sensitive refusal codes for the Block 6B upper bounds. They
# carry no account, key, or venue-payload information - only which bound was
# exceeded - and they are constants so the admission gate, the SELL gate, and
# operator tooling cannot drift on their spelling.
QUANTITY_ABOVE_VENUE_MAXIMUM = "QUANTITY_ABOVE_VENUE_MAXIMUM"
QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM = "QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM"
NOTIONAL_ABOVE_VENUE_MAXIMUM = "NOTIONAL_ABOVE_VENUE_MAXIMUM"
FULL_EXIT_ABOVE_VENUE_MAXIMUM = "FULL_EXIT_ABOVE_VENUE_MAXIMUM"
VENUE_UPPER_BOUNDS_UNAVAILABLE = "VENUE_UPPER_BOUNDS_UNAVAILABLE"

RULE_CONFIG_KEYS = frozenset(
    {
        "venue",
        "symbol",
        "base_asset",
        "quote_asset",
        "quantity_step",
        "min_quantity",
        "min_notional",
        "price_tick",
        "source",
        "source_version",
        "retrieved_at",
        "max_quantity",
        "max_notional",
        "market_max_quantity",
        "digest",
    }
)


class InstrumentRulesConfigError(ValueError):
    """Raised when a checked-in instrument-rules config is missing, malformed,
    or fails contract validation.

    ``ExecutionManager`` and the composition root treat this uniformly as
    "no rules for this run": every trade-enabled symbol then fails closed at
    startup (``INSTRUMENT_RULES_UNAVAILABLE``) rather than executing against
    an unverified precision.
    """


def _optional_decimal_field(value: Any, name: str) -> Decimal | None:
    """Convert an optional venue bound, or ``None`` when it is not configured.

    Block 6B: the venue *upper* bounds are optional because no verified value
    for them exists in the checked-in config yet, and a fabricated bound is
    worse than an absent one. Absent means "this bound is not modelled for
    this symbol" - which is exactly what a live-authorized runtime refuses to
    trade on (``ExecutionManager`` fails closed on incomplete bounds), and
    what a bounded PAPER runtime carries on with unchanged. A *present* bound
    is validated exactly as strictly as a required one.
    """
    if value is None:
        return None
    return _decimal_field(value, name)


def _decimal_field(value: Any, name: str) -> Decimal:
    """Convert a strictly positive, exact ``Decimal`` financial field.

    Floats are rejected outright: a binary float cannot represent most venue
    step/tick sizes exactly, and this contract's whole purpose is to carry
    them exactly.
    """
    if isinstance(value, bool) or isinstance(value, float):
        raise InstrumentRulesConfigError(
            f"{name} must be a Decimal-compatible non-float value"
        )
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InstrumentRulesConfigError(f"{name} is not a valid decimal") from exc
    if not result.is_finite() or result <= 0:
        raise InstrumentRulesConfigError(f"{name} must be finite and positive")
    return result


def is_aligned_to_step(value: Decimal, step: Decimal) -> bool:
    """True when ``value`` is an exact whole multiple of ``step``.

    Used both for quantity/quantity_step alignment and for price/price_tick
    alignment - the two axes never round, only accept or refuse exactly.
    """
    return value % step == 0


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Floor ``value`` down to the nearest whole multiple of ``step``.

    Rounds toward zero only, under its own ``ROUND_DOWN`` context regardless
    of the caller's ambient one, so a fill can never be sized above what was
    actually approved. Venue-neutral: unlike ``Decimal.quantize``, this works
    for any positive step, not only powers of ten.
    """
    with localcontext() as context:
        context.rounding = ROUND_DOWN
        steps = (value / step).to_integral_value()
    return steps * step


@dataclass(frozen=True, slots=True)
class InstrumentRules:
    """One venue's precision and provenance contract for one symbol.

    ``quantity_step``, ``min_quantity``, ``min_notional`` and ``price_tick``
    are the required authoritative financial fields.

    ``max_quantity`` (``LOT_SIZE.maxQty``), ``max_notional``
    (``NOTIONAL.maxNotional``) and ``market_max_quantity``
    (``MARKET_LOT_SIZE.maxQty``) are the venue's upper bounds (Block 6B,
    readiness gate V1). They are optional in the schema and absent from the
    shipped config, because no verified value for them has been obtained -
    inventing one would be worse than modelling none. Absent means the bound
    is not modelled: a bounded PAPER runtime is unchanged by it, and a
    live-authorized runtime refuses to come online or dispatch at all
    (``VENUE_UPPER_BOUNDS_UNAVAILABLE``). Present means enforced, in every
    mode, at the same fail-closed admission gate that already enforces the
    lower bounds.

    Every production entry must
    trace to a verified venue source: ``source`` and ``retrieved_at`` record
    where and when the authoritative values were confirmed, and ``digest``
    seals all of them so a later change to any one of them is structurally
    detectable and invalidates a prior risk admission (Block 5D RULE
    IDENTITY / REPLAY).
    """

    venue: str
    symbol: str
    base_asset: str
    quote_asset: str
    quantity_step: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    price_tick: Decimal
    source: str
    source_version: str
    retrieved_at: str
    max_quantity: Decimal | None = None
    max_notional: Decimal | None = None
    market_max_quantity: Decimal | None = None
    digest: str = field(init=False, default="")

    def __post_init__(self) -> None:
        venue = str(self.venue).strip().upper()
        symbol = str(self.symbol).strip().upper()
        base_asset = str(self.base_asset).strip().upper()
        quote_asset = str(self.quote_asset).strip().upper()
        source = str(self.source).strip()
        source_version = str(self.source_version).strip()
        retrieved_at = str(self.retrieved_at).strip()

        if not venue:
            raise InstrumentRulesConfigError("venue is required")
        if not symbol:
            raise InstrumentRulesConfigError("symbol is required")
        if not base_asset:
            raise InstrumentRulesConfigError("base_asset is required")
        if not quote_asset:
            raise InstrumentRulesConfigError("quote_asset is required")
        if not source:
            raise InstrumentRulesConfigError("source is required")
        if not source_version:
            raise InstrumentRulesConfigError("source_version is required")
        if not retrieved_at:
            raise InstrumentRulesConfigError("retrieved_at is required")

        quantity_step = _decimal_field(self.quantity_step, "quantity_step")
        min_quantity = _decimal_field(self.min_quantity, "min_quantity")
        min_notional = _decimal_field(self.min_notional, "min_notional")
        price_tick = _decimal_field(self.price_tick, "price_tick")

        if not is_aligned_to_step(min_quantity, quantity_step):
            raise InstrumentRulesConfigError(
                "min_quantity must be an exact multiple of quantity_step"
            )

        max_quantity = _optional_decimal_field(self.max_quantity, "max_quantity")
        max_notional = _optional_decimal_field(self.max_notional, "max_notional")
        market_max_quantity = _optional_decimal_field(
            self.market_max_quantity, "market_max_quantity"
        )

        # A bound that contradicts the matching minimum admits nothing at all:
        # no quantity can be both at or above the minimum and at or below a
        # smaller maximum. That is a defective config, not an empty admission
        # window, so it is refused at load rather than silently rejecting
        # every request at runtime. Upper bounds are deliberately *not*
        # required to be step-aligned: a venue may publish a maximum that is
        # not a whole multiple of its step, and the comparison stays exact
        # either way.
        if max_quantity is not None and max_quantity < min_quantity:
            raise InstrumentRulesConfigError(
                "max_quantity must not be below min_quantity"
            )
        if max_notional is not None and max_notional < min_notional:
            raise InstrumentRulesConfigError(
                "max_notional must not be below min_notional"
            )
        if market_max_quantity is not None and market_max_quantity < min_quantity:
            raise InstrumentRulesConfigError(
                "market_max_quantity must not be below min_quantity"
            )

        object.__setattr__(self, "max_quantity", max_quantity)
        object.__setattr__(self, "max_notional", max_notional)
        object.__setattr__(self, "market_max_quantity", market_max_quantity)

        object.__setattr__(self, "venue", venue)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "base_asset", base_asset)
        object.__setattr__(self, "quote_asset", quote_asset)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_version", source_version)
        object.__setattr__(self, "retrieved_at", retrieved_at)
        object.__setattr__(self, "quantity_step", quantity_step)
        object.__setattr__(self, "min_quantity", min_quantity)
        object.__setattr__(self, "min_notional", min_notional)
        object.__setattr__(self, "price_tick", price_tick)
        object.__setattr__(self, "digest", self._compute_digest())

    def _compute_digest(self) -> str:
        """Seal every field capable of changing execution behaviour.

        Identity (``venue``/``symbol``/``base_asset``/``quote_asset``) is
        included alongside the four authoritative Decimal fields so that a
        rule silently re-pointed at the wrong instrument is also detected,
        not only a changed step or tick. Mirrors
        ``PositionSizingService._inputs_digest``'s canonical-JSON + sha256
        convention (Block 5C).

        Each Decimal field is ``normalize()``-d before serialization (Block
        5D M3 remediation): ``Decimal`` compares two differently-represented
        but economically equal values as equal (``Decimal("5") ==
        Decimal("5.00")``), but their un-normalized ``format(x, "f")``
        strings differ, which previously made the digest sensitive to purely
        cosmetic trailing-zero choices in the checked-in config. Normalizing
        collapses both to the same canonical string
        (``format(Decimal("5.00").normalize(), "f") == "5"``) without
        altering the value carried anywhere else - ``to_dict()`` and every
        execution-path computation still use the field exactly as
        configured.
        """
        canonical = {
            "venue": self.venue,
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "quantity_step": format(self.quantity_step.normalize(), "f"),
            "min_quantity": format(self.min_quantity.normalize(), "f"),
            "min_notional": format(self.min_notional.normalize(), "f"),
            "price_tick": format(self.price_tick.normalize(), "f"),
            "source": self.source,
            "source_version": self.source_version,
            "retrieved_at": self.retrieved_at,
        }

        # Block 6B: an upper bound changes execution behaviour, so it must be
        # sealed like every other authoritative field - publishing a different
        # maxQty has to invalidate a prior admission. It is added to the
        # canonical payload only when it is *present*, so a rule that models
        # no upper bound hashes to exactly the digest it had before 6B
        # existed. Adding a bound to a symbol therefore changes that symbol's
        # identity (correct: its admission window changed) while leaving every
        # unbounded symbol's prior admissions and evidence intact.
        for name in ("max_quantity", "max_notional", "market_max_quantity"):
            bound = getattr(self, name)
            if bound is not None:
                canonical[name] = format(bound.normalize(), "f")

        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def upper_bound_violation(
        self,
        *,
        base_quantity: Decimal,
        quote_notional: Decimal,
        order_type: str = MARKET_ORDER_TYPE,
    ) -> tuple[str, dict[str, str]] | None:
        """Return the venue upper bound this order breaks, or ``None``.

        The single derivation both venue-bound gates use - the new-risk BUY
        admission check in ``ExecutionManager.risk_check`` and the SELL
        reduction check in ``_resolve_reduction_quantity`` - so the two can
        never drift apart on what "too large" means, exactly as they already
        share ``_resolve_base_fill`` for what a fill is.

        Comparisons are strict (``>``): a quantity or notional exactly *at*
        the venue maximum is admissible, because the venue itself accepts it.
        They are also plain ``Decimal`` comparisons, never a subtraction or a
        ratio, so no arithmetic context can round two distinguishable values
        into one.

        An unmodelled bound is skipped rather than defaulted: whether that
        absence is tolerable is a runtime authority question
        (``ExecutionManager`` refuses it under live authority), not something
        a rule can answer about itself.

        ``MARKET_LOT_SIZE`` binds market orders only, which is what makes it
        distinct from ``LOT_SIZE``; ``order_type`` is compared case- and
        whitespace-insensitively against the same ``MARKET`` vocabulary
        ``ExecutionRequest`` normalizes to.
        """
        if self.max_quantity is not None and base_quantity > self.max_quantity:
            return (
                QUANTITY_ABOVE_VENUE_MAXIMUM,
                {
                    "base_quantity": format(base_quantity, "f"),
                    "max_quantity": format(self.max_quantity, "f"),
                },
            )

        if (
            self.market_max_quantity is not None
            and str(order_type).strip().upper() == MARKET_ORDER_TYPE
            and base_quantity > self.market_max_quantity
        ):
            return (
                QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM,
                {
                    "base_quantity": format(base_quantity, "f"),
                    "market_max_quantity": format(self.market_max_quantity, "f"),
                    "order_type": MARKET_ORDER_TYPE,
                },
            )

        if self.max_notional is not None and quote_notional > self.max_notional:
            return (
                NOTIONAL_ABOVE_VENUE_MAXIMUM,
                {
                    "quote_notional": format(quote_notional, "f"),
                    "max_notional": format(self.max_notional, "f"),
                },
            )

        return None

    @property
    def has_complete_venue_bounds(self) -> bool:
        """True when every Block 6B upper bound is modelled for this symbol.

        Completeness is all three or none of the safety they provide: a rule
        that bounds quantity but not notional still admits an order the venue
        would refuse. This is what a live-authorized runtime requires before
        it may come online or dispatch.
        """
        return (
            self.max_quantity is not None
            and self.max_notional is not None
            and self.market_max_quantity is not None
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize with every Decimal field as an exact decimal string.

        An unmodelled upper bound is *omitted* rather than serialized as
        null, so the shipped config's on-disk shape is unchanged and a
        round-trip through this method reproduces the same digest.
        """
        payload = {
            "venue": self.venue,
            "symbol": self.symbol,
            "base_asset": self.base_asset,
            "quote_asset": self.quote_asset,
            "quantity_step": format(self.quantity_step, "f"),
            "min_quantity": format(self.min_quantity, "f"),
            "min_notional": format(self.min_notional, "f"),
            "price_tick": format(self.price_tick, "f"),
            "source": self.source,
            "source_version": self.source_version,
            "retrieved_at": self.retrieved_at,
        }

        for name in ("max_quantity", "max_notional", "market_max_quantity"):
            bound = getattr(self, name)
            if bound is not None:
                payload[name] = format(bound, "f")

        payload["digest"] = self.digest
        return payload


@dataclass(frozen=True, slots=True)
class InstrumentRuleset:
    """An immutable, venue-scoped collection of :class:`InstrumentRules`.

    Loaded once at process startup and injected into ``ExecutionManager``.
    Lookup is by symbol only: this runtime trades on one configured venue at
    a time, so the ruleset itself is that venue's scope, while each entry
    still carries its own ``venue`` field for identity and evidence.

    ``schema_version`` is the config schema the entries were loaded under. It
    is set-level metadata, deliberately *not* a field of ``InstrumentRules``:
    the per-rule ``digest`` seals execution-affecting values only, and Block
    6A must not perturb the rule identity Block 5D admission and replay
    already depend on.
    """

    rules: Mapping[str, InstrumentRules]
    schema_version: str = INSTRUMENT_RULES_SCHEMA_VERSION

    def __post_init__(self) -> None:
        schema_version = str(self.schema_version).strip()
        if not schema_version:
            raise InstrumentRulesConfigError("schema_version is required")
        object.__setattr__(self, "schema_version", schema_version)

        normalized: dict[str, InstrumentRules] = {}
        for key, entry in self.rules.items():
            if not isinstance(entry, InstrumentRules):
                raise InstrumentRulesConfigError(
                    "InstrumentRuleset entries must be InstrumentRules"
                )
            normalized_key = str(key).strip().upper()
            if normalized_key != entry.symbol:
                raise InstrumentRulesConfigError(
                    f"ruleset key {normalized_key!r} does not match rule "
                    f"symbol {entry.symbol!r}"
                )
            if normalized_key in normalized:
                raise InstrumentRulesConfigError(
                    f"duplicate instrument rule for symbol {normalized_key!r}"
                )
            normalized[normalized_key] = entry
        object.__setattr__(self, "rules", MappingProxyType(normalized))

    def get(self, symbol: str) -> InstrumentRules | None:
        """Return the rule for ``symbol``, or ``None`` if it is unconfigured."""
        return self.rules.get(str(symbol).strip().upper())

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self.rules))


def load_instrument_ruleset(path: str | Path) -> InstrumentRuleset:
    """Load the checked-in static instrument-rules config (owner decision 1).

    This is the sole canonical authority for venue instrument precision in
    Package 5D: no live ``/exchangeInfo`` fetch, no fallback quantum. A
    missing file, malformed JSON, or a schema/contract violation all raise
    ``InstrumentRulesConfigError`` uniformly, which the composition root
    treats as "no rules for this run" rather than repairing or defaulting it.
    """
    resolved = Path(path)
    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstrumentRulesConfigError(
            f"instrument rules config unavailable: {resolved}"
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstrumentRulesConfigError(
            f"instrument rules config is not valid JSON: {resolved}"
        ) from exc

    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != INSTRUMENT_RULES_SCHEMA_VERSION
    ):
        raise InstrumentRulesConfigError(
            "instrument rules config must be a JSON object with schema_version "
            f"{INSTRUMENT_RULES_SCHEMA_VERSION!r}"
        )

    entries = payload.get("rules")
    if not isinstance(entries, list) or not entries:
        raise InstrumentRulesConfigError(
            "instrument rules config must contain a non-empty 'rules' array"
        )

    rules: dict[str, InstrumentRules] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise InstrumentRulesConfigError(f"rules[{index}] must be an object")

        # An unrecognised key is refused rather than ignored. The Block 6B
        # upper bounds are optional, so a misspelled ``max_quanttiy`` would
        # otherwise read as "this venue has no maximum" - the exact silent
        # weakening this gate exists to prevent.
        unknown = sorted(set(entry) - RULE_CONFIG_KEYS)
        if unknown:
            raise InstrumentRulesConfigError(
                f"rules[{index}] has unrecognised fields: {', '.join(unknown)}"
            )

        try:
            rule = InstrumentRules(
                venue=entry["venue"],
                symbol=entry["symbol"],
                base_asset=entry["base_asset"],
                quote_asset=entry["quote_asset"],
                quantity_step=entry["quantity_step"],
                min_quantity=entry["min_quantity"],
                min_notional=entry["min_notional"],
                price_tick=entry["price_tick"],
                source=entry["source"],
                source_version=entry["source_version"],
                retrieved_at=entry["retrieved_at"],
                max_quantity=entry.get("max_quantity"),
                max_notional=entry.get("max_notional"),
                market_max_quantity=entry.get("market_max_quantity"),
            )
        except KeyError as exc:
            raise InstrumentRulesConfigError(
                f"rules[{index}] missing required field: {exc}"
            ) from exc

        if rule.symbol in rules:
            raise InstrumentRulesConfigError(
                f"duplicate instrument rule for symbol {rule.symbol!r}"
            )
        rules[rule.symbol] = rule

    return InstrumentRuleset(
        rules,
        schema_version=str(payload["schema_version"]),
    )
