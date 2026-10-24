"""Provider-free Slice S4 checks for assembly, persistence, and walk routing."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.core import canonical_json, sha256_bytes, sha256_json
from character_creation.creative_controller import (
    ACTION_MENU,
    DETERMINISTIC_CREATIVE_CONTROLLER,
    CommittedState,
    ControllerRoutePersistence,
    WALK_COMPLETED,
    WALK_STARTED,
    WALK_FAILED,
    LinearWalkPersistence,
    build_background_ability_menu,
    build_ordinary_talent_menu,
    build_background_choice_menu,
    build_background_sphere_choice_menu,
    build_background_talent_choice_menu,
    build_origin_insight_choice_menu,
    build_origin_skill_menu,
    build_asi_milestone_menu,
    build_insight_occurrence_menu,
    build_method_choice_menu,
    build_path_choice_menu,
    build_path_progression_menu,
    build_point_buy_assignment_menu,
    build_point_buy_preset_menu,
    build_response,
    build_route_binding,
    commit_option,
    next_step,
    verify_controller_event_chain,
)
from character_creation.service import CharacterCreationExecutionService
from character_creation.creative_controller.linear_menus import (
    LinearMenuError,
    MAX_WALK_STEPS,
    _expected_count,
    _pair_rows,
    build_insight_priorities_menu,
    build_sphere_free_talent_pair_menu,
)
from character_creation.creative_controller.linear_walk import _step_descriptors


def _insert_project(db) -> None:
    now = "2026-09-04T00:00:00Z"
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO projects(
               project_id,working_name,status,revision,created_at,updated_at,
               target_factory_version,target_candidate_schema_version,target_gm_screen_version,
               catalog_build_hash,quality_target,project_json,
               compatibility_projection_status,compile_status,consumer_verification_status)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "s4-project",
                "S4",
                "draft",
                0,
                now,
                now,
                "x",
                "x",
                "x",
                None,
                "x",
                canonical_json({"project_id": "s4-project", "revision": 0}),
                "x",
                "x",
                "x",
            ),
        )


def _request(envelope: dict) -> dict:
    request = {
        "schema": "TianxiaFoundry.CharacterCreationPlanRequest.v3",
        "project_id": "s4-project",
        "project_revision": 0,
        "content_lock_hash": "a" * 64,
        "controller_route": DETERMINISTIC_CREATIVE_CONTROLLER,
        "controller_route_binding": build_route_binding(DETERMINISTIC_CREATIVE_CONTROLLER),
        "concept": "A patient cultivator",
        "delegated_choice_envelope": envelope,
    }
    request["request_sha256"] = CharacterCreationExecutionService.request_payload_sha256(request)
    return request


def _seed_run(db, request: dict, run_id: str = "cg1.run.s4") -> None:
    now = "2026-09-04T00:00:00Z"
    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO character_creation_runs(
               run_id,project_id,starting_revision,execution_mode,idempotency_key,
               request_json,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                "s4-project",
                0,
                "STANDARD_API",
                f"s4-key-{run_id}",
                canonical_json(request),
                "PREPARING_REQUEST",
                now,
                now,
            ),
        )
        ControllerRoutePersistence(db).bind_new_run(
            conn,
            run_id=run_id,
            project_id="s4-project",
            request_sha256=request["request_sha256"],
            binding=request["controller_route_binding"],
            created_at=now,
        )


def _envelope() -> dict:
    slots = {
        "path_choice": [
            {"id": "path.wood", "name": "Wood"},
            {"id": "path.iron", "name": "Iron"},
        ],
        "method_choice": [{"id": "method.breath", "name": "Breath"}],
        "foundation_choice": [{"id": "foundation.quiet", "name": "Quiet"}],
        "background_choice": [{"id": "background.wanderer", "name": "Wanderer"}],
        "background_sphere_choice": [{"id": "sphere.unfurl", "name": "Unfurl"}],
        "background_talent_choice": [{"id": "talent.listen", "name": "Listen"}],
    }

    return {
        "envelope_sha256": "b" * 64,
        "choices_by_slot": slots,
        "allowed_choices_by_slot": {
            slot: [row["id"] for row in rows] for slot, rows in slots.items()
        },
        "selection_limits_by_slot": {
            "path_choice": {"final_min": 1, "final_max": 1, "allow_none": False},
        },
        "subpath_choice_required": False,
        "compatibility_envelope": {"compatible_method_ids": ["method.breath"]},
        "background_package_linkage": {
            "background.wanderer": {
                "spheres": [{"id": "sphere.unfurl", "name": "Unfurl"}],
                "sphere.unfurl": {
                    "talents": [{"id": "talent.listen", "name": "Listen"}],
                },
            }
        },
    }


def test_l4_frozen_ordinary_count_maps_typed_rows_into_assembled_response() -> None:
    request = {
        "request_sha256": "a" * 64,
        "concept": "A patient cultivator",
    }
    rows = {
        "talent.fire.first": {"choice_id": "talent.fire.first", "name": "First Flame", "content_type": "talent"},
        "talent.fire.second": {"choice_id": "talent.fire.second", "name": "Second Flame", "content_type": "talent"},
    }
    authority = {
        choice_id: {
            "authority_complete": True,
            "allowed_channels": ["level-choice"],
            "allowed_kinds": ["level_talent_acquisition"],
            "minimum_cl": index,
            "sphere_id": "sphere.fire",
        }
        for index, choice_id in enumerate(rows, start=1)
    }
    envelope = {
        "ordinary_talent_count": 2,
        "choices_by_slot": {"advancement_skeleton": rows},
        "allowed_choice_ids_by_slot": {"advancement_skeleton": list(rows)},
        "typed_choice_authority_by_slot": {
            "advancement_skeleton": {
                "stage2_authority_by_choice": authority,
            },
        },
    }
    # Level talents come only from known Spheres: the CL1 free pair opens
    # sphere.fire before any ordinary talent from it can be offered.
    state = CommittedState.empty().with_pair("sphere.fire", "talent.fire.free")
    descriptors = _step_descriptors(request, envelope, state)
    assert ("ordinary_talent:1", "ordinary_talent", "ordinary_talent:1") in descriptors

    first = build_ordinary_talent_menu(request, envelope, state, cl=1)
    assert first is not None
    first_option = next(option for option in first.options if option.choice_ids == ("talent.fire.first",))
    state = commit_option(first, first_option.option_id, state)
    second = build_ordinary_talent_menu(request, envelope, state, cl=2)
    assert second is not None
    second_option = next(option for option in second.options if option.choice_ids == ("talent.fire.second",))
    state = commit_option(second, second_option.option_id, state)
    state = state.with_identity("Li Wei", "Quiet Walker")
    response = json.loads(build_response(request, state))
    assert response["acquisition_intent"]["ordinary_talent_ids"] == [
        "talent.fire.first",
        "talent.fire.second",
    ]
    assert response["selection_intent"]["by_slot"]["advancement_skeleton"] == response["acquisition_intent"]["ordinary_talent_ids"]


def test_l4_typed_grant_aliases_expose_bootstrap_pair_capacity_and_rows() -> None:
    pair = {
        "sphere_id": "sphere.fire",
        "talent_id": "talent.fire.free",
        "sphere_name": "Fire",
        "talent_name": "First Flame",
    }

    def grant_lock(count: int, rows: list[dict]) -> dict:
        return {
            "field": "character_sheet.canonical_grant_plan",
            "value": {
                "grant_accounting": {
                    "free_sphere_talent_grant_count": count,
                    "free_sphere_talent_grants": rows,
                },
            },
        }

    placeholder_request = {
        "typed_choice_snapshot": {
            "typed_locks": [
                {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
                {"field": "character_sheet.canonical_grant_plan_origin", "value": "compatibility_projection"},
                grant_lock(0, []),
            ],
        },
        "stage1_prompt": {
            "envelope": {
                "user_locks": [grant_lock(0, [])],
            },
        },
    }
    envelope = {"ordinary_talent_count": 1}
    assert _expected_count(placeholder_request, envelope, "sphere_free_talent_pairs") == 1

    row_request = {
        **placeholder_request,
        "typed_choice_snapshot": {
            "typed_locks": [
                {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
                {"field": "character_sheet.canonical_grant_plan_origin", "value": "compatibility_projection"},
                grant_lock(1, [pair]),
            ],
        },
    }
    assert _pair_rows(row_request, envelope) == [pair]
    menu = build_sphere_free_talent_pair_menu(row_request, envelope)
    assert menu is not None
    assert menu.options[0].choice_ids == ("sphere.fire", "talent.fire.free")


def test_l4_production_point_buy_lock_maps_provider_presets_into_s3_menus() -> None:
    abilities = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
    costs = {str(value): cost for value, cost in ((8, 0), (9, 1), (10, 2), (11, 3), (12, 4), (13, 5), (14, 7), (15, 9))}
    presets = [
        {"scores": [15, 14, 13, 12, 10, 8], "cost": 27, "permutable_across_abilities": True},
        {"scores": [15, 15, 12, 11, 10, 8], "cost": 27, "permutable_across_abilities": False},
    ]
    request = {
        "request_sha256": "a" * 64,
        "bounded_choice_contract": {
            "fields": {
                "ability_scores": {
                    "type": "point_buy_scores",
                    "abilities": abilities,
                    "allowed_values": list(range(8, 16)),
                    "budget": 27,
                },
            },
        },
        "typed_choice_snapshot": {
            "typed_locks": [
                {
                    "field": "character_sheet.ability_point_buy",
                    "value": {
                        "auto_abilities": abilities,
                        "budget": 27,
                        "completion": "pending",
                        "fixed_scores": {},
                        "points_remaining": 27,
                        "points_spent": 0,
                    },
                },
            ],
        },
    }
    envelope = {
        "envelope_sha256": "b" * 64,
        "linear_provider_payload": {
            "bounded_choice_summary": {
                "ability_scores": {
                    "abilities": abilities,
                    "allowed_values": list(range(8, 16)),
                    "cost_by_value": costs,
                    "budget": 27,
                    "exact_budget": 27,
                    "legal_score_presets": presets,
                },
            },
        },
    }
    descriptors = _step_descriptors(request, envelope, CommittedState.empty())
    assert ("point_buy_preset", "point_buy_preset", "point_buy_preset") in descriptors

    preset_menu = build_point_buy_preset_menu(request, envelope)
    assert preset_menu is not None and preset_menu.min_choices == preset_menu.max_choices == 1
    permutable = next(option for option in preset_menu.options if ":permutable:" in option.choice_ids[0])
    state = commit_option(preset_menu, permutable.option_id)
    assignment_menu = build_point_buy_assignment_menu(request, envelope, state)
    assert assignment_menu is not None and len(assignment_menu.options) <= 12
    committed = commit_option(assignment_menu, assignment_menu.options[0].option_id, state)
    assert set(committed.bounded["ability_scores"]) == set(abilities)


def test_l4_production_method_menu_uses_materializable_typed_slot_authority() -> None:
    compatible_methods = ["method.unmaterializable", "method.materializable"]
    materializable_method = "method.materializable"
    path_method_authority = {
        "schema": "TianxiaFoundry.PathMethodAuthority.v1",
        "compatible_method_ids": compatible_methods,
        "method_granted_path_ids": {
            method_id: ["path.wood"] for method_id in compatible_methods
        },
        "required_advancing_path_ids": [],
    }
    request = {
        "request_sha256": "a" * 64,
        "typed_choice_snapshot": {
            "typed_locks": [
                {"field": "character_sheet.method_access_plan", "value": None},
                {
                    "field": "character_sheet.path_method_compatibility",
                    "value": path_method_authority,
                },
            ]
        },
        "stage1_prompt": {
            "envelope": {
                "user_locks": [
                    {"field": "character_sheet.method_access_plan", "value": None},
                    {
                        "field": "character_sheet.path_method_compatibility",
                        "value": path_method_authority,
                    },
                ]
            }
        },
    }
    envelope = {
        "path_method_authority": path_method_authority,
        "typed_choice_authority_by_slot": {
            "method_choice": {
                "compatible_method_ids": compatible_methods,
                "planning_only_typed_method_rows": [
                    {"method_id": "method.unmaterializable"}
                ],
            }
        },
        "choices_by_slot": {
            "method_choice": [
                {"choice_id": materializable_method, "name": "Materializable method"}
            ]
        },
        "allowed_choice_ids_by_slot": {
            "method_choice": [materializable_method]
        },
        "selection_limits_by_slot": {
            "method_choice": {"final_min": 1, "final_max": 1, "allow_none": False}
        },
        "owner_locks": {
            "by_slot": {"method_choice": []},
            "zero_owner_path_locks_are_legal": True,
        },
    }
    state = CommittedState.empty().with_slot("path_choice", ["path.wood"])
    menu = build_method_choice_menu(request, envelope, state)
    assert menu is not None and menu.min_choices == menu.max_choices == 1
    assert {choice_id for option in menu.options for choice_id in option.choice_ids} == {
        materializable_method
    }


def test_l4_zero_lock_method_menu_recovers_when_compatibility_allowlist_drifts() -> None:
    from copy import deepcopy

    legal_method = "method.materializable"
    request = {"request_sha256": "a" * 64}
    envelope = {
        "envelope_sha256": "b" * 64,
        "choices_by_slot": {
            "method_choice": {
                legal_method: {"choice_id": legal_method, "name": "Materializable method"},
            },
        },
        "allowed_choice_ids_by_slot": {"method_choice": [legal_method]},
        "selection_limits_by_slot": {
            "path_choice": {"final_min": 1, "final_max": 1, "allow_none": False},
            "method_choice": {"final_min": 1, "final_max": 1, "allow_none": False},
        },
        "owner_locks": {
            "by_slot": {"method_choice": [], "path_choice": [], "subpath_choice": ["sub.wood"]},
            "zero_owner_path_locks_are_legal": True,
        },
        # The planner allowlist drifted from grant coverage.  The delegated
        # validator never checks this list, so the required zero-owner-lock
        # pick must still be offered as a 1/1 menu instead of skipped.
        "path_method_authority": {
            "compatible_method_ids": ["method.stale"],
            "method_granted_path_ids": {legal_method: ["path.wood"]},
        },
    }
    state = CommittedState.empty().with_bounded("identity", {"name": "Test Name", "title": "Test Title"}).with_slot("path_choice", ["path.wood"])
    menu = build_method_choice_menu(request, envelope, state)
    assert menu is not None and menu.min_choices == menu.max_choices == 1
    assert {choice_id for option in menu.options for choice_id in option.choice_ids} == {legal_method}
    committed = commit_option(menu, menu.options[0].option_id, state)
    assert committed.by_slot["method_choice"] == [legal_method]

    step = next_step(request, envelope, state, [])
    assert step.step_id == "method_choice" and step.menu is not None
    assert step.committed.by_slot["method_choice"] == [legal_method]

    # A run with owner-locked Paths may still lawfully defer Method, so the
    # drifted allowlist keeps skipping the menu there.
    deferred_envelope = deepcopy(envelope)
    deferred_envelope["owner_locks"] = {
        "by_slot": {"method_choice": [], "path_choice": ["path.wood"]},
    }
    assert build_method_choice_menu(request, deferred_envelope, state) is None


def test_l4_path_choice_preserves_grant_covering_method() -> None:
    request = {"request_sha256": "a" * 64}
    envelope = {
        "envelope_sha256": "b" * 64,
        "choices_by_slot": {
            "path_choice": [
                {"choice_id": "path.a", "name": "Path A"},
                {"choice_id": "path.b", "name": "Path B"},
                {"choice_id": "path.c", "name": "Path C"},
            ],
            "method_choice": [
                {"choice_id": "method.m1", "name": "Method M1"},
            ],
        },
        "allowed_choice_ids_by_slot": {
            "path_choice": ["path.a", "path.b", "path.c"],
            "method_choice": ["method.m1"],
        },
        "selection_limits_by_slot": {
            "path_choice": {"final_min": 1, "final_max": 3, "allow_none": False},
            "method_choice": {"final_min": 1, "final_max": 1, "allow_none": False},
        },
        "owner_locks": {
            "by_slot": {},
            "zero_owner_path_locks_are_legal": True,
        },
        "path_method_authority": {
            "compatible_method_ids": ["method.m1"],
            "method_granted_path_ids": {"method.m1": ["path.a", "path.b"]},
        },
    }
    empty = CommittedState.empty()
    assert build_method_choice_menu(request, envelope, empty) is not None
    assert {option.choice_ids for option in build_method_choice_menu(request, envelope, empty).options} == {
        ("method.m1",)
    }

    first = build_path_choice_menu(request, envelope, empty)
    assert first is not None
    first_ids = {choice_id for option in first.options for choice_id in option.choice_ids}
    assert first_ids == {"path.a", "path.b"}

    state = commit_option(first, next(option for option in first.options if option.choice_ids == ("path.a",)).option_id, empty)
    second = build_path_choice_menu(request, envelope, state)
    assert second is not None
    second_ids = {choice_id for option in second.options for choice_id in option.choice_ids}
    assert second_ids == {"path.b"}

    state = commit_option(second, second.options[0].option_id, state)
    assert build_method_choice_menu(request, envelope, state) is not None
    third = build_path_choice_menu(request, envelope, state)
    assert third is None or all("path.c" not in option.choice_ids for option in third.options)

    dead_end = CommittedState.empty().with_slot("path_choice", ["path.a", "path.b", "path.c"])
    assert build_method_choice_menu(request, envelope, dead_end) is None


def test_l4_production_progression_rows_project_exact_cl_routes() -> None:
    request = {"request_sha256": "a" * 64}
    envelope = {
        "path_progression_choices": [
            {"cl": 1, "path_ids": ["path.iron", "path.wood"]},
            {"cl": 2, "path_ids": ["path.wood"]},
        ],
        "owner_locks": {
            "by_slot": {"path_progression": []},
            "zero_owner_path_locks_are_legal": True,
        },
    }
    state = CommittedState.empty().with_slot(
        "path_choice", ["path.wood", "path.iron"]
    )
    menu = build_path_progression_menu(request, envelope, state, cl=1)
    assert menu is not None and menu.min_choices == menu.max_choices == 1
    assert {option.choice_ids for option in menu.options} == {
        ("path.iron",),
        ("path.wood",),
    }
    committed = commit_option(menu, menu.options[0].option_id, state)
    assert committed.bounded["path_progression_by_cl"]["1"] in {
        "path.iron",
        "path.wood",
    }
    assert build_path_progression_menu(request, envelope, committed, cl=1) is None


def test_l4_progression_stops_at_sealed_target_cl() -> None:
    request = {"request_sha256": "a" * 64}
    envelope = {
        "frozen_owner_target_cl": {"value": 2},
        "path_progression_choices": [
            {"cl": 1, "path_ids": ["path.iron", "path.wood"]},
            {"cl": 2, "path_ids": ["path.iron", "path.wood"]},
            {"cl": 3, "path_ids": ["path.iron", "path.wood"]},
        ],
        "owner_locks": {
            "by_slot": {"path_progression": []},
            "zero_owner_path_locks_are_legal": True,
        },
    }
    state = CommittedState.empty().with_slot(
        "path_choice", ["path.wood", "path.iron"]
    )

    assert build_path_progression_menu(request, envelope, state, cl=1) is not None
    # Both selected Paths must advance by CL 2. With CL 1 committed to iron,
    # CL 2 is a (forced) step; asked for CL 2 while CL 1 is still unassigned,
    # no pick can complete a legal split and the menu fails closed.
    advanced = state.with_path_progression("1", "path.iron")
    assert build_path_progression_menu(request, envelope, advanced, cl=2) is not None
    with pytest.raises(LinearMenuError) as unsatisfiable:
        build_path_progression_menu(request, envelope, state, cl=2)
    assert unsatisfiable.value.code == "DCC_LINEAR_PROGRESSION_UNSATISFIABLE"
    assert build_path_progression_menu(request, envelope, state, cl=3) is None
    progression_steps = [
        step_id
        for step_id, _step_kind, _slot_id in _step_descriptors(request, envelope, state)
        if step_id.startswith("path_progression:")
    ]
    assert progression_steps == ["path_progression:1", "path_progression:2"]


def test_l4_progression_singleton_preserved_when_response_authority_ambiguous() -> None:
    # The delegated validator requires one exact Path route at every
    # ambiguous CL.  When the bounded contract narrows an ambiguous
    # response authority to a singleton, the walk must still offer that
    # singleton as an explicit 1/1 CL1 pick instead of skipping it.
    request = {
        "request_sha256": "a" * 64,
        "bounded_choice_contract": {
            "fields": {
                "path_progression_by_cl": {
                    "1": ["path.wood"],
                },
            },
        },
    }
    envelope = {
        "envelope_sha256": "b" * 64,
        "response_contract": {
            "presented_legal_path_progression_ids_by_cl": {
                "1": ["path.iron", "path.wood"],
            },
        },
    }
    state = CommittedState.empty().with_slot("path_choice", ["path.iron", "path.wood"])
    assert ("path_progression:1", "path_progression", "path_progression:1") in _step_descriptors(
        request, envelope, state
    )
    menu = build_path_progression_menu(request, envelope, state, cl=1)
    assert menu is not None
    assert menu.step_id == "path_progression:1" and menu.min_choices == menu.max_choices == 1
    assert {option.choice_ids for option in menu.options} == {("path.wood",)}
    committed = commit_option(menu, menu.options[0].option_id, state)
    assert committed.bounded["path_progression_by_cl"]["1"] == "path.wood"
    assert build_path_progression_menu(request, envelope, committed, cl=1) is None


def test_l4_progression_routes_are_limited_to_selected_paths() -> None:
    # Production rows advertise every selectable Path that can advance at a
    # CL.  The delegated validator only admits a route among the selected
    # Paths and auto-resolves a selected singleton, so a one-Path character
    # must walk zero progression steps and a two-Path character must only be
    # offered the two Paths it selected.
    request = {"request_sha256": "a" * 64}
    envelope = {
        "frozen_owner_target_cl": {"value": 3},
        "path_progression_choices": [
            {"cl": cl, "path_ids": ["path.body", "path.qi", "path.spirit"]}
            for cl in range(1, 4)
        ],
        "response_contract": {
            "presented_legal_path_progression_ids_by_cl": {
                str(cl): ["path.body", "path.qi", "path.spirit"] for cl in range(1, 4)
            },
        },
        "owner_locks": {
            "by_slot": {"path_progression": []},
            "zero_owner_path_locks_are_legal": True,
        },
    }

    unselected = CommittedState.empty()
    assert build_path_progression_menu(request, envelope, unselected, cl=1) is None

    single = CommittedState.empty().with_slot("path_choice", ["path.qi"])
    for cl in range(1, 4):
        assert build_path_progression_menu(request, envelope, single, cl=cl) is None
    assert not [
        step_id
        for step_id, _kind, _slot in _step_descriptors(request, envelope, single)
        if step_id.startswith("path_progression:")
    ]

    dual = CommittedState.empty().with_slot("path_choice", ["path.qi", "path.body"])
    menu = build_path_progression_menu(request, envelope, dual, cl=1)
    assert menu is not None and menu.min_choices == menu.max_choices == 1
    assert {option.choice_ids for option in menu.options} == {("path.body",), ("path.qi",)}
    committed = commit_option(menu, menu.options[0].option_id, dual)
    assert committed.bounded["path_progression_by_cl"]["1"] in {"path.body", "path.qi"}
    assert build_path_progression_menu(request, envelope, committed, cl=1) is None


def test_l4_slot_menus_mirror_frozen_prerequisites_and_incompatibilities() -> None:
    # Production Insight priority rows carry typed Path/Sphere prerequisites
    # and the delegated validator checks every selected priority against the
    # full selected set.  The menu must therefore only offer rows whose
    # frozen prerequisites the committed walk already satisfies, and must
    # close rows an already committed choice excludes.
    request = {"request_sha256": "a" * 64}
    envelope = {
        "frozen_owner_target_cl": {"value": 10},
        "selection_limits_by_slot": {"insight_priorities": {"final_min": 0, "final_max": 3}},
        "choices_by_slot": {
            "path_choice": [
                {"choice_id": "path.qi", "name": "Qi"},
                {"choice_id": "path.body", "name": "Body"},
            ],
            "sphere_priorities": [{"choice_id": "sphere.alchemy", "name": "Alchemy"}],
            "insight_priorities": [
                {
                    "choice_id": "insight.needs_body",
                    "name": "Needs Body",
                    "prerequisites": [{"kind": "path", "operator": "requires", "target_id": "path.body"}],
                },
                {
                    "choice_id": "insight.needs_alchemy",
                    "name": "Needs Alchemy",
                    "prerequisites": [{"kind": "sphere", "operator": "requires", "target_id": "sphere.alchemy"}],
                },
                {
                    "choice_id": "insight.one_of",
                    "name": "One Of",
                    "legality": {"prerequisites": [{"operator": "one_of", "target_ids": ["path.body", "path.qi"]}]},
                },
                {
                    "choice_id": "insight.not_qi",
                    "name": "Not Qi",
                    "prerequisites": [{"operator": "not", "target_id": "path.qi"}],
                },
                {
                    "choice_id": "insight.too_high",
                    "name": "Too High",
                    "availability": {"minimum_cl": 12},
                },
                {
                    "choice_id": "insight.clashes",
                    "name": "Clashes",
                    "incompatibilities": [{"target_id": "insight.one_of"}],
                },
                {
                    "choice_id": "insight.untyped",
                    "name": "Untyped",
                    "prerequisites": ["free text"],
                },
                {"choice_id": "insight.free", "name": "Free"},
            ],
        },
        "owner_locks": {"by_slot": {}, "zero_owner_path_locks_are_legal": True},
    }
    state = (
        CommittedState.empty()
        .with_slot("path_choice", ["path.qi"])
        .with_slot("sphere_priorities", ["sphere.alchemy"])
    )
    menu = build_insight_priorities_menu(request, envelope, state, step_id="insight_priorities:1")
    assert menu is not None
    offered = {choice_id for option in menu.options for choice_id in option.choice_ids}
    assert offered == {"insight.needs_alchemy", "insight.one_of", "insight.clashes", "insight.free"}

    # Once the one_of Insight is committed, the row it clashes with closes.
    committed = commit_option(menu, next(o for o in menu.options if o.choice_ids == ("insight.one_of",)).option_id, state)
    second = build_insight_priorities_menu(request, envelope, committed, step_id="insight_priorities:2")
    assert second is not None
    offered = {choice_id for option in second.options for choice_id in option.choice_ids}
    assert offered == {"insight.needs_alchemy", "insight.free"}

    # Rows without any typed legality are left untouched.
    assert build_path_choice_menu(request, envelope, CommittedState.empty()) is not None


def test_l4_optional_priority_none_converges_before_the_step_ceiling() -> None:
    request = {"request_sha256": "a" * 64}
    envelope = {
        "frozen_owner_target_cl": {"value": 15},
        "choices_by_slot": {
            "item_priorities": [{"choice_id": "item.optional", "name": "Optional Item"}],
        },
        "allowed_choice_ids_by_slot": {"item_priorities": ["item.optional"]},
        "selection_limits_by_slot": {
            "insight_priorities": {"final_min": 0, "final_max": 0, "allow_none": True},
            "item_priorities": {"final_min": 0, "final_max": 8, "allow_none": True},
        },
        "owner_locks": {
            "by_slot": {"item_priorities": []},
            "zero_owner_path_locks_are_legal": True,
        },
    }
    state = CommittedState.empty().with_bounded("identity", {"name": "Test Name", "title": "Test Title"})
    first = next_step(request, envelope, state, [])
    assert first.step_id == "item_priorities:1" and first.action == ACTION_MENU
    assert first.menu is not None
    none = next(option for option in first.menu.options if option.kind == "none")
    state = commit_option(first.menu, none.option_id, state)
    # Identity now opens the walk, so after the declined optional pick the
    # walk converges: it moves past item priorities (here to its completion
    # check, which this minimal fixture cannot satisfy) instead of looping.
    from character_creation.creative_controller.linear_walk import LinearWalkError as _WalkError
    try:
        second = next_step(
            request,
            envelope,
            state,
            [{"event_type": "STEP_COMMITTED", "step_id": first.step_id, "choice_ids": []}],
        )
    except _WalkError as exc:
        assert exc.code == "DCC_LINEAR_MANDATORY_STEPS_INCOMPLETE"
    else:
        assert not second.step_id.startswith("item_priorities")


def test_l4_priorities_prompts_frame_coherent_character_choice() -> None:
    from character_creation.creative_controller import (
        StepMenu,
        StepOption,
        build_insight_priorities_menu,
        build_item_priorities_menu,
        build_response_schema,
        build_stable_prefix,
        build_step_prompt,
    )
    from character_creation.creative_controller.linear_prompt import (
        MAX_PREFIX_LENGTH,
        MAX_SUFFIX_LENGTH,
        OPERATOR_CONTRACT,
    )

    request = {"request_sha256": "a" * 64, "concept": "A patient cultivator"}
    envelope = {
        "choices_by_slot": {
            "path_choice": [{"id": "path.wood", "name": "Wood"}],
            "insight_priorities": [{"choice_id": "insight.calm", "name": "Calm Insight"}],
            "item_priorities": [{"choice_id": "item.sash", "name": "Travel Sash"}],
        },
        "allowed_choice_ids_by_slot": {
            "insight_priorities": ["insight.calm"],
            "item_priorities": ["item.sash"],
        },
        "selection_limits_by_slot": {
            "insight_priorities": {"final_min": 0, "final_max": 1, "allow_none": True},
            "item_priorities": {"final_min": 0, "final_max": 1, "allow_none": True},
        },
        "owner_locks": {
            "by_slot": {},
            "zero_owner_path_locks_are_legal": True,
        },
    }
    state = CommittedState.empty().with_slot("path_choice", ["path.wood"])
    coherence = "Choose what this built character would prioritize next; this shapes the final sheet."
    prefix = build_stable_prefix(request, envelope)
    assert "The Factory, not this reply, is authoritative for legality." in OPERATOR_CONTRACT
    assert prefix.startswith("[system]\n" + OPERATOR_CONTRACT.rstrip("\n"))
    assert len(prefix) <= MAX_PREFIX_LENGTH

    for builder in (build_insight_priorities_menu, build_item_priorities_menu):
        menu = builder(request, envelope, state)
        assert menu is not None
        prompt = build_step_prompt(request, envelope, state, menu)
        assert prompt.startswith(prefix)
        suffix = prompt[len(prefix):]
        assert coherence in suffix
        assert suffix.index("Already chosen:") < suffix.index(coherence) < suffix.index("Options:")
        assert "Wood" in suffix and "path.wood" not in prompt
        assert 'Reply with one JSON object: {"option_id":"<one of the IDs above>"}' in suffix
        assert build_response_schema(menu) == {
            "type": "object",
            "additionalProperties": False,
            "required": ["option_id"],
            "properties": {"option_id": {"type": "string", "enum": list(menu.option_ids)}},
        }
        assert len(suffix) <= MAX_SUFFIX_LENGTH
        assert len(prompt) <= MAX_PREFIX_LENGTH + MAX_SUFFIX_LENGTH

    sphere_menu = StepMenu(
        step_id="sphere_priorities",
        step_kind="sphere_priorities",
        ordinal=1,
        title="Sphere priorities",
        min_choices=1,
        max_choices=1,
        options=(StepOption("dcc.opt." + "s" * 24, ("sphere.fire",), "Sphere bundle", "bundle"),),
        page_id="sphere_priorities:page:1",
    )
    assert coherence not in build_step_prompt(request, envelope, state, sphere_menu)


def test_l4_production_asi_projection_commits_one_typed_resolution() -> None:
    milestone_id = "milestone.path.fire.cl4"
    request = {"request_sha256": "a" * 64}
    envelope = {
        "linear_provider_payload": {
            "response_contract": {
                "required_milestone_resolutions": {
                    milestone_id: {
                        "milestone_id": milestone_id,
                        "path_id": "path.fire",
                        "cl": 4,
                        "resolution_cardinality": "exactly_one",
                        "resolution_options": {
                            "ability_score_change": {
                                "destination": (
                                    "bounded_choices.ability_score_changes_by_milestone_id."
                                    + milestone_id
                                ),
                                "constraints": {
                                    "allowed_abilities": ["STR", "DEX"],
                                    "allowed_deltas": [1, 2],
                                    "budget": 2,
                                    "cap": 15,
                                },
                            }
                        },
                    }
                }
            }
        }
    }
    state = CommittedState.empty().with_slot("path_choice", ["path.fire"]).with_bounded(
        "ability_scores",
        {"STR": 13, "DEX": 14, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
    )
    menu = build_asi_milestone_menu(
        request, envelope, state, milestone_id=milestone_id
    )
    assert menu is not None and menu.min_choices == menu.max_choices == 1
    assert len(menu.options) == 2
    committed = commit_option(menu, menu.options[0].option_id, state)
    changes = committed.bounded["ability_score_changes_by_milestone_id"]
    assert set(changes) == {milestone_id}
    assert isinstance(changes[milestone_id]["deltas"], dict)
    response = json.loads(
        build_response(request, committed.with_identity("Li Wei", "Quiet Walker"))
    )
    assert response["bounded_choices"]["ability_score_changes_by_milestone_id"] == changes


def test_l4_production_asi_without_allowed_abilities_defaults_to_six_and_commits() -> None:
    milestone_id = "tianxia.path.body_refining.feature.ability_score_improvement_or_cultivation_insight.cl4"
    request = {"request_sha256": "a" * 64}
    envelope = {
        "linear_provider_payload": {
            "response_contract": {
                "required_milestone_resolutions": {
                    milestone_id: {
                        "milestone_id": milestone_id,
                        "path_id": "tianxia.path.body_refining",
                        "cl": 4,
                        "resolution_cardinality": "exactly_one",
                        "resolution_options": {
                            "ability_score_change": {
                                "destination": (
                                    "bounded_choices.ability_score_changes_by_milestone_id."
                                    + milestone_id
                                ),
                                "constraints": {
                                    "allowed_deltas": [1, 2],
                                    "budget": 2,
                                    "cap": 14,
                                },
                            }
                        },
                    }
                }
            }
        }
    }
    state = CommittedState.empty().with_slot("path_choice", ["tianxia.path.body_refining"]).with_bounded(
        "ability_scores",
        {"STR": 12, "DEX": 13, "CON": 14, "INT": 14, "WIS": 14, "CHA": 14},
    )
    menu = build_asi_milestone_menu(
        request, envelope, state, milestone_id=milestone_id
    )
    assert menu is not None and menu.min_choices == menu.max_choices == 1
    assert {frozenset(option.choice_ids) for option in menu.options} == {
        frozenset(("asi:STR:2",)),
        frozenset(("asi:DEX:1", "asi:STR:1")),
    }
    committed = commit_option(menu, menu.options[0].option_id, state)
    changes = committed.bounded["ability_score_changes_by_milestone_id"]
    assert set(changes) == {milestone_id}
    assert sum(changes[milestone_id]["deltas"].values()) == 2


def test_l4_dual_kind_asi_insight_milestone_commits_exactly_one_resolution() -> None:
    milestone_id = "tianxia.path.body_refining.feature.ability_score_improvement_or_cultivation_insight.cl8"
    request = {"request_sha256": "a" * 64}
    envelope = {
        "linear_provider_payload": {
            "response_contract": {
                "required_milestone_resolutions": {
                    milestone_id: {
                        "milestone_id": milestone_id,
                        "path_id": "tianxia.path.body_refining",
                        "cl": 8,
                        "effective_cl": 8,
                        "resolution_cardinality": "exactly_one",
                        "allowed_resolutions": [
                            "ability_score_change",
                            "cultivation_insight_acquisition",
                        ],
                        "resolution_options": {
                            "ability_score_change": {
                                "destination": (
                                    "bounded_choices.ability_score_changes_by_milestone_id."
                                    + milestone_id
                                ),
                                "constraints": {
                                    "allowed_deltas": [2],
                                    "budget": 2,
                                    "cap": 14,
                                },
                            },
                            "cultivation_insight_acquisition": {
                                "destination": "acquisition_intent.insight_occurrences[]",
                                "allowed_insight_ids": ["insight.core"],
                            },
                        },
                    }
                }
            }
        }
    }
    base = CommittedState.empty().with_slot("path_choice", ["tianxia.path.body_refining"]).with_bounded(
        "ability_scores",
        {"STR": 12, "DEX": 13, "CON": 14, "INT": 14, "WIS": 14, "CHA": 14},
    )
    assert build_asi_milestone_menu(request, envelope, base, milestone_id=milestone_id) is not None
    assert build_insight_occurrence_menu(request, envelope, base, milestone_id=milestone_id) is not None

    asi_menu = build_asi_milestone_menu(request, envelope, base, milestone_id=milestone_id)
    assert asi_menu is not None
    asi_committed = commit_option(asi_menu, asi_menu.options[0].option_id, base)
    assert build_insight_occurrence_menu(request, envelope, asi_committed, milestone_id=milestone_id) is None
    assert build_asi_milestone_menu(request, envelope, asi_committed, milestone_id=milestone_id) is None
    asi_descriptors = {step_id for step_id, _kind, _group in _step_descriptors(request, envelope, asi_committed)}
    assert f"insight_occurrence:{milestone_id}" not in asi_descriptors
    assert f"asi_milestone:{milestone_id}" not in asi_descriptors

    insight_menu = build_insight_occurrence_menu(request, envelope, base, milestone_id=milestone_id)
    assert insight_menu is not None
    insight_committed = commit_option(insight_menu, insight_menu.options[0].option_id, base)
    assert build_asi_milestone_menu(request, envelope, insight_committed, milestone_id=milestone_id) is None
    assert build_insight_occurrence_menu(request, envelope, insight_committed, milestone_id=milestone_id) is None
    insight_descriptors = {step_id for step_id, _kind, _group in _step_descriptors(request, envelope, insight_committed)}
    assert f"insight_occurrence:{milestone_id}" not in insight_descriptors
    assert f"asi_milestone:{milestone_id}" not in insight_descriptors


def test_l4_production_typed_background_linkage_keeps_required_slots_visible() -> None:
    slots = {
        "background_choice": [{"choice_id": "background.production", "name": "Production Background"}],
        "background_sphere_choice": [{"choice_id": "sphere.production", "name": "Production Sphere"}],
        "background_talent_choice": [{"choice_id": "talent.production", "name": "Production Talent"}],
        "origin_insight_choice": [{"choice_id": "insight.production", "name": "Production Insight"}],
    }
    envelope = {
        "envelope_sha256": "b" * 64,
        "choices_by_slot": slots,
        "allowed_choice_ids_by_slot": {
            slot: [row["choice_id"] for row in rows] for slot, rows in slots.items()
        },
        "selection_limits_by_slot": {
            slot: {"final_min": 1, "final_max": 1, "allow_none": False}
            for slot in slots
        },
        "owner_locks": {
            "by_slot": {slot: [] for slot in slots},
            "zero_owner_path_locks_are_legal": True,
        },
        "typed_choice_authority_by_slot": {
            "background_choice": {
                "background_package_linkage": {
                    "background.production": [
                        {
                            "background_sphere_choice_id": "sphere.production",
                            "background_talent_choice_id": "talent.production",
                            "package_index": 1,
                            "sphere_record_id": "sphere.record.production",
                            "talent_record_id": "talent.record.production",
                        }
                    ]
                }
            }
        },
        "bounded_choice_contract": {
            "starting_proficiency_choice_contract": {
                "fields": {"origin_skill_choices_by_origin_id": {}}
            }
        },
    }
    request = {"request_sha256": "a" * 64, "concept": "A patient cultivator"}
    state = CommittedState.empty()

    background = build_background_choice_menu(request, envelope, state)
    assert background is not None and background.options[0].choice_ids == ("background.production",)
    state = commit_option(background, background.options[0].option_id, state)

    sphere = build_background_sphere_choice_menu(request, envelope, state)
    assert sphere is not None and sphere.options[0].choice_ids == ("sphere.production",)
    state = commit_option(sphere, sphere.options[0].option_id, state)

    talent = build_background_talent_choice_menu(request, envelope, state)
    assert talent is not None and talent.options[0].choice_ids == ("talent.production",)
    origin = build_origin_insight_choice_menu(request, envelope, state)
    assert origin is not None and origin.options[0].choice_ids == ("insight.production",)


def test_l4_background_ability_projection_commits_exact_bounded_fields() -> None:
    request = {
        "request_sha256": "a" * 64,
        "bounded_choice_contract": {
            "fields": {
                "background_ability": {
                    "type": "string",
                    "allowed_values": ["INT", "WIS"],
                },
                "background_ability_amount": {
                    "type": "integer",
                    "allowed_values": [1, 2],
                },
            }
        },
    }
    envelope = {
        "envelope_sha256": "b" * 64,
        "choices_by_slot": {
            "background_choice": [{"choice_id": "background.production", "name": "Production Background"}]
        },
        "allowed_choice_ids_by_slot": {"background_choice": ["background.production"]},
        "selection_limits_by_slot": {
            "background_ability": {"final_min": 1, "final_max": 1, "allow_none": False}
        },
        "owner_locks": {
            "by_slot": {"background_ability": []},
            "zero_owner_path_locks_are_legal": True,
        },
        "linear_provider_payload": {
            "bounded_choice_summary": {
                "background_ability_candidates": {
                    "background.production": {
                        "allowed_abilities": ["WIS"],
                        "allowed_amounts": [1, 2],
                    }
                }
            },
            "response_contract": {
                "allowed_bounded_choice_keys": [
                    "background_ability",
                    "background_ability_amount",
                ]
            },
        },
    }
    state = CommittedState.empty().with_slot("background_choice", ["background.production"])
    menu = build_background_ability_menu(request, envelope, state)
    assert menu is not None and menu.min_choices == menu.max_choices == 1
    assert {option.choice_ids for option in menu.options} == {
        ("WIS", "background_ability_amount:1"),
        ("WIS", "background_ability_amount:2"),
    }
    committed = commit_option(menu, menu.options[0].option_id, state)
    assert committed.bounded["background_ability"] == "WIS"
    assert committed.bounded["background_ability_amount"] == 1
    response = json.loads(build_response(request, committed.with_identity("Li Wei", "Quiet Walker")))
    assert set(response["bounded_choices"]) == {"background_ability", "background_ability_amount"}
    assert response["bounded_choices"] == {
        "background_ability": "WIS",
        "background_ability_amount": 1,
    }
    assert build_background_ability_menu(request, envelope, committed) is None


def test_l4_origin_menu_filters_only_projection_unresolved_and_reads_resolved_skill() -> None:
    origin_contract = {
        "schema": "TianxiaFoundry.StartingProficiencyChoiceContract.v1",
        "fields": {
            "origin_skill_choices_by_origin_id": {
                "origin.resolved": {
                    "choice_kind": "origin_skill",
                    "choice_id": "origin.resolved",
                    "required_count": 1,
                    "allowed_values": ["History"],
                }
            }
        },
        "unresolved": [
            {
                "field": "origin_skill_choices_by_origin_id",
                "choice_id": "origin.unresolved",
                "proficiency_mechanics_present": True,
            }
        ],
    }
    envelope = {
        "envelope_sha256": "b" * 64,
        "choices_by_slot": {
            "origin_insight_choice": [
                {"choice_id": "origin.unresolved", "name": "Unresolved Origin"},
                {"choice_id": "origin.resolved", "name": "Resolved Origin"},
            ]
        },
        "allowed_choice_ids_by_slot": {
            "origin_insight_choice": ["origin.unresolved", "origin.resolved"]
        },
        "selection_limits_by_slot": {
            "origin_insight_choice": {"final_min": 1, "final_max": 1, "allow_none": False}
        },
        "owner_locks": {
            "by_slot": {"origin_insight_choice": []},
            "zero_owner_path_locks_are_legal": True,
        },
        "linear_provider_payload": {
            "response_contract": {
                "starting_proficiency_choice_contract": origin_contract
            }
        },
    }
    request = {"request_sha256": "a" * 64, "concept": "A patient cultivator"}
    state = CommittedState.empty()
    origin = build_origin_insight_choice_menu(request, envelope, state)
    assert origin is not None
    assert {choice_id for option in origin.options for choice_id in option.choice_ids} == {"origin.resolved"}
    state = commit_option(origin, origin.options[0].option_id, state)
    skill = build_origin_skill_menu(request, envelope, state, origin_id="origin.resolved")
    assert skill is not None
    assert {choice_id for option in skill.options for choice_id in option.choice_ids} == {"History"}
    assert build_origin_skill_menu(request, envelope, state, origin_id="origin.unresolved") is None


def test_l4_assembly_has_exact_preferred_shape_and_ordinary_mirror() -> None:
    state = (
        CommittedState.empty()
        .with_slot("path_choice", ["path.wood"])
        .with_ordinary(1, "talent.wood.1")
        .with_ordinary(2, "talent.wood.2")
        .with_identity("Li Wei", "Quiet Walker")
    )
    response = json.loads(
        build_response(
            {"request_sha256": "a" * 64, "concept": "A patient cultivator"},
            state,
        )
    )
    assert set(response) == {
        "schema",
        "request_sha256",
        "selection_intent",
        "acquisition_intent",
        "bounded_choices",
        "owner_descriptive_fields",
    }
    assert set(response["acquisition_intent"]) == {
        "sphere_free_talent_pairs",
        "ordinary_talent_ids",
        "insight_occurrences",
    }
    assert response["acquisition_intent"]["ordinary_talent_ids"] == [
        "talent.wood.1",
        "talent.wood.2",
    ]
    assert response["selection_intent"]["by_slot"]["advancement_skeleton"] == response[
        "acquisition_intent"
    ]["ordinary_talent_ids"]


def test_l4_persistence_snapshot_replays_against_strict_route_chain(fresh_db) -> None:
    _insert_project(fresh_db)
    request = _request(_envelope())
    _seed_run(fresh_db, request, "cg1.run.snapshot")
    persistence = LinearWalkPersistence(fresh_db)
    projection = persistence.projection("cg1.run.snapshot")
    assert projection is not None
    state = CommittedState.empty()
    started = persistence.append_event(
        "cg1.run.snapshot",
        event_type=WALK_STARTED,
        subject_sha256=request["request_sha256"],
        state_sha256_before=projection["state_sha256"],
        state_sha256_after=state.committed_sha256,
        payload={"steps_estimate": 22, "ceilings": {"max_steps": MAX_WALK_STEPS}},
    )
    persistence.save_snapshot(
        "cg1.run.snapshot", 0, state, started["event_sha256"]
    )
    replay = persistence.verified_replay(
        request,
        request["delegated_choice_envelope"],
        "cg1.run.snapshot",
    )
    assert replay["state"].to_dict() == state.to_dict()
    assert replay["projection"]["event_head_sha256"] == started["event_sha256"]
    assert persistence.load_snapshot("cg1.run.snapshot")["committed_sha256"] == state.committed_sha256


def test_l4_start_walk_single_option_autocommit_replays(fresh_db) -> None:
    """A single-option first menu autocommits at start and still replays.

    The start-walk snapshot must persist the STEP_AUTOCOMMITTED event for the
    already-committed first step; otherwise the verified replay sees an empty
    event chain and fails closed with DCC_LINEAR_SNAPSHOT_MISMATCH.
    """

    _insert_project(fresh_db)
    envelope = {
        "choices_by_slot": {"path_choice": [{"choice_id": "syn.path.a", "name": "Syn Path"}]},
        "allowed_choice_ids_by_slot": {"path_choice": ["syn.path.a"]},
        "selection_limits_by_slot": {
            "path_choice": {"final_min": 1, "final_max": 1, "allow_none": False},
        },
        "owner_locks": {
            # Identity opens the walk; locking it keeps this test on the
            # single-option first menu it exercises.
            "by_slot": {"identity": {"name": "Test Name", "title": "Test Title"}},
            "zero_owner_path_locks_are_legal": True,
        },
    }
    request = _request(envelope)
    run_id = "cg1.run.start-autocommit"
    _seed_run(fresh_db, request, run_id)
    provider = _FakeFirstProvider()
    service = _service_for(fresh_db, provider)
    replay = service._dcc_start_walk(run_id, request, envelope)
    assert provider.calls == []
    assert len(replay["step_events"]) == 1
    snapshot = LinearWalkPersistence(fresh_db).load_snapshot(run_id)
    assert snapshot is not None
    assert snapshot["step_ordinal"] == len(replay["step_events"]) == 1
    assert replay["state"].committed_sha256 == snapshot["committed_sha256"]
    assert replay["projection"]["event_head_sha256"] == snapshot["event_head_sha256"]
    resumed = service._dcc_start_walk(run_id, request, envelope)
    assert resumed["state"].to_dict() == replay["state"].to_dict()
    assert provider.calls == []


class _FakeFirstProvider:
    def __init__(self, *, unknown: int = 0):
        self.calls: list[dict] = []
        self.unknown = unknown

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["response_schema"]
        if "name" in schema.get("properties", {}):
            value = {"name": "Li Wei", "title": "Quiet Walker", "concept": "A patient alchemist who keeps the sect's furnaces honest."}
        elif self.unknown:
            self.unknown -= 1
            value = {"option_id": "dcc.opt.unknown"}
        else:
            value = {"option_id": schema["properties"]["option_id"]["enum"][0]}
        return {
            "value": value,
            "response_text": canonical_json(value),
            "provider_id": "fake",
            "purpose": kwargs["purpose"],
            "response_sha256": "d" * 64,
            "completion_sha256": "e" * 64,
            "timings": {"provider_reported": {"prompt_n": 7, "predicted_n": 1, "duration_ms": 1}},
        }


class _Projects:
    def __init__(self, db):
        self.db = db

    def get_project(self, project_id: str) -> dict:
        return {"project": {"project_id": project_id, "revision": 0, "content_lock": {"lock_hash": "a" * 64}}}


def test_sol77b_service_walk_selects_original_window_excluded_insight_on_page_four(fresh_db, monkeypatch):
    """Exercise both menu and service continuation ceilings through persisted events."""
    from paged_selection_contract import PAGED_WINDOW_SEMANTICS, PAGED_SELECTION_SLOTS_KEY, paged_slot_contract
    from stage1.insight_window import insight_windows, starting_at
    _insert_project(fresh_db)
    records = [{"record_id": f"syn.insight.{i:03}", "name": f"Insight {i:03}"} for i in range(80)]
    windows = insight_windows(records, project={"project_id": "s4-project", "user_locks": []},
                              effective_by_id={}, preferred={}, linked=set(), required=[], limit=50, choice=lambda row: row)
    original_window = {row["record_id"] for row in windows.windows[0]}
    choices = [{"choice_id": row["record_id"], "name": row["name"]} for row in starting_at(windows.windows, 0)]
    envelope = _envelope()
    envelope["choices_by_slot"]["insight_priorities"] = choices
    envelope.setdefault("allowed_choice_ids_by_slot", {})["insight_priorities"] = [row["choice_id"] for row in choices]
    envelope["selection_limits_by_slot"]["insight_priorities"] = {"final_min": 1, "final_max": 1, "allow_none": False}
    envelope[PAGED_SELECTION_SLOTS_KEY] = {"insight_priorities": paged_slot_contract({"selection_semantics": PAGED_WINDOW_SEMANTICS, "choices": choices})}
    request = _request(envelope)
    # Locate an option on page four that the original 30-row window excluded.
    menu = build_insight_priorities_menu(request, envelope, CommittedState.empty(), page=4)
    target = next(choice_id for option in menu.options if not option.is_continuation for choice_id in option.choice_ids if choice_id not in original_window)
    assert target not in original_window
    _seed_run(fresh_db, request, "cg1.run.sol77b")
    provider = _FakeFirstProvider()
    service = _service_for(fresh_db, provider)
    from character_creation.service import next_linear_step as actual_step
    seen_pages = []
    selected = []
    def observe_step(*args, **kwargs):
        step = actual_step(*args, **kwargs)
        if step.menu is not None and step.menu.step_kind == "insight_priorities":
            seen_pages.append(kwargs.get("page", 1))
            selected[:] = [step.menu]
        else:
            selected.clear()
        return step
    monkeypatch.setattr("character_creation.service.next_linear_step", observe_step)
    real_complete = provider.complete_json
    def choose(**kwargs):
        if selected:
            menu = selected[0]
            option = next((option for option in menu.options if target in option.choice_ids), None)
            if option is None:
                option = next(option for option in menu.options if option.is_continuation)
            receipt = real_complete(**kwargs)
            receipt["value"] = {"option_id": option.option_id}
            receipt["response_text"] = canonical_json(receipt["value"])
            return receipt
        return real_complete(**kwargs)
    monkeypatch.setattr(provider, "complete_json", choose)
    applied = []
    def fake_apply(run_id, response_text, transport, **kwargs):
        applied.append(json.loads(response_text))
        with fresh_db.transaction() as conn:
            conn.execute("UPDATE character_creation_runs SET transport_json=?,status='READY_FOR_REVIEW' WHERE run_id=?",
                         (canonical_json(transport), run_id))
        return service.get(run_id)
    monkeypatch.setattr(service, "_apply_response", fake_apply)
    result = service._run_dcc_linear_walk("cg1.run.sol77b")
    assert result["status"] == "READY_FOR_REVIEW", result.get("diagnostics")
    assert seen_pages == [1, 2, 3, 4]
    assert applied[0]["selection_intent"]["by_slot"]["insight_priorities"] == [target]
    snapshot = LinearWalkPersistence(fresh_db).load_snapshot("cg1.run.sol77b")
    assert snapshot["committed"].by_slot["insight_priorities"] == [target]


def _service_for(db, provider):
    return CharacterCreationExecutionService(
        db,
        stage1=None,
        provider=provider,
        project_store=_Projects(db),
        owner_principal="s4-test-owner",
    )


def test_l4_fake_first_walk_is_provider_free_and_reaches_ready_for_review(fresh_db, monkeypatch) -> None:
    _insert_project(fresh_db)
    request = _request(_envelope())
    _seed_run(fresh_db, request)
    provider = _FakeFirstProvider()
    service = _service_for(fresh_db, provider)
    applied: list[dict] = []

    def fake_apply(run_id, response_text, transport, **kwargs):
        applied.append({"response_text": response_text, **kwargs})
        with fresh_db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET transport_json=?,status='READY_FOR_REVIEW',updated_at=? WHERE run_id=?",
                (canonical_json(transport), "2026-09-04T00:01:00Z", run_id),
            )
        return service.get(run_id)

    monkeypatch.setattr(service, "_apply_response", fake_apply)
    result = service._run_dcc_linear_walk("cg1.run.s4")
    assert result["status"] == "READY_FOR_REVIEW"
    assert applied and applied[0]["action_type"] == "DCC_LINEAR_WALK"
    assert provider.calls
    assert all(call["purpose"] == "dcc_linear_step" for call in provider.calls)
    identity_calls = [call for call in provider.calls if "name" in call["response_schema"]["properties"]]
    selection_calls = [call for call in provider.calls if "option_id" in call["response_schema"]["properties"]]
    assert len(identity_calls) == 1 and len(identity_calls) + len(selection_calls) == len(provider.calls)
    assert identity_calls[0]["substantive"] is True and identity_calls[0]["response_schema_max_output_tokens"] == 256
    assert all(call["substantive"] is False and call["response_schema_max_output_tokens"] == 64 for call in selection_calls)
    assert all(call["timeout_seconds"] == 180 for call in provider.calls)
    events = ControllerRoutePersistence(fresh_db).projection("cg1.run.s4")["events"]
    assert events[-1]["event_type"] == WALK_COMPLETED
    walk_receipt = result["transport"]["linear_walk"]
    assert walk_receipt["provider_called"] is True
    assert walk_receipt["steps"]
    assert walk_receipt["menu_sha256_chain_digest"] == sha256_json(
        walk_receipt["menu_sha256_chain"]
    )


def test_l4_unknown_id_twice_fails_closed_then_continue_resumes(fresh_db, monkeypatch) -> None:
    _insert_project(fresh_db)
    request = _request(_envelope())
    _seed_run(fresh_db, request, "cg1.run.retry")
    provider = _FakeFirstProvider(unknown=2)
    service = _service_for(fresh_db, provider)

    def fake_apply(run_id, response_text, transport, **kwargs):
        with fresh_db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET transport_json=?,status='READY_FOR_REVIEW',updated_at=? WHERE run_id=?",
                (canonical_json(transport), "2026-09-04T00:02:00Z", run_id),
            )
        return service.get(run_id)

    monkeypatch.setattr(service, "_apply_response", fake_apply)
    failed = service._run_dcc_linear_walk("cg1.run.retry")
    assert failed["status"] == "NEEDS_REVIEW"
    events = ControllerRoutePersistence(fresh_db).projection("cg1.run.retry")["events"]
    assert events[-1]["event_type"] == WALK_FAILED
    snapshot = LinearWalkPersistence(fresh_db).load_snapshot("cg1.run.retry")
    assert snapshot is not None and snapshot["committed"].by_slot == {}
    resumed = service.continue_controller_walk("cg1.run.retry")
    assert resumed["status"] == "READY_FOR_REVIEW"
    assert provider.calls[2:]


def test_l4_same_frozen_request_has_deterministic_menus_and_plan_bytes(fresh_db, monkeypatch) -> None:
    _insert_project(fresh_db)
    request = _request(_envelope())
    _seed_run(fresh_db, request, "cg1.run.deterministic-a")
    _seed_run(fresh_db, request, "cg1.run.deterministic-b")
    responses: dict[str, str] = {}
    transports: dict[str, dict] = {}

    for run_id in ("cg1.run.deterministic-a", "cg1.run.deterministic-b"):
        provider = _FakeFirstProvider()
        service = _service_for(fresh_db, provider)

        def fake_apply(run_id, response_text, transport, _run_id=run_id, **kwargs):
            responses[_run_id] = response_text
            transports[_run_id] = transport
            with fresh_db.transaction() as conn:
                conn.execute(
                    "UPDATE character_creation_runs SET transport_json=?,status='READY_FOR_REVIEW',updated_at=? WHERE run_id=?",
                    (canonical_json(transport), "2026-09-04T00:03:00Z", run_id),
                )
            return service.get(run_id)

        monkeypatch.setattr(service, "_apply_response", fake_apply)
        assert service._run_dcc_linear_walk(run_id)["status"] == "READY_FOR_REVIEW"

    assert responses["cg1.run.deterministic-a"] == responses["cg1.run.deterministic-b"]
    assert transports["cg1.run.deterministic-a"]["linear_walk"]["menu_sha256_chain"] == transports[
        "cg1.run.deterministic-b"
    ]["linear_walk"]["menu_sha256_chain"]


def test_l4_restart_after_durable_menu_published_replays_and_verifies_chain(fresh_db, monkeypatch) -> None:
    _insert_project(fresh_db)
    request = _request(_envelope())
    _seed_run(fresh_db, request, "cg1.run.restart")
    interrupted_provider = _FakeFirstProvider()
    interrupted = _service_for(fresh_db, interrupted_provider)

    def stop_after_snapshot(*, prompt_text, response_schema):
        raise KeyboardInterrupt("simulated process stop")

    monkeypatch.setattr(interrupted, "_dcc_provider_step", stop_after_snapshot)
    try:
        interrupted._run_dcc_linear_walk("cg1.run.restart")
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("the simulated restart must interrupt the in-flight walk")

    persistence = LinearWalkPersistence(fresh_db)
    snapshot = persistence.load_snapshot("cg1.run.restart")
    projection = persistence.projection("cg1.run.restart")
    assert snapshot is not None and projection is not None
    assert any(event["event_type"] == "MENU_PUBLISHED" for event in projection["events"])
    verify_controller_event_chain(
        projection["events"],
        route_binding_sha256=projection["binding_sha256"],
    )

    resumed_provider = _FakeFirstProvider()
    resumed = _service_for(fresh_db, resumed_provider)

    def fake_apply(run_id, response_text, transport, **kwargs):
        with fresh_db.transaction() as conn:
            conn.execute(
                "UPDATE character_creation_runs SET transport_json=?,status='READY_FOR_REVIEW',updated_at=? WHERE run_id=?",
                (canonical_json(transport), "2026-09-04T00:04:00Z", run_id),
            )
        return resumed.get(run_id)

    monkeypatch.setattr(resumed, "_apply_response", fake_apply)
    result = resumed.continue_controller_walk("cg1.run.restart")
    assert result["status"] == "READY_FOR_REVIEW"
    final_projection = persistence.projection("cg1.run.restart")
    assert final_projection is not None
    assert final_projection["events"][-1]["event_type"] == WALK_COMPLETED
    verify_controller_event_chain(
        final_projection["events"],
        route_binding_sha256=final_projection["binding_sha256"],
    )


def _copy_opt_in_li_wei_root() -> tuple[tempfile.TemporaryDirectory[str], Path, dict]:
    """Copy one explicitly opted-in golden root using a required COW copy."""

    from tests.test_golden_li_wei import (
        GOLDEN_SCHEMA,
        _data_root,
        _opt_in_paths,
        _relative_input,
        _safe_absolute,
    )

    selected = _opt_in_paths()
    if selected is None:
        pytest.skip(
            "set TIANXIA_GOLDEN_LI_WEI_DATA_ROOT and "
            "TIANXIA_GOLDEN_LI_WEI_MANIFEST for the Li Wei integration"
        )
    data_root_text, manifest_text = selected
    source_root = _data_root(data_root_text)
    manifest_path = _safe_absolute(Path(manifest_text), label="golden manifest")
    if not manifest_path.is_file():
        pytest.fail(f"golden manifest does not exist: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        pytest.fail(f"golden manifest is not valid UTF-8 JSON: {exc}")
    if not isinstance(manifest, dict) or manifest.get("schema") != GOLDEN_SCHEMA:
        pytest.fail("golden manifest schema is missing or unsupported")
    run = manifest.get("run")
    inputs = manifest.get("inputs")
    if not isinstance(run, dict) or not isinstance(inputs, dict):
        pytest.fail("golden manifest is incomplete: run/inputs")
    project_id = run.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        pytest.fail("golden manifest run.project_id is missing")
    source_db_value = (manifest.get("source_database") or {}).get("relative_path", "foundry.sqlite3")
    source_db = _relative_input(source_root, source_db_value, label="golden source database", expect="file")

    try:
        temporary = tempfile.TemporaryDirectory(prefix=".dcc-linear-li-wei-", dir=str(source_root.parent))
    except OSError as exc:
        pytest.skip(f"Li Wei COW copy parent is unavailable: {exc}")
    target_root = Path(temporary.name) / "data"
    target_root.mkdir()
    try:
        copied = subprocess.run(
            ["cp", "--reflink=always", "-a", f"{source_root}/.", str(target_root)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        temporary.cleanup()
        pytest.skip(f"Li Wei COW copy unavailable: {exc}")
    if copied.returncode != 0:
        temporary.cleanup()
        pytest.skip(f"Li Wei COW copy unavailable: {copied.stderr.strip()}")
    target_db = _relative_input(target_root, source_db.relative_to(source_root), label="copied source database", expect="file")
    if target_db.stat().st_ino == source_db.stat().st_ino:
        temporary.cleanup()
        pytest.skip("Li Wei COW copy did not produce a distinct database inode")

    config_path = target_root / "vendor" / "factory_adapter.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            temporary.cleanup()
            pytest.fail(f"copied Factory adapter configuration is invalid: {exc}")

        source_prefix = str(source_root)
        target_prefix = str(target_root)

        def rebase(value):
            if isinstance(value, str) and (value == source_prefix or value.startswith(source_prefix + os.sep)):
                return target_prefix + value[len(source_prefix):]
            if isinstance(value, dict):
                return {key: rebase(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rebase(item) for item in value]
            return value

        config_path.write_text(canonical_json(rebase(config)), encoding="utf-8")
    return temporary, target_root, {"manifest": manifest, "source_db": source_db, "project_id": project_id}


class _GoldenFirstProvider:
    """A static fake that returns the first opaque option from every menu."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def selected_ai_identity(self) -> dict[str, str]:
        return {
            "selected_ai_identity_sha256": "a" * 64,
            "selected_ai_identity_state": "AVAILABLE_STATIC",
        }

    def complete_json(self, **kwargs):
        self.calls.append({key: value for key, value in kwargs.items() if key != "prompt_text"})
        schema = kwargs["response_schema"]
        properties = schema.get("properties") or {}
        if "name" in properties:
            value = {"name": "Li Wei", "title": "Quiet Walker", "concept": "A patient alchemist who keeps the sect's furnaces honest."}
        else:
            enum = (properties.get("option_id") or {}).get("enum") or []
            assert enum
            value = {"option_id": enum[0]}
        return {
            "value": value,
            "response_text": canonical_json(value),
            "provider_id": "fake-golden-first",
            "purpose": kwargs["purpose"],
            "response_sha256": "d" * 64,
            "completion_sha256": "e" * 64,
            "timings": {"provider_reported": {"prompt_n": 7, "predicted_n": 1, "duration_ms": 1}},
        }


