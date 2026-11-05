"""A2GTRA3: real service choices, session execute_intent and cold reload."""
import copy
import json

import pytest

from combat.gate5_service import CombatService
from combat.gate2_runtime_models import ActionIntent, Position
from combat.ext import end_effect, inner_soul_gate as gate, last_inch_palm as palm
from test_riders_c8 import ROOT, ME, ALLY, MIND_SPIKE, bundle, held, HE, HE_ALL, HB_ALL, KW_ALL, NF_ALL, MF_ALL
from test_riders_c8_review import service_commit as base_service_commit

ENEMY = 'actor:factory.a2gtra3_enemy'
ALLY2 = 'actor:factory.a2gtra3_ally2'
LI = 'tianxia.tradition.spirit.last_inch_palm.feature.'
GATE_IDS = [MIND_SPIKE, gate.ROOT, gate.HEART]


def setup_action(pack, label, effects, *, kind='HOSTILE_ENTITY', numbers=None):
    action = copy.deepcopy(next(a for a in pack['action_catalog'] if a['display_name'] == 'Mind Spike'))
    action.update(source_definition_id='test:a2gtra3.' + label.replace(' ', '_'), display_name=label,
                  economy='NONE', costs=[], target_kind=kind, range_ft=120)
    action['parameters']['typed']['effects'] = effects
    action['parameters']['free_primary'] = True  # declared free activation; NONE alone is not a primary intent (ad49b65f)
    if numbers:
        action['parameters']['typed']['numbers'].update(numbers)
    pack['action_catalog'].append(action)
    pack['actor_template']['action_ids'].append(action['source_definition_id'])
    return action


def table(tmp_path, ids, control, *, enemy=None, mine=None, allies=True, ally_ids=None, dc=40, positions=None, battlefield=None):
    mine = mine or bundle(ids, dc=dc)
    enemy = enemy or bundle([MIND_SPIKE], actor_id=ENEMY)
    enemy['actor_template']['maximum_hp'] = 1000
    packs = [mine, enemy]
    teams = {ME: 'team:a', ENEMY: 'team:b'}
    spots = {ME: {'x': 6, 'y': 6}, ENEMY: {'x': 10, 'y': 6}}
    if allies:
        packs += [bundle(ally_ids or [MIND_SPIKE], actor_id=a) for a in (ALLY, ALLY2)]
        teams.update({a:'team:a' for a in (ALLY, ALLY2)})
        spots.update({ALLY:{'x':7,'y':6}, ALLY2:{'x':6,'y':7}})
    spots.update(positions or {})
    svc = CombatService(ROOT, tmp_path)
    session = svc.persistence.create_match(match_seed='A2GTRA3-EXACT', maximum_rounds=20,
        typed_bundles=tuple(packs), roster_setup={'primary_actor_ids':list(teams), 'team_by_actor':teams, 'starting_positions':spots},
        battlefield=battlefield)
    metadata = {'participant_control_modes': {a: 'MANUAL' for a in teams}}
    return svc, session, metadata


def service_commit(service, session, metadata, name, target=None, **kwargs):
    # Apply the same runtime control metadata as CombatService's load/mode path.
    # The test's metadata also routes the actual manual/automatic choice transport.
    session.engine.typed_control_modes = dict(metadata['participant_control_modes'])
    return base_service_commit(service, session, metadata, name, target, **kwargs)


def chooser(context):
    spec=context.extension_choice
    return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()


def advance(svc, session, metadata, who, choose=chooser):
    for _ in range(15):
        if session.engine.state.current_actor_id == who:
            return
        service_commit(svc, session, metadata, 'End turn', choose=choose)
    pytest.fail('turn not reached')


