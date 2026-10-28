"""Source-time procedures through native service, registry, and encounter entry."""
import pytest
from combat.gate5_service import CombatService
from combat.factory_compiler import compile_character
from combat.ext import formations, placed
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE


def game(tmp_path, *, owned=True, foe_score=14):
    service = CombatService(ROOT,tmp_path)
    kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.tool.thieves_tools','quantity':1,'name':'Thieves’ tools'},
        {'item_id':'tianxia.mortal.gear.chalk','quantity':1,'name':'Chalk'}]}}
    owner=sheet(['TRAP_BASE_DART_MECHANISM','FORMATIONS_BASE_SET_ARRAY'] if owned else [],cl=5,kit=kit)
    owner.setdefault('spheres_and_talents',{})['formation_patterns']=['locking_gate']
    bundles=[compile_character(owner,actor_id=OWNER),compile_character(sheet([],cl=5,score=foe_score),actor_id=FOE)]
    arena={'display_name':'Construction map','stable_id':'construction:scene','width_squares':20,'height_squares':15,
        'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    state=service.journeys.create(bundles,arena,{OWNER:{'x':3,'y':6},FOE:{'x':10,'y':6}},
        {OWNER:30,FOE:30})
    jid=state['journey_id']
    def cold(): return CombatService(ROOT,tmp_path)
    def act(kind,payload,aid=OWNER):
        s=cold().journey_state(jid)
        after=cold().journey_act(jid,s['revision'],aid,kind,payload)
        assert cold().journeys.replay(jid)['status']=='PASS'
        return after
    return cold,jid,act


def test_prepared_array_clock_cost_nodes_and_combat_replay(tmp_path):
    cold,jid,act=game(tmp_path)
    before=cold().journey_state(jid)['actors'][OWNER]['resources']['resource:core.qi']
    s=act('prepare_array',{'pattern':'locking_gate','center':{'x':4,'y':6},'site':'','damage_type':'force'})
    assert s['seconds']==600
    assert s['actors'][OWNER]['resources']['resource:core.qi']==before-3
    assert s['actors'][OWNER]['constructed_patterns'][0]['expires']==29400
    result=cold().journey_start_combat(jid,s['revision'],{OWNER:'a',FOE:'b'})
    session=cold()._load_session(result['match_id'])
    assert session.mechanical.replay()['status']=='PASS'
    e=session.engine
    z=formations.arrays(e,OWNER)[0]
    assert not z.concentration_link
    assert z.center.x==4
    assert len(formations.record(z)['nodes'])==3
    parts=formations.objects_of(e,z)
    assert len(parts)==4
    assert all(o.ac==15 for o in parts)
    assert sorted(o.maximum_hp for o in parts)==[15,15,15,25]
    assert e.state.actors[OWNER].concentration is None


def test_ritual_trap_no_focus_cost_and_source_expiry(tmp_path):
    cold,jid,act=game(tmp_path)
    before=cold().journey_state(jid)['actors'][OWNER]['resources']
    s=act('construct_trap',{'form':'tripwire','cells':[{'x':4,'y':6},{'x':4,'y':7}],'aim':'e'})
    assert s['seconds']==60
    assert s['actors'][OWNER]['resources']==before
    assert s['actors'][OWNER]['constructed_patterns'][0]['expires']==3660
    s=act('wait',{'seconds':3600})
    result=cold().journey_start_combat(jid,s['revision'],{OWNER:'a',FOE:'b'})
    session=cold()._load_session(result['match_id'])
    assert session.mechanical.replay()['status']=='PASS'
    assert not placed.of(session.engine,'trap')


def test_wrong_owner_unknown_pattern_and_stale_revision_are_atomic(tmp_path):
    cold,jid,act=game(tmp_path,owned=False)
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):
        act('prepare_array',{'pattern':'locking_gate','center':{'x':4,'y':6},'site':'','damage_type':'force'})
    assert cold().journey_state(jid)==before
    with pytest.raises(ValueError):
        cold().journey_act(jid,99,OWNER,'wait',{'seconds':1})
    assert cold().journey_state(jid)==before


