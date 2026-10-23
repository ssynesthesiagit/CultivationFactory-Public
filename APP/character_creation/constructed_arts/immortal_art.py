"""Pure construction and recompilation for sealed Dao Aspect Immortal Arts.

The module accepts an already authenticated source snapshot.  It does not
look up a catalogue, read the private source tree, or choose mechanics from a
name.  A source is eligible only when the caller supplies its acquisition
proof, exact source binding, and a complete action surface.  This keeps the
module useful to character creation and Stage 2 while leaving authority and
database ownership with those services.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from app.core import FoundryError, canonical_json, sha256_bytes, sha256_json

IMMORTAL_ART_SCHEMA = "TianxiaFoundry.ImmortalArt.v1"
IMMORTAL_ART_REQUEST_SCHEMA = "TianxiaFoundry.ImmortalArtRequest.v1"
IMMORTAL_ART_AUTHORITY_SCHEMA = "TianxiaFoundry.ImmortalArtAuthority.v1"
IMMORTAL_ART_PACK_ID = "tianxia.immortal_art_authority.r1"
IMMORTAL_ART_PACK_VERSION = "R1"
IMMORTAL_ART_FILENAME = "Tianxia_Immortal_Art_Authority_R1.json"
# Keep the authority-file name discoverable under the terminology used by the
# other constructed-art loaders.
IMMORTAL_ART_AUTHORITY_FILENAME = IMMORTAL_ART_FILENAME
IMMORTAL_ART_ID_PREFIX = "tianxia.constructed.immortal_art."
IMMORTAL_ART_KIND = "immortal_art"
IMMORTAL_ART_FEATURE_COMMITMENT_SCHEMA = (
    "TianxiaFoundry.ImmortalArtProgressionFeatureCommitment.v1"
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ABILITY_CODES = frozenset({"STR", "DEX", "CON", "INT", "WIS", "CHA"})
_REALMS = ("Nascent Soul", "Immortal", "Earth Immortal", "Heaven Immortal", "True Immortal")
_REALM_ALIASES = {"True Immortality": "Immortal"}
# Core Rules Reference v0.2C §17.6 and opening rules Step 7 print one Mandate
# Threshold per tier (Nascent Soul 3, Immortal 6, ...).  In the text that
# number is a per-Art Mandate Complexity budget (Heaven Pressure applies above
# it; see ``construct_immortal_art``).  The owner ruling of 2026-09-11 applies
# the same tier number as the ceiling on how many refined Immortal Arts a
# cultivator may hold.  CL 15-19 is Nascent Soul; CL 20 ("True Immortality")
# is the Immortal tier (``standard_cl20_realm_alias`` in the sealed authority).
IMMORTAL_ART_MINIMUM_CL = 15
IMMORTAL_ART_COUNT_CEILING_RULE_ID = "tianxia.owner.immortal_art.count_ceiling.mandate_threshold.v1"
IMMORTAL_ART_COUNT_CEILING_AUTHORITY = (
    "Core Rules Reference v0.2C §17.6 Mandate Thresholds; opening rules Step 7; "
    "owner ruling 2026-09-11: refined Immortal Art count <= tier Mandate Threshold"
)
IMMORTAL_ART_COUNT_CEILING_BY_TIER = {"Nascent Soul": 3, "Immortal": 6}


def immortal_art_tier_for_cl(cl: Any) -> str | None:
    """Return the standard-ladder Immortal Art tier for a CL, or None below CL 15."""
    if isinstance(cl, bool) or type(cl) is not int or cl < IMMORTAL_ART_MINIMUM_CL:
        return None
    return "Immortal" if cl >= 20 else "Nascent Soul"


def immortal_art_count_ceiling(cl: Any) -> int:
    """Maximum number of refined Immortal Arts a character of this CL may hold (0 below CL 15)."""
    tier = immortal_art_tier_for_cl(cl)
    return IMMORTAL_ART_COUNT_CEILING_BY_TIER[tier] if tier else 0
_PATH_KINDS = {"body_refining", "qi_cultivation", "spirit_awakening"}
_RESOURCE_BY_PATH = {
    "body_refining": "Stamina",
    "qi_cultivation": "Qi",
    "spirit_awakening": "Resonance",
}
_ABILITY_BY_PATH = {
    "body_refining": frozenset({"CON"}),
    "qi_cultivation": frozenset({"INT", "CHA"}),
    "spirit_awakening": frozenset({"WIS"}),
}
_PLACEHOLDERS = (
    "as primary sphere prints",
    "as source prints",
    "define later",
    "not recorded",
    "unnamed talent",
    "unknown",
    "tbd",
    "varies by ruling",
)
_PASSIVE_ACTIONS = frozenset({"passive", "always on", "narrative", "downtime"})
_SOURCE_CONTENT_TYPES = frozenset(
    {
        "sphere_effect",
        "talent",
        "path_feature",
        "subpath_feature",
        "item_action",
        "manual_technique",
        "recorded_art",
        "forged_technique",
        "insight",
        "subclass_feature",
    }
)

# A source adapter may expose this exact list after it has authenticated the
# source's action against the installed catalogue.  The constructor never
# infers these Factor capabilities from a display name or a broad tag.
_FALLBACK_FACTORS = {
    "Destruction": "destructive_damage",
    "Binding": "speed_reduction",
    "Revelation": "detect_presence",
    "Concealment": "veil_target",
    "Fortification": "temporary_hp_fortification",
    "Restoration": "hp_restoration",
    "Transformation": "material_transformation",
    "Command": "tactical_coordination",
    "Transport": "movement_increase",
    "Reflection": "mirror_defense",
    "Entropy": "entropy_pressure",
    "Fate": "omen_reading",
    "Time": "hasten",
    "Soul": "soul_strike",
    "Heaven": "heaven_mark",
}
_FACTOR_SOURCE_TAGS = {
    "destructive_damage": {"damage", "destroy", "ruin"},
    "speed_reduction": {"bind", "restrain", "movement", "lock"},
    "detect_presence": {"reveal", "detect", "identity"},
    "veil_target": {"conceal", "hide", "veil"},
    "temporary_hp_fortification": {"protect", "reinforce", "guard"},
    "hp_restoration": {"restore", "heal", "repair"},
    "material_transformation": {"transform", "change", "form"},
    "tactical_coordination": {"command", "control", "order"},
    "movement_increase": {"move", "cross", "teleport"},
    "mirror_defense": {"reflect", "return", "rebound"},
    "entropy_pressure": {"decay", "decline", "ruin"},
    "omen_reading": {"fate", "branch", "prophecy"},
    "hasten": {"time", "delay", "duration"},
    "soul_strike": {"soul", "identity", "spirit"},
    "heaven_mark": {"heaven", "mandate", "permission", "law"},
}
# Path-feature actions are not admitted by the generic learned-source
# fallback.  These are the only source/Factor pairs whose complete action
# and Factor correspondence are explicitly implemented in this release.
_EXPLICIT_PATH_FEATURE_FACTORS = {
    "tianxia.subpath.body.mantis_style.feature.eye_of_the_mantis": "detect_presence",
    "tianxia.tradition.spirit.dreamweaver.feature.unreality_bites_back": "destructive_damage",
}


def _error(code: str, message: str, **details: Any) -> FoundryError:
    return FoundryError(code, message, details=details)


def _invalid(message: str, **details: Any) -> FoundryError:
    return _error("IMMORTAL_ART_REQUEST_INVALID", message, **details)


def _text(
    value: Any,
    field: str,
    *,
    maximum: int = 4000,
    allow_empty: bool = False,
    preserve_whitespace: bool = False,
) -> str:
    if not isinstance(value, str):
        if allow_empty and value is None:
            return ""
        raise _invalid("A text field must be a string.", field=field)
    if not preserve_whitespace:
        value = value.strip()
    if not value and not allow_empty:
        raise _invalid("A text field must be non-empty.", field=field)
    if len(value) > maximum or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise _invalid("A text field is too long or contains control characters.", field=field)
    return value


def _id(value: Any, field: str) -> str:
    value = _text(value, field, maximum=300)
    if not _ID_RE.fullmatch(value):
        raise _invalid("An identifier contains unsupported characters.", field=field, value=value)
    return value


def _hash(value: Any, field: str) -> str:
    value = _text(value, field, maximum=64)
    if not _HASH_RE.fullmatch(value):
        raise _invalid("A source or record hash must be a lowercase SHA-256 commitment.", field=field)
    return value


def _list_text(value: Any, field: str, *, maximum: int = 240, allow_empty: bool = True) -> list[str]:
    if value is None and allow_empty:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise _invalid("A field must be a list of strings.", field=field)
    result = [_text(item, f"{field}[{index}]", maximum=maximum) for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise _invalid("A list must not contain duplicate strings.", field=field)
    return result


def _first(mapping: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return default


def _path_kind(path_id: str, explicit: Any) -> str:
    if explicit is not None:
        value = _text(explicit, "path_kind", maximum=80).casefold().replace(" ", "_")
        if value in _PATH_KINDS:
            return value
        raise _invalid("The Path kind is not one of the three canonical Paths.", field="path_kind", value=value)
    lowered = path_id.casefold()
    if "body" in lowered:
        return "body_refining"
    if "qi" in lowered:
        return "qi_cultivation"
    if "spirit" in lowered:
        return "spirit_awakening"
    raise _invalid("The Path kind must be supplied by independent Path authority.", field="path_kind")


def immortal_art_progression_child_hash(
    parent_record_id: str,
    parent_record_hash: str,
    feature: Mapping[str, Any],
) -> str:
    """Commit one authenticated Subpath progression child to its parent.

    P2B progression children are published inside a locked Subpath authority
    row; they are not independent project lock records.  This commitment gives
    the child a stable identity for the Art source snapshot while retaining the
    exact parent identity that Stage 2 must authenticate separately.
    """
    if not isinstance(parent_record_id, str) or not parent_record_id.strip():
        raise _error(
            "IMMORTAL_ART_FEATURE_PROVENANCE_INVALID",
            "A progression-child commitment requires a parent record ID.",
        )
    if not isinstance(parent_record_hash, str) or not _HASH_RE.fullmatch(parent_record_hash):
        raise _error(
            "IMMORTAL_ART_FEATURE_PROVENANCE_INVALID",
            "A progression-child commitment requires the exact parent record hash.",
        )
    if not isinstance(feature, Mapping):
        raise _error(
            "IMMORTAL_ART_FEATURE_PROVENANCE_INVALID",
            "A progression-child commitment requires an authenticated feature row.",
        )
    return sha256_json({
        "schema": IMMORTAL_ART_FEATURE_COMMITMENT_SCHEMA,
        "parent_record_id": parent_record_id,
        "parent_record_hash": parent_record_hash,
        "feature": deepcopy(dict(feature)),
    })


def immortal_art_authority_path(root_dir: Path) -> Path:
    return Path(root_dir) / "authority" / IMMORTAL_ART_FILENAME


def _authority_error(message: str, **details: Any) -> FoundryError:
    return _error("IMMORTAL_ART_AUTHORITY_INVALID", message, **details)


def load_immortal_art_authority(root_dir: Path) -> dict[str, Any]:
    """Load the shipped authority and verify its internal source commitments.

    Runtime loading intentionally does not read ``LocalSources``.  The build
    tool verifies that private/source-controlled tree; the application trusts
    only the sealed copy and its embedded exact source text/hash commitments.
    """
    path = immortal_art_authority_path(root_dir)
    if not path.is_file():
        raise _authority_error("The sealed Immortal Art authority is missing.", path=str(path))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive I/O boundary
        raise _authority_error("The sealed Immortal Art authority is unreadable.", path=str(path), error=str(exc)) from exc
    if not isinstance(value, dict) or value.get("schema_version") != IMMORTAL_ART_AUTHORITY_SCHEMA:
        raise _authority_error("The authority declares an unsupported schema.", path=str(path))
    unsigned = {key: item for key, item in value.items() if key != "seal_sha256"}
    if value.get("seal_sha256") != sha256_json(unsigned):
        raise _authority_error("The authority failed its canonical seal.", path=str(path))
    if value.get("pack_id") != IMMORTAL_ART_PACK_ID or value.get("authority_classification") != "AUTHENTICATED_CANONICAL_SOURCE":
        raise _authority_error("The authority pack identity or classification is invalid.", path=str(path))
    opening = value.get("opening_rules")
    if not isinstance(opening, Mapping) or not isinstance(opening.get("source_text"), str):
        raise _authority_error("The authority has no exact opening rules source.")
    if sha256_bytes(opening["source_text"].encode("utf-8")) != opening.get("source_text_sha256"):
        raise _authority_error("The embedded opening rules failed their source hash.")
    aspects = value.get("aspects")
    if not isinstance(aspects, list) or len(aspects) != 17:
        raise _authority_error("The authority must contain all seventeen active Aspects.")
    if set(row.get("display_name") for row in aspects if isinstance(row, Mapping)) != {
        "Destruction", "Binding", "Revelation", "Concealment", "Fortification", "Restoration", "Transformation", "Command", "Transport", "Reflection", "Domain", "Creation", "Entropy", "Fate", "Time", "Soul", "Heaven"
    }:
        raise _authority_error("The authority Aspect set is incomplete or contains inactive Chaos.")
    for row in aspects:
        if not isinstance(row, Mapping) or not isinstance(row.get("source_text"), str) or not isinstance(row.get("source"), Mapping):
            raise _authority_error("An Aspect chassis is incomplete.")
        actual = sha256_bytes(row["source_text"].encode("utf-8"))
        if actual != row.get("source_text_sha256") or actual != row["source"].get("source_hash"):
            raise _authority_error("An Aspect chassis source commitment is inconsistent.", aspect=row.get("display_name"))
    shared = value.get("shared_rules")
    if not isinstance(shared, Mapping) or not isinstance(shared.get("realm_thresholds"), list) or not isinstance(shared.get("activation_cp"), Mapping):
        raise _authority_error("The authority lacks required numeric construction tables.")
    if value.get("manifest_sources_verified") is not True or value.get("sidecars_verified") is not True:
        raise _authority_error("The authority was not built from verified source sidecars.")
    return value


def _source_binding(row: Mapping[str, Any], field: str) -> dict[str, str]:
    source = _first(row, "source", "source_binding", "provenance")
    if not isinstance(source, Mapping):
        raise _invalid("Every source must carry an exact source binding.", field=f"{field}.source")
    source_id = _id(_first(source, "source_id", "id"), f"{field}.source.source_id")
    path = _text(_first(source, "path", "source_path", "factory_source_path"), f"{field}.source.path", maximum=1500)
    anchor = _text(_first(source, "anchor", "section", "source_anchor"), f"{field}.source.anchor", maximum=700)
    source_hash = _hash(_first(source, "source_hash", "sha256", "file_sha256", "source_file_sha256"), f"{field}.source.source_hash")
    return {"source_id": source_id, "path": path, "anchor": anchor, "source_hash": source_hash}


def _nested_action(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for candidate in (
        row.get("action_surface"),
        row.get("source_action"),
        row.get("action"),
        row.get("execution"),
        (row.get("path_feature") or {}).get("action_surface") if isinstance(row.get("path_feature"), Mapping) else None,
        ((row.get("stage2_authority") or {}).get("action_surface") if isinstance(row.get("stage2_authority"), Mapping) else None),
    ):
        if isinstance(candidate, Mapping):
            return candidate
    return None


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.casefold()
        return any(phrase in lowered for phrase in _PLACEHOLDERS)
    if isinstance(value, Mapping):
        return any(_contains_placeholder(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_placeholder(item) for item in value)
    return False


def _json_value(
    value: Any,
    field: str,
    *,
    maximum_text: int = 12000,
    preserve_strings: bool = False,
) -> Any:
    """Copy a source extension while keeping the construction JSON typed.

    Source adapters sometimes carry chassis-specific fields (for example a
    construct's statistics or a Domain relation list) that are not part of
    the common action surface.  Preserve those fields, but do not let an
    arbitrary Python object enter the identity/recompilation payload.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str):
            return _text(
                value,
                field,
                maximum=maximum_text,
                allow_empty=True,
                preserve_whitespace=preserve_strings,
            )
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _invalid("A source mechanics mapping must use string keys.", field=field)
            result[key] = _json_value(
                item,
                f"{field}.{key}",
                maximum_text=maximum_text,
                preserve_strings=preserve_strings,
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            _json_value(
                item,
                f"{field}[{index}]",
                maximum_text=maximum_text,
                preserve_strings=preserve_strings,
            )
            for index, item in enumerate(value)
        ]
    raise _invalid("A source mechanics field contains an unsupported value.", field=field)


