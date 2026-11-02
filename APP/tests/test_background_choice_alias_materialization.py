from copy import deepcopy

import pytest

from app.core import FoundryError, sha256_json
from character_creation.response_materialization import (
    RESPONSE_SCHEMA,
    CanonicalSelectionIntent,
)
from character_creation.service import CharacterCreationExecutionService


BACKGROUND_ID = "tianxia.background.synthetic"
SPHERE_ID = "tianxia.background_sphere.synthetic"
TALENT_ID = "tianxia.background_talent.synthetic.hidden_cache"
SPHERE_ALIAS = "tianxia.background.sphere.synthetic"
TALENT_ALIAS = "tianxia.background.talent.synthetic.hidden_cache"


def _choice(choice_id: str, category: str) -> dict[str, str]:
    return {
        "choice_id": choice_id,
        "name": f"Synthetic {category}",
        "content_type": category,
    }


def _package(*, sphere_id: str = SPHERE_ID, talent_id: str = TALENT_ID, index: int = 0) -> dict[str, str | int]:
    return {
        "package_index": index,
        "sphere_record_id": f"source.{sphere_id}",
        "talent_record_id": f"source.{talent_id}",
        "background_sphere_choice_id": sphere_id,
        "background_talent_choice_id": talent_id,
    }


def _envelope() -> dict:
    return {
        "allowed_choice_ids_by_slot": {
            "background_choice": [BACKGROUND_ID],
            "background_sphere_choice": [SPHERE_ID],
            "background_talent_choice": [TALENT_ID],
        },
        "choices_by_slot": {
            "background_choice": {BACKGROUND_ID: _choice(BACKGROUND_ID, "background")},
            "background_sphere_choice": {SPHERE_ID: _choice(SPHERE_ID, "sphere")},
            "background_talent_choice": {TALENT_ID: _choice(TALENT_ID, "talent")},
        },
        "typed_choice_authority_by_slot": {
            "background_choice": {
                "background_package_linkage": {
                    BACKGROUND_ID: [_package()],
                },
            },
        },
    }


def test_unique_dotted_background_alias_is_rebound_to_frozen_choice_and_rehashed() -> None:
    envelope = _envelope()
    assert CharacterCreationExecutionService._canonicalize_frozen_background_choice_id(
        envelope,
        "background_sphere_choice",
        SPHERE_ALIAS,
        background_id=BACKGROUND_ID,
    ) == SPHERE_ID
    assert CharacterCreationExecutionService._canonicalize_frozen_background_choice_id(
        envelope,
        "background_talent_choice",
        TALENT_ALIAS,
        background_id=BACKGROUND_ID,
    ) == TALENT_ID

    document = {
        "schema": "TianxiaFoundry.DelegatedSelectionIntent.v1",
        "selected_by_slot": {
            "background_choice": [BACKGROUND_ID],
            "background_sphere_choice": [SPHERE_ALIAS],
            "background_talent_choice": [TALENT_ALIAS],
        },
        "intent_sha256": "provider-bound-before-server-repair",
    }
    original = deepcopy(document)
    canonical = CharacterCreationExecutionService._canonicalize_frozen_background_intent(
        CanonicalSelectionIntent.from_document(document),
        envelope,
    )
    canonical_document = canonical.as_dict()
    assert canonical_document["selected_by_slot"]["background_sphere_choice"] == [SPHERE_ID]
    assert canonical_document["selected_by_slot"]["background_talent_choice"] == [TALENT_ID]
    unsigned = deepcopy(canonical_document)
    intent_hash = unsigned.pop("intent_sha256")
    assert intent_hash == sha256_json(unsigned)
    assert document == original


