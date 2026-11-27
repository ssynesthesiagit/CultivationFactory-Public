"""Candidate admission at a raised eave, through real services and cold saves."""
import pytest

from combat import falling
from combat import flight, roof_movement
from combat.gate2_runtime_models import Position
from tests.test_walkable_roofs import (
    OWNER, cold, end_turn, gather, roof_fight, route,
)


def offered(combat, mid, destination, mode):
    return next((c for c in combat._load_session(mid).engine.legal_candidates()
                 if c.kind == 'MOVE' and c.destination == destination
                 and c.metadata.get('movement_mode', 'walk') == mode), None)


def commit_offered(combat, table, mid, candidate):
    assert candidate is not None, 'the legal route must be offered, not only accepted explicitly'
    route(combat, table, mid,
          [(p.x, p.y, p.z) for p in candidate.canonical_path],
          mode=candidate.metadata.get('movement_mode', 'walk'))


def test_flyer_reaches_raised_roof_and_flies_back_down_after_cold_reload(tmp_path):
    combat, table, mid = roof_fight(tmp_path, roof_height_ft=15)
    gather(combat, mid)
    destination = Position(x=5, y=3, z=3)
    commit_offered(combat, table, mid, offered(combat, mid, destination, 'fly'))
    combat, table, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == destination and falling.supported(session.engine, actor)
    end_turn(combat, mid)
    end_turn(combat, mid)
    gather(combat, mid)
    # Leave the eave before descending; a solid roof cannot be crossed vertically.
    ground = Position(x=3, y=3)
    candidate = offered(combat, mid, ground, 'fly')
    commit_offered(combat, table, mid, candidate)
    _, _, session = cold(combat, tmp_path, mid)
    assert session.engine.state.actors[OWNER].position == ground
    assert not any(e.payload.get('fall_distance_ft') for e in session.engine.events)


def test_climber_reaches_roof_above_wall_after_cold_reload(tmp_path):
    combat, table, mid = roof_fight(tmp_path, roof_height_ft=15, owner_start=(3, 2),
                                  owner_talents=('TAL_ATHLETICS_SPIDER_S_TOUCH',))
    destination = Position(x=4, y=2, z=3)
    commit_offered(combat, table, mid, offered(combat, mid, destination, 'climb'))
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == destination and falling.supported(session.engine, actor)
    assert not actor.climbing


def test_walking_cannot_gain_roof_height_through_an_open_door(tmp_path):
    combat, table, mid = roof_fight(tmp_path, roof_height_ft=15, owner_talents=())
    assert not any(c.kind == 'MOVE' and c.destination.z >= 3
                   for c in combat._load_session(mid).engine.legal_candidates())
    assert not any(c.kind == 'MOVE' and c.metadata.get('movement_mode', 'walk') == 'walk' and c.destination.z
                   for c in combat._load_session(mid).engine.legal_candidates())
    route(combat, table, mid, [(3, 3, 0), (4, 3, 0), (5, 3, 0)])
    _, _, session = cold(combat, tmp_path, mid)
    assert session.engine.state.actors[OWNER].position == Position(x=5, y=3)


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO', 'API_AUTO'])
def test_running_high_jump_offers_supported_roof_landing_and_cold_reloads(tmp_path, control):
    combat, table, mid = roof_fight(tmp_path, owner_start=(1, 2), owner_talents=(), owner_strength=24)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=control)
    destination = Position(x=4, y=2, z=2)
    candidate = offered(combat, mid, destination, 'jump')
    assert candidate is not None
    assert candidate.movement_cost_ft == 25
    # Admission must include AI seats, but the manual table-route API correctly
    # refuses to drive their turns. Preserve/reload that seat, then hand it to
    # the player to exercise the same offered path through the table API.
    if control != 'MANUAL':
        combat, table, _ = cold(combat, tmp_path, mid)
        assert offered(combat, mid, destination, 'jump') is not None
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
        candidate = offered(combat, mid, destination, 'jump')
    commit_offered(combat, table, mid, candidate)
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == destination and falling.supported(session.engine, actor)
    assert actor.current_hp == actor.maximum_hp


def test_flyer_can_exit_a_door_and_rise_past_the_eave_from_under_roof(tmp_path):
    combat, table, mid = roof_fight(tmp_path, roof_height_ft=15, owner_start=(5, 3))
    gather(combat, mid)
    destination = Position(x=4, y=3, z=3)
    candidate = offered(combat, mid, destination, 'fly')
    assert candidate is not None and candidate.movement_cost_ft <= 30
    assert any(p.x == 3 and p.z == 3 for p in candidate.canonical_path)
    commit_offered(combat, table, mid, candidate)
    _, _, session = cold(combat, tmp_path, mid)
    actor = session.engine.state.actors[OWNER]
    assert actor.position == destination and falling.supported(session.engine, actor)