def _action_surface(row: Mapping[str, Any], field: str, *, path_kind: str) -> dict[str, Any]:
    raw = _nested_action(row)
    if raw is None:
        raise _error("IMMORTAL_ART_SOURCE_ACTION_INCOMPLETE", "A source has no explicit complete action surface.", field=field)
    if row.get("passive") is True or raw.get("passive") is True:
        raise _error("IMMORTAL_ART_SOURCE_PASSIVE_UNSUPPORTED", "A passive source cannot supply an Immortal Art action.", field=field)
    action_type = _text(_first(raw, "action_type", "action_cost", "activation", "action"), f"{field}.action_type", maximum=100).casefold()
    if action_type in _PASSIVE_ACTIONS:
        raise _error("IMMORTAL_ART_SOURCE_PASSIVE_UNSUPPORTED", "A passive or narrative source cannot supply an Immortal Art action.", field=field)
    if action_type not in {"action", "bonus action", "reaction", "free action", "ritual", "object interaction"}:
        raise _error("IMMORTAL_ART_SOURCE_ACTION_INCOMPLETE", "A source action has an unsupported action economy.", field=field, action_type=action_type)
    activation = _text(_first(raw, "activation", "action_cost", "action_type", "action"), f"{field}.activation", maximum=100)
    required_text = {
        "range": _first(raw, "range", "range_text"),
        "target": _first(raw, "target", "targets", "target_text"),
        "duration": _first(raw, "duration", "duration_text"),
        "effect": _first(raw, "effect", "effect_package", "published_effect"),
    }
    for name, value in required_text.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            raise _error("IMMORTAL_ART_SOURCE_ACTION_INCOMPLETE", "A source action omits a required mechanical field.", field=f"{field}.{name}")
    placeholder_surface = raw
    from .native_immortal_sources import NATIVE_COMMITMENT_KIND, native_placeholder_surface
    if row.get("feature_record_hash_kind") == NATIVE_COMMITMENT_KIND:
        placeholder_surface = native_placeholder_surface(row, raw)
    if _contains_placeholder(placeholder_surface):
        raise _error("IMMORTAL_ART_SOURCE_ACTION_INCOMPLETE", "A source action contains a generic or unresolved placeholder.", field=field)
    resource = raw.get("resource") if isinstance(raw.get("resource"), Mapping) else {}
    resource_name = _first(raw, "resource_name", "path_resource", default=resource.get("name"))
    resource_cost = _first(raw, "resource_cost", "cost", default=resource.get("cost"))
    resource_name = _text(resource_name, f"{field}.resource_name", maximum=120)
    if type(resource_cost) is not int or resource_cost < 1:
        raise _error("IMMORTAL_ART_SOURCE_COST_UNPUBLISHED", "An Immortal Art source must carry a positive numeric Path-resource cost.", field=f"{field}.resource_cost", value=resource_cost)
    area = _first(raw, "area", "area_text")
    if area is not None:
        area = _text(area, f"{field}.area", maximum=1000, allow_empty=True) or None
    limits = _list_text(_first(raw, "limits", "restrictions", default=[]), f"{field}.limits", maximum=1200)
    tags = _list_text(
        _first(raw, "source_tags", "tags", "semantic_tags", default=_first(row, "source_tags", "tags", default=[])),
        f"{field}.source_tags",
        maximum=160,
    )
    if not tags:
        raise _error("IMMORTAL_ART_SOURCE_TAGS_MISSING", "An Immortal Art source must carry source-backed semantic tags.", field=f"{field}.source_tags")
    procedure_raw = _first(raw, "normalized_procedure", "procedure", default=[])
    if isinstance(procedure_raw, str):
        procedure = [_text(procedure_raw, f"{field}.normalized_procedure", maximum=4000)]
    else:
        procedure = _list_text(procedure_raw, f"{field}.normalized_procedure", maximum=4000, allow_empty=False)
    cross_raw = _first(raw, "cross_references", "cross_refs", default=[])
    cross = _list_text(cross_raw, f"{field}.cross_references", maximum=600)
    def optional_text(*names: str, maximum: int = 4000, default: str = "none") -> str:
        value = _first(raw, *names, default=default)
        return _text(value, f"{field}.{names[0]}", maximum=maximum)
    normalized = {
        "action_type": action_type,
        "activation": activation,
        "range": _text(required_text["range"], f"{field}.range", maximum=1000),
        "target": _text(required_text["target"], f"{field}.target", maximum=2000),
        "area": area,
        "duration": _text(required_text["duration"], f"{field}.duration", maximum=1000),
        "trigger": optional_text("trigger", default="on activation"),
        "trigger_frequency": optional_text("trigger_frequency", "frequency", default="once per activation"),
        "save_or_check": optional_text("save_or_check", "save", "check", default="none"),
        "attack_roll": optional_text("attack_roll", "attack", default="none"),
        "dc_basis": optional_text("dc_basis", "dc", default="none"),
        "effect": deepcopy(required_text["effect"]),
        "success": optional_text("success", "success_result", default="resolves the source effect"),
        "failure": optional_text("failure", "failure_result", default="the source effect does not resolve"),
        "success_by_5": optional_text("success_by_5", "success_by_five", default="none"),
        "failure_by_5": optional_text("failure_by_5", "failure_by_five", default="none"),
        "counterplay": optional_text("counterplay", "counterplay_route", default="ordinary source counterplay applies"),
        "cleanup": optional_text("cleanup", "cleanup_result", default="ends according to the source duration"),
        "limits": limits,
        "resource_name": resource_name,
        "resource_cost": resource_cost,
        "source_tags": sorted(set(tags)),
        "normalized_procedure": procedure,
        "cross_references": cross,
    }
    # Carry authenticated, chassis-specific mechanics through the twelve-step
    # payload.  The common fields above remain canonical; these extensions are
    # source data, not inferred rules.
    common_keys = {
        "action_type", "action_cost", "activation", "action", "range", "range_text",
        "target", "targets", "target_text", "area", "area_text", "duration", "duration_text",
        "trigger", "trigger_frequency", "frequency", "save_or_check", "save", "check",
        "attack_roll", "attack", "dc_basis", "dc", "effect", "effect_package", "published_effect",
        "success", "success_result", "failure", "failure_result", "success_by_5", "success_by_five",
        "failure_by_5", "failure_by_five", "counterplay", "counterplay_route", "cleanup",
        "cleanup_result", "limits", "restrictions", "resource", "resource_name", "path_resource",
        "resource_cost", "cost", "source_tags", "tags", "semantic_tags", "normalized_procedure",
        "procedure", "cross_references", "cross_refs", "passive", "source_mechanics",
    }
    extensions = raw.get("source_mechanics", {})
    if extensions is None:
        extensions = {}
    if not isinstance(extensions, Mapping):
        raise _invalid("A source mechanics extension must be a mapping.", field=f"{field}.source_mechanics")
    extensions = dict(extensions)
    extensions.update({key: value for key, value in raw.items() if key not in common_keys})
    # ``source_mechanics`` may carry the exact hash-bound published section.
    # Preserve its bytes through normalization; trimming would make an honest
    # source snapshot differ from the installed section at the Stage 2 gate.
    normalized["source_mechanics"] = _json_value(
        extensions,
        f"{field}.source_mechanics",
        preserve_strings=True,
    )
    # The path is retained as a check input, not inferred from resource text.
    expected_resource = _RESOURCE_BY_PATH[path_kind]
    if resource_name != expected_resource:
        raise _error("IMMORTAL_ART_SOURCE_RESOURCE_MISMATCH", "The source cost is not paid from the powering Path resource.", expected=expected_resource, actual=resource_name)
    return normalized


