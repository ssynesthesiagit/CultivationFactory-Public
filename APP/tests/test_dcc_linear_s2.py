"""Provider-free L2 checks for the deterministic linear DCC walk."""

from __future__ import annotations

import pytest

from character_creation.creative_controller import (
    CommittedState,
    OPTION_BUNDLE,
    OPTION_NONE,
    build_insight_occurrence_menu,
    build_insight_priorities_menu,
    build_ordinary_talent_menu,
    build_response_schema,
    build_sphere_free_talent_pair_menu,
    build_sphere_priorities_menu,
    build_sphere_route_menu,
    build_step_menu,
    build_step_prompt,
    commit_option,
    replay_committed_state,
)


def _fixture() -> tuple[dict, dict]:
    request = {"request_sha256": "a" * 64, "concept": "A patient cultivator"}
    envelope = {
        "envelope_sha256": "b" * 64,
        "response_contract": {
            "expected_acquisition_counts": {
                "sphere_free_talent_pairs": 2,
                "ordinary_talent_ids": 2,
            },
            "presented_legal_first_cycle_pairs": [
                {
                    "sphere_id": "sphere.fire",
                    "talent_id": "talent.fire.free",
                    "sphere_name": "Fire",
                    "talent_name": "Ember Gift",
                },
                {
                    "sphere_id": "sphere.water",
                    "talent_id": "talent.water.free",
                    "sphere_name": "Water",
                    "talent_name": "River Gift",
                },
            ],
            "required_milestone_resolutions": {
                "milestone.fire.1": {
                    "milestone_id": "milestone.fire.1",
                    "path_id": "path.fire",
                    "resolution_options": {
                        "cultivation_insight_acquisition": {
                            "destination": "acquisition_intent.insight_occurrences[]",
                            "allowed_insight_ids": ["insight.core"],
                            "parameters_by_insight_id": {
                                "insight.core": {
                                    "ability": {"allowed_values": ["INT", "WIS"]},
                                },
                            },
                        },
                    },
                },
                "milestone.fire.2": {
                    "milestone_id": "milestone.fire.2",
                    "path_id": "path.fire",
                    "resolution_options": {
                        "ability_score_change": {
                            "destination": "bounded_choices.ability_score_changes_by_milestone_id.milestone.fire.2",
                        },
                    },
                },
            },
        },
        "sphere_route_modules": [
            {
                "route_id": "route.fire",
                "sphere_id": "sphere.fire",
                "sphere_name": "Fire",
                "capability_tags": ["burst", "precision"],
                "free_talent_pair": {
                    "sphere_id": "sphere.fire",
                    "talent_id": "talent.fire.free",
                },
                "ordinary_talent_ids_by_cl": {
                    "1": "talent.fire.1",
                    "2": "talent.fire.2",
                    "3": "talent.fire.free",
                },
            },
            {
                "route_id": "route.water",
                "sphere_id": "sphere.water",
                "sphere_name": "Water",
                "capability_tags": ["flow"],
                "free_talent_pair": {
                    "sphere_id": "sphere.water",
                    "talent_id": "talent.water.free",
                },
                "ordinary_talent_ids_by_cl": {
                    "1": "talent.water.1",
                    "2": "talent.water.2",
                },
            },
        ],
        "ordinary_talent_shortlist_by_sphere": {
            "sphere.fire": [
                {"id": "talent.fire.free", "name": "Ember Gift"},
                {"id": "talent.fire.1", "name": "First Flame"},
                {"id": "talent.fire.2", "name": "Second Flame"},
            ],
            "sphere.water": [
                {"id": "talent.water.free", "name": "River Gift"},
                {"id": "talent.water.1", "name": "First Current"},
                {"id": "talent.water.2", "name": "Second Current"},
            ],
        },
        "allowed_choices_by_slot": {
            "path_choice": [{"id": "path.fire", "name": "Fire Path"}],
            "insight_priorities": [{"id": "insight.core", "name": "Core Insight"}],
        },
        "selection_limits_by_slot": {
            "insight_priorities": {"final_min": 1, "final_max": 2, "allow_none": True},
        },
    }
    return request, envelope


def _option(menu, *choice_ids: str):
    return next(option for option in menu.options if option.choice_ids == choice_ids)


def _commit_first(menu, state: CommittedState) -> CommittedState:
    option = next(option for option in menu.options if option.choice_ids)
    return commit_option(menu, option.option_id, state)


