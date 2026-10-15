"""Native cylinder placement and fixed-duration continuation boundaries."""
from tests.mason_native_support import *


@pytest.mark.parametrize('center,section',[((3,6),(6,8)),((21,6),(28,6))])
def test_bastion_center_is_independent_of_its_first_supported_section(tmp_path,center,section):
    combat,table,mid,send,commit=fixture(tmp_path)
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    commit(at(table,mid,'Raise the Imperial Bastion: Raise Sections',*center),picks={
        'choice:needle.mason_space_0':cell_id(Position(x=section[0],y=section[1])),
        'choice:needle.mason_allies':s.OWNER})
    engine=cold(tmp_path,mid);obj=works(engine)[0]
    assert (obj.position.x,obj.position.y)==section
    condition=next(c for c in engine.state.actors[s.OWNER].conditions.values() if c.condition_id=='condition:typed.mason_bastion')
    assert condition.data['center']=={'x':center[0],'y':center[1],'z':0}
    assert condition.data['chosen_allies']==[s.OWNER]
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==22


def test_journey_explicit_cylinder_center_allows_its_full_far_edge(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    payload=journey_wall_payload();payload.update(source=BASE+'raise_the_imperial_bastion',form='Raise Sections',
        chosen_allies=[s.OWNER],center={'x':21,'y':6})
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    payload['sections'][0].update(position={'x':28,'y':6},material_source='terrain:'+cell_id(Position(x=28,y=6)))
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    obj=next(iter(state['runtime_objects'].values()))
    assert obj['position']=={'x':28,'y':6,'z':0}
    assert obj['component']['asset_anchor_runtime']['center']=={'x':21,'y':6,'z':0}
    assert state['actors'][s.OWNER]['resources']['resource:core.qi']==22
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state


def test_fixed_bastion_remainder_imports_at_the_exact_native_slot(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    payload=journey_wall_payload();payload.update(source=BASE+'raise_the_imperial_bastion',form='Raise Sections',chosen_allies=[s.OWNER])
    state=combat.journey_act(jid,j['revision'],s.OWNER,'mason_build',payload)
    state=combat.journey_act(jid,state['revision'],s.OWNER,'wait',{'seconds':2})
    started=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'})
    engine=cold(tmp_path,started['match_id'])
    condition=next(c for c in engine.state.actors[s.OWNER].conditions.values() if c.condition_id=='condition:typed.mason_bastion')
    _,round_number,slot=condition.expires_on.split(':');slots=len(engine.state.initiative_order)
    ticks=(int(round_number)-engine.state.round_number)*slots+int(slot)-engine.state.current_slot_index
    assert ticks*6==58*slots, 'a 58-second remainder must not grow to a full 60-second round count'
    assert engine.state.actors[s.OWNER].resources['resource:core.qi']==22


def test_bastion_first_raised_in_encounter_exports_real_center_allies_and_clock(tmp_path):
    combat,j=journey_fixture(tmp_path);jid=j['journey_id']
    started=combat.journey_start_combat(jid,j['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'},maximum_rounds=1)
    mid=started['match_id']
    from combat.tabletop_service import TabletopService
    table=TabletopService(combat,tmp_path)
    while table.state(mid)['menu']['actor_id']!=s.OWNER:commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    cid=s.candidate(table,mid,'Raise the Imperial Bastion: Raise Sections');answers=[]
    from combat.placement_menu import CHOICE
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    for _ in range(64):
        menu=table.state(mid)['menu'];r=table.act(mid,cid,menu['decision_id'],menu['state_version'],0,answers)
        if r['status']=='COMMITTED':break
        assert r['status']=='REACTION_REQUIRED',r
        p=r['reaction'];answer={**p['context'],'selection':'DECLINE'}
        if p.get('choice'):
            source=p['context']['reaction_source_id']
            chosen=cell_id(Position(x=6,y=8),include_altitude=True) if source==CHOICE else s.OWNER if source=='choice:needle.mason_allies' else None
            answer.update(selection='USE',option_ids=[chosen] if chosen else (p['choice'].get('preferred') or [p['choice']['options'][0]['id']])[:1])
        answers.append(answer)
    else:raise AssertionError('Bastion did not commit')
    for _ in range(12):
        if cold(tmp_path,mid).state.terminal_result is not None:break
        commit_other_table(table,mid,table.state(mid)['menu']['end_turn'])
    assert cold(tmp_path,mid).state.terminal_result is not None
    state=combat.journey_state(jid);state=combat.journey_resume(jid,state['revision'])
    obj=next(o for o in state['runtime_objects'].values() if not o['destroyed'])
    marker=obj['component']['asset_anchor_runtime']
    assert marker['center']=={'x':6,'y':8,'z':0} and marker['chosen_allies']==[s.OWNER]
    assert state['actors'][s.OWNER]['resources']['resource:core.qi']==22
    assert CombatService(ROOT,tmp_path).journey_state(jid)==state
    second=combat.journey_start_combat(jid,state['revision'],{s.OWNER:'team:a',s.FOE:'team:b',s.SECOND:'team:a'})
    engine=cold(tmp_path,second['match_id'])
    active=next(c for c in engine.state.actors[s.OWNER].conditions.values() if c.condition_id=='condition:typed.mason_bastion')
    assert active.data['center']==marker['center'] and active.data['chosen_allies']==[s.OWNER]
    assert engine.state.actors[s.OWNER].concentration is not None
