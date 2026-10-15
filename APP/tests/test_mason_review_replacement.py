"""Replacement choices remain controller-owned and sequentially collision safe."""
from tests.mason_native_support import *
from tests.test_mason_review_journey import build_payload


def test_two_journey_occupants_cannot_choose_the_same_replacement_square(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',build_payload(
        'bridge_the_impossible','Great Bridge',4,4,length_ft=10,width_ft=10,height_ft=10,legal_load='ordinary'))
    old=set(state['runtime_objects'])
    for aid,x in [(s.OWNER,4),(s.SECOND,5)]:
        state=combat.journey_act(jid,state['revision'],aid,'move',{'path':[
            {'x':x,'y':5,'z':1},{'x':x,'y':5,'z':2}]})
    options={aid:[o for o in combat.journey_menu(jid,aid)['options'] if o['id'].startswith('mason_replacement:')]
        for aid in (s.OWNER,s.SECOND)}
    common=next(a['payload'] for a in options[s.OWNER] if any(
        a['payload']['value']==b['payload']['value'] for b in options[s.SECOND]))
    for aid in (s.OWNER,s.SECOND):
        declaration={**common,'subject':aid,'expires_at':int(state['seconds'])+6}
        state=combat.journey_act(jid,state['revision'],aid,'declare_fact',declaration)
    replacement=build_payload('bridge_the_impossible','Ascending Stair',7,8,length_ft=10,width_ft=10,height_ft=10)
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',replacement)
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    other=next(o['payload'] for o in options[s.SECOND] if o['payload']['value']!=common['value'])
    state=combat.journey_act(jid,state['revision'],s.SECOND,'declare_fact',{**other,'expires_at':int(state['seconds'])+6})
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',replacement)
    assert state['actors'][s.OWNER]['position']!=state['actors'][s.SECOND]['position']
    assert all(state['runtime_objects'][oid]['destroyed'] for oid in old)
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
