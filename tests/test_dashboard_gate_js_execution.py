"""Executes the dashboard's gate JavaScript for real, instead of pinning its
source text.

templates/dashboard.html has no build step and no JS test runner; every
prior test of `assessRiskGate` (tests/test_dashboard_execution_gates.py)
only regex-matches the function's source text, so a logic change that
happens to preserve the pinned substrings would pass unnoticed. This module
extracts the same client-side helpers the independent audit exercised ad
hoc with a node harness while verifying commit 6ac94f8's F1 fix, and runs
that harness as a real regression test: it slices the script out of the
template (same start-of-<script> to end-of-assessRiskGate boundary as
tests/test_dashboard_execution_gates.py's text-pin regex), feeds it to
`node` with a stubbed `executionGates`, and asserts on the actual return
value of `assessRiskGate(signal)` - not on strings inside its source.

Skips (not fails) if `node` is not on PATH, since the template itself does
not depend on Node at runtime; this only needs it to test the browser JS
from Python.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_TEMPLATE = REPOSITORY_ROOT / "templates" / "dashboard.html"

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not on PATH")


def _extract_gate_script() -> str:
    """The client-side helpers assessRiskGate depends on, verbatim from the
    template: from the start of the (single) <script> block through the end
    of the assessRiskGate function body. Nothing below that point runs
    (no fetch()/document/setInterval calls are reached), so this slice is
    safe to eval standalone in node.
    """

    body = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    start = body.index("<script>") + len("<script>")
    end_marker = "\n            return { html, blocked, markers };\n        }\n"
    end = body.index(end_marker, start) + len(end_marker)
    script = body[start:end]
    # This slice is Jinja source, not plain JS: strip {# ... #} comments and
    # substitute the one {{ symbol }} interpolation with a literal, exactly
    # what Jinja rendering would leave behind for this constant.
    script = re.sub(r"\{#.*?#\}", "", script, flags=re.DOTALL)
    script = script.replace("{{ symbol }}", "BTCUSDT")
    assert "{{" not in script and "{#" not in script
    assert "function assessRiskGate(signal)" in script
    assert "function bucketGate(level)" in script
    return script


GATE_SCRIPT = _extract_gate_script()

def _harness(execution_gates: dict, signal: dict) -> str:
    # Plain concatenation, not str.format: the extracted script's own JS
    # object literals and comments are full of unescaped "{"/"}".
    return (
        # A minimal stand-in for the one browser global the extracted slice
        # touches at module-evaluation time (a Chart.js feature check); not
        # reached by assessRiskGate itself.
        "global.window = { Chart: undefined };\n"
        + GATE_SCRIPT
        # The extracted script already declares `let executionGates = null;`
        # (the module-level cache assessRiskGate's helpers read from) -
        # reassign it rather than redeclaring, which node's strict-per-file
        # scoping rejects as a duplicate `let`/`const`.
        + "\nexecutionGates = " + json.dumps(execution_gates) + ";"
        + "\nconst signal = " + json.dumps(signal) + ";"
        + "\nconst result = assessRiskGate(signal);"
        + "\nprocess.stdout.write(JSON.stringify({ blocked: result.blocked, html: result.html }));\n"
    )


def _run_gate(execution_gates: dict, signal: dict, tmp_path: Path) -> dict:
    harness = _harness(execution_gates, signal)
    harness_path = tmp_path / "gate_harness.js"
    harness_path.write_text(harness, encoding="utf-8")
    completed = subprocess.run(
        [NODE, str(harness_path)],
        capture_output=True,
        encoding="utf-8",  # node writes UTF-8; the Windows locale default is not
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


_POLICY = {
    "available": True,
    "version": "gate-js-test-v1",
    "buckets": {
        "LOW": {"minimum_confidence_pct": 60.0, "required_confidence_pct": 60.0},
    },
}


def _gates(execution_minimum: float | None, policy: dict | None = None) -> dict:
    return {
        "available": True,
        "execution_minimum_confidence": execution_minimum,
        "risk_policy": policy if policy is not None else _POLICY,
    }


def _signal(action: str, confidence: float, level: str = "LOW") -> dict:
    return {"symbol": "BTCUSDT", "action": action, "confidence": confidence, "risk_level": level}


# ---------------------------------------------------------------------
# Baseline behaviour (guards against a future change breaking these too)
# ---------------------------------------------------------------------


def test_a_buy_above_both_floors_passes(tmp_path: Path) -> None:
    result = _run_gate(_gates(60.0), _signal("BUY", 61.0), tmp_path)
    assert result["blocked"] is False
    assert "gate-pass" in result["html"]


def test_a_buy_below_the_bucket_floor_is_blocked(tmp_path: Path) -> None:
    result = _run_gate(_gates(60.0), _signal("BUY", 59.0), tmp_path)
    assert result["blocked"] is True
    assert "gate-fail" in result["html"]


def test_a_buy_is_never_shown_passing_while_the_execution_gate_is_unknown(tmp_path: Path) -> None:
    result = _run_gate(_gates(None), _signal("BUY", 65.0), tmp_path)
    assert result["blocked"] is False
    assert "gate-pass" not in result["html"]
    assert "execution gate eşiği bilinmiyor" in result["html"]


def test_hold_is_never_blocked_even_below_every_floor(tmp_path: Path) -> None:
    result = _run_gate(_gates(60.0), _signal("HOLD", 10.0), tmp_path)
    assert result["blocked"] is False


# ---------------------------------------------------------------------
# F2: the execution gate applies to SELL too, and to a BUY whose risk
# bucket is unreadable, not only to a BUY that clears the (readable)
# bucket gate but misses the (readable) execution gate.
# ---------------------------------------------------------------------


def test_a_sell_below_the_execution_gate_is_now_blocked(tmp_path: Path) -> None:
    result = _run_gate(_gates(60.0), _signal("SELL", 59.0), tmp_path)
    assert result["blocked"] is True
    assert "gate-fail" in result["html"]


def test_a_sell_above_the_execution_gate_is_not_blocked(tmp_path: Path) -> None:
    result = _run_gate(_gates(60.0), _signal("SELL", 61.0), tmp_path)
    assert result["blocked"] is False


def test_a_sell_with_no_execution_minimum_known_is_not_blocked(tmp_path: Path) -> None:
    # Nothing to compare confidence against - must not be invented as a fail.
    result = _run_gate(_gates(None), _signal("SELL", 10.0), tmp_path)
    assert result["blocked"] is False


def test_a_buy_below_the_execution_gate_is_blocked_even_when_risk_policy_is_unreadable(tmp_path: Path) -> None:
    unreadable = {
        "available": True,
        "execution_minimum_confidence": 60.0,
        "risk_policy": {"available": False, "reason": "RISK_POLICY_UNAVAILABLE"},
    }
    result = _run_gate(unreadable, _signal("BUY", 59.0), tmp_path)
    assert result["blocked"] is True
    assert "gate-fail" in result["html"]


def test_a_buy_above_the_execution_gate_with_risk_policy_unreadable_is_not_blocked(tmp_path: Path) -> None:
    unreadable = {
        "available": True,
        "execution_minimum_confidence": 60.0,
        "risk_policy": {"available": False, "reason": "RISK_POLICY_UNAVAILABLE"},
    }
    result = _run_gate(unreadable, _signal("BUY", 65.0), tmp_path)
    assert result["blocked"] is False


def test_a_buy_below_the_execution_gate_is_blocked_when_the_bucket_has_no_policy_entry(tmp_path: Path) -> None:
    # RiskEngine rejects new risk outright when the level has no bucket -
    # the BUY is already blocked for that reason; the execution-gate wording
    # is additionally appended when it also fails, without changing the
    # already-blocked outcome.
    no_bucket_policy = {"available": True, "version": "v1", "buckets": {}}
    result = _run_gate(_gates(60.0, no_bucket_policy), _signal("BUY", 10.0, level="CRITICAL"), tmp_path)
    assert result["blocked"] is True


def test_a_sell_is_blocked_when_the_bucket_has_no_policy_entry_and_execution_gate_fails(tmp_path: Path) -> None:
    no_bucket_policy = {"available": True, "version": "v1", "buckets": {}}
    result = _run_gate(_gates(60.0, no_bucket_policy), _signal("SELL", 10.0, level="CRITICAL"), tmp_path)
    assert result["blocked"] is True
    assert "execute edilmez" in result["html"] or "execution gate" in result["html"]


def test_a_sell_is_not_blocked_when_the_bucket_has_no_policy_entry_but_execution_gate_passes(tmp_path: Path) -> None:
    no_bucket_policy = {"available": True, "version": "v1", "buckets": {}}
    result = _run_gate(_gates(60.0, no_bucket_policy), _signal("SELL", 90.0, level="CRITICAL"), tmp_path)
    assert result["blocked"] is False
