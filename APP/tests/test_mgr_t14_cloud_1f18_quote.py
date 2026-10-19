"""Round 1F18 regression for the Cloud Walker Sol review (liquid-edge quote).

A chargeable liquid edge must be quoted at the same price the move spends. Before
the fix the MOVE candidate was offered at 5 ft while the committed move spent 10 ft
(flight._step_cost and flight.reachable both add movement_costs.segment_surcharge,
but the ground walking search did not). The dry-edge control keeps 5 ft.
"""
from combat.gate2_runtime_models import Position
from tests.worker2_support import settle
from tests.test_mgr_t14_cloud_1f17 import _surface_game, A


def test_liquid_edge_quote_equals_the_movement_it_spends(tmp_path):
    surface = {'id': 'swim-edge', 'kind': 'water', 'cells': [[2, 6], [1, 6]], 'z': 0, 'capacity_lb': 0,
               'fragile': False, 'trigger': 'weight'}
    c, t, mid = _surface_game(tmp_path, [surface])
    engine = c._load_session(mid).engine
    before = engine.state.actors[A].movement_remaining_ft
    liquid = next(row for row in engine.legal_candidates()
                  if row.kind.value == 'MOVE' and row.destination == Position(x=2, y=6))
    quoted = liquid.movement_cost_ft
    settle(t, mid, liquid.candidate_id)
    engine = c._load_session(mid).engine
    spent = before - engine.state.actors[A].movement_remaining_ft
    assert quoted == spent, 'the menu quote must equal the movement the liquid edge spends'


def test_dry_edge_quote_is_one_plain_step(tmp_path):
    c, t, mid = _surface_game(tmp_path, [])
    engine = c._load_session(mid).engine
    dry = next(row for row in engine.legal_candidates()
               if row.kind.value == 'MOVE' and row.destination == Position(x=3, y=5))
    assert dry.movement_cost_ft == 5
