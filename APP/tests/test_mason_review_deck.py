"""Native touch range on a committed elevated construction surface."""
from tests.mason_native_support import *
from tests.test_mason_review_journey import build_payload


def test_journey_repair_can_touch_the_deck_after_real_encounter_damage(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,damage=20)
    engine=cold(tmp_path,mid)
    j=combat.journeys.create(engine.typed_bundle_documents,engine.battlefield_document,
        {aid:a.position.model_dump(mode='json') for aid,a in engine.state.actors.items()},
        {aid:3000 for aid in engine.state.actors})
    jid=j['journey_id'];payload=build_payload('raise_barrier','Platform',4,4,length_ft=10,width_ft=10,height_ft=10)
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    oid=next(iter(state['runtime_objects']))
    state=combat.journey_act(jid,state['revision'],s.OWNER,'move',{'path':[
        {'x':4,'y':5,'z':1},{'x':4,'y':5,'z':2}]})
    result=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'},maximum_rounds=1)
    mid=result['match_id']
    from combat.tabletop_service import TabletopService
    table=TabletopService(combat,tmp_path)
    while table.state(mid)['menu']['actor_id']!=s.OWNER:
        commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    cid=s.candidate(table,mid,'Damage a structure',oid);answers=[]
    for _ in range(16):
        menu=table.state(mid)['menu'];result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED'
        answers.append({**result['reaction']['context'],'selection':'DECLINE'})
    assert cold(tmp_path,mid).state.objects[oid].current_hp==52
    for _ in range(12):
        if cold(tmp_path,mid).state.terminal_result is not None:break
        commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    current=combat.journey_state(jid);state=combat.journey_resume(jid,current['revision'])
    assert state['actors'][s.OWNER]['position']['z']==2
    assert any(o['id']=='mason_repair:'+oid for o in combat.journey_menu(jid,s.OWNER)['options'])
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_repair',{
        'object_id':oid,'material_source':payload['sections'][0]['material_source']})
    assert 52<state['runtime_objects'][oid]['current_hp']<=72
    bound=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'})
    assert cold(tmp_path,bound['match_id']).state.objects[oid].current_hp==state['runtime_objects'][oid]['current_hp']
