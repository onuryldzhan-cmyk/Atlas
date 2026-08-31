"""Block 6C - the bounded venue metadata adapter.

Package 6A closed the freshness gate but built no refresh mechanism, and
Package 6B modelled the venue maxima but shipped no verified values for them,
both for the same recorded reason: no venue metadata seam existed. This is
that seam, and these tests hold its contract.

The properties that matter are not "it parses exchangeInfo". They are:
publication is atomic, a failed publication leaves the previous known-good
ruleset untouched, nothing incomplete or invented is ever published, the
financial core gains no network dependency, and the checked-in config is never
written. Each test below discriminates one of those.

Every publication in this file writes into `tmp_path`. Nothing here touches
the repository's real config or runtime state.
"""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from core.instrument_rules import (
    QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM,
    QUANTITY_ABOVE_VENUE_MAXIMUM,
    InstrumentRulesConfigError,
    load_instrument_ruleset,
)
from core.venue_rule_freshness import VenueRuleFreshnessService
from tools.venue_metadata_adapter import (
    REFERENCE_CONFIG_PATH,
    TRANSPORT_FILE,
    VERIFICATION_UNVERIFIED_TRANSPORT,
    ExchangeInfoSnapshot,
    VenueMetadataError,
    build_ruleset_from_exchange_info,
    load_exchange_info_snapshot,
    main,
    publish_venue_rules,
    reference_symbols,
    verify_published_rules,
)


SERVER_TIME = datetime(2026, 8, 19, 17, 46, 53, tzinfo=UTC)
SERVER_TIME_MS = int(SERVER_TIME.timestamp() * 1000)
OBSERVED_AT = SERVER_TIME + timedelta(seconds=55)  # the shipped config's own shape


