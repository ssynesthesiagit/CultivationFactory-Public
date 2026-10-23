"""Conditional paid riders qualify before consent/payment in persisted Tables."""
import copy

import pytest

from combat.ext.attack_modifiers import chosen
from combat.typed_executor import bears_mark
from tests.hunt36_support import LEFT, RIGHT, act, fight, reload, send, turn
from tests.test_solfsol117_review import hits, choose

SEAL = 'tianxia.talent.radiance.daybreak_seal'
PURIFY = 'tianxia.talent.radiance.purifying_radiance'


@pytest.mark.parametrize('marked', [False, True])
@pytest.mark.parametrize('ask', [False, True])
def test_daybreak_purification_qualifies_before_payment_table_reload(tmp_path, monkeypatch, hits, marked, ask):
    from tests import hunt36_support
    original_sheet = hunt36_support.sheet
    def unclean_sheet(*args, **kwargs):
        document = original_sheet(*args, **kwargs)
        document['identity']['creature_type'] = 'Undead'
        return document
    monkeypatch.setattr(hunt36_support, 'sheet', unclean_sheet)
    original_compile = hunt36_support.compile_character
    def with_mark_setup(*args, **kwargs):
        bundle = original_compile(*args, **kwargs)
        if kwargs['actor_id'] == LEFT:
            # The current compiler emits Burning Purification via compile_actions,
            # after modifier capture. Reproduce the reviewed sealed loadout route
            # using shipped attack effects and shipped captured Daybreak rows;
            # no authority file or production compiler behavior is changed.
            from combat.ext.attack_modifiers import settings
            from combat.gate2_runtime_models import ActionDefinition
            burning = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Burning Purification')
            strike = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Radiance Strike')
            burning['parameters']['typed']['attack_modifier_loadout'] = copy.deepcopy(
                strike['parameters']['typed']['attack_modifier_loadout'])
            additions = settings([ActionDefinition.model_validate(burning)])[1:]
            bundle['action_catalog'].extend(a.model_dump(mode='json') for a in additions)
            bundle['actor_template']['action_ids'].extend(a.source_definition_id for a in additions)
            action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED'))
            action.update(source_definition_id='action:test.r6.mark', display_name='Test Dawnmark',
                          economy='NONE', target_kind='HOSTILE_ENTITY', costs=[], range_ft=60)
            action['parameters'] = {'typed': {'effects': [{'type': 'mark', 'mark': 'Dawnmark',
                'applies_to': 'target', 'duration': {'kind': 'until_removed'}}], 'numbers': {}, 'riders': []}}
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        return bundle
    monkeypatch.setattr(hunt36_support, 'compile_character', with_mark_setup)
    combat, table, mid = fight(tmp_path, [SEAL, PURIFY], cl=5, seed=f'SOLFSOL117R6-{marked}-{ask}')
    turn(combat, table, mid)
    engine = reload(combat, mid)
    parent = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and a.display_name == 'Burning Purification')
    choose(combat, table, mid, parent, SEAL, 'on', 'toggle')
    choose(combat, table, mid, parent, SEAL, 'payment', '0')
    if not ask:
        choose(combat, table, mid, parent, SEAL, 'option', '0')
    if marked:
        act(combat, table, mid, 'Test Dawnmark')
    engine = reload(combat, mid)
    preferences = chosen(engine.state.actors[LEFT], parent, SEAL)
    assert preferences['on'] == 1 and preferences['payment'] == '0'
    assert preferences['option'] == ('ask' if ask else '0')
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Dawnmark') == marked
    before_hp = engine.state.actors[RIGHT].current_hp
    before_cp = engine.state.actors[LEFT].resources['resource:core.qi']
    sequence = engine.state.event_sequence
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == parent
                     and c.target_ids == (RIGHT,))
    prompts = send(combat, table, mid, candidate.candidate_id)
    engine = reload(combat, mid)  # fresh service, recorded events + mechanical replay
    events = [e for e in engine.events if e.sequence > sequence]
    assert len([e for e in events if e.event_type == 'ATTACK_ROLLED']) == 1
    assert engine.state.actors[RIGHT].current_hp < before_hp
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'Dawnmark') == marked
    spent = [e for e in events if e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == SEAL]
    saves = [e for e in events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == SEAL]
    rider_prompts = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.attack_modifier']
    assert bool(rider_prompts) == (marked and ask)
    assert len(spent) == len(saves) == int(marked)
    assert before_cp - engine.state.actors[LEFT].resources['resource:core.qi'] == 3 + 2 * int(marked)
    for prompt in rider_prompts:
        assert all(name in prompt['moment'] for name in ('Daybreak Seal', 'Burning Purification', 'Visiting Fighter'))
    assert chosen(engine.state.actors[LEFT], parent, SEAL) == preferences
    assert bool([c for c in engine.state.actors[RIGHT].conditions.values()
                 if c.source_definition_id == SEAL]) == marked
