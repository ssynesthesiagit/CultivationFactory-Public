"""Traditions 2: compiled service intents, committed choices, cold reload/replay."""
from pathlib import Path
import pytest
from combat.factory_compiler import compile_character
from combat.canonical import canonical_sha256
from combat import typed_executor
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_riders_c8 import sheet
from tests.hunt12_support import candidate, send

ROOT=Path(__file__).resolve().parents[1]
ME='actor:factory.fix12';FOE='actor:factory.fix12-foe';ALLY='actor:factory.traditions2-ally'
EX='tianxia.tradition.spirit.exorcist.feature.'
DW='tianxia.tradition.spirit.dreamweaver.feature.'
ES='tianxia.tradition.spirit.echo_step_disciple.feature.'
EQ='tianxia.tradition.spirit.equal_measure_scripture.feature.'
GE='tianxia.tradition.spirit.grief_eater.feature.'
SPIKE='tianxia.path.spirit_awakening.feature.mind_spike'
BLOOD_PUMP='tianxia.path.body_refining.feature.blood_pump'
BAN='tianxia.subpath.qi.banner_cultivator.feature.'

def probe(bundle, name, effects, target='ANY_CREATURE'):
    source='test:traditions2.'+name+'.'+bundle['actor_id']
    bundle['action_catalog'].append({'source_definition_id':source,'display_name':'Test: '+name,'owner_id':bundle['actor_id'],
        'economy':'NONE','resolution_kind':'TYPED','target_kind':target,'range_ft':60,
        'parameters':{'free_primary':True,'typed':{'effects':effects,'numbers':{'save_dc':100,'cl':18,'pb':6},'duration':{'kind':'instant'},'riders':[]},'expected_damage':0}})
    bundle['actor_template']['action_ids'].append(source)


def scene(tmp_path, ids, *, dc=100, kinds=('Intruder',), auto=False, ally_kinds=(), ally_features=(), ally_resource=None, foe_features=(), foe_reaction_rows=(), foe_cl=18, primary_resource=None, owner_position=(3,6), foe_position=(4,6), ranged_strike=False, seed='A2GTRA2', foe_probes=()):
    docs=[sheet(ids,dc=dc),sheet(foe_features,dc=1,cl=foe_cl),sheet(ally_features,dc=1)]
    if primary_resource:
        docs[0]['ability_scores_and_statistics']['primary_resource']['name']=primary_resource
    if ally_resource:
        docs[2]['ability_scores_and_statistics']['primary_resource']['name']=ally_resource
    for d in docs:d['ability_scores_and_statistics']['hit_points']['maximum']=1000
    docs[1]['identity']['creature_types']=list(kinds)
    docs[2]['identity']['creature_types']=list(ally_kinds)
    bundles=[compile_character(d,actor_id=aid,reaction_plan={'ask':True}) for d,aid in zip(docs,[ME,FOE,ALLY])]
    bundles[1]['typed_reactions'].extend(foe_reaction_rows)
    probe(bundles[0],'sleep',[{'type':'dreamweaver_refuge_sleep','applies_to':'target'}])
    probe(bundles[0],'mark',[{'type':'mark','mark':'Resonance','applies_to':'target','duration':{'kind':'until_removed'}}])
    probe(bundles[0],'dream thread mark',[{'type':'mark','mark':'Dream Thread','applies_to':'target','duration':{'kind':'until_removed'}}])
    probe(bundles[0],'measure',[{'type':'gain_resource','resource_id':'resource:named.measure_impact','flat':1,'applies_to':'self'}],target='SELF')
    probe(bundles[0],'burden',[{'type':'gain_resource','resource_id':'resource:named.sorrow_burden','flat':1,'applies_to':'self'}],target='SELF')
    probe(bundles[0],'ordinary',[{'type':'damage','flat':10,'damage_types':['force'],'applies_to':'target'}])
    probe(bundles[0],'lethal bypass',[{'type':'damage','bypass_temporary_hp':True,'flat':1100,'damage_types':['force'],'applies_to':'target'}])
    probe(bundles[0],'nick',[{'type':'damage','flat':990,'damage_types':['force'],'applies_to':'target'}])
    probe(bundles[0],'bypass 20',[{'type':'damage','bypass_temporary_hp':True,'flat':20,'damage_types':['force'],'applies_to':'target'}])
    probe(bundles[0],'bypass 20 necrotic',[{'type':'damage','bypass_temporary_hp':True,'flat':20,'damage_types':['necrotic'],'applies_to':'target'}])
    probe(bundles[0],'hold',[{'type':'held_at_distance','mode':'closer','duration':{'kind':'until_start_of_next_turn'},'applies_to':'target','evidence':'cannot willingly move closer'}])
    if GE+'vessel_of_ten_thousand_sorrows' in ids:
        probe(bundles[0],'push field target',[{'type':'forced_movement','distance_ft':40,'direction':'away','applies_to':'target'}])
        probe(bundles[0],'pull field target',[{'type':'forced_movement','distance_ft':40,'direction':'toward','applies_to':'target'}])
    probe(bundles[0],'bypass',[{'type':'damage','bypass_temporary_hp':True,'flat':10,'damage_types':['force'],'applies_to':'target'}])
    probe(bundles[1],'disadvantage',[{'type':'disadvantage','on':'its next attack roll','applies_to':'self'}],target='SELF')
    for name,effects in foe_probes:probe(bundles[1],name,effects,target='SELF')
    probe(bundles[1],'strike',[{'type':'attack','attack_kind':'cultivation_melee','count':1,'on_hit':[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}]}],target='HOSTILE_ENTITY')
    if ranged_strike:
        strike=next(a for a in bundles[1]['action_catalog'] if a['display_name']=='Test: strike')
        typed=strike['parameters']['typed']
        typed.update(range_ft=20,long_range_ft=80,strike_penalty_provenance=1,
                     weapon={'damage':{'count':1,'sides':6,'modifier':0},'damage_type':'force'})
        typed['effects'][0]['attack_kind']='cultivation_ranged'
        strike['range_ft']=80
    probe(bundles[1],'hurt',[{'type':'damage','flat':1001,'damage_types':['force'],'applies_to':'target'}])
    probe(bundles[1],'death save',[{'type':'death_save_now','applies_to':'target'}])
    probe(bundles[1],'temp',[{'type':'temp_hp','flat':500,'applies_to':'self'}],target='SELF')
    probe(bundles[1],'invisible',[{'type':'condition','condition':'invisible','applies_to':'self','duration':{'kind':'until_end_of_turn'}}],target='SELF')
    probe(bundles[1],'teleport',[{'type':'teleport','distance_ft':5,'applies_to':'self','picks_destination':True}],target='SELF')
    probe(bundles[1],'frighten',[{'type':'condition','condition':'frightened','applies_to':'target','duration':{'kind':'until_removed'}}])
    probe(bundles[2],'temp',[{'type':'temp_hp','flat':500,'applies_to':'self'}],target='SELF')
    warp=next(a for a in bundles[1]['action_catalog'] if a['display_name']=='Test: teleport')
    warp['economy']='BONUS_ACTION';warp['range_ft']=5
    for b in bundles:
        b.pop('bundle_sha256',None);b['bundle_sha256']=canonical_sha256(b)
    svc=CombatService(ROOT,tmp_path);table=TabletopService(svc,tmp_path)
    mid=svc._finish_factory_match(bundles,[ME,FOE,ALLY],{ME:'team:a',FOE:'team:b',ALLY:'team:a'},
        {ME:{'x':owner_position[0],'y':owner_position[1]},FOE:{'x':foe_position[0],'y':foe_position[1]},ALLY:{'x':3,'y':7}},
        svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],[ME,ALLY],[FOE],
        control_modes={ME:'LOCAL_AUTO' if auto else 'MANUAL',FOE:'MANUAL',ALLY:'MANUAL'},match_seed=seed,display_name='Tradition test',maximum_rounds=20)['match_id']
    advance(svc,table,mid,ME)
    return svc,table,mid