def filters(**overrides: Any) -> list[dict[str, Any]]:
    """A complete, well-formed Binance-shaped filter set."""
    base = {
        "PRICE_FILTER": {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
        "LOT_SIZE": {
            "filterType": "LOT_SIZE",
            "minQty": "0.00001000",
            "maxQty": "9000.00000000",
            "stepSize": "0.00001000",
        },
        "MARKET_LOT_SIZE": {"filterType": "MARKET_LOT_SIZE", "maxQty": "100.00000000"},
        "NOTIONAL": {
            "filterType": "NOTIONAL",
            "minNotional": "5.00000000",
            "maxNotional": "9000000.00000000",
        },
    }
    for filter_type, changes in overrides.items():
        if changes is None:
            base.pop(filter_type, None)
            continue
        base[filter_type] = {**base[filter_type], **changes}
    return list(base.values())


def symbol_entry(
    symbol: str = "BTCUSDT",
    *,
    base_asset: str = "BTC",
    status: str = "TRADING",
    **filter_overrides: Any,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "status": status,
        "baseAsset": base_asset,
        "quoteAsset": "USDT",
        "filters": filters(**filter_overrides),
    }


def exchange_info(*entries: dict[str, Any], server_time_ms: int = SERVER_TIME_MS) -> dict[str, Any]:
    return {
        "timezone": "UTC",
        "serverTime": server_time_ms,
        "symbols": list(entries) or [symbol_entry()],
    }


def snapshot(payload: dict[str, Any] | None = None, tmp_path: Path | None = None):
    """A snapshot as the file transport would produce it."""
    document = payload if payload is not None else exchange_info()
    if tmp_path is not None:
        path = tmp_path / "exchangeInfo.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return load_exchange_info_snapshot(path)
    return ExchangeInfoSnapshot(
        payload=document,
        origin="in-memory",
        transport=TRANSPORT_FILE,
        digest="0" * 64,
        verification_status=VERIFICATION_UNVERIFIED_TRANSPORT,
    )


def frozen(at: datetime = OBSERVED_AT) -> VenueRuleFreshnessService:
    return VenueRuleFreshnessService(clock=lambda: at)


def publish(tmp_path: Path, payload: dict[str, Any] | None = None, **kwargs: Any):
    destination = kwargs.pop("destination", tmp_path / "published" / "rules.json")
    return publish_venue_rules(
        snapshot=kwargs.pop("snapshot_override", None) or snapshot(payload, tmp_path),
        destination=destination,
        venue=kwargs.pop("venue", "BINANCE"),
        symbols=kwargs.pop("symbols", ["BTCUSDT"]),
        source=kwargs.pop("source", "https://api.binance.com/api/v3/exchangeInfo"),
        clock=kwargs.pop("clock", lambda: OBSERVED_AT),
        freshness=kwargs.pop("freshness", frozen()),
        **kwargs,
    )


# ===========================================================================
# what a publication produces
# ===========================================================================


def test_publication_is_loadable_and_carries_maxima_and_provenance(tmp_path) -> None:
    """The whole point of 6C: an artifact the runtime's own loader accepts, in
    which every symbol models the venue maxima 6B added and nothing was
    invented to get there."""
    report = publish(tmp_path)

    published = load_instrument_ruleset(report.destination)
    rule = published.get("BTCUSDT")

    assert rule.has_complete_venue_bounds is True
    assert rule.max_quantity == D("9000.00000000")
    assert rule.max_notional == D("9000000.00000000")
    assert rule.market_max_quantity == D("100.00000000")
    assert rule.quantity_step == D("0.00001000")
    assert rule.min_notional == D("5.00000000")
    assert rule.price_tick == D("0.01000000")

    document = json.loads(Path(report.destination).read_text(encoding="utf-8"))
    provenance = document["provenance"]

    assert provenance["venue"] == "BINANCE"
    assert provenance["source"] == "https://api.binance.com/api/v3/exchangeInfo"
    assert provenance["source_version"] == str(SERVER_TIME_MS)
    assert provenance["server_time"] == "2026-08-19T17:46:53Z"
    assert provenance["retrieved_at"] == "2026-08-19T17:47:48Z"
    assert provenance["published_at"] == "2026-08-19T17:47:48Z"
    assert provenance["transport"] == TRANSPORT_FILE
    assert provenance["verification_status"] == VERIFICATION_UNVERIFIED_TRANSPORT
    assert provenance["venue_upper_bounds_modelled"] is True
    assert len(provenance["payload_digest"]) == 64
    assert report.freshness_status == "FRESH"
    assert report.replaced_existing is False


def test_published_rules_are_enforceable_by_the_block_6b_gate(tmp_path) -> None:
    """The two packages join up here: values that came from the venue drive the
    same fail-closed gate 6B built, with no hand-entered number in between."""
    rule = load_instrument_ruleset(publish(tmp_path).destination).get("BTCUSDT")

    # MARKET_LOT_SIZE.maxQty (100) binds a market order; LOT_SIZE.maxQty
    # (9000) binds one that is not. Both came from the snapshot.
    assert rule.upper_bound_violation(
        base_quantity=D("100"), quote_notional=D("1000"),
    ) is None
    assert rule.upper_bound_violation(
        base_quantity=D("100.00001"), quote_notional=D("1000"),
    )[0] == QUANTITY_ABOVE_VENUE_MARKET_MAXIMUM

    assert rule.upper_bound_violation(
        base_quantity=D("9000"), quote_notional=D("1000"), order_type="LIMIT",
    ) is None
    assert rule.upper_bound_violation(
        base_quantity=D("9000.00001"), quote_notional=D("1000"), order_type="LIMIT",
    )[0] == QUANTITY_ABOVE_VENUE_MAXIMUM


def test_provenance_keeps_the_checked_in_two_timestamp_convention(tmp_path) -> None:
    """`source_version` is the venue's serverTime and `retrieved_at` is when the
    operator observed it - the shape the checked-in config already has, where
    the observation sits just after the payload it recorded. An observation
    that predates its own payload is refused."""
    rule = load_instrument_ruleset(publish(tmp_path).destination).get("BTCUSDT")

    assert rule.source_version == str(SERVER_TIME_MS)
    assert rule.retrieved_at == "2026-08-19T17:47:48Z"

    with pytest.raises(VenueMetadataError, match="cannot predate"):
        build_ruleset_from_exchange_info(
            snapshot(),
            venue="BINANCE",
            symbols=["BTCUSDT"],
            source="test",
            retrieved_at=SERVER_TIME - timedelta(minutes=1),
        )


# ===========================================================================
# atomicity and the previous known-good ruleset
# ===========================================================================


def test_publication_leaves_no_temporary_file_behind(tmp_path) -> None:
    report = publish(tmp_path)
    directory = Path(report.destination).parent

    assert [item.name for item in directory.iterdir()] == ["rules.json"]


def test_a_failed_publication_preserves_the_previous_ruleset_byte_for_byte(tmp_path) -> None:
    """The core durability property. A second publication that fails validation
    must leave the first one exactly as it was - not truncated, not partially
    rewritten, and with no temporary file surviving to be mistaken for one."""
    first = publish(tmp_path)
    destination = Path(first.destination)
    before = destination.read_bytes()

    broken = exchange_info(symbol_entry(MARKET_LOT_SIZE={"maxQty": "0.00000000"}))

    with pytest.raises(VenueMetadataError):
        publish(tmp_path, broken, destination=destination)

    assert destination.read_bytes() == before
    assert [item.name for item in destination.parent.iterdir()] == ["rules.json"]
    # And the survivor is still a valid, complete ruleset.
    assert load_instrument_ruleset(destination).get("BTCUSDT").has_complete_venue_bounds


def test_a_second_valid_publication_replaces_and_reports_it(tmp_path) -> None:
    destination = tmp_path / "published" / "rules.json"
    publish(tmp_path, destination=destination)

    later = exchange_info(
        symbol_entry(LOT_SIZE={"maxQty": "8000.00000000"}),
        server_time_ms=SERVER_TIME_MS + 30_000,
    )
    report = publish(tmp_path, later, destination=destination)

    assert report.replaced_existing is True
    assert load_instrument_ruleset(destination).get("BTCUSDT").max_quantity == D("8000.00000000")


# ===========================================================================
# what is refused - nothing incomplete or invented is ever published
# ===========================================================================


def refusal(tmp_path, payload, match: str) -> None:
    destination = tmp_path / "published" / "rules.json"

    with pytest.raises(VenueMetadataError, match=match):
        publish(tmp_path, payload, destination=destination)

    assert not destination.exists()
    assert not (destination.parent / "rules.json.tmp").exists()


def test_a_zero_maximum_means_unlimited_and_is_refused_by_name(tmp_path) -> None:
    """A venue publishes 0 for "no limit". This contract models a bound as a
    positive Decimal and has no representation for explicitly-unbounded, so the
    symbol is refused by name rather than published with that axis silently
    unmodelled - which is exactly the state 6B fails closed on."""
    refusal(
        tmp_path,
        exchange_info(symbol_entry(MARKET_LOT_SIZE={"maxQty": "0.00000000"})),
        "MARKET_LOT_SIZE.maxQty",
    )


def test_a_venue_without_a_maximum_notional_is_refused(tmp_path) -> None:
    """Older `MIN_NOTIONAL`-only payloads carry no maxNotional. Completeness is
    all three bounds or nothing."""
    payload = exchange_info(symbol_entry(NOTIONAL=None))
    payload["symbols"][0]["filters"].append(
        {"filterType": "MIN_NOTIONAL", "minNotional": "5.00000000"}
    )

    refusal(tmp_path, payload, "no NOTIONAL filter")


def test_a_symbol_the_venue_is_not_trading_is_refused(tmp_path) -> None:
    refusal(tmp_path, exchange_info(symbol_entry(status="BREAK")), "not TRADING")


def test_a_requested_symbol_missing_from_the_snapshot_is_refused(tmp_path) -> None:
    with pytest.raises(VenueMetadataError, match="not present"):
        publish(tmp_path, symbols=["BTCUSDT", "ETHUSDT"])


def test_a_maximum_below_its_own_minimum_is_refused_by_the_rule_contract(tmp_path) -> None:
    """The 6B contradiction rule reached through the adapter: a maximum below
    the matching minimum admits nothing at all."""
    refusal(
        tmp_path,
        exchange_info(symbol_entry(LOT_SIZE={"maxQty": "0.00000100"})),
        "rejected by the rule contract",
    )


def test_a_float_bound_is_refused_rather_than_rounded(tmp_path) -> None:
    """A JSON number cannot carry a venue step exactly. Refused at the boundary
    for the same reason `InstrumentRules` refuses one."""
    refusal(
        tmp_path,
        exchange_info(symbol_entry(LOT_SIZE={"stepSize": 0.00001})),
        "float",
    )


def test_a_stale_snapshot_cannot_be_laundered_by_a_fresh_observation(tmp_path) -> None:
    """The subtle one. `retrieved_at` is when the operator observed the payload,
    so publishing a months-old exchangeInfo file today would stamp it as
    observed-now and assess FRESH. The venue's own serverTime is what dates the
    data, and it is held to the same policy."""
    ancient = exchange_info(server_time_ms=int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000))

    refusal(tmp_path, ancient, "beyond the")


