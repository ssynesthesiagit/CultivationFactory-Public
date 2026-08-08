from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import PurePosixPath
from typing import Any


REQUIRED_ROOT_FILES = {"README_START_HERE.md", "MANIFEST.json", "SHA256SUMS.txt"}


def validate_handoff_package(payload: bytes) -> dict[str, Any]:
    """Validate the small, owner-facing handoff envelope before it is published."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise ValueError("handoff is not a ZIP archive") from exc
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError("handoff contains duplicate members")
    unsafe = [name for name in names if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts]
    if unsafe:
        raise ValueError(f"handoff contains unsafe members: {unsafe}")
    missing = sorted(REQUIRED_ROOT_FILES.difference(names))
    if missing:
        raise ValueError("handoff missing required root files: " + ", ".join(missing))
    try:
        manifest = json.loads(archive.read("MANIFEST.json"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("handoff MANIFEST.json is not valid JSON") from exc
    if not isinstance(manifest, dict) or not manifest.get("status"):
        raise ValueError("handoff MANIFEST.json must declare status")
    declared: dict[str, str] = {}
    for line in archive.read("SHA256SUMS.txt").decode("ascii").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        declared[name] = digest
    if set(declared) != set(names) - {"SHA256SUMS.txt"}:
        raise ValueError("handoff SHA256SUMS.txt inventory does not match the archive")
    for name, digest in declared.items():
        actual = hashlib.sha256(archive.read(name)).hexdigest()
        if actual != digest:
            raise ValueError(f"handoff checksum mismatch: {name}")
    return {"manifest": manifest, "members": sorted(names), "valid": True}
