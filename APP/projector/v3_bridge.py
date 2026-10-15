from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core import FoundryError, canonical_json, sha256_file, sha256_json
from canonical_catalog.service import _realm_for_cl
from character_creation.choice_snapshot import valid_choice_snapshot
from character_creation.starting_proficiency_authority import (
    _tool_key,
    validate_starting_proficiency_choices,
)
from contracts.canonical import canonical_event_hash, canonical_record_hash
from sphere_component_authority import normalize_sphere_automatic_components
from creation_training_authority import (
    CREATION_TRAINING_KINDS,
    CREATION_TRAINING_BONUS_KIND,
    CREATION_TRAINING_SPHERE_KIND,
    CREATION_TRAINING_TALENT_KIND,
    canonical_trained_choice,
    validate_trained_choice_shape,
)
from projector.path_feature_statistics import load_path_feature_statistic_formulas, resolve_armor_class, statistic_formulas_path
from stage2.formulas import FormulaError, evaluate_formula
from recorded_art_authority import RECORDED_ART_CONSTRUCTION_KIND

ZERO_HASH = "0" * 64
V3 = "TianxiaFoundry.AdvancementEvent.v3"
_TITLE_MAX_LENGTH = 120
_TITLE_FINAL_LOCK_FIELD = "character.identity.final_title"
_TITLE_RAW_LOCK_FIELD = "character.identity.title"
_TITLE_DERIVED_BINDING_SCHEMA = "TianxiaFoundry.ServerDerivedDescriptiveFields.v1"
_STARTING_PROFICIENCY_LOCK_FIELD = "character.choices.starting_proficiencies"
_STARTING_PROFICIENCY_LOCK_ID = "lock.cg1.character-choices-starting-proficiencies"
_STARTING_PROFICIENCY_LOCK_SCHEMA = "TianxiaFoundry.ServerDerivedStartingProficiencies.v1"
_STARTING_PROFICIENCY_FIELDS = (
    "path_skill_choices_by_path_id",
    "origin_skill_choices_by_origin_id",
    "background_language_choices_by_background_id",
)
_STARTING_PROFICIENCY_SLOTS = (
    "path_choice",
    "background_choice",
    "origin_insight_choice",
)
_CORE_ABILITY_IDS = frozenset(("STR", "DEX", "CON", "INT", "WIS", "CHA"))
_SKILL_ABILITY_MAP = {
    "Acrobatics": "DEX",
    "Animal Handling": "WIS",
    "Arcana": "INT",
    "Athletics": "STR",
    "Deception": "CHA",
    "History": "INT",
    "Insight": "WIS",
    "Intimidation": "CHA",
    "Investigation": "INT",
    "Medicine": "WIS",
    "Nature": "INT",
    "Perception": "WIS",
    "Performance": "CHA",
    "Persuasion": "CHA",
    "Religion": "INT",
    "Sleight of Hand": "DEX",
    "Stealth": "DEX",
    "Survival": "WIS",
}
_TRAINING_SOURCE_ACCESS_CALCULATION_SCHEMA = (
    "TianxiaFoundry.Stage2TrainingSourceAccessCalculation.v1"
)
_TRAINING_SOURCE_CONTENT_TYPE_MAP = {
    "source_document": "other",
    "sphere": "other",
    "tradition": "sect_lineage",
    "item": "item_source",
    "companion": "spirit_relation",
    "manual": "manual",
    "martial_manual": "manual",
    "manual_expression": "manual",
}
_TRAINING_SOURCE_TARGET_CONTENT_TYPES = {
    "new_sphere": "sphere",
    "known_sphere_talent": "talent",
    "recorded_art": "recorded_art",
}


def _read_sealed(path: Path, *, schema_version: str, mismatch_code: str) -> dict[str, Any]:
    if not path.is_file():
        raise FoundryError(mismatch_code, "A required sealed C2A-R.1 authority file is missing.", details={"path": str(path)})
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FoundryError(mismatch_code, "A required sealed C2A-R.1 authority file is unreadable.", details={"path": str(path), "error": str(exc)}) from exc
    if value.get("schema_version") != schema_version:
        raise FoundryError(mismatch_code, "A required C2A-R.1 authority file declares an unsupported schema.", details={"path": str(path), "schema_version": value.get("schema_version")})
    seal = value.get("seal_sha256")
    unsigned = {key: item for key, item in value.items() if key != "seal_sha256"}
    if seal != sha256_json(unsigned):
        raise FoundryError(mismatch_code, "A required C2A-R.1 authority file failed its canonical seal.", details={"path": str(path)})
    return value