def reload(svc, session):
    state = session.engine.state.model_dump(mode='json')
    fresh = svc.persistence.load_match(session.match_id)
    assert fresh.engine.state.model_dump(mode='json') == state
    assert fresh.verify()['status'] == 'PASS'
    return fresh


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('success', [True, False])
def test_bite_repeats_original_dc_and_restores_only_on_success(tmp_path, control, success):
    other=bundle([MIND_SPIKE], actor_id=ENEMY, cl=18)
    setup_action(other, 'Radiance setup', [{'type':'condition','condition':'blessed','applies_to':'self',
        'expires_on':'UNTIL_REMOVED','condition_data':{'rule':{'effect_kind':'benefit'}}}], kind='SELF')
    setup_action(other, 'Save aid', [{'type':'save_bonus','amount':100,'abilities':['CHA'],'applies_to':'self','expires_on':'UNTIL_REMOVED'}],kind='SELF')
    svc,session,meta=table(tmp_path, HE_ALL, control, enemy=other, allies=False)
    advance(svc,session,meta,ENEMY)
    service_commit(svc,session,meta,'Radiance setup',choose=chooser)
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Bite the Halo',ENEMY,choose=chooser)
    session=reload(svc,session)
    target=session.engine.state.actors[ENEMY]
    assert target.turn_flags[end_effect.SUPPRESSED_FLAG][0]['bite_dc']==40
    advance(svc,session,meta,ENEMY)
    if success: service_commit(svc,session,meta,'Save aid',choose=chooser)
    meta['participant_control_modes'][ENEMY]=control
    events,_,_=service_commit(svc,session,meta,'End turn',choose=chooser)
    assert any(e.event_type=='SAVE_ROLLED' and e.actor_id==ENEMY and e.payload['dc']==(-60 if success else 40) for e in events)
    session=reload(svc,session)
    assert bool(held(session.engine.state.actors[ENEMY],'condition:typed.blessed')) is success


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_root_opening_native_stand_cost_is_five(tmp_path,control):
    mine=bundle(GATE_IDS)
    setup_action(mine,'Lie down',[{'type':'condition','condition':'prone','applies_to':'self','expires_on':'UNTIL_REMOVED'}],kind='SELF')
    svc,session,meta=table(tmp_path,GATE_IDS,control,mine=mine)
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Root Opening',choose=chooser)
    service_commit(svc,session,meta,'Lie down',choose=chooser)
    session=reload(svc,session)
    before=session.engine.state.actors[ME].movement_remaining_ft
    meta['participant_control_modes'][ME]=control
    name=next(c.display_name for c in session.engine.legal_candidates() if c.display_name.startswith('Stand up'))
    service_commit(svc,session,meta,name,choose=chooser)
    session=reload(svc,session)
    assert session.engine.state.actors[ME].movement_remaining_ft==before-5
    assert not held(session.engine.state.actors[ME],'condition:typed.prone')


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_heart_restoration_failed_save_suppresses_until_source_start(tmp_path,control):
    other=bundle([MIND_SPIKE],actor_id=ENEMY,cl=18)
    setup_action(other,'Fear setup',[{'type':'condition','condition':'frightened','applies_to':'target','expires_on':'UNTIL_REMOVED',
        'condition_data':{'origin_save':{'dc':100,'ability':'CHA'}}}])
    svc,session,meta=table(tmp_path,GATE_IDS,control,enemy=other)
    advance(svc,session,meta,ENEMY)
    service_commit(svc,session,meta,'Fear setup',ALLY,choose=chooser)
    advance(svc,session,meta,ME)
    meta['participant_control_modes'][ME]=control
    events,_,_=service_commit(svc,session,meta,'Heart Restoration',ALLY,choose=chooser)
    saves=[e for e in events if e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY]
    assert saves[-1].payload['dc']==100 and saves[-1].payload['reason'].endswith(':CHA')
    assert any('Cultivation Level' in str(e.payload) for e in events)
    session=reload(svc,session)
    target=session.engine.state.actors[ALLY]
    assert not held(target,'condition:typed.frightened')
    assert target.turn_flags[end_effect.SUPPRESSED_FLAG][0]['boundary']=='start'
    service_commit(svc,session,meta,'End turn',choose=chooser)
    advance(svc,session,meta,ME)
    session=reload(svc,session)
    assert held(session.engine.state.actors[ALLY],'condition:typed.frightened')


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_two_heart_restorers_cannot_nest_suppression_clocks(tmp_path,control):
    """A suppressed symptom is unavailable to the second restorer and returns once."""
    other=bundle([MIND_SPIKE],actor_id=ENEMY,cl=18)
    setup_action(other,'Two symptoms',[
        {'type':'condition','condition':'frightened','applies_to':'target','expires_on':'UNTIL_REMOVED',
         'condition_data':{'origin_save':{'dc':100,'ability':'CHA'}}},
        {'type':'condition','condition':'charmed','applies_to':'target','expires_on':'UNTIL_REMOVED',
         'condition_data':{'origin_save':{'dc':100,'ability':'CHA'}}}])
    svc,session,meta=table(tmp_path,GATE_IDS,control,enemy=other,ally_ids=GATE_IDS)
    advance(svc,session,meta,ENEMY)
    service_commit(svc,session,meta,'Two symptoms',ALLY2,choose=chooser)
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Heart Restoration',ALLY2,choose=chooser)
    session=reload(svc,session)
    target=session.engine.state.actors[ALLY2]
    assert len(gate._calm(target))==1
    advance(svc,session,meta,ALLY)
    meta['participant_control_modes'][ALLY]=control
    service_commit(svc,session,meta,'Heart Restoration',ALLY2,choose=chooser)
    session=reload(svc,session)
    target=session.engine.state.actors[ALLY2]
    rows=target.turn_flags[end_effect.SUPPRESSED_FLAG]
    assert len(rows)==2
    assert all(not row['original'].startswith('condition:typed.suppressed.') for row in rows)
    assert len(gate._calm(target))==0
    advance(svc,session,meta,ME)
    session=reload(svc,session)
    advance(svc,session,meta,ALLY)
    session=reload(svc,session)
    target=session.engine.state.actors[ALLY2]
    assert not target.turn_flags.get(end_effect.SUPPRESSED_FLAG)
    assert {c.condition_id for c in target.conditions.values() if c.condition_id.rsplit('.',1)[-1] in {'frightened','charmed'}} == {
        'condition:typed.frightened','condition:typed.charmed'}


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('include_owner', [True, False])
def test_chain_member_selection_contains_only_allies(tmp_path,control,include_owner):
    svc,session,meta=table(tmp_path,HB_ALL,control)
    advance(svc,session,meta,ME)
    for ally in (ALLY,ALLY2):
        if not held(session.engine.state.actors[ally], 'condition:typed.mark.vow_mark.'+ME):
            service_commit(svc,session,meta,'Vow Mark',ally,choose=chooser)
            service_commit(svc,session,meta,'End turn',choose=chooser)
            advance(svc,session,meta,ME)
    session=reload(svc,session)
    meta['participant_control_modes'][ME]=control
    def choose(c):
        if c.reaction_source_id.endswith('chain_members'):
            assert set(c.extension_choice.option_ids)=={ME,ALLY,ALLY2}
            return (ME,ALLY2) if include_owner else (ALLY,ALLY2)
        return chooser(c)
    service_commit(svc,session,meta,'Chain of Devotion',choose=choose)
    session=reload(svc,session)
    from combat.ext.damage_sharing import CHAIN
    assert bool(held(session.engine.state.actors[ME],CHAIN)) is (include_owner or control=='LOCAL_AUTO')
    assert held(session.engine.state.actors[ALLY2],CHAIN)
    assert not held(session.engine.state.actors[ENEMY],CHAIN)
    assert bool(held(session.engine.state.actors[ALLY],CHAIN)) is (not include_owner or control=='LOCAL_AUTO')


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('block_sides', [False, True])
def test_draw_palm_chooses_lateral_adjacent_endpoint(tmp_path,control,block_sides):
    ids=[MIND_SPIKE,LI+'the_last_inch',LI+'palm_across_emptiness']
    mine=bundle(ids)
    setup_action(mine,'Mark setup',[{'type':'mark','mark':'Resonance','applies_to':'target','expires_on':'UNTIL_REMOVED'}])
    spots={ENEMY:{'x':11,'y':6}}
    if block_sides:
        spots.update({ALLY:{'x':7,'y':6},ALLY2:{'x':5,'y':6}})
    svc,session,meta=table(tmp_path,ids,control,mine=mine,allies=block_sides,positions=spots)
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Mark setup',ENEMY,choose=chooser)
    meta['participant_control_modes'][ME]=control
    name=next(c.display_name for c in session.engine.legal_candidates() if 'Palm Across Emptiness' in c.display_name and 'Draw Into' in c.display_name)
    def choose(c):
        if c.reaction_source_id.endswith('draw_destination'):
            assert 'cell:6,5' in c.extension_choice.option_ids
            return ('cell:6,5',)
        return chooser(c)
    events,_,_=service_commit(svc,session,meta,name,ENEMY,choose=choose)
    session=reload(svc,session)
    target=session.engine.state.actors[ENEMY]
    if control=='MANUAL':
        assert (target.position.x,target.position.y)==(6,5)
    assert session.engine._distance_actor_to_actor(target,session.engine.state.actors[ME])==5
    assert any(e.event_type=='MOVEMENT_COMMITTED' and ENEMY==e.actor_id for e in events)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_draw_palm_far_side_arrival_is_offered_at_maximum_range(tmp_path,control):
    # Printed text: "Move it to a legal space adjacent to you" -- the 30 feet is the action's Range,
    # not a travel budget, so the square on the far side of the caster (35 feet from a target that is
    # exactly 30 feet away) is a legal destination and has to be offered.
    ids=[MIND_SPIKE,LI+'the_last_inch',LI+'palm_across_emptiness']
    mine=bundle(ids)
    setup_action(mine,'Mark setup',[{'type':'mark','mark':'Resonance','applies_to':'target','expires_on':'UNTIL_REMOVED'}])
    svc,session,meta=table(tmp_path,ids,control,mine=mine,allies=False,positions={ENEMY:{'x':12,'y':6}})
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Mark setup',ENEMY,choose=chooser)
    meta['participant_control_modes'][ME]=control
    engine=session.engine
    assert engine._distance_actor_to_actor(engine.state.actors[ENEMY],engine.state.actors[ME])==30
    name=next(c.display_name for c in session.engine.legal_candidates() if 'Palm Across Emptiness' in c.display_name and 'Draw Into' in c.display_name)
    def choose(c):
        if c.reaction_source_id.endswith('draw_destination'):
            assert 'cell:5,6' in c.extension_choice.option_ids
            return ('cell:5,6',)
        return chooser(c)
    events,_,_=service_commit(svc,session,meta,name,ENEMY,choose=choose)
    session=reload(svc,session)
    target=session.engine.state.actors[ENEMY]
    if control=='MANUAL':
        assert (target.position.x,target.position.y)==(5,6)
    assert session.engine._distance_actor_to_actor(target,session.engine.state.actors[ME])==5
    assert any(e.event_type=='MOVEMENT_COMMITTED' and ENEMY==e.actor_id for e in events)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_collapse_arrival_is_player_chosen_native_teleport(tmp_path,control):
    svc,session,meta=table(tmp_path,NF_ALL,control,positions={ALLY:{'x':10,'y':8}})
    advance(svc,session,meta,ME)
    name=next(c.display_name for c in session.engine.legal_candidates() if c.display_name.startswith('Name What Is Near') and ALLY in c.target_ids)
    service_commit(svc,session,meta,name,ALLY,choose=chooser)
    service_commit(svc,session,meta,'End turn',choose=chooser)
    advance(svc,session,meta,ME)
    meta['participant_control_modes'][ME]=control
    def choose(c):
        if c.reaction_source_id.endswith('collapse_destination'):
            assert 'cell:11,8' in c.extension_choice.option_ids
            return ('cell:11,8',)
        if c.reaction_source_id.endswith('collapse_to'): return (ALLY,)
        return chooser(c)
    events,_,_=service_commit(svc,session,meta,'Collapse the Interval',choose=choose)
    session=reload(svc,session)
    assert session.engine._distance_actor_to_actor(session.engine.state.actors[ME],session.engine.state.actors[ALLY])==5
    if control=='MANUAL': assert (session.engine.state.actors[ME].position.x,session.engine.state.actors[ME].position.y)==(11,8)
    assert any(e.event_type=='MOVEMENT_COMMITTED' and e.payload.get('teleport') for e in events)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_collapse_subject_at_120_feet_can_arrive_on_far_side(tmp_path,control):
    battlefield=json.loads((ROOT/'combat_gate1/generated/Battlefield.json').read_text())
    battlefield['width_squares']=30
    mine=bundle(NF_ALL)
    setup_action(mine,'Set distant Near relation',[{'type':'near_name','applies_to':'target'}],kind='ALLY_OR_SELF')
    svc,session,meta=table(tmp_path,NF_ALL,control,mine=mine,positions={ME:{'x':1,'y':6},ALLY:{'x':25,'y':6}},battlefield=battlefield)
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Set distant Near relation',ALLY,choose=chooser)
    session=reload(svc,session)
    assert session.engine._distance_actor_to_actor(session.engine.state.actors[ME],session.engine.state.actors[ALLY])==120
    meta['participant_control_modes'][ME]=control
    def choose(c):
        if c.reaction_source_id.endswith('collapse_destination'):
            assert 'cell:26,6' in c.extension_choice.option_ids
            return ('cell:26,6',)
        if c.reaction_source_id.endswith('collapse_to'): return (ALLY,)
        return chooser(c)
    events,_,_=service_commit(svc,session,meta,'Collapse the Interval',choose=choose)
    session=reload(svc,session)
    if control=='MANUAL':
        assert (session.engine.state.actors[ME].position.x,session.engine.state.actors[ME].position.y)==(26,6)
    else:
        assert session.engine._distance_actor_to_actor(session.engine.state.actors[ME],session.engine.state.actors[ALLY])==5
    assert any(e.event_type=='MOVEMENT_COMMITTED' and e.payload.get('teleport') for e in events)


