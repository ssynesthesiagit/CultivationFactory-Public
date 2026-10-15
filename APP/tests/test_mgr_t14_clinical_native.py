"""Real imported acquisition, source declarations, table intent and cold replay."""
from pathlib import Path
import json
import zipfile
import pytest
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet
ROOT=Path(__file__).resolve().parents[1]
PA='0badc0de-1414-4000-8000-000000000001'; PB='0badc0de-1414-4000-8000-000000000002'
PC='0badc0de-1414-4000-8000-000000000003'
A=FACTORY_ACTOR_PREFIX+PA; B=FACTORY_ACTOR_PREFIX+PB; C=FACTORY_ACTOR_PREFIX+PC


@pytest.fixture(autouse=True)
def final_native_mechanical_replay(tmp_path):
    yield
    combat=CombatService(ROOT,tmp_path)
    for path in combat.matches_root.iterdir():
        if path.is_dir():
            session=combat._load_session(path.name)
            assert session.mechanical.replay()['status']=='PASS'


def game(tmp_path,monkeypatch,spheres=('blood','life'),enemy=(),cl=10,talents=(),ally=False,cells=1,hp=500,enemy_hp=None,enemy_dc=1,weapon=False,owner_dc=50,body=False):
    monkeypatch.setattr('combat.journey.secrets.token_hex',lambda n:'14'*n)
    for pid in ((PA,PB,PC) if ally else (PA,PB)):
        doc=sheet([],cl=cl,dc=owner_dc if pid==PA else enemy_dc,name='Physician' if pid==PA else 'Patient')
        doc['identity']['path_ids']=['tianxia.path.qi_cultivation']
        doc['path_and_subpath']={'path_record_id':'tianxia.path.qi_cultivation','path_record_ids':['tianxia.path.qi_cultivation']}
        doc['ability_scores_and_statistics']['hit_points']={'maximum':enemy_hp if pid==PB and enemy_hp is not None else hp}
        if weapon and pid==PA:doc['equipment']=[{'starting_kit':{'items':[{'item_id':'tianxia.mortal.weapon.jian'}]}}]
        if body and pid==PA:
            doc['identity'].update(path='Body Refining',path_ids=['tianxia.path.body_refining'])
            doc['path_and_subpath']={'path_record_id':'tianxia.path.body_refining','path_record_ids':['tianxia.path.body_refining']}
            doc['ability_scores_and_statistics']['primary_resource']={'name':'Stamina','maximum':30}
        doc['ability_scores_and_statistics']['skills']=[{'skill':'medicine','bonus':100,'proficiency':'proficient'}]
        folder=tmp_path/'portable_characters'/pid; folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path); table=TabletopService(combat,tmp_path)
    from canonical_catalog import CanonicalCatalogAuthorityService
    table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
    for pid,names in ((PA,spheres),(PB,enemy)):
        for name in names:table.add_advancement(pid,'sphere','tianxia.sphere.'+name)
    for talent in talents:table.add_advancement(PA,'talent',talent)
    combat.tabletop_maps.save({'display_name':'Clinical yard','width_squares':68,'height_squares':10,
        'walls':[],'starts':{'team1':[[3,6],[3,5]],'team2':[[4,6]]}})
    state=combat.create_journey(project_ids=[PA,PB,PC] if ally else [PA,PB],arena_id='battlefield:map.clinical-yard',
        positions={A:{'x':3,'y':6},B:{'x':3+cells,'y':6},**({C:{'x':3,'y':5}} if ally else {})},
        base_paces={A:5,B:5,**({C:5} if ally else {})})
    jid=state['journey_id']
    def cold():return CombatService(ROOT,tmp_path)
    def command(kind,payload=None,actor=A):
        before=cold().journey_state(jid); result=cold().journey_act(jid,before['revision'],actor,kind,payload)
        assert cold().journey_state(jid)==result
        return result
    def world(kind,value,target=B,scope=None,readers=None):
        before=cold().journey_state(jid)
        result=cold().journey_world_fact(jid,before['revision'],{'source':'clinical_source','subject':target,'kind':kind,
            'scope':scope or kind,'value':value,'expires_at':int(before['seconds'])+100000,'readers':readers if readers is not None else [A]})
        assert cold().journey_state(jid)==result
        return result
    return cold,table,jid,command,world


def anatomy(world):
    for aid in (A,B):world('clinical_anatomy',{'living':1,'meaningful_circulation':1},target=aid)


