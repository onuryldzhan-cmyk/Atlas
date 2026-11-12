"""Read-only pre-flight: print Atlas's effective configuration (CFG-001).

Runs the same validation main.py runs at startup and prints either the
effective values or every problem found. Takes no lock, writes nothing,
prints no secrets (the configuration holds none).

Usage:
  python -m tools.show_config
"""

from __future__ import annotations

import os
import sys

from core.atlas_config import AtlasConfigError, load_config
from main import EXECUTION_MODE, PAPER_CONFIDENCE_EXPERIMENT


def main() -> int:
    try:
        config = load_config(
            os.environ,
            execution_mode=EXECUTION_MODE,
            paper_confidence_experiment=PAPER_CONFIDENCE_EXPERIMENT,
        )
    except AtlasConfigError as exc:
        print(f"INVALID - Atlas would refuse to start ({len(exc.errors)} problem(s)):")
        for problem in exc.errors:
            print(f"  - {problem}")
        return 1

    for key, value in config.describe().items():
        print(f"{key}: {value}")
    print("OK - configuration valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
