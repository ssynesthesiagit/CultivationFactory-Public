"""Portable movement menus must offer routes the persisted table can execute."""
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.portable_step_support import (
    intent_from_candidate, portable_step_fight, preview_commit, step_intent, step_placements,
)


def test_table_step_excludes_terrain_over_budget_and_occupied_destination(tmp_path):
    service, match_id, actor_id = portable_step_fight(tmp_path)
    engine = service._load_session(match_id).engine
    actor = engine.state.actors[actor_id]
    destination = Position(x=10, y=6)
    assert engine.grid.distance_ft(actor.position, destination) == 15
    _, cost = engine.grid.shortest_path(actor.position, destination,
        occupied_cells=engine._occupied_cells_except(actor.entity_id), footprint=engine._footprint(actor))
    assert cost == 20
    before = engine.state.model_dump(mode='json')
    context = service.decision(match_id)['context']
    _, steps = step_placements(engine, context)
    assert steps
    assert not any((row.destination.x, row.destination.y) in {(10, 6), (13, 5)} for row in steps)
    assert service._load_session(match_id).engine.state.model_dump(mode='json') == before


def test_table_step_uses_its_grant_after_ordinary_movement_and_survives_reload(tmp_path):
    service, match_id, actor_id = portable_step_fight(tmp_path)
    context = service.decision(match_id)['context']
    move = next(row for row in context['legal_candidates']
                if row['kind'] == 'MOVE' and row['movement_cost_ft'] == 30)
    preview_commit(service, match_id, intent_from_candidate(context, move))
    context = service.decision(match_id)['context']
    engine = service._load_session(match_id).engine
    actor = engine.state.actors[actor_id]
    assert actor.movement_remaining_ft == 0
    start, qi = actor.position, actor.resources['resource:core.qi']

    def reachable_neighbor(destination):
        if engine.grid.distance_ft(start, destination) != 5:
            return False
        return engine.grid.shortest_path(start, destination,
            occupied_cells=engine._occupied_cells_except(actor.entity_id),
            footprint=engine._footprint(actor), max_cost_ft=15) is not None

    # Use a simple reachable neighbor to isolate the separate grant from route filtering.
    root, steps = step_placements(engine, context)
    destination = next(row.destination for row in steps if reachable_neighbor(row.destination))
    preview_commit(service, match_id, step_intent(context, root, destination))
    reopened = CombatService(ROOT, tmp_path)
    actor = reopened._load_session(match_id).engine.state.actors[actor_id]
    assert actor.position == destination
    assert actor.movement_remaining_ft == 0
    assert actor.resources['resource:core.qi'] == qi - 1
    assert actor.bonus_action_available is False
    assert reopened.verify(match_id)['status'] == 'PASS'
    assert reopened.replay(match_id)['status'] == 'PASS'
