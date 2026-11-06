"""Additional Ground/Descent service-level cases with ordinary saved afflictions."""
import copy

import pytest

from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from test_riders_c8 import ROOT, ME, MIND_SPIKE, MK_ALL, SPIRITUAL_SENSE, bundle, held
from test_a2_group_traditions4 import ENEMY, ALLY, act, advance, reload


def prepare(tmp_path, control='MANUAL', spirit=False, dc=40):
    service = CombatService(ROOT, tmp_path)
    me = bundle([*MK_ALL, SPIRITUAL_SENSE], dc=dc, resonance=100)
    enemy = bundle([MIND_SPIKE], actor_id=ENEMY, cl=5, dc=40)
    ally = bundle([MIND_SPIKE], actor_id=ALLY)
    enemy['actor_template']['creature_types'] = ['spirit' if spirit else 'humanoid']
    if dc == 1:
        enemy['actor_template']['saving_throws']['CHA'] = 100
    for doc in (me, enemy, ally):
        doc['actor_template']['maximum_hp'] = 1000
    base = next(a for a in enemy['action_catalog'] if a['display_name'] == 'Mind Spike')
    for key, name, rows in (
        ('burdens', 'Apply represented afflictions', [
            {'type': 'condition', 'condition': n, 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED',
             'condition_data': {'ordinary': True, 'origin_save': {'dc': 1, 'ability': 'WIS'}}}
            for n in ('diseased', 'cursed')]),
        ('curse', 'Test hostile curse save', [{'type': 'save', 'ability': 'wis', 'dc': 40, 'applies_to': 'target',
             'on_fail': [{'type': 'condition', 'condition': 'cursed', 'applies_to': 'target', 'duration': {'kind': 'scene'}}]}]),
        ('attack', 'Test hostile strike', [{'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 1,
             'applies_to': 'target', 'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['psychic'], 'applies_to': 'target'}]}]),
    ):
        action = copy.deepcopy(base)
        action.update(source_definition_id=base['source_definition_id'] + '.' + key, display_name=name, costs=[])
        action['parameters']['typed']['effects'] = rows
        enemy['action_catalog'].append(action)
        enemy['actor_template']['action_ids'].append(action['source_definition_id'])
    own = copy.deepcopy(next(a for a in enemy['action_catalog'] if a['display_name'] == 'Apply represented afflictions'))
    own.update(source_definition_id='action:typed.a2gtra4_ally.self_afflictions', owner_id=ALLY,
               display_name='Apply own represented afflictions', target_kind='SELF', range_ft=0)
    for row in own['parameters']['typed']['effects']:
        row['applies_to'] = 'self'
    ally['action_catalog'].append(own)
    ally['actor_template']['action_ids'].append(own['source_definition_id'])
    session = service.persistence.create_match(
        match_seed='A2GTRA4-GROUND', maximum_rounds=20, typed_bundles=(me, enemy, ally),
        roster_setup={'primary_actor_ids': [ME, ENEMY, ALLY],
                      'team_by_actor': {ME: 'team:a', ALLY: 'team:a', ENEMY: 'team:b'},
                      'starting_positions': {ME: {'x': 6, 'y': 6}, ALLY: {'x': 7, 'y': 6},
                                             ENEMY: {'x': 11 if spirit else 8, 'y': 6}}})
    metadata = {'participant_control_modes': {ME: control, ENEMY: 'MANUAL', ALLY: control}}
    return service, session, metadata


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_descent_named_curse_advantage_is_resolved_by_service(tmp_path, control):
    service, session, metadata = prepare(tmp_path, control)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Kami Descent: Descent of Protection')
    session = reload(service, session)
    advance(service, session, metadata, ENEMY)
    events, _, _ = act(service, session, metadata, 'Test hostile curse save', ME)
    rolls = [e.payload for e in events if e.event_type == 'SAVE_ROLLED']
    assert rolls and rolls[0]['mode'] == 'ADVANTAGE'
    reload(service, session)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_purifying_ground_repeats_represented_disease_save(tmp_path, control):
    service, session, metadata = prepare(tmp_path, control)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Sacred Ground: Purifying Ground')
    advance(service, session, metadata, ENEMY)
    act(service, session, metadata, 'Apply represented afflictions', ALLY)
    session = reload(service, session)
    def choose(context):
        spec = context.extension_choice
        if context.reaction_source_id.endswith('miko.purifying_ground'):
            return ('repeat',)
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    events = []
    while session.engine.state.current_actor_id != ALLY:
        committed, _, _ = act(service, session, metadata, 'End turn', choose=choose)
        events.extend(committed)
    assert any(e.event_type == 'SAVE_ROLLED' for e in events)
    session = reload(service, session)
    ally = session.engine.state.actors[ALLY]
    # Sorted instances choose disease or curse; either printed qualifying save ends one.
    assert len(held(ally, 'condition:typed.diseased') + held(ally, 'condition:typed.cursed')) == 1
    assert held(ally, 'condition:typed.purifying_ground_used')


@pytest.mark.parametrize('friendly', [True, False])
def test_purifying_ground_offers_repeat_only_for_hostile_affliction(tmp_path, friendly):
    """An ally's own matching condition is not offered a repeat save; a hostile one is."""
    service, session, metadata = prepare(tmp_path)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Sacred Ground: Purifying Ground')
    if friendly:
        advance(service, session, metadata, ALLY)
        act(service, session, metadata, 'Apply own represented afflictions', ALLY)
    else:
        advance(service, session, metadata, ENEMY)
        act(service, session, metadata, 'Apply represented afflictions', ALLY)
    session = reload(service, session)
    offered = []
    def choose(context):
        spec = context.extension_choice
        if context.reaction_source_id.endswith('miko.purifying_ground'):
            offered.append(True)
            return ('repeat',)
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    act(service, session, metadata, 'End turn', choose=choose)
    while session.engine.state.current_actor_id != ALLY:
        act(service, session, metadata, 'End turn', choose=choose)
    session = reload(service, session)
    ally = session.engine.state.actors[ALLY]
    assert bool(offered) is (not friendly)
    assert bool(held(ally, 'condition:typed.purifying_ground_used')) is (not friendly)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('friendly_burdens', [False, True])
def test_renewal_restore_ends_ordinary_disease_and_leaves_curse(tmp_path, control, friendly_burdens):
    service, session, metadata = prepare(tmp_path, control)
    advance(service, session, metadata, ALLY if friendly_burdens else ENEMY)
    act(service, session, metadata, 'Apply own represented afflictions' if friendly_burdens else 'Apply represented afflictions', None if friendly_burdens else ALLY)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Kami Descent: Descent of Renewal')
    act(service, session, metadata, 'Descent of Renewal: restore', ALLY)
    session = reload(service, session)
    assert not held(session.engine.state.actors[ALLY], 'condition:typed.diseased')
    assert held(session.engine.state.actors[ALLY], 'condition:typed.cursed')


def test_revelation_sense_is_120_feet_after_cold_reload(tmp_path):
    from combat import senses
    service, session, metadata = prepare(tmp_path)
    baseline = senses.of(session.engine, session.engine.state.actors[ME]).get('spiritual_sense', {}).get('range_ft', 0)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Kami Descent: Descent of Revelation')
    session = reload(service, session)
    assert senses.of(session.engine, session.engine.state.actors[ME])['spiritual_sense']['range_ft'] == 120
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Kami Descent: Descent of Protection')
    session = reload(service, session)
    assert senses.of(session.engine, session.engine.state.actors[ME]).get('spiritual_sense', {}).get('range_ft', 0) == baseline


@pytest.mark.parametrize('failed', [True, False])
def test_welcoming_ground_entry_save_hostile_actions_and_expiry(tmp_path, failed):
    from combat.ext.miko import WELCOMED
    service, session, metadata = prepare(tmp_path, spirit=True, dc=40 if failed else 1)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Sacred Ground: Welcoming Ground', destination=Position(x=6, y=6))
    advance(service, session, metadata, ENEMY)
    events, _, _ = act(service, session, metadata, 'Move to 10,6')
    assert any(e.event_type == 'SAVE_ROLLED' for e in events)
    session = reload(service, session)
    enemy = session.engine.state.actors[ENEMY]
    assert bool(held(enemy, WELCOMED)) == failed
    names = {c.display_name for c in session.engine.legal_candidates()}
    assert ('Test hostile curse save' in names) is not failed
    assert ('Test hostile strike' in names) is not failed
    assert 'Dodge' in names or 'Take the Dodge action' in names
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ENEMY)
    session = reload(service, session)
    assert not held(session.engine.state.actors[ENEMY], WELCOMED)


@pytest.mark.parametrize('friendly', [True, False])
def test_descent_of_purity_offers_repeat_only_for_hostile_affliction(tmp_path, friendly):
    """Descent of Purity offers the repeat-save blessing for a hostile affliction only, never an ally's or the Miko's own."""
    service, session, metadata = prepare(tmp_path)
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'Kami Descent: Descent of Purity')
    if friendly:
        advance(service, session, metadata, ALLY)
        act(service, session, metadata, 'Apply own represented afflictions', ALLY)
    else:
        advance(service, session, metadata, ENEMY)
        act(service, session, metadata, 'Apply represented afflictions', ALLY)
    session = reload(service, session)
    advance(service, session, metadata, ME)
    blessings = []
    def choose(context):
        spec = context.extension_choice
        if context.reaction_source_id.endswith('miko.purity'):
            return (ALLY,)
        if context.reaction_source_id.endswith('miko.purity_what'):
            blessings.append(tuple(spec.option_ids))
            return ('save',) if 'save' in spec.option_ids else ('heal',)
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    act(service, session, metadata, 'Purification Dance: Advantage against Frightened (2 Resonance)', ALLY, choose=choose)
    session = reload(service, session)
    assert blessings, 'Descent of Purity did not ask which blessing'
    assert any('save' in options for options in blessings) is (not friendly)
    assert 'heal' in blessings[0]
