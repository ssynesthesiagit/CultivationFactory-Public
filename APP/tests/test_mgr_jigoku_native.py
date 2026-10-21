"""Native Jigoku acquisition, accepted table intents, cold mechanical replay."""
import json
import zipfile
import itertools
import pytest
from combat.gate5_service import CombatService, CombatServiceError, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import settle
SOURCE='tianxia.subpath.body.jigoku'
PREFIX=SOURCE+'.feature.'
KEY='jigoku:acquisition'

PIDS=['0badc0de-0000-4000-8000-000000000081','0badc0de-0000-4000-8000-000000000082']
A,B=[FACTORY_ACTOR_PREFIX+p for p in PIDS]
IRON='tianxia.path.body_refining.feature.iron_fist'


def test_pain_eater_damage_type_menu_includes_independent_fire_packet(monkeypatch):
    from types import SimpleNamespace
    from combat.ext import jigoku
    from combat.ext import condition_events, needle
    from combat import typed_executor
    actor=SimpleNamespace(entity_id='jigoku-owner',display_name='Jigoku Owner',turn_flags={},proficiency_bonus=3,conditions={})
    target=SimpleNamespace(entity_id='marked-foe',display_name='Marked Foe',conditions={
        'mark':SimpleNamespace(instance_id='mark',condition_id=jigoku.MARK,source_actor_id=actor.entity_id,
            data={'numbers':{'pb':3}})})
    engine=SimpleNamespace(state=SimpleNamespace(round_number=1,current_actor_id=actor.entity_id,actors={actor.entity_id:actor}))
    class HitContext:
        source='tianxia.natural.unarmed'
        typed={'effects':[{'type':'attack','attack_kind':'unarmed'}]}
        intent=object()
        action=SimpleNamespace(display_name='Unarmed strike')
        attack_defense_spec={'damage_type':'BLUDGEONING'}
        damage_cache={}
        def __init__(self):
            self.actor=actor
            self.engine=engine
        def on_hit_context(self,*args,**kwargs):return self
    HitContext=HitContext()
    seen={}
    monkeypatch.setattr(condition_events,'drop_condition',lambda *args,**kwargs:None)
    monkeypatch.setattr(needle,'ask',lambda *args,**kwargs:(seen.setdefault('options',args[5]) and ['FIRE']))
    monkeypatch.setattr(needle,'checkpoint_id',lambda *args:'pain-type')
    monkeypatch.setattr(typed_executor,'run_effects',lambda ctx,effects:seen.setdefault('effects',effects))
    jigoku.hit_packet(HitContext,target,('BLUDGEONING','FIRE'))
    assert seen['options']==['BLUDGEONING','FIRE']
    assert seen['effects'][0]['damage_types']==['fire']
    assert seen['effects'][0]['flat']==3


def game(tmp_path,monkeypatch,cl=18,access=True,fire=False,observer_type=None,hazard=False,inside_hazard=False,burning_weapon=False,attack_sphere=None,hazard_terrain="fire terrain",third=False,magma_smoke=False,foe_x=3,arena_width=10,arena_height=10,published_arena=False,foe_cl=None,stock_spawn=None):
    serial=itertools.count(142)
    monkeypatch.setattr("secrets.token_hex",lambda size: format(next(serial), "x").zfill(size*2))
    pids=PIDS+(['0badc0de-0000-4000-8000-000000000083'] if third else [])
    for i,pid in enumerate(pids):
        level=foe_cl if i==1 and foe_cl is not None else cl
        pb=2+(level-1)//4
        doc=sheet([],cl=level,name='Ember' if i==0 else 'Challenger',primary='Stamina',dc=8+pb+2)
        doc['identity']['proficiency_bonus']=pb
        doc['identity']['path']='Body Refining'
        if i==1 and observer_type:doc['identity']['creature_types']=[observer_type]
        doc['path_and_subpath']={'path_record_ids':['tianxia.path.body_refining'],'path_feature_record_ids':[IRON]}
        qi_caster=i==1 and attack_sphere in ('tianxia.sphere.force','tianxia.sphere.space','tianxia.sphere.ash')
        if qi_caster:
            doc['identity'].update(path='Qi Cultivation',key_ability='INT')
            doc['path_and_subpath']={'path_record_ids':['tianxia.path.qi_cultivation'],'path_feature_record_ids':[]}
        stats=doc['ability_scores_and_statistics']
        stats['primary_resource']['maximum']=level*2
        stats['hit_points']['maximum']=14+9*(level-1)
        stats['technique_attack_bonus']=pb+2
        stats['skills']=[{'skill':skill,'bonus':pb+2,'proficiency':'Proficient'} for skill in (('Arcana','Perception') if qi_caster else ('Athletics','Perception'))]
        if qi_caster:
            stats['primary_resource'].update(name='Qi',maximum=level*2)
            stats['hit_points']['maximum']=10+7*(level-1)
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    from combat.tabletop import table_section
    arena_presentation=table_section({'map_id':'native-world-scene','walls':[],'background':{},'display':{}}) if published_arena else {}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'test':{
        'stable_id':'journey:jigoku','display_name':'Jigoku proving ground','width_squares':arena_width,'height_squares':arena_height,'square_size_ft':5,
        'starting_positions':({stock_spawn:{'x':3,'y':2},A:{'x':2,'y':2}} if stock_spawn else {}),'terrain_regions':[],
        **({'tabletop':arena_presentation} if published_arena else {}),
        **({'map_terrain':[{'terrain':hazard_terrain,'cells':[[2,2],[3,2]] if inside_hazard else [[2,3]],'save_dc':30,'pb':10}]} if hazard else {})}})
    cold=lambda:CombatService(ROOT,tmp_path)
    if fire or attack_sphere:
        from canonical_catalog.service import CanonicalCatalogAuthorityService
        table=TabletopService(cold(),tmp_path)
        table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
        table.add_advancement(PIDS[1],'sphere',attack_sphere or 'tianxia.sphere.fire')
        if burning_weapon:table.add_advancement(PIDS[1],'talent','FIRE_TAL_BURNING_WEAPON')
    if magma_smoke:
        from canonical_catalog.service import CanonicalCatalogAuthorityService
        table=TabletopService(cold(),tmp_path);table.canonical_catalog=CanonicalCatalogAuthorityService(ROOT)
        for pid in PIDS:
            table.add_advancement(pid,'sphere','tianxia.sphere.magma')
            table.add_advancement(pid,'talent','TAL_MAGMA_VOLCANIC_SMOKE')
    positions={A:{'x':2,'y':2},B:{'x':foe_x,'y':2}}
    if third:positions[FACTORY_ACTOR_PREFIX+pids[2]]={'x':3,'y':3}
    s=cold().create_journey(project_ids=pids,arena_id='test',positions=positions,base_paces={a:1800 for a in positions})
    jid=s['journey_id']
    if access:
        s=cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':A,'kind':'legal_access','scope':'acquisition',
            'value':'The table owner admits the Forbidden Method scripture held by Ember.','expires_at':31536000,'readers':[]})
    def acquire(aid=A):
        s=cold().journey_state(jid)
        return cold().journey_acquire_source(jid,s['revision'],aid,SOURCE,{'scar_locations':'arms','scar_appearance':'permanent red lines','covered':1})
    return cold,jid,acquire


def combat(cold,jid,rounds=15,*,allies=()):
    s=cold().journey_state(jid)
    result=cold().journey_start_combat(jid,s['revision'],{aid:'team:a' if aid==A or aid in allies else 'team:b' for aid in s['actors']},maximum_rounds=rounds)
    mid=result['match_id'];service=cold();table=TabletopService(service,service.userdata_root)
    return service,table,mid


def reload(cold,mid):
    s=cold()._load_session(mid)
    assert s.mechanical.replay()['status']=='PASS'
    return s.engine


def turn(table,mid,aid):
    for _ in range(30):
        try:state=table.state(mid)
        except CombatServiceError as error:raise AssertionError(error.diagnostic.details) from error
        if state['menu']['actor_id']==aid:return
        settle(table,mid,state['menu']['end_turn'],choices={})
    raise AssertionError('No turn')


def candidate(service,mid,name,target=None,at=None):
    engine=service._load_session(mid).engine
    rows=[c for c in engine.legal_candidates() if engine.action_catalog.get(c.source_definition_id) and name in engine.action_catalog[c.source_definition_id].display_name
          and (name!='Ignite' or engine.action_catalog[c.source_definition_id].display_name=='Ignite: Push Target')
          and (':' not in name or engine.action_catalog[c.source_definition_id].display_name==name)
          and (target is None or c.target_ids==(target,))
          and (at is None or c.destination and (c.destination.x,c.destination.y)==at)]
    from combat.action_legality import query
    assert rows,(name,{k:query(engine,engine.state.current_actor_id,k) for k,a in engine.action_catalog.items() if name in a.display_name})
    return rows[0]


def move_caster_out_of_melee(service,table,mid):
    """A real ranged attacker steps out of adjacent-enemy Disadvantage."""
    turn(table,mid,B)
    engine=service._load_session(mid).engine
    if (engine.state.actors[B].position.x,engine.state.actors[B].position.y)==(4,2):return
    settle(table,mid,candidate(service,mid,'Disengage').candidate_id,choices={})
    engine=service._load_session(mid).engine
    step=next(c for c in engine.legal_candidates() if str(getattr(c.kind,'value',c.kind))=='MOVE'
        and c.destination and (c.destination.x,c.destination.y)==(4,2))
    settle(table,mid,step.candidate_id,choices={})
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,B)


def test_native_access_required_atomic(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,access=False)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='legal Forbidden Method'):acquire()
    assert cold().journey_state(jid)==before


