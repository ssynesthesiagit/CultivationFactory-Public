"""Actual source admission -> narrow movement menu -> native commit/cold replay."""
from copy import deepcopy
import pytest
from combat.gate2_runtime_models import Position
from combat.physical_passages import records,permitted
from tests.test_living_quicksilver_native import (
    A,B,setup,combat,engine,use,candidate,settle,
)

PATH=[{'x':3,'y':2},{'x':4,'y':2},{'x':5,'y':2}]
FLAGS=('airtight','liquid_tight','force','sealed_formation','artifact_restraint')


def scene():
    return {'display_name':'One-inch culvert','stable_id':'battlefield:culvert','width_squares':8,
        'height_squares':6,'square_size_ft':5,'starting_positions':{},'terrain_regions':[{
            'region_id':'culvert-wall','terrain_type':'BLOCKED','movement_cost':1,'height_ft':10,
            'material':'stone','cells':[{'x':4,'y':y} for y in range(6)]}]}


def passage(**changes):
    return {**{k:0 for k in FLAGS},'path':deepcopy(PATH),'width_inches':1,
        'region_ids':['culvert-wall'],'object_ids':[],'items':{},**changes}


def crossing(e):
    path=tuple(Position.model_validate(p) for p in PATH)
    return [c for c in e.legal_candidates() if c.kind=='MOVE' and c.canonical_path==path]


@pytest.mark.parametrize('perfect,elevated',[(False,False),(True,False),(False,True)])
def test_native_liquefaction_crosses_one_inch_with_only_printed_movement_cost(tmp_path,monkeypatch,perfect,elevated):
    arena=scene();path=deepcopy(PATH)
    if elevated:
        path=[{**p,'z':1} for p in path]
        arena['terrain_regions'].append({'region_id':'raised-floor','terrain_type':'BLOCKED','movement_cost':1,
            'height_ft':5,'material':'stone','cells':[{'x':x,'y':y} for x in range(8) for y in range(6)]})
    cold,jid,act,world=setup(tmp_path,monkeypatch,18 if perfect else 3,arena_override=scene(),
        positions={A:PATH[0],B:{'x':7,'y':4}})
    world('barrier_authority','culvert',passage(path=path))
    if elevated:
        # Journey travel intentionally starts on the ground. Use the ordinary
        # Factory combat-setup boundary to seat these genuinely acquired
        # characters on the authored upper platform, without moving a live actor.
        from combat.tabletop_service import TabletopService
        from tests.test_living_quicksilver_native import turn
        state=cold().journey_state(jid)
        bundles=[state['actors'][aid]['bundle'] for aid in (A,B)]
        mid=cold()._finish_factory_match(bundles,[A,B],{A:'team:a',B:'team:b'},
            {A:path[0],B:{'x':7,'y':4,'z':1}},arena,[A],[B],
            control_modes={A:'MANUAL',B:'MANUAL'},match_seed='UPPER-CULVERT',
            display_name='Upper culvert',maximum_rounds=15)['match_id']
        table=TabletopService(cold(),tmp_path);turn(table,mid,A)
    else:table,mid=combat(cold,jid,tmp_path)
    if perfect:use(cold,table,mid,'Undying Prima Materia')
    before=engine(cold,mid)
    assert not before.grid.volume_step_legal(Position(**path[0]),Position(**path[1]))
    assert records(before,before.state.actors[B])==[]
    options=[c for c in before.legal_candidates() if c.kind=='MOVE' and c.canonical_path==tuple(Position(**p) for p in path)]
    assert options
    chosen=options[0]
    assert chosen.movement_cost_ft==(10 if perfect else 20)
    assert chosen.metadata.get('explicit_movement_path')
    settle(table,mid,chosen.candidate_id)
    after=engine(cold,mid)
    assert after.state.actors[A].position==Position(**path[-1])
    movement=next(e for e in reversed(after.events) if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==A)
    assert movement.payload['cost_ft']==(10 if perfect else 20)
    assert tuple(Position.model_validate(p) for p in movement.payload['path'])==tuple(Position(**p) for p in path)
    assert not movement.payload.get('teleport')
    assert after.state.actors[A].resources==before.state.actors[A].resources
    assert engine(cold,mid).state.model_dump(mode='json')==after.state.model_dump(mode='json')


@pytest.mark.parametrize('barrier',[*FLAGS,'too_narrow','expired','nonowner','native_seal','native_force'])
def test_native_passage_exclusions_do_not_grant_wall_movement(tmp_path,monkeypatch,barrier):
    arena=scene()
    if barrier=='native_seal':arena['terrain_regions'][0]['sealed_formation']=1
    if barrier=='native_force':arena['terrain_regions'][0]['material']='force'
    cold,jid,act,world=setup(tmp_path,monkeypatch,3,acquire=barrier!='nonowner',arena_override=arena,
        positions={A:PATH[0],B:{'x':7,'y':4}})
    value=passage(**({barrier:1} if barrier in FLAGS else {}))
    if barrier=='too_narrow':value['width_inches']=0
    world('barrier_authority','culvert',value)
    if barrier=='expired':act('wait',{'seconds':2592000})
    table,mid=combat(cold,jid,tmp_path)
    e=engine(cold,mid)
    assert not crossing(e)
    assert not permitted(e,e.state.actors[A],Position(**PATH[0]),Position(**PATH[1]),'walk',observed=True)
    assert engine(cold,mid).state.actors[A].position==Position(**PATH[0])


