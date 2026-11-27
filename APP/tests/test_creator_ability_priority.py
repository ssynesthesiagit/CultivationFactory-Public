"""ABILITYPICK1: the creator ranks the abilities of the committed build."""
import pytest

from character_creation.creative_controller.linear_menus import (
    CommittedState, _ability_priority, _effective_ability_scores, branch_recommendation,
)
from character_creation.creative_controller.linear_walk import ACTION_AUTOCOMMITTED, commit_option, next_step
from combat.tabletop import sheet_summary


BODY = "tianxia.path.body_refining"
QI = "tianxia.path.qi_cultivation"
BACKGROUND = "tianxia.background.synthetic"
INSIGHT = "insight.synthetic-qi-reserve"
HIDDEN_EYE = "tianxia.sphere.the_hidden_eye"
WRESTLING = "tianxia.sphere.wrestling"
SHINOBI = "tianxia.subpath.body.shinobi"
PATH_ROWS = [
    {"choice_id": BODY, "display_name": "Body Refining", "stage2_authority": {"key_ability": "CON"}},
    {"choice_id": QI, "display_name": "Qi Cultivation", "stage2_authority": {"key_ability": "INT"}},
]


def _fixture():
    request = {"request_sha256": "a" * 64}
    insight = {
        "choice_id": INSIGHT, "name": "Qi Reserve",
        "description": "Increase your maximum Qi by 2.",
        "stage2_authority": {
            "authority_complete": True,
            "allowed_kinds": ["cultivation_insight_acquisition"],
            "allowed_channels": ["cultivation-insight-selection"],
            "allowed_cls": [4, 8],
            "ability_change": {"allowed_abilities": ["CON", "INT"], "amount": 1, "cap": 20},
        },
    }
    milestones = {}
    for cl in (4, 8):
        milestone_id = f"synthetic.body.cl{cl}"
        milestones[milestone_id] = {
            "milestone_id": milestone_id, "path_id": BODY, "cl": cl,
            "allowed_kinds": ["ability_score_change", "cultivation_insight_acquisition"],
            "resolution_cardinality": "exactly_one",
            "resolution_options": {"ability_score_change": {
                "destination": f"bounded_choices.ability_score_changes_by_milestone_id.{milestone_id}",
                "constraints": {"allowed_deltas": [1, 2], "budget": 2, "cap": 20},
            }},
        }
    envelope = {
        "frozen_owner_target_cl": 8,
        "choices_by_slot": {"path_choice": PATH_ROWS, "insight_priorities": {INSIGHT: insight}},
        "path_progression_choices": [{"cl": cl, "path_ids": [BODY, QI]} for cl in range(1, 9)],
        "advancement_choice_milestones": list(milestones.values()),
        "bounded_choice_contract": {"starting_proficiency_choice_contract": {"fields": {
            "path_skill_choices_by_path_id": {QI: {"allowed_values": ["Arcana", "History"], "required_count": 2}},
            "background_language_choices_by_background_id": {BACKGROUND: {
                "fixed_skill_names": ["Acrobatics", "Stealth"], "language_choice_count": 0,
            }},
        }}},
        "response_contract": {"required_milestone_resolutions": milestones},
    }
    state = CommittedState(
        by_slot={"path_choice": [BODY, QI], "method_choice": ["method.synthetic"],
                 "background_choice": [BACKGROUND], "insight_priorities": [INSIGHT]},
        bounded={"ability_scores": {"STR": 8, "DEX": 15, "CON": 15, "INT": 15, "WIS": 8, "CHA": 8},
                 "background_ability": "INT", "background_ability_amount": 2},
    ).with_identity("Test Cultivator", "Quiet Step", "Uses Qi and stealth.")
    return request, envelope, state


def _choose(step, choice_ids):
    option = next(option for option in step.options if option.choice_ids == choice_ids)
    if step.action == ACTION_AUTOCOMMITTED:
        return step.committed
    return commit_option(step.menu, option.option_id, step.committed)


def _next_expected(request, envelope, state, events, step_id):
    while True:
        step = next_step(request, envelope, state, events)
        if step.action == ACTION_AUTOCOMMITTED:
            events.append(step.event)
        if step.step_id == step_id:
            return step
        assert step.action == ACTION_AUTOCOMMITTED
        state = step.committed