def commit(svc,table,mid,c,picks=(),*,auto=False):
    answers=[];prompts=[]
    for _ in range(30):
        r=send(svc,table,mid,c,answers,auto=auto)
        if r['status']=='COMMITTED':return prompts
        assert r['status']=='REACTION_REQUIRED',r
        p=r['reaction'];prompts.append(p);a={**p['context'],'selection':'DECLINE'}
        if p.get('choice'):
            ids=[o['id'] for o in p['choice']['options']]
            chosen=next((x for x in picks if (all(k in ids for k in x) if isinstance(x,tuple) else x in ids)),None)
            if chosen is not None:a.update(selection='USE',option_ids=list(chosen) if isinstance(chosen,tuple) else [chosen])
            elif not p['choice'].get('allow_decline'):a.update(selection='USE',option_ids=ids[:p['choice'].get('minimum_selections',1)])
        answers.append(a)
    raise AssertionError('Unresolved choices')


def use(svc,table,mid,name,target=None,picks=(),auto=False):
    engine=svc._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if getattr(engine.action_catalog.get(c.source_definition_id),'display_name',c.display_name)==name and (target is None or target in c.target_ids))
    return commit(svc,table,mid,c,picks,auto=auto)


def end(svc,table,mid):commit(svc,table,mid,candidate(svc,mid,lambda c:c.kind.value=='END_TURN'),auto=svc.decision(mid)['control_mode']=='LOCAL_AUTO')
def advance(svc,table,mid,aid):
    for _ in range(9):
        if svc._load_session(mid).engine.state.current_actor_id==aid:return
        end(svc,table,mid)
    raise AssertionError(aid)
def cold(tmp_path,mid):
    sess=CombatService(ROOT,tmp_path)._load_session(mid)
    assert sess.verify()['status']=='PASS'
    assert sess.mechanical.replay()['status']=='PASS'
    return sess.engine

def held(actor,key):return [c for c in actor.conditions.values() if c.condition_id==key]

@pytest.mark.parametrize('kinds,marked',[(('Intruder',),True),(('Spirit',),False)])
def test_name_designation_and_explicit_kind_mark(tmp_path,kinds,marked):
    s,t,m=scene(tmp_path,[EX+'ghost_sight_and_name_the_intruder'],kinds=kinds)
    use(s,t,m,'Ghost Sight and Name the Intruder',FOE,picks=('Intruder',))
    e=cold(tmp_path,m);f=e.state.actors[FOE]
    assert held(f,'condition:typed.exorcist_designation')[0].data['designation']=='Intruder'
    assert bool([c for c in f.conditions.values() if 'resonance' in c.condition_id])==marked

