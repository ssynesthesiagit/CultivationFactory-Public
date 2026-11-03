"""Unreliable Witness offered inside a real Study transaction."""
import pytest
from combat.ext import figment, placed
from combat.ext.illusion_second_pass import WITNESS
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, turn, resolve
from tests.test_auto41_illusion import cell_action, answer


@pytest.mark.parametrize('ai,resists,decline,allied', [
    (False,False,False,False), (False,True,False,False),
    (False,False,True,False), (True,False,False,False), (True,False,False,True)])
def test_unreliable_witness_successful_study(tmp_path, ai, resists, decline, allied):
    def edit(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['saving_throws']['WIS'] = 200 if resists else -200
            bundle['actor_template'].setdefault('skills', {})['Investigation'] = 200
            bundle.setdefault('skills', {})['Investigation'] = 200
    combat, table, mid = fight(tmp_path, [WITNESS, figment.MINOR], spheres=[figment.SPHERE],
        left_save_dc=1, bundle_edit=edit, right_team='team:factory' if allied else 'team:opponents')
    resolve(lambda answers: cell_action(table, mid, 'Minor Illusion', (4,6), answers))
    turn(table, mid, RIGHT)
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    zone, = placed.of(reload(combat, mid), 'figment')
    answers = []
    sources = []
    for _ in range(8):
        result = act(table, mid, 'Study an illusion', answers)
        if result['status'] != 'REACTION_REQUIRED':
            break
        prompt = result['reaction']; source = prompt['context']['reaction_source_id']; sources.append(source)
        if prompt.get('choice'):
            answers.append(answer(result, [zone.zone_id]))
        else:
            answers.append({**prompt['context'], 'selection':'DECLINE' if decline else 'USE', 'option_ids':[]})
    assert result['status']=='COMMITTED', result
    engine = reload(combat, mid)
    used = not decline and not allied
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == (98 if used else 100)
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'False Premise') == (used and not resists)
    changes = [e for e in engine.events if e.event_type=='D20_REWRITTEN' and e.source_definition_id==WITNESS]
    assert bool(changes) == used
    if used:
        payload=changes[-1].payload
        old=payload['original']; new=payload['result']
        assert new['total'] <= old['total']
        if resists:
            assert new['total'] == old['total']
        assert not engine.state.actors[LEFT].reaction_available
        assert any(e.event_type=='SAVE_ROLLED' and e.source_definition_id==WITNESS for e in engine.events)
    assert not engine.state.actors[RIGHT].action_available


def test_unreliable_witness_uses_stored_save_bonus_and_expires_on_owner_turn(tmp_path):
    """The follow-up Wisdom save reads an already committed save bonus, then its mark expires at the owner's next turn."""
    bonus = {'type': 'save_bonus', 'flat': 500, 'applies_to': 'self', 'against': ['false_premise'], 'duration': 'until_removed'}
    def edit(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['saving_throws']['WIS'] = -200
            bundle['actor_template'].setdefault('skills', {})['Investigation'] = 200
            bundle.setdefault('skills', {})['Investigation'] = 200
    combat, table, mid = fight(tmp_path, [WITNESS, figment.MINOR], spheres=[figment.SPHERE],
        cause=[bonus], cause_target='SELF', left_save_dc=100,
        bundle_edit=edit)
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    assert any(c.condition_id == 'condition:typed.save_bonus' for c in reload(combat, mid).state.actors[RIGHT].conditions.values())
    turn(table, mid, LEFT)
    resolve(lambda answers: cell_action(table, mid, 'Minor Illusion', (4, 6), answers))
    turn(table, mid, RIGHT)
    zone, = placed.of(reload(combat, mid), 'figment')
    result = act(table, mid, 'Study an illusion')
    answers = []
    while result['status'] == 'REACTION_REQUIRED':
        prompt = result['reaction']
        answers.append(answer(result, [zone.zone_id]) if prompt.get('choice') else
                       {**prompt['context'], 'selection': 'USE', 'option_ids': []})
        result = act(table, mid, 'Study an illusion', answers)
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid)
    assert not bears_mark(engine.state.actors[RIGHT], LEFT, 'False Premise')
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 98
    assert any(e.event_type == 'D20_REWRITTEN' and e.source_definition_id == WITNESS for e in engine.events)


