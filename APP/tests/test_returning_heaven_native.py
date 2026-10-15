"""Returning-Heaven service regressions; resources come from committed movement."""
import pytest
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.worker2_support import fixture, candidate, reload, settle, turn, OWNER, ALLY, FOE
from tests.hunt12_support import hit_dice
from tests.h1_support import ROOT
P = 'tianxia.subpath.body.returning_heaven_momentum_body.feature.'
M = 'resource:named.momentum'
IRON = 'tianxia.path.body_refining.feature.iron_fist'
LEVELS = [(3, 'gather_and_return'), (6, 'store_the_collision'), (10, 'rebounding_assault'),
          (14, 'avalanche_meridian_circuit'), (18, 'heaven_returning_impact')]

def start(tmp_path,cl=14,owned=True,*,foe_features=(),positions=None,arena=None,map_objects=None,foe_score=10,owner_kit=None,body_cl=None,maximum_rounds=30,journey=False,auto_foe=False,owner_core_features=()):
    import json,zipfile
    from tests.h1_support import sheet
    from combat.tabletop_service import TabletopService
    docs={OWNER:sheet([IRON,*owner_core_features],cl=cl,primary='Stamina',key='STR',score=20,dc=22,kit=owner_kit),
          ALLY:sheet([],cl=cl),FOE:sheet(list(foe_features),cl=cl,score=foe_score)}
    docs[OWNER]['identity'].update(path='Body Refining',proficiency_bonus=6)
    docs[OWNER]['path_and_subpath']['path_record_ids']=['tianxia.path.body_refining']
    if body_cl is not None:
        docs[OWNER]['path_and_subpath']['paths']=[{'path_id':'tianxia.path.body_refining','effective_cl':body_cl}]
    for aid,doc in docs.items():
        doc['ability_scores_and_statistics']['hit_points']['maximum']=300
        folder=tmp_path/'portable_characters'/aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    def cold():return CombatService(ROOT,tmp_path)
    combat=cold()
    chosen_arena=next(iter(combat.factory_arenas()))
    if map_objects is not None:
        doc=combat.tabletop_maps.get(chosen_arena.removeprefix('battlefield:map.'))
        doc.update(map_id='momentum-native-map',display_name='Momentum native map',objects=map_objects)
        combat.tabletop_maps.save(doc)
        chosen_arena='battlefield:map.momentum-native-map'
    state=combat.create_journey(project_ids=[aid.removeprefix('actor:factory.') for aid in docs],
        arena_id=chosen_arena,positions=positions or {OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':8,'y':6}},
        base_paces={aid:3000 for aid in docs},control_modes={FOE:'LOCAL_AUTO'} if auto_foe else None)
    jid=state['journey_id']
    if owned:
        menu=cold().journey_source_choices(jid,OWNER,P.removesuffix('.feature.'))
        assert len(menu['options'])==1
        state=cold().journey_acquire_source(jid,menu['revision'],OWNER,P.removesuffix('.feature.'),menu['options'][0]['payload'])
        assert cold().journey_source_choices(jid,OWNER,P.removesuffix('.feature.'))['options']==[]
    result=cold().journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'},maximum_rounds=maximum_rounds)
    mid=result['match_id'];combat=cold();table=TabletopService(combat,tmp_path)
    turn(table,mid,OWNER)
    return (combat,table,mid,jid) if journey else (combat,table,mid)

def move(combat, table, mid, x, y=6):
    row = next(c for c in combat._load_session(mid).engine.legal_candidates()
               if c.kind == 'MOVE' and c.destination == Position(x=x,y=y))
    settle(table, mid, row.candidate_id, choices={'choice:needle.fact_admission.momentum_eligibility':'genuine'})

def strike(combat,mid,target):
    engine=combat._load_session(mid).engine
    rows=[c for c in engine.legal_candidates() if c.target_ids==(target,)
        and any(e.get('type')=='attack' and e.get('attack_kind')=='unarmed'
                for e in ((getattr(engine.action_catalog.get(c.source_definition_id),'parameters',{}) or {}).get('typed') or {}).get('effects',[]))]
    assert rows,[(a.display_name,a.source_definition_id) for a in engine.action_catalog.values() if a.owner_id==engine.state.current_actor_id]
    return rows[0]

def checked(tmp_path, mid):
    session = CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine

@pytest.mark.parametrize('cl,expected',[(3,6),(14,9)])
def test_momentum_native_movement_round_budget_and_maximum(tmp_path, cl, expected):
    combat,table,mid = start(tmp_path,cl)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[M] == 0
    move(combat,table,mid,7)
    engine = checked(tmp_path,mid); a=engine.state.actors[OWNER]
    assert a.resources[M] == (2 if cl>=14 else 1)
    from combat.ext.subpath_pools import maximum
    assert maximum(engine,a,M) == expected
    move(combat,table,mid,7,5)
    assert checked(tmp_path,mid).state.actors[OWNER].resources[M] == (2 if cl>=14 else 1)

@pytest.mark.parametrize('cl,option,dice',[(14,'die',2),(17,'die',3),(14,'push',0)])
def test_avalanche_replaces_base_damage_and_options_before_damage(tmp_path,monkeypatch,cl,option,dice):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl)
    move(combat,table,mid,7)
    engine=reload(tmp_path,mid); before=len(engine.events)
    row=strike(combat,mid,FOE)
    settle(table,mid,row.candidate_id,picks={
        'choice:needle.gather_and_return':(option,None),
        'choice:needle.gather_damage_type':'force'})
    engine=checked(tmp_path,mid)
    events=engine.events[before:]
    bonus=[r for r in engine.rolls if 'Gather and Return' in r.reason]
    if dice:
        assert bonus and bonus[-1].expression.startswith(str(dice)+'d8')
    else:
        assert not bonus
    spent=[e for e in events if e.event_type=='RESOURCE_SPENT' and e.payload.get('resource_id')==M]
    damage=[e for e in events if e.event_type=='DAMAGE_COMMITTED']
    assert spent and damage and spent[0].sequence < damage[0].sequence
    assert engine.state.actors[OWNER].resources[M] == 1