def _locks(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for lock in project.get("user_locks") or []:
        field = lock.get("field")
        if isinstance(field, str):
            result[field] = lock
    return result


def _title_text(value: Any, *, field: str, project_id: str) -> str:
    if not isinstance(value, str):
        raise FoundryError(
            "PROJECTION_CHARACTER_TITLE_INVALID",
            "A present character title lock must contain a string value.",
            details={"field": field, "project_id": project_id},
        )
    title = value.strip()
    if not title or len(title) > _TITLE_MAX_LENGTH:
        raise FoundryError(
            "PROJECTION_CHARACTER_TITLE_INVALID",
            "A present character title lock must be nonblank and no longer than 120 characters.",
            details={"field": field, "project_id": project_id, "max_length": _TITLE_MAX_LENGTH},
        )
    return title


def _is_sha256_text(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except (TypeError, ValueError):
        return False
    return True


def _server_derived_title(lock: Any, *, project_id: str) -> str:
    if not isinstance(lock, dict):
        raise FoundryError(
            "PROJECTION_CHARACTER_TITLE_INVALID",
            "The server-derived character title lock is malformed.",
            details={"field": _TITLE_FINAL_LOCK_FIELD, "project_id": project_id},
        )
    payload = lock.get("value")
    binding = payload.get("binding") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or not isinstance(binding, dict):
        raise FoundryError(
            "PROJECTION_CHARACTER_TITLE_INVALID",
            "The server-derived character title lock must retain its evidence binding.",
            details={"field": _TITLE_FINAL_LOCK_FIELD, "project_id": project_id},
        )
    expected_binding = {
        "schema": _TITLE_DERIVED_BINDING_SCHEMA,
        "project_id": project_id,
        "phase": "server-derived",
    }
    if any(binding.get(key) != value for key, value in expected_binding.items()):
        raise FoundryError(
            "PROJECTION_CHARACTER_TITLE_INVALID",
            "The server-derived character title lock is bound to a different project or phase.",
            details={"field": _TITLE_FINAL_LOCK_FIELD, "project_id": project_id},
        )
    if (
        not isinstance(binding.get("run_id"), str)
        or not binding["run_id"].strip()
        or not _is_sha256_text(binding.get("request_sha256"))
        or not _is_sha256_text(binding.get("response_sha256"))
    ):
        raise FoundryError(
            "PROJECTION_CHARACTER_TITLE_INVALID",
            "The server-derived character title lock has incomplete evidence binding.",
            details={"field": _TITLE_FINAL_LOCK_FIELD, "project_id": project_id},
        )
    if (
        lock.get("lock_id") != "lock.cg1.character-identity-final_title"
        or not isinstance(lock.get("source"), str)
        or lock["source"] != f"cg1-owner-descriptive:{binding['run_id']}:server-derived"
    ):
        raise FoundryError(
            "PROJECTION_CHARACTER_TITLE_INVALID",
            "The server-derived character title lock does not carry the expected server source marker.",
            details={"field": _TITLE_FINAL_LOCK_FIELD, "project_id": project_id},
        )
    return _title_text(payload.get("value"), field=_TITLE_FINAL_LOCK_FIELD, project_id=project_id)


def _resolve_project_title(project: dict[str, Any]) -> tuple[str | None, str]:
    """Resolve only authenticated project title locks for generic projection.

    A final title is a server-derived lock emitted after delegated response
    validation.  A raw title is an explicit owner lock.  Neither may be
    inferred from a name, concept, catalogue record, or free-form project
    text.  The omission marker is retained for historical/current proof
    fixtures that intentionally have no title.
    """

    project_id = project.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise FoundryError(
            "PROJECTION_CHARACTER_TITLE_INVALID",
            "A title-bearing generic project requires a non-empty project identity.",
            details={"field": _TITLE_RAW_LOCK_FIELD},
        )
    project_id = project_id.strip()
    title_rows = {
        field: [
            lock
            for lock in project.get("user_locks") or []
            if isinstance(lock, dict) and lock.get("field") == field
        ]
        for field in (_TITLE_RAW_LOCK_FIELD, _TITLE_FINAL_LOCK_FIELD)
    }
    for field, rows in title_rows.items():
        if len(rows) > 1:
            raise FoundryError(
                "PROJECTION_CHARACTER_TITLE_CONFLICT",
                "A character title lock is duplicated in the project authority.",
                details={"field": field, "project_id": project_id},
            )
    raw_present = bool(title_rows[_TITLE_RAW_LOCK_FIELD])
    final_present = bool(title_rows[_TITLE_FINAL_LOCK_FIELD])
    raw_title: str | None = None
    final_title: str | None = None
    if raw_present:
        raw_lock = title_rows[_TITLE_RAW_LOCK_FIELD][0]
        if not isinstance(raw_lock, dict):
            raise FoundryError(
                "PROJECTION_CHARACTER_TITLE_INVALID",
                "The raw character title lock is malformed.",
                details={"field": _TITLE_RAW_LOCK_FIELD, "project_id": project_id},
            )
        raw_title = _title_text(raw_lock.get("value"), field=_TITLE_RAW_LOCK_FIELD, project_id=project_id)
    if final_present:
        final_title = _server_derived_title(title_rows[_TITLE_FINAL_LOCK_FIELD][0], project_id=project_id)
    if raw_title is not None and final_title is not None and raw_title != final_title:
        raise FoundryError(
            "PROJECTION_CHARACTER_TITLE_CONFLICT",
            "The raw owner title and server-derived final title disagree.",
            details={"project_id": project_id},
        )
    title = final_title or raw_title
    if title is None:
        return None, "OPTIONAL_OMITTED_BY_OWNER"
    return title, "OWNER_LOCKED" if raw_title is not None else "SELECTED"


def _authenticated_fixture_prefix(
    project: dict[str, Any],
    events: list[dict[str, Any]],
    fixture: dict[str, Any],
    fixture_path: Path,
) -> bool:
    """Recognize the owner-ratified historical prefix, not just its hashes."""
    fixture_id = fixture.get("fixture_id")
    selections = fixture.get("selections") or {}
    prefix = fixture.get("required_prefix") or {}
    if not isinstance(fixture_id, str) or not isinstance(prefix, dict):
        return False
    expected_fields = {
        "character.identity.display_name": selections.get("display_name"),
        "character.choices.qi_cultivation_skills": selections.get("qi_cultivation_skills"),
        "character.choices.street_hardened": selections.get("street_hardened"),
        "character.choices.language": selections.get("language"),
    }
    expected_revision = prefix.get("revision")
    locks = _locks(project)
    marker = f"owner-ratified:{fixture_id}:{sha256_file(fixture_path)}"
    if not isinstance(expected_revision, int) or project.get("revision") != expected_revision + 1:
        return False
    for index, (field, value) in enumerate(expected_fields.items(), start=1):
        lock = locks.get(field)
        if not isinstance(lock, dict) or (
            lock.get("lock_id") != f"lock.c2ar1.{index}"
            or lock.get("created_revision") != project.get("revision")
            or lock.get("value") != value
            or lock.get("source") != marker
        ):
            return False
    count = prefix.get("event_count")
    return (
        isinstance(count, int)
        and count > 0
        and len(events) == count
        and events[count - 1].get("event_hash") == prefix.get("event_head")
    )


def _authenticated_raw_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return the locked catalog record carried by the factory raw projection."""

    factory = ((record.get("compatibility") or {}).get("factory") or {}) if isinstance(record, dict) else {}
    raw_projection = factory.get("raw_projection") if isinstance(factory, dict) else None
    raw_projection = raw_projection if isinstance(raw_projection, dict) else {}
    raw_record = raw_projection.get("raw_record")
    return raw_record if isinstance(raw_record, dict) else {}


def _display(record: dict[str, Any]) -> tuple[str, str]:
    """Return (one-line text, full rules text) for one locked catalog record.

    The catalog normalizer fills ``display_projection.full_description`` with
    the first line of the printed entry only ("Action Type: Bonus Action"),
    which is not the rules text a human needs.  The locked raw record carries
    the complete text, so it is preferred whenever it is longer -- the same
    rule the earned-Path-feature projection already applies.  Only the full
    text changes; the projection's short text stays the one-line summary, and
    no hash or sealed identity is touched.
    """

    projection = record.get("display_projection") or {}
    short = projection.get("short_description")
    full = projection.get("full_description")
    name = record.get("display_name") or record.get("name") or record.get("record_id")
    if not isinstance(short, str) or not short.strip():
        short = str(name)
    if not isinstance(full, str) or not full.strip():
        full = short
    raw_record = _authenticated_raw_record(record)
    for key in ("effective_rules_text", "player_rules_text", "full_description", "full_exact_source_text"):
        candidate = raw_record.get(key)
        if isinstance(candidate, str) and candidate.strip() and len(candidate.strip()) > len(full.strip()):
            full = candidate
    return short.strip(), full.strip()


def _packet_id(event: dict[str, Any]) -> str:
    return f"packet.stage2.{int(event['sequence']):03d}.{event['event_hash'][:16]}"


def _event_provenance(event: dict[str, Any], record: dict[str, Any], contract: dict[str, Any], destinations: list[str], transformation: str) -> dict[str, Any]:
    binding = event["content_binding"]
    sources = deepcopy(event.get("source_evidence") or [])
    stage2 = (record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
    return {
        "provenance_unit": "canonical_advancement_event",
        "event_id": event["event_id"],
        "event_hash": event["event_hash"],
        "event_sequence": event["sequence"],
        "record_id": record["record_id"],
        "record_hash": record["record_hash"],
        "pack_id": binding["pack_id"],
        "pack_version": binding["pack_version"],
        "pack_hash": binding["pack_hash"],
        "canonical_sources": sources,
        "stage2_rule_id": event["advancement"]["calculation"]["rule_id"],
        "projection_contract_id": contract["contract_id"],
        "projection_contract_hash": sha256_json({k: v for k, v in contract.items() if k != "seal_sha256"}),
        "stage2_normalization_authority": deepcopy(contract["stage2_authority_pack"]),
        "exact_source_map": deepcopy(contract["exact_source_map"]),
        "destination_pointers": sorted(destinations),
        "transformation_kind": transformation,
        "authority_complete": stage2.get("authority_complete") is True,
    }


def _lock_provenance(lock: dict[str, Any], fixture_path: Path, destinations: list[str], transformation: str) -> dict[str, Any]:
    return {
        "provenance_unit": "owner_project_lock",
        "lock_id": lock["lock_id"],
        "lock_field": lock["field"],
        "created_revision": lock["created_revision"],
        "source": lock.get("source", "local-user"),
        "fixture_contract_sha256": sha256_file(fixture_path),
        "destination_pointers": sorted(destinations),
        "transformation_kind": transformation,
    }


def _baseline_provenance(rule: dict[str, Any], pack: dict[str, Any], pack_path: Path, destinations: list[str], trace: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "provenance_unit": "core_character_baseline_rule",
        "rule_id": rule["rule_id"],
        "authority_classification": rule["authority_classification"],
        "source": deepcopy(rule["source"]),
        "baseline_pack_id": pack["pack_id"],
        "baseline_pack_version": pack["version"],
        "baseline_pack_sha256": sha256_file(pack_path),
        "destination_pointers": sorted(destinations),
        "transformation_kind": "DIRECT_TYPED_VALUE" if "typed_value" in rule else "SAFE_FORMULA_EVALUATION",
    }
    if trace is not None:
        result["formula_trace"] = trace
    return result


def _capability_entry(record: dict[str, Any], selected_at_cl: int, event: dict[str, Any]) -> dict[str, Any]:
    record_id = record["record_id"]
    content_type = record.get("content_type", "unknown")
    _, full = _display(record)
    is_executable_surface = content_type in {"talent", "path_feature", "subpath_feature", "origin_insight"}
    combat = "UNSUPPORTED" if is_executable_surface else "NOT_APPLICABLE"
    ai = "BLOCKED_BY_DEPENDENCY" if is_executable_surface else "NOT_APPLICABLE"
    surfaces: list[str] = []
    lowered = full.lower()
    for label, terms in {
        "BURN": ("burn", "burning"),
        "FIRE_TERRAIN": ("fire terrain", "terrain"),
        "REACTION": ("reaction",),
        "CONCENTRATION": ("concentration",),
        "MOVEMENT": ("move", "push", "pull", "speed"),
        "DAMAGE_PREVENTION": ("reduce damage", "prevent damage"),
        "RESOURCE": (" qi", "cost:"),
        "MODIFIER": ("advantage", "+3 ac", "bonus"),
        "PROCEDURE": ("trigger:", "save", "attack roll"),
    }.items():
        if any(term in lowered for term in terms):
            surfaces.append(label)
    return {
        "record_id": record_id,
        "record_hash": record["record_hash"],
        "record_type": content_type,
        "selected_at_cl": selected_at_cl,
        "event_id": event["event_id"],
        "coverage": {
            "advancement": "SUPPORTED",
            "character_sheet": "PARTIAL" if is_executable_surface else "SUPPORTED",
            "gm_display": "PARTIAL" if is_executable_surface else "SUPPORTED",
            "combat_execution": combat,
            "ai_policy": ai,
        },
        "demonstrated_surfaces": sorted(set(surfaces)),
        "display_only_not_execution_authority": is_executable_surface,
    }


def _dynamic_display_section(record: dict[str, Any], packets: list[dict[str, Any]]) -> tuple[str, str]:
    content_type = str(record.get("content_type") or "")
    record_id = str(record.get("record_id") or "")
    kinds = {str(packet.get("advancement_kind") or "") for packet in packets}
    if record_id.startswith("tianxia.c1a.none."):
        return "explicit_none", "Explicit None"
    if content_type == "source_document":
        return "source_authority", "Authority Source"
    if content_type in {"background", "origin_insight"}:
        return "background_origin", "Background" if content_type == "background" else "Origin Insight"
    if content_type in {"path", "subpath"}:
        return "path_subpath", content_type.replace("_", " ").title()
    if content_type == "sphere":
        return "spheres", "Sphere"
    if content_type == "manual":
        return "manuals", "Manual"
    if content_type == "recorded_art":
        return "recorded_arts", "Recorded Art"
    if content_type == "cultivation_insight":
        return "insights", "Insight"
    if content_type == "talent":
        if "background_talent_acquisition" in kinds:
            return "background_talent", "Background Talent"
        return "talents", "Talent"
    if content_type == "path_feature" and "ability_score_change" in kinds:
        return "advancement_features", "Path Feature"
    if content_type in {"path_feature", "subpath_feature"}:
        return "path_features", content_type.replace("_", " ").title()
    return "other", content_type.replace("_", " ").title() or "Selected Record"


def _component_display_source(component: dict[str, Any], parent_source: dict[str, Any], parent_record_id: str) -> dict[str, str]:
    """Map the CAT3 source-matrix identity to the sheet display-source shape."""
    source = component.get("source") if isinstance(component.get("source"), dict) else {}
    path = source.get("path") or source.get("source_path") or parent_source.get("path")
    anchor = source.get("anchor") or source.get("source_anchor") or f"{parent_source.get('anchor', parent_record_id)}:{component.get('component_id')}"
    source_hash = (
        source.get("source_hash")
        or source.get("source_file_sha256")
        or source.get("compendium_sha256")
        or parent_source.get("source_hash")
    )
    if not all(isinstance(value, str) and value for value in (path, anchor, source_hash)):
        raise FoundryError(
            "CHARACTER_SHEET_DESCRIPTION_UNPROVEN",
            "A Sphere automatic component lacks exact source identity.",
            details={"parent_sphere_id": parent_record_id, "component_id": component.get("component_id"), "source": source},
        )
    return {"path": path, "anchor": anchor, "source_hash": source_hash}


def _sphere_record_with_event_authority(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Bind the immutable compiled Sphere packet to the locked display record.

    Some project-lock adapters retain the CAT3 packet only in the event's
    calculation output, while others retain it in the raw catalog record.
    The event packet is already normalized and content-bound by Stage 2, so
    using it here keeps projector output independent of that storage detail.
    """
    packet = (
        (event.get("advancement") or {})
        .get("calculation", {})
        .get("outputs", {})
        .get("automatic_component_authority")
    )
    if not isinstance(packet, dict):
        return record
    result = deepcopy(record)
    result["automatic_component_authority"] = deepcopy(packet)
    return result


def _explicit_subpath_owner(event: dict[str, Any], record: dict[str, Any]) -> str:
    """Return the Subpath owner only when every explicit mirror agrees.

    ``owning_path_id`` on the locked catalog record is authoritative.  The
    record's parent mirror, typed Stage 2 mirrors, and event output may confirm
    that owner, but none of them may provide one when it is absent.  This is a
    module-level boundary so the same fail-closed rule can be regression-tested
    independently of the larger v3 fixture.
    """
    owner_path_id = record.get("owning_path_id")
    if not isinstance(owner_path_id, str) or not owner_path_id:
        raise FoundryError(
            "PROJECTION_SUBPATH_OWNER_MISSING",
            "A Subpath projection requires an explicit owning_path_id in the locked record.",
            details={"event_id": event.get("event_id"), "record_id": record.get("record_id")},
        )
    authority = ((record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {})
    outputs = ((event.get("advancement") or {}).get("calculation") or {}).get("outputs") or {}
    mirrors = {
        "record_parent_path_id": record.get("parent_path_id"),
        "stage2_owning_path_id": authority.get("owning_path_id"),
        "stage2_parent_path_id": authority.get("parent_path_id"),
        "output_parent_path_id": outputs.get("parent_path_id"),
    }
    conflicts = {
        key: value
        for key, value in mirrors.items()
        if value is not None and (not isinstance(value, str) or value != owner_path_id)
    }
    if conflicts:
        raise FoundryError(
            "PROJECTION_SUBPATH_OWNER_MISMATCH",
            "A Subpath projection contains conflicting explicit and mirrored Path ownership.",
            details={
                "event_id": event.get("event_id"),
                "record_id": record.get("record_id"),
                "owning_path_id": owner_path_id,
                "mirrors": mirrors,
                "conflicts": conflicts,
            },
        )
    return owner_path_id


def _validate_generic_subpath_owners(
    subpath_events: list[dict[str, Any]],
    event_records: dict[str, dict[str, Any]],
    selected_path_ids: list[str],
) -> dict[str, str]:
    """Validate every generic Subpath owner against the selected Path set.

    Stage 2 validates each acquisition while reducing its own causal state. The
    projector repeats the cross-event invariant independently because the v3
    projection is also a durable consumer boundary: a valid individual event
    must not let one owner escape the selected Path set or be reused by a
    second Subpath event.
    """
    selected = set(selected_path_ids)
    owners_by_event: dict[str, str] = {}
    event_ids_by_owner: dict[str, list[str]] = {}
    for event in subpath_events:
        event_id = event.get("event_id")
        record = event_records.get(event_id) or {}
        owner_path_id = _explicit_subpath_owner(event, record)
        if owner_path_id not in selected:
            raise FoundryError(
                "PROJECTION_SUBPATH_OWNER_NOT_SELECTED",
                "A generic Subpath acquisition is owned by a Path that was not selected in the projection.",
                details={
                    "event_id": event_id,
                    "record_id": record.get("record_id"),
                    "owning_path_id": owner_path_id,
                    "selected_path_ids": list(selected_path_ids),
                },
            )
        owners_by_event[event_id] = owner_path_id
        event_ids_by_owner.setdefault(owner_path_id, []).append(event_id)
    duplicates = {
        owner_path_id: event_ids
        for owner_path_id, event_ids in event_ids_by_owner.items()
        if len(event_ids) > 1
    }
    if duplicates:
        raise FoundryError(
            "PROJECTION_SUBPATH_OWNER_DUPLICATE",
            "A generic projection contains more than one Subpath acquisition for one selected Path owner.",
            details={
                "duplicates": duplicates,
                "event_ids": [event_id for event_ids in duplicates.values() for event_id in event_ids],
            },
        )
    return owners_by_event


def _validated_subpath_events(
    raw_events: list[dict[str, Any]] | None,
    *,
    generic_project: bool,
    milestone_target_cl: int,
) -> list[dict[str, Any]]:
    """Return the authenticated Subpath events required by this projection.

    A generic project below the first Subpath milestone may legitimately have
    no event yet.  Every other projection shape retains the strict
    source-backed event requirement.
    """
    events = sorted(
        raw_events or [],
        key=lambda event: (int(event["sequence"]), event["subject"]["record_id"]),
    )
    if events or (generic_project and milestone_target_cl < 3):
        return events
    raise FoundryError(
        "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
        "The projection requires at least one authenticated Subpath or Tradition acquisition.",
        details={"kind": "subpath_acquisition", "count": 0, "target_cl": milestone_target_cl},
    )


def _validated_cl4_selection_authority(
    score_changes: list[dict[str, Any]] | None,
    insight_events: list[dict[str, Any]] | None,
    *,
    generic_project: bool,
    target_cl: int,
) -> None:
    """Require the CL4 choice authority only once that milestone is due.

    Generic initial-creation projections at CL1–CL3 have no ability-score or
    ordinary Insight event yet; the first such selection authority is due at
    CL4. Historical and fixture projections retain the established strict
    requirement regardless of target level.
    """

    if score_changes or insight_events:
        return
    if generic_project and 0 < target_cl < 4:
        return
    raise FoundryError(
        "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
        "The projection requires an ability-score change or an ordinary Cultivation Insight event to represent the CL4 selection authority.",
        details={"ability_score_change_count": 0, "cultivation_insight_count": 0},
    )


def _earned_event_metadata(event: dict[str, Any], packet_id: str) -> dict[str, Any]:
    """Expose the canonical identity of an earned-feature event.

    This is presentation provenance only.  The event has already passed the
    v3 registry, chain, hash, and Stage 2 binding checks before this helper is
    called, so the display contract can retain the exact causal identity
    without copying an untrusted event payload wholesale.
    """

    advancement = event.get("advancement") or {}
    target_cl = advancement.get("target_cl")
    sequence = event.get("sequence")
    event_id = event.get("event_id")
    event_hash = event.get("event_hash")
    kind = advancement.get("kind")
    if (
        not isinstance(event_id, str)
        or not event_id
        or not isinstance(event_hash, str)
        or len(event_hash) != 64
        or not isinstance(sequence, int)
        or sequence < 1
        or not isinstance(target_cl, int)
        or target_cl < 0
        or not isinstance(kind, str)
        or not kind
        or not isinstance(packet_id, str)
        or not packet_id
    ):
        raise FoundryError(
            "PROJECTION_EARNED_FEATURE_EVENT_INVALID",
            "An earned Path or Subpath feature lacks a complete canonical event identity.",
            details={"event_id": event_id, "record_id": (event.get("subject") or {}).get("record_id")},
        )
    return {
        "event_id": event_id,
        "event_hash": event_hash,
        "sequence": sequence,
        "kind": kind,
        "target_cl": target_cl,
        "packet_id": packet_id,
    }



def _authenticated_path_feature_payload(record: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the authenticated Path-index feature payload from one record.

    ``NonSphereAuthorityService.project_locked_path_feature_catalog_record``
    places the complete feature leaf under the raw projection's
    ``path_feature`` key before canonical normalization.  Older catalog
    projections instead used ``raw_projection.raw_record``.  Both locations
    are accepted only after their identity and Path ownership agree with the
    canonical record and its Stage 2 authority; the projected wrapper itself
    is never treated as a feature leaf.
    """

    if not isinstance(record, dict) or record.get("content_type") != "path_feature":
        return None
    factory = ((record.get("compatibility") or {}).get("factory") or {})
    raw_projection = factory.get("raw_projection") if isinstance(factory, dict) else None
    raw_projection = raw_projection if isinstance(raw_projection, dict) else {}
    stage2 = factory.get("stage2_authority") if isinstance(factory, dict) else None
    stage2 = stage2 if isinstance(stage2, dict) else {}
    record_id = record.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise FoundryError(
            "PROJECTION_EARNED_FEATURE_AUTHORITY_INVALID",
            "An earned Path feature lacks a canonical record identity.",
            details={"record_id": record_id},
        )
    stage2_record_id = stage2.get("feature_record_id")
    if stage2_record_id is not None and stage2_record_id != record_id:
        raise FoundryError(
            "PROJECTION_EARNED_FEATURE_AUTHORITY_INVALID",
            "The Path feature Stage 2 authority names a different feature record.",
            details={"record_id": record_id, "authority_feature_record_id": stage2_record_id},
        )
    expected_path_id = stage2.get("path_id")
    if not isinstance(expected_path_id, str) or not expected_path_id:
        expected_path_id = record.get("owning_path_id") or record.get("parent_path_id")
    if not isinstance(expected_path_id, str) or not expected_path_id:
        expected_path_id = record_id.split(".feature.", 1)[0] if ".feature." in record_id else None

    candidates: list[tuple[str, dict[str, Any]]] = []

    def add_candidate(label: str, value: Any) -> None:
        if isinstance(value, dict):
            candidates.append((label, value))

    add_candidate("raw_projection.path_feature", raw_projection.get("path_feature"))
    raw_record = raw_projection.get("raw_record")
    add_candidate("raw_projection.raw_record", raw_record)
    if isinstance(raw_record, dict):
        add_candidate("raw_projection.raw_record.path_feature", raw_record.get("path_feature"))
        add_candidate("raw_projection.raw_record.feature", raw_record.get("feature"))

    if not candidates:
        return None

    expected_source = record.get("source") if isinstance(record.get("source"), dict) else {}
    expected_kind = stage2.get("feature_kind")
    expected_thresholds = stage2.get("granted_at_cl")
    if isinstance(expected_thresholds, int) and not isinstance(expected_thresholds, bool):
        expected_thresholds = [expected_thresholds]
    expected_thresholds = (
        tuple(value for value in expected_thresholds if type(value) is int)
        if isinstance(expected_thresholds, list)
        else ()
    )
    expected_minimum = stage2.get("minimum_cl")
    expected_shared_rule = stage2.get("shared_rule_id")

    def source_value(source: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = source.get(key)
            if value is not None:
                return value
        return None

    for label, candidate in candidates:
        candidate_id = candidate.get("canonical_id") or candidate.get("record_id") or candidate.get("id")
        if candidate_id != record_id:
            continue
        candidate_path = (
            candidate.get("path_id")
            or candidate.get("owning_path_id")
            or candidate.get("parent_path_id")
        )
        if expected_path_id and candidate_path is not None and candidate_path != expected_path_id:
            continue
        if expected_kind is not None and candidate.get("feature_kind") is not None and candidate.get("feature_kind") != expected_kind:
            continue
        candidate_thresholds = candidate.get("granted_at_cl")
        if isinstance(candidate_thresholds, int) and not isinstance(candidate_thresholds, bool):
            candidate_thresholds = [candidate_thresholds]
        if candidate_thresholds is not None:
            if not isinstance(candidate_thresholds, list) or any(type(value) is not int for value in candidate_thresholds):
                continue
            if expected_thresholds and tuple(candidate_thresholds) != expected_thresholds:
                continue
        if expected_minimum is not None and candidate.get("minimum_cl") is not None and candidate.get("minimum_cl") != expected_minimum:
            continue
        if expected_shared_rule is not None and candidate.get("shared_rule_id") is not None and candidate.get("shared_rule_id") != expected_shared_rule:
            continue

        candidate_source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
        candidate_path_value = source_value(candidate_source, ("path", "factory_source_path", "source_path"))
        candidate_hash_value = source_value(candidate_source, ("source_hash", "source_file_sha256", "file_sha256"))
        if candidate_path_value is None:
            candidate_path_value = source_value(candidate, ("factory_source_path", "source_path"))
        if candidate_hash_value is None:
            candidate_hash_value = source_value(candidate, ("source_hash", "source_file_sha256", "file_sha256"))
        if candidate_path_value is not None and expected_source.get("path") is not None and candidate_path_value != expected_source.get("path"):
            continue
        if candidate_hash_value is not None and expected_source.get("source_hash") is not None and candidate_hash_value != expected_source.get("source_hash"):
            continue
        return candidate

    raise FoundryError(
        "PROJECTION_EARNED_FEATURE_AUTHORITY_INVALID",
        "The complete Path feature payload is not bound to its canonical record, Path, and Stage 2 authority.",
        details={
            "record_id": record_id,
            "path_id": expected_path_id,
            "candidate_locations": [label for label, _candidate in candidates],
        },
    )


def _required_feature_level(record: dict[str, Any], actual_path_level: int) -> int:
    """Choose the printed threshold corresponding to one feature occurrence."""

    raw_record = _authenticated_path_feature_payload(record)
    candidates: Any = raw_record.get("granted_at_cl") if isinstance(raw_record, dict) else None
    if candidates is None:
        authority = (((record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {})
        candidates = authority.get("minimum_cl")
    if candidates is None:
        candidates = record.get("minimum_cl")
    if isinstance(candidates, int) and not isinstance(candidates, bool):
        values = [candidates]
    elif isinstance(candidates, list):
        values = [value for value in candidates if isinstance(value, int) and not isinstance(value, bool)]
    else:
        values = []
    values = sorted({value for value in values if value > 0})
    if not values:
        raise FoundryError(
            "PROJECTION_EARNED_FEATURE_THRESHOLD_INVALID",
            "An earned Path feature lacks an authenticated printed Path-level threshold.",
            details={"record_id": record.get("record_id"), "granted_at_cl": candidates},
        )
    exact = [value for value in values if value == actual_path_level]
    if exact:
        return exact[0]
    prior = [value for value in values if value <= actual_path_level]
    if prior:
        return max(prior)
    raise FoundryError(
        "PROJECTION_EARNED_FEATURE_THRESHOLD_INVALID",
        "An earned Path feature was emitted before its authenticated printed threshold.",
        details={"record_id": record.get("record_id"), "actual_path_level": actual_path_level, "granted_at_cl": values},
    )


def _record_feature_source(record: dict[str, Any]) -> dict[str, Any]:
    """Return the locked Path feature's complete source-backed display data."""

    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    if not all(isinstance(source.get(key), str) and source.get(key) for key in ("path", "anchor", "source_hash")):
        raise FoundryError(
            "PROJECTION_EARNED_FEATURE_SOURCE_INVALID",
            "An earned Path feature lacks exact locked source identity.",
            details={"record_id": record.get("record_id"), "source": source},
        )
    _short, full = _display(record)
    raw_record = _authenticated_path_feature_payload(record)
    # A few older locked cards carry only a display name in display_projection.
    # Prefer the authenticated effective rules text whenever it is present; the
    # original source text can be longer while describing superseded rules.
    effective_text = raw_record.get("effective_rules_text") if isinstance(raw_record, dict) else None
    source_text = raw_record.get("source_rules_text") if isinstance(raw_record, dict) else None
    if isinstance(effective_text, str) and effective_text.strip():
        full = effective_text
    elif isinstance(source_text, str) and len(source_text.strip()) > len(full.strip() if isinstance(full, str) else ""):
        full = source_text
    if not isinstance(full, str) or not full.strip():
        raise FoundryError(
            "PROJECTION_EARNED_FEATURE_SOURCE_INVALID",
            "An earned Path feature lacks complete source-backed display text.",
            details={"record_id": record.get("record_id")},
        )
    return {
        "source": deepcopy(source),
        "source_text": full,
        "full_description": full,
        "full_description_source": "locked_path_feature_record",
        "source_hash": source["source_hash"],
        "source_file_sha256": source["source_hash"],
        "factory_source_path": source["path"],
        "anchor": source["anchor"],
    }


def _progression_feature_source(
    feature_id: str,
    feature: dict[str, Any],
    *,
    factory_root: Path,
) -> dict[str, Any]:
    """Resolve one authenticated Subpath progression section exactly."""

    source = feature.get("source") if isinstance(feature.get("source"), dict) else {}
    required = ("factory_source_path", "source_file_sha256", "line_start", "line_end", "section_sha256")
    if (
        not all(isinstance(source.get(key), str) and source.get(key) for key in ("factory_source_path", "source_file_sha256", "section_sha256"))
        or any(type(source.get(key)) is not int or source.get(key) < 1 for key in ("line_start", "line_end"))
        or source["line_start"] > source["line_end"]
    ):
        raise FoundryError(
            "PROJECTION_EARNED_FEATURE_SOURCE_INVALID",
            "A selected Subpath progression feature lacks a complete exact source locator.",
            details={"feature_id": feature_id, "source": source, "required": required},
        )
    from character_creation.constructed_arts.sources import published_section

    text = published_section(factory_root, source)
    if not isinstance(text, str) or not text:
        raise FoundryError(
            "PROJECTION_EARNED_FEATURE_SOURCE_INVALID",
            "A selected Subpath progression feature could not be resolved from the installed authenticated source.",
            details={"feature_id": feature_id, "source": source},
        )
    source_binding = deepcopy(source)
    source_binding.update({
        "path": source["factory_source_path"],
        "anchor": f"line:{source['line_start']}-{source['line_end']}",
        "source_hash": source["section_sha256"],
        "source_file_sha256": source["source_file_sha256"],
    })
    return {
        "source": source_binding,
        "source_text": text,
        "full_description": text,
        "full_description_source": "authenticated_subpath_progression_section",
        "source_hash": source["section_sha256"],
        "source_file_sha256": source["source_file_sha256"],
        "factory_source_path": source["factory_source_path"],
        "anchor": f"line:{source['line_start']}-{source['line_end']}",
        "line_start": source["line_start"],
        "line_end": source["line_end"],
        "section_sha256": source["section_sha256"],
    }


def _earned_feature_occurrence(
    *,
    feature_id: str,
    display_name: str,
    feature_record_hash: str,
    required_path_level: int,
    acquired_at_path_level: int,
    acquisition_event: dict[str, Any],
    attainment_event: dict[str, Any],
    source_packet_ids: list[str],
    parent_record_id: str,
    parent_record_hash: str,
    owning_path_id: str,
    parent_kind: str,
    source_data: dict[str, Any],
    components: list[Any] | None = None,
    minimum_realm_band: Any = None,
    source_cl_basis: Any = None,
    selection: dict[str, Any] | None = None,
    derived_feature_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    acquisition_event_id = acquisition_event["event_id"]
    occurrence = {
        "occurrence_id": f"feature-occurrence.{acquisition_event_id}.{feature_id}",
        "feature_id": feature_id,
        "display_name": display_name,
        "parent_kind": parent_kind,
        "parent_record_id": parent_record_id,
        "parent_record_hash": parent_record_hash,
        "parent_subpath_id": parent_record_id if parent_kind == "subpath" else None,
        "parent_subpath_record_id": parent_record_id if parent_kind == "subpath" else None,
        "owning_path_id": owning_path_id,
        "required_path_level": required_path_level,
        "acquired_at_path_level": acquired_at_path_level,
        "acquired_at_character_cl": acquisition_event["target_cl"],
        "acquisition_event": deepcopy(acquisition_event),
        "attainment_event": deepcopy(attainment_event),
        "acquisition_event_id": acquisition_event_id,
        "acquisition_event_hash": acquisition_event["event_hash"],
        "attainment_event_id": attainment_event["event_id"],
        "attainment_event_hash": attainment_event["event_hash"],
        "event_id": acquisition_event_id,
        "event_hash": acquisition_event["event_hash"],
        "event_sequence": acquisition_event["sequence"],
        "source_packet_ids": list(source_packet_ids),
        "feature_record_hash": feature_record_hash,
        "derived_feature_hash": sha256_json({
            "parent_record_id": parent_record_id,
            "parent_record_hash": parent_record_hash,
            "feature_id": feature_id,
            "feature_record_hash": feature_record_hash,
        }),
        "components": deepcopy(components or []),
        "minimum_realm_band": minimum_realm_band,
        "source_cl_basis": source_cl_basis,
        "source_backed": True,
        "mechanical_identity": feature_id,
        "mechanically_stacks": False,
        "stacking": "duplicate_occurrences_preserved_without_mechanical_stacking",
        **deepcopy(source_data),
    }
    if selection is not None:
        occurrence["selection"] = deepcopy(selection)
    if derived_feature_snapshot is not None:
        occurrence["derived_feature_snapshot"] = deepcopy(derived_feature_snapshot)
    return occurrence


def _build_earned_feature_occurrences(
    *,
    path_events: list[dict[str, Any]],
    level_events: list[dict[str, Any]],
    score_change_events: list[dict[str, Any]],
    subpath_events: list[dict[str, Any]],
    event_records: dict[str, dict[str, Any]],
    locked_records: dict[str, dict[str, Any]],
    packet_by_event: dict[str, str],
    selected_path_ids: list[str],
    factory_root: Path | None,
    insight_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Derive earned Path/Subpath feature displays from sealed causal history."""

    # Existing direct reducer fixtures predate the installed Factory source
    # context.  They retain their historical shape; production ProjectionService
    # always supplies the configured installed root and takes this strict path.
    if factory_root is None:
        return []

    selected_paths = set(selected_path_ids)
    attainments_by_path: dict[str, list[dict[str, Any]]] = {path_id: [] for path_id in selected_paths}
    for event in path_events:
        path_id = (event.get("subject") or {}).get("record_id")
        if isinstance(path_id, str) and path_id in selected_paths:
            attainments_by_path[path_id].append({
                "path_level": 0,
                "event": event,
                "metadata": _earned_event_metadata(event, packet_by_event[event["event_id"]]),
            })

    automatic_rows: list[dict[str, Any]] = []
    for event in level_events:
        advancement = event.get("advancement") or {}
        outputs = ((advancement.get("calculation") or {}).get("outputs") or {})
        target_cl = advancement.get("target_cl")
        native_entries = outputs.get("native_path_progressions")
        if native_entries is None:
            entries = [{**(outputs.get("path_progression_authority") or {}), "automatic_feature_record_ids": outputs.get("automatic_feature_record_ids") or []}]
        else:
            if not isinstance(native_entries, list) or len(native_entries) != len(selected_paths) or {entry.get("path_id") for entry in native_entries} != selected_paths:
                raise FoundryError("PROJECTION_EARNED_FEATURE_PATH_ATTAINMENT_INVALID", "Native progression does not account for exactly the selected Paths.")
            entries = native_entries
        for path_authority in entries:
            automatic_ids = [value for value in path_authority.get("automatic_feature_record_ids") or [] if isinstance(value, str) and value]
            path_id = path_authority.get("path_id")
            path_level = path_authority.get("cl")
            if not automatic_ids and not isinstance(path_id, str):
                continue
            if (
                not isinstance(path_id, str) or path_id not in selected_paths
                or type(path_level) is not int or path_level < 1
                or type(target_cl) is not int or target_cl < 1
                or (native_entries is not None and path_level != target_cl)
            ):
                raise FoundryError(
                    "PROJECTION_EARNED_FEATURE_PATH_ATTAINMENT_INVALID",
                    "A level feature grant lacks authenticated owning-Path attainment.",
                    details={"event_id": event.get("event_id"), "path_progression_authority": path_authority},
                )
            metadata = _earned_event_metadata(event, packet_by_event[event["event_id"]])
            attainment = {"path_level": path_level, "event": event, "metadata": metadata}
            attainments_by_path.setdefault(path_id, []).append(attainment)
            automatic_rows.append({"event": event, "path_id": path_id, "path_level": path_level, "automatic_ids": automatic_ids, "metadata": metadata})

    choice_events = [
        event for event in [*score_change_events, *(insight_events or [])]
        if isinstance(event, dict)
    ]
    choice_by_cl: dict[int, list[dict[str, Any]]] = {}
    choice_by_subject_cl: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for choice_event in choice_events:
        metadata = _earned_event_metadata(
            choice_event,
            packet_by_event[choice_event["event_id"]],
        )
        target_cl = metadata["target_cl"]
        subject_id = (choice_event.get("subject") or {}).get("record_id")
        choice_row = {"event": choice_event, "metadata": metadata}
        choice_by_cl.setdefault(target_cl, []).append(choice_row)
        if isinstance(subject_id, str) and subject_id:
            choice_by_subject_cl.setdefault((subject_id, target_cl), []).append(choice_row)

    def choice_allowed_kinds(feature_record: dict[str, Any], owning_path_level: int) -> set[str]:
        stage2 = (((feature_record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {})
        raw_record = _authenticated_path_feature_payload(feature_record)
        # The Path record's allowed_kinds authorizes the level-advance subject
        # event.  A shared ASI/Insight milestone is a separate, sealed choice
        # authority and therefore must be identified from its exact published
        # rule and milestone list rather than by broadening allowed_kinds.
        if (
            isinstance(raw_record, dict)
            and raw_record.get("feature_kind") == "advancement_choice"
            and raw_record.get("shared_rule_id") == "tianxia.shared.advancement.ability_score_improvement_or_cultivation_insight"
            and owning_path_level in {
                value for value in raw_record.get("granted_at_cl") or []
                if type(value) is int
            }
        ):
            return {"ability_score_change", "cultivation_insight_acquisition"}
        allowed = {
            value for value in stage2.get("allowed_kinds") or []
            if isinstance(value, str)
        }
        if allowed:
            return allowed
        return set()

    choice_assignments: dict[str, tuple[str, int, str]] = {}

    def choice_interval(automatic_row: dict[str, Any]) -> tuple[int, int | None]:
        """Return the sealed event interval belonging to one level grant."""

        grant_sequence = int(automatic_row["metadata"]["sequence"])
        later_grants = [
            int(other["metadata"]["sequence"])
            for other in automatic_rows
            if int(other["metadata"]["sequence"]) > grant_sequence
        ]
        return grant_sequence, min(later_grants) if later_grants else None

    def in_choice_interval(choice_row: dict[str, Any], interval: tuple[int, int | None]) -> bool:
        sequence = int(choice_row["metadata"]["sequence"])
        grant_sequence, next_grant_sequence = interval
        return sequence > grant_sequence and (
            next_grant_sequence is None or sequence < next_grant_sequence
        )

    def claim_choice(choice_row: dict[str, Any], automatic_row: dict[str, Any], feature_id: str) -> None:
        event_id = choice_row["metadata"]["event_id"]
        occurrence_key = (
            automatic_row["path_id"],
            int(automatic_row["metadata"]["sequence"]),
            feature_id,
        )
        prior = choice_assignments.get(event_id)
        if prior is not None:
            raise FoundryError(
                "PROJECTION_EARNED_FEATURE_CHOICE_AMBIGUOUS",
                "An authenticated choice event was associated with more than one earned feature occurrence.",
                details={"event_id": event_id, "prior_occurrence": prior, "occurrence": occurrence_key},
            )
        choice_assignments[event_id] = occurrence_key

    def choice_selection(
        automatic_row: dict[str, Any],
        feature_id: str,
        feature_record: dict[str, Any],
        owning_path_level: int,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """Bind one real choice event to its matching printed Path grant."""

        target_cl = automatic_row["metadata"]["target_cl"]
        interval = choice_interval(automatic_row)
        allowed = choice_allowed_kinds(feature_record, owning_path_level)
        candidates = [
            choice
            for choice in choice_by_subject_cl.get((feature_id, target_cl), [])
            if in_choice_interval(choice, interval)
        ]
        if len(candidates) > 1:
            raise FoundryError(
                "PROJECTION_EARNED_FEATURE_CHOICE_AMBIGUOUS",
                "A Path choice feature has multiple authenticated choice events in its grant interval.",
                details={"feature_id": feature_id, "target_cl": target_cl, "interval": interval},
            )
        if not candidates:
            level_outputs = automatic_row["event"]["advancement"]["calculation"]["outputs"]
            if level_outputs.get("native_path_progressions") is not None and (level_outputs.get("path_progression_authority") or {}).get("path_id") != automatic_row["path_id"]:
                # Both Paths gain their printed feature; the shared global
                # milestone has one choice attached to its representative.
                return None, []
            # A feature-independent Insight subject is bound only to choice
            # events in this grant's sealed interval and only when this exact
            # automatic grant is the sole compatible shared-choice feature.
            compatible_ids = []
            for candidate_id in automatic_row["automatic_ids"]:
                candidate_record = locked_records.get(candidate_id)
                if (
                    isinstance(candidate_record, dict)
                    and candidate_id not in compatible_ids
                    and choice_by_cl.get(target_cl)
                    and any(
                        candidate["metadata"]["kind"] in choice_allowed_kinds(
                            candidate_record,
                            automatic_row["path_level"],
                        )
                        for candidate in choice_by_cl[target_cl]
                        if in_choice_interval(candidate, interval)
                    )
                ):
                    compatible_ids.append(candidate_id)
            if compatible_ids != [feature_id]:
                return None, []
            candidates = [
                choice
                for choice in choice_by_cl.get(target_cl, [])
                if in_choice_interval(choice, interval)
                and choice["metadata"]["kind"] in allowed
            ]
            if not candidates:
                return None, []
            if len(candidates) > 1:
                raise FoundryError(
                    "PROJECTION_EARNED_FEATURE_CHOICE_AMBIGUOUS",
                    "A feature-independent choice has multiple authenticated events in its grant interval.",
                    details={"feature_id": feature_id, "target_cl": target_cl, "interval": interval},
                )
        if candidates[0]["metadata"]["kind"] not in allowed:
            return None, []
        claim_choice(candidates[0], automatic_row, feature_id)
        choice_event = candidates[0]["event"]
        metadata = candidates[0]["metadata"]
        advancement = choice_event.get("advancement") or {}
        calculation = advancement.get("calculation") or {}
        inputs = calculation.get("inputs") or {}
        outputs = calculation.get("outputs") or {}
        selection: dict[str, Any] = {
            "choice_kind": metadata["kind"],
            "event": deepcopy(metadata),
        }
        if metadata["kind"] == "ability_score_change":
            deltas = inputs.get("deltas")
            scores_after = outputs.get("ability_scores")
            if not isinstance(deltas, dict) or not deltas or not isinstance(scores_after, dict):
                raise FoundryError(
                    "PROJECTION_EARNED_FEATURE_CHOICE_INVALID",
                    "An authenticated ability-score choice lacks its selected delta and resulting scores.",
                    details={"event_id": metadata["event_id"], "feature_id": feature_id},
                )
            selection["deltas"] = deepcopy(deltas)
            selection["ability_scores_after"] = deepcopy(scores_after)
        elif metadata["kind"] == "cultivation_insight_acquisition":
            insight_occurrence = outputs.get("insight_occurrence")
            details = advancement.get("details") or {}
            insight_record_id = (choice_event.get("subject") or {}).get("record_id")
            insight_record = locked_records.get(insight_record_id) if isinstance(insight_record_id, str) else None
            if (
                not isinstance(insight_occurrence, dict)
                or not isinstance(insight_record, dict)
                or insight_record.get("content_type") != "cultivation_insight"
                or insight_occurrence.get("record_id") != insight_record_id
                or insight_occurrence.get("event_id") != choice_event.get("event_id")
            ):
                raise FoundryError(
                    "PROJECTION_EARNED_FEATURE_CHOICE_INVALID",
                    "An authenticated Cultivation Insight choice lacks its locked subject and matching occurrence output.",
                    details={
                        "event_id": metadata["event_id"],
                        "feature_id": feature_id,
                        "insight_record_id": insight_record_id,
                    },
                )
            selection["insight_occurrence"] = deepcopy(insight_occurrence)
            for key in ("ability", "amount", "repeat_index"):
                value = inputs.get(key, details.get(key))
                if value is not None:
                    selection[key] = deepcopy(value)
        else:
            raise FoundryError(
                "PROJECTION_EARNED_FEATURE_CHOICE_INVALID",
                "An earned Path choice has an unsupported authenticated event kind.",
                details={"event_id": metadata["event_id"], "kind": metadata["kind"]},
            )
        return selection, [metadata["packet_id"]]
    occurrences: list[dict[str, Any]] = []
    for row in automatic_rows:
        event = row["event"]
        path_id = row["path_id"]
        path_level = row["path_level"]
        path_record = locked_records.get(path_id)
        if not isinstance(path_record, dict) or path_record.get("content_type") != "path":
            raise FoundryError(
                "PROJECTION_EARNED_FEATURE_PARENT_INVALID",
                "An automatic Path feature lacks its authenticated Path parent record.",
                details={"event_id": event.get("event_id"), "path_id": path_id},
            )
        event_metadata = row["metadata"]
        for feature_id in row["automatic_ids"]:
            feature_record = locked_records.get(feature_id)
            if not isinstance(feature_record, dict) or feature_record.get("content_type") != "path_feature":
                raise FoundryError(
                    "PROJECTION_EARNED_FEATURE_RECORD_MISSING",
                    "An automatic Path feature grant lacks its locked typed feature record.",
                    details={"event_id": event.get("event_id"), "feature_id": feature_id, "path_id": path_id},
                )
            required_level = _required_feature_level(feature_record, path_level)
            source_data = _record_feature_source(feature_record)
            selection, choice_packets = choice_selection(
                row,
                feature_id,
                feature_record,
                path_level,
            )
            occurrences.append(_earned_feature_occurrence(
                feature_id=feature_id,
                display_name=str(feature_record.get("display_name") or feature_id),
                feature_record_hash=str(feature_record.get("record_hash")),
                required_path_level=required_level,
                acquired_at_path_level=path_level,
                acquisition_event=event_metadata,
                attainment_event=event_metadata,
                source_packet_ids=list(dict.fromkeys([event_metadata["packet_id"], *choice_packets])),
                parent_record_id=path_id,
                parent_record_hash=str(path_record.get("record_hash")),
                owning_path_id=path_id,
                parent_kind="path",
                source_data=source_data,
                selection=selection,
            ))

    for attainments in attainments_by_path.values():
        attainments.sort(key=lambda row: int(row["metadata"]["sequence"]))

    for subpath_event in subpath_events:
        event_id = subpath_event.get("event_id")
        parent = event_records.get(event_id) or {}
        parent_id = (subpath_event.get("subject") or {}).get("record_id")
        owner_path_id = parent.get("owning_path_id")
        authority = (((parent.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {})
        progression = authority.get("feature_progression")
        if not isinstance(parent_id, str) or not isinstance(parent.get("record_hash"), str) or parent.get("content_type") != "subpath":
            raise FoundryError(
                "PROJECTION_EARNED_FEATURE_PARENT_INVALID",
                "A selected Subpath lacks its authenticated parent record for feature display.",
                details={"event_id": event_id, "record_id": parent_id},
            )
        if not isinstance(owner_path_id, str) or owner_path_id not in selected_paths or not isinstance(progression, list):
            raise FoundryError(
                "PROJECTION_EARNED_FEATURE_PARENT_INVALID",
                "A selected Subpath lacks authenticated owning-Path progression authority.",
                details={"event_id": event_id, "record_id": parent_id, "owning_path_id": owner_path_id},
            )
        parent_metadata = _earned_event_metadata(subpath_event, packet_by_event[event_id])
        owner_attainments = attainments_by_path.get(owner_path_id) or []
        parent_sequence = int(parent_metadata["sequence"])
        if not owner_attainments or not any(int(row["metadata"]["sequence"]) < parent_sequence for row in owner_attainments):
            raise FoundryError(
                "PROJECTION_EARNED_FEATURE_PATH_ATTAINMENT_INVALID",
                "A selected Subpath was acquired without prior authenticated owning-Path attainment.",
                details={"event_id": event_id, "owning_path_id": owner_path_id},
            )
        for feature in progression:
            if not isinstance(feature, dict):
                raise FoundryError(
                    "PROJECTION_EARNED_FEATURE_PROGRESSION_INVALID",
                    "A selected Subpath progression contains a malformed feature row.",
                    details={"event_id": event_id, "parent_record_id": parent_id},
                )
            feature_id = feature.get("canonical_id")
            display_name = feature.get("display_name")
            threshold = feature.get("granted_at_cl")
            if isinstance(threshold, list):
                values = [value for value in threshold if type(value) is int and value > 0]
                threshold = min(values) if values else None
            if not isinstance(feature_id, str) or not feature_id or not isinstance(display_name, str) or not display_name or type(threshold) is not int or threshold < 1:
                raise FoundryError(
                    "PROJECTION_EARNED_FEATURE_PROGRESSION_INVALID",
                    "A selected Subpath progression feature lacks canonical identity or printed threshold.",
                    details={"event_id": event_id, "parent_record_id": parent_id, "feature": feature},
                )
            before = [
                row for row in owner_attainments
                if int(row["metadata"]["sequence"]) < parent_sequence and int(row["path_level"]) >= threshold
            ]
            after = [
                row for row in owner_attainments
                if int(row["metadata"]["sequence"]) > parent_sequence and int(row["path_level"]) >= threshold
            ]
            if before:
                attained = max(before, key=lambda row: int(row["metadata"]["sequence"]))
                acquisition = parent_metadata
                source_packets = [parent_metadata["packet_id"], attained["metadata"]["packet_id"]]
            elif after:
                attained = min(after, key=lambda row: int(row["metadata"]["sequence"]))
                acquisition = attained["metadata"]
                source_packets = [parent_metadata["packet_id"], attained["metadata"]["packet_id"]]
            else:
                # A printed future feature remains quoted in its parent source,
                # but is not presented as already earned.
                continue
            source_data = _progression_feature_source(feature_id, feature, factory_root=factory_root)
            feature_record_hash = sha256_json({
                "parent_record_id": parent_id,
                "parent_record_hash": parent["record_hash"],
                "feature": feature,
            })
            occurrences.append(_earned_feature_occurrence(
                feature_id=feature_id,
                display_name=display_name,
                feature_record_hash=feature_record_hash,
                required_path_level=threshold,
                acquired_at_path_level=int(attained["path_level"]),
                acquisition_event=acquisition,
                attainment_event=attained["metadata"],
                source_packet_ids=list(dict.fromkeys(source_packets)),
                parent_record_id=parent_id,
                parent_record_hash=parent["record_hash"],
                owning_path_id=owner_path_id,
                parent_kind="subpath",
                source_data=source_data,
                components=feature.get("components") if isinstance(feature.get("components"), list) else [],
                minimum_realm_band=feature.get("minimum_realm_band"),
                source_cl_basis=feature.get("source_cl_basis"),
                derived_feature_snapshot=feature,
            ))

    occurrences.sort(key=lambda row: (
        int(row["acquired_at_character_cl"]),
        str(row["owning_path_id"]),
        int(row["acquired_at_path_level"]),
        str(row["feature_id"]),
        int(row["event_sequence"]),
    ))
    return occurrences


def _dynamic_display_contract(
    project: dict[str, Any],
    choice_snapshot: dict[str, Any],
    locked_records: dict[str, dict[str, Any]],
    packets: list[dict[str, Any]],
    granted_ids: list[str],
    subpath_packet_id: str | None,
    granted_feature_sources: dict[str, list[dict[str, Any]]] | None = None,
    level_feature_sources: dict[str, list[dict[str, Any]]] | None = None,
    earned_feature_occurrences: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    packets_by_record: dict[str, list[dict[str, Any]]] = {}
    for packet in packets:
        packets_by_record.setdefault(str(packet["record_id"]), []).append(packet)
    # Every feature a level grants beyond the event's representative subject
    # binds to that level's packet, so the sheet can render it with an exact
    # acquisition source.
    level_feature_sources = level_feature_sources or {}
    required_ids = set(packets_by_record) | set(granted_ids) | set(level_feature_sources)
    granted_id_set = set(granted_ids)
    granted_feature_sources = granted_feature_sources or {}
    rules: list[dict[str, Any]] = []
    automatic_component_ids: set[str] = set()
    for record_id in sorted(required_ids):
        record = locked_records.get(record_id)
        if not record:
            raise FoundryError(
                "CHARACTER_SHEET_DISPLAY_AUTHORITY_MISSING",
                "A selected record lacks its locked typed catalog snapshot.",
                details={"record_id": record_id},
            )
        record_packets = sorted(packets_by_record.get(record_id) or [], key=lambda row: int(row.get("sequence") or 0))
        # A source-granted Subpath feature has no independent Stage 2 event of
        # its own.  Its display authority must nevertheless retain the exact
        # Subpath acquisition that granted it.  Do not fall back to the first
        # (primary) Subpath packet when a second Path owns this feature.
        source_bindings = [
            row for row in granted_feature_sources.get(record_id, [])
            if isinstance(row, dict) and isinstance(row.get("packet_id"), str)
        ]
        if record_id in granted_id_set and not source_bindings:
            raise FoundryError(
                "PROJECTION_SUBPATH_FEATURE_SOURCE_MISSING",
                "A source-granted Subpath feature lacks an exact Subpath acquisition source binding.",
                details={"record_id": record_id},
            )
        level_bindings = [
            row for row in level_feature_sources.get(record_id, [])
            if isinstance(row, dict) and isinstance(row.get("packet_id"), str)
        ] if not record_packets else []
        binding_packet = (
            {
                "packet_id": source_bindings[0]["packet_id"],
                "event_id": source_bindings[0].get("event_id"),
                "target_cl": source_bindings[0].get("target_cl", 3),
                "advancement_kind": "subpath_acquisition",
            }
            if source_bindings
            else {
                "packet_id": level_bindings[0]["packet_id"],
                "event_id": level_bindings[0].get("event_id"),
                "target_cl": level_bindings[0].get("target_cl"),
                "advancement_kind": "level_advance",
            }
            if level_bindings
            else next(
                (packet for packet in record_packets if packet.get("advancement_kind") == "level_advance"),
                record_packets[0] if record_packets else None,
            )
        )
        if binding_packet is None:
            if not subpath_packet_id:
                raise FoundryError(
                    "PROJECTION_SUBPATH_FEATURE_SOURCE_MISSING",
                    "A display record lacks an exact event packet and no authenticated Subpath packet is available.",
                    details={"record_id": record_id},
                )
            binding_packet = {
                "packet_id": subpath_packet_id,
                "target_cl": 3,
                "advancement_kind": "source_granted_subpath_feature",
            }
        content_type = str(record.get("content_type") or "")
        short, full = _display(record)
        if content_type in {"path_feature", "subpath_feature"}:
            # Path-feature cards may expose only a name in their display
            # projection.  Their selected rule must use the exact same
            # authenticated source payload as earned occurrences.
            full = _record_feature_source(record)["full_description"]
        source = deepcopy(record.get("source") or {})
        if not all(isinstance(source.get(key), str) and source.get(key) for key in ("path", "anchor", "source_hash")):
            raise FoundryError(
                "CHARACTER_SHEET_DESCRIPTION_UNPROVEN",
                "A selected typed catalog record lacks exact source identity.",
                details={"record_id": record_id},
            )
        section, subsection = _dynamic_display_section(record, record_packets)
        executable = content_type in {"talent", "path_feature", "subpath_feature", "origin_insight"}
        stage2 = ((record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {})
        rule = {
            "record_id": record_id,
            "record_hash": record["record_hash"],
            "display_name": record.get("display_name") or record_id,
            "section": section,
            "subsection": subsection,
            "one_line_description": short,
            "full_description": full,
            "full_description_source": "locked_typed_catalog_record",
            "source": source,
            "acquisition_source": {
                "target_cl": binding_packet.get("target_cl"),
                "advancement_kind": binding_packet.get("advancement_kind"),
                "packet_ids": [binding_packet["packet_id"]],
                "event_ids": [binding_packet.get("event_id")]
                if binding_packet.get("event_id")
                else [],
            },
            "stage2_rule_id": stage2.get("rule_id"),
            "display_timing_or_category": None,
            "capabilities": {
                "character_sheet": "SUPPORTED",
                "gm_display": "NOT_ATTEMPTED",
                "combat_execution": "UNSUPPORTED" if executable else "NOT_APPLICABLE",
                "ai_policy": "BLOCKED_BY_DEPENDENCY" if executable else "NOT_APPLICABLE",
            },
            "display_only_not_execution_authority": executable,
        }
        if content_type == "sphere":
            sphere_packet = normalize_sphere_automatic_components(record)
            rule["automatic_component_authority"] = sphere_packet
            for component in sphere_packet["components"]:
                component_id = component["component_id"]
                if component_id in automatic_component_ids:
                    raise FoundryError(
                        "CHARACTER_SHEET_DUPLICATE_DISPLAY_MAPPING",
                        "A Sphere automatic component ID is attached to more than one display mapping.",
                        details={"component_id": component_id},
                    )
                automatic_component_ids.add(component_id)
                component_source = _component_display_source(component, source, record_id)
                component_text = str(component["player_rules_text"]).strip()
                component_rule = {
                    "record_id": component_id,
                    "record_hash": component["component_hash"],
                    "display_name": component.get("display_name") or component_id,
                    "section": "sphere_automatic_components",
                    "subsection": f"{record.get('display_name') or record_id} Automatic Components",
                    "one_line_description": component_text.splitlines()[0].strip(),
                    "full_description": component_text,
                    "full_description_source": "locked_sphere_automatic_component_authority",
                    "source": component_source,
                    "acquisition_source": {
                        "target_cl": binding_packet.get("target_cl"),
                        "advancement_kind": binding_packet.get("advancement_kind"),
                        "packet_ids": [binding_packet["packet_id"]],
                    },
                    "stage2_rule_id": stage2.get("rule_id"),
                    "display_timing_or_category": "Automatic Sphere Component",
                    "capabilities": {
                        "character_sheet": "SUPPORTED",
                        "gm_display": "NOT_ATTEMPTED",
                        "combat_execution": "NOT_APPLICABLE",
                        "ai_policy": "NOT_APPLICABLE",
                    },
                    "display_only_not_execution_authority": False,
                    "parent_sphere_id": record_id,
                    "component_hash": component["component_hash"],
                    "automatic_component_flags": {
                        key: component[key]
                        for key in (
                            "automatic_grant",
                            "owner_removable",
                            "counts_as_talent_choice",
                            "counts_as_advancement_talent",
                            "counts_as_training_talent",
                        )
                    },
                    "owner_ruling": deepcopy(component.get("owner_ruling") or {}),
                    "automatic_component_authority": {
                        "schema_version": sphere_packet["schema_version"],
                        "parent_sphere_id": record_id,
                        "package_hash": sphere_packet["package_hash"],
                        "component_ids": [component_id],
                    },
                }
                rules.append(component_rule)
            required_ids.update(automatic_component_ids)
        rules.append(rule)
    unsigned = {
        "schema_version": "TianxiaFoundry.CharacterSheetDisplayContract.v1",
        "contract_id": f"tianxia.character_sheet.display.project.{project['project_id']}",
        "canonical_project_id": project["project_id"],
        "project_revision": project["revision"],
        "typed_choice_snapshot_sha256": choice_snapshot["snapshot_sha256"],
        "readiness_stage": "CHARACTER_SHEET_READY",
        "policies": {
            "combat_execution_promotion": False,
            "duplicate_record_presentation": "FAIL_CLOSED",
            "missing_mapping": "FAIL_CLOSED",
            "runtime_prose_parsing": False,
            "source_backed_display_only": True,
            "unproven_description": "FAIL_CLOSED",
        },
        "rules": rules,
        "earned_feature_occurrences": deepcopy(earned_feature_occurrences or []),
    }
    return {**unsigned, "seal_sha256": sha256_json(unsigned)}


FORGED_TECHNIQUE_KIND = "forged_technique_creation"


def _validated_constructed_art_record(
    record: dict[str, Any],
    locked_records: dict[str, dict[str, Any]] | None,
    *,
    factory_root: Path | None = None,
) -> dict[str, Any] | None:
    """Return the embedded constructed art when this is a Factory-constructed record.

    Accepted only when the locked-record projection holds byte-identical data
    and the record re-derives from its own art under the sealed authority.
    The pack ID alone never authorizes anything.
    """
    from character_creation.constructed_arts.records import (
        CONSTRUCTED_ART_PACK_IDS,
        validate_constructed_art_record,
    )

    binding = record.get("content_binding") if isinstance(record, dict) else None
    if not isinstance(binding, dict) or binding.get("pack_id") not in CONSTRUCTED_ART_PACK_IDS:
        return None
    record_id = record.get("record_id")
    snapshot = locked_records.get(record_id) if isinstance(locked_records, dict) and isinstance(record_id, str) else None
    if not isinstance(snapshot, dict) or canonical_json(snapshot) != canonical_json(record):
        raise FoundryError(
            "PROJECTION_CONSTRUCTED_ART_INVALID",
            "A Factory-constructed art is not byte-identical to its locked-record projection.",
            details={"record_id": record_id},
        )
    try:
        return validate_constructed_art_record(
            record,
            root_dir=_BRIDGE_ROOT_DIR,
            factory_root=factory_root,
        )
    except FoundryError as exc:
        raise FoundryError(
            "PROJECTION_CONSTRUCTED_ART_INVALID",
            "A Factory-constructed art does not re-derive from its sealed authority.",
            details={"record_id": record_id, "cause": exc.code},
        ) from exc


def _validated_custom_training_source_record(
    record: dict[str, Any],
    locked_records: dict[str, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Return the exact project-scoped custom contract, if this is one.

    A custom record is accepted only when the caller's locked-record
    projection contains byte-identical record data and the dedicated builder
    can reproduce every authority surface.  The pack ID alone is never an
    authorization signal.
    """
    binding = record.get("content_binding") if isinstance(record, dict) else None
    if not isinstance(binding, dict) or binding.get("pack_id") != "tianxia.project.user_directive.training_source":
        return None
    record_id = record.get("record_id")
    snapshot = locked_records.get(record_id) if isinstance(locked_records, dict) and isinstance(record_id, str) else None
    try:
        from character_creation.custom_training_source_authority import (
            CUSTOM_TRAINING_SOURCE_PACK_ID,
            validate_custom_training_source_record,
        )

        if not isinstance(snapshot, dict) or canonical_json(snapshot) != canonical_json(record):
            raise FoundryError(
                "PROJECTION_CUSTOM_TRAINING_SOURCE_INVALID",
                "A project-scoped custom source is not byte-identical to its locked-record projection.",
                details={"record_id": record_id},
            )
        if binding.get("pack_id") != CUSTOM_TRAINING_SOURCE_PACK_ID:
            raise FoundryError(
                "PROJECTION_CUSTOM_TRAINING_SOURCE_INVALID",
                "A project-scoped custom source has an unsupported pack binding.",
                details={"record_id": record_id},
            )
        return validate_custom_training_source_record(record)
    except FoundryError as exc:
        if exc.code == "PROJECTION_CUSTOM_TRAINING_SOURCE_INVALID":
            raise
        raise FoundryError(
            "PROJECTION_CUSTOM_TRAINING_SOURCE_INVALID",
            "A project-scoped custom source does not reproduce its sealed authority contract.",
            details={"record_id": record_id, "cause": exc.code},
        ) from exc


def _validate_binding(
    event: dict[str, Any],
    record: dict[str, Any],
    project: dict[str, Any],
    *,
    locked_records: dict[str, dict[str, Any]] | None = None,
    factory_root: Path | None = None,
) -> None:
    binding = event.get("content_binding") or {}
    rb = record.get("content_binding") or {}
    if binding.get("record_hash") != record.get("record_hash") or any(binding.get(k) != rb.get(k) for k in ("pack_id", "pack_version", "pack_hash")):
        raise FoundryError("PROJECTION_CONTENT_BINDING_MISMATCH", "A v3 event does not match its locked record snapshot.", details={"event_id": event.get("event_id"), "record_id": record.get("record_id")})
    allowed = {(x.get("pack_id"), x.get("version"), x.get("content_hash")) for x in (project.get("content_lock") or {}).get("packs", [])}
    factory = record.get("compatibility", {}).get("factory", {})
    raw_projection = factory.get("raw_projection") or {}
    source_path = str(record.get("source", {}).get("path", ""))
    from non_sphere_authority.foundation_mechanics import (
        FOUNDATION_MECHANICS_PACK_VERSION, verified_initial_foundation_record_source,
    )
    initial_foundation_source = None
    if record.get("content_type") == "foundation" and (
        rb.get("pack_version") == FOUNDATION_MECHANICS_PACK_VERSION
        or (factory.get("stage2_authority") or {}).get("initial_foundation_mechanics") is not None
    ):
        # Installed derivations have an explicit source version, not the old
        # authority file paths. The upstream resolver must first prove the
        # immutable parent and reproduce this exact event-bound record.
        snapshot = (locked_records or {}).get(record.get("record_id"))
        if not isinstance(snapshot, dict) or canonical_json(snapshot) != canonical_json(record):
            raise FoundryError("PROJECTION_FOUNDATION_MECHANICS_INVALID", "An installed Foundation must match its authenticated locked-record projection.")
        initial_foundation_source = verified_initial_foundation_record_source(record)
    foundation_authority_identity = (
        record.get("content_type") == "foundation"
        and (
            source_path.startswith("non_sphere_authority/authority/")
            or source_path.startswith("09_RULES/Foundation_Runtime/")
            or source_path == "Foundation_Trait_Reference_v0_6.json"
        )
    )
    non_sphere_authority = (
        binding.get("pack_id") == "tianxia.non_sphere.authority"
        and (record.get("selected_authority") is True or raw_projection.get("selected_authority") is True)
        and record.get("publication", {}).get("status") == "published"
        and (
            record.get("record_id", "").startswith(("METHOD-", "tianxia.path.", "tianxia.subpath.", "tianxia.tradition.", "ancient_", "FOUNDATION_"))
            or foundation_authority_identity
        )
        and (
            source_path.startswith("non_sphere_authority/authority/")
            or (
                record.get("record_id", "").startswith(("ancient_", "FOUNDATION_"))
                and source_path == "Foundation_Trait_Reference_v0_6.json"
            )
            or foundation_authority_identity
            or (
                record.get("record_id", "").startswith(("tianxia.subpath.", "tianxia.tradition."))
                and source_path.startswith("09_RULES/Source_Text/Paths/")
            )
        )
        and (factory.get("stage2_authority", {}).get("authority_complete") is True)
    )
    custom_source = _validated_custom_training_source_record(record, locked_records)
    constructed_art = _validated_constructed_art_record(
        record,
        locked_records,
        factory_root=factory_root,
    )
    if (
        (binding.get("pack_id"), binding.get("pack_version"), binding.get("pack_hash")) not in allowed
        and not non_sphere_authority
        and initial_foundation_source is None
        and custom_source is None
        and constructed_art is None
    ):
        raise FoundryError("PROJECTION_UNLOCKED_CONTENT", "A v3 event references content outside the project lock.", details={"event_id": event.get("event_id")})


def _clean_training_source_strings(value: Any, *, field: str, event_id: Any) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item or item.strip() != item for item in value
    ) or len(value) != len(set(value)):
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_ACCESS_INVALID",
            "A training-source access authority list must contain unique, nonblank strings.",
            details={"event_id": event_id, "field": field, "value": value},
        )
    return list(value)


def _validate_training_source_access_event(
    event: dict[str, Any],
    record: dict[str, Any],
    locked_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Authenticate one canonical source-access event and its teaching targets."""
    event_id = event.get("event_id")
    advancement = event.get("advancement") or {}
    subject = event.get("subject") or {}
    stage2 = ((record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {}
    access = stage2.get("training_source_access")
    content_type = record.get("content_type")
    compiler_type = _TRAINING_SOURCE_CONTENT_TYPE_MAP.get(content_type)
    custom_source_contract = _validated_custom_training_source_record(record, locked_records)
    factory = ((record.get("compatibility") or {}).get("factory") or {})
    authority_classification = factory.get("authority_classification")
    custom_design = factory.get("custom_design") is True or record.get("custom_design") is True
    record_authority = record.get("authority")
    custom_source_authorized = custom_source_contract is not None
    if compiler_type is None:
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_CONTENT_TYPE_UNSUPPORTED",
            "The training-source content type has no explicit compiler mapping.",
            details={"event_id": event_id, "record_id": record.get("record_id"), "content_type": content_type},
        )
    if (
        subject.get("record_id") != record.get("record_id")
        or subject.get("content_type") != content_type
        or not isinstance(subject.get("display_name"), str)
        or not subject["display_name"].strip()
        or subject.get("display_name") != record.get("display_name")
        or record.get("publication", {}).get("status") != "published"
        or (custom_design and not custom_source_authorized)
        or (
            (record_authority in {"user_directive", "original_design", "inspiration_source"}
             or authority_classification in {"user_directive", "original_design", "inspiration_source"})
            and not custom_source_authorized
        )
    ):
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_ACCESS_INVALID",
            "A source-access event is not bound to a published canonical source record.",
            details={"event_id": event_id, "record_id": record.get("record_id")},
        )
    if not isinstance(access, dict) or access.get("mode") != "requires_access_event":
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_ACCESS_AUTHORITY_INVALID",
            "Only an explicit requires_access_event source authority may project a training source.",
            details={"event_id": event_id, "record_id": record.get("record_id"), "mode": access.get("mode") if isinstance(access, dict) else None},
        )
    published_modes = access.get("access_modes")
    if published_modes is None and content_type in {"manual", "martial_manual", "manual_expression"}:
        manual = stage2.get("manual")
        published_modes = manual.get("access_modes") if isinstance(manual, dict) else None
    published_modes = _clean_training_source_strings(
        published_modes,
        field="access_modes",
        event_id=event_id,
    )
    training_types = _clean_training_source_strings(
        access.get("training_types"),
        field="training_types",
        event_id=event_id,
    )
    unsupported_types = sorted(set(training_types) - set(_TRAINING_SOURCE_TARGET_CONTENT_TYPES))
    if unsupported_types:
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_TRAINING_TYPE_UNSUPPORTED",
            "The source publishes a training type without a typed target contract.",
            details={"event_id": event_id, "training_types": unsupported_types},
        )
    target_record_ids = _clean_training_source_strings(
        access.get("target_record_ids"),
        field="target_record_ids",
        event_id=event_id,
    )
    if record.get("record_id") in target_record_ids:
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_TARGET_INVALID",
            "A training source cannot publish itself as a teaching target.",
            details={"event_id": event_id, "record_id": record.get("record_id")},
        )
    expected_target_types = {
        _TRAINING_SOURCE_TARGET_CONTENT_TYPES[training_type]
        for training_type in training_types
    }
    target_records: list[dict[str, Any]] = []
    for target_id in target_record_ids:
        target = locked_records.get(target_id)
        if not isinstance(target, dict):
            raise FoundryError(
                "PROJECTION_TRAINING_SOURCE_TARGET_MISSING",
                "A published training-source target is absent from the project locked-record snapshot.",
                details={"event_id": event_id, "source_record_id": record.get("record_id"), "target_record_id": target_id},
            )
        if (
            target.get("record_id") != target_id
            or target.get("publication", {}).get("status") != "published"
            or target.get("content_type") not in expected_target_types
            or not isinstance(target.get("record_hash"), str)
            or re.fullmatch(r"[0-9a-f]{64}", target["record_hash"]) is None
        ):
            raise FoundryError(
                "PROJECTION_TRAINING_SOURCE_TARGET_TYPE_INVALID",
                "A training-source target does not match its published training-type contract.",
                details={"event_id": event_id, "target_record_id": target_id, "target_content_type": target.get("content_type"), "expected_content_types": sorted(expected_target_types)},
            )
        target_records.append(target)

    calculation = advancement.get("calculation")
    inputs = calculation.get("inputs") if isinstance(calculation, dict) else None
    outputs = calculation.get("outputs") if isinstance(calculation, dict) else None
    expected_calculation = {
        "schema": _TRAINING_SOURCE_ACCESS_CALCULATION_SCHEMA,
        "record_id": record.get("record_id"),
        "record_hash": record.get("record_hash"),
        "content_type": content_type,
        "access_mode": ((inputs or {}).get("access_mode") if isinstance(inputs, dict) else None),
        "source_mode": "requires_access_event",
        "published_access_modes": published_modes,
        "training_types": training_types,
        "target_record_ids": target_record_ids,
    }
    if (
        advancement.get("kind") != "training_source_access"
        or advancement.get("details") != {}
        or not isinstance(calculation, dict)
        or calculation.get("formula") is not None
        or not isinstance(calculation.get("rule_id"), str)
        or calculation.get("rule_id") != stage2.get("rule_id")
        or not isinstance(stage2.get("rule_id"), str)
        or not stage2["rule_id"].strip()
        or calculation.get("trace") != {}
        or not isinstance(inputs, dict)
        or not isinstance(outputs, dict)
        or inputs != outputs
        or set(inputs) != set(expected_calculation)
        or inputs.get("record_id") != record.get("record_id")
        or inputs.get("record_hash") != record.get("record_hash")
        or inputs.get("content_type") != content_type
        or inputs.get("source_mode") != "requires_access_event"
        or inputs.get("published_access_modes") != published_modes
        or inputs.get("training_types") != training_types
        or inputs.get("target_record_ids") != target_record_ids
        or not isinstance(inputs.get("access_mode"), str)
        or not inputs["access_mode"]
        or inputs["access_mode"].strip() != inputs["access_mode"]
        or inputs["access_mode"] not in published_modes
        or not isinstance(record.get("record_hash"), str)
        or re.fullmatch(r"[0-9a-f]{64}", record["record_hash"]) is None
        or event.get("created_records") != [record.get("record_id")]
        or event.get("updated_records") != []
        or event.get("retired_records") != []
        or advancement.get("training_transaction") is not None
        or advancement.get("none_state") is not None
        or type(advancement.get("target_cl")) is not int
        or advancement.get("target_cl") < 1
    ):
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_ACCESS_CALCULATION_INVALID",
            "A source-access event calculation does not exactly reproduce the locked source authority.",
            details={"event_id": event_id, "record_id": record.get("record_id")},
        )
    if expected_calculation["access_mode"] != inputs["access_mode"]:
        # This branch is intentionally explicit: expected_calculation is built
        # from the event only for the mode, while all other commitments above
        # come from the locked source authority.
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_ACCESS_CALCULATION_INVALID",
            "The source-access mode is not a validated canonical calculation input.",
            details={"event_id": event_id, "record_id": record.get("record_id")},
        )
    return {
        "record": record,
        "compiler_type": compiler_type,
        "published_access_modes": published_modes,
        "training_types": training_types,
        "target_record_ids": target_record_ids,
        "target_records": target_records,
        "access_mode": inputs["access_mode"],
    }


def _forged_technique_projection_rows(
    events: list[dict[str, Any]],
    *,
    event_records: dict[str, dict[str, Any]],
    locked_records: dict[str, dict[str, Any]],
    packet_by_event: dict[str, str],
    event_context_by_id: dict[str, dict[str, Any]] | None = None,
    factory_root: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Project compiled Forged Techniques from their causal creation events."""
    from character_creation.constructed_arts.forged_technique import (
        forged_technique_acquisition_authority,
        validate_forged_technique_acquisition,
    )
    from character_creation.constructed_arts.records import forged_technique_record_text

    rows: list[dict[str, Any]] = []
    indexes: dict[str, int] = {}
    seen: set[str] = set()
    for event in events:
        record = event_records[event["event_id"]]
        technique = _validated_constructed_art_record(
            record,
            locked_records,
            factory_root=factory_root,
        )
        if technique is None:
            raise FoundryError(
                "PROJECTION_CONSTRUCTED_ART_INVALID",
                "A Forged Technique creation event is not bound to a Factory-constructed record.",
                details={"event_id": event["event_id"], "record_id": record.get("record_id")},
            )
        outputs = (event.get("advancement") or {}).get("calculation", {}).get("outputs") or {}
        compiled = outputs.get("forged_technique") or {}
        if compiled.get("technique_id") != technique["technique_id"] or compiled.get("record_id") != record["record_id"]:
            raise FoundryError(
                "PROJECTION_CONSTRUCTED_ART_INVALID",
                "A Forged Technique creation event does not name the technique its record embeds.",
                details={"event_id": event["event_id"], "record_id": record.get("record_id")},
            )
        calculation = (event.get("advancement") or {}).get("calculation") or {}
        acquisition = outputs.get("forging_acquisition")
        input_acquisition = calculation.get("inputs", {}).get("forging_acquisition") if isinstance(calculation.get("inputs"), dict) else None
        persisted_authority = compiled.get("forging_acquisition_authority")
        input_authority = calculation.get("inputs", {}).get("forging_acquisition_authority") if isinstance(calculation.get("inputs"), dict) else None
        authority_required = persisted_authority is not None or input_authority is not None
        if authority_required:
            expected_authority = forged_technique_acquisition_authority()
            if persisted_authority != expected_authority or input_authority != expected_authority:
                raise FoundryError(
                    "PROJECTION_FORGED_ACQUISITION_AUTHORITY_INVALID",
                    "A new Forged Technique event has an invalid or incomplete persistent acquisition authority binding.",
                    details={"event_id": event["event_id"], "record_id": record.get("record_id")},
                )
            if acquisition is None or input_acquisition is None:
                raise FoundryError(
                    "PROJECTION_FORGED_ACQUISITION_REQUIRED",
                    "A new Forged Technique event must retain both server-derived acquisition proof copies.",
                    details={"event_id": event["event_id"], "record_id": record.get("record_id")},
                )
        elif (
            isinstance(acquisition, dict) and "authority" in acquisition
        ) or (
            isinstance(input_acquisition, dict) and "authority" in input_acquisition
        ):
            raise FoundryError(
                "PROJECTION_FORGED_ACQUISITION_AUTHORITY_MISSING",
                "A Forged Technique proof with new creator authority must be bound to its persistent event marker.",
                details={"event_id": event["event_id"], "record_id": record.get("record_id")},
            )
        if acquisition is not None or input_acquisition is not None:
            if acquisition is None or input_acquisition is None or canonical_json(acquisition) != canonical_json(input_acquisition):
                raise FoundryError(
                    "PROJECTION_FORGED_ACQUISITION_INVALID",
                    "A Forged Technique event's acquisition proof must be identical on its calculated input and output sides.",
                    details={"event_id": event["event_id"], "record_id": record.get("record_id")},
                )
            context = (event_context_by_id or {}).get(event["event_id"]) or {}
            path_event = context.get("path_event")
            ability_event = context.get("ability_event")
            level_event = context.get("level_event")
            path_record = context.get("path_record")
            if not isinstance(path_event, dict) or not isinstance(ability_event, dict) or not isinstance(level_event, dict) or not isinstance(path_record, dict):
                raise FoundryError(
                    "PROJECTION_FORGED_ACQUISITION_CONTEXT_MISSING",
                    "A Forged Technique acquisition proof lacks its causal Powering Path, ability state or level event.",
                    details={"event_id": event["event_id"], "record_id": record.get("record_id")},
                )
            path_authority = ((path_record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {}
            key_ability = path_authority.get("key_ability")
            ability_outputs = ((ability_event.get("advancement") or {}).get("calculation") or {}).get("outputs") or {}
            level_outputs = ((level_event.get("advancement") or {}).get("calculation") or {}).get("outputs") or {}
            ability_modifiers = ability_outputs.get("ability_modifiers")
            pb = level_outputs.get("pb")
            if key_ability not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"} or not isinstance(ability_modifiers, dict) or type(ability_modifiers.get(key_ability)) is not int or type(pb) is not int:
                raise FoundryError(
                    "PROJECTION_FORGED_ACQUISITION_CONTEXT_INVALID",
                    "A Forged Technique acquisition proof lacks a complete causal Path ability or Proficiency Bonus.",
                    details={"event_id": event["event_id"], "record_id": record.get("record_id")},
                )
            if path_event.get("subject", {}).get("record_id") != technique.get("powering_path_id"):
                raise FoundryError(
                    "PROJECTION_FORGED_POWERING_PATH_INVALID",
                    "The Forged Technique acquisition proof is not bound to its actually acquired Powering Path.",
                    details={"event_id": event["event_id"], "record_id": record.get("record_id")},
                )
            try:
                validate_forged_technique_acquisition(
                    acquisition,
                    event_id=event["event_id"],
                    record_id=record["record_id"],
                    record_hash=record["record_hash"],
                    cl=int(event["advancement"]["target_cl"]),
                    path_id=path_event["subject"]["record_id"],
                    key_ability=key_ability,
                    ability_modifier=ability_modifiers[key_ability],
                    pb=pb,
                    dc=int(technique["technique_forging_dc"]),
                    research_days=int(technique["research_days"]),
                    material_cost_gp=int(technique["material_cost_gp"]),
                    require_derived_fields=True,
                    require_authority_binding=authority_required,
                )
            except (FoundryError, KeyError, TypeError, ValueError) as exc:
                if isinstance(exc, FoundryError):
                    raise FoundryError(
                        "PROJECTION_FORGED_ACQUISITION_INVALID",
                        exc.message,
                        details={"event_id": event["event_id"], **(exc.details or {})},
                    ) from exc
                raise FoundryError(
                    "PROJECTION_FORGED_ACQUISITION_INVALID",
                    "The Forged Technique acquisition proof cannot be re-derived from its causal state.",
                    details={"event_id": event["event_id"], "record_id": record.get("record_id")},
                ) from exc
        if record["record_id"] in seen:
            raise FoundryError(
                "PROJECTION_FORGED_TECHNIQUE_DUPLICATE",
                "A Forged Technique may receive only one causal creation event.",
                details={"record_id": record["record_id"]},
            )
        seen.add(record["record_id"])
        indexes[event["event_id"]] = len(rows)
        rows.append({
            "technique_id": technique["technique_id"],
            "record_id": record["record_id"],
            "record_hash": record["record_hash"],
            "name": technique["name"],
            "state": "known",
            "evolution_state": technique["evolution_state"],
            "realm": technique["realm"],
            "cl_created": int(event["advancement"]["target_cl"]),
            "base_form": deepcopy(technique["base_form"]),
            "primary_sphere_effect": deepcopy(technique["primary_sphere_effect"]),
            "secondary_sphere_effects": deepcopy(technique.get("secondary_sphere_effects") or []),
            "augments": deepcopy(technique.get("augments") or []),
            "drawbacks": deepcopy(technique.get("drawbacks") or []),
            "backlash": deepcopy(technique.get("backlash")),
            "exhausting": bool(technique.get("exhausting")),
            "action_type": technique["action_type"],
            "cp_cost": deepcopy(technique["cp_cost"]),
            "complexity": deepcopy(technique["complexity"]),
            "spheres_used": technique["spheres_used"],
            "technique_forging_dc": technique["technique_forging_dc"],
            "research_days": technique["research_days"],
            "material_cost_gp": technique["material_cost_gp"],
            "target_range_area": technique["target_range_area"],
            "attack_save_check": technique["attack_save_check"],
            "effect": deepcopy(technique["effect"]),
            "duration": technique["duration"],
            "limits": list(technique.get("limits") or []),
            "record_text": forged_technique_record_text(technique),
            "source_notes": deepcopy(technique.get("source_notes") or []),
            "construction": {"seed": technique["construction"]["seed"], "authority_seal_sha256": technique["construction"].get("authority_seal_sha256")},
            "known_after": outputs.get("known_after"),
            "known_limit": outputs.get("known_limit"),
            "source_packet_ids": [packet_by_event[event["event_id"]]],
            "event_id": event["event_id"],
        })
    return rows, indexes


def _ordinary_recorded_art_projection_row(
    event: dict[str, Any],
    *,
    record: dict[str, Any],
    event_records: dict[str, dict[str, Any]],
    locked_records: dict[str, dict[str, Any]],
    packet_by_event: dict[str, str],
) -> dict[str, Any]:
    """Project a successful ordinary template-backed Recorded Art study.

    Ordinary catalog arts do not carry the Factory constructed-art bundle used
    by the lineage lane.  Their execution authority is the published action
    template on the locked source component, so keep that path separate from
    the strict quote-only constructed-art projection below.
    """
    from stage2.authority_contract import (
        MANUAL_CONTENT_TYPES,
        recorded_art_execution_issues,
        recorded_art_expression_issues,
    )

    event_id = event.get("event_id")
    advancement = event.get("advancement") or {}
    calculation = advancement.get("calculation") or {}
    outputs = calculation.get("outputs") or {}
    transaction = advancement.get("training_transaction") or {}

    def fail(message: str, **details: Any) -> None:
        raise FoundryError("PROJECTION_RECORDED_ART_INVALID", message, details={"event_id": event_id, **details})

    record_id = record.get("record_id")
    snapshot = locked_records.get(record_id) if isinstance(record_id, str) else None
    if not isinstance(snapshot, dict) or canonical_json(snapshot) != canonical_json(record):
        fail("An ordinary Recorded Art event is not byte-identical to its locked record projection.", record_id=record_id)
    if (
        transaction.get("target_record_id") != record_id
        or transaction.get("target_record_hash") != record.get("record_hash")
        or transaction.get("training_type") != "recorded_art"
        or transaction.get("result") != "success"
    ):
        fail("A successful ordinary Recorded Art event is not bound to its target record transaction.", record_id=record_id)

    stage2 = ((record.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {}
    art = stage2.get("recorded_art")
    if not isinstance(art, dict):
        fail("An ordinary Recorded Art has no complete locked Stage 2 authority.", record_id=record_id)
    expression_issues = recorded_art_expression_issues(
        record_id=record_id,
        art=art,
        record_map=locked_records,
    )
    if expression_issues:
        fail("An ordinary Recorded Art does not reproduce its locked expression grammar.", record_id=record_id, issues=expression_issues)

    parent_id = art.get("parent_manual_record_id")
    parent = locked_records.get(parent_id) if isinstance(parent_id, str) else None
    if (
        not isinstance(parent, dict)
        or parent.get("content_type") not in MANUAL_CONTENT_TYPES
    ):
        fail("An ordinary Recorded Art does not resolve to a locked Manual parent.", record_id=record_id, parent_manual_record_id=parent_id)
    parent_authority = ((parent.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {}
    parent_manual = parent_authority.get("manual")
    if (
        not isinstance(parent_manual, dict)
        or record_id not in (parent_manual.get("technique_record_ids") or [])
    ):
        fail("An ordinary Recorded Art is not listed by its locked Manual parent.", record_id=record_id, parent_manual_record_id=parent_id)

    component_ids = art.get("reproduced_component_record_ids")
    sphere_ids = art.get("associated_sphere_record_ids")
    if not isinstance(component_ids, list) or not component_ids or not isinstance(sphere_ids, list) or not sphere_ids:
        fail("An ordinary Recorded Art has incomplete component or Sphere authority.", record_id=record_id)
    components: list[dict[str, Any]] = []
    for component_id in component_ids:
        component = locked_records.get(component_id)
        if not isinstance(component, dict):
            fail("An ordinary Recorded Art component is absent from the locked record projection.", record_id=record_id, component_record_id=component_id)
        components.append(component)
    spheres: list[dict[str, Any]] = []
    for sphere_id in sphere_ids:
        sphere = locked_records.get(sphere_id)
        if not isinstance(sphere, dict) or sphere.get("content_type") != "sphere":
            fail("An ordinary Recorded Art Sphere reference is not a locked Sphere record.", record_id=record_id, sphere_record_id=sphere_id)
        spheres.append(sphere)

    derivation = art.get("execution_derivation") if isinstance(art.get("execution_derivation"), dict) else {}
    source_record_id = derivation.get("source_record_id")
    source_component = locked_records.get(source_record_id) if isinstance(source_record_id, str) else None
    template_id = derivation.get("template_id")
    template = (
        next(
            (
                row
                for row in source_component.get("execution_templates", [])
                if isinstance(row, dict)
                and row.get("template_id") == template_id
                and row.get("template_type") == "action"
            ),
            None,
        )
        if isinstance(source_component, dict)
        else None
    )
    if not isinstance(template, dict) or not isinstance(template.get("payload"), dict):
        fail("An ordinary Recorded Art does not resolve to its published action template.", record_id=record_id, source_record_id=source_record_id, template_id=template_id)
    template_issues = recorded_art_execution_issues(template["payload"])
    if template_issues:
        fail("An ordinary Recorded Art action template is not a complete executable payload.", record_id=record_id, source_record_id=source_record_id, template_id=template_id, issues=template_issues)

    execution = deepcopy(template["payload"])
    expected_derivation = {
        "derivation_kind": "published_expression",
        "source_execution_record_id": source_record_id,
        "component_record_ids": list(component_ids),
        "source_template_hash": sha256_json(template),
        "compiled_payload_hash": sha256_json(execution),
    }
    learning = art.get("learning_dc") if isinstance(art.get("learning_dc"), dict) else {}
    if learning.get("mode") == "difficulty_formula" and type(learning.get("difficulty")) is int and learning["difficulty"] >= 0:
        learning_suffix = f"Difficulty {learning['difficulty']}"
    elif learning.get("mode") == "explicit_dc_override" and type(learning.get("explicit_dc")) is int and learning["explicit_dc"] >= 0:
        learning_suffix = f"DC {learning['explicit_dc']} (specific override)"
    else:
        fail("An ordinary Recorded Art lacks a resolved learning authority.", record_id=record_id)

    expected_output = {
        "record_id": record_id,
        "display_name": record.get("display_name"),
        "parent_manual_record_id": parent_id,
        "parent_manual_name": parent.get("display_name"),
        "lineage_source": parent_manual.get("lineage_source"),
        "technique_name": art.get("technique_name"),
        "dm_facing_line": (
            f"Sphere of {' and '.join(' '.join(str(sphere.get('display_name')).replace('—', '-').replace('–', '-').split()) for sphere in spheres)}"
            f" — {' '.join(str(art.get('technique_name')).replace('—', '-').replace('–', '-').split())}"
            f" — {', '.join(' '.join(str(component.get('display_name')).replace('—', '-').replace('–', '-').split()) for component in components)}"
            f" — {learning_suffix}"
        ),
        "associated_sphere_record_ids": list(sphere_ids),
        "associated_sphere_names": [sphere.get("display_name") for sphere in spheres],
        "reproduced_component_record_ids": list(component_ids),
        "reproduced_component_names": [component.get("display_name") for component in components],
        "expression_kind": art.get("expression_kind"),
        "learning_dc": deepcopy(learning),
        "study_time": deepcopy(art.get("study_time")),
        "allowed_study_abilities": deepcopy(art.get("allowed_study_abilities")),
        "requirements": deepcopy(art.get("requirements")),
        "execution": execution,
        "execution_derivation": expected_derivation,
        "linked_action_id": execution.get("action_id"),
        "fixed_expression_warning": "Learning this Recorded Art grants no source Sphere, source talent, flexible package, or modification permission.",
        "learned_at_cl": advancement.get("target_cl"),
        "acquisition_event_id": event_id,
        "record_hash": record.get("record_hash"),
    }
    output_art = outputs.get("recorded_art")
    if not isinstance(output_art, dict) or canonical_json(output_art) != canonical_json(expected_output):
        fail("An ordinary Recorded Art event output does not rederive from its locked template authority.", record_id=record_id)

    training_source_record_id = transaction.get("training_source_record_id")
    training_source_access_event_id = transaction.get("training_source_access_event_id")
    if training_source_record_id != parent_id or transaction.get("training_source_record_hash") != parent.get("record_hash"):
        fail("An ordinary Recorded Art study is not bound to its parent Manual source authority.", record_id=record_id, parent_manual_record_id=parent_id)
    if not isinstance(training_source_access_event_id, str) or not isinstance(packet_by_event.get(training_source_access_event_id), str):
        fail("An ordinary Recorded Art study lacks its causal Manual source-access packet.", record_id=record_id, source_access_event_id=training_source_access_event_id)
    source_access_record = event_records.get(training_source_access_event_id)
    if (
        not isinstance(source_access_record, dict)
        or source_access_record.get("record_id") != parent_id
        or source_access_record.get("content_type") not in MANUAL_CONTENT_TYPES
    ):
        fail("An ordinary Recorded Art study source-access event is not bound to its locked Manual.", record_id=record_id, source_access_event_id=training_source_access_event_id)
    event_packet = packet_by_event.get(event_id)
    source_packet = packet_by_event.get(training_source_access_event_id)
    if not isinstance(event_packet, str) or not event_packet or not isinstance(source_packet, str) or not source_packet or event_packet == source_packet:
        fail("An ordinary Recorded Art source provenance list is incomplete or aliased.", record_id=record_id)

    target_cl = output_art.get("learned_at_cl")
    if type(target_cl) is not int or target_cl < 1:
        fail("An ordinary Recorded Art has an invalid learned-at CL.", record_id=record_id, learned_at_cl=target_cl)
    computed_dc = transaction.get("computed_dc")
    prior_count = transaction.get("recorded_arts_learned_this_cl_before", 0)
    if type(computed_dc) is not int or computed_dc < 1 or type(prior_count) is not int or prior_count < 0:
        fail("An ordinary Recorded Art training transaction has invalid deterministic learning figures.", record_id=record_id)
    learning_dc = deepcopy(output_art["learning_dc"])
    learning_dc["computed_dc"] = computed_dc
    learning_dc["prior_recorded_arts_this_cl"] = prior_count
    return {
        "record_id": record_id,
        "record_hash": record["record_hash"],
        "display_name": record["display_name"],
        "name": output_art["technique_name"],
        "technique_name": output_art["technique_name"],
        "state": "known",
        "learned_at_cl": target_cl,
        "acquisition_event_id": event_id,
        "acquisition_kind": "manual_training_attempt",
        "parent_manual_record_id": parent_id,
        "parent_manual_name": parent["display_name"],
        "training_source_record_id": training_source_record_id,
        "training_source_access_event_id": training_source_access_event_id,
        "lineage_source": deepcopy(parent_manual.get("lineage_source")),
        "dm_facing_line": output_art["dm_facing_line"],
        "associated_sphere_record_ids": deepcopy(output_art["associated_sphere_record_ids"]),
        "associated_sphere_names": deepcopy(output_art["associated_sphere_names"]),
        "reproduced_component_record_ids": deepcopy(output_art["reproduced_component_record_ids"]),
        "reproduced_component_names": deepcopy(output_art["reproduced_component_names"]),
        "expression_kind": output_art["expression_kind"],
        "learning_dc": learning_dc,
        "study_time": deepcopy(output_art["study_time"]),
        "allowed_study_abilities": deepcopy(output_art["allowed_study_abilities"]),
        "requirements": deepcopy(output_art["requirements"]),
        "execution": deepcopy(output_art["execution"]),
        "execution_derivation": deepcopy(output_art["execution_derivation"]),
        "linked_action_id": output_art["linked_action_id"],
        "fixed_expression_warning": output_art["fixed_expression_warning"],
        "record_text": _display(source_component)[1],
        "source_record_id": source_record_id,
        "source_record_hash": source_component["record_hash"],
        "source_block_sha256": None,
        "source": deepcopy(record.get("source") or {}),
        "outcome": {"result": "success", "mode": "ordinary_training"},
        "counts_against_trained_choices": False,
        "slot_cost": 0,
        "source_packet_ids": [event_packet, source_packet],
        "event_id": event_id,
    }


def _immortal_art_projection_rows(
    events: list[dict[str, Any]],
    *,
    event_records: dict[str, dict[str, Any]],
    locked_records: dict[str, dict[str, Any]],
    packet_by_event: dict[str, str],
    factory_root: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Project automatic Immortal Arts from their authenticated creation events.

    The complete Art is already sealed in the constructed child record.  The
    bridge still checks the event output, parent Subpath progression, and
    installed source bytes so a valid self-hash cannot relabel an unattained
    feature or replace its printed action.
    """
    from character_creation.constructed_arts.immortal_art import immortal_art_progression_child_hash
    from character_creation.constructed_arts.records import immortal_art_record_text
    from character_creation.constructed_arts.sources import installed_factory_root, published_section
    from character_creation.service import _IMMORTAL_FEATURE_SOURCE_ADAPTERS, _authenticated_immortal_feature_action
    from character_creation.constructed_arts.native_immortal_sources import (
        NATIVE_COMMITMENT_KIND, native_feature_hash, native_source_row,
    )
    from character_creation.constructed_arts.immortal_art import _normalize_source

    rows: list[dict[str, Any]] = []
    indexes: dict[str, int] = {}
    seen: set[str] = set()
    for event in sorted(events, key=lambda value: (int(value["sequence"]), value["event_id"])):
        event_id = event["event_id"]
        record = event_records.get(event_id)
        if not isinstance(record, dict) or record.get("content_type") != "immortal_art":
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_INVALID",
                "An Immortal Art creation event has no locked Immortal Art child record.",
                details={"event_id": event_id},
            )
        art = _validated_constructed_art_record(
            record,
            locked_records,
            factory_root=factory_root,
        )
        if not isinstance(art, dict) or art.get("art_id") != record.get("record_id"):
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_INVALID",
                "An Immortal Art event does not rederive its locked child identity.",
                details={"event_id": event_id, "record_id": record.get("record_id")},
            )
        art_id = art["art_id"]
        outputs = ((event.get("advancement") or {}).get("calculation") or {}).get("outputs") or {}
        output_art = outputs.get("immortal_art")
        if not isinstance(output_art, dict) or canonical_json(output_art) != canonical_json(art):
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_INVALID",
                "An Immortal Art event output differs from its authenticated child record.",
                details={"event_id": event_id, "record_id": record.get("record_id")},
            )
        expected_text = immortal_art_record_text(art)
        if outputs.get("immortal_art_record_text") != expected_text:
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_RECORD_TEXT_INVALID",
                "An Immortal Art event does not retain the canonical full record text.",
                details={"event_id": event_id, "record_id": record.get("record_id")},
            )
        if art_id in seen:
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_DUPLICATE",
                "An Immortal Art may receive only one causal creation event.",
                details={"record_id": art_id},
            )
        seen.add(art_id)

        source = art.get("source") if isinstance(art.get("source"), dict) else {}
        native_source = source.get("feature_record_hash_kind") == NATIVE_COMMITMENT_KIND
        commitment_kind = NATIVE_COMMITMENT_KIND if native_source else "subpath_progression_commitment"
        progression = source.get("progression") if isinstance(source.get("progression"), dict) else {}
        source_id = art.get("source_record_id")
        parent_id = progression.get("parent_record_id")
        parent_hash = progression.get("parent_record_hash")
        parent = locked_records.get(parent_id) if isinstance(parent_id, str) else None
        if (
            not isinstance(source_id, str)
            or not isinstance(parent_id, str)
            or not isinstance(parent_hash, str)
            or not isinstance(parent, dict)
            or parent.get("content_type") != ("path" if native_source else "subpath")
            or parent.get("record_hash") != parent_hash
        ):
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_PARENT_INVALID",
                "An Immortal Art does not bind its exact locked parent Subpath.",
                details={"event_id": event_id, "source_record_id": source_id, "parent_record_id": parent_id},
            )
        parent_path_id = parent.get("record_id") if native_source else (parent.get("owning_path_id") or parent.get("parent_path_id"))
        source_path_id = source.get("owning_path_id") or source.get("path_id")
        progression_path_id = progression.get("owning_path_id") or progression.get("parent_path_id")
        if any(
            observed is not None and observed != art.get("path_id")
            for observed in (parent_path_id, source_path_id, progression_path_id)
        ):
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_PATH_PROVENANCE_MISMATCH",
                "An Immortal Art source and parent must remain attached to its powering Path.",
                details={"event_id": event_id, "path_id": art.get("path_id"), "parent_path_id": parent_path_id, "source_path_id": source_path_id, "progression_path_id": progression_path_id},
            )
        parent_authority = ((parent.get("compatibility") or {}).get("factory") or {}).get("stage2_authority") or {}
        feature = next(
            (
                value for value in parent_authority.get("feature_progression") or []
                if isinstance(value, dict) and value.get("canonical_id") == source_id
            ),
            None,
        )
        native_expected = None
        if native_source:
            path_cl = ((art.get("construction") or {}).get("request") or {}).get("owning_path_cl")
            native_expected = native_source_row(
                _BRIDGE_ROOT_DIR, factory_root, feature_id=source_id, parent_record=parent,
                owning_path_cl=path_cl, construction_cl=art["cl_created"],
            )
            native_expected = _normalize_source(native_expected, 0, path_kind=parent_id.rsplit(".", 1)[1],
                                                target_cl=art["cl_created"], owning_path_cl=path_cl)
            feature = native_expected["progression"]["feature_snapshot"]
        if not isinstance(feature, dict):
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_FEATURE_PROVENANCE_MISSING",
                "An Immortal Art source feature is not an authenticated child of its locked Subpath progression.",
                details={"event_id": event_id, "source_record_id": source_id, "parent_record_id": parent_id},
            )
        feature_source = feature.get("source") if isinstance(feature.get("source"), dict) else {}
        source_binding = source.get("source") if isinstance(source.get("source"), dict) else {}
        progression_source = progression.get("source") if isinstance(progression.get("source"), dict) else {}
        adapter = _IMMORTAL_FEATURE_SOURCE_ADAPTERS.get(source_id)
        if native_source:
            adapter = feature_source
        if adapter is None:
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_SOURCE_ADAPTER_UNSUPPORTED",
                "An Immortal Art source has no complete authenticated action adapter.",
                details={"event_id": event_id, "source_record_id": source_id},
            )
        expected_source_id = adapter["source_id"]
        raw_source_id = feature_source.get("source_id")
        expected_path = feature_source.get("factory_source_path") or feature_source.get("path")
        expected_file_hash = feature_source.get("source_file_sha256") or feature_source.get("source_hash")
        expected_section_hash = feature_source.get("section_sha256")
        if (
            (raw_source_id is not None and raw_source_id != expected_source_id)
            or source_binding.get("source_id") != expected_source_id
            or source_binding.get("path") != expected_path
            or source_binding.get("source_hash") != expected_file_hash
            or progression_source.get("source_id") != expected_source_id
            or progression_source.get("path") != expected_path
            or progression_source.get("source_hash") != expected_file_hash
            or not isinstance(expected_section_hash, str)
            or progression.get("source", {}).get("section_sha256") != expected_section_hash
            or not source.get("published_text")
            or source.get("published_text") != published_section(factory_root, progression_source)
        ):
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_SOURCE_BINDING_INVALID",
                "An Immortal Art source does not match its parent Subpath feature's exact source binding.",
                details={"event_id": event_id, "source_record_id": source_id, "parent_record_id": parent_id},
            )
        exact_source = {
            "source_id": adapter["source_id"],
            "path": expected_path,
            "anchor": f"line:{adapter['line_start']}",
            "source_hash": adapter["source_file_sha256"],
            "factory_source_path": expected_path,
            "source_file_sha256": adapter["source_file_sha256"],
            "line_start": adapter["line_start"],
            "line_end": adapter["line_end"],
            "section_sha256": adapter["section_sha256"],
        }
        try:
            if native_source:
                expected_action, expected_dependencies = native_expected["action_surface"], native_expected["source_dependencies"]
            else:
                expected_action, expected_dependencies = _authenticated_immortal_feature_action(
                    source_id, source["published_text"], factory_root, exact_source,
                )
        except FoundryError as exc:
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_SOURCE_DEPENDENCY_UNAVAILABLE",
                "A required Immortal Art source dependency is missing or hash-drifted in the installed pack.",
                details={"event_id": event_id, "source_record_id": source_id, "cause": exc.code},
            ) from exc
        if source.get("action_surface") != expected_action:
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_ACTION_SOURCE_INVALID",
                "An Immortal Art source does not match the complete authenticated feature action.",
                details={"event_id": event_id, "source_record_id": source_id},
            )
        if source.get("source_dependencies") != expected_dependencies:
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_SOURCE_DEPENDENCY_INVALID",
                "An Immortal Art source does not retain the exact server-derived dependency bindings.",
                details={"event_id": event_id, "source_record_id": source_id},
            )

        path_id = art.get("path_id")
        path = locked_records.get(path_id) if isinstance(path_id, str) else None
        if not isinstance(path, dict) or path.get("content_type") != "path":
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_PATH_INVALID",
                "An Immortal Art does not resolve to its locked powering Path.",
                details={"event_id": event_id, "path_id": path_id},
            )
        path_binding = next(
            (
                binding for binding in ((event.get("advancement") or {}).get("authority_bindings") or [])
                if isinstance(binding, dict)
                and binding.get("role") == "immortal_art_path_authority"
                and binding.get("record_id") == path_id
            ),
            None,
        )
        if not isinstance(path_binding, dict) or path_binding.get("record_hash") != path.get("record_hash"):
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_PATH_PROVENANCE_MISSING",
                "An Immortal Art lacks the exact causal powering Path binding.",
                details={"event_id": event_id, "path_id": path_id},
            )

        try:
            expected_feature_hash = (native_feature_hash if native_source else immortal_art_progression_child_hash)(parent_id, parent_hash, feature)
        except FoundryError as exc:
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_FEATURE_RECORD_INVALID",
                "An Immortal Art progression feature commitment is malformed.",
                details={"event_id": event_id, "source_record_id": source_id, "cause": exc.code},
            ) from exc
        acquisition = source.get("acquisition") if isinstance(source.get("acquisition"), dict) else {}
        if (
            acquisition.get("feature_record_id") != source_id
            or acquisition.get("parent_record_id") != parent_id
            or acquisition.get("parent_record_hash") != parent_hash
            or acquisition.get("feature_record_hash") != expected_feature_hash
            or acquisition.get("acquired_at_cl") != feature.get("granted_at_cl")
        ):
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_FEATURE_RECORD_INVALID",
                "An Immortal Art source acquisition does not retain its exact parent-bound feature commitment.",
                details={"event_id": event_id, "source_record_id": source_id, "parent_record_id": parent_id},
            )
        feature_snapshot = progression.get("feature_snapshot")
        if (
            source.get("feature_record_hash_kind") != commitment_kind
            or progression.get("feature_record_hash_kind") != commitment_kind
            or not isinstance(feature_snapshot, dict)
            or canonical_json(feature_snapshot) != canonical_json(feature)
            or art.get("source_record_hash") != expected_feature_hash
            or source.get("record_hash") != expected_feature_hash
            or source.get("display_name") != feature.get("display_name")
        ):
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_FEATURE_RECORD_INVALID",
                "An Immortal Art source does not retain the parent-bound progression feature commitment.",
                details={"event_id": event_id, "source_record_id": source_id, "parent_record_id": parent_id},
            )
        source_record = locked_records.get(source_id)
        if native_source:
            native_bindings = [binding for binding in ((event.get("advancement") or {}).get("authority_bindings") or [])
                               if binding.get("role") == "immortal_art_native_feature_authority" and binding.get("record_id") == source_id]
            if (not isinstance(source_record, dict) or source_record.get("content_type") != "path_feature"
                    or len(native_bindings) != 1 or native_bindings[0].get("record_hash") != source_record.get("record_hash")
                    or not native_bindings[0].get("causal_event_id")
                    or (source_record.get("source") or {}).get("source_hash") != feature["native_authority"]["source"]["sha256"]):
                raise FoundryError("PROJECTION_IMMORTAL_ART_FEATURE_RECORD_INVALID", "The native Art lacks its exact causal feature record binding.", details={"event_id": event_id, "source_record_id": source_id})
        elif isinstance(source_record, dict):
            if (
                source_record.get("record_id") != source_id
                or source_record.get("record_hash") != expected_feature_hash
                or source_record.get("display_name") != source.get("display_name")
            ):
                raise FoundryError(
                    "PROJECTION_IMMORTAL_ART_FEATURE_RECORD_INVALID",
                    "An optional Immortal Art child snapshot disagrees with its parent-bound progression commitment.",
                    details={"event_id": event_id, "source_record_id": source_id},
                )

        packet_id = packet_by_event.get(event_id)
        if not isinstance(packet_id, str) or not packet_id:
            raise FoundryError(
                "PROJECTION_IMMORTAL_ART_PACKET_MISSING",
                "An Immortal Art lacks its exact causal event packet.",
                details={"event_id": event_id, "record_id": art_id},
            )
        entry = deepcopy(art)
        entry.update({
            "record_id": art["art_id"],
            "record_hash": record["record_hash"],
            "state": "known",
            "acquisition_event_id": event_id,
            "acquisition_kind": "immortal_art_creation",
            "record_text": expected_text,
            "source_record_ids": sorted({value for value in (art.get("source_record_id"), art.get("path_id"), parent_id) if isinstance(value, str)}),
            "source_packet_ids": [packet_id],
            "event_id": event_id,
            "outcome": deepcopy(outputs.get("outcome") or {}),
            "counts_against_trained_choices": False,
            "slot_cost": 0,
        })
        # A creator Art carries its server-derived Refinement Check history
        # (opening rules 4-6) so the sheet can show how the Art was earned.
        if isinstance(outputs.get("immortal_refinement"), dict):
            entry["refinement"] = deepcopy(outputs["immortal_refinement"])
        indexes[event_id] = len(rows)
        rows.append(entry)
    return rows, indexes


def _recorded_art_projection_rows(
    events: list[dict[str, Any]],
    *,
    event_records: dict[str, dict[str, Any]],
    locked_records: dict[str, dict[str, Any]],
    packet_by_event: dict[str, str],
    factory_root: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Project learned Recorded Arts from their causal acquisition events.

    The event output is a compiled Stage 2 entry, while the locked child record
    remains the source of the exact quoted block and parent/child identity.
    Keeping both surfaces here prevents a client-authored output from relabeling
    or replacing the sealed source text.
    """
    from recorded_art_authority import manual_outcome

    rows: list[dict[str, Any]] = []
    indexes: dict[str, int] = {}
    seen_record_ids: set[str] = set()
    for event in sorted(events, key=lambda value: (int(value["sequence"]), value["event_id"])):
        event_id = event.get("event_id")
        kind = (event.get("advancement") or {}).get("kind")
        advancement = event.get("advancement") or {}
        calculation = advancement.get("calculation") or {}
        outputs = calculation.get("outputs") or {}
        transaction = advancement.get("training_transaction") or {}
        if kind == "manual_training_attempt":
            if transaction.get("result") != "success":
                continue
            if transaction.get("training_type") != "recorded_art":
                raise FoundryError(
                    "PROJECTION_RECORDED_ART_INVALID",
                    "A manual-training event marked successful does not carry a Recorded Art training transaction.",
                    details={"event_id": event_id},
                )
        elif kind == RECORDED_ART_CONSTRUCTION_KIND:
            if outputs.get("outcome") != manual_outcome():
                raise FoundryError(
                    "PROJECTION_RECORDED_ART_INVALID",
                    "A constructed Recorded Art event does not carry its exact non-rolled outcome.",
                    details={"event_id": event_id},
                )
        else:
            continue

        record = event_records.get(event_id)
        if not isinstance(record, dict) or record.get("content_type") != "recorded_art":
            raise FoundryError(
                "PROJECTION_RECORDED_ART_INVALID",
                "A Recorded Art acquisition event has no locked Recorded Art child record.",
                details={"event_id": event_id},
            )
        art = _validated_constructed_art_record(
            record,
            locked_records,
            factory_root=factory_root,
        )
        if kind == "manual_training_attempt" and art is None:
            ordinary_row = _ordinary_recorded_art_projection_row(
                event,
                record=record,
                event_records=event_records,
                locked_records=locked_records,
                packet_by_event=packet_by_event,
            )
            record_id = ordinary_row["record_id"]
            if record_id in seen_record_ids:
                raise FoundryError(
                    "PROJECTION_RECORDED_ART_DUPLICATE",
                    "A Recorded Art may receive only one successful acquisition event in the projected stream.",
                    details={"record_id": record_id},
                )
            seen_record_ids.add(record_id)
            indexes[event_id] = len(rows)
            rows.append(ordinary_row)
            continue
        if not isinstance(art, dict) or art.get("record_id") != record.get("record_id"):
            raise FoundryError(
                "PROJECTION_RECORDED_ART_INVALID",
                "A Recorded Art acquisition event does not rederive its locked child identity.",
                details={"event_id": event_id, "record_id": record.get("record_id")},
            )
        output_art = outputs.get("recorded_art")
        if not isinstance(output_art, dict):
            raise FoundryError(
                "PROJECTION_RECORDED_ART_INVALID",
                "A successful Recorded Art acquisition event lacks its compiled entry.",
                details={"event_id": event_id, "record_id": record.get("record_id")},
            )
        if (
            output_art.get("record_id") != record.get("record_id")
            or output_art.get("record_hash") != record.get("record_hash")
            or output_art.get("parent_manual_record_id") != art.get("parent_manual_record_id")
            or output_art.get("technique_name") != art.get("technique_name")
        ):
            raise FoundryError(
                "PROJECTION_RECORDED_ART_INVALID",
                "A Recorded Art event output is not bound to its locked child record.",
                details={"event_id": event_id, "record_id": record.get("record_id")},
            )
        record_id = record["record_id"]
        if record_id in seen_record_ids:
            raise FoundryError(
                "PROJECTION_RECORDED_ART_DUPLICATE",
                "A Recorded Art may receive only one successful acquisition event in the projected stream.",
                details={"record_id": record_id},
            )
        seen_record_ids.add(record_id)

        parent_id = art.get("parent_manual_record_id")
        parent = locked_records.get(parent_id) if isinstance(parent_id, str) else None
        if not isinstance(parent, dict) or parent.get("content_type") != "manual":
            raise FoundryError(
                "PROJECTION_RECORDED_ART_PARENT_MISSING",
                "A Recorded Art child does not resolve to its locked parent Manual.",
                details={"event_id": event_id, "record_id": record_id, "parent_manual_record_id": parent_id},
            )
        parent_art = _validated_constructed_art_record(
            parent,
            locked_records,
            factory_root=factory_root,
        )
        if not isinstance(parent_art, dict) or parent_art.get("manual_id") != parent_id:
            raise FoundryError(
                "PROJECTION_RECORDED_ART_PARENT_INVALID",
                "A Recorded Art child does not resolve to a rederived Manual parent.",
                details={"event_id": event_id, "record_id": record_id, "parent_manual_record_id": parent_id},
            )

        source_access_event_id: str | None = None
        training_source_record_id: str | None = None
        if kind == "manual_training_attempt":
            training_source_record_id = transaction.get("training_source_record_id")
            source_access_event_id = transaction.get("training_source_access_event_id")
            if training_source_record_id != parent_id:
                raise FoundryError(
                    "PROJECTION_RECORDED_ART_SOURCE_INVALID",
                    "A manual-training Recorded Art must use its parent Manual as the training source.",
                    details={"event_id": event_id, "record_id": record_id},
                )
        else:
            training_source_record_id = parent_id
            parent_binding = next(
                (
                    binding
                    for binding in advancement.get("authority_bindings") or []
                    if isinstance(binding, dict)
                    and binding.get("record_id") == parent_id
                    and binding.get("role") == "recorded_art_parent_manual"
                ),
                None,
            )
            source_access_event_id = parent_binding.get("causal_event_id") if isinstance(parent_binding, dict) else None
        if not isinstance(source_access_event_id, str) or source_access_event_id not in packet_by_event:
            raise FoundryError(
                "PROJECTION_RECORDED_ART_SOURCE_PROVENANCE_MISSING",
                "A Recorded Art lacks the exact causal Manual source-access packet.",
                details={"event_id": event_id, "record_id": record_id, "parent_manual_record_id": parent_id, "source_access_event_id": source_access_event_id},
            )

        derivation = art.get("execution_derivation") or {}
        source_block = derivation.get("source_block")
        source_block_hash = derivation.get("source_block_sha256")
        if (
            derivation.get("mode") != "quote_published_source_block"
            or not isinstance(source_block, str)
            or not source_block.strip()
            or not isinstance(source_block_hash, str)
        ):
            raise FoundryError(
                "PROJECTION_RECORDED_ART_SOURCE_INVALID",
                "A Recorded Art lacks its hash-bound published source block.",
                details={"event_id": event_id, "record_id": record_id},
            )

        learning_dc = output_art.get("learning_dc")
        if not isinstance(learning_dc, dict):
            learning_dc = deepcopy(art.get("learning_dc") or {})
        if kind == "manual_training_attempt":
            learning_dc = {
                **learning_dc,
                "computed_dc": transaction.get("computed_dc"),
                "prior_recorded_arts_this_cl": transaction.get("recorded_arts_learned_this_cl_before", 0),
            }
        else:
            supplied_learning_dc = outputs.get("learning_dc")
            if isinstance(supplied_learning_dc, dict):
                learning_dc = deepcopy(supplied_learning_dc)

        source_packet_ids = [packet_by_event[event_id], packet_by_event[source_access_event_id]]
        # The exact event packet is first; duplicate packet IDs are impossible
        # for a causal source event but fail closed if a malformed chain aliases
        # them.
        if len(source_packet_ids) != len(set(source_packet_ids)):
            raise FoundryError(
                "PROJECTION_RECORDED_ART_SOURCE_PROVENANCE_INVALID",
                "A Recorded Art source provenance list contains duplicate packets.",
                details={"event_id": event_id, "record_id": record_id},
            )
        indexes[event_id] = len(rows)
        rows.append({
            "record_id": record_id,
            "record_hash": record["record_hash"],
            "display_name": record.get("display_name") or record_id,
            "name": art.get("technique_name") or record.get("display_name") or record_id,
            "technique_name": art.get("technique_name"),
            "state": "known",
            "learned_at_cl": int(output_art.get("learned_at_cl", advancement.get("target_cl"))),
            "acquisition_event_id": output_art.get("acquisition_event_id") or event_id,
            "acquisition_kind": kind,
            "parent_manual_record_id": parent_id,
            "parent_manual_name": parent.get("display_name") or parent_id,
            "training_source_record_id": training_source_record_id,
            "training_source_access_event_id": source_access_event_id,
            "lineage_source": deepcopy(parent_art.get("lineage_source") or {}),
            "dm_facing_line": output_art.get("dm_facing_line"),
            "associated_sphere_record_ids": deepcopy(art.get("associated_sphere_record_ids") or []),
            "associated_sphere_names": deepcopy(output_art.get("associated_sphere_names") or []),
            "reproduced_component_record_ids": deepcopy(art.get("reproduced_component_record_ids") or []),
            "reproduced_component_names": deepcopy(output_art.get("reproduced_component_names") or []),
            "expression_kind": art.get("expression_kind"),
            "learning_dc": learning_dc,
            "study_time": deepcopy(art.get("study_time") or {}),
            "allowed_study_abilities": deepcopy(art.get("allowed_study_abilities") or []),
            "requirements": deepcopy(art.get("requirements") or []),
            "execution": deepcopy(output_art.get("execution") or {}),
            "execution_derivation": deepcopy(output_art.get("execution_derivation") or {}),
            "linked_action_id": output_art.get("linked_action_id"),
            "fixed_expression_warning": output_art.get("fixed_expression_warning"),
            "record_text": source_block.strip(),
            "source_record_id": art.get("source_record_id"),
            "source_record_hash": art.get("source_record_hash"),
            "source_block_sha256": source_block_hash,
            "source": deepcopy(record.get("source") or {}),
            "outcome": deepcopy(outputs.get("outcome") if kind == RECORDED_ART_CONSTRUCTION_KIND else {"result": transaction.get("result"), "mode": "ordinary_training"}),
            "counts_against_trained_choices": False,
            "slot_cost": 0,
            "source_packet_ids": source_packet_ids,
            "event_id": event_id,
        })
    return rows, indexes


def _training_source_projection_rows(
    source_events: list[dict[str, Any]],
    *,
    event_records: dict[str, dict[str, Any]],
    locked_records: dict[str, dict[str, Any]],
    packet_by_event: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build compiler-shaped source rows from validated causal access events."""
    rows: list[dict[str, Any]] = []
    row_index_by_event: dict[str, int] = {}
    seen_source_ids: set[str] = set()
    for event in sorted(source_events, key=lambda value: (int(value["sequence"]), value["event_id"])):
        event_id = event.get("event_id")
        record = event_records.get(event_id)
        if not isinstance(record, dict):
            raise FoundryError(
                "PROJECTION_TRAINING_SOURCE_RECORD_MISSING",
                "A source-access event has no locked source record.",
                details={"event_id": event_id},
            )
        metadata = _validate_training_source_access_event(event, record, locked_records)
        source_id = record["record_id"]
        if source_id in seen_source_ids:
            raise FoundryError(
                "PROJECTION_TRAINING_SOURCE_DUPLICATE",
                "A source may receive only one causal access event in the projected stream.",
                details={"event_id": event_id, "record_id": source_id},
            )
        seen_source_ids.add(source_id)
        packet_id = packet_by_event.get(event_id)
        if not isinstance(packet_id, str) or not packet_id:
            raise FoundryError(
                "PROJECTION_TRAINING_SOURCE_PACKET_MISSING",
                "A projected source row must bind to its exact causal event packet.",
                details={"event_id": event_id, "record_id": source_id},
            )
        target_records = metadata["target_records"]
        factory_contract = ((record.get("compatibility") or {}).get("factory") or {}).get("constructed_art")
        manual_payload = factory_contract.get("bundle", {}).get("manual") if isinstance(factory_contract, dict) else None
        collection = manual_payload.get("collection") if isinstance(manual_payload, dict) else None
        learned_ids = set(collection.get("learned_record_ids") or []) if isinstance(collection, dict) else set()
        recorded_art_details = []
        for target in target_records:
            if target.get("content_type") != "recorded_art":
                continue
            target_contract = ((target.get("compatibility") or {}).get("factory") or {}).get("constructed_art")
            target_bundle = target_contract.get("bundle") if isinstance(target_contract, dict) else None
            target_art = next(
                (row for row in (target_bundle.get("recorded_arts") or []) if isinstance(row, dict) and row.get("record_id") == target.get("record_id")),
                None,
            ) if isinstance(target_bundle, dict) else None
            derivation = target_art.get("execution_derivation") if isinstance(target_art, dict) else {}
            recorded_art_details.append({
                "record_id": target.get("record_id"),
                "display_name": target.get("display_name"),
                "record_text": derivation.get("source_block") if isinstance(derivation, dict) else None,
                "source_record_id": target_art.get("source_record_id") if isinstance(target_art, dict) else None,
                "minimum_cl": (target.get("legality") or {}).get("minimum_cl"),
                "state": "known" if target.get("record_id") in learned_ids else "locked",
                "parent_manual_record_id": manual_payload.get("manual_id") if isinstance(manual_payload, dict) else None,
            })
        rows.append({
            "source_id": source_id,
            "allocation_id": f"training_source_access:{event_id}",
            "name": event["subject"]["display_name"],
            "type": metadata["compiler_type"],
            "gained_at_cl": int(event["advancement"]["target_cl"]),
            "contents": {
                "recorded_arts": [
                    target["record_id"]
                    for target in target_records
                    if target.get("content_type") == "recorded_art"
                ],
                "recorded_art_details": recorded_art_details,
                "manual_collection": deepcopy(collection) if isinstance(collection, dict) else None,
                "methods": [],
                "warnings": [],
                "recipes": [],
                "theory": [],
                "false_routes": [],
            },
            "restrictions": [],
            "risks": [],
            "mechanics_granted": [],
            "source_packet_ids": [packet_id],
            "record_hash": record["record_hash"],
        })
        row_index_by_event[event_id] = len(rows) - 1
    return rows, row_index_by_event


def _validate_non_sphere_method_access_event(
    event: dict[str, Any],
    record: dict[str, Any],
    project: dict[str, Any],
    *,
    locked_row: dict[str, Any] | None = None,
) -> None:
    """Validate a server method-access event without projecting mechanics.

    Non-Sphere authority events deliberately bind a complete immutable target
    set rather than one catalog record.  They remain part of the canonical
    event chain and packet audit, but cannot supply Stage 2 ledger mechanics.
    ``record`` is the exact ``project_locked_records`` row the authority
    service bound; when ``locked_row`` carries that row's stored identity the
    record bytes are rehashed against it before any binding comparison.
    """
    if locked_row is not None:
        row_hash = locked_row.get("record_hash")
        if (
            locked_row.get("record_id") != record.get("record_id")
            or not isinstance(row_hash, str)
            or record.get("record_hash") != row_hash
            or canonical_record_hash(record) != row_hash
            or (record.get("content_binding") or {}).get("pack_id") != locked_row.get("pack_id")
            or (record.get("content_binding") or {}).get("pack_version") != locked_row.get("pack_version")
        ):
            raise FoundryError(
                "PROJECTION_NON_SPHERE_AUTHORITY_INVALID",
                "A non-Sphere Method access target no longer matches its immutable project-locked row.",
                details={"event_id": event.get("event_id"), "method_id": record.get("record_id")},
            )
    details = (event.get("advancement") or {}).get("details") or {}
    subject = event.get("subject") or {}
    calculation = (event.get("advancement") or {}).get("calculation") or {}
    bindings = (event.get("advancement") or {}).get("authority_bindings") or []
    target_bindings = [row for row in bindings if row.get("role") != "project_lock_proof"]
    proof_bindings = [row for row in bindings if row.get("role") == "project_lock_proof"]
    invalid = (
        event.get("legal_channel") != "authenticated_project_authority_service"
        or subject.get("content_type") != "non_sphere_authority"
        or subject.get("record_id") != details.get("method_id")
        or details.get("authority_type") != "method_access"
        or details.get("creation_authority") != "AUTHENTICATED_PROJECT_AUTHORITY_SERVICE"
        or details.get("amount_awarded") is not None
        or record.get("record_id") != details.get("method_id")
        or record.get("content_type") != "cultivation_method"
        or record.get("publication", {}).get("status") != "published"
        or len(target_bindings) != 1
        or len(proof_bindings) != 1
        or calculation.get("rule_id") != "non_sphere_authority_commit"
        or (calculation.get("trace") or {}).get("authenticated") is not True
    )
    if invalid:
        raise FoundryError(
            "PROJECTION_NON_SPHERE_AUTHORITY_INVALID",
            "A non-Sphere Method access event failed its server-authority boundary.",
            details={"event_id": event.get("event_id"), "kind": event.get("advancement", {}).get("kind")},
        )

    record_binding = record.get("content_binding") or {}
    target = target_bindings[0]
    target_matches_record = all(
        target.get(key) == expected
        for key, expected in {
            "role": "method",
            "record_id": record.get("record_id"),
            "record_hash": record.get("record_hash"),
            "relationship_id": f"method:{record.get('record_id')}",
            "pack_id": record_binding.get("pack_id"),
            "pack_version": record_binding.get("pack_version"),
            "pack_hash": record_binding.get("pack_hash"),
            "source_id": record.get("record_id"),
            "source_hash": record.get("record_hash"),
        }.items()
    )
    proof = proof_bindings[0]
    proof_matches_shape = all(
        proof.get(key) == expected
        for key, expected in {
            "relationship_id": "project_lock_proof",
            "relationship_hash": proof.get("record_hash"),
            "record_id": "project_lock_proof",
            "record_hash": proof.get("record_hash"),
            "pack_id": "project.lock",
            "pack_version": "HF2",
            "pack_hash": proof.get("record_hash"),
            "source_id": "project_lock_proof",
            "source_hash": proof.get("record_hash"),
        }.items()
    )
    binding = event.get("content_binding") or {}
    canonical_targets = [{
        key: target[key]
        for key in (
            "role", "record_id", "record_hash", "relationship_id", "relationship_hash",
            "pack_id", "pack_version", "pack_hash",
        )
    }]
    expected_target_hash = sha256_json({
        "schema": "Tianxia.CompleteLockedTargetBinding.v1",
        "targets": canonical_targets,
    })
    target_details = {
        key: value
        for key, value in details.items()
        if key not in {"authority_type", "amount_awarded", "creation_authority", "operation_hash"}
    }
    expected_operation_hash = sha256_json({
        "project_id": project["project_id"],
        "kind": "non_sphere_method_access",
        "details": target_details,
        "amount_awarded": None,
        "idempotency_key": event.get("idempotency_key"),
    })
    binding_valid = (
        binding.get("pack_id") == "project.locked.target-set"
        and binding.get("pack_version") == "1"
        and binding.get("pack_hash") == proof.get("record_hash")
        and binding.get("record_hash") == expected_target_hash
        and binding.get("catalog_build_id") == (
            project.get("catalog_build_hash")
            or (project.get("content_lock") or {}).get("catalog_build_id")
            or "catalog.unbuilt"
        )
    )
    if (
        not target_matches_record
        or not proof_matches_shape
        or not binding_valid
        or details.get("operation_hash") != expected_operation_hash
    ):
        raise FoundryError(
            "PROJECTION_NON_SPHERE_AUTHORITY_INVALID",
            "A non-Sphere Method access event has an invalid immutable target or operation binding.",
            details={"event_id": event.get("event_id"), "method_id": details.get("method_id")},
        )


def _validate_non_sphere_method_acquisition_event(
    event: dict[str, Any],
    record: dict[str, Any],
) -> None:
    """Validate the initial Method acquisition as an audited non-mechanical event."""
    advancement = event.get("advancement") or {}
    details = advancement.get("details") or {}
    subject = event.get("subject") or {}
    stage2 = (record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
    raw_projection = ((record.get("compatibility") or {}).get("factory") or {}).get("raw_projection") or {}
    invalid = (
        event.get("legal_channel") != "method-acquisition"
        or subject.get("content_type") != "cultivation_method"
        or subject.get("record_id") != record.get("record_id")
        or not str(record.get("record_id") or "").startswith("METHOD-")
        or record.get("content_type") != "cultivation_method"
        or record.get("publication", {}).get("status") != "published"
        or not (record.get("selected_authority") is True or raw_projection.get("selected_authority") is True)
        or stage2.get("authority_complete") is not True
        or "method_acquisition" not in (stage2.get("allowed_kinds") or [])
        or "method-acquisition" not in (stage2.get("allowed_channels") or [])
        or (details.get("method_id") is not None and details.get("method_id") != record.get("record_id"))
    )
    if invalid:
        raise FoundryError(
            "PROJECTION_NON_SPHERE_AUTHORITY_INVALID",
            "An initial non-Sphere Method acquisition event failed its authenticated authority boundary.",
            details={"event_id": event.get("event_id"), "method_id": record.get("record_id")},
        )


def _validate_non_sphere_foundation_acquisition_event(
    event: dict[str, Any],
    record: dict[str, Any],
) -> None:
    """Validate a named Foundation selection without projecting mechanics."""
    advancement = event.get("advancement") or {}
    details = advancement.get("details") or {}
    subject = event.get("subject") or {}
    stage2 = (record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
    raw_projection = ((record.get("compatibility") or {}).get("factory") or {}).get("raw_projection") or {}
    checks = {
        "legal_channel": event.get("legal_channel") == "foundation-selection",
        "subject_content_type": subject.get("content_type") == "foundation",
        "subject_record_id": subject.get("record_id") == record.get("record_id"),
        "record_content_type": record.get("content_type") == "foundation",
        "published": record.get("publication", {}).get("status") == "published",
        "selected_authority": record.get("selected_authority") is True or raw_projection.get("selected_authority") is True,
        "authority_complete": stage2.get("authority_complete") is True,
        "kind_allowed": "foundation_acquisition" in (stage2.get("allowed_kinds") or []),
        "channel_allowed": "foundation-selection" in (stage2.get("allowed_channels") or []),
        "detail_record_id": details.get("foundation_id") is None or details.get("foundation_id") == record.get("record_id"),
    }
    invalid = not all(checks.values())
    if invalid:
        raise FoundryError(
            "PROJECTION_NON_SPHERE_AUTHORITY_INVALID",
            "A named Foundation acquisition event failed its authenticated authority boundary.",
            details={
                "event_id": event.get("event_id"),
                "foundation_id": record.get("record_id"),
                "checks": checks,
                "legal_channel": event.get("legal_channel"),
                "subject": subject,
                "stage2_authority": stage2,
            },
        )


def _non_sphere_event_provenance(
    event: dict[str, Any],
    record: dict[str, Any],
    contract: dict[str, Any],
    destination: str | list[str],
) -> dict[str, Any]:
    destinations = [destination] if isinstance(destination, str) else list(destination)
    return {
        "provenance_unit": "canonical_non_sphere_authority_event",
        "event_id": event["event_id"],
        "event_hash": event["event_hash"],
        "event_sequence": event["sequence"],
        "record_id": record["record_id"],
        "record_hash": record["record_hash"],
        "pack_id": event["content_binding"]["pack_id"],
        "pack_version": event["content_binding"]["pack_version"],
        "pack_hash": event["content_binding"]["pack_hash"],
        "canonical_sources": deepcopy(event.get("source_evidence") or []),
        "stage2_rule_id": None,
        "projection_contract_id": contract["contract_id"],
        "projection_contract_hash": sha256_json({k: v for k, v in contract.items() if k != "seal_sha256"}),
        "stage2_normalization_authority": deepcopy(contract["stage2_authority_pack"]),
        "exact_source_map": deepcopy(contract["exact_source_map"]),
        "destination_pointers": sorted(destinations),
        "transformation_kind": "NON_SPHERE_AUTHORITY_AUDIT_ONLY",
        "authority_complete": True,
        "mechanical_projection": False,
    }


def _validated_starting_proficiency_lock(
    project: dict[str, Any],
    *,
    path_events: list[dict[str, Any]],
    background_event: dict[str, Any],
    origin_event: dict[str, Any],
    choice_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """Authenticate and normalize the server-derived starting-choice lock.

    Generic v3 projections may only consume the exact lock emitted by the
    character-creation service.  The response maps are revalidated here so a
    caller cannot make a self-consistent project lock become projection
    authority by changing only its outer value or source marker.
    """
    project_id = project.get("project_id")

    def fail(code: str, message: str, **details: Any) -> None:
        raise FoundryError(code, message, details=details)

    if not isinstance(project_id, str) or not project_id.strip():
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "A generic projection requires a project-bound starting-proficiency lock.",
        )
    rows = [
        lock
        for lock in project.get("user_locks") or []
        if isinstance(lock, dict) and lock.get("field") == _STARTING_PROFICIENCY_LOCK_FIELD
    ]
    if not rows:
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_REQUIRED",
            "A generic projection cannot emit starting proficiencies without the server-derived lock.",
        )
    if len(rows) != 1:
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "A generic projection requires exactly one starting-proficiency lock.",
        )
    lock = rows[0]
    value = lock.get("value")
    expected_value_keys = {
        "schema",
        "contract",
        "response_maps",
        "selected_by_slot",
        "validated",
        "binding",
    }
    if (
        lock.get("lock_id") != _STARTING_PROFICIENCY_LOCK_ID
        or lock.get("field") != _STARTING_PROFICIENCY_LOCK_FIELD
        or type(lock.get("created_revision")) is not int
        or lock.get("created_revision") < 0
        or not isinstance(value, dict)
        or set(value) != expected_value_keys
        or value.get("schema") != _STARTING_PROFICIENCY_LOCK_SCHEMA
    ):
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "The starting-proficiency lock shape is not the server-derived contract.",
        )

    value_hash = sha256_json(value)
    expected_source = f"cg1-starting-proficiencies:{value_hash}:server-derived"
    if lock.get("source") != expected_source:
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "The starting-proficiency lock source does not bind its exact value.",
        )

    binding = value.get("binding")
    expected_binding_keys = {
        "schema",
        "run_id",
        "project_id",
        "starting_revision",
        "content_lock_hash",
        "request_sha256",
        "response_sha256",
    }
    if not isinstance(binding, dict) or set(binding) != expected_binding_keys:
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "The starting-proficiency lock is missing its immutable request binding.",
        )
    if (
        binding.get("schema") != _STARTING_PROFICIENCY_LOCK_SCHEMA
        or binding.get("project_id") != project_id
        or not isinstance(binding.get("run_id"), str)
        or not binding["run_id"].strip()
        or type(binding.get("starting_revision")) is not int
        or binding["starting_revision"] < 0
        or not _is_sha256_text(binding.get("content_lock_hash"))
        or not _is_sha256_text(binding.get("request_sha256"))
        or not _is_sha256_text(binding.get("response_sha256"))
    ):
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "The starting-proficiency lock binding is malformed.",
        )
    project_content_lock = project.get("content_lock")
    project_content_hash = (
        project_content_lock.get("lock_hash")
        if isinstance(project_content_lock, dict)
        else None
    ) or project.get("content_lock_hash")
    if (
        not _is_sha256_text(project_content_hash)
        or binding["content_lock_hash"] != project_content_hash
    ):
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "The starting-proficiency lock is bound to a different content lock.",
        )
    if choice_snapshot is not None:
        if (
            not valid_choice_snapshot(choice_snapshot)
            or choice_snapshot.get("canonical_project_id") != project_id
            or choice_snapshot.get("content_lock_hash") != binding["content_lock_hash"]
            or type(choice_snapshot.get("project_revision")) is not int
            or choice_snapshot.get("project_revision") != binding["starting_revision"]
        ):
            fail(
                "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
                "The starting-proficiency lock does not match the authenticated choice snapshot.",
            )

    response_maps = value.get("response_maps")
    selected_by_slot = value.get("selected_by_slot")
    if (
        not isinstance(response_maps, dict)
        or set(response_maps) != set(_STARTING_PROFICIENCY_FIELDS)
        or any(not isinstance(response_maps[field], dict) for field in _STARTING_PROFICIENCY_FIELDS)
        or not isinstance(selected_by_slot, dict)
        or set(selected_by_slot) != set(_STARTING_PROFICIENCY_SLOTS)
        or any(not isinstance(selected_by_slot[slot], list) for slot in _STARTING_PROFICIENCY_SLOTS)
    ):
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "The starting-proficiency lock maps are incomplete or contain extra fields.",
        )

    validated = value.get("validated")
    if not isinstance(validated, dict):
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "The starting-proficiency lock does not retain its validated result.",
        )
    recomputed = validate_starting_proficiency_choices(
        contract=value.get("contract"),
        selected_by_slot=deepcopy(selected_by_slot),
        bounded_choices=deepcopy(response_maps),
    )
    if (
        set(validated) != {
            "schema",
            "valid",
            "blockers",
            "normalized_mechanics",
            "contract_sha256",
            "validation_sha256",
        }
        or validated != recomputed
        or validated.get("valid") is not True
        or validated.get("blockers") != []
    ):
        fail(
            "PROJECTION_STARTING_PROFICIENCY_LOCK_INVALID",
            "The starting-proficiency lock failed pure server validation.",
        )

    selected = validated["normalized_mechanics"].get("selected_by_slot")
    path_ids = [
        event.get("subject", {}).get("record_id")
        for event in path_events
    ]
    background_id = (background_event.get("subject") or {}).get("record_id")
    origin_id = (origin_event.get("subject") or {}).get("record_id")
    selected_paths = selected.get("path_choice") if isinstance(selected, dict) else None
    selected_backgrounds = selected.get("background_choice") if isinstance(selected, dict) else None
    selected_origins = selected.get("origin_insight_choice") if isinstance(selected, dict) else None
    if (
        not isinstance(selected_paths, list)
        or len(selected_paths) != len(set(selected_paths))
        or set(selected_paths) != set(path_ids)
        or not isinstance(selected_backgrounds, list)
        or selected_backgrounds != [background_id]
        or not isinstance(selected_origins, list)
        or selected_origins != [origin_id]
    ):
        fail(
            "PROJECTION_STARTING_PROFICIENCY_SELECTION_MISMATCH",
            "Starting-proficiency selections are not bound to the authenticated event subjects.",
        )

    return {
        "lock": deepcopy(lock),
        "value": deepcopy(value),
        "value_sha256": value_hash,
        "binding": deepcopy(binding),
        "validated": deepcopy(validated),
        "normalized_mechanics": deepcopy(validated["normalized_mechanics"]),
    }


def _project_starting_proficiency_skills(
    normalized: dict[str, Any],
    *,
    path_ids: list[str],
    background_id: str,
    origin_id: str,
    final_mods: dict[str, int],
    final_pb: int,
) -> dict[str, Any]:
    """Build the generic ledger's complete starting-skill projection."""
    path_values = normalized.get("path_skill_choices_by_path_id")
    background = normalized.get("background")
    origin = normalized.get("origin")
    if (
        not isinstance(path_values, dict)
        or not isinstance(background, dict)
        or background.get("background_id") != background_id
        or (isinstance(origin, dict) and origin.get("origin_id") != origin_id)
    ):
        raise FoundryError(
            "PROJECTION_STARTING_PROFICIENCY_MECHANICS_INVALID",
            "The validated starting-proficiency mechanics do not match the authenticated event subjects.",
        )
    selected_skills: list[str] = []
    for path_id in path_ids:
        values = path_values.get(path_id)
        if not isinstance(values, list):
            raise FoundryError(
                "PROJECTION_STARTING_PROFICIENCY_MECHANICS_INVALID",
                "A selected Path has no validated skill projection.",
            )
        for skill in values:
            if skill not in selected_skills:
                selected_skills.append(skill)
    background_skills = background.get("fixed_skill_names")
    background_tools = background.get("fixed_tool_proficiencies")
    selected_languages = background.get("selected_languages")
    origin_skill = origin.get("selected_skill") if isinstance(origin, dict) else None
    # A typed Origin choice is exactly one of a skill or a registry tool.
    origin_tool = origin.get("selected_tool") if isinstance(origin, dict) else None
    origin_trade = origin.get("selected_trade") if isinstance(origin, dict) else None
    origin_language = origin.get("selected_language") if isinstance(origin, dict) else None
    origin_result = origin.get("result") if isinstance(origin, dict) else "catalog_effect"
    origin_picks = [
        value for value in (origin_skill, origin_tool, origin_trade, origin_language)
        if value is not None
    ]
    origin_choice_valid = (
        len(origin_picks) == 1
        and isinstance(origin_picks[0], str)
        and bool(origin_picks[0].strip())
    )
    proficiencies = normalized.get("proficiencies")
    proficiencies = proficiencies if isinstance(proficiencies, dict) else {}
    if (
        not isinstance(background_skills, list)
        or not isinstance(background_tools, list)
        or not isinstance(selected_languages, list)
        or (origin is not None and not isinstance(origin, dict))
        or (origin is not None and not origin_choice_valid)
        or origin_result not in {"expertise", "proficiency", "catalog_effect"}
        # Spelling-insensitive, like the validator's duplicate check: an Origin
        # "herbalism kit" matches a Background's "the herbalism kit".
        or (
            isinstance(origin_tool, str)
            and _tool_key(origin_tool) not in {
                _tool_key(tool) for tool in (proficiencies.get("tools") or []) if isinstance(tool, str)
            }
        )
        or (isinstance(origin_trade, str) and origin_trade not in (proficiencies.get("trades") or []))
        or (isinstance(origin_language, str) and origin_language not in (proficiencies.get("languages") or []))
    ):
        raise FoundryError(
            "PROJECTION_STARTING_PROFICIENCY_MECHANICS_INVALID",
            "The validated starting-proficiency mechanics are incomplete.",
        )
    all_skills: list[str] = []
    for skill in [*selected_skills, *background_skills, origin_skill]:
        if not isinstance(skill, str):
            continue
        if skill not in all_skills:
            all_skills.append(skill)
    proficient_skills = sorted(all_skills)
    skill_ability_map = {
        skill: _SKILL_ABILITY_MAP.get(skill)
        for skill in proficient_skills
    }
    if any(not isinstance(ability, str) for ability in skill_ability_map.values()):
        raise FoundryError(
            "PROJECTION_STARTING_PROFICIENCY_SKILL_UNSUPPORTED",
            "A validated starting-proficiency skill is not in the canonical ability map.",
        )
    multipliers = {
        skill: 2 if origin_result == "expertise" and skill == origin_skill else 1
        for skill in proficient_skills
    }
    if any(skill_ability_map[skill] not in final_mods for skill in proficient_skills):
        raise FoundryError(
            "PROJECTION_STARTING_PROFICIENCY_ABILITY_MODIFIER_MISSING",
            "The canonical ability modifier map is incomplete for starting proficiencies.",
        )
    skills = {
        skill: final_mods[skill_ability_map[skill]] + final_pb * multipliers[skill]
        for skill in proficient_skills
    }
    sources: dict[str, list[str]] = {skill: [] for skill in proficient_skills}
    for path_id in path_ids:
        for skill in path_values[path_id]:
            if path_id not in sources[skill]:
                sources[skill].append(path_id)
    for skill in background_skills:
        if background_id not in sources[skill]:
            sources[skill].append(background_id)
    if isinstance(origin_skill, str) and origin_id not in sources[origin_skill]:
        sources[origin_skill].append(origin_id)
    tool_proficiencies: list[str] = []
    for tool in [*background_tools, *(proficiencies.get("tools") or []), *([origin_tool] if isinstance(origin_tool, str) else [])]:
        if isinstance(tool, str) and _tool_key(tool) not in {_tool_key(seen) for seen in tool_proficiencies}:
            tool_proficiencies.append(tool)
    tool_expertise = [
        tool for tool in (proficiencies.get("tool_expertise") or [])
        if isinstance(tool, str) and tool == origin_tool and origin_result == "expertise"
    ]
    trade_proficiencies = [
        trade for trade in (proficiencies.get("trades") or [])
        if isinstance(trade, str)
    ]
    language_proficiencies: list[str] = []
    for language in [*selected_languages, *(proficiencies.get("languages") or [])]:
        if isinstance(language, str) and language not in language_proficiencies:
            language_proficiencies.append(language)
    return {
        "path_skill_choices_by_path_id": deepcopy(path_values),
        "selected_skills": selected_skills,
        "background_skills": list(background_skills),
        "background_tools": list(background_tools),
        "selected_languages": list(selected_languages),
        "origin_skill": origin_skill,
        "origin_tool": origin_tool,
        "origin_trade": origin_trade,
        "origin_language": origin_language,
        "tool_proficiencies": tool_proficiencies,
        "tool_expertise": tool_expertise,
        "trade_proficiencies": trade_proficiencies,
        "language_proficiencies": language_proficiencies,
        "origin_result": origin_result,
        "proficient_skills": proficient_skills,
        "skill_ability_map": skill_ability_map,
        "skill_proficiency_multipliers": multipliers,
        "skills": skills,
        "skill_sources": sources,
    }


_BRIDGE_ROOT_DIR = Path(__file__).resolve().parents[1]


def reduce_v3(*, root_dir: Path, registry: Any, project: dict[str, Any], events: list[dict[str, Any]], locked_records: dict[str, dict[str, Any]], choice_snapshot: dict[str, Any] | None, state_type: Any, locked_target_rows: dict[str, dict[str, Any]] | None = None, factory_root: Path | None = None) -> Any:
    contract_path = root_dir / "projector" / "contracts" / "C2AR1_Stage2_v3_Projection_Contract.json"
    profile_path = root_dir / "projector" / "contracts" / "C2AR1_Stage_Aware_Validation_Profile.json"
    fixture_path = root_dir / "authority" / "Tianxia_C2AR1_Fixture_Selections_R1.json"
    baseline_path = root_dir / "authority" / "Tianxia_Core_Character_Baseline_Authority_Pack_R1.json"
    language_path = root_dir / "authority" / "Tianxia_Campaign_Language_Binding_Fire_Qi_Proof_R1.json"
    amendment_path = root_dir / "authority" / "Tianxia_Core_Character_Baseline_Owner_Amendment_R1.json"
    stage2_pack_path = root_dir / "catalog" / "typed_authority" / "C1A_Canonical_Typed_Authority_Pack_v1.json"
    source_map_path = root_dir / "catalog" / "typed_authority" / "C1A_Exact_Source_Map_v1.json"
    contract = _read_sealed(contract_path, schema_version="TianxiaFoundry.Stage2V3FactoryProjectionContract.v1", mismatch_code="PROJECTION_V3_CONTRACT_INVALID")
    profile = _read_sealed(profile_path, schema_version="TianxiaFoundry.StageAwareProjectionValidationProfile.v1", mismatch_code="PROJECTION_VALIDATION_PROFILE_INVALID")
    fixture = _read_sealed(fixture_path, schema_version="TianxiaFoundry.OwnerFixtureSelections.v1", mismatch_code="PROJECTION_FIXTURE_SELECTIONS_INVALID")
    baseline = _read_sealed(baseline_path, schema_version="TianxiaFoundry.CoreCharacterBaselineAuthorityPack.v1", mismatch_code="PROJECTION_BASELINE_PACK_INVALID")
    language = _read_sealed(language_path, schema_version="TianxiaFoundry.CampaignLanguageBinding.v1", mismatch_code="PROJECTION_LANGUAGE_BINDING_INVALID")
    amendment = _read_sealed(amendment_path, schema_version="TianxiaFoundry.OwnerRatifiedRuleAmendment.v1", mismatch_code="PROJECTION_OWNER_AMENDMENT_INVALID")
    expected_files = {
        "baseline_pack": (baseline_path, contract["baseline_pack"]["sha256"]),
        "fixture_selection_contract": (fixture_path, contract["fixture_selection_contract"]["sha256"]),
        "validation_profile": (profile_path, contract["validation_profile"]["sha256"]),
        "stage2_authority_pack": (stage2_pack_path, contract["stage2_authority_pack"]["sha256"]),
        "exact_source_map": (source_map_path, contract["exact_source_map"]["sha256"]),
    }
    for label, (path, expected) in expected_files.items():
        if sha256_file(path) != expected:
            raise FoundryError("PROJECTION_AUTHORITY_IDENTITY_MISMATCH", "A projection authority identity does not match the sealed bridge contract.", details={"authority": label, "path": str(path)})
    if sha256_file(amendment_path) != next(rule["source"]["amendment_sha256"] for rule in baseline["rules"] if rule["rule_id"] == "tianxia.core.unarmored_ac.owner_r1"):
        raise FoundryError("PROJECTION_OWNER_AMENDMENT_IDENTITY_MISMATCH", "The owner amendment does not match the baseline pack binding.")
    if sha256_file(language_path) != fixture["authority"]["language"]["binding_sha256"]:
        raise FoundryError("PROJECTION_LANGUAGE_BINDING_IDENTITY_MISMATCH", "The campaign language binding does not match the fixture-selection contract.")

    supported_kinds = set(contract["supported_event_kinds"])
    # The sealed C2A-R.1 contract predates the explicitly causal training-source
    # access event.  Keep the legacy contract bytes unchanged while accepting
    # this newer event only through the stricter typed validation below.
    supported_kinds.add("training_source_access")
    # Creation-training events are part of the newer sealed construction
    # contract.  Preserve the historical bridge bytes while accepting these
    # explicitly validated, constructed outcomes.
    supported_kinds.update(CREATION_TRAINING_KINDS)
    # A new Sphere learned through constructed training grants one same-Sphere
    # bonus Talent as its own acquisition event.  The bridge already projects
    # that kind into the talent ledger and its provenance routes; only the
    # sealed contract list predates it, so accept it alongside the training
    # kinds rather than fail every rival/boss build at projection.
    supported_kinds.add(CREATION_TRAINING_BONUS_KIND)
    # Factory-constructed Forged Techniques compile in Stage 2 from the sealed
    # Core §11 tables; their events project the forged_techniques section.
    supported_kinds.add(FORGED_TECHNIQUE_KIND)
    # A constructed Recorded Art is a separate fixed-expression event.  Manual
    # training attempts remain accepted only when their successful output is
    # bound to the same authenticated child record.
    supported_kinds.add(RECORDED_ART_CONSTRUCTION_KIND)
    supported_kinds.add("manual_training_attempt")
    # Immortal Arts are automatic, source-bound constructions.  Their complete
    # child records and event outputs are rederived below before ledger use.
    supported_kinds.add("immortal_art_creation")
    # Initial activation uses the versioned, independently reconstructed Method
    # mechanics record and the causal order check below.
    supported_kinds.add("method_activation")
    # Equipment acquisitions (the constructed starting kit) project the
    # ledger equipment section; see equipment_rows below.
    supported_kinds.add("equipment_acquisition")
    non_projecting_kinds = set(contract.get("non_projecting_event_kinds") or [])
    # The sealed C2A-R.1 contract predates the normal-wizard initial Method and
    # named Foundation acquisitions.  They are accepted here only as strictly
    # validated audit events; neither contributes projected mechanics.
    non_projecting_kinds.add("method_acquisition")
    non_projecting_kinds.add("foundation_acquisition")
    supported_records = set(contract["supported_record_ids"])
    previous = ZERO_HASH
    by_kind: dict[str, list[dict[str, Any]]] = {}
    event_records: dict[str, dict[str, Any]] = {}
    for expected, event in enumerate(events, start=1):
        report = registry.report(event, V3)
        if not report["valid"]:
            raise FoundryError("PROJECTION_EVENT_SCHEMA_INVALID", "A v3 event failed canonical validation before projection.", details={"event_id": event.get("event_id"), "diagnostics": report["diagnostics"]})
        if event["sequence"] != expected or event["previous_event_hash"] != previous:
            raise FoundryError("PROJECTION_EVENT_CHAIN_BROKEN", "The v3 event stream is not a gap-free canonical chain.", details={"expected": expected, "actual": event.get("sequence")})
        if canonical_event_hash(event) != event["event_hash"]:
            raise FoundryError("PROJECTION_EVENT_HASH_MISMATCH", "A v3 event does not match its canonical event hash.", details={"sequence": expected})
        kind = event["advancement"]["kind"]
        record_id = event["subject"]["record_id"]
        record = locked_records.get(record_id)
        if record is None:
            raise FoundryError("PROJECTION_LOCKED_RECORD_MISSING", "The v3 event record is absent from the canonical locked-record snapshot.", details={"record_id": record_id})
        rr = registry.report(record, "TianxiaFoundry.RulesCatalogRecord.v1")
        if not rr["valid"]:
            raise FoundryError("PROJECTION_RECORD_SCHEMA_INVALID", "A v3 locked record failed canonical validation.", details={"record_id": record_id, "diagnostics": rr["diagnostics"]})
        if kind not in supported_kinds and kind not in non_projecting_kinds:
            raise FoundryError("PROJECTION_V3_KIND_UNSUPPORTED", "The v3 projection contract does not support this advancement kind.", details={"kind": kind, "event_id": event["event_id"]})
        if kind in non_projecting_kinds:
            if kind == "method_acquisition":
                _validate_non_sphere_method_acquisition_event(event, record)
            elif kind == "foundation_acquisition":
                _validate_non_sphere_foundation_acquisition_event(event, record)
            elif kind != "non_sphere_method_access":
                raise FoundryError("PROJECTION_V3_KIND_UNSUPPORTED", "The v3 projection contract declares an unsupported non-projecting event kind.", details={"kind": kind, "event_id": event["event_id"]})
            else:
                # The authority service bound the exact ``project_locked_records``
                # row, not the proof-bound registry projection that serves
                # ``method_acquisition``; validate against what was bound.
                bound = (locked_target_rows or {}).get(record_id)
                if not isinstance(bound, dict) or not isinstance(bound.get("record"), dict) or not isinstance(bound.get("row"), dict):
                    raise FoundryError(
                        "PROJECTION_NON_SPHERE_AUTHORITY_INVALID",
                        "A non-Sphere Method access event names a target that is not an immutable project-locked row.",
                        details={"event_id": event.get("event_id"), "method_id": record_id},
                    )
                _validate_non_sphere_method_access_event(event, bound["record"], project, locked_row=bound["row"])
        else:
            stage2 = (record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
            if record_id not in supported_records and stage2.get("authority_complete") is not True:
                raise FoundryError("PROJECTION_V3_RECORD_AUTHORITY_MISSING", "The selected record is neither sealed by the legacy projection contract nor complete in the project's locked typed catalog authority.", details={"record_id": record_id, "event_id": event["event_id"]})
            if stage2.get("authority_complete") is not True or kind not in (stage2.get("allowed_kinds") or []):
                raise FoundryError("PROJECTION_V3_RECORD_AUTHORITY_MISSING", "The selected record lacks complete Stage 2 authority for this event kind.", details={"record_id": record_id, "kind": kind})
            _validate_binding(
                event,
                record,
                project,
                locked_records=locked_records,
                factory_root=factory_root,
            )
            if kind == "training_source_access":
                _validate_training_source_access_event(event, record, locked_records)
            by_kind.setdefault(kind, []).append(event)
        event_records[event["event_id"]] = record
        previous = event["event_hash"]
    training_source_events = sorted(
        by_kind.get("training_source_access") or [],
        key=lambda event: (int(event["sequence"]), event["event_id"]),
    )
    forged_technique_events = sorted(
        by_kind.get(FORGED_TECHNIQUE_KIND) or [],
        key=lambda event: (int(event["sequence"]), event["event_id"]),
    )
    recorded_art_events = sorted(
        [
            *by_kind.get(RECORDED_ART_CONSTRUCTION_KIND, []),
            *[
                event
                for event in by_kind.get("manual_training_attempt", [])
                if ((event.get("advancement") or {}).get("training_transaction") or {}).get("result") == "success"
                and (event.get("subject") or {}).get("content_type") == "recorded_art"
            ],
        ],
        key=lambda event: (int(event["sequence"]), event["event_id"]),
    )
    immortal_art_events = sorted(
        by_kind.get("immortal_art_creation") or [],
        key=lambda event: (int(event["sequence"]), event["event_id"]),
    )

    locks = _locks(project)
    current_fixture = (
        project.get("project_id") == "40ea751e-7913-557f-b403-a3ec3cd7c004"
        and locks.get("source_reference", {}).get("value")
        == "Accepted C1A owner intent; current catalog authority only"
        and locks.get("character.identity.display_name", {}).get("value")
        == "W5 Current Fire-Qi Owner-Test Fixture"
    )
    historical_fixture = _authenticated_fixture_prefix(project, events, fixture, fixture_path)
    generic_project = not current_fixture and not historical_fixture
    if current_fixture and len(events) != 25:
        raise FoundryError("CG1_CURRENT_PROJECTION_EVENT_COUNT_INVALID", "The bounded current fixture requires the exact 25-event Fire/Qi route.", details={"event_count": len(events)})
    final_display_lock = locks.get("character.identity.final_display_name", {}).get("value")
    final_concept_lock = locks.get("character.identity.final_concept", {}).get("value")
    if isinstance(final_display_lock, dict):
        final_display_lock = final_display_lock.get("value")
    if isinstance(final_concept_lock, dict):
        final_concept_lock = final_concept_lock.get("value")
    if generic_project:
        title_value, title_status = _resolve_project_title(project)
    else:
        # The owner-ratified/current proof contracts intentionally omit title.
        # Do not let a later lock silently turn those historical fixtures into
        # a different projection shape.
        if _TITLE_RAW_LOCK_FIELD in locks or _TITLE_FINAL_LOCK_FIELD in locks:
            raise FoundryError(
                "PROJECTION_OPTIONAL_TITLE_FABRICATED",
                "The owner-approved proof fixture intentionally omitted its optional title.",
            )
        title_value, title_status = None, "OPTIONAL_OMITTED_BY_OWNER"
    required_lock_values = {
        "character.identity.display_name": (
            final_display_lock
            or locks.get("character.identity.display_name", {}).get("value")
            or choice_snapshot.get("display_name_content")
            if generic_project
            else "W5 Current Fire-Qi Owner-Test Fixture"
            if current_fixture
            else fixture["selections"]["display_name"]
        ),
        "character.choices.qi_cultivation_skills": (
            locks.get("character.choices.qi_cultivation_skills", {}).get("value", [])
            if generic_project
            else fixture["selections"]["qi_cultivation_skills"]
        ),
        "character.choices.street_hardened": (
            locks.get("character.choices.street_hardened", {}).get("value")
            if generic_project
            else fixture["selections"]["street_hardened"]
        ),
        "character.choices.language": (
            locks.get("character.choices.language", {}).get("value")
            if generic_project
            else fixture["selections"]["language"]
        ),
    }
    concept_value = final_concept_lock or next(
        lock["value"] for lock in project["user_locks"] if lock["field"] == "concept"
    )
    for field, expected in required_lock_values.items() if not generic_project else ():
        lock = locks.get(field)
        if lock is None or lock.get("value") != expected:
            raise FoundryError("PROJECTION_REQUIRED_OWNER_CHOICE_MISSING", "A required owner-ratified fixture choice is absent or differs from the sealed selection.", details={"field": field})
    language_ids = {entry["language_id"] for entry in language["languages"] if entry.get("selected") is True}
    if not generic_project and required_lock_values["character.choices.language"] not in language_ids:
        raise FoundryError("PROJECTION_LANGUAGE_BINDING_MISSING", "The selected language is not present in the sealed campaign binding.")

    def only(kind: str) -> dict[str, Any]:
        values = by_kind.get(kind) or []
        if len(values) != 1:
            raise FoundryError("PROJECTION_REQUIRED_EVENT_COUNT_INVALID", "A required advancement event kind has the wrong cardinality.", details={"kind": kind, "count": len(values)})
        return values[0]

    start = only("starting_state")
    background = only("background_acquisition")
    origin = only("origin_insight_acquisition")
    path_events = sorted(
        by_kind.get("path_acquisition") or [],
        key=lambda event: (int(event["sequence"]), event["subject"]["record_id"]),
    )
    path_ids = [event["subject"]["record_id"] for event in path_events]
    canonical_all_path_ids = {
        "tianxia.path.body_refining",
        "tianxia.path.qi_cultivation",
        "tianxia.path.spirit_awakening",
    }
    if len(path_events) == 1:
        pass
    elif len(path_events) == len(canonical_all_path_ids) and set(path_ids) == canonical_all_path_ids:
        # The normal wizard may commit the authenticated Method's complete
        # three-Path grant.  Keep the historical single-Path projection
        # shape as the primary view, while retaining every Path below.
        pass
    elif (
        generic_project
        and 1 < len(path_events) < len(canonical_all_path_ids)
        and len(path_ids) == len(set(path_ids))
        and set(path_ids).issubset(canonical_all_path_ids)
    ):
        # A generic production project may deliberately select a bounded
        # subset of the canonical Paths; preserve every selected Path while
        # retaining the primary-path ledger shape below.
        pass
    else:
        raise FoundryError(
            "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
            "The projection requires one Path, a bounded canonical Path subset, or the authenticated canonical three-Path grant.",
            details={"kind": "path_acquisition", "count": len(path_events), "record_ids": path_ids},
        )
    starting_proficiency = (
        _validated_starting_proficiency_lock(
            project,
            path_events=path_events,
            background_event=background,
            origin_event=origin,
            choice_snapshot=choice_snapshot,
        )
        if generic_project
        else None
    )
    path_event = next(
        (event for event in path_events if event["subject"]["record_id"] == "tianxia.path.qi_cultivation"),
        path_events[0] if path_events else None,
    )
    # Path subpaths are an authenticated milestone choice, not a required
    # CL1/CL2 placeholder.  Generic initial-creation projections may therefore
    # have no Subpath event before the first possible selection milestone (CL3).
    # Historical/current fixture projections retain their stricter event
    # contract, and generic projections at/after the milestone still require
    # an exact source-backed event.
    milestone_target_cl = max(
        (
            event.get("advancement", {}).get("target_cl")
            for event in by_kind.get("level_advance") or []
            if isinstance(event.get("advancement", {}).get("target_cl"), int)
        ),
        default=0,
    )
    subpath_events = _validated_subpath_events(
        by_kind.get("subpath_acquisition"),
        generic_project=generic_project,
        milestone_target_cl=milestone_target_cl,
    )

    generic_subpath_owners: dict[str, str] = {}
    if generic_project:
        generic_subpath_owners = _validate_generic_subpath_owners(
            subpath_events,
            event_records,
            path_ids,
        )

    def subpath_parent_path(event: dict[str, Any]) -> str | None:
        if generic_project and event.get("event_id") in generic_subpath_owners:
            return generic_subpath_owners[event["event_id"]]
        record = event_records.get(event.get("event_id")) or {}
        return _explicit_subpath_owner(event, record)

    subpath = next(
        (
            event for event in subpath_events
            if subpath_parent_path(event) == path_event["subject"]["record_id"]
        ),
        None,
    )
    if subpath is None and subpath_events:
        raise FoundryError(
            "PROJECTION_SUBPATH_PRIMARY_OWNER_MISSING",
            "No authenticated Subpath acquisition is bound to the projection's explicit primary Path.",
            details={
                "primary_path_id": path_event["subject"]["record_id"],
                "subpath_event_ids": [event["event_id"] for event in subpath_events],
            },
        )
    level_events = sorted(by_kind.get("level_advance") or [], key=lambda e: e["advancement"]["target_cl"])
    target_cl = max((e["advancement"]["target_cl"] for e in level_events), default=0)
    score_changes = by_kind.get("ability_score_change") or []
    if len(score_changes) > 1 and not generic_project:
        raise FoundryError(
            "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
            "The bounded historical projection permits at most one CL-specific ability-score change event.",
            details={"kind": "ability_score_change", "count": len(score_changes)},
        )
    insight_events = by_kind.get("cultivation_insight_acquisition") or []
    _validated_cl4_selection_authority(
        score_changes,
        insight_events,
        generic_project=generic_project,
        target_cl=target_cl,
    )
    score_change = score_changes[0] if score_changes else None
    if [e["advancement"]["target_cl"] for e in level_events] != list(range(1, target_cl + 1)):
        raise FoundryError("PROJECTION_LEVEL_ADVANCEMENT_INCOMPLETE", "The projection requires a gap-free committed level chain.", details={"target_cl": target_cl})
    ability_history_events = [
        event
        for event in [background, *(score_changes or []), *insight_events]
        if ((event.get("advancement") or {}).get("calculation") or {}).get("outputs", {}).get("ability_scores")
    ]
    ability_history_events.sort(key=lambda event: int(event["sequence"]))
    latest_ability_event = ability_history_events[-1]
    final_scores = deepcopy(latest_ability_event["advancement"]["calculation"]["outputs"]["ability_scores"])
    final_mods = deepcopy(latest_ability_event["advancement"]["calculation"]["outputs"]["ability_modifiers"])
    starting_scores = ((start.get("advancement") or {}).get("calculation") or {}).get("outputs", {}).get("ability_scores")
    background_scores = ((background.get("advancement") or {}).get("calculation") or {}).get("outputs", {}).get("ability_scores")
    if not isinstance(starting_scores, dict) or not isinstance(background_scores, dict) or set(starting_scores) != _CORE_ABILITY_IDS or set(background_scores) != _CORE_ABILITY_IDS or any(
        type(scores.get(ability)) is not int
        for scores in (starting_scores, background_scores)
        for ability in scores
    ):
        raise FoundryError(
            "PROJECTION_BACKGROUND_ABILITY_CHANGE_INVALID",
            "The accepted Background event does not carry complete canonical score outputs.",
            details={"background_id": background["subject"]["record_id"]},
        )
    background_ability_change = {
        ability: background_scores[ability] - starting_scores[ability]
        for ability in sorted(starting_scores)
        if background_scores[ability] != starting_scores[ability]
    }
    final_pb = level_events[-1]["advancement"]["calculation"]["outputs"]["pb"]
    formula_context = {"ability_scores": final_scores, "ability_modifiers": final_mods, "cl": target_cl, "pb": final_pb}
    rules_by_id = {rule["rule_id"]: rule for rule in baseline["rules"]}
    try:
        ac_result = evaluate_formula(rules_by_id["tianxia.core.unarmored_ac.owner_r1"]["formula"]["root"], formula_context)
        init_result = evaluate_formula(rules_by_id["tianxia.core.initiative.owner_r1"]["formula"]["root"], formula_context)
    except FormulaError as exc:
        raise FoundryError("PROJECTION_BASELINE_FORMULA_INVALID", "A sealed core baseline formula could not be evaluated.", details={"error": str(exc)}) from exc

    packet_by_event: dict[str, str] = {event["event_id"]: _packet_id(event) for event in events}
    forged_technique_rows: list[dict[str, Any]] = []
    forged_technique_row_indexes: dict[str, int] = {}
    if forged_technique_events:
        forged_event_context: dict[str, dict[str, Any]] = {}
        for forged_event in forged_technique_events:
            forged_sequence = int(forged_event["sequence"])
            preceding = [event for event in events if int(event.get("sequence", 0)) < forged_sequence]
            technique_record = event_records.get(forged_event["event_id"]) or {}
            technique = (
                ((technique_record.get("compatibility") or {}).get("factory") or {})
                .get("constructed_art", {})
                .get("technique", {})
            )
            path_id = technique.get("powering_path_id") if isinstance(technique, dict) else None
            path_event = next(
                (
                    candidate for candidate in reversed(preceding)
                    if (candidate.get("advancement") or {}).get("kind") == "path_acquisition"
                    and (candidate.get("subject") or {}).get("record_id") == path_id
                ),
                None,
            )
            ability_event = next(
                (
                    candidate for candidate in reversed(preceding)
                    if isinstance(
                        (((candidate.get("advancement") or {}).get("calculation") or {}).get("outputs") or {}).get("ability_modifiers"),
                        dict,
                    )
                ),
                None,
            )
            target_cl = (forged_event.get("advancement") or {}).get("target_cl")
            level_event = next(
                (
                    candidate for candidate in reversed(preceding)
                    if (candidate.get("advancement") or {}).get("kind") == "level_advance"
                    and (candidate.get("advancement") or {}).get("target_cl") == target_cl
                ),
                None,
            )
            forged_event_context[forged_event["event_id"]] = {
                "path_event": path_event,
                "path_record": event_records.get(path_event["event_id"]) if isinstance(path_event, dict) else None,
                "ability_event": ability_event,
                "level_event": level_event,
            }
        forged_technique_rows, forged_technique_row_indexes = _forged_technique_projection_rows(
            forged_technique_events,
            event_records=event_records,
            locked_records=locked_records,
            packet_by_event=packet_by_event,
            event_context_by_id=forged_event_context,
            factory_root=factory_root,
        )
    training_source_rows: list[dict[str, Any]] = []
    training_source_row_indexes: dict[str, int] = {}
    if training_source_events:
        training_source_rows, training_source_row_indexes = _training_source_projection_rows(
            training_source_events,
            event_records=event_records,
            locked_records=locked_records,
            packet_by_event=packet_by_event,
        )
    recorded_art_rows: list[dict[str, Any]] = []
    recorded_art_row_indexes: dict[str, int] = {}
    if recorded_art_events:
        recorded_art_rows, recorded_art_row_indexes = _recorded_art_projection_rows(
            recorded_art_events,
            event_records=event_records,
            locked_records=locked_records,
            packet_by_event=packet_by_event,
            factory_root=factory_root,
        )
    immortal_art_rows: list[dict[str, Any]] = []
    immortal_art_row_indexes: dict[str, int] = {}
    if immortal_art_events:
        immortal_art_rows, immortal_art_row_indexes = _immortal_art_projection_rows(
            immortal_art_events,
            event_records=event_records,
            locked_records=locked_records,
            packet_by_event=packet_by_event,
            factory_root=factory_root,
        )
    packets_list: list[dict[str, Any]] = []
    capability: list[dict[str, Any]] = []
    for event in events:
        record = event_records[event["event_id"]]
        short, full = _display(record)
        packets_list.append({
            "packet_id": packet_by_event[event["event_id"]],
            "event_id": event["event_id"],
            "event_hash": event["event_hash"],
            "sequence": event["sequence"],
            "target_cl": event["advancement"]["target_cl"],
            "advancement_kind": event["advancement"]["kind"],
            "record_id": record["record_id"],
            "record_hash": record["record_hash"],
            "display_name": event["subject"]["display_name"],
            "short_description": short,
            "full_description": full,
            "stage2_rule_id": event["advancement"]["calculation"]["rule_id"],
            "source_evidence": deepcopy(event.get("source_evidence") or []),
            "content_binding": deepcopy(event["content_binding"]),
        })
        if event["advancement"]["kind"] not in non_projecting_kinds:
            capability.append(_capability_entry(record, event["advancement"]["target_cl"], event))
    # Include source-granted Subpath features without inventing independent
    # events.  There may be one exact Subpath binding for each selected Path.
    granted_ids_by_subpath_event: dict[str, list[str]] = {}
    subpath_events_by_id = {
        event["event_id"]: event
        for event in subpath_events
    }
    for subpath_event in subpath_events:
        granted_ids = (
            subpath_event["advancement"]["calculation"]["outputs"].get("granted_feature_record_ids")
            or []
        )
        granted_ids_by_subpath_event[subpath_event["event_id"]] = list(granted_ids)
        for granted_id in granted_ids:
            record = locked_records.get(granted_id)
            granted_authority = ((record or {}).get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
            if record is None or (granted_id not in supported_records and granted_authority.get("authority_complete") is not True):
                raise FoundryError("PROJECTION_V3_RECORD_AUTHORITY_MISSING", "A source-granted feature lacks complete locked typed authority.", details={"record_id": granted_id, "subpath_event_id": subpath_event["event_id"]})
            capability.append(_capability_entry(record, 3, subpath_event))
    granted_ids = sorted({
        granted_id
        for values in granted_ids_by_subpath_event.values()
        for granted_id in values
    })

    spheres = []
    sphere_packets: dict[str, dict[str, Any]] = {}
    for kind, acquisition_type in (
        ("background_sphere_acquisition", "background_sphere"),
        ("ai_bootstrap_sphere_acquisition", "level_1_sphere"),
        ("sphere_training_attempt", "sphere_training"),
        (CREATION_TRAINING_SPHERE_KIND, "creation_training"),
    ):
        for event in by_kind.get(kind) or []:
            if kind == "sphere_training_attempt" and ((event.get("advancement") or {}).get("training_transaction") or {}).get("result") != "success":
                continue
            record = _sphere_record_with_event_authority(event_records[event["event_id"]], event)
            sphere_packet = normalize_sphere_automatic_components(record, acquisition_event=event)
            sphere_id = event["subject"]["record_id"]
            sphere_packets[sphere_id] = sphere_packet
            spheres.append({
                "sphere_id": sphere_id,
                "name": event["subject"]["display_name"],
                "gained_at_cl": event["advancement"]["target_cl"],
                "acquisition_type": acquisition_type,
                "source_packet_ids": [packet_by_event[event["event_id"]]],
                "allocation_id": f"allocation.{event['event_id']}",
                "automatic_component_authority": deepcopy(sphere_packet),
                "automatic_component_ids": deepcopy(sphere_packet["component_ids"]),
                "automatic_base_abilities": deepcopy(sphere_packet["components"]),
            })
    spheres.sort(key=lambda x: (x["gained_at_cl"], x["sphere_id"]))
    automatic_sphere_component_receipts = [
        {
            "schema_version": packet["schema_version"],
            "parent_sphere_id": packet["parent_sphere_id"],
            "parent_record_hash": packet.get("parent_record_hash"),
            "package_hash": packet["package_hash"],
            "component_ids": deepcopy(packet["component_ids"]),
            "components": deepcopy(packet["components"]),
            "acquisition": deepcopy(packet.get("acquisition") or {}),
        }
        for packet in sorted(sphere_packets.values(), key=lambda row: row["parent_sphere_id"])
    ]
    automatic_sphere_components = []
    component_by_id: dict[str, dict[str, Any]] = {}
    for receipt in automatic_sphere_component_receipts:
        for component in receipt["components"]:
            prior = component_by_id.get(component["component_id"])
            if prior is not None and prior["component_hash"] != component["component_hash"]:
                raise FoundryError(
                    "SPHERE_AUTOMATIC_COMPONENT_CONFLICT",
                    "The projection encountered conflicting bytes for one automatic Sphere component ID.",
                    details={"component_id": component["component_id"]},
                )
            if prior is None:
                component_by_id[component["component_id"]] = deepcopy(component)
    automatic_sphere_components = [component_by_id[key] for key in sorted(component_by_id)]
    sphere_names = {
        sphere["sphere_id"]: sphere["name"]
        for sphere in spheres
    }
    talents = []
    for kind, acquisition_type in (
        ("background_talent_acquisition", "background_talent"),
        ("ai_bootstrap_talent_acquisition", "new_sphere_bonus"),
        ("new_sphere_bonus_talent_acquisition", "new_sphere_bonus"),
        ("level_talent_acquisition", "free_level"),
        (CREATION_TRAINING_TALENT_KIND, "creation_training"),
    ):
        for event in by_kind.get(kind) or []:
            rid = event["subject"]["record_id"]
            record = event_records[event["event_id"]]
            stage2 = record["compatibility"]["factory"]["stage2_authority"]
            sphere_id = stage2.get("sphere_id")
            sphere_name = sphere_names.get(sphere_id, str(sphere_id or "Unbound"))
            talents.append({
                "talent_id": rid,
                "name": event["subject"]["display_name"].title() if event["subject"]["display_name"].isupper() else event["subject"]["display_name"],
                "sphere": sphere_name,
                "gained_at_cl": event["advancement"]["target_cl"],
                "acquisition_type": acquisition_type,
                "mechanical_summary": _display(record)[0],
                "source_packet_ids": [packet_by_event[event["event_id"]]],
                "allocation_id": f"allocation.{event['event_id']}",
            })
    talents.sort(key=lambda x: (x["gained_at_cl"], x["talent_id"]))

    insights = []
    for event in sorted(by_kind.get("cultivation_insight_acquisition") or [], key=lambda row: int(row["sequence"])):
        record = event_records[event["event_id"]]
        outputs = (event.get("advancement") or {}).get("calculation", {}).get("outputs") or {}
        occurrence = deepcopy(outputs.get("insight_occurrence") or {})
        # The owner-facing sheet needs an Insight's printed rules text, not just
        # its name.  The locked record carries it; the ledger row did not.
        _insight_short, _insight_full = _display(record)
        insights.append({
            "insight_id": event["subject"]["record_id"],
            "name": event["subject"]["display_name"],
            "one_line_description": _insight_short,
            "full_description": _insight_full,
            "gained_at_cl": event["advancement"]["target_cl"],
            "repeat_index": occurrence.get("repeat_index", (event.get("advancement") or {}).get("details", {}).get("repeat_index", 1)),
            "ability": occurrence.get("ability"),
            "amount": occurrence.get("amount"),
            "ability_change_applied": bool(outputs.get("ability_change_applied")),
            "source_packet_ids": [packet_by_event[event["event_id"]]],
            "source_record_hash": record["record_hash"],
            "source_evidence": deepcopy(event.get("source_evidence") or []),
        })

    features = []
    acquired_feature_ids: list[str] = []
    level_feature_sources: dict[str, list[dict[str, Any]]] = {}
    for event in level_events:
        record = event_records[event["event_id"]]
        outputs = (event.get("advancement") or {}).get("calculation", {}).get("outputs") or {}
        # Stage 2 records every feature the Path grants at this level; the
        # event subject is only the representative one.  A Body Refiner's
        # CL1 grants four features (Tempered Response, Unarmored Defense,
        # Iron Fist, Stomping Step) and the ledger must carry all of them.
        automatic_ids = [value for value in outputs.get("automatic_feature_record_ids") or [] if isinstance(value, str) and value]
        automatic_names = outputs.get("automatic_feature_display_names") or []
        names_by_id = {fid: name for fid, name in zip(automatic_ids, automatic_names) if isinstance(name, str)}
        feature_ids = [event["subject"]["record_id"]] + [fid for fid in automatic_ids if fid != event["subject"]["record_id"]]
        for feature_id in feature_ids:
            if feature_id != event["subject"]["record_id"]:
                level_feature_sources.setdefault(feature_id, []).append({
                    "event_id": event["event_id"],
                    "packet_id": packet_by_event[event["event_id"]],
                    "target_cl": event["advancement"]["target_cl"],
                })
            feature_record = record if feature_id == event["subject"]["record_id"] else locked_records.get(feature_id)
            summary = _display(feature_record)[0] if isinstance(feature_record, dict) else ""
            features.append({
                "feature_id": feature_id,
                "allocation_id": f"allocation.{event['event_id']}" if feature_id == event["subject"]["record_id"] else f"allocation.{event['event_id']}.{feature_id}",
                "name": event["subject"]["display_name"] if feature_id == event["subject"]["record_id"] else (names_by_id.get(feature_id) or (feature_record or {}).get("display_name") or feature_id),
                "gained_at_cl": event["advancement"]["target_cl"],
                "mechanical_summary": summary,
                "source_packet_ids": [packet_by_event[event["event_id"]]],
                "category": "path_feature",
            })
            acquired_feature_ids.append(feature_id)
    for subpath_event in subpath_events:
        for granted_id in granted_ids_by_subpath_event.get(subpath_event["event_id"], []):
            record = locked_records[granted_id]
            features.append({
                "feature_id": granted_id,
                "allocation_id": f"allocation.{subpath_event['event_id']}.{granted_id}",
                "name": record.get("display_name") or granted_id,
                "gained_at_cl": 3,
                "mechanical_summary": _display(record)[0],
                "source_packet_ids": [packet_by_event[subpath_event["event_id"]]],
                "category": "subpath_feature",
                "grant_source_record_id": subpath_event["subject"]["record_id"],
                "owning_path_id": subpath_parent_path(subpath_event),
            })
            acquired_feature_ids.append(granted_id)
    features.sort(key=lambda x: (x["gained_at_cl"], x["feature_id"]))
    # Passive statistics granted by acquired features: the Path's own base AC
    # calculation replaces the 10 + DEX baseline when it applies.
    statistic_formulas = load_path_feature_statistic_formulas(root_dir)
    armor_class = resolve_armor_class(
        statistic_formulas,
        acquired_feature_ids,
        baseline_rule=rules_by_id["tianxia.core.unarmored_ac.owner_r1"],
        baseline_value=ac_result.value,
        baseline_trace=ac_result.trace,
        context=formula_context,
    )

    def primary_resource_id(resources: dict[str, Any]) -> str:
        if "tianxia.resource.qi" in resources:
            return "tianxia.resource.qi"
        if not resources:
            raise FoundryError(
                "PROJECTION_RESOURCE_AUTHORITY_MISSING",
                "The final level calculation contains no authenticated primary resource.",
            )
        return sorted(resources)[0]

    def resource_display_name(resource_id: str) -> str:
        return {
            "tianxia.resource.qi": "Qi",
            "tianxia.resource.stamina": "Stamina",
            "tianxia.resource.resonance": "Resonance",
        }.get(resource_id, resource_id.rsplit(".", 1)[-1].replace("_", " ").title())

    levels = []
    cumulative_talents: list[str] = []
    talent_by_cl: dict[int, list[str]] = {}
    for t in talents:
        talent_by_cl.setdefault(t["gained_at_cl"], []).append(t["talent_id"])

    trained_choices_by_cl: dict[int, list[dict[str, Any]]] = {}
    for event in by_kind.get(CREATION_TRAINING_SPHERE_KIND, []) + by_kind.get(CREATION_TRAINING_TALENT_KIND, []):
        creation = ((event.get("advancement") or {}).get("calculation") or {}).get("outputs", {}).get("creation_training")
        if not isinstance(creation, dict):
            raise FoundryError(
                "PROJECTION_CREATION_TRAINING_MISSING",
                "A creation-training event lacks its constructed semantic choice output.",
                details={"event_id": event.get("event_id")},
            )
        choice = {
            "cl": int(event["advancement"]["target_cl"]),
            "slot": creation.get("slot"),
            "choice_type": creation.get("choice_type"),
            "record_id": event["subject"]["record_id"],
            "source": deepcopy(creation.get("source")),
            "outcome": deepcopy(creation.get("outcome")),
        }
        if creation.get("bonus_talent_id") is not None:
            choice["bonus_talent_id"] = creation.get("bonus_talent_id")
        choice = canonical_trained_choice(choice)
        issues = validate_trained_choice_shape(choice)
        if issues:
            raise FoundryError(
                "PROJECTION_CREATION_TRAINING_INVALID",
                "A creation-training event failed its canonical semantic choice validation.",
                details={"event_id": event.get("event_id"), "issues": issues},
            )
        trained_choices_by_cl.setdefault(choice["cl"], []).append(choice)
    for choices in trained_choices_by_cl.values():
        choices.sort(key=lambda value: int(value["slot"]))

    def ability_scores_after(sequence: int) -> dict[str, int]:
        for history_event in reversed(ability_history_events):
            if int(history_event["sequence"]) <= sequence:
                return deepcopy(history_event["advancement"]["calculation"]["outputs"]["ability_scores"])
        return deepcopy(background["advancement"]["calculation"]["outputs"]["ability_scores"])

    for event in level_events:
        cl = event["advancement"]["target_cl"]
        out = event["advancement"]["calculation"]["outputs"]
        for rid in sorted(talent_by_cl.get(cl, [])):
            cumulative_talents.append(rid)
        hp_total = out["hp_after"]["total"]
        resource = out["resources_after"][primary_resource_id(out.get("resources_after") or {})]
        levels.append({
            "cl": cl,
            "realm": _realm_for_cl(cl),
            "pb": out["pb"],
            "hp": {"gain": out["hp_after"]["last_gain"], "max_after_level": hp_total, "formula_id": out["hp_after"]["last_formula_id"]},
            "resource": {"resource_id": resource["resource_id"], "maximum": resource["maximum"], "current_after_event": resource["current"], "formula_id": resource["formula_id"]},
            "ability_scores_after": ability_scores_after(int(event["sequence"])),
            "feature_record_id": event["subject"]["record_id"],
            "trained_choices": deepcopy(trained_choices_by_cl.get(cl, [])),
            "talent_record_ids_gained": sorted(talent_by_cl.get(cl, [])),
            "talent_record_ids_known": sorted(cumulative_talents),
            "state_after_hash": event["state_after_hash"],
            "event_id": event["event_id"],
        })
    # CL1 must show the starting and background/bootstrap talents as known.
    cl1_initial = sorted([t["talent_id"] for t in talents if t["gained_at_cl"] == 1])
    levels[0]["talent_record_ids_known"] = cl1_initial
    for idx in range(1, len(levels)):
        prior = set(levels[idx - 1]["talent_record_ids_known"])
        levels[idx]["talent_record_ids_known"] = sorted(prior | set(levels[idx]["talent_record_ids_gained"]))

    typed_none: dict[str, Any] = {}
    for event in by_kind.get("typed_none") or []:
        target = event["advancement"]["details"].get("target")
        if target not in {"method", "foundation", "manuals", "equipment", "forged_techniques", "immortal_arts"}:
            raise FoundryError("PROJECTION_TYPED_NONE_TARGET_UNSUPPORTED", "The v3 projection contract does not support this typed-none target.", details={"target": target})
        typed_none[target] = deepcopy(event["advancement"]["none_state"])
    source_ids = [event["subject"]["record_id"] for event in training_source_events]
    if len(source_ids) != len(set(source_ids)):
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_DUPLICATE",
            "A source may receive only one causal access event in the projected stream.",
            details={"record_ids": source_ids},
        )
    manuals_none_events = sorted(
        (
            event
            for event in by_kind.get("typed_none") or []
            if (event["advancement"].get("details") or {}).get("target") == "manuals"
        ),
        key=lambda event: int(event["sequence"]),
    )
    if training_source_events and any(
        int(source_event["sequence"]) < int(none_event["sequence"])
        for source_event in training_source_events
        for none_event in manuals_none_events
    ):
        raise FoundryError(
            "PROJECTION_TRAINING_SOURCE_MANUALS_ORDER_CONFLICT",
            "A later Manuals typed-none event cannot silently override an earlier causal training-source access.",
            details={
                "source_event_ids": [event["event_id"] for event in training_source_events],
                "manuals_typed_none_event_ids": [event["event_id"] for event in manuals_none_events],
            },
        )
    if training_source_events:
        # Source access is the current Manuals/lineage resolution.  Historical
        # typed-none events remain in the event and packet chains, but the
        # current typed-none projection is intentionally omitted.
        typed_none.pop("manuals", None)
    forged_none_events = sorted(
        (
            event
            for event in by_kind.get("typed_none") or []
            if (event["advancement"].get("details") or {}).get("target") == "forged_techniques"
        ),
        key=lambda event: int(event["sequence"]),
    )
    if forged_technique_events and any(
        int(creation_event["sequence"]) < int(none_event["sequence"])
        for creation_event in forged_technique_events
        for none_event in forged_none_events
    ):
        raise FoundryError(
            "PROJECTION_FORGED_TECHNIQUE_NONE_ORDER_CONFLICT",
            "A later Forged Technique typed-none event cannot silently override an earlier causal creation.",
            details={"creation_event_ids": [event["event_id"] for event in forged_technique_events]},
        )
    if forged_technique_events:
        typed_none.pop("forged_techniques", None)
    immortal_none_events = sorted(
        (
            event
            for event in by_kind.get("typed_none") or []
            if (event["advancement"].get("details") or {}).get("target") == "immortal_arts"
        ),
        key=lambda event: int(event["sequence"]),
    )
    if immortal_art_events and any(
        int(creation_event["sequence"]) < int(none_event["sequence"])
        for creation_event in immortal_art_events
        for none_event in immortal_none_events
    ):
        raise FoundryError(
            "PROJECTION_IMMORTAL_ART_NONE_ORDER_CONFLICT",
            "A later Immortal Art typed-none event cannot silently override an earlier causal creation.",
            details={"creation_event_ids": [event["event_id"] for event in immortal_art_events]},
        )
    if immortal_art_events:
        typed_none.pop("immortal_arts", None)
    method_acquisition_events = [
        event for event in events
        if event["advancement"]["kind"] == "method_acquisition"
    ]
    foundation_acquisition_events = [
        event for event in events
        if event["advancement"]["kind"] == "foundation_acquisition"
    ]
    if len(method_acquisition_events) > 1:
        raise FoundryError(
            "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
            "The initial proof stream may contain at most one authenticated Method acquisition.",
            details={"kind": "method_acquisition", "count": len(method_acquisition_events)},
        )
    if len(foundation_acquisition_events) > 1:
        raise FoundryError(
            "PROJECTION_REQUIRED_EVENT_COUNT_INVALID",
            "The initial proof stream may contain at most one authenticated Foundation acquisition.",
            details={"kind": "foundation_acquisition", "count": len(foundation_acquisition_events)},
        )
    # Equipment present in the causal stream (e.g. the constructed starting
    # kit) replaces the typed-none equipment section.
    equipment_events = sorted(
        by_kind.get("equipment_acquisition") or [],
        key=lambda event: (int(event["sequence"]), event["event_id"]),
    )
    equipment_rows: list[dict[str, Any]] = []
    for event in equipment_events:
        record_id = event["subject"]["record_id"]
        record = locked_records[record_id]
        equipment_row: dict[str, Any] = {
            "record_id": record_id,
            "name": record.get("display_name") or record_id,
            "content_type": record.get("content_type"),
            "gained_at_cl": int(event["advancement"]["target_cl"]),
            "acquisition_event_id": event["event_id"],
        }
        constructed = ((record.get("compatibility") or {}).get("factory") or {}).get("constructed_art")
        kit = constructed.get("kit") if isinstance(constructed, dict) and constructed.get("kind") == "starting_kit" else None
        if isinstance(kit, dict):
            resolved = kit.get("resolved") or {}
            equipment_row["starting_kit"] = {
                "kit_id": kit.get("kit_id"),
                "background_id": kit.get("background_id"),
                "path_id": kit.get("path_id"),
                "path_option": kit.get("path_option"),
                "picks": deepcopy(kit.get("picks") or {}),
                **({"purchases": list(kit["purchases"])} if kit.get("purchases") else {}),
                "seed": kit.get("seed"),
                "items": deepcopy(resolved.get("items") or []),
                "trinkets": deepcopy(resolved.get("trinkets") or []),
                "coin_cc": resolved.get("coin_cc"),
                "printed_coin_rolls": deepcopy(resolved.get("printed_coin_rolls") or []),
                "choices": deepcopy(resolved.get("choices") or []),
                **({"treasure_weapon": deepcopy(kit["treasure_weapon"])} if kit.get("treasure_weapon") else {}),
                **({"resolved_treasure_weapon": deepcopy(resolved["treasure_weapon"])} if resolved.get("treasure_weapon") else {}),
                **({"treasure_armor": deepcopy(kit["treasure_armor"])} if kit.get("treasure_armor") else {}),
                **({"resolved_treasure_armor": deepcopy(resolved["treasure_armor"])} if resolved.get("treasure_armor") else {}),
                **({"treasure_purchases": deepcopy(kit["treasure_purchases"])} if kit.get("treasure_purchases") else {}),
                **({"resolved_treasure_purchases": deepcopy(resolved["treasure_purchases"])} if resolved.get("treasure_purchases") else {}),
            }
        equipment_rows.append(equipment_row)
    if equipment_events:
        typed_none.pop("equipment", None)
    required_typed_none_targets = set() if equipment_events else {"equipment"}
    if not training_source_events:
        required_typed_none_targets.add("manuals")
    if not forged_technique_events:
        required_typed_none_targets.add("forged_techniques")
    if target_cl >= 15 and not immortal_art_events:
        required_typed_none_targets.add("immortal_arts")
    missing_typed_none_targets = sorted(required_typed_none_targets - set(typed_none))
    if (
        missing_typed_none_targets
        or (not method_acquisition_events and "method" not in typed_none)
        or (not foundation_acquisition_events and "foundation" not in typed_none)
    ):
        raise FoundryError("PROJECTION_REQUIRED_FIELD_AUTHORITY_MISSING", "The proof stream does not contain all required exact typed-none sections.", details={"present": sorted(typed_none)})
    if method_acquisition_events and "method" in typed_none:
        raise FoundryError(
            "PROJECTION_METHOD_AUTHORITY_CONFLICT",
            "An authenticated Method acquisition and a typed-none Method cannot both be present.",
            details={"method_event_id": method_acquisition_events[0]["event_id"]},
        )
    if foundation_acquisition_events and "foundation" in typed_none:
        raise FoundryError(
            "PROJECTION_FOUNDATION_AUTHORITY_CONFLICT",
            "An authenticated Foundation acquisition and a typed-none Foundation cannot both be present.",
            details={"foundation_event_id": foundation_acquisition_events[0]["event_id"]},
        )
    method_projection = deepcopy(typed_none.get("method"))
    if by_kind.get("method_activation") and not method_acquisition_events:
        raise FoundryError(
            "PROJECTION_METHOD_MECHANICS_INVALID",
            "A Method activation must have an acquired Method in the same causal stream.",
            details={"reason": "activation_without_acquisition"},
        )
    if method_acquisition_events:
        method_event = method_acquisition_events[0]
        method_record = event_records[method_event["event_id"]]
        method_projection = {
            "state": "acquired",
            "status": "acquired",
            "record_id": method_record["record_id"],
            "display_name": method_event["subject"]["display_name"],
            "event_id": method_event["event_id"],
            "record_hash": method_record["record_hash"],
            "source_packet_ids": [packet_by_event[method_event["event_id"]]],
            "mechanical_projection": False,
        }
        from projector.method_mechanics import project_initial_method_mechanics

        active_method = project_initial_method_mechanics(
            root_dir, method_record, events, packet_by_event,
        )
        if active_method is not None:
            method_projection.update(active_method)
    foundation_projection = deepcopy(typed_none.get("foundation"))
    active_foundation = None
    if foundation_acquisition_events:
        foundation_event = foundation_acquisition_events[0]
        foundation_record = event_records[foundation_event["event_id"]]
        foundation_projection = {
            "state": "acquired",
            "status": "acquired",
            "record_id": foundation_record["record_id"],
            "display_name": foundation_event["subject"]["display_name"],
            "event_id": foundation_event["event_id"],
            "record_hash": foundation_record["record_hash"],
            "source_packet_ids": [packet_by_event[foundation_event["event_id"]]],
            "mechanical_projection": False,
        }
        from projector.foundation_mechanics import project_initial_foundation_mechanics
        active_foundation = project_initial_foundation_mechanics(foundation_record, events, packet_by_event)
        if active_foundation is not None:
            foundation_projection.update(active_foundation)

    background_record = event_records[background["event_id"]]
    origin_record = event_records[origin["event_id"]]
    last_level_out = level_events[-1]["advancement"]["calculation"]["outputs"]
    if active_foundation is not None:
        # The new version follows all causal adjustments, including an
        # installation or ASI after the target level. Legacy packets retain
        # their historical projection contract.
        last_level_out = deepcopy(last_level_out)
        for event in sorted(events, key=lambda value: value["sequence"]):
            outputs = ((event.get("advancement") or {}).get("calculation") or {}).get("outputs") or {}
            for field in ("hp_after", "resources_after"):
                if field in outputs:
                    last_level_out[field] = deepcopy(outputs[field])
    primary_resource = last_level_out["resources_after"][primary_resource_id(last_level_out.get("resources_after") or {})]
    key_ability = ((event_records[path_event["event_id"]].get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}).get("key_ability", "INT")
    attack_bonus = final_mods[key_ability] + final_pb
    save_dc = 8 + final_mods[key_ability] + final_pb
    if generic_project:
        runtime_starting = _project_starting_proficiency_skills(
            starting_proficiency["normalized_mechanics"],
            path_ids=path_ids,
            background_id=background["subject"]["record_id"],
            origin_id=origin["subject"]["record_id"],
            final_mods=final_mods,
            final_pb=final_pb,
        )
        path_skills_by_path_id = runtime_starting["path_skill_choices_by_path_id"]
        selected_skills = runtime_starting["selected_skills"]
        background_skills = runtime_starting["background_skills"]
        background_tools = runtime_starting["background_tools"]
        selected_languages = runtime_starting["selected_languages"]
        expertise_skill = runtime_starting["origin_skill"]
        origin_tool = runtime_starting["origin_tool"]
        origin_trade = runtime_starting["origin_trade"]
        origin_language = runtime_starting["origin_language"]
        tool_expertise = runtime_starting["tool_expertise"]
        origin_result = runtime_starting["origin_result"]
        proficient_skills = runtime_starting["proficient_skills"]
        multipliers = runtime_starting["skill_proficiency_multipliers"]
        skill_ability_map = runtime_starting["skill_ability_map"]
        skills = runtime_starting["skills"]
        skill_sources = runtime_starting["skill_sources"]
    else:
        path_skills_by_path_id = {}
        selected_skills = [x.rsplit(".", 1)[-1].title() for x in required_lock_values["character.choices.qi_cultivation_skills"]]
        background_skills = background["advancement"]["calculation"]["outputs"].get("skill_proficiencies", [])
        background_tools = background["advancement"]["calculation"]["outputs"].get("tool_proficiencies", [])
        selected_languages = []
        proficient_skills = sorted(set(background_skills + selected_skills))
        multipliers = {skill: 1 for skill in proficient_skills}
        expertise_skill = required_lock_values["character.choices.street_hardened"]
        if isinstance(expertise_skill, str) and expertise_skill:
            multipliers[expertise_skill.rsplit(".", 1)[-1].title()] = 2
        skill_ability_map = {
            skill: ("INT" if skill in {"Arcana", "History"} else "CHA" if skill == "Deception" else "DEX")
            for skill in proficient_skills
        }
        skills = {skill: final_mods[skill_ability_map[skill]] + final_pb * multipliers[skill] for skill in sorted(skill_ability_map)}
        skill_sources = {
            skill: [path_event["subject"]["record_id"]] if skill in selected_skills else [background["subject"]["record_id"]]
            for skill in proficient_skills
        }
        origin_result = "expertise" if expertise_skill else "catalog_effect"
        origin_tool = None
        origin_trade = None
        origin_language = None
        tool_expertise = []
    path_selection_rows = []
    path_event_indexes = {}
    for index, event in enumerate(path_events):
        path_event_indexes[event["event_id"]] = index
        record_stage2 = ((event_records[event["event_id"]].get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {})
        path_selection_rows.append({
            "path_id": event["subject"]["record_id"],
            "display_name": event["subject"]["display_name"],
            "effective_cl": target_cl,
            "key_ability": record_stage2.get("key_ability") or (key_ability if event["event_id"] == path_event["event_id"] else None),
            "selected_skills": (
                deepcopy(path_skills_by_path_id.get(event["subject"]["record_id"], []))
                if generic_project
                else deepcopy(selected_skills) if event["event_id"] == path_event["event_id"] else []
            ),
            "source_packet_ids": [packet_by_event[event["event_id"]]],
        })
    primary_subpath_row = next(
        (
            {
                "subpath_id": event["subject"]["record_id"],
                "name": event["subject"]["display_name"],
                "owning_path_id": subpath_parent_path(event),
                "selected_at_cl": 3,
                "feature_ids_expected": deepcopy(granted_ids_by_subpath_event.get(event["event_id"], [])),
                "source_packet_ids": [packet_by_event[event["event_id"]]],
            }
            for event in subpath_events
            if subpath_parent_path(event) == path_event["subject"]["record_id"]
        ),
        None,
    )
    earned_feature_occurrences = _build_earned_feature_occurrences(
        path_events=path_events,
        level_events=level_events,
        score_change_events=score_changes,
        subpath_events=subpath_events,
        event_records=event_records,
        locked_records=locked_records,
        packet_by_event=packet_by_event,
        selected_path_ids=path_ids,
        factory_root=factory_root if not historical_fixture else None,
        insight_events=insight_events,
    )

    readiness = {
        "active_profile": "ADVANCEMENT_READY",
        "advancement": "ADVANCEMENT_READY",
        "character_sheet": "NOT_ATTEMPTED",
        "gm_screen": "NOT_ATTEMPTED",
        "combat": "NOT_ATTEMPTED",
        "profile_id": profile["profile_id"],
        "profile_sha256": sha256_file(profile_path),
    }
    later = {
        "character_sheet": {"status": "NOT_ATTEMPTED", "pending": profile["later_stage_nodes"]["character_sheet"]},
        "gm_screen": {"status": "NOT_ATTEMPTED", "pending": profile["later_stage_nodes"]["gm_screen"]},
        "combat": {"status": "NOT_ATTEMPTED", "pending": profile["later_stage_nodes"]["combat"]},
    }
    display_packets = [
        packet for packet in packets_list
        if packet["advancement_kind"] not in non_projecting_kinds
        or packet["advancement_kind"] in {"method_acquisition", "foundation_acquisition"}
    ]
    display_locked_records = deepcopy(locked_records)
    for event in events:
        if "sphere" not in str((event.get("advancement") or {}).get("kind") or ""):
            continue
        record_id = (event.get("subject") or {}).get("record_id")
        if record_id in display_locked_records:
            display_locked_records[record_id] = _sphere_record_with_event_authority(
                display_locked_records[record_id], event
            )
    dynamic_display_contract = (
        _dynamic_display_contract(
            project,
            choice_snapshot,
            display_locked_records,
            display_packets,
            granted_ids,
            packet_by_event[subpath["event_id"]] if subpath is not None else None,
            {
                granted_id: [
                    {
                        "event_id": event_id,
                        "packet_id": packet_by_event[event_id],
                        "target_cl": subpath_events_by_id[event_id]["advancement"].get("target_cl", 3),
                    }
                    for event_id, granted_event_ids in granted_ids_by_subpath_event.items()
                    if granted_id in granted_event_ids
                ]
                for granted_id in granted_ids
            },
            level_feature_sources,
            earned_feature_occurrences,
        )
        if not historical_fixture
        else None
    )
    ledger = {
        "schema_version": "HF05ZVK-R1F",
        "projection_profile": "TianxiaFoundry.AdvancementReadyProjection.v1",
        "build_mode": "production",
        "status": "COMMAND_2_ADVANCEMENT_LEDGER_SEALED",
        "typed_choice_snapshot": {
            "schema": "TianxiaFoundry.TypedProjectChoiceSnapshotBinding.v1",
            "canonical_project_id": choice_snapshot["canonical_project_id"],
            "project_revision": choice_snapshot["project_revision"],
            "content_lock_hash": choice_snapshot["content_lock_hash"],
            "event_stream": deepcopy(choice_snapshot["event_stream"]),
            "snapshot_sha256": choice_snapshot["snapshot_sha256"],
            "typed_lock_count": len(choice_snapshot.get("typed_locks") or []),
        },
        "readiness": readiness,
        "character": {
            "character_id": project["project_id"],
            "name": required_lock_values["character.identity.display_name"],
            "concept": concept_value,
            "species": rules_by_id["tianxia.core.human.species.v1"]["typed_value"],
            "creature_type": rules_by_id["tianxia.core.human.creature_type.v1"]["typed_value"],
            "size": rules_by_id["tianxia.core.human.size.v1"]["typed_value"],
            "cl": target_cl,
            "realm": _realm_for_cl(target_cl),
            "path": path_event["subject"]["display_name"],
            "path_id": path_event["subject"]["record_id"],
            "paths": deepcopy(path_selection_rows),
            "subpath": deepcopy(primary_subpath_row),
            "key_ability": key_ability,
            "pb": final_pb,
            "title": title_value,
            "title_status": title_status,
        },
        "core_stats": {
            "ability_scores": final_scores,
            "ability_modifiers": final_mods,
            "ability_generation": deepcopy(start["advancement"]["calculation"]),
            "proficiency_bonus": final_pb,
            "ac_base": armor_class["ac_base"],
            "ac_active": armor_class["ac_active"],
            "ac_generation": armor_class["ac_generation"],
            "initiative_bonus": init_result.value,
            "initiative_generation": {"ability": "DEX", "check": "1d20", "formula_id": rules_by_id["tianxia.core.initiative.owner_r1"]["formula"]["formula_id"], "trace": init_result.trace, "situational_advantage_sources": ["tianxia.origin_insight.street_hardened"]},
            "speed_ft": rules_by_id["tianxia.core.human.walking_speed.v1"]["typed_value"],
            "speed_generation": {"rule_id": "tianxia.core.human.walking_speed.v1", "mode": "walking"},
            "hp_current": last_level_out["hp_after"]["total"],
            "hp_max": last_level_out["hp_after"]["total"],
            "hp_generation": {"levels": [{"cl": level["cl"], "gain": level["hp"]["gain"], "maximum": level["hp"]["max_after_level"], "formula_id": level["hp"]["formula_id"]} for level in levels]},
            "primary_resource_name": resource_display_name(primary_resource["resource_id"]),
            "primary_resource_current": primary_resource["current"],
            "primary_resource_max": primary_resource["maximum"],
            "technique_attack_bonus": attack_bonus,
            "save_dc": save_dc,
            "proficient_skills": proficient_skills,
            "skills": skills,
            "skill_ability_map": skill_ability_map,
            "skill_proficiency_multipliers": multipliers,
            "skill_sources": skill_sources,
        },
        "background_origin": {
            "background": {
                "background_id": background["subject"]["record_id"],
                "name": background["subject"]["display_name"],
                "ability_score_change": background_ability_change,
                "skill_proficiencies": background_skills,
                "tool_proficiencies": background_tools,
                "languages": (
                    [deepcopy(language_name) for language_name in selected_languages]
                    if generic_project
                    else []
                    if not required_lock_values["character.choices.language"]
                    else [{"language_id": language["languages"][0]["language_id"], "display_name": language["languages"][0]["display_name"]}]
                ),
                "background_sphere": next((event["subject"]["display_name"] for event in by_kind.get("background_sphere_acquisition") or []), None),
                "background_talent": next((event["subject"]["display_name"] for event in by_kind.get("background_talent_acquisition") or []), None),
                "summary": _display(background_record)[0],
                "source_packet_ids": [packet_by_event[background["event_id"]]],
            },
            "origin_insight": {
                "origin_insight_id": origin["subject"]["record_id"],
                "name": origin["subject"]["display_name"],
                "selected_skill": expertise_skill.rsplit(".", 1)[-1].title() if isinstance(expertise_skill, str) and expertise_skill else None,
                "selected_tool": origin_tool,
                "selected_trade": origin_trade,
                "selected_language": origin_language,
                "tool_expertise": list(tool_expertise),
                "result": origin_result,
                "initiative_effect": "situational_advantage",
                "summary": _display(origin_record)[0],
                "source_packet_ids": [packet_by_event[origin["event_id"]]],
            },
        },
        "advancement": {"levels": levels, "event_count": len(events), "event_head_hash": previous, "historical_prefix_preserved": historical_fixture},
        "path_selections": path_selection_rows,
        "subpaths": [
            {
                "subpath_id": event["subject"]["record_id"],
                "name": event["subject"]["display_name"],
                "owning_path_id": subpath_parent_path(event),
                "selected_at_cl": 3,
                "feature_ids_expected": deepcopy(granted_ids_by_subpath_event.get(event["event_id"], [])),
                "source_packet_ids": [packet_by_event[event["event_id"]]],
            }
            for event in subpath_events
        ],
        "spheres": spheres,
        "automatic_sphere_component_receipts": automatic_sphere_component_receipts,
        "automatic_sphere_components": automatic_sphere_components,
        "talents": talents,
        "insights": insights,
        "cultivation_insight_occurrences": deepcopy(insights),
        "features": features,
        "earned_feature_occurrences": deepcopy(earned_feature_occurrences),
        "resources": [
            {"resource_id": resource["resource_id"], "name": resource_display_name(resource["resource_id"]), "current": resource["current"], "max": resource["maximum"], "formula_id": resource["formula_id"], "authority_components": deepcopy(resource["authority_components"])}
            for _, resource in sorted(last_level_out["resources_after"].items())
        ],
        "method": method_projection,
        "foundation": foundation_projection,
        "recorded_arts": (
            deepcopy(recorded_art_rows)
            if recorded_art_events
            else []
            if training_source_events
            else deepcopy(typed_none["manuals"])
        ),
        "equipment": deepcopy(equipment_rows) if equipment_events else deepcopy(typed_none["equipment"]),
        "forged_techniques": deepcopy(forged_technique_rows) if forged_technique_events else deepcopy(typed_none["forged_techniques"]),
        "typed_none": typed_none,
        "record_capability_coverage": sorted(capability, key=lambda x: x["record_id"]),
        "later_stage_readiness": later,
        "authority_identities": {
            "stage2_authority_pack": deepcopy(contract.get("stage2_authority_pack")),
            "core_baseline_pack": {"pack_id": baseline["pack_id"], "version": baseline["version"], "sha256": sha256_file(baseline_path)},
            "owner_amendment": {"amendment_id": amendment["amendment_id"], "sha256": sha256_file(amendment_path)},
            "campaign_language_binding": {"binding_id": language["binding_id"], "sha256": sha256_file(language_path)},
            "projection_contract": {"contract_id": contract["contract_id"], "version": contract["version"], "sha256": sha256_file(contract_path)},
        },
    }
    if immortal_art_events:
        ledger["immortal_arts"] = deepcopy(immortal_art_rows)
    elif "immortal_arts" in typed_none:
        ledger["immortal_arts"] = deepcopy(typed_none["immortal_arts"])
    if training_source_events:
        ledger["training_sources"] = deepcopy(training_source_rows)
    if generic_project and not subpath_events and 0 < target_cl < 3:
        # The selected Path is authenticated, but its first Subpath choice is
        # not due yet. Keep the subpath array empty; this marker records the
        # sealed milestone-gated absence for the stage-aware validator.
        ledger["subpath_authority"] = {
            "status": "NOT_YET_DUE",
            "first_selection_cl": 3,
            "selected_path_ids": [row["path_id"] for row in path_selection_rows],
        }
    owner_selections = {
        "display_name": required_lock_values["character.identity.display_name"],
        "language": required_lock_values["character.choices.language"],
        "qi_cultivation_skills": deepcopy(required_lock_values["character.choices.qi_cultivation_skills"]),
        "street_hardened": required_lock_values["character.choices.street_hardened"],
        "title": title_value,
        "typed_choice_snapshot_sha256": choice_snapshot["snapshot_sha256"],
    }
    if generic_project:
        owner_selections.update({
            "language": deepcopy(selected_languages),
            "qi_cultivation_skills": deepcopy(
                path_skills_by_path_id.get("tianxia.path.qi_cultivation", [])
            ),
            "street_hardened": expertise_skill,
            "starting_proficiencies": deepcopy(
                starting_proficiency["value"]["response_maps"]
            ),
        })
    packets = {
        "schema_version": "TianxiaFoundry.RulesSelectionPackets.v2",
        "project_id": project["project_id"],
        "project_revision": project["revision"],
        "readiness_profile": "ADVANCEMENT_READY",
        "packets": sorted(packets_list, key=lambda x: x["sequence"]),
        "owner_selections": owner_selections,
        "baseline_rule_ids": sorted(rules_by_id),
    }

    state = state_type()
    state.ledger = ledger
    state.rules_selection_packets = packets
    state.operations_applied = len(events)
    state.event_ids = [event["event_id"] for event in events]
    state.selected_record_ids = sorted({
        event["subject"]["record_id"]
        for event in events
        if event["advancement"]["kind"] not in non_projecting_kinds
    } | set(granted_ids))
    state.event_schema_version = V3
    state.readiness = readiness
    state.capability_coverage = sorted(capability, key=lambda x: x["record_id"])
    state.validation_profile = deepcopy(profile)
    state.project_display_contract = deepcopy(dynamic_display_contract)
    state.typed_choice_snapshot = deepcopy(choice_snapshot)

    # Semantic provenance: one entry per meaningful node or bounded subtree.
    semantic: dict[str, dict[str, Any]] = {}
    semantic["typed_choice_snapshot"] = {
        "provenance_unit": "revision_bound_typed_project_choice_snapshot",
        "canonical_project_id": choice_snapshot["canonical_project_id"],
        "project_revision": choice_snapshot["project_revision"],
        "content_lock_hash": choice_snapshot["content_lock_hash"],
        "event_stream": deepcopy(choice_snapshot["event_stream"]),
        "snapshot_sha256": choice_snapshot["snapshot_sha256"],
        "destination_pointers": [
            "/ledger/typed_choice_snapshot",
            "/ledger/character/character_id",
            "/ledger/character/name",
            "/rules_selection_packets/owner_selections",
        ],
        "transformation_kind": "SERVER_MATERIALIZED_TYPED_CHOICE_BINDING",
    }
    for event in events:
        record = event_records[event["event_id"]]
        kind = event["advancement"]["kind"]
        if kind in non_projecting_kinds:
            destinations = [f"/rules_selection_packets/packets/{event['sequence'] - 1}"]
            if kind == "method_acquisition":
                destinations.append("/ledger/method")
            elif kind == "foundation_acquisition":
                destinations.append("/ledger/foundation")
            semantic[f"event:{event['sequence']:03d}:{event['event_id']}"] = _non_sphere_event_provenance(event, record, contract, destinations)
            continue
        destinations = [f"/ledger/advancement/events/{event['sequence']}", f"/rules_selection_packets/packets/{event['sequence'] - 1}"]
        if kind == "starting_state": destinations += ["/ledger/core_stats/ability_generation"]
        elif kind == "background_acquisition": destinations += ["/ledger/background_origin/background", "/ledger/core_stats/ability_scores", "/ledger/core_stats/ability_modifiers"]
        elif kind == "origin_insight_acquisition": destinations += ["/ledger/background_origin/origin_insight"]
        elif kind == "path_acquisition": destinations += [f"/ledger/path_selections/{path_event_indexes.get(event['event_id'], 0)}"]
        elif kind in {"background_sphere_acquisition", "ai_bootstrap_sphere_acquisition", CREATION_TRAINING_SPHERE_KIND}: destinations += ["/ledger/spheres"]
        elif kind == "sphere_training_attempt": destinations += ["/ledger/spheres"]
        elif kind in {"background_talent_acquisition", "ai_bootstrap_talent_acquisition", "new_sphere_bonus_talent_acquisition", "level_talent_acquisition", CREATION_TRAINING_TALENT_KIND}: destinations += ["/ledger/talents"]
        if kind in CREATION_TRAINING_KINDS:
            destinations.append(f"/ledger/advancement/levels/{event['advancement']['target_cl'] - 1}/trained_choices")
        elif kind == "cultivation_insight_acquisition": destinations += ["/ledger/insights", "/ledger/cultivation_insight_occurrences"]
        elif kind == "level_advance": destinations += ["/ledger/advancement/levels", "/ledger/core_stats/hp_generation", "/ledger/resources"]
        elif kind == "subpath_acquisition": destinations += ["/ledger/subpaths", "/ledger/features"]
        elif kind == "ability_score_change": destinations += ["/ledger/core_stats/ability_scores", "/ledger/core_stats/ability_modifiers"]
        elif kind == "training_source_access":
            row_index = training_source_row_indexes.get(event["event_id"])
            if row_index is None:
                raise FoundryError(
                    "PROJECTION_TRAINING_SOURCE_PROVENANCE_MISSING",
                    "A projected training source lacks its causal semantic destination.",
                    details={"event_id": event["event_id"]},
                )
            destinations += ["/ledger/training_sources", f"/ledger/training_sources/{row_index}"]
        elif kind == FORGED_TECHNIQUE_KIND:
            row_index = forged_technique_row_indexes.get(event["event_id"])
            if row_index is None:
                raise FoundryError(
                    "PROJECTION_FORGED_TECHNIQUE_PROVENANCE_MISSING",
                    "A projected Forged Technique lacks its causal semantic destination.",
                    details={"event_id": event["event_id"]},
                )
            destinations += ["/ledger/forged_techniques", f"/ledger/forged_techniques/{row_index}"]
        elif kind in {RECORDED_ART_CONSTRUCTION_KIND, "manual_training_attempt"}:
            row_index = recorded_art_row_indexes.get(event["event_id"])
            if row_index is not None:
                destinations += ["/ledger/recorded_arts", f"/ledger/recorded_arts/{row_index}"]
        elif kind == "immortal_art_creation":
            row_index = immortal_art_row_indexes.get(event["event_id"])
            if row_index is None:
                raise FoundryError(
                    "PROJECTION_IMMORTAL_ART_PROVENANCE_MISSING",
                    "A projected Immortal Art lacks its causal semantic destination.",
                    details={"event_id": event["event_id"]},
                )
            destinations += ["/ledger/immortal_arts", f"/ledger/immortal_arts/{row_index}"]
        elif kind == "typed_none":
            target = event["advancement"]["details"]["target"]
            if not (target == "manuals" and training_source_events) and not (target == "forged_techniques" and forged_technique_events):
                destinations.append(f"/ledger/typed_none/{target}")
        semantic[f"event:{event['sequence']:03d}:{event['event_id']}"] = _event_provenance(event, record, contract, destinations, "CANONICAL_V3_EVENT_PROJECTION")
    for field, destinations in {
        "character.identity.display_name": ["/ledger/character/name"],
        "character.choices.qi_cultivation_skills": ["/ledger/path_selections/0/selected_skills", "/ledger/core_stats/proficient_skills"],
        "character.choices.street_hardened": ["/ledger/background_origin/origin_insight/selected_skill", "/ledger/core_stats/skill_proficiency_multipliers/Deception"],
        "character.choices.language": ["/ledger/background_origin/background/languages/0"],
    }.items():
        if field in locks:
            semantic[f"lock:{field}"] = _lock_provenance(locks[field], fixture_path, destinations, "OWNER_SELECTION_BINDING")
    if earned_feature_occurrences:
        semantic["earned_feature_occurrences"] = {
            "provenance_unit": "authenticated_path_and_subpath_feature_occurrences",
            "occurrence_count": len(earned_feature_occurrences),
            "destination_pointers": [
                "/ledger/earned_feature_occurrences",
                "/project_display_contract/earned_feature_occurrences",
            ],
            "source_packet_ids": sorted({
                packet_id
                for occurrence in earned_feature_occurrences
                for packet_id in occurrence.get("source_packet_ids") or []
                if isinstance(packet_id, str)
            }),
            "transformation_kind": "AUTHENTICATED_EVENT_AND_PATH_PROGRESSION_DISPLAY_DERIVATION",
            "mechanical_projection": False,
        }
    if generic_project:
        starting_destinations = [
            *[
                f"/ledger/path_selections/{path_event_indexes[event['event_id']]}/selected_skills"
                for event in path_events
            ],
            "/ledger/background_origin/background/skill_proficiencies",
            "/ledger/background_origin/background/tool_proficiencies",
            "/ledger/background_origin/background/languages",
            "/ledger/background_origin/origin_insight/selected_skill",
            "/ledger/background_origin/origin_insight/selected_tool",
            "/ledger/background_origin/origin_insight/selected_trade",
            "/ledger/background_origin/origin_insight/selected_language",
            "/ledger/background_origin/origin_insight/tool_expertise",
            "/ledger/background_origin/origin_insight/result",
            "/ledger/core_stats/proficient_skills",
            "/ledger/core_stats/skills",
            "/ledger/core_stats/skill_ability_map",
            "/ledger/core_stats/skill_proficiency_multipliers",
            "/ledger/core_stats/skill_sources",
            "/rules_selection_packets/owner_selections/starting_proficiencies",
        ]
        semantic["lock:character.choices.starting_proficiencies"] = {
            "provenance_unit": "server_derived_starting_proficiency_lock",
            "lock_id": _STARTING_PROFICIENCY_LOCK_ID,
            "lock_field": _STARTING_PROFICIENCY_LOCK_FIELD,
            "source": starting_proficiency["lock"].get("source"),
            "lock_value_sha256": starting_proficiency["value_sha256"],
            "contract_sha256": starting_proficiency["validated"].get("contract_sha256"),
            "validation_sha256": starting_proficiency["validated"].get("validation_sha256"),
            "binding": deepcopy(starting_proficiency["binding"]),
            "destination_pointers": sorted(starting_destinations),
            "transformation_kind": "SERVER_DERIVED_STARTING_PROFICIENCY_CHOICE",
            "mechanical_projection": True,
        }
    baseline_destinations = {
        "tianxia.core.human.species.v1": ["/ledger/character/species"],
        "tianxia.core.human.creature_type.v1": ["/ledger/character/creature_type"],
        "tianxia.core.human.size.v1": ["/ledger/character/size"],
        "tianxia.core.human.walking_speed.v1": ["/ledger/core_stats/speed_ft", "/ledger/core_stats/speed_generation"],
        "tianxia.core.unarmored_ac.owner_r1": ["/ledger/core_stats/ac_base", "/ledger/core_stats/ac_active", "/ledger/core_stats/ac_generation"],
        "tianxia.core.initiative.owner_r1": ["/ledger/core_stats/initiative_bonus", "/ledger/core_stats/initiative_generation"],
    }
    for rule_id, destinations in baseline_destinations.items():
        trace = ac_result.trace if rule_id == "tianxia.core.unarmored_ac.owner_r1" else init_result.trace if rule_id == "tianxia.core.initiative.owner_r1" else None
        semantic[f"baseline:{rule_id}"] = _baseline_provenance(rules_by_id[rule_id], baseline, baseline_path, destinations, trace)
    for rule, trace in armor_class["applied_rules"]:
        entry = {
            "provenance_unit": "path_feature_statistic_rule",
            "rule_id": rule["rule_id"],
            "feature_id": rule["feature_id"],
            "kind": rule["kind"],
            "authority_classification": statistic_formulas.get("authority_classification"),
            "source": deepcopy(rule.get("source") or {}),
            "statistic_pack_id": statistic_formulas.get("pack_id"),
            "statistic_pack_version": statistic_formulas.get("version"),
            "statistic_pack_sha256": sha256_file(statistic_formulas_path(root_dir)),
            "destination_pointers": ["/ledger/core_stats/ac_active", "/ledger/core_stats/ac_generation"] + (["/ledger/core_stats/ac_base"] if rule["kind"] == "base_ac_calculation" else []),
            "transformation_kind": "SAFE_FORMULA_EVALUATION" if trace is not None else "DIRECT_TYPED_VALUE",
        }
        if trace is not None:
            entry["formula_trace"] = trace
        semantic[f"statistic:{rule['rule_id']}"] = entry
    state.provenance = semantic
    return state