@pytest.mark.parametrize('mode', ['ADVANTAGE', 'DISADVANTAGE'])
def test_unreliable_witness_applies_and_consumes_only_matching_stored_save_mode(tmp_path, mode):
    """Witness's native follow-up save shares the typed next-save mode reader."""
    row_type = mode.lower()
    effects = [
        {'type': row_type, 'applies_to': 'self', 'on': 'the next Wisdom saving throw', 'duration': 'until_removed'},
        {'type': 'advantage', 'applies_to': 'self', 'on': 'the next Dexterity saving throw', 'duration': 'until_removed'},
    ]
    def edit(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['saving_throws']['WIS'] = -200
            bundle['actor_template'].setdefault('skills', {})['Investigation'] = 200
            bundle.setdefault('skills', {})['Investigation'] = 200
    combat, table, mid = fight(tmp_path, [WITNESS, figment.MINOR], spheres=[figment.SPHERE],
        cause=effects, cause_target='SELF', left_save_dc=100, bundle_edit=edit)
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    before = reload(combat, mid).state.actors[RIGHT]
    held = [c for c in before.conditions.values() if c.condition_id == 'condition:typed.save_against']
    assert len(held) == 2
    turn(table, mid, LEFT)
    resolve(lambda answers: cell_action(table, mid, 'Minor Illusion', (4, 6), answers))
    turn(table, mid, RIGHT)
    zone, = placed.of(reload(combat, mid), 'figment')
    result = act(table, mid, 'Study an illusion')
    answers = []
    while result['status'] == 'REACTION_REQUIRED':
        prompt = result['reaction']
        answers.append(answer(result, [zone.zone_id]) if prompt.get('choice') else
                       {**prompt['context'], 'selection': 'USE', 'option_ids': []})
        result = act(table, mid, 'Study an illusion', answers)
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid)
    save, = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == WITNESS]
    assert save.payload['mode'] == mode
    remaining = [c for c in engine.state.actors[RIGHT].conditions.values()
                 if c.condition_id == 'condition:typed.save_against']
    assert len(remaining) == 1
    assert remaining[0].data['rule']['save_against']['abilities'] == ['DEX']


@pytest.mark.parametrize('stored_modes', [['DISADVANTAGE'], ['ADVANTAGE', 'DISADVANTAGE']])
def test_native_save_cancels_stored_modes_with_an_independent_mode_through_reload(tmp_path, monkeypatch, stored_modes):
    """Native save bridge retains each stored mode until engine cancellation."""
    import copy
    from combat import typed_executor

    # This ordinary condition contribution is separate from the one-use
    # save_against statuses read by the native bridge.
    rules = copy.deepcopy(typed_executor.rules())
    rules['conditions']['test_native_wisdom_advantage'] = {'save_mode': {'WIS': 'ADVANTAGE'}}
    monkeypatch.setattr(typed_executor, 'rules', lambda: rules)
    effects = [
        {'type': mode.lower(), 'applies_to': 'self', 'on': 'the next Wisdom saving throw', 'duration': 'until_removed'}
        for mode in stored_modes
    ]
    effects.append({'type': 'condition', 'condition': 'test_native_wisdom_advantage',
                    'applies_to': 'self', 'duration': 'until_removed'})

    def edit(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['saving_throws']['WIS'] = -200
            bundle['actor_template'].setdefault('skills', {})['Investigation'] = 200
            bundle.setdefault('skills', {})['Investigation'] = 200

    combat, table, mid = fight(tmp_path, [WITNESS, figment.MINOR], spheres=[figment.SPHERE],
        cause=effects, cause_target='SELF', left_save_dc=100, bundle_edit=edit)
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    assert len([c for c in reload(combat, mid).state.actors[RIGHT].conditions.values()
                if c.condition_id == 'condition:typed.save_against']) == len(stored_modes)
    turn(table, mid, LEFT)
    resolve(lambda answers: cell_action(table, mid, 'Minor Illusion', (4, 6), answers))
    turn(table, mid, RIGHT)
    zone, = placed.of(reload(combat, mid), 'figment')
    result = act(table, mid, 'Study an illusion')
    answers = []
    while result['status'] == 'REACTION_REQUIRED':
        prompt = result['reaction']
        answers.append(answer(result, [zone.zone_id]) if prompt.get('choice') else
                       {**prompt['context'], 'selection': 'USE', 'option_ids': []})
        result = act(table, mid, 'Study an illusion', answers)
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid)
    save, = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == WITNESS]
    assert save.payload['mode'] == 'NORMAL', save.payload
    assert not any(c.condition_id == 'condition:typed.save_against'
                   for c in engine.state.actors[RIGHT].conditions.values())
    assert any(c.condition_id == 'condition:typed.test_native_wisdom_advantage'
               for c in engine.state.actors[RIGHT].conditions.values())


def test_unreliable_witness_false_premise_expires_at_owner_next_turn(tmp_path):
    def edit(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template']['saving_throws']['WIS'] = -200
            bundle['actor_template'].setdefault('skills', {})['Investigation'] = 200
            bundle.setdefault('skills', {})['Investigation'] = 200
    combat, table, mid = fight(tmp_path, [WITNESS, figment.MINOR], spheres=[figment.SPHERE], bundle_edit=edit)
    resolve(lambda answers: cell_action(table, mid, 'Minor Illusion', (4, 6), answers))
    turn(table, mid, RIGHT)
    zone, = placed.of(reload(combat, mid), 'figment')
    result = act(table, mid, 'Study an illusion')
    answers = []
    while result['status'] == 'REACTION_REQUIRED':
        prompt = result['reaction']
        answers.append(answer(result, [zone.zone_id]) if prompt.get('choice') else
                       {**prompt['context'], 'selection': 'USE', 'option_ids': []})
        result = act(table, mid, 'Study an illusion', answers)
    assert result['status'] == 'COMMITTED', result
    assert bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'False Premise')
    turn(table, mid, LEFT)
    assert not bears_mark(reload(combat, mid).state.actors[RIGHT], LEFT, 'False Premise')
