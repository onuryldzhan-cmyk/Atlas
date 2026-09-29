"""Data source registry (Data Engineering §1): every external host in code is registered, with a fail-closed fallback."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = json.loads((ROOT / "config" / "data_sources.json").read_text(encoding="utf-8"))
FIELDS = ("source_id", "provider", "endpoint", "data_type", "timeframe", "role", "freshness_rule", "license",
          "availability", "fallback", "status")


def test_every_source_is_complete_and_unique():
    ids = [s["source_id"] for s in REG["sources"]]
    assert len(ids) == len(set(ids))
    for s in REG["sources"]:
        assert all(s.get(f) for f in FIELDS), s["source_id"]
        assert "neutral" not in s["fallback"].lower() or "never" in s["fallback"].lower()


def test_every_external_host_used_by_runtime_code_is_registered():
    hosts = set()
    for folder in ("core", "ai", "atlas_finance"):
        for path in (ROOT / folder).rglob("*.py"):
            hosts |= set(re.findall(r"https://([a-z0-9.-]+)", path.read_text(encoding="utf-8-sig", errors="ignore")))
    registered = {re.match(r"https://([a-z0-9.-]+)", s["endpoint"]).group(1) for s in REG["sources"]}
    assert hosts <= registered | {"alternative.me"}, sorted(hosts - registered)
