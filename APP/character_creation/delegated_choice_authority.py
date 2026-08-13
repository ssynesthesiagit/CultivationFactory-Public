"""Revision-bound delegated-choice authority for complete character creation.

This module is intentionally independent of transport and compilation.  It
turns the production Stage 1 envelope into a sealed request envelope before an
AI response exists, then validates a response against that exact envelope.
Planner prose never participates in the legality decision.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core import FoundryError, canonical_json, sha256_json
from catalog_choice_authority import DELEGATED_FINAL_CATALOG_GRANT_FIELD
from path_method_authority import (
    CANONICAL_PATH_IDS,
    canonicalize_path_ids,
    method_granted_path_ids,
    method_path_compatibility,
)
from character_creation.response_materialization import (
    inject_canonical_intent,
    normalize_selection_intent,
)


ENVELOPE_SCHEMA = "TianxiaFoundry.DelegatedChoiceAuthorityEnvelope.v1"
FINAL_PLAN_SCHEMA = "TianxiaFoundry.CharacterCreationFinalPlan.v1"
FROZEN_TARGET_CL_AUTHORITY_SCHEMA = "TianxiaFoundry.FrozenOwnerTargetCLAuthority.v1"
TARGET_CL_MISMATCH_ERROR = "CG1_DELEGATED_TARGET_CL_MISMATCH"
FINAL_PLAN_TARGET_CL_STALE_ERROR = "CG1_FINAL_PLAN_TARGET_CL_AUTHORITY_STALE"
DELEGATED_NAME_REQUIRED_ERROR = "CG1_DELEGATED_NAME_REQUIRED"
DELEGATED_NAME_REQUIREMENT_SCHEMA = "TianxiaFoundry.DelegatedNameRequirement.v1"

_PATH_SLOT = "path_choice"
_METHOD_SLOT = "method_choice"
_FOUNDATION_SLOT = "foundation_choice"
_CANONICAL_SLOT_FIELDS = {
    "sphere_ids": {"sphere_priorities", "sphere_choice", "background_sphere_choice"},
    "talent_ids": {"advancement_skeleton", "talent_choice", "background_talent_choice"},
    "insight_ids": {"insight_priorities", "insight_choice", "origin_insight_choice"},
    "item_ids": {"item_priorities", "item_choice"},
}
_PATH_KINDS = {"path_acquisition"}
_METHOD_KINDS = {"method_acquisition", "method_activation"}
_FOUNDATION_KINDS = {"foundation_acquisition", "foundation_expression", "foundation_stage"}
_CANONICAL_KINDS = {
    "cultivation_insight_acquisition",
    "sect_trial_sphere_acquisition",
    "sect_trial_talent_acquisition",
    "ai_bootstrap_sphere_acquisition",
    "ai_bootstrap_talent_acquisition",
    "level_talent_acquisition",
    "new_sphere_bonus_talent_acquisition",
}


def _canonical_stage2_kind(kind: Any) -> Any:
    """Normalize the legacy delegated Insight alias before authority checks."""
    return "cultivation_insight_acquisition" if kind == "insight_acquisition" else kind


_CATALOG_SPHERE_GRANT_KINDS = {
    "sect_trial_sphere_acquisition",
    "ai_bootstrap_sphere_acquisition",
}
_BACKGROUND_SPHERE_KINDS = {"background_sphere_acquisition"}
_CATALOG_FREE_TALENT_KINDS = {
    "sect_trial_talent_acquisition",
    "ai_bootstrap_talent_acquisition",
    "new_sphere_bonus_talent_acquisition",
}
_BACKGROUND_TALENT_KINDS = {"background_talent_acquisition"}
_CATALOG_ORDINARY_TALENT_KINDS = {"level_talent_acquisition"}
_DIRECT_STAGE2_SLOT_KINDS = {
    "path_acquisition": _PATH_SLOT,
    "method_acquisition": _METHOD_SLOT,
    "method_activation": _METHOD_SLOT,
}
_STAGE2_DELEGATED_SLOT_KINDS = {
    **_DIRECT_STAGE2_SLOT_KINDS,
    "foundation_acquisition": _FOUNDATION_SLOT,
    "foundation_expression": _FOUNDATION_SLOT,
    "foundation_stage": _FOUNDATION_SLOT,
    "background_acquisition": "background_choice",
    # Background Sphere/Talent rows are authenticated route consequences.
    # They remain in the typed Stage 2 catalog ledger, but are not delegated
    # free-choice representations and therefore must not be checked against
    # the bounded Stage 1 choice slots.
    "origin_insight_acquisition": "origin_insight_choice",
    "cultivation_insight_acquisition": "insight_priorities",
    "insight_acquisition": "insight_priorities",
    "origin_insight_selection": "origin_insight_choice",
    "subpath_acquisition": "subpath_choice",
    "tradition_acquisition": "subpath_choice",
    "item_acquisition": "item_priorities",
    "equipment_acquisition": "item_priorities",
    "sect_trial_sphere_acquisition": "sphere_priorities",
    "ai_bootstrap_sphere_acquisition": "sphere_priorities",
    "sect_trial_talent_acquisition": "advancement_skeleton",
    "ai_bootstrap_talent_acquisition": "advancement_skeleton",
    "level_talent_acquisition": "advancement_skeleton",
    "new_sphere_bonus_talent_acquisition": "advancement_skeleton",
}
_SELECTION_ALIASES = {
    "path_ids": _PATH_SLOT,
    "path_choice_ids": _PATH_SLOT,
    "selected_path_ids": _PATH_SLOT,
    "method_id": _METHOD_SLOT,
    "method_choice_id": _METHOD_SLOT,
    "foundation_id": _FOUNDATION_SLOT,
    "foundation_choice_id": _FOUNDATION_SLOT,
    "sphere_ids": "sphere_priorities",
    "sphere_choice_ids": "sphere_priorities",
    "talent_ids": "advancement_skeleton",
    "talent_choice_ids": "advancement_skeleton",
    "offered_talent_priority_ids": "advancement_skeleton",
    "insight_ids": "insight_priorities",
    "insight_choice_ids": "insight_priorities",
    "insight_priority_ids": "insight_priorities",
    "item_ids": "item_priorities",
    "item_choice_ids": "item_priorities",
    "item_priority_ids": "item_priorities",
}

_PLANNING_SLOT_IDS = frozenset({
    "sphere_priorities",
    "advancement_skeleton",
    "insight_priorities",
    "item_priorities",
})

# The current CAT3 envelope publishes the canonical Background-Talent record
# ID, while the bounded historical Stage 2 fixture carries the older compact
# TAL_ alias.  Keep this compatibility explicit and slot-bound: it is a
# representation alias, never a second selectable record or a fuzzy name
# match.
_LEGACY_CHOICE_ALIASES = {
    "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE": "tianxia.background_talent.scoundrel.hidden_tool_cache",
    "tianxia.sphere.scoundrel": "tianxia.background_sphere.scoundrel",
}


def _locks(project: dict[str, Any]) -> dict[str, Any]:
    return {
        row.get("field"): deepcopy(row.get("value"))
        for row in project.get("user_locks") or []
        if isinstance(row, dict) and isinstance(row.get("field"), str)
    }


def _owner_user_locks(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only owner-choice locks covered by the frozen envelope."""
    return [
        deepcopy(row)
        for row in project.get("user_locks") or []
        if isinstance(row, dict) and row.get("field") != DELEGATED_FINAL_CATALOG_GRANT_FIELD
    ]


