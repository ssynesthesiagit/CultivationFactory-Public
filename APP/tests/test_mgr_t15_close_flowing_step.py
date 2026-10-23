"""Portable source-shaped Water import, native commits and cold continuations."""
import copy
import json
import zipfile
from pathlib import Path
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT=Path(__file__).resolve().parents[1]
FLOW='TAL_WATER_FLOWING_STEP'
RETURN='WATER_BASE_RETURN_THE_FLOW'
SHAPE='WATER_BASE_SHAPE_CURRENT'
ME,FOE='actor:factory.flow-owner','actor:factory.flow-foe'


def document(owned=True):
    return {'identity':{'display_name':'River Walker','cultivation_level':5,'proficiency_bonus':3,
                       'path':'Qi Cultivation','path_ids':['tianxia.path.qi_cultivation'],'key_ability':'CON'},
        'ability_scores_and_statistics':{
            'abilities':[{'ability':a,'score':16,'modifier':3} for a in ['STR','DEX','CON','INT','WIS','CHA']],
            'primary_resource':{'name':'Qi','maximum':20},'hit_points':{'maximum':100},
            'armor_class':{'base_value':14},'speed':{'walking_ft':30},
            'technique_save_dc':16,'technique_attack_bonus':6},
        'spheres_and_talents':{'sphere_record_ids':['tianxia.sphere.water'],
            'learned_talent_record_ids':[FLOW] if owned else [],
            'automatic_sphere_component_record_ids':[SHAPE,RETURN,'WATER_BASE_WATER_LASH']},
        'equipment':[{'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.bi_shou',
                                               'name':'Bi Shou (Dagger)','quantity':1}]}}]}


def scene(tmp_path,terrain=None,owned=True,regions=(),weather=False):
    combat=CombatService(ROOT,tmp_path); bundles=[]
    for aid in (ME,FOE):
        doc=document(owned if aid==ME else False)
        doc['identity']['display_name']='River Walker' if aid==ME else 'Dry Fighter'
        if weather and aid==FOE:
            doc['spheres_and_talents']['sphere_record_ids'].append('tianxia.sphere.weather')
            doc['spheres_and_talents']['automatic_sphere_component_record_ids'].append('WEATHER_BASE_GATHER_WEATHER')
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.');folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
        b=compile_character(doc,actor_id=aid,reaction_plan={'ask':True})
        # A generic fixture cause of Prone; never supplies the tested ability,
        # water, its result, its benefit or a successful receipt.
        action={'source_definition_id':'action:test.flow-trip.'+aid,'display_name':'Lie down','owner_id':aid,
                'economy':'NONE','target_kind':'SELF','resolution_kind':'TYPED','costs':[],
                'parameters':{'free_primary':True,'typed':{'source':'test:prone','effects':[
                    {'type':'condition','condition':'prone','applies_to':'self'}],
                    'numbers':{'cl':5,'pb':3,'key_mod':3},'riders':[]}}}
        b['action_catalog'].append(action);b['actor_template']['action_ids'].append(action['source_definition_id'])
        restriction=copy.deepcopy(action);restriction['source_definition_id']+='-restraint'
        restriction['display_name']='Fixture restraint'
        restriction['parameters']['typed']['effects']=[{'type':'condition','condition':'restrained','applies_to':'self'}]
        b['action_catalog'].append(restriction);b['actor_template']['action_ids'].append(restriction['source_definition_id'])
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b);bundles.append(b)
    arena=copy.deepcopy(combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'])
    arena['terrain_regions']=list(regions)
    arena['map_terrain']=[] if terrain is None or terrain in {'rain','wet ground'} else [{'terrain':terrain,'cells':[[3,6]]}]
    if terrain in {'rain','wet ground'}:
        arena['terrain_regions'].append({'region_id':'natural-environment','terrain_type':'OPEN','movement_cost':1,
            'material':terrain,'material_only':True,'cells':[{'x':3,'y':6}]})
    mid=combat._finish_factory_match(bundles,[ME,FOE],{ME:'team:a',FOE:'team:b'},
        {ME:{'x':3,'y':6},FOE:{'x':4,'y':6}},arena,[ME],[FOE],control_modes={ME:'MANUAL',FOE:'MANUAL'},
        match_seed='flow-native',maximum_rounds=12,display_name='Flowing Step regression')['match_id']
    turn(tmp_path,mid,ME);return mid


def engine(tmp_path,mid):return CombatService(ROOT,tmp_path)._load_session(mid).engine


def choose_action(tmp_path,mid,text,destination=None):
    return next(c for c in engine(tmp_path,mid).legal_candidates() if text in c.display_name
                and (destination is None or c.destination and (c.destination.x,c.destination.y)==destination))


def commit(tmp_path,mid,candidate=None,picks=None):
    combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path);view=table.state(mid);menu=view['menu']
    cid=candidate.candidate_id if candidate is not None else menu['end_turn']
    before=engine(tmp_path,mid).state.model_dump(mode='json');answers=[];prompts=[]
    for _ in range(30):
        combat=CombatService(ROOT,tmp_path);table=TabletopService(combat,tmp_path)
        result=table.act(mid,cid,menu['decision_id'],menu['state_version'],view['last_sequence'],answers)
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            assert combat.replay(mid)['status']=='PASS'
            assert combat.verify(mid)['status']=='PASS'
            assert combat._load_session(mid).engine.state.model_dump(mode='json')==engine(tmp_path,mid).state.model_dump(mode='json')
            return prompts
        assert engine(tmp_path,mid).state.model_dump(mode='json')==before
        p=result['reaction'];prompts.append(p);selection=picks(p) if picks else None
        answer={**p['context'],'selection':'USE' if selection else 'DECLINE'}
        if p.get('choice'):answer['option_ids']=selection or []
        answers.append(answer)
    raise AssertionError('choice did not settle')


