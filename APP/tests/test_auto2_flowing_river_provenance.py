"""Player provenance through service intents, committed state and cold replay."""
import pytest

from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, act, turn, cell_send
from tests.test_auto2_flowing_river import P, reload, settle, decline_steps
from combat.ext.flowing_second_pass import RETALIATE


def prompt_text(prompts, choice):
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == choice)
    return prompt['moment']


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('talent', ['TEN_THOUSAND_EDGES_FIND_NO_CENTER', 'TURNING_GUARD', 'CURRENT_BETWEEN_STEPS'])
def test_melee_step_names_actual_attack_source_and_recipient(tmp_path, native, talent):
    def edit(b):
        for a in b['action_catalog']:
            if a['display_name'] == 'Cause':
                if native:
                    a.update(resolution_kind='ATTACK', range_ft=None, reach_ft=60,
                             attack_bonus=100 if talent.startswith('TEN_') else -100, damage=None)
                    a['parameters'] = {'attack_kind': 'weapon'}
                else:
                    a['parameters']['typed']['range_ft'] = None
                    a['parameters']['typed']['numbers']['attack_bonus'] = 100 if talent.startswith('TEN_') else -100
    c, t, m = fight(tmp_path, [P+talent], bundle_edit=edit,
                    cause=[{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}])
    if talent == 'CURRENT_BETWEEN_STEPS':
        settle(lambda a: act(t, m, 'Disengage', a))
        settle(cell_send(t, m, 'Move', (2, 6)))
    else:
        settle(lambda a: act(t, m, 'Dodge', a))
    reload(c, m)
    turn(t, m, RIGHT)
    _, prompts = settle(lambda a: act(t, m, 'Cause', a, target_id=LEFT), decline_steps)
    reload(c, m)
    text = prompt_text(prompts, 'choice:needle.river_step')
    assert "Visitor missed Keeper with Cause (a melee attack)." in text


@pytest.mark.parametrize('reaction', [False, True])
@pytest.mark.parametrize('success', [False, True])
def test_paid_save_names_actual_effect_source_and_recipient(tmp_path, reaction, success):
    save = {'type': 'save', 'ability': 'dex',
            'on_fail': [{'type': 'damage', 'flat': 20, 'damage_types': ['fire']}],
            'on_success': [{'type': 'damage', 'flat': 10, 'damage_types': ['fire']}]}
    def edit(b):
        if reaction and b['actor_template']['entity_id'] == RIGHT:
            b['typed_reactions'].append({'feature_id': 'reaction:test.visible_flame', 'name': 'Visible Flame',
                'block': 'generic', 'kind': 'missed', 'range_ft': 60,
                'numbers': {'save_dc': 1 if success else 100, 'pb': 4}, 'effects': [save]})
        for a in b['action_catalog']:
            if a['display_name'] == 'Prepare':
                a['parameters']['typed']['range_ft'] = None
    c, t, m = fight(tmp_path, [P+'EMPTY_BANK_EVASION'], left_score=50 if success else 14,
        bundle_edit=edit, cause_save_dc=1 if success else 100,
        prepare=[{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}] if reaction else (),
        prepare_attack_bonus=-100, cause=() if reaction else [save])
    if not reaction:
        turn(t, m, RIGHT)
    reload(c, m)
    _, prompts = settle(lambda a: act(t, m, 'Prepare' if reaction else 'Cause', a,
                                     target_id=RIGHT if reaction else LEFT))
    reload(c, m)
    text = prompt_text(prompts, 'choice:needle.river_bank')
    action = 'Visible Flame' if reaction else 'Cause'
    assert f"Keeper's Dexterity save against Visitor's {action}" in text
    if reaction:
        assert 'Prepare' not in text


def test_two_protected_characters_have_distinct_pills(tmp_path):
    def edit(b):
        aid = b['actor_template']['entity_id']
        b['actor_template']['initiative_bonus'] = {LEFT: 100, ALLY: 0, RIGHT: -100}[aid]
        if aid == ALLY:
            b['actor_template']['display_name'] = 'Guarding Friend'
            b['typed_passives'].append({'feature_id': P+'CURRENT_BETWEEN_STEPS', 'block': 'river_second_pass',
                                       'kind': 'between_steps', 'numbers': {'pb': 4}})
    c, t, m = fight(tmp_path, [P+'CURRENT_BETWEEN_STEPS'], ally=(), bundle_edit=edit)
    settle(lambda a: act(t, m, 'Disengage', a)); settle(cell_send(t, m, 'Move', (2, 6)))
    reload(c, m)
    turn(t, m, ALLY)
    settle(lambda a: act(t, m, 'Disengage', a)); settle(cell_send(t, m, 'Move', (2, 5)))
    e = reload(c, m)
    labels = {x.data['target']: x.data['label'] for x in e.state.actors[RIGHT].conditions.values()
              if x.condition_id == RETALIATE}
    assert labels == {LEFT: 'Current Between Steps: next melee attack against Keeper has Disadvantage',
                      ALLY: 'Current Between Steps: next melee attack against Guarding Friend has Disadvantage'}


def test_reaction_attack_step_names_reaction_instead_of_outer_intent(tmp_path):
    def edit(b):
        if b['actor_template']['entity_id'] == RIGHT:
            b['typed_reactions'].append({'feature_id': 'reaction:test.counter', 'name': 'Visible Counter',
                'block': 'generic', 'kind': 'missed', 'range_ft': 60,
                'numbers': {'attack_bonus': -100, 'pb': 4},
                'effects': [{'type': 'attack', 'attack_kind': 'melee',
                             'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning']}]}]})
        for a in b['action_catalog']:
            if a['display_name'] == 'Prepare':
                a['parameters']['typed']['range_ft'] = None
    c, t, m = fight(tmp_path, [P+'TURNING_GUARD'], bundle_edit=edit,
        prepare=[{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}], prepare_attack_bonus=-100)
    settle(lambda a: act(t, m, 'Dodge', a)); reload(c, m)
    _, prompts = settle(lambda a: act(t, m, 'Prepare', a), decline_steps)
    reload(c, m)
    text = prompt_text(prompts, 'choice:needle.river_step')
    assert 'Visitor missed Keeper with Visible Counter (a melee attack).' in text
    assert 'Prepare' not in text