def test_wrong_owner_has_no_momentum_choices_or_resource(tmp_path):
    combat,table,mid=start(tmp_path,owned=False)
    move(combat,table,mid,7)
    engine=checked(tmp_path,mid)
    assert M not in engine.state.actors[OWNER].resources
    assert not any(e.source_definition_id.startswith(P) for e in engine.events)


def test_acquisition_rejects_wrong_path_and_duplicate_progression(tmp_path):
    # The source menu cannot grant features to a character on another Path.
    from combat.ext.momentum_body import _selection_legal
    from tests.h1_support import sheet
    doc=sheet([],cl=18)
    assert not _selection_legal(doc)
    doc.setdefault('path_and_subpath',{})['path_record_ids']=['tianxia.path.body_refining']
    doc['path_and_subpath']['subpath_record_ids']=['tianxia.subpath.body.iron_shirt']
    assert not _selection_legal(doc)
    combat,table,mid=start(tmp_path)
    engine=checked(tmp_path,mid)
    roles=[r for r in engine.typed_passive_rows[OWNER] if r.get('kind')=='momentum']
    assert len([r for r in roles if r.get('role')=='rebound'])==1
    assert {r['role'] for r in roles}>={'gather','store','rebound','avalanche'}


@pytest.mark.parametrize('option',['ac','next_push','push','move'])
def test_gather_native_options_are_reachable_after_acquisition(tmp_path,monkeypatch,option):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=11)
    move(combat,table,mid,7)
    row=strike(combat,mid,FOE)
    prompts=settle(table,mid,row.candidate_id,picks={'choice:needle.gather_and_return':option,
        'choice:needle.gather_damage_type':'force','choice:needle.gather_move':'cell:7,5'})
    engine=checked(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.gather_and_return' for p in prompts)
    assert engine.state.actors[OWNER].resources[M]==0
    assert len([e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER])==1
    if option=='ac':
        guards=[c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id=='condition:typed.ac_against']
        assert len(guards)==1 and guards[0].data['against']==FOE and guards[0].data['amount']==1
    if option=='next_push':
        assert any(c.condition_id.endswith('gather_next_push') for c in engine.state.actors[OWNER].conditions.values())
    if option=='move':
        assert engine.state.actors[OWNER].position==Position(x=7,y=5)
    if option=='push':
        assert engine.state.actors[FOE].position==Position(x=9,y=6)
    if option in ('ac','next_push'):
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
        if option=='ac':
            assert any(c.condition_id=='condition:typed.ac_against' for c in checked(tmp_path,mid).state.actors[OWNER].conditions.values())
            turn(table,mid,OWNER)
        assert not any(c.condition_id in ('condition:typed.ac_against','condition:typed.gather_next_push') for c in checked(tmp_path,mid).state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('auto',[False,True])
def test_store_impact_off_turn_cost_and_direct_gain_survive_reload(tmp_path,monkeypatch,auto):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=6,foe_features=[IRON],auto_foe=auto)
    move(combat,table,mid,7)
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER]
    selected=strike(combat,mid,OWNER)
    real=combat.controller
    if auto:
        from combat.gate4_adapters import ManualControllerAdapter
        class FakeTransport:
            def choose_primary_action(self,context):
                return ManualControllerAdapter(lambda _:(selected.candidate_id,())).choose_primary_action(context)
            def __getattr__(self,key):return getattr(real,key)
        combat.controller=FakeTransport()
    try:
        prompts=settle(table,mid,selected.candidate_id,auto=auto,
            choices={'choice:needle.store_impact':'store','choice:needle.fact_admission.momentum_eligibility':'genuine'})
    finally:combat.controller=real
    engine=checked(tmp_path,mid);owner=engine.state.actors[OWNER]
    assert any(p['context']['reaction_source_id']=='choice:needle.store_impact' for p in prompts)
    assert owner.resources['resource:core.stamina']==before.resources['resource:core.stamina']-1
    assert not owner.reaction_available
    assert owner.current_hp==before.current_hp
    assert owner.resources[M]==2  # one real movement grant + Store's direct grant


