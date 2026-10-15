"""Installed Qi character -> source acquisition -> journey/table -> replay."""
import json
import zipfile
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import turn, candidate, settle
FAMILY='tianxia.subpath.qi.living_quicksilver_immortal_embryo'
FEATURES=[FAMILY+'.feature.'+s for s in ('living_mercury_body','divide_the_immortal_embryo','assimilate_the_pattern','thousandfold_quicksilver_court','undying_prima_materia')]
A='actor:factory.mercury';B='actor:factory.opponent';QI='resource:core.qi';MASS='resource:named.quicksilver_mass'

def setup(tmp_path,monkeypatch,cl=18,acquire=True,own_features=(),enemy_features=()):
    for name in ('mercury','opponent'):
        doc=sheet([*(own_features if name=='mercury' else enemy_features),'tianxia.path.qi_cultivation.feature.qi_sensing',*(['tianxia.path.qi_cultivation.feature.domain_armament'] if cl>=9 else [])],cl=cl,name=name.title())
        doc['identity']['proficiency_bonus']=2+(cl-1)//4
        doc['ability_scores_and_statistics']['primary_resource']['maximum']=max(30,2*cl)
        doc['path_and_subpath'].update(path_record_id='tianxia.path.qi_cultivation',path_record_ids=['tianxia.path.qi_cultivation'],paths=[{'path_id':'tianxia.path.qi_cultivation','attainment':cl}])
        folder=tmp_path/'portable_characters'/name;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    arena={'display_name':'Mercury courtyard','stable_id':'battlefield:mercury','width_squares':12,'height_squares':12,'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    monkeypatch.setattr(CombatService,'factory_arenas',lambda self,**kw:{'scene':arena})
    def cold():return CombatService(ROOT,tmp_path)
    state=cold().create_journey(project_ids=['mercury','opponent'],arena_id='scene',positions={A:{'x':3,'y':3},B:{'x':8,'y':3}},base_paces={A:100,B:100})
    jid=state['journey_id']
    def world(kind,scope,value,subject=A,readers=None):
        s=cold();state=s.journey_state(jid)
        return s.journey_world_fact(jid,state['revision'],{'source':FAMILY,'subject':subject,'kind':kind,'scope':scope,'value':value,'expires_at':int(state['seconds'])+2592000,'readers':readers or [A]})
    def act(kind,payload=None,who=A):
        s=cold();state=s.journey_state(jid);after=s.journey_act(jid,state['revision'],who,kind,payload or {})
        assert cold().journey_state(jid)==after
        return after
    if acquire:
        world('source_access','inheritance',{'variant':FAMILY,'route':'direct','source_rule':'A living mercury inheritance grants the first Qi Subpath choice.'})
        state=cold().journey_state(jid);state=cold().journey_acquire_source(jid,state['revision'],A,FAMILY,{'access_scope':'inheritance'})
        assert any(e['kind']=='QUICKSILVER_SOURCE_ACQUIRED' for e in state['events'])
    return cold,jid,act,world

def combat(cold,jid,tmp_path):
    s=cold();state=s.journey_state(jid);mid=s.journey_start_combat(jid,state['revision'],{A:'team:a',B:'team:b'})['match_id']
    table=TabletopService(cold(),tmp_path);turn(table,mid,A)
    return table,mid

def engine(cold,mid):
    session=cold()._load_session(mid)
    assert session.mechanical.replay()['status']=='PASS'
    assert not any(e.event_type=='GM_RIDER' and e.source_definition_id.startswith('ext:combat.ext.mgr_reserve_living') for e in session.engine.events)
    return session.engine

def use(cold,table,mid,label,picks=None):
    c=candidate(cold(),mid,label,at=(3,4) if label.startswith('Create Quicksilver Body') else None)
    settle(table,mid,c.candidate_id,picks=picks)
    return engine(cold,mid)

@pytest.mark.parametrize('cl,count',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_access_acquires_only_earned_progression_and_scene_mass(tmp_path,monkeypatch,cl,count):
    cold,jid,act,world=setup(tmp_path,monkeypatch,cl)
    state=cold().journey_state(jid);bundle=state['actors'][A]['bundle']
    owned={p['feature_id'] for p in bundle['typed_passives'] if p.get('block')=='living_quicksilver'}
    assert owned==set(FEATURES[:count])
    assert state['actors'][A]['resources'][MASS]==(bundle['actor_template']['proficiency_bonus']+1)//2
    assert MASS not in state['actors'][B]['resources']
    table,mid=combat(cold,jid,tmp_path);e=engine(cold,mid)
    assert e.state.actors[A].resources[MASS]==(bundle['actor_template']['proficiency_bonus']+1)//2
    assert MASS not in e.state.actors[B].resources

def test_no_access_or_unknown_source_cannot_grant_features(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,acquire=False)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,before['revision'],A,FAMILY,{'access_scope':'invented'})
    assert cold().journey_state(jid)==before
    with pytest.raises(ValueError):cold().journey_acquire_source(jid,before['revision'],A,'unknown',{})
    assert cold().journey_state(jid)==before

def test_body_creation_rejoin_cost_capacity_and_cold_replay(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,6)
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    bodies=[o for o in e.state.objects.values() if o.component.get('quicksilver_body') and not o.destroyed]
    assert len(bodies)==1 and bodies[0].maximum_hp==12 and bodies[0].ac==14
    assert e.state.actors[A].resources[QI]==28
    e=use(cold,table,mid,'Rejoin: regain Quicksilver Mass')
    assert all(o.destroyed for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    assert e.state.actors[A].resources[MASS]==3


def test_full_cultivation_changes_only_superficial_profile_and_uses_two_hours(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,3)
    act('declare_fact',{'source':FAMILY,'subject':A,'kind':'cultivation_environment','scope':'calm','value':{'calm':1,'ambient_qi':1},'expires_at':10000,'readers':[A]})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):act('quicksilver_cultivate',{'environment_scope':'calm','appearance':{'functional_wings':'yes'}})
    assert cold().journey_state(jid)==before
    after=act('quicksilver_cultivate',{'environment_scope':'calm','appearance':{'hair':'silver','voice_resonance':'deep'}})
    assert after['seconds']==7200
    assert after['actors'][A]['source_states'][FAMILY]['appearance']=={'hair':'silver','voice_resonance':'deep'}
    table,mid=combat(cold,jid,tmp_path)
    e=engine(cold,mid)
    held=next(c for c in e.state.actors[A].conditions.values() if c.condition_id=='condition:typed.living_quicksilver_ledger')
    assert held.data['appearance']['hair']=='silver'


def test_undying_native_activation_free_body_turn_choice_expiry_and_replay(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,18)
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Undying Prima Materia')
    assert e.state.actors[A].resources[QI]==28
    from combat.flight import profile
    assert profile(e,e.state.actors[A]).speed_ft==50 and profile(e,e.state.actors[A]).hover
    turn(table,mid,B)
    from tests.worker2_support import settle
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.quicksilver.configuration':'mirror'})
    e=engine(cold,mid)
    bs=[o for o in e.state.objects.values() if o.component.get('quicksilver_body') and not o.destroyed]
    assert bs and all(o.maximum_hp==72 and o.component['hover']==1 for o in bs)
    # The transformation still has a native ten-round expiry, never rest-of-fight.
    held=next(c for c in e.state.actors[A].conditions.values() if c.condition_id=='condition:typed.undying_prima_materia')
    from combat.ext.effect_durations import parse_round
    assert parse_round(held.expires_on)==(11,e.state.initiative_order.index(A))


def test_body_occupies_space_without_creating_a_wall_and_wrong_owner_is_inert(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,6)
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    body=next(o for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    assert (3,4) in e._occupied_cells_except(A)
    assert e.grid.line_of_sight(e.state.actors[A].position,e.state.actors[B].position)
    assert not any(c.destination==body.position for c in e.legal_candidates() if c.kind=='MOVE')
    assert not any(c.parameters.get('quicksilver_command') for c in e.action_catalog.values() if c.owner_id==B)
    # No dependent creature/initiative slot was invented for the targetable Body.
    assert set(e.state.actors)=={A,B}
    assert set(e.state.initiative_order)=={A,B}


def test_native_scene_boundary_cannot_be_faked_by_rest_or_actor_declaration(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,18)
    act('declare_fact',{'source':FAMILY,'subject':A,'kind':'cultivation_environment','scope':'calm','value':{'calm':1,'ambient_qi':1},'expires_at':10000,'readers':[A]})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):
        act('declare_fact',{'source':'system:journey.scene','subject':A,'kind':'scene_end','scope':'false-end','value':'It ended','expires_at':1,'readers':[A]})
    assert cold().journey_state(jid)==before
    after=act('long_rest')
    assert not any(e['kind']=='SCENE_ENDED' for e in after['events'])
    next_scene=cold().journey_end_scene(jid,after['revision'],'The table owner ends the courtyard encounter and begins a new meaningful situation.')
    assert next_scene['actors'][A]['resources'][MASS]==3
    assert any(e['kind']=='SCENE_ENDED' for e in next_scene['events'])


@pytest.mark.parametrize('guard',['below_path_level','expired_access','wrong_subject','repeat_acquisition','unowned_cultivation'])
def test_source_authority_boundaries_are_native_atomic(tmp_path,monkeypatch,guard):
    cold,jid,act,world=setup(tmp_path,monkeypatch,2 if guard=='below_path_level' else 6,acquire=guard in ('repeat_acquisition','unowned_cultivation'))
    if guard=='unowned_cultivation':
        before=cold().journey_state(jid)
        with pytest.raises(ValueError):act('quicksilver_cultivate',{'environment_scope':'unknown'},B)
        assert cold().journey_state(jid)==before
        return
    if guard!='repeat_acquisition':
        world('source_access','inheritance',{'variant':FAMILY,'route':'direct','source_rule':'An actual inheritance Source grants the first Subpath choice.'})
    if guard=='expired_access':act('wait',{'seconds':2592000})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):
        cold().journey_acquire_source(jid,before['revision'],B if guard=='wrong_subject' else A,FAMILY,{'access_scope':'inheritance'})
    assert cold().journey_state(jid)==before


