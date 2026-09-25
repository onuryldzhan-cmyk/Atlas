"""F-4: PaperTrader mirror integrity.

The paper book is a passive mirror of ExecutionPortfolioFoundation. These
tests pin three properties the reconciliation audit found missing:

- startup re-projects every symbol from the durable authority, so a lost,
  stale, or torn book cannot disagree with it indefinitely;
- save() is atomic, so an interrupted write leaves the previous complete
  file rather than a torn one;
- load() fails loud (CORRUPT / UNREADABLE, bad file preserved) instead of
  silently presenting an empty book - and never halts the runtime, because
  nothing reads the mirror.

Every runtime here is built on a pytest scratch state directory.
"""

from __future__ import annotations

import json
import logging

import pytest

import core.paper_trader as paper_trader_module
from core.application import PAPER_TRADE_BOOK_FILE, AtlasApplication
from core.paper_trader import PaperTrader

from tests.test_block3_execution_exception_atomicity import execute
from tests.test_block2_risk_service_composition_wiring import seed_valid_state


def start_app(state_dir) -> AtlasApplication:
    app = AtlasApplication(state_directory=state_dir)
    app.execution.start()
    return app


def assert_not_halted(app: AtlasApplication) -> None:
    assert app.execution.execution_halted is False
    assert app.execution.recovery_required is False


@pytest.fixture
def traded_state(tmp_path):
    """A state directory whose durable authority holds an open BTCUSDT."""
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = start_app(state_dir)
    assert execute(app)["status"] == "PAPER_EXECUTED"
    durable = app.portfolio_foundation.snapshot()["positions"]
    assert "BTCUSDT" in durable
    return state_dir


def book_path(state_dir):
    return state_dir / PAPER_TRADE_BOOK_FILE


# --------------------------------------------------------------------------
# startup re-projection
# --------------------------------------------------------------------------


def test_startup_reprojects_a_symbol_missing_from_the_book(traded_state, caplog):
    book_path(traded_state).write_text(
        json.dumps({"positions": {}, "history": []}), encoding="utf-8"
    )

    with caplog.at_level(logging.WARNING):
        app = start_app(traded_state)

    assert_not_halted(app)
    durable = app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]
    mirrored = app.paper_trader.positions["BTCUSDT"]
    assert mirrored["base_quantity"] == str(durable["base_quantity"])
    assert mirrored["position_id"] == str(durable["position_id"])
    assert "re-projected at startup" in caplog.text
    # Persisted, not only held in memory.
    on_disk = json.loads(book_path(traded_state).read_text(encoding="utf-8"))
    assert on_disk["positions"]["BTCUSDT"] == mirrored


def test_startup_drops_a_symbol_the_authority_shows_flat(traded_state):
    data = json.loads(book_path(traded_state).read_text(encoding="utf-8"))
    data["positions"]["ETHUSDT"] = {"symbol": "ETHUSDT", "stale_marker": True}
    history_before = list(data["history"])
    book_path(traded_state).write_text(json.dumps(data), encoding="utf-8")

    app = start_app(traded_state)

    assert_not_halted(app)
    assert "ETHUSDT" not in app.paper_trader.positions
    assert "BTCUSDT" in app.paper_trader.positions
    # History is a log of past projections, not a position source.
    assert app.paper_trader.history == history_before


def test_consistent_book_is_left_unchanged_and_not_reported(traded_state, caplog):
    before = json.loads(book_path(traded_state).read_text(encoding="utf-8"))

    with caplog.at_level(logging.WARNING):
        app = start_app(traded_state)

    assert "re-projected at startup" not in caplog.text
    assert app.paper_trader.positions == before["positions"]
    assert app.paper_trader.history == before["history"]


def test_consistent_startup_does_not_create_a_book_file(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)

    app = start_app(state_dir)

    assert_not_halted(app)
    assert app.paper_trader.load_status == "MISSING"
    assert not book_path(state_dir).exists()


def test_failing_startup_reprojection_never_halts(tmp_path):
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = AtlasApplication(state_directory=state_dir)

    def raising(positions):
        raise RuntimeError("mirror write failed")

    app.paper_trader.reproject_all = raising
    app.execution.start()

    assert_not_halted(app)


def test_no_reprojection_when_the_durable_foundation_is_not_ready(tmp_path):
    """A halted foundation is not a trusted source to project from."""
    state_dir = tmp_path / "state"
    seed_valid_state(state_dir)
    app = AtlasApplication(state_directory=state_dir)
    calls = []
    app.paper_trader.reproject_all = lambda positions: calls.append(positions)
    app.execution._durable_financial_ready = lambda: (False, "TEST_NOT_READY")

    app.execution.start()

    assert app.execution.execution_halted is True
    assert calls == []