def test_a_future_dated_snapshot_is_refused(tmp_path) -> None:
    ahead = exchange_info(
        server_time_ms=int((OBSERVED_AT + timedelta(hours=1)).timestamp() * 1000)
    )

    refusal(tmp_path, ahead, "future")


def test_a_malformed_snapshot_file_is_refused_at_the_transport(tmp_path) -> None:
    path = tmp_path / "exchangeInfo.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(VenueMetadataError, match="not valid JSON"):
        load_exchange_info_snapshot(path)

    with pytest.raises(VenueMetadataError, match="unavailable"):
        load_exchange_info_snapshot(tmp_path / "absent.json")


# ===========================================================================
# the boundary itself
# ===========================================================================


def test_publishing_never_writes_the_checked_in_config(tmp_path) -> None:
    """The adapter publishes to a runtime destination the operator names. The
    checked-in ruleset is read-only to it, and is never the destination."""
    before = REFERENCE_CONFIG_PATH.read_bytes()

    report = publish(tmp_path)

    assert Path(report.destination) != REFERENCE_CONFIG_PATH
    assert tmp_path in Path(report.destination).parents
    assert REFERENCE_CONFIG_PATH.read_bytes() == before
    # The checked-in config is still the unbounded one 6B recorded: publishing
    # did not retroactively give it maxima.
    assert reference_symbols() == load_instrument_ruleset(REFERENCE_CONFIG_PATH).symbols
    assert (
        load_instrument_ruleset(REFERENCE_CONFIG_PATH)
        .get("BTCUSDT")
        .has_complete_venue_bounds
        is False
    )


