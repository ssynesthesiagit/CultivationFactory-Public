"""Printed Cultivation Insight identities shared by typing and combat admission.

These helpers do not acquire Insights or interpret their mechanical benefits.
The CAT3 catalogue supplies canonical typing rows. Combat checks those rows
against the current, smaller source document before granting reviewed effects.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


INSIGHT_KIND = "cultivation_insight"
SOURCE_PATH = "catalog_authority/cat3/source/Tianxia_Central_Cultivation_Insights_AI_Reference_R5_Legacy_Restored.json"
EDITS_PATH = "authority/typed_mechanics/owner_text_edits.json"
_CURRENT_CACHE: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record_sha(record: dict[str, Any]) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return _text_sha(payload)


def catalog_insight_sources(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose every canonical printed entry, including nonselectable history.

    ``source_provenance`` can describe the superseded first occurrence. The
    selected raw record's own source authority binds the current printed text.
    """
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in catalog.get("insights") or []:
        if not isinstance(row, dict):
            raise ValueError("Cultivation Insight catalogue entry is not a record")
        raw = row.get("raw_source_record") or {}
        if not isinstance(raw, dict):
            raise ValueError("Cultivation Insight catalogue lacks a source record")
        key = row.get("canonical_insight_id") or row.get("record_id")
        text = raw.get("full_rules_text")
        provenance = raw.get("source_authority") or {}
        if not isinstance(key, str) or not key.startswith("insight.") or key in seen:
            raise ValueError("Cultivation Insight source has an invalid or duplicate canonical ID")
        if not isinstance(text, str) or not raw.get("record_id") or not isinstance(provenance, dict) \
                or not all(provenance.get(field) for field in ("r2_source_path", "r2_source_sha256", "source_record_sha256")):
            raise ValueError(f"Cultivation Insight lacks selected printed source authority: {key}")
        seen.add(key)
        result.append({
            "id": key, "name": row.get("display_name") or raw.get("name") or key,
            "kind": INSIGHT_KIND, "text": text,
            "sphere_id": row.get("owning_canonical_sphere_id"),
            "insight_selectable": row.get("selectable") is True and raw.get("selectable") is True,
            "source": {
                "path": provenance.get("r2_source_path"), "line": None,
                "file_sha256": provenance.get("r2_source_sha256"),
                "record_id": raw["record_id"],
                "record_sha256": provenance["source_record_sha256"],
                "anchor": f"record:{raw['record_id']}", "text_sha256": _text_sha(text),
            },
        })
    return result


def current_insight_sources(app: Path) -> dict[str, dict[str, Any]]:
    """Return current source rows for admission; callers must not mutate them.

    Read and hash the 2 MB source and small edit file, and parse only after a
    content change. This also detects a source edit with preserved timestamps,
    without parsing the much larger generated catalogue for every character.
    Ambiguous supersession is retained as nonselectable manual authority.
    """
    path = app / SOURCE_PATH
    source_bytes = path.read_bytes()
    edits_path = app / EDITS_PATH
    edit_bytes = edits_path.read_bytes() if edits_path.is_file() else b"{}"
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    stamp = (str(path.resolve()), source_sha, hashlib.sha256(edit_bytes).hexdigest())
    if stamp in _CURRENT_CACHE:
        return _CURRENT_CACHE[stamp]
    source, edit_document = json.loads(source_bytes), json.loads(edit_bytes)
    if not isinstance(source, dict) or not isinstance(source.get("records"), list) or not isinstance(edit_document, dict):
        raise ValueError("Cultivation Insight source or edit document has an invalid shape")
    edits = edit_document.get("records") or {}
    if not isinstance(edits, dict):
        raise ValueError("Cultivation Insight source edits are not keyed records")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in source.get("records") or []:
        if not isinstance(raw, dict):
            raise ValueError("Cultivation Insight source entry is not a record")
        key = raw.get("canonical_id")
        if not isinstance(key, str) or not key.startswith("insight."):
            raise ValueError("Cultivation Insight source has an invalid canonical ID")
        grouped[key].append(raw)
    from .owner_text_edits import apply_edit

    result: dict[str, dict[str, Any]] = {}
    for key, occurrences in grouped.items():
        active = [row for row in occurrences if not row.get("superseded_by")
                  and str(row.get("execution_status") or "").casefold() != "superseded_source_record"]
        resolved = len(active) == 1 and all(
            row is active[0] or row.get("superseded_by") == key for row in occurrences)
        selected = active[0] if active else occurrences[0]
        text = selected.get("full_rules_text")
        if not isinstance(text, str):
            raise ValueError(f"Cultivation Insight lacks printed rules text: {key}")
        edit = edits.get(key)
        if edit is not None and not isinstance(edit, dict):
            raise ValueError(f"Cultivation Insight source edit is not a record: {key}")
        _, text, problems = apply_edit(text, edit)
        result[key] = {
            "id": key, "name": selected.get("display_name") or selected.get("name") or key,
            "text": text, "insight_selectable": resolved and selected.get("selectable") is True,
            "owner_edit_problems": problems,
            "source": {
                "path": SOURCE_PATH, "line": None, "file_sha256": source_sha,
                "record_id": selected.get("record_id"), "record_sha256": _record_sha(selected),
                "anchor": f"record:{selected.get('record_id')}", "text_sha256": _text_sha(text),
            },
        }
    if len(_CURRENT_CACHE) >= 4:
        _CURRENT_CACHE.clear()
    _CURRENT_CACHE[stamp] = result
    return result
