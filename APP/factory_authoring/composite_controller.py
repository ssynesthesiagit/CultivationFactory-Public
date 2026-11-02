"""Provider-free contract for the future ``composite_controller`` target.

The Command 1--4 workspace is the only mechanics input to this module.  A
local provider may propose a controller policy, but it never supplies action
mechanics: each response reference is an opaque, request-scoped token and
the server resolves that token back to the sealed action packet.

This module deliberately stops at a detached overlay.  Command 5 and the
portable package are not invoked here; an explicit later caller can validate
and apply the overlay to a copied workspace with :func:`apply_overlay`.
"""

from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_file, sha256_json
from factory_authoring.theme_contract import build_gm_themes_schema, validate_gm_themes


COMPOSITE_CONTROLLER_PURPOSE = "factory_composite_controller"
COMPOSITE_CONTROLLER_SCHEMA = "TianxiaFoundry.CompositeControllerProviderResponse.v1"
COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_NAME = "TianxiaFoundry_CompositeController_v1"
# Keep both spellings for callers mirroring Command 4.
COMPOSITE_CONTROLLER_PROVIDER_RESPONSE_SCHEMA = COMPOSITE_CONTROLLER_SCHEMA
COMPOSITE_CONTROLLER_PROVIDER_RESPONSE_SCHEMA_NAME = COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_NAME
COMPOSITE_CONTROLLER_ARTIFACT_SCHEMA = "TianxiaFoundry.CompositeControllerArtifact.v1"
COMPOSITE_CONTROLLER_OVERLAY_SCHEMA = "TianxiaFoundry.CompositeControllerOverlay.v1"
COMPOSITE_CONTROLLER_TARGET = "composite_controller"
COMPOSITE_CONTROLLER_ID = "composite_controller"
COMPOSITE_CONTROLLER_MAX_REQUEST_BYTES = 64 * 1024
# The response includes the controller plus both required GM themes. Use the
# existing local substantive ceiling so a complete response is not truncated.
COMPOSITE_CONTROLLER_MAX_OUTPUT_TOKENS = 6144
COMPOSITE_CONTROLLER_RESOURCE_ALIAS = "RES_CP"
COMPOSITE_CONTROLLER_RESOURCE_ID = "tianxia.resource.stamina"
# ``COMPOSITE_CONTROLLER_MAX_SPEND`` is retained as the historical Body
# Refining default for callers that only have a bare action row.  A prepared
# controller always replaces it with the sealed active-Path maximum below.
COMPOSITE_CONTROLLER_MAX_SPEND = 45
COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX = 1_000_000
COMPOSITE_CONTROLLER_RESOLUTION_LOCAL = "local_provider"
COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED = "delegated_response"

_LOCAL_PROVIDER_IDS = frozenset({"local", "lemonade"})
# The agent bridge speaks the same provider contract, so a harness-held agent
# may author a composite controller proposal.  The local-only set above still
# governs the local wire format and local fallback identity.
_AGENT_AUTHORING_PROVIDER_IDS = _LOCAL_PROVIDER_IDS | {"agent"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^ccopt_[0-9a-f]{24}$")
_ACTION_ECONOMIES = frozenset({
    "action",
    "bonus_action",
    "reaction",
    "free",
    "movement",
    "passive",
    "procedure",
})
_ROUND_ECONOMY_CAPACITY = {
    "action": 1,
    "bonus_action": 1,
    "reaction": 1,
    "movement": 1,
    "free": 4,
    "passive": 1,
    "procedure": 1,
}
_BASE_PROVENANCE_KEYS = frozenset({
    "provider_target",
    "request_sha256",
    "provider_request_sha256",
    "response_sha256",
    "provider_retry_count",
})
_ECONOMY_ALIASES = {
    "action": "action",
    "standard action": "action",
    "bonus action": "bonus_action",
    "bonus_action": "bonus_action",
    "reaction": "reaction",
    "free": "free",
    "free action": "free",
    "movement": "movement",
    "move": "movement",
    "passive": "passive",
    "procedure": "procedure",
    "ritual procedure": "procedure",
}
_NONE_COST_TEXT = frozenset({
    "",
    "0",
    "none",
    "no cost",
    "no action",
    "no resource",
    "no resources",
    "no resource cost",
    "zero",
})
_GENERIC_RESOURCE_ALIASES = frozenset({
    "cp",
    "res_cp",
    "res cp",
    "cultivation point",
    "cultivation points",
})
_PATH_RESOURCE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "tianxia.resource.stamina": {
        "name": "Stamina",
        "aliases": frozenset({"stamina", "res_stamina", "res stamina"}),
    },
    "tianxia.resource.qi": {
        "name": "Qi",
        "aliases": frozenset({"qi", "res_qi", "res qi"}),
    },
    "tianxia.resource.resonance": {
        "name": "Resonance",
        "aliases": frozenset({"resonance", "res_resonance", "res resonance"}),
    },
}
_POWERING_PATH_FIELDS = (
    "powering_path_id",
    "powering_path",
    "recorded_powering_path_id",
    "recorded_powering_path",
    "required_path_id",
    "required_path",
    "required_path_ids",
    "required_paths",
)
_ACTION_MECHANIC_FIELDS = (
    "action_id",
    "record_id",
    "name",
    "display_name",
    "action_type",
    "economy",
    "bucket",
    "timing",
    "cost",
    "range",
    "target",
    "area",
    "roll_save_check",
    "effect",
    "failure",
    "duration",
    "limit",
    "counterplay",
    "resource_costs",
    "resource_gains",
    "resource_requirements",
    "requires_states",
    "required_states",
    "state_requirements",
    "required_state_ids",
    "states",
    "state_arrays",
    "requirements",
    "full_description",
    "description",
    "readiness",
    "classification",
    "execution_authority",
    "global_combat_readiness",
)


_THEME_GUIDANCE = (
                    "Write both themes for THIS character from identity.concept and the named Spheres, Talents and actions; "
                    "never describe the controller or the rules. dao.core_theme: the character's personal Dao in a short phrase "
                    "in the character's own imagery (do not reuse any example wording). principles: 2-4 convictions the character lives and fights by. "
                    "strengths and risks: concrete tactical tendencies naming their actions. tactical_expression: how the Dao "
                    "shapes their choices in a fight. roleplay_expression: how it shows in speech and manner. gm_usage_notes: "
                    "one sentence telling the GM how to play them. i_ching: the same fields for the I Ching reading of their "
                    "temperament; name a hexagram or trigram in core_theme. No sentence may repeat."
                )


def _theme_source_projection(theme_records: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Descriptive theme sources (record id, section, name, one line) for the prompt."""
    theme_sources: list[dict[str, Any]] = []
    theme_record_ids: list[str] = []
    for row in theme_records or []:
        record = row.get("record") if isinstance(row.get("record"), Mapping) else row
        if not isinstance(record, Mapping):
            continue
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or not record_id or record_id in theme_record_ids:
            continue
        theme_record_ids.append(record_id)
        projection = {"record_id": record_id}
        section = row.get("section") if isinstance(row, Mapping) else None
        if section is not None:
            projection["section"] = deepcopy(section)
        for key in (
            "display_name", "one_line_description", "subsection", "acquisition_route",
            "parent_sphere_id", "acquisition_cl",
        ):
            value = record.get(key)
            if value not in (None, "", [], {}):
                projection[key] = deepcopy(value)
        theme_sources.append(projection)
    return theme_sources, theme_record_ids


def _error(code: str, message: str, *, details: Any = None, status_code: int = 400) -> FoundryError:
    return FoundryError(code, message, details=details, status_code=status_code)


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _safe_text(value: Any, *, limit: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split()).strip()
    if not value:
        return None
    return value[:limit]


def _safe_identifier(value: Any, *, limit: int = 120) -> str | None:
    text = _safe_text(value, limit=limit)
    if text is None or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", text) is None:
        return None
    return text


def _is_selector_id(value: Any) -> bool:
    return isinstance(value, str) and _safe_identifier(value, limit=80) == value


def _validated_project_id(value: Any) -> str:
    """Return a project ID safe to use as one path component."""

    if not isinstance(value, str) or value != value.strip():
        raise _error("COMPOSITE_CONTROLLER_PROJECT_ID_INVALID", "The project ID must be one bounded path-safe identifier.")
    identifier = _safe_identifier(value, limit=120)
    if identifier != value:
        raise _error("COMPOSITE_CONTROLLER_PROJECT_ID_INVALID", "The project ID must be one bounded path-safe identifier.")
    return value


def _first_text(*values: Any, limit: int = 160) -> str | None:
    for value in values:
        text = _safe_text(value, limit=limit)
        if text:
            return text
    return None


def _integer(value: Any, *, minimum: int = 0, maximum: int = 1_000_000) -> int | None:
    if isinstance(value, bool) or type(value) is not int:
        return None
    return value if minimum <= value <= maximum else None


def _bounded_string_schema(maximum: int = 240) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _string_array_schema(max_items: int = 8, maximum: int = 240) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": max_items,
        "items": _bounded_string_schema(maximum),
    }


def _canonical_economy(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    folded = " ".join(value.strip().casefold().replace("-", " ").split())
    return _ECONOMY_ALIASES.get(folded)


def _resource_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return " ".join(text.casefold().replace("_", " ").split()) if text else None


def _canonical_path_resource_id(value: Any) -> str | None:
    """Resolve only a concrete canonical Path resource, never generic CP."""

    folded = _resource_key(value)
    if folded is None:
        return None
    for resource_id, definition in _PATH_RESOURCE_DEFINITIONS.items():
        aliases = definition["aliases"]
        if folded == resource_id.casefold() or folded in aliases:
            return resource_id
    return None


def _canonical_resource_id(value: Any, *, active_resource_id: str | None = None) -> str | None:
    """Resolve CP aliases against the exact active Path resource.

    The default preserves the historical Body Refining behavior for small
    helper callers.  Prepared/validated controller paths always pass the
    sealed active resource explicitly.
    """

    folded = _resource_key(value)
    if folded is None:
        return None
    active = active_resource_id or COMPOSITE_CONTROLLER_RESOURCE_ID
    if active not in _PATH_RESOURCE_DEFINITIONS:
        return value.strip() or None
    if folded in _GENERIC_RESOURCE_ALIASES:
        return active
    concrete = _canonical_path_resource_id(value)
    if concrete is not None:
        return concrete
    return value.strip() or None


def _resource_rows(resource_authority: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return each separately authenticated concrete Path resource pool."""

    if resource_authority is None:
        return [{
            "resource_id": COMPOSITE_CONTROLLER_RESOURCE_ID,
            "alias": COMPOSITE_CONTROLLER_RESOURCE_ALIAS,
            "name": _resource_name(COMPOSITE_CONTROLLER_RESOURCE_ID),
            "current": 0,
            "maximum": COMPOSITE_CONTROLLER_MAX_SPEND,
        }]
    raw_rows = resource_authority.get("resources")
    if isinstance(raw_rows, list):
        rows = [dict(row) for row in raw_rows if isinstance(row, Mapping)]
    elif resource_authority.get("resource_id") is not None:
        rows = [dict(resource_authority)]
    else:
        rows = []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        resource_id = _canonical_path_resource_id(row.get("resource_id"))
        current = _integer(row.get("current"), maximum=COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX)
        maximum = _integer(row.get("maximum"), maximum=COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX)
        if resource_id is None or current is None or maximum is None or current > maximum or resource_id in seen:
            raise _error(
                "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
                "The sealed Path resource authority contains an invalid or duplicate pool.",
            )
        row.update({
            "resource_id": resource_id,
            "name": _resource_name(resource_id),
            "current": current,
            "maximum": maximum,
        })
        seen.add(resource_id)
        result.append(row)
    if not result:
        raise _error(
            "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
            "The sealed Path resource authority has no concrete pools.",
        )
    return result


def _resource_pool(resource_authority: Mapping[str, Any] | None, resource_id: str) -> dict[str, Any]:
    resource_id = _canonical_path_resource_id(resource_id) or resource_id
    for row in _resource_rows(resource_authority):
        if row["resource_id"] == resource_id:
            return row
    raise _error(
        "COMPOSITE_CONTROLLER_RESOURCE_UNSUPPORTED",
        "The action names a resource without sealed Path authority.",
        details={"resource_id": resource_id},
    )


def _resource_balances(resource_authority: Mapping[str, Any] | None) -> dict[str, dict[str, int]]:
    return {
        row["resource_id"]: {"current": int(row["current"]), "maximum": int(row["maximum"])}
        for row in _resource_rows(resource_authority)
    }


def _resource_context(resource_authority: Mapping[str, Any] | None) -> tuple[str, int]:
    """Return a resource context only when exactly one pool is applicable."""

    if resource_authority is None:
        return COMPOSITE_CONTROLLER_RESOURCE_ID, COMPOSITE_CONTROLLER_MAX_SPEND
    rows = _resource_rows(resource_authority)
    explicit = _canonical_path_resource_id(resource_authority.get("resource_id"))
    if explicit is not None:
        pool = _resource_pool(resource_authority, explicit)
        return explicit, int(pool["maximum"])
    if len(rows) == 1:
        return rows[0]["resource_id"], int(rows[0]["maximum"])
    raise _error(
        "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
        "The sealed Path resource authority contains multiple pools; a single active pool is not established.",
        details={"resources": [row["resource_id"] for row in rows]},
    )


def _reject_unbound_powering_path_fields(row: Mapping[str, Any]) -> None:
    """Reject action metadata until a producer binds it to acquisition proof.

    The composite controller only receives the sealed action surface.  A field
    copied into that surface is not itself an authenticated Powering Path
    record, so this controller must not interpret it or allow it to select a
    payer.  The Command4 source resolver remains the authority for any future
    producer-bound record.
    """

    fields = [field for field in _POWERING_PATH_FIELDS if field in row]
    if fields:
        raise _error(
            "COMPOSITE_CONTROLLER_RESOURCE_POWERING_PATH_MISSING",
            "The action carries Powering/required Path metadata without an authenticated producer-bound record.",
            details={
                "action_id": row.get("action_id"),
                "record_id": row.get("record_id"),
                "fields": fields,
                "required_authority": "authenticated producer-bound Powering Path or required Path record",
            },
        )


def _action_resource_id(
    value: Any,
    row: Mapping[str, Any],
    resource_authority: Mapping[str, Any] | None,
) -> str | None:
    """Resolve a named resource, requiring a sealed Path for generic CP."""

    _reject_unbound_powering_path_fields(row)
    folded = _resource_key(value)
    if folded in _GENERIC_RESOURCE_ALIASES:
        pools = _resource_rows(resource_authority)
        if len(pools) == 1:
            return pools[0]["resource_id"]
        raise _error(
            "COMPOSITE_CONTROLLER_RESOURCE_POWERING_PATH_MISSING",
            "A generic CP action in a multi-Path workspace needs an authenticated producer-bound Powering Path or required Path record.",
            details={
                "action_id": row.get("action_id"),
                "record_id": row.get("record_id"),
                "required_authority": "authenticated producer-bound Powering Path or required Path record",
            },
        )
    concrete = _canonical_path_resource_id(value)
    return concrete or (value.strip() if isinstance(value, str) and value.strip() else None)


def _resource_name(resource_id: str) -> str:
    definition = _PATH_RESOURCE_DEFINITIONS.get(resource_id)
    return str(definition["name"]) if definition is not None else resource_id


def _nested_number(value: Any) -> int | None:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, Mapping):
        for key in ("value", "amount", "current", "maximum", "max"):
            candidate = value.get(key)
            if type(candidate) is int and candidate >= 0:
                return candidate
    return None


def _load_json(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> Any:
    if path.is_symlink() or not path.is_file():
        raise _error("COMPOSITE_CONTROLLER_SOURCE_MISSING", f"The sealed source member is missing: {path.name}")
    try:
        if path.stat().st_size > max_bytes:
            raise _error("COMPOSITE_CONTROLLER_SOURCE_TOO_LARGE", f"The sealed source member is too large: {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))
    except FoundryError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise _error("COMPOSITE_CONTROLLER_SOURCE_INVALID", f"The sealed source member is invalid: {path.name}") from exc


def _validated_output_root(value: Any) -> Path:
    """Validate an output boundary before a provider or filesystem write."""

    try:
        root = Path(value)
        current = root
        while True:
            if current.is_symlink():
                raise _error("COMPOSITE_CONTROLLER_OUTPUT_ROOT_INVALID", "The controller output root may not contain symlinked path components.")
            if current.exists():
                if not current.is_dir():
                    raise _error("COMPOSITE_CONTROLLER_OUTPUT_ROOT_INVALID", "The controller output root is not a directory.")
                break
            parent = current.parent
            if parent == current:
                break
            current = parent
    except FoundryError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise _error(
            "COMPOSITE_CONTROLLER_OUTPUT_ROOT_INVALID",
            "The controller output root cannot be used safely.",
            details={"exception_type": type(exc).__name__},
        ) from exc
    return root


def _reject_recursive_symlinks(
    root: Path,
    *,
    code: str,
    message: str,
) -> None:
    """Reject links anywhere below a workspace boundary before consuming it."""

    if root.is_symlink():
        raise _error(code, message)
    try:
        linked = next((path for path in root.rglob("*") if path.is_symlink()), None)
    except OSError as exc:
        raise _error(code, message) from exc
    if linked is not None:
        raise _error(code, message, details={"path": linked.relative_to(root).as_posix()})


def _tree_hashes(root: Path, *, include_checksums: bool = False) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and (include_checksums or path.name != "SHA256SUMS.txt")
    }


def _verify_workspace_checksums(root: Path) -> None:
    sums_path = root / "SHA256SUMS.txt"
    if sums_path.is_symlink() or not sums_path.is_file():
        raise _error("COMPOSITE_CONTROLLER_WORKSPACE_CHECKSUMS_MISSING", "The sealed workspace checksum ledger is missing.")
    declared: dict[str, str] = {}
    try:
        lines = sums_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise _error("COMPOSITE_CONTROLLER_WORKSPACE_CHECKSUMS_INVALID", "The workspace checksum ledger cannot be read.") from exc
    for line in lines:
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise _error("COMPOSITE_CONTROLLER_WORKSPACE_CHECKSUMS_INVALID", "The workspace checksum ledger is malformed.")
        digest, relative = parts
        relative = relative.lstrip("*").strip()
        relative_path = Path(relative)
        if (
            not _is_hash(digest)
            or not relative
            or relative in declared
            or relative_path.is_absolute()
            or ".." in relative_path.parts
        ):
            raise _error("COMPOSITE_CONTROLLER_WORKSPACE_CHECKSUMS_INVALID", "The workspace checksum ledger has an invalid entry.")
        declared[relative] = digest.lower()
    # Validate the root and generated Build ledgers independently.
    if (root / "Build/SHA256SUMS.txt").is_file() and not (root / "Build/SHA256SUMS.txt").is_symlink():
        actual = {
            name: digest
            for name, digest in _tree_hashes(root).items()
            if not name.startswith("Build/")
        }
    else:
        actual = _tree_hashes(root)
    if declared != actual:
        raise _error(
            "COMPOSITE_CONTROLLER_WORKSPACE_CHECKSUMS_STALE",
            "The sealed workspace checksum ledger does not match its files.",
            details={"missing": sorted(set(actual) - set(declared)), "extra": sorted(set(declared) - set(actual))},
        )
    build_root = root / "Build"
    build_ledger = build_root / "SHA256SUMS.txt"
    if build_ledger.is_file() and not build_ledger.is_symlink():
        build_declared: dict[str, str] = {}
        try:
            build_lines = build_ledger.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise _error("COMPOSITE_CONTROLLER_WORKSPACE_CHECKSUMS_INVALID", "The Build checksum ledger cannot be read.") from exc
        for line in build_lines:
            if not line.strip():
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                raise _error("COMPOSITE_CONTROLLER_WORKSPACE_CHECKSUMS_INVALID", "The Build checksum ledger is malformed.")
            digest, relative = parts
            relative = relative.lstrip("*").strip()
            relative_path = Path(relative)
            if (
                not _is_hash(digest)
                or not relative
                or relative in build_declared
                or relative_path.is_absolute()
                or ".." in relative_path.parts
            ):
                raise _error("COMPOSITE_CONTROLLER_WORKSPACE_CHECKSUMS_INVALID", "The Build checksum ledger has an invalid entry.")
            build_declared[relative] = digest.lower()
        build_actual = _tree_hashes(build_root)
        if build_declared != build_actual:
            raise _error(
                "COMPOSITE_CONTROLLER_WORKSPACE_CHECKSUMS_STALE",
                "The sealed Build checksum ledger does not match its files.",
                details={"missing": sorted(set(build_actual) - set(build_declared)), "extra": sorted(set(build_declared) - set(build_actual))},
            )


def _workspace_sha256(root: Path) -> str:
    return sha256_json(_tree_hashes(root, include_checksums=True))


def _read_candidate_pointer(workspace_service: Any, project_id: str) -> tuple[str | None, str | None, dict[str, Any]]:
    """Read the current candidate pointer without changing any state."""

    project_id = _validated_project_id(project_id)
    db = getattr(workspace_service, "db", None)
    settings = getattr(db, "settings", None)
    data_dir = getattr(settings, "data_dir", None)
    if not isinstance(data_dir, (str, Path)) or not str(data_dir):
        return None, None, {}
    pointer_path = Path(data_dir) / "factory_candidates" / project_id / "current.json"
    if pointer_path.is_symlink() or not pointer_path.is_file():
        return None, None, {}
    pointer = _load_json(pointer_path, max_bytes=256 * 1024)
    if not isinstance(pointer, Mapping) or pointer.get("project_id") not in {None, project_id}:
        raise _error("COMPOSITE_CONTROLLER_CANDIDATE_POINTER_INVALID", "The current candidate pointer is not bound to this project.")
    if pointer.get("status") not in {None, "GM_MODEL_CANDIDATE_READY"}:
        raise _error("COMPOSITE_CONTROLLER_CANDIDATE_NOT_READY", "The current candidate is not ready for controller authoring.")
    candidate_sha = pointer.get("candidate_sha256")
    candidate_path_value = pointer.get("candidate_zip")
    if not _is_hash(candidate_sha) or not isinstance(candidate_path_value, str) or not candidate_path_value:
        raise _error("COMPOSITE_CONTROLLER_CANDIDATE_POINTER_INVALID", "The current candidate pointer has no valid candidate hash/path.")
    candidate_path = Path(candidate_path_value)
    if candidate_path.is_symlink() or not candidate_path.is_file():
        raise _error("COMPOSITE_CONTROLLER_CANDIDATE_NOT_READY", "The current Command 5 candidate is unavailable.")
    try:
        actual = sha256_file(candidate_path)
    except OSError as exc:
        raise _error("COMPOSITE_CONTROLLER_CANDIDATE_NOT_READY", "The current Command 5 candidate cannot be read.") from exc
    if actual != candidate_sha:
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_HASH_MISMATCH",
            "The current Command 5 candidate hash is stale.",
            details={"expected": candidate_sha, "actual": actual},
        )
    return actual, pointer.get("projection_id"), dict(pointer)


