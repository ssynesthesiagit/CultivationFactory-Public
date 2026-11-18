"""Fear-aware search preserves equal-cost alternatives and longer legal detours."""
import pytest
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.voluntary_movement import edge_predicate, path_allowed
from tests.h1_support import ROOT, sheet
from tests.test_hunt33_frightened import ME, FOE
from tests.test_tabletop_hunt6 import on_hold, HOLD
from tests.test_lock2_persistence import act


@pytest.mark.parametrize('x,cost', [(4,20), (6,30)])
@pytest.mark.parametrize('has_flight', [False, True])
def test_table_offers_legal_alternative_at_real_cost_and_reloads(monkeypatch, tmp_path, x, cost, has_flight):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = {**combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], 'terrain_regions': []}
    bundles = [compile_character(sheet([]), actor_id=a) for a in (ME, FOE)]
    mid = combat._finish_factory_match(bundles, [ME,FOE], {ME:'team:a',FOE:'team:b'},
        {ME:{'x':3,'y':6},FOE:{'x':7,'y':6}}, arena, [ME], [FOE],
        control_modes={ME:'MANUAL',FOE:'MANUAL'}, match_seed='L11-FEAR-ROUTES',
        display_name='Fear route regression', maximum_rounds=5)['match_id']
    while table.state(mid)['menu']['actor_id'] != ME:
        assert act(table,mid,'end')['status'] == 'COMMITTED'
    def fear(engine):
        a = engine.state.actors[ME]
        a.movement_remaining_ft = cost
        engine._append_event('MOVEMENT_GRANTED','test:budget',actor_id=ME,payload={'remaining_ft':cost})
        engine._apply_condition(a,'condition:typed.frightened','test:fear',FOE,expires_on='UNTIL_REMOVED')
        if has_flight:
            from tests.test_lock10_flight_movement import grant
            grant(engine, a, speed=10, cannot_gain_altitude=1)
    on_hold(monkeypatch,fear)
    assert act(table,mid,HOLD)['status'] == 'COMMITTED'
    e = combat._load_session(mid).engine
    a = e.state.actors[ME]
    dest = Position(x=x,y=10)
    occupied = e._occupied_cells_except(ME,observed=True)
    kwargs = {'occupied_cells':occupied,'footprint':e._footprint(a)}
    naive = e.grid.shortest_path(a.position,dest,**kwargs)
    assert not path_allowed(e,a,naive[0])
    restricted = e.grid.shortest_path(a.position,dest,edge_allowed=edge_predicate(e,a),**kwargs)
    assert restricted[1] == cost and path_allowed(e,a,restricted[0])
    if x == 6:
        assert restricted[1] > naive[1]
        assert dest not in e.grid.reachable(a.position,movement_ft=cost-5,edge_allowed=edge_predicate(e,a),**kwargs)
    before = e.state.model_dump(mode='json')
    c = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination == dest)
    assert e.state.model_dump(mode='json') == before
    assert c.movement_cost_ft == cost and path_allowed(e,a,c.canonical_path)
    assert all(e.grid.distance_ft(p,e.state.actors[FOE].position) >= 20 for p in c.canonical_path)
    assert table.act(mid,c.candidate_id,c.decision_id,c.state_version,table.state(mid)['last_sequence'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT,tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ME].position == dest
    assert loaded.engine.state.actors[ME].movement_remaining_ft == 0
    ev = next(ev for ev in reversed(loaded.engine.events) if ev.event_type == 'MOVEMENT_COMMITTED')
    assert ev.payload['cost_ft'] == cost and not ev.payload['interrupted']
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