def test_fixed_devices_do_not_gain_lifetime_when_journey_changes(tmp_path):
    cold,jid,act=game(tmp_path)
    act('construct_trap',{'form':'tripwire','cells':[{'x':4,'y':6}],'aim':'e'})
    s=act('wait',{'seconds':3599})
    act('finish',{})
    # Reopen the actual same acquired bundles through the native registry.
    prior=cold().journey_state(jid)
    bundles=[prior['actors'][a]['bundle'] for a in (OWNER,FOE)]
    s=cold().journeys.create(bundles,prior['battlefield'],{OWNER:{'x':3,'y':6},FOE:{'x':10,'y':6}},
        {OWNER:30,FOE:30})
    jid2=s['journey_id']
    s=cold().journey_act(jid2,s['revision'],OWNER,'wait',{'seconds':1})
    result=cold().journey_start_combat(jid2,s['revision'],{OWNER:'a',FOE:'b'})
    session=cold()._load_session(result['match_id'])
    assert session.mechanical.replay()['status']=='PASS'
    assert not placed.of(session.engine,'trap')


def test_source_site_admission_is_typed_private_and_replayed(tmp_path):
    cold,jid,act=game(tmp_path)
    payload={'id':'bridge-east','name':'East bridge','kind':'bridge',
        'cells':[{'x':x,'y':6} for x in range(3,11)],'known_to':[OWNER]}
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):
        cold().journey_admit(jid,0,OWNER,'construction_site',payload,gm=False,reason='Surveyed bridge')
    assert cold().journey_state(jid)==before
    cold().journey_admit(jid,0,OWNER,'construction_site',payload,gm=True,reason='Recorded site survey: bridge piers and deck')
    assert not cold().journey_state(jid,viewer_id=FOE)['construction_sites']
    assert cold().journeys.replay(jid)['status']=='PASS'
    s=act('prepare_array',{'pattern':'locking_gate','center':{'x':3,'y':6},'site':'bridge-east','damage_type':'force'})
    assert s['actors'][OWNER]['constructed_patterns'][0]['cells']==payload['cells']


@pytest.mark.parametrize('item',['tianxia.mortal.gear.smoke_pellet','item:alchemy.ordinary_smoke_pellet'])
def test_external_ordinary_recipe_needs_real_stock_gm_typed_source_and_replays(tmp_path,item):
    from hashlib import sha256
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate, settle, turn, reload
    from combat import carry
    doc=sheet(['TRAP_BASE_ACTIVATION_TRAP'],cl=5,kit={'starting_kit':{'items':[
        {'item_id':item,'name':'Ordinary smoke pellets','quantity':2},
        {'item_id':'tianxia.mortal.tool.thieves_tools','name':'Thieves’ tools','quantity':1}]}})
    bundles=[compile_character(doc,actor_id=OWNER),compile_character(sheet([],cl=5),actor_id=FOE)]
    service=CombatService(ROOT,tmp_path)
    arena={'display_name':'Recipe map','stable_id':'construction:recipe','width_squares':15,'height_squares':12,
        'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    s=service.journeys.create(bundles,arena,{OWNER:{'x':3,'y':6},FOE:{'x':6,'y':5}},{OWNER:30,FOE:30})
    jid=s['journey_id']
    text='smoke pellets with no combat effect unless a printed rule allows'
    payload={'item_id':item,'nature':'ordinary_consumable','source_text':text,'source_sha256':sha256(text.encode()).hexdigest(),
        'spec':{'name':'Ordinary smoke pellet','fragile':1,'effects':[
            {'type':'physical_payload_fact','text':'An ordinary smoke pellet releases smoke; it has no combat effect without another printed rule.'}]}}
    with pytest.raises(ValueError):
        service.journey_admit(jid,0,OWNER,'ordinary_consumable_definition',payload,gm=False,reason='Printed background equipment')
    s=service.journey_admit(jid,0,OWNER,'ordinary_consumable_definition',payload,gm=True,
        reason='PHB Backgrounds, Shinobi starting equipment: ordinary smoke pellet, no combat effect')
    assert service.journeys.replay(jid)['status']=='PASS'
    assert 'declared_item_specs' not in service.journey_state(jid,viewer_id=FOE)['actors'][OWNER]
    result=service.journey_start_combat(jid,s['revision'],{OWNER:'a',FOE:'b'})
    mid=result['match_id']; table=TabletopService(service,tmp_path)
    turn(table,mid,OWNER)
    settle(table,mid,candidate(service,mid,'Trap form: Activation Trap').candidate_id)
    settle(table,mid,candidate(service,mid,'Set Trap',at=(4,6)).candidate_id)
    turn(table,mid,FOE)
    e=service._load_session(mid).engine
    row=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
             (c.destination.x,c.destination.y)==(4,6))
    hp=e.state.actors[FOE].current_hp
    settle(table,mid,row.candidate_id)
    e=reload(tmp_path,mid)
    assert e.state.actors[FOE].current_hp==hp
    assert any('ordinary smoke pellet releases smoke' in str(v.payload).lower() for v in e.events)
    carried=next(i for i in carry.carrying_of(e,OWNER)['items'] if i['item_id']==item)
    assert carry.remaining_quantity(e,e.state.actors[OWNER],carried)==1