@pytest.mark.parametrize('cl', [3,6,10,14,18])
def test_native_progression_cold_acquisition(tmp_path,monkeypatch,cl):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl)
    s=acquire()
    assert KEY in cold().journey_state(jid)['actors'][A]['source_states']
    encoded=json.dumps(s['actors'][A]['bundle'])
    for level,name in ((3,'hell_tempered'),(6,'pain_eater'),(10,'flame_fist'),(14,'hellwalker'),(18,'asura_s_rage')):
        assert (PREFIX+name in encoded)==(cl>=level)
    assert cold().journey_verify(jid)['status']=='PASS'
    service,table,mid=combat(cold,jid)
    engine=reload(cold,mid)
    assert not [r for r in engine.typed_passive_rows.get(B,[]) if r.get('kind')=='jigoku']


def test_asura_cost_cold_replay(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    before=reload(cold,mid).state.actors[A].resources['resource:core.stamina']
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    engine=reload(cold,mid);actor=engine.state.actors[A]
    assert actor.resources['resource:core.stamina']==before-7
    assert any(c.condition_id=='condition:typed.state.asura_s_rage' for c in actor.conditions.values())
    assert not actor.bonus_action_available


@pytest.mark.parametrize('cl,dice',[(10,1),(17,2)])
def test_brand_native_unarmed_play(tmp_path,monkeypatch,cl,dice):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=cl)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    picks={'choice:needle.path_hit.'+PREFIX+'flame_fist':['Use Burning Brand']}
    prompts=settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
    engine=reload(cold,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.path_hit.'+PREFIX+'flame_fist' for p in prompts)
    assert any(e.event_type=='SAVE_ROLLED' and (B in e.target_ids or e.actor_id==B) for e in engine.events)
    assert any(r.expression.startswith(str(dice)+'d8') and 'DAMAGE' in r.reason for r in engine.rolls)


@pytest.mark.parametrize('benefit',['temp_hp','move','save','no_reactions'])
def test_native_pain_mark_damage_and_benefit(tmp_path,monkeypatch,benefit):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=6)
    acquire();service,table,mid=combat(cold,jid)
    picks={'choice:needle.fact_admission.hostile_intent':['genuine'], 'choice:needle.pain_eater':['mark'],
           'choice:needle.pain_eater_benefit':[benefit], 'choice:needle.pain_eater_move':['cell:2,1']}
    marked=False
    for _ in range(8):
        turn(table,mid,B)
        settle(table,mid,candidate(service,mid,'Iron Fist',A).candidate_id,picks)
        engine=reload(cold,mid)
        marked=any(c.condition_id=='condition:typed.pain_eater_mark' for c in engine.state.actors[B].conditions.values())
        if marked:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert marked
    turn(table,mid,A)
    start=reload(cold,mid).state.event_sequence
    prompts=settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
    engine=reload(cold,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.pain_eater_benefit' for p in prompts)
    assert not any(c.condition_id=='condition:typed.pain_eater_mark' for c in engine.state.actors[B].conditions.values())
    owner=engine.state.actors[A]
    if benefit=='no_reactions':assert any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[B].conditions.values())
    elif benefit=='temp_hp':assert owner.temporary_hp==owner.proficiency_bonus
    elif benefit=='move':assert (owner.position.x,owner.position.y)==(2,1)
    else:
        held,=[c for c in owner.conditions.values() if c.condition_id=='condition:typed.save_against']
        assert held.data['rule']['save_against']['mode']=='ADVANTAGE' and held.data['rule']['save_against']['next']
        assert set(held.data['rule']['save_against']['abilities'])=={'STR','DEX','CON','INT','WIS','CHA'}
    assert not [e for e in engine.events if e.sequence>start and e.event_type=='REACTION_WINDOW_OPENED' and e.payload.get('checkpoint')=='LEAVE_REACH']
    rolls=[e for e in engine.events if e.sequence>start and e.event_type=='ATTACK_ROLLED' and e.actor_id==A and B in e.target_ids]
    first=rolls[0].sequence;end=rolls[1].sequence if len(rolls)>1 else engine.state.event_sequence+1
    packets=[e for e in engine.events if first<e.sequence<end and e.event_type=='DAMAGE_COMMITTED' and e.actor_id==A and B in e.target_ids]
    assert len(packets)==1  # The PB rider belongs to the strike's one packet.
    if benefit=='save':
        turn(table,mid,B)
        boundary=reload(cold,mid).state.event_sequence
        settle(table,mid,candidate(service,mid,'Shove: Prone',A).candidate_id,choices={})
        saved=reload(cold,mid)
        roll=next(e for e in saved.events if e.sequence>boundary and e.event_type=='SAVE_ROLLED' and e.actor_id==A)
        assert roll.payload['mode']=='ADVANTAGE'
        assert not any(c.condition_id=='condition:typed.save_against' for c in saved.state.actors[A].conditions.values())



@pytest.mark.parametrize('intent',['genuine','weakened','cooperative','staged'])
def test_native_eat_flame_anti_farming(tmp_path,monkeypatch,intent):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,fire=True)
    acquire();service,table,mid=combat(cold,jid)
    move_caster_out_of_melee(service,table,mid)
    picks={'choice:needle.fact_admission.hostile_intent':[intent],'choice:needle.eat_the_flame':['eat']}
    for _ in range(8):
        turn(table,mid,B)
        before=reload(cold,mid)
        hp=before.state.actors[A].current_hp
        stamina=before.state.actors[A].resources['resource:core.stamina']
        settle(table,mid,candidate(service,mid,'Ignite',A).candidate_id,picks)
        final=reload(cold,mid);actor=final.state.actors[A]
        if actor.current_hp<hp:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert actor.current_hp<hp
    assert actor.resources['resource:core.stamina']==stamina-(intent=='genuine')
    assert actor.temporary_hp==(min(hp-actor.current_hp,2*actor.proficiency_bonus) if intent=='genuine' else 0)


def end_encounter(table,mid):
    for _ in range(40):
        state=table.state(mid)
        if table.combat._load_session(mid).engine.state.terminal_result:return
        settle(table,mid,state['menu']['end_turn'],choices={})
    raise AssertionError('Encounter did not finish')


def test_rage_expiry_native_aftermath_and_rites(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,observer_type='infernal')
    acquire()
    # Directional signal is plane-scoped; the table owner records the same
    # plane for both creatures rather than the test assuming an unknown plane.
    s=cold().journey_state(jid)
    for aid in (A,B):
        s=cold().journey_world_fact(jid,s['revision'],{'source':'system:scene.fields','subject':aid,'kind':'plane',
            'scope':'scene','value':{'plane_id':'the-material-plane'},'expires_at':s['seconds']+3600,'readers':[]})
    service,table,mid=combat(cold,jid);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    end_encounter(table,mid)
    final=reload(cold,mid);owner=final.state.actors[A]
    assert not any(c.condition_id=='condition:typed.state.asura_s_rage' for c in owner.conditions.values())
    for cid in ('condition:typed.exhaustion','condition:typed.directional_signal','condition:typed.eat_the_flame_spent'):
        assert any(c.condition_id==cid for c in owner.conditions.values()),cid
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    assert cold().journey_menu(jid,B)['properties']['hell_signaled_directions']==['west: same Realm']
    s=cold().journey_end_scene(jid,s['revision'],'The immediate fight has ended; the party is safe to cool down.')
    def act(kind,payload):
        s=cold().journey_state(jid)
        result=cold().journey_act(jid,s['revision'],A,kind,payload)
        assert cold().journey_verify(jid)['status']=='PASS'
        return result
    start={'source':SOURCE+'.cooling_rite','parameters':{}}
    act('activity_start',start);act('activity_work',{'seconds':599});s=act('wait',{'seconds':1})
    assert 'journey:activity' not in s['actors'][A]['source_states']
    assert any(json.loads(c)['condition_id']=='condition:typed.eat_the_flame_spent' for c in s['actors'][A]['encounter_snapshot']['conditions'].values())
    act('activity_start',start);s=act('activity_work',{'seconds':600})
    ids=[json.loads(c)['condition_id'] for c in s['actors'][A]['encounter_snapshot']['conditions'].values()]
    assert 'condition:typed.eat_the_flame_spent' not in ids
    assert 'condition:typed.directional_signal' in ids
    act('activity_start',{'source':SOURCE+'.cultivation_session','parameters':{}});s=act('activity_work',{'seconds':7200})
    ids=[json.loads(c)['condition_id'] for c in s['actors'][A]['encounter_snapshot']['conditions'].values()]
    assert 'condition:typed.directional_signal' not in ids
    assert 'condition:typed.exhaustion' in ids
    assert not cold().journey_menu(jid,B)['properties'].get('hell_signaled_directions')
    assert s['actors'][A]['resources']['resource:core.stamina']==36
    # A second complete session clears aftermath but cannot recharge again
    # until a real eight-hour Long Rest changes the native rest counter.
    act('activity_start',{'source':SOURCE+'.cultivation_session','parameters':{}})
    s=act('activity_work',{'seconds':7200})
    assert len([e for e in s['events'] if e['kind']=='JIGOKU_STAMINA_RECOVERED' and e['source']==SOURCE+'.cultivation_session'])==1
    s=act('long_rest',{})
    act('activity_start',{'source':SOURCE+'.cultivation_session','parameters':{}})
    s=act('activity_work',{'seconds':7200})
    assert len([e for e in s['events'] if e['kind']=='JIGOKU_STAMINA_RECOVERED' and e['source']==SOURCE+'.cultivation_session'])==2


def test_unknown_source_wrong_owner_and_low_cl_guards(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=2)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError,match='CL3'):acquire()
    with pytest.raises(ValueError,match='unique native acquisition'):
        cold().journey_acquire_source(jid,before['revision'],A,'unowned:source',{})
    with pytest.raises(ValueError):
        cold().journey_act(jid,before['revision'],B,'activity_start',{'source':SOURCE+'.cooling_rite','parameters':{}})
    assert cold().journey_state(jid)==before


