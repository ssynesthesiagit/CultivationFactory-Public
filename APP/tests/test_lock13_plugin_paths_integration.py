"""Chosen paths preserve flight geometry and payment in the combined engine."""
import pytest
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.granted_movement import Route
from combat.tabletop import TabletopMapStore
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT
from tests.test_lock10_flight_movement import grant
from tests.test_lock2_persistence import act


@pytest.mark.parametrize('kind', ['willing', 'granted', 'forced'])
def test_chosen_vertical_path_over_low_wall_commits_and_reloads(monkeypatch,tmp_path,kind):
    original = TabletopMapStore.save
    monkeypatch.setattr(TabletopMapStore, 'save', lambda store, definition: original(store, {
        **definition, 'walls':[{'shape':'rect','points':[[4,4],[5,5]],'height_ft':5}],
        'starts':{'team1':[[3,4],[1,1]],'team2':[[9,6]]}}))
    combat, table, mid = H.table_fight(tmp_path, [])
    before = combat._load_session(mid).engine.state.actors[H.LEFT].movement_remaining_ft
    def move(engine):
        actor = engine.state.actors[H.LEFT]
        grant(engine, actor, flight_hover=1)
        route = Route((actor.position, Position(x=3,y=4,z=1), Position(x=4,y=4,z=1)), 'fly')
        spent = engine.move_path(actor, route, 'test:chosen-path', kind=kind,
            feet=None if kind == 'willing' else 10, provokes=False,
            source_actor_id=H.RIGHT if kind == 'forced' else None)
        assert spent == 10
    H.on_hold(monkeypatch, move)
    assert act(table,mid,H.HOLD)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[H.LEFT]
    assert actor.position == Position(x=4,y=4,z=1)
    assert actor.movement_remaining_ft == before - (10 if kind == 'willing' else 0)
    event = next(ev for ev in loaded.engine.events if ev.event_type == 'MOVEMENT_COMMITTED' and ev.source_definition_id == 'test:chosen-path')
    assert event.payload['path'][-1]['z'] == 1
    assert event.payload.get('reaction',False) == (kind == 'granted')
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
