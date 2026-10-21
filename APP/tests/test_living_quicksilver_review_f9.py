"""Review F9 regression diagnostics and native acceptance."""
import pytest
from types import SimpleNamespace
from combat.ext.mgr_reserve_living_quicksilver_immortal_embryo_living_mercury_body import patterns_of
from combat.qi_sensing import ray_clear
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from tests.test_living_quicksilver_native import A, B, QI, MASS, FAMILY, FEATURES, setup, combat, engine


def test_reaction_denied_is_a_recordable_rider_not_an_unrecognized_structure():
    ctx=SimpleNamespace(typed={'source':'test:hostile.qi','effects':[{'type':'save',
        'on_success':[{'type':'reaction_denied','applies_to':'target','duration':'until_start_of_your_next_turn'}]}]},
        source='test:activation',numbers={'cl':10,'save_dc':16},
        action=SimpleNamespace(parameters={}))
    pattern,=patterns_of(ctx)
    assert pattern['kind']=='rider' and pattern['value']['type']=='reaction_denied'
    assert pattern['value']['duration']=='until_start_of_your_next_turn'


def test_recorded_reaction_denial_is_expressed_through_native_damage_and_reload(tmp_path,monkeypatch):
    from tests.test_living_quicksilver_native import native_qi_delivery, candidate, settle, turn
    from combat.typed_executor import condition_rules
    C='actor:factory.witness'
    native_qi_delivery(monkeypatch,'Review visible reaction rider',[
        {'type':'damage','flat':1,'damage_types':['FIRE'],'applies_to':'target'},
        {'type':'reaction_denied','applies_to':'self','duration':'until_start_of_your_next_turn'}])
    native_qi_delivery(monkeypatch,'Review expression',[
        {'type':'damage','flat':1,'damage_types':['FIRE'],'applies_to':'target'}],owner=A)
    cold,jid,act,world=setup(tmp_path,monkeypatch,10,third=True,
        positions={A:{'x':3,'y':3},B:{'x':5,'y':3},C:{'x':6,'y':4}})
    table,mid=combat(cold,jid,tmp_path);turn(table,mid,B)
    hit=candidate(cold(),mid,'Review visible reaction rider',target=A)
    settle(table,mid,hit.candidate_id,picks={'choice:needle.quicksilver.record_pattern':'1'})
    e=engine(cold,mid)
    ledger=next(c.data for c in e.state.actors[A].conditions.values()
        if c.condition_id=='condition:typed.living_quicksilver_ledger')
    assert ledger['pattern']['kind']=='rider' and ledger['pattern']['value']['type']=='reaction_denied'
    assert e.state.actors[A].resources[QI]==27
    turn(table,mid,A)
    hit=candidate(cold(),mid,'Review expression',target=C)
    settle(table,mid,hit.candidate_id,picks={
        'choice:needle.quicksilver.express_pattern':QI,'choice:needle.quicksilver.conversion':None})
    e=engine(cold,mid)
    assert any(rule.get('no_reactions') for rule in condition_rules(e.state.actors[C]))
    denial=next(c for c in e.state.actors[C].conditions.values() if c.condition_id=='condition:typed.reaction_denied')
    assert denial.expires_on=='START_OF_SOURCE_NEXT_TURN' and denial.source_actor_id==A
    assert e.state.actors[A].resources[QI]==24
    assert engine(cold,mid).state.model_dump(mode='json')==e.state.model_dump(mode='json')


@pytest.mark.parametrize('material,thickness,flags,expected',[
    ('stone',11999,{},True),('stone',12000,{},False),
    ('metal',999,{},True),('metal',1000,{},False),
    ('wood',35999,{},True),('packed earth',36000,{},False),
    ('lead',1,{},False),('wood',1000,{'sealed_formation':True},False),
    ('glass',1000,{'blocks_qi_perception':True},False),
])
def test_qi_rays_use_printed_material_thickness_and_seals(material,thickness,flags,expected):
    region={'region_id':'wall','terrain_type':'BLOCKED','cells':[{'x':2,'y':1}],
        'movement_cost':1,'height_ft':5,'material':material,'thickness_mils':thickness,**flags}
    document={'width_squares':5,'height_squares':3,'square_size_ft':5,'starting_positions':{},'terrain_regions':[region]}
    grid=SquareGrid(document)
    e=SimpleNamespace(grid=grid,battlefield_document=document,state=SimpleNamespace(objects={},zones={}))
    start,end=Position(x=1,y=1),Position(x=3,y=1)
    assert not grid.line_of_physical_transmission(start,end)
    assert ray_clear(e,start,end) is expected


