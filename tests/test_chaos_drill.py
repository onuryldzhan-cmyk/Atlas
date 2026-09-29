"""Failure drill (registry v5.59): a missing or failing scenario is never reported as caught."""

from __future__ import annotations

from tools import chaos_drill


def test_every_scenario_names_an_existing_test_file():
    for nodes in chaos_drill.SCENARIOS.values():
        for node in nodes:
            path = chaos_drill.ROOT / node.split("::")[0]
            assert path.is_file(), node
            assert f"def {node.split('::')[1]}" in path.read_text(encoding="utf-8"), node


def test_a_missing_scenario_is_not_run_and_fails_the_drill():
    out = chaos_drill.run({"X": ["tests/test_chaos_drill.py::test_does_not_exist"]})
    assert out["all_pass"] is False and out["groups"]["X"]["test_does_not_exist"] == "NOT RUN"