def test_eave_grip_requires_a_real_wall_and_cannot_bridge_a_taller_gap():
    from tests.test_roof_movement import engine_at_wall
    engine, actor = engine_at_wall(height_ft=15, climb_speed=30)
    assert roof_movement.faces(engine, actor, Position(x=3, y=5, z=3))
    engine.grid.blocked.discard((4, 5))
    assert not roof_movement.faces(engine, actor, Position(x=3, y=5, z=3))
    engine, actor = engine_at_wall(height_ft=20, climb_speed=30)
    assert not roof_movement.faces(engine, actor, Position(x=3, y=5, z=3))


def test_hovering_flight_candidates_include_the_surface_and_air_above_it():
    from tests.test_roof_movement import engine_at_wall
    engine, actor = engine_at_wall(height_ft=15)
    actor.fly_speed_ft, actor.hover = 30, True
    destinations = flight.reachable(engine, actor, mode='fly')
    assert Position(x=4, y=5, z=3) in destinations
    assert Position(x=4, y=5, z=4) in destinations


def test_high_jump_landing_preserves_height_limit_and_has_only_one_landing_step():
    from tests.test_roof_movement import engine_at_wall
    engine, actor = engine_at_wall(height_ft=15)
    actor.strength_score = 24  # ten feet running, five feet standing
    actor.position = Position(x=1, y=5)
    approach = tuple(Position(x=x, y=5) for x in (1, 2, 3))
    ascent = tuple(Position(x=3, y=5, z=z) for z in (1, 2, 3))
    assert not flight.valid_jump(engine, actor, approach + ascent + (Position(x=4, y=5, z=3),))
    engine, actor = engine_at_wall(height_ft=10)
    actor.strength_score = 24
    actor.position = Position(x=1, y=5)
    path = approach + ascent[:2] + (Position(x=4, y=5, z=2),)
    assert flight.valid_jump(engine, actor, path)
    assert not flight.valid_jump(engine, actor, path + (Position(x=5, y=5, z=2),))


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO', 'API_AUTO'])
@pytest.mark.parametrize('chosen_mode', ['fly', 'jump', 'climb'])
def test_overlapping_roof_modes_remain_selectable_and_cold_reload(tmp_path, control, chosen_mode):
    from tests.test_walkable_roofs import WIND, perform
    combat, table, mid = roof_fight(
        tmp_path, owner_start=(1, 2), owner_strength=24,
        owner_talents=(WIND, 'TAL_ATHLETICS_SPIDER_S_TOUCH'))
    gather(combat, mid)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=control)
    destination = Position(x=4, y=2, z=2)

    def quotes(service):
        candidates = [c for c in service._load_session(mid).engine.legal_candidates()
                      if c.kind == 'MOVE' and c.destination == destination]
        by_mode = {c.metadata.get('movement_mode', 'walk'): c for c in candidates}
        assert {'fly', 'jump', 'climb'} <= by_mode.keys()
        assert by_mode['fly'].movement_cost_ft == 15
        assert by_mode['jump'].movement_cost_ft == 25
        assert len({c.candidate_id for c in candidates}) == len(candidates)
        assert candidates[0].movement_cost_ft == min(c.movement_cost_ft for c in candidates)
        return by_mode

    before = quotes(combat)
    combat, table, _ = cold(combat, tmp_path, mid)
    after = quotes(combat)
    assert {m: c.candidate_id for m, c in before.items()} == {
        m: c.candidate_id for m, c in after.items()}
    if control != 'MANUAL':
        # No model transport: verify AI admission, then execute the same native
        # candidate by ID on the player's seat (the table API is manual-only).
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    chosen = quotes(combat)[chosen_mode]
    session, executed = perform(combat, mid, lambda c: c.candidate_id == chosen.candidate_id)
    assert executed.canonical_path == chosen.canonical_path
    assert session.engine.state.actors[OWNER].position == destination
    _, _, loaded = cold(combat, tmp_path, mid)
    assert loaded.engine.state.actors[OWNER].position == destination


def test_table_commits_preserved_cheaper_flight_with_jump_available(tmp_path):
    combat, table, mid = roof_fight(tmp_path, owner_start=(1, 2), owner_strength=24)
    gather(combat, mid)
    destination = Position(x=4, y=2, z=2)
    candidate = offered(combat, mid, destination, 'fly')
    assert candidate is not None and candidate.movement_cost_ft == 15
    commit_offered(combat, table, mid, candidate)
    _, _, loaded = cold(combat, tmp_path, mid)
    assert loaded.engine.state.actors[OWNER].position == destination
