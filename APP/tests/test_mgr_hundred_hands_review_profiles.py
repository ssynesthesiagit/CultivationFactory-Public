"""R4: specialized weapon profiles and independently increased melee reach.

The family is acquired through the real Restricted Scripture journey boundary.
Every table commit cold-reloads, verifies its journal and mechanically replays.
No browser or model transport is used.
"""
import pytest

from combat.gate5_service import CombatService
from tests.h48_table_support import candidate
from tests.test_mgr_hundred_hands_native import (
    ROOT, OWNER, FOE, HANDS, PREFIX, table_fixture,
)


def engine_at(tmp_path, match):
    return CombatService(ROOT, tmp_path)._load_session(match).engine


@pytest.mark.parametrize("economy,omits_damage", [("ACTION", False), ("BONUS_ACTION", True)])
def test_constitution_profiles_preserve_maneuver_costs_requirements_and_offhand_damage(economy, omits_damage):
    from copy import deepcopy
    from combat.ext.hundred_hands import wheel_constitution_profiles
    original = {
        "source_definition_id": "action:typed.test.weapon.jian#method_breaking",
        "display_name": "Jian attack + Breaking", "economy": economy,
        "costs": [["resource:core.stamina", 2]], "range_ft": 5,
        "parameters": {"requires_resource": {"resource:core.martial_focus": 1},
            "blocked_by_turn_flag": "weapon_method",
            "typed": {"source": "tianxia.mortal.weapon.jian", "proficient": True,
                "numbers": {"attack_bonus": 5, "key_mod": 1, "save_dc": 13},
                "weapon": {"ability": "STR", "ability_modifier": 1,
                    "properties": "Finesse", "omits_ability_damage": omits_damage,
                    "damage": {"count": 1, "sides": 8, "modifier": 0 if omits_damage else 1}},
                "effects": [{"type": "attack", "count": 2,
                    "on_hit": [{"type": "weapon_method", "name": "Breaking"}]}]}}
    }
    saved = deepcopy(original)
    variants = wheel_constitution_profiles([original], 4, 9)
    assert len(variants) == 2
    assert original == saved
    for action in variants:
        assert action["costs"] == original["costs"]
        assert action["parameters"]["requires_resource"] == original["parameters"]["requires_resource"]
        assert action["parameters"]["blocked_by_turn_flag"] == "weapon_method"
        typed = action["parameters"]["typed"]
        assert typed["effects"] == original["parameters"]["typed"]["effects"]
        assert typed["numbers"]["save_dc"] == 13
        assert typed["weapon"]["damage"]["modifier"] == (0 if omits_damage else 4)
    assert [a["parameters"]["typed"]["numbers"]["attack_bonus"] for a in variants] == [8, 9]
    # A second pass must not register another profile for either purpose.
    assert wheel_constitution_profiles([original, *variants], 4, 9) == []


@pytest.mark.parametrize("delivery", ["ordinary", "sequence"])
@pytest.mark.parametrize("profile", ["#mandala_con", "#integrated_con"])
def test_acquired_wheel_keeps_lunge_and_its_native_use(tmp_path, delivery, profile):
    combat, table, match, commit = table_fixture(
        tmp_path, cl=10, foe_at=(5, 6), owner_features=("TAL_FENCING_LUNGE",),
        ability_mods={"STR": 1, "DEX": 1, "CON": 4},
    )
    engine = engine_at(tmp_path, match)
    action = next((a for a in engine.action_catalog.values()
                   if a.owner_id == OWNER and ".weapon.jian#lunge" in a.source_definition_id
                   and a.source_definition_id.endswith(profile)), None)
    assert action is not None, "Weapon-Wheel must preserve both modifiers for Lunge"
    assert action.parameters["lunge"]
    assert action.parameters["requires_resource"]
    assert action.parameters["typed"]["weapon"]["ability"] == "CON"
    from combat.ext.hundred_hands import _attack_choices, known_attacks
    option = action.source_definition_id + "|" + FOE
    choices = _attack_choices(engine, engine.state.actors[OWNER], None)
    assert option in choices
    assert option in known_attacks(engine, engine.state.actors[OWNER], choices)
    if delivery == "ordinary":
        commit(candidate(table, match, action.display_name, FOE))
    else:
        commit(candidate(table, match, "Weapon-Wheel Body: Attack with weapon choices"),
               {"weapon_wheel_gear": "keep", "weapon_wheel_attack": option})
        prompts = [p for p in commit.prompts
                   if "weapon_wheel_attack" in str(p)]
        assert any(option in [o["id"] for o in p["choice"]["options"]] for p in prompts)
    engine = engine_at(tmp_path, match)
    rolls = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"
             and e.actor_id == OWNER and e.source_definition_id == action.source_definition_id]
    assert rolls
    assert rolls[0].payload["modifier"] == (8 if profile == "#mandala_con" else 100)
    from combat.ext.needle_footwork import LUNGE
    assert any(c.condition_id == LUNGE for c in engine.state.actors[OWNER].conditions.values())
    # Losing the printed prerequisite removes the profile from the sequence as
    # well as from the ordinary menu; the grant cannot bypass Martial Focus.
    actor = engine.state.actors[OWNER]
    for rid in action.parameters["requires_resource"]:
        actor.resources[rid] = 0
    assert option not in _attack_choices(engine, actor, None)