def _bounded_diagnostic_summary(result: dict) -> dict:
    """Keep opt-in failure output structural without exposing choice data."""

    validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
    candidates = [
        validation.get("last_submission_error"),
        validation.get("submission_error"),
        result.get("submission_error"),
    ]
    blockers = result.get("blockers")
    if isinstance(blockers, list):
        candidates.extend(blockers)

    def summarize_values(value):
        if isinstance(value, dict):
            return {"kind": "object", "count": len(value)}
        if isinstance(value, (list, tuple, set, frozenset)):
            return {"kind": "list", "count": len(value)}
        return {"kind": type(value).__name__}

    for diagnostic in candidates:
        if not isinstance(diagnostic, dict):
            continue
        details = diagnostic.get("details") if isinstance(diagnostic.get("details"), dict) else {}
        issues = details.get("issues")
        issue = next((row for row in issues if isinstance(row, dict)), None) if isinstance(issues, list) else None
        summary = {
            "code": diagnostic.get("code"),
            "message": diagnostic.get("message"),
        }
        seen_counts: set[str] = set()
        nested_codes: set[str] = set()
        slots: set[str] = set()

        def visit(value) -> None:
            if isinstance(value, dict):
                nested_code = value.get("code")
                if isinstance(nested_code, str) and nested_code != summary["code"]:
                    nested_codes.add(nested_code)
                slot = value.get("slot")
                if isinstance(slot, str):
                    slots.add(slot)
                for key in ("field", "milestone_id", "effective_cl", "cl"):
                    item = value.get(key)
                    if isinstance(item, (str, int)) and not isinstance(item, bool):
                        summary.setdefault(key, item)
                for key in (
                    "allowed_values",
                    "allowed_resolutions",
                    "allowed_kinds",
                    "allowed_channels",
                    "candidates",
                    "required_abilities",
                    "allowed_deltas",
                    "expected_count",
                    "actual_count",
                    "required_count",
                ):
                    if key in value and key in {"expected_count", "actual_count", "required_count"}:
                        item = value[key]
                        if type(item) is int:
                            summary[f"{key}_summary"] = {"kind": "integer", "count": item}
                            seen_counts.add(key)
                    elif key in value and key not in seen_counts:
                        summary[f"{key}_summary"] = summarize_values(value[key])
                        seen_counts.add(key)
                for item in value.values():
                    if isinstance(item, (dict, list, tuple)):
                        visit(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, (dict, list, tuple)):
                        visit(item)

        visit(details)
        visit(issue or {})
        if nested_codes:
            summary["nested_codes"] = sorted(nested_codes)
        if slots:
            summary["slots"] = sorted(slots)
        return summary
    return {"code": None}


