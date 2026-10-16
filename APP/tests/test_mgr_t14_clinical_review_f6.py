"""Paid clinical work crosses an immutable terminal fight and cold re-entry."""
import pytest
from tests.test_mgr_t14_clinical_native import (
    B, start, engine, use, turn, act, final_native_mechanical_replay,
)
from tests.test_mgr_t14_clinical_review_f5 import scenario, finish
from tests.test_mgr_t14_clinical_review_f4 import conditions
from combat.ext.clinical_procedures import PROGRESS


@pytest.mark.parametrize('skip_first_round',[False,True],ids=['continue-paid-work','skip-interrupts'])
def test_paid_work_rebases_only_at_journey_boundary(tmp_path,monkeypatch,skip_first_round):
    cold,table,jid,command,mid,patient,healer,_,group=scenario(
        tmp_path,monkeypatch,treatment_seconds=18)
    while True:
        state=turn(cold,table,mid,patient)
        if engine(cold,mid).state.round_number>=5:break
        act(cold,table,mid,state,state['menu']['end_turn'],lambda p,ids:[])
    before=engine(cold,mid).state.actors[patient].resources['resource:core.qi']
    use(cold,table,mid,'Begin Medicine treatment',aid=patient,target=patient)
    paid=engine(cold,mid).state.actors[patient]
    progress=next(c for c in paid.conditions.values() if c.condition_id==PROGRESS)
    assert progress.data['last_round']==5 and progress.data['remaining_steps']==2
    assert paid.resources['resource:core.qi']==before-1
    resumed=finish(cold,table,jid,mid,patient)
    carried=next(c for c in conditions(resumed,patient) if c['condition_id']==PROGRESS)
    assert carried['data']['last_round']==0 and carried['data']['remaining_steps']==2
    original=next(c for c in engine(cold,mid).state.actors[patient].conditions.values() if c.condition_id==PROGRESS)
    assert original.data==progress.data
    second=start(cold,jid,teams={patient:'team:a',healer:'team:b',B:'team:a'})
    state=turn(cold,table,second,patient)
    assert engine(cold,second).state.round_number==1
    assert any(g['label']=='Continue Medicine treatment' for g in state['menu']['actions'])
    assert not any(g['label']=='Begin Medicine treatment' for g in state['menu']['actions'])
    if skip_first_round:
        act(cold,table,second,state,state['menu']['end_turn'],lambda p,ids:[])
        state=turn(cold,table,second,patient)
        e=engine(cold,second)
        assert not any(c.condition_id==PROGRESS for c in e.state.actors[patient].conditions.values())
        assert any(g['label']=='Begin Medicine treatment' for g in state['menu']['actions'])
        assert any('a round passed without an Action' in v.payload.get('log','') for v in e.events)
    else:
        use(cold,table,second,'Continue Medicine treatment',aid=patient,target=patient)
        e=engine(cold,second)
        left=next(c for c in e.state.actors[patient].conditions.values() if c.condition_id==PROGRESS)
        assert left.data['last_round']==1 and left.data['remaining_steps']==1
        state=turn(cold,table,second,patient)
        assert not any(g['label']=='Continue Medicine treatment' for g in state['menu']['actions'])
        act(cold,table,second,state,state['menu']['end_turn'],lambda p,ids:[])
        use(cold,table,second,'Continue Medicine treatment',aid=patient,target=patient)
        e=engine(cold,second)
        assert not any(c.condition_id==PROGRESS for c in e.state.actors[patient].conditions.values())
        assert not any((c.data.get('clinical') or c.data.get('clinical_retained_source') or {}).get('source_instance')==group
                       for c in e.state.actors[patient].conditions.values())
    assert engine(cold,second).state.actors[patient].resources['resource:core.qi']==before-1
