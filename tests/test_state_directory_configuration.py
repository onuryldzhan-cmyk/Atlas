"""STATE-MOVE-1 Phase A: operator-configurable durable roots, fail closed.

Two roots may be relocated by the operator - the durable state root that
every execution and financial-state file lives under, and the historical
market-data archive root. Both are overridden by an environment variable and
both default to their installation-anchored location when the variable is
absent.

The hazard these tests exist for is not a crash. It is a *silent* success: an
override that is mistyped, not yet created, or points at a file must never
fall back to the default, because falling back would open a different, empty
financial state while the operator believes the configured one is in use.
Every invalid-value test below therefore asserts that construction raises,
not merely that the value is ignored.

No test here touches the real state directory. The unset-variable cases
redirect the module-level default at the composition root instead, which is
what lets "unchanged when unset" be proven without binding a runtime to the
operator's live financial state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import core.application as application_module

from core.application import (
    DEFAULT_MARKET_ARCHIVE_DIRECTORY,
    DEFAULT_STATE_DIRECTORY,
    MARKET_ARCHIVE_DIRECTORY_ENV,
    STATE_DIRECTORY_ENV,
    AtlasApplication,
    ConfiguredDirectoryError,
    resolve_market_archive_directory,
    resolve_state_directory,
)


@pytest.fixture(autouse=True)
def _no_inherited_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from a known-clean environment.

    The suite must behave identically whether or not the operator running it
    has exported either variable in their own shell.
    """

    monkeypatch.delenv(STATE_DIRECTORY_ENV, raising=False)
    monkeypatch.delenv(MARKET_ARCHIVE_DIRECTORY_ENV, raising=False)


# ---------------------------------------------------------------------------
# (a) Unset - the default is preserved exactly
# ---------------------------------------------------------------------------


def test_unset_state_directory_resolves_to_the_installation_default() -> None:
    assert resolve_state_directory() == DEFAULT_STATE_DIRECTORY


def test_the_installation_default_is_absolute_and_installation_anchored() -> None:
    # Not CWD-relative: the same runtime must find the same durable state
    # from any working directory.
    assert DEFAULT_STATE_DIRECTORY.is_absolute()
    assert DEFAULT_STATE_DIRECTORY == (
        Path(application_module.__file__).resolve().parent.parent / "memory_data"
    )


def test_unset_market_archive_resolves_to_the_installation_default() -> None:
    assert resolve_market_archive_directory() == DEFAULT_MARKET_ARCHIVE_DIRECTORY
    assert DEFAULT_MARKET_ARCHIVE_DIRECTORY.is_absolute()


def test_application_with_no_override_uses_the_module_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The unset path really does flow into the constructor.

    The default constant is redirected rather than the environment being
    set, so this exercises the *absent-variable* branch end to end without
    binding a real runtime to the operator's live state directory.
    """

    monkeypatch.setattr(application_module, "DEFAULT_STATE_DIRECTORY", tmp_path)

    app = AtlasApplication()

    assert app.state_directory == tmp_path


def test_an_explicit_argument_still_wins_over_the_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Composition-root callers and tests are never overridden by the shell."""

    exported = tmp_path / "exported"
    exported.mkdir()
    explicit = tmp_path / "explicit"
    explicit.mkdir()

    monkeypatch.setenv(STATE_DIRECTORY_ENV, str(exported))

    app = AtlasApplication(state_directory=explicit)

    assert app.state_directory == explicit


# ---------------------------------------------------------------------------
# (b) Set to a valid absolute existing directory
# ---------------------------------------------------------------------------