def exposure(world,category='ordinary_bleeding',condition='bleeding',ongoing=0,excluded=(),label='Ordinary cut',readers=None):
    result=world('clinical_source',{'label':label,'category':category,'conditions':[condition],
        'ongoing':ongoing,'excluded':list(excluded),'dc':12},scope=label,readers=readers)
    return result['fact_consent_admission'][-1]['receipt_id']


def start(cold,jid,teams=None):
    state=cold().journey_state(jid)
    return cold().journey_start_combat(jid,state['revision'],teams or {aid:('team:b' if aid==B else 'team:a') for aid in state['actors']})['match_id']


def engine(cold,mid):
    e=cold()._load_session(mid).engine; fresh=cold()._load_session(mid).engine
    assert e.state.model_dump(mode='json')==fresh.state.model_dump(mode='json')
    assert [x.model_dump(mode='json') for x in e.events]==[x.model_dump(mode='json') for x in fresh.events]
    return fresh


def act(cold,table,mid,state,candidate,choose=None):
    answers=[]; menu=state['menu']
    for _ in range(40):
        result=table.act(mid,candidate,menu['decision_id'],menu['state_version'],state['last_sequence'],answers)
        if result['status']!='REACTION_REQUIRED':break
        p=result['reaction']; ids=[o['id'] for o in (p.get('choice') or {}).get('options',[])]
        selected=choose(p,ids) if choose else ids[:1]
        answers.append({**p['context'],'selection':'USE' if selected or choose is None and not p.get('choice') else 'DECLINE','option_ids':selected})
    assert result['status']=='COMMITTED',result
    engine(cold,mid)
    return result['state']


def turn(cold,table,mid,aid=A):
    for _ in range(20):
        state=table.state(mid)
        if state['menu']['actor_id']==aid:return state
        act(cold,table,mid,state,state['menu']['end_turn'],lambda p,ids:[])
    pytest.fail('Turn did not arrive')


def use(cold,table,mid,name,target=B,choose=None,aid=A):
    state=turn(cold,table,mid,aid)
    groups=[g for g in state['menu']['actions'] if g['label']==name]
    assert groups,(name,[g['label'] for g in state['menu']['actions']])
    options=[o for g in groups for o in g['options'] if target in o.get('target_ids',[])]
    assert options,(name,groups)
    return act(cold,table,mid,state,options[0]['candidate_id'],choose)


def next_round(cold,table,mid):
    state=turn(cold,table,mid)
    act(cold,table,mid,state,state['menu']['end_turn'],lambda p,ids:[])
    return turn(cold,table,mid)


def clinical(actor,category=None):
    return [c for c in actor.conditions.values() if c.data.get('clinical') and (category is None or c.data['clinical']['category']==category)]


def test_blood_consent_and_exact_one_source(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch); anatomy(world)
    first=exposure(world,label='First cut'); second=exposure(world,label='Second cut'); mid=start(cold,jid)
    use(cold,table,mid,'Blood Thread: willing creature (willing creature)')
    e=engine(cold,mid); assert any('blood_thread' in c.condition_id for c in e.state.actors[B].conditions.values())
    before=e.state.actors[A].resources['resource:core.qi']
    use(cold,table,mid,'Coagulate: End Bleeding (willing creature)')
    e=engine(cold,mid); remaining=clinical(e.state.actors[B],'ordinary_bleeding')
    assert len(remaining)==1 and remaining[0].data['clinical']['source_instance'] in (first,second)
    assert e.state.actors[A].resources['resource:core.qi']==before-1


@pytest.mark.parametrize('condition,category,ongoing,excluded,ends',[
    ('blinded','physical_impairment',0,(),True),('deafened','physical_impairment',0,(),True),
    ('paralyzed','physical_impairment',0,(),True),('poisoned','poison',0,(),True),('sickened','disease',0,(),True),
    ('blinded','physical_impairment',1,(),False),('blinded','physical_impairment',0,('curse',),False),
    ('poisoned','poison',0,('spiritual_binding',),False)])
def test_purify_sources(tmp_path,monkeypatch,condition,category,ongoing,excluded,ends):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('life',)); anatomy(world)
    exposure(world,category,condition,ongoing,excluded,'Authored ailment'); mid=start(cold,jid)
    label='Disease' if category=='disease' else condition.title()
    before=engine(cold,mid).state.actors[A].resources['resource:core.qi']
    use(cold,table,mid,'Purify the Pulse: Remove '+label+' (any living creature)')
    e=engine(cold,mid); held=clinical(e.state.actors[B],category)
    if not ongoing:assert bool(held) is not ends
    assert e.state.actors[A].resources['resource:core.qi']==before-1
    if ongoing:
        assert not held
        assert any(c.data.get('clinical_retained_source') for c in e.state.actors[B].conditions.values())
        assert not any(c.condition_id=='condition:typed.blinded' for c in e.state.actors[B].conditions.values())
        for _ in range(2):next_round(cold,table,mid)
        held=clinical(engine(cold,mid).state.actors[B],category)
        assert held and not any(c.data.get('suppressed') for c in held)


