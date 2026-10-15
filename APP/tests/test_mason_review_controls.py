"""Accepted table choices and reconstruction against current native volumes."""
from tests.mason_native_support import *
from tests.test_mason_review_journey import build_payload


@pytest.mark.parametrize('auto_turn',[False,True])
def test_table_elevated_advance_commits_the_willing_creatures_choice(tmp_path,auto_turn):
    combat,table,mid,send,commit=fixture(tmp_path)
    commit(at(table,mid,'Raise Barrier: Platform',4,4))
    recipient=s.OWNER if auto_turn else s.SECOND
    if recipient!=s.OWNER:
        commit(table.state(mid)['menu']['end_turn'])
        while table.state(mid)['menu']['actor_id']!=recipient:commit(table.state(mid)['menu']['end_turn'])
    candidates=combat._legal_candidates(combat._load_session(mid))
    climb=next(c for c in candidates if c.kind=='MOVE' and c.destination is not None and
        (c.destination.x,c.destination.y,c.destination.z)==(4 if recipient==s.OWNER else 5,5,2))
    commit(climb.candidate_id)
    if recipient==s.OWNER:next_owner(table,mid,commit)
    else:
        commit(table.state(mid)['menu']['end_turn'])
        while table.state(mid)['menu']['actor_id']!=s.OWNER:commit(table.state(mid)['menu']['end_turn'])
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',7,8))
    before=cold(tmp_path,mid)
    from combat.ext.granted_movement import choices
    dest=(5 if recipient==s.OWNER else 4,5,2)
    route=next(c for c in choices(before,before.state.actors[recipient],15)
        if (c.destination.x,c.destination.y,c.destination.z)==dest)
    budget=before.state.actors[recipient].movement_remaining_ft
    if auto_turn:
        from combat.gate4_adapters import ManualControllerAdapter
        real=combat.controller
        class EndController:
            def choose_primary_action(self,context):
                cid=table.state(mid)['menu']['end_turn']
                return ManualControllerAdapter(lambda _:(cid,())).choose_primary_action(context)
            def __getattr__(self,name):return getattr(real,name)
        combat.controller=EndController()
        for aid in (s.FOE,s.SECOND):combat.set_controller_mode(mid,actor_id=aid,controller_mode='LOCAL_AUTO')
    prompts=[]
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id']!=s.OWNER:
        cid=table.state(mid)['menu']['end_turn'];answers=[]
        for _ in range(32):
            result=table.auto_step(mid,0,answers) if auto_turn else send(cid,answers)
            if result['status']=='COMMITTED':break
            assert result['status']=='REACTION_REQUIRED',result
            prompt=result['reaction'];prompts.append(prompt)
            answer={**prompt['context'],'selection':'DECLINE'}
            if prompt.get('choice'):
                source=prompt['context']['reaction_source_id']
                selected={'choice:needle.mason_command':'Covered Advance',
                    'choice:needle.mason_command_ally':recipient,
                    'choice:needle.mason_free_step_'+recipient:route.candidate_id}.get(source)
                answer.update(selection='USE',option_ids=[selected] if selected else
                    (prompt['choice'].get('preferred') or [prompt['choice']['options'][0]['id']])[:1])
            answers.append(answer)
        else:raise AssertionError('command did not commit')
    after=cold(tmp_path,mid)
    assert (after.state.actors[recipient].position.x,after.state.actors[recipient].position.y,after.state.actors[recipient].position.z)==dest
    if recipient!=s.OWNER:assert after.state.actors[recipient].movement_remaining_ft==budget
    assert any(p['context']['reactor_id']==recipient and 'accept Covered Advance' in p.get('moment','') for p in prompts)


def test_journey_reconstruction_rechecks_occupied_space_and_live_source(tmp_path):
    combat,table,mid,send,commit=fixture(tmp_path,damage=200)
    engine=cold(tmp_path,mid)
    j=combat.journeys.create(engine.typed_bundle_documents,engine.battlefield_document,
        {aid:a.position.model_dump(mode='json') for aid,a in engine.state.actors.items()},
        {aid:3000 for aid in engine.state.actors})
    jid=j['journey_id'];payload=build_payload('raise_barrier','Low Wall',3,5)
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    oid=next(iter(state['runtime_objects']))
    result=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'},maximum_rounds=1)
    mid=result['match_id']
    from combat.tabletop_service import TabletopService
    table=TabletopService(combat,tmp_path)
    while table.state(mid)['menu']['actor_id']!=s.OWNER:
        commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    # Decline Intervention while the real object-damage action destroys it.
    cid=s.candidate(table,mid,'Damage a structure',oid);answers=[]
    for _ in range(16):
        menu=table.state(mid)['menu'];result=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED'
        answers.append({**result['reaction']['context'],'selection':'DECLINE'})
    assert cold(tmp_path,mid).state.objects[oid].destroyed
    for _ in range(12):
        if cold(tmp_path,mid).state.terminal_result is not None:break
        commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    current=combat.journey_state(jid);state=combat.journey_resume(jid,current['revision'])
    state=combat.journey_act(jid,state['revision'],s.SECOND,'move',{'path':[{'x':4,'y':5},{'x':3,'y':5}]})
    repair={'object_id':oid,'material_source':payload['sections'][0]['material_source'],'sufficient_material':True}
    with pytest.raises(ValueError):combat.journey_act(jid,state['revision'],s.OWNER,'mason_repair',repair)
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    state=combat.journey_act(jid,state['revision'],s.SECOND,'move',{'path':[{'x':4,'y':5}]})
    state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_repair',repair)
    assert not state['runtime_objects'][oid]['destroyed'] and state['runtime_objects'][oid]['current_hp']>0
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    bound=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'})
    restored=cold(tmp_path,bound['match_id']).state.objects[oid]
    assert not restored.destroyed and restored.current_hp==state['runtime_objects'][oid]['current_hp']