@pytest.mark.parametrize('feature,name',[(EX+'purification_bell','Purification Bell'),(EX+'grand_exorcism','Grand Exorcism')])
@pytest.mark.parametrize('kind',['radiant','psychic'])
def test_exorcism_damage_type_and_sides(tmp_path,feature,name,kind):
    s,t,m=scene(tmp_path,[feature],ally_kinds=('Intruder',))
    advance(s,t,m,FOE);use(s,t,m,'Test: frighten',ALLY);advance(s,t,m,ME)
    use(s,t,m,name,picks=(kind,FOE))
    e=cold(tmp_path,m)
    damage=[ev for ev in e.events if ev.event_type=='DAMAGE_COMMITTED' and FOE in ev.target_ids]
    assert damage and {ev.payload['damage_type'].lower() for ev in damage}=={kind}
    assert e.state.actors[ALLY].current_hp==1000
    assert not any(ev.event_type=='DAMAGE_COMMITTED' and ALLY in ev.target_ids for ev in e.events)


def test_binding_seal_blocks_teleport_and_invisibility(tmp_path):
    s,t,m=scene(tmp_path,[EX+'seal_of_binding'])
    use(s,t,m,'Seal of Binding',FOE)
    e=cold(tmp_path,m);assert held(e.state.actors[FOE],'condition:typed.binding_seal')
    advance(s,t,m,FOE)
    before=cold(tmp_path,m).state.actors[FOE].position
    use(s,t,m,'Test: teleport',picks=('cell:5,6',))
    use(s,t,m,'Test: invisible')
    e=cold(tmp_path,m)
    assert e.state.actors[FOE].position==before
    assert any(v.event_type=='PASSIVE_TRIGGERED' and v.payload.get('log')=='Binding Seal prevents teleportation.' for v in e.events)
    assert not held(e.state.actors[FOE],'condition:typed.invisible')


def test_adjacent_ally_wakes_dream_sleep_with_action(tmp_path):
    s,t,m=scene(tmp_path,[DW+'eternal_dream_refuge'])
    use(s,t,m,'Test: sleep',ALLY)
    assert held(cold(tmp_path,m).state.actors[ALLY],'condition:typed.dream_sleep')
    use(s,t,m,'Wake Dream-Sleeping Ally',ALLY)
    e=cold(tmp_path,m)
    assert not held(e.state.actors[ALLY],'condition:typed.dream_sleep')
    assert not held(e.state.actors[ALLY],'condition:typed.unconscious')
    assert not e.state.actors[ME].action_available


def test_automatic_wake_only_allies(tmp_path):
    s,t,m=scene(tmp_path,[DW+'eternal_dream_refuge'],auto=True)
    use(s,t,m,'Test: sleep',FOE,auto=True);use(s,t,m,'Test: sleep',ALLY,auto=True)
    cs=[c for c in s._load_session(m).engine.legal_candidates() if c.source_definition_id=='action:typed.dreamweaver.wake_dream_sleeper']
    assert cs and all(c.target_ids==(ALLY,) for c in cs)
    commit(s,t,m,cs[0],auto=True)
    e=cold(tmp_path,m)
    assert not held(e.state.actors[ALLY],'condition:typed.dream_sleep')
    assert held(e.state.actors[FOE],'condition:typed.dream_sleep')


def test_hundred_echo_crosses_hostile_space_but_cannot_end_there(tmp_path):
    s,t,m=scene(tmp_path,[ES+'hundred_echoes_kill_one_moment'])
    use(s,t,m,'Hundred Echoes Kill One Moment')
    e=cold(tmp_path,m)
    moves=[c for c in e.legal_candidates() if c.kind.value=='MOVE']
    assert not any(c.destination==e.state.actors[FOE].position for c in moves)
    chosen=next(c for c in moves if any(p==e.state.actors[FOE].position for p in c.canonical_path))
    commit(s,t,m,chosen)
    e=cold(tmp_path,m);assert e.state.actors[ME].position==chosen.destination


def test_bypass_is_one_packet_and_preserves_temp_hp(tmp_path):
    s,t,m=scene(tmp_path,[])
    advance(s,t,m,FOE);use(s,t,m,'Test: temp');advance(s,t,m,ME)
    use(s,t,m,'Test: bypass',FOE)
    e=cold(tmp_path,m);f=e.state.actors[FOE]
    assert (f.current_hp,f.temporary_hp)==(990,500)
    use(s,t,m,'Test: ordinary',FOE)
    f=cold(tmp_path,m).state.actors[FOE]
    assert (f.current_hp,f.temporary_hp)==(990,490)


def test_bypass_damage_standard_cannot_fall_preserves_temporary_hp_through_service(tmp_path):
    s,t,m=scene(tmp_path,[BAN+'raise_the_standard',BAN+'imperial_standard_of_heaven'],primary_resource='Qi')
    use(s,t,m,'Manifest Command Banner (1 Qi)',picks=('cell:4,7',))
    end(s,t,m)
    advance(s,t,m,ME)
    use(s,t,m,'Imperial Standard of Heaven (8 Qi, once per scene)')
    use(s,t,m,'Test: nick',ALLY)
    e=cold(tmp_path,m);assert e.state.actors[ALLY].current_hp==10
    advance(s,t,m,ALLY);use(s,t,m,'Test: temp')
    e=cold(tmp_path,m);assert (e.state.actors[ALLY].current_hp,e.state.actors[ALLY].temporary_hp)==(10,500)
    advance(s,t,m,ME);use(s,t,m,'Test: bypass 20',ALLY,picks=('use',))
    e=cold(tmp_path,m);a=e.state.actors[ALLY]
    # Standard Cannot Fall floors the packet at 1 HP and never spends the ally's
    # temporary Hit Points. The step it owes is offered immediately and consumed on
    # the damage that triggered it (banner.survival_step), so the pending condition
    # is gone by the next read -- assert the printed result, not the transient row.
    assert (a.current_hp,a.temporary_hp)==(1,500)
    assert not any(c.condition_id=='condition:typed.banner_step' for c in a.conditions.values())
    assert any(ev.event_type=='PASSIVE_TRIGGERED' and ev.source_definition_id==BAN+'imperial_standard_of_heaven'
               for ev in e.events)


