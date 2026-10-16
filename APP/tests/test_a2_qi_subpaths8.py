"""Qi Subpaths 8: real table commits, session execute_intent and cold replay."""
import pytest
from combat.canonical import canonical_sha256
from combat.gate5_service import CombatService
from tests import r1i_service_support as s
from tests.h1_support import ROOT
from combat.ext import furnace_core as core, shugenja_prayer as prayer


def seal(bundle):
    bundle.pop('bundle_sha256',None)
    bundle['bundle_sha256']=canonical_sha256(bundle)


def prepare(*, success=False, with_core=False):
    def transform(bundles):
        for b in bundles:
            if b['actor_id'] != s.OWNER:
                if success:
                    b['actor_template']['saving_throws']={k:100 for k in ('STR','DEX','CON','INT','WIS','CHA')}
            elif with_core:
                next(r for r in b['actor_template']['resources'] if r['resource_id']==core.DEVIL)['initial']=3
            seal(b)
    return transform


def cold(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    return session.engine


def choose(send,cid, *, patron='air', amount='2', motion='temp_hp', damage_type=None, terrain='temp_hp', movement=None):
    answers=[]
    for _ in range(16):
        result=send(cid,answers)
        if result['status']=='COMMITTED': return result
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction']
        answer={**prompt['context'],'selection':'DECLINE'}
        if prompt.get('choice') and not ('shugenja_terrain_confirm' in prompt['context']['checkpoint'] and terrain == 'decline'):
            opts=prompt['choice']['options']
            checkpoint=prompt['context']['checkpoint']
            wanted=(movement if 'RIDER_STEP' in checkpoint else patron if 'shugenja_patron' in checkpoint else amount if 'furnace_payment' in checkpoint
                    else terrain if 'shugenja_terrain_benefit' in checkpoint else damage_type if 'shugenja_damage' in checkpoint else motion if 'furnace_motion' in checkpoint else 'push' if 'shugenja_water' in checkpoint else None)
            option=next((o for o in opts if o['id']==wanted or o['id'].endswith(':'+str(wanted))),None)
            if option is None: option=opts[0]
            answer.update(selection='USE',option_ids=[option['id']])
        answers.append(answer)
    raise AssertionError('too many choices')


@pytest.mark.parametrize('patron',prayer.PATRONS)
@pytest.mark.parametrize('success',[False,True])
def test_prayer_uses_only_the_patron_delivery_and_rider_after_reload(tmp_path,patron,success):
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER],owner_dc=50,
        bundle_transform=prepare(success=success),patron=patron,seed='A2GQISUB8-'+patron)
    initial=combat._load_session(mid).engine
    start=len(initial.events)
    before=initial.state.actors[s.FOE].current_hp
    choose(send,s.candidate(table,mid,'Elemental Prayer',s.FOE),patron=patron)
    engine=cold(tmp_path,mid)
    actor,foe=engine.state.actors[s.OWNER],engine.state.actors[s.FOE]
    assert prayer.patron(actor)==patron
    assert actor.resources[core.QI]==29
    events=engine.events[start:]
    attacks=[e for e in events if e.event_type=='ATTACK_ROLLED']
    saves=[e for e in events if e.event_type=='SAVE_ROLLED']
    attack=patron in ('air','lightning','metal')
    assert bool(attacks)==attack
    assert bool(saves)==(not attack)
    if saves: assert saves[0].payload['reason'].endswith(':'+prayer.SAVES[patron])
    damage=[e for e in events if e.event_type=='DAMAGE_COMMITTED']
    assert damage and {e.payload['damage_type'] for e in damage}=={prayer.TYPES[patron].upper()}
    rolls=[e for e in events if e.event_type=='DAMAGE_ROLLED']
    assert len(rolls)==1 and '4d8' in rolls[0].payload['expression']
    assert foe.current_hp < before
    expected_rider=attack or not success
    conds={c.condition_id for c in foe.conditions.values()}
    assert ('condition:typed.prone' in conds)==(patron=='earth' and expected_rider)
    assert ('condition:typed.reaction_denied' in conds)==(patron in ('fire','lightning') and expected_rider)
    assert engine._effective_speed(foe)==(20 if patron=='cold' and expected_rider else 30)
    woody=[z for z in engine.state.zones.values() if z.active and (z.trigger_profile.get('profile') or {}).get('shugenja_wood')]
    assert bool(woody)==(patron=='wood' and expected_rider)
    if woody:
        assert [(p.x,p.y) for p in woody[0].affected_cells]==[(4,6)]
        assert woody[0].trigger_profile['difficult']=='all'
    if success and not attack:
        assert before-foe.current_hp==int(rolls[0].payload['total'])//2