@pytest.mark.parametrize('transforms',[0,1])
def test_native_carried_item_clearance_is_not_inferred_from_liquid_body(tmp_path,monkeypatch,transforms):
    cold,jid,act,world=setup(tmp_path,monkeypatch,3,items=['tianxia.mortal.weapon.qiang'],arena_override=scene(),
        positions={A:PATH[0],B:{'x':7,'y':4}})
    state=cold().journey_state(jid)
    item=state['actors'][A]['bundle']['carrying']['items'][0]
    world('barrier_authority','culvert',passage(items={
        item['key']:{'minimum_width_inches':2,'transforms':transforms}}))
    table,mid=combat(cold,jid,tmp_path)
    e=engine(cold,mid)
    assert bool(crossing(e)) is bool(transforms)


def test_interrupted_transit_keeps_native_exit_quotes_at_the_real_step_cost(tmp_path,monkeypatch):
    from tests.test_living_quicksilver_review_f6 import add_hook
    def halt(e,mover,previous,nxt,intent):
        if mover.entity_id==A and nxt==Position(**PATH[1]):
            return {'stop':True,'source_id':'test:passage.stop','label':'Pause inside the actual narrow channel'}
    add_hook(monkeypatch,'movement_step',halt)
    cold,jid,act,world=setup(tmp_path,monkeypatch,3,arena_override=scene(),
        positions={A:PATH[0],B:{'x':7,'y':4}})
    world('barrier_authority','culvert',passage())
    table,mid=combat(cold,jid,tmp_path)
    e=engine(cold,mid)
    settle(table,mid,crossing(e)[0].candidate_id)
    e=engine(cold,mid)
    assert e.state.actors[A].position==Position(**PATH[1])
    exits=[c for c in e.legal_candidates() if c.kind=='MOVE'
        and c.canonical_path==(Position(**PATH[1]),Position(**PATH[-1]))]
    assert exits and all(c.movement_cost_ft==10 for c in exits)
    settle(table,mid,exits[0].candidate_id)
    e=engine(cold,mid)
    assert e.state.actors[A].position==Position(**PATH[-1])
    assert e.state.actors[A].movement_remaining_ft==10


def test_destroyed_named_barrier_no_longer_adds_a_squeeze_price_to_open_ground(tmp_path,monkeypatch):
    from tests.test_living_quicksilver_review_f6 import add_hook
    from combat.gate2_runtime_models import ActionDefinition
    from combat.ext.objects import object_id
    arena=scene()
    arena['terrain_regions'][0]['cells']=[c for c in arena['terrain_regions'][0]['cells'] if c['y']!=2]
    door={'id':7,'kind':'door','x':4,'y':2,'material':'wood','door_open':False}
    arena['map_objects']=[door]
    oid=object_id(door)
    def actions(info):
        if info['actor_id']!=A:return None
        return [ActionDefinition(source_definition_id='test:passage.break_door',display_name='Break the test door',
            owner_id=A,economy='ACTION',resolution_kind='TYPED',target_kind='OBJECT',range_ft=30,
            parameters={'typed':{'source':'test:passage.break_door','numbers':dict(info['numbers']),
                'effects':[{'type':'object_damage','flat':500,'damage_types':['FORCE']}],
                'duration':{'kind':'instant'}}})]
    add_hook(monkeypatch,'compile_actions',actions)
    cold,jid,act,world=setup(tmp_path,monkeypatch,3,arena_override=arena,
        positions={A:PATH[0],B:{'x':7,'y':4}})
    world('barrier_authority','door-gap',passage(region_ids=[],object_ids=[oid]))
    table,mid=combat(cold,jid,tmp_path)
    e=engine(cold,mid)
    assert crossing(e) and all(c.movement_cost_ft==20 for c in crossing(e))
    hit=candidate(cold(),mid,'Break the test door',target=oid)
    settle(table,mid,hit.candidate_id)
    e=engine(cold,mid)
    assert e.state.objects[oid].destroyed
    assert crossing(e) and all(c.movement_cost_ft==10 for c in crossing(e))
    settle(table,mid,crossing(e)[0].candidate_id)
    assert engine(cold,mid).state.actors[A].position==Position(**PATH[-1])


@pytest.mark.parametrize('invalid',['unknown','unbound'])
def test_invalid_source_passage_is_atomic_and_cannot_invent_barrier_ids(tmp_path,monkeypatch,invalid):
    cold,jid,act,world=setup(tmp_path,monkeypatch,3,arena_override=scene(),
        positions={A:PATH[0],B:{'x':7,'y':4}})
    before=cold().journey_state(jid)
    with pytest.raises(ValueError):
        world('barrier_authority','invented',passage(region_ids=['unmapped-wall']) if invalid=='unknown'
            else passage(path=[{'x':3,'y':1},{'x':3,'y':2},{'x':3,'y':3}]))
    assert cold().journey_state(jid)==before
