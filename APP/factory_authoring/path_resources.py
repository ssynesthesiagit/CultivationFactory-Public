"""Source-backed active Path resource authority for final-character consumers.

A character's executable resource (Stamina, Qi or Resonance) follows from its
one canonical Path.  Every sealed document that declares that resource must
agree exactly; a generic "CP" row never establishes which Path resource is
active.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from app.core import FoundryError
from factory_authoring.composite_controller import (
    _PATH_RESOURCE_DEFINITIONS,
    _canonical_path_resource_id,
    _load_json,
)


PATH_RESOURCE_ALIAS = "RES_CP"
PATH_RESOURCE_ABSOLUTE_MAX = 1_000_000
_PATH_RESOURCE_BY_PATH: dict[str, dict[str, str]] = {
    "tianxia.path.body_refining": {
        "path_name": "Body Refining",
        "resource_id": "tianxia.resource.stamina",
    },
    "tianxia.path.qi_cultivation": {
        "path_name": "Qi Cultivation",
        "resource_id": "tianxia.resource.qi",
    },
    "tianxia.path.spirit_awakening": {
        "path_name": "Spirit Awakening",
        "resource_id": "tianxia.resource.resonance",
    },
}
_GENERIC_CP_NAMES = {"cp", "res cp", "cultivation point", "cultivation points"}


def _error(code: str, message: str, *, details: Any = None, status_code: int = 400) -> FoundryError:
    return FoundryError(code, message, details=details, status_code=status_code)


def _integer(value: Any, *, minimum: int = 0, maximum: int = 1_000_000_000) -> int | None:
    if isinstance(value, bool) or type(value) is not int or not minimum <= value <= maximum:
        return None
    return value


def _nested_integer(value: Any, *, minimum: int = 0, maximum: int = 1_000_000_000) -> int | None:
    direct = _integer(value, minimum=minimum, maximum=maximum)
    if direct is not None:
        return direct
    if isinstance(value, Mapping):
        for key in ("value", "amount", "current", "maximum", "max", "max_value"):
            candidate = _integer(value.get(key), minimum=minimum, maximum=maximum)
            if candidate is not None:
                return candidate
    return None


def path_resource_authority(character: Mapping[str, Any]) -> dict[str, str]:
    """Resolve exactly one canonical Path to its distinct runtime resource."""

    if not isinstance(character, Mapping):
        raise _error("PATH_RESOURCE_PATH_MISMATCH", "The accepted candidate has no typed active Path authority.")
    rows: list[Mapping[str, Any]] = [{"path_id": character.get("path_id"), "path": character.get("path")}]
    paths = character.get("paths")
    if paths is not None:
        if not isinstance(paths, list) or not paths:
            raise _error("PATH_RESOURCE_PATH_MISMATCH", "The accepted candidate Path selection is malformed.")
        rows.extend(row for row in paths if isinstance(row, Mapping))
        if len(rows) != 1 + len(paths):
            raise _error("PATH_RESOURCE_PATH_MISMATCH", "The accepted candidate Path selection contains a malformed row.")

    path_ids: set[str] = set()
    path_names: set[str] = set()
    for row in rows:
        raw_id = row.get("path_id")
        raw_name = row.get("path") or row.get("display_name") or row.get("name")
        if raw_id is not None:
            if not isinstance(raw_id, str) or raw_id not in _PATH_RESOURCE_BY_PATH:
                raise _error("PATH_RESOURCE_PATH_MISMATCH", "The accepted candidate Path ID is not one canonical Path.")
            path_ids.add(raw_id)
        if raw_name is not None:
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise _error("PATH_RESOURCE_PATH_MISMATCH", "The accepted candidate Path name is malformed.")
            path_names.add(raw_name.strip())
    if len(path_ids) != 1:
        raise _error("PATH_RESOURCE_PATH_MISMATCH", "The accepted candidate must select exactly one canonical Path.")
    path_id = next(iter(path_ids))
    expected = _PATH_RESOURCE_BY_PATH[path_id]
    if path_names and path_names != {expected["path_name"]}:
        raise _error("PATH_RESOURCE_PATH_MISMATCH", "The accepted candidate Path name does not match its canonical Path ID.")
    resource_id = expected["resource_id"]
    definition = _PATH_RESOURCE_DEFINITIONS.get(resource_id)
    if not isinstance(definition, Mapping) or definition.get("name") is None:
        raise _error("PATH_RESOURCE_AUTHORITY_INVALID", "The canonical Path resource definition is unavailable.")
    return {
        "path_id": path_id,
        "path_name": expected["path_name"],
        "resource_id": resource_id,
        "resource_name": str(definition["name"]),
    }


def _resource_rows(document: Any) -> list[Mapping[str, Any]]:
    if not isinstance(document, Mapping):
        return []
    values: list[Any] = []
    for key in ("resources", "resource_block", "combat_resources"):
        if key in document:
            values.append(document.get(key))
    if any(key in document for key in ("resource_id", "resource_name", "current", "maximum", "max", "max_value")):
        values.append(document)
    rows: list[Mapping[str, Any]] = []
    for value in values:
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, Mapping))
        elif isinstance(value, Mapping):
            if any(key in value for key in ("resource_id", "resource_name", "current", "maximum", "max", "max_value")):
                rows.append(value)
            else:
                for key, row in value.items():
                    if isinstance(row, Mapping):
                        projected = dict(row)
                        projected.setdefault("resource_id", key)
                        rows.append(projected)
    return rows


def active_resource_authority(root: Path, ledger: Mapping[str, Any], character: Mapping[str, Any]) -> dict[str, Any]:
    """Read one source-backed Path resource from canonical stats and ledger.

    The canonical Command 2 block has priority; the Build ledger is a
    corroborating source for fixtures and materialized candidates.  Every
    source that declares a Path resource must agree exactly, and generic CP
    alone never establishes an active resource.
    """

    source_documents: list[tuple[str, Any]] = []
    for relative in (
        "Command_2/Canonical_Stats_Resource_Block.json",
        "Build/Character_Master_Ledger.json",
        "Command_2/Canonical_Advancement_Ledger.json",
    ):
        path = Path(root) / relative
        if path.is_file() and not path.is_symlink():
            source_documents.append((relative, _load_json(path)))
    path_candidates: list[tuple[str, dict[str, str]]] = []
    for relative, document in source_documents:
        source_character = document.get("character") if isinstance(document, Mapping) else None
        if isinstance(source_character, Mapping):
            path_candidates.append((relative, path_resource_authority(source_character)))
    if isinstance(character, Mapping):
        path_candidates.append(("Build/Character_Master_Ledger.json", path_resource_authority(character)))
    if not path_candidates:
        raise _error("PATH_RESOURCE_PATH_MISMATCH", "The sealed workspace has no source-backed active Path authority.")
    path_authority = path_candidates[0][1]
    if any(candidate[1] != path_authority for candidate in path_candidates[1:]):
        raise _error(
            "PATH_RESOURCE_PATH_AUTHORITY_INVALID",
            "The sealed workspace contains conflicting active Path authority.",
            details={"paths": [candidate for _source, candidate in path_candidates]},
        )
    expected_id = path_authority["resource_id"]
    expected_name = path_authority["resource_name"]
    found: list[tuple[str, dict[str, Any]]] = []
    for relative, document in source_documents:
        source_found = 0
        for row in _resource_rows(document):
            raw_id = row.get("resource_id")
            if raw_id is None:
                raw_id = row.get("id", row.get("key"))
            raw_name = row.get("name", row.get("display_name", row.get("resource_name")))
            raw_values = [value for value in (raw_id, raw_name) if isinstance(value, str) and value.strip()]
            concrete_ids = {
                canonical
                for value in raw_values
                for canonical in (_canonical_path_resource_id(value),)
                if canonical is not None
            }
            generic = any(value.strip().casefold().replace("_", " ") in _GENERIC_CP_NAMES for value in raw_values)
            unknown = [
                value for value in raw_values
                if value.strip().casefold().replace("_", " ") not in _GENERIC_CP_NAMES
                and _canonical_path_resource_id(value) is None
            ]
            if not concrete_ids:
                if generic:
                    raise _error(
                        "PATH_RESOURCE_AUTHORITY_INVALID",
                        "A generic CP resource row does not prove one active Path resource.",
                        details={"source": relative},
                    )
                continue
            if unknown or len(concrete_ids) != 1:
                if expected_id in concrete_ids:
                    raise _error(
                        "PATH_RESOURCE_MISMATCH",
                        "The sealed resource display or identity does not match the active Path resource.",
                        details={"source": relative, "expected_resource_id": expected_id},
                    )
                raise _error(
                    "PATH_RESOURCE_AUTHORITY_INVALID",
                    "A resource row contains conflicting or unknown Path resource identity.",
                    details={"source": relative},
                )
            resource_id = next(iter(concrete_ids))
            definition = _PATH_RESOURCE_DEFINITIONS.get(resource_id)
            if not isinstance(definition, Mapping) or resource_id != expected_id:
                raise _error(
                    "PATH_RESOURCE_MISMATCH",
                    "The sealed resource does not match the character's active Path.",
                    details={"expected_resource_id": expected_id, "actual_resource_id": resource_id},
                )
            if raw_name is not None and (not isinstance(raw_name, str) or raw_name.strip() != expected_name):
                raise _error("PATH_RESOURCE_MISMATCH", "The sealed resource display name does not match its canonical Path resource.")
            current = _nested_integer(row.get("current"))
            if current is None:
                current = _nested_integer(row.get("current_value"))
            maximum = _nested_integer(row.get("maximum"), minimum=1, maximum=PATH_RESOURCE_ABSOLUTE_MAX)
            if maximum is None:
                maximum = _nested_integer(row.get("max"), minimum=1, maximum=PATH_RESOURCE_ABSOLUTE_MAX)
            if maximum is None:
                maximum = _nested_integer(row.get("max_value"), minimum=1, maximum=PATH_RESOURCE_ABSOLUTE_MAX)
            if current is None or maximum is None or current > maximum:
                raise _error(
                    "PATH_RESOURCE_MISMATCH",
                    "The sealed active Path resource current/max mapping is invalid.",
                    details={"source": relative, "resource_id": resource_id},
                )
            source_found += 1
            found.append((relative, {
                "resource_id": resource_id,
                "alias": PATH_RESOURCE_ALIAS,
                "name": expected_name,
                "current": current,
                "maximum": maximum,
            }))
        if source_found > 1:
            raise _error(
                "PATH_RESOURCE_AUTHORITY_INVALID",
                "A sealed source document contains more than one active Path resource row.",
                details={"source": relative},
            )
    if not found:
        raise _error(
            "PATH_RESOURCE_MISSING",
            "The candidate has no singular source-backed active Path resource.",
            details={"expected_resource_id": expected_id},
        )
    signatures = {tuple(record[key] for key in ("resource_id", "name", "current", "maximum")) for _source, record in found}
    if len(signatures) != 1:
        raise _error(
            "PATH_RESOURCE_AUTHORITY_INVALID",
            "The sealed workspace contains conflicting active Path resource authority.",
            details={"resources": sorted(signatures)},
        )
    return deepcopy(found[0][1])