def _progression(row: Mapping[str, Any], field: str) -> dict[str, Any] | None:
    raw = _first(row, "progression", "feature_progression", default=None)
    if raw is None:
        authority = row.get("stage2_authority")
        if isinstance(authority, Mapping):
            raw = authority.get("feature_progression")
    if raw is None:
        return None
    if isinstance(raw, list):
        if not raw or not isinstance(raw[0], Mapping):
            raise _error("IMMORTAL_ART_SOURCE_PROGRESSION_INVALID", "A source progression proof is malformed.", field=field)
        raw = raw[0]
    if not isinstance(raw, Mapping):
        raise _error("IMMORTAL_ART_SOURCE_PROGRESSION_INVALID", "A source progression proof is malformed.", field=field)
    result = deepcopy(dict(raw))
    granted = _first(result, "granted_at_cl", "owning_level", "source_cl", "minimum_cl")
    if type(granted) is not int or granted < 1:
        raise _error("IMMORTAL_ART_SOURCE_PROGRESSION_INVALID", "A source progression proof has no numeric granted level.", field=f"{field}.granted_at_cl")
    result["granted_at_cl"] = granted
    owning = _first(result, "owning_path_id", "parent_path_id", "path_id")
    if owning is not None:
        result["owning_path_id"] = _id(owning, f"{field}.owning_path_id")
    source = result.get("source")
    if source is not None and not isinstance(source, Mapping):
        raise _error("IMMORTAL_ART_SOURCE_PROGRESSION_INVALID", "A source progression proof has an invalid source binding.", field=f"{field}.source")
    return result


def _normalize_source(row: Mapping[str, Any], index: int, *, path_kind: str, target_cl: int, owning_path_cl: int) -> dict[str, Any]:
    field = f"known_sources[{index}]"
    if not isinstance(row, Mapping):
        raise _invalid("A known source row must be an object.", field=field)
    record_id = _id(_first(row, "record_id", "source_record_id", "talent_id", "feature_id", "item_id"), f"{field}.record_id")
    record_hash = _hash(_first(row, "record_hash", "source_record_hash"), f"{field}.record_hash")
    source = _source_binding(row, field)
    display_name = _text(_first(row, "display_name", "name", "source_name", default=record_id), f"{field}.display_name", maximum=300)
    content_type = _text(_first(row, "content_type", "source_type", "kind", default="talent"), f"{field}.content_type", maximum=100).casefold()
    if content_type == "subpath":
        content_type = "path_feature"
    if content_type not in _SOURCE_CONTENT_TYPES:
        raise _error("IMMORTAL_ART_SOURCE_KIND_UNSUPPORTED", "The source kind is not a legal Immortal Art source route.", field=f"{field}.content_type", value=content_type)
    acquired_raw = _first(row, "acquired", "known", default=None)
    acquisition = row.get("acquisition") if isinstance(row.get("acquisition"), Mapping) else {}
    if acquired_raw is None:
        acquired_raw = _first(acquisition, "acquired", "known", "status", default=None)
        if isinstance(acquired_raw, str):
            acquired_raw = acquired_raw.casefold() in {"acquired", "known", "learned", "active", "true"}
    if acquired_raw is not True:
        raise _error("IMMORTAL_ART_SOURCE_NOT_KNOWN", "An Immortal Art source must be actually known or acquired before construction.", source_record_id=record_id)
    acquired_at = _first(row, "acquired_at_cl", "learned_at_cl", "gained_at_cl", default=_first(acquisition, "acquired_at_cl", "learned_at_cl", "gained_at_cl", default=None))
    if type(acquired_at) is not int or acquired_at < 1 or acquired_at > target_cl:
        raise _error("IMMORTAL_ART_SOURCE_ACQUISITION_TIMING_INVALID", "A source is not acquired by the construction CL.", source_record_id=record_id, acquired_at_cl=acquired_at, target_cl=target_cl)
    action = _action_surface(row, field, path_kind=path_kind)
    tags = sorted(set(_list_text(_first(row, "source_tags", "tags", default=action["source_tags"]), f"{field}.source_tags", maximum=160) + action["source_tags"]))
    sphere_id = _first(row, "sphere_id", "owning_sphere_id")
    if sphere_id is not None:
        sphere_id = _id(sphere_id, f"{field}.sphere_id")
    sphere_name = _first(row, "sphere_name", "owning_sphere_name")
    if sphere_name is not None:
        sphere_name = _text(sphere_name, f"{field}.sphere_name", maximum=300)
    owning_path_id = _first(row, "owning_path_id", "path_id")
    if owning_path_id is not None:
        owning_path_id = _id(owning_path_id, f"{field}.owning_path_id")
    feature_record_hash_kind = _first(row, "feature_record_hash_kind", default=None)
    if feature_record_hash_kind is not None:
        feature_record_hash_kind = _text(feature_record_hash_kind, f"{field}.feature_record_hash_kind", maximum=120)
    progression = _progression(row, field)
    if content_type in {"path_feature", "subpath_feature"}:
        if progression is None:
            raise _error("IMMORTAL_ART_SOURCE_PROGRESSION_MISSING", "A Path feature source requires proof-bound selected Subpath progression.", source_record_id=record_id)
        progression_path = progression.get("owning_path_id") or owning_path_id
        if progression_path != row.get("path_id", row.get("owning_path_id")) and progression_path is not None and owning_path_id is not None:
            raise _error("IMMORTAL_ART_SOURCE_PROGRESSION_OWNER_MISMATCH", "A source progression is owned by a different Path.", source_record_id=record_id)
        if progression_path is not None and progression_path != owning_path_id and owning_path_id is not None:
            raise _error("IMMORTAL_ART_SOURCE_PROGRESSION_OWNER_MISMATCH", "A source progression and feature record disagree about Path ownership.", source_record_id=record_id)
        if type(progression["granted_at_cl"]) is not int or progression["granted_at_cl"] > owning_path_cl:
            raise _error("IMMORTAL_ART_SOURCE_PROGRESSION_NOT_ATTAINED", "A Path feature was not attained by the owning Path CL.", source_record_id=record_id, granted_at_cl=progression["granted_at_cl"], owning_path_cl=owning_path_cl)
        feature_snapshot = progression.get("feature_snapshot")
        if feature_snapshot is not None:
            parent_id = progression.get("parent_record_id")
            parent_hash = progression.get("parent_record_hash")
            from .native_immortal_sources import NATIVE_COMMITMENT_KIND, native_feature_hash
            native = feature_record_hash_kind == NATIVE_COMMITMENT_KIND
            commitment_kind = NATIVE_COMMITMENT_KIND if native else "subpath_progression_commitment"
            expected_child_hash = (native_feature_hash if native else immortal_art_progression_child_hash)(parent_id, parent_hash, feature_snapshot)
            if (
                feature_record_hash_kind != commitment_kind
                or progression.get("feature_record_hash_kind") != commitment_kind
                or progression.get("feature_record_id") != record_id
                or record_hash != expected_child_hash
            ):
                raise _error(
                    "IMMORTAL_ART_SOURCE_FEATURE_COMMITMENT_MISMATCH",
                    "A progression feature source hash must commit to its exact parent and authenticated feature row.",
                    source_record_id=record_id,
                )
    source_package_id = _id(_first(row, "source_package_id", "package_id", default=source["source_id"]), f"{field}.source_package_id")
    supported_factor_ids = _list_text(
        _first(row, "supported_factor_ids", "compatible_factor_ids", default=[]),
        f"{field}.supported_factor_ids",
        maximum=300,
    )
    adapter_rows = _first(row, "factor_adapters", "supported_factor_adapters", default={})
    if adapter_rows is None:
        adapter_rows = {}
    if not isinstance(adapter_rows, Mapping):
        raise _invalid("Source Factor adapters must be a mapping keyed by Factor id.", field=f"{field}.factor_adapters")
    factor_adapters: dict[str, Any] = {}
    for adapter_id, adapter in adapter_rows.items():
        normalized_adapter_id = _id(adapter_id, f"{field}.factor_adapters.key")
        factor_adapters[normalized_adapter_id] = _json_value(adapter, f"{field}.factor_adapters.{normalized_adapter_id}", maximum_text=4000)
    dependency_rows = _first(row, "source_dependencies", "authenticated_source_dependencies", default=[])
    if dependency_rows is None:
        dependency_rows = []
    if not isinstance(dependency_rows, list):
        raise _invalid("Source dependencies must be a list.", field=f"{field}.source_dependencies")
    source_dependencies = [
        _json_value(
            dependency,
            f"{field}.source_dependencies[{index}]",
            maximum_text=12000,
            preserve_strings=True,
        )
        for index, dependency in enumerate(dependency_rows)
    ]
    normalized = {
        "record_id": record_id,
        "record_hash": record_hash,
        "display_name": display_name,
        "content_type": content_type,
        "source": source,
        "sphere_id": sphere_id,
        "sphere_name": sphere_name,
        "owning_path_id": owning_path_id,
        "source_package_id": source_package_id,
        "source_tags": tags,
        "acquired": True,
        "acquired_at_cl": acquired_at,
        "acquisition": deepcopy(dict(acquisition)),
        "progression": progression,
        "action_surface": action,
        # This is quoted source content, so leading/trailing whitespace is
        # part of the authenticated value and must survive normalization.
        "published_text": _text(
            _first(row, "published_text", "source_block", default=""),
            f"{field}.published_text",
            maximum=12000,
            allow_empty=True,
            preserve_whitespace=True,
        ),
        "credible_bridges": _list_text(_first(row, "credible_bridges", "bridge_factors", default=[]), f"{field}.credible_bridges", maximum=300),
        "supported_factor_ids": supported_factor_ids,
        "factor_adapters": factor_adapters,
        "source_dependencies": source_dependencies,
    }
    if feature_record_hash_kind is not None:
        normalized["feature_record_hash_kind"] = feature_record_hash_kind
    return normalized


