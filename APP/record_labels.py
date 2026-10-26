"""Record presentation shared by catalog, authoring, sheets and fighter cards.

authority/record_labels.json is the editable ID -> label table. Names in sealed
source documents remain provenance, not aliases or gameplay foreign keys.
Generated names are compatibility exports. Unknown (e.g. user-authored) IDs keep
the caller's label; a label never confers ownership. No mechanical hashes are
rewritten here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

APP = Path(__file__).resolve().parent


_PARSED: dict[Path, tuple[bytes, dict[str, str]]] = {}


def labels(app: Path | None = None) -> dict[str, str]:
    """The table, parsed once per distinct file content (callers are per card, per sheet and per query). Keyed on the
    exact bytes, not mtime, so an edit is seen at once even within one timestamp tick."""
    path = (app or APP) / "authority/record_labels.json"
    if not path.is_file():
        return {}
    raw = path.read_bytes()
    cached = _PARSED.get(path)
    if cached is None or cached[0] != raw:
        cached = (raw, json.loads(raw.decode("utf-8")))
        _PARSED[path] = cached
    return dict(cached[1])


def label(record_id: str, fallback: str = "", *, app: Path | None = None,
          names: dict[str, str] | None = None) -> str:
    return (labels(app) if names is None else names).get(record_id, fallback)


def present(record: dict, *, app: Path | None = None, names: dict[str, str] | None = None) -> dict:
    """A catalog/selection view; apply labels to every ID-bearing nested record."""
    names = labels(app) if names is None else names

    def project(value):
        if isinstance(value, list):
            return [project(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: project(item) for key, item in value.items()}
        rid = result.get("record_id") or result.get("canonical_id")
        if rid:
            result["display_name"] = label(rid, result.get("display_name", ""), names=names)
        return result

    return project(record)


def presentation_diff(before: dict[str, str], after: dict[str, str]) -> dict:
    """Explicit label changes and their artifact commitments, not a combat filter."""
    digest = lambda value: hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"aspect": "presentation", "before_sha256": digest(before), "after_sha256": digest(after),
            "changes": {rid: {"before": before.get(rid), "after": after.get(rid)}
                        for rid in sorted(before.keys() | after.keys()) if before.get(rid) != after.get(rid)}}
