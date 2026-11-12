"""Record/aspect access shared by compilation, typed numbers, and impact tooling.

No exported data changes. A full record is deliberately the default: existing
name-based mechanical consumers must not claim a presentation-free dependency.
Explicit aspect views contain ONLY that aspect's fields. Iteration is an explicit
aggregate dependency, not an inference from the records returned this time.

The pytest recorder subscribes to events; without a subscriber these operations
only read data. The cache uses boundary_read to distinguish its internal file IO
from an unconverted whole-file reader. See tools/record_impact.schema.json.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import PurePosixPath
from typing import Callable

ASPECTS = frozenset({"mechanics", "presentation", "provenance", "membership", "rules", "*"})
PRESENTATION = frozenset({"name", "description", "notes"})
PROVENANCE = frozenset({"source", "provenance", "coverage", "typing_status", "structure_source",
                        "insight_reviewed_text_sha256", "owner_edit"})
_observer: Callable[[str, str], None] | None = None
_inside_read: ContextVar[bool] = ContextVar("authority_boundary_read", default=False)


def observe(record_id: str, aspect: str) -> None:
    if callback := _observer:
        callback(record_id, aspect)


@contextmanager
def recording(callback):
    global _observer
    previous, _observer = _observer, callback
    try:
        yield
    finally:
        _observer = previous


@contextmanager
def boundary_read():
    token = _inside_read.set(True)
    try:
        yield
    finally:
        _inside_read.reset(token)


def inside_boundary_read() -> bool:
    """Public audit seam used by the pytest recorder (thread-local IO scope)."""
    return _inside_read.get()


def source_paths(document: dict) -> set[str]:
    """APP-relative source locators used by the selector and raw-reader audit.

    Derived from builder output, never a maintained list of readers or records.
    Package-internal/unresolved locators remain unknown to the selector.
    """
    return {"APP/" + PurePosixPath(source).as_posix()
            for row in document["mechanics"].values()
            if isinstance(source := (row.get("source") or {}).get("path"), str)
            and source and not PurePosixPath(source).is_absolute()
            and ".." not in PurePosixPath(source).parts}


def project(row: dict, aspect: str) -> dict:
    if aspect == "*":
        return row
    if aspect == "presentation":
        return {key: value for key, value in row.items() if key in PRESENTATION}
    if aspect == "provenance":
        return {key: value for key, value in row.items() if key in PROVENANCE}
    if aspect == "mechanics":
        return {key: value for key, value in row.items() if key not in PRESENTATION | PROVENANCE}
    raise ValueError(f"Not a record aspect: {aspect}")


class RecordMap(dict):
    """Compatibility mapping: lookups declare records, enumeration declares an aggregate.

    Used by factory_compiler and typed_numbers. No result truncation or inferred
    sibling/target/resource relationships: all actual accesses are observed.
    """
    def __init__(self, rows: Mapping, aspect: str = "*", namespace: str = "records"):
        if aspect not in ASPECTS:
            raise ValueError(aspect)
        dict.__init__(self, rows)
        self._rows, self.aspect, self.namespace = rows, aspect, namespace

    def _id(self, key):
        return key if self.namespace == "records" else f"@{self.namespace}:{key}"

    def __getitem__(self, key):
        observe(self._id(key), self.aspect)
        value = self._rows[key]
        return project(value, self.aspect) if isinstance(value, dict) else value

    def __repr__(self):
        return repr(self.copy())

    def __reversed__(self):
        observe(f"@{self.namespace}", "membership")
        return reversed(self._rows)

    def __ne__(self, other):
        return not self == other

    def __iter__(self):
        observe(f"@{self.namespace}", "membership")
        return iter(self._rows)

    def __len__(self):
        observe(f"@{self.namespace}", "membership")
        return len(self._rows)

    def __contains__(self, key):
        observe(self._id(key), "membership")
        return key in self._rows

    def items(self):
        observe(f"@{self.namespace}", self.aspect)
        return Mapping.items(self)

    def values(self):
        observe(f"@{self.namespace}", self.aspect)
        return Mapping.values(self)

    def keys(self):
        observe(f"@{self.namespace}", "membership")
        return Mapping.keys(self)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def copy(self):
        return dict(self.items())

    def __copy__(self):
        return self.copy()

    def __deepcopy__(self, memo):
        return copy.deepcopy(self.copy(), memo)

    def __or__(self, other):
        return self.copy() | other

    def __ror__(self, other):
        return other | self.copy()

    def __eq__(self, other):
        observe(f"@{self.namespace}", self.aspect)
        return self.copy() == other

    def _read_only(self, *_args, **_kwargs):
        raise TypeError("Authority query mappings are read-only; copy before editing.")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _read_only


class Authority:
    """A read-only query boundary over the existing builder output.

    record() declares one actual lookup (including absent IDs); records() exposes
    explicit enumeration/index queries. aggregate() declares a whole top-level
    section. Transitive consumers use the same boundary for split/option siblings,
    modifiers, resources and membership, even when no active action is produced.
    """
    def __init__(self, data: dict, digest: str = ""):
        self._data, self._digest = data, digest

    @property
    def digest(self):
        observe("@document", "provenance")
        return self._digest

    def record(self, record_id: str, aspect: str = "*"):
        observe(record_id, aspect)
        return project(self._data["mechanics"][record_id], aspect)

    def records(self, aspect: str = "*") -> RecordMap:
        return RecordMap(self._data["mechanics"], aspect)

    def resources(self, aspect: str = "*") -> RecordMap:
        return RecordMap(self._data.get("resources") or {}, aspect, "resources")

    def aggregate(self, section: str, default=None):
        observe(f"@{section}", "*")
        return self._data.get(section, default)
