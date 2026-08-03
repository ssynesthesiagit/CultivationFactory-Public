from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(root: Path) -> dict:
    resolved = root.resolve()
    files = []
    if resolved.is_dir():
        for path in sorted((item for item in resolved.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
            files.append({
                "path": path.relative_to(resolved).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            })
    return {
        "root": str(resolved),
        "exists": resolved.exists(),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "schema": "Tianxia.W5P1FilesystemInventory.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "roots": [inventory(root) for root in args.root],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
