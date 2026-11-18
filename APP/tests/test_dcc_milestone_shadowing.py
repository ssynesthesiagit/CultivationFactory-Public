"""Advancement milestones are one character choice per level, not one per Path.

Owner ruling 2026-09-13: every chosen Path advances at every level, but the
ability-score-improvement-or-Insight milestone at a CL is character-level.
When two selected Paths carry that milestone at the same CL, the walk offers
it once: resolving one Path's copy pins that Path as the level's
representative and shadows the other copy, and a committed representative
shadows the other Path's copy up front.
"""
from __future__ import annotations

from character_creation.creative_controller.linear_menus import (
    CommittedState,
    build_asi_milestone_menu,
    build_path_progression_menu,
    milestone_shadowed,
    progression_step_expected,
)
from character_creation.creative_controller.linear_walk import commit_option

FIRE = "path.fire"
WATER = "path.water"
FIRE_MILESTONE = "path.fire.feature.advancement_choice.cl1"
WATER_MILESTONE = "path.water.feature.advancement_choice.cl1"


def _milestone(milestone_id: str, path_id: str) -> dict:
    return {
        "milestone_id": milestone_id,
        "path_id": path_id,
        "cl": 1,
        "resolution_cardinality": "exactly_one",
        "resolution_options": {
            "ability_score_change": {
                "destination": f"bounded_choices.ability_score_changes_by_milestone_id.{milestone_id}",
                "constraints": {"allowed_abilities": ["STR", "DEX"], "allowed_deltas": [1, 2], "budget": 2, "cap": 15},
            }
        },
    }


def _fixture() -> tuple[dict, dict, CommittedState]:
    request = {
        "request_sha256": "a" * 64,
        "bounded_choice_contract": {"fields": {"path_progression_by_cl": {"1": [FIRE, WATER]}}},
    }
    envelope = {
        "envelope_sha256": "b" * 64,
        "response_contract": {
            "required_milestone_resolutions": {
                FIRE_MILESTONE: _milestone(FIRE_MILESTONE, FIRE),
                WATER_MILESTONE: _milestone(WATER_MILESTONE, WATER),
            },
            "presented_legal_path_progression_ids_by_cl": {"1": [FIRE, WATER]},
        },
    }
    state = CommittedState.empty().with_slot("path_choice", [FIRE, WATER]).with_bounded(
        "ability_scores", {"STR": 13, "DEX": 13, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10}
    )
    return request, envelope, state


def test_both_copies_are_offered_until_one_is_resolved_then_the_other_is_shadowed() -> None:
    request, envelope, state = _fixture()
    fire_menu = build_asi_milestone_menu(request, envelope, state, milestone_id=FIRE_MILESTONE)
    assert fire_menu is not None
    assert build_asi_milestone_menu(request, envelope, state, milestone_id=WATER_MILESTONE) is not None
    committed = commit_option(fire_menu, fire_menu.options[0].option_id, state)
    assert set(committed.bounded["ability_score_changes_by_milestone_id"]) == {FIRE_MILESTONE}
    water_row = envelope["response_contract"]["required_milestone_resolutions"][WATER_MILESTONE]
    assert milestone_shadowed(request, envelope, committed, water_row) is True
    assert build_asi_milestone_menu(request, envelope, committed, milestone_id=WATER_MILESTONE) is None
    # The resolved milestone pins the level's representative Path.
    assert progression_step_expected(request, envelope, committed, 1) is True
    progression = build_path_progression_menu(request, envelope, committed, cl=1)
    assert progression is not None
    assert [option.choice_ids[0] for option in progression.options if option.choice_ids] == [FIRE]
    pinned = commit_option(progression, progression.options[0].option_id, committed)
    assert pinned.bounded["path_progression_by_cl"]["1"] == FIRE


def test_a_committed_representative_shadows_the_other_path_s_copy() -> None:
    request, envelope, state = _fixture()
    progression = build_path_progression_menu(request, envelope, state, cl=1)
    assert progression is not None
    water_option = next(option for option in progression.options if option.choice_ids == (WATER,) or option.choice_ids == [WATER])
    committed = commit_option(progression, water_option.option_id, state)
    assert committed.bounded["path_progression_by_cl"]["1"] == WATER
    assert build_asi_milestone_menu(request, envelope, committed, milestone_id=FIRE_MILESTONE) is None
    assert build_asi_milestone_menu(request, envelope, committed, milestone_id=WATER_MILESTONE) is not None


def test_single_path_milestones_are_never_shadowed() -> None:
    request, envelope, _state = _fixture()
    state = CommittedState.empty().with_slot("path_choice", [FIRE]).with_bounded(
        "ability_scores", {"STR": 13, "DEX": 13, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10}
    )
    fire_row = envelope["response_contract"]["required_milestone_resolutions"][FIRE_MILESTONE]
    assert milestone_shadowed(request, envelope, state, fire_row) is False
    assert build_asi_milestone_menu(request, envelope, state, milestone_id=FIRE_MILESTONE) is not None
