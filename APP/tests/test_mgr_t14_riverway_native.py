"""Native acquired Riverway progression, table settlement and cold mechanical replay."""
from copy import deepcopy
import pytest
from app.core import Database, Settings
from non_sphere_authority import NonSphereAuthorityService
from combat.factory_compiler import compile_character
from combat.ext import placed
from combat.ext.riverway import PASSAGE,FERRY,MOON,KNOWS,FIELD,GATES,FIELD_TAG
from tests.h1_support import ROOT,sheet
from tests.ns1r_evidence_helpers import install_authority_test_pack,ap_award
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import OWNER,ALLY,FOE,fixture,candidate as native_candidate,reload,settle,turn

QI='tianxia.path.qi_cultivation'
SUB='tianxia.subpath.qi.riverway_cultivator'


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    settings=Settings.from_env(ROOT,tmp_path_factory.mktemp('riverway-acquisition'))
    settings.ensure_dirs();db=Database(settings);db.migrate()
    service=NonSphereAuthorityService(db)
    install_authority_test_pack(db,service)
    cache={}
    def get(cl):
        if cl not in cache:
            pid='riverway-native-'+str(cl)
            insert_project(db,pid,cl)
            service.initialize_for_project(pid,target_cl=cl,path_ids=[QI],method_id='METHOD-001')
            service.allocate_advancement(pid,{QI:cl-1},evidence_id=ap_award(db,service,pid,'METHOD-001',cl,cl-1),idempotency_key=pid+'-advance')
            service.select_subpath(pid,QI,SUB)
            state=NonSphereAuthorityService(db).get_state(pid)
            doc=sheet([],cl=cl,name='River guide')
            doc['identity']['proficiency_bonus']=2+(cl-1)//4
            doc['ability_scores_and_statistics']['technique_save_dc']=10+doc['identity']['proficiency_bonus']
            doc['path_and_subpath']={'paths':state['paths']}
            doc['ability_scores_and_statistics']['primary_resource']['maximum']=100
            cache[cl]=doc
        return deepcopy(cache[cl])
    return get


def game(tmp_path,acquired,cl=18,**kw):
    doc=acquired(cl)
    owner=compile_character(doc,actor_id=OWNER,reaction_plan={'ask':True})
    if 'battlefield' not in kw:
        from combat.tabletop import TabletopMapStore,to_battlefield
        maps=TabletopMapStore(tmp_path/'maps')
        maps.save({'map_id':'native-riverway','display_name':'Riverway crossing','width_squares':20,'height_squares':14})
        kw['battlefield']=to_battlefield(maps.get('native-riverway'))
    return fixture(tmp_path,[],cl=cl,owner_bundle=owner,seed='RIVERWAY-NATIVE',named=True,**kw)


def candidate(combat,mid,name,*,target=None,at=None,remote=None):
    """This fixture's two-coordinate declarations mean a ground-level cell."""
    if at is None:
        return native_candidate(combat,mid,name,target=target,remote=remote)
    engine=combat._load_session(mid).engine
    rows=[c for c in engine.legal_candidates()
          if getattr(engine.action_catalog.get(c.source_definition_id),'display_name',None)==name
          and c.destination and (c.destination.x,c.destination.y,c.destination.z)==(*at,0)
          and (target is None or c.target_ids==(target,))
          and (remote is None or bool(c.metadata.get('effect_origin'))==remote)]
    assert rows,name
    return rows[0]


def passage(combat,table,mid,*,greater=False):
    choices={'choice:needle.flowing_passage_allies':[OWNER,ALLY],
             'choice:riverway.greater_allies':[ALLY]}
    for n in range(1,12 if greater else 6):
        choices['choice:needle.flowing_passage_cell.'+str(n)]=[f'cell:{3+n},6']
    settle(table,mid,candidate(combat,mid,'Flowing Passage',at=(3,6)).candidate_id,choices=choices)


@pytest.mark.parametrize('cl,count',[(3,1),(6,2),(10,3),(14,4),(18,5)])
def test_native_acquired_progression_tiers(acquired,cl,count):
    bundle=compile_character(acquired(cl),actor_id=OWNER)
    rows=[r for r in bundle['typed_passives'] if r.get('block')=='riverway']
    assert len(rows)==count
    assert {r['feature_id'] for r in rows}==set([PASSAGE,FERRY,MOON,KNOWS,FIELD][:count])