def turn(tmp_path,mid,actor):
    for _ in range(8):
        if engine(tmp_path,mid).state.current_actor_id==actor:return
        commit(tmp_path,mid)
    raise AssertionError('turn did not advance')


@pytest.mark.parametrize('seat',['MANUAL','SUGGESTED'],ids=['manual','ask'])
def test_owned_return_offers_remote_self_target(tmp_path,seat):
    mid=scene(tmp_path)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Mist Basin',(9,6)))
    CombatService(ROOT,tmp_path).set_controller_mode(mid,actor_id=ME,controller_mode=seat)
    choices=[c for c in engine(tmp_path,mid).legal_candidates() if 'Return the Flow: Move an Ally + Flowing Step' in c.display_name]
    assert choices and all(c.target_ids in [(),(ME,)] for c in choices)
    old=engine(tmp_path,mid);basin=next(z for z in old.state.zones.values() if z.active and z.owner_id==ME)
    assert old.grid.distance_ft(old.state.actors[ME].position,basin.center)>5
    def pick(p):
        kind=p['context']['reaction_source_id']
        if kind.endswith('flowing_water'):return [basin.zone_id]
        if kind.endswith('flowing_destination'):
            assert len(p['choice']['options'])>16
            assert any('(4, 8)' in o['label'] for o in p['choice']['options'])
            return [next(o['id'] for o in p['choice']['options'] if '(3, 8)' in o['label'])]
        return None
    prompts=commit(tmp_path,mid,choices[0],pick);final=engine(tmp_path,mid)
    assert (final.state.actors[ME].position.x,final.state.actors[ME].position.y)==(3,8)
    assert final.state.zones[basin.zone_id].active
    assert final.state.actors[ME].movement_remaining_ft==old.state.actors[ME].movement_remaining_ft
    assert not final.state.actors[ME].bonus_action_available
    assert any('Flowing Step' in str(p) for p in prompts)


@pytest.mark.parametrize('terrain',['rain','courtyard mist','wet ground',None])
@pytest.mark.parametrize('owned',[True,False])
def test_natural_start_free_stand(tmp_path,terrain,owned):
    mid=scene(tmp_path,terrain,owned)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'));commit(tmp_path,mid);turn(tmp_path,mid,FOE)
    prompts=commit(tmp_path,mid,picks=lambda p:['stand'] if p['context']['reaction_source_id'].endswith('flowing_stand') else None)
    turn(tmp_path,mid,ME);final=engine(tmp_path,mid)
    stood=[e for e in final.events if e.event_type=='STOOD_UP' and e.actor_id==ME][-1]
    assert stood.payload['cost_ft']==(0 if owned and terrain else 15)
    assert final.state.actors[ME].movement_remaining_ft==(30 if owned and terrain else 15)
    if owned and terrain:
        assert any('Flowing Step' in str(p) and 'River Walker' in str(p) for p in prompts)
        commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'))
        commit(tmp_path,mid,choose_action(tmp_path,mid,'Stand up'))
        assert engine(tmp_path,mid).state.actors[ME].movement_remaining_ft==15
        # The consumed use renews only through another genuine owner start.
        commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'))
        commit(tmp_path,mid);turn(tmp_path,mid,FOE)
        commit(tmp_path,mid,picks=lambda p:['stand'] if
            p['context']['reaction_source_id'].endswith('flowing_stand') else None)
        turn(tmp_path,mid,ME)
        renewed=engine(tmp_path,mid)
        assert [e for e in renewed.events if e.event_type=='STOOD_UP' and e.actor_id==ME][-1].payload['cost_ft']==0
        assert renewed.state.actors[ME].movement_remaining_ft==30