def _bounded_exception_summary(exc: Exception) -> dict:
    """Summarize caught validator details without exposing choice data."""

    diagnostic = {
        "code": getattr(exc, "code", None),
        "message": getattr(exc, "message", None),
        "details": getattr(exc, "details", None),
    }
    return _bounded_diagnostic_summary({"validation": {"last_submission_error": diagnostic}})


_BACKGROUND_SELECTION_SLOTS = (
    "background_choice",
    "background_sphere_choice",
    "background_talent_choice",
    "origin_insight_choice",
)


def _bounded_selection_slot_counts(result: dict) -> dict[str, int]:
    """Report only selected-value counts for the four required slots."""

    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    parsed = response.get("parsed_plan")
    if not isinstance(parsed, dict):
        text = response.get("exact_response_text")
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = {}
    selection = parsed.get("selection_intent") if isinstance(parsed, dict) else None
    by_slot = selection.get("by_slot") if isinstance(selection, dict) else None
    return {
        slot: (
            len(by_slot.get(slot))
            if isinstance(by_slot, dict) and isinstance(by_slot.get(slot), (list, tuple))
            else (1 if isinstance(by_slot, dict) and isinstance(by_slot.get(slot), str) else 0)
        )
        for slot in _BACKGROUND_SELECTION_SLOTS
    }