@pytest.mark.parametrize('benefit',['temp_hp','move','advantage','terrain'])
def test_hellwalker_native_area_and_all_choices(tmp_path,monkeypatch,benefit):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=14,fire=True)
    acquire();service,table,mid=combat(cold,jid)
    turn(table,mid,B)
    settle(table,mid,candidate(service,mid,'Conflagration',at=(2,2)).candidate_id,choices={})
    before=reload(cold,mid);hp=before.state.actors[A].current_hp
    pos=before.state.actors[A].position
    prompts=settle(table,mid,table.state(mid)['menu']['end_turn'],{
        'choice:needle.hellwalker':[benefit], 'choice:needle.hellwalker_move':'first'})
    engine=reload(cold,mid);actor=engine.state.actors[A]
    assert actor.current_hp==hp
    assert any(p['context']['reaction_source_id']=='choice:needle.hellwalker' for p in prompts)
    if benefit=='temp_hp':assert actor.temporary_hp==actor.proficiency_bonus
    elif benefit=='move':assert actor.position!=pos and engine.grid.in_bounds((actor.position.x,actor.position.y))
    elif benefit=='terrain':assert any(c.condition_id=='condition:typed.hellwalker_ignores_difficult' for c in actor.conditions.values())
    else:
        assert any(c.condition_id=='condition:typed.hellwalker_unarmed_advantage' for c in actor.conditions.values())
        settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,choices={})
        after=reload(cold,mid)
        assert not any(c.condition_id=='condition:typed.hellwalker_unarmed_advantage' for c in after.state.actors[A].conditions.values())
        assert next(e for e in reversed(after.events) if e.event_type=='ATTACK_ROLLED' and e.actor_id==A).payload['mode']=='ADVANTAGE'


@pytest.mark.parametrize('reaction_mode',['auto','ask'])
def test_human_eat_choice_on_ai_turn_uses_native_source_history(tmp_path,monkeypatch,reaction_mode):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,fire=True)
    TabletopService(cold(),tmp_path).save_reactions(PIDS[0],{'mode':reaction_mode})
    acquire();s=cold().journey_state(jid)
    cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':B,'kind':'hostility','scope':'combat',
        'value':{'hostile_to':[A],'cooperative':0,'staged':0,'weakened':0,'captured':0,'revived':0,'controlled':0},
        'expires_at':86400,'readers':[]})
    service,table,mid=combat(cold,jid);turn(table,mid,B)
    move_caster_out_of_melee(service,table,mid)
    service.set_controller_mode(mid,actor_id=B,controller_mode='LOCAL_AUTO')
    chosen=candidate(service,mid,'Ignite',A).candidate_id
    from tests.r1i_service_support import force_ai_candidate
    force_ai_candidate(service,mid,B,chosen)
    prompts=settle(table,mid,chosen,{'choice:needle.eat_the_flame':['eat']},auto=True)
    final=reload(cold,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' for p in prompts)
    assert final.state.actors[A].temporary_hp>0


def test_native_acquisition_preserves_reaction_plan_and_rejects_other_progression(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    table=TabletopService(cold(),tmp_path)
    table.save_reactions(PIDS[0],{'mode':'ask'})
    result=acquire()
    assert result['actors'][A]['bundle']['reaction_plan']['mode']=='ask'
    with pytest.raises(ValueError,match='already acquired'):acquire()


def test_gm_staged_source_cannot_be_overridden_by_attacker(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,fire=True)
    acquire();s=cold().journey_state(jid)
    s=cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':B,'kind':'hostility','scope':'combat',
        'value':{'hostile_to':[A],'cooperative':0,'staged':1,'weakened':0,'captured':0,'revived':0,'controlled':0},
        'expires_at':86400,'readers':[]})
    assert cold().journey_verify(jid)['status']=='PASS'
    service,table,mid=combat(cold,jid);turn(table,mid,B)
    move_caster_out_of_melee(service,table,mid)
    hp=reload(cold,mid).state.actors[A].current_hp
    before=reload(cold,mid).state.actors[A].resources['resource:core.stamina']
    prompts=settle(table,mid,candidate(service,mid,'Ignite',A).candidate_id,{
        'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.eat_the_flame':['eat']})
    owner=reload(cold,mid).state.actors[A]
    assert not any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' for p in prompts)
    assert owner.current_hp<hp
    assert owner.resources['resource:core.stamina']==before and owner.temporary_hp==0


def test_native_scar_covering_survives_next_encounter_once(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();service,table,mid=combat(cold,jid,rounds=1);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,'Record physical covering').candidate_id,{'choice:needle.jigoku_cover':['visible']})
    first=reload(cold,mid)
    scar,=[c for c in first.state.actors[A].conditions.values() if c.condition_id=='condition:typed.jigoku_scars']
    assert scar.data['covered']==0
    end_encounter(table,mid)
    s=cold().journey_state(jid);cold().journey_resume(jid,s['revision'])
    service,table,second=combat(cold,jid,rounds=1)
    restored=reload(cold,second)
    scar,=[c for c in restored.state.actors[A].conditions.values() if c.condition_id=='condition:typed.jigoku_scars']
    assert scar.data['covered']==0
    assert len([c for c in restored.state.actors[A].conditions.values() if c.condition_id=='condition:typed.jigoku_scene'])==1


def test_native_ordinary_burn_has_settled_eat_flame_choice(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,fire=True)
    acquire();service,table,mid=combat(cold,jid)
    move_caster_out_of_melee(service,table,mid)
    for _ in range(8):
        turn(table,mid,B)
        settle(table,mid,candidate(service,mid,'Ignite',A).candidate_id,{
            'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.eat_the_flame':None})
        engine=reload(cold,mid)
        if any(c.condition_id=='condition:typed.burning' for c in engine.state.actors[A].conditions.values()):break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert any(c.condition_id=='condition:typed.burning' for c in engine.state.actors[A].conditions.values())
    hp=engine.state.actors[A].current_hp;stamina=engine.state.actors[A].resources['resource:core.stamina']
    prompts=settle(table,mid,table.state(mid)['menu']['end_turn'],{
        'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.eat_the_flame':['eat']})
    final=reload(cold,mid);owner=final.state.actors[A]
    assert any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' for p in prompts)
    grant=next(e for e in final.events if e.event_type=='TEMP_HP_GRANTED' and e.source_definition_id==PREFIX+'hell_tempered')
    assert owner.current_hp<hp and grant.payload['offered']==min(hp-owner.current_hp,2*owner.proficiency_bonus)
    # The ensuing native Fire Terrain packet may consume this new buffer.
    later=[e for e in final.events if e.sequence>grant.sequence and e.event_type=='DAMAGE_COMMITTED' and A in e.target_ids]
    assert owner.temporary_hp==max(0,grant.payload['after']-sum(e.payload['temporary_hp_absorbed'] for e in later))
    count=len(final.rolls)
    settle(table,mid,candidate(service,mid,'Extinguish flames',A).candidate_id,choices={})
    ended=reload(cold,mid)
    assert not any(c.condition_id=='condition:typed.burning' for c in ended.state.actors[A].conditions.values())
    assert len(ended.rolls)==count and not ended.state.actors[A].action_available
    assert owner.resources['resource:core.stamina']==stamina-1


@pytest.mark.parametrize('skill,problem,covered,mode',[
    ('Intimidation','',0,'ADVANTAGE'),('Intimidation','',1,'NORMAL'),
    ('Persuasion','harmless',0,'DISADVANTAGE'),('Persuasion','other',0,'NORMAL'),
    ('Persuasion','orthodox',1,'NORMAL')])
def test_native_scar_social_purposes(tmp_path,monkeypatch,skill,problem,covered,mode):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();s=cold().journey_state(jid)
    s=cold().journey_act(jid,s['revision'],A,'jigoku_scar_cover',{'covered':covered})
    s=cold().journey_world_fact(jid,s['revision'],{'source':'journey:noncombat_check','subject':A,'kind':'request','scope':'scar-social',
        'value':{'purpose':'Address the visible observer','ability':'CHA','skill':skill,'dc':12,
                 'sect_context':0,'role':'','duty':'','institution':'','recovery':'','person':B,'problem':problem},
        'expires_at':1000,'readers':[]})
    s=cold().journey_act(jid,s['revision'],A,'check_start',{'scope':'scar-social','merit':0})
    event=next(e for e in reversed(s['events']) if e['kind']=='JOURNEY_CHECK_ROLLED')
    assert event['roll']['mode']==mode
    s=cold().journey_act(jid,s['revision'],A,'check_settle',{'merit':0})
    assert cold().journey_state(jid)==s and cold().journey_verify(jid)['status']=='PASS'


@pytest.mark.parametrize('staged',[0,1])
def test_native_mapped_fire_first_exposure_and_absolute_repeat_guard(tmp_path,monkeypatch,staged):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,hazard=True)
    acquire();s=cold().journey_state(jid)
    s=cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':A,'kind':'hazard','scope':'zone:map:1',
        'value':{'created_by':'','staged':staged,'weakened':0,'harmless':0,'cosmetic':0,'cooperative':0},
        'expires_at':86400,'readers':[]})
    assert cold().journey_verify(jid)['status']=='PASS'
    service,table,mid=combat(cold,jid);turn(table,mid,A)
    before=reload(cold,mid).state.actors[A]
    move=next(c for c in service._load_session(mid).engine.legal_candidates()
              if str(getattr(c.kind,'value',c.kind))=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(2,3))
    prompts=settle(table,mid,move.candidate_id,{'choice:needle.eat_the_flame':['eat']})
    actor=reload(cold,mid).state.actors[A]
    assert actor.current_hp<before.current_hp
    assert actor.resources['resource:core.stamina']==before.resources['resource:core.stamina']-(not staged)
    assert any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' for p in prompts)==(not staged)
    after_stamina=actor.resources['resource:core.stamina']
    # Return to the same stationary source on a later round, with a restored
    # Reaction and a fresh once-per-round allowance. It still cannot be farmed.
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,A)
    actor=reload(cold,mid).state.actors[A]
    assert actor.resources['resource:core.stamina']==after_stamina
    assert actor.temporary_hp==0