@pytest.mark.parametrize('creator',[ME,FOE])
@pytest.mark.parametrize('form',['Cleansing Basin','Mist Basin'])
def test_owned_basin_free_stand_and_foreign_basin_negative(tmp_path,creator,form):
    mid=scene(tmp_path)
    turn(tmp_path,mid,creator)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: '+form,(3,6)))
    turn(tmp_path,mid,ME)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'));commit(tmp_path,mid)
    turn(tmp_path,mid,FOE)
    commit(tmp_path,mid,picks=lambda p:['stand'] if p['context']['reaction_source_id'].endswith('flowing_stand') else None)
    turn(tmp_path,mid,ME)
    stood=[e for e in engine(tmp_path,mid).events if e.event_type=='STOOD_UP' and e.actor_id==ME][-1]
    assert stood.payload['cost_ft']==(0 if creator==ME or form=='Mist Basin' else 15)


@pytest.mark.parametrize('decline_at',['water','destination'])
def test_return_decline_spends_only_bonus_action_and_keeps_water(tmp_path,decline_at):
    mid=scene(tmp_path)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Mist Basin',(9,6)))
    before=engine(tmp_path,mid);basin=next(z for z in before.state.zones.values() if z.active and z.owner_id==ME)
    def pick(p):
        if decline_at=='destination' and p['context']['reaction_source_id'].endswith('flowing_water'):return [basin.zone_id]
        return None
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Return the Flow: Move an Ally + Flowing Step'),pick)
    final=engine(tmp_path,mid)
    assert final.state.actors[ME].position==before.state.actors[ME].position
    assert final.state.actors[ME].resources==before.state.actors[ME].resources
    assert final.state.zones[basin.zone_id].model_dump()==before.state.zones[basin.zone_id].model_dump()
    assert not final.state.actors[ME].bonus_action_available
    assert not any('Return the Flow: Move an Ally + Flowing Step' in c.display_name for c in final.legal_candidates())


def test_dry_start_cannot_gain_free_stand_by_entering_mist_later(tmp_path):
    mid=scene(tmp_path)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Mist Basin',(3,6)))
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'))
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Stand up'))
    assert engine(tmp_path,mid).state.actors[ME].movement_remaining_ft==15


def test_free_stand_can_be_declined_without_spending_movement(tmp_path):
    mid=scene(tmp_path,'courtyard mist')
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'));commit(tmp_path,mid);turn(tmp_path,mid,FOE)
    prompts=commit(tmp_path,mid);turn(tmp_path,mid,ME)
    final=engine(tmp_path,mid)
    assert any(p['context']['reaction_source_id'].endswith('flowing_stand') for p in prompts)
    assert any(c.expires_on=='STAND_UP' for c in final.state.actors[ME].conditions.values())
    assert final.state.actors[ME].movement_remaining_ft==30


@pytest.fixture(autouse=True)
def native_registry_dependency():
    # Explicit dynamic registry dependency for the approved public exporter.
    rows=json.loads((ROOT / 'combat/rules/feature_blocks.d/water_flowing_step.json').read_text())
    assert rows['features'][FLOW]['kind']=='flowing_step'
    reviewed=json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/water_flowing_step.json').read_text())
    assert reviewed['mechanics'][FLOW]['modifier']['targets']==['Return the Flow: Move an Ally']


def flow_pick(basin,destination=(3,8)):
    def pick(p):
        kind=p['context']['reaction_source_id']
        if kind.endswith('flowing_water'):return [basin.zone_id]
        if kind.endswith('flowing_destination'):
            return [next(o['id'] for o in p['choice']['options'] if str(destination) in o['label'])]
        return None
    return pick


