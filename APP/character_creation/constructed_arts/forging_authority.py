"""Sealed Forged Technique authority (Core Rules §11, PHB chapter 18)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError, sha256_json

FORGING_AUTHORITY_SCHEMA = "TianxiaFoundry.ForgedTechniqueAuthority.v1"
FORGING_AUTHORITY_FILENAME = "Tianxia_Forged_Technique_Authority_R1.json"
REALM_ORDER = ("Mortal", "Foundation", "Core Formation", "Nascent Soul", "Immortal")


def forging_authority_path(root_dir: Path) -> Path:
    return Path(root_dir) / "authority" / FORGING_AUTHORITY_FILENAME


def load_forging_authority(root_dir: Path) -> dict[str, Any]:
    """Read and verify the sealed forging tables."""
    path = forging_authority_path(root_dir)
    if not path.is_file():
        raise FoundryError("FORGING_AUTHORITY_MISSING", "The sealed Forged Technique authority is missing.", details={"path": str(path)})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        raise FoundryError("FORGING_AUTHORITY_INVALID", "The Forged Technique authority is unreadable.", details={"path": str(path), "error": str(exc)}) from exc
    if value.get("schema_version") != FORGING_AUTHORITY_SCHEMA:
        raise FoundryError("FORGING_AUTHORITY_INVALID", "The Forged Technique authority declares an unsupported schema.", details={"path": str(path)})
    unsigned = {key: item for key, item in value.items() if key != "seal_sha256"}
    if value.get("seal_sha256") != sha256_json(unsigned):
        raise FoundryError("FORGING_AUTHORITY_INVALID", "The Forged Technique authority failed its canonical seal.", details={"path": str(path)})
    for key in ("realm_complexity_limits", "recommended_maximum_spheres", "base_forms", "augments", "drawbacks", "forging_check", "known_limit", "access"):
        if key not in value:
            raise FoundryError("FORGING_AUTHORITY_INVALID", "The Forged Technique authority lacks a required table.", details={"table": key})
    return value


def realm_for_cl(cl: int) -> str:
    if cl >= 20:
        return "Immortal"
    if cl >= 15:
        return "Nascent Soul"
    if cl >= 10:
        return "Core Formation"
    if cl >= 5:
        return "Foundation"
    return "Mortal"


def realm_at_least(realm: str, minimum: str) -> bool:
    return REALM_ORDER.index(realm) >= REALM_ORDER.index(minimum)


def realm_complexity_limit(authority: Mapping[str, Any], realm: str) -> dict[str, Any]:
    for row in authority["realm_complexity_limits"]:
        if row["realm"] == realm:
            return dict(row)
    raise FoundryError("FORGING_AUTHORITY_INVALID", "The Realm has no published Complexity limit.", details={"realm": realm})


def recommended_maximum_spheres(authority: Mapping[str, Any], realm: str) -> int:
    for row in authority["recommended_maximum_spheres"]:
        if row["realm"] == realm:
            return int(row["maximum_spheres"])
    raise FoundryError("FORGING_AUTHORITY_INVALID", "The Realm has no published Sphere maximum.", details={"realm": realm})


def base_form(authority: Mapping[str, Any], form_id: str) -> dict[str, Any]:
    for row in authority["base_forms"]:
        if row["form_id"] == form_id:
            return dict(row)
    raise FoundryError("FORGING_BASE_FORM_UNKNOWN", "The Base Form is not published.", details={"form_id": form_id})


def augment(authority: Mapping[str, Any], augment_id: str) -> dict[str, Any]:
    for row in authority["augments"]:
        if row["augment_id"] == augment_id:
            return dict(row)
    raise FoundryError("FORGING_AUGMENT_UNKNOWN", "The Augment is not published.", details={"augment_id": augment_id})


def drawback(authority: Mapping[str, Any], drawback_id: str) -> dict[str, Any]:
    for row in authority["drawbacks"]:
        if row["drawback_id"] == drawback_id:
            return dict(row)
    raise FoundryError("FORGING_DRAWBACK_UNKNOWN", "The Drawback is not published.", details={"drawback_id": drawback_id})


__all__ = [
    "FORGING_AUTHORITY_FILENAME",
    "FORGING_AUTHORITY_SCHEMA",
    "REALM_ORDER",
    "augment",
    "base_form",
    "drawback",
    "forging_authority_path",
    "load_forging_authority",
    "realm_at_least",
    "realm_complexity_limit",
    "realm_for_cl",
    "recommended_maximum_spheres",
]