@pytest.mark.parametrize('staged',[0,1])
def test_initial_hellwalker_choice_is_human_owned_and_staged_area_inert(tmp_path,monkeypatch,staged):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=14,hazard=True)
    acquire();s=cold().journey_state(jid)
    s=cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':B,'kind':'legal_access','scope':'acquisition',
        'value':'The table owner admits the second practitioner’s Forbidden Method scripture.','expires_at':86400,'readers':[]})
    acquire(B)
    for who in (A,B):
        s=cold().journey_state(jid)
        cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':who,'kind':'hazard','scope':'zone:map:1',
            'value':{'created_by':'','staged':staged,'weakened':0,'harmless':0,'cosmetic':0,'cooperative':0},
            'expires_at':86400,'readers':[]})
    service,table,mid=combat(cold,jid)
    engine=reload(cold,mid);who=engine.state.current_actor_id
    actor=engine.state.actors[who]
    assert actor.temporary_hp==0
    choices=[c for c in engine.legal_candidates() if c.source_definition_id=='system:combat.jigoku_hellwalker_start_choice']
    from combat.action_legality import query
    assert bool(choices)==(not staged), query(engine,who,'system:combat.jigoku_hellwalker_start_choice')
    if staged:return
    stamina=actor.resources['resource:core.stamina']
    prompts=settle(table,mid,choices[0].candidate_id,{'choice:needle.hellwalker':['advantage']})
    actor=reload(cold,mid).state.actors[who]
    assert any(p['context']['reaction_source_id']=='choice:needle.hellwalker' for p in prompts)
    assert any(c.condition_id=='condition:typed.hellwalker_unarmed_advantage' for c in actor.conditions.values())
    assert not any(c.condition_id=='condition:typed.jigoku_hellwalker_start_choice' for c in actor.conditions.values())
    assert actor.resources['resource:core.stamina']==stamina and actor.action_available and actor.bonus_action_available


@pytest.mark.parametrize('order',['strike_first','move_first'])
def test_rage_native_separate_movement_reaction_and_once_turn_rider(tmp_path,monkeypatch,order):
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    turn(table,mid,B)
    before=reload(cold,mid);start=before.state.event_sequence;feet=before.state.actors[A].movement_remaining_ft
    picks={'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.pain_eater':None,
        'choice:needle.asura_response_order':[order],'choice:needle.asura_strike':['strike'],
        'choice:needle.asura_move':[cell_id(Position(x=2,y=1))],
        'choice:needle.path_hit.'+PREFIX+'flame_fist':None}
    prompts=settle(table,mid,candidate(service,mid,'Iron Fist',A).candidate_id,picks)
    engine=reload(cold,mid);actor=engine.state.actors[A]
    assert any(p['context']['reaction_source_id']=='choice:needle.asura_response_order' for p in prompts)
    assert actor.position==Position(x=2,y=1) and actor.movement_remaining_ft==feet
    assert not actor.reaction_available
    attacks=[e for e in engine.events if e.sequence>start and e.event_type=='ATTACK_ROLLED' and e.source_definition_id==PREFIX+'asura_s_rage']
    assert len(attacks)==1 and attacks[0].actor_id==A and attacks[0].payload['mode']=='ADVANTAGE'
    incoming=[e for e in engine.events if e.sequence>start and e.event_type=='DAMAGE_COMMITTED' and e.actor_id==B and A in e.target_ids]
    assert incoming and all(e.payload['reduced_to']==e.payload['rolled_or_pending_damage']//2 for e in incoming)
    riders=[r for r in engine.rolls if r.actor_id==A and r.expression.startswith(('3d6','6d6'))]
    assert len(riders)==1
    assert not any(e.event_type=='REACTION_WINDOW_OPENED' and e.source_definition_id.endswith('opportunity_attack') for e in engine.events if e.sequence>start)
    turn(table,mid,A)
    settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
    final=reload(cold,mid)
    assert len([r for r in final.rolls if r.actor_id==A and r.expression.startswith(('3d6','6d6'))])==2


def test_granted_rage_counter_cannot_grant_another_counter(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();s=cold().journey_state(jid)
    cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':B,'kind':'legal_access','scope':'acquisition',
        'value':'The table owner admits Challenger’s independent Forbidden Method scripture.','expires_at':86400,'readers':[]})
    acquire(B);service,table,mid=combat(cold,jid);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    turn(table,mid,B)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    start=reload(cold,mid).state.event_sequence
    settle(table,mid,candidate(service,mid,'Iron Fist',A).candidate_id,{
        'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.pain_eater':None,
        'choice:needle.asura_response_order':['strike_first'],'choice:needle.asura_strike':['strike'],
        'choice:needle.asura_move':None,'choice:needle.path_hit.'+PREFIX+'flame_fist':None})
    engine=reload(cold,mid)
    counters=[e for e in engine.events if e.sequence>start and e.event_type=='ATTACK_ROLLED' and e.source_definition_id==PREFIX+'asura_s_rage']
    assert len(counters)==1 and counters[0].actor_id==A
    assert engine.state.actors[B].reaction_available


def test_native_initial_map_fire_preserves_player_reaction(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,hazard=True,inside_hazard=True)
    acquire();s=cold().journey_state(jid)
    s=cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':B,'kind':'legal_access','scope':'acquisition',
        'value':'The second practitioner holds the admitted Forbidden Method scripture.','expires_at':86400,'readers':[]})
    acquire(B)
    for who in (A,B):
        s=cold().journey_state(jid)
        cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':who,'kind':'hazard','scope':'zone:map:1',
            'value':{'created_by':'','staged':0,'weakened':0,'harmless':0,'cosmetic':0,'cooperative':0},
            'expires_at':86400,'readers':[]})
    service,table,mid=combat(cold,jid)
    initial=reload(cold,mid);who=initial.state.current_actor_id
    assert initial.state.actors[who].resources['resource:core.stamina']==6
    assert any(c.condition_id=='condition:typed.jigoku_initial_flame' for c in initial.state.actors[who].conditions.values())
    prompts=settle(table,mid,candidate(service,mid,'answer resolved Fire').candidate_id,{'choice:needle.eat_the_flame':['eat']})
    actor=reload(cold,mid).state.actors[who]
    assert actor.resources['resource:core.stamina']==5 and actor.temporary_hp==4
    assert any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' and p['context']['reactor_id']==who for p in prompts)


@pytest.mark.parametrize('rescuer',['self','adjacent'])
def test_native_brand_pulses_and_any_adjacent_creature_can_extinguish(tmp_path,monkeypatch,rescuer):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=10)
    acquire();service,table,mid=combat(cold,jid)
    picks={'choice:needle.path_hit.'+PREFIX+'flame_fist':['Use Burning Brand']}
    brand=None
    for _ in range(10):
        turn(table,mid,A)
        if rescuer=='adjacent':
            brand=next((c for c in reload(cold,mid).state.actors[B].conditions.values() if c.data.get('brand_dice')),None)
            if brand:break
        settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
        before=reload(cold,mid)
        brand=next((c for c in before.state.actors[B].conditions.values() if c.data.get('brand_dice')),None)
        turn(table,mid,B)
        if brand:
            engine=reload(cold,mid)
            packets=[e for e in engine.events if e.sequence>before.state.event_sequence and e.event_type=='DAMAGE_COMMITTED'
                     and e.source_definition_id==PREFIX+'flame_fist' and B in e.target_ids]
            assert len(packets)==1 and packets[0].payload['damage_type']=='FIRE'
            assert brand.data['source_cl']==10 and brand.data['brand_save_dc']==14
            if rescuer=='self':break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert brand,'No actual failed Brand save occurred'
    actor=B if rescuer=='self' else A
    assert reload(cold,mid).state.current_actor_id==actor
    before=reload(cold,mid)
    settle(table,mid,candidate(service,mid,'Extinguish flames',B).candidate_id,{'choice:needle.extinguish_brand':'first'})
    engine=reload(cold,mid)
    assert not [c for c in engine.state.actors[B].conditions.values() if c.data.get('brand_dice')]
    assert not engine.state.actors[actor].action_available
    assert len(engine.rolls)==len(before.rolls)  # automatic; no check or save