def test_walk_raises_the_dominant_paths_key_at_both_milestones():
    request, envelope, state = _fixture()
    events = []
    for cl in range(1, 9):
        step = _next_expected(request, envelope, state, events, f"path_progression:{cl}")
        state = _choose(step, (BODY if cl in (4, 8) else QI,))

    step = _next_expected(request, envelope, state, events, f"path_skill:{QI}")
    state = _choose(step, ("Arcana",))
    step = _next_expected(request, envelope, state, events, f"path_skill:{QI}:2")
    state = _choose(step, ("History",))
    assert _ability_priority(state, request, envelope)[:3] == ("INT", "CON", "DEX")
    step = _next_expected(request, envelope, state, events, "asi_or_insight:synthetic.body.cl4")
    assert "INT 17→18" in branch_recommendation(request, envelope, step.committed, "synthetic.body.cl4")[1]
    assert step.options[0].choice_ids == ("cultivation_insight",)
    state = _choose(step, step.options[0].choice_ids)

    step = _next_expected(request, envelope, state, events, "insight_occurrence:synthetic.body.cl4")
    state = _choose(step, (INSIGHT,))
    step = _next_expected(request, envelope, state, events, "insight_occurrence:synthetic.body.cl4:ability")
    assert [option.choice_ids for option in step.options] == [("INT",), ("CON",)]
    state = _choose(step, step.options[0].choice_ids)

    step = _next_expected(request, envelope, state, events, "asi_milestone:synthetic.body.cl8")
    assert step.options[0].choice_ids == ("asi:INT:2",)
    state = _choose(step, step.options[0].choice_ids)
    scores = _effective_ability_scores(state, request, envelope)
    assert (scores["INT"], scores["CON"]) == (20, 15)


def test_dual_path_keys_and_sphere_attacks_precede_stealth():
    request, envelope, state = _fixture()
    for cl in range(1, 9):
        state = state.with_path_progression(cl, BODY if cl in (4, 8) else QI)
    state = state.with_pair(HIDDEN_EYE, "synthetic.eye-talent").with_pair(WRESTLING, "synthetic.wrestling-talent")
    assert _ability_priority(state, request, envelope)[:4] == ("INT", "CON", "STR", "DEX")


@pytest.mark.parametrize("source", ["background", "sphere"])
def test_stealth_beats_fallback_constitution_but_not_owned_sphere_attacks(source):
    envelope = {"choices_by_slot": {"path_choice": PATH_ROWS}}
    state = CommittedState(by_slot={"path_choice": [QI], "background_choice": [BACKGROUND]})
    state = state.with_pair(WRESTLING, "synthetic.wrestling-talent")
    assert _ability_priority(state, {}, envelope)[:3] == ("INT", "STR", "CON")
    if source == "background":
        envelope["bounded_choice_contract"] = {"starting_proficiency_choice_contract": {"fields": {
            "background_language_choices_by_background_id": {BACKGROUND: {"fixed_skill_names": ["Stealth"]}},
        }}}
    else:
        state = state.with_pair(HIDDEN_EYE, "synthetic.eye-talent")
    assert _ability_priority(state, {}, envelope)[:4] == ("INT", "STR", "DEX", "CON")


@pytest.mark.parametrize("cl, expected", [(2, ("CON", "STR", "DEX")), (3, ("CON", "DEX", "STR"))])
def test_body_refining_keeps_constitution_first_with_or_without_subpath_stealth(cl, expected):
    envelope = {
        "frozen_owner_target_cl": cl,
        "choices_by_slot": {"path_choice": PATH_ROWS,
                            "subpath_choice": [{"choice_id": SHINOBI, "owning_path_id": BODY}]},
        "path_progression_choices": [{"cl": n, "path_ids": [BODY]} for n in range(1, cl + 1)],
    }
    state = CommittedState(by_slot={"path_choice": [BODY], "subpath_choice": [SHINOBI] if cl == 3 else []})
    assert _ability_priority(state, {}, envelope)[:3] == expected


def test_table_sheet_summary_includes_each_paths_own_key_and_modifier():
    sheet = {"identity": {"path": "Body Refining", "key_ability": "CON", "paths": [
        {"display_name": "Body Refining", "key_ability": "CON"},
        {"display_name": "Qi Cultivation", "key_ability": "INT"},
    ]}, "ability_scores_and_statistics": {"hit_points": {"maximum": 30}, "abilities": [
        {"ability": "CON", "score": 16, "modifier": 3},
        {"ability": "INT", "score": 18, "modifier": 4},
    ]}}
    summary = sheet_summary(sheet)
    assert summary["path_key_abilities"] == [
        {"path": "Body Refining", "key_ability": "CON", "modifier": 3},
        {"path": "Qi Cultivation", "key_ability": "INT", "modifier": 4},
    ]
    assert summary["key_ability"] == "CON"  # Legacy readers are unchanged.
