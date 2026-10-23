"""Printed Magma through table/session execution and fresh service reload."""
import copy
import pytest
from combat import zones
from combat.ext import surface_areas
from combat.ext.needle import cell_id
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, settle, cell_send, turn, ascend
from tests.h1_support import ROOT
MAGMA='tianxia.sphere.magma'
SLAG='TAL_MAGMA_SLAG_GRASP'
GROUND='TAL_MAGMA_MOLTEN_GROUND'
FLOW='TAL_MAGMA_LAVA_FLOW'
RIVER='TAL_MAGMA_BLACKGLASS_RIVER'


def cold(c,m):
    expected=c._load_session(m).engine.state.model_dump(mode='json')
    c=CombatService(ROOT,c.userdata_root)
    session=c._load_session(m)
    assert session.engine.state.model_dump(mode='json')==expected
    assert session.verify()['status']=='PASS'
    assert session.mechanical.replay()['status']=='PASS'
    assert not any(v.event_type=='GM_RIDER' and any(key in v.source_definition_id for key in [SLAG,GROUND,FLOW]) for v in session.engine.events)
    return c,TabletopService(c,c.userdata_root),session.engine


def events(e,kind):
    return [v for v in e.events if v.event_type==kind]


def choice(ability):
    return lambda p: [ability] if p['context']['reaction_source_id']=='choice:needle.save_choice' else [p['choice']['options'][0]['id']]


def move_line(c, t, m, name, xy, area=None):
    def pick(p):
        source=p['context']['reaction_source_id']
        if source=='choice:needle.surface_destination':
            wanted=cell_id(Position(x=xy[0],y=xy[1]))
            assert wanted in [v['id'] for v in p['choice']['options']]
            return [wanted]
        if source=='choice:needle.surface_area' and area is not None:
            assert p['context']['reactor_id']==LEFT
            return [area]
        return [p['choice']['options'][0]['id']]
    return settle(lambda a:act(t,m,name+': move the line',a),pick)


@pytest.mark.parametrize('ability',['STR','DEX'])
@pytest.mark.parametrize('success',[False,True])
def test_slag_target_choice_outcomes_and_printed_expiry(tmp_path,ability,success):
    c,t,m=fight(tmp_path,[SLAG],spheres=[MAGMA],left_save_dc=-100 if success else 100)
    _,prompts=settle(lambda a:act(t,m,'Slag Grasp',a,target_id=RIGHT),choice(ability))
    assert any(p['context']['reactor_id']==RIGHT for p in prompts if p['context']['reaction_source_id']=='choice:needle.save_choice')
    c,t,e=cold(c,m)
    assert events(e,'SAVE_ROLLED')[-1].payload['reason'].endswith(':'+ability)
    owner,target=e.state.actors[LEFT],e.state.actors[RIGHT]
    assert owner.resources['resource:core.qi']==98 and not owner.action_available
    if success:
        assert target.current_hp==1000 and e._effective_speed(target)==20
    else:
        assert target.current_hp<1000
        assert events(e,'DAMAGE_ROLLED')[-1].payload['expression']=='1d8+2'
        assert any(x.condition_id=='condition:typed.restrained' for x in target.conditions.values())
    turn(t,m,RIGHT)
    c,t,e=cold(c,m)
    if success:
        assert e._effective_speed(e.state.actors[RIGHT])==20
    else:
        assert any(x.condition_id=='condition:typed.restrained' for x in e.state.actors[RIGHT].conditions.values())
        assert any(g['label']=='Break free' for g in t.state(m)['menu']['actions'])
    turn(t,m,LEFT)
    c,t,e=cold(c,m)
    assert not any(x.condition_id=='condition:typed.restrained' for x in e.state.actors[RIGHT].conditions.values())
    assert e._effective_speed(e.state.actors[RIGHT])==30


