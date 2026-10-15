"""Ash's friendly-damage exclusion remains reachable under current area rules."""
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, turn, reload
from tests.test_a2_foundations3 import pool
from tests.test_mgr_t14_ash_parent import native_fixture
from combat.ext.foundation_context import CONTEXT


def test_native_friendly_fire_is_excluded_without_scene_prompt(tmp_path):
    # Keep the original parent regression in the parent file as well. Running
    # this small file makes the integration failure independently verifiable.
    from tests.test_mgr_t14_ash_parent import test_native_friendly_fire_is_excluded_without_scene_prompt as check
    check(tmp_path)


def test_generic_fireball_spares_ally_without_ash_context(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    turn(table, mid, ALLY)
    row = candidate(combat, mid, 'Fireball Art', at=(3,6))
    prompts = settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == engine.state.actors[OWNER].maximum_hp
    assert not any(e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids for e in engine.events)
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0
    assert not any(p['context']['reaction_source_id'].startswith(CONTEXT) for p in prompts)


def test_hostile_furnace_damage_remains_a_qualifying_ash_trigger(tmp_path):
    combat, table, mid = native_fixture(tmp_path, foe_talents=['TAL_ALCHEMY_FURNACE_VENT'],
        positions={OWNER: {'x':3,'y':6}, ALLY: {'x':4,'y':6}, FOE: {'x':6,'y':6}})
    turn(table, mid, FOE)
    row = candidate(combat, mid, 'Furnace Vent', at=(3,6))
    prompts = settle(table, mid, row.candidate_id, choices={CONTEXT: 'real'})
    engine = reload(tmp_path, mid)
    damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                  and e.source_definition_id == row.source_definition_id and OWNER in e.target_ids)
    assert damage.actor_id == FOE and damage.payload['hp_damage'] > 0
    assert engine.state.actors[OWNER].current_hp < engine.state.actors[OWNER].maximum_hp
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    gain = next(e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
                and e.payload.get('resource_id') == pool('ash'))
    assert damage.sequence < gain.sequence
    assert any(p['context']['reaction_source_id'] == CONTEXT for p in prompts)