def test_outside_combat_body_commands_keep_identity_costs_and_native_genesis(tmp_path,monkeypatch):
    cold,jid,act,world=setup(tmp_path,monkeypatch,6)
    def options():return cold().journey_menu(jid,A)['options']
    create=next(o for o in options() if o['kind']=='quicksilver_create_body'
        and Position.model_validate(o['payload']['position'])==Position(x=3,y=4) and o['payload']['resource']==QI)
    state=act(create['kind'],create['payload'])
    body=next(o for o in state['runtime_objects'].values() if o['component'].get('quicksilver_body'))
    assert body['current_hp']==12 and body['ac']==14 and state['actors'][A]['resources'][QI]==28
    assert not any(o['kind']=='quicksilver_create_body' for o in options()), 'CL6 capacity is still one.'
    assert not any(o['kind'].startswith('quicksilver_') and o['kind']!='quicksilver_short_rest'
        for o in cold().journey_menu(jid,B)['options'])
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):
        act('quicksilver_rejoin',{'body_id':body['object_id'],'mode':'mass'},who=B)
    assert cold().journey_state(jid)==before
    move=next(o for o in options() if o['kind']=='quicksilver_move_body'
        and Position.model_validate(o['payload']['destination'])==Position(x=4,y=4))
    state=act(move['kind'],move['payload'])
    assert Position.model_validate(state['runtime_objects'][body['object_id']]['position'])==Position(x=4,y=4)
    assert state['actors'][A]['resources'][QI]==28
    rejoin=next(o for o in options() if o['kind']=='quicksilver_rejoin' and o['payload']['mode']=='mass')
    state=act(rejoin['kind'],rejoin['payload'])
    assert state['runtime_objects'][body['object_id']]['destroyed']
    assert state['actors'][A]['resources'][MASS]==3 and state['seconds']==18
    table,mid=combat(cold,jid,tmp_path)
    assert not any(o.component.get('quicksilver_body') for o in engine(cold,mid).state.objects.values()), 'Rejoin must not revive an ended Body on combat entry.'



@pytest.mark.parametrize('blocked',['thin','map_seal','declared_seal'])
def test_distributed_qi_sensing_crosses_only_printed_thin_barriers_after_reload(tmp_path,monkeypatch,blocked):
    from tests.test_living_quicksilver_native import use, candidate, settle, turn
    from combat.senses import perception
    arena={'display_name':'Thin wood screen','stable_id':'battlefield:qi-screen','width_squares':12,
        'height_squares':12,'square_size_ft':5,'starting_positions':{},'terrain_regions':[{
            'region_id':'wood-screen','terrain_type':'BLOCKED','cells':[{'x':5,'y':y} for y in range(12)],
            'movement_cost':1,'material':'wood','thickness_mils':1000,'sealed_formation':blocked=='map_seal'}]}
    cold,jid,act,world=setup(tmp_path,monkeypatch,14,arena_override=arena)
    if blocked=='declared_seal':
        world('barrier_authority','sealed-screen',{
            'path':[{'x':4,'y':4},{'x':5,'y':4},{'x':6,'y':4}],'width_inches':1,
            'region_ids':['wood-screen'],'object_ids':[],'items':{},
            'airtight':0,'liquid_tight':0,'force':0,'artifact_restraint':0,'sealed_formation':1})
    world('source_access','other-inheritance',{'variant':FAMILY,'route':'direct',
        'source_rule':'The opponent also inherits this progression.'},subject=B,readers=[B])
    state=cold().journey_state(jid)
    cold().journey_acquire_source(jid,state['revision'],B,FAMILY,{'access_scope':'other-inheritance'})
    table,mid=combat(cold,jid,tmp_path)
    e=use(cold,table,mid,'Create Quicksilver Body: 2 Qi')
    body=next(o for o in e.state.objects.values() if o.owner_id==A and o.component.get('quicksilver_body'))
    turn(table,mid,B)
    create=candidate(cold(),mid,'Create Quicksilver Body: 2 Qi',at=(8,4))
    settle(table,mid,create.candidate_id)
    e=engine(cold,mid)
    target=next(o for o in e.state.objects.values() if o.owner_id==B and o.component.get('quicksilver_body'))
    assert not e.grid.line_of_physical_transmission(body.position,target.position)
    before=e.state.model_dump(mode='json')
    facts=perception(e,e.state.actors[A]).get('information',[])
    sensed=[f for f in facts if f['kind']=='qi_presence' and f['details']=={
        'origin_id':body.object_id,'direction':'east','presence':1}]
    assert bool(sensed) is (blocked=='thin')
    assert all('hp' not in f['details'] and 'source_actor_id' not in f['details'] for f in sensed)
    assert e.state.model_dump(mode='json')==before
    assert engine(cold,mid).state.model_dump(mode='json')==before