@pytest.mark.parametrize('water',['dry','owner_current','owner_basin','foreign_basin','soaked'])
def test_only_eligible_attackers_lose_opportunity_attacks(tmp_path,water):
    mid=scene(tmp_path)
    if water=='foreign_basin':
        turn(tmp_path,mid,FOE)
        commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Cleansing Basin',(4,6)))
        commit(tmp_path,mid);turn(tmp_path,mid,ME)
    if water=='soaked':
        # Actual Water Lash hit is the native producer of Soaked.
        commit(tmp_path,mid,choose_action(tmp_path,mid,'Water Lash'))
        commit(tmp_path,mid);turn(tmp_path,mid,ME)
        assert any(c.condition_id.startswith('condition:typed.mark.soaked.')
                   for c in engine(tmp_path,mid).state.actors[FOE].conditions.values())
    name='Shape Current: Flowing Current' if water=='owner_current' else 'Shape Current: Cleansing Basin'
    location=(4,6) if water in ['owner_current','owner_basin'] else (9,6)
    commit(tmp_path,mid,choose_action(tmp_path,mid,name,location))
    before=engine(tmp_path,mid);basin=next(z for z in before.state.zones.values() if z.active and z.owner_id==ME)
    base_pick=flow_pick(basin)
    def pick(p):
        if p['context'].get('reactor_id')==FOE:
            return [p['choice']['options'][0]['id']] if p.get('choice') else ['use']
        return base_pick(p)
    prompts=commit(tmp_path,mid,choose_action(tmp_path,mid,'Return the Flow: Move an Ally + Flowing Step'),pick)
    oa=[p for p in prompts if p['context'].get('reactor_id')==FOE]
    assert bool(oa)==(water in ['dry','foreign_basin'])
    final=engine(tmp_path,mid)
    assert (final.state.actors[ME].position.x,final.state.actors[ME].position.y)==(3,8)
    assert final.state.actors[FOE].reaction_available==(water not in ['dry','foreign_basin'])
    assert final.state.zones[basin.zone_id].active


def test_foreign_water_does_not_supply_return_target(tmp_path):
    mid=scene(tmp_path);turn(tmp_path,mid,FOE)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Mist Basin',(9,6)))
    commit(tmp_path,mid);turn(tmp_path,mid,ME)
    assert not any('Return the Flow: Move an Ally + Flowing Step' in c.display_name
                   for c in engine(tmp_path,mid).legal_candidates())


def test_spent_normal_movement_does_not_spend_the_return_grant(tmp_path):
    mid=scene(tmp_path)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Mist Basin',(9,6)))
    move=next(c for c in engine(tmp_path,mid).legal_candidates() if c.kind=='MOVE'
              and c.destination and (c.destination.x,c.destination.y)==(3,12))
    commit(tmp_path,mid,move)
    before=engine(tmp_path,mid);assert before.state.actors[ME].movement_remaining_ft==0
    basin=next(z for z in before.state.zones.values() if z.active and z.owner_id==ME)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Return the Flow: Move an Ally + Flowing Step'),flow_pick(basin,(3,10)))
    after=engine(tmp_path,mid)
    assert after.state.actors[ME].position.y==10
    assert after.state.actors[ME].movement_remaining_ft==0


class FakeModel:
    """Only selects from the creature-permitted native decision frame."""
    def __init__(self,source):self.source=source;self.frames=[]
    def status(self):return {'ready':True,'provider_id':'fixture-model'}
    def complete_json(self,*,prompt_text,system_message,purpose):
        assert purpose=='combat_decision'
        frame=json.loads(prompt_text.split('\n\n',1)[1]);self.frames.append(frame)
        selected=next(c for c in frame['legal_candidates'] if self.source in c['display_name'])
        payload={k:frame[k] for k in ['decision_id','state_version']}
        payload.update(actor_id=frame['active_actor_id'],**{k:selected[k] for k in
            ['candidate_id','target_ids','destination','option_ids']})
        return {'provider_id':'fixture-model','model':'fake-no-network',
                'value':{'schema':'TianxiaFactoryCombatAIIntent.v1','action_intent':payload}}


