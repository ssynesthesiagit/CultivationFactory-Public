"""Review regressions through acquired sheets, owner maps and cold services."""
import json
import zipfile
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate2_runtime_models import Position
from combat.factory_compiler import compile_character
from combat.ext.qi_subpaths_five import CLOUD
from tests.h1_support import ROOT, sheet
from tests.worker2_support import settle, turn
from tests.test_mgr_t14_cloud_acquisition import acquired_sheet

A='actor:factory.nativewalker'
B='actor:factory.companion'
KEY='tianxia.subpath.qi.cloud_walker'


def game(tmp_path, acquired_sheet, *, surfaces=(), barriers=(), fields=(), width=36, journey=False):
    for pid,doc in [('nativewalker',acquired_sheet),('companion',sheet([],cl=1,name='Companion'))]:
        folder=tmp_path/'portable_characters'/pid;folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    c=CombatService(ROOT,tmp_path)
    c.tabletop_maps.save({'display_name':'Cloud review yard','width_squares':12,'height_squares':14,
        'walls':[],'starts':{'team1':[[3,6]],'team2':[[4,6]]},'source_data':{KEY:{
            'source':KEY,'authority':'map_owner','declared_by':'Scene GM','expires':'scene',
            'bodies':{A:{'body_weight_lb':160,'width_inches':18},B:{'body_weight_lb':160,'width_inches':width}},
            'surfaces':list(surfaces),'barriers':list(barriers),'fields':list(fields)}}})
    arena='battlefield:map.cloud-review-yard'
    if journey:
        state=c.create_journey(project_ids=['nativewalker','companion'],arena_id=arena,
            positions={A:{'x':3,'y':6},B:{'x':4,'y':6}},base_paces={A:18000,B:18000},
            control_modes={A:'MANUAL',B:'MANUAL'})
        return c,state['journey_id']
    result=c.create_factory_match(project_ids=['nativewalker','companion'],arena_id=arena,
        match_seed='CLOUD-REVIEW-BOUNDARIES',control_modes={A:'MANUAL',B:'MANUAL'})
    t=TabletopService(c,tmp_path);turn(t,result['match_id'],A)
    return c,t,result['match_id']


def action(c,mid,name):
    return next(x for x in c._load_session(mid).engine.legal_candidates() if x.display_name==name)


def verify(tmp_path,mid):
    session=CombatService(ROOT,tmp_path)._load_session(mid)
    assert session.verify()['status']==session.mechanical.replay()['status']=='PASS'
    return session.engine


def barrier(opening, *, axis='y',plane=5,low=(0,0),high=(11,100)):
    return {'axis':axis,'plane':plane,'low':list(low),'high':list(high),
        'opening_inches':opening,'total_cover':False,'sealed_formation':False}


@pytest.mark.parametrize('opening,allowed',[(0,False),('1/2',False),(1,True)])
def test_acquired_wind_journey_boundary_menu_commit_and_cold_load(tmp_path,acquired_sheet,opening,allowed):
    c,jid=game(tmp_path,acquired_sheet,journey=True,barriers=[barrier(opening,axis='x',plane=3)])
    def act(kind,payload=None):
        cold=CombatService(ROOT,tmp_path);state=cold.journey_state(jid)
        return cold.journey_act(jid,state['revision'],A,kind,payload or {})
    act('cloud_wind_begin');act('wait',{'seconds':600});act('cloud_wind_finish')
    before=CombatService(ROOT,tmp_path).journey_state(jid)
    menu=CombatService(ROOT,tmp_path).journey_menu(jid,A)
    assert any(x['id']=='move:2,6,0' for x in menu['options']) is allowed
    if allowed:
        after=act('move',{'path':[{'x':2,'y':6}]})
        assert after['actors'][A]['position']=={'x':2,'y':6,'z':0}
    else:
        with pytest.raises(ValueError,match='boundary|opening'):
            act('move',{'path':[{'x':2,'y':6}]})
        assert CombatService(ROOT,tmp_path).journey_state(jid)==before


@pytest.mark.parametrize('width,carried',[(18,True),(36,False)])
def test_acquired_passenger_uses_own_width_for_every_leap_edge(tmp_path,acquired_sheet,width,carried):
    c,t,mid=game(tmp_path,acquired_sheet,width=width,barriers=[barrier(24)])
    before=c._load_session(mid).engine.state.actors[A].resources['resource:core.qi']
    settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,choices={
        'choice:needle.cloud_leap_destination':['cell:3,3'],
        'choice:needle.cloud_leap_companion':[B],
        'choice:needle.fact_admission.heavenly_leap_carry':['accept'],
        'choice:needle.cloud_leap_landing':['cell:4,3']})
    e=verify(tmp_path,mid)
    assert e.state.actors[A].position==Position(x=3,y=3)
    assert (e.state.actors[B].position.y<5) is carried
    assert e.state.actors[A].resources['resource:core.qi']==before-(5 if carried else 3)


def test_acquired_passenger_landing_does_not_cross_an_airtight_face(tmp_path,acquired_sheet):
    c,t,mid=game(tmp_path,acquired_sheet,barriers=[barrier(0,axis='x',plane=4,low=(3,0),high=(3,100))])
    prompts=settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,choices={
        'choice:needle.cloud_leap_destination':['cell:3,3'],
        'choice:needle.cloud_leap_companion':[B],
        'choice:needle.fact_admission.heavenly_leap_carry':['accept'],
        'choice:needle.cloud_leap_landing':'first'})
    landing=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.cloud_leap_landing')
    assert 'cell:4,3' not in json.dumps(landing)
    e=verify(tmp_path,mid)
    assert e.state.actors[B].position.x<=3


@pytest.mark.parametrize('kind',['water','liquid','snow','mud','loose_sand','hanging_cloth'])
def test_acquired_ground_surface_cross_end_and_cold_reload(tmp_path,acquired_sheet,kind):
    surface={'id':'ground-footing','kind':kind,'cells':[[2,6]],'z':0,'capacity_lb':1,
        'fragile':False,'trigger':'weight'}
    c,t,mid=game(tmp_path,acquired_sheet,surfaces=[surface])
    e=c._load_session(mid).engine
    move=next(x for x in e.legal_candidates() if x.kind.value=='MOVE' and x.destination==Position(x=2,y=6))
    settle(t,mid,move.candidate_id)
    e=verify(tmp_path,mid)
    assert not any(x.data.get('surface_id')=='ground-footing' for x in e.state.actors[A].conditions.values())
    settle(t,mid,t.state(mid)['menu']['end_turn'])
    e=verify(tmp_path,mid)
    held=next(x for x in e.state.actors[A].conditions.values() if x.data.get('surface_id')=='ground-footing')
    assert held.data['kind']==kind
    assert held.data['movement_cost']==2
    turn(t,mid,A)
    move=next(x for x in c._load_session(mid).engine.legal_candidates()
        if x.kind.value=='MOVE' and x.destination==Position(x=1,y=6))
    settle(t,mid,move.candidate_id)
    e=verify(tmp_path,mid)
    assert not any(x.data.get('surface_id')=='ground-footing' for x in e.state.actors[A].conditions.values())
