"""TEMPORARY probe (never committed): where does the AI-thrown axe end up?"""
import json

from combat import carry
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_attack_abilities import ROOT
from tests.test_thrown_possession import AXE, act, fixture, reload


def _pos(engine, who):
    return engine.state.actors[who].position.model_dump(mode="json")


def test_probe_ai_throw(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    original = reload(tmp_path, mid)
    before = carry.weight(original.engine, original.engine.state.actors[actor])
    target_position = _pos(original.engine, foe)
    data = {"before": before, "target": target_position, "steps": []}
    rolls = []
    for _ in range(12):
        state = table.state(mid)
        step = {"menu_actor": state["menu"]["actor_id"],
                "actions": [g["source_definition_id"] for g in state["menu"]["actions"]],
                "actor_pos": _pos(original.engine, actor)}
        if state["menu"]["actor_id"] == foe:
            step["result"] = act(table, mid, "end")["status"]
        else:
            step["result"] = table.auto_step(mid, state["last_sequence"], [])["status"]
        loaded = reload(tmp_path, mid)
        step["after_actor_pos"] = _pos(loaded.engine, actor)
        step["conditions"] = [dict(c.data or {}) for c in loaded.engine.state.actors[actor].conditions.values()]
        rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor
                 and e.source_definition_id.endswith(".weapon.fu#thrown")]
        step["thrown_rolls"] = len(rolls)
        data["steps"].append(step)
        if rolls:
            break
    if not rolls:
        raise AssertionError("NO THROW: " + json.dumps(data))
    base = rolls[0].source_definition_id.split("#")[0]
    loaded = reload(tmp_path, mid)
    data["base"] = base
    data["final_actor_pos"] = _pos(loaded.engine, actor)
    data["final_foe_pos"] = _pos(loaded.engine, foe)
    data["conditions"] = [dict(c.data or {}) for c in loaded.engine.state.actors[actor].conditions.values()]
    data["weight_after"] = carry.weight(loaded.engine, loaded.engine.state.actors[actor])
    data["holds"] = carry.holds(loaded.engine, loaded.engine.state.actors[actor], AXE)
    data["dropped_items"] = table._dropped_items(mid)
    data["replay"] = loaded.mechanical.replay()["status"]
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")
    data["end1"] = act(table, mid, "end")["status"]
    data["end2"] = act(table, mid, "end")["status"]
    state = table.state(mid)
    data["offered"] = [g["source_definition_id"] for g in state["menu"]["actions"]]
    data["menu_actor"] = state["menu"]["actor_id"]
    raise AssertionError("PROBE: " + json.dumps(data))