@pytest.mark.parametrize('guard',['unowned','wrong-parent','suppressed'])
def test_acquisition_guards(acquired,guard):
    doc=acquired(18)
    if guard=='unowned':
        doc['path_and_subpath']={}
    else:
        path=next(row for row in doc['path_and_subpath']['paths'] if row['path_id']==QI)
        if guard=='wrong-parent':path['path_id']='tianxia.path.body_refining'
        else:path['effective_cl']=2
    bundle=compile_character(doc,actor_id=OWNER)
    assert not [r for r in bundle['typed_passives'] if r.get('block')=='riverway']


def test_native_passage_and_greater_length_payment_cold(tmp_path,acquired):
    combat,table,mid=game(tmp_path,acquired,foe_position={'x':15,'y':10})
    passage(combat,table,mid,greater=True)
    engine=reload(tmp_path,mid)
    z=placed.of(engine,'riverway_passage')[0]
    assert len(z.affected_cells)==12
    assert placed.data(z)['starters']==[ALLY]
    assert engine.state.actors[OWNER].resources['resource:core.qi']==99
    assert not engine.state.actors[OWNER].bonus_action_available


@pytest.mark.parametrize('endpoint',[(4,6,1),(6,6,2)])
def test_grounded_ally_walks_greater_passage_and_gap(tmp_path,acquired,endpoint,monkeypatch):
    from combat import ext, flight
    from combat.gate2_runtime_models import Position

    def wall(arena):
        # Keep a supported continuation beside the far end of the two-cell
        # gap, so the next choice exists without making a third gap legal.
        arena['terrain_regions'].append({'terrain_type':'BLOCKED','movement_cost':0,
                                          'cells':[{'x':4,'y':5},{'x':6,'y':8}]})
    combat,table,mid=game(tmp_path,acquired,cl=14,foe_position={'x':15,'y':10},
                          battlefield_transform=wall)
    choices={'choice:needle.flowing_passage_allies':[OWNER,ALLY],
             'choice:riverway.greater_allies':[],
             'choice:needle.flowing_passage_cell.1':['cell:4,6,1'],
             'choice:needle.flowing_passage_cell.2':['cell:4,6,2'],
             'choice:needle.flowing_passage_cell.3':['cell:5,6,2'],
             'choice:needle.flowing_passage_cell.4':['cell:6,6,2'],
             'choice:needle.flowing_passage_cell.5':['end']}
    engine=combat._load_session(mid).engine
    action=next(c for c in engine.legal_candidates()
                if c.destination==Position(x=4,y=6) and
                getattr(engine.action_catalog.get(c.source_definition_id),'display_name',None)=='Flowing Passage')
    prompts=settle(table,mid,action.candidate_id,choices=choices)
    last=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.flowing_passage_cell.5')
    options={o['id'] for o in last['choice']['options']}
    assert 'cell:6,7,2' in options  # supported by the far wall
    assert 'cell:7,6,2' not in options  # a third unsupported gap
    turn(table,mid,ALLY)
    engine=reload(tmp_path,mid)
    assert flight.spatial_walk(engine,engine.state.actors[ALLY])
    assert not flight.spatial_walk(engine,engine.state.actors[FOE])
    destination=Position(x=endpoint[0],y=endpoint[1],z=endpoint[2])
    move=next(c for c in engine.legal_candidates()
              if c.kind=='MOVE' and c.destination==destination
              and c.metadata.get('movement_mode','walk')=='walk')
    if endpoint[0]==6:
        assert Position(x=5,y=6,z=2) in move.canonical_path
    settle(table,mid,move.candidate_id)
    engine=reload(tmp_path,mid)
    receipt=next(e for e in reversed(engine.events)
                 if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==ALLY and not e.payload.get('forced'))
    assert receipt.payload['destination']==destination.model_dump(mode='json')
    assert engine.state.actors[ALLY].position.z==0  # the move has ended; native falling settles
    # An independent capability veto must also govern the ground approach.
    blocked=Position(x=5,y=7)
    def deny(engine,actor,previous,destination,mode):
        if actor.entity_id==ALLY and destination==blocked and mode=='walk':
            return False
    with monkeypatch.context() as patch:
        patch.setitem(ext._HOOKS,'movement_step_capability',
                      [*ext._HOOKS.get('movement_step_capability',()),deny])
        assert not any(c.kind=='MOVE' and c.destination==blocked and c.metadata.get('movement_mode','walk')=='walk'
                       for c in engine.legal_candidates())


