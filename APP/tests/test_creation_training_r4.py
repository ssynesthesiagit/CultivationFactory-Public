"""Focused provider-free checks for the R4 creation-training lane."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.core import FoundryError, canonical_json, sha256_json
from character_builder import CharacterBuilderService
from character_creation.response_materialization import CanonicalSelectionIntent, RESPONSE_SCHEMA
from character_creation.service import CharacterCreationExecutionService
from character_creation.creative_controller.linear_assembly import build_response
from character_creation.creative_controller.linear_menus import (
    CommittedState,
    LinearMenuError,
    _background_package_acquisitions,
    _creation_training_kind_allowed,
    build_creation_training_menu,
    build_ordinary_talent_menu,
    build_sphere_free_talent_pair_menu,
)
from character_creation.creative_controller.linear_walk import commit_option, _apply_owner_locks
from character_creation.delegated_choice_authority import (
    _validate_semantic_acquisition_intent,
    build_delegated_choice_envelope,
)
from creation_training_authority import (
    CREATION_TRAINING_CONTRACT_SCHEMA,
    CREATION_TRAINING_CHANNEL_BY_KIND,
    CREATION_TRAINING_MAX_PER_CL,
    CREATION_TRAINING_SPHERE_KIND,
    CREATION_TRAINING_TALENT_KIND,
    SealedBackgroundSphereResolutionError,
    canonical_background_package_ids,
    build_creation_training_contract,
    canonical_background_sphere_ids,
    canonical_selected_background_sphere_ids,
    creation_context_ids,
    constructed_outcome,
    constructed_source,
    validate_creation_training_contract,
    validate_trained_choice_shape,
)
from contracts.canonical import ZERO_HASH
from project_store.service import ProjectStore
from stage1.service import Stage1ClipboardService
from stage2.service import (
    RulesCausalStage2Service,
    _state,
)
from tests.test_rec1_p1cr5_owner_authority import _private_scope


def _route(
    record_id: str,
    *,
    content_type: str,
    choice_type: str,
    owning_sphere_id: str | None = None,
    minimum_cl: int = 1,
    prerequisites: list[dict] | None = None,
    bonus_talent_eligible: bool = True,
) -> dict:
    return {
        "record_id": record_id,
        "content_type": content_type,
        "choice_type": choice_type,
        "source_route": "published_legal_teaching_route" if content_type == "sphere" else "recorded_self_training",
        "source_record_id": owning_sphere_id or record_id,
        "source_provenance": {
            "record_id": record_id,
            "source_id": f"source.{record_id}",
            "source_hash": "a" * 64,
            "source_anchor": f"rules:{record_id}",
            "source_path": "TIANXIA_RULES_AS_WRITTEN.md",
        },
        "owning_sphere_id": owning_sphere_id,
        "bonus_talent_eligible": bonus_talent_eligible,
        "minimum_cl": minimum_cl,
        "realm_rules": {},
        "prerequisites": prerequisites or [],
        "incompatibilities": [],
        "access_category": "Open",
    }


def _contract(*, target_cl: int = 3, required: int | None = None, routes: dict | None = None) -> dict:
    return {
        "schema": CREATION_TRAINING_CONTRACT_SCHEMA,
        "version": 1,
        "target_cl": target_cl,
        "power_band": "rival/boss" if required == 3 else "standard",
        "max_choices_per_cl": CREATION_TRAINING_MAX_PER_CL,
        "required_choices_per_cl": required,
        "bonus_rule": "new_sphere_one_same_sphere_talent_without_slot_cost",
        "construction_mode": "published_route_success_without_rolls",
        "records": routes or {},
        "rule_ids": ["Q06", "RAW-079", "RAW-081"],
    }


def _menu_fixture(*, target_cl: int = 3, required: int | None = None) -> tuple[dict, dict, dict]:
    routes = {
        "sphere.a": _route("sphere.a", content_type="sphere", choice_type="new_sphere"),
        "sphere.z": _route("sphere.z", content_type="sphere", choice_type="new_sphere"),
        "sphere.future": _route("sphere.future", content_type="sphere", choice_type="new_sphere", minimum_cl=5),
        "talent.a": _route("talent.a", content_type="talent", choice_type="known_sphere_talent", owning_sphere_id="sphere.a"),
        "talent.zbonus": _route("talent.zbonus", content_type="talent", choice_type="known_sphere_talent", owning_sphere_id="sphere.z"),
        "talent.chain": _route(
            "talent.chain",
            content_type="talent",
            choice_type="known_sphere_talent",
            owning_sphere_id="sphere.z",
            prerequisites=[{"operator": "requires", "target_id": "talent.zbonus"}],
        ),
        "talent.future": _route("talent.future", content_type="talent", choice_type="known_sphere_talent", owning_sphere_id="sphere.z", minimum_cl=5),
    }
    rows = {
        record_id: {"choice_id": record_id, "name": record_id}
        for record_id in routes
    }
    typed_authority = {
        "sphere_priorities": {
            "stage2_authority_by_choice": {
                record_id: {
                    "authority_complete": True,
                    "allowed_kinds": [CREATION_TRAINING_SPHERE_KIND],
                    "allowed_channels": ["creation-training-published-sphere"],
                }
                for record_id in routes
                if record_id.startswith("sphere.")
            }
        },
        "advancement_skeleton": {
            "stage2_authority_by_choice": {
                record_id: {
                    "authority_complete": True,
                    "allowed_kinds": [
                        CREATION_TRAINING_TALENT_KIND,
                        *(["new_sphere_bonus_talent_acquisition"] if record_id == "talent.zbonus" else []),
                    ],
                    "allowed_channels": [
                        "creation-training-known-sphere-talent",
                        *(["new-sphere-bonus"] if record_id == "talent.zbonus" else []),
                    ],
                }
                for record_id in routes
                if record_id.startswith("talent.")
            }
        },
    }
    envelope = {
        "creation_training_contract": _contract(target_cl=target_cl, required=required, routes=routes),
        "choices_by_slot": {
            "sphere_priorities": {key: rows[key] for key in routes if key.startswith("sphere.")},
            "advancement_skeleton": {key: rows[key] for key in routes if key.startswith("talent.")},
        },
        "allowed_choices_by_slot": {
            "sphere_priorities": [key for key in routes if key.startswith("sphere.")],
            "advancement_skeleton": [key for key in routes if key.startswith("talent.")],
        },
        "typed_choice_authority_by_slot": typed_authority,
    }
    request = {
        "request_sha256": "b" * 64,
        "owner_planning_preferences": {
            "sphere_priority_ids": ["sphere.z"],
            "talent_priority_ids": ["talent.chain"],
        },
    }
    return request, envelope, routes


def _row(route: dict, *, cl: int, slot: int, bonus_talent_id: str | None = None) -> dict:
    choice_type = route["choice_type"]
    result = {
        "cl": cl,
        "slot": slot,
        "choice_type": choice_type,
        "record_id": route["record_id"],
        "source": constructed_source(route, choice_type=choice_type),
        "outcome": constructed_outcome(),
    }
    if bonus_talent_id is not None:
        result["bonus_talent_id"] = bonus_talent_id
    return result


def _semantic_plan(rows: list[dict], *, pairs: list[dict] | None = None) -> dict:
    return {
        "canonical_selection_intent": {
            "acquisition_intent": {
                "sphere_free_talent_pairs": pairs or [],
                "ordinary_talent_ids": [],
                "insight_occurrences": [],
                "trained_choices": rows,
            }
        }
    }


def test_preferred_parser_accepts_training_rows_only_when_contract_is_active() -> None:
    route = _route("sphere.training", content_type="sphere", choice_type="new_sphere")
    payload = {
        "schema": RESPONSE_SCHEMA,
        "request_sha256": "a" * 64,
        "selection_intent": {"by_slot": {}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [],
            "ordinary_talent_ids": [],
            "insight_occurrences": [],
            "trained_choices": [_row(route, cl=1, slot=1, bonus_talent_id="talent.training")],
        },
        "bounded_choices": {},
        "owner_descriptive_fields": {"identity": {"name": "R4 parser"}},
    }
    response_text = canonical_json(payload)

    parsed, _raw = CharacterCreationExecutionService._parse_plan(
        response_text,
        expected_request_sha256="a" * 64,
        creation_training_active=True,
    )
    assert parsed["acquisition_intent"]["trained_choices"] == payload["acquisition_intent"]["trained_choices"]

    with pytest.raises(FoundryError) as error:
        CharacterCreationExecutionService._parse_plan(
            response_text,
            expected_request_sha256="a" * 64,
        )
    assert getattr(error.value, "code", None) == "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID"

    schema_less = deepcopy(payload)
    schema_less.pop("schema")
    inferred, _raw = CharacterCreationExecutionService._parse_plan(
        canonical_json(schema_less),
        expected_request_sha256="a" * 64,
        creation_training_active=True,
    )
    assert inferred["schema"] == RESPONSE_SCHEMA


def _validation_envelope(routes: dict, *, required: int | None = None, target_cl: int = 3) -> dict:
    choices = {}
    for record_id, route in routes.items():
        choices.setdefault("sphere_priorities" if route["choice_type"] == "new_sphere" else "advancement_skeleton", {})[record_id] = {
            "choice_id": record_id,
            "name": record_id,
            "minimum_cl": route.get("minimum_cl"),
            "prerequisites": deepcopy(route.get("prerequisites", [])),
            "incompatibilities": deepcopy(route.get("incompatibilities", [])),
        }
    return {
        "creation_training_contract": _contract(target_cl=target_cl, required=required, routes=routes),
        "choices_by_slot": choices,
        "allowed_choice_ids_by_slot": {
            "sphere_priorities": [rid for rid, route in routes.items() if route["choice_type"] == "new_sphere"],
            "advancement_skeleton": [rid for rid, route in routes.items() if route["choice_type"] == "known_sphere_talent"],
        },
        "owner_locks": {"by_slot": {}},
    }


def test_menu_filters_future_and_causal_choices_before_priority_ordering() -> None:
    request, envelope, routes = _menu_fixture(target_cl=3)
    menu = build_creation_training_menu(request, envelope, CommittedState.empty(), cl=1, slot=1)
    assert menu is not None
    assert menu.options[0].choice_ids == ("sphere.z", "talent.zbonus")
    offered = {value for option in menu.options for value in option.choice_ids}
    assert "sphere.future" not in offered
    assert "talent.future" not in offered
    assert "talent.chain" not in offered

    state = commit_option(menu, menu.options[0].option_id, CommittedState.empty())
    second = build_creation_training_menu(request, envelope, state, cl=1, slot=2)
    assert second is not None
    assert second.options[0].choice_ids == ("talent.chain",)
    assert "talent.future" not in {value for option in second.options for value in option.choice_ids}

    stop = next(option for option in second.options if option.kind == "none")
    stopped = commit_option(second, stop.option_id, state)
    assert build_creation_training_menu(request, envelope, stopped, cl=1, slot=3) is None
    assert routes["sphere.z"]["choice_type"] == "new_sphere"


def test_acquisition_menus_exclude_training_and_retain_trained_prerequisites() -> None:
    talent_ids = ("talent.bonus", "talent.trained", "talent.chain", "talent.future", "talent.available")
    rows = {
        talent_id: {
            "choice_id": talent_id,
            "name": talent_id,
            "content_type": "talent",
            "prerequisites": (
                [{"operator": "requires", "target_id": "talent.bonus"}]
                if talent_id == "talent.chain"
                else []
            ),
        }
        for talent_id in talent_ids
    }
    rows["talent.future"]["availability"] = {"minimum_cl": 5}
    authority = {
        talent_id: {
            "authority_complete": True,
            "allowed_channels": ["level-choice"],
            "allowed_kinds": ["level_talent_acquisition"],
            "minimum_cl": 5 if talent_id == "talent.future" else 1,
            "sphere_id": "sphere.z",
        }
        for talent_id in talent_ids
    }
    request = {"request_sha256": "c" * 64}
    envelope = {
        "ordinary_talent_count": 1,
        "free_sphere_talent_grant_count": 1,
        "presented_legal_first_cycle_pairs": [
            {"sphere_id": "sphere.z", "talent_id": talent_id}
            for talent_id in ("talent.bonus", "talent.trained", "talent.chain", "talent.available")
        ],
        "choices_by_slot": {"advancement_skeleton": rows},
        "allowed_choice_ids_by_slot": {"advancement_skeleton": list(talent_ids)},
        "typed_choice_authority_by_slot": {
            "advancement_skeleton": {"stage2_authority_by_choice": authority},
        },
    }

    state = CommittedState.empty().with_trained_choice(
        {"cl": 1, "slot": 1, "choice_type": "new_sphere", "record_id": "sphere.z", "bonus_talent_id": "talent.bonus"}
    )
    state = state.with_trained_choice(
        {"cl": 1, "slot": 2, "choice_type": "known_sphere_talent", "record_id": "talent.trained"}
    )
    ordinary = build_ordinary_talent_menu(request, envelope, state, cl=1)
    assert ordinary is not None
    offered = {value for option in ordinary.options for value in option.choice_ids}
    assert "talent.bonus" not in offered
    assert "talent.trained" not in offered
    assert "talent.chain" in offered
    assert "talent.future" not in offered

    ordinary_option = next(option for option in ordinary.options if option.choice_ids == ("talent.chain",))
    state = commit_option(ordinary, ordinary_option.option_id, state)
    pair_menu = build_sphere_free_talent_pair_menu(request, envelope, state, pair_index=1)
    assert pair_menu is not None
    assert [option.choice_ids for option in pair_menu.options] == [("sphere.z", "talent.available")]
    with pytest.raises(LinearMenuError):
        state.with_pair("sphere.z", "talent.bonus")


def test_state_enforces_three_slot_cap_and_consumed_bonus() -> None:
    state = CommittedState.empty()
    state = state.with_trained_choice({"cl": 1, "slot": 1, "choice_type": "new_sphere", "record_id": "sphere.a", "bonus_talent_id": "talent.a"})
    with pytest.raises(LinearMenuError):
        state.with_trained_choice({"cl": 1, "slot": 2, "choice_type": "new_sphere", "record_id": "sphere.z", "bonus_talent_id": "talent.a"})
    state = state.with_trained_choice({"cl": 1, "slot": 2, "choice_type": "known_sphere_talent", "record_id": "talent.chain"})
    state = state.with_trained_choice({"cl": 1, "slot": 3, "choice_type": "known_sphere_talent", "record_id": "talent.other"})
    with pytest.raises(LinearMenuError):
        state.with_trained_choice({"cl": 1, "slot": 4, "choice_type": "known_sphere_talent", "record_id": "talent.fourth"})


def test_delegated_creation_validation_rejects_forgery_future_and_post_creation_rows() -> None:
    routes = {
        "sphere.a": _route("sphere.a", content_type="sphere", choice_type="new_sphere"),
        "talent.a": _route("talent.a", content_type="talent", choice_type="known_sphere_talent", owning_sphere_id="sphere.a"),
        "talent.future": _route("talent.future", content_type="talent", choice_type="known_sphere_talent", owning_sphere_id="sphere.a", minimum_cl=5),
    }
    envelope = _validation_envelope(routes, target_cl=3)
    valid = _row(routes["sphere.a"], cl=1, slot=1, bonus_talent_id="talent.a")
    _validate_semantic_acquisition_intent(envelope, _semantic_plan([valid]), {})

    forged = deepcopy(valid)
    forged["source"]["mode"] = "observed_play"
    with pytest.raises(Exception) as exc:
        _validate_semantic_acquisition_intent(envelope, _semantic_plan([forged]), {})
    assert exc.value.code == "CG1_PREFERRED_RESPONSE_TRAINED_CHOICE_INVALID"

    missing_bonus = deepcopy(valid)
    missing_bonus["bonus_talent_id"] = "talent.missing"
    with pytest.raises(Exception) as exc:
        _validate_semantic_acquisition_intent(envelope, _semantic_plan([missing_bonus]), {})
    assert exc.value.code == "CG1_NEW_SPHERE_BONUS_INVALID"

    future = _row(routes["talent.future"], cl=1, slot=1)
    with pytest.raises(Exception) as exc:
        _validate_semantic_acquisition_intent(envelope, _semantic_plan([future]), {})
    assert exc.value.code == "CG1_TRAINED_CHOICE_ILLEGAL"

    after_creation = _row(routes["sphere.a"], cl=4, slot=1, bonus_talent_id="talent.a")
    with pytest.raises(Exception) as exc:
        _validate_semantic_acquisition_intent(envelope, _semantic_plan([after_creation]), {})
    assert exc.value.code == "CG1_TRAINED_CHOICE_CL_INVALID"


def test_training_uses_canonical_background_sphere_identity_and_rejects_alias_reuse() -> None:
    sphere_id = "tianxia.sphere.spirit_companions"
    background_choice_id = "tianxia.background.spirit_companions"
    background_id = "tianxia.background_sphere.spirit_companions"
    talent_id = "tianxia.talent.spirit_companions.court_of_small_spirits"
    bonus_id = "tianxia.talent.spirit_companions.bonus"
    routes = {
        sphere_id: _route(sphere_id, content_type="sphere", choice_type="new_sphere"),
        talent_id: _route(talent_id, content_type="talent", choice_type="known_sphere_talent", owning_sphere_id=sphere_id),
        bonus_id: _route(bonus_id, content_type="talent", choice_type="known_sphere_talent", owning_sphere_id=sphere_id),
    }
    envelope = _validation_envelope(routes, target_cl=1)
    envelope["choices_by_slot"]["background_choice"] = {
        background_choice_id: {
            "choice_id": background_choice_id,
            "name": "Spirit Companions Background",
        },
    }
    envelope["choices_by_slot"]["background_sphere_choice"] = {
        background_id: {
            "choice_id": background_id,
            "name": "Spirit Companions",
            "canonical_sphere_id": sphere_id,
        },
    }
    envelope["choices_by_slot"]["sphere_priorities"][sphere_id] = {
        "choice_id": sphere_id,
        "name": "Spirit Companions",
    }
    envelope.setdefault("typed_choice_authority_by_slot", {})["background_choice"] = {
        "authority_contract": {
            "schema": "TianxiaFoundry.BackgroundTypedChoiceContract.v1",
            "background_package_linkage": {
                background_choice_id: [{
                    "background_sphere_choice_id": background_id,
                    "canonical_sphere_id": sphere_id,
                }]
            },
        },
    }
    selected = {
        "background_choice": [background_choice_id],
        "background_sphere_choice": [background_id],
    }
    valid = _row(routes[talent_id], cl=1, slot=1)
    _validate_semantic_acquisition_intent(envelope, _semantic_plan([valid]), selected)

    reused = _row(routes[sphere_id], cl=1, slot=1, bonus_talent_id=bonus_id)
    with pytest.raises(Exception) as exc:
        _validate_semantic_acquisition_intent(envelope, _semantic_plan([reused]), selected)
    assert exc.value.code == "CG1_DELEGATED_DUPLICATE_CHOICE"

    unknown_selected = {"background_sphere_choice": ["unknownSphere"]}
    with pytest.raises(Exception) as exc:
        _validate_semantic_acquisition_intent(envelope, _semantic_plan([valid]), unknown_selected)
    assert exc.value.code == "CG1_TRAINED_CHOICE_BACKGROUND_SPHERE_INVALID"

    assert canonical_background_sphere_ids(
        [background_id], envelope["choices_by_slot"]
    )[background_id] == sphere_id
    name_only = deepcopy(envelope["choices_by_slot"])
    name_only["background_sphere_choice"][background_id].pop("canonical_sphere_id")
    with pytest.raises(SealedBackgroundSphereResolutionError) as name_only_error:
        canonical_background_sphere_ids([background_id], name_only)
    assert name_only_error.value.reason == "background_canonical_relation_missing"

    bare_canonical = deepcopy(envelope["choices_by_slot"])
    bare_canonical["background_sphere_choice"] = {
        sphere_id: {"choice_id": sphere_id, "name": "Spirit Companions"},
    }
    with pytest.raises(SealedBackgroundSphereResolutionError) as bare_canonical_error:
        canonical_background_sphere_ids([sphere_id], bare_canonical)
    assert bare_canonical_error.value.reason == "background_canonical_relation_missing"

    missing_relation = deepcopy(envelope["choices_by_slot"])
    missing_relation["background_sphere_choice"][background_id]["canonical_sphere_id"] = None
    with pytest.raises(SealedBackgroundSphereResolutionError) as missing_relation_error:
        canonical_background_sphere_ids([background_id], missing_relation)
    assert missing_relation_error.value.reason == "background_canonical_relation_invalid"

    invalid_relation = deepcopy(envelope["choices_by_slot"])
    invalid_relation["background_sphere_choice"][background_id]["canonical_sphere_id"] = "tianxia.sphere.not-offered"
    with pytest.raises(SealedBackgroundSphereResolutionError) as invalid_relation_error:
        canonical_background_sphere_ids([background_id], invalid_relation)
    assert invalid_relation_error.value.reason == "background_canonical_relation_invalid"

    ambiguous = deepcopy(name_only)
    ambiguous["sphere_priorities"]["tianxia.sphere.other"] = {
        "choice_id": "tianxia.sphere.other",
        "name": "Spirit Companions",
    }
    with pytest.raises(SealedBackgroundSphereResolutionError):
        canonical_background_sphere_ids([background_id], ambiguous)

    without_selected_background_row = deepcopy(envelope["choices_by_slot"])
    without_selected_background_row["background_sphere_choice"] = {}
    with pytest.raises(SealedBackgroundSphereResolutionError) as missing_row:
        canonical_background_sphere_ids([sphere_id], without_selected_background_row)
    assert missing_row.value.reason == "background_choice_unresolved"


def test_selected_background_package_adds_canonical_talent_for_prerequisites_and_duplicates() -> None:
    background_id = "tianxia.background.abandoned_orphan"
    background_sphere_id = "tianxia.background_sphere.scoundrel"
    canonical_sphere_id = "tianxia.sphere.scoundrel"
    background_talent_id = "tianxia.background_talent.scoundrel.hidden_tool_cache"
    canonical_talent_id = "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE"
    other_background_sphere_id = "tianxia.background_sphere.other"
    other_background_talent_id = "tianxia.background_talent.other"
    other_canonical_sphere_id = "tianxia.sphere.other"
    other_canonical_talent_id = "TAL_OTHER_BACKGROUND"
    dependent_id = "talent.after-background"
    cross_dependent_id = "talent.after-unselected-background-package"
    canonical_route = _route(
        canonical_talent_id,
        content_type="talent",
        choice_type="known_sphere_talent",
        owning_sphere_id=canonical_sphere_id,
    )
    dependent_route = _route(
        dependent_id,
        content_type="talent",
        choice_type="known_sphere_talent",
        owning_sphere_id=canonical_sphere_id,
        prerequisites=[{"operator": "requires", "target_id": canonical_talent_id}],
    )
    cross_dependent_route = _route(
        cross_dependent_id,
        content_type="talent",
        choice_type="known_sphere_talent",
        owning_sphere_id=canonical_sphere_id,
        prerequisites=[{"operator": "requires", "target_id": other_canonical_talent_id}],
    )
    routes = {
        canonical_talent_id: canonical_route,
        dependent_id: dependent_route,
        cross_dependent_id: cross_dependent_route,
    }
    envelope = _validation_envelope(routes, target_cl=2)
    envelope["choices_by_slot"].update({
        "background_choice": {background_id: {"choice_id": background_id, "name": "Abandoned Orphan"}},
        "background_sphere_choice": {
            background_sphere_id: {
                "choice_id": background_sphere_id,
                "name": "Scoundrel",
                "canonical_sphere_id": canonical_sphere_id,
            },
            other_background_sphere_id: {
                "choice_id": other_background_sphere_id,
                "name": "Other Sphere",
                "canonical_sphere_id": other_canonical_sphere_id,
            },
        },
        "background_talent_choice": {
            background_talent_id: {"choice_id": background_talent_id, "name": "Hidden Tool Cache"},
            other_background_talent_id: {"choice_id": other_background_talent_id, "name": "Other Background Talent"},
        },
        "sphere_priorities": {
            canonical_sphere_id: {"choice_id": canonical_sphere_id, "name": "Scoundrel"},
            other_canonical_sphere_id: {"choice_id": other_canonical_sphere_id, "name": "Other Sphere"},
        },
    })
    envelope.setdefault("typed_choice_authority_by_slot", {})["background_choice"] = {
        "authority_contract": {
            "schema": "TianxiaFoundry.BackgroundTypedChoiceContract.v1",
            "background_package_linkage": {
                background_id: [{
                    "background_sphere_choice_id": background_sphere_id,
                    "background_talent_choice_id": background_talent_id,
                    "canonical_sphere_id": canonical_sphere_id,
                    "sphere_record_id": canonical_sphere_id,
                    "talent_record_id": canonical_talent_id,
                }]
            },
        },
    }
    envelope["typed_choice_authority_by_slot"]["background_choice"]["authority_contract"][
        "background_package_linkage"
    ][background_id].append({
        "background_sphere_choice_id": other_background_sphere_id,
        "background_talent_choice_id": other_background_talent_id,
        "canonical_sphere_id": other_canonical_sphere_id,
        "sphere_record_id": other_canonical_sphere_id,
        "talent_record_id": other_canonical_talent_id,
    })
    selected = {
        "background_choice": [background_id],
        "background_sphere_choice": [background_sphere_id],
        "background_talent_choice": [background_talent_id],
    }

    assert canonical_background_package_ids(
        selected,
        envelope["typed_choice_authority_by_slot"],
    ) == ({canonical_sphere_id}, {canonical_talent_id})
    assert canonical_background_package_ids(
        {
            "background_sphere_choice": [background_sphere_id],
            "background_talent_choice": [background_talent_id],
        },
        envelope["typed_choice_authority_by_slot"],
    ) == (set(), set())
    assert creation_context_ids(
        selected,
        envelope["choices_by_slot"],
        envelope["typed_choice_authority_by_slot"],
        current_cl=1,
    ) >= {background_id, canonical_sphere_id, canonical_talent_id}
    assert canonical_sphere_id not in creation_context_ids(
        {
            "background_sphere_choice": [background_sphere_id],
            "background_talent_choice": [background_talent_id],
        },
        envelope["choices_by_slot"],
        envelope["typed_choice_authority_by_slot"],
        current_cl=1,
    )
    assert creation_context_ids(
        {
            "background_choice": [background_id],
            "background_talent_choice": [background_talent_id],
        },
        envelope["choices_by_slot"],
        envelope["typed_choice_authority_by_slot"],
        current_cl=1,
    ).isdisjoint({canonical_sphere_id, canonical_talent_id})
    absent_linkage = deepcopy(envelope["typed_choice_authority_by_slot"])
    absent_linkage["background_choice"]["authority_contract"].pop("background_package_linkage")
    with pytest.raises(SealedBackgroundSphereResolutionError) as absent_linkage_error:
        canonical_selected_background_sphere_ids(
            selected,
            envelope["choices_by_slot"],
            absent_linkage,
        )
    assert absent_linkage_error.value.reason == "background_package_relation_missing"
    wrong_background = deepcopy(selected)
    wrong_background["background_choice"] = ["tianxia.background.other"]
    with pytest.raises(SealedBackgroundSphereResolutionError) as wrong_background_error:
        canonical_selected_background_sphere_ids(
            wrong_background,
            envelope["choices_by_slot"],
            envelope["typed_choice_authority_by_slot"],
        )
    assert wrong_background_error.value.reason == "background_package_relation_mismatch"
    no_sphere = deepcopy(selected)
    no_sphere["background_sphere_choice"] = []
    assert canonical_selected_background_sphere_ids(
        no_sphere,
        envelope["choices_by_slot"],
        envelope["typed_choice_authority_by_slot"],
    ) == {}
    cross_package_selected = {
        "background_choice": [background_id],
        "background_sphere_choice": [background_sphere_id],
        "background_talent_choice": [other_background_talent_id],
    }
    assert canonical_selected_background_sphere_ids(
        cross_package_selected,
        envelope["choices_by_slot"],
        envelope["typed_choice_authority_by_slot"],
    ) == {background_sphere_id: canonical_sphere_id}
    assert canonical_background_package_ids(
        cross_package_selected,
        envelope["typed_choice_authority_by_slot"],
    ) == ({canonical_sphere_id}, set())
    assert other_canonical_talent_id not in creation_context_ids(
        cross_package_selected,
        envelope["choices_by_slot"],
        envelope["typed_choice_authority_by_slot"],
        current_cl=1,
    )
    cross_state = CommittedState.empty()
    for slot_id, values in cross_package_selected.items():
        cross_state = cross_state.with_choice(slot_id, values)
    assert _background_package_acquisitions({}, envelope, cross_state) == (
        {canonical_sphere_id},
        set(),
    )
    with pytest.raises(Exception) as cross_semantic_error:
        _validate_semantic_acquisition_intent(
            envelope,
            _semantic_plan([_row(cross_dependent_route, cl=2, slot=1)]),
            cross_package_selected,
        )
    assert cross_semantic_error.value.code == "CG1_TRAINED_CHOICE_ILLEGAL"
    mismatched_authority = deepcopy(envelope["typed_choice_authority_by_slot"])
    mismatched_authority["background_choice"]["authority_contract"]["background_package_linkage"][background_id][0][
        "canonical_sphere_id"
    ] = "tianxia.sphere.other"
    with pytest.raises(SealedBackgroundSphereResolutionError) as mismatch_error:
        canonical_selected_background_sphere_ids(
            selected,
            envelope["choices_by_slot"],
            mismatched_authority,
        )
    assert mismatch_error.value.reason == "background_package_relation_mismatch"
    _validate_semantic_acquisition_intent(
        envelope,
        _semantic_plan([_row(dependent_route, cl=2, slot=1)]),
        selected,
    )

    with pytest.raises(Exception) as exc:
        _validate_semantic_acquisition_intent(
            envelope,
            _semantic_plan([_row(canonical_route, cl=1, slot=1)]),
            selected,
        )
    assert exc.value.code == "CG1_DELEGATED_DUPLICATE_CHOICE"


def test_fresh_background_relation_null_survives_delegated_projection() -> None:
    background_id = "tianxia.background_sphere.unresolved"
    stage1_row = {
        "choice_id": background_id,
        "name": "Unresolved Background Sphere",
        "description": "An authenticated row whose canonical relation is unavailable.",
        "content_type": "background_sphere",
        "canonical_sphere_id": None,
    }
    prompt = {
        "prompt_id": "stage1.prompt.relation-marker",
        "envelope": {
            "decision_slots": [{
                "slot_id": "background_sphere_choice",
                "min_selections": 1,
                "max_selections": 1,
                "allow_none": False,
                "choices": [stage1_row],
            }],
        },
    }
    project = {
        "project_id": "relation-marker-project",
        "revision": 0,
        "content_lock": {"catalog_build_id": "catalog", "lock_hash": "lock"},
        "user_locks": [{"field": "target_cl", "value": 1}],
    }
    delegated = build_delegated_choice_envelope(
        project,
        prompt,
        execution_mode="MANUAL_CHAT",
        idempotency_key="relation-marker",
    )
    assert delegated is not None
    projected = delegated["choices_by_slot"]["background_sphere_choice"][background_id]
    assert "canonical_sphere_id" in projected
    assert projected["canonical_sphere_id"] is None
    with pytest.raises(SealedBackgroundSphereResolutionError) as exc:
        canonical_background_sphere_ids(
            [background_id], delegated["choices_by_slot"]
        )
    assert exc.value.reason == "background_canonical_relation_invalid"


def test_boss_requires_three_rows_and_free_grant_stays_separate() -> None:
    routes: dict[str, dict] = {}
    rows: list[dict] = []
    for index in range(1, 4):
        sphere_id = f"sphere.{index}"
        talent_id = f"talent.{index}"
        routes[sphere_id] = _route(sphere_id, content_type="sphere", choice_type="new_sphere")
        routes[talent_id] = _route(talent_id, content_type="talent", choice_type="known_sphere_talent", owning_sphere_id=sphere_id)
        rows.append(_row(routes[sphere_id], cl=1, slot=index, bonus_talent_id=talent_id))
    envelope = _validation_envelope(routes, required=3, target_cl=1)
    _validate_semantic_acquisition_intent(envelope, _semantic_plan(rows), {})

    with pytest.raises(Exception) as exc:
        _validate_semantic_acquisition_intent(envelope, _semantic_plan(rows[:2]), {})
    assert exc.value.code == "CG1_TRAINED_CHOICE_REQUIRED_COUNT_UNMET"

    request = {
        "request_sha256": "c" * 64,
        "concept": "A constructed cultivator",
        "delegated_choice_envelope": {"creation_training_contract": envelope["creation_training_contract"]},
    }
    state = CommittedState.empty().with_identity("Tester", "Builder", "A constructed cultivator")
    for row in rows:
        state = state.with_trained_choice({key: row[key] for key in ("cl", "slot", "choice_type", "record_id", "bonus_talent_id")})
    state = state.with_pair("sphere.free", "talent.free")
    response = json.loads(build_response(request, state))
    assert response["acquisition_intent"]["sphere_free_talent_pairs"] == [{"sphere_id": "sphere.free", "talent_id": "talent.free"}]
    assert len(response["acquisition_intent"]["trained_choices"]) == 3
    assert "talent.free" not in {row["record_id"] for row in response["acquisition_intent"]["trained_choices"]}


def test_contract_and_row_shapes_are_closed_world() -> None:
    request, envelope, routes = _menu_fixture()
    assert validate_creation_training_contract(envelope["creation_training_contract"]) == []
    assert validate_trained_choice_shape(_row(routes["sphere.z"], cl=1, slot=1, bonus_talent_id="talent.zbonus")) == []
    malformed = _row(routes["sphere.z"], cl=1, slot=1, bonus_talent_id="talent.zbonus")
    malformed["dice"] = 20
    assert "extra_fields" in validate_trained_choice_shape(malformed)


def _authority_menu_fixture(
    *,
    choice_type: str,
    expected_kind: str,
    allowed: bool,
) -> tuple[dict, dict, CommittedState, str, tuple[str, ...]]:
    sphere_id = "sphere.training"
    talent_id = "talent.training"
    bonus_id = "talent.bonus"
    routes = {
        sphere_id: _route(sphere_id, content_type="sphere", choice_type="new_sphere"),
        talent_id: _route(talent_id, content_type="talent", choice_type="known_sphere_talent", owning_sphere_id=sphere_id),
        bonus_id: _route(bonus_id, content_type="talent", choice_type="known_sphere_talent", owning_sphere_id=sphere_id),
    }
    rows = {
        sphere_id: {"choice_id": sphere_id, "name": "Training Sphere", "content_type": "sphere", "acquisition_channels": ["sphere-acquisition"]},
        talent_id: {"choice_id": talent_id, "name": "Training Talent", "content_type": "talent", "acquisition_channels": ["ordinary-sphere-talent"]},
        bonus_id: {"choice_id": bonus_id, "name": "Bonus Talent", "content_type": "talent", "acquisition_channels": ["ordinary-sphere-talent"]},
    }
    sphere_kind = CREATION_TRAINING_SPHERE_KIND if choice_type == "new_sphere" and allowed else "background_sphere_acquisition"
    if choice_type == "bonus":
        sphere_kind = CREATION_TRAINING_SPHERE_KIND
    talent_kind = CREATION_TRAINING_TALENT_KIND if choice_type == "known_sphere_talent" and allowed else "background_talent_acquisition"
    bonus_kind = "new_sphere_bonus_talent_acquisition" if choice_type in {"new_sphere", "bonus"} and allowed else "background_talent_acquisition"
    typed = {
        "sphere_priorities": {
            "stage2_authority_by_choice": {
                sphere_id: {
                    "authority_complete": True,
                    "allowed_kinds": [sphere_kind],
                    "allowed_channels": ["creation-training-published-sphere"],
                }
            }
        },
        "advancement_skeleton": {
            "stage2_authority_by_choice": {
                talent_id: {
                    "authority_complete": True,
                    "allowed_kinds": [talent_kind],
                    "allowed_channels": ["creation-training-known-sphere-talent"],
                    "sphere_id": sphere_id,
                },
                bonus_id: {
                    "authority_complete": True,
                    "allowed_kinds": [bonus_kind],
                    "allowed_channels": ["new-sphere-bonus"],
                    "sphere_id": sphere_id,
                },
            }
        },
    }
    envelope = {
        "creation_training_contract": _contract(target_cl=1, routes=routes),
        "choices_by_slot": {
            "sphere_priorities": {sphere_id: rows[sphere_id]},
            "advancement_skeleton": {talent_id: rows[talent_id], bonus_id: rows[bonus_id]},
        },
        "allowed_choices_by_slot": {
            "sphere_priorities": [sphere_id],
            "advancement_skeleton": [talent_id, bonus_id],
        },
        "typed_choice_authority_by_slot": typed,
    }
    state = CommittedState.empty()
    expected_ids = (talent_id,)
    if choice_type in {"new_sphere", "bonus"}:
        expected_ids = (sphere_id, bonus_id)
    else:
        state = state.with_pair(sphere_id, "talent.free")
    return {"request_sha256": "d" * 64}, envelope, state, expected_kind, expected_ids


@pytest.mark.parametrize(
    "choice_type,expected_kind",
    [
        ("new_sphere", CREATION_TRAINING_SPHERE_KIND),
        ("known_sphere_talent", CREATION_TRAINING_TALENT_KIND),
        ("bonus", "new_sphere_bonus_talent_acquisition"),
    ],
)
def test_creation_training_menu_emits_only_sealed_stage2_kinds(choice_type: str, expected_kind: str) -> None:
    for allowed in (True, False):
        request, envelope, state, _expected_kind, expected_ids = _authority_menu_fixture(
            choice_type=choice_type,
            expected_kind=expected_kind,
            allowed=allowed,
        )
        menu = build_creation_training_menu(request, envelope, state, cl=1, slot=1)
        offered = {value for option in menu.options for value in option.choice_ids} if menu else set()
        if choice_type == "new_sphere":
            expected = {"sphere.training", "talent.bonus"}
        elif choice_type == "bonus":
            expected = {"sphere.training", "talent.bonus"}
        else:
            expected = {"talent.training"}
        assert offered == (expected if allowed else set())
        if menu:
            for option in menu.options:
                if choice_type == "new_sphere" and option.choice_ids == ("sphere.training", "talent.bonus"):
                    assert _creation_training_kind_allowed(
                        request,
                        envelope,
                        envelope["creation_training_contract"]["records"]["sphere.training"],
                        "sphere.training",
                        "new_sphere",
                        envelope["choices_by_slot"]["sphere_priorities"]["sphere.training"],
                        CREATION_TRAINING_SPHERE_KIND,
                    )
                elif choice_type == "known_sphere_talent" and option.choice_ids == ("talent.training",):
                    assert _creation_training_kind_allowed(
                        request,
                        envelope,
                        envelope["creation_training_contract"]["records"]["talent.training"],
                        "talent.training",
                        "known_sphere_talent",
                        envelope["choices_by_slot"]["advancement_skeleton"]["talent.training"],
                        CREATION_TRAINING_TALENT_KIND,
                    )


def test_creation_training_menu_requires_complete_sealed_authority() -> None:
    request, envelope, state, _expected_kind, _expected_ids = _authority_menu_fixture(
        choice_type="known_sphere_talent",
        expected_kind=CREATION_TRAINING_TALENT_KIND,
        allowed=True,
    )
    del envelope["typed_choice_authority_by_slot"]["advancement_skeleton"]["stage2_authority_by_choice"]["talent.training"]

    menu = build_creation_training_menu(request, envelope, state, cl=1, slot=1)
    assert not menu or not {
        value for option in menu.options for value in option.choice_ids
    }


@pytest.mark.parametrize("committed", [False, True], ids=["owner-lock", "selected-state"])
@pytest.mark.parametrize("lane", ("creation_training", "ordinary"))
def test_creation_training_reserves_sealed_background_talent_alias(committed: bool, lane: str) -> None:
    sphere_id = "tianxia.sphere.scoundrel"
    background_sphere_id = "tianxia.background_sphere.scoundrel"
    background_talent_id = "tianxia.background_talent.scoundrel.hidden_tool_cache"
    canonical_talent_id = "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE"
    other_talent_id = "TAL_SCOUNDREL_SWITCHEROO"
    routes = {
        canonical_talent_id: _route(canonical_talent_id, content_type="talent", choice_type="known_sphere_talent", owning_sphere_id=sphere_id),
        other_talent_id: _route(other_talent_id, content_type="talent", choice_type="known_sphere_talent", owning_sphere_id=sphere_id),
    }
    row = {"choice_id": canonical_talent_id, "name": "Hidden Tool Cache", "content_type": "talent"}
    other_row = {"choice_id": other_talent_id, "name": "Switcheroo", "content_type": "talent"}
    envelope = {
        "creation_training_contract": _contract(target_cl=1, routes=routes),
        "ordinary_talent_count": 1,
        "choices_by_slot": {
            "background_choice": {"background.abandoned": {"choice_id": "background.abandoned", "name": "Abandoned Orphan"}},
            "background_sphere_choice": {background_sphere_id: {"choice_id": background_sphere_id, "name": "Scoundrel", "canonical_sphere_id": sphere_id}},
            "background_talent_choice": {background_talent_id: {"choice_id": background_talent_id, "name": "Hidden Tool Cache"}},
            "sphere_priorities": {sphere_id: {"choice_id": sphere_id, "name": "Scoundrel", "content_type": "sphere"}},
            "advancement_skeleton": {canonical_talent_id: row, other_talent_id: other_row},
        },
        "allowed_choices_by_slot": {
            "sphere_priorities": [sphere_id],
            "advancement_skeleton": [canonical_talent_id, other_talent_id],
        },
        "typed_choice_authority_by_slot": {
            "advancement_skeleton": {
                "stage2_authority_by_choice": {
                    canonical_talent_id: {
                        "authority_complete": True,
                        "allowed_kinds": [CREATION_TRAINING_TALENT_KIND, "level_talent_acquisition"],
                        "allowed_channels": ["creation-training-known-sphere-talent", "level-choice"],
                        "sphere_id": sphere_id,
                    },
                    other_talent_id: {
                        "authority_complete": True,
                        "allowed_kinds": [CREATION_TRAINING_TALENT_KIND, "level_talent_acquisition"],
                        "allowed_channels": ["creation-training-known-sphere-talent", "level-choice"],
                        "sphere_id": sphere_id,
                    },
                }
            },
            "background_choice": {
                "authority_contract": {
                    "schema": "TianxiaFoundry.BackgroundTypedChoiceContract.v1",
                    "background_package_linkage": {
                        "background.abandoned": [{
                            "background_sphere_choice_id": background_sphere_id,
                            "background_talent_choice_id": background_talent_id,
                            "sphere_record_id": sphere_id,
                            "canonical_sphere_id": sphere_id,
                            "talent_record_id": background_talent_id,
                            "canonical_talent_id": canonical_talent_id,
                        }]
                    },
                }
            },
        },
    }
    if committed:
        state = CommittedState.empty().with_choice("background_choice", ["background.abandoned"])
        state = state.with_choice("background_sphere_choice", [background_sphere_id])
        state = state.with_choice("background_talent_choice", [background_talent_id])
    else:
        state = CommittedState.empty()
        envelope["owner_locks"] = {"by_slot": {
            "background_choice": ["background.abandoned"],
            "background_sphere_choice": [background_sphere_id],
            "background_talent_choice": [background_talent_id],
        }}
    request = {"request_sha256": "e" * 64}
    # The walk applies owner locks before invoking any acquisition menu.
    state = _apply_owner_locks(request, envelope, state)
    menu = (
        build_creation_training_menu(request, envelope, state, cl=1, slot=1)
        if lane == "creation_training"
        else build_ordinary_talent_menu(request, envelope, state, cl=1)
    )
    assert menu is not None
    offered = {value for option in menu.options for value in option.choice_ids}
    assert canonical_talent_id not in offered
    assert other_talent_id in offered


def _catalog_training_record(record_id: str, content_type: str, allowed_kinds: list[str], *, sphere_id: str | None = None) -> dict:
    authority = {
        "authority_complete": True,
        "allowed_kinds": allowed_kinds,
        "allowed_channels": [
            CREATION_TRAINING_CHANNEL_BY_KIND[kind]
            for kind in allowed_kinds
            if kind in CREATION_TRAINING_CHANNEL_BY_KIND
        ],
        **({"sphere_id": sphere_id} if sphere_id else {}),
    }
    raw = {
        "access_category": "Open",
        "creator_selectability_can_be_evaluated_safely": True,
        **({"owning_canonical_sphere_id": sphere_id} if sphere_id else {}),
    }
    return {
        "record_id": record_id,
        "content_type": content_type,
        "record_hash": "b" * 64,
        "source": {"source_id": "source.rules", "source_hash": "a" * 64, "anchor": "line:1", "path": "rules.md"},
        "raw_record": raw,
        "compatibility": {"factory": {"stage2_authority": authority}},
    }


def test_creation_training_contract_drops_records_without_creation_training_authority() -> None:
    records = {
        "sphere.allowed": _catalog_training_record("sphere.allowed", "sphere", [CREATION_TRAINING_SPHERE_KIND]),
        "sphere.disallowed": _catalog_training_record("sphere.disallowed", "sphere", ["ai_bootstrap_sphere_acquisition"]),
        "talent.allowed": _catalog_training_record("talent.allowed", "talent", [CREATION_TRAINING_TALENT_KIND], sphere_id="sphere.allowed"),
        "talent.background": _catalog_training_record("talent.background", "talent", ["background_talent_acquisition"], sphere_id="sphere.allowed"),
    }
    contract = build_creation_training_contract(records, target_cl=1, power_band="standard")
    assert set(contract["records"]) == {"sphere.allowed", "talent.allowed"}


def test_creation_training_contract_requires_exact_creation_training_channel() -> None:
    record = _catalog_training_record(
        "sphere.missing-channel",
        "sphere",
        [CREATION_TRAINING_SPHERE_KIND],
    )
    _stage2_authority(record).pop("allowed_channels")

    contract = build_creation_training_contract(
        {record["record_id"]: record},
        target_cl=1,
        power_band="standard",
    )

    assert contract["records"] == {}


@pytest.mark.parametrize(
    "raw_bonus_eligible,authority_allows_bonus",
    [
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    ],
    ids=["raw-off-authority-off", "raw-off-authority-on", "raw-on-authority-off", "raw-on-authority-on"],
)
def test_creation_training_bonus_requires_raw_flag_and_sealed_bonus_kind(
    raw_bonus_eligible: bool,
    authority_allows_bonus: bool,
) -> None:
    allowed_kinds = [CREATION_TRAINING_TALENT_KIND]
    if authority_allows_bonus:
        allowed_kinds.append("new_sphere_bonus_talent_acquisition")
    record = _catalog_training_record(
        "talent.bonus",
        "talent",
        allowed_kinds,
        sphere_id="sphere.allowed",
    )
    record["raw_record"]["free_sphere_talent_eligible"] = raw_bonus_eligible

    contract = build_creation_training_contract(
        {record["record_id"]: record},
        target_cl=1,
        power_band="standard",
    )

    route = contract["records"][record["record_id"]]
    assert route["bonus_talent_eligible"] is (raw_bonus_eligible and authority_allows_bonus)


def _stage2_authority(record: dict) -> dict:
    return (record.get("compatibility") or {}).get("factory", {}).get("stage2_authority") or {}


def _real_creation_intent(
    catalog_environment,
    *,
    selected_background_id: str | None = None,
    selected_background_sphere_id: str | None = None,
    target_cl: int = 1,
) -> tuple[CharacterCreationExecutionService, dict, dict, CanonicalSelectionIntent, dict]:
    db = catalog_environment["db"]
    created = CharacterBuilderService(db).create_project(
        working_name="R4 creation-training integration",
        concept="A provider-free constructed-training integration character.",
        target_cl=target_cl,
        power_band="standard",
        source_reference=None,
        creation_mode="detailed",
        ability_scores={},
        # Stage 1 presents a bounded Origin window; an owner who wants a
        # specific Background locks it, and the window then leads with that
        # Background's suggested Origins.  Mirror that owner flow here.
        selections={"background_choice": [selected_background_id]} if selected_background_id else {},
        generation_route="ai_bootstrap",
    )
    project_id = created["project_id"]
    store = ProjectStore(db)
    creator = CharacterCreationExecutionService(
        db,
        stage1=Stage1ClipboardService(db),
        provider=None,
        project_store=store,
    )
    request = creator._complete_request(
        project_id,
        execution_mode="MANUAL_CHAT",
        idempotency_key="r4-creation-training-integration",
    )
    run_id = f"cg1.test.r4-creation-training.{project_id}"
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO character_creation_runs(
                run_id,project_id,starting_revision,execution_mode,idempotency_key,
                request_json,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                project_id,
                request["project_revision"],
                "MANUAL_CHAT",
                "r4-creation-training-integration",
                canonical_json(request),
                "WAITING_FOR_RESPONSE",
                "2026-08-17T00:00:00+00:00",
                "2026-08-17T00:00:00+00:00",
            ),
        )
    project = store.get_project(project_id)["project"]
    records = creator._locked_records_for_project(project_id)
    envelope = request["delegated_choice_envelope"]

    def owning_sphere(record: dict) -> str | None:
        authority = _stage2_authority(record)
        return (
            authority.get("owning_canonical_sphere_id")
            or authority.get("sphere_id")
            or record.get("owning_canonical_sphere_id")
        )

    initial_pair = next(
        (
            (sphere_id, talent_id)
            for sphere_id, sphere in sorted(records.items())
            if sphere.get("content_type") == "sphere"
            and "ai_bootstrap_sphere_acquisition" in (_stage2_authority(sphere).get("allowed_kinds") or [])
            for talent_id, talent in sorted(records.items())
            if talent.get("content_type") == "talent"
            and "ai_bootstrap_talent_acquisition" in (_stage2_authority(talent).get("allowed_kinds") or [])
            and _stage2_authority(talent).get("free_sphere_talent_eligible", talent.get("free_sphere_talent_eligible", True)) is not False
            and owning_sphere(talent) == sphere_id
        ),
        None,
    )
    assert initial_pair is not None
    initial_sphere_id, initial_talent_id = initial_pair

    linkage = (
        envelope["typed_choice_authority_by_slot"]["background_choice"]
        .get("background_package_linkage")
        or {}
    )
    offered_origins = set(envelope["allowed_choice_ids_by_slot"]["origin_insight_choice"])
    background_id, packages, origin_id = next(
        (
            (candidate_id, candidate_packages, relation["record_id"])
            for candidate_id, candidate_packages in linkage.items()
            if selected_background_id is None or candidate_id == selected_background_id
            if candidate_packages
            for relation in envelope["choices_by_slot"]["background_choice"][candidate_id].get("parent_relationships") or []
            if relation.get("record_id") in offered_origins
        )
    )
    package = next(
        package
        for package in packages
        if selected_background_sphere_id is None
        or package.get("background_sphere_choice_id") == selected_background_sphere_id
    )
    background_sphere_id = package["background_sphere_choice_id"]
    background_talent_id = package["background_talent_choice_id"]
    canonical_background_sphere_id = canonical_background_sphere_ids(
        [background_sphere_id], envelope["choices_by_slot"]
    )[background_sphere_id]
    background_adjustment = (
        envelope["typed_choice_authority_by_slot"]["background_choice"]
        .get("ability_adjustment_by_choice", {})
        .get(background_id)
        or {}
    )
    allowed_abilities = background_adjustment.get("allowed_abilities") or []
    allowed_amounts = background_adjustment.get("allowed_amounts") or background_adjustment.get("amount_choices") or []
    background_ability = allowed_abilities[0] if allowed_abilities else None
    background_amount = allowed_amounts[0] if allowed_amounts else background_adjustment.get("amount")

    contract = envelope["creation_training_contract"]
    training_sphere_id, training_route = next(
        (
            (record_id, route)
            for record_id, route in sorted(contract["records"].items())
            if route.get("content_type") == "sphere"
            and route.get("choice_type") == "new_sphere"
            and record_id in records
            and record_id not in {initial_sphere_id, canonical_background_sphere_id}
        ),
        (None, None),
    )
    assert training_route is not None
    assert training_sphere_id != canonical_background_sphere_id
    bonus_id, bonus_route = next(
        (
            (record_id, route)
            for record_id, route in sorted(contract["records"].items())
            if route.get("content_type") == "talent"
            and route.get("choice_type") == "known_sphere_talent"
            and route.get("owning_sphere_id") == training_sphere_id
            and route.get("bonus_talent_eligible") is True
            and (route.get("minimum_cl") or 1) <= 1
            and record_id in records
        ),
        (None, None),
    )
    assert bonus_route is not None

    free_talent_ids = {initial_talent_id, background_talent_id, bonus_id}
    known_spheres = {initial_sphere_id, canonical_background_sphere_id, training_sphere_id}
    ordinary_id = next(
        choice_id
        for choice_id in envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"]
        if choice_id in records
        and choice_id not in free_talent_ids
        and records[choice_id].get("content_type") == "talent"
        and owning_sphere(records[choice_id]) in known_spheres
        and "level_talent_acquisition" in (_stage2_authority(records[choice_id]).get("allowed_kinds") or [])
        and "ai-bootstrap-free-cl1-talent" in (_stage2_authority(records[choice_id]).get("allowed_channels") or [])
        and (_stage2_authority(records[choice_id]).get("minimum_cl") or records[choice_id].get("legality", {}).get("minimum_cl") or 1) <= 1
    )
    trained_row = _row(training_route, cl=1, slot=1, bonus_talent_id=bonus_id)
    intent = CanonicalSelectionIntent.from_document(
        {
            "selected_by_slot": {
                "path_choice": ["tianxia.path.body_refining"],
                "background_choice": [background_id],
                "background_sphere_choice": [background_sphere_id],
                "background_talent_choice": [background_talent_id],
                "origin_insight_choice": [origin_id],
            },
            "bounded_choices": {
                "ability_scores": {"STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8},
                **({"background_ability": background_ability} if background_ability else {}),
                **({"background_ability_amount": background_amount} if background_amount is not None else {}),
            },
            "acquisition_intent": {
                "sphere_free_talent_pairs": [{"sphere_id": initial_sphere_id, "talent_id": initial_talent_id}],
                "ordinary_talent_ids": [ordinary_id],
                "insight_occurrences": [],
                "trained_choices": [trained_row],
            },
        }
    )
    return creator, project, {"project_id": project_id, "request": request, "run_id": run_id}, intent, trained_row


def test_stage2_creation_training_requires_trusted_scope_and_reduces_catalog_row(catalog_environment) -> None:
    creator, project, run, intent, trained_row = _real_creation_intent(catalog_environment)
    db = creator.db
    stage2 = RulesCausalStage2Service(db)
    rows = creator._derive_stage2_rows_from_frozen_authority(run, project, intent)
    assert not any(
        row.get("record_id") == "tianxia.c1a.none.immortal_arts"
        for row in rows
    )
    materialized = next(row for row in rows if row["kind"] == "creation_training_sphere_acquisition")
    assert materialized["record_id"] == trained_row["record_id"]
    assert materialized["parameters"]["outcome"] == constructed_outcome()

    proposal = {
        "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
        "project_id": run["project_id"],
        "expected_project_revision": run["request"]["project_revision"],
        "expected_content_lock_hash": run["request"]["content_lock_hash"],
        "target_cl": 1,
        "idempotency_key": "r4-stage2-scope-negative",
        "choices": [materialized],
    }
    created = stage2.create_proposal(proposal)
    validation = stage2.validate_proposal(created["proposal_id"])
    assert validation["status"] == "blocked"
    assert "CREATION_TRAINING_SCOPE_REQUIRED" in {
        blocker["code"] for blocker in validation["blocker_report"]["blockers"]
    }

    with db.connection() as conn:
        proposal_row = stage2._proposal_row(conn, created["proposal_id"])
        event, next_state, blockers = stage2._choice_event(
            conn=conn,
            row=proposal_row,
            project=project,
            state=_state(run["project_id"]),
            choice=materialized,
            index=0,
            sequence=1,
            previous_hash=ZERO_HASH,
            generic_prefix=[],
        )
    assert event is None
    assert next_state == _state(run["project_id"])
    assert any(blocker["code"] == "CREATION_TRAINING_SCOPE_REQUIRED" for blocker in blockers)

    with _private_scope(stage2, run["request"], run["run_id"], {"tianxia.path.body_refining"}):
        with db.connection() as conn:
            event, reduced, blockers = stage2._choice_event(
                conn=conn,
                row=proposal_row,
                project=project,
                state=_state(run["project_id"]),
                choice=materialized,
                index=0,
                sequence=1,
                previous_hash=ZERO_HASH,
                generic_prefix=[],
            )
    assert blockers == []
    assert event is not None
    reduced = stage2._apply_event(_state(run["project_id"]), event)
    assert materialized["record_id"] in reduced["known_spheres"]
    assert reduced["creation_training_choices"]["1"][0]["record_id"] == materialized["record_id"]
    assert reduced["new_sphere_entitlements"][0]["bonus_talent_id"] == materialized["parameters"]["bonus_talent_id"]
    # The visible ledger re-derives the canonical trained-choice shape from
    # the reduced row; a row without its CL failed every terminal receipt.
    from creation_training_authority import canonical_trained_choice

    reduced_row = reduced["creation_training_choices"]["1"][0]
    assert reduced_row["cl"] == 1
    assert validate_trained_choice_shape(canonical_trained_choice(reduced_row)) == []


def test_real_background_sphere_talent_uses_canonical_identity(catalog_environment) -> None:
    creator, project, run, intent, _trained_row = _real_creation_intent(
        catalog_environment,
        selected_background_id="tianxia.background.ancestral_shrine_keeper",
        selected_background_sphere_id="tianxia.background_sphere.spirit_companions",
    )
    envelope = run["request"]["delegated_choice_envelope"]
    document = intent.as_dict()
    selected = document["selected_by_slot"]
    background_id = selected["background_sphere_choice"][0]
    canonical_id = canonical_background_sphere_ids(
        [background_id], envelope["choices_by_slot"]
    )[background_id]
    assert canonical_id != background_id

    records = creator._locked_records_for_project(run["project_id"])
    contract = envelope["creation_training_contract"]
    excluded = {
        selected["background_talent_choice"][0],
        document["acquisition_intent"]["sphere_free_talent_pairs"][0]["talent_id"],
    }
    training_route = next(
        route
        for record_id, route in sorted(contract["records"].items())
        if route.get("content_type") == "talent"
        and route.get("choice_type") == "known_sphere_talent"
        and route.get("owning_sphere_id") == canonical_id
        and record_id in records
        and record_id not in excluded
        and (route.get("minimum_cl") or 1) <= 1
        and not route.get("prerequisites")
    )
    document["acquisition_intent"]["trained_choices"] = [_row(training_route, cl=1, slot=1)]

    initial_sphere_id = document["acquisition_intent"]["sphere_free_talent_pairs"][0]["sphere_id"]
    free_talent_ids = {
        pair["talent_id"]
        for pair in document["acquisition_intent"]["sphere_free_talent_pairs"]
    }
    ordinary_id = next(
        record_id
        for record_id in envelope["allowed_choice_ids_by_slot"]["advancement_skeleton"]
        if record_id in records
        and record_id not in free_talent_ids
        and record_id not in excluded
        and records[record_id].get("content_type") == "talent"
        and (
            (_stage2_authority(records[record_id]).get("owning_canonical_sphere_id")
             or _stage2_authority(records[record_id]).get("sphere_id")
             or records[record_id].get("owning_canonical_sphere_id"))
            in {initial_sphere_id, canonical_id}
        )
        and "level_talent_acquisition" in (_stage2_authority(records[record_id]).get("allowed_kinds") or [])
        and ( _stage2_authority(records[record_id]).get("minimum_cl") or records[record_id].get("legality", {}).get("minimum_cl") or 1) <= 1
    )
    document["acquisition_intent"]["ordinary_talent_ids"] = [ordinary_id]
    document.pop("intent_sha256", None)
    document["intent_sha256"] = sha256_json(document)
    canonical_intent = CanonicalSelectionIntent.from_document(document)
    semantic_plan = {"canonical_selection_intent": {"acquisition_intent": document["acquisition_intent"]}}
    _validate_semantic_acquisition_intent(envelope, semantic_plan, selected)

    rows = creator._derive_stage2_rows_from_frozen_authority(run, project, canonical_intent)
    native_background_sphere_id = next(
        row["record_id"]
        for row in rows
        if row["kind"] == "background_sphere_acquisition"
    )
    materialized = next(
        row for row in rows if row["kind"] == "creation_training_talent_acquisition"
    )
    assert materialized["record_id"] == training_route["record_id"]
    assert materialized["parameters"]["choice_type"] == "known_sphere_talent"
    assert native_background_sphere_id == background_id

    compile_plan = {
        "canonical_selection_intent": canonical_intent.as_dict(),
        "stage2_proposal": {"choices": rows},
    }
    final_plan = {
        "schema": "TianxiaFoundry.CharacterCreationFinalPlan.v1",
        "project_id": run["project_id"],
        "target_cl": 1,
        "resolution": {
            "selected_choices_by_slot": deepcopy(selected),
            "actual_advancing_path_ids": deepcopy(selected.get("path_choice") or []),
            "method_id": (selected.get("method_choice") or [None])[0],
            "foundation_id": (selected.get("foundation_choice") or [None])[0],
        },
    }
    compiled = creator._derive_delegated_final_grant_plan(run, compile_plan, final_plan)
    grant_plan = compiled["canonical_grant_plan"]
    assert canonical_id in grant_plan["acquired_canonical_sphere_ids"]
    assert compiled["catalog_response_authority"]["accepted_background_canonical_sphere_ids"] == [canonical_id]

    stage2 = RulesCausalStage2Service(creator.db)
    initial_rows = [
        row
        for row in rows
        if row["kind"] in {
            "starting_state",
            "background_acquisition",
            "background_sphere_acquisition",
            "background_talent_acquisition",
        }
    ]
    proposal = stage2.create_proposal(
        {
            "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
            "project_id": run["project_id"],
            "expected_project_revision": run["request"]["project_revision"],
            "expected_content_lock_hash": run["request"]["content_lock_hash"],
            "target_cl": 1,
            "idempotency_key": "r4-background-package-reduction",
            "choices": initial_rows,
        }
    )
    background_sphere_event = None
    background_talent_event = None
    with creator.db.connection() as conn:
        proposal_row = stage2._proposal_row(conn, proposal["proposal_id"])
        state = _state(run["project_id"])
        prefix: list[dict] = []
        previous_hash = ZERO_HASH
        for index, choice in enumerate(initial_rows):
            event, state, blockers = stage2._choice_event(
                conn=conn,
                row=proposal_row,
                project=project,
                state=state,
                choice=choice,
                index=index,
                sequence=index + 1,
                previous_hash=previous_hash,
                generic_prefix=prefix,
            )
            assert blockers == []
            assert event is not None
            if choice["kind"] == "background_sphere_acquisition":
                background_sphere_event = event
            elif choice["kind"] == "background_talent_acquisition":
                background_talent_event = event
            prefix.append(event)
            previous_hash = event["event_hash"]

        resolved_background_sphere = creator.projects._resolve_locked_record_after_proof(
            conn,
            run["project_id"],
            background_id,
        )
        resolved_background_talent = creator.projects._resolve_locked_record_after_proof(
            conn,
            run["project_id"],
            selected["background_talent_choice"][0],
        )

    assert native_background_sphere_id == background_id
    assert resolved_background_sphere is not None
    assert resolved_background_sphere["record_id"] == canonical_id
    assert background_sphere_event is not None
    assert background_sphere_event["subject"]["record_id"] == canonical_id
    assert state["background_sphere"] == canonical_id
    assert resolved_background_talent is not None
    assert background_talent_event is not None
    assert background_talent_event["subject"]["record_id"] == resolved_background_talent["record_id"]
    talent_authority = _stage2_authority(resolved_background_talent)
    assert (
        talent_authority.get("sphere_id")
        or talent_authority.get("owning_canonical_sphere_id")
    ) == canonical_id
    assert state["background_talent"] == resolved_background_talent["record_id"]


def test_real_harvesting_background_alias_uses_sealed_canonical_identity(catalog_environment) -> None:
    creator, project, run, intent, _trained_row = _real_creation_intent(
        catalog_environment,
        selected_background_id="tianxia.background.forest_hermit",
        selected_background_sphere_id="tianxia.background_sphere.harvesting_and_gathering",
    )
    envelope = run["request"]["delegated_choice_envelope"]
    selected = intent.as_dict()["selected_by_slot"]
    background_id = selected["background_sphere_choice"][0]
    canonical_id = canonical_background_sphere_ids(
        [background_id], envelope["choices_by_slot"]
    )[background_id]
    assert canonical_id == "tianxia.sphere.harvesting_gathering"
    background_sphere_row = envelope["choices_by_slot"]["background_sphere_choice"][background_id]
    assert background_sphere_row["canonical_sphere_id"] == canonical_id
    package = next(
        package
        for package in (
            envelope["typed_choice_authority_by_slot"]["background_choice"]
            .get("background_package_linkage")
            or {}
        )[selected["background_choice"][0]]
        if package.get("background_sphere_choice_id") == background_id
    )
    assert package["sphere_record_id"] == background_id
    assert package["canonical_sphere_id"] == canonical_id

    # Keep this alias regression focused on the selected Background Sphere
    # relation.  Use a known-Sphere training row so the test does not also
    # exercise the separate new-Sphere grant accounting lane.
    document = intent.as_dict()
    records = creator._locked_records_for_project(run["project_id"])
    contract = envelope["creation_training_contract"]
    initial_talent_id = document["acquisition_intent"]["sphere_free_talent_pairs"][0]["talent_id"]
    excluded = {selected["background_talent_choice"][0], initial_talent_id}
    training_route = next(
        route
        for record_id, route in sorted(contract["records"].items())
        if route.get("content_type") == "talent"
        and route.get("choice_type") == "known_sphere_talent"
        and route.get("owning_sphere_id") == canonical_id
        and record_id in records
        and record_id not in excluded
        and (route.get("minimum_cl") or 1) <= 1
        and not route.get("prerequisites")
    )
    document["acquisition_intent"]["trained_choices"] = [_row(training_route, cl=1, slot=1)]
    document.pop("intent_sha256", None)
    document["intent_sha256"] = sha256_json(document)
    intent = CanonicalSelectionIntent.from_document(document)

    rows = creator._derive_stage2_rows_from_frozen_authority(run, project, intent)
    native_background_sphere_id = next(
        row["record_id"]
        for row in rows
        if row["kind"] == "background_sphere_acquisition"
    )
    assert native_background_sphere_id == background_id
    compile_plan = {
        "canonical_selection_intent": intent.as_dict(),
        "stage2_proposal": {"choices": rows},
    }
    final_plan = {
        "schema": "TianxiaFoundry.CharacterCreationFinalPlan.v1",
        "project_id": run["project_id"],
        "target_cl": 1,
        "resolution": {
            "selected_choices_by_slot": deepcopy(selected),
            "actual_advancing_path_ids": deepcopy(selected.get("path_choice") or []),
            "method_id": (selected.get("method_choice") or [None])[0],
            "foundation_id": (selected.get("foundation_choice") or [None])[0],
        },
    }
    compiled = creator._derive_delegated_final_grant_plan(run, compile_plan, final_plan)
    assert canonical_id in compiled["canonical_grant_plan"]["acquired_canonical_sphere_ids"]
    assert compiled["catalog_response_authority"]["accepted_background_canonical_sphere_ids"] == [canonical_id]

    stage2 = RulesCausalStage2Service(creator.db)
    initial_rows = [
        row
        for row in rows
        if row["kind"] in {
            "starting_state",
            "background_acquisition",
            "background_sphere_acquisition",
            "background_talent_acquisition",
        }
    ]
    proposal = stage2.create_proposal(
        {
            "schema_version": "TianxiaFoundry.Stage2AdvancementProposal.v2",
            "project_id": run["project_id"],
            "expected_project_revision": run["request"]["project_revision"],
            "expected_content_lock_hash": run["request"]["content_lock_hash"],
            "target_cl": 1,
            "idempotency_key": "r4-harvesting-background-package-reduction",
            "choices": initial_rows,
        }
    )
    background_sphere_event = None
    with creator.db.connection() as conn:
        proposal_row = stage2._proposal_row(conn, proposal["proposal_id"])
        state = _state(run["project_id"])
        prefix: list[dict] = []
        previous_hash = ZERO_HASH
        for index, choice in enumerate(initial_rows):
            event, state, blockers = stage2._choice_event(
                conn=conn,
                row=proposal_row,
                project=project,
                state=state,
                choice=choice,
                index=index,
                sequence=index + 1,
                previous_hash=previous_hash,
                generic_prefix=prefix,
            )
            assert blockers == []
            assert event is not None
            if choice["kind"] == "background_sphere_acquisition":
                background_sphere_event = event
            prefix.append(event)
            previous_hash = event["event_hash"]
        resolved_background_sphere = creator.projects._resolve_locked_record_after_proof(
            conn,
            run["project_id"],
            background_id,
        )

    assert resolved_background_sphere is not None
    assert resolved_background_sphere["record_id"] == canonical_id
    assert background_sphere_event is not None
    assert background_sphere_event["subject"]["record_id"] == canonical_id
    assert state["background_sphere"] == canonical_id


def test_required_training_slot_without_legal_menu_fails_closed_instead_of_completing() -> None:
    from character_creation.creative_controller.linear_walk import LinearWalkError, next_step

    # Control: the same rival/boss contract with sealed Sphere authority
    # presents the first required training slot as a menu.
    request, envelope, _routes = _menu_fixture(target_cl=1, required=3)
    # The identity step opens every walk (a13c3e3); start after it.
    step = next_step(request, envelope, CommittedState.empty().with_bounded("identity", {"name": "Test Name", "title": "Test Title", "concept": "Test concept."}), [])
    # The fixture has exactly one legal bundle, so the slot auto-commits.
    assert step.action in {"MENU", "AUTOCOMMITTED"}
    assert step.step_id == "creation_training:1:1"

    # The owner's CL15 request shape: the frozen envelope published no typed
    # authority for the Sphere slot, so no new-Sphere bundle is legal, and
    # with no Sphere known no known-Sphere Talent is legal either.  The walk
    # used to skip the slot and complete an incomplete character.
    request, envelope, routes = _menu_fixture(target_cl=1, required=3)
    del envelope["typed_choice_authority_by_slot"]["sphere_priorities"]
    assert build_creation_training_menu(request, envelope, CommittedState.empty(), cl=1, slot=1) is None
    with pytest.raises(LinearWalkError) as excinfo:
        next_step(request, envelope, CommittedState.empty().with_bounded("identity", {"name": "Test Name", "title": "Test Title", "concept": "Test concept."}), [])
    assert excinfo.value.code == "DCC_LINEAR_REQUIRED_STEP_UNSATISFIABLE"
    details = excinfo.value.details
    assert details["step_id"] == "creation_training:1:1"
    assert details["cl"] == 1 and details["slot"] == 1 and details["target_cl"] == 1
    sphere_routes = [rid for rid, route in routes.items() if route["choice_type"] == "new_sphere"]
    assert details["new_sphere_route_count"] == len(sphere_routes)
    assert details["new_sphere_routes_without_exact_training_authority"] == len(sphere_routes)
    assert details["known_sphere_ids"] == []
    assert details["owner_sphere_priority_ids"] == ["sphere.z"]

    # A standard contract is not required: the same empty state simply has
    # no training descriptor gap and the walk continues.
    request, envelope, _routes = _menu_fixture(target_cl=1, required=None)
    del envelope["typed_choice_authority_by_slot"]["sphere_priorities"]
    assert next_step(request, envelope, CommittedState.empty(), []).action in {"MENU", "AUTOCOMMITTED", "COMPLETE"}


def test_walk_completion_refuses_missing_mandatory_acquisitions() -> None:
    from character_creation.creative_controller.linear_walk import LinearWalkError, next_step

    request, envelope, _routes = _menu_fixture(target_cl=1, required=3)
    envelope["ordinary_talent_count"] = 1
    state = CommittedState.empty().with_bounded(
        "identity", {"name": "Test Name", "title": "Test Title", "concept": "Test concept."}
    )
    for slot in (1, 2):
        menu = build_creation_training_menu(request, envelope, state, cl=1, slot=slot)
        assert menu is not None
        state = commit_option(menu, menu.options[0].option_id, state)
    # The third required slot is recorded as done without a commit, which is
    # the state a skipped None menu used to leave behind before completion.
    events = [
        {"event_type": "STEP_COMMITTED", "step_id": "creation_training:1:3"},
        {"event_type": "STEP_AUTOCOMMITTED", "step_id": "insight_priorities:1"},
        {"event_type": "STEP_AUTOCOMMITTED", "step_id": "item_priorities:1"},
    ]
    with pytest.raises(LinearWalkError) as excinfo:
        next_step(request, envelope, state, events)
    assert excinfo.value.code == "DCC_LINEAR_MANDATORY_STEPS_INCOMPLETE"
    details = excinfo.value.details
    assert details["trained_choices_missing_by_cl"] == {"1": 1}
    assert details["ordinary_talent_missing_cls"] == [1]
    assert details["next_step_id"] == "creation_training:1:3"
    assert details["target_cl"] == 1


def _menu_choice_ids_across_pages(request: dict, envelope: dict, state: CommittedState, *, cl: int, slot: int) -> list[tuple[str, ...]]:
    from character_creation.creative_controller.linear_menus import MAX_PAGES_PER_STEP

    result: list[tuple[str, ...]] = []
    for page in range(1, MAX_PAGES_PER_STEP + 1):
        try:
            menu = build_creation_training_menu(request, envelope, state, cl=cl, slot=slot, page=page)
        except LinearMenuError:
            break
        if menu is None:
            break
        result.extend(option.choice_ids for option in menu.options if not option.is_continuation)
        if menu.to_dict().get("next_page_id") is None:
            break
    return result


def test_real_frozen_request_publishes_exact_training_sphere_authority(catalog_environment) -> None:
    from character_creation.creative_controller.linear_menus import (
        _creation_training_choice_rows,
        _creation_training_route_row,
    )

    _creator, _project, run, intent, _trained_row = _real_creation_intent(catalog_environment)
    request = run["request"]
    envelope = request["delegated_choice_envelope"]
    contract = envelope["creation_training_contract"]
    packages = envelope["typed_choice_authority_by_slot"]["background_choice"]["background_package_linkage"]
    field_repair = next(
        package for package in packages["tianxia.background.furnace_laborer"]
        if package["background_talent_choice_id"] == "tianxia.background_talent.blacksmith.field_repair"
    )
    assert field_repair["canonical_talent_id"] == "tianxia.talent.blacksmith.field_repair"
    assert field_repair["talent_record_id"] == "tianxia.background_talent.blacksmith.field_repair"
    sphere_routes = {
        record_id: route
        for record_id, route in contract["records"].items()
        if route.get("choice_type") == "new_sphere"
    }
    assert sphere_routes
    typed = envelope["typed_choice_authority_by_slot"]["sphere_priorities"]["stage2_authority_by_choice"]
    choice_rows = _creation_training_choice_rows(request, envelope)
    for record_id, route in sphere_routes.items():
        assert typed[record_id]["authority_complete"] is True
        assert CREATION_TRAINING_SPHERE_KIND in typed[record_id]["allowed_kinds"]
        assert _creation_training_kind_allowed(
            request,
            envelope,
            route,
            record_id,
            "new_sphere",
            _creation_training_route_row(request, envelope, record_id, "new_sphere", choice_rows),
            CREATION_TRAINING_SPHERE_KIND,
        )
    # A Sphere without an exact training route stays unauthorized for this lane.
    unrouted = [record_id for record_id in typed if record_id not in contract["records"]]
    for record_id in unrouted:
        assert CREATION_TRAINING_SPHERE_KIND not in (typed[record_id].get("allowed_kinds") or [])

    # Every published talent route resolves in the CAT3 canonical registry the
    # final validator uses; stat-block component rows are not routes.
    from canonical_catalog import CanonicalCatalogAuthorityService

    registry = CanonicalCatalogAuthorityService(catalog_environment["settings"].root_dir)
    talent_routes = {
        record_id: route
        for record_id, route in contract["records"].items()
        if route.get("choice_type") == "known_sphere_talent"
    }
    assert talent_routes
    assert all(registry.resolve_talent_id(record_id) for record_id in talent_routes)
    names = {
        str(envelope["choices_by_slot"]["advancement_skeleton"].get(record_id, {}).get("name", "")).casefold()
        for record_id in talent_routes
    }
    assert not any(name.endswith("stat block") for name in names)
    assert not any(record_id in talent_routes for record_id in registry._load()["legacy_non_talent_by_id"])

    # The actual CL1 training menu offers new-Sphere bundles from those routes.
    pair = intent.as_dict()["acquisition_intent"]["sphere_free_talent_pairs"][0]
    state = CommittedState.empty().with_pair(pair["sphere_id"], pair["talent_id"])
    offered = _menu_choice_ids_across_pages(request, envelope, state, cl=1, slot=1)
    bundles = [ids for ids in offered if len(ids) == 2]
    assert bundles
    assert {ids[0] for ids in bundles} <= set(sphere_routes)
    assert all(contract["records"][ids[1]]["owning_sphere_id"] == ids[0] for ids in bundles)


def test_stage1_revalidation_accepts_sealed_background_sphere_relation_marker(catalog_environment) -> None:
    _creator, project, run, intent, _trained_row = _real_creation_intent(catalog_environment)
    request = run["request"]
    selected = intent.as_dict()["selected_by_slot"]
    sphere_id = selected["background_sphere_choice"][0]
    slots = {slot["slot_id"]: slot for slot in request["stage1_prompt"]["envelope"]["decision_slots"]}
    row = next(choice for choice in slots["background_sphere_choice"]["choices"] if choice["choice_id"] == sphere_id)
    # Stage 1 publishes the canonical relation marker on the sealed prompt row.
    assert "canonical_sphere_id" in row
    assert row["canonical_sphere_id"] in set(request["delegated_choice_envelope"]["allowed_choice_ids_by_slot"]["sphere_priorities"])
    binding = row["content_binding"]

    def decisions_for(choice: dict) -> list[dict]:
        return [{
            "slot_id": "background_sphere_choice",
            "record_snapshots": [{
                "record_id": sphere_id,
                "record_hash": binding["record_hash"],
                "pack_id": binding["pack_id"],
                "pack_version": binding["pack_version"],
                "pack_hash": binding["pack_hash"],
                "choice_snapshot_hash": sha256_json(choice),
                "choice_snapshot": deepcopy(choice),
            }],
        }]

    db = catalog_environment["db"]
    stage1 = Stage1ClipboardService(db)
    with db.transaction() as conn:
        # The exact sealed prompt row revalidates against the unchanged record.
        stage1._revalidate_snapshots(conn, project["project_id"], decisions_for(row))
        # A marker naming a Sphere outside the lock fails even with a
        # recomputed self-consistent hash.
        forged = deepcopy(row)
        forged["canonical_sphere_id"] = "tianxia.sphere.not_in_this_lock"
        with pytest.raises(FoundryError) as excinfo:
            stage1._revalidate_snapshots(conn, project["project_id"], decisions_for(forged))
        assert excinfo.value.code == "STAGE1_RECORD_SNAPSHOT_CHANGED"
        # A snapshot whose stored hash no longer matches its own row fails.
        inconsistent = decisions_for(row)
        inconsistent[0]["record_snapshots"][0]["choice_snapshot"]["canonical_sphere_id"] = None
        with pytest.raises(FoundryError) as excinfo:
            stage1._revalidate_snapshots(conn, project["project_id"], inconsistent)
        assert excinfo.value.code == "STAGE1_RECORD_SNAPSHOT_CHANGED"


def test_creation_training_contract_excludes_talents_the_canonical_registry_rejects() -> None:
    records = {
        "sphere.allowed": _catalog_training_record("sphere.allowed", "sphere", [CREATION_TRAINING_SPHERE_KIND]),
        "talent.real": _catalog_training_record("talent.real", "talent", [CREATION_TRAINING_TALENT_KIND], sphere_id="sphere.allowed"),
        "talent.statblock": _catalog_training_record("talent.statblock", "talent", [CREATION_TRAINING_TALENT_KIND], sphere_id="sphere.allowed"),
    }
    unfiltered = build_creation_training_contract(records, target_cl=3, power_band="standard")
    assert set(unfiltered["records"]) == {"sphere.allowed", "talent.real", "talent.statblock"}

    def resolver(record_id: str) -> str | None:
        return None if record_id == "talent.statblock" else record_id

    filtered = build_creation_training_contract(records, target_cl=3, power_band="standard", canonical_talent_resolver=resolver)
    assert set(filtered["records"]) == {"sphere.allowed", "talent.real"}
    assert not validate_creation_training_contract(filtered)