@pytest.mark.parametrize('circulation,living',[(None,1),(0,1),(1,None),(1,0)])
def test_anatomy_unknown_and_negative(tmp_path,monkeypatch,circulation,living):
    cold,table,jid,command,world=game(tmp_path,monkeypatch)
    world('clinical_anatomy',{k:v for k,v in [('meaningful_circulation',circulation),('living',living)] if v is not None})
    mid=start(cold,jid); state=turn(cold,table,mid)
    offers=[g for g in state['menu']['actions'] if any(B in o.get('target_ids',[]) for o in g['options'])]
    if circulation!=1:assert not any(g['label'].startswith('Blood Thread') for g in offers)
    if living!=1:assert not any(g['label'].startswith('Purify the Pulse') for g in offers)


def test_procedure_payment_time_consent_and_cure(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=())
    group=exposure(world,'poison','poisoned',label='External minor poison')
    world('clinical_protocol',{'method':'Medicine','ability':'WIS','skill':'medicine','seconds':60,
        'costs':{'resource:core.qi':1},'operation':'treat','source_instance':group},scope='ordinary_medicine')
    payload={'target':B,'source_instance':group,'protocol_scope':'ordinary_medicine'}; before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='consent'):command('clinical_treat',payload)
    assert cold().journey_state(jid)==before
    command('declare_fact',{'source':'clinical_source','subject':B,'kind':'clinical_consent','scope':'ordinary_medicine:'+group+':'+A,
        'value':1,'expires_at':3600,'readers':[A]},actor=B)
    done=command('clinical_treat',payload)
    assert done['seconds']==60 and done['actors'][A]['resources']['resource:core.qi']==before['actors'][A]['resources']['resource:core.qi']-1
    assert not done['actors'][B]['encounter_snapshot']['conditions']
    roll=next(e for e in done['events'] if e['kind']=='CLINICAL_CHECK_ROLLED'); assert roll['dc']==12 and roll['success']==1


def test_world_authority_validation_and_privacy(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=()); before=cold().journey_state(jid)
    payload={'source':'clinical_source','subject':B,'kind':'clinical_source','scope':'hidden','value':{},'expires_at':100,'readers':[]}
    with pytest.raises(ValueError):command('declare_fact',payload,actor=B)
    assert cold().journey_state(jid)==before
    with pytest.raises(ValueError):world('clinical_source',{'done':1})
    assert cold().journey_state(jid)==before
    exposure(world,'disease','sickened',label='Private diagnosis',readers=[B])
    from combat.fact_consent_admission import read
    session=cold().journeys.load(jid)
    assert read(session,'clinical_source',B,'clinical_source','Private diagnosis',A) is None
    assert read(session,'clinical_source',B,'clinical_source','Private diagnosis',B)


@pytest.mark.parametrize('choice',['Bitter Breath','Numb Channels','Sour Blood','Clouded Senses','Heavy Pulse'])
def test_ingrain_post_failed_save(tmp_path,monkeypatch,choice):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('poison',)); anatomy(world); mid=start(cold,jid)
    from combat.ext.stacking_marks import count
    for _ in range(8):
        e=engine(cold,mid)
        if count(e,e.state.actors[A],e.state.actors[B],'Dose Mark')>=2:break
        use(cold,table,mid,'Deliver the Dose'); next_round(cold,table,mid)
    e=engine(cold,mid); assert count(e,e.state.actors[A],e.state.actors[B],'Dose Mark')>=2
    before=e.state.actors[A].resources['resource:core.qi']
    use(cold,table,mid,'Ingrain the Toxin: Bitter Breath',choose=lambda p,ids:[choice] if choice in ids else ids[:1])
    e=engine(cold,mid); toxins=[c for c in e.state.actors[B].conditions.values() if c.condition_id=='condition:typed.minor_ingrained_toxin']
    assert len(toxins)==1 and toxins[0].data['choice']==choice
    assert toxins[0].data['clinical']['dc']==50 and toxins[0].expires_on=='UNTIL_REMOVED'
    assert e.state.actors[A].resources['resource:core.qi']==before-2
    assert count(e,e.state.actors[A],e.state.actors[B],'Dose Mark')<2