def automatic_commit(tmp_path,mid,fake,picks=None):
    combat=CombatService(ROOT,tmp_path,ai_provider=fake)
    table=TabletopService(combat,tmp_path);view=table.state(mid);menu=view['menu']
    before=engine(tmp_path,mid).state.model_dump(mode='json');answers=[];prompts=[]
    for _ in range(20):
        combat=CombatService(ROOT,tmp_path,ai_provider=fake);table=TabletopService(combat,tmp_path)
        result=table.auto_step(mid,view['last_sequence'],answers,menu['decision_id'],menu['state_version'])
        if result['status']!='REACTION_REQUIRED':
            assert result['status']=='COMMITTED',result
            assert combat.replay(mid)['status']=='PASS'
            assert combat.verify(mid)['status']=='PASS'
            assert combat._load_session(mid).engine.state.model_dump(mode='json')==engine(tmp_path,mid).state.model_dump(mode='json')
            return prompts
        assert engine(tmp_path,mid).state.model_dump(mode='json')==before
        p=result['reaction'];prompts.append(p);selection=picks(p) if picks else None
        answer={**p['context'],'selection':'USE' if selection else 'DECLINE'}
        if p.get('choice'):answer['option_ids']=selection or []
        answers.append(answer)
    raise AssertionError('automatic choice did not settle')


def test_automatic_return_uses_fake_model_and_retains_manual_oa(tmp_path):
    mid=scene(tmp_path)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Mist Basin',(9,6)))
    combat=CombatService(ROOT,tmp_path);combat.set_controller_mode(mid,actor_id=ME,controller_mode='API_AUTO')
    before=engine(tmp_path,mid);fake=FakeModel('Return the Flow: Move an Ally + Flowing Step')
    prompts=automatic_commit(tmp_path,mid,fake)
    final=engine(tmp_path,mid)
    assert len(fake.frames)==1
    assert any(p['context']['reactor_id']==FOE for p in prompts)
    assert final.state.actors[ME].position!=before.state.actors[ME].position
    assert final.state.actors[ME].movement_remaining_ft==before.state.actors[ME].movement_remaining_ft


@pytest.mark.parametrize('accept',[True,False])
def test_player_free_stand_on_automatic_turn_end_cold_provider_continuation(tmp_path,accept):
    mid=scene(tmp_path,'courtyard mist')
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'));commit(tmp_path,mid);turn(tmp_path,mid,FOE)
    combat=CombatService(ROOT,tmp_path);combat.set_controller_mode(mid,actor_id=FOE,controller_mode='API_AUTO')
    fake=FakeModel('End turn')
    prompts=automatic_commit(tmp_path,mid,fake,lambda p:['stand'] if accept and
        p['context']['reaction_source_id'].endswith('flowing_stand') else None)
    final=engine(tmp_path,mid)
    assert len(fake.frames)==1
    assert any(p['context']['reactor_id']==ME and 'Flowing Step' in str(p) for p in prompts)
    assert bool([c for c in final.state.actors[ME].conditions.values() if c.expires_on=='STAND_UP'])!=accept
    assert final.state.actors[ME].movement_remaining_ft==30


def test_native_catalog_initial_acquisition_and_source_identity():
    from hashlib import sha256
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    from combat import table_advance
    row=CanonicalCatalogAuthorityService(ROOT).get_talent(FLOW)
    assert sha256(row['full_exact_source_text'].encode()).hexdigest()=='89d5a8d254499f7d90e0557e5091d418d63ffb59e7a919b26a60b4798bcc6e3d'
    assert row['minimum_cl']==1 and row['realm_band']=='Mortal' and row['access_category']=='Open'
    doc=document(False);doc['identity']['path_ids']=['tianxia.path.qi_cultivation']
    have=table_advance.known(doc)
    assert table_advance.talent_status(row,have)=={'legal':True,'gm':False,'reasons':[]}
    have['spheres']=set()
    assert not table_advance.talent_status(row,have)['legal']
    assert table_advance.sphere_status('tianxia.sphere.water',have)=={'legal':True,'gm':False,'reasons':[]}


