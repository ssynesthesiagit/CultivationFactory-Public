"""Roofless Air Stunt remains usable by shared movement-budget consumers."""
from combat import falling, flight, roof_movement
from combat.gate2_runtime_models import Position
from combat.movement_routes import explicit_candidate
from tests.auto_worker1_support import LEFT, RIGHT, fight, reload, turn
from tests.test_auto98_chains_counter import COUNTER, attack, counter_prompts


def test_roofless_air_stunt_chain_counter_choice_and_reduction_cold_reload(tmp_path):
    combat, table, mid = fight(
        tmp_path, [COUNTER], left_save_dc=1,
        right_talents=['TAL_ATHLETICS_WALL_STUNT', 'TAL_ATHLETICS_AIR_STUNT'],
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}},
    )
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert not engine.grid.roof_surfaces
    path = (Position(x=4, y=6), Position(x=4, y=6, z=1))
    candidate = explicit_candidate(engine, RIGHT, path, 'climb')
    state = table.state(mid)
    answers = []
    for _ in range(8):
        result = table.commit_move_path(
            mid, candidate.candidate_id, candidate.decision_id, candidate.state_version,
            RIGHT, [p.model_dump(mode='json') for p in path],
            after=state['last_sequence'], movement_mode='climb', reactions=answers,
        )
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    actor = engine.state.actors[RIGHT]
    assert actor.position == path[-1] and actor.climbing
    assert roof_movement.can_hold(engine, actor)
    assert not falling.supported(engine, actor)
    assert flight.profile(engine, actor).speed_ft == 0
    assert actor.movement_remaining_ft == 20
    assert flight.budget(engine, actor).available_ft == 20
    asked = counter_prompts(attack(table, mid, 'withhold'))
    assert asked
    assert {o['id'] for o in asked[0]['choice']['options']} == {'pull', 'withhold'}
    engine = reload(combat, mid)
    actor = engine.state.actors[RIGHT]
    assert actor.position == path[-1] and roof_movement.can_hold(engine, actor)
    assert actor.movement_remaining_ft == flight.budget(engine, actor).available_ft == 15
    reductions = [e.payload['distance_ft'] for e in engine.events
                  if e.event_type == 'MOVEMENT_GRANTED'
                  and e.source_definition_id == COUNTER and e.actor_id == RIGHT]
    assert reductions == [-5]
