"""Owner-run repair of the S1 risk-bucket sidecar (re-audit R-2).

  python -m tools.position_risk_buckets_repair <state>/position_risk_buckets.jsonl

Drops only an unfinished last line (a crash mid-write) and keeps a .bak copy.
Any other damage is refused. Run with Atlas stopped. Not imported by the runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

from core.position_risk_buckets import repair_unfinished_tail


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        print(repair_unfinished_tail(Path(args[0])))
    except (OSError, ValueError) as exc:
        print(f"HATA: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
