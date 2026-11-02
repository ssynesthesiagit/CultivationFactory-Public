"""Native collision stops also cover changes during leave-reach reactions."""
import pytest
from combat.gate2_runtime_models import Position
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.history_feed import format_history_feed
from tests.h1_support import ROOT
from tests.test_hunt33_contact import contact_table, MOVER, BLOCKER


@pytest.mark.parametrize('blocker_at',[(4,3),(4,2),(3,3)])
@pytest.mark.parametrize('invisible',[False,True])
def test_reaction_time_obstruction_stops_before_payment_and_records_contact(
        monkeypatch,tmp_path,blocker_at,invisible):
    service,table,mid=contact_table(tmp_path,monkeypatch,'L9-REACTION-COLLISION',(3,2),(10,2),False)
    engine=service._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=4,y=3))
    before=engine.state.actors[MOVER].movement_remaining_ft
    original=Gate4ControllerEngine._resolve_leave_reach
    # Model an evented reaction displacement at the real leave-reach boundary.
    # No candidate/step/collision function is replaced by this fixture.
    def displace(e,mover,previous,nxt,intent,**kwargs):
        original(e,mover,previous,nxt,intent,**kwargs)
        if mover.entity_id!=MOVER:return
        blocker=e.state.actors[BLOCKER]
        if not invisible:e._remove_condition(blocker,'condition:typed.invisible','test:reveal')
        old=blocker.position;blocker.position=Position(x=blocker_at[0],y=blocker_at[1])
        e._append_event('MOVEMENT_COMMITTED','test:reaction-step',actor_id=BLOCKER,
            payload={'destination':blocker.position.model_dump(mode='json'),
                'path':[old.model_dump(mode='json'),blocker.position.model_dump(mode='json')],'cost_ft':0})
    monkeypatch.setattr(Gate4ControllerEngine,'_resolve_leave_reach',displace)
    assert table.act(mid,c.candidate_id,c.decision_id,c.state_version,table.state(mid)['last_sequence'])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid);e=loaded.engine;a=e.state.actors[MOVER]
    assert a.position==Position(x=3,y=2) and a.movement_remaining_ft==before
    event=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==MOVER)
    assert event.payload['interrupted'] and event.payload['cost_ft']==0
    assert event.payload['path']==[{'x':3,'y':2}]
    if invisible:
        assert a.turn_flags['unseen_contact_cells']==[{'x':blocker_at[0],'y':blocker_at[1]}]
        assert e.state.observations[a.team_id][BLOCKER]==e.state.actors[BLOCKER].position
    assert not any(row.kind=='MOVE' and row.canonical_path==c.canonical_path for row in e.legal_candidates())
    feed=format_history_feed([ev.model_dump(mode='json') for ev in e.events],
        [r.model_dump(mode='json') for r in e.rolls],pre_state=None,post_state=e.state.model_dump(mode='json'),
        actor_names={k:v.display_name for k,v in e.state.actors.items()},
        definition_names={k:v.display_name for k,v in e.action_catalog.items()})
    notices=[row['summary'] for row in feed if 'Movement stopped' in row['summary']]
    assert notices and all('Not automated' not in text and 'skipped' not in text for text in notices)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_contact_includes_full_diagonal_side_footprint_but_not_uncontacted_cells(tmp_path,monkeypatch):
    from combat.footprints import ActorFootprintDefinition
    from combat.target_knowledge import movement_contact
    service,_,mid=contact_table(tmp_path,monkeypatch,'L9-LARGE-CONTACT',(3,2),(5,2),False)
    e=service._load_session(mid).engine;a=e.state.actors[MOVER]
    e.actor_footprints[MOVER]=ActorFootprintDefinition.rectangle(2,2,
        footprint_id='footprint:test.large',source_definition_id='test:large')
    e.actor_footprints[BLOCKER]=ActorFootprintDefinition.rectangle(2,1,
        footprint_id='footprint:test.wide',source_definition_id='test:wide')
    assert not e.grid.step_legal(a.position,Position(x=4,y=3),
        occupied_cells=e._occupied_cells_except(MOVER),footprint=e._footprint(a))
    assert movement_contact(e,a,Position(x=4,y=3))
    assert a.turn_flags['unseen_contact_cells']==[{'x':5,'y':2}]


def test_contact_does_not_locate_a_shared_occupancy_partner(tmp_path,monkeypatch):
    from combat.footprints import ActorFootprintDefinition
    from combat.target_knowledge import movement_contact
    from tests.test_lock_choices import install
    service,_,mid=contact_table(tmp_path,monkeypatch,'L9-SHARED-CONTACT',(3,2),(4,2),False)
    e=service._load_session(mid).engine;a=e.state.actors[MOVER]
    e.actor_footprints[BLOCKER]=ActorFootprintDefinition.rectangle(2,2,
        footprint_id='footprint:test.mount',source_definition_id='test:mount')
    install(monkeypatch,'shared_occupancy',lambda *args:{'rider_id':MOVER,'mount_id':BLOCKER})
    assert not movement_contact(e,a,Position(x=4,y=2))
    assert not a.turn_flags.get('unseen_contact_cells')