def test_bypass_damage_generic_blood_pump_preserves_temporary_hp_through_service(tmp_path):
    s,t,m=scene(tmp_path,[],ally_features=(BLOOD_PUMP,),ally_resource='Stamina')
    use(s,t,m,'Test: nick',ALLY)
    advance(s,t,m,ALLY);use(s,t,m,'Test: temp')
    e=cold(tmp_path,m);assert (e.state.actors[ALLY].current_hp,e.state.actors[ALLY].temporary_hp)==(10,500)
    advance(s,t,m,ME);use(s,t,m,'Test: bypass 20',ALLY,picks=('use',))
    e=cold(tmp_path,m);a=e.state.actors[ALLY]
    assert (a.current_hp,a.temporary_hp)==(1,500)
    assert any(ev.event_type=='REACTION_RESOLVED' and ev.source_definition_id==BLOOD_PUMP for ev in e.events)


@pytest.mark.parametrize('dc',[100,1])
def test_impact_recompense_added_damage_bypasses_temp_hp(tmp_path,dc):
    s,t,m=scene(tmp_path,[EQ+'receive_and_return',EQ+'threefold_recompense',SPIKE],dc=dc)
    use(s,t,m,'Test: measure');use(s,t,m,'Test: mark',FOE)
    advance(s,t,m,FOE);use(s,t,m,'Test: temp');advance(s,t,m,ME)
    use(s,t,m,'Threefold Recompense',FOE,picks=(('impact',),'spike'))
    e=cold(tmp_path,m);f=e.state.actors[FOE]
    assert f.current_hp<1000 and f.temporary_hp<500
    packets=[ev.payload for ev in e.events if ev.event_type=='DAMAGE_COMMITTED' and FOE in ev.target_ids]
    assert any(p['hp_damage']>0 and p['temporary_hp_absorbed']==0 for p in packets)
    assert e.state.actors[ME].resources['resource:named.measure_impact']==0


def test_mourner_cease_ends_on_exit_even_if_target_reenters_before_turn_end(tmp_path):
    s,t,m=scene(tmp_path,[GE+'taste_of_sorrow',GE+'vessel_of_ten_thousand_sorrows'],foe_features=(SPIKE,),foe_cl=5,foe_position=(7,6))
    use(s,t,m,'Test: mark',FOE)
    use(s,t,m,'Vessel of Ten Thousand Sorrows',picks=(ALLY,))
    use(s,t,m,"Mourner's Embrace",FOE,picks=('cease',))
    e=cold(tmp_path,m);assert held(e.state.actors[FOE],'condition:typed.mourner_cease')
    def move_owner_to(x):
        engine=s._load_session(m).engine
        candidate=next(c for c in engine.legal_candidates() if c.actor_id==ME and c.kind.value=='MOVE'
                       and (c.destination.x,c.destination.y)==(x,6))
        commit(s,t,m,candidate)
    move_owner_to(0)
    e=cold(tmp_path,m)
    assert not held(e.state.actors[FOE],'condition:typed.mourner_cease')
    move_owner_to(3)
    e=cold(tmp_path,m)
    assert (e.state.actors[ME].position.x,e.state.actors[ME].position.y)==(3,6)
    assert not held(e.state.actors[FOE],'condition:typed.mourner_cease')
    advance(s,t,m,FOE)
    assert not held(cold(tmp_path,m).state.actors[FOE],'condition:typed.mourner_cease')


def test_mourner_cease_blocks_hostile_actions(tmp_path):
    s,t,m=scene(tmp_path,[GE+'taste_of_sorrow',GE+'vessel_of_ten_thousand_sorrows'],foe_features=(SPIKE,),foe_cl=5)
    use(s,t,m,'Test: mark',FOE)
    use(s,t,m,'Vessel of Ten Thousand Sorrows',picks=(ALLY,))
    use(s,t,m,"Mourner's Embrace",FOE,picks=('cease',))
    e=cold(tmp_path,m);assert held(e.state.actors[FOE],'condition:typed.mourner_cease')
    advance(s,t,m,FOE)
    e=cold(tmp_path,m)
    assert not any(getattr(e.action_catalog.get(c.source_definition_id),'target_kind',None)=='HOSTILE_ENTITY' for c in e.legal_candidates())


def _offensive_damaged_reaction():
    return {'block':'generic','feature_id':'test:traditions2.offensive_counter','name':'Test Offensive Counter',
            'kind':'damaged','costs':[],'numbers':{'attack_bonus':100,'pb':6,'cl':5},'range_ft':60,
            'effects':[{'type':'attack','attack_kind':'cultivation_ranged','count':1,
                        'on_hit':[{'type':'damage','flat':1,'damage_types':['force'],'applies_to':'target'}]}]}


