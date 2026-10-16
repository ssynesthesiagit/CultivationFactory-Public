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
