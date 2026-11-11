"""Compact, request-bound choice context for the interim Manual Chat bridge.

This module deliberately projects only stable choice metadata from the frozen
delegated-choice envelope.  It is not a second legality engine: the Factory
still owns acceptance and compilation.  The correction classifier is an
early, bounded diagnostic so a malformed ordinary-talent progression is sent
back to the AI instead of being presented as an owner choice.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable


MANUAL_AI_CHOICE_MODEL_SCHEMA = "TianxiaFoundry.ManualAIChoiceModel.v1"
MANUAL_AI_CORRECTION_SCHEMA = "TianxiaFoundry.ManualAICorrectionRequest.v1"
ORDINARY_TALENT_SLOT = "advancement_skeleton"
ORDINARY_TALENT_FIELD = "acquisition_intent.ordinary_talent_ids"
MAX_SUPPORTED_CL = 20

_PLANNING_SLOTS = frozenset({
    "sphere_priorities",
    "advancement_skeleton",
    "insight_priorities",
    "item_priorities",
})
_SLOT_CATEGORIES = {
    "path_choice": "path",
    "method_choice": "method",
    "foundation_choice": "foundation",
    "subpath_choice": "subpath",
    "background_choice": "background",
    "background_sphere_choice": "sphere",
    "background_talent_choice": "talent",
    "origin_insight_choice": "insight",
    "sphere_priorities": "sphere",
    "advancement_skeleton": "talent",
    "insight_priorities": "insight",
    "item_priorities": "item",
}


def _choice_row(envelope: dict[str, Any], slot_id: str, choice_id: str) -> dict[str, Any]:
    rows = (envelope.get("choices_by_slot") or {}).get(slot_id) or {}
    row = rows.get(choice_id) if isinstance(rows, dict) else None
    return row if isinstance(row, dict) else {}


def choice_authority(
    envelope: dict[str, Any],
    slot_id: str,
    choice_id: str,
    row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the typed Stage 2 authority published for one frozen choice."""

    typed = envelope.get("typed_choice_authority_by_slot") or {}
    authority = (
        (typed.get(slot_id) or {}).get("stage2_authority_by_choice", {}).get(choice_id)
        if isinstance(typed, dict)
        else None
    )
    current = row if isinstance(row, dict) else _choice_row(envelope, slot_id, choice_id)
    if not isinstance(authority, dict):
        authority = current.get("stage2_authority")
    if not isinstance(authority, dict):
        authority = (current.get("compatibility") or {}).get("factory", {}).get("stage2_authority")
    return authority if isinstance(authority, dict) else {}


def relation_targets(relation: Any) -> list[str]:
    """Extract only stable IDs from a typed prerequisite/incompatibility."""

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


def _relations(row: dict[str, Any], key: str) -> list[Any]:
    values = row.get(key)
    if values is None and isinstance(row.get("legality"), dict):
        values = row["legality"].get(key)
    return list(values) if isinstance(values, list) else []


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _minimum_cl(row: dict[str, Any], authority: dict[str, Any]) -> int | None:
    for value in (
        authority.get("minimum_cl"),
        (row.get("availability") or {}).get("minimum_cl") if isinstance(row.get("availability"), dict) else None,
        row.get("minimum_cl"),
        (row.get("legality") or {}).get("minimum_cl") if isinstance(row.get("legality"), dict) else None,
    ):
        if type(value) is int:
            return value
    return None


def _owner(row: dict[str, Any], authority: dict[str, Any]) -> str | None:
    return _first_string(
        row.get("owner"),
        row.get("owning_path_id"),
        row.get("owning_canonical_sphere_id"),
        row.get("owning_sphere_id"),
        authority.get("owner"),
        authority.get("owning_path_id"),
        authority.get("owning_canonical_sphere_id"),
        authority.get("owning_sphere_id"),
        authority.get("sphere_id"),
    )


def _category(slot_id: str, row: dict[str, Any], authority: dict[str, Any]) -> str:
    value = _first_string(row.get("category"), row.get("content_type"), authority.get("category"))
    return value or _SLOT_CATEGORIES.get(slot_id, "choice")


def _semantic_cue(slot_id: str, choice_id: str, row: dict[str, Any], category: str) -> str:
    value = _first_string(
        row.get("semantic_cue"),
        row.get("short_description"),
        row.get("summary"),
        row.get("owner_description"),
        row.get("description"),
    )
    if value:
        # The compact model is deliberately not a source or mechanics dump.
        value = " ".join(value.split())
        return value[:180]
    return f"{category} choice {choice_id}."


