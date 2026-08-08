"""Build and validate the canonical Atlas runtime distribution.

This tool defines a deterministic boundary over the tracked source tree. It
does not replace the independent-review provenance export.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    REPOSITORY_ROOT
    / "packaging"
    / "atlas_runtime_distribution_manifest.json"
)
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class DistributionBoundaryError(RuntimeError):
    """Raised when the requested distribution violates its boundary."""


def _load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise DistributionBoundaryError("unsupported distribution manifest")
    return data


def _normalize_relative_path(value: str) -> str:
    raw_candidate = str(value).replace("\\", "/")
    candidate = raw_candidate.strip("/")
    path = PurePosixPath(candidate)
    if (
        not candidate
        or raw_candidate.startswith("/")
        or path.is_absolute()
        or ".." in path.parts
        or ":" in path.parts[0]
    ):
        raise DistributionBoundaryError(
            f"unsafe repository-relative path: {value!r}"
        )
    return path.as_posix()


def _flatten_exclusions(manifest: dict[str, Any]) -> tuple[str, ...]:
    exclusions = manifest.get("exclusions")
    if not isinstance(exclusions, dict):
        raise DistributionBoundaryError("manifest exclusions must be an object")
    patterns: list[str] = []
    for values in exclusions.values():
        if not isinstance(values, list):
            raise DistributionBoundaryError("exclusion groups must be arrays")
        patterns.extend(_normalize_relative_path(value) for value in values)
    return tuple(patterns)


def _matches(path: str, pattern: str) -> bool:
    if "/" not in pattern:
        return fnmatch.fnmatchcase(path, pattern)
    pure_path = PurePosixPath(path)
    return pure_path.match(pattern) or fnmatch.fnmatchcase(path, pattern)


def _is_excluded(
    path: str,
    patterns: Iterable[str],
    allowed_paths: Iterable[str] = (),
) -> bool:
    if path in set(allowed_paths):
        return False
    return any(_matches(path, pattern) for pattern in patterns)


def _tracked_files(repository_root: Path) -> list[str]:
    completed = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repository_root.as_posix()}",
            "-c",
            "core.quotepath=false",
            "ls-files",
            "-z",
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )
    return sorted(
        _normalize_relative_path(item.decode("utf-8"))
        for item in completed.stdout.split(b"\0")
        if item
    )


def select_distribution_files(
    repository_root: Path,
    manifest: dict[str, Any],
    *,
    include_tests: bool,
    tracked_files: Iterable[str] | None = None,
) -> list[str]:
    include_values: list[str] = []
    for field in (
        "canonical_runtime_files",
        "canonical_runtime_source_paths",
        "canonical_configuration_paths",
    ):
        values = manifest.get(field, [])
        if not isinstance(values, list):
            raise DistributionBoundaryError(f"{field} must be an array")
        include_values.extend(_normalize_relative_path(value) for value in values)
    if include_tests:
        include_values.extend(
            _normalize_relative_path(value)
            for value in manifest.get("canonical_test_paths", [])
        )

    exclusions = _flatten_exclusions(manifest)
    allowed_paths = tuple(
        _normalize_relative_path(value)
        for value in manifest.get("safe_public_templates", [])
    )
    candidates = (
        list(tracked_files)
        if tracked_files is not None
        else _tracked_files(repository_root)
    )
    selected: list[str] = []
    for raw_path in candidates:
        path = _normalize_relative_path(raw_path)
        included = any(
            path == value or path.startswith(value + "/")
            for value in include_values
        )
        if included and not _is_excluded(path, exclusions, allowed_paths):
            resolved = (repository_root / path).resolve()
            try:
                resolved.relative_to(repository_root.resolve())
            except ValueError as exc:
                raise DistributionBoundaryError(
                    f"selected path escapes repository: {path}"
                ) from exc
            if resolved.is_file():
                selected.append(path)
    return sorted(set(selected))


def validate_import_boundaries(
    repository_root: Path,
    selected_files: Iterable[str],
    manifest: dict[str, Any],
) -> list[str]:
    patterns = tuple(manifest.get("excluded_module_patterns", []))
    violations: list[str] = []
    for relative_path in selected_files:
        if not relative_path.endswith(".py"):
            continue
        tree = ast.parse(
            (repository_root / relative_path).read_text(encoding="utf-8-sig"),
            filename=relative_path,
        )
        imported: list[str] = []
        source_path = PurePosixPath(relative_path)
        package_parts = list(source_path.with_suffix("").parts[:-1])
        if source_path.name == "__init__.py":
            package_parts = list(source_path.parts[:-1])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    trim = max(node.level - 1, 0)
                    base = package_parts[: len(package_parts) - trim]
                    module_parts = node.module.split(".") if node.module else []
                    resolved = ".".join(base + module_parts)
                    if resolved:
                        imported.append(resolved)
                    if node.module is None:
                        imported.extend(
                            ".".join(base + [alias.name])
                            for alias in node.names
                        )
                elif node.module:
                    imported.append(node.module)
        for module in imported:
            if any(fnmatch.fnmatchcase(module, pattern) for pattern in patterns):
                violations.append(f"{relative_path}: {module}")
    return sorted(violations)


def build_distribution(
    output_path: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    include_tests: bool | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    manifest = _load_manifest(manifest_path.resolve())
    if include_tests is None:
        include_tests = bool(manifest.get("default_include_tests", False))
    selected = select_distribution_files(
        repository_root,
        manifest,
        include_tests=include_tests,
    )
    boundary_files = [
        path for path in selected
        if not path.startswith("tests/") and path != "pytest.ini"
    ]
    violations = validate_import_boundaries(
        repository_root,
        boundary_files,
        manifest,
    )
    if violations:
        raise DistributionBoundaryError(
            "canonical source imports excluded modules: " + "; ".join(violations)
        )
    if not selected:
        raise DistributionBoundaryError("distribution selection is empty")

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for relative_path in selected:
                data = (repository_root / relative_path).read_bytes()
                info = zipfile.ZipInfo(relative_path, FIXED_ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (
                    stat.S_IFREG | stat.S_IRUSR | stat.S_IWUSR
                    | stat.S_IRGRP | stat.S_IROTH
                ) << 16
                archive.writestr(info, data, compresslevel=9)
        os.replace(temporary_path, output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest().upper()
    return {
        "artifact": str(output_path),
        "file_count": len(selected),
        "include_tests": include_tests,
        "sha256": digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument("--list", action="store_true", dest="list_only")
    args = parser.parse_args()
    manifest = _load_manifest(args.manifest.resolve())
    if args.list_only:
        for path in select_distribution_files(
            REPOSITORY_ROOT,
            manifest,
            include_tests=args.include_tests,
        ):
            print(path)
        return 0
    result = build_distribution(
        args.output,
        manifest_path=args.manifest,
        include_tests=args.include_tests,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