def test_native_rage_continues_into_travel_and_ends_at_elapsed_boundary(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();service,table,mid=combat(cold,jid,rounds=1);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    end_encounter(table,mid)
    terminal=reload(cold,mid)
    assert any(c.condition_id=='condition:typed.state.asura_s_rage' for c in terminal.state.actors[A].conditions.values())
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    assert s['seconds']==6  # The completed real round also advances the journey clock.
    clock=s['actors'][A]['source_states']['jigoku:rage_continuation']
    remaining=int(clock['remaining_seconds']);assert 0<remaining<60
    assert clock['source_cl']==18 and s['actors'][A]['exhaustion']==0
    s=cold().journey_act(jid,s['revision'],A,'wait',{'seconds':remaining-1})
    assert s['actors'][A]['source_states']['jigoku:rage_continuation']['remaining_seconds']=='1'
    assert s['actors'][A]['exhaustion']==0 and cold().journey_verify(jid)['status']=='PASS'
    s=cold().journey_act(jid,s['revision'],A,'wait',{'seconds':1})
    assert 'jigoku:rage_continuation' not in s['actors'][A]['source_states']
    assert s['actors'][A]['exhaustion']==1
    ids=[json.loads(c)['condition_id'] for c in s['actors'][A]['encounter_snapshot']['conditions'].values()]
    assert 'condition:typed.directional_signal' in ids and 'condition:typed.eat_the_flame_spent' in ids
    assert cold().journey_verify(jid)['status']=='PASS'
    assert reload(cold,mid).state==terminal.state  # immutable terminal evidence


def test_native_rage_encounter_continuation_keeps_scene_limit_and_source_cl(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();service,table,mid=combat(cold,jid,rounds=1);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    end_encounter(table,mid)
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    stamina=s['actors'][A]['resources']['resource:core.stamina']
    service,table,next_mid=combat(cold,jid,rounds=1);turn(table,next_mid,A)
    engine=reload(cold,next_mid);actor=engine.state.actors[A]
    rage,=[c for c in actor.conditions.values() if c.condition_id=='condition:typed.state.asura_s_rage']
    assert rage.data['source_cl']==18 and rage.data['numbers']['cl']==18 and actor.resources['resource:core.stamina']==stamina
    assert any(m.source_definition_id==rage.source_definition_id for m in actor.modifiers.values())
    assert not any((engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')==PREFIX+'asura_s_rage' for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)


def test_native_mixed_weapon_packet_eat_uses_only_actual_fire_hp(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,fire=True,burning_weapon=True)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,B)
    settle(table,mid,candidate(service,mid,'Burning Weapon',B).candidate_id,{'choice:fire.imbue_weapon':['unarmed']})
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,B)
    before=reload(cold,mid)
    picks={'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.eat_the_flame':['eat']}
    for _ in range(6):
        before=reload(cold,mid);start=before.state.event_sequence
        prompts=settle(table,mid,candidate(service,mid,'Iron Fist',A).candidate_id,picks)
        after=reload(cold,mid)
        if any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' for p in prompts):break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={});turn(table,mid,B)
    packets=[e for e in after.events if e.sequence>start and e.event_type=='DAMAGE_COMMITTED' and A in e.target_ids and e.actor_id==B]
    fire=sum(e.payload['hp_damage'] for e in packets if e.payload['damage_type']=='FIRE')
    physical=sum(e.payload['hp_damage'] for e in packets if e.payload['damage_type']!='FIRE')
    assert fire>0 and physical>0
    actor=after.state.actors[A]
    assert actor.temporary_hp==min(fire,2*actor.proficiency_bonus)
    assert actor.resources['resource:core.stamina']==before.state.actors[A].resources['resource:core.stamina']-1
    gain=next(e for e in after.events if e.sequence>start and e.event_type=='TEMP_HP_GRANTED' and A in e.target_ids)
    assert gain.sequence>max(e.sequence for e in packets)


@pytest.mark.parametrize('sphere,action,damage_type',[
    ('tianxia.sphere.force','Impact','FORCE'),
    ('tianxia.sphere.radiance','Radiance Strike','RADIANT'),
    ('tianxia.sphere.space','Spatial Edge','FORCE')])
def test_native_rage_excluded_damage_types_are_not_resisted(tmp_path,monkeypatch,sphere,action,damage_type):
    cold,jid,acquire=game(tmp_path,monkeypatch,attack_sphere=sphere)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    move_caster_out_of_melee(service,table,mid)
    picks={'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.pain_eater':None,
           'choice:needle.asura_move':None,'choice:needle.asura_strike':None}
    packets=[]
    for _ in range(5):
        turn(table,mid,B);start=reload(cold,mid).state.event_sequence
        settle(table,mid,candidate(service,mid,action,A).candidate_id,picks)
        engine=reload(cold,mid)
        packets=[e for e in engine.events if e.sequence>start and e.event_type=='DAMAGE_COMMITTED'
                 and e.actor_id==B and A in e.target_ids and e.payload['damage_type']==damage_type]
        if packets:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert packets
    assert all(e.payload['reduced_to']==e.payload['rolled_or_pending_damage'] for e in packets)


def test_native_brand_refresh_keeps_one_pulse_and_repeats_actual_save(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=10)
    acquire();service,table,mid=combat(cold,jid)
    picks={'choice:needle.path_hit.'+PREFIX+'flame_fist':['Use Burning Brand']}
    refreshed=False
    for _ in range(10):
        turn(table,mid,A)
        before=reload(cold,mid)
        old=[c for c in before.state.actors[B].conditions.values() if c.data.get('brand_dice')]
        settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
        applied=reload(cold,mid)
        brands=[c for c in applied.state.actors[B].conditions.values() if c.data.get('brand_dice')]
        assert len(brands)<=1
        refreshed=bool(old and brands and old[0].instance_id!=brands[0].instance_id)
        turn(table,mid,B)
        started=reload(cold,mid)
        if brands:
            packets=[e for e in started.events if e.sequence>applied.state.event_sequence and e.event_type=='DAMAGE_COMMITTED'
                     and e.source_definition_id==PREFIX+'flame_fist' and B in e.target_ids]
            assert len(packets)==1 and brands[0].data['source_cl']==10
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
        ended=reload(cold,mid)
        if brands:
            saves=[e for e in ended.events if e.sequence>started.state.event_sequence and e.event_type=='SAVE_ROLLED'
                   and e.actor_id==B and e.source_definition_id==PREFIX+'flame_fist']
            assert len(saves)==1 and saves[0].payload['dc']==14
            if saves[0].payload['success']:assert not [c for c in ended.state.actors[B].conditions.values() if c.data.get('brand_dice')]
        if refreshed:break
    assert refreshed,'No native failed reapplication occurred while the existing Brand persisted'


def test_native_source_fact_expires_during_combat_before_next_encounter(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,fire=True)
    acquire();s=cold().journey_state(jid)
    s=cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':B,'kind':'hostility','scope':'combat',
        'value':{'hostile_to':[A],'cooperative':0,'staged':0,'weakened':0,'captured':0,'revived':0,'controlled':0},
        'expires_at':6,'readers':[]})
    service,table,first=combat(cold,jid,rounds=1);end_encounter(table,first)
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    assert s['seconds']==6 and cold().journey_verify(jid)['status']=='PASS'
    service,table,mid=combat(cold,jid)
    move_caster_out_of_melee(service,table,mid)
    engine=reload(cold,mid)
    assert 'jigoku_hostility_fact' not in next(b for b in engine.typed_bundle_documents if b['actor_id']==B)
    service.set_controller_mode(mid,actor_id=B,controller_mode='LOCAL_AUTO')
    from tests.r1i_service_support import force_ai_candidate
    damaged=False
    for _ in range(5):
        turn(table,mid,B)
        hp=reload(cold,mid).state.actors[A].current_hp
        chosen=candidate(service,mid,'Ignite',A).candidate_id
        force_ai_candidate(service,mid,B,chosen)
        prompts=settle(table,mid,chosen,{'choice:needle.eat_the_flame':['eat']},auto=True)
        after=reload(cold,mid).state.actors[A]
        assert not any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' for p in prompts)
        if after.current_hp<hp:damaged=True;break
        service.set_controller_mode(mid,actor_id=B,controller_mode='MANUAL')
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert damaged and after.temporary_hp==0


def test_native_unconscious_rage_ending_keeps_exhaustion_signal_and_scene_ledger(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,attack_sphere='tianxia.sphere.radiance')
    acquire();service,table,first=combat(cold,jid,rounds=15)
    move_caster_out_of_melee(service,table,first)
    # Arrive wounded through actual committed attacks, never an HP edit.
    for _ in range(15):
        if service._load_session(first).engine.state.terminal_result:break
        turn(table,first,B)
        if reload(cold,first).state.actors[A].current_hp>80:
            settle(table,first,candidate(service,first,'Radiance Strike',A).candidate_id,choices={})
        settle(table,first,table.state(first)['menu']['end_turn'],choices={})
    end_encounter(table,first)
    wounded=reload(cold,first).state.actors[A]
    assert 0<wounded.current_hp<=80
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    service,table,mid=combat(cold,jid);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    picks={'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.pain_eater':None,
           'choice:needle.asura_move':None,'choice:needle.asura_strike':None}
    for _ in range(9):
        engine=reload(cold,mid)
        if engine.state.actors[A].current_hp==0:break
        turn(table,mid,B)
        settle(table,mid,candidate(service,mid,'Radiance Strike',A).candidate_id,picks)
        engine=reload(cold,mid)
        if engine.state.actors[A].current_hp==0:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    actor=reload(cold,mid).state.actors[A]
    assert actor.current_hp==0 and (actor.life_state in ('DYING','STABLE') or not actor.active)
    assert not any(c.condition_id=='condition:typed.state.asura_s_rage' for c in actor.conditions.values())
    exhaustion,=[c for c in actor.conditions.values() if c.condition_id=='condition:typed.exhaustion']
    assert exhaustion.data['level']==1
    assert any(c.condition_id=='condition:typed.directional_signal' for c in actor.conditions.values())
    assert any(c.condition_id=='condition:typed.eat_the_flame_spent' for c in actor.conditions.values())
    scene,=[c for c in actor.conditions.values() if c.condition_id=='condition:typed.jigoku_scene']
    assert scene.data['rage_spent']==1


@pytest.mark.parametrize('staged',[0,1])
def test_native_dynamic_fire_area_requires_creator_intent(tmp_path,monkeypatch,staged):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=14,fire=True)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,B)
    settle(table,mid,candidate(service,mid,'Conflagration',at=(2,2)).candidate_id,choices={})
    prompts=settle(table,mid,table.state(mid)['menu']['end_turn'],{
        'choice:needle.fact_admission.environment_intent':['staged' if staged else 'active'],
        'choice:needle.hellwalker':['advantage']})
    actor=reload(cold,mid).state.actors[A]
    assert any(p['context']['reaction_source_id']=='choice:needle.fact_admission.environment_intent' and p['context']['reactor_id']==B for p in prompts)
    assert any(c.condition_id=='condition:typed.hellwalker_unarmed_advantage' for c in actor.conditions.values())==(not staged)


@pytest.mark.parametrize('terrain',['dense wax smoke','ash terrain','molten terrain'])
def test_native_active_smoke_ash_magma_map_producers(tmp_path,monkeypatch,terrain):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=14,hazard=True,inside_hazard=True,hazard_terrain=terrain)
    acquire();s=cold().journey_state(jid)
    s=cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':B,'kind':'legal_access','scope':'acquisition',
        'value':'Challenger also holds the admitted Forbidden Method scripture.','expires_at':86400,'readers':[]})
    acquire(B)
    for aid in (A,B):
        s=cold().journey_state(jid)
        cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':aid,'kind':'hazard','scope':'zone:map:1',
            'value':{'created_by':'','staged':0,'weakened':0,'harmless':0,'cosmetic':0,'cooperative':0},'expires_at':86400,'readers':[]})
    service,table,mid=combat(cold,jid)
    initial=reload(cold,mid);aid=initial.state.current_actor_id
    assert any(c.condition_id=='condition:typed.jigoku_hellwalker_start_choice' for c in initial.state.actors[aid].conditions.values())
    settle(table,mid,candidate(service,mid,'Hellwalker: choose your start-of-turn benefit').candidate_id,{'choice:needle.hellwalker':['advantage']})
    assert any(c.condition_id=='condition:typed.hellwalker_unarmed_advantage' for c in reload(cold,mid).state.actors[aid].conditions.values())