def _bounded_background_source_summary(result: dict) -> dict:
    """Summarize typed source counts and empty owner-lock semantics only."""

    request = result.get("request") if isinstance(result.get("request"), dict) else {}
    envelope = request.get("delegated_choice_envelope")
    envelope = envelope if isinstance(envelope, dict) else {}
    choices = envelope.get("choices_by_slot")
    choices = choices if isinstance(choices, dict) else {}
    typed = envelope.get("typed_choice_authority_by_slot")
    background_authority = typed.get("background_choice") if isinstance(typed, dict) else None
    linkage = background_authority.get("background_package_linkage") if isinstance(background_authority, dict) else None
    locks = envelope.get("owner_locks")
    locks = locks.get("by_slot") if isinstance(locks, dict) and isinstance(locks.get("by_slot"), dict) else locks
    return {
        "choices_by_slot_counts": {
            slot: len(choices.get(slot)) if isinstance(choices.get(slot), (list, tuple, dict)) else 0
            for slot in _BACKGROUND_SELECTION_SLOTS
        },
        "typed_linkage_background_count": len(linkage) if isinstance(linkage, dict) else 0,
        "zero_owner_lock": {
            slot: isinstance(locks, dict) and not bool(locks.get(slot))
            for slot in _BACKGROUND_SELECTION_SLOTS
        },
    }


