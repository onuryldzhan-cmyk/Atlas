"""Backup and restore of Atlas's durable state, with integrity verification (audit finding F-6).

  python -m tools.state_backup backup  --out D:\\AtlasBackups          # state + governance records
  python -m tools.state_backup verify  D:\\AtlasBackups\\20260930T120000Z
  python -m tools.state_backup restore D:\\AtlasBackups\\20260930T120000Z --target C:\\AtlasState_restored

Run with Atlas STOPPED, so the files are not being written while they are copied.

* backup  copies the state directory (financial state, journal, idempotency,
          audit, risk accounting, closed positions) and governance/records into
          a new timestamped folder, with a manifest holding each file's
          sha256, size and the schema tag found inside it.
* verify  recomputes every hash; any mismatch, missing or extra file means
          the backup is CORRUPTED and must not be used.
* restore verifies first, refuses a non-empty target (it never overwrites
          live state), copies, re-verifies the copy and checks that every
          .json / .jsonl file still parses. Reconciliation after a restore is
          the existing startup recovery; Atlas must be started against the
          restored directory deliberately by the owner.

Files that look like secrets (.env, *key*, *secret*, *token*) are never copied.
Nothing here is imported by the runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST = "atlas_backup_manifest.json"
FORMAT = "atlas-state-backup-v1"
SECRET_MARKERS = (".env", "key", "secret", "token", "password")


class BackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_secret(path: Path) -> bool:
    name = path.name.lower()
    return any(m in name for m in SECRET_MARKERS)


def _schema_tag(path: Path) -> str | None:
    if path.suffix not in (".json", ".jsonl"):
        return None
    try:
        with path.open(encoding="utf-8") as f:
            first = f.readline() if path.suffix == ".jsonl" else f.read()
        data = json.loads(first) if first.strip() else {}
    except (ValueError, OSError):
        return "UNPARSEABLE"
    return str(data.get("schema") or data.get("schema_version") or "") or None if isinstance(data, dict) else None


def _files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and not _is_secret(p) and not p.name.endswith(".tmp"))


def backup(sources: dict[str, Path], out_dir: Path, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    dest = out_dir / stamp
    if dest.exists():
        raise BackupError(f"{dest} already exists")
    entries = []
    for label, root in sources.items():
        if not root.exists():
            raise BackupError(f"source {label} missing: {root}")
        for src in _files(root):
            rel = Path(label) / src.relative_to(root)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            entries.append({"path": rel.as_posix(), "sha256": _sha256(target), "bytes": target.stat().st_size,
                            "schema": _schema_tag(target)})
    manifest = {"format": FORMAT, "created_at": stamp, "sources": {k: str(v) for k, v in sources.items()},
                "files": entries}
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    verify(dest)
    return dest


def verify(backup_dir: Path) -> dict[str, Any]:
    manifest_path = backup_dir / MANIFEST
    if not manifest_path.exists():
        raise BackupError("CORRUPTED: manifest missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise BackupError("CORRUPTED: manifest unreadable") from exc
    if manifest.get("format") != FORMAT:
        raise BackupError("CORRUPTED: unknown backup format")
    listed = {e["path"] for e in manifest["files"]}
    present = {p.relative_to(backup_dir).as_posix() for p in backup_dir.rglob("*") if p.is_file() and p.name != MANIFEST}
    if listed != present:
        raise BackupError(f"CORRUPTED: missing {sorted(listed - present)[:3]} extra {sorted(present - listed)[:3]}")
    for e in manifest["files"]:
        if _sha256(backup_dir / e["path"]) != e["sha256"]:
            raise BackupError(f"CORRUPTED: hash mismatch {e['path']}")
    return manifest


def restore(backup_dir: Path, target: Path) -> dict[str, Any]:
    manifest = verify(backup_dir)
    if target.exists() and any(target.iterdir()):
        raise BackupError("REFUSED: target is not empty (restore never overwrites live state)")
    target.mkdir(parents=True, exist_ok=True)
    for e in manifest["files"]:
        dst = target / e["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_dir / e["path"], dst)
        if _sha256(dst) != e["sha256"]:
            raise BackupError(f"RESTORE FAILED: copy mismatch {e['path']}")
        if dst.suffix == ".json":
            json.loads(dst.read_text(encoding="utf-8"))
        elif dst.suffix == ".jsonl":
            for line in dst.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
    return {"restored_files": len(manifest["files"]), "from": manifest["created_at"], "target": str(target)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup"); b.add_argument("--out", required=True)
    v = sub.add_parser("verify"); v.add_argument("backup_dir")
    r = sub.add_parser("restore"); r.add_argument("backup_dir"); r.add_argument("--target", required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "backup":
            from core.application import resolve_state_directory

            root = Path(__file__).resolve().parents[1]
            dest = backup({"state": resolve_state_directory(), "governance_records": root / "governance" / "records"},
                          Path(args.out))
            print(f"YEDEK TAMAM: {dest}")
        elif args.cmd == "verify":
            m = verify(Path(args.backup_dir))
            print(f"SAĞLAM: {len(m['files'])} dosya, {m['created_at']}")
        else:
            out = restore(Path(args.backup_dir), Path(args.target))
            print(f"GERİ YÜKLENDİ: {out['restored_files']} dosya -> {out['target']} (Atlas'ı bu klasörle başlatmak senin kararın)")
    except BackupError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