def normalize_immortal_art_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and canonicalize an already authenticated construction input."""
    if not isinstance(request, Mapping):
        raise _invalid("The Immortal Art request must be an object.")
    schema = request.get("schema")
    if schema not in (None, IMMORTAL_ART_REQUEST_SCHEMA):
        raise _invalid("The Immortal Art request declares an unsupported schema.", schema=schema)
    seed = _text(request.get("seed"), "seed", maximum=300)
    project_id = _text(request.get("project_id"), "project_id", maximum=300)
    cl = request.get("cl")
    pb = request.get("pb")
    if type(cl) is not int or not 15 <= cl <= 20:
        raise _error("IMMORTAL_ART_NOT_AVAILABLE", "Immortal Arts require CL 15 or higher.", cl=cl)
    if type(pb) is not int or not 2 <= pb <= 6:
        raise _invalid("Proficiency Bonus must be an integer from 2 through 6.", field="pb")
    path_id = _id(request.get("path_id"), "path_id")
    path_kind = _path_kind(path_id, request.get("path_kind"))
    path_name = _text(_first(request, "path_name", default=path_id), "path_name", maximum=300)
    key_ability = request.get("key_ability")
    if key_ability not in _ABILITY_CODES or key_ability not in _ABILITY_BY_PATH[path_kind]:
        raise _invalid("The powering Path key ability does not match independent Path authority.", field="key_ability", value=key_ability, path_kind=path_kind)
    modifier = _first(request, "key_ability_modifier", "path_ability_modifier", "ability_modifier")
    if modifier is None and isinstance(request.get("ability_modifiers"), Mapping):
        modifier = request["ability_modifiers"].get(key_ability)
    if type(modifier) is not int:
        raise _invalid("The Path ability modifier must be supplied by character authority.", field="key_ability_modifier")
    owning_path_cl = _first(request, "owning_path_cl", "path_cl", "effective_path_cl")
    if type(owning_path_cl) is not int or not 1 <= owning_path_cl <= 20:
        raise _invalid("The attained owning Path CL must be supplied independently of overall CL.", field="owning_path_cl")
    path_realm_input = _text(_first(request, "path_realm", "realm"), "path_realm", maximum=100)
    path_realm = _REALM_ALIASES.get(path_realm_input, path_realm_input)
    if path_realm not in _REALMS:
        raise _invalid("The Path Realm is not a published Immortal Art Realm band.", field="path_realm", value=path_realm_input)
    known_spheres_in = _first(request, "known_spheres", "spheres", default=[])
    if not isinstance(known_spheres_in, list):
        raise _invalid("Known Spheres must be a list.", field="known_spheres")
    spheres: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(known_spheres_in):
        if not isinstance(row, Mapping):
            raise _invalid("A known Sphere row must be an object.", field=f"known_spheres[{index}]")
        sphere_id = _id(_first(row, "sphere_id", "record_id"), f"known_spheres[{index}].sphere_id")
        if sphere_id in spheres:
            raise _invalid("Known Spheres must be unique.", field=f"known_spheres[{index}].sphere_id")
        spheres[sphere_id] = {
            "sphere_id": sphere_id,
            "display_name": _text(_first(row, "display_name", "name", default=sphere_id), f"known_spheres[{index}].display_name", maximum=300),
        }
    sources_in = _first(request, "known_sources", "source_records", "known_talents", default=[])
    if not isinstance(sources_in, list) or not sources_in:
        raise _invalid("An Immortal Art requires at least one known complete source action.", field="known_sources")
    sources = [_normalize_source(row, index, path_kind=path_kind, target_cl=cl, owning_path_cl=owning_path_cl) for index, row in enumerate(sources_in)]
    if len({row["record_id"] for row in sources}) != len(sources):
        raise _invalid("Known source records must be unique.", field="known_sources")
    sources.sort(key=lambda row: (row["owning_path_id"] or "", row["source_package_id"], row["record_id"]))
    selected = _first(request, "source_record_id", "selected_source_id", "base_source_record_id")
    if selected is not None:
        selected = _id(selected, "source_record_id")
    ordinal = _first(request, "art_ordinal", "ordinal", default=0)
    if type(ordinal) is not int or ordinal not in (0, 1):
        raise _invalid("Immortal Art ordinal must be zero or one.", field="art_ordinal")
    if ordinal == 1 and cl < 20:
        raise _error("IMMORTAL_ART_SECOND_NOT_AVAILABLE", "A second Immortal Art is only available at CL 20.", cl=cl)
    aspect_id = _first(request, "aspect_id", "selected_aspect_id")
    if aspect_id is not None:
        aspect_id = _id(aspect_id, "aspect_id")
    factor_ids = _list_text(_first(request, "factor_ids", "selected_factor_ids", default=[]), "factor_ids", maximum=300)
    burdens = _list_text(_first(request, "burdens", "burden_ids", default=[]), "burdens", maximum=300)
    special_scale = _first(request, "special_scale_cost", default=0)
    if type(special_scale) is not int or special_scale < 0:
        raise _invalid("Special scale cost must be a non-negative integer.", field="special_scale_cost")
    gm_approved = request.get("gm_review_approved", False)
    if type(gm_approved) is not bool:
        raise _invalid("GM review approval must be boolean.", field="gm_review_approved")
    gm_review_authority = request.get("gm_review_authority")
    if gm_review_authority is not None and not isinstance(gm_review_authority, Mapping):
        raise _invalid("GM review authority must be an authenticated authority record.", field="gm_review_authority")
    source_packages = sorted({row["source_package_id"] for row in sources})
    return {
        "schema": IMMORTAL_ART_REQUEST_SCHEMA,
        "seed": seed,
        "project_id": project_id,
        "cl": cl,
        "pb": pb,
        "path_id": path_id,
        "path_kind": path_kind,
        "path_name": path_name,
        "key_ability": key_ability,
        "key_ability_modifier": modifier,
        "owning_path_cl": owning_path_cl,
        "path_realm": path_realm,
        "path_realm_input": path_realm_input,
        "known_spheres": [spheres[key] for key in sorted(spheres)],
        "known_sources": sources,
        "source_packages": source_packages,
        "source_record_id": selected,
        "art_ordinal": ordinal,
        "aspect_id": aspect_id,
        "factor_ids": factor_ids,
        "burdens": burdens,
        "special_scale_cost": special_scale,
        "gm_review_approved": gm_approved,
        "gm_review_authority": deepcopy(dict(gm_review_authority)) if isinstance(gm_review_authority, Mapping) else None,
    }


def _aspect_rows(authority: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = authority.get("aspects")
    if not isinstance(rows, list):
        raise _authority_error("The authority has no Aspect rows.")
    return {str(row.get("aspect_id")): row for row in rows if isinstance(row, Mapping)}


def _source_score(source_tags: Iterable[str], aspect: Mapping[str, Any]) -> int | None:
    required = {str(tag).casefold() for tag in aspect.get("semantic_tags", [])}
    actual = {str(tag).casefold() for tag in source_tags}
    if not required or not actual:
        return None
    if required & actual:
        return 0
    # An explicit caller-supplied ``credible_bridges`` is checked later; no
    # name or free text is treated as a capability signal.
    return None


def _factor_row(aspect: Mapping[str, Any], factor_id: str) -> Mapping[str, Any]:
    for row in aspect.get("factors", []):
        if isinstance(row, Mapping) and row.get("factor_id") == factor_id:
            return row
    raise _error("IMMORTAL_ART_FACTOR_UNSUPPORTED", "The requested Factor is not published by the selected Aspect.", aspect=aspect.get("display_name"), factor_id=factor_id)


def _burden_row(aspect: Mapping[str, Any], burden_id: str) -> Mapping[str, Any]:
    for row in aspect.get("burdens", []):
        if isinstance(row, Mapping) and row.get("burden_id") == burden_id:
            return row
    raise _error("IMMORTAL_ART_BURDEN_UNSUPPORTED", "The requested Burden is not published by the selected Aspect.", aspect=aspect.get("display_name"), burden_id=burden_id)


def _select_source(authority: Mapping[str, Any], normalized: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    rows = list(normalized["known_sources"])
    by_id = {row["record_id"]: row for row in rows}
    selected_id = normalized.get("source_record_id")
    if selected_id is not None and selected_id not in by_id:
        raise _error("IMMORTAL_ART_SOURCE_NOT_KNOWN", "The requested source record is not in the authenticated known-source set.", source_record_id=selected_id)
    aspects = _aspect_rows(authority)
    active = [row for row in aspects.values() if row.get("display_name") != "Chaos"]
    eligible: list[tuple[dict[str, Any], int]] = []
    for source in rows:
        score = min((value for value in (_source_score(source["source_tags"], aspect) for aspect in active) if value is not None), default=None)
        if score is not None:
            eligible.append((source, score))
    if selected_id is not None:
        selected = by_id[selected_id]
        if not any(row["record_id"] == selected_id for row, _score in eligible):
            raise _error("IMMORTAL_ART_SOURCE_UNSUPPORTED", "The selected source has no source-backed compatible Dao Aspect.", source_record_id=selected_id)
        return selected, next(score for row, score in eligible if row["record_id"] == selected_id)
    if not eligible:
        raise _error("IMMORTAL_ART_SOURCE_UNSUPPORTED", "No known source has a source-backed compatible Dao Aspect and complete action surface.")
    eligible.sort(key=lambda item: (item[1], item[0].get("owning_path_id") or "", item[0]["source_package_id"], item[0]["record_id"], hashlib.sha256(f"{normalized['seed']}:{item[0]['record_id']}".encode()).hexdigest()))
    ordinal = int(normalized["art_ordinal"])
    if ordinal >= len(eligible):
        raise _error("IMMORTAL_ART_SECOND_UNAVAILABLE", "The requested Art ordinal has no distinct authenticated complete source.", ordinal=ordinal, available=len(eligible))
    return eligible[ordinal][0], eligible[ordinal][1]


def _select_aspect(authority: Mapping[str, Any], normalized: Mapping[str, Any], source: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    rows = _aspect_rows(authority)
    requested = normalized.get("aspect_id")
    if requested is not None:
        aspect = rows.get(requested)
        if aspect is None:
            raise _error("IMMORTAL_ART_ASPECT_UNSUPPORTED", "The requested Dao Aspect is not active in the sealed authority.", aspect_id=requested)
        score = _source_score(source["source_tags"], aspect)
        if score is None:
            raise _error("IMMORTAL_ART_ASPECT_SOURCE_MISMATCH", "The requested Dao Aspect has no source-backed correspondence to the action.", aspect_id=requested)
        return dict(aspect), score
    # Automatic Aspect selection is constrained by the authenticated source
    # adapter's complete Factor IDs.  Broad tags can correspond to several
    # Aspects (for example a Body source can also describe healing), but they
    # cannot choose an Aspect whose sealed Factors the source cannot execute.
    # Explicit requests retain their existing Aspect/source error path above;
    # this filter applies only to the deterministic default producer.
    supported_factor_ids = {str(factor_id) for factor_id in source.get("supported_factor_ids", [])}
    choices = []
    for raw_aspect in rows.values():
        if raw_aspect.get("display_name") == "Chaos":
            continue
        if not any(
            isinstance(factor, Mapping)
            and str(factor.get("factor_id")) in supported_factor_ids
            for factor in raw_aspect.get("factors", [])
        ):
            continue
        aspect = dict(raw_aspect)
        score = _source_score(source["source_tags"], aspect)
        if score is not None:
            choices.append((aspect, score))
    if not choices:
        raise _error(
            "IMMORTAL_ART_ASPECT_UNSUPPORTED",
            "No active Dao Aspect has a sealed Factor authenticated by the source adapter.",
            supported_factor_ids=sorted(supported_factor_ids),
        )
    choices.sort(key=lambda item: (item[1], item[0].get("display_name", ""), hashlib.sha256(f"{normalized['seed']}:{item[0].get('aspect_id')}".encode()).hexdigest()))
    return choices[0][0], int(choices[0][1])


def _default_factor_ids(aspect: Mapping[str, Any], source: Mapping[str, Any]) -> list[str]:
    name = str(aspect.get("display_name", "")).casefold()
    tags = set(source["source_tags"])
    supported = set(source.get("supported_factor_ids", []))
    # These two source adapters are intentionally explicit.  A body/construct
    # or boundary tag is useful correspondence evidence, but a tag by itself
    # cannot grant the complete Factor chassis.
    if name == "creation" and "construct_puppet_body_creation" in supported and {"body", "construct", "manifest"} <= tags:
        return ["construct_puppet_body_creation"]
    if name == "domain" and "domain_lock" in supported and {"boundary", "division", "crossing"} <= tags:
        return ["domain_lock"]
    fallback = next((factor for display_name, factor in _FALLBACK_FACTORS.items() if display_name.casefold() == name), None)
    if fallback and fallback in supported and fallback in _FACTOR_SOURCE_TAGS:
        return [fallback]
    raise _error(
        "IMMORTAL_ART_FACTOR_UNSUPPORTED",
        "The source adapter did not authenticate a supported complete Factor for this action.",
        aspect=aspect.get("display_name"),
        supported_factor_ids=source.get("supported_factor_ids", []),
    )


def _route_for(authority: Mapping[str, Any], aspect_id: str, factor_id: str) -> Mapping[str, Any] | None:
    routes = ((authority.get("shared_rules") or {}).get("supported_source_routes") or [])
    return next((row for row in routes if isinstance(row, Mapping) and row.get("aspect_id") == aspect_id and row.get("factor_id") == factor_id), None)


def _correspondence(authority: Mapping[str, Any], aspect: Mapping[str, Any], source: Mapping[str, Any], factor_id: str) -> dict[str, Any]:
    route = _route_for(authority, str(aspect["aspect_id"]), factor_id)
    if factor_id not in source.get("supported_factor_ids", []):
        raise _error("IMMORTAL_ART_FACTOR_SOURCE_MISMATCH", "The source adapter did not authenticate this Factor for the selected action.", factor_id=factor_id, source_record_id=source["record_id"])
    if route is None and factor_id not in _FACTOR_SOURCE_TAGS:
        raise _error("IMMORTAL_ART_FACTOR_UNSUPPORTED", "No bounded source adapter exists for the selected Factor.", factor_id=factor_id)
    # Never substitute an Aspect-wide semantic tag set for a Factor-specific
    # capability.  Only a published route or the explicit bounded fallback
    # table can establish the required source correspondence.
    required = list(route.get("required_source_tags", [])) if route else list(_FACTOR_SOURCE_TAGS[factor_id])
    actual = set(source["source_tags"])
    required_set = {str(tag).casefold() for tag in required}
    matched = sorted(actual & required_set)
    if route is not None and factor_id in {"construct_puppet_body_creation", "domain_lock", "domain_authority"} and not required_set <= actual:
        raise _error(
            "IMMORTAL_ART_FACTOR_SOURCE_MISMATCH",
            "A specialized Factor adapter requires every source capability named by its sealed route.",
            factor_id=factor_id,
            source_record_id=source["record_id"],
            required_source_tags=sorted(required_set),
            actual_source_tags=sorted(actual),
        )
    if matched:
        label = "Direct"
        bridge_count = 0
    elif factor_id in source.get("credible_bridges", []):
        label = "Distant / Unlike"
        bridge_count = 2
    else:
        raise _error("IMMORTAL_ART_FACTOR_SOURCE_MISMATCH", "A selected Factor has no authenticated source-backed correspondence.", factor_id=factor_id, source_record_id=source["record_id"], required_source_tags=required, actual_source_tags=sorted(actual))
    return {
        "factor_id": factor_id,
        "correspondence": label,
        "bridge_factor_count": bridge_count,
        "source_tags": sorted(actual),
        "required_source_tags": sorted(required),
        "matched_source_tags": matched,
        "bridge_rule": "source.dao_aspect.opening§4:principle-correspondence" if bridge_count else None,
    }


def _realm_row(authority: Mapping[str, Any], realm: str) -> Mapping[str, Any]:
    for row in ((authority.get("shared_rules") or {}).get("realm_thresholds") or []):
        if isinstance(row, Mapping) and row.get("realm") == realm:
            return row
    raise _authority_error("The authority has no Mandate threshold for the Path Realm.", realm=realm)


def _escalation(authority: Mapping[str, Any], factor_count: int) -> tuple[int, bool]:
    table = ((authority.get("shared_rules") or {}).get("factor_escalation") or {})
    if factor_count <= 5:
        value = table.get(str(factor_count))
        if type(value) is not int:
            raise _authority_error("The factor-escalation table is incomplete.", factor_count=factor_count)
        return value, False
    return 0, True


def _package_modifier(authority: Mapping[str, Any], count: int) -> int:
    table = ((authority.get("shared_rules") or {}).get("source_package_modifier") or {})
    key = str(count) if count < 4 else "4_plus"
    value = table.get(key)
    if type(value) is not int:
        raise _authority_error("The source-package modifier table is incomplete.", count=count)
    return value


def _has_gm_review_proof(normalized: Mapping[str, Any], requirement: str) -> bool:
    """Return whether an authenticated scoped GM authority is available.

    The pure constructor has no authority-store context with which to resolve
    a GM record.  A caller-provided mapping, even when it has a valid-looking
    ID/hash/scope shape, is therefore self-attestation and cannot authorize a
    GM-only operation.  The live integration layer must establish such a
    scoped proof before constructing a future supported route.
    """
    del normalized, requirement
    return False


def _factor_application(aspect: Mapping[str, Any], factors: Sequence[Mapping[str, Any]], source: Mapping[str, Any], action: Mapping[str, Any]) -> dict[str, Any]:
    """Apply only the bounded source adapters supported by this pure stage.

    Each adapter retains the source's complete mechanics.  It adds the
    Aspect-specific operating fields required by the source chassis without
    inventing dice, targets, action capacity, or cleanup behavior.
    """
    factor_ids = [str(row["factor_id"]) for row in factors]
    if len(factor_ids) != 1:
        raise _error("IMMORTAL_ART_FACTOR_ADAPTER_UNSUPPORTED", "The bounded pure constructor supports one complete source Factor at a time.", factor_ids=factor_ids)
    factor_id = factor_ids[0]
    source_mechanics = action.get("source_mechanics") if isinstance(action.get("source_mechanics"), Mapping) else {}
    base = {
        "factor_id": factor_id,
        "mechanical_chassis": factors[0]["mechanical_chassis"],
        "factor_source": deepcopy(factors[0].get("source")),
        "source_action_preserved": True,
        "action_type": action["action_type"],
        "range": action["range"],
        "target": action["target"],
        "duration": action["duration"],
        "effect": deepcopy(action["effect"]),
        "resolution": {
            "trigger": action["trigger"],
            "trigger_frequency": action["trigger_frequency"],
            "save_or_check": action["save_or_check"],
            "attack_roll": action["attack_roll"],
            "success": action["success"],
            "failure": action["failure"],
            "counterplay": action["counterplay"],
            "cleanup": action["cleanup"],
        },
    }
    if factor_id == "hp_restoration":
        if str(aspect.get("display_name")) != "Restoration" or not {"heal", "restore"} <= set(source["source_tags"]):
            raise _error(
                "IMMORTAL_ART_FACTOR_SOURCE_MISMATCH",
                "HP Restoration requires authenticated healing and restoration source capabilities.",
                source_record_id=source["record_id"],
            )
        native_healing = action.get("effect", {}).get("healing") if isinstance(action.get("effect"), Mapping) else None
        if not isinstance(native_healing, Mapping):
            raise _error(
                "IMMORTAL_ART_FACTOR_SOURCE_MISMATCH",
                "HP Restoration requires the source's complete native healing expression.",
                source_record_id=source["record_id"],
            )
        restoration_factor = {
            "factor_id": factor_id,
            "source_chassis": deepcopy(factors[0]["mechanical_chassis"]),
            "package": {
                "formula": "PBd10",
                "die": "d10",
                "quantity": "PB",
                "target": "you only",
                "cap": "cannot exceed maximum Hit Points",
                "replacement": "The purchased Factor replaces the native 2d10/3d10 + Constitution modifier magnitude; it does not add another healing package or Constitution modifier.",
            },
            "anti_healing": "Contest existing anti-healing first.",
            "restoration_check": "d20 + Proficiency Bonus + Refinement Ability Modifier against the actual harm, effect, or anti-recovery DC.",
            "result_bands": {
                "failure_by_5": "Healing fails and exposes the actual complication, anti-recovery, or source-backed backlash.",
                "failure": "No removal occurs; the harm category or missing requirement remains known.",
                "success": "Restore one PBd10 Restoration Package, capped at maximum Hit Points, or resolve the source-backed minor-harm result.",
                "success_by_5": "Restore one additional package or resolve the source-backed minor-harm result with its linked suppression.",
                "success_by_10": "Reduce major harm only when the authenticated source supports it; otherwise establish the source-backed stable recovery route.",
            },
            "native_source_healing": deepcopy(dict(native_healing)),
        }
        base.update({
            "mode": "restoration_hp_package",
            "source_healing_preserved": deepcopy(native_healing),
            "restoration_factor": restoration_factor,
            "effective_effect": {
                "base_source_effect": deepcopy(action["effect"]),
                "restoration_factor": deepcopy(restoration_factor),
                "healing_output": "one PBd10 Restoration Package, replacing the source's native healing magnitude",
                "healing_formula": "PBd10",
            },
        })
        return base
    if factor_id == "construct_puppet_body_creation":
        if str(aspect.get("display_name")) != "Creation" or not {"body", "construct", "manifest"} <= set(source["source_tags"]):
            raise _error("IMMORTAL_ART_FACTOR_SOURCE_MISMATCH", "Creation's construct-body adapter requires authenticated body/construct/manifest source capabilities.", source_record_id=source["record_id"])
        # The published Creation chassis supplies these defaults.  A source
        # adapter may replace a value with an exact source-specific mechanic;
        # no action, movement, attack, or durability is invented here.
        frame = {
            "size": source_mechanics.get("size", "Medium unless Factor changes"),
            "duration": action["duration"],
            "ownership": source_mechanics.get("ownership", "Creator-Owned"),
            "action_capacity": source_mechanics.get("action_capacity", "none unless Commanded or Autonomous"),
            "movement": source_mechanics.get("movement", "none unless locomotion function is paid"),
            "senses": source_mechanics.get("senses", "none unless sensor function is paid"),
            "speech": source_mechanics.get("speech", "none unless voice function is paid"),
            "attacks": source_mechanics.get("attacks", "none unless attack function is paid"),
            "counterplay": source_mechanics.get("counterplay", "damage, Break Attempt, sever control, suppress Creation Layer"),
            "cleanup": source_mechanics.get("cleanup", "collapse into inert frame"),
        }
        base.update({
            "mode": "created_construct_or_puppet_body",
            "created_subject": action["target"],
            "created_subject_frame": frame,
            "source_specific_mechanics": deepcopy(dict(source_mechanics)),
            "effective_effect": {
                "base_source_effect": deepcopy(action["effect"]),
                "creation_frame": deepcopy(frame),
            },
        })
        return base
    if factor_id == "domain_lock":
        if str(aspect.get("display_name")) != "Domain" or not {"boundary", "division", "crossing"} <= set(source["source_tags"]):
            raise _error("IMMORTAL_ART_FACTOR_SOURCE_MISMATCH", "Domain Lock requires authenticated boundary/division/crossing source capabilities.", source_record_id=source["record_id"])
        lock_rule = {
            "trigger": action["trigger"],
            "check_or_save": action["save_or_check"],
            "success": action["success"],
            "failure": action["failure"],
            "failure_by_5": action["failure_by_5"],
            "counterplay": action["counterplay"],
            "cleanup": action["cleanup"],
        }
        base.update({
            "mode": "bounded_domain_lock",
            "domain_area": action.get("area"),
            "locked_relation": action["effect"],
            "crossing_resolution": deepcopy(lock_rule),
            "break_route": action["counterplay"],
            "source_specific_mechanics": deepcopy(dict(source_mechanics)),
            "effective_effect": {
                "base_source_effect": deepcopy(action["effect"]),
                "domain_lock_rule": deepcopy(lock_rule),
            },
        })
        return base
    from .native_immortal_sources import NATIVE_COMMITMENT_KIND, native_factor_application
    if source.get("feature_record_hash_kind") == NATIVE_COMMITMENT_KIND:
        return native_factor_application(aspect, factors[0], source, base)
    if source["content_type"] == "path_feature":
        expected_factor = _EXPLICIT_PATH_FEATURE_FACTORS.get(str(source.get("record_id")))
        action_source_mechanics = action.get("source_mechanics") if isinstance(action.get("source_mechanics"), Mapping) else {}
        if expected_factor != factor_id or action_source_mechanics.get("feature_id") != source.get("record_id"):
            raise _error(
                "IMMORTAL_ART_FACTOR_ADAPTER_UNSUPPORTED",
                "This Path feature has no explicit source/Factor adapter for the selected action.",
                factor_id=factor_id,
                source_record_id=source.get("record_id"),
            )
        source_record_id = str(source["record_id"])
        adapter_binding = source.get("factor_adapters", {}).get(factor_id) if isinstance(source.get("factor_adapters"), Mapping) else None
        if not isinstance(adapter_binding, Mapping) or adapter_binding.get("source_record_id") != source_record_id or adapter_binding.get("source_record_hash") != source.get("record_hash"):
            raise _error(
                "IMMORTAL_ART_FACTOR_SOURCE_MISMATCH",
                "The Path feature Factor adapter is not bound to the selected source commitment.",
                factor_id=factor_id,
                source_record_id=source_record_id,
            )
        if factor_id == "detect_presence":
            required_tags = {"detect", "diagnose"}
            if not required_tags <= set(source.get("source_tags") or []):
                raise _error(
                    "IMMORTAL_ART_FACTOR_SOURCE_MISMATCH",
                    "Detect Presence requires the source-authenticated diagnosis and detection capabilities.",
                    source_record_id=source_record_id,
                )
            detection_factor = {
                "factor_id": factor_id,
                "source_chassis": deepcopy(factors[0]["mechanical_chassis"]),
                "scope": "The source's listed target-profile readout is the complete detected category.",
                "concealment_route": "Use the source-authored equal-or-higher-authority concealment check and report concealment instead of false data on failure.",
                "per_turn_tracking": "Track the source's first attack, first Grapple, and first Joint Lock save occurrences separately.",
            }
            base.update({
                "mode": "path_feature_detect_presence",
                "source_specific_mechanics": deepcopy(dict(source_mechanics)),
                "detection_factor": detection_factor,
                "effective_effect": {
                    "base_source_effect": deepcopy(action["effect"]),
                    "detection_factor": deepcopy(detection_factor),
                },
            })
            return base
        if factor_id == "destructive_damage":
            required_tags = {"damage", "dream", "psychic"}
            if not required_tags <= set(source.get("source_tags") or []):
                raise _error(
                    "IMMORTAL_ART_FACTOR_SOURCE_MISMATCH",
                    "Destructive Damage requires the source-authenticated damage type and dream action capabilities.",
                    source_record_id=source_record_id,
                )
            factor_source = deepcopy(factors[0].get("source"))
            if not isinstance(factor_source, Mapping):
                raise _error(
                    "IMMORTAL_ART_FACTOR_SOURCE_MISMATCH",
                    "Destructive Damage requires the sealed factor definition binding.",
                    source_record_id=source_record_id,
                )
            destruction_factor = {
                "factor_id": factor_id,
                "source_chassis": deepcopy(factors[0]["mechanical_chassis"]),
                "definition": "Destructive Damage adds one standard Destruction Package to the source's legal damaging effect.",
                "definition_source": {
                    "factor_id": factor_id,
                    "display_name": "Destructive Damage",
                    "mechanical_chassis": deepcopy(factors[0]["mechanical_chassis"]),
                    "binding": factor_source,
                },
                "package": {
                    "name": "standard Destruction Package",
                    "formula": "PBd8",
                    "quantity": "Proficiency Bonus",
                    "die": "d8",
                    "damage_type": "Psychic",
                    "application": "one additional package to the source's legal damaging effect",
                    "definition_source": {**deepcopy(factor_source), "anchor": "line:70-83"},
                },
                "source_resolution": "Preserve the source Wisdom save and its failed-save and successful-save bands.",
                "damage_type": "Psychic",
                "native_damage_expression": "3d10 Psychic",
                "effective_damage_expression": "3d10 Psychic + PBd8 Psychic on a failed save; half of the combined damage on a successful save",
                "successful_save": "The source's successful-save half-damage band applies to the combined 3d10 + PBd8 Psychic expression.",
            }
            base.update({
                "mode": "path_feature_destructive_damage",
                "source_specific_mechanics": deepcopy(dict(source_mechanics)),
                "destruction_factor": destruction_factor,
                "effective_effect": {
                    "base_source_effect": deepcopy(action["effect"]),
                    "destruction_factor": deepcopy(destruction_factor),
                    "damage_expression": "3d10 Psychic + PBd8 Psychic on a failed save; half of the combined damage on a successful save",
                },
            })
            return base
    # A learned Sphere/manual/etc. source may use one of the explicit
    # complete fallback Factors authenticated by its source adapter.  The
    # source action remains the entire effect surface and the sealed Factor
    # chassis supplies the bounded upgrade semantics.
    if source["content_type"] not in {"talent", "sphere_effect", "manual_technique", "recorded_art", "forged_technique", "insight"}:
        raise _error("IMMORTAL_ART_FACTOR_ADAPTER_UNSUPPORTED", "This Factor adapter is reserved for complete learned source actions.", factor_id=factor_id)
    base.update({
        "mode": "complete_learned_source_factor",
        "source_effect": deepcopy(action["effect"]),
        "factor_resolution": deepcopy(base["resolution"]),
        "effective_effect": {
            "base_source_effect": deepcopy(action["effect"]),
            "factor_chassis": factors[0]["mechanical_chassis"],
        },
    })
    return base


def _construct_from_normalized(authority: Mapping[str, Any], normalized: Mapping[str, Any]) -> dict[str, Any]:
    source, source_selection_score = _select_source(authority, normalized)
    aspect, aspect_score = _select_aspect(authority, normalized, source)
    factor_ids = list(normalized.get("factor_ids") or _default_factor_ids(aspect, source))
    if len(factor_ids) != len(set(factor_ids)):
        raise _error("IMMORTAL_ART_FACTOR_DUPLICATE", "An Immortal Art cannot list one Factor twice.")
    factors: list[dict[str, Any]] = []
    for factor_id in factor_ids:
        row = _factor_row(aspect, factor_id)
        if type(row.get("mandate_cost")) is not int or type(row.get("cp_cost")) is not int or not str(row.get("mechanical_chassis") or "").strip():
            raise _error("IMMORTAL_ART_FACTOR_UNPUBLISHED_COST", "A selected Factor has no complete numeric mechanical chassis.", factor_id=factor_id)
        factors.append({
            "factor_id": factor_id,
            "display_name": row.get("display_name"),
            "mandate_cost": int(row["mandate_cost"]),
            "cp_cost": int(row["cp_cost"]),
            "mechanical_chassis": row.get("mechanical_chassis"),
            "source": {"source_id": aspect["source"]["source_id"], "path": aspect["source"]["path"], "anchor": f"line:{row.get('source_line')}", "source_hash": aspect["source"]["source_hash"]},
        })
    correspondences = [_correspondence(authority, aspect, source, factor_id) for factor_id in factor_ids]
    bridge_count = sum(int(row["bridge_factor_count"]) for row in correspondences)
    burden_rows: list[dict[str, Any]] = []
    stability_credit = 0
    burden_cp_credit = 0
    for burden_id in normalized.get("burdens", []):
        row = _burden_row(aspect, burden_id)
        if type(row.get("stability_credit")) is not int or type(row.get("cp_credit")) is not int:
            raise _error("IMMORTAL_ART_BURDEN_UNPUBLISHED", "A selected Burden has no numeric stability/CP credit.", burden_id=burden_id)
        burden_rows.append(dict(row))
        stability_credit += int(row["stability_credit"])
        burden_cp_credit += int(row["cp_credit"])
    # ``known_sources`` is a candidate pool.  Only the selected source is
    # consumed by this Art; unused candidates must not inflate MC, DC, or the
    # sphere/source-package count.
    source_packages = [source["source_package_id"]]
    source_package_count = len(source_packages)
    if source_package_count < 1:
        raise _error("IMMORTAL_ART_SOURCE_PACKAGE_MISSING", "An Immortal Art must retain at least one source package.")
    source_modifier = _package_modifier(authority, source_package_count)
    special_scale = int(normalized["special_scale_cost"])
    factor_count = len(factors) + bridge_count
    escalation, escalation_review = _escalation(authority, factor_count)
    gm_review = bool(escalation_review or special_scale)
    if factor_count > 5 and not _has_gm_review_proof(normalized, "factor_count_6_plus"):
        raise _error("IMMORTAL_ART_GM_REVIEW_REQUIRED", "Six or more Factors require a separately authenticated scoped GM authority record.", factor_count=factor_count)
    if source_package_count >= 4 and not _has_gm_review_proof(normalized, "source_package_count_4_plus"):
        raise _error("IMMORTAL_ART_GM_REVIEW_REQUIRED", "Four or more source packages require a separately authenticated scoped GM authority record.", source_package_count=source_package_count)
    if special_scale and not _has_gm_review_proof(normalized, "special_scale"):
        raise _error("IMMORTAL_ART_GM_REVIEW_REQUIRED", "A special-scale Art requires a separately authenticated scoped GM authority record.")
    realm = str(normalized["path_realm"])
    threshold_row = _realm_row(authority, realm)
    threshold = int(threshold_row["mandate_threshold"])
    aspect_cost = int(aspect["mandate_cost"])
    aspect_cp = int(aspect["cp_modifier"])
    factor_cost = sum(int(row["mandate_cost"]) for row in factors)
    factor_cp = sum(int(row["cp_cost"]) for row in factors)
    bridge_cost = bridge_count
    mc = aspect_cost + factor_cost + bridge_cost + source_modifier + special_scale
    pressure = 2 * max(0, mc - threshold)
    sphere_count = 1
    aspect_count = 1
    dc_floor = 10 + mc + sphere_count + aspect_count
    dc = max(dc_floor, dc_floor + escalation + pressure - stability_credit)
    resource_name = _RESOURCE_BY_PATH[normalized["path_kind"]]
    source_cost = int(source["action_surface"]["resource_cost"])
    cp_gross = source_cost + aspect_cp + factor_cp + bridge_count
    cp_final = max(1, cp_gross - burden_cp_credit)
    automatic_policy = {
        "mode": "initial_factory_materialization",
        "roll": None,
        "outcome": "accepted_after_full_rederivation",
        "payment": "reported_requirement_only",
        "training_choice_cost": 0,
    }
    action = deepcopy(source["action_surface"])
    factor_application = _factor_application(aspect, factors, source, action)
    action.update({
        "source_record_id": source["record_id"],
        "source_record_hash": source["record_hash"],
        "source_packages_used": source_packages,
        "source_spheres_used": sphere_count,
        "source_binding": deepcopy(source["source"]),
        "aspect_id": aspect["aspect_id"],
        "factor_ids": list(factor_ids),
        "gm_review_required": gm_review,
        "resource_name": resource_name,
        # The source's printed cost is retained in the step-1 snapshot.  The
        # executable Art pays its final sealed CP cost after Aspect/Factors.
        "base_source_resource_cost": source_cost,
        "resource_cost": cp_final,
        "factor_application": factor_application,
    })
    request_hash = sha256_json(normalized)
    identity_material = {
        "schema": IMMORTAL_ART_SCHEMA,
        "project_id": normalized["project_id"],
        "request_sha256": request_hash,
        "seed": normalized["seed"],
        "ordinal": normalized["art_ordinal"],
        "source_record_id": source["record_id"],
        "source_record_hash": source["record_hash"],
        "aspect_id": aspect["aspect_id"],
        "factor_ids": list(factor_ids),
    }
    art_id = IMMORTAL_ART_ID_PREFIX + sha256_json(identity_material)[:40]
    display_name = f"{source['display_name']} — {aspect['display_name']} Immortal Art"
    source_step = {
        "record_id": source["record_id"],
        "record_hash": source["record_hash"],
        "display_name": source["display_name"],
        "content_type": source["content_type"],
        "source": deepcopy(source["source"]),
        # Keep the complete normalized source snapshot in the Art.  Stage 2
        # re-authenticates this exact row against construction.request rather
        # than accepting a display-only subset that could omit ownership or
        # Factor adapter commitments.
        "sphere_id": source["sphere_id"],
        "sphere_name": source["sphere_name"],
        "owning_path_id": source["owning_path_id"],
        "source_package_id": source["source_package_id"],
        "source_tags": list(source["source_tags"]),
        "supported_factor_ids": list(source["supported_factor_ids"]),
        "factor_adapters": deepcopy(source["factor_adapters"]),
        "source_dependencies": deepcopy(source["source_dependencies"]),
        "credible_bridges": list(source["credible_bridges"]),
        "acquired": source["acquired"],
        "acquired_at_cl": source["acquired_at_cl"],
        "acquisition": deepcopy(source["acquisition"]),
        "progression": deepcopy(source["progression"]),
        "action_surface": deepcopy(source["action_surface"]),
        "published_text": source["published_text"],
    }
    if source.get("feature_record_hash_kind") is not None:
        source_step["feature_record_hash_kind"] = source["feature_record_hash_kind"]
    steps = [
        {"step": 1, "name": "source_effect", "payload": source_step},
        {"step": 2, "name": "dao_aspect", "payload": {"aspect_id": aspect["aspect_id"], "display_name": aspect["display_name"], "mandate_cost": aspect_cost, "cp_modifier": aspect_cp, "source": deepcopy(aspect["source"]), "correspondence": aspect_score}},
        {"step": 3, "name": "factor_package", "payload": {"factors": deepcopy(factors), "factor_count": factor_count}},
        {"step": 4, "name": "principle_correspondence", "payload": {"rows": deepcopy(correspondences), "bridge_factor_count": bridge_count}},
        {"step": 5, "name": "burdens", "payload": {"rows": deepcopy(burden_rows), "stability_credit": stability_credit, "cp_credit": burden_cp_credit}},
        {"step": 6, "name": "mandate_complexity", "payload": {"aspect_cost": aspect_cost, "factor_cost": factor_cost, "bridge_factor_cost": bridge_cost, "source_package_modifier": source_modifier, "special_scale_cost": special_scale, "final": mc}},
        {"step": 7, "name": "realm_threshold", "payload": {"path_realm": realm, "threshold": threshold, "source": deepcopy(dict(threshold_row))}},
        {"step": 8, "name": "heaven_pressure", "payload": {"formula": "2 * max(0, mandate_complexity - mandate_threshold)", "final": pressure}},
        {"step": 9, "name": "factor_escalation", "payload": {"factor_count": factor_count, "final": escalation, "gm_review_required": escalation_review}},
        {"step": 10, "name": "refinement_dc", "payload": {"formula": "max(10 + MC + source_spheres + aspects, minimum + escalation + pressure - stability_credit)", "minimum": dc_floor, "path_ability": normalized["key_ability"], "path_ability_modifier": normalized["key_ability_modifier"], "final": dc}},
        {"step": 11, "name": "activation_cp", "payload": {"formula": "max(1, base_source_cp + aspect_cp + factor_cp + bridge_cp - burden_cp_credit)", "base_source_cp": source_cost, "base_source_resource": resource_name, "aspect_cp": aspect_cp, "factor_cp": factor_cp, "bridge_cp": bridge_count, "burden_cp_credit": burden_cp_credit, "final": cp_final}},
        {"step": 12, "name": "action_surface", "payload": deepcopy(action)},
    ]
    art = {
        "schema": IMMORTAL_ART_SCHEMA,
        "art_id": art_id,
        "immortal_art_id": art_id,
        "display_name": display_name,
        "name": display_name,
        "owner_project_id": normalized["project_id"],
        "cl_created": normalized["cl"],
        "pb_at_creation": normalized["pb"],
        "realm": realm,
        "path_id": normalized["path_id"],
        "path_name": normalized["path_name"],
        "path_kind": normalized["path_kind"],
        "key_ability": normalized["key_ability"],
        "source_record_id": source["record_id"],
        "source_record_hash": source["record_hash"],
        "source": source_step,
        "source_packages_used": source_packages,
        "source_spheres_used": sphere_count,
        "dao_aspect": {"aspect_id": aspect["aspect_id"], "display_name": aspect["display_name"], "mandate_cost": aspect_cost, "cp_modifier": aspect_cp, "source": deepcopy(aspect["source"])},
        "factors": factors,
        "burdens": burden_rows,
        "correspondence": correspondences,
        "mandate_complexity": mc,
        "mandate_complexity_breakdown": steps[5]["payload"],
        "mandate_threshold": threshold,
        "heaven_pressure": pressure,
        "factor_escalation": escalation,
        "refinement_dc": dc,
        "activation_cp": cp_final,
        "activation_cp_breakdown": steps[10]["payload"],
        "research_days": 5 * mc,
        "material_cost_gp": 250 * mc * mc,
        "action_surface": action,
        "gm_review_required": gm_review,
        "automatic_construction": automatic_policy,
        "steps": steps,
        "construction": {
            "schema": IMMORTAL_ART_REQUEST_SCHEMA,
            "seed": normalized["seed"],
            "ordinal": normalized["art_ordinal"],
            "request": deepcopy(dict(normalized)),
            "request_sha256": request_hash,
            "authority_seal_sha256": authority.get("seal_sha256"),
            "identity_material": identity_material,
            "automatic_policy": automatic_policy,
            "source_selection_score": source_selection_score,
            "rule_ids": [
                "tianxia.immortal_art.construction.v1",
                "tianxia.immortal_art.principle_correspondence.v1",
                "tianxia.immortal_art.refinement.v1",
                "source.core_rules_reference.v0_2c§3.2:lines:725-735",
            ],
        },
    }
    return art


IMMORTAL_ART_REFINEMENT_SCHEMA = "TianxiaFoundry.ImmortalArtRefinement.v1"
IMMORTAL_ART_REFINEMENT_AUTHORITY_SCHEMA = "TianxiaFoundry.ImmortalArtRefinementAuthority.v1"
IMMORTAL_ART_REFINEMENT_AUTHORITY_VERSION = "server_owned_pre_provider.v1"
IMMORTAL_ART_REFINEMENT_AUTHORITY_ISSUER = "tianxia.foundry.character_creation"
IMMORTAL_ART_REFINEMENT_MAX_ATTEMPTS = 8


def immortal_art_refinement_authority() -> dict[str, str]:
    """Return the durable issuer/version marker for new creator refinement proofs."""
    return {
        "schema": IMMORTAL_ART_REFINEMENT_AUTHORITY_SCHEMA,
        "version": IMMORTAL_ART_REFINEMENT_AUTHORITY_VERSION,
        "issuer": IMMORTAL_ART_REFINEMENT_AUTHORITY_ISSUER,
    }


def validate_immortal_art_refinement(
    refinement: Mapping[str, Any],
    *,
    event_id: str,
    record_id: str,
    record_hash: str,
    cl: int,
    path_id: str,
    key_ability: str,
    ability_modifier: int,
    pb: int,
    dc: int,
    research_days: int,
    material_cost_gp: int,
    require_derived_fields: bool = False,
    require_authority_binding: bool = False,
) -> dict[str, Any]:
    """Validate the bounded Refinement Check proof for one Immortal Art.

    Opening rules section 4 and 5: the Refinement Check is d20 + Proficiency
    Bonus + Path ability modifier against the Refinement DC; failure leaves
    the Art unstabilized and loses half the research or materials; success
    refines the Art.  Section 6 fixes research at 5 days per Mandate
    Complexity and materials at 250 gp per Mandate Complexity squared.  The
    constructed Art supplies those published figures; this helper accepts only
    the bounded d20 and payment inputs and derives every result, so a refined
    Art cannot be created by authoring a total or a result.  The last attempt
    must succeed: an unrefined Art is never known.
    """

    def reject(message: str, **details: Any) -> FoundryError:
        return FoundryError(
            "IMMORTAL_ART_REFINEMENT_INVALID",
            message,
            details={"record_id": record_id, **details},
        )

    if not isinstance(refinement, Mapping):
        raise reject("An Immortal Art needs a typed Refinement Check proof.")
    if refinement.get("schema") != IMMORTAL_ART_REFINEMENT_SCHEMA:
        raise reject("The Immortal Art refinement proof declares an unsupported schema.")
    authority = refinement.get("authority")
    expected_authority = immortal_art_refinement_authority()
    if require_authority_binding and authority != expected_authority:
        raise reject("A new creator Immortal Art proof must carry its server-owned authority binding.")
    if authority is not None and authority != expected_authority:
        raise reject("The Immortal Art refinement proof carries an unsupported authority binding.")
    if refinement.get("mode") != "creator_generated_history" or refinement.get("scope") != "initial_creation":
        raise reject("Immortal Art refinement provenance must be scoped to initial creation.")
    if refinement.get("observed_play") is not False or refinement.get("live_currency_debit") is not False:
        raise reject("Creator-generated refinement history cannot claim observed play or a live currency debit.")
    if refinement.get("target_cl") != cl or refinement.get("record_id") != record_id or refinement.get("record_hash") != record_hash:
        raise reject("The refinement proof is bound to a different creation CL or record snapshot.")
    if refinement.get("path_id") != path_id or refinement.get("key_ability") != key_ability:
        raise reject("The refinement proof is bound to a different Path or Refinement ability.")
    if refinement.get("pb") not in (None, pb) or refinement.get("ability_modifier") not in (None, ability_modifier) or refinement.get("dc") not in (None, dc):
        raise reject("The refinement proof contains authored or stale check inputs.")
    if require_derived_fields and (
        refinement.get("pb") != pb or refinement.get("ability_modifier") != ability_modifier or refinement.get("dc") != dc
    ):
        raise reject("The persisted refinement proof is missing a server-derived check input.")

    research = refinement.get("research")
    required_hours = research_days * 8
    if (
        not isinstance(research, Mapping)
        or research.get("required_days") != research_days
        or research.get("meaningful_training_hours") != required_hours
        or research.get("completed") is not True
    ):
        raise reject("Refinement research must cover the exact published duration.", expected_days=research_days, expected_hours=required_hours)
    materials = refinement.get("materials")
    if (
        not isinstance(materials, Mapping)
        or materials.get("required_gp") != material_cost_gp
        or materials.get("paid_gp") != material_cost_gp
        or materials.get("payment_complete") is not True
    ):
        raise reject("Refinement materials must record the exact published cost.", expected_gp=material_cost_gp)
    completion = refinement.get("completion")
    if (
        not isinstance(completion, Mapping)
        or completion.get("mode") != "creator_generated_history"
        or completion.get("scope") != "initial_creation"
        or completion.get("record_id") != record_id
        or completion.get("record_hash") != record_hash
    ):
        raise reject("Refinement completion provenance is incomplete.")
    if completion.get("event_id") not in (None, event_id):
        raise reject("Refinement completion provenance is bound to a different event.")

    attempts = refinement.get("attempts")
    if not isinstance(attempts, list) or not attempts or len(attempts) > IMMORTAL_ART_REFINEMENT_MAX_ATTEMPTS:
        raise reject(f"Refinement requires one to {IMMORTAL_ART_REFINEMENT_MAX_ATTEMPTS} ordered attempts.")
    half_materials = material_cost_gp // 2
    half_hours = required_hours // 2
    allowed_input_keys = {"attempt_id", "retry_of_attempt_id", "check_die_result", "research_time_hours", "materials_paid_gp"}
    derived_keys = {
        "target_record_id", "target_record_hash", "character_cl", "check_ability", "pb", "ability_modifier", "dc",
        "computed_check_total", "result", "margin", "research_time_hours_expected", "materials_paid_gp_expected",
    }
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    previous: str | None = None
    for index, raw in enumerate(attempts):
        if not isinstance(raw, Mapping):
            raise reject("Every refinement attempt must be an object.", attempt_index=index)
        attempt_id = raw.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id.strip() or attempt_id in seen:
            raise reject("Every refinement attempt needs a unique identity.", attempt_index=index)
        if raw.get("retry_of_attempt_id") != previous:
            raise reject("Refinement retries must form one ordered chain.", attempt_index=index)
        die = raw.get("check_die_result")
        if type(die) is not int or not 1 <= die <= 20:
            raise reject("Refinement accepts only a bounded d20 result.", attempt_index=index)
        supplied = set(raw)
        authored = supplied - allowed_input_keys - derived_keys
        if authored:
            raise reject("A refinement attempt contains unsupported authored fields.", attempt_index=index, fields=sorted(authored))
        if not require_derived_fields and supplied & derived_keys:
            raise reject("A refinement attempt may supply only its bounded die and retry/payment inputs.", attempt_index=index, fields=sorted(supplied & derived_keys))
        total = die + pb + ability_modifier
        result = "success" if total >= dc else "failure"
        expected_hours = required_hours if result == "success" else half_hours
        expected_gp = material_cost_gp if result == "success" else half_materials
        if raw.get("research_time_hours") != expected_hours or raw.get("materials_paid_gp") != expected_gp:
            raise reject("Refinement research and material payment must match the derived attempt result.", attempt_index=index, expected_hours=expected_hours, expected_gp=expected_gp)
        if result == "success" and index != len(attempts) - 1:
            raise reject("A successful refinement ends the attempt chain.", attempt_index=index)
        derived = {
            "attempt_id": attempt_id,
            "retry_of_attempt_id": previous,
            "target_record_id": record_id,
            "target_record_hash": record_hash,
            "character_cl": cl,
            "check_ability": key_ability,
            "pb": pb,
            "ability_modifier": ability_modifier,
            "dc": dc,
            "check_die_result": die,
            "computed_check_total": total,
            "result": result,
            "margin": total - dc,
            "research_time_hours": expected_hours,
            "materials_paid_gp": expected_gp,
        }
        if require_derived_fields and any(raw.get(key) != value for key, value in derived.items() if key in raw):
            raise reject("A persisted refinement attempt disagrees with its derived result.", attempt_index=index)
        normalized.append(derived)
        seen.add(attempt_id)
        previous = attempt_id
    if normalized[-1]["result"] != "success":
        raise reject("The Art is not stabilized: the final Refinement Check failed, so the Art cannot be known.")
    return {
        **{key: deepcopy(value) for key, value in refinement.items() if key != "attempts"},
        "pb": pb,
        "ability_modifier": ability_modifier,
        "dc": dc,
        "check_formula": "d20 + proficiency_bonus + path_ability_modifier",
        "attempts": normalized,
        "completion": {**deepcopy(dict(completion)), "event_id": event_id},
    }


def immortal_art_id(art: Mapping[str, Any]) -> str:
    construction = art.get("construction") if isinstance(art, Mapping) else None
    identity = construction.get("identity_material") if isinstance(construction, Mapping) else None
    if not isinstance(identity, Mapping):
        raise _error("IMMORTAL_ART_ID_INVALID", "The Immortal Art has no identity material.")
    return IMMORTAL_ART_ID_PREFIX + sha256_json(identity)[:40]


def construct_immortal_art(authority: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    """Construct one deterministic, fully typed Immortal Art."""
    if not isinstance(authority, Mapping) or authority.get("schema_version") != IMMORTAL_ART_AUTHORITY_SCHEMA:
        raise _authority_error("The supplied authority is not the sealed Immortal Art authority.")
    normalized = normalize_immortal_art_request(request)
    return _construct_from_normalized(authority, normalized)


def compile_immortal_art(
    authority: Mapping[str, Any],
    art: Mapping[str, Any],
    *,
    cl: int | None = None,
    pb: int | None = None,
    known_source_ids: set[str] | None = None,
    known_sources: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recompute the entire Art and refuse any semantic or identity drift."""
    if not isinstance(art, Mapping) or art.get("schema") != IMMORTAL_ART_SCHEMA:
        raise _error("IMMORTAL_ART_SCHEMA_INVALID", "The Immortal Art declares an unsupported schema.")
    construction = art.get("construction")
    if not isinstance(construction, Mapping) or not isinstance(construction.get("request"), Mapping):
        raise _error("IMMORTAL_ART_CONSTRUCTION_INVALID", "The Immortal Art has no normalized construction request.")
    if construction.get("authority_seal_sha256") != authority.get("seal_sha256"):
        raise _error("IMMORTAL_ART_AUTHORITY_MISMATCH", "The Art was constructed under a different sealed authority.")
    request = deepcopy(dict(construction["request"]))
    if construction.get("request_sha256") != sha256_json(request):
        raise _error("IMMORTAL_ART_REQUEST_HASH_MISMATCH", "The normalized construction request hash does not match its contents.")
    if cl is not None and request.get("cl") != cl:
        raise _error("IMMORTAL_ART_REALM_MISMATCH", "The Art creation CL differs from the compile point.", cl=cl)
    if pb is not None and request.get("pb") != pb:
        raise _error("IMMORTAL_ART_PB_MISMATCH", "The Art creation PB differs from the compile point.", pb=pb)
    if known_source_ids is not None and art.get("source_record_id") not in known_source_ids:
        raise _error("IMMORTAL_ART_SOURCE_NOT_KNOWN", "The Art source is absent from the authenticated known-source set.", source_record_id=art.get("source_record_id"))
    if known_sources is not None:
        source_id = art.get("source_record_id")
        external_rows = [
            row for row in known_sources
            if isinstance(row, Mapping)
            and _first(row, "record_id", "source_record_id", "talent_id", "feature_id", "item_id") == source_id
        ]
        if len(external_rows) != 1:
            raise _error("IMMORTAL_ART_SOURCE_NOT_KNOWN", "The Art source is absent from the supplied authenticated source snapshots.", source_record_id=art.get("source_record_id"))
        normalized_request = normalize_immortal_art_request(request)
        expected_source = next(
            (row for row in normalized_request["known_sources"] if row["record_id"] == source_id),
            None,
        )
        if expected_source is None:
            raise _error("IMMORTAL_ART_SOURCE_NOT_KNOWN", "The Art source is absent from its normalized construction request.", source_record_id=source_id)
        try:
            external_source = _normalize_source(
                external_rows[0],
                0,
                path_kind=normalized_request["path_kind"],
                target_cl=int(normalized_request["cl"]),
                owning_path_cl=int(normalized_request["owning_path_cl"]),
            )
        except FoundryError as exc:
            raise _error(
                "IMMORTAL_ART_SOURCE_SNAPSHOT_MISMATCH",
                "The supplied source snapshot cannot be normalized under the construction request.",
                source_record_id=source_id,
                cause=exc.code,
            ) from exc
        if canonical_json(external_source) != canonical_json(expected_source):
            raise _error(
                "IMMORTAL_ART_SOURCE_SNAPSHOT_MISMATCH",
                "The supplied source snapshot differs from the source used by the normalized construction request.",
                source_record_id=source_id,
            )
    expected = construct_immortal_art(authority, request)
    if canonical_json(expected) != canonical_json(dict(art)):
        raise _error("IMMORTAL_ART_REDERIVATION_MISMATCH", "The stored Immortal Art differs from complete sealed re-derivation.", art_id=art.get("art_id"))
    if art.get("art_id") != immortal_art_id(art) or art.get("immortal_art_id") != art.get("art_id"):
        raise _error("IMMORTAL_ART_ID_MISMATCH", "The Immortal Art identity is not derived from its sealed construction request.", art_id=art.get("art_id"))
    return {
        "immortal_art_id": art["art_id"],
        "mandate_complexity": art["mandate_complexity"],
        "mandate_threshold": art["mandate_threshold"],
        "heaven_pressure": art["heaven_pressure"],
        "factor_escalation": art["factor_escalation"],
        "refinement_dc": art["refinement_dc"],
        "activation_cp": art["activation_cp"],
        "research_days": art["research_days"],
        "material_cost_gp": art["material_cost_gp"],
        "gm_review_required": art["gm_review_required"],
    }


reconstruct_immortal_art_from_record = construct_immortal_art


__all__ = [
    "IMMORTAL_ART_AUTHORITY_SCHEMA",
    "IMMORTAL_ART_FEATURE_COMMITMENT_SCHEMA",
    "IMMORTAL_ART_AUTHORITY_FILENAME",
    "IMMORTAL_ART_FILENAME",
    "IMMORTAL_ART_ID_PREFIX",
    "IMMORTAL_ART_KIND",
    "IMMORTAL_ART_PACK_ID",
    "IMMORTAL_ART_PACK_VERSION",
    "IMMORTAL_ART_REQUEST_SCHEMA",
    "IMMORTAL_ART_SCHEMA",
    "compile_immortal_art",
    "construct_immortal_art",
    "immortal_art_authority_path",
    "immortal_art_id",
    "immortal_art_progression_child_hash",
    "load_immortal_art_authority",
    "normalize_immortal_art_request",
    "reconstruct_immortal_art_from_record",
]