def _candidate_hash_from_manifest(manifest: Mapping[str, Any]) -> str | None:
    for key in ("candidate_sha256", "base_candidate_sha256", "source_command5_candidate_sha256"):
        value = manifest.get(key)
        if _is_hash(value):
            return value
    return None


def _pointer_workspace_sha256(pointer: Mapping[str, Any]) -> str | None:
    """Read the server-recorded source-workspace binding from a candidate pointer."""

    values: list[Any] = [pointer.get("workspace_sha256")]
    command4 = pointer.get("character_gm_command4")
    if isinstance(command4, Mapping):
        values.append(command4.get("workspace_sha256"))
        overlay = command4.get("reviewed_command4_overlay")
        if isinstance(overlay, Mapping):
            values.append(overlay.get("source_workspace_sha256"))
    hashes = [value for value in values if value is not None]
    if not hashes:
        return None
    if any(not _is_hash(value) for value in hashes) or len(set(hashes)) != 1:
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The current candidate pointer has no consistent source-workspace hash binding.",
        )
    return str(hashes[0])


_REVIEWED_OVERLAY_FILES = {
    "manifest_sha256": "Command4_Provider_Overlay_Manifest.json",
    "surface_sha256": "Command_4/Complete_Action_Surface.json",
    "audit_sha256": "Command_4/Provider_Action_Authoring_Audit.json",
    "validation_sha256": "Validation/Command4_Provider.validation.json",
}


def _reviewed_overlay_binding(pointer: Mapping[str, Any]) -> Mapping[str, Any] | None:
    bindings: list[Mapping[str, Any]] = []
    direct = pointer.get("reviewed_command4_overlay")
    if isinstance(direct, Mapping):
        bindings.append(direct)
    command4 = pointer.get("character_gm_command4")
    if isinstance(command4, Mapping) and isinstance(command4.get("reviewed_command4_overlay"), Mapping):
        bindings.append(command4["reviewed_command4_overlay"])
    if not bindings:
        return None
    canonical = {canonical_json(dict(binding)) for binding in bindings}
    if len(canonical) != 1:
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The current candidate pointer has inconsistent reviewed Command 4 overlay bindings.",
        )
    return bindings[0]


def _verify_materialized_candidate_workspace(
    candidate_root: Path,
    source_root: Path,
    pointer: Mapping[str, Any],
    *,
    source_workspace_sha256: str,
) -> None:
    """Bind a Command 5 workspace to its sealed source plus reviewed overlay.

    A materialized candidate workspace intentionally differs from the original
    Command 1--4 source: it contains the reviewed Command 4 overlay and a
    generated ``Build`` tree.  The source-workspace receipt therefore cannot
    be compared to the candidate's whole-tree hash.  Instead, prove the exact
    source tree, allow only the four hash-bound overlay files outside Build,
    and bind the generated build manifest back to the current candidate
    pointer.
    """

    if candidate_root.resolve() == source_root.resolve() or source_root.is_symlink() or not source_root.is_dir():
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The materialized candidate workspace has no distinct sealed source workspace.",
        )
    # Hashing follows regular-file symlinks.  A candidate or source tree that
    # contains one would therefore be able to make an unrelated path appear
    # byte-equivalent to the sealed source.  Reject links before consuming any
    # receipt or build content.
    for tree_root in (source_root, candidate_root):
        _reject_recursive_symlinks(
            tree_root,
            code="COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            message="The materialized candidate and sealed source workspaces must contain regular files only.",
        )
    source_build = source_root / "Build"
    if source_build.exists() or source_build.is_symlink():
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The sealed Command 1–4 source workspace must not already contain a Build tree.",
        )
    build_root = candidate_root / "Build"
    build_ledger = build_root / "SHA256SUMS.txt"
    if build_root.is_symlink() or not build_root.is_dir() or build_ledger.is_symlink() or not build_ledger.is_file():
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The materialized candidate must contain a regular, checksummed Build tree.",
        )
    _verify_workspace_checksums(source_root)
    actual_source_sha = _workspace_sha256(source_root)
    if actual_source_sha != source_workspace_sha256:
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH",
            "The sealed source workspace no longer matches the current candidate binding.",
            details={"expected": source_workspace_sha256, "actual": actual_source_sha},
        )

    overlay = _reviewed_overlay_binding(pointer)
    if overlay is None or overlay.get("source_workspace_sha256") != source_workspace_sha256:
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The current candidate has no reviewed overlay bound to its sealed source workspace.",
        )
    for key in ("overlay_id", "request_sha256", "response_sha256", "source_workspace_sha256", "overlay_tree_sha256"):
        if not _is_hash(overlay.get(key)):
            raise _error(
                "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
                "The reviewed Command 4 overlay receipt has incomplete hash bindings.",
                details={"field": key},
            )
    for receipt_key, relative in _REVIEWED_OVERLAY_FILES.items():
        expected = overlay.get(receipt_key)
        path = candidate_root / relative
        if not _is_hash(expected) or path.is_symlink() or not path.is_file() or sha256_file(path) != expected:
            raise _error(
                "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH",
                "The materialized candidate workspace does not match its reviewed Command 4 overlay receipts.",
                details={"receipt": receipt_key, "path": relative},
            )

    overlay_manifest = _load_json(candidate_root / _REVIEWED_OVERLAY_FILES["manifest_sha256"])
    for key in ("overlay_id", "request_sha256", "response_sha256", "source_workspace_sha256"):
        if overlay_manifest.get(key) != overlay.get(key):
            raise _error(
                "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
                "The reviewed Command 4 overlay manifest is inconsistent with the candidate pointer.",
                details={"field": key},
            )

    source_files = _tree_hashes(source_root, include_checksums=True)
    candidate_files = _tree_hashes(candidate_root, include_checksums=True)
    permitted = frozenset(_REVIEWED_OVERLAY_FILES.values()) | {"SHA256SUMS.txt"}
    names = {
        name for name in set(source_files) | set(candidate_files)
        if not name.startswith("Build/") and name not in permitted
    }
    if any(source_files.get(name) != candidate_files.get(name) for name in names):
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH",
            "The materialized candidate workspace differs from its sealed source outside the reviewed overlay.",
        )
    candidate_overlay_tree_sha = sha256_json({
        name: digest for name, digest in candidate_files.items() if not name.startswith("Build/")
    })
    if candidate_overlay_tree_sha != overlay.get("overlay_tree_sha256"):
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH",
            "The materialized candidate workspace does not match the reviewed Command 4 overlay tree receipt.",
        )

    build_manifest = candidate_root / "Build/PACKAGE_MANIFEST.json"
    pointer_build_path = pointer.get("build_manifest_path")
    expected_build_sha = pointer.get("build_manifest_sha256")
    try:
        exact_build_path = build_manifest.resolve()
        pointer_build_resolved = Path(pointer_build_path).resolve() if isinstance(pointer_build_path, str) else None
    except OSError as exc:
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The current candidate build-manifest path cannot be resolved.",
        ) from exc
    if (
        pointer_build_resolved != exact_build_path
        or not _is_hash(expected_build_sha)
        or build_manifest.is_symlink()
        or not build_manifest.is_file()
        or sha256_file(build_manifest) != expected_build_sha
    ):
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The materialized candidate workspace is not bound to the current candidate build manifest.",
        )
    build_document = _load_json(build_manifest)
    declared_build = build_document.get("files") if isinstance(build_document, Mapping) else None
    if not isinstance(declared_build, list):
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The current candidate Build manifest has no exact file inventory.",
        )
    declared: dict[str, tuple[str, int]] = {}
    for row in declared_build:
        if not isinstance(row, Mapping) or set(row) != {"path", "sha256", "bytes"}:
            raise _error(
                "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
                "The current candidate Build manifest file inventory is malformed.",
            )
        relative = row.get("path")
        relative_path = Path(relative) if isinstance(relative, str) else None
        byte_count = _integer(row.get("bytes"), maximum=1_000_000_000)
        if (
            relative_path is None
            or not relative
            or relative != relative_path.as_posix()
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or not _is_hash(row.get("sha256"))
            or byte_count is None
            or relative in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}
            or relative in declared
        ):
            raise _error(
                "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
                "The current candidate Build manifest file inventory is unsafe or duplicated.",
            )
        declared[relative] = (str(row["sha256"]), byte_count)
    actual_build = {
        name: digest
        for name, digest in _tree_hashes(build_root).items()
        if name not in {"PACKAGE_MANIFEST.json", "SHA256SUMS.txt"}
    }
    if set(declared) != set(actual_build):
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH",
            "The materialized candidate Build tree is not exactly covered by its package manifest.",
        )
    for relative, (expected_digest, expected_bytes) in declared.items():
        path = build_root / relative
        if not path.is_file() or sha256_file(path) != expected_digest or path.stat().st_size != expected_bytes:
            raise _error(
                "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH",
                "The materialized candidate Build file does not match its package manifest receipt.",
                details={"path": relative},
            )


def _resolve_workspace_root(
    workspace_service: Any,
    project_id: str,
    fixed_workspace_root: Path | None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    project_id = _validated_project_id(project_id)
    pointer: dict[str, Any] = {}
    pointer_candidate_sha: str | None = None
    pointer_projection_id: str | None = None
    if fixed_workspace_root is not None:
        root = fixed_workspace_root
        metadata: dict[str, Any] = {"available": True, "workspace_path": str(root)}
    else:
        status_method = getattr(workspace_service, "status", None)
        if not callable(status_method):
            raise _error("COMPOSITE_CONTROLLER_WORKSPACE_SERVICE_INVALID", "A Factory workspace status reader is required.")
        status = status_method(project_id)
        if not isinstance(status, Mapping) or status.get("available") is not True:
            raise _error("COMPOSITE_CONTROLLER_WORKSPACE_NOT_READY", "The current sealed Factory workspace is not available.")
        value = status.get("workspace_path")
        if not isinstance(value, str) or not value:
            raise _error("COMPOSITE_CONTROLLER_WORKSPACE_PATH_INVALID", "The current Factory workspace has no path.")
        status_root = Path(value)
        metadata = dict(status)
        # A hash-checked detached candidate workspace is authoritative for
        # this target; older pointers retain the legacy status root.
        pointer_candidate_sha, pointer_projection_id, pointer = _read_candidate_pointer(workspace_service, project_id)
        candidate_workspace = pointer.get("workspace") or pointer.get("workspace_path")
        if isinstance(candidate_workspace, str) and candidate_workspace:
            candidate_root = Path(candidate_workspace)
            candidate_zip = pointer.get("candidate_zip")
            if not isinstance(candidate_zip, str) or not candidate_zip:
                raise _error(
                    "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
                    "The current candidate workspace has no candidate ZIP binding.",
                )
            try:
                candidate_parent = Path(candidate_zip).resolve().parent
                candidate_root_resolved = candidate_root.resolve()
            except OSError as exc:
                raise _error(
                    "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
                    "The current candidate workspace path cannot be resolved.",
                ) from exc
            if candidate_root_resolved.parent != candidate_parent:
                raise _error(
                    "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
                    "The current candidate workspace is not the workspace paired with its candidate ZIP.",
                )
            root = candidate_root
        else:
            root = status_root
    if root.is_symlink() or not root.is_dir():
        raise _error("COMPOSITE_CONTROLLER_WORKSPACE_MISSING", "The sealed Factory workspace directory is unavailable.")
    _reject_recursive_symlinks(
        root,
        code="COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
        message="The selected Factory workspace must contain regular files only.",
    )
    manifest_path = root / "Workspace_Manifest.json"
    manifest = _load_json(manifest_path)
    if not isinstance(manifest, Mapping) or manifest.get("workspace_status") != "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE":
        raise _error("COMPOSITE_CONTROLLER_WORKSPACE_STATUS_INVALID", "The workspace is not sealed at the Command 1–4 boundary.")
    if manifest.get("project_id") not in {None, project_id}:
        raise _error("COMPOSITE_CONTROLLER_WORKSPACE_PROJECT_MISMATCH", "The workspace is bound to a different project.")
    _verify_workspace_checksums(root)
    workspace_sha = _workspace_sha256(root)
    pointer_workspace_sha = _pointer_workspace_sha256(pointer) if pointer else None
    if pointer and pointer_workspace_sha is None:
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The current candidate pointer does not bind its workspace contents.",
        )
    if pointer_workspace_sha is not None:
        direct_workspace_sha = pointer.get("workspace_sha256")
        if direct_workspace_sha is not None:
            if workspace_sha != pointer_workspace_sha:
                raise _error(
                    "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_HASH_MISMATCH",
                    "The selected candidate workspace is not the hash-bound workspace for the current candidate.",
                    details={"expected": pointer_workspace_sha, "actual": workspace_sha},
                )
        else:
            _verify_materialized_candidate_workspace(
                root,
                status_root,
                pointer,
                source_workspace_sha256=pointer_workspace_sha,
            )
    # A detached candidate may have a different tree hash than status.
    if root == (Path(metadata.get("workspace_path")) if isinstance(metadata.get("workspace_path"), str) else root):
        if _is_hash(metadata.get("workspace_sha256")) and metadata["workspace_sha256"] != workspace_sha:
            raise _error("COMPOSITE_CONTROLLER_WORKSPACE_STALE", "The Factory workspace changed after it was sealed.")
    metadata["workspace_sha256"] = workspace_sha

    manifest_candidate_sha = _candidate_hash_from_manifest(manifest)
    if pointer_candidate_sha and manifest_candidate_sha and manifest_candidate_sha != pointer_candidate_sha:
        raise _error(
            "COMPOSITE_CONTROLLER_CANDIDATE_WORKSPACE_BINDING_INVALID",
            "The selected workspace manifest is bound to a different candidate.",
            details={"expected": pointer_candidate_sha, "actual": manifest_candidate_sha},
        )
    candidate_sha = manifest_candidate_sha or metadata.get("candidate_sha256")
    if fixed_workspace_root is None:
        candidate_sha = pointer_candidate_sha or candidate_sha
        metadata["candidate_pointer"] = pointer
    if not _is_hash(candidate_sha):
        # Fixed roots support deterministic tests; production uses the pointer.
        if fixed_workspace_root is None:
            raise _error("COMPOSITE_CONTROLLER_CANDIDATE_NOT_READY", "A current Command 5 candidate is required before controller authoring.")
        candidate_sha = sha256_json({"workspace_sha256": workspace_sha, "project_id": project_id})
        metadata["candidate_sha256_source"] = "fixed_test_workspace_binding"
    projection_id = pointer_projection_id or manifest.get("projection_id") or metadata.get("projection_id")
    if not isinstance(projection_id, str) or not projection_id.strip():
        projection_id = "projection." + sha256_json({"project_id": project_id, "workspace_sha256": workspace_sha})[:24]
    metadata.update({"candidate_sha256": candidate_sha, "projection_id": projection_id})
    return root, metadata, dict(manifest)


