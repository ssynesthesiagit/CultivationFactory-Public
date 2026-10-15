"""What the table's fighter picker shows on a character card (owner 2026-10-04: "listed by recency ... larger and more
visual, with searches, maybe the tokens to select").

Used by CombatService.factory_characters (combat/gate5_service.py), which adds these read-only fields to each row of
GET /api/combat/factory-characters; static/tabletop/fighter-picker.js reads them.  Nothing here changes a fight.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from character_sheet.path_display import path_display

TYPED_AUTHORITY = Path(__file__).resolve().parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"


@lru_cache(maxsize=1)
def _sphere_names() -> dict[str, str]:
    try:
        return dict(json.loads(TYPED_AUTHORITY.read_bytes()).get("sphere_names") or {})
    except (OSError, ValueError):
        return {}


def sphere_name(sphere_id: str) -> str:
    """'tianxia.sphere.fire' -> 'Fire' (the rules' own name when it has one)."""
    return _sphere_names().get(sphere_id) or str(sphere_id).rsplit(".", 1)[-1].replace("_", " ").title()


def card_fields(sheet: dict[str, Any]) -> dict[str, Any]:
    """Path, Subpath and Sphere names from an owner sheet, in its selection order."""
    block = sheet.get("path_and_subpath") or {}
    paths = [row.get("display_name") or row.get("name") for row in block.get("paths") or []
             if isinstance(row, dict) and (row.get("display_name") or row.get("name"))]
    # Older single-Path sheets predate the selection list.
    if not paths:
        primary = block.get("path") or {}
        name = ((primary.get("display_name") or primary.get("name")) if isinstance(primary, dict) else None) or (sheet.get("identity") or {}).get("path")
        paths = [name] if name else []
    subpath = block.get("subpath") or {}
    spheres = (sheet.get("spheres_and_talents") or {}).get("sphere_record_ids") or []
    return {**path_display(sheet), "paths": paths, "path": paths[0] if paths else None,
            "subpath": (subpath.get("name") if isinstance(subpath, dict) else None) or None,
            "spheres": [sphere_name(sphere) for sphere in spheres]}


def edited_at(*paths: Path) -> str | None:
    """The latest change to any of these files (the installed package, the table's overlay) as a UTC ISO string."""
    times = [path.stat().st_mtime for path in paths if path.is_file()]
    if not times:
        return None
    return datetime.fromtimestamp(max(times), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