# --------------------------------------------------------------------------
# load(): fail loud, never silently empty, never halting
# --------------------------------------------------------------------------


def test_torn_book_at_startup_is_reported_preserved_and_reprojected(traded_state, caplog):
    path = book_path(traded_state)
    torn = path.read_text(encoding="utf-8")[:25]
    path.write_text(torn, encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        app = start_app(traded_state)

    assert_not_halted(app)
    assert app.paper_trader.load_status == "CORRUPT"
    assert app.paper_trader.status()["load_status"] == "CORRUPT"
    assert "PAPER BOOK MIRROR CORRUPT" in caplog.text
    # The bad file is preserved for the operator, byte-exact.
    preserved = list(traded_state.glob(PAPER_TRADE_BOOK_FILE + ".corrupt.*"))
    assert len(preserved) == 1
    assert preserved[0].read_text(encoding="utf-8") == torn
    # And the mirror is rebuilt from durable truth rather than left empty.
    durable = app.portfolio_foundation.snapshot()["positions"]["BTCUSDT"]
    assert app.paper_trader.positions["BTCUSDT"]["base_quantity"] == str(
        durable["base_quantity"]
    )


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        json.dumps({"positions": [], "history": []}),
        json.dumps({"positions": {}, "history": {}}),
        json.dumps({"history": []}),
    ],
)
def test_wrong_shape_is_corrupt_not_empty(tmp_path, content):
    path = tmp_path / "book.json"
    path.write_text(content, encoding="utf-8")

    trader = PaperTrader(filename=str(path))

    assert trader.load_status == "CORRUPT"
    assert trader.positions == {}
    assert not path.exists()
    assert len(list(tmp_path.glob("book.json.corrupt.*"))) == 1


def test_unreadable_book_is_distinct_from_corrupt(tmp_path, monkeypatch):
    path = tmp_path / "book.json"
    path.write_text(json.dumps({"positions": {}, "history": []}), encoding="utf-8")

    def unreadable(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(paper_trader_module, "open", unreadable, raising=False)
    trader = PaperTrader(filename=str(path))

    assert trader.load_status == "UNREADABLE"
    assert trader.positions == {}
    assert trader.history == []


def test_missing_and_valid_books_load_statuses(tmp_path):
    path = tmp_path / "book.json"
    assert PaperTrader(filename=str(path)).load_status == "MISSING"

    path.write_text(
        json.dumps({"positions": {"X": {"symbol": "X"}}, "history": [{"type": "OPEN"}]}),
        encoding="utf-8",
    )
    trader = PaperTrader(filename=str(path))
    assert trader.load_status == "OK"
    assert trader.positions == {"X": {"symbol": "X"}}
    assert trader.history == [{"type": "OPEN"}]


# --------------------------------------------------------------------------
# save(): atomic
# --------------------------------------------------------------------------


def test_interrupted_save_leaves_the_previous_complete_file(tmp_path, monkeypatch):
    path = tmp_path / "book.json"
    trader = PaperTrader(filename=str(path))
    trader.positions = {"BTCUSDT": {"symbol": "BTCUSDT", "base_quantity": "1"}}
    trader.save()
    committed = path.read_text(encoding="utf-8")

    real_dump = json.dump

    def torn_dump(obj, stream, **kwargs):
        stream.write('{"positions": {"BTCUSDT": {"sym')
        raise OSError("disk full mid-write")

    monkeypatch.setattr(paper_trader_module.json, "dump", torn_dump)
    trader.positions = {}
    with pytest.raises(OSError):
        trader.save()
    monkeypatch.setattr(paper_trader_module.json, "dump", real_dump)

    # The live file is untouched and still parses to the last good book.
    assert path.read_text(encoding="utf-8") == committed
    reloaded = PaperTrader(filename=str(path))
    assert reloaded.load_status == "OK"
    assert "BTCUSDT" in reloaded.positions


def test_save_round_trips_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "nested" / "book.json"
    trader = PaperTrader(filename=str(path))
    trader.positions = {"A": {"symbol": "A"}}
    trader.history = [{"type": "OPEN", "symbol": "A"}]
    trader.save()

    assert not (tmp_path / "nested" / "book.json.tmp").exists()
    reloaded = PaperTrader(filename=str(path))
    assert reloaded.positions == trader.positions
    assert reloaded.history == trader.history


def test_reproject_all_reports_divergence(tmp_path):
    trader = PaperTrader(filename=str(tmp_path / "book.json"))
    trader.positions = {"OLD": {"symbol": "OLD"}}
    position = {"position_id": "p1", "base_quantity": "2", "version": 1}

    diverged = trader.reproject_all({"NEW": position})

    assert diverged == ["NEW", "OLD"]
    assert set(trader.positions) == {"NEW"}
    assert trader.reproject_all({"NEW": position}) == []
