"""Fixed-target native movement queries preserve complete-query routes."""
import pytest
from combat.flight import reachable
from combat.read_queries import candidate_pass
from tests.test_mgr_t14_cloud_resume import (game,action,verify,A,Position,settle,acquired_sheet,tested_source_identity)

@pytest.mark.parametrize('mode',['walk','fly'])
def test_fixed_target_preserves_native_route_price_and_query_inertness(tmp_path,acquired_sheet,mode):
    c,t,mid=game(tmp_path,acquired_sheet)
    settle(t,mid,action(c,mid,'Cloud Step').candidate_id)
    e=verify(tmp_path,mid);actor=e.state.actors[A]
    before=actor.model_dump(mode='json'),len(e.events),e.roller.counter
    full=reachable(e,actor,grant_ft=15,mode=mode)
    with candidate_pass(e):
        assert reachable(e,actor,grant_ft=15,mode=mode)==full
    for target in [Position(x=3,y=5),Position(x=4,y=6),Position(x=9,y=9),Position(x=3,y=6,z=1)]:
        limited=reachable(e,actor,grant_ft=15,mode=mode,target=target)
        assert limited==({target:full[target]} if target in full else {})
    assert (actor.model_dump(mode='json'),len(e.events),e.roller.counter)==before


def test_acquired_native_equipment_guard_cannot_be_swallowed_by_a_menu_provider(tmp_path,acquired_sheet,monkeypatch):
    from tests.test_lock_choices import install
    c,t,mid=game(tmp_path,acquired_sheet)
    e=c._load_session(mid).engine;before=e.state.model_dump(mode='json')
    with monkeypatch.context() as scoped:
        install(scoped,'equipment_use_allowed',lambda *args:1)
        with pytest.raises(ValueError,match='equipment_use_allowed'):
            e.legal_candidates()
    assert verify(tmp_path,mid).state.model_dump(mode='json')==before


def test_native_owner_map_profile_cold_roundtrip_keeps_its_exact_object_binding(tmp_path):
    from copy import deepcopy
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    c=CombatService(ROOT,tmp_path)
    saved=c.tabletop_maps.save({'display_name':'Bound source profile','width_squares':12,'height_squares':14,
        'walls':[],'objects':[{'id':1,'kind':'custom','name':'Scene Anchor','x':3,'y':5,'ac':10,'hp':20,
        'blocks':False,'source_cl':17,'cultivation_asset':True,'asset_declaration':{
        'actor':'Scene GM','authority':'GM','source_rule':'This Anchor supplies the declared scene field.',
        'visibility':'gm','expiry':'source_rule'}}]})
    mid=saved['map_id']
    assert CombatService(ROOT,tmp_path).tabletop_maps.get(mid)==saved
    bad=deepcopy(saved);bad['objects'][0]['asset_declaration']['object_id']=2
    with pytest.raises(ValueError,match='actual map object'):
        c.tabletop_maps.save(bad)
    assert CombatService(ROOT,tmp_path).tabletop_maps.get(mid)==saved


@pytest.mark.parametrize('remaining',[1,3])
def test_acquired_wind_remainder_uses_the_first_recognized_native_slot(tmp_path,acquired_sheet,remaining):
    from combat.gate5_service import CombatService
    c,jid=game(tmp_path,acquired_sheet,journey=True)
    for kind,payload in [('cloud_wind_begin',{}),('wait',{'seconds':600}),
                         ('cloud_wind_finish',{}),('wait',{'seconds':3600-remaining})]:
        state=c.journey_state(jid);c.journey_act(jid,state['revision'],A,kind,payload)
    state=c.journey_state(jid)
    result=c.journey_start_combat(jid,state['revision'],{A:'team:a','actor:factory.companion':'team:b'})
    e=verify(tmp_path,result['match_id'])
    held=next(v for v in e.state.actors[A].conditions.values() if v.condition_id=='condition:typed.cloud_walker_form')
    assert (held.data['remaining_num'],held.data['remaining_den'])==(remaining,1)
    count=len(e.state.initiative_order)
    assert held.data['clock_slots']==count
    prefix,end_round,end_slot=held.expires_on.split(':')
    assert prefix=='START_OF_SLOT_AT'
    current=(e.state.round_number-1)*count+e.state.current_slot_index
    deadline=(int(end_round)-1)*count+int(end_slot)
    ticks=deadline-current
    assert ticks*6>=remaining*count and (ticks-1)*6<remaining*count
