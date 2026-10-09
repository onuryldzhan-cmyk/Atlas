"""Audit P4-CLOSURE-003 F-2: strategy research only counts as evidence when pre-registered.

v5.87 P4-1: "Every research study is pre-registered (sealed) in the hypothesis
registry". The daily ``strategy_research`` agent runs ``tools.strategy_compare``;
these tests pin that a run is a REGISTERED study only when bound to a sealed
hypothesis whose sealed ``feature_spec["strategy_compare"]`` equals the run,
that anything else is quarantined as EXPLORATORY, and that nothing downstream
(memory record, regime bar) promotes an unregistered verdict.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from atlas_org import memory_records
from research.hypothesis_registry import HypothesisRegistry
from research.lifecycle import HypothesisState
from tests.test_research_hypothesis_registry import make_preregistration
from tools import agent_cycle as ac
from tools import atlas_org_cli as cli
from tools import strategy_compare as sc

DAILY = sc.study_parameters(sc.VARIANTS, days=30, windows=3, embargo=240, step=15, exp001=True)
# Reviews NF-1 / R4-1: a study's sealed window must lie wholly after the registry's own
# genesis time (set by register(), i.e. now) and last exactly the sealed days, and the
# data must be exactly that window, one candle per minute. A legitimate study here
# therefore runs on tests/test_backtest_replay._rows shifted to start at 2100-01-01.
# PAST is the unshifted 2023 data (2023-11-14).
START_MS = 4_102_444_800_000  # 2100-01-01T00:00:00Z
FUTURE_SHIFT = START_MS - 1_700_000_000_000
PAST_START = "2023-11-14T22:13:20+00:00"
AFTER_THE_WINDOWS = 4_200_000_000.0  # 2103: every sealed window here has ended


@pytest.fixture(autouse=True)
def state_root(tmp_path, monkeypatch):
    """Review R4-2: registered studies use the canonical registry under the state root."""
    monkeypatch.setenv("ATLAS_STATE_DIRECTORY", str(tmp_path))
    (tmp_path / "research").mkdir()
    # Review R5-1: the daily agent checks the sealed universe against the universe selection.
    (tmp_path / "universe.json").write_text(json.dumps({"symbols": ["BTCUSDT"]}), encoding="utf-8")


def _window(days, start="2100-01-01T00:00:00+00:00"):
    from datetime import datetime, timedelta

    return {"data_start": start, "data_end": (datetime.fromisoformat(start) + timedelta(days=days)).isoformat()}


def _registry(tmp_path, spec=DAILY, hid="HYP-0001", **window):
    path = sc.canonical_registry()
    reg = HypothesisRegistry(registry_path=path)
    sealed = {"universe": ("BTCUSDT",), "preregistered_at": "2026-10-01T00:00:00+00:00", **_window(spec["days"])}
    reg.register(make_preregistration(hypothesis_id=hid, feature_spec={sc.STUDY_SPEC_KEY: spec},
                                      **{**sealed, **window}))
    return path, reg


# -- binding ---------------------------------------------------------------


def test_a_matching_sealed_registration_binds_the_study(tmp_path):
    path, reg = _registry(tmp_path)
    study = sc.bind_study(path, "HYP-0001", DAILY)
    assert study["status"] == "REGISTERED" and study["evidence_eligible"] is True
    assert study["preregistration_hash"] == reg.get("HYP-0001").preregistration_hash


@pytest.mark.parametrize("change", [{"windows": 2}, {"embargo": 0}, {"variants": [sc.REFERENCE]}, {"step": 30}])
def test_a_run_that_differs_from_the_sealed_spec_is_refused(tmp_path, change):
    path, _ = _registry(tmp_path)
    with pytest.raises(sc.StudyRegistrationError, match="does not match"):
        sc.bind_study(path, "HYP-0001", {**DAILY, **change})


def test_unknown_hypothesis_missing_registry_and_missing_spec_are_refused(tmp_path):
    path, _ = _registry(tmp_path)
    with pytest.raises(sc.StudyRegistrationError):
        sc.bind_study(path, "HYP-0099", DAILY)
    with pytest.raises(sc.StudyRegistrationError, match="no hypothesis registry"):
        sc.bind_study(tmp_path / "absent.json", "HYP-0001", DAILY)
    assert not (tmp_path / "absent.json").exists()  # binding never creates a registry
    HypothesisRegistry(registry_path=path).register(
        make_preregistration(hypothesis_id="HYP-0002", feature_spec={"lookback": 24}))
    with pytest.raises(sc.StudyRegistrationError, match="does not match"):
        sc.bind_study(path, "HYP-0002", DAILY)


def test_a_broken_seal_is_refused(tmp_path):
    path, _ = _registry(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["records"][0]["preregistration"]["feature_spec"][sc.STUDY_SPEC_KEY]["windows"] = 2  # hindsight edit
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(sc.StudyRegistrationError):
        sc.bind_study(path, "HYP-0001", {**DAILY, "windows": 2})


def test_a_terminal_hypothesis_cannot_host_a_new_study(tmp_path):
    path, reg = _registry(tmp_path)
    reg.advance("HYP-0001", HypothesisState.REJECTED)
    with pytest.raises(sc.StudyRegistrationError, match="REJECTED"):
        sc.bind_study(path, "HYP-0001", DAILY)


# -- the tool: refuse before replay, quarantine without registration -------


def _candles(count=1440, past=False):
    from tests.test_backtest_replay import _rows

    shift = 0 if past else FUTURE_SHIFT
    return [[r[0] + shift, *r[1:6], r[6] + shift, *r[7:]] for r in _rows(count)]


def _saved_dataset(tmp_path, past=False, outlier=None, rows=None, name=None):
    rows = _candles(past=past) if rows is None else rows
    if outlier is not None:  # one mid-series candle with another open time (NF-5)
        rows[outlier[0]] = [outlier[1], *rows[outlier[0]][1:]]
    data = {"BTCUSDT": rows}
    saved = tmp_path / (name or ("past.json" if past else "ds.json"))
    saved.write_text(json.dumps({"manifest": sc.dataset_manifest(data), "data": data}), encoding="utf-8")
    return saved


def test_unregistered_run_is_quarantined_as_exploratory(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "compare", lambda *a, **k: {"table": {"x": []}, "verdicts": {sc.REFERENCE: "-", "x": "BETTER"}})
    out = tmp_path / "out.json"
    assert sc.main(["--dataset", str(_saved_dataset(tmp_path)), "--symbols", "BTCUSDT", "--json", "--output", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["verdicts"] == {sc.REFERENCE: "-", "x": "EXPLORATORY"}
    assert result["study"] == {"status": "EXPLORATORY", "evidence_eligible": False, "reason": "NO_SEALED_PREREGISTRATION"}


def test_a_refused_binding_stops_before_any_replay(tmp_path, monkeypatch):
    path, _ = _registry(tmp_path)
    replayed = []
    monkeypatch.setattr(sc, "compare", lambda *a, **k: replayed.append(1) or {"table": {}, "verdicts": {}})
    rc = sc.main(["--dataset", str(_saved_dataset(tmp_path)), "--symbols", "BTCUSDT", "--json",
                  "--registry", str(path), "--hypothesis", "HYP-0001", "--windows", "2"])
    assert rc == 2 and replayed == []
    assert sc.main(["--registry", str(path), "--json"]) == 2  # the two flags go together


# A one-day study keeps the synthetic data small (1440 one-minute candles).
SPEC1 = sc.study_parameters(sc.VARIANTS, days=1, windows=3, embargo=0, step=15, exp001=True)


def _no_evidence(out):
    """A refused run produced no result. Round 6 (R5-1): it now leaves a REFUSED file for the daily agent
    to record (before, it left nothing); either way nothing in it can count as evidence."""
    if not out.exists():
        return True
    study = json.loads(out.read_text(encoding="utf-8"))["study"]
    return study["status"] == "REFUSED" and study["evidence_eligible"] is False and "table" not in json.loads(out.read_text(encoding="utf-8"))


# The sealed study's shape: every sealed variant, one row per sealed window.
FULL_TABLE = {name: [{"net_pnl": "1", "max_drawdown": "1", "closed_trades": 1}] * 3 for name in sc.VARIANTS}


def _registered_run(tmp_path, monkeypatch, dataset=None, **window):
    dataset = dataset or {}
    path, reg = _registry(tmp_path, spec=SPEC1, **window)
    replayed = []
    monkeypatch.setattr(sc, "compare", lambda *a, **k: replayed.append(1) or {"table": FULL_TABLE, "verdicts": {"x": "BETTER"}})
    out = tmp_path / "out.json"
    rc = sc.main(["--dataset", str(_saved_dataset(tmp_path, **dataset)), "--symbols", "BTCUSDT", "--json", "--days", "1",
                  "--output", str(out), "--registry", str(path), "--hypothesis", "HYP-0001"])
    return rc, out, replayed, path, reg


def test_a_registered_run_keeps_its_verdicts_and_links_the_hypothesis(tmp_path, monkeypatch):
    rc, out, replayed, path, reg = _registered_run(tmp_path, monkeypatch)
    assert rc == 0 and replayed == [1]
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["verdicts"] == {"x": "BETTER"}
    assert result["study"]["hypothesis_id"] == "HYP-0001"
    assert result["study"]["preregistration_hash"] == reg.get("HYP-0001").preregistration_hash
    assert sc.verify_registered_result(result, path)["hypothesis_id"] == "HYP-0001"


# -- review N-1: no retroactive registration, sealed window and universe bind the data --


@pytest.mark.parametrize("window", [
    {"preregistered_at": "2100-01-01T12:00:00+00:00"},                    # registered after the data existed
    {**_window(1, "2020-01-01T00:00:00+00:00"),
     "preregistered_at": "2019-12-01T00:00:00+00:00"},                    # the reviewer's sealed 2020 window
    _window(1, "2100-01-01T00:01:00+00:00"),                              # data starts before the sealed window
    _window(1, "2099-12-31T23:59:00+00:00"),                              # data runs past the sealed window
    {"data_end": "2100-01-03T00:00:00+00:00"},                            # a window wider than the sealed days
    _window(1, "2100-01-01T00:00:30+00:00"),                              # not on a whole minute
    {"universe": ("ETHUSDT",)},                                           # not the sealed universe
])
def test_data_outside_the_sealed_window_or_universe_is_refused_before_replay(tmp_path, monkeypatch, window):
    rc, out, replayed, *_ = _registered_run(tmp_path, monkeypatch, **window)
    assert rc == 2 and replayed == [] and _no_evidence(out)


def test_reviewer_n1_retroactive_registration_after_an_exploratory_look(tmp_path, monkeypatch):
    """Look at exploratory results first, then register a matching hypothesis: refused."""
    monkeypatch.setattr(sc, "compare", lambda *a, **k: {"table": {"x": [1]}, "verdicts": {"x": "BETTER"}})
    dataset = _saved_dataset(tmp_path, past=True)
    seen = tmp_path / "seen.json"
    assert sc.main(["--dataset", str(dataset), "--symbols", "BTCUSDT", "--json", "--output", str(seen)]) == 0
    assert json.loads(seen.read_text(encoding="utf-8"))["study"]["status"] == "EXPLORATORY"
    # Register now -- honestly dated, or with preregistered_at backdated to before the data (NF-1).
    for hid, prereg in (("HYP-0001", "2026-10-09T00:00:00+00:00"), ("HYP-0002", "2023-11-01T00:00:00+00:00")):
        path, _ = _registry(tmp_path, spec=SPEC1, hid=hid, preregistered_at=prereg, **_window(1, PAST_START))
        for _ in range(3):  # re-running the already-seen data never turns it into a study
            assert sc.main(["--dataset", str(dataset), "--symbols", "BTCUSDT", "--json", "--days", "1",
                            "--output", str(tmp_path / "r.json"), "--registry", str(path), "--hypothesis", hid]) == 2
        assert HypothesisRegistry(registry_path=path).get(hid).state is HypothesisState.REGISTERED


# -- the actual daily agent workflow --------------------------------------


def _sc_records(rec):
    return [r for r in memory_records.replay(cli.read_log(rec / cli.MEMORY_LOG)).values() if r["id"].startswith("SC-")]


def test_daily_agent_passes_the_owner_registration_to_the_run(tmp_path):
    # Rounds 4-5 (NEW-2, R4-1, R4-2): the agent checks the binding before launching, so this uses
    # a real sealed registration in the canonical registry, launched once its window has ended.
    path, _ = _registry(tmp_path, hid="HYP-0007")
    rd, launched = tmp_path / "research", []
    rd.mkdir(exist_ok=True)
    (rd / "strategy_research_registration.json").write_text(json.dumps({"hypothesis_id": "HYP-0007"}), encoding="utf-8")
    ac.strategy_research(tmp_path / "records", research_dir=rd, universe_file=rd.parent / "universe.json", launch=launched.append, now=AFTER_THE_WINDOWS)
    cmd = launched[0]
    assert cmd[cmd.index("--registry") + 1] == str(path) and cmd[cmd.index("--hypothesis") + 1] == "HYP-0007"


def test_daily_agent_runs_exploratory_until_the_sealed_window_has_ended(tmp_path):
    _registry(tmp_path, hid="HYP-0007")
    rd, launched = tmp_path / "research", []
    (rd / "strategy_research_registration.json").write_text(json.dumps({"hypothesis_id": "HYP-0007"}), encoding="utf-8")
    ac.strategy_research(tmp_path / "records", research_dir=rd, universe_file=rd.parent / "universe.json", launch=launched.append, now=1000.0)
    assert "--hypothesis" not in launched[0]  # its data does not exist yet


def test_daily_agent_without_registration_launches_an_exploratory_run(tmp_path):
    rd, launched = tmp_path / "research", []
    rd.mkdir(exist_ok=True)
    ac.strategy_research(tmp_path / "records", research_dir=rd, universe_file=rd.parent / "universe.json", launch=launched.append, now=1000.0)
    assert "--hypothesis" not in launched[0] and "--registry" not in launched[0]


@pytest.mark.parametrize("study", [None, {"status": "EXPLORATORY"}, {"status": "REGISTERED"}])
def test_daily_agent_never_promotes_an_unregistered_result(tmp_path, study):
    rd, rec = tmp_path / "research", tmp_path / "records"
    rd.mkdir(exist_ok=True)
    data = {"table": {"ref": [{"net_pnl": "1"}]}, "verdicts": {"ref": "-", "x": "BETTER"}}
    if study is not None:
        data["study"] = study
    (rd / "strategy_compare_latest.json").write_text(json.dumps(data), encoding="utf-8")
    done = ac.strategy_research(rec, research_dir=rd, universe_file=rd.parent / "universe.json", launch=lambda c: None, now=1200.0)
    assert "x" not in done["summary"]
    [record] = _sc_records(rec)
    body = json.loads(record["body"])
    assert body["verdicts"]["x"] == "EXPLORATORY" and body["study"]["evidence_eligible"] is False
    assert "BETTER" not in record["title"] and record["authority"] == "RESEARCH"


def _registered_result(tmp_path, monkeypatch):
    rc, out, _, path, _ = _registered_run(tmp_path, monkeypatch)
    assert rc == 0
    return json.loads(out.read_text(encoding="utf-8")), path


def _record_daily(tmp_path, result, registry=None):
    rd, rec = tmp_path / "research", tmp_path / "records"
    rd.mkdir(exist_ok=True)
    if registry is not None:
        (rd / "strategy_research_registration.json").write_text(
            json.dumps({"registry": str(registry), "hypothesis_id": "HYP-0001"}), encoding="utf-8")
    (rd / "strategy_compare_latest.json").write_text(json.dumps(result), encoding="utf-8")
    done = ac.strategy_research(rec, research_dir=rd, universe_file=rd.parent / "universe.json", launch=lambda c: None, now=1200.0)
    [record] = _sc_records(rec)
    return done, record


def test_daily_agent_records_a_verified_registered_result_with_its_hypothesis(tmp_path, monkeypatch):
    result, registry = _registered_result(tmp_path, monkeypatch)
    done, record = _record_daily(tmp_path, result, registry)
    assert "x" in done["summary"]
    assert "HYP-0001" in record["title"] and json.loads(record["body"])["study"]["hypothesis_id"] == "HYP-0001"
    assert record["authority"] == "RESEARCH"  # evidence for the owner, never authority


@pytest.mark.parametrize("tamper", ["fake_hash", "no_registry", "other_spec"])
def test_daily_agent_does_not_trust_a_self_declared_registration(tmp_path, monkeypatch, tamper):
    result, registry = _registered_result(tmp_path, monkeypatch)
    if tamper == "fake_hash":
        result["study"]["preregistration_hash"] = "a" * 64
    elif tamper == "other_spec":
        result["study"]["parameters"] = {**result["study"]["parameters"], "windows": 2}
    elif tamper == "no_registry":  # the canonical registry is gone: nothing verifies
        registry.rename(registry.with_name("moved.json"))
    done, record = _record_daily(tmp_path, result, registry)
    assert "x" not in done["summary"] and "BETTER" not in record["title"]
    assert json.loads(record["body"])["study"]["evidence_eligible"] is False


# -- review round 3: NF-4..NF-7 ----------------------------------------------


def test_nf5_one_mid_series_candle_outside_the_window_is_refused_before_replay(tmp_path, monkeypatch):
    rc, out, replayed, *_ = _registered_run(tmp_path, monkeypatch, dataset={"outlier": (700, 1_700_000_000_000)})
    assert rc == 2 and replayed == [] and _no_evidence(out)


def test_nf4_a_registered_study_block_copied_onto_another_result_is_refused(tmp_path, monkeypatch):
    result, registry = _registered_result(tmp_path, monkeypatch)
    other = {**result, "verdicts": {"FORGED-VARIANT": "BETTER"}}
    edited = json.loads(json.dumps(result))
    edited["table"][sc.REFERENCE][0]["net_pnl"] = "-50"
    for forged in (other, edited):
        with pytest.raises(sc.StudyRegistrationError, match="altered or relabelled"):
            sc.verify_registered_result(forged, registry)
    done, record = _record_daily(tmp_path, other, registry)
    assert "FORGED-VARIANT" not in done["summary"] and json.loads(record["body"])["study"]["evidence_eligible"] is False


def test_nf6_a_terminal_hypothesis_no_longer_verifies(tmp_path, monkeypatch):
    rc, out, _, path, reg = _registered_run(tmp_path, monkeypatch)
    result = json.loads(out.read_text(encoding="utf-8"))
    reg.advance("HYP-0001", HypothesisState.REJECTED)
    with pytest.raises(sc.StudyRegistrationError, match="REJECTED"):
        sc.verify_registered_result(result, path)


@pytest.mark.parametrize("binding", ["not json", "[1, 2]", '{"hypothesis_id": "HYP-0001"}', '{"registry": 5}',
                                     '{"hypothesis_id": ["HYP-0001"]}'])
def test_nf7_a_malformed_or_spent_binding_never_wedges_the_daily_agent(tmp_path, monkeypatch, binding):
    # Round 5 (R4-2): recording re-verifies against the canonical registry and no longer reads the
    # binding, so the binding only decides the next launch. HYP-0001's one run is already spent.
    result, _ = _registered_result(tmp_path, monkeypatch)
    rd, rec = tmp_path / "research", tmp_path / "records"
    (rd / "strategy_research_registration.json").write_text(binding, encoding="utf-8")
    (rd / "strategy_compare_latest.json").write_text(json.dumps(result), encoding="utf-8")
    done = ac.strategy_research(rec, research_dir=rd, universe_file=rd.parent / "universe.json", launch=lambda c: None, now=1200.0)
    [record] = _sc_records(rec)
    assert json.loads(record["body"])["study"]["hypothesis_id"] == "HYP-0001" and "x" in done["summary"]
    launched = []
    (rd / "strategy_compare_latest.json").unlink()
    ac.strategy_research(rec, research_dir=rd, universe_file=rd.parent / "universe.json", launch=launched.append, now=AFTER_THE_WINDOWS)
    assert "--hypothesis" not in launched[0] and "--registry" not in launched[0]


def test_nf7_a_corrupt_registry_or_malformed_result_is_refused_not_raised(tmp_path, monkeypatch):
    result, registry = _registered_result(tmp_path, monkeypatch)
    for mangle in (lambda r: r.update(dataset=[1]), lambda r: r.update(table=None),
                   lambda r: r["study"].update(parameters="x")):
        bad = json.loads(json.dumps(result))
        mangle(bad)
        with pytest.raises(sc.StudyRegistrationError):
            sc.verify_registered_result(bad, registry)
    registry.write_text("{not json", encoding="utf-8")
    with pytest.raises(sc.StudyRegistrationError):
        sc.verify_registered_result(result, registry)


def test_nf7_naive_sealed_times_are_refused(tmp_path):
    path, reg = _registry(tmp_path, data_start="2100-01-01T00:00:00", data_end="2100-01-31T00:00:00")
    with pytest.raises(sc.StudyRegistrationError, match="timezone-aware"):
        sc.check_study_data(path, "HYP-0001", {"symbols": {"BTCUSDT": {"first_open": 4_100_000_000_000,
                                                                       "last_open": 4_100_000_060_000}}})


# -- review round 4: NEW-2b (one recorded run per hypothesis), NEW-4 -------------


def test_new2b_the_tool_records_the_run_and_refuses_a_second_one(tmp_path, monkeypatch):
    rc, out, replayed, path, _ = _registered_run(tmp_path, monkeypatch)
    assert rc == 0 and replayed == [1]
    record = HypothesisRegistry(registry_path=path).get("HYP-0001")
    assert record.state is HypothesisState.CALIBRATED  # durable, in the registry's own state chain
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["study"]["run_started_at"] == record.state_chain[-1].recorded_at
    rc2 = sc.main(["--dataset", str(_saved_dataset(tmp_path)), "--symbols", "BTCUSDT", "--json", "--days", "1",
                   "--output", str(tmp_path / "again.json"), "--registry", str(path), "--hypothesis", "HYP-0001"])
    assert rc2 == 2 and replayed == [1] and _no_evidence(tmp_path / "again.json")
    assert sc.verify_registered_result(result, path)["hypothesis_id"] == "HYP-0001"  # the one run still verifies


def test_new2b_refused_data_does_not_consume_the_hypothesis(tmp_path, monkeypatch):
    rc, _, replayed, path, _ = _registered_run(tmp_path, monkeypatch, universe=("ETHUSDT",))
    assert rc == 2 and replayed == []
    assert HypothesisRegistry(registry_path=path).get("HYP-0001").state is HypothesisState.REGISTERED


@pytest.mark.parametrize("case", ["consumed", "other_spec", "unknown"])
def test_new2b_daily_agent_runs_exploratory_when_the_binding_cannot_host_a_run(tmp_path, case):
    path, reg = _registry(tmp_path, spec={**DAILY, "windows": 2} if case == "other_spec" else DAILY)
    if case == "consumed":
        reg.advance("HYP-0001", HypothesisState.CALIBRATED)
    rd, launched = tmp_path / "research", []
    rd.mkdir(exist_ok=True)
    (rd / "strategy_research_registration.json").write_text(json.dumps(
        {"hypothesis_id": "HYP-0099" if case == "unknown" else "HYP-0001"}), encoding="utf-8")
    ac.strategy_research(tmp_path / "records", research_dir=rd, universe_file=rd.parent / "universe.json", launch=launched.append, now=AFTER_THE_WINDOWS)
    assert "--hypothesis" not in launched[0] and "--registry" not in launched[0]


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", '{"table": {"x": [1, "a"]}, "verdicts": ["BETTER"]}',
                                     '{"table": [], "verdicts": {"x": "BETTER"}, "dataset": 5}', "\udcff"])
def test_new4_a_malformed_result_file_is_recorded_as_exploratory_not_raised(tmp_path, content):
    rd, rec = tmp_path / "research", tmp_path / "records"
    rd.mkdir(exist_ok=True)
    (rd / "strategy_compare_latest.json").write_text(content, encoding="utf-8", errors="surrogateescape")
    done = ac.strategy_research(rec, research_dir=rd, universe_file=rd.parent / "universe.json", launch=lambda c: None, now=1200.0)
    assert "BETTER" not in done["summary"]
    [record] = _sc_records(rec)
    assert json.loads(record["body"])["study"]["evidence_eligible"] is False
    assert (rd / "strategy_compare.recorded").exists()  # marked seen: the next cycle is not stuck on it
    assert len(_sc_records_after(rec, rd)) == 1


def _sc_records_after(rec, rd):
    ac.strategy_research(rec, research_dir=rd, universe_file=rd.parent / "universe.json", launch=lambda c: None, now=1300.0)
    return _sc_records(rec)


def test_new4_a_registry_path_that_is_a_directory_is_refused_not_raised(tmp_path, monkeypatch):
    # Round 5 (R4-2): the registry is the canonical path, not the binding's; make that a directory.
    result, registry = _registered_result(tmp_path, monkeypatch)
    registry.unlink()
    registry.mkdir()
    rd, rec = tmp_path / "research", tmp_path / "records"
    (rd / "strategy_compare_latest.json").write_text(json.dumps(result), encoding="utf-8")
    done = ac.strategy_research(rec, research_dir=rd, universe_file=rd.parent / "universe.json", launch=lambda c: None, now=1200.0)
    assert "ön kayıt yok" in done["summary"]
    assert json.loads(_sc_records(rec)[0]["body"])["study"]["evidence_eligible"] is False


# -- review round 5: R4-1 (exactly the sealed window), R4-2 (canonical registry) --


def _drop(rows, i):
    return rows[:i] + rows[i + 1:]


@pytest.mark.parametrize("rows", [
    lambda: _drop(_candles(), 700),                                   # one candle deleted mid-series
    lambda: _drop(_candles(1441), 700),                               # deleted, padded at the end to the count
    lambda: _candles()[:700] + [_candles()[699]] + _candles()[701:],  # a duplicated candle
    lambda: _candles(1000),                                           # a slice of the sealed window
    lambda: _candles(1500),                                           # more than the sealed window
    lambda: [["abc", *r[1:]] if i == 5 else r for i, r in enumerate(_candles())],  # a malformed open time
    lambda: [r if i != 5 else [] for i, r in enumerate(_candles())],  # an empty row
    # review R5-3: every column is checked before the run is recorded
    lambda: [r if i != 5 else r[:1] for i, r in enumerate(_candles())],                    # a short row
    lambda: [r if i != 5 else r[:11] for i, r in enumerate(_candles())],                   # 11 columns
    lambda: [r if i != 5 else [r[0], "NaN", *r[2:]] for i, r in enumerate(_candles())],    # a NaN price
    lambda: [r if i != 5 else [r[0], "-1", *r[2:]] for i, r in enumerate(_candles())],     # a negative price
    lambda: [r if i != 5 else [*r[:5], "-3", *r[6:]] for i, r in enumerate(_candles())],   # a negative volume
    lambda: [r if i != 5 else [*r[:6], r[6] + 1, *r[7:]] for i, r in enumerate(_candles())],  # bad close time
])
def test_r4_1_registered_data_must_be_exactly_the_sealed_window(tmp_path, monkeypatch, rows):
    path, _ = _registry(tmp_path, spec=SPEC1)
    replayed = []
    monkeypatch.setattr(sc, "compare", lambda *a, **k: replayed.append(1) or {"table": FULL_TABLE, "verdicts": {}})
    rc = sc.main(["--dataset", str(_saved_dataset(tmp_path, rows=rows())), "--symbols", "BTCUSDT", "--json",
                  "--days", "1", "--output", str(tmp_path / "o.json"), "--registry", str(path), "--hypothesis", "HYP-0001"])
    assert rc == 2 and replayed == [] and _no_evidence(tmp_path / "o.json")
    assert HypothesisRegistry(registry_path=path).get("HYP-0001").state is HypothesisState.REGISTERED  # not spent


def test_r4_1_a_registered_run_downloads_exactly_its_sealed_window(tmp_path, monkeypatch):
    path, _ = _registry(tmp_path, spec=SPEC1)
    candles, asked = _candles(1440 + 120), []

    def fetch(symbol, start):  # a market that also has candles after the window
        asked.append(start)
        return [r for r in candles if r[0] >= start][:1000]

    seen = []
    monkeypatch.setattr(sc, "compare", lambda data, *a, **k: seen.append(data) or {"table": FULL_TABLE, "verdicts": {}})
    rc = sc.main(["--symbols", "BTCUSDT", "--json", "--days", "1", "--output", str(tmp_path / "o.json"),
                  "--registry", str(path), "--hypothesis", "HYP-0001"], fetch=fetch)
    assert rc == 0 and asked[0] == START_MS
    assert [r[0] for r in seen[0]["BTCUSDT"]] == list(range(START_MS, START_MS + 1440 * 60_000, 60_000))


def test_r4_2_a_registry_outside_the_canonical_path_is_refused(tmp_path, monkeypatch):
    result, registry = _registered_result(tmp_path, monkeypatch)
    _registry(tmp_path, spec=SPEC1, hid="HYP-0002")
    copy = tmp_path / "elsewhere.json"
    copy.write_bytes(registry.read_bytes())  # the same registry file, outside the canonical path
    with pytest.raises(sc.StudyRegistrationError, match="canonical"):
        sc.bind_study(copy, "HYP-0002", SPEC1)
    with pytest.raises(sc.StudyRegistrationError, match="canonical"):
        sc.verify_registered_result(result, copy)
    assert sc.verify_registered_result(result, registry)["hypothesis_id"] == "HYP-0001"


# -- review round 6: R5-1 (a refused registered daily run never stalls the research) --


def _launch(tmp_path, now=AFTER_THE_WINDOWS):
    launched = []
    done = ac.strategy_research(tmp_path / "records", research_dir=tmp_path / "research", launch=launched.append,
                                now=now, universe_file=tmp_path / "universe.json")
    return done, launched[0] if launched else None


def _refusals(tmp_path):
    rec = tmp_path / "records"
    return [r for r in _sc_records(rec) if json.loads(r["body"])["study"]["status"] == "REFUSED"] if rec.exists() else []


def test_r5_1_a_tool_refusal_is_recorded_once_and_later_runs_are_exploratory(tmp_path, monkeypatch):
    path, _ = _registry(tmp_path, spec=SPEC1)
    rd = tmp_path / "research"
    (rd / "strategy_research_registration.json").write_text(json.dumps({"hypothesis_id": "HYP-0001"}), encoding="utf-8")
    monkeypatch.setattr(sc, "compare", lambda *a, **k: {"table": FULL_TABLE, "verdicts": {}})
    gappy = _saved_dataset(tmp_path, rows=_drop(_candles(), 700))  # the exchange history has a gap
    out = rd / "strategy_compare_latest.json"
    assert sc.main(["--dataset", str(gappy), "--symbols", "BTCUSDT", "--json", "--days", "1", "--output", str(out),
                    "--registry", str(path), "--hypothesis", "HYP-0001"]) == 2
    refused = json.loads(out.read_text(encoding="utf-8"))
    assert refused["study"]["status"] == "REFUSED" and refused["study"]["evidence_eligible"] is False
    done, _ = _launch(tmp_path)
    assert "reddedildi" in done["summary"] and "HYP-0001" in done["summary"]
    [record] = _refusals(tmp_path)
    assert "HYP-0001" in record["title"] and record["authority"] == "RESEARCH"
    out.unlink()
    for _ in range(3):  # no stall: every later launch is exploratory and says why; no duplicate record
        done, cmd = _launch(tmp_path)
        assert "--hypothesis" not in cmd and "refused earlier" in done["summary"]
        (rd / "strategy_compare.running").unlink()
    assert len(_refusals(tmp_path)) == 1
    assert HypothesisRegistry(registry_path=path).get("HYP-0001").state is HypothesisState.REGISTERED  # unspent


def test_r5_1_a_universe_that_drifted_from_the_sealed_one_falls_back_with_a_record(tmp_path):
    _registry(tmp_path, hid="HYP-0007")
    rd = tmp_path / "research"
    (rd / "strategy_research_registration.json").write_text(json.dumps({"hypothesis_id": "HYP-0007"}), encoding="utf-8")
    (tmp_path / "universe.json").write_text(json.dumps({"symbols": ["BTCUSDT", "ETHUSDT"]}), encoding="utf-8")
    for _ in range(2):
        done, cmd = _launch(tmp_path)
        assert "--hypothesis" not in cmd and "keşif" in done["summary"]
        (rd / "strategy_compare.running").unlink()
    [record] = _refusals(tmp_path)
    assert "sealed universe" in json.loads(record["body"])["study"]["reason"]


def test_r5_1_a_new_hypothesis_after_a_refusal_runs_registered(tmp_path):
    _registry(tmp_path, hid="HYP-0007")
    rd = tmp_path / "research"
    (rd / "strategy_compare.refused").write_text(json.dumps({"hypothesis_id": "HYP-0006", "reason": "gap"}), encoding="utf-8")
    (rd / "strategy_research_registration.json").write_text(json.dumps({"hypothesis_id": "HYP-0007"}), encoding="utf-8")
    done, cmd = _launch(tmp_path)
    assert cmd[cmd.index("--hypothesis") + 1] == "HYP-0007" and "ön kayıtlı: HYP-0007" in done["summary"]


def test_r5_1_a_refused_result_never_counts_as_evidence(tmp_path):
    forged = {"study": {"status": "REFUSED", "hypothesis_id": "HYP-0001", "reason": "x", "evidence_eligible": True},
              "verdicts": {"x": "BETTER"}, "table": {}}
    with pytest.raises(sc.StudyRegistrationError):
        sc.verify_registered_result(forged, sc.canonical_registry())
    rd = tmp_path / "research"
    (rd / "strategy_compare_latest.json").write_text(json.dumps(forged), encoding="utf-8")
    done, _ = _launch(tmp_path, now=1200.0)
    assert "BETTER" not in done["summary"]
    assert json.loads(_refusals(tmp_path)[0]["body"])["study"]["evidence_eligible"] is False
