"""Read-only, source-content-keyed setup for repeated character compilation.

The authority is large, while an individual compiler consumes only a small
part of it. Re-reading and hashing the bytes on every call keeps source edits
observable (including edits that preserve file size and mtime); only JSON
parsing is reused. One entry bounds retained data in each interpreter. No
cache files, mutable combat state, compiled bundles, or validation results are
shared between tests or workers.

The private containers remain dict/list instances for existing readers. They
reject normal mutation methods; deepcopy returns ordinary independent mutable
containers when a compiler needs to edit a selected record or effect tree.
They are a defensive internal convention, not a security boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any


def _read_only(*_args: Any, **_kwargs: Any) -> None:
    raise TypeError("Cached authority is read-only; deepcopy the records to edit them.")


class _FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _read_only

    def __copy__(self) -> dict:
        return dict(self)

    def __deepcopy__(self, memo: dict[int, Any]) -> dict:
        result: dict = {}
        memo[id(self)] = result
        result.update((copy.deepcopy(key, memo), copy.deepcopy(value, memo)) for key, value in self.items())
        return result


class _FrozenList(list):
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _read_only

    def __copy__(self) -> list:
        return list(self)

    def __deepcopy__(self, memo: dict[int, Any]) -> list:
        result: list = []
        memo[id(self)] = result
        result.extend(copy.deepcopy(value, memo) for value in self)
        return result


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict((key, _freeze(item)) for key, item in value.items())
    if isinstance(value, list):
        return _FrozenList(_freeze(item) for item in value)
    return value


class _AuthorityCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._source_sha256: str | None = None
        self._value: Any = None

    def read(self, path: Path) -> tuple[Any, str]:
        # Read before consulting the cache: deleted/unreadable files must not
        # silently use an older snapshot. The digest binds this exact read to
        # both its parsed data and the compiler's existing provenance field.
        source = path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        with self._lock:
            if digest != self._source_sha256:
                value = _freeze(json.loads(source))
                # A parse failure never publishes a partial or invalid entry.
                self._value = value
                self._source_sha256 = digest
            return self._value, digest


_CACHE = _AuthorityCache()


def read_authority(path: Path) -> tuple[Any, str]:
    """Return read-only authority data and the SHA-256 of its current bytes."""
    return _CACHE.read(path)