def test_return_does_not_bypass_sealed_wall_or_terrain_prices(tmp_path):
    wall={'region_id':'sealed-wall','terrain_type':'BLOCKED','movement_cost':0,
          'cells':[{'x':x,'y':7} for x in range(20)]}
    ground={'region_id':'rough-ground','terrain_type':'DIFFICULT','movement_cost':2,
            'cells':[{'x':x,'y':y} for x in range(1,6) for y in range(4,7)]}
    mid=scene(tmp_path,regions=[wall,ground])
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Mist Basin',(9,6)))
    before=engine(tmp_path,mid);basin=next(z for z in before.state.zones.values() if z.active and z.owner_id==ME)
    def pick(p):
        kind=p['context']['reaction_source_id']
        if kind.endswith('flowing_water'):return [basin.zone_id]
        if kind.endswith('flowing_destination'):
            labels=[o['label'] for o in p['choice']['options']]
            assert not any('(3, 8)' in x or '(3, 4)' in x or '(3, 7)' in x for x in labels)
            return [next(o['id'] for o in p['choice']['options'] if '(3, 5)' in o['label'])]
        return None
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Return the Flow: Move an Ally + Flowing Step'),pick)
    final=engine(tmp_path,mid)
    move=[e for e in final.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==ME][-1]
    assert move.payload['granted_cost_ft']==10
    assert final.state.actors[ME].position.y==5
    assert final.state.actors[ME].movement_remaining_ft==before.state.actors[ME].movement_remaining_ft


def test_restraint_prevents_return_movement_and_free_standing(tmp_path):
    mid=scene(tmp_path,'courtyard mist')
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Mist Basin',(9,6)))
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Fixture restraint'))
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'))
    before=engine(tmp_path,mid);basin=next(z for z in before.state.zones.values() if z.active and z.owner_id==ME)
    prompts=commit(tmp_path,mid,choose_action(tmp_path,mid,'Return the Flow: Move an Ally + Flowing Step'),flow_pick(basin))
    assert not any(p['context']['reaction_source_id'].endswith('flowing_destination') for p in prompts)
    final=engine(tmp_path,mid)
    assert final.state.actors[ME].position==before.state.actors[ME].position
    assert not any(c.source_definition_id=='system:combat.stand_up' for c in final.legal_candidates())
    commit(tmp_path,mid);turn(tmp_path,mid,ME)
    assert any(c.expires_on=='STAND_UP' for c in engine(tmp_path,mid).state.actors[ME].conditions.values())


def test_return_water_range_is_sixty_feet_and_does_not_follow_owner(tmp_path):
    mid=scene(tmp_path)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Shape Current: Mist Basin',(15,6)))
    before=engine(tmp_path,mid)
    basin=next(z for z in before.state.zones.values() if z.active and z.owner_id==ME)
    assert before.grid.distance_ft(before.state.actors[ME].position,basin.center)==60
    assert any('Return the Flow: Move an Ally + Flowing Step' in c.display_name for c in before.legal_candidates())
    move=next(c for c in before.legal_candidates() if c.kind=='MOVE' and c.destination
              and (c.destination.x,c.destination.y)==(0,6))
    commit(tmp_path,mid,move)
    after=engine(tmp_path,mid)
    assert after.grid.distance_ft(after.state.actors[ME].position,after.state.zones[basin.zone_id].center)>60
    assert not any('Return the Flow: Move an Ally + Flowing Step' in c.display_name for c in after.legal_candidates())


@pytest.mark.parametrize('sign',['rain','dry'])
def test_actual_gathered_weather_supplies_rain_not_dry(tmp_path,sign):
    mid=scene(tmp_path,weather=True)
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'));commit(tmp_path,mid);turn(tmp_path,mid,FOE)
    def gather(p):
        source=p['context']['reaction_source_id']
        if source.endswith('weather_field_gather_sign'):return [sign]
        if 'weather_field_severity_' in source:return ['1']
        return None
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Gather Weather',(3,6)),gather)
    e=engine(tmp_path,mid)
    assert any(z.active and (z.trigger_profile.get('profile') or {}).get('signs')=={sign:1}
               for z in e.state.zones.values())
    prompts=commit(tmp_path,mid,picks=lambda p:['stand'] if
        p['context']['reaction_source_id'].endswith('flowing_stand') else None)
    turn(tmp_path,mid,ME)
    final=engine(tmp_path,mid)
    stood=[e for e in final.events if e.event_type=='STOOD_UP' and e.actor_id==ME][-1]
    assert stood.payload['cost_ft']==(0 if sign=='rain' else 15)
    assert any('Flowing Step' in str(p) for p in prompts)==(sign=='rain')


def test_wet_start_while_upright_does_not_grant_a_later_free_stand(tmp_path):
    mid=scene(tmp_path,'courtyard mist')
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Lie down'))
    commit(tmp_path,mid,choose_action(tmp_path,mid,'Stand up'))
    final=engine(tmp_path,mid)
    assert final.state.actors[ME].movement_remaining_ft==15
    assert [e for e in final.events if e.event_type=='STOOD_UP' and e.actor_id==ME][-1].payload['cost_ft']==15
