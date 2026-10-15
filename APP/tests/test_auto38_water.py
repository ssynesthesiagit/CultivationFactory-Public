"""Water's paid hit, chosen burst and post-damage defense in committed fights."""
from copy import deepcopy
import pytest
from combat.canonical import canonical_sha256
from tests.worker2_support import (OWNER,ALLY,FOE,fixture,candidate,act,
                                   settle,turn,reload)
from tests.test_carry import KIT
WHIP='TAL_WATER_WATER_WHIP'
WAVE='TAL_WATER_WAVE_BURST'
SHIELD='TAL_WATER_WATER_SHIELD'


def prepare(bundles,save=-100,attack=100,escape=100,rooted=False,area=False,fragile=False):
    for b in bundles:
        if b['actor_id']==FOE:
            b['actor_template']['saving_throws']['STR']=save
        for a in b['action_catalog']:
            t=a.get('parameters',{}).get('typed',{})
            if t.get('source')=='WATER_BASE_WATER_LASH': t['numbers']['attack_bonus']=attack
            if b['actor_id']==FOE and t.get('weapon'):
                t['numbers']['attack_bonus']=100
                for eff in t.get('effects',[]):
                    for hit in eff.get('on_hit',[]):
                        if hit['type']=='damage':
                            hit.pop('weapon_damage',None)
                            hit.update(dice=None,flat=30,formula='none',damage_types=['piercing'])
            if b['actor_id']==FOE and a['display_name']=='Escape grapple': t['numbers']['escape_bonus']=escape
        if b['actor_id']==OWNER:
            if fragile: b['actor_template']['maximum_hp']=1
            base=next((a for a in b['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('source')=='WATER_BASE_WATER_LASH'),None)
            if base:
                soak=deepcopy(base)
                soak.update(source_definition_id='action:test.water_soak',display_name='Fixture soak',economy='NONE',target_kind='ANY_CREATURE')
                soak['parameters']={'typed':{'source':'test_water_soak','effects':[{'type':'mark','mark':'Soaked','applies_to':'target','duration':{'kind':'until_end_of_your_next_turn'}}],
                                            'numbers':deepcopy(base['parameters']['typed']['numbers']),'duration':{'kind':'instant'},'riders':[]},'expected_damage':0}
                if rooted:
                    soak['parameters']['typed']['effects'] += [{'type':'condition','condition':name,'applies_to':'target','duration':'until_end_of_your_next_turn'} for name in ['restrained','prone']]
                b['action_catalog'].append(soak)
                b['actor_template']['action_ids'].append(soak['source_definition_id'])
        if b['actor_id']==FOE and area:
            spell=deepcopy(next(a for owner in bundles if owner['actor_id']==OWNER for a in owner['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('source')=='WATER_BASE_WATER_LASH'))
            spell.update(owner_id=FOE,source_definition_id='action:test.water_area',display_name='Fixture area damage',target_kind='CELL',range_ft=60,radius_ft=10)
            spell['parameters']={'typed':{'source':'test_water_area','area':{'shape':'sphere','size_ft':10},'duration':{'kind':'instant'},
                'numbers':deepcopy(spell['parameters']['typed']['numbers']),'riders':[],
                'effects':[{'type':'rider_choose_area_recipients','cast_only':True},{'type':'damage','applies_to':'creatures_in_area','flat':30,'formula':'none','damage_types':['bludgeoning']}]},'expected_damage':30}
            b['action_catalog'].append(spell);b['actor_template']['action_ids'].append(spell['source_definition_id'])
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)


def soaked(actor):
    return any(c.condition_id.startswith('condition:typed.mark.soaked.') for c in actor.conditions.values())


@pytest.mark.parametrize('case',['hold','decline','save','miss'])
def test_water_whip_pays_only_after_hit_and_expires_on_caster_next_end(tmp_path,case):
    combat,table,mid=fixture(tmp_path,[WHIP],bundle_transform=lambda b:prepare(b,save=100 if case=='save' else -100,attack=-100 if case=='miss' else 100))
    prompts=settle(table,mid,candidate(combat,mid,'Water Lash',target=FOE).candidate_id,{'choice:needle.water_whip':None if case=='decline' else 'use'})
    e=reload(tmp_path,mid)
    held=[c for c in e.state.actors[FOE].conditions.values() if c.condition_id=='condition:typed.grappled']
    assert bool(held)==(case=='hold')
    assert e.state.actors[OWNER].resources['resource:core.qi']==(99 if case in ['hold','save'] else 100)
    assert any(p['context']['reaction_source_id']=='choice:needle.water_whip' for p in prompts)==(case!='miss')
    if held:
        assert held[0].data['escape_dc']==16 and 'reach_ft' not in held[0].data
        assert held[0].expires_on=='END_OF_SOURCE_TURN_AT:2'
        assert soaked(e.state.actors[FOE])
        c=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination.x==2 and c.destination.y==6 and c.destination.z==0)
        settle(table,mid,c.candidate_id)
        e=reload(tmp_path,mid)
        assert e.state.actors[OWNER].movement_remaining_ft==25
        assert (e.state.actors[FOE].position.x,e.state.actors[FOE].position.y)==(6,6)
        turn(table,mid,FOE)
        assert any(c.condition_id=='condition:typed.grappled' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
        turn(table,mid,OWNER)
        assert any(c.condition_id=='condition:typed.grappled' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())
        settle(table,mid,table.state(mid)['menu']['end_turn'])
        assert not any(c.condition_id=='condition:typed.grappled' for c in reload(tmp_path,mid).state.actors[FOE].conditions.values())


def test_water_whip_native_action_escape_uses_cultivation_dc(tmp_path):
    combat,table,mid=fixture(tmp_path,[WHIP],bundle_transform=prepare)
    settle(table,mid,candidate(combat,mid,'Water Lash',target=FOE).candidate_id)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Escape grapple',target=FOE).candidate_id)
    e=reload(tmp_path,mid)
    assert not any(c.condition_id=='condition:typed.grappled' for c in e.state.actors[FOE].conditions.values())
    assert not e.state.actors[FOE].action_available
    check=next(ev for ev in reversed(e.events) if ev.event_type=='CHECK_ROLLED' and ev.actor_id==FOE)
    assert check.payload['dc']==16 and check.payload['success']


@pytest.mark.parametrize('success',[False,True])
def test_wave_burst_chooses_recipients_and_pushes_once_from_center(tmp_path,success):
    combat,table,mid=fixture(tmp_path,[WAVE],bundle_transform=lambda b:prepare(b,save=100 if success else -100))
    e=reload(tmp_path,mid)
    assert not any('Wave Burst' in a.display_name and 'Flowing Current' not in a.display_name for a in e.action_catalog.values())
    c=candidate(combat,mid,'Shape Current: Flowing Current + Wave Burst',at=(5,5))
    assert act(table,mid,c.candidate_id)['status']=='REACTION_REQUIRED'
    prompts=settle(table,mid,c.candidate_id,{'choice:needle.area_recipients':[FOE]})
    assert any(p['context']['reaction_source_id']=='choice:needle.area_recipients' for p in prompts)
    e=reload(tmp_path,mid)
    assert soaked(e.state.actors[FOE]) and not soaked(e.state.actors[ALLY])
    assert (e.state.actors[FOE].position.x,e.state.actors[FOE].position.y)==((6,6) if success else (8,8))
    assert (e.state.actors[ALLY].position.x,e.state.actors[ALLY].position.y)==(4,6)
    assert len([v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==FOE])==1
    zones=[z for z in e.state.zones.values() if z.active and z.owner_id==OWNER]
    assert len(zones)==1 and e.action_catalog[zones[0].source_definition_id].parameters['typed']['area']=={
        'shape':'sphere','size_ft':10,'recipients':'all','harmful_recipients':'all',
        'include_self':True,'exclude_self':False}
    turn(table,mid,FOE)
    assert len([v for v in reload(tmp_path,mid).events if v.event_type=='SAVE_ROLLED' and v.actor_id==FOE])==1


@pytest.mark.parametrize('contact,cl,target,accept',[
    ('soaked',1,ALLY,True),('basin',11,OWNER,True),('dry',17,OWNER,True),('soaked',17,OWNER,False),('held',11,ALLY,True),('fallen',1,OWNER,True)])
def test_water_shield_reduces_attack_then_moves_without_spending_movement(tmp_path,contact,cl,target,accept):
    combat,table,mid=fixture(tmp_path,[SHIELD],cl=cl,foe_position={'x':3,'y':5},foe_kit={'starting_kit':{'items':[KIT['items'][-1]]}},bundle_transform=lambda b:prepare(b,rooted=contact=='held',fragile=contact=='fallen'))
    if contact in ['soaked','held','fallen']: settle(table,mid,candidate(combat,mid,'Fixture soak',target=target).candidate_id)
    elif contact=='basin': settle(table,mid,candidate(combat,mid,'Shape Current: Mist Basin',at=(3,6)).candidate_id)
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.model_dump(mode='json')
    c=candidate(combat,mid,'Bi Shou (Dagger) attack',target=target)
    assert act(table,mid,c.candidate_id)['status']=='REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json')==before
    dest='step:4,7' if target==ALLY else 'step:3,7'
    prompts=settle(table,mid,c.candidate_id,{'choice:needle.water_shield':'use' if accept else None,'choice:needle.water_shield_step':dest})
    e=reload(tmp_path,mid)
    assert any(p['context']['reactor_id']==OWNER and p['context']['reaction_source_id']=='choice:needle.water_shield' for p in prompts)
    move=accept and contact!='dry'
    assert any(p['context']['reaction_source_id']=='choice:needle.water_shield_step' for p in prompts)==move
    assert e.state.actors[OWNER].reaction_available is (not accept)
    assert e.state.actors[OWNER].resources['resource:core.qi']==100-int(accept)-int(contact=='basin')
    if contact=='fallen':
        assert e.state.actors[target].current_hp==0
        assert e.state.actors[target].movement_remaining_ft==0  # Native defeat clears the ordinary allowance.
    else:
        assert e.state.actors[target].movement_remaining_ft==before['actors'][target]['movement_remaining_ft']
    assert e.state.actors[target].position.y==(7 if move else 6)
    if contact=='held':
        assert e._effective_speed(e.state.actors[target])==0
        assert any(c.condition_id=='condition:typed.prone' for c in e.state.actors[target].conditions.values())
    assert not any(k.startswith('auto38_shield_pending:') for k in e.state.actors[OWNER].turn_flags)
    if accept:
        die=next(v for v in e.events if v.event_type=='DAMAGE_ROLLED' and v.source_definition_id==SHIELD)
        assert die.payload['expression']==f'{3 if cl>=17 else 2 if cl>=11 else 1}d10+2'
        reaction=next(v for v in e.events if v.event_type=='REACTION_RESOLVED' and v.source_definition_id==SHIELD)
        assert e.state.actors[target].current_hp==max(0,before['actors'][target]['current_hp']-reaction.payload['pending_after'])
        if move:
            damage=next(v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.target_ids==(target,))
            step=next(v for v in e.events if v.event_type=='MOVEMENT_COMMITTED' and v.source_definition_id==SHIELD)
            assert damage.sequence<step.sequence
            assert not any('opportunity' in p['context']['reaction_source_id'] for p in prompts)


def test_water_shield_protects_area_damage_without_an_attack(tmp_path):
    combat,table,mid=fixture(tmp_path,[SHIELD],foe_position={'x':3,'y':5},bundle_transform=lambda b:prepare(b,area=True))
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Fixture area damage',at=(3,6)).candidate_id,
                   {'choice:needle.area_recipients':[OWNER],'choice:needle.water_shield':'use'})
    assert any(p['context']['reaction_source_id']=='choice:needle.water_shield' for p in prompts)
    e=reload(tmp_path,mid)
    receipt=next(v for v in e.events if v.event_type=='REACTION_RESOLVED' and v.source_definition_id==SHIELD)
    assert receipt.payload['pending_before']==30
    assert e.state.actors[OWNER].current_hp==60-receipt.payload['pending_after']
    assert e.state.actors[OWNER].resources['resource:core.qi']==99


def test_water_shield_is_inert_without_its_compiled_owned_row(tmp_path):
    combat,table,mid=fixture(tmp_path,[],foe_position={'x':3,'y':5},foe_kit={'starting_kit':{'items':[KIT['items'][-1]]}},bundle_transform=prepare)
    turn(table,mid,FOE)
    prompts=settle(table,mid,candidate(combat,mid,'Bi Shou (Dagger) attack',target=OWNER).candidate_id)
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.water_shield') for p in prompts)
    e=reload(tmp_path,mid)
    assert not any(v.source_definition_id==SHIELD for v in e.events)
    assert e.state.actors[OWNER].resources['resource:core.qi']==100