def test_rebounding_assault_after_melee_damage_runs_granted_strike(tmp_path,monkeypatch):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=14,foe_features=[IRON])
    move(combat,table,mid,7)
    turn(table,mid,FOE)
    row=strike(combat,mid,OWNER)
    prompts=settle(table,mid,row.candidate_id,choices={
        'choice:needle.rebounding_assault':'use','choice:needle.fact_admission.momentum_eligibility':'genuine','choice:needle.rebound_move':'cell:7,5',
        'choice:needle.rebound_hit':'prone'})
    engine=checked(tmp_path,mid)
    assert any(p['context']['reaction_source_id']=='choice:needle.rebounding_assault' for p in prompts)
    assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER for e in engine.events)
    assert any(c.condition_id.endswith('.prone') for c in engine.state.actors[FOE].conditions.values())


def test_heaven_impact_native_spends_all_momentum_and_leaves_bounded_ground(tmp_path,monkeypatch):
    hit_dice(monkeypatch,save_roll=1)
    combat,table,mid=start(tmp_path,cl=18)
    move(combat,table,mid,7)
    turn(table,mid,OWNER)  # already own turn: explicitly end through a new round
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    engine=reload(tmp_path,mid);assert engine.state.actors[OWNER].resources[M]==4
    row=candidate(combat,mid,'Heaven-Returning Impact',at=(10,6))
    quoted=engine.effective_costs(engine.state.actors[OWNER],row.source_definition_id,engine.action_catalog[row.source_definition_id].costs)
    assert dict(quoted)[M]==4
    settle(table,mid,row.candidate_id,choices={'choice:needle.impact_push':None})
    engine=checked(tmp_path,mid)
    assert engine.state.actors[OWNER].resources[M]==0
    assert engine.state.actors[OWNER].position==Position(x=10,y=6)
    assert any(r.reason=='DAMAGE:'+P+'heaven_returning_impact' and r.expression.startswith('10d10') for r in engine.rolls)
    hits=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id.endswith(P+'heaven_returning_impact')]
    assert len([e for e in hits if FOE in e.target_ids])==1
    assert len([e for e in hits if ALLY in e.target_ids])==1
    zones=[z for z in engine.state.zones.values() if z.source_definition_id.endswith(P+'heaven_returning_impact')]
    assert zones and all(engine.grid.distance_ft(zones[-1].center,c)<=10 for c in zones[-1].affected_cells)
    assert any(c.condition_id.endswith('.prone') for c in engine.state.actors[FOE].conditions.values())


def test_source_progression_uses_body_path_cl_instead_of_header_cl(tmp_path):
    combat,table,mid=start(tmp_path,cl=18,body_cl=3)
    engine=checked(tmp_path,mid)
    roles={row.get('role') for row in engine.typed_passive_rows[OWNER] if row.get('kind')=='momentum'}
    assert roles=={'gather'}
    assert not any(a.owner_id==OWNER and ((a.parameters or {}).get('typed') or {}).get('source')==P+'heaven_returning_impact' for a in engine.action_catalog.values())
    move(combat,table,mid,7)
    assert checked(tmp_path,mid).state.actors[OWNER].resources[M]==1


def test_store_movement_reduces_native_brutal_shove_and_gains_direct_point(tmp_path,monkeypatch):
    from tests.test_lock_choices import install
    install(monkeypatch,'d20_result',lambda *args:{'source_id':'test:roll','operation':'replace','natural_result':10})
    combat,table,mid=start(tmp_path,cl=6,foe_features=['BRUTE_BASE_BRUTAL_SHOVE'],foe_score=30)
    move(combat,table,mid,7)
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER]
    prompts=settle(table,mid,candidate(combat,mid,'Brutal Shove',target=OWNER).candidate_id,choices={
        'choice:needle.brute_contest_skill':'Athletics','choice:needle.brutal_shove_result':'push','choice:needle.store_the_collision_move':'first',
        'choice:needle.fact_admission.momentum_eligibility':'genuine'})
    engine=checked(tmp_path,mid);owner=engine.state.actors[OWNER]
    assert any(p['context']['reaction_source_id']=='choice:needle.store_the_collision_move' for p in prompts)
    assert owner.position==before.position
    assert not owner.reaction_available
    assert owner.resources['resource:core.stamina']==before.resources['resource:core.stamina']-1
    assert owner.resources[M]>=before.resources[M]+1