def test_normalization_seals_canonical_background_ids_without_mutating_response_plan() -> None:
    envelope = _envelope()
    request_sha256 = "r" * 64
    plan = {
        "schema": RESPONSE_SCHEMA,
        "request_sha256": request_sha256,
        "selection_intent": {
            "by_slot": {
                "background_choice": [BACKGROUND_ID],
                "background_sphere_choice": [SPHERE_ALIAS],
                "background_talent_choice": [TALENT_ALIAS],
            },
        },
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [],
        },
        "bounded_choices": {},
        "owner_descriptive_fields": {
            "identity": {"name": "Synthetic Alias Test"},
            "concept": "A public-safe alias fixture.",
        },
        "stage1_response": {},
    }
    original_plan = deepcopy(plan)
    project = {
        "project_id": "project.synthetic-background-alias",
        "revision": 3,
        "content_lock": {"lock_hash": "l" * 64},
        "user_locks": [{"field": "target_cl", "value": 1}],
    }
    service = object.__new__(CharacterCreationExecutionService)
    service._project = lambda _project_id: deepcopy(project)
    service._server_materialized_stage2_proposal = lambda run, current_project, intent, normalized: None
    run = {
        "project_id": project["project_id"],
        "request": {
            "request_sha256": request_sha256,
            "delegated_choice_envelope": envelope,
        },
    }

    normalized, intent, stage2 = service._normalize_and_materialize_response(run, plan)

    assert stage2 is None
    assert intent is not None
    assert intent.as_dict()["selected_by_slot"]["background_sphere_choice"] == [SPHERE_ID]
    assert intent.as_dict()["selected_by_slot"]["background_talent_choice"] == [TALENT_ID]
    assert normalized["canonical_selection_intent"] == intent.as_dict()
    assert plan == original_plan
    assert plan["selection_intent"]["by_slot"]["background_sphere_choice"] == [SPHERE_ALIAS]


def test_background_alias_is_rejected_when_canonical_choice_is_not_offered() -> None:
    envelope = _envelope()
    envelope["allowed_choice_ids_by_slot"]["background_sphere_choice"] = []
    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._canonicalize_frozen_background_choice_id(
            envelope,
            "background_sphere_choice",
            SPHERE_ALIAS,
            background_id=BACKGROUND_ID,
        )
    assert raised.value.code == "CG1_DELEGATED_BACKGROUND_ALIAS_UNPROVEN"


def test_unallowed_alias_row_is_not_reinterpreted_as_a_canonical_choice() -> None:
    envelope = _envelope()
    envelope["choices_by_slot"]["background_sphere_choice"][SPHERE_ALIAS] = _choice(
        SPHERE_ALIAS,
        "sphere",
    )
    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._canonicalize_frozen_background_choice_id(
            envelope,
            "background_sphere_choice",
            SPHERE_ALIAS,
            background_id=BACKGROUND_ID,
        )
    assert raised.value.code == "CG1_DELEGATED_BACKGROUND_ALIAS_UNPROVEN"


def test_background_alias_is_rejected_when_package_proof_is_missing() -> None:
    envelope = _envelope()
    envelope["typed_choice_authority_by_slot"]["background_choice"]["background_package_linkage"] = {}
    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._canonicalize_frozen_background_choice_id(
            envelope,
            "background_sphere_choice",
            SPHERE_ALIAS,
            background_id=BACKGROUND_ID,
        )
    assert raised.value.code == "CG1_DELEGATED_BACKGROUND_ALIAS_UNPROVEN"


def test_background_alias_is_rejected_when_frozen_proof_is_ambiguous() -> None:
    envelope = _envelope()
    second_sphere = "tianxia.background_sphere.other"
    shared_alias = "tianxia.background.sphere.shared"
    envelope["allowed_choice_ids_by_slot"]["background_sphere_choice"].append(second_sphere)
    envelope["choices_by_slot"]["background_sphere_choice"][SPHERE_ID]["aliases"] = [shared_alias]
    envelope["choices_by_slot"]["background_sphere_choice"][second_sphere] = {
        **_choice(second_sphere, "sphere"),
        "aliases": [shared_alias],
    }
    envelope["typed_choice_authority_by_slot"]["background_choice"]["background_package_linkage"][BACKGROUND_ID].append(
        _package(sphere_id=second_sphere, index=1)
    )
    with pytest.raises(FoundryError) as raised:
        CharacterCreationExecutionService._canonicalize_frozen_background_choice_id(
            envelope,
            "background_sphere_choice",
            shared_alias,
            background_id=BACKGROUND_ID,
        )
    assert raised.value.code == "CG1_DELEGATED_BACKGROUND_ALIAS_AMBIGUOUS"
    assert raised.value.details["candidates"] == sorted([SPHERE_ID, second_sphere])
