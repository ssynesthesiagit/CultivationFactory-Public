"""Shared Path key authority for creation, projection, and combat.

The Path indexes own the legal choices. A new acquisition records its actual
choice in the event, not in the (character-independent) catalog record.
"""
from functools import lru_cache
import json
from pathlib import Path
from typing import Mapping

from app.core import FoundryError

ABILITY_NAMES = {
    "STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
    "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma",
}
CHOICE_FIELD = "path_key_ability_by_path_id"
INDEX_ROOT = Path(__file__).resolve().parent / "non_sphere_authority" / "authority"


def ability_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    return next((code for code, name in ABILITY_NAMES.items() if value in (code.lower(), name.lower())), None)


def profile_key_options(index: Mapping) -> tuple[str, ...]:
    options = index["path_profile"]["key_ability"]["options"]
    names = {name: code for code, name in ABILITY_NAMES.items()}
    return tuple(names[option] for option in options)


@lru_cache(maxsize=1)
def _profiles() -> dict:
    indexes = (json.loads(path.read_text(encoding="utf-8")) for path in INDEX_ROOT.glob("*.path_index.p2a.json"))
    return {index["canonical_id"]: index for index in indexes}


def canonical_path_id(path: object) -> str | None:
    for path_id, profile in _profiles().items():
        if path in (path_id, path_id.removeprefix("tianxia."), path_id.removeprefix("tianxia.path."), profile["display_name"]):
            return path_id
    return None


def path_key_options(path: str) -> tuple[str, ...]:
    path_id = canonical_path_id(path)
    return profile_key_options(_profiles()[path_id]) if path_id else ()


def sheet_path_ids(sheet: Mapping) -> tuple[str | None, tuple[str, ...]]:
    identity = sheet.get("identity") or {}
    paths = sheet.get("path_and_subpath") or {}
    primary = canonical_path_id(paths.get("path_record_id") or identity.get("path_id") or identity.get("path"))
    declared = identity.get("path_ids") or paths.get("path_record_ids") or []
    rows = paths.get("paths") or identity.get("paths") or []
    path_ids = tuple(dict.fromkeys(
        pid for value in (primary, *declared, *(row.get("path_id") for row in rows if isinstance(row, Mapping)))
        if (pid := canonical_path_id(value))
    ))
    return primary or next(iter(path_ids), None), path_ids


def sheet_key(sheet: Mapping, path_id: str | None = None) -> str | None:
    """Read the recorded key, never choose one for a character at read time."""
    primary, _ = sheet_path_ids(sheet)
    identity = sheet.get("identity") or {}
    if path_id is None or path_id == primary:
        value = identity.get("key_ability")
        path_id = primary
    else:
        rows = (sheet.get("path_and_subpath") or {}).get("paths") or identity.get("paths") or []
        value = next((row.get("key_ability") for row in rows
                      if isinstance(row, Mapping) and row.get("path_id") == path_id), None)
    key = ability_code(value)
    if key is None and (path_id is not None or value is not None):
        raise FoundryError(
            "PATH_KEY_ABILITY_MISSING" if not value else "PATH_KEY_ABILITY_ILLEGAL",
            "This character does not have a valid recorded key ability for this Path.",
            details={"path_id": path_id, "key_ability": value}, status_code=409,
        )
    return key


def sheet_path_keys(sheet: Mapping) -> dict[str, str]:
    _, path_ids = sheet_path_ids(sheet)
    return {path_id: sheet_key(sheet, path_id) for path_id in path_ids}


def acquisition_key(path_id: str, authority: Mapping, selected: object = None) -> str:
    """Read/validate the pick; old frozen catalogs already contain a fixed key."""
    options = authority.get("key_ability_options")
    if options is None:
        fixed = ability_code(authority.get("key_ability"))
        options = (fixed,) if fixed else ()
        if selected is None:
            selected = fixed
    elif selected is None and len(options) == 1:
        selected = options[0]
    if selected not in options:
        raise FoundryError(
            "PATH_KEY_ABILITY_MISSING" if selected is None else "PATH_KEY_ABILITY_ILLEGAL",
            "Choose one of the allowed key abilities for this Path.",
            details={"path_id": path_id, "key_ability": selected, "options": list(options)},
            status_code=409,
        )
    return selected


def path_record_authority(record: Mapping) -> Mapping:
    return ((record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {}


def proposal_key(rows, path_id: str, record: Mapping) -> str:
    row = next((row for row in rows if row.get("kind") == "path_acquisition" and row.get("record_id") == path_id), {})
    return acquisition_key(path_id, path_record_authority(record), (row.get("parameters") or {}).get("key_ability"))


def recorded_acquisition_key(path_id: str, authority: Mapping, picked: object) -> str:
    """Read an accepted acquisition (including single-option Paths)."""
    if "key_ability_options" in authority and picked is None:
        raise FoundryError("PATH_KEY_ABILITY_MISSING", "This Path acquisition has no recorded key ability.",
                           details={"path_id": path_id}, status_code=409)
    return acquisition_key(path_id, authority, picked)


def event_key(event: Mapping, authority: Mapping) -> str:
    advancement = event["advancement"]
    picked = (advancement.get("details") or {}).get("key_ability")
    return recorded_acquisition_key(event["subject"]["record_id"], authority, picked)