def _iter_named_rows(value: Any, *, keys: tuple[str, ...]) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        rows: list[Mapping[str, Any]] = []
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, list):
                rows.extend(item for item in candidate if isinstance(item, Mapping))
            elif isinstance(candidate, Mapping):
                rows.append(candidate)
        if not rows and any(
            key in value for key in ("resource_id", "resource_name", "current", "current_value", "maximum", "max", "max_value")
        ):
            rows.append(value)
        if not rows:
            for key, candidate in value.items():
                if isinstance(candidate, Mapping):
                    row = dict(candidate)
                    row.setdefault("resource_id", str(key))
                    row.setdefault("name", str(key))
                    rows.append(row)
        return rows
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _extract_resource_authority(root: Path) -> dict[str, Any]:
    candidates: list[tuple[str, Any]] = []
    for relative in (
        "Command_2/Canonical_Stats_Resource_Block.json",
        "Character_Master_Ledger.json",
        "Command_2/Canonical_Advancement_Ledger.json",
    ):
        path = root / relative
        if path.is_file() and not path.is_symlink():
            candidates.append((relative, _load_json(path)))
    found: list[dict[str, Any]] = []
    for relative, document in candidates:
        direct_values: list[Any] = []
        if isinstance(document, Mapping):
            for key in ("resources", "resource_block", "combat_resources"):
                direct_values.append(document.get(key))
            if any(key in document for key in ("resource_id", "resource_name", "current", "maximum", "max")):
                direct_values.append(document)
        rows: list[Mapping[str, Any]] = []
        for value in direct_values:
            rows.extend(_iter_named_rows(value, keys=("resources", "definitions", "records", "items", "entries")))
        for row in rows:
            # ``resource_id`` is the sealed authority key.  Some ledgers also
            # carry an unrelated record ``id``; only use id/key as identity
            # fallbacks when the canonical field is absent.
            raw_ids = (
                [row.get("resource_id")]
                if _resource_key(row.get("resource_id")) is not None
                else [row.get("id"), row.get("key")]
            )
            raw_names = [row.get("name"), row.get("display_name"), row.get("resource_name")]
            concrete_ids = {
                concrete
                for value in (*raw_ids, *raw_names)
                for concrete in (_canonical_path_resource_id(value),)
                if concrete is not None
            }
            generic_present = any(_resource_key(value) in _GENERIC_RESOURCE_ALIASES for value in (*raw_ids, *raw_names))
            unknown_identity_values = [
                value
                for value in (*raw_ids, *raw_names)
                if _resource_key(value) is not None
                and _resource_key(value) not in _GENERIC_RESOURCE_ALIASES
                and _canonical_path_resource_id(value) is None
            ]
            if not concrete_ids:
                # Unknown resources are owned by another subsystem.  A bare
                # generic CP row, however, cannot establish which Path it
                # aliases and is therefore malformed authority.
                if generic_present:
                    raise _error(
                        "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
                        "The sealed generic CP row does not identify one concrete active Path resource.",
                        details={"source": relative},
                    )
                continue
            if unknown_identity_values:
                raise _error(
                    "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
                    "A sealed resource row contains an unknown identity beside a concrete Path resource.",
                    details={"source": relative},
                )
            if len(concrete_ids) != 1:
                raise _error(
                    "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
                    "A sealed resource row names more than one concrete Path resource.",
                    details={"source": relative},
                )
            resource_id = next(iter(concrete_ids))
            current = _nested_number(row.get("current"))
            if current is None:
                current = _nested_number(row.get("current_value"))
            maximum = _nested_number(row.get("maximum"))
            if maximum is None:
                maximum = _nested_number(row.get("max"))
            if maximum is None:
                maximum = _nested_number(row.get("max_value"))
            if (
                current is None
                or maximum is None
                or current > maximum
                or maximum > COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX
            ):
                raise _error(
                    "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
                    "The sealed active Path resource has invalid current/maximum bounds.",
                    details={"source": relative, "resource_id": resource_id},
                )
            record: dict[str, Any] = {
                "resource_id": resource_id,
                "alias": COMPOSITE_CONTROLLER_RESOURCE_ALIAS,
                "name": _resource_name(resource_id),
                "current": current,
                "maximum": maximum,
                "source": relative,
                "source_backed": True,
            }
            # Preserve source-backed formula lineage when present, while
            # keeping the runtime authority limited to the canonical fields.
            if "formula_id" in row:
                record["formula_id"] = deepcopy(row["formula_id"])
            if "authority_components" in row:
                record["authority_components"] = deepcopy(row["authority_components"])
            found.append(record)
    if not found:
        raise _error(
            "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_MISSING",
            "The sealed source-backed active Path resource current/max is unavailable.",
        )
    by_id: dict[str, dict[str, Any]] = {}
    for item in found:
        resource_id = item["resource_id"]
        prior = by_id.get(resource_id)
        if prior is not None and (prior["current"], prior["maximum"]) != (item["current"], item["maximum"]):
            raise _error(
                "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
                "The sealed workspace contains conflicting authority for one Path resource.",
                details={
                    "resource_id": resource_id,
                    "values": sorted({
                        (candidate["current"], candidate["maximum"])
                        for candidate in found
                        if candidate["resource_id"] == resource_id
                    }),
                },
            )
        by_id.setdefault(resource_id, item)
    unique = list(by_id.values())
    if not unique:
        raise _error(
            "COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID",
            "The sealed workspace contains no concrete Path resource authority.",
        )
    if len(unique) == 1:
        # Files are traversed in authority priority order, so the first
        # agreeing record is the canonical source while duplicate ledgers are
        # corroboration.
        return deepcopy(unique[0])
    # Multiple independently authenticated pools remain distinct.  There is
    # deliberately no top-level active resource: generic CP remains blocked
    # until an upstream producer supplies an authenticated Powering Path record.
    return {
        "resources": [deepcopy(by_id[resource_id]) for resource_id in sorted(by_id)],
        "source_backed": True,
    }


def _extract_identity(root: Path, manifest: Mapping[str, Any]) -> dict[str, str]:
    identity: dict[str, str] = {}
    if isinstance(manifest.get("identity"), Mapping):
        value = manifest["identity"]
        for key in ("display_name", "name", "character_name"):
            text = _safe_text(value.get(key), limit=160)
            if text:
                identity["name"] = text
                break
        for key in ("role", "cultivation_role", "path", "realm"):
            text = _safe_text(value.get(key), limit=160)
            if text:
                identity["role" if key != "realm" else "realm"] = text
    for relative in ("Command_1/Character_Blueprint.json", "Command_2/Canonical_Stats_Resource_Block.json"):
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        document = _load_json(path)
        if not isinstance(document, Mapping):
            continue
        for container_key in ("identity", "character"):
            container = document.get(container_key)
            if not isinstance(container, Mapping):
                continue
            if "name" not in identity:
                identity["name"] = _first_text(container.get("display_name"), container.get("name"), container.get("character_name"), limit=160) or ""
            if "role" not in identity:
                identity["role"] = _first_text(container.get("role"), container.get("cultivation_role"), container.get("path"), container.get("realm"), limit=160) or ""
            if "concept" not in identity:
                identity["concept"] = _first_text(container.get("concept"), container.get("character_concept"), limit=600) or ""
    return {key: value for key, value in identity.items() if value}


def _is_action_row(row: Mapping[str, Any]) -> bool:
    if row.get("execution_authority") is False or row.get("executable") is False:
        return False
    economy = _canonical_economy(row.get("economy") or row.get("action_type") or row.get("bucket"))
    return economy is not None and economy != "procedure"