@pytest.mark.parametrize('sphere,action,tag',[
    ('tianxia.sphere.ash','Cinder Brand: Create Remnant','ash_terrain'),
    ('tianxia.sphere.magma','Magma Glob: Molten Terrain Patch','magma')])
def test_native_ash_and_magma_placed_producers_feed_hellwalker(tmp_path,monkeypatch,sphere,action,tag):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=14,attack_sphere=sphere)
    acquire();service,table,mid=combat(cold,jid)
    zone=None
    for _ in range(6):
        turn(table,mid,B)
        settle(table,mid,candidate(service,mid,action,A).candidate_id,{
            'choice:rider.ash_remnant':['cell:2,3'],'choice:rider.magma_patch':['cell:2,3']})
        engine=reload(cold,mid)
        zone=next((z for z in engine.state.zones.values() if z.active and tag in z.trigger_profile.get('source_profile',{}).get('source_tags',[])),None)
        if zone:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert zone and zone.owner_id==B and zone.trigger_profile['source_profile']['source_cl']==14
    prompts=settle(table,mid,table.state(mid)['menu']['end_turn'],{
        'choice:needle.fact_admission.environment_intent':['active'],'choice:needle.hellwalker':['advantage']})
    actor=reload(cold,mid).state.actors[A]
    assert any(p['context']['reaction_source_id']=='choice:needle.hellwalker' for p in prompts)
    assert any(c.condition_id=='condition:typed.hellwalker_unarmed_advantage' for c in actor.conditions.values())


def test_native_brand_new_encounter_has_a_new_turn_allowance(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=10)
    acquire();service,table,mid=combat(cold,jid,rounds=1);turn(table,mid,A)
    picks={'choice:needle.path_hit.'+PREFIX+'flame_fist':['Use Burning Brand']}
    prompts=settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
    assert any(p['context']['reaction_source_id']=='choice:needle.path_hit.'+PREFIX+'flame_fist' for p in prompts)
    end_encounter(table,mid)
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    assert cold().journey_verify(jid)['status']=='PASS'
    service,table,mid=combat(cold,jid);turn(table,mid,A)
    before=reload(cold,mid);start=before.state.event_sequence
    prompts=settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
    after=reload(cold,mid)
    assert any(e.sequence>start and e.event_type=='DAMAGE_COMMITTED' and e.actor_id==A and B in e.target_ids and e.payload['hp_damage']>0 for e in after.events)
    assert any(p['context']['reaction_source_id']=='choice:needle.path_hit.'+PREFIX+'flame_fist' for p in prompts)
    assert after.state.actors[A].resources['resource:core.stamina']==before.state.actors[A].resources['resource:core.stamina']-1


def test_native_short_rest_choice_caps_and_long_rest_reset(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire()
    def act(kind,payload):
        s=cold().journey_state(jid)
        result=cold().journey_act(jid,s['revision'],A,kind,payload)
        assert cold().journey_verify(jid)['status']=='PASS'
        return result
    def spend_rage():
        service,table,mid=combat(cold,jid,rounds=1);turn(table,mid,A)
        settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
        end_encounter(table,mid)
        s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
        remaining=int(s['actors'][A]['source_states']['jigoku:rage_continuation']['remaining_seconds'])
        s=act('wait',{'seconds':remaining})
        return cold().journey_end_scene(jid,s['revision'],'The immediate conflict has ended.')
    spend_rage();s=act('short_rest',{})
    assert s['actors'][A]['resources']['resource:core.stamina']==29
    assert len([o for o in cold().journey_menu(jid,A)['options'] if o['kind']=='jigoku_short_rest_recovery'])==2
    s=act('jigoku_short_rest_recovery',{'recover':0})
    assert s['actors'][A]['resources']['resource:core.stamina']==29
    assert s['actors'][A]['source_states']['jigoku:stamina_recovery']['short_uses']==0
    s=act('short_rest',{});s=act('jigoku_short_rest_recovery',{'recover':1})
    assert s['actors'][A]['resources']['resource:core.stamina']==36
    s=act('short_rest',{})  # No missing Stamina: no recovery use is wasted.
    assert 'jigoku:short_rest_choice' not in s['actors'][A]['source_states']
    assert s['actors'][A]['source_states']['jigoku:stamina_recovery']['short_uses']==1
    spend_rage();act('short_rest',{});s=act('jigoku_short_rest_recovery',{'recover':1})
    assert s['actors'][A]['resources']['resource:core.stamina']==36
    spend_rage();s=act('short_rest',{})
    assert s['actors'][A]['resources']['resource:core.stamina']==29
    assert 'jigoku:short_rest_choice' not in s['actors'][A]['source_states']
    assert s['actors'][A]['source_states']['jigoku:stamina_recovery']['short_uses']==2
    act('long_rest',{})
    spend_rage();act('short_rest',{});s=act('jigoku_short_rest_recovery',{'recover':1})
    assert s['actors'][A]['resources']['resource:core.stamina']==36
    assert s['actors'][A]['source_states']['jigoku:stamina_recovery']['short_uses']==1


def test_native_different_authored_maps_do_not_share_stationary_fire_identity(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,hazard=True)
    acquire()
    original=cold().factory_arenas()['test']
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'test':original,
        'second':{**original,'stable_id':'journey:jigoku:second-authored-map','display_name':'A different native map'}})
    for index in range(2):
        s=cold().journey_state(jid)
        cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':A,'kind':'hazard','scope':'zone:map:1',
            'value':{'created_by':'','staged':0,'weakened':0,'harmless':0,'cosmetic':0,'cooperative':0},'expires_at':86400,'readers':[]})
        service,table,mid=combat(cold,jid,rounds=1);turn(table,mid,A)
        before=reload(cold,mid).state.actors[A].resources['resource:core.stamina']
        step=next(c for c in service._load_session(mid).engine.legal_candidates() if str(getattr(c.kind,'value',c.kind))=='MOVE'
            and c.destination and (c.destination.x,c.destination.y)==(2,3))
        prompts=settle(table,mid,step.candidate_id,{'choice:needle.eat_the_flame':['eat']})
        assert any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' for p in prompts)
        assert reload(cold,mid).state.actors[A].resources['resource:core.stamina']==before-1
        if index:break
        settle(table,mid,candidate(service,mid,'Extinguish flames',A).candidate_id,choices={})
        end_encounter(table,mid)
        s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
        s=cold().journey_act(jid,s['revision'],A,'finish',{})
        s=cold().create_journey(project_ids=PIDS,arena_id='second',positions={A:{'x':2,'y':2},B:{'x':3,'y':2}},base_paces={A:1800,B:1800})
        jid=s['journey_id']
    exposure,=[c for c in reload(cold,mid).state.actors[A].conditions.values() if c.condition_id=='condition:typed.jigoku_fire_exposure']
    assert len(exposure.data['sources'])==2


def rage_aftermath_travel(cold,jid):
    service,table,mid=combat(cold,jid,rounds=1);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    end_encounter(table,mid)
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    seconds=int(s['actors'][A]['source_states']['jigoku:rage_continuation']['remaining_seconds'])
    return cold().journey_act(jid,s['revision'],A,'wait',{'seconds':seconds})


@pytest.mark.parametrize('strenuous',[0,1])
def test_native_cooling_distinguishes_declared_light_and_strenuous_checks(tmp_path,monkeypatch,strenuous):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();s=rage_aftermath_travel(cold,jid)
    s=cold().journey_end_scene(jid,s['revision'],'The immediate conflict is over.')
    s=cold().journey_world_fact(jid,s['revision'],{'source':'journey:noncombat_check','subject':A,'kind':'request','scope':'cooling-reading',
        'value':{'purpose':'Read an ordinary compass','ability':'INT','skill':'Investigation','dc':12,
                 'sect_context':0,'role':'','duty':'','institution':'','recovery':''},'expires_at':s['seconds']+600,'readers':[]})
    s=cold().journey_act(jid,s['revision'],A,'declare_fact',{'source':SOURCE,'subject':A,'kind':'rite_light_check','scope':'cooling-reading',
        'value':1-strenuous,'expires_at':s['seconds']+600,'readers':[]})
    def act(kind,payload):
        s=cold().journey_state(jid);result=cold().journey_act(jid,s['revision'],A,kind,payload)
        assert cold().journey_verify(jid)['status']=='PASS'
        return result
    act('activity_start',{'source':SOURCE+'.cooling_rite','parameters':{}})
    act('activity_work',{'seconds':599})
    s=act('check_start',{'scope':'cooling-reading','merit':0})
    assert ('journey:activity' in s['actors'][A]['source_states'])==(not strenuous)
    s=act('check_settle',{'merit':0})
    if not strenuous:
        s=act('activity_work',{'seconds':1})
        assert not any(json.loads(c)['condition_id']=='condition:typed.eat_the_flame_spent' for c in s['actors'][A]['encounter_snapshot']['conditions'].values())
    else:assert any(json.loads(c)['condition_id']=='condition:typed.eat_the_flame_spent' for c in s['actors'][A]['encounter_snapshot']['conditions'].values())