def test_native_moonlit_pair_not_one_shot_teleport(tmp_path,acquired):
    combat,table,mid=game(tmp_path,acquired,cl=10,foe_position={'x':15,'y':10})
    settle(table,mid,candidate(combat,mid,'Moonlit Ferry',at=(5,6)).candidate_id,
        choices={'choice:riverway.Moonlit Ferry second gate':['cell:10,6']})
    engine=reload(tmp_path,mid)
    gates=placed.of(engine,GATES)
    assert len(gates)==1
    assert [(p.x,p.y) for p in gates[0].affected_cells]==[(5,6),(10,6)]
    assert engine.state.actors[ALLY].position.x==4
    assert engine.state.actors[OWNER].resources['resource:core.qi']==95
    assert engine.state.actors[OWNER].concentration is not None
    turn(table,mid,ALLY)
    moves=[c for c in combat._load_session(mid).engine.legal_candidates() if c.canonical_path and c.destination.x==5 and c.destination.y==6]
    assert moves
    prompts=settle(table,mid,moves[0].candidate_id,choices={'choice:riverway.Moonlit Ferry arrival':['cell:11,6']})
    engine=reload(tmp_path,mid)
    assert any(p['context']['reactor_id']==ALLY for p in prompts if p['context']['reaction_source_id']=='choice:riverway.Moonlit Ferry arrival')
    assert engine.state.actors[ALLY].position.x==11
    assert len(placed.of(engine,GATES))==1
    assert any(e.event_type=='MOVEMENT_COMMITTED' and e.payload.get('teleport') and e.actor_id==ALLY for e in engine.events)


def test_native_field_creation_is_not_a_command_option(tmp_path,acquired):
    combat,table,mid=game(tmp_path,acquired,foe_position={'x':8,'y':6})
    settle(table,mid,candidate(combat,mid,'Imperial River Field',at=(3,6)).candidate_id,
        choices={'choice:riverway.Imperial River Field':[OWNER,ALLY]})
    engine=reload(tmp_path,mid)
    assert len(placed.of(engine,FIELD_TAG))==1
    from combat.spatial_areas import zone_contains_cells
    zone=placed.of(engine,FIELD_TAG)[0]
    assert zone_contains_cells(engine, [(3,6,1)], zone)
    assert zone_contains_cells(engine, [(3,6,7)], zone)
    assert not zone_contains_cells(engine, [(3,6,8)], zone)
    assert not zone_contains_cells(engine, [(3,6,-1)], zone)
    assert zone_contains_cells(engine, [(9,12,0)], zone) is False
    assert zone_contains_cells(engine, [(9,10,0)], zone) is True
    assert engine.state.actors[OWNER].resources['resource:core.qi']==92
    assert engine._effective_speed(engine.state.actors[ALLY])==40
    assert (8,6) in engine._hostile_difficult_cells(engine.state.actors[FOE])
    assert not [c for c in engine.legal_candidates()
                if getattr(engine.action_catalog.get(c.source_definition_id),'display_name',None)=='Imperial River Field']


