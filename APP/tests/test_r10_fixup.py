"""R10 re-review: accepted casts, turn transitions and persisted table choices."""
import pytest

from combat.ext import radiance, shadow
from tests import test_riders_lane10 as lane


def road(extras=()):
    _, engine, owner, foe = lane._shadow(lane.S + "SHADOW_STEP", extras=(shadow.LONG_ROAD, *extras))
    friend = lane.SWF.ally(engine, owner)
    lane.SWF.cast(engine, "Second Silhouette: Shadow Anchor", at=(2, 6))
    owner.action_available = True
    lane.SWF.cast(engine, "Second Silhouette: Shadow Anchor", at=(12, 10))
    owner.action_available = True
    return engine, owner, friend


def test_long_road_actual_cast_obeys_first_dawn():
    engine, owner, friend = road((radiance.FIRST_DAWN,))
    from combat.footprints import ActorFootprintDefinition
    engine.actor_footprints[friend.entity_id] = ActorFootprintDefinition.rectangle(
        footprint_id="test:large", source_definition_id="test:large", width_cells=2, height_cells=2)
    lane.SWF.cast(engine, "First Dawn Before Falsehood")
    owner.action_available = True
    start, companion_start = owner.position, friend.position
    lane.SWF.cast(engine, "Long Road Between Lanterns", at=(12, 11))
    assert owner.position == start and friend.position == companion_start
    assert any("shadow road fails" in str(e.payload) for e in engine.events)


@pytest.mark.parametrize("sealed", [False, True])
def test_long_road_actual_cast_checks_large_companion_footprint_and_seal(sealed):
    engine, owner, friend = road()
    from combat.footprints import ActorFootprintDefinition
    engine.actor_footprints[friend.entity_id] = ActorFootprintDefinition.rectangle(
        footprint_id="test:large", source_definition_id="test:large", width_cells=2, height_cells=2)
    start = friend.position
    if sealed:
        engine._apply_condition(friend, "condition:typed.formation_spirit_locked", "test:seal", owner.entity_id,
                                expires_on="UNTIL_REMOVED")
    else:
        engine.grid.blocked.add((13, 10))
        engine._wall_base = (frozenset(engine.grid.blocked), frozenset(engine.grid.opaque),
                                   frozenset(engine.grid.cover), dict(engine.grid.base_movement_cost))
    lane.SWF.cast(engine, "Long Road Between Lanterns", at=(12, 11))
    assert owner.position.x == 12
    if sealed:
        assert friend.position == start
        assert not any("companion(s)" in str(e.payload.get("log", "")) for e in engine.events)
    else:
        if friend.position != start:
            assert engine.grid.placement_legal(friend.position, footprint=engine._footprint(friend),
                                               occupied_cells=engine._occupied_cells_except(friend.entity_id))


def test_generated_sovereign_step_actual_cast_obeys_first_dawn():
    _, engine, owner, foe = lane._shadow(shadow.STEP, extras=(shadow.SOVEREIGN, radiance.FIRST_DAWN))
    lane.SWF.cast(engine, "First Dawn Before Falsehood")
    engine._apply_condition(owner, shadow.SOVEREIGN_STATE, shadow.SOVEREIGN, owner.entity_id, expires_on="UNTIL_REMOVED")
    start = owner.position
    lane.SWF.cast(engine, "Shadow Step (Shadow-Sovereign", at=(5, 6))
    assert owner.position == start


def test_long_road_actual_cast_cannot_follow_a_sealed_road():
    from combat.ext import placed, seal
    engine, owner, friend = road()
    sealer = engine.state.actors[lane.FOE]
    placed.place(engine, sealer, source=seal.CUT, tag="seal", cells=[owner.position],
                 name="Sealed road", placed={"from": [3, 6], "to": [12, 11], "dc": 100})
    start = owner.position
    lane.SWF.cast(engine, "Long Road Between Lanterns", at=(12, 11))
    assert owner.position == start
    assert any(e.event_type == "CHECK_ROLLED" for e in engine.events)


@pytest.mark.parametrize("dawn", [False, True])
def test_two_shadows_actual_cast_respects_owner_gate_and_companion_seal(dawn):
    _, engine, owner, foe = lane._shadow(shadow.STEP, extras=(lane.S + "TWO_SHADOWS_CROSSING", radiance.FIRST_DAWN))
    friend = lane.SWF.ally(engine, owner)
    start, companion_start = owner.position, friend.position
    if dawn:
        lane.SWF.cast(engine, "First Dawn Before Falsehood")
    else:
        engine._apply_condition(friend, "condition:typed.formation_spirit_locked", "test:seal", owner.entity_id,
                                expires_on="UNTIL_REMOVED")
    lane.SWF.cast(engine, "Shadow Step + Two Shadows Crossing", at=(6, 6))
    assert (owner.position == start) == dawn
    assert friend.position == companion_start
    assert not any("crosses with" in str(e.payload.get("log", "")) for e in engine.events)
