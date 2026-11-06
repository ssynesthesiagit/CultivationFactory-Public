"""Provider-free cross-layer acquisition contracts for the R4 pipeline."""

from __future__ import annotations

from copy import deepcopy

import pytest

from ai_provider.service import AIProviderService
from app.core import FoundryError, sha256_json
from character_creation.delegated_choice_authority import (
    _validate_semantic_acquisition_intent,
    catalog_stage2_selections,
)
from character_creation.response_materialization import CanonicalSelectionIntent
from character_creation.service import CharacterCreationExecutionService
from character_creation.creative_controller.linear_menus import (
    CommittedState,
    _known_sphere_ids,
    build_ordinary_talent_menu,
    build_subpath_choice_menu,
)
from character_creation.creative_controller.linear_walk import _step_descriptors
from creation_training_authority import (
    CREATION_TRAINING_BONUS_KIND,
    CREATION_TRAINING_CHANNEL_BY_KIND,
    CREATION_TRAINING_SPHERE_KIND,
    CREATION_TRAINING_TALENT_KIND,
    canonical_background_package_ids,
    canonical_background_sphere_ids,
    constructed_source,
)
from tests.test_creation_training_r4 import (
    _menu_fixture,
    _real_creation_intent,
    _route,
    _row,
    _semantic_plan,
    _validation_envelope,
)


@pytest.fixture(scope="module", autouse=True)
def _provider_call_tripwire():
    """Fail any accidental provider transport during this contract suite.

    Module scope: a session-scoped fixture is only torn down at the end of
    the whole run, so the tripwire stayed installed for every later test
    file (test_ai_provider_agent_bridge, test_w5_p1r_r1_production_endpoints)
    whenever this module ran first.
    """

    original = AIProviderService.complete_json

    def forbidden_complete_json(self, *args, **kwargs):
        raise AssertionError("provider calls are forbidden in acquisition pipeline contracts")

    AIProviderService.complete_json = forbidden_complete_json
    try:
        yield
    finally:
        AIProviderService.complete_json = original


def _stage2_row(
    kind: str,
    record_id: str,
    *,
    effective_cl: int = 1,
    acquisition_channel: str = "test-source-route",
    parameters: dict | None = None,
) -> dict:
    return {
        "kind": kind,
        "effective_cl": effective_cl,
        "record_id": record_id,
        "acquisition_channel": acquisition_channel,
        "parameters": deepcopy(parameters or {}),
    }


