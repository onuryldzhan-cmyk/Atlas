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
# Review NF-1: a study's data must postdate the registry's own genesis time (set by
# register(), i.e. now), so a legitimate study here runs on candles dated after it:
# tests/test_backtest_replay._rows shifted to 2099-12-03. PAST is the unshifted 2023 data.
FUTURE_SHIFT = 4_100_000_000_000 - 1_700_000_000_000
WINDOW = {"universe": ("BTCUSDT",), "data_start": "2099-01-01T00:00:00+00:00",
          "data_end": "2100-12-31T00:00:00+00:00", "preregistered_at": "2026-10-01T00:00:00+00:00"}
PAST_WINDOW = {"data_start": "2023-11-01T00:00:00+00:00", "data_end": "2023-12-31T00:00:00+00:00",
               "preregistered_at": "2023-11-01T00:00:00+00:00"}


def _registry(tmp_path, spec=DAILY, hid="HYP-0001", **window):
    path = tmp_path / "hypotheses.json"
    reg = HypothesisRegistry(registry_path=path)
    reg.register(make_preregistration(hypothesis_id=hid, feature_spec={sc.STUDY_SPEC_KEY: spec},
                                      **{**WINDOW, **window}))
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
    no_spec = tmp_path / "other"
    no_spec.mkdir()
    reg = HypothesisRegistry(registry_path=no_spec / "h.json")
    reg.register(make_preregistration(hypothesis_id="HYP-0002", feature_spec={"lookback": 24}))
    with pytest.raises(sc.StudyRegistrationError, match="does not match"):
        sc.bind_study(no_spec / "h.json", "HYP-0002", DAILY)


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


def _saved_dataset(tmp_path, past=False, outlier=None):
    from tests.test_backtest_replay import _rows

    shift = 0 if past else FUTURE_SHIFT
    rows = [[r[0] + shift, *r[1:6], r[6] + shift, *r[7:]] for r in _rows(1500)]
    if outlier is not None:  # one mid-series candle with another open time (NF-5)
        rows[outlier[0]] = [outlier[1], *rows[outlier[0]][1:]]
    data = {"BTCUSDT": rows}
    saved = tmp_path / ("past.json" if past else "ds.json")
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


SPEC21 = sc.study_parameters(sc.VARIANTS, days=21, windows=3, embargo=0, step=15, exp001=True)


# The sealed study's shape: every sealed variant, one row per sealed window.
FULL_TABLE = {name: [{"net_pnl": "1", "max_drawdown": "1", "closed_trades": 1}] * 3 for name in sc.VARIANTS}


def _registered_run(tmp_path, monkeypatch, dataset=None, **window):
    dataset = dataset or {}
    path, reg = _registry(tmp_path, spec=SPEC21, **window)
    replayed = []
    monkeypatch.setattr(sc, "compare", lambda *a, **k: replayed.append(1) or {"table": FULL_TABLE, "verdicts": {"x": "BETTER"}})
    out = tmp_path / "out.json"
    rc = sc.main(["--dataset", str(_saved_dataset(tmp_path, **dataset)), "--symbols", "BTCUSDT", "--json",
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
    {"preregistered_at": "2100-01-01T00:00:00+00:00"},                    # registered after the data existed
    {"data_start": "2020-01-01T00:00:00+00:00", "data_end": "2020-02-01T00:00:00+00:00",
     "preregistered_at": "2019-12-01T00:00:00+00:00"},                    # the reviewer's sealed 2020 window
    {"data_start": "2099-12-04T00:00:00+00:00"},                          # data starts before the sealed window
    {"data_end": "2099-12-04T00:00:00+00:00"},                            # data runs past the sealed window
    {"universe": ("ETHUSDT",)},                                           # not the sealed universe
])
def test_data_outside_the_sealed_window_or_universe_is_refused_before_replay(tmp_path, monkeypatch, window):
    rc, out, replayed, *_ = _registered_run(tmp_path, monkeypatch, **window)
    assert rc == 2 and replayed == [] and not out.exists()


def test_reviewer_n1_retroactive_registration_after_an_exploratory_look(tmp_path, monkeypatch):
    """Look at exploratory results first, then register a matching hypothesis: refused."""
    monkeypatch.setattr(sc, "compare", lambda *a, **k: {"table": {"x": [1]}, "verdicts": {"x": "BETTER"}})
    dataset = _saved_dataset(tmp_path, past=True)
    seen = tmp_path / "seen.json"
    assert sc.main(["--dataset", str(dataset), "--symbols", "BTCUSDT", "--json", "--output", str(seen)]) == 0
    assert json.loads(seen.read_text(encoding="utf-8"))["study"]["status"] == "EXPLORATORY"
    # Register now -- honestly dated, or with preregistered_at backdated to before the data (NF-1).
    for i, prereg in enumerate(("2026-10-09T00:00:00+00:00", PAST_WINDOW["preregistered_at"])):
        sub = tmp_path / f"r{i}"
        sub.mkdir()
        path, _ = _registry(sub, spec=SPEC21, **{**PAST_WINDOW, "preregistered_at": prereg})
        for _ in range(3):  # re-running the already-seen data never turns it into a study
            assert sc.main(["--dataset", str(dataset), "--symbols", "BTCUSDT", "--json", "--output", str(sub / "r.json"),
                            "--registry", str(path), "--hypothesis", "HYP-0001"]) == 2


