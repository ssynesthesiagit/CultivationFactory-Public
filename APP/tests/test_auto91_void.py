"""Void's native ongoing field and opt-in, dynamic incarnation flight."""
import pytest
from combat import flight
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.void_support import ascend, cell_send, cell_sender, settle, turn
from tests.b3f2_support import cell_send

FIELD='TAL_VOID_VOID_FIELD'
SOVEREIGN='TAL_VOID_VOID_SOVEREIGN_INCARNATION'

@pytest.mark.parametrize('success',[False,True])
@pytest.mark.parametrize('ai',[False,True])
def test_field_saves_on_actual_start_not_cast_and_renews(tmp_path,success,ai):
    c,t,m=fight(tmp_path,[FIELD],positions={LEFT:{'x':1,'y':1},RIGHT:{'x':8,'y':1}},right_score=214 if success else 14)
    settle(cell_sender(c,t,m,'Void Field',(8,1),ai))
    e=reload(c,m)
    assert e.state.actors[RIGHT].current_hp==1000
    assert not any(v.event_type=='SAVE_ROLLED' for v in e.events)
    if ai:c.set_controller_mode(m,actor_id=LEFT,controller_mode='MANUAL')
    turn(t,m,RIGHT)
    e=reload(c,m)
    damage=[v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids]
    roll=[v for v in e.events if v.event_type=='DAMAGE_ROLLED'][-1]
    assert len(damage)==1 and len(roll.payload['dice'])==5
    assert damage[0].payload['hp_damage']==(roll.payload['total']//2 if success else roll.payload['total'])
    assert any(x.condition_id.endswith('.hollowed') for x in e.state.actors[RIGHT].conditions.values())== (not success)
    if success:assert any(x.condition_id.endswith('.no_temp_hp') for x in e.state.actors[RIGHT].conditions.values())
    turn(t,m,LEFT);turn(t,m,RIGHT)
    e=reload(c,m)
    assert len([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids])==2
    assert e.state.actors[LEFT].resources['resource:core.qi']==96


def test_field_entry_start_limit_and_later_turn(tmp_path):
    c,t,m=fight(tmp_path,[FIELD],positions={LEFT:{'x':1,'y':1},RIGHT:{'x':8,'y':1}},right_score=214,cause_target='SELF',
                cause=[{'type':'teleport','applies_to':'self','distance_ft':90}])
    settle(cell_send(t,m,'Void Field',(8,1)))
    turn(t,m,RIGHT)
    for _ in range(2):
        settle(cell_send(t,m,'Cause',(17,1)))
        settle(cell_send(t,m,'Cause',(8,1)))
    e=reload(c,m)
    assert len([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids])==1
    assert len([v for v in e.events if v.event_type=='MOVEMENT_COMMITTED' and v.actor_id==RIGHT])==4
    turn(t,m,LEFT);turn(t,m,RIGHT)
    e=reload(c,m)
    assert len([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and RIGHT in v.target_ids])==2


def test_legacy_field_keeps_its_saved_cast_save(tmp_path):
    def old(bundle):
        for a in bundle['action_catalog']:
            typed=a.get('parameters',{}).get('typed',{})
            if typed.get('source')==FIELD:
                z=typed['effects'][0];saved=z.pop('triggers')[0]['effects'][0]
                typed['effects'].insert(0,saved)
    c,t,m=fight(tmp_path,[FIELD],positions={LEFT:{'x':1,'y':1},RIGHT:{'x':8,'y':1}},bundle_edit=old)
    settle(cell_send(t,m,'Void Field',(8,1)))
    e=reload(c,m)
    assert e.state.actors[RIGHT].current_hp<1000
    assert any(v.event_type=='SAVE_ROLLED' for v in e.events)


@pytest.mark.parametrize('case',['manual','ai','legacy'])
def test_sovereign_opt_in_flight_hover_tracks_actual_speed(tmp_path,case):
    def old(bundle):
        if case=='legacy':
            for a in bundle['action_catalog']:
                rows=a.get('parameters',{}).get('typed',{}).get('effects',[])
                rows[:]=[x for x in rows if x.get('condition')!='void_sovereign_flight']
    c,t,m=fight(tmp_path,[SOVEREIGN],bundle_edit=old,prepare_target='ALLY_OR_SELF',
        prepare=[{'type':'speed','applies_to':'target','flat':-10,'duration':'one_minute'}])
    e=reload(c,m);assert flight.profile(e,e.state.actors[LEFT]).speed_ft==0
    settle(action_sender(c,t,m,'Void-Sovereign Incarnation',ai=case=='ai'))
    e=reload(c,m);a=e.state.actors[LEFT]
    assert flight.profile(e,a).speed_ft==(0 if case=='legacy' else 30)
    assert flight.profile(e,a).hover==(case!='legacy')
    assert a.resources['resource:core.qi']==90
    if case=='manual':
        assert ascend(c,t,m,LEFT)['status']=='COMMITTED'
        settle(lambda answers:act(t,m,'Prepare',answers,target_id=LEFT))
        e=reload(c,m);a=e.state.actors[LEFT]
        assert e._effective_speed(a)==20 and flight.profile(e,a).speed_ft==20


def test_sovereign_flight_native_timer_ends_after_ten_rounds(tmp_path):
    c,t,m=fight(tmp_path,[SOVEREIGN],maximum_rounds=12)
    settle(lambda answers:act(t,m,'Void-Sovereign Incarnation',answers))
    e=reload(c,m);assert flight.profile(e,e.state.actors[LEFT]).speed_ft==30
    for _ in range(10):turn(t,m,RIGHT);turn(t,m,LEFT)
    e=reload(c,m);assert flight.profile(e,e.state.actors[LEFT]).speed_ft==0