def _final_plan(run: dict, intent: CanonicalSelectionIntent) -> dict:
    selected = intent.as_dict()["selected_by_slot"]
    return {
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


def _causal_routes() -> dict[str, dict]:
    return {
        "sphere.base": _route(
            "sphere.base", content_type="sphere", choice_type="new_sphere"
        ),
        "talent.free": _route(
            "talent.free",
            content_type="talent",
            choice_type="known_sphere_talent",
            owning_sphere_id="sphere.base",
        ),
        "talent.trained": _route(
            "talent.trained",
            content_type="talent",
            choice_type="known_sphere_talent",
            owning_sphere_id="sphere.base",
        ),
        "talent.ordinary1": _route(
            "talent.ordinary1",
            content_type="talent",
            choice_type="known_sphere_talent",
            owning_sphere_id="sphere.base",
        ),
        "talent.ordinary2": _route(
            "talent.ordinary2",
            content_type="talent",
            choice_type="known_sphere_talent",
            owning_sphere_id="sphere.base",
        ),
        "talent.priority": _route(
            "talent.priority",
            content_type="talent",
            choice_type="known_sphere_talent",
            owning_sphere_id="sphere.base",
        ),
    }


def _causal_envelope(routes: dict[str, dict], training_ids: set[str], *, target_cl: int = 2) -> dict:
    envelope = _validation_envelope(routes, target_cl=target_cl)
    envelope["creation_training_contract"]["records"] = {
        record_id: route
        for record_id, route in routes.items()
        if record_id in training_ids
    }
    return envelope


def _causal_plan(rows: list[dict], ordinary: list[str], *, pairs: list[dict] | None = None) -> dict:
    plan = _semantic_plan(rows, pairs=pairs)
    plan["canonical_selection_intent"]["acquisition_intent"]["ordinary_talent_ids"] = list(ordinary)
    return plan


def _base_causal_pairs() -> list[dict]:
    return [{"sphere_id": "sphere.base", "talent_id": "talent.free"}]


def test_semantic_causality_allows_earlier_training_for_later_ordinary() -> None:
    routes = _causal_routes()
    routes["talent.ordinary2"]["prerequisites"] = [
        {"operator": "requires", "target_id": "talent.trained"}
    ]
    envelope = _causal_envelope(routes, {"talent.trained"})
    trained = _row(routes["talent.trained"], cl=1, slot=1)
    plan = _causal_plan(
        [trained],
        ["talent.ordinary1", "talent.ordinary2"],
        pairs=_base_causal_pairs(),
    )

    _validate_semantic_acquisition_intent(envelope, plan, {})


def test_semantic_causality_allows_earlier_ordinary_for_later_training() -> None:
    routes = _causal_routes()
    routes["talent.trained"]["prerequisites"] = [
        {"operator": "requires", "target_id": "talent.ordinary1"}
    ]
    envelope = _causal_envelope(routes, {"talent.trained"})
    trained = _row(routes["talent.trained"], cl=2, slot=1)
    plan = _causal_plan(
        [trained],
        ["talent.ordinary1", "talent.ordinary2"],
        pairs=_base_causal_pairs(),
    )

    _validate_semantic_acquisition_intent(envelope, plan, {})


def test_semantic_causality_rejects_future_ordinary_prerequisite() -> None:
    routes = _causal_routes()
    routes["talent.trained"]["prerequisites"] = [
        {"operator": "requires", "target_id": "talent.ordinary2"}
    ]
    envelope = _causal_envelope(routes, {"talent.trained"})
    trained = _row(routes["talent.trained"], cl=1, slot=1)
    plan = _causal_plan(
        [trained],
        ["talent.ordinary1", "talent.ordinary2"],
        pairs=_base_causal_pairs(),
    )

    with pytest.raises(FoundryError) as error:
        _validate_semantic_acquisition_intent(envelope, plan, {})
    assert error.value.code == "CG1_TRAINED_CHOICE_ILLEGAL"


def test_semantic_causality_does_not_use_planning_priority_as_acquisition() -> None:
    routes = _causal_routes()
    routes["talent.trained"]["prerequisites"] = [
        {"operator": "requires", "target_id": "talent.priority"}
    ]
    envelope = _causal_envelope(routes, {"talent.trained"})
    trained = _row(routes["talent.trained"], cl=1, slot=1)
    plan = _causal_plan([trained], [], pairs=_base_causal_pairs())

    with pytest.raises(FoundryError) as error:
        _validate_semantic_acquisition_intent(
            envelope,
            plan,
            {"advancement_skeleton": ["talent.priority"]},
        )
    assert error.value.code == "CG1_TRAINED_CHOICE_ILLEGAL"


@pytest.mark.parametrize(
    ("training_route", "ordinary_ids", "expected_code"),
    [
        ("talent.trained", ["talent.trained", "talent.ordinary2"], "CG1_DELEGATED_DUPLICATE_CHOICE"),
        ("sphere.new", ["talent.bonus", "talent.ordinary2"], "CG1_NEW_SPHERE_BONUS_REUSED"),
    ],
    ids=["trained-ordinary-duplicate", "bonus-ordinary-duplicate"],
)
def test_semantic_causality_rejects_cross_lane_duplicates(
    training_route: str,
    ordinary_ids: list[str],
    expected_code: str,
) -> None:
    routes = _causal_routes()
    training_ids = {training_route}
    if training_route == "sphere.new":
        routes[training_route] = _route(
            training_route, content_type="sphere", choice_type="new_sphere"
        )
        routes["talent.bonus"] = _route(
            "talent.bonus",
            content_type="talent",
            choice_type="known_sphere_talent",
            owning_sphere_id=training_route,
        )
        training_ids.add("talent.bonus")
        row = _row(routes[training_route], cl=1, slot=1, bonus_talent_id="talent.bonus")
    else:
        row = _row(routes[training_route], cl=1, slot=1)
    envelope = _causal_envelope(routes, training_ids)
    plan = _causal_plan([row], ordinary_ids, pairs=_base_causal_pairs())

    with pytest.raises(FoundryError) as error:
        _validate_semantic_acquisition_intent(envelope, plan, {})
    assert error.value.code == expected_code


def _causal_menu_fixture() -> tuple[dict, dict]:
    request, envelope, _routes = _menu_fixture(target_cl=3)
    envelope["ordinary_talent_count"] = 1
    rows = envelope["choices_by_slot"]["advancement_skeleton"]
    rows["talent.chain"]["prerequisites"] = [
        {"operator": "requires", "target_id": "talent.zbonus"}
    ]
    rows["talent.future-owned"] = {"choice_id": "talent.future-owned", "name": "talent.future-owned"}
    envelope["allowed_choices_by_slot"]["advancement_skeleton"].append("talent.future-owned")
    authority = {
        record_id: {
            "authority_complete": True,
            "allowed_channels": ["level-choice"],
            "allowed_kinds": ["level_talent_acquisition"],
            "minimum_cl": 1,
            "sphere_id": "sphere.z",
        }
        for record_id in rows
    }
    authority["talent.future-owned"]["sphere_id"] = "sphere.future"
    envelope["typed_choice_authority_by_slot"] = {
        "advancement_skeleton": {"stage2_authority_by_choice": authority}
    }
    return request, envelope


def test_menu_causality_excludes_future_trained_sphere_and_talent() -> None:
    request, envelope = _causal_menu_fixture()
    base = CommittedState.empty().with_pair("sphere.z", "talent.available")
    future_talent = base.with_trained_choice(
        {"cl": 2, "slot": 1, "choice_type": "known_sphere_talent", "record_id": "talent.zbonus"}
    )
    menu = build_ordinary_talent_menu(request, envelope, future_talent, cl=1)
    assert menu is not None
    offered = {value for option in menu.options for value in option.choice_ids}
    assert "talent.chain" not in offered

    future_sphere = base.with_trained_choice(
        {
            "cl": 2,
            "slot": 1,
            "choice_type": "new_sphere",
            "record_id": "sphere.future",
            "bonus_talent_id": "talent.future-bonus",
        }
    )
    menu = build_ordinary_talent_menu(request, envelope, future_sphere, cl=1)
    assert menu is not None
    offered = {value for option in menu.options for value in option.choice_ids}
    assert "talent.future-owned" not in offered

    earlier_training = base.with_trained_choice(
        {
            "cl": 1,
            "slot": 1,
            "choice_type": "known_sphere_talent",
            "record_id": "talent.zbonus",
        }
    )
    menu = build_ordinary_talent_menu(request, envelope, earlier_training, cl=2)
    assert menu is not None
    offered = {value for option in menu.options for value in option.choice_ids}
    assert "talent.chain" in offered


def test_menu_requires_selected_background_for_explicit_sphere_relation() -> None:
    request = {}
    envelope = {
        "choices_by_slot": {
            "background_sphere_choice": {
                "background.sphere": {
                    "choice_id": "background.sphere",
                    "name": "Sealed Sphere",
                    "canonical_sphere_id": "sphere.canonical",
                },
            },
            "sphere_priorities": {
                "sphere.canonical": {
                    "choice_id": "sphere.canonical",
                    "name": "Sealed Sphere",
                },
            },
        },
    }
    sphere_only = CommittedState.empty().with_choice(
        "background_sphere_choice", ["background.sphere"]
    )
    assert "sphere.canonical" not in _known_sphere_ids(request, envelope, sphere_only)

    selected_package = sphere_only.with_choice("background_choice", ["background"])
    # An explicit canonical row is only a relation candidate.  Ownership is
    # established by the selected sealed Background package linkage.
    assert "sphere.canonical" not in _known_sphere_ids(request, envelope, selected_package)

    envelope_with_linkage = deepcopy(envelope)
    envelope_with_linkage["typed_choice_authority_by_slot"] = {
        "background_choice": {
            "authority_contract": {
                "schema": "TianxiaFoundry.BackgroundTypedChoiceContract.v1",
                "background_package_linkage": {
                    "background": [{
                        "background_sphere_choice_id": "background.sphere",
                        "canonical_sphere_id": "sphere.canonical",
                    }],
                },
            },
        },
    }
    assert _known_sphere_ids(request, envelope_with_linkage, selected_package) == {"sphere.canonical"}


def test_linear_walk_interleaves_training_and_ordinary_descriptors() -> None:
    request = {}
    envelope = {
        "creation_training_contract": {"target_cl": 2},
        "ordinary_talent_count": 2,
        "selection_limits_by_slot": {"path_choice": {"final_max": 1}, "subpath_choice": {"final_min": 0, "final_max": 0}},
    }
    state = CommittedState(
        by_slot={
            "path_choice": ["path"],
            "method_choice": ["method"],
            "foundation_choice": ["foundation"],
            "background_choice": ["background"],
            "background_sphere_choice": ["background-sphere"],
            "background_talent_choice": ["background-talent"],
            "origin_insight_choice": ["origin"],
        },
        bounded={
            "ability_scores": {
                "STR": 10,
                "DEX": 10,
                "CON": 10,
                "INT": 10,
                "WIS": 10,
                "CHA": 10,
            },
            "background_ability": "STR",
            # a13c3e3a (2026-09-23) opens the walk with the identity step;
            # this state has already conceived the character.
            "identity": {"name": "Test", "title": "Tester"},
        },
    )

    assert _step_descriptors(request, envelope, state)[0][0] == "creation_training:1:1"
    for slot, record_id in enumerate(("trained.1", "trained.2", "trained.3"), start=1):
        state = state.with_trained_choice(
            {"cl": 1, "slot": slot, "choice_type": "known_sphere_talent", "record_id": record_id}
        )
    assert _step_descriptors(request, envelope, state)[0][0] == "ordinary_talent:1"
    state = state.with_ordinary(1, "ordinary.1")
    assert _step_descriptors(request, envelope, state)[0][0] == "creation_training:2:1"


@pytest.mark.parametrize(
    ("target_cl", "expected"),
    [(1, set()), (2, set()), (3, {"subpath.body"})],
    ids=["cl1", "cl2", "cl3"],
)
def test_subpath_menu_filters_by_frozen_target_attainment(target_cl: int, expected: set[str]) -> None:
    request = {"frozen_owner_target_cl": {"value": target_cl}}
    envelope = {
        "subpath_choice_required": True,
        "choices_by_slot": {
            "subpath_choice": {
                "subpath.body": {"choice_id": "subpath.body", "name": "Body Tradition", "owning_path_id": "path.body"},
            }
        },
        "allowed_choices_by_slot": {"subpath_choice": ["subpath.body"]},
        "typed_choice_authority_by_slot": {
            "subpath_choice": {
                "minimum_attainment_by_choice": {"subpath.body": 3},
            }
        },
    }

    menu = build_subpath_choice_menu(request, envelope, path_id="path.body")
    offered = {value for option in menu.options for value in option.choice_ids} if menu else set()
    assert offered == expected


def test_subpath_menu_respects_sealed_higher_attainment_and_legacy_no_target() -> None:
    base_envelope = {
        "subpath_choice_required": True,
        "choices_by_slot": {
            "subpath_choice": {
                "subpath.body": {"choice_id": "subpath.body", "name": "Body Tradition", "owning_path_id": "path.body"},
                "subpath.spirit": {"choice_id": "subpath.spirit", "name": "Spirit Tradition", "owning_path_id": "path.body"},
            }
        },
        "allowed_choices_by_slot": {"subpath_choice": ["subpath.body", "subpath.spirit"]},
        "typed_choice_authority_by_slot": {
            "subpath_choice": {
                "minimum_attainment_by_choice": {"subpath.body": 3, "subpath.spirit": 4},
            }
        },
    }

    target_three = build_subpath_choice_menu(
        {"frozen_owner_target_cl": {"value": 3}},
        deepcopy(base_envelope),
        path_id="path.body",
    )
    assert {value for option in target_three.options for value in option.choice_ids} == {"subpath.body"}

    target_four = build_subpath_choice_menu(
        {"frozen_owner_target_cl": {"value": 4}},
        deepcopy(base_envelope),
        path_id="path.body",
    )
    assert {value for option in target_four.options for value in option.choice_ids} == {"subpath.body", "subpath.spirit"}

    no_target = build_subpath_choice_menu({}, deepcopy(base_envelope), path_id="path.body")
    assert {value for option in no_target.options for value in option.choice_ids} == {"subpath.body", "subpath.spirit"}


@pytest.mark.parametrize(
    ("kind", "record_id", "bucket"),
    [
        ("background_acquisition", "background.source", "background_ids"),
        ("background_sphere_acquisition", "background.sphere", "background_sphere_ids"),
        ("background_talent_acquisition", "background.talent", "background_talent_ids"),
        ("sect_trial_sphere_acquisition", "sect.sphere", "sphere_ids"),
        ("sect_trial_talent_acquisition", "sect.talent", "free_sphere_talent_ids"),
        ("ai_bootstrap_sphere_acquisition", "initial.sphere", "sphere_ids"),
        ("ai_bootstrap_talent_acquisition", "initial.talent", "free_sphere_talent_ids"),
        ("level_talent_acquisition", "level.talent", "ordinary_talent_ids"),
        ("new_sphere_bonus_talent_acquisition", "trained.bonus", "free_sphere_talent_ids"),
    ],
    ids=[
        "background",
        "background-sphere",
        "background-talent",
        "sect-initial-sphere",
        "sect-initial-talent",
        "ai-initial-sphere",
        "ai-initial-talent",
        "level-talent",
        "trained-new-sphere-bonus",
    ],
)
def test_catalog_projection_preserves_each_source_route(kind: str, record_id: str, bucket: str) -> None:
    """Each explicit Stage 2 source route lands in its typed catalog bucket."""

    projected = catalog_stage2_selections(
        {"stage2_proposal": {"choices": [_stage2_row(kind, record_id)]}}
    )

    assert projected[bucket] == [record_id]
    for other_bucket, values in projected.items():
        if other_bucket != bucket and isinstance(values, list) and other_bucket != "insight_occurrences":
            assert record_id not in values


def test_catalog_projection_keeps_trained_talent_out_of_level_talent_capacity() -> None:
    """A constructed Talent remains a separate training lane, never ordinary level capacity."""

    projected = catalog_stage2_selections(
        {
            "stage2_proposal": {
                "choices": [
                    _stage2_row("creation_training_talent_acquisition", "trained.talent"),
                    _stage2_row("level_talent_acquisition", "level.talent"),
                ]
            }
        }
    )

    assert projected["ordinary_talent_ids"] == ["level.talent"]
    assert projected["trained_talent_ids"] == ["trained.talent"]
    assert projected["trained_talent_acquisitions"] == [
        {
            "talent_id": "trained.talent",
            "effective_cl": 1,
            "slot": None,
            "choice_type": None,
            "acquisition_channel": "test-source-route",
            "source": None,
            "outcome": None,
        }
    ]
    assert "trained.talent" not in projected["ordinary_talent_ids"]


def test_catalog_projection_conserves_new_sphere_and_its_bonus() -> None:
    """A trained new Sphere and its distinct zero-slot bonus must survive projection."""

    trained = {
        "cl": 1,
        "slot": 1,
        "choice_type": "new_sphere",
        "record_id": "trained.sphere",
        "source": {"schema": "source", "route": "published-route"},
        "outcome": {"slot_cost": 1, "counts_against_limit": True},
        "bonus_talent_id": "trained.bonus",
    }
    rows = [
        _stage2_row(
            "creation_training_sphere_acquisition",
            trained["record_id"],
            parameters={
                "slot": trained["slot"],
                "choice_type": trained["choice_type"],
                "source": trained["source"],
                "outcome": trained["outcome"],
                "bonus_talent_id": trained["bonus_talent_id"],
            },
        ),
        _stage2_row(
            "new_sphere_bonus_talent_acquisition",
            trained["bonus_talent_id"],
            parameters={"entitlement_attempt_id": "creation-training:1:1:trained.sphere"},
        ),
    ]
    projected = catalog_stage2_selections({"stage2_proposal": {"choices": rows}})

    # The bonus is already retained by the current projection.  Keep this
    # assertion before the known missing-Sphere assertion so the failure names
    # the source route that is lost at this boundary.
    assert projected["free_sphere_talent_ids"] == ["trained.bonus"]
    assert projected["sphere_ids"] == ["trained.sphere"]


def test_proposal_projection_conserves_training_rows_without_promoting_them() -> None:
    """The owner-readable proposal view keeps both training rows and their pair."""

    sphere_route = _route(
        "sphere.training",
        content_type="sphere",
        choice_type="new_sphere",
    )
    talent_route = _route(
        "talent.training",
        content_type="talent",
        choice_type="known_sphere_talent",
        owning_sphere_id="sphere.training",
    )
    sphere_choice = _row(
        sphere_route,
        cl=1,
        slot=1,
        bonus_talent_id="talent.bonus",
    )
    talent_choice = _row(talent_route, cl=1, slot=2)
    value = {
        "selection_intent": {"by_slot": {"path_choice": ["tianxia.path.body_refining"]}},
        "acquisition_intent": {
            "sphere_free_talent_pairs": [
                {"sphere_id": "initial.sphere", "talent_id": "initial.talent"}
            ],
            "ordinary_talent_ids": ["level.talent"],
            "insight_occurrences": [],
            "trained_choices": [sphere_choice, talent_choice],
        },
        "bounded_choices": {},
        "owner_descriptive_fields": {"identity": {"name": "Contract character"}},
    }

    projected = CharacterCreationExecutionService._proposal_projection(value)

    assert projected["acquisition_intent"] == {
        "sphere_free_talent_pairs": [
            {"sphere_id": "initial.sphere", "talent_id": "initial.talent"}
        ],
        "ordinary_talent_ids": ["level.talent"],
        "insight_occurrences": [],
        "trained_choices": [sphere_choice, talent_choice],
    }


def test_real_materializer_conserves_training_source_cl_cost_bonus_and_pairs(catalog_environment) -> None:
    """The production materializer emits source-bound training and acquisition rows."""

    creator, project, run, intent, trained_row = _real_creation_intent(catalog_environment)
    rows = creator._derive_stage2_rows_from_frozen_authority(run, project, intent)
    training_row = next(
        row for row in rows if row["kind"] == "creation_training_sphere_acquisition"
    )
    bonus_row = next(
        row for row in rows if row["kind"] == "new_sphere_bonus_talent_acquisition"
    )
    intent_doc = intent.as_dict()
    expected_pair = intent_doc["acquisition_intent"]["sphere_free_talent_pairs"][0]
    expected_ordinary = intent_doc["acquisition_intent"]["ordinary_talent_ids"]

    assert training_row["record_id"] == trained_row["record_id"]
    assert training_row["effective_cl"] == trained_row["cl"]
    assert training_row["parameters"]["slot"] == trained_row["slot"]
    assert training_row["parameters"]["choice_type"] == trained_row["choice_type"]
    assert training_row["parameters"]["source"] == trained_row["source"]
    assert training_row["parameters"]["source"]["route"] == trained_row["source"]["route"]
    assert training_row["parameters"]["source"]["source_record_id"] == trained_row["source"]["source_record_id"]
    assert training_row["parameters"]["source"]["source_provenance"] == trained_row["source"]["source_provenance"]
    assert training_row["parameters"]["outcome"] == trained_row["outcome"]
    assert training_row["parameters"]["outcome"]["slot_cost"] == 1
    assert training_row["parameters"]["outcome"]["counts_against_limit"] is True
    assert training_row["parameters"]["bonus_talent_id"] == trained_row["bonus_talent_id"]
    assert bonus_row["record_id"] == trained_row["bonus_talent_id"]
    assert bonus_row["effective_cl"] == trained_row["cl"]
    assert bonus_row["parameters"]["entitlement_attempt_id"] == (
        f"creation-training:{trained_row['cl']}:{trained_row['slot']}:{trained_row['record_id']}"
    )

    contract = run["request"]["delegated_choice_envelope"].get("creation_training_contract") or {}
    locked_records = creator._locked_records_for_project(run["project_id"])
    for record_id, route in (contract.get("records") or {}).items():
        authority = (
            (locked_records.get(record_id, {}).get("compatibility") or {})
            .get("factory", {})
            .get("stage2_authority")
            or {}
        )
        expected_kind = CREATION_TRAINING_SPHERE_KIND if route.get("choice_type") == "new_sphere" else CREATION_TRAINING_TALENT_KIND
        assert authority.get("authority_complete") is True
        assert expected_kind in (authority.get("allowed_kinds") or [])
        assert CREATION_TRAINING_CHANNEL_BY_KIND[expected_kind] in (authority.get("allowed_channels") or [])
        if (
            route.get("content_type") == "talent"
            and route.get("choice_type") == "known_sphere_talent"
            and route.get("bonus_talent_eligible") is True
        ):
            assert CREATION_TRAINING_BONUS_KIND in (authority.get("allowed_kinds") or [])
            assert CREATION_TRAINING_CHANNEL_BY_KIND[CREATION_TRAINING_BONUS_KIND] in (authority.get("allowed_channels") or [])

    initial_sphere_rows = [
        row["record_id"]
        for row in rows
        if row["kind"] == "ai_bootstrap_sphere_acquisition"
    ]
    initial_talent_rows = [
        row["record_id"]
        for row in rows
        if row["kind"] == "ai_bootstrap_talent_acquisition"
    ]
    ordinary_rows = [
        row["record_id"]
        for row in rows
        if row["kind"] == "level_talent_acquisition"
    ]
    assert initial_sphere_rows == [expected_pair["sphere_id"]]
    assert initial_talent_rows == [expected_pair["talent_id"]]
    assert ordinary_rows == expected_ordinary

    projected = catalog_stage2_selections({"stage2_proposal": {"choices": rows}})
    assert projected["sphere_ids"] == [expected_pair["sphere_id"], trained_row["record_id"]]
    assert projected["free_sphere_talent_ids"] == [
        expected_pair["talent_id"],
        trained_row["bonus_talent_id"],
    ]
    assert projected["ordinary_talent_ids"] == expected_ordinary
    assert trained_row["bonus_talent_id"] not in projected["ordinary_talent_ids"]


def test_real_final_catalog_compilation_conserves_training_sphere_and_bonus(catalog_environment) -> None:
    """The final catalogue compiler must accept a materialized training Sphere plus bonus."""

    creator, project, run, intent, trained_row = _real_creation_intent(catalog_environment)
    rows = creator._derive_stage2_rows_from_frozen_authority(run, project, intent)
    compiled = creator._derive_delegated_final_grant_plan(
        run,
        {
            "canonical_selection_intent": intent.as_dict(),
            "stage2_proposal": {"choices": rows},
        },
        _final_plan(run, intent),
    )
    stage2 = compiled["catalog_response_authority"]["stage2_mechanical_choices"]
    expected_pair = intent.as_dict()["acquisition_intent"]["sphere_free_talent_pairs"][0]

    assert stage2["sphere_ids"] == [expected_pair["sphere_id"], trained_row["record_id"]]
    assert stage2["free_sphere_talent_ids"] == [
        expected_pair["talent_id"],
        trained_row["bonus_talent_id"],
    ]
    assert trained_row["record_id"] in compiled["canonical_grant_plan"]["acquired_canonical_sphere_ids"]



def test_real_final_catalog_compilation_preserves_background_identity(catalog_environment) -> None:
    """Final catalog compilation keeps the Background alias separate from initial grants."""

    creator, project, run, intent, _trained_row = _real_creation_intent(
        catalog_environment,
        selected_background_id="tianxia.background.ancestral_shrine_keeper",
        selected_background_sphere_id="tianxia.background_sphere.spirit_companions",
    )
    envelope = run["request"]["delegated_choice_envelope"]
    document = intent.as_dict()
    selected = document["selected_by_slot"]
    background_alias = selected["background_sphere_choice"][0]
    canonical_background = canonical_background_sphere_ids(
        [background_alias], envelope["choices_by_slot"]
    )[background_alias]
    assert canonical_background != background_alias
    records = creator._locked_records_for_project(run["project_id"])
    initial_talent_id = document["acquisition_intent"]["sphere_free_talent_pairs"][0]["talent_id"]
    excluded = {selected["background_talent_choice"][0], initial_talent_id}
    training_route = next(
        route
        for record_id, route in sorted(envelope["creation_training_contract"]["records"].items())
        if route.get("content_type") == "talent"
        and route.get("choice_type") == "known_sphere_talent"
        and route.get("owning_sphere_id") == canonical_background
        and record_id in records
        and record_id not in excluded
        and (route.get("minimum_cl") or 1) <= 1
        and not route.get("prerequisites")
    )
    document["acquisition_intent"]["trained_choices"] = [_row(training_route, cl=1, slot=1)]
    document.pop("intent_sha256", None)
    document["intent_sha256"] = sha256_json(document)
    canonical_intent = CanonicalSelectionIntent.from_document(document)

    rows = creator._derive_stage2_rows_from_frozen_authority(run, project, canonical_intent)
    training_materialized = next(
        row for row in rows if row["kind"] == "creation_training_talent_acquisition"
    )
    assert training_materialized["record_id"] == training_route["record_id"]
    assert training_materialized["effective_cl"] == 1
    assert training_materialized["parameters"]["source"] == constructed_source(
        training_route, choice_type=training_route["choice_type"]
    )
    assert training_materialized["parameters"]["outcome"]["slot_cost"] == 1
    assert training_materialized["parameters"]["outcome"]["counts_against_limit"] is True

    compile_plan = {
        "canonical_selection_intent": canonical_intent.as_dict(),
        "stage2_proposal": {"choices": rows},
    }
    compiled = creator._derive_delegated_final_grant_plan(
        run,
        compile_plan,
        _final_plan(run, canonical_intent),
    )
    stage2 = compiled["catalog_response_authority"]["stage2_mechanical_choices"]
    expected_pair = document["acquisition_intent"]["sphere_free_talent_pairs"][0]
    expected_ordinary = document["acquisition_intent"]["ordinary_talent_ids"]

    assert stage2["sphere_ids"] == [expected_pair["sphere_id"]]
    assert stage2["free_sphere_talent_ids"] == [expected_pair["talent_id"]]
    assert stage2["ordinary_talent_ids"] == expected_ordinary
    assert stage2["trained_talent_ids"] == [training_route["record_id"]]
    assert stage2["trained_talent_acquisitions"] == [
        {
            "talent_id": training_route["record_id"],
            "effective_cl": 1,
            "slot": 1,
            "choice_type": "known_sphere_talent",
            "acquisition_channel": "creation-training-known-sphere-talent",
            "source": constructed_source(training_route, choice_type="known_sphere_talent"),
            "outcome": deepcopy(training_materialized["parameters"]["outcome"]),
        }
    ]
    assert compiled["canonical_grant_plan"]["grant_accounting"]["trained_talent_ids"] == [training_route["record_id"]]
    assert compiled["canonical_grant_plan"]["grant_accounting"]["ordinary_talent_ids"] == expected_ordinary
    assert stage2["background_sphere_ids"] == [background_alias]
    expected_background_talents = canonical_background_package_ids(
        {
            **selected,
            "background_talent_choice": list(stage2["background_talent_ids"]),
        },
        envelope["typed_choice_authority_by_slot"],
    )[1]
    assert expected_background_talents
    assert compiled["catalog_response_authority"]["accepted_background_canonical_talent_ids"] == sorted(
        expected_background_talents
    )
    assert not set(expected_background_talents).intersection(
        compiled["canonical_grant_plan"]["grant_accounting"].get("ordinary_talent_ids") or []
    )
    assert not set(expected_background_talents).intersection(
        compiled["canonical_grant_plan"]["grant_accounting"].get("trained_talent_ids") or []
    )
    assert training_route["record_id"] not in stage2["ordinary_talent_ids"]
    assert compiled["canonical_selection_intent"]["acquisition_intent"]["trained_choices"] == [
        document["acquisition_intent"]["trained_choices"][0]
    ]
    assert canonical_background in compiled["canonical_grant_plan"]["acquired_canonical_sphere_ids"]
    assert expected_pair["sphere_id"] in compiled["canonical_grant_plan"]["acquired_canonical_sphere_ids"]
    assert background_alias not in stage2["sphere_ids"]
    assert compiled["catalog_response_authority"]["accepted_background_canonical_sphere_ids"] == [
        canonical_background
    ]


def test_real_materializer_rejects_background_talent_alias_from_other_package(catalog_environment) -> None:
    """A legacy Background Talent alias must match the selected sealed package."""

    creator, project, run, intent, _trained_row = _real_creation_intent(
        catalog_environment,
        selected_background_id="tianxia.background.ancestral_shrine_keeper",
        selected_background_sphere_id="tianxia.background_sphere.spirit_companions",
    )
    envelope = run["request"]["delegated_choice_envelope"]
    selected = intent.as_dict()["selected_by_slot"]
    selected_background_id = selected["background_choice"][0]
    selected_talent_id = selected["background_talent_choice"][0]
    linkage = envelope["typed_choice_authority_by_slot"]["background_choice"][
        "background_package_linkage"
    ]
    selected_package_talent_ids = {
        package.get("background_talent_choice_id")
        for package in linkage[selected_background_id]
        if isinstance(package, dict)
        and isinstance(package.get("background_talent_choice_id"), str)
    }
    offered_talents = set(
        envelope["allowed_choice_ids_by_slot"]["background_talent_choice"]
    )
    foreign_talent_id = next(
        package["background_talent_choice_id"]
        for background_id, packages in linkage.items()
        if background_id != selected_background_id
        for package in packages
        if isinstance(package, dict)
        and package.get("background_talent_choice_id") in offered_talents
        and package.get("background_talent_choice_id") != selected_talent_id
        and package.get("background_talent_choice_id") not in selected_package_talent_ids
        and isinstance(package.get("background_talent_choice_id"), str)
        and package["background_talent_choice_id"].startswith(
            "tianxia.background_talent."
        )
    )
    legacy_foreign_alias = "tianxia.background.talent." + foreign_talent_id[
        len("tianxia.background_talent.") :
    ]

    document = intent.as_dict()
    document["selected_by_slot"]["background_talent_choice"] = [legacy_foreign_alias]
    unsigned = deepcopy(document)
    unsigned.pop("intent_sha256", None)
    document["intent_sha256"] = sha256_json(unsigned)
    tampered_intent = CanonicalSelectionIntent.from_document(document)

    with pytest.raises(FoundryError) as error:
        creator._derive_stage2_rows_from_frozen_authority(
            run,
            project,
            tampered_intent,
        )
    assert error.value.code == "CG1_DELEGATED_BACKGROUND_ALIAS_UNPROVEN"
    assert error.value.details["background_id"] == selected_background_id


def test_real_materializer_rejects_exact_background_talent_from_other_package(catalog_environment) -> None:
    """An exact allowed Talent ID must still match the selected package Sphere."""

    creator, project, run, intent, _trained_row = _real_creation_intent(
        catalog_environment,
        selected_background_id="tianxia.background.ancestral_shrine_keeper",
        selected_background_sphere_id="tianxia.background_sphere.spirit_companions",
    )
    envelope = run["request"]["delegated_choice_envelope"]
    document = intent.as_dict()
    selected = document["selected_by_slot"]
    selected_background_id = selected["background_choice"][0]
    selected_talent_id = selected["background_talent_choice"][0]
    linkage = envelope["typed_choice_authority_by_slot"]["background_choice"][
        "background_package_linkage"
    ]
    selected_package_talent_ids = {
        package.get("background_talent_choice_id")
        for package in linkage[selected_background_id]
        if isinstance(package, dict)
    }
    offered_talents = set(
        envelope["allowed_choice_ids_by_slot"]["background_talent_choice"]
    )
    foreign_talent_id = next(
        package["background_talent_choice_id"]
        for background_id, packages in linkage.items()
        if background_id != selected_background_id
        for package in packages
        if isinstance(package, dict)
        and package.get("background_talent_choice_id") in offered_talents
        and package.get("background_talent_choice_id") != selected_talent_id
        and package.get("background_talent_choice_id") not in selected_package_talent_ids
        and isinstance(package.get("background_talent_choice_id"), str)
        and package["background_talent_choice_id"].startswith(
            "tianxia.background_talent."
        )
    )
    selected["background_talent_choice"] = [foreign_talent_id]
    unsigned = deepcopy(document)
    unsigned.pop("intent_sha256", None)
    document["intent_sha256"] = sha256_json(unsigned)
    tampered_intent = CanonicalSelectionIntent.from_document(document)

    with pytest.raises(FoundryError) as error:
        creator._derive_stage2_rows_from_frozen_authority(
            run,
            project,
            tampered_intent,
        )
    assert error.value.code == "CG1_DELEGATED_BACKGROUND_PACKAGE_MISMATCH"
    assert error.value.details["background_id"] == selected_background_id
    assert error.value.details["background_talent_choice_id"] == foreign_talent_id


def _negative_validation_case(case: str) -> tuple[dict, dict, str]:
    if case == "wrong-sphere-bonus":
        routes = {
            "sphere.training": _route(
                "sphere.training", content_type="sphere", choice_type="new_sphere"
            ),
            "talent.other": _route(
                "talent.other",
                content_type="talent",
                choice_type="known_sphere_talent",
                owning_sphere_id="sphere.other",
            ),
        }
        rows = [_row(routes["sphere.training"], cl=1, slot=1, bonus_talent_id="talent.other")]
        return _validation_envelope(routes, target_cl=1), _semantic_plan(rows), "CG1_NEW_SPHERE_BONUS_INVALID"

    if case == "missing-bonus":
        routes = {
            "sphere.training": _route(
                "sphere.training", content_type="sphere", choice_type="new_sphere"
            ),
        }
        rows = [_row(routes["sphere.training"], cl=1, slot=1, bonus_talent_id="talent.missing")]
        return _validation_envelope(routes, target_cl=1), _semantic_plan(rows), "CG1_NEW_SPHERE_BONUS_INVALID"

    if case == "duplicate-acquisition":
        routes = {
            "sphere.training": _route(
                "sphere.training", content_type="sphere", choice_type="new_sphere"
            ),
            "talent.bonus": _route(
                "talent.bonus",
                content_type="talent",
                choice_type="known_sphere_talent",
                owning_sphere_id="sphere.training",
            ),
        }
        row = _row(routes["sphere.training"], cl=1, slot=1, bonus_talent_id="talent.bonus")
        return _validation_envelope(routes, target_cl=1), _semantic_plan([row, deepcopy(row)]), "CG1_DELEGATED_DUPLICATE_CHOICE"

    if case == "excessive-training":
        routes = {}
        rows = []
        for index in range(1, 5):
            sphere_id = f"sphere.{index}"
            talent_id = f"talent.{index}"
            routes[sphere_id] = _route(sphere_id, content_type="sphere", choice_type="new_sphere")
            routes[talent_id] = _route(
                talent_id,
                content_type="talent",
                choice_type="known_sphere_talent",
                owning_sphere_id=sphere_id,
            )
            rows.append(
                _row(
                    routes[sphere_id],
                    cl=1,
                    slot=min(index, 3),
                    bonus_talent_id=talent_id,
                )
            )
        return _validation_envelope(routes, target_cl=1), _semantic_plan(rows), "CG1_TRAINED_CHOICE_CAPACITY_EXCEEDED"

    if case == "future-prerequisite":
        routes = {
            "sphere.training": _route(
                "sphere.training", content_type="sphere", choice_type="new_sphere"
            ),
            "talent.bonus": _route(
                "talent.bonus",
                content_type="talent",
                choice_type="known_sphere_talent",
                owning_sphere_id="sphere.training",
            ),
            "talent.future": _route(
                "talent.future",
                content_type="talent",
                choice_type="known_sphere_talent",
                owning_sphere_id="sphere.training",
                prerequisites=[{"operator": "requires", "target_id": "talent.prerequisite"}],
            ),
            "talent.prerequisite": _route(
                "talent.prerequisite",
                content_type="talent",
                choice_type="known_sphere_talent",
                owning_sphere_id="sphere.training",
            ),
        }
        rows = [
            _row(routes["sphere.training"], cl=1, slot=1, bonus_talent_id="talent.bonus"),
            # The prerequisite appears later in the ordered intent at CL2; it
            # cannot satisfy the dependent CL1 route retroactively.
            _row(routes["talent.future"], cl=1, slot=2),
            _row(routes["talent.prerequisite"], cl=2, slot=1),
        ]
        return _validation_envelope(routes, target_cl=2), _semantic_plan(rows), "CG1_TRAINED_CHOICE_ILLEGAL"

    raise AssertionError(f"unhandled negative validation case: {case}")


@pytest.mark.parametrize(
    "case",
    [
        "wrong-sphere-bonus",
        "missing-bonus",
        "duplicate-acquisition",
        "excessive-training",
        "future-prerequisite",
    ],
)
def test_real_semantic_validation_rejects_invalid_acquisition_routes(case: str) -> None:
    envelope, plan, expected_code = _negative_validation_case(case)

    with pytest.raises(FoundryError) as error:
        _validate_semantic_acquisition_intent(
            envelope,
            plan,
            {},
        )

    assert error.value.code == expected_code