def _bounded_locked_id_missing_counts(result: dict, db, project_id: str) -> dict[str, int]:
    """Compare assembled IDs with the copied project's lock snapshot safely.

    This diagnostic intentionally returns counts only.  It is used by the
    opt-in integration assertion to distinguish a response-to-lock mismatch
    without exposing any frozen IDs, cues, or owner content in test output.
    """

    response = result.get("response") if isinstance(result.get("response"), dict) else {}
    parsed = response.get("parsed_plan")
    if not isinstance(parsed, dict):
        text = response.get("exact_response_text")
        if isinstance(text, str):
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    selection = parsed.get("selection_intent")
    selection = selection if isinstance(selection, dict) else {}
    by_slot = selection.get("by_slot")
    if not isinstance(by_slot, dict):
        # Keep the helper useful if the service exposes its canonicalized
        # selection projection instead of the preferred response wrapper.
        by_slot = selection.get("selected_by_slot")
    by_slot = by_slot if isinstance(by_slot, dict) else {}
    acquisition = parsed.get("acquisition_intent")
    acquisition = acquisition if isinstance(acquisition, dict) else {}

    def string_values(value) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple)):
            return [item for item in value if isinstance(item, str)]
        return []

    pairs = acquisition.get("sphere_free_talent_pairs")
    pairs = pairs if isinstance(pairs, list) else []
    categories = {
        "pair sphere": [
            row.get("sphere_id")
            for row in pairs
            if isinstance(row, dict) and isinstance(row.get("sphere_id"), str)
        ],
        "pair talent": [
            row.get("talent_id")
            for row in pairs
            if isinstance(row, dict) and isinstance(row.get("talent_id"), str)
        ],
        "ordinary talent": string_values(acquisition.get("ordinary_talent_ids")),
        "insight occurrence": [
            row.get("insight_id")
            for row in (acquisition.get("insight_occurrences") or [])
            if isinstance(row, dict) and isinstance(row.get("insight_id"), str)
        ],
    }
    with db.connection() as conn:
        locked_ids = {
            row[0]
            for row in conn.execute(
                "SELECT record_id FROM project_locked_records WHERE project_id=?",
                (project_id,),
            ).fetchall()
            if isinstance(row[0], str)
        }
    missing_counts = {
        category: sum(value not in locked_ids for value in values)
        for category, values in categories.items()
    }
    missing_counts["high-level slots"] = {
        slot_id: sum(
            value not in locked_ids
            for value in string_values(by_slot.get(slot_id))
        )
        for slot_id in (
            "path_choice",
            "subpath_choice",
            "method_choice",
            "foundation_choice",
            "background_choice",
            "background_sphere_choice",
            "background_talent_choice",
            "origin_insight_choice",
        )
    }
    return missing_counts


def _bounded_walk_step_counts(db, run_id: str) -> dict[str, dict[str, int]]:
    """Count persisted walk events by step without exposing response values."""

    projection = ControllerRoutePersistence(db).projection(run_id)
    events = projection.get("events") if isinstance(projection, dict) else None
    counts: dict[str, dict[str, int]] = {}
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type")
        if event_type not in {"MENU_PUBLISHED", "STEP_COMMITTED", "STEP_AUTOCOMMITTED", "STEP_RETRIED"}:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        step_id = payload.get("step_id")
        if not isinstance(step_id, str) or not step_id:
            continue
        by_type = counts.setdefault(step_id, {})
        by_type[event_type] = by_type.get(event_type, 0) + 1
    return counts


def test_l4_scratch_compile_carries_an_external_security_directory(tmp_path: Path) -> None:
    # The scratch compile pins security_dir to <scratch>/security.  When the
    # live security directory is external (TIANXIA_FOUNDRY_SECURITY_DIR), the
    # scratch must receive a copy of it or keyed evidence cannot be verified.
    from types import SimpleNamespace

    data = tmp_path / "data"
    (data / "security").mkdir(parents=True)
    external = tmp_path / "external-security"
    external.mkdir()
    (external / "marker.json").write_text("{}", encoding="utf-8")
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    fake = SimpleNamespace(db=SimpleNamespace(settings=SimpleNamespace(data_dir=data, security_dir=external)))
    CharacterCreationExecutionService._snapshot_external_security(fake, scratch)
    assert (scratch / "security" / "marker.json").is_file()

    # An in-data security directory is already covered by the data snapshot
    # and is not copied twice.
    inside = SimpleNamespace(db=SimpleNamespace(settings=SimpleNamespace(data_dir=data, security_dir=data / "security")))
    untouched = tmp_path / "scratch-inside"
    untouched.mkdir()
    CharacterCreationExecutionService._snapshot_external_security(inside, untouched)
    assert not (untouched / "security").exists()


def _two_milestone_insight_envelope(repeatability: dict | None) -> dict:
    parameters = {"ability": {"allowed_values": ["CHA", "WIS"]}}
    if repeatability is not None:
        parameters["repeatability"] = repeatability
    resolution = {
        "cultivation_insight_acquisition": {
            "destination": "acquisition_intent.insight_occurrences[]",
            "allowed_insight_ids": ["insight.tools", "insight.other"],
            "parameters_by_insight_id": {
                "insight.tools": parameters,
                "insight.other": {"ability": {"allowed_values": ["CHA"]}},
            },
        },
    }
    return {
        "envelope_sha256": "b" * 64,
        "response_contract": {
            "required_milestone_resolutions": {
                "milestone.cl8": {"milestone_id": "milestone.cl8", "path_id": "path.qi", "resolution_options": resolution},
                "milestone.cl12": {"milestone_id": "milestone.cl12", "path_id": "path.qi", "resolution_options": resolution},
            },
        },
        "choices_by_slot": {
            "insight_priorities": [
                {"choice_id": "insight.tools", "name": "Tools"},
                {"choice_id": "insight.other", "name": "Other"},
            ],
        },
    }


def test_l4_insight_occurrence_menu_never_repeats_a_nonrepeatable_insight() -> None:
    # Stage 2 rejects a second causal occurrence of a nonrepeatable Insight
    # (its default when the record carries no repeatability), even though
    # the delegated validator accepts it.  A CL8 occurrence therefore closes
    # that Insight for CL12 unless typed repeatability allows the repeat.
    from character_creation.creative_controller.linear_menus import build_insight_occurrence_menu

    request = {"request_sha256": "a" * 64}
    state = CommittedState.empty().with_slot("path_choice", ["path.qi"])

    envelope = _two_milestone_insight_envelope(None)
    first = build_insight_occurrence_menu(request, envelope, state, milestone_id="milestone.cl8")
    assert first is not None
    assert {option.choice_ids for option in first.options} == {("insight.tools",), ("insight.other",)}
    taken = state.with_insight_occurrence({"insight_id": "insight.tools", "milestone_id": "milestone.cl8", "parameters": {"ability": "CHA"}})
    second = build_insight_occurrence_menu(request, envelope, taken, milestone_id="milestone.cl12")
    assert second is not None
    assert {option.choice_ids for option in second.options} == {("insight.other",)}
    # The ability follow-up for the committed milestone is unaffected.
    follow_up = build_insight_occurrence_menu(request, envelope, taken, milestone_id="milestone.cl8", step_id="insight_occurrence:milestone.cl8:ability")
    assert follow_up is None or all(option.choice_ids[0] in {"CHA", "WIS"} for option in follow_up.options)

    repeatable = _two_milestone_insight_envelope({"mode": "repeatable", "maximum": 2})
    again = build_insight_occurrence_menu(request, repeatable, taken, milestone_id="milestone.cl12")
    assert again is not None
    assert {option.choice_ids for option in again.options} == {("insight.tools",), ("insight.other",)}

    capped = _two_milestone_insight_envelope({"mode": "repeatable", "maximum": 1})
    limited = build_insight_occurrence_menu(request, capped, taken, milestone_id="milestone.cl12")
    assert limited is not None
    assert {option.choice_ids for option in limited.options} == {("insight.other",)}


def test_l4_insight_occurrences_follow_milestone_cl_order_not_commit_order() -> None:
    # Stage 2 derives Insight rows by effective CL and the compiler compares
    # the semantic occurrence list with it positionally.  Milestone IDs sort
    # "cl12" before "cl8" as strings, so both the walk order and the
    # assembled response must use the sealed milestone CL instead.
    milestones = [
        {"milestone_id": "milestone.x.cl12", "cl": 12, "path_id": "path.qi"},
        {"milestone_id": "milestone.x.cl8", "cl": 8, "path_id": "path.qi"},
    ]
    request = {
        "request_sha256": "a" * 64,
        "delegated_choice_envelope": {"advancement_choice_milestones": milestones},
    }
    envelope = _two_milestone_insight_envelope(None)
    envelope["response_contract"]["required_milestone_resolutions"] = {
        "milestone.x.cl12": {"milestone_id": "milestone.x.cl12", "path_id": "path.qi", "resolution_options": envelope["response_contract"]["required_milestone_resolutions"]["milestone.cl12"]["resolution_options"]},
        "milestone.x.cl8": {"milestone_id": "milestone.x.cl8", "path_id": "path.qi", "resolution_options": envelope["response_contract"]["required_milestone_resolutions"]["milestone.cl8"]["resolution_options"]},
    }
    envelope["advancement_choice_milestones"] = milestones
    state = CommittedState.empty().with_slot("path_choice", ["path.qi"])
    occurrence_steps = [
        step_id
        for step_id, kind, _slot in _step_descriptors(request, envelope, state)
        if kind == "insight_occurrence"
    ]
    assert occurrence_steps[:2] == ["insight_occurrence:milestone.x.cl8", "insight_occurrence:milestone.x.cl12"]

    committed = (
        state.with_insight_occurrence({"insight_id": "insight.tools", "milestone_id": "milestone.x.cl12", "parameters": {"ability": "CHA"}})
        .with_insight_occurrence({"insight_id": "insight.other", "milestone_id": "milestone.x.cl8", "parameters": {"ability": "CHA"}})
        .with_identity("Li Wei", "Quiet Walker")
    )
    response = json.loads(build_response(request, committed))
    assert [row["milestone_id"] for row in response["acquisition_intent"]["insight_occurrences"]] == [
        "milestone.x.cl8",
        "milestone.x.cl12",
    ]


