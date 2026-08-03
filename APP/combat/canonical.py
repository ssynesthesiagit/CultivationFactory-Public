from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

CANONICAL_FORMAT_VERSION = "tianxia.canonical-json.v1"


class CanonicalValueError(ValueError):
    pass


def _normalize(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        raise CanonicalValueError(f"Binary floating point is not allowed at {path}.")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, tuple):
        return [_normalize(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalValueError(f"Object keys must be strings at {path}.")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise CanonicalValueError(f"NFC-normalized duplicate key {normalized_key!r} at {path}.")
            normalized[normalized_key] = _normalize(item, f"{path}.{normalized_key}")
        return normalized
    raise CanonicalValueError(f"Unsupported canonical value {type(value).__name__} at {path}.")


def canonical_bytes(value: Any) -> bytes:
    normalized = _normalize(value)
    text = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text.encode("utf-8")


def canonical_text(value: Any) -> str:
    return canonical_bytes(value).decode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