def test_native_new_conflict_revokes_old_cooling_admission(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();s=rage_aftermath_travel(cold,jid)
    s=cold().journey_end_scene(jid,s['revision'],'The first immediate conflict ended.')
    service,table,mid=combat(cold,jid,rounds=1);end_encounter(table,mid)
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    before=s
    with pytest.raises(ValueError,match='current immediate conflict'):
        cold().journey_act(jid,s['revision'],A,'activity_start',{'source':SOURCE+'.cooling_rite','parameters':{}})
    assert cold().journey_state(jid)==before
    s=cold().journey_end_scene(jid,s['revision'],'The new immediate conflict has ended too.')
    s=cold().journey_act(jid,s['revision'],A,'activity_start',{'source':SOURCE+'.cooling_rite','parameters':{}})
    s=cold().journey_act(jid,s['revision'],A,'activity_work',{'seconds':600})
    assert not any(json.loads(c)['condition_id']=='condition:typed.eat_the_flame_spent' for c in s['actors'][A]['encounter_snapshot']['conditions'].values())
    assert cold().journey_verify(jid)['status']=='PASS'


def test_native_full_session_does_not_require_ending_the_meaningful_scene(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();s=rage_aftermath_travel(cold,jid)
    assert s.get('scene_number',0)==0
    s=cold().journey_act(jid,s['revision'],A,'activity_start',{'source':SOURCE+'.cultivation_session','parameters':{}})
    s=cold().journey_act(jid,s['revision'],A,'activity_work',{'seconds':7200})
    ids=[json.loads(c)['condition_id'] for c in s['actors'][A]['encounter_snapshot']['conditions'].values()]
    assert 'condition:typed.directional_signal' not in ids and 'condition:typed.eat_the_flame_spent' in ids
    assert s['actors'][A]['resources']['resource:core.stamina']==36
    assert cold().journey_verify(jid)['status']=='PASS'
    service,table,mid=combat(cold,jid);turn(table,mid,A)
    engine=reload(cold,mid)
    assert not any((engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')==PREFIX+'asura_s_rage'
                   for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)


def world(table,mid,subject,kind,value,*,source='system:scene.fields',scope='scene',expires=86400,request='world-test'):
    engine=table.combat._load_session(mid).engine
    from combat.combat_world_facts import clock
    return table.world_fact(mid,engine.state.state_version,{'source':source,'subject':subject,'kind':kind,'scope':scope,
        'value':value,'expires_at':int(clock(engine))+expires,'readers':[]},request)


def test_native_world_fact_replaces_hostility_without_fabricating_damage(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,fire=True)
    acquire();service,table,mid=combat(cold,jid)
    move_caster_out_of_melee(service,table,mid)
    before=reload(cold,mid)
    value={'hostile_to':[A],'cooperative':0,'staged':1,'weakened':0,'captured':0,'revived':0,'controlled':0}
    result=world(table,mid,B,'hostility',value,source=SOURCE,scope='combat')
    assert result['status']=='COMMITTED'
    after=reload(cold,mid)
    assert after.state.actors[A].current_hp==before.state.actors[A].current_hp
    assert len([e for e in after.events if e.event_type=='DAMAGE_COMMITTED'])==len([e for e in before.events if e.event_type=='DAMAGE_COMMITTED'])
    hp=after.state.actors[A].current_hp
    prompts=settle(table,mid,candidate(service,mid,'Ignite',A).candidate_id,{
        'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.eat_the_flame':['eat']})
    actor=reload(cold,mid).state.actors[A]
    assert actor.current_hp<hp and actor.resources['resource:core.stamina']==6
    assert not any(p['context']['reaction_source_id']=='choice:needle.eat_the_flame' for p in prompts)
    assert world(table,mid,B,'hostility',value,source=SOURCE,scope='combat')['receipt_id']==result['receipt_id']  # idempotent


def test_native_world_input_cannot_impersonate_controller_or_create_area(tmp_path,monkeypatch):
    from combat.tabletop_service import TabletopError
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=14)
    acquire();service,table,mid=combat(cold,jid)
    before=reload(cold,mid).state.model_dump(mode='json')
    with pytest.raises(TabletopError,match='private consent'):
        world(table,mid,A,'rite_light_check',1,source=SOURCE,scope='nonexistent')
    with pytest.raises(TabletopError,match='actual mapped area'):
        world(table,mid,A,'hazard',{'created_by':'', 'staged':0,'weakened':0,'harmless':0,'cosmetic':0,'cooperative':0},source=SOURCE,scope='zone:map:99',request='bad-map')
    assert reload(cold,mid).state.model_dump(mode='json')==before


def test_native_hell_signaled_plane_direction_privacy_and_expiry(tmp_path,monkeypatch):
    from combat.observer_information import readings
    cold,jid,acquire=game(tmp_path,monkeypatch,observer_type='Infernal')
    acquire();service,table,mid=combat(cold,jid,rounds=1);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    end_encounter(table,mid)
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    s=cold().journey_act(jid,s['revision'],A,'wait',{'seconds':60})
    service,table,mid=combat(cold,jid,rounds=3)
    def directions():
        engine=reload(cold,mid)
        return [r for r in readings(engine,engine.state.actors[B]) if r['kind']=='direction']
    assert not directions()  # No invented plane while that world fact is unknown.
    for aid in (A,B):world(table,mid,aid,'plane',{'plane_id':'material-plane'},request='initial-plane-'+aid)
    rows=directions();assert rows
    assert all(set(r['details'])=={'reading'} and 'Realm' in r['details']['reading'] for r in rows)
    world(table,mid,A,'plane',{'plane_id':'infernal-plane'},request='plane-away')
    assert not directions()
    world(table,mid,B,'plane',{'plane_id':'infernal-plane'},request='plane-follow',expires=6)
    assert directions()
    # Cross an actual round boundary; expired plane knowledge cannot revive the
    # encounter's default plane or expose a now-unproven direction.
    start=reload(cold,mid).state.round_number
    for _ in range(3):
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
        if reload(cold,mid).state.round_number>start:break
    assert not directions()

    end_encounter(table,mid)
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    assert 'hell_signaled_directions' not in cold().journey_menu(jid,B)['properties']
    s=cold().journey_world_fact(jid,s['revision'],{'source':'system:scene.fields','subject':B,'kind':'plane','scope':'world-transition',
        'value':{'plane_id':'infernal-plane'},'expires_at':s['seconds']+86400,'readers':[]})
    assert cold().journey_menu(jid,B)['properties']['hell_signaled_directions']
    assert not any(json.loads(c)['condition_id']=='condition:world.fact_history' for a in s['actors'].values() for c in a.get('encounter_snapshot',{}).get('conditions',{}).values())
    assert cold().journey_verify(jid)['status']=='PASS'


@pytest.mark.parametrize('creator',[A,B])
def test_native_hellwalker_sees_only_own_magma_smoke(tmp_path,monkeypatch,creator):
    from combat.senses import ordinary_sight_perceives
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=14,magma_smoke=True)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,creator)
    settle(table,mid,candidate(service,mid,'Volcanic Smoke',at=(2,2)).candidate_id,choices={})
    engine=reload(cold,mid);viewer=engine.state.actors[A];other=engine.state.actors[B]
    zone=next(z for z in engine.state.zones.values() if z.owner_id==creator and z.trigger_profile.get('name')=='Volcanic Smoke')
    assert zone.trigger_profile['obscured']=='heavy'
    assert 'Smoke' in zone.trigger_profile['source_profile']['source_tags']
    assert ordinary_sight_perceives(engine,viewer,other)==(creator==A)
    assert not ordinary_sight_perceives(engine,other,viewer)
    assert not any(c.data.get('truesight') for c in viewer.conditions.values())


def test_native_pain_mark_replaces_on_later_round_then_expires_next_own_turn(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=6,third=True)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    picks={'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.pain_eater':['mark']}
    C=FACTORY_ACTOR_PREFIX+'0badc0de-0000-4000-8000-000000000083'
    def move(at):
        e=reload(cold,mid)
        row=next(c for c in e.legal_candidates() if str(getattr(c.kind,'value',c.kind))=='MOVE' and c.destination and (c.destination.x,c.destination.y)==at)
        settle(table,mid,row.candidate_id,picks)
        return reload(cold,mid)
    replaced=False
    for attempt in range(10):
        e=reload(cold,mid)
        if (e.state.actors[A].position.x,e.state.actors[A].position.y)!=(2,2):move((2,2))
        boundary=reload(cold,mid).state.event_sequence
        first=move((2,1))  # A real Opportunity Attack can miss; never force a roll.
        original=next((c for c in first.state.actors[C].conditions.values() if c.condition_id=='condition:typed.pain_eater_mark' and c.applied_sequence>boundary),None)
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={});turn(table,mid,A)
        if original is None:continue
        assert original.data['source_cl']==6
        second=move((1,1))
        marks=[(a.entity_id,c) for a in second.state.actors.values() for c in a.conditions.values() if c.condition_id=='condition:typed.pain_eater_mark']
        replaced=(len(marks)==1 and marks[0][0]==B and marks[0][1].instance_id!=original.instance_id)
        if replaced:
            assert any(e.event_type=='CONDITION_REMOVED' and e.payload.get('instance_id')==original.instance_id and e.payload.get('reason')=='REPLACED' for e in second.events)
            break
    assert replaced,'No pair of actual damaging Opportunity Attacks occurred before the native boundary.'
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={});turn(table,mid,A)
    held=reload(cold,mid)
    assert any(c.condition_id=='condition:typed.pain_eater_mark' for c in held.state.actors[B].conditions.values())
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert not any(c.condition_id=='condition:typed.pain_eater_mark' for a in reload(cold,mid).state.actors.values() for c in a.conditions.values())