def test_mourner_cease_blocks_hostile_opportunity_attacks_through_service(tmp_path):
    s,t,m=scene(tmp_path,[GE+'taste_of_sorrow',GE+'vessel_of_ten_thousand_sorrows'],foe_features=(SPIKE,),foe_cl=5)
    use(s,t,m,'Test: mark',FOE)
    use(s,t,m,'Vessel of Ten Thousand Sorrows',picks=(ALLY,))
    use(s,t,m,"Mourner's Embrace",FOE,picks=('cease',))
    assert held(cold(tmp_path,m).state.actors[FOE],'condition:typed.mourner_cease')
    advance(s,t,m,ALLY)
    e=s._load_session(m).engine
    mover=next(c for c in e.legal_candidates() if c.actor_id==ALLY and c.kind.value=='MOVE' and c.destination.x==3 and c.destination.y==10)
    prompts=commit(s,t,m,mover)
    e=cold(tmp_path,m)
    assert prompts==[]
    assert not any(ev.event_type=='REACTION_RESOLVED' and ev.actor_id==FOE for ev in e.events)
    assert held(e.state.actors[FOE],'condition:typed.mourner_cease')


def test_mourner_cease_blocks_generic_offensive_reaction_but_keeps_damage_committed(tmp_path):
    s,t,m=scene(tmp_path,[GE+'taste_of_sorrow',GE+'vessel_of_ten_thousand_sorrows'],foe_features=(SPIKE,),foe_reaction_rows=(_offensive_damaged_reaction(),),foe_cl=5)
    use(s,t,m,'Test: mark',FOE)
    use(s,t,m,'Vessel of Ten Thousand Sorrows',picks=(ALLY,))
    use(s,t,m,"Mourner's Embrace",FOE,picks=('cease',))
    assert held(cold(tmp_path,m).state.actors[FOE],'condition:typed.mourner_cease')
    prompts=use(s,t,m,'Test: ordinary',FOE)
    e=cold(tmp_path,m)
    assert prompts==[]
    assert e.state.actors[FOE].current_hp==990
    assert not any(ev.event_type=='REACTION_RESOLVED' and ev.feature_id=='test:traditions2.offensive_counter' for ev in e.events)


def test_mourner_cease_ends_on_forced_exit_and_does_not_return_on_reentry(tmp_path):
    s,t,m=scene(tmp_path,[GE+'taste_of_sorrow',GE+'vessel_of_ten_thousand_sorrows'],foe_features=(SPIKE,),foe_cl=5,
                owner_position=(7,6),foe_position=(3,6))
    use(s,t,m,'Test: mark',FOE)
    use(s,t,m,'Vessel of Ten Thousand Sorrows',picks=(ALLY,))
    use(s,t,m,"Mourner's Embrace",FOE,picks=('cease',))
    assert held(cold(tmp_path,m).state.actors[FOE],'condition:typed.mourner_cease')
    use(s,t,m,'Test: push field target',FOE)
    e=cold(tmp_path,m)
    assert e.state.actors[FOE].position.x==0
    assert not held(e.state.actors[FOE],'condition:typed.mourner_cease')
    use(s,t,m,'Test: pull field target',FOE)
    e=cold(tmp_path,m)
    assert e.state.actors[FOE].position.x>=6
    assert not held(e.state.actors[FOE],'condition:typed.mourner_cease')


def test_zero_distance_interrupted_move_does_not_fulfill_prediction(tmp_path):
    read='tianxia.tradition.spirit.fate_reader.feature.read_the_thread'
    s,t,m=scene(tmp_path,[read],foe_position=(6,6))
    use(s,t,m,'Read the Thread',FOE)
    use(s,t,m,'Mark the Branch: record a prediction',FOE,picks=('move',))
    use(s,t,m,'Test: hold',FOE)
    advance(s,t,m,FOE)
    e=cold(tmp_path,m)
    move=next(c for c in e.legal_candidates() if c.actor_id==FOE and c.kind.value=='MOVE' and (c.destination.x,c.destination.y)==(5,6))
    commit(s,t,m,move)
    e=cold(tmp_path,m)
    receipt=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==FOE)
    assert receipt.payload.get('interrupted') and len(receipt.payload.get('path') or ())==1
    assert held(e.state.actors[FOE],'condition:typed.fate_reader_branch')
    assert not any('resonance' in c.condition_id for c in e.state.actors[FOE].conditions.values())

@pytest.mark.parametrize('owns',[True,False])
def test_banishment_native_ghost_needs_feature_and_failed_mind_spike(tmp_path,owns):
    s,t,m=scene(tmp_path,[SPIKE,*([EX+'banishment_strike'] if owns else [])],kinds=('Restless Dead',))
    before=cold(tmp_path,m).state.actors[ME].resources['resource:core.resonance']
    use(s,t,m,'Mind Spike',FOE,picks=('use',))
    e=cold(tmp_path,m)
    fears=held(e.state.actors[FOE],'condition:typed.frightened')
    assert bool(fears)==owns
    if owns:
        # main's banish_native_dead records the repeat save with the engine's own
        # lowercase ability key; the rule's Charisma save is the same thing.
        assert fears[0].data['repeat_save']['ability']=='cha'
        assert fears[0].data['repeat_save']['dc']==100
        assert e.state.actors[ME].resources['resource:core.resonance']==before-2

