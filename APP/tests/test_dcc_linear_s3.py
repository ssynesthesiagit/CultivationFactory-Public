"""Provider-free L3 checks for bounded S3 linear DCC choices."""

from __future__ import annotations

from character_creation.creative_controller import (
    CommittedState,
    build_asi_milestone_menu,
    build_background_language_menu,
    build_path_progression_menu,
    build_path_skill_menu,
    build_point_buy_assignment_menu,
    build_point_buy_preset_menu,
    build_step_menu,
    commit_option,
)
from character_creation.creative_controller.linear_walk import _step_descriptors


ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
COSTS = {"8": 0, "9": 1, "10": 2, "11": 3, "12": 4, "13": 5, "14": 7, "15": 9}


def _fixture() -> tuple[dict, dict]:
    request = {
        "request_sha256": "a" * 64,
        "bounded_choice_contract": {
            "fields": {
                "ability_scores": {
                    "type": "point_buy_scores",
                    "abilities": list(ABILITIES),
                    "allowed_values": list(range(8, 16)),
                    "budget": 27,
                },
                "ability_score_changes_by_milestone_id": {
                    "milestone.asi": {
                        "allowed_abilities": ["STR", "DEX", "CON"],
                        "allowed_deltas": [1, 2],
                        "budget": 2,
                        "cap": 15,
                    },
                },
                "path_progression_by_cl": {
                    "1": ["path.fire", "path.water"],
                    "2": ["path.fire"],
                },
            },
            "starting_proficiency_choice_contract": {
                "fields": {
                    "path_skill_choices_by_path_id": {
                        "path.fire": {
                            "choice_kind": "path_skill",
                            "choice_id": "path.fire",
                            "required_count": 2,
                            "allowed_values": ["Arcana", "Athletics"],
                        },
                    },
                    "origin_skill_choices_by_origin_id": {
                        "origin.scholar": {
                            "choice_kind": "origin_skill",
                            "choice_id": "origin.scholar",
                            "required_count": 1,
                            "allowed_values": ["History"],
                        },
                    },
                    "background_language_choices_by_background_id": {
                        "background.wanderer": {
                            "choice_kind": "background_language",
                            "choice_id": "background.wanderer",
                            "language_choice_count": 1,
                            "allowed_values": ["Classical", "Draconic"],
                        },
                    },
                },
            },
        },
    }
    envelope = {
        "envelope_sha256": "b" * 64,
        "bounded_choice_summary": {
            "ability_scores": {
                "abilities": list(ABILITIES),
                "allowed_values": list(range(8, 16)),
                "cost_by_value": COSTS,
                "budget": 27,
                "exact_budget": 27,
                "legal_score_presets": [
                    {"scores": [15, 14, 13, 12, 10, 8], "cost": 27, "permutable_across_abilities": True},
                    {"scores": [15, 15, 12, 11, 10, 8], "cost": 27, "permutable_across_abilities": False},
                ],
            },
        },
        "response_contract": {
            "required_milestone_resolutions": {
                "milestone.asi": {
                    "milestone_id": "milestone.asi",
                    "path_id": "path.fire",
                    "cl": 1,
                    "resolution_cardinality": "exactly_one",
                    "resolution_options": {
                        "ability_score_change": {
                            "destination": "bounded_choices.ability_score_changes_by_milestone_id.milestone.asi",
                        },
                    },
                },
            },
            "presented_legal_path_progression_ids_by_cl": {
                "1": ["path.fire", "path.water"],
                "2": ["path.fire"],
            },
        },
    }
    return request, envelope


def _first_option(menu):
    return next(option for option in menu.options if option.choice_ids)


def _score_tokens(option, prefix: str) -> dict[str, int]:
    result = {}
    for token in option.choice_ids:
        parts = token.split(":")
        if prefix == "point_buy_preset":
            _, _mode, ability, score = parts
        else:
            _, ability, score = parts
        result[ability] = int(score)
    return result


def _score_state() -> CommittedState:
    return CommittedState.empty().with_bounded(
        "ability_scores",
        {"STR": 15, "DEX": 14, "CON": 13, "INT": 12, "WIS": 10, "CHA": 8},
    )