def test_furnace_split_spends_devil_qi_and_grants_one_motion_on_real_commit(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[core.CORE,prayer.PRAYER],bundle_transform=prepare(with_core=True),patron='fire')
    engine=cold(tmp_path,mid)
    assert core.DEVIL in engine.state.actors[s.OWNER].resources
    choose(send,s.candidate(table,mid,'Second Furnace: choose Qi payment'))
    cold(tmp_path,mid)
    choose(send,s.candidate(table,mid,'Elemental Prayer',s.FOE),patron='fire')
    engine=cold(tmp_path,mid)
    owner=engine.state.actors[s.OWNER]
    assert owner.resources[core.QI]==30 and owner.resources[core.DEVIL]==2
    assert owner.temporary_hp==4
    receipts=[e for e in engine.events if e.event_type=='ALTERNATIVE_PAYMENT_COMMITTED']
    assert len(receipts)==1
    assert owner.turn_flags['typed_once_turn:furnace_motion:temp_hp']


def test_furnace_zero_setting_keeps_ordinary_payment(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[core.CORE,prayer.PRAYER],bundle_transform=prepare(with_core=True),patron='fire')
    choose(send,s.candidate(table,mid,'Second Furnace: choose Qi payment'),amount='0')
    choose(send,s.candidate(table,mid,'Elemental Prayer',s.FOE),patron='fire')
    engine=cold(tmp_path,mid)
    owner=engine.state.actors[s.OWNER]
    assert owner.resources[core.QI]==29 and owner.resources[core.DEVIL]==3
    assert owner.temporary_hp==0
    assert not any(e.event_type=='ALTERNATIVE_PAYMENT_COMMITTED' for e in engine.events)


def test_wood_terrain_ends_at_owner_start_after_other_creatures_turns(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER],owner_dc=50,patron='wood')
    choose(send,s.candidate(table,mid,'Elemental Prayer',s.FOE),patron='wood')
    cold(tmp_path,mid)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != s.OWNER:
        assert any(z.active and z.trigger_profile.get('profile',{}).get('shugenja_wood') for z in cold(tmp_path,mid).state.zones.values())
        commit(table.state(mid)['menu']['end_turn'])
    assert not any(z.active and z.trigger_profile.get('profile',{}).get('shugenja_wood') for z in cold(tmp_path,mid).state.zones.values())


def test_wood_prayer_covers_large_target_footprint_after_cold_reload(tmp_path,monkeypatch):
    from combat.footprints import ActorFootprintDefinition
    from combat.footprint_registry import ACTOR_FOOTPRINTS
    monkeypatch.setitem(ACTOR_FOOTPRINTS,s.FOE,ActorFootprintDefinition.rectangle(2,2,
        footprint_id='test:a2gqisub8.large-foe',source_definition_id='test:a2gqisub8.large-foe'))
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER],patron='wood',wide=True,
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':8,'y':6},s.SECOND:{'x':12,'y':6}})
    choose(send,s.candidate(table,mid,'Elemental Prayer',s.FOE),patron='wood')
    engine=cold(tmp_path,mid); foe=engine.state.actors[s.FOE]
    assert engine._footprint(foe).width_cells==2
    zone=next(z for z in engine.state.zones.values() if z.active and (z.trigger_profile.get('profile') or {}).get('shugenja_wood'))
    assert {(p.x,p.y) for p in zone.affected_cells}=={(8,6),(9,6),(8,7),(9,7)}
    from combat import zones
    assert set(engine.grid.footprint_cells(foe.position,engine._footprint(foe))) <= zones.difficult_cells(engine,foe)