def area(cold,table,mid,name,choose):
    state=turn(cold,table,mid)
    group=next(g for g in state['menu']['actions'] if g['label']==name)
    options=[o for o in group['options'] if o.get('destination')]
    option=min(options,key=lambda o:abs(o['destination']['x']-4)+abs(o['destination']['y']-6))
    return act(cold,table,mid,state,option['candidate_id'],choose)


def test_native_veil_outbreak_damage_choice_and_cold_zone(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('disease',))
    mid=start(cold,jid)
    area(cold,table,mid,'Raise the Quarantine Veil: Outbreak Mode',lambda p,ids:['psychic'] if 'psychic' in ids else ids[:1])
    e=engine(cold,mid); zone=next(z for z in e.state.zones.values() if z.active)
    assert zone.trigger_profile['veil_damage_type']=='psychic'
    assert e.state.actors[A].resources['resource:core.qi']==28
    next_round(cold,table,mid)
    e=engine(cold,mid)
    packets=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and B in v.target_ids]
    assert packets and all(v.payload['damage_type']=='PSYCHIC' for v in packets)
    assert any(c.condition_id=='condition:typed.sickened' for c in e.state.actors[B].conditions.values()) is False


def test_native_containment_chosen_hostile_recipient(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('disease',))
    mid=start(cold,jid)
    area(cold,table,mid,'Raise the Quarantine Veil: Containment Mode',lambda p,ids:['invisible'] if 'invisible' in ids else [B] if B in ids else ids[:1])
    e=engine(cold,mid); zone=next(z for z in e.state.zones.values() if z.active)
    assert zone.trigger_profile['veil_recipients']==[B]
    assert zone.trigger_profile['visual']['invisible']==1
    from combat.typed_executor import condition_rules
    assert any(r.get('disease_containment') for r in condition_rules(e.state.actors[B]))
    assert not any(r.get('disease_containment') for r in condition_rules(e.state.actors[A]))


def test_native_succor_luck_success_save_sacrifices_before_reroll(tmp_path,monkeypatch):
    luck='tianxia.talent.protection.luck'
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('protection',),enemy=('disease',),talents=(luck,),ally=True)
    table.buttons.save_reactions(PA,{'mode':'ask'},{luck})
    mid=start(cold,jid)
    use(cold,table,mid,'Aegis: Armored Aegis (Persistent)',target=C)
    e=engine(cold,mid)
    from combat.ext.protection import aegises
    assert aegises(e.state.actors[C],A,persistent=True)
    use(cold,table,mid,'Sow the Fever Seed',target=C,aid=B)
    e=engine(cold,mid)
    assert not aegises(e.state.actors[C],A,persistent=True)
    rewrites=[v for v in e.events if v.event_type=='D20_REWRITTEN' and v.source_definition_id==luck]
    assert rewrites
    original=rewrites[0].payload.get('original') or {}
    assert original['total']>=1  # The old failed-save-only trigger must miss this.
    removal=next(v for v in e.events if v.event_type=='CONDITION_REMOVED' and v.payload.get('reason')=='SACRIFICED')
    assert removal.sequence<rewrites[0].sequence


@pytest.mark.parametrize('cells,allowed',[(12,True),(13,False)])
def test_thread_native_range_boundary(tmp_path,monkeypatch,cells,allowed):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('blood',),cells=cells)
    anatomy(world); mid=start(cold,jid); state=turn(cold,table,mid)
    offered=any(g['label'].startswith('Blood Thread: willing creature') and any(B in o.get('target_ids',[]) for o in g['options'])
                for g in state['menu']['actions'])
    assert offered is allowed
    if allowed:use(cold,table,mid,'Blood Thread: willing creature (willing creature)')


@pytest.mark.parametrize('cl', [10,11,17])
def test_coagulate_native_temp_hp_bands(tmp_path,monkeypatch,cl):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('blood',),cl=cl)
    anatomy(world); mid=start(cold,jid)
    use(cold,table,mid,'Blood Thread: willing creature (willing creature)')
    use(cold,table,mid,'Coagulate: Temporary HP (willing creature)')
    e=engine(cold,mid); base=e.state.actors[A].proficiency_bonus+2
    count=2 if cl>=17 else 1 if cl>=11 else 0
    assert base+count<=e.state.actors[B].temporary_hp<=base+count*8


