"""Deterministic assembly of a completed DCC linear walk.

The linear controller owns the response bytes it hands to the existing
character-creation validator.  This module deliberately has no provider or
database dependency: a request-bound hash and a committed typed state are the
only inputs to the preferred response document.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from collections.abc import Mapping

from app.core import FoundryError, canonical_json
from creation_training_authority import (
    canonical_trained_choice,
    constructed_outcome,
    constructed_source,
    validate_creation_training_contract,
    validate_trained_choice_shape,
)

from .linear_menus import CommittedState


RESPONSE_SCHEMA = "TianxiaFoundry.DelegatedSelectionIntentResponse.v1"

# Keep these local copies to avoid importing character_creation.service while
# that service imports the creative-controller package.  The sets intentionally
# mirror the preferred response contract defined at service.py:105-125.
PREFERRED_RESPONSE_KEYS = frozenset(
    {
        "schema",
        "request_sha256",
        "selection_intent",
        "acquisition_intent",
        "bounded_choices",
        "owner_descriptive_fields",
    }
)
PREFERRED_ACQUISITION_KEYS = frozenset(
    {"sphere_free_talent_pairs", "ordinary_talent_ids", "insight_occurrences"}
)
PREFERRED_BOUNDED_CHOICE_KEYS = frozenset(
    {
        "foundation_initial_stage",
        "ability_scores",
        "background_ability",
        "background_ability_amount",
        "ability_score_changes_by_milestone_id",
        "path_progression_by_cl",
        "path_skill_choices_by_path_id",
        "origin_skill_choices_by_origin_id",
        "background_language_choices_by_background_id",
    }
)


class LinearAssemblyError(FoundryError):
    """A completed walk cannot be represented by the preferred response."""


def _error(code: str, message: str, *, details: Any = None) -> None:
    raise LinearAssemblyError(code, message, details=details, status_code=409)


def _state(value: CommittedState | Mapping[str, Any] | None) -> CommittedState:
    if isinstance(value, CommittedState):
        return value
    if not isinstance(value, Mapping):
        return CommittedState.empty()
    return CommittedState(
        by_slot=value.get("by_slot") or {},
        pairs=value.get("pairs") or (),
        ordinary_by_cl=value.get("ordinary_by_cl") or {},
        insight_occurrences=value.get("insight_occurrences") or (),
        bounded=value.get("bounded") or {},
        route_id=value.get("route_id"),
        trained_choices=value.get("trained_choices") or (),
        trained_choice_skips=value.get("trained_choice_skips") or (),
    )


def _request_sha256(request: Mapping[str, Any]) -> str:
    value = request.get("request_sha256")
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _error(
            "DCC_LINEAR_ASSEMBLY_REQUEST_INVALID",
            "A completed linear walk requires the exact request_sha256.",
        )
    return value


def _cl_key(value: Any) -> tuple[int, str]:
    text = str(value)
    try:
        return (0, f"{int(text):09d}")
    except (TypeError, ValueError):
        return (1, text)


def _milestone_cl_by_id(request: Mapping[str, Any]) -> dict[str, int]:
    """Map sealed milestone IDs to their typed CL without parsing IDs."""

    result: dict[str, int] = {}
    envelope = request.get("delegated_choice_envelope")
    for source in (request, envelope if isinstance(envelope, Mapping) else {}):
        rows = source.get("advancement_choice_milestones")
        if not isinstance(rows, (list, tuple)):
            continue
        for row in rows:
            if isinstance(row, Mapping) and isinstance(row.get("milestone_id"), str) and type(row.get("cl")) is int:
                result.setdefault(row["milestone_id"], row["cl"])
    return result


def _ordinary_ids(state: CommittedState) -> list[str]:
    return [
        state.ordinary_by_cl[key]
        for key in sorted(state.ordinary_by_cl, key=_cl_key)
        if isinstance(state.ordinary_by_cl.get(key), str)
    ]


def _selection(state: CommittedState) -> dict[str, list[str]]:
    result = {
        slot_id: [value for value in values if isinstance(value, str)]
        for slot_id, values in state.by_slot.items()
        if isinstance(slot_id, str) and isinstance(values, (list, tuple))
    }
    # This is a redundant planning mirror required by the existing preferred
    # response contract.  It is generated from the typed CL map, never from
    # prompt text or an independently supplied array.
    result["advancement_skeleton"] = _ordinary_ids(state)
    return result


def _advertised_bounded_fields(request: Mapping[str, Any]) -> frozenset[str] | None:
    """Return the sealed bounded fields this request advertises, when known.

    ``service.py`` rejects any assembled bounded field the sealed
    ``bounded_choice_contract.fields`` does not advertise.  A request without
    that contract keeps its previous behaviour.
    """

    if not isinstance(request, Mapping):
        return None
    contract = request.get("bounded_choice_contract")
    fields = contract.get("fields") if isinstance(contract, Mapping) else None
    if not isinstance(fields, Mapping):
        return None
    return frozenset(key for key in fields if isinstance(key, str))


def _bounded(state: CommittedState, advertised: frozenset[str] | None = None) -> dict[str, Any]:
    bounded = state.bounded if isinstance(state.bounded, Mapping) else {}
    result: dict[str, Any] = {}
    for key in sorted(PREFERRED_BOUNDED_CHOICE_KEYS):
        if key in bounded and (advertised is None or key in advertised):
            result[key] = deepcopy(bounded[key])
    # ``point_buy_preset`` is a transient walk fact, not a preferred response
    # field.  Do not leak it into the validator-facing document.
    return result


def _creation_training_choices(request: Mapping[str, Any], state: CommittedState) -> list[dict[str, Any]]:
    envelope = request.get("delegated_choice_envelope")
    envelope = envelope if isinstance(envelope, Mapping) else {}
    contract = envelope.get("creation_training_contract")
    if not isinstance(contract, Mapping):
        authority = envelope.get("complete_character_source_authority")
        contract = authority.get("creation_training_contract") if isinstance(authority, Mapping) else None
    if contract is None:
        if state.trained_choices:
            _error(
                "DCC_LINEAR_ASSEMBLY_TRAINED_CONTRACT_MISSING",
                "Constructed training state cannot be assembled without its sealed contract.",
            )
        return []
    errors = validate_creation_training_contract(contract)
    if errors:
        _error(
            "DCC_LINEAR_ASSEMBLY_TRAINED_CONTRACT_INVALID",
            "The sealed creation-training contract is malformed.",
            details={"fields": errors},
        )
    routes = contract.get("records")
    if not isinstance(routes, Mapping):
        _error("DCC_LINEAR_ASSEMBLY_TRAINED_CONTRACT_INVALID", "The sealed creation-training contract has no record routes.")
    result: list[dict[str, Any]] = []
    seen_slots: set[tuple[int, int]] = set()
    for row in sorted(
        (row for row in state.trained_choices if isinstance(row, Mapping)),
        key=lambda row: (row.get("cl", 0), row.get("slot", 0), row.get("record_id", "")),
    ):
        record_id = row.get("record_id")
        route = routes.get(record_id) if isinstance(record_id, str) else None
        if not isinstance(route, Mapping) or route.get("choice_type") != row.get("choice_type"):
            _error(
                "DCC_LINEAR_ASSEMBLY_TRAINED_ROUTE_INVALID",
                "A constructed training selection is absent from the sealed contract.",
                details={"record_id": record_id},
            )
        key = (row.get("cl"), row.get("slot"))
        if key in seen_slots:
            _error("DCC_LINEAR_ASSEMBLY_TRAINED_SLOT_DUPLICATE", "A constructed training slot cannot be selected twice.", details={"slot": key})
        seen_slots.add(key)
        complete = canonical_trained_choice({
            **dict(row),
            "source": row.get("source") or constructed_source(route, choice_type=row.get("choice_type")),
            "outcome": row.get("outcome") or constructed_outcome(),
        })
        if validate_trained_choice_shape(complete):
            _error(
                "DCC_LINEAR_ASSEMBLY_TRAINED_CHOICE_INVALID",
                "A constructed training selection is not a valid semantic row.",
                details={"record_id": record_id, "fields": validate_trained_choice_shape(complete)},
            )
        if complete["source"] != constructed_source(route, choice_type=complete["choice_type"]):
            _error("DCC_LINEAR_ASSEMBLY_TRAINED_SOURCE_INVALID", "A constructed training source proof does not match the sealed route.", details={"record_id": record_id})
        if complete["outcome"] != constructed_outcome():
            _error("DCC_LINEAR_ASSEMBLY_TRAINED_OUTCOME_INVALID", "Constructed training must record a successful non-rolled outcome.", details={"record_id": record_id})
        result.append(complete)
    return result


def _owner_descriptive_fields(request: Mapping[str, Any], state: CommittedState) -> dict[str, Any]:
    raw = state.bounded.get("identity") if isinstance(state.bounded, Mapping) else None
    identity = dict(raw) if isinstance(raw, Mapping) else {}
    name = identity.get("name")
    title = identity.get("title")
    if not isinstance(name, str) or not name.strip():
        _error(
            "DCC_LINEAR_IDENTITY_MISSING",
            "A completed linear walk requires the committed identity name.",
        )
    if not isinstance(title, str) or not title.strip():
        _error(
            "DCC_LINEAR_IDENTITY_MISSING",
            "A completed linear walk requires the committed identity title.",
        )
    concept = request.get("concept")
    if not isinstance(concept, str):
        stage1_prompt = request.get("stage1_prompt")
        concept = stage1_prompt.get("concept") if isinstance(stage1_prompt, Mapping) else None
    if not (isinstance(concept, str) and concept.strip()):
        # No owner-authored concept: carry the walk's proposed one-sentence
        # concept so the review does not open on an empty "Choose concept".
        concept = identity.get("concept")
    result: dict[str, Any] = {
        "identity": {"name": " ".join(name.split()), "title": " ".join(title.split())},
        "concept": " ".join(concept.split()) if isinstance(concept, str) and concept.strip() else None,
    }
    return result


def build_response(
    request: Mapping[str, Any],
    committed: CommittedState | Mapping[str, Any] | None,
) -> str:
    """Return canonical preferred response JSON for a completed walk."""

    if not isinstance(request, Mapping):
        _error("DCC_LINEAR_ASSEMBLY_REQUEST_INVALID", "The linear request must be an object.")
    state = _state(committed)
    delegated_envelope = request.get("delegated_choice_envelope")
    delegated_envelope = delegated_envelope if isinstance(delegated_envelope, Mapping) else {}
    creation_training_contract = delegated_envelope.get("creation_training_contract")
    if not isinstance(creation_training_contract, Mapping):
        source_authority = delegated_envelope.get("complete_character_source_authority")
        creation_training_contract = source_authority.get("creation_training_contract") if isinstance(source_authority, Mapping) else None
    pairs = [
        {"sphere_id": row["sphere_id"], "talent_id": row["talent_id"]}
        for row in state.pairs
        if isinstance(row, Mapping)
        and isinstance(row.get("sphere_id"), str)
        and isinstance(row.get("talent_id"), str)
    ]
    # Stage 2 derives Insight rows in effective-CL order and the delegated
    # compiler compares the semantic list with it positionally, so the
    # assembled occurrences must follow the sealed milestone CL order rather
    # than commit order (milestone IDs sort "cl12" before "cl8").
    milestone_cls = _milestone_cl_by_id(request)
    occurrences = [
        deepcopy(dict(row))
        for row in sorted(
            (row for row in state.insight_occurrences if isinstance(row, Mapping)),
            key=lambda row: (
                0 if milestone_cls.get(row.get("milestone_id")) is not None else 1,
                milestone_cls.get(row.get("milestone_id")) or 0,
                str(row.get("milestone_id") or ""),
            ),
        )
    ]
    response = {
        "schema": RESPONSE_SCHEMA,
        "request_sha256": _request_sha256(request),
        "selection_intent": {"by_slot": _selection(state)},
        "acquisition_intent": {
            "sphere_free_talent_pairs": pairs,
            "ordinary_talent_ids": _ordinary_ids(state),
            "insight_occurrences": occurrences,
        },
        "bounded_choices": _bounded(state, _advertised_bounded_fields(request)),
        "owner_descriptive_fields": _owner_descriptive_fields(request, state),
    }
    trained_choices = _creation_training_choices(request, state)
    if isinstance(creation_training_contract, Mapping):
        response["acquisition_intent"]["trained_choices"] = trained_choices
    if set(response) != PREFERRED_RESPONSE_KEYS:
        _error("DCC_LINEAR_ASSEMBLY_SHAPE_INVALID", "The assembled response has the wrong preferred top-level keys.")
    expected_acquisition_keys = PREFERRED_ACQUISITION_KEYS | ({"trained_choices"} if isinstance(creation_training_contract, Mapping) else set())
    from character_creation.constructed_arts.explicit_forging import concepts_for_design_ids, has_explicit_forging_contract, validate_required_design_selection
    validate_required_design_selection(delegated_envelope, state.bounded.get("forged_design_ids") or [], complete=True, request=request)
    if has_explicit_forging_contract(delegated_envelope):
        if state.bounded.get("forged_design_done") is not True:
            _error("DCC_LINEAR_FORGED_DESIGN_INCOMPLETE", "The sealed Forge selection step is unfinished.")
        response["acquisition_intent"]["forged_technique_concepts"] = concepts_for_design_ids(state.bounded.get("forged_design_ids") or [])
        expected_acquisition_keys = expected_acquisition_keys | {"forged_technique_concepts"}
    starting_kit = state.bounded.get("starting_kit")
    if isinstance(starting_kit, Mapping) and starting_kit.get("path_option"):
        response["acquisition_intent"]["starting_kit"] = {
            "path_option": starting_kit["path_option"],
            "picks": dict(sorted(dict(starting_kit.get("picks") or {}).items())),
        }
        from .linear_menus import owner_kit_plan

        plan = owner_kit_plan(request, delegated_envelope, state)
        if plan and plan.get("path_option") == starting_kit["path_option"] and plan.get("purchases"):
            response["acquisition_intent"]["starting_kit"]["purchases"] = list(plan["purchases"])
        weapon = state.bounded.get("treasure_weapon")
        if isinstance(weapon, Mapping) and weapon.get("material_id"):
            response["acquisition_intent"]["starting_kit"]["treasure_weapon"] = {
                "chassis_id": weapon["chassis_id"],
                "material_id": weapon["material_id"],
                "enchantment_ids": list(weapon.get("enchantment_ids") or []),
            }
        armor = state.bounded.get("treasure_armor")
        if isinstance(armor, Mapping) and armor.get("material_id"):
            response["acquisition_intent"]["starting_kit"]["treasure_armor"] = {
                "chassis_id": armor["chassis_id"],
                "material_id": armor["material_id"],
                "enhancement_ids": list(armor.get("enhancement_ids") or []),
            }
        wondrous = state.bounded.get("treasure_wondrous")
        consumables = state.bounded.get("treasure_consumables")
        if isinstance(wondrous, Mapping) or isinstance(consumables, Mapping):
            response["acquisition_intent"]["starting_kit"]["treasure_purchases"] = {
                "wondrous_ids": list((wondrous or {}).get("ids") or []),
                "consumable_ids": list((consumables or {}).get("ids") or []),
            }
        expected_acquisition_keys = expected_acquisition_keys | {"starting_kit"}
    if set(response["acquisition_intent"]) != expected_acquisition_keys:
        _error("DCC_LINEAR_ASSEMBLY_SHAPE_INVALID", "The assembled acquisition intent has the wrong keys.")
    if not set(response["bounded_choices"]).issubset(PREFERRED_BOUNDED_CHOICE_KEYS):
        _error("DCC_LINEAR_ASSEMBLY_SHAPE_INVALID", "The assembled bounded choices contain an unsupported field.")
    return canonical_json(response)


assemble_response = build_response
build_linear_response = build_response
assemble_linear_response = build_response


__all__ = [
    "RESPONSE_SCHEMA",
    "PREFERRED_RESPONSE_KEYS",
    "PREFERRED_ACQUISITION_KEYS",
    "PREFERRED_BOUNDED_CHOICE_KEYS",
    "LinearAssemblyError",
    "build_response",
    "assemble_response",
    "build_linear_response",
    "assemble_linear_response",
]
