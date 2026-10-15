"""Real native acquisition, table intents, committed cold state and replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

P='tianxia.subpath.qi.spirit_bow_cultivator'
K=('spirit_bow','seeking_arrow','piercing_shot','arrow_of_fate','heaven_sundering_arrow')
O='actor:factory.spirit-bow-owner';F='actor:factory.spirit-bow-target';X='actor:factory.spirit-bow-other'
QI='resource:core.qi';ACTIVE='condition:typed.spirit_bow_manifestation';SEAL='condition:typed.spirit_bow_fate'


class NativeSeedService(CombatService):
    def _finish_factory_match(self,*args,**kwargs):
        kwargs['match_seed']='SPIRIT-BOW-NATIVE'
        return super()._finish_factory_match(*args,**kwargs)


def setup(tmp_path,cl=18,acquire=True,kit=None,foe_ac=1,dc=100,walls=None,objects=None,width=28,positions=None,terrain=None):
    for aid in (O,F,X):
        doc=sheet([],cl=cl,dc=dc,score=18,key='INT',kit=kit if aid==O else None)
        doc['identity']['display_name']=aid.rsplit('-',1)[-1].title()
        stats=doc['ability_scores_and_statistics'];stats.update(technique_attack_bonus=100,hit_points={'maximum':1000},armor_class={'base_value':foe_ac})
        stats['primary_resource']['maximum']=100
        if aid==O:doc['path_and_subpath']={'path_record_ids':['tianxia.path.qi_cultivation'],
            'paths':[{'path_id':'tianxia.path.qi_cultivation','attainment':cl,'key_ability':'INT'}],
            'path_feature_record_ids':(['tianxia.path.qi_cultivation.feature.domain_armament'] if cl>=9 else [])+
                (['tianxia.path.qi_cultivation.feature.domain_armament_link'] if cl>=13 else [])}
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.');folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    c=NativeSeedService(ROOT,tmp_path);t=TabletopService(c,tmp_path)
    saved=c.tabletop_maps.save({'display_name':'Spirit Bow native','width_squares':width,'height_squares':12,
        'walls':walls or [],'objects':objects or [],'terrain':terrain or [],'starts':{'team1':[[3,6]],'team2':[[12,6],[13,6]]}})
    j=c.create_journey(project_ids=[a.removeprefix('actor:factory.') for a in (O,F,X)],arena_id='battlefield:map.'+saved['map_id'],
        positions=positions or {O:{'x':3,'y':6},F:{'x':12,'y':6},X:{'x':13,'y':6}},base_paces={a:3000 for a in (O,F,X)})
    if acquire:j=c.journey_acquire_source(j['journey_id'],j['revision'],O,P,{})
    return c,t,j


def fight(c,t,j,maximum_rounds=30):
    mid=c.journey_start_combat(j['journey_id'],j['revision'],teams={O:'team:a',F:'team:b',X:'team:b'},maximum_rounds=maximum_rounds)['match_id']
    while t.state(mid)['menu']['actor_id']!=O:commit(t,mid,t.state(mid)['menu']['end_turn'])
    return mid


def cold(c,mid):
    s=CombatService(ROOT,c.userdata_root)._load_session(mid);assert s.verify()['status']=='PASS';assert s.mechanical.replay()['status']=='PASS';return s.engine


def option(t,mid,label,target=None,at=None):
    group=next(g for g in t.state(mid)['menu']['actions'] if g['label']==label)
    rows=[o for o in group['options'] if target is None or target in o.get('target_ids',[])]
    if at is None:return rows[0]['candidate_id']
    chosen=next((o for o in rows if ((o.get('destination') or {}).get('x'),(o.get('destination') or {}).get('y'))==at),None)
    if chosen is None and group.get('placement_picker'):chosen=next(o for o in rows if o.get('destination') is None)
    assert chosen is not None,(label,at,rows)
    return chosen['candidate_id'],at


def commit(t,mid,cid,picks=None):
    aim=None
    if isinstance(cid,tuple):cid,aim=cid
    answers=[]
    for _ in range(24):
        m=t.state(mid)['menu']
        try:r=t.act(mid,cid,m['decision_id'],m['state_version'],0,answers)
        except Exception as exc:
            detail=getattr(getattr(exc,'diagnostic',None),'details',None)
            import traceback
            frame=traceback.extract_tb(exc.__traceback__)[-1]
            raise AssertionError(f'Native commit rejected: {detail or exc}; {frame.filename}:{frame.lineno}') from exc
        if r['status']=='COMMITTED':return r
        assert r['status']=='REACTION_REQUIRED',r
        p=r['reaction'];key=p['context'].get('reaction_source_id','');a={**p['context'],'selection':'DECLINE'}
        if p.get('choice'):
            selected=None
            if aim is not None and key=='choice:placement_menu.square':
                selected=f'cell:{aim[0]},{aim[1]},0'
                assert selected in {o['id'] for o in p['choice']['options']}
            for needle,wanted in (picks or {}).items():
                if key.endswith(needle):selected=next(o['id'] for o in p['choice']['options'] if o['id']==wanted or wanted in o.get('label',''))
            if selected is None and not key.endswith('spirit_bow_fate'):selected=(p['choice'].get('preferred') or [p['choice']['options'][0]['id']])[0]
            if selected is not None:a.update(selection='USE',option_ids=[selected])
        answers.append(a)
    raise AssertionError('unbounded choices')


def next_turn(t,mid):
    commit(t,mid,t.state(mid)['menu']['end_turn'])
    while t.state(mid)['menu']['actor_id']!=O:commit(t,mid,t.state(mid)['menu']['end_turn'])


def manifest(t,mid):commit(t,mid,option(t,mid,'Manifest Spirit Bow: Projected Spirit Bow'))
def held(e,aid=F,cid=SEAL):return [c for c in e.state.actors[aid].conditions.values() if c.condition_id==cid]


@pytest.mark.parametrize('cl,count',[(3,1),(5,1),(6,2),(9,2),(10,3),(13,3),(14,4),(17,4),(18,5)])
def test_acquisition_native_progression(tmp_path,cl,count):
    c,t,j=setup(tmp_path,cl)
    assert j['actors'][O]['source_states'][P]['earned']==[P+'.feature.'+k for k in K[:count]]
    assert all(P not in str(j['actors'][aid]['bundle']['typed_passives']) for aid in (F,X))
    assert CombatService(ROOT,tmp_path).journey_state(j['journey_id'])['actors'][O]['bundle']==j['actors'][O]['bundle']
    with pytest.raises(ValueError,match='already acquired'):c.journey_acquire_source(j['journey_id'],j['revision'],O,P,{})


def test_manifest_projected_payment_replacement_profile_hit(tmp_path):
    c,t,j=setup(tmp_path);mid=fight(c,t,j)
    assert not any(g['label']=='Spirit Bow attack' for g in t.state(mid)['menu']['actions'])
    manifest(t,mid);e=cold(c,mid)
    assert len(held(e,O,ACTIVE))==1 and e.state.actors[O].resources[QI]==99
    a=next(a for a in e.action_catalog.values() if a.owner_id==O and a.display_name=='Spirit Bow attack')
    p=a.parameters['typed'];assert (p['range_ft'],p['long_range_ft'])==(120,480)
    assert p['weapon']['damage']=={'count':1,'sides':8,'modifier':4}
    hp=e.state.actors[F].current_hp;commit(t,mid,option(t,mid,'Spirit Bow attack',F));e=cold(c,mid)
    assert e.state.actors[F].current_hp<hp and not e.state.objects
    next_turn(t,mid);manifest(t,mid);assert len(held(cold(c,mid),O,ACTIVE))==1


@pytest.mark.parametrize('form',['Far-Seeking Arrow','Cover-Piercing Arrow','Blood-Seeking Arrow','Revealing Arrow'])
def test_seeking_native_payment_and_first_attack(tmp_path,form):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Spirit Bow attack + '+form,F));e=cold(c,mid)
    assert e.state.actors[O].resources[QI]==98 and e.state.actors[O].turn_flags['spirit_bow_seeking']==1
    if form=='Revealing Arrow':assert held(e,cid='condition:typed.spirit_bow_revealed')


def test_piercing_line_native_damage_no_weapon_roll(tmp_path):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);before=cold(c,mid)
    commit(t,mid,option(t,mid,'Piercing Shot: Force',at=(20,6)));e=cold(c,mid)
    assert all(e.state.actors[a].current_hp<before.state.actors[a].current_hp for a in (F,X))
    assert e.state.actors[O].resources[QI]==96
    assert not any(x.event_type=='ATTACK_ROLLED' for x in e.events)
    assert len([x for x in e.events if x.event_type=='DAMAGE_ROLLED'])==1


@pytest.mark.parametrize('seal',['recovery','journey','resistance','thread'])
def test_fate_native_declared_seals_and_replace(tmp_path,seal):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Spirit Bow attack',F),{'spirit_bow_fate':seal});e=cold(c,mid);seals=held(e)
    assert len(seals)==1 and seals[0].data['seal']==seal
    assert e.state.actors[O].resources[QI]==96 and seals[0].data['repeat_save']['ability']=='CHA'
    if seal=='journey':assert e._effective_speed(e.state.actors[F])==15
    if seal=='recovery':
        from combat.typed_executor import condition_rules
        assert any(r.get('healing_denied') and r.get('temp_hp_denied') for r in condition_rules(e.state.actors[F]))
    if seal=='thread':
        from combat.observer_information import readings
        assert readings(e,e.state.actors[O])[0]['details']['distance_ft']==45
        assert not readings(e,e.state.actors[X])
    next_turn(t,mid);commit(t,mid,option(t,mid,'Spirit Bow attack',F),{'spirit_bow_fate':'recovery'})
    seals=held(cold(c,mid));assert len(seals)==1 and seals[0].data['seal']=='recovery'


@pytest.mark.parametrize('outcome',['push','stop','reactions','recovery','save'])
def test_heaven_native_all_choices_once_scene(tmp_path,outcome):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Heaven-Sundering Arrow: Projected Spirit Bow',F),{'spirit_bow_heaven':outcome});e=cold(c,mid)
    assert e.state.actors[O].resources[QI]==91 and held(e,O,'condition:typed.spirit_bow_scene_use')
    assert any(x.event_type=='DAMAGE_ROLLED' and '10d10' in str(x.payload) for x in e.events)
    assert held(e,cid='condition:typed.prone' if outcome=='push' else 'condition:typed.spirit_bow_heaven')
    next_turn(t,mid);assert not any(g['label'].startswith('Heaven-Sundering') for g in t.state(mid)['menu']['actions'])


def test_wrong_owner_and_journey_manifest_continuation(tmp_path):
    c,t,j=setup(tmp_path,acquire=False)
    assert all('spirit_bow' not in o['id'] for o in c.journey_menu(j['journey_id'],O)['options'])
    with pytest.raises(ValueError):c.journey_acquire_source(j['journey_id'],j['revision'],F,P,{})
    j=c.journey_acquire_source(j['journey_id'],j['revision'],O,P,{})
    j=c.journey_act(j['journey_id'],j['revision'],O,'spirit_bow_manifest',{'profile':'projected'})
    assert j['actors'][O]['resources'][QI]==99
    assert j['actors'][O]['source_states'][P]['manifestation']['expires_at']==3600
    mid=fight(c,t,j);assert held(cold(c,mid),O,ACTIVE)


def test_curving_selects_real_obstacle_and_commits_route(tmp_path):
    c,t,j=setup(tmp_path,walls=[{'shape':'line','points':[[7,6],[7,7]],'blocks':'sight_and_movement'}]);mid=fight(c,t,j)
    manifest(t,mid)
    commit(t,mid,option(t,mid,'Curving Arrow: Choose Obstacle',at=(6,5)))
    e=cold(c,mid)
    candidates=[a for a in e.legal_candidates() if a.display_name=='Spirit Bow attack + Curving Arrow' and F in a.target_ids]
    assert candidates and candidates[0].metadata['shot_geometry']['route']['source_id']==P+'.feature.seeking_arrow'
    commit(t,mid,option(t,mid,'Spirit Bow attack + Curving Arrow',F));e=cold(c,mid)
    assert e.state.actors[O].resources[QI]==98


def test_fate_success_is_source_next_start_not_target_turn(tmp_path):
    c,t,j=setup(tmp_path,dc=1);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Spirit Bow attack',F),{'spirit_bow_fate':'journey'});e=cold(c,mid)
    rows=held(e);assert len(rows)==1 and rows[0].expires_on=='START_OF_SOURCE_NEXT_TURN'
    assert 'repeat_save' not in rows[0].data and e._effective_speed(e.state.actors[F])==20
    next_turn(t,mid);assert not held(cold(c,mid))


def test_journey_hour_clock_expires_across_small_waits(tmp_path):
    c,t,j=setup(tmp_path);jid=j['journey_id']
    j=c.journey_act(jid,j['revision'],O,'spirit_bow_manifest',{'profile':'projected'})
    for seconds in (1000,1000,1593):j=c.journey_act(jid,j['revision'],O,'wait',{'seconds':seconds})
    assert 'manifestation' in j['actors'][O]['source_states'][P]
    j=c.journey_act(jid,j['revision'],O,'wait',{'seconds':1})
    assert 'manifestation' not in j['actors'][O]['source_states'][P]
    mid=fight(c,t,j);assert not held(cold(c,mid),O,ACTIVE)


def test_real_bow_native_inventory_empowerment_and_binding(tmp_path):
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.duan_gong','quantity':1},
                                {'item_id':'tianxia.mortal.gear.arrows_20','quantity':1}]}}
    c,t,j=setup(tmp_path,kit=kit);jid=j['journey_id']
    choices=[a['parameters']['spirit_bow_manifest'] for a in j['actors'][O]['bundle']['action_catalog'] if a.get('parameters',{}).get('spirit_bow_manifest') not in (None,'projected')]
    assert choices,[(a['display_name'],a.get('parameters',{}).get('typed',{}).get('proficient')) for a in j['actors'][O]['bundle']['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('weapon')]
    real=choices[0]
    with pytest.raises(ValueError):c.journey_act(jid,j['revision'],O,'spirit_bow_manifest',{'profile':real})
    j=c.journey_act(jid,j['revision'],O,'spirit_bow_wield',{'profile':real})
    j=c.journey_act(jid,j['revision'],O,'spirit_bow_manifest',{'profile':real})
    with pytest.raises(ValueError):c.journey_act(jid,j['revision'],O,'spirit_bow_bind',{'profile':real,'scope':real})
    payload={'source':P,'subject':O,'kind':'bond_requirements','scope':real,'value':{'item':real,
        'lawful_access':1,'attunement_ready':1,'sentient_consent':1,'unbound':1},'expires_at':1000,'readers':[O]}
    with pytest.raises(ValueError):c.journey_act(jid,j['revision'],O,'declare_fact',payload)
    j=c.journey_world_fact(jid,j['revision'],payload)
    j=c.journey_act(jid,j['revision'],O,'spirit_bow_bind',{'profile':real,'scope':real})
    assert j['seconds']==612 and j['actors'][O]['source_states'][P]['bound']==real
    mid=fight(c,t,j);e=cold(c,mid)
    assert held(e,O,'condition:typed.spirit_bow_bound')
    manifest_name=next(g['label'] for g in t.state(mid)['menu']['actions'] if g['label'].startswith('Spirit Bow: Duan Gong') and '+' not in g['label'])
    commit(t,mid,option(t,mid,manifest_name,F));e=cold(c,mid)
    assert any(x.event_type=='DAMAGE_COMMITTED' and F in x.target_ids for x in e.events)


@pytest.mark.parametrize('hp',[1,10000])
def test_piercing_real_native_barrier_destruction_or_stop(tmp_path,hp):
    obj={'name':'Stone barrier','kind':'door','material':'stone','size':'medium','x':7,'y':6,
        'ac':10,'hp':hp,'blocks':True,'structure':True,'unattended':True}
    c,t,j=setup(tmp_path,objects=[obj]);mid=fight(c,t,j)
    commit(t,mid,option(t,mid,'Piercing Shot: Force',at=(20,6)));e=cold(c,mid)
    barrier=next(iter(e.state.objects.values()));assert barrier.destroyed==(hp==1)
    assert (e.state.actors[F].current_hp<1000)==(hp==1)


def test_heaven_range_is_300_not_projected_long_range(tmp_path):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid);e=cold(c,mid)
    action=next(a for a in e.action_catalog.values() if a.owner_id==O and a.display_name=='Heaven-Sundering Arrow: Projected Spirit Bow')
    assert action.range_ft==300 and action.parameters['typed']['long_range_ft']==300


def test_automatic_owner_keeps_native_choice_and_payment_pipeline(tmp_path):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid)
    cid=option(t,mid,'Heaven-Sundering Arrow: Projected Spirit Bow',F)
    from tests.r1i_service_support import force_ai_candidate
    force_ai_candidate(c,mid,O,cid)
    answers=[]
    for _ in range(16):
        result=t.auto_step(mid,0,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        p=result['reaction'];answer={**p['context'],'selection':'DECLINE'}
        if p.get('choice'):answer.update(selection='USE',option_ids=[p['choice']['options'][0]['id']])
        answers.append(answer)
    else:raise AssertionError('automatic native turn did not settle')
    e=cold(c,mid)
    assert held(e,O,'condition:typed.spirit_bow_scene_use')
    assert e.state.actors[O].resources[QI] in (88,91)


@pytest.mark.parametrize('form,mode',[('', 'DISADVANTAGE'),('Far-Seeking Arrow','NORMAL')])
def test_long_range_removal_never_grants_advantage(tmp_path,form,mode):
    c,t,j=setup(tmp_path,width=60,positions={O:{'x':3,'y':6},F:{'x':43,'y':6},X:{'x':13,'y':6}})
    mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Spirit Bow attack'+(' + '+form if form else ''),F));e=cold(c,mid)
    roll=next(x for x in reversed(e.events) if x.event_type=='ATTACK_ROLLED' and x.actor_id==O)
    assert roll.payload['mode']==mode


@pytest.mark.parametrize('form,cover',[('',2),('Cover-Piercing Arrow',0)])
def test_cover_form_removes_cover_bonus_without_advantage(tmp_path,form,cover):
    c,t,j=setup(tmp_path,terrain=[{'type':'SIMPLE_COVER','cells':[[12,6]]}]);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Spirit Bow attack'+(' + '+form if form else ''),F));e=cold(c,mid)
    roll=next(x for x in reversed(e.events) if x.event_type=='ATTACK_ROLLED' and x.actor_id==O)
    assert roll.payload['cover_bonus']==cover and roll.payload['mode']=='NORMAL'


def test_projected_damage_type_remains_a_human_choice(tmp_path):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Spirit Bow attack',F),{'spirit_bow_damage':'PIERCING'})
    e=cold(c,mid)
    damage=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and x.actor_id==O and F in x.target_ids]
    assert damage and {x.payload['damage_type'] for x in damage}=={'PIERCING'}


def test_blood_seeking_requires_real_damage_in_previous_turn_window(tmp_path):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Spirit Bow attack',F));next_turn(t,mid)
    commit(t,mid,option(t,mid,'Spirit Bow attack + Blood-Seeking Arrow',F));e=cold(c,mid)
    roll=next(x for x in reversed(e.events) if x.event_type=='ATTACK_ROLLED' and x.actor_id==O)
    assert roll.payload['mode']=='ADVANTAGE'


def test_heaven_success_expires_at_target_start(tmp_path):
    from combat.ext.effect_durations import parse
    c,t,j=setup(tmp_path,dc=1);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Heaven-Sundering Arrow: Projected Spirit Bow',F));e=cold(c,mid)
    row=held(e,cid='condition:typed.spirit_bow_heaven')[0]
    assert parse(row.expires_on)[:2]==('start',F)
    commit(t,mid,t.state(mid)['menu']['end_turn'])
    while t.state(mid)['menu']['actor_id']!=F:commit(t,mid,t.state(mid)['menu']['end_turn'])
    assert not held(cold(c,mid),cid='condition:typed.spirit_bow_heaven')


def test_heaven_failed_save_duration_reaches_source_next_end(tmp_path):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Heaven-Sundering Arrow: Projected Spirit Bow',F),{'spirit_bow_heaven':'stop'})
    next_turn(t,mid)
    assert held(cold(c,mid),cid='condition:typed.spirit_bow_heaven')
    commit(t,mid,t.state(mid)['menu']['end_turn'])
    assert not held(cold(c,mid),cid='condition:typed.spirit_bow_heaven')


def bound_bow(tmp_path):
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.duan_gong','quantity':1},
                                {'item_id':'tianxia.mortal.gear.arrows_20','quantity':1}]}}
    c,t,j=setup(tmp_path,kit=kit);jid=j['journey_id']
    choices=[a['parameters']['spirit_bow_manifest'] for a in j['actors'][O]['bundle']['action_catalog'] if a.get('parameters',{}).get('spirit_bow_manifest') not in (None,'projected')]
    assert choices,[(a['display_name'],a.get('parameters',{}).get('typed',{}).get('proficient')) for a in j['actors'][O]['bundle']['action_catalog'] if a.get('parameters',{}).get('typed',{}).get('weapon')]
    real=choices[0]
    j=c.journey_act(jid,j['revision'],O,'spirit_bow_wield',{'profile':real})
    j=c.journey_act(jid,j['revision'],O,'spirit_bow_manifest',{'profile':real})
    j=c.journey_world_fact(jid,j['revision'],{'source':P,'subject':O,'kind':'bond_requirements','scope':real,
        'value':{'item':real,'lawful_access':1,'attunement_ready':1,'sentient_consent':1,'unbound':1},'expires_at':1000,'readers':[O]})
    j=c.journey_act(jid,j['revision'],O,'spirit_bow_bind',{'profile':real,'scope':real})
    return c,t,j,real


def native_option(c,mid,label,target=None,at=None,remote=None):
    e=c._load_session(mid).engine
    rows=c.decision(mid)['context']['legal_candidates']
    chosen=next(row for row in rows if
        (a:=e.action_catalog.get(row['source_definition_id'])) is not None and a.display_name==label and
        (target is None or target in row.get('target_ids',[])) and
        (at is None or row.get('metadata',{}).get('placement_picker') or row.get('destination') is not None and (row['destination']['x'],row['destination']['y'])==at) and
        (remote is None or bool(row.get('metadata',{}).get('effect_origin'))==remote))
    return (chosen['candidate_id'],at) if at is not None else chosen['candidate_id']


def test_floating_real_bow_native_origin_link_payment_and_call(tmp_path):
    from combat.ext.hand_occupancy import weapon_grips
    c,t,j,real=bound_bow(tmp_path);mid=fight(c,t,j)
    commit(t,mid,option(t,mid,'Manifest Bound Spirit Bow',at=(9,6)));e=cold(c,mid)
    assert real not in weapon_grips(e,e.state.actors[O])
    obj=next(o for o in e.state.objects.values() if (o.component or {}).get('real_bow')==real)
    assert (obj.position.x,obj.position.y)==(9,6) and not obj.destroyed
    heaven=next(a.display_name for a in e.action_catalog.values() if a.owner_id==O and a.display_name.startswith('Heaven-Sundering Arrow: Duan Gong'))
    commit(t,mid,native_option(c,mid,heaven,F,remote=True));e=cold(c,mid)
    assert e.state.actors[O].position.x==3 and e.state.actors[O].resources[QI]==90
    assert any(x.payload.get('effect_origin',{}).get('position',{}).get('x')==9 for x in e.events)
    next_turn(t,mid)
    commit(t,mid,native_option(c,mid,'Piercing Shot: Force',at=(20,6),remote=True));e=cold(c,mid)
    assert e.state.actors[O].resources[QI]==85
    commit(t,mid,option(t,mid,'Call Bound Spirit Bow'));e=cold(c,mid)
    assert real in weapon_grips(e,e.state.actors[O])
    assert e.state.objects[obj.object_id].component['representation_retired']==1


def finish_fight(c,t,mid):
    for _ in range(12):
        if c._load_session(mid).engine.state.terminal_result is not None:return
        commit(t,mid,t.state(mid)['menu']['end_turn'])
    raise AssertionError('native fight did not reach its round boundary')


def test_floating_real_item_and_scene_use_survive_encounter_boundary(tmp_path):
    c,t,j,real=bound_bow(tmp_path);mid=fight(c,t,j,maximum_rounds=1)
    commit(t,mid,option(t,mid,'Manifest Bound Spirit Bow',at=(9,6)))
    e=cold(c,mid)
    heaven=next(a.display_name for a in e.action_catalog.values() if a.owner_id==O and a.display_name.startswith('Heaven-Sundering Arrow: Duan Gong'))
    commit(t,mid,native_option(c,mid,heaven,F,remote=True))
    finish_fight(c,t,mid);cold(c,mid)
    j=c.journey_resume(j['journey_id'],c.journey_state(j['journey_id'])['revision'])
    state=j['actors'][O]['source_states'][P]
    assert state['floating']['profile']==real and state['heaven_used']==1
    assert len(state['bow_objects'])==1
    j=c.journey_act(j['journey_id'],j['revision'],O,'wait',{'seconds':6})
    mid2=fight(c,t,j);e=cold(c,mid2)
    assert held(e,O,'condition:typed.spirit_bow_floating')
    assert len([o for o in e.state.objects.values() if (o.component or {}).get('real_bow')==real])==1
    assert not any(g['label'].startswith('Heaven-Sundering') for g in t.state(mid2)['menu']['actions'])


def test_piercing_line_includes_allied_creatures_without_weapon_attack(tmp_path):
    c,t,j=setup(tmp_path)
    mid=c.journey_start_combat(j['journey_id'],j['revision'],teams={O:'team:a',F:'team:a',X:'team:b'},maximum_rounds=30)['match_id']
    while t.state(mid)['menu']['actor_id']!=O:commit(t,mid,t.state(mid)['menu']['end_turn'])
    commit(t,mid,option(t,mid,'Piercing Shot: Force',at=(24,6)))
    e=cold(c,mid)
    assert e.state.actors[F].current_hp<1000 and e.state.actors[X].current_hp<1000
    assert not any(x.event_type=='ATTACK_ROLLED' and x.actor_id==O for x in e.events)


def test_heaven_can_use_legal_seeking_form_on_the_same_attack(tmp_path):
    c,t,j=setup(tmp_path);mid=fight(c,t,j);manifest(t,mid)
    commit(t,mid,option(t,mid,'Heaven-Sundering Arrow: Projected Spirit Bow + Revealing Arrow',F),{'spirit_bow_heaven':'stop'})
    e=cold(c,mid)
    assert e.state.actors[O].resources[QI]==90
    assert held(e,cid='condition:typed.spirit_bow_revealed')
    assert held(e,O,'condition:typed.spirit_bow_scene_use')


def test_new_journey_preserves_remaining_hour_without_reset(tmp_path):
    c,t,j=setup(tmp_path);jid=j['journey_id']
    j=c.journey_act(jid,j['revision'],O,'spirit_bow_manifest',{'profile':'projected'})
    j=c.journey_act(jid,j['revision'],O,'wait',{'seconds':3590})
    assert j['actors'][O]['source_states'][P]['manifestation']['expires_at']-j['seconds']==4
    c.journey_act(jid,j['revision'],O,'finish',{})
    j=c.create_journey(project_ids=[a.removeprefix('actor:factory.') for a in (O,F,X)],
        arena_id=next(k for k in c.factory_arenas() if k.startswith('battlefield:map.')),
        positions={O:{'x':3,'y':6},F:{'x':12,'y':6},X:{'x':13,'y':6}},base_paces={a:3000 for a in (O,F,X)})
    assert j['actors'][O]['source_states'][P]['manifestation']['expires_at']==4
    j=c.journey_act(j['journey_id'],j['revision'],O,'wait',{'seconds':4})
    assert 'manifestation' not in j['actors'][O]['source_states'][P]


@pytest.mark.parametrize('item,label',[('duan_gong','Duan Gong'),('biao_qiang','Biao Qiang')])
def test_native_mundane_weapon_profile_without_spirit_bow(tmp_path,item,label):
    kit={'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.'+item,'quantity':1},
                                {'item_id':'tianxia.mortal.gear.arrows_20','quantity':1}]}}
    c,t,j=setup(tmp_path,acquire=False,kit=kit,positions={O:{'x':3,'y':6},F:{'x':4,'y':6},X:{'x':13,'y':6}})
    mid=fight(c,t,j)
    group=next(g for g in t.state(mid)['menu']['actions'] if g['label'].startswith(label) and any(F in o.get('target_ids',[]) for o in g['options']))
    commit(t,mid,option(t,mid,group['label'],F));e=cold(c,mid)
    assert e.state.actors[F].current_hp<1000
    assert not held(e,O,ACTIVE) and not any(a.parameters.get('spirit_bow_manifest') for a in e.action_catalog.values() if a.owner_id==O)
