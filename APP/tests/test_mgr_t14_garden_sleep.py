"""Native Dream Sleep excludes Garden generation, including after cold replay."""
from types import SimpleNamespace

import pytest

from combat.ext.dreams_core import SLEEP, SLEEP_RULE
from combat.ext.foundation_context import CONTEXT, conscious, helpless_before
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, reload
from tests.test_mgr_t14_garden_actions import native_garden, cast, turn_unknown
from tests.test_mgr_t14_garden_sum import GARDEN_NAME

GENERATE = 'choice:needle.ash_garden.generate'


@pytest.mark.parametrize('name,awake,helpless', [
    ('dream_sleep', False, True), ('unconscious', False, True),
    ('life_unconscious', False, True), ('stunned', True, False),
    ('paralyzed', True, True), ('drowsy', True, False),
])
def test_foundation_condition_queries_distinguish_unconsciousness(name, awake, helpless):
    cid = 'condition:typed.' + name
    actor = SimpleNamespace(active=True, current_hp=10, life_state='ALIVE',
                            conditions={'native': SimpleNamespace(condition_id=cid)})
    receipt = SimpleNamespace(payload={'hp_before': 10, 'target_active_before': 1,
                                      'target_conditions_before': [cid]})
    assert conscious(actor) is awake
    assert helpless_before(receipt) is helpless


def sleep_and_finish_actions(bundles):
    """Accepted typed setup uses the actual Dreams condition and its native rule.

    No fake asleep flag or separate unconscious condition: the wake-on-damage
    hook must remove Dream Sleep while the damage receipt retains its old id.
    """
    for name, effects in (
        ('Fixture Dream Sleep', [
            {'type': 'condition', 'condition': 'dream_sleep', 'applies_to': 'target',
             'condition_data': {'rule': SLEEP_RULE}, 'duration': {'kind': 'one_minute'}},
            {'type': 'condition', 'condition': 'prone', 'applies_to': 'target',
             'duration': {'kind': 'until_removed'}},
        ]),
        ('Fixture finishing blow', [
            {'type': 'damage', 'flat': 999, 'damage_types': ['slashing'], 'applies_to': 'target'},
        ]),
    ):
        action = ActionDefinition(source_definition_id='action:test.garden.' + name.replace(' ', '_'),
            display_name=name, owner_id=ALLY, economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='ANY_CREATURE', range_ft=60,
            parameters={'free_primary': True, 'typed': {'source': 'test:garden_sleep',
                'effects': effects, 'numbers': {}, 'duration': {'kind': 'one_minute'}, 'riders': []}})
        bundles[1]['action_catalog'].append(action.model_dump(mode='json'))
        bundles[1]['actor_template']['action_ids'].append(action.source_definition_id)


@pytest.mark.parametrize('sleeper', [OWNER, FOE], ids=['sleeping-owner', 'sleeping-target'])
def test_native_dream_sleep_blocks_garden_zero_hp_generation_after_reload(tmp_path, sleeper):
    combat, table, mid = native_garden(tmp_path, hp=1, extra_foes=1,
        bundle_transform=sleep_and_finish_actions, seed='GARDEN-NATIVE-SLEEP')
    cast(combat, table, mid, GARDEN_NAME)
    turn_unknown(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Fixture Dream Sleep', target=sleeper).candidate_id)
    before = reload(tmp_path, mid)
    actor = before.state.actors[sleeper]
    assert actor.active and actor.current_hp > 0
    assert any(c.condition_id == SLEEP for c in actor.conditions.values())
    assert not any(c.condition_id.endswith('.unconscious') for c in actor.conditions.values())
    first = before.state.event_sequence

    prompts = settle(table, mid, candidate(combat, mid, 'Fixture finishing blow', target=FOE).candidate_id,
                     choices={CONTEXT: 'real', GENERATE: 'generate'})
    engine = reload(tmp_path, mid)
    drop, = [e for e in engine.events if e.sequence > first and e.event_type == 'DAMAGE_COMMITTED'
             and e.actor_id == ALLY and e.target_ids == (FOE,) and e.payload.get('remaining_hp') == 0]
    assert drop.payload['hp_before'] > 0
    assert OWNER in drop.payload['ash_garden_owners_before']
    if sleeper == FOE:
        assert SLEEP in drop.payload['target_conditions_before']
        assert not any(c.condition_id == SLEEP for c in engine.state.actors[FOE].conditions.values())
    else:
        assert engine.state.actors[OWNER].active and engine.state.actors[OWNER].current_hp > 0
        assert any(c.condition_id == SLEEP for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0
    assert not any(p['context']['reactor_id'] == OWNER
                   and p['context']['reaction_source_id'] in (CONTEXT, CONTEXT + '.detail', GENERATE)
                   for p in prompts)
    assert not any(e.sequence > first and e.event_type == 'RESOURCE_GAINED'
                   and e.actor_id == OWNER
                   and e.payload.get('resource_id') == 'resource:foundation.funeral_ash' for e in engine.events)
