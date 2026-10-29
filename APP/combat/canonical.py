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


_is_normalized = unicodedata.is_normalized


def _already_canonical(value: Any) -> bool:
    """True when ``value`` is made only of exact ``None``/``bool``/``int``/``str``/``list``/``tuple``/``dict`` values whose
    strings and keys are already NFC.  Such a value needs no normalised copy: ``json.dumps`` writes it exactly as it
    would write ``_normalize(value)`` (a tuple is written as a list; a dict's keys are already distinct strings, and
    distinct NFC strings cannot collide).  Anything else -- a float, a key that is not a string, a string that
    changes under NFC, a subclass, an unsupported type -- answers False and takes the checked path below, which
    also produces every error message."""
    kind = type(value)
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str or not (key.isascii() or _is_normalized("NFC", key)):
                return False
            kind = type(item)
            if kind is str:
                if not (item.isascii() or _is_normalized("NFC", item)):
                    return False
            elif kind is int or kind is bool or item is None:
                continue
            elif not _already_canonical(item):
                return False
        return True
    if kind is list or kind is tuple:
        for item in value:
            kind = type(item)
            if kind is str:
                if not (item.isascii() or _is_normalized("NFC", item)):
                    return False
            elif kind is int or kind is bool or item is None:
                continue
            elif not _already_canonical(item):
                return False
        return True
    if kind is str:
        return value.isascii() or _is_normalized("NFC", value)
    return kind is int or kind is bool or value is None


def canonical_bytes(value: Any) -> bytes:
    # The common case (a plain JSON document that is already NFC) is dumped as it is; the normalising copy is only
    # built when something needs it (or must be rejected, with its exact path in the message).
    normalized = value if _already_canonical(value) else _normalize(value)
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