@pytest.mark.parametrize("delivery", ["sequence", "circle"])
def test_incarnation_composes_catalog_reach_in_real_choices_and_strikes(tmp_path, delivery):
    combat, table, match, commit = table_fixture(
        tmp_path, foe_at=(6, 6), owner_features=("TAL_BERSERKER_WAR_GOD_INCARNATION",),
    )
    commit(candidate(table, match, "War-God Incarnation"))
    for _ in range(2):
        commit(table.state(match)["menu"]["end_turn"])
    commit(candidate(table, match, "Thousand-Hand Incarnation"))
    engine = engine_at(tmp_path, match)
    from combat.attack_reach import maximum
    from combat.ext.reach_bonus import current_reach
    from combat.ext.hundred_hands import _attack_choices, circle_reach, known_attacks
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and ".weapon.jian" in a.source_definition_id
                  and a.parameters.get("reach_bonus", {}).get("menu_variant")
                  and "#integrated_con" in a.source_definition_id)
    actor = engine.state.actors[OWNER]
    assert current_reach(engine, actor, action) == 10
    assert maximum(engine, actor, action, base=current_reach(engine, actor, action)) == 15
    assert circle_reach(engine, actor) >= 15
    choices = _attack_choices(engine, actor, None)
    option = action.source_definition_id + "|" + FOE
    assert option in choices, "The combined 15-foot reach must survive sequence admission"
    assert option in known_attacks(engine, actor, choices)
    start = len(engine.events)
    if delivery == "sequence":
        commit(candidate(table, match, "Weapon-Wheel Body: Attack with weapon choices"),
               {"weapon_wheel_gear": "keep", "weapon_wheel_attack": option})
    else:
        commit(table.state(match)["menu"]["end_turn"])
        commit(candidate(table, match, "Dash"),
               {"circle_of_uncounted_arms": "intercept", "circle_strike": option})
    engine = engine_at(tmp_path, match)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER
               and e.source_definition_id == action.source_definition_id
               for e in engine.events[start:])
    assert engine.state.actors[FOE].current_hp < 1000
    if delivery == "circle":
        assert engine.state.actors[OWNER].resources[HANDS] == 10
        assert any(e.event_type == "REACTION_RESOLVED"
                   and e.source_definition_id == PREFIX + "circle_of_uncounted_arms"
                   for e in engine.events[start:])


def test_off_turn_mandala_guard_belongs_to_and_expires_on_the_practitioner(monkeypatch):
    """Modifier-boundary regression for the inherited off-turn ownership issue.

    The four-Hand threshold is arranged through native resource-spent events;
    no claim is made that the current Circle limit alone can spend four Hands
    on one hostile creature's turn.
    """
    from tests import test_riders_c7 as C7
    from combat.ext import hundred_hands, needle
    engine, actor, foe = C7._mandala(["four_hand_sequence", "thousand_hand_incarnation"],
                                   picks={"four_hand_sequence": None})
    C7.use(engine, "Thousand-Hand Incarnation")
    C7.turn(engine, foe.entity_id)
    engine._spend_resource(actor, HANDS, 4, "test:mandala-threshold")
    monkeypatch.setattr(needle, "ask", lambda *args, **kwargs: ["guard"])
    hundred_hands.mandala(engine, actor, None)
    guard = next(m for m in actor.modifiers.values()
                 if m.source_definition_id == PREFIX + "thousand_hand_incarnation"
                 and m.target_field == "armor_class" and m.value == 3)
    assert guard.source_actor_id == actor.entity_id
    C7.turn(engine, foe.entity_id)
    assert guard.instance_id in actor.modifiers
    C7.turn(engine, actor.entity_id)
    assert guard.instance_id not in actor.modifiers
