"""Native acquired passenger routes, source costs and interruption controls."""
import json
import pytest
from combat.gate5_service import CombatService
from tests.test_mgr_t14_cloud_resume import (game,action,verify,barrier,A,B,CLOUD,Position,settle,turn,
    acquired_sheet,tested_source_identity,assert_native_qi_payment)

@pytest.mark.parametrize('width,carried',[(18,True),(36,False)])
def test_acquired_passenger_uses_own_width_for_every_leap_edge(tmp_path,acquired_sheet,width,carried):
    c,t,mid=game(tmp_path,acquired_sheet,width=width,barriers=[barrier(24)])
    e=c._load_session(mid).engine;before=e.state.actors[A].resources['resource:core.qi'];since=len(e.events)
    settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,choices={
        'choice:needle.cloud_leap_destination':['cell:3,3'],
        'choice:needle.cloud_leap_companion':[B],
        'choice:needle.fact_admission.heavenly_leap_carry':['accept'],
        'choice:needle.cloud_leap_landing':['cell:4,3']})
    e=verify(tmp_path,mid)
    assert e.state.actors[A].position==Position(x=3,y=3)
    assert (e.state.actors[B].position.y<5) is carried
    assert_native_qi_payment(e,before,since,CLOUD+'heavenly_leap',5 if carried else 3)


def test_acquired_passenger_landing_does_not_cross_an_airtight_face(tmp_path,acquired_sheet):
    c,t,mid=game(tmp_path,acquired_sheet,barriers=[barrier(0,axis='x',plane=4,low=(0,0),high=(4,100))])
    prompts=settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,choices={
        'choice:needle.cloud_leap_destination':['cell:3,3'],
        'choice:needle.cloud_leap_companion':[B],
        'choice:needle.fact_admission.heavenly_leap_carry':['accept'],
        'choice:needle.cloud_leap_landing':'first'})
    landing=next(p for p in prompts if p['context']['reaction_source_id']=='choice:needle.cloud_leap_landing')
    assert 'cell:4,3' not in json.dumps(landing)
    e=verify(tmp_path,mid)
    assert e.state.actors[B].position.x<=3


def test_acquired_feather_fall_does_not_protect_the_carried_unowned_companion(tmp_path,acquired_sheet):
    c,t,mid=game(tmp_path,acquired_sheet,width=18)
    before=c._load_session(mid).engine
    hp={aid:before.state.actors[aid].current_hp for aid in (A,B)}
    settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,choices={
        'choice:needle.cloud_leap_destination':['cell:3,3,12'],
        'choice:needle.cloud_leap_companion':[B],
        'choice:needle.fact_admission.heavenly_leap_carry':['accept'],
        'choice:needle.cloud_leap_landing':['cell:4,3,12'],
        'choice:needle.featherfall':None,'choice:needle.fall_ability':None})
    e=verify(tmp_path,mid)
    assert e.state.actors[A].position.z==e.state.actors[B].position.z==0
    assert e.state.actors[A].current_hp==hp[A]
    assert e.state.actors[B].current_hp<hp[B]
    assert any(r.reason=='FALLING_DAMAGE' and r.actor_id==A for r in e.rolls)
    assert any(r.reason=='FALLING_DAMAGE' and r.actor_id==B for r in e.rolls)


def test_acquired_leap_keeps_large_companions_left_side_landing_reachable(tmp_path,acquired_sheet):
    c,t,mid=game(tmp_path,acquired_sheet,width=120,companion_size='Large')
    e=c._load_session(mid).engine;before=e.state.actors[A].resources['resource:core.qi'];since=len(e.events)
    settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,choices={
        'choice:needle.cloud_leap_destination':['cell:3,3'],
        'choice:needle.cloud_leap_companion':[B],
        'choice:needle.fact_admission.heavenly_leap_carry':['accept'],
        'choice:needle.cloud_leap_landing':['cell:1,3']})
    e=verify(tmp_path,mid)
    assert e.state.actors[B].position==Position(x=1,y=3)
    assert_native_qi_payment(e,before,since,CLOUD+'heavenly_leap',5)
    assert not set(e._actor_volume(e.state.actors[A])) & set(e._actor_volume(e.state.actors[B]))


@pytest.mark.parametrize('companion',[False,True])
def test_acquired_immortal_leap_waiver_never_creates_qi_or_discounts_the_companion(tmp_path,acquired_sheet,companion):
    c,t,mid=game(tmp_path,acquired_sheet,width=18)
    settle(t,mid,action(c,mid,'Cloud Immortal').candidate_id)
    settle(t,mid,t.state(mid)['menu']['end_turn']);turn(t,mid,A)
    e=c._load_session(mid).engine;before=e.state.actors[A].resources['resource:core.qi'];since=len(e.events)
    choices={'choice:needle.cloud_leap_destination':['cell:3,3']}
    if companion:choices.update({'choice:needle.cloud_leap_companion':[B],
        'choice:needle.fact_admission.heavenly_leap_carry':['accept'],
        'choice:needle.cloud_leap_landing':['cell:4,3']})
    settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,choices=choices)
    e=verify(tmp_path,mid);events=e.events[since:]
    spends=[ev for ev in events if ev.event_type=='RESOURCE_SPENT' and ev.actor_id==A
        and ev.payload.get('resource_id')=='resource:core.qi']
    assert sum(ev.payload['amount'] for ev in spends)==(2 if companion else 0)
    assert not any(ev.event_type=='RESOURCE_GAINED' and ev.actor_id==A
        and ev.payload.get('resource_id')=='resource:core.qi' for ev in events)
    assert e.state.actors[A].resources['resource:core.qi']==before-(2 if companion else 0)


def test_native_refund_permission_guard_rolls_back_the_real_paid_use(tmp_path,acquired_sheet,monkeypatch):
    from tests.test_lock_choices import install
    from combat.gate5_service import CombatServiceError
    c,t,mid=game(tmp_path,acquired_sheet)
    e=c._load_session(mid).engine;before=e.state.model_dump(mode='json')
    cid=action(c,mid,'Cloud Step').candidate_id
    with monkeypatch.context() as scoped:
        install(scoped,'technique_refund_allowed',lambda *args:'yes')
        with pytest.raises(CombatServiceError) as caught:
            settle(t,mid,cid)
        assert 'refund permission' in str(caught.value.__cause__)
    assert verify(tmp_path,mid).state.model_dump(mode='json')==before



def test_acquired_large_companion_cannot_enter_a_plane_with_its_leading_body(tmp_path,acquired_sheet):
    face=barrier(24,axis='x',plane=4,low=(0,0),high=(4,100))
    c,t,mid=game(tmp_path,acquired_sheet,width=120,companion_size='Large',barriers=[face])
    e=c._load_session(mid).engine;before=e.state.actors[A].resources['resource:core.qi'];since=len(e.events)
    settle(t,mid,action(c,mid,'Heavenly Leap').candidate_id,choices={
        'choice:needle.cloud_leap_destination':['cell:3,3'],
        'choice:needle.cloud_leap_companion':[B],
        'choice:needle.fact_admission.heavenly_leap_carry':['accept'],
        'choice:needle.cloud_leap_landing':'first'})
    e=verify(tmp_path,mid)
    assert e.state.actors[A].position==Position(x=3,y=3)
    assert e.state.actors[B].position==Position(x=4,y=6)
    assert_native_qi_payment(e,before,since,CLOUD+'heavenly_leap',3)
