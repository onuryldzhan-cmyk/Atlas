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
   destination, not even partially. That bounded publication goes to a
   throwaway staging directory, never to the destination.
3. Writes the destination **with every venue upper bound withheld** (owner
   decision 2026-09-27, Block 6B disposition reaffirmed): a copy of the
   staged, validated ruleset with ``max_quantity`` / ``max_notional`` /
   ``market_max_quantity`` removed from every rule, through its own
   write-temp / fsync / re-load / ``os.replace`` sequence. Running this tool
   is not the deliberate, high-friction operator verification Block 6B
   requires before the shipped config may model venue maxima, so it never
   supplies them and the live fail-closed gate
   (``VENUE_UPPER_BOUNDS_UNAVAILABLE``) keeps holding. The fetched maxima are
   still required and validated - a payload missing one is refused exactly
   as before - and are printed for operator visibility; they are just never
   written.
4. Prints a unified diff between the previous and new file content, plus the
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
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

import requests
from requests import Session
from requests.exceptions import RequestException

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from core.instrument_rules import (  # noqa: E402
    InstrumentRulesConfigError,
    InstrumentRuleset,
    load_instrument_ruleset,
)
from core.venue_rule_freshness import (  # noqa: E402
    VenueRuleFreshnessService,
    VenueRuleFreshnessStatus,
)
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

# The Block 6B venue maxima. Never written by this tool, under any code path:
# their absence from the shipped config is the premise the live fail-closed
# gate depends on (tests/test_block6b_venue_upper_bounds.py), and a refresh is
# not the verification that premise is waiting for.
WITHHELD_UPPER_BOUND_FIELDS = ("max_quantity", "max_notional", "market_max_quantity")
UPPER_BOUNDS_POLICY_WITHHELD = "WITHHELD_FROM_SHIPPED_CONFIG"


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
            params={"symbols": json.dumps(wanted, separators=(",", ":"))},
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


def _withhold_upper_bounds(ruleset: InstrumentRuleset) -> InstrumentRuleset:
    """The same rules with every venue maximum removed (``None`` = unmodelled).

    ``replace`` re-runs ``InstrumentRules`` construction, so each rule is
    re-validated and re-sealed: its digest is the unbounded rule's digest, not
    the bounded one's.
    """
    return InstrumentRuleset(
        {
            symbol: replace(
                ruleset.rules[symbol],
                **{name: None for name in WITHHELD_UPPER_BOUND_FIELDS},
            )
            for symbol in ruleset.symbols
        },
        schema_version=ruleset.schema_version,
    )


