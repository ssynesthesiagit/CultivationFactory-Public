"""Cross-caster isolation for rider lane 1's timed effects."""
from combat.ext import states, rider_damage_states
from combat.ext.owned_effects import remove_conditions
from tests.test_riders_lane1 import _rider_engine, LASH, ME, AN, F1


def test_incapacitation_preserves_second_casters_same_court_benefits():
    engine = _rider_engine(LASH)
    owner, other, holder = (engine.state.actors[k] for k in (ME, F1, AN))
    source = "test:shared_court"
    engine._apply_condition(owner, states.PREFIX + "court", source, ME,
                            expires_on="UNTIL_REMOVED", data={"ends_if_incapacitated": True})
    for caster in (owner, other):
        engine._apply_condition(holder, "condition:typed.court_benefit", source, caster.entity_id,
                                expires_on="UNTIL_REMOVED")
        engine.state.current_actor_id = caster.entity_id
        engine._add_modifier(holder, source, "armor_class", "ADD", 2, "SELF", expires_on="UNTIL_REMOVED")
    engine._apply_condition(owner, "condition:typed.incapacitated", "test:disable", ME, expires_on="UNTIL_REMOVED")
    assert [c.source_actor_id for c in holder.conditions.values() if c.source_definition_id == source] == [F1]
    assert [m.source_actor_id for m in holder.modifiers.values() if m.source_definition_id == source] == [F1]
    assert any(e.event_type == "CONDITION_REMOVED" and e.payload.get("reason") == "INCAPACITATED" for e in engine.events)


def test_owned_replacement_keeps_other_source_and_owner_instances():
    engine = _rider_engine(LASH)
    holder = engine.state.actors[AN]
    for source, owner in [("test:a", ME), ("test:a", F1), ("test:b", ME)]:
        engine._apply_condition(holder, "condition:typed.link.lightning", source, owner, expires_on="UNTIL_REMOVED")
    remove_conditions(engine, holder, "test:a", ME, "condition:typed.link.lightning")
    assert {(c.source_definition_id, c.source_actor_id) for c in holder.conditions.values()} == {("test:a", F1), ("test:b", ME)}


def test_unrelated_hit_does_not_create_rider_snapshot():
    engine = _rider_engine(LASH)
    rider_damage_states.hit_states(engine, engine.state.actors[ME], engine.state.actors[AN], None, 20, 20, 10)
    assert "_rider_hit_states" not in engine.__dict__


def test_unrelated_hit_clears_a_cancelled_hits_expired_snapshot():
    engine = _rider_engine(LASH)
    engine._rider_hit_states = {(ME, AN): (["expired"], []), (ME, F1): (["other"], [])}
    rider_damage_states.hit_states(engine, engine.state.actors[ME], engine.state.actors[AN], None, 20, 20, 10)
    assert (ME, AN) not in engine._rider_hit_states
    assert (ME, F1) in engine._rider_hit_states
