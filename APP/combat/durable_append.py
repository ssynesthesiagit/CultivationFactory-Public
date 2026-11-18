"""Shared durable JSON-lines append for controller journals and commit diagnostics."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes


def append_jsonl(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_bytes(document) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        while payload:
            written = os.write(fd, payload)
            if written <= 0:
                raise OSError("JSONL write made no progress")
            payload = payload[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