def test_collapse_carried_traveler_can_land_beyond_its_origin_range(tmp_path):
    battlefield=json.loads((ROOT/'combat_gate1/generated/Battlefield.json').read_text())
    battlefield['width_squares']=30
    mine=bundle(NF_ALL)
    setup_action(mine,'Set distant Near relation',[{'type':'near_name','applies_to':'target'}],kind='ALLY_OR_SELF')
    svc,session,meta=table(tmp_path,NF_ALL,'MANUAL',mine=mine,positions={ME:{'x':1,'y':6},ALLY:{'x':25,'y':6},ALLY2:{'x':1,'y':7}},battlefield=battlefield)
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Set distant Near relation',ALLY,choose=chooser)
    session=reload(svc,session)
    assert session.engine._distance_actor_to_actor(session.engine.state.actors[ME],session.engine.state.actors[ALLY])==120
    destinations=[]
    def choose(c):
        if c.reaction_source_id.endswith('collapse_carry'):
            return (ALLY2,)
        if c.reaction_source_id.endswith('collapse_destination'):
            expected=('cell:26,6','cell:26,7')[len(destinations)]
            destinations.append(expected)
            assert expected in c.extension_choice.option_ids
            return (expected,)
        if c.reaction_source_id.endswith('collapse_to'): return (ALLY,)
        return chooser(c)
    events,_,_=service_commit(svc,session,meta,'Collapse the Interval (carry allies)',choose=choose)
    session=reload(svc,session)
    assert len(destinations)==2
    assert (session.engine.state.actors[ME].position.x,session.engine.state.actors[ME].position.y)==(26,6)
    assert (session.engine.state.actors[ALLY2].position.x,session.engine.state.actors[ALLY2].position.y)==(26,7)
    assert any(e.event_type=='MOVEMENT_COMMITTED' and e.payload.get('teleport') for e in events)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_sever_selects_represented_possession(tmp_path,control):
    other=bundle([MIND_SPIKE],actor_id=ENEMY,cl=6)
    setup_action(other,'Possession setup',[{'type':'condition','condition':'possessed','applies_to':'target','expires_on':'UNTIL_REMOVED',
        'condition_data':{'origin_save':{'dc':-40,'ability':'WIS'}}}])
    svc,session,meta=table(tmp_path,KW_ALL,control,enemy=other)
    advance(svc,session,meta,ENEMY)
    service_commit(svc,session,meta,'Possession setup',ALLY,choose=chooser)
    advance(svc,session,meta,ME)
    meta['participant_control_modes'][ME]=control
    service_commit(svc,session,meta,'Sever the False Thread',ALLY,choose=chooser)
    session=reload(svc,session)
    assert not held(session.engine.state.actors[ALLY],'condition:typed.possessed')


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_gentle_knife_edge_consumed_by_pressure_save(tmp_path,control):
    other=bundle([MIND_SPIKE],actor_id=ENEMY)
    setup_action(other,'Pressure save',[{'type':'save','ability':'wis','on_fail':[{'type':'spiritual_pressure','applies_to':'target','option':'stilled_intent'}]}])
    svc,session,meta=table(tmp_path,MF_ALL,control,enemy=other)
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Gentle Knife: Take the Edge',ALLY,choose=chooser)
    session=reload(svc,session)
    advance(svc,session,meta,ENEMY)
    meta['participant_control_modes'][ALLY]=control
    events,_,_=service_commit(svc,session,meta,'Pressure save',ALLY,choose=chooser)
    saves=[e for e in events if e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY]
    assert saves[-1].payload['mode']=='ADVANTAGE'
    session=reload(svc,session)
    assert not any(c.data.get('mercy_edge') for c in session.engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_ten_thousand_hands_never_strikes_designated_ally(tmp_path,control):
    ids=[MIND_SPIKE,LI+'the_last_inch',LI+'world_of_one_handspan']
    mine=bundle(ids)
    setup_action(mine,'Friendly designation',[{'type':'condition','condition':'handspan_subject','applies_to':'target',
        'expires_on':'UNTIL_REMOVED'}],kind='ALLY_OR_SELF')
    svc,session,meta=table(tmp_path,ids,control,mine=mine)
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Friendly designation',ALLY,choose=chooser)
    service_commit(svc,session,meta,'World of One Handspan',choose=chooser)
    session=reload(svc,session)
    meta['participant_control_modes'][ME]=control
    def choose(c):
        if c.reaction_source_id.endswith('hands_subjects'):
            assert c.extension_choice.option_ids==(ENEMY,)
            assert 'field created by World of One Handspan' in c.choice_trigger['prompt']
            return (ENEMY,)
        return chooser(c)
    events,_,_=service_commit(svc,session,meta,'Ten Thousand Hands: strike up to PB Handspan Subjects',choose=choose)
    assert {t for e in events if e.event_type=='ATTACK_ROLLED' for t in e.target_ids}=={ENEMY}
    session=reload(svc,session)
    assert session.engine.state.actors[ALLY].current_hp==90


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('secondary_success', [True, False])
def test_large_draw_palm_secondary_strength_save_caps_only_on_success(tmp_path,control,secondary_success):
    ids=[MIND_SPIKE,LI+'the_last_inch',LI+'palm_across_emptiness']
    mine=bundle(ids)
    setup_action(mine,'Mark setup',[{'type':'mark','mark':'Resonance','applies_to':'target','expires_on':'UNTIL_REMOVED'}])
    other=bundle([MIND_SPIKE],actor_id=ENEMY)
    # These are sealed fixture creature statistics, set before match creation.
    # The native evented d20 roller and both saves are used without replacement.
    other['actor_template']['size_category']='Huge'
    other['actor_template']['saving_throws']['STR']=100 if secondary_success else 0
    svc,session,meta=table(tmp_path,ids,control,mine=mine,enemy=other,allies=False,positions={ENEMY:{'x':11,'y':6}})
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Mark setup',ENEMY,choose=chooser)
    meta['participant_control_modes'][ME]=control
    def draw_choose(context):
        # The optional Strength save is a player prompt (9eeaf9fa); answer it with the save.
        spec=context.extension_choice
        if spec and 'save' in spec.option_ids and spec.allow_decline:
            return ('save',)
        return chooser(context)
    name=next(c.display_name for c in session.engine.legal_candidates() if 'Palm Across Emptiness' in c.display_name and 'Draw Into' in c.display_name)
    events,_,_=service_commit(svc,session,meta,name,ENEMY,choose=draw_choose)
    session=reload(svc,session)
    saves=[e for e in events if e.event_type=='SAVE_ROLLED' and e.actor_id==ENEMY]
    assert any(e.payload['reason'].endswith(':STR') and e.payload['success'] is secondary_success for e in saves)
    target=session.engine.state.actors[ENEMY]
    assert session.engine._distance_actor_to_actor(target,session.engine.state.actors[ME])==(15 if secondary_success else 5)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_chain_manual_can_choose_known_unseen_ally_automatic_does_not(tmp_path,control):
    mine=bundle(HB_ALL)
    setup_action(mine,'Conceal ally',[{'type':'condition','condition':'invisible','applies_to':'target','expires_on':'UNTIL_REMOVED'}],kind='ALLY_OR_SELF')
    svc,session,meta=table(tmp_path,HB_ALL,control,mine=mine)
    advance(svc,session,meta,ME)
    for ally in (ALLY,ALLY2):
        service_commit(svc,session,meta,'Vow Mark',ally,choose=chooser)
        service_commit(svc,session,meta,'End turn',choose=chooser)
        advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Conceal ally',ALLY2,choose=chooser)
    session=reload(svc,session)
    meta['participant_control_modes'][ME]=control
    def choose(c):
        if c.reaction_source_id.endswith('chain_members'):
            assert ALLY2 in c.extension_choice.option_ids
            return (ME,ALLY2)
        return chooser(c)
    service_commit(svc,session,meta,'Chain of Devotion',choose=choose)
    session=reload(svc,session)
    from combat.ext.damage_sharing import CHAIN
    assert bool(held(session.engine.state.actors[ALLY2],CHAIN)) is (control=='MANUAL')
    assert held(session.engine.state.actors[ME],CHAIN)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('burden', ['grief', 'despair'])
@pytest.mark.parametrize('procedure', ['Hold the Heart', 'Bear It With Me'])
def test_borrowed_courage_suppresses_or_transfers_printed_burdens(tmp_path,control,burden,procedure):
    other=bundle([MIND_SPIKE],actor_id=ENEMY,cl=6)
    setup_action(other,'Burden setup',[{'type':'condition','condition':burden,'applies_to':'target','expires_on':'UNTIL_REMOVED',
        'condition_data':{'origin_save':{'dc':31,'ability':'WIS'},'rule':{'save_mode':{'WIS':'DISADVANTAGE'}}}}])
    setup_action(other,'Burden probe',[{'type':'save','ability':'wis','applies_to':'target','on_fail':[]}])
    svc,session,meta=table(tmp_path,HB_ALL,control,enemy=other)
    advance(svc,session,meta,ME)
    service_commit(svc,session,meta,'Vow Mark',ALLY,choose=chooser)
    advance(svc,session,meta,ENEMY)
    service_commit(svc,session,meta,'Burden setup',ALLY,choose=chooser)
    advance(svc,session,meta,ME)
    meta['participant_control_modes'][ME]=control
    service_commit(svc,session,meta,'Borrowed Courage: '+procedure,ALLY,choose=chooser)
    session=reload(svc,session)
    owner,friend=session.engine.state.actors[ME],session.engine.state.actors[ALLY]
    assert not held(friend,'condition:typed.'+burden)
    if procedure=='Hold the Heart':
        assert any(c.condition_id.startswith('condition:typed.suppressed.') for c in friend.conditions.values())
        assert not held(owner,'condition:typed.'+burden)
        advance(svc,session,meta,ENEMY)
        events,_,_=service_commit(svc,session,meta,'Burden probe',ALLY,choose=chooser)
        assert any(e.event_type=='SAVE_ROLLED' and e.actor_id==ALLY and e.payload['mode']=='NORMAL' for e in events)
        session=reload(svc,session)
        advance(svc,session,meta,ME)
        service_commit(svc,session,meta,'End turn',choose=chooser)
        session=reload(svc,session)
        assert held(session.engine.state.actors[ALLY],'condition:typed.'+burden)
    else:
        [carried]=held(owner,'condition:typed.'+burden)
        assert carried.source_actor_id==ENEMY and carried.data['origin_save']=={'dc':31,'ability':'WIS'}
        advance(svc,session,meta,ENEMY)
        events,_,_=service_commit(svc,session,meta,'Burden probe',ME,choose=chooser)
        assert any(e.event_type=='SAVE_ROLLED' and e.actor_id==ME and e.payload['mode']=='DISADVANTAGE' for e in events)
        session=reload(svc,session)



def _legal_adjacent_arrivals(engine, chooser, occupant, *, altitude=None):
    """Every anchor the engine's OWN adjacency and volume rules call legal for ``occupant`` beside ``chooser``.

    Scans the whole map through the engine's own measures so this never reuses the helper under test.
    """
    occupied = engine._occupied_volumes_except(occupant.entity_id)
    footprint = engine._footprint(occupant)
    out = []
    for x in range(engine.grid.width):
        for y in range(engine.grid.height):
            cell = Position(x=x, y=y, z=chooser.position.z if altitude is None else altitude)
            if engine._distance_actor_to_actor(occupant, chooser, actor_position=cell) > 5:
                continue
            if not engine.grid.volume_legal(cell, footprint=footprint, occupied_cells=occupied):
                continue
            out.append((x, y))
    return out


def _eight_neighbour_anchors(chooser):
    from combat.ext.forced_destination import NEIGHBORS
    return {(chooser.position.x + dx, chooser.position.y + dy) for dx, dy in NEIGHBORS}


def _draw_palm(svc, session, meta, control):
    return next(c.display_name for c in session.engine.legal_candidates()
                if 'Palm Across Emptiness' in c.display_name and 'Draw Into' in c.display_name)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_draw_palm_offers_arrival_at_mover_altitude_when_chooser_is_lower(tmp_path, control):
    """A2GTRA3r6 finding 1: the legal goal altitude must match the altitude-preserving route."""
    ids = [MIND_SPIKE, LI + 'the_last_inch', LI + 'palm_across_emptiness']
    mine = bundle(ids)
    setup_action(mine, 'Mark setup', [{'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target',
                                       'expires_on': 'UNTIL_REMOVED'}])
    other = bundle([MIND_SPIKE], actor_id=ENEMY)
    other['actor_template']['saving_throws']['WIS'] = 0
    other['actor_template'].update(fly_speed_ft=30, hover=True)
    svc, session, meta = table(tmp_path, ids, control, mine=mine, enemy=other, allies=False,
                               positions={ENEMY: {'x': 10, 'y': 6}})
    advance(svc, session, meta, ME)
    service_commit(svc, session, meta, 'Mark setup', ENEMY, choose=chooser)
    meta['participant_control_modes'][ME] = control
    session = reload(svc, session)

    # Starting-position input is intentionally ground-only. Give the target altitude by its own
    # legal fly move, preview it through CombatService, commit execute_intent, and cold reload.
    advance(svc, session, meta, ENEMY)
    ascender = next(c for c in session.engine.legal_candidates()
                    if c.actor_id == ENEMY and c.destination == Position(x=10, y=6, z=1))
    intent = ActionIntent(intent_id='a2gtra3r7-altitude-setup', decision_id=ascender.decision_id,
                          candidate_id=ascender.candidate_id, state_version=ascender.state_version,
                          actor_id=ENEMY, target_ids=ascender.target_ids, destination=ascender.destination)
    preview = svc._run_preview(session, meta, intent, ())
    session.mechanical.execute_intent(ActionIntent.model_validate(preview['intent']))
    session = reload(svc, session)
    service_commit(svc, session, meta, 'End turn', choose=chooser)
    session = reload(svc, session)
    advance(svc, session, meta, ME)

    engine = session.engine
    palm_actor, target = engine.state.actors[ME], engine.state.actors[ENEMY]
    assert palm_actor.position.z == 0 and target.position.z == 1
    legal = _legal_adjacent_arrivals(engine, palm_actor, target, altitude=target.position.z)
    assert (7, 6) in legal, 'fixture must include the review’s legal elevated arrival'
    selected = (7, 6)
    # Main's shared movement-choice transport includes nonzero altitude.
    # Keep choosing the same elevated arrival and all placement assertions.
    from combat.ext.needle import cell_id
    selected_id = cell_id(Position(x=selected[0], y=selected[1], z=1))
    seen = []

    def choose(c):
        if c.reaction_source_id.endswith('draw_destination'):
            seen.append(c.extension_choice.option_ids)
            if control == 'MANUAL':
                return (selected_id,)
        return chooser(c)

    events, prompts, _ = service_commit(svc, session, meta, _draw_palm(svc, session, meta, control),
                                        ENEMY, choose=choose)
    recorded = seen + [p.extension_choice.option_ids for p in prompts
                      if p.reaction_source_id.endswith('draw_destination')]
    session = reload(svc, session)
    moved = session.engine.state.actors[ENEMY]
    if control == 'MANUAL':
        assert (moved.position.x, moved.position.y, moved.position.z) == (*selected, 1)
    else:
        assert (moved.position.x, moved.position.y) in legal
        assert moved.position.z == 1
    assert session.engine._distance_actor_to_actor(moved, session.engine.state.actors[ME]) == 5
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and ENEMY == e.actor_id for e in events)
    if control == 'MANUAL':
        assert recorded, 'the player must receive the destination choice'
        assert selected_id in recorded[0]


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_draw_palm_offers_multi_cell_target_arrivals_outside_eight_neighbours(tmp_path, control):
    """A2GTRA3r5 finding 1: a multi-cell target has legal "space adjacent to you" arrivals that are not
    among the eight offsets of the chooser's top-left anchor.

    Footprints are anchored top-left and extend right and down, while the engine measures separation
    between the two occupied CELL SETS. A 2x2 target anchored two cells west of a Medium chooser is
    still only one cell from that chooser's body. Enumerating the chooser's eight neighbouring anchors
    cannot produce that anchor, so the paid draw silently lost a legal destination -- and if the eight
    neighbouring sides were blocked the draw would do nothing at all.

    The growth is a real, committed, reloaded ``size_change``, so the 2x2 body is saved state rather
    than a live-only mutation, exactly as a player who was grown before the draw would be.
    """
    ids = [MIND_SPIKE, LI + 'the_last_inch', LI + 'palm_across_emptiness']
    mine = bundle(ids)
    setup_action(mine, 'Mark setup', [{'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target',
                                       'expires_on': 'UNTIL_REMOVED'}])
    other = bundle([MIND_SPIKE], actor_id=ENEMY)
    setup_action(other, 'Grow self', [{'type': 'size_change', 'size': 'Large', 'duration': 'one_minute'}])
    # Sealed fixture creature statistics, set before match creation: the real evented d20 roller
    # runs, and this only pins the opening Wisdom save to the failure the printed draw hangs on.
    other['actor_template']['saving_throws']['WIS'] = 0
    svc, session, meta = table(tmp_path, ids, control, mine=mine, enemy=other, allies=False,
                               positions={ENEMY: {'x': 8, 'y': 6}})
    advance(svc, session, meta, ME)
    service_commit(svc, session, meta, 'Mark setup', ENEMY, choose=chooser)
    meta['participant_control_modes'][ME] = control
    # The drawn creature grows on its own turn, through the engine's own size_change, so the 2x2
    # body is committed, evented state that survives the cold reload below.
    advance(svc, session, meta, ENEMY)
    service_commit(svc, session, meta, 'Grow self', choose=chooser)
    session = reload(svc, session)
    advance(svc, session, meta, ME)
    engine = session.engine
    target, palm_actor = engine.state.actors[ENEMY], engine.state.actors[ME]
    assert target.transformed_size_category == 'Large', 'the growth must be saved, reloaded state'
    assert engine._footprint(target).width_cells == 2, 'the draw target must really occupy two cells'

    legal = _legal_adjacent_arrivals(engine, palm_actor, target)
    omitted = [c for c in legal if c not in _eight_neighbour_anchors(palm_actor)]
    assert omitted, 'this board must produce an arrival the eight-neighbour enumeration cannot reach'

    seen = []

    def choose(c):
        if c.reaction_source_id.endswith('draw_destination'):
            seen.append(c.extension_choice.option_ids)
            return (f'cell:{omitted[0][0]},{omitted[0][1]}',)
        return chooser(c)

    events, prompts, _ = service_commit(svc, session, meta, _draw_palm(svc, session, meta, control),
                                        ENEMY, choose=choose)
    # Asserted on the recorded prompt, so the arrivals must be OFFERED under either control mode; only
    # a manual controller can afterwards be told to take one of them.
    recorded = seen + [p.extension_choice.option_ids for p in prompts
                      if p.reaction_source_id.endswith('draw_destination')]
    session = reload(svc, session)
    moved = session.engine.state.actors[ENEMY]
    if control == 'MANUAL':
        # The player owns this menu, so the printed destination set is asserted exactly: every legal
        # arrival the eight-neighbour enumeration used to drop must be on offer, and the chooser is
        # then told to take one of them.
        assert recorded, 'the full draw must put its destinations to a chooser'
        offered = set(recorded[0])
        for x, y in omitted:
            assert f'cell:{x},{y}' in offered, (f'cell:{x},{y}' not in offered)
        assert (moved.position.x, moved.position.y) == omitted[0]
    else:
        # Under LOCAL_AUTO the local controller answers the menu inside the preview, so no prompt is
        # surfaced; what must hold is that the automatic actor landed on a legal adjacent arrival.
        assert (moved.position.x, moved.position.y) in legal
    assert session.engine._distance_actor_to_actor(moved, session.engine.state.actors[ME]) == 5
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and ENEMY == e.actor_id for e in events)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
def test_draw_palm_offers_multi_cell_caster_arrivals_outside_eight_neighbours(tmp_path, control):
    """A2GTRA3r5 finding 1, chooser side: a multi-cell drawing creature's own body reaches further
    than its top-left anchor, so a Medium target may land two cells east of that anchor and still be
    adjacent to the chooser's occupied squares. The eight offsets of the chooser's ANCHOR lose those
    arrivals just as they lose the multi-cell target's.

    The chooser is grown by a real, committed, reloaded ``size_change`` on its own turn, so this is
    the same saved state a player who grew earlier would be drawing from.
    """
    ids = [MIND_SPIKE, LI + 'the_last_inch', LI + 'palm_across_emptiness']
    mine = bundle(ids)
    setup_action(mine, 'Mark setup', [{'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target',
                                       'expires_on': 'UNTIL_REMOVED'}])
    setup_action(mine, 'Grow self', [{'type': 'size_change', 'size': 'Large', 'duration': 'one_minute'}],
                 kind='SELF')
    other = bundle([MIND_SPIKE], actor_id=ENEMY)
    other['actor_template']['saving_throws']['WIS'] = 0
    svc, session, meta = table(tmp_path, ids, control, mine=mine, enemy=other, allies=False,
                               positions={ENEMY: {'x': 10, 'y': 6}})
    advance(svc, session, meta, ME)
    service_commit(svc, session, meta, 'Mark setup', ENEMY, choose=chooser)
    meta['participant_control_modes'][ME] = control
    service_commit(svc, session, meta, 'Grow self', choose=chooser)
    session = reload(svc, session)
    engine = session.engine
    palm_actor, target = engine.state.actors[ME], engine.state.actors[ENEMY]
    assert palm_actor.transformed_size_category == 'Large', 'the growth must be saved, reloaded state'
    assert engine._footprint(palm_actor).width_cells == 2, 'the drawing creature must really occupy two cells'

    legal = _legal_adjacent_arrivals(engine, palm_actor, target)
    omitted = [c for c in legal if c not in _eight_neighbour_anchors(palm_actor)]
    assert omitted, 'this board must produce an arrival the eight-neighbour enumeration cannot reach'

    seen = []

    def choose(c):
        if c.reaction_source_id.endswith('draw_destination'):
            seen.append(c.extension_choice.option_ids)
            return (f'cell:{omitted[0][0]},{omitted[0][1]}',)
        return chooser(c)

    events, prompts, _ = service_commit(svc, session, meta, _draw_palm(svc, session, meta, control),
                                        ENEMY, choose=choose)
    recorded = seen + [p.extension_choice.option_ids for p in prompts
                      if p.reaction_source_id.endswith('draw_destination')]
    session = reload(svc, session)
    moved = session.engine.state.actors[ENEMY]
    if control == 'MANUAL':
        # The player owns this menu, so the printed destination set is asserted exactly: every legal
        # arrival the eight-neighbour enumeration used to drop must be on offer, and the chooser is
        # then told to take one of them.
        assert recorded, 'the full draw must put its destinations to a chooser'
        offered = set(recorded[0])
        for x, y in omitted:
            assert f'cell:{x},{y}' in offered, (f'cell:{x},{y}' not in offered)
        assert (moved.position.x, moved.position.y) == omitted[0]
    else:
        # Under LOCAL_AUTO the local controller answers the menu inside the preview, so no prompt is
        # surfaced; what must hold is that the automatic actor landed on a legal adjacent arrival.
        assert (moved.position.x, moved.position.y) in legal
    assert session.engine._distance_actor_to_actor(moved, session.engine.state.actors[ME]) == 5
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and ENEMY == e.actor_id for e in events)
