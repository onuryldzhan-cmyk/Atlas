"""Block 5G: closed-position lifetime identity.

Block 5F's own evidence (F3, accepted/deferred) recorded that
``ExecutionPortfolioFoundation._close`` keys ``closed_positions`` by
``position_id`` alone, while ``ExecutionManager`` minted only a bare
``"long:" + symbol`` constant for every flat-book BUY - identical for every
re-entry of the same symbol. A full close of the Nth lifetime therefore
silently overwrote the closed record of every lifetime before it: a real
four-cycle open/full-close run through the production paper pipeline left
exactly 1 of 4 closed records standing, with no error and no recovery flag.

The fix is a deterministic composite identity minted once per lifetime -
``long:<symbol>:<sha256(opening_request_id).hexdigest()>``
(``mint_long_position_id`` in ``core/execution_portfolio_foundation.py``) -
plus a fail-closed collision guard in ``_close`` so a reused identity can
never again silently overwrite history.

The identity is *hashed*, not the raw ``request_id`` embedded directly. An
intermediate version of this package embedded ``request_id`` raw and had to
widen the identity charset to accommodate MarketLoop's real, already-
shipping ``request_id`` convention - the deterministic fingerprint
``f"{symbol}|{candle_identity}|{action}"`` (``core/market_loop.py``), which
contains ``"|"``. Hashing removes that coupling entirely: a SHA-256 hex
digest is always exactly 64 lowercase hex characters regardless of what
``request_id`` contains or how long it is, so the composite always
satisfies ``data_layer.models``' canonical, *unwidened* `_ID` charset and
always stays comfortably inside its 128-character bound - with no
special-casing for any particular caller's ``request_id`` shape. This
closes 5G-3 (dormant relational-projection incompatibility) unconditionally,
not only for ``request_id`` shapes that happened to already be
relational-clean. ``request_id`` itself is unchanged and keeps its own,
unrelated, pre-existing validation (``ExecutionManager`` requires only
non-blank); ``mint_long_position_id`` owns solely the safe, deterministic
*projection* of it into a durable identity - never a truncation or
sanitization of the raw value into that identity. The identity remains
derivable from opening-request evidence alone: given the same ``request_id``
(already durably recorded - transaction journal, idempotency store), anyone
can recompute the identical digest and thus the identical ``position_id``.

``request_id`` is already the value ``apply_confirmed`` enforces as a
globally unique idempotency key, so the composite introduces no new
uniqueness invariant, only a naming convention layered over an existing one.

Legacy ``long:<symbol>`` live/closed records (pre-5G) are never rewritten:
they close under their own id exactly once, and only that position's *next*
lifetime mints the new composite form.

Every fixture writes into pytest's tmp_path. Nothing here may touch the
operator's real runtime state.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal as D
import hashlib
import json

import pytest

from core.application import AtlasApplication
from core.execution_models import ExecutionResult
from core.execution_portfolio_foundation import (
    AppliedExecutionArchiveStore,
    ClosedPositionArchiveStore,
    ExecutionPortfolioFoundation,
    FinancialStateStore,
    mint_long_position_id,
)
from data_layer.models import PositionRecord, validate_id

from tests.test_block2_risk_service_composition_wiring import seed_valid_state


# --------------------------------------------------------------------------
# shared fixtures - real production classes, isolated tmp_path state only
# --------------------------------------------------------------------------


def _expected_position_id(symbol: str, request_id: str) -> str:
    """Independently recomputes the same digest ``mint_long_position_id``
    is expected to produce, so tests assert against the documented
    algorithm rather than against whatever the implementation happens to
    return."""
    digest = hashlib.sha256(str(request_id).encode("utf-8")).hexdigest()
    return f"long:{symbol}:{digest}"


# request_id shapes that are hostile to a raw-embedding identity (too long,
# disallowed characters, non-ASCII, empty) but must all mint cleanly under
# hashing, with no per-shape special-casing anywhere in the mint path.
HOSTILE_REQUEST_IDS = [
    "r1",
    "BTCUSDT|open:1755781200000|BUY",
    "has a space",
    "has/slash",
    "unicode-é中文-\U0001F600",
    "r" * 5000,
    "",
    "!@#$%^&*()+=<>?",
]


def _sidecars(store: FinancialStateStore) -> tuple[AppliedExecutionArchiveStore, ClosedPositionArchiveStore]:
    """Derive a store's sidecar paths deterministically from its own path -
    these stores hold no Python-side state, only a path, so a restart (a
    fresh FinancialStateStore/ExecutionPortfolioFoundation pointing at the
    same file) trivially points at the same sidecars too."""
    return (
        AppliedExecutionArchiveStore(store.path.with_name(store.path.stem + "-applied.jsonl")),
        ClosedPositionArchiveStore(store.path.with_name(store.path.stem + "-closed.jsonl")),
    )


def _foundation(tmp_path, *, name: str = "financial", cash: str = "1000"
                 ) -> tuple[ExecutionPortfolioFoundation, FinancialStateStore]:
    store = FinancialStateStore(tmp_path / f"{name}.json")
    store.initialize(D(cash))
    applied_archive, closed_archive = _sidecars(store)
    return ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive), store


def _fill(action, *, base, price, fee, fee_ccy, execution_id, position_id) -> ExecutionResult:
    return ExecutionResult(
        success=True, status="PAPER_EXECUTED", execution_id=execution_id,
        position_id=position_id, symbol="BTCUSDT", action=action,
        filled_price=price, filled_base_quantity=D(str(base)),
        filled_quote_notional=D(str(price)) * D(str(base)),
        fee_amount=D(str(fee)), fee_currency=fee_ccy,
        idempotency_key=execution_id, provenance_ref="test",
    )


def _real_app(tmp_path) -> AtlasApplication:
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = AtlasApplication(state_directory=state_dir)
    app.execution.start()
    return app


def _buy(app: AtlasApplication, *, request_id: str, price: float) -> dict:
    return app.execution.execute({
        "symbol": "BTCUSDT", "action": "BUY", "price": price, "amount": "100",
        "confidence": 90.0, "risk": "MEDIUM", "request_id": request_id,
    })


def _sell(app: AtlasApplication, *, request_id: str, price: float) -> dict:
    return app.execution.execute({
        "symbol": "BTCUSDT", "action": "SELL", "price": price, "amount": 0,
        "confidence": 90.0, "risk": "MEDIUM", "request_id": request_id,
    })


def _live(app: AtlasApplication, symbol: str = "BTCUSDT"):
    return app.portfolio_foundation.snapshot()["positions"].get(symbol)


def _closed_on_disk(store: FinancialStateStore) -> dict:
    _, closed_archive = _sidecars(store)
    return closed_archive.load_index().by_position_id


# ===========================================================================
# A - the real reproduction: 4 lifetimes through the production paper
# pipeline, all 4 closed records surviving
# ===========================================================================


def test_four_real_lifetimes_produce_four_distinct_closed_records_surviving_restart(tmp_path):
    """The exact reproduction Block 5G was opened to fix: BUY -> full SELL,
    four times over, through ExecutionManager.execute() in PAPER mode. Under
    the pre-5G bare ``long:<symbol>`` identity this left exactly 1 of 4
    closed records standing; the deterministic composite identity leaves
    all 4, each with its own correct entry/exit/pnl evidence."""
    app = _real_app(tmp_path)
    cycles = [
        ("buy-0", "sell-0", 10.0, 12.0),
        ("buy-1", "sell-1", 20.0, 15.0),
        ("buy-2", "sell-2", 5.0, 9.0),
        ("buy-3", "sell-3", 40.0, 41.0),
    ]
    # base = 100 / entry (fixed 100 quote allocation each cycle); fee is 0
    # on this paper path, so gross_pnl = base * (exit - entry) exactly.
    expected = {
        _expected_position_id("BTCUSDT", "buy-0"): {"entry": D("10"), "exit": D("12"), "pnl": D("20")},
        _expected_position_id("BTCUSDT", "buy-1"): {"entry": D("20"), "exit": D("15"), "pnl": D("-25")},
        _expected_position_id("BTCUSDT", "buy-2"): {"entry": D("5"), "exit": D("9"), "pnl": D("80")},
        _expected_position_id("BTCUSDT", "buy-3"): {"entry": D("40"), "exit": D("41"), "pnl": D("2.5")},
    }

    position_ids = []
    opened_ats = []
    closed_ats = []
    for buy_id, sell_id, entry, exit_price in cycles:
        buy_result = _buy(app, request_id=buy_id, price=entry)
        assert buy_result["status"] == "PAPER_EXECUTED"
        assert buy_result["commit_outcome"] == "COMMITTED"
        live = _live(app)
        position_ids.append(live["position_id"])
        opened_ats.append(live["opened_at"])

        sell_result = _sell(app, request_id=sell_id, price=exit_price)
        assert sell_result["status"] == "PAPER_EXECUTED"
        assert sell_result["commit_outcome"] == "COMMITTED"
        assert _live(app) is None

    assert position_ids == list(expected)
    assert len(set(position_ids)) == 4, "each lifetime must mint a distinct identity"
    assert len(set(opened_ats)) == 4, "each lifetime opens at its own timestamp"

    closed = app.portfolio_foundation._closed_by_position_id
    assert set(closed) == set(expected)

    for position_id, want in expected.items():
        record = closed[position_id]
        assert record["position_id"] == position_id
        assert D(record["average_entry_price"]) == want["entry"]
        assert D(record["exit_price"]) == want["exit"]
        assert D(record["base_quantity"]) == D("0")
        assert D(record["gross_pnl"]) == want["pnl"]
        assert D(record["entry_fees"]) == D("0")
        closed_ats.append(record["closed_at"])
    assert len(set(closed_ats)) == 4, "each lifetime closes at its own timestamp"

    snap = app.portfolio_foundation.snapshot()
    assert snap["realized_gross_pnl"] == sum((row["pnl"] for row in expected.values()), D("0"))
    assert snap["fees"] == D("0")
    assert snap["cash"] == D("10000") + snap["realized_gross_pnl"]
    assert snap["gross_exposure"] == D("0")

    # Restart: reload the durable state fresh and prove every record and
    # every book-level total survives exactly.
    restarted = AtlasApplication(state_directory=tmp_path / "state")
    restarted.execution.start()
    assert restarted.portfolio_foundation.ready is True
    assert restarted.portfolio_foundation._closed_by_position_id == closed
    restarted_snap = restarted.portfolio_foundation.snapshot()
    assert restarted_snap["realized_gross_pnl"] == snap["realized_gross_pnl"]
    assert restarted_snap["cash"] == snap["cash"]


def test_candle_identity_shaped_request_id_mints_and_closes_through_the_real_pipeline(tmp_path):
    """Regression guard: MarketLoop mints request_id as the deterministic
    fingerprint ``f"{symbol}|{candle_identity}|{action}"``
    (``core/market_loop.py``) - the request_id this mint site actually sees
    on every real, currently-shipping automated BUY. An intermediate
    version of this package's identity contract embedded request_id raw and
    rejected "|", turning every such BUY into a FAILED result; several
    sibling suites (test_block5a_risk_state_plumbing.py,
    test_block5c_upstream_sizing_authority.py) caught this immediately. The
    final, hashed contract accepts this shape (and every other shape) with
    no special-casing at all."""
    app = _real_app(tmp_path)
    buy_request_id = "BTCUSDT|open:1755781200000|BUY"
    sell_request_id = "BTCUSDT|open:1755781200000|SELL"
    expected_id = _expected_position_id("BTCUSDT", buy_request_id)

    buy_result = _buy(app, request_id=buy_request_id, price=10.0)
    assert buy_result["status"] == "PAPER_EXECUTED"
    assert buy_result["commit_outcome"] == "COMMITTED"
    live = _live(app)
    assert live["position_id"] == expected_id
    assert validate_id(expected_id, "position_id") == expected_id

    sell_result = _sell(app, request_id=sell_request_id, price=11.0)
    assert sell_result["status"] == "PAPER_EXECUTED"
    assert _live(app) is None
    closed = app.portfolio_foundation._closed_by_position_id
    assert expected_id in closed


# ===========================================================================
# B - determinism: pure function of (symbol, request_id), no randomness
# ===========================================================================


def test_mint_is_deterministic_pure_function_of_symbol_and_request_id():
    first = mint_long_position_id("BTCUSDT", "r1")
    second = mint_long_position_id("BTCUSDT", "r1")
    assert first == second == _expected_position_id("BTCUSDT", "r1")
    assert mint_long_position_id("BTCUSDT", "r2") != first
    assert mint_long_position_id("ETHUSDT", "r1") != first
    # Reproducible from confirmed evidence alone (symbol + opening
    # request_id), exactly as data_layer's projection-replay contract
    # requires for a re-derivable identity - never a fresh random value.
    assert all(mint_long_position_id("BTCUSDT", "r1") == first for _ in range(50))


# ===========================================================================
# C - add-to-position reuses the existing live position_id
# ===========================================================================


def test_add_to_position_reuses_existing_position_id_and_mints_no_new_lifetime(tmp_path):
    foundation, store = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")

    open1 = foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", fee="1", fee_ccy="USDT",
              execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    assert open1["positions"]["BTCUSDT"]["position_id"] == position_id

    open2 = foundation.apply_confirmed(
        _fill("BUY", base="5", price="11", fee="1", fee_ccy="USDT",
              execution_id="e2", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    live = open2["positions"]["BTCUSDT"]
    assert live["position_id"] == position_id
    assert live["version"] == 2
    assert D(live["base_quantity"]) == D("15")
    assert len(open2["positions"]) == 1
    assert _closed_on_disk(store) == {}


# ===========================================================================
# D - partial SELL never archives a closed record and never changes identity
# ===========================================================================


def test_partial_sell_creates_no_closed_record_and_preserves_position_id(tmp_path):
    foundation, store = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")

    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", fee="0", fee_ccy="USDT",
              execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    snap = foundation.apply_confirmed(
        _fill("SELL", base="4", price="11", fee="0", fee_ccy="USDT",
              execution_id="e2", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )

    live = snap["positions"]["BTCUSDT"]
    assert live["position_id"] == position_id
    assert D(live["base_quantity"]) == D("6")
    assert _closed_on_disk(store) == {}


# ===========================================================================
# E - full SELL archives exactly one immutable record under the live id
# ===========================================================================


def test_full_sell_archives_exactly_one_immutable_record(tmp_path):
    foundation, store = _foundation(tmp_path)
    position_id = mint_long_position_id("BTCUSDT", "b1")

    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", fee="1", fee_ccy="USDT",
              execution_id="e1", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    snap = foundation.apply_confirmed(
        _fill("SELL", base="10", price="12", fee="0.5", fee_ccy="USDT",
              execution_id="e2", position_id=position_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )

    assert "BTCUSDT" not in snap["positions"]
    closed = _closed_on_disk(store)
    assert set(closed) == {position_id}
    record_before = json.loads(json.dumps(closed[position_id]))

    # An unrelated later lifetime on the same symbol must not perturb the
    # already-archived record.
    other_id = mint_long_position_id("BTCUSDT", "b2")
    foundation.apply_confirmed(
        _fill("BUY", base="1", price="50", fee="0", fee_ccy="USDT",
              execution_id="e3", position_id=other_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    foundation.apply_confirmed(
        _fill("SELL", base="1", price="55", fee="0", fee_ccy="USDT",
              execution_id="e4", position_id=other_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )

    closed_after = _closed_on_disk(store)
    assert closed_after[position_id] == record_before
    assert set(closed_after) == {position_id, other_id}


# ===========================================================================
# F - a real duplicate closed-position identity fails closed, never overwrites
# ===========================================================================


def test_reused_closed_position_identity_fails_closed_without_overwriting(tmp_path):
    """Constructs the exact scenario the pre-5G code produced on every
    re-entry: two independent lifetimes that happen to carry the identical
    position_id. The first closes normally; the second's close must be
    refused rather than silently replacing the first's history."""
    foundation, store = _foundation(tmp_path)
    collision_id = "long:BTCUSDT:collision"

    foundation.apply_confirmed(
        _fill("BUY", base="10", price="10", fee="0", fee_ccy="USDT",
              execution_id="e1", position_id=collision_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    foundation.apply_confirmed(
        _fill("SELL", base="10", price="12", fee="0", fee_ccy="USDT",
              execution_id="e2", position_id=collision_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    first_record = json.loads(json.dumps(_closed_on_disk(store)[collision_id]))
    assert foundation.ready is True

    # A second, independent lifetime reuses the same identity.
    foundation.apply_confirmed(
        _fill("BUY", base="1", price="99", fee="0", fee_ccy="USDT",
              execution_id="e3", position_id=collision_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    state_before = store.path.read_bytes()
    with pytest.raises(ValueError, match="CLOSED_POSITION_IDENTITY_CONFLICT"):
        foundation.apply_confirmed(
            _fill("SELL", base="1", price="200", fee="0", fee_ccy="USDT",
                  execution_id="e4", position_id=collision_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
        )

    # The collision is refused and the first lifetime's history survives
    # byte-for-byte - the Block 5G guarantee.
    assert _closed_on_disk(store)[collision_id] == first_record

    # F-6 (execution reconciliation audit, 2026-09-24): the refusal is now
    # raised before the transition marker is persisted, so it leaves nothing
    # behind. This test previously asserted the marker stayed on disk and the
    # book needed recovery; the owner ruled that the defect. System-level
    # fail-closed is unchanged: ExecutionManager still halts on the raise.
    assert store.path.read_bytes() == state_before
    on_disk = json.loads(store.path.read_text(encoding="utf-8"))
    assert on_disk["transition"] is None
    assert foundation.ready is True

    applied_archive, closed_archive = _sidecars(store)
    reloaded = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    # A restart still fails closed - on the reused identity itself (a live
    # position carrying an archived lifetime's id), no longer on a leftover
    # transition marker.
    assert reloaded.ready is False
    assert reloaded.diagnostics()["reason"] == "FINANCIAL_CLOSED_POSITION_LIVE_CONFLICT"
    assert "e4" not in applied_archive.load_index().by_execution_id


# ===========================================================================
# G - legacy bare long:<symbol> records are never rewritten
# ===========================================================================


def test_legacy_bare_symbol_position_id_closes_once_and_next_lifetime_mints_composite(tmp_path):
    """A pre-5G installation may already hold a live position under the old
    bare ``long:<symbol>`` identity. It must keep working exactly as
    before: reload cleanly and close under that same id, unrewritten. Only
    the *next* lifetime, opened after that legacy position closes, mints
    the new composite (hashed) form."""
    store = FinancialStateStore(tmp_path / "financial.json")
    store.initialize(D("1000"))
    payload = store.load()
    legacy_id = "long:BTCUSDT"
    payload["positions"]["BTCUSDT"] = {
        "position_id": legacy_id, "symbol": "BTCUSDT", "base_quantity": "10",
        "cost_quote": "100", "entry_fees": "0", "average_entry_price": "10",
        "mark_price": "10", "version": 1, "opened_at": datetime.now(UTC).isoformat(),
    }
    store.save(payload)

    applied_archive, closed_archive = _sidecars(store)
    foundation = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert foundation.ready is True
    assert foundation.snapshot()["positions"]["BTCUSDT"]["position_id"] == legacy_id

    snap = foundation.apply_confirmed(
        _fill("SELL", base="10", price="11", fee="0", fee_ccy="USDT",
              execution_id="legacy-close", position_id=legacy_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
    )
    assert "BTCUSDT" not in snap["positions"]
    legacy_record = json.loads(json.dumps(_closed_on_disk(store)[legacy_id]))
    assert legacy_record["position_id"] == legacy_id

    new_id = mint_long_position_id("BTCUSDT", "new-1")
    assert new_id == _expected_position_id("BTCUSDT", "new-1")
    assert new_id != legacy_id

    snap2 = foundation.apply_confirmed(
        _fill("BUY", base="1", price="20", fee="0", fee_ccy="USDT",
              execution_id="new-open", position_id=new_id),
        risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
    )
    assert snap2["positions"]["BTCUSDT"]["position_id"] == new_id

    # The legacy archive is untouched by the new lifetime.
    assert _closed_on_disk(store)[legacy_id] == legacy_record
    assert set(_closed_on_disk(store)) == {legacy_id}


# ===========================================================================
# H - restart preserves every closed lifetime exactly
# ===========================================================================


def test_restart_preserves_every_closed_lifetime_exactly(tmp_path):
    foundation, store = _foundation(tmp_path)
    ids = [mint_long_position_id("BTCUSDT", f"r{i}") for i in range(3)]

    for i, position_id in enumerate(ids):
        entry, exit_price = str(D("10") + i), str(D("12") + i)
        foundation.apply_confirmed(
            _fill("BUY", base="1", price=entry, fee="0", fee_ccy="USDT",
                  execution_id=f"buy-{i}", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=None,
        )
        foundation.apply_confirmed(
            _fill("SELL", base="1", price=exit_price, fee="0", fee_ccy="USDT",
                  execution_id=f"sell-{i}", position_id=position_id),
            risk_authorized=True, reservation_confirmed=True, expected_position_version=1,
        )

    before = _closed_on_disk(store)
    assert len(before) == 3
    assert set(before) == set(ids)

    applied_archive, closed_archive = _sidecars(store)
    restarted = ExecutionPortfolioFoundation(store, applied_archive=applied_archive, closed_archive=closed_archive)
    assert restarted.ready is True
    assert _closed_on_disk(store) == before
    assert restarted.snapshot()["positions"] == {}


# ===========================================================================
# I - length/charset independence: hashing bounds and normalizes identity
# regardless of request_id's own shape; request_id's own validation is
# unchanged and is not this module's concern
# ===========================================================================


def test_long_request_id_still_produces_a_bounded_valid_position_id():
    symbol = "BTCUSDT"
    very_long_request_id = "r" * 100_000

    minted = mint_long_position_id(symbol, very_long_request_id)

    assert len(minted) == len(f"long:{symbol}:") + 64
    assert len(minted) < 128
    assert validate_id(minted, "position_id") == minted
    assert minted == _expected_position_id(symbol, very_long_request_id)


def test_no_raw_request_id_charset_dependency_remains():
    """The lifetime-ID encoder owns safe, deterministic projection;
    request_id keeps its own existing, unrelated validation
    (ExecutionManager requires only non-blank). Every request_id shape
    below mints successfully with no special-casing, produces a distinct
    identity, and satisfies the canonical data_layer ID contract - proving
    the mint path has no dependency on request_id's own charset at all."""
    minted = [mint_long_position_id("BTCUSDT", rid) for rid in HOSTILE_REQUEST_IDS]

    assert len(set(minted)) == len(HOSTILE_REQUEST_IDS), "distinct request_ids must mint distinct identities"
    fixed_length = len("long:BTCUSDT:") + 64
    for position_id, request_id in zip(minted, HOSTILE_REQUEST_IDS):
        assert len(position_id) == fixed_length
        assert position_id == _expected_position_id("BTCUSDT", request_id)
        assert validate_id(position_id, "position_id") == position_id


# ===========================================================================
# J - the minted identity satisfies the dormant relational projection layer
# unconditionally (5G-3, fully CLOSED - not only for request_id shapes that
# happened to already be relational-clean)
# ===========================================================================


def test_minted_identity_always_satisfies_the_dormant_relational_projection_contract():
    """Without wiring data_layer storage (out of scope by owner decision):
    prove the composite identity this package mints always satisfies
    ``data_layer.models``' PRIMARY KEY identity contract - including for
    MarketLoop's real pipe-delimited request_id convention and every other
    hostile shape in HOSTILE_REQUEST_IDS - so the moment
    ``FinancialRuntimeSafetyService`` is ever given a storage backend,
    replaying any such identity through ``PositionRecord`` will not raise
    ``IntegrityViolation`` (Block 5G finding 5G-3, fully CLOSED)."""
    for request_id in HOSTILE_REQUEST_IDS:
        minted = mint_long_position_id("BTCUSDT", request_id)
        assert validate_id(minted, "position_id") == minted

        record = PositionRecord(
            position_id=minted, symbol="BTCUSDT", quantity=D("0"),
            average_price=D("10"), status="CLOSED", updated_at=datetime.now(UTC),
        )
        assert record.position_id == minted

    legacy = "long:BTCUSDT"
    assert validate_id(legacy, "position_id") == legacy
