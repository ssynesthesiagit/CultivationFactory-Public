"""Native negative/boundary regressions for the four Mason review findings."""
from tests.mason_native_support import *
from tests.test_mason_review_journey import build_payload


@pytest.mark.parametrize('source,form,heights',[
    ('raise_barrier','Ramp',[5,10,10]),
    ('bridge_the_impossible','Ascending Stair',[5,10,15,15,20,25,30,30]),
])
def test_sloped_work_supports_only_its_actual_walking_planes(tmp_path,source,form,heights):
    from combat.falling import supported,required,landing
    from combat.gate2_runtime_models import Position
    combat,table,mid,send,commit=fixture(tmp_path)
    label=('Raise Barrier: ' if source=='raise_barrier' else 'Bridge the Impossible: ')+form
    commit(at(table,mid,label,6,8))
    engine=cold(tmp_path,mid);actor=engine.state.actors[s.OWNER]
    air=Position(x=6,y=8,z=heights[-1]//5)
    low=Position(x=6,y=8,z=heights[0]//5)
    assert supported(engine,actor,low)
    assert not supported(engine,actor,air), 'bounding height must not support empty air above the low end'
    falling_actor=actor.model_copy(update={'position':air,'climbing':False})
    assert required(engine,falling_actor)
    assert landing(engine,falling_actor)==low
    # Keep the ordinary ascent reachable through actual table movement commits.
    for destination in [(5,8,0),*[(6+i,8,h//5) for i,h in enumerate(heights)]]:
        def route():
            return next((c for c in combat._legal_candidates(combat._load_session(mid))
                if c.kind=='MOVE' and c.destination is not None and
                (c.destination.x,c.destination.y,c.destination.z)==destination),None)
        candidate=route()
        if candidate is None:
            next_owner(table,mid,commit);candidate=route()
        assert candidate is not None,('ordinary ascent missing',destination)
        commit(candidate.candidate_id)
        assert cold(tmp_path,mid).state.actors[s.OWNER].position==Position(x=destination[0],y=destination[1],z=destination[2])
    # A native horizontal climbing step cannot cross into air above a lower step.
    from combat.roof_movement import step_allowed
    engine=cold(tmp_path,mid);actor=engine.state.actors[s.OWNER]
    previous=Position(x=7,y=8,z=heights[-1]//5)
    assert not step_allowed(engine,actor,previous,air)


@pytest.mark.parametrize('operation',['barrier','greater','bastion','repair','reinforce'])
def test_incapacitated_journey_mason_commands_reject_atomically(tmp_path,operation):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    wall=build_payload('raise_barrier','Low Wall',4,5)
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',wall)
    oid=next(iter(state['runtime_objects']))
    if operation=='bastion':
        state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',build_payload(
            'raise_the_imperial_bastion','Low Wall',7,8))
    state=combat.journey_act(jid,state['revision'],s.OWNER,'incapacitated',{'value':True})
    if operation=='bastion':
        assert all(o['destroyed'] for o in state['runtime_objects'].values()
            if o['component']['mason']['feature']==BASE+'raise_the_imperial_bastion')
    kind,payload={
        'barrier':('mason_build',build_payload('raise_barrier','Low Wall',6,8)),
        'greater':('mason_build',build_payload('bridge_the_impossible','Ascending Stair',6,8,
            length_ft=10,width_ft=10,height_ft=10)),
        'bastion':('mason_build',build_payload('raise_the_imperial_bastion','Low Wall',6,8)),
        'repair':('mason_repair',{'object_id':oid,'material_source':wall['sections'][0]['material_source']}),
        'reinforce':('mason_reinforce',{'object_id':oid}),
    }[operation]
    with pytest.raises(ValueError,match='incapacitated'):
        combat.journey_act(jid,state['revision'],s.OWNER,kind,payload)
    # This includes revision, events, clock, resources, source use and objects.
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


@pytest.mark.parametrize('effect',['reinforce','brace'])
def test_imported_two_second_buff_expires_at_first_native_slot(tmp_path,effect):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',build_payload('raise_barrier','Low Wall',4,5))
    oid=next(iter(state['runtime_objects']))
    if effect=='reinforce':
        state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_reinforce',{'object_id':oid})
        condition_id='condition:typed.mason_reinforcement';recipient=s.OWNER
    else:
        state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_build',build_payload(
            'raise_the_imperial_bastion','Low Wall',7,8))
        state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':6})
        state=combat.journey_act(jid,state['revision'],s.OWNER,'mason_command',{
            'command':'Brace the Defender','ally_id':s.SECOND})
        condition_id='condition:typed.mason_brace';recipient=s.SECOND
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':4})
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    result=combat.journey_start_combat(jid,state['revision'],{
        s.OWNER:'team:a',s.SECOND:'team:a',s.FOE:'team:b'})
    mid=result['match_id']
    from combat.tabletop_service import TabletopService
    table=TabletopService(combat,tmp_path)
    engine=cold(tmp_path,mid)
    assert len(engine.state.initiative_order)==3
    condition=next(c for c in engine.state.actors[recipient].conditions.values() if c.condition_id==condition_id)
    if effect=='reinforce':
        assert (engine.state.objects[oid].ac,engine.state.objects[oid].damage_threshold)==(17,8)
    # One native slot in a three-actor fight is exactly the two seconds left.
    # Decline new commands so the expiry assertion cannot be masked by a refresh.
    answers=[];cid=table.state(mid)['menu']['end_turn']
    for _ in range(32):
        menu=table.state(mid)['menu']
        reply=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        if reply['status']=='COMMITTED':break
        assert reply['status']=='REACTION_REQUIRED',reply
        prompt=reply['reaction'];answer={**prompt['context'],'selection':'DECLINE'}
        if prompt['context']['reaction_source_id']=='choice:needle.mason_command':
            answer.update(selection='USE',option_ids=['Reconfigure'])
        answers.append(answer)
    else:raise AssertionError('native end turn did not commit')
    engine=cold(tmp_path,mid)
    assert condition.instance_id not in engine.state.actors[recipient].conditions
    if effect=='reinforce':
        assert (engine.state.objects[oid].ac,engine.state.objects[oid].damage_threshold)==(15,4)
        assert 'mason_reinforcement' not in engine.state.objects[oid].component
