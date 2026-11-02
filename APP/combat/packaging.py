from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .canonical import canonical_bytes, sha256_bytes, sha256_file

PACK_MANIFEST = "pack.json"
EXCLUDED_PAYLOAD_PATHS = {PACK_MANIFEST, "SHA256SUMS.txt"}
FIXED_ZIP_DATETIME = (2020, 1, 1, 0, 0, 0)


def iter_payload_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.relative_to(root).as_posix() not in EXCLUDED_PAYLOAD_PATHS
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def canonical_payload_hash_from_directory(root: Path) -> str:
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in iter_payload_files(root)
    ]
    return sha256_bytes(canonical_bytes({"payload_domain_version": "1", "files": records}))


def build_deterministic_zip(source_dir: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted((p for p in source_dir.rglob("*") if p.is_file()), key=lambda p: p.relative_to(source_dir).as_posix()):
            relative = path.relative_to(source_dir).as_posix()
            info = zipfile.ZipInfo(relative, date_time=FIXED_ZIP_DATETIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    os.replace(temporary, destination)


def rewrite_manifest_payload_hash(pack_dir: Path) -> dict:
    manifest_path = pack_dir / PACK_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["canonical_payload_hash"] = canonical_payload_hash_from_directory(pack_dir)
    manifest_path.write_bytes(canonical_bytes(manifest) + b"\n")
    return manifest