def test_the_adapter_opens_no_socket(tmp_path) -> None:
    """The financial core must gain no network dependency, and neither does
    this: with every socket constructor poisoned, a full publication still
    completes."""
    def refuse(*args: Any, **kwargs: Any):
        raise AssertionError("the venue metadata adapter must not open a socket")

    original_socket, original_connect = socket.socket, socket.create_connection
    socket.socket, socket.create_connection = refuse, refuse
    try:
        report = publish(tmp_path)
    finally:
        socket.socket, socket.create_connection = original_socket, original_connect

    assert load_instrument_ruleset(report.destination).symbols == ("BTCUSDT",)


def test_the_adapter_is_outside_the_runtime_closure(tmp_path) -> None:
    """The reviewed boundary, structurally: nothing the runtime imports can
    reach this module, so the core cannot acquire venue metadata by accident.
    The direction of dependency is tools -> core, never core -> tools."""
    closure = json.loads(
        (REFERENCE_CONFIG_PATH.parent.parent / "packaging/atlas_runtime_closure.json")
        .read_text(encoding="utf-8")
    )
    modules = closure["modules"] if isinstance(closure, dict) else closure

    assert not [name for name in modules if "venue_metadata_adapter" in name]

    core_directory = REFERENCE_CONFIG_PATH.parent.parent / "core"
    importers = [
        path.name
        for path in core_directory.glob("*.py")
        if "venue_metadata_adapter" in path.read_text(encoding="utf-8")
    ]

    assert importers == []


# ===========================================================================
# operator entry points
# ===========================================================================


def test_verify_reports_bounds_freshness_and_provenance(tmp_path) -> None:
    report = publish(tmp_path)

    verified = verify_published_rules(report.destination, freshness=frozen())

    assert verified["loadable"] is True
    assert verified["venue_upper_bounds_complete"] is True
    assert verified["symbols_without_complete_bounds"] == []
    assert verified["freshness"]["status"] == "FRESH"
    assert verified["provenance"]["source_version"] == str(SERVER_TIME_MS)


def test_verify_refuses_an_unloadable_artifact(tmp_path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"schema_version": "1.0", "rules": []}), encoding="utf-8")

    with pytest.raises(VenueMetadataError, match="not loadable"):
        verify_published_rules(broken)


def test_the_operator_cli_publishes_then_verifies(tmp_path, capsys) -> None:
    source = tmp_path / "exchangeInfo.json"
    source.write_text(json.dumps(exchange_info()), encoding="utf-8")
    destination = tmp_path / "published.json"

    # The CLI uses the real wall clock, so the snapshot is dated now: this
    # exercises the operator path end to end rather than a frozen fixture.
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    source.write_text(json.dumps(exchange_info(server_time_ms=now_ms)), encoding="utf-8")

    code = main([
        "publish",
        "--snapshot", str(source),
        "--destination", str(destination),
        "--venue", "BINANCE",
        "--source", "https://api.binance.com/api/v3/exchangeInfo",
        "--symbol", "BTCUSDT",
    ])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["freshness_status"] == "FRESH"

    assert main(["verify", "--path", str(destination)]) == 0
    assert json.loads(capsys.readouterr().out)["venue_upper_bounds_complete"] is True


def test_the_operator_cli_refuses_with_a_nonzero_exit(tmp_path, capsys) -> None:
    source = tmp_path / "exchangeInfo.json"
    source.write_text(
        json.dumps(exchange_info(symbol_entry(MARKET_LOT_SIZE={"maxQty": "0"}))),
        encoding="utf-8",
    )
    destination = tmp_path / "published.json"

    code = main([
        "publish",
        "--snapshot", str(source),
        "--destination", str(destination),
        "--venue", "BINANCE",
        "--source", "test",
        "--symbol", "BTCUSDT",
    ])

    assert code == 1
    assert "REFUSED" in capsys.readouterr().err
    assert not destination.exists()
