"""Portable movement menus must offer routes the persisted table can execute."""
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.test_c3d_p1_portable_live_combat import (
    ROOT, RUNTIME_PACKAGE, DYNAMIC_ACTOR_ID, _install_pointer, _catalog_payload,
    _manual_end_turn, _preview_commit, _intent_from_candidate,
)

SOURCE = 'action:fire.combustive_step'


def fight(tmp_path):
    _install_pointer(tmp_path, RUNTIME_PACKAGE)
    service = CombatService(ROOT, tmp_path)
    payload = _catalog_payload(service)
    for row in payload['participants']:
        row['placement'] = {'x': 13, 'y': 4 if row['actor_id'] == DYNAMIC_ACTOR_ID else 5}
    preflight = service.preflight_new_fight(payload)
    assert preflight['ready'], preflight['blockers']
    created = service.create_confirmed_fight({**payload, 'owner_confirmed': True,
        'preflight_commitment': preflight['preflight_commitment'], 'idempotency_key': 'lock25-step'})
    match_id = created['match_id']
    if created['state']['current_actor_id'] != DYNAMIC_ACTOR_ID:
        _manual_end_turn(service, match_id)
    return service, match_id


def test_table_step_excludes_terrain_over_budget_and_occupied_destination(tmp_path):
    service, match_id = fight(tmp_path)
    engine = service._load_session(match_id).engine
    actor = engine.state.actors[DYNAMIC_ACTOR_ID]
    destination = Position(x=10, y=6)
    assert engine.grid.distance_ft(actor.position, destination) == 15
    path, cost = engine.grid.shortest_path(actor.position, destination,
        occupied_cells=engine._occupied_cells_except(actor.entity_id), footprint=engine._footprint(actor))
    assert cost == 20
    before = engine.state.model_dump(mode='json')
    context = service.decision(match_id)['context']
    steps = [row for row in context['legal_candidates'] if row['source_definition_id'] == SOURCE]
    assert steps
    assert not any((row['destination']['x'], row['destination']['y']) in {(10, 6), (13, 5)} for row in steps)
    assert service._load_session(match_id).engine.state.model_dump(mode='json') == before


def test_table_step_uses_its_grant_after_ordinary_movement_and_survives_reload(tmp_path):
    service, match_id = fight(tmp_path)
    context = service.decision(match_id)['context']
    move = next(row for row in context['legal_candidates']
                if row['kind'] == 'MOVE' and row['movement_cost_ft'] == 30)
    _preview_commit(service, match_id, _intent_from_candidate(context, move))
    context = service.decision(match_id)['context']
    engine = service._load_session(match_id).engine
    actor = engine.state.actors[DYNAMIC_ACTOR_ID]
    assert actor.movement_remaining_ft == 0
    start, qi = actor.position, actor.resources['resource:core.qi']
    def reachable_neighbor(row):
        if row['source_definition_id'] != SOURCE:
            return False
        destination = Position(**row['destination'])
        if engine.grid.distance_ft(start, destination) != 5:
            return False
        return engine.grid.shortest_path(start, destination,
            occupied_cells=engine._occupied_cells_except(actor.entity_id),
            footprint=engine._footprint(actor), max_cost_ft=15) is not None
    # Also legal in the old menu: isolate the separate grant from route filtering.
    step = next(row for row in context['legal_candidates'] if reachable_neighbor(row))
    _preview_commit(service, match_id, _intent_from_candidate(context, step))
    reopened = CombatService(ROOT, tmp_path)
    actor = reopened._load_session(match_id).engine.state.actors[DYNAMIC_ACTOR_ID]
    assert actor.position == Position(**step['destination'])
    assert actor.movement_remaining_ft == 0
    assert actor.resources['resource:core.qi'] == qi - 1
    assert actor.bonus_action_available is False
    assert reopened.verify(match_id)['status'] == 'PASS'
    assert reopened.replay(match_id)['status'] == 'PASS'
