"""Revision-bound delegated-choice authority for complete character creation.

This module is intentionally independent of transport and compilation.  It
turns the production Stage 1 envelope into a sealed request envelope before an
AI response exists, then validates a response against that exact envelope.
Planner prose never participates in the legality decision.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from app.core import FoundryError, canonical_json, sha256_json
from character_creation.constructed_arts.explicit_forging import explicit_forging_contract, has_explicit_forging_contract
from catalog_choice_authority import DELEGATED_FINAL_CATALOG_GRANT_FIELD
from character_creation.compiler_selection_authority import (
    COMPILER_SELECTION_AUTHORITY_SCHEMA,
    CompilerSelectionAuthoritySnapshot,
    NOT_COMPILER_BACKED_CODE,
    verify_compiler_selection_authority,
    normalize_canonical_option_name,
)
from paged_selection_contract import PAGED_SELECTION_SLOTS_KEY, paged_slot_contract
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
from canonical_catalog.service import REALM_ENTRY_CL
from stage1.service import FIRST_PATH_SUBPATH_SELECTION_CL
from creation_training_authority import (
    CREATION_TRAINING_CONTRACT_SCHEMA,
    CREATION_TRAINING_MAX_PER_CL,
    CREATION_TRAINING_CHOICE_TYPES,
    SealedBackgroundSphereResolutionError,
    canonical_background_package_ids,
    canonical_selected_background_sphere_ids,
    creation_context_ids,
    constructed_outcome,
    constructed_source,
    creation_route_legality_errors,
    creation_route_temporal_legality_errors,
    validate_trained_choice_shape,
    validate_creation_training_contract,
)


ENVELOPE_SCHEMA = "TianxiaFoundry.DelegatedChoiceAuthorityEnvelope.v1"
FINAL_PLAN_SCHEMA = "TianxiaFoundry.CharacterCreationFinalPlan.v1"
FROZEN_TARGET_CL_AUTHORITY_SCHEMA = "TianxiaFoundry.FrozenOwnerTargetCLAuthority.v1"
TARGET_CL_MISMATCH_ERROR = "CG1_DELEGATED_TARGET_CL_MISMATCH"
FINAL_PLAN_TARGET_CL_STALE_ERROR = "CG1_FINAL_PLAN_TARGET_CL_AUTHORITY_STALE"
DELEGATED_NAME_REQUIRED_ERROR = "CG1_DELEGATED_NAME_REQUIRED"
DELEGATED_NAME_REQUIREMENT_SCHEMA = "TianxiaFoundry.DelegatedNameRequirement.v1"
DELEGATED_TITLE_REQUIRED_ERROR = "CG1_DELEGATED_TITLE_REQUIRED"
DELEGATED_TITLE_REQUIREMENT_SCHEMA = "TianxiaFoundry.DelegatedTitleRequirement.v1"

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
# These buckets count acquisition occurrences. Activation, expression and
# stage changes are lifecycle operations; the causal engine validates their
# ownership and order without granting another initial selection.
_METHOD_KINDS = {"method_acquisition"}
_FOUNDATION_KINDS = {"foundation_acquisition"}
_CANONICAL_KINDS = {
    "cultivation_insight_acquisition",
    "sect_trial_sphere_acquisition",
    "sect_trial_talent_acquisition",
    "ai_bootstrap_sphere_acquisition",
    "ai_bootstrap_talent_acquisition",
    "level_talent_acquisition",
    "new_sphere_bonus_talent_acquisition",
}



# The controller-built starting kit is a constructed item record, not a pick
# from the delegated item menu; it must not be checked against item slots.
_STARTING_KIT_RECORD_PREFIX = "tianxia.constructed.starting_kit."



def _owner_wins(owner_value: str, proposed: Any) -> str:
    """Owner rule 2026-10-10: owner-written name/concept/title always win; the AI may only ADD to them.
    Whitespace-only differences keep the owner's exact text; a proposal that contains the owner's whole
    wording plus additions is kept (an addition); anything else is replaced by the owner's text. Never blocks."""
    if not isinstance(proposed, str) or not proposed.strip():
        return owner_value
    own, prop = " ".join(owner_value.split()), " ".join(proposed.split())
    if prop == own:
        return owner_value
    # An addition must contain the owner's wording as WHOLE words ("Kai" -> "Kai the Rotbloom" ok,
    # "Kai" -> "Kaiden" is a replacement), case-sensitive.
    import re as _re
    if not _re.search(r"(?<!\w)" + _re.escape(own) + r"(?!\w)", prop):
        return owner_value
    return proposed.strip()


def _same_owner_wording(owner_value: Any, proposed: Any) -> bool:
    """Owner-locked text matches when only whitespace differs (browsers and models collapse
    double spaces / line breaks). The owner's exact text is still what gets kept."""
    if not isinstance(owner_value, str) or not isinstance(proposed, str):
        return False
    return " ".join(owner_value.split()) == " ".join(proposed.split())

def _is_constructed_starting_kit_row(row: Mapping[str, Any]) -> bool:
    return str(row.get("record_id") or "").startswith(_STARTING_KIT_RECORD_PREFIX)

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

# These delegated acquisition slots identify independent records.  Their
# transport/materialization order is not semantic; planning/preference slots
# above remain ordered and continue to require exact sequence agreement.
_SET_SHAPED_SELECTION_SLOTS = frozenset({_PATH_SLOT, "subpath_choice"})

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