def test_a_valid_state_override_is_used(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(STATE_DIRECTORY_ENV, str(tmp_path))

    assert resolve_state_directory() == tmp_path.resolve()


def test_a_valid_state_override_reaches_every_durable_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(STATE_DIRECTORY_ENV, str(tmp_path))

    app = AtlasApplication()

    assert app.state_directory == tmp_path.resolve()

    for path in (
        app.idempotency_store.file_path,
        app.transaction_journal.file_path,
        app.audit_store.file_path,
        Path(app.paper_trader.filename),
    ):
        assert path.is_relative_to(tmp_path.resolve()), path


def test_a_valid_market_archive_override_is_used(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(MARKET_ARCHIVE_DIRECTORY_ENV, str(tmp_path))

    assert resolve_market_archive_directory() == tmp_path.resolve()


def test_the_archive_tool_default_follows_the_market_archive_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The only writer of the archive must not keep its own idea of the path."""

    from tools.fetch_historical_market_data import (
        DATABASE_FILENAME,
        default_database_path,
    )

    monkeypatch.setenv(MARKET_ARCHIVE_DIRECTORY_ENV, str(tmp_path))

    assert default_database_path() == tmp_path.resolve() / DATABASE_FILENAME


def test_the_archive_tool_default_is_unchanged_when_unset() -> None:
    from tools.fetch_historical_market_data import (
        DATABASE_FILENAME,
        default_database_path,
    )

    assert default_database_path() == (
        DEFAULT_MARKET_ARCHIVE_DIRECTORY / DATABASE_FILENAME
    )


# ---------------------------------------------------------------------------
# (b) The intelligence layer lands in the same root, not beside the CWD
# ---------------------------------------------------------------------------


def test_the_state_root_is_threaded_into_the_brain(tmp_path: Path) -> None:
    app = AtlasApplication(state_directory=tmp_path)

    assert app.brain.state_directory == tmp_path


def test_every_intelligence_module_persists_under_the_configured_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The real intelligence layer, loaded for real, writes where told.

    ``ai.core.atlas_brain`` builds its memory core, reasoning engine and
    world model from one ``data_dir`` that used to default to a CWD-relative
    "memory_data". This asserts the threaded value actually arrives in all
    three, and - by running from a different working directory - that the
    old CWD-relative directory is no longer created anywhere.
    """

    state_root = tmp_path / "state"
    state_root.mkdir()
    working_directory = tmp_path / "cwd"
    working_directory.mkdir()

    monkeypatch.chdir(working_directory)

    app = AtlasApplication(state_directory=state_root)

    assert app.brain.load_intelligence() is True

    intelligence = app.brain.intelligence

    assert intelligence is not None
    assert intelligence.config["data_dir"] == str(state_root)

    for module in (
        intelligence.memory_core,
        intelligence.reasoning_engine,
        intelligence.world,
    ):
        assert module is not None
        assert Path(module.data_dir) == state_root

    assert not (working_directory / "memory_data").exists()


def test_a_bare_brain_keeps_its_historical_intelligence_config() -> None:
    """No new behaviour for callers that supply no state directory."""

    from core.brain import AtlasBrain

    assert AtlasBrain().state_directory is None
    assert AtlasBrain()._intelligence_config() is None


# ---------------------------------------------------------------------------
# (c/d/e) Invalid overrides must raise, never fall back
# ---------------------------------------------------------------------------


def _invalid_values(tmp_path: Path) -> list[tuple[str, str]]:
    a_file = tmp_path / "not_a_directory.json"
    a_file.write_text("{}", encoding="utf-8")

    return [
        ("relative", "memory_data"),
        ("relative_dotted", "./memory_data"),
        ("missing", str(tmp_path / "does_not_exist")),
        ("a_file", str(a_file)),
        ("empty", ""),
        ("whitespace", "   "),
    ]


@pytest.mark.parametrize(
    "variable",
    [STATE_DIRECTORY_ENV, MARKET_ARCHIVE_DIRECTORY_ENV],
)
def test_an_invalid_override_raises_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    variable: str,
) -> None:
    resolve = (
        resolve_state_directory
        if variable == STATE_DIRECTORY_ENV
        else resolve_market_archive_directory
    )

    for label, value in _invalid_values(tmp_path):
        monkeypatch.setenv(variable, value)

        with pytest.raises(ConfiguredDirectoryError) as raised:
            resolve()

        # The message must name the variable: an operator who mistyped one of
        # two similarly-named variables has to know which one to fix.
        assert variable in str(raised.value), label


def test_an_invalid_state_override_stops_the_application_from_constructing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The failure that matters: startup, not a later silent divergence."""

    monkeypatch.setenv(STATE_DIRECTORY_ENV, str(tmp_path / "typo"))

    with pytest.raises(ConfiguredDirectoryError):
        AtlasApplication()


def test_an_invalid_market_archive_override_stops_the_application_too(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Both roots are validated at startup, not at first use.

    Nothing in AtlasApplication opens the archive, but an operator who
    relocated it and mistyped the path should learn that when Atlas starts
    rather than when a fetch silently writes to the old location.
    """

    monkeypatch.setenv(MARKET_ARCHIVE_DIRECTORY_ENV, str(tmp_path / "typo"))

    with pytest.raises(ConfiguredDirectoryError):
        AtlasApplication(state_directory=tmp_path)


def test_a_missing_override_directory_is_never_created(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Creating it would turn a typo into a new, empty state root."""

    missing = tmp_path / "does_not_exist"

    monkeypatch.setenv(STATE_DIRECTORY_ENV, str(missing))

    with pytest.raises(ConfiguredDirectoryError):
        resolve_state_directory()

    assert not missing.exists()


def test_a_user_relative_override_is_expanded_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``~`` is a home-anchored absolute path, not a CWD-relative one."""

    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    home_state = tmp_path / "atlas_state"
    home_state.mkdir()

    monkeypatch.setenv(STATE_DIRECTORY_ENV, "~/atlas_state")

    assert resolve_state_directory() == home_state.resolve()