def test_l4_background_and_origin_cannot_be_skipped_when_the_proficiency_contract_needs_them() -> None:
    # The sealed selection limits call Background and Origin Insight optional,
    # but the starting-proficiency validator requires exactly one Background
    # and one Origin when its contract carries entries for them.  The real
    # Granite walk took the offered stop at Background and was rejected with
    # BACKGROUND_SELECTION_CARDINALITY after 44 steps.
    from character_creation.creative_controller.linear_menus import (
        build_background_choice_menu,
        build_origin_insight_choice_menu,
    )

    request = {
        "request_sha256": "a" * 64,
        "bounded_choice_contract": {
            "starting_proficiency_choice_contract": {
                "fields": {
                    "background_language_choices_by_background_id": {
                        "bg.orphan": {"choice_id": "bg.orphan", "allowed_values": ["Classical"], "language_choice_count": 1},
                    },
                    "origin_skill_choices_by_origin_id": {
                        "origin.suspicion": {"choice_id": "origin.suspicion", "allowed_values": ["Deception", "Insight"], "required_count": 1},
                    },
                },
            },
        },
    }
    envelope = {
        "selection_limits_by_slot": {
            "background_choice": {"allow_none": True, "final_max": 1, "final_min": 0},
            "origin_insight_choice": {"allow_none": True, "final_max": 1, "final_min": 0},
            "foundation_choice": {"allow_none": True, "final_max": 1, "final_min": 0},
        },
        "choices_by_slot": {
            "background_choice": [{"choice_id": "bg.orphan", "name": "Abandoned Orphan"}],
            "origin_insight_choice": [{"choice_id": "origin.suspicion", "name": "Born Under Suspicion"}],
            "foundation_choice": [{"choice_id": "foundation.bowl", "name": "Empty Bowl"}],
        },
        "owner_locks": {"by_slot": {}, "zero_owner_path_locks_are_legal": True},
    }
    state = CommittedState.empty().with_slot("path_choice", ["path.qi"])

    background = build_background_choice_menu(request, envelope, state)
    assert background is not None
    assert [option.choice_ids for option in background.options] == [("bg.orphan",)]
    assert all(option.kind != "none" for option in background.options)

    with_background = state.with_slot("background_choice", ["bg.orphan"])
    origin = build_origin_insight_choice_menu(request, envelope, with_background)
    assert origin is not None
    assert [option.choice_ids for option in origin.options] == [("origin.suspicion",)]

    # Background Sphere and Background Talent are mandatory for the same
    # validator, even when the sealed limits call them optional.
    from character_creation.creative_controller.linear_menus import (
        build_background_sphere_choice_menu,
        build_background_talent_choice_menu,
    )
    envelope["selection_limits_by_slot"]["background_sphere_choice"] = {"allow_none": True, "final_max": 1, "final_min": 0}
    envelope["selection_limits_by_slot"]["background_talent_choice"] = {"allow_none": True, "final_max": 1, "final_min": 0}
    envelope["choices_by_slot"]["background_sphere_choice"] = [{"choice_id": "bgs.scoundrel", "name": "Scoundrel"}]
    envelope["choices_by_slot"]["background_talent_choice"] = [{"choice_id": "bgt.tools", "name": "Hidden Tool Cache"}]
    envelope["background_package_linkage"] = {
        "bg.orphan": {
            "spheres": [{"id": "bgs.scoundrel", "name": "Scoundrel"}],
            "bgs.scoundrel": {"talents": [{"id": "bgt.tools", "name": "Hidden Tool Cache"}]},
        }
    }
    sphere = build_background_sphere_choice_menu(request, envelope, with_background)
    assert sphere is not None and all(option.kind != "none" for option in sphere.options)
    talent = build_background_talent_choice_menu(request, envelope, with_background.with_slot("background_sphere_choice", ["bgs.scoundrel"]))
    assert talent is not None and all(option.kind != "none" for option in talent.options)

    # A slot the validator does not demand keeps its sealed optional stop.
    from character_creation.creative_controller.linear_menus import build_foundation_choice_menu
    foundation = build_foundation_choice_menu(request, envelope, with_background.with_slot("method_choice", ["METHOD-001"]))
    assert foundation is not None
    assert any(option.kind == "none" for option in foundation.options)


def test_l4_empty_owner_lock_rows_never_lock_a_slot_even_with_owner_locked_paths() -> None:
    # Production envelopes publish an empty by_slot row for every unresolved
    # slot and set zero_owner_path_locks_are_legal to False as soon as the
    # owner locks a Path.  The validator ignores empty rows; the walk must
    # too, or every unresolved slot is skipped and the plan is rejected.
    from character_creation.creative_controller.linear_menus import build_background_choice_menu, is_owner_locked

    request = {"request_sha256": "a" * 64}
    envelope = {
        "choices_by_slot": {
            "path_choice": [{"choice_id": "path.body", "name": "Body"}, {"choice_id": "path.qi", "name": "Qi"}],
            "background_choice": [{"choice_id": "bg.orphan", "name": "Abandoned Orphan"}],
        },
        "owner_locks": {
            "by_slot": {"path_choice": ["path.body"], "background_choice": [], "sphere_priorities": [], "method_choice": []},
            "zero_owner_path_locks_are_legal": False,
        },
    }
    assert is_owner_locked(request, envelope, "path_choice") is True
    for slot in ("background_choice", "sphere_priorities", "method_choice", "origin_insight_choice"):
        assert is_owner_locked(request, envelope, slot) is False, slot
    state = CommittedState.empty().with_slot("path_choice", ["path.body"])
    menu = build_background_choice_menu(request, envelope, state)
    assert menu is not None and [option.choice_ids for option in menu.options][0] == ("bg.orphan",)
    descriptors = [step_id for step_id, _kind, _slot in _step_descriptors(request, envelope, state)]
    assert "background_choice" in descriptors
    assert not any(step.startswith("path_choice") for step in descriptors) or "path_choice:2" in descriptors


def test_l4_every_selected_path_must_advance_before_the_target_cl() -> None:
    # NS1R_INITIAL_CREATION_PROGRESS_MAP_INVALID: every selected Path must
    # advance at least once across CL 1..target.  The first real two-Path
    # Granite walk advanced one Path at all ten CLs.  When the CLs left equal
    # the Paths still at zero, only those Paths may be offered.
    request = {"request_sha256": "a" * 64}
    envelope = {
        "frozen_owner_target_cl": {"value": 12},
        "path_progression_choices": [
            {"cl": cl, "path_ids": ["path.body", "path.spirit", "path.qi"]} for cl in range(1, 21)
        ],
        "owner_locks": {"by_slot": {}, "zero_owner_path_locks_are_legal": True},
    }
    state = CommittedState.empty().with_slot("path_choice", ["path.body", "path.spirit"])
    steps = [step_id for step_id, kind, _slot in _step_descriptors(request, envelope, state) if kind == "path_progression"]
    assert steps == [f"path_progression:{cl}" for cl in range(1, 13)]

    for cl in range(1, 12):
        menu = build_path_progression_menu(request, envelope, state, cl=cl)
        assert menu is not None
        assert {option.choice_ids for option in menu.options} == {("path.body",), ("path.spirit",)}, cl
        state = commit_option(menu, next(o for o in menu.options if o.choice_ids == ("path.body",)).option_id, state)
    last = build_path_progression_menu(request, envelope, state, cl=12)
    assert last is not None
    assert [option.choice_ids for option in last.options] == [("path.spirit",)]

    # Once every selected Path has advanced, the remaining CLs are free again.
    relaxed = CommittedState.empty().with_slot("path_choice", ["path.body", "path.spirit"])
    first = build_path_progression_menu(request, envelope, relaxed, cl=1)
    relaxed = commit_option(first, next(o for o in first.options if o.choice_ids == ("path.spirit",)).option_id, relaxed)
    second = build_path_progression_menu(request, envelope, relaxed, cl=2)
    assert {option.choice_ids for option in second.options} == {("path.body",), ("path.spirit",)}


def test_l4_level_talents_come_only_from_known_spheres() -> None:
    # Rulebook: a level talent is chosen from a Sphere you already know.  At
    # creation the known Spheres are the CL1 free Sphere from the committed
    # pair and the Background Sphere, which the validator resolves to its
    # canonical Sphere by display name.  The typed candidate path used to
    # offer every talent in the skeleton regardless of Sphere.
    from character_creation.creative_controller.linear_menus import _known_sphere_ids

    rows = {
        "talent.alchemy.one": "sphere.alchemy",
        "talent.alchemy.two": "sphere.alchemy",
        "talent.scoundrel.trick": "sphere.scoundrel",
        "talent.ash.burn": "sphere.ash",
    }
    envelope = {
        "ordinary_talent_count": 3,
        "choices_by_slot": {
            "advancement_skeleton": {tid: {"choice_id": tid, "name": tid} for tid in rows},
            "sphere_priorities": [
                {"choice_id": "sphere.alchemy", "name": "Alchemy"},
                {"choice_id": "sphere.scoundrel", "name": "Scoundrel"},
                {"choice_id": "sphere.ash", "name": "Ash"},
            ],
            "background_sphere_choice": {"bgs.scoundrel": {"choice_id": "bgs.scoundrel", "name": "Scoundrel"}},
        },
        "allowed_choice_ids_by_slot": {"advancement_skeleton": list(rows)},
        "typed_choice_authority_by_slot": {
            "advancement_skeleton": {
                "stage2_authority_by_choice": {
                    tid: {"authority_complete": True, "allowed_channels": ["level-choice"], "allowed_kinds": ["level_talent_acquisition"], "minimum_cl": 1, "sphere_id": sid}
                    for tid, sid in rows.items()
                },
            },
        },
    }
    request = {"request_sha256": "a" * 64}
    paired = CommittedState.empty().with_pair("sphere.alchemy", "talent.alchemy.free")
    assert _known_sphere_ids(request, envelope, paired) == {"sphere.alchemy"}
    menu = build_ordinary_talent_menu(request, envelope, paired, cl=1)
    assert menu is not None
    assert {o.choice_ids[0] for o in menu.options} == {"talent.alchemy.one", "talent.alchemy.two"}

    # The Background Sphere becomes known only through its sealed package:
    # the selected Background's package linkage names the Background Sphere
    # choice and its canonical Sphere, and the Background Sphere row carries
    # the same canonical relation.  Display names never resolve identity.
    envelope["choices_by_slot"]["background_sphere_choice"]["bgs.scoundrel"]["canonical_sphere_id"] = "sphere.scoundrel"
    envelope["choices_by_slot"]["background_choice"] = {"bg.orphan": {"choice_id": "bg.orphan", "name": "Abandoned Orphan"}}
    envelope["typed_choice_authority_by_slot"]["background_choice"] = {
        "background_package_linkage": {
            "bg.orphan": [
                {
                    "background_sphere_choice_id": "bgs.scoundrel",
                    "canonical_sphere_id": "sphere.scoundrel",
                    "background_talent_choice_id": "bgt.scoundrel.trick",
                    "talent_record_id": "talent.scoundrel.trick",
                }
            ]
        }
    }
    unlinked = paired.with_slot("background_sphere_choice", ["bgs.scoundrel"])
    assert _known_sphere_ids(request, envelope, unlinked) == {"sphere.alchemy"}
    with_background = unlinked.with_slot("background_choice", ["bg.orphan"])
    assert _known_sphere_ids(request, envelope, with_background) == {"sphere.alchemy", "sphere.scoundrel"}
    menu = build_ordinary_talent_menu(request, envelope, with_background, cl=1)
    assert {o.choice_ids[0] for o in menu.options} == {"talent.alchemy.one", "talent.alchemy.two", "talent.scoundrel.trick"}
    assert not any(o.choice_ids[0] == "talent.ash.burn" for o in menu.options)


def test_l4_insight_occurrences_respect_typed_prerequisites_against_acquisitions() -> None:
    # An Insight occurrence is an acquisition: the validator checks its typed
    # prerequisites against the final Paths, Spheres and Talents (not against
    # planning priorities).  A milestone menu must not offer an Insight whose
    # Path prerequisite the committed build cannot meet.
    from character_creation.creative_controller.linear_menus import build_insight_occurrence_menu

    request = {"request_sha256": "a" * 64}
    envelope = _two_milestone_insight_envelope(None)
    envelope["choices_by_slot"]["insight_priorities"] = [
        {"choice_id": "insight.tools", "name": "Tools", "prerequisites": [{"kind": "path", "operator": "requires", "target_id": "path.body"}]},
        {"choice_id": "insight.other", "name": "Other", "prerequisites": [{"kind": "sphere", "operator": "requires", "target_id": "sphere.alchemy"}]},
    ]
    qi_only = CommittedState.empty().with_slot("path_choice", ["path.qi"]).with_pair("sphere.alchemy", "talent.alchemy.free")
    menu = build_insight_occurrence_menu(request, envelope, qi_only, milestone_id="milestone.cl8")
    assert menu is not None
    assert {option.choice_ids for option in menu.options} == {("insight.other",)}

    # A planning priority for the Path does not satisfy an acquisition prerequisite.
    planned_only = qi_only.with_slot("insight_priorities", ["insight.tools"])
    menu = build_insight_occurrence_menu(request, envelope, planned_only, milestone_id="milestone.cl8")
    assert {option.choice_ids for option in menu.options} == {("insight.other",)}

    body_too = qi_only.with_slot("path_choice", ["path.qi", "path.body"])
    menu = build_insight_occurrence_menu(request, envelope, body_too, milestone_id="milestone.cl8")
    assert {option.choice_ids for option in menu.options} == {("insight.tools",), ("insight.other",)}


def test_l4_foundation_menu_mirrors_method_foundation_compatibility() -> None:
    # CG1_METHOD_FOUNDATION_INCOMPATIBLE: a Foundation's typed
    # compatible_method_ids and a Method's compatible_foundation_ids (row or
    # sealed map) both constrain the pair; empty lists constrain nothing.
    from character_creation.creative_controller.linear_menus import build_foundation_choice_menu

    request = {"request_sha256": "a" * 64}
    envelope = {
        "choices_by_slot": {
            "method_choice": {"METHOD-1": {"choice_id": "METHOD-1", "name": "Root"}},
            "foundation_choice": {
                "f.open": {"choice_id": "f.open", "name": "Open"},
                "f.picky": {"choice_id": "f.picky", "name": "Picky", "compatible_method_ids": ["METHOD-9"]},
                "f.listed": {"choice_id": "f.listed", "name": "Listed"},
            },
        },
        "method_foundation_compatibility": {"METHOD-1": {"compatible_foundation_ids": []}},
        "owner_locks": {"by_slot": {}, "zero_owner_path_locks_are_legal": True},
    }
    state = CommittedState.empty().with_slot("path_choice", ["path.qi"]).with_slot("method_choice", ["METHOD-1"])
    menu = build_foundation_choice_menu(request, envelope, state)
    offered = {o.choice_ids[0] for o in menu.options if o.choice_ids}
    assert offered == {"f.open", "f.listed"}

    envelope["method_foundation_compatibility"]["METHOD-1"]["compatible_foundation_ids"] = ["f.listed"]
    menu = build_foundation_choice_menu(request, envelope, state)
    assert {o.choice_ids[0] for o in menu.options if o.choice_ids} == {"f.listed"}


def test_l4_foundation_menu_withholds_foundations_that_cannot_express_the_paths() -> None:
    # NS1R_INITIAL_FOUNDATION_AUTHORITY_INVALID: a Foundation that publishes
    # compatible_path_ids must cover every Path the character ends with.  A
    # Body-Refining-only character was offered Empty Bowl Soul Anchor
    # (QI_CULTIVATION, SPIRIT_AWAKENING), the walk committed it, and the
    # validator could only reject the run.  The menu must not extend it.
    from character_creation.creative_controller.linear_menus import build_foundation_choice_menu

    request = {"request_sha256": "a" * 64}
    envelope = {
        "choices_by_slot": {
            "method_choice": {"METHOD-1": {"choice_id": "METHOD-1", "name": "Root"}},
            "foundation_choice": {
                "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR": {
                    "choice_id": "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR",
                    "name": "Empty Bowl Soul Anchor",
                    "compatible_path_ids": ["QI_CULTIVATION", "SPIRIT_AWAKENING"],
                },
                "beast_echo_marrow_v0_2A": {
                    "choice_id": "beast_echo_marrow_v0_2A",
                    "name": "Beast Echo Marrow",
                    "compatible_path_ids": ["BODY_REFINING", "SPIRIT_AWAKENING"],
                },
                "unconstrained": {"choice_id": "unconstrained", "name": "Unconstrained"},
            },
        },
        "method_foundation_compatibility": {"METHOD-1": {"compatible_foundation_ids": []}},
        "owner_locks": {"by_slot": {}, "zero_owner_path_locks_are_legal": True},
    }

    body_only = CommittedState.empty().with_slot(
        "path_choice", ["tianxia.path.body_refining"]
    ).with_slot("method_choice", ["METHOD-1"])
    menu = build_foundation_choice_menu(request, envelope, body_only)
    offered = {o.choice_ids[0] for o in menu.options if o.choice_ids}
    assert "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR" not in offered
    assert offered == {"beast_echo_marrow_v0_2A", "unconstrained"}

    qi_only = CommittedState.empty().with_slot(
        "path_choice", ["tianxia.path.qi_cultivation"]
    ).with_slot("method_choice", ["METHOD-1"])
    menu = build_foundation_choice_menu(request, envelope, qi_only)
    offered = {o.choice_ids[0] for o in menu.options if o.choice_ids}
    assert offered == {"FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR", "unconstrained"}

    # Two Paths: a Foundation must cover both.
    both = CommittedState.empty().with_slot(
        "path_choice", ["tianxia.path.body_refining", "tianxia.path.qi_cultivation"]
    ).with_slot("method_choice", ["METHOD-1"])
    menu = build_foundation_choice_menu(request, envelope, both)
    offered = {o.choice_ids[0] for o in menu.options if o.choice_ids}
    assert offered == {"unconstrained"}


