"""
============================================================
ATLAS VENUE METADATA ADAPTER (Block 6C)
============================================================

Explicit, operator-invoked boundary that turns a venue ``exchangeInfo``
snapshot into a validated, atomically published ``InstrumentRuleset``
carrying the Block 6B venue maxima and full provenance.

This tool is never called by AtlasApplication. Nothing in the runtime closure
imports it, and it is not part of the financial core: the core continues to
read a static, checked-in ruleset and knows nothing about where a published
one came from. That separation is the Block 6A finding restated - venue
metadata acquisition must live behind a reviewed boundary, not inside the
component that decides whether an order may execute.

What it guarantees
------------------
**No unvalidated write path.** A publication is transformed, constructed
through ``InstrumentRules`` (which enforces every 5D/6B field and
contradiction rule), serialized, written to a temporary file, and then
*re-loaded through the runtime's own* ``load_instrument_ruleset`` and
re-validated. Only then is the destination replaced. A payload that fails any
step reaches the destination in no form at all.

**Atomic publication.** The destination is replaced with ``os.replace`` after
the temporary file is fsynced, mirroring the durable-store convention already
used by ``FinancialStateStore``. There is no partial or torn update: a reader
sees either the previous ruleset or the new one.

**Previous known-good preserved.** Validation happens before the destination
is touched, so a failed publication leaves the existing ruleset byte-identical
and removes its own temporary file.

**Fail-closed on incomplete bounds.** A symbol whose ``exchangeInfo`` does not
carry every bound this contract requires - including a venue that publishes
``0`` to mean "unlimited" - is refused by name rather than published with a
missing or invented maximum. This is the same posture Block 6B took: an
unmodelled maximum fails closed under live authority and changes nothing for
bounded PAPER execution.

**No network transport.** This module opens no socket. It reads an
``exchangeInfo`` snapshot the operator supplies as a file, and records how it
arrived. A future HTTP transport may be added behind ``ExchangeInfoSnapshot``
without changing anything below it - and, deliberately, without the financial
core gaining a network dependency either way. Because the transport is not
authenticated here, the published provenance never claims the payload was
verified; it records exactly what is known.

It has no LIVE authority. It cannot enable live execution, cannot write the
checked-in ``config/instrument_rules.json``, and cannot alter runtime state.
Publishing a ruleset does not make Atlas load it: wiring a runtime to a
published artifact is a separate, explicit operator action.
============================================================
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from core.instrument_rules import (  # noqa: E402
    INSTRUMENT_RULES_SCHEMA_VERSION,
    InstrumentRules,
    InstrumentRulesConfigError,
    InstrumentRuleset,
    load_instrument_ruleset,
)
from core.venue_rule_freshness import (  # noqa: E402
    VenueRuleFreshnessService,
    VenueRuleFreshnessStatus,
)

ADAPTER_VERSION = "6C.1"

# The checked-in ruleset. Read only, and only to learn which symbols a
# publication should cover; this tool never writes it.
REFERENCE_CONFIG_PATH = _REPOSITORY_ROOT / "config" / "instrument_rules.json"

DEFAULT_PUBLISHED_FILENAME = "instrument_rules.published.json"

# The transport that actually delivered the payload. Recorded in provenance
# so a reader can tell an operator-supplied file from anything else. No
# authenticated transport exists yet, hence the explicit verification status.
TRANSPORT_FILE = "OPERATOR_SUPPLIED_FILE"
VERIFICATION_UNVERIFIED_TRANSPORT = "OPERATOR_SUPPLIED_SNAPSHOT_UNVERIFIED_TRANSPORT"

# Venue symbol states this adapter will publish. A symbol the venue is not
# currently trading is not an executable instrument, whatever its filters say.
TRADING_STATUS = "TRADING"


class VenueMetadataError(RuntimeError):
    """Raised when a snapshot cannot be turned into a publishable ruleset.

    Every failure path in this module raises this and publishes nothing. The
    message names the symbol and the field at fault so an operator can act on
    it without reading the payload back by hand.
    """


@dataclass(frozen=True, slots=True)
class ExchangeInfoSnapshot:
    """One venue metadata payload plus how it reached this process.

    ``digest`` seals the exact bytes that were parsed, so a published artifact
    can be traced back to the snapshot that produced it.
    """

    payload: dict[str, Any]
    origin: str
    transport: str
    digest: str
    verification_status: str

    @property
    def server_time_ms(self) -> int:
        raw = self.payload.get("serverTime")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise VenueMetadataError("exchangeInfo payload has no usable serverTime")
        return raw

    @property
    def server_time(self) -> datetime:
        return datetime.fromtimestamp(self.server_time_ms / 1000, UTC)


@dataclass(frozen=True, slots=True)
class PublicationReport:
    """What a publication did, for the operator and for the evidence record."""

    destination: str
    venue: str
    symbols: tuple[str, ...]
    source: str
    source_version: str
    retrieved_at: str
    published_at: str
    payload_digest: str
    verification_status: str
    freshness_status: str
    replaced_existing: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "venue": self.venue,
            "symbols": list(self.symbols),
            "source": self.source,
            "source_version": self.source_version,
            "retrieved_at": self.retrieved_at,
            "published_at": self.published_at,
            "payload_digest": self.payload_digest,
            "verification_status": self.verification_status,
            "freshness_status": self.freshness_status,
            "replaced_existing": self.replaced_existing,
            "adapter_version": ADAPTER_VERSION,
        }


# ---------------------------------------------------------------------------
# transport boundary
# ---------------------------------------------------------------------------


def load_exchange_info_snapshot(path: str | Path) -> ExchangeInfoSnapshot:
    """Read an operator-supplied ``exchangeInfo`` snapshot from disk.

    The only transport this adapter implements. It opens no socket: the
    operator obtains the payload however they already do and hands the file
    over, which keeps the acquisition step auditable and this module offline.
    """
    resolved = Path(path)

    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise VenueMetadataError(f"exchangeInfo snapshot unavailable: {resolved}") from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VenueMetadataError(f"exchangeInfo snapshot is not valid JSON: {resolved}") from exc

    if not isinstance(payload, dict):
        raise VenueMetadataError("exchangeInfo snapshot must be a JSON object")

    return ExchangeInfoSnapshot(
        payload=payload,
        origin=str(resolved),
        transport=TRANSPORT_FILE,
        digest=hashlib.sha256(raw).hexdigest(),
        verification_status=VERIFICATION_UNVERIFIED_TRANSPORT,
    )


# ---------------------------------------------------------------------------
# transform
# ---------------------------------------------------------------------------


def _filters_by_type(entry: dict[str, Any], symbol: str) -> dict[str, dict[str, Any]]:
    filters = entry.get("filters")
    if not isinstance(filters, list):
        raise VenueMetadataError(f"{symbol}: exchangeInfo entry has no filters array")

    resolved: dict[str, dict[str, Any]] = {}
    for item in filters:
        if isinstance(item, dict) and isinstance(item.get("filterType"), str):
            resolved[item["filterType"]] = item
    return resolved


def _bound(
    filters: dict[str, dict[str, Any]],
    *,
    filter_type: str,
    field: str,
    symbol: str,
) -> str:
    """Read one required numeric bound, refusing every way it can be absent.

    A venue that publishes ``0`` means "no limit on this axis". That is not a
    number this contract can carry: ``InstrumentRules`` models a bound as a
    positive Decimal and has no representation for "explicitly unbounded". It
    is refused by name rather than dropped - dropping it would publish a rule
    whose maximum is silently unmodelled, which is exactly the state Block 6B
    made a live runtime fail closed on.
    """
    venue_filter = filters.get(filter_type)
    if venue_filter is None:
        raise VenueMetadataError(f"{symbol}: exchangeInfo has no {filter_type} filter")

    raw = venue_filter.get(field)
    if raw is None:
        raise VenueMetadataError(f"{symbol}: {filter_type} has no {field}")
    if isinstance(raw, float):
        raise VenueMetadataError(
            f"{symbol}: {filter_type}.{field} is a float and cannot be carried exactly"
        )

    text = str(raw).strip()
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise VenueMetadataError(f"{symbol}: {filter_type}.{field} is not a decimal") from exc

    if not value.is_finite() or value <= 0:
        raise VenueMetadataError(
            f"{symbol}: {filter_type}.{field} is {text}, which this contract cannot "
            "represent (a venue publishes 0 to mean unlimited); refusing to publish "
            "an unmodelled maximum"
        )

    return text


def build_ruleset_from_exchange_info(
    snapshot: ExchangeInfoSnapshot,
    *,
    venue: str,
    symbols: Iterable[str],
    source: str,
    retrieved_at: datetime,
) -> InstrumentRuleset:
    """Transform a snapshot into canonical rules, or refuse.

    Every requested symbol must be present, trading, and carry a complete set
    of bounds. Nothing is defaulted and nothing partial is returned: this
    either produces a ruleset in which every entry satisfies
    ``has_complete_venue_bounds``, or it raises.

    ``source_version`` is the payload's ``serverTime`` and ``retrieved_at`` is
    when the operator observed it - the same two-timestamp convention the
    checked-in config already uses, where ``retrieved_at`` sits slightly after
    the ``serverTime`` it recorded.
    """
    wanted = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    if not wanted:
        raise VenueMetadataError("no symbols requested")

    if retrieved_at.tzinfo is None:
        raise VenueMetadataError("retrieved_at must be timezone-aware")

    server_time = snapshot.server_time
    observed = retrieved_at.astimezone(UTC)
    if observed < server_time:
        raise VenueMetadataError(
            "retrieved_at precedes the payload's serverTime; an observation "
            "cannot predate what it observed"
        )

    entries = snapshot.payload.get("symbols")
    if not isinstance(entries, list) or not entries:
        raise VenueMetadataError("exchangeInfo payload has no symbols array")

    by_symbol: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("symbol"), str):
            by_symbol[entry["symbol"].strip().upper()] = entry

    source_version = str(snapshot.server_time_ms)
    stamp = observed.strftime("%Y-%m-%dT%H:%M:%SZ")

    rules: dict[str, InstrumentRules] = {}
    for symbol in wanted:
        entry = by_symbol.get(symbol)
        if entry is None:
            raise VenueMetadataError(f"{symbol}: not present in the exchangeInfo snapshot")

        status = str(entry.get("status", "")).strip().upper()
        if status != TRADING_STATUS:
            raise VenueMetadataError(
                f"{symbol}: venue status is {status or 'UNKNOWN'}, not {TRADING_STATUS}"
            )

        filters = _filters_by_type(entry, symbol)

        try:
            rule = InstrumentRules(
                venue=venue,
                symbol=symbol,
                base_asset=entry["baseAsset"],
                quote_asset=entry["quoteAsset"],
                quantity_step=_bound(filters, filter_type="LOT_SIZE", field="stepSize", symbol=symbol),
                min_quantity=_bound(filters, filter_type="LOT_SIZE", field="minQty", symbol=symbol),
                min_notional=_bound(filters, filter_type="NOTIONAL", field="minNotional", symbol=symbol),
                price_tick=_bound(filters, filter_type="PRICE_FILTER", field="tickSize", symbol=symbol),
                source=source,
                source_version=source_version,
                retrieved_at=stamp,
                max_quantity=_bound(filters, filter_type="LOT_SIZE", field="maxQty", symbol=symbol),
                max_notional=_bound(filters, filter_type="NOTIONAL", field="maxNotional", symbol=symbol),
                market_max_quantity=_bound(
                    filters, filter_type="MARKET_LOT_SIZE", field="maxQty", symbol=symbol
                ),
            )
        except KeyError as exc:
            raise VenueMetadataError(f"{symbol}: exchangeInfo entry missing {exc}") from exc
        except InstrumentRulesConfigError as exc:
            # 5D/6B validation - exactness, positivity, step alignment, and a
            # maximum that contradicts its own minimum - all land here.
            raise VenueMetadataError(f"{symbol}: rejected by the rule contract: {exc}") from exc

        if not rule.has_complete_venue_bounds:  # pragma: no cover - defensive
            raise VenueMetadataError(f"{symbol}: venue bounds are incomplete after transform")

        rules[symbol] = rule

    return InstrumentRuleset(rules, schema_version=INSTRUMENT_RULES_SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# publication
# ---------------------------------------------------------------------------


def _artifact(
    ruleset: InstrumentRuleset,
    *,
    snapshot: ExchangeInfoSnapshot,
    venue: str,
    source: str,
    retrieved_at: datetime,
    published_at: datetime,
) -> dict[str, Any]:
    """The published document: a config the runtime's loader accepts, plus
    provenance describing where it came from and how far it was verified."""
    return {
        "schema_version": INSTRUMENT_RULES_SCHEMA_VERSION,
        "provenance": {
            "adapter_version": ADAPTER_VERSION,
            "venue": venue.strip().upper(),
            "source": source,
            "source_version": str(snapshot.server_time_ms),
            "server_time": snapshot.server_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "retrieved_at": retrieved_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "published_at": published_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "transport": snapshot.transport,
            "snapshot_origin": snapshot.origin,
            "payload_digest": snapshot.digest,
            "verification_status": snapshot.verification_status,
            "symbol_count": len(ruleset.symbols),
            "venue_upper_bounds_modelled": True,
        },
        "rules": [ruleset.rules[symbol].to_dict() for symbol in ruleset.symbols],
    }


def publish_venue_rules(
    *,
    snapshot: ExchangeInfoSnapshot,
    destination: str | Path,
    venue: str,
    symbols: Iterable[str],
    source: str,
    retrieved_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
    freshness: VenueRuleFreshnessService | None = None,
) -> PublicationReport:
    """Validate a snapshot completely, then replace ``destination`` atomically.

    The order of operations is the contract:

    1. transform and construct every rule (refusing on the first defect);
    2. serialize and write a temporary file beside the destination, fsynced;
    3. **re-load that temporary file through the runtime's own loader** and
       re-check bounds, symbols and freshness on what was actually written;
    4. only then ``os.replace`` it onto the destination.

    Step 3 is what makes this a reviewed boundary rather than a write: the
    bytes that will become the runtime's ruleset are validated as bytes, by
    the same code the runtime would use, before anything is replaced. Any
    failure removes the temporary file and leaves the previous known-good
    ruleset exactly as it was.
    """
    now = (clock or (lambda: datetime.now(UTC)))()
    if now.tzinfo is None:
        raise VenueMetadataError("clock must return a timezone-aware datetime")

    observed = retrieved_at if retrieved_at is not None else now
    service = freshness if freshness is not None else VenueRuleFreshnessService(clock=clock)

    venue_id = str(venue).strip().upper()
    if not venue_id:
        raise VenueMetadataError("venue is required")

    # Bound the age of the *snapshot*, not just of the stamp written onto it.
    # ``retrieved_at`` records when the operator observed the payload, so a
    # six-month-old exchangeInfo file published today would carry a brand-new
    # provenance stamp and assess as FRESH - staleness laundered through an
    # observation. The venue's own ``serverTime`` is what actually dates the
    # data, and it is held to the same policy the runtime will judge the
    # published rules by.
    policy = service.policy
    snapshot_age = (now - snapshot.server_time).total_seconds()

    if snapshot_age > policy.maximum_age_seconds:
        raise VenueMetadataError(
            f"exchangeInfo snapshot is {int(snapshot_age)}s old, beyond the "
            f"{policy.maximum_age_seconds}s freshness policy; refusing to publish "
            "stale venue metadata under a current observation stamp"
        )

    if snapshot_age < -policy.future_skew_seconds:
        raise VenueMetadataError(
            "exchangeInfo snapshot serverTime is in the future beyond the allowed skew"
        )

    wanted = tuple(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip())

    ruleset = build_ruleset_from_exchange_info(
        snapshot,
        venue=venue_id,
        symbols=wanted,
        source=source,
        retrieved_at=observed,
    )

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    replaced_existing = target.exists()

    document = _artifact(
        ruleset,
        snapshot=snapshot,
        venue=venue_id,
        source=source,
        retrieved_at=observed,
        published_at=now,
    )

    temporary = target.with_suffix(target.suffix + ".tmp")

    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(document, indent=2, sort_keys=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

        # Re-read what was written, through the loader the runtime itself
        # uses. A document this rejects never becomes the destination.
        try:
            reloaded = load_instrument_ruleset(temporary)
        except InstrumentRulesConfigError as exc:
            raise VenueMetadataError(
                f"published document failed to re-load through the canonical loader: {exc}"
            ) from exc

        if set(reloaded.symbols) != set(wanted):
            raise VenueMetadataError("published document does not cover exactly the requested symbols")

        for symbol in reloaded.symbols:
            entry = reloaded.rules[symbol]
            if not entry.has_complete_venue_bounds:
                raise VenueMetadataError(f"{symbol}: published rule lost its venue upper bounds")
            if entry.digest != ruleset.rules[symbol].digest:
                raise VenueMetadataError(f"{symbol}: published rule identity changed in serialization")

        report = service.assess(reloaded)
        if report.status is not VenueRuleFreshnessStatus.FRESH:
            raise VenueMetadataError(
                f"published ruleset is not FRESH ({report.status.value}); refusing to publish "
                "a snapshot the runtime would immediately treat as stale"
            )

        os.replace(temporary, target)

    except BaseException:
        # No partial update: the destination was never opened, and the
        # temporary file does not survive a failed publication.
        temporary.unlink(missing_ok=True)
        raise

    return PublicationReport(
        destination=str(target),
        venue=venue_id,
        symbols=tuple(reloaded.symbols),
        source=source,
        source_version=str(snapshot.server_time_ms),
        retrieved_at=document["provenance"]["retrieved_at"],
        published_at=document["provenance"]["published_at"],
        payload_digest=snapshot.digest,
        verification_status=snapshot.verification_status,
        freshness_status=report.status.value,
        replaced_existing=replaced_existing,
    )


def verify_published_rules(
    path: str | Path,
    *,
    freshness: VenueRuleFreshnessService | None = None,
) -> dict[str, Any]:
    """Report on an already-published artifact without modifying anything."""
    service = freshness if freshness is not None else VenueRuleFreshnessService()

    try:
        ruleset = load_instrument_ruleset(path)
    except InstrumentRulesConfigError as exc:
        raise VenueMetadataError(f"published artifact is not loadable: {exc}") from exc

    document = json.loads(Path(path).read_text(encoding="utf-8"))
    report = service.assess(ruleset)
    incomplete = [
        symbol
        for symbol in ruleset.symbols
        if not ruleset.rules[symbol].has_complete_venue_bounds
    ]

    return {
        "path": str(path),
        "loadable": True,
        "schema_version": ruleset.schema_version,
        "symbols": list(ruleset.symbols),
        "symbols_without_complete_bounds": incomplete,
        "venue_upper_bounds_complete": not incomplete,
        "freshness": report.to_dict(),
        "provenance": document.get("provenance"),
    }


def reference_symbols(path: str | Path = REFERENCE_CONFIG_PATH) -> tuple[str, ...]:
    """The symbols the checked-in ruleset covers. Read-only."""
    return load_instrument_ruleset(path).symbols


# ---------------------------------------------------------------------------
# operator entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish or verify venue instrument rules derived from an operator-supplied "
            "exchangeInfo snapshot. Never writes config/instrument_rules.json, never "
            "opens a network connection, and grants no live authority."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    publish = sub.add_parser("publish", help="validate a snapshot and publish it atomically")
    publish.add_argument("--snapshot", required=True, help="path to an exchangeInfo JSON file")
    publish.add_argument("--destination", required=True, help="path of the published ruleset")
    publish.add_argument("--venue", required=True)
    publish.add_argument(
        "--source",
        required=True,
        help="the endpoint identity the snapshot came from, recorded as provenance",
    )
    publish.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="symbol to publish; repeatable. Defaults to the checked-in config's symbols.",
    )

    verify = sub.add_parser("verify", help="report on an already-published artifact")
    verify.add_argument("--path", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)

    try:
        if arguments.command == "publish":
            symbols = arguments.symbol if arguments.symbol else reference_symbols()
            report = publish_venue_rules(
                snapshot=load_exchange_info_snapshot(arguments.snapshot),
                destination=arguments.destination,
                venue=arguments.venue,
                symbols=symbols,
                source=arguments.source,
            )
            print(json.dumps(report.to_dict(), indent=2))
            return 0

        print(json.dumps(verify_published_rules(arguments.path), indent=2))
        return 0

    except (VenueMetadataError, InstrumentRulesConfigError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
