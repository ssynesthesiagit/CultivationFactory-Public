"""Ranged attacks ignore adjacent enemies that cannot see the attacker."""

from combat.gate5_service import CombatService
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import LEFT, RIGHT, table_fight


def test_invisible_archer_is_not_disadvantaged_by_unseeing_adjacent_enemies(tmp_path):
    talent = "tianxia.talent.illusion.greater_invisibility"
    kit = {"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.gong_jian", "quantity": 1},
        {"item_id": "tianxia.mortal.gear.arrows_20", "quantity": 1},
    ]}}
    combat, table, match_id = table_fight(tmp_path, [talent], ally_talents=[], kit=kit)

    state = table.state(match_id)
    group = next(g for g in state["menu"]["actions"] if talent in g["source_definition_id"])
    own = next(o for o in group["options"] if LEFT in o["target_ids"])
    assert table.act(match_id, own["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    for _ in range(12):
        if table.state(match_id)["menu"]["actor_id"] == RIGHT:
            break
        assert act(table, match_id, "end")["status"] == "COMMITTED"
    assert table.state(match_id)["menu"]["actor_id"] == RIGHT
    assert act(table, match_id, "end")["status"] == "COMMITTED"
    for _ in range(12):
        if table.state(match_id)["menu"]["actor_id"] == LEFT:
            break
        assert act(table, match_id, "end")["status"] == "COMMITTED"
    assert table.state(match_id)["menu"]["actor_id"] == LEFT
    # The willing caster, not every creature nearby, received Greater Invisibility.
    assert table.state(match_id)["menu"]["actor_id"] == LEFT
    staged = combat._load_session(match_id).engine
    from combat.target_knowledge import can_see
    assert staged._distance_actor_to_actor(staged.state.actors[LEFT], staged.state.actors[RIGHT]) <= 5
    assert not can_see(staged, staged.state.actors[RIGHT], staged.state.actors[LEFT])

    state = table.state(match_id)
    group = next(group for group in state["menu"]["actions"]
                 if ".weapon.gong_jian" in group["source_definition_id"]
                 and "#" not in group["source_definition_id"])
    option = next(option for option in group["options"] if RIGHT in option["target_ids"])
    assert table.act(match_id, option["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"

    loaded = CombatService(combat.source_root, tmp_path)._load_session(match_id)
    attacker = loaded.engine.state.actors[LEFT]
    assert any("invisible" in condition.condition_id for condition in attacker.conditions.values())
    rolls = [event for event in loaded.engine.events
             if event.event_type == "ATTACK_ROLLED" and event.actor_id == LEFT and RIGHT in event.target_ids]
    assert rolls and all(event.payload["mode"] == "ADVANTAGE" for event in rolls)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