@pytest.mark.parametrize(('cl','dice'),[(3,'2d8'),(11,'3d8')])
def test_prayer_damage_scales_at_cl3_and_cl11_after_service_reload(tmp_path,cl,dice):
    def set_cl(bundles):
        owner=next(b for b in bundles if b['actor_id']==s.OWNER)
        for action in owner['action_catalog']:
            if prayer.PRAYER in action['source_definition_id']:
                action['parameters']['typed']['numbers']['cl']=cl
        seal(owner)
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER],patron='air',bundle_transform=set_cl)
    choose(send,s.candidate(table,mid,'Elemental Prayer',s.FOE),patron='air')
    engine=cold(tmp_path,mid)
    rolls=[e for e in engine.events if e.event_type=='DAMAGE_ROLLED']
    assert len(rolls)==1 and dice in rolls[0].payload['expression']


def test_metal_prayer_ignores_half_cover_on_service_attack_after_reload(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER],patron='metal',wide=True,
        positions={s.OWNER:{'x':3,'y':6},s.FOE:{'x':8,'y':6},s.SECOND:{'x':12,'y':6}},
        map_terrain=[{'type':'SIMPLE_COVER','cells':[[5,6]]}])
    before=cold(tmp_path,mid)
    assert before.grid.cover_bonus(before.state.actors[s.OWNER].position,before.state.actors[s.FOE].position)==2
    choose(send,s.candidate(table,mid,'Elemental Prayer',s.FOE),patron='metal')
    engine=cold(tmp_path,mid)
    attack=next(e for e in reversed(engine.events) if e.event_type=='ATTACK_ROLLED' and e.target_ids==(s.FOE,))
    assert attack.payload.get('cover_bonus')==0


def test_prayer_automatic_recipient_is_enemy_with_an_adjacent_ally(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER],allies=(s.SECOND,),seed='A2GQISUB8-SIDES')
    combat.set_controller_mode(mid,actor_id=s.OWNER,controller_mode='LOCAL_AUTO')
    result=table.auto_step(mid,0,[])
    assert result['status']=='COMMITTED',result
    engine=cold(tmp_path,mid)
    assert engine.state.actors[s.SECOND].current_hp==500
    attacks=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and 'elemental_prayer' in e.source_definition_id]
    assert attacks and all(e.target_ids==(s.FOE,) for e in attacks)


def add_direct_spend(bundles):
    prepare(with_core=True)(bundles)
    owner=next(b for b in bundles if b['actor_id']==s.OWNER)
    source='tianxia.subpath.qi.test.direct_devil_spend'
    owner['action_catalog'].append({'source_definition_id':source,'owner_id':s.OWNER,'display_name':'Direct Devil Qi Spend',
        'economy':'NONE','resolution_kind':'TYPED','target_kind':'SELF','costs':[[core.DEVIL,1]],
        'parameters':{'typed':{'source':source,'numbers':{'pb':4,'cl':17,'key_mod':2},'duration':{'kind':'instant'},
                             'effects':[{'type':'gain_resource','resource_id':core.QI,'flat':0,'applies_to':'self'}],'riders':[]}}})
    owner['actor_template']['action_ids'].append(source)
    seal(owner)


def test_furnace_motion_observes_direct_devil_expenditure_and_limits_each_benefit(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[core.CORE],bundle_transform=add_direct_spend)
    choose(send,s.candidate(table,mid,'Direct Devil Qi Spend'),motion='temp_hp')
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert owner.temporary_hp==4 and owner.resources[core.DEVIL]==2
    assert owner.turn_flags['typed_once_turn:furnace_motion:temp_hp']
    choose(send,s.candidate(table,mid,'Direct Devil Qi Spend'),motion='check')
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert owner.resources[core.DEVIL]==1
    assert any(c.condition_id==core.CHECK for c in owner.conditions.values())
    assert owner.temporary_hp==4