def _write_withheld_document(
    document: dict[str, Any],
    *,
    target: Path,
    expected: InstrumentRuleset,
) -> None:
    """Atomically replace ``target`` with ``document``, or leave it untouched.

    Same order of operations as ``publish_venue_rules``: write a temporary
    file beside the target and fsync it, re-load it through the runtime's own
    loader, check what was actually written - symbols, rule identity, the
    absence of every withheld field in the raw JSON *and* in the loaded rules,
    and freshness - and only then ``os.replace`` it. Any failure removes the
    temporary file and leaves the previous ``target`` byte-identical.
    """
    temporary = target.with_suffix(target.suffix + ".tmp")

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(document, indent=2, sort_keys=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

        try:
            reloaded = load_instrument_ruleset(temporary)
        except InstrumentRulesConfigError as exc:
            raise VenueMetadataError(
                f"withheld document failed to re-load through the canonical loader: {exc}"
            ) from exc

        if set(reloaded.symbols) != set(expected.symbols):
            raise VenueMetadataError(
                "withheld document does not cover exactly the requested symbols"
            )

        written = json.loads(temporary.read_text(encoding="utf-8"))
        for entry in written["rules"]:
            leaked = sorted(set(entry) & set(WITHHELD_UPPER_BOUND_FIELDS))
            if leaked:
                raise VenueMetadataError(
                    f"{entry.get('symbol')}: refusing to write venue upper bounds: "
                    f"{', '.join(leaked)}"
                )

        for symbol in reloaded.symbols:
            entry = reloaded.rules[symbol]
            if any(getattr(entry, name) is not None for name in WITHHELD_UPPER_BOUND_FIELDS):
                raise VenueMetadataError(f"{symbol}: withheld rule still models an upper bound")
            if entry.digest != expected.rules[symbol].digest:
                raise VenueMetadataError(
                    f"{symbol}: withheld rule identity changed in serialization"
                )

        freshness = VenueRuleFreshnessService().assess(reloaded)
        if freshness.status is not VenueRuleFreshnessStatus.FRESH:
            raise VenueMetadataError(
                f"withheld ruleset is not FRESH ({freshness.status.value}); refusing to write it"
            )

        os.replace(temporary, target)

    except BaseException:
        # No partial update: the target was never opened, and the temporary
        # file does not survive a failed write.
        temporary.unlink(missing_ok=True)
        raise


def _print_withheld_bounds(ruleset: InstrumentRuleset) -> None:
    print("Venue maxima fetched and validated, but WITHHELD from the written file (Block 6B):")
    for symbol in ruleset.symbols:
        entry = ruleset.rules[symbol]
        values = ", ".join(
            f"{name}={format(getattr(entry, name), 'f')}" for name in WITHHELD_UPPER_BOUND_FIELDS
        )
        print(f"  {symbol}: {values}")


def refresh_venue_instrument_rules(
    *,
    venue: str = "BINANCE",
    symbols: Iterable[str] | None = None,
    destination: str | Path = REFERENCE_CONFIG_PATH,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    session: Session | None = None,
) -> PublicationReport:
    """Fetch, validate and atomically write ``destination`` without maxima.

    Every validation of the fetched payload is delegated unchanged to
    ``tools.venue_metadata_adapter.publish_venue_rules``, which publishes the
    complete, bounded ruleset into a throwaway staging directory. What reaches
    ``destination`` is that validated ruleset with every
    ``WITHHELD_UPPER_BOUND_FIELDS`` entry removed, written by
    ``_write_withheld_document``. No path writes a bound to ``destination``.
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
    replaced_existing = target.exists()

    with tempfile.TemporaryDirectory(
        prefix="atlas-venue-rules-", ignore_cleanup_errors=True
    ) as staging:
        staged_path = Path(staging) / target.name
        report = publish_venue_rules(
            snapshot=snapshot,
            destination=staged_path,
            venue=venue,
            symbols=wanted,
            source=f"{base_url.rstrip('/')}{EXCHANGE_INFO_ENDPOINT}",
        )
        staged_provenance = json.loads(staged_path.read_text(encoding="utf-8"))["provenance"]
        bounded = load_instrument_ruleset(staged_path)

    withheld = _withhold_upper_bounds(bounded)
    document = {
        "schema_version": withheld.schema_version,
        "provenance": {
            **staged_provenance,
            "venue_upper_bounds_modelled": False,
            "venue_upper_bounds_policy": UPPER_BOUNDS_POLICY_WITHHELD,
        },
        "rules": [withheld.rules[symbol].to_dict() for symbol in withheld.symbols],
    }

    _write_withheld_document(document, target=target, expected=withheld)

    after = _read_bytes_if_present(target)
    _print_diff(before=before, after=after, destination=target)
    _print_withheld_bounds(bounded)

    return replace(report, destination=str(target), replaced_existing=replaced_existing)


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
    parser.add_argument(
        "--preset",
        choices=sorted(SYMBOL_PRESETS),
        default=None,
        help="a named symbol list (owner-20: the owner's 20-coin universe, registry v5.41).",
    )
    parser.add_argument("--destination", default=str(REFERENCE_CONFIG_PATH))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


# Registry v5.41, owner decision 2026-09-29: "coinlerin sayısını 20 yap".
# Long-listed, high-volume Binance USDT spot pairs. Every rule is still fetched
# from Binance and validated; a symbol Binance does not list as TRADING is
# refused by the adapter, never filled in.
SYMBOL_PRESETS = {
    "owner-20": (
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
        "DOGEUSDT", "ADAUSDT", "TRXUSDT", "AVAXUSDT", "LINKUSDT",
        "DOTUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT", "UNIUSDT",
        "ATOMUSDT", "XLMUSDT", "SUIUSDT", "APTUSDT", "FILUSDT",
    ),
}


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.preset:
        arguments.symbols = sorted(set(arguments.symbols or ()) | set(SYMBOL_PRESETS[arguments.preset]))

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