@pytest.mark.parametrize('kind',['force','necrotic'])
def test_three_step_uses_one_chosen_damage_type(tmp_path,kind):
    s,t,m=scene(tmp_path,[ES+'three_step_soul_execution'])
    use(s,t,m,'Three-Step Soul Execution',picks=(kind,FOE,'cell:3,6'))
    e=cold(tmp_path,m)
    damage=[ev.payload for ev in e.events if ev.event_type=='DAMAGE_COMMITTED' and FOE in ev.target_ids]
    assert damage and {p['damage_type'].lower() for p in damage}=={kind}

@pytest.mark.parametrize('feature,name',[(EX+'purification_bell','Purification Bell'),(EX+'grand_exorcism','Grand Exorcism')])
def test_automatic_exorcism_harms_enemies_and_purifies_allies(tmp_path,feature,name):
    s,t,m=scene(tmp_path,[feature],ally_kinds=('Intruder',),auto=True)
    advance(s,t,m,FOE);use(s,t,m,'Test: frighten',ALLY);advance(s,t,m,ME)
    use(s,t,m,name,auto=True)
    e=cold(tmp_path,m)
    assert e.state.actors[FOE].current_hp<1000
    assert e.state.actors[ALLY].current_hp==1000
    assert not held(e.state.actors[ALLY],'condition:typed.frightened')


def test_living_chronicle_erases_one_recorded_death_failure(tmp_path):
    from combat.ext.life_state import failed_death_saves
    ch='tianxia.tradition.spirit.echo_scribe.feature.chronicle_of_the_living_soul'
    s,t,m=scene(tmp_path,[ch],seed='A2GTRA2-DEATH-1')
    use(s,t,m,'Chronicle of the Living Soul',picks=(ALLY,))
    advance(s,t,m,FOE);use(s,t,m,'Test: hurt',ALLY)
    # A real death save is rolled by the sealed source; record at most one failure.
    for _ in range(2):
        use(s,t,m,'Test: death save',ALLY)
        e=cold(tmp_path,m)
        if failed_death_saves(e.state.actors[ALLY])>0:break
    bad=failed_death_saves(e.state.actors[ALLY])
    assert bad>0 and e.state.actors[ALLY].active
    assert any(c.data.get('kind')=='failed_death_save' for c in held(e.state.actors[ME],'condition:typed.living_entry'))
    advance(s,t,m,ME)
    before=cold(tmp_path,m)
    bad=failed_death_saves(before.state.actors[ALLY])
    entries=sum(c.data.get('kind')=='failed_death_save' for c in held(before.state.actors[ME],'condition:typed.living_entry'))
    use(s,t,m,'Rewrite the Margin: erase a failed death save',ALLY)
    e=cold(tmp_path,m)
    assert failed_death_saves(e.state.actors[ALLY])==bad-1
    assert e.state.actors[ALLY].current_hp==0
    assert sum(c.data.get('kind')=='failed_death_save' for c in held(e.state.actors[ME],'condition:typed.living_entry'))==entries-1
    assert not any(c.display_name=='Rewrite the Margin: erase a failed death save' for c in e.legal_candidates())


@pytest.mark.parametrize('already',[True,False])
def test_dream_stitch_existing_disadvantage_subtracts_pb(tmp_path,already):
    s,t,m=scene(tmp_path,[DW+'dream_stitch'])
    advance(s,t,m,FOE)
    if already:use(s,t,m,'Test: disadvantage')
    use(s,t,m,'Test: strike',ME,picks=('stitch','thread'))
    e=cold(tmp_path,m)
    attacks=[ev for ev in e.events if ev.event_type=='ATTACK_ROLLED' and ev.actor_id==FOE]
    assert attacks and attacks[-1].payload.get('modifier', 0)==(-6 if already else 0)
    assert e.state.actors[ME].resources['resource:core.resonance']==59
    assert not e.state.actors[ME].reaction_available


def test_ink_records_observable_disturbance_when_marking(tmp_path):
    ink='tianxia.tradition.spirit.echo_scribe.feature.ink_remembers'
    s,t,m=scene(tmp_path,[ink])
    advance(s,t,m,FOE);use(s,t,m,'Test: frighten',ALLY);advance(s,t,m,ME)
    use(s,t,m,'Test: mark',ALLY,picks=('frightened',))
    e=cold(tmp_path,m);entries=held(e.state.actors[ME],'condition:typed.echo_entry')
    assert len(entries)==1 and entries[0].data['category']=='frightened' and entries[0].data['soul']==ALLY
    assert e.state.actors[ME].resources['resource:core.resonance']==60


def test_predicted_attack_marks_once_and_grants_chosen_step(tmp_path):
    read='tianxia.tradition.spirit.fate_reader.feature.read_the_thread'
    s,t,m=scene(tmp_path,[read])
    use(s,t,m,'Read the Thread',FOE)
    use(s,t,m,'Mark the Branch: record a prediction',FOE,picks=('attack',))
    assert held(cold(tmp_path,m).state.actors[FOE],'condition:typed.fate_reader_branch')
    advance(s,t,m,FOE)
    prompts=use(s,t,m,'Test: strike',ME,picks=(ME,'cell:4,5'))
    assert any('Factory character' in str(p) and 'Test: strike' in str(p) for p in prompts)
    e=cold(tmp_path,m)
    assert not held(e.state.actors[FOE],'condition:typed.fate_reader_branch')
    assert any('resonance' in c.condition_id for c in e.state.actors[FOE].conditions.values())
    assert (e.state.actors[ME].position.x,e.state.actors[ME].position.y)==(4,5)
    events=[v for v in e.events if v.event_type=='MOVEMENT_COMMITTED' and v.actor_id==ME]
    assert events and events[-1].payload['cost_ft']==0