def test_furnace_motion_declined_step_can_retry_and_success_consumes_once_after_reload(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[core.CORE],wide=True,bundle_transform=add_direct_spend)
    def spend(*, accept_step=False):
        # A committed spend changes the decision and its candidate identities.
        cid=s.candidate(table,mid,'Direct Devil Qi Spend')
        answers=[]; saw_step=False; prompt_text=None
        for _ in range(20):
            result=send(cid,answers)
            if result['status']=='COMMITTED': return saw_step,prompt_text
            assert result['status']=='REACTION_REQUIRED',result
            prompt=result['reaction']; answer={**prompt['context'],'selection':'DECLINE'}
            checkpoint=prompt['context']['checkpoint']
            if prompt.get('choice') and 'furnace_motion' in checkpoint:
                option=next(o for o in prompt['choice']['options'] if o['id']=='move' or o['id'].endswith(':move'))
                answer.update(selection='USE',option_ids=[option['id']])
            elif prompt.get('choice') and 'RIDER_STEP' in checkpoint:
                saw_step=True; prompt_text=prompt.get('moment') or prompt.get('text') or str(prompt)
                if accept_step:
                    option=next(o for o in prompt['choice']['options'] if o['id'].startswith('cell:') and 'Stay' not in o['label'])
                    answer.update(selection='USE',option_ids=[option['id']])
            answers.append(answer)
        raise AssertionError('too many Furnace Motion choices')

    assert spend(accept_step=False)[0]
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert not owner.turn_flags.get('typed_once_turn:furnace_motion:move')
    assert owner.resources[core.DEVIL]==2
    before=owner.position
    saw_step,text=spend(accept_step=True)
    assert saw_step and 'Furnace Motion' in text
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert owner.turn_flags['typed_once_turn:furnace_motion:move']
    assert owner.resources[core.DEVIL]==1 and owner.position != before
    # A third spend must no longer offer movement after a committed move.
    cid=s.candidate(table,mid,'Direct Devil Qi Spend')
    answers=[]
    for _ in range(16):
        result=send(cid,answers)
        if result['status']=='COMMITTED': break
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction']; answer={**prompt['context'],'selection':'DECLINE'}
        if prompt.get('choice') and 'furnace_motion' in prompt['context']['checkpoint']:
            assert not any(o['id']=='move' or o['id'].endswith(':move') for o in prompt['choice']['options'])
        answers.append(answer)
    else: raise AssertionError('third spend did not commit')
    assert cold(tmp_path,mid).state.actors[s.OWNER].turn_flags['typed_once_turn:furnace_motion:move']


def fixture(tmp_path,talents,*,patron='air',terrain='temp_hp',movement=None,**kwargs):
    def setup(combat,table,mid,send,commit):
        if any('Finish fight setup' in g['label'] for g in table.state(mid)['menu']['actions']):
            choose(send,s.candidate(table,mid,'Finish fight setup'),patron=patron,terrain=terrain,movement=movement)
    return s.fixture(tmp_path,talents,before_turns=setup,**kwargs)


@pytest.mark.parametrize('patron',list(prayer.CHOICES))
def test_prayer_alternate_damage_is_selected_before_resolution(tmp_path,patron):
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER],patron=patron)
    chosen=prayer.CHOICES[patron][1]
    choose(send,s.candidate(table,mid,'Elemental Prayer',s.FOE),damage_type=chosen)
    engine=cold(tmp_path,mid)
    damages=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED']
    assert damages and {e.payload['damage_type'] for e in damages}=={chosen.upper()}
    assert prayer.patron(engine.state.actors[s.OWNER])==patron