@pytest.mark.parametrize('hp,threshold,resist',[(1,0,[]),(999,0,['FORCE']),(1,999,[])])
def test_impact_uses_native_map_object_threshold_damage_and_recoil(tmp_path,monkeypatch,hp,threshold,resist):
    hit_dice(monkeypatch,save_roll=1)
    obj={'id':1,'kind':'custom','name':'Trial barrier','x':9,'y':6,'height_ft':2,'material':'stone',
         'hp':hp,'blocks':True,'unattended':True,'threshold':threshold,'resist':resist,'cover':'half',
         'asset_declaration':{'actor':'GM of the trial map','authority':'GM','source_rule':'This two-foot barrier provides half cover while blocking physical passage.',
             'visibility':'public','expiry':'source_rule'}}
    combat,table,mid=start(tmp_path,cl=18,map_objects=[obj])
    move(combat,table,mid,7)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    before=reload(tmp_path,mid).state.actors[OWNER]
    assert before.resources[M]==4
    row=candidate(combat,mid,'Heaven-Returning Impact',at=(12,6))
    prompts=settle(table,mid,row.candidate_id,choices={'choice:needle.impact_push':None,'choice:needle.store_impact':'store'})
    engine=checked(tmp_path,mid);actor=engine.state.actors[OWNER]
    barrier=engine.state.objects['object:map.1']
    roll=next(r for r in engine.rolls if r.reason=='DAMAGE:'+P+'heaven_returning_impact')
    expected=0 if threshold and roll.total<threshold else 2*(roll.total//2 if resist else roll.total)
    assert barrier.current_hp==max(0,hp-expected)
    assert barrier.destroyed is (expected>=hp)
    assert actor.resources[M]==0
    if barrier.destroyed:
        assert actor.position==Position(x=12,y=6)
        assert actor.current_hp==before.current_hp
    else:
        assert actor.position.x<9
        assert actor.current_hp==before.current_hp-36
        assert not any(p['context']['reaction_source_id']=='choice:needle.store_impact' for p in prompts)


@pytest.mark.parametrize('x,expected',[(4,0),(5,1)])
def test_hostile_native_teleport_uses_actual_distance_not_two_point_path_length(tmp_path,monkeypatch,x,expected):
    hit_dice(monkeypatch,save_roll=1)
    combat,table,mid=start(tmp_path,cl=3,foe_features=['tianxia.talent.space.spatial_displacement'])
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Spatial Displacement',target=OWNER).candidate_id,choices={
        'choice:needle.subject_destination':f'cell:{x},6','choice:needle.fact_admission.momentum_eligibility':'genuine'})
    engine=checked(tmp_path,mid)
    assert engine.state.actors[OWNER].position==Position(x=x,y=6)
    assert engine.state.actors[OWNER].resources[M]==expected
    assert any(e.event_type=='MOVEMENT_COMMITTED' and e.payload.get('teleport') and e.payload.get('source_actor_id')==FOE for e in engine.events)


def test_scene_momentum_survives_encounter_and_rest_until_explicit_scene_end(tmp_path):
    combat,table,mid,jid=start(tmp_path,cl=14,maximum_rounds=1,journey=True)
    move(combat,table,mid,7)
    for _ in range(12):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    assert checked(tmp_path,mid).state.actors[OWNER].resources[M]==2
    state=combat.journey_state(jid)
    state=combat.journey_resume(jid,state['revision'])
    assert state['actors'][OWNER]['resources'][M]==2
    state=combat.journey_act(jid,state['revision'],OWNER,'long_rest',{})
    assert state['actors'][OWNER]['resources'][M]==2
    state=combat.journey_end_scene(jid,state['revision'],'The pursuit ended at a safe destination.')
    assert state['actors'][OWNER]['resources'][M]==0
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    result=combat.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'})
    assert checked(tmp_path,result['match_id']).state.actors[OWNER].resources[M]==0


