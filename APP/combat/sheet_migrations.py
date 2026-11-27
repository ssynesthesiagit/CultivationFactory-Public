"""Migrate installed owner-sheet data without invalidating its sealed package."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from app.core import FoundryError, sha256_bytes
from path_keys import ability_code, sheet_path_ids

# Historical assignments, not legal-option authority. Only the migration can use them.
_LEGACY_KEYS = {
    "tianxia.path.body_refining": "CON",
    "tianxia.path.qi_cultivation": "INT",
    "tianxia.path.spirit_awakening": "WIS",
}


def migrate_installed_sheet(sheet: dict[str, Any], raw: bytes, package: Path,
                            write_json: Callable[[Path, dict], None]) -> dict[str, Any]:
    """Persist an idempotent, source-bound backfill at the installed sheet boundary."""
    primary, path_ids = sheet_path_ids(sheet)
    if primary is None:
        return sheet
    identity = sheet.setdefault("identity", {})
    paths = sheet.get("path_and_subpath") or {}
    rows = paths.get("paths") or identity.get("paths") or []
    by_id = {row.get("path_id"): row for row in rows if isinstance(row, dict)}
    missing = {pid for pid in path_ids if pid != primary and by_id.get(pid, {}).get("key_ability") in (None, "")}
    if identity.get("key_ability") in (None, ""):
        missing.add(primary)
    if not missing:
        return sheet

    source = sha256_bytes(raw)
    record = package.with_name("sheet-path-key-migration.json")
    try:
        saved = json.loads(record.read_bytes())
    except FileNotFoundError:
        saved = {}
    if saved.get("source_sha256") == source:
        backfill = saved.get("path_keys") or {}
        if any(ability_code(backfill.get(pid)) is None for pid in missing):
            raise FoundryError("PATH_KEY_ABILITY_MISSING", "The saved Path key backfill is incomplete.",
                               details={"path_ids": sorted(missing)}, status_code=409)
    else:
        backfill = {pid: by_id.get(pid, {}).get("key_ability") or _LEGACY_KEYS[pid] for pid in sorted(missing)}
        write_json(record, {"source_sha256": source, "path_keys": backfill})

    if primary in missing:
        identity["key_ability"] = backfill[primary]
    for pid in missing - {primary}:
        if pid in by_id:
            by_id[pid]["key_ability"] = backfill[pid]
        else:
            rows.append({"path_id": pid, "key_ability": backfill[pid],
                         "effective_cl": identity.get("cultivation_level", 1)})
    if missing - {primary}:
        sheet.setdefault("path_and_subpath", {})["paths"] = rows
    return sheet
