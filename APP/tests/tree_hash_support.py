"""Pure file-tree hashing helper shared by replay/storage tests."""
from __future__ import annotations

import hashlib
from pathlib import Path


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != ".writer.lock"
    }


