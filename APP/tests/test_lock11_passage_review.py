"""Compulsory passage recovery never adds to willing movement thresholds."""
import pytest
from combat import motion
from combat.gate2_runtime_models import Position
from tests.test_lock9_passage_review import table,send,checked,hook,OWNER,FOE
from tests.test_lock8_passage import CLOUD,LIQUID


@pytest.mark.parametrize('feature,cost',[(CLOUD,5),(LIQUID,10)])
def test_table_afterimage_counts_entry_but_not_compulsory_return(monkeypatch,tmp_path,feature,cost):
    service,ui,mid=table(tmp_path,feature,extra_features=['TAL_ATHLETICS_AFTERIMAGE'],start=(0,6))
    e=service._load_session(mid).engine
    c=next(c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=3,y=6))
    assert send(service,ui,mid,c)['status']=='COMMITTED'
    e=checked(tmp_path,mid); a=e.state.actors[OWNER]
    assert a.turn_flags['moved_ft']==15 and not motion.has_afterimage(a)
    before=a.movement_remaining_ft
    def stop(engine,mover,occupant,intent):
        if mover.entity_id==OWNER:
            engine._apply_condition(mover,'condition:typed.pinned','test:pin',FOE,expires_on='UNTIL_REMOVED')
    hook(monkeypatch,'pass_through_entered',stop)
    c=next(c for c in e.legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=5,y=6))
    assert send(service,ui,mid,c)['status']=='COMMITTED'
    e=checked(tmp_path,mid); a=e.state.actors[OWNER]
    movement=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==OWNER)
    assert movement.payload['path']==[{'x':3,'y':6},{'x':4,'y':6},{'x':3,'y':6}]
    assert movement.payload['cost_ft']==cost and a.movement_remaining_ft==before-cost
    assert movement.payload['interrupted'] and a.position==Position(x=3,y=6)
    assert a.turn_flags['moved_ft']==20 and not motion.has_afterimage(a)