def test_native_form_expiry_lands_perfected_air_bodies_and_removes_their_flight(tmp_path,monkeypatch):
    from tests.test_living_quicksilver_native import use, turn, settle
    from combat.ext.mgr_reserve_living_quicksilver_immortal_embryo_living_mercury_body import transformed
    cold,jid,act,world=setup(tmp_path,monkeypatch,18)
    table,mid=combat(cold,jid,tmp_path)
    use(cold,table,mid,'Undying Prima Materia')
    turn(table,mid,B)
    settle(table,mid,table.state(mid)['menu']['end_turn'],picks={
        'choice:needle.quicksilver.free_body':'3,4,2','choice:needle.quicksilver.configuration':'mirror'})
    e=engine(cold,mid)
    first=next(o for o in e.state.objects.values() if o.component.get('quicksilver_body'))
    assert first.position.z==2 and first.component['hover']==1
    for _ in range(22):
        if not transformed(engine(cold,mid).state.actors[A]):break
        settle(table,mid,table.state(mid)['menu']['end_turn'],picks={'choice:needle.quicksilver.configuration':'mirror'})
    e=engine(cold,mid)
    assert not transformed(e.state.actors[A])
    body=e.state.objects[first.object_id]
    assert body.position.z==0 and body.component['hover']==0 and body.component['fly_speed_ft']==0
    assert body.maximum_hp==36 and body.current_hp<=36
    assert any(event.event_type=='OBJECT_UPDATED' and first.object_id in event.target_ids
        and event.payload['object']['position'].get('z',0)==0 for event in e.events)
    assert engine(cold,mid).state.model_dump(mode='json')==e.state.model_dump(mode='json')


def test_cramped_arena_cold_reload_preview_and_gate3_recovery_keep_actual_roster(tmp_path,monkeypatch):
    from tests.h1_support import ROOT
    from combat.gate3_storage import Gate3Persistence
    from combat.gate5_service import CombatService
    from tests.test_living_quicksilver_native import no_body_space_arena
    arena=no_body_space_arena()
    cold,jid,act,world=setup(tmp_path,monkeypatch,3,arena_override=arena,
        positions={A:{'x':0,'y':0},B:{'x':1,'y':0}})
    table,mid=combat(cold,jid,tmp_path)
    loaded=engine(cold,mid)
    clone=CombatService._clone_engine(ROOT,loaded)
    assert set(clone.state.actors)=={A,B}
    assert clone.state.model_dump(mode='json')==loaded.state.model_dump(mode='json')
    recovered=Gate3Persistence(ROOT,tmp_path).load_match(mid)
    assert recovered.engine.state.model_dump(mode='json')==loaded.state.model_dump(mode='json')
    assert table.state(mid)['menu']['actor_id']==A
    assert engine(cold,mid).state.model_dump(mode='json')==loaded.state.model_dump(mode='json')