def test_impact_ground_continues_into_travel_and_clears_with_native_minute_work(tmp_path,monkeypatch):
    hit_dice(monkeypatch,save_roll=1)
    shovel={'starting_kit':{'items':[{'item_id':'tianxia.mortal.gear.shovel'}]}}
    combat,table,mid,jid=start(tmp_path,cl=18,owner_kit=shovel,maximum_rounds=2,journey=True)
    move(combat,table,mid,7)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    settle(table,mid,candidate(combat,mid,'Heaven-Returning Impact',at=(10,6)).candidate_id,choices={'choice:needle.impact_push':None})
    for _ in range(12):
        if reload(tmp_path,mid).state.terminal_result is not None:break
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    checked(tmp_path,mid)
    state=combat.journey_state(jid)
    state=combat.journey_resume(jid,state['revision'],effect_resolutions={a:'The timed combat effects ended after the encounter.' for a in [OWNER,ALLY,FOE]})
    menu=CombatService(ROOT,tmp_path).journey_menu(jid,OWNER)
    option=next(o for o in menu['options'] if o['kind']=='clear_impact_ground')
    maker=next(iter(state['actors'][OWNER]['source_states'][P.removesuffix('.feature.')+'.damaged_ground']['maps'].values()))
    import json
    before=sum(len(json.loads(z)['affected_cells']) for z in maker['zones'])
    seconds=state['seconds']
    state=combat.journey_act(jid,state['revision'],OWNER,option['kind'],option['payload'])
    assert state['seconds']==seconds+60
    saved=next(iter(state['actors'][OWNER]['source_states'][P.removesuffix('.feature.')+'.damaged_ground']['maps'].values()))
    assert sum(len(json.loads(z)['affected_cells']) for z in saved['zones'])==before-1
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    result=combat.journey_start_combat(jid,state['revision'],{OWNER:'team:a',ALLY:'team:a',FOE:'team:b'})
    engine=checked(tmp_path,result['match_id'])
    assert sum(len(z.affected_cells) for z in engine.state.zones.values() if z.source_definition_id.endswith(P+'heaven_returning_impact'))==before-1


@pytest.mark.parametrize('restriction',['sealed_formation','spatial_lock'])
def test_impact_obeys_explicit_native_gm_spatial_boundary_without_barrier_recoil(tmp_path,monkeypatch,restriction):
    hit_dice(monkeypatch,save_roll=1)
    obj={'id':1,'kind':'custom','name':'Declared boundary','x':9,'y':6,'height_ft':2,'material':'stone',
         'hp':999,'blocks':False,'unattended':True,restriction:True,
         'asset_declaration':{'actor':'GM of this scene','authority':'GM','source_rule':'The active boundary forbids physical passage.',
             'visibility':'gm','expiry':'source_rule'}}
    combat,table,mid=start(tmp_path,cl=18,map_objects=[obj])
    move(combat,table,mid,7)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    before=reload(tmp_path,mid).state.actors[OWNER]
    settle(table,mid,candidate(combat,mid,'Heaven-Returning Impact',at=(12,6)).candidate_id,choices={'choice:needle.impact_push':None})
    engine=checked(tmp_path,mid);actor=engine.state.actors[OWNER]
    assert actor.position.x<9 and actor.current_hp==before.current_hp
    assert engine.state.objects['object:map.1'].component[restriction] is True
    assert actor.resources[M]==0


def test_native_spatial_profile_rejects_missing_gm_authority(tmp_path):
    combat=CombatService(ROOT,tmp_path)
    with pytest.raises(ValueError,match='GM authority'):
        combat.tabletop_maps.save({'display_name':'Invalid undeclared spatial boundary','width_squares':20,'height_squares':20,
            'walls':[],'objects':[{'id':1,'kind':'custom','name':'Boundary','x':9,'y':6,'spatial_lock':True}],
            'starts':{'team1':[[3,6]],'team2':[[8,6]]}})


def test_rebound_after_actual_hostile_teleport_uses_source_and_granted_attack_packet(tmp_path,monkeypatch):
    hit_dice(monkeypatch,save_roll=1)
    combat,table,mid=start(tmp_path,cl=14,foe_features=['tianxia.talent.space.spatial_displacement'])
    move(combat,table,mid,7)
    move(combat,table,mid,5)
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER]
    assert before.resources[M]==2
    prompts=settle(table,mid,candidate(combat,mid,'Spatial Displacement',target=OWNER).candidate_id,choices={
        'choice:needle.subject_destination':'cell:4,6','choice:needle.rebounding_assault':'use',
        'choice:needle.rebound_move':'cell:7,6','choice:needle.rebound_hit':'push',
        'choice:needle.fact_admission.momentum_eligibility':'genuine'})
    engine=checked(tmp_path,mid);owner=engine.state.actors[OWNER]
    receipt=next(e for e in engine.events if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==OWNER and e.payload.get('teleport'))
    assert receipt.payload['source_actor_id']==FOE
    assert any(p['context']['reaction_source_id']=='choice:needle.rebounding_assault' for p in prompts)
    assert owner.resources[M]==0 and not owner.reaction_available
    assert owner.position==Position(x=7,y=6)
    assert engine.state.actors[FOE].position==Position(x=10,y=6)
    packets=[e for e in engine.events if e.event_type=='DAMAGE_COMMITTED' and e.actor_id==OWNER and FOE in e.target_ids]
    assert len(packets)==1
    assert any(c['damage_type']=='FORCE' and c['amount']==6 for c in packets[0].payload['damage_components'])