def test_two_real_node_destructions_collapse_prepared_site(tmp_path):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import settle, turn
    cold,jid,act=game(tmp_path,foe_score=30)
    s=act('prepare_array',{'pattern':'locking_gate','center':{'x':4,'y':6},'site':'','damage_type':'force'})
    result=cold().journey_start_combat(jid,s['revision'],{OWNER:'a',FOE:'b'},maximum_rounds=20)
    mid=result['match_id']; service=cold(); table=TabletopService(service,tmp_path)
    e=service._load_session(mid).engine
    z=formations.arrays(e,OWNER)[0]
    nodes=list(formations.record(z)['nodes'])
    for index,oid in enumerate(nodes[:2]):
        for _ in range(12):
            turn(table,mid,FOE)
            e=service._load_session(mid).engine
            obj=e.state.objects[oid]
            if obj.destroyed:
                break
            if not e.state.actors[FOE].action_available:
                settle(table,mid,table.state(mid)['menu']['end_turn'])
                continue
            rows=list(e.legal_candidates())
            attacks=[c for c in rows if c.target_ids==(oid,) and c.metadata.get('object_target')]
            if attacks:
                settle(table,mid,attacks[0].candidate_id)
            else:
                moves=[c for c in rows if c.kind.value=='MOVE' and c.destination]
                if moves:
                    row=min(moves,key=lambda c:(e.grid.distance_ft(c.destination,obj.position),c.movement_cost_ft,c.candidate_id))
                    settle(table,mid,row.candidate_id)
                else:
                    settle(table,mid,table.state(mid)['menu']['end_turn'])
        else:
            raise AssertionError('The native attacker could not destroy the Node in the bounded fight')
        e=cold()._load_session(mid).engine
        assert e.state.objects[oid].destroyed
        assert bool(formations.arrays(e,OWNER))==(index==0)
    session=cold()._load_session(mid)
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'