def test_l3_point_buy_presets_are_exact_budget_and_assignments_are_deterministic() -> None:
    request, envelope = _fixture()
    first = build_point_buy_preset_menu(request, envelope)
    again = build_point_buy_preset_menu(request, envelope)
    assert first is not None and again is not None
    assert first.to_dict() == again.to_dict()
    assert first.min_choices == first.max_choices == 1
    assert len(first.options) == 2
    for option in first.options:
        scores = _score_tokens(option, "point_buy_preset")
        assert set(scores) == set(ABILITIES)
        assert sum(COSTS[str(value)] for value in scores.values()) == 27

    permutable = next(option for option in first.options if ":permutable:" in option.choice_ids[0])
    state = commit_option(first, permutable.option_id)
    assignment = build_point_buy_assignment_menu(request, envelope, state)
    assignment_again = build_point_buy_assignment_menu(request, envelope, state)
    assert assignment is not None and assignment_again is not None
    assert assignment.to_dict() == assignment_again.to_dict()
    assert len(assignment.options) <= 12
    preset_scores = sorted(state.bounded["point_buy_preset"]["scores"], reverse=True)
    for option in assignment.options:
        if option.is_continuation:
            assert not option.choice_ids and assignment.next_page_id is not None
            continue
        scores = _score_tokens(option, "point_buy_assignment")
        assert set(scores) == set(ABILITIES)
        assert sorted(scores.values(), reverse=True) == preset_scores
    committed = commit_option(assignment, assignment.options[0].option_id, state)
    assert set(committed.bounded["ability_scores"]) == set(ABILITIES)


def test_l3_asi_options_are_contract_subsets_and_respect_cap_and_budget() -> None:
    request, envelope = _fixture()
    state = _score_state().with_slot("path_choice", ["path.fire"])
    menu = build_asi_milestone_menu(request, envelope, state, milestone_id="milestone.asi")
    assert menu is not None
    assert menu.min_choices == menu.max_choices == 1
    assert len(menu.options) <= 12
    for option in menu.options:
        pairs = [token.split(":") for token in option.choice_ids]
        assert all(parts[0] == "asi" and parts[1] in {"STR", "DEX", "CON"} and int(parts[2]) in {1, 2} for parts in pairs)
        assert sum(int(parts[2]) for parts in pairs) == 2
        assert all(state.bounded["ability_scores"][parts[1]] + int(parts[2]) <= 15 for parts in pairs)
    committed = commit_option(menu, menu.options[0].option_id, state)
    assert committed.bounded["ability_score_changes_by_milestone_id"]["milestone.asi"]["deltas"]


def test_l3_progression_is_only_ambiguous_contract_values() -> None:
    request, envelope = _fixture()
    selected = _score_state().with_slot("path_choice", ["path.fire", "path.water"])
    menu = build_path_progression_menu(request, envelope, selected, cl=1)
    assert menu is not None
    assert {option.choice_ids for option in menu.options} == {("path.fire",), ("path.water",)}
    assert build_path_progression_menu(request, envelope, selected, cl=2) is None
    state = commit_option(menu, menu.options[0].option_id, selected)
    assert state.bounded["path_progression_by_cl"]["1"] in {"path.fire", "path.water"}


def test_l3_starting_proficiency_values_are_exact_and_repeated_steps_are_bounded() -> None:
    request, envelope = _fixture()
    state = _score_state().with_slot("path_choice", ["path.fire"])
    first = build_path_skill_menu(request, envelope, state, path_id="path.fire")
    assert first is not None and {option.choice_ids for option in first.options} == {("Arcana",), ("Athletics",)}
    state = commit_option(first, first.options[0].option_id, state)
    second = build_step_menu(request, envelope, state, step_id="path_skill:path.fire:2")
    assert second is not None
    assert {option.choice_ids for option in second.options} == {("Athletics",)}
    state = commit_option(second, second.options[0].option_id, state)
    assert state.bounded["path_skill_choices_by_path_id"]["path.fire"] == [first.options[0].choice_ids[0], "Athletics"]

    state = state.with_slot("origin_insight_choice", ["origin.scholar"]).with_slot("background_choice", ["background.wanderer"])
    assert build_step_menu(request, envelope, state, step_id="origin_skill:origin.scholar") is not None
    language = build_background_language_menu(request, envelope, state, background_id="background.wanderer")
    assert language is not None
    assert {option.choice_ids[0] for option in language.options} == {"Classical", "Draconic"}


def test_l3_descriptor_order_places_s3_between_s2_and_item_identity() -> None:
    request, envelope = _fixture()
    state = (
        _score_state()
        .with_slot("path_choice", ["path.fire"])
        .with_slot("origin_insight_choice", ["origin.scholar"])
        .with_slot("background_choice", ["background.wanderer"])
        .with_bounded("path_skill_choices_by_path_id", {"path.fire": ["Arcana"]})
        .with_bounded("origin_skill_choices_by_origin_id", {"origin.scholar": ["History"]})
        .with_bounded("background_language_choices_by_background_id", {"background.wanderer": ["Classical"]})
        .with_bounded("path_progression_by_cl", {"1": "path.fire"})
    )
    descriptors = _step_descriptors(request, envelope, state)
    kinds = [kind for _step_id, kind, _slot in descriptors]
    assert kinds.index("asi_milestone") < kinds.index("path_skill")
    assert kinds.index("path_skill") < kinds.index("item_priorities")
    # The character is conceived first (identity opens the walk, 2026-09-23).
    assert kinds[0] == "identity"