def test_dream_refuge_intercepts_service_zero_hp_and_allied_recall(tmp_path):
    s,t,m=scene(tmp_path,[DW+'eternal_dream_refuge'])
    advance(s,t,m,FOE)
    use(s,t,m,'Test: hurt',ME,picks=('refuge',))
    e=cold(tmp_path,m);owner=e.state.actors[ME]
    assert owner.current_hp==0 and owner.life_state=='STABLE'
    assert held(owner,'condition:typed.dream_refuge')
    assert owner.resources['resource:core.resonance']==54
    advance(s,t,m,ALLY)
    use(s,t,m,'Refuge Recall (speak their name and a shared memory)',ME)
    e=cold(tmp_path,m);owner=e.state.actors[ME]
    assert owner.current_hp==12 and owner.life_state is None
    assert not held(owner,'condition:typed.dream_refuge')
    assert not held(owner,'condition:typed.life_unconscious')


def test_bypassing_packet_offers_borrowed_ending_at_real_hp_threshold(tmp_path):
    borrowed='tianxia.tradition.spirit.fate_reader.feature.borrowed_ending'
    s,t,m=scene(tmp_path,[],foe_features=(borrowed,))
    advance(s,t,m,FOE);use(s,t,m,'Test: temp');advance(s,t,m,ME)
    use(s,t,m,'Test: lethal bypass',FOE,picks=('borrow',))
    e=cold(tmp_path,m);f=e.state.actors[FOE]
    assert f.current_hp==1 and f.temporary_hp==500
    assert f.resources['resource:core.resonance']==54
    assert any(c.condition_id=='condition:typed.borrowed_ending' for c in f.conditions.values())



def test_bypass_packet_offers_morning_breath_at_real_hp_threshold(tmp_path):
    breath='tianxia.talent.radiance.resurrection_of_the_morning_breath'
    s,t,m=scene(tmp_path,[breath],primary_resource='Qi')
    use(s,t,m,'Test: nick',ALLY)
    assert cold(tmp_path,m).state.actors[ALLY].current_hp==10
    advance(s,t,m,ALLY);use(s,t,m,'Test: temp')
    advance(s,t,m,ME)
    before=cold(tmp_path,m).state.actors[ME].resources['resource:core.qi']
    use(s,t,m,'Test: bypass 20 necrotic',ALLY,picks=('manual',))
    e=cold(tmp_path,m);ally=e.state.actors[ALLY]
    assert (ally.current_hp,ally.temporary_hp)==(1,500)
    assert e.state.actors[ME].resources['resource:core.qi']==before-8
    assert not e.state.actors[ME].reaction_available


def test_name_success_conceals_mark_then_reveals_at_source_start(tmp_path):
    s,t,m=scene(tmp_path,[EX+'ghost_sight_and_name_the_intruder'],dc=1)
    use(s,t,m,'Ghost Sight and Name the Intruder',FOE,picks=('Intruder',))
    e=cold(tmp_path,m)
    assert any(c.condition_id=='condition:typed.exorcist_concealed_mark' for c in e.state.actors[FOE].conditions.values())
    stream=t.events(m,0,engine=e)['events']
    assert not any('Resonance mark' in row.get('summary','') for row in stream)
    default_projection=s.presentation(m)
    assert not any('Resonance mark' in row.get('summary','') for row in default_projection.get('feed',[]))
    # main's design: a concealed row stays in the projection carrying hidden=True, so the
    # table cannot render it; the prose feed above drops it outright. Both must hold.
    resonance_id=typed_executor.mark_condition_id('Resonance',ME)
    rows={c['condition_id']:c for c in next(a for a in s.presentation(m,feed=False)['actors']
                                            if a['entity_id']==FOE)['conditions']}
    assert rows[resonance_id]['hidden'] is True
    assert rows['condition:typed.exorcist_concealed_mark']['hidden'] is True
    assert typed_executor.bears_mark(cold(tmp_path,m).state.actors[FOE],ME,'Resonance')  # mechanics still see it
    end(s,t,m);advance(s,t,m,ME)
    assert not any(c.condition_id=='condition:typed.exorcist_concealed_mark' for c in cold(tmp_path,m).state.actors[FOE].conditions.values())
    rows={c['condition_id']:c for c in next(a for a in s.presentation(m,feed=False)['actors']
                                            if a['entity_id']==FOE)['conditions']}
    assert rows[resonance_id]['hidden'] is False


def test_dream_stitch_explains_pb_penalty_when_attack_already_has_disadvantage(tmp_path):
    s,t,m=scene(tmp_path,[DW+'dream_stitch'])
    advance(s,t,m,FOE)
    use(s,t,m,'Test: disadvantage',FOE)
    prompts=use(s,t,m,'Test: strike',ME,picks=('stitch',))
    stitch=next(row for row in prompts if row.get('reaction')=='Dream Stitch')
    choice=stitch['choice']
    label=choice['options'][0].get('label','')
    assert 'subtract 6' in label and 'Disadvantage' not in label
    assert 'Proficiency Bonus' in stitch.get('moment','')
    cold(tmp_path,m)


