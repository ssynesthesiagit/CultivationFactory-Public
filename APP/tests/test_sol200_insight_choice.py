"""SOL200: automatic builds take a Cultivation Insight when it is the better pick.

Root cause: production envelopes keep each Insight's typed authority (with its
Realm cap) in ``typed_choice_authority_by_slot.insight_priorities``, not on the
compact row, so the SOL190 advice saw no cap and never recommended an Insight.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from character_creation.creative_controller import seeded_picker
from character_creation.creative_controller.linear_menus import (
    _effective_ability_scores, branch_recommendation, mechanical_choice_detail,
)
from character_creation.creative_controller.linear_prompt import build_step_prompt
from character_creation.insight_build_policy import (
    branch_advice, build_choice_reason, insight_use, recommended_build_option, unverified_prerequisites,
)
from tests import test_insights_are_chosen as levels

PRIORITY = ("INT", "DEX", "CON", "WIS", "CHA", "STR")
USEFUL_INT = {"INT": (2, "Expanded Dantian", "uses your Qi")}


@pytest.mark.parametrize("key, take_insight", [(15, True), (17, True), (19, True), (16, False), (18, False)])
def test_branch_prefers_insight_only_when_plus_one_matches_the_modifier(key, take_insight):
    scores = {"STR": 8, "DEX": 15, "CON": 15, "INT": key, "WIS": 8, "CHA": 8}
    chosen, reason = branch_advice(scores, PRIORITY, 20, USEFUL_INT)
    assert chosen is take_insight
    assert reason and ("INT" in reason)


def test_key_19_takes_insight_over_the_plus_one_split():
    # The owner's bad case: +1/+1 (INT 20, CON 16) is dominated by an Insight
    # that also gives INT 20 plus a used benefit.
    scores = {"STR": 8, "DEX": 15, "CON": 15, "INT": 19, "WIS": 8, "CHA": 8}
    assert branch_advice(scores, PRIORITY, 20, USEFUL_INT)[0] is True
    assert branch_advice(scores, PRIORITY, 20, {})[0] is False


def test_capped_key_moves_to_the_next_used_ability():
    scores = {"STR": 8, "DEX": 15, "CON": 15, "INT": 20, "WIS": 8, "CHA": 8}
    assert branch_advice(scores, PRIORITY, 20, USEFUL_INT)[0] is False
    assert branch_advice(scores, PRIORITY, 20, {"DEX": (1, "Heaven's Luck", "combat benefit")})[0] is True


def _printed(insight_id):
    rules = json.loads((Path(__file__).resolve().parents[1] / "authority/typed_mechanics/rules_text.json").read_text())
    return rules[insight_id]


def test_use_evidence_comes_from_printed_text_and_owned_choices():
    owned = {"tianxia.path.qi_cultivation", "tianxia.sphere.flowing_river", "TAL_FLOWING_RIVER_EMPTY_STEP"}
    sphere_row = {"description": _printed("insight.body-like-water"),
                  "prerequisites": [{"kind": "sphere", "operator": "requires", "target_id": "tianxia.sphere.flowing_river"}]}
    assert insight_use(sphere_row, owned)[0] == 3
    assert insight_use(sphere_row, {"tianxia.path.qi_cultivation"}) is None
    # Untyped printed prerequisites (a Path feature, a bond) are not assumed.
    pressure = {"description": _printed("insight.legacy-pressure-intensification"),
                "prerequisites": [{"kind": "path", "operator": "requires", "target_id": "tianxia.path.spirit_awakening"}]}
    assert unverified_prerequisites(pressure, {"tianxia.path.spirit_awakening"}) == ["domain pressure"]
    assert insight_use(pressure, {"tianxia.path.spirit_awakening"}) is None
    assert insight_use({"description": _printed("insight.legacy-dao-bound-weapon"), "prerequisites": []}, owned) is None
    # Downtime-only benefits are not use; combat statistics are.
    assert insight_use({"description": _printed("insight.legacy-comprehension-through-battle"), "prerequisites": []}, {"x"}) is None
    assert insight_use({"description": _printed("insight.legacy-heavens-luck"), "prerequisites": []}, {"x"})[0] == 1


def _production_shaped(cl, extra=(("insight.expanded-dantian", "Expanded Dantian", ["CON", "INT", "CHA"],
                                     [{"kind": "path", "operator": "requires", "target_id": levels.PATH_ID}]),)):
    """The fixture with typed authority moved where production keeps it.

    ``extra`` adds real catalogue Insights with their owner-printed text.
    """
    request, envelope = levels._request(cl), deepcopy(levels._envelope(cl))
    rows = envelope["choices_by_slot"]["insight_priorities"]
    for insight_id, name, abilities, prerequisites in extra:
        rows[insight_id] = levels._insight_row(insight_id, name, abilities, prerequisites)
        rows[insight_id]["description"] = _printed(insight_id)
    typed = {}
    for insight_id, row in rows.items():
        typed[insight_id] = row.pop("stage2_authority")
    envelope["typed_choice_authority_by_slot"] = {"insight_priorities": {"stage2_authority_by_choice": typed}}
    for milestone in envelope["linear_provider_payload"]["response_contract"]["required_milestone_resolutions"].values():
        option = milestone["resolution_options"]["cultivation_insight_acquisition"]
        for insight_id, _name, abilities, _prerequisites in extra:
            option["allowed_insight_ids"].append(insight_id)
            option["parameters_by_insight_id"][insight_id] = {"allowed_abilities": list(abilities), "amount": 1}
    return request, envelope


def _sphere_owner(scores, sphere_id):
    return levels._starting_state(10).with_ability_scores(scores).with_pair(sphere_id, "TAL_TEST_OWNED")


@pytest.mark.parametrize("seed", ["QB-AAA111", "QB-BBB222"])
def test_session_limited_combat_insight_is_kept_in_menu_and_walk(seed):
    # Review r1: "Before your next Full Cultivation Session, you may replace one
    # attack roll ... or saving throw" is a session-limited combat benefit.
    fate = "tianxia.sphere.fate"
    request, envelope = _production_shaped(10, extra=(("insight.loaded-destiny", "Loaded Destiny", ["WIS", "CHA", "INT"],
                                                       [{"kind": "sphere", "operator": "requires", "target_id": fate}]),))
    start = _sphere_owner({"STR": 8, "DEX": 15, "CON": 15, "INT": 19, "WIS": 8, "CHA": 8}, fate)
    step, state = levels._step_for(request, envelope, start, f"asi_or_insight:{levels._milestone_id(4)}")
    assert recommended_build_option(step.menu).choice_ids == ("cultivation_insight",)
    assert "attack rolls" in branch_recommendation(request, envelope, state, levels._milestone_id(4))[1]
    state = levels._walk_until(request, envelope, start, lambda s: levels._levels_answered(s, 10),
                               chooser=lambda m: seeded_picker.step_receipt(seed, m)["value"]["option_id"])
    assert [(row["insight_id"], row["parameters"]["ability"]) for row in state.insight_occurrences][0] == (
        "insight.loaded-destiny", "INT")
    assert _effective_ability_scores(state, request, envelope)["INT"] == 20


def test_downtime_only_insight_is_excluded_from_menu_and_walk():
    # Arsenal Script Custodian: owned Weapons, but only a downtime project.
    weapons = "tianxia.sphere.weapons"
    request, envelope = _production_shaped(5, extra=(("insight.arsenal-script-custodian", "Arsenal Script Custodian",
                                                      ["STR", "DEX", "CON"],
                                                      [{"kind": "sphere", "operator": "requires", "target_id": weapons}]),))
    start = _sphere_owner({"STR": 15, "DEX": 15, "CON": 15, "INT": 20, "WIS": 8, "CHA": 8}, weapons)
    step, state = levels._step_for(request, envelope, start, f"asi_or_insight:{levels._milestone_id(4)}")
    assert recommended_build_option(step.menu).choice_ids == ("ability_score_increase",)
    state = levels._walk_until(request, envelope, start, lambda s: levels._levels_answered(s, 5),
                               chooser=lambda m: seeded_picker.step_receipt("QB-AAA111", m)["value"]["option_id"])
    assert not state.insight_occurrences


@pytest.mark.parametrize("seed", ["QB-AAA111", "QB-BBB222"])
def test_production_shaped_walk_takes_a_useful_insight_and_keeps_key_strong(seed):
    request, envelope = _production_shaped(10)
    start = levels._starting_state(10).with_ability_scores({"STR": 8, "DEX": 15, "CON": 15, "INT": 17, "WIS": 8, "CHA": 8})
    step, state = levels._step_for(request, envelope, start, f"asi_or_insight:{levels._milestone_id(4)}")
    preferred, reason = branch_recommendation(request, envelope, state, levels._milestone_id(4))
    assert preferred == "cultivation_insight" and "INT 17→18" in reason and "uses your Qi" in reason
    assert recommended_build_option(step.menu).choice_ids == ("cultivation_insight",)
    assert reason in build_step_prompt(request, envelope, state, step.menu)
    detail = mechanical_choice_detail(request, envelope, state, step.menu, recommended_build_option(step.menu))
    assert "uses your Qi" in build_choice_reason(step.menu, recommended_build_option(step.menu), detail)
    state = levels._walk_until(request, envelope, start, lambda s: levels._levels_answered(s, 10),
                               chooser=lambda m: seeded_picker.step_receipt(seed, m)["value"]["option_id"])
    assert [(row["insight_id"], row["parameters"]["ability"]) for row in state.insight_occurrences] == [
        ("insight.expanded-dantian", "INT")]
    assert _effective_ability_scores(state, request, envelope)["INT"] == 20


def _branch(request, envelope, scores):
    start = levels._starting_state(5).with_ability_scores(scores)
    step, _state = levels._step_for(request, envelope, start, f"asi_or_insight:{levels._milestone_id(4)}")
    return recommended_build_option(step.menu).choice_ids


def test_even_key_keeps_focused_increase_even_with_a_useful_insight():
    request, envelope = _production_shaped(5)
    assert _branch(request, envelope, {"STR": 8, "DEX": 15, "CON": 15, "INT": 16, "WIS": 8, "CHA": 8}) == ("ability_score_increase",)


def test_odd_key_without_a_useful_insight_keeps_focused_increase():
    request, envelope = _production_shaped(5)
    # Same Insight, but its printed benefit is only the +1 (no used benefit).
    envelope["choices_by_slot"]["insight_priorities"]["insight.expanded-dantian"]["description"] = (
        "**Ability Increase (Level Selection):** raise CON, INT or CHA by 1.")
    assert _branch(request, envelope, {"STR": 8, "DEX": 15, "CON": 15, "INT": 17, "WIS": 8, "CHA": 8}) == ("ability_score_increase",)


def test_insight_whose_own_cap_blocks_the_key_does_not_win_the_branch():
    # Review finding 1: ASI cap 20, but this Insight's own cap is 18. It can
    # still raise CON 15, never INT 19, so it must not be credited with INT 20.
    request, envelope = _production_shaped(5)
    typed = envelope["typed_choice_authority_by_slot"]["insight_priorities"]["stage2_authority_by_choice"]["insight.expanded-dantian"]
    for key in ("ability_change", "insight_ability_change"):
        typed[key]["cap"] = 18
    scores = {"STR": 8, "DEX": 15, "CON": 15, "INT": 19, "WIS": 8, "CHA": 8}
    assert _branch(request, envelope, scores) == ("ability_score_increase",)
    typed["ability_change"]["cap"] = typed["insight_ability_change"]["cap"] = 20
    assert _branch(request, envelope, scores) == ("cultivation_insight",)


def test_owned_sphere_downtime_only_insight_is_not_recommended_but_mixed_is():
    # Review finding 2: owning the prerequisite Sphere is not use when the
    # whole printed benefit is a downtime project.
    weapons = {"description": _printed("insight.arsenal-script-custodian"),
               "prerequisites": [{"kind": "sphere", "operator": "requires", "target_id": "tianxia.sphere.weapons"}]}
    assert insight_use(weapons, {"tianxia.sphere.weapons"}) is None
    mixed = {"description": _printed("insight.body-like-water"),
             "prerequisites": [{"kind": "sphere", "operator": "requires", "target_id": "tianxia.sphere.flowing_river"}]}
    assert insight_use(mixed, {"tianxia.sphere.flowing_river"})[0] == 3
    # Downtime paragraphs do not hide a combat use elsewhere in the benefit.
    assert insight_use({"description": "**Prerequisite:** CL4+\n\nDuring downtime, keep a ledger.\n\n"
                                       "When you are hit, use your Reaction to halve the damage.", "prerequisites": []},
                       {"x"})[0] == 1
    for downtime in ("insight.legacy-walking-the-ten-thousand-li-circuit", "insight.legacy-quiet-foundation",
                     "insight.legacy-pill-connoisseur", "insight.legacy-heavenly-comprehension"):
        assert insight_use({"description": _printed(downtime), "prerequisites": []},
                           {"tianxia.sphere.fire", "tianxia.path.qi_cultivation"}) is None, downtime


def test_reasons_use_player_facing_names():
    row = {"description": _printed("insight.body-like-water"),
           "prerequisites": [{"kind": "talent", "operator": "requires", "target_id": "TAL_FLOWING_RIVER_EMPTY_STEP"}]}
    owned = {"TAL_FLOWING_RIVER_EMPTY_STEP"}
    assert insight_use(row, owned, {"TAL_FLOWING_RIVER_EMPTY_STEP": "Empty Step"})[1].startswith("builds on your Empty Step")
    fallback = insight_use(row, owned)[1]
    assert "TAL" not in fallback.upper().split() and "Tal " not in fallback and "_" not in fallback
    resource = insight_use({"description": _printed("insight.legacy-empowered-technique"), "prerequisites": []},
                           {"tianxia.sphere.fire"})[1]
    assert "Cultivation Points" in resource and "CP" not in resource.split()
    assert "combat benefit" not in insight_use({"description": _printed("insight.legacy-heavens-luck"),
                                                "prerequisites": []}, {"x"})[1]
