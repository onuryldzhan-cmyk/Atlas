"""
============================================================
ATLAS VENUE INSTRUMENT RULES REFRESH (owner brief 2026-09-25, Part G / G1)
============================================================

Manual, operator-triggered tool that fetches a current ``exchangeInfo``
snapshot over the network and writes a validated, provenance-carrying
``config/instrument_rules.json`` for the operator to review and commit.

This closes the two gaps the 2026-09-25 checkpoint
(``checkpoints/20260925T185300Z_batch-g-venue-rules-refresh-proposal.md``)
found: nothing fetched a current snapshot, and the adapter never wrote the
checked-in config. Owner decision was **G1**: keep
``tools/venue_metadata_adapter.py``'s "cannot write the checked-in config"
posture intact as an *architectural* guarantee (it still opens no socket and
still never touches this file on its own), and let this separate,
explicitly-named tool be the one thing that does write it - as a normal,
uncommitted file change the operator reviews with ``git diff`` and commits
themselves.

What this tool does
--------------------
1. One unauthenticated HTTP GET of ``/api/v3/exchangeInfo`` for the
   requested symbols (default: the symbols already in the checked-in
   config), using the same keyless-public-endpoint posture as
   ``BinancePublicDataProvider`` and ``tools/fetch_historical_market_data.py``.
2. Hands the response to ``tools.venue_metadata_adapter.publish_venue_rules``
   unchanged - the same validate / write-temp-fsync / reload-through-the-
   canonical-loader / ``os.replace`` sequence Block 6C already carries, with
   the same fail-closed guarantee: a rejected payload never touches the
   destination, not even partially.
3. Prints a unified diff between the previous and new file content, plus the
   adapter's own publication report, and stops. It never runs ``git``.

What this tool does NOT do
---------------------------
- No runtime change. ``core/application.py`` still reads
  ``config/instrument_rules.json`` exactly as before (still the sole reader,
  per that module's own comment); this tool has no import relationship with
  it.
- No auto-commit, no scheduling, no network call beyond the one
  ``exchangeInfo`` fetch.
- No new verification of the transport: like the file-based adapter, this
  records exactly what is known (an unauthenticated HTTP fetch) and claims
  nothing more.

Usage
-----
    python tools/refresh_venue_instrument_rules.py
    python tools/refresh_venue_instrument_rules.py --symbol BTCUSDT --symbol ETHUSDT
    python tools/refresh_venue_instrument_rules.py --destination C:\\scratch\\rules.json
============================================================
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import requests
from requests import Session
from requests.exceptions import RequestException

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from core.instrument_rules import InstrumentRulesConfigError  # noqa: E402
from tools.venue_metadata_adapter import (  # noqa: E402
    REFERENCE_CONFIG_PATH,
    ExchangeInfoSnapshot,
    PublicationReport,
    VenueMetadataError,
    publish_venue_rules,
    reference_symbols,
)

DEFAULT_BASE_URL = "https://api.binance.com"
DEFAULT_TIMEOUT_SECONDS = 20.0
EXCHANGE_INFO_ENDPOINT = "/api/v3/exchangeInfo"

# Distinct from tools.venue_metadata_adapter.TRANSPORT_FILE: this snapshot
# arrived over the network, not as an operator-supplied file, so provenance
# must say so. Neither transport is cryptographically verified, hence both
# verification statuses name themselves "UNVERIFIED".
TRANSPORT_HTTP = "BINANCE_PUBLIC_HTTP"
VERIFICATION_HTTP_UNVERIFIED_TRANSPORT = "LIVE_HTTP_FETCH_UNVERIFIED_TRANSPORT"


def fetch_exchange_info_snapshot(
    symbols: Iterable[str],
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    session: Session | None = None,
) -> ExchangeInfoSnapshot:
    """One unauthenticated GET of ``exchangeInfo``, or a refusal.

    Every failure mode - unreachable venue, a non-2xx status, unparsable
    JSON, or a payload that is not a JSON object - raises
    ``VenueMetadataError`` and returns nothing, matching the fail-closed
    contract ``load_exchange_info_snapshot`` already holds for the file
    transport. Nothing is written to disk here; this function only builds an
    in-memory snapshot for ``publish_venue_rules`` to validate.
    """
    wanted = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    if not wanted:
        raise VenueMetadataError("no symbols requested")

    url = f"{base_url.rstrip('/')}{EXCHANGE_INFO_ENDPOINT}"
    http = session if session is not None else requests.Session()

    try:
        response = http.get(
            url,
            params={"symbols": json.dumps(wanted)},
            timeout=timeout_seconds,
            headers={"Accept": "application/json"},
        )
    except RequestException as exc:
        raise VenueMetadataError(f"exchangeInfo fetch failed: {exc}") from exc

    status_code = getattr(response, "status_code", None)
    if status_code != 200:
        raise VenueMetadataError(f"exchangeInfo fetch returned HTTP {status_code}")

    raw = response.content
    if not isinstance(raw, (bytes, bytearray)):
        raise VenueMetadataError("exchangeInfo response body was not bytes")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VenueMetadataError(f"exchangeInfo response is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise VenueMetadataError("exchangeInfo response must be a JSON object")

    return ExchangeInfoSnapshot(
        payload=payload,
        origin=url,
        transport=TRANSPORT_HTTP,
        digest=hashlib.sha256(bytes(raw)).hexdigest(),
        verification_status=VERIFICATION_HTTP_UNVERIFIED_TRANSPORT,
    )


def _read_bytes_if_present(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def _print_diff(*, before: bytes, after: bytes, destination: Path) -> None:
    diff = difflib.unified_diff(
        before.decode("utf-8", errors="replace").splitlines(keepends=True),
        after.decode("utf-8", errors="replace").splitlines(keepends=True),
        fromfile=f"a/{destination.name}",
        tofile=f"b/{destination.name}",
    )
    text = "".join(diff)
    if text:
        print(text)
    else:
        print(f"(no change to {destination})")


def refresh_venue_instrument_rules(
    *,
    venue: str = "BINANCE",
    symbols: Iterable[str] | None = None,
    destination: str | Path = REFERENCE_CONFIG_PATH,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    session: Session | None = None,
) -> PublicationReport:
    """Fetch, validate and atomically write ``destination``.

    Delegates every validation and write step to
    ``tools.venue_metadata_adapter.publish_venue_rules`` - this function adds
    only the network fetch and the before/after diff, never a separate write
    path.
    """
    target = Path(destination)
    wanted = list(symbols) if symbols is not None else list(reference_symbols(target))

    snapshot = fetch_exchange_info_snapshot(
        wanted,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        session=session,
    )

    before = _read_bytes_if_present(target)

    report = publish_venue_rules(
        snapshot=snapshot,
        destination=target,
        venue=venue,
        symbols=wanted,
        source=f"{base_url.rstrip('/')}{EXCHANGE_INFO_ENDPOINT}",
    )

    after = _read_bytes_if_present(target)
    _print_diff(before=before, after=after, destination=target)

    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a live exchangeInfo snapshot and write a validated "
            "config/instrument_rules.json for the operator to review and "
            "commit. Never runs git, never auto-commits."
        ),
    )
    parser.add_argument("--venue", default="BINANCE")
    parser.add_argument(
        "--symbol",
        dest="symbols",
        action="append",
        default=None,
        help="symbol to refresh; repeatable. Defaults to the destination file's current symbols.",
    )
    parser.add_argument("--destination", default=str(REFERENCE_CONFIG_PATH))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)

    try:
        report = refresh_venue_instrument_rules(
            venue=arguments.venue,
            symbols=arguments.symbols,
            destination=arguments.destination,
            base_url=arguments.base_url,
            timeout_seconds=arguments.timeout_seconds,
        )
    except (VenueMetadataError, InstrumentRulesConfigError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report.to_dict(), indent=2))
    print(
        "\nNo commit was made. Review the diff above (or `git diff "
        f"{report.destination}`) and commit it yourself if it looks right."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
