"""Every degradation row points at code that really contains its behaviour (no paper-only claims)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = json.loads((ROOT / "config" / "degradation_matrix.json").read_text(encoding="utf-8"))


def test_every_behaviour_has_code_evidence():
    missing = []
    for row in MATRIX["components"]:
        assert row["behaviour"] and row["failure"]
        for rel, needle in row["evidence"].items():
            text = (ROOT / rel).read_text(encoding="utf-8-sig", errors="ignore")
            if needle not in text:
                missing.append(f"{row['component']}: '{needle}' not in {rel}")
    assert missing == [], missing
