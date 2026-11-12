"""
Atlas Project Snapshot Engine
Version: 1.0

Creates a complete snapshot of the Atlas codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json


@dataclass
class ProjectSnapshot:
    version: str
    scan_time: str
    root: str

    total_files: int
    python_files: int

    total_lines: int

    total_classes: int
    total_functions: int

    folders: int

    largest_file: str
    largest_file_lines: int


class ProjectSnapshotEngine:

    VERSION = "1.0"

    def __init__(self, root: str | Path):

        self.root = Path(root)

    def create_snapshot(self) -> ProjectSnapshot:

        total_files = 0
        python_files = 0
        total_lines = 0

        total_classes = 0
        total_functions = 0

        largest_file = ""
        largest_lines = 0

        folders = 0

        for path in self.root.rglob("*"):

            if path.is_dir():
                folders += 1
                continue

            total_files += 1

            if path.suffix != ".py":
                continue

            python_files += 1

            try:

                text = path.read_text(
                    encoding="utf-8",
                    errors="ignore"
                )

            except Exception:
                continue

            lines = text.splitlines()

            line_count = len(lines)

            total_lines += line_count

            if line_count > largest_lines:

                largest_lines = line_count
                largest_file = str(path.relative_to(self.root))

            for line in lines:

                s = line.strip()

                if s.startswith("class "):
                    total_classes += 1

                elif s.startswith("def "):
                    total_functions += 1

        return ProjectSnapshot(

            version=self.VERSION,

            scan_time=datetime.now(
                timezone.utc
            ).isoformat(),

            root=str(self.root),

            total_files=total_files,

            python_files=python_files,

            total_lines=total_lines,

            total_classes=total_classes,

            total_functions=total_functions,

            folders=folders,

            largest_file=largest_file,

            largest_file_lines=largest_lines

        )

    def save(self, output_file: str | Path):

        snapshot = self.create_snapshot()

        output = Path(output_file)

        output.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            output,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                asdict(snapshot),
                f,
                indent=4,
                ensure_ascii=False
            )

        return snapshot