def test_rebound_after_actual_melee_miss_preserves_no_closer_space_rule(tmp_path,monkeypatch):
    from tests.test_lock_choices import install
    install(monkeypatch,'d20_result',lambda engine,roll,intent:{'source_id':'test:fixed-die',
        'operation':'replace','natural_result':1 if roll.actor_id==FOE else 18})
    combat,table,mid=start(tmp_path,cl=14,foe_features=[IRON])
    move(combat,table,mid,7)
    turn(table,mid,FOE)
    prompts=settle(table,mid,strike(combat,mid,OWNER).candidate_id,choices={
        'choice:needle.rebounding_assault':'use','choice:needle.rebound_hit':'prone'})
    engine=checked(tmp_path,mid);owner=engine.state.actors[OWNER]
    missed=[e for e in engine.events if e.event_type=='ATTACK_ROLLED' and e.actor_id==FOE]
    assert missed and missed[-1].payload['provisional_hit'] is False
    assert any(p['context']['reaction_source_id']=='choice:needle.rebounding_assault' for p in prompts)
    assert owner.resources[M]==0 and not owner.reaction_available
    assert owner.position==Position(x=7,y=6)  # no legal space closer than adjacent
    assert any(e.event_type=='ATTACK_ROLLED' and e.actor_id==OWNER for e in engine.events)


def test_store_impact_on_native_ladder_fall_keeps_gravity_prone_and_no_farming(tmp_path):
    obj={'id':1,'kind':'custom','name':'Trial ladder','x':4,'y':5,'height_ft':10,'blocks':False,'ordinary_route':'ladder',
         'asset_declaration':{'actor':'GM of the fall trial','authority':'GM',
             'source_rule':'A stable ordinary ladder reaches its ten-foot top.','visibility':'public','expiry':'source_rule'}}
    combat,table,mid=start(tmp_path,cl=6,map_objects=[obj])
    engine=reload(tmp_path,mid)
    climb=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=4,y=5,z=2))
    settle(table,mid,climb.candidate_id,choices={'choice:needle.fact_admission.momentum_eligibility':'excluded'})
    checked(tmp_path,mid)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    engine=checked(tmp_path,mid);before=engine.state.actors[OWNER]
    drops=[c for c in engine.legal_candidates() if c.kind=='MOVE' and c.metadata.get('movement_mode')=='jump_down']
    assert drops,'An actual ladder top must permit the native jump-down procedure.'
    prompts=settle(table,mid,drops[0].candidate_id,choices={
        'choice:needle.store_impact':'store','choice:needle.fact_admission.momentum_eligibility':'excluded'})
    engine=checked(tmp_path,mid);owner=engine.state.actors[OWNER]
    assert any(p['context']['reaction_source_id']=='choice:needle.store_impact' for p in prompts)
    assert not any(p['context']['reaction_source_id']=='choice:needle.store_the_collision_move' for p in prompts)
    assert owner.resources['resource:core.stamina']==before.resources['resource:core.stamina']-1
    assert owner.current_hp==before.current_hp and owner.resources[M]==0
    assert any(c.condition_id=='condition:typed.prone' for c in owner.conditions.values())
    assert any(e.event_type=='DAMAGE_COMMITTED' and e.source_definition_id=='system:combat.falling' for e in engine.events)


@pytest.mark.parametrize('classification',[None,'formation_anchor','vehicle','terrain_section'])
def test_impact_uses_native_gm_object_classification_for_attended_targets(tmp_path,monkeypatch,classification):
    hit_dice(monkeypatch,save_roll=1)
    obj={'id':1,'kind':'custom','name':'Attended trial object','x':9,'y':6,'height_ft':2,'material':'stone',
         'hp':999,'blocks':False,'unattended':False}
    if classification:
        obj.update({classification:True,'asset_declaration':{'actor':'GM of the object trial','authority':'GM',
            'source_rule':'The actual scene object has the declared '+classification.replace('_',' ')+ ' classification.',
            'visibility':'gm','expiry':'source_rule'}})
    combat,table,mid=start(tmp_path,cl=18,map_objects=[obj])
    public=table.state(mid)['map']['objects'][0]
    assert classification is None or classification not in public
    move(combat,table,mid,7)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    settle(table,mid,candidate(combat,mid,'Heaven-Returning Impact',at=(12,6)).candidate_id,choices={'choice:needle.impact_push':None})
    engine=checked(tmp_path,mid)
    roll=next(r for r in engine.rolls if r.reason=='DAMAGE:'+P+'heaven_returning_impact')
    assert engine.state.objects['object:map.1'].current_hp==999-(2*roll.total if classification else 0)
    assert engine.state.actors[OWNER].position==Position(x=12,y=6)


