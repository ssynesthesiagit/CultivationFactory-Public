"""Forced movement reconciles range immediately across table commit/reload."""
import pytest
from tests.hunt12_support import ME, FOE, candidate, fight, reload, send
from tests.test_lock2_persistence import act


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("reach", [5, 10])
def test_shove_breaks_grapple_before_next_turn(tmp_path, monkeypatch, auto, reach):
    from tests import hunt12_support
    original = hunt12_support.compile_character

    def with_reach(*args, **kwargs):
        bundle = original(*args, **kwargs)
        for row in bundle["action_catalog"]:
            if row["display_name"] == "Grapple":
                row["range_ft"] = reach
        return bundle

    monkeypatch.setattr(hunt12_support, "compile_character", with_reach)
    combat, table, mid = fight(tmp_path)
    grapple = candidate(combat, mid, lambda c: c.display_name == "Grapple" and tuple(c.target_ids) == (FOE,))
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    assert send(combat, table, mid, grapple, auto=auto)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[FOE].conditions.values())
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="MANUAL")
    assert act(table, mid, "end")["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    shove = candidate(combat, mid, lambda c: c.display_name == "Shove: Push 5 ft" and tuple(c.target_ids) == (FOE,))
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    assert send(combat, table, mid, shove, auto=auto)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[FOE]) == 10
    assert any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[FOE].conditions.values()) == (reach == 10)
    removed = [e for e in engine.events if e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id") == "condition:typed.grappled"]
    assert bool(removed) == (reach == 5)
    if removed:
        assert removed[-1].payload["reason"] == "OUT_OF_REACH"


@pytest.mark.parametrize("auto", [False, True])
def test_nested_forced_movement_of_grappler_releases_target(tmp_path, monkeypatch, auto):
    from combat.typed_executor import Context, block_forced_movement
    from tests.hunt12_support import event_hook
    combat, table, mid = fight(tmp_path)
    grapple = candidate(combat, mid, lambda c: c.display_name == "Grapple" and tuple(c.target_ids) == (FOE,))
    assert send(combat, table, mid, grapple)["status"] == "COMMITTED"

    def force(engine, event_type, kwargs):
        if event_type != "HOLD_POSITION_COMMITTED" or kwargs.get("actor_id") != FOE:
            return
        source, target = engine.state.actors[FOE], engine.state.actors[ME]
        action = engine.action_catalog[grapple.source_definition_id]
        ctx = Context(engine, source, action, None, {}, [target], target)
        block_forced_movement(ctx, {"type": "forced_movement", "applies_to": "target", "direction": "away", "distance_ft": 5})

    event_hook(monkeypatch, force)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    chosen = candidate(combat, mid, lambda c: c.source_definition_id == "system:combat.hold_position")
    if auto:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    assert send(combat, table, mid, chosen, auto=auto)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[FOE]) == 10
    assert not any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize("auto", [False, True])
def test_native_drag_keeps_the_grapple_in_range(tmp_path, auto):
    combat, table, mid = fight(tmp_path)
    grapple = candidate(combat, mid, lambda c: c.display_name == "Grapple" and tuple(c.target_ids) == (FOE,))
    assert send(combat, table, mid, grapple)["status"] == "COMMITTED"
    move = candidate(combat, mid, lambda c: str(c.kind) == "MOVE" and c.destination.x == 2 and c.destination.y == 6)
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    assert send(combat, table, mid, move, auto=auto)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.x == 3
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[FOE]) == 5
    assert any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[FOE].conditions.values())