@pytest.mark.parametrize('patron',prayer.PATRONS)
@pytest.mark.parametrize('tagged',[False,True])
def test_prayer_narrow_resistance_exists_before_first_prayer_and_requires_printed_tag(tmp_path,patron,tagged):
    def probe(bundles):
        foe=next(b for b in bundles if b['actor_id']==s.FOE)
        source='test:a2qisub8.damage'
        foe['action_catalog'].append({'source_definition_id':source,'owner_id':s.FOE,'display_name':'Resistance Probe',
            'economy':'NONE','resolution_kind':'TYPED','target_kind':'ANY_CREATURE','range_ft':60,
            'parameters':{'typed':{'source':source,'source_tags':[patron] if tagged else [],
                'numbers':{'pb':4,'cl':17,'key_mod':2},'duration':{'kind':'instant'},
                'effects':[{'type':'damage','flat':20,'damage_types':[prayer.TYPES[patron]],'applies_to':'target'}],'riders':[]}}})
        foe['actor_template']['action_ids'].append(source)
        seal(foe)
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER],patron=patron,bundle_transform=probe)
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert owner.current_hp==500 and owner.resources[core.QI]==30
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != s.FOE:
        commit(table.state(mid)['menu']['end_turn'])
    choose(send,s.candidate(table,mid,'Resistance Probe',s.OWNER))
    engine=cold(tmp_path,mid)
    resisted=tagged or patron not in ('earth','metal','water','wood')
    assert engine.state.actors[s.OWNER].current_hp == 500-(10 if resisted else 20)


@pytest.mark.parametrize('benefit',['temp_hp','qi','decline'])
def test_terrain_attunement_is_exclusive_and_resolves_once_before_turn_one(tmp_path,benefit):
    from combat.ext.shugenja_terrain import TERRAIN
    def setup(bundles):
        owner=next(b for b in bundles if b['actor_id']==s.OWNER)
        next(r for r in owner['actor_template']['resources'] if r['resource_id']==core.QI)['initial']=20
        seal(owner)
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER,TERRAIN],terrain=benefit,bundle_transform=setup)
    engine=cold(tmp_path,mid); owner=engine.state.actors[s.OWNER]
    assert owner.resources[core.QI]==(24 if benefit=='qi' else 20)
    assert owner.temporary_hp==(8 if benefit=='temp_hp' else 0)
    assert not any('Finish fight setup' in g['label'] for g in table.state(mid)['menu']['actions'])
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != s.OWNER: commit(table.state(mid)['menu']['end_turn'])
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert owner.resources[core.QI]==(24 if benefit=='qi' else 20)
    assert owner.temporary_hp==(8 if benefit=='temp_hp' else 0)


def test_devil_qi_sheet_pool_uses_printed_scene_start_and_pb_cap_without_core(tmp_path):
    augment='tianxia.subpath.qi.devil_heart_second_furnace.feature.devil_qi_augment'
    combat,table,mid,send,commit=fixture(tmp_path,[augment],owner_pb=6)
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert owner.resources[core.DEVIL]==0
    assert owner.resource_maximums[core.DEVIL]==6