def test_nourishing_native_benefit_survives_new_encounter_until_actual_short_rest(tmp_path):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate, settle, turn
    doc=sheet(['FORMATIONS_BASE_SET_ARRAY'],cl=5,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','name':'Chalk','quantity':1}]}})
    doc['spheres_and_talents']['formation_patterns']=['nourishing_cycle']
    service=CombatService(ROOT,tmp_path)
    bundles=[compile_character(doc,actor_id=OWNER),compile_character(sheet([],cl=5),actor_id=FOE)]
    arena={'display_name':'Nourishing Cycle map','stable_id':'nourishing-continuity','width_squares':15,'height_squares':12,
           'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    state=service.journeys.create(bundles,arena,{OWNER:{'x':3,'y':6},FOE:{'x':10,'y':6}},{OWNER:30,FOE:30})
    jid=state['journey_id']
    state=service.journey_act(jid,state['revision'],OWNER,'prepare_array',
        {'pattern':'nourishing_cycle','center':{'x':3,'y':6},'site':'','damage_type':'force'})
    def enter():
        cold=CombatService(ROOT,tmp_path)
        state=cold.journey_state(jid)
        result=cold.journey_start_combat(jid,state['revision'],{OWNER:'a',FOE:'b'},maximum_rounds=1)
        return cold,TabletopService(cold,tmp_path),result['match_id']
    def finish(combat,table,mid):
        for _ in range(4):
            session=combat._load_session(mid)
            if session.engine.state.terminal_result is not None:break
            settle(table,mid,table.state(mid)['menu']['end_turn'])
        session=CombatService(ROOT,tmp_path)._load_session(mid)
        assert session.engine.state.terminal_result is not None
        assert session.mechanical.replay()['status']=='PASS'
        cold=CombatService(ROOT,tmp_path)
        return cold.journey_resume(jid,cold.journey_state(jid)['revision'])
    combat,table,mid=enter(); turn(table,mid,OWNER)
    settle(table,mid,candidate(combat,mid,'Pulse: Nourishing Cycle',target=OWNER).candidate_id)
    state=finish(combat,table,mid)
    assert state['actors'][OWNER]['formation_nourishing_rest_blocked']==1
    combat,table,mid=enter(); turn(table,mid,OWNER)
    e=combat._load_session(mid).engine
    assert not any(c.target_ids==(OWNER,) and e.action_catalog.get(c.source_definition_id) and
        e.action_catalog[c.source_definition_id].display_name=='Pulse: Nourishing Cycle' for c in e.legal_candidates())
    state=finish(combat,table,mid)
    before=state['seconds']; resources=dict(state['actors'][OWNER]['resources'])
    state=CombatService(ROOT,tmp_path).journey_act(jid,state['revision'],OWNER,'short_rest',{})
    assert state['seconds']==before+3600
    assert state['actors'][OWNER]['resources']==resources
    assert not state['actors'][OWNER].get('formation_nourishing_rest_blocked')
    combat,table,mid=enter(); turn(table,mid,OWNER)
    assert candidate(combat,mid,'Pulse: Nourishing Cycle',target=OWNER)
    assert CombatService(ROOT,tmp_path)._load_session(mid).mechanical.replay()['status']=='PASS'


def test_outside_combat_trap_contact_runs_real_allied_table_scene(tmp_path):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import settle,turn
    cold,jid,act=game(tmp_path)
    state=act('construct_trap',{'form':'tripwire','cells':[{'x':4,'y':6}],'aim':'e'})
    before=cold().journey_state(jid,viewer_id=OWNER)
    path=[{'x':x,'y':6} for x in range(9,3,-1)]
    with pytest.raises(ValueError,match='table scene'):
        act('move',{'path':path},aid=FOE)
    assert cold().journey_state(jid,viewer_id=OWNER)==before
    assert any(row['kind']=='open_scene' for row in cold().journey_menu(jid,OWNER)['options'])
    result=cold().journey_act(jid,state['revision'],OWNER,'open_scene',{'teams':{OWNER:'party',FOE:'party'}})
    mid=result['match_id'];service=cold();table=TabletopService(service,tmp_path)
    assert service._load_session(mid).engine.state.terminal_result is None
    turn(table,mid,FOE)
    e=service._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==(4,6))
    settle(table,mid,move.candidate_id)
    session=cold()._load_session(mid)
    assert any(v.event_type=='SAVE_ROLLED' and v.actor_id==FOE for v in session.engine.events)
    assert placed.of(session.engine,'trap')
    assert session.mechanical.replay()['status']=='PASS'


def test_single_actor_array_pulse_uses_native_scene_and_source_time(tmp_path):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate,settle
    doc=sheet(['FORMATIONS_BASE_SET_ARRAY'],cl=5,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','name':'Chalk','quantity':1}]}})
    doc['spheres_and_talents']['formation_patterns']=['nourishing_cycle']
    service=CombatService(ROOT,tmp_path)
    arena={'display_name':'Solo Array map','stable_id':'single-actor-native-scene','width_squares':12,'height_squares':12,
           'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    state=service.journeys.create([compile_character(doc,actor_id=OWNER)],arena,{OWNER:{'x':3,'y':6}},{OWNER:30})
    jid=state['journey_id']
    state=service.journey_act(jid,state['revision'],OWNER,'prepare_array',
        {'pattern':'nourishing_cycle','center':{'x':3,'y':6},'site':'','damage_type':'force'})
    with pytest.raises(ValueError):
        service.journey_start_combat(jid,state['revision'],{OWNER:'party'})
    result=service.journey_start_scene(jid,state['revision'],{OWNER:'party'})
    mid=result['match_id'];table=TabletopService(service,tmp_path)
    session=service._load_session(mid)
    assert session.engine.state.terminal_result is None
    assert session.engine.state.current_actor_id==OWNER
    settle(table,mid,candidate(service,mid,'Pulse: Nourishing Cycle',target=OWNER).candidate_id)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.engine.state.terminal_result is not None
    assert session.mechanical.replay()['status']=='PASS'
    state=service.journey_resume(jid,service.journey_state(jid)['revision'])
    assert state['actors'][OWNER]['construction_clock_num']==606
    assert state['actors'][OWNER]['formation_nourishing_rest_blocked']==1


def test_native_source_admission_and_scene_are_token_protected_and_private(tmp_path):
    import asyncio
    import httpx
    from app.api import create_app
    from app.core import Settings
    cold,jid,act=game(tmp_path)
    app=create_app(Settings.from_env(ROOT,tmp_path))
    app.state.agent_seats.background=False
    payload={'id':'http-gatehouse','name':'West gatehouse','kind':'gatehouse',
             'cells':[{'x':x,'y':6} for x in range(3,7)],'known_to':[OWNER]}
    url=f'/api/combat/journeys/{jid}'
    # GM facts enter through the one documented entry point, CombatService
    # .journey_admit: journey.Journeys.admit records that this local API has no GM
    # sign-in and its HTTP surface deliberately does not expose admission. The gate
    # is the strict GM flag, and the private fact is filtered per viewer on the
    # real HTTP read.
    service=cold()
    for flag in ({'gm':False},{'gm':'true'}):
        with pytest.raises(ValueError, match='Only the GM'):
            service.journey_admit(jid,0,OWNER,'construction_site',payload,
                reason='GM survey of the gatehouse walls and floor',**flag)
    with pytest.raises(ValueError, match='Give the source'):
        service.journey_admit(jid,0,OWNER,'construction_site',payload,gm=True,reason='')
    admitted=service.journey_admit(jid,0,OWNER,'construction_site',payload,gm=True,
        reason='GM survey of the gatehouse walls and floor')
    assert admitted['revision']==1 and 'http-gatehouse' in admitted['construction_sites']
    assert service.journey_state(jid,FOE)['construction_sites']=={}
    scene_body={'revision':admitted['revision'],'actor_id':OWNER,'kind':'open_scene',
                'payload':{'teams':{OWNER:'party',FOE:'party'}}}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            unauth=await client.post(url+'/act',json=scene_body)
            assert unauth.status_code==403, 'the local session token guards every journey write'
            token=(await client.get('/api/session')).json()['token']
            headers={'x-foundry-token':token}
            foreign=(await client.get(url,params={'viewer_id':FOE},headers=headers)).json()
            assert foreign['construction_sites']=={}
            owner=(await client.get(url,params={'viewer_id':OWNER},headers=headers)).json()
            assert 'http-gatehouse' in owner['construction_sites']
            scene=await client.post(url+'/act',headers=headers,json={
                'revision':owner['revision'],'actor_id':OWNER,'kind':'open_scene',
                'payload':{'teams':{OWNER:'party',FOE:'party'}}})
            assert scene.status_code==200,scene.text
            return scene.json()['match_id']
    mid=asyncio.run(exercise())
    session=cold()._load_session(mid)
    assert session.engine.state.rules['scene_window']=='elapsed_rounds_v1'
    assert session.engine.state.terminal_result is None
    assert session.mechanical.replay()['status']=='PASS'


def test_prepared_mode_uses_existing_owned_time_and_geometry_modifiers(tmp_path):
    doc=sheet(['FORMATIONS_BASE_SET_ARRAY','tianxia.talent.formations.rapid_array',
        'tianxia.talent.formations.expanded_geometry'],cl=5,kit={'starting_kit':{'items':[
            {'item_id':'tianxia.mortal.gear.chalk','name':'Chalk','quantity':1}]}})
    doc['spheres_and_talents']['formation_patterns']=['locking_gate']
    service=CombatService(ROOT,tmp_path)
    arena={'display_name':'Prepared Array map','stable_id':'prepared-owned-modifiers','width_squares':20,'height_squares':15,
           'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    state=service.journeys.create([compile_character(doc,actor_id=OWNER)],arena,{OWNER:{'x':3,'y':6}},{OWNER:30})
    jid=state['journey_id']
    state=service.journey_act(jid,state['revision'],OWNER,'prepare_array',
        {'pattern':'locking_gate','center':{'x':4,'y':6},'site':'','damage_type':'force'})
    assert state['seconds']==60
    record=state['actors'][OWNER]['constructed_patterns'][0]
    from combat.gate2_runtime_models import Position
    assert Position(x=10,y=6) in [Position.model_validate(c) for c in record['cells']]
    assert record['expires']==28860
    assert service.journeys.replay(jid)['status']=='PASS'
    result=service.journey_start_scene(jid,state['revision'],{OWNER:'party'})
    session=CombatService(ROOT,tmp_path)._load_session(result['match_id'])
    assert session.mechanical.replay()['status']=='PASS'
    z=formations.arrays(session.engine,OWNER)[0]
    assert any((c.x,c.y,c.z)==(10,6,0) for c in z.affected_cells)


def test_pulse_controller_range_is_native_120_feet_even_with_bound_array_origin(tmp_path):
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import candidate,settle,turn
    doc=sheet(['FORMATIONS_BASE_SET_ARRAY'],cl=5,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.gear.chalk','name':'Chalk','quantity':1}]}})
    doc['spheres_and_talents']['formation_patterns']=['nourishing_cycle']
    service=CombatService(ROOT,tmp_path)
    arena={'display_name':'Array Pulse range map','stable_id':'pulse-controller-range','width_squares':40,'height_squares':12,
           'square_size_ft':5,'starting_positions':{},'terrain_regions':[]}
    state=service.journeys.create([compile_character(doc,actor_id=OWNER),
        compile_character(sheet([],cl=5),actor_id=FOE)],arena,
        {OWNER:{'x':3,'y':6},FOE:{'x':3,'y':7}},{OWNER:30,FOE:30})
    jid=state['journey_id']
    state=service.journey_act(jid,state['revision'],OWNER,'prepare_array',
        {'pattern':'nourishing_cycle','center':{'x':3,'y':6},'site':'','damage_type':'force'})
    result=service.journey_start_scene(jid,state['revision'],{OWNER:'party',FOE:'party'},maximum_rounds=6)
    mid=result['match_id'];table=TabletopService(service,tmp_path)
    for x in (9,15,21,27):
        turn(table,mid,OWNER)
        e=service._load_session(mid).engine
        move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
                  (c.destination.x,c.destination.y)==(x,6))
        settle(table,mid,move.candidate_id)
        session=CombatService(ROOT,tmp_path)._load_session(mid)
        assert session.mechanical.replay()['status']=='PASS'
        if x<27:settle(table,mid,table.state(mid)['menu']['end_turn'])
    assert candidate(service,mid,'Pulse: Nourishing Cycle',target=FOE)
    settle(table,mid,table.state(mid)['menu']['end_turn'])
    turn(table,mid,OWNER)
    e=service._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==(28,6))
    settle(table,mid,move.candidate_id)
    session=CombatService(ROOT,tmp_path)._load_session(mid);e=session.engine
    z=formations.arrays(e,OWNER)[0]
    assert e.grid.distance_ft(e.state.actors[OWNER].position,z.center)==125
    assert formations.eye_perceived(e,e.state.actors[OWNER],z)
    assert not any(c.target_ids==(FOE,) and e.action_catalog.get(c.source_definition_id) and
        e.action_catalog[c.source_definition_id].display_name=='Pulse: Nourishing Cycle' for c in e.legal_candidates())
    assert session.mechanical.replay()['status']=='PASS'
