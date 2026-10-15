from combat.factory_compiler import compile_character
from combat.ext import placed
from tests.h1_support import sheet
from tests.worker2_support import OWNER,ALLY,FOE,fixture,candidate,settle,reload,turn


def test_creator_knows_tripwire_and_receives_native_save_advantage(tmp_path):
    doc=sheet(['TRAP_BASE_TRIPWIRE'],cl=5,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.tool.thieves_tools','quantity':1,'name':'Thieves’ tools'}]}})
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER),cl=5,
        positions={OWNER:{'x':3,'y':6},ALLY:{'x':2,'y':6},FOE:{'x':6,'y':5}})
    settle(table,mid,candidate(combat,mid,'Trap form: Tripwire').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=(4,6)).candidate_id)
    e=combat._load_session(mid).engine
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==(4,6))
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    saves=[v for v in e.events if v.event_type=='SAVE_ROLLED' and v.actor_id==OWNER]
    assert saves and 'ADVANTAGE' in str(saves[-1].payload)
    assert placed.of(e,'trap')


def test_dart_native_attack_uses_device_geometry_without_moving_creator(tmp_path):
    boundary="cover"
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    from combat import action_geometry
    doc=sheet(["TRAP_BASE_DART_MECHANISM"],cl=5,score=20,kit={'starting_kit':{'items':[
        {'item_id':'tianxia.mortal.tool.thieves_tools','name':'Thieves’ tools','quantity':1}]}})
    trap_at=(1,7) if boundary=='cover' else (2,6)
    foe_at=(8,7) if boundary=='cover' else (20,6)
    ally_at=(0,7) if boundary=='cover' else (1,7)
    arena={'stable_id':'dart-native-origin:'+boundary,'width_squares':30,'height_squares':12,
        'square_size_ft':5,'starting_positions':{},'terrain_regions':[
            {'region_id':'wall','terrain_type':'BLOCKED','cells':[{'x':2,'y':6}],
             'movement_cost':1,'description':'Solid wall'}] if boundary=='cover' else []}
    combat,table,mid=fixture(tmp_path,[],owner_bundle=compile_character(doc,actor_id=OWNER),battlefield=arena,
        seed='MGR-DART-ANCHOR-'+boundary,positions={OWNER:{'x':1,'y':6},ALLY:{'x':ally_at[0],'y':ally_at[1]},
            FOE:{'x':foe_at[0],'y':foe_at[1]}})
    settle(table,mid,candidate(combat,mid,'Trap aim: east').candidate_id)
    settle(table,mid,candidate(combat,mid,'Set Trap',at=trap_at).candidate_id)
    turn(table,mid,ALLY)
    e=combat._load_session(mid).engine;z=placed.of(e,'trap')[0]
    if boundary=='cover':
        assert not e.grid.line_of_sight(e.state.actors[OWNER].position,e.state.actors[FOE].position)
        assert e.grid.line_of_sight(z.affected_cells[0],e.state.actors[FOE].position)
    else:
        assert e.grid.distance_ft(e.state.actors[OWNER].position,e.state.actors[FOE].position)==95
        assert e.grid.distance_ft(z.affected_cells[0],e.state.actors[FOE].position)==90
    move=next(c for c in e.legal_candidates() if c.kind.value=='MOVE' and c.destination and
              (c.destination.x,c.destination.y)==trap_at)
    settle(table,mid,move.candidate_id)
    e=reload(tmp_path,mid)
    attacks=[v for v in e.events if v.event_type=='ATTACK_ROLLED' and FOE in v.target_ids]
    assert attacks and attacks[-1].payload['cover_bonus']==0
    origins=[v.payload['effect_origin'] for v in e.events if v.event_type=='PASSIVE_TRIGGERED'
             and v.payload.get('effect_origin',{}).get('id')=='trap:'+z.zone_id]
    assert origins and origins[-1]['position']=={'x':trap_at[0],'y':trap_at[1],'z':0}
    assert (e.state.actors[OWNER].position.x,e.state.actors[OWNER].position.y)==(1,6)
    action=next(a for a in e.action_catalog.values() if a.owner_id==OWNER and a.parameters.get('set_trap'))
    assert not action_geometry.origins(e,e.state.actors[OWNER],action)