def test_l4_no_foundation_is_offered_below_cl_5() -> None:


    # Rulebook: no Foundation by default before the Foundation Realm (CL 5).
    # Below that the Foundation step may only defer; at CL 5 and above the
    # sealed Foundations are offered.
    from character_creation.creative_controller.linear_menus import build_foundation_choice_menu

    request = {"request_sha256": "a" * 64}
    envelope = {
        "frozen_owner_target_cl": {"value": 3},
        "selection_limits_by_slot": {"foundation_choice": {"allow_none": True, "final_max": 1, "final_min": 0}},
        "choices_by_slot": {
            "method_choice": {"METHOD-1": {"choice_id": "METHOD-1", "name": "Root"}},
            "foundation_choice": {"f.open": {"choice_id": "f.open", "name": "Open"}},
        },
        "owner_locks": {"by_slot": {}, "zero_owner_path_locks_are_legal": True},
    }
    state = CommittedState.empty().with_slot("path_choice", ["path.qi"]).with_slot("method_choice", ["METHOD-1"])
    low = build_foundation_choice_menu(request, envelope, state)
    assert low is not None
    assert [option.kind for option in low.options] == ["none"]

    envelope["frozen_owner_target_cl"] = {"value": 5}
    high = build_foundation_choice_menu(request, envelope, state)
    assert {option.choice_ids[0] for option in high.options if option.choice_ids} == {"f.open"}


def test_l4_ordinary_talents_respect_typed_prerequisites() -> None:
    # Talent requirements are typed prerequisites on the skeleton rows and the
    # validator checks them against the acquisitions (not planning picks).
    rows = {"talent.a.first": "sphere.a", "talent.a.chain": "sphere.a"}
    envelope = {
        "ordinary_talent_count": 2,
        "choices_by_slot": {
            "advancement_skeleton": {
                "talent.a.first": {"choice_id": "talent.a.first", "name": "First"},
                "talent.a.chain": {"choice_id": "talent.a.chain", "name": "Chain", "prerequisites": [{"kind": "talent", "operator": "requires", "target_id": "talent.a.first"}]},
            },
            "sphere_priorities": [{"choice_id": "sphere.a", "name": "A"}],
        },
        "allowed_choice_ids_by_slot": {"advancement_skeleton": list(rows)},
        "typed_choice_authority_by_slot": {
            "advancement_skeleton": {
                "stage2_authority_by_choice": {
                    tid: {"authority_complete": True, "allowed_channels": ["level-choice"], "allowed_kinds": ["level_talent_acquisition"], "minimum_cl": 1, "sphere_id": sid}
                    for tid, sid in rows.items()
                },
            },
        },
    }
    request = {"request_sha256": "a" * 64}
    state = CommittedState.empty().with_pair("sphere.a", "talent.a.free")
    first = build_ordinary_talent_menu(request, envelope, state, cl=1)
    assert {o.choice_ids[0] for o in first.options} == {"talent.a.first"}
    state = commit_option(first, first.options[0].option_id, state)
    second = build_ordinary_talent_menu(request, envelope, state, cl=2)
    assert {o.choice_ids[0] for o in second.options} == {"talent.a.chain"}


def test_l4_identity_step_proposes_a_concept_and_foundation_is_required_from_cl_5() -> None:
    from character_creation.creative_controller.linear_assembly import build_response
    from character_creation.creative_controller.linear_menus import build_foundation_choice_menu
    from character_creation.creative_controller.linear_prompt import parse_identity_response

    identity = parse_identity_response({"name": "Lianhua Mo", "title": "Bone Whisperer", "concept": "  A quiet corpse-tender who   listens to old bones.  "})
    assert identity["concept"] == "A quiet corpse-tender who listens to old bones."
    state = CommittedState.empty().with_identity(identity["name"], identity["title"], identity["concept"])
    response = json.loads(build_response({"request_sha256": "a" * 64}, state))
    assert response["owner_descriptive_fields"]["identity"] == {"name": "Lianhua Mo", "title": "Bone Whisperer"}
    assert response["owner_descriptive_fields"]["concept"] == "A quiet corpse-tender who listens to old bones."
    owned = json.loads(build_response({"request_sha256": "a" * 64, "concept": "Owner wrote this."}, state))
    assert owned["owner_descriptive_fields"]["concept"] == "Owner wrote this."

    request = {"request_sha256": "a" * 64}
    envelope = {
        "frozen_owner_target_cl": {"value": 10},
        "selection_limits_by_slot": {"foundation_choice": {"allow_none": True, "final_max": 1, "final_min": 0}},
        "choices_by_slot": {
            "method_choice": {"METHOD-1": {"choice_id": "METHOD-1", "name": "Root"}},
            "foundation_choice": {"f.open": {"choice_id": "f.open", "name": "Open"}, "f.other": {"choice_id": "f.other", "name": "Other"}},
        },
        "owner_locks": {"by_slot": {}, "zero_owner_path_locks_are_legal": True},
    }
    walk_state = CommittedState.empty().with_slot("path_choice", ["path.qi"])
    menu = build_foundation_choice_menu(request, envelope, walk_state)
    assert menu is not None
    assert all(option.kind != "none" for option in menu.options)
    assert {option.choice_ids[0] for option in menu.options} == {"f.open", "f.other"}


def _priority_envelope() -> tuple[dict, dict]:
    talents = {
        "TAL_DEATH_BONE_WARD": ("sphere.death", 1),
        "TAL_DEATH_DEATH_MASK": ("sphere.death", 1),
        "TAL_DEATH_CORPSE_SERVANT": ("sphere.death", 5),
        "TAL_DEATH_CORPSE_SERVANT_STAT_BLOCK": ("sphere.death", 5),
        "TAL_DAEMON_CLAW": ("sphere.daemonic", 1),
        "TAL_ALCHEMY_ANTIDOTE": ("sphere.alchemy", 1),
    }
    rows = {tid: {"choice_id": tid, "name": tid.replace("TAL_", "").replace("_", " ").title(), "acquisition_channels": ["level-choice"]} for tid in talents}
    rows["TAL_DEATH_CORPSE_SERVANT_STAT_BLOCK"]["name"] = "Corpse Servant Stat Block"
    request = {
        "request_sha256": "a" * 64,
        "stage1_prompt": {"envelope": {"user_locks": [
            {"field": "character_sheet.generation_route", "value": "ai_bootstrap"},
            {"field": "character_sheet.planning_preferences", "value": {
                "sphere_priority_ids": ["sphere.daemonic", "sphere.death", "sphere.alchemy"],
                "talent_priority_ids": ["TAL_DEATH_CORPSE_SERVANT", "TAL_DEATH_DEATH_MASK", "TAL_DEATH_UNPUBLISHED"],
            }},
        ]}},
    }
    envelope = {
        "frozen_owner_target_cl": {"value": 10},
        "ordinary_talent_count": 10,
        "response_contract": {
            "expected_acquisition_counts": {"sphere_free_talent_pairs": 1, "ordinary_talent_ids": 10},
            "presented_legal_first_cycle_pairs": [{"sphere_id": "sphere.alchemy", "talent_id": "TAL_ALCHEMY_ANTIDOTE", "sphere_name": "Alchemy", "talent_name": "Antidote"}],
        },
        "choices_by_slot": {
            "sphere_priorities": {sid: {"choice_id": sid, "name": sid.split(".")[-1].title(), "acquisition_channels": ["sphere-acquisition"]} for sid in ("sphere.death", "sphere.daemonic", "sphere.alchemy")},
            "advancement_skeleton": rows,
        },
        "allowed_choice_ids_by_slot": {"sphere_priorities": ["sphere.death", "sphere.daemonic", "sphere.alchemy"], "advancement_skeleton": list(rows)},
        "typed_choice_authority_by_slot": {"advancement_skeleton": {"stage2_authority_by_choice": {
            tid: {"authority_complete": True, "allowed_channels": ["ai-bootstrap-free-cl1-talent", "level-choice"], "allowed_kinds": ["ai_bootstrap_talent_acquisition", "level_talent_acquisition"], "minimum_cl": cl, "sphere_id": sid}
            for tid, (sid, cl) in talents.items()
        }}},
        "owner_locks": {"by_slot": {}, "zero_owner_path_locks_are_legal": True},
    }
    return request, envelope


def test_l4_owner_priorities_drive_the_free_pair_level_talents_and_sphere_list() -> None:
    # Owner decision 10: wizard priorities are binding.  The server presented
    # only an Alchemy sample pair; the walk builds the full legal set, takes
    # the priority Sphere owning the most priority Talents (Death, not the
    # first-listed Daemonic), prefers priority Talents inside it, forces a
    # legal priority Talent at every level-talent step, leads the Sphere
    # priorities list with the owner's Spheres, and never offers a stat block.
    from character_creation.creative_controller.linear_menus import (
        _legal_free_pairs,
        build_sphere_free_talent_pair_menu,
        build_sphere_priorities_menu,
    )

    request, envelope = _priority_envelope()
    legal = _legal_free_pairs(request, envelope)
    assert {(p["sphere_id"], p["talent_id"]) for p in legal} == {
        ("sphere.death", "TAL_DEATH_BONE_WARD"), ("sphere.death", "TAL_DEATH_DEATH_MASK"),
        ("sphere.daemonic", "TAL_DAEMON_CLAW"), ("sphere.alchemy", "TAL_ALCHEMY_ANTIDOTE"),
    }
    state = CommittedState.empty().with_slot("path_choice", ["path.qi"])
    pair_menu = build_sphere_free_talent_pair_menu(request, envelope, state, pair_index=1)
    assert [o.choice_ids for o in pair_menu.options] == [("sphere.death", "TAL_DEATH_DEATH_MASK")]
    state = commit_option(pair_menu, pair_menu.options[0].option_id, state)

    descriptors = [step_id for step_id, _k, _s in _step_descriptors(request, envelope, state)]
    assert "ordinary_talent:1" in descriptors and "sphere_route" not in descriptors

    cl1 = build_ordinary_talent_menu(request, envelope, state, cl=1)
    assert {o.choice_ids[0] for o in cl1.options} == {"TAL_DEATH_BONE_WARD"}
    state = commit_option(cl1, cl1.options[0].option_id, state)
    cl5 = build_ordinary_talent_menu(request, envelope, state, cl=5)
    assert [o.choice_ids[0] for o in cl5.options] == ["TAL_DEATH_CORPSE_SERVANT"]
    state = commit_option(cl5, cl5.options[0].option_id, state)
    cl6 = build_ordinary_talent_menu(request, envelope, state, cl=6)
    assert cl6 is None or all(o.choice_ids[0] != "TAL_DEATH_CORPSE_SERVANT_STAT_BLOCK" for o in cl6.options)

    for cl in range(2, 11):
        if str(cl) in state.ordinary_by_cl:
            continue
        menu = build_ordinary_talent_menu(request, envelope, state, cl=cl)
        if menu is None:
            break
        state = commit_option(menu, menu.options[0].option_id, state)
    priorities = build_sphere_priorities_menu(request, envelope, state)
    assert priorities is not None
    assert priorities.options[0].choice_ids[:3] == ("sphere.daemonic", "sphere.death", "sphere.alchemy")


def _fresh_project_from_owner_locks(projects, golden_project_id: str) -> str:
    """Create a new project carrying only the golden project's owner inputs.

    Every project in the golden root is already CLEAN_AND_FINALIZED, and a
    finalized project holds server-derived descriptive and grant-plan locks
    whose values embed the finalizing run.  Any later run on that project,
    legacy or DCC, therefore fails at scratch compile with
    ``CG1_DELEGATED_FINAL_GRANT_PLAN_IMMUTABLE`` before its plan can be
    reviewed.  The acceptance walk needs the same Stage 1 owner authority on
    a project that has not been finalized, so rebuild one through the
    public project store from the revision-zero owner locks and the same
    sealed pack locks.
    """

    golden = projects.get_project(golden_project_id)["project"]
    pack_locks = [
        {"pack_id": pack["pack_id"], "version": pack["version"], "content_hash": pack.get("content_hash")}
        for pack in golden["content_lock"]["packs"]
    ]
    owner_locks = [
        lock
        for lock in golden.get("user_locks") or []
        if isinstance(lock, dict)
        and lock.get("created_revision") == 0
        and not str(lock.get("lock_id") or "").startswith("lock.cg1.")
    ]
    assert owner_locks, "golden project carries no revision-zero owner locks"
    created = projects.create_project(
        working_name=f"{golden['name']} (linear acceptance)",
        pack_locks=pack_locks,
        user_locks=owner_locks,
    )
    return created["project"]["project_id"]


def test_l4_opt_in_li_wei_public_dcc_start_uses_real_apply_and_validates_plan() -> None:
    temporary, target_root, evidence = _copy_opt_in_li_wei_root()
    try:
        from app.core import Database, Settings
        from character_creation.delegated_choice_authority import validate_delegated_choice_plan
        from character_creation.production_release import CharacterProductionReleaseAdapter
        from character_sheet import CharacterSheetService
        from factory_authoring import FactoryAuthoringWorkspaceService, FinalCharacterWorkflowService
        from gm_export import GMCharacterExportService
        from portable_character import PortableCharacterPackageService
        from project_store.service import ProjectStore
        from projector.service import ProjectionService
        from security.integrity import IntegrityService
        from security.local_identity import BoundPrincipalProvider, ProcessPrincipalProvider
        from stage1.service import Stage1ClipboardService
        from stage2 import Stage2AdvancementService

        settings = Settings.from_env(Path(__file__).resolve().parents[1], target_root)
        db = Database(settings)
        db.migrate()
        principal = ProcessPrincipalProvider().current_principal()
        bound = BoundPrincipalProvider(principal)
        integrity = IntegrityService.for_database(db)
        workflow = FinalCharacterWorkflowService(db, principal_provider=bound, integrity=integrity)
        provider = _GoldenFirstProvider()
        projects = ProjectStore(db, principal_provider=bound, integrity=integrity)
        service = CharacterCreationExecutionService(
            db,
            stage1=Stage1ClipboardService(db),
            provider=provider,
            project_store=projects,
            stage2=Stage2AdvancementService(db, principal_provider=bound),
            character_sheets=CharacterSheetService(db),
            gm_exports=GMCharacterExportService(db),
            portable_characters=PortableCharacterPackageService(db),
            factory_authoring=FactoryAuthoringWorkspaceService(
                db,
                principal_provider=bound,
                integrity=integrity,
                final_character_workflow=workflow,
            ),
            projections=ProjectionService(db),
            production_release=CharacterProductionReleaseAdapter(db),
            owner_principal=principal.principal_id,
        )
        caught_diagnostics: list[dict] = []
        caught_compile_diagnostics: list[dict] = []
        applied_results: list[dict] = []
        original_diagnostic = service._dcc_diagnostic
        original_apply = service._apply_response
        original_compile = service._validate_and_compile

        def capture_diagnostic(exc, **kwargs):
            caught_diagnostics.append(_bounded_exception_summary(exc))
            return original_diagnostic(exc, **kwargs)

        def capture_apply(*args, **kwargs):
            try:
                applied = original_apply(*args, **kwargs)
            except Exception as exc:
                applied_results.append({"exception": _bounded_exception_summary(exc)})
                raise
            applied_results.append({"result": _bounded_diagnostic_summary(applied)})
            return applied

        def capture_compile(*args, **kwargs):
            try:
                return original_compile(*args, **kwargs)
            except Exception as exc:
                caught_compile_diagnostics.append(_bounded_exception_summary(exc))
                raise

        service._dcc_diagnostic = capture_diagnostic
        service._apply_response = capture_apply
        service._validate_and_compile = capture_compile
        project_id = _fresh_project_from_owner_locks(projects, evidence["project_id"])
        result = service.start(
            project_id,
            execution_mode="STANDARD_API",
            idempotency_key=f"dcc-li-wei-l4-2-{target_root.parent.name}",
            controller_route=DETERMINISTIC_CREATIVE_CONTROLLER,
        )
        failure_diagnostic = {
            "status": result.get("status"),
            "diagnostic": {
                "retained": _bounded_diagnostic_summary(result),
                "caught": caught_diagnostics[-1:] or [],
                "caught_compile": caught_compile_diagnostics[-1:] or [],
                "apply": applied_results[-1:] or [],
                "selection_slot_counts": _bounded_selection_slot_counts(result),
                "typed_background_source": _bounded_background_source_summary(result),
                "locked_id_missing_counts": _bounded_locked_id_missing_counts(result, db, project_id),
                "walk_step_counts": _bounded_walk_step_counts(db, result.get("run_id", "")),
            },
        }
        assert result["status"] in {"READY_FOR_REVIEW", "CLEAN_AND_FINALIZED"}, canonical_json(failure_diagnostic)
        assert provider.calls
        assert all(call["purpose"] == "dcc_linear_step" for call in provider.calls)
        assert all(call["substantive"] is False for call in provider.calls)

        response_text = result["response"]["exact_response_text"]
        plan, raw = service._parse_plan(
            response_text,
            expected_project_id=result["project_id"],
            expected_project_revision=result["starting_revision"],
            expected_request_sha256=result["request"]["request_sha256"],
        )
        assert raw == response_text.encode("utf-8")
        provider_contract = json.loads(service._provider_prompt(result)).get("response_contract") or {}
        required_slots = sorted(
            slot_id
            for slot_id in provider_contract.get("required_selection_slots") or []
            if slot_id in {"sphere_priorities", "insight_priorities", "item_priorities"}
        )
        validated = validate_delegated_choice_plan(
            result,
            service._project(result["project_id"]),
            plan,
            response_sha256=sha256_bytes(raw),
            provider_required_planning_slot_ids=required_slots,
        )
        assert isinstance(validated, dict)
    finally:
        temporary.cleanup()


