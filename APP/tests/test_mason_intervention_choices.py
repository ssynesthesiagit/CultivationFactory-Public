"""Optional Intervention movement is the adjacent creature's native decision."""
from tests.mason_native_support import *


@pytest.mark.parametrize('accept',[False,True])
def test_zero_damage_intervention_offers_adjacent_creatures_own_step(tmp_path,accept):
    combat,table,mid,send,commit=fixture(tmp_path,damage=8)
    commit(at(table,mid,'Raise Barrier: Low Wall',4,5))
    oid=works(cold(tmp_path,mid))[0].object_id
    next_owner(table,mid,commit)
    before=cold(tmp_path,mid);ally=before.state.actors[s.SECOND].position
    qi=before.state.actors[s.OWNER].resources['resource:core.qi']
    cid=s.candidate(table,mid,'Damage a structure',oid);answers=[];asked=False
    for _ in range(32):
        result=send(cid,answers)
        if result['status']=='COMMITTED':break
        assert result['status']=='REACTION_REQUIRED',result
        prompt=result['reaction'];context=prompt['context'];source=context['reaction_source_id']
        answer={**context,'selection':'DECLINE'}
        if source=='choice:needle.mason_intervention':answer.update(selection='USE',option_ids=['protect'])
        elif source=='choice:needle.mason_intervention_step':answer.update(selection='USE',option_ids=[s.SECOND])
        elif source=='choice:needle.mason_free_step_'+s.SECOND:
            asked=True
            assert context['reactor_id']==s.SECOND
            if accept:answer.update(selection='USE',option_ids=[prompt['choice']['options'][0]['id']])
        elif prompt.get('choice'):
            answer.update(selection='USE',option_ids=(prompt['choice'].get('preferred') or [prompt['choice']['options'][0]['id']])[:1])
        answers.append(answer)
    else:raise AssertionError('Intervention did not commit')
    after=cold(tmp_path,mid)
    assert asked
    assert after.state.objects[oid].current_hp==before.state.objects[oid].current_hp
    assert after.state.actors[s.OWNER].resources['resource:core.qi']==qi-2
    assert not after.state.actors[s.OWNER].reaction_available
    moved=after.state.actors[s.SECOND].position
    assert after.grid.distance_ft(ally,moved)==(5 if accept else 0)
    lingering='mason_trigger_protection' in after.state.objects[oid].component
    # A later, explicitly declined response cannot borrow the earlier receipt.
    next_owner(table,mid,commit)
    commit(s.candidate(table,mid,'Damage a structure',oid),decline=('choice:needle.mason_intervention',))
    assert cold(tmp_path,mid).state.objects[oid].current_hp==64
    assert not lingering, 'the completed trigger must release its protection receipt'
