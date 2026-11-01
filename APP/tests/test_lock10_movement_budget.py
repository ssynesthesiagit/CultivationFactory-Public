"""DS3-080's cost transition: a reaction makes the mover start dragging."""
import pytest
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate5_service import CombatService
from tests import lock8_support as S
from tests.test_lock_choices import install
from tests.test_lock8_movement_steps import candidate, use, portable
from tests.h1_support import ROOT


def drag_reaction(monkeypatch,mover_id,held_id):
    def react(engine,mover,previous,nxt,intent):
        if mover.entity_id!=mover_id:return
        held=engine.state.actors[held_id]
        if any(c.condition_id=='condition:typed.grappled' for c in held.conditions.values()):return
        engine._apply_condition(held,'condition:typed.grappled','test:midmove_reaction',mover.entity_id,
            expires_on='UNTIL_REMOVED',data={'reach_ft':5})
        engine._append_event('REACTION_RESOLVED','test:midmove_reaction',actor_id=held_id,target_ids=(mover_id,),
            payload={'checkpoint':'LEAVE_REACH','result':'The mover now drags the held creature.'})
    install(monkeypatch,'movement_attempt',react)


@pytest.mark.parametrize('granted',[False,True])
def test_new_drag_cost_stops_accepted_move_without_abort(monkeypatch,granted):
    e=S.fight(S.bundle('SAND_BASE_SCOURING_HAND'),foe_at=(4,7))
    e.grid.blocked.clear();e.grid.opaque.clear();e.grid.qi_hazard.clear()
    e._wall_base=(frozenset(),frozenset(),frozenset(),{})
    mover=e.state.actors[S.ME]
    c=candidate(e,9)
    assert c.movement_cost_ft==30
    drag_reaction(monkeypatch,S.ME,S.FOE)
    if granted:
        intent=ActionIntent(intent_id='test:grant',decision_id=c.decision_id,candidate_id=c.candidate_id,
            state_version=c.state_version,actor_id=mover.entity_id,destination=c.destination)
        assert e.grant_movement(mover,c.canonical_path,'test:grant',feet=30,intent=intent,provokes=False)==30
    else:use(e,c)
    assert mover.position==Position(x=6,y=6)
    assert mover.movement_remaining_ft==(30 if granted else 0)
    receipt=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==S.ME)
    assert receipt.payload['interrupted'] and len(receipt.payload['path'])==4
    assert receipt.payload['granted_cost_ft' if granted else 'cost_ft']==30
    assert any(c.condition_id=='condition:typed.grappled' for c in e.state.actors[S.FOE].conditions.values())


def test_table_drag_reaction_commits_shortened_path_and_replays(tmp_path,monkeypatch):
    combat,table,mid,left,right=portable(tmp_path,'SAND_BASE_SCOURING_HAND','SAND_BASE_SCOURING_HAND',
                                      left_at=(3,6),right_at=(4,7))
    drag_reaction(monkeypatch,left,right)
    e=combat._load_session(mid).engine
    c=candidate(e,9)
    assert c.movement_cost_ft==30
    from tests.r10_fixup_support import commit
    sequence=table.state(mid)['last_sequence']
    commit(lambda answers: table.act(mid,c.candidate_id,c.decision_id,c.state_version,sequence,answers))
    loaded=CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[left].position==Position(x=6,y=6)
    assert loaded.engine.state.actors[left].movement_remaining_ft==0
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'