def test_impact_crosses_actual_non_solid_wind_wall_without_recoil(tmp_path,monkeypatch):
    hit_dice(monkeypatch,save_roll=1)
    combat,table,mid=start(tmp_path,cl=18,foe_features=['TAL_AIR_WIND_WALL'],
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':8,'y':10}})
    move(combat,table,mid,7)
    turn(table,mid,FOE)
    settle(table,mid,candidate(combat,mid,'Wind Wall',at=(9,6)).candidate_id,choices={})
    engine=checked(tmp_path,mid)
    walls=[z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('wall')]
    assert walls and not walls[-1].trigger_profile['wall'].get('blocks_movement')
    assert any(p.x==9 and p.y==6 for p in walls[-1].affected_cells)
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    before=reload(tmp_path,mid).state.actors[OWNER]
    assert before.resources[M]==4
    settle(table,mid,candidate(combat,mid,'Heaven-Returning Impact',at=(12,6)).candidate_id,choices={'choice:needle.impact_push':None})
    actor=checked(tmp_path,mid).state.actors[OWNER]
    assert actor.position==Position(x=12,y=6) and actor.current_hp==before.current_hp
    assert actor.resources[M]==0


@pytest.mark.parametrize('guard',['wrong_path','declared_body','feature_only_body'])
def test_native_source_admission_rejects_existing_body_progression_atomically(tmp_path,guard):
    import json,zipfile
    from tests.h1_support import sheet
    doc=sheet([],cl=18)
    if guard!='wrong_path':
        doc['identity']['path']='Body Refining'
        fields=doc.setdefault('path_and_subpath',{})
        fields['path_record_ids']=['tianxia.path.body_refining']
        if guard=='declared_body':fields['subpath_record_ids']=['tianxia.subpath.body.karate']
        else:fields['path_feature_record_ids']=['tianxia.subpath.body.karate.feature.precision_strike']
    folder=tmp_path/'portable_characters'/'worker2-owner';folder.mkdir(parents=True)
    with zipfile.ZipFile(folder/'current.zip','w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    combat=CombatService(ROOT,tmp_path)
    state=combat.create_journey(project_ids=['worker2-owner'],arena_id=next(iter(combat.factory_arenas())),
        positions={OWNER:{'x':3,'y':6}},base_paces={OWNER:3000})
    jid=state['journey_id'];source=P.removesuffix('.feature.')
    assert combat.journey_source_choices(jid,OWNER,source)['options']==[]
    with pytest.raises(ValueError,match='one Body Refining Subpath'):
        combat.journey_acquire_source(jid,state['revision'],OWNER,source,{'select':True})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


@pytest.mark.parametrize('benefit',['die','push','move'])
def test_avalanche_spends_three_real_points_and_repeats_each_printed_benefit(tmp_path,monkeypatch,benefit):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=14)
    move(combat,table,mid,7)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    turn(table,mid,FOE)
    row=next(c for c in reload(tmp_path,mid).legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=4,y=6))
    settle(table,mid,row.candidate_id,choices={})
    turn(table,mid,OWNER)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[M]==4
    prompts=settle(table,mid,strike(combat,mid,FOE).candidate_id,choices={
        'choice:needle.gather_and_return':(benefit,benefit,benefit),
        'choice:needle.gather_damage_type':'force','choice:needle.gather_move':'cell:3,9'})
    engine=checked(tmp_path,mid);owner=engine.state.actors[OWNER]
    assert owner.resources[M]==1
    assert len([p for p in prompts if p['context']['reaction_source_id']=='choice:needle.gather_and_return'])==3
    rolls=[r for r in engine.rolls if r.reason=='Gather and Return']
    if benefit=='die':assert rolls and rolls[-1].expression.startswith('6d8')
    else:assert not rolls
    if benefit=='push':assert engine.state.actors[FOE].position==Position(x=7,y=6)
    if benefit=='move':
        assert owner.position==Position(x=3,y=9)
        assert not any(e.event_type=='REACTION_RESOLVED' and 'opportunity' in e.source_definition_id.lower() for e in engine.events)