def test_dream_stitch_honors_far_shot_long_range_removal_through_service(tmp_path,monkeypatch):
    from combat.ext.sniper_precision import FAR
    s,t,m=scene(tmp_path,[DW+'dream_stitch'],foe_features=[FAR],owner_position=(1,6),foe_position=(8,6),ranged_strike=True)
    engine=s._load_session(m).engine
    original=type(engine)._attack_mode
    queries=[]
    def inspect_mode(self,attacker,defender,**kwargs):
        result=original(self,attacker,defender,**kwargs)
        if attacker.entity_id==FOE:
            queries.append({'removed':sorted(kwargs.get('removed') or ()),
                            'provenance':dict(kwargs.get('provenance') or {}),'result':result})
        return result
    monkeypatch.setattr(type(engine),'_attack_mode',inspect_mode)
    advance(s,t,m,FOE)
    prompts=use(s,t,m,'Test: strike',ME,picks=('stitch',))
    stitch=next(row for row in prompts if row.get('reaction')=='Dream Stitch')
    assert 'Disadvantage' in stitch['choice']['options'][0]['label']
    assert 'subtract' not in stitch['choice']['options'][0]['label']
    assert any(q['removed']==['DISADVANTAGE:long_range'] and q['provenance'] and q['result']=='NORMAL' for q in queries),queries
    e=cold(tmp_path,m)
    attack=next(v for v in reversed(e.events) if v.event_type=='ATTACK_ROLLED' and v.actor_id==FOE)
    assert attack.payload['mode']=='DISADVANTAGE', attack.payload
    assert not any(v.event_type=='D20_REWRITTEN' and v.source_definition_id==DW+'dream_stitch'
                   and v.payload.get('operation')=='bonus' for v in e.events)


def test_dream_stitch_ignores_storm_ranged_only_removal_for_melee_attack(tmp_path):
    adv={'type':'advantage','applies_to':'self','on':'the next attack roll'}
    s,t,m=scene(tmp_path,[DW+'dream_stitch','TAL_AIR_STORM_WITHOUT_DIRECTION'],foe_probes=[('advantage',[adv])])
    use(s,t,m,'Storm Without Direction: No Safe Breath',ME)
    advance(s,t,m,FOE)
    use(s,t,m,'Test: advantage',FOE)
    use(s,t,m,'Test: disadvantage',FOE)
    prompts=use(s,t,m,'Test: strike',ME,picks=('stitch',))
    stitch=next(row for row in prompts if row.get('reaction')=='Dream Stitch')
    label=stitch['choice']['options'][0]['label']
    assert 'Disadvantage on' in label and 'subtract' not in label
    e=cold(tmp_path,m)
    attack=next(v for v in reversed(e.events) if v.event_type=='ATTACK_ROLLED' and v.actor_id==FOE)
    assert attack.payload['mode']=='DISADVANTAGE', attack.payload
    assert not any(v.event_type=='D20_REWRITTEN' and v.source_definition_id==DW+'dream_stitch'
                   and v.payload.get('operation')=='bonus' for v in e.events)


@pytest.mark.parametrize('mark,eligible',[('dream thread',False),('mark',True)])
def test_name_intruder_requires_named_resonance_mark_candidate_after_service_reload(tmp_path,mark,eligible):
    s,t,m=scene(tmp_path,[EX+'ghost_sight_and_name_the_intruder'],kinds=('Humanoid',))
    use(s,t,m,'Test: '+('dream thread mark' if mark=='dream thread' else mark),FOE)
    e=cold(tmp_path,m)
    candidates=[c for c in e.legal_candidates()
                if c.display_name=='Ghost Sight and Name the Intruder' and FOE in c.target_ids]
    assert bool(candidates)==eligible, ([(c.source_definition_id,c.target_ids,c.display_name) for c in e.legal_candidates()],
                                        [(c.condition_id,c.source_actor_id) for c in e.state.actors[FOE].conditions.values()],
                                        e.state.current_actor_id,e.state.actors[ME].action_available,e.state.actors[ME].bonus_action_available,
                                        e.state.actors[ME].action_ids)


def test_grand_exorcism_does_not_damage_unqualified_humanoid(tmp_path):
    s,t,m=scene(tmp_path,[EX+'grand_exorcism'],kinds=('Humanoid',))
    use(s,t,m,'Grand Exorcism',picks=('radiant',FOE))
    e=cold(tmp_path,m)
    assert e.state.actors[FOE].current_hp==1000
    assert not any(v.event_type=='SAVE_ROLLED' and v.actor_id==FOE for v in e.events)


def test_unfulfilled_prediction_ends_at_next_source_turn_end(tmp_path):
    read='tianxia.tradition.spirit.fate_reader.feature.read_the_thread'
    s,t,m=scene(tmp_path,[read])
    use(s,t,m,'Read the Thread',FOE)
    use(s,t,m,'Mark the Branch: record a prediction',FOE,picks=('move',))
    end(s,t,m);advance(s,t,m,ME)
    assert held(cold(tmp_path,m).state.actors[FOE],'condition:typed.fate_reader_branch')
    end(s,t,m)
    assert not held(cold(tmp_path,m).state.actors[FOE],'condition:typed.fate_reader_branch')