def test_thread_recipient_refusal_is_nonmutating_until_committed(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('blood',))
    anatomy(world); mid=start(cold,jid); state=turn(cold,table,mid)
    group=next(g for g in state['menu']['actions'] if g['label']=='Blood Thread: willing creature (willing creature)')
    option=next(o for o in group['options'] if B in o.get('target_ids',[])); menu=state['menu']
    before=engine(cold,mid).state.model_dump(mode='json')
    paused=table.act(mid,option['candidate_id'],menu['decision_id'],menu['state_version'],state['last_sequence'],[])
    assert paused['status']=='REACTION_REQUIRED'
    assert paused['reaction']['context']['reactor_id']==B
    assert engine(cold,mid).state.model_dump(mode='json')==before
    act(cold,table,mid,state,option['candidate_id'],lambda p,ids:[])
    e=engine(cold,mid)
    assert not any('blood_thread' in c.condition_id for c in e.state.actors[B].conditions.values())
    assert e.state.actors[B].current_hp==500 and e.state.actors[A].resources['resource:core.qi']==30


def test_wrong_thread_owner_does_not_offer_coagulate(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('blood',),enemy=('blood',),ally=True)
    anatomy(world); world('clinical_anatomy',{'living':1,'meaningful_circulation':1},target=C)
    mid=start(cold,jid)
    use(cold,table,mid,'Blood Thread: willing creature (willing creature)',target=C,aid=B)
    state=turn(cold,table,mid)
    assert not any(g['label'].startswith('Coagulate') and any(C in o.get('target_ids',[]) for o in g['options'])
                   for g in state['menu']['actions'])


def test_coagulate_native_stabilization(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=('blood',),hp=35,ally=True)
    anatomy(world); mid=start(cold,jid,{A:'team:a',B:'team:b',C:'team:b'})
    # Every wound comes from the actual ranged Cultivation Attack. The target
    # explicitly refuses the automatic Thread; no HP/life-state patch is made.
    for _ in range(8):
        def refuse(p,ids):return [] if p['context'].get('reactor_id')==B else ids[:1]
        use(cold,table,mid,'Blood Thread',choose=refuse)
        e=engine(cold,mid)
        if e.state.actors[B].current_hp==0:break
        next_round(cold,table,mid)
    assert e.state.actors[B].current_hp==0 and e.state.actors[B].life_state=='DYING'
    use(cold,table,mid,'Coagulate: Stabilize (willing creature)')
    e=engine(cold,mid)
    assert e.state.actors[B].current_hp==0 and e.state.actors[B].life_state=='STABLE'


def test_native_toxin_survives_source_defeat_and_ends_at_actual_long_rest(tmp_path,monkeypatch):
    cold,table,jid,command,world=game(tmp_path,monkeypatch,spheres=(),enemy=('poison',),
        enemy_dc=50,enemy_hp=35,weapon=True)
    anatomy(world);mid=start(cold,jid)
    from combat.ext.stacking_marks import count
    for _ in range(8):
        e=engine(cold,mid)
        if count(e,e.state.actors[B],e.state.actors[A],'Dose Mark')>=2:break
        use(cold,table,mid,'Deliver the Dose',target=A,aid=B)
        state=turn(cold,table,mid,B)
        act(cold,table,mid,state,state['menu']['end_turn'],lambda p,ids:[])
    use(cold,table,mid,'Ingrain the Toxin: Bitter Breath',target=A,aid=B,
        choose=lambda p,ids:['Numb Channels'] if 'Numb Channels' in ids else ids[:1])
    for _ in range(20):
        e=engine(cold,mid)
        if e.state.terminal_result is not None:break
        state=turn(cold,table,mid,A)
        groups=[g for g in state['menu']['actions'] if g['label'].startswith('Jian')]
        assert groups,[g['label'] for g in state['menu']['actions']]
        option=next(o for g in groups for o in g['options'] if B in o.get('target_ids',[]))
        act(cold,table,mid,state,option['candidate_id'])
        if engine(cold,mid).state.terminal_result is None:next_round(cold,table,mid)
    e=engine(cold,mid);assert e.state.terminal_result is not None
    assert any(c.condition_id=='condition:typed.minor_ingrained_toxin' for c in e.state.actors[A].conditions.values())
    state=cold().journey_state(jid)
    resumed=cold().journey_resume(jid,state['revision'])
    records=resumed['actors'][A]['encounter_snapshot']['conditions']
    assert any(json.loads(v)['condition_id']=='condition:typed.minor_ingrained_toxin' for v in records.values())
    rested=command('long_rest')
    assert rested['seconds']>=28800
    assert not any(json.loads(v)['condition_id']=='condition:typed.minor_ingrained_toxin'
                   for v in rested['actors'][A]['encounter_snapshot']['conditions'].values())