def test_furnace_motion_armament_can_move_twenty_feet_and_link_is_separate(tmp_path):
    from combat.ext import qi_path
    armament='tianxia.path.qi_cultivation.feature.domain_armament'
    combat,table,mid,send,commit=fixture(tmp_path,[core.CORE,armament,'tianxia.path.qi_cultivation.feature.domain_armament_link'],wide=True,bundle_transform=add_direct_spend)
    commit(s.candidate(table,mid,'Domain Armament: Manifest'))
    before=qi_path.armament_point(cold(tmp_path,mid).state.actors[s.OWNER])
    wanted=f'cell:{before[0]+4},{before[1]}'
    def spend(*, accept=False):
        # Resolve the current candidate after each committed payment.
        cid=s.candidate(table,mid,'Direct Devil Qi Spend')
        answers=[]; selected=False
        for _ in range(16):
            result=send(cid,answers)
            if result['status']=='COMMITTED': return selected
            assert result['status']=='REACTION_REQUIRED',result
            p=result['reaction'];a={**p['context'],'selection':'DECLINE'}
            checkpoint=p['context']['checkpoint']
            if p.get('choice'):
                options=p['choice']['options']
                if 'furnace_motion' in checkpoint:
                    pick=next(o for o in options if o['id']=='armament' or o['id'].endswith(':armament'))
                    a.update(selection='USE',option_ids=[pick['id']])
                elif 'FURNACE_ARMAMENT' in checkpoint and accept and not selected:
                    pick=next(o for o in options if o['id']==wanted)
                    a.update(selection='USE',option_ids=[pick['id']]);selected=True
            answers.append(a)
        raise AssertionError('too many armament choices')

    assert not spend(accept=False)
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert owner.resources[core.DEVIL]==2
    assert qi_path.armament_point(owner)==before
    assert not owner.turn_flags.get('typed_once_turn:furnace_motion:armament')
    assert spend(accept=True)
    engine=cold(tmp_path,mid);owner=engine.state.actors[s.OWNER]
    assert qi_path.armament_point(owner)==(before[0]+4,before[1])
    assert owner.resources[core.DEVIL]==1
    assert owner.turn_flags['typed_once_turn:furnace_motion:armament']
    assert not owner.turn_flags.get('typed_once_turn:furnace_link')


def test_furnace_link_decline_can_retry_and_only_success_consumes_movement_after_reload(tmp_path):
    from combat.ext import qi_path
    armament='tianxia.path.qi_cultivation.feature.domain_armament'
    combat,table,mid,send,commit=fixture(tmp_path,[core.CORE,armament],wide=True,bundle_transform=add_direct_spend)
    commit(s.candidate(table,mid,'Domain Armament: Manifest'))
    before=qi_path.armament_point(cold(tmp_path,mid).state.actors[s.OWNER])

    def spend(*, accept_link=False):
        cid=s.candidate(table,mid,'Direct Devil Qi Spend')
        answers=[]; saw_link=False
        for _ in range(20):
            result=send(cid,answers)
            if result['status']=='COMMITTED':
                return saw_link
            assert result['status']=='REACTION_REQUIRED',result
            prompt=result['reaction']; answer={**prompt['context'],'selection':'DECLINE'}
            checkpoint=prompt['context']['checkpoint']
            if prompt.get('choice') and 'FURNACE_ARMAMENT' in checkpoint:
                saw_link=True
                if accept_link:
                    options=prompt['choice']['options']
                    answer.update(selection='USE',option_ids=[options[-1]['id']])
            answers.append(answer)
        raise AssertionError('too many choices')

    assert spend(accept_link=False)
    engine=cold(tmp_path,mid); owner=engine.state.actors[s.OWNER]
    assert not owner.turn_flags.get('typed_once_turn:furnace_link')
    assert qi_path.armament_point(owner)==before
    assert spend(accept_link=True)
    engine=cold(tmp_path,mid); owner=engine.state.actors[s.OWNER]
    assert owner.turn_flags['typed_once_turn:furnace_link']
    assert qi_path.armament_point(owner)!=before
    assert not spend(accept_link=True)
    assert cold(tmp_path,mid).state.actors[s.OWNER].turn_flags['typed_once_turn:furnace_link']