# -- the actual daily agent workflow --------------------------------------


def _sc_records(rec):
    return [r for r in memory_records.replay(cli.read_log(rec / cli.MEMORY_LOG)).values() if r["id"].startswith("SC-")]


def test_daily_agent_passes_the_owner_registration_to_the_run(tmp_path):
    rd, launched = tmp_path / "research", []
    rd.mkdir()
    (rd / "strategy_research_registration.json").write_text(
        json.dumps({"registry": "reg.json", "hypothesis_id": "HYP-0007"}), encoding="utf-8")
    ac.strategy_research(tmp_path / "records", research_dir=rd, launch=launched.append, now=1000.0)
    cmd = launched[0]
    assert cmd[cmd.index("--registry") + 1] == "reg.json" and cmd[cmd.index("--hypothesis") + 1] == "HYP-0007"


def test_daily_agent_without_registration_launches_an_exploratory_run(tmp_path):
    rd, launched = tmp_path / "research", []
    rd.mkdir()
    ac.strategy_research(tmp_path / "records", research_dir=rd, launch=launched.append, now=1000.0)
    assert "--hypothesis" not in launched[0] and "--registry" not in launched[0]


@pytest.mark.parametrize("study", [None, {"status": "EXPLORATORY"}, {"status": "REGISTERED"}])
def test_daily_agent_never_promotes_an_unregistered_result(tmp_path, study):
    rd, rec = tmp_path / "research", tmp_path / "records"
    rd.mkdir()
    data = {"table": {"ref": [{"net_pnl": "1"}]}, "verdicts": {"ref": "-", "x": "BETTER"}}
    if study is not None:
        data["study"] = study
    (rd / "strategy_compare_latest.json").write_text(json.dumps(data), encoding="utf-8")
    done = ac.strategy_research(rec, research_dir=rd, launch=lambda c: None, now=1200.0)
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
    done = ac.strategy_research(rec, research_dir=rd, launch=lambda c: None, now=1200.0)
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
    done, record = _record_daily(tmp_path, result, None if tamper == "no_registry" else registry)
    assert "x" not in done["summary"] and "BETTER" not in record["title"]
    assert json.loads(record["body"])["study"]["evidence_eligible"] is False


# -- review round 3: NF-4..NF-7 ----------------------------------------------


def test_nf5_one_mid_series_candle_outside_the_window_is_refused_before_replay(tmp_path, monkeypatch):
    rc, out, replayed, *_ = _registered_run(tmp_path, monkeypatch, dataset={"outlier": (700, 1_700_000_000_000)})
    assert rc == 2 and replayed == [] and not out.exists()


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


@pytest.mark.parametrize("binding", ["not json", "[1, 2]", '{"hypothesis_id": "HYP-0001"}', '{"registry": 5}'])
def test_nf7_a_malformed_binding_never_wedges_the_daily_agent(tmp_path, monkeypatch, binding):
    result, _ = _registered_result(tmp_path, monkeypatch)
    rd, rec = tmp_path / "research", tmp_path / "records"
    rd.mkdir()
    (rd / "strategy_research_registration.json").write_text(binding, encoding="utf-8")
    (rd / "strategy_compare_latest.json").write_text(json.dumps(result), encoding="utf-8")
    done = ac.strategy_research(rec, research_dir=rd, launch=lambda c: None, now=1200.0)
    [record] = _sc_records(rec)
    assert "x" not in done["summary"] and json.loads(record["body"])["study"]["evidence_eligible"] is False
    launched = []
    (rd / "strategy_compare_latest.json").unlink()
    ac.strategy_research(rec, research_dir=rd, launch=launched.append, now=10**9)
    assert "--hypothesis" not in launched[0] or "--registry" in launched[0]


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
    path, reg = _registry(tmp_path, data_start="2099-01-01T00:00:00", data_end="2100-12-31T00:00:00")
    with pytest.raises(sc.StudyRegistrationError, match="timezone-aware"):
        sc.check_study_data(path, "HYP-0001", {"symbols": {"BTCUSDT": {"first_open": 4_100_000_000_000,
                                                                       "last_open": 4_100_000_060_000}}})
