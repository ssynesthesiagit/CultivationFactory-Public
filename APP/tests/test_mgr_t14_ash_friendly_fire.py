"""Ash's friendly-damage exclusion remains reachable under current area rules."""
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, turn, reload
from tests.test_a2_foundations3 import pool
from tests.test_mgr_t14_ash_parent import OLD_FACT_PROMPT, native_fixture


def test_native_fixture_retains_generation_ownership_after_reload(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    engine = reload(tmp_path, mid)
    assert any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
               for row in engine.typed_passive_rows[OWNER])
    assert engine.state.actors[OWNER].resources[pool('ash')] == 0
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
                   and e.payload.get('resource_id') == pool('ash') for e in engine.events)


def test_native_friendly_fire_is_excluded_without_scene_prompt(tmp_path):
    # Keep the original parent regression in the parent file as well. Running
    # this small file makes the integration failure independently verifiable.
    from tests.test_mgr_t14_ash_parent import test_native_friendly_fire_is_excluded_without_scene_prompt as check
    check(tmp_path)


def test_allied_fireball_damage_generates_ash_without_scene_prompt(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    turn(table, mid, ALLY)
    row = candidate(combat, mid, 'Fireball Art', at=(3,6))
    prompts = settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    # Bible: PLAYERS_HANDBOOK Areas, Targeting & Friendly Fire
    assert engine.state.actors[OWNER].current_hp < engine.state.actors[OWNER].maximum_hp
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == row.source_definition_id
               and e.actor_id == ALLY and OWNER in e.target_ids and e.payload['hp_damage'] > 0
               for e in engine.events)
    # Generate Funeral Ash: survive fire damage while below maximum HP.
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1
    assert not any(p['context']['reaction_source_id'].startswith(OLD_FACT_PROMPT) for p in prompts)


def test_hostile_furnace_damage_remains_a_qualifying_ash_trigger(tmp_path):
    combat, table, mid = native_fixture(tmp_path, foe_talents=['TAL_ALCHEMY_FURNACE_VENT'],
        foe_dc=100,
        positions={OWNER: {'x':3,'y':6}, ALLY: {'x':4,'y':6}, FOE: {'x':6,'y':6}})
    turn(table, mid, FOE)
    row = candidate(combat, mid, 'Furnace Vent', at=(3,6))
    prompts = settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    damage = next(e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                  and e.source_definition_id == row.source_definition_id and OWNER in e.target_ids)
    assert damage.actor_id == FOE and damage.payload['hp_damage'] > 0
    assert damage.payload['damage_type'] in ('POISON', 'FIRE'), damage.payload
    assert engine.state.actors[OWNER].current_hp < engine.state.actors[OWNER].maximum_hp
    assert engine.state.actors[OWNER].resources[pool('ash')] == 1, {'damage': damage.payload,
        'prompts': [(p['context'], p.get('choice')) for p in prompts]}
    gain = next(e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
                and e.payload.get('resource_id') == pool('ash'))
    assert damage.sequence < gain.sequence
    assert not any(p['context']['reaction_source_id'].startswith(OLD_FACT_PROMPT) for p in prompts)