def _two_path_subpath_envelope(*, target_cl: int, lock_body_subpath: bool) -> tuple[dict, dict]:
    subpaths = {
        "sub.body.oni": {"choice_id": "sub.body.oni", "name": "Oni Blood", "owning_path_id": "path.body", "owning_path_choice_ids": ["path.body"]},
        "sub.body.bone": {"choice_id": "sub.body.bone", "name": "Bone Monarch", "owning_path_id": "path.body", "owning_path_choice_ids": ["path.body"]},
        "sub.spirit.warden": {"choice_id": "sub.spirit.warden", "name": "Soul Warden", "owning_path_id": "path.spirit", "owning_path_choice_ids": ["path.spirit"]},
        "sub.spirit.lantern": {"choice_id": "sub.spirit.lantern", "name": "Lantern Keeper", "owning_path_id": "path.spirit", "owning_path_choice_ids": ["path.spirit"]},
    }
    envelope = {
        "frozen_owner_target_cl": {"value": target_cl},
        "path_progression_choices": [{"cl": cl, "path_ids": ["path.body", "path.spirit"]} for cl in range(1, target_cl + 1)],
        "choices_by_slot": {"subpath_choice": subpaths},
        "allowed_choice_ids_by_slot": {"subpath_choice": list(subpaths)},
        "selection_limits_by_slot": {"subpath_choice": {"final_min": 0, "final_max": 3, "allow_none": True}},
        "owner_locks": {
            # The Method is owner-locked so this fixture isolates Subpath behaviour.
            "by_slot": {"path_choice": ["path.body", "path.spirit"], "method_choice": ["method.locked"], "subpath_choice": ["sub.body.oni"] if lock_body_subpath else []},
            "zero_owner_path_locks_are_legal": False,
        },
    }
    return {"request_sha256": "a" * 64}, envelope


def test_l4_owner_subpath_lock_is_per_path_not_slot_wide() -> None:
    # The owner locked Oni Blood (Body Refining).  That decides Body's Subpath
    # only; Spirit Awakening still needs its own menu.  Treating the lock as
    # slot-wide silenced Spirit's Subpath and Stage 2 rejected the build at the
    # Spirit Awakening level-3 Subpath milestone.
    from character_creation.creative_controller.linear_walk import _apply_owner_locks, _step_descriptors, next_step
    from character_creation.creative_controller.linear_menus import build_subpath_choice_menu

    request, envelope = _two_path_subpath_envelope(target_cl=10, lock_body_subpath=True)
    state = _apply_owner_locks(request, envelope, CommittedState.empty().with_bounded("identity", {"name": "Test Name", "title": "Test Title"}))
    assert state.by_slot["subpath_choice"] == ["sub.body.oni"]
    assert build_subpath_choice_menu(request, envelope, state, path_id="path.body") is None
    spirit = build_subpath_choice_menu(request, envelope, state, path_id="path.spirit")
    assert spirit is not None
    assert {option.choice_ids for option in spirit.options if option.kind == "pick"} == {("sub.spirit.warden",), ("sub.spirit.lantern",)}
    assert [step_id for step_id, kind, _slot in _step_descriptors(request, envelope, state) if kind == "subpath_choice"] == ["subpath_choice:path.spirit"]
    step = next_step(request, envelope, state, [])
    assert step.step_id == "subpath_choice:path.spirit"
    assert step.action == "MENU"


def test_l4_path_reaching_subpath_level_requires_a_subpath_before_completion() -> None:
    from character_creation.creative_controller.linear_walk import _apply_owner_locks, _step_descriptors, next_step, LinearWalkError
    from character_creation.creative_controller.linear_menus import (
        build_step_menu,
        final_path_attainment,
        mandatory_completion_gaps,
        subpath_required_path_ids,
    )

    request, envelope = _two_path_subpath_envelope(target_cl=6, lock_body_subpath=True)
    state = _apply_owner_locks(request, envelope, CommittedState.empty().with_bounded("identity", {"name": "Test Name", "title": "Test Title"}))
    # Progression still open: no attainment is knowable, so no requirement yet.
    assert final_path_attainment(request, envelope, state) is None
    assert subpath_required_path_ids(request, envelope, state) == []
    for cl, path_id in ((1, "path.body"), (2, "path.spirit"), (3, "path.body"), (4, "path.spirit"), (5, "path.body"), (6, "path.spirit")):
        state = state.with_path_progression(str(cl), path_id)
    assert final_path_attainment(request, envelope, state) == {"path.body": 3, "path.spirit": 3}
    assert subpath_required_path_ids(request, envelope, state) == ["path.spirit"]
    # The early optional step was declined; the required step has its own ID
    # and no skip option.
    descriptors = [step_id for step_id, kind, _slot in _step_descriptors(request, envelope, state) if kind == "subpath_choice"]
    assert "subpath_choice:path.spirit:required" in descriptors
    required = build_step_menu(request, envelope, state, step_id="subpath_choice:path.spirit:required", ordinal=1)
    assert required is not None
    assert required.to_dict()["min_choices"] == 1
    assert all(option.kind == "pick" for option in required.options)
    gaps = mandatory_completion_gaps(request, envelope, state)
    assert gaps["subpath_required_for_path_ids"] == ["path.spirit"]
    assert gaps["next_step_id"] == "subpath_choice:path.spirit:required"
    done = [
        {"event_type": "STEP_COMMITTED", "step_id": "subpath_choice:path.spirit"},
        {"event_type": "STEP_AUTOCOMMITTED", "step_id": "insight_priorities:1"},
        {"event_type": "STEP_AUTOCOMMITTED", "step_id": "item_priorities:1"},
    ]
    step = next_step(request, envelope, state, done)
    assert step.step_id == "subpath_choice:path.spirit:required"
    # Committing the required pick satisfies the milestone; the Body Subpath
    # stays the owner's and no gap remains.
    state = commit_option(step.menu, step.options[0].option_id, state)
    # Re-applying the owner locks on the next replay must accept the added
    # Spirit Subpath beside the owner's Body Subpath, and still reject a
    # state where the owner's Subpath was replaced.
    assert _apply_owner_locks(request, envelope, state).by_slot["subpath_choice"] == state.by_slot["subpath_choice"]
    # Replay rebuilds state from committed events only: the owner's Body
    # Subpath is merged back in front of the walk's Spirit Subpath.
    replayed = state.with_slot("subpath_choice", [value for value in state.by_slot["subpath_choice"] if value != "sub.body.oni"])
    assert _apply_owner_locks(request, envelope, replayed).by_slot["subpath_choice"][0] == "sub.body.oni"
    replaced = state.with_slot("subpath_choice", [value for value in state.by_slot["subpath_choice"] if value != "sub.body.oni"] + ["sub.body.bone"])
    with pytest.raises(LinearWalkError) as excinfo:
        _apply_owner_locks(request, envelope, replaced)
    assert excinfo.value.code == "DCC_LINEAR_OWNER_LOCK_CONFLICT"
    assert "sub.body.oni" in state.by_slot["subpath_choice"]
    assert len(set(state.by_slot["subpath_choice"]) & {"sub.spirit.warden", "sub.spirit.lantern"}) == 1
    assert subpath_required_path_ids(request, envelope, state) == []
    assert mandatory_completion_gaps(request, envelope, state) is None


def test_l4_attained_character_must_pick_a_method_and_auto_means_the_model_chooses() -> None:
    from character_creation.creative_controller.linear_menus import build_method_choice_menu, mandatory_completion_gaps, method_required_gap
    from character_creation.creative_controller.linear_walk import LinearWalkError, next_step

    legal_method = "method.legal"
    request = {"request_sha256": "a" * 64, "method_planning_mode": "AUTO"}
    envelope = {
        "envelope_sha256": "b" * 64,
        "frozen_owner_target_cl": {"value": 10},
        "choices_by_slot": {"method_choice": {legal_method: {"choice_id": legal_method, "name": "Legal method"}}},
        "allowed_choice_ids_by_slot": {"method_choice": [legal_method]},
        "selection_limits_by_slot": {"method_choice": {"final_min": 0, "final_max": 1, "allow_none": True}},
        "owner_locks": {"by_slot": {"method_choice": [], "path_choice": ["path.wood"]}},
        "path_method_authority": {"compatible_method_ids": [legal_method], "method_granted_path_ids": {legal_method: ["path.wood"]}},
    }
    state = CommittedState.empty().with_bounded("identity", {"name": "Test Name", "title": "Test Title"}).with_slot("path_choice", ["path.wood"])
    # AUTO used to clear the candidates and offer only "continue with automatic
    # planning"; with attainment the model must choose a real Method.
    menu = build_method_choice_menu(request, envelope, state)
    assert menu is not None
    assert menu.to_dict()["min_choices"] == 1
    assert [option.choice_ids for option in menu.options if not option.is_continuation] == [(legal_method,)]
    assert all(option.kind != "none" for option in menu.options)
    gaps = mandatory_completion_gaps(request, envelope, state)
    assert gaps["method_required"] is True and gaps["next_step_id"] == "method_choice"
    assert method_required_gap(request, envelope, state) is None

    # No legal Method at all: the walk stops with the exact facts instead of
    # deferring into a build the validator would reject.
    empty = {**envelope, "allowed_choice_ids_by_slot": {"method_choice": []}, "choices_by_slot": {"method_choice": {}}}
    empty["path_method_authority"] = {
        "compatible_method_ids": ["METHOD-081"],
        "method_granted_path_ids": {},
        "method_access_by_id": {"METHOD-081": {"initial_creation_selectable": False, "owner_route_options": []}},
    }
    gap = method_required_gap(request, empty, state)
    assert gap["reasons_by_method_id"] == {"METHOD-081": ["no_published_learning_route"]}
    done = [{"event_type": "STEP_AUTOCOMMITTED", "step_id": "subpath_choice:path.wood"}]
    with pytest.raises(LinearWalkError) as excinfo:
        next_step(request, empty, state, done)
    assert excinfo.value.code == "DCC_LINEAR_REQUIRED_STEP_UNSATISFIABLE"
    assert excinfo.value.details["step_id"] == "method_choice"

    # No attainment (CL 0): the old optional behaviour is unchanged.
    zero = {**envelope, "frozen_owner_target_cl": {"value": 0}}
    optional = build_method_choice_menu(request, zero, state)
    assert optional is not None and any(option.kind == "none" for option in optional.options)


def test_l4_assembly_omits_bounded_fields_the_sealed_contract_never_advertised() -> None:
    # A projection summary can expose a point-buy field while the sealed
    # bounded-choice contract advertises only a subset of fields; the
    # assembled preferred response must carry only advertised bounded fields.
    from character_creation.creative_controller.linear_assembly import build_response

    state = (
        CommittedState.empty()
        .with_identity("Shen Qinglan", "Cinder-Wind Witness", "A cinder-wind witness.")
        .with_bounded("ability_scores", {"STR": 15, "DEX": 14})
        .with_bounded("foundation_initial_stage", {"choice_id": "f.open"})
    )
    sealed = {
        "request_sha256": "a" * 64,
        "bounded_choice_contract": {"fields": {"foundation_initial_stage": {"choice_id": "f.open"}}},
    }
    response = json.loads(build_response(sealed, state))
    assert set(response["bounded_choices"]) == {"foundation_initial_stage"}
    assert response["bounded_choices"]["foundation_initial_stage"] == {"choice_id": "f.open"}

    unsealed = {"request_sha256": "a" * 64}
    legacy = json.loads(build_response(unsealed, state))
    assert set(legacy["bounded_choices"]) == {"ability_scores", "foundation_initial_stage"}


def test_l4_locked_background_talent_restricts_sphere_menu_to_its_sealed_package() -> None:
    # A Background Talent owner lock names one exact sealed package: the walk
    # must not offer another package's sphere, which the response validator
    # would reject as CG1_DELEGATED_BACKGROUND_PACKAGE_MISMATCH.
    slots = {
        "background_choice": [{"choice_id": "background.scout", "name": "Border Scout"}],
        "background_sphere_choice": [
            {"choice_id": "sphere.athletics", "name": "Athletics"},
            {"choice_id": "sphere.sniper", "name": "Sniper"},
            {"choice_id": "sphere.trap", "name": "Trap"},
        ],
        "background_talent_choice": [{"choice_id": "talent.sniper", "name": "Still-Scope Posture"}],
    }
    envelope = {
        "envelope_sha256": "b" * 64,
        "choices_by_slot": slots,
        "allowed_choice_ids_by_slot": {slot: [row["choice_id"] for row in rows] for slot, rows in slots.items()},
        "selection_limits_by_slot": {slot: {"final_min": 1, "final_max": 1, "allow_none": False} for slot in slots},
        "owner_locks": {
            "by_slot": {
                "background_choice": ["background.scout"],
                "background_sphere_choice": [],
                "background_talent_choice": ["talent.sniper"],
            },
            "zero_owner_path_locks_are_legal": True,
        },
        "typed_choice_authority_by_slot": {
            "background_choice": {
                "background_package_linkage": {
                    "background.scout": [
                        {"background_sphere_choice_id": "sphere.athletics", "background_talent_choice_id": "talent.athletics", "package_index": 0},
                        {"background_sphere_choice_id": "sphere.trap", "background_talent_choice_id": "talent.trap", "package_index": 1},
                        {"background_sphere_choice_id": "sphere.sniper", "background_talent_choice_id": "talent.sniper", "package_index": 2},
                    ]
                }
            }
        },
        "bounded_choice_contract": {"starting_proficiency_choice_contract": {"fields": {"origin_skill_choices_by_origin_id": {}}}},
    }
    request = {"request_sha256": "a" * 64, "concept": "A patient cultivator"}
    state = CommittedState.empty().with_slot("background_choice", ["background.scout"])
    menu = build_background_sphere_choice_menu(request, envelope, state)
    assert menu is not None
    assert [option.choice_ids for option in menu.options] == [("sphere.sniper",)]

    unlocked = json.loads(json.dumps(envelope))
    unlocked["owner_locks"]["by_slot"]["background_talent_choice"] = []
    every = build_background_sphere_choice_menu(request, unlocked, state)
    assert every is not None
    assert [option.choice_ids for option in every.options] == [("sphere.athletics",), ("sphere.sniper",), ("sphere.trap",)]