def test_native_hell_scars_exact_recognition_range_and_cover(tmp_path,monkeypatch):
    from combat.observer_information import readings
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=3,observer_type='Infernal',foe_x=9)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    def recognitions():
        e=reload(cold,mid)
        return [r for r in readings(e,e.state.actors[B]) if r['kind']=='declaration']
    assert not recognitions()  # Actual clothing covers the permanent scars.
    card=next(a for a in table.state(mid)['presentation']['actors'] if a['entity_id']==A)
    scar,=[row for row in card.get('conditions',[]) if row.get('condition_id')=='condition:typed.jigoku_scars']
    assert scar['hidden'] is True
    e=reload(cold,mid)
    assert any(r.get('details',{}).get('state')=='Permanent Hell Scars' for r in readings(e,e.state.actors[A]))
    settle(table,mid,candidate(service,mid,'Record physical covering').candidate_id,{'choice:needle.jigoku_cover':['visible']})
    table=TabletopService(cold(),tmp_path)  # Public presentation must reflect the committed covering choice after reload.
    card=next(a for a in table.state(mid)['presentation']['actors'] if a['entity_id']==A)
    scar,=[row for row in card.get('conditions',[]) if row.get('condition_id')=='condition:typed.jigoku_scars']
    assert scar['hidden'] is False
    assert not recognitions()  # 35 feet is outside automatic recognition.
    turn(table,mid,B)
    e=reload(cold,mid)
    step=next(c for c in e.legal_candidates() if str(getattr(c.kind,'value',c.kind))=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(8,2))
    settle(table,mid,step.candidate_id,choices={})
    rows=recognitions();assert rows
    assert rows==[{'kind':'declaration','details':{'creature':'Ember','recognition':'Forbidden bodily cultivation'},'label':'Recognize visible Hell Scars'}]
    assert 'cl' not in rows[0]['details'] and 'subpath' not in rows[0]['details']


def test_native_hell_signaled_one_mile_boundary_requires_no_sight(tmp_path,monkeypatch):
    from combat.observer_information import readings
    cold,jid,acquire=game(tmp_path,monkeypatch,observer_type='Infernal',foe_x=1059,arena_width=1065,arena_height=3,published_arena=True)
    acquire();service,table,mid=combat(cold,jid,rounds=1);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    end_encounter(table,mid)
    s=cold().journey_state(jid);s=cold().journey_resume(jid,s['revision'])
    s=cold().journey_act(jid,s['revision'],A,'wait',{'seconds':60})
    service,table,mid=combat(cold,jid,rounds=3)
    for aid in (A,B):world(table,mid,aid,'plane',{'plane_id':'the-material-plane'},request='range-plane-'+aid)
    def directions():
        e=reload(cold,mid)
        return [r for r in readings(e,e.state.actors[B]) if r['kind']=='direction']
    assert not directions()  # 5,285 feet, one square outside the printed mile.
    turn(table,mid,B)
    e=reload(cold,mid)
    step=next(c for c in e.legal_candidates() if str(getattr(c.kind,'value',c.kind))=='MOVE' and c.destination and (c.destination.x,c.destination.y)==(1058,2))
    settle(table,mid,step.candidate_id,choices={})
    rows=directions();assert rows==[{'kind':'direction','details':{'reading':'west: same Realm'},'label':'Hell-Signaled direction and relative Realm'}]
    assert set(rows[0]['details'])=={'reading'}  # No source identity or distance.


@pytest.mark.parametrize('bonus_type',['BLUDGEONING','NECROTIC'])
def test_native_pain_eater_can_join_rage_rider_type_without_an_extra_packet(tmp_path,monkeypatch,bonus_type):
    cold,jid,acquire=game(tmp_path,monkeypatch)
    acquire();service,table,mid=combat(cold,jid);turn(table,mid,A)
    settle(table,mid,candidate(service,mid,"Asura's Rage").candidate_id,choices={})
    received={'choice:needle.fact_admission.hostile_intent':['genuine'],'choice:needle.pain_eater':['mark'],
        'choice:needle.asura_response_order':['strike_first'],
        'choice:needle.asura_move':None,'choice:needle.asura_strike':None}
    dealt={'choice:needle.iron_fist_damage_type':['BLUDGEONING'],'choice:needle.asura_damage_type':['NECROTIC'],
        'choice:needle.pain_eater_damage_type':[bonus_type],'choice:needle.pain_eater_benefit':['temp_hp'],
        'choice:needle.path_hit.'+PREFIX+'flame_fist':None}
    packets=[];prompts=[]
    for attempt in range(8):
        turn(table,mid,B)
        settle(table,mid,candidate(service,mid,'Iron Fist',A).candidate_id,choices=received)
        e=reload(cold,mid)
        marked=any(c.condition_id=='condition:typed.pain_eater_mark' for c in e.state.actors[B].conditions.values())
        turn(table,mid,A)
        if marked:
            boundary=reload(cold,mid).state.event_sequence
            prompts=settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,choices=dealt)
            final=reload(cold,mid)
            packets=[e for e in final.events if e.sequence>boundary and e.event_type=='DAMAGE_COMMITTED' and e.actor_id==A and B in e.target_ids]
            if packets:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert len(packets)==2 and {e.payload['damage_type'] for e in packets}=={'BLUDGEONING','NECROTIC'}
    assert any(p['context']['reaction_source_id']=='choice:needle.pain_eater_damage_type' for p in prompts)
    rolls=[e for e in final.events if e.sequence>boundary and e.event_type=='DAMAGE_ROLLED' and e.actor_id==A]
    rage,=[e for e in rolls if e.payload.get('damage_label')=="Asura's Rage"]
    primary,=[e for e in rolls if e is not rage]
    pb=final.state.actors[A].proficiency_bonus
    assert rage.payload['modifier']==(pb if bonus_type=='NECROTIC' else 0)
    assert primary.payload['modifier']==2+(pb if bonus_type=='BLUDGEONING' else 0)
    assert not any(c.condition_id=='condition:typed.pain_eater_mark' for c in final.state.actors[B].conditions.values())


def test_native_one_action_extinguishes_one_of_two_real_brands(tmp_path,monkeypatch):
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=10,foe_cl=20,third=True)
    acquire();C=FACTORY_ACTOR_PREFIX+'0badc0de-0000-4000-8000-000000000083'
    s=cold().journey_state(jid)
    cold().journey_world_fact(jid,s['revision'],{'source':SOURCE,'subject':C,'kind':'legal_access','scope':'acquisition',
        'value':'The third practitioner holds the admitted Forbidden Method scripture.','expires_at':86400,'readers':[]})
    acquire(C);service,table,mid=combat(cold,jid,allies=(C,))
    opening=reload(cold,mid)
    assert opening.state.actors[C].team_id==opening.state.actors[A].team_id!=opening.state.actors[B].team_id
    picks={'choice:needle.iron_fist_damage_type':['BLUDGEONING'],'choice:needle.path_hit.'+PREFIX+'flame_fist':['Use Burning Brand']}
    both=False
    for attempt in range(8):
        for caster in (A,C):
            turn(table,mid,caster)
            e=reload(cold,mid)
            if not any(c.data.get('brand_dice') and c.source_actor_id==caster for c in e.state.actors[B].conditions.values()):
                settle(table,mid,candidate(service,mid,'Iron Fist',B).candidate_id,picks)
            e=reload(cold,mid)
            both={c.source_actor_id for c in e.state.actors[B].conditions.values() if c.data.get('brand_dice')}=={A,C}
            if both:break
        if both:break
    assert both,'The actual unarmed hits and failed saves did not establish both Brands.'
    turn(table,mid,B)
    before=reload(cold,mid);bearer=before.state.actors[B]
    brands=[c for c in bearer.conditions.values() if c.data.get('brand_dice')]
    assert len(brands)==2 and bearer.current_hp>0 and bearer.action_available
    assert not any(before.action_catalog[c.source_definition_id].display_name=='Extinguish Burning Brand' for c in before.legal_candidates() if c.source_definition_id in before.action_catalog)
    chosen=brands[-1].instance_id
    prompts=settle(table,mid,candidate(service,mid,'Extinguish flames',B).candidate_id,{'choice:needle.utilize_end.burning':[chosen]})
    final=reload(cold,mid)
    remaining=[c for c in final.state.actors[B].conditions.values() if c.data.get('brand_dice')]
    assert len(remaining)==1 and remaining[0].instance_id!=chosen
    assert not final.state.actors[B].action_available and len(final.rolls)==len(before.rolls)
    assert any(p['context']['reaction_source_id']=='choice:needle.utilize_end.burning' for p in prompts)


def test_native_acquisition_reaches_factory_and_stock_bearer_extinguish(tmp_path,monkeypatch):
    from combat.gate2_runtime_content import AN
    cold,jid,acquire=game(tmp_path,monkeypatch,cl=10,stock_spawn=AN)
    acquire();s=cold().journey_state(jid)
    cold().journey_act(jid,s['revision'],A,'finish',{})
    service=cold()
    result=service.create_factory_match(project_ids=[PIDS[0]],opponent_actor_ids=[AN],
        control_modes={A:'MANUAL',AN:'MANUAL'},match_seed='JIGOKU_NATIVE_STOCK_BEARER',arena_id='test',maximum_rounds=15)
    mid=result['match_id'];table=TabletopService(service,tmp_path)
    engine=reload(cold,mid)
    assert any(r.get('feature_id')==PREFIX+'hell_tempered' for r in engine.typed_passive_rows[A])
    assert AN not in engine.typed_actor_ids
    brands=[]
    for attempt in range(8):
        turn(table,mid,A)
        e=reload(cold,mid)
        if e._distance_actor_to_actor(e.state.actors[A],e.state.actors[AN])>5:
            moves=[c for c in e.legal_candidates() if str(getattr(c.kind,'value',c.kind))=='MOVE']
            step=min(moves,key=lambda c:e.grid.distance_ft(c.destination,e.state.actors[AN].position))
            settle(table,mid,step.candidate_id,choices={})
            e=reload(cold,mid)
        if e._distance_actor_to_actor(e.state.actors[A],e.state.actors[AN])<=5:
            settle(table,mid,candidate(service,mid,'Iron Fist',AN).candidate_id,{'choice:needle.path_hit.'+PREFIX+'flame_fist':['Use Burning Brand']})
        e=reload(cold,mid)
        brands=[c for c in e.state.actors[AN].conditions.values() if c.data.get('brand_dice')]
        if brands:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert brands
    turn(table,mid,AN)
    before=reload(cold,mid)
    option=candidate(service,mid,'Extinguish flames',AN)
    assert option.source_definition_id=='system:combat.extinguish_burn'
    settle(table,mid,option.candidate_id,choices={})
    after=reload(cold,mid)
    assert not any(c.data.get('brand_dice') for c in after.state.actors[AN].conditions.values())
    assert not after.state.actors[AN].action_available and len(after.rolls)==len(before.rolls)