def test_s2_pair_repetition_subtracts_committed_pairs_and_uses_exact_source() -> None:
    request, envelope = _fixture()
    state = CommittedState.empty()

    first = build_sphere_free_talent_pair_menu(request, envelope, state, pair_index=1)
    assert first is not None
    assert first.min_choices == first.max_choices == 1
    assert {option.choice_ids for option in first.options} == {
        ("sphere.fire", "talent.fire.free"),
        ("sphere.water", "talent.water.free"),
    }
    state = _commit_first(first, state)

    second = build_sphere_free_talent_pair_menu(request, envelope, state, pair_index=2)
    assert second is not None
    assert {option.choice_ids for option in second.options} == {
        ("sphere.water", "talent.water.free"),
    }
    state = _commit_first(second, state)
    assert [(row["sphere_id"], row["talent_id"]) for row in state.pairs] == [
        ("sphere.fire", "talent.fire.free"),
        ("sphere.water", "talent.water.free"),
    ]
    assert build_sphere_free_talent_pair_menu(request, envelope, state, pair_index=3) is None


def test_s2_route_is_filtered_by_committed_pair_and_commits_route_only() -> None:
    request, envelope = _fixture()
    state = CommittedState.empty().with_pair("sphere.fire", "talent.fire.free")
    menu = build_sphere_route_menu(request, envelope, state)
    assert menu is not None
    assert all(option.kind == OPTION_BUNDLE for option in menu.options)
    assert {option.choice_ids for option in menu.options} == {("route.fire",)}
    state = _commit_first(menu, state)
    assert state.route_id == "route.fire"
    assert "sphere_route" not in state.by_slot

    mismatched = CommittedState.empty().with_pair("sphere.void", "talent.void.free")
    assert build_sphere_route_menu(request, envelope, mismatched) is None


def test_s2_ordinary_menus_are_route_subsets_and_exclude_pair_or_used_talents() -> None:
    request, envelope = _fixture()
    state = (
        CommittedState.empty()
        .with_pair("sphere.fire", "talent.fire.free")
        .with_route("route.fire")
    )
    cl1 = build_ordinary_talent_menu(request, envelope, state, cl=1)
    assert cl1 is not None
    assert cl1.min_choices == cl1.max_choices == 1
    assert {option.choice_ids[0] for option in cl1.options} <= {"talent.fire.1"}
    state = _commit_first(cl1, state)

    cl2 = build_ordinary_talent_menu(request, envelope, state, cl=2)
    assert cl2 is not None
    assert {option.choice_ids[0] for option in cl2.options} <= {"talent.fire.2"}
    state = _commit_first(cl2, state)
    assert build_ordinary_talent_menu(request, envelope, state, cl=3) is None
    assert "talent.fire.free" not in state.ordinary_by_cl.values()


def test_s2_sphere_priorities_are_one_deterministic_bundle() -> None:
    request, envelope = _fixture()
    state = (
        CommittedState.empty()
        .with_pair("sphere.water", "talent.water.free")
        .with_pair("sphere.fire", "talent.fire.free")
        .with_route("route.fire")
    )
    first = build_sphere_priorities_menu(request, envelope, state)
    again = build_sphere_priorities_menu(request, envelope, state)
    assert first is not None and again is not None
    assert first.to_dict() == again.to_dict()
    assert first.min_choices == first.max_choices == 1
    assert first.options[0].kind == OPTION_BUNDLE
    assert first.options[0].choice_ids == ("sphere.fire", "sphere.water")
    committed = _commit_first(first, state)
    assert committed.by_slot["sphere_priorities"] == ["sphere.fire", "sphere.water"]


def test_s2_insight_priority_none_waits_for_frozen_minimum() -> None:
    request, envelope = _fixture()
    state = CommittedState.empty()
    first = build_insight_priorities_menu(request, envelope, state)
    assert first is not None
    assert all(option.kind != OPTION_NONE for option in first.options)
    state = _commit_first(first, state)
    second = build_insight_priorities_menu(request, envelope, state)
    assert second is not None
    none = next(option for option in second.options if option.kind == OPTION_NONE)
    assert commit_option(second, none.option_id, state) == state


