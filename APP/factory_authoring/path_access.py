"""Which Paths may learn which Spheres, and Body Refining's external projection (owner 2026-09-27: "body refining isnt
modifying access to spheres and the whole 'using qi outside of the body' isnt being enforced. The ai chose lava spit and
other ranged qi techniques").

authority/Tianxia_Sphere_Path_Access_R1.json holds each Sphere's printed Primary / Secondary / Rare Path lines. A Path
not listed cannot learn the Sphere (Ash lists Qi Cultivation and Spirit Awakening only). A "through ..." route (Magma:
"Body Refining through Volcanic Body scripture") is allowed for now and reported, pending the owner's ruling on routes.

The Path rules (PHB Chapter 3, Path Identity Boundaries): "Body Refining normally acts through the cultivator's own
body, a natural bodily weapon, an integrated weapon ... Every external projection requires a printed exception." A
character whose only Path is Body Refining is therefore not offered a ranged technique (a Cultivation Attack or area
beyond reach, not a weapon attack) from a Sphere Body Refining is not primary in.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

APP = Path(__file__).resolve().parents[1]
ACCESS = APP / "authority" / "Tianxia_Sphere_Path_Access_R1.json"
TYPED = APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
BODY = "tianxia.path.body_refining"


@lru_cache(maxsize=2)
def _access(mtime: float) -> dict[str, Any]:
    return json.loads(ACCESS.read_text(encoding="utf-8"))["spheres"]


@lru_cache(maxsize=2)
def _mechanics(mtime: float) -> dict[str, dict[str, Any]]:
    rows = json.loads(TYPED.read_text(encoding="utf-8"))["mechanics"]
    return {key: {"sphere_id": row.get("sphere_id"), "economy": (row.get("activation") or {}).get("economy"),
                  "range": row.get("range"), "area": row.get("area"), "weapon": bool(row.get("weapon_delivery")),
                  "name": row.get("name")} for key, row in rows.items()}


def access() -> dict[str, Any]:
    return _access(ACCESS.stat().st_mtime)


def mechanic(talent_id: str) -> dict[str, Any] | None:
    return _mechanics(TYPED.stat().st_mtime).get(talent_id)


def can_learn(sphere_id: str, paths: Iterable[str]) -> bool:
    entry = access().get(sphere_id)
    paths = set(paths)
    if entry is None or not paths:
        return True  # an unknown Sphere, or no Path chosen yet: nothing to check
    return bool(paths & {*entry["primary"], *entry["open"], *entry["conditional"]})


def _projects(row: dict[str, Any]) -> bool:
    if row.get("weapon") or row.get("economy") not in ("action", "bonus_action"):
        return False
    rng = row.get("range") or {}
    feet = rng.get("feet") if isinstance(rng, dict) else None
    area = row.get("area") or {}
    ranged = isinstance(feet, (int, float)) and feet > 10
    return ranged or bool(area.get("size_ft")) and not area.get("centered_on_self") and isinstance(feet, (int, float)) and feet > 5


def blocked(choice_id: str, paths: Iterable[str], sphere_of_route: dict[str, str] | None = None) -> str | None:
    """Why this choice is not for a character of these Paths, or None."""
    paths = set(paths)
    if not paths:
        return None
    sphere_id = (sphere_of_route or {}).get(choice_id) or (choice_id if choice_id in access() else None)
    row = None if sphere_id else mechanic(choice_id)
    if row is not None:
        sphere_id = row.get("sphere_id")
    if sphere_id and not can_learn(sphere_id, paths):
        return f"{access()[sphere_id]['name']} is not a Sphere your Path can learn"
    entry = access().get(sphere_id or "") or {}
    if row is not None and paths == {BODY} and entry.get("power", True) and BODY not in entry.get("primary", [BODY]) and _projects(row):
        return f"{row.get('name')} projects Qi beyond the body (Body Refining needs a printed exception)"
    return None