def _slot_map(prompt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    envelope = prompt.get("envelope") if isinstance(prompt, dict) else None
    return {
        row.get("slot_id"): row
        for row in (envelope or {}).get("decision_slots") or []
        if isinstance(row, dict) and isinstance(row.get("slot_id"), str)
    }


def _choice_map(slot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row.get("choice_id"): deepcopy(row)
        for row in slot.get("choices") or []
        if isinstance(row, dict) and isinstance(row.get("choice_id"), str)
    }


def _canonical_slot_choice_id(envelope: dict[str, Any], slot_id: str, choice_id: str) -> str:
    """Resolve only the published, explicit legacy alias for a slot value."""

    rows = (envelope.get("choices_by_slot") or {}).get(slot_id) or {}
    if choice_id in rows:
        return choice_id
    canonical = _LEGACY_CHOICE_ALIASES.get(choice_id)
    if canonical and canonical in rows:
        return canonical
    return choice_id


def _slot_lock_values(lock_values: dict[str, Any], slot_id: str) -> list[str]:
    value = lock_values.get("character_sheet.locked_choices") or {}
    if not isinstance(value, dict):
        return []
    values = value.get(slot_id) or []
    return [value for value in values if isinstance(value, str)] if isinstance(values, list) else []


def _method_planning_lock(lock_values: dict[str, Any]) -> dict[str, Any] | None:
    """Project an exact owner Method planning lock without granting it.

    ``character_sheet.method_access_plan`` proves the separate access route;
    ``method_exact_choice_id`` proves the owner's planning selection.  Neither
    field is an acquired Stage 2 event.  Keeping this projection explicit in
    the frozen envelope lets owner surfaces report provenance without treating
    access evidence as a Method acquisition lock.
    """
    mode = lock_values.get("character_sheet.method_planning_mode")
    if mode not in {"EXACT", "HARD_LOCK"}:
        return None
    planning = lock_values.get("character_sheet.planning_preferences")
    planning = planning if isinstance(planning, dict) else {}
    locked_choices = lock_values.get("character_sheet.locked_choices")
    locked_choices = locked_choices if isinstance(locked_choices, dict) else {}
    method_ids = planning.get("method_exact_choice_id")
    if not isinstance(method_ids, str) or not method_ids:
        locked_method_ids = locked_choices.get(_METHOD_SLOT) or []
        method_ids = locked_method_ids[0] if isinstance(locked_method_ids, list) and locked_method_ids else None
    if not isinstance(method_ids, str) or not method_ids:
        return None
    access_plan = lock_values.get("character_sheet.method_access_plan")
    access_plan = deepcopy(access_plan) if isinstance(access_plan, dict) else None
    return {
        "slot_id": _METHOD_SLOT,
        "choice_ids": [method_ids],
        "mode": mode,
        "field": "character_sheet.planning_preferences.method_exact_choice_id",
        "planning_authority": "owner_locked_planning_selection",
        "acquisition_authority": "server_materialized_after_validated_response",
        "access_authority": {
            "field": "character_sheet.method_access_plan",
            "present": access_plan is not None,
            "method_id": access_plan.get("method_id") if access_plan else None,
            "route_type": access_plan.get("route_type") if access_plan else None,
            "route_commitment_sha256": access_plan.get("route_commitment_sha256") if access_plan else None,
        },
    }


def _method_access_proof(
    project: dict[str, Any],
    method_id: str,
    method_access: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the server-owned exact access proof for one restricted Method.

    Compatibility is intentionally not part of this proof.  A Method can be
    AP-compatible while still requiring either a complete owner-authored route
    plan or an exact committed evidence record.  Merely displaying a route, or
    putting a Method ID in an arbitrary lock, is not access authority.
    """
    metadata = method_access if isinstance(method_access, dict) else {}
    direct = metadata.get("initial_creation_selectable") is True
    locks = _locks(project)
    plan = locks.get("character_sheet.method_access_plan")
    plan = plan if isinstance(plan, dict) else {}
    route_options = metadata.get("owner_route_options") or []
    route_types = {
        row.get("typed_route")
        for row in route_options
        if isinstance(row, dict) and isinstance(row.get("typed_route"), str)
    }
    plan_fields = (
        "schema", "method_id", "access_tier", "route_type", "route_label",
        "source_reference", "source_route_sha256", "route_commitment_sha256",
        "method_registry_commitment_sha256", "status",
    )
    plan_missing = [field for field in plan_fields if plan.get(field) in (None, "", {})]
    plan_route_advertised = (
        plan.get("route_type") == "PUBLISHED_OPEN_INITIAL_AUTHORITY"
        or plan.get("route_type") in route_types
    )
    # ``route_configurable`` describes an advertised owner route, not whether
    # the project has already committed its route plan.  The latter remains an
    # internal proof detail: a complete owner plan permits the exact Method to
    # remain in the pending delegated selection, while access authorization is
    # still false until the server commits its exact access record.
    route_configurable = bool(route_options)
    route_plan_configured = bool(
        not plan_missing
        and plan.get("schema") == "TianxiaFoundry.MethodAccessPlan.v2"
        and plan.get("method_id") == method_id
        and plan_route_advertised
    )
    evidence_rows = [
        row for row in (locks.get("character_sheet.non_sphere_access_sources") or [])
        if isinstance(row, dict)
        and row.get("authority_type") == "method_access"
        and row.get("method_id") == method_id
        and isinstance(row.get("source_record_id"), str)
        and bool(row["source_record_id"].strip())
    ]
    return {
        "direct_access": direct,
        "route_configurable": route_configurable,
        "evidence_present": bool(evidence_rows),
        # A displayed/configurable route is not proof that the route has been
        # authorized.  Open Methods are authorized directly; restricted
        # Methods require a committed exact access record.  The owner route
        # plan is planning input and is materialized/committed later by the
        # server-owned compilation boundary.
        "access_authorized": direct or bool(evidence_rows),
        "exact_access_record_present": bool(evidence_rows),
        "selection_authorized": direct or route_plan_configured or bool(evidence_rows),
        "route_plan_configured": route_plan_configured,
        "route_plan_method_id": plan.get("method_id"),
        "route_plan_missing_fields": plan_missing,
        "evidence_count": len(evidence_rows),
    }


def _stable_hash(value: Any) -> str:
    return sha256_json(value)


def frozen_owner_target_cl(project: dict[str, Any]) -> int:
    """Return the one canonical target CL frozen by the owner/server.

    Character Builder projects persist target CL as an immutable ``target_cl``
    user lock.  Delegated planning must never fall back to a response value or
    planner text when that lock is absent, malformed, or contradictory.
    """

    values = [
        row.get("value")
        for row in project.get("user_locks") or []
        if isinstance(row, dict) and row.get("field") == "target_cl"
    ]
    if not values or any(type(value) is not int or not 1 <= value <= 20 for value in values) or len(set(values)) != 1:
        raise FoundryError(
            "CG1_FROZEN_TARGET_CL_AUTHORITY_INVALID",
            "The project has no single valid immutable owner target CL for delegated character creation.",
            details={
                "project_id": project.get("project_id"),
                "target_cl_lock_values": values,
            },
            status_code=409,
        )
    project_projection = project.get("target_cl")
    if project_projection is not None and (
        type(project_projection) is not int or project_projection != values[0]
    ):
        raise FoundryError(
            "CG1_FROZEN_TARGET_CL_AUTHORITY_INVALID",
            "The project target CL projections do not agree with the immutable owner target lock.",
            details={
                "project_id": project.get("project_id"),
                "target_cl_lock": values[0],
                "project_target_cl": project_projection,
            },
            status_code=409,
        )
    return values[0]


def _target_context(run: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    request = run.get("request") or {}
    return {
        "project_id": project.get("project_id") or run.get("project_id"),
        "project_revision": project.get("revision") or run.get("starting_revision"),
        "request_sha256": request.get("request_sha256"),
        "content_lock_hash": (project.get("content_lock") or {}).get("lock_hash")
        or request.get("content_lock_hash"),
    }


def _raise_target_mismatch(
    run: dict[str, Any],
    project: dict[str, Any],
    *,
    expected: int,
    proposed: Any,
    surface: str,
    progression_target: Any = None,
) -> None:
    details = {
        "expected_target_cl": expected,
        "proposed_target_cl": proposed,
        "surface": surface,
        **_target_context(run, project),
    }
    if progression_target is not None:
        details["stage2_progression_target_cl"] = progression_target
    raise FoundryError(
        TARGET_CL_MISMATCH_ERROR,
        "The delegated response target CL must equal the exact frozen owner target before final-plan derivation or compilation.",
        details=details,
        status_code=409,
    )


def validate_delegated_target_cl(
    run: dict[str, Any],
    project: dict[str, Any],
    plan: dict[str, Any],
) -> int:
    """Validate every delegated target-CL surface before final-plan derivation."""

    envelope = ((run.get("request") or {}).get("delegated_choice_envelope") or {})
    authority = envelope.get("frozen_owner_target_cl")
    expected = frozen_owner_target_cl(project)
    binding = envelope.get("binding") or {}
    authority_binding = authority.get("binding") if isinstance(authority, dict) else None
    if (
        not isinstance(authority, dict)
        or authority.get("schema") != FROZEN_TARGET_CL_AUTHORITY_SCHEMA
        or authority.get("field") != "target_cl"
        or type(authority.get("value")) is not int
        or authority.get("value") != expected
        or authority.get("delegated") is not False
        or authority.get("immutable") is not True
        or authority_binding != binding
    ):
        raise FoundryError(
            "CG1_DELEGATED_TARGET_CL_AUTHORITY_STALE",
            "The delegated envelope does not carry the exact frozen owner target CL bound to this request.",
            details={
                "expected_target_cl": expected,
                "envelope_target_cl": authority.get("value") if isinstance(authority, dict) else None,
                "project_id": project.get("project_id") or run.get("project_id"),
                "project_revision": project.get("revision") or run.get("starting_revision"),
                "request_sha256": (run.get("request") or {}).get("request_sha256"),
            },
            status_code=409,
        )

    # The preferred response contract omits target CL entirely.  The immutable
    # project/envelope value is injected by the server before downstream
    # compilation.  A compatibility copy remains legal only when it is exact.
    if "target_cl" in plan:
        proposed = plan.get("target_cl")
        if type(proposed) is not int or proposed != expected:
            _raise_target_mismatch(run, project, expected=expected, proposed=proposed, surface="complete_response.target_cl")

    stage2 = plan.get("stage2_proposal")
    if not isinstance(stage2, dict):
        return expected
    stage2_target = stage2.get("target_cl")
    stage2_choices = stage2.get("choices")
    selection_intent_only = (
        stage2_target is None
        and isinstance(stage2.get("selection_intent_by_slot"), dict)
        and not isinstance(stage2_choices, list)
    )
    if not selection_intent_only and stage2_target is not None and (type(stage2_target) is not int or stage2_target != expected):
        _raise_target_mismatch(run, project, expected=expected, proposed=stage2_target, surface="stage2_proposal.target_cl")

    choices = stage2_choices
    if not isinstance(choices, list):
        return expected
    level_targets: list[int] = []
    for index, row in enumerate(choices):
        if not isinstance(row, dict):
            continue
        row_target = row.get("target_cl")
        if "target_cl" in row and (type(row_target) is not int or row_target != expected):
            _raise_target_mismatch(
                run,
                project,
                expected=expected,
                proposed=row_target,
                surface=f"stage2_proposal.choices[{index}].target_cl",
            )
        effective_cl = row.get("effective_cl")
        if "effective_cl" not in row:
            continue
        if type(effective_cl) is not int or effective_cl < 0 or effective_cl > expected:
            _raise_target_mismatch(
                run,
                project,
                expected=expected,
                proposed=effective_cl,
                surface=f"stage2_proposal.choices[{index}].effective_cl",
            )
        if row.get("kind") == "level_advance":
            level_targets.append(effective_cl)
    if level_targets and max(level_targets) != expected:
        _raise_target_mismatch(
            run,
            project,
            expected=expected,
            proposed=max(level_targets),
            surface="stage2_proposal.level_advance_rows",
            progression_target=max(level_targets),
        )
    return expected


def validate_accepted_final_plan_target(
    run: dict[str, Any],
    project: dict[str, Any],
    final_plan: dict[str, Any],
) -> int:
    """Reject P1A/P1AR1 final plans that lack proven frozen target authority."""

    expected = frozen_owner_target_cl(project)
    authority = final_plan.get("target_cl_authority")
    envelope = ((run.get("request") or {}).get("delegated_choice_envelope") or {})
    envelope_authority = envelope.get("frozen_owner_target_cl")
    valid = (
        type(final_plan.get("target_cl")) is int
        and final_plan.get("target_cl") == expected
        and isinstance(authority, dict)
        and authority.get("schema") == FROZEN_TARGET_CL_AUTHORITY_SCHEMA
        and authority.get("field") == "target_cl"
        and authority.get("value") == expected
        and authority.get("delegated") is False
        and authority.get("immutable") is True
        and authority.get("envelope_sha256") == envelope.get("envelope_sha256")
        and isinstance(envelope_authority, dict)
    )
    if not valid:
        raise FoundryError(
            FINAL_PLAN_TARGET_CL_STALE_ERROR,
            "This delegated final plan predates frozen target-CL authority and must be regenerated from the current request.",
            details={
                "expected_target_cl": expected,
                "final_plan_target_cl": final_plan.get("target_cl"),
                "final_plan_target_cl_authority": authority.get("value") if isinstance(authority, dict) else None,
                **_target_context(run, project),
            },
            status_code=409,
        )
    return expected


def _authority_mapping(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("authority") if isinstance(row, dict) else None
    return value if isinstance(value, dict) else {}


def build_delegated_choice_envelope(
    project: dict[str, Any],
    prompt: dict[str, Any],
    *,
    execution_mode: str,
    idempotency_key: str,
) -> dict[str, Any] | None:
    """Freeze the authority envelope without resolving unspecified choices.

    A small compatibility return of ``None`` is used for old test doubles that
    do not expose the real Stage 1 envelope.  Production prompts always carry
    ``decision_slots`` and therefore always receive this envelope.
    """

    slots = _slot_map(prompt)
    if not slots:
        return None
    prompt_envelope = prompt.get("envelope") or {}
    locks = _locks(project)
    method_planning_lock = _method_planning_lock(locks)
    by_slot: dict[str, list[str]] = {}
    offered: dict[str, list[str]] = {}
    allowed: dict[str, list[str]] = {}
    unavailable: dict[str, list[str]] = {}
    limits: dict[str, dict[str, Any]] = {}
    choices: dict[str, dict[str, Any]] = {}
    method_access_by_id = (
        (prompt_envelope.get("path_method_authority") or {}).get("method_access_by_id") or {}
    )
    for slot_id, slot in sorted(slots.items()):
        rows = _choice_map(slot)
        ids = list(rows)
        offered[slot_id] = ids
        choices[slot_id] = rows
        required = [value for value in slot.get("required_choice_ids") or [] if isinstance(value, str)]
        by_slot[slot_id] = required or _slot_lock_values(locks, slot_id)
        # ``initial_creation_selectable`` is authoritative when present.  The
        # absence of that field is the legacy published-choice convention.
        permitted: list[str] = []
        rejected: list[str] = []
        for choice_id, row in rows.items():
            selectable = row.get("initial_creation_selectable")
            if selectable is None:
                selectable = row.get("selectable", row.get("available", True))
            availability = row.get("availability") if isinstance(row.get("availability"), dict) else {}
            method_access = method_access_by_id.get(choice_id) if slot_id == _METHOD_SLOT else None
            access_proof = (
                _method_access_proof(project, choice_id, method_access)
                if slot_id == _METHOD_SLOT
                else {}
            )
            owner_access = slot_id == _METHOD_SLOT and access_proof.get("selection_authorized") is True
            access_required_without_proof = (
                isinstance(method_access, dict)
                and method_access.get("initial_creation_selectable") is False
                and not owner_access
            )
            if selectable is False or availability.get("available") is False or access_required_without_proof:
                rejected.append(choice_id)
            else:
                permitted.append(choice_id)
        allowed[slot_id] = permitted
        unavailable[slot_id] = sorted(rejected)
        limits_min = 0 if slot.get("allow_none") else slot.get("min_selections")
        limits[slot_id] = {
            "owner_lock_min": 0,
            "owner_lock_max": slot.get("max_selections"),
            "final_min": 1 if slot_id == _PATH_SLOT else limits_min,
            "final_max": 3 if slot_id == _PATH_SLOT else slot.get("max_selections"),
            "allow_none": bool(slot.get("allow_none")),
        }

    content_lock = project.get("content_lock") or {}
    frozen_target_cl = frozen_owner_target_cl(project)
    path_authority = deepcopy(prompt_envelope.get("path_method_authority") or {})
    complete_source_authority = path_authority.get("complete_character_source_authority") or {}
    typed_choice_authority = {
        slot_id: deepcopy(slot.get("authority_contract") or {})
        for slot_id, slot in slots.items()
        if isinstance(slot.get("authority_contract"), dict)
    }
    name_lock_present = "character.identity.display_name" in locks
    owner_name = locks.get("character.identity.display_name")
    if not name_lock_present:
        owner_name = project.get("working_name") or project.get("name")
    concept_lock_present = "concept" in locks
    owner_concept = locks.get("concept")
    if not concept_lock_present:
        owner_concept = project.get("concept")
    owner_name = str(owner_name or "").strip() or None
    owner_concept = str(owner_concept or "").strip() or None
    delegated_fields = {
        "identity.name": {
            "state": "owner_locked" if owner_name else "delegated",
            "owner_value": owner_name,
            "response_field": "owner_descriptive_fields.identity.name",
            "required_in_response": True,
            "nonblank_required": True,
            "positive_delegation": not bool(owner_name),
            "requirement_schema": DELEGATED_NAME_REQUIREMENT_SCHEMA,
            "semantic_requirement": (
                "The response must propose one nonblank descriptive character name for owner review."
                if not owner_name
                else "The response must repeat the exact owner-locked character name unchanged."
            ),
        },
        "concept": {
            "state": "owner_locked" if owner_concept else "delegated",
            "owner_value": owner_concept,
            "response_field": "owner_descriptive_fields.concept",
        },
    }
    unresolved = [
        slot_id for slot_id, required in by_slot.items()
        if not required and slot_id not in {_PATH_SLOT}
    ]
    binding = {
        "project_id": project.get("project_id"),
        "project_revision": project.get("revision"),
        "catalog_build_id": content_lock.get("catalog_build_id"),
        "content_lock_hash": content_lock.get("lock_hash"),
        "stage1_prompt_id": prompt.get("prompt_id"),
        "stage1_prompt_sha256": prompt.get("prompt_sha256"),
    }
    payload = {
        "schema": ENVELOPE_SCHEMA,
        "binding": binding,
        "frozen_owner_target_cl": {
            "schema": FROZEN_TARGET_CL_AUTHORITY_SCHEMA,
            "field": "target_cl",
            "value": frozen_target_cl,
            "source": "project.user_locks[field=target_cl]",
            "delegated": False,
            "immutable": True,
            "binding": deepcopy(binding),
        },
        "owner_locks": {
            "by_slot": by_slot,
            "lock_sha256": _stable_hash(project.get("user_locks") or []),
            "zero_owner_path_locks_are_legal": not bool(by_slot.get(_PATH_SLOT)),
            "planning_by_slot": {
                _METHOD_SLOT: method_planning_lock,
            } if method_planning_lock else {},
            "planning_lock_sha256": _stable_hash(method_planning_lock) if method_planning_lock else None,
        },
        "offered_choice_ids_by_slot": offered,
        "allowed_choice_ids_by_slot": allowed,
        "unavailable_or_rejected_choice_ids_by_slot": unavailable,
        "nonselectable_choice_ids_by_slot": unavailable,
        "choices_by_slot": choices,
        "typed_choice_authority_by_slot": typed_choice_authority,
        "selection_limits_by_slot": limits,
        "prerequisites_and_availability": {
            slot_id: {
                choice_id: {
                    "prerequisites": deepcopy(row.get("prerequisites") or row.get("legality", {}).get("prerequisites") or []),
                    "availability": deepcopy(row.get("availability") or {}),
                    "incompatibilities": deepcopy(row.get("incompatibilities") or row.get("legality", {}).get("incompatibilities") or []),
                }
                for choice_id, row in rows.items()
            }
            for slot_id, rows in choices.items()
        },
        "ordinary_talent_count": complete_source_authority.get("ordinary_talent_count"),
        "advancement_choice_milestones": deepcopy(complete_source_authority.get("advancement_choice_milestones") or []),
        "path_progression_choices": deepcopy(complete_source_authority.get("path_progression_choices") or []),
        "path_method_authority": path_authority,
        "method_foundation_compatibility": {
            method_id: {
                "compatible_foundation_ids": deepcopy(
                    row.get("compatible_foundation_ids")
                    or _authority_mapping(row).get("compatible_foundation_ids")
                    or []
                ),
            }
            for method_id, row in choices.get(_METHOD_SLOT, {}).items()
        },
        "automatic_grants": {
            "declared_before_response": [],
            "method_granted_extra_paths_are_disclosed_after_response": True,
            "method_granted_path_ids_by_method": deepcopy(path_authority.get("method_granted_path_ids") or {}),
            "canonical_grant_lock_present": bool(
                locks.get("character_sheet.canonical_grant_plan")
                or locks.get("character_creation.committed_catalog_choice_plan")
                or locks.get("character_creation.delegated_final_catalog_grant_plan")
            ),
        },
        "delegated_fields": delegated_fields,
        "delegated_name_contract": {
            "schema": DELEGATED_NAME_REQUIREMENT_SCHEMA,
            "field": "owner_descriptive_fields.identity.name",
            "state": delegated_fields["identity.name"]["state"],
            "required": True,
            "nonblank": True,
            "positive_delegation": delegated_fields["identity.name"]["positive_delegation"],
            "owner_locked_value": owner_name,
            "instruction": delegated_fields["identity.name"]["semantic_requirement"],
        },
        "unresolved_owner_decisions": unresolved,
        "one_shot": {
            "execution_mode": execution_mode,
            "idempotency_key": idempotency_key,
            "max_response_count": 1,
            "automatic_retries": False,
            "replay_requires_exact_request_binding": True,
        },
        "policy": {
            "ai_may_select_only_allowed_ids": True,
            "planner_prose_is_display_only": True,
            "no_final_no_path": True,
            "level_zero_tracks": "all_three_present_dormant",
            "unspecified_choices_are_not_prefrozen": True,
        },
    }
    payload["envelope_sha256"] = _stable_hash(payload)
    return payload


def _stage1_payload(plan: dict[str, Any]) -> dict[str, Any]:
    response = plan.get("stage1_response") or {}
    if isinstance(response, str):
        return {}
    return response.get("response_payload") or {}


def _decisions(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row.get("slot_id"): row
        for row in _stage1_payload(plan).get("decisions") or []
        if isinstance(row, dict) and isinstance(row.get("slot_id"), str)
    }


def _priority_order(plan: dict[str, Any]) -> dict[str, Any]:
    # Stage2AdvancementProposal.v2 is intentionally closed and therefore
    # cannot carry response-authority metadata as an extra property.  Keep
    # the complete-plan representation at the CharacterCreationPlan level;
    # accept the historical nested shape only for compatibility with older
    # callers that never reached the production Stage2 schema boundary.
    top_level = plan.get("catalog_priority_order")
    if isinstance(top_level, dict):
        return top_level
    proposal = plan.get("stage2_proposal") or {}
    return deepcopy(
        proposal.get("catalog_priority_order")
        or proposal.get("selection_intent_by_slot")
        or {}
    )


def _delegated_selection(plan: dict[str, Any]) -> dict[str, Any]:
    canonical_intent = plan.get("canonical_selection_intent")
    if isinstance(canonical_intent, dict):
        by_slot = canonical_intent.get("selected_by_slot")
        if isinstance(by_slot, dict):
            result: dict[str, Any] = {}
            aliases = {
                _PATH_SLOT: "path_ids",
                _METHOD_SLOT: "method_id",
                _FOUNDATION_SLOT: "foundation_id",
                "sphere_priorities": "sphere_ids",
                "advancement_skeleton": "talent_ids",
                "insight_priorities": "insight_ids",
                "item_priorities": "item_ids",
                "subpath_choice": "subpath_ids",
                "background_choice": "background_ids",
                "background_sphere_choice": "background_sphere_ids",
                "background_talent_choice": "background_talent_ids",
                "origin_insight_choice": "origin_insight_ids",
            }
            for slot_id, values in by_slot.items():
                key = aliases.get(slot_id)
                if not key:
                    continue
                cleaned = _values(values)
                result[key] = cleaned[0] if key.endswith("_id") and cleaned else cleaned
            # Actual acquisitions are separate from planning priorities, but a
            # materialized compatibility plan may not yet have its Stage 2
            # rows.  Keep only the explicit IDs here; the materializer expands
            # them into typed rows before compilation.
            return result
    selection = plan.get("delegated_choice_selections")
    if not isinstance(selection, dict):
        selection = {}
    priority = _priority_order(plan)
    merged = deepcopy(selection)
    aliases = {
        "path_ids": ("path_choice_ids", "selected_path_ids"),
        "method_id": ("method_choice_id",),
        "foundation_id": ("foundation_choice_id",),
        "sphere_ids": ("sphere_choice_ids",),
        "talent_ids": ("talent_choice_ids", "offered_talent_priority_ids"),
        "insight_ids": ("insight_choice_ids", "insight_priority_ids"),
        "item_ids": ("item_choice_ids", "item_priority_ids"),
    }
    for target, sources in aliases.items():
        if target in merged:
            continue
        for source in sources:
            if source in priority:
                merged[target] = deepcopy(priority[source])
                break
    decisions = _decisions(plan)
    decision_aliases = {
        "path_ids": _PATH_SLOT,
        "method_id": _METHOD_SLOT,
        "foundation_id": _FOUNDATION_SLOT,
        "sphere_ids": "sphere_priorities",
        "talent_ids": "advancement_skeleton",
        "insight_ids": "insight_priorities",
        "item_ids": "item_priorities",
    }
    for target, slot_id in decision_aliases.items():
        if target in merged:
            continue
        decision = decisions.get(slot_id) or {}
        if decision.get("state") == "selected":
            values = decision.get("choice_ids") or []
            merged[target] = values[0] if target.endswith("_id") else deepcopy(values)
    # A complete Stage2 proposal may express the authoritative event intent
    # without using catalog_priority_order.
    stage2_choices = (plan.get("stage2_proposal") or {}).get("choices") or []
    if "path_ids" not in merged:
        merged["path_ids"] = [row.get("record_id") for row in stage2_choices if isinstance(row, dict) and row.get("kind") in _PATH_KINDS and row.get("record_id")]
    if "method_id" not in merged:
        methods = [row.get("record_id") for row in stage2_choices if isinstance(row, dict) and row.get("kind") in _METHOD_KINDS and row.get("record_id")]
        if methods:
            merged["method_id"] = methods[0]
    if "foundation_id" not in merged:
        foundations = [row.get("record_id") for row in stage2_choices if isinstance(row, dict) and row.get("kind") in _FOUNDATION_KINDS and row.get("record_id")]
        if foundations:
            merged["foundation_id"] = foundations[0]
    return merged


def _values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [item for item in (value or []) if isinstance(item, str)] if isinstance(value, list) else []


def _selection_candidates(plan: dict[str, Any]) -> dict[str, list[tuple[str, list[str]]]]:
    """Collect every response representation that can carry a delegated ID.

    Complete-plan producers in the wild use the Stage 1 decision list, a
    catalog-priority object, or the explicit delegated-choice extension.  All
    three are accepted, but disagreeing representations are a hard conflict;
    the first representation must not silently win by dictionary order.
    """

    candidates: dict[str, list[tuple[str, list[str]]]] = {}

    def add(slot_id: str, value: Any, source: str) -> None:
        values = _values(value)
        if values:
            candidates.setdefault(slot_id, []).append((source, values))

    direct = plan.get("delegated_choice_selections")
    if isinstance(direct, dict):
        by_slot = direct.get("by_slot") or direct.get("slot_selections")
        if isinstance(by_slot, dict):
            for slot_id, value in by_slot.items():
                if isinstance(slot_id, str):
                    add(slot_id, value, "delegated_choice_selections.by_slot")
        for key, slot_id in _SELECTION_ALIASES.items():
            if key in direct:
                add(slot_id, direct[key], f"delegated_choice_selections.{key}")
        # A direct mapping may use the published slot IDs without a wrapper.
        for slot_id, value in direct.items():
            if isinstance(slot_id, str) and slot_id in {
                _PATH_SLOT, _METHOD_SLOT, _FOUNDATION_SLOT,
                "background_choice", "background_sphere_choice", "background_talent_choice",
                "origin_insight_choice", "subpath_choice", "sphere_priorities",
                "advancement_skeleton", "insight_priorities", "item_priorities",
            }:
                add(slot_id, value, f"delegated_choice_selections.{slot_id}")

    priority = _priority_order(plan)
    priority_source = "catalog_priority_order" if isinstance(plan.get("catalog_priority_order"), dict) else "stage2_proposal.catalog_priority_order"
    for key, slot_id in _SELECTION_ALIASES.items():
        if key in priority:
            add(slot_id, priority[key], f"{priority_source}.{key}")

    for decision in _stage1_payload(plan).get("decisions") or []:
        if not isinstance(decision, dict) or decision.get("state") != "selected":
            continue
        slot_id = decision.get("slot_id")
        if isinstance(slot_id, str):
            add(slot_id, decision.get("choice_ids") or [], f"stage1_response.decisions.{slot_id}")

    # Stage 2 is the final mechanical representation.  Its catalog rows are
    # reconciled with the delegated and priority representations below.  Stage
    # 1 remains a declared/owner representation and is checked as a subset when
    # the final mechanical representation contains later delegated additions.
    stage2_by_slot: dict[str, list[str]] = {}
    for row in (plan.get("stage2_proposal") or {}).get("choices") or []:
        if not isinstance(row, dict):
            continue
        slot_id = _STAGE2_DELEGATED_SLOT_KINDS.get(_canonical_stage2_kind(row.get("kind")))
        if slot_id and row.get("record_id"):
            stage2_by_slot.setdefault(slot_id, []).append(row["record_id"])
    for slot_id, values in stage2_by_slot.items():
        add(slot_id, values, f"stage2_proposal.choices.{slot_id}")
    return candidates


def catalog_stage2_selections(plan: dict[str, Any]) -> dict[str, Any]:
    """Return the exact typed catalog/mechanical IDs carried by Stage 2.

    This is deliberately a projection of response authority, not a planner
    interpretation.  Background and catalog-grant acquisitions stay in
    separate buckets so the server can derive the final grant accounting plan
    without silently treating a background route as an initial Sphere grant.
    """
    result: dict[str, Any] = {
        "path_ids": [],
        "method_ids": [],
        "foundation_ids": [],
        "background_ids": [],
        "background_sphere_ids": [],
        "background_talent_ids": [],
        "origin_insight_ids": [],
        "subpath_or_tradition_ids": [],
        "sphere_ids": [],
        "free_sphere_talent_ids": [],
        "ordinary_talent_ids": [],
        "insight_ids": [],
        "insight_occurrences": [],
        "item_ids": [],
    }
    buckets = {
        **{kind: "path_ids" for kind in _PATH_KINDS},
        **{kind: "method_ids" for kind in _METHOD_KINDS},
        **{kind: "foundation_ids" for kind in _FOUNDATION_KINDS},
        "background_acquisition": "background_ids",
        "background_sphere_acquisition": "background_sphere_ids",
        "background_talent_acquisition": "background_talent_ids",
        "origin_insight_acquisition": "origin_insight_ids",
        "origin_insight_selection": "origin_insight_ids",
        "subpath_acquisition": "subpath_or_tradition_ids",
        "tradition_acquisition": "subpath_or_tradition_ids",
        **{kind: "sphere_ids" for kind in _CATALOG_SPHERE_GRANT_KINDS},
        **{kind: "free_sphere_talent_ids" for kind in _CATALOG_FREE_TALENT_KINDS},
        **{kind: "ordinary_talent_ids" for kind in _CATALOG_ORDINARY_TALENT_KINDS},
        "cultivation_insight_acquisition": "insight_ids",
        "insight_acquisition": "insight_ids",
        "item_acquisition": "item_ids",
        "equipment_acquisition": "item_ids",
    }
    for row in (plan.get("stage2_proposal") or {}).get("choices") or []:
        if not isinstance(row, dict):
            continue
        canonical_kind = _canonical_stage2_kind(row.get("kind"))
        bucket = buckets.get(canonical_kind)
        record_id = row.get("record_id")
        if bucket and isinstance(record_id, str) and record_id:
            result[bucket].append(record_id)
        if canonical_kind == "cultivation_insight_acquisition" and isinstance(record_id, str) and record_id:
            parameters = row.get("parameters") if isinstance(row.get("parameters"), dict) else {}
            result["insight_occurrences"].append(
                {
                    "record_id": record_id,
                    "effective_cl": row.get("effective_cl"),
                    "legal_kind": "cultivation_insight_acquisition",
                    "acquisition_channel": row.get("acquisition_channel"),
                    "parameters": {
                        key: deepcopy(parameters[key])
                        for key in ("ability", "amount", "repeat_index")
                        if key in parameters
                    },
                }
            )
    return result


def response_authority_representations(plan: dict[str, Any]) -> dict[str, Any]:
    """Preserve all mechanical authority representations in the final plan."""
    stage1_decisions = [
        {
            "slot_id": row.get("slot_id"),
            "state": row.get("state"),
            "choice_ids": list(row.get("choice_ids") or []),
        }
        for row in _stage1_payload(plan).get("decisions") or []
        if isinstance(row, dict) and isinstance(row.get("slot_id"), str)
    ]
    return {
        "stage1_decisions": stage1_decisions,
        "delegated_choice_selections": deepcopy(plan.get("delegated_choice_selections") or {}),
        "catalog_priority_order": deepcopy(_priority_order(plan)),
        "stage2_mechanical_choices": catalog_stage2_selections(plan),
    }


def _resolved_slot_values(envelope: dict[str, Any], plan: dict[str, Any]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Resolve slot IDs and retain the exact source used for each slot."""

    canonical_intent = plan.get("canonical_selection_intent")
    if isinstance(canonical_intent, dict) and isinstance(canonical_intent.get("selected_by_slot"), dict):
        # REC1-P1CR3 has already separated planning preferences from actual
        # acquisitions.  Reusing the older representation merger here would
        # incorrectly require a 15-item priority list to equal (for example)
        # a 12-item explicit acquisition list.  The canonical intent is the
        # authority boundary; a materialized Stage 2 projection may only
        # confirm its actual IDs, never replace or extend them silently.
        resolved = {
            slot_id: _values(values)
            for slot_id, values in (canonical_intent.get("selected_by_slot") or {}).items()
            if isinstance(slot_id, str)
        }
        sources = {
            slot_id: [str(source) for source in values if isinstance(source, str)]
            for slot_id, values in (canonical_intent.get("sources_by_slot") or {}).items()
            if isinstance(slot_id, str) and isinstance(values, list)
        }
        planning_preferences = {
            slot_id: [
                _canonical_slot_choice_id(envelope, slot_id, choice_id)
                for choice_id in _values(values)
            ]
            for slot_id, values in (canonical_intent.get("planning_preferences_by_slot") or {}).items()
            if isinstance(slot_id, str)
        }
        # A priority order is never promoted to an acquisition.  It is used as
        # the visible/frozen selection only when no actual acquisition intent
        # exists for that slot, preserving historical Stage 1 validation while
        # keeping the canonical intent's acquisition list authoritative.
        for slot_id, values in planning_preferences.items():
            if slot_id not in _PLANNING_SLOT_IDS and resolved.get(slot_id) and resolved[slot_id] != values:
                _raise(
                    "CG1_DELEGATED_AUTHORITY_CONFLICT",
                    "A non-planning delegated slot has conflicting selection and priority representations.",
                    details={
                        "slot_id": slot_id,
                        "selected_choice_ids": resolved[slot_id],
                        "priority_choice_ids": values,
                    },
                )
            if not resolved.get(slot_id):
                resolved[slot_id] = list(values)
                sources.setdefault(slot_id, []).append("planning_preferences_by_slot")
        stage2_slot_kinds = {
            "path_acquisition": _PATH_SLOT,
            "method_acquisition": _METHOD_SLOT,
            "method_activation": _METHOD_SLOT,
            "foundation_acquisition": _FOUNDATION_SLOT,
            "foundation_expression": _FOUNDATION_SLOT,
            "foundation_stage": _FOUNDATION_SLOT,
            "background_acquisition": "background_choice",
            "background_sphere_acquisition": "background_sphere_choice",
            "background_talent_acquisition": "background_talent_choice",
            "origin_insight_acquisition": "origin_insight_choice",
            "origin_insight_selection": "origin_insight_choice",
            "subpath_acquisition": "subpath_choice",
            "tradition_acquisition": "subpath_choice",
            "item_acquisition": "item_priorities",
            "equipment_acquisition": "item_priorities",
            "sect_trial_sphere_acquisition": "sphere_priorities",
            "ai_bootstrap_sphere_acquisition": "sphere_priorities",
            "sphere_acquisition": "sphere_priorities",
            "sect_trial_talent_acquisition": "advancement_skeleton",
            "ai_bootstrap_talent_acquisition": "advancement_skeleton",
            "level_talent_acquisition": "advancement_skeleton",
            "new_sphere_bonus_talent_acquisition": "advancement_skeleton",
            "talent_acquisition": "advancement_skeleton",
            "cultivation_insight_acquisition": "insight_priorities",
            "insight_acquisition": "insight_priorities",
        }
        stage2_values: dict[str, list[str]] = {}
        for row in (plan.get("stage2_proposal") or {}).get("choices") or []:
            if not isinstance(row, dict) or not isinstance(row.get("record_id"), str):
                continue
            kind = _canonical_stage2_kind(row.get("kind"))
            slot_id = stage2_slot_kinds.get(kind)
            if slot_id:
                stage2_values.setdefault(slot_id, []).append(row["record_id"])
        for slot_id, values in stage2_values.items():
            values = _values(values)
            existing = resolved.get(slot_id) or []
            if existing and existing != values:
                _raise(
                    "CG1_DELEGATED_AUTHORITY_CONFLICT",
                    "The server-materialized Stage 2 IDs do not equal the canonical delegated intent.",
                    details={
                        "slot_id": slot_id,
                        "canonical_choice_ids": existing,
                        "stage2_choice_ids": values,
                    },
                )
            if not existing:
                resolved[slot_id] = values
                sources.setdefault(slot_id, []).append("server_materialized_stage2")
        for slot_id, values in resolved.items():
            canonical_values = [
                _canonical_slot_choice_id(envelope, slot_id, choice_id)
                for choice_id in values
            ]
            resolved[slot_id] = canonical_values
            _ensure_allowed(envelope, slot_id, canonical_values)
            limits = (envelope.get("selection_limits_by_slot") or {}).get(slot_id) or {}
            minimum = limits.get("final_min")
            maximum = limits.get("final_max")
            if minimum is not None and len(canonical_values) < int(minimum):
                _raise(
                    "CG1_DELEGATED_CHOICE_COUNT_INVALID",
                    "The canonical delegated intent selected fewer IDs than the frozen slot minimum.",
                    details={"slot_id": slot_id, "minimum": minimum, "actual": len(canonical_values)},
                )
            if maximum is not None and len(canonical_values) > int(maximum):
                _raise(
                    "CG1_DELEGATED_CHOICE_COUNT_INVALID",
                    "The canonical delegated intent selected more IDs than the frozen slot maximum.",
                    details={"slot_id": slot_id, "maximum": maximum, "actual": len(canonical_values)},
                )
        return resolved, sources

    resolved: dict[str, list[str]] = {}
    sources: dict[str, list[str]] = {}
    for slot_id, entries in _selection_candidates(plan).items():
        entries = [
            (
                source,
                [
                    _canonical_slot_choice_id(envelope, slot_id, choice_id)
                    for choice_id in values
                ],
            )
            for source, values in entries
        ]
        final_entries = [
            (source, values)
            for source, values in entries
            if not source.startswith("stage1_response.decisions.")
        ]
        # A Stage 1 selected row records an owner/declaration constraint.  It
        # may be a strict subset of the final Stage 2 catalog rows, but it may
        # never disappear from the final plan.  All final representations must
        # still agree exactly with one another.
        stage1_entries = [
            (source, values)
            for source, values in entries
            if source.startswith("stage1_response.decisions.")
        ]
        authority_entries = final_entries or entries
        distinct: dict[tuple[str, ...], list[str]] = {}
        for source, values in authority_entries:
            distinct.setdefault(tuple(values), []).append(source)
        if len(distinct) > 1:
            _raise(
                "CG1_DELEGATED_AUTHORITY_CONFLICT",
                "The complete response supplied conflicting delegated IDs for the same authority slot.",
                details={
                    "slot_id": slot_id,
                    "representations": [
                        {"source": source, "choice_ids": values}
                         for source, values in authority_entries
                        ],
                },
            )
        values, matching_sources = next(iter(distinct.items()))
        for source, stage1_values in stage1_entries:
            if not set(stage1_values).issubset(set(values)):
                _raise(
                    "CG1_DELEGATED_AUTHORITY_CONFLICT",
                    "A Stage 1 declared choice is absent from the accepted final mechanical representation.",
                    details={
                        "slot_id": slot_id,
                        "source": source,
                        "declared_choice_ids": stage1_values,
                        "final_choice_ids": list(values),
                    },
                )
            matching_sources.append(source)
        resolved[slot_id] = list(values)
        sources[slot_id] = list(matching_sources)
        _ensure_allowed(envelope, slot_id, list(values))
        limits = (envelope.get("selection_limits_by_slot") or {}).get(slot_id) or {}
        minimum = limits.get("final_min")
        maximum = limits.get("final_max")
        if minimum is not None and len(values) < int(minimum):
            _raise("CG1_DELEGATED_CHOICE_COUNT_INVALID", "The response selected fewer IDs than the frozen slot minimum.", details={"slot_id": slot_id, "minimum": minimum, "actual": len(values)})
        if maximum is not None and len(values) > int(maximum):
            _raise("CG1_DELEGATED_CHOICE_COUNT_INVALID", "The response selected more IDs than the frozen slot maximum.", details={"slot_id": slot_id, "maximum": maximum, "actual": len(values)})
    return resolved, sources


def _raise(code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
    raise FoundryError(code, message, details=details or {}, status_code=409)


def _ensure_allowed(
    envelope: dict[str, Any],
    slot_id: str,
    values: list[str],
    *,
    required: bool = False,
) -> None:
    if len(values) != len(set(values)):
        _raise("CG1_DELEGATED_DUPLICATE_CHOICE", "A delegated choice list contains duplicate IDs.", details={"slot_id": slot_id, "choice_ids": values})
    allowed = set((envelope.get("allowed_choice_ids_by_slot") or {}).get(slot_id) or [])
    out = sorted(set(values) - allowed)
    if out:
        _raise(
            "CG1_DELEGATED_CHOICE_OUT_OF_ENVELOPE",
            "The response selected an ID that was not offered and allowed by the frozen delegated-choice envelope.",
            details={"slot_id": slot_id, "choice_ids": out, "offered_choice_ids": (envelope.get("offered_choice_ids_by_slot") or {}).get(slot_id, []), "allowed_choice_ids": sorted(allowed)},
        )
    if required and not values:
        _raise("CG1_DELEGATED_CHOICE_REQUIRED", "The response omitted a required delegated choice.", details={"slot_id": slot_id})
    for choice_id in values:
        choice = ((envelope.get("choices_by_slot") or {}).get(slot_id) or {}).get(choice_id) or {}
        availability = choice.get("availability") if isinstance(choice.get("availability"), dict) else {}
        if (
            availability.get("available") is False
            or choice.get("selectable") is False
            # Method access is checked against the exact owner route/evidence
            # below, after the complete Method row and project locks are
            # available.  Do not let this generic choice check accidentally
            # turn a displayed, route-authorized restricted Method into an
            # inaccessible one; also do not use it to grant access.
            or (
                choice.get("initial_creation_selectable") is False
                and slot_id != _METHOD_SLOT
            )
        ):
            _raise("CG1_DELEGATED_CHOICE_UNAVAILABLE", "The response selected an unavailable choice.", details={"slot_id": slot_id, "choice_id": choice_id})


def _relation_targets(relation: Any) -> list[str]:
    if isinstance(relation, str):
        return [relation]
    if not isinstance(relation, dict):
        return []
    targets = relation.get("target_ids") or relation.get("targets")
    if isinstance(targets, str):
        return [targets]
    if isinstance(targets, list):
        return [target for target in targets if isinstance(target, str)]
    target = relation.get("target_id") or relation.get("record_id") or relation.get("canonical_id") or relation.get("id")
    return [target] if isinstance(target, str) else []


def _validate_path_subpath_bindings(
    envelope: dict[str, Any],
    selected_by_slot: dict[str, list[str]],
) -> None:
    """Require one frozen Path-owned Subpath/Tradition per selected owner.

    The delegated envelope already contains the exact Stage 1 choice snapshots,
    including their typed parent relationships.  This check deliberately uses
    those relationships rather than names or a global first-subpath fallback.
    """
    path_ids = list(selected_by_slot.get(_PATH_SLOT) or [])
    subpath_ids = list(selected_by_slot.get("subpath_choice") or [])
    if not subpath_ids:
        return
    choices = (envelope.get("choices_by_slot") or {}).get("subpath_choice") or {}
    selected_paths = set(path_ids)
    by_owner: dict[str, str] = {}
    for subpath_id in subpath_ids:
        choice = choices.get(subpath_id) or {}
        owning_path_id = choice.get("owning_path_id")
        owning_path_choice_ids = choice.get("owning_path_choice_ids") or []
        if not isinstance(owning_path_id, str) or owning_path_id not in CANONICAL_PATH_IDS:
            _raise(
                "CG1_PATH_SUBPATH_MISMATCH",
                "Each selected Subpath or Tradition must publish one explicit canonical owning Path.",
                details={"subpath_id": subpath_id, "selected_path_ids": path_ids},
            )
        if owning_path_choice_ids != [owning_path_id]:
            _raise(
                "CG1_PATH_SUBPATH_MISMATCH",
                "The frozen Subpath ownership representations disagree.",
                details={
                    "subpath_id": subpath_id,
                    "owning_path_id": owning_path_id,
                    "owning_path_choice_ids": owning_path_choice_ids,
                },
            )
        owners = {owning_path_id} & selected_paths
        if len(owners) != 1:
            _raise(
                "CG1_PATH_SUBPATH_MISMATCH",
                "Each selected Subpath or Tradition must belong to exactly one final selected Path.",
                details={
                    "subpath_id": subpath_id,
                    "selected_path_ids": path_ids,
                    "owning_path_ids": sorted(owners),
                },
            )
        owner = next(iter(owners))
        prior = by_owner.get(owner)
        if prior is not None:
            _raise(
                "CG1_MULTIPLE_SUBPATHS_FOR_ONE_PATH",
                "Each selected Path may have only one current Subpath or Tradition.",
                details={"path_id": owner, "choice_ids": [prior, subpath_id]},
            )
        by_owner[owner] = subpath_id


def _validate_frozen_legality(
    envelope: dict[str, Any],
    selected_by_slot: dict[str, list[str]],
    plan: dict[str, Any],
    *,
    automatic_ids: set[str] | None = None,
) -> None:
    """Re-evaluate the frozen typed legality relations against the final IDs."""

    present = {
        choice_id
        for choice_ids in selected_by_slot.values()
        for choice_id in choice_ids
    }
    present.update(automatic_ids or set())
    target_cl = plan.get("target_cl")
    for slot_id, choice_ids in selected_by_slot.items():
        rows = (envelope.get("choices_by_slot") or {}).get(slot_id) or {}
        for choice_id in choice_ids:
            choice = rows.get(choice_id) or {}
            availability = choice.get("availability") if isinstance(choice.get("availability"), dict) else {}
            minimum_cl = availability.get("minimum_cl")
            if isinstance(minimum_cl, int) and isinstance(target_cl, int) and target_cl < minimum_cl:
                _raise(
                    "CG1_DELEGATED_CHOICE_UNAVAILABLE",
                    "The selected choice is unavailable at the response target CL in the frozen envelope.",
                    details={"slot_id": slot_id, "choice_id": choice_id, "minimum_cl": minimum_cl, "target_cl": target_cl},
                )
            relations = choice.get("prerequisites")
            if relations is None and isinstance(choice.get("legality"), dict):
                relations = choice["legality"].get("prerequisites")
            for index, relation in enumerate(relations or []):
                if not isinstance(relation, dict):
                    _raise(
                        "CG1_DELEGATED_PREREQUISITE_UNSUPPORTED",
                        "The frozen choice contains an untyped prerequisite and cannot be safely delegated.",
                        details={"slot_id": slot_id, "choice_id": choice_id, "index": index, "prerequisite": relation},
                    )
                operator = relation.get("operator", "requires")
                targets = _relation_targets(relation)
                if not targets:
                    _raise(
                        "CG1_DELEGATED_PREREQUISITE_UNSUPPORTED",
                        "The frozen prerequisite has no typed target and cannot be safely delegated.",
                        details={"slot_id": slot_id, "choice_id": choice_id, "index": index, "prerequisite": relation},
                    )
                if operator == "requires":
                    satisfied = all(target in present for target in targets)
                elif operator == "one_of":
                    satisfied = any(target in present for target in targets)
                elif operator == "all_of":
                    satisfied = all(target in present for target in targets)
                elif operator == "not":
                    satisfied = not any(target in present for target in targets)
                else:
                    _raise(
                        "CG1_DELEGATED_PREREQUISITE_UNSUPPORTED",
                        "The frozen prerequisite operator is not supported by the delegated validator.",
                        details={"slot_id": slot_id, "choice_id": choice_id, "index": index, "operator": operator},
                    )
                if not satisfied:
                    _raise(
                        "CG1_DELEGATED_PREREQUISITE_UNMET",
                        "A selected delegated choice does not satisfy its frozen prerequisite.",
                        details={"slot_id": slot_id, "choice_id": choice_id, "prerequisite": relation, "present_choice_ids": sorted(present)},
                    )
            incompatibilities = choice.get("incompatibilities")
            if incompatibilities is None and isinstance(choice.get("legality"), dict):
                incompatibilities = choice["legality"].get("incompatibilities")
            incompatible_ids = {
                target
                for relation in incompatibilities or []
                for target in _relation_targets(relation)
            }
            conflicting = sorted(incompatible_ids & (present - {choice_id}))
            if conflicting:
                _raise(
                    "CG1_DELEGATED_INCOMPATIBILITY",
                    "A selected delegated choice conflicts with another final choice in the frozen envelope.",
                    details={"slot_id": slot_id, "choice_id": choice_id, "incompatible_choice_ids": conflicting},
                )


def _validate_semantic_acquisition_intent(
    envelope: dict[str, Any],
    plan: dict[str, Any],
    selected_by_slot: dict[str, list[str]],
) -> None:
    """Validate the preferred semantic acquisitions before materialization.

    This is deliberately an envelope check, not a catalog lookup.  The later
    materializer proves ownership and grant legality again from project-locked
    records.  Keeping this first check here gives response authors precise
    out-of-envelope, pair, duplicate, and milestone diagnostics without ever
    accepting a planner-authored event kind or channel.
    """

    intent = plan.get("canonical_selection_intent") or {}
    acquisition = intent.get("acquisition_intent") if isinstance(intent, dict) else None
    if not isinstance(acquisition, dict):
        _raise(
            "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID",
            "The canonical intent does not contain semantic acquisition fields.",
        )
    sphere_slot = "sphere_priorities"
    talent_slot = "advancement_skeleton"
    insight_slot = "insight_priorities"
    pair_spheres: list[str] = []
    pair_talents: list[str] = []
    for index, pair in enumerate(acquisition.get("sphere_free_talent_pairs") or []):
        if not isinstance(pair, dict):
            _raise("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Every Sphere acquisition must be a semantic pair.", details={"index": index})
        sphere_id = pair.get("sphere_id")
        talent_id = pair.get("talent_id")
        if not isinstance(sphere_id, str) or not isinstance(talent_id, str):
            _raise("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "A Sphere/free-Talent pair requires two stable IDs.", details={"index": index})
        pair_spheres.append(sphere_id)
        pair_talents.append(talent_id)
    if len(pair_spheres) != len(set(pair_spheres)) or len(pair_talents) != len(set(pair_talents)):
        _raise("CG1_DELEGATED_DUPLICATE_CHOICE", "Sphere/free-Talent pairs may not repeat a Sphere or Talent.", details={"sphere_ids": pair_spheres, "talent_ids": pair_talents})
    _ensure_allowed(envelope, sphere_slot, pair_spheres)
    _ensure_allowed(envelope, talent_slot, pair_talents)
    choice_map = (envelope.get("choices_by_slot") or {}).get(talent_slot) or {}
    typed_authority_by_choice = (
        (envelope.get("typed_choice_authority_by_slot") or {})
        .get(talent_slot, {})
        .get("stage2_authority_by_choice", {})
    )
    for sphere_id, talent_id in zip(pair_spheres, pair_talents):
        talent_choice = choice_map.get(talent_id) or {}
        authority = typed_authority_by_choice.get(talent_id)
        if not isinstance(authority, dict):
            authority = talent_choice.get("stage2_authority")
        if not isinstance(authority, dict):
            authority = (talent_choice.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
        if not isinstance(authority, dict):
            authority = {}
        owning_sphere = (
            talent_choice.get("owning_sphere_id")
            or talent_choice.get("owning_canonical_sphere_id")
            or authority.get("owning_sphere_id")
            or authority.get("owning_canonical_sphere_id")
            or authority.get("sphere_id")
        )
        if isinstance(owning_sphere, str) and owning_sphere != sphere_id:
            _raise(
                "CG1_DELEGATED_FREE_TALENT_SPHERE_MISMATCH",
                "The selected free Talent does not belong to its selected Sphere in the frozen envelope.",
                details={"sphere_id": sphere_id, "talent_id": talent_id, "owning_sphere_id": owning_sphere},
            )
        if authority.get("free_sphere_talent_eligible") is False or talent_choice.get("free_sphere_talent_eligible") is False:
            _raise(
                "CG1_DELEGATED_FREE_TALENT_NOT_LEGAL",
                "The selected Talent is not a legal free-Talent grant for its Sphere in frozen authority.",
                details={"sphere_id": sphere_id, "talent_id": talent_id},
            )

    ordinary = [value for value in acquisition.get("ordinary_talent_ids") or [] if isinstance(value, str)]
    _ensure_allowed(envelope, talent_slot, ordinary)
    if len(ordinary) != len(set(ordinary)) or set(ordinary).intersection(pair_talents):
        _raise(
            "CG1_DELEGATED_DUPLICATE_CHOICE",
            "A free Sphere Talent cannot be repeated as an ordinary Talent acquisition.",
            details={"ordinary_talent_ids": ordinary, "free_talent_ids": pair_talents},
        )
    expected_count = envelope.get("ordinary_talent_count")
    if isinstance(expected_count, int) and len(ordinary) != expected_count:
        _raise(
            "CG1_BOUNDED_DECISION_REQUIRED",
            "The ordinary Talent acquisition count does not equal the source-governed creation capacity.",
            details={"field": "acquisition_intent.ordinary_talent_ids", "required_count": expected_count, "actual_count": len(ordinary)},
        )

    milestone_rows = {
        row.get("milestone_id"): row
        for row in envelope.get("advancement_choice_milestones") or []
        if isinstance(row, dict) and isinstance(row.get("milestone_id"), str)
    }
    insight_occurrences = acquisition.get("insight_occurrences") or []
    occurrence_milestones: list[str] = []
    for index, occurrence in enumerate(insight_occurrences):
        if not isinstance(occurrence, dict):
            _raise("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Every Insight occurrence must be a semantic object.", details={"index": index})
        insight_id = occurrence.get("insight_id")
        milestone_id = occurrence.get("milestone_id")
        if not isinstance(insight_id, str) or not isinstance(milestone_id, str):
            _raise("CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "Insight occurrences require insight_id and milestone_id.", details={"index": index})
        _ensure_allowed(envelope, insight_slot, [insight_id])
        if milestone_id not in milestone_rows:
            _raise(
                "CG1_BOUNDED_DECISION_REQUIRED",
                "The Insight occurrence names a milestone that was not advertised by the frozen Path authority.",
                details={"field": f"acquisition_intent.insight_occurrences[{index}].milestone_id", "milestone_id": milestone_id, "allowed_milestone_ids": sorted(milestone_rows)},
            )
        occurrence_milestones.append(milestone_id)
        parameters = occurrence.get("parameters") or {}
        choice = ((envelope.get("choices_by_slot") or {}).get(insight_slot) or {}).get(insight_id) or {}
        authority = (
            (envelope.get("typed_choice_authority_by_slot") or {})
            .get(insight_slot, {})
            .get("stage2_authority_by_choice", {})
            .get(insight_id)
        )
        if not isinstance(authority, dict):
            authority = choice.get("stage2_authority")
        if not isinstance(authority, dict):
            authority = (choice.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
        if not isinstance(authority, dict):
            authority = {}
        rule = authority.get("ability_change") or authority.get("insight_ability_change") or {}
        allowed_parameters = {"ability"} if rule else set()
        unsupported = sorted(set(parameters) - allowed_parameters)
        if unsupported:
            _raise(
                "CG1_INSIGHT_PARAMETER_OUT_OF_AUTHORITY",
                "Insight parameters are outside the selected Insight's frozen typed authority.",
                details={"insight_id": insight_id, "milestone_id": milestone_id, "unsupported_parameters": unsupported, "allowed_parameters": sorted(allowed_parameters)},
            )
        if rule and "ability" in parameters and parameters["ability"] not in (rule.get("allowed_abilities") or []):
            _raise(
                "CG1_INSIGHT_PARAMETER_OUT_OF_AUTHORITY",
                "The selected Insight ability is not in its frozen typed authority.",
                details={"insight_id": insight_id, "milestone_id": milestone_id, "ability": parameters["ability"], "allowed_abilities": rule.get("allowed_abilities") or []},
            )
    if len(occurrence_milestones) != len(set(occurrence_milestones)):
        _raise("CG1_DELEGATED_DUPLICATE_CHOICE", "An Insight milestone may be resolved only once.", details={"milestone_ids": occurrence_milestones})

    # Relation evaluation includes both planning selections and explicit
    # semantic acquisitions.  Do not mutate the canonical selected mapping;
    # the extra IDs are a legality-only view.
    legality_slots = deepcopy(selected_by_slot)
    legality_slots.setdefault(sphere_slot, [])
    legality_slots.setdefault(talent_slot, [])
    legality_slots.setdefault(insight_slot, [])
    for value in pair_spheres:
        if value not in legality_slots[sphere_slot]:
            legality_slots[sphere_slot].append(value)
    for value in pair_talents + ordinary:
        if value not in legality_slots[talent_slot]:
            legality_slots[talent_slot].append(value)
    for occurrence in insight_occurrences:
        if occurrence["insight_id"] not in legality_slots[insight_slot]:
            legality_slots[insight_slot].append(occurrence["insight_id"])
    _validate_frozen_legality(envelope, legality_slots, plan)


def _selection_from_plan(plan: dict[str, Any], key: str) -> list[str]:
    values = _delegated_selection(plan).get(key)
    return _values(values)


def _method_row(envelope: dict[str, Any], method_id: str) -> dict[str, Any]:
    return deepcopy(((envelope.get("choices_by_slot") or {}).get(_METHOD_SLOT) or {}).get(method_id) or {})


def _foundation_compatibility(method_row: dict[str, Any], foundation_row: dict[str, Any], method_id: str, foundation_id: str) -> None:
    compatible_methods = foundation_row.get("compatible_method_ids") or _authority_mapping(foundation_row).get("compatible_method_ids") or []
    if compatible_methods and method_id not in compatible_methods:
        _raise("CG1_METHOD_FOUNDATION_INCOMPATIBLE", "The selected Foundation does not accept the selected Method.", details={"method_id": method_id, "foundation_id": foundation_id, "compatible_method_ids": compatible_methods})
    compatible_foundations = method_row.get("compatible_foundation_ids") or _authority_mapping(method_row).get("compatible_foundation_ids") or []
    if compatible_foundations and foundation_id not in compatible_foundations:
        _raise("CG1_METHOD_FOUNDATION_INCOMPATIBLE", "The selected Method does not accept the selected Foundation.", details={"method_id": method_id, "foundation_id": foundation_id, "compatible_foundation_ids": compatible_foundations})


def _validate_selected_slot_values(envelope: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    by_slot, sources = _resolved_slot_values(envelope, plan)
    resolved: dict[str, Any] = {"by_slot": by_slot, "sources_by_slot": sources}
    for key, slot_id in {
        "path_ids": _PATH_SLOT,
        "sphere_ids": "sphere_priorities",
        "talent_ids": "advancement_skeleton",
        "insight_ids": "insight_priorities",
        "item_ids": "item_priorities",
    }.items():
        resolved[key] = list(by_slot.get(slot_id) or [])
    for key, slot_id in (("method_id", _METHOD_SLOT), ("foundation_id", _FOUNDATION_SLOT)):
        values = list(by_slot.get(slot_id) or [])
        if len(values) > 1:
            _raise("CG1_DELEGATED_CHOICE_COUNT_INVALID", "A single-select delegated slot received multiple IDs.", details={"slot_id": slot_id, "choice_ids": values})
        resolved[key] = values
    return resolved


def validate_delegated_choice_plan(
    run: dict[str, Any],
    project: dict[str, Any],
    plan: dict[str, Any],
    *,
    response_sha256: str | None = None,
) -> dict[str, Any] | None:
    """Validate and return a server-owned final plan, or ``None`` for legacy prompts."""

    envelope = ((run.get("request") or {}).get("delegated_choice_envelope") or {})
    if not envelope:
        return None
    if not isinstance(plan.get("canonical_selection_intent"), dict):
        # Keep the authority function independently useful for callers that
        # validate a preferred response directly rather than through the full
        # execution service.  The execution service performs the same step
        # before compilation and persists the resulting hash/evidence.
        try:
            intent = normalize_selection_intent(
                plan,
                request_sha256=str((run.get("request") or {}).get("request_sha256") or ""),
                delegated_envelope=envelope,
                project=project,
                target_cl=frozen_owner_target_cl(project),
            )
            plan = inject_canonical_intent(plan, intent, target_cl=frozen_owner_target_cl(project))
        except FoundryError:
            raise
    if _stable_hash({key: value for key, value in envelope.items() if key != "envelope_sha256"}) != envelope.get("envelope_sha256"):
        _raise("CG1_DELEGATED_ENVELOPE_TAMPERED", "The persisted delegated-choice envelope no longer matches its sealed hash.")
    binding = envelope.get("binding") or {}
    lock = project.get("content_lock") or {}
    actual_binding = {
        "project_id": project.get("project_id"),
        "project_revision": project.get("revision"),
        "catalog_build_id": lock.get("catalog_build_id"),
        "content_lock_hash": lock.get("lock_hash"),
    }
    expected_binding = {key: binding.get(key) for key in actual_binding}
    if actual_binding != expected_binding:
        _raise("CG1_DELEGATED_ENVELOPE_STALE", "The project revision or content lock changed after the delegated request was frozen.", details={"expected": expected_binding, "actual": actual_binding})
    target_cl = validate_delegated_target_cl(run, project, plan)
    locks = _locks(project)
    if _stable_hash(_owner_user_locks(project)) != (envelope.get("owner_locks") or {}).get("lock_sha256"):
        _raise("CG1_DELEGATED_OWNER_LOCKS_CHANGED", "Owner locks changed after the delegated request was frozen.")
    one_shot = envelope.get("one_shot") or {}
    if one_shot.get("idempotency_key") != run.get("idempotency_key") or one_shot.get("execution_mode") != run.get("execution_mode"):
        _raise("CG1_DELEGATED_ONE_SHOT_BINDING_MISMATCH", "The delegated envelope is bound to a different one-shot run.")

    selected = _validate_selected_slot_values(envelope, plan)
    selected_by_slot = deepcopy(selected.get("by_slot") or {})
    selection_sources = deepcopy(selected.get("sources_by_slot") or {})
    owner_by_slot = deepcopy((envelope.get("owner_locks") or {}).get("by_slot") or {})
    owner_paths = list(owner_by_slot.get(_PATH_SLOT) or [])
    selected_paths = list(selected_by_slot.get(_PATH_SLOT) or [])
    if not selected_paths:
        if owner_paths:
            selected_paths = owner_paths
        else:
            _raise("CG1_DELEGATED_PATH_REQUIRED", "A complete character must end with one to three selected canonical Paths; zero owner locks do not authorize a final no-Path plan.")
    try:
        selected_paths = canonicalize_path_ids(selected_paths, allow_empty=False)
    except FoundryError as exc:
        _raise(exc.code, exc.message, details=exc.details)
    selected_by_slot[_PATH_SLOT] = list(selected_paths)
    for slot_id, locked_ids in owner_by_slot.items():
        locked_ids = list(locked_ids or [])
        if not locked_ids:
            continue
        final_ids = list(selected_by_slot.get(slot_id) or [])
        if slot_id != _PATH_SLOT and not final_ids:
            final_ids = list(locked_ids)
            selected_by_slot[slot_id] = final_ids
            selection_sources.setdefault(slot_id, []).append("owner_lock_fallback")
        if not set(locked_ids).issubset(final_ids):
            _raise(
                "CG1_OWNER_LOCK_NOT_PRESERVED",
                "The final delegated selection does not preserve every owner-locked choice.",
                details={"slot_id": slot_id, "owner_locked_choice_ids": locked_ids, "final_choice_ids": final_ids},
            )
        _ensure_allowed(envelope, slot_id, final_ids, required=True)
        limits = (envelope.get("selection_limits_by_slot") or {}).get(slot_id) or {}
        maximum = limits.get("final_max")
        if maximum is not None and len(final_ids) > int(maximum):
            _raise(
                "CG1_DELEGATED_CHOICE_COUNT_INVALID",
                "Owner-locked choices exceed the frozen delegated slot maximum.",
                details={"slot_id": slot_id, "maximum": maximum, "actual": len(final_ids)},
            )
    _ensure_allowed(envelope, _PATH_SLOT, selected_paths, required=True)

    method_values = list(selected_by_slot.get(_METHOD_SLOT) or [])
    if len(method_values) > 1:
        _raise("CG1_DELEGATED_CHOICE_COUNT_INVALID", "A single-select Method slot received multiple IDs.", details={"slot_id": _METHOD_SLOT, "choice_ids": method_values})
    method_id = method_values[0] if method_values else None
    method_row = _method_row(envelope, method_id) if method_id else {}
    path_authority = envelope.get("path_method_authority") or {}
    grants = list((path_authority.get("method_granted_path_ids") or {}).get(method_id) or method_row.get("related_choice_ids") or []) if method_id else []
    grants = canonicalize_path_ids(grants) if grants else []
    deferred_method = not method_id
    if deferred_method and not owner_paths:
        _raise("CG1_DELEGATED_METHOD_REQUIRED", "A zero-owner-lock delegated run must choose a legal Method so the server can derive its exact AP-granted Path set.")
    if method_id:
        if not method_row:
            _raise("CG1_DELEGATED_METHOD_UNKNOWN", "The selected Method is absent from the frozen Method envelope.", details={"method_id": method_id})
        compatibility = method_path_compatibility(selected_paths, {**method_row, "method_id": method_id, "related_choice_ids": grants})
        if compatibility["missing_path_ids"]:
            _raise("CG1_METHOD_PATH_INCOMPATIBLE", "The selected Method does not explicitly grant AP for every final selected Path.", details=compatibility)
        method_access = (
            (path_authority.get("method_access_by_id") or {}).get(method_id)
            or method_row.get("method_access")
            or {
                "initial_creation_selectable": method_row.get("initial_creation_selectable") is True,
                "owner_route_options": method_row.get("owner_route_options") or [],
            }
        )
        if method_access.get("initial_creation_selectable") is False:
            proof = _method_access_proof(project, method_id, method_access)
            if proof.get("selection_authorized") is not True:
                _raise(
                    "CG1_METHOD_ACCESS_REQUIRED",
                    "This Method is compatible with the selected Paths but cannot be selected without an advertised exact owner access route or evidence.",
                    details={
                        "method_id": method_id,
                        "access_tier": method_access.get("access_tier"),
                        "access_text": method_access.get("access_text") or "",
                        "owner_route_options": deepcopy(method_access.get("owner_route_options") or []),
                        "exact_selection_available": bool(method_access.get("exact_selection_available")),
                        "route_configurable": proof.get("route_configurable"),
                        "evidence_present": proof.get("evidence_present"),
                    },
                )
    else:
        # Historical owner-locked runs are allowed to leave Method deferred or
        # typed-none.  The compatibility state is explicit and never treated
        # as a hidden Method choice.
        grants = []

    _validate_frozen_legality(
        envelope,
        selected_by_slot,
        plan,
        automatic_ids=set(grants),
    )
    _validate_path_subpath_bindings(envelope, selected_by_slot)
    _validate_semantic_acquisition_intent(envelope, plan, selected_by_slot)

    foundation_values = list(selected_by_slot.get(_FOUNDATION_SLOT) or [])
    if len(foundation_values) > 1:
        _raise("CG1_DELEGATED_CHOICE_COUNT_INVALID", "A single-select Foundation slot received multiple IDs.", details={"slot_id": _FOUNDATION_SLOT, "choice_ids": foundation_values})
    foundation_id = foundation_values[0] if foundation_values else None
    foundation_row = ((envelope.get("choices_by_slot") or {}).get(_FOUNDATION_SLOT) or {}).get(foundation_id) if foundation_id else {}
    if foundation_id and foundation_row:
        _foundation_compatibility(method_row, foundation_row, method_id or "DEFERRED", foundation_id)
        foundation_paths = set(foundation_row.get("related_choice_ids") or foundation_row.get("compatible_path_ids") or [])
        if foundation_paths and not set(selected_paths).issubset(foundation_paths):
            _raise("CG1_FOUNDATION_PATH_INCOMPATIBLE", "The selected Foundation does not support every final selected Path.", details={"foundation_id": foundation_id, "selected_path_ids": selected_paths, "supported_path_ids": sorted(foundation_paths)})

    stage2_choices = (plan.get("stage2_proposal") or {}).get("choices") or []
    for row in stage2_choices:
        if not isinstance(row, dict) or not row.get("record_id"):
            continue
        slot_id = _STAGE2_DELEGATED_SLOT_KINDS.get(_canonical_stage2_kind(row.get("kind")))
        if slot_id:
            _ensure_allowed(
                envelope,
                slot_id,
                [_canonical_slot_choice_id(envelope, slot_id, row["record_id"])],
            )
    proposed_path_ids = [row.get("record_id") for row in stage2_choices if isinstance(row, dict) and row.get("kind") in _PATH_KINDS and row.get("record_id")]
    if proposed_path_ids:
        _ensure_allowed(envelope, _PATH_SLOT, proposed_path_ids)
        if len(proposed_path_ids) != len(set(proposed_path_ids)):
            _raise("CG1_DELEGATED_DUPLICATE_CHOICE", "The Stage2 proposal repeats a canonical Path acquisition.", details={"path_ids": proposed_path_ids})
        if method_id and not set(proposed_path_ids).issubset(set(grants)):
            _raise("CG1_PATH_PROPOSAL_NOT_METHOD_GRANTED", "The Stage2 proposal advances a Path outside the selected Method AP grant set.", details={"proposed_path_ids": proposed_path_ids, "method_granted_path_ids": grants})

    descriptive = deepcopy(plan.get("owner_descriptive_fields") or {})
    identity = descriptive.get("identity") if isinstance(descriptive.get("identity"), dict) else {}
    delegated_fields = envelope.get("delegated_fields") or {}
    name_authority = delegated_fields.get("identity.name") or {}
    response_identity_name = identity.get("name") if isinstance(identity, dict) else None
    response_identity_name_text = (
        response_identity_name.strip()
        if isinstance(response_identity_name, str)
        else ""
    )
    if name_authority.get("state") == "delegated" and not response_identity_name_text:
        _raise(
            DELEGATED_NAME_REQUIRED_ERROR,
            "A delegated character name is required: owner_descriptive_fields.identity.name must contain a nonblank proposed name for owner review.",
            details={
                "field": "owner_descriptive_fields.identity.name",
                "required": True,
                "nonblank": True,
                "state": "delegated",
            },
        )
    if name_authority.get("state") == "owner_locked":
        owner_name = str(name_authority.get("owner_value") or "").strip()
        if not response_identity_name_text or response_identity_name_text != owner_name:
            _raise(
                "CG1_OWNER_LOCKED_DESCRIPTIVE_FIELD_CHANGED",
                "The response must contain the exact owner-locked character name unchanged.",
                details={
                    "field": "owner_descriptive_fields.identity.name",
                    "expected": owner_name,
                    "actual": response_identity_name_text or None,
                },
            )
    name_values = [
        str(value).strip()
        for value in (identity.get("name"), descriptive.get("name"))
        if str(value or "").strip()
    ]
    concept_values = [
        str(value).strip()
        for value in (descriptive.get("concept"), descriptive.get("character_concept"))
        if str(value or "").strip()
    ]
    if len(set(name_values)) > 1:
        _raise("CG1_DELEGATED_AUTHORITY_CONFLICT", "The response supplied conflicting delegated name representations.", details={"representations": name_values})
    if len(set(concept_values)) > 1:
        _raise("CG1_DELEGATED_AUTHORITY_CONFLICT", "The response supplied conflicting delegated concept representations.", details={"representations": concept_values})
    proposed_name = name_values[0] if name_values else ""
    proposed_concept = concept_values[0] if concept_values else ""
    concept_authority = delegated_fields.get("concept") or {}
    if name_authority.get("state") == "owner_locked":
        owner_name = str(name_authority.get("owner_value") or "").strip()
        if proposed_name != owner_name:
            _raise("CG1_OWNER_LOCKED_DESCRIPTIVE_FIELD_CHANGED", "The response changed the owner-locked character name.", details={"field": "identity.name", "expected": owner_name, "actual": proposed_name})
        proposed_name = owner_name
    if concept_authority.get("state") == "owner_locked":
        owner_concept = str(concept_authority.get("owner_value") or "").strip()
        if proposed_concept != owner_concept:
            _raise("CG1_OWNER_LOCKED_DESCRIPTIVE_FIELD_CHANGED", "The response changed the owner-locked character concept.", details={"field": "concept", "expected": owner_concept, "actual": proposed_concept})
        proposed_concept = owner_concept
    descriptive["identity"] = identity
    descriptive["identity"]["name"] = proposed_name or None
    descriptive["concept"] = proposed_concept or None
    provenance: list[dict[str, Any]] = []

    def add_provenance(row: dict[str, Any]) -> None:
        if not any(
            existing.get("slot_id") == row.get("slot_id")
            and existing.get("choice_id") == row.get("choice_id")
            and existing.get("status") == row.get("status")
            for existing in provenance
        ):
            provenance.append(row)

    for slot_id, choice_ids in selected_by_slot.items():
        owner_set = set(owner_by_slot.get(slot_id) or [])
        for choice_id in choice_ids:
            add_provenance({
                "slot_id": slot_id,
                "choice_id": choice_id,
                "provenance": "owner" if choice_id in owner_set else "AI",
                "status": "accepted",
                "sources": deepcopy(selection_sources.get(slot_id) or []),
            })
    for path_id in grants:
        if path_id not in selected_paths:
            add_provenance({"slot_id": _PATH_SLOT, "choice_id": path_id, "provenance": "automatic", "status": "accepted", "reason": "method_explicit_ap_grant_extra_path"})
    for slot_id, choice_ids in (envelope.get("unavailable_or_rejected_choice_ids_by_slot") or {}).items():
        for choice_id in choice_ids or []:
            add_provenance({"slot_id": slot_id, "choice_id": choice_id, "provenance": "unavailable", "status": "rejected", "reason": "frozen_unavailable_or_rejected"})
    for slot_id in envelope.get("unresolved_owner_decisions") or []:
        if not selected_by_slot.get(slot_id):
            add_provenance({"slot_id": slot_id, "choice_id": None, "provenance": "needs_owner", "status": "unresolved"})
    if not method_id:
        add_provenance({"slot_id": _METHOD_SLOT, "choice_id": None, "provenance": "needs_owner", "status": "deferred_or_typed_none"})
    if not proposed_name and name_authority.get("state") != "owner_locked":
        provenance.append({"slot_id": "identity.name", "choice_id": None, "provenance": "needs_owner", "status": "unresolved"})
    if not proposed_concept and concept_authority.get("state") != "owner_locked":
        provenance.append({"slot_id": "concept", "choice_id": None, "provenance": "needs_owner", "status": "unresolved"})

    resolution = {
        "schema": "TianxiaFoundry.DelegatedChoiceResolution.v1",
        "selected_path_ids": selected_paths,
        "owner_required_or_proposed_path_ids": list(selected_paths),
        "selected_choices_by_slot": deepcopy(selected_by_slot),
        "selection_sources_by_slot": deepcopy(selection_sources),
        "method_id": method_id,
        "method_granted_path_ids": list(grants),
        "actual_advancing_path_ids": grants,
        "extra_method_granted_path_ids": [path_id for path_id in grants if path_id not in selected_paths],
        "foundation_id": foundation_id,
        "deferred_method": deferred_method,
        "method_semantics": {
            "status": "deferred_or_typed_none" if deferred_method else "selected",
            "owner_required_or_proposed_path_ids": list(selected_paths),
            "actual_method_granted_path_ids": list(grants),
        },
        "descriptive_fields": {"name": proposed_name or None, "concept": proposed_concept or None},
        "level_zero_semantics": {
            "all_three_tracks_present": True,
            "attainment": {path_id: 0 for path_id in CANONICAL_PATH_IDS},
            "active_features": False,
            "resource_progression": False,
        },
        "provenance": provenance,
        "planner_prose_authority": False,
    }
    final_plan = {
        "schema": FINAL_PLAN_SCHEMA,
        "project_id": project.get("project_id"),
        "project_revision": project.get("revision"),
        "content_lock_hash": (project.get("content_lock") or {}).get("lock_hash"),
        "catalog_build_id": (project.get("content_lock") or {}).get("catalog_build_id"),
        "target_cl": target_cl,
        "target_cl_authority": {
            **deepcopy(envelope.get("frozen_owner_target_cl") or {}),
            "envelope_sha256": envelope.get("envelope_sha256"),
        },
        "request_sha256": run.get("request", {}).get("request_sha256"),
        "response_sha256": response_sha256 or run.get("response", {}).get("response_sha256"),
        "idempotency_key": run.get("idempotency_key"),
        "plan_sha256": _stable_hash(plan),
        "resolution": resolution,
        "owner_locks": deepcopy(envelope.get("owner_locks")),
        "envelope_sha256": envelope.get("envelope_sha256"),
        "selection_sources": {
            "delegated_choice_selections": deepcopy(plan.get("delegated_choice_selections") or {}),
            "catalog_priority_order": deepcopy(_priority_order(plan)),
            "resolved_by_slot": deepcopy(selection_sources),
        },
        "response_representations": response_authority_representations(plan),
        "descriptive_fields": descriptive,
        "automatic_grants": {"path_ids": resolution["extra_method_granted_path_ids"]},
        "unresolved": [row for row in provenance if row.get("status") == "unresolved"],
        "authority_hash": _stable_hash(resolution),
        "immutable_after_validation": True,
    }
    final_plan["final_plan_sha256"] = _stable_hash({key: value for key, value in final_plan.items() if key != "final_plan_sha256"})
    return final_plan


def final_plan_sha256(final_plan: dict[str, Any]) -> str:
    return _stable_hash({key: value for key, value in final_plan.items() if key != "final_plan_sha256"})


def canonical_final_plan_bytes(final_plan: dict[str, Any]) -> bytes:
    return canonical_json(final_plan).encode("utf-8")