def _channels(row: dict[str, Any], authority: dict[str, Any]) -> list[str]:
    values = authority.get("allowed_channels") or row.get("acquisition_channels") or row.get("allowed_channels")
    if isinstance(values, str):
        values = [values]
    return sorted({value for value in values or [] if isinstance(value, str) and value})


def compact_choice(
    envelope: dict[str, Any],
    slot_id: str,
    choice_id: str,
    row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project one choice without copying its full frozen record."""

    current = row if isinstance(row, dict) else _choice_row(envelope, slot_id, choice_id)
    authority = choice_authority(envelope, slot_id, choice_id, current)
    category = _category(slot_id, current, authority)
    channels = _channels(current, authority)
    prerequisites = sorted({target for relation in _relations(current, "prerequisites") for target in relation_targets(relation)})
    incompatibilities = sorted({target for relation in _relations(current, "incompatibilities") for target in relation_targets(relation)})
    return {
        "id": choice_id,
        "display_name": _first_string(
            current.get("display_name"),
            current.get("name"),
            current.get("canonical_name"),
            current.get("title"),
            choice_id,
        ) or choice_id,
        "owner": _owner(current, authority),
        "category": category,
        "minimum_cl": _minimum_cl(current, authority),
        "hard_prerequisite_ids": prerequisites,
        "incompatibility_ids": incompatibilities,
        "acquisition_channel": channels[0] if len(channels) == 1 else channels or None,
        "semantic_cue": _semantic_cue(slot_id, choice_id, current, category),
    }


def _ordinary_source_eligible(record: dict[str, Any], cl: int, authority: dict[str, Any]) -> bool:
    minimum = record.get("minimum_cl")
    if type(minimum) is int and minimum > cl:
        return False
    kinds = authority.get("allowed_kinds") or []
    if kinds and "level_talent_acquisition" not in kinds:
        return False
    channels = authority.get("allowed_channels") or []
    return bool(authority.get("authority_complete") is True and kinds and channels)


def _background_package_linkage(
    envelope: dict[str, Any],
    allowed_by_slot: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Project the Stage 1 Background package contract without inference."""

    typed = envelope.get("typed_choice_authority_by_slot") or {}
    contract = typed.get("background_choice") if isinstance(typed, dict) else None
    raw_linkage = contract.get("background_package_linkage") if isinstance(contract, dict) else None
    if not isinstance(raw_linkage, dict):
        return {}
    allowed_background_ids = {
        value for value in allowed_by_slot.get("background_choice") or [] if isinstance(value, str)
    }
    allowed_sphere_ids = {
        value for value in allowed_by_slot.get("background_sphere_choice") or [] if isinstance(value, str)
    }
    allowed_talent_ids = {
        value for value in allowed_by_slot.get("background_talent_choice") or [] if isinstance(value, str)
    }
    projected: dict[str, list[dict[str, Any]]] = {}
    for background_id in sorted(allowed_background_ids):
        packages = raw_linkage.get(background_id)
        if not isinstance(packages, list) or not packages:
            continue
        valid_packages: list[dict[str, Any]] = []
        for package in packages:
            if not isinstance(package, dict):
                break
            if (
                type(package.get("package_index")) is not int
                or not isinstance(package.get("sphere_record_id"), str)
                or not isinstance(package.get("talent_record_id"), str)
            ):
                break
            sphere_choice_id = package.get("background_sphere_choice_id")
            talent_choice_id = package.get("background_talent_choice_id")
            if (
                not isinstance(sphere_choice_id, str)
                or not isinstance(talent_choice_id, str)
                or sphere_choice_id not in allowed_sphere_ids
                or talent_choice_id not in allowed_talent_ids
            ):
                break
            valid_packages.append(deepcopy(package))
        if len(valid_packages) == len(packages):
            projected[background_id] = valid_packages
    return projected


def build_compact_choice_model(request: dict[str, Any]) -> dict[str, Any]:
    """Build the deterministic Manual Chat choice context from one request."""

    envelope = request.get("delegated_choice_envelope") or {}
    envelope = envelope if isinstance(envelope, dict) else {}
    allowed_by_slot = envelope.get("allowed_choice_ids_by_slot") or {}
    allowed_by_slot = allowed_by_slot if isinstance(allowed_by_slot, dict) else {}
    choices_by_slot = envelope.get("choices_by_slot") or {}
    choices_by_slot = choices_by_slot if isinstance(choices_by_slot, dict) else {}
    compact_by_slot: dict[str, list[dict[str, Any]]] = {}
    for slot_id in sorted(allowed_by_slot):
        ids = sorted({value for value in allowed_by_slot.get(slot_id) or [] if isinstance(value, str)})
        compact_by_slot[slot_id] = [compact_choice(envelope, slot_id, choice_id) for choice_id in ids]
    background_package_linkage = _background_package_linkage(envelope, allowed_by_slot)

    ordinary_records = {
        row["id"]: row
        for row in compact_by_slot.get(ORDINARY_TALENT_SLOT, [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    target_authority = envelope.get("frozen_owner_target_cl") or {}
    target_cl = target_authority.get("value") if isinstance(target_authority, dict) else None
    if type(target_cl) is not int:
        target_cl = None
    ordinary_rows = (choices_by_slot.get(ORDINARY_TALENT_SLOT) or {})
    ordinary_slots: list[dict[str, Any]] = []
    for cl in range(1, MAX_SUPPORTED_CL + 1):
        eligible: list[str] = []
        for choice_id, record in ordinary_records.items():
            source_row = ordinary_rows.get(choice_id) if isinstance(ordinary_rows, dict) else {}
            source_row = source_row if isinstance(source_row, dict) else {}
            authority = choice_authority(envelope, ORDINARY_TALENT_SLOT, choice_id, source_row)
            if _ordinary_source_eligible(record, cl, authority):
                eligible.append(choice_id)
        ordinary_slots.append({
            "cl": cl,
            "array_index": cl - 1,
            "response_field": ORDINARY_TALENT_FIELD,
            "eligible_choice_ids": sorted(eligible),
            "active_for_request": target_cl is None or cl <= target_cl,
            "sphere_ownership": "candidate owner must match an acquired Sphere",
        })

    return {
        "schema": MANUAL_AI_CHOICE_MODEL_SCHEMA,
        "model_version": 1,
        "request_sha256": request.get("request_sha256"),
        "project_id": request.get("project_id"),
        "project_revision": request.get("project_revision"),
        "content_lock_hash": request.get("content_lock_hash"),
        "target_cl": target_cl,
        "response_contract": {
            "schema": "TianxiaFoundry.DelegatedSelectionIntentResponse.v1",
            "ordinary_talent_field": ORDINARY_TALENT_FIELD,
            "ordinary_talent_field_aliases": [
                ORDINARY_TALENT_FIELD,
                "selection_intent.by_slot.advancement_skeleton",
            ],
            "ordinary_talent_slot_id": ORDINARY_TALENT_SLOT,
            "array_position_semantics": "zero-based array index N is the ordinary Talent acquired at CL N+1",
            "one_entry_per_cl": True,
            "supported_cl_range": [1, MAX_SUPPORTED_CL],
            "background_package_linkage_field": "background_package_linkage",
            "background_package_selection_semantics": (
                "For a selected Background, choose the linked Background Sphere and Background Talent "
                "from one package_index; do not infer or mix package rows."
            ),
        },
        "choices_by_slot": compact_by_slot,
        "background_package_linkage": background_package_linkage,
        "ordinary_talent_slots": ordinary_slots,
    }


def _selected_values(plan: dict[str, Any], slot_id: str) -> list[str]:
    selection = plan.get("selection_intent") if isinstance(plan.get("selection_intent"), dict) else {}
    by_slot = selection.get("by_slot") if isinstance(selection.get("by_slot"), dict) else {}
    values = by_slot.get(slot_id)
    return [value for value in values or [] if isinstance(value, str)] if isinstance(values, list) else []


def _ordinary_values(plan: dict[str, Any]) -> tuple[list[Any] | None, str]:
    acquisition = plan.get("acquisition_intent")
    if isinstance(acquisition, dict) and "ordinary_talent_ids" in acquisition:
        values = acquisition.get("ordinary_talent_ids")
        return values if isinstance(values, list) else None, ORDINARY_TALENT_FIELD
    selection = plan.get("selection_intent")
    by_slot = selection.get("by_slot") if isinstance(selection, dict) else None
    values = by_slot.get(ORDINARY_TALENT_SLOT) if isinstance(by_slot, dict) else None
    return values if isinstance(values, list) else None, "selection_intent.by_slot.advancement_skeleton"


def _sphere_ids_for_response(envelope: dict[str, Any], plan: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    acquisition = plan.get("acquisition_intent") if isinstance(plan.get("acquisition_intent"), dict) else {}
    for pair in acquisition.get("sphere_free_talent_pairs") or []:
        if isinstance(pair, dict) and isinstance(pair.get("sphere_id"), str):
            result.add(pair["sphere_id"])
    background_rows = (envelope.get("choices_by_slot") or {}).get("background_sphere_choice") or {}
    for choice_id in _selected_values(plan, "background_sphere_choice"):
        row = background_rows.get(choice_id) if isinstance(background_rows, dict) else {}
        authority = choice_authority(envelope, "background_sphere_choice", choice_id, row if isinstance(row, dict) else {})
        for value in (
            (row or {}).get("owning_canonical_sphere_id") if isinstance(row, dict) else None,
            (row or {}).get("sphere_id") if isinstance(row, dict) else None,
            authority.get("owning_canonical_sphere_id"),
            authority.get("sphere_id"),
        ):
            if isinstance(value, str):
                result.add(value)
    return result


def _present_ids(plan: dict[str, Any], envelope: dict[str, Any], ordinary: list[Any], index: int) -> set[str]:
    result: set[str] = set()
    selection = plan.get("selection_intent") if isinstance(plan.get("selection_intent"), dict) else {}
    by_slot = selection.get("by_slot") if isinstance(selection.get("by_slot"), dict) else {}
    for slot_id, values in by_slot.items():
        if slot_id in _PLANNING_SLOTS or not isinstance(values, list):
            continue
        result.update(value for value in values if isinstance(value, str))
    acquisition = plan.get("acquisition_intent") if isinstance(plan.get("acquisition_intent"), dict) else {}
    for pair in acquisition.get("sphere_free_talent_pairs") or []:
        if isinstance(pair, dict):
            result.update(value for value in (pair.get("sphere_id"), pair.get("talent_id")) if isinstance(value, str))
    result.update(_sphere_ids_for_response(envelope, plan))
    result.update(value for value in ordinary[:index] if isinstance(value, str))
    return result


def _candidate_issues(
    *,
    envelope: dict[str, Any],
    project: dict[str, Any],
    choices: dict[str, dict[str, Any]],
    compact_records: dict[str, dict[str, Any]],
    candidate_id: str,
    cl: int,
    index: int,
    ordinary: list[Any],
    free_talent_ids: set[str],
    present_ids: set[str],
    resolve_event_authority: Callable[..., Any],
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    row = choices.get(candidate_id)
    record = compact_records.get(candidate_id)
    if not isinstance(row, dict) or not isinstance(record, dict):
        return [{"code": "INVALID_ID", "reason": "The proposed ordinary Talent ID is not an allowed frozen choice."}]
    if row.get("content_type") not in {None, "talent"}:
        issues.append({"code": "RECORD_TYPE", "reason": "The proposed ID is not a Talent authority record."})
    minimum = record.get("minimum_cl")
    if type(minimum) is int and minimum > cl:
        issues.append({"code": "MINIMUM_CL", "reason": f"The source minimum CL is {minimum}, but this array position is CL{cl}."})
    if candidate_id in free_talent_ids or any(
        value == candidate_id for position, value in enumerate(ordinary) if position != index
    ):
        issues.append({"code": "DUPLICATE", "reason": "The ordinary Talent is already used by another acquisition or free-Talent grant."})
    owner = record.get("owner")
    # The response's acquired Spheres are the only IDs that can satisfy this
    # ownership check; do not infer ownership from a display name.
    sphere_ids = set()
    acquisition = project.get("_manual_ai_selected_sphere_ids") if isinstance(project, dict) else None
    if isinstance(acquisition, set):
        sphere_ids = acquisition
    if isinstance(owner, str) and owner not in sphere_ids:
        issues.append({"code": "SPHERE_OWNERSHIP", "reason": f"The Talent is owned by Sphere {owner}, which is not among the acquired Spheres."})

    authority = choice_authority(envelope, ORDINARY_TALENT_SLOT, candidate_id, row)
    if authority.get("authority_complete") is not True or "level_talent_acquisition" not in (authority.get("allowed_kinds") or []):
        issues.append({"code": "ACQUISITION_CHANNEL", "reason": "The frozen authority does not allow the level-talent acquisition channel for this CL."})
    else:
        try:
            synthetic_record = deepcopy(row)
            synthetic_record["record_id"] = candidate_id
            synthetic_record.setdefault("compatibility", {}).setdefault("factory", {})["stage2_authority"] = deepcopy(authority)
            resolve_event_authority(
                synthetic_record,
                project,
                requested_kind="level_talent_acquisition",
                effective_cl=cl,
                field=f"{ORDINARY_TALENT_FIELD}.{index}",
            )
        except Exception as exc:  # Factory authority errors are correction reasons, not owner choices.
            message = getattr(exc, "message", None)
            issues.append({
                "code": "ACQUISITION_CHANNEL",
                "reason": str(message or "The frozen authority rejects the level-talent acquisition channel for this CL."),
            })

    prerequisites = _relations(row, "prerequisites")
    for relation in prerequisites:
        if not isinstance(relation, (str, dict)):
            issues.append({"code": "HARD_PREREQUISITE", "reason": "The frozen prerequisite is not a supported typed relation."})
            continue
        targets = relation_targets(relation)
        operator = relation.get("operator", "requires") if isinstance(relation, dict) else "requires"
        if not targets or operator not in {"requires", "one_of", "all_of", "not"}:
            issues.append({"code": "HARD_PREREQUISITE", "reason": "The frozen prerequisite is not a supported typed relation."})
            continue
        if operator in {"requires", "all_of"}:
            satisfied = all(target in present_ids for target in targets)
        elif operator == "one_of":
            satisfied = any(target in present_ids for target in targets)
        else:
            satisfied = not any(target in present_ids for target in targets)
        if not satisfied:
            issues.append({
                "code": "HARD_PREREQUISITE",
                "reason": f"The hard prerequisite IDs are not satisfied: {', '.join(targets)}.",
            })

    incompatible_ids = {
        target
        for relation in _relations(row, "incompatibilities")
        for target in relation_targets(relation)
    }
    conflicting = sorted(incompatible_ids & (present_ids - {candidate_id}))
    if conflicting:
        issues.append({
            "code": "INCOMPATIBILITY",
            "reason": f"The proposed Talent conflicts with frozen choice IDs: {', '.join(conflicting)}.",
        })
    return issues


def classify_ordinary_talent_corrections(
    request: dict[str, Any],
    plan: dict[str, Any],
    project: dict[str, Any],
    resolve_event_authority: Callable[..., Any],
) -> dict[str, Any] | None:
    """Aggregate safely detectable invalid ordinary-talent positions.

    ``None`` means this narrow preflight found no ordinary-position issue and
    normal delegated validation should continue.  It intentionally does not
    try to diagnose unrelated response-shape or Path/milestone failures.
    """

    envelope = request.get("delegated_choice_envelope") or {}
    if not isinstance(envelope, dict):
        return None
    ordinary, response_field = _ordinary_values(plan)
    if not isinstance(ordinary, list):
        return None
    acquisition = plan.get("acquisition_intent")
    acquisition = acquisition if isinstance(acquisition, dict) else {}
    frozen = envelope.get("frozen_owner_target_cl") or {}
    target_cl = frozen.get("value") if isinstance(frozen, dict) else None
    if type(target_cl) is not int:
        target_cl = plan.get("target_cl") if type(plan.get("target_cl")) is int else None
    if type(target_cl) is not int or not 1 <= target_cl <= MAX_SUPPORTED_CL:
        return None
    allowed_ids = [value for value in (envelope.get("allowed_choice_ids_by_slot") or {}).get(ORDINARY_TALENT_SLOT, []) if isinstance(value, str)]
    choices = (envelope.get("choices_by_slot") or {}).get(ORDINARY_TALENT_SLOT) or {}
    choices = choices if isinstance(choices, dict) else {}
    model = build_compact_choice_model(request)
    compact_records = {
        row["id"]: row
        for row in (model.get("choices_by_slot") or {}).get(ORDINARY_TALENT_SLOT, [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    free_talent_ids = {
        pair.get("talent_id")
        for pair in acquisition.get("sphere_free_talent_pairs") or []
        if isinstance(pair, dict) and isinstance(pair.get("talent_id"), str)
    }
    selected_spheres = _sphere_ids_for_response(envelope, plan)
    # The callback context must stay JSON-serializable.  The set is attached
    # only to this local shallow copy and never leaves this function.
    callback_project = dict(project)
    callback_project["_manual_ai_selected_sphere_ids"] = selected_spheres
    expected_count = envelope.get("ordinary_talent_count")
    if type(expected_count) is not int:
        expected_count = target_cl
    position_count = max(target_cl, expected_count, len(ordinary))
    errors: list[dict[str, Any]] = []
    for index in range(position_count):
        cl = index + 1
        if index >= target_cl:
            errors.append({
                "slot": f"{response_field}[{index}]",
                "field": f"{response_field}.{index}",
                "slot_id": ORDINARY_TALENT_SLOT,
                "array_index": index,
                "cl": cl,
                "proposed_id": ordinary[index] if index < len(ordinary) and isinstance(ordinary[index], str) else None,
                "proposal": deepcopy(ordinary[index]) if index < len(ordinary) else None,
                "reason_codes": ["ARRAY_POSITION_OUT_OF_RANGE"],
                "reasons": [f"The frozen request has no ordinary-Talent slot beyond CL{target_cl}."],
                "reason": f"The frozen request has no ordinary-Talent slot beyond CL{target_cl}.",
                "legal_choice_ids": [],
                "legal_candidate_ids": [],
            })
            continue
        present_ids = _present_ids(plan, envelope, ordinary, index)
        used_other = set(free_talent_ids) | {
            value for position, value in enumerate(ordinary)
            if position != index and isinstance(value, str)
        }
        legal_ids: list[str] = []
        for candidate_id in sorted(set(allowed_ids)):
            if candidate_id in used_other:
                continue
            candidate_issues = _candidate_issues(
                envelope=envelope,
                project=callback_project,
                choices=choices,
                compact_records=compact_records,
                candidate_id=candidate_id,
                cl=cl,
                index=index,
                ordinary=ordinary,
                free_talent_ids=free_talent_ids,
                present_ids=present_ids,
                resolve_event_authority=resolve_event_authority,
            )
            if not candidate_issues:
                legal_ids.append(candidate_id)
        if index >= len(ordinary):
            errors.append({
                "slot": f"{response_field}[{index}]",
                "field": f"{response_field}.{index}",
                "slot_id": ORDINARY_TALENT_SLOT,
                "array_index": index,
                "cl": cl,
                "proposed_id": None,
                "proposal": None,
                "reason_codes": ["MISSING_POSITION"],
                "reasons": [f"The response did not provide an ordinary Talent for CL{cl}."],
                "reason": f"The response did not provide an ordinary Talent for CL{cl}.",
                "legal_choice_ids": legal_ids,
                "legal_candidate_ids": legal_ids,
            })
            continue
        proposed = ordinary[index]
        issues = _candidate_issues(
            envelope=envelope,
            project=callback_project,
            choices=choices,
            compact_records=compact_records,
            candidate_id=proposed if isinstance(proposed, str) else "",
            cl=cl,
            index=index,
            ordinary=ordinary,
            free_talent_ids=free_talent_ids,
            present_ids=present_ids,
            resolve_event_authority=resolve_event_authority,
        )
        if not issues:
            continue
        codes = [issue["code"] for issue in issues]
        reasons = [issue["reason"] for issue in issues]
        errors.append({
            "slot": f"{response_field}[{index}]",
            "field": f"{response_field}.{index}",
            "slot_id": ORDINARY_TALENT_SLOT,
            "array_index": index,
            "cl": cl,
            "proposed_id": proposed if isinstance(proposed, str) else None,
            "proposal": deepcopy(proposed),
            "reason_codes": codes,
            "reasons": reasons,
            "reason": " ".join(reasons),
            "legal_choice_ids": legal_ids,
            "legal_candidate_ids": legal_ids,
        })
    if not errors:
        return None
    return {
        "schema": MANUAL_AI_CORRECTION_SCHEMA,
        "classification": "AI_CORRECTION_REQUIRED",
        "request_sha256": request.get("request_sha256"),
        "response_field": response_field,
        "slot_id": ORDINARY_TALENT_SLOT,
        "target_cl": target_cl,
        "expected_count": expected_count,
        "actual_count": len(ordinary),
        "error_count": len(errors),
        "errors": errors,
    }