@pytest.mark.parametrize('patron',list(prayer.CHOICES))
def test_prayer_damage_choice_prompt_names_action_and_target_after_service_render(tmp_path,patron):
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER],patron=patron)
    cid=s.candidate(table,mid,'Elemental Prayer',s.FOE)
    answers=[]; saw_prompt=False
    for _ in range(16):
        result=send(cid,answers)
        if result['status']=='COMMITTED': break
        assert result['status']=='REACTION_REQUIRED',result
        raw=result['reaction']
        answer={**raw['context'],'selection':'DECLINE'}
        if raw.get('choice') and 'shugenja_damage' in raw['context']['checkpoint']:
            owner=cold(tmp_path,mid).state.actors[s.OWNER]
            foe=cold(tmp_path,mid).state.actors[s.FOE]
            assert raw['action']=='Elemental Prayer',raw
            assert raw['affected']==foe.display_name
            assert 'Elemental Prayer' in raw['moment']
            assert foe.display_name in raw['moment']
            saw_prompt=True
        if raw.get('choice'):
            wanted=prayer.CHOICES[patron][1] if 'shugenja_damage' in raw['context']['checkpoint'] else None
            option=next((o for o in raw['choice']['options'] if wanted and (o['id']==wanted or o['id'].endswith(':'+wanted))),raw['choice']['options'][0])
            answer.update(selection='USE',option_ids=[option['id']])
        answers.append(answer)
    else: raise AssertionError('Prayer did not commit')
    assert saw_prompt
    cold(tmp_path,mid)


def test_furnace_motion_prompt_names_spending_action_and_affected_owner_after_service_render(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[core.CORE],bundle_transform=add_direct_spend)
    cid=s.candidate(table,mid,'Direct Devil Qi Spend')
    answers=[]; saw_prompt=False
    for _ in range(16):
        result=send(cid,answers)
        if result['status']=='COMMITTED': break
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction']
        if prompt.get('choice') and 'furnace_motion' in prompt['context']['checkpoint']:
            owner=cold(tmp_path,mid).state.actors[s.OWNER]
            assert prompt['action']=='Direct Devil Qi Spend',prompt
            assert prompt['affected']==owner.display_name
            assert 'Direct Devil Qi Spend' in prompt['moment']
            assert owner.display_name in prompt['moment']
            saw_prompt=True
        answer={**prompt['context'],'selection':'DECLINE'}
        if prompt.get('choice'):
            option=next((o for o in prompt['choice']['options'] if o['id']=='temp_hp' or o['id'].endswith(':temp_hp')),prompt['choice']['options'][0])
            answer.update(selection='USE',option_ids=[option['id']])
        answers.append(answer)
    else: raise AssertionError('Furnace action did not commit')
    assert saw_prompt
    engine=cold(tmp_path,mid)
    assert engine.state.actors[s.OWNER].temporary_hp==4


def test_manual_furnace_owner_gets_contextual_prompt_during_ai_reaction_turn(tmp_path):
    from tests.test_devil_qi_augment_review import add_counter_probe, play, probe_action, turn_to
    counter='tianxia.subpath.qi.test.devil_qi_counter'

    def prepare(bundles):
        add_counter_probe(bundles)
        owner=next(b for b in bundles if b['actor_id']==s.OWNER)
        reaction=next(r for r in owner['typed_reactions'] if r['feature_id']==counter)
        reaction['costs']=[{'resource_id':core.DEVIL,'amount':1}]
        probe_action(owner,'Second Cultivation Counter',counter,
            [{'type':'damage','applies_to':'target','flat':3,'damage_types':['force']}],economy='REACTION')

    combat,table,mid,_,_=s.fixture(tmp_path,[core.CORE],wide=True,bundle_transform=prepare)
    turn_to(table,mid,s.FOE)
    candidate=s.candidate(table,mid,'Trigger Cultivation Counter',s.OWNER)
    s.force_ai_candidate(combat,mid,s.FOE,candidate)
    combat.set_controller_mode(mid,actor_id=s.OWNER,controller_mode='MANUAL')
    combat.set_controller_mode(mid,actor_id=s.FOE,controller_mode='LOCAL_AUTO')
    prompts=play(combat,table,mid,candidate,'Temporary Hit Points',auto=True)
    motion=next(p for p in prompts if 'furnace_motion' in p['context']['checkpoint'])
    owner=cold(tmp_path,mid).state.actors[s.OWNER]
    assert motion['context']['reactor_id']==s.OWNER
    assert motion['action']=='Second Cultivation Counter',motion
    assert motion['affected']==owner.display_name
    assert owner.display_name in motion['moment'] and 'Second Cultivation Counter' in motion['moment']
    engine=cold(tmp_path,mid)
    assert engine.state.current_actor_id==s.FOE
    assert engine.state.actors[s.OWNER].resources[core.DEVIL]==1