def _action_packet(row: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unbound_powering_path_fields(row)
    packet: dict[str, Any] = {}
    for field in _ACTION_MECHANIC_FIELDS:
        if field in row and row[field] is not None:
            packet[field] = deepcopy(row[field])
    action_id = packet.get("action_id")
    record_id = packet.get("record_id")
    if not isinstance(action_id, str) or not action_id.strip() or not isinstance(record_id, str) or not record_id.strip():
        raise _error("COMPOSITE_CONTROLLER_ACTION_ID_INVALID", "Every executable action must carry a stable action and record identity.")
    packet["action_id"] = action_id
    packet["record_id"] = record_id
    packet["name"] = _first_text(packet.get("name"), packet.get("display_name"), limit=160) or record_id
    packet["economy"] = _canonical_economy(packet.get("economy") or packet.get("action_type") or packet.get("bucket"))
    if packet["economy"] is None or packet["economy"] == "procedure":
        raise _error("COMPOSITE_CONTROLLER_ACTION_ECONOMY_INVALID", "Every linked action must have a canonical executable economy.")
    return packet


def _resource_gain_rows(
    row: Mapping[str, Any],
    resource_authority: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw = row.get("resource_gains")
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise _error("COMPOSITE_CONTROLLER_ACTION_GAIN_INVALID", "An action resource-gain container is invalid.")
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise _error("COMPOSITE_CONTROLLER_ACTION_GAIN_INVALID", "An action resource gain is invalid.")
        resource_value = item.get("resource_id") or item.get("id") or item.get("resource")
        resource_id = _action_resource_id(resource_value, row, resource_authority)
        pool = None
        if resource_id in _PATH_RESOURCE_DEFINITIONS:
            try:
                pool = _resource_pool(resource_authority, resource_id)
            except FoundryError:
                pool = None
        resource_maximum = pool["maximum"] if pool is not None else COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX
        amount = _integer(item.get("amount"), maximum=resource_maximum)
        if amount is None:
            amount = _integer(item.get("gain"), maximum=resource_maximum)
        if resource_id is None or amount is None:
            raise _error("COMPOSITE_CONTROLLER_ACTION_GAIN_INVALID", "An action resource gain needs a bounded resource and amount.")
        if resource_id not in _PATH_RESOURCE_DEFINITIONS or pool is None:
            raise _error(
                "COMPOSITE_CONTROLLER_RESOURCE_UNSUPPORTED",
                "The action names a resource without sealed Path authority.",
                details={"resource_id": resource_id},
            )
        result.append({"resource_id": resource_id, "amount": amount})
    return result


def _canonicalize_action_resource_rows(
    packet: Mapping[str, Any],
    resource_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Make runtime resource rows concrete without changing source mechanics."""

    normalized = deepcopy(dict(packet))
    if "resource_costs" in packet:
        _total, normalized["resource_costs"] = _resource_costs(packet, resource_authority)
    if "resource_requirements" in packet:
        normalized["resource_requirements"] = _resource_requirements(packet, resource_authority)
    if "resource_gains" in packet:
        normalized["resource_gains"] = _resource_gain_rows(packet, resource_authority)
    return normalized


def _load_actions(root: Path, resource_authority: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    resource_authority = resource_authority or _extract_resource_authority(root)
    surface_path = root / "Command_4/Complete_Action_Surface.json"
    candidates_path = root / "Command_4/Action_Authoring_Candidates.json"
    rows: list[Any] = []
    if surface_path.is_file() and not surface_path.is_symlink():
        surface = _load_json(surface_path)
        rows = surface.get("actions") if isinstance(surface, Mapping) else []
    if not isinstance(rows, list) or not rows:
        if candidates_path.is_file() and not candidates_path.is_symlink():
            candidates = _load_json(candidates_path)
            rows = candidates.get("candidates") if isinstance(candidates, Mapping) else []
    if not isinstance(rows, list):
        raise _error("COMPOSITE_CONTROLLER_ACTIONS_MISSING", "The sealed executable action surface is unavailable.")
    actions: list[dict[str, Any]] = []
    missing_powering_path: FoundryError | None = None
    for row in rows:
        if not isinstance(row, Mapping) or not _is_action_row(row):
            continue
        packet = _action_packet(row)
        try:
            # Validate all resource containers before offering an action.  A
            # positive untracked resource makes the action ineligible; a
            # different concrete Path resource is a hard cross-resource error.
            _resource_costs(packet, resource_authority)
            _resource_requirements(packet, resource_authority)
            _resource_gains(packet, resource_authority)
        except FoundryError as exc:
            details = exc.details if isinstance(exc.details, Mapping) else {}
            resource_id = details.get("resource_id")
            if exc.code == "COMPOSITE_CONTROLLER_RESOURCE_POWERING_PATH_MISSING":
                # A catalog can contain generic-CP actions awaiting a use-time
                # Path choice. Never offer them as executable controller steps.
                # Untrusted declared Path fields still fail in _action_packet,
                # before this eligibility filter.
                missing_powering_path = missing_powering_path or exc
                continue
            if exc.code == "COMPOSITE_CONTROLLER_RESOURCE_UNSUPPORTED" and resource_id not in _PATH_RESOURCE_DEFINITIONS:
                continue
            raise
        actions.append(_canonicalize_action_resource_rows(packet, resource_authority))
    if len(actions) < 2:
        if missing_powering_path is not None:
            raise missing_powering_path
        raise _error("COMPOSITE_CONTROLLER_ACTIONS_INCOMPLETE", "At least two executable Actions are required for a composite controller.")
    if len(actions) > 32:
        raise _error("COMPOSITE_CONTROLLER_ACTIONS_TOO_MANY", "The executable action surface exceeds the bounded controller input.")
    action_ids = [row["action_id"] for row in actions]
    record_ids = [row["record_id"] for row in actions]
    if len(action_ids) != len(set(action_ids)) or len(record_ids) != len(set(record_ids)):
        raise _error("COMPOSITE_CONTROLLER_ACTION_ID_DUPLICATE", "The executable action surface contains duplicate identities.")
    return actions


def _available_states(root: Path, actions: list[Mapping[str, Any]]) -> list[str]:
    values: list[Any] = []
    for relative in ("Command_2/Canonical_Stats_Resource_Block.json", "Command_4/Complete_Action_Surface.json"):
        path = root / relative
        if path.is_file() and not path.is_symlink():
            document = _load_json(path)
            if isinstance(document, Mapping):
                for key in ("available_states", "states", "state_effects", "state_registry"):
                    values.append(document.get(key))
    for row in actions:
        for key in ("available_states", "states", "state_arrays"):
            values.append(row.get(key))
    result: set[str] = set()

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 3:
            return
        if isinstance(value, str):
            text = _safe_text(value, limit=160)
            if text and text.casefold() not in {"none", "null", "absent", "unavailable"}:
                result.add(text)
        elif isinstance(value, Mapping):
            for key in ("state_id", "id", "name", "display_name"):
                if key in value:
                    visit(value[key], depth + 1)
            for key in ("states", "typed_definitions", "items", "entries"):
                if key in value:
                    visit(value[key], depth + 1)
        elif isinstance(value, list):
            for item in value:
                visit(item, depth + 1)

    for value in values:
        visit(value)
    return sorted(result, key=str.casefold)


def _resource_costs(
    row: Mapping[str, Any],
    resource_authority: Mapping[str, Any] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    pools = _resource_rows(resource_authority)
    active_maximum = int(pools[0]["maximum"]) if len(pools) == 1 else COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX
    raw = row.get("resource_costs")
    items: list[Any]
    if isinstance(raw, list):
        items = raw
    elif raw in (None, {}):
        items = []
    else:
        raise _error("COMPOSITE_CONTROLLER_ACTION_COST_INVALID", "An action resource-cost container is invalid.")
    result: list[dict[str, Any]] = []
    total = 0
    for item in items:
        if not isinstance(item, Mapping):
            raise _error("COMPOSITE_CONTROLLER_ACTION_COST_INVALID", "An action resource-cost row is invalid.")
        resource_value = item.get("resource_id") or item.get("id") or item.get("resource")
        resource_id = _action_resource_id(resource_value, row, resource_authority)
        pool = None
        if resource_id in _PATH_RESOURCE_DEFINITIONS:
            try:
                pool = _resource_pool(resource_authority, resource_id)
            except FoundryError:
                pool = None
        resource_maximum = pool["maximum"] if pool is not None else COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX
        amount = _integer(item.get("amount"), maximum=resource_maximum)
        if amount is None:
            amount = _integer(item.get("cost"), maximum=resource_maximum)
        if resource_id is None or amount is None:
            raise _error("COMPOSITE_CONTROLLER_ACTION_COST_INVALID", "An action resource cost needs a resource ID and bounded amount.")
        if resource_id in _PATH_RESOURCE_DEFINITIONS and pool is not None:
            result.append({"resource_id": resource_id, "amount": amount})
            total += amount
        else:
            raise _error(
                "COMPOSITE_CONTROLLER_RESOURCE_UNSUPPORTED",
                "The action names a resource without sealed Path authority.",
                details={"resource_id": resource_id},
            )
    if items:
        return total, result
    cost = row.get("cost")
    if type(cost) is int:
        if cost < 0 or cost > active_maximum:
            raise _error("COMPOSITE_CONTROLLER_ACTION_COST_INVALID", "An action cost is outside the bounded range.")
        if cost == 0:
            return 0, []
        resource_id = _action_resource_id(COMPOSITE_CONTROLLER_RESOURCE_ALIAS, row, resource_authority)
        pool = _resource_pool(resource_authority, resource_id)
        if cost > int(pool["maximum"]):
            raise _error("COMPOSITE_CONTROLLER_ACTION_COST_INVALID", "An action cost is outside the bounded range.")
        return cost, [{"resource_id": resource_id, "amount": cost}]
    if isinstance(cost, str):
        folded = " ".join(cost.strip().casefold().split())
        # Legacy scalar costs may include a source description after ``None``.
        first_line = " ".join(cost.splitlines()[0].strip().casefold().split()) if cost.splitlines() else folded
        if folded in _NONE_COST_TEXT or first_line in _NONE_COST_TEXT or _canonical_economy(first_line) is not None:
            return 0, []
        match = re.fullmatch(r"([0-9]+)\s*(cp|cultivation\s+points?|stamina|qi|resonance)?", first_line)
        if match:
            amount = int(match.group(1))
            suffix = match.group(2)
            resource_id = _action_resource_id(suffix or COMPOSITE_CONTROLLER_RESOURCE_ALIAS, row, resource_authority)
            pool = _resource_pool(resource_authority, resource_id)
            if amount > int(pool["maximum"]):
                raise _error("COMPOSITE_CONTROLLER_ACTION_COST_INVALID", "An action cost is outside the bounded range.")
            return amount, ([{"resource_id": resource_id, "amount": amount}] if amount else [])
        # A bounded scalar for another resource is an ineligible action, not
        # a license to reinterpret it as CP.  ``_load_actions`` drops this
        # only when the row is otherwise executable; response/artifact paths
        # retain the same fail-closed error.
        other = re.fullmatch(r"([0-9]+)\s+([A-Za-z][A-Za-z0-9 _-]{0,79})", first_line)
        if other:
            amount = int(other.group(1))
            resource_id = _action_resource_id(other.group(2), row, resource_authority)
            raise _error(
                "COMPOSITE_CONTROLLER_RESOURCE_UNSUPPORTED",
                "The action names a resource without sealed Path authority.",
                details={"resource_id": resource_id or other.group(2).strip()},
            )
    if cost is None:
        return 0, []
    raise _error("COMPOSITE_CONTROLLER_ACTION_COST_INVALID", "An action has an unparseable resource cost; fail closed.")


def _resource_requirements(
    row: Mapping[str, Any],
    resource_authority: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw = row.get("resource_requirements")
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise _error("COMPOSITE_CONTROLLER_ACTION_REQUIREMENT_INVALID", "An action resource-requirement container is invalid.")
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise _error("COMPOSITE_CONTROLLER_ACTION_REQUIREMENT_INVALID", "An action resource requirement is invalid.")
        resource_value = item.get("resource_id") or item.get("id") or item.get("resource")
        resource_id = _action_resource_id(resource_value, row, resource_authority)
        pool = None
        if resource_id in _PATH_RESOURCE_DEFINITIONS:
            try:
                pool = _resource_pool(resource_authority, resource_id)
            except FoundryError:
                pool = None
        resource_maximum = pool["maximum"] if pool is not None else COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX
        minimum_value = item.get("minimum")
        if minimum_value is None:
            minimum_value = item.get("amount")
        minimum = _integer(minimum_value, maximum=resource_maximum)
        if resource_id is None or minimum is None:
            raise _error("COMPOSITE_CONTROLLER_ACTION_REQUIREMENT_INVALID", "An action resource requirement needs a bounded resource and minimum.")
        if resource_id not in _PATH_RESOURCE_DEFINITIONS or pool is None:
            raise _error(
                "COMPOSITE_CONTROLLER_RESOURCE_UNSUPPORTED",
                "The action names a resource without sealed Path authority.",
                details={"resource_id": resource_id},
            )
        result.append({"resource_id": resource_id, "minimum": minimum})
    return result


def _resource_gains(
    row: Mapping[str, Any],
    resource_authority: Mapping[str, Any] | None = None,
) -> int:
    return sum(item["amount"] for item in _resource_gain_rows(row, resource_authority))


def _intrinsic_states(row: Mapping[str, Any]) -> list[str]:
    result: list[str] = []

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 3:
            return
        if isinstance(value, str):
            text = _safe_text(value, limit=160)
            if text and text.casefold() not in {"none", "null", "absent", "unavailable"}:
                result.append(text)
        elif isinstance(value, Mapping):
            for key in ("state_id", "id", "name", "display_name"):
                if key in value:
                    visit(value[key], depth + 1)
            for key in ("states", "required_states", "requires_states", "state_requirements"):
                if key in value:
                    visit(value[key], depth + 1)
        elif isinstance(value, list):
            for item in value:
                visit(item, depth + 1)

    for key in ("requires_states", "required_states", "state_requirements", "required_state_ids"):
        if key in row:
            visit(row[key])
    return sorted(set(result), key=str.casefold)


def _validate_provenance(value: Any, *, allow_legacy: bool) -> dict[str, Any]:
    """Validate the mode discriminator without weakening legacy receipts."""

    if not isinstance(value, Mapping):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The controller artifact provenance is incomplete.")
    if "legacy_playbook_preserved" in value:
        if not allow_legacy or value.get("legacy_playbook_preserved") is not True:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The legacy playbook provenance is invalid.")
        value = {key: item for key, item in value.items() if key != "legacy_playbook_preserved"}
    keys = set(value)
    if keys == set(_BASE_PROVENANCE_KEYS):
        if not allow_legacy:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The controller artifact provenance needs an explicit resolution mode.")
        mode = "legacy_provider"
        selector_id = None
        provider_call_count = 1
    elif keys == set(_BASE_PROVENANCE_KEYS) | {"resolution_mode", "provider_call_count"}:
        mode = value.get("resolution_mode")
        selector_id = None
        provider_call_count = value.get("provider_call_count")
        if mode != COMPOSITE_CONTROLLER_RESOLUTION_LOCAL or type(provider_call_count) is not int or provider_call_count != 1:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The local-provider provenance discriminator is invalid.")
    elif keys == set(_BASE_PROVENANCE_KEYS) | {"resolution_mode", "provider_call_count", "selector_id"}:
        mode = value.get("resolution_mode")
        selector_id = value.get("selector_id")
        provider_call_count = value.get("provider_call_count")
        if (
            mode != COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED
            or type(provider_call_count) is not int
            or provider_call_count != 0
            or not _is_selector_id(selector_id)
        ):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The delegated-response provenance discriminator is invalid.")
    else:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The controller artifact provenance has unsupported fields.")
    if (
        value.get("provider_target") != COMPOSITE_CONTROLLER_TARGET
        or value.get("provider_retry_count") != 0
        or any(not _is_hash(value.get(key)) for key in ("request_sha256", "provider_request_sha256", "response_sha256"))
    ):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The controller artifact provenance is incomplete.")
    return {"resolution_mode": mode, "selector_id": selector_id, "provider_call_count": provider_call_count}


def _validate_controller_artifact(artifact: Mapping[str, Any], *, project_id: str | None = None, candidate_sha256: str | None = None, projection_id: str | None = None) -> None:
    expected_keys = {
        "schema_version", "project_id", "projection_id", "base_candidate_sha256", "source_workspace_sha256",
        "execution_authority", "controller_policy_registered", "resource_authority", "composite_controller",
        "linked_actions", "provenance",
    }
    legacy_playbook_shape = set(artifact) == expected_keys | {"display_only_playbooks"}
    if (set(artifact) != expected_keys and not legacy_playbook_shape) or artifact.get("schema_version") != COMPOSITE_CONTROLLER_ARTIFACT_SCHEMA:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_ARTIFACT_INVALID", "The controller artifact contents are incomplete or unsupported.")
    if legacy_playbook_shape and not isinstance(artifact.get("display_only_playbooks"), list):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_ARTIFACT_INVALID", "The legacy controller playbook summary is invalid.")
    artifact_project_id = _validated_project_id(artifact.get("project_id"))
    if project_id is not None and artifact_project_id != _validated_project_id(project_id):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_LINEAGE_MISMATCH", "The controller artifact project binding is stale.")
    artifact_candidate = artifact.get("base_candidate_sha256")
    artifact_workspace = artifact.get("source_workspace_sha256")
    if not _is_hash(artifact_candidate) or not _is_hash(artifact_workspace):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_LINEAGE_MISMATCH", "The controller artifact has an invalid hash lineage.")
    if candidate_sha256 is not None:
        if not _is_hash(candidate_sha256) or artifact_candidate != candidate_sha256:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_LINEAGE_MISMATCH", "The controller artifact candidate binding is stale.")
    artifact_projection = _safe_identifier(artifact.get("projection_id"), limit=160)
    if artifact_projection is None:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_LINEAGE_MISMATCH", "The controller artifact projection binding is invalid.")
    if projection_id is not None and artifact_projection != _safe_identifier(projection_id, limit=160):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_LINEAGE_MISMATCH", "The controller artifact projection binding is stale.")
    if artifact.get("execution_authority") is not True or artifact.get("controller_policy_registered") is not True:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_AUTHORITY_INVALID", "The controller artifact does not register execution authority.")

    resource = artifact.get("resource_authority")
    if not isinstance(resource, Mapping) or resource.get("source_backed") is not True:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact resource authority is not source-backed.")
    resource_rows = _resource_rows(resource)
    for pool in resource_rows:
        resource_id = pool["resource_id"]
        if (
            pool.get("source_backed") is not True
            or pool.get("resource_id") != resource_id
            or pool.get("name") != _resource_name(resource_id)
            or _integer(pool.get("current"), maximum=COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX) is None
            or _integer(pool.get("maximum"), maximum=COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX) is None
            or int(pool["current"]) > int(pool["maximum"])
        ):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact resource bounds are invalid.")
    resource_id = resource_rows[0]["resource_id"] if len(resource_rows) == 1 else None

    controller = artifact.get("composite_controller")
    if not isinstance(controller, Mapping) or controller.get("composite_id") != COMPOSITE_CONTROLLER_ID or controller.get("execution_role") != COMPOSITE_CONTROLLER_TARGET:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact target is invalid.")
    if not isinstance(controller.get("sequence"), list) or len(controller["sequence"]) < 2 or len(controller["sequence"]) > 32:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact sequence is invalid.")
    budget = controller.get("resource_budget")
    if not isinstance(budget, Mapping):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact budget is invalid.")
    budget_limits: dict[str, int] = {}
    if len(resource_rows) == 1:
        maximum = int(resource_rows[0]["maximum"])
        if budget.get("resource_id") != resource_id or budget.get("alias") != COMPOSITE_CONTROLLER_RESOURCE_ALIAS:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", f"The controller artifact budget is not bound to {_resource_name(resource_id)}.")
        max_spend = _integer(budget.get("max_spend"), maximum=maximum)
        if max_spend is None:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact budget is invalid.")
        budget_limits[resource_id] = max_spend
    else:
        budget_rows = budget.get("resource_budgets")
        if not isinstance(budget_rows, list) or len(budget_rows) != len(resource_rows):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact must budget every sealed resource pool.")
        pool_by_id = {pool["resource_id"]: pool for pool in resource_rows}
        for item in budget_rows:
            if not isinstance(item, Mapping):
                raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact budget row is invalid.")
            item_id = _canonical_path_resource_id(item.get("resource_id"))
            pool = pool_by_id.get(item_id)
            item_max = _integer(item.get("max_spend"), maximum=int(pool["maximum"]) if pool is not None else COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX)
            if item.get("resource_id") != item_id or pool is None or item_max is None or item_id in budget_limits:
                raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact budget must name each sealed pool exactly once.")
            budget_limits[item_id] = item_max
        if set(budget_limits) != set(pool_by_id):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact budget does not cover every sealed pool.")

    linked = artifact.get("linked_actions")
    controller_linked = controller.get("linked_actions")
    if not isinstance(linked, list) or linked != controller_linked:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact linked-action binding is invalid.")
    action_by_id: dict[str, Mapping[str, Any]] = {}
    for action in linked:
        if not isinstance(action, Mapping):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_ACTION_INVALID", "The controller artifact linked action is invalid.")
        try:
            normalized = _canonicalize_action_resource_rows(_action_packet(action), resource)
        except FoundryError as exc:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_ACTION_INVALID", "The controller artifact linked action is invalid.") from exc
        supplied_normalized = _canonicalize_action_resource_rows(_action_packet(action), resource)
        if normalized != dict(action) or normalized != supplied_normalized or action["action_id"] in action_by_id:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_ACTION_INVALID", "The controller artifact linked action packet is not canonical.")
        action_by_id[action["action_id"]] = normalized

    total_cost = 0
    cost_totals = {pool["resource_id"]: 0 for pool in resource_rows}
    round_economies: dict[tuple[int, str], int] = {}
    previous_offset = -1
    sequence = controller["sequence"]
    for index, step in enumerate(sequence, start=1):
        if not isinstance(step, Mapping) or step.get("step") != index:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact sequence numbering is invalid.")
        action = step.get("action")
        action_id = step.get("action_id")
        economy = _canonical_economy(step.get("economy"))
        offset = _integer(step.get("round_offset"), maximum=20)
        if not isinstance(action, Mapping) or not isinstance(action_id, str) or action_id not in action_by_id or dict(action) != dict(action_by_id[action_id]) or economy != action_by_id[action_id].get("economy") or offset is None or offset < previous_offset:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact sequence packet is invalid.")
        previous_offset = offset
        round_key = (offset, economy)
        round_economies[round_key] = round_economies.get(round_key, 0) + 1
        if round_economies[round_key] > _ROUND_ECONOMY_CAPACITY[economy]:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact exceeds per-round economy capacity.")
        cost, rows = _resource_costs(action_by_id[action_id], resource)
        if step.get("resource_costs") != rows:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact resource costs do not match the action packet.")
        total_cost += cost
        for cost_row in rows:
            cost_totals[cost_row["resource_id"]] += cost_row["amount"]
    if len(resource_rows) == 1:
        if controller["resource_budget"].get("total_sequence_cost") != total_cost or total_cost > budget_limits[resource_rows[0]["resource_id"]]:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact sequence cost is not bound to its budget.")
    else:
        for item in controller["resource_budget"]["resource_budgets"]:
            if item.get("total_sequence_cost") != cost_totals[item["resource_id"]] or cost_totals[item["resource_id"]] > budget_limits[item["resource_id"]]:
                raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact sequence cost is not bound to each pool budget.")

    fallback = controller.get("fallback")
    if not isinstance(fallback, Mapping) or fallback.get("action_id") not in action_by_id or not isinstance(fallback.get("action"), Mapping) or dict(fallback["action"]) != dict(action_by_id[fallback["action_id"]]):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact fallback packet is invalid.")
    fallback_cost, fallback_rows = _resource_costs(action_by_id[fallback["action_id"]], resource)
    if fallback_cost != 0 or fallback.get("resource_costs") != fallback_rows:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact fallback is not zero-cost.")
    conditional = controller.get("conditional_options")
    if not isinstance(conditional, list):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact conditional options are invalid.")
    for option in conditional:
        if not isinstance(option, Mapping) or option.get("action_id") not in action_by_id or not isinstance(option.get("action"), Mapping) or dict(option["action"]) != dict(action_by_id[option["action_id"]]):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact conditional packet is invalid.")

    _validate_provenance(artifact.get("provenance"), allow_legacy=True)


def _replay_controller_legality(
    controller: Mapping[str, Any],
    action_by_id: Mapping[str, Mapping[str, Any]],
    resource: Mapping[str, Any],
    available_states: set[str] | None = None,
) -> None:
    """Replay resource/state legality from the sealed workspace authority.

    Artifact validation must not trust the sequence totals alone: a forged
    overlay can otherwise spend the same declared total twice before the
    current resource is exhausted.  This deliberately mirrors the response
    validator's ordered deduction/gain semantics using only source-bound
    action packets.
    """

    resource_rows = _resource_rows(resource)
    balances = _resource_balances(resource)
    initial_balances = deepcopy(balances)
    try:
        budget_limits = _validated_budget_limits(controller, resource)
    except FoundryError as exc:
        raise _error(
            "COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID",
            "The replay budget is not bound to the sealed resource pools.",
            details=exc.details,
        ) from exc

    def packet_for(action_id: Any) -> Mapping[str, Any]:
        if not isinstance(action_id, str) or action_id not in action_by_id:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_ACTION_INVALID", "The replay references an unknown action.")
        return action_by_id[action_id]

    def action_resources(action: Mapping[str, Any]) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        try:
            cost, cost_rows = _resource_costs(action, resource)
            requirements = _resource_requirements(action, resource)
            gains = _resource_gain_rows(action, resource)
        except FoundryError as exc:
            raise _error(
                "COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID",
                "The replay action contains unsupported resource authority.",
                details=exc.details,
            ) from exc
        return cost, cost_rows, requirements, gains, _intrinsic_states(action)

    def require_states(states: Any, intrinsic: list[str], *, code: str) -> None:
        if not isinstance(states, list) or any(not isinstance(state, str) for state in states):
            raise _error(code, "Replay required states must be a bounded string list.")
        if available_states is not None:
            if any(state.casefold() not in available_states for state in states) or any(
                state.casefold() not in available_states for state in intrinsic
            ):
                raise _error(code, "Replay requires a state unavailable in the sealed workspace.")

    sequence = controller.get("sequence")
    if not isinstance(sequence, list) or len(sequence) < 2 or len(sequence) > 32:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The replay sequence is invalid.")
    total_cost = 0
    spent = {pool["resource_id"]: 0 for pool in resource_rows}
    for index, step in enumerate(sequence, start=1):
        if not isinstance(step, Mapping) or step.get("step") != index:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The replay sequence numbering is invalid.")
        action_id = step.get("action_id")
        action = packet_for(action_id)
        if not isinstance(step.get("action"), Mapping) or dict(step["action"]) != dict(action):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_ACTION_INVALID", "The replay sequence action packet diverges from linked authority.")
        cost, cost_rows, requirements, gains, intrinsic = action_resources(action)
        if step.get("resource_costs") != cost_rows:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The replay sequence resource rows diverge from linked authority.")
        require_states(step.get("requires_states"), intrinsic, code="COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID")
        for requirement in requirements:
            pool_id = requirement["resource_id"]
            if requirement["minimum"] > balances[pool_id]["current"]:
                raise _error("COMPOSITE_CONTROLLER_OVERLAY_ACTION_PREREQUISITE_UNAVAILABLE", f"The replay action requires unavailable {_resource_name(pool_id)}.")
        for cost_row in cost_rows:
            pool_id = cost_row["resource_id"]
            if cost_row["amount"] > balances[pool_id]["current"]:
                raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_UNAVAILABLE", f"The replay action costs more {_resource_name(pool_id)} than remains.")
        for cost_row in cost_rows:
            pool_id = cost_row["resource_id"]
            balances[pool_id]["current"] -= cost_row["amount"]
            spent[pool_id] += cost_row["amount"]
        for gain_row in gains:
            pool_id = gain_row["resource_id"]
            balances[pool_id]["current"] = min(
                balances[pool_id]["maximum"],
                balances[pool_id]["current"] + gain_row["amount"],
            )
        total_cost += cost
    if any(spent[pool_id] > budget_limits[pool_id] for pool_id in spent):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The replay sequence exceeds a bound resource budget.")
    budget = controller.get("resource_budget")
    if len(resource_rows) == 1:
        if not isinstance(budget, Mapping) or budget.get("total_sequence_cost") != total_cost:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The replay sequence total is not recomputed from its actions.")
    else:
        if not isinstance(budget, Mapping) or not isinstance(budget.get("resource_budgets"), list) or any(
            item.get("total_sequence_cost") != spent[item["resource_id"]]
            for item in budget["resource_budgets"]
            if isinstance(item, Mapping) and item.get("resource_id") in spent
        ):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The replay sequence totals are not recomputed per resource pool.")

    fallback = controller.get("fallback")
    if not isinstance(fallback, Mapping):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The replay fallback is invalid.")
    fallback_action = packet_for(fallback.get("action_id"))
    if not isinstance(fallback.get("action"), Mapping) or dict(fallback["action"]) != dict(fallback_action):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_ACTION_INVALID", "The replay fallback action diverges from linked authority.")
    fallback_cost, fallback_rows, fallback_requirements, _fallback_gains, fallback_intrinsic = action_resources(fallback_action)
    if fallback.get("resource_costs") != fallback_rows or fallback_cost != 0:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The replay fallback is not zero-cost.")
    require_states(fallback.get("requires_states", []), fallback_intrinsic, code="COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID")
    if any(
        requirement["minimum"] > initial_balances[requirement["resource_id"]]["current"]
        for requirement in fallback_requirements
    ):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_FALLBACK_UNAVAILABLE", "The replay fallback requires an unavailable sealed resource.")

    conditional = controller.get("conditional_options")
    if not isinstance(conditional, list):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The replay conditional options are invalid.")
    for option in conditional:
        if not isinstance(option, Mapping):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "A replay conditional option is invalid.")
        option_action = packet_for(option.get("action_id"))
        if not isinstance(option.get("action"), Mapping) or dict(option["action"]) != dict(option_action):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_ACTION_INVALID", "A replay conditional action diverges from linked authority.")
        option_cost, option_rows, option_requirements, _option_gains, option_intrinsic = action_resources(option_action)
        require_states(option.get("requires_states", []), option_intrinsic, code="COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID")
        if any(
            requirement["minimum"] > initial_balances[requirement["resource_id"]]["current"]
            for requirement in option_requirements
        ) or any(
            row["amount"] > initial_balances[row["resource_id"]]["current"]
            for row in option_rows
        ):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_UNAVAILABLE", "A replay conditional action is not affordable in the sealed resource pools.")
        option_spent = {pool_id: 0 for pool_id in balances}
        for row in option_rows:
            option_spent[row["resource_id"]] += row["amount"]
        if any(option_spent[pool_id] > budget_limits[pool_id] for pool_id in option_spent):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "A replay conditional action exceeds a sealed resource budget.")


def _validate_artifact_against_workspace(artifact: Mapping[str, Any], root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise _error("COMPOSITE_CONTROLLER_BASE_INVALID", "The source workspace is not a regular directory.")
    _reject_recursive_symlinks(
        root,
        code="COMPOSITE_CONTROLLER_BASE_INVALID",
        message="The source workspace must contain regular files only.",
    )
    _verify_workspace_checksums(root)
    if _workspace_sha256(root) != artifact.get("source_workspace_sha256"):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_BASE_MISMATCH", "The controller artifact is bound to a different source workspace.")
    expected_resource = _extract_resource_authority(root)
    source_action_rows = _load_actions(root, expected_resource)
    source_actions = {row["action_id"]: row for row in source_action_rows}
    for action in artifact.get("linked_actions", []):
        action_id = action.get("action_id") if isinstance(action, Mapping) else None
        if action_id not in source_actions or _canonicalize_action_resource_rows(_action_packet(action), expected_resource) != source_actions[action_id]:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_ACTION_INVALID", "The controller artifact action is not from the bound workspace.")
    actual_resource = artifact.get("resource_authority")
    if not isinstance(actual_resource, Mapping) or dict(actual_resource) != expected_resource:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_RESOURCE_INVALID", "The controller artifact resource is not from the bound workspace.")
    controller = artifact.get("composite_controller")
    linked_actions = artifact.get("linked_actions")
    if not isinstance(controller, Mapping) or not isinstance(linked_actions, list):
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTROLLER_INVALID", "The controller artifact controller projection is invalid.")
    action_by_id = {
        action["action_id"]: action
        for action in linked_actions
        if isinstance(action, Mapping) and isinstance(action.get("action_id"), str)
    }
    fallback = controller.get("fallback") if isinstance(controller, Mapping) else None
    fallback_id = fallback.get("action_id") if isinstance(fallback, Mapping) else None
    fallback_action = source_actions.get(fallback_id)
    if fallback_action is None:
        raise _error("COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE", "The bound workspace does not contain the fallback action.")
    available_states = {value.casefold() for value in _available_states(root, source_action_rows)}
    if any(state.casefold() not in available_states for state in _intrinsic_states(fallback_action)):
        raise _error("COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE", "The fallback action requires a state that is not present in sealed authority.")
    resource_balances = _resource_balances(expected_resource)
    if any(
        requirement["minimum"] > resource_balances[requirement["resource_id"]]["current"]
        for requirement in _resource_requirements(fallback_action, expected_resource)
    ):
        raise _error("COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE", "The fallback action requires an unavailable sealed resource.")
    fallback_cost, _fallback_rows = _resource_costs(fallback_action, expected_resource)
    if fallback_cost != 0:
        raise _error("COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE", "The fallback must be zero-cost in the sealed resource pools.")
    _replay_controller_legality(controller, action_by_id, expected_resource, available_states)


def _write_workspace_checksums(root: Path) -> None:
    files = _tree_hashes(root)
    build_ledger = root / "Build/SHA256SUMS.txt"
    if build_ledger.is_file() and not build_ledger.is_symlink():
        files = {name: digest for name, digest in files.items() if not name.startswith("Build/")}
    (root / "SHA256SUMS.txt").write_text(
        "\n".join(f"{digest}  {name}" for name, digest in sorted(files.items())) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _overlay_validation_payload(artifact: Mapping[str, Any], artifact_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": "TianxiaFoundry.CompositeControllerValidation.v1",
        "valid": True,
        "execution_authority": True,
        "controller_policy_registered": True,
        "artifact_sha256": artifact_sha256,
        "project_id": artifact["project_id"],
        "projection_id": artifact["projection_id"],
        "base_candidate_sha256": artifact["base_candidate_sha256"],
    }


def _validate_applied_target(base: Path, target: Path, validated: Mapping[str, Any], base_hash: str) -> None:
    if target.is_symlink() or not target.is_dir():
        raise _error("COMPOSITE_CONTROLLER_APPLIED_COLLISION", "The applied controller workspace path is not a regular directory.")
    _reject_recursive_symlinks(
        target,
        code="COMPOSITE_CONTROLLER_APPLIED_CONTENT_INVALID",
        message="The applied controller workspace must contain regular files only.",
    )
    _verify_workspace_checksums(target)
    artifact = validated["artifact"]
    _validate_artifact_against_workspace(artifact, base)
    base_files = _tree_hashes(base, include_checksums=True)
    target_files = _tree_hashes(target, include_checksums=True)
    base_files.pop("SHA256SUMS.txt", None)
    target_files.pop("SHA256SUMS.txt", None)
    generated = {
        "Command_4/Composite_Controller_Artifact.json",
        "Composite_Controller_Overlay_Manifest.json",
        "Validation/Composite_Controller.validation.json",
    }
    if set(target_files) != set(base_files) | generated:
        raise _error("COMPOSITE_CONTROLLER_APPLIED_CONTENT_INVALID", "The applied controller workspace has unexpected or missing contents.")
    for name, digest in base_files.items():
        if target_files.get(name) != digest:
            raise _error("COMPOSITE_CONTROLLER_APPLIED_CONTENT_INVALID", "The applied controller workspace changed its base contents.")
    target_artifact = _load_json(target / "Command_4/Composite_Controller_Artifact.json")
    target_manifest = _load_json(target / "Composite_Controller_Overlay_Manifest.json")
    target_validation = _load_json(target / "Validation/Composite_Controller.validation.json")
    if target_artifact != artifact or target_manifest != validated["manifest"] or target_validation != _overlay_validation_payload(artifact, validated["artifact_sha256"]):
        raise _error("COMPOSITE_CONTROLLER_APPLIED_CONTENT_INVALID", "The applied controller workspace contents are not the validated overlay.")
    if artifact.get("source_workspace_sha256") != base_hash:
        raise _error("COMPOSITE_CONTROLLER_OVERLAY_BASE_MISMATCH", "The applied controller overlay is bound to a different workspace.")


def _normalized_controller(controller: Mapping[str, Any], action_by_token: Mapping[str, Any], available_states: Any) -> dict[str, Any]:
    """Derive what sealed authority already fixes, instead of trusting the model.

    A step's economy is its action's economy, and a required state only
    matters if the character has it.  MiMo mismatched the first (build 12)
    and invented the second (build 5); the local server does not enforce a
    schema tight enough to stop either, so both are derived here.  Unknown
    tokens and every other rule are still checked below.
    """
    normalized = deepcopy(dict(controller))
    states = {str(value).casefold(): value for value in available_states if isinstance(value, str)}
    sequence = normalized.get("sequence")
    for step in sequence if isinstance(sequence, list) else []:
        if not isinstance(step, dict):
            continue
        action = action_by_token.get(str(step.get("action_token")))
        if isinstance(action, Mapping):
            economy = action.get("economy") or _canonical_economy(action.get("action_type") or action.get("bucket"))
            if economy is not None:
                step["economy"] = economy
        if isinstance(step.get("requires_states"), list):
            step["requires_states"] = [states[str(value).casefold()] for value in step["requires_states"] if isinstance(value, str) and str(value).casefold() in states]
    # A step that overfills its economy's slots in a round moves to the next
    # round with room (LFM CPU, build 16), keeping offsets nondecreasing.
    used: dict[tuple[int, str], int] = {}
    previous = 0
    for step in sequence if isinstance(sequence, list) else []:
        if not isinstance(step, dict) or type(step.get("round_offset")) is not int or step.get("economy") not in _ROUND_ECONOMY_CAPACITY:
            continue
        offset = max(step["round_offset"], previous)
        while used.get((offset, step["economy"]), 0) >= _ROUND_ECONOMY_CAPACITY[step["economy"]] and offset < 20:
            offset += 1
        step["round_offset"] = offset
        used[(offset, step["economy"])] = used.get((offset, step["economy"]), 0) + 1
        previous = offset
    return normalized


def build_composite_controller_response_schema(prepared: Mapping[str, Any]) -> dict[str, Any]:
    tokens = prepared.get("action_tokens")
    if not isinstance(tokens, list) or not tokens or any(not isinstance(token, str) or _TOKEN_RE.fullmatch(token) is None for token in tokens):
        raise _error("COMPOSITE_CONTROLLER_TOKEN_INVALID", "The prepared action token set is invalid.")
    resource = prepared.get("resource")
    if not isinstance(resource, Mapping):
        raise _error("COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID", "The prepared active Path resource authority is missing.")
    resource_rows = _resource_rows(resource)
    resource_id = resource_rows[0]["resource_id"] if len(resource_rows) == 1 else None
    resource_maximum = int(resource_rows[0]["maximum"]) if len(resource_rows) == 1 else COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX
    resource_values = [COMPOSITE_CONTROLLER_RESOURCE_ALIAS, resource_id] if resource_id is not None else []
    token_schema = {"type": "string", "enum": list(tokens)}
    sequence_item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["step", "action_token", "round_offset", "economy", "requires_states", "external_preconditions"],
        "properties": {
            "step": {"type": "integer", "minimum": 1, "maximum": 32},
            "action_token": token_schema,
            "round_offset": {"type": "integer", "minimum": 0, "maximum": 20},
            "economy": {"type": "string", "enum": sorted(_ACTION_ECONOMIES)},
            "requires_states": _string_array_schema(8, 160),
            "external_preconditions": _string_array_schema(3, 200),
        },
    }
    conditional_item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["action_token", "when", "priority"],
        "properties": {
            "action_token": token_schema,
            "when": _bounded_string_schema(240),
            "priority": {"type": "integer", "minimum": 0, "maximum": 32},
        },
    }
    controller = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "composite_id", "name", "execution_role", "when_to_use", "do_not_use_when",
            "resource_budget", "temporal_feasibility", "fallback", "dao_hook", "i_ching_hook",
            "sequence", "conditional_options",
        ],
        "properties": {
            "composite_id": {"const": COMPOSITE_CONTROLLER_ID},
            "name": _bounded_string_schema(160),
            "execution_role": {"const": COMPOSITE_CONTROLLER_TARGET},
            "when_to_use": _string_array_schema(4),
            "do_not_use_when": _string_array_schema(4),
            "resource_budget": (
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["resource_id", "max_spend"],
                    "properties": {
                        "resource_id": {"type": "string", "enum": resource_values},
                        "max_spend": {"type": "integer", "minimum": 0, "maximum": resource_maximum},
                    },
                }
                if len(resource_rows) == 1
                else {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["resource_budgets"],
                    "properties": {
                        "resource_budgets": {
                            "type": "array",
                            "minItems": len(resource_rows),
                            "maxItems": len(resource_rows),
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["resource_id", "max_spend"],
                                "properties": {
                                    "resource_id": {
                                        "type": "string",
                                        "enum": [row["resource_id"] for row in resource_rows],
                                    },
                                    "max_spend": {
                                        "type": "integer",
                                        "minimum": 0,
                                        "maximum": COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX,
                                    },
                                },
                            },
                        },
                    },
                }
            ),
            "temporal_feasibility": {
                "type": "object",
                "additionalProperties": False,
                "required": ["same_turn_legal", "round_span", "notes"],
                "properties": {
                    "same_turn_legal": {"type": "boolean"},
                    "round_span": {"type": "integer", "minimum": 0, "maximum": 20},
                    "notes": _string_array_schema(4),
                },
            },
            "fallback": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action_token", "reason"],
                "properties": {"action_token": token_schema, "reason": _bounded_string_schema(240)},
            },
            "dao_hook": _bounded_string_schema(240),
            "i_ching_hook": _bounded_string_schema(240),
            "sequence": {"type": "array", "minItems": 2, "maxItems": 6, "items": sequence_item},
            "conditional_options": {"type": "array", "maxItems": 6, "items": conditional_item},
        },
    }
    theme_ids = prepared.get("theme_record_ids")
    theme_bound = isinstance(theme_ids, list) and bool(theme_ids)
    theme_schema = build_gm_themes_schema(theme_ids) if theme_bound else build_gm_themes_schema()
    # Both themes have the same contract. Reference it once on the wire,
    # including the complete selected-record enum, without relaxing validation.
    theme_definition = deepcopy(theme_schema["properties"]["dao"])
    for kind in ("dao", "i_ching"):
        theme_schema["properties"][kind] = {"$ref": "#/$defs/gm_theme"}
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"gm_theme": theme_definition},
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema", "project_id", "projection_id", "candidate_sha256", "request_sha256",
            "composite_controller",
        ] + (["gm_themes"] if theme_bound else []),
        "properties": {
            "schema": {"const": COMPOSITE_CONTROLLER_SCHEMA},
            "project_id": _bounded_string_schema(160),
            "projection_id": _bounded_string_schema(160),
            "candidate_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
            "request_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
            "composite_controller": controller,
            "gm_themes": theme_schema,
        },
    }
    return schema


def _validated_budget_limits(
    controller: Mapping[str, Any],
    resource: Mapping[str, Any],
) -> dict[str, int]:
    """Resolve the response budget to one limit for every sealed pool."""

    pools = {row["resource_id"]: row for row in _resource_rows(resource)}
    budget = controller.get("resource_budget")
    if not isinstance(budget, Mapping):
        raise _error("COMPOSITE_CONTROLLER_RESOURCE_BUDGET_INVALID", "The provider resource budget is invalid.")
    if len(pools) == 1:
        resource_id, maximum = _resource_context(resource)
        budget_resource = _canonical_resource_id(budget.get("resource_id"), active_resource_id=resource_id)
        max_spend = _integer(budget.get("max_spend"), maximum=maximum)
        if budget_resource != resource_id or max_spend is None:
            raise _error(
                "COMPOSITE_CONTROLLER_RESOURCE_BUDGET_INVALID",
                f"The provider budget must use the sealed {_resource_name(resource_id)} pool.",
            )
        return {resource_id: max_spend}
    rows = budget.get("resource_budgets")
    if not isinstance(rows, list) or len(rows) != len(pools):
        raise _error(
            "COMPOSITE_CONTROLLER_RESOURCE_BUDGET_INVALID",
            "The provider must declare one budget for every sealed resource pool.",
        )
    limits: dict[str, int] = {}
    for item in rows:
        if not isinstance(item, Mapping):
            raise _error("COMPOSITE_CONTROLLER_RESOURCE_BUDGET_INVALID", "A sealed resource budget row is invalid.")
        resource_id = _canonical_path_resource_id(item.get("resource_id"))
        pool = pools.get(resource_id)
        max_spend = _integer(
            item.get("max_spend"),
            maximum=int(pool["maximum"]) if pool is not None else COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX,
        )
        if resource_id is None or pool is None or max_spend is None or resource_id in limits:
            raise _error(
                "COMPOSITE_CONTROLLER_RESOURCE_BUDGET_INVALID",
                "The provider budget must name each sealed concrete resource exactly once.",
            )
        limits[resource_id] = max_spend
    if set(limits) != set(pools):
        raise _error(
            "COMPOSITE_CONTROLLER_RESOURCE_BUDGET_INVALID",
            "The provider budget does not cover the sealed resource pools.",
        )
    return limits


def _canonical_wire_bytes(
    prompt_text: str,
    system_message: str,
    settings: Mapping[str, Any],
    response_schema: Mapping[str, Any],
) -> bytes:
    provider_id = str(settings.get("provider_id") or "local")
    model = str(settings.get("model") or "local-composite-controller")
    configured = settings.get("max_output_tokens")
    max_tokens = configured if type(configured) is int and configured > 0 else COMPOSITE_CONTROLLER_MAX_OUTPUT_TOKENS
    max_tokens = min(max_tokens, 6144, COMPOSITE_CONTROLLER_MAX_OUTPUT_TOKENS)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system_message}, {"role": "user", "content": prompt_text}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_NAME,
                "strict": True,
                "schema": deepcopy(dict(response_schema)),
            },
        },
        "max_tokens": max_tokens,
        "stream": False,
        "temperature": 0,
    }
    if provider_id in _LOCAL_PROVIDER_IDS:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        payload["cache_prompt"] = True
    return canonical_json(payload).encode("utf-8")


def _provider_settings(provider: Any) -> Mapping[str, Any] | None:
    getter = getattr(provider, "_settings", None)
    if not callable(getter):
        return None
    try:
        result = getter()
    except Exception:
        return None
    return result if isinstance(result, Mapping) else None


def _parse_provider_result(provider_result: Any) -> tuple[dict[str, Any], str]:
    if not isinstance(provider_result, Mapping):
        raise _error("COMPOSITE_CONTROLLER_PROVIDER_RESPONSE_INVALID", "The provider result must be an object.")
    raw = provider_result.get("response_text")
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise _error("COMPOSITE_CONTROLLER_PROVIDER_RESPONSE_INVALID", "The provider response is not valid JSON.") from exc
        if isinstance(value, Mapping):
            return deepcopy(dict(value)), raw
        raise _error("COMPOSITE_CONTROLLER_PROVIDER_RESPONSE_INVALID", "The provider response must be one JSON object.")
    value = provider_result.get("value")
    if isinstance(value, Mapping):
        return deepcopy(dict(value)), canonical_json(value)
    raise _error("COMPOSITE_CONTROLLER_PROVIDER_RESPONSE_INVALID", "The provider result has no JSON response object.")


class CompositeControllerAuthoring:
    """Prepare and explicitly invoke one local provider controller proposal."""

    purpose = COMPOSITE_CONTROLLER_PURPOSE
    response_schema = COMPOSITE_CONTROLLER_SCHEMA
    response_schema_name = COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_NAME
    system_message = (
        "You are an untrusted local Tianxia controller-planning adapter. Return exactly one JSON object "
        "matching the supplied schema. Use only the opaque action tokens offered in this request. "
        "Do not return action IDs, source text, mechanics, hashes other than the requested lineage fields, "
        "or new actions. The local server validates every legality rule and never retries this request."
    )

    def __init__(
        self,
        db: Any | None = None,
        *,
        workspace_service: Any | None = None,
        workspace_root: Path | None = None,
        candidate_sha256: str | None = None,
        projection_id: str | None = None,
    ) -> None:
        self.workspace_service = workspace_service
        if self.workspace_service is None and db is not None:
            # Import lazily to avoid a service/__init__ cycle during app boot.
            from factory_authoring.service import FactoryAuthoringWorkspaceService

            self.workspace_service = FactoryAuthoringWorkspaceService(db)
        self._fixed_workspace_root = Path(workspace_root).resolve() if workspace_root is not None else None
        self._fixed_candidate_sha256 = candidate_sha256
        self._fixed_projection_id = projection_id
        self._db = db or getattr(self.workspace_service, "db", None)

    def _resolve(self, project_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
        project_id = _validated_project_id(project_id)
        if self.workspace_service is None and self._fixed_workspace_root is None:
            raise _error("COMPOSITE_CONTROLLER_WORKSPACE_SERVICE_REQUIRED", "A sealed Factory workspace reader is required.")
        root, metadata, manifest = _resolve_workspace_root(self.workspace_service, project_id, self._fixed_workspace_root)
        if self._fixed_candidate_sha256 is not None:
            if not _is_hash(self._fixed_candidate_sha256):
                raise _error("COMPOSITE_CONTROLLER_CANDIDATE_HASH_INVALID", "The supplied candidate hash binding is malformed.")
            if self._fixed_workspace_root is None and metadata.get("candidate_sha256") != self._fixed_candidate_sha256:
                raise _error("COMPOSITE_CONTROLLER_CANDIDATE_HASH_MISMATCH", "The supplied candidate hash does not match the current pointer.")
            metadata["candidate_sha256"] = self._fixed_candidate_sha256
        if self._fixed_projection_id is not None:
            if not isinstance(self._fixed_projection_id, str) or not self._fixed_projection_id.strip():
                raise _error("COMPOSITE_CONTROLLER_PROJECTION_ID_INVALID", "The supplied projection binding is blank.")
            if self._fixed_workspace_root is None and metadata.get("projection_id") not in {None, self._fixed_projection_id}:
                raise _error("COMPOSITE_CONTROLLER_PROJECTION_ID_MISMATCH", "The supplied projection binding does not match the current pointer.")
            metadata["projection_id"] = self._fixed_projection_id
        return root, metadata, manifest

    def prepare(
        self,
        project_id: str,
        *,
        theme_records: list[Mapping[str, Any]] | None = None,
        allow_theme_only: bool = False,
    ) -> dict[str, Any]:
        root, metadata, manifest = self._resolve(project_id)
        resource = _extract_resource_authority(root)
        try:
            actions = _load_actions(root, resource)
        except FoundryError as exc:
            # A character whose sealed actions cannot form a controller (fewer
            # than two executable packets) still gets its Dao and I Ching when
            # the caller opts in; no combat plan is proposed or claimed.
            if not allow_theme_only or exc.code not in {"COMPOSITE_CONTROLLER_ACTIONS_INCOMPLETE", "COMPOSITE_CONTROLLER_RESOURCE_POWERING_PATH_MISSING"}:
                raise
            return self._prepare_theme_only(project_id, root, metadata, manifest, theme_records)
        resource_rows = _resource_rows(resource)
        resource_id = resource_rows[0]["resource_id"] if len(resource_rows) == 1 else None
        resource_maximum = int(resource_rows[0]["maximum"]) if len(resource_rows) == 1 else None
        identity = _extract_identity(root, manifest)
        states = _available_states(root, actions)
        action_tokens: list[str] = []
        token_to_action: dict[str, dict[str, Any]] = {}
        for index, action in enumerate(actions):
            token = "ccopt_" + sha256_json({
                "project_id": project_id,
                "candidate_sha256": metadata["candidate_sha256"],
                "ordinal": index,
                "action_id": action["action_id"],
            })[:24]
            if token in token_to_action:
                raise _error("COMPOSITE_CONTROLLER_TOKEN_COLLISION", "The request-scoped action tokens are not unique.")
            action_tokens.append(token)
            token_to_action[token] = deepcopy(action)

        summaries: list[dict[str, Any]] = []
        for token, action in zip(action_tokens, actions):
            cost, cost_rows = _resource_costs(action, resource)
            summary: dict[str, Any] = {
                "action_token": token,
                "name": action["name"],
                "economy": action["economy"],
                "timing": _first_text(action.get("timing"), limit=120),
                "cost": cost,
                "range": _first_text(action.get("range"), limit=120),
                "target": _first_text(action.get("target"), action.get("area"), limit=120),
                "roll_save_check": _first_text(action.get("roll_save_check"), limit=120),
                "effect": _first_text(action.get("effect"), limit=180),
                "resource_costs": cost_rows,
                "resource_requirements": _resource_requirements(action, resource),
                "required_states": _intrinsic_states(action),
            }
            summaries.append({key: value for key, value in summary.items() if value is not None})
        authoritative_resource = (
            {
                "resource_id": resource_id,
                "alias": COMPOSITE_CONTROLLER_RESOURCE_ALIAS,
                "name": resource_rows[0]["name"],
                "current": resource_rows[0]["current"],
                "maximum": resource_rows[0]["maximum"],
            }
            if len(resource_rows) == 1
            else {
                "resources": [
                    {
                        "resource_id": row["resource_id"],
                        "name": row["name"],
                        "current": row["current"],
                        "maximum": row["maximum"],
                    }
                    for row in resource_rows
                ],
            }
        )
        if len(resource_rows) == 1:
            resource_rule = (
                f"Use {COMPOSITE_CONTROLLER_RESOURCE_ALIAS} only for the generic CP alias; the server binds it to the exact sealed active Path resource "
                f"{resource_rows[0]['name']} ({resource_id}). Charge each sealed action cost from remaining {resource_rows[0]['name']} in sequence order, applying any sealed gain after that step; never exceed remaining {resource_rows[0]['name']} or the declared budget. The budget and total linked cost cannot exceed the sealed maximum {resource_maximum}."
            )
            fallback_rule = (
                f"fallback.action_token must name an offered zero-resource-cost action whose intrinsic states and resource requirements are available at current {resource_rows[0]['name']} {resource_rows[0]['current']}."
            )
        else:
            resource_rule = (
                "Generic CP is unavailable while more than one Path resource pool is sealed unless an upstream producer supplies an authenticated, acquisition-bound Powering Path or required Path record; "
                "this controller rejects unbound action metadata and the provider cannot choose or change a payer. Explicit named resource rows remain bound to their named sealed pool. "
                "Charge each cost, requirement, and gain against that concrete pool in sequence order, with no splitting or conversion. "
                "Declare one resource_budgets entry for every sealed pool and keep each max_spend within that pool's maximum."
            )
            fallback_rule = (
                "fallback.action_token must name an offered zero-resource-cost action whose intrinsic states and resource requirements are available in every referenced sealed pool."
            )
        theme_sources, theme_record_ids = _theme_source_projection(theme_records)
        action_columns = list(dict.fromkeys(key for row in summaries for key in row))
        theme_sections: list[Any] = []
        for source in theme_sources:
            if source.get("section") not in theme_sections:
                theme_sections.append(source.get("section"))
        prompt_payload = {
            "schema": "TianxiaFoundry.CompositeControllerProviderPrompt.v3",
            "target": COMPOSITE_CONTROLLER_TARGET,
            "identity": {
                "name": identity.get("name"),
                "role": identity.get("role"),
                "realm": identity.get("realm"),
                "concept": identity.get("concept"),
            },
            "authoritative_resource": authoritative_resource,
            "available_states": states,
            "actions": {
                "columns": action_columns,
                "rows": [[row.get(key) for key in action_columns] for row in summaries],
            },
            # These are descriptive inputs, not acquisition authority. Keep
            # every ID, section, name and complete summary without repeating
            # JSON keys or acquisition bookkeeping for every selected record.
            "descriptive_theme_sources": {
                "columns": ["record_id", "section_index", "display_name", "one_line_description"],
                "sections": theme_sections,
                "rows": [
                    [source.get("record_id"), theme_sections.index(source.get("section")),
                     source.get("display_name"), source.get("one_line_description")]
                    for source in theme_sources
                ],
            },
            "contract": {
                "response_top_level_keys": [
                    "schema", "project_id", "projection_id", "candidate_sha256", "request_sha256", "composite_controller", "gm_themes",
                ],
                "composite_fields": [
                    "composite_id", "name", "execution_role", "when_to_use", "do_not_use_when", "resource_budget",
                    "temporal_feasibility", "fallback", "dao_hook", "i_ching_hook", "sequence", "conditional_options",
                ],
                "sequence_requirements": "At least two steps, consecutive step numbers, offered action_token only, exact source economy, nondecreasing round offsets, and only available required states.",
                "brevity": "Keep it short: 2-6 steps, at most 3 external preconditions per step, at most 4 lines in when_to_use and do_not_use_when, at most 6 conditional options. Short phrases, not paragraphs.",
                "round_economy_capacity": dict(sorted(_ROUND_ECONOMY_CAPACITY.items())),
                "round_economy_rule": "For each round_offset, use at most one action, one bonus_action, one reaction, one movement, one passive, and one procedure; free may repeat up to four times. A second step using any one-slot economy must use a strictly later round_offset. round_offset 0 is the current round, and offsets must be nondecreasing.",
                "resource_rule": resource_rule,
                "fallback_rule": fallback_rule,
                "execution_boundary": "Linked action packets are server-owned. This request proposes a controller policy only; it cannot alter action mechanics.",
                "theme_boundary": "gm_themes is descriptive only; bind each relevant_record_id to descriptive_theme_sources and leave mechanical_effects empty.",
                "theme_guidance": _THEME_GUIDANCE,
            },
        }
        request_sha256 = sha256_bytes(canonical_json(prompt_payload).encode("utf-8"))
        prompt_payload["response_constants"] = {
            "schema": self.response_schema,
            "project_id": project_id,
            "projection_id": metadata["projection_id"],
            "candidate_sha256": metadata["candidate_sha256"],
            "request_sha256": request_sha256,
            "action_tokens": action_tokens,
        }
        prompt_text = canonical_json(prompt_payload)
        authority = {
            "project_id": project_id,
            "workspace_path": str(root),
            "workspace_sha256": metadata["workspace_sha256"],
            "candidate_sha256": metadata["candidate_sha256"],
            "projection_id": metadata["projection_id"],
            "identity": identity,
            "resource": resource,
            "available_states": states,
            "actions": actions,
            "action_tokens": action_tokens,
            "token_to_action": token_to_action,
            "request_sha256": request_sha256,
            "prompt_text": prompt_text,
            "theme_record_ids": theme_record_ids,
            "theme_sources": theme_sources,
        }
        response_schema = build_composite_controller_response_schema(authority)
        settings = {
            "provider_id": "local",
            "model": "local-composite-controller",
            "max_output_tokens": COMPOSITE_CONTROLLER_MAX_OUTPUT_TOKENS,
        }
        request_bytes = _canonical_wire_bytes(prompt_text, self.system_message, settings, response_schema)
        authority.update({
            "system_message": self.system_message,
            "response_schema": response_schema,
            "response_schema_name": self.response_schema_name,
            "request_bytes": len(request_bytes),
            "wire_request_sha256": sha256_bytes(request_bytes),
            "max_request_bytes": COMPOSITE_CONTROLLER_MAX_REQUEST_BYTES,
            "action_summaries": summaries,
        })
        if len(request_bytes) > COMPOSITE_CONTROLLER_MAX_REQUEST_BYTES:
            raise _error(
                "COMPOSITE_CONTROLLER_REQUEST_TOO_LARGE",
                "The bounded composite-controller request exceeds its exact wire byte cap.",
                details={"request_bytes": len(request_bytes), "max_request_bytes": COMPOSITE_CONTROLLER_MAX_REQUEST_BYTES},
                status_code=413,
            )
        return authority

    def _prepare_theme_only(self, project_id: str, root: Path, metadata: Mapping[str, Any], manifest: Mapping[str, Any], theme_records: Any) -> dict[str, Any]:
        identity = _extract_identity(root, manifest)
        theme_sources, theme_record_ids = _theme_source_projection(theme_records)
        if not theme_record_ids:
            raise _error("COMPOSITE_CONTROLLER_ACTIONS_INCOMPLETE", "At least two executable Actions are required for a composite controller.")
        theme_sections: list[Any] = []
        for source in theme_sources:
            if source.get("section") not in theme_sections:
                theme_sections.append(source.get("section"))
        prompt_payload = {
            "schema": "TianxiaFoundry.CompositeControllerThemeOnlyPrompt.v1",
            "target": COMPOSITE_CONTROLLER_TARGET,
            "identity": {key: identity.get(key) for key in ("name", "role", "realm", "concept")},
            "descriptive_theme_sources": {
                "columns": ["record_id", "section_index", "display_name", "one_line_description"],
                "sections": theme_sections,
                "rows": [
                    [source.get("record_id"), theme_sections.index(source.get("section")),
                     source.get("display_name"), source.get("one_line_description")]
                    for source in theme_sources
                ],
            },
            "contract": {
                "response_top_level_keys": ["schema", "project_id", "projection_id", "candidate_sha256", "request_sha256", "gm_themes"],
                "note": "This character's sealed actions cannot form a validated combat plan yet; write only the descriptive Dao and I Ching.",
                "theme_boundary": "gm_themes is descriptive only; bind each relevant_record_id to descriptive_theme_sources and leave mechanical_effects empty.",
                "theme_guidance": _THEME_GUIDANCE,
            },
        }
        request_sha256 = sha256_bytes(canonical_json(prompt_payload).encode("utf-8"))
        prompt_payload["response_constants"] = {
            "schema": self.response_schema,
            "project_id": project_id,
            "projection_id": metadata["projection_id"],
            "candidate_sha256": metadata["candidate_sha256"],
            "request_sha256": request_sha256,
        }
        prompt_text = canonical_json(prompt_payload)
        response_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema", "project_id", "projection_id", "candidate_sha256", "request_sha256", "gm_themes"],
            "properties": {
                "schema": {"const": self.response_schema},
                "project_id": {"const": project_id},
                "projection_id": {"const": metadata["projection_id"]},
                "candidate_sha256": {"const": metadata["candidate_sha256"]},
                "request_sha256": {"const": request_sha256},
                "gm_themes": build_gm_themes_schema(theme_record_ids),
            },
        }
        settings = {"provider_id": "local", "model": "local-composite-controller", "max_output_tokens": COMPOSITE_CONTROLLER_MAX_OUTPUT_TOKENS}
        request_bytes = _canonical_wire_bytes(prompt_text, self.system_message, settings, response_schema)
        if len(request_bytes) > COMPOSITE_CONTROLLER_MAX_REQUEST_BYTES:
            raise _error(
                "COMPOSITE_CONTROLLER_REQUEST_TOO_LARGE",
                "The bounded composite-controller request exceeds its exact wire byte cap.",
                details={"request_bytes": len(request_bytes), "max_request_bytes": COMPOSITE_CONTROLLER_MAX_REQUEST_BYTES},
                status_code=413,
            )
        return {
            "theme_only": True,
            "project_id": project_id,
            "workspace_path": str(root),
            "workspace_sha256": metadata["workspace_sha256"],
            "candidate_sha256": metadata["candidate_sha256"],
            "projection_id": metadata["projection_id"],
            "identity": identity,
            "resource": None,
            "available_states": [],
            "actions": [],
            "action_tokens": [],
            "token_to_action": {},
            "request_sha256": request_sha256,
            "prompt_text": prompt_text,
            "theme_record_ids": theme_record_ids,
            "theme_sources": theme_sources,
            "system_message": self.system_message,
            "response_schema": response_schema,
            "response_schema_name": self.response_schema_name,
            "request_bytes": len(request_bytes),
            "wire_request_sha256": sha256_bytes(request_bytes),
            "max_request_bytes": COMPOSITE_CONTROLLER_MAX_REQUEST_BYTES,
            "action_summaries": [],
        }

    @staticmethod
    def _validate_dynamic_schema(prepared: Mapping[str, Any], response: Mapping[str, Any]) -> None:
        schema = prepared.get("response_schema")
        if not isinstance(schema, Mapping):
            raise _error("COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_MISSING", "The prepared response schema is missing.")
        try:
            Draft202012Validator(dict(schema)).validate(response)
        except ValidationError as exc:
            raise _error(
                "COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_INVALID",
                "The provider response failed the sealed composite-controller response schema.",
                details={"validator": exc.validator if isinstance(exc.validator, str) else None},
            ) from None

    @staticmethod
    def _validate_response(prepared: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(response, Mapping):
            raise _error("COMPOSITE_CONTROLLER_RESPONSE_INVALID", "The provider response must be one object.")
        CompositeControllerAuthoring._validate_dynamic_schema(prepared, response)
        expected = {
            "schema": COMPOSITE_CONTROLLER_SCHEMA,
            "project_id": prepared.get("project_id"),
            "projection_id": prepared.get("projection_id"),
            "candidate_sha256": prepared.get("candidate_sha256"),
            "request_sha256": prepared.get("request_sha256"),
        }
        for key, value in expected.items():
            if response.get(key) != value:
                raise _error("COMPOSITE_CONTROLLER_LINEAGE_MISMATCH", f"The provider response field {key} is not bound to this request.")
        theme_ids = prepared.get("theme_record_ids")
        if isinstance(theme_ids, list) and theme_ids and "gm_themes" not in response:
            raise _error(
                "GM_AUTHORING_THEME_REQUIRED",
                "A theme-bound composite request must return its source-bound descriptive themes.",
            )
        if "gm_themes" in response:
            try:
                validate_gm_themes(
                    response["gm_themes"],
                    prepared.get("theme_record_ids") or [
                        action.get("record_id")
                        for action in (prepared.get("token_to_action") or {}).values()
                        if isinstance(action, Mapping) and isinstance(action.get("record_id"), str)
                    ],
                )
            except FoundryError as exc:
                raise _error(exc.code, exc.message, details=exc.details) from exc
        if prepared.get("theme_only") is True:
            # Themes only: lineage and the source-bound themes were checked above.
            return {key: deepcopy(response[key]) for key in ("schema", "project_id", "projection_id", "candidate_sha256", "request_sha256", "gm_themes")}
        controller = response.get("composite_controller")
        if not isinstance(controller, Mapping):
            raise _error("COMPOSITE_CONTROLLER_RESPONSE_INVALID", "The provider did not return a controller object.")
        tokens = prepared.get("action_tokens")
        token_to_action = prepared.get("token_to_action")
        if not isinstance(tokens, list) or not isinstance(token_to_action, Mapping):
            raise _error("COMPOSITE_CONTROLLER_PREPARED_AUTHORITY_INVALID", "The prepared token authority is invalid.")
        action_by_token = {str(token): token_to_action[token] for token in tokens if token in token_to_action}
        if len(action_by_token) != len(tokens):
            raise _error("COMPOSITE_CONTROLLER_PREPARED_AUTHORITY_INVALID", "The prepared token authority is incomplete.")
        controller = _normalized_controller(controller, action_by_token, prepared.get("available_states") or [])
        costs: dict[str, int] = {}
        cost_rows: dict[str, list[dict[str, Any]]] = {}
        requirements: dict[str, list[dict[str, Any]]] = {}
        gain_rows: dict[str, list[dict[str, Any]]] = {}
        intrinsic_states: dict[str, list[str]] = {}
        resource = prepared.get("resource")
        if not isinstance(resource, Mapping):
            raise _error("COMPOSITE_CONTROLLER_RESOURCE_AUTHORITY_INVALID", "The prepared active Path resource authority is missing.")
        resource_rows = _resource_rows(resource)
        for token, action in action_by_token.items():
            costs[token], cost_rows[token] = _resource_costs(action, resource)
            requirements[token] = _resource_requirements(action, resource)
            gain_rows[token] = _resource_gain_rows(action, resource)
            intrinsic_states[token] = _intrinsic_states(action)
        balances = _resource_balances(resource)
        initial_balances = deepcopy(balances)
        budget_limits = _validated_budget_limits(controller, resource)
        available_states = {str(value).casefold() for value in (prepared.get("available_states") or []) if isinstance(value, str)}


        sequence = controller.get("sequence")
        if not isinstance(sequence, list) or len(sequence) < 2:
            raise _error("COMPOSITE_CONTROLLER_SEQUENCE_INVALID", "A composite controller needs at least two sequence steps.")
        fallback = controller.get("fallback")
        fallback_token = fallback.get("action_token") if isinstance(fallback, Mapping) else None
        if fallback_token not in action_by_token:
            raise _error("COMPOSITE_CONTROLLER_FALLBACK_INVALID", "The fallback must reference one offered action token.")
        if any(state.casefold() not in available_states for state in intrinsic_states[str(fallback_token)]):
            raise _error(
                "COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE",
                "The fallback action requires a state that is not present in sealed authority.",
            )
        if any(
            requirement["minimum"] > initial_balances[requirement["resource_id"]]["current"]
            for requirement in requirements[str(fallback_token)]
        ):
            raise _error("COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE", "The fallback action requires an unavailable sealed resource.")
        if costs[fallback_token] != 0 or any(
            cost_row["amount"] > initial_balances[cost_row["resource_id"]]["current"]
            for cost_row in cost_rows[str(fallback_token)]
        ):
            raise _error("COMPOSITE_CONTROLLER_FALLBACK_UNAVAILABLE", "The fallback must be zero-cost and affordable in the sealed resource pools.")
        total_cost = 0
        spent = {pool["resource_id"]: 0 for pool in resource_rows}
        previous_offset = -1
        round_economies: dict[tuple[int, str], int] = {}
        for index, step in enumerate(sequence, start=1):
            if not isinstance(step, Mapping):
                raise _error("COMPOSITE_CONTROLLER_SEQUENCE_INVALID", "A composite sequence step is not an object.")
            if step.get("step") != index:
                raise _error("COMPOSITE_CONTROLLER_SEQUENCE_NUMBER_INVALID", "Composite sequence steps must be consecutive and start at one.")
            token = step.get("action_token")
            if token not in action_by_token:
                raise _error("COMPOSITE_CONTROLLER_ACTION_TOKEN_INVALID", "The composite sequence contains an unknown or raw action reference.")
            economy = _canonical_economy(step.get("economy"))
            action_economy = action_by_token[token].get("economy") or _canonical_economy(action_by_token[token].get("action_type") or action_by_token[token].get("bucket"))
            if economy != action_economy:
                raise _error("COMPOSITE_CONTROLLER_ECONOMY_MISMATCH", "The provider economy does not match the sealed action economy.")
            offset = _integer(step.get("round_offset"), maximum=20)
            if offset is None or offset < previous_offset:
                raise _error("COMPOSITE_CONTROLLER_TEMPORAL_INVALID", "Composite round offsets must be bounded and nondecreasing.")
            previous_offset = offset
            round_key = (offset, economy)
            round_economies[round_key] = round_economies.get(round_key, 0) + 1
            if round_economies[round_key] > _ROUND_ECONOMY_CAPACITY[economy]:
                raise _error(
                    "COMPOSITE_CONTROLLER_ECONOMY_CAPACITY_EXCEEDED",
                    "The composite schedules too many actions from one economy in the same round.",
                )
            required_states = step.get("requires_states")
            if not isinstance(required_states, list):
                raise _error("COMPOSITE_CONTROLLER_STATES_INVALID", "Composite required states must be a bounded list.")
            if any(not isinstance(state, str) or state.casefold() not in available_states for state in required_states):
                raise _error("COMPOSITE_CONTROLLER_STATE_UNAVAILABLE", "The composite requires a state that is not present in sealed authority.")
            if any(state.casefold() not in available_states for state in intrinsic_states[token]):
                raise _error(
                    "COMPOSITE_CONTROLLER_ACTION_PREREQUISITE_UNAVAILABLE",
                    "A linked action requires a state that is not present in sealed authority.",
                )
            for requirement in requirements[token]:
                pool_id = requirement["resource_id"]
                if requirement["minimum"] > balances[pool_id]["current"]:
                    raise _error(
                        "COMPOSITE_CONTROLLER_ACTION_PREREQUISITE_UNAVAILABLE",
                        f"A linked action requires more {_resource_name(pool_id)} than remains available.",
                    )
            for cost_row in cost_rows[token]:
                pool_id = cost_row["resource_id"]
                if cost_row["amount"] > balances[pool_id]["current"]:
                    raise _error(
                        "COMPOSITE_CONTROLLER_RESOURCE_UNAVAILABLE",
                        f"A linked action costs more {_resource_name(pool_id)} than remains available.",
                    )
            for cost_row in cost_rows[token]:
                pool_id = cost_row["resource_id"]
                balances[pool_id]["current"] -= cost_row["amount"]
                spent[pool_id] += cost_row["amount"]
            for gain_row in gain_rows[token]:
                pool_id = gain_row["resource_id"]
                balances[pool_id]["current"] = min(
                    balances[pool_id]["maximum"],
                    balances[pool_id]["current"] + gain_row["amount"],
                )
            total_cost += costs[token]
        if any(spent[pool_id] > budget_limits[pool_id] for pool_id in spent):
            raise _error("COMPOSITE_CONTROLLER_RESOURCE_BUDGET_EXCEEDED", "The sequence resource cost exceeds a sealed pool budget.")

        conditional = controller.get("conditional_options")
        if not isinstance(conditional, list):
            raise _error("COMPOSITE_CONTROLLER_CONDITIONAL_OPTIONS_INVALID", "Conditional options must be a bounded list.")
        for option in conditional:
            if not isinstance(option, Mapping) or option.get("action_token") not in action_by_token:
                raise _error("COMPOSITE_CONTROLLER_ACTION_TOKEN_INVALID", "A conditional option contains an unknown or raw action reference.")
            option_token = str(option["action_token"])
            if any(state.casefold() not in available_states for state in intrinsic_states[option_token]):
                raise _error("COMPOSITE_CONTROLLER_ACTION_PREREQUISITE_UNAVAILABLE", "A conditional action requires an unavailable state.")
            if any(
                requirement["minimum"] > initial_balances[requirement["resource_id"]]["current"]
                for requirement in requirements[option_token]
            ) or any(
                cost_row["amount"] > initial_balances[cost_row["resource_id"]]["current"]
                for cost_row in cost_rows[option_token]
            ):
                raise _error("COMPOSITE_CONTROLLER_RESOURCE_UNAVAILABLE", "A conditional action is not affordable in the sealed resource pools.")
            option_spent = {pool_id: 0 for pool_id in balances}
            for cost_row in cost_rows[option_token]:
                option_spent[cost_row["resource_id"]] += cost_row["amount"]
            if any(option_spent[pool_id] > budget_limits[pool_id] for pool_id in option_spent):
                raise _error("COMPOSITE_CONTROLLER_RESOURCE_BUDGET_EXCEEDED", "A conditional action exceeds a sealed resource budget.")

        validated = deepcopy(dict(response))
        controller_value = deepcopy(dict(controller))
        linked_tokens: set[str] = {str(step["action_token"]) for step in sequence}
        linked_tokens.add(str(fallback_token))
        linked_tokens.update(str(option["action_token"]) for option in conditional)
        linked_actions = {
            token: _canonicalize_action_resource_rows(_action_packet(action_by_token[token]), resource)
            for token in sorted(linked_tokens)
        }
        server_sequence: list[dict[str, Any]] = []
        for step in sequence:
            token = str(step["action_token"])
            server_step = deepcopy(dict(step))
            server_step.update({
                "action_id": linked_actions[token]["action_id"],
                "record_id": linked_actions[token]["record_id"],
                "action": deepcopy(linked_actions[token]),
                "resource_costs": deepcopy(cost_rows[token]),
            })
            server_sequence.append(server_step)
        server_fallback = deepcopy(dict(fallback))
        server_fallback.update({
            "action_id": linked_actions[str(fallback_token)]["action_id"],
            "record_id": linked_actions[str(fallback_token)]["record_id"],
            "action": deepcopy(linked_actions[str(fallback_token)]),
            "resource_costs": deepcopy(cost_rows[str(fallback_token)]),
        })
        server_conditional: list[dict[str, Any]] = []
        for option in conditional:
            token = str(option["action_token"])
            server_option = deepcopy(dict(option))
            server_option.update({
                "action_id": linked_actions[token]["action_id"],
                "record_id": linked_actions[token]["record_id"],
                "action": deepcopy(linked_actions[token]),
            })
            server_conditional.append(server_option)
        if len(resource_rows) == 1:
            pool_id = resource_rows[0]["resource_id"]
            controller_value["resource_budget"] = {
                "resource_id": pool_id,
                "alias": COMPOSITE_CONTROLLER_RESOURCE_ALIAS,
                "max_spend": budget_limits[pool_id],
                "total_sequence_cost": total_cost,
            }
        else:
            controller_value["resource_budget"] = {
                "resource_budgets": [
                    {
                        "resource_id": pool_id,
                        "max_spend": budget_limits[pool_id],
                        "total_sequence_cost": spent[pool_id],
                    }
                    for pool_id in sorted(budget_limits)
                ],
            }
        controller_value["sequence"] = server_sequence
        controller_value["fallback"] = server_fallback
        controller_value["conditional_options"] = server_conditional
        controller_value["linked_actions"] = [linked_actions[token] for token in sorted(linked_actions)]
        validated["composite_controller"] = controller_value
        return validated

    def _artifact(
        self,
        prepared: Mapping[str, Any],
        validated: Mapping[str, Any],
        *,
        response_sha256: str | None,
        resolution_mode: str = COMPOSITE_CONTROLLER_RESOLUTION_LOCAL,
        selector_id: str | None = None,
        provider_call_count: int = 1,
    ) -> dict[str, Any]:
        if resolution_mode not in {COMPOSITE_CONTROLLER_RESOLUTION_LOCAL, COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED}:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The controller resolution mode is unsupported.")
        if resolution_mode == COMPOSITE_CONTROLLER_RESOLUTION_LOCAL:
            if selector_id is not None or provider_call_count != 1:
                raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The local-provider provenance is invalid.")
        elif not _is_selector_id(selector_id) or provider_call_count != 0:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The delegated-response provenance is invalid.")
        if not _is_hash(response_sha256):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The response hash is required for a sealed controller artifact.")
        controller = deepcopy(dict(validated["composite_controller"]))
        resource = deepcopy(dict(prepared["resource"]))
        provenance = {
            "provider_target": COMPOSITE_CONTROLLER_TARGET,
            "request_sha256": prepared["request_sha256"],
            "provider_request_sha256": prepared["wire_request_sha256"],
            "response_sha256": response_sha256,
            "provider_retry_count": 0,
            "resolution_mode": resolution_mode,
            "provider_call_count": provider_call_count,
        }
        if resolution_mode == COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED:
            provenance["selector_id"] = selector_id
        artifact = {
            "schema_version": COMPOSITE_CONTROLLER_ARTIFACT_SCHEMA,
            "project_id": prepared["project_id"],
            "projection_id": prepared["projection_id"],
            "base_candidate_sha256": prepared["candidate_sha256"],
            "source_workspace_sha256": prepared["workspace_sha256"],
            "execution_authority": True,
            "controller_policy_registered": True,
            "resource_authority": resource,
            "composite_controller": controller,
            "linked_actions": deepcopy(controller.get("linked_actions") or []),
            "provenance": provenance,
        }
        return artifact

    @staticmethod
    def _safe_provider_receipt(provider_result: Any, *, response_text: str | None) -> dict[str, Any]:
        result = provider_result if isinstance(provider_result, Mapping) else {}
        provider_id = _safe_text(result.get("provider_id"), limit=80)
        model = _safe_identifier(result.get("model"), limit=120)
        usage_source = result.get("usage") if isinstance(result.get("usage"), Mapping) else {}
        usage = {
            key: usage_source.get(key)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if _integer(usage_source.get(key), maximum=1_000_000_000) is not None
        }
        performance_source = result.get("performance") if isinstance(result.get("performance"), Mapping) else {}
        performance = {
            key: performance_source.get(key)
            for key in ("duration_ms", "duration_seconds", "completion_tokens_per_second")
            if isinstance(performance_source.get(key), (int, float)) and not isinstance(performance_source.get(key), bool)
        }
        timings_source = result.get("timings") if isinstance(result.get("timings"), Mapping) else {}
        timings: dict[str, Any] = {}
        for bucket in ("phases_ms", "provider_reported"):
            value = timings_source.get(bucket)
            if isinstance(value, Mapping):
                timings[bucket] = {
                    str(key): item
                    for key, item in value.items()
                    if isinstance(key, str) and isinstance(item, (int, float)) and not isinstance(item, bool) and 0 <= item <= 1_000_000_000_000
                }
        fallback_response_sha = sha256_bytes((response_text or "").encode("utf-8")) if response_text is not None else None
        response_sha = result.get("response_sha256") if _is_hash(result.get("response_sha256")) else fallback_response_sha
        completion_sha = result.get("completion_sha256") if _is_hash(result.get("completion_sha256")) else (
            sha256_bytes(response_text.encode("utf-8")) if isinstance(response_text, str) else None
        )
        return {
            "provider_id": provider_id if provider_id in _AGENT_AUTHORING_PROVIDER_IDS else "local",
            "model": model,
            "response_sha256": response_sha,
            "completion_sha256": completion_sha,
            "usage": usage,
            "performance": performance,
            "timings": timings,
        }

    @staticmethod
    def _append_evidence(
        output_root: Path,
        prepared: Mapping[str, Any],
        *,
        provider_result: Any = None,
        response_text: str | None = None,
        valid: bool,
        error: FoundryError | None = None,
        resolution_mode: str = COMPOSITE_CONTROLLER_RESOLUTION_LOCAL,
        selector_id: str | None = None,
        provider_call_count: int = 1,
    ) -> Path:
        root = _validated_output_root(output_root)
        try:
            return CompositeControllerAuthoring._append_evidence_unchecked(
                root,
                prepared,
                provider_result=provider_result,
                response_text=response_text,
                valid=valid,
                error=error,
                resolution_mode=resolution_mode,
                selector_id=selector_id,
                provider_call_count=provider_call_count,
            )
        except FoundryError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError) as exc:
            raise _error(
                "COMPOSITE_CONTROLLER_EVIDENCE_WRITE_FAILED",
                "The composite-controller evidence could not be written.",
                details={"exception_type": type(exc).__name__},
                status_code=500,
            ) from exc

    @staticmethod
    def _append_evidence_unchecked(
        output_root: Path,
        prepared: Mapping[str, Any],
        *,
        provider_result: Any = None,
        response_text: str | None = None,
        valid: bool,
        error: FoundryError | None = None,
        resolution_mode: str = COMPOSITE_CONTROLLER_RESOLUTION_LOCAL,
        selector_id: str | None = None,
        provider_call_count: int = 1,
    ) -> Path:
        if resolution_mode == COMPOSITE_CONTROLLER_RESOLUTION_LOCAL:
            if selector_id is not None or provider_call_count != 1:
                raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The local-provider evidence provenance is invalid.")
        elif (
            resolution_mode != COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED
            or not _is_selector_id(selector_id)
            or provider_call_count != 0
        ):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_PROVENANCE_INVALID", "The delegated-response evidence provenance is invalid.")
        output_root.mkdir(parents=True, exist_ok=True)
        if output_root.is_symlink() or not output_root.is_dir():
            raise _error(
                "COMPOSITE_CONTROLLER_EVIDENCE_PATH_INVALID",
                "The composite-controller evidence root is not a regular directory.",
            )
        evidence_root = output_root / "composite_controller_evidence"
        if evidence_root.is_symlink() or (evidence_root.exists() and not evidence_root.is_dir()):
            raise _error(
                "COMPOSITE_CONTROLLER_EVIDENCE_PATH_INVALID",
                "The composite-controller evidence path is not a regular directory.",
            )
        evidence_root.mkdir(parents=True, exist_ok=True)
        if evidence_root.is_symlink() or not evidence_root.is_dir():
            raise _error(
                "COMPOSITE_CONTROLLER_EVIDENCE_PATH_INVALID",
                "The composite-controller evidence path is not a regular directory.",
            )
        request_hash = str(prepared.get("wire_request_sha256") or prepared.get("request_sha256"))
        attempt_dir: Path | None = None
        for attempt in range(1, 10_000):
            candidate = evidence_root / f"{request_hash}-attempt-{attempt:03d}"
            if candidate.is_symlink():
                raise _error(
                    "COMPOSITE_CONTROLLER_EVIDENCE_PATH_INVALID",
                    "The composite-controller evidence attempt path is symlinked.",
                )
            try:
                candidate.mkdir()
            except FileExistsError:
                if candidate.is_symlink() or not candidate.is_dir():
                    raise _error(
                        "COMPOSITE_CONTROLLER_EVIDENCE_PATH_INVALID",
                        "The composite-controller evidence attempt path is not a regular directory.",
                    )
                continue
            attempt_dir = candidate
            break
        if attempt_dir is None:  # pragma: no cover - exhaustion is defensive
            raise _error("COMPOSITE_CONTROLLER_EVIDENCE_UNAVAILABLE", "No append-only evidence slot is available.")
        request_payload = {
            "request_sha256": prepared.get("request_sha256"),
            "provider_request_sha256": prepared.get("wire_request_sha256"),
            "request_bytes": prepared.get("request_bytes"),
            "candidate_sha256": prepared.get("candidate_sha256"),
            "projection_id": prepared.get("projection_id"),
            "target": COMPOSITE_CONTROLLER_TARGET,
            "retry_count": 0,
            "resolution_mode": resolution_mode,
            "selector_id": selector_id,
            "provider_call_count": provider_call_count,
        }
        (attempt_dir / "request.json").write_text(canonical_json(request_payload), encoding="utf-8", newline="\n")
        prompt_text = prepared.get("prompt_text")
        if isinstance(prompt_text, str):
            (attempt_dir / "request_prompt.json").write_text(prompt_text, encoding="utf-8", newline="\n")
        request_wire = prepared.get("_request_wire_bytes")
        if isinstance(request_wire, bytes):
            (attempt_dir / "request_wire.json").write_bytes(request_wire)
        safe = CompositeControllerAuthoring._safe_provider_receipt(provider_result, response_text=response_text)
        if resolution_mode == COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED:
            safe = {
                **safe,
                "provider_id": "delegated_response",
                "model": None,
                "completion_sha256": None,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        response_payload = {
            "response_sha256": safe.get("response_sha256"),
            "completion_sha256": safe.get("completion_sha256"),
            "response_bytes": len(response_text.encode("utf-8")) if isinstance(response_text, str) else None,
            "resolution_mode": resolution_mode,
            "selector_id": selector_id,
            "provider_call_count": provider_call_count,
        }
        (attempt_dir / "response_summary.json").write_text(canonical_json(response_payload), encoding="utf-8", newline="\n")
        receipt = {
            **request_payload,
            "provider_id": safe.get("provider_id"),
            "model": safe.get("model"),
            "usage": safe.get("usage"),
            "performance": safe.get("performance"),
            "timings": safe.get("timings"),
            "response_sha256": safe.get("response_sha256"),
            "completion_sha256": safe.get("completion_sha256"),
            "resolution_mode": resolution_mode,
            "selector_id": selector_id,
            "provider_call_count": provider_call_count,
            "validation_verdict": "PASS" if valid else "FAIL",
            "error_code": error.code if isinstance(error, FoundryError) else None,
        }
        (attempt_dir / "receipt.json").write_text(canonical_json(receipt), encoding="utf-8", newline="\n")
        (attempt_dir / "validation.json").write_text(
            canonical_json({
                "valid": valid,
                "error_code": error.code if isinstance(error, FoundryError) else None,
                "resolution_mode": resolution_mode,
                "selector_id": selector_id,
                "provider_call_count": provider_call_count,
            }),
            encoding="utf-8",
            newline="\n",
        )
        return attempt_dir

    def _record_failure_evidence(
        self,
        output_root: Any,
        prepared: Mapping[str, Any],
        *,
        primary: FoundryError,
        **kwargs: Any,
    ) -> Path:
        """Record failure evidence without replacing the primary failure."""

        try:
            return self._append_evidence(output_root, prepared, **kwargs)
        except Exception as evidence_error:
            evidence_code = evidence_error.code if isinstance(evidence_error, FoundryError) else "COMPOSITE_CONTROLLER_EVIDENCE_WRITE_FAILED"
            primary.details = {
                "cause": primary.details,
                "evidence_error": {
                    "code": evidence_code,
                    "exception_type": type(evidence_error).__name__,
                },
            }
            raise primary from evidence_error

    def _write_overlay(
        self,
        output_root: Path,
        artifact: Mapping[str, Any],
        *,
        source_workspace: Path | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        root = _validated_output_root(output_root)
        try:
            return self._write_overlay_unchecked(root, artifact, source_workspace=source_workspace)
        except FoundryError:
            raise
        except (OSError, TypeError, ValueError, UnicodeError) as exc:
            raise _error(
                "COMPOSITE_CONTROLLER_OVERLAY_WRITE_FAILED",
                "The composite-controller overlay could not be written.",
                details={"exception_type": type(exc).__name__},
                status_code=500,
            ) from exc

    def _write_overlay_unchecked(
        self,
        output_root: Path,
        artifact: Mapping[str, Any],
        *,
        source_workspace: Path | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        artifact_sha = sha256_json(artifact)
        overlay_id = sha256_json({
            "source_workspace_sha256": artifact["source_workspace_sha256"],
            "base_candidate_sha256": artifact["base_candidate_sha256"],
            "artifact_sha256": artifact_sha,
        })
        overlay_parent = output_root / "composite_controller_overlays"
        if overlay_parent.is_symlink() or (overlay_parent.exists() and not overlay_parent.is_dir()):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_COLLISION", "The controller overlay parent is not a directory.")
        overlay_parent.mkdir(parents=True, exist_ok=True)
        if overlay_parent.is_symlink() or not overlay_parent.is_dir():
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_COLLISION", "The controller overlay parent is not a directory.")
        overlay = overlay_parent / overlay_id
        if overlay.is_symlink() or (overlay.exists() and not overlay.is_dir()):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_COLLISION", "The controller overlay path is not a directory.")
        if overlay.exists():
            self.validate_overlay(
                overlay,
                project_id=artifact["project_id"],
                candidate_sha256=artifact["base_candidate_sha256"],
                projection_id=artifact["projection_id"],
                source_workspace=source_workspace,
            )
            return overlay, {"overlay_id": overlay_id, "artifact_sha256": artifact_sha}
        staging = overlay.with_name(overlay.name + ".staging")
        if staging.is_symlink() or staging.exists():
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_STAGING_EXISTS", "A controller overlay staging path already exists.")
        staging.mkdir()
        try:
            command4 = staging / "Command_4"
            validation_root = staging / "Validation"
            command4.mkdir()
            validation_root.mkdir()
            _write_json(command4 / "Composite_Controller_Artifact.json", artifact)
            manifest = {
                "schema_version": COMPOSITE_CONTROLLER_OVERLAY_SCHEMA,
                "overlay_id": overlay_id,
                "artifact_sha256": artifact_sha,
                "source_workspace_sha256": artifact["source_workspace_sha256"],
                "base_candidate_sha256": artifact["base_candidate_sha256"],
                "project_id": artifact["project_id"],
                "projection_id": artifact["projection_id"],
                "scope": "Command 4 composite_controller policy overlay; no Command 5/6 claim",
            }
            _write_json(staging / "Composite_Controller_Overlay_Manifest.json", manifest)
            _write_json(validation_root / "Composite_Controller.validation.json", _overlay_validation_payload(artifact, artifact_sha))
            files = _tree_hashes(staging)
            (staging / "SHA256SUMS.txt").write_text(
                "\n".join(f"{digest}  {name}" for name, digest in sorted(files.items())) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            staging.replace(overlay)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self.validate_overlay(
            overlay,
            project_id=artifact["project_id"],
            candidate_sha256=artifact["base_candidate_sha256"],
            projection_id=artifact["projection_id"],
            source_workspace=source_workspace,
        )
        return overlay, {"overlay_id": overlay_id, "artifact_sha256": artifact_sha}

    def author(self, project_id: str, provider: Any, output_root: Path | None = None) -> dict[str, Any]:
        """Make exactly one explicit local-provider call and seal a detached overlay."""

        prepared = self.prepare(project_id)
        settings = _provider_settings(provider)
        if settings is None or settings.get("provider_id") not in _AGENT_AUTHORING_PROVIDER_IDS:
            raise _error("COMPOSITE_CONTROLLER_LOCAL_PROVIDER_REQUIRED", "Composite controller authoring requires a selected local provider or the Agent bridge.")
        request_wire = _canonical_wire_bytes(
            str(prepared["prompt_text"]),
            str(prepared["system_message"]),
            settings,
            prepared["response_schema"],
        )
        actual_wire_sha = sha256_bytes(request_wire)
        # ``prepare`` is provider-free, so its wire hash uses a deterministic
        # local default.  Bind the actual provider/model settings immediately
        # before the one call and use that exact descriptor in the receipt and
        # artifact lineage.
        prepared_for_call = dict(prepared)
        prepared_for_call["wire_request_sha256"] = actual_wire_sha
        prepared_for_evidence = dict(prepared)
        prepared_for_evidence["wire_request_sha256"] = actual_wire_sha
        prepared_for_evidence["_request_wire_bytes"] = request_wire
        root = _validated_output_root(output_root if output_root is not None else self._default_output_root())
        provider_result: Any = None
        response_text: str | None = None
        try:
            # This is intentionally the only provider invocation in this
            # module.  AIProviderService.complete_json performs no retries.
            provider_result = provider.complete_json(
                prompt_text=prepared["prompt_text"],
                system_message=prepared["system_message"],
                purpose=COMPOSITE_CONTROLLER_PURPOSE,
                substantive=True,
                response_schema=prepared["response_schema"],
                response_schema_name=prepared["response_schema_name"],
                response_schema_max_output_tokens=COMPOSITE_CONTROLLER_MAX_OUTPUT_TOKENS,
                max_request_bytes=COMPOSITE_CONTROLLER_MAX_REQUEST_BYTES,
                temperature=0,
                expected_request_sha256=actual_wire_sha,
            )
        except FoundryError as exc:
            evidence = self._record_failure_evidence(
                root,
                prepared_for_evidence,
                primary=exc,
                provider_result=provider_result,
                valid=False,
                error=exc,
            )
            raise FoundryError(
                exc.code,
                exc.message,
                details={"evidence": str(evidence), "cause": exc.details},
                status_code=exc.status_code,
            ) from exc
        except Exception as exc:
            wrapped = _error(
                "COMPOSITE_CONTROLLER_PROVIDER_FAILED",
                "The local composite-controller provider call failed; no retry was attempted.",
                details={"exception_type": type(exc).__name__},
                status_code=502,
            )
            evidence = self._record_failure_evidence(
                root,
                prepared_for_evidence,
                primary=wrapped,
                provider_result=provider_result,
                valid=False,
                error=wrapped,
            )
            wrapped.details = {"evidence": str(evidence), "cause": wrapped.details}
            raise wrapped from exc
        try:
            parsed, response_text = _parse_provider_result(provider_result)
            supplied_completion_hash = provider_result.get("completion_sha256") if isinstance(provider_result, Mapping) else None
            calculated_completion_hash = sha256_bytes(response_text.encode("utf-8"))
            if supplied_completion_hash is not None and supplied_completion_hash != calculated_completion_hash:
                raise _error(
                    "COMPOSITE_CONTROLLER_COMPLETION_HASH_MISMATCH",
                    "The provider completion hash does not match the returned JSON content.",
                    details={"expected": calculated_completion_hash},
                )
            validated = self._validate_response(prepared, parsed)
            safe = self._safe_provider_receipt(provider_result, response_text=response_text)
            artifact = self._artifact(prepared_for_call, validated, response_sha256=safe.get("response_sha256"))
            overlay, overlay_info = self._write_overlay(root, artifact, source_workspace=Path(prepared["workspace_path"]))
        except FoundryError as exc:
            evidence = self._record_failure_evidence(
                root,
                prepared_for_evidence,
                primary=exc,
                provider_result=provider_result,
                response_text=response_text,
                valid=False,
                error=exc,
            )
            raise FoundryError(
                exc.code,
                exc.message,
                details={"evidence": str(evidence), "cause": exc.details},
                status_code=exc.status_code,
            ) from exc
        self._append_evidence(root, prepared_for_evidence, provider_result=provider_result, response_text=response_text, valid=True)
        return {
            "valid": True,
            "project_id": project_id,
            "candidate_sha256": prepared["candidate_sha256"],
            "projection_id": prepared["projection_id"],
            "request_sha256": prepared["request_sha256"],
            "provider_request_sha256": actual_wire_sha,
            "retry_count": 0,
            "resolution_mode": COMPOSITE_CONTROLLER_RESOLUTION_LOCAL,
            "provider_call_count": 1,
            "artifact": artifact,
            "overlay_path": str(overlay),
            **overlay_info,
        }

    def materialize_delegated(
        self,
        project_id: str,
        response: Mapping[str, Any],
        output_root: Path | None = None,
        *,
        selector_id: str,
    ) -> dict[str, Any]:
        """Seal an already-generated bounded response without invoking a provider."""

        prepared = self.prepare(project_id)
        safe_selector_id = _safe_identifier(selector_id, limit=80)
        if not _is_selector_id(selector_id):
            raise _error(
                "COMPOSITE_CONTROLLER_SELECTOR_ID_INVALID",
                "The delegated selector ID must be one bounded identifier.",
            )
        # Defer output-boundary validation until after delegated response
        # validation so a filesystem failure cannot mask its primary error.
        root = output_root if output_root is not None else self._default_output_root()
        request_wire = _canonical_wire_bytes(
            str(prepared["prompt_text"]),
            str(prepared["system_message"]),
            {
                "provider_id": "local",
                "model": "local-composite-controller",
                "max_output_tokens": COMPOSITE_CONTROLLER_MAX_OUTPUT_TOKENS,
            },
            prepared["response_schema"],
        )
        request_wire_sha256 = sha256_bytes(request_wire)
        if request_wire_sha256 != prepared.get("wire_request_sha256"):
            raise _error(
                "COMPOSITE_CONTROLLER_REQUEST_BINDING_INVALID",
                "The prepared request wire hash changed before delegated materialization.",
            )
        prepared_for_evidence = dict(prepared)
        prepared_for_evidence["_request_wire_bytes"] = request_wire
        response_text: str | None = None
        try:
            if not isinstance(response, Mapping):
                raise _error("COMPOSITE_CONTROLLER_DELEGATED_RESPONSE_INVALID", "The delegated response must be one object.")
            try:
                response_text = canonical_json(response)
            except (TypeError, ValueError, UnicodeError) as exc:
                raise _error("COMPOSITE_CONTROLLER_DELEGATED_RESPONSE_INVALID", "The delegated response is not canonical JSON.") from exc
            response_sha256 = sha256_bytes(response_text.encode("utf-8"))
            validated = self._validate_response(prepared, response)
            artifact = self._artifact(
                prepared,
                validated,
                response_sha256=response_sha256,
                resolution_mode=COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED,
                selector_id=safe_selector_id,
                provider_call_count=0,
            )
            overlay, overlay_info = self._write_overlay(
                root,
                artifact,
                source_workspace=Path(prepared["workspace_path"]),
            )
        except FoundryError as exc:
            evidence = self._record_failure_evidence(
                root,
                prepared_for_evidence,
                primary=exc,
                response_text=response_text,
                valid=False,
                error=exc,
                resolution_mode=COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED,
                selector_id=safe_selector_id,
                provider_call_count=0,
            )
            raise FoundryError(
                exc.code,
                exc.message,
                details={"evidence": str(evidence), "cause": exc.details},
                status_code=exc.status_code,
            ) from exc
        except Exception as exc:
            wrapped = _error(
                "COMPOSITE_CONTROLLER_DELEGATED_RESPONSE_INVALID",
                "The delegated response could not be materialized; no provider call was attempted.",
                details={"exception_type": type(exc).__name__},
            )
            evidence = self._record_failure_evidence(
                root,
                prepared_for_evidence,
                primary=wrapped,
                response_text=response_text,
                valid=False,
                error=wrapped,
                resolution_mode=COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED,
                selector_id=safe_selector_id,
                provider_call_count=0,
            )
            wrapped.details = {"evidence": str(evidence), "cause": wrapped.details}
            raise wrapped from exc
        self._append_evidence(
            root,
            prepared_for_evidence,
            response_text=response_text,
            valid=True,
            resolution_mode=COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED,
            selector_id=safe_selector_id,
            provider_call_count=0,
        )
        return {
            "valid": True,
            "project_id": project_id,
            "candidate_sha256": prepared["candidate_sha256"],
            "projection_id": prepared["projection_id"],
            "request_sha256": prepared["request_sha256"],
            "provider_request_sha256": request_wire_sha256,
            "response_sha256": response_sha256,
            "retry_count": 0,
            "resolution_mode": COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED,
            "selector_id": safe_selector_id,
            "provider_call_count": 0,
            "artifact": artifact,
            "overlay_path": str(overlay),
            **overlay_info,
        }

    def _default_output_root(self) -> Path:
        settings = getattr(getattr(self._db, "settings", None), "logs_dir", None)
        if isinstance(settings, (str, Path)):
            return Path(settings) / "factory_composite_controller"
        if self._fixed_workspace_root is not None:
            return self._fixed_workspace_root.parent / "composite_controller_logs"
        raise _error("COMPOSITE_CONTROLLER_OUTPUT_ROOT_INVALID", "A server-owned evidence output root is required.")

    @staticmethod
    def validate_overlay(
        overlay_root: Path,
        *,
        project_id: str | None = None,
        candidate_sha256: str | None = None,
        projection_id: str | None = None,
        source_workspace: Path | None = None,
    ) -> dict[str, Any]:
        root = Path(overlay_root)
        if source_workspace is None:
            raise _error(
                "COMPOSITE_CONTROLLER_OVERLAY_SOURCE_REQUIRED",
                "A controller overlay must be validated against its bound source workspace.",
            )
        if root.is_symlink() or not root.is_dir():
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_INVALID", "The controller overlay root is not a regular directory.")
        _reject_recursive_symlinks(
            root,
            code="COMPOSITE_CONTROLLER_OVERLAY_INVALID",
            message="The controller overlay must contain regular files only.",
        )
        _verify_workspace_checksums(root)
        expected_files = {
            "Command_4/Composite_Controller_Artifact.json",
            "Composite_Controller_Overlay_Manifest.json",
            "Validation/Composite_Controller.validation.json",
        }
        if set(_tree_hashes(root)) != expected_files:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTENT_INVALID", "The controller overlay contains unexpected or missing files.")
        manifest_path = root / "Composite_Controller_Overlay_Manifest.json"
        artifact_path = root / "Command_4/Composite_Controller_Artifact.json"
        validation_path = root / "Validation/Composite_Controller.validation.json"
        manifest = _load_json(manifest_path)
        artifact = _load_json(artifact_path)
        validation = _load_json(validation_path)
        if not isinstance(manifest, Mapping) or manifest.get("schema_version") != COMPOSITE_CONTROLLER_OVERLAY_SCHEMA:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_MANIFEST_INVALID", "The controller overlay manifest schema is unsupported.")
        if not isinstance(artifact, Mapping):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_ARTIFACT_INVALID", "The controller overlay artifact is not an object.")
        _validate_controller_artifact(artifact, project_id=project_id, candidate_sha256=candidate_sha256, projection_id=projection_id)
        expected_manifest_keys = {
            "schema_version", "overlay_id", "artifact_sha256", "source_workspace_sha256",
            "base_candidate_sha256", "project_id", "projection_id", "scope",
        }
        if set(manifest) != expected_manifest_keys:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_MANIFEST_INVALID", "The controller overlay manifest contents are incomplete.")
        for key in ("project_id", "projection_id", "source_workspace_sha256", "base_candidate_sha256"):
            artifact_key = "base_candidate_sha256" if key == "base_candidate_sha256" else key
            if manifest.get(key) != artifact.get(artifact_key):
                raise _error("COMPOSITE_CONTROLLER_OVERLAY_LINEAGE_MISMATCH", "The controller overlay manifest is not bound to its artifact.")
        if manifest.get("scope") != "Command 4 composite_controller policy overlay; no Command 5/6 claim":
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_MANIFEST_INVALID", "The controller overlay scope is unsupported.")
        artifact_sha = sha256_json(artifact)
        if manifest.get("artifact_sha256") != artifact_sha or manifest.get("overlay_id") != sha256_json({
            "source_workspace_sha256": artifact.get("source_workspace_sha256"),
            "base_candidate_sha256": artifact.get("base_candidate_sha256"),
            "artifact_sha256": artifact_sha,
        }):
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_HASH_INVALID", "The controller overlay manifest is not bound to its artifact.")
        expected_validation = _overlay_validation_payload(artifact, artifact_sha)
        if validation != expected_validation:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_CONTENT_INVALID", "The controller overlay validation receipt is not bound to its artifact.")
        if source_workspace is not None:
            _validate_artifact_against_workspace(artifact, Path(source_workspace))
        return {"overlay_id": manifest["overlay_id"], "artifact_sha256": artifact_sha, "artifact": deepcopy(dict(artifact)), "manifest": deepcopy(dict(manifest))}

    @staticmethod
    def apply_overlay(base_workspace: Path, overlay_root: Path, output_root: Path) -> Path:
        """Apply a validated controller overlay to a copied workspace only."""

        base = Path(base_workspace)
        if base.is_symlink() or not base.is_dir():
            raise _error("COMPOSITE_CONTROLLER_BASE_INVALID", "The base workspace is not a regular directory.")
        _reject_recursive_symlinks(
            base,
            code="COMPOSITE_CONTROLLER_BASE_INVALID",
            message="The base workspace must contain regular files only.",
        )
        _verify_workspace_checksums(base)
        base_hash = _workspace_sha256(base)
        validated = CompositeControllerAuthoring.validate_overlay(overlay_root, source_workspace=base)
        artifact = validated["artifact"]
        if artifact.get("source_workspace_sha256") != base_hash:
            raise _error("COMPOSITE_CONTROLLER_OVERLAY_BASE_MISMATCH", "The controller overlay is bound to a different workspace.")
        target_root = Path(output_root)
        if target_root.exists() and (target_root.is_symlink() or not target_root.is_dir()):
            raise _error("COMPOSITE_CONTROLLER_OUTPUT_ROOT_INVALID", "The applied controller output root is not a regular directory.")
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / validated["overlay_id"]
        if target.exists():
            _validate_applied_target(base, target, validated, base_hash)
            return target
        staging = target.with_name(target.name + ".staging")
        if staging.exists():
            raise _error("COMPOSITE_CONTROLLER_APPLIED_STAGING_EXISTS", "An applied controller staging path already exists.")
        shutil.copytree(base, staging)
        try:
            command4 = staging / "Command_4"
            command4.mkdir(exist_ok=True)
            _write_json(command4 / "Composite_Controller_Artifact.json", artifact)
            _write_json(staging / "Composite_Controller_Overlay_Manifest.json", validated["manifest"])
            validation_root = staging / "Validation"
            validation_root.mkdir(exist_ok=True)
            _write_json(validation_root / "Composite_Controller.validation.json", _overlay_validation_payload(artifact, validated["artifact_sha256"]))
            _write_workspace_checksums(staging)
            staging.replace(target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        _validate_applied_target(base, target, validated, base_hash)
        return target


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value), encoding="utf-8", newline="\n")


__all__ = [
    "COMPOSITE_CONTROLLER_ARTIFACT_SCHEMA",
    "COMPOSITE_CONTROLLER_ID",
    "COMPOSITE_CONTROLLER_MAX_REQUEST_BYTES",
    "COMPOSITE_CONTROLLER_MAX_SPEND",
    "COMPOSITE_CONTROLLER_RESOURCE_ABSOLUTE_MAX",
    "COMPOSITE_CONTROLLER_OVERLAY_SCHEMA",
    "COMPOSITE_CONTROLLER_PROVIDER_RESPONSE_SCHEMA",
    "COMPOSITE_CONTROLLER_PROVIDER_RESPONSE_SCHEMA_NAME",
    "COMPOSITE_CONTROLLER_PURPOSE",
    "COMPOSITE_CONTROLLER_RESOURCE_ALIAS",
    "COMPOSITE_CONTROLLER_RESOURCE_ID",
    "COMPOSITE_CONTROLLER_RESOLUTION_DELEGATED",
    "COMPOSITE_CONTROLLER_RESOLUTION_LOCAL",
    "COMPOSITE_CONTROLLER_RESPONSE_SCHEMA_NAME",
    "COMPOSITE_CONTROLLER_SCHEMA",
    "COMPOSITE_CONTROLLER_TARGET",
    "CompositeControllerAuthoring",
    "build_composite_controller_response_schema",
]