@pytest.mark.parametrize('success',[False,True])
def test_slag_escape_uses_caster_dc_and_removes_only_its_hold(tmp_path,success):
    def stats(bundle):
        if bundle['actor_template']['entity_id']==RIGHT:
            bundle['actor_template']['saving_throws']['DEX']=-100
    dc=1 if success else 25
    c,t,m=fight(tmp_path,[SLAG],spheres=[MAGMA],left_save_dc=dc,right_score=14,bundle_edit=stats,
                cause=[{'type':'condition','condition':'restrained','applies_to':'self','duration':'one_minute'}],cause_target='SELF')
    settle(lambda a:act(t,m,'Slag Grasp',a,target_id=RIGHT),choice('DEX'))
    turn(t,m,RIGHT)
    settle(lambda a:act(t,m,'Cause',a))
    c,t,e=cold(c,m)
    assert len([x for x in e.state.actors[RIGHT].conditions.values() if x.condition_id=='condition:typed.restrained'])==2
    settle(lambda a:act(t,m,'Break free',a))
    c,t,e=cold(c,m)
    check=events(e,'CHECK_ROLLED')[-1]
    assert check.payload['dc']==dc and check.payload['success']==success
    assert not e.state.actors[RIGHT].action_available
    held=[x for x in e.state.actors[RIGHT].conditions.values() if x.condition_id=='condition:typed.restrained']
    assert len(held)==(1 if success else 2)
    if success:
        assert all(x.source_actor_id==RIGHT for x in held)