def test_furnace_cultivation_check_bonus_consumes_once_on_native_check_after_reload(tmp_path):
    def setup(bundles):
        add_direct_spend(bundles)
        owner=next(b for b in bundles if b['actor_id']==s.OWNER)
        source='test:a2qisub8.cultivation_check'
        owner['action_catalog'].append({'source_definition_id':source,'owner_id':s.OWNER,'display_name':'Cultivation Check Probe',
            'economy':'NONE','resolution_kind':'TYPED','target_kind':'ANY_CREATURE','range_ft':60,
            'parameters':{'typed':{'source':source,'numbers':{'pb':4,'cl':17,'key_mod':2},'duration':{'kind':'instant'},
                'effects':[{'type':'contest_against','applies_to':'target','actor_check':{'kind':'cultivation'},
                    'target_check':{'kind':'dc','dc':10},'on_success':[],'on_fail':[]}],'riders':[]}}})
        owner['actor_template']['action_ids'].append(source);seal(owner)
    combat,table,mid,send,commit=fixture(tmp_path,[core.CORE],bundle_transform=setup)
    choose(send,s.candidate(table,mid,'Direct Devil Qi Spend'),motion='check')
    assert any(c.condition_id==core.CHECK for c in cold(tmp_path,mid).state.actors[s.OWNER].conditions.values())
    choose(send,s.candidate(table,mid,'Cultivation Check Probe',s.FOE))
    engine=cold(tmp_path,mid)
    checks=[e for e in engine.events if e.event_type=='CHECK_ROLLED']
    assert checks[-1].payload['actor']['modifier']==10
    assert not any(c.condition_id==core.CHECK for c in engine.state.actors[s.OWNER].conditions.values())
    choose(send,s.candidate(table,mid,'Cultivation Check Probe',s.FOE))
    engine=cold(tmp_path,mid)
    checks=[e for e in engine.events if e.event_type=='CHECK_ROLLED']
    assert checks[-1].payload['actor']['modifier']==6


def test_furnace_motion_unused_check_bonus_expires_at_owners_next_turn_end(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,[core.CORE],bundle_transform=add_direct_spend)
    choose(send,s.candidate(table,mid,'Direct Devil Qi Spend'),motion='check')
    engine=cold(tmp_path,mid); owner=engine.state.actors[s.OWNER]
    held=next(c for c in owner.conditions.values() if c.condition_id==core.CHECK)
    assert held.expires_on==f'END_OF_SOURCE_TURN_AT:{owner.turns_started + 1}'
    assert held.data['label']==f'Furnace Motion: +{owner.proficiency_bonus} to your next Cultivation Check before your next turn ends'
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != s.OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    assert any(c.condition_id==core.CHECK for c in cold(tmp_path,mid).state.actors[s.OWNER].conditions.values())
    commit(table.state(mid)['menu']['end_turn'])
    engine=cold(tmp_path,mid)
    assert not any(c.condition_id==core.CHECK for c in engine.state.actors[s.OWNER].conditions.values())


def test_terrain_attunement_half_speed_step_uses_native_movement_without_oa_or_ordinary_budget(tmp_path):
    from combat.ext.shugenja_terrain import TERRAIN
    combat,table,mid,send,commit=fixture(tmp_path,[prayer.PRAYER,TERRAIN],terrain='move',movement='cell:0,6')
    engine=cold(tmp_path,mid);owner=engine.state.actors[s.OWNER]
    assert (owner.position.x,owner.position.y)==(0,6)
    assert owner.movement_remaining_ft==30
    assert owner.resources[core.QI]==30 and owner.temporary_hp==0
    assert not any(e.event_type=='ATTACK_ROLLED' for e in engine.events)