def _constructed_method_access_route(method_access: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The learning route the Factory constructs for a restricted Method.

    Only a Method whose typed access is not open and that publishes at least
    one non-custom route qualifies.  The first advertised route is used, in
    the registry's own order, so the choice is deterministic and source-bound
    (each option carries its ``source_route_sha256``).
    """

    if not isinstance(method_access, Mapping) or method_access.get("initial_creation_selectable") is not False:
        return None
    for option in method_access.get("owner_route_options") or []:
        if not isinstance(option, Mapping) or option.get("requires_explanation"):
            continue
        if isinstance(option.get("choice_id"), str) and isinstance(option.get("typed_route"), str):
            return {
                "choice_id": option["choice_id"],
                "typed_route": option["typed_route"],
                "label": option.get("label"),
                "source_route_sha256": option.get("source_route_sha256"),
                "origin": "factory_constructed",
            }
    return None


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


def _delegated_title_contract_is_complete(
    title_authority: Any,
    title_contract: Any,
) -> bool:
    """Require both halves of the active title contract before validation.

    Historical envelopes may omit the title contract entirely.  Once the
    compiler-backed envelope carries this field, however, either half being
    absent or partial would turn a required descriptive field into an
    optional one.  Keep the structural check server-owned and separate from
    the later persisted-lock/value comparison.
    """
    if not isinstance(title_authority, dict) or not isinstance(title_contract, dict):
        return False
    authority_required = {
        "state",
        "owner_value",
        "response_field",
        "required_in_response",
        "nonblank_required",
        "max_length",
        "requirement_schema",
    }
    contract_required = {
        "schema",
        "field",
        "state",
        "required",
        "nonblank",
        "max_length",
        "owner_locked_value",
    }
    if not authority_required.issubset(title_authority) or not contract_required.issubset(title_contract):
        return False
    return (
        title_authority.get("state") in {"delegated", "owner_locked"}
        and title_authority.get("response_field") == "owner_descriptive_fields.identity.title"
        and title_authority.get("required_in_response") is True
        and title_authority.get("nonblank_required") is True
        and type(title_authority.get("max_length")) is int
        and title_authority.get("max_length") == 120
        and title_authority.get("requirement_schema") == DELEGATED_TITLE_REQUIREMENT_SCHEMA
        and title_contract.get("schema") == DELEGATED_TITLE_REQUIREMENT_SCHEMA
        and title_contract.get("field") == "owner_descriptive_fields.identity.title"
        and title_contract.get("state") in {"delegated", "owner_locked"}
        and title_contract.get("required") is True
        and title_contract.get("nonblank") is True
        and type(title_contract.get("max_length")) is int
        and title_contract.get("max_length") == 120
    )


def build_delegated_choice_envelope(
    project: dict[str, Any],
    prompt: dict[str, Any],
    *,
    execution_mode: str,
    idempotency_key: str,
    compiler_selection_authority: dict[str, Any] | None = None,
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
    production_prompt = bool(
        prompt_envelope.get("schema_version")
        or prompt_envelope.get("response_schema_version")
        or (prompt_envelope.get("path_method_authority") or {}).get("method_access_by_id")
    )
    if production_prompt and not isinstance(compiler_selection_authority, CompilerSelectionAuthoritySnapshot):
        raise FoundryError(
            "CG1_DELEGATED_COMPILER_AUTHORITY_MISSING",
            "A real Stage 1 delegated request must carry a server-built compiler-selection authority snapshot.",
            details={"schema": COMPILER_SELECTION_AUTHORITY_SCHEMA},
            status_code=503,
        )
    compiler_gate_active = isinstance(compiler_selection_authority, CompilerSelectionAuthoritySnapshot)
    if compiler_gate_active:
        project_content = project.get("content_lock") or {}
        compiler_selection_authority = verify_compiler_selection_authority(
            compiler_selection_authority,
            expected_content_lock=project_content,
        )
        authority_content = compiler_selection_authority.get("content") or {}
        if authority_content.get("content_lock_hash") != project_content.get("lock_hash"):
            raise FoundryError(
                "CG1_DELEGATED_COMPILER_AUTHORITY_STALE",
                "The compiler-selection authority is bound to a different project content lock.",
                details={
                    "authority_content_lock_hash": authority_content.get("content_lock_hash"),
                    "project_content_lock_hash": project_content.get("lock_hash"),
                },
                status_code=409,
            )
    locks = _locks(project)
    method_planning_lock = _method_planning_lock(locks)
    by_slot: dict[str, list[str]] = {}
    offered: dict[str, list[str]] = {}
    allowed: dict[str, list[str]] = {}
    unavailable: dict[str, list[str]] = {}
    limits: dict[str, dict[str, Any]] = {}
    choices: dict[str, dict[str, Any]] = {}
    paged_slots: dict[str, dict[str, Any]] = {}
    method_access_by_id = (
        (prompt_envelope.get("path_method_authority") or {}).get("method_access_by_id") or {}
    )
    for slot_id, slot in sorted(slots.items()):
        rows = _choice_map(slot)
        ids = list(rows)
        offered[slot_id] = ids
        choices[slot_id] = rows
        # A slot that publishes a chain of option windows needs more than the
        # ordinary three menu pages, or the controller fails the run when it
        # asks for the next window. The contract is frozen with the request.
        paged_contract = paged_slot_contract(slot)
        if paged_contract is not None:
            paged_slots[slot_id] = paged_contract
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
            constructed_route = (
                _constructed_method_access_route(method_access)
                if slot_id == _METHOD_SLOT and isinstance(method_access, dict) and not owner_access
                else None
            )
            if constructed_route is not None:
                # Owner ruling 2026-09-06: a learning route is a field the
                # Factory fills, not a blocker.  When the owner authored no
                # route plan, the first published non-custom route becomes the
                # constructed access the compile step commits as evidence.
                method_access["constructed_access_route"] = deepcopy(constructed_route)
            access_required_without_proof = (
                isinstance(method_access, dict)
                and method_access.get("initial_creation_selectable") is False
                and not owner_access
                and constructed_route is None
            )
            compiler_evidence = None
            if compiler_gate_active and slot_id in {_METHOD_SLOT, _FOUNDATION_SLOT}:
                authority_section = compiler_selection_authority.get(slot_id) or {}
                authority_records = authority_section.get("records") or {}
                compiler_evidence = authority_records.get(choice_id)
                if not isinstance(compiler_evidence, dict):
                    raise FoundryError(
                        "CG1_DELEGATED_COMPILER_AUTHORITY_MISMATCH",
                        "A Method/Foundation choice is absent from the server-built compiler authority index.",
                        details={"slot_id": slot_id, "choice_id": choice_id},
                        status_code=503,
                    )
                row_name = normalize_canonical_option_name(str(row.get("name") or row.get("display_name") or choice_id))
                evidence_name = normalize_canonical_option_name(str(compiler_evidence.get("canonical_name") or ""))
                if row_name != evidence_name or compiler_evidence.get("choice_id") != choice_id:
                    raise FoundryError(
                        "CG1_DELEGATED_COMPILER_AUTHORITY_MISMATCH",
                        "A Method/Foundation choice name or ID diverges from the server-built compiler authority index.",
                        details={"slot_id": slot_id, "choice_id": choice_id, "choice_name": row_name, "authority_name": evidence_name},
                        status_code=503,
                    )
                row["compiler_selection_evidence"] = deepcopy(compiler_evidence)
            compiler_backed = compiler_evidence is None or compiler_evidence.get("selectable") is True
            if selectable is False or availability.get("available") is False or access_required_without_proof or not compiler_backed:
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

    # An owner-locked Foundation must pass the same gate as a delegated choice
    # before a guided walk starts. Otherwise the walk can finish every model
    # step only to fail when final validation reads this frozen envelope.
    if compiler_gate_active:
        for foundation_id in by_slot.get(_FOUNDATION_SLOT) or []:
            if foundation_id not in allowed.get(_FOUNDATION_SLOT, []):
                raise FoundryError(
                    "CG1_FOUNDATION_EXACT_PLAN_UNAVAILABLE",
                    "The owner's selected Foundation cannot be compiled by this request's source authority.",
                    details={"foundation_id": foundation_id,
                             "allowed_foundation_ids": list(allowed.get(_FOUNDATION_SLOT) or []),
                             "resolution": "Update the Foundation source authority before starting the guided build; retained selections are unchanged."},
                    status_code=422,
                )

    # An EXACT owner Method plan that this sealed request cannot deliver is a
    # dead end if it reaches review: the Method decision would be unresolved
    # with no legal choice and no recovery action.  Fail closed here, before
    # any provider call, naming the exact reasons and the legal alternatives.
    if method_planning_lock and compiler_gate_active:
        exact_method_id = (method_planning_lock.get("choice_ids") or [None])[0]
        if isinstance(exact_method_id, str) and exact_method_id not in (allowed.get(_METHOD_SLOT) or []):
            method_row = (choices.get(_METHOD_SLOT) or {}).get(exact_method_id) or {}
            evidence = method_row.get("compiler_selection_evidence") if isinstance(method_row, dict) else None
            method_access = method_access_by_id.get(exact_method_id) if isinstance(method_access_by_id, dict) else None
            reasons: list[str] = []
            if not method_row:
                reasons.append("not_offered_for_selected_paths")
            if isinstance(evidence, dict) and evidence.get("selectable") is not True:
                reasons.append("not_in_pinned_compiler_corpus")
            if isinstance(method_access, dict) and method_access.get("initial_creation_selectable") is False:
                reasons.append("access_evidence_required")
            raise FoundryError(
                "CG1_METHOD_EXACT_PLAN_UNAVAILABLE",
                "The owner's exact Method plan cannot be selected in this request; choose an offered Method or set Method planning to AUTO (defer the Method, which is legal at creation).",
                details={
                    "method_id": exact_method_id,
                    "method_name": method_row.get("name") if isinstance(method_row, dict) else None,
                    "reasons": reasons or ["not_selectable"],
                    "allowed_method_ids": list(allowed.get(_METHOD_SLOT) or []),
                    "offered_method_ids": list(offered.get(_METHOD_SLOT) or []),
                    "planning_mode": method_planning_lock.get("mode"),
                    "resolution": "Change the wizard's Method planning to AUTO, or pick one of allowed_method_ids; making this Method selectable needs the pinned compiler corpus to include it and the access evidence the route requires.",
                },
                status_code=422,
            )

    content_lock = project.get("content_lock") or {}
    frozen_target_cl = frozen_owner_target_cl(project)
    # Rulebook line 11: Path 0 to 1 is a legal Method initiation, so a
    # character with any attainment needs a Method.  A request that can offer
    # none for the locked Paths cannot finish; say so before any model runs.
    if (
        type(frozen_target_cl) is int
        and frozen_target_cl >= 1
        and by_slot.get(_PATH_SLOT)
        and _METHOD_SLOT in slots
        and not allowed.get(_METHOD_SLOT)
    ):
        reasons: dict[str, list[str]] = {}
        for method_id in (prompt_envelope.get("path_method_authority") or {}).get("compatible_method_ids") or []:
            row = (choices.get(_METHOD_SLOT) or {}).get(method_id) or {}
            evidence = row.get("compiler_selection_evidence") if isinstance(row, dict) else None
            access = method_access_by_id.get(method_id) if isinstance(method_access_by_id, dict) else None
            why: list[str] = []
            if isinstance(evidence, dict) and evidence.get("selectable") is not True:
                why.append("not_in_pinned_compiler_corpus")
            if isinstance(access, dict) and access.get("initial_creation_selectable") is False and _constructed_method_access_route(access) is None:
                why.append("no_published_learning_route")
            reasons[method_id] = why or ["not_selectable"]
        raise FoundryError(
            "CG1_METHOD_REQUIRED_NONE_SELECTABLE",
            "A character with attainment needs a Method, and no Method that covers the locked Paths can be selected in this request.",
            details={
                "target_cl": frozen_target_cl,
                "locked_path_ids": list(by_slot.get(_PATH_SLOT) or []),
                "compatible_method_ids": list((prompt_envelope.get("path_method_authority") or {}).get("compatible_method_ids") or []),
                "reasons_by_method_id": reasons,
                "resolution": "Choose Paths covered by a compiler-backed Method with a published learning route, or release the newer Methods into the pinned compiler corpus (R8).",
            },
            status_code=422,
        )
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
    title_lock_present = "character.identity.title" in locks
    owner_title_raw = locks.get("character.identity.title")
    if compiler_gate_active and title_lock_present and (
        not isinstance(owner_title_raw, str)
        or not owner_title_raw.strip()
        or len(owner_title_raw.strip()) > 120
    ):
        raise FoundryError(
            "CG1_DELEGATED_TITLE_AUTHORITY_INVALID",
            "An active delegated request cannot carry an empty, non-string, or overlong owner title lock.",
            details={"field": "character.identity.title", "max_length": 120},
            status_code=409,
        )
    owner_title = owner_title_raw.strip() if isinstance(owner_title_raw, str) and owner_title_raw.strip() else None
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
    if compiler_gate_active:
        delegated_fields["identity.title"] = {
            "state": "owner_locked" if owner_title else "delegated",
            "owner_value": owner_title,
            "response_field": "owner_descriptive_fields.identity.title",
            "required_in_response": True,
            "nonblank_required": True,
            "max_length": 120,
            "positive_delegation": not bool(owner_title),
            "requirement_schema": DELEGATED_TITLE_REQUIREMENT_SCHEMA,
            "semantic_requirement": (
                "The response must propose one concise nonblank character title for owner review."
                if not owner_title
                else "The response must repeat the exact owner-locked character title unchanged."
            ),
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
    if compiler_gate_active:
        binding["target_cl"] = frozen_target_cl
        binding["compiler_selection_authority_sha256"] = compiler_selection_authority.get("authority_sha256")
        binding["one_shot_binding_sha256"] = _stable_hash({
            "project_id": binding.get("project_id"),
            "project_revision": binding.get("project_revision"),
            "target_cl": binding.get("target_cl"),
            "content_lock_hash": binding.get("content_lock_hash"),
            "stage1_prompt_id": binding.get("stage1_prompt_id"),
            "stage1_prompt_sha256": binding.get("stage1_prompt_sha256"),
            "execution_mode": execution_mode,
            "idempotency_key": idempotency_key,
            "compiler_selection_authority_sha256": binding.get("compiler_selection_authority_sha256"),
        })
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
            # Server-derived locks (for example the final catalog grant plan)
            # are persisted alongside owner locks but are intentionally not
            # part of this delegated request's owner-choice binding.  Keep
            # the builder projection identical to the validator's projection.
            "lock_sha256": _stable_hash(_owner_user_locks(project)),
            "zero_owner_path_locks_are_legal": not bool(by_slot.get(_PATH_SLOT)),
            "planning_by_slot": {
                _METHOD_SLOT: method_planning_lock,
            } if method_planning_lock else {},
            "planning_lock_sha256": _stable_hash(method_planning_lock) if method_planning_lock else None,
        },
        "offered_choice_ids_by_slot": offered,
        "allowed_choice_ids_by_slot": allowed,
        PAGED_SELECTION_SLOTS_KEY: paged_slots,
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
        "explicit_forging_contract": explicit_forging_contract(),
        "ordinary_talent_count": complete_source_authority.get("ordinary_talent_count"),
        "advancement_choice_milestones": deepcopy(complete_source_authority.get("advancement_choice_milestones") or []),
        "path_progression_choices": deepcopy(complete_source_authority.get("path_progression_choices") or []),
        "creation_training_contract": deepcopy(
            complete_source_authority.get("creation_training_contract")
        ) if isinstance(complete_source_authority.get("creation_training_contract"), dict) else None,
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
            "method_foundation_selection_authority": "closed_world_pinned_compiler_corpus",
            "method_foundation_unbacked_reason_code": NOT_COMPILER_BACKED_CODE,
            "no_final_no_path": True,
            "level_zero_tracks": "all_three_present_dormant",
            "unspecified_choices_are_not_prefrozen": True,
        },
    }
    if compiler_gate_active:
        payload["delegated_title_contract"] = {
            "schema": DELEGATED_TITLE_REQUIREMENT_SCHEMA,
            "field": "owner_descriptive_fields.identity.title",
            "state": delegated_fields["identity.title"]["state"],
            "required": True,
            "nonblank": True,
            "max_length": 120,
            "positive_delegation": delegated_fields["identity.title"]["positive_delegation"],
            "owner_locked_value": owner_title,
            "instruction": delegated_fields["identity.title"]["semantic_requirement"],
        }
    if compiler_gate_active:
        payload["compiler_selection_authority"] = compiler_selection_authority
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
        if not isinstance(row, dict) or _is_constructed_starting_kit_row(row):
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
        "creation_training_sphere_acquisition": "sphere_ids",
        **{kind: "free_sphere_talent_ids" for kind in _CATALOG_FREE_TALENT_KINDS},
        **{kind: "ordinary_talent_ids" for kind in _CATALOG_ORDINARY_TALENT_KINDS},
        "cultivation_insight_acquisition": "insight_ids",
        "insight_acquisition": "insight_ids",
        "item_acquisition": "item_ids",
        "equipment_acquisition": "item_ids",
    }
    for row in (plan.get("stage2_proposal") or {}).get("choices") or []:
        if not isinstance(row, dict) or _is_constructed_starting_kit_row(row):
            continue
        canonical_kind = _canonical_stage2_kind(row.get("kind"))
        bucket = buckets.get(canonical_kind)
        record_id = row.get("record_id")
        if bucket and isinstance(record_id, str) and record_id:
            result[bucket].append(record_id)
        if canonical_kind == "creation_training_talent_acquisition" and isinstance(record_id, str) and record_id:
            parameters = row.get("parameters") if isinstance(row.get("parameters"), dict) else {}
            result.setdefault("trained_talent_ids", []).append(record_id)
            result.setdefault("trained_talent_acquisitions", []).append(
                {
                    "talent_id": record_id,
                    "effective_cl": row.get("effective_cl"),
                    "slot": parameters.get("slot"),
                    "choice_type": parameters.get("choice_type"),
                    "acquisition_channel": row.get("acquisition_channel"),
                    "source": deepcopy(parameters.get("source")),
                    "outcome": deepcopy(parameters.get("outcome")),
                }
            )
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
            **{kind: _METHOD_SLOT for kind in _METHOD_KINDS},
            **{kind: _FOUNDATION_SLOT for kind in _FOUNDATION_KINDS},
            "background_acquisition": "background_choice",
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
            if not isinstance(row, dict) or not isinstance(row.get("record_id"), str) or _is_constructed_starting_kit_row(row):
                continue
            kind = _canonical_stage2_kind(row.get("kind"))
            slot_id = stage2_slot_kinds.get(kind)
            if slot_id:
                stage2_values.setdefault(slot_id, []).append(row["record_id"])
        for slot_id, values in stage2_values.items():
            values = _values(values)
            existing = resolved.get(slot_id) or []
            if existing and existing != values:
                # Priority slots describe the owner's planning order; they do
                # not promise that every preferred record will be acquired.
                # Stage 2 is the authoritative acquisition projection for
                # those slots, so a shorter/different materialized list is
                # expected and must not be reported as a delegated conflict.
                if slot_id in _PLANNING_SLOT_IDS:
                    continue
                # Path-owned Subpaths (and the advancing Path set itself) are
                # set-shaped acquisitions.  Preserve exact multiplicity and
                # membership checks below, but do not reject a materializer
                # that emits the same records in a different order.
                if (
                    slot_id in _SET_SHAPED_SELECTION_SLOTS
                    and len(existing) == len(values)
                    and len(existing) == len(set(existing))
                    and len(values) == len(set(values))
                    and set(existing) == set(values)
                ):
                    continue
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
    compiler_section = (envelope.get("compiler_selection_authority") or {}).get(slot_id) if slot_id in {_METHOD_SLOT, _FOUNDATION_SLOT} else None
    compiler_records = compiler_section.get("records") if isinstance(compiler_section, dict) else {}
    for choice_id in values:
        compiler_row = compiler_records.get(choice_id) if isinstance(compiler_records, dict) else None
        if isinstance(compiler_row, dict) and compiler_row.get("selectable") is not True:
            _raise(
                NOT_COMPILER_BACKED_CODE,
                "The selected Method/Foundation is not proven by the pinned compiler corpus.",
                details={
                    "slot_id": slot_id,
                    "choice_id": choice_id,
                    "reason_code": compiler_row.get("reason_code") or NOT_COMPILER_BACKED_CODE,
                },
            )
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
    # Catalog either-or relations (schema: one target_id) list every
    # alternative in ``value``.
    if not targets and relation.get("operator") in {"one_of", "all_of"} and isinstance(relation.get("value"), list):
        targets = relation["value"]
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
    ignored_slot_ids: set[str] | None = None,
    only_slot_ids: set[str] | None = None,
) -> None:
    """Re-evaluate the frozen typed legality relations against the final IDs."""

    present = {
        choice_id
        for slot_id, choice_ids in selected_by_slot.items()
        if slot_id not in (ignored_slot_ids or set())
        for choice_id in choice_ids
    }
    present.update(automatic_ids or set())
    target_cl = plan.get("target_cl")
    for slot_id, choice_ids in selected_by_slot.items():
        if slot_id in (ignored_slot_ids or set()):
            continue
        if only_slot_ids is not None and slot_id not in only_slot_ids:
            continue
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


def legal_slot_replacement_ids(
    envelope: dict[str, Any],
    plan: dict[str, Any],
    selected_by_slot: dict[str, list[str]],
    slot_id: str,
    *,
    target_value: str | None = None,
) -> list[str]:
    """Return frozen choices that pass the real slot legality validator.

    Owner review must not turn ``allowed_choice_ids_by_slot`` into a second,
    weaker legality contract.  For a one-value replacement the current target
    is removed and each offered candidate is checked against the same typed
    prerequisite/incompatibility validator used by delegated response
    validation.  Multi-value slots must provide an explicit target so the
    replacement cannot discard unrelated owner or AI priorities.
    """
    if not isinstance(slot_id, str) or not slot_id:
        return []
    authority = envelope.get("compiler_selection_authority")
    if not isinstance(authority, dict):
        return []
    try:
        verify_compiler_selection_authority(authority)
    except FoundryError:
        return []
    authority_content = authority.get("content") if isinstance(authority.get("content"), dict) else {}
    binding = envelope.get("binding") if isinstance(envelope.get("binding"), dict) else {}
    if (
        authority_content.get("content_lock_hash") != binding.get("content_lock_hash")
        or authority.get("authority_sha256") != binding.get("compiler_selection_authority_sha256")
    ):
        # Replacement enumeration is also a request-boundary consumer.  It
        # cannot accept an authority snapshot merely because its own static
        # pins verify; the frozen envelope must bind that snapshot to its
        # content-lock context before it can disclose candidates.
        return []
    current = {
        key: list(values)
        for key, values in (selected_by_slot or {}).items()
        if isinstance(key, str) and isinstance(values, list)
    }
    existing = list(current.get(slot_id) or [])
    target = target_value
    if target is None and len(existing) == 1:
        target = existing[0]
    if target is not None and target not in existing:
        return []
    if len(existing) > 1 and target is None:
        return []
    allowed = (envelope.get("allowed_choice_ids_by_slot") or {}).get(slot_id, [])
    if not isinstance(allowed, list):
        return []
    result: list[str] = []
    for candidate in allowed:
        if not isinstance(candidate, str) or not candidate:
            continue
        if target is None:
            trial_values = [candidate]
        else:
            trial_values = [candidate if value == target else value for value in existing]
        trial = deepcopy(current)
        trial[slot_id] = trial_values
        try:
            _validate_frozen_legality(
                envelope,
                trial,
                plan,
                only_slot_ids={slot_id},
            )
        except FoundryError:
            continue
        result.append(candidate)
    return result


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

    # R4 direct-construction training is a separate semantic lane.  Its rows
    # are validated against the sealed source route before the ordinary
    # planning legality pass; planning priorities cannot act as source proof.
    creation_contract = envelope.get("creation_training_contract")
    trained = acquisition.get("trained_choices")
    trained_ids: list[str] = []
    trained_spheres: list[str] = []
    bonus_ids: set[str] = set()
    # The planning pass below counts these as held even when the frozen
    # envelope carries no creation-training contract, so they must exist in
    # both branches; an envelope without the contract used to crash here.
    canonical_background_ids: dict[str, str] = {}
    package_talents: set[str] = set()
    if creation_contract is not None:
        contract_errors = validate_creation_training_contract(creation_contract)
        if contract_errors:
            _raise(
                "CG1_CREATION_TRAINING_CONTRACT_INVALID",
                "The sealed creation-training contract is malformed.",
                details={"schema": CREATION_TRAINING_CONTRACT_SCHEMA, "fields": contract_errors},
            )
        if not isinstance(trained, list):
            _raise(
                "CG1_CREATION_TRAINING_CHOICES_REQUIRED",
                "A sealed creation-training contract requires a trained_choices array.",
            )
        target_cl = creation_contract.get("target_cl")
        routes = creation_contract.get("records") or {}
        by_cl: dict[int, list[dict[str, Any]]] = {}
        known_spheres = set(pair_spheres)
        known_talents = set(pair_talents)
        used_ids = set(pair_spheres) | set(pair_talents) | set(ordinary)
        background_sphere_ids = [
            value
            for value in selected_by_slot.get("background_sphere_choice") or []
            if isinstance(value, str)
        ]
        try:
            canonical_background_ids = canonical_selected_background_sphere_ids(
                selected_by_slot,
                envelope.get("choices_by_slot"),
                envelope.get("typed_choice_authority_by_slot"),
            )
        except SealedBackgroundSphereResolutionError as exc:
            _raise(
                "CG1_TRAINED_CHOICE_BACKGROUND_SPHERE_INVALID",
                "The selected Background Sphere cannot be resolved to one canonical sealed Sphere.",
                details={
                    "background_sphere_id": exc.background_sphere_id,
                    "reason": exc.reason,
                    "display_name": exc.display_name,
                    "candidate_ids": exc.candidate_ids,
                },
            )
        known_spheres.update(canonical_background_ids.values())
        used_ids.update(background_sphere_ids)
        used_ids.update(canonical_background_ids.values())
        package_spheres, package_talents = canonical_background_package_ids(
            selected_by_slot,
            envelope.get("typed_choice_authority_by_slot"),
        )
        known_spheres.update(package_spheres)
        known_talents.update(package_talents)
        used_ids.update(package_spheres)
        used_ids.update(package_talents)
        for slot_id in ("background_sphere_choice", "background_talent_choice"):
            for value in selected_by_slot.get(slot_id) or []:
                if not isinstance(value, str):
                    continue
                if slot_id == "background_talent_choice":
                    used_ids.add(value)
                    known_talents.add(value)

        ordinary_by_cl = {index + 1: record_id for index, record_id in enumerate(ordinary)}
        validated_ordinary_cls: set[int] = set()

        def ordinary_route(record_id: str) -> dict[str, Any]:
            """Build one typed ordinary route from the sealed choice authority."""

            choice = choice_map.get(record_id) if isinstance(choice_map, dict) else None
            if not isinstance(choice, dict):
                choice = {}
            route = deepcopy(choice)
            authority = typed_authority_by_choice.get(record_id) if isinstance(typed_authority_by_choice, dict) else None
            if not isinstance(authority, dict):
                authority = choice.get("stage2_authority")
            if not isinstance(authority, dict):
                authority = (choice.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}
            if not isinstance(authority, dict):
                authority = {}
            for key in ("access_category", "minimum_cl", "allowed_cls", "realm_rules", "prerequisites", "incompatibilities", "owning_sphere_id", "owning_canonical_sphere_id"):
                if key not in route and authority.get(key) is not None:
                    route[key] = deepcopy(authority[key])
            if "minimum_cl" not in route:
                availability = route.get("availability")
                if isinstance(availability, dict) and availability.get("minimum_cl") is not None:
                    route["minimum_cl"] = availability["minimum_cl"]
            route.setdefault("record_id", record_id)
            route.setdefault("content_type", "talent")
            route.setdefault("choice_type", "known_sphere_talent")
            if "prerequisites" not in route and isinstance(route.get("legality"), dict):
                route["prerequisites"] = deepcopy(route["legality"].get("prerequisites") or [])
            if "incompatibilities" not in route and isinstance(route.get("legality"), dict):
                route["incompatibilities"] = deepcopy(route["legality"].get("incompatibilities") or [])
            return route

        def validate_ordinary_before(effective_cl: int) -> None:
            """Commit ordinary Talents from prior CLs into causal state only."""

            for ordinary_cl in range(1, min(effective_cl, len(ordinary) + 1)):
                if ordinary_cl in validated_ordinary_cls:
                    continue
                record_id = ordinary_by_cl[ordinary_cl]
                route = ordinary_route(record_id)
                route_errors = creation_route_temporal_legality_errors(
                    route,
                    cl=ordinary_cl,
                    present_ids=(
                        creation_context_ids(
                            selected_by_slot,
                            envelope.get("choices_by_slot"),
                            envelope.get("typed_choice_authority_by_slot"),
                            current_cl=ordinary_cl,
                        )
                        | set(known_spheres)
                        | set(known_talents)
                    ),
                    candidate_ids=(record_id,),
                )
                owning_sphere = route.get("owning_sphere_id") or route.get("owning_canonical_sphere_id")
                if isinstance(owning_sphere, str) and owning_sphere not in known_spheres:
                    route_errors = [*route_errors, "owning_sphere_id"]
                if route_errors:
                    _raise(
                        "CG1_ORDINARY_TALENT_ILLEGAL",
                        "An ordinary Talent is not legal in its prior causal state.",
                        details={
                            "ordinary_talent_index": ordinary_cl - 1,
                            "record_id": record_id,
                            "effective_cl": ordinary_cl,
                            "fields": sorted(set(route_errors)),
                        },
                    )
                known_talents.add(record_id)
                validated_ordinary_cls.add(ordinary_cl)

        indexed_rows = sorted(
            enumerate(trained),
            key=lambda item: (
                item[1].get("cl", 0) if isinstance(item[1], dict) else 0,
                item[1].get("slot", 0) if isinstance(item[1], dict) else 0,
                item[0],
            ),
        )
        if [index for index, _row in indexed_rows] != list(range(len(trained))):
            _raise(
                "CG1_TRAINED_CHOICE_ORDER_INVALID",
                "Constructed trained choices must be ordered by CL and slot.",
            )
        for index, row in indexed_rows:
            row_errors = validate_trained_choice_shape(row)
            if row_errors:
                _raise(
                    "CG1_PREFERRED_RESPONSE_TRAINED_CHOICE_INVALID",
                    "A trained choice does not match the constructed creation-training contract.",
                    details={"index": index, "fields": row_errors},
                )
            cl = row["cl"]
            validate_ordinary_before(cl)
            if type(target_cl) is int and (cl < 1 or cl > target_cl):
                _raise(
                    "CG1_TRAINED_CHOICE_CL_INVALID",
                    "A trained choice must occur within the frozen target CL.",
                    details={"index": index, "cl": cl, "target_cl": target_cl},
                )
            if len(by_cl.get(cl, [])) >= CREATION_TRAINING_MAX_PER_CL:
                _raise(
                    "CG1_TRAINED_CHOICE_CAPACITY_EXCEEDED",
                    "A CL cannot contain more than three constructed trained choices.",
                    details={"cl": cl, "maximum": CREATION_TRAINING_MAX_PER_CL},
                )
            rid = row["record_id"]
            route = routes.get(rid)
            if not isinstance(route, dict):
                _raise(
                    "CG1_TRAINED_CHOICE_OUT_OF_ENVELOPE",
                    "The trained record is absent from the sealed constructed source authority.",
                    details={"index": index, "record_id": rid},
                )
            choice_type = row["choice_type"]
            if route.get("choice_type") != choice_type:
                _raise(
                    "CG1_TRAINED_CHOICE_TYPE_MISMATCH",
                    "The trained choice type does not match its sealed catalog route.",
                    details={"record_id": rid, "expected": route.get("choice_type"), "actual": choice_type},
                )
            if row.get("source") != constructed_source(route, choice_type=choice_type):
                _raise(
                    "CG1_TRAINED_CHOICE_SOURCE_INVALID",
                    "The constructed training source proof does not match the sealed route.",
                    details={"index": index, "record_id": rid},
                )
            if row.get("outcome") != constructed_outcome():
                _raise(
                    "CG1_TRAINED_CHOICE_OUTCOME_INVALID",
                    "Constructed training must record a successful non-rolled outcome.",
                    details={"index": index, "record_id": rid},
                )
            if rid in trained_ids or rid in used_ids or rid in bonus_ids:
                _raise(
                    "CG1_DELEGATED_DUPLICATE_CHOICE",
                    "A constructed training record cannot repeat a prior acquisition.",
                    details={"record_id": rid},
                )
            expected_content_type = "sphere" if choice_type == "new_sphere" else "talent"
            if route.get("content_type") != expected_content_type:
                _raise(
                    "CG1_TRAINED_CHOICE_RECORD_TYPE_INVALID",
                    "A constructed training row is bound to the wrong catalog content type.",
                    details={"record_id": rid, "expected_content_type": expected_content_type},
                )
            present_ids = (
                creation_context_ids(
                    selected_by_slot,
                    envelope.get("choices_by_slot"),
                    envelope.get("typed_choice_authority_by_slot"),
                    current_cl=cl,
                )
                | set(known_spheres)
                | set(known_talents)
            )
            route_errors = creation_route_legality_errors(
                route,
                cl=cl,
                present_ids=present_ids,
                candidate_ids=(rid,),
            )
            if route_errors:
                _raise(
                    "CG1_TRAINED_CHOICE_ILLEGAL",
                    "A constructed training route is not legal in the prior causal state.",
                    details={"index": index, "record_id": rid, "fields": route_errors},
                )
            trained_ids.append(rid)
            if choice_type == "new_sphere":
                bonus_id = row.get("bonus_talent_id")
                bonus_route = routes.get(bonus_id)
                if not isinstance(bonus_id, str) or not isinstance(bonus_route, dict) or bonus_route.get("content_type") != "talent" or bonus_route.get("owning_sphere_id") != rid or bonus_route.get("choice_type") != "known_sphere_talent" or bonus_route.get("bonus_talent_eligible") is not True:
                    _raise(
                        "CG1_NEW_SPHERE_BONUS_INVALID",
                        "A newly trained Sphere must name one exact bonus Talent from that Sphere.",
                        details={"sphere_id": rid, "bonus_talent_id": bonus_id},
                    )
                if bonus_id in used_ids or bonus_id in bonus_ids:
                    _raise(
                        "CG1_NEW_SPHERE_BONUS_REUSED",
                        "A new-Sphere bonus Talent may be consumed only once.",
                        details={"bonus_talent_id": bonus_id},
                    )
                bonus_errors = creation_route_legality_errors(
                    bonus_route,
                    cl=cl,
                    present_ids=present_ids,
                    candidate_ids=(rid, bonus_id),
                    prior_choice_ids=(rid,),
                )
                if bonus_errors:
                    _raise(
                        "CG1_NEW_SPHERE_BONUS_ILLEGAL",
                        "A new-Sphere bonus Talent is not legal in the constructed causal state.",
                        details={"sphere_id": rid, "bonus_talent_id": bonus_id, "fields": bonus_errors},
                    )
                bonus_ids.add(bonus_id)
                used_ids.add(bonus_id)
                known_spheres.add(rid)
                known_talents.add(bonus_id)
                trained_spheres.append(rid)
            else:
                owning_sphere = route.get("owning_sphere_id")
                if not isinstance(owning_sphere, str) or owning_sphere not in known_spheres:
                    _raise(
                        "CG1_TRAINED_TALENT_SPHERE_NOT_KNOWN",
                        "A constructed Talent requires its owning Sphere to be known earlier in the causal order.",
                        details={"record_id": rid, "owning_sphere_id": owning_sphere, "known_spheres": sorted(known_spheres)},
                    )
                known_talents.add(rid)
            used_ids.add(rid)
            if row["slot"] != len(by_cl.get(cl, [])) + 1:
                _raise(
                    "CG1_TRAINED_CHOICE_SLOT_NOT_CONTIGUOUS",
                    "Constructed trained-choice slots must be contiguous within each CL.",
                    details={"cl": cl, "expected": len(by_cl.get(cl, [])) + 1, "actual": row["slot"]},
                )
            by_cl.setdefault(cl, []).append(row)
        for ordinary_cl in range(1, len(ordinary) + 1):
            if ordinary_cl not in validated_ordinary_cls:
                validate_ordinary_before(ordinary_cl + 1)
        if creation_contract.get("required_choices_per_cl") == 3:
            missing = {
                cl: 3 - len(by_cl.get(cl, []))
                for cl in range(1, (target_cl or 0) + 1)
                if len(by_cl.get(cl, [])) < 3
            }
            if missing:
                _raise(
                    "CG1_TRAINED_CHOICE_REQUIRED_COUNT_UNMET",
                    "The rival/boss creation contract requires three legal trained choices at every CL.",
                    details={"missing_by_cl": missing},
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

    # Planning priorities are not acquisition authority, but the frozen
    # priority choices themselves still have to satisfy their typed source
    # prerequisites.  Validate only those slots here so a priority cannot
    # satisfy a prerequisite for an actual acquisition below.  The free CL1
    # Sphere talents are real acquisitions (already proven allowed above) and
    # the books let them satisfy a later talent's prerequisite (Bone Ward
    # before Bone Bastion), so they count as held for this pass; the full
    # acquisition set is re-evaluated below.
    planning_automatic_ids = (
        set(pair_spheres)
        | set(pair_talents)
        | set(ordinary)
        | set(canonical_background_ids.values())
        | set(package_talents)
        | set(trained_ids)
        | set(trained_spheres)
        | set(bonus_ids)
        | {
            value
            for value in selected_by_slot.get("background_talent_choice") or []
            if isinstance(value, str)
        }
    )
    _validate_frozen_legality(
        envelope,
        selected_by_slot,
        plan,
        automatic_ids=planning_automatic_ids,
        only_slot_ids=_PLANNING_SLOT_IDS,
    )

    # Relation evaluation uses explicit semantic acquisitions, not planning
    # priorities.  Do not mutate the canonical selected mapping; build a
    # legality-only view that adds the typed acquisition IDs below.  This
    # prevents a preferred-but-unacquired Insight or Sphere from satisfying
    # (or failing) a prerequisite.
    legality_slots = {
        slot_id: deepcopy(values)
        for slot_id, values in selected_by_slot.items()
        if slot_id not in _PLANNING_SLOT_IDS
    }
    legality_slots.setdefault(sphere_slot, [])
    legality_slots.setdefault(talent_slot, [])
    legality_slots.setdefault(insight_slot, [])
    for value in pair_spheres:
        if value not in legality_slots[sphere_slot]:
            legality_slots[sphere_slot].append(value)
    for value in pair_talents + ordinary:
        if value not in legality_slots[talent_slot]:
            legality_slots[talent_slot].append(value)
    for value in trained_ids:
        if value not in legality_slots[talent_slot]:
            legality_slots[talent_slot].append(value)
    for row in acquisition.get("trained_choices") or []:
        bonus_id = row.get("bonus_talent_id") if isinstance(row, dict) else None
        if isinstance(bonus_id, str) and bonus_id not in legality_slots[talent_slot]:
            legality_slots[talent_slot].append(bonus_id)
    for occurrence in insight_occurrences:
        if occurrence["insight_id"] not in legality_slots[insight_slot]:
            legality_slots[insight_slot].append(occurrence["insight_id"])
    _validate_frozen_legality(
        envelope,
        legality_slots,
        plan,
        automatic_ids=planning_automatic_ids,
    )


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
    provider_required_planning_slot_ids: list[str] | None = None,
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
    has_explicit_forging_contract(envelope)
    from character_creation.constructed_arts.explicit_forging import required_design_ids, validate_required_design_concepts
    if required_design_ids(envelope, run.get("request") or {}):
        validate_required_design_concepts(envelope, ((plan.get("canonical_selection_intent") or {}).get("acquisition_intent") or {}).get("forged_technique_concepts"))
    creation_contract = envelope.get("creation_training_contract")
    if creation_contract is not None:
        contract_errors = validate_creation_training_contract(creation_contract)
        if contract_errors:
            _raise(
                "CG1_CREATION_TRAINING_CONTRACT_INVALID",
                "The sealed creation-training contract is malformed.",
                details={"schema": CREATION_TRAINING_CONTRACT_SCHEMA, "fields": contract_errors},
            )
        source_contract = ((envelope.get("path_method_authority") or {}).get("complete_character_source_authority") or {}).get("creation_training_contract")
        if source_contract != creation_contract:
            _raise(
                "CG1_CREATION_TRAINING_CONTRACT_MISMATCH",
                "The delegated creation-training contract is not identical to the Stage 1 source authority.",
            )
    authority = envelope.get("compiler_selection_authority")
    compiler_gate_active = isinstance(authority, dict)
    binding = envelope.get("binding") or {}
    lock = project.get("content_lock") or {}
    if compiler_gate_active:
        try:
            authority = verify_compiler_selection_authority(
                authority,
                expected_content_lock=lock,
            )
        except FoundryError as exc:
            _raise(exc.code, exc.message, details=exc.details)
        active_request = run.get("request") if isinstance(run.get("request"), dict) else {}
        active_prompt = active_request.get("stage1_prompt") if isinstance(active_request.get("stage1_prompt"), dict) else {}
        expected_prompt = {
            "prompt_id": binding.get("stage1_prompt_id"),
            "prompt_sha256": binding.get("stage1_prompt_sha256"),
        }
        actual_prompt = {
            "prompt_id": active_prompt.get("prompt_id"),
            "prompt_sha256": active_prompt.get("prompt_sha256"),
        }
        if (
            not isinstance(active_request.get("stage1_prompt"), dict)
            or any(not isinstance(value, str) or not value for value in expected_prompt.values())
            or actual_prompt != expected_prompt
        ):
            _raise(
                "CG1_DELEGATED_STAGE1_PROMPT_BINDING_MISMATCH",
                "The delegated envelope is not bound to the active persisted Stage 1 prompt.",
                details={"expected": expected_prompt, "actual": actual_prompt},
            )
        request_binding = {
            "project_id": active_request.get("project_id"),
            "project_revision": active_request.get("project_revision"),
            "content_lock_hash": active_request.get("content_lock_hash"),
        }
        expected_request_binding = {
            "project_id": binding.get("project_id"),
            "project_revision": binding.get("project_revision"),
            "content_lock_hash": binding.get("content_lock_hash"),
        }
        if request_binding != expected_request_binding:
            _raise(
                "CG1_DELEGATED_REQUEST_BINDING_MISMATCH",
                "The delegated envelope does not match the active persisted request binding.",
                details={"expected": expected_request_binding, "actual": request_binding},
            )
        persisted_authority = active_request.get("delegated_choice_envelope")
        persisted_authority = persisted_authority if isinstance(persisted_authority, dict) else {}
        persisted_authority = persisted_authority.get("compiler_selection_authority")
        if not isinstance(persisted_authority, dict) or persisted_authority.get("authority_sha256") != authority.get("authority_sha256"):
            _raise(
                "CG1_DELEGATED_COMPILER_AUTHORITY_STALE",
                "The delegated compiler authority is not the authority persisted in the active request.",
                details={
                    "expected": authority.get("authority_sha256"),
                    "actual": persisted_authority.get("authority_sha256") if isinstance(persisted_authority, dict) else None,
                },
            )
    if compiler_gate_active:
        authority_content = authority.get("content") or {}
        if authority_content.get("content_lock_hash") != lock.get("lock_hash"):
            _raise(
                "CG1_DELEGATED_COMPILER_AUTHORITY_STALE",
                "The persisted delegated request is bound to a different project content lock than its compiler authority.",
                details={
                    "authority_content_lock_hash": authority_content.get("content_lock_hash"),
                    "project_content_lock_hash": lock.get("lock_hash"),
                },
            )
    actual_binding = {
        "project_id": project.get("project_id"),
        "project_revision": project.get("revision"),
        "catalog_build_id": lock.get("catalog_build_id"),
        "content_lock_hash": lock.get("lock_hash"),
    }
    if compiler_gate_active:
        actual_binding["target_cl"] = frozen_owner_target_cl(project)
    expected_binding = {key: binding.get(key) for key in actual_binding}
    if actual_binding != expected_binding:
        _raise("CG1_DELEGATED_ENVELOPE_STALE", "The project revision or content lock changed after the delegated request was frozen.", details={"expected": expected_binding, "actual": actual_binding})
    if compiler_gate_active and binding.get("compiler_selection_authority_sha256") != authority.get("authority_sha256"):
        _raise(
            "CG1_DELEGATED_COMPILER_AUTHORITY_STALE",
            "The delegated request is not bound to its compiler-selection authority snapshot.",
            details={"expected": binding.get("compiler_selection_authority_sha256"), "actual": authority.get("authority_sha256")},
        )
    # The title contract is part of the sealed envelope for new production
    # requests.  Establish its shape before any lock-state checks so a
    # forged/self-rehashed descriptive field cannot reach ordinary planning
    # validation as a legacy omission.
    delegated_fields = envelope.get("delegated_fields")
    delegated_fields = delegated_fields if isinstance(delegated_fields, dict) else {}
    title_authority_present = "identity.title" in delegated_fields
    title_authority = delegated_fields.get("identity.title")
    title_contract = envelope.get("delegated_title_contract")
    title_contract_present = "delegated_title_contract" in envelope
    title_contract_active = _delegated_title_contract_is_complete(title_authority, title_contract)
    title_contract_applies = compiler_gate_active or title_authority_present or title_contract_present
    if title_contract_applies and not title_contract_active:
        _raise(
            "CG1_DELEGATED_TITLE_AUTHORITY_INVALID",
            "The active delegated title contract is malformed or incomplete.",
            details={"field": "identity.title"},
        )
    target_cl = validate_delegated_target_cl(run, project, plan)
    locks = _locks(project)
    if _stable_hash(_owner_user_locks(project)) != (envelope.get("owner_locks") or {}).get("lock_sha256"):
        _raise("CG1_DELEGATED_OWNER_LOCKS_CHANGED", "Owner locks changed after the delegated request was frozen.")
    if title_contract_active:
        persisted_title_lock = locks.get("character.identity.title")
        if persisted_title_lock is not None and (
            not isinstance(persisted_title_lock, str) or not persisted_title_lock.strip()
        ):
            _raise(
                "CG1_DELEGATED_TITLE_AUTHORITY_INVALID",
                "The active delegated request is bound to an invalid owner title lock.",
                details={"field": "character.identity.title"},
                status_code=409,
            )
        persisted_title = persisted_title_lock.strip() if isinstance(persisted_title_lock, str) else None
        expected_title_state = "owner_locked" if persisted_title else "delegated"
        if (
            not isinstance(title_authority, dict)
            or title_authority.get("state") != expected_title_state
            or title_authority.get("owner_value") != persisted_title
            or title_contract.get("state") != expected_title_state
            or title_contract.get("owner_locked_value") != persisted_title
        ):
            _raise(
                "CG1_DELEGATED_TITLE_AUTHORITY_INVALID",
                "The active delegated title authority is not bound to the persisted owner lock state.",
                details={
                    "field": "identity.title",
                    "expected_state": expected_title_state,
                    "actual_state": title_authority.get("state") if isinstance(title_authority, dict) else None,
                },
                status_code=409,
            )
    one_shot = envelope.get("one_shot") or {}
    if one_shot.get("idempotency_key") != run.get("idempotency_key") or one_shot.get("execution_mode") != run.get("execution_mode"):
        _raise("CG1_DELEGATED_ONE_SHOT_BINDING_MISMATCH", "The delegated envelope is bound to a different one-shot run.")
    if compiler_gate_active:
        expected_one_shot_binding = _stable_hash({
            "project_id": binding.get("project_id"),
            "project_revision": binding.get("project_revision"),
            "target_cl": binding.get("target_cl"),
            "content_lock_hash": binding.get("content_lock_hash"),
            "stage1_prompt_id": binding.get("stage1_prompt_id"),
            "stage1_prompt_sha256": binding.get("stage1_prompt_sha256"),
            "compiler_selection_authority_sha256": binding.get("compiler_selection_authority_sha256"),
            "execution_mode": run.get("execution_mode"),
            "idempotency_key": run.get("idempotency_key"),
        })
        if binding.get("one_shot_binding_sha256") != expected_one_shot_binding:
            _raise("CG1_DELEGATED_ONE_SHOT_BINDING_MISMATCH", "The delegated envelope one-shot binding does not match this request.", details={"expected": binding.get("one_shot_binding_sha256"), "actual": expected_one_shot_binding})

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
    if deferred_method and type(target_cl) is int and target_cl >= 1:
        # Path 0 to 1 is a Method initiation (rulebook line 11); a deferred
        # Method is legal only for a character with no attainment.
        _raise(
            "CG1_DELEGATED_METHOD_REQUIRED",
            "A character with attainment must have a Method; deferring the Method is legal only at CL 0.",
            details={"target_cl": target_cl, "allowed_method_ids": list((envelope.get("allowed_choice_ids_by_slot") or {}).get(_METHOD_SLOT) or [])},
        )
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
            constructed = method_access.get("constructed_access_route")
            constructed_ok = isinstance(constructed, Mapping) and isinstance(constructed.get("choice_id"), str)
            if proof.get("selection_authorized") is not True and not constructed_ok:
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
        ignored_slot_ids=_PLANNING_SLOT_IDS,
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
        if not isinstance(row, dict) or not row.get("record_id") or _is_constructed_starting_kit_row(row):
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
    title_authority = delegated_fields.get("identity.title") or {}
    title_contract = envelope.get("delegated_title_contract")
    title_contract_active = (
        isinstance(title_contract, dict)
        and title_contract.get("schema") == DELEGATED_TITLE_REQUIREMENT_SCHEMA
        and title_contract.get("field") == "owner_descriptive_fields.identity.title"
        and title_contract.get("required") is True
        and title_contract.get("nonblank") is True
    )
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
        pass  # owner-locked name: resolved below by _owner_wins (owner rule 2026-10-10)
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
        proposed_name = _owner_wins(owner_name, proposed_name)
    if concept_authority.get("state") == "owner_locked":
        owner_concept = str(concept_authority.get("owner_value") or "").strip()
        proposed_concept = _owner_wins(owner_concept, proposed_concept)
    title_values_raw: list[Any] = []
    if isinstance(identity, dict) and "title" in identity:
        title_values_raw.append(identity.get("title"))
    if "title" in descriptive:
        title_values_raw.append(descriptive.get("title"))
    title_values = [
        value.strip()
        for value in title_values_raw
        if isinstance(value, str) and value.strip()
    ]
    if len(set(title_values)) > 1:
        _raise(
            "CG1_DELEGATED_AUTHORITY_CONFLICT",
            "The response supplied conflicting delegated title representations.",
            details={"field": "identity.title", "representations": title_values},
        )
    if title_contract_active:
        if not isinstance(title_authority, dict) or not title_authority:
            _raise(
                "CG1_DELEGATED_TITLE_AUTHORITY_INVALID",
                "The active delegated request is missing its sealed title authority.",
                details={"field": "identity.title"},
                status_code=409,
            )
        if any(not isinstance(value, str) or not value.strip() for value in title_values_raw) or not title_values:
            _raise(
                DELEGATED_TITLE_REQUIRED_ERROR,
                "A delegated character title is required: owner_descriptive_fields.identity.title must contain a concise nonblank title for owner review.",
                details={
                    "field": "owner_descriptive_fields.identity.title",
                    "required": True,
                    "nonblank": True,
                    "state": title_authority.get("state"),
                },
            )
        proposed_title = title_values[0]
        if len(proposed_title) > 120:
            _raise(
                "CG1_DELEGATED_TITLE_INVALID",
                "A delegated character title must be concise and no longer than 120 characters.",
                details={"field": "owner_descriptive_fields.identity.title", "max_length": 120},
                status_code=422,
            )
        title_state = title_authority.get("state")
        owner_title = title_authority.get("owner_value")
        if title_state == "owner_locked":
            if not isinstance(owner_title, str) or not owner_title.strip():
                _raise(
                    "CG1_OWNER_LOCKED_DESCRIPTIVE_FIELD_CHANGED",
                    "The response must contain the exact owner-locked character title unchanged.",
                    details={
                        "field": "owner_descriptive_fields.identity.title",
                        "expected": owner_title if isinstance(owner_title, str) else None,
                        "actual": proposed_title,
                    },
                )
            proposed_title = _owner_wins(owner_title.strip(), proposed_title)
        elif title_state != "delegated":
            _raise(
                "CG1_DELEGATED_TITLE_AUTHORITY_INVALID",
                "The active delegated title authority has an invalid state.",
                details={"field": "identity.title", "state": title_state},
                status_code=409,
            )
    else:
        proposed_title = title_values[0] if title_values else ""
    descriptive["identity"] = identity
    descriptive["identity"]["name"] = proposed_name or None
    if title_contract_active or title_values_raw:
        descriptive["identity"]["title"] = proposed_title or None
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
    provider_required_planning_slots = (
        set(provider_required_planning_slot_ids)
        if isinstance(provider_required_planning_slot_ids, list)
        and all(isinstance(slot_id, str) for slot_id in provider_required_planning_slot_ids)
        else None
    )
    for slot_id in envelope.get("unresolved_owner_decisions") or []:
        if (
            provider_required_planning_slots is not None
            and slot_id in _PLANNING_SLOT_IDS
            and slot_id not in provider_required_planning_slots
        ):
            continue
        if slot_id == _METHOD_SLOT and not method_id:
            # A deferred Method is a legal typed outcome at creation (RAW:
            # Methods are not required at creation), recorded once below as
            # ``deferred``; it is not an owner decision the review must block
            # on.  An EXACT plan that cannot be delivered fails closed at
            # request assembly instead (CG1_METHOD_EXACT_PLAN_UNAVAILABLE).
            continue
        if selected_by_slot.get(slot_id):
            continue
        # The same Realm-entry rules the walk applies: no Foundation before
        # the Foundation Realm (CL 5) and no Subpath before the first Path
        # Subpath selection (CL 3).  Below those CLs the absent choice is a
        # legal typed none, not an owner decision; a CL 1 build otherwise
        # reached review clean and then stalled on two undecidable slots.
        if slot_id == _FOUNDATION_SLOT and type(target_cl) is int and target_cl < REALM_ENTRY_CL["Foundation"]:
            add_provenance({"slot_id": slot_id, "choice_id": None, "provenance": "typed_none", "status": "deferred_or_typed_none", "reason": "foundation_not_available_below_realm_entry_cl"})
            continue
        if slot_id == "subpath_choice" and type(target_cl) is int and target_cl < FIRST_PATH_SUBPATH_SELECTION_CL:
            add_provenance({"slot_id": slot_id, "choice_id": None, "provenance": "typed_none", "status": "deferred_or_typed_none", "reason": "subpath_not_selectable_below_first_selection_cl"})
            continue
        add_provenance({"slot_id": slot_id, "choice_id": None, "provenance": "needs_owner", "status": "unresolved"})
    if not method_id:
        add_provenance({
            "slot_id": _METHOD_SLOT,
            "choice_id": None,
            "provenance": "deferred",
            "status": "deferred_or_typed_none",
            "reason": "method_deferred_legal_at_creation",
        })
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
        "descriptive_fields": {
            "name": proposed_name or None,
            "concept": proposed_concept or None,
            **(
                {"title": proposed_title or None}
                if title_contract_active or title_values_raw
                else {}
            ),
        },
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
