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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class InstrumentRulesConfigError(ValueError):
    """Raised when a checked-in instrument-rules config is missing, malformed,
    or fails contract validation.

    ``ExecutionManager`` and the composition root treat this uniformly as
    "no rules for this run": every trade-enabled symbol then fails closed at
    startup (``INSTRUMENT_RULES_UNAVAILABLE``) rather than executing against
    an unverified precision.
    """


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
    are the only authoritative financial fields. Every production entry must
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
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Serialize with every Decimal field as an exact decimal string."""
        return {
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
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class InstrumentRuleset:
    """An immutable, venue-scoped collection of :class:`InstrumentRules`.

    Loaded once at process startup and injected into ``ExecutionManager``.
    Lookup is by symbol only: this runtime trades on one configured venue at
    a time, so the ruleset itself is that venue's scope, while each entry
    still carries its own ``venue`` field for identity and evidence.
    """

    rules: Mapping[str, InstrumentRules]

    def __post_init__(self) -> None:
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

    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
        raise InstrumentRulesConfigError(
            "instrument rules config must be a JSON object with schema_version '1.0'"
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

    return InstrumentRuleset(rules)
