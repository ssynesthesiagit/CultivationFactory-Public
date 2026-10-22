"""TEMPORARY probe (never committed): where does the AI-thrown axe end up?"""
import json

from combat import carry
from combat.gate2_runtime_models import Position
from tests.test_thrown_possession import AXE, act, fixture, reload


def _pos(engine, who):
    return engine.state.actors[who].position.model_dump(mode="json")


def _menu(state):
    menu = state.get("menu") or {}
    return {
        "actor": menu.get("actor_id"),
        "action_ids": [g.get("source_definition_id") for g in (menu.get("actions") or [])],
        "move_count": len(menu.get("moves") or []),
    }


def test_probe_ai_throw(tmp_path):
    combat, table, mid, actor, foe = fixture(tmp_path, automatic=True)
    original = reload(tmp_path, mid)
    before = carry.weight(original.engine, original.engine.state.actors[actor])
    target_position = _pos(original.engine, foe)
    data = {"before": before, "target": target_position,
            "start_actor": _pos(original.engine, actor), "steps": []}
    rolls = []
    for _ in range(12):
        state = table.state(mid)
        step = {"menu": _menu(state), "actor_pos": _pos(original.engine, actor)}
        if state["menu"]["actor_id"] == foe:
            step["result"] = act(table, mid, "end")["status"]
        else:
            step["result"] = table.auto_step(mid, state["last_sequence"], [])["status"]
        loaded = reload(tmp_path, mid)
        step["after_actor_pos"] = _pos(loaded.engine, actor)
        step["after_foe_pos"] = _pos(loaded.engine, foe)
        step["conditions"] = [{k: v for k, v in (c.data or {}).items() if k in ("disables_action", "dropped_at", "held_by")}
                              for c in loaded.engine.state.actors[actor].conditions.values()]
        rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == actor
                 and e.source_definition_id.endswith(".weapon.fu#thrown")]
        step["thrown_rolls"] = len(rolls)
        data["steps"].append(step)
        if rolls:
            break
    data["has_throw"] = bool(rolls)
    loaded = reload(tmp_path, mid)
    actor_state = loaded.engine.state.actors[actor]
    data["final_actor_pos"] = _pos(loaded.engine, actor)
    data["final_foe_pos"] = _pos(loaded.engine, foe)
    data["conditions"] = [{k: v for k, v in (c.data or {}).items() if k in ("disables_action", "dropped_at", "held_by")}
                          for c in actor_state.conditions.values()]
    data["weight_after"] = carry.weight(loaded.engine, actor_state)
    data["holds"] = carry.holds(loaded.engine, actor_state, AXE)
    data["can_pick_up"] = carry.can_pick_up(loaded.engine, actor_state, AXE)
    data["dropped_items"] = table._dropped_items(mid)
    data["replay"] = loaded.mechanical.replay()["status"]
    if rolls:
        base = rolls[0].source_definition_id.split("#")[0]
        data["base"] = base
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")
    data["end1"] = act(table, mid, "end")["status"]
    data["end2"] = act(table, mid, "end")["status"]
    state = table.state(mid)
    data["final_menu"] = _menu(state)
    data["pickup_offered"] = [s for s in data["final_menu"]["action_ids"]
                              if s and s.endswith(".weapon.fu.pickup")]
    loaded = reload(tmp_path, mid)
    data["final2_actor_pos"] = _pos(loaded.engine, actor)
    data["dist_to_drop"] = loaded.engine.grid.distance_ft(
        loaded.engine.state.actors[actor].position, Position(x=target_position["x"], y=target_position["y"]))
    raise AssertionError("PROBE: " + json.dumps(data))
