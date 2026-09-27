"""Owner brief 2026-09-25, Part G (G1) - the venue rules refresh tool.

Discriminates two things: a successful fetch actually writes a validated,
loadable ``config/instrument_rules.json``-shaped file with correct
provenance; and a malformed/incomplete ``exchangeInfo`` response never
writes anything at all - not even a partial or temporary artifact -
whatever destination content existed before the attempt.

Every write in this file targets ``tmp_path``. Nothing here touches the
repository's real ``config/instrument_rules.json``.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest
import requests

from core.instrument_rules import RULE_CONFIG_KEYS, load_instrument_ruleset
from tools import refresh_venue_instrument_rules as refresh_module
from tools.refresh_venue_instrument_rules import (
    TRANSPORT_HTTP,
    UPPER_BOUNDS_POLICY_WITHHELD,
    VERIFICATION_HTTP_UNVERIFIED_TRANSPORT,
    WITHHELD_UPPER_BOUND_FIELDS,
    fetch_exchange_info_snapshot,
    main,
    refresh_venue_instrument_rules,
)
from tools.venue_metadata_adapter import REFERENCE_CONFIG_PATH, VenueMetadataError


# publish_venue_rules judges freshness against the real clock by default (no
# clock override is threaded through this tool, deliberately - the refresh
# tool always runs "now"), so the fixture's serverTime must be current too,
# not a fixed historical timestamp the freshness policy would reject.
SERVER_TIME_MS = int(datetime.now(UTC).timestamp() * 1000) - 60_000


def filters(**overrides: Any) -> list[dict[str, Any]]:
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


def symbol_entry(symbol: str = "BTCUSDT", *, status: str = "TRADING", **filter_overrides: Any) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "status": status,
        "baseAsset": symbol.replace("USDT", ""),
        "quoteAsset": "USDT",
        "filters": filters(**filter_overrides),
    }


def exchange_info(*entries: dict[str, Any], server_time_ms: int = SERVER_TIME_MS) -> dict[str, Any]:
    return {
        "timezone": "UTC",
        "serverTime": server_time_ms,
        "symbols": list(entries) or [symbol_entry()],
    }


class FakeHTTPResponse:
    def __init__(self, *, status_code: int = 200, content: bytes = b"") -> None:
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, response: FakeHTTPResponse | None = None, exception: Exception | None = None) -> None:
        self._response = response
        self._exception = exception
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, params=None, timeout=None, headers=None) -> FakeHTTPResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout, "headers": headers})
        if self._exception is not None:
            raise self._exception
        assert self._response is not None
        return self._response


def json_session(payload: dict[str, Any], *, status_code: int = 200) -> FakeSession:
    return FakeSession(FakeHTTPResponse(status_code=status_code, content=json.dumps(payload).encode("utf-8")))


# ===========================================================================
# fetch_exchange_info_snapshot: the network-fetch transport
# ===========================================================================


def test_fetch_builds_a_snapshot_with_http_transport_and_digest() -> None:
    session = json_session(exchange_info(symbol_entry("BTCUSDT")))

    snapshot = fetch_exchange_info_snapshot(["BTCUSDT"], session=session)

    assert snapshot.transport == TRANSPORT_HTTP
    assert snapshot.verification_status == VERIFICATION_HTTP_UNVERIFIED_TRANSPORT
    assert len(snapshot.digest) == 64
    assert session.calls[0]["url"].endswith("/api/v3/exchangeInfo")
    assert json.loads(session.calls[0]["params"]["symbols"]) == ["BTCUSDT"]


def test_fetch_refuses_a_non_200_status() -> None:
    session = FakeSession(FakeHTTPResponse(status_code=503, content=b"{}"))

    with pytest.raises(VenueMetadataError, match="HTTP 503"):
        fetch_exchange_info_snapshot(["BTCUSDT"], session=session)


def test_fetch_refuses_invalid_json() -> None:
    session = FakeSession(FakeHTTPResponse(status_code=200, content=b"not json"))

    with pytest.raises(VenueMetadataError, match="not valid JSON"):
        fetch_exchange_info_snapshot(["BTCUSDT"], session=session)


def test_fetch_refuses_a_non_object_payload() -> None:
    session = FakeSession(FakeHTTPResponse(status_code=200, content=b"[]"))

    with pytest.raises(VenueMetadataError, match="JSON object"):
        fetch_exchange_info_snapshot(["BTCUSDT"], session=session)


def test_fetch_refuses_a_network_failure() -> None:
    session = FakeSession(exception=requests.exceptions.ConnectionError("boom"))

    with pytest.raises(VenueMetadataError, match="exchangeInfo fetch failed"):
        fetch_exchange_info_snapshot(["BTCUSDT"], session=session)


def test_fetch_refuses_with_no_symbols_requested() -> None:
    with pytest.raises(VenueMetadataError, match="no symbols requested"):
        fetch_exchange_info_snapshot([], session=FakeSession())


# ===========================================================================
# refresh_venue_instrument_rules: fetch + write, end to end
# ===========================================================================


def test_successful_refresh_writes_a_loadable_validated_file(tmp_path: Path) -> None:
    destination = tmp_path / "instrument_rules.json"
    session = json_session(exchange_info(symbol_entry("BTCUSDT")))

    report = refresh_venue_instrument_rules(
        symbols=["BTCUSDT"],
        destination=destination,
        session=session,
    )

    assert destination.exists()
    ruleset = load_instrument_ruleset(destination)
    assert ruleset.symbols == ("BTCUSDT",)
    # Owner decision 2026-09-27: the tool validates the venue maxima but never
    # writes them (Block 6B premise), so the written rule is unbounded.
    assert ruleset.rules["BTCUSDT"].has_complete_venue_bounds is False
    assert report.symbols == ("BTCUSDT",)
    assert report.destination == str(destination)
    assert report.verification_status == VERIFICATION_HTTP_UNVERIFIED_TRANSPORT


def test_refresh_defaults_symbols_to_the_destinations_existing_ones(tmp_path: Path) -> None:
    destination = tmp_path / "instrument_rules.json"
    # Seed an existing file so the tool can discover which symbols to refresh.
    seed_session = json_session(exchange_info(symbol_entry("ETHUSDT")))
    refresh_venue_instrument_rules(symbols=["ETHUSDT"], destination=destination, session=seed_session)

    refresh_session = json_session(exchange_info(symbol_entry("ETHUSDT")))
    report = refresh_venue_instrument_rules(destination=destination, session=refresh_session)

    assert report.symbols == ("ETHUSDT",)
    assert json.loads(refresh_session.calls[0]["params"]["symbols"]) == ["ETHUSDT"]


def test_refresh_never_writes_on_a_malformed_response(tmp_path: Path) -> None:
    """The fail-closed guarantee: a bad fetch leaves the destination exactly
    as it was, byte for byte - not overwritten, not partially written."""
    destination = tmp_path / "instrument_rules.json"
    good_session = json_session(exchange_info(symbol_entry("BTCUSDT")))
    refresh_venue_instrument_rules(symbols=["BTCUSDT"], destination=destination, session=good_session)
    before = destination.read_bytes()

    bad_session = FakeSession(FakeHTTPResponse(status_code=200, content=b"not json"))
    with pytest.raises(VenueMetadataError):
        refresh_venue_instrument_rules(symbols=["BTCUSDT"], destination=destination, session=bad_session)

    assert destination.read_bytes() == before
    assert not destination.with_suffix(destination.suffix + ".tmp").exists()


def test_refresh_never_writes_on_an_incomplete_exchange_info_entry(tmp_path: Path) -> None:
    """A symbol present but missing a required bound (the Block 6B posture)
    must refuse the whole publication, not write the symbols that did
    validate."""
    destination = tmp_path / "instrument_rules.json"
    incomplete = exchange_info(symbol_entry("BTCUSDT", NOTIONAL=None))
    session = json_session(incomplete)

    with pytest.raises(VenueMetadataError, match="NOTIONAL"):
        refresh_venue_instrument_rules(symbols=["BTCUSDT"], destination=destination, session=session)

    assert not destination.exists()


def test_refresh_never_writes_when_a_requested_symbol_is_absent(tmp_path: Path) -> None:
    destination = tmp_path / "instrument_rules.json"
    session = json_session(exchange_info(symbol_entry("BTCUSDT")))

    with pytest.raises(VenueMetadataError, match="ETHUSDT"):
        refresh_venue_instrument_rules(symbols=["BTCUSDT", "ETHUSDT"], destination=destination, session=session)

    assert not destination.exists()


# ===========================================================================
# Block 6B: venue upper bounds are never written (owner decision 2026-09-27)
# ===========================================================================


def assert_no_upper_bound_written(destination: Path) -> None:
    """Checked on the raw JSON as well as on the loaded rules: the loader
    reading a bound back as ``None`` is not the same as it never being on
    disk."""
    document = json.loads(destination.read_text(encoding="utf-8"))
    for entry in document["rules"]:
        assert not set(entry) & set(WITHHELD_UPPER_BOUND_FIELDS), entry["symbol"]

    ruleset = load_instrument_ruleset(destination)
    for symbol in ruleset.symbols:
        rule = ruleset.rules[symbol]
        assert (rule.max_quantity, rule.max_notional, rule.market_max_quantity) == (
            None, None, None,
        )
        assert rule.has_complete_venue_bounds is False

    assert document["provenance"]["venue_upper_bounds_modelled"] is False
    assert document["provenance"]["venue_upper_bounds_policy"] == UPPER_BOUNDS_POLICY_WITHHELD


def test_withheld_fields_are_exactly_the_block6b_upper_bounds() -> None:
    """The withheld set must match the schema's own upper-bound fields, so a
    renamed or added bound cannot slip past the strip unnoticed."""
    fields = set(WITHHELD_UPPER_BOUND_FIELDS)
    assert fields == {"max_quantity", "max_notional", "market_max_quantity"}
    assert fields <= RULE_CONFIG_KEYS


def test_refresh_never_writes_a_venue_upper_bound(tmp_path: Path) -> None:
    """The regression test for the whole package: a venue payload carrying
    every maximum for several symbols produces a written file with none of
    them, while the lower bounds and provenance still update."""
    destination = tmp_path / "instrument_rules.json"
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    session = json_session(exchange_info(*(symbol_entry(symbol) for symbol in symbols)))

    report = refresh_venue_instrument_rules(
        symbols=symbols, destination=destination, session=session,
    )

    assert_no_upper_bound_written(destination)
    ruleset = load_instrument_ruleset(destination)
    assert set(ruleset.symbols) == set(symbols)
    assert ruleset.rules["BTCUSDT"].min_notional == D("5")
    assert ruleset.rules["BTCUSDT"].retrieved_at == report.retrieved_at
    assert report.freshness_status == "FRESH"
    # Nothing but the destination is left behind: no bounded staging copy
    # and no temporary file beside it.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["instrument_rules.json"]


def test_refreshing_a_copy_of_the_shipped_config_keeps_the_block6b_premise(
    tmp_path: Path,
) -> None:
    """Run exactly as the operator does - symbols defaulted from the
    shipped config - against a copy of it: the result still satisfies the
    premise tests/test_block6b_venue_upper_bounds.py asserts of the real
    file."""
    destination = tmp_path / "instrument_rules.json"
    shutil.copyfile(REFERENCE_CONFIG_PATH, destination)
    symbols = load_instrument_ruleset(destination).symbols
    session = json_session(exchange_info(*(symbol_entry(symbol) for symbol in symbols)))

    report = refresh_venue_instrument_rules(destination=destination, session=session)

    assert set(report.symbols) == set(symbols)
    assert report.replaced_existing is True
    assert_no_upper_bound_written(destination)


def test_a_payload_missing_only_a_maximum_is_still_refused(tmp_path: Path) -> None:
    """Withholding the maxima from the written file must not stop them being
    required of the venue payload: a snapshot lacking only MARKET_LOT_SIZE -
    which carries no lower bound at all - is refused and writes nothing."""
    destination = tmp_path / "instrument_rules.json"
    session = json_session(exchange_info(symbol_entry("BTCUSDT", MARKET_LOT_SIZE=None)))

    with pytest.raises(VenueMetadataError, match="MARKET_LOT_SIZE"):
        refresh_venue_instrument_rules(symbols=["BTCUSDT"], destination=destination, session=session)

    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_the_write_guard_refuses_bounds_even_if_the_strip_regresses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth: if a future change stopped stripping the maxima, the
    write itself refuses and the previous file survives byte for byte."""
    destination = tmp_path / "instrument_rules.json"
    refresh_venue_instrument_rules(
        symbols=["BTCUSDT"], destination=destination,
        session=json_session(exchange_info(symbol_entry("BTCUSDT"))),
    )
    before = destination.read_bytes()

    monkeypatch.setattr(refresh_module, "_withhold_upper_bounds", lambda ruleset: ruleset)

    with pytest.raises(VenueMetadataError, match="upper bound"):
        refresh_venue_instrument_rules(
            symbols=["BTCUSDT"], destination=destination,
            session=json_session(exchange_info(symbol_entry("BTCUSDT"))),
        )

    assert destination.read_bytes() == before
    assert not destination.with_suffix(destination.suffix + ".tmp").exists()


# ===========================================================================
# CLI entry point
# ===========================================================================


def test_main_prints_a_refusal_and_returns_1_on_failure(tmp_path, capsys) -> None:
    destination = tmp_path / "instrument_rules.json"
    # main() builds its own real requests.Session; point it at an
    # unroutable host so it fails fast without touching the network, rather
    # than mocking transport internals the CLI itself doesn't expose.
    exit_code = main(
        [
            "--destination",
            str(destination),
            "--symbol",
            "BTCUSDT",
            "--base-url",
            "http://127.0.0.1:1",
            "--timeout-seconds",
            "1",
        ]
    )

    assert exit_code == 1
    assert not destination.exists()
    captured = capsys.readouterr()
    assert "REFUSED" in captured.err