def test_native_qi_damage_conversion_poison_resistance_and_mass_are_not_blanket_immunity(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,3,own_features=['FIRE_BASE_CONFLAGRATION'])
    world('source_access','second-inheritance',{'variant':FAMILY,'route':'direct','source_rule':'A second actual living mercury inheritance grants this creature its first Qi Subpath choice.'},subject=B,readers=[B])
    state=cold().journey_state(jid)
    cold().journey_acquire_source(jid,state['revision'],B,FAMILY,{'access_scope':'second-inheritance'})
    table,mid=combat(cold,jid,tmp_path)
    before=engine(cold,mid).state.actors[B].current_hp
    c=candidate(cold(),mid,'Conflagration',at=(8,3))
    prompts=settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.conversion':'POISON'})
    e=engine(cold,mid)
    packets=[x for x in e.events if x.event_type=='DAMAGE_COMMITTED' and B in x.target_ids]
    assert packets and packets[-1].payload['damage_type']=='POISON'
    p=packets[-1].payload
    assert p['reduced_to']==p['rolled_or_pending_damage']//2
    assert e.state.actors[B].current_hp<before
    assert e.state.actors[B].resources[MASS]==2
    assert e.state.actors[A].resources[QI]==27
    assert any(p['context']['reactor_id']==A for p in prompts if p['context']['reaction_source_id']=='choice:needle.quicksilver.conversion')


def test_record_pattern_comes_from_actual_hostile_qi_resolution_and_replays(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,10,enemy_features=['FIRE_BASE_CONFLAGRATION'])
    table,mid=combat(cold,jid,tmp_path)
    turn(table,mid,B)
    c=candidate(cold(),mid,'Conflagration',at=(3,3))
    prompts=settle(table,mid,c.candidate_id,picks={'choice:needle.quicksilver.record_pattern':'0'})
    e=engine(cold,mid)
    d=next(c.data for c in e.state.actors[A].conditions.values() if c.condition_id=='condition:typed.living_quicksilver_ledger')
    assert d['pattern']['kind']=='damage' and d['pattern']['value']=='FIRE'
    assert d['pattern']['source']=='FIRE_BASE_CONFLAGRATION'
    assert e.state.actors[A].resources[QI]==27 and not e.state.actors[A].reaction_available
    assert e.state.actors[A].resources[MASS]==3
    assert any(p['context']['reactor_id']==A for p in prompts if p['context']['reaction_source_id']=='choice:needle.quicksilver.record_pattern')