def test_destroyed_boundary_object_does_not_end_its_declared_spatial_lock(tmp_path,monkeypatch):
    hit_dice(monkeypatch,save_roll=1)
    obj={'id':1,'kind':'custom','name':'Lock focus','x':9,'y':6,'height_ft':2,'material':'stone','hp':1,
         'blocks':False,'unattended':True,'spatial_lock':True,
         'asset_declaration':{'actor':'GM of the lock trial','authority':'GM',
            'source_rule':'This spatial lock remains active until its source ends it; destroying its focus does not end it.',
            'visibility':'public','expiry':'source_rule'}}
    combat,table,mid=start(tmp_path,cl=18,map_objects=[obj])
    move(combat,table,mid,7)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    move(combat,table,mid,3)
    settle(table,mid,candidate(combat,mid,'Heaven-Returning Impact',at=(12,6)).candidate_id,choices={'choice:needle.impact_push':None})
    engine=checked(tmp_path,mid)
    assert engine.state.objects['object:map.1'].destroyed
    assert engine.state.actors[OWNER].position.x<9
    for x in [3,7]:
        settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
        turn(table,mid,OWNER)
        settle(table,mid,candidate(combat,mid,'Dash').candidate_id,choices={})
        move(combat,table,mid,x)
    settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
    turn(table,mid,OWNER)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[M]==4
    settle(table,mid,candidate(combat,mid,'Heaven-Returning Impact',at=(12,6)).candidate_id,choices={'choice:needle.impact_push':None})
    engine=checked(tmp_path,mid)
    assert engine.state.objects['object:map.1'].component['spatial_lock'] is True
    assert engine.state.actors[OWNER].position.x<9


@pytest.mark.parametrize('foe_score,expected',[(10,0),(30,2)])
def test_normal_momentum_uses_actual_stamina_guard_contribution_not_overkill_roll(tmp_path,monkeypatch,foe_score,expected):
    hit_dice(monkeypatch)
    guard='tianxia.path.body_refining.feature.stamina_guard'
    combat,table,mid=start(tmp_path,cl=14,foe_features=[IRON],foe_score=foe_score,owner_core_features=[guard],
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':4,'y':6}})
    turn(table,mid,FOE)
    settle(table,mid,strike(combat,mid,OWNER).candidate_id,choices={
        'reaction:typed.'+guard:'6','choice:needle.fact_admission.momentum_eligibility':'genuine'})
    engine=checked(tmp_path,mid);owner=engine.state.actors[OWNER]
    receipt=next(e for e in engine.events if e.event_type=='REACTION_RESOLVED' and e.source_definition_id==guard)
    assert receipt.payload['reduction']==6
    assert receipt.payload['pending_before']==(1 if foe_score==10 else 11)
    assert owner.resources[M]==expected
    triggers=[e for e in engine.events if e.event_type=='RESOURCE_TRIGGERED' and e.actor_id==OWNER]
    assert len(triggers)==(1 if expected else 0)
    if expected:assert triggers[0].source_definition_id==guard


@pytest.mark.parametrize('declaration,expected',[('genuine',2),('excluded',0)])
def test_hostile_damage_normal_momentum_uses_native_packet_and_source_declaration(tmp_path,monkeypatch,declaration,expected):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=14,foe_features=[IRON],
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':3,'y':7},FOE:{'x':4,'y':6}})
    turn(table,mid,FOE)
    before=reload(tmp_path,mid).state.actors[OWNER]
    settle(table,mid,strike(combat,mid,OWNER).candidate_id,choices={'choice:needle.fact_admission.momentum_eligibility':declaration})
    owner=checked(tmp_path,mid).state.actors[OWNER]
    assert owner.current_hp==before.current_hp-1 and owner.resources[M]==expected

def test_gather_next_forced_movement_is_armed_before_rebound_hit_push(tmp_path,monkeypatch):
    hit_dice(monkeypatch)
    combat,table,mid=start(tmp_path,cl=10,foe_features=[IRON])
    for index,x in enumerate([7,3,7]):
        if index:
            settle(table,mid,table.state(mid)['menu']['end_turn'],choices={})
            turn(table,mid,OWNER)
        move(combat,table,mid,x)
    assert reload(tmp_path,mid).state.actors[OWNER].resources[M]==3
    turn(table,mid,FOE)
    settle(table,mid,strike(combat,mid,OWNER).candidate_id,choices={
        'choice:needle.rebounding_assault':'use','choice:needle.rebound_hit':'push',
        'choice:needle.gather_and_return':'next_push','choice:needle.gather_damage_type':'force',
        'choice:needle.fact_admission.momentum_eligibility':'genuine'})
    engine=checked(tmp_path,mid)
    assert engine.state.actors[FOE].position==Position(x=11,y=6)
    assert engine.state.actors[OWNER].resources[M]==0
    assert not any(c.condition_id=='condition:typed.gather_next_push' for c in engine.state.actors[OWNER].conditions.values())