@pytest.mark.parametrize('mode',['Buoy','Carry','Sweep'])
def test_native_field_commands_resolve_real_targets_and_replay(tmp_path,acquired,mode):
    combat,table,mid=game(tmp_path,acquired,foe_position={'x':8,'y':6})
    target=FOE if mode=='Sweep' else ALLY
    choices={'choice:riverway.Imperial River Field':[OWNER,ALLY],
        'choice:riverway.command':[mode+':'+target],
        'choice:riverway.Command the Current — Carry':['cell:6,6'],
        'choice:riverway.consent':['accept'],'choice:riverway.sweep':['push']}
    settle(table,mid,candidate(combat,mid,'Imperial River Field',at=(3,6)).candidate_id,choices=choices)
    prompts=settle(table,mid,candidate(combat,mid,'Command the Current').candidate_id,choices=choices)
    engine=reload(tmp_path,mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi']==92
    field=placed.of(engine,FIELD_TAG)[0]
    assert placed.data(field)['command_used']
    if mode=='Buoy':assert engine.state.actors[ALLY].temporary_hp==12
    elif mode=='Carry':
        assert engine.state.actors[ALLY].position.x==6
        assert any(p['context']['reactor_id']==ALLY for p in prompts if p['context']['reaction_source_id']=='choice:riverway.consent')
    else:
        assert engine.state.actors[FOE].position.x in (9,11)
        assert any(e.event_type=='SAVE_ROLLED' and e.actor_id==FOE for e in engine.events)


def test_native_knowledge_is_owned_and_breathing_is_mechanical(tmp_path,acquired):
    from combat.physiology import trait
    from combat.tabletop import TabletopMapStore,to_battlefield,battlefield_as_map
    store=TabletopMapStore(tmp_path/'maps')
    doc={'map_id':'water-facts','display_name':'Canal','width_squares':20,'height_squares':14,
        'route_regions':[{'id':'canal','kind':'water','flow':'east','poisoned':1,
            'cells':[{'x':x,'y':6} for x in range(3,19)]}]}
    store.save(doc);arena=to_battlefield(store.get('water-facts'))
    assert battlefield_as_map(arena)['route_regions']==store.get('water-facts')['route_regions']
    combat,table,mid=game(tmp_path/'fight',acquired,cl=14,battlefield=arena)
    settle(table,mid,candidate(combat,mid,'River Knows the Way: read connected water').candidate_id)
    engine=reload(tmp_path/'fight',mid)
    assert trait(engine.state.actors[OWNER],'water_breathing') is True
    assert trait(engine.state.actors[ALLY],'water_breathing') is None
    from combat.information_results import for_observer, describe
    own=for_observer(engine,engine.state.actors[OWNER])
    assert not for_observer(engine,engine.state.actors[ALLY])
    assert 'River Knows the Way' in ' '.join(describe(engine,engine.state.actors[OWNER],own))
    facts=next(r for r in own if r.get('ability')=='River Knows the Way')['water_facts']
    assert any(f.get('poisoned')==1 for f in facts)
    assert all('stagnant' not in f for f in facts)
    assert any(f.get('flow')=='east' and 'poisoned' not in f for f in facts)


@pytest.mark.parametrize('with_passage',[False,True])
def test_native_rescue_moves_damaged_ally_after_packet_with_conditional_protection(tmp_path,acquired,with_passage):
    from tests.test_mgr_t14_sol_subpath_ferry_wounded import AXE, REACTION, damage_ally
    combat,table,mid=game(tmp_path,acquired,cl=6,foe_kit=AXE,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':4,'y':6},FOE:{'x':5,'y':6}})
    if with_passage:
        settle(table,mid,candidate(combat,mid,'Flowing Passage',at=(3,6)).candidate_id,
            choices={'choice:needle.flowing_passage_allies':[OWNER,ALLY],
                     'choice:needle.flowing_passage_cell.1':['cell:3,7'],
                     'choice:needle.flowing_passage_cell.2':['cell:4,7'],
                     'choice:needle.flowing_passage_cell.3':['end']})
    turn(table,mid,FOE)
    engine,events,prompts=damage_ally(combat,table,mid,tmp_path,choices={REACTION: ['cell:4,7']})
    assert (engine.state.actors[ALLY].position.x,engine.state.actors[ALLY].position.y)==(4,7)
    assert engine.state.actors[FOE].position.x==5
    damage=next(i for i,e in enumerate(events) if e.event_type=='DAMAGE_COMMITTED' and ALLY in e.target_ids)
    reaction=next(i for i,e in enumerate(events) if e.event_type=='REACTION_WINDOW_OPENED' and e.source_definition_id==FERRY)
    movement=next(i for i,e in enumerate(events) if e.event_type=='MOVEMENT_COMMITTED' and e.actor_id==ALLY)
    assert damage<reaction<movement
    assert events[damage].payload['temporary_hp_absorbed']==0
    assert engine.state.actors[ALLY].temporary_hp==(engine.state.actors[OWNER].proficiency_bonus if with_passage else 0)
    assert not engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[OWNER].resources['resource:core.qi']==(97 if with_passage else 98)
