"""Review r4 regressions through service intents, commit and cold replay."""
import pytest

from combat.factory_compiler import _reaction_plan
from tests.h1_support import mechanics
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, turn
from tests.test_auto2_flowing_river import P, RESPONSE, reload, settle, decline_steps
from tests.test_auto2_flowing_river_provenance import prompt_text

GUARD = 'tianxia.path.body_refining.feature.stamina_guard'


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('mode', ['auto', 'order'])
@pytest.mark.parametrize('guard_ready', [False, True])
def test_response_respects_competing_guard_priority(tmp_path, native, mode, guard_ready):
    def edit(b):
        if b['actor_template']['entity_id'] == LEFT:
            # Compile the owner's automatic plan before sealing the bundle;
            # no running engine or saved-session row is changed.
            rows = [{k: v for k, v in r.items() if k != 'ask'} for r in b['typed_reactions']]
            b['typed_reactions'], b['reaction_plan'] = _reaction_plan(
                rows, {'order': [GUARD, RESPONSE]} if mode == 'order' else {}, mechanics())
            guard = next(r for r in b['typed_reactions'] if r['feature_id'] == GUARD)
            if not guard_ready:
                next(r for r in b['actor_template']['resources'] if r['resource_id'] == guard['resource_id'])['initial'] = 0
        for a in b['action_catalog']:
            if a['display_name'] == 'Cause':
                if native:
                    a.update(resolution_kind='ATTACK', range_ft=None, reach_ft=5,
                             attack_bonus=100, damage={'count': 1, 'sides': 2, 'modifier': 19},
                             damage_type='BLUDGEONING')
                    a['parameters'] = {'attack_kind': 'weapon'}
                else:
                    a['parameters']['typed']['range_ft'] = None
                    a['parameters']['typed']['numbers']['attack_bonus'] = 100
    c, t, m = fight(tmp_path, [RESPONSE, GUARD], left_resource='Stamina', bundle_edit=edit,
        cause=[{'type': 'attack', 'attack_kind': 'melee',
                'on_hit': [{'type': 'damage', 'flat': 20, 'damage_types': ['bludgeoning']}]}])
    turn(t, m, RIGHT)
    before = reload(c, m).state.actors[LEFT]
    _, prompts = settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), decline_steps)
    e = reload(c, m)
    used_response = any(x.event_type == 'REACTION_WINDOW_OPENED' and x.source_definition_id == RESPONSE for x in e.events)
    used_guard = any(x.event_type == 'REACTION_WINDOW_OPENED' and x.source_definition_id == GUARD for x in e.events)
    assert used_response is not guard_ready
    assert used_guard is guard_ready
    after = e.state.actors[LEFT]
    assert not after.reaction_available
    assert not prompts  # Auto/My order do not ask the player to arbitrate.
    assert not any(v.source_definition_id.startswith('flowing_response:') for v in after.modifiers.values())
    damage = next(x.payload for x in reversed(e.events) if x.event_type == 'DAMAGE_COMMITTED' and LEFT in x.target_ids)
    assert before.current_hp - after.current_hp == damage['hp_damage']
    assert damage['rolled_or_pending_damage'] >= 20
    if guard_ready:
        assert damage['reduced_to'] < damage['rolled_or_pending_damage']
        row = next(r for r in e.typed_reaction_rows[LEFT] if r['feature_id'] == GUARD)
        assert after.resources[row['resource_id']] < before.resources[row['resource_id']]
    else:
        assert damage['reduced_to'] == damage['rolled_or_pending_damage']


@pytest.mark.parametrize('origin', ['typed', 'native', 'reaction'])
def test_response_step_names_resolving_attack(tmp_path, origin):
    def edit(b):
        if origin == 'reaction' and b['actor_template']['entity_id'] == RIGHT:
            b['typed_reactions'].append({'feature_id': 'reaction:test.counter', 'name': 'Visible Counter',
                'block': 'generic', 'kind': 'missed', 'range_ft': 60,
                'numbers': {'attack_bonus': -100, 'pb': 4},
                'effects': [{'type': 'attack', 'attack_kind': 'melee',
                             'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning']}]}]})
        for a in b['action_catalog']:
            if a['display_name'] == ('Prepare' if origin == 'reaction' else 'Cause'):
                if origin == 'native':
                    a.update(resolution_kind='ATTACK', range_ft=None, reach_ft=5,
                             attack_bonus=-100, damage=None)
                    a['parameters'] = {'attack_kind': 'weapon'}
                else:
                    a['parameters']['typed']['range_ft'] = None
                    a['parameters']['typed']['numbers']['attack_bonus'] = -100
    attack = [{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}]
    c, t, m = fight(tmp_path, [RESPONSE], bundle_edit=edit,
        prepare=attack if origin == 'reaction' else (), cause=() if origin == 'reaction' else attack,
        prepare_attack_bonus=-100)
    settle(lambda a: act(t, m, 'Flowing Response: step away', a))
    if origin != 'reaction':
        turn(t, m, RIGHT)
    reload(c, m)
    _, prompts = settle(lambda a: act(t, m, 'Prepare' if origin == 'reaction' else 'Cause', a,
                                     target_id=RIGHT if origin == 'reaction' else LEFT), decline_steps)
    reload(c, m)
    text = prompt_text(prompts, 'choice:needle.river_step')
    name = 'Visible Counter' if origin == 'reaction' else 'Cause'
    assert f'Flowing Response: Visitor missed Keeper with {name} (a melee attack).' in text
    if origin == 'reaction':
        assert 'Prepare' not in text
