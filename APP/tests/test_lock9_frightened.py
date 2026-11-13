"""Native Frightened checks visibility and every step at query and commit time."""
import pytest
from combat import ext
from combat.gate2_runtime_models import Position
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.target_knowledge import can_see
from combat.voluntary_movement import path_allowed
from tests.h1_support import ROOT
from tests.test_hunt33_frightened import fear_table, ME, FOE


@pytest.mark.parametrize('change',['fear_after_reaction','fear_after_step','sight_after_reaction'])
def test_new_fear_or_sight_stops_accepted_move_without_charging_forbidden_step(monkeypatch,tmp_path,change):
    service,table,mid=fear_table(tmp_path,monkeypatch,
        frightened=change=='sight_after_reaction',invisible=change=='sight_after_reaction')
    engine=service._load_session(mid).engine
    c=next(c for c in engine.legal_candidates() if c.kind=='MOVE' and c.destination==Position(x=6,y=6))
    budget=engine.state.actors[ME].movement_remaining_ft
    def change_state(e,actor):
        if actor.entity_id!=ME:return
        if change=='sight_after_reaction':
            e._remove_condition(e.state.actors[FOE],'condition:typed.invisible','test:reveal')
        else:
            e._apply_condition(actor,'condition:typed.frightened','test:new-fear',FOE,expires_on='UNTIL_REMOVED')
    if change=='fear_after_step':
        original=Gate4ControllerEngine._resolve_zone_entry_triggers
        def entry(e,actor):
            original(e,actor);change_state(e,actor)
        monkeypatch.setattr(Gate4ControllerEngine,'_resolve_zone_entry_triggers',entry)
    else:
        original=Gate4ControllerEngine._resolve_leave_reach
        def react(e,actor,previous,nxt,intent,**kwargs):
            original(e,actor,previous,nxt,intent,**kwargs);change_state(e,actor)
        monkeypatch.setattr(Gate4ControllerEngine,'_resolve_leave_reach',react)
    assert table.act(mid,c.candidate_id,c.decision_id,c.state_version,table.state(mid)['last_sequence'])['status']=='COMMITTED'
    loaded=CombatService(ROOT,tmp_path)._load_session(mid);e=loaded.engine;a=e.state.actors[ME]
    moved=change=='fear_after_step'
    assert a.position==Position(x=4 if moved else 3,y=6)
    assert a.movement_remaining_ft==budget-(5 if moved else 0)
    event=next(ev for ev in reversed(e.events) if ev.event_type=='MOVEMENT_COMMITTED' and ev.actor_id==ME)
    assert event.payload['interrupted'] and event.payload['cost_ft']==(5 if moved else 0)
    assert any(ev.event_type=='PASSIVE_TRIGGERED' and 'Frightened prevents a step closer' in ev.payload.get('log','') for ev in e.events)
    assert loaded.verify()['status']==loaded.mechanical.replay()['status']=='PASS'


def test_retreat_then_approach_is_not_legal_just_because_it_ends_at_start(monkeypatch,tmp_path):
    service,_,mid=fear_table(tmp_path,monkeypatch)
    e=service._load_session(mid).engine;a=e.state.actors[ME]
    assert not path_allowed(e,a,[a.position,Position(x=2,y=6),a.position])


def test_sight_is_checked_from_each_projected_step_without_mutating_state(monkeypatch,tmp_path):
    service,_,mid=fear_table(tmp_path,monkeypatch)
    e=service._load_session(mid).engine;a=e.state.actors[ME];source=e.state.actors[FOE]
    # A curtain blocks sight, but not movement. Crossing it reveals the source;
    # only subsequent steps toward the now-visible source are prohibited.
    e.grid.blocked.clear();e.grid.opaque={(5,y) for y in range(e.grid.height)}
    e._wall_base=(frozenset(),frozenset(e.grid.opaque),frozenset(),{})
    assert not can_see(e,a,source)
    beyond=a.model_copy(update={'position':Position(x=6,y=6)})
    assert can_see(e,beyond,source)
    before=e.state.model_dump(mode='json');events=len(e.events)
    assert path_allowed(e,a,[a.position,Position(x=4,y=6)])
    assert not path_allowed(e,a,[a.position,Position(x=4,y=6),Position(x=5,y=6),Position(x=6,y=6),Position(x=7,y=6)])
    assert e.state.model_dump(mode='json')==before and len(e.events)==events


def test_old_shared_helper_delegates_without_registering_a_candidate_filter():
    from combat.ext.frightened_movement import path_allowed as old_helper
    assert old_helper is path_allowed
    ext.effects()
    assert not any(fn.__module__=='combat.ext.frightened_movement' for fn in ext._HOOKS.get('candidate_allowed',[]))
