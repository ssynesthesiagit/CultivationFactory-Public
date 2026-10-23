"""SOL183's strict expected failure, now the authorized SOL184 table regression."""
from tests.hunt15_support import LEFT, act, fight, reload, turn


def test_death_finalized_creature_gets_no_later_turns_after_table_reload(tmp_path):
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"], ally=[],
        target="SELF", effects=[{"type": "damage", "flat": 10000, "damage_types": ["untyped"], "applies_to": "self"}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert engine.state.rules["finalized_turns"] == "skip_finalized_v1"
    assert engine.events[0].payload["rules"]["finalized_turns"] == "skip_finalized_v1"
    actor = engine.state.actors[LEFT]
    assert not actor.active
    assert any(c.condition_id == "condition:typed.death_finalized" for c in actor.conditions.values())
    turns = actor.turns_started
    order = list(engine.state.initiative_order)
    defeat = max(e.sequence for e in engine.events if e.event_type == "ENTITY_DEFEATED" and e.actor_id == LEFT)
    for _ in range(8):
        state = table.state(mid)
        if "end_turn" in state["menu"]:
            result = act(table, mid, "end")
        else:
            result = table.auto_step(mid, state["last_sequence"])
        assert result["status"] == "COMMITTED"
        shown = table.state(mid)
        assert shown["presentation"]["current_actor_id"] != LEFT
        assert shown["menu"]["actor_id"] != LEFT
    engine = reload(combat, mid)
    assert engine.state.initiative_order == order
    assert engine.state.actors[LEFT].turns_started == turns
    assert not [e for e in engine.events if e.sequence > defeat and e.event_type == "TURN_STARTED" and e.actor_id == LEFT]