@pytest.mark.parametrize('cl,count',[(1,2),(5,3),(11,5),(17,7)])
@pytest.mark.parametrize('success',[False,True])
def test_ground_scaling_save_and_one_trigger_per_actual_turn(tmp_path,cl,count,success):
    c,t,m=fight(tmp_path,[GROUND],spheres=[MAGMA],cl=cl,left_save_dc=-100 if success else 100)
    settle(cell_send(t,m,'Molten Ground',(4,6)))
    c,t,e=cold(c,m)
    assert not events(e,'DAMAGE_ROLLED')
    assert e.state.actors[LEFT].resources['resource:core.qi']==97
    z,=zones.typed_zones(e)
    assert z.concentration_link and (4,6) in zones.difficult_cells(e,e.state.actors[RIGHT])
    turn(t,m,RIGHT)
    c,t,e=cold(c,m)
    assert len(events(e,'SAVE_ROLLED'))==1
    roll=events(e,'DAMAGE_ROLLED')[-1]
    assert roll.payload['expression']==f'{count}d6+0'
    assert e.state.actors[RIGHT].current_hp==1000-(roll.payload['total']//2 if success else roll.payload['total'])
    assert (4,6) in zones.difficult_cells(e,e.state.actors[RIGHT])
    state=t.state(m)
    cid=next(v.candidate_id for v in c._load_session(m).engine.legal_candidates()
             if v.kind.value=='MOVE' and v.destination and (v.destination.x,v.destination.y)==(5,6))
    settle(lambda a:t.act(m,cid,state['menu']['decision_id'],state['menu']['state_version'],state['last_sequence'],a))
    c,t,e=cold(c,m)
    assert len(events(e,'SAVE_ROLLED'))==1
    assert e.state.actors[RIGHT].movement_remaining_ft==20


@pytest.mark.parametrize('source,name,width',[(FLOW,'Lava Flow',10),(RIVER,'Blackglass River',15)])
def test_moving_line_preserves_shape_clock_and_spends_bonus(tmp_path,source,name,width):
    c,t,m=fight(tmp_path,[source],spheres=[MAGMA],cl=15,positions={LEFT:{'x':3,'y':6},RIGHT:{'x':5,'y':6}},arena_edit=lambda a:a.update(terrain_regions=[]))
    assert not any(g['label']==name+': move the line' for g in t.state(m)['menu']['actions'])
    settle(cell_send(t,m,name,(5,6)))
    c,t,e=cold(c,m)
    z,=zones.typed_zones(e);old=copy.deepcopy(z.model_dump(mode='json'))
    assert not events(e,'DAMAGE_ROLLED')
    dy = 2 if source == RIVER else 1
    move_line(c,t,m,name,(5,6+dy))
    c,t,e=cold(c,m)
    z,=zones.typed_zones(e)
    assert z.zone_id==old['zone_id'] and z.center.y==6+dy
    assert {(p.x,p.y,p.z) for p in z.affected_cells}=={(p['x'],p['y']+dy,p.get('z',0)) for p in old['affected_cells']}
    assert z.trigger_profile['width_ft']==width
    assert z.trigger_profile['area_vertex']==[old['trigger_profile']['area_vertex'][0],old['trigger_profile']['area_vertex'][1]+dy,0]
    assert z.duration_rounds==old['duration_rounds'] and z.created_round==old['created_round']
    assert z.per_turn_triggered==old['per_turn_triggered']
    assert not e.state.actors[LEFT].bonus_action_available
    turn(t,m,RIGHT)
    c,t,e=cold(c,m)
    if source == FLOW:
        assert events(e,'DAMAGE_ROLLED')
    else:
        state=t.state(m)
        candidate=next(v for v in e.legal_candidates() if v.kind.value=='MOVE' and v.destination==Position(x=5,y=8))
        settle(lambda a:t.act(m,candidate.candidate_id,state['menu']['decision_id'],state['menu']['state_version'],state['last_sequence'],a))
        c,t,e=cold(c,m)
        assert events(e,'DAMAGE_ROLLED')


def test_slag_rejects_airborne_target_before_payment(tmp_path):
    c,t,m=fight(tmp_path,[SLAG],spheres=[MAGMA],cause=[{'type':'general_flight','speed_ft':30,'applies_to':'self','hover':True,'duration':{'kind':'minutes','amount':1}}],cause_target='SELF')
    turn(t,m,RIGHT);settle(lambda a:act(t,m,'Cause',a));ascend(c,t,m,RIGHT);turn(t,m,LEFT)
    c,t,e=cold(c,m)
    assert e.state.actors[RIGHT].position.z==1
    assert not any(g['label']=='Slag Grasp' for g in t.state(m)['menu']['actions'])
    assert e.state.actors[LEFT].resources['resource:core.qi']==100


def clear_arena(arena):
    arena['terrain_regions']=[]


def test_line_rejects_a_route_that_would_drag_any_strip_through_a_pillar(tmp_path):
    c,t,m=fight(tmp_path,[FLOW],spheres=[MAGMA],positions={LEFT:{'x':3,'y':6},RIGHT:{'x':5,'y':6}})
    settle(cell_send(t,m,'Lava Flow',(5,6)))
    c,t,e=cold(c,m)
    action=next(a for a in e.action_catalog.values() if a.display_name=='Lava Flow: move the line')
    destinations={(p.x,p.y) for p in surface_areas.destinations(e,e.state.actors[LEFT],action,action.parameters['surface_translation'])}
    assert (5,7) not in destinations, 'the upper strip would cross the center pillar'
    assert (5,9) not in destinations, 'movement is limited to 10 feet'
    assert e.state.actors[LEFT].bonus_action_available
    assert e.state.actors[LEFT].resources['resource:core.qi']==95


def test_held_line_remains_movable_after_starting_another_concentration(tmp_path):
    c,t,m=fight(tmp_path,[FLOW,GROUND],spheres=[MAGMA],arena_edit=clear_arena,
                positions={LEFT:{'x':3,'y':6},RIGHT:{'x':5,'y':6}})
    settle(cell_send(t,m,'Lava Flow',(5,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(cell_send(t,m,'Molten Ground',(3,4)))
    c,t,e=cold(c,m)
    assert e.state.actors[LEFT].concentration.source_definition_id.endswith(GROUND)
    old={z.zone_id:copy.deepcopy(z.model_dump(mode='json')) for z in zones.typed_zones(e)}
    move_line(c,t,m,'Lava Flow',(5,7))
    c,t,e=cold(c,m)
    flowing=[z for z in zones.typed_zones(e) if z.source_definition_id.endswith(FLOW)]
    ground=[z for z in zones.typed_zones(e) if z.source_definition_id.endswith(GROUND)]
    assert flowing[0].center.y==7
    assert ground[0].model_dump(mode='json')==old[ground[0].zone_id]
    assert flowing[0].per_turn_triggered==old[flowing[0].zone_id]['per_turn_triggered']
    assert e.state.actors[LEFT].resources['resource:core.qi']==92


def test_two_live_copies_let_owner_choose_the_area_that_moves(tmp_path):
    c,t,m=fight(tmp_path,[FLOW],spheres=[MAGMA],arena_edit=clear_arena,
                positions={LEFT:{'x':3,'y':6},RIGHT:{'x':5,'y':6}})
    settle(cell_send(t,m,'Lava Flow',(5,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(cell_send(t,m,'Lava Flow',(5,6)))
    c,t,e=cold(c,m)
    areas=list(zones.typed_zones(e));assert len(areas)==2
    selected=areas[-1].zone_id
    old={z.zone_id:copy.deepcopy(z.model_dump(mode='json')) for z in areas}
    _,prompts=move_line(c,t,m,'Lava Flow',(5,7),selected)
    assert any(p['context']['reaction_source_id']=='choice:needle.surface_area' for p in prompts)
    c,t,e=cold(c,m)
    for z in zones.typed_zones(e):
        if z.zone_id==selected:
            assert z.center.y==7
        else:
            assert z.model_dump(mode='json')==old[z.zone_id]


def test_surface_zone_does_not_burn_a_hovering_creature_above_it(tmp_path):
    flight={'type':'general_flight','speed_ft':30,'applies_to':'self','hover':True,'duration':{'kind':'minutes','amount':1}}
    c,t,m=fight(tmp_path,[GROUND],spheres=[MAGMA],cause=[flight],cause_target='SELF')
    turn(t,m,RIGHT);settle(lambda a:act(t,m,'Cause',a));ascend(c,t,m,RIGHT);turn(t,m,LEFT)
    settle(cell_send(t,m,'Molten Ground',(4,6)))
    turn(t,m,RIGHT)
    c,t,e=cold(c,m)
    assert e.state.actors[RIGHT].position.z==1 and e.state.actors[RIGHT].current_hp==1000
    assert not events(e,'SAVE_ROLLED')


def test_line_ends_and_mover_disappears_when_concentration_is_lost(tmp_path):
    c,t,m=fight(tmp_path,[FLOW],spheres=[MAGMA],arena_edit=clear_arena,
                positions={LEFT:{'x':3,'y':6},RIGHT:{'x':5,'y':6}},
                cause=[{'type':'condition','condition':'stunned','applies_to':'target','duration':'one_minute'}])
    settle(cell_send(t,m,'Lava Flow',(5,6)))
    turn(t,m,RIGHT);settle(lambda a:act(t,m,'Cause',a,target_id=LEFT))
    c,t,e=cold(c,m)
    assert e.state.actors[LEFT].concentration is None
    assert not zones.typed_zones(e)
    turn(t,m,LEFT)
    assert not any(g['label']=='Lava Flow: move the line' for g in t.state(m)['menu']['actions'])


def test_line_movement_is_not_limited_by_its_original_casting_range(tmp_path):
    c,t,m=fight(tmp_path,[FLOW],spheres=[MAGMA],arena_edit=clear_arena,
                positions={LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6}})
    settle(cell_send(t,m,'Lava Flow',(15,6)))
    state=t.state(m)
    cid=next(v.candidate_id for v in c._load_session(m).engine.legal_candidates()
             if v.kind.value=='MOVE' and v.destination and (v.destination.x,v.destination.y)==(2,6))
    settle(lambda a:t.act(m,cid,state['menu']['decision_id'],state['menu']['state_version'],state['last_sequence'],a))
    c,t,e=cold(c,m)
    assert e.grid.distance_ft(e.state.actors[LEFT].position,next(iter(zones.typed_zones(e))).center)>60
    move_line(c,t,m,'Lava Flow',(15,7))
    c,t,e=cold(c,m)
    z,=zones.typed_zones(e)
    assert z.center.x==15 and z.center.y==7
    assert e.state.actors[LEFT].resources['resource:core.qi']==95