def test_s2_insight_occurrence_is_typed_and_parameterized() -> None:
    request, envelope = _fixture()
    state = CommittedState.empty().with_slot("path_choice", ["path.fire"])
    first = build_insight_occurrence_menu(request, envelope, state, milestone_id="milestone.fire.1")
    assert first is not None
    assert first.step_id == "insight_occurrence:milestone.fire.1"
    assert first.min_choices == first.max_choices == 1
    assert {option.choice_ids for option in first.options} == {("insight.core",)}
    selected = _option(first, "insight.core")
    committed = commit_option(first, selected.option_id, state)
    assert committed.insight_occurrences == [{
        "insight_id": "insight.core",
        "milestone_id": "milestone.fire.1",
    }]
    follow_up = build_insight_occurrence_menu(
        request,
        envelope,
        committed,
        milestone_id="milestone.fire.1",
    )
    assert follow_up is not None
    assert follow_up.step_id == "insight_occurrence:milestone.fire.1:ability"
    assert follow_up.min_choices == follow_up.max_choices == 1
    assert {option.choice_ids for option in follow_up.options} == {("INT",), ("WIS",)}
    ability = _option(follow_up, "INT")
    completed = commit_option(follow_up, ability.option_id, committed)
    assert completed.insight_occurrences == [{
        "insight_id": "insight.core",
        "milestone_id": "milestone.fire.1",
        "parameters": {"ability": "INT"},
    }]
    assert build_insight_occurrence_menu(
        request,
        envelope,
        completed,
        milestone_id="milestone.fire.1",
    ) is None
    assert build_insight_occurrence_menu(
        request,
        envelope,
        state,
        milestone_id="milestone.fire.2",
    ) is None
    replayed = replay_committed_state(
        [
            {"event_type": "STEP_COMMITTED", "step_id": first.step_id, "choice_ids": ["insight.core"]},
            {"event_type": "STEP_COMMITTED", "step_id": follow_up.step_id, "choice_ids": ["INT"]},
        ],
        initial=state,
    )
    assert replayed == completed


def test_s2_dispatch_and_prompt_use_typed_payload_fields_without_ids_in_prose() -> None:
    request, envelope = _fixture()
    state = (
        CommittedState.empty()
        .with_slot("path_choice", ["path.fire"])
        .with_pair("sphere.fire", "talent.fire.free")
        .with_route("route.fire")
        .with_ordinary(1, "talent.fire.1")
    )
    assert build_step_menu(request, envelope, CommittedState.empty(), step_id="sphere_free_talent_pair:1") is not None
    route = build_step_menu(
        request,
        envelope,
        CommittedState.empty().with_pair("sphere.fire", "talent.fire.free"),
        step_id="sphere_route",
    )
    assert route is not None and route.options[0].choice_ids == ("route.fire",)
    assert build_step_menu(request, envelope, state, step_id="ordinary_talent:2") is not None
    assert build_step_menu(request, envelope, state.with_ordinary(2, "talent.fire.2"), step_id="sphere_priorities") is not None
    assert build_step_menu(request, envelope, state, step_id="insight_priorities:1") is not None
    occurrence = build_step_menu(request, envelope, state, step_id="insight_occurrence:milestone.fire.1")
    assert occurrence is not None
    assert build_response_schema(occurrence)["properties"]["option_id"]["enum"] == list(occurrence.option_ids)

    prompt = build_step_prompt(request, envelope, state, occurrence)
    assert "Fire Path" in prompt
    assert "First Flame" in prompt
    assert "route.fire" not in prompt
    assert "talent.fire.free" not in prompt
    assert "talent.fire.1" not in prompt
    assert "milestone.fire.1" not in prompt


@pytest.mark.parametrize("step_id", [
    "sphere_free_talent_pair:1",
    "sphere_route",
    "ordinary_talent:1",
    "sphere_priorities",
    "insight_priorities:1",
    "insight_occurrence:milestone.fire.1",
])
def test_s2_source_fields_are_the_synthetic_provider_payload_fields(step_id: str) -> None:
    request, envelope = _fixture()
    state = CommittedState.empty().with_slot("path_choice", ["path.fire"])
    if step_id != "sphere_free_talent_pair:1":
        state = state.with_pair("sphere.fire", "talent.fire.free")
    if step_id not in {"sphere_free_talent_pair:1", "sphere_route"}:
        state = state.with_route("route.fire")
    menu = build_step_menu(request, envelope, state, step_id=step_id)
    assert menu is not None
